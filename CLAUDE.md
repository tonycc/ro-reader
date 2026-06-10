# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 出现问题时，先分析问题原因并在回复时输出问题原因

## 仓库当前状态

四个 Phase 全部完成，项目可运行。

```text
packages/
  ro_generator/        核心包（Python）：13 模块，261 测试，92% 覆盖
  ro_workbench_api/    工作台后端（FastAPI）：10 API 端点 + 2 静态资源路由
  ro_workbench_launcher/  启动器（PyInstaller .app 24 MB）
frontend/              Vue 3 + TypeScript + Pinia（Vite 构建）
templates/             14 个 .xlsx 模板 + 14 份 YAML mapping
tests/fixtures/        合成 base 文件生成脚本
```

- `docs/product/ro-document-generator-product-plan.md`：**产品方案**（最权威，所有产品决策以此为准）。
- `docs/development/ro-document-workbench-ui-design.md`：**前端 UI 与交互设计**。
- `docs/development/implementation-guide.md`：**工程实施指南**（含各 Phase 细粒度任务清单与状态）。
- `docs/development/unified-field-mapping-guide.md`：**统一字段映射与配置指南**（同时面向业务与开发/agent：覆盖字段来源链路、四类单据口径、预览配置规范、模板 mapping 以及修改决策表）。
- `docs/development/phase-0-spike-results.md`：Phase 0 spike 结论。

> 当 docs 文件之间冲突时，优先级为：产品方案 > UI 设计 > 实施指南 > CLAUDE.md。

## 项目目标

构建 **RO 单据工作台**（`RO Document Workbench`）：把"准备数据"和"装配单据"合并成一个连续的视觉操作。用户在工作台里浏览 PO、补齐字段、看到四类单据（PI / PO / Invoice / PL）的实时预览，并在确认后导出 Excel。

工具是**装配器**而非"生成器"：发票号、工厂文件号、出厂日期等业务编号必须由人工在工作台里录入，工具只读取、校验、装配、呈现。

MVP 形态为**本地启动器 + 浏览器**：双击 PyInstaller 打包的可执行文件，启动器拉起本地 FastAPI server 并自动开浏览器。所有数据 100% 在用户机器上处理，离线可用。

> Agent / MCP 集成已从 MVP 中移除，列入产品方案 §16 的"后续路线"。当前阶段**不实现** Hermes Agent 相关功能，但架构上保留扩展通路。

## 五件套架构

```text
┌────────────────────────────────────────────────────────────┐
│  ro_generator（核心包，Python）                              │
│  models / errors / schema / workbook_reader / validator    │
│  resolver / document_model / template_mapping              │
│  renderer / packager / generator / cli / source_index      │
│  —— 业务规则只写在这里 ——                                   │
└────────────────────────────────────────────────────────────┘
              ▲                          ▲
              │                          │
       ┌──────┴──────┐            ┌──────┴──────┐
       │     CLI     │            │  工作台后端  │
       │ ro-generate │            │  FastAPI    │
       └─────────────┘            └──────┬──────┘
                                         │
                                  ┌──────┴───────┐
                                  │   前端 UI    │
                                  │   Vue 3      │
                                  └──────┬───────┘
                                         │
                                  ┌──────┴──────┐
                                  │   启动器    │
                                  │ PyInstaller │
                                  │(内嵌FastAPI)│
                                  └─────────────┘
```

**架构纪律**（产品方案 §7.1）：

- **业务规则只写在核心包里**。CLI、工作台后端、前端 UI、启动器都是薄壳，不允许写业务判断、校验逻辑或装配逻辑。
- 工作台后端是核心包的**网络包装层**，只负责 HTTP/IPC 协议、session 管理、前端事件路由。"路由处理器里的 if 业务条件"是越界，应该重构进核心包。
- CLI 与工作台后端共用核心包入口，作为这条架构纪律的活体校验。
- 这条纪律保证未来扩展 MCP server / Agent tools 时只需新增壳层，不需改核心包。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 核心包 | Python 3.11+ / uv workspace |
| Excel 读写 | `openpyxl`（`.xls` 转 `.xlsx` 用 `xlrd<2`，一次性转换后不再依赖） |
| 配置 | `PyYAML`（模板 mapping） |
| CLI | `argparse`（薄包装，业务逻辑都在核心包） |
| 工作台后端 | FastAPI + uvicorn |
| 启动器 | PyInstaller 打包（内嵌 FastAPI 后台线程）+ pystray 托盘 |
| 前端框架 | **Vue 3 + TypeScript**（不使用 React） |
| 前端构建 | Vite |
| 前端样式 | CSS 变量 token 文件（无 CSS-in-JS，无 Tailwind） |
| 前端状态 | Pinia |
| 数据视图 | 自研 `<table>` + inline 编辑（未引入重型 grid 库） |
| 预览渲染 | 后端 openpyxl 渲染后通过结构化 JSON payload 传给前端展示（header + table layout），支持悬停溯源 |
| 测试 | pytest（后端） / Playwright（E2E，5 场景） |

