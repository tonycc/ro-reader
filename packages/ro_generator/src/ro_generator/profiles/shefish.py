"""SHEFISH：Item Number、月度出货和分别向杆/轮工厂采购。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from ro_generator.base_schema import BaseSchema, load_base_schema
from ro_generator.errors import InvalidProfileError
from ro_generator.models import OrderLine
from ro_generator.profiles.base import (
    CustomerProfile,
    DocumentVariant,
    ProfileAssets,
    ProfileCapabilities,
)
from ro_generator.profiles.manifest import (
    load_profile_assets,
    load_profile_manifest,
    manifest_string,
)
from ro_generator.profiles.ro import RoRules
from ro_generator.resources import profile_root


@dataclass(frozen=True)
class ShefishRules(RoRules):
    profile_id: str = "shefish"
    seller_to_buyer: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(
            {"SK": "GS PTE", "YM": "GS PTE", "GS PTE": "EMAX PTE", "EMAX PTE": "SHEFISH"}
        )
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
    rule_modules: tuple[str, ...] = (
        "ro_generator.profiles.shefish",
        "ro_generator.line_rules",
        "ro_generator.header_rules",
        "ro_generator.totals_rules",
        "ro_generator.packager",
    )
    include_customer_po_only_orders: bool = True

    def category_for_value(self, value: object) -> int | None:
        if isinstance(value, str):
            aliases = {"combo": 1, "rod": 2, "single rod": 2, "reel": 3, "single reel": 3}
            category = aliases.get(" ".join(value.strip().casefold().split()))
            if category is not None:
                return category
        return super().category_for_value(value)

    def factory_sellers_for_category(self, category: int | None) -> tuple[str, ...]:
        return {1: ("SK", "YM"), 2: ("YM",), 3: ("SK",)}.get(category or 0, ())

    def document_variants(
        self, document_type: str, seller: str, lines: tuple[OrderLine, ...]
    ) -> tuple[DocumentVariant, ...]:
        if document_type != "PO" or seller != "GS PTE":
            return ()
        return tuple(
            DocumentVariant(factory, f"PURCHASE ORDER · {factory}", mapping, factory)
            for factory, mapping in (("SK", "PO_SK"), ("YM", "PO_YM"))
            if any(
                factory
                in self.factory_sellers_for_category(line.po_record_category or line.category)
                for line in lines
            )
        )

    def shipment_quantity_for_row(
        self, row: Mapping[str, object], schema: BaseSchema
    ) -> tuple[object | None, str]:
        invoice_no = str(row.get(schema.field("PO record", "inv_no")) or "")
        match = re.search(r"(?<!\d)(\d{2}(?:0[1-9]|1[0-2]))", invoice_no)
        # 只按明确的发票月份取数量；不能把另一月份的出货算到当前发票。
        column = match.group(1) if match else schema.field("PO record", "ship_qty")
        return row.get(column), column

    def uses_po_record_unit_price(self, document_type: str) -> bool:
        return False

    def price_segment(self, document_type: str, seller: str, buyer: str) -> tuple[str, str]:
        if document_type == "PO" and seller == "EMAX PTE":
            return "GS PTE", "EMAX PTE"
        if document_type == "PO" and seller == "GS PTE":
            return "SK", "GS PTE"
        return seller, buyer

    def pi_no_for_lines(
        self, lines: tuple[OrderLine, ...], seller: str, po_no: str
    ) -> tuple[str | None, str | None]:
        # SHEFISH PI Number 统一取 PO RECORD PI#；客户 PO# 由 header.po_no 另写。
        _ = (seller, po_no)
        return next((line.pi_no for line in lines if line.pi_no), None), "PI#"

    def invoice_no_for_line(self, line: OrderLine, document_type: str, seller: str) -> str | None:
        return line.invoice_no

    def header_ex_factory_date_for_line(
        self, line: OrderLine, document_type: str, seller: str
    ) -> date | None:
        return line.po_ex_factory_date

    def line_ex_factory_date_for_line(
        self, line: OrderLine, document_type: str, seller: str
    ) -> date | None:
        return line.po_ex_factory_date

    def ex_factory_source(self, document_type: str, seller: str, scope: str) -> tuple[str, str]:
        return "PO record", "final_ex_factory_date"

    def packing_values_for_line(
        self, line: OrderLine, quantity: Decimal
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        carton_size = line.product.carton_qty
        cartons = quantity / carton_size if carton_size else None
        net = (
            (line.net_weight * cartons).quantize(Decimal("0.01"))
            if line.net_weight is not None and cartons is not None
            else None
        )
        gross = (
            (line.gross_weight * cartons).quantize(Decimal("0.01"))
            if line.gross_weight is not None and cartons is not None
            else None
        )
        product = line.product
        cbm = product.cbm
        if product.length is not None and product.width is not None and product.height is not None:
            cbm = product.length * product.width * product.height / Decimal("1000000")
        return (
            cartons,
            net,
            gross,
            (cbm * cartons).quantize(Decimal("0.0001"))
            if cbm is not None and cartons is not None
            else None,
        )

    def packing_weight_source_for_line(self, line: OrderLine, field: str) -> tuple[str, str, str]:
        label = "N/W" if field == "net_weight" else "G/W"
        value = line.po_net_weight if field == "net_weight" else line.po_gross_weight
        sheet = "PO record" if value is not None else "DATA BASE"
        return sheet, field, f"{label} 单箱重量 × 本月出货箱数（出货数量 / round value）"


def create_shefish_profile() -> CustomerProfile:
    root = profile_root("shefish")
    manifest = load_profile_manifest(root)
    path = root / "profile.yaml"
    profile_id = manifest_string(manifest, "profile_id", path)
    if profile_id != "shefish":
        raise InvalidProfileError(f"SHEFISH manifest profile_id 不匹配：{path}")
    schema_path, template_root, mapping_root, sellers, mappings = load_profile_assets(
        root, manifest
    )
    schema = load_base_schema(schema_path)
    return CustomerProfile(
        profile_id=profile_id,
        display_name=manifest_string(manifest, "display_name", path),
        version=manifest_string(manifest, "version", path),
        assets=ProfileAssets(root, schema_path, template_root, mapping_root, sellers, mappings),
        schema=schema,
        rules=ShefishRules(
            po_price_columns=MappingProxyType(dict(schema.price_columns)),
            data_base_price_columns=MappingProxyType(dict(schema.data_base_price_columns)),
        ),
        capabilities=ProfileCapabilities(
            sellers=("GS PTE", "EMAX PTE", "SK"),
            supported_documents_by_seller={
                "GS PTE": ("PI", "PO", "INVOICE", "PL"),
                "EMAX PTE": ("PI", "PO", "INVOICE", "PL"),
                "SK": ("PI", "INVOICE", "PL"),
            },
        ),
    )
