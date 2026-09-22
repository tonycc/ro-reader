"""PF options sheet 价格版本规则。

PF base 文件的 `options` sheet 按「卖方-单据族」键（如 `SK/YM-PI`、
`EMAX-INV`）提供「断点日期 → DATA BASE 行1价格组标签」的升序表。
行级单价按单据族对应的日期字段 floor 匹配断点，命中的版本标签
**字面完全相等**地匹配 DATA BASE 行1分组标签，组内取 COMBO 列。

- PI：键 `{卖方前缀}-PI`，日期 = 客户PO "PO Creation Date"
- INVOICE：键 `{卖方前缀}-INV`，日期 = PO record "ACTUAL EX FACTORY"

键约定（卖方前缀、单据后缀）由 Profile schema 的 `price_options`
段声明；RO 不声明，本模块不激活。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from ro_generator.base_schema import BaseSchema, PriceOptionConfig
from ro_generator.models import PriceGroup, ResolvedPrice
from ro_generator.schema import normalize_header
from ro_generator.workbook_reader import SheetData, WorkbookReader


@dataclass(frozen=True)
class PriceBreakpoint:
    """options 表中的一行：断点日期 → 价格版本标签。"""

    effective_from: date
    label: str


@dataclass(frozen=True)
class PriceBook:
    """一个 workbook 的价格版本表与 DATA BASE 价格组→列映射。"""

    # options 键（如 "SK/YM-PI"）→ 升序断点表
    options: Mapping[str, tuple[PriceBreakpoint, ...]]
    # DATA BASE 行1组标签 → 组内列定位
    groups: Mapping[str, PriceGroup]
    seller_keys: Mapping[str, str]
    doc_keys: Mapping[str, str]
    # 单据族 → 行日期字段的显示名（供来源摘要/告警文案使用）
    date_field_labels: Mapping[str, str] = field(default_factory=dict)
    # 解析期发现的 options 表数据问题（半行、缺键列等）
    issues: tuple[str, ...] = ()

    def collect_columns(self) -> tuple[str, ...]:
        """所有价格组内的列名（供 Product.data_base_prices 采集）。"""
        columns: list[str] = []
        seen: set[str] = set()
        for group in self.groups.values():
            for col in (group.combo, group.rod, group.reel):
                if col and col not in seen:
                    seen.add(col)
                    columns.append(col)
        return tuple(columns)

    def key_for(self, document_type: str, seller: str) -> str | None:
        prefix = self.seller_keys.get(seller)
        suffix = self.doc_keys.get(document_type)
        if prefix is None or suffix is None:
            return None
        return f"{prefix}-{suffix}"

    def resolve(
        self,
        document_type: str,
        seller: str,
        line_date: date | None,
    ) -> ResolvedPrice:
        """按断点 floor 匹配 + 组标签字面匹配解析一行应取的价格列。

        - 行日期早于首断点或缺失 → 取最早版本（首断点行）。
        - 行日期 ≥ 末断点 → 取末版本。
        - 版本标签与行1组标签严格字面匹配；无匹配组或组内无 COMBO 列
          返回 kind="missing"。
        """
        date_field = self.date_field_labels.get(document_type)
        key = self.key_for(document_type, seller)
        if key is None:
            return ResolvedPrice(kind="missing", line_date=line_date, date_field=date_field)
        breakpoints = self.options.get(key, ())
        if not breakpoints:
            return ResolvedPrice(
                kind="missing",
                option_key=key,
                line_date=line_date,
                date_field=date_field,
            )
        hit = breakpoints[0]
        if line_date is not None:
            for bp in breakpoints:
                if bp.effective_from <= line_date:
                    hit = bp
                else:
                    break
        group = self.groups.get(hit.label)
        column = group.combo if group is not None else None
        kind = "options" if group is not None and column is not None else "missing"
        return ResolvedPrice(
            kind=kind,
            option_key=key,
            line_date=line_date,
            date_field=date_field,
            breakpoint=hit.effective_from,
            version_label=hit.label,
            group=group,
            column=column,
        )


def load_price_book(reader: WorkbookReader, schema: BaseSchema) -> PriceBook | None:
    """从 reader 构建价格版本表；Profile 未声明 options 或 sheet 缺失时返回 None。

    options sheet 在 schema 中是必需 sheet，缺失由 schema 校验层报
    SHEET_MISSING；此处返回 None 仅是直接调用路径的兜底。
    """
    config = schema.price_options
    if config is None:
        return None
    options_cfg = schema.sheets.get(config.sheet)
    if options_cfg is None or not reader.has_sheet(options_cfg.name):
        return None
    options_sheet = reader.read_sheet(options_cfg.name)
    db_cfg = schema.sheet("DATA BASE")
    group_labels = reader.read_group_labels(db_cfg.name)
    db_headers = reader.read_headers(db_cfg.name)
    return build_price_book(
        options_sheet,
        group_labels,
        db_headers.header_columns,
        config,
        schema,
    )


def build_price_book(
    options_sheet: SheetData,
    group_labels: Mapping[int, str],
    db_header_columns: Mapping[str, int],
    config: PriceOptionConfig,
    schema: BaseSchema,
) -> PriceBook:
    """从已读取的 options 行 + DATA BASE 表头构建 PriceBook。

    options 的键列与取值列按**位置配对**（取值列 = 键列右邻），不依赖
    "取值" 后缀文案（实际表里有 `GS-INV取值字段` 这类不一致命名）。
    """
    col_to_header = {col: h for h, col in options_sheet.header_columns.items()}
    table: dict[str, tuple[PriceBreakpoint, ...]] = {}
    issues: list[str] = []
    for key in config.required_keys:
        idx = options_sheet.header_columns.get(key)
        if idx is None:
            issues.append(f"options 表缺少键列 {key!r}")
            continue
        label_header = col_to_header.get(idx + 1)
        if label_header is None:
            issues.append(f"options 表 {key!r} 右侧缺少取值列")
            continue
        breakpoints: list[PriceBreakpoint] = []
        for row in options_sheet.rows:
            raw_date = row.get(key)
            raw_label = row.get(label_header)
            if raw_date in (None, "") and raw_label in (None, ""):
                continue
            bp_date = _parse_breakpoint_date(raw_date)
            label = normalize_header(raw_label)
            if bp_date is None or not label:
                issues.append(f"options 表 {key!r} 存在不完整断点行：{raw_date!r} / {raw_label!r}")
                continue
            breakpoints.append(PriceBreakpoint(bp_date, label))
        breakpoints.sort(key=lambda bp: bp.effective_from)
        table[key] = tuple(breakpoints)

    groups = build_price_groups(group_labels, db_header_columns)
    date_field_labels = {
        "PI": schema.field("客户PO", "document_date"),
        "INVOICE": schema.field("PO record", "actual_ex_factory_date"),
    }
    return PriceBook(
        options=table,
        groups=groups,
        seller_keys=config.seller_keys,
        doc_keys=config.doc_keys,
        date_field_labels=date_field_labels,
        issues=tuple(issues),
    )


def build_price_groups(
    group_labels: Mapping[int, str],
    header_columns: Mapping[str, int],
) -> dict[str, PriceGroup]:
    """按行1分组标签把 DATA BASE 列切成组，组内定位 COMBO/ROD/REEL 列。

    组范围 = 标签所在列到下一个标签列之间（最后一个组延伸到最右表头列）。
    """
    col_to_header = {col: h for h, col in header_columns.items()}
    ordered = sorted(group_labels.items())
    max_col = max(header_columns.values(), default=0)
    groups: dict[str, PriceGroup] = {}
    for i, (start, label) in enumerate(ordered):
        end = ordered[i + 1][0] if i + 1 < len(ordered) else max_col + 1
        combo = rod = reel = None
        for col in range(start, end):
            header = col_to_header.get(col)
            if not header:
                continue
            upper = header.upper()
            if "COMBO" in upper and combo is None:
                combo = header
            elif "REEL" in upper and reel is None:
                reel = header
            elif "ROD" in upper and rod is None:
                rod = header
        groups[label] = PriceGroup(label=label, combo=combo, rod=rod, reel=reel)
    return groups


def _parse_breakpoint_date(value: object) -> date | None:
    """解析 options 断点日期：兼容 datetime、int(yyyymmdd) 和字符串。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(int(value))
    elif isinstance(value, str):
        text = re.sub(r"\D", "", value.strip())
    else:
        return None
    if len(text) != 8:
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


__all__ = [
    "PriceBook",
    "PriceBreakpoint",
    "build_price_book",
    "build_price_groups",
    "load_price_book",
]
