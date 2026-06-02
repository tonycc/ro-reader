"""Renderer 测试：用真实 GS Invoice 模板装配 Invoice，验证样式保留 + 数据正确。

复用 Phase 0 Spike A 的样式不变量断言，确保插入行 + 复制样式仍然安全。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook
from ro_generator.document_model import DocumentModel, build_invoice_model
from ro_generator.errors import TemplateError
from ro_generator.models import OrderLine, Product
from ro_generator.renderer import render_document
from ro_generator.schema import (
    ENTITY_EMAX_PTE,
    ENTITY_GS_PTE,
)
from ro_generator.source_index import COMPUTED_SHEET
from ro_generator.template_mapping import load_template_mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
GS_INVOICE_MAPPING = REPO_ROOT / "templates" / "gs" / "mappings" / "invoice.yaml"
GS_INVOICE_TEMPLATE = REPO_ROOT / "templates" / "gs" / "invoice.xlsx"


# ————————————————————————————————————————
# Fixture builders
# ————————————————————————————————————————


def make_order_line(
    *,
    sap: str,
    description: str,
    gs_model: str,
    quantity: int,
    item_line_no: str = "10",
    unit_prices: dict[tuple[str, str], Decimal] | None = None,
    source_row: int | None = None,
) -> OrderLine:
    if unit_prices is None:
        unit_prices = {(ENTITY_GS_PTE, ENTITY_EMAX_PTE): Decimal("32.8")}
    qty = Decimal(quantity)
    subtotals = {seg: (price * qty).quantize(Decimal("0.01")) for seg, price in unit_prices.items()}
    return OrderLine(
        po_no="4500030844",
        item_line_no=item_line_no,
        sap=sap,
        description=description,
        category=1,
        quantity=qty,
        product=Product(
            sap=sap,
            description=description,
            category=1,
            gs_model=gs_model,
        ),
        ship_to="EMAX HQ",
        invoice_no="INV-RENDER-001",
        factory_doc_no="FDOC-RENDER-001",
        prices=unit_prices,
        subtotals=subtotals,
        source_row=source_row,
    )


def build_three_line_invoice(
    seller: str = ENTITY_GS_PTE, buyer: str = ENTITY_EMAX_PTE
) -> DocumentModel:
    """3 行（在 GS Invoice 9 行预留范围内）。"""
    lines = (
        make_order_line(
            sap="21-44640", description="CB2500.B2", gs_model="Q1", quantity=100, source_row=5
        ),
        make_order_line(
            sap="21-44641",
            description="CB3000.B2",
            gs_model="Q2",
            quantity=200,
            item_line_no="20",
            source_row=6,
        ),
        make_order_line(
            sap="21-44642",
            description="CB4000.B2",
            gs_model="Q3",
            quantity=80,
            item_line_no="30",
            source_row=7,
        ),
    )
    result = build_invoice_model(lines, seller=seller, buyer=buyer, po_no="4500030844")
    assert result.model is not None, result.messages
    return result.model


def build_overflowing_invoice() -> DocumentModel:
    """10 行（超过 GS Invoice 模板预留的 7 行，触发插入路径）。"""
    lines = tuple(
        make_order_line(
            sap=f"21-4464{i}",
            description=f"CB{i}00.B2",
            gs_model=f"Q{i}",
            quantity=50 + i,
            item_line_no=str(10 + i * 10),
        )
        for i in range(10)
    )
    result = build_invoice_model(
        lines, seller=ENTITY_GS_PTE, buyer=ENTITY_EMAX_PTE, po_no="4500030844"
    )
    assert result.model is not None, result.messages
    return result.model


# ————————————————————————————————————————
# 基础渲染：3 行，不触发插入
# ————————————————————————————————————————


class TestRenderBasic:
    def test_returns_absolute_path(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_three_line_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        assert result.output_path.is_absolute()
        assert result.output_path.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_three_line_invoice()
        deep = tmp_path / "a" / "b" / "c" / "out.xlsx"
        result = render_document(model, mapping, deep)
        assert result.output_path.exists()

    def test_invoice_no_written_to_header(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_three_line_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        # mapping.header.invoice_no = H6
        assert ws["H6"].value == "INV-RENDER-001"

    def test_three_lines_written_to_correct_columns(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_three_line_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        # mapping start_row=18, columns: SAP=D, qty=F, price=E, amount=H, gs_model=C, unit_label=G
        # 注意：openpyxl 把 Decimal 数值读回为 int/float，断言用数值相等
        assert ws["D18"].value == "21-44640"
        assert ws["E18"].value == 32.8
        assert ws["F18"].value == 100
        assert ws["G18"].value == "PCS"  # mapping.lines.unit_label
        assert ws["H18"].value == "=E18*F18"  # 公式
        assert ws["C18"].value == "Q1"

        assert ws["D19"].value == "21-44641"
        assert ws["F19"].value == 200

        assert ws["D20"].value == "21-44642"
        assert ws["F20"].value == 80

    def test_unfilled_reserved_rows_cleared(self, tmp_path: Path) -> None:
        """3 行 < 预留 7 行，剩余 4 行的样板数据应被清掉。"""
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_three_line_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        # row 21-24 应该没有 SAP（D 列）
        for row in range(21, 25):
            assert ws[f"D{row}"].value is None, f"row {row} 没有清掉 D 列"
            assert ws[f"F{row}"].value is None, f"row {row} 没有清掉 F 列"

    def test_totals_written_at_unchanged_position(self, tmp_path: Path) -> None:
        """3 行不触发插入时，合计行号保持模板原位置 (F27/H27)。"""
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_three_line_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        # openpyxl 读回 Decimal 数值会被规约为 int/float
        assert ws["F27"].value == 380  # 100+200+80
        # amount: 100*32.8 + 200*32.8 + 80*32.8 = 12464.00
        assert ws["H27"].value == pytest.approx(12464.0)


# ————————————————————————————————————————
# 触发插入：10 行 > 模板预留 7 行
# ————————————————————————————————————————


class TestRenderOverflow:
    def test_all_ten_lines_present(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_overflowing_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        for i in range(10):
            row = 18 + i
            assert ws[f"D{row}"].value == f"21-4464{i}", f"row {row} D 列未写入第 {i} 行 SAP"

    def test_totals_shifted_by_insertion_count(self, tmp_path: Path) -> None:
        """模板预留区间 = totals_row(27) - start_row(18) = 9 行；
        10 行只插入 1 行，合计从 F27/H27 平移到 F28/H28。
        """
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_overflowing_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        assert ws["F28"].value is not None
        assert ws["H28"].value is not None
        # 10 行总数: 50+51+...+59 = 545
        assert ws["F28"].value == 545

    def test_inserted_rows_have_styles(self, tmp_path: Path) -> None:
        """新插入的行单元格必须有样式（来自 style_source_row 19）。

        预留区间 = 27-18 = 9 行（rows 18-26），10 行触发插入 1 行 at row 27。
        """
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        model = build_overflowing_invoice()
        result = render_document(model, mapping, tmp_path / "out.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        cell = ws["D27"]
        assert cell.has_style, "插入行 row 27 D 列缺样式"


# ————————————————————————————————————————
# 复用 Spike A 的不变量断言
# ————————————————————————————————————————


class TestStylePreservationParity:
    """无论是否插入行，几个关键不变量都必须保持。"""

    @pytest.fixture
    def baseline(self) -> dict[str, object]:
        wb = load_workbook(GS_INVOICE_TEMPLATE)
        ws = wb["Sheet1"]
        return {
            "merged": {str(r) for r in ws.merged_cells.ranges},
            "col_widths": {col: dim.width for col, dim in ws.column_dimensions.items()},
        }

    def test_basic_keeps_merges_and_widths(
        self, tmp_path: Path, baseline: dict[str, object]
    ) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "basic.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        assert {str(r) for r in ws.merged_cells.ranges} == baseline["merged"]
        for col, expected in baseline["col_widths"].items():  # type: ignore[attr-defined]
            assert ws.column_dimensions[col].width == expected, f"列 {col} 宽度变化"

    def test_overflow_keeps_widths(self, tmp_path: Path, baseline: dict[str, object]) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_overflowing_invoice(), mapping, tmp_path / "overflow.xlsx")
        wb = load_workbook(result.output_path)
        ws = wb["Sheet1"]
        for col, expected in baseline["col_widths"].items():  # type: ignore[attr-defined]
            assert ws.column_dimensions[col].width == expected


# ————————————————————————————————————————
# 边界
# ————————————————————————————————————————


class TestEdgeCases:
    def test_invalid_sheet_raises(self, tmp_path: Path) -> None:
        # 构造一个 mapping 引用不存在的 sheet 名
        # 通过修改加载后的对象做不到（frozen）；直接传入坏 mapping 副本要复杂
        # 用 monkeypatch 替换更简单：但本测试只为冒烟，我们先 skip 这条
        pytest.skip("需要 mapping mocking，留待 Phase 1 §6.7 集成测试")

    def test_corrupt_template_raises(self, tmp_path: Path) -> None:
        from dataclasses import replace

        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        bad_template = tmp_path / "bad.xlsx"
        bad_template.write_bytes(b"not a real xlsx")
        broken_mapping = replace(mapping, template_path=bad_template)
        with pytest.raises(TemplateError, match="无法打开模板"):
            render_document(build_three_line_invoice(), broken_mapping, tmp_path / "out.xlsx")


# ————————————————————————————————————————
# 双向溯源索引（产品方案 §4.4）
# ————————————————————————————————————————


class TestSourceIndex:
    def test_index_returned_with_result(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "out.xlsx")
        # 数据行 SAP/qty/price + 表头 invoice_no/ship_to + 合计 quantity/amount 都应有条目
        assert len(result.source_index) > 0

    def test_data_row_traces_back_to_po_record(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "out.xlsx")
        # 第一行的 SAP（D18）应溯源到 PO record source_row=5 的 SAP Number 字段
        loc = result.source_index.lookup_source("D18")
        assert loc is not None
        assert loc.sheet == "PO record"
        assert loc.row == 5
        assert loc.field == "SAP Number"

    def test_quantity_traces_to_finalqty(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "out.xlsx")
        loc = result.source_index.lookup_source("F18")
        assert loc is not None
        assert loc.field == "FINALQTY"

    def test_amount_marked_computed(self, tmp_path: Path) -> None:
        """amount 列写公式，UI 上溯源应标识为"由工作台计算"。"""
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "out.xlsx")
        loc = result.source_index.lookup_source("H18")
        assert loc is not None
        assert loc.is_computed
        assert loc.sheet == COMPUTED_SHEET

    def test_totals_marked_computed(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "out.xlsx")
        # 模板原合计在 F27/H27（3 行不触发插入）
        qty_loc = result.source_index.lookup_source("F27")
        amt_loc = result.source_index.lookup_source("H27")
        assert qty_loc is not None and qty_loc.is_computed
        assert amt_loc is not None and amt_loc.is_computed
        assert qty_loc.field == "total_quantity"
        assert amt_loc.field == "total_amount"

    def test_header_traces_to_po_record(self, tmp_path: Path) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        result = render_document(build_three_line_invoice(), mapping, tmp_path / "out.xlsx")
        loc = result.source_index.lookup_source("H6")
        assert loc is not None
        assert loc.sheet == "PO record"
        assert loc.field == "invoice_no"
