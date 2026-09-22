"""base 文件结构问题探测：把结构校验结果翻译成可修复的字段映射问题。

与 validator 的边界：
- validator 产出面向流水线的 blocking_error，装配一遇到就停。
- 本模块把同样的校验结果转成面向用户的「问题清单 + 可候选列」，
  供修复向导展示。它不决定怎么修，只描述"哪一列没对上"和"sheet 里现有
  哪些列可选"。

修复向导只需要 L1（结构映射）层面的问题；价格列等敏感配置不进入候选，
避免业务用户误改金额来源。
"""

from __future__ import annotations

from dataclasses import dataclass

from openpyxl.utils import get_column_letter

from ro_generator.base_schema import BaseSchema
from ro_generator.schema import required_headers_for
from ro_generator.workbook_reader import SheetHeaders, WorkbookReader

# 逻辑 sheet → schema 字段属性名 + 用户可读标签。
_SHEET_META: dict[str, tuple[str, str]] = {
    "DATA BASE": ("data_base_fields", "产品主数据"),
    "PO record": ("po_record_fields", "PO/出货记录"),
    "客户PO": ("customer_po_fields", "客户订单"),
    "options": ("options", "价格选项"),
}


@dataclass(frozen=True)
class SchemaFieldIssue:
    """一条表头映射问题。

    `remappable=False` 表示该问题无法通过修复向导的列重映射解决，只能修正
    workbook 本身。options 价格版本表属于此类：它的"表头"是业务约定的键
    （如 `SK/YM-PI`）和其右侧取值列，不走 field_aliases override 通道，
    给用户下拉选择只会产生"保存后问题依旧"的假修复。
    """

    logical_sheet: str  # 逻辑 sheet key（"DATA BASE"/"PO record"/"客户PO"）
    sheet_label: str  # 用户可读 sheet 名
    actual_sheet: str  # 生效 schema 下的真实 sheet 名
    internal_key: str  # 内部字段键
    expected_header: str  # 当前生效 schema 期望的表头
    available_headers: tuple[str, ...]  # 该 sheet 现有可选列
    column_letters: dict[str, str]  # 表头 → Excel 列号（A、B、…），供下拉显示
    remappable: bool = True  # False 时修复向导不提供列映射，只提示修正 workbook
    repair_hint: str = ""  # remappable=False 时给业务的修正说明


@dataclass(frozen=True)
class SchemaSheetIssue:
    """整张 sheet 缺失，无法逐列修复。"""

    logical_sheet: str
    sheet_label: str
    actual_sheet: str


@dataclass(frozen=True)
class SchemaInspection:
    """一次结构探测的完整结果。"""

    sheet_issues: tuple[SchemaSheetIssue, ...]
    field_issues: tuple[SchemaFieldIssue, ...]
    price_issues: tuple[SchemaFieldIssue, ...] = ()

    def has_issues(self) -> bool:
        return bool(self.sheet_issues or self.field_issues or self.price_issues)


def inspect_schema(
    reader: WorkbookReader,
    schema: BaseSchema,
    *,
    skip_sheets: tuple[str, ...] = (),
) -> SchemaInspection:
    """对生效 schema（内置+override）探测 base 文件的结构问题。

    只读 workbook 表头，不消费数据行；调用方负责提供已按生效 schema
    构造的 reader。`skip_sheets` 跳过指定 sheet 的逐列表头检测（如大表
    DATA BASE 的性能优化），但 sheet 存在性始终检查。
    """

    required_by_sheet = required_headers_for(schema)
    options_sheet_key = schema.price_options.sheet if schema.price_options is not None else None

    sheet_issues: list[SchemaSheetIssue] = []
    field_issues: list[SchemaFieldIssue] = []
    price_issues: list[SchemaFieldIssue] = []

    for logical_sheet, sheet_cfg in schema.sheets.items():
        actual_sheet = sheet_cfg.name
        sheet_label = _SHEET_META.get(logical_sheet, ("", logical_sheet))[1]
        if not reader.has_sheet(actual_sheet):
            sheet_issues.append(
                SchemaSheetIssue(
                    logical_sheet=logical_sheet,
                    sheet_label=sheet_label,
                    actual_sheet=actual_sheet,
                )
            )
            continue

        if actual_sheet in skip_sheets:
            continue

        available, letters = sheet_header_candidates(reader, schema, logical_sheet, actual_sheet)
        present = set(available)
        is_options = logical_sheet == options_sheet_key

        for expected in required_by_sheet.get(logical_sheet, ()):
            if expected in present:
                continue
            internal_key = _internal_key_for(schema, logical_sheet, expected)
            field_issues.append(
                SchemaFieldIssue(
                    logical_sheet=logical_sheet,
                    sheet_label=sheet_label,
                    actual_sheet=actual_sheet,
                    internal_key=internal_key or expected,
                    expected_header=expected,
                    available_headers=available,
                    column_letters=letters,
                    remappable=not is_options,
                    repair_hint=(
                        f"请在 {actual_sheet!r} sheet 中把该价格版本键列的表头改回 {expected!r}"
                        if is_options
                        else ""
                    ),
                )
            )

        # options 的取值列靠位置约定（键列右邻一列）而非表头名定位；右邻缺表头时
        # 版本标签读不到，必须在结构校验阶段阻断，不能留到行级静默取不到价。
        if is_options:
            field_issues.extend(
                _detect_options_value_column_issues(
                    reader,
                    schema,
                    actual_sheet=actual_sheet,
                    sheet_label=sheet_label,
                    logical_sheet=logical_sheet,
                    present=present,
                    available=available,
                    column_letters=letters,
                )
            )

        # DATA BASE 的价格列单独检测：这些列不在字段别名里，但缺失会导致
        # 静默取不到价。候选列为 DATA BASE 现有列。
        if logical_sheet == "DATA BASE":
            price_issues.extend(
                _detect_price_issues(schema, actual_sheet, sheet_label, present, available, letters)
            )

    return SchemaInspection(
        sheet_issues=tuple(sheet_issues),
        field_issues=tuple(field_issues),
        price_issues=tuple(price_issues),
    )


