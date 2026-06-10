# 统一字段映射与配置指南

> 本文档是当前仓库唯一的字段映射权威文档，用于替代已删除的旧映射文档。
>
> 目标：
>
> - 解释 `base` 数据如何进入领域模型、单据模型、预览与模板
> - 说明四类单据 `PI / PO / Invoice / PL` 的字段口径差异
> - 说明当前预览配置规范：`header_fixed`、`terms_fields`、`static_terms`
> - 提供“字段值不正确时该改哪一层”的决策规则，供开发者和 Agent 直接使用

## 1. 适用范围

本文档覆盖以下内容：

- `templates/base_schema.yaml` 中的 base 结构映射
- `DATA BASE`、`PO record`、`客户PO` 三张 sheet 的定位
- `resolver.py` 如何把原始行转换为 `Product` / `OrderLine`
- `document_model.py` 如何把 `OrderLine` 投影成 `DocumentModel` / `DocumentLine`
- `document_preview.py` 如何构建预览字段
- `renderer.py` 如何把字段写入模板单元格
- 模板 YAML 中 `header`、`header_fixed`、`lines`、`totals`、`preview_content` 的职责边界

本文档不覆盖：

- 前端 UI 的交互细节
- 启动器、HTTP 路由、会话管理
- 与字段来源无关的样式细节

## 2. 总体数据链路

字段在系统中的主链路如下：

```text
base workbook
  ├─ DATA BASE
  ├─ PO record
  └─ 客户PO
      ↓
templates/base_schema.yaml
      ↓
WorkbookReader / validator
      ↓
resolver.py
  ├─ Product
  └─ OrderLine
      ↓
document_model.py  ← line_rules.py / header_rules.py（字段来源分派）
  ├─ DocumentModel
  └─ DocumentLine
      ↓
  ├─ document_preview.py  -> 预览 JSON
  └─ renderer.py         -> Excel 模板单元格
```

一句话记忆：

- `base_schema` 解决”从哪张表、哪一列读”
- `resolver` 解决”base 里有什么”
- `line_rules` / `header_rules` 解决”同一字段在不同单据/主体下来源是否不同”
- `document_model` 解决”这张单据该显示什么”
- `document_preview` / `renderer` 解决”怎么展示”

## 3. 三张 Base Sheet 的定位

| Sheet | 角色 | 当前主要用途 |
| --- | --- | --- |
| `DATA BASE` | 产品主数据 | 提供产品描述、GS Model、包装物流字段、价格基线 |
| `PO record` | 订单与出货事实数据 | 提供 PO 行、数量、价格、INV#、装箱字段、发货数量 |
| `客户PO` | 客户侧补充数据 | 当前主要用于工作台查询与部分预览/来源覆盖说明 |

### 3.1 `DATA BASE`

核心字段示例：

- `SAP`
- `Material Description`
- `Category`
- `GS MODEL`
- `round value`
- `N/W` / `G/W`
- `L` / `W` / `H` / `CBM`

用途：

- 构建 `Product`
- 在 `PO record` 缺值时提供回退值
- 为不同链段和品类提供价格来源

### 3.2 `PO record`

核心字段示例：

- `PO NO.`
- `ITEM LINE#`
- `SAP Number`
- `DESCRIPTION`
- `FINALQTY`
- `INV#`
- `SHIP QTY`
- `CTNS`
- `N/W` / `G/W`
- `TOTAL CBM`

用途：

- 构建 `OrderLine`
- 提供订单行数量、发票号、出货数量、装箱信息
- 作为四类单据的主要事实来源

### 3.3 `客户PO`

核心字段示例：

- `Purchasing Document`
- `Material`

当前定位：

- 必需 sheet 之一
- 用于工作台查询、快照和部分来源覆盖说明
- 目前尚未像 `DATA BASE` / `PO record` 一样直接进入导出主链的大部分字段装配

## 4. 领域模型与单据模型

### 4.1 `Product`

`Product` 表示 `DATA BASE` 中的一行主数据，主要承载：

- 产品标识：`sap`
- 描述与分类：`description`、`category`
- 包装物流：`carton_qty`、`net_weight`、`gross_weight`、`cbm`
- 价格表：`prices`

### 4.2 `OrderLine`

`OrderLine` 表示 `PO record` 中的一行，并已经 join 上对应 `Product`，必要时再补充
`客户PO` 的同 PO 辅助字段。

它承载：

- 订单事实：`po_no`、`item_line_no`、`sap`
- 数量事实：`quantity`、`ship_qty`
- 发票与出货：`invoice_no`
- 客户侧补充字段：`ship_to`
- 装箱物流：`carton_count`、`net_weight`、`gross_weight`、`total_cbm`
- 当前行价格快照：`prices[(seller, buyer)]`

### 4.3 `DocumentLine`

`DocumentLine` 是“当前单据视角下的一行”。  
同一个 `OrderLine`，在不同单据里会投影成不同的 `DocumentLine`。

例如：

- PI / PO 使用完整 `quantity`
- Invoice / PL 使用 `ship_qty`
- 金额由 `quantity * unit_price` 现算

### 4.4 `DocumentModel`

`DocumentModel` 是整张单据的视图模型，包含：

