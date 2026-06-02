"""Document model：把 OrderLine 列表转成具体单据的视图模型。

设计边界：
- document_model 关心"这一类单据的视图长什么样"，不关心模板单元格位置
  （那是 template_mapping 的职责）
- 由 (seller, buyer) 决定从 OrderLine.subtotals 中取哪一段
- 数量来源：完整 PO 数量 vs 月度出货数量（产品方案 §10.3）
- 校验只产出本层能产生的信息
- 不重复 resolver 已经报过的错误
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from ro_generator.models import DocumentType, OrderLine, ValidationMessage
from ro_generator.schema import SHEET_PO_RECORD

# —————————————————————————————————————
# 校验消息 code
# —————————————————————————————————————

CODE_LINE_NOT_PRICED: Final = "LINE_NOT_PRICED_FOR_SEGMENT"
CODE_INVOICE_NO_MISSING: Final = "INVOICE_NO_MISSING"
CODE_FACTORY_DOC_NO_MISSING: Final = "FACTORY_DOC_NO_MISSING"
CODE_NO_SHIPMENT_IN_MONTH: Final = "NO_SHIPMENT_IN_MONTH"
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

    item_line_no: str
    sap: str
    description: str
    gs_model: str | None
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    source_row: int | None = None
    carton_count: Decimal | None = None
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    cbm: Decimal | None = None


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
    invoice_no: str | None = None
    factory_doc_no: str | None = None
    invoice_month: str | None = None
    total_carton_count: Decimal | None = None
    total_net_weight: Decimal | None = None
    total_gross_weight: Decimal | None = None
    total_cbm: Decimal | None = None
    ship_to: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildResult:
    """build_*_model 的返回值。`model` 为 None 时 messages 包含阻断原因。"""

    model: DocumentModel | None
    messages: tuple[ValidationMessage, ...]


# —————————————————————————————————————
# 共享：定价校验 + 行装配
# —————————————————————————————————————

_Segment = tuple[str, str]


def _assemble_lines(
    lines: tuple[OrderLine, ...],
    segment: _Segment,
    invoice_month: str | None,
    po_no: str,
    *,
    packing: bool = False,
) -> tuple[list[DocumentLine] | None, list[ValidationMessage]]:
    """价格段校验 + 月度切片 + DocumentLine 装配（四类单据共用）。

    返回 (doc_lines, messages)。doc_lines 在阻断时为 None。
    `packing=True` 时，每行要求装箱数据完整，缺一项即阻断。
    """
    messages: list[ValidationMessage] = []

    sliced = _slice_by_month(lines, invoice_month)
    if invoice_month is not None and not sliced:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_NO_SHIPMENT_IN_MONTH,
                message=f"PO {po_no} 在月份 {invoice_month} 没有出货数据",
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
                    kind="blocking_error",
                    code=CODE_LINE_NOT_PRICED,
                    message=(
                        f"行（SAP {original_line.sap}）在链段 {segment[0]}→{segment[1]} 下无单价"
                    ),
                    sheet=SHEET_PO_RECORD,
                    field="SAP Number",
                )
            )
            continue
        amount = (unit_price * line_quantity).quantize(Decimal("0.01"))

        if packing:
            missing = _collect_missing_packing_fields(original_line)
            if missing:
                messages.append(
                    ValidationMessage(
                        kind="blocking_error",
                        code=CODE_PACKING_DATA_MISSING,
                        message=(
                            f"行（SAP {original_line.sap}）缺少装箱数据：{', '.join(missing)}"
                        ),
                        sheet=SHEET_PO_RECORD,
                        field=next(iter(missing)),
                    )
                )
                continue

        doc_lines.append(
            DocumentLine(
                item_line_no=original_line.item_line_no,
                sap=original_line.sap,
                description=original_line.description,
                gs_model=original_line.product.gs_model,
                quantity=line_quantity,
                unit_price=unit_price,
                amount=amount,
                source_row=original_line.source_row,
                carton_count=original_line.carton_count if packing else None,
                net_weight=original_line.net_weight if packing else None,
                gross_weight=original_line.gross_weight if packing else None,
                cbm=original_line.total_cbm if packing else None,
            )
        )

    if any(m.code == CODE_LINE_NOT_PRICED for m in messages):
        return None, messages
    if packing and any(m.code == CODE_PACKING_DATA_MISSING for m in messages):
        return None, messages
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


# —————————————————————————————————————
# PI — Proforma Invoice
# —————————————————————————————————————


def build_pi_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
) -> BuildResult:
    """PI ：使用完整 PO 数量（产品方案 §10.3）。不查 INV# / FACTORY DOC NO.。"""
    doc_lines, messages = _assemble_lines(
        lines,
        (seller, buyer),
        invoice_month=None,
        po_no=po_no,
    )
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)

    model = DocumentModel(
        document_type="PI",
        seller=seller,
        buyer=buyer,
        po_no=po_no,
        lines=tuple(doc_lines),
        total_quantity=total_qty,
        total_amount=total_amt,
        ship_to=ship_to,
    )
    return BuildResult(model=model, messages=tuple(messages))


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
    """PO ：与 PI 结构相同，使用完整 PO 数量。"""
    doc_lines, messages = _assemble_lines(
        lines,
        (seller, buyer),
        invoice_month=None,
        po_no=po_no,
    )
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)

    model = DocumentModel(
        document_type="PO",
        seller=seller,
        buyer=buyer,
        po_no=po_no,
        lines=tuple(doc_lines),
        total_quantity=total_qty,
        total_amount=total_amt,
        ship_to=ship_to,
    )
    return BuildResult(model=model, messages=tuple(messages))


# —————————————————————————————————————
# Invoice
# —————————————————————————————————————


