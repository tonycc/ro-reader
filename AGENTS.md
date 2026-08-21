# AGENTS.md

本文件提供在此仓库中工作的长期约束。出现问题时，先分析根因，并在回复中说明根因。

## 当前状态

项目已经可运行，当前主路径包括：

```text
packages/ro_generator/          Python 核心业务包
packages/ro_workbench_api/      FastAPI 网络包装层
packages/ro_workbench_launcher/ PyInstaller 桌面启动器
frontend/                       Vue 3 + TypeScript + Pinia
customer_profiles/ro/           12 个 workbook + 18 份 mapping + base schema
customer_profiles/pf/           10 个 workbook + 10 份 mapping + base schema
```

截至 2026-08-21，Python 全量测试为 642 个（其中 10 个历史 spike 跳过），默认前端 Playwright 为 29 个场景，另有 1 个隔离真实 HTTP 验收场景。数量会随代码变化；执行测试命令比引用固定数字更可靠。

## 文档事实源

- `README.md`：安装、使用、CLI/API 和开发入口。
- `docs/product/ro-document-generator-product-plan.md`：当前产品能力与范围。
- `docs/product/multi-customer-workspace-design.md`：已确认的多客户工作区设计；`ro`、`pf` 两个 Profile 已接入，实施状态以对应实施方案为准。
- `docs/development/ro-document-workbench-ui-design.md`：当前前端行为。
- `docs/development/implementation-guide.md`：当前工程结构和修改流程。
- `docs/development/multi-customer-workspace-implementation-plan.md`：多客户工作区 Phase 4.5–7 的实施记录与验收门槛；Phase 8 仍为目标级。
- `docs/单据模板字段取值规则汇总.md`：字段来源业务基准。
- `docs/development/agent-field-fix-playbook.md`：字段问题排查流程。
- `docs/development/field-fix-case-library.md`：字段修复案例。

文档与代码冲突时：产品意图以产品文档为准；已经实现的接口和行为以代码、schema 和测试为准。发现漂移时必须同步修正文档，不要继续复制旧描述。

## 产品边界

RO 单据工作台把 Excel 数据检查、结构化预览和单据装配合并到本地工作流中。

- 工具只读取、校验、装配和呈现，不生成业务编号。
- 所有数据留在本机；当前没有云端、多用户协作、ERP/SAP 集成或 Agent/MCP。
- 当前没有撤销/重做、导出历史或模板预览工具。
- PDF 依赖用户预装 LibreOffice；缺失时明确阻断，不静默降级。Invoice/PL 的 PDF 会叠主体印章，缺章文件不阻断。
- 当前仅支持 USD。

## 架构纪律

业务规则只写在 `ro_generator`：

```text
Excel
  → WorkbookReader / Validator
  → WorkbookSnapshot / Resolver
  → DocumentModel
  → TemplateMapping / DocumentPreview
  → Renderer / PDF converter / Packager
```

Invoice/PL 的 PDF 在 LibreOffice 转换后叠主体印章；缺章文件不阻断导出。Excel 导出不加章。

- CLI 只做参数解析、核心调用和结果序列化。
- FastAPI 只做 HTTP、session、事件路由和结果序列化。
- 前端只做交互和呈现，不重复价格、主体、校验或装配规则。
- 启动器只管理端口、server、浏览器、托盘和单实例。
- 新增接口壳层时必须复用核心包，不能复制业务逻辑。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 核心 | Python 3.11+、openpyxl、PyYAML、Decimal、冻结 dataclass |
| API | FastAPI、uvicorn |
| 前端 | Vue 3、TypeScript、Pinia、Vite、自研 table/CSS token |
| PDF | LibreOffice headless；Invoice/PL 印章用 pypdf |
| 启动器 | PyInstaller、pystray、Pillow |
| 测试 | pytest、Playwright |

禁止引入 React、Tailwind、CSS-in-JS、Vuex 或大型 Vue 设计系统，除非产品和架构文档先明确改变技术选型。

## 输入数据

base workbook 有三张逻辑 Sheet，实际名称由当前 Profile schema 决定：

| Profile | 产品主数据 | PO/出货记录 | 客户订单 |
| --- | --- | --- | --- |
| RO | `DATA BASE`（4/5） | `PO record`（4/5） | `客户PO`（1/2） |
| PF | `DATA BASE TEMPLATE`（2/3） | `PO RECORD 26`（1/2） | `new PO template`（1/2） |

真实名称、别名和价格列以 `customer_profiles/<profile_id>/base_schema.yaml` 为准。不要在 Python 中重复硬编码可配置的表头名称。PF 的月份表头 `2601`–`2612` 可能以 Excel 数字形式存在，只在 reader 边界转为字符串。

表头必须先通过 `schema.normalize_header()` 规范化。客户 PO 通过 `(Purchasing Document, Material)` 与 PO/SAP 数据关联。

## 主体和单据

当前合法链段由 `schema.LEGAL_CHAIN_SEGMENTS` 定义：

```text
SK → YM → GS PTE → EMAX PTE → PF
```

内部单据类型为：`PI`、`PO`、`INVOICE`、`PL`、`CI`、`RO_PL`。

- RO：GS PTE/EMAX PTE 支持 PI、PO、INVOICE、PL；SK/YM 支持 PI、INVOICE、PL、CI、RO_PL，没有 PO。
- PF：GS PTE/EMAX PTE 支持 PI、PO、INVOICE、PL；SK/YM 仅支持 PI。
- SK/YM 工厂主体：Category 1/2 → YM，Category 3 → SK。
- 配对 mapping 使用同一模板时渲染为双 Sheet workbook（RO）；使用不同模板时分别渲染并打 ZIP（PF）。