- 单据头字段：`po_no`、`pi_no`、`invoice_no`、`ship_to`、`ex_factory_date`
- 明细行：`lines`
- 合计：`total_quantity`、`total_amount` 等

## 5. 四类单据口径差异

| 字段 | PI | PO | Invoice | PL |
| --- | --- | --- | --- | --- |
| 行过滤 | 全部行 | 全部行 | 按 `invoice_no` 过滤 | 按 `invoice_no` 过滤 |
| 数量来源 | `FINALQTY` | `FINALQTY` | `SHIP QTY` | `SHIP QTY` |
| 单价来源 | 当前链段价格 | 当前链段价格 | 当前链段价格 | 当前链段价格 |
| 金额 | `quantity * unit_price` | `quantity * unit_price` | `quantity * unit_price` | `quantity * unit_price` |
| 装箱字段 | 否 | 否 | 否 | 是 |
| `pi_no` | 是 | 否 | 否 | 否 |
| `invoice_no` | 否 | 否 | 是 | 是 |

### 5.1 数量规则

- `PI / PO` 始终使用完整订单数量 `FINALQTY`
- `Invoice / PL` 使用当前 `INV#` 对应的 `SHIP QTY`

### 5.2 单价规则

单价不是模板自己从 Excel 某列直接读取，而是：

1. `resolver` 从 base 里收集价格列
2. 形成 `OrderLine.prices[(seller, buyer)]`
3. `document_model` 再按当前链段选出 `unit_price`

### 5.3 金额规则

金额不直接取 base 列，而是统一现算：

```text
amount = quantity * unit_price
```

### 5.4 Packing List 额外字段

仅 `PL` 会投影这些字段：

- `carton_count`
- `net_weight`
- `gross_weight`
- `cbm`

## 6. 价格、数量、装箱的关键业务规则

### 6.1 价格链段

| 链段 `(seller -> buyer)` | 价格语义 |
| --- | --- |
| `SK / YM -> GS PTE` | 第一段链路价格 |
| `GS PTE -> EMAX PTE` | 第二段链路价格 |
| `EMAX PTE -> PF` | 第三段链路价格 |

### 6.2 数量口径

- PI / PO：完整订单量
- Invoice / PL：发票对应出货量

### 6.3 装箱回退

装箱字段通常以 `PO record` 为主，必要时回退到 `DATA BASE` 或公式现算：

- `CTNS` 缺失时可由当前数量口径 / 外箱回退（当前实现取 `客户PO.Order Quantity`）
- `TOTAL CBM` 缺失时可按尺寸与箱数回退
- `N/W` / `G/W` 可回退到 `DATA BASE`

## 7. 模板 YAML 结构说明

当前模板 mapping 的核心区块如下：

```yaml
header:
header_fixed:
lines:
totals:
preview_content:
```

### 7.1 `header`

职责：

- 只定义“字段写到哪个单元格”

示例：

```yaml
header:
  invoice_no: H6
  invoice_date: H7
  ship_to: G10
```

含义：

- `invoice_no` 写到 `H6`
- `invoice_date` 写到 `H7`

### 7.2 `header_fixed`

职责：

- 定义“这些 header 字段是固定文案，值由 YAML 明确给出”

适用场景：

- 字段在 `header` 中有明确单元格
- 该字段不是从 `DocumentModel` 动态取值，而是模板/主体固定值

示例：

```yaml
header_fixed:
  payment_terms: Net 90 days
  port_of_loading: Guangdong, China
  final_destination: USA
```

规则：

- 只有已经属于 header 语义、并且在模板上有明确位置的固定文案，才应放在这里

### 7.2.1 系统生成的 header 日期字段

有一类 header 字段虽然写在 mapping YAML 的 `header` 里，但它们的值并不来自
`DATA BASE`、`PO record` 或 `客户PO`，而是由系统在预览或导出时自动生成。

当前最典型的是：

- `document_date`
- `invoice_date`
- `signature_date`

规则：

- mapping YAML 的 `header` 只定义它们写到哪个单元格
- 这些字段不是 `header_fixed`
- 这些字段也不是 `base_schema.yaml` 或 `resolver.py` 的取数字段
- 当前实现里，它们的值来自程序运行当天日期

示例：

```yaml
header:
  document_date: G6
  invoice_date: H7
```

含义：

- `document_date: G6` 表示“把文档日期写到 `G6`”
- 但不表示“值来自 base 的某一列”

当前实现来源：

- 预览层：`document_preview.py` 会把 `document_date`、`invoice_date`、
  `signature_date` 解析为当天日期
- 导出层：`renderer.py` 会把 `document_date`、`invoice_date`、
  `signature_date` 写成当天日期字符串

边界说明：

- 如果你想改的是**位置**，改 mapping YAML 的 `header`
- 如果你想改的是**日期格式**或**日期来源规则**，改
  `document_preview.py` 和 `renderer.py`
- 不要去改 `base_schema.yaml`、`resolver.py` 或 `document_model.py`
  试图为 `document_date` 找 base 来源

补充说明：