**禁用清单**：

- 设计系统库（Element Plus / Naive UI / Vuetify / Ant Design Vue）：与定制视觉冲突。
- CSS-in-JS 运行时方案：本工作台对包体大小敏感。
- Vuex 4：使用 Pinia 已足够。
- React、Tailwind、styled-components：明确不在技术栈内。

## 关键设计决策

- **模板单元格位置写在 YAML，不写在代码里**。每个主体 × 单据类型一份 mapping（如 `templates/gs/mappings/invoice.yaml`），描述表头单元格、行起始位置、样式参考行、可选表头保护行、列字母、合计单元格。模板版式变化只改 YAML。
- **领域模型与 Excel 解耦**。`Product` / `OrderLine` / `DocumentModel` 是冻结 dataclass，金额用 `Decimal`，日期用 `date`。
- **校验三类输出**：`blocking_errors`（阻断装配）、`warnings`（带 `severity: high | low`）、`missing_inputs`（信息不足，UI 直接呈现候选）。
- **公式回退**：当 `data_only` 读到 None 时核心包按公式现算，并在数据视图中以橙色边框标记。
- **双向溯源**：核心包构建 `SourceIndex`，前端可点文档预览定位到源字段，反之亦然。
- **openpyxl `insert_rows` 陷阱**：该函数只平移单元格内容和公式，**不平移 `row_dimensions`**。不修复会导致插入行之后所有行的高度错位。修复方法：调用 `insert_rows` 之前，倒序把 `row_dimensions` 的行号 += 1（详见 `renderer._insert_styled_row` 和 Phase 0 Spike A 结论）。

## 源数据结构（`RO DATA BASE.xlsx`）

两张必需 sheet，**表头在第 4 行，数据从第 5 行开始**。

### `DATA BASE`（产品主数据，~248 行 × 28 列）

按 `SAP` 唯一识别。同一产品在不同主体（SK/YM、GS PTE、EMAX PTE）下有不同 FOB 单价列。**单价选择由"贸易链段 + Category"两个维度决定**：

| 链段 `(seller → buyer)` | 价格列前缀 |
| --- | --- |
| SK / YM → GS PTE | `SK/YM ... FOB` |
| GS PTE → EMAX PTE | `GS PTE ... FOB` |
| EMAX PTE → PF | `EMAX PTE ... FOB` |

类别：`Category = 1` → combo / `2` → rod / `3` → reel。

包装/物流字段：`inner case value`、`round value`（外箱装箱数）、`N/W`、`G/W`、`L`/`W`/`H`、`CBM`、`包装`、`品牌`、`RFID`、`主件编号`。

### `PO record`（订单和出货计算）

通过 `SAP Number` 引用 `DATA BASE`。关键字段组：

- 订单识别：`SHIP TO`、`PO NO.`、`ITEM LINE#`、`SAP Number`
- 数量价格：`FINALQTY`、`SK/YM USD FOB`、`GS PTE FOB`、`EMAX PTE`、`SUBTOTAL`
- 装箱：`CTNS`、`N/W`、`G/W`、`L`/`W`/`H`、`TOTAL CBM`、`外箱`
- 发票：`INV#`、`FACTORY DOC NO.`
- **月度出货列 `2601` 到 `2612`** = 2026 年 1–12 月的发货数量
- 月度发票金额：`GS-SK/YM INV-*`、`EMAX-GS INV-*`、`PF-EMAX INV-*`

注意：表头可能含换行和多余空格（如 `"GS PTE \nFOB "`），`schema.normalize_header()` 必须先规范化再匹配。

## 业务规则

- `SUBTOTAL = quantity * unit_price`
- `CTNS = quantity / 外箱`（当前实现中 `quantity` 取 `客户PO.Order Quantity`）
- `TOTAL CBM = L * W * H / 1000000 * CTNS`
- `BALANCE QTY = FINALQTY - 各月出货数量合计`
- **PI/PO 使用 `客户PO.Order Quantity`；Invoice/PL 按 `invoice_month` 用月度出货数量**。
- **MVP 仅支持 USD**。
- 缺失关键字段（INV#、FACTORY DOC NO.、SAP、价格等）必须报阻断错误，**绝不自动编造**。
- SK / YM 主体没有 PO 模板，请求生成 PO 时返回阻断错误。

## 模板矩阵

| 主体 | PI | PO | Invoice | PL |
| --- | :-: | :-: | :-: | :-: |
| GS | ✅ | ✅ | ✅ | ✅ |
| EMAX | ✅ | ✅ | ✅ | ✅ |
| SK | ✅ | ❌ | ✅ | ✅ |
| YM | ✅ | ❌ | ✅ | ✅ |

