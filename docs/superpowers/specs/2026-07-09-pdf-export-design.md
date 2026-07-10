# PDF 导出功能设计

> **修订记录（2026-07-10，v3 — 渲染引擎推翻）**：v2 用 **reportlab** 从 `DocumentPreview` 重画 PDF，结果**版式与 Excel 模板不一致**（reportlab 只是照简化版预览另画一套，不读 `.xlsx` 模板，字体/列宽/合并单元格/边框/logo/打印区全部丢失）。改为 **LibreOffice 无头转换**：先用现有 renderer 把数据填进 `.xlsx` 模板，再由用户机器预装的 LibreOffice 把该 xlsx 转成 PDF，保证**纸面 = Excel 模板**。
> - 这是一次**产品/分发形态的取舍**：放弃"纯 Python、离线自包含"约束，换取像素级还原。LibreOffice 由用户机器预装（不随应用打包），导出时检测缺失则返回阻断错误。
> - 保留 v2 中仍然成立的部分：**格式分派仍在核心包**（复用 `output_format`）、**两种作用域都覆盖**（PO + SK·YM 发票组）。
> - reportlab 依赖与 `pdf_renderer.py` 已删除，替换为 `pdf_convert.py`。
>
> **修订记录（2026-07-09，v2）**：初版把格式分派放在 API 路由层、并给 `GenerationResult` 挂 `preview` 字段。经对照现有代码修正三处：
> 1. **格式分派下沉核心包**——复用已存在的 `DocumentRequest.output_format`，而非在 `app.py` 里写 `if format == "pdf"`（违反架构纪律，见产品方案 §7.1）。
> 2. **不再新增平行的 `format` 字段、不再改 `GenerationResult`**——核心包内按 `output_format` 分派渲染器，xlsx 导出零负担。
> 3. **补齐 invoice-group 导出路径**——预览页有 `po` / `invoice` 两种作用域，SK/YM 发票组走 `/api/invoice/{key}/export`，初版只覆盖了 `/api/po/{po_no}/export`。

## 概述

在单据预览页面增加导出 PDF 功能。用户可在预览页一键把当前预览的单据导出为 PDF 文件，下载流程与现有 `.xlsx` 导出一致。预览页的两种作用域（PO 单据 / SK·YM 发票组）都支持。

## 约束

- **像素级还原**：PDF 版式必须与 Excel 模板逐格一致（首要目标，v3 的立项原因）。
- **本地转换**：转换在用户机器本地完成，不上传外部服务。
- **LibreOffice 预装**：像素级 xlsx→pdf 无纯 Python 方案，依赖 LibreOffice；它**不随应用打包**（体积大、原生程序），要求用户机器预装。导出时检测 `soffice`，缺失则返回阻断错误 `PDF_CONVERTER_UNAVAILABLE`，**不静默降级**。可用环境变量 `RO_SOFFICE_PATH` 指定非标准安装位置。
- **架构纪律**：PDF 转换逻辑与**格式分派**都放在核心包 `ro_generator`；CLI / API / 前端为薄壳，路由处理器里**不得**出现 `if format == ...` 这类业务分派（产品方案 §7.1）。
- **范围**：仅预览页导出（含 PO 单据与 SK·YM 发票组）。不含导出确认页（ExportScreen）的批量 zip、不含 CLI 新增 flag（CLI 可自然获得，见下）。

## 技术方案

**先渲染 xlsx 模板、再无头转换**：PDF 导出复用现有 renderer 生成 `.xlsx`（数据逐格填进模板），再由 LibreOffice 无头模式（`soffice --headless --convert-to pdf`）转成 PDF，通过现有 `/api/download` 通道下载。中间 `.xlsx` 转换后删除，只保留 `.pdf`。这样 PDF 与 Excel 导出出自**同一个模板**，版式必然一致。

- 转换封装在核心包 `pdf_convert.py`：`find_soffice()` 按"环境变量 → PATH → 平台常见安装位置"定位，`convert_to_pdf()` 用独立临时 `UserInstallation` profile 避免与用户在跑的 LibreOffice 抢锁；缺失抛 `SofficeNotFoundError`、失败抛 `PdfConversionError`（均继承 `RoGeneratorError`）。
- `generate()` 顶层已捕获 `RoGeneratorError` → 阻断错误结果；发票组入口 `export_invoice_group_from_snapshot()` 不经过该兜底，自行 `try/except` 转成 `_error_result`。
- CLI/API/前端无需感知转换细节：错误经现有 `GenerationResult.errors` → 前端导出错误区展示。

### 关键决策 1：复用已有的 `output_format` 轴，分派写在核心包

核心包 `DocumentRequest` **已有** `output_format` 字段（`models.py`）：

```python
output_format: Literal["xlsx", "zip"] = "xlsx"   # 现状
```

且 API 层已通过 `_build_document_request(output_format=...)` 在传递它（`app.py`）。因此**扩展这个已有字段**，而不是另造一个平行的 `format`：

```python
output_format: Literal["xlsx", "zip", "pdf"] = "xlsx"   # 修改后
```

