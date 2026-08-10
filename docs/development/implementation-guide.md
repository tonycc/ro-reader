# RO 单据工作台工程指南

> 本文描述当前代码结构、修改路径和验证方式。历史 Phase 任务清单已完成并删除，不再作为工程事实源。

## 1. 仓库结构

```text
packages/
  ro_generator/          核心业务包和 CLI
  ro_workbench_api/      FastAPI 薄包装层
  ro_workbench_launcher/ PyInstaller 启动器
frontend/                Vue 3 工作台
customer_profiles/ro/    RO Profile 的 Excel 模板、mapping、base schema
customer_profiles/pf/    PF Profile 的 Excel 模板、mapping、base schema
tests/fixtures/          合成 base 生成脚本
docs/                    当前产品、UI、工程和字段规则
.github/workflows/       Python、前端/E2E、启动器 CI
```

根 `pyproject.toml` 是 uv workspace。前端单独使用 pnpm lockfile。

## 2. 环境准备

```bash
uv sync --all-packages
cd frontend && pnpm install && cd ..
uv run python tests/fixtures/generate_synthetic_base.py
```

真实业务 Excel 被 gitignore，不得提交。

## 3. 核心包模块

| 模块 | 职责 |
| --- | --- |
| `models.py` | Product、OrderLine、DocumentRequest、GenerationResult |
| `profiles/` | CustomerProfile、GenerationContext、RO/PF 客户差异策略和注册表 |
| `base_schema.py` / `schema.py` | 配置、Sheet、表头、主体、价格列 |
| `workbook_reader.py` | 读取公式值和缓存值，规范化表头 |
| `validator.py` | 三张 Sheet 和最小必需表头 |
| `resolver.py` | PO/SAP/客户PO join、数量、价格、公式回退 |
| `order_constraints.py` | Profile 可选的客户订单 MOQ/整箱提醒 |
| `seller_filter.py` | SK/YM Category 主体规则 |
| `invoice_groups.py` | 实际出货票据组和稳定 key |
| `invoice_inspection.py` | 票据组解析、成员行和冲突 |
| `document_model.py` | 六种单据共享的领域装配 |
| `line_rules.py` | 明细字段来源分派 |
| `header_rules.py` | header 字段来源分派 |
| `totals_rules.py` | 合计来源和预览规则 |
| `template_mapping.py` | YAML 加载和模板引用校验 |
| `document_preview.py` | DocumentModel → 结构化预览 |
| `renderer.py` | DocumentModel → Excel 模板 |
| `pdf_convert.py` | LibreOffice xlsx → pdf |
| `packager.py` | 文件命名、冲突策略和 ZIP |
| `source_index.py` | 文档单元格与源字段双向索引 |
| `workbook_snapshot.py` | 一次读取后的 PO/Invoice 索引 |
| `workbook_cache.py` | 文件签名缓存和 TTL |
| `workbook_editor.py` | 字段级写回和 per-file lock |
| `workbench_service.py` | 工作台用核心服务编排 |
| `generator.py` | preview/export 总入口 |
| `cli.py` | argparse 和 JSON 协议 |

## 4. PO 流水线

```text
DocumentRequest
  → validate_workbook_structure
  → resolve_po_lines / resolve_po_rows
  → seller + buyer 推导
  → invoice_no 候选（票据类单据）
  → build_document_model
  → load_template_mapping
  ├─ preview: build_preview
  └─ export: render_document / render_document_bundle
                └─ optional convert_to_pdf
```

`generate()` 读磁盘，适合 CLI 和 PO 导出。`preview_from_snapshot()` 复用 session 快照，避免每次预览重新读取整个 workbook。

PF Profile 允许“客户 PO 先行”：`new PO template` 中存在、但尚未进入 `PO RECORD 26` 的 PO 会在快照中生成只用于 PI/PO 的最小行。该行不伪造发票或物流字段；Invoice/PL 仍必须等待真实月度出货记录。

## 5. Invoice 票据组流水线

打开 session 时，`build_workbook_snapshot()`：

1. 读取三张 Sheet。
2. 构建产品索引、PO 行索引和客户 PO 索引。
3. 对 PO record 行做宽松解析以获得当前 Profile 的出货数量和发票标识。
4. RO 使用 `SHIP QTY`；PF 根据 `INV#` 的 YYMM 使用 `2601`–`2612` 月度列，只保留数量大于 0 的行。
5. 构建票据组 summary、成员行 index 和 header context。

Invoice 路由只从 snapshot 取结果：

