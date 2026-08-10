# RO 单据工作台产品说明

> 状态：当前实现基准，最近核对于 2026-08-08。

## 1. 产品概述

RO 单据工作台是支持 Customer Profile 的本地单据装配工具，当前内置 `ro` 和 `pf`。它把 Excel 数据检查、单据预览和导出放在同一个工作空间中，减少人工查表和复制。

对外的核心业务单据是 PI、PO、Invoice 和 Packing List；核心包还使用 `CI`、`RO_PL` 表示 SK/YM 的 RO 版商业发票和装箱单。

工作台不是编号生成器。`INV#`、`SK/YM INVOICE NO.`、SK/YM PI 编号和业务日期必须来自当前 Profile 的 base 文件或人工维护，工具不得自动编造。

## 2. 解决的问题

原流程需要在产品主数据、PO、客户 PO 和多个 Excel 模板之间手工搬运字段，容易出现：

- 同一数据重复填写。
- 缺字段到导出后才发现。
- 单价、数量和主体选择口径不一致。
- 无法快速判断哪些 PO 或票据可以导出。
- 模板样式在程序写入后被破坏。

工作台以同一套核心规则驱动数据检查、预览、CLI 和最终文件。

## 3. 产品目标与贸易链段

### 3.1 当前目标

- 本地、离线处理业务文件。
- 在导出前展示结构化单据内容和校验结果。
- 允许在 PO 数据检查中直接修正 `PO record`。
- PI/PO 以 PO 为业务对象；Invoice/PL 以实际出货票据组为业务对象。
- Excel 与 PDF 使用同一份 `.xlsx` 模板作为版式来源。

### 3.2 当前链段

合法链段由核心包 `schema.LEGAL_CHAIN_SEGMENTS` 定义：

```text
SK → YM → GS PTE → EMAX PTE → PF
```

| seller | buyer | 支持单据 |
| --- | --- | --- |
| SK | YM | PI、INVOICE、PL、CI、RO_PL |
| YM | GS PTE | PI、INVOICE、PL、CI、RO_PL |
| GS PTE | EMAX PTE | PI、PO、INVOICE、PL |
| EMAX PTE | PF | PI、PO、INVOICE、PL |

SK/YM 不提供 PO 模板。

上表是 RO Profile 的完整能力矩阵。PF Profile 复用同一贸易链，GS PTE/EMAX PTE 支持 PI、PO、INVOICE、PL，SK/YM 仅支持 PI。这里的 `PF` 既可能表示 RO 链段中的最终买方，也可能表示机器 ID 为 `pf` 的 Customer Profile，两者不得混用。

## 4. 体验原则

### 4.1 先预览，再导出

预览展示的是核心包装配后的领域值和模板展示配置。导出只是把已经检查过的结果写入模板，不应再引入新的业务计算。

单据标题、出具方抬头和 header 标签以当前 Excel 模板为事实源：mapping 用 `preview_content.template_fields` 引用固定文本单元格，用 `layout` 声明展示区域，loader 从 header 值单元格所在行读取模板标签。空白但已映射的日期或业务字段在预览中保留空白横线。前端不复制客户、主体或单据专属抬头。

明细列的选择和顺序由 mapping 的 `preview_content.column_labels` 键决定，显示文案则在 mapping 加载时直接读取实际 Excel 的 `table_header_row`。多行表头保留换行，模板中的空白子列也保持空白，前端不得另写一套列名。

### 4.2 在源数据处解决错误

PO 检查表允许直接编辑 `PO record`。写回成功后，缓存立即失效，下一次检查和预览重新读取文件。

### 4.3 来源可解释

预览字段可以显示来源 Sheet、行、字段、固定模板内容或计算规则。核心 renderer 同时生成单元格到源字段的 `SourceIndex`。

当前 UI 已实现“预览字段 → 来源信息”；“源字段 → 所有文档单元格”的反向高亮尚未实现。

### 4.4 不隐藏不确定性

多主体、多发票号、缺字段和公式回退必须显式显示为 `missing_inputs`、阻断错误或警告。

