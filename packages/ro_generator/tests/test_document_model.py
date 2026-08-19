"""Document model 测试 — 新 base 文件数据模型。"""

from __future__ import annotations

from decimal import Decimal

from ro_generator.document_model import (
    CODE_INVOICE_NO_MISSING,
    CODE_LINE_NOT_PRICED,
    CODE_NO_SHIPMENT_FOR_INVOICE,
    CODE_PACKING_DATA_MISSING,
    build_invoice_model,
    build_pi_model,
    build_pl_model,
)
from ro_generator.models import OrderLine, Product


def make_product(sap="21-44640", description="CB2500.B2", category=1, gs_model="Q1", **kw):
    defaults = {
        "sap": sap,
        "description": description,
        "category": category,
        "gs_model": gs_model,
        "carton_qty": Decimal("24"),
        "net_weight": Decimal("8.5"),
        "gross_weight": Decimal("10.1"),
        "length": Decimal("48"),
        "width": Decimal("31"),
        "height": Decimal("35"),
        "cbm": Decimal("0.052"),
        "inner_case_value": Decimal("2"),
        **kw,
    }
    return Product(**defaults)


def make_order_line(
    po_no="4500030844",
    item_line_no="10",
    sap="21-44640",
    description="CB2500.B2",
    category=1,
    quantity=Decimal("100"),
    product=None,
    prices=None,
    subtotals=None,
    invoice_no="INV-001",
    ship_qty=Decimal("100"),
    carton_count=Decimal("5"),
    total_cbm=Decimal("0.36"),
    net_weight=Decimal("8.5"),
    gross_weight=Decimal("10.1"),
    **kw,
):
    p = product or make_product(sap=sap, description=description, category=category)
    defaults = {
        "po_no": po_no,
        "item_line_no": item_line_no,
        "sap": sap,
        "description": description,
        "category": category,
        "quantity": quantity,
        "product": p,
        "invoice_no": invoice_no,
        "ship_qty": ship_qty,
        "carton_count": carton_count,
        "total_cbm": total_cbm,
        "net_weight": net_weight,
        "gross_weight": gross_weight,
        **kw,
    }
    if prices:
        defaults["prices"] = prices
    if subtotals:
        defaults["subtotals"] = subtotals
    return OrderLine(**defaults)


class TestPI:
    def test_pi_uses_full_quantity(self):
        line = make_order_line(quantity=Decimal("100"))
        result = build_pi_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="4500030844")
        assert result.model is not None
        assert result.model.total_quantity == Decimal("100")
        assert result.model.invoice_no is None

    def test_pi_without_price_warns(self):
        line = make_order_line(quantity=Decimal("100"), prices={})
        result = build_pi_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="4500030844")
        assert result.model is not None
        assert any(m.code == CODE_LINE_NOT_PRICED for m in result.messages)


