"""当前 RO Profile 的声明。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from ro_generator.base_schema import BaseSchema, load_base_schema
from ro_generator.errors import InvalidProfileError
from ro_generator.models import CostBreakdownItem, DocumentType, OrderLine
from ro_generator.profiles.base import (
    CustomerProfile,
    ProfileAssets,
    ProfileCapabilities,
)
from ro_generator.profiles.manifest import (
    load_profile_assets,
    load_profile_manifest,
    manifest_string,
)
from ro_generator.resources import profile_root
from ro_generator.schema import (
    DATA_BASE_PRICE_COLUMNS,
    SELLER_PRICE_COLUMNS,
    SELLER_TO_BUYER,
    SELLERS,
)

RO_PROFILE_ID = "ro"
RO_PROFILE_DISPLAY_NAME = "Rather Outdoors"
RO_PROFILE_VERSION = "ro_v1"


@dataclass(frozen=True)
class RoRules:
    """RO 当前字段、价格和数量来源规则的声明式目录。"""

    profile_id: str = RO_PROFILE_ID
    seller_to_buyer: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(dict(SELLER_TO_BUYER))
    )
    quantity_source_by_document: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(
            {
                "PI": "customer_po.order_quantity",
                "PO": "customer_po.order_quantity",
                "INVOICE": "po_record.ship_qty",
                "PL": "po_record.ship_qty",
                "CI": "po_record.ship_qty",
                "RO_PL": "po_record.ship_qty",
            }
        )
    )
    po_price_columns: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(dict(SELLER_PRICE_COLUMNS))
    )
    data_base_price_columns: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(dict(DATA_BASE_PRICE_COLUMNS))
    )
    invoice_data_base_price_columns: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    data_base_component_price_columns: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    rule_modules: tuple[str, ...] = (
        "ro_generator.schema",
        "ro_generator.line_rules",
        "ro_generator.header_rules",
        "ro_generator.totals_rules",
        "ro_generator.seller_filter",
        "ro_generator.invoice_groups",
        "ro_generator.packager",
    )
    filename_strategy: str = "ro_standard_packager_v1"
    invoice_grouping_strategy: str = "ro_invoice_groups_v1"
    order_constraint_checks: tuple[str, ...] = ()
    include_customer_po_only_orders: bool = False

    def buyer_for(self, seller: str) -> str | None:
        return self.seller_to_buyer.get(seller)

    def category_for_value(self, value: object) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else None
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    def shipment_quantity_for_row(
        self,
        row: Mapping[str, object],
        schema: BaseSchema,
    ) -> tuple[object | None, str]:
        field = schema.field("PO record", "ship_qty")
        return row.get(field), field

    def packing_values_for_line(
        self,
        line: OrderLine,
        quantity: Decimal,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        del quantity
        cartons = line.carton_count
        return (
            cartons,
            _carton_total(line.net_weight, cartons),
            _carton_total(line.gross_weight, cartons),
            line.total_cbm,
        )

    def packing_weight_source_for_line(
        self,
        line: OrderLine,
        field: str,
    ) -> tuple[str, str, str]:
        label = "N/W" if field == "net_weight" else "G/W"
        po_total = line.po_net_weight if field == "net_weight" else line.po_gross_weight
        if po_total is not None:
            return "PO record", field, f"PO record 的 {label} 列 × CTNS（箱数）"
        return "DATA BASE", field, f"DATA BASE 的 {label} 列 × CTNS（箱数）"

    def price_segment(
        self,
        document_type: str,
        seller: str,
        buyer: str,
    ) -> tuple[str, str]:
        overrides = {
            ("PO", "GS PTE"): ("YM", "GS PTE"),
            ("PO", "EMAX PTE"): ("GS PTE", "EMAX PTE"),
        }
        return overrides.get((document_type, seller), (seller, buyer))

    def uses_po_record_unit_price(self, document_type: str) -> bool:
        return document_type == "INVOICE"

    def unit_price_for_line(
        self,
        line: OrderLine,
        document_type: str,
        segment: tuple[str, str],
    ) -> Decimal | None:
        if self.uses_po_record_unit_price(document_type):
            return line.po_record_prices.get(segment)
        return line.prices.get(segment)

    def pi_no_for_lines(
        self,
        lines: tuple[OrderLine, ...],
        seller: str,
        po_no: str,
    ) -> tuple[str | None, str | None]:
        if seller == "SK":
            return next((line.e10_po for line in lines if line.e10_po), None), "E10 PO"
        if seller == "YM":
            return next((line.ym_po for line in lines if line.ym_po), None), "YM PO"
        return po_no, None

    def invoice_no_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> str | None:
        if document_type in {"INVOICE", "PL", "CI", "RO_PL"} and seller in {"SK", "YM"}:
            return line.sk_ym_invoice_no
        if document_type in {"INVOICE", "PL", "CI", "RO_PL"} and seller == "EMAX PTE":
            if not line.invoice_no:
                return None
            return line.invoice_no if line.invoice_no.endswith("-P") else f"{line.invoice_no}-P"
        return line.invoice_no

    def invoice_no_matches(
        self,
        line: OrderLine,
        requested_invoice_no: str,
        document_type: str,
        seller: str,
    ) -> bool:
        resolved = self.invoice_no_for_line(line, document_type, seller)
        if resolved == requested_invoice_no:
            return True
        return (
            document_type in {"INVOICE", "PL", "CI", "RO_PL"}
            and seller == "EMAX PTE"
            and line.invoice_no == requested_invoice_no
        )

    def header_ex_factory_date_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> date | None:
        if seller in {"SK", "YM", "GS PTE"} or (document_type == "PI" and seller == "EMAX PTE"):
            return line.po_ex_factory_date
        return line.confirmed_ex_factory_date

    def line_ex_factory_date_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> date | None:
        if document_type == "PO" and seller == "GS PTE":
            return line.confirmed_ex_factory_date
        if seller in {"SK", "YM", "GS PTE"} or (document_type == "PI" and seller == "EMAX PTE"):
            return line.po_ex_factory_date
        return line.confirmed_ex_factory_date

    def ex_factory_source(
        self,
        document_type: str,
        seller: str,
        scope: str,
    ) -> tuple[str, str]:
        if scope == "line" and document_type == "PO" and seller == "GS PTE":
            return "客户PO", "ship_date"
        if seller in {"SK", "YM", "GS PTE"} or (document_type == "PI" and seller == "EMAX PTE"):
            return "PO record", "final_ex_factory_date"
        return "客户PO", "ship_date"

    def manufacturer_header_values(
        self,
        lines: tuple[OrderLine, ...],
        document_type: str,
        seller: str,
    ) -> tuple[str | None, str | None, str | None]:
        del lines, document_type, seller
        return None, None, None

    def cost_breakdown_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> tuple[CostBreakdownItem, ...]:
        del line, document_type, seller
        return ()


def _carton_total(value_per_carton: Decimal | None, cartons: Decimal | None) -> Decimal | None:
    if value_per_carton is None or cartons is None:
        return None
    return (value_per_carton * cartons).quantize(Decimal("0.01"))


def create_ro_profile() -> CustomerProfile:
    """从 ``customer_profiles/ro/profile.yaml`` 构造默认 RO Profile。"""

    root = profile_root(RO_PROFILE_ID)
    manifest_path = root / "profile.yaml"
    manifest = load_profile_manifest(root)
    profile_id = manifest_string(manifest, "profile_id", manifest_path)
    display_name = manifest_string(manifest, "display_name", manifest_path)
    version = manifest_string(manifest, "version", manifest_path)
    if profile_id != RO_PROFILE_ID:
        raise InvalidProfileError(
            f"Profile manifest profile_id 必须是 {RO_PROFILE_ID!r}：{manifest_path}"
        )
    (
        schema_path,
        template_root,
        mapping_root,
        seller_directories,
        mapping_filenames,
    ) = load_profile_assets(root, manifest)
    supported_documents: dict[str, tuple[DocumentType, ...]] = {
        "GS PTE": ("PI", "PO", "INVOICE", "PL"),
        "EMAX PTE": ("PI", "PO", "INVOICE", "PL"),
        "SK": ("PI", "INVOICE", "PL", "CI", "RO_PL"),
        "YM": ("PI", "INVOICE", "PL", "CI", "RO_PL"),
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
        schema=load_base_schema(schema_path),
        rules=RoRules(),
        capabilities=ProfileCapabilities(
            sellers=SELLERS,
            supported_documents_by_seller=supported_documents,
            currencies=("USD",),
        ),
    )
