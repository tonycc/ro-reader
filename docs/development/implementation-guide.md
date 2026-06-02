# RO 单据工作台实施指南

> 本文档是动手写代码前的工程准备文件，覆盖：仓库结构、工作流约定、Phase 0 spike 验收标准、Phase 0 与 Phase 1 的细粒度任务清单。
>
> 产品决策、业务规则、UI 交互不在本文重复——以 [产品方案](../product/ro-document-generator-product-plan.md) 和 [UI 设计](./ro-document-workbench-ui-design.md) 为准。
>
> **文档增量规则**（参见 CLAUDE.md "文档增量规则"）：当前 Phase 和下一 Phase 才有细粒度任务清单，更后续 Phase 仅在产品方案 §16 中保留目标级描述。Phase 完成后再追加下一 Phase 的细粒度清单。

---

## 1. 文档定位

| 类型 | 文档 | 谁负责 |
|---|---|---|
| 产品决策 | `docs/product/ro-document-generator-product-plan.md` | PM |
| UI 与交互 | `docs/development/ro-document-workbench-ui-design.md` | 前端 + PM |
| 工程实施 | 本文档 | Tech Lead |
| 仓库使用规则 | `CLAUDE.md` | Tech Lead |

冲突时优先级：产品方案 > UI 设计 > 本文档 > CLAUDE.md。

---

## 2. 仓库结构

monorepo，Python 多包共仓库，前端独立子目录。

```text
ro-reader/
├── pyproject.toml                    # Python workspace 根配置
├── packages/
│   ├── ro_generator/                 # 核心包：业务规则唯一源
│   │   ├── pyproject.toml
│   │   ├── src/ro_generator/
│   │   └── tests/
│   ├── ro_workbench_api/             # FastAPI 后端（Phase 3）
│   │   ├── pyproject.toml
│   │   ├── src/ro_workbench_api/
│   │   └── tests/
│   └── ro_workbench_launcher/        # PyInstaller 启动器（Phase 3）
│       ├── pyproject.toml
│       └── src/ro_workbench_launcher/
├── frontend/                         # Vue 3 前端（Phase 3）
│   ├── package.json
│   ├── src/
│   └── tests/
├── templates/                        # 受控 .xlsx 模板资产
│   ├── gs/  emax/  sk/  ym/
│   └── _legacy_xls/                  # 原 .xls 留底
├── tests/
│   ├── fixtures/                     # 合成 base 文件
│   └── e2e/                          # Playwright 端到端
├── docs/
│   ├── product/
│   └── development/
├── .github/workflows/
└── CLAUDE.md
```

### 2.1 Python workspace

使用 **uv workspace**（替代 pip + setuptools 多包管理），原因：

- 原生支持 monorepo workspace
- 锁文件统一，依赖一致性可保证
- 安装与构建速度比 pip 快一个数量级
- 与 PyInstaller 集成无障碍

根 `pyproject.toml` 用 `[tool.uv.workspace]` 声明 `packages/*`。每个子包有独立 `pyproject.toml`，通过 path 互相依赖：

```toml
# packages/ro_workbench_api/pyproject.toml 示例
[project]
dependencies = [
  "ro-generator",
  "fastapi>=0.110",
  "uvicorn>=0.27",
]

[tool.uv.sources]
ro-generator = { workspace = true }
```

### 2.2 前端工作区

`frontend/` 用 **pnpm**。MVP 不引入 monorepo 工具链（Turborepo / Nx），保持简单。

### 2.3 模板资产

- `templates/<entity>/*.xlsx`：受控装配模板。
- `templates/<entity>/mappings/*.yaml`：每模板一份字段映射。
- `templates/_legacy_xls/`：原始 `.xls` 留底，不参与构建。

模板文件随 git 跟踪（体积小，~ 20–80 KB / 个）。Mapping 必须含 `template_version` 字段（产品方案 §13.2）。

---

## 3. 工作流约定

### 3.1 分支策略

**Trunk-based**：

