"""Schema 结构映射配置 API 的边界测试。

覆盖：issues 探测、mappings 总览、PIN 校验/设置、override 保存闭环。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from ro_workbench_api import app as app_module
from ro_workbench_api.schema_pin import SCHEMA_PIN_FILENAME, SCHEMA_REPAIR_PIN

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "synthetic_base.xlsx"

client = TestClient(app_module.app)


def _json(resp: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resp.json())


@pytest.fixture(autouse=True)
def reset_workspace_runtime() -> Iterator[None]:
    app_module._reset_workspace_runtime()
    yield
    app_module._reset_workspace_runtime()


def _make_workspace() -> tuple[str, str]:
    """创建工作区并激活，返回 (workspace_id, session_id)。"""

    resp = client.post(
        "/api/workspaces",
        json={"display_name": "测试", "profile_id": "ro", "base_file": str(FIXTURE)},
    )
    assert resp.status_code == 200, resp.text
    workspace_id = _json(resp)["id"]
    act = client.post(f"/api/workspaces/{workspace_id}/activate")
    assert act.status_code == 200, act.text
    session_id = _json(act)["session_id"]
    return workspace_id, session_id


def test_schema_issues_no_problem_on_matching_workbook() -> None:
    _workspace_id, session_id = _make_workspace()
    resp = client.get("/api/schema/issues", headers={"X-Session-Id": session_id})
    assert resp.status_code == 200
    data = _json(resp)
    assert data["has_issues"] is False
    assert data["field_issues"] == []


def test_schema_issues_via_workspace_id_without_session() -> None:
    workspace_id, _session_id = _make_workspace()
    resp = client.get(f"/api/schema/issues?workspace_id={workspace_id}")
    assert resp.status_code == 200
    assert _json(resp)["has_issues"] is False


def test_schema_issues_requires_target() -> None:
    resp = client.get("/api/schema/issues")
    assert resp.status_code == 400
    assert _json(resp)["detail"]["code"] == "INVALID_SESSION"


def test_schema_mappings_returns_groups() -> None:
    _workspace_id, session_id = _make_workspace()
    resp = client.get("/api/schema/mappings", headers={"X-Session-Id": session_id})
    assert resp.status_code == 200
    groups = _json(resp)["groups"]
    logical = {g["logical_sheet"] for g in groups}
    assert {"DATA BASE", "PO record", "客户PO"} <= logical
    db = next(g for g in groups if g["logical_sheet"] == "DATA BASE" and g.get("kind") != "price")
    assert "SAP" in db["available_headers"]
    assert db["column_letters"]["SAP"] == "A"


def test_system_pin_verify_rejects_wrong_and_accepts_default() -> None:
    _make_workspace()

    empty = client.post("/api/schema/verify-pin", json={"pin": ""})
    assert empty.status_code == 403
    assert _json(empty)["detail"]["code"] == "PIN_INVALID"

    bad = client.post("/api/schema/verify-pin", json={"pin": "0000"})
    assert bad.status_code == 403
    assert _json(bad)["detail"]["code"] == "PIN_INVALID"

    good = client.post("/api/schema/verify-pin", json={"pin": SCHEMA_REPAIR_PIN})
    assert good.status_code == 200
    assert _json(good)["verified"] is True

    # 不再提供用户设置入口
    missing = client.post("/api/schema/pin", json={"pin": "2468"})
    assert missing.status_code == 404


def test_override_merge_keeps_unrelated_aliases_and_can_revert() -> None:
    _workspace_id, session_id = _make_workspace()
    override_path = FIXTURE.with_suffix("").parent / f"{FIXTURE.with_suffix('').name}.schema.yaml"
    headers = {"X-Session-Id": session_id}
    try:
        first = client.post(
            "/api/schema/override",
            json={"field_aliases": {"DATA BASE": {"description": "SAP"}}},
            headers=headers,
        )
        assert first.status_code == 200, first.text

        second = client.post(
            "/api/schema/override",
            json={"field_aliases": {"PO record": {"po_no": "ITEM LINE#"}}},
            headers=headers,
        )
        assert second.status_code == 200, second.text

        mapped = _json(client.get("/api/schema/mappings", headers=headers))["groups"]
        db = next(
            g for g in mapped if g["logical_sheet"] == "DATA BASE" and g.get("kind") != "price"
        )
        desc = next(f for f in db["fields"] if f["internal_key"] == "description")
        assert desc["is_overridden"] is True
        po = next(g for g in mapped if g["logical_sheet"] == "PO record")
        po_no = next(f for f in po["fields"] if f["internal_key"] == "po_no")
        assert po_no["is_overridden"] is True

        revert = client.post(
            "/api/schema/override",
            json={"field_aliases": {"DATA BASE": {"description": desc["builtin_header"]}}},
            headers=headers,
        )
        assert revert.status_code == 200, revert.text
        after = _json(client.get("/api/schema/mappings", headers=headers))["groups"]
        db_after = next(
            g for g in after if g["logical_sheet"] == "DATA BASE" and g.get("kind") != "price"
        )
        desc_after = next(f for f in db_after["fields"] if f["internal_key"] == "description")
        po_after = next(g for g in after if g["logical_sheet"] == "PO record")
        po_no_after = next(f for f in po_after["fields"] if f["internal_key"] == "po_no")
        assert desc_after["is_overridden"] is False
        assert po_no_after["is_overridden"] is True
    finally:
        override_path.unlink(missing_ok=True)


def test_config_file_pin_overrides_builtin(tmp_path: Path) -> None:
    _make_workspace()
    config_dir = tmp_path / "workbench-config"
    (config_dir / SCHEMA_PIN_FILENAME).write_text("office-pin\n", encoding="utf-8")

    denied = client.post("/api/schema/verify-pin", json={"pin": SCHEMA_REPAIR_PIN})
    assert denied.status_code == 403
    accepted = client.post("/api/schema/verify-pin", json={"pin": "office-pin"})
    assert accepted.status_code == 200
    assert _json(accepted)["verified"] is True


def test_save_override_persists_and_reports_no_remaining(tmp_path: Path) -> None:
    _workspace_id, session_id = _make_workspace()
    override_path = FIXTURE.with_suffix("").parent / f"{FIXTURE.with_suffix('').name}.schema.yaml"
    try:
        resp = client.post(
            "/api/schema/override",
            json={"field_aliases": {"PO record": {"po_no": "PO NO."}}},
            headers={"X-Session-Id": session_id},
        )
        assert resp.status_code == 200, resp.text
        data = _json(resp)
        assert data["saved"] is True
        assert data["session_refreshed"] is True
        assert data["remaining_issues"]["has_issues"] is False
    finally:
        override_path.unlink(missing_ok=True)


def test_price_override_redirects_column_and_clears_issue(tmp_path: Path) -> None:
    """价格列改名后应被检测为 issue；override 重定向后 issue 消除。"""

    _workspace_id, session_id = _make_workspace()
    override_path = FIXTURE.with_suffix("").parent / f"{FIXTURE.with_suffix('').name}.schema.yaml"
    try:
        # 把价格键指到另一张已存在的列；合并写入后应标成 overridden。
        resp = client.post(
            "/api/schema/override",
            json={"price_columns": {"data_base_price_columns": {"EMAX PTE/combo": "SAP"}}},
            headers={"X-Session-Id": session_id},
        )
        assert resp.status_code == 200, resp.text
        data = _json(resp)
        assert data["saved"] is True
        assert data["remaining_issues"]["has_issues"] is False
        assert data["remaining_issues"]["price_issues"] == []

        m = client.get("/api/schema/mappings", headers={"X-Session-Id": session_id})
        assert m.status_code == 200, m.text
        groups = _json(m)["groups"]
        price_group = next(g for g in groups if g.get("kind") == "price")
        combo = next(f for f in price_group["fields"] if f["internal_key"] == "EMAX PTE/combo")
        assert combo["effective_header"] == "SAP"
        assert combo["is_overridden"] is True
        assert combo["builtin_header"] == "EMAX PTE COMBO FOB 2026"
    finally:
        override_path.unlink(missing_ok=True)
