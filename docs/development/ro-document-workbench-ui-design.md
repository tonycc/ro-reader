# RO 单据工作台 UI 说明

> 本文描述当前前端实现，不包含尚未开发的交互设想。产品范围见 [`../product/ro-document-generator-product-plan.md`](../product/ro-document-generator-product-plan.md)。

## 1. 技术与边界

- Vue 3 + `<script setup lang="ts">`
- TypeScript、Pinia、Vite
- 原生 `<table>` 和组件局部 CSS
- 全局 token：`frontend/src/styles/tokens.css`

前端不计算价格、主体、票据组、校验结果或导出文件名，只提交用户选择并渲染核心包结果。

当前依赖中没有 SheetJS、Tailwind 或组件设计系统。单据预览消费后端结构化 JSON，而不是在浏览器读取 `.xlsx`。

## 2. 页面结构

`App.vue` 使用三行网格：

```text
TopBar（56px）
┌───────────────┬─────────────────────────────────────┐
│ QueueSidebar  │ 数据检查 | 单据预览 | 导出确认       │
│ 292px         │ 当前 Tab 内容                       │
└───────────────┴─────────────────────────────────────┘
StatusBar（30px）
```

主要组件：

| 组件 | 职责 |
| --- | --- |
| `TopBar.vue` | 当前工作区显示、切换入口、启动 bootstrap 和旧路径迁移 |
| `WorkspaceSwitcher.vue` | 顶部工作区下拉切换和激活失败提示 |
| `WorkspaceSettings.vue` | 工作区列表、CRUD、检测和激活 |
| `WorkspaceForm.vue` | Customer Profile/base 路径表单及不落盘检测 |
| `WorkspaceStatusBadge.vue` | 工作区路径/Profile/schema 状态 |
| `QueueSidebar.vue` | PO/Invoice 业务对象列表、选择和筛选 |
| `DataCheckScreen.vue` | PO/Invoice 数据检查切换 |
| `InvoiceDataCheck.vue` | 票据组只读成员行 |
| `IssueSummaryBar.vue` | 阻断/警告摘要和详情 |
| `PreviewScreen.vue` | 作用域、主体、单据选择和预览编排 |
| `PreviewDocumentPanel.vue` | 单张结构化单据 |
| `ExportScreen.vue` | 主体、单据、Excel/PDF 导出确认 |
| `LibreOfficePrompt.vue` | PDF 转换器缺失提示 |
| `StatusBar.vue` | 当前对象状态和问题计数 |

## 3. TopBar

正式模式顶部栏显示当前工作区、Customer Profile 和 base 文件名；下拉菜单调用真实 HTTP `WorkspaceService` 激活工作区。切换开始时先清空页面数据；列名对不上时顶部显示刚选中的工作区，并在数据检查页用黄色横幅提示，不再弹框。文件不存在、无权限等仍弹出「无法打开工作区」。

“管理工作区”打开工作区设置：

- 列表支持新增、编辑、删除、检测和设为当前；当前工作区不能直接删除。
- 新增/编辑表单的“检测路径”调用 `POST /api/workspaces/validate`，只读取 Profile 与 base，不落盘。
- “保存工作区”和“设为当前”是两个独立操作，避免误把保存配置当成激活。
- 编辑当前工作区后旧 session 暂时保留，但卡片和顶部栏显示“待重新激活”，并把“设为当前”变为可操作的“重新激活”；激活成功才替换 session 和工作台数据。
- 启动先调用 `GET /api/bootstrap`。若内存里已有匹配当前工作区的 session，仍会重建快照并做结构校验，不能直接复用上次激活留下的旧数据。列名对不上时不弹框，只在数据检查页显示黄色横幅；文件不存在等仍弹出错误。旧版本 `localStorage` 的 `ro-workbench-base-path` 只在没有当前工作区时迁移；创建和激活都成功后才删除旧 key，失败时保留并打开设置。
- 「重新加载」走 `POST /api/session/refresh`（无 session 时改为重新激活当前工作区）。列名对不上时清空页面并刷新黄色横幅；文件缺失等仍弹框。成功后刷新数据检查里的列名问题提示。
- 正式模式使用 `frontend/src/services/workspace.http.ts`；访问 `?workspace-prototype=1` 时仅在开发环境切换到 mock，供交互评审和失败回滚测试。

