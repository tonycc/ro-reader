from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Final, TypedDict

from ro_generator.header_multiline import (
    MANUFACTURER_HEADER_FIELDS,
    SHIP_TO_HEADER_FIELDS,
    split_manufacturer_address_lines,
    split_ship_to_lines,
)
from ro_generator.schema import SHEET_CUSTOMER_PO, SHEET_PO_RECORD

if TYPE_CHECKING:
    from ro_generator.document_model import DocumentModel


@dataclass(frozen=True)
class HeaderFieldSpec:
    label: str
    source_type: str
    rule: str
    source_sheet: str | None = None
    source_field: str | None = None
    model_attr: str | None = None
    render_keys: tuple[str, ...] = ()


class HeaderFieldOverride(TypedDict, total=False):
    label: str
    source_type: str
    rule: str
    source_sheet: str | None
    source_field: str | None
    model_attr: str | None
    render_keys: tuple[str, ...]


HEADER_DATE_KEYS: Final[frozenset[str]] = frozenset(
    {"document_date", "invoice_date", "signature_date"}
)
HEADER_MANUAL_KEYS: Final[frozenset[str]] = frozenset()
HEADER_MANUAL_PLACEHOLDERS: Final[dict[str, str]] = {}
_SPLIT_CONTINUATION_FIELDS: Final[frozenset[str]] = frozenset(
    (*SHIP_TO_HEADER_FIELDS[1:], "manufacturer_address_2")
)

HEADER_FIELD_SPECS: Final[dict[str, HeaderFieldSpec]] = {
    "invoice_no": HeaderFieldSpec(
        label="Invoice No.",
        source_type="base_field",
        source_sheet=SHEET_PO_RECORD,
        source_field="INV#",
        rule="人工在 base 表录入，工具不自动生成",
        model_attr="invoice_no",
        render_keys=("invoice_no",),
    ),
    "pi_no": HeaderFieldSpec(
        label="PI #",
        source_type="base_field",
        source_sheet=SHEET_PO_RECORD,
        source_field=None,
        rule="SK 用 E10 PO，YM 用 YM PO，其他同 PO #；SK/YM 缺值时阻断生成",
        model_attr="pi_no",
        render_keys=("pi_no",),
    ),
    "po_no": HeaderFieldSpec(
        label="PO #",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="Purchasing Document",
        rule="客户PO 的 Purchasing Document 列",
        model_attr="po_no",
        render_keys=("po_no",),
    ),
    "ship_to": HeaderFieldSpec(
        label="Ship To",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship to",
        rule="客户PO 的 ship to 列；优先按当前 PO 行的 SAP/Material 精确匹配，找不到时回退到同 PO 的首个非空值",
        model_attr="ship_to",
        render_keys=("ship_to", "bill_to"),
    ),
    "ship_to_line2": HeaderFieldSpec(
        label="Ship To",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship to",
        rule="客户PO 的 ship to 列拆分后的第 2 行，按与 ship_to 相同的来源规则生成",
        model_attr="ship_to",
        render_keys=("ship_to_line2",),
    ),
    "ship_to_line3": HeaderFieldSpec(
        label="Ship To",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship to",
        rule="客户PO 的 ship to 列拆分后的第 3 行，按与 ship_to 相同的来源规则生成",
        model_attr="ship_to",
        render_keys=("ship_to_line3",),
    ),
    "seller": HeaderFieldSpec(
        label="Seller",
        source_type="base_field",
        source_sheet=None,
        source_field=None,
        rule="用户选择的贸易链段卖方",
        model_attr="seller",
        render_keys=("seller",),
    ),
    "buyer": HeaderFieldSpec(
        label="Buyer",
        source_type="base_field",
        source_sheet=None,
        source_field=None,
        rule="根据卖方自动推导的买方",
        model_attr="buyer",
        render_keys=("buyer",),
    ),
    "seller_info": HeaderFieldSpec(
        label="Seller Info",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板内置卖方公司信息",
    ),
    "to_label": HeaderFieldSpec(
        label="Bill To Label",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板内置买方标签",
    ),
    "title": HeaderFieldSpec(
        label="Document Title",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板内置单据标题",
    ),
    "terms": HeaderFieldSpec(
        label="Terms",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板内置交易条款（付款条件、贸易术语等）",
    ),
    "to": HeaderFieldSpec(
        label="To",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板固定文本",
    ),
    "manufacturer": HeaderFieldSpec(
        label="Actual Manufacturer Company",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板固定文本",
    ),
    "manufacturer_address": HeaderFieldSpec(
        label="Actual Manufacturer Company Address",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="manufacturer",
        rule='客户PO Y列 "manufacturer"',
        model_attr="manufacturer_address",
        render_keys=("manufacturer_address", "manufacturer_address_2"),
    ),
    "manufacturer_address_2": HeaderFieldSpec(
        label="Actual Manufacturer Company Address",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="manufacturer",
        rule='客户PO Y列 "manufacturer" 拆分后的地址第 2 行',
        model_attr="manufacturer_address",
        render_keys=("manufacturer_address_2",),
    ),
    "ex_factory_date": HeaderFieldSpec(
        label="Ex-Factory Date",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship DATE",
        rule="客户PO 的 ship DATE 列；SK/YM/GS 实际取 PO record FINAL EX-FACTORY DATE",
        model_attr="ex_factory_date",
        render_keys=("ex_factory_date",),
    ),
}
# —————————————————————————————————————
# 主体专属覆盖
# field_name → [(seller_set, override_kwargs), ...]
# —————————————————————————————————————

