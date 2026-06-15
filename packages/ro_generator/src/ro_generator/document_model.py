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

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from ro_generator.header_rules import resolve_header_field_spec
from ro_generator.line_rules import resolve_line_field_spec
from ro_generator.models import DocumentType, OrderLine, ValidationMessage
from ro_generator.schema import SHEET_PO_RECORD

# —————————————————————————————————————
# 校验消息 code
# —————————————————————————————————————

CODE_LINE_NOT_PRICED: Final = "LINE_NOT_PRICED_FOR_SEGMENT"
CODE_INVOICE_NO_MISSING: Final = "INVOICE_NO_MISSING"
CODE_NO_SHIPMENT_FOR_INVOICE: Final = "NO_SHIPMENT_FOR_INVOICE"
CODE_PACKING_DATA_MISSING: Final = "PACKING_DATA_MISSING"


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
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    cbm: Decimal | None = None
    confirmed_ex_factory_date: date | None = None
    po_ex_factory_date: date | None = None  # PO record "FINAL EX-FACTORY DATE"
    item_number: str = ""  # PO 模板 Item Number，SK/YM 取客户PO Material，其余同 item_line_no
    cp_item: str = ""  # 客户PO "Item" 列值，SK/YM PI 模板 PO item Line Number 来源


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
    pi_no: str | None = None  # PI 编号：SK 用 E10 PO，YM 用 YM PO，GS/EMAX 用客户 PO
    invoice_no: str | None = None
    total_carton_count: Decimal | None = None
    total_net_weight: Decimal | None = None
    total_gross_weight: Decimal | None = None
    total_cbm: Decimal | None = None
    ship_to: str | None = None
    manufacturer_address: str | None = None  # 客户PO "manufacturer" 列
    final_destination: str | None = None  # 客户PO "final destination" 列
    ex_factory_date: date | None = None


@dataclass(frozen=True)
class BuildResult:
    model: DocumentModel | None
    messages: tuple[ValidationMessage, ...]


# —————————————————————————————————————
# 共享：定价校验 + 行装配
# —————————————————————————————————————

_Segment = tuple[str, str]

_PRICE_SEGMENT_OVERRIDES: Final[dict[tuple[str, str], _Segment]] = {
    ("PO", "GS PTE"): ("YM", "GS PTE"),
}
_INVOICE_NO_FROM_SK_YM_SELLERS: Final[frozenset[str]] = frozenset({"SK", "YM"})
_INVOICE_NO_SUFFIX_SELLERS: Final[frozenset[str]] = frozenset({"EMAX PTE"})
_INVOICE_NO_CONTEXT_DOCS: Final[frozenset[str]] = frozenset({"INVOICE", "PL"})


def _price_segment(document_type: str, seller: str, buyer: str) -> _Segment:
    return _PRICE_SEGMENT_OVERRIDES.get((document_type, seller), (seller, buyer))


def invoice_no_for_line(
    line: OrderLine,
    *,
    document_type: str,
    seller: str,
) -> str | None:
    """按单据上下文返回对用户可见、可用于导出的发票号。"""
    if document_type in _INVOICE_NO_CONTEXT_DOCS and seller in _INVOICE_NO_FROM_SK_YM_SELLERS:
        return line.sk_ym_invoice_no
    if document_type in _INVOICE_NO_CONTEXT_DOCS and seller in _INVOICE_NO_SUFFIX_SELLERS:
        return _append_invoice_suffix(line.invoice_no, "-P")
    return line.invoice_no


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
    resolved = invoice_no_for_line(line, document_type=document_type, seller=seller)
    if resolved == requested_invoice_no:
        return True
    if document_type in _INVOICE_NO_CONTEXT_DOCS and seller in _INVOICE_NO_SUFFIX_SELLERS:
        return line.invoice_no == requested_invoice_no
    return False


def _invoice_source_field(document_type: str, seller: str) -> str:
    spec = resolve_header_field_spec("invoice_no", document_type=document_type, seller=seller)
    if spec is not None and spec.source_field:
        return spec.source_field
    return "INV#"


