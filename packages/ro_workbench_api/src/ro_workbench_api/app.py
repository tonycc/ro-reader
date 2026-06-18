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
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ro_generator.generator import generate, preview_from_snapshot
from ro_generator.models import DocumentRequest, GenerationResult, ValidationMessage
from ro_generator.source_index import SourceIndex
from ro_generator.workbench_service import (
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
async def lifespan(_app: FastAPI):
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
        async def serve_index():
            return FileResponse(str(dist_path / "index.html"))

        app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="assets")

        @app.get("/favicon.svg")
        async def serve_favicon():
            return FileResponse(str(dist_path / "favicon.svg"))

        @app.get("/icons.svg")
        async def serve_icons():
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
            sid for sid, info in _sessions.items()
            if now - info.last_access > SESSION_TTL_SECONDS
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
                "source": {"sheet": loc.sheet, "row": loc.row, "field": loc.field, "is_computed": loc.is_computed},
            }
            for cell, loc in result.source_index
        ]
    else:
        payload["source_index"] = []
    return payload


def _msg_to_dict(m: ValidationMessage) -> dict[str, Any]:
    return asdict(m)


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
        raise HTTPException(400, detail={"code": "WORKBOOK_INSPECTION_FAILED", "message": str(errors)})

    session = _get_or_create_session(req.base_file)
    po_list = [
        {
            "po_no": p.po_no,
            "status": p.status,
            "sellers": list(p.sellers),
            "line_count": p.line_count,
            "invoice_nos": list(p.invoice_nos),
            "blocking_count": p.blocking_count,
        }
        for p in inspection.po_list
    ]
    return {"ok": True, "session_id": session.session_id, "po_list": po_list}


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
        raise HTTPException(400, detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"})
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
        raise HTTPException(400, detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"})

    doc = req.document.upper()
    request = DocumentRequest(
        base_file=req.base_file,
        po_no=po_no,
        documents=(doc,),  # type: ignore[arg-type]
        seller=req.seller,
        invoice_no=req.invoice_no,
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
        raise HTTPException(400, detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"})

    doc = req.document.upper() if req.document else "INVOICE"
    request = DocumentRequest(
        base_file=req.base_file,
        po_no=po_no,
        documents=(doc,),  # type: ignore[arg-type]
        seller=req.seller,
        invoice_no=req.invoice_no,
        output_dir=session.temp_dir,
    )

    # 使用缓存快照路径
    cache = get_cache_manager()
    snapshot = cache.get_snapshot(req.base_file)
    result = preview_from_snapshot(snapshot, request)

    # Serialize DocumentPreview
    preview_data: dict[str, Any] | None = None
    if result.preview is not None:
        p = result.preview
        preview_data = {
            "document_type": getattr(p, "document_type", ""),
            "title": getattr(p, "title", ""),
            "seller": getattr(p, "seller", ""),
            "buyer": getattr(p, "buyer", ""),
            "po_no": getattr(p, "po_no", ""),
            "pi_no": getattr(p, "pi_no", None),
            "invoice_no": getattr(p, "invoice_no", None),
            "ship_to": getattr(p, "ship_to", None),
            "seller_info": getattr(p, "seller_info", []),
            "to_label": getattr(p, "to_label", ""),
            "terms": getattr(p, "terms", {}),
            "column_labels": getattr(p, "column_labels", []),
            "lines": getattr(p, "lines", []),
            "totals": getattr(p, "totals", {}),
            "notes": getattr(p, "notes", []),
            "source_entries": getattr(p, "source_entries", []),
            "layout": getattr(p, "layout", {}),
            "resolved_values": getattr(p, "resolved_values", {}),
        }

    return {
        "status": result.status,
        "preview": preview_data,
        "errors": [_msg_to_dict(m) for m in result.errors],
        "warnings": [_msg_to_dict(m) for m in result.warnings],
        "missing_inputs": list(result.missing_inputs),
        "options": {k: list(v) for k, v in result.options.items()},
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
        raise HTTPException(400, detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"})

    doc = req.document.upper() if req.document else "INVOICE"
    documents = ("INVOICE", "PL") if doc in {"INVOICE_PL", "INVOICE&PL"} else (doc,)
    request = DocumentRequest(
        base_file=req.base_file,
        po_no=po_no,
        documents=documents,  # type: ignore[arg-type]
        seller=req.seller,
        invoice_no=req.invoice_no,
        output_format="zip",
        output_dir=session.temp_dir,
    )
    result = generate(request)
    return _result_to_dict(result)


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
        raise HTTPException(400, detail={"code": "INVALID_SESSION", "message": f"session {sid!r} 无效或已过期"})

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