- `ex_factory_date` 容易和这类字段混淆，但它**不属于系统自动生成日期**
- `ex_factory_date` 当前规则来自 `客户PO` 的 `ship DATE`
- `document_model.py` 会把当前单据行中的首个非空
  `confirmed_ex_factory_date` 汇总到 header 级字段 `ex_factory_date`
- 预览层和导出层都复用这个 header 字段，不再把它标成“人工填写”
- 明细行里的 `confirmed_ex_factory_date` 与表头 `ex_factory_date` 是同一业务来源的
  两种展示形式：前者按行显示，后者用于单据头部汇总展示

### 7.3 `lines`

职责：

- 定义明细行起始行、样式参考行、可选表格表头保护行、固定列和值、以及每个字段对应的列字母

典型结构：

```yaml
table_header_row: 17
lines:
  start_row: 18
  style_source_row: 18
  row_fixed:
    G: PCS
  columns:
    po_no: B
    description: C
    sap: D
    unit_price: E
    quantity: F
    amount: H
```

其中：

- `start_row`：模板明细开始行
- `style_source_row`：明细样式参考行；既用于超行插入时复制样式，也用于把模板预留明细区统一成同一套样式
- `table_header_row`：可选；当 `start_row` 上方存在真实表格表头时显式声明，渲染时保留该行
- `row_fixed`：每一行都写入相同固定值的列
- `columns`：来自 `DocumentLine` 的业务字段列映射

边界规则：

- `style_source_row` 应指向真实明细样式行，而不是表头行或脏样板行
- 如果模板预留区某一行带了错误 `number_format`，应优先检查 `style_source_row`
- `table_header_row` 不写不会报错；但如果模板在 `start_row` 上方有真实表头，又未声明该字段，清样板时该行会被当作普通样板行清掉
- `table_header_row` 必须小于 `lines.start_row`

### 7.4 `lines.row_fixed`

职责：

- 定义“明细区某一列对每一行都写入同一个固定值”

适用场景：

- 单位列固定为 `PCS`
- 重量单位固定为 `KGS`
- 体积单位固定为 `CBM`
- 原产地列固定为 `China`

真实示例：

GS Invoice：

```yaml
lines:
  row_fixed:
    G: PCS
```

GS PL：

```yaml
lines:
  row_fixed:
    F: PCS
    H: KGS
    J: KGS
    L: CBM
```

EMAX PI：

```yaml
lines:
  row_fixed:
    A: China
```

边界规则：

- 如果值是“每一行都一样”的固定列值，优先放 `row_fixed`
- 如果值来自订单数据或单据模型，不要放 `row_fixed`，应放 `columns`
- `row_fixed` 只作用于明细区，不作用于表头
- `row_fixed` 不参与 `resolved_values`，也不属于 `header_fixed` 或 `static_terms`

与其他配置的区别：

| 配置 | 作用区域 | 适用对象 | 例子 |
| --- | --- | --- | --- |
| `header_fixed` | 表头 | 有单元格位置的固定表头字段 | `payment_terms` |
| `row_fixed` | 明细行 | 每一行都一样的固定列值 | `PCS`、`KGS`、`China` |
| `columns` | 明细行 | 来自 `DocumentLine` 的动态字段 | `quantity`、`amount` |
| `static_terms` | 预览条款区 | 仅预览展示的固定文案 | `incoterm` |

常见错误：

错误示例 1：把固定列值写进 `columns`

```yaml
columns:
  unit_label: G
```

如果这个值在所有行中都固定为 `PCS`，而不是来自 `DocumentLine.unit_label`，更适合改为：

```yaml
row_fixed:
  G: PCS
```

错误示例 2：把明细固定列误写到 `header_fixed`

```yaml
header_fixed:
  unit_label: PCS
```

问题：

- `header_fixed` 是表头固定值
- `PCS` 作为明细区每一行的单位列，应放 `row_fixed`

### 7.5 `totals`

职责：

- 定义合计字段写入的目标单元格

### 7.6 `preview_content`

职责：

- 定义预览页面中与 Excel 位置无关的展示结构

当前有效结构包括：

- `title`
- `to_label`
- `terms_fields`
- `static_terms`
- `notes`
- `column_labels`
- `seller_info`
- `layout`
- `source_overrides`

## 8. 当前预览配置规范

这是当前版本最重要的配置规则。

### 8.1 `terms_fields`

职责：

- 声明预览条款区要展示哪些“已解析字段”
- 只负责顺序，不重复保存字段值

示例：

```yaml
preview_content:
  terms_fields:
    - payment_terms
    - port_of_loading
    - final_destination
```

解释：

- 这些字段的值来自 `resolved_values`
- `resolved_values` 由 `document_preview.py` 基于 `header_fixed`、`DocumentModel` 字段、日期字段等统一生成

### 8.2 `static_terms`

职责：

- 保存仅用于预览展示、但不属于 header 字段的静态文案

示例：

```yaml
preview_content:
  static_terms:
    incoterm: FOB GUANGDONG
```

适用场景：

- 字段不在模板 header 中
- 字段只在预览条款区出现

### 8.3 `header_fixed` 与 `terms_fields` 的关系

如果某个字段：

- 在模板上有位置
- 又需要在预览条款区展示

那么正确做法是：

