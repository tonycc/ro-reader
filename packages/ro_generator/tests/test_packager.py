"""Packager 测试：文件名规则、冲突策略、zip 打包、版本目录。"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ro_generator.errors import InvalidRequestError
from ro_generator.packager import (
    build_document_filename,
    build_zip_filename,
    copy_file,
    package_zip,
    resolve_output_path,
    write_to_versioned_dir,
)

# ————————————————————————————————————————
# 文件名规则（产品方案 §12.1）
# ————————————————————————————————————————


class TestFilenameRules:
    def test_pi_no_month_suffix(self) -> None:
        name = build_document_filename(seller="GS PTE", document_type="PI", po_no="4500030844")
        assert name == "GS_PTE-RO-PI-4500030844.xlsx"

    def test_po_no_month_suffix(self) -> None:
        name = build_document_filename(seller="GS PTE", document_type="PO", po_no="4500030844")
        assert name == "GS_PTE-RO-PO-4500030844.xlsx"

    def test_invoice_with_month(self) -> None:
        name = build_document_filename(
            seller="GS PTE",
            document_type="INVOICE",
            po_no="4500030844",
            invoice_no="2601",
        )
        assert name == "GS_PTE-RO-INVOICE-4500030844-2601.xlsx"

    def test_pl_with_month(self) -> None:
        name = build_document_filename(
            seller="EMAX PTE",
            document_type="PL",
            po_no="4500030844",
            invoice_no="2602",
        )
        assert name == "EMAX_PTE-RO-PL-4500030844-2602.xlsx"

    def test_invoice_without_month_drops_suffix(self) -> None:
        name = build_document_filename(
            seller="GS PTE",
            document_type="INVOICE",
            po_no="4500030844",
        )
        assert name == "GS_PTE-RO-INVOICE-4500030844.xlsx"

    def test_pi_ignores_passed_month(self) -> None:
        # PI 永不带月份后缀
        name = build_document_filename(
            seller="GS PTE",
            document_type="PI",
            po_no="P",
            invoice_no="2601",
        )
        assert name == "GS_PTE-RO-PI-P.xlsx"

    def test_seller_with_slash_sanitized(self) -> None:
        # SK/YM 主体常出现，斜杠是文件系统不友好字符
        name = build_document_filename(
            seller="SK/YM", document_type="INVOICE", po_no="P", invoice_no="2601"
        )
        # SK/YM → SK_YM
        assert "/" not in name
        assert name.startswith("SK_YM-RO-INVOICE-")


class TestZipFilename:
    def test_zip_with_month(self) -> None:
        assert build_zip_filename(po_no="4500030844", invoice_no="2601") == (
            "RO-4500030844-2601.zip"
        )

    def test_zip_without_month(self) -> None:
        assert build_zip_filename(po_no="4500030844") == "RO-4500030844.zip"

    def test_zip_seller_independent(self) -> None:
        # zip 名只含 PO + 月份，不含 seller（产品方案 §12.1）
        name = build_zip_filename(po_no="4500030844", invoice_no="2602")
        assert "GS" not in name and "EMAX" not in name


# ————————————————————————————————————————
# 冲突策略
# ————————————————————————————————————————


class TestResolveOutputPath:
    def test_creates_output_dir(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "outputs" / "subdir"
        path = resolve_output_path(out_dir, "test.xlsx")
        assert out_dir.exists()
        assert path == out_dir / "test.xlsx"

    def test_overwrite_returns_same_path(self, tmp_path: Path) -> None:
        existing = tmp_path / "test.xlsx"
        existing.write_bytes(b"old")
        path = resolve_output_path(tmp_path, "test.xlsx", on_conflict="overwrite")
        assert path == existing

    def test_abort_raises_when_exists(self, tmp_path: Path) -> None:
        existing = tmp_path / "test.xlsx"
        existing.write_bytes(b"old")
        with pytest.raises(InvalidRequestError, match="已存在"):
            resolve_output_path(tmp_path, "test.xlsx", on_conflict="abort")

    def test_abort_ok_when_missing(self, tmp_path: Path) -> None:
        path = resolve_output_path(tmp_path, "test.xlsx", on_conflict="abort")
        assert path.name == "test.xlsx"

    def test_rename_appends_timestamp(self, tmp_path: Path) -> None:
        existing = tmp_path / "test.xlsx"
        existing.write_bytes(b"old")
        path = resolve_output_path(tmp_path, "test.xlsx", on_conflict="rename")
        assert path != existing
        assert path.name.startswith("test-")
        assert path.suffix == ".xlsx"
        # 应符合 stem-timestamp 格式
        assert "T" in path.stem and path.stem.endswith("Z")

    def test_rename_when_missing_no_timestamp(self, tmp_path: Path) -> None:
        # 不存在时 rename 直接返回原名（不需要时间戳）
        path = resolve_output_path(tmp_path, "test.xlsx", on_conflict="rename")
        assert path.name == "test.xlsx"

    def test_invalid_on_conflict_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError):
            resolve_output_path(tmp_path, "test.xlsx", on_conflict="bogus")  # type: ignore[arg-type]


# ————————————————————————————————————————
# Zip 打包
# ————————————————————————————————————————


class TestPackageZip:
    def test_packs_multiple_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.xlsx"
        f1.write_bytes(b"file a")
        f2 = tmp_path / "b.xlsx"
        f2.write_bytes(b"file b")
        out = tmp_path / "out"
        zip_path = package_zip(
            files=(f1, f2),
            output_dir=out,
            zip_name="bundle.zip",
        )
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            names = sorted(zf.namelist())
        assert names == ["a.xlsx", "b.xlsx"]

    def test_files_packed_flat_no_directory(self, tmp_path: Path) -> None:
        deep = tmp_path / "nested" / "deep" / "file.xlsx"
        deep.parent.mkdir(parents=True)
        deep.write_bytes(b"x")
        zip_path = package_zip(
            files=(deep,),
            output_dir=tmp_path / "out",
            zip_name="bundle.zip",
        )
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == ["file.xlsx"]

    def test_empty_files_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError, match="至少需要一个"):
            package_zip(files=(), output_dir=tmp_path, zip_name="z.zip")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError, match="找不到文件"):
            package_zip(
                files=(tmp_path / "nope.xlsx",),
                output_dir=tmp_path,
                zip_name="z.zip",
            )

    def test_conflict_strategy_applied(self, tmp_path: Path) -> None:
        f = tmp_path / "f.xlsx"
        f.write_bytes(b"x")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        existing = out_dir / "z.zip"
        existing.write_bytes(b"old")
        with pytest.raises(InvalidRequestError, match="已存在"):
            package_zip(
                files=(f,),
                output_dir=out_dir,
                zip_name="z.zip",
                on_conflict="abort",
            )


# ————————————————————————————————————————
# 版本目录（产品方案 §12.2）
# ————————————————————————————————————————


class TestVersionedDir:
    def test_creates_named_subdir(self, tmp_path: Path) -> None:
        ts = datetime(2026, 6, 2, 14, 23, 45, tzinfo=UTC)
        folder = write_to_versioned_dir(tmp_path, timestamp=ts)
        assert folder.name == "20260602-142345"
        assert folder.exists()
        assert folder.is_dir()

    def test_two_calls_with_different_timestamps_create_distinct_dirs(self, tmp_path: Path) -> None:
        a = write_to_versioned_dir(
            tmp_path,
            timestamp=datetime(2026, 6, 2, 10, 0, 0, tzinfo=UTC),
        )
        b = write_to_versioned_dir(
            tmp_path,
            timestamp=datetime(2026, 6, 2, 10, 0, 1, tzinfo=UTC),
        )
        assert a != b
        assert a.exists() and b.exists()


# ————————————————————————————————————————
# copy_file
# ————————————————————————————————————————


class TestCopyFile:
    def test_copies_to_new_path(self, tmp_path: Path) -> None:
        src = tmp_path / "a.xlsx"
        src.write_bytes(b"x")
        dest = tmp_path / "b.xlsx"
        out = copy_file(src, dest)
        assert out == dest.resolve()
        assert out.read_bytes() == b"x"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        src = tmp_path / "a.xlsx"
        src.write_bytes(b"x")
        dest = tmp_path / "deep" / "path" / "b.xlsx"
        out = copy_file(src, dest)
        assert out.exists()
