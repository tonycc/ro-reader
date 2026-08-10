"""本地 Customer Workspace 配置存储。

``WorkspaceStore`` 只管理工作区配置，不读取 workbook，也不执行 Profile 业务规则。
它是后续 ``SessionManager`` 和 Workspace API 的持久化边界：所有写入都通过临时文件
完成 ``flush + fsync + os.replace``，因此一次失败不会覆盖最后一份有效配置。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir
from ro_generator.errors import ProfileNotFoundError
from ro_generator.profiles import ProfileRegistry, default_profile_registry

WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_CONFIG_ENV = "RO_WORKBENCH_CONFIG_DIR"
WORKSPACE_CONFIG_FILENAME = "workspaces.json"
_WORKSPACE_CONFIG_LOCK = threading.RLock()


class WorkspaceStoreError(Exception):
    """WorkspaceStore 根异常，``code`` 是对 API 暴露的稳定错误码。"""

    code = "WORKSPACE_STORE_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class WorkspaceConfigInvalidError(WorkspaceStoreError):
    """配置文件不存在以外的解析、结构或版本错误。"""

    code = "WORKSPACE_CONFIG_INVALID"


class WorkspaceConfigReadError(WorkspaceStoreError):
    """配置文件存在但无法读取。"""

    code = "WORKSPACE_CONFIG_READ_FAILED"


class WorkspaceConfigWriteError(WorkspaceStoreError):
    """配置无法原子写入。"""

    code = "WORKSPACE_CONFIG_WRITE_FAILED"


class WorkspaceNotFoundError(WorkspaceStoreError):
    """请求的工作区不存在。"""

    code = "WORKSPACE_NOT_FOUND"


class WorkspaceValidationError(WorkspaceStoreError):
    """工作区字段不满足持久化契约。"""

    code = "WORKSPACE_INVALID"


class WorkspaceIdConflictError(WorkspaceStoreError):
    """工作区 ID 已被占用。"""

    code = "WORKSPACE_ID_CONFLICT"


class CurrentWorkspaceDeleteError(WorkspaceStoreError):
    """当前工作区不能直接删除。"""

    code = "WORKSPACE_CURRENT_DELETE_FORBIDDEN"


@dataclass(frozen=True, slots=True)
class CustomerWorkspace:
    """用户配置的 Profile + base 文件组合。"""

    id: str
    display_name: str
    profile_id: str
    base_file: str
    created_at: str
    updated_at: str
    last_opened_at: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSettings:
    """版本化的工作区配置文档。"""

    schema_version: int
    current_workspace_id: str | None
    workspaces: tuple[CustomerWorkspace, ...]


Clock = Callable[[], str]


def _now_iso() -> str:
    """返回带时区的可序列化时间戳。"""

    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _as_nonempty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceValidationError(f"{field_name} 不能为空")
    return value.strip()


def _normalise_base_file(value: object) -> str:
    if isinstance(value, (Path, os.PathLike)):
        raw = _as_nonempty_string(os.fspath(value), field_name="base_file")
    else:
        raw = _as_nonempty_string(value, field_name="base_file")
    # ``absolute`` 不解析符号链接，也不会把 macOS 的 /tmp 改写成 /private/tmp；
    # 配置只需要稳定的绝对路径身份，实际文件校验留给核心包/SessionManager。
    return str(Path(raw).expanduser().absolute())


class WorkspaceStore:
    """以原子 JSON 文件保存 Customer Workspace 配置。

    默认文件位于 ``platformdirs.user_config_dir("RO Workbench")``。测试、便携版和
    启动器可通过 ``RO_WORKBENCH_CONFIG_DIR`` 或构造函数 ``config_dir`` 注入隔离目录。
    ``profile_registry`` 只用于检查 Profile ID 是否已注册；store 不会读取 base 文件。
    """

    def __init__(
        self,
        *,
        config_dir: str | Path | None = None,
        profile_registry: ProfileRegistry | None = None,
        filename: str = WORKSPACE_CONFIG_FILENAME,
        clock: Clock = _now_iso,
    ) -> None:
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Workspace 配置文件名不能为空")
        if Path(filename).name != filename:
            raise ValueError("Workspace 配置文件名必须是单一文件名")
        if not callable(clock):
            raise TypeError("clock 必须可调用")

        configured_dir = config_dir
        if configured_dir is None:
            configured_dir = os.environ.get(WORKSPACE_CONFIG_ENV)
        if configured_dir is None:
            configured_dir = user_config_dir("RO Workbench", appauthor=False)

        self._config_dir = Path(configured_dir).expanduser().absolute()
        self._config_path = self._config_dir / filename
        self._profile_registry = profile_registry or default_profile_registry()
        self._clock = clock
        # 同一进程可能有多个服务对象指向同一个配置文件，锁必须跨实例共享。
        self._lock = _WORKSPACE_CONFIG_LOCK

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def profile_registry(self) -> ProfileRegistry:
        return self._profile_registry

    def load(self) -> WorkspaceSettings:
        """读取当前配置；首次启动没有文件时返回空配置。"""

        with self._lock:
            return self._read_locked()

    # ``get_settings`` 是给调用方的语义化别名，避免 API 层依赖文件名细节。
    get_settings = load

    def save(self, settings: WorkspaceSettings) -> WorkspaceSettings:
        """校验并原子保存配置，成功后返回同一份不可变对象。"""

        with self._lock:
            normalised = self._validate_settings(settings)
            self._write_locked(normalised)
            return normalised

    def list_workspaces(self) -> tuple[CustomerWorkspace, ...]:
        return self.load().workspaces

    def list(self) -> tuple[CustomerWorkspace, ...]:
        """兼容简短调用名。"""

        return self.list_workspaces()

    def get(self, workspace_id: str) -> CustomerWorkspace:
        settings = self.load()
        return self._find(settings, workspace_id)

    def get_current(self) -> CustomerWorkspace | None:
        settings = self.load()
        if settings.current_workspace_id is None:
            return None
        return self._find(settings, settings.current_workspace_id)

    get_current_workspace = get_current

    def create(
        self,
        *,
        display_name: str,
        profile_id: str,
        base_file: str | Path,
        workspace_id: str | None = None,
    ) -> CustomerWorkspace:
        """创建工作区并持久化；ID 默认由后端随机生成。"""

        with self._lock:
            settings = self._read_locked()
            normalized_id = self._normalise_workspace_id(workspace_id or self._new_id())
            if any(item.id == normalized_id for item in settings.workspaces):
                raise WorkspaceIdConflictError(f"工作区 ID 已存在：{normalized_id}")
            workspace = self._new_workspace(
                workspace_id=normalized_id,
                display_name=display_name,
                profile_id=profile_id,
                base_file=base_file,
            )
            updated = WorkspaceSettings(
                schema_version=WORKSPACE_SCHEMA_VERSION,
                current_workspace_id=settings.current_workspace_id,
                workspaces=(*settings.workspaces, workspace),
            )
            self._write_locked(updated)
            return workspace

    def update(
        self,
        workspace_id: str,
        *,
        display_name: str | None = None,
        profile_id: str | None = None,
        base_file: str | Path | None = None,
    ) -> CustomerWorkspace:
        """更新工作区配置，保持稳定 ID 和创建时间。"""

        with self._lock:
            settings = self._read_locked()
            current = self._find(settings, workspace_id)
            next_name = (
                current.display_name if display_name is None else self._normalise_name(display_name)
            )
            next_profile = (
                current.profile_id if profile_id is None else self._normalise_profile_id(profile_id)
            )
            next_base = current.base_file if base_file is None else _normalise_base_file(base_file)
            updated_workspace = CustomerWorkspace(
                id=current.id,
                display_name=next_name,
                profile_id=next_profile,
                base_file=next_base,
                created_at=current.created_at,
                updated_at=self._clock(),
                last_opened_at=current.last_opened_at,
            )
            workspaces = tuple(
                updated_workspace if item.id == current.id else item for item in settings.workspaces
            )
            self._write_locked(
                WorkspaceSettings(
                    schema_version=WORKSPACE_SCHEMA_VERSION,
                    current_workspace_id=settings.current_workspace_id,
                    workspaces=workspaces,
                )
            )
            return updated_workspace

    def delete(self, workspace_id: str) -> None:
        """删除配置，不删除用户的 base 文件。"""

        with self._lock:
            settings = self._read_locked()
            normalized_id = self._normalise_workspace_id(workspace_id)
            self._find(settings, normalized_id)
            if settings.current_workspace_id == normalized_id:
                raise CurrentWorkspaceDeleteError("当前工作区不能直接删除，请先切换到其他工作区")
            workspaces = tuple(item for item in settings.workspaces if item.id != normalized_id)
            self._write_locked(
                WorkspaceSettings(
                    schema_version=WORKSPACE_SCHEMA_VERSION,
                    current_workspace_id=settings.current_workspace_id,
                    workspaces=workspaces,
                )
            )

    def set_current_workspace(self, workspace_id: str | None) -> WorkspaceSettings:
        """更新当前工作区指针；传 ``None`` 可清空指针。"""

        with self._lock:
            settings = self._read_locked()
            normalized_id: str | None = None
            if workspace_id is not None:
                normalized_id = self._normalise_workspace_id(workspace_id)
                self._find(settings, normalized_id)
            updated = WorkspaceSettings(
                schema_version=WORKSPACE_SCHEMA_VERSION,
                current_workspace_id=normalized_id,
                workspaces=settings.workspaces,
            )
            self._write_locked(updated)
            return updated

    def clear_current_workspace(self) -> WorkspaceSettings:
        return self.set_current_workspace(None)

    def mark_opened(self, workspace_id: str, *, opened_at: str | None = None) -> CustomerWorkspace:
        """记录成功打开时间；不改变当前指针，事务提交由 SessionManager 负责。"""

        with self._lock:
            settings = self._read_locked()
            current = self._find(settings, workspace_id)
            timestamp = opened_at or self._clock()
            if not isinstance(timestamp, str) or not timestamp.strip():
                raise WorkspaceValidationError("last_opened_at 不能为空")
            updated_workspace = CustomerWorkspace(
                id=current.id,
                display_name=current.display_name,
                profile_id=current.profile_id,
                base_file=current.base_file,
                created_at=current.created_at,
                updated_at=self._clock(),
                last_opened_at=timestamp.strip(),
            )
            workspaces = tuple(
                updated_workspace if item.id == current.id else item for item in settings.workspaces
            )
            self._write_locked(
                WorkspaceSettings(
                    schema_version=WORKSPACE_SCHEMA_VERSION,
                    current_workspace_id=settings.current_workspace_id,
                    workspaces=workspaces,
                )
            )
            return updated_workspace

    @classmethod
    def migrate_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        """将旧配置 payload 迁移到当前版本，不写入文件。

        v0 没有 ``schema_version`` 时，只接受已经符合 v1 字段形状的配置并补上版本号；
        这样可以安全接入早期实验版，同时不会猜测字段含义。未来版本在这里按版本递进。
        """

        if not isinstance(payload, Mapping):
            raise WorkspaceConfigInvalidError("Workspace 配置根节点必须是 JSON object")
        raw_version = payload.get("schema_version", 0)
        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            raise WorkspaceConfigInvalidError("schema_version 必须是整数")
        if raw_version > WORKSPACE_SCHEMA_VERSION:
            raise WorkspaceConfigInvalidError(
                f"不支持的 Workspace 配置版本：{raw_version}（当前为 {WORKSPACE_SCHEMA_VERSION}）"
            )
        if raw_version < 0:
            raise WorkspaceConfigInvalidError(f"非法 Workspace 配置版本：{raw_version}")

        migrated = dict(payload)
        if raw_version == 0:
            migrated["schema_version"] = WORKSPACE_SCHEMA_VERSION
        return migrated

    def _read_locked(self) -> WorkspaceSettings:
        if not self._config_path.exists():
            return WorkspaceSettings(
                schema_version=WORKSPACE_SCHEMA_VERSION,
                current_workspace_id=None,
                workspaces=(),
            )
        try:
            raw = self._config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceConfigReadError(f"无法读取 Workspace 配置：{self._config_path}") from exc
        try:
            payload = json.loads(raw)
            migrated = self.migrate_payload(payload)
            return self._validate_settings(self._settings_from_payload(migrated))
        except WorkspaceStoreError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkspaceConfigInvalidError(
                f"Workspace 配置无法解析：{self._config_path}"
            ) from exc

    def _write_locked(self, settings: WorkspaceSettings) -> None:
        payload = self._settings_to_payload(self._validate_settings(settings))
        temporary_path: Path | None = None
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self._config_path.name}.",
                suffix=".tmp",
                dir=self._config_dir,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self._config_path)
            temporary_path = None
            self._fsync_directory()
        except (OSError, TypeError, ValueError) as exc:
            raise WorkspaceConfigWriteError(
                f"无法写入 Workspace 配置：{self._config_path}"
            ) from exc
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    def _fsync_directory(self) -> None:
        """尽力持久化目录项；Windows 或测试文件系统不支持时不影响替换结果。"""

        open_directory = getattr(os, "O_DIRECTORY", 0)
        try:
            directory_fd = os.open(self._config_dir, os.O_RDONLY | open_directory)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)

    def _new_workspace(
        self,
        *,
        workspace_id: str,
        display_name: str,
        profile_id: str,
        base_file: str | Path,
    ) -> CustomerWorkspace:
        timestamp = self._clock()
        normalized_name = self._normalise_name(display_name)
        normalized_profile = self._normalise_profile_id(profile_id)
        normalized_base = _normalise_base_file(base_file)
        return CustomerWorkspace(
            id=workspace_id,
            display_name=normalized_name,
            profile_id=normalized_profile,
            base_file=normalized_base,
            created_at=timestamp,
            updated_at=timestamp,
            last_opened_at=None,
        )

    def _normalise_name(self, value: object) -> str:
        return _as_nonempty_string(value, field_name="display_name")

    def _normalise_profile_id(self, value: object) -> str:
        profile_id = _as_nonempty_string(value, field_name="profile_id")
        if profile_id != str(value).strip():
            raise WorkspaceValidationError("profile_id 不能包含首尾空格")
        try:
            self._profile_registry.get(profile_id)
        except ProfileNotFoundError as exc:
            raise ProfileNotFoundError(f"未知 Customer Profile：{profile_id}") from exc
        return profile_id

    @staticmethod
    def _normalise_workspace_id(value: object) -> str:
        workspace_id = _as_nonempty_string(value, field_name="workspace_id")
        if workspace_id != str(value).strip() or any(char.isspace() for char in workspace_id):
            raise WorkspaceValidationError("workspace_id 不能包含空白字符")
        return workspace_id

    @staticmethod
    def _new_id() -> str:
        return f"workspace-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _find(settings: WorkspaceSettings, workspace_id: str) -> CustomerWorkspace:
        normalized_id = WorkspaceStore._normalise_workspace_id(workspace_id)
        for workspace in settings.workspaces:
            if workspace.id == normalized_id:
                return workspace
        raise WorkspaceNotFoundError(f"工作区不存在：{normalized_id}")

    def _validate_settings(self, settings: WorkspaceSettings) -> WorkspaceSettings:
        if not isinstance(settings, WorkspaceSettings):
            raise WorkspaceValidationError("settings 必须是 WorkspaceSettings")
        if settings.schema_version != WORKSPACE_SCHEMA_VERSION:
            raise WorkspaceConfigInvalidError(
                f"不支持的 Workspace 配置版本：{settings.schema_version}"
            )
        workspaces: list[CustomerWorkspace] = []
        ids: set[str] = set()
        for workspace in settings.workspaces:
            if not isinstance(workspace, CustomerWorkspace):
                raise WorkspaceValidationError("workspaces 只能包含 CustomerWorkspace")
            normalized_id = self._normalise_workspace_id(workspace.id)
            if normalized_id in ids:
                raise WorkspaceIdConflictError(f"工作区 ID 重复：{normalized_id}")
            ids.add(normalized_id)
            normalized_name = self._normalise_name(workspace.display_name)
            normalized_profile = self._normalise_profile_id(workspace.profile_id)
            normalized_base = _normalise_base_file(workspace.base_file)
            if not isinstance(workspace.created_at, str) or not workspace.created_at.strip():
                raise WorkspaceValidationError(f"工作区 {normalized_id} 缺少 created_at")
            if not isinstance(workspace.updated_at, str) or not workspace.updated_at.strip():
                raise WorkspaceValidationError(f"工作区 {normalized_id} 缺少 updated_at")
            if workspace.last_opened_at is not None and (
                not isinstance(workspace.last_opened_at, str)
                or not workspace.last_opened_at.strip()
            ):
                raise WorkspaceValidationError(f"工作区 {normalized_id} 的 last_opened_at 非法")
            workspaces.append(
                CustomerWorkspace(
                    id=normalized_id,
                    display_name=normalized_name,
                    profile_id=normalized_profile,
                    base_file=normalized_base,
                    created_at=workspace.created_at.strip(),
                    updated_at=workspace.updated_at.strip(),
                    last_opened_at=(
                        workspace.last_opened_at.strip()
                        if workspace.last_opened_at is not None
                        else None
                    ),
                )
            )
        current_id = settings.current_workspace_id
        if current_id is not None:
            current_id = self._normalise_workspace_id(current_id)
            if current_id not in ids:
                raise WorkspaceConfigInvalidError(f"current_workspace_id 不存在：{current_id}")
        return WorkspaceSettings(
            schema_version=WORKSPACE_SCHEMA_VERSION,
            current_workspace_id=current_id,
            workspaces=tuple(workspaces),
        )

    @classmethod
    def _settings_from_payload(cls, payload: Mapping[str, Any]) -> WorkspaceSettings:
        version = payload.get("schema_version")
        if version != WORKSPACE_SCHEMA_VERSION:
            raise WorkspaceConfigInvalidError(f"不支持的 Workspace 配置版本：{version}")
        current_id = payload.get("current_workspace_id")
        if current_id is not None and not isinstance(current_id, str):
            raise WorkspaceConfigInvalidError("current_workspace_id 必须是字符串或 null")
        raw_workspaces = payload.get("workspaces", [])
        if not isinstance(raw_workspaces, list):
            raise WorkspaceConfigInvalidError("workspaces 必须是数组")
        workspaces: list[CustomerWorkspace] = []
        for index, raw in enumerate(raw_workspaces):
            if not isinstance(raw, Mapping):
                raise WorkspaceConfigInvalidError(f"workspaces[{index}] 必须是 object")
            try:
                workspaces.append(
                    CustomerWorkspace(
                        id=raw["id"],
                        display_name=raw["display_name"],
                        profile_id=raw["profile_id"],
                        base_file=raw["base_file"],
                        created_at=raw["created_at"],
                        updated_at=raw["updated_at"],
                        last_opened_at=raw.get("last_opened_at"),
                    )
                )
            except KeyError as exc:
                raise WorkspaceConfigInvalidError(
                    f"workspaces[{index}] 缺少字段：{exc.args[0]}"
                ) from exc
            except TypeError as exc:
                raise WorkspaceConfigInvalidError(f"workspaces[{index}] 字段类型非法") from exc
        return WorkspaceSettings(
            schema_version=WORKSPACE_SCHEMA_VERSION,
            current_workspace_id=current_id,
            workspaces=tuple(workspaces),
        )

    @staticmethod
    def _settings_to_payload(settings: WorkspaceSettings) -> dict[str, Any]:
        return {
            "schema_version": settings.schema_version,
            "current_workspace_id": settings.current_workspace_id,
            "workspaces": [
                {
                    "id": workspace.id,
                    "display_name": workspace.display_name,
                    "profile_id": workspace.profile_id,
                    "base_file": workspace.base_file,
                    "created_at": workspace.created_at,
                    "updated_at": workspace.updated_at,
                    "last_opened_at": workspace.last_opened_at,
                }
                for workspace in settings.workspaces
            ],
        }


__all__ = [
    "WORKSPACE_CONFIG_ENV",
    "WORKSPACE_CONFIG_FILENAME",
    "WORKSPACE_SCHEMA_VERSION",
    "CurrentWorkspaceDeleteError",
    "CustomerWorkspace",
    "WorkspaceConfigInvalidError",
    "WorkspaceConfigReadError",
    "WorkspaceConfigWriteError",
    "WorkspaceIdConflictError",
    "WorkspaceNotFoundError",
    "WorkspaceSettings",
    "WorkspaceStore",
    "WorkspaceStoreError",
    "WorkspaceValidationError",
]
