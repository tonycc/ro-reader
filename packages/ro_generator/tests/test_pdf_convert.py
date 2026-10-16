"""pdf_convert 单元测试。

真实 LibreOffice 转换只在本机装了 soffice 时跑（skipif 守卫）；其余用例通过
monkeypatch find_soffice / subprocess.run 在无 soffice 环境（含 CI）下验证逻辑。
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path
from xml.etree import ElementTree

import pytest
from ro_generator import pdf_convert
from ro_generator.errors import PdfConversionError, SofficeNotFoundError
from ro_generator.pdf_convert import convert_to_pdf, find_soffice


def _make_xlsx(tmp_path: Path) -> Path:
    xlsx = tmp_path / "doc.xlsx"
    xlsx.write_bytes(b"PK\x03\x04 fake xlsx")
    return xlsx


def test_find_soffice_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "soffice"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("RO_SOFFICE_PATH", str(fake))
    assert find_soffice() == fake


def test_find_soffice_missing(monkeypatch):
    monkeypatch.delenv("RO_SOFFICE_PATH", raising=False)
    monkeypatch.setattr(pdf_convert.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pdf_convert, "_candidate_paths", list)
    assert find_soffice() is None


def test_convert_missing_soffice_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_convert, "find_soffice", lambda: None)
    xlsx = _make_xlsx(tmp_path)
    with pytest.raises(SofficeNotFoundError):
        convert_to_pdf(xlsx)


def test_convert_missing_input_raises(tmp_path):
    with pytest.raises(PdfConversionError):
        convert_to_pdf(tmp_path / "does-not-exist.xlsx")


def test_convert_success_with_mocked_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_convert, "find_soffice", lambda: Path("/fake/soffice"))

    def fake_run(cmd, **_kwargs):
        assert "--norestore" in cmd
        assert "--nofirststartwizard" not in cmd
        out_dir = Path(cmd[cmd.index("--outdir") + 1])
        src = Path(cmd[-1])
        (out_dir / f"{src.stem}.pdf").write_bytes(b"%PDF-1.4\n")
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(pdf_convert.subprocess, "run", fake_run)

    xlsx = _make_xlsx(tmp_path)
    pdf = convert_to_pdf(xlsx)
    assert pdf == tmp_path / "doc.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")


def test_convert_nonzero_exit_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_convert, "find_soffice", lambda: Path("/fake/soffice"))
    monkeypatch.setattr(
        pdf_convert.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stderr=b"boom"),
    )
    xlsx = _make_xlsx(tmp_path)
    with pytest.raises(PdfConversionError):
        convert_to_pdf(xlsx)


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_timeout_stays_blocking_and_offers_macos_startup_recovery(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(pdf_convert.sys, "platform", platform)
    monkeypatch.setattr(pdf_convert, "find_soffice", lambda: Path("/fake/soffice"))
    profiles = []

    def timeout_run(cmd, **kwargs):
        profiles.append(cmd[4].split("file://", 1)[1])
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(pdf_convert.subprocess, "run", timeout_run)
    xlsx = _make_xlsx(tmp_path)
    original = xlsx.read_bytes()
    with pytest.raises(PdfConversionError, match="转换超时") as error:
        convert_to_pdf(xlsx, timeout=3)
    assert ("手动打开 LibreOffice" in str(error.value)) == (platform == "darwin")
    assert len(profiles) == 1  # 不静默降级、重试或打开用户 GUI。
    assert not Path(profiles[0]).exists()
    assert xlsx.read_bytes() == original


def test_macos_font_config_is_scoped_to_conversion_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_convert.sys, "platform", "darwin")
    monkeypatch.setattr(pdf_convert, "find_soffice", lambda: Path("/fake/soffice"))
    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    monkeypatch.setenv("FONTCONFIG_PATH", str(tmp_path / "custom & fonts"))
    monkeypatch.setenv("RO_PDF_TEST_PRESERVED", "yes")
    before = dict(os.environ)
    config_paths = []

    def fake_run(cmd, **kwargs):
        env = kwargs["env"]
        assert env["RO_PDF_TEST_PRESERVED"] == "yes"
        config_path = Path(env["FONTCONFIG_FILE"])
        config_paths.append(config_path)
        config = ElementTree.parse(config_path).getroot()
        assert config.tag == "fontconfig"
        assert config[0].tag == "cachedir"
        assert config.findtext("include") == str(tmp_path / "custom & fonts" / "fonts.conf")
        cache = Path(config.findtext("cachedir"))
        assert cache.parent == config_path.parent
        assert config_path.parent.as_uri() in cmd[4]
        # 不写入系统或用户字体目录，也不修改源 workbook。
        src = Path(cmd[-1])
        src.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(pdf_convert.subprocess, "run", fake_run)
    xlsx = _make_xlsx(tmp_path)
    original = xlsx.read_bytes()
    convert_to_pdf(xlsx)
    convert_to_pdf(xlsx)
    assert dict(os.environ) == before
    assert xlsx.read_bytes() == original
    assert config_paths[0] != config_paths[1]
    assert all(not path.parent.exists() for path in config_paths)


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_conversion_preserves_explicit_font_config(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(pdf_convert.sys, "platform", platform)
    monkeypatch.setenv("FONTCONFIG_FILE", str(tmp_path / "user-fonts.conf"))
    assert pdf_convert._conversion_env(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_non_macos_uses_existing_font_discovery(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(pdf_convert.sys, "platform", platform)
    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    assert pdf_convert._conversion_env(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(find_soffice() is None, reason="本机未安装 LibreOffice，跳过真实转换")
def test_convert_real_libreoffice(tmp_path):
    from openpyxl import Workbook

    xlsx = tmp_path / "real.xlsx"
    wb = Workbook()
    wb.active["A1"] = "hello"
    wb.save(xlsx)

    pdf = convert_to_pdf(xlsx)
    assert pdf.is_file()
    assert pdf.read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(
    sys.platform != "darwin" or find_soffice() is None,
    reason="需要 macOS 系统中文字体和 LibreOffice",
)
def test_convert_macos_keeps_chinese_missing_date_placeholder(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from pypdf import PdfReader

    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "需填: 出厂日期"
    sheet["A1"].font = Font(name="Arial", size=9)
    sheet.column_dimensions["A"].width = 30
    xlsx = tmp_path / "missing-date.xlsx"
    workbook.save(xlsx)
    workbook.close()

    pdf = convert_to_pdf(xlsx)
    assert "需填: 出厂日期" in PdfReader(pdf).pages[0].extract_text()
