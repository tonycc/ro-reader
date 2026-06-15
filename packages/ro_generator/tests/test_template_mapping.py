"""Template mapping 测试：YAML 解析 + 引用校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook
from ro_generator.errors import MappingError, TemplateError
from ro_generator.template_mapping import (
    LineColumns,
    TotalCell,
    TemplateMapping,
    load_template_mapping,
)

# ————————————————————————————————————————
# 真实 GS Invoice mapping 加载
# ————————————————————————————————————————


REPO_ROOT = Path(__file__).resolve().parents[3]
GS_INVOICE_MAPPING = REPO_ROOT / "templates" / "gs" / "mappings" / "invoice.yaml"
GS_PI_MAPPING = REPO_ROOT / "templates" / "gs" / "mappings" / "pi.yaml"
GS_PO_MAPPING = REPO_ROOT / "templates" / "gs" / "mappings" / "po.yaml"
EMAX_PI_MAPPING = REPO_ROOT / "templates" / "emax" / "mappings" / "pi.yaml"
EMAX_PO_MAPPING = REPO_ROOT / "templates" / "emax" / "mappings" / "po.yaml"
EMAX_INVOICE_MAPPING = REPO_ROOT / "templates" / "emax" / "mappings" / "invoice.yaml"
EMAX_PL_MAPPING = REPO_ROOT / "templates" / "emax" / "mappings" / "pl.yaml"
SK_PI_MAPPING = REPO_ROOT / "templates" / "sk" / "mappings" / "pi.yaml"
SK_PL_MAPPING = REPO_ROOT / "templates" / "sk" / "mappings" / "pl.yaml"
YM_PI_MAPPING = REPO_ROOT / "templates" / "ym" / "mappings" / "pi.yaml"
YM_PL_MAPPING = REPO_ROOT / "templates" / "ym" / "mappings" / "pl.yaml"


class TestRealGsInvoiceMapping:
    """对仓库内实际 mapping 做端到端验证。"""

    def test_loads_without_error(self) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        assert isinstance(mapping, TemplateMapping)

    def test_top_level_fields(self) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        assert mapping.document == "INVOICE"
        assert mapping.template_version == "2026.06"
        assert mapping.sheet == "INV"
        assert mapping.template_path.name == "invoice.xlsx"
        assert mapping.template_path.exists()

    def test_header_section(self) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        assert mapping.header["invoice_no"] == "H6"
        assert mapping.header["invoice_date"] == "H7"

    def test_lines_section(self) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        assert mapping.lines.start_row == 15
        assert mapping.lines.style_source_row == 15
        cols = mapping.lines.columns
        assert isinstance(cols, LineColumns)
        # 新版 GS Invoice 列布局 (2026.06 模板)
        assert cols.po_no == "B"
        assert cols.description == "C"
        assert cols.sap == "D"
        assert cols.unit_price == "E"
        assert cols.quantity == "F"
        assert cols.amount == "H"

    def test_totals_section(self) -> None:
        mapping = load_template_mapping(GS_INVOICE_MAPPING)
        assert mapping.totals["quantity"] == TotalCell(cell="F20")
        assert mapping.totals["amount"] == TotalCell(cell="H20")


class TestRealMappingsTableHeaderRows:
    @pytest.mark.parametrize(
        ("mapping_path", "expected_rows"),
        [
            (GS_PI_MAPPING, [19]),
            (GS_PO_MAPPING, [19]),
            (EMAX_INVOICE_MAPPING, [12, 13, 14]),
            (EMAX_PI_MAPPING, [17]),
            (EMAX_PO_MAPPING, [19]),
            (EMAX_PL_MAPPING, [9]),
            (SK_PI_MAPPING, [19]),
            (SK_PL_MAPPING, [8]),
            (YM_PI_MAPPING, [19]),
            (YM_PL_MAPPING, [8]),
        ],
    )
    def test_declares_table_header_row(self, mapping_path: Path, expected_rows: list[int]) -> None:
        mapping = load_template_mapping(mapping_path)
        assert mapping.table_header_row == expected_rows


# ————————————————————————————————————————
# 合成 fixture：可控的错误注入测试
# ————————————————————————————————————————


def make_template(tmp_path: Path, *, max_row: int = 30, max_col: int = 10) -> Path:
    """生成一个最小可识别的"模板"文件（足够覆盖默认 mapping 的引用）。"""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    # 通过写入边界单元格定义 max_row / max_col
    ws.cell(row=max_row, column=max_col, value="x")
    path = tmp_path / "template.xlsx"
    wb.save(path)
    return path


def write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def good_yaml_content(template_rel: str) -> str:
    return f"""\
