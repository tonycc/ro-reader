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