## 业务规则

- PI/PO 数量：当前 Profile 的客户订单 `Order Quantity`。
- RO 票据数量：`PO record.SHIP QTY`；PF 票据数量：按 `INV#` 的 YYMM 读取 `2601`–`2612` 月度列。
- RO SK/YM 发票号：`SK/YM INVOICE NO.`；GS PTE：`INV#`；EMAX PTE：`INV#` 加 `-P`。
- PF GS/EMAX 发票号保持 `INV#` 原值。
- `amount = quantity × unit_price`。
- `CTNS = quantity / 外箱`。
- `TOTAL CBM = L × W × H / 1,000,000 × CTNS`。
- PF 对同一 PO、同一 SAP 的客户订单数量聚合后检查 `MOQ` 和 `round value`，返回 `MOQ_NOT_MET` / `FULL_CARTON_NOT_MET` high warning，不阻断导出。
- PF 新 PO 可先只存在于 `new PO template` 并进入 PI/PO；没有 PO record 月度出货前不进入票据组。
- 缺失 SAP、订单数量、发票号或 mapping 时不得编造兜底值。
- 金额用 `Decimal`，日期用 `date`，领域对象不依赖 Excel 坐标。

字段来源差异通过 `line_rules.py`、`header_rules.py`、`totals_rules.py` 的声明式规则表达，不要在 renderer、preview 或 API 中增加平行 `if` 链。

## Invoice 票据组

工作台只把 `SHIP QTY > 0` 且有发票标识的行纳入票据组。分组、跨 PO 聚合、header 冲突和主体发票号选择都属于核心包职责，入口位于：

- `invoice_groups.py`
- `invoice_inspection.py`
- `workbook_snapshot.py`
- `generator.preview_invoice_group_from_snapshot`
- `generator.export_invoice_group_from_snapshot`

API 不得自行聚合票据组。

## 模板纪律

- 单元格坐标只写在 YAML mapping，不写在 Python。
- mapping 必须包含 `template_version`，加载时验证引用单元格。
- `table_header_row` 显式保护真实表头。
- `preview_content.column_labels` 只决定预览列和顺序；显示文案由 mapping loader 从实际 `table_header_row` 解析。特殊多行模板可用 `column_label_rows` 选择其子集，前端不得复制表头文案。
- 需要忠实复现 Excel 抬头的 mapping 必须用 `preview_content.template_fields` 引用标题和出具方单元格，并用 `layout` 声明区域；header 字段标签由 loader 从对应值单元格所在行解析，前端不得维护另一套抬头。
- `style_source_row` 必须指向真实明细样式行。
- 清理空 `to_label`、旧 `terms: {}` 等无效配置，不保留噪音。
- 模板修改后同时更新 mapping、字段规则文档和渲染测试。
- 不要把一个真实 mapping 逐字复制成另一个主体或单据；必须核对模板边界。

openpyxl 的 `insert_rows()` 不会平移 `row_dimensions`。插入明细行前必须倒序移动行维度，再插行和复制样式；对应实现位于 `renderer._insert_styled_row`。

## 编辑、缓存和 session

- `workbook_editor.py` 集中处理 base 文件写回，并使用 per-file lock。
- 编辑成功后必须使 `WorkbookCacheManager` 对应快照失效。
- 快照按文件签名自动重建，默认缓存 TTL 为 30 分钟。
- API 导出写入 session 临时目录；下载路径必须限制在该目录内。
- session 一小时无活动后清理，定时器每五分钟检查一次。

## CLI 稳定契约

当前参数以 `uv run ro-generate --help` 为准。CLI 暴露：

```text
--base --po --docs --seller --invoice-no
--output-format {xlsx,zip}
--output-dir --on-conflict --input --json
```

不要在文档中写不存在的 `--buyer`、`--invoice-month` 或 CLI PDF 参数。

退出码不可随意改变：成功 0、阻断 1、参数错误 2、需要输入 3。`--json` 模式 stdout 只能包含 JSON。

## 开发命令

```bash
uv sync --all-packages
uv run python tests/fixtures/generate_synthetic_base.py
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages

cd frontend
pnpm install
pnpm run type-check
pnpm run build
pnpm run test:e2e
```

后端开发服务器：

```bash
uv run uvicorn ro_workbench_api.app:app --reload --host 127.0.0.1 --port 54321
```

启动器：

```bash
cd frontend && pnpm run build && cd ..
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
```

## 测试 fixture

- 黄金回归 PO：`4500030844`。
- 合成 fixture：`tests/fixtures/synthetic_base.xlsx`，由生成脚本创建并被 gitignore。
- 真实业务 Excel 不入库。
- PF 真实文件只用于本机只读验收；自动回归使用 `test_pf_snapshot.py` 和 `test_order_constraints.py` 的合成 workbook。
- 测试应覆盖 combo/rod/reel、Profile 实际 Sheet、主体过滤、RO SHIP QTY、PF 月度数量、多发票号、缺 SAP、客户 PO 先行、MOQ/整箱、模板插行、票据组、PDF 错误路径、Invoice/PL PDF 印章和 API session 边界。

## 文档维护

- 长期事实只写入 README、产品、UI、工程和字段规则文档。
- 临时设计/实施计划在功能落地并合并长期结论后删除，不在主分支持续累积。
- 修改 CLI、API、支持矩阵、Sheet、mapping 数量、输出命名或依赖时，同一变更必须更新相关文档。
- 文档不要承诺未实现的撤销、历史、模板预览或 CLI PDF。

## 提交规范

使用 Conventional Commits。允许的 type：`feat`、`fix`、`refactor`、`test`、`docs`、`chore`、`spike`。标题上限 100 字符。
