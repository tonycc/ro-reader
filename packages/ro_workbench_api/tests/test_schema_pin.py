"""系统校验码配置文件的读取与覆盖测试。"""

from __future__ import annotations

from pathlib import Path

from ro_workbench_api.schema_pin import (
    SCHEMA_PIN_FILENAME,
    SCHEMA_REPAIR_PIN,
    ensure_schema_pin_file,
    load_schema_pin,
    schema_pin_path,
    verify_schema_pin,
)


def test_missing_file_uses_builtin_default(tmp_path: Path) -> None:
    assert load_schema_pin(tmp_path) == SCHEMA_REPAIR_PIN
    assert verify_schema_pin(SCHEMA_REPAIR_PIN, config_dir=tmp_path)
    assert not verify_schema_pin("0000", config_dir=tmp_path)
    assert not verify_schema_pin("", config_dir=tmp_path)


def test_ensure_writes_default_file_once(tmp_path: Path) -> None:
    path = ensure_schema_pin_file(tmp_path)
    assert path == tmp_path / SCHEMA_PIN_FILENAME
    assert SCHEMA_REPAIR_PIN in path.read_text(encoding="utf-8")
    path.write_text("custom-pin\n", encoding="utf-8")
    ensure_schema_pin_file(tmp_path)
    assert load_schema_pin(tmp_path) == "custom-pin"


def test_file_overrides_default_and_skips_comments(tmp_path: Path) -> None:
    schema_pin_path(tmp_path).write_text(
        "# comment\n\n  office-pin  \nsecond-ignored\n",
        encoding="utf-8",
    )
    assert load_schema_pin(tmp_path) == "office-pin"
    assert verify_schema_pin("office-pin", config_dir=tmp_path)
    assert not verify_schema_pin(SCHEMA_REPAIR_PIN, config_dir=tmp_path)


def test_empty_or_comment_only_file_falls_back(tmp_path: Path) -> None:
    schema_pin_path(tmp_path).write_text("# only comment\n\n", encoding="utf-8")
    assert load_schema_pin(tmp_path) == SCHEMA_REPAIR_PIN
