# Invoice 只读检查视图设计

## 1. 背景与目标

当前工作台已经按业务对象拆分预览和导出：PI/PO 以单个 PO 为对象，Invoice/PL 以可能覆盖多个 PO 的票据组为对象。但数据检查仍只支持 PO，用户无法在装配前确认一个票据组实际包含哪些出货行，也无法集中查看票据组层面的阻断和警告。

本功能增加 Invoice 只读检查视图。它回答两个基础问题：

1. 当前 `invoice_group_key` 实际使用哪些输入行？
2. 哪些基础数据问题会阻止或影响后续装配？

检查视图不承担编辑和文档渲染职责。

## 2. 第一性原理

数据检查不是某张 Excel sheet 的镜像，而是对当前业务对象的装配输入和基础约束进行解释。因此：

- PO 检查以 `po_no` 为对象，展示该 PO 的源行和 resolver 问题。
- Invoice 检查以 `invoice_group_key` 为对象，展示该票据组实际参与装配的源行、resolver 问题和票据组问题。
- 检查、预览和导出必须使用同一份票据组成员关系，不能由前端重新筛选或聚合。
- 基础检查与单据预览保持边界：模板缺失、模板 mapping 或特定 document type 的构建错误留在预览/导出阶段。

## 3. 用户体验

### 3.1 视角切换

`数据检查`页显示 `PO 视角 / Invoice 视角`切换：

- PO 视角保持现有可编辑 PO 表格。
- Invoice 视角显示票据组列表和只读检查表格。
- 两个视角分别记忆选中对象。
- 从预览或导出返回数据检查时沿用当前视角，不强制切回 PO。

### 3.2 Invoice 检查摘要

右侧顶部显示：

- `display_invoice_no`
- 出货行数
- 覆盖 PO 数量
- 阻断数量
- 警告数量

阻断和警告沿用 PO 数据检查的交互：同样的状态徽章、问题面板、问题去重和位置格式。问题必须直接展示原因；不提供跳转到 PO 或源单元格的操作。

### 3.3 只读出货行表格

表格只包含票据组中 `SHIP QTY > 0` 且实际参与该组装配的源行，列固定为：

| 列 | 含义 |
| --- | --- |
| 源行 | `PO record` 中的真实行号 |
| PO NO. | 行所属 PO |
| SAP | 产品 SAP 编号 |
| 品名 | 解析后的产品描述 |
| Category | 产品/工厂主体分类 |
| SHIP QTY | 实际出货数量 |
| INV# | 客户侧发票号 |
| FACTORY DOC NO. | 工厂侧票据号 |
| 可用主体 | 当前行可参与装配的 seller |

表格不提供双击编辑、输入框、批量操作或跳转动作。

## 4. 问题口径

### 4.1 复用 PO resolver 问题

核心包按票据组覆盖的每个 PO 分别调用现有 `resolve_po_rows()`，但只把票据组成员源行传入 resolver。收集并去重：

- `blocking_error`
- `warning`

去重键固定为 `(kind, code, message, sheet, row, field)`，与现有 PO 检查前端口径一致。这样保留现有 SAP、数量、价格和产品主数据校验，不在 API 或前端复制业务规则。

### 4.2 票据组特有问题

核心包同时纳入：

- 原始发票号或工厂票据号冲突
- `ship_to` 冲突
- `final_destination` 冲突
- `manufacturer_address` 冲突

影响抬头语义的跨 PO 冲突为阻断错误。原始发票号或工厂票据号冲突生成 `severity: high` 的 warning，与现有票据组 `partial` 状态一致；本功能不改变既有分组、预览或导出行为。问题级别由核心包固定，不由前端推断。

### 4.3 明确排除

以下问题不进入基础检查：

- 某一模板不存在
- YAML mapping 或模板单元格错误
- 某个 document type 特有的渲染错误
- 导出目录或文件冲突

这些问题继续在单据预览或导出阶段呈现。

## 5. 核心包设计

在 `ro_generator` 增加冻结结果模型和入口：