_HEADER_SELLER_OVERRIDES: Final[dict[str, list[tuple[frozenset[str], HeaderFieldOverride]]]] = {
    "ex_factory_date": [
        (
            frozenset({"SK", "YM", "GS PTE"}),
            {
                "source_sheet": SHEET_PO_RECORD,
                "source_field": "FINAL EX-FACTORY DATE",
                "rule": 'PO record 的 "FINAL EX-FACTORY DATE" 列',
            },
        ),
    ],
    "pi_no": [
        (
            frozenset({"SK"}),
            {
                "source_sheet": SHEET_PO_RECORD,
                "source_field": "E10 PO",
                "rule": 'PO record 的 "E10 PO" 列，必填',
            },
        ),
        (
            frozenset({"YM"}),
            {
                "source_sheet": SHEET_PO_RECORD,
                "source_field": "YM PO",
                "rule": 'PO record 的 "YM PO" 列，必填',
            },
        ),
        (
            frozenset({"GS PTE"}),
            {
                "source_sheet": SHEET_CUSTOMER_PO,
                "source_field": "Purchasing Document",
                "rule": '客户PO A列 "Purchasing Document"',
            },
        ),
    ],
}

_HEADER_CONTEXT_OVERRIDES: Final[dict[tuple[str, str, str], HeaderFieldOverride]] = {
    ("PI", "EMAX PTE", "pi_no"): {
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "Purchasing Document",
        "rule": '客户PO A列 "Purchasing Document"',
    },
    ("PI", "EMAX PTE", "ex_factory_date"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "FINAL EX-FACTORY DATE",
        "rule": 'PO record 的 "FINAL EX-FACTORY DATE" 列',
    },
    ("INVOICE", "EMAX PTE", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "INV#",
        "rule": 'PO record 的 "INV#" 列 + "-P"',
    },
    ("PL", "EMAX PTE", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "INV#",
        "rule": '引用 Invoice，最终来自 PO record 的 "INV#" 列 + "-P"',
    },
    ("INVOICE", "SK", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "SK/YM INVOICE NO.",
        "rule": 'PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("PL", "SK", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "SK/YM INVOICE NO.",
        "rule": '引用 Invoice，最终来自 PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("INVOICE", "YM", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "SK/YM INVOICE NO.",
        "rule": 'PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("PL", "YM", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "SK/YM INVOICE NO.",
        "rule": '引用 Invoice，最终来自 PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("INVOICE", "SK", "to"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "final destination",
        "rule": '客户PO Z列 "final destination"',
        "model_attr": "final_destination",
    },
    ("INVOICE", "YM", "to"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "final destination",
        "rule": '客户PO Z列 "final destination"',
        "model_attr": "final_destination",
    },
    ("PI", "GS PTE", "manufacturer"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "manufacturer",
        "rule": '客户PO Y列 "manufacturer" 拆分后的制造商名称',
        "model_attr": "manufacturer_address",
    },
    ("PO", "GS PTE", "manufacturer"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "manufacturer",
        "rule": '客户PO Y列 "manufacturer" 拆分后的制造商名称',
        "model_attr": "manufacturer_address",
    },
}


