# Agent 字段修复操作手册

> 本手册面向开发者与 Agent，目标是把“发现字段问题 -> 定位根因 -> 修改正确层级 -> 验证结果”收敛成一套可重复执行的标准流程。

配套文档：

- 总体规则与字段链路见 [统一字段映射与配置指南](./unified-field-mapping-guide.md)
- 真实修复示例见 [字段修复案例库](./field-fix-case-library.md)

## 1. 适用范围

适用于以下问题：

- 模板中的字段值不正确
- 预览中的字段值不正确
- Excel 导出的字段位置不正确
- 单据数量、金额、装箱字段口径不正确
- header 固定文案、明细固定列、预览条款字段配置错误

不适用于：

- 与字段映射无关的 UI 样式问题
- 启动器、网络路由、会话管理问题
- 模板版式大改但尚未确定业务规则的问题

## 2. 总体流程

```text
发现问题
  ↓
确认问题类别（值错 / 位置错 / 顺序错 / 口径错）
  ↓
判断字段类型（base / 口径 / header 固定 / row_fixed / 纯预览）
  ↓
定位根因层级
  ↓
只修改最靠近根因的一层
  ↓
补充或更新测试
  ↓
验证预览与导出结果
```

## 3. 五步执行法

### 3.1 第一步：记录问题现场

先记录以下信息：

- 单据类型：`PI` / `PO` / `INVOICE` / `PL`
- 主体 / 链段：如 `GS PTE -> EMAX PTE`
- 出错字段名
- 当前值
- 期望值
- 当前是预览错、Excel 错，还是两者都错
- 当前单元格位置或预览区域位置

如果缺少这一步，后续很容易误改到错误层级。

### 3.2 第二步：判断问题类型

| 问题类型 | 典型现象 |
| --- | --- |
| 值错 | 单元格位置对，但值不对 |
| 位置错 | 值对，但写到了错误格子 |
| 顺序错 | 预览条款或展示顺序不对 |
| 口径错 | `Invoice` 用了 `FINALQTY` 等 |
| 预览错但 Excel 对 | 只影响 `document_preview.py` 或 preview YAML |
| Excel 错但预览对 | 只影响 mapping YAML 或 `renderer.py` |

### 3.3 第三步：判断字段类型

| 字段类型 | 典型字段 | 首选修改位置 |
| --- | --- | --- |
| Base 列映射 | `SAP`、`FINALQTY`、`INV#` | `templates/base_schema.yaml` |
| Base 取值/回退 | `description`、`carton_count`、`net_weight` | `resolver.py` |
| 单据口径 | `quantity`、`amount`、发票过滤 | `document_model.py` |
| 表头位置 | `invoice_no -> H6` | 对应 mapping YAML `header` |
| 表头固定文案 | `payment_terms`、`final_destination` | mapping YAML `header_fixed` |
| 明细固定列 | `PCS`、`KGS`、`China` | mapping YAML `lines.row_fixed` |
| 明细动态列 | `quantity`、`amount` | mapping YAML `lines.columns` |
| 明细样式参考行 | `style_source_row` | mapping YAML `lines.style_source_row` |
| 表格表头保护行 | `table_header_row` | mapping YAML `table_header_row` |
| 纯预览条款 | `incoterm`、`term`、`from`、`to` | `preview_content.static_terms` |
| 预览条款顺序 | `payment_terms`、`port_of_loading` 顺序 | `preview_content.terms_fields` |
| 预览布局 | `title`、`seller_info`、`terms` 区块位置 | `preview_content.layout` |
| 预览解析 | `resolved_values`、`terms` 生成不对 | `document_preview.py` |
| Excel 写入 | 样式、写值、插值不对 | `renderer.py` |

### 3.4 第四步：只改根因层

核心原则：

- 不要在下游做掩盖式修复
- 优先修改最靠近问题根因的那一层

错误示例：

- `Invoice` 数量口径错，却去改模板单元格
- `payment_terms` 作为 header 固定值，却改成 `static_terms`
- `PCS` 每行都固定，却去改 `DocumentLine.unit_label`

正确示例：

