"""Document model 测试 — 新 base 文件数据模型。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from ro_generator.document_model import (
    CODE_INVOICE_NO_MISSING,
    CODE_LINE_NOT_PRICED,
    CODE_NO_SHIPMENT_FOR_INVOICE,
    CODE_PACKING_DATA_MISSING,
    build_invoice_model,
    build_pi_model,
    build_pl_model,
)
from ro_generator.document_preview import build_preview
from ro_generator.generator import BuildDocumentResult
from ro_generator.models import OrderLine, Product
from ro_generator.profiles import create_pf_profile, create_ro_profile, profile_scope
from ro_generator.renderer import render_document
from ro_generator.template_mapping import TemplateMapping, load_template_mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
RO_TEMPLATES = REPO_ROOT / "customer_profiles" / "ro" / "templates"
PF_TEMPLATES = REPO_ROOT / "customer_profiles" / "pf" / "templates"


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
        sk = build_invoice_model((line,), seller="SK", buyer="YM", po_no="P", invoice_no="SKYM-001")
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

    def test_pl_assigns_sequential_carton_numbers(self) -> None:
        line1 = make_order_line(
            item_line_no="10", carton_count=Decimal("2"), ship_qty=Decimal("50")
        )
        line2 = make_order_line(
            item_line_no="20",
            sap="21-44641",
            description="X",
            carton_count=Decimal("3"),
            ship_qty=Decimal("50"),
        )
        result = build_pl_model((line1, line2), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert [(line.carton_from, line.carton_to) for line in result.model.lines] == [
            (1, 2),
            (3, 5),
        ]

    def test_pl_skips_carton_numbers_when_carton_count_is_zero(self) -> None:
        line = make_order_line(
            carton_count=Decimal("0"),
            net_weight=Decimal("0"),
            gross_weight=Decimal("0"),
            total_cbm=Decimal("0"),
        )
        result = build_pl_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert result.model.lines[0].carton_from is None
        assert result.model.lines[0].carton_to is None

    def test_pl_ceils_fractional_cartons_and_continues_numbering(self) -> None:
        line1 = make_order_line(
            item_line_no="10", carton_count=Decimal("0.4"), ship_qty=Decimal("10")
        )
        line2 = make_order_line(
            item_line_no="20",
            sap="21-44641",
            description="X",
            carton_count=Decimal("3"),
            ship_qty=Decimal("50"),
        )
        result = build_pl_model((line1, line2), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert [(line.carton_from, line.carton_to) for line in result.model.lines] == [
            (1, 1),
            (2, 4),
        ]

    def test_pl_stops_carton_numbers_after_unknown_carton_count(self) -> None:
        line1 = make_order_line(item_line_no="10", carton_count=None, ship_qty=Decimal("10"))
        line2 = make_order_line(
            item_line_no="20",
            sap="21-44641",
            description="X",
            carton_count=Decimal("3"),
            ship_qty=Decimal("50"),
        )
        result = build_pl_model((line1, line2), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        assert [(line.carton_from, line.carton_to) for line in result.model.lines] == [
            (None, None),
            (None, None),
        ]

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


def _pf_pl_mapping(seller: str) -> TemplateMapping:
    mapping_name = "gs" if seller == "GS PTE" else "emax"
    return load_template_mapping(PF_TEMPLATES / mapping_name / "mappings" / "pl.yaml")


def _assert_pf_pl_weight_sources(
    *,
    seller: str,
    buyer: str,
    line: OrderLine,
    tmp_path: Path,
    expected_sheet: str,
    expected_row: int | None,
    net_rule: str,
    gross_rule: str,
) -> None:
    mapping = _pf_pl_mapping(seller)
    with profile_scope(create_pf_profile()):
        result = build_pl_model((line,), seller=seller, buyer=buyer, po_no="P")
        assert result.model is not None
        packed = result.model.lines[0]
        assert packed.net_weight_source_sheet == expected_sheet
        assert packed.net_weight_source_field == "N/W"
        assert packed.gross_weight_source_sheet == expected_sheet
        assert packed.gross_weight_source_field == "G/W"
        preview = build_preview(
            BuildDocumentResult(model=result.model, mapping=mapping, messages=result.messages)
        )
        rendered = render_document(result.model, mapping, tmp_path / "pl.xlsx")
    source_by_field = {entry["preview_field"]: entry for entry in preview.source_entries}
    net = source_by_field["line[0].net_weight"]
    gross = source_by_field["line[0].gross_weight"]
    assert net["sheet"] == expected_sheet
    assert net["field"] == "N/W"
    assert net["row"] == expected_row
    assert net_rule in str(net["rule"])
    assert gross["sheet"] == expected_sheet
    assert gross["field"] == "G/W"
    assert gross["row"] == expected_row
    assert gross_rule in str(gross["rule"])
    if expected_sheet != "PO RECORD 26":
        assert "按出货箱数/订单箱数缩放" not in str(net["rule"])
        assert "按出货箱数/订单箱数缩放" not in str(gross["rule"])
    start_row = mapping.lines.start_row
    net_loc = rendered.source_index.lookup_source(f"H{start_row}")
    gross_loc = rendered.source_index.lookup_source(f"I{start_row}")
    assert net_loc is not None
    assert net_loc.sheet == expected_sheet
    assert net_loc.field == "N/W"
    assert net_loc.row == expected_row
    assert gross_loc is not None
    assert gross_loc.sheet == expected_sheet
    assert gross_loc.field == "G/W"
    assert gross_loc.row == expected_row


@pytest.mark.parametrize("seller,buyer", [("GS PTE", "EMAX PTE"), ("EMAX PTE", "PF")])
def test_pf_pl_weight_source_uses_po_record_when_order_total_present(
    seller: str, buyer: str, tmp_path: Path
) -> None:
    line = make_order_line(
        ship_qty=Decimal("24"),
        carton_count=Decimal("2"),
        po_net_weight=Decimal("10"),
        po_gross_weight=Decimal("12"),
        source_row=18,
        product=make_product(
            carton_qty=Decimal("24"), net_weight=Decimal("10"), gross_weight=Decimal("12")
        ),
    )
    _assert_pf_pl_weight_sources(
        seller=seller,
        buyer=buyer,
        line=line,
        tmp_path=tmp_path,
        expected_sheet="PO RECORD 26",
        expected_row=18,
        net_rule="订单总净重",
        gross_rule="订单总毛重",
    )


@pytest.mark.parametrize("seller,buyer", [("GS PTE", "EMAX PTE"), ("EMAX PTE", "PF")])
def test_pf_pl_weight_source_falls_back_to_data_base(
    seller: str, buyer: str, tmp_path: Path
) -> None:
    line = make_order_line(
        ship_qty=Decimal("24"),
        carton_count=Decimal("2"),
        po_net_weight=None,
        po_gross_weight=None,
        source_row=18,
        product=make_product(
            carton_qty=Decimal("24"), net_weight=Decimal("1.10"), gross_weight=Decimal("2.00")
        ),
    )
    _assert_pf_pl_weight_sources(
        seller=seller,
        buyer=buyer,
        line=line,
        tmp_path=tmp_path,
        expected_sheet="DATA BASE TEMPLATE",
        expected_row=None,
        net_rule="单箱 N/W",
        gross_rule="单箱 G/W",
    )


@pytest.mark.parametrize("carton_count", [None, Decimal("0")])
@pytest.mark.parametrize("seller,buyer", [("GS PTE", "EMAX PTE"), ("EMAX PTE", "PF")])
def test_pf_pl_weight_source_falls_back_when_order_cartons_missing(
    carton_count: Decimal | None, seller: str, buyer: str, tmp_path: Path
) -> None:
    line = make_order_line(
        ship_qty=Decimal("1"),
        carton_count=carton_count,
        po_net_weight=Decimal("10"),
        po_gross_weight=Decimal("12"),
        source_row=18,
        product=make_product(
            carton_qty=Decimal("1"), net_weight=Decimal("1.10"), gross_weight=Decimal("2.00")
        ),
    )
    _assert_pf_pl_weight_sources(
        seller=seller,
        buyer=buyer,
        line=line,
        tmp_path=tmp_path,
        expected_sheet="DATA BASE TEMPLATE",
        expected_row=None,
        net_rule="单箱 N/W",
        gross_rule="单箱 G/W",
    )


def test_ro_gs_pl_weight_source_explains_carton_multiply_not_pf_scale(
    tmp_path: Path,
) -> None:
    mapping = load_template_mapping(RO_TEMPLATES / "gs" / "mappings" / "pl.yaml")
    line = make_order_line(
        ship_qty=Decimal("100"),
        carton_count=Decimal("5"),
        net_weight=Decimal("8.5"),
        gross_weight=Decimal("10.1"),
        po_net_weight=Decimal("8.5"),
        po_gross_weight=Decimal("10.1"),
        source_row=5,
    )
    with profile_scope(create_ro_profile()):
        result = build_pl_model((line,), seller="GS PTE", buyer="EMAX PTE", po_no="P")
        assert result.model is not None
        packed = result.model.lines[0]
        assert packed.net_weight == Decimal("42.50")
        assert packed.gross_weight == Decimal("50.50")
        assert packed.net_weight_source_sheet == "PO record"
        assert packed.net_weight_source_field == "N/W"
        assert packed.net_weight_source_rule is not None
        assert "× CTNS" in packed.net_weight_source_rule
        assert "按出货箱数/订单箱数缩放" not in packed.net_weight_source_rule
        preview = build_preview(
            BuildDocumentResult(model=result.model, mapping=mapping, messages=result.messages)
        )
        rendered = render_document(result.model, mapping, tmp_path / "pl.xlsx")
    source_by_field = {entry["preview_field"]: entry for entry in preview.source_entries}
    net = source_by_field["line[0].net_weight"]
    gross = source_by_field["line[0].gross_weight"]
    assert net["sheet"] == "PO record"
    assert net["field"] == "N/W"
    assert net["row"] == 5
    assert net["value"] == "42.50"
    assert "× CTNS" in str(net["rule"])
    assert "按出货箱数/订单箱数缩放" not in str(net["rule"])
    assert "本月出货箱数" not in str(net["rule"])
    assert "× CTNS" in str(gross["rule"])
    loc = rendered.source_index.lookup_source("G9")
    assert loc is not None
    assert loc.sheet == "PO record"
    assert loc.field == "N/W"
    assert loc.row == 5