14/14 mapping 全部通过 `load_template_mapping` 校验。

## 文件命名规则

| 单据类型 | 命名模板 |
| --- | --- |
| PI | `<SELLER>-RO-PI-<PO>.xlsx` |
| PO | `<SELLER>-RO-PO-<PO>.xlsx` |
| Invoice | `<SELLER>-RO-INVOICE-<PO>-<MONTH>.xlsx` |
| PL | `<SELLER>-RO-PL-<PO>-<MONTH>.xlsx` |

zip：`RO-<PO>-<MONTH>.zip`。`<MONTH>` 已含年份信息（`2601` = 2026-01）。

工作台默认导出策略：写入 `outputs/<YYYYMMDD-HHMMSS>/` 子目录，避免覆盖。CLI 保留 `--on-conflict overwrite|rename|abort` 选项。

## CLI 契约

`ro-generate` 用于命令行装配、自动化脚本、开发调试。

退出码（**稳定，不要随意变**）：

| 状态 | 退出码 |
| --- | ---: |
| `success` | `0` |
| `error`（阻断错误） | `1` |
| 参数错误 | `2` |
| `needs_input` | `3` |

`--json` 模式下 **stdout 只输出 JSON，所有日志/警告写 stderr**。

## 开发命令

```bash
# === 核心包 ===
uv sync --all-packages                          # 安装所有依赖
uv run pytest                                   # 全部 Python 测试（261 项）
uv run pytest packages/ro_generator/tests/test_resolver.py -v
uv run pytest packages/ro_generator/tests/test_resolver.py::test_known_po_resolves -v

# CLI 端到端（用合成 fixture）
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx --po 4500099999 \
  --docs invoice --seller "GS PTE" --buyer "EMAX PTE" \
  --invoice-month 2603 --output-dir /tmp/out --json

# === 工作台后端 ===
uv run uvicorn ro_workbench_api.app:app --reload --host 127.0.0.1 --port 54321

# === 前端（在 frontend/ 子目录执行） ===
pnpm install
pnpm run dev                                    # Vite 开发服务器 :5173
pnpm run build                                  # vue-tsc + vite build → dist/
pnpm run test:e2e                               # Playwright E2E（5 场景）

# === 启动器（macOS） ===
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
# .app 产物在 dist/RO Workbench.app（24 MB）

# === Lint ===
uv run ruff check . && uv run ruff format --check . && uv run mypy packages
```

## 工作台前端架构

工作台采用**三 tab 顺序工作流**（取代早期三栏 IDE 布局）：

```text
┌──────────────────────────────────────────────────────┐
│  TopBar：base 文件路径 │ 撤销/重做 │ 导出             │
├──────────┬───────────────────────────────────────────┤
│          │  数据检查 │ 单据预览 │ 导出确认             │
│  PO 队列 │  ───────────────────────────────────       │
│  （左侧） │  选中 tab 对应内容区                       │
│          │                                           │
│  多选    │  - 数据检查：PO 行表格 + inline 编辑       │
│  搜索    │  - 单据预览：链段选择 + header/tables      │
│  状态筛选 │  - 导出确认：选单据类型 → 下载            │
├──────────┴───────────────────────────────────────────┤
│  StatusBar：PO 状态 │ 阻断/警告数                      │
└──────────────────────────────────────────────────────┘
```

组件对应关系：

- `QueueSidebar.vue` — PO 队列（搜索、筛选、多选）
- `DataCheckScreen.vue` — "数据检查" tab（类 Excel 表格 + inline 编辑）
- `PreviewScreen.vue` — "单据预览" tab（链段胶囊、doc type 切换、header/table 分区域渲染、悬停溯源）
- `ExportScreen.vue` — "导出确认" tab（勾选单据类型、触发下载）
- `TopBar.vue` / `StatusBar.vue` — 顶部栏/底部状态栏

预览数据由后端 `POST /api/po/{po_no}/preview` 返回结构化 `PreviewPayload` JSON（含 `layout.top` / `layout.info` 区、`column_labels`、`lines`、`totals`、`notes`、`source_entries`），前端按区域渲染，不再直接加载 xlsx 二进制。

## 工作台 API 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/check-path` | 校验文件路径是否存在 |
| `POST` | `/api/session/open` | 打开 base 文件，返回 session_id + PO 列表 |
| `GET` | `/api/po/{po_no}` | 获取 PO 数据行（headers + rows） |
| `POST` | `/api/po/{po_no}/dry-run` | 干跑装配（不写入磁盘） |
| `POST` | `/api/po/{po_no}/preview` | 获取结构化预览 payload |
| `POST` | `/api/po/{po_no}/edit` | 编辑单元格并写回 base 文件 |
| `POST` | `/api/export` | 导出单据到磁盘 |
| `GET` | `/api/download` | 下载导出文件 |
| `POST` | `/api/session/close` | 关闭 session |