- 列名变了：改 `base_schema.yaml`
- 回退规则错：改 `resolver.py`
- 单据口径错：改 `document_model.py`
- 单元格位置错：改 mapping YAML
- 导出最后一行格式错：先看 `lines.style_source_row`
- 表格表头被清掉：先看 `table_header_row`
- 纯预览条款错：改 `static_terms`

### 3.5 第五步：做验证

至少验证：

- 预览是否正确
- 导出是否正确
- 相关测试是否通过

推荐验证顺序：

1. 跑相关单测
2. 生成对应预览
3. 必要时导出 Excel 核对单元格

## 4. 速查口诀

- 列名变了：先看 `base_schema.yaml`
- 值来源错了：先看 `resolver.py`
- 单据口径错了：先看 `document_model.py`
- 格子写错了：先看 mapping YAML
- 每行固定值错了：先看 `lines.row_fixed`
- 预览条款错了：先看 `header_fixed` / `terms_fields` / `static_terms`
- 预览值对不上 YAML：再看 `document_preview.py`
- Excel 导出不对但预览对：再看 `renderer.py`

## 5. 标准提示模板

### 5.1 通用模板

```text
请帮我修复一个字段映射问题。

问题字段：
- 单据类型：
- 主体 / 链段：
- 字段名：

当前现象：
- 当前值：
- 当前位置：
- 是预览错、Excel 错，还是两者都错：

期望行为：
- 期望值：
- 期望来源：
- 期望写入位置：

已知信息：
- 是否属于 header 字段：
- 是否属于每行固定列：
- 是否只在预览展示：
- 是否受单据类型口径影响：

请按以下方式处理：
1. 先分析问题原因
2. 判断应该修改哪一层：
   - `base_schema.yaml`
   - `resolver.py`
   - `document_model.py`
   - mapping YAML
   - `document_preview.py`
   - `renderer.py`
3. 只修改最靠近根因的那一层，不要做掩盖式修复
4. 如有必要，同步更新测试
5. 最后说明修改原因与影响范围
```

### 5.2 YAML 配置模板

```text
请帮我修复模板 YAML 配置问题。

文件：
- mapping 文件路径：

问题字段：
- 字段名：
- 当前配置块：
- 当前值：

期望行为：
- 应属于：
  - `header_fixed`
  - `terms_fields`
  - `static_terms`
  - `lines.row_fixed`
  - `lines.columns`
- 期望值：

请先分析问题原因，再只修改正确的配置块。
如果你发现这是架构边界问题，请明确指出原因。
```

### 5.3 字段来源模板

```text
请帮我修复字段来源问题。

问题字段：
- 字段名：
- 当前来源：
- 期望来源：

问题范围：
- 影响单据：
- 影响主体：
- 影响预览 / 导出：

请按这条链路排查：
`base_schema -> resolver -> document_model -> preview/render`

要求：
1. 先分析问题原因
2. 明确根因层级
3. 只修改根因层
4. 补充必要测试
5. 输出变更摘要
```

## 6. 边界规则

### 6.1 `header_fixed`

只放：

- 有 header 单元格位置
- 且值固定不来自业务模型

不要放：

- 每行固定列
- 纯预览字段

### 6.2 `lines.row_fixed`

只放：

- 每一行都一样的固定列值

例如：

- `PCS`
- `KGS`
- `CBM`
- `China`

### 6.3 `static_terms`

只放：

- 只在预览条款区展示
- 不属于 header 字段

例如：

- `incoterm`
- `term`
- `from`
- `to`

## 7. 推荐测试策略

字段修复后优先补哪类测试：

| 变更层级 | 推荐测试 |
| --- | --- |
| `base_schema.yaml` | schema / reader / resolver 相关测试 |
| `resolver.py` | resolver 单测 |
| `document_model.py` | document_model 单测 |
| mapping YAML | generator / preview 集成测试 |
| `document_preview.py` | preview 行为测试 |
| `renderer.py` | renderer / generator 导出测试 |

## 8. 与其他文档的关系

- 字段总规则：见 [统一字段映射与配置指南](./unified-field-mapping-guide.md)
- 真实修复案例：见 [字段修复案例库](./field-fix-case-library.md)

如果手册与代码实现冲突，以代码和主文档为准，并及时更新本手册。
