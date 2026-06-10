"""Generator：核心装配流水线。

串联：
  reader → validator → resolver → document_model → renderer → packager

调用方（CLI / 工作台后端）只需要传入 DocumentRequest，得到 GenerationResult。

支持四类单据（PI / PO / Invoice / PL）× 四类主体（GS / EMAX / SK / YM）。

返回值约定（产品方案 §11）：
- status == "error"：阻断错误，errors 非空，不写文件
- status == "needs_input"：信息不足，missing_inputs/options 非空，不写文件
- status == "success"：files / output_file 非空，warnings 可能有
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from dataclasses import dataclass, field

from ro_generator.document_model import (
    DocumentModel,
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
from ro_generator.resolver import resolve_po_lines, resolve_po_rows
from ro_generator.resources import resource_root
from ro_generator.schema import (
    SELLER_TO_BUYER,
    SELLERS,
)
from ro_generator.source_index import SourceIndex
from ro_generator.template_mapping import TemplateMapping, load_template_mapping
from ro_generator.validator import validate_workbook_structure
from ro_generator.workbook_reader import WorkbookReader

# —————————————————————————————————————
# 校验消息 code
# —————————————————————————————————————

@dataclass(frozen=True)
class BuildDocumentResult:
    """单文档模型构建结果。model 为 None 时表示阻断错误。"""

    model: DocumentModel | None
    mapping: TemplateMapping | None
    messages: tuple[ValidationMessage, ...]


@dataclass(frozen=True)
class PreviewResult:
    """预览结果。不包含 output_file，不经过 Excel renderer。"""

    status: str  # success | error | needs_input
    preview: object | None = None  # DocumentPreview
    errors: tuple[ValidationMessage, ...] = ()
    warnings: tuple[ValidationMessage, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    options: dict[str, object] = field(default_factory=dict)


CODE_UNSUPPORTED_DOCUMENT: Final = "UNSUPPORTED_DOCUMENT_TYPE"
CODE_UNSUPPORTED_SEGMENT: Final = "UNSUPPORTED_CHAIN_SEGMENT"
CODE_MAPPING_NOT_FOUND: Final = "MAPPING_NOT_FOUND"

INPUT_SELLER: Final = "seller"
INPUT_BUYER: Final = "buyer"
INPUT_INVOICE_NO: Final = "invoice_no"


# —————————————————————————————————————
# 内置 mapping 注册表
# —————————————————————————————————————

_REPO_ROOT = resource_root()


def builtin_mapping_path(seller: str, document: str) -> Path | None:
    seller_dir = {
        "GS PTE": "gs",
        "EMAX PTE": "emax",
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
    try:
        return _generate(request)
    except WorkbookOpenError as exc:
        return _error_result(
            ValidationMessage(kind="blocking_error", code=exc.code, message=exc.message)
        )
    except RoGeneratorError as exc:
        return _error_result(
            ValidationMessage(kind="blocking_error", code=exc.code, message=exc.message)
        )


def preview(request: DocumentRequest) -> "PreviewResult":
    """生成预览数据，不写 Excel。复用与 generate() 相同的 resolver 和 DocumentModel 构建路径。

    只处理单文档。不调用 render_document()。
    """
    from ro_generator.document_preview import DocumentPreview, build_preview

    try:
        return _preview(request)
    except WorkbookOpenError as exc:
        return PreviewResult(
            status="error",
            errors=(ValidationMessage(kind="blocking_error", code=exc.code, message=exc.message),),
        )
    except RoGeneratorError as exc:
        return PreviewResult(
            status="error",
            errors=(ValidationMessage(kind="blocking_error", code=exc.code, message=exc.message),),
        )


def _preview(request: DocumentRequest) -> "PreviewResult":
    from ro_generator.document_preview import DocumentPreview, build_preview

    documents = tuple(d.upper() for d in request.documents)
    if not documents:
        return PreviewResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error", code=CODE_UNSUPPORTED_DOCUMENT,
                    message="documents 不能为空",
                ),
            ),
        )
    doc_type = documents[0]  # preview 只处理单文档

    with WorkbookReader(request.base_file) as reader:
        struct_messages = validate_workbook_structure(reader)
        if struct_messages:
            return PreviewResult(status="error", errors=struct_messages)
        resolve_result = resolve_po_lines(reader, request.po_no)

    blocking = tuple(m for m in resolve_result.messages if m.kind == "blocking_error")
    warnings_resolver = tuple(m for m in resolve_result.messages if m.kind == "warning")
    if blocking:
        return PreviewResult(status="error", errors=blocking, warnings=warnings_resolver)

    lines = resolve_result.lines
    if not lines:
        return PreviewResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error", code="NO_LINES_RESOLVED",
                    message=f"PO {request.po_no} 没有可装配的订单行",
                ),
            ),
        )

    # 推断 seller / buyer
    seller, buyer, segment_messages = _resolve_segment(request, lines)
    if seller is None or buyer is None:
        blocking = tuple(m for m in segment_messages if m.kind == "blocking_error")
        if blocking:
            return PreviewResult(status="error", errors=blocking, warnings=warnings_resolver)
        # needs_input — 返回可选的 seller 列表
        options: dict[str, tuple[dict[str, str], ...]] = {}
        if INPUT_SELLER in [m.code for m in segment_messages if hasattr(m, 'code')]:
            options[INPUT_SELLER] = tuple({"value": s, "label": s} for s in SELLERS)
        return PreviewResult(
            status="needs_input",
            missing_inputs=tuple(INPUT_SELLER if INPUT_SELLER in [m.code for m in segment_messages if hasattr(m, 'code')] else ()),  # type: ignore[arg-type]
            options=options,
            warnings=warnings_resolver,
        )

    # Invoice/PL 需要 INV#
    invoice_no = request.invoice_no
    if doc_type in ("INVOICE", "PL"):
        distinct_invs = _collect_distinct_invoice_nos(lines)
        if len(distinct_invs) > 1 and invoice_no is None:
            return PreviewResult(
                status="needs_input",
                missing_inputs=(INPUT_INVOICE_NO,),
                options={"invoice_no": distinct_invs},
                warnings=warnings_resolver,
            )
        if invoice_no is not None:
            inv_values = {item["value"] for item in distinct_invs}
            if invoice_no not in inv_values:
                return PreviewResult(
                    status="error",
                    errors=(
                        ValidationMessage(
                            kind="blocking_error", code="INVOICE_NO_NOT_FOUND",
                            message=f"指定的 INVOICE# {invoice_no!r} 在 PO {request.po_no} 中不存在",
                        ),
                    ),
                )
        if len(distinct_invs) == 1 and invoice_no is None:
            invoice_no = distinct_invs[0]["value"]

    # 构建 DocumentModel
    build = build_document_model(
        lines, seller=seller, buyer=buyer, po_no=request.po_no,
        invoice_no=invoice_no, doc_type=doc_type,  # type: ignore[arg-type]
    )

    all_warnings = list(warnings_resolver)
    doc_warnings = tuple(m for m in build.messages if m.kind == "warning")
    all_warnings.extend(doc_warnings)

    preview_data = build_preview(build)

    return PreviewResult(
        status="success" if build.model is not None else "error",
        preview=preview_data if build.model is not None else None,
        errors=tuple(m for m in build.messages if m.kind == "blocking_error"),
        warnings=tuple(all_warnings),
    )


def preview_from_snapshot(
    snapshot: object,  # WorkbookSnapshot
    request: DocumentRequest,
) -> "PreviewResult":
    """基于缓存的 WorkbookSnapshot 生成预览，不读 Excel。

    与 preview() 的区别：绕过 WorkbookReader，直接从 snapshot 获取 PO 行和产品索引。
    seller / buyer 推断、invoice_no 校验、DocumentModel 构建与 preview() 相同。
    """
    from ro_generator.document_preview import build_preview
    from ro_generator.workbook_snapshot import WorkbookSnapshot

    snap: WorkbookSnapshot = snapshot  # type: ignore[assignment]

    documents = tuple(d.upper() for d in request.documents)
    if not documents:
        return PreviewResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error", code=CODE_UNSUPPORTED_DOCUMENT,
                    message="documents 不能为空",
                ),
            ),
        )
    doc_type = documents[0]

    # 从 snapshot 获取 PO 行和产品索引
    rows = snap.po_rows_for_po(request.po_no)
    if not rows:
        return PreviewResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error", code="PO_NOT_FOUND",
                    message=f"PO 号 {request.po_no!r} 在 PO record 中不存在",
                ),
            ),
        )

    # 解析订单行
    resolve_result = resolve_po_rows(
        rows,
        snap.product_index,
        po_no=request.po_no,
        customer_po_rows=snap.customer_po_rows_for_po(request.po_no),
    )
    blocking = tuple(m for m in resolve_result.messages if m.kind == "blocking_error")
    warnings_resolver = tuple(m for m in resolve_result.messages if m.kind == "warning")
    if blocking:
        return PreviewResult(status="error", errors=blocking, warnings=warnings_resolver)

    lines = resolve_result.lines
    if not lines:
        return PreviewResult(
            status="error",
            errors=(
                ValidationMessage(
                    kind="blocking_error", code="NO_LINES_RESOLVED",
                    message=f"PO {request.po_no} 没有可装配的订单行",
                ),
            ),
        )

    # 推断 seller / buyer
    seller, buyer, segment_messages = _resolve_segment(request, lines)
    if seller is None or buyer is None:
        blocking = tuple(m for m in segment_messages if m.kind == "blocking_error")
        if blocking:
            return PreviewResult(status="error", errors=blocking, warnings=warnings_resolver)
        options: dict[str, tuple[dict[str, str], ...]] = {}
        options[INPUT_SELLER] = tuple({"value": s, "label": s} for s in SELLERS)
        return PreviewResult(
            status="needs_input",
            missing_inputs=(INPUT_SELLER,),  # type: ignore[arg-type]
            options=options,
            warnings=warnings_resolver,
        )

    # Invoice/PL 需要 INV#
    invoice_no = request.invoice_no
    if doc_type in ("INVOICE", "PL"):
        distinct_invs = _collect_distinct_invoice_nos(lines)
        if len(distinct_invs) > 1 and invoice_no is None:
            return PreviewResult(
                status="needs_input",
                missing_inputs=(INPUT_INVOICE_NO,),
                options={"invoice_no": distinct_invs},
                warnings=warnings_resolver,
            )
        if invoice_no is not None:
            inv_values = {item["value"] for item in distinct_invs}
            if invoice_no not in inv_values:
                return PreviewResult(
                    status="error",
                    errors=(
                        ValidationMessage(
                            kind="blocking_error", code="INVOICE_NO_NOT_FOUND",
                            message=f"指定的 INVOICE# {invoice_no!r} 在 PO {request.po_no} 中不存在",
                        ),
                    ),
                )
        if len(distinct_invs) == 1 and invoice_no is None:
            invoice_no = distinct_invs[0]["value"]

    # 构建 DocumentModel
    build = build_document_model(
        lines, seller=seller, buyer=buyer, po_no=request.po_no,
        invoice_no=invoice_no, doc_type=doc_type,  # type: ignore[arg-type]
    )

    all_warnings = list(warnings_resolver)
    doc_warnings = tuple(m for m in build.messages if m.kind == "warning")
    all_warnings.extend(doc_warnings)

    preview_data = build_preview(build)

    return PreviewResult(
        status="success" if build.model is not None else "error",
        preview=preview_data if build.model is not None else None,
        errors=tuple(m for m in build.messages if m.kind == "blocking_error"),
        warnings=tuple(all_warnings),
    )


def _generate(request: DocumentRequest) -> GenerationResult:
    documents = tuple(d.upper() for d in request.documents)
    if not documents:
        return _error_result(
            ValidationMessage(
                kind="blocking_error", code=CODE_UNSUPPORTED_DOCUMENT,
                message="documents 不能为空",
            )
        )

    with WorkbookReader(request.base_file) as reader:
        struct_messages = validate_workbook_structure(reader)
        if struct_messages:
            return GenerationResult(status="error", errors=struct_messages)
        resolve_result = resolve_po_lines(reader, request.po_no)

    blocking = tuple(m for m in resolve_result.messages if m.kind == "blocking_error")
    warnings_resolver = tuple(m for m in resolve_result.messages if m.kind == "warning")
    if blocking:
        return GenerationResult(status="error", errors=blocking, warnings=warnings_resolver)

    lines = resolve_result.lines
    if not lines:
        return _error_result(
            ValidationMessage(
                kind="blocking_error", code="NO_LINES_RESOLVED",
                message=f"PO {request.po_no} 没有可装配的订单行",
            )
        )

    # 推断 seller / buyer
    seller, buyer, segment_messages = _resolve_segment(request, lines)
    if seller is None or buyer is None:
        blocking = tuple(m for m in segment_messages if m.kind == "blocking_error")
        if blocking:
            return GenerationResult(status="error", errors=blocking, warnings=warnings_resolver)
        return _needs_input(segment_messages, [INPUT_SELLER, INPUT_BUYER], lines)

    # Invoice/PL 需要 INV# — 如果多行有不同 INV#，要求用户选择
    invoice_no = request.invoice_no
    invoiced_docs = [d for d in documents if d in ("INVOICE", "PL")]
    if invoiced_docs:
        distinct_invs = _collect_distinct_invoice_nos(lines)
        if len(distinct_invs) > 1 and invoice_no is None:
            return GenerationResult(
                status="needs_input",
                missing_inputs=(INPUT_INVOICE_NO,),
                options={"invoice_no": distinct_invs},
                warnings=warnings_resolver,
            )
        if invoice_no is not None:
            inv_values = {item["value"] for item in distinct_invs}
            if invoice_no not in inv_values:
                return _error_result(
                    ValidationMessage(
                        kind="blocking_error", code="INVOICE_NO_NOT_FOUND",
                        message=f"指定的 INVOICE# {invoice_no!r} 在 PO {request.po_no} 中不存在",
                    )
                )
        if len(distinct_invs) == 1 and invoice_no is None:
            invoice_no = distinct_invs[0]["value"]

    # 逐个装配单据
    rendered_files: list[tuple[str, Path]] = []
    all_warnings = list(warnings_resolver)
    source_indices: list[SourceIndex] = []
    last_summary: dict[str, object] = {}

    for doc_type in documents:
        doc_result = _generate_one(
            lines, seller=seller, buyer=buyer, po_no=request.po_no,
            invoice_no=invoice_no, doc_type=doc_type,  # type: ignore[arg-type]
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
        last_summary = doc_result.summary

    all_warnings_t = tuple(all_warnings)
    if len(rendered_files) == 1:
        filename, path = rendered_files[0]
        return GenerationResult(
            status="success",
            summary=_build_summary(request, seller, buyer, lines, documents, invoice_no=invoice_no, extra=last_summary),
            files=(filename,),
            output_file=str(path),
            warnings=all_warnings_t,
            source_index=source_indices[0] if source_indices else None,
        )

    if request.output_format == "zip":
        zip_name = build_zip_filename(po_no=request.po_no, invoice_no=invoice_no)
        zip_path = package_zip(
            files=tuple(p for _, p in rendered_files),
            output_dir=request.output_dir,
            zip_name=zip_name,
            on_conflict=request.on_conflict,
        )
        filenames = tuple(fn for fn, _ in rendered_files)
        return GenerationResult(
            status="success",
            summary=_build_summary(request, seller, buyer, lines, documents, invoice_no=invoice_no),
            files=filenames, output_file=str(zip_path), warnings=all_warnings_t,
        )

    filenames = tuple(fn for fn, _ in rendered_files)
    return GenerationResult(
        status="success",
        summary=_build_summary(request, seller, buyer, lines, documents, invoice_no=invoice_no),
        files=filenames,
        output_file=str(Path(request.output_dir).resolve()),
        warnings=all_warnings_t,
    )


# —————————————————————————————————————
# 单文档模型构建（export 和 preview 共用）
# —————————————————————————————————————

ENTITIES_WITHOUT_PO: Final = {"SK", "YM"}


def build_document_model(
    lines: tuple,  # type: ignore[type-arg]
    *,
    seller: str,
    buyer: str,
    po_no: str,
    invoice_no: str | None,
    doc_type: DocumentType,
) -> "BuildDocumentResult":
    """构建单个单据的 DocumentModel。

    export 和 preview 共用此函数，避免第二套 seller/buyer/invoice_no/PI 编号判断。

    返回 (model, mapping, messages)。model 为 None 时表示阻断错误。
    """
    from ro_generator.document_model import BuildResult

    if doc_type == "PO" and seller in ENTITIES_WITHOUT_PO:
        return BuildDocumentResult(
            model=None,
            mapping=None,
            messages=(
                ValidationMessage(
                    kind="blocking_error", code=CODE_MAPPING_NOT_FOUND,
                    message=f"{seller} 主体不提供 PO 模板",
                ),
            ),
        )

    mapping = _load_mapping(seller, doc_type)
    if mapping is None:
        return BuildDocumentResult(
            model=None,
            mapping=None,
            messages=(
                ValidationMessage(
                    kind="blocking_error", code=CODE_MAPPING_NOT_FOUND,
                    message=f"找不到 (seller={seller!r}, document={doc_type}) 对应的模板 mapping",
                ),
            ),
        )

    if doc_type == "PI":
        pi_no = po_no
        if seller == "SK":
            pi_no = _first_non_empty(line.e10_po for line in lines) or po_no
        elif seller == "YM":
            pi_no = _first_non_empty(line.ym_po for line in lines) or po_no
        build_result = build_pi_model(lines, seller=seller, buyer=buyer, po_no=po_no, pi_no=pi_no)
    elif doc_type == "PO":
        build_result = build_po_model(lines, seller=seller, buyer=buyer, po_no=po_no)
    elif doc_type == "PL":
        build_result = build_pl_model(
            lines, seller=seller, buyer=buyer, po_no=po_no, invoice_no=invoice_no,
        )
    else:
        build_result = build_invoice_model(
            lines, seller=seller, buyer=buyer, po_no=po_no, invoice_no=invoice_no,
        )

    return BuildDocumentResult(
        model=build_result.model,
        mapping=mapping,
        messages=build_result.messages,
    )


# —————————————————————————————————————
# 单文档装配（export 用）
# —————————————————————————————————————


def _generate_one(
    lines: tuple,  # type: ignore[type-arg]
    *, seller: str, buyer: str, po_no: str,
    invoice_no: str | None, doc_type: DocumentType,
    request: DocumentRequest,
) -> GenerationResult:
    build = build_document_model(
        lines, seller=seller, buyer=buyer, po_no=po_no,
        invoice_no=invoice_no, doc_type=doc_type,
    )

    blocking = tuple(m for m in build.messages if m.kind == "blocking_error")
    doc_warnings = tuple(m for m in build.messages if m.kind == "warning")
    if build.model is None or build.mapping is None:
        return GenerationResult(status="error", errors=blocking, warnings=doc_warnings)

    filename = build_document_filename(
        seller=seller, document_type=doc_type, po_no=po_no, invoice_no=invoice_no,
    )
    output_path = resolve_output_path(
        request.output_dir, filename, on_conflict=request.on_conflict,
    )
    render_result = render_document(build.model, build.mapping, output_path)

    return GenerationResult(
        status="success",
        files=(filename,),
        output_file=str(render_result.output_path),
        warnings=doc_warnings,
        source_index=render_result.source_index,
        summary={
            "table_start_row": build.mapping.lines.start_row,
            "table_label_row": build.mapping.lines.start_row - 1,
            "style": {
                "bold": list(build.mapping.style.bold),
                "underline": list(build.mapping.style.underline),
            },
        },
    )


def _build_summary(
    request: DocumentRequest, seller: str, buyer: str,
    lines: tuple, documents: tuple[str, ...],  # type: ignore[type-arg]
    *,
    invoice_no: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    s: dict[str, object] = {
        "po_no": request.po_no,
        "documents": list(documents),
        "seller": seller,
        "buyer": buyer,
        "line_count": len(lines),
        "invoice_no": invoice_no,
    }
    if extra:
        s.update(extra)
    return s


# —————————————————————————————————————
# Helpers
# —————————————————————————————————————

def _resolve_segment(
    request: DocumentRequest, lines: tuple,  # type: ignore[type-arg]
) -> tuple[str | None, str | None, tuple[ValidationMessage, ...]]:
    if request.seller:
        if request.seller not in SELLERS:
            return (
                None, None,
                (ValidationMessage(
                    kind="blocking_error", code=CODE_UNSUPPORTED_SEGMENT,
                    message=f"未知卖方主体 {request.seller!r}，合法值：{SELLERS}",
                ),),
            )
        buyer = SELLER_TO_BUYER.get(request.seller, "")
        return request.seller, buyer, ()
    return None, None, ()


def _needs_input(
    base_messages: tuple[ValidationMessage, ...],
    inputs: list[str],
    lines: tuple,  # type: ignore[type-arg]
) -> GenerationResult:
    options: dict[str, tuple[dict[str, str], ...]] = {}
    if INPUT_SELLER in inputs:
        options[INPUT_SELLER] = tuple({"value": s, "label": s} for s in SELLERS)
    return GenerationResult(
        status="needs_input", missing_inputs=tuple(inputs),
        options=options, warnings=base_messages,
    )


def _collect_distinct_invoice_nos(
    lines: tuple,  # type: ignore[type-arg]
) -> tuple[dict[str, str], ...]:
    seen: list[str] = []
    for line in lines:
        inv = line.invoice_no
        if not inv or inv in seen:
            continue
        seen.append(inv)
    return tuple({"value": inv, "label": inv} for inv in seen)


def _load_mapping(seller: str, document: str) -> TemplateMapping | None:
    path = builtin_mapping_path(seller, document)
    if path is None:
        return None
    return load_template_mapping(path)


def _first_non_empty(values: object) -> str | None:
    for v in values:  # type: ignore[attr-defined]
        if v:
            return str(v)
    return None


def _error_result(*messages: ValidationMessage) -> GenerationResult:
    return GenerationResult(status="error", errors=messages)


_ = (SourceIndex,)


__all__ = [
    "BuildDocumentResult",
    "CODE_MAPPING_NOT_FOUND",
    "CODE_UNSUPPORTED_DOCUMENT",
    "CODE_UNSUPPORTED_SEGMENT",
    "INPUT_BUYER",
    "INPUT_INVOICE_NO",
    "INPUT_SELLER",
    "PreviewResult",
    "build_document_model",
    "builtin_mapping_path",
    "generate",
    "preview",
    "preview_from_snapshot",
]
