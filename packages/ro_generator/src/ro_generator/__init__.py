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
from ro_generator.workbench_service import (
    WorkbookInspectionResult,
    inspect_workbook,
)
from ro_generator.workbook_editor import EditResult, edit_workbook_cell
from ro_generator.workbook_snapshot import PoInspection

__version__ = "0.0.0"

__all__ = [
    "DocumentRequest",
    "DocumentType",
    "EditResult",
    "GenerationResult",
    "InternalError",
    "InvalidRequestError",
    "MappingError",
    "OrderLine",
    "PoInspection",
    "Product",
    "ResultStatus",
    "RoGeneratorError",
    "TemplateError",
    "ValidationKind",
    "ValidationMessage",
    "WarningSeverity",
    "WorkbookInspectionResult",
    "WorkbookOpenError",
    "__version__",
    "edit_workbook_cell",
    "inspect_workbook",
]
