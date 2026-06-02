"""RO 单据装配核心包。业务规则唯一源。"""

from __future__ import annotations

from ro_generator.errors import (
    InternalError,
    InvalidRequestError,
    MappingError,
    RoGeneratorError,
    TemplateError,
    WorkbookOpenError,
)
from ro_generator.models import (
    DocumentRequest,
    DocumentType,
    GenerationResult,
    OrderLine,
    Product,
    ResultStatus,
    ValidationKind,
    ValidationMessage,
    WarningSeverity,
)

__version__ = "0.0.0"

__all__ = [
    "DocumentRequest",
    "DocumentType",
    "GenerationResult",
    "InternalError",
    "InvalidRequestError",
    "MappingError",
    "OrderLine",
    "Product",
    "ResultStatus",
    "RoGeneratorError",
    "TemplateError",
    "ValidationKind",
    "ValidationMessage",
    "WarningSeverity",
    "WorkbookOpenError",
    "__version__",
]
