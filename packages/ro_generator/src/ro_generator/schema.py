"""核心包静态 schema：必需 sheet、必需表头、月份列、表头规范化。

来源：templates/base_schema.yaml（产品方案 §9 + 实际表头观察）。

表头规范化的必要性：openpyxl 读出来的表头单元格可能含换行符 (`\\n`)、
首尾空白、连续空格（如 `"GS PTE \\nFOB "`），下游匹配时必须先归一。
"""

from __future__ import annotations

import re
from typing import Final

from ro_generator.base_schema import base_schema

_schema = base_schema()

# —————————————————————————————————————
# 必需 sheet
# —————————————————————————————————————
SHEET_DATA_BASE: Final = _schema.sheet("DATA BASE").name
SHEET_PO_RECORD: Final = _schema.sheet("PO record").name
SHEET_CUSTOMER_PO: Final = _schema.sheet("客户PO").name

REQUIRED_SHEETS: Final[tuple[str, ...]] = (SHEET_DATA_BASE, SHEET_PO_RECORD, SHEET_CUSTOMER_PO)


# —————————————————————————————————————
# 表头位置约定
# —————————————————————————————————————
#
# 表头行和数据起始行由 base_schema.yaml 定义，默认第 4/5 行。
HEADER_ROW: Final = _schema.sheet("PO record").header_row
FIRST_DATA_ROW: Final = _schema.sheet("PO record").first_data_row


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

# 合法 (seller, buyer) 组合，按链路从工厂到最终客户排序。
LEGAL_CHAIN_SEGMENTS: Final[tuple[tuple[str, str], ...]] = (
    (ENTITY_SK, ENTITY_YM),
    (ENTITY_YM, ENTITY_GS_PTE),
    (ENTITY_GS_PTE, ENTITY_EMAX_PTE),
    (ENTITY_EMAX_PTE, ENTITY_PF),
)

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
SELLER_PRICE_COLUMNS: Final[dict[str, str]] = dict(_schema.price_columns)

# DATA BASE 中按 (卖方, 品类) 的价格列
DATA_BASE_PRICE_COLUMNS: Final[dict[str, str]] = dict(_schema.data_base_price_columns)

# PO record 中各链段发票金额列
INVOICE_AMOUNT_COLUMNS: Final[dict[str, str]] = dict(_schema.invoice_amount_columns)


# —————————————————————————————————————
# 必需表头
# —————————————————————————————————————
#
# 这里只列**必需的**表头，不全部列出。可选字段在 validator
# 里走"缺失只产生 low warning"路径。
#
# 表头名以**规范化后的形式**给出（去除换行 / 多余空格），匹配时双方都先 normalize。

DATA_BASE_REQUIRED_HEADERS: Final[tuple[str, ...]] = (
    _schema.field("DATA BASE", "sap"),
    _schema.field("DATA BASE", "description"),
    _schema.field("DATA BASE", "category"),
)

PO_RECORD_REQUIRED_HEADERS: Final[tuple[str, ...]] = (
    _schema.field("PO record", "po_no"),
    _schema.field("PO record", "item_line"),
    _schema.field("PO record", "sap"),
)

CUSTOMER_PO_REQUIRED_HEADERS: Final[tuple[str, ...]] = (
    _schema.field("客户PO", "purchasing_document"),
    _schema.field("客户PO", "material"),
    _schema.field("客户PO", "order_quantity"),
)


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


def normalize_headers(raw_headers: list[object]) -> list[str]:
    """对一行表头批量规范化。"""
    return [normalize_header(h) for h in raw_headers]
