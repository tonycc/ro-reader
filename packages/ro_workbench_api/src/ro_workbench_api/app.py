"""工作台后端 API：ro_generator 核心包的 FastAPI 薄包装层。

所有业务逻辑在 ro_generator 中，此层只负责：
- HTTP 协议（JSON 序列化 / 路由 / CORS）
- 请求到 DocumentRequest 的转换
- GenerationResult 到 JSON 响应的转换
- Session 管理（临时目录、文件生命周期）

禁止：在本层写任何校验、价格计算、业务判断。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ro_generator.document_preview import DocumentPreview
from ro_generator.generator import (
    export_invoice_group_from_snapshot,
    generate,
    preview_from_snapshot,
    preview_invoice_group_from_snapshot,
)
from ro_generator.invoice_inspection import (
    InvoiceGroupInspection,
    inspect_invoice_group_from_snapshot,
)
from ro_generator.models import (
    DocumentRequest,
    DocumentType,
    GenerationResult,
    ValidationMessage,
)
from ro_generator.source_index import SourceIndex
from ro_generator.workbench_service import (
    ExportDocumentGroup,
    export_document_groups,
    get_customer_po_data,
    get_po_data,
    get_po_issues,
    inspect_file_path,
    inspect_workbook,
)
from ro_generator.workbook_cache import get_cache_manager
from ro_generator.workbook_editor import edit_workbook_cell

_cleanup_timer: threading.Timer | None = None
_cleanup_stopped = threading.Event()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    _cleanup_stopped.clear()
    _schedule_cleanup_timer()
    try:
        yield
    finally:
        _cleanup_stopped.set()
        if _cleanup_timer is not None:
            _cleanup_timer.cancel()


# 生产模式（非开发模式）下 serve 前端静态资源
FRONTEND_DIST = os.environ.get("RO_WORKBENCH_FRONTEND_DIST", "")

app = FastAPI(title="RO Workbench API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:*", "http://localhost:*"] if FRONTEND_DIST else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
if FRONTEND_DIST:
    from fastapi.staticfiles import StaticFiles

    dist_path = Path(FRONTEND_DIST)
    if dist_path.exists():

        @app.get("/")
        async def serve_index() -> FileResponse:
            return FileResponse(str(dist_path / "index.html"))

        app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="assets")

        @app.get("/favicon.svg")
        async def serve_favicon() -> FileResponse:
            return FileResponse(str(dist_path / "favicon.svg"))

        @app.get("/icons.svg")
        async def serve_icons() -> FileResponse:
            return FileResponse(str(dist_path / "icons.svg"))


# —————————————————————————————————————
# Session 管理
# —————————————————————————————————————

SESSION_TTL_SECONDS = 3600  # 1 小时无活动后清理


@dataclass
class SessionInfo:
    session_id: str
    base_file: str
    temp_dir: str
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)


_sessions: dict[str, SessionInfo] = {}
_lock = threading.Lock()


def _get_or_create_session(base_file: str) -> SessionInfo:
    """复用已有 session（同 base_file），或创建新的。"""
    with _lock:
        # 查找同 base_file 的现有 session
        for info in list(_sessions.values()):
            if info.base_file == base_file:
                info.last_access = time.time()
                return info
        # 创建新 session
        sid = uuid.uuid4().hex[:12]
        tmp = tempfile.mkdtemp(prefix=f"ro-session-{sid}-")
        info = SessionInfo(session_id=sid, base_file=base_file, temp_dir=tmp)
        _sessions[sid] = info
        return info


def _get_session(session_id: str) -> SessionInfo | None:
    with _lock:
        info = _sessions.get(session_id)
        if info:
            info.last_access = time.time()
        return info


def _cleanup_expired_sessions() -> None:
    """清理过期 session 的临时目录和过期缓存。"""
    now = time.time()
    with _lock:
        expired = [
            sid for sid, info in _sessions.items() if now - info.last_access > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            info = _sessions.pop(sid)
            with suppress(Exception):
                shutil.rmtree(info.temp_dir, ignore_errors=True)
    get_cache_manager().clear_expired()


def _schedule_cleanup_timer() -> None:
    """每 5 分钟运行一次过期清理。"""
    global _cleanup_timer
    if _cleanup_stopped.is_set():
        return
    _cleanup_expired_sessions()
    timer = threading.Timer(300, _schedule_cleanup_timer)
    timer.daemon = True
    _cleanup_timer = timer
    timer.start()


# —————————————————————————————————————
# Request / Response 模型
# —————————————————————————————————————


class OpenSessionRequest(BaseModel):
    base_file: str


class OpenSessionResponse(BaseModel):
    ok: bool
    session_id: str = ""
    po_list: list[dict[str, object]] = []
    errors: list[dict[str, object]] | None = None


class DryRunRequest(BaseModel):
    base_file: str
    po_no: str
    seller: str
    invoice_no: str | None = None
    document: str = "INVOICE"
    documents: list[str] | None = None


class InvoicePreviewRequest(BaseModel):
    seller: str
    document: Literal["INVOICE", "PL"]


class InvoiceExportRequest(BaseModel):
    seller: str
    documents: list[Literal["INVOICE", "PL"]]


class ExportGroupRequest(BaseModel):
    seller: str
    documents: list[str]
    invoice_no: str | None = None


class BatchExportRequest(BaseModel):
    base_file: str
    po_no: str
    groups: list[ExportGroupRequest]


class EditFieldRequest(BaseModel):
    base_file: str
    sheet: str
    row: int
    field: str
    value: object


class EditFieldResponse(BaseModel):
    ok: bool
    message: str = ""


class SessionCloseRequest(BaseModel):
    session_id: str


# —————————————————————————————————————
# 辅助
# —————————————————————————————————————


def _result_to_dict(result: GenerationResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status,
        "summary": result.summary,
        "files": list(result.files),
        "output_file": result.output_file,
        "errors": [_msg_to_dict(m) for m in result.errors],
        "warnings": [_msg_to_dict(m) for m in result.warnings],
        "missing_inputs": list(result.missing_inputs),
        "options": {k: list(v) for k, v in result.options.items()},
    }
    if isinstance(result.source_index, SourceIndex):
        payload["source_index"] = [
            {
                "doc_cell": cell,
                "source": {
                    "sheet": loc.sheet,
                    "row": loc.row,
                    "field": loc.field,
                    "is_computed": loc.is_computed,
                },
            }
            for cell, loc in result.source_index
        ]
    else:
        payload["source_index"] = []
    return payload


def _msg_to_dict(m: ValidationMessage) -> dict[str, Any]:
    return asdict(m)


def _invoice_inspection_to_dict(result: InvoiceGroupInspection) -> dict[str, Any]:
    return {
        "invoice_group_key": result.invoice_group_key,
        "display_invoice_no": result.display_invoice_no,
        "po_nos": list(result.po_nos),
        "line_count": len(result.rows),
        "blocking_count": len(result.blocking_errors),
        "warnings_count": len(result.warnings),
        "rows": [
            {
                **asdict(row),
                "ship_qty": float(row.ship_qty),
                "sellers": list(row.sellers),
            }
            for row in result.rows
        ],
        "blocking_errors": [_msg_to_dict(message) for message in result.blocking_errors],
        "warnings": [_msg_to_dict(message) for message in result.warnings],
    }


def _normalize_document(raw: str | None) -> DocumentType:
    doc = (raw or "INVOICE").upper()
    if doc not in {"PI", "PO", "INVOICE", "PL"}:
        raise HTTPException(
            400,
            detail={"code": "INVALID_DOCUMENT", "message": f"不支持的单据类型: {doc}"},
        )
    return cast(DocumentType, doc)


def _normalize_documents(raw_documents: Iterable[str | None]) -> tuple[DocumentType, ...]:
    documents: list[DocumentType] = []
    for raw in raw_documents:
        doc = (raw or "INVOICE").upper()
        if doc in {"INVOICE_PL", "INVOICE&PL"}:
            documents.extend(["INVOICE", "PL"])
            continue
        documents.append(_normalize_document(doc))
    return tuple(documents)


def _preview_options_to_dict(options: Mapping[str, object]) -> dict[str, list[dict[str, str]]]:
    payload: dict[str, list[dict[str, str]]] = {}
    for key, value in options.items():
        if not isinstance(value, Iterable):
            continue
        items: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, str):
                items.append({"value": item, "label": item})
                continue
            if not isinstance(item, dict):
                continue
            raw_value = item.get("value")
            raw_label = item.get("label")
            if isinstance(raw_value, str) and isinstance(raw_label, str):
                items.append({"value": raw_value, "label": raw_label})
        payload[key] = items
    return payload


def _document_preview_to_dict(preview: DocumentPreview | None) -> dict[str, Any] | None:
    if preview is None:
        return None
    return {
        "document_type": preview.document_type,
        "title": preview.title,
        "seller": preview.seller,
        "buyer": preview.buyer,
        "po_no": preview.po_no,
        "pi_no": preview.pi_no,
        "invoice_no": preview.invoice_no,
        "ship_to": preview.ship_to,
        "seller_info": preview.seller_info,
        "to_label": preview.to_label,
        "terms": preview.terms,
        "column_labels": preview.column_labels,
        "lines": preview.lines,
        "totals": preview.totals,
        "notes": preview.notes,
        "source_entries": preview.source_entries,
        "layout": preview.layout,
        "resolved_values": preview.resolved_values,
    }


def _build_document_request(
    *,
    req: DryRunRequest,
    po_no: str,
    output_dir: str,
    documents: tuple[DocumentType, ...],
    output_format: Literal["xlsx", "zip"] = "xlsx",
) -> DocumentRequest:
    return DocumentRequest(
        base_file=req.base_file,
        po_no=po_no,
        documents=documents,
        seller=req.seller,
        invoice_no=req.invoice_no,
        output_format=output_format,
        output_dir=output_dir,
    )


# —————————————————————————————————————
# 端点
# —————————————————————————————————————


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class CheckPathRequest(BaseModel):
    path: str


@app.post("/api/check-path")
def check_path(req: CheckPathRequest) -> dict[str, object]:
    """检查文件路径是否有效。"""
    result = inspect_file_path(req.path)
    if result.ok:
        return {"ok": True, "sheets": list(result.sheets), "size": result.size}
    return {"ok": False, "error": result.error}


@app.post("/api/session/open")
def open_session(req: OpenSessionRequest) -> dict[str, Any]:
    """打开 base 文件，返回 PO 列表 + session_id。"""
    inspection = inspect_workbook(req.base_file)
    if not inspection.ok:
        errors = [_msg_to_dict(m) for m in inspection.errors]
        raise HTTPException(
            400, detail={"code": "WORKBOOK_INSPECTION_FAILED", "message": str(errors)}
        )

    session = _get_or_create_session(req.base_file)
    po_list = [
        {
            "po_no": p.po_no,
            "status": p.status,
            "sellers": list(p.sellers),
            "line_count": p.line_count,
            "invoice_nos": list(p.invoice_nos),
            "invoice_options_by_seller": {
                seller: list(options) for seller, options in p.invoice_options_by_seller.items()
            },
            "exportable_documents_by_seller": {
                seller: list(documents)
                for seller, documents in p.exportable_documents_by_seller.items()
            },
            "blocking_count": p.blocking_count,
        }
        for p in inspection.po_list
    ]
    return {"ok": True, "session_id": session.session_id, "po_list": po_list}


@app.get("/api/invoices")
def get_invoice_groups(
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    snapshot = get_cache_manager().get_snapshot(session.base_file)
    return {"invoices": [asdict(item) for item in snapshot.invoice_summary]}


@app.get("/api/invoice/{invoice_group_key}/inspection")
def inspect_invoice_group(
    invoice_group_key: str,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    snapshot = get_cache_manager().get_snapshot(session.base_file)
    result = inspect_invoice_group_from_snapshot(snapshot, invoice_group_key)
    return _invoice_inspection_to_dict(result)


@app.post("/api/invoice/{invoice_group_key}/preview")
def preview_invoice_group(
    invoice_group_key: str,
    req: InvoicePreviewRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    snapshot = get_cache_manager().get_snapshot(session.base_file)
    result = preview_invoice_group_from_snapshot(
        snapshot,
        invoice_group_key,
        seller=req.seller,
        document=req.document,
    )
    summary = next(
        (item for item in snapshot.invoice_summary if item.invoice_group_key == invoice_group_key),
        None,
    )
    return {
        "status": result.status,
        "invoice_group_key": invoice_group_key,
        "display_invoice_no": summary.display_invoice_no if summary else "",
        "seller_invoice_no": (summary.seller_invoice_numbers.get(req.seller) if summary else None),
        "po_nos": list(summary.po_nos) if summary else [],
        "preview": _document_preview_to_dict(result.preview),
        "errors": [_msg_to_dict(message) for message in result.errors],
        "warnings": [_msg_to_dict(message) for message in result.warnings],
        "missing_inputs": list(result.missing_inputs),
        "options": _preview_options_to_dict(result.options),
    }


@app.post("/api/invoice/{invoice_group_key}/export")
def export_invoice_group(
    invoice_group_key: str,
    req: InvoiceExportRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    snapshot = get_cache_manager().get_snapshot(session.base_file)
    result = export_invoice_group_from_snapshot(
        snapshot,
        invoice_group_key,
        seller=req.seller,
        documents=tuple(req.documents),
        output_dir=session.temp_dir,
    )
    return _result_to_dict(result)


@app.get("/api/po/{po_no}")
def get_po_data_endpoint(po_no: str, base_file: str = Query(...)) -> dict[str, Any]:
    """返回 PO 行数据视图（grid 数据）。复用缓存快照。"""
    return get_po_data(base_file, po_no)


@app.get("/api/po/{po_no}/customer-po")
def get_customer_po_endpoint(po_no: str, base_file: str = Query(...)) -> dict[str, Any]:
    """返回指定 PO 号在客户PO sheet 中的对应行数据。"""
    return get_customer_po_data(base_file, po_no)


@app.get("/api/po/{po_no}/issues")
def get_po_issues_endpoint(
    po_no: str,
    base_file: str = Query(...),
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    """返回指定 PO 的阻断原因和警告明细。"""
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    return get_po_issues(base_file, po_no)


@app.post("/api/po/{po_no}/dry-run")
def dry_run(
    po_no: str,
    req: DryRunRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    """装配预览，返回数据摘要 + source_index。

    generate() 的 summary 已包含 table_start_row / table_label_row / style，
    无需再访问 mapping 私有函数。
    """
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )

    request = _build_document_request(
        req=req,
        po_no=po_no,
        documents=(_normalize_document(req.document),),
        output_dir=session.temp_dir,
    )
    result = generate(request)
    payload = _result_to_dict(result)
    style = payload.get("summary", {}).pop("style", None)
    if style:
        payload["style"] = style
    return payload


@app.post("/api/po/{po_no}/preview")
def preview_document(
    po_no: str,
    req: DryRunRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    """预览单据内容，返回结构化 DocumentModel + 模板固定内容。

    复用 WorkbookSnapshot 缓存，不读 Excel。
    不调用 Excel renderer，不生成 .xlsx。
    """
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )

    request = _build_document_request(
        req=req,
        po_no=po_no,
        documents=(_normalize_document(req.document),),
        output_dir=session.temp_dir,
    )

    # 使用缓存快照路径
    cache = get_cache_manager()
    snapshot = cache.get_snapshot(req.base_file)
    result = preview_from_snapshot(snapshot, request)

    preview_data: dict[str, Any] | None = None
    if result.preview is not None:
        p: DocumentPreview = result.preview
        preview_data = {
            "document_type": p.document_type,
            "title": p.title,
            "seller": p.seller,
            "buyer": p.buyer,
            "po_no": p.po_no,
            "pi_no": p.pi_no,
            "invoice_no": p.invoice_no,
            "ship_to": p.ship_to,
            "seller_info": p.seller_info,
            "to_label": p.to_label,
            "terms": p.terms,
            "column_labels": p.column_labels,
            "lines": p.lines,
            "totals": p.totals,
            "notes": p.notes,
            "source_entries": p.source_entries,
            "layout": p.layout,
            "resolved_values": p.resolved_values,
        }

    return {
        "status": result.status,
        "preview": preview_data,
        "errors": [_msg_to_dict(m) for m in result.errors],
        "warnings": [_msg_to_dict(m) for m in result.warnings],
        "missing_inputs": list(result.missing_inputs),
        "options": _preview_options_to_dict(result.options),
    }


@app.post("/api/po/{po_no}/edit")
def edit_field(po_no: str, req: EditFieldRequest) -> EditFieldResponse:
    """接受字段编辑，写回 base 文件。

    写回成功后自动失效缓存，确保下次读取反映最新内容。
    """
    result = edit_workbook_cell(
        base_file=req.base_file,
        sheet=req.sheet,
        row=req.row,
        field=req.field,
        value=req.value,
    )
    if result.ok:
        get_cache_manager().invalidate(req.base_file)
    return EditFieldResponse(ok=result.ok, message=result.message)


@app.post("/api/po/{po_no}/export")
def export_documents(
    po_no: str,
    req: DryRunRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    """执行真实导出，返回生成的文件。

    产物写入 session 临时目录，由 session 生命周期管理。
    """
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )

    documents = _export_documents_from_request(req)
    request = _build_document_request(
        req=req,
        po_no=po_no,
        documents=documents,
        output_dir=session.temp_dir,
        output_format="zip",
    )
    result = generate(request)
    return _result_to_dict(result)


@app.post("/api/po/{po_no}/export-batch")
def export_document_batch(
    po_no: str,
    req: BatchExportRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    """执行工作台导出确认页批量导出，返回单个 ZIP 文件。"""
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )

    groups = tuple(
        ExportDocumentGroup(
            seller=group.seller,
            documents=_normalize_documents(group.documents),
            invoice_no=group.invoice_no,
        )
        for group in req.groups
    )
    result = export_document_groups(
        base_file=req.base_file,
        po_no=po_no,
        output_dir=session.temp_dir,
        groups=groups,
    )
    return _result_to_dict(result)


def _export_documents_from_request(req: DryRunRequest) -> tuple[DocumentType, ...]:
    raw_documents = req.documents if req.documents is not None else [req.document]
    return _normalize_documents(raw_documents)


@app.get("/api/download")
def download_file(
    path: str = Query(...),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
    session_id: str | None = Query(None, alias="session_id"),
) -> FileResponse:
    """下载 session 内的临时文件。

    接受 Header (X-Session-Id) 或 Query (?session_id=) 两种方式传 session。
    """
    sid = x_session_id or session_id
    if sid is None:
        raise HTTPException(400, detail="缺少 session_id（Header 或 Query 参数）")

    session = _get_session(sid)
    if session is None:
        raise HTTPException(
            400, detail={"code": "INVALID_SESSION", "message": f"session {sid!r} 无效或已过期"}
        )

    p = Path(path).resolve()
    allowed = Path(session.temp_dir).resolve()
    try:
        p.relative_to(allowed)
    except ValueError as exc:
        raise HTTPException(403, detail="路径不在当前 session 范围内") from exc

    if not p.exists():
        raise HTTPException(404, detail=f"file not found: {path}")
    media_type = (
        "application/zip"
        if p.suffix.lower() == ".zip"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(str(p), media_type=media_type)


@app.post("/api/session/close")
def close_session(req: SessionCloseRequest) -> dict[str, str]:
    """关闭 session 并清理临时目录。"""
    with _lock:
        info = _sessions.pop(req.session_id, None)
    if info:
        with suppress(Exception):
            shutil.rmtree(info.temp_dir, ignore_errors=True)
        return {"status": "closed"}
    return {"status": "not_found"}


def main() -> None:
    """开发服务器入口：`uv run api` 一键启动。"""
    import uvicorn

    uvicorn.run(
        "ro_workbench_api.app:app",
        host="127.0.0.1",
        port=54321,
        reload=True,
    )
