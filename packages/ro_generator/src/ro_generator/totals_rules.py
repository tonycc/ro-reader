from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ro_generator.document_model import DocumentModel


@dataclass(frozen=True)
class TotalFieldSpec:
    mapping_key: str
    model_attr: str
    preview_key: str
    label: str
    rule: str


TOTAL_FIELD_SPECS: Final[dict[str, TotalFieldSpec]] = {
    "subtotal": TotalFieldSpec(
        mapping_key="subtotal",
        model_attr="total_amount",
        preview_key="total_amount",
        label="Sub-Total",
        rule="SUM of line amounts",
    ),
    "quantity": TotalFieldSpec(
        mapping_key="quantity",
        model_attr="total_quantity",
        preview_key="total_quantity",
        label="Total Qty",
        rule="SUM of line quantities",
    ),
    "amount": TotalFieldSpec(
        mapping_key="amount",
        model_attr="total_amount",
        preview_key="total_amount",
        label="Total Amount",
        rule="SUM of line amounts",
    ),
    "net_weight": TotalFieldSpec(
        mapping_key="net_weight",
        model_attr="total_net_weight",
        preview_key="total_net_weight",
        label="Total N/W (KGS)",
        rule="SUM of line net weights",
    ),
    "gross_weight": TotalFieldSpec(
        mapping_key="gross_weight",
        model_attr="total_gross_weight",
        preview_key="total_gross_weight",
        label="Total G/W (KGS)",
        rule="SUM of line gross weights",
    ),
    "cbm": TotalFieldSpec(
        mapping_key="cbm",
        model_attr="total_cbm",
        preview_key="total_cbm",
        label="Total CBM",
        rule="SUM of line CBM",
    ),
    "carton_count": TotalFieldSpec(
        mapping_key="carton_count",
        model_attr="total_carton_count",
        preview_key="total_carton_count",
        label="Total CTNS",
        rule="SUM of line carton counts",
    ),
}

STANDARD_TOTAL_MAPPING_KEYS: Final[tuple[str, ...]] = ("quantity", "amount")
PL_TOTAL_MAPPING_KEYS: Final[tuple[str, ...]] = (
    "quantity",
    "net_weight",
    "gross_weight",
    "cbm",
    "carton_count",
)


def preview_total_specs(document_type: str) -> tuple[TotalFieldSpec, ...]:
    mapping_keys = (
        PL_TOTAL_MAPPING_KEYS if document_type in ("PL", "RO_PL") else STANDARD_TOTAL_MAPPING_KEYS
    )
    return tuple(TOTAL_FIELD_SPECS[key] for key in mapping_keys)


def total_spec_for_mapping_key(mapping_key: str) -> TotalFieldSpec | None:
    return TOTAL_FIELD_SPECS.get(mapping_key)


def total_value_for_mapping_key(
    model: DocumentModel,
    mapping_key: str,
) -> Decimal | None:
    spec = total_spec_for_mapping_key(mapping_key)
    if spec is None:
        return None
    value = getattr(model, spec.model_attr, None)
    return value if isinstance(value, Decimal) or value is None else None


def build_preview_totals(
    model: DocumentModel,
    *,
    unit_label: str,
) -> dict[str, object]:
    totals: dict[str, object] = {
        "unit_label": unit_label,
    }

    for spec in preview_total_specs(model.document_type):
        value = getattr(model, spec.model_attr, None)
        if value is None:
            continue
        totals[spec.preview_key] = _format_total_preview_value(spec.preview_key, value)

    if "total_quantity" not in totals:
        totals["total_quantity"] = "0"
    if model.document_type not in ("PL", "RO_PL"):
        totals.setdefault("total_amount", "$0.00")
        totals["currency"] = "USD"

    totals["_labels"] = {
        spec.preview_key: spec.label
        for spec in preview_total_specs(model.document_type)
        if spec.preview_key in totals
    }
    return totals


def iter_present_preview_totals(
    model: DocumentModel,
) -> tuple[tuple[TotalFieldSpec, str], ...]:
    entries: list[tuple[TotalFieldSpec, str]] = []
    for spec in preview_total_specs(model.document_type):
        value = getattr(model, spec.model_attr, None)
        if value is not None:
            entries.append((spec, str(value)))
    return tuple(entries)


def _format_total_preview_value(preview_key: str, value: Decimal) -> str:
    if preview_key == "total_amount":
        normalized = value.quantize(Decimal("0.01"))
        return f"${normalized:,.2f}"
    return str(value)


__all__ = [
    "PL_TOTAL_MAPPING_KEYS",
    "STANDARD_TOTAL_MAPPING_KEYS",
    "TOTAL_FIELD_SPECS",
    "TotalFieldSpec",
    "build_preview_totals",
    "iter_present_preview_totals",
    "preview_total_specs",
    "total_spec_for_mapping_key",
    "total_value_for_mapping_key",
]
