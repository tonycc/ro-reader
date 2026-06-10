"""工作台 API 边界测试。"""

from __future__ import annotations

import shutil
import time

import pytest
from fastapi import HTTPException
from ro_workbench_api.app import SessionInfo, _lock, _sessions, download_file


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
            session_id="own",
            base_file="/tmp/own-base.xlsx",
            temp_dir=str(own_dir),
            created_at=time.time(),
            last_access=time.time(),
        )
        _sessions["other"] = SessionInfo(
            session_id="other",
            base_file="/tmp/other-base.xlsx",
            temp_dir=str(other_dir),
            created_at=time.time(),
            last_access=time.time(),
        )

    try:
        with pytest.raises(HTTPException) as exc_info:
            download_file(path=str(other_file), x_session_id="own")

        assert exc_info.value.status_code == 403
    finally:
        with _lock:
            _sessions.clear()
        shutil.rmtree(own_dir, ignore_errors=True)
        shutil.rmtree(other_dir, ignore_errors=True)
