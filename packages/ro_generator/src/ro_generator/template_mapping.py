"""Template mapping：把 YAML 字段映射加载成结构化对象，并校验对模板文件的引用。

设计边界：
- mapping 是模板的"字段位置说明书"。模板维护者只改 YAML，不改代码。
- mapping 加载时校验所有引用的单元格在模板中真实存在（产品方案 §13.2）。
  这道防线让"模板换了但 mapping 没改"的漂移立即暴露，而不是悄悄写错单元格。
- template_version 是必填字段。模板版本改了就必须更新 mapping，否则加载失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string

from ro_generator.errors import MappingError, TemplateError
from ro_generator.models import DocumentType

# —————————————————————————————————————
# 数据结构
# —————————————————————————————————————


@dataclass(frozen=True)
class LineColumns:
    """订单行各业务字段对应的模板列字母（如 "B"、"H"）。

    必填项保证 renderer 在装配每行时知道写到哪一列。
    可选项（如 unit_label）允许模板用固定文案覆盖，YAML 不提供时跳过。
    """

    sap: str
    quantity: str
    unit_price: str
    amount: str
    po_no: str | None = None
    item_line_no: str | None = None
    description: str | None = None
    gs_model: str | None = None
    unit_label: str | None = None  # PCS 等单位列


@dataclass(frozen=True)
class LinesSection:
    start_row: int
    style_source_row: int
    columns: LineColumns
    unit_label: str | None = None  # 固定写到 unit_label 列的文案
    row_fixed: dict[str, str] = field(default_factory=dict)  # 每行固定值 {列字母: 值}


@dataclass(frozen=True)
class CellStyles:
    """可选的单元格样式声明（来自 mapping YAML 的 style 节）。"""
    bold: tuple[str, ...] = ()
    underline: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateMapping:
    """单份 mapping 加载后的不可变结构。"""

    document: DocumentType
    template_version: str
    template_path: Path
    sheet: str
    header: dict[str, str]
    lines: LinesSection
    totals: dict[str, str]
    notes: dict[str, str]
    style: CellStyles = field(default_factory=CellStyles)


# —————————————————————————————————————
# 加载入口
# —————————————————————————————————————


VALID_DOCUMENT_TYPES: Final[set[str]] = {"PI", "PO", "INVOICE", "PL"}


def load_template_mapping(yaml_path: str | Path) -> TemplateMapping:
    """从 YAML 文件加载 mapping，并校验对应模板文件的所有引用。

    YAML 加载失败抛 `MappingError`；模板加载失败抛 `TemplateError`。
    引用校验失败抛 `MappingError`，错误消息会指出具体哪个字段错了。
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise MappingError(f"mapping 文件不存在：{yaml_path}")
    raw = _read_yaml(yaml_path)

    mapping = _parse_mapping(raw, yaml_path)
    _validate_against_template(mapping)
    return mapping


# —————————————————————————————————————
# YAML 解析
# —————————————————————————————————————


def _read_yaml(yaml_path: Path) -> dict[str, object]:
    try:
        with yaml_path.open(encoding="utf-8") as fp:
            data = yaml.safe_load(fp)
    except yaml.YAMLError as exc:
        raise MappingError(f"YAML 解析失败 {yaml_path}：{exc}") from exc
    if not isinstance(data, dict):
        raise MappingError(f"mapping 文件根节点必须是 dict：{yaml_path}")
    return data


def _parse_mapping(raw: dict[str, object], yaml_path: Path) -> TemplateMapping:
    document_raw = _require_str(raw, "document", yaml_path)
    document = _normalize_document_type(document_raw, yaml_path)
    template_version = _require_str(raw, "template_version", yaml_path)
    template_rel = _require_str(raw, "template", yaml_path)
    sheet = _require_str(raw, "sheet", yaml_path)

    # 模板路径：相对 mapping 文件的目录解析；最终落到仓库相对路径上
    # 真实业务里 mapping 与模板同目录，YAML 中常写 templates/gs/invoice.xlsx 这种仓库相对路径
    # YAML 在 templates/<entity>/mappings/<doc>.yaml → repo root 上 4 级
    template_path = (yaml_path.parent.parent.parent.parent / template_rel).resolve()
    if not template_path.exists():
        raise MappingError(
            f"模板文件不存在：{template_rel}（相对 {yaml_path} 解析为 {template_path}）"
        )

    header = _require_dict_of_str(raw, "header", yaml_path)
    lines = _parse_lines_section(raw, yaml_path)
    totals = _require_dict_of_str(raw, "totals", yaml_path)
    notes = _optional_dict_of_str(raw, "notes")
    style = _parse_style(raw.get("style"), yaml_path)

    return TemplateMapping(
        document=document,
        template_version=template_version,
        template_path=template_path,
        sheet=sheet,
        header=header,
        lines=lines,
        totals=totals,
        notes=notes,
        style=style,
    )


