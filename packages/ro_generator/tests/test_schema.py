"""Schema 测试：聚焦表头规范化（§6.1 必需测试）。"""

from __future__ import annotations

import pytest
from ro_generator.schema import (
    DATA_BASE_REQUIRED_HEADERS,
    HEADER_ROW,
    LEGAL_CHAIN_SEGMENTS,
    MONTH_COLUMNS,
    PO_RECORD_REQUIRED_HEADERS,
    REQUIRED_SHEETS,
    normalize_header,
    normalize_headers,
)


class TestNormalizeHeader:
    """实测 RO DATA BASE.xlsx 中观察到的表头变形（CLAUDE.md 中的"换行和多余空格"）。"""

    def test_collapses_newline_to_space(self) -> None:
        assert normalize_header("GS PTE \nFOB ") == "GS PTE FOB"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert normalize_header("  SAP  ") == "SAP"

    def test_collapses_multiple_spaces(self) -> None:
        assert normalize_header("PO   NO.") == "PO NO."

    def test_handles_tabs(self) -> None:
        assert normalize_header("CATEGORY\t") == "CATEGORY"

    def test_handles_mixed_whitespace(self) -> None:
        assert normalize_header("  GS \n PTE  \t FOB ") == "GS PTE FOB"

    def test_handles_full_width_space(self) -> None:
        # 中文环境下偶尔会出现全角空格
        assert normalize_header("SAP　Number") == "SAP Number"

    def test_preserves_case(self) -> None:
        # 大小写有业务含义，不能丢
        assert normalize_header("INV#") == "INV#"
        assert normalize_header("Inv#") == "Inv#"

    def test_preserves_punctuation_and_special_chars(self) -> None:
        assert normalize_header("PO NO.") == "PO NO."
        assert normalize_header("INV#") == "INV#"
        assert normalize_header("ITEM LINE#") == "ITEM LINE#"
        assert normalize_header("N/W") == "N/W"

    def test_preserves_chinese(self) -> None:
        assert normalize_header("外箱") == "外箱"
        assert normalize_header("包装") == "包装"

    def test_empty_string(self) -> None:
        assert normalize_header("") == ""

    def test_whitespace_only_string(self) -> None:
        assert normalize_header("   \n\t  ") == ""

    @pytest.mark.parametrize("raw", [None, 42, 3.14, [], {}, object()])
    def test_non_string_returns_empty(self, raw: object) -> None:
        # openpyxl 读到空单元格或非字符串时，规范化必须不抛异常
        assert normalize_header(raw) == ""


class TestNormalizeHeaders:
    def test_batch(self) -> None:
        raw: list[object] = ["  SAP  ", "GS PTE \nFOB ", None, "CATEGORY"]
        assert normalize_headers(raw) == ["SAP", "GS PTE FOB", "", "CATEGORY"]

    def test_empty_input(self) -> None:
        assert normalize_headers([]) == []


class TestSchemaConstants:
    """对静态常量做防回归断言，避免有人误改。"""

    def test_required_sheets(self) -> None:
        assert REQUIRED_SHEETS == ("DATA BASE", "PO record")

    def test_header_row_position(self) -> None:
        # CLAUDE.md "源数据结构"明确：表头第 4 行
        assert HEADER_ROW == 4

    def test_month_columns_cover_full_year(self) -> None:
        assert len(MONTH_COLUMNS) == 12
        assert MONTH_COLUMNS[0] == "2601"
        assert MONTH_COLUMNS[-1] == "2612"

    def test_data_base_headers_includes_sap(self) -> None:
        assert "SAP" in DATA_BASE_REQUIRED_HEADERS

    def test_po_record_headers_include_po_and_qty(self) -> None:
        assert "PO NO." in PO_RECORD_REQUIRED_HEADERS
        assert "FINALQTY" in PO_RECORD_REQUIRED_HEADERS

    def test_legal_chain_has_three_segments(self) -> None:
        # 产品方案 §3.3：工厂 → SK/YM → GS PTE → EMAX PTE → PF
        # 三段链路（不含工厂段，工厂不参与单据装配）
        assert len(LEGAL_CHAIN_SEGMENTS) == 3

    def test_legal_chain_terminates_at_pf(self) -> None:
        # 最后一段必须是 EMAX PTE → PF
        assert LEGAL_CHAIN_SEGMENTS[-1] == ("EMAX PTE", "PF")
