"""工作区 Session 生命周期和激活事务。

本模块只负责把 ``CustomerWorkspace`` 转换成不可变的
``GenerationContext``，构建候选快照并管理 session 临时目录。它不把业务校验复制到
API 层；base 文件的结构校验仍由 ``ro_generator.build_workbook_snapshot`` 完成。

激活分成两个边界清晰的阶段：候选 session 在内存中准备完成后，才持久化
``current_workspace_id``；持久化成功后才发布 active 指针。发布异常会恢复旧配置和旧
session，避免出现“配置指向新客户、内存仍在使用旧客户”的半切换状态。
"""

from __future__ import annotations

import errno
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ro_generator.errors import ProfileNotFoundError, WorkbookOpenError
from ro_generator.profiles import (
    GenerationContext,
    ProfileRegistry,
    default_profile_registry,
)
from ro_generator.workbook_snapshot import (
    BuildSnapshotError,
    WorkbookSnapshot,
    build_workbook_snapshot,
)

from ro_workbench_api.workspace_store import (
    CustomerWorkspace,
    WorkspaceStore,
    WorkspaceStoreError,
)

SESSION_TTL_SECONDS = 3600
DRAIN_GRACE_SECONDS = 300
SessionState = Literal["active", "draining"]
Clock = Callable[[], float]
TempDirFactory = Callable[[str], str]
SnapshotFactory = Callable[[GenerationContext], WorkbookSnapshot]

_ACTIVATION_LOCK = threading.RLock()


def _default_snapshot_factory(context: GenerationContext) -> WorkbookSnapshot:
    return build_workbook_snapshot(str(context.base_path), context=context)


class SessionManagerError(Exception):
    """SessionManager 根异常，``code`` 是稳定错误码。"""

    code = "SESSION_MANAGER_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SessionInactiveError(SessionManagerError):
    """session 不存在、已过期或不是当前可路由 session。"""

    code = "SESSION_INACTIVE"


class SessionSnapshotRefreshError(SessionManagerError):
    """工作区文件编辑后无法重建 managed session 快照。"""

    code = "SESSION_SNAPSHOT_REFRESH_FAILED"


class WorkspaceActivationError(SessionManagerError):
    """工作区无法完成激活。``code`` 区分文件、Profile 和 schema 原因。"""

    code = "WORKSPACE_ACTIVATION_FAILED"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class WorkspaceActivationInProgressError(SessionManagerError):
    """非阻塞激活请求发现已有激活事务。"""

    code = "WORKSPACE_ACTIVATION_IN_PROGRESS"


@dataclass
class SessionInfo:
    """一个 session 的可路由身份和临时文件生命周期。"""

    session_id: str
    workspace_id: str
    profile_id: str
    base_file: str
    temp_dir: str
    state: SessionState = "active"
    drain_until: float | None = None
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    context: GenerationContext = field(repr=False, default=None)  # type: ignore[assignment]
    snapshot: WorkbookSnapshot = field(repr=False, default=None)  # type: ignore[assignment]

    def touch(self, now: float) -> None:
        self.last_access = now


@dataclass(frozen=True)
class SessionActivation:
    """激活成功后返回的 session 和首屏快照。"""

    session: SessionInfo
    snapshot: WorkbookSnapshot
    workspace: CustomerWorkspace


