"""WorkbookSnapshot：base 文件的内存只读快照。

一次性读取 workbook，构建 product_index、po_index、po_summary。
后续预览、数据检查、PO 列表查询复用此快照，不再重复打开 Excel。

快照构建后视为不可变。po_rows 中的 dict 元素必须按 read-only 使用，
消费者如需修改应在本地创建 copy。

FileSignature 用于检测 base 文件是否被外部修改。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ro_generator.base_schema import base_schema
from ro_generator.errors import WorkbookOpenError
from ro_generator.models import Product
from ro_generator.resolver import build_product_index, resolve_po_rows
from ro_generator.schema import SELLERS, SHEET_CUSTOMER_PO, SHEET_DATA_BASE, SHEET_PO_RECORD
from ro_generator.validator import validate_workbook_structure
from ro_generator.workbook_reader import WorkbookReader

_bs = base_schema()


# —————————————————————————————————————
# PO 状态模型（原在 workbench_service，移到此处避免循环导入）
# —————————————————————————————————————

@dataclass(frozen=True)
class PoInspection:
    po_no: str
    status: str
    sellers: tuple[str, ...]
    line_count: int
    invoice_nos: tuple[str, ...]
    blocking_count: int


# —————————————————————————————————————
# FileSignature
# —————————————————————————————————————

@dataclass(frozen=True)
class FileSignature:
    path: str
    mtime_ns: int
    size: int

    @classmethod
    def from_file(cls, file_path: str | Path) -> FileSignature:
        st = os.stat(file_path)
        return cls(
            path=str(Path(file_path).resolve()),
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FileSignature):
            return NotImplemented
        return (
            self.path == other.path
            and self.mtime_ns == other.mtime_ns
            and self.size == other.size
        )


# —————————————————————————————————————
# WorkbookSnapshot
# —————————————————————————————————————

@dataclass(frozen=True)
class WorkbookSnapshot:
    """base 文件的内存只读快照。

    IMPORTANT: po_rows 使用 tuple 包装，但其中每个元素是 dict[str, object]。
    消费者必须将 row dict 视为 read-only，不得原地修改。
    如需加工数据，请在消费者侧创建 copy。

    文件签名（mtime_ns + size）由 WorkbookCacheManager 通过 FileSignature
    独立管理，不重复存储在快照中。
    """

    base_file: str
    headers_data_base: tuple[str, ...]
    headers_po_record: tuple[str, ...]
    headers_customer_po: tuple[str, ...] = ()
    product_index: dict[str, Product] = field(default_factory=dict)
    po_rows: tuple[dict[str, object], ...] = ()
    po_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
    po_summary: tuple[PoInspection, ...] = ()
    customer_po_rows: tuple[dict[str, object], ...] = ()
    customer_po_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def po_rows_for_po(self, po_no: str) -> tuple[dict[str, object], ...]:
        """返回指定 PO 的所有行（按 po_index 下标从 po_rows 获取）。"""
        indices = self.po_index.get(po_no, ())
        return tuple(self.po_rows[i] for i in indices)

    def customer_po_rows_for_po(self, purchasing_document: str) -> tuple[dict[str, object], ...]:
        """返回指定 Purchasing Document 在客户PO sheet 中的行。"""
        indices = self.customer_po_index.get(purchasing_document, ())
        return tuple(self.customer_po_rows[i] for i in indices)


# —————————————————————————————————————
# 构建入口
# —————————————————————————————————————

def build_workbook_snapshot(base_file: str) -> WorkbookSnapshot:
    """一次性读取 workbook，构建完整快照。"""
    try:
        reader = WorkbookReader(base_file)
    except WorkbookOpenError as exc:
        raise BuildSnapshotError(
            f"无法打开 base 文件 {base_file}: {exc.message if hasattr(exc, 'message') else exc}"
        ) from exc

    try:
        # 结构校验
        struct = validate_workbook_structure(reader)
        if struct:
            raise BuildSnapshotError(
                f"base 文件结构校验失败: {struct[0].message if struct else '未知错误'}"
            )

        # 文件签名
        signature = FileSignature.from_file(base_file)

        # 读取 sheet 头
        db_sheet = reader.read_sheet(SHEET_DATA_BASE)
        po_sheet = reader.read_sheet(SHEET_PO_RECORD)
        cp_config = _bs.sheet("客户PO")
        cp_sheet = reader.read_sheet(
            SHEET_CUSTOMER_PO,
            header_row=cp_config.header_row,
            first_data_row=cp_config.first_data_row,
        )
        headers_db = db_sheet.headers
        headers_po = po_sheet.headers
        headers_cp = cp_sheet.headers

        # 构建 product_index
        product_index = build_product_index(reader)

        # 构建 po_rows 和 po_index
        po_field_name = _bs.field("PO record", "po_no")
        all_rows: list[dict[str, object]] = []
        po_index_builder: dict[str, list[int]] = {}

        for row in po_sheet.rows:
            idx = len(all_rows)
            all_rows.append(row)
            raw = row.get(po_field_name)
            if raw is None:
                continue
            po_no = str(raw).strip()
            if not po_no or po_no == "None":
                continue
            po_index_builder.setdefault(po_no, []).append(idx)

        po_rows = tuple(all_rows)
        po_index: dict[str, tuple[int, ...]] = {
            k: tuple(v) for k, v in po_index_builder.items()
        }

        # 构建 po_summary
        # 构建 customer_po_rows 和 customer_po_index
        cp_field_name = _bs.field("客户PO", "purchasing_document")
        cp_all_rows: list[dict[str, object]] = []
        cp_index_builder: dict[str, list[int]] = {}

        for row in cp_sheet.rows:
            idx = len(cp_all_rows)
            cp_all_rows.append(row)
            raw = row.get(cp_field_name)
            if raw is None:
                continue
            pd_no = str(raw).strip()
            if not pd_no or pd_no == "None":
                continue
            cp_index_builder.setdefault(pd_no, []).append(idx)

        cp_rows = tuple(cp_all_rows)
        cp_index: dict[str, tuple[int, ...]] = {
            k: tuple(v) for k, v in cp_index_builder.items()
        }

        po_summary = _build_po_summary(
            po_index,
            po_rows,
            product_index,
            cp_rows,
            cp_index,
        )

        return WorkbookSnapshot(
            base_file=str(Path(base_file).resolve()),
            headers_data_base=headers_db,
            headers_po_record=headers_po,
            headers_customer_po=headers_cp,
            product_index=product_index,
            po_rows=po_rows,
            po_index=po_index,
            po_summary=po_summary,
            customer_po_rows=cp_rows,
            customer_po_index=cp_index,
        )
    finally:
        reader.close()


# —————————————————————————————————————
# PO Summary 构建
# —————————————————————————————————————

def _build_po_summary(
    po_index: dict[str, tuple[int, ...]],
    po_rows: tuple[dict[str, object], ...],
    products: dict[str, Product],
    customer_po_rows: tuple[dict[str, object], ...],
    customer_po_index: dict[str, tuple[int, ...]],
) -> tuple[PoInspection, ...]:
    """基于索引和行数据构建所有 PO 的状态摘要。"""
    summaries: list[PoInspection] = []
    for po_no, indices in po_index.items():
        rows = tuple(po_rows[i] for i in indices)
        customer_rows = tuple(
            customer_po_rows[i] for i in customer_po_index.get(po_no, ())
        )
        resolve_result = resolve_po_rows(
            rows,
            products,
            po_no=po_no,
            customer_po_rows=customer_rows,
        )
        blocking = [m for m in resolve_result.messages if m.kind == "blocking_error"]

        invoice_nos: set[str] = set()
        for line in resolve_result.lines:
            if line.invoice_no:
                invoice_nos.add(line.invoice_no)

        has_lines = len(resolve_result.lines) > 0
        status = "blocked" if blocking else ("ready" if has_lines else "partial")
        summaries.append(
            PoInspection(
                po_no=po_no,
                status=status,
                sellers=tuple(SELLERS),
                line_count=len(resolve_result.lines) or len(rows),
                invoice_nos=tuple(sorted(invoice_nos)),
                blocking_count=len(blocking),
            )
        )
    return tuple(summaries)


# —————————————————————————————————————
# 错误
# —————————————————————————————————————

class BuildSnapshotError(Exception):
    """构建 WorkbookSnapshot 失败。"""
    pass


__all__ = [
    "BuildSnapshotError",
    "FileSignature",
    "PoInspection",
    "WorkbookSnapshot",
    "build_workbook_snapshot",
]
