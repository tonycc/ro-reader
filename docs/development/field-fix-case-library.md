# 字段修复案例库

> 本文档沉淀字段映射修复的真实案例，目标是帮助开发者和 Agent 快速类比类似问题。

配套文档：

- 总体规则见 [统一字段映射与配置指南](./unified-field-mapping-guide.md)
- 标准操作流程见 [Agent 字段修复操作手册](./agent-field-fix-playbook.md)

## 1. 使用方式

遇到字段问题时，优先按以下顺序使用本文档：

1. 先判断问题类型
2. 找最接近的案例
3. 对照案例里的“根因层级”和“修改文件”
4. 再回到代码里动手修改

## 2. 案例索引

| 案例 | 问题类型 | 根因层级 |
| --- | --- | --- |
| 案例 1 | header 固定文案值错误 | `header_fixed` |
| 案例 2 | 纯预览条款值错误 | `preview_content.static_terms` |
| 案例 3 | 明细固定列配置错误 | `lines.row_fixed` |
| 案例 4 | 单据数量口径错误 | `document_model.py` |
| 案例 5 | 字段来源列错误 | `base_schema.yaml` / `resolver.py` |
| 案例 6 | 单元格位置错误 | mapping YAML `header` / `lines.columns` |
| 案例 7 | 预览条款顺序错误 | `preview_content.terms_fields` |
| 案例 8 | 预览对、导出错 | `renderer.py` / mapping YAML |
| 案例 9 | 导出最后一行格式错误 | `lines.style_source_row` / `renderer.py` |

## 3. 案例详情

### 案例 1：`payment_terms` 显示值错误

现象：

- `EMAX PI` 的 `payment_terms` 显示成错误文案
- 预览和 Excel 都错

判断：

- 这是 header 固定文案
- 字段在模板 header 中有明确位置
- 问题不属于单据口径，也不属于纯预览条款

根因层级：

- `header_fixed`

修改位置：

- 对应 mapping YAML 的 `header_fixed.payment_terms`

不要这样改：

- 不要改 `static_terms`
- 不要改 `document_model.py`
- 不要改 `renderer.py`

验证：

- 预览中的条款区是否更新
- Excel header 单元格是否更新

### 案例 2：`incoterm` 预览值错误

现象：

- 预览里的 `incoterm` 错了
- Excel 里没有对应 header 单元格

判断：

- `incoterm` 是纯预览字段
- 不属于 header

根因层级：

- `preview_content.static_terms`

修改位置：

- 对应 mapping YAML 的 `preview_content.static_terms.incoterm`

不要这样改：

- 不要把它塞进 `header_fixed`
- 不要去改 `document_preview.py`，除非 YAML 已经正确但预览仍不对

验证：

- 只需验证预览条款区

### 案例 3：`PCS` / `KGS` / `China` 错误

现象：

- 明细表格里每一行固定显示的单位或原产地错了
- 例如：
  - `PCS` 应显示在每行单位列
  - `China` 应显示在每行原产地列

判断：

- 这是每一行都固定的值
- 不属于 header
- 不属于业务字段来源

根因层级：

- `lines.row_fixed`

修改位置：

- 对应 mapping YAML 的 `lines.row_fixed`

不要这样改：

- 不要改 `header_fixed`
- 不要改 `DocumentLine`
- 不要把 `PCS` 当作 `static_terms`

验证：

- 预览表格每一行是否正确
- Excel 明细行每一行是否正确

### 案例 4：`Invoice` 数量口径错误

现象：

- `Invoice` 中 `quantity` 错误地使用了 `FINALQTY`
- 正确口径应该是 `SHIP QTY`

判断：

- 这是单据口径问题
- 不是模板位置问题

根因层级：

- `document_model.py`

修改位置：

- `_slice_by_invoice()` 或相关组装逻辑

不要这样改：

- 不要改 mapping YAML
- 不要改 `resolver.py` 的原始字段读取逻辑，除非 `ship_qty` 本身读错了

验证：

- `Invoice` 使用 `SHIP QTY`
- `PI / PO` 仍保持 `FINALQTY`

### 案例 5：`ship_to` 来自错误列

现象：

- `ship_to` 当前来自错误列或错误 sheet
- 例如本应来自 `客户PO`，实际来自 `PO record`

