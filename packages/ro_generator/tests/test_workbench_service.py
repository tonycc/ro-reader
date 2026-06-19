"""workbench_service 测试：PO 列表检查与状态判定。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

from ro_generator.workbench_service import (
    ExportDocumentGroup,
    export_document_groups,
    get_po_issues,
    inspect_workbook,
)

FIXTURE = Path(__file__).parents[3] / "tests" / "fixtures" / "synthetic_base.xlsx"


def test_inspect_workbook_returns_ok_and_po_list() -> None:
    result = inspect_workbook(str(FIXTURE))
    assert result.ok
    assert len(result.po_list) >= 1
    po_nos = {p.po_no for p in result.po_list}
    assert "4500099999" in po_nos


def test_inspect_workbook_blocked_po() -> None:
    result = inspect_workbook(str(FIXTURE))
    blocked = [p for p in result.po_list if p.status == "blocked"]
    assert len(blocked) >= 1
    assert any(p.po_no == "4500088888" for p in blocked)


def test_inspect_workbook_ready_po() -> None:
    result = inspect_workbook(str(FIXTURE))
    ready = [p for p in result.po_list if p.status == "ready"]
    assert len(ready) >= 1
    assert any(p.po_no == "4500099999" for p in ready)


def test_inspect_workbook_has_sellers() -> None:
    result = inspect_workbook(str(FIXTURE))
    for p in result.po_list:
        assert len(p.sellers) >= 1
        assert "GS PTE" in p.sellers


def test_po_inspection_fields() -> None:
    result = inspect_workbook(str(FIXTURE))
    for p in result.po_list:
        assert p.po_no
        assert p.status in ("ready", "partial", "blocked")
        assert p.line_count >= 0
        assert p.blocking_count >= 0


def test_missing_file_returns_error() -> None:
    result = inspect_workbook("/nonexistent/file.xlsx")
    assert not result.ok
    assert len(result.errors) >= 1


def test_get_po_issues_returns_blocking_details() -> None:
    issues = cast(dict[str, Any], get_po_issues(str(FIXTURE), "4500088888"))

    assert issues["po_no"] == "4500088888"
    assert issues["blocking_count"] >= 1
    assert issues["warnings_count"] >= 0
    assert issues["blocking_errors"]
    first = issues["blocking_errors"][0]
    assert first["kind"] == "blocking_error"
    assert first["code"]
    assert first["message"]
    assert "sheet" in first
    assert "field" in first


def test_get_po_issues_returns_empty_for_ready_po() -> None:
    issues = cast(dict[str, Any], get_po_issues(str(FIXTURE), "4500099999"))

    assert issues["po_no"] == "4500099999"
    assert issues["blocking_count"] == 0
    assert issues["blocking_errors"] == []


def test_export_document_groups_returns_single_zip(tmp_path: Path) -> None:
    result = export_document_groups(
        base_file=str(FIXTURE),
        po_no="4500099999",
        output_dir=str(tmp_path),
        groups=(
            ExportDocumentGroup(seller="GS PTE", documents=("PI",)),
            ExportDocumentGroup(seller="EMAX PTE", documents=("PI",)),
        ),
    )

    assert result.status == "success"
    assert result.output_file is not None
    assert result.output_file.endswith(".zip")
    assert result.files == (
        "GS_PTE-RO-PI-4500099999.xlsx",
        "EMAX_PTE-RO-PI-4500099999.xlsx",
    )
    with ZipFile(result.output_file) as zf:
        assert sorted(zf.namelist()) == sorted(result.files)