def _append_invoice_suffix(invoice_no: str | None, suffix: str) -> str | None:
    if not invoice_no:
        return None
    return invoice_no if invoice_no.endswith(suffix) else f"{invoice_no}{suffix}"


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
            line, requested_invoice_no, document_type=document_type, seller=seller,
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
                sheet=SHEET_PO_RECORD,
            )
        )
        return None, messages

    doc_lines: list[DocumentLine] = []
    for original_line, line_quantity in sliced:
        unit_price = original_line.prices.get(segment)
        if unit_price is None:
            messages.append(
                ValidationMessage(
                    kind="warning",
                    code=CODE_LINE_NOT_PRICED,
                    severity="high",
                    message=(
                        f"行（SAP {original_line.sap}）在链段 {segment[0]}→{segment[1]} 下无单价"
                    ),
                    sheet=SHEET_PO_RECORD,
                    field="SAP Number",
                )
            )
            unit_price = Decimal("0")
        amount = (unit_price * line_quantity).quantize(Decimal("0.01"))

        if packing:
            missing = _collect_missing_packing_fields(original_line)
            if missing:
                messages.append(
                    ValidationMessage(
                        kind="warning",
                        code=CODE_PACKING_DATA_MISSING,
                        severity="high",
                        message=f"行（SAP {original_line.sap}）缺少装箱数据：{', '.join(missing)}，将填 0",
                        sheet=SHEET_PO_RECORD,
                        field=next(iter(missing)),
                    )
                )

        item_line_spec = resolve_line_field_spec("item_line_no", document_type=document_type, seller=seller)
        item_line_value = original_line.cp_item if item_line_spec.source_field == "item" else original_line.item_line_no
        item_num_spec = resolve_line_field_spec("item_number", document_type=document_type, seller=seller)
        item_num_value = original_line.cp_item if item_num_spec.source_field == "item" else original_line.item_line_no

        ex_factory_spec = resolve_line_field_spec(
            "confirmed_ex_factory_date",
            document_type=document_type,
            seller=seller,
        )
        if ex_factory_spec.source_sheet == SHEET_PO_RECORD:
            ex_factory_date = original_line.po_ex_factory_date
        else:
            ex_factory_date = original_line.confirmed_ex_factory_date

        doc_lines.append(
            DocumentLine(
                po_no=original_line.po_no,
                item_line_no=item_line_value,
                item_number=item_num_value,
                cp_item=original_line.cp_item,
                sap=original_line.sap,
                description=(
                    original_line.po_record_description
                    if use_po_record_description and original_line.po_record_description
                    else original_line.description
                ),
                category=original_line.category,
                gs_model=original_line.product.gs_model,
                quantity=line_quantity,
                unit_price=unit_price,
                amount=amount,
                source_row=original_line.source_row,
                carton_count=original_line.carton_count if packing else None,
                net_weight=original_line.net_weight if packing else None,
                gross_weight=original_line.gross_weight if packing else None,
                cbm=original_line.total_cbm if packing else None,
                confirmed_ex_factory_date=ex_factory_date,
                po_ex_factory_date=original_line.po_ex_factory_date,
            )
        )

    return doc_lines, messages


def _collect_missing_packing_fields(line: OrderLine) -> list[str]:
    missing: list[str] = []
    if line.carton_count is None:
        missing.append("CTNS")
    if line.net_weight is None:
        missing.append("N/W")
    if line.gross_weight is None:
        missing.append("G/W")
    if line.total_cbm is None:
        missing.append("TOTAL CBM")
    return missing


def _resolve_model_ex_factory_date(
    lines: tuple[OrderLine, ...], document_type: str, seller: str,
) -> date | None:
    """根据 header_rules 选择表头出厂日期来源。"""
    spec = resolve_header_field_spec(
        "ex_factory_date",
        document_type=document_type,
        seller=seller,
    )
    if spec.source_sheet == SHEET_PO_RECORD:
        for line in lines:
            if line.po_ex_factory_date is not None:
                return line.po_ex_factory_date
        return None
    for line in lines:
        if line.confirmed_ex_factory_date is not None:
            return line.confirmed_ex_factory_date
    return None


# —————————————————————————————————————
# PI — Proforma Invoice
# —————————————————————————————————————

