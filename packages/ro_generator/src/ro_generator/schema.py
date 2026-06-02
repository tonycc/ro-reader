"""核心包静态 schema：必需 sheet、必需表头、月份列、表头规范化。

来源：产品方案 §9（数据源说明）和 RO DATA BASE.xlsx 实际表头观察。

表头规范化的必要性：openpyxl 读出来的表头单元格可能含换行符 (`\\n`)、
首尾空白、连续空格（如 `"GS PTE \\nFOB "`），下游匹配时必须先归一。
"""

from __future__ import annotations

import re
from typing import Final

# —————————————————————————————————————
# 必需 sheet
# —————————————————————————————————————

SHEET_DATA_BASE: Final = "DATA BASE"
SHEET_PO_RECORD: Final = "PO record"

REQUIRED_SHEETS: Final[tuple[str, ...]] = (SHEET_DATA_BASE, SHEET_PO_RECORD)


# —————————————————————————————————————
# 表头位置约定
# —————————————————————————————————————
#
# 两张 sheet 的表头都在第 4 行，数据从第 5 行开始（产品方案 §9）。
HEADER_ROW: Final = 4
FIRST_DATA_ROW: Final = 5


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

ENTITY_SK_YM: Final = "SK/YM"
ENTITY_GS_PTE: Final = "GS PTE"
ENTITY_EMAX_PTE: Final = "EMAX PTE"
ENTITY_PF: Final = "PF"

# 合法 (seller, buyer) 组合，按链路从工厂到最终客户排序。
LEGAL_CHAIN_SEGMENTS: Final[tuple[tuple[str, str], ...]] = (
    (ENTITY_SK_YM, ENTITY_GS_PTE),
    (ENTITY_GS_PTE, ENTITY_EMAX_PTE),
    (ENTITY_EMAX_PTE, ENTITY_PF),
)


# —————————————————————————————————————
# 月度列：2601 ~ 2612（2026 年 1-12 月）
# —————————————————————————————————————

MONTH_COLUMNS: Final[tuple[str, ...]] = tuple(f"26{m:02d}" for m in range(1, 13))


# —————————————————————————————————————
# 必需表头
# —————————————————————————————————————
#
# 这里只列**必需的**表头，不全部列出。可选字段（如 `RFID`、`MOQ`）在 validator
# 里走"缺失只产生 low warning"路径。
#
# 表头名以**规范化后的形式**给出（去除换行 / 多余空格），匹配时双方都先 normalize。

DATA_BASE_REQUIRED_HEADERS: Final[tuple[str, ...]] = (
    "SAP",
    "Material Description",
    "Category",
)

PO_RECORD_REQUIRED_HEADERS: Final[tuple[str, ...]] = (
    "PO NO.",
    "ITEM LINE#",
    "SAP Number",
    "FINALQTY",
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
