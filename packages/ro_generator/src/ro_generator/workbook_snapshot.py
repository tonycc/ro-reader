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

from ro_generator.document_model import invoice_no_for_line
from ro_generator.errors import WorkbookOpenError
from ro_generator.invoice_groups import (
    InvoiceGroupBuild,
    InvoiceHeaderContext,
    InvoiceInspection,
    build_invoice_groups,
)
from ro_generator.models import OrderLine, Product
from ro_generator.profiles import CustomerProfile, GenerationContext, default_profile_registry
from ro_generator.profiles.runtime import current_profile, current_rules, profile_scope
from ro_generator.resolver import (
    CUSTOMER_PO_ONLY_ROW_KEY,
    build_product_index_from_rows,
    resolve_po_rows,
)
from ro_generator.schema import SELLERS
from ro_generator.seller_filter import factory_seller_for_line, has_factory_categories, int_or_none
from ro_generator.validator import validate_workbook_structure
from ro_generator.workbook_reader import ROW_NUMBER_KEY, WorkbookReader

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
    invoice_options_by_seller: dict[str, tuple[str, ...]]
    exportable_documents_by_seller: dict[str, tuple[str, ...]]
    blocking_count: int
    date: str | None


def _active_sellers() -> tuple[str, ...]:
    profile = current_profile()
    return profile.capabilities.sellers if profile is not None else SELLERS


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
            self.path == other.path and self.mtime_ns == other.mtime_ns and self.size == other.size
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
    profile_id: str = "ro"
    product_index: dict[str, Product] = field(default_factory=dict)
    po_rows: tuple[dict[str, object], ...] = ()
    po_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
    po_summary: tuple[PoInspection, ...] = ()
    invoice_summary: tuple[InvoiceInspection, ...] = ()
    invoice_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
    invoice_header_context: dict[str, InvoiceHeaderContext] = field(default_factory=dict)
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

    def invoice_rows_for_group(self, invoice_group_key: str) -> tuple[dict[str, object], ...]:
        indices = self.invoice_index.get(invoice_group_key, ())
        return tuple(self.po_rows[i] for i in indices)


# —————————————————————————————————————
# 构建入口
# —————————————————————————————————————


def build_workbook_snapshot(
    base_file: str,
    *,
    context: GenerationContext | None = None,
    profile: CustomerProfile | None = None,
) -> WorkbookSnapshot:
    """一次性读取 workbook，构建绑定 Profile 的完整快照。"""

    if context is None:
        active_profile = profile or current_profile() or default_profile_registry().default
        context = GenerationContext(profile=active_profile, base_file=Path(base_file))
    elif Path(base_file).expanduser().resolve() != context.base_path.expanduser().resolve():
        raise ValueError(
            "GenerationContext.base_file 与 build_workbook_snapshot 的 base_file 不一致"
        )
    with profile_scope(context.profile):
        return _build_workbook_snapshot(context)


