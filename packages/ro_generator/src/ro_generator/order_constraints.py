"""客户订单层面的 MOQ 与整箱提醒。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from ro_generator.base_schema import BaseSchema
from ro_generator.models import Product, ValidationMessage
from ro_generator.workbook_reader import ROW_NUMBER_KEY

CODE_MOQ_NOT_MET: Final = "MOQ_NOT_MET"
CODE_FULL_CARTON_NOT_MET: Final = "FULL_CARTON_NOT_MET"
CHECK_MOQ: Final = "moq"
CHECK_FULL_CARTON: Final = "full_carton"


def validate_customer_order_constraints(
    customer_po_rows: tuple[dict[str, object], ...],
    products: dict[str, Product],
    *,
    target_saps: set[str],
    checks: tuple[str, ...],
    schema: BaseSchema,
) -> tuple[ValidationMessage, ...]:
    """按客户订单中的 Material 聚合数量，再检查主数据中的 MOQ/round value。"""

    enabled = set(checks)
    if not enabled or not customer_po_rows or not target_saps:
        return ()

    material_field = schema.field("客户PO", "material")
    quantity_field = schema.field("客户PO", "order_quantity")
    quantities: dict[str, Decimal] = {}
    source_rows: dict[str, int | None] = {}
    for row in customer_po_rows:
        sap = _as_text(row.get(material_field))
        if not sap or sap not in target_saps:
            continue
        quantity = _as_decimal(row.get(quantity_field))
        if quantity is None:
            continue
        quantities[sap] = quantities.get(sap, Decimal(0)) + quantity
        source_rows.setdefault(sap, _as_int(row.get(ROW_NUMBER_KEY)))

    messages: list[ValidationMessage] = []
    customer_po_sheet = schema.sheet("客户PO").name
    for sap in sorted(quantities):
        quantity = quantities[sap]
        product = products.get(sap)
        if product is None:
            continue

        if CHECK_MOQ in enabled and product.moq is not None:
            minimum = Decimal(product.moq)
            if minimum > 0 and quantity < minimum:
                messages.append(
                    ValidationMessage(
                        kind="warning",
                        code=CODE_MOQ_NOT_MET,
                        severity="high",
                        message=(
                            f"SAP {sap} 的客户订单数量 {_display(quantity)} 低于 MOQ "
                            f"{_display(minimum)}，请确认是否调整订单数量"
                        ),
                        sheet=customer_po_sheet,
                        row=source_rows.get(sap),
                        field=quantity_field,
                        sap=sap,
                    )
                )

        carton_qty = product.carton_qty
        if CHECK_FULL_CARTON in enabled and carton_qty is not None and carton_qty > 0:
            remainder = quantity % carton_qty
            if remainder != 0:
                messages.append(
                    ValidationMessage(
                        kind="warning",
                        code=CODE_FULL_CARTON_NOT_MET,
                        severity="high",
                        message=(
                            f"SAP {sap} 的客户订单数量 {_display(quantity)} 不是整箱数量 "
                            f"{_display(carton_qty)} 的整数倍（余数 {_display(remainder)}），"
                            "请确认装箱安排"
                        ),
                        sheet=customer_po_sheet,
                        row=source_rows.get(sap),
                        field=quantity_field,
                        sap=sap,
                    )
                )
    return tuple(messages)


def constraint_alerts_by_sap(
    messages: tuple[ValidationMessage, ...] | list[ValidationMessage],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """按 SAP 归并 MOQ/整箱提醒 (code, message)，供 PI/PO 预览标红 Quantity。"""

    grouped: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for message in messages:
        if message.sap is None:
            continue
        if message.code not in {CODE_MOQ_NOT_MET, CODE_FULL_CARTON_NOT_MET}:
            continue
        codes = seen.setdefault(message.sap, set())
        if message.code in codes:
            continue
        codes.add(message.code)
        grouped.setdefault(message.sap, []).append((message.code, message.message))
    return {sap: tuple(items) for sap, items in grouped.items()}


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    if text.endswith(".0"):
        integer, decimal = text.rsplit(".", 1)
        if decimal == "0" and integer.lstrip("-").isdigit():
            return integer
    return text


def _as_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _as_int(value: object) -> int | None:
    decimal = _as_decimal(value)
    if decimal is None or decimal != decimal.to_integral_value():
        return None
    return int(decimal)


def _display(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


__all__ = [
    "CHECK_FULL_CARTON",
    "CHECK_MOQ",
    "CODE_FULL_CARTON_NOT_MET",
    "CODE_MOQ_NOT_MET",
    "constraint_alerts_by_sap",
    "validate_customer_order_constraints",
]
