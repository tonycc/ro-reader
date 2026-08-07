# RO 单据工作台产品说明

> 状态：当前实现基准，最近核对于 2026-08-07。

## 1. 产品概述

RO 单据工作台是面向 RO 订单业务的本地单据装配工具。它把 Excel 数据检查、单据预览和导出放在同一个工作空间中，减少人工查表和复制。

对外的核心业务单据是 PI、PO、Invoice 和 Packing List；核心包还使用 `CI`、`RO_PL` 表示 SK/YM 的 RO 版商业发票和装箱单。

工作台不是编号生成器。`INV#`、`SK/YM INVOICE NO.`、SK/YM PI 编号和业务日期必须来自 base 文件或人工维护，工具不得自动编造。

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

## 4. 体验原则

### 4.1 先预览，再导出

预览展示的是核心包装配后的领域值和模板展示配置。导出只是把已经检查过的结果写入模板，不应再引入新的业务计算。

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
- Invoice 视角承载 INVOICE/PL 和 SK/YM 的 CI/RO_PL。
- INVOICE+PL、CI+RO_PL 可以连续预览。
- 点击预览字段展示来源详情。

### 8.4 导出确认

用户选择主体、单据和 `xlsx`/`pdf` 格式。多个结果打成 ZIP 后通过 `/api/download` 下载。

## 9. 数据源

base workbook 有三张必需 Sheet：

| Sheet | 表头行 | 首行数据 | 作用 |
| --- | ---: | ---: | --- |
| `DATA BASE` | 4 | 5 | 产品、分类、主体价格和包装主数据 |
| `PO record` | 4 | 5 | PO、出货、发票、箱数和物流数据 |
| `客户PO` | 1 | 2 | 客户订单数量、行号、日期、收货和制造商信息 |

字段名称和别名以 `templates/base_schema.yaml` 为准。

主要关联：

```text
PO record.SAP Number ↔ DATA BASE.SAP
(PO record.PO NO., PO record.SAP Number)
  ↔ (客户PO.Purchasing Document, 客户PO.Material)
```

## 10. 业务规则

### 10.1 主体和价格

- Category 1/2 → YM；Category 3 → SK。
- 价格按单据上下文、seller 和 Category 从 `DATA BASE` 价格矩阵读取。
- 价格列配置位于 `base_schema.yaml`；字段来源展示由 `line_rules.py` 生成。
- 缺价格时核心包以高严重度 warning 标记，并使用 0 继续构建供用户复核。

### 10.2 数量

- PI/PO：`客户PO.Order Quantity`。
- INVOICE/PL/CI/RO_PL：`PO record.SHIP QTY`。
- 票据组只纳入 `SHIP QTY > 0` 的行。

### 10.3 发票号

- SK/YM：`SK/YM INVOICE NO.`。
- GS PTE：`INV#`。
- EMAX PTE：展示/导出为 `INV#-P`，输入过滤兼容未加后缀的原值。

### 10.4 票据组

票据组以 `INV#` 为主要标识；没有 `INV#` 时使用 `SK/YM INVOICE NO.`。相同标识可以聚合多个 PO。group key 是规范化标识的 SHA-256 前 16 位摘要，前缀为 `invgrp::`。

### 10.5 计算

- `amount = quantity × unit_price`
- `CTNS = quantity / 外箱`
- `TOTAL CBM = L × W × H / 1,000,000 × CTNS`
- PL 行净重/毛重 = 单箱重量 × CTNS
- 合计由 `DocumentModel` 计算，金额使用 `Decimal`

当 Excel 公式的缓存值为 `None` 时，resolver 按规则回退计算并产生 `FORMULA_FALLBACK` 警告。

## 11. 校验体系

| 输出 | 含义 | 是否允许导出 |
| --- | --- | :---: |
| `blocking_error` | 结构或关键业务数据不满足要求 | 否 |
| `warning` | 可继续但需要复核，严重度为 high/low | 是 |
| `missing_inputs` | 存在多个合法候选，需要选择 | 否，选择后重试 |

结构校验覆盖三张 Sheet 和最小必需表头。行级校验覆盖 PO、SAP、客户订单数量、主体行、发票号和模板 mapping。

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

CLI 写入 `--output-dir`，支持 `overwrite`、`rename`、`abort` 冲突策略，以及 `xlsx`/`zip` 输出。

### 12.4 PDF

PDF 复用 Excel renderer：先写模板，再调用 LibreOffice `soffice --headless --convert-to pdf`。转换使用独立 LibreOffice user profile，避免与用户正在运行的实例争锁。

## 13. 模板策略

当前有 12 个 workbook 和 18 份 mapping：

| 主体 | workbook | mapping |
| --- | ---: | ---: |
| GS PTE | 3 | 4 |
| EMAX PTE | 3 | 4 |
| SK | 3 | 5 |
| YM | 3 | 5 |

Invoice 与 PL、CI 与 RO_PL 分别共享双 Sheet workbook，但各自使用独立 mapping。

mapping 必须声明模板、Sheet、`template_version`、header、明细起始行、样式来源行、列和合计位置。模板修改必须同时更新 mapping 与回归测试。

## 14. 当前质量基线

- Python 3.11 strict mypy、Ruff 和 pytest。
- 前端 type-check、build 和 Playwright E2E。
- E2E CI 安装 LibreOffice，覆盖真实 PDF 下载路径。
- macOS/Windows 启动器由独立 CI workflow 构建。

截至 2026-08-07，Python 套件通过 465 个测试，Playwright 文件包含 23 个场景。

## 15. 已知限制与风险

- base 文件是共享可写文件；当前不适合多人同时编辑。
- PO 编辑直接落盘且没有撤销，业务使用前应备份。
- LibreOffice 不随应用打包，PDF 可用性依赖本机环境。
- 模板和 mapping 必须人工同步。
- 真实业务文件不入库，自动测试主要依赖合成 fixture。
- 包版本分别存在于构建 workflow、Python manifest、FastAPI metadata 和前端界面，发布时需要统一核对。

## 16. 后续路线

以下均未实现，只有真实需求确认后再立项：

- 撤销/重做和导出版本历史。
- 模板预览/诊断工具。
- CLI 暴露 PDF 输出。
- 源字段到预览位置的反向高亮。
- 多 PO 自动批处理入口。
- Agent/MCP 壳层。
- 云端协作、权限和 ERP/SAP 集成。
- 统一版本元数据、签名和发布自动化。
