# 工作台票据组聚合键、预览与导出 API 设计

## 1. 目标

本文是《工作台预览页双视角设计》的配套设计稿，专门细化两件事：

- `invoice_group_key` 如何定义，才能把不同主体下属于同一业务票据的实际出货行聚合成同一票据组
- `Invoice 视角` 的预览与导出 API 应如何设计，才能与 `PO 视角` 解耦

本文解决“票据组如何识别”以及“预览、导出接口如何承载票据组”。这里的“票据组”不是单纯的发票号字符串，而是“发票身份 + `SHIP QTY > 0` 的可装配源行”的组合。

## 2. 背景

上一份设计文档已确认：

- 预览页采用 `PO 视角 / Invoice 视角` 双视角切换
- `Invoice 视角` 左侧列表一行对应一个票据组
- 页面主文本统一显示 `Invoice 号`
- 同一业务票据在不同主体下视为同一票据组

但要真正落地，还必须解决一个关键问题：

- 当前不同主体看到的“发票号”来源并不完全相同
- API 也仍然严格绑定 `po_no`
- Invoice / PL 的数量来自 `PO record.SHIP QTY`，而不是完整 `PO` 数量

如果不先设计好统一聚合键，前端即使做出 `Invoice 视角` 外壳，也无法稳定加载票据组列表和预览内容。

## 3. 当前现状

### 3.1 不同主体的发票号来源

当前代码里，用户可见的 `Invoice / PL` 发票号并非统一来自同一个原始字段：

- `GS PTE`
  - 使用 `PO record.INV#`
- `EMAX PTE`
  - 对外显示使用 `PO record.INV# + "-P"`
- `SK`
  - 使用 `PO record.SK/YM INVOICE NO.`
- `YM`
  - 使用 `PO record.SK/YM INVOICE NO.`

现状证据：

- `invoice_no_for_line()` 已按主体和单据上下文做分流
- `EMAX PTE` 追加 `-P`
- `SK / YM` 使用 `SK/YM INVOICE NO.`

因此，“页面统一显示 `Invoice 号`”与“底层发票号来源不一致”是同时成立的。

### 3.2 当前预览接口的限制

当前预览接口只有 `PO` 维度：

- `POST /api/po/{po_no}/preview`

核心预览逻辑也只会：

1. 从 snapshot 里取某一个 `po_no` 的行
2. 在该 `PO` 内部再筛选 seller 和 invoice
3. 构建单个单据的预览

这套接口语义不适合 `Invoice 视角`，因为：

- `Invoice 视角` 对象应是票据组，而不是单个 `PO`
- 一个票据组可能覆盖多个 `PO`

## 4. 设计原则

### 4.1 页面显示与底层主键分离

- 页面上继续统一叫“`Invoice 号`”
- 底层引入 `invoice_group_key`
- `invoice_group_key` 是内部稳定主键，不要求与某一个原始字段完全相同

### 4.2 左侧列表只选票据组，不选主体

- 左侧列表项主键必须是票据组
- 主体切换保留在右侧
- 同一票据组在不同主体下的可见发票号差异，通过“主体上下文”解决，不通过左侧重复列表项解决

### 4.3 票据组归并规则必须写在核心包

- 不允许前端通过拼接字段或临时比对把多个发票号归并成一组
- API 层也不应写业务归并判断
- 票据组构建规则必须沉淀在 `ro_generator` 核心包里

### 4.4 票据组成员行使用 `SHIP QTY`

- 票据组身份只由同行共现的原始发票标识集合决定，不增加月份或虚拟出货范围
- `Invoice / PL` 的业务对象是某个发票身份下 `SHIP QTY > 0` 的源行集合
- `SHIP QTY` 为空或为 0 的行不进入票据组，也不进入 Invoice / PL 预览和导出
- 当前源数据没有独立批次字段；同一组发票标识再次出现时视为同一票据组
- 如果未来必须区分同一发票号下的多个批次，应先在源数据增加真实批次字段，再扩展聚合键，不能根据月份、行号或加载时间推断

### 4.5 API 必须继续受 session 约束

- `base_file` 只在 `/api/session/open` 阶段由前端提交
- 后续票据组列表、预览、导出都应通过 `X-Session-Id` 或 session 路径获取上下文
- 不新增绕过 session 的 `?base_file=...` 访问路径

这样可以复用当前工作台的缓存失效、临时目录、下载权限和 session TTL 规则。

## 5. 票据组模型

新增独立数据模型，用于 `Invoice 视角` 的左侧列表与预览入口：

```ts
interface InvoiceInspection {
  invoice_group_key: string;
  display_invoice_no: string;
  status: "ready" | "partial" | "blocked" | "done";
  po_nos: string[];
  po_count: number;
  sellers: string[];
  seller_invoice_numbers: Record<string, string>;
  blocking_count: number;
  conflict_count: number;
}
```

