"""核心包领域异常与错误码。

设计原则：
- 业务规则违反（缺字段、数据格式错）通过 `ValidationMessage` 在结果中返回，不抛异常。
- 真正的异常仅用于：调用方使用错误（如传非法参数）、运行时环境问题（如文件不可读）、
  以及核心包内部的不变量违反（说明代码 bug）。
- 异常都有稳定的 `code`，方便调用方分类处理。
"""

from __future__ import annotations


class RoGeneratorError(Exception):
    """核心包根异常。所有领域异常继承自此。"""

    code: str = "RO_GENERATOR_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class WorkbookOpenError(RoGeneratorError):
    """无法打开 base workbook（文件不存在、损坏、不是有效 xlsx）。"""

    code = "WORKBOOK_OPEN_ERROR"


class MappingError(RoGeneratorError):
    """模板 mapping 文件加载或校验失败。

    场景：YAML 解析失败、必需字段缺失、引用的单元格在模板中不存在、template_version 缺失等。
    """

    code = "MAPPING_ERROR"


class TemplateError(RoGeneratorError):
    """模板文件本身有问题（不存在、不是 .xlsx、被损坏）。"""

    code = "TEMPLATE_ERROR"


class InvalidRequestError(RoGeneratorError):
    """`DocumentRequest` 参数非法。

    场景：未知的链段组合、未知的单据类型、`invoice_month` 格式错等。
    这是调用方使用错误，不是数据问题。
    """

    code = "INVALID_REQUEST"


class InternalError(RoGeneratorError):
    """核心包内部不变量违反，表明代码 bug。不应该在生产中触发。"""

    code = "INTERNAL_ERROR"
