"""Customer Profile 模型和注册表测试。"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from ro_generator.errors import (
    DuplicateProfileError,
    InvalidProfileError,
    ProfileNotFoundError,
)
from ro_generator.header_rules import resolve_header_field_spec
from ro_generator.line_rules import resolve_line_field_spec
from ro_generator.models import OrderLine, Product
from ro_generator.profiles import (
    CustomerProfile,
    GenerationContext,
    ProfileCapabilities,
    ProfileRegistry,
    create_pf_profile,
    create_ro_profile,
    current_rules,
    current_schema,
    default_profile_registry,
    profile_scope,
)
from ro_generator.profiles.ro import RoRules
from ro_generator.template_mapping import load_template_mapping


def test_default_registry_exposes_ro_profile() -> None:
    registry = default_profile_registry()

    assert registry.default_profile_id == "ro"
    assert registry.default.profile_id == "ro"
    assert registry.default.display_name == "Rather Outdoors"
    assert [profile.profile_id for profile in registry.list()] == ["ro", "pf"]
    assert registry.default.assets.schema_path.exists()
    assert registry.default.assets.root.name == "ro"
    assert registry.default.schema.sheet("PO record").header_row == 4


def test_ro_profile_loads_every_declared_mapping() -> None:
    profile = create_ro_profile()

    mapping_paths = sorted(profile.assets.mapping_root.glob("*/mappings/*.yaml"))
    assert len(mapping_paths) == 18
    for mapping_path in mapping_paths:
        mapping = load_template_mapping(mapping_path)
        assert mapping.template_path.is_relative_to(profile.assets.root)


def test_ro_packing_weight_source_explains_carton_multiply() -> None:
    profile = create_ro_profile()
    product = Product(
        sap="21-44640",
        description="CB2500.B2",
        category=1,
        carton_qty=Decimal("24"),
        net_weight=Decimal("8.5"),
        gross_weight=Decimal("10.1"),
    )
    line = OrderLine(
        po_no="4500030844",
        item_line_no="10",
        sap=product.sap,
        description=product.description,
        category=product.category,
        quantity=Decimal("100"),
        product=product,
        carton_count=Decimal("5"),
        net_weight=Decimal("8.5"),
        gross_weight=Decimal("10.1"),
        po_net_weight=Decimal("8.5"),
        po_gross_weight=Decimal("10.1"),
    )
    assert profile.rules.packing_values_for_line(line, Decimal("100")) == (
        Decimal("5"),
        Decimal("42.50"),
        Decimal("50.50"),
        None,
    )
    sheet, field, rule = profile.rules.packing_weight_source_for_line(line, "net_weight")
    assert (sheet, field) == ("PO record", "net_weight")
    assert "× CTNS" in rule
    assert "按出货箱数/订单箱数缩放" not in rule


def test_pf_profile_loads_supplied_capability_matrix_and_mappings() -> None:
    profile = create_pf_profile()

    assert profile.profile_id == "pf"
    assert profile.display_name == "PF"
    assert profile.schema.sheet("DATA BASE").name == "DATA BASE TEMPLATE"
    assert profile.schema.sheet("PO record").name == "PO RECORD 26"
    assert profile.schema.sheet("客户PO").name == "new PO template"
    assert profile.capabilities.documents_for("GS PTE") == ("PI", "PO", "INVOICE", "PL")
    assert profile.capabilities.documents_for("SK") == ("PI",)
    assert profile.rules.order_constraint_checks == ("moq", "full_carton")
    assert profile.rules.include_customer_po_only_orders is True

    mapping_paths = sorted(profile.assets.mapping_root.glob("*/mappings/*.yaml"))
    assert len(mapping_paths) == 10
    for mapping_path in mapping_paths:
        mapping = load_template_mapping(mapping_path)
        assert mapping.template_path.is_relative_to(profile.assets.root)
        assert mapping.preview_content.get("column_labels")
        assert mapping.preview_content.get("layout")
        assert mapping.preview_static_values.get("title")
        assert mapping.preview_static_values.get("seller_info")


def test_pf_rules_normalize_text_category_and_invoice_month_quantity() -> None:
    profile = create_pf_profile()

    assert profile.rules.category_for_value("Single Reel") == 3
    assert profile.rules.category_for_value(" single rod ") == 2
    assert profile.rules.category_for_value("Combo") == 1
    assert profile.rules.category_for_value("Handle Assy") is None
    value, field = profile.rules.shipment_quantity_for_row(
        {"INV#": "G26020201A", "2601": None, "2602": 27},
        profile.schema,
    )
    assert (value, field) == (27, "2602")


def test_pf_packing_values_scale_order_totals_to_invoice_month_quantity() -> None:
    profile = create_pf_profile()
    product = Product(
        sap="1609836",
        description="PF reel",
        category=3,
        carton_qty=Decimal("3"),
        net_weight=Decimal("1.12"),
        gross_weight=Decimal("1.70"),
        length=Decimal("119"),
        width=Decimal("10.5"),
        height=Decimal("16.5"),
    )
    line = OrderLine(
        po_no="4500737516",
        item_line_no="10",
        sap=product.sap,
        description=product.description,
        category=product.category,
        quantity=Decimal("0"),
        product=product,
        ship_qty=Decimal("3003"),
        carton_count=Decimal("1015"),
        po_net_weight=Decimal("1136.8"),
        po_gross_weight=Decimal("1725.5"),
        net_weight=Decimal("1136.8"),
        gross_weight=Decimal("1725.5"),
        total_cbm=Decimal("20.92600125"),
    )

    assert profile.rules.packing_values_for_line(line, Decimal("3003")) == (
        Decimal("1001"),
        Decimal("1121.12"),
        Decimal("1701.70"),
        Decimal("20.6374"),
    )


def test_pf_packing_values_use_data_base_per_carton_when_po_weight_missing() -> None:
    """PO RECORD 缺 N/W 时只用 DATA BASE 单箱重量 × 本月出货箱数。"""

    profile = create_pf_profile()
    product = Product(
        sap="1429058",
        description="PF rod",
        category=2,
        carton_qty=Decimal("3"),
        net_weight=Decimal("1.10"),
        gross_weight=Decimal("2.00"),
        length=Decimal("119"),
        width=Decimal("11.5"),
        height=Decimal("17"),
    )
    line = OrderLine(
        po_no="4500754841",
        item_line_no="10",
        sap=product.sap,
        description=product.description,
        category=product.category,
        quantity=Decimal("0"),
        product=product,
        ship_qty=Decimal("501"),
        carton_count=Decimal("167"),
        po_net_weight=None,
        po_gross_weight=None,
        net_weight=product.net_weight,
        gross_weight=product.gross_weight,
    )

    assert profile.rules.packing_values_for_line(line, Decimal("501")) == (
        Decimal("167"),
        Decimal("183.70"),
        Decimal("334.00"),
        Decimal("3.8852"),
    )

    with profile_scope(profile):
        spec = resolve_line_field_spec("net_weight", seller="GS PTE", document_type="PL")
    assert spec.source_sheet == "DATA BASE TEMPLATE"
    assert spec.source_field == "N/W"
    assert "单箱 N/W × 本月出货箱数" in spec.rule
    sheet, field, rule = profile.rules.packing_weight_source_for_line(line, "net_weight")
    assert (sheet, field) == ("DATA BASE", "net_weight")
    assert "单箱 N/W × 本月出货箱数" in rule


def test_pf_packing_values_scale_po_total_even_when_equal_to_data_base_per_carton() -> None:
    """PO 总量碰巧等于单箱重量时仍按订单箱数缩放，不能当缺失回退。"""

    profile = create_pf_profile()
    product = Product(
        sap="1429058",
        description="PF rod",
        category=2,
        carton_qty=Decimal("5"),
        net_weight=Decimal("10"),
        gross_weight=Decimal("12"),
        length=Decimal("10"),
        width=Decimal("10"),
        height=Decimal("10"),
    )
    line = OrderLine(
        po_no="4500754841",
        item_line_no="10",
        sap=product.sap,
        description=product.description,
        category=product.category,
        quantity=Decimal("0"),
        product=product,
        ship_qty=Decimal("5"),
        carton_count=Decimal("2"),
        po_net_weight=Decimal("10"),
        po_gross_weight=Decimal("12"),
        net_weight=Decimal("10"),
        gross_weight=Decimal("12"),
    )

    assert profile.rules.packing_values_for_line(line, Decimal("5")) == (
        Decimal("1"),
        Decimal("5.00"),
        Decimal("6.00"),
        Decimal("0.0010"),
    )
    sheet, field, rule = profile.rules.packing_weight_source_for_line(line, "net_weight")
    assert (sheet, field) == ("PO record", "net_weight")
    assert "按出货箱数/订单箱数缩放" in rule


@pytest.mark.parametrize("carton_count", [None, Decimal("0")])
def test_pf_packing_weight_source_falls_back_when_order_cartons_missing(
    carton_count: Decimal | None,
) -> None:
    """PO 有总量但订单箱数缺失或为 0 时，计算和溯源都回退 DATA BASE 单箱重量。"""

    profile = create_pf_profile()
    product = Product(
        sap="1429058",
        description="PF rod",
        category=2,
        carton_qty=Decimal("1"),
        net_weight=Decimal("1.10"),
        gross_weight=Decimal("2.00"),
        length=Decimal("10"),
        width=Decimal("10"),
        height=Decimal("10"),
    )
    line = OrderLine(
        po_no="4500754841",
        item_line_no="10",
        sap=product.sap,
        description=product.description,
        category=product.category,
        quantity=Decimal("0"),
        product=product,
        ship_qty=Decimal("1"),
        carton_count=carton_count,
        po_net_weight=Decimal("10"),
        po_gross_weight=Decimal("12"),
        net_weight=Decimal("10"),
        gross_weight=Decimal("12"),
    )

    assert profile.rules.packing_values_for_line(line, Decimal("1")) == (
        Decimal("1"),
        Decimal("1.10"),
        Decimal("2.00"),
        Decimal("0.0010"),
    )
    net_sheet, net_field, net_rule = profile.rules.packing_weight_source_for_line(
        line, "net_weight"
    )
    gross_sheet, gross_field, gross_rule = profile.rules.packing_weight_source_for_line(
        line, "gross_weight"
    )
    assert (net_sheet, net_field) == ("DATA BASE", "net_weight")
    assert "单箱 N/W × 本月出货箱数" in net_rule
    assert "按出货箱数/订单箱数缩放" not in net_rule
    assert (gross_sheet, gross_field) == ("DATA BASE", "gross_weight")
    assert "单箱 G/W × 本月出货箱数" in gross_rule
    assert "按出货箱数/订单箱数缩放" not in gross_rule


def test_pf_invoice_ex_factory_source_uses_actual_ex_factory_column() -> None:
    profile = create_pf_profile()

    with profile_scope(profile):
        header = resolve_header_field_spec(
            "ex_factory_date",
            seller="GS PTE",
            document_type="INVOICE",
        )
        line = resolve_line_field_spec(
            "confirmed_ex_factory_date",
            seller="GS PTE",
            document_type="INVOICE",
        )
        po_no = resolve_line_field_spec("po_no", seller="GS PTE", document_type="PI")
        item_line_no = resolve_line_field_spec("item_line_no", seller="GS PTE", document_type="PI")
        item_number = resolve_line_field_spec("item_number", seller="GS PTE", document_type="PI")
        description = resolve_line_field_spec("description", seller="GS PTE", document_type="PI")
        quantity = resolve_line_field_spec("quantity", seller="GS PTE", document_type="PI")

    assert header is not None
    assert (header.source_sheet, header.source_field) == (
        "PO RECORD 26",
        "ACTUAL EX FACTORY",
    )
    assert (line.source_sheet, line.source_field) == (
        "PO RECORD 26",
        "ACTUAL EX FACTORY",
    )
    assert (po_no.source_sheet, po_no.source_field) == ("new PO template", "PO#")
    assert (item_line_no.source_sheet, item_line_no.source_field) == (
        "new PO template",
        "PO-Item",
    )
    assert (item_number.source_sheet, item_number.source_field) == (
        "new PO template",
        "Material",
    )
    assert (description.source_sheet, description.source_field) == (
        "new PO template",
        "Material Description",
    )
    assert (quantity.source_sheet, quantity.source_field) == (
        "new PO template",
        "Order Quantity",
    )


def test_pf_emax_pi_uses_customer_po_creation_date_and_description() -> None:
    profile = create_pf_profile()

    with profile_scope(profile):
        document_date = resolve_header_field_spec(
            "document_date",
            seller="EMAX PTE",
            document_type="PI",
        )
        ex_factory = resolve_header_field_spec(
            "ex_factory_date",
            seller="EMAX PTE",
            document_type="PI",
        )
        description = resolve_line_field_spec(
            "description",
            seller="EMAX PTE",
            document_type="PI",
        )
        unit_price = resolve_line_field_spec(
            "unit_price",
            seller="EMAX PTE",
            document_type="PI",
            category=3,
        )

    assert document_date is not None
    assert (document_date.source_sheet, document_date.source_field) == (
        "new PO template",
        "PO Creation Date",
    )
    assert document_date.model_attr == "document_date"
    assert ex_factory is not None
    assert (ex_factory.source_sheet, ex_factory.source_field) == (
        "PO RECORD 26",
        "NEW DATE EX -FACTORY DATE",
    )
    assert (description.source_sheet, description.source_field) == (
        "new PO template",
        "Material Description",
    )
    assert unit_price is not None
    assert unit_price.source_field == ("PF-EMAX COMBO DDP 2026 EFFECTIVE AS OF JUN/12/26-NEW PO")


def test_ro_capabilities_keep_current_document_matrix() -> None:
    profile = create_ro_profile()

    assert profile.capabilities.supports("GS PTE", "PO")
    assert not profile.capabilities.supports("SK", "PO")
    assert profile.capabilities.supports("SK", "CI")
    assert profile.capabilities.supports("YM", "RO_PL")
    assert profile.rules.buyer_for("GS PTE") == "EMAX PTE"
    assert profile.rules.buyer_for("unknown") is None
    assert "ro_generator.validator" not in profile.rules.rule_modules
    assert profile.rules.filename_strategy == "ro_standard_packager_v1"


def test_generation_context_binds_profile_and_base_file() -> None:
    profile = create_ro_profile()
    context = GenerationContext(profile=profile, base_file=Path("/tmp/ro-base.xlsx"))

    assert context.profile_id == "ro"
    assert context.base_path == Path("/tmp/ro-base.xlsx")
    assert context.schema is profile.schema
    assert context.rules is profile.rules


def test_profile_scope_isolated_between_two_profiles() -> None:
    ro_profile = create_ro_profile()
    custom_fields = replace(
        ro_profile.schema.po_record_fields,
        _mapping={**ro_profile.schema.po_record_fields._mapping, "po_no": "CUSTOM PO"},
    )
    custom_schema = replace(ro_profile.schema, po_record_fields=custom_fields)
    custom_rules = replace(cast(RoRules, ro_profile.rules), profile_id="customer-b")
    custom_profile = replace(
        ro_profile,
        profile_id="customer-b",
        display_name="Customer B",
        schema=custom_schema,
        rules=custom_rules,
    )

    assert current_schema().field("PO record", "po_no") == "PO NO."
    with profile_scope(custom_profile):
        assert current_schema().field("PO record", "po_no") == "CUSTOM PO"
        assert current_rules() is custom_profile.rules
        with profile_scope(ro_profile):
            assert current_schema().field("PO record", "po_no") == "PO NO."
        assert current_schema().field("PO record", "po_no") == "CUSTOM PO"
    assert current_schema().field("PO record", "po_no") == "PO NO."


def test_registry_rejects_duplicate_profile_ids() -> None:
    profile = create_ro_profile()

    with pytest.raises(DuplicateProfileError, match="Profile ID 已注册") as exc_info:
        ProfileRegistry((profile, profile))

    assert exc_info.value.code == "PROFILE_DUPLICATE"


def test_registry_rejects_unknown_profile() -> None:
    registry = default_profile_registry()

    with pytest.raises(ProfileNotFoundError, match="未知 Customer Profile") as exc_info:
        registry.get("customer-b")

    assert exc_info.value.code == "PROFILE_NOT_FOUND"


def test_registry_requires_existing_default_profile() -> None:
    with pytest.raises(InvalidProfileError, match="默认 Profile 不存在") as exc_info:
        ProfileRegistry((create_ro_profile(),), default_profile_id="customer-b")

    assert exc_info.value.code == "PROFILE_INVALID"


def test_profile_rejects_rule_identity_mismatch() -> None:
    profile = create_ro_profile()

    with pytest.raises(InvalidProfileError, match=r"rules\.profile_id 不匹配"):
        CustomerProfile(
            profile_id="customer-b",
            display_name="客户 B",
            version="v1",
            assets=profile.assets,
            schema=profile.schema,
            rules=profile.rules,
            capabilities=profile.capabilities,
        )


def test_capabilities_reject_unknown_seller() -> None:
    with pytest.raises(InvalidProfileError, match="未知 seller"):
        ProfileCapabilities(
            sellers=("GS PTE",),
            supported_documents_by_seller={"customer-b": ("PI",)},
        )