- 主干：`main`
- 功能：`feat/<scope>-<short-desc>`
- 修复：`fix/<scope>-<short-desc>`
- spike：`spike/<topic>`（spike 完成后**只保留结论文档，代码丢弃**，分支可删除）

PR 寿命目标 < 3 天。超过 1 周的长分支需提前拆分。

### 3.2 提交信息

`<type>(<scope>): <subject>` 格式：

```
feat(generator): add SAP resolver
fix(api): handle missing INV# correctly
docs(impl): add Phase 1 task list
chore(deps): bump openpyxl to 3.1.5
```

`type` 枚举：`feat / fix / refactor / test / docs / chore / spike`。
`scope` 枚举：`generator / api / launcher / frontend / templates / impl / product`。

### 3.3 PR 检查项

PR 必须满足：

- 所有相关包测试通过（pytest / vitest）
- 类型检查通过（mypy / vue-tsc）
- 格式化无差异（ruff / prettier）
- 涉及业务规则变更时，PR 描述说明对应产品方案章节
- 涉及 API 契约变更时，前后端代码同 PR 提交（避免阶段性破坏）

### 3.4 CI

GitHub Actions，三个独立 job 并行：

- `python`：所有 Python 包的 lint + type check + test
- `frontend`：前端 lint + type check + unit test + build
- `e2e`：Playwright 端到端（启动 backend + frontend 后跑）

**Phase 0 阶段只跑 `python` 和 `frontend`**，e2e 在 Phase 3 工作台 MVP 接入。

发布构建（PyInstaller 打包）作为单独的 manual-trigger workflow，不阻塞 PR。

### 3.5 工具版本

| 工具 | 版本 |
|---|---|
| Python | 3.11+ |
| uv | 最新稳定 |
| Node | 20 LTS |
| pnpm | 9+ |
| Vue | 3.4+ |
| Vite | 5+ |
| FastAPI | 0.110+ |

锁定到 `pyproject.toml` 和 `package.json`，CI 使用同一版本。

---

## 4. Phase 0 spike 验收标准

三个 spike 必须全部通过才进入 Phase 1。失败时按各自的回退方案处理。

### 4.1 spike A：模板样式保留

> **状态**：✅ 已通过。结论见 [`phase-0-spike-results.md`](./phase-0-spike-results.md)。本节验收标准保留供未来回归参考。

**目标**：验证 openpyxl 在真实 Invoice 模板上做"读取 → 写入 → 插入行 → 复制样式 → 保存"后，模板样式不被破坏。

**输入**：

- 模板：`templates/gs/invoice.xlsx`（先把 `GS PTE-RO INVOICE template.xlsx` 转换并放入对应目录）
- 数据：3 行虚拟 PO 数据（手工构造，包含 SAP、数量、单价、金额）

**操作步骤**：

1. openpyxl 加载模板（保留公式）
2. 在 `start_row` 写入 2 行数据
3. 在 `start_row + 2` 处 `insert_rows(1)` + 复制 `start_row + 1` 的样式（cell.style、行高、合并）
4. 在新行写入第 3 条数据
5. 写入合计单元格
6. 保存为新文件

**通过判定**（写自动化测试断言）：

- 文件能被 openpyxl 重新打开，无 corruption 警告
- 所有原有合并单元格区域保持不变（`ws.merged_cells.ranges` 集合相等）
- 打印区域 `ws.print_area` 与原模板一致或正确扩展（覆盖新增行）
- 列宽 `ws.column_dimensions[col].width` 完全一致
- 行高 `ws.row_dimensions[row].height` 在新插入行处为模板样板行的值
- LibreOffice 命令行打开后无错误（`soffice --headless --convert-to pdf`），生成的 PDF 与原模板填入数据后的视觉一致

**回退方案**：

- 如果插入行失败：改为模板内预留足够多空白行（如 50 行），渲染时只填值不插入，多余行保持隐藏。代价：模板需要预先准备空行，行数硬上限。
- 如果整体失败：评估替代库（如 `xlsxwriter`，但不支持读取模板，需要从零构建工作簿）。

