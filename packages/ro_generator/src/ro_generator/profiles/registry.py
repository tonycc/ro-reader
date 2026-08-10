"""Customer Profile 注册表。"""

from __future__ import annotations

from collections.abc import Iterable

from ro_generator.errors import DuplicateProfileError, InvalidProfileError, ProfileNotFoundError
from ro_generator.profiles.base import CustomerProfile
from ro_generator.profiles.pf import create_pf_profile
from ro_generator.profiles.ro import create_ro_profile


class ProfileRegistry:
    """按稳定 ``profile_id`` 管理不可变 Profile。"""

    def __init__(
        self,
        profiles: Iterable[CustomerProfile],
        *,
        default_profile_id: str = "ro",
    ) -> None:
        profile_map: dict[str, CustomerProfile] = {}
        for profile in profiles:
            if not isinstance(profile, CustomerProfile):
                raise InvalidProfileError("注册表只接受 CustomerProfile 实例")
            if profile.profile_id in profile_map:
                raise DuplicateProfileError(f"Profile ID 已注册：{profile.profile_id}")
            profile_map[profile.profile_id] = profile
        if not profile_map:
            raise InvalidProfileError("Profile 注册表不能为空")
        if default_profile_id not in profile_map:
            raise InvalidProfileError(f"默认 Profile 不存在：{default_profile_id}")
        self._profiles = profile_map
        self._default_profile_id = default_profile_id

    @property
    def default_profile_id(self) -> str:
        return self._default_profile_id

    @property
    def default(self) -> CustomerProfile:
        return self._profiles[self._default_profile_id]

    def get(self, profile_id: str) -> CustomerProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ProfileNotFoundError(f"未知 Customer Profile：{profile_id}") from exc

    def list(self) -> tuple[CustomerProfile, ...]:
        return tuple(self._profiles.values())


def default_profile_registry() -> ProfileRegistry:
    """返回包含 RO 与 PF、并以 RO 为默认值的注册表。"""

    return ProfileRegistry((create_ro_profile(), create_pf_profile()), default_profile_id="ro")
