"""Generator：核心装配流水线。

串联：
  reader → validator → resolver → document_model → renderer → packager

调用方（CLI / 工作台后端）只需要传入 DocumentRequest，得到 GenerationResult。

Phase 1 范围：
- 只支持 INVOICE 单据类型；PI/PO/PL 在 Phase 2 加
- 只支持 GS PTE → EMAX PTE 链段（对应已实现的 templates/gs/mappings/invoice.yaml）；
  其他链段对应的 mapping 在 Phase 2 加

返回值约定（产品方案 §11）：
- status == "error"：阻断错误，errors 非空，不写文件
- status == "needs_input"：信息不足，missing_inputs/options 非空，不写文件
- status == "success"：files / output_file 非空，warnings 可能有
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Final

from ro_generator.document_model import build_invoice_model
from ro_generator.errors import RoGeneratorError, WorkbookOpenError
from ro_generator.models import (
    DocumentRequest,
    GenerationResult,
    ValidationMessage,
)
from ro_generator.packager import (
    build_document_filename,
    resolve_output_path,
)
from ro_generator.renderer import render_document
from ro_generator.resolver import resolve_po_lines
from ro_generator.schema import (
    ENTITY_EMAX_PTE,
    ENTITY_GS_PTE,
    LEGAL_CHAIN_SEGMENTS,
    MONTH_COLUMNS,
)
from ro_generator.source_index import SourceIndex
from ro_generator.template_mapping import TemplateMapping, load_template_mapping
from ro_generator.validator import validate_workbook_structure
from ro_generator.workbook_reader import WorkbookReader

# —————————————————————————————————————
# 校验消息 code（generator 层独有）
# —————————————————————————————————————

CODE_UNSUPPORTED_DOCUMENT: Final = "UNSUPPORTED_DOCUMENT_TYPE"
CODE_UNSUPPORTED_SEGMENT: Final = "UNSUPPORTED_CHAIN_SEGMENT"
CODE_MAPPING_NOT_FOUND: Final = "MAPPING_NOT_FOUND"

# 缺失输入的标识 code（用作 missing_inputs 元素）
INPUT_SELLER: Final = "seller"
INPUT_BUYER: Final = "buyer"
INPUT_INVOICE_MONTH: Final = "invoice_month"


# —————————————————————————————————————
# Phase 1 内置 mapping 注册表
# —————————————————————————————————————
#
# Phase 2 会替换为基于目录约定的动态查找（templates/<entity>/mappings/<doc>.yaml）。
# 这里先列硬编码以便测试。

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _builtin_mapping_path(seller: str, document: str) -> Path | None:
    """根据 (seller, document) 推断仓库内置 mapping 路径。

    Phase 1 只覆盖 GS PTE Invoice。
    """
    seller_dir = {
        "GS PTE": "gs",
        "EMAX PTE": "emax",
        "SK/YM": "sk",
        "SK": "sk",
        "YM": "ym",
    }.get(seller)
    if seller_dir is None:
        return None
    doc_file = {
        "PI": "pi.yaml",
        "PO": "po.yaml",
        "INVOICE": "invoice.yaml",
        "PL": "pl.yaml",
    }.get(document)
    if doc_file is None:
        return None
    candidate = _REPO_ROOT / "templates" / seller_dir / "mappings" / doc_file
    return candidate if candidate.exists() else None


# —————————————————————————————————————
# 主入口
# —————————————————————————————————————


def generate(request: DocumentRequest) -> GenerationResult:
    """运行装配流水线，返回统一结果。

    任何 RoGeneratorError 都被捕获并转成 status="error" 的结果，避免
    异常泄漏到调用方（CLI / 工作台后端）。
    """
    try:
        return _generate(request)
    except WorkbookOpenError as exc:
        return _error_result(
            ValidationMessage(
                kind="blocking_error",
                code=exc.code,
                message=exc.message,
            )
        )
    except RoGeneratorError as exc:
        return _error_result(
            ValidationMessage(
                kind="blocking_error",
                code=exc.code,
                message=exc.message,
            )
        )


def _generate(request: DocumentRequest) -> GenerationResult:
    # 1. 文档类型检查（Phase 1 只支持 INVOICE）
    documents = tuple(d.upper() for d in request.documents)
    unsupported = [d for d in documents if d != "INVOICE"]
    if unsupported:
        return _error_result(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_UNSUPPORTED_DOCUMENT,
                message=(
                    f"Phase 1 仅支持 INVOICE 单据类型；收到不支持的类型：{unsupported}。"
                    "PI/PO/PL 在 Phase 2 加入。"
                ),
            )
        )
    if not documents:
        return _error_result(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_UNSUPPORTED_DOCUMENT,
                message="documents 不能为空",
            )
        )

    # 2. 打开 workbook 并校验结构
    with WorkbookReader(request.base_file) as reader:
        struct_messages = validate_workbook_structure(reader)
        if struct_messages:
            return GenerationResult(
                status="error",
                errors=struct_messages,
            )

        # 3. 解析 PO
        resolve_result = resolve_po_lines(reader, request.po_no)

    blocking = tuple(m for m in resolve_result.messages if m.kind == "blocking_error")
    warnings_resolver = tuple(m for m in resolve_result.messages if m.kind == "warning")
    if blocking:
        return GenerationResult(
            status="error",
            errors=blocking,
            warnings=warnings_resolver,
        )

    lines = resolve_result.lines
    if not lines:
        return _error_result(
            ValidationMessage(
                kind="blocking_error",
                code="NO_LINES_RESOLVED",
                message=f"PO {request.po_no} 没有可装配的订单行",
            )
        )

    # 4. 推断 seller / buyer 或返回 needs_input
    seller, buyer, segment_messages = _resolve_segment(request, lines)
    if seller is None or buyer is None:
        # segment_messages 已是 needs_input 形态
        return _needs_input(segment_messages, [INPUT_SELLER, INPUT_BUYER], request, lines)

    # 5. 推断 invoice_month（仅 INVOICE/PL 需要）
    invoice_month = request.invoice_month
    if "INVOICE" in documents and invoice_month is None:
        candidates = _collect_month_candidates(lines)
        if len(candidates) == 0:
            return _error_result(
                ValidationMessage(
                    kind="blocking_error",
                    code="NO_MONTHLY_SHIPMENT",
                    message=f"PO {request.po_no} 没有任何月度出货数据",
                )
            )
        if len(candidates) > 1:
            return GenerationResult(
                status="needs_input",
                missing_inputs=(INPUT_INVOICE_MONTH,),
                options={INPUT_INVOICE_MONTH: candidates},
                warnings=warnings_resolver,
            )
        # 单个月份：自动选定
        invoice_month = candidates[0]["value"]

    # 6. 加载 mapping
    mapping = _load_mapping(seller, "INVOICE")
    if mapping is None:
        return _error_result(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_MAPPING_NOT_FOUND,
                message=(
                    f"找不到 (seller={seller!r}, document=INVOICE) 对应的模板 mapping。"
                    "Phase 1 仅支持 GS PTE。"
                ),
            )
        )

    # 7. 构建 document model
    invoice_result = build_invoice_model(
        lines,
        seller=seller,
        buyer=buyer,
        po_no=request.po_no,
        invoice_month=invoice_month,
    )
    invoice_blocking = tuple(m for m in invoice_result.messages if m.kind == "blocking_error")
    invoice_warnings = tuple(m for m in invoice_result.messages if m.kind == "warning")
    if invoice_result.model is None:
        return GenerationResult(
            status="error",
            errors=invoice_blocking,
            warnings=warnings_resolver + invoice_warnings,
        )

    # 8. 解析输出路径并渲染
    filename = build_document_filename(
        seller=seller,
        document_type="INVOICE",
        po_no=request.po_no,
        invoice_month=invoice_month,
    )
    output_path = resolve_output_path(
        request.output_dir,
        filename,
        on_conflict=request.on_conflict,
    )
    render_result = render_document(invoice_result.model, mapping, output_path)

    # 9. 装配最终结果
    summary: dict[str, object] = {
        "po_no": request.po_no,
        "documents": list(documents),
        "seller": seller,
        "buyer": buyer,
        "invoice_month": invoice_month,
        "line_count": len(invoice_result.model.lines),
        "total_quantity": str(invoice_result.model.total_quantity),
        "total_amount": str(invoice_result.model.total_amount),
    }
    return GenerationResult(
        status="success",
        summary=summary,
        files=(filename,),
        output_file=str(render_result.output_path),
        warnings=warnings_resolver + invoice_warnings,
        source_index=render_result.source_index,
    )


# —————————————————————————————————————
# Helpers
# —————————————————————————————————————


def _resolve_segment(
    request: DocumentRequest,
    lines: tuple,  # type: ignore[type-arg]
) -> tuple[str | None, str | None, tuple[ValidationMessage, ...]]:
    """决定使用哪个链段。

    优先级：
    - request.seller + request.buyer 都给定 → 校验后直接用
    - 都未给定但 lines 在所有链段下都有定价 → needs_input（产品方案 §11.3）
    - 都未给定但只有一段定价 → 自动选定
    """
    if request.seller and request.buyer:
        seg = (request.seller, request.buyer)
        if seg not in LEGAL_CHAIN_SEGMENTS:
            return (
                None,
                None,
                (
                    ValidationMessage(
                        kind="blocking_error",
                        code=CODE_UNSUPPORTED_SEGMENT,
                        message=f"链段 {request.seller}→{request.buyer} 不是合法链段",
                    ),
                ),
            )
        return request.seller, request.buyer, ()

    # 推断：哪些链段在所有行上都有定价
    available = _segments_with_full_coverage(lines)
    if not available:
        return (
            None,
            None,
            (
                ValidationMessage(
                    kind="blocking_error",
                    code="NO_PRICED_SEGMENT",
                    message="所有合法链段下都至少有一行无定价，无法选定单据链段",
                ),
            ),
        )
    if len(available) == 1:
        return available[0][0], available[0][1], ()

    # 多个候选 → needs_input
    return None, None, ()


def _segments_with_full_coverage(lines: tuple) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    out: list[tuple[str, str]] = []
    for seg in LEGAL_CHAIN_SEGMENTS:
        if all(seg in line.prices for line in lines):
            out.append(seg)
    return out


def _collect_month_candidates(lines: tuple) -> tuple[dict[str, str], ...]:  # type: ignore[type-arg]
    """收集所有有出货数据的月份，按月份代码排序。

    返回 [{"value": "2601", "label": "2026 年 1 月（出货 240 件）"}, ...]。
    """
    totals: dict[str, int] = {}
    for line in lines:
        for month, qty in line.monthly_shipments.items():
            totals[month] = totals.get(month, 0) + int(qty)
    candidates: list[dict[str, str]] = []
    for month in MONTH_COLUMNS:
        if month not in totals:
            continue
        year = "2026"  # MVP 仅 2026 年
        month_num = int(month[2:])
        label = f"{year} 年 {month_num} 月（出货 {totals[month]} 件）"
        candidates.append({"value": month, "label": label})
    return tuple(candidates)


def _load_mapping(seller: str, document: str) -> TemplateMapping | None:
    path = _builtin_mapping_path(seller, document)
    if path is None:
        return None
    return load_template_mapping(path)


def _error_result(*messages: ValidationMessage) -> GenerationResult:
    return GenerationResult(status="error", errors=messages)


def _needs_input(
    base_messages: tuple[ValidationMessage, ...],
    inputs: list[str],
    request: DocumentRequest,
    lines: tuple,  # type: ignore[type-arg]
) -> GenerationResult:
    """构造 needs_input 结果。

    Phase 1 简化：只列出"哪些是合法链段候选"，UI 用此作为多选项。
    """
    available = _segments_with_full_coverage(lines)
    options: dict[str, tuple[dict[str, str], ...]] = {}
    if INPUT_SELLER in inputs and available:
        seller_options = tuple({"value": s, "label": f"{s} → {b}"} for s, b in available)
        options[INPUT_SELLER] = seller_options
    return GenerationResult(
        status="needs_input",
        missing_inputs=tuple(inputs),
        options=options,
        warnings=base_messages,
    )


# 保留导出 for IDE / 测试方便
_ = (replace, ENTITY_GS_PTE, ENTITY_EMAX_PTE, SourceIndex)


__all__ = [
    "CODE_MAPPING_NOT_FOUND",
    "CODE_UNSUPPORTED_DOCUMENT",
    "CODE_UNSUPPORTED_SEGMENT",
    "INPUT_BUYER",
    "INPUT_INVOICE_MONTH",
    "INPUT_SELLER",
    "generate",
]
