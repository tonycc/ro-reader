# RO 单据工作台

RO 单据工作台读取本地 Excel base 文件，按当前 Customer Profile 校验并装配 PI、PO、Invoice 和 Packing List；RO Profile 还支持 SK/YM 使用的 CI/RO_PL。应用采用“本地启动器 + 浏览器”形态，业务数据不离开用户电脑。

本工具是单据装配器，不负责生成 `INV#`、`SK/YM INVOICE NO.`、PI 编号或业务日期。缺少这些输入时，工具会返回阻断错误或待选择项，不会自动编造。

## 当前能力

- PO 视角：查看和编辑 `PO record` 行，预览及导出 PI/PO。
- Invoice 视角：按发票标识聚合 `SHIP QTY > 0` 的出货行，跨 PO 检查、预览和导出发票/装箱单。
- Excel 模板渲染：保留模板字体、边框、合并单元格、行高、列宽和打印设置。
- PDF 导出：先生成 `.xlsx`，再使用本机 LibreOffice 无头转换。
- 字段溯源：预览字段可查看源 Sheet、行、字段或计算规则。
- 分级校验：区分阻断错误、警告和待选择输入。
- 多客户工作区：内置 `ro` 与 `pf` Profile，可保存多个 base 文件配置并从顶部快速切换。
- PF 订单检查：按 SAP 聚合客户订单数量，提醒低于 MOQ 或不是整箱数量。
- CLI、FastAPI 和工作台 UI 共享同一核心业务包。

RO Profile 支持的主体与内部单据类型：

| 卖方 | 买方 | PI | PO | INVOICE / PL | CI / RO_PL |
| --- | --- | :---: | :---: | :---: | :---: |
| SK | YM | ✅ | — | ✅ | ✅ |
| YM | GS PTE | ✅ | — | ✅ | ✅ |
| GS PTE | EMAX PTE | ✅ | ✅ | ✅ | — |
| EMAX PTE | PF | ✅ | ✅ | ✅ | — |

`CI` / `RO_PL` 是 SK/YM 的 RO 版商业发票和装箱单。SK/YM 没有 PO 模板。

