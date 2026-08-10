"""工作台 API 测试的用户配置隔离。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch


@pytest.fixture(autouse=True)
def isolated_workbench_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """任何 API 测试都不得读取或覆盖用户真实工作区配置。"""

    monkeypatch.setenv("RO_WORKBENCH_CONFIG_DIR", str(tmp_path / "workbench-config"))