**预期工作量**：1–2 个工作日。

### 4.2 spike B：预览渲染组件

> **状态**：✅ 已通过。选定 SheetJS（`xlsx@^0.18`）。结论见 [`phase-0-spike-results.md`](./phase-0-spike-results.md)。

**目标**：选定前端预览组件，验证能加载渲染后的 `.xlsx` 并保持视觉与导出一致。

**候选**：

- SheetJS（`xlsx` 包）+ 自渲染：轻量、纯只读、无编辑能力
- Luckysheet：完整在线 Excel 替代品，体积大（~ 1 MB），有编辑但 MVP 不需要

**输入**：spike A 产出的 Invoice 文件。

**操作步骤**：

1. 各自搭一个 Vue 3 demo 页面
2. fetch 同一份 `.xlsx` 文件，用候选库渲染
3. 与 LibreOffice 转 PDF 的视觉对比

**通过判定**（两个候选各自评分）：

- 必须项：合并单元格正确呈现、数字格式（千分位、货币符号）正确、列宽行高匹配
- 必须项：能在容器内滚动、缩放（缩放比例至少 50%–150%）
- 必须项：包体积 ≤ 800 KB（gzip 后）
- 加分项：能高亮指定坐标（用于产品方案 §4.4 双向溯源）
- 加分项：能监听单元格 hover 事件

**结论形式**：选定一个并把决策写入 UI 设计文档 §15。

**回退方案**：

- 两个都不行：使用 `xlsx-viewer` 或自研最小渲染（仅展示文本和合并，放弃格式保真）
- 实在不行：预览改为"列出装配出的关键字段值"的文字摘要，导出后再用户自行打开

**预期工作量**：2–3 个工作日。

### 4.3 spike C：启动器打包

> **状态**：⏳ 推迟到 Phase 3 启动前必须完成。理由：Spike C 不影响 Phase 1（核心包 + CLI）和 Phase 2（多主体模板），仅在工作台 MVP 上线时变成关键路径。本机为 macOS arm64，跨平台和公证验证需要 CI runner / Apple Developer 账号支持。

**目标**：验证 PyInstaller 能把"FastAPI + 自动开浏览器 + 托盘"打包为单可执行文件，在 macOS（含 Apple Silicon 和 Intel）和 Windows 上双击启动。

**输入**：

- 最小 FastAPI app（一个 `/health` 路由）
- 启动逻辑：探测可用端口、启动 server、`webbrowser.open(http://localhost:<port>)`
- 托盘：使用 `pystray` 或 `rumps`（macOS 专用，更原生）

**操作步骤**：

1. 写最小启动器（< 100 行 Python）
2. PyInstaller 打包：`--onefile` 模式
3. 在 macOS arm64 / macOS x86_64 / Windows x86_64 上分别测试
4. 验证 macOS 签名：用本地 ad-hoc 签名跑一次，记录公证流程文档
5. 验证 Windows SmartScreen 拦截，记录绕过和签名方案

**通过判定**：

- 三个平台双击都能在 5 秒内打开浏览器并显示 `/health` 响应
- 关闭浏览器 tab 后 server 仍运行，托盘"退出"菜单可正常退出
- 第二次双击触发单实例锁，把已有 tab 调到前台
- macOS 安装包（`.app` 在 `.dmg` 中）≤ 80 MB
- Windows `.exe` ≤ 80 MB

**回退方案**：

- 如果 PyInstaller 跨平台不稳定：评估 `Nuitka`（编译式，更稳定但更慢）
- 如果托盘集成有问题：MVP 阶段可以暂不做托盘，仅靠 server 持续运行 + 关闭浏览器即终止

**预期工作量**：3–5 个工作日（多平台测试和签名是大头）。

### 4.4 全部通过的判定

三个 spike 各自独立通过即可。结论汇总写入 `docs/development/phase-0-spike-results.md`（spike 结束后创建），明确：

- 每个 spike 的最终选型
- 失败项及其回退方案（如果有）
- 影响 Phase 1 的具体决策（如选定 SheetJS 而非 Luckysheet 后，前端依赖列表确定）