### 4.5 本地文件优先

base 文件、缓存、临时导出和 PDF 转换都在用户机器上完成。应用不上传业务数据。

## 5. 当前范围与不做范围

### 5.1 已实现

- 单个 base 文件中的多 PO 浏览。
- PO 与 Invoice 双视角队列。
- PO 行编辑和 Invoice 只读 inspection。
- 六种内部单据类型的结构化预览。
- Excel 导出、批量 ZIP、LibreOffice PDF。
- YAML 模板 mapping、模板引用校验和超行插入。
- CLI、FastAPI、本地浏览器工作台和 PyInstaller 启动器。
- macOS/Windows CI 构建。
- 可配置多个工作区并从顶部切换；session、缓存和资产按 `profile_id` 隔离。
- PF Profile 的独立 schema、模板和规则。
- PF 客户订单 MOQ/整箱 high warning。
- PF 客户 PO 先行流程：订单未进入 `PO RECORD 26` 时仍可检查并生成 PI/PO。

### 5.2 当前不支持

- 撤销/重做。
- 导出版本历史和历史快照恢复。
- 图形化或 CLI 模板预览专用工具。
- 多用户协同、权限审批和云端托管。
- ERP/SAP 直连。
- Agent/MCP 集成。
- 多币种、税务或关务计算。
- 手工拆分单行出货数量。
- CLI 的 PDF 参数；PDF 当前由工作台/API 暴露。

## 6. 用户

| 用户 | 当前场景 |
| --- | --- |
| 跟单/单证人员 | 加载 base、检查 PO/票据、修正字段、预览和导出 |
| 业务主管 | 查看队列状态和阻断原因 |
| 模板维护者 | 修改 `.xlsx` 与对应 YAML mapping，并运行回归测试 |
| 开发维护者 | 维护 schema、字段规则、核心流水线和应用壳层 |

## 7. 产品架构

```text
┌─────────────────────────────────────────────────────┐
│ ro_generator：全部业务规则                           │
│ reader / validator / snapshot / resolver            │
│ document model / preview / mapping / renderer       │
│ pdf converter / packager / editor                   │
└─────────────────────────────────────────────────────┘
             ▲                         ▲
             │                         │
          CLI                         FastAPI
                                         │
                                      Vue UI
                                         │
                                PyInstaller launcher
```

### 7.1 架构纪律

- 业务规则只能出现在 `ro_generator`。
- API 只处理 HTTP、session、临时文件和序列化。
- 前端只做交互和呈现，不重复主体、价格、数量或校验规则。
- 启动器只负责进程和桌面生命周期。
- 模板坐标只写在 YAML mapping。

### 7.2 部署形态

启动器探测随机 localhost 端口，在后台线程运行 uvicorn，等待 `/api/health` 就绪后打开默认浏览器。托盘菜单负责重新打开页面和退出。

第二次启动时读取临时锁文件并探测已有实例；服务仍可用时只打开已有地址。

### 7.3 Session 和缓存

- 同一 base 路径复用 API session。
- session 一小时无活动后清理，导出临时目录随之删除。
- `WorkbookSnapshot` 缓存按文件路径和文件签名命中。
- 编辑成功后显式失效缓存。

## 8. 工作台流程

### 8.1 加载

用户在系统设置中输入 `.xlsx` 绝对路径。路径检查返回文件大小和 Sheet 列表；打开 session 后返回 PO 摘要和 Invoice 票据组列表。

### 8.2 数据检查

- PO 视角：显示 `PO record` headers/rows，支持字段级写回。
- Invoice 视角：显示票据组成员出货行、主体、发票号和校验结果，只读。

### 8.3 单据预览

- PO 视角只承载 PI/PO。
- Invoice 视角承载 RO 的 INVOICE/PL 和 SK/YM 的 CI/RO_PL；PF 的 Invoice 与 PL 分别进入独立预览页。
- RO 的 INVOICE+PL、CI+RO_PL 可以连续预览。
- 点击预览字段展示来源详情。

### 8.4 导出确认

