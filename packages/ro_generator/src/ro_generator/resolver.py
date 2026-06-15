"""PO resolver：把 base 文件解析成 OrderLine 列表。

职责（产品方案 §10）：
- 从 DATA BASE 建立 SAP → Product 索引（含按品类的价格矩阵）
- 按 PO 号过滤 PO record 行
- 每行 join 产品、读客户PO/PO record 中的数量与出货口径、读发票金额
- 公式列（CTNS/TOTAL CBM）按 §10.4 公式回退
- 缺关键字段（SAP、客户PO Order Quantity、SAP 不在 DATA BASE）报阻断错误

base 表中的列名通过 base_schema.yaml 的 field_aliases 映射。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

from ro_generator.base_schema import base_schema
from ro_generator.line_rules import resolve_line_field_spec
from ro_generator.models import OrderLine, Product, ValidationMessage
from ro_generator.schema import (
    CATEGORY_NAMES,
    DATA_BASE_PRICE_COLUMNS,
    INVOICE_AMOUNT_COLUMNS,
    SELLER_PRICE_COLUMNS,
    SELLER_TO_BUYER,
    SHEET_CUSTOMER_PO,
    SHEET_DATA_BASE,
    SHEET_PO_RECORD,
)
from ro_generator.workbook_reader import ROW_NUMBER_KEY, WorkbookReader, row_decimal_places

_bs = base_schema()

# —————————————————————————————————————
# 校验消息 code
# —————————————————————————————————————

CODE_PO_NOT_FOUND: Final = "PO_NOT_FOUND"
CODE_SAP_MISSING: Final = "SAP_MISSING"
CODE_SAP_NOT_IN_DATA_BASE: Final = "SAP_NOT_IN_DATA_BASE"
CODE_QTY_MISSING: Final = "QTY_MISSING"
CODE_QTY_INVALID: Final = "QTY_INVALID"
CODE_NO_PRICES: Final = "NO_PRICES"
CODE_FORMULA_FALLBACK: Final = "FORMULA_FALLBACK"


# —————————————————————————————————————
# 字段别名快捷方式
# —————————————————————————————————————

def _db(key: str) -> str:
    return _bs.field("DATA BASE", key)


def _po(key: str) -> str:
    return _bs.field("PO record", key)


def _cp(key: str) -> str:
    return _bs.field("客户PO", key)


# PO record 价格列，从 (seller, buyer) → 列名
PO_PRICE_COLUMNS: Final[dict[tuple[str, str], str]] = {
    (seller, SELLER_TO_BUYER[seller]): col
    for seller, col in SELLER_PRICE_COLUMNS.items()
}


# —————————————————————————————————————
# 公开 API
# —————————————————————————————————————

@dataclass(frozen=True)
class ResolveResult:
    lines: tuple[OrderLine, ...]
    messages: tuple[ValidationMessage, ...]


def resolve_po_lines(
    reader: WorkbookReader, po_no: str,
    *, products: dict[str, Product] | None = None,
) -> ResolveResult:
    """解析指定 PO 号的所有订单行。

    可通过 `products` 参数传入预构建的 DATA BASE 索引，避免重复读取。
    """
    if products is None:
        products = build_product_index(reader)
    rows = _read_po_record_rows(reader, po_no)
    customer_po_rows = _read_customer_po_rows(reader, po_no)
    return resolve_po_rows(
        tuple(rows),
        products,
        po_no=po_no,
        customer_po_rows=customer_po_rows,
    )


def resolve_po_rows(
    rows: tuple[dict[str, object], ...],
    products: dict[str, Product],
    po_no: str | None = None,
    *,
    customer_po_rows: tuple[dict[str, object], ...] = (),
) -> ResolveResult:
    """从已过滤的 PO record 行解析 OrderLine 列表。

    缓存路径入口：调用方通过 snapshot 获取预过滤的 rows 和 products，
    不再经过 WorkbookReader。

    当 rows 为空且传入 po_no 时，返回 PO_NOT_FOUND blocking error。
    当 rows 为空且未传 po_no 时，返回空结果（由调用方处理空行逻辑）。
    """
    if not rows:
        if po_no is not None:
            return ResolveResult(
                lines=(),
                messages=(
                    ValidationMessage(
                        kind="blocking_error",
                        code=CODE_PO_NOT_FOUND,
                        message=f"PO 号 {po_no!r} 在 PO record 中不存在",
                        sheet=SHEET_PO_RECORD,
                    ),
                ),
            )
        return ResolveResult(lines=(), messages=())

    lines: list[OrderLine] = []
    messages: list[ValidationMessage] = []
    customer_po_lookup = _build_customer_po_lookup(customer_po_rows)
    for row in rows:
        line, row_msgs = _resolve_row(row, products, customer_po_lookup)
        messages.extend(row_msgs)
        if line is not None:
            lines.append(line)
    return ResolveResult(lines=tuple(lines), messages=tuple(messages))


# —————————————————————————————————————
# DATA BASE → Product 索引
# —————————————————————————————————————

def build_product_index(reader: WorkbookReader) -> dict[str, Product]:
    """从 DATA BASE sheet 建立 SAP 到产品主数据的索引。"""
    sheet = reader.read_sheet(SHEET_DATA_BASE)
    index: dict[str, Product] = {}
    for row in sheet.rows:
        sap = _str_or_none(row.get(_db("sap")))
        if not sap:
            continue
        category = _int_or_none(row.get(_db("category")))
        if category is None:
            continue
        # 按品类读取 DATA BASE 中的价格（9 列：3 卖方 × 3 品类）
        prices: dict[str, Decimal] = {}
        cat_name = CATEGORY_NAMES.get(category, "")
        if cat_name:
            for price_key, col_name in DATA_BASE_PRICE_COLUMNS.items():
                seller_cat = price_key.split("/")
                if len(seller_cat) == 2 and seller_cat[1] == cat_name:
                    p = _decimal_from_row(row, col_name)
                    if p is not None:
                        prices[price_key] = p

        index[sap] = Product(
            sap=sap,
            description=_str_or_empty(row.get(_db("description"))),
            category=category,
            gs_model=_str_or_none(row.get(_db("gs_model"))),
            sub_category=_str_or_none(row.get(_db("sub_category"))),
            moq=_int_or_none(row.get(_db("moq"))),
            fob_lt=_int_or_none(row.get(_db("fob_lt"))),
            brand=_str_or_none(row.get(_db("brand"))),
            rfid=_str_or_none(row.get(_db("rfid"))),
            packing_type=_str_or_none(row.get(_db("packing_type"))),
            main_part_no=_str_or_none(row.get(_db("main_part_no"))),
            reel_sap=_str_or_none(row.get(_db("reel_sap"))),
            reel_description=_str_or_none(row.get(_db("reel_description"))),
            inner_case_value=_decimal_from_row(row, _db("inner_case_value")),
            carton_qty=_decimal_from_row(row, _db("carton_qty")),
            net_weight=_decimal_from_row(row, _db("net_weight")),
            gross_weight=_decimal_from_row(row, _db("gross_weight")),
            length=_decimal_from_row(row, _db("length")),
            width=_decimal_from_row(row, _db("width")),
            height=_decimal_from_row(row, _db("height")),
            cbm=_decimal_from_row(row, _db("cbm")),
            prices=prices,
        )
    return index


_build_product_index = build_product_index


# —————————————————————————————————————
# PO record 行解析
# —————————————————————————————————————

def _read_po_record_rows(
    reader: WorkbookReader,
    po_no: str,
) -> tuple[dict[str, object], ...]:
    sheet = reader.read_sheet(SHEET_PO_RECORD)
    target = po_no.strip()
    matched: list[dict[str, object]] = []
    for row in sheet.rows:
        cell_value = _str_or_none(row.get(_po("po_no")))
        if cell_value and cell_value == target:
            matched.append(row)
    return tuple(matched)


def _read_customer_po_rows(
    reader: WorkbookReader,
    po_no: str,
) -> tuple[dict[str, object], ...]:
    cp_sheet = reader.read_sheet(
        SHEET_CUSTOMER_PO,
        header_row=_bs.sheet("客户PO").header_row,
        first_data_row=_bs.sheet("客户PO").first_data_row,
    )
    purchasing_document_field = _cp("purchasing_document")
    target = po_no.strip()
    matched: list[dict[str, object]] = []
    for row in cp_sheet.rows:
        cell_value = _str_or_none(row.get(purchasing_document_field))
        if cell_value and cell_value == target:
            matched.append(row)
    return tuple(matched)


def _resolve_row(
    row: dict[str, object],
    products: dict[str, Product],
    customer_po_lookup: CustomerPoLookup,
) -> tuple[OrderLine | None, list[ValidationMessage]]:
    row_number = _int_or_none(row.get(ROW_NUMBER_KEY))
    messages: list[ValidationMessage] = []

    sap = _str_or_none(row.get(_po("sap")))
    if not sap:
        messages.append(
            ValidationMessage(
                kind="blocking_error", code=CODE_SAP_MISSING,
                message="行缺少 SAP Number", sheet=SHEET_PO_RECORD,
                row=row_number, field=_po("sap"),
            )
        )
        return None, messages

    product = products.get(sap)
    if product is None:
        messages.append(
            ValidationMessage(
                kind="blocking_error", code=CODE_SAP_NOT_IN_DATA_BASE,
                message=f"SAP {sap!r} 在 DATA BASE 中不存在",
                sheet=SHEET_DATA_BASE, row=row_number, field=_po("sap"),
            )
        )
        return None, messages

    qty_row, qty_raw = _resolve_customer_po_raw_entry(
        sap=sap,
        customer_po_lookup=customer_po_lookup,
        field_name=_cp("order_quantity"),
    )
    if qty_raw is None:
        messages.append(
            ValidationMessage(
                kind="blocking_error", code=CODE_QTY_MISSING,
                message="行缺少客户PO Order Quantity", sheet=SHEET_CUSTOMER_PO,
                row=None, field=_cp("order_quantity"),
            )
        )
        return None, messages
    quantity = qty_raw
    if not isinstance(quantity, Decimal):
        quantity = _decimal_or_none(
            qty_raw,
            decimal_places=(
                row_decimal_places(qty_row, _cp("order_quantity")) if qty_row is not None else None
            ),
        )
        if quantity is None:
            messages.append(
                ValidationMessage(
                    kind="blocking_error", code=CODE_QTY_INVALID,
                    message=f"客户PO Order Quantity 不是有效数字：{qty_raw!r}",
                    sheet=SHEET_CUSTOMER_PO, row=None, field=_cp("order_quantity"),
                )
            )
            return None, messages

    # 价格与小计：从 DATA BASE 按主体 + Category 价格列读取
    prices, subtotals, price_msgs = _collect_prices(product, quantity)
    messages.extend(price_msgs)
    if not prices:
        messages.append(
            ValidationMessage(
                kind="warning", code=CODE_NO_PRICES,
                message=f"SAP {sap!r} 在所有链段下均无可用价格",
                sheet=SHEET_DATA_BASE, row=None,
                field=next(iter(DATA_BASE_PRICE_COLUMNS.values())) if DATA_BASE_PRICE_COLUMNS else "price",
                severity="high",
            )
        )

    # 发票金额
    invoice_amounts = _collect_invoice_amounts(row)

    # 装箱字段（公式列回退）
    carton_count, ctns_msg = _read_with_fallback(
        row, _po("carton_count"),
        lambda: _compute_ctns(quantity, product.carton_qty),
        row_number,
    )
    if ctns_msg is not None:
        messages.append(ctns_msg)
    total_cbm, cbm_msg = _read_with_fallback(
        row, _po("total_cbm"),
        lambda: _compute_total_cbm(product, carton_count),
        row_number,
    )
    if cbm_msg is not None:
        messages.append(cbm_msg)

    po_net_weight = _decimal_from_row(row, _po("net_weight"))
    po_gross_weight = _decimal_from_row(row, _po("gross_weight"))

    line = OrderLine(
        po_no=_str_or_empty(row.get(_po("po_no"))),
        item_line_no=_resolve_customer_po_material(
            sap=sap,
            customer_po_lookup=customer_po_lookup,
        ),
        cp_item=_resolve_customer_po_field(
            sap=sap,
            customer_po_lookup=customer_po_lookup,
            field_name=_cp("item"),
        ) or "",
        sap=sap,
        description=product.description,
        category=product.category,
        quantity=quantity,
        po_record_category=_int_or_none(row.get(_po("category"))),
        product=product,
        ship_to=_resolve_ship_to(
            sap=sap,
            customer_po_lookup=customer_po_lookup,
        ),
        manufacturer_address=_resolve_customer_po_field(
            sap=sap,
            customer_po_lookup=customer_po_lookup,
            field_name=_cp("manufacturer"),
        ),
        final_destination=_resolve_customer_po_field(
            sap=sap,
            customer_po_lookup=customer_po_lookup,
            field_name=_cp("final_destination"),
        ),
        brand=_str_or_none(row.get(_po("brand"))) or product.brand,
        invoice_no=_str_or_none(row.get(_po("inv_no"))),
        ship_qty=_decimal_or_none(row.get(_po("ship_qty"))),
        balance_qty=_decimal_or_none(row.get(_po("balance_qty"))),
        po_record_description=_str_or_none(row.get(_po("description"))),
        sk_ym_invoice_no=_str_or_none(row.get(_po("sk_ym_invoice_no"))),
        reel_sap=_str_or_none(row.get(_po("reel_sap"))) or product.reel_sap,
        reel_description=_str_or_none(row.get(_po("reel_description"))) or product.reel_description,
        e10_po=_str_or_none(row.get(_po("e10_po"))),
        ym_po=_str_or_none(row.get(_po("ym_po"))),
        carton_count=carton_count,
        net_weight=po_net_weight if po_net_weight is not None else product.net_weight,
        gross_weight=po_gross_weight if po_gross_weight is not None else product.gross_weight,
        total_cbm=total_cbm,
        prices=prices,
        subtotals=subtotals,
        invoice_amounts=invoice_amounts,
        # 日期字段：订单日期仍来自 PO record，出厂日期改为客户 PO 的 ship DATE
        order_date=_date_or_none(row.get(_po("order_date"))),
        delivery_date=_date_or_none(row.get(_po("delivery_date"))),
        confirmed_ex_factory_date=_resolve_customer_po_date(
            sap=sap,
            customer_po_lookup=customer_po_lookup,
            field_name=_cp("ship_date"),
        ),
        po_ex_factory_date=_date_or_none(row.get(_po("final_ex_factory_date"))),
        etd_on_board=_date_or_none(row.get(_po("etd_on_board"))),
        source_row=row_number,
    )
    return line, messages


CustomerPoLookup = tuple[
    dict[str, tuple[dict[str, object], ...]],
    tuple[dict[str, object], ...],
]


def _build_customer_po_lookup(
    customer_po_rows: tuple[dict[str, object], ...],
) -> CustomerPoLookup:
    by_material: dict[str, list[dict[str, object]]] = {}
    for row in customer_po_rows:
        material = _str_or_none(row.get(_cp("material")))
        if not material:
            continue
        by_material.setdefault(material, []).append(row)
    return (
        {material: tuple(rows) for material, rows in by_material.items()},
        customer_po_rows,
    )


def _resolve_ship_to(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
) -> str | None:
    return _resolve_customer_po_field(
        sap=sap,
        customer_po_lookup=customer_po_lookup,
        field_name=_cp("ship_to"),
    )


def _resolve_customer_po_date(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
    field_name: str,
) -> date | None:
    _, raw = _resolve_customer_po_raw_entry(
        sap=sap,
        customer_po_lookup=customer_po_lookup,
        field_name=field_name,
    )
    return _date_or_none(raw)


def _resolve_customer_po_material(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
) -> str:
    return _resolve_customer_po_field(
        sap=sap,
        customer_po_lookup=customer_po_lookup,
        field_name=_cp("material"),
    ) or ""


def _resolve_cp_field_by_spec(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
    field_key: str,
    seller: str,
) -> str:
    """根据 line_rules 的 seller 专属覆盖解析客户PO字段值。"""
    spec = resolve_line_field_spec(field_key, document_type="PI", seller=seller)
    field_name = _cp(spec.source_field) if spec.source_field else _cp(field_key)
    return _resolve_customer_po_field(
        sap=sap,
        customer_po_lookup=customer_po_lookup,
        field_name=field_name,
    ) or ""


def _resolve_customer_po_raw_entry(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
    field_name: str,
) -> tuple[dict[str, object] | None, object | None]:
    for row in _matched_customer_po_rows(sap=sap, customer_po_lookup=customer_po_lookup):
        raw = row.get(field_name)
        if raw is None or raw == "":
            continue
        return row, raw
    return None, None


def _matched_customer_po_rows(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
) -> tuple[dict[str, object], ...]:
    by_material, all_rows = customer_po_lookup
    material_matches = by_material.get(sap, ())
    return material_matches or all_rows


def _resolve_customer_po_field(
    *,
    sap: str,
    customer_po_lookup: CustomerPoLookup,
    field_name: str,
) -> str | None:
    for row in _matched_customer_po_rows(sap=sap, customer_po_lookup=customer_po_lookup):
        value = _str_or_none(row.get(field_name))
        if value:
            return value

    return None


def _collect_prices(
    product: Product,
    quantity: Decimal,
) -> tuple[dict[tuple[str, str], Decimal], dict[tuple[str, str], Decimal], list[ValidationMessage]]:
    """从 DATA BASE 的按主体 + Category 价格矩阵读取价格，计算小计。"""
    prices: dict[tuple[str, str], Decimal] = {}
    subtotals: dict[tuple[str, str], Decimal] = {}
    for seller in SELLER_TO_BUYER:
        buyer = SELLER_TO_BUYER.get(seller, "")
        segment = (seller, buyer)
        category_name = CATEGORY_NAMES.get(product.category, "")
        if not category_name:
            continue
        price_key = f"{seller}/{category_name}"
        price = product.prices.get(price_key)
        if price is None:
            continue
        prices[segment] = price
        subtotals[segment] = (price * quantity).quantize(Decimal("0.01"))
    return prices, subtotals, []


def _collect_invoice_amounts(row: dict[str, object]) -> dict[str, Decimal]:
    """从 PO record 读取各链段的发票金额。"""
    amounts: dict[str, Decimal] = {}
    for key, col_name in INVOICE_AMOUNT_COLUMNS.items():
        v = _decimal_from_row(row, col_name)
        if v is not None:
            amounts[key] = v
    return amounts


def _read_with_fallback(
    row: dict[str, object],
    field_name: str,
    fallback_fn: Callable[[], Decimal | None],
    row_number: int | None,
) -> tuple[Decimal | None, ValidationMessage | None]:
    raw = row.get(field_name)
    if raw is not None and raw != "":
        value = _decimal_or_none(raw, decimal_places=row_decimal_places(row, field_name))
        if value is not None:
            return value, None
    computed = fallback_fn()
    if computed is not None:
        msg = ValidationMessage(
            kind="warning", code=CODE_FORMULA_FALLBACK,
            message=f"字段 {field_name!r} 为空，使用公式回退计算",
            sheet=SHEET_PO_RECORD, row=row_number, field=field_name,
            severity="high",
        )
        return computed, msg
    return None, None


# —————————————————————————————————————
# 公式
# —————————————————————————————————————

def _compute_ctns(quantity: Decimal, carton_qty: Decimal | None) -> Decimal | None:
    if carton_qty is None or carton_qty == 0:
        return None
    from math import ceil
    return Decimal(ceil(int(quantity / carton_qty)))


def _compute_total_cbm(product: Product, carton_count: Decimal | None) -> Decimal | None:
    if carton_count is None:
        return None
    if product.length is None or product.width is None or product.height is None:
        return None
    cbm = (product.length * product.width * product.height) / Decimal("1000000")
    return (cbm * carton_count).quantize(Decimal("0.0001"))


# —————————————————————————————————————
# 小工具
# —————————————————————————————————————

def _str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if value is not None:
        s = str(value).strip()
        return s or None
    return None


def _str_or_empty(value: object) -> str:
    return _str_or_none(value) or ""


def _int_or_none(value: object) -> int | None:
    try:
        if isinstance(value, float) and value != int(value):
            return None
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _decimal_from_row(row: dict[str, object], field_name: str) -> Decimal | None:
    return _decimal_or_none(row.get(field_name), decimal_places=row_decimal_places(row, field_name))


def _decimal_or_none(value: object, *, decimal_places: int | None = None) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, (int, float)):
        try:
            decimal_value = Decimal(str(value))
        except InvalidOperation:
            return None
    elif isinstance(value, str):
        try:
            cleaned = value.strip().replace(",", "").replace(" ", "")
            decimal_value = Decimal(cleaned)
        except InvalidOperation:
            return None
    else:
        return None
    if decimal_places is None:
        return decimal_value
    quantizer = Decimal("1").scaleb(-decimal_places)
    return decimal_value.quantize(quantizer)


def _date_or_none(value: object) -> date | None:
    """尝试将单元格值转为 date。支持 datetime、date、字符串。"""
    if value is None:
        return None
    from datetime import datetime as dt
    if isinstance(value, dt):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return dt.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


__all__ = [
    "CODE_FORMULA_FALLBACK",
    "CODE_NO_PRICES",
    "CODE_PO_NOT_FOUND",
    "CODE_QTY_INVALID",
    "CODE_QTY_MISSING",
    "CODE_SAP_MISSING",
    "CODE_SAP_NOT_IN_DATA_BASE",
    "PO_PRICE_COLUMNS",
    "ResolveResult",
    "build_product_index",
    "resolve_po_lines",
    "resolve_po_rows",
]
