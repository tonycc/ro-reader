"""Phase 5.0 RO 行为基线。

这些断言锁定合成 fixture 当前的输入边界和核心结果，供 Profile/context 重构后回归。
真实 ``RO DATA BASE.xlsx`` 未入库，因此本文件不伪装成真实业务黄金输出快照。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import cast

from ro_generator.resolver import resolve_po_lines
from ro_generator.workbench_service import get_po_issues, inspect_workbook
from ro_generator.workbook_reader import WorkbookReader
from ro_generator.workbook_snapshot import PoInspection

FIXTURE = Path(__file__).parents[3] / "tests" / "fixtures" / "synthetic_base.xlsx"


def _inspection(po_no: str) -> PoInspection:
    result = inspect_workbook(str(FIXTURE))
    assert result.ok, result.errors
    return next(item for item in result.po_list if item.po_no == po_no)


def test_golden_po_inspection_contract_is_stable() -> None:
    """4500030844 的当前合成数据仍因缺客户 PO 行而阻断。"""

    item = _inspection("4500030844")

    assert item.status == "blocked"
    assert item.line_count == 2
    assert item.invoice_nos == ("INV-2601-001",)
    assert item.invoice_options_by_seller["GS PTE"] == ("INV-2601-001",)
    assert item.invoice_options_by_seller["EMAX PTE"] == ("INV-2601-001-P",)
    assert item.exportable_documents_by_seller["GS PTE"] == ("PI", "PO", "INVOICE_PL")
    assert item.blocking_count == 1


def test_golden_po_quantity_sources_are_stable() -> None:
    """PI/PO 数量取客户 PO，Invoice/PL 的出货数量取 PO record.SHIP QTY。"""

    with WorkbookReader(str(FIXTURE)) as reader:
        resolved = resolve_po_lines(reader, "4500030844")

    assert [line.sap for line in resolved.lines] == ["21-44640", "21-44641"]
    assert [line.quantity for line in resolved.lines] == [Decimal("240"), Decimal("120")]
    assert [line.ship_qty for line in resolved.lines] == [Decimal("100"), Decimal("60")]
    assert any(message.code == "QTY_MISSING" for message in resolved.messages)


def test_ready_po_contract_is_stable() -> None:
    item = _inspection("4500099999")

    assert item.status == "ready"
    assert item.line_count == 1
    assert item.invoice_nos == ("INV-2603-001",)
    assert item.invoice_options_by_seller["GS PTE"] == ("INV-2603-001",)
    assert item.invoice_options_by_seller["EMAX PTE"] == ("INV-2603-001-P",)
    assert item.blocking_count == 0


def test_missing_sap_blocking_contract_is_stable() -> None:
    issues = get_po_issues(str(FIXTURE), "4500088888")
    blocking_errors = cast(list[dict[str, object]], issues["blocking_errors"])

    assert issues["blocking_count"] == 1
    assert issues["warnings_count"] == 0
    assert blocking_errors[0]["code"] == "SAP_MISSING"
    assert blocking_errors[0]["sheet"] == "PO record"
