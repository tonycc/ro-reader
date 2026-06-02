"""异常类型测试：验证层次和稳定 code。"""

from __future__ import annotations

import pytest
from ro_generator.errors import (
    InternalError,
    InvalidRequestError,
    MappingError,
    RoGeneratorError,
    TemplateError,
    WorkbookOpenError,
)


class TestErrorHierarchy:
    @pytest.mark.parametrize(
        "exc_cls",
        [
            WorkbookOpenError,
            MappingError,
            TemplateError,
            InvalidRequestError,
            InternalError,
        ],
    )
    def test_all_errors_inherit_from_root(self, exc_cls: type[RoGeneratorError]) -> None:
        # 调用方应能用单个 except RoGeneratorError 兜底
        assert issubclass(exc_cls, RoGeneratorError)

    def test_root_inherits_from_exception(self) -> None:
        assert issubclass(RoGeneratorError, Exception)


class TestErrorCodes:
    """code 是机器识别的稳定接口，禁止轻易改名。"""

    @pytest.mark.parametrize(
        ("exc_cls", "expected_code"),
        [
            (RoGeneratorError, "RO_GENERATOR_ERROR"),
            (WorkbookOpenError, "WORKBOOK_OPEN_ERROR"),
            (MappingError, "MAPPING_ERROR"),
            (TemplateError, "TEMPLATE_ERROR"),
            (InvalidRequestError, "INVALID_REQUEST"),
            (InternalError, "INTERNAL_ERROR"),
        ],
    )
    def test_error_code(self, exc_cls: type[RoGeneratorError], expected_code: str) -> None:
        assert exc_cls.code == expected_code


class TestErrorInstantiation:
    def test_message_accessible(self) -> None:
        exc = MappingError("template_version 缺失")
        assert exc.message == "template_version 缺失"
        assert str(exc) == "template_version 缺失"

    def test_code_on_instance(self) -> None:
        exc = WorkbookOpenError("file not found")
        assert exc.code == "WORKBOOK_OPEN_ERROR"
