"""客户订单 MOQ 与整箱提醒规则测试。"""

from __future__ import annotations

from decimal import Decimal

from ro_generator.models import Product
from ro_generator.order_constraints import (
    CODE_FULL_CARTON_NOT_MET,
    CODE_MOQ_NOT_MET,
    constraint_alerts_by_sap,
    validate_customer_order_constraints,
)
from ro_generator.profiles import create_pf_profile
from ro_generator.workbook_reader import ROW_NUMBER_KEY


def _product() -> Product:
    return Product(
        sap="10001",
        description="PF test product",
        category=2,
        moq=100,
        carton_qty=Decimal("24"),
    )


def test_below_moq_and_non_full_carton_are_non_blocking_high_warnings() -> None:
    profile = create_pf_profile()
    rows = (
        {
            "PO#": "4500000001",
            "Material": "10001",
            "Order Quantity": 90,
            ROW_NUMBER_KEY: 7,
        },
    )

    messages = validate_customer_order_constraints(
        rows,
        {"10001": _product()},
        target_saps={"10001"},
        checks=profile.rules.order_constraint_checks,
        schema=profile.schema,
    )

    assert [message.code for message in messages] == [
        CODE_MOQ_NOT_MET,
        CODE_FULL_CARTON_NOT_MET,
    ]
    assert all(message.kind == "warning" for message in messages)
    assert all(message.severity == "high" for message in messages)
    assert messages[0].sheet == "new PO template"
    assert messages[0].row == 7
    assert messages[0].sap == "10001"
    assert "低于 MOQ 100" in messages[0].message
    assert "余数 18" in messages[1].message
    assert constraint_alerts_by_sap(messages) == {
        "10001": (
            (
                CODE_MOQ_NOT_MET,
                "SAP 10001 的客户订单数量 90 低于 MOQ 100，请确认是否调整订单数量",
            ),
            (
                CODE_FULL_CARTON_NOT_MET,
                "SAP 10001 的客户订单数量 90 不是整箱数量 24 的整数倍（余数 18），请确认装箱安排",
            ),
        ),
    }


def test_constraints_aggregate_same_spec_and_accept_compliant_quantity() -> None:
    profile = create_pf_profile()
    rows = (
        {"Material": "10001", "Order Quantity": 48, ROW_NUMBER_KEY: 2},
        {"Material": "10001", "Order Quantity": 72, ROW_NUMBER_KEY: 3},
    )

    messages = validate_customer_order_constraints(
        rows,
        {"10001": _product()},
        target_saps={"10001"},
        checks=profile.rules.order_constraint_checks,
        schema=profile.schema,
    )

    assert messages == ()


def test_ro_profile_does_not_enable_pf_order_constraints() -> None:
    from ro_generator.profiles import create_ro_profile

    assert create_ro_profile().rules.order_constraint_checks == ()
