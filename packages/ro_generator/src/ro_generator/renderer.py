"""Renderer：把 DocumentModel 写入 Excel 模板，输出可下载的 .xlsx。

设计要点（核心来自 Phase 0 Spike A 的发现）：
- openpyxl `insert_rows()` 不平移 `row_dimensions`，必须先**倒序手动 += 1 行号**再调用
  insert_rows（详见 `_insert_styled_row` 实现）
- 样式复制使用 `copy.copy()` 处理 Font / Fill / Border / Alignment，行高从 style_source_row
  借用
- 模板里有样板数据（如 GS Invoice 行 18-24 有示例 SKU），渲染前必须先清掉
- totals 单元格的位置在数据行扩展时由 openpyxl 自动平移（公式如 =SUM(F16:F26) 也会
  跟着扩展），调用方拿到的最终行号会上移
- 渲染期间累积双向溯源索引（产品方案 §4.4），随 RenderResult 返回

输入：`DocumentModel` + `TemplateMapping` + 输出路径。
输出：RenderResult（文件路径 + 源索引）。
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ro_generator.document_model import DocumentLine, DocumentModel
from ro_generator.errors import InternalError, TemplateError
from ro_generator.schema import SHEET_PO_RECORD
from ro_generator.source_index import SourceIndex, SourceIndexBuilder, SourceLocation
from ro_generator.template_mapping import LineColumns, TemplateMapping

# —————————————————————————————————————
# 公开 API
# —————————————————————————————————————


@dataclass(frozen=True)
class RenderResult:
    """渲染输出。

    - `output_path`：写好的 .xlsx 绝对路径
    - `source_index`：装配单元格 ↔ base 字段的双向映射
    """

    output_path: Path
    source_index: SourceIndex


def render_document(
    model: DocumentModel,
    mapping: TemplateMapping,
    output_path: str | Path,
) -> RenderResult:
    """把 model 渲染到 mapping.template_path 上指定的模板，保存到 output_path。

    返回 RenderResult，含文件绝对路径与源索引。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        wb = load_workbook(filename=str(mapping.template_path))
    except Exception as exc:
        raise TemplateError(f"无法打开模板 {mapping.template_path}：{exc}") from exc

    builder = SourceIndexBuilder()
    try:
        if mapping.sheet not in wb.sheetnames:
            raise TemplateError(
                f"模板 {mapping.template_path.name} 中找不到 sheet {mapping.sheet!r}"
            )
        ws: Worksheet = wb[mapping.sheet]

        _write_header(ws, model, mapping, builder)
        _write_lines_and_totals(ws, model, mapping, builder)

        wb.save(output_path)
    finally:
        wb.close()

    return RenderResult(
        output_path=output_path.resolve(),
        source_index=builder.build(),
    )


# —————————————————————————————————————
# Header
# —————————————————————————————————————

# DocumentModel 字段名 → mapping.header 中的 key（一对一映射）
_HEADER_FIELD_FROM_MODEL: Final[dict[str, str]] = {
    "invoice_no": "invoice_no",
    "factory_doc_no": "factory_doc_no",
    "ship_to": "ship_to",
    "po_no": "po_no",
    "invoice_month": "invoice_month",
    "seller": "seller",
    "buyer": "buyer",
}


# 缺值占位符的中文标签（key = mapping key）
_PLACEHOLDER_LABELS: dict[str, str] = {
    "invoice_no": "需填: INV#",
    "factory_doc_no": "需填: FACTORY DOC NO.",
    "ship_to": "需填: Ship To",
    "po_no": "需填: PO#",
    "invoice_month": "需填: 月份",
    "unit_price": "需填: 单价",
    "quantity": "需填: 数量",
}


def _write_header(
    ws: Worksheet,
    model: DocumentModel,
    mapping: TemplateMapping,
    builder: SourceIndexBuilder,
) -> None:
    """按 mapping.header 写表头字段。值为 None 时写 [需填: ...] 占位符。"""
    for model_attr, mapping_key in _HEADER_FIELD_FROM_MODEL.items():
        cell_addr = mapping.header.get(mapping_key)
        if not cell_addr:
            continue
        value = getattr(model, model_attr, None)
        label = _PLACEHOLDER_LABELS.get(mapping_key, f"[需填: {mapping_key}]")
        ws[cell_addr] = value if value is not None else label
        # 表头字段大多在 sheet 元信息层面（INV# 等），用 row=None 标识"非具体行"
        builder.add(
            cell_addr,
            SourceLocation(sheet=SHEET_PO_RECORD, row=None, field=mapping_key),
        )


# —————————————————————————————————————
# Lines + Totals
# —————————————————————————————————————


