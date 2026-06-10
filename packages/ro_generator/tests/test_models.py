"""领域模型测试：冻结性、默认值、Decimal 精度、空集合默认。"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import pytest
from ro_generator.models import (
    DocumentRequest,
    GenerationResult,
    OrderLine,
    Product,
    ValidationMessage,
)


class TestFrozen:
    """所有 dataclass 必须冻结，不可变。"""

    def test_validation_message_frozen(self) -> None:
        msg = ValidationMessage(kind="warning", code="TEST", message="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            msg.code = "OTHER"  # type: ignore[misc]

    def test_product_frozen(self) -> None:
        p = Product(sap="123", description="desc", category=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.sap = "456"  # type: ignore[misc]

    def test_order_line_frozen(self) -> None:
        line = _make_order_line()
        with pytest.raises(dataclasses.FrozenInstanceError):
            line.po_no = "9999"  # type: ignore[misc]

    def test_document_request_frozen(self) -> None:
        req = DocumentRequest(base_file="/x", po_no="1", documents=("PI",))
        with pytest.raises(dataclasses.FrozenInstanceError):
            req.po_no = "2"  # type: ignore[misc]

    def test_generation_result_frozen(self) -> None:
        result = GenerationResult(status="success")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = "error"  # type: ignore[misc]


class TestProductDefaults:
    def test_minimal_product(self) -> None:
        p = Product(sap="21-44640", description="CB2500.B2", category=1)
        assert p.sap == "21-44640"
        assert p.brand is None
        assert p.prices == {}
        assert p.cbm is None

    def test_independent_default_dicts(self) -> None:
        # 防回归：default_factory 必须保证两个实例的 prices 不是同一个对象
        a = Product(sap="A", description="", category=1)
        b = Product(sap="B", description="", category=1)
        assert a.prices is not b.prices

    def test_decimal_precision_preserved(self) -> None:
        p = Product(
            sap="A",
            description="",
            category=1,
            prices={"GS PTE/combo": Decimal("32.80")},
        )
        # 不应该自动转 float 丢精度
        assert p.prices["GS PTE/combo"] == Decimal("32.80")
        assert p.prices["GS PTE/combo"] != Decimal("32.8000001")


class TestOrderLineDefaults:
    def test_minimal(self) -> None:
        line = _make_order_line()
        assert line.po_no == "4500030844"
        assert line.invoice_no is None
        assert line.ship_qty is None
        assert line.prices == {}

    def test_holds_product_reference(self) -> None:
        prod = Product(sap="A", description="", category=1)
        line = _make_order_line(product=prod)
        assert line.product is prod

    def test_subtotals_keyed_by_chain_segment(self) -> None:
        line = _make_order_line(
            quantity=Decimal("100"),
            subtotals={
                ("SK/YM", "GS PTE"): Decimal("3280.00"),
                ("GS PTE", "EMAX PTE"): Decimal("3500.00"),
            },
        )
        assert line.subtotals[("SK/YM", "GS PTE")] == Decimal("3280.00")
        assert line.subtotals[("GS PTE", "EMAX PTE")] == Decimal("3500.00")


class TestDocumentRequestDefaults:
    def test_minimal(self) -> None:
        req = DocumentRequest(
            base_file="/path/to/base.xlsx",
            po_no="4500030844",
            documents=("PI", "INVOICE"),
        )
        assert req.seller is None
        assert req.invoice_no is None
        assert req.output_format == "xlsx"
        assert req.output_dir == "outputs"
        assert req.on_conflict == "overwrite"

    def test_documents_as_tuple(self) -> None:
        # documents 必须是不可变的 tuple，避免外部修改影响装配
        req = DocumentRequest(
            base_file="/x",
            po_no="1",
            documents=("PI", "PO", "INVOICE", "PL"),
        )
        assert req.documents == ("PI", "PO", "INVOICE", "PL")


class TestGenerationResultDefaults:
    def test_success_default(self) -> None:
        result = GenerationResult(status="success")
        assert result.files == ()
        assert result.errors == ()
        assert result.missing_inputs == ()
        assert result.options == {}

    def test_needs_input_with_options(self) -> None:
        result = GenerationResult(
            status="needs_input",
            missing_inputs=("invoice_no",),
            options={
                "invoice_no": (
                    {"value": "2601", "label": "2026 年 1 月"},
                    {"value": "2602", "label": "2026 年 2 月"},
                )
            },
        )
        assert "invoice_no" in result.options
        assert len(result.options["invoice_no"]) == 2


# ————————————————————————————————————————
# helpers
# ————————————————————————————————————————


def _make_order_line(**overrides: object) -> OrderLine:
    defaults: dict[str, object] = {
        "po_no": "4500030844",
        "item_line_no": "10",
        "sap": "21-44640",
        "description": "CB2500.B2",
        "category": 1,
        "quantity": Decimal("100"),
        "product": Product(sap="21-44640", description="CB2500.B2", category=1),
        "order_date": date(2026, 1, 15),
    }
    defaults.update(overrides)
    return OrderLine(**defaults)  # type: ignore[arg-type]