def build_invoice_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_month: str | None = None,
) -> BuildResult:
    """Invoice ：支持月度切片，要求 INV# + FACTORY DOC NO. 都存在。"""
    segment = (seller, buyer)
    messages: list[ValidationMessage] = []

    doc_lines, assemble_msgs = _assemble_lines(
        lines,
        segment,
        invoice_month=invoice_month,
        po_no=po_no,
    )
    if assemble_msgs:
        messages.extend(assemble_msgs)
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    invoice_no = _first_non_empty(line.invoice_no for line in lines)
    factory_doc_no = _first_non_empty(line.factory_doc_no for line in lines)
    if not invoice_no:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_INVOICE_NO_MISSING,
                message="Invoice 单据要求 INV#，但 PO record 中未填写",
                sheet=SHEET_PO_RECORD,
                field="INV#",
            )
        )
    if not factory_doc_no:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_FACTORY_DOC_NO_MISSING,
                message="Invoice 单据要求 FACTORY DOC NO.，但 PO record 中未填写",
                sheet=SHEET_PO_RECORD,
                field="FACTORY DOC NO.",
            )
        )
    if not invoice_no or not factory_doc_no:
        return BuildResult(model=None, messages=tuple(messages))

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)

    model = DocumentModel(
        document_type="INVOICE",
        seller=seller,
        buyer=buyer,
        po_no=po_no,
        lines=tuple(doc_lines),
        total_quantity=total_qty,
        total_amount=total_amt,
        invoice_no=invoice_no,
        factory_doc_no=factory_doc_no,
        invoice_month=invoice_month,
        ship_to=ship_to,
    )
    return BuildResult(model=model, messages=tuple(messages))


# —————————————————————————————————————
# PL — Packing List
# —————————————————————————————————————


def build_pl_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_month: str | None = None,
) -> BuildResult:
    """PL ：与 Invoice 共享月度切片 + INV# 要求，额外要求装箱字段完整。

    每行必须齐备 CTNS、N/W、G/W、TOTAL CBM（产品方案 §11 阻断）。
    """
    segment = (seller, buyer)
    messages: list[ValidationMessage] = []

    doc_lines, assemble_msgs = _assemble_lines(
        lines,
        segment,
        invoice_month=invoice_month,
        po_no=po_no,
        packing=True,
    )
    if assemble_msgs:
        messages.extend(assemble_msgs)
    if doc_lines is None:
        return BuildResult(model=None, messages=tuple(messages))

    invoice_no = _first_non_empty(line.invoice_no for line in lines)
    factory_doc_no = _first_non_empty(line.factory_doc_no for line in lines)
    if not invoice_no:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_INVOICE_NO_MISSING,
                message="Packing List 要求 INV#，但 PO record 中未填写",
                sheet=SHEET_PO_RECORD,
                field="INV#",
            )
        )
    if not factory_doc_no:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_FACTORY_DOC_NO_MISSING,
                message="Packing List 要求 FACTORY DOC NO.，但 PO record 中未填写",
                sheet=SHEET_PO_RECORD,
                field="FACTORY DOC NO.",
            )
        )
    if not invoice_no or not factory_doc_no:
        return BuildResult(model=None, messages=tuple(messages))

    total_qty = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amt = sum((dl.amount for dl in doc_lines), Decimal(0))
    total_carton = sum(
        (dl.carton_count for dl in doc_lines if dl.carton_count is not None), Decimal(0)
    )
    total_nw = sum((dl.net_weight for dl in doc_lines if dl.net_weight is not None), Decimal(0))
    total_gw = sum((dl.gross_weight for dl in doc_lines if dl.gross_weight is not None), Decimal(0))
    total_cbm = sum((dl.cbm for dl in doc_lines if dl.cbm is not None), Decimal(0))
    ship_to = _first_non_empty(line.ship_to for line in lines)

    model = DocumentModel(
        document_type="PL",
        seller=seller,
        buyer=buyer,
        po_no=po_no,
        lines=tuple(doc_lines),
        total_quantity=total_qty,
        total_amount=total_amt,
        invoice_no=invoice_no,
        factory_doc_no=factory_doc_no,
        invoice_month=invoice_month,
        ship_to=ship_to,
        total_carton_count=total_carton,
        total_net_weight=total_nw,
        total_gross_weight=total_gw,
        total_cbm=total_cbm,
    )
    return BuildResult(model=model, messages=tuple(messages))


# —————————————————————————————————————
# helpers
# —————————————————————————————————————


def _slice_by_month(
    lines: tuple[OrderLine, ...],
    invoice_month: str | None,
) -> list[tuple[OrderLine, Decimal]]:
    """按月份切片，返回 (原行, 该月数量) 列表。

    invoice_month 为 None 时返回每行的完整 quantity。
    某行该月无出货时被剔除。
    """
    if invoice_month is None:
        return [(line, line.quantity) for line in lines]
    out: list[tuple[OrderLine, Decimal]] = []
    for line in lines:
        amount = line.monthly_shipments.get(invoice_month)
        if amount is None or amount == 0:
            continue
        out.append((line, amount))
    return out


def _first_non_empty(values: object) -> str | None:
    """从迭代器中取首个非空字符串；都没有则返回 None。"""
    for v in values:  # type: ignore[attr-defined]
        if v:
            return str(v)
    return None


__all__ = [
    "CODE_FACTORY_DOC_NO_MISSING",
    "CODE_INVOICE_NO_MISSING",
    "CODE_LINE_NOT_PRICED",
    "CODE_NO_SHIPMENT_IN_MONTH",
    "CODE_PACKING_DATA_MISSING",
    "BuildResult",
    "DocumentLine",
    "DocumentModel",
    "build_invoice_model",
    "build_pi_model",
    "build_pl_model",
    "build_po_model",
]
