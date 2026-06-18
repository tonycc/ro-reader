"""结构性校验：base workbook 是否有装配所需的 sheet 和表头。

设计边界：
- 只产出 `blocking_error`，因为结构缺失意味着流水线无法继续。
- 行级校验（PO 是否存在、SAP 是否能解析、INV# 是否齐等）属于业务规则，
  依赖产品库和具体 PO，归 resolver 与后续模块处理。
- 无副作用、无网络、无文件写入，纯函数化（输入 reader，输出消息列表）。
"""

from __future__ import annotations

from typing import Final

from ro_generator.base_schema import base_schema
from ro_generator.models import ValidationMessage
from ro_generator.schema import (
    CUSTOMER_PO_REQUIRED_HEADERS,
    DATA_BASE_REQUIRED_HEADERS,
    PO_RECORD_REQUIRED_HEADERS,
    REQUIRED_SHEETS,
    SHEET_CUSTOMER_PO,
    SHEET_DATA_BASE,
    SHEET_PO_RECORD,
)
from ro_generator.workbook_reader import WorkbookReader

_schema = base_schema()

# 校验消息 code 是机器接口，禁止轻易改名。
CODE_SHEET_MISSING: Final = "SHEET_MISSING"
CODE_HEADER_MISSING: Final = "HEADER_MISSING"


def validate_workbook_structure(
    reader: WorkbookReader,
    *,
    skip_sheets: tuple[str, ...] = (),
) -> tuple[ValidationMessage, ...]:
    """校验 workbook 是否包含装配所需的 sheet 和表头。

    可通过 `skip_sheets` 跳过特定 sheet 的表头校验（如大表 DATA BASE 很慢）。
    """
    messages: list[ValidationMessage] = []

    # 1. 必需 sheet（sheet 存在性检查不走 skip，必须验）
    missing_sheets = tuple(s for s in REQUIRED_SHEETS if not reader.has_sheet(s))
    for sheet in missing_sheets:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_SHEET_MISSING,
                message=f"workbook 缺少必需 sheet：{sheet!r}",
                sheet=sheet,
            )
        )

    # 2. 已存在的 sheet 上校验必需表头
    if reader.has_sheet(SHEET_DATA_BASE) and SHEET_DATA_BASE not in skip_sheets:
        messages.extend(_check_headers(reader, SHEET_DATA_BASE, DATA_BASE_REQUIRED_HEADERS))
    if reader.has_sheet(SHEET_PO_RECORD) and SHEET_PO_RECORD not in skip_sheets:
        messages.extend(_check_headers(reader, SHEET_PO_RECORD, PO_RECORD_REQUIRED_HEADERS))
    if reader.has_sheet(SHEET_CUSTOMER_PO) and SHEET_CUSTOMER_PO not in skip_sheets:
        cp_cfg = _schema.sheet("客户PO")
        messages.extend(
            _check_headers(
                reader,
                SHEET_CUSTOMER_PO,
                CUSTOMER_PO_REQUIRED_HEADERS,
                header_row=cp_cfg.header_row,
            )
        )

    return tuple(messages)


def _check_headers(
    reader: WorkbookReader,
    sheet_name: str,
    required_headers: tuple[str, ...],
    header_row: int | None = None,
) -> list[ValidationMessage]:
    kwargs: dict[str, int] = {}
    if header_row is not None:
        kwargs["header_row"] = header_row
    sheet_headers = reader.read_headers(sheet_name, **kwargs)
    present = set(sheet_headers.header_columns)
    missing = [h for h in required_headers if h not in present]
    return [
        ValidationMessage(
            kind="blocking_error",
            code=CODE_HEADER_MISSING,
            message=f"sheet {sheet_name!r} 缺少必需表头：{header!r}",
            sheet=sheet_name,
            field=header,
        )
        for header in missing
    ]


__all__ = [
    "CODE_HEADER_MISSING",
    "CODE_SHEET_MISSING",
    "validate_workbook_structure",
]
