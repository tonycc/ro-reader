"""Workspace/Profile/bootstrap API 契约测试。"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pytest import MonkeyPatch
from ro_workbench_api import app as app_module

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "synthetic_base.xlsx"
client = TestClient(app_module.app)


def _json(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], response.json())


@pytest.fixture(autouse=True)
def isolated_workspace_runtime(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RO_WORKBENCH_CONFIG_DIR", str(tmp_path / "config"))
    app_module._reset_workspace_runtime()
    with app_module._lock:
        app_module._sessions.clear()
    yield
    app_module._reset_workspace_runtime()
    with app_module._lock:
        app_module._sessions.clear()


def _create(name: str = "RO 2026", base: Path = FIXTURE) -> dict[str, Any]:
    response = client.post(
        "/api/workspaces",
        json={"display_name": name, "profile_id": "ro", "base_file": str(base)},
    )
    assert response.status_code == 200, response.text
    return _json(response)


def _break_required_header(src: Path, dest: Path) -> None:
    """复制 fixture 并把 DATA BASE 的 SAP 表头改掉，使结构校验失败。"""

    shutil.copy(src, dest)
    workbook = load_workbook(dest)
    sheet = workbook["DATA BASE"]
    for cell in sheet[4]:
        if cell.value == "SAP":
            cell.value = "SAP_RENAMED"
            workbook.save(dest)
            return
    raise AssertionError("DATA BASE 第 4 行没有 SAP 表头")


def test_profiles_and_first_bootstrap() -> None:
    profiles = _json(client.get("/api/profiles"))
    assert profiles["profiles"][0]["id"] == "ro"
    assert profiles["profiles"][0]["available"] is True
    assert [profile["id"] for profile in profiles["profiles"]] == ["ro", "pf"]
    assert profiles["profiles"][1]["description"] == "PF 单据流程（含 MOQ 与整箱提醒）"

    bootstrap = _json(client.get("/api/bootstrap"))
    assert bootstrap["needs_setup"] is True
    assert bootstrap["current_workspace_id"] is None
    assert bootstrap["session_id"] is None


def test_workspace_crud_and_path_validation() -> None:
    valid = _json(
        client.post(
            "/api/workspaces/validate",
            json={"display_name": "RO", "profile_id": "ro", "base_file": str(FIXTURE)},
        )
    )
    assert valid["status"] == "ready"
    assert valid["base_file_name"] == FIXTURE.name

    missing = _json(
        client.post(
            "/api/workspaces/validate",
            json={
                "display_name": "missing",
                "profile_id": "ro",
                "base_file": str(FIXTURE.with_name("missing.xlsx")),
            },
        )
    )
    assert missing["status"] == "file_missing"

    workspace = _create()
    workspace_id = workspace["id"]
    listed = _json(client.get("/api/workspaces"))
    assert [item["id"] for item in listed["workspaces"]] == [workspace_id]

    updated = _json(
        client.patch(
            f"/api/workspaces/{workspace_id}",
            json={"display_name": "RO 2027", "profile_id": "ro", "base_file": str(FIXTURE)},
        )
    )
    assert updated["display_name"] == "RO 2027"
    assert updated["id"] == workspace_id

    checked = _json(client.post(f"/api/workspaces/{workspace_id}/validate"))
    assert checked["status"] == "ready"
    assert _json(client.delete(f"/api/workspaces/{workspace_id}"))["status"] == "deleted"


def test_activate_bootstrap_and_existing_invoice_api_use_session_identity() -> None:
    workspace = _create()
    workspace_id = workspace["id"]
    activated = _json(client.post(f"/api/workspaces/{workspace_id}/activate"))
    assert activated["workspace"]["id"] == workspace_id
    assert activated["workspace"]["status"] == "ready"
    assert activated["session_id"]
    assert activated["po_list"]

    session_id = activated["session_id"]
    invoices = client.get("/api/invoices", headers={"X-Session-Id": session_id})
    assert invoices.status_code == 200
    assert "invoices" in invoices.json()

    # 有 session 时，客户端重复提交的路径只作为兼容字段，不能改变数据来源。
    po = client.get(
        "/api/po/4500099999",
        params={"base_file": str(FIXTURE.with_name("wrong.xlsx"))},
        headers={"X-Session-Id": session_id},
    )
    assert po.status_code == 200
    assert po.json()["po_no"] == "4500099999"

    bootstrap = _json(client.get("/api/bootstrap"))
    assert bootstrap["current_workspace_id"] == workspace_id
    assert bootstrap["session_id"] == session_id
    assert bootstrap["activation_error"] is None


def test_bootstrap_and_refresh_revalidate_reused_session(tmp_path: Path) -> None:
    """复用 session 时仍重建快照；文件结构坏了要返回与激活失败相同的错误。"""

    base = tmp_path / "live.xlsx"
    shutil.copy(FIXTURE, base)
    workspace = _create("Live file", base)
    activated = _json(client.post(f"/api/workspaces/{workspace['id']}/activate"))
    session_id = activated["session_id"]

    healthy = _json(client.get("/api/bootstrap"))
    assert healthy["session_id"] == session_id
    assert healthy["activation_error"] is None

    _break_required_header(FIXTURE, base)

    broken_bootstrap = _json(client.get("/api/bootstrap"))
    assert broken_bootstrap["current_workspace_id"] == workspace["id"]
    assert broken_bootstrap["session_id"] is None
    assert broken_bootstrap["activation_error"]["code"] == "WORKSPACE_SCHEMA_MISMATCH"

    refresh = client.post("/api/session/refresh", headers={"X-Session-Id": session_id})
    assert refresh.status_code == 400
    assert _json(refresh)["detail"]["code"] == "WORKSPACE_SCHEMA_MISMATCH"


def test_edit_refreshes_managed_session_snapshot_for_preview(tmp_path: Path) -> None:
    base = tmp_path / "managed-edit.xlsx"
    shutil.copy(FIXTURE, base)
    workspace = _create("Managed edit", base)
    activated = _json(client.post(f"/api/workspaces/{workspace['id']}/activate"))
    session_id = activated["session_id"]
    request = {
        "base_file": str(base),
        "po_no": "4500099999",
        "seller": "GS PTE",
        "invoice_no": "INV-2603-001",
        "document": "INVOICE",
    }

    before = _json(
        client.post(
            "/api/po/4500099999/preview",
            json=request,
            headers={"X-Session-Id": session_id},
        )
    )
    assert before["preview"]["lines"][0]["description"] == "CB2500.B2 Combo"

    edited = client.post(
        "/api/po/4500099999/edit",
        json={
            "base_file": str(base),
            "sheet": "PO record",
            "row": 8,
            "field": "DESCRIPTION",
            "value": "UPDATED DESCRIPTION",
        },
        headers={"X-Session-Id": session_id},
    )
    assert edited.status_code == 200
    assert edited.json()["ok"] is True, edited.text

    after = _json(
        client.post(
            "/api/po/4500099999/preview",
            json=request,
            headers={"X-Session-Id": session_id},
        )
    )
    assert after["preview"]["lines"][0]["description"] == "UPDATED DESCRIPTION"


def test_current_workspace_update_requires_a_new_session_identity_on_bootstrap(
    tmp_path: Path,
) -> None:
    workspace = _create()
    activated = _json(client.post(f"/api/workspaces/{workspace['id']}/activate"))
    old_session_id = activated["session_id"]

    replacement = tmp_path / "replacement.xlsx"
    shutil.copy(FIXTURE, replacement)
    updated = _json(
        client.patch(
            f"/api/workspaces/{workspace['id']}",
            json={
                "display_name": workspace["display_name"],
                "profile_id": "ro",
                "base_file": str(replacement),
            },
        )
    )
    assert updated["status"] == "unchecked"
    assert "重新检测并激活" in updated["status_message"]

    # 修改配置不会半途切断旧页面；在重新 bootstrap/激活前，旧 session 仍可完成读取。
    old_invoices = client.get("/api/invoices", headers={"X-Session-Id": old_session_id})
    assert old_invoices.status_code == 200

    bootstrap = _json(client.get("/api/bootstrap"))
    assert bootstrap["current_workspace_id"] == workspace["id"]
    assert bootstrap["session_id"] != old_session_id
    assert bootstrap["workspace"]["base_file"] == str(replacement.absolute())
    assert bootstrap["activation_error"] is None

    # 新 session 已发布后，旧 session 进入 draining，不能再访问业务端点。
    old_after_switch = client.get("/api/invoices", headers={"X-Session-Id": old_session_id})
    assert old_after_switch.status_code == 400
    assert old_after_switch.json()["detail"]["code"] == "INVALID_SESSION"


def test_invalid_current_workspace_update_keeps_old_session_and_surfaces_bootstrap_error(
    tmp_path: Path,
) -> None:
    workspace = _create()
    activated = _json(client.post(f"/api/workspaces/{workspace['id']}/activate"))
    old_session_id = activated["session_id"]
    missing = tmp_path / "missing-after-edit.xlsx"
    client.patch(
        f"/api/workspaces/{workspace['id']}",
        json={
            "display_name": workspace["display_name"],
            "profile_id": "ro",
            "base_file": str(missing),
        },
    )

    bootstrap = _json(client.get("/api/bootstrap"))
    assert bootstrap["current_workspace_id"] == workspace["id"]
    assert bootstrap["session_id"] is None
    assert bootstrap["activation_error"]["code"] == "WORKSPACE_FILE_MISSING"
    assert bootstrap["workspaces"][0]["status"] == "file_missing"

    # 恢复失败不应破坏仍在内存中的旧工作台；用户修复配置后可再次 activate。
    old_invoices = client.get("/api/invoices", headers={"X-Session-Id": old_session_id})
    assert old_invoices.status_code == 200


def test_activation_failure_records_target_and_legacy_open_requires_activation(
    tmp_path: Path,
) -> None:
    workspace = _create()
    activated = _json(client.post(f"/api/workspaces/{workspace['id']}/activate"))
    assert activated["session_id"]

    other = tmp_path / "other.xlsx"
    shutil.copy(FIXTURE, other)
    legacy = client.post("/api/session/open", json={"base_file": str(other)})
    assert legacy.status_code == 409
    assert _json(legacy)["detail"]["code"] == "WORKSPACE_ACTIVATION_REQUIRED"

    missing = _create("missing", tmp_path / "missing.xlsx")
    failed = client.post(f"/api/workspaces/{missing['id']}/activate")
    assert failed.status_code == 400
    assert _json(failed)["detail"]["code"] == "WORKSPACE_FILE_MISSING"
    bootstrap = _json(client.get("/api/bootstrap"))
    assert bootstrap["current_workspace_id"] == missing["id"]
    assert bootstrap["activation_error"]["code"] == "WORKSPACE_FILE_MISSING"


def test_current_workspace_cannot_be_deleted_and_unknown_workspace_has_stable_error() -> None:
    workspace = _create()
    client.post(f"/api/workspaces/{workspace['id']}/activate")

    deleted = client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 409
    assert _json(deleted)["detail"]["code"] == "WORKSPACE_CURRENT_DELETE_FORBIDDEN"

    unknown = client.post("/api/workspaces/unknown/activate")
    assert unknown.status_code == 404
    assert _json(unknown)["detail"]["code"] == "WORKSPACE_NOT_FOUND"
