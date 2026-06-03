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

from ro_generator.document_model import (
    build_invoice_model,
    build_pi_model,
    build_pl_model,
    build_po_model,
)
from ro_generator.errors import RoGeneratorError, WorkbookOpenError
from ro_generator.models import (
    DocumentRequest,
    DocumentType,
    GenerationResult,
    ValidationMessage,
)
from ro_generator.packager import (
    build_document_filename,
    build_zip_filename,
    package_zip,
    resolve_output_path,
)
from ro_generator.renderer import render_document
from ro_generator.resolver import resolve_po_lines
from ro_generator.schema import (
    ENTITY_EMAX_PTE,
    ENTITY_GS_PTE,
    LEGAL_CHAIN_SEGMENTS,
    MONTH_COLUMNS,
    SELLER_TO_BUYER,
    SELLERS,
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
    # 1. 文档类型检查
    documents = tuple(d.upper() for d in request.documents)
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

    # 4. 推断 seller / buyer 或返回 needs_input/error
    seller, buyer, segment_messages = _resolve_segment(request, lines)
    if seller is None or buyer is None:
        blocking = tuple(m for m in segment_messages if m.kind == "blocking_error")
        if blocking:
            return GenerationResult(status="error", errors=blocking, warnings=warnings_resolver)
        return _needs_input(segment_messages, [INPUT_SELLER, INPUT_BUYER], request, lines)

    # 5. 推断 invoice_month
    invoice_month = request.invoice_month
    needs_month = any(d in ("INVOICE", "PL") for d in documents)
    if needs_month and invoice_month is None:
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
            # 自动选第一个月，加一条 warning 告知用户当前用的是哪个月
            invoice_month = candidates[0]["value"]
            warnings_resolver = warnings_resolver + (
                ValidationMessage(
                    kind="warning",
                    code="AUTO_SELECTED_MONTH",
                    severity="high",
                    message=f"PO {request.po_no} 存在多个月份的出货数据，已自动选择 {invoice_month} 月"
                    f"（{candidates[0]['label']}）。可点击月份切换。",
                ),
            )
        elif len(candidates) == 1:
            invoice_month = candidates[0]["value"]

    # 6. 同一 (po, month) 多个 INV# → needs_input
    invoiced_docs = [d for d in documents if d in ("INVOICE", "PL")]
    if invoiced_docs:
        distinct_invs = _collect_distinct_invoice_nos(lines, invoice_month)
        if len(distinct_invs) > 1 and request.invoice_no is None:
            return GenerationResult(
                status="needs_input",
                missing_inputs=("invoice_no",),
                options={"invoice_no": distinct_invs},
                warnings=warnings_resolver,
            )
        if request.invoice_no is not None:
            inv_values = {item["value"] for item in distinct_invs}
            if request.invoice_no not in inv_values:
                return _error_result(
                    ValidationMessage(
                        kind="blocking_error",
                        code="INVOICE_NO_NOT_FOUND",
                        message=(
                            f"指定的 INVOICE# {request.invoice_no!r} 在 PO"
                            f" {request.po_no} 中不存在"
                        ),
                    )
                )

    # 6. 逐个装配单据
    rendered_files: list[tuple[str, Path]] = []  # (filename, absolute_path)
    all_warnings = list(warnings_resolver)
    source_indices: list[SourceIndex] = []

    for doc_type in documents:
        doc_result = _generate_one(
            lines,
            seller=seller,
            buyer=buyer,
            po_no=request.po_no,
            invoice_month=invoice_month,
            doc_type=doc_type,  # type: ignore[arg-type]
            request=request,
        )
        if doc_result.status == "error":
            return GenerationResult(
                status="error",
                errors=doc_result.errors,
                warnings=tuple(all_warnings) + doc_result.warnings,
            )
        if doc_result.files and doc_result.output_file:
            rendered_files.append((doc_result.files[0], Path(doc_result.output_file)))
        if isinstance(doc_result.source_index, SourceIndex):
            source_indices.append(doc_result.source_index)
        all_warnings.extend(doc_result.warnings)

    # 7. Zip（多文件时）
    all_warnings_t = tuple(all_warnings)
    if len(rendered_files) == 1:
        filename, path = rendered_files[0]
        return GenerationResult(
            status="success",
            summary=_build_summary(request, seller, buyer, invoice_month, lines, documents),
            files=(filename,),
            output_file=str(path),
            warnings=all_warnings_t,
            source_index=source_indices[0] if source_indices else None,
        )

    if request.output_format == "zip":
        zip_name = build_zip_filename(
            po_no=request.po_no,
            invoice_month=invoice_month,
        )
        zip_path = package_zip(
            files=tuple(p for _, p in rendered_files),
            output_dir=request.output_dir,
            zip_name=zip_name,
            on_conflict=request.on_conflict,
        )
        filenames = tuple(fn for fn, _ in rendered_files)
        return GenerationResult(
            status="success",
            summary=_build_summary(request, seller, buyer, invoice_month, lines, documents),
            files=filenames,
            output_file=str(zip_path),
            warnings=all_warnings_t,
        )

    # 多文件、非 zip：各自落盘
    filenames = tuple(fn for fn, _ in rendered_files)
    return GenerationResult(
        status="success",
        summary=_build_summary(request, seller, buyer, invoice_month, lines, documents),
        files=filenames,
        output_file=str(Path(request.output_dir).resolve()),
        warnings=all_warnings_t,
    )


# —————————————————————————————————————
# 单文档装配
# —————————————————————————————————————

# 无 PO 模板的主体集合（仅 SK/YM 链段下不提供 PO）
ENTITIES_WITHOUT_PO: Final = {"SK", "YM", "SK/YM"}

# 卖方主体列表（供 UI）
ALL_SELLERS: Final = SELLERS


def _generate_one(
    lines: tuple,  # type: ignore[type-arg]
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_month: str | None,
    doc_type: DocumentType,
    request: DocumentRequest,
) -> GenerationResult:
    """为单个单据类型走完整装配流程并返回临时结果。"""

    # SK / YM 无 PO
    if doc_type == "PO" and seller in ENTITIES_WITHOUT_PO:
        return GenerationResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error",
                    code=CODE_MAPPING_NOT_FOUND,
                    message=f"{seller} 主体不提供 PO 模板（产品方案 §13.1）",
                ),
            ),
        )

    # 加载 mapping
    mapping = _load_mapping(seller, doc_type)
    if mapping is None:
        return GenerationResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error",
                    code=CODE_MAPPING_NOT_FOUND,
                    message=f"找不到 (seller={seller!r}, document={doc_type}) 对应的模板 mapping",
                ),
            ),
        )

    # 构建 model
    month_for_doc = invoice_month if doc_type in ("INVOICE", "PL") else None
    if doc_type == "PI":
        build_result = build_pi_model(lines, seller=seller, buyer=buyer, po_no=po_no)
    elif doc_type == "PO":
        build_result = build_po_model(lines, seller=seller, buyer=buyer, po_no=po_no)
    elif doc_type == "PL":
        build_result = build_pl_model(
            lines, seller=seller, buyer=buyer, po_no=po_no, invoice_month=month_for_doc,
        )
    else:
        build_result = build_invoice_model(
            lines, seller=seller, buyer=buyer, po_no=po_no, invoice_month=month_for_doc,
        )

    blocking = tuple(m for m in build_result.messages if m.kind == "blocking_error")
    doc_warnings = tuple(m for m in build_result.messages if m.kind == "warning")
    if build_result.model is None:
        return GenerationResult(status="error", errors=blocking, warnings=doc_warnings)

    # 渲染
    filename = build_document_filename(
        seller=seller,
        document_type=doc_type,
        po_no=po_no,
        invoice_month=month_for_doc,
    )
    output_path = resolve_output_path(
        request.output_dir, filename, on_conflict=request.on_conflict,
    )
    render_result = render_document(build_result.model, mapping, output_path)

    return GenerationResult(
        status="success",
        files=(filename,),
        output_file=str(render_result.output_path),
        warnings=doc_warnings,
        source_index=render_result.source_index,
        summary={"table_start_row": mapping.lines.start_row},
    )