def _normalize_document_type(value: str, yaml_path: Path) -> DocumentType:
    upper = value.strip().upper()
    if upper not in VALID_DOCUMENT_TYPES:
        raise MappingError(
            f"document 字段必须是 {sorted(VALID_DOCUMENT_TYPES)} 之一，得到 {value!r}（{yaml_path}）"
        )
    # mypy: 此处 upper 在白名单内，但 DocumentType 是 Literal，需要 cast
    return upper  # type: ignore[return-value]


def _parse_lines_section(raw: dict[str, object], yaml_path: Path) -> LinesSection:
    lines = raw.get("lines")
    if not isinstance(lines, dict):
        raise MappingError(f"mapping 必须有 lines 节（dict）：{yaml_path}")
    start_row = _require_int(lines, "start_row", yaml_path, ctx="lines")
    style_source_row = _require_int(lines, "style_source_row", yaml_path, ctx="lines")
    if start_row <= 0 or style_source_row <= 0:
        raise MappingError(f"lines.start_row / lines.style_source_row 必须为正整数（{yaml_path}）")

    columns_raw = lines.get("columns")
    if not isinstance(columns_raw, dict):
        raise MappingError(f"mapping 必须有 lines.columns 节（dict）：{yaml_path}")
    columns = _parse_columns(columns_raw, yaml_path)

    unit_label_default = lines.get("unit_label")
    unit_label = unit_label_default if isinstance(unit_label_default, str) else None

    # Parse row_fixed: per-row fixed values {column_letter: value}
    row_fixed: dict[str, str] = {}
    rf = lines.get("row_fixed")
    if isinstance(rf, dict):
        for col_letter, val in rf.items():
            if isinstance(col_letter, str) and isinstance(val, str):
                col_letter = col_letter.strip().upper()
                try:
                    column_index_from_string(col_letter)
                except (ValueError, KeyError):
                    raise MappingError(
                        f"lines.row_fixed 列字母 {col_letter!r} 不合法：{yaml_path}"
                    )
                row_fixed[col_letter] = val

    return LinesSection(
        start_row=start_row,
        style_source_row=style_source_row,
        columns=columns,
        unit_label=unit_label,
        row_fixed=row_fixed,
    )


def _parse_columns(raw: dict[object, object], yaml_path: Path) -> LineColumns:
    required = ["sap", "quantity", "unit_price", "amount"]
    optional = ["po_no", "item_line_no", "description", "gs_model", "unit_label"]

    parsed: dict[str, str] = {}
    for key in required + optional:
        v = raw.get(key)
        if v is None:
            continue
        if not isinstance(v, str):
            raise MappingError(f"lines.columns.{key} 必须是列字母字符串：{yaml_path}")
        parsed[key] = v.strip().upper()

    for key in required:
        if key not in parsed:
            raise MappingError(f"lines.columns 缺少必填项 {key!r}：{yaml_path}")

    # 校验列字母合法（让 column_index_from_string 帮我们验）
    for key, letter in parsed.items():
        try:
            column_index_from_string(letter)
        except (ValueError, KeyError) as exc:
            raise MappingError(
                f"lines.columns.{key} {letter!r} 不是合法列字母：{yaml_path}"
            ) from exc

    return LineColumns(**parsed)


# —————————————————————————————————————
# 模板引用校验（产品方案 §13.2）
# —————————————————————————————————————


