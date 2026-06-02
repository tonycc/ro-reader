"""PO resolver：把 base 文件解析成 OrderLine 列表。

职责（产品方案 §10）：
- 从 DATA BASE 建立 SAP → Product 索引
- 按 PO 号过滤 PO record 行
- 每行 join 产品、读价格、读月度出货、计算小计
- 公式列（CTNS/TOTAL CBM）按 §10.4 公式回退
- 缺关键字段（SAP、FINALQTY、SAP 在 DATA BASE 找不到）报阻断错误

设计边界：
- resolver 关心"数据如何拼装"，不关心"用户请求要装配哪些单据"——后者归 generator
- resolver 不挑"用哪段链路的单价"，而是把所有能解析出价格的链段都附在 OrderLine 上，
  让下游 document_model 按 (seller, buyer) 取用
- DATA BASE 的 (entity, category) 价格矩阵在 Phase 1 暂不交叉校验，
  Phase 2 多模板接入时再加（产品方案 §10.1 注：列名以实际表头为准）
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from ro_generator.models import OrderLine, Product, ValidationMessage
from ro_generator.schema import (
    ENTITY_EMAX_PTE,
    ENTITY_GS_PTE,
    ENTITY_PF,
    ENTITY_SK_YM,
    LEGAL_CHAIN_SEGMENTS,
    MONTH_COLUMNS,
    SHEET_DATA_BASE,
    SHEET_PO_RECORD,
)
from ro_generator.workbook_reader import ROW_NUMBER_KEY, WorkbookReader

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
# PO record 中各链段的单价列名（产品方案 §10.1 + 数据源观察）
# —————————————————————————————————————
#
# PO record 的单价列已经按链段命名（不带 category），每行内的价格直接就是该 SAP 的实际单价。
PO_PRICE_COLUMNS: Final[dict[tuple[str, str], str]] = {
    (ENTITY_SK_YM, ENTITY_GS_PTE): "SK/YM USD FOB",
    (ENTITY_GS_PTE, ENTITY_EMAX_PTE): "GS PTE FOB",
    (ENTITY_EMAX_PTE, ENTITY_PF): "EMAX PTE",
}


# —————————————————————————————————————
# 公开 API
# —————————————————————————————————————


@dataclass(frozen=True)
class ResolveResult:
    """resolver 输出：解析出的 OrderLine + 校验消息。"""

    lines: tuple[OrderLine, ...]
    messages: tuple[ValidationMessage, ...]


def resolve_po_lines(reader: WorkbookReader, po_no: str) -> ResolveResult:
    """解析指定 PO 号的所有订单行。

    返回值约定：
    - 当任何阻断错误产生时，messages 非空，**lines 仍包含已成功解析的行**
      （UI/CLI 可以"部分显示"，让用户看见 13 行里第 7 行是为什么坏的）。
    - 当 PO 号根本不存在时，messages 含 PO_NOT_FOUND，lines 为空。
    - 上层（generator/cli）决定阻断错误是否阻断整个流水线。
    """
    products = _build_product_index(reader)
    po_rows = _read_po_record_rows(reader, po_no)

    if not po_rows:
        return ResolveResult(
            lines=(),
            messages=(
                ValidationMessage(
                    kind="blocking_error",
                    code=CODE_PO_NOT_FOUND,
                    message=f"PO 号 {po_no!r} 在 PO record 中不存在",
                    sheet=SHEET_PO_RECORD,
                    field="PO NO.",
                ),
            ),
        )

    lines: list[OrderLine] = []
    messages: list[ValidationMessage] = []
    for row in po_rows:
        line, row_messages = _resolve_row(row, products)
        messages.extend(row_messages)
        if line is not None:
            lines.append(line)

    return ResolveResult(lines=tuple(lines), messages=tuple(messages))


# —————————————————————————————————————
# DATA BASE → Product 索引
# —————————————————————————————————————


def _build_product_index(reader: WorkbookReader) -> dict[str, Product]:
    """把 DATA BASE sheet 转成 SAP → Product 字典。

    重复 SAP 后写覆盖前——Phase 2 加入"重复 SAP 警告"时再细化。
    """
    sheet = reader.read_sheet(SHEET_DATA_BASE)
    index: dict[str, Product] = {}
    for row in sheet.rows:
        sap = _str_or_none(row.get("SAP"))
        if not sap:
            # DATA BASE 中没 SAP 的行视为无效产品，跳过
            continue
        category = _int_or_none(row.get("Category"))
        if category is None:
            # category 缺失时也跳过——下游 SAP 命中后会拿到不完整产品很危险
            continue
        index[sap] = Product(
            sap=sap,
            description=_str_or_empty(row.get("Material Description")),
            category=category,
            gs_model=_str_or_none(row.get("GS MODEL")),
            moq=_int_or_none(row.get("MOQ")),
            fob_lt=_int_or_none(row.get("FOB LT")),
            brand=_str_or_none(row.get("品牌")),
            rfid=_str_or_none(row.get("RFID")),
            packing_type=_str_or_none(row.get("包装")),
            main_part_no=_str_or_none(row.get("主件编号")),
            inner_case_value=_decimal_or_none(row.get("inner case value")),
            carton_qty=_decimal_or_none(row.get("round value")),
            net_weight=_decimal_or_none(row.get("N/W")),
            gross_weight=_decimal_or_none(row.get("G/W")),
            length=_decimal_or_none(row.get("L")),
            width=_decimal_or_none(row.get("W")),
            height=_decimal_or_none(row.get("H")),
            cbm=_decimal_or_none(row.get("CBM")),
            # DATA BASE 价格矩阵在 Phase 1 不参与解析，Phase 2 再处理
            prices={},
        )
    return index


# —————————————————————————————————————
# PO record 行解析
# —————————————————————————————————————


def _read_po_record_rows(
    reader: WorkbookReader,
    po_no: str,
) -> tuple[dict[str, object], ...]:
    """读 PO record 并按 PO 号过滤。"""
    sheet = reader.read_sheet(SHEET_PO_RECORD)
    target = po_no.strip()
    matched: list[dict[str, object]] = []
    for row in sheet.rows:
        cell_value = _str_or_none(row.get("PO NO."))
        if cell_value and cell_value == target:
            matched.append(row)
    return tuple(matched)


def _resolve_row(
    row: dict[str, object],
    products: dict[str, Product],
) -> tuple[OrderLine | None, list[ValidationMessage]]:
    """把单行 PO record 转成 OrderLine。

    返回 None 表示该行因关键字段缺失无法装配，但已收集相应阻断消息。
    """
    row_number = _int_or_none(row.get(ROW_NUMBER_KEY))
    messages: list[ValidationMessage] = []

    sap = _str_or_none(row.get("SAP Number"))
    if not sap:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_SAP_MISSING,
                message="行缺少 SAP Number",
                sheet=SHEET_PO_RECORD,
                row=row_number,
                field="SAP Number",
            )
        )
        return None, messages

    product = products.get(sap)
    if product is None:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_SAP_NOT_IN_DATA_BASE,
                message=f"SAP {sap!r} 在 DATA BASE 中不存在",
                sheet=SHEET_PO_RECORD,
                row=row_number,
                field="SAP Number",
            )
        )
        return None, messages

    qty_raw = row.get("FINALQTY")
    if qty_raw is None or qty_raw == "":
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_QTY_MISSING,
                message="行缺少 FINALQTY",
                sheet=SHEET_PO_RECORD,
                row=row_number,
                field="FINALQTY",
            )
        )
        return None, messages
    quantity = _decimal_or_none(qty_raw)
    if quantity is None:
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_QTY_INVALID,
                message=f"FINALQTY 不是有效数字：{qty_raw!r}",
                sheet=SHEET_PO_RECORD,
                row=row_number,
                field="FINALQTY",
            )
        )
        return None, messages

    # 价格与小计：按合法链段挨个尝试
    prices, subtotals, price_messages = _collect_prices(row, quantity, row_number)
    messages.extend(price_messages)
    if not prices:
        # 任意链段都没价格——这条行无法装配任何单据
        messages.append(
            ValidationMessage(
                kind="blocking_error",
                code=CODE_NO_PRICES,
                message=f"SAP {sap!r} 在所有链段下均无可用价格",
                sheet=SHEET_PO_RECORD,
                row=row_number,
                field="SK/YM USD FOB",
            )
        )
        return None, messages

    # 月度出货
    monthly = _read_monthly_shipments(row)

    # 装箱字段（公式列回退）
    carton_count, carton_msg = _read_with_fallback(
        row,
        "CTNS",
        lambda: _compute_ctns(quantity, product.carton_qty),
        row_number,
    )
    if carton_msg is not None:
        messages.append(carton_msg)
    total_cbm, cbm_msg = _read_with_fallback(
        row,
        "TOTAL CBM",
        lambda: _compute_total_cbm(product, carton_count),
        row_number,
    )
    if cbm_msg is not None:
        messages.append(cbm_msg)

    line = OrderLine(
        po_no=_str_or_empty(row.get("PO NO.")),
        item_line_no=_str_or_empty(row.get("ITEM LINE#")),
        sap=sap,
        description=_str_or_empty(row.get("DESCRIPTION")) or product.description,
        category=product.category,
        quantity=quantity,
        product=product,
        ship_to=_str_or_none(row.get("SHIP TO")),
        brand=_str_or_none(row.get("BRAND")) or product.brand,
        invoice_no=_str_or_none(row.get("INV#")),
        factory_doc_no=_str_or_none(row.get("FACTORY DOC NO.")),
        carton_count=carton_count,
        net_weight=_decimal_or_none(row.get("N/W")) or product.net_weight,
        gross_weight=_decimal_or_none(row.get("G/W")) or product.gross_weight,
        total_cbm=total_cbm,
        prices=prices,
        subtotals=subtotals,
        monthly_shipments=monthly,
        source_row=row_number,
    )
    return line, messages


def _collect_prices(
    row: dict[str, object],
    quantity: Decimal,
    row_number: int | None,
) -> tuple[dict[tuple[str, str], Decimal], dict[tuple[str, str], Decimal], list[ValidationMessage]]:
    """按合法链段读取每段单价并计算小计。

    某段没数据时整体不报，只在所有段都没数据时由调用方报 NO_PRICES。
    """
    prices: dict[tuple[str, str], Decimal] = {}
    subtotals: dict[tuple[str, str], Decimal] = {}
    messages: list[ValidationMessage] = []
    for segment in LEGAL_CHAIN_SEGMENTS:
        column = PO_PRICE_COLUMNS.get(segment)
        if column is None:
            continue
        raw = row.get(column)
        if raw is None or raw == "":
            continue
        price = _decimal_or_none(raw)
        if price is None:
            messages.append(
                ValidationMessage(
                    kind="warning",
                    code="PRICE_NOT_DECIMAL",
                    message=f"链段 {segment[0]}→{segment[1]} 的单价 {raw!r} 不是有效数字",
                    sheet=SHEET_PO_RECORD,
                    row=row_number,
                    field=column,
                    severity="high",
                )
            )
            continue
        prices[segment] = price
        subtotals[segment] = (price * quantity).quantize(Decimal("0.01"))
    return prices, subtotals, messages


def _read_monthly_shipments(row: dict[str, object]) -> dict[str, Decimal]:
    """读 2601~2612 月度列，0 或空跳过。"""
    out: dict[str, Decimal] = {}
    for month in MONTH_COLUMNS:
        raw = row.get(month)
        if raw is None or raw == "":
            continue
        amount = _decimal_or_none(raw)
        if amount is None or amount == 0:
            continue
        out[month] = amount
    return out


# —————————————————————————————————————
# 公式回退（产品方案 §10.4）
# —————————————————————————————————————


def _read_with_fallback(
    row: dict[str, object],
    field_name: str,
    compute_fn: _DecimalThunk,
    row_number: int | None,
) -> tuple[Decimal | None, ValidationMessage | None]:
    """读公式列；读到 None 时按 §10.2 现算并产生 high warning。"""
    raw = row.get(field_name)
    if raw is not None and raw != "":
        value = _decimal_or_none(raw)
        if value is not None:
            return value, None
    # 现算
    fallback = compute_fn()
    if fallback is None:
        return None, None
    return (
        fallback,
        ValidationMessage(
            kind="warning",
            code=CODE_FORMULA_FALLBACK,
            message=(
                f"{field_name} 在 base 文件中无缓存值，工作台按公式现算。"
                "建议在 Excel 中保存一次以更新缓存。"
            ),
            sheet=SHEET_PO_RECORD,
            row=row_number,
            field=field_name,
            severity="high",
        ),
    )


def _compute_ctns(quantity: Decimal, carton_qty: Decimal | None) -> Decimal | None:
    if carton_qty is None or carton_qty == 0:
        return None
    return (quantity / carton_qty).quantize(Decimal("0.0001"))


def _compute_total_cbm(product: Product, carton_count: Decimal | None) -> Decimal | None:
    if carton_count is None:
        return None
    if product.length is None or product.width is None or product.height is None:
        return None
    per_ctn = product.length * product.width * product.height / Decimal("1000000")
    return (per_ctn * carton_count).quantize(Decimal("0.0001"))


# —————————————————————————————————————
# 类型转换工具
# —————————————————————————————————————

_DecimalThunk = Callable[[], "Decimal | None"]


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _str_or_empty(value: object) -> str:
    return _str_or_none(value) or ""


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        # bool 是 int 的子类，但表示业务数字时无意义
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    """把 openpyxl 单元格值转成 Decimal。

    `int`/`float`/`str` 都接受；`None`、空串、非数字返回 None。
    `float` 通过 str 中转避免精度污染。
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
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
    "resolve_po_lines",
]
