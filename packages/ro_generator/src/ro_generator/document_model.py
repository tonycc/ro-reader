"""Document model：把 OrderLine 列表转成具体单据的视图模型。

设计边界：
- document_model 关心"这一类单据的视图长什么样"，不关心模板单元格位置
  （那是 template_mapping 的职责）
- 由 (seller, buyer) 决定从 OrderLine.subtotals 中取哪一段
- 数量来源：完整 PO 数量 vs 出货数量 (ship_qty)（产品方案 §10.3）
- 校验只产出本层能产生的信息
- 不重复 resolver 已经报过的错误
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Final

from ro_generator.header_rules import resolve_header_field_spec
from ro_generator.line_rules import resolve_line_field_spec
from ro_generator.models import CostBreakdownItem, DocumentType, OrderLine, ValidationMessage
from ro_generator.profiles.runtime import current_rules, current_schema

# —————————————————————————————————————
# 校验消息 code
# —————————————————————————————————————

CODE_LINE_NOT_PRICED: Final = "LINE_NOT_PRICED_FOR_SEGMENT"
CODE_INVOICE_NO_MISSING: Final = "INVOICE_NO_MISSING"
CODE_NO_SHIPMENT_FOR_INVOICE: Final = "NO_SHIPMENT_FOR_INVOICE"
CODE_PACKING_DATA_MISSING: Final = "PACKING_DATA_MISSING"


def _po_record_sheet() -> str:
    return current_schema().sheet("PO record").name


# —————————————————————————————————————
# 视图模型
# —————————————————————————————————————


@dataclass(frozen=True)
class DocumentLine:
    """单据中的一行。

    `source_row` 是 PO record 中的源行号，用于双向溯源（产品方案 §4.4）。
    装箱字段仅 PL 使用。
    """

    po_no: str
    item_line_no: str
    sap: str
    description: str
    category: int
    gs_model: str | None
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    source_row: int | None = None
    carton_count: Decimal | None = None
    carton_from: int | None = None
    carton_to: int | None = None
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    cbm: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    confirmed_ex_factory_date: date | None = None
    po_ex_factory_date: date | None = None  # PO record "FINAL EX-FACTORY DATE"
    quantity_source_field: str | None = None
    net_weight_source_sheet: str | None = None
    net_weight_source_field: str | None = None
    net_weight_source_rule: str | None = None
    gross_weight_source_sheet: str | None = None
    gross_weight_source_field: str | None = None
    gross_weight_source_rule: str | None = None
    item_number: str = ""  # PO 模板 Item Number，实际来源由 line mapping 规则决定
    cp_item: str = ""  # 客户PO "Item" 列值，SK/YM PI 模板 PO item Line Number 来源
    cost_breakdown: tuple[CostBreakdownItem, ...] = ()


@dataclass(frozen=True)
class DocumentCostBreakdownLine:
    """Invoice Combo 成本拆分行。"""

    po_no: str
    item_line_no: str
    item_number: str
    description: str
    unit_price: Decimal
    component: str
    source_row: int | None = None
    source_field: str | None = None


@dataclass(frozen=True)
class DocumentModel:
    """单据视图模型。"""

    document_type: DocumentType
    seller: str
    buyer: str
    po_no: str
    lines: tuple[DocumentLine, ...]
    total_quantity: Decimal
    total_amount: Decimal
    cost_breakdown: tuple[DocumentCostBreakdownLine, ...] = ()
    pi_no: str | None = None  # PI 编号：SK 用 E10 PO，YM 用 YM PO，GS/EMAX 用客户 PO
    invoice_no: str | None = None
    etd_on_board: date | None = None  # PO record "ETD ON BOARD"，PF GS Invoice 表头
    total_carton_count: Decimal | None = None
    total_net_weight: Decimal | None = None
    total_gross_weight: Decimal | None = None
    total_cbm: Decimal | None = None
    ship_to: str | None = None
    manufacturer_address: str | None = None  # 客户PO "manufacturer" 列
    final_destination: str | None = None  # 客户PO "final destination" 列
    ex_factory_date: date | None = None
    document_date: date | None = None  # 客户PO单据日期（Profile 可声明为表头来源）
    manufacturer_name: str | None = None  # Profile 计算出的制造商名称
    manufacturer_company_address: str | None = None  # Profile 计算出的制造商地址第 1 行
    manufacturer_company_address_2: str | None = None  # Profile 计算出的制造商地址第 2 行


@dataclass(frozen=True)
class BuildResult:
    model: DocumentModel | None
    messages: tuple[ValidationMessage, ...]


# —————————————————————————————————————
# 共享：定价校验 + 行装配
# —————————————————————————————————————

_Segment = tuple[str, str]


def _price_segment(document_type: str, seller: str, buyer: str) -> _Segment:
    return current_rules().price_segment(document_type, seller, buyer)


def invoice_no_for_line(
    line: OrderLine,
    *,
    document_type: str,
    seller: str,
) -> str | None:
    """按单据上下文返回对用户可见、可用于导出的发票号。"""
    return current_rules().invoice_no_for_line(line, document_type, seller)


def invoice_no_matches(
    line: OrderLine,
    requested_invoice_no: str,
    *,
    document_type: str,
    seller: str,
) -> bool:
    """判断源行是否属于请求的发票号。

    EMAX 对外展示和导出使用 `INV#-P`，但为兼容已有命令行参数，也接受原始 `INV#` 作为过滤输入。
    """
    return current_rules().invoice_no_matches(
        line,
        requested_invoice_no,
        document_type,
        seller,
    )


def _invoice_source_field(document_type: str, seller: str) -> str:
    spec = resolve_header_field_spec("invoice_no", document_type=document_type, seller=seller)
    if spec is not None and spec.source_field:
        return spec.source_field
    return "INV#"


def _first_matching_invoice_no(
    lines: tuple[OrderLine, ...],
    requested_invoice_no: str | None,
    *,
    document_type: str,
    seller: str,
) -> str | None:
    for line in lines:
        inv = invoice_no_for_line(line, document_type=document_type, seller=seller)
        if not inv:
            continue
        if requested_invoice_no is None or invoice_no_matches(
            line,
            requested_invoice_no,
            document_type=document_type,
            seller=seller,
        ):
            return inv
    return None


def _assemble_lines(
    lines: tuple[OrderLine, ...],
    segment: _Segment,
    invoice_no: str | None,
    po_no: str,
    *,
    document_type: DocumentType,
    packing: bool = False,
    use_po_record_description: bool = False,
    seller: str = "",
) -> tuple[list[DocumentLine] | None, list[ValidationMessage]]:
    """价格段校验 + INV# 过滤 + DocumentLine 装配（四类单据共用）。

    返回 (doc_lines, messages)。doc_lines 在阻断时为 None。
    `packing=True` 时，每行要求装箱数据完整，缺一项即阻断。
    `use_po_record_description=True` 时，优先使用 PO record 的 DESCRIPTION。
    """
    messages: list[ValidationMessage] = []

    sliced = _slice_by_invoice(lines, invoice_no, document_type=document_type, seller=seller)
    if invoice_no is not None and not sliced:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_NO_SHIPMENT_FOR_INVOICE,
                message=f"PO {po_no} 在 INV# {invoice_no} 下没有出货数据",
                sheet=_po_record_sheet(),
            )
        )
        return None, messages

    doc_lines: list[DocumentLine] = []
    for original_line, line_quantity in sliced:
        unit_price = current_rules().unit_price_for_line(original_line, document_type, segment)
        if unit_price is None:
            messages.append(
                ValidationMessage(
                    kind="warning",
                    code=CODE_LINE_NOT_PRICED,
                    severity="high",
                    message=(
                        f"行（SAP {original_line.sap}）在链段 {segment[0]}→{segment[1]} 下无单价"
                    ),
                    sheet=_po_record_sheet(),
                    field=(
                        current_rules().po_price_columns.get(seller)
                        if current_rules().uses_po_record_unit_price(document_type)
                        else "SAP Number"
                    ),
                )
            )
            unit_price = Decimal("0")
        amount = (unit_price * line_quantity).quantize(Decimal("0.01"))

        packing_values = (
            current_rules().packing_values_for_line(original_line, line_quantity)
            if packing
            else (None, None, None, None)
        )
        if packing:
            missing = _collect_missing_packing_fields(packing_values)
            if missing:
                messages.append(
                    ValidationMessage(
                        kind="warning",
                        code=CODE_PACKING_DATA_MISSING,
                        severity="high",
                        message=f"行（SAP {original_line.sap}）缺少装箱数据：{', '.join(missing)}，将填 0",
                        sheet=_po_record_sheet(),
                        field=next(iter(missing)),
                    )
                )

        item_line_spec = resolve_line_field_spec(
            "item_line_no", document_type=document_type, seller=seller
        )
        item_line_value = (
            original_line.cp_item
            if item_line_spec.source_sheet == current_schema().sheet("客户PO").name
            and item_line_spec.source_field == current_schema().field("客户PO", "item")
            else (
                original_line.po_record_item_line_no
                if item_line_spec.source_sheet == current_schema().sheet("PO record").name
                and item_line_spec.source_field == current_schema().field("PO record", "item_line")
                else original_line.item_line_no
            )
        )
        po_no_spec = resolve_line_field_spec("po_no", document_type=document_type, seller=seller)
        po_no_value = (
            original_line.customer_po_no or original_line.po_no
            if po_no_spec.source_sheet == current_schema().sheet("客户PO").name
            and po_no_spec.source_field == current_schema().field("客户PO", "purchasing_document")
            else original_line.po_no
        )
        item_num_spec = resolve_line_field_spec(
            "item_number", document_type=document_type, seller=seller
        )
        item_num_value = (
            original_line.customer_po_material or original_line.item_line_no
            if item_num_spec.source_sheet == current_schema().sheet("客户PO").name
            and item_num_spec.source_field == current_schema().field("客户PO", "material")
            else original_line.item_line_no
        )

        description_spec = resolve_line_field_spec(
            "description", document_type=document_type, seller=seller
        )
        if description_spec.source_sheet == current_schema().sheet(
            "客户PO"
        ).name and description_spec.source_field == current_schema().field("客户PO", "description"):
            line_description = original_line.customer_po_description or ""
        elif use_po_record_description and original_line.po_record_description:
            line_description = original_line.po_record_description
        else:
            line_description = original_line.description

        ex_factory_date = current_rules().line_ex_factory_date_for_line(
            original_line,
            document_type,
            seller,
        )
        nw_sheet, nw_field, nw_rule = (
            _resolve_packing_weight_source(original_line, "net_weight")
            if packing
            else (None, None, None)
        )
        gw_sheet, gw_field, gw_rule = (
            _resolve_packing_weight_source(original_line, "gross_weight")
            if packing
            else (None, None, None)
        )

        doc_lines.append(
            DocumentLine(
                po_no=po_no_value,
                item_line_no=item_line_value,
                item_number=item_num_value,
                cp_item=original_line.cp_item,
                sap=original_line.sap,
                description=line_description,
                category=original_line.category,
                gs_model=original_line.product.gs_model,
                quantity=line_quantity,
                unit_price=unit_price,
                amount=amount,
                source_row=original_line.source_row,
                carton_count=packing_values[0],
                net_weight=packing_values[1],
                gross_weight=packing_values[2],
                cbm=packing_values[3],
                length=original_line.product.length if packing else None,
                width=original_line.product.width if packing else None,
                height=original_line.product.height if packing else None,
                confirmed_ex_factory_date=ex_factory_date,
                po_ex_factory_date=original_line.po_ex_factory_date,
                quantity_source_field=(
                    original_line.ship_qty_source_field
                    if document_type in {"INVOICE", "PL", "CI", "RO_PL"}
                    else None
                ),
                net_weight_source_sheet=nw_sheet,
                net_weight_source_field=nw_field,
                net_weight_source_rule=nw_rule,
                gross_weight_source_sheet=gw_sheet,
                gross_weight_source_field=gw_field,
                gross_weight_source_rule=gw_rule,
                cost_breakdown=current_rules().cost_breakdown_for_line(
                    original_line,
                    document_type,
                    seller,
                ),
            )
        )

    if packing:
        doc_lines = _assign_carton_ranges(doc_lines)

    return doc_lines, messages


def _carton_span(carton_count: Decimal | None) -> int | None:
    if carton_count is None or carton_count <= 0:
        return None
    span = int(carton_count.to_integral_value(rounding=ROUND_CEILING))
    return span if span > 0 else None


def _assign_carton_ranges(doc_lines: list[DocumentLine]) -> list[DocumentLine]:
    """按明细箱数累计 CTN# Fr/To，供装箱单首列使用。"""

    numbered: list[DocumentLine] = []
    next_number = 1
    numbering_active = True
    for line in doc_lines:
        span = _carton_span(line.carton_count)
        if not numbering_active or span is None:
            numbered.append(line)
            if span is None:
                numbering_active = False
            continue
        carton_from = next_number
        carton_to = next_number + span - 1
        numbered.append(replace(line, carton_from=carton_from, carton_to=carton_to))
        next_number = carton_to + 1
    return numbered


