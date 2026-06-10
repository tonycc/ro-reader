"""Packager：按命名规则（产品方案 §12.1）输出文件，支持 zip 打包。

文件命名（产品方案 §12.1）：
- PI: <SELLER>-RO-PI-<PO>.xlsx
- PO: <SELLER>-RO-PO-<PO>.xlsx
- Invoice: <SELLER>-RO-INVOICE-<PO>-<INVOICE_NO>.xlsx
- PL: <SELLER>-RO-PL-<PO>-<INVOICE_NO>.xlsx

zip 命名: RO-<PO>-<INVOICE_NO>.zip（无发票号则省略 -<INVOICE_NO>）

设计边界：
- packager 只负责"装配后的文件如何落盘和打包"，不调用 renderer
- 命名规则中的特殊字符（SK/YM 中的 /）替换为下划线，避免文件系统兼容问题
- on_conflict 策略沿用 DocumentRequest 的语义：overwrite / rename / abort
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from ro_generator.errors import InvalidRequestError
from ro_generator.models import DocumentType

OnConflict = Literal["overwrite", "rename", "abort"]


def build_document_filename(
    *,
    seller: str,
    document_type: DocumentType,
    po_no: str,
    invoice_no: str | None = None,
) -> str:
    seller_token = _sanitize(seller)
    po_token = _sanitize(po_no)
    base = f"{seller_token}-RO-{document_type}-{po_token}"
    if document_type in ("INVOICE", "PL") and invoice_no:
        base = f"{base}-{_sanitize(invoice_no)}"
    return f"{base}.xlsx"


def build_zip_filename(*, po_no: str, invoice_no: str | None = None) -> str:
    base = f"RO-{_sanitize(po_no)}"
    if invoice_no:
        base = f"{base}-{_sanitize(invoice_no)}"
    return f"{base}.zip"


def resolve_output_path(
    output_dir: str | Path,
    filename: str,
    *,
    on_conflict: OnConflict = "overwrite",
) -> Path:
    """按冲突策略决定最终输出路径。

    overwrite: 直接返回 output_dir/filename
    rename:    若已存在则追加 UTC 时间戳
    abort:     若已存在抛 InvalidRequestError
    """
    if on_conflict not in ("overwrite", "rename", "abort"):
        raise InvalidRequestError(f"未知的 on_conflict 值：{on_conflict!r}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename

    if not target.exists() or on_conflict == "overwrite":
        return target
    if on_conflict == "abort":
        raise InvalidRequestError(f"目标文件已存在：{target}")
    # rename
    stem = target.stem
    suffix = target.suffix
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return output_dir / f"{stem}-{timestamp}{suffix}"


def package_zip(
    *,
    files: tuple[Path, ...],
    output_dir: str | Path,
    zip_name: str,
    on_conflict: OnConflict = "overwrite",
) -> Path:
    """把多个文件打成 zip。文件以扁平结构（不带目录路径）放入 zip。

    files 元组中允许的同名重复会在 zip 内冲突，本函数不做去重——调用方应保证唯一。
    """
    if not files:
        raise InvalidRequestError("package_zip 至少需要一个文件")
    target = resolve_output_path(output_dir, zip_name, on_conflict=on_conflict)
    with ZipFile(target, mode="w", compression=ZIP_DEFLATED) as zf:
        for f in files:
            f = Path(f)
            if not f.exists():
                raise InvalidRequestError(f"package_zip 找不到文件：{f}")
            zf.write(f, arcname=f.name)
    return target.resolve()


def write_to_versioned_dir(
    base_output_dir: str | Path,
    *,
    timestamp: datetime | None = None,
) -> Path:
    """在 base_output_dir 下创建一个 YYYYMMDD-HHMMSS 子目录（产品方案 §12.2 工作台默认行为）。

    返回创建的子目录绝对路径。
    """
    ts = timestamp or datetime.now(UTC)
    folder = Path(base_output_dir) / ts.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve()


def copy_file(src: str | Path, dest: str | Path) -> Path:
    """简单文件拷贝助手，便于把渲染产物搬到不同目录。"""
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dest_path)
    return dest_path.resolve()


# —————————————————————————————————————
# Helpers
# —————————————————————————————————————

# 文件系统不友好的字符替换为下划线。SK/YM 中的 / 是核心目标。
_UNSAFE_CHARS_RE = re.compile(r"[\\/:*?\"<>|\s]+")


def _sanitize(token: str) -> str:
    """文件名安全化：替换 / \\ : 等不允许或不友好的字符。"""
    return _UNSAFE_CHARS_RE.sub("_", token.strip())


__all__ = [
    "OnConflict",
    "build_document_filename",
    "build_zip_filename",
    "copy_file",
    "package_zip",
    "resolve_output_path",
    "write_to_versioned_dir",
]
