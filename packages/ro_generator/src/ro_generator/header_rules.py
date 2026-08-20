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
from ro_generator.profiles.runtime import current_rules, current_schema, current_source_location
from ro_generator.schema import SHEET_CUSTOMER_PO, SHEET_DATA_BASE, SHEET_PO_RECORD

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
HEADER_MANUAL_KEYS: Final[frozenset[str]] = frozenset({"number_of_cartons"})
HEADER_MANUAL_PLACEHOLDERS: Final[dict[str, str]] = {"number_of_cartons": ""}
_SPLIT_CONTINUATION_FIELDS: Final[frozenset[str]] = frozenset(
    (*SHIP_TO_HEADER_FIELDS[1:], "manufacturer_address_2")
)

HEADER_FIELD_SPECS: Final[dict[str, HeaderFieldSpec]] = {
    "invoice_no": HeaderFieldSpec(
        label="Invoice No.",
        source_type="base_field",
        source_sheet=SHEET_PO_RECORD,
        source_field="inv_no",
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
        source_field="purchasing_document",
        rule="客户PO 的 Purchasing Document 列",
        model_attr="po_no",
        render_keys=("po_no",),
    ),
    "document_date": HeaderFieldSpec(
        label="Document Date",
        source_type="system_generated",
        source_sheet=None,
        source_field=None,
        rule="预览时自动填入程序运行当天日期",
        model_attr=None,
        render_keys=("document_date",),
    ),
    "etd_baseline": HeaderFieldSpec(
        label="ETD (Baseline Date for FOB Term)",
        source_type="template_content",
        source_sheet=None,
        source_field=None,
        rule="模板固定文本",
        model_attr=None,
        render_keys=("etd_baseline",),
    ),
    "ship_to": HeaderFieldSpec(
        label="Ship To",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship_to",
        rule="客户PO 的 ship to 列；优先按当前 PO 行的 SAP/Material 精确匹配，找不到时回退到同 PO 的首个非空值",
        model_attr="ship_to",
        render_keys=("ship_to", "bill_to"),
    ),
    "ship_to_line2": HeaderFieldSpec(
        label="Ship To",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship_to",
        rule="客户PO 的 ship to 列拆分后的第 2 行，按与 ship_to 相同的来源规则生成",
        model_attr="ship_to",
        render_keys=("ship_to_line2",),
    ),
    "ship_to_line3": HeaderFieldSpec(
        label="Ship To",
        source_type="base_field",
        source_sheet=SHEET_CUSTOMER_PO,
        source_field="ship_to",
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
        source_field="ship_date",
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
                "source_field": "final_ex_factory_date",
                "rule": 'PO record 的 "FINAL EX-FACTORY DATE" 列',
            },
        ),
    ],
    "pi_no": [
        (
            frozenset({"SK"}),
            {
                "source_sheet": SHEET_PO_RECORD,
                "source_field": "e10_po",
                "rule": 'PO record 的 "E10 PO" 列，必填',
            },
        ),
        (
            frozenset({"YM"}),
            {
                "source_sheet": SHEET_PO_RECORD,
                "source_field": "ym_po",
                "rule": 'PO record 的 "YM PO" 列，必填',
            },
        ),
        (
            frozenset({"GS PTE"}),
            {
                "source_sheet": SHEET_CUSTOMER_PO,
                "source_field": "purchasing_document",
                "rule": '客户PO A列 "Purchasing Document"',
            },
        ),
    ],
}