def _write_lines_and_totals(
    ws: Worksheet,
    model: DocumentModel,
    mapping: TemplateMapping,
    builder: SourceIndexBuilder,
) -> None:
    """把订单行写到模板，超出预留空间则插入新行并复制样式。"""
    line_count = len(model.lines)
    if line_count == 0:
        # 没有行数据时只清理样板，写合计为 0
        _clear_sample_rows(ws, mapping)
        _write_totals(ws, model, mapping, totals_row_offset=0, builder=builder)
        return

    start_row = mapping.lines.start_row
    style_source_row = mapping.lines.style_source_row
    reserved_rows = _reserved_row_count(mapping)

    # 1. 清掉模板里的样板数据（保留样式）
    _clear_sample_rows(ws, mapping)

    # 2. 如果实际行数 > 预留行数，插入额外的新行
    insertion_count = max(0, line_count - reserved_rows)
    if insertion_count > 0:
        # 在 reserved 区间末尾的下一行插入，避开样式源行
        insert_at = start_row + reserved_rows
        for _ in range(insertion_count):
            _insert_styled_row(ws, insert_at, style_src=style_source_row)

    # 3. 写每一行
    columns = mapping.lines.columns
    line_unit_label = mapping.lines.unit_label
    for offset, doc_line in enumerate(model.lines):
        row = start_row + offset
        _write_data_row(ws, row, doc_line, columns, line_unit_label, builder, po_no=model.po_no)
        # Write row_fixed values (e.g., Country of The Origin = "China")
        for col_letter, fixed_val in mapping.lines.row_fixed.items():
            ws[f"{col_letter}{row}"] = fixed_val

    # 4. 写合计（位置已被 openpyxl 自动平移）
    _write_totals(ws, model, mapping, totals_row_offset=insertion_count, builder=builder)


def _reserved_row_count(mapping: TemplateMapping) -> int:
    """从 mapping 推断模板预留多少行数据空间。

    取 totals 单元格的最小行号 − start_row。如果 mapping.totals 没有任何单元格，
    退化为 1（只用 style_source_row 一行）。
    """
    if not mapping.totals:
        return 1
    totals_rows: list[int] = []
    for addr in mapping.totals.values():
        try:
            _, row = coordinate_from_string(addr.strip())
        except ValueError as exc:
            raise InternalError(f"mapping totals 的单元格地址 {addr!r} 无法解析") from exc
        totals_rows.append(row)
    min_totals_row = min(totals_rows)
    reserved = min_totals_row - mapping.lines.start_row
    return max(reserved, 1)


def _clear_sample_rows(ws: Worksheet, mapping: TemplateMapping) -> None:
    """清掉模板预留区间里的样板数据（保留样式、公式列除外）。

    只清 mapping.lines.columns 引用到的单元格，避免误删模板里的标注/合并单元格。
    """
    reserved = _reserved_row_count(mapping)
    columns = mapping.lines.columns
    addrs = list(_iter_column_letters(columns))
    for offset in range(reserved):
        row = mapping.lines.start_row + offset
        for letter in addrs:
            cell = ws[f"{letter}{row}"]
            cell.value = None


def _write_data_row(
    ws: Worksheet,
    row: int,
    doc_line: DocumentLine,
    columns: LineColumns,
    fixed_unit_label: str | None,
    builder: SourceIndexBuilder,
    *,
    po_no: str = "",
) -> None:
    """写单行数据。amount 列写公式，让 Excel 在打开时自动重算。"""
    src_row = doc_line.source_row  # 可能为 None（合成数据 / 测试场景）

    if columns.po_no:
        ws[f"{columns.po_no}{row}"] = po_no
    if columns.item_line_no:
        addr = f"{columns.item_line_no}{row}"
        ws[addr] = doc_line.item_line_no
        builder.add(addr, SourceLocation(SHEET_PO_RECORD, src_row, "ITEM LINE#"))
    if columns.description:
        addr = f"{columns.description}{row}"
        ws[addr] = doc_line.description
        builder.add(addr, SourceLocation(SHEET_PO_RECORD, src_row, "DESCRIPTION"))
    if columns.gs_model:
        addr = f"{columns.gs_model}{row}"
        ws[addr] = doc_line.gs_model
        # gs_model 来自 DATA BASE，不是 PO record；这里仍标 PO record 行+字段名
        # 因为 UI 双向溯源 PO record 行号定位更直接，DATA BASE 详情通过 SAP 二次跳转
        builder.add(addr, SourceLocation(SHEET_PO_RECORD, src_row, "GS MODEL"))

    sap_addr = f"{columns.sap}{row}"
    ws[sap_addr] = doc_line.sap
    builder.add(sap_addr, SourceLocation(SHEET_PO_RECORD, src_row, "SAP Number"))

    price_addr = f"{columns.unit_price}{row}"
    ws[price_addr] = doc_line.unit_price if doc_line.unit_price != 0 else "[需填: 单价]"
    builder.add(price_addr, SourceLocation(SHEET_PO_RECORD, src_row, "unit_price"))

    qty_addr = f"{columns.quantity}{row}"
    ws[qty_addr] = doc_line.quantity if doc_line.quantity != 0 else "[需填: 数量]"
    builder.add(qty_addr, SourceLocation(SHEET_PO_RECORD, src_row, "FINALQTY"))

    # amount 列写公式：=E{row}*F{row}（保持模板风格，便于 Excel 用户审计）
    amount_addr = f"{columns.amount}{row}"
    ws[amount_addr] = doc_line.amount
    builder.add_computed(amount_addr, "amount")

    if columns.unit_label and fixed_unit_label:
        ws[f"{columns.unit_label}{row}"] = fixed_unit_label
        # 单位标签是模板里的固定文案，不溯源


