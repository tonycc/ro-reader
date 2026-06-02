"""Document model：把 OrderLine 列表转成具体单据的视图模型。

Phase 1 只实现 Invoice，PI/PO/PL 在 Phase 2 加。

设计边界：
- document_model 关心"这一类单据的视图长什么样"，不关心模板单元格位置
  （那是 template_mapping 的职责）
- 由 (seller, buyer) 决定从 OrderLine.subtotals 中取哪一段
- 数量来源：完整 PO 数量 vs 月度出货数量（产品方案 §10.3）
- 校验只产出本层能产生的信息：链段无价、月份无出货、Invoice 缺 INV# 等
- 不重复 resolver 已经报过的错误（resolver 已确保 lines 都至少有一段价格）
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


# —————————————————————————————————————
# 视图模型
# —————————————————————————————————————


@dataclass(frozen=True)
class DocumentLine:
    """单据中的一行。

    PL 专属字段（carton_count、net/gross weight、cbm）在 Invoice 中保持 None；
    Phase 2 PL 实现时会填充。

    `source_row` 是 PO record 中的源行号，用于双向溯源（产品方案 §4.4）。
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
    """单据视图模型。

    `total_carton_count` 等 PL 合计字段在 Invoice 中保持 None。
    `invoice_no` / `factory_doc_no` 在 PI/PO 中可为 None（Phase 2 处理）。
    """

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
    """build_*_model 的返回值。

    `model` 为 None 时 messages 包含阻断原因。
    """

    model: DocumentModel | None
    messages: tuple[ValidationMessage, ...]


# —————————————————————————————————————
# Invoice 构建
# —————————————————————————————————————


def build_invoice_model(
    lines: tuple[OrderLine, ...],
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_month: str | None = None,
) -> BuildResult:
    """构建 Invoice 视图模型。

    数量来源（产品方案 §10.3）：
    - `invoice_month` 为 None：使用每行的完整 quantity（FINALQTY）
    - `invoice_month` 给定：使用该月的出货数量；为 0 或缺失的行被剔除

    阻断条件：
    - 任意保留行在 (seller, buyer) 段下没有 subtotal/price → LINE_NOT_PRICED
    - 月度切片后没有任何行 → NO_SHIPMENT_IN_MONTH
    - 缺 INV# 或 FACTORY DOC NO. → INVOICE_NO_MISSING / FACTORY_DOC_NO_MISSING
      （Invoice 必填，参见产品方案 §11）
    """
    segment = (seller, buyer)
    messages: list[ValidationMessage] = []

    # 1. 月度切片
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
        return BuildResult(model=None, messages=tuple(messages))

    # 2. 价格段校验 + 行装配
    doc_lines: list[DocumentLine] = []
    for original_line, line_quantity in sliced:
        unit_price = original_line.prices.get(segment)
        if unit_price is None:
            messages.append(
                ValidationMessage(
                    kind="blocking_error",
                    code=CODE_LINE_NOT_PRICED,
                    message=(f"行（SAP {original_line.sap}）在链段 {seller}→{buyer} 下无单价"),
                    sheet=SHEET_PO_RECORD,
                    field="SAP Number",
                )
            )
            continue
        amount = (unit_price * line_quantity).quantize(Decimal("0.01"))
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
            )
        )

    # 任何行未定价就阻断（不输出半成品 Invoice）
    if any(m.code == CODE_LINE_NOT_PRICED for m in messages):
        return BuildResult(model=None, messages=tuple(messages))

    # 3. Invoice 必填字段
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

    # 4. 合计
    total_quantity = sum((dl.quantity for dl in doc_lines), Decimal(0))
    total_amount = sum((dl.amount for dl in doc_lines), Decimal(0))

    # 5. ship_to 取首条非空
    ship_to = _first_non_empty(line.ship_to for line in lines)

    model = DocumentModel(
        document_type="INVOICE",
        seller=seller,
        buyer=buyer,
        po_no=po_no,
        lines=tuple(doc_lines),
        total_quantity=total_quantity,
        total_amount=total_amount,
        invoice_no=invoice_no,
        factory_doc_no=factory_doc_no,
        invoice_month=invoice_month,
        ship_to=ship_to,
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
    某行该月无出货（key 不在或值为 0）时被剔除。
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
    "BuildResult",
    "DocumentLine",
    "DocumentModel",
    "build_invoice_model",
]