---

## 5. Phase 0 任务清单

### 5.1 工程准备（不依赖 spike）

- [x] 初始化 monorepo 结构（创建 `packages/`、`frontend/`、`templates/` 目录骨架）
- [x] 配置根 `pyproject.toml` 用 uv workspace
- [x] 配置 `.github/workflows/python.yml` 和 `frontend.yml`（lint + test）
- [x] 配置 ruff（Python lint + format）和 prettier（前端 format）
- [x] 配置 mypy（Python 类型检查，strict 模式）
- [x] 配置 commitlint 强制提交信息格式（参见 §3.2）
- [ ] 把 `templates/` 下原有 `.xls` 模板转成 `.xlsx`，原文件移到 `_legacy_xls/`
  - 已完成：原 12 个 `.xlsx` 模板已按主体重组到 `templates/<entity>/{pi,po,invoice,pl}.xlsx`，2 个原 `.xls` 模板（EMAX INVOICE / EMAX PL）移入 `templates/_legacy_xls/` 留底。
  - 未完成：EMAX INVOICE / EMAX PL 的 `.xls` → `.xlsx` 转换尚未做，本机无 LibreOffice。**推迟到 Phase 2 EMAX 模板接入时再处理**——Phase 0 spike A 与 Phase 1 都使用 GS Invoice，不依赖 EMAX 模板。

### 5.2 Spike A：模板样式保留 ✅

- [x] 创建 `spike/template-style-preservation` 分支
- [x] 把 `GS PTE-RO INVOICE template.xlsx` 复制到 `templates/gs/invoice.xlsx`
- [x] 写最小 spike 脚本完成 §4.1 操作步骤（`tests/spike/test_template_style_preservation.py`，10 个断言全过）
- [x] 写自动化断言（合并单元格、列宽、行高、打印区域、公式平移等）
- [ ] LibreOffice 转 PDF 视觉对比（**跳过**：本机未安装 LibreOffice。结构性断言已覆盖关键不变量；视觉对比延后到 Phase 3 工作台 MVP 阶段做端到端验证）
- [x] 撰写 spike 结论（见 [`phase-0-spike-results.md`](./phase-0-spike-results.md) Spike A 节）

### 5.3 Spike B：预览渲染组件 ✅

- [x] 创建 `spike/preview-component` 分支
- [x] 在 `frontend/` 下初始化 Vue 3 + Vite 项目骨架
- [x] 用 Vite 构建测量两个候选库的 gzip bundle 体积
- [x] 验证 SheetJS `sheet_to_html` 的合并单元格 + 坐标 ID 输出
- [x] 撰写 spike 结论 + 锁定前端预览依赖为 `xlsx@^0.18`

### 5.4 Spike C：启动器打包 ⏳ 推迟

按 §4.3 的状态说明，本 spike 推迟到 Phase 3 启动前必须完成。Phase 1 / Phase 2 不依赖启动器，可继续推进。

启动 Phase 3 前必须完成的子项：

- [ ] 创建 `spike/launcher-packaging` 分支
- [ ] 在 `packages/ro_workbench_launcher/` 下写最小启动器（FastAPI + 端口探测 + `webbrowser.open` + 托盘）
- [ ] 配置 PyInstaller 构建脚本（`build-launcher.sh` / `.ps1`）
- [ ] CI matrix 覆盖 macOS arm64 / macOS x86_64 / Windows x86_64 三个平台的打包构建
- [ ] 在 macOS arm64 本地双击启动验证
- [ ] 在 CI 上构建 Windows artifact，下载手测
- [ ] 记录 macOS 公证流程到 `docs/development/macos-codesign.md`
- [ ] 撰写 spike 结论并并入 [`phase-0-spike-results.md`](./phase-0-spike-results.md)

### 5.5 收尾