- inspection：`inspect_invoice_group_from_snapshot`
- preview：`preview_invoice_group_from_snapshot`
- export：`export_invoice_group_from_snapshot`

不得在 API 或前端重新实现分组。

## 6. FastAPI 层

`app.py` 当前有 27 个 `/api` 端点。职责仅限：

- Pydantic 请求模型。
- session header 和生命周期。
- 核心 dataclass/结果的 JSON 序列化。
- 临时输出目录。
- 受限下载。
- 生产静态资源挂载。

下载端点必须验证请求 path 位于 session temp directory 内，防止路径穿越。

Session 默认一小时过期；清理任务每五分钟运行。工作区激活后，业务 session 绑定 `workspace_id`、`profile_id` 和 base 文件；旧 `session/open` 仅作为 RO 兼容入口。

## 7. 前端层

```text
App.vue
  ├─ TopBar
  ├─ QueueSidebar
  ├─ DataCheckScreen
  ├─ PreviewScreen
  ├─ ExportScreen
  ├─ StatusBar
  ├─ LibreOfficePrompt
  └─ WorkspaceSwitcher / WorkspaceSettings / WorkspaceForm
```

`stores/api.ts` 维护业务 HTTP 类型和 `X-Session-Id`；`services/workspace.http.ts` 维护 Profile/工作区 HTTP 契约。`stores/workspace.ts` 维护工作区、bootstrap 和激活状态，`stores/workbench.ts` 维护选择、数据、预览、导出和错误状态。

组合预览由前端并行请求两种真实单据。核心导出会检查两份 mapping 的模板身份：同一模板（RO）写入双 Sheet workbook；不同模板（PF）分别生成并打 ZIP。

## 8. 模板和 mapping

目录约定：

```text
customer_profiles/ro/templates/<seller>/
  *.xlsx
  mappings/
    pi.yaml
    po.yaml          # 仅 gs/emax
    invoice.yaml
    pl.yaml
    ci.yaml          # 仅 sk/ym
    ro_pl.yaml       # 仅 sk/ym
```

PF 使用相同目录层级，但只有 GS/EMAX 的 PI/PO/Invoice/PL 及 SK/YM PI。当前 RO 为 12 个 workbook/18 份 mapping，PF 为 10 个 workbook/10 份 mapping。

### 8.1 修改模板

1. 明确主体、单据类型和 Sheet。
2. 在 `.xlsx` 中修改版式。
3. 同步 YAML 坐标、`template_version`、`table_header_row`、`style_source_row`。
   `preview_content.column_labels` 的键及顺序决定结构化预览列；文字由 loader 从模板表头读取。只有需要排除类别说明行等特殊情况时，才配置 `column_label_rows`，且它必须是 `table_header_row` 的子集。
   单据抬头需要与导出一致时，用 `preview_content.template_fields` 引用模板中的 `title`、`seller_info` 单元格，并用 `layout` 声明顶部和左右信息区。header 字段标签由 loader 从值单元格所在行解析，不在 YAML 或前端重复抄写。
4. 清理无效空配置。
5. 运行 mapping loader 和 renderer 测试。
6. 打开渲染结果做视觉检查，尤其是打印区、合并单元格和插入行后的底部区域。
7. 更新字段规则文档。

### 8.2 插入行陷阱

`openpyxl.Worksheet.insert_rows()` 不移动 `row_dimensions`。正确顺序是：

1. 倒序把插入点及之后的 `row_dimensions` key 加一。
2. 调用 `insert_rows()`。
3. 复制真实样式来源行的样式、行高和必要公式。
4. 调整 mapping 后续区域坐标。

不要用普通 `insert_rows()` 代替 `renderer._insert_styled_row`。

## 9. 字段规则修改

字段问题先按 [`agent-field-fix-playbook.md`](./agent-field-fix-playbook.md) 定位层级：

- 源表头或列变化：`base_schema.yaml`。
- 主体/单据字段来源：`line_rules.py`、`header_rules.py`、`totals_rules.py`。
- 领域计算：`resolver.py` 或 `document_model.py`。
- 模板坐标或固定文案：mapping YAML。
- 仅展示序列化：`document_preview.py`。

业务来源规则不能只修预览，也不能只修 renderer；两条路径必须共享同一规则。

## 10. PDF

PDF 不是独立排版器：

```text
DocumentModel → renderer → .xlsx → LibreOffice → .pdf
```

`find_soffice()` 按环境变量、PATH 和平台常见路径查找。转换使用临时 `UserInstallation`，失败转换为核心错误类型。