document: invoice
template_version: "v1"
template: {template_rel}
sheet: Sheet1
header:
  invoice_no: H6
lines:
  start_row: 18
  style_source_row: 19
  columns:
    sap: D
    quantity: F
    unit_price: E
    amount: H
totals:
  amount: H27
"""


@pytest.fixture
def template_file(tmp_path: Path) -> Path:
    return make_template(tmp_path)


@pytest.fixture
def good_yaml(tmp_path: Path, template_file: Path) -> Path:
    yaml_path = tmp_path / "mapping.yaml"
    return write_yaml(yaml_path, good_yaml_content(str(template_file)))


# ————————————————————————————————————————
# 加载与基础解析
# ————————————————————————————————————————


class TestLoadBasic:
    def test_loads_synthetic_mapping(self, good_yaml: Path) -> None:
        mapping = load_template_mapping(good_yaml)
        assert mapping.document == "INVOICE"
        assert mapping.template_version == "v1"
        assert mapping.totals["amount"] == TotalCell(cell="H27")

    def test_loads_declared_total_value_mode(self, tmp_path: Path, template_file: Path) -> None:
        yaml_path = write_yaml(
            tmp_path / "mapping.yaml",
            f"""\
document: invoice
template_version: "v1"
template: {template_file}
sheet: Sheet1
header:
  invoice_no: H6
lines:
  start_row: 18
  style_source_row: 19
  columns:
    sap: D
    quantity: F
    unit_price: E
    amount: H
totals:
  amount: H27
  signature:
    cell: H28
    value_mode: fixed
    value: Joyce
  Date:
    cell: H29
    value_mode: current_date
""",
        )
        mapping = load_template_mapping(yaml_path)
        assert mapping.totals["signature"] == TotalCell(
            cell="H28",
            value_mode="fixed",
            value="Joyce",
        )
        assert mapping.totals["Date"] == TotalCell(cell="H29", value_mode="current_date")

    def test_loads_optional_table_header_row(self, tmp_path: Path, template_file: Path) -> None:
        yaml_path = write_yaml(
            tmp_path / "mapping.yaml",
            f"""\
document: invoice
template_version: "v1"
template: {template_file}
sheet: Sheet1
header:
  invoice_no: H6
table_header_row: 17
lines:
  start_row: 18
  style_source_row: 19
  columns:
    sap: D
    quantity: F
    unit_price: E
    amount: H
totals:
  amount: H27
""",
        )
        mapping = load_template_mapping(yaml_path)
        assert mapping.table_header_row == [17]

    def test_yaml_path_must_exist(self, tmp_path: Path) -> None:
        with pytest.raises(MappingError, match="mapping 文件不存在"):
            load_template_mapping(tmp_path / "nope.yaml")

    def test_yaml_root_must_be_dict(self, tmp_path: Path) -> None:
        path = write_yaml(tmp_path / "mapping.yaml", "- just\n- a list\n")
        with pytest.raises(MappingError, match="根节点必须是 dict"):
            load_template_mapping(path)

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        path = write_yaml(tmp_path / "mapping.yaml", "key: : invalid")
        with pytest.raises(MappingError, match="YAML 解析失败"):
            load_template_mapping(path)


# ————————————————————————————————————————
# 必填字段校验
# ————————————————————————————————————————


class TestRequiredFields:
    def test_missing_template_version(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file))
        content = content.replace('template_version: "v1"\n', "")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="template_version"):
            load_template_mapping(path)

    def test_missing_template_path_field(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file))
        content = content.replace(f"template: {template_file}\n", "")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="template"):
            load_template_mapping(path)

    def test_template_file_not_found(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path / "mapping.yaml",
            good_yaml_content("/path/to/nonexistent.xlsx"),
        )
        with pytest.raises(MappingError, match="模板文件不存在"):
            load_template_mapping(path)

    def test_unknown_document_type(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            "document: invoice", "document: receipt"
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="document 字段必须是"):
            load_template_mapping(path)

    def test_fixed_total_requires_value(self, tmp_path: Path, template_file: Path) -> None:
        path = write_yaml(
            tmp_path / "mapping.yaml",
            f"""\
document: invoice
template_version: "v1"
template: {template_file}
sheet: Sheet1
header:
  invoice_no: H6
lines:
  start_row: 18
  style_source_row: 19
  columns:
    sap: D
    quantity: F
    unit_price: E
    amount: H
totals:
  signature:
    cell: H28
    value_mode: fixed
