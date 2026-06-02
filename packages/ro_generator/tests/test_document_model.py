"""Document model 测试：覆盖完整 PO 数量、月度切片、合计、阻断条件。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from ro_generator.document_model import (
    CODE_FACTORY_DOC_NO_MISSING,
    CODE_INVOICE_NO_MISSING,
    CODE_LINE_NOT_PRICED,
    CODE_NO_SHIPMENT_IN_MONTH,
    BuildResult,
    DocumentModel,
    build_invoice_model,
)
from ro_generator.models import OrderLine, Product
from ro_generator.schema import (
    ENTITY_EMAX_PTE,
    ENTITY_GS_PTE,
    ENTITY_PF,
    ENTITY_SK_YM,
)

# ————————————————————————————————————————
# Fixture builders
# ————————————————————————————————————————


def make_product(sap: str = "21-44640", **overrides: object) -> Product:
    defaults: dict[str, object] = {
        "sap": sap,
        "description": "CB2500.B2",
        "category": 1,
        "gs_model": "Q1",
    }
    defaults.update(overrides)
    return Product(**defaults)  # type: ignore[arg-type]


def make_order_line(
    *,
    sap: str = "21-44640",
    quantity: Decimal | int = Decimal("100"),
    prices: dict[tuple[str, str], Decimal] | None = None,
    monthly_shipments: dict[str, Decimal] | None = None,
    invoice_no: str | None = "INV-001",
    factory_doc_no: str | None = "FDOC-001",
    ship_to: str | None = "EMAX HQ",
    item_line_no: str = "10",
    description: str = "CB2500.B2",
    product: Product | None = None,
) -> OrderLine:
    qty = quantity if isinstance(quantity, Decimal) else Decimal(quantity)
    if prices is None:
        prices = {
            (ENTITY_SK_YM, ENTITY_GS_PTE): Decimal("28.0"),
            (ENTITY_GS_PTE, ENTITY_EMAX_PTE): Decimal("32.8"),
            (ENTITY_EMAX_PTE, ENTITY_PF): Decimal("38.0"),
        }
    subtotals = {seg: (price * qty).quantize(Decimal("0.01")) for seg, price in prices.items()}
    return OrderLine(
        po_no="4500030844",
        item_line_no=item_line_no,
        sap=sap,
        description=description,
        category=1,
        quantity=qty,
        product=product or make_product(sap=sap),
        ship_to=ship_to,
        invoice_no=invoice_no,
        factory_doc_no=factory_doc_no,
        prices=prices,
        subtotals=subtotals,
        monthly_shipments=monthly_shipments or {},
    )


# ————————————————————————————————————————
# 完整 PO 数量（不指定月份）
# ————————————————————————————————————————


class TestFullPoQuantity:
    def test_single_line_invoice(self) -> None:
        lines = (make_order_line(),)
        result = build_invoice_model(
            lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="4500030844"
        )
        assert isinstance(result, BuildResult)
        assert result.messages == ()
        assert result.model is not None
        model = result.model
        assert isinstance(model, DocumentModel)
        assert model.document_type == "INVOICE"
        assert model.seller == ENTITY_GS_PTE
        assert model.buyer == ENTITY_EMAX_PTE
        assert model.po_no == "4500030844"
        assert model.invoice_no == "INV-001"
        assert model.factory_doc_no == "FDOC-001"
        assert model.invoice_month is None
        assert model.ship_to == "EMAX HQ"

    def test_line_uses_segment_price(self) -> None:
        lines = (make_order_line(quantity=100),)
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is not None
        line = result.model.lines[0]
        assert line.unit_price == Decimal("32.8")
        assert line.quantity == Decimal("100")
        assert line.amount == Decimal("3280.00")

    def test_totals_match_sum(self) -> None:
        lines = (
            make_order_line(sap="21-44640", quantity=100),
            make_order_line(sap="21-44641", quantity=200, item_line_no="20"),
        )
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is not None
        # 100 + 200
        assert result.model.total_quantity == Decimal("300")
        # 100*32.8 + 200*32.8 = 9840
        assert result.model.total_amount == Decimal("9840.00")

    def test_different_segments_use_different_prices(self) -> None:
        lines = (make_order_line(quantity=100),)
        # GS→EMAX 段 32.8 vs SK→GS 段 28.0
        result_gs = build_invoice_model(
            lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P"
        )
        result_sk = build_invoice_model(lines, seller=ENTITY_SK_YM, buyer=ENTITY_GS_PTE, po_no="P")
        assert result_gs.model is not None
        assert result_sk.model is not None
        assert result_gs.model.total_amount == Decimal("3280.00")
        assert result_sk.model.total_amount == Decimal("2800.00")


# ————————————————————————————————————————
# 月度切片
# ————————————————————————————————————————


class TestMonthlySlice:
    def test_takes_monthly_quantity(self) -> None:
        lines = (
            make_order_line(
                quantity=300,
                monthly_shipments={"2601": Decimal("100"), "2602": Decimal("200")},
            ),
        )
        result = build_invoice_model(
            lines,
            seller=ENTITY_GS_PTE,
            buyer=ENTITY_EMAX_PTE,
            po_no="P",
            invoice_month="2601",
        )
        assert result.model is not None
        assert result.model.invoice_month == "2601"
        assert result.model.lines[0].quantity == Decimal("100")
        assert result.model.total_quantity == Decimal("100")
        assert result.model.total_amount == Decimal("3280.00")

    def test_drops_lines_with_no_shipment_in_month(self) -> None:
        # 第一行 1 月有货，第二行 1 月无货
        lines = (
            make_order_line(
                sap="21-44640",
                quantity=100,
                monthly_shipments={"2601": Decimal("80")},
            ),
            make_order_line(
                sap="21-44641",
                item_line_no="20",
                quantity=100,
                monthly_shipments={"2602": Decimal("100")},
            ),
        )
        result = build_invoice_model(
            lines,
            seller=ENTITY_GS_PTE,
            buyer=ENTITY_EMAX_PTE,
            po_no="P",
            invoice_month="2601",
        )
        assert result.model is not None
        assert len(result.model.lines) == 1
        assert result.model.lines[0].sap == "21-44640"
        assert result.model.lines[0].quantity == Decimal("80")

    def test_no_shipment_in_month_blocks(self) -> None:
        lines = (
            make_order_line(
                quantity=100,
                monthly_shipments={"2602": Decimal("100")},
            ),
        )
        result = build_invoice_model(
            lines,
            seller=ENTITY_GS_PTE,
            buyer=ENTITY_EMAX_PTE,
            po_no="P",
            invoice_month="2601",
        )
        assert result.model is None
        codes = [m.code for m in result.messages]
        assert CODE_NO_SHIPMENT_IN_MONTH in codes

    def test_zero_amount_treated_as_no_shipment(self) -> None:
        lines = (
            make_order_line(
                quantity=100,
                monthly_shipments={"2601": Decimal("0")},
            ),
        )
        result = build_invoice_model(
            lines,
            seller=ENTITY_GS_PTE,
            buyer=ENTITY_EMAX_PTE,
            po_no="P",
            invoice_month="2601",
        )
        assert result.model is None


# ————————————————————————————————————————
# 链段定价缺失
# ————————————————————————————————————————


class TestSegmentPricing:
    def test_unpriced_line_blocks(self) -> None:
        # 该行只在 SK→GS 段定价，但请求 GS→EMAX
        lines = (
            make_order_line(
                quantity=100,
                prices={(ENTITY_SK_YM, ENTITY_GS_PTE): Decimal("28.0")},
            ),
        )
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is None
        codes = [m.code for m in result.messages]
        assert CODE_LINE_NOT_PRICED in codes

    def test_partial_unpriced_blocks_whole(self) -> None:
        """只要有一行在该段无价就不输出半成品 Invoice。"""
        lines = (
            make_order_line(sap="21-44640", quantity=100),
            make_order_line(
                sap="21-44641",
                quantity=200,
                item_line_no="20",
                prices={(ENTITY_SK_YM, ENTITY_GS_PTE): Decimal("28.0")},  # 仅这段
            ),
        )
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is None


# ————————————————————————————————————————
# Invoice 必填字段
# ————————————————————————————————————————


class TestInvoiceRequiredFields:
    def test_missing_invoice_no_blocks(self) -> None:
        lines = (make_order_line(invoice_no=None),)
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is None
        codes = [m.code for m in result.messages]
        assert CODE_INVOICE_NO_MISSING in codes

    def test_missing_factory_doc_no_blocks(self) -> None:
        lines = (make_order_line(factory_doc_no=None),)
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is None
        codes = [m.code for m in result.messages]
        assert CODE_FACTORY_DOC_NO_MISSING in codes

    def test_takes_first_non_empty_invoice_no(self) -> None:
        # 部分行有 INV#，部分没有：取首个非空
        lines = (
            make_order_line(invoice_no=None, factory_doc_no=None),
            make_order_line(
                sap="21-44641", item_line_no="20", invoice_no="INV-002", factory_doc_no="FDOC-002"
            ),
        )
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        assert result.model is not None
        assert result.model.invoice_no == "INV-002"
        assert result.model.factory_doc_no == "FDOC-002"

    def test_both_missing_reports_both(self) -> None:
        lines = (make_order_line(invoice_no=None, factory_doc_no=None),)
        result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
        codes = [m.code for m in result.messages]
        assert CODE_INVOICE_NO_MISSING in codes
        assert CODE_FACTORY_DOC_NO_MISSING in codes


# ————————————————————————————————————————
# 模型不可变
# ————————————————————————————————————————


@pytest.mark.parametrize("_label", ["smoke"])
def test_result_is_immutable(_label: str) -> None:
    lines = (make_order_line(),)
    result = build_invoice_model(lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="P")
    assert isinstance(result.messages, tuple)
    assert result.model is not None
    assert isinstance(result.model.lines, tuple)
