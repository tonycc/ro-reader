"""PF Customer Profile 的字段、数量、定价和单据能力规则。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from ro_generator.base_schema import BaseSchema, load_base_schema
from ro_generator.errors import InvalidProfileError
from ro_generator.models import CostBreakdownItem, DocumentType, OrderLine
from ro_generator.profiles.base import CustomerProfile, ProfileAssets, ProfileCapabilities
from ro_generator.profiles.manifest import (
    load_profile_assets,
    load_profile_manifest,
    manifest_string,
)
from ro_generator.resources import profile_root
from ro_generator.schema import CATEGORY_NAMES, SELLER_TO_BUYER, SELLERS

PF_PROFILE_ID = "pf"
PF_PROFILE_DISPLAY_NAME = "PF"
PF_PROFILE_VERSION = "pf_v1"
_MONTH_COLUMNS = tuple(f"26{month:02d}" for month in range(1, 13))
_INVOICE_MONTH_RE = re.compile(r"(?<!\d)(\d{4})")
_CATEGORY_ALIASES = MappingProxyType(
    {
        "combo": 1,
        "single rod": 2,
        "rod": 2,
        "single reel": 3,
        "reel": 3,
    }
)

_GLOBALSINO_MANUFACTURER = (
    "GUANGDONG GLOBALSINO OUTDOOR SPORTS EQUIPMENT LIMITED",
    "NO.40 BAIJIA ST12 NO. 93 GRAPE BEACH ROAD",
    "DEVELOPMENT ZONE QINGYUAN GUANGDONG CHINA",
)
_EMAX_MANUFACTURER = (
    "WEIHAI E-MAX SPORT APPARATUS CO.LTD",
    "NO. 93 GRAPE BEACH ROAD",
    "SUNJIATUAN TOWN, WEIHAI, SHANGDONG, CHINA",
)


@dataclass(frozen=True)
class PfRules:
    """PF 的客户差异策略；不保存 workbook 或 session 状态。"""

    profile_id: str = PF_PROFILE_ID
    seller_to_buyer: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(dict(SELLER_TO_BUYER))
    )
    quantity_source_by_document: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(
            {
                "PI": "customer_po.order_quantity",
                "PO": "customer_po.order_quantity",
                "INVOICE": "po_record.invoice_month_quantity",
                "PL": "po_record.invoice_month_quantity",
            }
        )
    )
    po_price_columns: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    data_base_price_columns: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    invoice_data_base_price_columns: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    data_base_component_price_columns: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    rule_modules: tuple[str, ...] = (
        "ro_generator.profiles.pf",
        "ro_generator.order_constraints",
        "ro_generator.line_rules",
        "ro_generator.header_rules",
        "ro_generator.totals_rules",
        "ro_generator.packager",
    )
    filename_strategy: str = "ro_standard_packager_v1"
    invoice_grouping_strategy: str = "ro_invoice_groups_v1"
    order_constraint_checks: tuple[str, ...] = ("moq", "full_carton")
    include_customer_po_only_orders: bool = True

    def buyer_for(self, seller: str) -> str | None:
        return self.seller_to_buyer.get(seller)

    def category_for_value(self, value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value in {1, 2, 3}:
            return value
        if isinstance(value, str):
            return _CATEGORY_ALIASES.get(" ".join(value.strip().casefold().split()))
        return None

    def shipment_quantity_for_row(
        self,
        row: Mapping[str, object],
        schema: BaseSchema,
    ) -> tuple[object | None, str]:
        invoice_field = schema.field("PO record", "inv_no")
        raw_invoice = row.get(invoice_field)
        invoice_no = str(raw_invoice).strip() if raw_invoice is not None else ""
        match = _INVOICE_MONTH_RE.search(invoice_no)
        if match and match.group(1) in _MONTH_COLUMNS:
            month_field = match.group(1)
            return row.get(month_field), month_field

        populated = [
            month_field
            for month_field in _MONTH_COLUMNS
            if row.get(month_field) not in (None, "", 0)
        ]
        if len(populated) == 1:
            month_field = populated[0]
            return row.get(month_field), month_field
        fallback = schema.field("PO record", "ship_qty")
        return row.get(fallback), fallback

    def packing_values_for_line(
        self,
        line: OrderLine,
        quantity: Decimal,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        carton_size = line.product.carton_qty
        if carton_size is None or carton_size == 0:
            return None, None, None, None

        shipment_cartons = quantity / carton_size
        net_weight = _scaled_packing_total(
            line.net_weight,
            line.carton_count,
            shipment_cartons,
            line.product.net_weight,
            Decimal("0.01"),
        )
        gross_weight = _scaled_packing_total(
            line.gross_weight,
            line.carton_count,
            shipment_cartons,
            line.product.gross_weight,
            Decimal("0.01"),
        )
        cbm_per_carton = _dimension_cbm(line)
        total_cbm = (
            (cbm_per_carton * shipment_cartons).quantize(Decimal("0.0001"))
            if cbm_per_carton is not None
            else _scaled_packing_total(
                line.total_cbm,
                line.carton_count,
                shipment_cartons,
                None,
                Decimal("0.0001"),
            )
        )
        return shipment_cartons, net_weight, gross_weight, total_cbm

    def price_segment(
        self,
        document_type: str,
        seller: str,
        buyer: str,
    ) -> tuple[str, str]:
        overrides = {
            ("PO", "GS PTE"): ("YM", "GS PTE"),
        }
        return overrides.get((document_type, seller), (seller, buyer))

    def uses_po_record_unit_price(self, document_type: str) -> bool:
        del document_type
        return False

    def unit_price_for_line(
        self,
        line: OrderLine,
        document_type: str,
        segment: tuple[str, str],
    ) -> Decimal | None:
        if document_type in {"INVOICE", "PL"} and self.invoice_data_base_price_columns:
            category_name = CATEGORY_NAMES.get(line.category, "")
            return line.product.invoice_prices.get(f"{segment[0]}/{category_name}")
        return line.prices.get(segment)

    def pi_no_for_lines(
        self,
        lines: tuple[OrderLine, ...],
        seller: str,
        po_no: str,
    ) -> tuple[str | None, str | None]:
        del seller
        customer_po_no = next((line.customer_po_no for line in lines if line.customer_po_no), None)
        return customer_po_no or po_no, None

    def invoice_no_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> str | None:
        del document_type, seller
        return line.invoice_no

    def invoice_no_matches(
        self,
        line: OrderLine,
        requested_invoice_no: str,
        document_type: str,
        seller: str,
    ) -> bool:
        return self.invoice_no_for_line(line, document_type, seller) == requested_invoice_no

    def header_ex_factory_date_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> date | None:
        if document_type in {"INVOICE", "PL"}:
            return line.actual_ex_factory_date or line.po_ex_factory_date
        if seller in {"SK", "YM"} or (document_type == "PI" and seller == "EMAX PTE"):
            return line.po_ex_factory_date
        return line.confirmed_ex_factory_date

    def line_ex_factory_date_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> date | None:
        if document_type in {"INVOICE", "PL"}:
            return line.actual_ex_factory_date or line.po_ex_factory_date
        if document_type == "PO" and seller == "GS PTE":
            return line.confirmed_ex_factory_date
        if document_type == "PI" and seller == "GS PTE":
            return line.po_ex_factory_date
        if seller in {"SK", "YM"} or (document_type == "PI" and seller == "EMAX PTE"):
            return line.po_ex_factory_date
        return line.confirmed_ex_factory_date

    def ex_factory_source(
        self,
        document_type: str,
        seller: str,
        scope: str,
    ) -> tuple[str, str]:
        if document_type in {"INVOICE", "PL"}:
            return "PO record", "actual_ex_factory_date"
        if scope == "line" and document_type == "PO" and seller == "GS PTE":
            return "客户PO", "ship_date"
        if seller in {"SK", "YM"} or (document_type == "PI" and seller in {"GS PTE", "EMAX PTE"}):
            return "PO record", "final_ex_factory_date"
        return "客户PO", "ship_date"

    def manufacturer_header_values(
        self,
        lines: tuple[OrderLine, ...],
        document_type: str,
        seller: str,
    ) -> tuple[str | None, str | None, str | None]:
        if document_type not in {"PI", "PO"} or seller != "GS PTE":
            return None, None, None
        category = next((line.category for line in lines if line.category in {1, 2, 3}), None)
        if category == 3:
            return _GLOBALSINO_MANUFACTURER
        if category in {1, 2}:
            return _EMAX_MANUFACTURER
        return None, None, None

    def cost_breakdown_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> tuple[CostBreakdownItem, ...]:
        """PF GS PTE Invoice 的 Combo 组件价格拆分。"""

        if document_type != "INVOICE" or seller != "GS PTE":
            return ()
        # Invoice 截图的业务规则以 PO RECORD CATEGORY 识别 Combo；部分旧行没有
        # 该列时再回退到 DATA BASE 品类，避免把非 Combo 行错误拆分。
        category = line.po_record_category or line.category
        if category != 1:
            return ()
        items: list[CostBreakdownItem] = []
        for component in ("rod", "reel"):
            key = f"{seller}/{component}"
            source_field = self.data_base_component_price_columns.get(key)
            if not source_field:
                continue
            price = line.product.component_prices.get(key)
            if price is None:
                continue
            items.append(
                CostBreakdownItem(
                    component=component.upper() + "S",
                    unit_price=price,
                    source_field=source_field,
                )
            )
        return tuple(items)


def _dimension_cbm(line: OrderLine) -> Decimal | None:
    product = line.product
    if product.length is None or product.width is None or product.height is None:
        return product.cbm
    return product.length * product.width * product.height / Decimal("1000000")


def _scaled_packing_total(
    source_total: Decimal | None,
    source_cartons: Decimal | None,
    shipment_cartons: Decimal,
    fallback_per_carton: Decimal | None,
    quantum: Decimal,
) -> Decimal | None:
    per_carton: Decimal | None
    if source_total is not None and source_cartons is not None and source_cartons != Decimal("0"):
        per_carton = source_total / source_cartons
    else:
        per_carton = fallback_per_carton
    if per_carton is None:
        return None
    return (per_carton * shipment_cartons).quantize(quantum)


def create_pf_profile() -> CustomerProfile:
    root = profile_root(PF_PROFILE_ID)
    manifest_path = root / "profile.yaml"
    manifest = load_profile_manifest(root)
    profile_id = manifest_string(manifest, "profile_id", manifest_path)
    display_name = manifest_string(manifest, "display_name", manifest_path)
    version = manifest_string(manifest, "version", manifest_path)
    if profile_id != PF_PROFILE_ID:
        raise InvalidProfileError(
            f"Profile manifest profile_id 必须是 {PF_PROFILE_ID!r}：{manifest_path}"
        )
    (
        schema_path,
        template_root,
        mapping_root,
        seller_directories,
        mapping_filenames,
    ) = load_profile_assets(root, manifest)
    schema = load_base_schema(schema_path)
    supported_documents: dict[str, tuple[DocumentType, ...]] = {
        "GS PTE": ("PI", "PO", "INVOICE", "PL"),
        "EMAX PTE": ("PI", "PO", "INVOICE", "PL"),
        "SK": ("PI",),
        "YM": ("PI",),
    }
    return CustomerProfile(
        profile_id=profile_id,
        display_name=display_name,
        version=version,
        assets=ProfileAssets(
            root=root,
            schema_path=schema_path,
            template_root=template_root,
            mapping_root=mapping_root,
            seller_directories=seller_directories,
            mapping_filenames=mapping_filenames,
        ),
        schema=schema,
        rules=PfRules(
            po_price_columns=MappingProxyType(dict(schema.price_columns)),
            data_base_price_columns=MappingProxyType(dict(schema.data_base_price_columns)),
            invoice_data_base_price_columns=MappingProxyType(
                dict(schema.invoice_data_base_price_columns)
            ),
            data_base_component_price_columns=MappingProxyType(
                dict(schema.data_base_component_price_columns)
            ),
        ),
        capabilities=ProfileCapabilities(
            sellers=SELLERS,
            supported_documents_by_seller=supported_documents,
            currencies=("USD",),
        ),
    )


__all__ = ["PF_PROFILE_ID", "PfRules", "create_pf_profile"]