class SessionManager:
    """串行提交工作区激活并管理 active/draining session。"""

    def __init__(
        self,
        store: WorkspaceStore,
        *,
        profile_registry: ProfileRegistry | None = None,
        snapshot_factory: SnapshotFactory | None = None,
        snapshot_builder: SnapshotFactory | None = None,
        clock: Clock = time.time,
        temp_dir_factory: TempDirFactory | None = None,
        session_ttl_seconds: float = SESSION_TTL_SECONDS,
        drain_grace_seconds: float = DRAIN_GRACE_SECONDS,
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds 必须大于 0")
        if drain_grace_seconds <= 0:
            raise ValueError("drain_grace_seconds 必须大于 0")
        if snapshot_factory is not None and snapshot_builder is not None:
            raise ValueError("snapshot_factory 与 snapshot_builder 只能设置一个")
        self._store = store
        self._profile_registry = (
            profile_registry or store.profile_registry or default_profile_registry()
        )
        self._snapshot_factory = snapshot_factory or snapshot_builder or _default_snapshot_factory
        self._clock = clock
        self._temp_dir_factory = temp_dir_factory or self._default_temp_dir
        self._session_ttl = session_ttl_seconds
        self._drain_grace = drain_grace_seconds
        self._sessions: dict[str, SessionInfo] = {}
        self._active_session_id: str | None = None
        self._lock = threading.RLock()

    @property
    def active_session_id(self) -> str | None:
        with self._lock:
            return self._active_session_id

    @property
    def session_ttl_seconds(self) -> float:
        return self._session_ttl

    @property
    def drain_grace_seconds(self) -> float:
        return self._drain_grace

    def active_session(self) -> SessionInfo | None:
        with self._lock:
            if self._active_session_id is None:
                return None
            return self._sessions.get(self._active_session_id)

    get_active_session = active_session

    def sessions(self) -> tuple[SessionInfo, ...]:
        with self._lock:
            return tuple(self._sessions.values())

    list_sessions = sessions

    def get_session(
        self,
        session_id: str,
        *,
        allow_draining: bool = False,
    ) -> SessionInfo:
        """取得可用于业务或下载的 session，并刷新活动时间。

        业务端点使用默认值，只接受 active session；下载端点传
        ``allow_draining=True``，允许旧 session 在宽限期内继续提供已生成文件。
        """

        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionInactiveError(f"session {session_id!r} 不存在或已过期")
            now = self._clock()
            if self._is_expired(session, now):
                self._remove_session_locked(session_id)
                raise SessionInactiveError(f"session {session_id!r} 已过期")
            if session.state == "draining" and not allow_draining:
                raise SessionInactiveError(f"session {session_id!r} 已进入 draining 状态")
            if session.state == "active" and session_id != self._active_session_id:
                raise SessionInactiveError(f"session {session_id!r} 不是当前 active session")
            session.touch(now)
            return session

    get = get_session

    def get_context(self, session_id: str, *, allow_draining: bool = False) -> GenerationContext:
        return self.get_session(session_id, allow_draining=allow_draining).context

    def refresh_snapshot(self, session_id: str) -> WorkbookSnapshot:
        """重建并替换 active session 的快照。"""
        with _ACTIVATION_LOCK:
            session = self.get_session(session_id)
            try:
                snapshot = self._snapshot_factory(session.context)
            except Exception as exc:
                if isinstance(exc, SessionManagerError):
                    raise
                raise SessionSnapshotRefreshError(
                    f"session {session_id!r} 快照刷新失败：{exc}"
                ) from exc

            with self._lock:
                current = self._sessions.get(session_id)
                if (
                    current is not session
                    or current.state != "active"
                    or session_id != self._active_session_id
                ):
                    raise SessionInactiveError(f"session {session_id!r} 不是当前 active session")
                current.snapshot = snapshot
                current.touch(self._clock())
            return snapshot

    refresh_session_snapshot = refresh_snapshot

    def close(self, session_id: str) -> bool:
        """关闭并删除一个 session 的临时目录，不修改持久化工作区。"""

        with _ACTIVATION_LOCK, self._lock:
            if session_id not in self._sessions:
                return False
            self._remove_session_locked(session_id)
            return True

    close_session = close

    def activate(self, workspace_id: str) -> SessionActivation:
        """执行一次阻塞式激活；并发调用按进入顺序串行提交。"""

        with _ACTIVATION_LOCK:
            return self._activate_locked(workspace_id)

    activate_workspace = activate
    switch = activate

    def try_activate(self, workspace_id: str) -> SessionActivation:
        """非阻塞激活入口，已有激活事务时返回稳定错误。"""

        if not _ACTIVATION_LOCK.acquire(blocking=False):
            raise WorkspaceActivationInProgressError("已有工作区激活事务正在进行")
        try:
            return self._activate_locked(workspace_id)
        finally:
            _ACTIVATION_LOCK.release()

    def restore_current(self) -> SessionActivation | None:
        """进程重启后按持久化 current_workspace_id 创建全新的 session。"""

        settings = self._store.load()
        if settings.current_workspace_id is None:
            return None
        return self.activate(settings.current_workspace_id)

    restore = restore_current

    def cleanup(self, *, now: float | None = None) -> tuple[str, ...]:
        """清理超过 TTL 的 session 和 draining 宽限期已结束的 session。"""

        current_time = self._clock() if now is None else now
        removed: list[str] = []
        with _ACTIVATION_LOCK, self._lock:
            expired_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if self._is_expired(session, current_time)
            ]
            for session_id in expired_ids:
                self._remove_session_locked(session_id)
                removed.append(session_id)
        return tuple(removed)

    cleanup_expired = cleanup

    def _activate_locked(self, workspace_id: str) -> SessionActivation:
        settings_before = self._store.load()
        workspace = self._get_workspace(workspace_id)
        candidate = self._prepare_candidate(workspace)

        with self._lock:
            old_active_id = self._active_session_id
            old_active = self._sessions.get(old_active_id) if old_active_id else None
            old_active_state = old_active.state if old_active is not None else None
            old_drain_until = old_active.drain_until if old_active is not None else None

        try:
            # 只有候选快照成功后才修改持久化 current 指针。
            self._store.set_current_workspace(workspace.id)
            self._publish_candidate(candidate, old_active_id=old_active_id)
        except Exception as exc:
            # set_current_workspace 可能已经成功，任何发布异常都恢复旧配置。
            with self._lock:
                self._restore_publication_locked(
                    candidate.session_id,
                    old_active_id=old_active_id,
                    old_active=old_active,
                    old_active_state=old_active_state,
                    old_drain_until=old_drain_until,
                )
            try:
                self._store.save(settings_before)
            except Exception as rollback_exc:
                self._discard_candidate(candidate)
                raise WorkspaceActivationError(
                    f"工作区激活失败且配置回滚失败：{rollback_exc}",
                    code="WORKSPACE_ACTIVATION_FAILED",
                ) from exc
            self._discard_candidate(candidate)
            if isinstance(exc, WorkspaceStoreError):
                raise
            if isinstance(exc, SessionManagerError):
                raise
            raise WorkspaceActivationError(f"工作区激活失败：{exc}") from exc

        # last_opened_at 是展示元数据，不参与 active 指针提交；失败不影响已发布 session。
        with suppress(Exception):
            self._store.mark_opened(workspace.id)
        # 配置的核心一致性已经提交，时间戳写失败不应让用户失去可用 session。
        return SessionActivation(
            session=candidate, snapshot=candidate.snapshot, workspace=workspace
        )

    def _get_workspace(self, workspace_id: str) -> CustomerWorkspace:
        try:
            workspace = self._store.get(workspace_id)
            self._profile_registry.get(workspace.profile_id)
        except ProfileNotFoundError as exc:
            raise WorkspaceActivationError(str(exc), code="PROFILE_NOT_FOUND") from exc
        return workspace

    def _prepare_candidate(self, workspace: CustomerWorkspace) -> SessionInfo:
        path = Path(workspace.base_file).expanduser().absolute()
        self._validate_base_path(path)
        temp_dir: str | None = None
        try:
            profile = self._profile_registry.get(workspace.profile_id)
            context = GenerationContext(profile=profile, base_file=path)
            temp_dir = self._temp_dir_factory(workspace.id)
            snapshot = self._snapshot_factory(context)
        except Exception as exc:
            if temp_dir is not None:
                _remove_temp_dir(temp_dir)
            if isinstance(exc, ProfileNotFoundError):
                raise WorkspaceActivationError(str(exc), code="PROFILE_NOT_FOUND") from exc
            if isinstance(exc, (PermissionError, OSError)):
                code = (
                    "WORKSPACE_FILE_PERMISSION_DENIED"
                    if _is_permission_error(exc)
                    else "WORKSPACE_FILE_MISSING"
                )
                raise WorkspaceActivationError(str(exc), code=code) from exc
            if isinstance(exc, (BuildSnapshotError, WorkbookOpenError)):
                raise WorkspaceActivationError(str(exc), code="WORKSPACE_SCHEMA_MISMATCH") from exc
            if isinstance(exc, WorkspaceActivationError):
                raise
            raise WorkspaceActivationError(str(exc), code="WORKSPACE_SCHEMA_MISMATCH") from exc

        session_id = uuid.uuid4().hex[:12]
        return SessionInfo(
            session_id=session_id,
            workspace_id=workspace.id,
            profile_id=profile.profile_id,
            base_file=str(path),
            temp_dir=temp_dir,
            context=context,
            snapshot=snapshot,
            created_at=self._clock(),
            last_access=self._clock(),
        )

    def _publish_candidate(self, candidate: SessionInfo, *, old_active_id: str | None) -> None:
        with self._lock:
            self._sessions[candidate.session_id] = candidate
            if old_active_id is not None:
                old_active = self._sessions.get(old_active_id)
                if old_active is not None:
                    old_active.state = "draining"
                    old_active.drain_until = self._clock() + self._drain_grace
            self._active_session_id = candidate.session_id

    def _restore_publication_locked(
        self,
        candidate_id: str,
        *,
        old_active_id: str | None,
        old_active: SessionInfo | None,
        old_active_state: SessionState | None,
        old_drain_until: float | None,
    ) -> None:
        self._sessions.pop(candidate_id, None)
        if old_active is not None and old_active_id is not None:
            old_active.state = old_active_state or "active"
            old_active.drain_until = old_drain_until
            self._sessions[old_active_id] = old_active
        self._active_session_id = old_active_id

    def _discard_candidate(self, candidate: SessionInfo) -> None:
        _remove_temp_dir(candidate.temp_dir)

    def _remove_session_locked(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        if session_id == self._active_session_id:
            self._active_session_id = None
        _remove_temp_dir(session.temp_dir)

    def _is_expired(self, session: SessionInfo, now: float) -> bool:
        if now - session.last_access > self._session_ttl:
            return True
        return (
            session.state == "draining"
            and session.drain_until is not None
            and now >= session.drain_until
        )

    @staticmethod
    def _default_temp_dir(workspace_id: str) -> str:
        safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in workspace_id)
        return tempfile.mkdtemp(prefix=f"ro-session-{safe_id[:24]}-")

    @staticmethod
    def _validate_base_path(path: Path) -> None:
        try:
            path.stat()
        except FileNotFoundError as exc:
            raise WorkspaceActivationError(
                f"base 文件不存在：{path}", code="WORKSPACE_FILE_MISSING"
            ) from exc
        except PermissionError as exc:
            raise WorkspaceActivationError(
                f"无权读取 base 文件：{path}", code="WORKSPACE_FILE_PERMISSION_DENIED"
            ) from exc
        if not path.is_file():
            raise WorkspaceActivationError(
                f"base 路径不是文件：{path}", code="WORKSPACE_FILE_MISSING"
            )
        try:
            with path.open("rb") as file:
                file.read(1)
        except PermissionError as exc:
            raise WorkspaceActivationError(
                f"无权读取 base 文件：{path}", code="WORKSPACE_FILE_PERMISSION_DENIED"
            ) from exc
        except FileNotFoundError as exc:
            raise WorkspaceActivationError(
                f"base 文件不存在：{path}", code="WORKSPACE_FILE_MISSING"
            ) from exc
        except OSError as exc:
            code = (
                "WORKSPACE_FILE_PERMISSION_DENIED"
                if _is_permission_error(exc)
                else "WORKSPACE_FILE_MISSING"
            )
            raise WorkspaceActivationError(str(exc), code=code) from exc


def _is_permission_error(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EPERM} or isinstance(error, PermissionError)


def _remove_temp_dir(path: str) -> None:
    with suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "DRAIN_GRACE_SECONDS",
    "SESSION_TTL_SECONDS",
    "SessionActivation",
    "SessionInactiveError",
    "SessionInfo",
    "SessionManager",
    "SessionManagerError",
    "SessionSnapshotRefreshError",
    "WorkspaceActivationError",
    "WorkspaceActivationInProgressError",
]
