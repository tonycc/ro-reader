"""pdf_convert 单元测试。

真实 LibreOffice 转换只在本机装了 soffice 时跑（skipif 守卫）；其余用例通过
monkeypatch find_soffice / subprocess.run 在无 soffice 环境（含 CI）下验证逻辑。
"""

from __future__ import annotations

import types
from pathlib import Path

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