字段说明：

- `invoice_group_key`
  - 内部稳定主键
  - 用于 API 查询、前端选中、缓存索引
- `display_invoice_no`
  - 左侧列表和右侧标题使用的统一展示值
- `po_nos`
  - 当前票据组覆盖的 `PO` 集合
- `seller_invoice_numbers`
  - 当前票据组在各主体下的实际显示发票号
  - 例如：
    - `GS PTE -> INV-001`
    - `EMAX PTE -> INV-001-P`
    - `SK -> SKYM-2026-001`

## 6. invoice_group_key 设计

### 6.1 为什么不能直接用一个字段

不能简单把 `invoice_group_key` 直接定义成：

- `INV#`
- 或 `SK/YM INVOICE NO.`
- 或“当前主体的发票号”

原因：

- `EMAX PTE` 对外展示值与原始 `INV#` 还差一个 `-P`
- `SK / YM` 与 `GS / EMAX` 的显示号码可能完全不同
- 同一业务票据跨主体应视为同一票据组，说明聚合键不能直接等于任一单主体显示值

### 6.2 固定方案：基于同行共现关系构建票据组

票据组构建逻辑建立在“同一源行里共同出现的发票标识属于同一业务票据”这一事实上。

对于每一条 `PO record` 解析后的 `OrderLine`，提取该行可见的票据标识：

- `raw_inv`
  - `line.invoice_no`
- `emax_visible_inv`
  - `line.invoice_no + "-P"`，仅对 `EMAX PTE` 视角有效
- `factory_inv`
  - `line.sk_ym_invoice_no`

然后按以下规则构建票据组：

1. 遍历所有解析后的 `OrderLine`，先跳过 `SHIP QTY` 为空或小于等于 0 的行
2. 对每一条保留行，把该行上出现的非空发票标识视为“共现标识”
3. 任何在同一行共现的标识，视为属于同一个业务票据组
4. 通过并查集或等价的连通分量算法，把所有共现标识归并为一个连通组件
5. 每个连通组件生成一个 `invoice_group_key`

这样可以得到稳定的业务含义：

- 同一源行里的 `INV#` 与 `SK/YM INVOICE NO.` 自动归到同一组
- `EMAX PTE` 的 `-P` 仅是显示规则，不会把票据组拆开
- 左侧列表可以只保留一个票据组对象

注意：并查集只负责识别“哪些发票标识彼此关联”，不负责吞掉所有差异。若同一个连通组件里出现多组互相冲突的原始发票号或工厂发票号，核心包必须把冲突显式写入摘要状态，而不是静默合并。

### 6.3 display_invoice_no 选择规则

每个票据组需要一个统一展示值 `display_invoice_no`，用于：

- 左侧列表主文本
- 右侧预览标题

采用如下优先级：

1. 若票据组中存在原始 `INV#`，优先使用 `INV#` 作为 `display_invoice_no`
2. 若不存在 `INV#`，但存在 `SK/YM INVOICE NO.`，则使用该值
3. 若两类值都不存在，则该组件不构成可预览票据组

这样做的原因：

- `INV#` 更接近当前页面已认知的“Invoice 号”
- `EMAX PTE` 的 `-P` 属于主体专属展示，不适合作为跨主体组标题
- 工厂侧票据号作为兜底值，保证纯工厂链场景下仍能形成票据组

### 6.4 seller_invoice_numbers 生成规则

对于一个已经聚合完成的票据组，按以下规则为每个主体生成显示号码：

- `GS PTE`
  - 取组件中的原始 `INV#`
- `EMAX PTE`
  - 对组件中的原始 `INV#` 应用 `-P`
- `SK`
  - 取组件中的 `SK/YM INVOICE NO.`
- `YM`
  - 取组件中的 `SK/YM INVOICE NO.`

说明：

- 左侧列表主文本仍只显示 `display_invoice_no`
- 当右侧切换主体时，再使用 `seller_invoice_numbers[seller]` 作为当前主体的实际单据上下文

### 6.5 invoice_group_key 编码

`invoice_group_key` 作为内部主键，不直接使用 `display_invoice_no`。第一阶段即采用稳定编码：

```text
invgrp::<component_hash>
```

`component_hash` 固定使用 SHA-256，对以下规范化 JSON 的 UTF-8 字节计算摘要，并取前 16 个十六进制字符：

```json
{"identifiers":["INV-001","SKYM-001"]}
```

规范化等价于 Python `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`：对象 key 按字典序、无多余空白、非 ASCII 字符直接按 UTF-8 编码，`identifiers` 去空、去重并按字典序排列。输入只包含：