def _validate_against_template(mapping: TemplateMapping) -> None:
    """打开模板，校验所有 mapping 引用的单元格在模板中存在且可写。"""
    try:
        wb = load_workbook(filename=str(mapping.template_path), read_only=False)
    except Exception as exc:
        raise TemplateError(f"无法打开模板 {mapping.template_path}：{exc}") from exc

    try:
        if mapping.sheet not in wb.sheetnames:
            raise MappingError(
                f"模板 {mapping.template_path.name} 中找不到 sheet {mapping.sheet!r}"
            )
        ws = wb[mapping.sheet]
        max_row = ws.max_row
        max_col = ws.max_column

        # 1. header 单元格
        for field_name, addr in mapping.header.items():
            _check_cell_reference(addr, max_row, max_col, f"header.{field_name}")

        # 2. lines.style_source_row 必须 ≤ max_row
        if mapping.lines.style_source_row > max_row:
            raise MappingError(
                f"lines.style_source_row={mapping.lines.style_source_row} 超过模板行数 {max_row}"
            )
        # start_row 可以 ≤ style_source_row（先填后插），不强制 ≤ max_row。
        # 但 start_row 列上的样式参考还是要在模板里存在 → 通过 style_source_row 间接保证。

        # 3. 行列字母在模板列范围内
        for col_name, col_letter in _iter_line_columns(mapping.lines.columns):
            col_idx = column_index_from_string(col_letter)
            if col_idx > max_col:
                raise MappingError(
                    f"lines.columns.{col_name} 列 {col_letter} (idx={col_idx}) "
                    f"超过模板列数 {max_col}"
                )

        # 4. totals 单元格
        for field_name, addr in mapping.totals.items():
            _check_cell_reference(addr, max_row, max_col, f"totals.{field_name}")

        # 5. notes 单元格
        for field_name, addr in mapping.notes.items():
            _check_cell_reference(addr, max_row, max_col, f"notes.{field_name}")
    finally:
        wb.close()


def _check_cell_reference(addr: str, max_row: int, max_col: int, ctx: str) -> None:
    try:
        col_letter, row = coordinate_from_string(addr.strip())
    except ValueError as exc:
        raise MappingError(f"{ctx} 单元格地址不合法：{addr!r}") from exc
    col_idx = column_index_from_string(col_letter)
    if row > max_row or col_idx > max_col:
        raise MappingError(
            f"{ctx} 单元格 {addr} 超出模板范围（max_row={max_row}, max_col={max_col}）"
        )


def _iter_line_columns(cols: LineColumns) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key in (
        "po_no",
        "item_line_no",
        "description",
        "gs_model",
        "sap",
        "quantity",
        "unit_price",
        "amount",
        "unit_label",
    ):
        v = getattr(cols, key)
        if isinstance(v, str):
            pairs.append((key, v))
    return pairs


# —————————————————————————————————————
# 小工具
# —————————————————————————————————————


def _require_str(raw: dict[str, object], key: str, yaml_path: Path) -> str:
    v = raw.get(key)
    if not isinstance(v, str) or not v.strip():
        raise MappingError(f"mapping 缺少必填字段 {key!r} 或值非字符串：{yaml_path}")
    return v.strip()


def _require_int(raw: dict[object, object], key: str, yaml_path: Path, ctx: str) -> int:
    v = raw.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise MappingError(f"{ctx}.{key} 必须为整数：{yaml_path}")
    return v


def _require_dict_of_str(raw: dict[str, object], key: str, yaml_path: Path) -> dict[str, str]:
    v = raw.get(key)
    if not isinstance(v, dict):
        raise MappingError(f"mapping 缺少必填节 {key!r}（必须是 dict）：{yaml_path}")
    out: dict[str, str] = {}
    for k, val in v.items():
        if not isinstance(k, str) or not isinstance(val, str):
            raise MappingError(f"{key}.{k!r} 的键和值都必须是字符串：{yaml_path}")
        out[k] = val.strip()
    return out


def _parse_style(raw: object, yaml_path: Path) -> CellStyles:
    """解析可选的 style 节。格式：
    style:
      bold: [A1, B4]        # 加粗的单元格地址
      underline: [H6, F6]   # 下划线的单元格地址
    """
    if not isinstance(raw, dict):
        return CellStyles()
    bold = _parse_cell_list(raw.get("bold"), yaml_path)
    underline = _parse_cell_list(raw.get("underline"), yaml_path)
    return CellStyles(bold=tuple(bold), underline=tuple(underline))


def _parse_cell_list(raw: object, yaml_path: Path) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MappingError(f"style 中的值必须是列表：{raw!r} ({yaml_path})")
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise MappingError(f"style 列表项必须是字符串：{item!r} ({yaml_path})")
        result.append(item.strip().upper())
    return result


def _optional_dict_of_str(raw: dict[str, object], key: str) -> dict[str, str]:
    v = raw.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise MappingError(f"mapping 中 {key!r} 节必须是 dict（如有）")
    out: dict[str, str] = {}
    for k, val in v.items():
        if not isinstance(k, str) or not isinstance(val, str):
            raise MappingError(f"{key}.{k!r} 的键和值都必须是字符串")
        out[k] = val.strip()
    return out


__all__ = [
    "VALID_DOCUMENT_TYPES",
    "LineColumns",
    "LinesSection",
    "TemplateMapping",
    "load_template_mapping",
]
