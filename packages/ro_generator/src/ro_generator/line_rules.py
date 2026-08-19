from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final, TypedDict

from ro_generator.profiles.runtime import current_rules, current_schema, current_source_location
from ro_generator.schema import (
    CATEGORY_NAMES,
    SHEET_CUSTOMER_PO,
    SHEET_DATA_BASE,
    SHEET_PO_RECORD,
)

USD_NUMBER_FORMAT: Final[str] = '"$"#,##0.00'


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
    display_prefix: str | None = None


class LineFieldOverride(TypedDict, total=False):
    rule: str
    source_sheet: str | None
    source_field: str | None
    source_type: str
    computed: bool
    fixed_value: bool
    skip_if_none: bool
    zero_placeholder: str | None
    none_placeholder: str | None
    display_decimal_places: int | None
    display_prefix: str | None


LINE_FIELD_SPECS: Final[dict[str, LineFieldSpec]] = {
    "po_no": LineFieldSpec(
        rule="客户PO 的 Purchasing Document 列",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="purchasing_document",
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
        source_field="sap",
    ),
    "description": LineFieldSpec(
        rule="DATA BASE 的 Material Description 列，通过 SAP 关联",
        source_sheet=SHEET_DATA_BASE,
        source_field="description",
    ),
    "gs_model": LineFieldSpec(
        rule="DATA BASE 的 GS Model 列，通过 SAP 关联",
        source_sheet=SHEET_DATA_BASE,
        source_field="gs_model",
    ),
    "unit_price": LineFieldSpec(
        rule="DATA BASE 中按主体 + Category 选择对应 FOB 单价列",
        source_sheet=SHEET_DATA_BASE,
        source_field="unit_price",
        zero_placeholder="需填: 单价",
        display_decimal_places=2,
        display_prefix="$",
    ),
    "quantity": LineFieldSpec(
        rule="PI/PO 使用客户PO 的 Order Quantity；Invoice/PL 使用 PO record 的 SHIP QTY",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="order_quantity",
        zero_placeholder="需填: 数量",
    ),
    "amount": LineFieldSpec(
        rule="amount = unit_price × quantity",
        source_sheet=None,
        source_field=None,
        source_type="computed",
        computed=True,
        display_decimal_places=2,
        display_prefix="$",
    ),
    "unit_label": LineFieldSpec(
        rule="模板固定单位标识",
        source_sheet=None,
        source_field=None,
        source_type="template_content",
        fixed_value=True,
    ),
    "net_weight": LineFieldSpec(
        rule="单箱净重（PO record 或 DATA BASE 中的 N/W 列） × CTNS（箱数）",
        source_sheet=None,
        source_field=None,
        source_type="computed",
        computed=True,
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "gross_weight": LineFieldSpec(
        rule="单箱毛重（PO record 或 DATA BASE 中的 G/W 列） × CTNS（箱数）",
        source_sheet=None,
        source_field=None,
        source_type="computed",
        computed=True,
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
        rule='PL 使用 PO record AD列 "CTNS"',
        source_field="carton_count",
        skip_if_none=True,
    ),
    "length": LineFieldSpec(
        rule="DATA BASE 的 L 列",
        source_sheet=SHEET_DATA_BASE,
        source_field="length",
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "width": LineFieldSpec(
        rule="DATA BASE 的 W 列",
        source_sheet=SHEET_DATA_BASE,
        source_field="width",
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "height": LineFieldSpec(
        rule="DATA BASE 的 H 列",
        source_sheet=SHEET_DATA_BASE,
        source_field="height",
        skip_if_none=True,
        display_decimal_places=2,
    ),
    "confirmed_ex_factory_date": LineFieldSpec(
        rule="客户PO 的 ship DATE 列",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship_date",
        none_placeholder="需填: 出厂日期",
    ),
}


# —————————————————————————————————————
# 单据族差异表
# PI/PO 沿用 LINE_FIELD_SPECS 默认值（订单时数据）
# INVOICE/PL 用出货时数据；PL 额外覆盖 cbm
# —————————————————————————————————————

_INVOICE_PL_OVERRIDES: Final[dict[str, LineFieldOverride]] = {
    "quantity": {
        "rule": "Invoice/PL 使用 PO record 的月度出货数量",
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "ship_qty",
    },
    "description": {
        "rule": "Invoice/PL 使用 PO record 的 DESCRIPTION 列",
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "description",
    },
}

_PL_ONLY_OVERRIDES: Final[dict[str, LineFieldOverride]] = {
    **_INVOICE_PL_OVERRIDES,
    "cbm": {
        "rule": 'PL 使用 PO record AJ列 "TOTAL CBM"',
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "total_cbm",
        "source_type": "base_field",
    },
}

# document_type → {field_name → override_kwargs}
_DOC_FAMILY_OVERRIDES: Final[dict[str, dict[str, LineFieldOverride]]] = {
    "INVOICE": _INVOICE_PL_OVERRIDES,
    "PL": _PL_ONLY_OVERRIDES,
    "CI": _INVOICE_PL_OVERRIDES,
    "RO_PL": _PL_ONLY_OVERRIDES,
}

# —————————————————————————————————————
# 主体专属来源覆盖
# field_name → [(seller_set, override_kwargs), ...]
# —————————————————————————————————————

_SELLER_LINE_OVERRIDES: Final[dict[str, list[tuple[frozenset[str], LineFieldOverride]]]] = {
    "confirmed_ex_factory_date": [
        (
            frozenset({"SK", "YM", "GS PTE"}),
            {
                "rule": 'PO record 的 "FINAL EX-FACTORY DATE" 列',
                "source_sheet": SHEET_PO_RECORD,
                "source_field": "final_ex_factory_date",
            },
        ),
    ],
}

_CONTEXT_LINE_OVERRIDES: Final[dict[tuple[str, str, str], LineFieldOverride]] = {
    ("PI", "EMAX PTE", "confirmed_ex_factory_date"): {
        "rule": 'PO record 的 "FINAL EX-FACTORY DATE" 列',
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "final_ex_factory_date",
    },
    ("PO", "GS PTE", "confirmed_ex_factory_date"): {
        "rule": '客户PO 的 "ship DATE" 列',
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "ship_date",
    },
}

# 仅在 Profile 明确声明时切换客户特有的订单描述来源；RO 等已有 Profile
# 继续使用 DATA BASE 描述，避免把客户 PO 的文案规则扩散到所有主体。
_PROFILE_LINE_OVERRIDES: Final[dict[tuple[str, str, str, str], LineFieldOverride]] = {
    ("pf", "INVOICE", "GS PTE", "po_no"): {
        "rule": 'PO RECORD C列 "PO NO."，按 INV# 筛选',
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "po_no",
    },
    ("pf", "INVOICE", "GS PTE", "item_line_no"): {
        "rule": 'PO RECORD D列 "ITEM LINE#"，按 INV# 筛选',
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "item_line",
    },
    ("pf", "PI", "GS PTE", "po_no"): {
        "rule": 'new PO template F列 "PO#"',
    },
    ("pf", "PI", "GS PTE", "item_line_no"): {
        "rule": 'new PO template G列 "PO-Item"',
    },
    ("pf", "PI", "GS PTE", "item_number"): {
        "rule": 'new PO template H列 "Material"',
    },
    ("pf", "PI", "GS PTE", "description"): {
        "rule": 'new PO template I列 "Material Description"',
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "description",
    },
    ("pf", "PI", "EMAX PTE", "description"): {
        "rule": 'new PO template I列 "Material Description"',
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "description",
    },
    ("pf", "PI", "GS PTE", "quantity"): {
        "rule": 'new PO template L列 "Order Quantity"',
    },
    ("pf", "PO", "GS PTE", "po_no"): {
        "rule": 'new PO template F列 "PO#"',
    },
    ("pf", "PO", "GS PTE", "item_line_no"): {
        "rule": 'new PO template G列 "PO-Item"',
    },
    ("pf", "PO", "GS PTE", "item_number"): {
        "rule": 'new PO template H列 "Material"',
    },
    ("pf", "PO", "GS PTE", "description"): {
        "rule": 'new PO template I列 "Material Description"',
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "description",
    },
    ("pf", "PO", "GS PTE", "quantity"): {
        "rule": 'new PO template L列 "Order Quantity"',
    },
    ("pf", "PO", "EMAX PTE", "po_no"): {
        "rule": 'new PO template F列 "PO#"',
    },
    ("pf", "PO", "EMAX PTE", "item_line_no"): {
        "rule": 'new PO template G列 "PO-Item"',
    },
    ("pf", "PO", "EMAX PTE", "item_number"): {
        "rule": 'new PO template H列 "Material"',
    },
    ("pf", "PO", "EMAX PTE", "description"): {
        "rule": 'new PO template I列 "Material Description"',
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "description",
    },
    ("pf", "PO", "EMAX PTE", "quantity"): {
        "rule": 'new PO template L列 "Order Quantity"',
    },
}


def get_line_field_spec(field_name: str) -> LineFieldSpec:
    return LINE_FIELD_SPECS.get(
        field_name,
        LineFieldSpec(
            rule="",
            source_field=field_name,
        ),
    )


def _apply_seller_line_override(spec: LineFieldSpec, field_name: str, seller: str) -> LineFieldSpec:
    """按主体查找来源覆盖，找到则返回替换后的 spec，否则原样返回。"""
    for seller_set, kwargs in _SELLER_LINE_OVERRIDES.get(field_name, []):
        if seller in seller_set:
            return replace(spec, **kwargs)
    return spec


def _apply_context_line_override(
    spec: LineFieldSpec,
    *,
    field_name: str,
    document_type: str,
    seller: str,
) -> LineFieldSpec:
    kwargs = _CONTEXT_LINE_OVERRIDES.get((document_type, seller, field_name))
    return replace(spec, **kwargs) if kwargs else spec


def _resolve_unit_price_spec(
    spec: LineFieldSpec,
    *,
    document_type: str,
    seller: str,
    category: int | None,
) -> LineFieldSpec:
    """unit_price 按 seller × category 叉积查列名，结果无法预先声明，单独处理。"""
    if current_rules().uses_po_record_unit_price(document_type):
        column = current_rules().po_price_columns.get(seller)
        if column:
            return replace(
                spec,
                rule=f'PO record 的 "{column}" 列，按当前发票对应出货行取值',
                source_sheet=current_schema().sheet("PO record").name,
                source_field=column,
            )
    category_name = CATEGORY_NAMES.get(category or -1, "")
    buyer = current_rules().buyer_for(seller) or ""
    price_seller = current_rules().price_segment(document_type, seller, buyer)[0]
    configured_columns = current_rules().data_base_price_columns
    if document_type in {"INVOICE", "PL"} and current_rules().invoice_data_base_price_columns:
        configured_columns = current_rules().invoice_data_base_price_columns
    column = configured_columns.get(f"{price_seller}/{category_name}")
    if column:
        rule = f"DATA BASE 的 {column} 列"
        if current_rules().profile_id == "pf":
            rule_prefix = (
                "DATA BASE Invoice 当前生效价格列"
                if document_type in {"INVOICE", "PL"}
                else "DATA BASE 当前生效价格列"
            )
            rule = f"{rule_prefix}（Profile 配置：{column}）"
        return replace(
            spec,
            rule=rule,
            source_sheet=current_schema().sheet("DATA BASE").name,
            source_field=column,
        )
    source_sheet, source_field = current_source_location(spec.source_sheet, spec.source_field)
    return replace(spec, source_sheet=source_sheet, source_field=source_field)


def resolve_line_field_spec(
    field_name: str,
    *,
    document_type: str,
    seller: str,
    category: int | None = None,
) -> LineFieldSpec:
    # 1. 按单据族叠加覆盖（INVOICE/PL 使用出货数据；PI/PO 沿用默认）
    doc_kwargs = _DOC_FAMILY_OVERRIDES.get(document_type, {}).get(field_name)
    spec = (
        replace(get_line_field_spec(field_name), **doc_kwargs)
        if doc_kwargs
        else get_line_field_spec(field_name)
    )

    # 2. 主体专属来源覆盖（数据驱动，无 if 链）
    spec = _apply_seller_line_override(spec, field_name, seller)
    spec = _apply_context_line_override(
        spec,
        field_name=field_name,
        document_type=document_type,
        seller=seller,
    )

    profile_kwargs = _PROFILE_LINE_OVERRIDES.get(
        (current_rules().profile_id, document_type, seller, field_name)
    )
    if profile_kwargs:
        spec = replace(spec, **profile_kwargs)

    # 3. unit_price：seller × category 叉积，无法预先声明
    if field_name == "unit_price":
        spec = _resolve_unit_price_spec(
            spec,
            document_type=document_type,
            seller=seller,
            category=category,
        )

    if field_name == "confirmed_ex_factory_date":
        logical_sheet, internal_field = current_rules().ex_factory_source(
            document_type,
            seller,
            "line",
        )
        source_sheet = current_schema().sheet(logical_sheet).name
        source_field = current_schema().field(logical_sheet, internal_field)
        spec = replace(
            spec,
            source_sheet=source_sheet,
            source_field=source_field,
            rule=(
                f'SK/YM确认的 PI 交期（{source_sheet} 的 "{source_field}" 列）'
                if current_rules().profile_id == "pf"
                and document_type == "PI"
                and seller in {"GS PTE", "EMAX PTE"}
                else (
                    'new PO template K列 "PO requested ex-fty date"'
                    if current_rules().profile_id == "pf"
                    and document_type == "PO"
                    and seller in {"GS PTE", "EMAX PTE"}
                    else f'{source_sheet} 的 "{source_field}" 列'
                )
            ),
        )

    # line_rules 中的来源声明使用逻辑 sheet/字段名，便于 RO 与其他
    # Profile 共用一套业务规则。返回给 renderer/preview 前必须和 header
    # 规则一样解析成当前 Profile 的实际 sheet/表头；否则 PF 会把
    # `new PO template` 的 `PO#` 显示成 RO 的 `客户PO`/`Purchasing Document`。
    resolved_source_sheet, resolved_source_field = current_source_location(
        spec.source_sheet,
        spec.source_field,
    )
    return replace(
        spec,
        source_sheet=resolved_source_sheet,
        source_field=resolved_source_field,
    )


def uses_po_record_row(spec: LineFieldSpec) -> bool:
    return (
        spec.source_type == "base_field"
        and spec.source_sheet == current_schema().sheet("PO record").name
    )


def line_display_value(value: object, spec: LineFieldSpec) -> object:
    """按字段显示规则格式化行值。"""
    if not isinstance(value, Decimal):
        return value
    decimal_places = _resolved_decimal_places(value, spec)
    if decimal_places is None:
        return str(value)
    quantizer = Decimal("1").scaleb(-decimal_places)
    normalized = value.quantize(quantizer)
    text = (
        f"{normalized:,.{decimal_places}f}"
        if spec.display_prefix
        else f"{normalized:.{decimal_places}f}"
    )
    return f"{spec.display_prefix or ''}{text}"


def line_excel_number_format(value: object, spec: LineFieldSpec) -> str | None:
    """返回 Excel number_format，None 表示沿用模板样式。"""
    if not isinstance(value, Decimal):
        return None
    decimal_places = _resolved_decimal_places(value, spec)
    if decimal_places is None:
        return None
    if spec.display_prefix == "$":
        return USD_NUMBER_FORMAT
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
    "USD_NUMBER_FORMAT",
    "LineFieldSpec",
    "get_line_field_spec",
    "line_display_value",
    "line_excel_number_format",
    "resolve_line_field_spec",
    "uses_po_record_row",
]