当前 TopBar 不提供撤销、重做、版本历史或文件选择器；用户输入本机 `.xlsx` 路径。若 HTTP 工作区服务不可用，临时回退到旧系统设置入口以保持 RO 兼容流程。

## 4. QueueSidebar

队列有两种业务对象：

- PO：状态为 `ready`、`partial` 或 `blocked`。
- Invoice：状态为 `ready`、`partial`、`blocked` 或 `done`。

PO 摘要包含主体、行数、发票候选、可导出单据和阻断数量。Invoice 摘要包含显示发票号、成员 PO、主体发票号和冲突数。

选择对象时，store 分别记忆 `selectedPo` 和 `selectedInvoiceGroup`，不能把两种 ID 混用。

## 5. 数据检查

### 5.1 PO 视角

从 `GET /api/po/{po_no}` 获取 headers 和 rows。双击可编辑单元格，提交到 `/api/po/{po_no}/edit`。

编辑成功后重新加载当前 PO、问题和预览。当前 store 固定写入 `PO record`，不允许从 UI 编辑 `DATA BASE` 或 `客户PO`。

PF 的新订单可以只存在于 `new PO template`。此时队列和 PI/PO 预览仍可用，但数据表中的 PO record 字段是只读解析投影；需要调整客户订单数量时应回到源 workbook 修改 `new PO template`。

### 5.2 Invoice 视角

从 `GET /api/invoice/{key}/inspection` 获取票据组实际出货行。表格只读，展示源行号、PO、SAP、描述、Category、SHIP QTY、发票号、SK/YM 发票号和可用主体。

loading、error 和 empty 状态彼此独立，不能沿用上一个票据组数据。

### 5.3 问题摘要

PO 和 Invoice 复用 `IssueSummaryBar`。详情由后端返回的 code、message、Sheet、row、field 和 severity 驱动；前端不重新判断严重度。

PF 会在这里显示两类非阻断 high warning：

- `MOQ_NOT_MET`：同一 PO、同一 SAP 的订单合计低于 MOQ；
- `FULL_CARTON_NOT_MET`：订单合计不是 `round value` 的整数倍。

提示详情直接显示 `new PO template / row / Order Quantity`，前端不自行读取 MOQ 或计算余数。

### 5.4 列名对应关系

黄色提示条和修复向导共用同一套计数：缺失 Sheet、缺失数据列和缺失价格列都算进去。列名对不上只走黄条，不再弹框。「对应到」下拉显示 Excel 列号和列名，例如 `A:SAP`。

旧列仍在、只想改指到新加列时，打开「字段对应关系总览」。总览按产品主数据、PO/出货记录、客户订单、价格列分页，一次只显示一组。点「修改对应关系」并验证 PIN 后用下拉调整，保存仍写入同一个 override 文件，并提交所有分组里的改动。

## 6. 单据预览

### 6.1 两种作用域

- `po`：PI、PO。
- `invoice`：RO 的 INVOICE_PL，以及 PF 的独立 INVOICE、PL；SK/YM 额外支持 CI_PL。

切换作用域时分别恢复已选 PO/票据组和主体。

### 6.2 请求编排

组合预览不是后端领域单据类型：

- `INVOICE_PL` 在前端并行请求 `INVOICE` 和 `PL`。
- `CI_PL` 在前端并行请求 `CI` 和 `RO_PL`。
- PF Profile 的 Invoice 与 PL 使用不同模板，预览页分别请求并展示单个文档，不使用 `INVOICE_PL` 合并页。

每张单据独立保留 preview、errors 和 warnings；一张失败不应隐藏另一张结果。

组合导出的物理文件由核心包决定：RO 的同模板 Invoice/PL 合并为双 Sheet workbook；PF 的两个独立模板分别生成并打 ZIP。导出页仍只表达“组合选择”，不判断模板是否相同；预览页按 Profile 的单据页面规则展示。

### 6.3 PreviewPayload

