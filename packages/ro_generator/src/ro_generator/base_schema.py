"""Base 文件结构描述加载器。

从当前默认 Profile 的 base_schema.yaml 读取 sheet 名、表头行、字段别名、
价格列和发票金额列。当 base 文件格式变化时只需修改 YAML。

设计边界：
- Profile schema 按资源路径缓存；`base_schema()` 只是默认 RO 的兼容入口。
- FieldAliases 的 get(key) 返回主 header 名，不存在时原样返回 key。
- 单个内部字段允许配置多个 header 别名，reader 会把它们归一到主 header。
- 列名匹配使用 normalize_header 之后的值——和 workbook_reader 一致。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ro_generator.resources import profile_root


@dataclass(frozen=True)
class SheetConfig:
    name: str
    header_row: int
    first_data_row: int


@dataclass(frozen=True)
class FieldAliases:
    """内部 field key → base 表列名（normalized）。"""

    _mapping: dict[str, str | tuple[str, ...]]

    def get(self, internal_key: str) -> str:
        """返回 internal_key 对应的 header 列名。不存在时返回 key 自身。"""
        headers = self.headers(internal_key)
        return headers[0] if headers else internal_key

    def headers(self, internal_key: str) -> tuple[str, ...]:
        raw = self._mapping.get(internal_key)
        if isinstance(raw, tuple):
            return raw
        if isinstance(raw, str):
            return (raw,)
        return ()

    def canonicalize(self, header: str) -> str:
        for internal_key in self._mapping:
            headers = self.headers(internal_key)
            if header in headers:
                return headers[0]
        return header

    def internal_key_for(self, header: str) -> str | None:
        """返回某个声明表头对应的内部字段 key。"""

        for internal_key in self._mapping:
            if header == internal_key or header in self.headers(internal_key):
                return internal_key
        return None

    def items(self) -> Iterator[tuple[str, str]]:
        return ((internal_key, self.get(internal_key)) for internal_key in self._mapping)


@dataclass(frozen=True)
class BaseSchema:
    """Base 文件的结构描述，从 YAML 加载。"""

    sheets: dict[str, SheetConfig]
    data_base_fields: FieldAliases
    po_record_fields: FieldAliases
    customer_po_fields: FieldAliases = field(default_factory=lambda: FieldAliases({}))
    price_columns: dict[str, str] = field(default_factory=dict)
    data_base_price_columns: dict[str, str] = field(default_factory=dict)
    invoice_data_base_price_columns: dict[str, str] = field(default_factory=dict)
    data_base_component_price_columns: dict[str, str] = field(default_factory=dict)
    invoice_amount_columns: dict[str, str] = field(default_factory=dict)

    def sheet(self, name: str) -> SheetConfig:
        return self.sheets[name]

    def logical_sheet_name(self, name: str) -> str | None:
        """把逻辑 sheet key 或 workbook 中的真实 sheet 名统一为逻辑 key。"""

        if name in self.sheets:
            return name
        for logical_name, config in self.sheets.items():
            if config.name == name:
                return logical_name
        return None

    def sheet_config_for_name(self, name: str) -> SheetConfig | None:
        logical_name = self.logical_sheet_name(name)
        return self.sheets.get(logical_name) if logical_name is not None else None

    def _field_aliases_for_sheet(self, sheet: str) -> FieldAliases | None:
        logical_sheet = self.logical_sheet_name(sheet) or sheet
        if logical_sheet in ("DATA BASE", "DATA_BASE"):
            return self.data_base_fields
        if logical_sheet == "PO record":
            return self.po_record_fields
        if logical_sheet == "客户PO":
            return self.customer_po_fields
        return None

    def internal_field_key(self, sheet: str, header: str) -> str | None:
        aliases = self._field_aliases_for_sheet(sheet)
        return aliases.internal_key_for(header) if aliases is not None else None

    def field(self, sheet: str, internal_key: str) -> str:
        """根据 sheet 和内部 key 返回 base 表中的列名。"""
        aliases = self._field_aliases_for_sheet(sheet)
        return aliases.get(internal_key) if aliases is not None else internal_key

    def field_candidates(self, sheet: str, internal_key: str) -> tuple[str, ...]:
        aliases = self._field_aliases_for_sheet(sheet)
        return aliases.headers(internal_key) if aliases is not None else (internal_key,)

    def canonical_header(self, sheet: str, header: str) -> str:
        aliases = self._field_aliases_for_sheet(sheet)
        return aliases.canonicalize(header) if aliases is not None else header


# —————————————————————————————————————
# 加载
# —————————————————————————————————————


def load_base_schema(path: str | Path | None = None) -> BaseSchema:
    """从 YAML 加载 base 文件结构描述。"""
    yaml_path = Path(path) if path else profile_root("ro") / "base_schema.yaml"
    if not yaml_path.exists():
        return _default_schema()

    with yaml_path.open(encoding="utf-8") as fp:
        raw = yaml.safe_load(fp)

    if not isinstance(raw, dict):
        return _default_schema()

    # sheets
    sheets: dict[str, SheetConfig] = {}
    sheets_raw = raw.get("sheets", {})
    if isinstance(sheets_raw, dict):
        for name, cfg in sheets_raw.items():
            if isinstance(cfg, dict):
                actual_name = cfg.get("name", name)
                if not isinstance(actual_name, str) or not actual_name.strip():
                    actual_name = name
                sheets[name] = SheetConfig(
                    name=actual_name.strip(),
                    header_row=int(cfg.get("header_row", 4)),
                    first_data_row=int(cfg.get("first_data_row", 5)),
                )

    # field aliases (three sheets)
    aliases_raw = raw.get("field_aliases", {})
    data_base_fields = _parse_field_aliases(aliases_raw, "DATA BASE")
    po_record_fields = _parse_field_aliases(aliases_raw, "PO record")
    customer_po_fields = _parse_field_aliases(aliases_raw, "客户PO")

    # PO record price columns (per seller)
    price_columns: dict[str, str] = {}
    pc = raw.get("price_columns", {})
    if isinstance(pc, dict):
        for seller, col in pc.items():
            if isinstance(seller, str) and isinstance(col, str):
                price_columns[seller] = col.strip()

    # DATA BASE price columns (per seller × category)
    db_price_columns: dict[str, str] = {}
    dbpc = raw.get("data_base_price_columns", {})
    if isinstance(dbpc, dict):
        for key, col in dbpc.items():
            if isinstance(key, str) and isinstance(col, str):
                db_price_columns[key] = col.strip()

    # Combo 成本拆分的组件价格列（例如 GS PTE/rod、GS PTE/reel）。
    component_price_columns: dict[str, str] = {}
    cbpc = raw.get("data_base_component_price_columns", {})
    if isinstance(cbpc, dict):
        for key, col in cbpc.items():
            if isinstance(key, str) and isinstance(col, str):
                component_price_columns[key] = col.strip()

    invoice_price_columns: dict[str, str] = {}
    ipc = raw.get("invoice_data_base_price_columns", {})
    if isinstance(ipc, dict):
        for key, col in ipc.items():
            if isinstance(key, str) and isinstance(col, str):
                invoice_price_columns[key] = col.strip()

    # Invoice amount columns in PO record
    inv_amount_columns: dict[str, str] = {}
    iac = raw.get("invoice_amount_columns", {})
    if isinstance(iac, dict):
        for key, col in iac.items():
            if isinstance(key, str) and isinstance(col, str):
                inv_amount_columns[key] = col.strip()

    return BaseSchema(
        sheets=sheets,
        data_base_fields=data_base_fields,
        po_record_fields=po_record_fields,
        customer_po_fields=customer_po_fields,
        price_columns=price_columns,
        data_base_price_columns=db_price_columns,
        invoice_data_base_price_columns=invoice_price_columns,
        data_base_component_price_columns=component_price_columns,
        invoice_amount_columns=inv_amount_columns,
    )


def _parse_field_aliases(raw: dict[str, object], sheet: str) -> FieldAliases:
    sheet_aliases = raw.get(sheet)
    mapping: dict[str, str | tuple[str, ...]] = {}
    if isinstance(sheet_aliases, dict):
        for internal_key, header in sheet_aliases.items():
            if not isinstance(internal_key, str):
                continue
            normalized_headers: tuple[str, ...]
            if isinstance(header, str):
                normalized_headers = (header.strip(),)
            elif isinstance(header, list):
                normalized_headers = tuple(
                    item.strip() for item in header if isinstance(item, str) and item.strip()
                )
            else:
                normalized_headers = ()
            if normalized_headers:
                mapping[internal_key] = (
                    normalized_headers if len(normalized_headers) > 1 else normalized_headers[0]
                )
    return FieldAliases(_mapping=mapping)


def _default_schema() -> BaseSchema:
    """返回与新 base 文件结构一致的默认 schema。"""
    return BaseSchema(
        sheets={
            "DATA BASE": SheetConfig("DATA BASE", 4, 5),
            "PO record": SheetConfig("PO record", 4, 5),
            "客户PO": SheetConfig("客户PO", 1, 2),
        },
        data_base_fields=FieldAliases(
            {
                "sap": "SAP",
                "description": "Material Description",
                "gs_model": "GS MODEL",
                "category": "Category",
                "sub_category": "SUB-CATEGORY",
                "moq": "MOQ",
                "fob_lt": "FOB LT",
                "brand": "品牌",
                "rfid": "RFID",
                "packing_type": "包装",
                "main_part_no": "主件编号",
                "inner_case_value": "inner case value",
                "carton_qty": "round value",
                "net_weight": "N/W",
                "gross_weight": "G/W",
                "length": "L",
                "width": "W",
                "height": "H",
                "cbm": "CBM",
                "reel_sap": "Reel SAP",
                "reel_description": "Reel Description",
            }
        ),
        po_record_fields=FieldAliases(
            {
                "po_no": "PO NO.",
                "item_line": "ITEM LINE#",
                "sap": "SAP Number",
                "description": "DESCRIPTION",
                "reel_sap": "Reel SAP",
                "reel_description": "Reel Description",
                "quantity": "FINALQTY",
                "category": "CATEGORY",
                "brand": "BRAND",
                "ship_to": "SHIP TO",
                "inv_no": "INV#",
                "ship_qty": "SHIP QTY",
                "balance_qty": "BALANCE QTY",
                "sk_ym_invoice_no": "SK/YM INVOICE NO.",
                "net_weight": "N/W",
                "gross_weight": "G/W",
                "length": "L",
                "width": "W",
                "height": "H",
                "carton_count": "CTNS",
                "total_cbm": "TOTAL CBM",
                "carton_qty_export": "外箱(最终出口装箱率)",
                "order_date": "ORDER DATE (EMAIL)",
                "required_ex_factory_date": "PO REQUIRED EX-FACTORYDATE(-60days)",
                "delivery_date": "PO DELIVERY DATE",
                "final_ex_factory_date": "FINAL EX-FACTORY DATE",
                "ex_factory_month": "EX-FACTORY month",
                "order_month": "ORDER month",
            }
        ),
        price_columns={
            "SK": "GS-SK/YM USD FOB",
            "YM": "GS-SK/YM USD FOB",
            "GS PTE": "EMAX-GS PTE FOB",
            "EMAX PTE": "EMAX PTE",
        },
        data_base_price_columns={
            "SK/combo": "GS-SK/YM COMBO FOB 2026",
            "YM/combo": "GS-SK/YM COMBO FOB 2026",
            "SK/rod": "GS-SK/YM YM ROD FOB 2026",
            "YM/rod": "GS-SK/YM COMBO FOB 2026",
            "SK/reel": "GS-SK/YM SK REEL FOB 2026",
            "YM/reel": "GS-SK/YM COMBO FOB 2026",
            "GS PTE/combo": "EMAX-GS PTE COMBO FOB 2026",
            "GS PTE/rod": "EMAX-GS PTE ROD FOB 2026",
            "GS PTE/reel": "EMAX-GS PTE REEL FOB 2026",
            "EMAX PTE/combo": "EMAX PTE COMBO FOB 2026",
            "EMAX PTE/rod": "EMAX PTE ROD FOB 2026",
            "EMAX PTE/reel": "EMAX PTE REEL FOB 2026",
        },
        invoice_amount_columns={
            "GS-SK/YM INV": "GS-SK/YM INV",
            "EMAX-GS INV": "EMAX-GS INV",
            "RO-EMAX INV": "RO-EMAX INV",
        },
        customer_po_fields=FieldAliases(
            {
                "purchasing_document": "Purchasing Document",
                "item": "Item",
                "material": "Material",
                "order_quantity": "Order Quantity",
                "ship_date": ("ship DATE", "Ship Date"),
                "ship_to": "ship to",
                "final_destination": "final destination",
            }
        ),
    )


# —————————————————————————————————————
# 兼容入口和按路径缓存
# —————————————————————————————————————


@lru_cache(maxsize=32)
def _cached_schema(path: str) -> BaseSchema:
    return load_base_schema(path)


def base_schema(profile_or_path: object | None = None) -> BaseSchema:
    """获取 Profile schema。

    无参数时兼容旧入口并返回默认 RO；传入 Profile、BaseSchema 或路径时，
    返回对应 schema。路径加载按 resolved path 缓存，避免不同 Profile 串用。
    """

    if isinstance(profile_or_path, BaseSchema):
        return profile_or_path
    if profile_or_path is not None and not isinstance(profile_or_path, (str, Path)):
        profile_schema = getattr(profile_or_path, "schema", None)
        if isinstance(profile_schema, BaseSchema):
            return profile_schema
    schema_path = (
        Path(profile_or_path)
        if isinstance(profile_or_path, (str, Path))
        else profile_root("ro") / "base_schema.yaml"
    )
    return _cached_schema(str(schema_path.expanduser().resolve()))
