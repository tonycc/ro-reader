"""base_schema 测试：YAML 加载、字段别名、默认值。"""

from __future__ import annotations

from ro_generator.base_schema import (
    base_schema,
    load_base_schema,
)


def test_base_schema_loads_from_yaml():
    """默认加载 RO Profile 的 base_schema.yaml 成功。"""
    s = base_schema()
    assert s is not None
    assert "DATA BASE" in s.sheets
    assert "PO record" in s.sheets


def test_sheet_config():
    s = base_schema()
    db = s.sheet("DATA BASE")
    assert db.header_row == 4
    assert db.first_data_row == 5
    po = s.sheet("PO record")
    assert po.header_row == 4


def test_field_aliases_db():
    s = base_schema()
    assert s.field("DATA BASE", "sap") == "SAP"
    assert s.field("DATA BASE", "description") == "Material Description"
    assert s.field("DATA BASE", "category") == "Category"
    assert s.field("DATA BASE", "brand") == "品牌"


def test_field_aliases_po():
    s = base_schema()
    assert s.field("PO record", "po_no") == "PO NO."
    assert s.field("PO record", "quantity") == "FINALQTY"
    assert s.field("PO record", "inv_no") == "INV#"
    assert s.field("PO record", "sap") == "SAP Number"


def test_field_unknown_key_returns_key():
    s = base_schema()
    assert s.field("PO record", "nonexistent") == "nonexistent"


def test_price_columns():
    s = base_schema()
    assert s.price_columns["SK"] == "GS-SK/YM USD FOB"
    assert s.price_columns["YM"] == "GS-SK/YM USD FOB"
    assert s.price_columns["GS PTE"] == "EMAX-GS PTE FOB"
    assert s.price_columns["EMAX PTE"] == "EMAX PTE"


def test_data_base_price_columns():
    s = base_schema()
    # 4 卖方 × 3 品类 = 12
    assert len(s.data_base_price_columns) == 12
    assert s.data_base_price_columns["SK/combo"] == "GS-SK/YM COMBO FOB 2026"
    assert s.data_base_price_columns["YM/rod"] == "GS-SK/YM COMBO FOB 2026"
    assert s.data_base_price_columns["YM/reel"] == "GS-SK/YM COMBO FOB 2026"
    assert s.data_base_price_columns["EMAX PTE/reel"] == "EMAX PTE REEL FOB 2026"


def test_default_schema_fallback():
    """不存在的路径返回默认 schema。"""
    s = load_base_schema("/nonexistent/base_schema.yaml")
    assert s.sheet("DATA BASE").header_row == 4
    assert s.field("DATA BASE", "sap") == "SAP"
    assert s.field("PO record", "quantity") == "FINALQTY"