def _resolve_packing_weight_source(
    line: OrderLine,
    internal_field: str,
) -> tuple[str, str, str]:
    logical_sheet, field_key, rule = current_rules().packing_weight_source_for_line(
        line, internal_field
    )
    schema = current_schema()
    return schema.sheet(logical_sheet).name, schema.field(logical_sheet, field_key), rule


def _collect_missing_packing_fields(
    values: tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None],
) -> list[str]:
    carton_count, net_weight, gross_weight, total_cbm = values
    missing: list[str] = []
    if carton_count is None:
        missing.append("CTNS")
    if net_weight is None:
        missing.append("N/W")
    if gross_weight is None:
        missing.append("G/W")
    if total_cbm is None:
        missing.append("TOTAL CBM")
    return missing


def _resolve_model_ex_factory_date(
    lines: tuple[OrderLine, ...],
    document_type: str,
    seller: str,
) -> date | None:
    """根据 header_rules 选择表头出厂日期来源。"""
    for line in lines:
        value = current_rules().header_ex_factory_date_for_line(line, document_type, seller)
        if value is not None:
            return value
    return None


def _resolve_model_etd_on_board(lines: tuple[OrderLine, ...]) -> date | None:
    """返回当前发票行中最早的 PO record ETD ON BOARD 日期。"""

    dates = [line.etd_on_board for line in lines if line.etd_on_board is not None]
    return min(dates) if dates else None