用户选择主体、单据和 `xlsx`/`pdf` 格式。多个结果打成 ZIP 后通过 `/api/download` 下载。

## 9. 数据源

每个 Profile 的 base workbook 都有三张逻辑 Sheet，实际名称和行号由各自 schema 声明：

| Profile | 产品主数据 | PO/出货记录 | 客户订单 |
| --- | --- | --- | --- |
| RO | `DATA BASE`（4/5） | `PO record`（4/5） | `客户PO`（1/2） |
| PF | `DATA BASE TEMPLATE`（2/3） | `PO RECORD 26`（1/2） | `new PO template`（1/2） |

括号内为“表头行/首行数据”。字段名称和别名以 `customer_profiles/<profile_id>/base_schema.yaml` 为准。

主要关联：

```text
PO record.SAP Number ↔ DATA BASE.SAP
(PO record.PO NO., PO record.SAP Number)
  ↔ (客户PO.Purchasing Document, 客户PO.Material)
```

## 10. 业务规则

### 10.1 主体和价格

- RO Category 1/2 → YM、3 → SK；PF 的 Combo/Single Rod/Single Reel 归一为 1/2/3 后使用同一主体过滤。
- 价格按单据上下文、seller 和 Category 从 `DATA BASE` 价格矩阵读取。
- 价格列配置位于 `base_schema.yaml`；字段来源展示由 `line_rules.py` 生成。
- 缺价格时核心包以高严重度 warning 标记，并使用 0 继续构建供用户复核。

### 10.2 数量

- PI/PO：`客户PO.Order Quantity`。
- RO INVOICE/PL/CI/RO_PL：`PO record.SHIP QTY`。
- PF INVOICE/PL：根据 `INV#` 中的 YYMM 读取 `PO RECORD 26` 的 `2601`–`2612` 月度数量列。
- 票据组只纳入当前 Profile 出货数量大于 0 的行。

### 10.3 发票号

- RO SK/YM：`SK/YM INVOICE NO.`；GS PTE：`INV#`；EMAX PTE：展示/导出为 `INV#-P`。
- PF GS/EMAX：保持 `INV#` 原值，不追加 RO 后缀。

### 10.4 票据组

票据组以 `INV#` 为主要标识；没有 `INV#` 时使用 `SK/YM INVOICE NO.`。相同标识可以聚合多个 PO。group key 是规范化标识的 SHA-256 前 16 位摘要，前缀为 `invgrp::`。

### 10.5 计算

- `amount = quantity × unit_price`
- `CTNS = quantity / 外箱`
- `TOTAL CBM = L × W × H / 1,000,000 × CTNS`
- RO PL 行净重/毛重 = 单箱重量 × CTNS。
- PF PL 以月度出货数量计算 CTNS，按 PO record 原订单总量折算净重/毛重，并按尺寸计算 CBM。
- 合计由 `DocumentModel` 计算，金额使用 `Decimal`

当 Excel 公式的缓存值为 `None` 时，resolver 按规则回退计算并产生 `FORMULA_FALLBACK` 警告。

## 11. 校验体系

| 输出 | 含义 | 是否允许导出 |
| --- | --- | :---: |
| `blocking_error` | 结构或关键业务数据不满足要求 | 否 |
| `warning` | 可继续但需要复核，严重度为 high/low | 是 |
| `missing_inputs` | 存在多个合法候选，需要选择 | 否，选择后重试 |

结构校验覆盖当前 Profile 的三张 Sheet 和最小必需表头。行级校验覆盖 PO、SAP、客户订单数量、主体行、发票号和模板 mapping。PF 额外返回 `MOQ_NOT_MET`、`FULL_CARTON_NOT_MET` high warning；同一 PO 的相同 SAP 先聚合再检查。

机器可识别的错误 code 属于接口契约，不能为了文案调整随意改名。

## 12. 输出和交付

### 12.1 文件名

文件名由 `packager.py` 统一生成并清理空格、斜杠等不安全字符。

PO 作用域示例：