1. 把值放进 `header_fixed`
2. 在 `terms_fields` 中引用字段名

不要这样做：

```yaml
preview_content:
  static_terms:
    payment_terms: Net 90 days
```

如果 `payment_terms` 已经是 header 字段，这种写法会制造重复来源。

### 8.4 `row_fixed` 与预览配置的关系

- `row_fixed` 不属于预览条款系统
- `row_fixed` 的值会进入每一行预览数据，因为预览明细也是按行构建的
- 但它不会进入 `terms_fields`、`static_terms` 或 `resolved_values`

因此：

- 如果你要改预览条款区里的字段，不要去改 `row_fixed`
- 如果你要改预览表格中每一行固定展示的单位或固定列值，优先检查 `row_fixed`

### 8.5 错误示例

错误示例 1：把 header 字段重复写成静态预览条款

```yaml
header_fixed:
  payment_terms: Net 90 days
preview_content:
  static_terms:
    payment_terms: Net 90 days
```

问题：

- 同一字段双写
- 预览和导出容易漂移

错误示例 2：把纯预览字段强行塞进 `header_fixed`

```yaml
header_fixed:
  incoterm: FOB GUANGDONG
```

问题：

- 如果模板 header 没有 `incoterm` 位置，这个字段就不属于 `header_fixed`

正确做法：

```yaml
preview_content:
  static_terms:
    incoterm: FOB GUANGDONG
```

### 8.6 完整 YAML 结构规范与示例模板

这一节用于回答一个实际维护问题：

- 当你要新增一份 mapping
- 或者要按当前能力改造旧 mapping
- 不应该直接机械复制某一份真实业务 YAML

原因：

- 真实业务 YAML 往往混合了主体专属、单据专属和模板专属细节
- 直接复制容易把“示例细节”误当成“结构规范”
- 当前已经引入 `table_header_row`、增强版 `totals`、`style_source_row` 新语义，单靠口口相传不够稳

推荐做法：

1. 先读这一节，明确字段职责和边界
2. 新增 mapping 时优先从最小骨架示例开始
3. 需要复杂 PI 布局、增强 totals、显式表头保护时，再参考完整 PI 示例
4. 最后再按真实模板修改单元格地址、列字母和预览布局

示例文件位置：

- `templates/_examples/mapping-template.minimal.yaml`
- `templates/_examples/mapping-template.pi.full.yaml`

注意：

- 这两个文件是示例资产，不参与真实装配流程
- 它们用于指导写法，不是可直接投产的生产配置
- 尤其是完整 PI 示例，不能被当成所有主体和所有单据的统一母版

#### 8.6.1 推荐顶层结构

```yaml
document: invoice
template_version: "2026.06"
template: templates/<entity>/<doc>.xlsx
sheet: Sheet1

header:
  invoice_no: H6
  ship_to: A12

header_fixed:
  payment_terms: Net 90 days

table_header_row: 17

lines:
  start_row: 18
  style_source_row: 18
  row_fixed:
    G: PCS
  columns:
    description: C
    unit_price: E
    quantity: F
    amount: H

totals:
  amount: H27

style:
  bold:
    - A1

preview_content:
  title: COMMERCIAL INVOICE
  static_terms:
    incoterm: FOB GUANGDONG
  notes: []
  column_labels:
    description: DESCRIPTION
    unit_price: UNIT PRICE
    quantity: QTY
    amount: AMOUNT
  seller_info:
    - DEMO SELLER
  layout:
    top:
      left: [seller_info]
      center: [title]
      right: []
    info:
      left: [ship_to]
      right: [invoice_no, terms]
```

#### 8.6.2 顶层字段职责

| 字段 | 必填 | 作用 | 是否影响 Excel 导出 | 是否影响预览 |
| --- | --- | --- | --- | --- |
| `document` | 是 | 声明单据类型，如 `pi` / `po` / `invoice` / `pl` | 是 | 是 |
| `template_version` | 是 | 标识当前 mapping 版本 | 间接影响 | 间接影响 |
| `template` | 是 | 模板文件路径 | 是 | 间接影响 |
| `sheet` | 是 | 目标工作表名称 | 是 | 间接影响 |
| `header` | 视模板而定 | 表头字段与单元格位置映射 | 是 | 是 |
| `header_fixed` | 否 | 固定表头值 | 是 | 是 |
| `table_header_row` | 否 | 显式保护 `start_row` 上方的真实表格表头 | 是 | 否 |
| `lines` | 是 | 定义明细区结构和列映射 | 是 | 是 |
| `totals` | 否 | 定义 footer / 合计 / 签名类单元格 | 是 | 是 |
| `style` | 否 | 声明需要强化的样式单元格 | 是 | 否 |
| `preview_content` | 否 | 定义与模板坐标无关的预览结构 | 否 | 是 |

#### 8.6.3 `header`、`header_fixed`、`preview_content` 的边界

- `header`：定义“哪个表头字段写到哪个单元格”
- `header_fixed`：定义“这个表头字段的值是固定文案，不来自模型”
- `preview_content`：定义“预览页面怎么组织内容”，不负责 Excel 单元格坐标

判断口诀：

