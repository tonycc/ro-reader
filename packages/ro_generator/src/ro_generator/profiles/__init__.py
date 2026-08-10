"""Customer Profile 领域模型和注册表。

Profile 是核心业务上下文的身份边界。Phase 5.1 先提供模型和 RO 默认注册，
后续阶段再把 resolver、schema、mapping 和缓存逐步接入 ``GenerationContext``。
"""

from ro_generator.profiles.base import (
    CustomerProfile,
    CustomerRules,
    GenerationContext,
    ProfileAssets,
    ProfileCapabilities,
)
from ro_generator.profiles.pf import create_pf_profile
from ro_generator.profiles.registry import ProfileRegistry, default_profile_registry
from ro_generator.profiles.ro import create_ro_profile
from ro_generator.profiles.runtime import (
    current_profile,
    current_rules,
    current_schema,
    profile_scope,
)

__all__ = [
    "CustomerProfile",
    "CustomerRules",
    "GenerationContext",
    "ProfileAssets",
    "ProfileCapabilities",
    "ProfileRegistry",
    "create_pf_profile",
    "create_ro_profile",
    "current_profile",
    "current_rules",
    "current_schema",
    "default_profile_registry",
    "profile_scope",
]
