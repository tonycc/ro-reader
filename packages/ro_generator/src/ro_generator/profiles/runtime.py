"""运行时 Profile 作用域。

核心函数优先接收显式 ``GenerationContext``；在尚未完成参数升级的兼容
入口中，由本模块提供一个请求级、线程/协程隔离的 Profile 作用域。它不是
“当前客户”单例：作用域只在一次调用链内有效，离开后立即恢复原值。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from ro_generator.base_schema import BaseSchema, base_schema
from ro_generator.profiles.base import CustomerProfile, CustomerRules

_ACTIVE_PROFILE: ContextVar[CustomerProfile | None] = ContextVar(
    "ro_generator_active_profile", default=None
)


@contextmanager
def profile_scope(profile: CustomerProfile) -> Iterator[None]:
    """在当前执行链绑定 Profile，退出时恢复上层作用域。"""

    token = _ACTIVE_PROFILE.set(profile)
    try:
        yield
    finally:
        _ACTIVE_PROFILE.reset(token)


def current_profile() -> CustomerProfile | None:
    """返回当前执行链的 Profile；未绑定时返回 ``None``。"""

    return _ACTIVE_PROFILE.get()


def current_schema(schema: BaseSchema | None = None) -> BaseSchema:
    """解析当前调用应使用的 schema，兼容旧入口的默认 RO。"""

    if schema is not None:
        return schema
    profile = current_profile()
    return profile.schema if profile is not None else base_schema()


def current_rules(rules: CustomerRules | None = None) -> CustomerRules:
    """解析当前调用应使用的规则，兼容旧入口的默认 RO。"""

    if rules is not None:
        return rules
    profile = current_profile()
    if profile is not None:
        return profile.rules

    # 只在旧的无 context 入口使用；导入延迟以避免 profiles.ro 循环导入。
    from ro_generator.profiles.ro import RoRules

    return RoRules()


def current_source_location(
    source_sheet: str | None,
    source_field: str | None,
) -> tuple[str | None, str | None]:
    """把 RO 兼容规则中的来源位置转换为当前 Profile 的真实 sheet/表头。"""

    if source_sheet is None:
        return None, source_field
    active = current_schema()
    default = base_schema()
    logical_sheet = default.logical_sheet_name(source_sheet) or active.logical_sheet_name(
        source_sheet
    )
    if logical_sheet is None:
        return source_sheet, source_field
    translated_field = source_field
    if source_field is not None:
        internal_key = default.internal_field_key(
            logical_sheet, source_field
        ) or active.internal_field_key(logical_sheet, source_field)
        if internal_key is not None:
            translated_field = active.field(logical_sheet, internal_key)
    return active.sheet(logical_sheet).name, translated_field


__all__ = [
    "current_profile",
    "current_rules",
    "current_schema",
    "current_source_location",
    "profile_scope",
]
