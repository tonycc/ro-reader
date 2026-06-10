"""Generator 流水线集成测试 — 新 base 文件数据模型。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from ro_generator.generator import (
    CODE_MAPPING_NOT_FOUND,
    INPUT_INVOICE_NO,
    INPUT_SELLER,
    build_document_model,
    generate,
    preview,
)
from ro_generator.models import DocumentRequest
from ro_generator.resolver import resolve_po_lines
from ro_generator.source_index import SourceIndex
from ro_generator.workbook_reader import WorkbookReader

DATA_BASE_HEADER = [
    "SAP", "Material Description", "Category", "GS MODEL",
    "GS-SK/YM COMBO FOB 2026",
    "EMAX-GS PTE COMBO FOB 2026", "EMAX PTE COMBO FOB 2026",
    "round value", "L", "W", "H",
]

PO_RECORD_HEADER = [
    "PO NO.", "ITEM LINE#", "SAP Number", "DESCRIPTION", "FINALQTY",
    "GS-SK/YM USD FOB", "EMAX-GS PTE FOB", "EMAX PTE",
    "INV#", "SHIP QTY", "CTNS", "TOTAL CBM", "外箱(最终出口装箱率)",
    "N/W", "G/W", "L", "W", "H", "FINAL EX-FACTORY DATE",
]

CUSTOMER_PO_HEADER = ["Purchasing Document", "Item", "Material", "ship to", "Order Quantity", "ship DATE"]


def _write_sheet(ws, headers, rows, header_row=4, first_data_row=5):
    for c_idx, header in enumerate(headers, start=1):
        ws.cell(row=header_row, column=c_idx, value=header)
    for r_offset, row in enumerate(rows):
        for c_idx, header in enumerate(headers, start=1):
            if header in row and row[header] is not None:
                ws.cell(row=first_data_row + r_offset, column=c_idx, value=row[header])


def _default_customer_po_rows(po_record_rows):
    rows = []
    for row in po_record_rows:
        po_no = row.get("PO NO.")
        material = row.get("SAP Number")
        if po_no is None or material is None:
            continue
        rows.append({
            "Purchasing Document": po_no,
            "Item": str(row.get("ITEM LINE#", "10")),
            "Material": material,
            "ship to": "Customer PO Ship To",
            "Order Quantity": row.get("FINALQTY", 100),
            "ship DATE": row.get("FINAL EX-FACTORY DATE"),
        })
    return rows


def make_base_file(tmp_path, *, data_base_rows, po_record_rows, customer_po_rows=None, name="base.xlsx"):
    wb = Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)
    ws_db = wb.create_sheet("DATA BASE")
    _write_sheet(ws_db, DATA_BASE_HEADER, data_base_rows)
    ws_po = wb.create_sheet("PO record")
    _write_sheet(ws_po, PO_RECORD_HEADER, po_record_rows)
    ws_cp = wb.create_sheet("客户PO")
    _write_sheet(
        ws_cp,
        CUSTOMER_PO_HEADER,
        customer_po_rows if customer_po_rows is not None else _default_customer_po_rows(po_record_rows),
        header_row=1,
        first_data_row=2,
    )
    path = tmp_path / name
    wb.save(path)
    return path


COMBO_PRODUCT = {
    "SAP": "21-44640",
    "Material Description": "CB2500.B2",
    "Category": 1,
    "GS MODEL": "Q1",
    "GS-SK/YM COMBO FOB 2026": Decimal("28.0"),
    "EMAX-GS PTE COMBO FOB 2026": Decimal("32.8"),
    "EMAX PTE COMBO FOB 2026": Decimal("38.0"),
    "round value": 24,
    "L": 60,
    "W": 40,
    "H": 30,
}


def basic_po_row(**overrides):
    base = {
        "PO NO.": "4500030844", "ITEM LINE#": "10", "SAP Number": "21-44640",
        "DESCRIPTION": "CB2500.B2", "FINALQTY": 100,
        "GS-SK/YM USD FOB": Decimal("28.0"), "EMAX-GS PTE FOB": Decimal("32.8"),
        "EMAX PTE": Decimal("38.0"), "INV#": "INV-001", "SHIP QTY": 100,
        "外箱(最终出口装箱率)": 24, "CTNS": 5, "TOTAL CBM": Decimal("0.36"),
        "N/W": Decimal("8.5"), "G/W": Decimal("10.1"), "L": 48, "W": 31, "H": 35,
        "FINAL EX-FACTORY DATE": date(2026, 3, 15),
    }
    base.update(overrides)
    return base


class TestSuccessPath:
    def test_invoice_with_seller_and_invoice_no(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "success", result.errors
        assert result.output_file is not None
        assert Path(result.output_file).exists()
        assert "INVOICE" in str(result.files[0])
        assert "INV-001" in str(result.files[0])
        assert isinstance(result.source_index, SourceIndex)
        assert len(result.source_index) > 0
        assert result.summary["seller"] == "GS PTE"
        assert result.summary["line_count"] == 1

    def test_output_file_contains_real_data(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row()],
            customer_po_rows=[{
                "Purchasing Document": "4500030844",
                "Material": "21-44640",
                "ship to": "Customer PO Warehouse",
                "Order Quantity": 100,
            }],
        )
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        wb = load_workbook(result.output_file)
        ws = wb["INV"]
        assert ws["H6"].value == "INV-001"
        assert ws["G10"].value == "Customer PO Warehouse"


class TestNeedsInput:
    def test_multiple_invoices_needs_input(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"INV#": "INV-001"}),
                            basic_po_row(**{"ITEM LINE#": "20", "FINALQTY": 100, "INV#": "INV-002"})])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "needs_input"
        assert INPUT_INVOICE_NO in result.missing_inputs

    def test_single_invoice_auto_selects(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "success", result.errors

    def test_segment_undecided_returns_needs_input(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "needs_input"
        assert INPUT_SELLER in result.missing_inputs


class TestErrorPath:
    def test_unknown_po(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="9999999", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "error"
        assert any(m.code == "PO_NOT_FOUND" for m in result.errors)

    def test_missing_invoice_no_warns_but_generates(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT],
                              po_record_rows=[basic_po_row(**{"INV#": None})])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "error"

    def test_multi_doc_generates_both(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("PI", "INVOICE"),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "success", result.errors
        assert len(result.files) == 2

    def test_sk_ym_po_blocked(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("PO",),
                                  seller="SK", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "error"
        assert any(m.code == CODE_MAPPING_NOT_FOUND for m in result.errors)

    def test_missing_workbook_returns_error(self, tmp_path):
        request = DocumentRequest(base_file=str(tmp_path / "nope.xlsx"), po_no="4500030844",
                                  documents=("INVOICE",), seller="GS PTE",
                                  invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "error"
        assert any(m.code == "WORKBOOK_OPEN_ERROR" for m in result.errors)

    def test_missing_sheet_returns_error(self, tmp_path):
        wb = Workbook()
        ws = wb.active
        if ws is not None:
            wb.remove(ws)
        wb.create_sheet("DATA BASE")
        path = tmp_path / "incomplete.xlsx"
        wb.save(path)
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "error"
        assert any(m.code == "SHEET_MISSING" for m in result.errors)


class TestWarningsPropagation:
    def test_formula_fallback_warning_in_result(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT],
                              po_record_rows=[basic_po_row(FINALQTY=240, **{"CTNS": None, "TOTAL CBM": None})])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
        result = generate(request)
        assert result.status == "success", result.errors
        assert any(m.code == "FORMULA_FALLBACK" for m in result.warnings)


class TestConflictStrategy:
    def test_overwrite_replaces_existing(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                                  seller="GS PTE", invoice_no="INV-001",
                                  output_dir=str(tmp_path / "out"), on_conflict="overwrite")
        first = generate(request)
        assert first.status == "success"
        second = generate(request)
        assert second.status == "success"
        assert first.output_file == second.output_file


@pytest.mark.parametrize("_label", ["smoke"])
def test_generation_result_immutable(tmp_path, _label):
    path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
    request = DocumentRequest(base_file=str(path), po_no="4500030844", documents=("INVOICE",),
                              seller="GS PTE", invoice_no="INV-001", output_dir=str(tmp_path / "out"))
    import dataclasses
    result = generate(request)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = "error"  # type: ignore[misc]


class TestBuildDocumentModel:
    def test_builds_invoice_model(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        with WorkbookReader(str(path)) as reader:
            resolved = resolve_po_lines(reader, "4500030844")
        build = build_document_model(
            resolved.lines, seller="GS PTE", buyer="EMAX PTE",
            po_no="4500030844", invoice_no="INV-001", doc_type="INVOICE",
        )
        assert build.model is not None
        assert build.mapping is not None
        assert build.model.document_type == "INVOICE"
        assert build.model.seller == "GS PTE"
        assert build.model.invoice_no == "INV-001"
        assert len(build.model.lines) == 1

    def test_builds_pi_model(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        with WorkbookReader(str(path)) as reader:
            resolved = resolve_po_lines(reader, "4500030844")
        build = build_document_model(
            resolved.lines, seller="GS PTE", buyer="EMAX PTE",
            po_no="4500030844", invoice_no=None, doc_type="PI",
        )
        assert build.model is not None
        assert build.model.document_type == "PI"
        assert build.model.total_quantity == Decimal("100")
        assert str(build.model.ex_factory_date) == "2026-03-15"
        assert build.model.ship_to == "Customer PO Ship To"

    def test_sk_po_blocked(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        with WorkbookReader(str(path)) as reader:
            resolved = resolve_po_lines(reader, "4500030844")
        build = build_document_model(
            resolved.lines, seller="SK", buyer="GS PTE",
            po_no="4500030844", invoice_no=None, doc_type="PO",
        )
        assert build.model is None
        assert any(m.code == CODE_MAPPING_NOT_FOUND for m in build.messages)


class TestPreviewFunction:
    def test_preview_returns_structured_data(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"
        assert result.preview is not None

        p = result.preview
        assert getattr(p, "document_type", "") == "INVOICE"
        assert getattr(p, "title", "") != ""
        assert getattr(p, "seller", "") == "GS PTE"
        assert getattr(p, "buyer", "") == "EMAX PTE"
        assert getattr(p, "po_no", "") == "4500030844"
        assert getattr(p, "invoice_no", None) == "INV-001"
        assert len(getattr(p, "lines", [])) == 1
        assert len(getattr(p, "source_entries", [])) > 0

    def test_preview_no_output_file(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"
        # Preview should NOT produce an output_file
        assert not hasattr(result, "output_file")

    def test_preview_needs_input_for_multiple_invoices(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"INV#": "INV-001"}),
                            basic_po_row(**{"ITEM LINE#": "20", "FINALQTY": 100, "INV#": "INV-002"})])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "needs_input"
        assert INPUT_INVOICE_NO in result.missing_inputs

    def test_preview_error_for_missing_po(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="9999999", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "error"

    def test_preview_contains_seller_info(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        p = result.preview
        seller_info = getattr(p, "seller_info", [])
        assert len(seller_info) > 0
        assert any("GLOBALSINO" in line for line in seller_info)

    def test_preview_contains_terms(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        p = result.preview
        terms = getattr(p, "terms", {})
        assert isinstance(terms, dict)
        assert terms == {
            "term": "T/T 75 DAYS AFTER BL DATE",
            "from": "QINGDAO, CHINA",
            "to": "KANSAS CITY, MO, USA",
        }

    def test_preview_terms_merge_resolved_header_fields_and_static_terms(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        terms = getattr(p, "terms", {})
        assert terms == {
            "payment_terms": "Net 90 days",
            "port_of_loading": "China",
            "final_destination": "USA",
            "incoterm": "FOB GUANGDONG",
        }
        resolved_values = getattr(p, "resolved_values", {})
        assert resolved_values["payment_terms"] == "Net 90 days"
        assert resolved_values["port_of_loading"] == "China"
        assert resolved_values["final_destination"] == "USA"
        assert resolved_values["bill_to"] == "209 Stoneridge Drive"
        assert resolved_values["bill_to_line2"] == "Columbia, South Carolina 29210"
        assert resolved_values["bill_to_line3"] == "United States"
        layout = getattr(p, "layout", {})
        info = layout.get("info", {}) if isinstance(layout, dict) else {}
        left = info.get("left", []) if isinstance(info, dict) else []
        assert "bill_to" in left
        assert "bill_to_line2" in left
        assert "bill_to_line3" in left

    def test_preview_document_date_source_entry_is_system_generated(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        entries = getattr(p, "source_entries", [])
        document_date_entry = next(e for e in entries if e["preview_field"] == "document_date")
        assert document_date_entry["source_type"] == "system_generated"
        assert document_date_entry["value"]
        assert "当天日期" in document_date_entry["rule"]

    def test_preview_ex_factory_date_source_entry_comes_from_customer_po(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        resolved_values = getattr(p, "resolved_values", {})
        assert resolved_values["ex_factory_date"] == "2026-03-15"

        entries = getattr(p, "source_entries", [])
        ex_factory_entry = next(e for e in entries if e["preview_field"] == "ex_factory_date")
        assert ex_factory_entry["source_type"] == "base_field"
        assert ex_factory_entry["sheet"] == "客户PO"
        assert ex_factory_entry["field"] == "ship DATE"
        assert ex_factory_entry["value"] == "2026-03-15"
        assert "ship DATE" in ex_factory_entry["rule"]

    def test_preview_ship_to_source_entry_comes_from_customer_po(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row()],
            customer_po_rows=[{
                "Purchasing Document": "4500030844",
                "Material": "21-44640",
                "ship to": "Customer PO Warehouse",
                "Order Quantity": 100,
            }],
        )
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
            output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert getattr(p, "ship_to", None) == "Customer PO Warehouse"
        resolved_values = getattr(p, "resolved_values", {})
        assert resolved_values["ship_to"] == "Customer PO Warehouse"

        entries = getattr(p, "source_entries", [])
        ship_to_entry = next(e for e in entries if e["preview_field"] == "ship_to")
        assert ship_to_entry["source_type"] == "base_field"
        assert ship_to_entry["sheet"] == "客户PO"
        assert ship_to_entry["field"] == "ship to"
        assert ship_to_entry["value"] == "Customer PO Warehouse"

    def test_emax_pi_preview_ship_to_uses_yaml_multiline_fields(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row()],
            customer_po_rows=[{
                "Purchasing Document": "4500030844",
                "Material": "21-44640",
                "ship to": "209 Stoneridge Drive, Columbia, South Carolina 29210, United States",
                "Order Quantity": 100,
            }],
        )
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        resolved_values = getattr(p, "resolved_values", {})
        assert resolved_values["ship_to"] == "209 Stoneridge Drive"
        assert resolved_values["ship_to_line2"] == "Columbia, South Carolina 29210"
        assert resolved_values["ship_to_line3"] == "United States"

        right = p.layout["info"]["right"]
        assert "ship_to" in right
        assert "ship_to_line2" in right
        assert "ship_to_line3" in right

        entries = getattr(p, "source_entries", [])
        ship_to_line2 = next(e for e in entries if e["preview_field"] == "ship_to_line2")
        ship_to_line3 = next(e for e in entries if e["preview_field"] == "ship_to_line3")
        assert ship_to_line2["sheet"] == "客户PO"
        assert ship_to_line2["field"] == "ship to"
        assert ship_to_line2["value"] == "Columbia, South Carolina 29210"
        assert ship_to_line3["sheet"] == "客户PO"
        assert ship_to_line3["field"] == "ship to"
        assert ship_to_line3["value"] == "United States"

    def test_emax_pi_item_no_comes_from_customer_po_material(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(**{"ITEM LINE#": "10"})],
            customer_po_rows=[{
                "Purchasing Document": "4500030844",
                "Item": "CP-ITEM-001",
                "Material": "CP-MATERIAL-001",
                "ship to": "Customer PO Warehouse",
                "Order Quantity": 100,
            }],
        )
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"
        p = result.preview
        assert p is not None
        assert p.lines[0]["item_line_no"] == "CP-ITEM-001"

        entries = getattr(p, "source_entries", [])
        item_no_entry = next(e for e in entries if e["preview_field"] == "line[0].item_line_no")
        assert item_no_entry["sheet"] == "客户PO"
        assert item_no_entry["field"] == "item"
        assert item_no_entry["row"] is None
        assert item_no_entry["value"] == "CP-ITEM-001"

    def test_gs_po_item_number_uses_formal_preview_key(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(**{"ITEM LINE#": "10"})],
            customer_po_rows=[{
                "Purchasing Document": "4500030844",
                "Material": "CP-MATERIAL-001",
                "ship to": "Customer PO Warehouse",
                "Order Quantity": 100,
                "ship DATE": date(2026, 3, 15),
            }],
        )
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PO",),
            seller="GS PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"
        p = result.preview
        assert p is not None
        assert p.lines[0]["item_number"] == "CP-MATERIAL-001"

        entries = getattr(p, "source_entries", [])
        item_number_entry = next(e for e in entries if e["preview_field"] == "line[0].item_number")
        assert item_number_entry["sheet"] == "客户PO"
        assert item_number_entry["field"] == "material"
        assert item_number_entry["row"] is None
        assert item_number_entry["value"] == "CP-MATERIAL-001"

    def test_emax_pi_line_sources_follow_data_base_and_customer_po_rules(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[{
                **COMBO_PRODUCT,
                "Material Description": "DB Description",
                "EMAX PTE COMBO FOB 2026": Decimal("88.8"),
            }],
            po_record_rows=[basic_po_row(**{"DESCRIPTION": "PO Description", "FINALQTY": 100})],
            customer_po_rows=[{
                "Purchasing Document": "4500030844",
                "Material": "21-44640",
                "ship to": "Customer PO Warehouse",
                "Order Quantity": 240,
            }],
        )
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"
        p = result.preview
        assert p is not None
        first_line = p.lines[0]
        assert first_line["description"] == "DB Description"
        assert first_line["unit_price"] == "88.8"
        assert first_line["quantity"] == "240"

        entries = getattr(p, "source_entries", [])
        description_entry = next(e for e in entries if e["preview_field"] == "line[0].description")
        unit_price_entry = next(e for e in entries if e["preview_field"] == "line[0].unit_price")
        quantity_entry = next(e for e in entries if e["preview_field"] == "line[0].quantity")
        assert description_entry["sheet"] == "DATA BASE"
        assert description_entry["field"] == "Material Description"
        assert unit_price_entry["sheet"] == "DATA BASE"
        assert unit_price_entry["field"] == "EMAX PTE COMBO FOB 2026"
        assert quantity_entry["sheet"] == "客户PO"
        assert quantity_entry["field"] == "Order Quantity"
        assert quantity_entry["value"] == "240"

    def test_preview_invoice_uses_po_record_description_rule(self, tmp_path):
        po_row = basic_po_row(DESCRIPTION="PO Record Description")
        db_row = dict(COMBO_PRODUCT)
        db_row["Material Description"] = "DB Description"
        path = make_base_file(tmp_path, data_base_rows=[db_row], po_record_rows=[po_row])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("INVOICE",),
            seller="GS PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        assert p.lines[0]["description"] == "PO Record Description"

        entries = getattr(p, "source_entries", [])
        description_entry = next(e for e in entries if e["preview_field"] == "line[0].description")
        assert description_entry["sheet"] == "PO record"
        assert description_entry["field"] == "DESCRIPTION"
        assert description_entry["value"] == "PO Record Description"

    def test_preview_pl_totals_keep_shared_labels_and_values(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller="GS PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"
        p = result.preview
        assert p is not None
        totals = getattr(p, "totals", {})
        labels = totals.get("_labels", {})
        assert totals["total_quantity"] == "100"
        assert totals["total_net_weight"] == "8.5"
        assert totals["total_gross_weight"] == "10.1"
        assert totals["total_cbm"] == "0.36"
        assert totals["total_carton_count"] == "5"
        assert labels["total_quantity"] == "Total Qty"
        assert labels["total_net_weight"] == "Total N/W (KGS)"
        assert labels["total_gross_weight"] == "Total G/W (KGS)"
        assert labels["total_cbm"] == "Total CBM"
        assert labels["total_carton_count"] == "Total CTNS"

        footer_items = totals.get("_footer_items", [])
        assert footer_items == [
            {"key": "quantity", "label": "Total Qty", "value": "100 PCS"},
            {"key": "net_weight", "label": "Total N/W (KGS)", "value": "8.5"},
            {"key": "gross_weight", "label": "Total G/W (KGS)", "value": "10.1"},
            {"key": "cbm", "label": "Total CBM", "value": "0.36 CBM"},
            {"key": "carton_count", "label": "Total CTNS", "value": "5"},
        ]
        layout = getattr(p, "layout", {})
        info = layout.get("info", {}) if isinstance(layout, dict) else {}
        top = layout.get("top", {}) if isinstance(layout, dict) else {}
        assert info.get("left", []) == ["shipping_mark", "shipping_mark_2"]
        assert info.get("right", []) == ["invoice_no", "invoice_date"]
        assert top.get("left", []) == ["seller_info"]

    def test_preview_emax_pl_includes_shipping_mark_headers(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller="EMAX PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        resolved_values = getattr(p, "resolved_values", {})
        assert resolved_values["shipping_mark"] == "WEIHAI"
        assert resolved_values["shipping_mark_2"] == "C/T#"
        assert resolved_values["shipping_mark_3"] == "MADE IN CHINA"

        layout = getattr(p, "layout", {})
        info = layout.get("info", {}) if isinstance(layout, dict) else {}
        left = info.get("left", []) if isinstance(info, dict) else []
        right = info.get("right", []) if isinstance(info, dict) else []
        assert left == ["shipping_mark", "shipping_mark_2", "shipping_mark_3"]
        assert right == ["invoice_no"]

    def test_preview_emax_pl_uses_po_record_description_rule(self, tmp_path):
        po_row = basic_po_row(DESCRIPTION="PO Record Description")
        db_row = dict(COMBO_PRODUCT)
        db_row["Material Description"] = "DB Description"
        path = make_base_file(tmp_path, data_base_rows=[db_row], po_record_rows=[po_row])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller="EMAX PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        assert p.lines[0]["description"] == "PO Record Description"

        entries = getattr(p, "source_entries", [])
        description_entry = next(e for e in entries if e["preview_field"] == "line[0].description")
        po_no_entry = next(e for e in entries if e["preview_field"] == "line[0].po_no")
        assert description_entry["sheet"] == "PO record"
        assert description_entry["field"] == "DESCRIPTION"
        assert description_entry["value"] == "PO Record Description"
        assert po_no_entry["sheet"] == "客户PO"
        assert po_no_entry["field"] == "Purchasing Document"

    def test_preview_emax_pl_includes_fixed_unit_columns(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller="EMAX PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        assert [c["key"] for c in p.column_labels] == [
            "po_no", "description", "sap", "quantity", "F",
            "net_weight", "H", "gross_weight", "J", "cbm", "L", "carton_count",
        ]
        labels = {c["key"]: c["label"] for c in p.column_labels}
        assert labels["F"] == ""
        assert labels["H"] == ""
        assert labels["J"] == ""
        assert labels["L"] == ""
        first_line = p.lines[0]
        assert first_line["F"] == "PCS"
        assert first_line["H"] == "KGS"
        assert first_line["J"] == "KGS"
        assert first_line["L"] == "CBM"

    def test_preview_emax_pl_uses_po_record_total_cbm_rule(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(**{"TOTAL CBM": Decimal("1.2")})],
        )
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller="EMAX PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        assert p.lines[0]["cbm"] == "1.20"

        entries = getattr(p, "source_entries", [])
        cbm_entry = next(e for e in entries if e["preview_field"] == "line[0].cbm")
        assert cbm_entry["sheet"] == "PO record"
        assert cbm_entry["field"] == "TOTAL CBM"
        assert cbm_entry["value"] == "1.20"
        assert 'PO record AJ列 "TOTAL CBM"' in cbm_entry["rule"]

    def test_preview_emax_pl_preserves_source_cbm_decimal_places(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(**{"TOTAL CBM": 1.2})],
        )
        wb = load_workbook(path)
        ws = wb["PO record"]
        total_cbm_col = PO_RECORD_HEADER.index("TOTAL CBM") + 1
        ws.cell(row=5, column=total_cbm_col).number_format = "0.0000"
        wb.save(path)
        wb.close()

        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller="EMAX PTE", invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        assert p.lines[0]["cbm"] == "1.2000"

        entries = getattr(p, "source_entries", [])
        cbm_entry = next(e for e in entries if e["preview_field"] == "line[0].cbm")
        assert cbm_entry["value"] == "1.2000"

    @pytest.mark.parametrize("seller", ["SK", "YM"])
    def test_preview_sk_ym_pl_layout_uses_supported_header_fields(self, tmp_path, seller):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PL",),
            seller=seller, invoice_no="INV-001",
        )
        result = preview(request)
        assert result.status == "success"

        p = result.preview
        assert p is not None
        layout = getattr(p, "layout", {})
        info = layout.get("info", {}) if isinstance(layout, dict) else {}
        top = layout.get("top", {}) if isinstance(layout, dict) else {}
        assert info.get("left", []) == ["shipping_mark", "shipping_mark_2"]
        assert info.get("right", []) == ["invoice_no", "invoice_date"]
        assert top.get("left", []) == ["seller_info"]

    def test_preview_emax_pi_includes_custom_totals_from_mapping(self, tmp_path):
        path = make_base_file(tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()])
        request = DocumentRequest(
            base_file=str(path), po_no="4500030844", documents=("PI",),
            seller="EMAX PTE", output_dir=str(tmp_path / "out"),
        )
        result = preview(request)
        assert result.status == "success"
        p = result.preview
        assert p is not None

        totals = getattr(p, "totals", {})
        assert totals["signature"] == "Joyce"
        assert totals["Date"] == date.today().strftime("%Y-%m-%d")

        extra_items = totals.get("_extra_items", [])
        assert {"key": "signature", "label": "Signature", "value": "Joyce", "source_type": "template_content", "rule": "mapping.totals 固定值"} in extra_items
        assert {
            "key": "Date",
            "label": "Date",
            "value": date.today().strftime("%Y-%m-%d"),
            "source_type": "system_generated",
            "rule": "系统生成当前日期",
        } in extra_items

        footer_items = totals.get("_footer_items", [])
        assert footer_items == [
            {"key": "amount", "label": "Total Amount", "value": "USD 3800.00"},
            {"key": "signature", "label": "Signature", "value": "Joyce"},
            {"key": "Date", "label": "Date", "value": date.today().strftime("%Y-%m-%d")},
        ]

        entries = getattr(p, "source_entries", [])
        amount_entry = next(e for e in entries if e["preview_field"] == "totals.amount")
        signature_entry = next(e for e in entries if e["preview_field"] == "totals.signature")
        date_entry = next(e for e in entries if e["preview_field"] == "totals.Date")
        assert amount_entry["value"] == "USD 3800.00"
        assert amount_entry["source_type"] == "computed"
        assert signature_entry["value"] == "Joyce"
        assert signature_entry["source_type"] == "template_content"
        assert date_entry["value"] == date.today().strftime("%Y-%m-%d")
        assert date_entry["source_type"] == "system_generated"
