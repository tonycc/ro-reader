# 四类单据字段取数逻辑

> 本文档说明 PI、PO、Invoice、PL 单据中每个字段的数据来源。适用于模板维护者（编写 YAML mapping）和开发维护者（理解渲染逻辑）。

## 通用概念

### 字段来源分类

| 来源 | 符号 | 说明 |
|---|---|---|
| 固定文案 | `固定` | 模板中已有，渲染器不覆盖。如公司名称、地址、银行信息。 |
| 调用方参数 | `参数` | 由 CLI 参数或 request.json 传入。如 seller、buyer、invoice_month。 |
| PO record 行 | `PO.字段` | 从 `PO record` sheet 当前 PO 的某行读取。 |
| PO record 元信息 | `PO/元` | 从 PO record 整体提取（如首条非空的 INV#、ship_to）。 |
| DATA BASE 产品 | `DB.字段` | 从 `DATA BASE` sheet 按 SAP 关联的产品主数据读取。 |
| 工作台计算 | `计算` | 由渲染引擎按业务规则现算（如金额 = 数量 × 单价）。 |
| 可选字段 | `可选` | 源数据中无对应字段时不报错，保留模板原值。 |

### 链段对价格列的影响

同一 PO 在不同贸易链段下使用不同的单价列：

| 链段 `(seller → buyer)` | 单价列名 | Invoice 金额列前缀 |
|---|---|---|
| SK/YM → GS PTE | `SK/YM USD FOB` | `GS-SK/YM INV-*` |
| GS PTE → EMAX PTE | `GS PTE FOB` | `EMAX-GS INV-*` |
| EMAX PTE → PF | `EMAX PTE` | `PF-EMAX INV-*` |

`SUBTOTAL = FINALQTY × 选定链段的 unit_price`。

---

## 1. PI — Proforma Invoice（形式发票）

### 表头区

| 单据字段 | 模板位置（GS PI 例） | 来源 | 取数逻辑 |
|---|---|---|---|
| 卖方公司名 | A1 | `固定` | 模板固定文案，不覆盖 |
| 卖方地址 | A2 | `固定` | 模板固定文案 |
| 单据标题 | F1 | `固定` | "PROFORMA INVOICE"，模板固定 |
| PI Number | B6 | `参数` | 从 request.po_no 生成或调用方传入 |
| Incoterm | B7 | `固定` | "FOB QINGDAO"（模板固定，不同主体可能不同） |
| Payment Terms | B8 | `固定` | "Net 75 days"（模板固定） |
| ETD | F6 | `可选` | `PO.ETD ON BOARD`，没有则留空 |
| Document Date | F7 | `可选` | `PO.ORDER DATE (EMAIL)` 或当前日期 |
| Ex-factory Date | F8 | `可选` | `PO.FINAL CONFIRMED EX-FACTORY DATE` |
| Bill To（客户名） | B10 | `固定` | 模板固定（取决于 seller/buyer 组合） |
| Ship To | F10 | `参数` / `PO/元` | request 参数或 `PO.SHIP TO` 首条非空 |
| Port of Loading | B14 | `固定` | 模板固定 |
| Final Destination | B15 | `固定` | 模板固定 |
| Manufacturer Name | F14 | `固定` | 模板固定 |
| Manufacturer Address | F15 | `固定` | 模板固定 |
| Number of Cartons | B16 | `计算` | PL 合计箱数，PI 阶段模板常留空 |

### 订单行

| 单据字段 | 模板列（GS PI 例） | 来源 | 取数逻辑 |
|---|---|---|---|
| Country of Origin | A | `固定` | "China"，模板固定 |
| PO Number | B | `PO.PO NO.` | PO record 行 |
| PO Item Line# | C | `PO.ITEM LINE#` | PO record 行 |
| Item Number (SAP) | D | `PO.SAP Number` | PO record 行，通过 SAP 关联 `DB.SAP` |
| Description | E | `DB.Material Description` | DATA BASE 产品描述（GS MODEL 或 Material Description） |
| USD Unit Price | F | `PO.{链段单价列}` | 按当前链段选列（如 `GS PTE FOB`） |
| Quantity | G | `PO.FINALQTY` | PO record 行——PI 始终用完整 PO 数量 |
| Sub-Total (Amount) | — | `计算` | `Quantity × USD Unit Price`（∑） |

### 页脚区

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| Signature | `固定` | 模板固定 |
| Date | `固定` | 模板固定 |

---

## 2. PO — Purchase Order（采购订单）

PO 结构与 PI 高度相似，区别在于 PO Number 语义不同（采购订单号 vs 形式发票号）。