- 模板里有单元格位置：优先看 `header`
- 值固定不变，且模板里有位置：优先看 `header_fixed`
- 只在预览里展示，不落 Excel：优先看 `preview_content.static_terms`

#### 8.6.4 `table_header_row` 与 `lines` 的边界

- `table_header_row` 是顶层字段，不在 `lines` 内部
- 它的作用是：显式保护 `start_row` 上方的真实表格表头
- `table_header_row` 不写不会报错
- 但如果模板确实有真实表头行，又不写这个字段，清样板时该行可能被当成普通样板行清掉

必须满足：

- `table_header_row < lines.start_row`

不要误解为：

- “有 `style_source_row` 就不需要 `table_header_row`”
- 这两个字段职责不同，前者管样式来源，后者管表头保护

#### 8.6.5 `style_source_row` 的当前语义

`style_source_row` 当前不只用于“超出模板预留区时新增插入行复制样式”，还用于：

- 在写值前统一预留明细区样式
- 抵消模板中脏 `number_format`
- 保证预留行与新增插入行的格式口径一致

因此：

- 它必须指向真实明细样式行
- 不能指向表头行
- 也不应指向带错误格式的旧样板行

如果导出最后一行格式错了，比如单价显示成日期，优先检查：

1. `lines.style_source_row`
2. 模板预留区是否存在脏样式

#### 8.6.6 `totals` 的推荐写法

当前支持两种写法。

旧写法：

```yaml
totals:
  amount: H27
```

适用于：

- 只有目标单元格
- 值直接来自标准 totals 模型字段

增强写法：

```yaml
totals:
  amount: G24
  signature:
    cell: G26
    value_mode: fixed
    value: Joyce
  Date:
    cell: G27
    value_mode: current_date
```

适用于：

- footer 中既有模型 totals
- 又有固定文案对应的值单元格
- 或需要填当前日期

当前 `value_mode` 语义：

| `value_mode` | 含义 | 典型场景 |
| --- | --- | --- |
| `model_total` | 使用标准 totals 模型值 | `amount`、`quantity` |
| `fixed` | 使用固定字符串 | `signature` |
| `current_date` | 使用系统当前日期 | `Date` |

#### 8.6.7 `preview_content` 的定位

`preview_content` 的核心原则是：

- 它定义的是预览结构，不是 Excel 坐标
- 改这里不会改变模板单元格位置
- 它只影响前端预览 payload 的组织方式

常见字段：

| 字段 | 作用 |
| --- | --- |
| `title` | 预览标题 |
| `to_label` | 预览顶部标签文案 |
| `terms_fields` | 引用已解析字段，并控制条款顺序 |
| `static_terms` | 仅预览展示的静态条款 |
| `notes` | 预览备注 |
| `column_labels` | 预览表头标签 |
| `seller_info` | 预览左上角主体信息 |
| `layout` | 预览分区布局 |
| `source_overrides` | 来源展示覆盖说明 |

#### 8.6.8 最小骨架示例与完整示例的使用顺序

最小骨架示例适合：

- 新增一份 mapping
- 从零开始搭结构
- 先把顶层区块搭出来，再填真实地址

完整 PI 示例适合：

- 需要参考复杂表头
- 需要参考 `table_header_row`
- 需要参考增强版 `totals`
- 需要参考完整 `preview_content.layout`

不要这样做：

- 直接复制完整 PI 示例，随后只改 `document`
- 直接把完整 PI 示例用于 `PO`、`Invoice`、`PL`
- 直接把示例中的 `seller_info`、`header_fixed`、`column_labels` 当作所有主体通用值

#### 8.6.9 推荐新增 mapping 流程

```text
确定单据类型
  ↓
复制 templates/_examples/mapping-template.minimal.yaml
  ↓
填 document / template / sheet / header / lines / totals
  ↓
如果模板在 start_row 上方有真实表头，补 table_header_row
  ↓
如果 footer 有固定值或日期值，改用增强版 totals 写法
  ↓
如果需要复杂预览结构，再参考 mapping-template.pi.full.yaml
  ↓
最后用真实模板校验所有单元格引用
```

#### 8.6.10 高风险误用清单

高风险误用 1：把完整示例当作统一母版

- 后果：主体信息、条款、表头字段、布局全部串错

高风险误用 2：把预览字段写进 `header_fixed`

- 后果：预览与导出职责混淆

高风险误用 3：把固定列值写进 `columns`

- 后果：把常量伪装成动态字段

高风险误用 4：不声明 `table_header_row`

- 后果：真实表头可能在清样板时被清掉

高风险误用 5：`style_source_row` 指向脏样式行

- 后果：最后一行或新增行的数字格式错乱

## 9. 字段来源映射总规则

### 9.1 先问“这个字段属于哪一类”

字段通常可分为 5 类：

| 类型 | 例子 | 主修改层 |
| --- | --- | --- |
| base 来源字段 | `SAP`、`FINALQTY`、`INV#` | `base_schema.yaml` / `resolver.py` |
| 单据口径字段 | `quantity`、`amount` | `document_model.py` |
| 模板位置字段 | `invoice_no -> H6` | mapping YAML |
| 系统生成字段 | `document_date`、`invoice_date`、`signature_date` | `document_preview.py` / `renderer.py` |
| Base 来源的表头字段 | `ex_factory_date` | `document_model.py` / `document_preview.py` / `renderer.py` |
| header 固定字段 | `payment_terms`、`final_destination` | `header_fixed` |
| 明细固定列字段 | `PCS`、`KGS`、`China` | `lines.row_fixed` |
| 纯预览字段 | `incoterm` | `preview_content.static_terms` |

