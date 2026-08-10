"""WorkspaceStore 的本地配置、迁移和原子写入测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ro_generator.errors import ProfileNotFoundError
from ro_workbench_api.workspace_store import (
    CurrentWorkspaceDeleteError,
    WorkspaceConfigInvalidError,
    WorkspaceConfigWriteError,
    WorkspaceNotFoundError,
    WorkspaceStore,
)


def test_first_start_is_empty_and_create_does_not_read_base_file(tmp_path: Path) -> None:
    store = WorkspaceStore(
        config_dir=tmp_path / "config", clock=lambda: "2026-08-07T10:00:00+08:00"
    )

    assert store.load().current_workspace_id is None
    assert store.list_workspaces() == ()
    workspace = store.create(
        display_name=" RO 2026 ",
        profile_id="ro",
        base_file=tmp_path / "does-not-exist.xlsx",
    )

    assert workspace.id.startswith("workspace-")
    assert workspace.display_name == "RO 2026"
    assert workspace.base_file == str((tmp_path / "does-not-exist.xlsx").absolute())
    assert store.get(workspace.id) == workspace
    assert store.config_path.exists()


def test_restart_round_trip_and_current_workspace_pointer(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    store = WorkspaceStore(config_dir=config_dir, clock=lambda: "2026-08-07T10:00:00+08:00")
    first = store.create(display_name="RO 2026", profile_id="ro", base_file="base.xlsx")
    second = store.create(display_name="RO 测试", profile_id="ro", base_file="test.xlsx")

    settings = store.set_current_workspace(first.id)
    assert settings.current_workspace_id == first.id
    assert store.get_current() == first

    restarted = WorkspaceStore(config_dir=config_dir, clock=lambda: "2026-08-07T11:00:00+08:00")
    assert restarted.list_workspaces() == (first, second)
    assert restarted.get_current() == first
    assert restarted.clear_current_workspace().current_workspace_id is None
    assert restarted.get_current() is None


def test_update_keeps_stable_id_and_created_at(tmp_path: Path) -> None:
    times = iter(("2026-08-07T10:00:00+08:00", "2026-08-07T11:00:00+08:00"))
    store = WorkspaceStore(config_dir=tmp_path, clock=lambda: next(times))
    original = store.create(display_name="RO", profile_id="ro", base_file="base.xlsx")

    updated = store.update(
        original.id,
        display_name="RO 2027",
        base_file=tmp_path / "new-base.xlsx",
    )
    assert updated.id == original.id
    assert updated.created_at == original.created_at
    assert updated.updated_at == "2026-08-07T11:00:00+08:00"
    assert updated.display_name == "RO 2027"
    assert updated.base_file == str((tmp_path / "new-base.xlsx").absolute())


def test_profile_and_workspace_validation(tmp_path: Path) -> None:
    store = WorkspaceStore(config_dir=tmp_path)

    with pytest.raises(ProfileNotFoundError) as profile_error:
        store.create(display_name="客户 B", profile_id="customer-b", base_file="b.xlsx")
    assert profile_error.value.code == "PROFILE_NOT_FOUND"

    with pytest.raises(WorkspaceNotFoundError):
        store.update("missing", display_name="new")

    workspace = store.create(display_name="RO", profile_id="ro", base_file="base.xlsx")
    with pytest.raises(CurrentWorkspaceDeleteError):
        store.set_current_workspace(workspace.id)
        store.delete(workspace.id)

    with pytest.raises(WorkspaceNotFoundError):
        store.delete("missing")


def test_delete_non_current_workspace_and_mark_opened(tmp_path: Path) -> None:
    store = WorkspaceStore(config_dir=tmp_path, clock=lambda: "2026-08-07T10:00:00+08:00")
    first = store.create(display_name="RO", profile_id="ro", base_file="base.xlsx")
    second = store.create(display_name="RO test", profile_id="ro", base_file="test.xlsx")
    store.set_current_workspace(first.id)

    opened = store.mark_opened(second.id, opened_at="2026-08-07T12:00:00+08:00")
    assert opened.last_opened_at == "2026-08-07T12:00:00+08:00"
    assert store.get_current() == first
    store.delete(second.id)
    assert store.list_workspaces() == (first,)


def test_corrupt_json_is_reported_without_replacing_file(tmp_path: Path) -> None:
    store = WorkspaceStore(config_dir=tmp_path)
    store.config_path.write_text("{not-json", encoding="utf-8")
    original = store.config_path.read_bytes()

    with pytest.raises(WorkspaceConfigInvalidError) as error:
        store.load()
    assert error.value.code == "WORKSPACE_CONFIG_INVALID"
    assert store.config_path.read_bytes() == original


def test_atomic_write_failure_preserves_last_valid_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = WorkspaceStore(config_dir=tmp_path)
    original = store.create(display_name="RO", profile_id="ro", base_file="base.xlsx")
    original_bytes = store.config_path.read_bytes()

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("ro_workbench_api.workspace_store.os.replace", fail_replace)
    with pytest.raises(WorkspaceConfigWriteError) as error:
        store.update(original.id, display_name="should not persist")
    assert error.value.code == "WORKSPACE_CONFIG_WRITE_FAILED"
    assert store.config_path.read_bytes() == original_bytes
    assert store.get(original.id).display_name == "RO"
    assert not list(tmp_path.glob(".workspaces.json.*.tmp"))


def test_migrate_v0_payload_and_reject_future_version(tmp_path: Path) -> None:
    store = WorkspaceStore(config_dir=tmp_path)
    payload: dict[str, object] = {
        "current_workspace_id": None,
        "workspaces": [],
    }
    store.config_path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load().schema_version == 1

    store.config_path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(WorkspaceConfigInvalidError):
        store.load()


def test_config_directory_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RO_WORKBENCH_CONFIG_DIR", str(tmp_path / "portable"))
    store = WorkspaceStore()
    assert store.config_dir == (tmp_path / "portable").absolute()