```text
GS_PTE-GS-PI-4500030844.xlsx
GS_PTE-GS-PO-4500030844.xlsx
GS_PTE-GS-INVOICE-4500030844-INV-001.xlsx
GS_PTE-GS-INVOICE&PL-4500030844-INV-001.xlsx
```

Invoice 票据组示例：

```text
GS_PTE-GS-INVOICE&PL-INV-001.xlsx
YM-RO-CI&PL-YM-INV-001.xlsx
RO-INV-001.zip
```

不要在其他模块重复拼接文件名。

### 12.2 工作台交付

工作台把结果写入 session 临时目录，通过受路径边界保护的下载端点返回。浏览器下载完成后，用户负责保存文件；服务端不维护永久导出历史。

### 12.3 CLI 交付

CLI 写入 `--output-dir`，支持 `overwrite`、`rename`、`abort` 冲突策略，以及 `xlsx`/`zip` 输出。`--profile` 可显式选择 Customer Profile，缺省为 `ro`；CLI 不读取 GUI 工作区状态。

### 12.4 PDF

PDF 复用 Excel renderer：先写模板，再调用 LibreOffice `soffice --headless --convert-to pdf`。转换使用独立 LibreOffice user profile，避免与用户正在运行的实例争锁。

## 13. 模板策略

当前两个 Profile 共 22 个 workbook 和 28 份 mapping：

| Profile | workbook | mapping |
| --- | ---: | ---: |
| RO | 12 | 18 |
| PF | 10 | 10 |

RO 的 Invoice 与 PL、CI 与 RO_PL 分别共享双 Sheet workbook，但各自使用独立 mapping。PF 的 Invoice 与 PL 使用不同 workbook，预览分别进入独立页面，组合导出时分别渲染并打 ZIP。

mapping 必须声明模板、Sheet、`template_version`、header、明细起始行、样式来源行、列和合计位置。模板修改必须同时更新 mapping 与回归测试。

## 14. 当前质量基线

- Python 3.11 strict mypy、Ruff 和 pytest。
- 前端 type-check、build 和 Playwright E2E。
- E2E CI 安装 LibreOffice，覆盖真实 PDF 下载路径。
- macOS/Windows 启动器由独立 CI workflow 构建。

截至 2026-08-09，Python 套件通过 531 个测试，默认 Playwright 回归包含 29 个场景，另有 1 个隔离真实 HTTP 验收场景。

## 15. 已知限制与风险

- base 文件是共享可写文件；当前不适合多人同时编辑。
- PO 编辑直接落盘且没有撤销，业务使用前应备份。
- LibreOffice 不随应用打包，PDF 可用性依赖本机环境。
- 模板和 mapping 必须人工同步。
- 真实业务文件不入库，自动测试主要依赖合成 fixture。
- 产品发布版本以根目录 `VERSION` 为唯一手写源；Python 包 metadata、FastAPI、前端构建、PyInstaller 和安装包说明由同步脚本或构建流程派生。Profile、workspace schema 和模板版本仍保持独立。
- PF Invoice 的 cost breakdown 预留区尚无批准的数据来源，当前保持空白，不自动推导。
- PF 新 PO 在进入 `PO RECORD 26` 前只支持 PI/PO；有月度出货记录后才进入 Invoice/PL 票据组。

## 16. 后续路线

已实现：

- [多客户工作区](multi-customer-workspace-design.md)：本地单用户模式，通过 Customer Profile 隔离客户规则和资产，通过顶部工作区切换器选择当前客户/base 文件；`ro` 与 `pf` 已可用。实施记录见[多客户工作区实施方案](../development/multi-customer-workspace-implementation-plan.md)。

以下候选能力尚未确认，只有真实需求确认后再立项：

- 撤销/重做和导出版本历史。
- 模板预览/诊断工具。
- CLI 暴露 PDF 输出。
- 源字段到预览位置的反向高亮。
- 多 PO 自动批处理入口。
- Agent/MCP 壳层。
- 云端协作、权限和 ERP/SAP 集成。
- 统一版本元数据、签名和发布自动化。
