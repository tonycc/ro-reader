"""双向溯源索引（产品方案 §4.4）。

记录"装配输出的某个单元格 ← → base 文件中的源字段"映射。
工作台 UI 消费此索引实现：

- hover 文档预览中的单元格 → 高亮 PO record 中的源字段
- 点击数据视图字段 → 高亮所有引用它的文档位置
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

# 一个伪 sheet 名，表示"由工作台计算得出"（如 amount = qty × price 的乘积）
COMPUTED_SHEET: Final = "__computed__"


@dataclass(frozen=True)
class SourceLocation:
    """base 文件中的某个数据点。

    `sheet`==COMPUTED_SHEET 时表示该值由工作台计算（amount 等公式列）；
    `row` 为 None 时表示来自整个 sheet 的元信息（如 sheet 级别的 INV# 字段汇总值）。
    """

    sheet: str
    row: int | None
    field: str

    @property
    def is_computed(self) -> bool:
        return self.sheet == COMPUTED_SHEET


@dataclass(frozen=True)
class SourceIndex:
    """单据中的单元格 → base 中字段的映射。

    `entries` 是 `{doc_cell_address: SourceLocation}` 的不可变快照（用 frozenset
    of 2-tuple 模拟）。提供正向 / 反向查询的便利方法。
    """

    entries: tuple[tuple[str, SourceLocation], ...]

    def lookup_source(self, doc_cell: str) -> SourceLocation | None:
        """给定文档单元格地址（如 "D18"），返回它的源；不存在时返回 None。"""
        for cell, loc in self.entries:
            if cell == doc_cell:
                return loc
        return None

    def lookup_doc_cells(self, source: SourceLocation) -> tuple[str, ...]:
        """给定源位置，返回所有引用它的文档单元格地址。"""
        return tuple(cell for cell, loc in self.entries if loc == source)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[tuple[str, SourceLocation]]:
        return iter(self.entries)


class SourceIndexBuilder:
    """渲染期间累积索引条目，最终冻结为 SourceIndex。

    设计为可变 builder + 不可变结果，避免渲染过程中索引被无意修改。
    """

    def __init__(self) -> None:
        self._entries: list[tuple[str, SourceLocation]] = []

    def add(self, doc_cell: str, location: SourceLocation) -> None:
        self._entries.append((doc_cell, location))

    def add_computed(self, doc_cell: str, field: str) -> None:
        """便捷方法：标记该单元格由工作台计算（如 amount 公式列）。"""
        self._entries.append((doc_cell, SourceLocation(COMPUTED_SHEET, None, field)))

    def build(self) -> SourceIndex:
        return SourceIndex(entries=tuple(self._entries))


__all__ = [
    "COMPUTED_SHEET",
    "SourceIndex",
    "SourceIndexBuilder",
    "SourceLocation",
]
