"""核心包领域模型。

设计原则：
- 全部冻结 dataclass（`frozen=True`），不可变，避免下游意外修改。
- 金额一律 `Decimal`，禁止 float（精度丢失风险）。
- 日期一律 `date`（不带时区）；时间戳由调用方自管。
- 与 Excel 单元格无任何耦合——renderer 通过 mapping 决定写到哪个单元格，
  这些 dataclass 本身不知道自己会被写到 B17 还是 C18。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

# —————————————————————————————————————
# 校验消息
# —————————————————————————————————————

# 校验输出的三大类（产品方案 §11.1）
ValidationKind = Literal["blocking_error", "warning", "missing_input"]

# 警告严重度（产品方案 §11.2）
WarningSeverity = Literal["high", "low"]


@dataclass(frozen=True)
class ValidationMessage:
    """校验输出的统一载体。

    `kind` 决定它是阻断错误、警告还是缺信息。`code` 是稳定的机器可识别标识，
    UI / CLI 据此决定如何呈现；`message` 是给人看的中文说明。
    `severity` 仅在 `kind == "warning"` 时使用。
    """

    kind: ValidationKind
    code: str
    message: str
    sheet: str | None = None
    row: int | None = None  # 1-based，对应 openpyxl 行号
    field: str | None = None
    severity: WarningSeverity | None = None


# —————————————————————————————————————
# 产品主数据
# —————————————————————————————————————


@dataclass(frozen=True)
class Product:
    """`DATA BASE` 一行解析结果。

    `prices` 的 key 形如 `"GS PTE/combo"`，由 `(seller_or_chain, category_name)` 拼成，
    具体规则在 resolver 里集中处理。值缺失或为 0 时不放入字典。
    """

    sap: str
    description: str
    category: int  # 见 schema.CATEGORY_*

    # 可选字段（缺失时为 None 或空 dict）
    gs_model: str | None = None
    moq: int | None = None
    fob_lt: int | None = None
    brand: str | None = None
    rfid: str | None = None
    packing_type: str | None = None  # `包装` 列：carton / box / bulk / clam
    main_part_no: str | None = None  # `主件编号`

    # 装箱与物流
    inner_case_value: Decimal | None = None
    carton_qty: Decimal | None = None  # `round value` 外箱装箱数
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    cbm: Decimal | None = None

    # 价格表（key 由 resolver 定义）
    prices: dict[str, Decimal] = field(default_factory=dict)


# —————————————————————————————————————
# 订单行
# —————————————————————————————————————


@dataclass(frozen=True)
class OrderLine:
    """`PO record` 一行解析结果，已与 `DATA BASE` 中的产品 join。

    `subtotals` 是按链段预计算的小计，方便下游不同视图直接取用：
    `{ "SK/YM->GS PTE": Decimal("3280.00"), "GS PTE->EMAX PTE": ..., ... }`。

    `monthly_shipments` 的 key 形如 `"2601"`，值是该月发货数量；空月份不放入。

    `source_row` 是该行在 `PO record` sheet 中的 1-based 行号，供双向溯源
    索引（产品方案 §4.4）使用。
    """

    po_no: str
    item_line_no: str
    sap: str
    description: str
    category: int
    quantity: Decimal

    # 完整的产品链接，方便下游不再重复查表
    product: Product

    # 可选业务字段
    ship_to: str | None = None
    brand: str | None = None
    invoice_no: str | None = None  # `INV#`
    factory_doc_no: str | None = None  # `FACTORY DOC NO.`

    # 日期
    order_date: date | None = None
    delivery_date: date | None = None
    confirmed_ex_factory_date: date | None = None
    etd_on_board: date | None = None

    # 装箱（部分字段在 PO record 中维护，部分回退到 product）
    carton_count: Decimal | None = None  # CTNS
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    total_cbm: Decimal | None = None

    # 单价快照（按 (seller, buyer) 建索引，已选定本行 category 对应的列）
    prices: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    subtotals: dict[tuple[str, str], Decimal] = field(default_factory=dict)

    # 月度出货
    monthly_shipments: dict[str, Decimal] = field(default_factory=dict)

    # 双向溯源（产品方案 §4.4）
    source_row: int | None = None


# —————————————————————————————————————
# 文档请求与结果
# —————————————————————————————————————

# 单据类型
DocumentType = Literal["PI", "PO", "INVOICE", "PL"]


@dataclass(frozen=True)
class DocumentRequest:
    """一次装配请求。

    seller / buyer 可空：留给 resolver 在数据可推断单段时自动填，否则返回 needs_input。
    """

    base_file: str
    po_no: str
    documents: tuple[DocumentType, ...]
    seller: str | None = None
    buyer: str | None = None
    invoice_month: str | None = None  # 例如 "2601"
    invoice_no: str | None = None
    output_format: Literal["xlsx", "zip"] = "xlsx"
    output_dir: str = "outputs"
    on_conflict: Literal["overwrite", "rename", "abort"] = "overwrite"


# 装配结果状态（产品方案 §11.1）
ResultStatus = Literal["success", "error", "needs_input"]


@dataclass(frozen=True)
class GenerationResult:
    """装配流水线的统一返回结果。

    `status == "success"` 时 `files` 与 `output_file` 有值；
    `status == "error"` 时 `errors` 非空；
    `status == "needs_input"` 时 `missing_inputs` 与 `options` 有值。

    `source_index` 是装配单元格 ↔ base 字段的双向映射（产品方案 §4.4），
    工作台 UI 在 Phase 3 消费此索引实现双向高亮。
    """

    status: ResultStatus
    summary: dict[str, object] = field(default_factory=dict)
    files: tuple[str, ...] = ()
    output_file: str | None = None
    errors: tuple[ValidationMessage, ...] = ()
    warnings: tuple[ValidationMessage, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    options: dict[str, tuple[dict[str, str], ...]] = field(default_factory=dict)
    # 注：source_index 是 SourceIndex 类型，但避免 models.py 反向依赖 source_index.py，
    # 这里用 object 暂存。Phase 3 工作台后端可以用 isinstance 还原类型。
    source_index: object = None

    # 渲染元信息（供前端预览分拆表头/表格）
    metadata: dict[str, object] = field(default_factory=dict)