```python
@dataclass(frozen=True)
class InvoiceInspectionRow:
    source_row: int
    po_no: str
    sap: str
    description: str
    category: int | None
    ship_qty: Decimal
    invoice_no: str | None
    factory_document_no: str | None
    sellers: tuple[str, ...]

@dataclass(frozen=True)
class InvoiceGroupInspection:
    invoice_group_key: str
    display_invoice_no: str
    po_nos: tuple[str, ...]
    rows: tuple[InvoiceInspectionRow, ...]
    blocking_errors: tuple[ValidationMessage, ...]
    warnings: tuple[ValidationMessage, ...]
```

公开入口：

```python
inspect_invoice_group_from_snapshot(snapshot, invoice_group_key) -> InvoiceGroupInspection
```

该入口负责成员行提取、逐 PO resolver 调用、票据组问题合并和稳定去重。未知 key 返回结构化阻断错误，不抛出未处理异常。

## 6. API 设计

新增 session 约束接口：

```text
GET /api/invoice/{invoice_group_key}/inspection
X-Session-Id: <session id>
```

请求不接受 `base_file`。API 从 session 获取工作簿快照，调用核心包入口并序列化结果。响应结构：

```json
{
  "invoice_group_key": "invgrp::...",
  "display_invoice_no": "INV-001",
  "po_nos": ["PO-1", "PO-2"],
  "line_count": 3,
  "blocking_count": 1,
  "warnings_count": 2,
  "rows": [],
  "blocking_errors": [],
  "warnings": []
}
```

问题对象继续使用现有 `ValidationIssue` 字段：`kind`、`code`、`message`、`sheet`、`row`、`field`、`severity`。

## 7. 前端设计

- `api.ts` 增加 Invoice inspection 类型和请求方法。
- Pinia 增加独立的 `invoiceInspection`、loading 和 error 状态。
- 选择 Invoice 票据组时，仅在数据检查 tab 需要时加载 inspection；预览和导出仍使用现有接口。
- `DataCheckScreen` 按当前视角渲染 PO 可编辑表格或 Invoice 只读表格。
- 抽取共享问题摘要组件，供 PO 和 Invoice 检查复用，确保徽章、去重、问题面板与位置格式一致。
- 前端不得根据行值计算阻断、警告、主体或票据组成员关系。

## 8. 错误与空态

- 未选择票据组：显示“选择左侧 Invoice 开始数据检查”。
- 票据组没有成员行：显示核心包返回的阻断原因，不伪造空白成功状态。
- session 失效：沿用当前 API 错误处理。
- inspection 请求失败：保留左侧选中状态，在右侧显示明确错误，不回退到 PO 数据。
- 票据组被重新计算后 key 失效：返回 `INVOICE_GROUP_NOT_FOUND`。

## 9. 测试策略

### 核心包

- 只返回票据组索引中的 `SHIP QTY > 0` 成员行。
- 跨 PO 成员按源行稳定排序。
- 合并并去重各 PO resolver 的阻断和警告。
- 返回发票标识及 header 冲突原因。
- 未知 key 返回结构化阻断。

### API

- 有效 session 返回完整 inspection。
- 缺失或过期 session 被拒绝。
- 请求体和查询参数不依赖 `base_file`。

### 前端与 E2E

- 数据检查页可切换 PO/Invoice 视角。
- Invoice 表格只读且显示正确成员行。
- 阻断和警告面板与 PO 检查交互一致。
- 从 Invoice 预览返回数据检查时保留 Invoice 票据组选中状态。
- PO 编辑流程不回归。

## 10. 非目标

- 不支持跨 PO 编辑。
- 不支持从问题或行跳转到 PO。
- 不增加前端业务校验。
- 不改变 Invoice/PL 预览和导出装配规则。
- 不把模板和渲染错误提前到基础检查。

## 11. 文档一致性

实施时同步修订产品方案和 UI 设计中“数据检查始终以 PO 为对象”的旧条款。修订后的规则是：数据检查按当前 PO/Invoice 视角检查对应业务对象；PO 可编辑，Invoice 只读。
