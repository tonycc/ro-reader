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
from ro_generator.errors import ProfileNotFoundError, WorkbookOpenError
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
from ro_generator.profiles import GenerationContext
from ro_generator.source_index import SourceIndex
from ro_generator.workbench_service import (
    ExportDocumentGroup,
    export_document_groups,
    export_invoice_document_groups,
    get_customer_po_data,
    get_po_data,
    get_po_issues,
    inspect_file_path,
    inspect_workbook,
)
from ro_generator.workbook_cache import get_cache_manager
from ro_generator.workbook_editor import edit_workbook_cell
from ro_generator.workbook_snapshot import (
    BuildSnapshotError,
    WorkbookSnapshot,
    build_workbook_snapshot,
)

from ro_workbench_api.session_manager import (
    SessionActivation,
    SessionInactiveError,
    SessionManager,
    SessionManagerError,
    WorkspaceActivationError,
)
from ro_workbench_api.session_manager import (
    SessionInfo as ManagedSessionInfo,
)
from ro_workbench_api.workspace_store import (
    CustomerWorkspace,
    WorkspaceStore,
    WorkspaceStoreError,
)

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

app = FastAPI(title="RO Workbench API", version="1.1.0", lifespan=lifespan)
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
    workspace_id: str = ""
    profile_id: str = "ro"
    state: Literal["active", "draining"] = "active"
    drain_until: float | None = None
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)


_sessions: dict[str, SessionInfo] = {}
_lock = threading.Lock()

# Workspace API 的运行时对象按配置目录惰性创建。这样测试和便携模式可以在进程内通过
# RO_WORKBENCH_CONFIG_DIR 注入隔离目录；旧 legacy session 仍使用上面的兼容字典。
_workspace_store: WorkspaceStore | None = None
_workspace_session_manager: SessionManager | None = None
_workspace_runtime_key: str | None = None
_workspace_runtime_lock = threading.Lock()


def _workspace_runtime() -> tuple[WorkspaceStore, SessionManager]:
    global _workspace_store, _workspace_session_manager, _workspace_runtime_key
    config_key = os.environ.get("RO_WORKBENCH_CONFIG_DIR") or "<default>"
    with _workspace_runtime_lock:
        if (
            _workspace_store is None
            or _workspace_session_manager is None
            or _workspace_runtime_key != config_key
        ):
            _workspace_store = WorkspaceStore()
            _workspace_session_manager = SessionManager(_workspace_store)
            _workspace_runtime_key = config_key
        return _workspace_store, _workspace_session_manager


def _reset_workspace_runtime() -> None:
    """测试或启动器重载时丢弃当前进程内 workspace runtime。"""

    global _workspace_store, _workspace_session_manager, _workspace_runtime_key
    with _workspace_runtime_lock:
        if _workspace_session_manager is not None:
            _workspace_session_manager.cleanup(now=float("inf"))
        _workspace_store = None
        _workspace_session_manager = None
        _workspace_runtime_key = None


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


def _get_session(
    session_id: str,
    *,
    allow_draining: bool = False,
) -> SessionInfo | ManagedSessionInfo | None:
    with _lock:
        info = _sessions.get(session_id)
        if info:
            info.last_access = time.time()
            return info
    try:
        _store, manager = _workspace_runtime()
        return manager.get_session(session_id, allow_draining=allow_draining)
    except SessionInactiveError:
        return None


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
    if _workspace_session_manager is not None:
        _workspace_session_manager.cleanup(now=now)
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
    output_format: Literal["xlsx", "pdf"] = "xlsx"


class InvoicePreviewRequest(BaseModel):
    seller: str
    document: Literal["INVOICE", "PL", "CI", "RO_PL"]


class InvoiceExportRequest(BaseModel):
    seller: str
    documents: list[Literal["INVOICE", "PL", "CI", "RO_PL"]]
    output_format: Literal["xlsx", "pdf"] = "xlsx"


class InvoiceBatchExportRequest(BaseModel):
    groups: list[ExportGroupRequest]
    output_formats: list[Literal["xlsx", "pdf"]] = ["xlsx"]


class ExportGroupRequest(BaseModel):
    seller: str
    documents: list[str]
    invoice_no: str | None = None


class BatchExportRequest(BaseModel):
    base_file: str
    po_no: str
    groups: list[ExportGroupRequest]
    output_formats: list[Literal["xlsx", "pdf"]] = ["xlsx"]


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


