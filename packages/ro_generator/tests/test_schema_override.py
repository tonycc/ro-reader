"""schema override 合并、加载、保存与结构探测的单元测试。"""

from __future__ import annotations

from pathlib import Path

from ro_generator.base_schema import (
    FieldAliases,
    SchemaOverride,
    SheetOverride,
    base_schema,
    effective_schema,
    load_schema_override,
    override_path_for,
    save_schema_override,
)


def test_override_path_derives_from_base_file(tmp_path: Path) -> None:
    base = tmp_path / "customer.xlsx"
    assert override_path_for(base) == tmp_path / "customer.schema.yaml"
    # 无扩展名也能稳定派生
    plain = tmp_path / "customer"
    assert override_path_for(plain) == tmp_path / "customer.schema.yaml"


def test_with_override_replaces_only_declared_fields() -> None:
    builtin = base_schema()
    override = SchemaOverride(
        field_aliases={"DATA BASE": {"sap": "SAP Code"}, "PO record": {"po_no": "PO Number"}}
    )
    merged = builtin.with_override(override)
    assert merged.field("DATA BASE", "sap") == "SAP Code"
    assert merged.field("PO record", "po_no") == "PO Number"
    # 未声明字段沿用内置值
    assert merged.field("DATA BASE", "description") == builtin.field("DATA BASE", "description")
    # 内置不可变对象不被污染
    assert builtin.field("DATA BASE", "sap") == "SAP"


def test_with_override_sheet_header_row() -> None:
    builtin = base_schema()
    override = SchemaOverride(sheets={"DATA BASE": SheetOverride(header_row=2, first_data_row=3)})
    merged = builtin.with_override(override)
    assert merged.sheet("DATA BASE").header_row == 2
    assert merged.sheet("DATA BASE").first_data_row == 3
    # 未覆盖的 sheet 不变
    assert merged.sheet("PO record").header_row == builtin.sheet("PO record").header_row


def test_field_aliases_merged_replaces_multi_alias_with_single() -> None:
    original = FieldAliases({"ship_date": ("ship DATE", "Ship Date")})
    merged = original.merged({"ship_date": "SHIP-DATE"})
    assert merged.headers("ship_date") == ("SHIP-DATE",)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "b.schema.yaml"
    override = SchemaOverride(
        sheets={"DATA BASE": SheetOverride(header_row=2)},
        field_aliases={"客户PO": {"material": "Material No"}},
    )
    save_schema_override(path, override)
    loaded = load_schema_override(path)
    assert loaded.sheets["DATA BASE"].header_row == 2
    assert loaded.field_aliases["客户PO"]["material"] == "Material No"


def test_save_empty_override_removes_file(tmp_path: Path) -> None:
    path = tmp_path / "b.schema.yaml"
    save_schema_override(path, SchemaOverride(field_aliases={"PO record": {"po_no": "X"}}))
    assert path.exists()
    save_schema_override(path, SchemaOverride())
    assert not path.exists()


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    loaded = load_schema_override(tmp_path / "nope.schema.yaml")
    assert loaded.is_empty()


def test_effective_schema_without_override_returns_builtin(tmp_path: Path) -> None:
    builtin = base_schema()
    assert effective_schema(builtin, tmp_path / "base.xlsx") is builtin


def test_effective_schema_with_override_merges(tmp_path: Path) -> None:
    base = tmp_path / "base.xlsx"
    base.write_bytes(b"")
    save_schema_override(
        override_path_for(base),
        SchemaOverride(field_aliases={"DATA BASE": {"sap": "SAP No."}}),
    )
    merged = effective_schema(base_schema(), base)
    assert merged.field("DATA BASE", "sap") == "SAP No."


def test_with_override_redirects_price_column() -> None:
    builtin = base_schema()
    override = SchemaOverride(
        price_columns={"data_base_price_columns": {"EMAX PTE/combo": "EMAX PTE COMBO FOB 2027"}}
    )
    merged = builtin.with_override(override)
    assert merged.data_base_price_columns["EMAX PTE/combo"] == "EMAX PTE COMBO FOB 2027"
    # 未覆盖的价格键沿用内置值；内置对象不被污染
    assert (
        merged.data_base_price_columns["EMAX PTE/rod"]
        == builtin.data_base_price_columns["EMAX PTE/rod"]
    )
    assert builtin.data_base_price_columns["EMAX PTE/combo"] == "EMAX PTE COMBO FOB 2026"


def test_price_override_cannot_add_new_key() -> None:
    builtin = base_schema()
    override = SchemaOverride(
        price_columns={"data_base_price_columns": {"NEWCOMER/x": "HACKED COLUMN"}}
    )
    merged = builtin.with_override(override)
    # 未声明的价格键不得外扩，防止凭空造金额来源
    assert "NEWCOMER/x" not in merged.data_base_price_columns


def test_price_override_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "b.schema.yaml"
    override = SchemaOverride(
        price_columns={"data_base_price_columns": {"EMAX PTE/combo": "EMAX PTE COMBO FOB 2027"}}
    )
    save_schema_override(path, override)
    loaded = load_schema_override(path)
    assert (
        loaded.price_columns["data_base_price_columns"]["EMAX PTE/combo"]
        == "EMAX PTE COMBO FOB 2027"
    )
    assert not loaded.is_empty()