### 表头区

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| 卖方公司名 / 地址 | `固定` | 模板固定 |
| 单据标题 | `固定` | "PURCHASE ORDER" |
| PO Number | `参数` | 由 request.po_no 传入 |
| Incoterm | `固定` | 模板固定 |
| Payment Terms | `固定` | 模板固定 |
| ETD | `可选` | `PO.ETD ON BOARD` |
| Document Date | `可选` | `PO.ORDER DATE (EMAIL)` 或当前日期 |
| Ex-factory Date | `可选` | `PO.FINAL CONFIRMED EX-FACTORY DATE` |
| Bill To / Ship To | `固定` / `PO/元` | 模板固定 + `PO.SHIP TO` |
| Supplier Name / Address | `固定` | 模板固定 |

### 订单行

与 PI 完全相同的取数逻辑（PO Number、Item Line#、SAP、Description、Unit Price、Quantity）。

---

## 3. Invoice（正式发票）

### 表头区

| 单据字段 | 模板位置（GS Invoice 例） | 来源 | 取数逻辑 |
|---|---|---|---|
| 卖方公司名 | A1 | `固定` | "GLOBALSINO PTE.LTD." 等，模板固定 |
| 卖方地址 | A2 | `固定` | 模板固定 |
| 单据标题 | F1 | `固定` | "INVOICE"，模板固定 |
| TO（买方） | A6-A8 | `固定` | 买方公司名和地址，模板固定 |
| INVOICE # | H6 | `PO/元` | `PO.INV#`，取首条非空。**Invoice 必填，缺失→阻断** |
| DATE | H7 | `可选` | `PO.ORDER DATE (EMAIL)` 或当前日期 |
| TERM | H8 | `固定` | "T/T 75DAYS AFTER BL DATE"，模板固定 |
| Shipped per | A10 | `固定` | 模板固定 |
| From | A11 | `固定` | 模板固定 |
| To | A12 | `固定` / `手动` | 模板固定，业务上可手动更新 |
| FACTORY DOC NO. | — | `PO/元` | `PO.FACTORY DOC NO.`，取首条非空。**Invoice 必填，缺失→阻断** |

### 订单行

| 单据字段 | 模板列（GS Invoice 例） | 来源 | 取数逻辑 |
|---|---|---|---|
| PO# | B | `PO.PO NO.` | PO record 行 |
| GOODS (Model) | C | `DB.GS MODEL` | DATA BASE 产品型号 |
| SAP ITEM# | D | `PO.SAP Number` | PO record 行 |
| Unit Price (FOB USD) | E | `PO.{链段单价列}` | 按当前链段选列 |
| QTY | F | `PO.FINALQTY` 或 `月度出货` | 无 invoice_month 时用完整数量；指定月份时用 `PO.{2601-2612}` |
| Unit | G | `固定` | "PCS"，模板固定（通过 mapping `unit_label`） |
| AMOUNT | H | `计算` | `= Unit Price × QTY`，渲染时写公式 `=E18*F18` |

### 合计

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| TOTAL QTY | `计算` | ∑ 所有行的 Quantity |
| TOTAL AMOUNT | `计算` | ∑ 所有行的 Amount |

### 页脚

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| ORIGIN IN CHINA | `固定` | 模板固定 |
| PACKED IN N CTNS | `计算` | `CTNS` 合计（箱数），来自 PL 或 resolver 公式回退 |
| NO SOLID WOOD... | `固定` | 模板固定 |

---

## 4. PL — Packing List（装箱单）

### 表头区

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| 卖方公司名 / 地址 | `固定` | 模板固定 |
| 单据标题 | `固定` | "PACKING LIST" |
| C/T# | `计算` / `手动` | 集装箱号或拖车号，业务上手工填写 |
| MADE IN CHINA | `固定` | 模板固定 |
| INVOICE # | `PO/元` | `PO.INV#`，取首条非空（与 Invoice 共用） |
| FACTORY DOC NO. | `PO/元` | `PO.FACTORY DOC NO.` |

### 订单行

| 单据字段 | 模板列（GS PL 例） | 来源 | 取数逻辑 |
|---|---|---|---|
| SAP PO# | B | `PO.PO NO.` | PO record 行 |
| Description of Goods | C | `DB.Material Description` | DATA BASE 产品描述 |
| SAP ITEM# | D | `PO.SAP Number` | PO record 行 |
| Quantity | E | `PO.FINALQTY` 或 `月度出货` | Invoice 同理：无月份用完整数量，有月份用月度出货 |
| Unit | F | `固定` | "PCS"，mapping 固定 |
| Net Weight | G | `计算` | `PO.N/W` 或 `DB.N/W × CTNS`（按行） |
| Gross Weight | — | `计算` | `PO.G/W` 或 `DB.G/W × CTNS`（按行） |
| Carton Count | `CTNS` | `计算` | `PO.CTNS`，用 `PO.FINALQTY ÷ 外箱` 现算（如缓存值缺失） |
| CBM | `TOTAL CBM` | `计算` | `PO.TOTAL CBM`，用 `L × W × H ÷ 1,000,000 × CTNS` 现算（如缓存值缺失） |