def _build_summary(
    request: DocumentRequest,
    seller: str,
    buyer: str,
    invoice_month: str | None,
    lines: tuple,  # type: ignore[type-arg]
    documents: tuple[str, ...],
) -> dict[str, object]:
    return {
        "po_no": request.po_no,
        "documents": list(documents),
        "seller": seller,
        "buyer": buyer,
        "invoice_month": invoice_month,
        "line_count": len(lines),
    }


# —————————————————————————————————————
# Helpers
# —————————————————————————————————————


def _resolve_segment(
    request: DocumentRequest,
    lines: tuple,  # type: ignore[type-arg]
) -> tuple[str | None, str | None, tuple[ValidationMessage, ...]]:
    """决定使用哪个卖方主体。buyer 从 SELLER_TO_BUYER 自动推导。"""
    if request.seller:
        if request.seller not in SELLERS:
            return (
                None, None,
                (ValidationMessage(kind="blocking_error", code=CODE_UNSUPPORTED_SEGMENT,
                 message=f"未知卖方主体 {request.seller!r}，合法值：{SELLERS}"),),
            )
        buyer = SELLER_TO_BUYER.get(request.seller, "")
        return request.seller, buyer, ()

    # 未给定 seller → needs_input
    return None, None, ()


def _needs_input(
    base_messages: tuple[ValidationMessage, ...],
    inputs: list[str],
    request: DocumentRequest,
    lines: tuple,  # type: ignore[type-arg]
) -> GenerationResult:
    """构造 needs_input 结果。列出所有合法卖方主体候选。"""
    options: dict[str, tuple[dict[str, str], ...]] = {}
    if INPUT_SELLER in inputs:
        seller_options = tuple(
            {"value": s, "label": s} for s in SELLERS
        )
        options[INPUT_SELLER] = seller_options
    return GenerationResult(
        status="needs_input",
        missing_inputs=tuple(inputs),
        options=options,
        warnings=base_messages,
    )