def _build_workbook_snapshot(context: GenerationContext) -> WorkbookSnapshot:
    """在已绑定 Profile 作用域内构建快照。"""

    base_file = str(context.base_path)
    try:
        reader = WorkbookReader(base_file, schema=context.schema)
    except WorkbookOpenError as exc:
        raise BuildSnapshotError(
            f"无法打开 base 文件 {base_file}: {exc.message if hasattr(exc, 'message') else exc}"
        ) from exc

    try:
        # 结构校验
        struct = validate_workbook_structure(reader, schema=context.schema)
        if struct:
            raise BuildSnapshotError(
                f"base 文件结构校验失败: {struct[0].message if struct else '未知错误'}"
            )

        # 读取 sheet 头
        db_sheet = reader.read_sheet(context.schema.sheet("DATA BASE").name)
        po_sheet = reader.read_sheet(context.schema.sheet("PO record").name)
        cp_config = context.schema.sheet("客户PO")
        cp_sheet = reader.read_sheet(
            context.schema.sheet("客户PO").name,
            header_row=cp_config.header_row,
            first_data_row=cp_config.first_data_row,
        )
        headers_db = db_sheet.headers
        headers_po = po_sheet.headers
        headers_cp = cp_sheet.headers

        # 构建 product_index
        product_index = build_product_index_from_rows(db_sheet.rows)

        # 构建 po_rows 和 po_index
        po_field_name = context.schema.field("PO record", "po_no")
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

        # 构建 customer_po_rows 和 customer_po_index
        cp_field_name = context.schema.field("客户PO", "purchasing_document")
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
        cp_index: dict[str, tuple[int, ...]] = {k: tuple(v) for k, v in cp_index_builder.items()}

        if current_rules().include_customer_po_only_orders:
            _append_customer_po_only_rows(
                all_rows,
                po_index_builder,
                cp_rows,
                cp_index,
                product_index,
            )

        po_rows = tuple(all_rows)
        po_index: dict[str, tuple[int, ...]] = {k: tuple(v) for k, v in po_index_builder.items()}

        po_summary = _build_po_summary(
            po_index,
            po_rows,
            product_index,
            cp_rows,
            cp_index,
        )
        invoice_groups = _build_invoice_group_snapshot(
            po_index,
            po_rows,
            product_index,
            cp_rows,
            cp_index,
        )

        return WorkbookSnapshot(
            base_file=str(context.base_path),
            profile_id=context.profile_id,
            headers_data_base=headers_db,
            headers_po_record=headers_po,
            headers_customer_po=headers_cp,
            product_index=product_index,
            po_rows=po_rows,
            po_index=po_index,
            po_summary=po_summary,
            invoice_summary=invoice_groups.summaries,
            invoice_index=invoice_groups.index,
            invoice_header_context=invoice_groups.header_context,
            customer_po_rows=cp_rows,
            customer_po_index=cp_index,
        )
    finally:
        reader.close()


def _append_customer_po_only_rows(
    all_rows: list[dict[str, object]],
    po_index_builder: dict[str, list[int]],
    customer_po_rows: tuple[dict[str, object], ...],
    customer_po_index: dict[str, tuple[int, ...]],
    products: dict[str, Product],
) -> None:
    """为尚未进入 PO record 的客户订单建立只用于 PI/PO 的最小解析行。"""

    profile = current_profile()
    if profile is None:
        return
    schema = profile.schema
    cp_material = schema.field("客户PO", "material")
    cp_item = schema.field("客户PO", "item")
    cp_description = schema.field("客户PO", "description")
    cp_document_date = schema.field("客户PO", "document_date")
    cp_ship_date = schema.field("客户PO", "ship_date")
    po_no_field = schema.field("PO record", "po_no")
    item_field = schema.field("PO record", "item_line")
    sap_field = schema.field("PO record", "sap")
    description_field = schema.field("PO record", "description")
    category_field = schema.field("PO record", "category")
    order_date_field = schema.field("PO record", "order_date")
    final_ex_factory_field = schema.field("PO record", "final_ex_factory_date")

    for po_no, row_indices in customer_po_index.items():
        if po_no in po_index_builder:
            continue
        for customer_index in row_indices:
            customer_row = customer_po_rows[customer_index]
            sap_raw = customer_row.get(cp_material)
            sap = str(sap_raw).removesuffix(".0").strip() if sap_raw is not None else ""
            product = products.get(sap)
            row = {
                CUSTOMER_PO_ONLY_ROW_KEY: True,
                po_no_field: po_no,
                item_field: customer_row.get(cp_item),
                sap_field: sap_raw,
                description_field: customer_row.get(cp_description),
                category_field: product.category if product is not None else None,
                order_date_field: customer_row.get(cp_document_date),
                final_ex_factory_field: customer_row.get(cp_ship_date),
            }
            index = len(all_rows)
            all_rows.append(row)
            po_index_builder.setdefault(po_no, []).append(index)


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
        customer_rows = tuple(customer_po_rows[i] for i in customer_po_index.get(po_no, ()))
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
        invoice_options_by_seller = _build_invoice_options_by_seller(resolve_result.lines)
        exportable_documents_by_seller = _build_exportable_documents_by_seller(resolve_result.lines)

        earliest = None
        for line in resolve_result.lines:
            d = line.etd_on_board
            if d is not None and (earliest is None or d < earliest):
                earliest = d
        po_date = earliest.isoformat() if earliest is not None else None

        has_lines = len(resolve_result.lines) > 0
        status = "blocked" if blocking else ("ready" if has_lines else "partial")
        summaries.append(
            PoInspection(
                po_no=po_no,
                status=status,
                sellers=_active_sellers(),
                line_count=len(resolve_result.lines) or len(rows),
                invoice_nos=tuple(sorted(invoice_nos)),
                invoice_options_by_seller=invoice_options_by_seller,
                exportable_documents_by_seller=exportable_documents_by_seller,
                blocking_count=len(blocking),
                date=po_date,
            )
        )
    return tuple(summaries)