### 9.2 字段错误时的判断顺序

```text
先看值是不是错
  ├─ 值对，位置错 -> 改 mapping YAML
  └─ 值错
      ├─ 来源列错 -> 改 base_schema.yaml
      ├─ 取值/回退错 -> 改 resolver.py
      ├─ 单据口径错 -> 改 document_model.py
      ├─ 主体/单据类型差异导致来源不同 -> 改 line_rules.py / header_rules.py
      ├─ 预览条款错 -> 改 header_fixed / terms_fields / static_terms
      └─ 模型值对、渲染错 -> 改 renderer.py 或 document_preview.py
```

### 9.3 字段来源的三层分派机制

`line_rules.py` 和 `header_rules.py` 实现了一套三层分派，决定"同一字段在不同上下文下取哪里的值"：

| 层级 | 数据结构 | 覆盖范围 | 典型例子 |
| --- | --- | --- | --- |
| 默认规则 | `get_line_field_spec()` / `HEADER_FIELD_SPECS` | 全部单据、全部主体 | `quantity` 来自 `FINALQTY` |
| 单据族覆盖 | `_DOC_FAMILY_OVERRIDES` | Invoice 或 PL 与 PI/PO 的来源差异 | Invoice/PL 的 `quantity` 改取 `SHIP QTY`；`description` 改取 PO record 的 `DESCRIPTION`；PL 的 `cbm` 改取 `TOTAL CBM` |
| 主体专属覆盖 | `_SELLER_LINE_OVERRIDES` / `_HEADER_SELLER_OVERRIDES` | 特定 seller 集合 | SK/YM/GS 的 `confirmed_ex_factory_date` 和 `ex_factory_date` 取 `FINAL EX-FACTORY DATE`；GS PTE 的 `pi_no` 取 `Purchasing Document` |

**架构纪律**：

- 字段来源的主体差异只写在 `_SELLER_LINE_OVERRIDES` / `_HEADER_SELLER_OVERRIDES` 里。
- `document_preview.py` 和 `renderer.py` **禁止**出现 `if seller == ...` 这类分派判断。
- 新增主体专属来源规则：在对应的 `_*_OVERRIDES` 数据字典中加 entry，key 用 `frozenset` 包住 seller 名称集合。

## 10. Agent 修改代码决策表

| 现象 | 根因类型 | 优先修改层 |
| --- | --- | --- |
| 模板里字段写到了错误单元格 | 位置映射错 | 对应 mapping YAML |
| 每一行的固定单位/原产地显示错了 | 明细固定列错 | `lines.row_fixed` |
| 字段取了错误的 base 列 | schema 映射错 | `templates/base_schema.yaml` |
| 描述、重量、箱数回退逻辑错 | resolver 逻辑错 | `resolver.py` |
| Invoice 数量用了 `FINALQTY` 而不是 `SHIP QTY` | 单据口径错 | `document_model.py` |
| `Document Date` / `Invoice Date` 显示错、格式错或来源规则要改 | 系统生成字段规则错 | `document_preview.py` / `renderer.py` |
| `EX-FACTORY DATE` 被当成系统生成、人工填写或模板固定文本 | header 来源标注错 | `document_model.py` / `header_rules.py` |
| 某字段在特定主体下来源错（如 GS 的 `pi_no` 应取 `Purchasing Document`） | 主体专属来源规则缺失或错误 | `header_rules.py` 的 `_HEADER_SELLER_OVERRIDES` |
| Invoice/PL 的字段来源与 PI/PO 不一致（如 `quantity` 来源错） | 单据族来源规则错 | `line_rules.py` 的 `_DOC_FAMILY_OVERRIDES` |
| 预览里条款值不对，但 Excel 正常 | 预览配置错 | `header_fixed` / `terms_fields` / `static_terms` |
| 预览里字段顺序不对 | 预览布局错 | `preview_content.layout` / `terms_fields` |
| Excel 和预览都错，但模型值对 | 渲染/预览层错 | `renderer.py` / `document_preview.py` |

## 11. 四类常见修改场景

### 11.1 修改固定表头文案

例子：

- `payment_terms`
- `port_of_loading`
- `final_destination`

处理方式：

- 如果字段在模板 header 中有对应单元格，改 `header_fixed`
- 如果预览需要显示，确保 `terms_fields` 引用了它

### 11.2 修改纯预览条款

例子：

- `incoterm`

处理方式：

- 改 `preview_content.static_terms`
- 不要放进 `header_fixed`，除非模板上已经新增了对应单元格

### 11.3 修改明细固定列

例子：

- 单位列 `PCS`
- 重量单位 `KGS`
- 原产地 `China`

处理方式：

- 如果该值在每一行都相同，优先改 `lines.row_fixed`
- 不要误改 `header_fixed`
- 不要误改 `static_terms`
- 也不要把这类常量错误归因到 `resolver.py`