预览响应包含：

```text
document_type / title / seller / buyer
po_no / pi_no / invoice_no / ship_to
seller_info / to_label / terms / header_labels
layout / resolved_values
column_labels / lines / totals / notes
source_entries
```

`PreviewDocumentPanel` 按 `layout.top`、`layout.info`、明细表、合计和备注渲染，不依赖 Excel 坐标。

标题和出具方文本由 mapping loader 按 `preview_content.template_fields` 指向的模板单元格读取；`header_labels` 则来自各 header 值单元格同一行的模板标签。`layout` 决定这些字段位于顶部或左右信息区。映射存在但业务值为空的字段仍保留空白横线，连续地址行不重复显示标签。前端只呈现这些结构化结果，不写 SK、YM、GS 或 EMAX 的专属抬头。

`column_labels` 已由核心包从当前 mapping 对应的 Excel 表头解析：YAML 键只决定列及顺序，实际文案来自 `table_header_row`。对于 mapping 声明 `merged_headers: true` 的模板，核心包还返回 `column_header_rows` 的 `rowspan/colspan` 结构，前端按 Excel 的合并关系渲染；其他多行表头仍以换行符呈现，不维护主体或单据专属列名。

### 6.4 来源信息

点击可溯源字段时显示来源详情。来源类型包括：

- `base_field`
- `computed`
- `template_content`
- `system_generated`
- `manual_input`

页面底部也可显示当前预览的来源表。当前没有从数据表单元格反向高亮预览字段。

## 7. 导出确认

导出页根据当前作用域和主体显示合法单据：

- PO 作用域：PI/PO。
- Invoice 作用域：INVOICE/PL；SK/YM 额外显示 CI/RO_PL。

支持勾选 Excel、PDF 或两者。前端把选择转换为 batch groups：

```json
{
  "seller": "GS PTE",
  "documents": ["INVOICE", "PL"]
}
```

后端返回单文件或 ZIP 路径后，store 通过 `/api/download` 触发浏览器下载。

当错误 code 为 `PDF_CONVERTER_UNAVAILABLE` 时设置全局 `libreOfficeMissing`，展示安装引导。前端不得自行把 PDF 请求降级为 Excel。

## 8. Store 状态

`stores/workbench.ts` 是工作台状态入口，主要状态组：

- session/base：`baseFile`、`poList`、`invoiceList`
- selection：PO、票据组、preview scope、seller、invoice no
- data check：PO rows/headers、Invoice inspection
- preview：单据结果、来源、loading/error
- validation：blocking、warnings、PO issues
- export：loading、错误、最后输出、LibreOffice 状态

异步请求必须记录请求上下文，避免较慢的旧请求覆盖新选择。

`stores/api.ts` 只封装 fetch、session header、类型和 HTTP 错误，不含业务规则。
`stores/workspace.ts` 管理 Profile、工作区列表、当前工作区 ID、`needsActivation`、bootstrap 和激活事务；`workspace.http.ts` 只做 FastAPI 协议转换，`workspace.mock.ts` 仅用于开发原型。

## 9. 样式

全局颜色和排版使用 CSS variables。组件优先使用 token，不新增平行色板。

当前视觉语义：

- 蓝色：主操作和当前选择。
- 绿色：ready/success。
- 黄色：warning/partial。
- 红色：blocked/error。
- 灰色：次级信息和不可用项。

布局最小可用高度由 `100vh` 网格保证，主内容区域独立滚动。

## 10. 可访问性和交互约束

- 原生 button/input 保留键盘焦点和 disabled 状态。
- loading 时禁止重复提交。
- 错误文本不能只靠颜色表达。
- 模态可点击遮罩关闭，并提供明确关闭按钮。
- 单据或格式不可用时应禁用，而不是提交后再猜测。

## 11. 当前未实现 UI

以下不应出现在当前使用说明中：

- 撤销/重做按钮。
- 版本历史抽屉。
- 模板预览工具。
- 源数据到文档的反向高亮。
- 原生系统文件选择对话框。

新增这些能力时，先更新产品说明，再补 API/store/组件/E2E，并同步本文档。
