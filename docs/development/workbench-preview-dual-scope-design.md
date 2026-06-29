# 工作台预览页双视角设计

## 1. 目标

将当前“先选择 PO，再查看所有单据预览”的单一操作逻辑，调整为面向业务对象的双视角预览：

- `PO 视角`：只查看 `PI / PO`
- `Invoice 视角`：只查看 `Invoice / PL`

该设计用于解决当前预览对象与实际业务对象不一致的问题，避免继续把所有预览都强行绑定到单个 `PO`。

## 2. 当前问题

现有预览页的核心上下文是单个 `PO`：

- 前端主状态以 `selectedPo` 为中心。
- 左侧列表是 `PO` 工作队列。
- 预览接口按 `po_no` 查询。

这套模型对 `PI / PO` 仍然成立，但对 `Invoice / PL` 已经不适用，因为 `Invoice / PL` 未来应按票据组聚合，一个票据组可覆盖多个 `PO`。

如果继续沿用“点一个 PO，看所有单据”的模型，会出现以下问题：

- 用户点的是 `PO`，看到的却是跨多个 `PO` 的 `Invoice / PL` 聚合结果，语义错位。
- 左侧列表无法表达票据组对象。
- `selectedPo` 同时承担列表选择、预览范围、导出上下文等多重职责，状态会继续耦合。

## 3. 已确认结论

### 3.1 视角划分

- 预览页采用双视角切换。
- 顶部增加一级 tab：
  - `PO 视角`
  - `Invoice 视角`

### 3.2 不同视角查看不同单据

- `PO 视角` 只显示：
  - `PI`
  - `PO`
- `Invoice 视角` 只显示：
  - `Invoice`
  - `PL`

### 3.3 Invoice 视角的列表粒度

- 左侧列表一行对应一个票据组。
- 不采用“票据组 × 主体”拆成多行的方式。
- 同一业务票据在不同主体下视为同一票据组。

### 3.4 Invoice 视角的列表展示

- 左侧列表主文本只显示 `Invoice 号`。
- 不再使用一整行自然语言副文案描述来源；`PO` 数量和主体信息作为紧凑元信息展示。
- 列表整体样式保持与当前 `PO 视角` 一致。
- 列表项仍需展示：
  - 状态
  - `PO` 数量
  - 主体信息

### 3.5 Invoice 视角的标题与主体切换

- 右侧主标题显示当前 `Invoice 号`，例如：`INV-001`
- 主体切换保留在右侧工作区。
- 在 `Invoice 视角` 下切换主体时：
  - 左侧当前票据组保持不变
  - 仅刷新右侧单据内容

### 3.6 PO 视角与 Invoice 视角之间的关系

- 两个视角通过顶部 tab 手动切换。
- 从 `PO 视角` 切到 `Invoice 视角` 时，不需要自动定位到当前 `PO` 所属票据组。

### 3.7 统一票据组主键

- 页面统一展示“`Invoice 号`”。
- 底层引入统一的 `invoice_group_key` 概念，作为 `Invoice 视角` 的聚合主键。
- `invoice_group_key` 不简单等同于某一个固定源字段，而是允许不同主体从不同原始字段映射到同一票据组。

## 4. 交互设计

### 4.1 顶部结构

预览页顶部结构调整为：

```text
[ PO 视角 ] [ Invoice 视角 ]
```

说明：

- 这是一级视角切换。
- 切换后，左侧列表对象和右侧单据 tabs 一并切换。

### 4.2 PO 视角

左侧：

- 继续显示 `PO` 工作队列。
- 列表风格保持当前实现。

右侧：

- 只显示 `PI / PO` 两个单据 tab。
- 不在该视角下承载票据组语义。

推荐交互：

```text
PO 视角
┌ 左侧：PO 列表 ────────────┐
│ 4500030844   就绪         │
│ 4500030845   待补全       │
└──────────────────────────┘

┌ 右侧：预览区 ─────────────────────────┐
│ 主体切换                              │
│ [ PI ] [ PO ]                         │
│                                       │
│ 单据预览                              │
└───────────────────────────────────────┘
```

### 4.3 Invoice 视角

左侧：

- 显示票据组列表。
- 一行仅对应一个票据组。
- 主文本只显示 `Invoice 号`。
- 每项显示：
  - 状态
  - `PO` 数量
  - 主体信息

右侧：

- 只显示 `Invoice / PL` 两个单据 tab。
- 右侧保留主体切换。
- 切换主体时只刷新右侧内容，不改变左侧选中项。

推荐交互：

```text
Invoice 视角
┌ 左侧：Invoice 列表 ─────────┐
│ INV-001   就绪              │
│         3 个 PO / GS, EMAX  │
│ INV-002   待补全            │
│         2 个 PO / GS        │
└─────────────────────────────┘

┌ 右侧：预览区 ─────────────────────────┐
│ INV-001                               │
│ 主体切换                              │
│ [ Invoice ] [ PL ]                    │
│                                       │
│ 单据预览                              │
└───────────────────────────────────────┘
```