### 11.4 修改字段数据来源

例子：

- `ship_to` 原先来自 `PO record`，现在要改成来自 `客户PO`

处理方式：

- 先判断这是：
  - 结构变更
  - 业务规则变更
- 通常会涉及：
  - `resolver.py`
  - 如有表头名变化，再补 `base_schema.yaml`
  - 必要时 `document_model.py`

### 11.5 修改 Invoice / PL 的数量逻辑

处理方式：

- 不改模板
- 不改 `header_fixed`
- 直接改 `document_model.py`

## 12. 推荐人工排查流程

当发现“模板某字段不正确”时，建议按下面顺序排查：

1. 在最终 Excel 或预览里确认哪个字段有问题
2. 判断是“值错”还是“位置错”
3. 查该字段属于哪一类：
   - base 来源
   - 单据口径
   - header 固定文案
   - 纯预览字段
4. 顺着链路向前追：
   - `mapping YAML`
   - `document_preview.py` / `renderer.py`
   - `document_model.py`
   - `resolver.py`
   - `base_schema.yaml`
5. 修改最靠近根因的那一层，而不是在下游做掩盖式修复

## 13. 高风险字段清单

这些字段最容易因为语义复杂或跨层而出错：

- `quantity`
- `unit_price`
- `amount`
- `invoice_no`
- `ship_to`
- `payment_terms`
- `port_of_loading`
- `final_destination`
- `incoterm`
- `PCS`
- `KGS`
- `China`
- `carton_count`
- `net_weight`
- `gross_weight`
- `cbm`

## 14. 推荐维护规则

为避免再次出现冗余和晦涩性，后续请遵守以下规则：

- 同一语义字段只保留一个权威值来源
- `header_fixed` 只承载真正属于 header 的固定字段
- `terms_fields` 只声明顺序，不重复声明值
- `static_terms` 只承载纯预览字段
- 模板位置变更只改 YAML，不在代码里硬编码单元格
- 业务口径变更优先改 `resolver.py` 或 `document_model.py`
- 字段来源变更先判断是“列名变化”还是“业务语义变化”

## 15. 与其他文档的关系

本文档是当前唯一的字段映射主文档。

建议理解方式：

- 如果你要判断“字段为什么这样取”，看本文档
- 如果你要判断“代码在哪一层实现这个规则”，也看本文档
- 如果你要让 Agent 按标准步骤修复字段问题，参考 [Agent 字段修复操作手册](./agent-field-fix-playbook.md)
- 如果你想先找相似问题的现成处理方法，参考 [字段修复案例库](./field-fix-case-library.md)
- 如果你要做更细粒度的产品交互设计，参考 UI 设计文档
- 如果你要看工程分期和实施背景，参考实施指南

后续如果字段结构、预览配置或单据口径发生变化，应优先更新本文档，而不是再新增并行映射文档。

## 16. Agent 速查表

这一节用于给 Agent 或开发者快速判断“字段属于哪一类，应优先修改哪个文件”。

### 16.1 字段类型到修改层速查

| 字段类型 | 典型字段 | 首选修改位置 | 说明 |
| --- | --- | --- | --- |
| Base 列映射 | `SAP`、`FINALQTY`、`INV#` | `templates/base_schema.yaml` | 当 Excel 表头变了，但业务语义没变 |
| Base 取值/回退逻辑 | `description`、`net_weight`、`gross_weight`、`carton_count` | `resolver.py` | 当字段来源、回退优先级或现算规则有误 |
| 单据口径逻辑 | `quantity`、`amount`、`invoice_no` 过滤 | `document_model.py` | 当不同单据类型的取值口径不正确 |
| 表头位置 | `invoice_no -> H6`、`ship_to -> G10` | 对应 mapping YAML 的 `header` | 值对但单元格错 |
| 系统生成日期字段 | `document_date`、`invoice_date`、`signature_date` | `document_preview.py` / `renderer.py` | 这些字段通常取当前日期，不来自 base |
| Base 来源的表头字段 | `ex_factory_date` | `header_rules.py` / `document_model.py` | 来源规则在 `header_rules.py`；SK/YM/GS 主体有专属覆盖 |
| 主体专属 header 来源字段 | `ex_factory_date`（SK/YM/GS 取 `FINAL EX-FACTORY DATE`）、`pi_no`（GS 取 `Purchasing Document`） | `header_rules.py` 的 `_HEADER_SELLER_OVERRIDES` | 不在此修改 `document_preview.py` |
| 单据族差异化明细来源 | Invoice/PL 的 `quantity`（`SHIP QTY`）、`description`（`DESCRIPTION`）；PL 的 `cbm`（`TOTAL CBM`） | `line_rules.py` 的 `_DOC_FAMILY_OVERRIDES` | 不在 `document_model.py` 里写 if 分支 |
| 表头固定文案 | `payment_terms`、`port_of_loading`、`final_destination` | 对应 mapping YAML 的 `header_fixed` | 字段有 header 单元格，且文案固定 |
| 明细固定列 | `PCS`、`KGS`、`CBM`、`China` | 对应 mapping YAML 的 `lines.row_fixed` | 每一行都一样的固定值 |
| 明细动态列 | `quantity`、`unit_price`、`amount` | 对应 mapping YAML 的 `lines.columns` | 列字母映射错，且字段值本身是对的 |
| 预览条款字段顺序 | `payment_terms`、`final_destination` 在 terms 区的顺序 | `preview_content.terms_fields` | 只调整顺序，不改值来源 |
| 纯预览固定文案 | `incoterm`、`term`、`from`、`to` | `preview_content.static_terms` | 只在预览里显示，不属于 header |
| 预览布局 | `title`、`seller_info`、`terms` 在哪个区域 | `preview_content.layout` | 控制预览区块分布 |
| 预览字段解析 | `resolved_values`、`terms` 生成逻辑 | `document_preview.py` | YAML 已正确但预览输出不对 |
| 明细样式参考行 | `style_source_row` | 对应 mapping YAML 的 `lines.style_source_row` | 导出最后一行格式错、单价显示成日期时优先检查 |
| 表格表头保护行 | `table_header_row` | 对应 mapping YAML 的 `table_header_row` | `start_row` 上方有真实表格表头，且导出时被清掉 |
| Excel 写入行为 | 插值、单元格写入、样式保留 | `renderer.py` | 模型值正确但导出结果不对 |