格式分派放进核心包 `generate()` 的下游装配函数（`_generate_one` / 发票组装配路径）：`output_format == "pdf"` 时走 PDF 渲染器，否则走现有 Excel 渲染器。**API 端点只是把 `output_format` 透传下去**，不含任何格式判断——完全符合"薄壳"纪律。这样 `generate()` 是**渲染 PDF 而非 xlsx**（分支，不是额外多渲染一个），因此不会产生没人要的中间 xlsx 文件。

### 关键决策 2：PDF 渲染器消费 `DocumentPreview`

PDF 渲染器消费 `document_preview.build_preview()` 产出的 `DocumentPreview`（前端预览页用的同一套结构化数据），而非从 `DocumentModel` 另造展示布局。原因：

- `DocumentModel` 只含领域数据（seller/buyer/lines/totals），**不含**表头字段标签与列标签；这些展示信息由 `build_preview()` 结合 `mapping` 生成。
- 复用 `DocumentPreview` 保证**纸面 = 预览页**，且不重复实现展示映射逻辑（DRY）。

装配路径内，`build_document_model()` 的产物（`BuildDocumentResult`）已在手，直接 `build_preview(build)` 即可拿到 `DocumentPreview`，无需读取额外数据、无需给 `GenerationResult` 增加字段。

### 数据源一致性（已由现有机制保证）

预览端点读**内存快照**（`cache.get_snapshot()`），导出走 `generate()` 读**磁盘 base 文件**——但编辑端点 `/api/po/{po_no}/edit` 写回 base 后会 `get_cache_manager().invalidate()` 使快照失效，下次预览重新读盘。因此快照与磁盘内容始终一致，PDF（走 `generate()`）与屏幕预览（走快照）数据相同。此点无需额外设计，仅作记录。

## 架构与数据流

```text
【PO 单据作用域】
用户点击 [导出 PDF]（PreviewScreen.vue，previewScope==="po"）
  → POST /api/po/{po_no}/export  { ..., output_format: "pdf" }
    → generate(request)  （request.output_format=="pdf"）
        → _generate_one() 内：build_preview(build) → pdf_renderer.render_pdf([preview], output_path)
    → GenerationResult(status, output_file="/tmp/session-xxx/GS-RO-INVOICE-....pdf")
  → GET /api/download?path=...   （现有端点，新增 pdf media type）

【SK·YM 发票组作用域】
用户点击 [导出 PDF]（PreviewScreen.vue，previewScope==="invoice"）
  → POST /api/invoice/{key}/export  { ..., output_format: "pdf" }
    → 发票组装配路径（output_format=="pdf"）
        → 组内每份单据 build_preview → pdf_renderer.render_pdf([preview1, preview2], output_path)
          （INVOICE+PL / CI+RO_PL 合并为一份多节 PDF，对齐现有"一个 workbook 两个 sheet"的 bundle 行为）
    → GenerationResult(status, output_file=".../SK-RO-INVOICE-....pdf")
  → GET /api/download?path=...
```

**无新增端点**。两个导出端点复用，通过 `output_format` 字段区分输出格式。

## 文件改动清单

### 新增

| 文件 | 说明 |
|------|------|
| `packages/ro_generator/src/ro_generator/pdf_renderer.py` | PDF 渲染器，从 `list[DocumentPreview]` 生成单份（可多节）PDF |

### 修改

| 文件 | 变更 |
|------|------|
| `packages/ro_generator/src/ro_generator/models.py` | `DocumentRequest.output_format` 扩展为 `Literal["xlsx", "zip", "pdf"]` |
| `packages/ro_generator/src/ro_generator/generator.py` | `_generate_one()` 及发票组装配路径：`output_format == "pdf"` 时调用 `build_preview()` + `pdf_renderer.render_pdf()`，文件名后缀 `.pdf`；返回值仍为标准 `GenerationResult`（**不新增字段**） |
| `packages/ro_generator/pyproject.toml` | 新增依赖 `reportlab>=4.0` |
| `packages/ro_workbench_api/src/ro_workbench_api/app.py` | ①`DryRunRequest` / 发票组导出请求模型新增 `output_format: Literal["xlsx", "pdf"] = "xlsx"`；②`export_documents` / `export_invoice_group` 停止硬编码 `output_format="xlsx"`，改为透传 `req.output_format`（**无 if 分派**）；③下载端点 media type 增加 `application/pdf` |
| `frontend/src/components/preview/PreviewScreen.vue` | 新增"导出 PDF"按钮 |
| `frontend/src/stores/workbench.ts` | 新增 `doExportPdf()` action（保留 `previewScope` 的 `po`/`invoice` 分叉，与 `doExport()` 同构） |

> **CLI 无需改动即获得能力**：`ro-generate` 走同一个 `generate()`，`output_format` 已是 `DocumentRequest` 字段。如需暴露 flag 属另一迭代，不在本范围。

## 核心模块：pdf_renderer.py

