"""Generator 流水线集成测试：reader → validator → resolver → document_model → renderer → packager。

用合成 base 文件覆盖 status 三态：success / error / needs_input。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook
from ro_generator.generator import (
    CODE_MAPPING_NOT_FOUND,
    CODE_UNSUPPORTED_DOCUMENT,
    INPUT_INVOICE_MONTH,
    INPUT_SELLER,
    generate,
)
from ro_generator.models import DocumentRequest
from ro_generator.source_index import SourceIndex

# ————————————————————————————————————————
# Fixture builders
# ————————————————————————————————————————


DATA_BASE_HEADER = [
    "SAP",
    "Material Description",
    "Category",
    "GS MODEL",
    "round value",
    "L",
    "W",
    "H",
]

PO_RECORD_HEADER = [
    "PO NO.",
    "ITEM LINE#",
    "SAP Number",
    "DESCRIPTION",
    "FINALQTY",
    "SK/YM USD FOB",
    "GS PTE FOB",
    "EMAX PTE",
    "INV#",
    "FACTORY DOC NO.",
    "CTNS",
    "TOTAL CBM",
    "外箱",
    *[f"26{m:02d}" for m in range(1, 13)],
]


def _write_sheet(ws: Any, headers: list[str], rows: list[dict[str, Any]]) -> None:
    for c_idx, header in enumerate(headers, start=1):
        ws.cell(row=4, column=c_idx, value=header)
    for r_offset, row in enumerate(rows):
        for c_idx, header in enumerate(headers, start=1):
            value = row.get(header)
            if value is not None:
                ws.cell(row=5 + r_offset, column=c_idx, value=value)


def make_base_file(
    tmp_path: Path,
    *,
    data_base_rows: list[dict[str, Any]],
    po_record_rows: list[dict[str, Any]],
    name: str = "base.xlsx",
) -> Path:
    wb = Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)
    ws_db = wb.create_sheet("DATA BASE")
    _write_sheet(ws_db, DATA_BASE_HEADER, data_base_rows)
    ws_po = wb.create_sheet("PO record")
    _write_sheet(ws_po, PO_RECORD_HEADER, po_record_rows)
    path = tmp_path / name
    wb.save(path)
    return path


COMBO_PRODUCT = {
    "SAP": "21-44640",
    "Material Description": "CB2500.B2",
    "Category": 1,
    "GS MODEL": "Q1",
    "round value": 24,
    "L": 60,
    "W": 40,
    "H": 30,
}


def basic_po_row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "PO NO.": "4500030844",
        "ITEM LINE#": "10",
        "SAP Number": "21-44640",
        "DESCRIPTION": "CB2500.B2",
        "FINALQTY": 100,
        "SK/YM USD FOB": Decimal("28.0"),
        "GS PTE FOB": Decimal("32.8"),
        "EMAX PTE": Decimal("38.0"),
        "INV#": "INV-001",
        "FACTORY DOC NO.": "FDOC-001",
        "外箱": 24,
        "CTNS": 5,
        "TOTAL CBM": Decimal("0.36"),
    }
    base.update(overrides)
    return base


# ————————————————————————————————————————
# 成功路径
# ————————————————————————————————————————


class TestSuccessPath:
    def test_invoice_with_explicit_month_and_segment(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "success", result.errors
        assert result.output_file is not None
        assert Path(result.output_file).exists()
        assert "INVOICE" in str(result.files[0])
        assert "2601" in str(result.files[0])

        # source_index 应为 SourceIndex 类型且非空
        assert isinstance(result.source_index, SourceIndex)
        assert len(result.source_index) > 0

        # 摘要包含关键字段
        assert result.summary["seller"] == "GS PTE"
        assert result.summary["buyer"] == "EMAX PTE"
        assert result.summary["invoice_month"] == "2601"
        assert result.summary["line_count"] == 1

    def test_output_file_contains_real_data(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.output_file is not None
        wb = load_workbook(result.output_file)
        ws = wb["Sheet1"]
        # 表头单元格 H6 应是 INV-001
        assert ws["H6"].value == "INV-001"
        # 行 18 D 列应是 SAP
        assert ws["D18"].value == "21-44640"


# ————————————————————————————————————————
# needs_input：月份多选
# ————————————————————————————————————————


class TestNeedsInput:
    def test_multiple_months_returns_options(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=300, **{"2601": 100, "2602": 200})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "needs_input"
        assert INPUT_INVOICE_MONTH in result.missing_inputs
        opts = result.options[INPUT_INVOICE_MONTH]
        values = {o["value"] for o in opts}
        assert values == {"2601", "2602"}
        # label 应包含数量信息
        for o in opts:
            assert "出货" in o["label"]

    def test_single_month_auto_selects(self, tmp_path: Path) -> None:
        """只有一个月份有出货时不应触发 needs_input。"""
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "success", result.errors
        assert result.summary["invoice_month"] == "2601"

    def test_segment_undecided_returns_needs_input(self, tmp_path: Path) -> None:
        """seller/buyer 未给定且多段都有定价 → needs_input。"""
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "needs_input"
        assert INPUT_SELLER in result.missing_inputs
        # options 应列出所有合法链段
        seller_opts = result.options[INPUT_SELLER]
        labels = {o["label"] for o in seller_opts}
        assert any("GS PTE" in label for label in labels)


# ————————————————————————————————————————
# error 路径
# ————————————————————————————————————————


class TestErrorPath:
    def test_unknown_po(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row()],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="9999999",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "error"
        assert any(m.code == "PO_NOT_FOUND" for m in result.errors)
        assert result.output_file is None

    def test_missing_invoice_no_blocks(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100, "INV#": None})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "error"
        codes = {m.code for m in result.errors}
        assert "INVOICE_NO_MISSING" in codes

    def test_unsupported_document_type_blocks(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("PI", "INVOICE"),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "error"
        codes = {m.code for m in result.errors}
        assert CODE_UNSUPPORTED_DOCUMENT in codes

    def test_unsupported_seller_blocks(self, tmp_path: Path) -> None:
        """Phase 1 仅 GS PTE 有 mapping。"""
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="EMAX PTE",
            buyer="PF",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "error"
        codes = {m.code for m in result.errors}
        assert CODE_MAPPING_NOT_FOUND in codes

    def test_missing_workbook_returns_error(self, tmp_path: Path) -> None:
        request = DocumentRequest(
            base_file=str(tmp_path / "nope.xlsx"),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "error"
        codes = {m.code for m in result.errors}
        assert "WORKBOOK_OPEN_ERROR" in codes

    def test_missing_sheet_returns_error(self, tmp_path: Path) -> None:
        wb = Workbook()
        ws = wb.active
        if ws is not None:
            wb.remove(ws)
        wb.create_sheet("DATA BASE")  # 缺 PO record
        path = tmp_path / "incomplete.xlsx"
        wb.save(path)
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "error"
        codes = {m.code for m in result.errors}
        assert "SHEET_MISSING" in codes


# ————————————————————————————————————————
# 警告传播
# ————————————————————————————————————————


class TestWarningsPropagation:
    def test_formula_fallback_warning_in_result(self, tmp_path: Path) -> None:
        """CTNS 缺失触发公式回退，应作为 warning 传到结果。"""
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[
                basic_po_row(FINALQTY=240, CTNS=None, **{"2601": 240, "TOTAL CBM": None})
            ],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "success", result.errors
        codes = {m.code for m in result.warnings}
        assert "FORMULA_FALLBACK" in codes


# ————————————————————————————————————————
# 文件冲突策略
# ————————————————————————————————————————


class TestConflictStrategy:
    def test_overwrite_replaces_existing(self, tmp_path: Path) -> None:
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            buyer="EMAX PTE",
            invoice_month="2601",
            output_dir=str(tmp_path / "out"),
            on_conflict="overwrite",
        )
        first = generate(request)
        assert first.status == "success"
        second = generate(request)
        assert second.status == "success"
        # 同名文件
        assert first.output_file == second.output_file


@pytest.mark.parametrize("_label", ["smoke"])
def test_generation_result_immutable(tmp_path: Path, _label: str) -> None:
    path = make_base_file(
        tmp_path,
        data_base_rows=[COMBO_PRODUCT],
        po_record_rows=[basic_po_row(FINALQTY=100, **{"2601": 100})],
    )
    request = DocumentRequest(
        base_file=str(path),
        po_no="4500030844",
        documents=("INVOICE",),
        seller="GS PTE",
        buyer="EMAX PTE",
        invoice_month="2601",
        output_dir=str(tmp_path / "out"),
    )
    result = generate(request)
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = "error"  # type: ignore[misc]