class TestInvoice:
    def test_invoice_filters_by_invoice_no_and_uses_ship_qty(self):
        line1 = make_order_line(item_line_no="10", invoice_no="INV-001", ship_qty=Decimal("80"))
        line2 = make_order_line(
            item_line_no="20",
            sap="21-44641",
            description="X",
            invoice_no="INV-002",
            ship_qty=Decimal("100"),
        )
        result = build_invoice_model(
            (line1, line2), seller="GS PTE", buyer="EMAX PTE", po_no="P", invoice_no="INV-001"
        )
        assert result.model is not None
        assert result.model.total_quantity == Decimal("80")
        assert len(result.model.lines) == 1

    def test_invoice_uses_po_record_description_when_present(self):
        line = make_order_line(
            description="DB Description",
            po_record_description="PO Record Description",
        )
        result = build_invoice_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert result.model.lines[0].description == "PO Record Description"

    def test_invoice_without_invoice_no_filter_uses_full_quantity(self):
        line = make_order_line(quantity=Decimal("100"), ship_qty=Decimal("100"))
        result = build_invoice_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert result.model.total_quantity == Decimal("100")

    def test_invoice_missing_invoice_no_warns(self):
        line = make_order_line(invoice_no=None)
        result = build_invoice_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert any(
            m.kind == "warning" and m.code == CODE_INVOICE_NO_MISSING for m in result.messages
        )

    def test_no_shipment_for_invoice_blocks(self):
        line = make_order_line(invoice_no="INV-001", ship_qty=Decimal("0"))
        result = build_invoice_model(
            (line,), seller="GS PTE", buyer="EMAX PTE", po_no="P", invoice_no="INV-002"
        )
        assert result.model is None
        assert any(m.code == CODE_NO_SHIPMENT_FOR_INVOICE for m in result.messages)

    def test_invoice_unit_price_uses_current_row_po_record_price_not_data_base(self):
        db_price = {("GS PTE", "EMAX PTE"): Decimal("32.80")}
        first = make_order_line(
            invoice_no="INV-01",
            ship_qty=Decimal("10"),
            source_row=10,
            prices=db_price,
            po_record_prices={("GS PTE", "EMAX PTE"): Decimal("11.00")},
        )
        second = make_order_line(
            invoice_no="INV-02",
            ship_qty=Decimal("10"),
            source_row=25,
            prices=db_price,
            po_record_prices={("GS PTE", "EMAX PTE"): Decimal("30.00")},
        )
        inv1 = build_invoice_model(
            (first, second),
            seller="GS PTE",
            buyer="EMAX PTE",
            po_no="4500030844",
            invoice_no="INV-01",
        )
        inv2 = build_invoice_model(
            (first, second),
            seller="GS PTE",
            buyer="EMAX PTE",
            po_no="4500030844",
            invoice_no="INV-02",
        )
        assert inv1.model is not None
        assert inv2.model is not None
        assert inv1.model.lines[0].unit_price == Decimal("11.00")
        assert inv1.model.lines[0].amount == Decimal("110.00")
        assert inv2.model.lines[0].unit_price == Decimal("30.00")
        assert inv2.model.lines[0].amount == Decimal("300.00")

    def test_invoice_sk_and_ym_share_po_record_k_column_price(self):
        shared = Decimal("28.00")
        line = make_order_line(
            invoice_no="SKYM-001",
            ship_qty=Decimal("4"),
            sk_ym_invoice_no="SKYM-001",
            prices={
                ("SK", "YM"): Decimal("99.00"),
                ("YM", "GS PTE"): Decimal("99.00"),
            },
            po_record_prices={
                ("SK", "YM"): shared,
                ("YM", "GS PTE"): shared,
            },
        )
        sk = build_invoice_model(
            (line,), seller="SK", buyer="YM", po_no="P", invoice_no="SKYM-001"
        )
        ym = build_invoice_model(
            (line,), seller="YM", buyer="GS PTE", po_no="P", invoice_no="SKYM-001"
        )
        assert sk.model is not None
        assert ym.model is not None
        assert sk.model.lines[0].unit_price == shared
        assert ym.model.lines[0].unit_price == shared

    def test_invoice_emax_uses_po_record_o_column_price(self):
        line = make_order_line(
            invoice_no="INV-001",
            ship_qty=Decimal("2"),
            prices={("EMAX PTE", "PF"): Decimal("88.80")},
            po_record_prices={("EMAX PTE", "PF"): Decimal("38.00")},
        )
        result = build_invoice_model(
            (line,), seller="EMAX PTE", buyer="PF", po_no="P", invoice_no="INV-001"
        )
        assert result.model is not None
        assert result.model.lines[0].unit_price == Decimal("38.00")

    def test_invoice_missing_po_record_price_warns(self):
        line = make_order_line(
            invoice_no="INV-001",
            ship_qty=Decimal("10"),
            prices={("GS PTE", "EMAX PTE"): Decimal("32.80")},
            po_record_prices={},
        )
        result = build_invoice_model(
            (line,), seller="GS PTE", buyer="EMAX PTE", po_no="P", invoice_no="INV-001"
        )
        assert result.model is not None
        assert result.model.lines[0].unit_price == Decimal("0")
        assert any(m.code == CODE_LINE_NOT_PRICED for m in result.messages)


class TestPL:
    def test_pl_still_uses_data_base_price_not_po_record(self):
        line = make_order_line(
            invoice_no="INV-001",
            ship_qty=Decimal("50"),
            prices={("GS PTE", "EMAX PTE"): Decimal("32.80")},
            po_record_prices={("GS PTE", "EMAX PTE"): Decimal("11.00")},
        )
        result = build_pl_model(
            (line,), seller="GS PTE", buyer="EMAX PTE", po_no="P", invoice_no="INV-001"
        )
        assert result.model is not None
        assert result.model.lines[0].unit_price == Decimal("32.80")

    def test_pl_filters_by_invoice_no(self):
        line1 = make_order_line(item_line_no="10", invoice_no="INV-001", ship_qty=Decimal("50"))
        line2 = make_order_line(
            item_line_no="20",
            sap="21-44641",
            description="X",
            invoice_no="INV-002",
            ship_qty=Decimal("100"),
        )
        result = build_pl_model(
            (line1, line2), seller="GS PTE", buyer="EMAX PTE", po_no="P", invoice_no="INV-001"
        )
        assert result.model is not None
        assert result.model.total_quantity == Decimal("50")
        assert result.model.lines[0].carton_count == Decimal("5")
        assert result.model.lines[0].net_weight == Decimal("42.50")
        assert result.model.lines[0].gross_weight == Decimal("50.50")
        assert result.model.lines[0].cbm == Decimal("0.36")

    def test_pl_missing_packing_warns(self):
        line = make_order_line(carton_count=None)
        result = build_pl_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert any(m.code == CODE_PACKING_DATA_MISSING for m in result.messages)

    def test_pl_missing_invoice_no_warns(self):
        line = make_order_line(invoice_no=None)
        result = build_pl_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert any(
            m.kind == "warning" and m.code == CODE_INVOICE_NO_MISSING for m in result.messages
        )

    def test_pl_zero_packing_values_do_not_warn_missing(self):
        line = make_order_line(
            carton_count=Decimal("0"),
            net_weight=Decimal("0"),
            gross_weight=Decimal("0"),
            total_cbm=Decimal("0"),
        )
        result = build_pl_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert not any(m.code == CODE_PACKING_DATA_MISSING for m in result.messages)
