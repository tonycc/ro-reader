"""工作台 API 边界测试。"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from ro_workbench_api.app import (
    SessionInfo,
    _cleanup_expired_sessions,
    _lock,
    _sessions,
    app,
)

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "synthetic_base.xlsx"

client = TestClient(app)


def _clear_sessions():
    with _lock:
        _sessions.clear()


@pytest.fixture(autouse=True)
def clean_sessions():
    _clear_sessions()
    yield
    _clear_sessions()


# --- Session lifecycle ---

def test_open_session_returns_po_list():
    resp = client.post("/api/session/open", json={"base_file": str(FIXTURE)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["session_id"]) == 12
    assert len(data["po_list"]) == 3
    po_nos = {p["po_no"] for p in data["po_list"]}
    assert "4500030844" in po_nos
    assert "4500099999" in po_nos
    assert "4500088888" in po_nos


def test_open_session_reuses_existing_for_same_base():
    resp1 = client.post("/api/session/open", json={"base_file": str(FIXTURE)})
    resp2 = client.post("/api/session/open", json={"base_file": str(FIXTURE)})
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["session_id"] == resp2.json()["session_id"]


def test_open_session_creates_new_for_different_base(tmp_path):
    other = tmp_path / "copy_base.xlsx"
    shutil.copy(FIXTURE, other)
    try:
        resp1 = client.post("/api/session/open", json={"base_file": str(FIXTURE)})
        resp2 = client.post("/api/session/open", json={"base_file": str(other)})
        assert resp1.json()["session_id"] != resp2.json()["session_id"]
    finally:
        other.unlink(missing_ok=True)


def test_close_session_removes_it():
    resp = client.post("/api/session/open", json={"base_file": str(FIXTURE)})
    sid = resp.json()["session_id"]
    resp2 = client.post("/api/session/close", json={"session_id": sid})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "closed"
    # Double close is safe
    resp3 = client.post("/api/session/close", json={"session_id": sid})
    assert resp3.json()["status"] == "not_found"


# --- Invalid session rejection ---

def test_dry_run_rejects_invalid_session():
    resp = client.post(
        "/api/po/4500099999/dry-run",
        json={
            "base_file": str(FIXTURE), "po_no": "4500099999",
            "seller": "GS PTE", "buyer": "EMAX PTE", "document": "PI",
        },
        headers={"X-Session-Id": "nonexistent"},
    )
    assert resp.status_code == 400
    assert "INVALID_SESSION" in str(resp.json()["detail"])


def test_preview_rejects_invalid_session():
    resp = client.post(
        "/api/po/4500099999/preview",
        json={
            "base_file": str(FIXTURE), "po_no": "4500099999",
            "seller": "GS PTE", "buyer": "EMAX PTE", "document": "PI",
        },
        headers={"X-Session-Id": "nonexistent"},
    )
    assert resp.status_code == 400


def test_export_rejects_invalid_session():
    resp = client.post(
        "/api/po/4500099999/export",
        json={
            "base_file": str(FIXTURE), "po_no": "4500099999",
            "seller": "GS PTE", "buyer": "EMAX PTE", "document": "PI",
        },
        headers={"X-Session-Id": "nonexistent"},
    )
    assert resp.status_code == 400


def test_get_po_issues_requires_valid_session():
    resp = client.get(
        f"/api/po/4500088888/issues?base_file={FIXTURE}",
        headers={"X-Session-Id": "nonexistent"},
    )

    assert resp.status_code == 400


def test_get_po_issues_returns_blocking_details():
    sid = client.post("/api/session/open", json={"base_file": str(FIXTURE)}).json()["session_id"]

    resp = client.get(
        f"/api/po/4500088888/issues?base_file={FIXTURE}",
        headers={"X-Session-Id": sid},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["po_no"] == "4500088888"
    assert data["blocking_count"] >= 1
    assert data["blocking_errors"][0]["kind"] == "blocking_error"
    assert data["blocking_errors"][0]["message"]


def test_export_uses_zip_output_format(monkeypatch, tmp_path):
    from ro_generator.models import GenerationResult

    captured = {}

    def fake_generate(request):
        captured["output_format"] = request.output_format
        output = tmp_path / "RO-4500099999-2601.zip"
        output.write_bytes(b"fake zip")
        return GenerationResult(
            status="success",
            files=("YM-RO-INVOICE&PL-4500099999-2601.xlsx", "SK-RO-INVOICE&PL-4500099999-2601.xlsx"),
            output_file=str(output),
        )

    monkeypatch.setattr("ro_workbench_api.app.generate", fake_generate)
    sid = client.post("/api/session/open", json={"base_file": str(FIXTURE)}).json()["session_id"]

    resp = client.post(
        "/api/po/4500099999/export",
        json={
            "base_file": str(FIXTURE),
            "po_no": "4500099999",
            "seller": "YM",
            "document": "INVOICE",
        },
        headers={"X-Session-Id": sid},
    )

    assert resp.status_code == 200
    assert captured["output_format"] == "zip"
    assert resp.json()["output_file"].endswith(".zip")


def test_export_invoice_pl_requests_combined_documents(monkeypatch, tmp_path):
    from ro_generator.models import GenerationResult

    captured = {}

    def fake_generate(request):
        captured["documents"] = request.documents
        captured["output_format"] = request.output_format
        output = tmp_path / "SK-RO-INVOICE&PL-4500099999.xlsx"
        output.write_bytes(b"fake xlsx")
        return GenerationResult(
            status="success",
            files=("SK-RO-INVOICE&PL-4500099999.xlsx",),
            output_file=str(output),
        )

    monkeypatch.setattr("ro_workbench_api.app.generate", fake_generate)
    sid = client.post("/api/session/open", json={"base_file": str(FIXTURE)}).json()["session_id"]

    resp = client.post(
        "/api/po/4500099999/export",
        json={
            "base_file": str(FIXTURE),
            "po_no": "4500099999",
            "seller": "SK",
            "document": "INVOICE_PL",
        },
        headers={"X-Session-Id": sid},
    )

    assert resp.status_code == 200
    assert captured["documents"] == ("INVOICE", "PL")
    assert captured["output_format"] == "zip"
    data = resp.json()
    assert data["files"] == ["SK-RO-INVOICE&PL-4500099999.xlsx"]
    assert data["output_file"].endswith(".xlsx")


# --- Session expiry ---

def test_cleanup_removes_expired_session():
    """Expired sessions are removed by cleanup (not by _get_session which doesn't check TTL)."""
    with _lock:
        _sessions["exp"] = SessionInfo(
            session_id="exp", base_file=str(FIXTURE),
            temp_dir="/tmp/fake-exp", created_at=0, last_access=0,
        )
    _cleanup_expired_sessions()
    with _lock:
        assert "exp" not in _sessions


def test_cleanup_keeps_fresh_sessions():
    sid = client.post("/api/session/open", json={"base_file": str(FIXTURE)}).json()["session_id"]
    _cleanup_expired_sessions()
    with _lock:
        assert sid in _sessions


# --- Download path traversal protection ---

def test_download_cannot_read_another_session_file(tmp_path):
    own_dir = tmp_path / "own"
    other_dir = tmp_path / "other"
    own_dir.mkdir()
    other_dir.mkdir()
    other_file = other_dir / "invoice.xlsx"
    other_file.write_bytes(b"not a real workbook; only auth boundary matters")

    with _lock:
        _sessions.clear()
        _sessions["own"] = SessionInfo(
            session_id="own", base_file="/tmp/own-base.xlsx",
            temp_dir=str(own_dir), created_at=time.time(), last_access=time.time(),
        )
        _sessions["other"] = SessionInfo(
            session_id="other", base_file="/tmp/other-base.xlsx",
            temp_dir=str(other_dir), created_at=time.time(), last_access=time.time(),
        )

    try:
        from ro_workbench_api.app import download_file

        with pytest.raises(HTTPException) as exc_info:
            download_file(path=str(other_file), x_session_id="own")

        assert exc_info.value.status_code == 403
    finally:
        with _lock:
            _sessions.clear()
        shutil.rmtree(own_dir, ignore_errors=True)
        shutil.rmtree(other_dir, ignore_errors=True)


# --- check-path endpoint ---

def test_check_path_valid_file():
    resp = client.post("/api/check-path", json={"path": str(FIXTURE)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "DATA BASE" in data["sheets"] or "PO record" in data["sheets"]
    assert data["size"] > 0


def test_check_path_nonexistent():
    resp = client.post("/api/check-path", json={"path": "/nonexistent/file.xlsx"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "不存在" in data["error"]


def test_check_path_unsupported_extension(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    resp = client.post("/api/check-path", json={"path": str(f)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "不支持" in data["error"]


# --- Health ---

def test_health_returns_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- edit endpoint ---

def test_edit_field_rejects_invalid_sheet(tmp_path):
    base = tmp_path / "test_base.xlsx"
    shutil.copy(FIXTURE, base)
    try:
        resp = client.post(
            "/api/po/TEST/edit",
            json={"base_file": str(base), "sheet": "NonExistent", "row": 5, "field": "X", "value": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
    finally:
        base.unlink(missing_ok=True)


def test_edit_field_writes_value(tmp_path):
    import openpyxl

    base = tmp_path / "test_base.xlsx"
    shutil.copy(FIXTURE, base)
    try:
        # First open a session so cache is primed
        client.post("/api/session/open", json={"base_file": str(base)})

        # Get the actual header name from the PO record
        wb = openpyxl.load_workbook(str(base), data_only=True)
        ws = wb["PO record"]
        header_cell = ws.cell(row=4, column=5).value  # Column E, row 4
        wb.close()
        field_name = str(header_cell).strip().replace("\n", " ")

        resp = client.post(
            "/api/po/TEST/edit",
            json={"base_file": str(base), "sheet": "PO record", "row": 5, "field": field_name, "value": "TEST_VALUE"},
        )
        data = resp.json()
        assert data["ok"] is True, f"Edit failed: {data.get('message')}"

        # Verify the value was actually written
        wb = openpyxl.load_workbook(str(base), data_only=True)
        ws = wb["PO record"]
        cell_val = str(ws.cell(row=5, column=5).value) if ws.cell(row=5, column=5).value is not None else ""
        wb.close()
        assert cell_val == "TEST_VALUE"
    finally:
        base.unlink(missing_ok=True)
