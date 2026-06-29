"""Invoice group aggregation tests."""

from decimal import Decimal

from ro_generator.invoice_groups import build_invoice_group_key, build_invoice_groups
from ro_generator.models import OrderLine, Product


def _line(
    *,
    po_no: str,
    invoice_no: str | None,
    factory_invoice_no: str | None = None,
    ship_qty: Decimal | None = Decimal("10"),
    category: int = 1,
    ship_to: str | None = None,
) -> OrderLine:
    product = Product(sap=f"SAP-{po_no}", description="Test product", category=category)
    return OrderLine(
        po_no=po_no,
        item_line_no="10",
        sap=product.sap,
        description=product.description,
        category=category,
        quantity=Decimal("100"),
        product=product,
        po_record_category=category,
        invoice_no=invoice_no,
        sk_ym_invoice_no=factory_invoice_no,
        ship_qty=ship_qty,
        ship_to=ship_to,
    )


def test_group_key_matches_canonical_sha256_example() -> None:
    assert build_invoice_group_key(("SKYM-001", "INV-001")) == ("invgrp::5c4da065fc2a5b64")


def test_groups_cross_po_rows_by_cooccurring_invoice_identifiers() -> None:
    result = build_invoice_groups(
        (
            (0, _line(po_no="PO-1", invoice_no="INV-001", factory_invoice_no="SKYM-001")),
            (1, _line(po_no="PO-2", invoice_no="INV-001")),
        )
    )

    assert len(result.summaries) == 1
    summary = result.summaries[0]
    assert summary.display_invoice_no == "INV-001"
    assert summary.po_nos == ("PO-1", "PO-2")
    assert summary.po_count == 2
    assert summary.seller_invoice_numbers == {
        "GS PTE": "INV-001",
        "EMAX PTE": "INV-001-P",
        "YM": "SKYM-001",
    }
    assert result.index[summary.invoice_group_key] == (0, 1)


def test_excludes_zero_and_missing_ship_qty_before_building_edges() -> None:
    result = build_invoice_groups(
        (
            (0, _line(po_no="PO-1", invoice_no="INV-A", factory_invoice_no="FACTORY-A")),
            (
                1,
                _line(
                    po_no="PO-2",
                    invoice_no="INV-B",
                    factory_invoice_no="FACTORY-A",
                    ship_qty=Decimal("0"),
                ),
            ),
            (2, _line(po_no="PO-3", invoice_no="INV-C", ship_qty=None)),
        )
    )

    assert [summary.display_invoice_no for summary in result.summaries] == ["INV-A"]
    assert next(iter(result.index.values())) == (0,)


def test_group_key_is_stable_under_row_reordering() -> None:
    first = _line(po_no="PO-2", invoice_no="INV-001", factory_invoice_no="SKYM-001")
    second = _line(po_no="PO-1", invoice_no="INV-001")

    forward = build_invoice_groups(((4, first), (9, second)))
    reverse = build_invoice_groups(((9, second), (4, first)))

    assert forward.summaries[0].invoice_group_key == reverse.summaries[0].invoice_group_key
    assert forward.summaries[0].po_nos == reverse.summaries[0].po_nos == ("PO-1", "PO-2")
    assert forward.index == reverse.index


def test_factory_reel_group_is_available_to_sk() -> None:
    result = build_invoice_groups(
        ((0, _line(po_no="PO-1", invoice_no=None, factory_invoice_no="SK-001", category=3)),)
    )

    summary = result.summaries[0]
    assert summary.display_invoice_no == "SK-001"
    assert summary.sellers == ("SK",)
    assert summary.seller_invoice_numbers == {"SK": "SK-001"}


def test_header_conflict_blocks_group_summary_and_records_context() -> None:
    result = build_invoice_groups(
        (
            (4, _line(po_no="PO-1", invoice_no="INV-001", ship_to="Kansas City")),
            (9, _line(po_no="PO-2", invoice_no="INV-001", ship_to="Chicago")),
        )
    )

    summary = result.summaries[0]
    context = result.header_context[summary.invoice_group_key]
    assert summary.status == "blocked"
    assert summary.blocking_count == 1
    assert summary.conflict_count == 1
    assert context.conflicts == ("ship_to",)
    assert context.values["ship_to"] == ("Chicago", "Kansas City")
    assert context.source_rows["ship_to"] == (4, 9)
