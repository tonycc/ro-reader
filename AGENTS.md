# AGENTS.md

本文件提供在此仓库中工作的长期约束。出现问题时，先分析根因，并在回复中说明根因。

## 文档事实源

按受影响功能选择对应文档，无需每次全部读取。

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

## 按需读取领域规则

修改输入表、主体、金额/数量规则、Invoice 票据组、模板、缓存/session 或 CLI 时，读取[单据领域实现参考](docs/development/document-domain-reference.md)的对应章节及下方相关事实源。纯文案修改无需通读领域规则。

- 业务字段以 Profile schema 和声明式规则为准，不在接口层或前端复制。
- 缺失业务数据不得编造；金额使用 `Decimal`，日期使用 `date`，Excel 坐标留在 YAML mapping。
- 用户数据留在本机，下载限定在 session 目录；真实业务文件不进入自动测试或仓库。

## 开发命令

按改动影响选择下列命令和受影响测试；文档修改检查链接与内容即可。已授权范围内连续完成实现、验证和失败修复，无新变化不重复已通过的检查。

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
