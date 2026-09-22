"""PF options sheet 价格版本规则的行级选价测试。

规则基准（与真实 PF base 文件一致）：
- PI 用客户PO "PO Creation Date" 在 {seller}-PI 键内 floor 匹配断点；
  BALANCE QTY=0 的已发货完成行不做版本选价，沿用 data_base_price_columns。
- Invoice 用 PO record "ACTUAL EX FACTORY" 在 {seller}-INV 键内匹配。
- 早于首断点/日期缺失 → 最早版本；晚于末断点 → 末版本。
- 版本标签与 DATA BASE 行1组标签严格字面匹配；组内取 COMBO 列。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from ro_generator.document_model import (
    CODE_COMPONENT_PRICE_MISSING,
    CODE_PRICE_VERSION_UNRESOLVED,
)
from ro_generator.generator import PreviewResult, preview_from_snapshot
from ro_generator.models import DocumentRequest, DocumentType
from ro_generator.price_options import (
    PriceBook,
    build_price_book,
    build_price_groups,
)
from ro_generator.profiles import GenerationContext, create_pf_profile
from ro_generator.resolver import ResolveResult, resolve_po_rows
from ro_generator.schema_inspect import inspect_schema
from ro_generator.workbook_reader import SheetData, WorkbookReader
from ro_generator.workbook_snapshot import (
    BuildSnapshotError,
    WorkbookSnapshot,
    build_workbook_snapshot,
)

# —————————————————————————————————————
# 合成 fixture
# —————————————————————————————————————

# DATA BASE 布局：行1 组标签 / 行2 表头 / 行3 数据。
# - F/G：SK/YM 的两个版本组
# - H/I：EMAX 的两个版本组（DDP价格7/8 无列，覆盖"版本无组"路径）
# - J：中间商价格4（单列 COMBO，无 ROD/REEL，用于验证组件价缺失告警）
# - K..M：中间商价格5（COMBO + ROD + REEL，供组件拆分跟随组验证）
# - N/O：中间商价格6/7、厂家价格6/7（NEW PO 版 COMBO，即 data_base_price_columns
#        的固定列，用于验证 PO 取价和 BALANCE QTY=0 的 PI 行不受 options 影响）
_DB_GROUP_LABELS = [
    None,
    None,
    None,
    None,
    None,
    "厂家价格4",
    "厂家价格5",
    "DDP价格5",
    "DDP价格6",
    "中间商价格4",
    "中间商价格5",
    None,
    None,
    "中间商价格6/7",
    "厂家价格6/7",
]
_DB_HEADERS = [
    "SAP",
    "Material Description",
    "Category",
    "round value",
    "MOQ",
    "GS-SK/YM COMBO FOB 2026",
    "GS-SK/YM COMBO FOB 20260612-OPO",
    "PF-EMAX COMBO DDP 2026 EFFECTIVE AS OF JUN/12/26-OPO",
    "PF-EMAX COMBO DDP 2026 EFFECTIVE AS OF JUN/12/26-NEW PO",
    "EMAX-GS COMBO FOB 2026 留下3%",
    "EMAX-GS COMBO FOB 20260612-OPO 留下3%",
    "EMAX-GS ROD FOB 20260612-OPO 留下3%",
    "EMAX-GS REEL FOB 20260612-OPO 留下3%",
    "EMAX-GS COMBO FOB 20260612-NEW PO 留下3%",
    "GS-SK/YM COMBO FOB 20260612-NEW PO",
]
_DB_VALUES = [
    "10001",
    "PF test item",
    "Single Rod",
    24,
    100,
    41,
    42,
    51,
    52,
    61,
    62,
    7,
    4,
    63,
    43,
]

_OPTIONS_HEADERS = [
    "EMAX-PI",
    "EMAX-PI取值",
    "GS-PI",
    "GS-PI取值",
    "SK/YM-PI",
    "SK/YM-PI取值",
    "EMAX-INV",
    "EMAX-INV取值",
    "GS-INV",
    "GS-INV取值字段",
    "SK/YM-INV",
    "SK/YM-INV取值",
]
# 断点结构与真实文件一致；EMAX-PI 的 0918 断点指向 fixture 中无对应组的
# 「DDP价格8」，覆盖"版本标签无匹配组"路径。
_OPTIONS_ROWS = [
    [
        20260612,
        "DDP价格6",
        20260612,
        "中间商价格4",
        20260612,
        "厂家价格4",
        20260612,
        "DDP价格5",
        20260612,
        "中间商价格4",
        20260612,
        "厂家价格4",
    ],
    [
        20260728,
        "DDP价格7",
        20260728,
        "中间商价格5",
        20260728,
        "厂家价格5",
        None,
        None,
        20260728,
        "中间商价格5",
        20260728,
        "厂家价格5",
    ],
    [20260918, "DDP价格8", None, None, None, None, None, None, None, None, None, None],
]


def _make_pf_base(
    tmp_path: Path,
    *,
    category: str = "Single Rod",
    po_creation_date: str = "2026-08-01",
    actual_ex_factory: str | None = "2026-09-15",
    balance_qty: object = None,
    options_rows: list[list[object]] | None = None,
    include_options: bool = True,
    blank_price_columns: tuple[str, ...] = (),
    drop_options_value_headers: tuple[str, ...] = (),
) -> Path:
    workbook = Workbook()
    data_base = workbook.active
    assert data_base is not None
    data_base.title = "DATA BASE TEMPLATE"
    data_base.append(_DB_GROUP_LABELS)
    data_base.append(_DB_HEADERS)
    data_base_values: list[object] = list(_DB_VALUES)
    data_base_values[2] = category
    for header in blank_price_columns:
        data_base_values[_DB_HEADERS.index(header)] = None
    data_base.append(data_base_values)

    po_record = workbook.create_sheet("PO RECORD 26")
    headers: list[object] = ["PO NO.", "ITEM LINE#", "SAP Number", "INV#", 2601]
    if actual_ex_factory is not None or balance_qty is not None:
        headers += ["ACTUAL EX FACTORY", "BALANCE QTY"]
    po_record.append(headers)
    row: list[object] = ["4500000001", 10, "10001", "G26010101", 90]
    if actual_ex_factory is not None or balance_qty is not None:
        row += [actual_ex_factory, balance_qty]
    po_record.append(row)

    customer_po = workbook.create_sheet("new PO template")
    customer_po.append(
        [
            "PO Creation Date",
            "PO#",
            "PO-Item",
            "Material",
            "Material Description",
            "PO requested ex-fty date",
            "Order Quantity",
        ]
    )
    customer_po.append(
        [po_creation_date, "4500000001", 10, "10001", "PF test item", "2026-09-01", 90]
    )

    if include_options:
        options = workbook.create_sheet("options")
        options_headers: list[object] = list(_OPTIONS_HEADERS)
        for key in drop_options_value_headers:
            # 清掉键列右邻的取值列表头：键仍在，但版本标签列失去表头
            options_headers[_OPTIONS_HEADERS.index(key) + 1] = None
        options.append(options_headers)
        for opt_row in options_rows if options_rows is not None else _OPTIONS_ROWS:
            options.append(opt_row)

    path = tmp_path / "pf-base.xlsx"
    workbook.save(path)
    return path


def _snapshot(base_file: Path) -> tuple[WorkbookSnapshot, GenerationContext]:
    profile = create_pf_profile()
    context = GenerationContext(profile=profile, base_file=base_file)
    return build_workbook_snapshot(str(base_file), context=context), context


def _resolve(snapshot: WorkbookSnapshot, context: GenerationContext) -> ResolveResult:
    return resolve_po_rows(
        snapshot.po_rows_for_po("4500000001"),
        snapshot.product_index,
        po_no="4500000001",
        customer_po_rows=snapshot.customer_po_rows_for_po("4500000001"),
        profile=context.profile,
        price_book=snapshot.price_book,
    )


def _preview(
    snapshot: WorkbookSnapshot,
    context: GenerationContext,
    seller: str,
    documents: tuple[DocumentType, ...],
) -> PreviewResult:
    request = DocumentRequest(
        base_file=str(context.base_path),
        po_no="4500000001",
        documents=documents,
        seller=seller,
        invoice_no="G26010101" if "INVOICE" in documents else None,
        output_dir=str(context.base_path.parent / "output"),
    )
    return preview_from_snapshot(snapshot, request, context=context)


# —————————————————————————————————————
# PriceBook 单元行为
# —————————————————————————————————————


def _pf_book(tmp_path: Path) -> PriceBook:
    base_file = _make_pf_base(tmp_path)
    profile = create_pf_profile()
    with WorkbookReader(str(base_file), schema=profile.schema) as reader:
        options_sheet = reader.read_sheet("options")
        group_labels = reader.read_group_labels("DATA BASE TEMPLATE")
        db_headers = reader.read_headers("DATA BASE TEMPLATE")
    config = profile.schema.price_options
    assert config is not None
    return build_price_book(
        options_sheet,
        group_labels,
        db_headers.header_columns,
        config,
        profile.schema,
    )


def test_price_groups_locate_combo_columns(tmp_path: Path) -> None:
    groups = _pf_book(tmp_path).groups
    assert groups["厂家价格4"].combo == "GS-SK/YM COMBO FOB 2026"
    assert groups["厂家价格5"].combo == "GS-SK/YM COMBO FOB 20260612-OPO"
    assert groups["中间商价格4"].combo == "EMAX-GS COMBO FOB 2026 留下3%"
    assert groups["中间商价格5"].combo == "EMAX-GS COMBO FOB 20260612-OPO 留下3%"
    assert groups["中间商价格5"].rod == "EMAX-GS ROD FOB 20260612-OPO 留下3%"
    assert groups["中间商价格5"].reel == "EMAX-GS REEL FOB 20260612-OPO 留下3%"
    ddp5_combo = groups["DDP价格5"].combo
    assert ddp5_combo is not None and ddp5_combo.startswith("PF-EMAX COMBO DDP")
    assert "DDP价格8" not in groups


def test_breakpoint_floor_matching(tmp_path: Path) -> None:
    book = _pf_book(tmp_path)
    # 恰好等于断点
    assert book.resolve("PI", "EMAX PTE", date(2026, 7, 28)).version_label == "DDP价格7"
    # 两断点之间 → floor
    assert book.resolve("PI", "EMAX PTE", date(2026, 8, 1)).version_label == "DDP价格7"
    # 早于首断点 → 最早版本
    assert book.resolve("PI", "EMAX PTE", date(2026, 1, 1)).version_label == "DDP价格6"
    # 晚于末断点 → 末版本
    hit = book.resolve("PI", "EMAX PTE", date(2027, 1, 1))
    assert hit.version_label == "DDP价格8"
    assert hit.kind == "missing"  # fixture 中无 DDP价格8 组
    # 日期缺失 → 最早版本
    hit = book.resolve("PI", "GS PTE", None)
    assert hit.version_label == "中间商价格4"
    assert hit.column == "EMAX-GS COMBO FOB 2026 留下3%"


def test_strict_label_matching_no_fuzzy(tmp_path: Path) -> None:
    """「厂家价格4」≠「厂家价格3/4」：字面不等即不命中。"""
    book = _pf_book(tmp_path)
    hit = book.resolve("PI", "SK", date(2026, 6, 12))
    assert hit.kind == "options"
    assert hit.column == "GS-SK/YM COMBO FOB 2026"
    # 组标签改为「厂家价格3/4」时，「厂家价格4」不得模糊命中
    groups = build_price_groups({6: "厂家价格3/4"}, {"GS-SK/YM COMBO FOB 2026": 6})
    book2 = PriceBook(
        options=book.options,
        groups=groups,
        seller_keys=book.seller_keys,
        doc_keys=book.doc_keys,
    )
    hit2 = book2.resolve("PI", "SK", date(2026, 6, 12))
    assert hit2.kind == "missing"
    assert hit2.version_label == "厂家价格4"


def test_options_missing_key_column_is_issue(tmp_path: Path) -> None:
    base_file = _make_pf_base(tmp_path)
    profile = create_pf_profile()
    with WorkbookReader(str(base_file), schema=profile.schema) as reader:
        options_sheet = reader.read_sheet("options")
        shrunk = SheetData(
            sheet_name=options_sheet.sheet_name,
            headers=tuple(h for h in options_sheet.headers if h != "EMAX-PI"),
            header_columns={
                h: c for h, c in options_sheet.header_columns.items() if h != "EMAX-PI"
            },
            rows=options_sheet.rows,
        )
        group_labels = reader.read_group_labels("DATA BASE TEMPLATE")
        db_headers = reader.read_headers("DATA BASE TEMPLATE")
    config = profile.schema.price_options
    assert config is not None
    book = build_price_book(
        shrunk,
        group_labels,
        db_headers.header_columns,
        config,
        profile.schema,
    )
    assert any("EMAX-PI" in issue for issue in book.issues)
    assert book.resolve("PI", "EMAX PTE", date(2026, 8, 1)).kind == "missing"


# —————————————————————————————————————
# 行级解析
# —————————————————————————————————————


def test_pi_unit_price_uses_po_creation_date_version(tmp_path: Path) -> None:
    """PI：PO Creation Date 2026-08-01 → GS-PI 命中 0728 断点 → 中间商价格5。"""
    snapshot, context = _snapshot(_make_pf_base(tmp_path))
    line = _resolve(snapshot, context).lines[0]
    assert line.price_sources[("PI", "GS PTE")].version_label == "中间商价格5"
    assert line.pi_prices[("GS PTE", "EMAX PTE")] == Decimal("62")
    # 静态固定列不被 PI 版本价污染（PO 取价来源）
    assert line.prices[("GS PTE", "EMAX PTE")] == Decimal("63")

    preview = _preview(snapshot, context, "GS PTE", ("PI",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    assert preview.preview.lines[0]["unit_price"] == "$62.00"
    source = {e["preview_field"]: e for e in preview.preview.source_entries}["line[0].unit_price"]
    assert source["field"] == "EMAX-GS COMBO FOB 20260612-OPO 留下3%"
    assert "中间商价格5" in str(source["rule"])


def test_pi_unit_price_before_first_breakpoint_uses_earliest(tmp_path: Path) -> None:
    snapshot, context = _snapshot(_make_pf_base(tmp_path, po_creation_date="2026-01-01"))
    line = _resolve(snapshot, context).lines[0]
    assert line.price_sources[("PI", "SK")].version_label == "厂家价格4"
    assert line.pi_prices[("SK", "YM")] == Decimal("41")
    assert line.prices[("SK", "YM")] == Decimal("43")


def test_invoice_unit_price_uses_actual_ex_factory(tmp_path: Path) -> None:
    """Invoice：ACTUAL EX FACTORY 2026-09-15 → GS-INV 命中 0728 → 中间商价格5。"""
    snapshot, context = _snapshot(_make_pf_base(tmp_path))
    line = _resolve(snapshot, context).lines[0]
    assert line.price_sources[("INVOICE", "GS PTE")].version_label == "中间商价格5"
    assert line.invoice_prices[("GS PTE", "EMAX PTE")] == Decimal("62")

    preview = _preview(snapshot, context, "GS PTE", ("INVOICE",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    assert preview.preview.lines[0]["unit_price"] == "$62.00"


def test_invoice_before_first_breakpoint_uses_earliest(tmp_path: Path) -> None:
    snapshot, context = _snapshot(_make_pf_base(tmp_path, actual_ex_factory="2026-01-01"))
    line = _resolve(snapshot, context).lines[0]
    assert line.price_sources[("INVOICE", "EMAX PTE")].version_label == "DDP价格5"
    assert line.invoice_prices[("EMAX PTE", "PF")] == Decimal("51")


def test_pi_balance_qty_zero_keeps_fixed_column(tmp_path: Path) -> None:
    """BALANCE QTY=0 的已发货完成行不做版本选价，沿用固定 NEW PO 列。"""
    snapshot, context = _snapshot(_make_pf_base(tmp_path, balance_qty=0))
    line = _resolve(snapshot, context).lines[0]
    assert line.price_sources[("PI", "GS PTE")].kind == "fixed"
    # 固定列 = data_base_price_columns 指向的 NEW PO 列（col N，值 63）
    assert line.prices[("GS PTE", "EMAX PTE")] == Decimal("63")
    # kind="fixed" 不做版本选价，pi_prices 不写入版本价
    assert ("GS PTE", "EMAX PTE") not in line.pi_prices
    # Invoice 不受 balance_qty 影响
    assert line.invoice_prices[("GS PTE", "EMAX PTE")] == Decimal("62")

    preview = _preview(snapshot, context, "GS PTE", ("PI",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    assert preview.preview.lines[0]["unit_price"] == "$63.00"
    source = {e["preview_field"]: e for e in preview.preview.source_entries}["line[0].unit_price"]
    assert source["field"] == "EMAX-GS COMBO FOB 20260612-NEW PO 留下3%"
    assert "BALANCE QTY" in str(source["rule"])


def test_missing_version_group_warns_and_price_empty(tmp_path: Path) -> None:
    """EMAX-PI 命中 DDP价格8（无对应组）→ 装配层告警 + PI 单价为空（不回退静态列）。

    版本解析失败属于单据级上下文：resolver 只记录 ResolvedPrice，告警在
    装配 EMAX PI 时才产生，不污染其他卖方/单据的预览。
    """
    snapshot, context = _snapshot(_make_pf_base(tmp_path, po_creation_date="2026-10-01"))
    result = _resolve(snapshot, context)
    line = result.lines[0]
    resolved = line.price_sources[("PI", "EMAX PTE")]
    assert resolved.kind == "missing"
    assert resolved.version_label == "DDP价格8"
    # resolver 不再在解析阶段产生版本告警
    assert not any(m.code == CODE_PRICE_VERSION_UNRESOLVED for m in result.messages)

    preview = _preview(snapshot, context, "EMAX PTE", ("PI",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    # 版本解析失败的行不沿用静态列旧值：单价置 0 并产生两类告警
    assert preview.preview.lines[0]["unit_price"] == "$0.00"
    warning_codes = {m.code for m in preview.warnings}
    assert "LINE_NOT_PRICED_FOR_SEGMENT" in warning_codes
    assert CODE_PRICE_VERSION_UNRESOLVED in warning_codes
    version_warnings = [m for m in preview.warnings if m.code == CODE_PRICE_VERSION_UNRESOLVED]
    assert version_warnings and "DDP价格8" in version_warnings[0].message
    # pi_prices 不留任何该段的版本价，静态列旧值也不被搬走
    assert ("EMAX PTE", "PF") not in line.pi_prices
    assert line.prices[("EMAX PTE", "PF")] == Decimal("52")


def test_missing_options_sheet_blocks_snapshot(tmp_path: Path) -> None:
    base_file = _make_pf_base(tmp_path, include_options=False)
    profile = create_pf_profile()
    context = GenerationContext(profile=profile, base_file=base_file)
    with pytest.raises(BuildSnapshotError, match="options"):
        build_workbook_snapshot(str(base_file), context=context)


def test_missing_options_key_header_blocks_snapshot(tmp_path: Path) -> None:
    base_file = _make_pf_base(tmp_path)
    workbook = load_workbook(base_file)
    options = workbook["options"]
    options["A1"] = "EMAX-PI-RENAMED"
    workbook.save(base_file)
    workbook.close()
    profile = create_pf_profile()
    context = GenerationContext(profile=profile, base_file=base_file)
    with pytest.raises(BuildSnapshotError, match="EMAX-PI"):
        build_workbook_snapshot(str(base_file), context=context)


def test_invoice_component_prices_follow_selected_group(tmp_path: Path) -> None:
    """GS Invoice 组件拆分列跟随所选版本组（组内 ROD/REEL 列）。

    ACTUAL EX FACTORY 2026-09-15 → GS-INV 命中 中间商价格5 组，
    ROD/REEL 组件价取组内 OPO 列（7/4），而非静态 NEW PO 配置列。
    """
    snapshot, context = _snapshot(_make_pf_base(tmp_path, category="Combo"))
    line = _resolve(snapshot, context).lines[0]
    assert line.resolved_component_prices["GS PTE/rod"] == Decimal("7")
    assert line.resolved_component_prices["GS PTE/reel"] == Decimal("4")

    preview = _preview(snapshot, context, "GS PTE", ("INVOICE",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    breakdown = preview.preview.cost_breakdown
    assert [item["component"] for item in breakdown] == ["RODS", "REELS"]
    assert breakdown[0]["unit_price"] == "$7.00"
    assert breakdown[1]["unit_price"] == "$4.00"


# —————————————————————————————————————
# 评审回归（6 项）
# —————————————————————————————————————


def test_pi_version_price_does_not_leak_into_po(tmp_path: Path) -> None:
    """PO 始终读静态固定列：SK/YM-PI 命中的版本价不得改变 GS PTE 的 PO 单价。

    回归：PI 版本价曾回写 line.prices，GS PTE 的 PO 输出 $42（SK/YM-PI 的
    OPO 版本价）而非静态 NEW PO 列的 $43。
    """
    snapshot, context = _snapshot(_make_pf_base(tmp_path))
    line = _resolve(snapshot, context).lines[0]
    # SK/YM-PI 命中 0728 断点 → 厂家价格5 → OPO 列 42；与 PO 段键相同
    assert line.pi_prices[("YM", "GS PTE")] == Decimal("42")
    # 同段键的静态列值（NEW PO 列）必须原样保留
    assert line.prices[("YM", "GS PTE")] == Decimal("43")

    preview = _preview(snapshot, context, "GS PTE", ("PO",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    assert preview.preview.lines[0]["unit_price"] == "$43.00"


def test_blank_selected_version_cell_does_not_fall_back(tmp_path: Path) -> None:
    """选中版本列但该 SAP 行单元格为空 → 缺价告警，不回退静态列旧价。

    回归：pi_prices 曾预填静态列值，选中列取空时静默沿用旧价 $63，
    而来源摘要却显示版本列。
    """
    snapshot, context = _snapshot(
        _make_pf_base(
            tmp_path,
            blank_price_columns=("EMAX-GS COMBO FOB 20260612-OPO 留下3%",),
        )
    )
    line = _resolve(snapshot, context).lines[0]
    resolved = line.price_sources[("PI", "GS PTE")]
    assert resolved.kind == "options"
    assert resolved.column == "EMAX-GS COMBO FOB 20260612-OPO 留下3%"
    # 选中列取空：pi_prices 不留值；静态列旧值留在 prices 供 PO，不被 PI 使用
    assert ("GS PTE", "EMAX PTE") not in line.pi_prices
    assert line.prices[("GS PTE", "EMAX PTE")] == Decimal("63")

    preview = _preview(snapshot, context, "GS PTE", ("PI",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    assert preview.preview.lines[0]["unit_price"] == "$0.00"
    assert "LINE_NOT_PRICED_FOR_SEGMENT" in {m.code for m in preview.warnings}


def test_price_version_warnings_scoped_to_document_and_seller(tmp_path: Path) -> None:
    """价格版本告警只出现在对应单据+卖方的装配结果里。

    回归：resolver 曾一次性产出所有卖方×单据族的告警，导致 GS PO 预览
    收到无关的 EMAX PI 版本缺失告警。
    """
    snapshot, context = _snapshot(_make_pf_base(tmp_path, po_creation_date="2026-10-01"))

    emax_pi = _preview(snapshot, context, "EMAX PTE", ("PI",))
    assert CODE_PRICE_VERSION_UNRESOLVED in {m.code for m in emax_pi.warnings}

    cases: tuple[tuple[str, tuple[DocumentType, ...]], ...] = (
        ("GS PTE", ("PI",)),
        ("GS PTE", ("PO",)),
        ("SK", ("PI",)),
    )
    for seller, documents in cases:
        preview = _preview(snapshot, context, seller, documents)
        codes = {m.code for m in preview.warnings}
        assert CODE_PRICE_VERSION_UNRESOLVED not in codes, (seller, documents)


def test_options_key_issue_is_not_remap_options(tmp_path: Path) -> None:
    """options 键列缺失标记为不可重映射。

    override 机制不支持 options 键列，修复向导不得提供保存后静默失效的列映射。
    """
    base_file = _make_pf_base(tmp_path)
    workbook = load_workbook(base_file)
    workbook["options"]["A1"] = "EMAX-PI-RENAMED"
    workbook.save(base_file)
    workbook.close()

    profile = create_pf_profile()
    with WorkbookReader(str(base_file), schema=profile.schema) as reader:
        inspection = inspect_schema(reader, profile.schema)
    options_issues = [
        issue for issue in inspection.field_issues if issue.logical_sheet == "options"
    ]
    assert options_issues, "应报告 EMAX-PI 键列缺失"
    assert any(issue.expected_header == "EMAX-PI" for issue in options_issues)
    assert all(issue.remappable is False for issue in options_issues)
    assert all(issue.repair_hint for issue in options_issues)


def test_missing_component_price_warns_on_combo_invoice(tmp_path: Path) -> None:
    """Combo Invoice 所选价格组缺 ROD/REEL 列 → 高优先级告警，不静默丢拆分。

    回归：组件价缺失时 cost_breakdown 曾直接为空且无告警，Invoice 显示
    success 却少了 RODS/REELS 两行。
    """
    snapshot, context = _snapshot(
        _make_pf_base(tmp_path, category="Combo", actual_ex_factory="2026-06-20")
    )
    line = _resolve(snapshot, context).lines[0]
    # 0612 断点 → 中间商价格4：组内只有 COMBO 列，无 ROD/REEL
    assert line.price_sources[("INVOICE", "GS PTE")].version_label == "中间商价格4"
    assert "GS PTE/rod" not in line.resolved_component_prices
    assert "GS PTE/reel" not in line.resolved_component_prices

    preview = _preview(snapshot, context, "GS PTE", ("INVOICE",))
    assert preview.status == "success", preview.errors
    assert preview.preview is not None
    # 主单价照常（COMBO 列有价），拆分区为空但必须有高优先级告警
    assert preview.preview.lines[0]["unit_price"] == "$61.00"
    assert not preview.preview.cost_breakdown
    component_warnings = [m for m in preview.warnings if m.code == CODE_COMPONENT_PRICE_MISSING]
    assert component_warnings, "缺组件价必须有告警"
    assert all(m.severity == "high" for m in component_warnings)
    assert any("RODS" in m.message for m in component_warnings)
    assert any("REELS" in m.message for m in component_warnings)


def test_missing_options_value_header_blocks_snapshot(tmp_path: Path) -> None:
    """options 键列右邻取值列表头缺失 → 结构校验阻断 snapshot。

    回归：此前该问题只进 PriceBook issues（低危告警），snapshot 成功后
    版本标签读不到，PI 静默输出 $0.00。
    """
    base_file = _make_pf_base(tmp_path, drop_options_value_headers=("EMAX-PI",))
    profile = create_pf_profile()
    context = GenerationContext(profile=profile, base_file=base_file)
    with pytest.raises(BuildSnapshotError, match="EMAX-PI"):
        build_workbook_snapshot(str(base_file), context=context)
