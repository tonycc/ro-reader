"""Profile、规则和一次业务执行上下文的不可变领域模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ro_generator.base_schema import BaseSchema
from ro_generator.errors import InvalidProfileError
from ro_generator.models import DocumentType

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from ro_generator.models import CostBreakdownItem, OrderLine


@dataclass(frozen=True)
class ProfileAssets:
    """一个 Profile 的声明式资源位置。

    ``root`` 是当前 Profile 的资源根；模板和 mapping 目录均相对它声明。
    调用方不应自行拼接仓库级路径。
    """

    root: Path
    schema_path: Path
    template_root: Path
    mapping_root: Path
    seller_directories: Mapping[str, str] = field(default_factory=dict)
    mapping_filenames: Mapping[str, str] = field(default_factory=dict)

    def mapping_path(self, seller: str, document: str) -> Path | None:
        """Resolve a seller/document mapping through this Profile's assets."""

        seller_dir = self.seller_directories.get(seller)
        mapping_filename = self.mapping_filenames.get(document.strip().upper())
        if seller_dir is None or mapping_filename is None:
            return None
        return self.mapping_root / seller_dir / "mappings" / mapping_filename


@runtime_checkable
class CustomerRules(Protocol):
    """客户差异规则的最小协议。

    规则对象只描述客户业务，不保存当前 workbook 或可变 session 状态。
    """

    @property
    def profile_id(self) -> str: ...

    @property
    def seller_to_buyer(self) -> Mapping[str, str]: ...

    @property
    def quantity_source_by_document(self) -> Mapping[str, str]: ...

    @property
    def po_price_columns(self) -> Mapping[str, str]: ...

    @property
    def data_base_price_columns(self) -> Mapping[str, str]: ...

    @property
    def invoice_data_base_price_columns(self) -> Mapping[str, str]: ...

    @property
    def data_base_component_price_columns(self) -> Mapping[str, str]: ...

    @property
    def rule_modules(self) -> tuple[str, ...]: ...

    @property
    def filename_strategy(self) -> str: ...

    @property
    def invoice_grouping_strategy(self) -> str: ...

    def buyer_for(self, seller: str) -> str | None:
        """返回卖方对应的买方；未知卖方返回 None。"""

    @property
    def order_constraint_checks(self) -> tuple[str, ...]: ...

    @property
    def include_customer_po_only_orders(self) -> bool: ...

    def category_for_value(self, value: object) -> int | None:
        """把当前客户的 Category 表达转换为核心统一类别编号。"""

    def shipment_quantity_for_row(
        self,
        row: Mapping[str, object],
        schema: BaseSchema,
    ) -> tuple[object | None, str]:
        """返回出货数量原值和其真实来源表头。"""

    def packing_values_for_line(
        self,
        line: OrderLine,
        quantity: Decimal,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        """返回 PL 行的箱数、净重、毛重和总体积。"""

    def price_segment(
        self,
        document_type: str,
        seller: str,
        buyer: str,
    ) -> tuple[str, str]: ...

    def uses_po_record_unit_price(self, document_type: str) -> bool:
        """Invoice 是否从当前 PO record 出货行读取按主体聚合的单价。"""

    def unit_price_for_line(
        self,
        line: OrderLine,
        document_type: str,
        segment: tuple[str, str],
    ) -> Decimal | None:
        """返回当前单据行应使用的单价；缺失时返回 None。"""

    def pi_no_for_lines(
        self,
        lines: tuple[OrderLine, ...],
        seller: str,
        po_no: str,
    ) -> tuple[str | None, str | None]:
        """返回 PI 编号和缺失时需要提示的源字段。"""

    def invoice_no_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> str | None: ...

    def invoice_no_matches(
        self,
        line: OrderLine,
        requested_invoice_no: str,
        document_type: str,
        seller: str,
    ) -> bool: ...

    def header_ex_factory_date_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> date | None: ...

    def line_ex_factory_date_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> date | None: ...

    def ex_factory_source(
        self,
        document_type: str,
        seller: str,
        scope: str,
    ) -> tuple[str, str]:
        """返回出厂日期的逻辑 Sheet 和 schema 内部字段键。"""

    def manufacturer_header_values(
        self,
        lines: tuple[OrderLine, ...],
        document_type: str,
        seller: str,
    ) -> tuple[str | None, str | None, str | None]:
        """返回表头制造商名称及两行地址；不适用时返回三个 None。"""

    def cost_breakdown_for_line(
        self,
        line: OrderLine,
        document_type: str,
        seller: str,
    ) -> tuple[CostBreakdownItem, ...]:
        """返回当前单据需要展示的 Combo 组件价格。"""


@dataclass(frozen=True)
class ProfileCapabilities:
    """Profile 可用主体、单据和币种声明。"""

    sellers: tuple[str, ...]
    supported_documents_by_seller: Mapping[str, tuple[DocumentType, ...]]
    currencies: tuple[str, ...] = ("USD",)

    def __post_init__(self) -> None:
        if not self.sellers or len(set(self.sellers)) != len(self.sellers):
            raise InvalidProfileError("Profile sellers 必须非空且不能重复")
        if not self.currencies or len(set(self.currencies)) != len(self.currencies):
            raise InvalidProfileError("Profile currencies 必须非空且不能重复")
        unknown_sellers = set(self.supported_documents_by_seller) - set(self.sellers)
        if unknown_sellers:
            names = ", ".join(sorted(unknown_sellers))
            raise InvalidProfileError(f"单据能力声明包含未知 seller：{names}")
        for seller, documents in self.supported_documents_by_seller.items():
            if not documents or len(set(documents)) != len(documents):
                raise InvalidProfileError(f"seller {seller} 的 supported documents 不能为空或重复")

    def documents_for(self, seller: str) -> tuple[DocumentType, ...]:
        return self.supported_documents_by_seller.get(seller, ())

    def supports(self, seller: str, document: DocumentType) -> bool:
        return document in self.documents_for(seller)


@dataclass(frozen=True)
class CustomerProfile:
    """客户 Profile 的完整声明。"""

    profile_id: str
    display_name: str
    version: str
    assets: ProfileAssets
    schema: BaseSchema
    rules: CustomerRules
    capabilities: ProfileCapabilities

    def __post_init__(self) -> None:
        if not self.profile_id or self.profile_id.strip() != self.profile_id:
            raise InvalidProfileError("Profile ID 不能为空且不能包含首尾空格")
        if any(char.isspace() for char in self.profile_id):
            raise InvalidProfileError(f"Profile ID 不能包含空白字符：{self.profile_id}")
        if not self.display_name.strip():
            raise InvalidProfileError(f"Profile {self.profile_id} 缺少 display_name")
        if not self.version.strip():
            raise InvalidProfileError(f"Profile {self.profile_id} 缺少 version")
        if self.rules.profile_id != self.profile_id:
            raise InvalidProfileError(
                f"Profile {self.profile_id} 的 rules.profile_id 不匹配：{self.rules.profile_id}"
            )

    def mapping_path(self, seller: str, document: str) -> Path | None:
        """Resolve one mapping using the Profile's declared asset layout."""

        return self.assets.mapping_path(seller, document)


@dataclass(frozen=True)
class GenerationContext:
    """一次核心业务执行绑定的不可变 Profile + base 文件身份。"""

    profile: CustomerProfile
    base_file: Path

    def __post_init__(self) -> None:
        if not isinstance(self.base_file, Path):
            object.__setattr__(self, "base_file", Path(self.base_file))
        object.__setattr__(self, "base_file", self.base_file.expanduser().absolute())

    @property
    def profile_id(self) -> str:
        return self.profile.profile_id

    @property
    def base_path(self) -> Path:
        return self.base_file

    @property
    def schema(self) -> BaseSchema:
        return self.profile.schema

    @property
    def rules(self) -> CustomerRules:
        return self.profile.rules
