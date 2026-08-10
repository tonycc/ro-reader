"""Read-only inspection projection for an invoice group."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from ro_generator.invoice_groups import InvoiceHeaderContext, InvoiceInspection
from ro_generator.models import OrderLine, ValidationMessage
from ro_generator.profiles import GenerationContext
from ro_generator.profiles.runtime import current_profile, current_schema, profile_scope
from ro_generator.resolver import resolve_po_rows
from ro_generator.schema import SELLERS
from ro_generator.seller_filter import factory_seller_for_line

if TYPE_CHECKING:
    from ro_generator.workbook_snapshot import WorkbookSnapshot


CODE_INVOICE_GROUP_NOT_FOUND: Final = "INVOICE_GROUP_NOT_FOUND"
CODE_INVOICE_GROUP_HEADER_CONFLICT: Final = "INVOICE_GROUP_HEADER_CONFLICT"


@dataclass(frozen=True)
class InvoiceInspectionRow:
    source_row: int
    po_no: str
    sap: str
    description: str
    category: int | None
    ship_qty: Decimal
    invoice_no: str | None
    factory_document_no: str | None
    sellers: tuple[str, ...]


@dataclass(frozen=True)
class InvoiceGroupInspection:
    invoice_group_key: str
    display_invoice_no: str
    po_nos: tuple[str, ...]
    rows: tuple[InvoiceInspectionRow, ...]
    blocking_errors: tuple[ValidationMessage, ...]
    warnings: tuple[ValidationMessage, ...]


@dataclass(frozen=True)
class InvoiceGroupResolution:
    summary: InvoiceInspection | None
    lines: tuple[OrderLine, ...]
    blocking_errors: tuple[ValidationMessage, ...]
    warnings: tuple[ValidationMessage, ...]


def dedupe_messages(
    messages: Iterable[ValidationMessage],
) -> tuple[ValidationMessage, ...]:
    seen: set[tuple[object, ...]] = set()
    result: list[ValidationMessage] = []
    for message in messages:
        key = (
            message.kind,
            message.code,
            message.message,
            message.sheet,
            message.row,
            message.field,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(message)
    return tuple(result)


def resolve_invoice_group_from_snapshot(
    snapshot: WorkbookSnapshot,
    invoice_group_key: str,
    *,
    context: GenerationContext | None = None,
) -> InvoiceGroupResolution:
    scope = profile_scope(context.profile) if context is not None else nullcontext()
    with scope:
        return _resolve_invoice_group_from_snapshot(snapshot, invoice_group_key)


def _resolve_invoice_group_from_snapshot(
    snapshot: WorkbookSnapshot,
    invoice_group_key: str,
) -> InvoiceGroupResolution:
    summary = next(
        (item for item in snapshot.invoice_summary if item.invoice_group_key == invoice_group_key),
        None,
    )
    if summary is None:
        return InvoiceGroupResolution(
            summary=None,
            lines=(),
            blocking_errors=(
                ValidationMessage(
                    kind="blocking_error",
                    code=CODE_INVOICE_GROUP_NOT_FOUND,
                    message=f"票据组 {invoice_group_key!r} 不存在",
                ),
            ),
            warnings=(),
        )

    member_rows = snapshot.invoice_rows_for_group(invoice_group_key)
    po_field = current_schema().field("PO record", "po_no")
    lines: list[OrderLine] = []
    blocking_errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []
    for po_no in summary.po_nos:
        po_rows = tuple(row for row in member_rows if str(row.get(po_field, "")).strip() == po_no)
        resolved = resolve_po_rows(
            po_rows,
            snapshot.product_index,
            po_no=po_no,
            customer_po_rows=snapshot.customer_po_rows_for_po(po_no),
            require_customer_po=False,
        )
        lines.extend(
            line for line in resolved.lines if line.ship_qty is not None and line.ship_qty > 0
        )
        blocking_errors.extend(
            message for message in resolved.messages if message.kind == "blocking_error"
        )
        warnings.extend(message for message in resolved.messages if message.kind == "warning")

    context = snapshot.invoice_header_context.get(invoice_group_key)
    blocking_errors.extend(_header_conflict_messages(context, summary.po_nos, tuple(lines)))
    return InvoiceGroupResolution(
        summary=summary,
        lines=tuple(lines),
        blocking_errors=dedupe_messages(blocking_errors),
        warnings=dedupe_messages(warnings),
    )


def inspect_invoice_group_from_snapshot(
    snapshot: WorkbookSnapshot,
    invoice_group_key: str,
    *,
    context: GenerationContext | None = None,
) -> InvoiceGroupInspection:
    scope = profile_scope(context.profile) if context is not None else nullcontext()
    with scope:
        return _inspect_invoice_group_from_snapshot(snapshot, invoice_group_key)


def _inspect_invoice_group_from_snapshot(
    snapshot: WorkbookSnapshot,
    invoice_group_key: str,
) -> InvoiceGroupInspection:
    resolution = _resolve_invoice_group_from_snapshot(snapshot, invoice_group_key)
    if resolution.summary is None:
        return InvoiceGroupInspection(
            invoice_group_key=invoice_group_key,
            display_invoice_no="",
            po_nos=(),
            rows=(),
            blocking_errors=resolution.blocking_errors,
            warnings=resolution.warnings,
        )

    projected_rows = [
        _project_line(line)
        for line in resolution.lines
        if line.source_row is not None and line.ship_qty is not None and line.ship_qty > 0
    ]

    projected_rows.sort(key=lambda row: row.source_row)
    return InvoiceGroupInspection(
        invoice_group_key=invoice_group_key,
        display_invoice_no=resolution.summary.display_invoice_no,
        po_nos=resolution.summary.po_nos,
        rows=tuple(projected_rows),
        blocking_errors=resolution.blocking_errors,
        warnings=resolution.warnings,
    )


# source sheet and column for header fields checked in invoice group cross-PO consistency
_HEADER_FIELD_SOURCE: dict[str, tuple[str, str]] = {
    "ship_to": ("客户PO", "ship to"),
    "final_destination": ("客户PO", "final destination"),
    "manufacturer_address": ("客户PO", "manufacturer"),
}


def _header_conflict_messages(
    context: InvoiceHeaderContext | None,
    po_nos: tuple[str, ...],
    lines: tuple[OrderLine, ...],
) -> tuple[ValidationMessage, ...]:
    if context is None:
        return ()
    messages: list[ValidationMessage] = []
    for field_name in context.conflicts:
        source_rows = sorted(
            {
                line.source_row
                for line in lines
                if line.source_row is not None
                and (value := getattr(line, field_name)) is not None
                and str(value).strip()
            }
        )
        sheet, column = _HEADER_FIELD_SOURCE.get(field_name, ("?", field_name))
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_INVOICE_GROUP_HEADER_CONFLICT,
                message=(
                    f"票据组跨 PO 的”{sheet}”sheet”{column}”列不一致；"
                    f"涉及 PO：{', '.join(po_nos)}；"
                    f"源行：{', '.join(str(row) for row in source_rows)}"
                ),
                sheet=sheet,
                field=field_name,
            )
        )
    return tuple(messages)


def _project_line(line: OrderLine) -> InvoiceInspectionRow:
    assert line.source_row is not None
    assert line.ship_qty is not None
    return InvoiceInspectionRow(
        source_row=line.source_row,
        po_no=line.po_no,
        sap=line.sap,
        description=line.description,
        category=line.po_record_category if line.po_record_category is not None else line.category,
        ship_qty=line.ship_qty,
        invoice_no=line.invoice_no,
        factory_document_no=line.sk_ym_invoice_no,
        sellers=_sellers_for_line(line),
    )


def _sellers_for_line(line: OrderLine) -> tuple[str, ...]:
    sellers: list[str] = []
    if line.invoice_no:
        sellers.extend(("GS PTE", "EMAX PTE"))
    factory_seller = factory_seller_for_line(line)
    if line.sk_ym_invoice_no and factory_seller:
        sellers.append(factory_seller)
    profile = current_profile()
    active_sellers = profile.capabilities.sellers if profile is not None else SELLERS
    return tuple(seller for seller in active_sellers if seller in sellers)


__all__ = [
    "CODE_INVOICE_GROUP_HEADER_CONFLICT",
    "CODE_INVOICE_GROUP_NOT_FOUND",
    "InvoiceGroupInspection",
    "InvoiceGroupResolution",
    "InvoiceInspectionRow",
    "dedupe_messages",
    "inspect_invoice_group_from_snapshot",
    "resolve_invoice_group_from_snapshot",
]