def _resolve_model_header_values(
    lines: tuple[OrderLine, ...],
    document_type: str,
    seller: str,
) -> tuple[date | None, str | None, str | None, str | None]:
    """解析可被 Profile 声明为表头来源的订单日期和制造商字段。"""

    document_date = next(
        (line.customer_po_document_date for line in lines if line.customer_po_document_date),
        None,
    )
    manufacturer_name, address_1, address_2 = current_rules().manufacturer_header_values(
        lines,
        document_type,
        seller,
    )
    return document_date, manufacturer_name, address_1, address_2


# —————————————————————————————————————
# PI — Proforma Invoice
# —————————————————————————————————————


def build_pi_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
    pi_no: str | None = None,
) -> BuildResult:
    """PI：使用完整 PO 数量。pi_no 由上游按 seller 规则解析后传入。"""
    doc_lines, messages = _assemble_lines(
        lines,
        _price_segment("PI", seller, buyer),
        invoice_no=None,
        po_no=po_no,
        document_type="PI",
        seller=seller,
    )
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)
    manufacturer_address = _first_non_empty(line.manufacturer_address for line in lines)
    final_destination = _first_non_empty(line.final_destination for line in lines)
    ex_factory_date = _resolve_model_ex_factory_date(lines, "PI", seller)
    document_date, manufacturer_name, manufacturer_address_1, manufacturer_address_2 = (
        _resolve_model_header_values(lines, "PI", seller)
    )

    return BuildResult(
        model=DocumentModel(
            document_type="PI",
            seller=seller,
            buyer=buyer,
            po_no=po_no,
            pi_no=pi_no or po_no,
            lines=tuple(doc_lines),
            total_quantity=total_qty,
            total_amount=total_amt,
            ship_to=ship_to,
            manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
            document_date=document_date,
            manufacturer_name=manufacturer_name,
            manufacturer_company_address=manufacturer_address_1,
            manufacturer_company_address_2=manufacturer_address_2,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# PO — Purchase Order
# —————————————————————————————————————


def build_po_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
) -> BuildResult:
    """PO：与 PI 结构相同，使用完整 PO 数量。"""
    doc_lines, messages = _assemble_lines(
        lines,
        _price_segment("PO", seller, buyer),
        invoice_no=None,
        po_no=po_no,
        document_type="PO",
        seller=seller,
    )
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)
    manufacturer_address = _first_non_empty(line.manufacturer_address for line in lines)
    final_destination = _first_non_empty(line.final_destination for line in lines)
    ex_factory_date = _resolve_model_ex_factory_date(lines, "PO", seller)
    document_date, manufacturer_name, manufacturer_address_1, manufacturer_address_2 = (
        _resolve_model_header_values(lines, "PO", seller)
    )
    display_po_no = _first_non_empty(line.customer_po_no for line in lines) or po_no

    return BuildResult(
        model=DocumentModel(
            document_type="PO",
            seller=seller,
            buyer=buyer,
            po_no=display_po_no,
            lines=tuple(doc_lines),
            total_quantity=total_qty,
            total_amount=total_amt,
            ship_to=ship_to,
            manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
            document_date=document_date,
            manufacturer_name=manufacturer_name,
            manufacturer_company_address=manufacturer_address_1,
            manufacturer_company_address_2=manufacturer_address_2,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# Invoice
# —————————————————————————————————————


def build_invoice_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_no: str | None = None,
) -> BuildResult:
    """Invoice：按 INV# 过滤行，使用 SHIP QTY。"""
    segment = _price_segment("INVOICE", seller, buyer)
    messages: list[ValidationMessage] = []

    doc_lines, assemble_msgs = _assemble_lines(
        lines,
        segment,
        invoice_no=invoice_no,
        po_no=po_no,
        document_type="INVOICE",
        use_po_record_description=True,
        seller=seller,
    )
    if assemble_msgs:
        messages.extend(assemble_msgs)
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    inv_no = _first_matching_invoice_no(
        lines,
        invoice_no,
        document_type="INVOICE",
        seller=seller,
    )
    if not inv_no:
        source_field = _invoice_source_field("INVOICE", seller)
        messages.append(
            ValidationMessage(
                kind="warning",
                code=CODE_INVOICE_NO_MISSING,
                severity="high",
                message=f"Invoice 单据要求 {source_field}，但 PO record 中未填写",
                sheet=_po_record_sheet(),
                field=source_field,
            )
        )

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    cost_breakdown = _build_cost_breakdown_lines(tuple(doc_lines))
    invoice_source_lines = tuple(
        original_line
        for original_line, _ in _slice_by_invoice(
            lines,
            invoice_no,
            document_type="INVOICE",
            seller=seller,
        )
    )
    header_source_lines = invoice_source_lines or lines
    ship_to = _first_non_empty(line.ship_to for line in header_source_lines)
    manufacturer_address = _first_non_empty(
        line.manufacturer_address for line in header_source_lines
    )
    final_destination = _first_non_empty(line.final_destination for line in header_source_lines)
    ex_factory_date = _resolve_model_ex_factory_date(header_source_lines, "INVOICE", seller)
    document_date, manufacturer_name, manufacturer_address_1, manufacturer_address_2 = (
        _resolve_model_header_values(header_source_lines, "INVOICE", seller)
    )

    return BuildResult(
        model=DocumentModel(
            document_type="INVOICE",
            seller=seller,
            buyer=buyer,
            po_no=po_no,
            lines=tuple(doc_lines),
            total_quantity=total_qty,
            total_amount=total_amt,
            cost_breakdown=cost_breakdown,
            invoice_no=inv_no,
            etd_on_board=_resolve_model_etd_on_board(invoice_source_lines),
            ship_to=ship_to,
            manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
            document_date=document_date,
            manufacturer_name=manufacturer_name,
            manufacturer_company_address=manufacturer_address_1,
            manufacturer_company_address_2=manufacturer_address_2,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# PL — Packing List
# —————————————————————————————————————


def build_pl_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_no: str | None = None,
) -> BuildResult:
    """PL：按 INV# 过滤，使用 SHIP QTY，额外要求装箱字段完整。"""
    segment = _price_segment("PL", seller, buyer)
    messages: list[ValidationMessage] = []

    doc_lines, assemble_msgs = _assemble_lines(
        lines,
        segment,
        invoice_no=invoice_no,
        po_no=po_no,
        document_type="PL",
        packing=True,
        use_po_record_description=True,
        seller=seller,
    )
    if assemble_msgs:
        messages.extend(assemble_msgs)
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    inv_no = _first_matching_invoice_no(
        lines,
        invoice_no,
        document_type="PL",
        seller=seller,
    )
    if not inv_no:
        source_field = _invoice_source_field("PL", seller)
        messages.append(
            ValidationMessage(
                kind="warning",
                code=CODE_INVOICE_NO_MISSING,
                severity="high",
                message=f"Packing List 要求 {source_field}，但 PO record 中未填写",
                sheet=_po_record_sheet(),
                field=source_field,
            )
        )

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    total_carton = sum(
        (dl.carton_count for dl in doc_lines if dl.carton_count is not None), Decimal(0)
    )
    total_nw = sum((dl.net_weight for dl in doc_lines if dl.net_weight is not None), Decimal(0))
    total_gw = sum((dl.gross_weight for dl in doc_lines if dl.gross_weight is not None), Decimal(0))
    total_cbm = sum((dl.cbm for dl in doc_lines if dl.cbm is not None), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)
    manufacturer_address = _first_non_empty(line.manufacturer_address for line in lines)
    final_destination = _first_non_empty(line.final_destination for line in lines)
    ex_factory_date = _resolve_model_ex_factory_date(lines, "PL", seller)
    document_date, manufacturer_name, manufacturer_address_1, manufacturer_address_2 = (
        _resolve_model_header_values(lines, "PL", seller)
    )

    return BuildResult(
        model=DocumentModel(
            document_type="PL",
            seller=seller,
            buyer=buyer,
            po_no=po_no,
            lines=tuple(doc_lines),
            total_quantity=total_qty,
            total_amount=total_amt,
            invoice_no=inv_no,
            ship_to=ship_to,
            manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
            document_date=document_date,
            manufacturer_name=manufacturer_name,
            manufacturer_company_address=manufacturer_address_1,
            manufacturer_company_address_2=manufacturer_address_2,
            total_carton_count=total_carton,
            total_net_weight=total_nw,
            total_gross_weight=total_gw,
            total_cbm=total_cbm,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# helpers
# —————————————————————————————————————


def _slice_by_invoice(
    lines: tuple[OrderLine, ...],
    invoice_no: str | None,
    *,
    document_type: DocumentType,
    seller: str,
) -> list[tuple[OrderLine, Decimal]]:
    """按 INV# 过滤，返回 (原行, 数量) 列表。

    invoice_no 为 None 时返回每行的完整 quantity（PI/PO 用）。
    invoice_no 指定时，返回匹配行的 ship_qty（Invoice/PL 用）。
    """
    if invoice_no is None:
        return [(line, line.quantity) for line in lines]
    out: list[tuple[OrderLine, Decimal]] = []
    for line in lines:
        if not invoice_no_matches(line, invoice_no, document_type=document_type, seller=seller):
            continue
        qty = line.ship_qty or Decimal("0")
        if qty == 0:
            continue
        out.append((line, qty))
    return out


def _build_cost_breakdown_lines(
    lines: tuple[DocumentLine, ...],
) -> tuple[DocumentCostBreakdownLine, ...]:
    """将 Profile 声明的组件价格展开为去重后的 Invoice 明细。"""

    result: list[DocumentCostBreakdownLine] = []
    seen: set[tuple[str, str, str, str]] = set()
    for line in lines:
        for item in line.cost_breakdown:
            key = (line.po_no, line.item_line_no, line.item_number or line.sap, item.component)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                DocumentCostBreakdownLine(
                    po_no=line.po_no,
                    item_line_no=line.item_line_no,
                    item_number=line.item_number or line.sap,
                    description=f"{line.description} - {item.component}",
                    unit_price=item.unit_price,
                    component=item.component,
                    source_row=line.source_row,
                    source_field=item.source_field,
                )
            )
    return tuple(result)


def _first_non_empty(values: object) -> str | None:
    for v in values:  # type: ignore[attr-defined]
        if v:
            return str(v)
    return None


__all__ = [
    "CODE_INVOICE_NO_MISSING",
    "CODE_LINE_NOT_PRICED",
    "CODE_NO_SHIPMENT_FOR_INVOICE",
    "CODE_PACKING_DATA_MISSING",
    "BuildResult",
    "DocumentCostBreakdownLine",
    "DocumentLine",
    "DocumentModel",
    "build_invoice_model",
    "build_pi_model",
    "build_pl_model",
    "build_po_model",
]