def _write_totals(
    ws: Worksheet,
    model: DocumentModel,
    mapping: TemplateMapping,
    totals_row_offset: int,
    builder: SourceIndexBuilder,
) -> None:
    """写合计单元格。位置随 insertion_count 平移。"""
    for field_name, addr in mapping.totals.items():
        try:
            col_letter, row = coordinate_from_string(addr.strip())
        except ValueError as exc:
            raise InternalError(f"mapping totals 单元格地址 {addr!r} 无法解析") from exc
        new_row = row + totals_row_offset
        cell_addr = f"{col_letter}{new_row}"
        wrote = True
        if field_name == "quantity":
            ws[cell_addr] = model.total_quantity
        elif field_name == "amount":
            ws[cell_addr] = model.total_amount
        elif field_name == "carton_count" and model.total_carton_count is not None:
            ws[cell_addr] = model.total_carton_count
        elif field_name == "net_weight" and model.total_net_weight is not None:
            ws[cell_addr] = model.total_net_weight
        elif field_name == "gross_weight" and model.total_gross_weight is not None:
            ws[cell_addr] = model.total_gross_weight
        elif field_name == "cbm" and model.total_cbm is not None:
            ws[cell_addr] = model.total_cbm
        else:
            wrote = False
        if wrote:
            # 合计是工作台计算得出，不指向某一行
            builder.add_computed(cell_addr, f"total_{field_name}")


# —————————————————————————————————————
# Spike A 验证过的样式插入逻辑
# —————————————————————————————————————


def _insert_styled_row(ws: Worksheet, insert_at: int, style_src: int) -> None:
    """在 insert_at 处插入一行，并执行 openpyxl 不会自动做的事：

    - 平移 insert_at 之后所有 row_dimensions 一格（openpyxl 只移单元格内容，不移
      row_dimensions，不修复会导致行高错乱）
    - 把 style_src 行的样式复制到新插入的行

    详见 Phase 0 Spike A 的结论 (`docs/development/phase-0-spike-results.md`)。
    """
    # 1. 倒序处理，避免覆盖
    existing_rows = sorted(
        (r for r in ws.row_dimensions if r >= insert_at),
        reverse=True,
    )
    for orig_row in existing_rows:
        src_dim = ws.row_dimensions[orig_row]
        new_dim = ws.row_dimensions[orig_row + 1]
        new_dim.height = src_dim.height
        new_dim.hidden = src_dim.hidden
        new_dim.outlineLevel = src_dim.outlineLevel
    if insert_at in ws.row_dimensions:
        ws.row_dimensions[insert_at].height = None

    # 2. openpyxl 处理单元格内容、公式、合并区域的下移
    ws.insert_rows(insert_at)

    # 3. 把样板行样式复制到新行
    _copy_row_style(ws, src_row=style_src, dst_row=insert_at, max_col=ws.max_column)


def _copy_row_style(ws: Worksheet, src_row: int, dst_row: int, max_col: int) -> None:
    """把 src_row 的每个单元格样式复制到 dst_row 的同列单元格。"""
    src_height = ws.row_dimensions[src_row].height
    if src_height is not None:
        ws.row_dimensions[dst_row].height = src_height
    for col_idx in range(1, max_col + 1):
        src_cell = ws.cell(row=src_row, column=col_idx)
        dst_cell = ws.cell(row=dst_row, column=col_idx)
        # MergedCell 不可设置样式，跳过；MergedCell 的样式由所属合并区域统一控制
        if not isinstance(src_cell, Cell) or not isinstance(dst_cell, Cell):
            continue
        if src_cell.has_style:
            # openpyxl 的 stub 把 .font 等声明为 Serialisable，
            # 但运行时 copy(StyleProxy) 返回相应的 Font/Fill/... 实例，赋值有效（Spike A 验证过）。
            dst_cell.font = copy(src_cell.font)  # type: ignore[assignment]
            dst_cell.fill = copy(src_cell.fill)  # type: ignore[assignment]
            dst_cell.border = copy(src_cell.border)  # type: ignore[assignment]
            dst_cell.alignment = copy(src_cell.alignment)  # type: ignore[assignment]
            dst_cell.number_format = src_cell.number_format
            dst_cell.protection = copy(src_cell.protection)  # type: ignore[assignment]


# —————————————————————————————————————
# Helpers
# —————————————————————————————————————


def _iter_column_letters(columns: LineColumns) -> list[str]:
    out: list[str] = []
    for key in (
        "po_no",
        "item_line_no",
        "description",
        "gs_model",
        "sap",
        "unit_price",
        "quantity",
        "unit_label",
        "amount",
    ):
        v = getattr(columns, key)
        if isinstance(v, str):
            out.append(v)
    return out


# 给类型校验器看，避免 unused warning
_ = (Workbook, column_index_from_string)


__all__ = ["render_document"]