判断：

- 这是字段来源问题
- 先判断是“列名变化”还是“业务规则变化”

根因层级：

- 可能是：
  - `templates/base_schema.yaml`
  - `resolver.py`

修改位置：

- 如果只是表头变了：优先改 `base_schema.yaml`
- 如果来源规则变了：改 `resolver.py`

不要这样改：

- 不要在 `document_preview.py` 里临时覆盖
- 不要在模板里写死错误值

验证：

- `OrderLine.ship_to`
- `DocumentModel.ship_to`
- 预览 / Excel header

### 案例 6：字段写到了错误单元格

现象：

- 值是正确的
- 但 Excel 里写到了错误位置

判断：

- 这是位置映射问题

根因层级：

- mapping YAML

修改位置：

- 表头字段：改 `header`
- 明细字段：改 `lines.columns`
- 合计字段：改 `totals`

不要这样改：

- 不要去改上游取值逻辑

验证：

- 重新导出 Excel，确认单元格正确

### 案例 7：预览条款顺序错误

现象：

- `payment_terms`、`port_of_loading`、`final_destination` 出现顺序不符合预期

判断：

- 值本身对
- 顺序错

根因层级：

- `preview_content.terms_fields`

修改位置：

- 调整 `terms_fields` 数组顺序

不要这样改：

- 不要改 `header_fixed` 的值
- 不要改 `document_preview.py`，除非顺序逻辑本身有 bug

验证：

- 仅验证预览条款顺序

### 案例 8：预览正确，但导出错误

现象：

- 预览里字段显示正常
- Excel 导出结果错误

判断：

- 上游模型和预览很可能是正确的
- 问题更可能在 Excel 写入层

根因层级：

- `renderer.py`
- 或 mapping YAML

修改位置：

- 先看 mapping YAML 是否写对位置
- 若位置对但 Excel 仍错，再看 `renderer.py`

不要这样改：

- 不要优先改 `document_model.py`

验证：

- 导出 Excel 单元格
- 必要时对比预览与导出

### 案例 9：最后一行单价显示成日期

现象：

- 预览里的明细值正确
- Excel 导出后只有最后一行或某一行的单价/数量/金额格式异常
- 例如 `USD Unit Price` 显示成 `14/Jan/00`

判断：

- 这通常不是业务值算错，而是 Excel 单元格样式错了
- 如果只在导出里出现，优先怀疑模板预留数据区样式不一致

根因层级：

- mapping YAML 的 `lines.style_source_row`
- `renderer.py` 的预留明细区样式处理

修改位置：

- 先检查 `style_source_row` 是否指向真实明细样式行，而不是表头或脏样板行
- 如果 mapping 正确但预留区样式仍不一致，再看 `renderer.py` 是否在写值前统一了预留明细区样式

不要这样改：

- 不要先改 `document_model.py`
- 不要先改 `document_preview.py`
- 不要直接把错误值硬编码成字符串去规避 Excel 格式问题

验证：

- 导出 Excel 中异常行与正常行的 `number_format` 是否一致
- 异常列的值是否仍为数值，而不是被格式化成日期文本
- 至少覆盖一条会写入到预留区末尾的回归测试

## 4. 案例复用规则

如果新问题和已有案例不完全一致，优先按下列维度做类比：

1. 是值错还是位置错
2. 是 header、明细、预览条款，还是单据口径
3. 是固定值，还是动态业务值
4. 是预览问题、导出问题，还是两者都有

只要这四项相同，通常就可以复用同一类修复策略。

## 5. 推荐补案例的标准

后续出现新的高频字段问题时，建议按下面结构追加：

```text
### 案例 N：<问题标题>

现象
判断
根因层级
修改位置
不要这样改
验证
```

建议优先补这几类新案例：

- `row_fixed` 与 `columns` 混淆
- `header_fixed` 与 `static_terms` 混淆
- `renderer.py` 与 mapping YAML 边界不清
- `客户PO` 引入后的来源切换

## 6. 与其他文档的关系

- 规则总表：见 [统一字段映射与配置指南](./unified-field-mapping-guide.md)
- 操作步骤：见 [Agent 字段修复操作手册](./agent-field-fix-playbook.md)

如果案例与当前代码实现冲突，以代码和主文档为准，并同步回写本案例库。