def resolve_header_field_spec(
    field_name: str,
    *,
    seller: str,
    document_type: str,
) -> HeaderFieldSpec | None:
    """获取 header 字段规格，已应用主体专属来源覆盖。

    与 resolve_line_field_spec 对称：先取全局默认，再按主体叠加覆盖。
    返回 None 表示该字段没有对应 spec（模板固定文本或未知字段）。
    """
    spec = HEADER_FIELD_SPECS.get(field_name)
    if spec is None:
        return None
    for seller_set, kwargs in _HEADER_SELLER_OVERRIDES.get(field_name, []):
        if seller in seller_set:
            spec = replace(spec, **kwargs)
            break
    context_kwargs = _HEADER_CONTEXT_OVERRIDES.get((document_type, seller, field_name))
    if context_kwargs:
        return replace(spec, **context_kwargs)
    return spec


def build_ship_to_header_values(
    ship_to: str | None,
    header_keys: Iterable[str],
) -> dict[str, str]:
    key_set = set(header_keys)
    if not any(field_name in key_set for field_name in SHIP_TO_HEADER_FIELDS[1:]):
        return {}
    return {
        field_name: value
        for field_name, value in split_ship_to_lines(ship_to).items()
        if field_name in key_set
    }


def build_manufacturer_address_values(
    manufacturer_address: str | None,
    header_keys: Iterable[str],
) -> dict[str, str]:
    key_set = set(header_keys)
    if not any(field_name in key_set for field_name in MANUFACTURER_HEADER_FIELDS):
        return {}
    return {
        field_name: value
        for field_name, value in split_manufacturer_address_lines(manufacturer_address).items()
        if field_name in key_set
    }


def build_header_resolved_values(
    model: DocumentModel,
    *,
    header_keys: Iterable[str],
    header_fixed: Mapping[str, str],
    field_names: Iterable[str] | None = None,
) -> dict[str, str]:
    header_key_list = list(header_keys)
    ship_to_values = build_ship_to_header_values(model.ship_to, header_key_list)
    mfr_addr_values = build_manufacturer_address_values(model.manufacturer_address, header_key_list)
    resolved_values: dict[str, str] = dict(header_fixed)
    requested_fields = field_names if field_names is not None else header_key_list

    for field_name in requested_fields:
        if field_name in resolved_values:
            continue

        spec = resolve_header_field_spec(
            field_name,
            seller=model.seller,
            document_type=model.document_type,
        )
        model_attr = spec.model_attr if spec is not None else None
        if field_name in ship_to_values:
            resolved_values[field_name] = ship_to_values[field_name]
            continue
        if field_name in mfr_addr_values:
            resolved_values[field_name] = mfr_addr_values[field_name]
            continue
        if field_name in _SPLIT_CONTINUATION_FIELDS:
            continue

        if model_attr:
            value = getattr(model, model_attr, None)
            if value is not None:
                if isinstance(value, date):
                    resolved_values[field_name] = value.strftime("%Y-%m-%d")
                else:
                    resolved_values[field_name] = str(value)
                continue

        if field_name in HEADER_DATE_KEYS:
            resolved_values[field_name] = date.today().strftime("%Y-%m-%d")
        elif field_name in HEADER_MANUAL_KEYS:
            resolved_values[field_name] = HEADER_MANUAL_PLACEHOLDERS.get(field_name, "")

    return resolved_values


def header_source_sheet(field_name: str) -> str:
    spec = HEADER_FIELD_SPECS.get(field_name)
    return spec.source_sheet if spec and spec.source_sheet else SHEET_PO_RECORD


def header_source_field(field_name: str) -> str:
    spec = HEADER_FIELD_SPECS.get(field_name)
    return spec.source_field if spec and spec.source_field else field_name
