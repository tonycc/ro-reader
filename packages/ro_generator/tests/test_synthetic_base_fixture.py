"""Regression tests for the tracked synthetic base workbook."""

from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_base.xlsx"


def test_po_record_uses_ship_qty_instead_of_month_columns() -> None:
    workbook = load_workbook(FIXTURE, read_only=True, data_only=False)
    try:
        sheet = workbook["PO record"]
        headers = tuple(cell.value for cell in sheet[4] if cell.value is not None)
    finally:
        workbook.close()

    assert "SHIP QTY" in headers
    assert "BALANCE QTY" in headers
    assert not {f"26{month:02d}" for month in range(1, 13)}.intersection(headers)