def _collect_month_candidates(lines: tuple) -> tuple[dict[str, str], ...]:  # type: ignore[type-arg]
    totals: dict[str, int] = {}
    for line in lines:
        for month, qty in line.monthly_shipments.items():
            totals[month] = totals.get(month, 0) + int(qty)
    candidates: list[dict[str, str]] = []
    for month in MONTH_COLUMNS:
        if month not in totals:
            continue
        year = "2026"
        month_num = int(month[2:])
        label = f"{year} 年 {month_num} 月（出货 {totals[month]} 件）"
        candidates.append({"value": month, "label": label})
    return tuple(candidates)


def _collect_distinct_invoice_nos(
    lines: tuple,  # type: ignore[type-arg]
    invoice_month: str | None,
) -> tuple[dict[str, str], ...]:
    """收集 (po, month) 范围内所有不同的 INV#。

    返回 [{"value": "INV-001", "label": "INV-001"}, ...]。
    """
    seen: list[str] = []
    for line in lines:
        inv = line.invoice_no
        if not inv or inv in seen:
            continue
        # 如果有 invoice_month，只统计该月有出货的行的 INV#
        if invoice_month is not None:
            if invoice_month not in line.monthly_shipments:
                continue
        seen.append(inv)
    return tuple({"value": inv, "label": inv} for inv in seen)


def _load_mapping(seller: str, document: str) -> TemplateMapping | None:
    path = _builtin_mapping_path(seller, document)
    if path is None:
        return None
    return load_template_mapping(path)


def _error_result(*messages: ValidationMessage) -> GenerationResult:
    return GenerationResult(status="error", errors=messages)


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
