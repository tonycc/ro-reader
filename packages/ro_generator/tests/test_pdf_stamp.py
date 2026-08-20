"""Invoice/PL PDF 主体印章：只盖 PDF，缺文件静默跳过。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, TextStringObject
from ro_generator.pdf_stamp import (
    POINTS_PER_CM,
    apply_seller_stamp,
    stamp_box_pt,
)

A4_WIDTH_PT = 595.27
A4_HEIGHT_PT = 841.89


def _writer_catalog(writer: PdfWriter) -> DictionaryObject:
    """pypdf 4.0 只有 `_root_object`；5.x 才公开 `root_object`。"""

    catalog = getattr(writer, "root_object", None) or writer._root_object
    assert isinstance(catalog, DictionaryObject)
    return catalog


def _blank_pdf(path: Path, pages: int = 2) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
    writer.write(path)
    return path


def _write_stamp_pack(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (200, 200), (0, 0, 220, 255)).save(root / "circle.png")
    Image.new("RGBA", (600, 250), (0, 80, 180, 255)).save(root / "rect.png")
    (root / "stamps.yaml").write_text(
        yaml.safe_dump(
            {
                "documents": ["INVOICE", "PL"],
                "margin_right_cm": 1.2,
                "margin_bottom_cm": 1.5,
                "sellers": {
                    "GS PTE": {
                        "file": "circle.png",
                        "shape": "circle",
                        "diameter_cm": 3,
                    },
                    "SK": {
                        "file": "circle.png",
                        "shape": "circle",
                        "diameter_cm": 4,
                    },
                    "YM": {
                        "file": "rect.png",
                        "shape": "rect",
                        "width_cm": 6,
                        "height_cm": 2.5,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def test_gs_stamp_box_is_3cm_at_bottom_right() -> None:
    x, y, width, height = stamp_box_pt(
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
        width_cm=3,
        height_cm=3,
        margin_right_cm=1.2,
        margin_bottom_cm=1.5,
    )
    assert width == pytest.approx(3 * POINTS_PER_CM)
    assert height == pytest.approx(3 * POINTS_PER_CM)
    assert x + width == pytest.approx(A4_WIDTH_PT - 1.2 * POINTS_PER_CM)
    assert y == pytest.approx(1.5 * POINTS_PER_CM)


def test_invalid_pdf_is_left_unchanged(tmp_path: Path) -> None:
    stamps = _write_stamp_pack(tmp_path / "stamps")
    pdf = tmp_path / "fake.pdf"
    payload = b"%PDF-1.4 fake\n"
    pdf.write_bytes(payload)
    apply_seller_stamp(
        pdf,
        seller="GS PTE",
        document_types=("INVOICE",),
        stamps_root=stamps,
    )
    assert pdf.read_bytes() == payload


def test_apply_stamp_skips_pi_and_missing_file(tmp_path: Path) -> None:
    stamps = _write_stamp_pack(tmp_path / "stamps")
    pdf = _blank_pdf(tmp_path / "doc.pdf")
    original = pdf.read_bytes()

    apply_seller_stamp(
        pdf,
        seller="GS PTE",
        document_types=("PI",),
        stamps_root=stamps,
    )
    assert pdf.read_bytes() == original

    apply_seller_stamp(
        pdf,
        seller="EMAX PTE",
        document_types=("INVOICE",),
        stamps_root=stamps,
    )
    assert pdf.read_bytes() == original

    apply_seller_stamp(
        pdf,
        seller="GS PTE",
        document_types=("INVOICE",),
        stamps_root=tmp_path / "missing",
    )
    assert pdf.read_bytes() == original


def test_apply_stamp_covers_every_invoice_page(tmp_path: Path) -> None:
    stamps = _write_stamp_pack(tmp_path / "stamps")
    pdf = _blank_pdf(tmp_path / "invoice.pdf", pages=2)

    apply_seller_stamp(
        pdf,
        seller="GS PTE",
        document_types=("INVOICE", "PL"),
        stamps_root=stamps,
    )

    pages = PdfReader(pdf).pages
    assert len(pages) == 2
    for page in pages:
        assert len(page.images) >= 1


def test_bundled_seller_sizes_match_spec(tmp_path: Path) -> None:
    from ro_generator.pdf_stamp import load_stamp_spec, seller_stamp_box_pt

    pdf = _blank_pdf(tmp_path / "pl.pdf", pages=1)
    apply_seller_stamp(pdf, seller="YM", document_types=("PL",))
    page = PdfReader(pdf).pages[0]
    assert len(page.images) >= 1

    spec = load_stamp_spec()
    assert spec is not None
    gs = seller_stamp_box_pt(A4_WIDTH_PT, A4_HEIGHT_PT, spec, "GS PTE")
    sk = seller_stamp_box_pt(A4_WIDTH_PT, A4_HEIGHT_PT, spec, "SK")
    ym = seller_stamp_box_pt(A4_WIDTH_PT, A4_HEIGHT_PT, spec, "YM")
    assert gs is not None
    assert sk is not None
    assert ym is not None
    assert gs[2] == pytest.approx(3 * POINTS_PER_CM)
    assert sk[2] == pytest.approx(4 * POINTS_PER_CM)
    assert ym[2] == pytest.approx(6 * POINTS_PER_CM)
    assert ym[3] == pytest.approx(2.5 * POINTS_PER_CM)


def test_stamp_preserves_catalog_structure_and_metadata(tmp_path: Path) -> None:
    stamps = _write_stamp_pack(tmp_path / "stamps")
    pdf = tmp_path / "structured.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
    writer.add_metadata({"/Author": "RO Workbench", "/Title": "Packing List"})
    writer.add_outline_item("Packing List", 0)
    catalog = _writer_catalog(writer)
    catalog[NameObject("/Lang")] = TextStringObject("en-US")
    mark_info = DictionaryObject()
    mark_info[NameObject("/Marked")] = BooleanObject(True)
    catalog[NameObject("/MarkInfo")] = mark_info
    struct_root = DictionaryObject()
    struct_root[NameObject("/Type")] = NameObject("/StructTreeRoot")
    catalog[NameObject("/StructTreeRoot")] = struct_root
    writer.write(pdf)

    apply_seller_stamp(
        pdf,
        seller="GS PTE",
        document_types=("PL",),
        stamps_root=stamps,
    )

    stamped = PdfReader(pdf)
    root = stamped.trailer["/Root"]
    assert isinstance(root, DictionaryObject)
    metadata = stamped.metadata
    assert metadata is not None
    assert metadata.author == "RO Workbench"
    assert metadata.title == "Packing List"
    assert str(root["/Lang"]) == "en-US"
    assert "/StructTreeRoot" in root
    struct_tree = root["/StructTreeRoot"]
    assert isinstance(struct_tree, DictionaryObject)
    assert str(struct_tree["/Type"]) == "/StructTreeRoot"
    mark_info_out = root["/MarkInfo"]
    assert isinstance(mark_info_out, DictionaryObject)
    assert bool(mark_info_out["/Marked"]) is True
    assert stamped.outline
