"""RO 单据装配核心包。业务规则唯一源。"""

from __future__ import annotations

from ro_generator.errors import (
    DuplicateProfileError,
    InternalError,
    InvalidProfileError,
    InvalidRequestError,
    MappingError,
    ProfileError,
    ProfileNotFoundError,
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
from ro_generator.profiles import (
    CustomerProfile,
    CustomerRules,
    GenerationContext,
    ProfileAssets,
    ProfileCapabilities,
    ProfileRegistry,
    create_pf_profile,
    create_ro_profile,
    current_profile,
    current_rules,
    current_schema,
    default_profile_registry,
    profile_scope,
)
from ro_generator.workbench_service import (
    WorkbookInspectionResult,
    inspect_workbook,
)
from ro_generator.workbook_editor import EditResult, edit_workbook_cell
from ro_generator.workbook_snapshot import PoInspection

__version__ = "1.1.0"

__all__ = [
    "CustomerProfile",
    "CustomerRules",
    "DocumentRequest",
    "DocumentType",
    "DuplicateProfileError",
    "EditResult",
    "GenerationContext",
    "GenerationResult",
    "InternalError",
    "InvalidProfileError",
    "InvalidRequestError",
    "MappingError",
    "OrderLine",
    "PoInspection",
    "Product",
    "ProfileAssets",
    "ProfileCapabilities",
    "ProfileError",
    "ProfileNotFoundError",
    "ProfileRegistry",
    "ResultStatus",
    "RoGeneratorError",
    "TemplateError",
    "ValidationKind",
    "ValidationMessage",
    "WarningSeverity",
    "WorkbookInspectionResult",
    "WorkbookOpenError",
    "__version__",
    "create_pf_profile",
    "create_ro_profile",
    "current_profile",
    "current_rules",
    "current_schema",
    "default_profile_registry",
    "edit_workbook_cell",
    "inspect_workbook",
    "profile_scope",
]