- 排序后的原始发票标识集合

这样做的原因：

- 展示发票号可能重复，不适合作为缓存和选中主键
- 发票号可能含 `/`、`#`、空格等 URL 不友好的字符
- 与源行号解耦后，工作簿插行或重排不会改变同一业务票据组的 key
- 修改发票标识会生成新 key，这是业务身份发生变化后的预期行为

## 7. 票据组摘要生成流程

在 `WorkbookSnapshot` 构建阶段新增 `invoice_summary`：

```text
build_workbook_snapshot
  -> 解析全部 PO 行
  -> resolve_po_rows
  -> 提取每行的票据标识
  -> 构建票据组连通分量
  -> 生成 invoice_summary
```

固定输出：

- `invoice_summary: tuple[InvoiceInspection, ...]`
- `invoice_index: dict[str, tuple[int, ...]]`
- `invoice_header_context: dict[str, InvoiceHeaderContext]`

其中：

- `invoice_index` 记录 `invoice_group_key -> po_rows 下标`
- 供 `Invoice 视角` 预览接口直接复用
- `invoice_header_context` 记录跨 `PO` 单据 header 的取值结果、冲突和来源

这样可以保持与当前 `po_index` 对称：

- `po_index` 用于 `PO 视角`
- `invoice_index` 用于 `Invoice 视角`

## 8. 跨 PO 预览装配规则

票据组可能覆盖多个 `PO`，因此不能直接复用“单个 `po_no` 即是单据 header 上下文”的假设。

在核心包中新增面向票据组的预览构建入口：

```text
preview_invoice_group_from_snapshot(snapshot, invoice_group_key, seller, document)
```

该入口负责：

1. 根据 `invoice_index` 取出源行集合
2. 根据 `seller` 过滤 SK/YM 对应 CATEGORY 行
3. 使用 `seller_invoice_numbers[seller]` 作为当前主体实际发票号
4. 构建跨 `PO` 的 `DocumentModel`
5. 返回与现有 preview 响应兼容的结构化预览

跨 `PO` header 固定取值如下：

| 字段 | 规则 |
| --- | --- |
| `po_no` | 多个 PO 时使用逗号连接的展示值，源数据保留 `po_nos` 数组 |
| `ship_to` / `final_destination` | 所有行一致时使用该值；不一致时返回阻断错误 |
| `manufacturer_address` | 所有行一致时使用该值；不一致时返回阻断错误 |
| `invoice_no` | 使用当前主体下的 `seller_invoice_numbers[seller]` |
| `pi_no` | 不适用于 `Invoice 视角` |

第一阶段对影响单据抬头含义的 header 冲突采取阻断错误，避免静默生成语义混杂的发票。

## 9. 预览与导出 API 设计

### 9.1 设计目标

API 需要做到：

- `PO 视角` 与 `Invoice 视角` 语义分离
- 前端能独立获取票据组列表
- 前端能基于 `invoice_group_key` 和 `seller` 获取 `Invoice / PL` 预览与导出

### 9.2 不推荐方案

不推荐继续沿用以下形式：

- `POST /api/po/{po_no}/preview?scope=invoice`
- 任何通过 `base_file` 查询票据组、绕过 session 的接口形式

原因：

- 路由主语仍然是 `po`
- 容易继续把两个业务对象混在一条接口里
- 后续导出接口也会被带偏
- `base_file` 绕过当前工作台 session、缓存和临时目录权限模型

### 9.3 固定接口

新增以下接口，不保留等价路由或 `base_file` 传参变体：

#### 1. 获取票据组列表

```text
GET /api/invoices
X-Session-Id: <session_id>
```

返回：

- `invoice_group_key`
- `display_invoice_no`
- `status`
- `po_count`
- `sellers`
- `blocking_count`
- `conflict_count`

#### 2. 获取票据组预览

```text
POST /api/invoice/{invoice_group_key}/preview
X-Session-Id: <session_id>
```

请求体：

```json
{
  "seller": "GS PTE",
  "document": "INVOICE"
}
```

说明：

- `invoice_group_key` 已经锁定票据组，无需再传 `invoice_no`
- `seller` 决定当前主体上下文
- `document` 只能是 `INVOICE` 或 `PL`
- `base_file` 不在请求体中重复传递，由 session 解析

#### 3. 导出票据组

```text
POST /api/invoice/{invoice_group_key}/export
X-Session-Id: <session_id>
```

请求体：

```json
{
  "seller": "GS PTE",
  "documents": ["INVOICE", "PL"]
}
```

说明：

