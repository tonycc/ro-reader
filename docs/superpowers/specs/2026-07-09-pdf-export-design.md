# PDF 导出功能设计

## 概述

在单据预览页面增加导出 PDF 功能。用户可在预览页一键导出当前预览的单份单据为 PDF 文件，下载流程与现有 `.xlsx` 导出一致。

## 约束

- **离线可用**：不依赖外部服务，PDF 渲染在用户本地完成。
- **PyInstaller 兼容**：新增依赖必须是纯 Python 包，无原生库依赖。
- **架构纪律**：PDF 渲染逻辑放在核心包 `ro_generator`，CLI / API / 前端为薄壳。
- **范围**：仅预览页单份单据导出（不含批量导出、不含 ExportScreen）。

## 技术方案

采用 **reportlab**（纯 Python，无原生依赖）在后端渲染 PDF，通过现有 `/api/download` 通道下载。不转换 `.xlsx` 文件本身。

**关键决策：复用现有预览构建逻辑。** PDF 渲染器消费 `document_preview.build_preview()` 产出的 `DocumentPreview`（前端预览页用的同一套结构化数据），而非从 `DocumentModel` 另造一套展示布局。原因：

- `DocumentModel` 只含领域数据（seller/buyer/lines/totals），**不含**表头字段标签与列标签；这些展示信息由 `build_preview()` 结合 `mapping` 生成。
- 用户要求"基于现有预览"——复用 `DocumentPreview` 可保证**纸面 = 预览页**，且不重复实现展示映射逻辑（DRY），避免 PDF 与预览出现差异。

## 架构与数据流

```text
用户点击 [导出 PDF]（PreviewScreen.vue）
  → POST /api/po/{po_no}/export  { ..., format: "pdf" }
    → generator.generate(request)  →  GenerationResult 携带 preview: DocumentPreview（新增字段）
    → pdf_renderer.render_pdf(preview, output_path)
    → 返回 { output_file: "/tmp/session-xxx/GS-INVOICE-PO-MONTH.pdf", ... }
  → GET /api/download?path=...  (现有端点，新增 pdf media type)
```

**无新增端点**。导出现有端点复用，通过 `format` 字段区分输出格式。`build_preview()` 已在预览端点使用；导出时复用同一函数，PDF 与预览页共享一份构建逻辑。

## 文件改动清单

### 新增

| 文件 | 说明 |
|------|------|
| `packages/ro_generator/src/ro_generator/pdf_renderer.py` | PDF 渲染器，从 DocumentPreview 生成 PDF |

### 修改

| 文件 | 变更 |
|------|------|
| `packages/ro_generator/src/ro_generator/generator.py` | `GenerationResult` 新增 `preview: DocumentPreview \| None` 字段（由 `_generate_one()` 复用 `build_preview()` 填充） |
| `packages/ro_generator/pyproject.toml` | 新增依赖 `reportlab>=4.0` |
| `packages/ro_workbench_api/src/ro_workbench_api/app.py` | `DryRunRequest` 新增 `format` 字段；导出端点增加 PDF 分派；下载端点增加 `application/pdf` |
| `frontend/src/components/preview/PreviewScreen.vue` | 新增"导出 PDF"按钮 |
| `frontend/src/stores/workbench.ts` | 新增 `doExportPdf()` action |

## 核心模块：pdf_renderer.py

```python
def render_pdf(preview: DocumentPreview, output_path: Path) -> PdfRenderResult:
    ...
```

### 输入

- `DocumentPreview`：`build_preview()` 产出的结构化预览数据，包含 `title`、`seller`/`buyer`、`seller_info`、`to_label`、`terms`、`layout`、`column_labels`、`lines`、`totals`、`notes` — 与前端预览页用同一份数据。

### 输出

- `PdfRenderResult(output_path=Path(...))`

### 页面布局（reportlab Platypus）

渲染逻辑按 `DocumentPreview` 中的结构化块逐块展开：

1. **标题区**：`preview.title`（已构建好的单据标题），可辅以 `preview.seller` / `preview.seller_info`
2. **头信息区**：`preview.layout["top"]` + `preview.layout["info"]` 按位置顺序渲染 key-value 对，配合 `preview.to_label` / `preview.terms`
3. **明细行表格**：`preview.column_labels` 为表头，`preview.lines` 为数据行，列宽根据列数自动适配 A4 竖版/横版
4. **合计区**：`preview.totals` 中的标准合计字段（quantity/amount/net_weight/gross_weight/cbm）右对齐展示
5. **备注区**：`preview.notes` 列表逐行渲染（如 `PACKED IN n CTNS`）

金额使用 `preview.totals` 中已格式化的值，不做重算或业务逻辑。

## 后端接口改动

### DryRunRequest 新增字段

```python
format: Literal["xlsx", "pdf"] = "xlsx"
```

### 导出端点逻辑

```
format == "xlsx" → 走现有 generate() 流程（行为不变）
format == "pdf"  → generate() 拿 GenerationResult.preview → pdf_renderer.render_pdf() → 返回 pdf 路径
```

### 下载端点

```python
media_type = (
    "application/zip" if suffix == ".zip"
    else "application/pdf" if suffix == ".pdf"
    else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
```

### 文件命名

沿用现有 `packager.py` 命名规则，后缀改为 `.pdf`。例如：
- `GS-RO-INVOICE-4500030844-2601.pdf`
- `GS-RO-PI-4500030844.pdf`

## 前端改动

### PreviewScreen.vue

在现有"导出 {docLabel}"按钮右侧新增按钮：

```
[导出 INVOICE (.xlsx)]  [导出 PDF]  [查看字段来源]
```

- 同样受 `disabled`（无数据/导出中/预览加载中）控制
- `@click="wb.doExportPdf()"`

### workbench.ts

```typescript
async function doExportPdf() {
  // 与 doExport() 结构相同，请求体加 format: "pdf"
  // 下载文件名后缀 .pdf
}
```

### api.ts

无需改动——现有 `exportDocuments()` 请求体已可接受额外字段。

## 测试

| 层级 | 测试内容 |
|------|----------|
| 单元 | `test_pdf_renderer.py`：验证报表输出路径、无异常、基本内容验证 |
| 集成 | `test_app.py`：`/export` 端点 `format=pdf` 返回 pdf 路径、download 返回正确 content-type |
| E2E | `workbench.spec.ts`：新增一个场景：preview 页下载 PDF，验证响应为 PDF 格式 |

## 依赖与打包

- `reportlab` 为纯 Python 包（无 C 扩展），PyInstaller 可直接打包。
- 预估 PDF 渲染器约 200-300 行 Python。
