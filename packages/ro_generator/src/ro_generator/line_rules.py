from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from ro_generator.schema import (
    CATEGORY_NAMES,
    DATA_BASE_PRICE_COLUMNS,
    SHEET_CUSTOMER_PO,
    SHEET_DATA_BASE,
    SHEET_PO_RECORD,
)


@dataclass(frozen=True)
class LineFieldSpec:
    rule: str
    source_sheet: str | None = SHEET_PO_RECORD
    source_field: str | None = None
    source_type: str = "base_field"
    computed: bool = False
    fixed_value: bool = False
    skip_if_none: bool = False
    zero_placeholder: str | None = None
    none_placeholder: str | None = None
    display_decimal_places: int | None = None


LINE_FIELD_SPECS: Final[dict[str, LineFieldSpec]] = {
    "po_no": LineFieldSpec(
        rule="客户PO 的 Purchasing Document 列",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="Purchasing Document",
    ),
    "item_line_no": LineFieldSpec(
        rule='客户PO B列 "Item"',
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="item",
    ),
    "item_number": LineFieldSpec(
        rule="客户PO 的 material 列",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="material",
    ),
    "sap": LineFieldSpec(
        rule="PO record 的 SAP Number 列，关联 DATA BASE",
        source_field="SAP Number",
    ),
    "description": LineFieldSpec(
        rule="DATA BASE 的 Material Description 列，通过 SAP 关联",
        source_sheet=SHEET_DATA_BASE,
        source_field="Material Description",
    ),
    "gs_model": LineFieldSpec(
        rule="DATA BASE 的 GS Model 列，通过 SAP 关联",
        source_field="GS MODEL",
    ),
    "unit_price": LineFieldSpec(
        rule="DATA BASE 中按主体 + Category 选择对应 FOB 单价列",
        source_sheet=SHEET_DATA_BASE,
        source_field="unit_price",
        zero_placeholder="需填: 单价",
    ),
    "quantity": LineFieldSpec(
        rule="PI/PO 使用客户PO 的 Order Quantity；Invoice/PL 使用 PO record 的 SHIP QTY",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="Order Quantity",
        zero_placeholder="需填: 数量",
    ),
    "amount": LineFieldSpec(
        rule="amount = unit_price × quantity",
        source_sheet=None,
        source_field=None,
        source_type="computed",
        computed=True,
    ),
    "unit_label": LineFieldSpec(
        rule="模板固定单位标识",
        source_sheet=None,
        source_field=None,
        source_type="template_content",
        fixed_value=True,
    ),
    "net_weight": LineFieldSpec(
        rule="PO record 或 DATA BASE 中的 N/W 列",
        source_field="N/W",
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "gross_weight": LineFieldSpec(
        rule="PO record 或 DATA BASE 中的 G/W 列",
        source_field="G/W",
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "cbm": LineFieldSpec(
        rule="L × W × H / 1,000,000 × CTNS",
        source_sheet=None,
        source_field=None,
        source_type="computed",
        computed=True,
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "carton_count": LineFieldSpec(
        rule="客户PO Order Quantity / 外箱 或 PO record CTNS 列",
        source_field="CTNS",
        skip_if_none=True,
    ),
    "confirmed_ex_factory_date": LineFieldSpec(
        rule="客户PO 的 ship DATE 列",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship DATE",
        none_placeholder="需填: 出厂日期",
    ),
}


def get_line_field_spec(field_name: str) -> LineFieldSpec:
    return LINE_FIELD_SPECS.get(
        field_name,
        LineFieldSpec(
            rule="",
            source_field=field_name,
        ),
    )


def resolve_line_field_spec(
    field_name: str,
    *,
    document_type: str,
    seller: str,
    category: int | None = None,
) -> LineFieldSpec:
    spec = get_line_field_spec(field_name)
    if field_name == "description" and document_type in {"INVOICE", "PL"}:
        return replace(
            spec,
            rule=f"{document_type} 使用 PO record 的 DESCRIPTION 列",
            source_sheet=SHEET_PO_RECORD,
            source_field="DESCRIPTION",
        )
    if field_name == "quantity" and document_type in {"INVOICE", "PL"}:
        return replace(
            spec,
            rule="Invoice/PL 使用 PO record 的 SHIP QTY",
            source_sheet=SHEET_PO_RECORD,
            source_field="SHIP QTY",
        )
    if field_name == "cbm" and document_type == "PL":
        return replace(
            spec,
            rule='PL 使用 PO record AJ列 "TOTAL CBM"',
            source_sheet=SHEET_PO_RECORD,
            source_field="TOTAL CBM",
            source_type="base_field",
        )
    if field_name == "unit_price":
        category_name = CATEGORY_NAMES.get(category or -1, "")
        column = DATA_BASE_PRICE_COLUMNS.get(f"{seller}/{category_name}")
        if column:
            return replace(
                spec,
                rule=f"DATA BASE 的 {column} 列",
                source_sheet=SHEET_DATA_BASE,
                source_field=column,
            )
    if field_name == "confirmed_ex_factory_date" and seller in {"SK", "YM", "GS PTE"}:
        return replace(
            spec,
            rule='PO record 的 "FINAL EX-FACTORY DATE" 列',
            source_sheet=SHEET_PO_RECORD,
            source_field="FINAL EX-FACTORY DATE",
        )
    return spec


def uses_po_record_row(spec: LineFieldSpec) -> bool:
    return spec.source_type == "base_field" and spec.source_sheet == SHEET_PO_RECORD


def line_display_value(value: object, spec: LineFieldSpec) -> object:
    """按字段显示规则格式化行值。"""
    if not isinstance(value, Decimal):
        return value
    decimal_places = _resolved_decimal_places(value, spec)
    if decimal_places is None:
        return str(value)
    quantizer = Decimal("1").scaleb(-decimal_places)
    normalized = value.quantize(quantizer)
    return f"{normalized:.{decimal_places}f}"


def line_excel_number_format(value: object, spec: LineFieldSpec) -> str | None:
    """返回 Excel number_format，None 表示沿用模板样式。"""
    if not isinstance(value, Decimal):
        return None
    decimal_places = _resolved_decimal_places(value, spec)
    if decimal_places is None:
        return None
    if decimal_places == 0:
        return "0"
    return "0." + ("0" * decimal_places)


def _resolved_decimal_places(value: Decimal, spec: LineFieldSpec) -> int | None:
    source_places = _decimal_places_from_value(value)
    spec_places = spec.display_decimal_places
    if source_places is None:
        return spec_places
    if spec_places is None:
        return source_places
    return max(source_places, spec_places)


def _decimal_places_from_value(value: Decimal) -> int | None:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    return max(-exponent, 0)


__all__ = [
    "LINE_FIELD_SPECS",
    "LineFieldSpec",
    "get_line_field_spec",
    "line_display_value",
    "line_excel_number_format",
    "resolve_line_field_spec",
    "uses_po_record_row",
]
