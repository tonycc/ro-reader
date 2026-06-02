# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库当前状态

仓库目前**没有源代码**，只包含：

- `RO DATA BASE.xlsx`：业务源数据（产品主数据 + PO 订单）。
- 14 个 Excel 模板（`*.xls` / `*.xlsx`），按主体（EMAX/GS/SK/YM）和单据类型（PI/PO/Invoice/PL）组织。
- `docs/product/ro-document-generator-product-plan.md`：**产品方案**（最权威，所有产品决策以此为准）。
- `docs/development/ro-document-workbench-ui-design.md`：**前端 UI 与交互设计**。
- `docs/development/implementation-guide.md`：**工程实施指南**。仓库结构、工作流约定、Phase 0 spike 验收标准、当前 Phase 与下一 Phase 的细粒度任务清单。

> 当 docs 文件之间冲突时，优先级为：产品方案 > UI 设计 > 实施指南 > CLAUDE.md。

## 项目目标

构建 **RO 单据工作台**（`RO Document Workbench`）：把"准备数据"和"装配单据"合并成一个连续的视觉操作。用户在工作台里浏览 PO、补齐字段、看到四类单据（PI / PO / Invoice / PL）的实时预览，并在确认后导出 Excel。

工具是**装配器**而非"生成器"：发票号、工厂文件号、出厂日期等业务编号必须由人工在工作台里录入，工具只读取、校验、装配、呈现。

MVP 形态为**本地启动器 + 浏览器**：双击 PyInstaller 打包的可执行文件，启动器拉起本地 FastAPI server 并自动开浏览器。所有数据 100% 在用户机器上处理，离线可用。

> Agent / MCP 集成已从 MVP 中移除，列入产品方案 §16 的"后续路线"。当前阶段**不实现** Hermes Agent 相关功能，但架构上保留扩展通路。

## 五件套架构

```
┌────────────────────────────────────────────────────────────┐
│  ro_generator（核心包，Python）                              │
│  schema / validator / resolver / document_model /          │
│  template_mapping / renderer / 双向溯源索引                  │
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
                                  └─────────────┘
```

**架构纪律**（产品方案 §7.1）：

- **业务规则只写在核心包里**。CLI、工作台后端、前端 UI、启动器都是薄壳，不允许写业务判断、校验逻辑或装配逻辑。
- 工作台后端是核心包的**网络包装层**，只负责 HTTP/IPC 协议、session 管理、前端事件路由。"路由处理器里的 if 业务条件"是越界，应该重构进核心包。
- CLI 与工作台后端共用核心包入口，作为这条架构纪律的活体校验。
- 这条纪律保证未来扩展 MCP server / Agent tools 时只需新增壳层，不需改核心包。

## 技术栈

| 层 | 选型 |
|---|---|
| 核心包 | Python 3.11+ |
| Excel 读写 | `openpyxl` |
| 配置 | `PyYAML`（模板 mapping） |
| CLI | `argparse` 或 `typer` |
| 工作台后端 | FastAPI |
| 启动器 | PyInstaller 打包 + 端口探测 + 自动开浏览器 + 托盘集成 |
| 前端框架 | **Vue 3 + TypeScript**（不使用 React） |
| 前端构建 | Vite |
| 前端样式 | CSS Modules + token 文件（CSS 变量） |
| 前端状态 | Pinia |
| 数据网格 | `@tanstack/vue-table` |
| 预览组件 | SheetJS 或 Luckysheet（Phase 0 spike 选定） |
| 测试 | pytest（后端） / Vitest + Vue Test Utils（前端） / Playwright（端到端） |

**禁用清单**：

- 设计系统库（Element Plus / Naive UI / Vuetify / Ant Design Vue）：与定制视觉冲突。
- CSS-in-JS 运行时方案：本工作台对包体大小敏感。
- Vuex 4：使用 Pinia 已足够。
- React、Tailwind、styled-components：明确不在技术栈内。

## 关键设计决策

- **模板单元格位置写在 YAML，不写在代码里**。每个主体 × 单据类型一份 mapping（如 `templates/gs/mappings/invoice.yaml`），描述表头单元格、行起始位置、列字母、合计单元格。模板版式变化只改 YAML。
- **领域模型与 Excel 解耦**。`Product` / `OrderLine` / `DocumentModel` 是冻结 dataclass，金额用 `Decimal`，日期用 `date`。
- **校验三类输出**：`blocking_errors`（阻断装配）、`warnings`（带 `severity: high | low`）、`missing_inputs`（信息不足，UI 直接呈现候选）。
- **公式回退**：当 `data_only` 读到 None 时核心包按公式现算，并在数据视图中以橙色边框标记。
- **双向溯源**：核心包构建索引，前端可点文档预览定位到源字段，反之亦然。

## 源数据结构（`RO DATA BASE.xlsx`）

两张必需 sheet，**表头在第 4 行，数据从第 5 行开始**。

### `DATA BASE`（产品主数据，~248 行 × 28 列）

按 `SAP` 唯一识别。同一产品在不同主体（SK/YM、GS PTE、EMAX PTE）下有不同 FOB 单价列。**单价选择由"贸易链段 + Category"两个维度决定**：

| 链段 `(seller → buyer)` | 价格列前缀 |
|---|---|
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