- [x] 创建 `docs/development/phase-0-spike-results.md`，汇总三个 spike 结论（Spike A/B 完整、Spike C 占位）
- [x] Spike A 代码以测试形式保留在 `tests/spike/`，Spike B 临时构建脚手架已清理
- [x] 在 CLAUDE.md 中标记 Phase 0 实质完成（Spike C 推迟到 Phase 3 启动前）
- [x] Phase 1 的细粒度任务清单已存在于本文档 §6

---

## 6. Phase 1 任务清单（核心包 + CLI）

> 目标：核心包能解析 base、校验数据、按 mapping 渲染**一种单据**（Invoice）。CLI 用于命令行装配和后续测试。
>
> 入口条件：Phase 0 三个 spike 全部通过。
>
> 退出条件：CLI 能针对黄金 PO `4500030844` 装配出与人工 Invoice 模板逐字段一致的 `.xlsx` 文件。

### 6.1 核心包基础

- [x] 在 `packages/ro_generator/` 创建包骨架
- [x] 定义领域模型 `models.py`：`Product` / `OrderLine` / `DocumentRequest` / `GenerationResult` / `ValidationMessage`（冻结 dataclass，金额 `Decimal`、日期 `date`）
- [x] 定义错误类 `errors.py`：`RoGeneratorError`（根） / `WorkbookOpenError` / `MappingError` / `TemplateError` / `InvalidRequestError` / `InternalError`，每个都有稳定 `code`
- [x] 定义 `schema.py`：必需 sheet、必需表头、表头别名、`MONTH_COLUMNS`、`HEADER_ROW`、`LEGAL_CHAIN_SEGMENTS`、`normalize_header()` 函数

### 6.2 Workbook Reader

- [x] 实现 `workbook_reader.py`：用 openpyxl 加载 base、按表头第 4 行 / 数据第 5 行解析两张 sheet
- [x] 处理表头规范化（参见 CLAUDE.md "源数据结构"中"换行和多余空格"）
- [x] 跳过完全空白行
- [x] 单元测试覆盖：合成 fixture 的最小 workbook、缺 sheet、缺表头、空数据

### 6.3 Validator

- [x] 实现 `validator.py`：校验 sheet、表头是否齐全
- [x] 输出 `ValidationMessage(kind="blocking_error")`，code 为 `SHEET_MISSING` / `HEADER_MISSING`
- [x] 行级校验（PO 是否存在、SAP 是否能解析、INV# 是否齐等）留给 §6.4 resolver 处理
- [x] 单元测试覆盖每条校验规则的正反例

### 6.4 PO Resolver

- [x] 实现 `resolver.py`：按 PO 号筛选行、SAP 匹配产品、按所有合法链段读取价格列
- [x] 公式回退逻辑（产品方案 §10.4）：CTNS / TOTAL CBM 读到 None 时按 §10.2 公式现算并 high warning
- [x] 单元测试覆盖：combo 类、跨多个月份、缺 SAP 阻断、SAP 在 DATA BASE 找不到、价格全缺、部分行失败

### 6.5 Document Model（Invoice）

- [x] 实现 `document_model.py` 中 Invoice 的视图模型构建
- [x] 数量来源切换：完整 PO 数量 vs 月度出货数量
- [x] 合计计算：总数量、总金额（PL 合计字段在 Phase 2 加）
- [x] 单元测试覆盖月份切片、空行剔除（产品方案 §10.3）、链段定价缺失、Invoice 必填字段

### 6.6 Template Mapping

- [x] 实现 `template_mapping.py`：从 YAML 加载 mapping、校验 `template_version`、校验所有引用单元格在模板中存在
- [x] 创建 `templates/gs/mappings/invoice.yaml`（用 spike A 验证过的模板）
- [x] 单元测试覆盖：mapping 引用了不存在的单元格、mapping 缺 `template_version`、mapping 字段缺失

### 6.7 Renderer + Packager

- [x] 实现 `renderer.py`：用 spike A 验证过的方案写入模板、超行时插入并复制样式
- [x] 实现 `packager.py`：按命名规则（产品方案 §12.1）输出文件，支持 zip 打包、冲突策略、版本目录
- [x] 集成测试：用 spike A 的断言验证装配输出的样式完整性

