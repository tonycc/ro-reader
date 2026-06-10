"""工作台查询服务：面向工作台 UI 的聚合查询接口。

所有工作台状态的业务推导（PO 状态、月份候选等）集中在此模块，
确保 API 层只做序列化，不做业务判断。

缓存路径：inspect_workbook() 和 get_po_data() 复用 WorkbookSnapshot，
避免每次请求重复读取 Excel。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ro_generator.errors import WorkbookOpenError
from ro_generator.models import ValidationMessage
from ro_generator.workbook_cache import get_cache_manager
from ro_generator.workbook_snapshot import BuildSnapshotError, PoInspection


@dataclass(frozen=True)
class FileInspectionResult:
    ok: bool
    sheets: tuple[str, ...] = ()
    size: int = 0
    error: str = ""


def inspect_file_path(path: str) -> FileInspectionResult:
    """检查文件路径是否有效，返回 sheet 列表和文件大小。

    API 层不应直接使用 openpyxl——此函数封装了文件检测逻辑。
    """
    from openpyxl import load_workbook

    p = Path(path)
    if not p.exists():
        return FileInspectionResult(ok=False, error=f"文件不存在：{path}")
    if not p.is_file():
        return FileInspectionResult(ok=False, error=f"路径不是文件：{path}")
    if p.suffix.lower() not in (".xlsx", ".xls", ".xlsm"):
        return FileInspectionResult(ok=False, error=f"不支持的文件格式：{p.suffix}")

    try:
        wb = load_workbook(str(p), read_only=True)
        sheets = tuple(wb.sheetnames)
        wb.close()
        return FileInspectionResult(ok=True, sheets=sheets, size=p.stat().st_size)
    except Exception as e:
        return FileInspectionResult(ok=False, error=f"无法打开文件：{e}")


@dataclass(frozen=True)
class WorkbookInspectionResult:
    ok: bool
    po_list: tuple[PoInspection, ...]
    errors: tuple[ValidationMessage, ...] = ()


def inspect_workbook(base_file: str) -> WorkbookInspectionResult:
    """返回 PO 列表和状态摘要。优先复用缓存。"""
    try:
        cache = get_cache_manager()
        snapshot = cache.get_snapshot(base_file)
        return WorkbookInspectionResult(ok=True, po_list=snapshot.po_summary)
    except (WorkbookOpenError, BuildSnapshotError, OSError) as exc:
        msg = str(exc)
        if hasattr(exc, "message"):
            msg = exc.message  # type: ignore[attr-defined]
        code = getattr(exc, "code", "WORKBOOK_OPEN_ERROR")
        return WorkbookInspectionResult(
            ok=False, po_list=(),
            errors=(ValidationMessage(kind="blocking_error", code=code, message=msg),),
        )


def get_po_data(base_file: str, po_no: str) -> dict[str, object]:
    """返回指定 PO 的行数据和表头。优先复用缓存。

    返回 {"po_no": str, "headers": list, "rows": list}。
    """
    cache = get_cache_manager()
    snapshot = cache.get_snapshot(base_file)
    rows = snapshot.po_rows_for_po(po_no)
    return {
        "po_no": po_no,
        "headers": list(snapshot.headers_po_record),
        "rows": [dict(r) for r in rows],  # shallow copy for safe serialization
    }


def get_customer_po_data(base_file: str, po_no: str) -> dict[str, object]:
    """返回指定 PO 号对应的客户PO数据。优先复用缓存。

    客户PO sheet 按 Purchasing Document 索引，PO record 的 PO NO. 列
    就是客户PO 的 Purchasing Document。
    """
    cache = get_cache_manager()
    snapshot = cache.get_snapshot(base_file)
    rows = snapshot.customer_po_rows_for_po(po_no)
    return {
        "po_no": po_no,
        "headers": list(snapshot.headers_customer_po),
        "rows": [dict(r) for r in rows],
    }


__all__ = [
    "FileInspectionResult",
    "PoInspection",
    "WorkbookInspectionResult",
    "get_customer_po_data",
    "get_po_data",
    "inspect_file_path",
    "inspect_workbook",
]
