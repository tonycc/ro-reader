"""Invoice-group aggregation for workbench Invoice scope."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ro_generator.models import OrderLine
from ro_generator.schema import SELLERS
from ro_generator.seller_filter import factory_seller_for_line


@dataclass(frozen=True)
class InvoiceInspection:
    invoice_group_key: str
    display_invoice_no: str
    status: str
    po_nos: tuple[str, ...]
    po_count: int
    sellers: tuple[str, ...]
    seller_invoice_numbers: dict[str, str]
    blocking_count: int
    conflict_count: int
    date: str | None


@dataclass(frozen=True)
class InvoiceGroupBuild:
    summaries: tuple[InvoiceInspection, ...]
    index: dict[str, tuple[int, ...]]
    header_context: dict[str, InvoiceHeaderContext]


@dataclass(frozen=True)
class InvoiceHeaderContext:
    values: dict[str, tuple[str, ...]]
    conflicts: tuple[str, ...]
    source_rows: dict[str, tuple[int, ...]]


def build_invoice_group_key(identifiers: tuple[str, ...]) -> str:
    normalized = sorted({_clean(value) for value in identifiers if _clean(value)})
    payload = json.dumps(
        {"identifiers": normalized},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"invgrp::{digest}"


def build_invoice_groups(
    lines_by_row: tuple[tuple[int, OrderLine], ...],
) -> InvoiceGroupBuild:
    eligible: list[tuple[int, OrderLine, tuple[str, ...]]] = []
    parents: dict[str, str] = {}

    for row_index, line in lines_by_row:
        if line.ship_qty is None or line.ship_qty <= 0:
            continue
        identifiers = _identifiers_for_line(line)
        if not identifiers:
            continue
        eligible.append((row_index, line, identifiers))
        for identifier in identifiers:
            parents.setdefault(identifier, identifier)
        for identifier in identifiers[1:]:
            _union(parents, identifiers[0], identifier)

    components: dict[str, list[tuple[int, OrderLine, tuple[str, ...]]]] = {}
    for entry in eligible:
        root = _find(parents, entry[2][0])
        components.setdefault(root, []).append(entry)

    summaries: list[InvoiceInspection] = []
    index: dict[str, tuple[int, ...]] = {}
    header_context: dict[str, InvoiceHeaderContext] = {}
    for entries in components.values():
        raw_numbers = sorted({_clean(line.invoice_no) for _, line, _ in entries if line.invoice_no})
        factory_numbers = sorted(
            {_clean(line.sk_ym_invoice_no) for _, line, _ in entries if line.sk_ym_invoice_no}
        )
        identifiers = tuple(sorted({value for _, _, values in entries for value in values}))
        group_key = build_invoice_group_key(identifiers)
        seller_numbers, _seller_conflicts = _seller_invoice_numbers(entries)
        context = _build_header_context(entries)
        blocking_count = len(context.conflicts)
        conflict_count = blocking_count
        po_nos = tuple(sorted({line.po_no for _, line, _ in entries if line.po_no}))
        display_number = raw_numbers[0] if raw_numbers else factory_numbers[0]
        group_earliest = None
        for _, line, _ in entries:
            d = line.etd_on_board
            if d is not None and (group_earliest is None or d < group_earliest):
                group_earliest = d
        group_date = group_earliest.isoformat() if group_earliest is not None else None
        summary = InvoiceInspection(
            invoice_group_key=group_key,
            display_invoice_no=display_number,
            status="blocked" if blocking_count else "ready",
            po_nos=po_nos,
            po_count=len(po_nos),
            sellers=tuple(seller for seller in SELLERS if seller in seller_numbers),
            seller_invoice_numbers=seller_numbers,
            blocking_count=blocking_count,
            conflict_count=conflict_count,
            date=group_date,
        )
        summaries.append(summary)
        index[group_key] = tuple(sorted(row_index for row_index, _, _ in entries))
        header_context[group_key] = context

    summaries.sort(key=lambda item: (item.display_invoice_no, item.invoice_group_key))
    return InvoiceGroupBuild(
        summaries=tuple(summaries),
        index=index,
        header_context=header_context,
    )


def _build_header_context(
    entries: list[tuple[int, OrderLine, tuple[str, ...]]],
) -> InvoiceHeaderContext:
    values: dict[str, tuple[str, ...]] = {}
    source_rows: dict[str, tuple[int, ...]] = {}
    conflicts: list[str] = []
    for attribute in ():  # type: ignore[var-annotated]  # no attributes currently checked
        field_values = tuple(
            sorted(
                {
                    _clean(getattr(line, attribute))
                    for _, line, _ in entries
                    if _clean(getattr(line, attribute))
                }
            )
        )
        values[attribute] = field_values
        source_rows[attribute] = tuple(
            sorted(row_index for row_index, line, _ in entries if _clean(getattr(line, attribute)))
        )
        if len(field_values) > 1:
            conflicts.append(attribute)
    return InvoiceHeaderContext(
        values=values,
        conflicts=tuple(conflicts),
        source_rows=source_rows,
    )


def _identifiers_for_line(line: OrderLine) -> tuple[str, ...]:
    inv = _clean(line.invoice_no)
    if inv:
        return (inv,)
    factory = _clean(line.sk_ym_invoice_no)
    if factory:
        return (factory,)
    return ()


def _seller_invoice_numbers(
    entries: list[tuple[int, OrderLine, tuple[str, ...]]],
) -> tuple[dict[str, str], int]:
    candidates: dict[str, set[str]] = {}
    for _, line, _ in entries:
        raw_number = _clean(line.invoice_no)
        if raw_number:
            candidates.setdefault("GS PTE", set()).add(raw_number)
            candidates.setdefault("EMAX PTE", set()).add(_append_suffix(raw_number, "-P"))
        factory_number = _clean(line.sk_ym_invoice_no)
        factory_seller = factory_seller_for_line(line)
        if factory_number and factory_seller:
            candidates.setdefault(factory_seller, set()).add(factory_number)

    conflicts = sum(max(0, len(values) - 1) for values in candidates.values())
    return {
        seller: sorted(candidates[seller])[0] for seller in SELLERS if candidates.get(seller)
    }, conflicts


def _append_suffix(value: str, suffix: str) -> str:
    return value if value.endswith(suffix) else f"{value}{suffix}"


def _clean(value: str | None) -> str:
    return value.strip() if value else ""


def _find(parents: dict[str, str], value: str) -> str:
    parent = parents[value]
    if parent != value:
        parents[value] = _find(parents, parent)
    return parents[value]


def _union(parents: dict[str, str], left: str, right: str) -> None:
    left_root = _find(parents, left)
    right_root = _find(parents, right)
    if left_root == right_root:
        return
    first, second = sorted((left_root, right_root))
    parents[second] = first


__all__ = [
    "InvoiceGroupBuild",
    "InvoiceHeaderContext",
    "InvoiceInspection",
    "build_invoice_group_key",
    "build_invoice_groups",
]
