# 单据领域实现参考

从仓库入口迁出的领域约束；仅在修改对应数据、模板、导出或 session 路径时读取。实际参数以当前代码与 schema 为准，发现漂移时同步修正。

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

- PI/PO 数量：当前 Profile 的客户订单 `Order Quantity`。按 `Material` 匹配客户PO行；命中单行直接沿用（不校验 Item 对应关系），命中多行时再用 PO record `ITEM LINE#` 与客户PO `Item` 对位（`00010` 与 `10` 等价），无法唯一对位时以 `QTY_ITEM_MISMATCH` 阻断，不静默取第一行。
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