PF Profile 使用同一贸易链，但能力矩阵为：GS PTE、EMAX PTE 支持 PI/PO/INVOICE/PL，SK、YM 仅支持 PI。PF 的 Invoice 与 PL 来自两个独立模板，预览分别进入独立页面，组合导出时分别生成后打入同一 ZIP。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ 和 [pnpm](https://pnpm.io/) 9+
- macOS、Windows 或 Linux
- PDF 导出需要预装 [LibreOffice](https://www.libreoffice.org/)

如果 `soffice` 不在标准安装位置，可设置 `RO_SOFFICE_PATH`。没有 LibreOffice 时，PDF 导出返回 `PDF_CONVERTER_UNAVAILABLE`，Excel 导出不受影响。

## 开发模式启动

```bash
uv sync --all-packages
cd frontend && pnpm install && cd ..

# 真实 base 文件不入库；开发时生成合成 fixture
uv run python tests/fixtures/generate_synthetic_base.py

# 终端 1：后端
uv run uvicorn ro_workbench_api.app:app --reload --host 127.0.0.1 --port 54321

# 终端 2：前端
cd frontend && pnpm run dev
```

开发页面默认位于 `http://localhost:6173`。

## 输入工作簿

base 文件必须是 `.xlsx`，并符合所选 Profile 的三张逻辑 Sheet。当前实际名称为：

| Profile | 产品主数据 | PO/出货记录 | 客户订单 |
| --- | --- | --- | --- |
| `ro` | `DATA BASE`（表头 4，数据 5） | `PO record`（表头 4，数据 5） | `客户PO`（表头 1，数据 2） |
| `pf` | `DATA BASE TEMPLATE`（表头 2，数据 3） | `PO RECORD 26`（表头 1，数据 2） | `new PO template`（表头 1，数据 2） |

Sheet、表头位置和字段别名分别位于 `customer_profiles/<profile_id>/base_schema.yaml`。表头匹配前会压缩换行和多余空格；PF 的数字月份表头 `2601`–`2612` 在读取边界转换为字符串。

主要关联关系：

```text
客户PO.Purchasing Document = PO record.PO NO.
客户PO.Material            = PO record.SAP Number
PO record.SAP Number       = DATA BASE.SAP
```

## 工作台流程

### 1. 配置文件

在顶部“管理工作区”中新建配置，填写显示名称、Customer Profile 和 base `.xlsx` 绝对路径。先“检测路径”，再保存并“设为当前”；保存配置不会自动切换。配置由后端保存在用户配置目录，顶部工作区切换器可快速切换，任一时刻只有一个当前工作区。

PF 示例应选择 `/path/to/Template PF/PO RECORD 2026.xlsx`，不是只填写模板文件夹。

### 2. 选择业务视角

左侧队列支持 PO 和 Invoice 两类对象：

- PO：用于订单数据检查和 PI/PO 工作流。
- Invoice：由实际出货行聚合的票据组，用于 Invoice/PL 或 CI/RO_PL 工作流。

### 3. 数据检查

- PO 数据表支持双击编辑，保存后直接写回 base 文件，并使内存快照失效。
- Invoice 检查表只读，展示票据组成员行、PO、SAP、出货数量和问题。

当前没有撤销/重做或导出历史；编辑前请保留业务文件备份。

### 4. 单据预览

预览由后端返回结构化 JSON，前端按 header、明细、合计和备注区域渲染。单据标题、出具方抬头和字段标签从当前 mapping 引用的 Excel 模板读取，区域位置由 `preview_content.layout` 声明；明细列名来自模板真实表头。点击预览字段可查看其来源。预览不会先生成临时 Excel。

### 5. 导出

导出确认页可选择一个或多个主体、单据类型及 Excel/PDF 格式。多个结果会打成 ZIP。工作台产物先写入 session 临时目录，再通过浏览器下载；session 一小时无活动后会被清理。

## 核心业务规则

- PI/PO 数量取当前 Profile 的客户 PO `Order Quantity`。
- RO 的 INVOICE/PL/CI/RO_PL 数量取 `PO record.SHIP QTY`。
- PF 的 INVOICE/PL 数量根据 `INV#` 中的 YYMM 读取 `PO RECORD 26` 的 `2601`–`2612` 月度列。
- `Category = 1/2` 的工厂主体为 YM，`Category = 3` 的工厂主体为 SK。
- RO 的 SK/YM 发票号取 `SK/YM INVOICE NO.`；GS PTE 取 `INV#`；EMAX PTE 给 `INV#` 添加 `-P`。PF 的 GS/EMAX 均保持 `INV#` 原值。
- 价格按主体和 Category 从 `DATA BASE` 的价格矩阵读取。
- `amount = quantity × unit_price`，金额使用 `Decimal`。
- `CTNS = quantity / 外箱`。
- `TOTAL CBM = L × W × H / 1,000,000 × CTNS`。
- RO PL 重量沿用既有单箱重量 × 箱数口径；PF PL 按月度出货数量重算箱数，并换算重量和 CBM。
- PF 对每个 PO 内相同 SAP 的客户订单数量先聚合，再检查 `MOQ` 和 `round value`；不合规返回 high warning，不阻断流程。
- 当前仅支持 USD。

## 校验结果

| 类型 | 含义 |
| --- | --- |
| `blocking_error` | 数据或模板不足，禁止导出 |
| `warning` | 可以继续，但需要复核；带 `high` 或 `low` 严重度 |
| `missing_inputs` | 数据存在多个合法候选，需要用户选择主体或发票号 |

典型阻断包括缺少 Sheet/表头、SAP 不存在、订单数量缺失、发票号不匹配和模板 mapping 不存在。公式缓存值为空时，核心包会按规则回退计算并产生警告。

PF 订单提醒使用稳定 code `MOQ_NOT_MET` 和 `FULL_CARTON_NOT_MET`，详情包含 SAP、订单数量、门槛/整箱值、余数及 `new PO template` 的定位信息。

## CLI

CLI 当前支持 `PI`、`PO`、`INVOICE`、`PL`、`CI`、`RO_PL`，输出格式仅开放 `xlsx` 和 `zip`。`--profile` 默认使用 `ro`，需要指定其它客户时显式传入 Profile ID；CLI 始终显式接收 `--base`，不会读取 GUI 工作区或 `current_workspace_id`。PDF 目前由工作台/API 暴露。

```bash
# PI
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs pi \
  --seller "GS PTE" \
  --output-dir /tmp/ro-output

# 指定发票号导出 Invoice + PL
uv run ro-generate \
  --base tests/fixtures/synthetic_base.xlsx \
  --po 4500099999 \
  --docs invoice,pl \
  --seller "GS PTE" \
  --invoice-no INV-2603-001 \
  --output-format zip \
  --output-dir /tmp/ro-output \
  --json
```

完整参数以实际帮助为准：

```bash
uv run ro-generate --help
```

PF CLI 示例：

```bash
uv run ro-generate \
  --profile pf \
  --base "/path/to/Template PF/PO RECORD 2026.xlsx" \
  --po 4500752093 \
  --docs pi,po \
  --seller "GS PTE" \
  --output-dir /tmp/pf-output
```

稳定退出码：

| 状态 | 退出码 |
| --- | ---: |
| 成功 | 0 |
| 阻断错误 | 1 |
| 参数错误 | 2 |
| 需要补充选择 | 3 |

`--json` 模式下 stdout 只输出 JSON，日志和提示写入 stderr。

## API

工作台后端当前提供 27 个 `/api` 端点：

| 分组 | 端点 |
| --- | --- |
| 健康与文件 | `GET /api/health`、`POST /api/check-path` |
| Profile/工作区 | `GET /api/profiles`、`GET /api/workspaces`、`POST /api/workspaces`、`PATCH /api/workspaces/{id}`、`DELETE /api/workspaces/{id}`、两种 validate、activate、`GET /api/bootstrap` |
| Session | `POST /api/session/open`、`POST /api/session/close` |
| Invoice | 列表、inspection、preview、export、export-batch |
| PO | 数据、customer-po、issues、dry-run、preview、edit、export、export-batch |
| 下载 | `GET /api/download` |

Profile/工作区配置端点不依赖业务 session；Invoice、PO、预览、编辑、导出和下载请求通过 `X-Session-Id` 关联 Profile、base 文件与临时输出目录。

## 架构

```text
ro_generator
  ├── ro-generate CLI
  └── ro_workbench_api
        └── Vue 3 frontend
              └── PyInstaller launcher
```

- `packages/ro_generator`：领域模型、读取、校验、解析、预览、渲染、PDF 和打包。
- `packages/ro_workbench_api`：HTTP、session、序列化和静态资源服务。
- `frontend`：Vue 3 + TypeScript + Pinia 工作台。
- `packages/ro_workbench_launcher`：随机端口、单实例、浏览器和托盘生命周期。
- `customer_profiles/ro`：12 个 `.xlsx`、18 份 mapping 和 RO schema/rules。
- `customer_profiles/pf`：10 个 `.xlsx`、10 份 mapping 和 PF schema/rules。

业务判断只能写在 `ro_generator`。API、CLI、前端和启动器必须保持薄壳。

## 测试与质量检查

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages

cd frontend
pnpm run type-check
pnpm run build
pnpm run test:e2e
pnpm run test:e2e:http
```

截至 2026-08-09，Python 套件收集并通过 531 个测试；默认 Playwright 回归包含 29 个场景（含单据预览表头与 Excel 模板一致性、PF MOQ/整箱提醒及客户 PO 只读投影），另有 1 个隔离真实 HTTP 验收场景。CI 分别覆盖 Python、前端/E2E，以及 macOS/Windows 启动器构建。

## 桌面构建

```bash
cd frontend && pnpm run build && cd ..
# 发布前核对所有包、API、前端和安装包版本
uv run python scripts/verify_release_metadata.py
uv run pyinstaller packages/ro_workbench_launcher/ro-workbench.spec --noconfirm
```

CI 中的发布包版本由 `.github/workflows/build-launcher.yml` 的 `APP_VERSION` 管理。

## 文档

文档入口见 [`docs/README.md`](docs/README.md)。产品现状、UI、工程实现和字段规则分别维护，已完成的一次性实施计划不留在主分支中。