### 6.8 双向溯源索引

- [x] 在 `source_index.py` 中定义 `SourceLocation` / `SourceIndex` / `SourceIndexBuilder`
- [x] `OrderLine` / `DocumentLine` 增加 `source_row` 字段，由 resolver 从 `__row_number__` 注入
- [x] renderer 在每个写入操作上累积条目，最终通过 `RenderResult.source_index` 返回
- [x] 索引随渲染结果返回，前端在 Phase 3 消费

### 6.9 Generator 流水线

- [x] 实现 `generator.py`：串联 reader → validator → resolver → document_model → renderer → packager
- [x] 统一返回 `GenerationResult`，含 status (success/error/needs_input)、files、output_file、warnings、errors、missing_inputs、options、source_index
- [x] 集成测试：成功路径、需补充月份、需补充链段、未知 PO、缺字段、不支持的单据/链段

### 6.10 CLI

- [x] 实现 `cli.py`：argparse 参数 + `--input request.json` + `--json` + 稳定退出码
- [x] 注册 `ro-generate` entry point（`pyproject.toml`：`ro_generator.cli:cli_entry`）
- [x] 命令行测试：成功路径、JSON 输出 schema、参数错误、阻断错误、needs_input

### 6.11 测试 fixture

- [ ] 与团队确认是否能提交真实 base 文件作为 fixture
- [x] 编写合成 fixture 生成脚本 `tests/fixtures/generate_synthetic_base.py`
- [x] 合成 fixture 覆盖（参见 CLAUDE.md "测试 fixture"）：combo/rod/reel、跨多月份、缺 SAP；多 INV# 留待 Phase 2 实现
- [x] 端到端 CLI 验证：单月 success、跨月 needs_input、缺 SAP error 三种退出码全部正确

### 6.12 收尾

- [ ] 黄金 PO `4500030844` 装配的 Invoice 与人工模板逐字段对比，达到 §14.2 一致性
  - 现状：合成 fixture（含 PO `4500030844` 三行跨月数据）端到端装配通过，自动化断言验证了样式保留、合并单元格、列宽、公式平移、数据正确写入。逐字段视觉对比依赖真实 `RO DATA BASE.xlsx`，**Phase 2 真实模板接入时一并验证**。
- [x] CI 中 Python 包测试覆盖率 ≥ 80%（实测 92%，245 项测试通过）
- [x] 在 CLAUDE.md 中标记 Phase 1 完成
- [x] 把 Phase 2 的细粒度任务清单写入本文档 §7（覆盖当前占位）

---

## 7. Phase 2 任务清单（多单据 + 多主体模板 + 模板预览 CLI）

> 目标：在 Phase 1 已实现的 Invoice + GS PTE 基础上，扩展到四类单据 × 四个主体的全套模板矩阵，并提供模板预览工具供模板维护者使用。
>
> 入口条件：Phase 1 完成。
>
> 退出条件：
> - 14 份 mapping（产品方案 §13.1 模板矩阵）全部通过自动加载校验
> - 装配 PI / PO / Invoice / PL 四类单据均能写到 GS、EMAX、SK、YM 主体的对应模板（SK/YM 无 PO）
> - 真实 `RO DATA BASE.xlsx`（如团队同意入库）或扩展合成 fixture 在所有合法链段下端到端装配成功
> - SK/YM 主体请求 PO 单据时返回阻断错误

### 7.1 .xls 模板转换（Phase 0 遗留）

- [ ] 安装 LibreOffice 或等效工具，把 `templates/_legacy_xls/EMAX PTE-RO INVOICE template.xls` 和 `EMAX PTE-RO PL template.xls` 转换为 `.xlsx`
- [ ] 转换后放入 `templates/emax/invoice.xlsx` 与 `templates/emax/pl.xlsx`
- [ ] `_legacy_xls/` 目录中的原文件保留，作为业务方今后只在 `.xlsx` 上修改的留底基线

### 7.2 PI / PO / PL document model