def _detect_options_value_column_issues(
    reader: WorkbookReader,
    schema: BaseSchema,
    *,
    actual_sheet: str,
    sheet_label: str,
    logical_sheet: str,
    present: set[str],
    available: tuple[str, ...],
    column_letters: dict[str, str],
) -> list[SchemaFieldIssue]:
    """检测 options 每个键列右邻的取值列表头是否存在。

    options 的一对列是「断点日期键列 + 紧邻右侧的版本标签列」，取值列的表头
    命名在真实文件里并不统一（`GS-INV取值字段` 等），因此按位置而非名称配对。
    右邻列没有表头时该键的版本标签全部读不到，等同于价格规则失效。
    """

    config = schema.price_options
    if config is None:
        return []
    headers = reader.read_headers(actual_sheet)
    columns = headers.header_columns
    occupied = set(columns.values())
    issues: list[SchemaFieldIssue] = []
    for key in config.required_keys:
        if key not in present:
            continue  # 键列本身缺失已单独报过，不重复报右邻列
        index = columns.get(key)
        if index is not None and index + 1 in occupied:
            continue
        issues.append(
            SchemaFieldIssue(
                logical_sheet=logical_sheet,
                sheet_label=sheet_label,
                actual_sheet=actual_sheet,
                internal_key=f"{key}/value",
                expected_header=f"{key} 右侧的版本标签取值列",
                available_headers=available,
                column_letters=column_letters,
                remappable=False,
                repair_hint=(
                    f"请在 {actual_sheet!r} sheet 的 {key!r} 列右侧补上带表头的版本标签列"
                ),
            )
        )
    return issues


def _detect_price_issues(
    schema: BaseSchema,
    actual_sheet: str,
    sheet_label: str,
    present: set[str],
    available: tuple[str, ...],
    column_letters: dict[str, str],
) -> list[SchemaFieldIssue]:
    """检测 DATA BASE 各价格块中期望表头缺失的价格键。"""

    issues: list[SchemaFieldIssue] = []
    seen: set[str] = set()
    for block in (
        schema.data_base_price_columns,
        schema.invoice_data_base_price_columns,
        schema.data_base_component_price_columns,
    ):
        for price_key, expected in block.items():
            # 同一价格键可能出现在多个块；按 (块内) 键去重，缺失时对每个
            # 受影响的价格键各报一条，便于修复向导逐个重定向。
            if price_key in seen:
                continue
            seen.add(price_key)
            if expected in present:
                continue
            issues.append(
                SchemaFieldIssue(
                    logical_sheet="DATA BASE",
                    sheet_label=sheet_label,
                    actual_sheet=actual_sheet,
                    internal_key=price_key,
                    expected_header=expected,
                    available_headers=available,
                    column_letters=column_letters,
                )
            )
    return issues


def sheet_header_candidates(
    reader: WorkbookReader,
    schema: BaseSchema,
    logical_sheet: str,
    actual_sheet: str,
) -> tuple[tuple[str, ...], dict[str, str]]:
    """返回某张逻辑 sheet 的现有表头和 Excel 列号，供修复向导与总览下拉使用。"""

    if not reader.has_sheet(actual_sheet):
        return (), {}
    kwargs: dict[str, int] = {}
    if logical_sheet == "客户PO":
        kwargs["header_row"] = schema.sheet("客户PO").header_row
    headers_result = reader.read_headers(actual_sheet, **kwargs)
    return headers_result.headers, _column_letters(headers_result)


def _column_letters(headers: SheetHeaders) -> dict[str, str]:
    """把 reader 的 1-based 列号转成 Excel 列字母，供下拉显示。"""

    return {header: get_column_letter(index) for header, index in headers.header_columns.items()}


def _internal_key_for(schema: BaseSchema, logical_sheet: str, header: str) -> str | None:
    """反查某个期望表头对应的内部字段键；找不到时返回 None。"""

    return schema.internal_field_key(logical_sheet, header)


__all__ = [
    "SchemaFieldIssue",
    "SchemaInspection",
    "SchemaSheetIssue",
    "inspect_schema",
    "sheet_header_candidates",
]