class WorkspaceInputRequest(BaseModel):
    display_name: str
    profile_id: str
    base_file: str


class WorkspaceUpdateRequest(BaseModel):
    display_name: str
    profile_id: str
    base_file: str


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
    if doc not in {"PI", "PO", "INVOICE", "PL", "CI", "RO_PL"}:
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
        if doc in {"CI_PL"}:
            documents.extend(["CI", "RO_PL"])
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
        "header_labels": preview.header_labels,
        "column_labels": preview.column_labels,
        "column_header_rows": preview.column_header_rows,
        "lines": preview.lines,
        "cost_breakdown_column_labels": preview.cost_breakdown_column_labels,
        "cost_breakdown": preview.cost_breakdown,
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
    output_format: Literal["xlsx", "zip", "pdf"] = "xlsx",
    base_file: str | None = None,
) -> DocumentRequest:
    return DocumentRequest(
        base_file=base_file or req.base_file,
        po_no=po_no,
        documents=documents,
        seller=req.seller,
        invoice_no=req.invoice_no,
        output_format=output_format,
        output_dir=output_dir,
    )


def _workspace_error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else "WORKSPACE_ERROR"


def _workspace_error_message(error: BaseException) -> str:
    message = getattr(error, "message", None)
    return message if isinstance(message, str) else str(error)


def _workspace_http_error(error: BaseException) -> HTTPException:
    code = _workspace_error_code(error)
    status = 400
    if code in {"WORKSPACE_NOT_FOUND", "PROFILE_NOT_FOUND"}:
        status = 404
    elif code in {
        "WORKSPACE_CURRENT_DELETE_FORBIDDEN",
        "WORKSPACE_ACTIVATION_IN_PROGRESS",
        "WORKSPACE_ACTIVATION_REQUIRED",
    }:
        status = 409
    return HTTPException(status, detail={"code": code, "message": _workspace_error_message(error)})


def _profile_summary(profile: object) -> dict[str, object]:
    profile_id = getattr(profile, "profile_id", "")
    descriptions = {
        "ro": "Rather Outdoors 单据流程",
        "pf": "PF 单据流程（含 MOQ 与整箱提醒）",
    }
    return {
        "id": profile_id,
        "display_name": getattr(profile, "display_name", profile_id),
        "version": getattr(profile, "version", ""),
        "available": True,
        "description": descriptions.get(profile_id),
    }


def _profile_summaries(store: WorkspaceStore) -> list[dict[str, object]]:
    return [_profile_summary(profile) for profile in store.profile_registry.list()]


