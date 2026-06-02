"""Workbook reader：把 base.xlsx 解析成结构化的 sheet 数据。

设计原则：
- 只读，绝不向 base 文件写回。
- `data_only=True`：公式列返回最近一次保存时的缓存值。读到 None 时由 resolver
  按产品方案 §10.4 的公式回退现算，reader 这一层不做计算。
- 不做语义校验：reader 关心结构（sheet 是否能打开、表头第几行、空白行如何跳过），
  validator 关心规则（必需表头是否齐、PO 是否存在等）。
- 行号一律 **1-based**（与 openpyxl 一致），dict 里以 `__row_number__` 暴露给下游。

每行返回 dict 而非 tuple，是为了把"列号"这个 Excel 细节限制在 reader 之内：
下游用规范化表头名取数据，例如 `row["SAP Number"]`，迁移列布局时只需改 schema。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ro_generator.errors import WorkbookOpenError
from ro_generator.schema import FIRST_DATA_ROW, HEADER_ROW, normalize_header

ROW_NUMBER_KEY: Final = "__row_number__"


@dataclass(frozen=True)
class SheetData:
    """单个 sheet 的解析结果。

    `headers` 与 `header_columns.keys()` 是同一份信息的两种视图，前者保留顺序。
    重复表头时**首次出现的列号胜出**（resolver 层若需要重复检查，可比较 length）。
    """

    sheet_name: str
    headers: tuple[str, ...]
    header_columns: dict[str, int]  # normalized header → 1-based column index
    rows: tuple[dict[str, object], ...]


class WorkbookReader:
    """对 openpyxl 的薄包装，按 base 文件的固定布局读两张 sheet。

    用法：

        with WorkbookReader(path) as reader:
            data = reader.read_sheet("PO record")
            for row in data.rows:
                print(row["SAP Number"], row["FINALQTY"])

    也可以不用 context manager，手动 `close()`。
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise WorkbookOpenError(f"base 文件不存在：{self._path}")
        if not self._path.is_file():
            raise WorkbookOpenError(f"base 路径不是文件：{self._path}")

        # read_only=True 流式读取，对 50K+ 行的 workbook 很重要。
        # data_only=True 让公式单元格返回缓存值。
        try:
            self._wb: Workbook = load_workbook(
                filename=str(self._path),
                read_only=True,
                data_only=True,
            )
        except Exception as exc:  # openpyxl 抛出的异常种类杂，统一包装
            raise WorkbookOpenError(f"无法打开 base 文件 {self._path}：{exc}") from exc

    # —————————————————————————————————————
    # Context manager
    # —————————————————————————————————————

    def __enter__(self) -> WorkbookReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._wb.close()

    # —————————————————————————————————————
    # Sheet 元信息
    # —————————————————————————————————————

    def sheet_names(self) -> tuple[str, ...]:
        return tuple(self._wb.sheetnames)

    def has_sheet(self, name: str) -> bool:
        return name in self._wb.sheetnames

    # —————————————————————————————————————
    # 主接口
    # —————————————————————————————————————

    def read_sheet(
        self,
        sheet_name: str,
        header_row: int = HEADER_ROW,
        first_data_row: int = FIRST_DATA_ROW,
    ) -> SheetData:
        """读取一个 sheet 并返回结构化结果。

        - `header_row`、`first_data_row` 默认值来自 schema.py，正常调用不需要传。
        - sheet 不存在抛 `WorkbookOpenError`（结构性问题，validator 不必再处理）。
        - 完全空白的数据行被跳过；只要任意一列非空就视为有效行。
        """
        if sheet_name not in self._wb.sheetnames:
            raise WorkbookOpenError(f"workbook 中找不到 sheet：{sheet_name!r}")

        ws: Worksheet = self._wb[sheet_name]
        headers, header_columns = self._read_headers(ws, header_row)
        rows = tuple(self._read_data_rows(ws, header_columns, first_data_row))

        return SheetData(
            sheet_name=sheet_name,
            headers=headers,
            header_columns=header_columns,
            rows=rows,
        )

    # —————————————————————————————————————
    # internals
    # —————————————————————————————————————

    @staticmethod
    def _read_headers(
        ws: Worksheet,
        header_row: int,
    ) -> tuple[tuple[str, ...], dict[str, int]]:
        """从指定行读出表头并规范化。

        重复表头时首次出现的列号胜出。空字符串表头（即原 cell 为空）跳过——
        它们不能用来索引数据。
        """
        # ws.iter_rows in read_only mode is forward-only; advance to header_row
        header_cells: tuple[object, ...] = ()
        for cur_row, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if cur_row == header_row:
                header_cells = tuple(row)
                break
        # 注意：如果 sheet 总行数 < header_row，header_cells 仍为 ()，下游会得到空 headers，
        # validator 会据此报"表头缺失"。

        ordered_headers: list[str] = []
        seen: dict[str, int] = {}
        for col_idx, raw in enumerate(header_cells, start=1):
            normalized = normalize_header(raw)
            if not normalized:
                continue
            if normalized not in seen:
                seen[normalized] = col_idx
                ordered_headers.append(normalized)
        return tuple(ordered_headers), seen

    @classmethod
    def _read_data_rows(
        cls,
        ws: Worksheet,
        header_columns: dict[str, int],
        first_data_row: int,
    ) -> Iterator[dict[str, object]]:
        """从 first_data_row 开始迭代非空行。

        read_only 模式下 ws.iter_rows 是前向流，不能随机访问，
        因此重新打开一次（_read_headers 已经消耗了迭代器）。
        """
        # 重新建立一次迭代器：read_only 工作表里读两次需要重新 iter_rows
        for cur_row, row_values in enumerate(ws.iter_rows(values_only=True), start=1):
            if cur_row < first_data_row:
                continue
            if _is_blank_row(row_values):
                continue
            row_dict: dict[str, object] = {ROW_NUMBER_KEY: cur_row}
            for header, col_idx in header_columns.items():
                # row_values 是 0-based tuple；col_idx 是 1-based。
                # 行长度可能短于 max column（read_only + 稀疏行常见），越界则填 None。
                value = row_values[col_idx - 1] if col_idx - 1 < len(row_values) else None
                row_dict[header] = value
            yield row_dict


def _is_blank_row(row_values: tuple[object, ...]) -> bool:
    """所有列都是 None 或空字符串才算空白行。

    不去除空格再判断：比如 `" "` 是用户故意留的占位，按非空对待，让 validator
    在数值字段上去捕捉这种异常。
    """
    return all(v is None or v == "" for v in row_values)


__all__ = ["ROW_NUMBER_KEY", "SheetData", "WorkbookReader"]