Session 通过 `X-Session-Id` header 传递（前端 Pinia store 自动管理）。

## 测试 fixture

- 黄金回归 PO：**`4500030844`**。
- 合成 fixture 路径：`tests/fixtures/synthetic_base.xlsx`（由 `tests/fixtures/generate_synthetic_base.py` 生成，已加入 `.gitignore`）。
- 合成 fixture 覆盖：combo / rod / reel 三种类别、跨多月份（2601/2602）、多 INV#、缺 SAP 阻断、SK/YM 请求 PO 阻断。
- 真实 `RO DATA BASE.xlsx` 未入库（`.gitignore` 已排除），待与团队确认数据敏感性。

## 模板处理注意

- `.xls` 老格式已通过 `xlrd` 一次性转换为 `.xlsx`（EMAX Invoice、EMAX PL），原始 `.xls` 保留在 `templates/_legacy_xls/` 留底。业务方今后只在 `.xlsx` 模板上修改。
- 更新其他 mapping 时，应参考当前成熟 `PI` mapping 沉淀出的规范格式；权威说明见 `docs/development/unified-field-mapping-guide.md`，示例起点见 `templates/_examples/`。但**不能**把某一份真实业务 `pi.yaml` 逐字复制成其它单据或主体的 mapping；必须按单据类型、主体信息和模板结构保留边界。
- 对 mapping 做规范化收敛时，应主动清理无效空配置和旧结构残留，例如空 `to_label`、旧 `terms: {}`、已不参与布局或渲染的占位字段；不要保留“虽然不报错但没有实际作用”的配置噪音。
- 如果 `start_row` 上方存在真实表格表头，mapping 中应显式声明 `table_header_row`；不要再依赖渲染器启发式猜测哪一行是表头。
- `style_source_row` 必须指向真实明细样式行。renderer 会先用它统一预留明细区样式，再写值、插入新行，避免模板脏格式把单价/数量显示成日期等错误格式。
- 当 PO 行数超过模板默认区域时，renderer 必须**插入新行并复制上一行样式**（先倒序平移 `row_dimensions` 再 `insert_rows`——这是 openpyxl 的已知陷阱，Phase 0 Spike A 已验证），返回 `severity: high` warning。
- 优先写入最终计算值，公式只保留必要的本表内引用（如 `=E18*F18`），避免不同 Excel 环境重算行为不一致。
- mapping 文件必须含 `template_version` 字段，加载时校验所有引用单元格在模板中存在。
- 模板文件较小（~20-80 KB/个），随 git 跟踪。`templates/_legacy_xls/` 中的原 `.xls` 不再参与构建。

## 实施顺序（产品方案 §16）

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 0 | 三个 spike：模板样式保留、预览渲染组件选型、启动器打包链路 | ✅ 完成（Spike A/B Phase 0 通过；Spike C Phase 3 完成） |
| 1 | 核心包 + CLI（先做 Invoice 一种单据） | ✅ 完成（261 测试，覆盖率 92%） |
| 2 | 四类单据 + GS/EMAX/SK/YM 多主体模板 + 模板预览 CLI | ✅ 完成（14 份 mapping，四类单据 × 三链段） |
| 3 | 工作台 MVP（FastAPI + Vue + PyInstaller 启动器，含完整 UI） | ✅ 完成（前后端联调通过，.app 24 MB） |
| 4 | 加固（回归测试、性能、模板版本管理） | ✅ 完成（E2E 5 场景、261 测试、README） |

> Phase 0 spike 结论见 [`docs/development/phase-0-spike-results.md`](docs/development/phase-0-spike-results.md)。

### 文档增量规则

**详细任务清单按 Phase 增量编写，不一次性规划全部**：

- 当前 Phase（含本 Phase）和**下一 Phase** 才允许有细粒度任务清单。
- 后续 Phase 在产品方案 §16 中只有目标级描述，**禁止预先写出 Task 1 / 2 / 3 这种粒度的清单**。
- Phase N 完成后，再追加 Phase N+1 的细粒度任务清单到实施指南中。

**理由**：每个 Phase 的输出（spike 结论、API 契约、模板兼容性结果）都可能改变后续 Phase 的具体路径。提前写细节会在产品方向调整时全部作废，刚删除的两份旧文档就是反例。

**例外**：跨 Phase 的架构纪律、业务规则、文件命名、技术栈选型等已确定的内容可以在产品方案、CLAUDE.md、UI 设计文档中提前固化。规则的边界是"是否依赖前一 Phase 的实际产出来决定"——依赖则等，不依赖则可以先写。