def _base_file_name(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or path


def _same_base_path(left: str, right: str) -> bool:
    return (
        Path(left).expanduser().absolute().resolve()
        == Path(right).expanduser().absolute().resolve()
    )


def _workspace_dict(
    workspace: CustomerWorkspace,
    store: WorkspaceStore,
    *,
    status: str = "unchecked",
    status_message: str | None = None,
) -> dict[str, object]:
    try:
        profile_name = store.profile_registry.get(workspace.profile_id).display_name
    except ProfileNotFoundError:
        profile_name = workspace.profile_id
    return {
        "id": workspace.id,
        "display_name": workspace.display_name,
        "profile_id": workspace.profile_id,
        "profile_name": profile_name,
        "base_file": workspace.base_file,
        "base_file_name": _base_file_name(workspace.base_file),
        "status": status,
        "status_message": status_message,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "last_opened_at": workspace.last_opened_at,
    }


def _session_matches_workspace(
    session: ManagedSessionInfo,
    workspace: CustomerWorkspace,
) -> bool:
    """确认 active session 绑定的不可变身份仍与当前配置一致。

    workspace_id 本身保持稳定，编辑当前工作区后不能只比较 ID；否则 bootstrap
    会把旧 base/profile 的 snapshot 当成新配置返回，形成“配置和 session 身份
    分裂”的半切换状态。
    """

    return (
        session.workspace_id == workspace.id
        and session.profile_id == workspace.profile_id
        and _same_base_path(session.base_file, workspace.base_file)
    )


def _validate_workspace_path(
    profile_id: str,
    base_file: str,
    store: WorkspaceStore,
) -> tuple[str, str]:
    """执行一次不落盘的 Profile/base 校验，返回前端稳定状态和说明。"""

    try:
        profile = store.profile_registry.get(profile_id)
    except ProfileNotFoundError:
        return "profile_not_found", f"未知 Customer Profile：{profile_id}"

    path = Path(base_file).expanduser().absolute()
    try:
        path.stat()
    except FileNotFoundError:
        return "file_missing", f"找不到 base 文件：{path}"
    except PermissionError:
        return "permission_denied", f"无权读取 base 文件：{path}"
    if not path.is_file():
        return "file_missing", f"base 路径不是文件：{path}"
    try:
        with path.open("rb") as file:
            file.read(1)
        build_workbook_snapshot(
            str(path), context=GenerationContext(profile=profile, base_file=path)
        )
    except PermissionError:
        return "permission_denied", f"无权读取 base 文件：{path}"
    except (BuildSnapshotError, WorkbookOpenError, OSError) as exc:
        return "schema_mismatch", str(exc)
    return "ready", "本地 base 文件已通过检测"


def _workspace_input_payload(req: WorkspaceInputRequest) -> tuple[str, str, str]:
    display_name = req.display_name.strip()
    profile_id = req.profile_id.strip()
    base_file = req.base_file.strip()
    if not display_name:
        raise HTTPException(
            400,
            detail={"code": "WORKSPACE_NAME_REQUIRED", "message": "请输入工作区名称"},
        )
    if not profile_id:
        raise HTTPException(400, detail={"code": "PROFILE_REQUIRED", "message": "请选择 Profile"})
    if not base_file:
        raise HTTPException(
            400,
            detail={"code": "WORKSPACE_FILE_REQUIRED", "message": "请输入 base 文件路径"},
        )
    return display_name, profile_id, base_file


def _validation_response(status: str, message: str, base_file: str) -> dict[str, object]:
    return {
        "status": status,
        "message": message,
        "base_file_name": _base_file_name(base_file),
    }


def _po_list_payload(items: Iterable[object]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for item in items:
        po_no = getattr(item, "po_no", "")
        payload.append(
            {
                "po_no": po_no,
                "status": getattr(item, "status", ""),
                "sellers": list(getattr(item, "sellers", ())),
                "line_count": getattr(item, "line_count", 0),
                "invoice_nos": list(getattr(item, "invoice_nos", ())),
                "invoice_options_by_seller": {
                    seller: list(options)
                    for seller, options in getattr(item, "invoice_options_by_seller", {}).items()
                },
                "exportable_documents_by_seller": {
                    seller: list(documents)
                    for seller, documents in getattr(
                        item, "exportable_documents_by_seller", {}
                    ).items()
                },
                "blocking_count": getattr(item, "blocking_count", 0),
                "date": getattr(item, "date", None),
            }
        )
    return payload


def _session_context(session: SessionInfo | ManagedSessionInfo) -> GenerationContext | None:
    context = getattr(session, "context", None)
    return context if isinstance(context, GenerationContext) else None


def _session_snapshot(session: SessionInfo | ManagedSessionInfo) -> WorkbookSnapshot:
    snapshot = getattr(session, "snapshot", None)
    if isinstance(snapshot, WorkbookSnapshot):
        return snapshot
    return get_cache_manager().get_snapshot(
        session.base_file,
        context=_session_context(session),
    )


def _generate_for_session(
    request: DocumentRequest,
    session: SessionInfo | ManagedSessionInfo,
) -> GenerationResult:
    context = _session_context(session)
    return generate(request, context=context) if context is not None else generate(request)


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


def _activation_payload(result: SessionActivation, store: WorkspaceStore) -> dict[str, object]:
    session = result.session
    snapshot = result.snapshot
    workspace = result.workspace
    return {
        "workspace": _workspace_dict(
            workspace,
            store,
            status="ready",
            status_message="本地 base 文件已通过检测",
        ),
        "session_id": session.session_id,
        "po_list": _po_list_payload(snapshot.po_summary),
        "invoices": [asdict(item) for item in snapshot.invoice_summary],
    }


def _activation_error_payload(error: BaseException) -> dict[str, str]:
    return {"code": _workspace_error_code(error), "message": _workspace_error_message(error)}


def _status_for_error(error: BaseException) -> tuple[str, str]:
    code = _workspace_error_code(error)
    status = {
        "WORKSPACE_FILE_MISSING": "file_missing",
        "WORKSPACE_FILE_PERMISSION_DENIED": "permission_denied",
        "PROFILE_NOT_FOUND": "profile_not_found",
        "WORKSPACE_SCHEMA_MISMATCH": "schema_mismatch",
    }.get(code, "unchecked")
    return status, _workspace_error_message(error)


@app.get("/api/profiles")
def list_profiles() -> dict[str, object]:
    store, _manager = _workspace_runtime()
    return {"profiles": _profile_summaries(store)}


@app.get("/api/workspaces")
def list_workspaces() -> dict[str, object]:
    store, _manager = _workspace_runtime()
    try:
        workspaces = store.list_workspaces()
    except WorkspaceStoreError as exc:
        raise _workspace_http_error(exc) from exc
    return {"workspaces": [_workspace_dict(item, store) for item in workspaces]}


@app.post("/api/workspaces/validate")
def validate_workspace_input(req: WorkspaceInputRequest) -> dict[str, object]:
    display_name, profile_id, base_file = _workspace_input_payload(req)
    del display_name
    store, _manager = _workspace_runtime()
    status, message = _validate_workspace_path(profile_id, base_file, store)
    return _validation_response(status, message, base_file)


@app.post("/api/workspaces")
def create_workspace(req: WorkspaceInputRequest) -> dict[str, object]:
    display_name, profile_id, base_file = _workspace_input_payload(req)
    store, _manager = _workspace_runtime()
    try:
        workspace = store.create(
            display_name=display_name,
            profile_id=profile_id,
            base_file=base_file,
        )
    except (WorkspaceStoreError, ProfileNotFoundError) as exc:
        raise _workspace_http_error(exc) from exc
    return _workspace_dict(workspace, store)


@app.patch("/api/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, req: WorkspaceUpdateRequest) -> dict[str, object]:
    display_name, profile_id, base_file = _workspace_input_payload(
        WorkspaceInputRequest(
            display_name=req.display_name,
            profile_id=req.profile_id,
            base_file=req.base_file,
        )
    )
    store, _manager = _workspace_runtime()
    try:
        workspace = store.update(
            workspace_id,
            display_name=display_name,
            profile_id=profile_id,
            base_file=base_file,
        )
    except (WorkspaceStoreError, ProfileNotFoundError) as exc:
        raise _workspace_http_error(exc) from exc
    return _workspace_dict(
        workspace,
        store,
        status="unchecked",
        status_message="配置已修改，请重新检测并激活",
    )


@app.post("/api/workspaces/{workspace_id}/validate")
def validate_workspace(workspace_id: str) -> dict[str, object]:
    store, _manager = _workspace_runtime()
    try:
        workspace = store.get(workspace_id)
    except (WorkspaceStoreError, ProfileNotFoundError) as exc:
        raise _workspace_http_error(exc) from exc
    status, message = _validate_workspace_path(workspace.profile_id, workspace.base_file, store)
    return _workspace_dict(workspace, store, status=status, status_message=message)


@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str) -> dict[str, str]:
    store, _manager = _workspace_runtime()
    try:
        store.delete(workspace_id)
    except (WorkspaceStoreError, ProfileNotFoundError) as exc:
        raise _workspace_http_error(exc) from exc
    return {"status": "deleted"}


@app.post("/api/workspaces/{workspace_id}/activate")
def activate_workspace(workspace_id: str) -> dict[str, object]:
    store, manager = _workspace_runtime()
    try:
        result = manager.activate(workspace_id)
    except (WorkspaceStoreError, ProfileNotFoundError, WorkspaceActivationError) as exc:
        raise _workspace_http_error(exc) from exc
    return _activation_payload(result, store)


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, object]:
    store, manager = _workspace_runtime()
    try:
        settings = store.load()
        workspaces = settings.workspaces
    except (WorkspaceStoreError, ProfileNotFoundError) as exc:
        return {
            "profiles": _profile_summaries(store),
            "workspaces": [],
            "current_workspace_id": None,
            "session_id": None,
            "needs_setup": True,
            "activation_error": _activation_error_payload(exc),
        }

    current_id = settings.current_workspace_id
    if current_id is None:
        return {
            "profiles": _profile_summaries(store),
            "workspaces": [_workspace_dict(item, store) for item in workspaces],
            "current_workspace_id": None,
            "session_id": None,
            "needs_setup": not workspaces,
            "activation_error": None,
        }

    try:
        active = manager.active_session()
        current_workspace = store.get(current_id)
        if active is not None and _session_matches_workspace(active, current_workspace):
            activation = SessionActivation(
                session=active,
                snapshot=active.snapshot,
                workspace=current_workspace,
            )
        else:
            restored = manager.restore_current()
            if restored is None:
                raise WorkspaceActivationError(
                    "当前工作区无法恢复", code="WORKSPACE_ACTIVATION_FAILED"
                )
            activation = restored
        if activation is None:
            raise WorkspaceActivationError("当前工作区无法恢复", code="WORKSPACE_ACTIVATION_FAILED")
        payload = _activation_payload(activation, store)
        payload.update(
            {
                "profiles": _profile_summaries(store),
                "workspaces": [
                    _workspace_dict(
                        item,
                        store,
                        status=("ready" if item.id == current_id else "unchecked"),
                        status_message=(
                            "本地 base 文件已通过检测" if item.id == current_id else None
                        ),
                    )
                    for item in workspaces
                ],
                "current_workspace_id": current_id,
                "needs_setup": False,
                "activation_error": None,
            }
        )
        return payload
    except (WorkspaceStoreError, ProfileNotFoundError, WorkspaceActivationError) as exc:
        status, message = _status_for_error(exc)
        return {
            "profiles": _profile_summaries(store),
            "workspaces": [
                _workspace_dict(
                    item,
                    store,
                    status=(status if item.id == current_id else "unchecked"),
                    status_message=(message if item.id == current_id else None),
                )
                for item in workspaces
            ],
            "current_workspace_id": current_id,
            "session_id": None,
            "needs_setup": False,
            "activation_error": _activation_error_payload(exc),
        }


@app.post("/api/session/open")
def open_session(req: OpenSessionRequest) -> dict[str, Any]:
    """打开 base 文件，返回 PO 列表 + session_id。"""
    # 兼容入口只允许临时打开默认 RO Profile；已有持久化工作区时，不允许绕过
    # activate API 把 session 指向另一个客户或另一个 base 文件。
    try:
        store, _manager = _workspace_runtime()
        current = store.get_current()
    except (WorkspaceStoreError, ProfileNotFoundError) as exc:
        raise _workspace_http_error(exc) from exc
    if current is not None and (
        current.profile_id != "ro" or not _same_base_path(current.base_file, req.base_file)
    ):
        raise HTTPException(
            409,
            detail={
                "code": "WORKSPACE_ACTIVATION_REQUIRED",
                "message": "当前已存在持久化工作区，请先通过工作区激活接口切换",
            },
        )
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
            "date": p.date,
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
    snapshot = _session_snapshot(session)
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
    snapshot = _session_snapshot(session)
    result = inspect_invoice_group_from_snapshot(
        snapshot,
        invoice_group_key,
        context=_session_context(session),
    )
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
    snapshot = _session_snapshot(session)
    result = preview_invoice_group_from_snapshot(
        snapshot,
        invoice_group_key,
        seller=req.seller,
        document=req.document,
        context=_session_context(session),
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
    snapshot = _session_snapshot(session)
    result = export_invoice_group_from_snapshot(
        snapshot,
        invoice_group_key,
        seller=req.seller,
        documents=tuple(req.documents),
        output_dir=session.temp_dir,
        output_format=req.output_format,
        context=_session_context(session),
    )
    return _result_to_dict(result)


@app.post("/api/invoice/{invoice_group_key}/export-batch")
def export_invoice_group_batch(
    invoice_group_key: str,
    req: InvoiceBatchExportRequest,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    snapshot = _session_snapshot(session)
    groups = tuple(
        ExportDocumentGroup(
            seller=group.seller,
            documents=_normalize_documents(group.documents),
            invoice_no=group.invoice_no,
        )
        for group in req.groups
    )
    result = export_invoice_document_groups(
        snapshot=snapshot,
        invoice_group_key=invoice_group_key,
        groups=groups,
        output_dir=session.temp_dir,
        formats=tuple(req.output_formats),
        context=_session_context(session),
    )
    return _result_to_dict(result)


@app.get("/api/po/{po_no}")
def get_po_data_endpoint(
    po_no: str,
    base_file: str | None = Query(None),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
) -> dict[str, Any]:
    """返回 PO 行数据视图（grid 数据）。复用缓存快照。"""
    if x_session_id is not None:
        session = _get_session(x_session_id)
        if session is None:
            raise HTTPException(
                400,
                detail={
                    "code": "INVALID_SESSION",
                    "message": f"session {x_session_id!r} 无效或已过期",
                },
            )
        return get_po_data(
            session.base_file,
            po_no,
            context=_session_context(session),
        )
    if base_file is None:
        raise HTTPException(
            400, detail={"code": "INVALID_SESSION", "message": "缺少 session_id 或 base_file"}
        )
    return get_po_data(base_file, po_no)


@app.get("/api/po/{po_no}/customer-po")
def get_customer_po_endpoint(
    po_no: str,
    base_file: str | None = Query(None),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
) -> dict[str, Any]:
    """返回指定 PO 号在客户PO sheet 中的对应行数据。"""
    if x_session_id is not None:
        session = _get_session(x_session_id)
        if session is None:
            raise HTTPException(
                400,
                detail={
                    "code": "INVALID_SESSION",
                    "message": f"session {x_session_id!r} 无效或已过期",
                },
            )
        return get_customer_po_data(
            session.base_file,
            po_no,
            context=_session_context(session),
        )
    if base_file is None:
        raise HTTPException(
            400, detail={"code": "INVALID_SESSION", "message": "缺少 session_id 或 base_file"}
        )
    return get_customer_po_data(base_file, po_no)


@app.get("/api/po/{po_no}/issues")
def get_po_issues_endpoint(
    po_no: str,
    base_file: str | None = Query(None),
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    """返回指定 PO 的阻断原因和警告明细。"""
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={"code": "INVALID_SESSION", "message": f"session {x_session_id!r} 无效或已过期"},
        )
    return get_po_issues(session.base_file, po_no, context=_session_context(session))


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
        base_file=session.base_file,
    )
    result = _generate_for_session(request, session)
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
        base_file=session.base_file,
    )

    # 使用缓存快照路径
    snapshot = _session_snapshot(session)
    result = preview_from_snapshot(snapshot, request, context=_session_context(session))

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
            "header_labels": p.header_labels,
            "column_labels": p.column_labels,
            "column_header_rows": p.column_header_rows,
            "lines": p.lines,
            "cost_breakdown_column_labels": p.cost_breakdown_column_labels,
            "cost_breakdown": p.cost_breakdown,
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
def edit_field(
    po_no: str,
    req: EditFieldRequest,
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
) -> EditFieldResponse:
    """接受字段编辑，写回 base 文件。

    写回成功后自动失效缓存，确保下次读取反映最新内容。
    """
    session: SessionInfo | ManagedSessionInfo | None = None
    base_file = req.base_file
    context = None
    if x_session_id is not None:
        session = _get_session(x_session_id)
        if session is None:
            raise HTTPException(
                400,
                detail={
                    "code": "INVALID_SESSION",
                    "message": f"session {x_session_id!r} 无效或已过期",
                },
            )
        base_file = session.base_file
        context = _session_context(session)
    result = edit_workbook_cell(
        base_file=base_file,
        sheet=req.sheet,
        row=req.row,
        field=req.field,
        value=req.value,
        schema=context.schema if context is not None else None,
        profile=context.profile if context is not None else None,
    )
    if result.ok:
        get_cache_manager().invalidate(base_file)
        if isinstance(session, ManagedSessionInfo):
            _store, manager = _workspace_runtime()
            try:
                manager.refresh_snapshot(session.session_id)
            except SessionManagerError as exc:
                return EditFieldResponse(
                    ok=False,
                    message=f"字段已写回，但刷新工作区快照失败：{exc}",
                )
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
        output_format=req.output_format,
        base_file=session.base_file,
    )
    result = _generate_for_session(request, session)
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
        base_file=session.base_file,
        po_no=po_no,
        output_dir=session.temp_dir,
        groups=groups,
        formats=tuple(req.output_formats),
        context=_session_context(session),
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

    session = _get_session(sid, allow_draining=True)
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
    suffix = p.suffix.lower()
    if suffix == ".zip":
        media_type = "application/zip"
    elif suffix == ".pdf":
        media_type = "application/pdf"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
    _store, manager = _workspace_runtime()
    if manager.close(req.session_id):
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