""",
        )
        with pytest.raises(MappingError, match="value_mode=fixed"):
            load_template_mapping(path)

    def test_table_header_row_must_be_positive_int(self, tmp_path: Path, template_file: Path) -> None:
        path = write_yaml(
            tmp_path / "mapping.yaml",
            good_yaml_content(str(template_file)).replace(
                'sheet: Sheet1\n',
                'sheet: Sheet1\ntable_header_row: 0\n',
            ),
        )
        with pytest.raises(MappingError, match=r"table_header_row 必须为正整数|table_header_row\[0\] 必须为正整数"):
            load_template_mapping(path)


class TestLinesSection:
    def test_missing_lines_section(self, tmp_path: Path, template_file: Path) -> None:
        content = f"""\
document: invoice
template_version: "v1"
template: {template_file}
sheet: Sheet1
header:
  invoice_no: H6
totals:
  amount: H27
"""
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="lines"):
            load_template_mapping(path)

    def test_negative_start_row(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace("start_row: 18", "start_row: -1")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="必须为正整数"):
            load_template_mapping(path)

    def test_missing_required_column(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace("    quantity: F\n", "")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match=r"lines\.columns 缺少必填项"):
            load_template_mapping(path)

    def test_invalid_column_letter(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace("    sap: D", "    sap: '@@'")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="不是合法列字母"):
            load_template_mapping(path)

    def test_table_header_row_must_be_before_start_row(
        self, tmp_path: Path, template_file: Path
    ) -> None:
        content = good_yaml_content(str(template_file)).replace(
            'sheet: Sheet1\n',
            'sheet: Sheet1\ntable_header_row: 18\n',
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="都必须小于 lines.start_row"):
            load_template_mapping(path)

    def test_table_header_row_list_form(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            'sheet: Sheet1\n',
            'sheet: Sheet1\ntable_header_row:\n  - 16\n  - 17\n',
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        mapping = load_template_mapping(path)
        assert mapping.table_header_row == [16, 17]

    def test_table_header_row_empty_list_rejected(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            'sheet: Sheet1\n',
            'sheet: Sheet1\ntable_header_row: []\n',
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="不能为空列表"):
            load_template_mapping(path)

    def test_table_header_row_list_bad_item_rejected(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            'sheet: Sheet1\n',
            'sheet: Sheet1\ntable_header_row:\n  - 17\n  - 0\n',
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match=r"table_header_row\[1\] 必须为正整数"):
            load_template_mapping(path)


# ————————————————————————————————————————
# 模板引用校验（核心防漂移）
# ————————————————————————————————————————


class TestReferenceValidation:
    def test_header_cell_out_of_range_raises(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            "  invoice_no: H6", "  invoice_no: H999"
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match=r"header\.invoice_no.*超出模板范围"):
            load_template_mapping(path)

    def test_totals_cell_out_of_range_raises(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace("  amount: H27", "  amount: H999")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match=r"totals\.amount.*超出模板范围"):
            load_template_mapping(path)

    def test_style_source_row_beyond_max(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            "style_source_row: 19", "style_source_row: 999"
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="style_source_row"):
            load_template_mapping(path)

    def test_line_column_letter_beyond_max(self, tmp_path: Path, template_file: Path) -> None:
        # 模板默认 max_col=10 (J)。把列改到 Z 即超界
        content = good_yaml_content(str(template_file)).replace("    amount: H", "    amount: Z")
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="超过模板列数"):
            load_template_mapping(path)

    def test_sheet_not_in_template(self, tmp_path: Path, template_file: Path) -> None:
        content = good_yaml_content(str(template_file)).replace(
            "sheet: Sheet1", "sheet: NonExistent"
        )
        path = write_yaml(tmp_path / "mapping.yaml", content)
        with pytest.raises(MappingError, match="找不到 sheet"):
            load_template_mapping(path)

    def test_corrupted_template(self, tmp_path: Path) -> None:
        bogus = tmp_path / "bogus.xlsx"
        bogus.write_bytes(b"not a real xlsx")
        path = write_yaml(
            tmp_path / "mapping.yaml",
            good_yaml_content(str(bogus)),
        )
        with pytest.raises(TemplateError, match="无法打开模板"):
            load_template_mapping(path)


# ————————————————————————————————————————
# 不可变性
# ————————————————————————————————————————


def test_mapping_is_frozen(good_yaml: Path) -> None:
    import dataclasses

    mapping = load_template_mapping(good_yaml)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mapping.template_version = "v2"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        mapping.lines.start_row = 99  # type: ignore[misc]