- `documents` 必须是 `INVOICE`、`PL` 的非空子集；前端默认同时提交两者
- 核心包按票据组构建一个或多个 workbook，API 统一封装为 ZIP 响应
- 文件名使用 `<SELLER>-RO-<DOCUMENT>-<INVOICE_NO>.xlsx`
- 本阶段不新增票据组详情端点；列表响应已经覆盖首屏和预览入口所需信息

### 9.4 返回结构

`POST /api/invoice/{invoice_group_key}/preview` 在现有 preview 响应上增加以下字段：

- `invoice_group_key`
- `display_invoice_no`
- `seller_invoice_no`
- `po_nos`

示意：

```json
{
  "status": "success",
  "invoice_group_key": "invgrp::5c4da065fc2a5b64",
  "display_invoice_no": "INV-001",
  "seller_invoice_no": "INV-001-P",
  "po_nos": ["4500030844", "4500030845"],
  "preview": { "...": "..." },
  "errors": [],
  "warnings": []
}
```

## 10. 核心包实现边界

能力固定分层如下：

### 10.1 ro_generator

负责：

- 票据组聚合规则
- `invoice_group_key` 生成
- `invoice_summary` 构建
- `SHIP QTY > 0` 成员行筛选
- 跨 `PO` header 冲突诊断
- 基于票据组的预览数据装配
- 基于票据组的导出装配与文件命名

禁止：

- 在 API 层或前端层推断票据组

### 10.2 ro_workbench_api

负责：

- 新增 `invoice` 相关 HTTP 路由
- 复用 session 获取 base 文件和缓存快照
- 把请求转换成核心包调用
- 把响应序列化为 JSON

禁止：

- 在路由里写“如何把 SK/YM 发票号和 INV# 合并”的业务逻辑
- 在路由里根据 `base_file` 绕过 session 直接读工作簿

### 10.3 frontend

负责：

- `Invoice 视角` 下展示 `invoice_summary`
- 以 `invoice_group_key` 作为左侧选中项主键
- 基于 `seller` 与 `document` 拉取右侧预览
- 基于当前票据组导出 Invoice / PL

禁止：

- 在前端自行拼接 `-P`
- 在前端自行决定哪些发票号属于同一组
- 在前端自行合并多个 `PO` 的 header 或状态

## 11. 风险与缓解

### 11.1 风险：不同主体发票号并非一一对应

说明：

- 同一票据组里，可能出现某主体缺失对应发票号

缓解：

- `seller_invoice_numbers` 允许缺项
- 切换到缺失主体时返回空态或阻断错误

### 11.2 风险：display_invoice_no 冲突

说明：

- 理论上可能存在两个业务票据组共享同一个展示号

缓解：

- 第一阶段即使用 `invgrp::<component_hash>` 作为主 key
- `display_invoice_no` 只做展示，不参与前端选中和 API 路径身份

### 11.3 风险：同行共现导致过度合并

说明：

- 一个连通组件内可能出现多个原始 `INV#` 或多个 `SK/YM INVOICE NO.`

缓解：

- 核心包在构建 `invoice_summary` 时统计冲突并写入 `conflict_count`
- 有冲突的票据组状态至少为 `partial`
- 若冲突会影响当前 `seller + document` 的预览行范围，则预览返回阻断错误，不静默合并

### 11.4 风险：跨 PO header 不一致

说明：

- 同一票据组覆盖多个 `PO` 时，`ship_to`、`final_destination`、`manufacturer_address` 可能不同

缓解：

- 核心包构建 `invoice_header_context`
- 影响单据抬头语义的字段不一致时返回阻断错误
- 错误中携带冲突字段、涉及 `PO` 和源行，供 UI 引导用户回到数据检查

### 11.5 风险：接口迁移期间双路径并存

说明：

- `PO` 预览接口与 `Invoice` 预览接口会同时存在

缓解：

- 明确前端 scope 到接口的映射
- 不在同一接口里混 scope 分支

## 12. 实施顺序

按以下顺序推进：

1. 在核心包中新增票据组提取与 `invoice_summary`
2. 在 snapshot 中补 `invoice_index` 和 `invoice_header_context`
3. 新增基于 `invoice_group_key` 的核心包预览入口
4. 在核心包新增基于票据组的 Invoice / PL 导出入口
5. 在 API 中新增受 session 约束的票据组列表、预览与导出接口
6. 在前端 `Invoice 视角` 接入票据组列表、预览与导出调用
7. 最后补全空态、错误态与右侧主体切换细节

## 13. 与上一份文档的关系

本文与《工作台预览页双视角设计》的分工如下：

- 上一份文档解决：
  - 预览页操作逻辑
  - 左侧列表对象
  - 双视角交互
- 本文解决：
  - 票据组如何聚合
  - 聚合键如何定义
  - `Invoice 视角` 预览与导出 API 如何设计

两份文档合起来，才构成完整的 `Invoice 视角` 设计基础。