**PL 装箱字段阻断规则**：CTNS / N/W / G/W / TOTAL CBM 全部缺失时阻断（任意一行缺一项即阻断整张 PL）。

### 合计

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| TOTAL Quantity | `计算` | ∑ 所有行的 Quantity |
| TOTAL CTNS | `计算` | ∑ 所有行的 Carton Count |
| TOTAL N/W | `计算` | ∑ 所有行的 Net Weight |
| TOTAL G/W | `计算` | ∑ 所有行的 Gross Weight |
| TOTAL CBM | `计算` | ∑ 所有行的 CBM |

### 页脚

| 单据字段 | 来源 | 取数逻辑 |
|---|---|---|
| ORIGIN IN CHINA | `固定` | 模板固定 |
| PACKED IN N CTNS | `计算` | `TOTAL CTNS` |
| NO SOLID WOOD... | `固定` | 模板固定 |

---

## 装箱字段详解

装箱数据以 **PO record 为主、DATA BASE 为回退**。优先级：

### Carton Count（CTNS）

1. `PO.CTNS`（直接读取 PO record 中的缓存值）
2. 缓存值为 `None` → **公式回退**：`FINALQTY ÷ 外箱`（外箱来自 `PO.外箱` 列）
3. 产生 `FORMULA_FALLBACK` 的 `severity: high` warning

### Net Weight / Gross Weight

1. `PO.N/W` / `PO.G/W`
2. `PO` 列为空 → 回退到 `DB.N/W` / `DB.G/W`（DATA BASE 产品）
3. 两者都为 `None` → PL 构建时报 `PACKING_DATA_MISSING` 阻断

### CBM

1. `PO.TOTAL CBM`（直接读取）
2. 缓存值为 `None` → **公式回退**：`L × W × H ÷ 1,000,000 × CTNS`（L/W/H 来自 `DB.L`/`DB.W`/`DB.H`，CTNS 来自上述回退值）
3. 产生 `FORMULA_FALLBACK` warning

---

## 月度切片逻辑

仅 Invoice 和 PL 受 `invoice_month` 影响。

```
request.invoice_month = "2601"
  ↓
_resolve_priced_lines() → _slice_by_month()
  ↓
取每行 monthly_shipments["2601"] 的值作为该行 quantity
  ↓
该月出货量为 0 或 key 不存在 → 该行从 DocumnetModel 中剔除
  ↓
所有行都被剔除 → NO_SHIPMENT_IN_MONTH 阻断
```

PI 和 PO **永远使用完整 PO 数量**（`PO.FINALQTY`），不受 invoice_month 影响。

---

## 校验规则速查

### 阻断错误（blocking_error）

| Code | 触发条件 | 影响单据 |
|---|---|---|
| `SHEET_MISSING` | `DATA BASE` 或 `PO record` sheet 不存在 | 全部 |
| `HEADER_MISSING` | 必需表头缺失 | 全部 |
| `PO_NOT_FOUND` | PO 号在 PO record 中找不到 | 全部 |
| `SAP_MISSING` | PO 行缺少 SAP Number | 全部 |
| `SAP_NOT_IN_DATA_BASE` | SAP 号在 DATA BASE 中找不到 | 全部 |
| `QTY_MISSING` / `QTY_INVALID` | FINALQTY 为空或非数字 | 全部 |
| `NO_PRICES` | 该行在所有链段下均无单价 | 全部 |
| `LINE_NOT_PRICED` | 某行在当前链段下无单价 | 全部 |
| `INVOICE_NO_MISSING` | INV# 为空 | Invoice / PL |
| `FACTORY_DOC_NO_MISSING` | FACTORY DOC NO. 为空 | Invoice / PL |
| `PACKING_DATA_MISSING` | CTNS / N/W / G/W / CBM 任一缺失 | PL |
| `NO_SHIPMENT_IN_MONTH` | 指定月份无出货数据 | Invoice / PL |
| `MAPPING_NOT_FOUND` | 找不到对应模板 mapping | 全部 |

### 警告（warning）

| Code | severity | 触发条件 |
|---|---|---|
| `FORMULA_FALLBACK` | high | CTNS / TOTAL CBM 缓存值缺失，工作台按公式现算 |
| `PRICE_NOT_DECIMAL` | high | 单价列值不是有效数字 |
| — | low | `RFID`、`SUB-CATEGORY`、可选日期字段为空 |

### 需补充信息（missing_inputs）

| Key | 触发条件 |
|---|---|
| `invoice_month` | 请求 Invoice/PL 但未指定月份，且 PO 在多个月有出货 |
| `invoice_no` | 同一 `(po, invoice_month)` 存在多个不同的 INV# |
| `seller` / `buyer` | 未指定链段且 PO 数据匹配多个合法链段 |
