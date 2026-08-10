"""SK/YM 主体过滤：按 CATEGORY 判定工厂卖方并过滤行。

CATEGORY 规则（产品方案 §6）：
- 1（combo）/ 2（rod）→ YM
- 3（reel）→ SK

此模块集中了 generator、workbook_snapshot 共用的 SK/YM 过滤逻辑，
避免规则散落在多个文件中导致分叉。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from ro_generator.models import OrderLine
from ro_generator.profiles.runtime import current_rules, current_schema

SK_YM_FACTORY_SELLERS: Final[frozenset[str]] = frozenset({"SK", "YM"})
ENTITIES_WITHOUT_PO: Final[frozenset[str]] = frozenset({"SK", "YM"})


def int_or_none(value: object) -> int | None:
    """将 Excel 单元格值安全转为 int，无法转换时返回 None。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else None
    except ImportError:
        pass
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def factory_seller_for_category(category: object) -> str | None:
    if category in (1, 2):
        return "YM"
    if category == 3:
        return "SK"
    return None


def factory_seller_for_line(line: OrderLine) -> str | None:
    return factory_seller_for_category(line.po_record_category)


def has_factory_categories(lines: tuple[OrderLine, ...]) -> bool:
    return any(factory_seller_for_line(line) is not None for line in lines)


def filter_lines_for_seller(
    lines: tuple[OrderLine, ...],
    seller: str,
) -> tuple[OrderLine, ...]:
    if seller not in SK_YM_FACTORY_SELLERS or not has_factory_categories(lines):
        return lines
    return tuple(line for line in lines if factory_seller_for_line(line) == seller)


def raw_row_factory_seller(row: dict[str, object]) -> str | None:
    category_field = current_schema().field("PO record", "category")
    return factory_seller_for_category(current_rules().category_for_value(row.get(category_field)))


def prefilter_raw_rows(
    rows: tuple[dict[str, object], ...],
    *,
    seller: str | None,
    documents: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    if not _should_prefilter(seller=seller, documents=documents):
        return rows
    if not any(raw_row_factory_seller(row) is not None for row in rows):
        return rows
    return tuple(row for row in rows if raw_row_factory_seller(row) == seller)


def raw_row_filter_for_request(
    *,
    seller: str | None,
    documents: tuple[str, ...],
) -> Callable[[dict[str, object]], bool] | None:
    if not _should_prefilter(seller=seller, documents=documents):
        return None

    def row_filter(row: dict[str, object]) -> bool:
        return raw_row_factory_seller(row) == seller

    return row_filter


def _should_prefilter(*, seller: str | None, documents: tuple[str, ...]) -> bool:
    return seller in SK_YM_FACTORY_SELLERS and set(documents) == {"PI"}


__all__ = [
    "ENTITIES_WITHOUT_PO",
    "SK_YM_FACTORY_SELLERS",
    "factory_seller_for_category",
    "factory_seller_for_line",
    "filter_lines_for_seller",
    "has_factory_categories",
    "int_or_none",
    "prefilter_raw_rows",
    "raw_row_factory_seller",
    "raw_row_filter_for_request",
]