def _build_invoice_group_snapshot(
    po_index: dict[str, tuple[int, ...]],
    po_rows: tuple[dict[str, object], ...],
    products: dict[str, Product],
    customer_po_rows: tuple[dict[str, object], ...],
    customer_po_index: dict[str, tuple[int, ...]],
) -> InvoiceGroupBuild:
    row_index_by_source_row: dict[int, int] = {}
    for index, row in enumerate(po_rows):
        source_row = int_or_none(row.get(ROW_NUMBER_KEY))
        if source_row is not None:
            row_index_by_source_row[source_row] = index
    lines_by_row: list[tuple[int, OrderLine]] = []
    for po_no, indices in po_index.items():
        rows = tuple(po_rows[index] for index in indices)
        customer_rows = tuple(customer_po_rows[index] for index in customer_po_index.get(po_no, ()))
        resolved = resolve_po_rows(
            rows,
            products,
            po_no=po_no,
            customer_po_rows=customer_rows,
            require_customer_po=False,
        )
        for line in resolved.lines:
            if line.source_row is None:
                continue
            raw_index = row_index_by_source_row.get(line.source_row)
            if raw_index is not None:
                lines_by_row.append((raw_index, line))
    return build_invoice_groups(tuple(lines_by_row))


def _build_invoice_options_by_seller(lines: tuple[OrderLine, ...]) -> dict[str, tuple[str, ...]]:
    """返回当前 PO 在各 seller 的可选发票号。

    SK/YM 的 Invoice/PL 使用 `SK/YM INVOICE NO.`；EMAX 使用追加 `-P` 后的发票号。
    """
    return {seller: _invoice_options_for_seller(lines, seller) for seller in _active_sellers()}


def _invoice_options_for_seller(lines: tuple[OrderLine, ...], seller: str) -> tuple[str, ...]:
    options: set[str] = set()
    for line in _lines_for_invoice_options(lines, seller):
        invoice_no = invoice_no_for_line(line, document_type="INVOICE", seller=seller)
        if invoice_no:
            options.add(invoice_no)
    return tuple(sorted(options))


def _build_exportable_documents_by_seller(
    lines: tuple[OrderLine, ...],
) -> dict[str, tuple[str, ...]]:
    return {seller: _exportable_documents_for_seller(lines, seller) for seller in _active_sellers()}


def _exportable_documents_for_seller(
    lines: tuple[OrderLine, ...],
    seller: str,
) -> tuple[str, ...]:
    seller_lines = _lines_for_invoice_options(lines, seller)
    if not seller_lines:
        return ()
    profile = current_profile()
    supported = (
        profile.capabilities.documents_for(seller)
        if profile is not None
        else ("PI", "PO", "INVOICE", "PL", "CI", "RO_PL")
    )
    documents: list[str] = []
    if "PI" in supported:
        pi_no, _missing_field = current_rules().pi_no_for_lines(
            seller_lines,
            seller,
            seller_lines[0].po_no,
        )
        if pi_no:
            documents.append("PI")
    if "PO" in supported:
        documents.append("PO")
    if (
        "INVOICE" in supported
        and "PL" in supported
        and _invoice_options_for_seller(seller_lines, seller)
    ):
        documents.append("INVOICE_PL")
    if (
        "CI" in supported
        and "RO_PL" in supported
        and _invoice_options_for_seller(seller_lines, seller)
    ):
        documents.append("CI_PL")
    return tuple(documents)


def _lines_for_invoice_options(lines: tuple[OrderLine, ...], seller: str) -> tuple[OrderLine, ...]:
    if seller not in {"SK", "YM"} or not has_factory_categories(lines):
        return lines
    return tuple(line for line in lines if factory_seller_for_line(line) == seller)


# —————————————————————————————————————
# 错误
# —————————————————————————————————————


class BuildSnapshotError(Exception):
    """构建 WorkbookSnapshot 失败。"""

    pass


__all__ = [
    "BuildSnapshotError",
    "FileSignature",
    "InvoiceInspection",
    "PoInspection",
    "WorkbookSnapshot",
    "build_workbook_snapshot",
]