### 16.2 快速判断口诀

- 列名变了：先看 `base_schema.yaml`
- 值来源错了：先看 `resolver.py`
- 单据口径错了：先看 `document_model.py`
- 格子写错了：先看 mapping YAML
- 每行固定值错了：先看 `lines.row_fixed`
- 导出最后一行格式错了：先看 `lines.style_source_row`
- 表格表头被清掉了：先看 `table_header_row`
- 预览条款错了：先看 `header_fixed` / `terms_fields` / `static_terms`
- 预览值对不上 YAML：再看 `document_preview.py`
- Excel 导出不对但预览对：再看 `renderer.py`
- 特定主体的字段来源不对：先看 `header_rules.py` 的 `_HEADER_SELLER_OVERRIDES` 或 `line_rules.py` 的 `_SELLER_LINE_OVERRIDES`
- Invoice/PL 字段来源与 PI/PO 不一致：先看 `line_rules.py` 的 `_DOC_FAMILY_OVERRIDES`

### 16.3 两步排查法

第一步：先判断问题属于哪一类

- 值错
- 位置错
- 顺序错
- 单据口径错
- 预览错但 Excel 对
- Excel 错但预览对

第二步：按下面顺序落点

1. `base_schema.yaml`
2. `resolver.py`
3. `document_model.py`
4. mapping YAML
5. `document_preview.py`
6. `renderer.py`

## 17. Agent 标准修改模板

下面这份模板可以直接复制给 Agent，用于减少描述歧义。

### 17.1 通用模板

```text
请帮我修复一个字段映射问题。

问题字段：
- 单据类型：
- 主体 / 链段：
- 字段名：

当前现象：
- 当前值：
- 当前位置：
- 是预览错、Excel 错，还是两者都错：

期望行为：
- 期望值：
- 期望来源：
- 期望写入位置：

已知信息：
- 是否属于 header 字段：
- 是否属于每行固定列：
- 是否只在预览展示：
- 是否受单据类型口径影响：

请按以下方式处理：
1. 先分析问题原因
2. 判断应该修改哪一层：
   - `base_schema.yaml`
   - `resolver.py`
   - `document_model.py`
   - mapping YAML
   - `document_preview.py`
   - `renderer.py`
3. 只修改最靠近根因的那一层，不要做掩盖式修复
4. 如有必要，同步更新测试
5. 最后说明修改原因与影响范围
```

### 17.2 预览配置问题模板

适用于：

- `header_fixed`
- `terms_fields`
- `static_terms`
- `row_fixed`

```text
请帮我修复模板 YAML 配置问题。

文件：
- mapping 文件路径：

问题字段：
- 字段名：
- 当前配置块：
- 当前值：

期望行为：
- 应属于：
  - `header_fixed`
  - `terms_fields`
  - `static_terms`
  - `lines.row_fixed`
  - `lines.columns`
- 期望值：

请先分析问题原因，再只修改正确的配置块。
如果你发现这是架构边界问题，请明确指出原因。
```

### 17.3 字段来源问题模板

适用于：

- 字段从错误 sheet/列取值
- 回退规则错误
- 口径错误

```text
请帮我修复字段来源问题。

问题字段：
- 字段名：
- 当前来源：
- 期望来源：

问题范围：
- 影响单据：
- 影响主体：
- 影响预览 / 导出：

请按这条链路排查：
`base_schema -> resolver -> document_model -> preview/render`

要求：
1. 先分析问题原因
2. 明确根因层级
3. 只修改根因层
4. 补充必要测试
5. 输出变更摘要
```

## 18. 文档维护建议

如果后续继续扩展模板或字段，请优先增量维护本文档，而不是新增并行的映射文档。

建议维护顺序：

1. 先更新 mapping 或代码
2. 再更新本文档中的：
   - 字段类型规则
   - 决策表
   - 真实示例
   - Agent 模板
3. 最后检查是否有导航文档需要同步更新
