"""SessionManager 激活事务、回滚和生命周期测试。"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from ro_generator.profiles import ProfileRegistry, create_ro_profile
from ro_generator.profiles.ro import RoRules
from ro_generator.workbook_snapshot import BuildSnapshotError, WorkbookSnapshot
from ro_workbench_api.session_manager import (
    SessionInactiveError,
    SessionManager,
    WorkspaceActivationError,
    WorkspaceActivationInProgressError,
)
from ro_workbench_api.workspace_store import (
    CustomerWorkspace,
    WorkspaceNotFoundError,
    WorkspaceStore,
)


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _snapshot(context: object) -> WorkbookSnapshot:
    del context
    return WorkbookSnapshot(
        base_file="fake.xlsx",
        headers_data_base=(),
        headers_po_record=(),
    )


def _store(tmp_path: Path, *names: str) -> tuple[WorkspaceStore, dict[str, CustomerWorkspace]]:
    base_files: dict[str, CustomerWorkspace] = {}
    store = WorkspaceStore(
        config_dir=tmp_path / "config", clock=lambda: "2026-08-07T10:00:00+08:00"
    )
    for name in names:
        path = tmp_path / f"{name}.xlsx"
        path.write_bytes(b"placeholder")
        base_files[name] = store.create(
            display_name=name,
            profile_id="ro",
            base_file=path,
        )
    return store, base_files


def test_activate_persists_current_workspace_and_binds_context(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "RO 2026")
    captured: list[object] = []

    def build(context: object) -> WorkbookSnapshot:
        captured.append(context)
        return _snapshot(context)

    manager = SessionManager(store, snapshot_factory=build)
    result = manager.activate(workspaces["RO 2026"].id)

    assert store.load().current_workspace_id == result.workspace.id
    assert manager.active_session_id == result.session.session_id
    assert result.session.state == "active"
    assert result.session.workspace_id == result.workspace.id
    assert result.session.profile_id == "ro"
    assert result.session.context.profile_id == "ro"
    assert captured


def test_refresh_snapshot_replaces_active_session_snapshot(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "RO 2026")
    snapshots = iter(
        (
            WorkbookSnapshot(base_file="before.xlsx", headers_data_base=(), headers_po_record=()),
            WorkbookSnapshot(base_file="after.xlsx", headers_data_base=(), headers_po_record=()),
        )
    )

    manager = SessionManager(store, snapshot_factory=lambda _context: next(snapshots))
    activated = manager.activate(workspaces["RO 2026"].id)

    refreshed = manager.refresh_snapshot(activated.session.session_id)

    assert refreshed.base_file == "after.xlsx"
    assert activated.session.snapshot is refreshed


def test_switch_marks_old_session_draining_and_limits_routing(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "A", "B")
    clock = FakeClock()
    manager = SessionManager(store, snapshot_factory=_snapshot, clock=clock)
    first = manager.activate(workspaces["A"].id)
    second = manager.activate(workspaces["B"].id)

    assert second.session.state == "active"
    old = next(item for item in manager.sessions() if item.session_id == first.session.session_id)
    assert old.state == "draining"
    assert old.drain_until == clock.value + 300
    with pytest.raises(SessionInactiveError):
        manager.get_session(old.session_id)
    assert manager.get_session(old.session_id, allow_draining=True) is old
    assert manager.get_session(second.session.session_id) is second.session

    third = manager.activate(workspaces["A"].id)
    assert third.workspace.id == first.workspace.id
    assert third.session.session_id != first.session.session_id
    assert manager.active_session_id == third.session.session_id
    assert all(item.state == "draining" for item in manager.sessions() if item is not third.session)


def test_missing_base_file_does_not_change_existing_active_session(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "A")
    missing = store.create(
        display_name="Missing", profile_id="ro", base_file=tmp_path / "missing.xlsx"
    )
    manager = SessionManager(store, snapshot_factory=_snapshot)
    first = manager.activate(workspaces["A"].id)

    with pytest.raises(WorkspaceNotFoundError):
        manager.activate("missing-workspace")
    assert manager.active_session_id == first.session.session_id

    with pytest.raises(WorkspaceActivationError) as error:
        manager.activate(missing.id)
    assert error.value.code == "WORKSPACE_FILE_MISSING"
    assert store.load().current_workspace_id == first.workspace.id
    assert manager.active_session_id == first.session.session_id
    assert len(manager.sessions()) == 1


def test_snapshot_failure_rolls_back_and_removes_candidate_temp_dir(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "A", "B")
    manager = SessionManager(store, snapshot_factory=_snapshot)
    first = manager.activate(workspaces["A"].id)
    candidate_dirs = set(tmp_path.glob("ro-session-*"))

    def fail(context: object) -> WorkbookSnapshot:
        del context
        raise BuildSnapshotError("schema mismatch")

    manager._snapshot_factory = fail
    with pytest.raises(WorkspaceActivationError) as error:
        manager.activate(workspaces["B"].id)
    assert error.value.code == "WORKSPACE_SCHEMA_MISMATCH"
    assert store.load().current_workspace_id == first.workspace.id
    assert manager.active_session_id == first.session.session_id
    assert {path for path in tmp_path.glob("ro-session-*")} == candidate_dirs


def test_publish_failure_restores_persistent_pointer_and_active_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, workspaces = _store(tmp_path, "A", "B")
    manager = SessionManager(store, snapshot_factory=_snapshot)
    first = manager.activate(workspaces["A"].id)
    before_dirs = set(tmp_path.glob("ro-session-*"))

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated in-memory publish failure")

    monkeypatch.setattr(manager, "_publish_candidate", fail_publish)
    with pytest.raises(WorkspaceActivationError):
        manager.activate(workspaces["B"].id)
    assert store.load().current_workspace_id == first.workspace.id
    assert manager.active_session_id == first.session.session_id
    assert {path for path in tmp_path.glob("ro-session-*")} == before_dirs


def test_unknown_profile_is_rejected_before_snapshot(tmp_path: Path) -> None:
    ro_profile = create_ro_profile()
    customer_profile = replace(
        ro_profile,
        profile_id="customer-b",
        rules=replace(cast(RoRules, ro_profile.rules), profile_id="customer-b"),
    )
    registry = ProfileRegistry((ro_profile, customer_profile))
    store = WorkspaceStore(config_dir=tmp_path / "config", profile_registry=registry)
    base = tmp_path / "base.xlsx"
    base.write_bytes(b"placeholder")
    workspace = store.create(display_name="客户 B", profile_id="customer-b", base_file=base)
    manager = SessionManager(
        store, profile_registry=ProfileRegistry((ro_profile,)), snapshot_factory=_snapshot
    )

    with pytest.raises(WorkspaceActivationError) as error:
        manager.activate(workspace.id)
    assert error.value.code == "PROFILE_NOT_FOUND"
    assert manager.active_session_id is None
    assert store.load().current_workspace_id is None


def test_restore_current_creates_new_session_after_restart(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "A")
    manager1 = SessionManager(store, snapshot_factory=_snapshot)
    first = manager1.activate(workspaces["A"].id)
    manager2 = SessionManager(store, snapshot_factory=_snapshot)

    restored = manager2.restore_current()

    assert restored is not None
    assert restored.session.session_id != first.session.session_id
    assert restored.session.temp_dir != first.session.temp_dir
    assert manager1.active_session_id == first.session.session_id
    assert manager2.active_session_id == restored.session.session_id


def test_cleanup_removes_draining_after_grace_and_active_after_ttl(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "A", "B")
    clock = FakeClock()
    manager = SessionManager(store, snapshot_factory=_snapshot, clock=clock)
    first = manager.activate(workspaces["A"].id)
    second = manager.activate(workspaces["B"].id)
    first_dir = Path(first.session.temp_dir)
    assert first_dir.exists()

    clock.advance(301)
    assert first.session.session_id in manager.cleanup()
    assert not first_dir.exists()
    assert manager.active_session_id == second.session.session_id

    clock.advance(3601)
    assert second.session.session_id in manager.cleanup()
    assert manager.active_session_id is None


def test_concurrent_activation_can_be_detected_without_partial_state(tmp_path: Path) -> None:
    store, workspaces = _store(tmp_path, "A", "B")
    entered = threading.Event()
    release = threading.Event()

    def blocking_snapshot(context: object) -> WorkbookSnapshot:
        entered.set()
        assert release.wait(timeout=5)
        return _snapshot(context)

    manager = SessionManager(store, snapshot_factory=blocking_snapshot)
    workspace_a = workspaces["A"]
    workspace_b = workspaces["B"]
    thread_error: list[BaseException] = []

    def activate_a() -> None:
        try:
            manager.activate(workspace_a.id)
        except BaseException as exc:  # pragma: no cover - only reports a thread failure
            thread_error.append(exc)

    thread = threading.Thread(target=activate_a)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(WorkspaceActivationInProgressError):
        manager.try_activate(workspace_b.id)
    assert store.load().current_workspace_id is None
    release.set()
    thread.join(timeout=5)
    assert not thread_error
    assert store.load().current_workspace_id == workspace_a.id
