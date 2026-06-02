# RO 单据工作台

把 `RO DATA BASE.xlsx` 中的 PO 数据装配为 PI、PO、Invoice、Packing List 四类单据。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（Python 包管理）
- Node.js 20+ + [pnpm](https://pnpm.io/) 9+（前端）
- macOS / Windows / Linux

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

### 1. 打开 base 文件

点击顶部栏文件名"点击打开 base 文件…"，在弹出的对话框中输入 `.xlsx` 文件的绝对路径：

```
/Users/max/projects/ro-reader/tests/fixtures/synthetic_base.xlsx
```

### 2. 浏览 PO 列表

左侧栏显示所有 PO，按状态着色：

- **● 绿色（就绪）**：全部字段齐备，可立即导出
- **◐ 黄色（部分）**：部分单据可导出，但 Invoice/PL 缺 INV# 等
- **● 红色（阻断）**：有阻断错误（缺 SAP、SAP 不在 DATA BASE 等）

支持搜索框筛选 PO 号和下拉按状态过滤。

### 3. 查看和编辑数据

点击某个 PO，中央主区展示该 PO 的所有行数据（类似 Excel 表格）。

- **双击单元格**进入编辑模式，输入新值后按 **Enter** 提交
- 修改会**直接写回 base 文件**，预览即时刷新
- 必填字段（SAP Number、FINALQTY 等）为空时显示**红色边框 + 粉色背景**

### 4. 选择链段和月份

主区下半部：

- **链段选择器**：横向胶囊按钮显示贸易链路（SK→GS PTE、GS PTE→EMAX PTE 等），点击切换定价视角
- **月份选择器**：显示该 PO 有出货数据的月份，点击切换 Invoice/PL 的取数月份。PI 和 PO 不受月份影响

### 5. 预览单据

右侧预览栏显示当前选中链段 + 月份的 Invoice 实时预览。顶部四个标签可切换 PI / PO / Invoice / PL。

- 预览由 SheetJS 渲染，悬停单元格时右下角显示源字段溯源信息
- 缺字段位置显示红色占位符

### 6. 导出

点击顶部栏右侧"导出 ⌘E"按钮，文件写入后端临时目录，状态栏显示导出文件名。

## 命令行工具

`ro-generate` 不依赖工作台 UI，可直接在终端使用。

```bash
# 装配单张 Invoice（GS PTE → EMAX PTE 段，2026 年 1 月）
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs invoice \
  --seller "GS PTE" \
  --buyer "EMAX PTE" \
  --invoice-month 2603 \
  --output-dir ./outputs

# 四类单据全部装配
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs pi,po,invoice,pl \
  --invoice-month 2603 \
  --output-format zip \
  --output-dir ./outputs \
  --json
```

### CLI 参数

| 参数 | 说明 |
|---|---|
| `--base` | base `.xlsx` 文件路径 |
| `--po` | PO 号 |
| `--docs` | 单据类型，逗号分隔：`pi,po,invoice,pl` |
| `--seller` / `--buyer` | 链段卖方/买方（GS PTE / EMAX PTE / SK/YM / PF） |
| `--invoice-month` | 月份代码（`2601`–`2612`），Invoice/PL 必填或自动推断 |
| `--invoice-no` | 指定发票号（多 INV# 歧义时使用） |
| `--output-format` | `xlsx`（默认）或 `zip`（多文件时打包） |
| `--output-dir` | 输出目录，默认 `./outputs` |
| `--on-conflict` | `overwrite`（默认）/ `rename` / `abort` |
| `--input` | 从 JSON 文件读取完整请求 |
| `--json` | stdout 只输出 JSON，日志走 stderr |

### 退出码

| 码 | 含义 |
|---:|---|
| 0 | 装配成功，文件已生成 |
| 1 | 阻断错误（缺 SAP、INV# 等），未生成文件 |
| 2 | CLI 参数错误（缺必填参数、unknown flag 等） |
| 3 | 需补充信息（多月出货需指定月份、多 INV# 需指定发票号等） |

### request.json 模式

适合脚本和自动化调用：

```json
{
  "base_file": "/path/to/base.xlsx",
  "po_no": "4500099999",
  "documents": ["PI", "INVOICE"],
  "seller": "GS PTE",
  "buyer": "EMAX PTE",
  "invoice_month": "2603",
  "output_format": "zip",
  "output_dir": "./outputs"
}
```

```bash
uv run ro-generate --input request.json --json
```

`--json` 模式下 stdout 输出结构化 JSON，`status` 字段为 `success` / `error` / `needs_input`。CLI 命令行参数会覆盖 JSON 中的同名字段。

## 构建桌面应用（macOS）

```bash
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
# 产物：dist/RO Workbench.app（~24 MB）
```

首次打开可能被 Gatekeeper 拦截：右键 → 打开，或系统设置 → 隐私与安全性 → 仍要打开。

## 架构

```
ro_generator (核心包) → CLI | FastAPI 后端 → Vue 3 前端 → PyInstaller 启动器
```

**业务规则只在核心包**，CLI、后端、前端都是薄壳。目录结构：

```
packages/
  ro_generator/         核心包（Python, 261 tests）
  ro_workbench_api/     工作台后端（FastAPI, 6 endpoints）
  ro_workbench_launcher/  启动器（PyInstaller 打包）
frontend/               Vue 3 + Pinia + SheetJS（Vite 构建）
templates/              14 个 .xlsx 模板 + 14 份 YAML mapping
tests/fixtures/         合成 base 文件
docs/                   产品方案 / UI 设计 / 实施指南
```

## 模板矩阵

| 主体 | PI | PO | Invoice | PL |
|---|:-:|:-:|:-:|:-:|
| GS PTE | ✅ | ✅ | ✅ | ✅ |
| EMAX PTE | ✅ | ✅ | ✅ | ✅ |
| SK/YM | ✅ | ❌ | ✅ | ✅ |

SK / YM 主体没有 PO 模板，请求 `--docs po --seller SK/YM` 时返回阻断错误。

## 测试

```bash
uv run pytest                                          # 全部 261 项
uv run pytest packages/ro_generator/tests/test_resolver.py -v
cd frontend && pnpm run test:e2e                       # Playwright E2E（5 场景）
```

## 技术栈

Python 3.11+ / openpyxl / FastAPI / Vue 3 + TypeScript / Pinia / SheetJS / PyInstaller
