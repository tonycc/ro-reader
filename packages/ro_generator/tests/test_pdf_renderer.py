"""pdf_renderer 单元测试。"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from ro_generator.document_preview import DocumentPreview
from ro_generator.pdf_renderer import PdfRenderResult, render_pdf


def _sample_preview(**overrides) -> DocumentPreview:
    base = dict(
        document_type="INVOICE",
        title="COMMERCIAL INVOICE",
        seller="GS PTE",
        buyer="EMAX PTE",
        po_no="4500030844",
        invoice_no="INV-001",
        column_labels=[
            {"key": "description", "label": "DESCRIPTION"},
            {"key": "quantity", "label": "QTY"},
            {"key": "unit_price", "label": "UNIT PRICE"},
        ],
        lines=[
            {"description": "CB2500.B2", "quantity": "100", "unit_price": "$28.00", "_index": 0},
        ],
        totals={
            "total_quantity": "100 PCS",
            "total_amount": "$2,800.00",
            "_labels": {"total_quantity": "TOTAL QTY", "total_amount": "TOTAL AMOUNT"},
        },
        notes=["PACKED IN 5 CTNS"],
    )
    base.update(overrides)
    return DocumentPreview(**base)


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_render_pdf_creates_file(tmp_path):
    out = tmp_path / "doc.pdf"
    result = render_pdf([_sample_preview()], out)
    assert isinstance(result, PdfRenderResult)
    assert result.output_path == out.resolve()
    assert out.exists()
    assert out.read_bytes()[:4] == b"%PDF"


def test_render_pdf_contains_title_columns_totals_notes(tmp_path):
    out = tmp_path / "doc.pdf"
    render_pdf([_sample_preview()], out)
    text = _text(out)
    assert "COMMERCIAL INVOICE" in text
    assert "DESCRIPTION" in text
    assert "CB2500.B2" in text
    assert "$2,800.00" in text
    assert "PACKED IN 5 CTNS" in text


def test_render_pdf_empty_previews_raises(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        render_pdf([], tmp_path / "x.pdf")


def test_render_pdf_landscape_when_many_columns(tmp_path):
    out = tmp_path / "wide.pdf"
    column_labels = [{"key": f"c{i}", "label": f"COL {i}"} for i in range(8)]
    lines = [{f"c{i}": str(i) for i in range(8)}]
    render_pdf([_sample_preview(column_labels=column_labels, lines=lines)], out)
    assert out.exists()
    assert out.read_bytes()[:4] == b"%PDF"


def test_render_pdf_escapes_special_chars(tmp_path):
    out = tmp_path / "special.pdf"
    preview = _sample_preview(
        title="INVOICE M&M",
        notes=["A & B <ok>"],
        totals={
            "total_amount": "A & B",
            "_labels": {"total_amount": "TOTAL & AMOUNT"},
        },
    )
    render_pdf([preview], out)
    text = _text(out)
    assert "M&M" in text
    assert "A & B" in text
    assert "ok" in text
    assert "TOTAL & AMOUNT" in text


def test_render_pdf_contains_header_layout_fields(tmp_path):
    preview = _sample_preview(
        seller_info=["GS PTE LTD", "1 Marina Blvd"],
        ship_to="EMAX WAREHOUSE",
        layout={
            "top": {"left": ["seller_info"], "center": [], "right": ["title", "seller", "po_no"]},
            "info": {"left": ["ship_to"], "right": ["invoice_no"]},
        },
        resolved_values={"po_no": "4500030844", "invoice_no": "INV-001"},
    )
    out = tmp_path / "doc.pdf"
    render_pdf([preview], out)
    text = _text(out)
    assert "GS PTE LTD" in text
    assert "1 Marina Blvd" in text
    assert "EMAX WAREHOUSE" in text
    assert "4500030844" in text
    assert "INV-001" in text


def test_render_pdf_multi_preview_paginates(tmp_path):
    inv = _sample_preview(title="COMMERCIAL INVOICE")
    pl = _sample_preview(
        document_type="PL",
        title="PACKING LIST",
        totals={"total_quantity": "100 PCS", "_labels": {"total_quantity": "TOTAL QTY"}},
        notes=["PACKED IN 5 CTNS"],
    )
    out = tmp_path / "bundle.pdf"
    render_pdf([inv, pl], out)
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2
    all_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "COMMERCIAL INVOICE" in all_text
    assert "PACKING LIST" in all_text