_HEADER_CONTEXT_OVERRIDES: Final[dict[tuple[str, str, str], HeaderFieldOverride]] = {
    ("PI", "EMAX PTE", "pi_no"): {
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "purchasing_document",
        "rule": '客户PO A列 "Purchasing Document"',
    },
    ("PI", "EMAX PTE", "ex_factory_date"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "final_ex_factory_date",
        "rule": 'PO record 的 "FINAL EX-FACTORY DATE" 列',
    },
    ("INVOICE", "EMAX PTE", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "inv_no",
        "rule": 'PO record 的 "INV#" 列 + "-P"',
    },
    ("PL", "EMAX PTE", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "inv_no",
        "rule": '引用 Invoice，最终来自 PO record 的 "INV#" 列 + "-P"',
    },
    ("INVOICE", "SK", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": 'PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("PL", "SK", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": '引用 Invoice，最终来自 PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("INVOICE", "YM", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": 'PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("PL", "YM", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": '引用 Invoice，最终来自 PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("INVOICE", "SK", "to"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "final_destination",
        "rule": '客户PO Z列 "final destination"',
        "model_attr": "final_destination",
    },
    ("INVOICE", "YM", "to"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "final_destination",
        "rule": '客户PO Z列 "final destination"',
        "model_attr": "final_destination",
    },
    ("CI", "SK", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": 'PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("RO_PL", "SK", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": '引用 Commercial Invoice，最终来自 PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("CI", "YM", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": 'PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("RO_PL", "YM", "invoice_no"): {
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "sk_ym_invoice_no",
        "rule": '引用 Commercial Invoice，最终来自 PO record 的 "SK/YM INVOICE NO." 列',
    },
    ("CI", "SK", "to"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "final_destination",
        "rule": '客户PO Z列 "final destination"',
        "model_attr": "final_destination",
    },
    ("CI", "YM", "to"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "final_destination",
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

_PROFILE_HEADER_OVERRIDES: Final[dict[tuple[str, str, str, str], HeaderFieldOverride]] = {
    ("pf", "INVOICE", "GS PTE", "invoice_no"): {
        "source_type": "base_field",
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "inv_no",
        "rule": 'PO RECORD A列 "INV#"，按 INV# 筛选',
        "model_attr": "invoice_no",
    },
    ("pf", "INVOICE", "GS PTE", "etd_baseline"): {
        "source_type": "base_field",
        "source_sheet": SHEET_PO_RECORD,
        "source_field": "etd_on_board",
        "rule": 'PO RECORD Y列 "ETD ON BOARD"，按 INV# 筛选',
        "model_attr": "etd_on_board",
    },
    ("pf", "PI", "GS PTE", "pi_no"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "purchasing_document",
        "rule": 'new PO template F列 "PO#"',
        "model_attr": "pi_no",
    },
    ("pf", "PO", "GS PTE", "po_no"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "purchasing_document",
        "rule": 'new PO template F列 "PO#"',
        "model_attr": "po_no",
    },
    ("pf", "PO", "EMAX PTE", "po_no"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "purchasing_document",
        "rule": 'new PO template F列 "PO#"',
        "model_attr": "po_no",
    },
    ("pf", "PI", "GS PTE", "document_date"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "document_date",
        "rule": 'new PO template A列 "PO Creation Date"',
        "model_attr": "document_date",
    },
    ("pf", "PI", "EMAX PTE", "document_date"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "document_date",
        "rule": 'new PO template A列 "PO Creation Date"',
        "model_attr": "document_date",
    },
    ("pf", "PO", "GS PTE", "document_date"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "document_date",
        "rule": 'new PO template A列 "PO Creation Date"',
        "model_attr": "document_date",
    },
    ("pf", "PO", "EMAX PTE", "document_date"): {
        "source_type": "base_field",
        "source_sheet": SHEET_CUSTOMER_PO,
        "source_field": "document_date",
        "rule": 'new PO template A列 "PO Creation Date"',
        "model_attr": "document_date",
    },
    ("pf", "PI", "GS PTE", "manufacturer"): {
        "source_type": "manual_input",
        "source_sheet": None,
        "source_field": None,
        "rule": "模板留空，业务手工维护",
        "model_attr": None,
    },
    ("pf", "PI", "GS PTE", "manufacturer_address"): {
        "source_type": "manual_input",
        "source_sheet": None,
        "source_field": None,
        "rule": "模板留空，业务手工维护",
        "model_attr": None,
    },
    ("pf", "PI", "GS PTE", "manufacturer_address_2"): {
        "source_type": "manual_input",
        "source_sheet": None,
        "source_field": None,
        "rule": "模板留空，业务手工维护",
        "model_attr": None,
    },
    ("pf", "PO", "GS PTE", "manufacturer"): {
        "source_type": "computed",
        "source_sheet": SHEET_DATA_BASE,
        "source_field": "category",
        "rule": "按 DATA BASE Category：Single Reel 使用 Globalsino，Single Rod/Combo 使用 EMAX",
        "model_attr": "manufacturer_name",
    },
    ("pf", "PO", "GS PTE", "manufacturer_address"): {
        "source_type": "computed",
        "source_sheet": SHEET_DATA_BASE,
        "source_field": "category",
        "rule": "按 DATA BASE Category 选择对应制造商地址第 1 行",
        "model_attr": "manufacturer_company_address",
    },
    ("pf", "PO", "GS PTE", "manufacturer_address_2"): {
        "source_type": "computed",
        "source_sheet": SHEET_DATA_BASE,
        "source_field": "category",
        "rule": "按 DATA BASE Category 选择对应制造商地址第 2 行",
        "model_attr": "manufacturer_company_address_2",
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
        spec = replace(spec, **context_kwargs)
    profile_kwargs = _PROFILE_HEADER_OVERRIDES.get(
        (current_rules().profile_id, document_type, seller, field_name)
    )
    if profile_kwargs:
        spec = replace(spec, **profile_kwargs)
    if field_name == "ex_factory_date":
        logical_sheet, internal_field = current_rules().ex_factory_source(
            document_type,
            seller,
            "header",
        )
        source_sheet = current_schema().sheet(logical_sheet).name
        source_field = current_schema().field(logical_sheet, internal_field)
        rule = f'{source_sheet} 的 "{source_field}" 列'
        if (
            current_rules().profile_id == "pf"
            and document_type in {"INVOICE", "PL"}
            and seller == "GS PTE"
        ):
            rule = f'{source_sheet} 的 "{source_field}" 列，按 INV# 筛选'
        spec = replace(
            spec,
            source_sheet=source_sheet,
            source_field=source_field,
            rule=rule,
        )
    resolved_source_sheet, resolved_source_field = current_source_location(
        spec.source_sheet,
        spec.source_field,
    )
    return replace(
        spec,
        source_sheet=resolved_source_sheet,
        source_field=resolved_source_field,
    )


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
    if model.manufacturer_name is not None:
        mfr_addr_values = {
            field_name: value
            for field_name, value in {
                "manufacturer_address": model.manufacturer_company_address,
                "manufacturer_address_2": model.manufacturer_company_address_2,
            }.items()
            if value and field_name in header_key_list
        }
    else:
        mfr_address = model.manufacturer_address
        mfr_addr_values = build_manufacturer_address_values(mfr_address, header_key_list)
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
        if field_name in HEADER_MANUAL_KEYS or (
            spec is not None and spec.source_type == "manual_input"
        ):
            resolved_values[field_name] = HEADER_MANUAL_PLACEHOLDERS.get(field_name, "")
            continue
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

        if field_name in HEADER_DATE_KEYS and (spec is None or spec.model_attr is None):
            resolved_values[field_name] = date.today().strftime("%Y-%m-%d")

    return resolved_values


def header_source_sheet(field_name: str) -> str:
    spec = HEADER_FIELD_SPECS.get(field_name)
    return spec.source_sheet if spec and spec.source_sheet else SHEET_PO_RECORD


def header_source_field(field_name: str) -> str:
    spec = HEADER_FIELD_SPECS.get(field_name)
    return spec.source_field if spec and spec.source_field else field_name


def is_system_generated_header_field(
    field_name: str,
    *,
    seller: str,
    document_type: str,
) -> bool:
    """判断日期表头是否仍由系统生成，而非由 Profile 声明的来源字段提供。"""

    if field_name not in HEADER_DATE_KEYS:
        return False
    spec = resolve_header_field_spec(
        field_name,
        seller=seller,
        document_type=document_type,
    )
    return spec is None or spec.model_attr is None