def build_pi_model(
    lines: tuple[OrderLine, ...],
    *, seller: str, buyer: str, po_no: str, pi_no: str | None = None,
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

    return BuildResult(
        model=DocumentModel(
            document_type="PI", seller=seller, buyer=buyer, po_no=po_no,
            pi_no=pi_no or po_no,
            lines=tuple(doc_lines), total_quantity=total_qty, total_amount=total_amt,
            ship_to=ship_to, manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# PO — Purchase Order
# —————————————————————————————————————

def build_po_model(
    lines: tuple[OrderLine, ...],
    *, seller: str, buyer: str, po_no: str,
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

    return BuildResult(
        model=DocumentModel(
            document_type="PO", seller=seller, buyer=buyer, po_no=po_no,
            lines=tuple(doc_lines), total_quantity=total_qty, total_amount=total_amt,
            ship_to=ship_to, manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# Invoice
# —————————————————————————————————————

def build_invoice_model(
    lines: tuple[OrderLine, ...],
    *, seller: str, buyer: str, po_no: str,
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
        lines, invoice_no, document_type="INVOICE", seller=seller,
    )
    if not inv_no:
        source_field = _invoice_source_field("INVOICE", seller)
        messages.append(
            ValidationMessage(
                kind="warning", code=CODE_INVOICE_NO_MISSING, severity="high",
                message=f"Invoice 单据要求 {source_field}，但 PO record 中未填写",
                sheet=SHEET_PO_RECORD, field=source_field,
            )
        )

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)
    manufacturer_address = _first_non_empty(line.manufacturer_address for line in lines)
    final_destination = _first_non_empty(line.final_destination for line in lines)
    ex_factory_date = _resolve_model_ex_factory_date(lines, "INVOICE", seller)

    return BuildResult(
        model=DocumentModel(
            document_type="INVOICE", seller=seller, buyer=buyer, po_no=po_no,
            lines=tuple(doc_lines), total_quantity=total_qty, total_amount=total_amt,
            invoice_no=inv_no, ship_to=ship_to, manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
        ),
        messages=tuple(messages),
    )


# —————————————————————————————————————
# PL — Packing List
# —————————————————————————————————————

def build_pl_model(
    lines: tuple[OrderLine, ...],
    *, seller: str, buyer: str, po_no: str,
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
        lines, invoice_no, document_type="PL", seller=seller,
    )
    if not inv_no:
        source_field = _invoice_source_field("PL", seller)
        messages.append(
            ValidationMessage(
                kind="warning", code=CODE_INVOICE_NO_MISSING, severity="high",
                message=f"Packing List 要求 {source_field}，但 PO record 中未填写",
                sheet=SHEET_PO_RECORD, field=source_field,
            )
        )

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    total_carton = sum((dl.carton_count for dl in doc_lines if dl.carton_count is not None), Decimal(0))
    total_nw = sum((dl.net_weight for dl in doc_lines if dl.net_weight is not None), Decimal(0))
    total_gw = sum((dl.gross_weight for dl in doc_lines if dl.gross_weight is not None), Decimal(0))
    total_cbm = sum((dl.cbm for dl in doc_lines if dl.cbm is not None), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)
    manufacturer_address = _first_non_empty(line.manufacturer_address for line in lines)
    final_destination = _first_non_empty(line.final_destination for line in lines)
    ex_factory_date = _resolve_model_ex_factory_date(lines, "PL", seller)

    return BuildResult(
        model=DocumentModel(
            document_type="PL", seller=seller, buyer=buyer, po_no=po_no,
            lines=tuple(doc_lines), total_quantity=total_qty, total_amount=total_amt,
            invoice_no=inv_no, ship_to=ship_to, manufacturer_address=manufacturer_address,
            final_destination=final_destination,
            ex_factory_date=ex_factory_date,
            total_carton_count=total_carton, total_net_weight=total_nw,
            total_gross_weight=total_gw, total_cbm=total_cbm,
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
    "DocumentLine",
    "DocumentModel",
    "build_invoice_model",
    "build_pi_model",
    "build_pl_model",
    "build_po_model",
]