- `SUBTOTAL = FINALQTY * unit_price`
- `CTNS = FINALQTY / 外箱`
- `TOTAL CBM = L * W * H / 1000000 * CTNS`
- `BALANCE QTY = FINALQTY - 各月出货数量合计`
- **PI/PO 用完整 PO 数量；Invoice/PL 按 `invoice_month` 用月度出货数量**。
- **MVP 仅支持 USD**。
- 缺失关键字段（INV#、FACTORY DOC NO.、SAP、价格等）必须报阻断错误，**绝不自动编造**。
- SK / YM 主体没有 PO 模板，请求生成 PO 时返回阻断错误。

## 模板矩阵

| 主体 | PI | PO | Invoice | PL |
|---|:-:|:-:|:-:|:-:|
| GS | ✅ | ✅ | ✅ | ✅ |
| EMAX | ✅ | ✅ | ✅ | ✅ |
| SK | ✅ | ❌ | ✅ | ✅ |
| YM | ✅ | ❌ | ✅ | ✅ |

## 文件命名规则

| 单据类型 | 命名模板 |
|---|---|
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
|---|---:|
| `success` | `0` |
| `error`（阻断错误） | `1` |
| 参数错误 | `2` |
| `needs_input` | `3` |

`--json` 模式下 **stdout 只输出 JSON，所有日志/警告写 stderr**。

## 开发命令

代码尚未实现。后续命令将分别用于核心包、工作台后端、前端：

```bash
# 核心包 + CLI（pyproject.toml 建好后）
pip install -e ".[dev]"
pytest                                          # 跑全部 Python 测试
pytest tests/test_resolver.py -v                # 单文件
pytest tests/test_resolver.py::test_known_po -v # 单用例
ro-generate --base "RO DATA BASE.xlsx" --po 4500030844 \
  --docs pi,po,invoice,pl --invoice-month 2601 --json

# 工作台后端
uvicorn ro_workbench.api:app --reload --port 0  # 0 = 端口探测

# 前端（在 frontend/ 子目录）
pnpm install
pnpm dev          # 开发服务器
pnpm test         # Vitest
pnpm e2e          # Playwright
pnpm build        # 构建静态资源，由 FastAPI serve

# 启动器（打包后）
./dist/RO\ Workbench.app   # macOS
./dist/RO\ Workbench.exe   # Windows
```

## 测试 fixture

- 黄金回归 PO：**`4500030844`**。Resolver、Document Model、Renderer、CLI、工作台 E2E 都应覆盖。
- 真实 `RO DATA BASE.xlsx` 是否能作为 fixture 提交到仓库**待与团队确认**（数据敏感性）。在确认前，测试 fixture 使用脱敏或合成的最小 workbook。
- 合成 fixture 必须覆盖：combo / rod / reel 三种类别、跨多个月份、多个 INV# 触发 `needs_input`、缺 SAP 触发阻断、SK 主体请求 PO 触发阻断。

## 模板处理注意

- `.xls`（老格式）模板 `openpyxl` 处理不稳定，**MVP 前统一手工转换为 `.xlsx`**，作为受控资产放到 `templates/<entity>/`。原 `.xls` 一并保留留底。业务方今后只在 `.xlsx` 模板上修改。
- 当 PO 行数超过模板默认区域时，renderer 必须**插入新行并复制上一行样式**，保留打印布局，并返回 `severity: high` warning。
- 优先写入最终计算值，公式只保留必要的本表内引用，避免不同 Excel 环境重算行为不一致。
- mapping 文件必须含 `template_version` 字段，加载时校验所有引用单元格在模板中存在。

## 实施顺序（产品方案 §16）

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 三个 spike：模板样式保留、预览渲染组件选型、启动器打包链路 | 🟡 实质完成（Spike A/B 通过；Spike C 推迟到 Phase 3 启动前） |
| 1 | 核心包 + CLI（先做 Invoice 一种单据） | ✅ 完成（245 测试，覆盖率 92%） |
| 2 | 四类单据 + GS/EMAX/SK/YM 多主体模板 + 模板预览 CLI | ✅ 完成（260 测试，12 份 mapping，四类单据 × 三链段） |
| 3 | 工作台 MVP（FastAPI + Vue + PyInstaller 启动器，含完整 UI） | ✅ 完成（260 测试，前后端联调通过，.app 24 MB） |
| 4 | 加固（回归测试、性能、模板版本管理） | ✅ 完成（E2E 5 场景、前端缺字段高亮、README） |

> Phase 0 的实质性结论见 [`docs/development/phase-0-spike-results.md`](docs/development/phase-0-spike-results.md)。Spike C 不阻塞 Phase 1 / 2，但**必须在 Phase 3 启动器开发前完成**。

### 文档增量规则

**详细任务清单按 Phase 增量编写，不一次性规划全部**：

- 当前 Phase（含本 Phase）和**下一 Phase** 才允许有细粒度任务清单。
- 后续 Phase 在产品方案 §16 中只有目标级描述，**禁止预先写出 Task 1 / 2 / 3 这种粒度的清单**。
- Phase N 完成后，再追加 Phase N+1 的细粒度任务清单到实施指南中。

**理由**：每个 Phase 的输出（spike 结论、API 契约、模板兼容性结果）都可能改变后续 Phase 的具体路径。提前写细节会在产品方向调整时全部作废，刚删除的两份旧文档就是反例。

**例外**：跨 Phase 的架构纪律、业务规则、文件命名、技术栈选型等已确定的内容可以在产品方案、CLAUDE.md、UI 设计文档中提前固化。规则的边界是"是否依赖前一 Phase 的实际产出来决定"——依赖则等，不依赖则可以先写。
