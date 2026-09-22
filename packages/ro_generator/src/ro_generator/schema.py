"""核心包静态 schema：必需 sheet、必需表头、月份列、表头规范化。

来源：默认 Profile 的 `base_schema.yaml`（产品方案 §9 + 实际表头观察）。

表头规范化的必要性：openpyxl 读出来的表头单元格可能含换行符 (`\\n`)、
首尾空白、连续空格（如 `"GS PTE \\nFOB "`），下游匹配时必须先归一。
"""

from __future__ import annotations

import re
from typing import Final

from ro_generator.base_schema import BaseSchema, base_schema


def _default_schema() -> BaseSchema:
    """Legacy constants use the cached default schema without retaining it globally."""

    return base_schema()


# —————————————————————————————————————
# 必需 sheet
# —————————————————————————————————————
SHEET_DATA_BASE: Final = _default_schema().sheet("DATA BASE").name
SHEET_PO_RECORD: Final = _default_schema().sheet("PO record").name
SHEET_CUSTOMER_PO: Final = _default_schema().sheet("客户PO").name


# —————————————————————————————————————
# 类别（产品方案 §10.1）
# —————————————————————————————————————

CATEGORY_COMBO: Final = 1
CATEGORY_ROD: Final = 2
CATEGORY_REEL: Final = 3

CATEGORY_NAMES: Final[dict[int, str]] = {
    CATEGORY_COMBO: "combo",
    CATEGORY_ROD: "rod",
    CATEGORY_REEL: "reel",
}


# —————————————————————————————————————
# 贸易链段（产品方案 §3.3）
# —————————————————————————————————————
ENTITY_SK: Final = "SK"
ENTITY_YM: Final = "YM"
ENTITY_GS_PTE: Final = "GS PTE"
ENTITY_EMAX_PTE: Final = "EMAX PTE"
ENTITY_PF: Final = "PF"

# 卖方主体列表（按贸易链顺序）
SELLERS: Final[tuple[str, ...]] = (ENTITY_SK, ENTITY_YM, ENTITY_GS_PTE, ENTITY_EMAX_PTE)

# 卖方 → 买方（固定对应关系）
SELLER_TO_BUYER: Final[dict[str, str]] = {
    ENTITY_SK: ENTITY_YM,
    ENTITY_YM: ENTITY_GS_PTE,
    ENTITY_GS_PTE: ENTITY_EMAX_PTE,
    ENTITY_EMAX_PTE: ENTITY_PF,
}

# 卖方 → 价格列名（来自 base_schema.yaml，PO record 中）
SELLER_PRICE_COLUMNS: Final[dict[str, str]] = dict(_default_schema().price_columns)

# DATA BASE 中按 (卖方, 品类) 的价格列
DATA_BASE_PRICE_COLUMNS: Final[dict[str, str]] = dict(_default_schema().data_base_price_columns)


# —————————————————————————————————————
# 必需表头
# —————————————————————————————————————
#
# 这里只列**必需的**表头，不全部列出。可选字段在 validator
# 里走"缺失只产生 low warning"路径。
#
# 表头名以**规范化后的形式**给出（去除换行 / 多余空格），匹配时双方都先 normalize。


def required_headers_for(
    schema: BaseSchema | None = None,
) -> dict[str, tuple[str, ...]]:
    """返回指定 Profile schema 各逻辑 sheet 的必需表头（按逻辑 key 索引）。"""

    active = schema or _default_schema()
    headers: dict[str, tuple[str, ...]] = {
        "DATA BASE": (
            active.field("DATA BASE", "sap"),
            active.field("DATA BASE", "description"),
            active.field("DATA BASE", "category"),
        ),
        "PO record": (
            active.field("PO record", "po_no"),
            active.field("PO record", "item_line"),
            active.field("PO record", "sap"),
        ),
        "客户PO": (
            active.field("客户PO", "purchasing_document"),
            active.field("客户PO", "material"),
            active.field("客户PO", "order_quantity"),
        ),
    }
    # options 价格版本表：必需表头为全部 "{卖方前缀}-{单据后缀}" 键列。
    options_key = active.price_options.sheet if active.price_options is not None else None
    if options_key and options_key in active.sheets and active.price_options is not None:
        headers[options_key] = active.price_options.required_keys
    return headers


# —————————————————————————————————————
# 表头规范化
# —————————————————————————————————————

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_header(raw: object) -> str:
    """把表头单元格的值规范化为可匹配字符串。

    - None / 非字符串 → 空串（让上层校验"缺表头"）
    - 所有连续空白（含换行、tab、全角空格）压成单个 ASCII 空格
    - 首尾空白去除
    - 大小写**保留**——表头里的大小写有业务含义（如 `INV#` 与 `Inv#`）

    示例：
        normalize_header("GS PTE \\nFOB ") == "GS PTE FOB"
        normalize_header(None) == ""
    """
    if not isinstance(raw, str):
        return ""
    # 把全角空格也并入空白处理
    cleaned = raw.replace("　", " ")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()
