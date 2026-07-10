"""LibreOffice 无头转换：.xlsx → .pdf（像素级还原模板）。

像素级 PDF 导出不再用 reportlab 重画，而是：
  1. 用 renderer 把 DocumentModel 逐格填进 .xlsx 模板（见 renderer.py）；
  2. 交给用户机器上预装的 LibreOffice 无头模式转换为 PDF。

这样纸面与 Excel 模板完全一致（字体、列宽、行高、合并单元格、边框、logo、打印区）。

约束：LibreOffice 是原生程序、体积大，**不随应用打包**，要求用户机器预装；
未检测到时在导出阶段返回 SofficeNotFoundError（阻断错误），绝不静默降级。
可用环境变量 RO_SOFFICE_PATH 指定非标准安装位置的 soffice 路径。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ro_generator.errors import PdfConversionError, SofficeNotFoundError

# 允许用环境变量显式指定 soffice 路径（打包 / 测试 / 非标准安装位置）
_ENV_OVERRIDE = "RO_SOFFICE_PATH"

_CONVERT_TIMEOUT_SECONDS = 120.0


def _candidate_paths() -> list[Path]:
    """按平台返回 LibreOffice 可执行文件的常见安装位置。"""
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    elif sys.platform.startswith("win"):
        for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
            if root:
                candidates.append(Path(root) / "LibreOffice" / "program" / "soffice.exe")
    else:  # linux / 其他
        candidates.extend(
            [
                Path("/usr/bin/soffice"),
                Path("/usr/local/bin/soffice"),
                Path("/opt/libreoffice/program/soffice"),
            ]
        )
    return candidates


def find_soffice() -> Path | None:
    """定位 LibreOffice 可执行文件。

    顺序：环境变量 RO_SOFFICE_PATH → PATH 上的 soffice/libreoffice → 平台常见安装位置。
    找不到返回 None。
    """
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate
    return None


def convert_to_pdf(xlsx_path: str | Path, *, timeout: float = _CONVERT_TIMEOUT_SECONDS) -> Path:
    """用 LibreOffice 无头模式把 .xlsx 转成同名 .pdf，返回 pdf 路径。

    pdf 输出到 xlsx 所在目录，文件名为 ``<stem>.pdf``。
    未检测到 LibreOffice 抛 SofficeNotFoundError；转换失败抛 PdfConversionError。
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.is_file():
        raise PdfConversionError(f"待转换的 xlsx 不存在：{xlsx_path}")

    soffice = find_soffice()
    if soffice is None:
        raise SofficeNotFoundError(
            "未检测到 LibreOffice。像素级 PDF 导出需要在本机预装 LibreOffice，"
            "请安装后重试（或改用 Excel 导出）。"
            f"也可用环境变量 {_ENV_OVERRIDE} 指定 soffice 路径。"
        )

    out_dir = xlsx_path.parent
    # 每次转换用独立的 UserInstallation profile，避免与用户正在运行的 LibreOffice 实例抢锁。
    with tempfile.TemporaryDirectory(prefix="ro-soffice-") as profile_dir:
        cmd = [
            str(soffice),
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            f"-env:UserInstallation={Path(profile_dir).as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(xlsx_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError(
                f"LibreOffice 转换超时（>{timeout:.0f}s）：{xlsx_path.name}"
            ) from exc
        except OSError as exc:
            raise PdfConversionError(f"无法启动 LibreOffice：{exc}") from exc

    pdf_path = out_dir / f"{xlsx_path.stem}.pdf"
    if proc.returncode != 0 or not pdf_path.is_file():
        stderr = proc.stderr.decode("utf-8", "replace").strip() if proc.stderr else ""
        raise PdfConversionError(
            f"LibreOffice 转换失败（退出码 {proc.returncode}）：{xlsx_path.name}"
            + (f"；{stderr}" if stderr else "")
        )
    return pdf_path