如果同时需要 xlsx 和 pdf，工作台服务为每种格式使用独立子目录，避免 PDF 流程删除中间 xlsx 时影响 Excel 产物。

## 11. CLI

实际参数：

```text
--base --profile --po --docs --seller --invoice-no
--output-format {xlsx,zip}
--output-dir --on-conflict --input --json
```

`--profile` 缺省为 `ro`，CLI 不读取 GUI 工作区配置；`buyer` 由 seller 推导。当前没有 `invoice_month` 参数，也没有 CLI PDF choice。

退出码和 JSON stdout 是稳定协议。新增参数时必须补 `test_cli.py` 并同步 README/AGENTS。

## 12. 测试

### 12.1 Python

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run pytest packages/ro_generator/tests/test_generator.py -v
uv run pytest packages/ro_workbench_api/tests/test_app.py -v
```

截至 2026-08-09，全量为 531 个测试。Phase 5.0 的 RO 回归基线见 `packages/ro_generator/tests/test_ro_baseline.py`；RO/PF Profile 契约见 `packages/ro_generator/tests/test_profiles.py`；PF 客户 PO 先行、分离模板导出和 SK/YM PI 抬头一致性见 `test_pf_snapshot.py`；MOQ/整箱规则见 `test_order_constraints.py`；Profile-aware cache 见 `test_workbook_cache.py`；WorkspaceStore、SessionManager 和工作区 API 见 API 对应测试；CLI Profile 和退出码见 `test_cli.py`。

### 12.2 前端

```bash
cd frontend
pnpm run type-check
pnpm run build
pnpm run test:e2e
pnpm run test:e2e:http
```

默认 Playwright 使用合成 fixture，并启动真实 Vite/FastAPI 服务；当前 29 个场景包含单据预览表头与 Excel 模板一致性、PF MOQ/整箱提醒呈现和客户 PO 只读投影。`test:e2e:http` 使用独立临时配置目录覆盖工作区 bootstrap/刷新恢复。CI 安装 LibreOffice 以覆盖 PDF。

### 12.3 质量检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy packages
```

## 13. CI

| Workflow | 内容 |
| --- | --- |
| `python.yml` | sync、ruff、format、mypy、fixture、pytest |
| `frontend.yml` | install、type-check、build、Playwright + LibreOffice |
| `build-launcher.yml` | macOS DMG、Windows ZIP |

前端 `lint` 和 `test` script 当前是占位命令；真实静态验证由 `type-check`/`build`，真实行为验证由 Playwright 完成。

## 14. 启动器和发布

本地构建：

```bash
python3 scripts/release_version.py sync
uv sync --all-packages
cd frontend && pnpm install --frozen-lockfile && pnpm run build && cd ..
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
```

启动器行为：随机端口、后台 uvicorn、30 秒健康检查、浏览器、托盘、单实例锁文件和优雅退出。

发布版本唯一手写源为根目录 `VERSION`。`scripts/release_version.py sync` 将其同步到 Python 包 metadata、运行时 metadata 和 Windows 安装器；Vite 与 PyInstaller 在构建时直接读取该文件，CI 用它生成安装包文件名和用户说明。

版本一致性可直接检查：

```bash
uv run python scripts/verify_release_metadata.py
```

## 15. 文档维护

- `README.md` 面向使用者和新开发者。
- 产品说明只记录当前范围与明确 roadmap。
- UI 文档只记录当前交互。
- 本文只记录当前工程路径。
- 字段规则文档保留业务字段事实。
- 一次性 spec/plan 完成后，把长期结论合并到上述文档并删除临时文件。

修改 API、CLI、Sheet、单据矩阵、mapping、输出命名、PDF 或 session 行为时，文档必须与代码同一提交更新。

## 16. 当前待实施方案

多客户工作区的 Phase 4.5 前端骨架、Phase 5.0–5.8 基础模型/后端、Phase 6.0–6.3 真实 HTTP/发行基础以及 Phase 7 PF Customer Profile 已写入当前代码。下一阶段为 Phase 8 多客户加固；在进入该阶段前不预写文件级任务：

- [多客户工作区设计](../product/multi-customer-workspace-design.md)
- [多客户工作区实施方案](multi-customer-workspace-implementation-plan.md)

Phase 7 已完成 PF schema、规则、10 份模板/mapping、客户 PO 先行、月度出货、原始发票号、MOQ/整箱提醒、分离 Invoice/PL 打包和真实文件验收。PF 原始业务目录只用于核对，运行时资产位于 `customer_profiles/pf/`；用户工作区应绑定具体 base `.xlsx` 文件。