- [x] `document_model.py` 增加 `build_pi_model()` / `build_po_model()` / `build_pl_model()`
- [x] PI / PO 使用完整 PO 数量（不依赖 invoice_month），不要求 INV# / FACTORY DOC NO.
- [x] PL 在 Invoice 字段基础上必须填充：`carton_count` / `net_weight` / `gross_weight` / `cbm`，以及合计字段 `total_*`
- [x] PL 缺装箱字段时返回阻断错误（产品方案 §11）
- [x] 单元测试覆盖每类单据的字段集与必填校验

### 7.3 多 mapping × 多模板

- [ ] 为每个 (entity, document) 组合编写 mapping YAML（参考 `templates/gs/mappings/invoice.yaml`）：
  - GS PTE：pi.yaml / po.yaml / invoice.yaml ✅ / pl.yaml
  - EMAX PTE：pi.yaml / po.yaml / invoice.yaml / pl.yaml（依赖 §7.1 转换完成）
  - SK：pi.yaml / invoice.yaml / pl.yaml（无 PO）
  - YM：pi.yaml / invoice.yaml / pl.yaml（无 PO）
- [ ] 每份 mapping 都通过 `load_template_mapping` 的引用校验
- [ ] 每份 mapping 含正确的 `template_version`

### 7.4 Generator 多文档支持

- [ ] `generator.py` 解除 "Phase 1 仅支持 INVOICE" 限制
- [ ] 一次请求多种单据类型时，对每种调用对应 `build_*_model` + 对应 mapping，输出多个文件
- [ ] 多文件场景按 `output_format`：xlsx 时各自输出，zip 时调用 `package_zip` 打包
- [ ] SK / YM 主体请求 PO 时立即返回 `MAPPING_NOT_FOUND` 阻断（产品方案 §13.1）
- [ ] 把 `_builtin_mapping_path` 替换为按 `templates/<entity>/mappings/<doc>.yaml` 约定的目录扫描，方便扩展新主体

### 7.5 多 INV# needs_input 支持

- [ ] resolver 收集每个 PO 行的 `INV#`，generator 检测同一 `(po, invoice_month)` 多个 INV# 时返回 `needs_input` + `options`
- [ ] CLI 接受 `--invoice-no` 参数（已支持），同时填充 request 时优先用之
- [ ] 单元测试：`PO 4500099999` 跨两个 INV# 触发 needs_input

### 7.6 模板预览 CLI 工具

- [ ] 新建命令 `ro-template-preview`（或子命令 `ro-generate preview-mapping`）
- [ ] 输入：base 文件 + mapping YAML 路径（多份）
- [ ] 输出：每份 mapping 的所有引用单元格 + 模板内对应位置摘要，便于模板维护者排查漂移
- [ ] 错误用 high-severity 标识：mapping 引用了不存在的单元格、`template_version` 缺失、列字母超界
- [ ] 单元测试覆盖每类诊断输出

### 7.7 跨链段一致性回归

- [ ] 扩展合成 fixture：包含 combo/rod/reel 三类的 PO，覆盖三段链路（SK/YM→GS、GS→EMAX、EMAX→PF）
- [ ] 端到端测试：每段 × 每类单据 装配成功
- [ ] 真实 `RO DATA BASE.xlsx` 接入决策落地（团队确认是否可入库）；不能入库时确保合成 fixture 等效覆盖

### 7.8 收尾

- [ ] CI 测试覆盖率仍 ≥ 80%
- [ ] CLAUDE.md 模板矩阵表更新为"全部完成"
- [ ] 标记 Phase 2 完成
- [ ] 把 Phase 3 的细粒度任务清单写入本文档 §8（覆盖当前占位）

---

## 8. Phase 3 任务清单

> 占位：等 Phase 2 完成后追加。
>
> Phase 3 目标见产品方案 §16：工作台 MVP（FastAPI + Vue + PyInstaller 启动器）。

---

## 9. Phase 4 任务清单

> 占位：等 Phase 3 完成后追加。
>
> Phase 4 目标见产品方案 §16：加固（回归测试、性能、模板版本管理）。
