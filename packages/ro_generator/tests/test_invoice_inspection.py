"""Read-only invoice-group inspection tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ro_generator.invoice_groups import InvoiceHeaderContext, InvoiceInspection
from ro_generator.invoice_inspection import (
    CODE_INVOICE_GROUP_HEADER_CONFLICT,
    dedupe_messages,
    inspect_invoice_group_from_snapshot,
)
from ro_generator.models import Product, ValidationMessage
from ro_generator.workbook_reader import ROW_NUMBER_KEY
from ro_generator.workbook_snapshot import WorkbookSnapshot

GROUP_KEY = "invgrp::inspection-test"


def _po_row(
    *,
    source_row: int,
    po_no: str,
    sap: str,
    category: int | None,
    ship_qty: Decimal,
    invoice_no: str,
    factory_document_no: str | None,
) -> dict[str, object]:
    return {
        ROW_NUMBER_KEY: source_row,
        "PO NO.": po_no,
        "SAP Number": sap,
        "CATEGORY": category,
        "INV#": invoice_no,
        "SK/YM INVOICE NO.": factory_document_no,
        "SHIP QTY": ship_qty,
        "CTNS": Decimal("1"),
        "TOTAL CBM": Decimal("0.1"),
    }


def _customer_po_row(*, source_row: int, po_no: str, sap: str) -> dict[str, object]:
    return {
        ROW_NUMBER_KEY: source_row,
        "Purchasing Document": po_no,
        "Material": sap,
        "Item": "10",
        "Order Quantity": Decimal("100"),
        "ship to": f"Ship to {po_no}",
        "final destination": f"Destination {po_no}",
        "manufacturer": f"Manufacturer {po_no}",
    }


def _snapshot() -> WorkbookSnapshot:
    products = {
        "SAP-REEL": Product(
            sap="SAP-REEL",
            description="Reel product",
            category=3,
            prices={
                "SK/reel": Decimal("10"),
                "GS PTE/reel": Decimal("12"),
                "EMAX PTE/reel": Decimal("14"),
            },
        ),
        "SAP-COMBO": Product(
            sap="SAP-COMBO",
            description="Combo product",
            category=1,
            prices={
                "YM/combo": Decimal("20"),
                "GS PTE/combo": Decimal("22"),
                "EMAX PTE/combo": Decimal("24"),
            },
        ),
    }
    po_rows = (
        _po_row(
            source_row=12,
            po_no="PO-2",
            sap="SAP-REEL",
            category=3,
            ship_qty=Decimal("7"),
            invoice_no="INV-001",
            factory_document_no="SK-001",
        ),
        _po_row(
            source_row=8,
            po_no="PO-1",
            sap="SAP-COMBO",
            category=None,
            ship_qty=Decimal("0"),
            invoice_no="INV-001",
            factory_document_no="YM-001",
        ),
        _po_row(
            source_row=6,
            po_no="PO-1",
            sap="SAP-COMBO",
            category=None,
            ship_qty=Decimal("5"),
            invoice_no="INV-001",
            factory_document_no="YM-001",
        ),
        _po_row(
            source_row=10,
            po_no="PO-1",
            sap="SAP-COMBO",
            category=1,
            ship_qty=Decimal("9"),
            invoice_no="INV-001",
            factory_document_no="YM-001",
        ),
    )
    customer_po_rows = (
        _customer_po_row(source_row=2, po_no="PO-1", sap="SAP-COMBO"),
        _customer_po_row(source_row=3, po_no="PO-2", sap="SAP-REEL"),
    )
    summary = InvoiceInspection(
        invoice_group_key=GROUP_KEY,
        display_invoice_no="INV-001",
        status="ready",
        po_nos=("PO-1", "PO-2"),
        po_count=2,
        sellers=("SK", "YM", "GS PTE", "EMAX PTE"),
        seller_invoice_numbers={},
        blocking_count=0,
        conflict_count=0,
        date=None,
    )
    return WorkbookSnapshot(
        base_file="base.xlsx",
        headers_data_base=(),
        headers_po_record=(),
        product_index=products,
        po_rows=po_rows,
        po_index={"PO-1": (1, 2, 3), "PO-2": (0,)},
        invoice_summary=(summary,),
        invoice_index={GROUP_KEY: (0, 1, 2)},
        customer_po_rows=customer_po_rows,
        customer_po_index={"PO-1": (0,), "PO-2": (1,)},
    )


def test_inspection_projects_cross_po_members_in_source_row_order() -> None:
    result = inspect_invoice_group_from_snapshot(_snapshot(), GROUP_KEY)

    assert result.invoice_group_key == GROUP_KEY
    assert result.display_invoice_no == "INV-001"
    assert result.po_nos == ("PO-1", "PO-2")
    assert [row.source_row for row in result.rows] == [6, 12]
    assert 8 not in {row.source_row for row in result.rows}
    assert 10 not in {row.source_row for row in result.rows}
    assert all(row.ship_qty > 0 for row in result.rows)
    assert result.blocking_errors == ()

    combo, reel = result.rows
    assert (
        combo.po_no,
        combo.sap,
        combo.description,
        combo.category,
        combo.ship_qty,
        combo.invoice_no,
        combo.factory_document_no,
        combo.sellers,
    ) == (
        "PO-1",
        "SAP-COMBO",
        "Combo product",
        1,
        Decimal("5"),
        "INV-001",
        "YM-001",
        ("GS PTE", "EMAX PTE"),
    )
    assert reel.sellers == ("SK", "GS PTE", "EMAX PTE")


def test_inspection_unknown_key_returns_structured_blocking_error() -> None:
    result = inspect_invoice_group_from_snapshot(_snapshot(), "invgrp::missing")

    assert result.invoice_group_key == "invgrp::missing"
    assert result.display_invoice_no == ""
    assert result.po_nos == ()
    assert result.rows == ()
    assert result.warnings == ()
    assert [message.code for message in result.blocking_errors] == ["INVOICE_GROUP_NOT_FOUND"]


def test_dedupe_messages_preserves_first_seen_order() -> None:
    duplicate = ValidationMessage(
        kind="warning",
        code="NO_PRICES",
        message="No prices",
        sheet="DATA BASE",
        row=5,
        field="price",
        severity="high",
    )
    other = ValidationMessage(kind="warning", code="OTHER", message="Other")

    assert dedupe_messages((duplicate, other, duplicate)) == (duplicate, other)


def test_each_header_conflict_is_reported_as_blocking() -> None:
    snapshot = _snapshot()
    summary = replace(
        snapshot.invoice_summary[0], status="blocked", blocking_count=2, conflict_count=2
    )
    context = InvoiceHeaderContext(
        values={
            "ship_to": ("Chicago", "Kansas City"),
            "final_destination": ("MO", "TX"),
            "manufacturer_address": (),
        },
        conflicts=("ship_to", "final_destination"),
        source_rows={
            "ship_to": (6, 12),
            "final_destination": (6, 12),
            "manufacturer_address": (),
        },
    )
    snapshot = replace(
        snapshot,
        invoice_summary=(summary,),
        invoice_header_context={GROUP_KEY: context},
    )

    result = inspect_invoice_group_from_snapshot(snapshot, GROUP_KEY)

    conflicts = [
        message
        for message in result.blocking_errors
        if message.code == CODE_INVOICE_GROUP_HEADER_CONFLICT
    ]
    assert [message.field for message in conflicts] == ["ship_to", "final_destination"]
    assert all("PO-1, PO-2" in message.message for message in conflicts)
    assert all("6, 12" in message.message for message in conflicts)
