# RO 单据工作台

把 `RO DATA BASE.xlsx` 中的 PO 数据装配为 PI、PO、Invoice、Packing List 四类单据，并支持导出 Excel 和 PDF。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（Python 包管理）
- Node.js 20+ + [pnpm](https://pnpm.io/) 9+（前端）
- macOS / Windows / Linux
- **导出 PDF 需预装 [LibreOffice](https://www.libreoffice.org/)**。PDF 由"渲染 xlsx 模板 → LibreOffice 无头转换"生成，以保证版式与 Excel 模板逐格一致；未安装时 PDF 导出返回明确的阻断错误（`PDF_CONVERTER_UNAVAILABLE`），Excel 导出不受影响。若 `soffice` 不在标准位置，可用环境变量 `RO_SOFFICE_PATH` 指定其路径。

## 快速启动（开发模式）

```bash
# 1. 安装依赖
uv sync --all-packages
cd frontend && pnpm install && cd ..

# 2. 生成测试用的合成 base 文件（如果没有真实 RO DATA BASE.xlsx）
uv run python tests/fixtures/generate_synthetic_base.py
# → 生成 tests/fixtures/synthetic_base.xlsx

# 3. 启动后端（终端 1）
uv run uvicorn ro_workbench_api.app:app --reload --host 127.0.0.1 --port 54321

# 4. 启动前端（终端 2）
cd frontend && pnpm run dev
# → 浏览器打开 http://localhost:5173
```

## 工作台使用流程

### 三 Tab 工作流

```text
┌────────────────────────────────────────────────────┐
│  TopBar：base 文件路径 │ 撤销/重做 │ 导出           │
├──────────┬─────────────────────────────────────────┤
│          │  数据检查 │ 单据预览 │ 导出确认           │
│  PO 队列 │  ─────────────────────────────────       │
│  （左侧） │  选中 tab 对应内容区                     │
│          │                                         │
│  多选    │  - 数据检查：PO 行表格 + inline 编辑     │
│  搜索    │  - 单据预览：链段选择 + header/tables    │
│  状态筛选 │  - 导出确认：选单据类型 → 下载          │
├──────────┴─────────────────────────────────────────┤
│  StatusBar：PO 状态 │ 阻断/警告数                    │
└────────────────────────────────────────────────────┘
```

### 1. 打开 base 文件

点击顶部栏文件名"点击打开 base 文件…"，在弹出的对话框中输入 `.xlsx` 文件的绝对路径。

### 2. 浏览 PO 列表

左侧栏显示所有 PO，按状态着色：

- **● 绿色（就绪）**：全部字段齐备，可立即导出
- **◐ 黄色（部分）**：部分单据可导出，但 Invoice/PL 缺 INV# 等
- **● 红色（阻断）**：有阻断错误（缺 SAP、SAP 不在 DATA BASE 等）

支持搜索框筛选 PO 号和下拉按状态过滤。

### 3. 查看和编辑数据（数据检查 Tab）

- **PO 数据检查**：展示选中 PO 的所有行数据（类 Excel 表格），双击单元格进入编辑模式，修改直接写回 base 文件
- **Invoice 数据检查**：展示按 `(PO, 月份, 链段)` 分组的发票数据，以只读方式查看出货行及校验问题

### 4. 预览单据（单据预览 Tab）

按 PO 或 Invoice 分组预览单据：

- **PO 预览**：选择链段和单据类型，查看 PI/PO 的结构化预览（header + table + totals + notes 区域）
- **Invoice 预览**：按 `(PO, 月份, 链段)` 分组查看 Invoice + PL 的合并预览
- 悬停单元格可查看源字段溯源信息

### 5. 导出（导出确认 Tab）

- 勾选需要导出的单据类型（PI / PO / Invoice / PL）；SK / YM 主体下 PO 自动禁用
- 可选择导出格式：**Excel** 或 **PDF**（二者可以同时勾选）
- Invoice + PL 同时导出时写入同一个 workbook 的两个 sheet
- PDF 导出由 LibreOffice 无头转换生成，保证与 Excel 模板像素级一致
- 未安装 LibreOffice 时 PDF 选项提示用户安装

## 核心架构

### 装配流水线

```text
RO DATA BASE.xlsx
     │
     ▼
  WorkbookReader ─── 打开文件，表头规范化（去掉 \n 和多余空格），按行读为 dict
     │
     ▼
  Validator ─── 校验 sheet 和必需表头是否存在（缺失 → blocking_error）
     │
     ▼
  Resolver ─── 按 PO 号筛选行，SAP 关联产品主数据，按链段读取价格列
     │          公式列（CTNS / TOTAL CBM）读到 None 时按公式现算并产生 warning
     │
     ▼
  DocumentModel ─── 构建四类单据的视图模型（DocumentLine 列表 + 合计）
     │              PI/PO 使用客户PO.Order Quantity；Invoice/PL 按 invoice_month 切片
     │
     ▼
  TemplateMapping ─── 加载 YAML 映射，校验所有引用单元格在模板中存在
     │
     ▼
  Renderer ─── 写入 Excel 模板；超行时插入新行并复制样式
     │          openpyxl 陷阱：insert_rows() 不平移 row_dimensions，须先手动处理
     │
     ├──→ 输出 .xlsx / .zip
     │
     └──→ pdf_convert ─── LibreOffice 无头转换 → 输出 .pdf（像素级还原模板版式）
```

### 模板与 YAML 映射

12 个 `.xlsx` 模板每个配一份 YAML mapping，描述"哪个业务字段写到哪个单元格"：

```yaml
# 示例：templates/gs/mappings/invoice.yaml
document: invoice
template_version: "v1"
template: templates/gs/invoice&pl.xlsx
sheet: Standard Invoice format
table_header_row: 17
header:
  invoice_no: H6
  ship_to: A12
lines:
  start_row: 18
  style_source_row: 19
  columns:
    sap: D
    unit_price: E
    quantity: F
    amount: H
totals:
  quantity: F27
  amount: H27
```

模板版式变化时**只改 YAML，不改代码**。

- `style_source_row`：用于"超行插入时复制样式"和统一预留明细区样式
- `table_header_row`：当 `start_row` 上方存在真实表格表头时显式声明，不再依赖启发式猜测
- `notes`：可选，声明模板底部动态说明单元格（如 PL 的 `PACKED IN <总 CTNS> CTNS`）

### 贸易链段与定价

RO 业务涉及多段贸易链路。同一个 PO 在不同链段下使用不同的单价列：

```text
工厂 → SK/YM → GS PTE → EMAX PTE → PF（最终客户）
        ↓ SK/YM USD FOB   ↓ GS PTE FOB   ↓ EMAX PTE
```

合法的 `(seller, buyer)` 组合及选价规则：

| 链段 | 价格列 | Invoice 金额列前缀 |
| --- | --- | --- |
| SK/YM → GS PTE | `SK/YM USD FOB` | `GS-SK/YM INV-*` |
| GS PTE → EMAX PTE | `GS PTE FOB` | `EMAX-GS INV-*` |
| EMAX PTE → PF | `EMAX PTE` | `PF-EMAX INV-*` |

`SUBTOTAL = quantity × unit_price`，金额用 `Decimal` 避免浮点精度问题。

SK / YM 主体按 `PO record.CATEGORY` 判断工厂主体：

| CATEGORY | 主体 |
| --- | --- |
| `1` / `2` | YM |
| `3` | SK |

### 数量来源

| 单据 | 数量来源 |
| --- | --- |
| PI / PO | `客户PO.Order Quantity` |
| Invoice / PL | `invoice_month` 对应的月度出货数量（`2601`–`2612` 列） |

### 校验体系

三类校验输出在装配流水线的不同阶段累积：

| 类型 | 含义 | 示例 |
| --- | --- | --- |
| `blocking_errors` | 阻断装配，必须修复 | SAP 缺失、SAP 不在 DATA BASE、数量无效、INV# 缺失 |
| `warnings` | 可装配但需复核（带 `severity: high/low`） | 公式回退现算（high）、RFID 为空（low） |
| `missing_inputs` | 信息不足，需用户选择 | 多月出货需指定月份、多 INV# 需选定 |

### 公式回退

`PO record` 中的 `SUBTOTAL`、`CTNS`、`TOTAL CBM` 通常来自 Excel 公式。当保存文件的程序未缓存公式结果时，`openpyxl` 的 `data_only=True` 读到的是 `None`，装配引擎按规则现算：

- `CTNS = quantity / 外箱`
- `TOTAL CBM = L × W × H ÷ 1,000,000 × CTNS`

并在数据视图中标记橙色边框，提示用户"由工作台计算，建议在 Excel 中刷新"。

### 双向溯源

渲染时每个写到 Excel 的单元格都记录其来源（`SourceLocation`：sheet + row + field），构建 `SourceIndex`。工作台中悬停文档预览的单元格时，右下角显示源字段信息。

### PDF 导出

PDF 不通过 reportlab 重画，而是：

1. **Renderer** 把 `DocumentModel` 逐格填进 `.xlsx` 模板
2. **LibreOffice 无头模式** 将 `.xlsx` 转换为 `.pdf`

这样 PDF 与 Excel 模板的字体、列宽、行高、合并单元格、边框、logo 完全一致。约束：LibreOffice 不随应用打包，需用户预装；未检测到时返回阻断错误，绝不静默降级。

### Invoice 工作流

工作台对 Invoice/PL 采用独立的分组视角：

- **Invoice Group**：按 `(PO 号, 月份, 链段)` 组合为分组键
- **Inspection**：以只读模式展示发票出货行及校验问题
- **Preview**：在 Invoice 分组上下文中预览 Invoice + PL
- **Export**：按分组导出，支持 Excel + PDF 双格式

## 命令行工具

`ro-generate` 不依赖工作台 UI，可直接在终端使用。

```bash
# 装配单张 Invoice（GS PTE → EMAX PTE 段，2026 年 3 月）
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs invoice \
  --seller "GS PTE" \
  --buyer "EMAX PTE" \
  --invoice-month 2603 \
  --output-dir ./outputs

# 四类单据全部装配为 Excel
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs pi,po,invoice,pl \
  --invoice-month 2603 \
  --output-format zip \
  --output-dir ./outputs \
  --json

# 导出 PDF
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs invoice \
  --seller "GS PTE" \
  --buyer "EMAX PTE" \
  --invoice-month 2603 \
  --output-format pdf \
  --output-dir ./outputs
```

### CLI 参数

| 参数 | 说明 |
| --- | --- |
| `--base` | base `.xlsx` 文件路径 |
| `--po` | PO 号 |
| `--docs` | 单据类型，逗号分隔：`pi,po,invoice,pl` |
| `--seller` / `--buyer` | 链段卖方/买方（GS PTE / EMAX PTE / SK/YM / PF） |
| `--invoice-month` | 月份代码（`2601`–`2612`），Invoice/PL 必填或自动推断 |
| `--invoice-no` | 指定发票号（多 INV# 歧义时使用） |
| `--output-format` | `xlsx`（默认）、`pdf` 或 `zip`（多文件时打包） |
| `--output-dir` | 输出目录，默认 `./outputs` |
| `--on-conflict` | `overwrite`（默认）/ `rename` / `abort` |
| `--input` | 从 JSON 文件读取完整请求 |
| `--json` | stdout 只输出 JSON，日志走 stderr |

### 退出码

| 码 | 含义 |
| ---: | --- |
| 0 | 装配成功，文件已生成 |
| 1 | 阻断错误（缺 SAP、INV# 等），未生成文件 |
| 2 | CLI 参数错误（缺必填参数、unknown flag 等） |
| 3 | 需补充信息（多月出货需指定月份、多 INV# 需指定发票号等） |

### request.json 模式

```json
{
  "base_file": "/path/to/base.xlsx",
  "po_no": "4500099999",
  "documents": ["PI", "INVOICE"],
  "seller": "GS PTE",
  "buyer": "EMAX PTE",
  "invoice_month": "2603",
  "output_format": "pdf",
  "output_dir": "./outputs"
}
```

```bash
uv run ro-generate --input request.json --json
```

## 构建桌面应用（macOS）

```bash
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
# 产物：dist/RO Workbench.app（~24 MB）
```

首次打开可能被 Gatekeeper 拦截：右键 → 打开，或系统设置 → 隐私与安全性 → 仍要打开。

## 架构

```text
ro_generator (核心包) → CLI | FastAPI 后端 → Vue 3 前端 → PyInstaller 启动器
```

**业务规则只在核心包**，CLI、后端、前端都是薄壳。目录结构：

```text
packages/
  ro_generator/          核心包（Python，24 模块）
  ro_workbench_api/      工作台后端（FastAPI，15 API 端点 + 3 静态资源路由）
  ro_workbench_launcher/   启动器（PyInstaller 打包）
frontend/                Vue 3 + TypeScript + Pinia（Vite 构建）
templates/               12 个 .xlsx 模板 workbook + 18 份 YAML mapping
tests/fixtures/          合成 base 文件生成脚本
docs/                    产品方案 / UI 设计 / 实施指南
```

## 模板矩阵

| 主体 | PI | PO | Invoice | PL |
| --- | :-: | :-: | :-: | :-: |
| GS PTE | ✅ | ✅ | ✅ | ✅ |
| EMAX PTE | ✅ | ✅ | ✅ | ✅ |
| SK | ✅ | ❌ | ✅ | ✅ |
| YM | ✅ | ❌ | ✅ | ✅ |

SK / YM 主体没有 PO 模板，请求 `--docs po --seller SK` / `--seller YM` 时返回阻断错误。

## 工作台 API 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/check-path` | 校验文件路径是否存在 |
| `POST` | `/api/session/open` | 打开 base 文件，返回 session_id + PO 列表 |
| `GET` | `/api/invoices` | 获取 Invoice 分组列表 |
| `GET` | `/api/invoice/{key}/inspection` | 获取 Invoice 分组的只读出货行及校验信息 |
| `POST` | `/api/invoice/{key}/preview` | 获取 Invoice 分组的结构化预览 |
| `POST` | `/api/invoice/{key}/export` | 导出单个 Invoice 分组单据 |
| `POST` | `/api/invoice/{key}/export-batch` | 批量导出多个 Invoice 分组单据 |
| `GET` | `/api/po/{po_no}` | 获取 PO 数据行（headers + rows） |
| `GET` | `/api/po/{po_no}/customer-po` | 获取客户 PO 数据 |
| `GET` | `/api/po/{po_no}/issues` | 获取 PO 校验问题（阻断/警告/缺失） |
| `POST` | `/api/po/{po_no}/dry-run` | 干跑装配（不写入磁盘） |
| `POST` | `/api/po/{po_no}/preview` | 获取 PO 的结构化预览 payload |
| `POST` | `/api/po/{po_no}/edit` | 编辑单元格并写回 base 文件 |
| `POST` | `/api/po/{po_no}/export` | 导出单个 PO 的单据 |
| `POST` | `/api/po/{po_no}/export-batch` | 批量导出多个单据组 |
| `GET` | `/api/download` | 下载导出文件 |
| `POST` | `/api/session/close` | 关闭 session |

Session 通过 `X-Session-Id` header 传递。

## 测试

```bash
# Python 测试（~400 个）
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run pytest packages/ro_generator/tests/test_resolver.py -v

# E2E 测试（23 场景）
cd frontend && pnpm run test:e2e
```

黄金回归 PO：**`4500030844`**。合成 fixture：`tests/fixtures/synthetic_base.xlsx`。

## 技术栈

Python 3.11+ / openpyxl / FastAPI / Vue 3 + TypeScript / Pinia / Vite / Playwright / PyInstaller / LibreOffice