## 5. 状态模型调整

前端需要把当前单一 `PO` 中心状态拆分为三类状态：

- `previewScope`
  - `"po"` 或 `"invoice"`
- 对象选择
  - `selectedPo`
  - `selectedInvoiceGroup`
- 右侧上下文
  - `selectedSeller`

推荐最小状态模型：

```ts
type PreviewScope = "po" | "invoice";

interface PreviewState {
  previewScope: PreviewScope;
  selectedPo: string | null;
  selectedInvoiceGroup: string | null;
  selectedSeller: string | null;
}
```

约束：

- `selectedPo` 不再承担所有预览上下文。
- `selectedInvoiceGroup` 只在 `Invoice 视角` 下生效。
- `selectedSeller` 在 `Invoice 视角` 下只影响右侧内容，不影响左侧票据组选中状态。

## 6. 数据模型

### 6.1 保留 PO 摘要

现有 `PO` 列表摘要模型继续保留，用于 `PO 视角`。

### 6.2 新增 Invoice 摘要

为 `Invoice 视角` 新增票据组摘要模型，包含：

- `invoice_group_key`
- `display_invoice_no`
- `status`
- `po_count`
- `sellers`
- `blocking_count`
- `conflict_count`

示意：

```ts
interface InvoiceInspection {
  invoice_group_key: string;
  display_invoice_no: string;
  status: "ready" | "partial" | "blocked" | "done";
  po_count: number;
  sellers: string[];
  blocking_count: number;
  conflict_count: number;
}
```

说明：

- 页面显示名统一使用 `Invoice 号`。
- `invoice_group_key` 作为内部聚合主键，不要求直接暴露给用户解释其来源细节。
- 票据组只包含 `SHIP QTY > 0` 的成员行，前端不参与数量筛选。
- 状态枚举沿用工作台现有 `ready / partial / blocked / done`。若第一阶段尚未实现导出完成态，后端可以暂不返回 `done`，但模型层不另起一套状态口径。

## 7. 接口设计

### 7.1 现状

当前预览接口按 `po_no` 查询，语义与 `Invoice 视角` 不匹配。

### 7.2 目标

预览能力需要同时支持两类对象：

- `PO` 对象预览
- `Invoice` 票据组预览

### 7.3 固定方案

为 `Invoice 视角` 提供独立接口，并继续沿用工作台 session 契约：

- `GET /api/invoices`，请求携带 `X-Session-Id`
- `POST /api/invoice/{invoice_group_key}/preview`，请求携带 `X-Session-Id`
- `POST /api/invoice/{invoice_group_key}/export`，请求携带 `X-Session-Id`

不推荐继续把 `Invoice` 票据组预览塞进 `/api/po/{po_no}/preview` 语义下，否则会继续加重模型混乱。也不建议绕过 session 直接暴露 `base_file` 查询，因为当前工作台的缓存、临时目录和下载权限都以 session 为边界。

## 8. 实施边界

本设计文档当前只覆盖：

- 预览页操作逻辑
- 页面对象模型
- 列表粒度
- 状态拆分
- 固定接口契约

导出按当前视角与选中对象执行：

- `PO 视角`只导出当前 PO 的 PI / PO
- `Invoice 视角`只导出当前票据组的 Invoice / PL，默认同时选中二者
- 一次操作不混合两类业务对象；工作台响应统一为 ZIP
- Invoice / PL 文件名使用 `<SELLER>-RO-<DOCUMENT>-<INVOICE_NO>.xlsx`

`invoice_group_key` 的聚合算法、`SHIP QTY` 成员行筛选、session API 与跨 `PO` 预览装配规则由配套文档《工作台票据组聚合键与预览 API 设计》细化。

## 9. 实施顺序

按以下顺序推进：

1. 先在核心包定义票据组模型、状态口径和跨 `PO` 预览输入。
2. 再补 `Invoice` 票据组摘要数据和 session 级接口。
3. 再完成前端双视角 UI 外壳与状态拆分。
4. 最后联调主体切换与 `Invoice / PL` 预览、导出。

这样可以避免前端先依赖临时聚合规则，保证页面状态、API 和核心包业务语义从一开始就是同一套对象模型。

## 10. 默认状态与空态

- 首次进入单据预览页默认使用 `PO 视角`，沿用当前选中的 PO；没有已选 PO 时选择列表中第一个对象。
- 首次切换到 `Invoice 视角`时，优先选择第一个非 `blocked` 票据组；若全部阻断则选择第一项；列表为空时右侧显示空态且不发预览请求。
- 两个视角分别记忆自己的选中对象、主体和单据类型，来回切换时恢复，不互相覆盖。
- 右侧只允许选择 `InvoiceInspection.sellers` 中存在的主体；其他主体显示为禁用状态，提示“该票据组在此主体下无可装配数据”。
- 当前票据组因字段冲突无法预览时保留选中状态，在右侧展示核心包返回的阻断原因和涉及的 PO / 源行。
