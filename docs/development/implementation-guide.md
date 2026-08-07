# RO 单据工作台工程指南

> 本文描述当前代码结构、修改路径和验证方式。历史 Phase 任务清单已完成并删除，不再作为工程事实源。

## 1. 仓库结构

```text
packages/
  ro_generator/          核心业务包和 CLI
  ro_workbench_api/      FastAPI 薄包装层
  ro_workbench_launcher/ PyInstaller 启动器
frontend/                Vue 3 工作台
templates/               Excel 模板、mapping、base schema
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
| `base_schema.py` / `schema.py` | 配置、Sheet、表头、主体、价格列 |
| `workbook_reader.py` | 读取公式值和缓存值，规范化表头 |
| `validator.py` | 三张 Sheet 和最小必需表头 |
| `resolver.py` | PO/SAP/客户PO join、数量、价格、公式回退 |
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

## 5. Invoice 票据组流水线

打开 session 时，`build_workbook_snapshot()`：

1. 读取三张 Sheet。
2. 构建产品索引、PO 行索引和客户 PO 索引。
3. 对 PO record 行做宽松解析以获得出货和发票标识。
4. 只保留 `SHIP QTY > 0` 且有发票标识的行。
5. 构建票据组 summary、成员行 index 和 header context。

Invoice 路由只从 snapshot 取结果：

- inspection：`inspect_invoice_group_from_snapshot`
- preview：`preview_invoice_group_from_snapshot`
- export：`export_invoice_group_from_snapshot`

不得在 API 或前端重新实现分组。

## 6. FastAPI 层

`app.py` 当前有 18 个 `/api` 端点。职责仅限：

- Pydantic 请求模型。
- session header 和生命周期。
- 核心 dataclass/结果的 JSON 序列化。
- 临时输出目录。
- 受限下载。
- 生产静态资源挂载。

下载端点必须验证请求 path 位于 session temp directory 内，防止路径穿越。

Session 默认一小时过期；清理任务每五分钟运行。单个 base 路径复用现有 session。

## 7. 前端层

```text
App.vue
  ├─ TopBar
  ├─ QueueSidebar
  ├─ DataCheckScreen
  ├─ PreviewScreen
  ├─ ExportScreen
  ├─ StatusBar
  └─ LibreOfficePrompt
```

`stores/api.ts` 维护 HTTP 类型和 `X-Session-Id`。`stores/workbench.ts` 维护选择、数据、预览、导出和错误状态。

组合预览由前端并行请求两种真实单据；核心导出仍负责把配对单据写入一个 workbook/PDF。

## 8. 模板和 mapping

目录约定：

```text
templates/<seller>/
  *.xlsx
  mappings/
    pi.yaml
    po.yaml          # 仅 gs/emax
    invoice.yaml
    pl.yaml
    ci.yaml          # 仅 sk/ym
    ro_pl.yaml       # 仅 sk/ym
```

当前共 12 个 workbook、18 份 mapping。

### 8.1 修改模板

1. 明确主体、单据类型和 Sheet。
2. 在 `.xlsx` 中修改版式。
3. 同步 YAML 坐标、`template_version`、`table_header_row`、`style_source_row`。
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
--base --po --docs --seller --invoice-no
--output-format {xlsx,zip}
--output-dir --on-conflict --input --json
```

`buyer` 由 seller 推导。当前没有 `invoice_month` 参数，也没有 CLI PDF choice。

退出码和 JSON stdout 是稳定协议。新增参数时必须补 `test_cli.py` 并同步 README/AGENTS。

## 12. 测试

### 12.1 Python

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run pytest packages/ro_generator/tests/test_generator.py -v
uv run pytest packages/ro_workbench_api/tests/test_app.py -v
```

截至 2026-08-07，全量为 465 个测试。

### 12.2 前端

```bash
cd frontend
pnpm run type-check
pnpm run build
pnpm run test:e2e
```

Playwright 使用合成 fixture，并启动真实 Vite/FastAPI 服务。CI 安装 LibreOffice 以覆盖 PDF。

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
cd frontend && pnpm run build && cd ..
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
```

启动器行为：随机端口、后台 uvicorn、30 秒健康检查、浏览器、托盘、单实例锁文件和优雅退出。

CI 发布版本来自 `build-launcher.yml` 的 `APP_VERSION`。发布前同时核对该值、界面版本文本、Python/FastAPI metadata 和安装包文件名。

## 15. 文档维护

- `README.md` 面向使用者和新开发者。
- 产品说明只记录当前范围与明确 roadmap。
- UI 文档只记录当前交互。
- 本文只记录当前工程路径。
- 字段规则文档保留业务字段事实。
- 一次性 spec/plan 完成后，把长期结论合并到上述文档并删除临时文件。

修改 API、CLI、Sheet、单据矩阵、mapping、输出命名、PDF 或 session 行为时，文档必须与代码同一提交更新。