```python
def render_pdf(previews: list[DocumentPreview], output_path: Path) -> PdfRenderResult:
    """把一份或多份预览渲染为单个 PDF（多份 = 多节/多页）。"""
    ...
```

### 输入

- `previews`：`build_preview()` 产出的结构化预览数据列表。单份单据传长度 1；发票组 bundle（INVOICE+PL / CI+RO_PL）传长度 2，顺序即页面顺序。每个 `DocumentPreview` 含 `title`、`seller`/`seller_info`、`to_label`、`terms`、`layout`、`column_labels`、`lines`、`totals`、`notes`——与前端预览页同源。

### 输出

- `PdfRenderResult(output_path=Path(...))`

### 页面布局（reportlab Platypus）

每份 preview 渲染为一节，按 `DocumentPreview` 结构逐块展开：

1. **标题区**：`preview.title`，辅以 `preview.seller` / `preview.seller_info`。
2. **头信息区**：按 `preview.layout` 的 `top.left` / `top.center` / `top.right` 区块**还原左右分栏**（注意：`layout` 是二维区域结构，不能简单线性平铺成一列 key-value，否则版面与预览页不符），配合 `preview.to_label` / `preview.terms`。
3. **明细行表格**：`preview.column_labels` 为表头，`preview.lines` 为数据行，列宽按列数自动适配 A4 竖/横版。
4. **合计区**：`preview.totals` 标准合计字段（quantity/amount/net_weight/gross_weight/cbm）右对齐。
5. **备注区**：`preview.notes` 逐行渲染（如 `PACKED IN n CTNS`）。

金额使用 `preview.totals` 中已格式化的值，**不做重算或业务逻辑**。多份 preview 之间用分页符分隔。

## 后端接口改动

### 请求模型新增字段

```python
# DryRunRequest（PO 导出）与发票组导出请求模型
output_format: Literal["xlsx", "pdf"] = "xlsx"
```

字段名与核心包 `DocumentRequest.output_format` 一致，直接映射，不引入平行概念。

### 导出端点逻辑（薄壳，无业务 if）

```python
# export_documents / export_invoice_group
request = _build_document_request(..., output_format=req.output_format)  # 透传
result = generate(request)          # 或发票组装配入口
return _result_to_dict(result)      # 无需改动，GenerationResult 结构不变
```

格式分派全部发生在核心包内部，路由处理器不含格式判断。

### 下载端点

```python
media_type = (
    "application/zip" if suffix == ".zip"
    else "application/pdf" if suffix == ".pdf"
    else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
```

（现有 session 目录路径穿越防护保持不变。）

### 文件命名

沿用现有 `packager.py` 命名规则，后缀改为 `.pdf`。例如：
- `GS-RO-INVOICE-4500030844-2601.pdf`
- `SK-RO-INVOICE-4500030844-2601.pdf`（发票组 bundle，单份 PDF 含 INVOICE + PL 两节）
- `GS-RO-PI-4500030844.pdf`

## 前端改动

### PreviewScreen.vue

在现有"导出 {docLabel}"按钮右侧新增按钮：

```
[导出 INVOICE (.xlsx)]  [导出 PDF]  [查看字段来源]
```

- 同样受 `disabled`（`!hasData || exporting || previewLoading`）控制。
- `@click="wb.doExportPdf()"`。

### workbench.ts

```typescript
async function doExportPdf() {
  // 与 doExport() 完全同构，包括 previewScope 的 po / invoice 分叉：
  //   - previewScope === "invoice" → api.exportInvoiceGroup(key, seller, docs, { output_format: "pdf" })
  //   - previewScope === "po"      → exportOneGroup({ ..., output_format: "pdf" })
  // 下载文件名后缀 .pdf
}
```

> 关键：**必须复用 `doExport()` 的 `previewScope` 分支**，否则 SK/YM 发票组预览下点"导出 PDF"会走错端点。

### api.ts

`exportDocuments()` / `exportInvoiceGroup()` 请求体已可接受额外字段，透传 `output_format` 即可，无需改签名。

## 测试

| 层级 | 测试内容 |
|------|----------|
| 单元 | `test_pdf_renderer.py`：单份 preview → 单节 PDF、多份 preview → 多节 PDF、输出路径存在、无异常、基本内容断言 |
| 单元 | `test_generator.py`：`generate()` 在 `output_format=="pdf"` 下返回 `.pdf` 的 `output_file` 且**不产生 .xlsx**；发票组路径 pdf 分派正确 |
| 集成 | `test_app.py`：`/api/po/{po}/export` 与 `/api/invoice/{key}/export` 在 `output_format=pdf` 下返回 pdf 路径；`/api/download` 对 `.pdf` 返回 `application/pdf` |
| E2E | `workbench.spec.ts`：PO 作用域与 invoice 作用域各一个场景，预览页下载 PDF，验证响应为 PDF |

## 依赖与打包

- `reportlab` 为纯 Python 包（无 C 扩展），PyInstaller 可直接打包。
- 预估 PDF 渲染器约 250-350 行 Python（含发票组多节布局）。
