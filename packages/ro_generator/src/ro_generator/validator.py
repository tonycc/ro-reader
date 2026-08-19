"""结构性校验：base workbook 是否有装配所需的 sheet 和表头。

设计边界：
- 只产出 `blocking_error`，因为结构缺失意味着流水线无法继续。
- 行级校验（PO 是否存在、SAP 是否能解析、INV# 是否齐等）属于业务规则，
  依赖产品库和具体 PO，归 resolver 与后续模块处理。
- 无副作用、无网络、无文件写入，纯函数化（输入 reader，输出消息列表）。

检测实现复用 `schema_inspect.inspect_schema`：本模块只做"把结构问题翻译成
blocking_error"的薄壳，唯一的检测事实源在 schema_inspect。sheet 缺失和
必需表头缺失会阻断；价格列缺失只提示（由工作台修复向导处理），不在此阻断。
"""

from __future__ import annotations

from typing import Final

from ro_generator.base_schema import BaseSchema, base_schema
from ro_generator.models import ValidationMessage
from ro_generator.schema_inspect import inspect_schema
from ro_generator.workbook_reader import WorkbookReader

# 校验消息 code 是机器接口，禁止轻易改名。
CODE_SHEET_MISSING: Final = "SHEET_MISSING"
CODE_HEADER_MISSING: Final = "HEADER_MISSING"


def validate_workbook_structure(
    reader: WorkbookReader,
    *,
    skip_sheets: tuple[str, ...] = (),
    schema: BaseSchema | None = None,
) -> tuple[ValidationMessage, ...]:
    """校验 workbook 是否包含装配所需的 sheet 和表头。

    可通过 `skip_sheets` 跳过特定 sheet 的表头校验（如大表 DATA BASE 很慢）。
    """

    active_schema = schema or getattr(reader, "schema", None) or base_schema()
    inspection = inspect_schema(reader, active_schema, skip_sheets=skip_sheets)

    messages: list[ValidationMessage] = [
        ValidationMessage(
            kind="blocking_error",
            code=CODE_SHEET_MISSING,
            message=f"workbook 缺少必需 sheet：{issue.actual_sheet!r}",
            sheet=issue.actual_sheet,
        )
        for issue in inspection.sheet_issues
    ]
    # field_issues 即必需表头缺失（schema_inspect 的逐列检测只覆盖必需表头）；
    # 价格列缺失不在此阻断，由工作台修复向导提示。
    messages.extend(
        ValidationMessage(
            kind="blocking_error",
            code=CODE_HEADER_MISSING,
            message=f"sheet {issue.actual_sheet!r} 缺少必需表头：{issue.expected_header!r}",
            sheet=issue.actual_sheet,
            field=issue.expected_header,
        )
        for issue in inspection.field_issues
    )
    return tuple(messages)


__all__ = [
    "CODE_HEADER_MISSING",
    "CODE_SHEET_MISSING",
    "validate_workbook_structure",
]
