# Phase 0 spike 结论汇总

> 三个 spike 的最终选型与发现。Phase 1 启动前必读。

---

## Spike A：模板样式保留 ✅ 通过

**测试位置**：`tests/spike/test_template_style_preservation.py`（10 个自动化断言全部通过）

**最终方案**：openpyxl `insert_rows` + 自定义样式复制（`copy_row_style`） + **手动平移 `row_dimensions`**。

**关键发现**：

1. **`openpyxl.insert_rows()` 不平移 `row_dimensions`**——只移动单元格内容、公式、合并区域。如果直接用，插入位置之后所有行的行高都会停留在原行号上，结果是新行套用了下一行的高度，下一行套用了再下一行的高度。
2. 解决方案：在调用 `insert_rows` 之前，倒序把 `row_dimensions` 的行号 += 1。详见 `insert_styled_row()` 实现。
3. `insert_rows` 的公式平移（`SUM(F16:F26)` → `SUM(F16:F27)`）是自动正确的。
4. 合并单元格区域在插入位置之前的不动，之后的随之下移，无需手动处理。
5. 列宽 (`column_dimensions[col].width`) 完全不受影响。
6. 打印区域 (`print_area`) 在 GS Invoice 模板中本身为空，未触发副作用。

**回退方案**：未触发。本机无 LibreOffice，跳过 PDF 视觉对比环节，但所有结构性属性都已自动化断言。

**Phase 1 影响**：

- `ro_generator/renderer.py` 的"插入行"逻辑直接复用 spike 的 `insert_styled_row` 和 `copy_row_style` 思路。
- 写一条警告：当输入数据行数 > 模板预留行数时，必须**先平移 row_dimensions 再 insert_rows**，否则行高错乱。

---

## Spike B：预览组件选型 ✅ 通过

**测试位置**：`frontend/spike-bundle/`（spike 完成后清理，结论保留在本文档）。

**最终选型**：**SheetJS（`xlsx` 包） + 后续配合自渲染容器**。

**测量结果**：

| 指标 | SheetJS | Luckysheet | 阈值（impl-guide §4.2） |
|---|---|---|---|
| Bundle gzip (JS) | **111 KB** | 626 KB | ≤ 800 KB |
| Bundle minified | 324 KB | 3037 KB | — |
| 字体资源 | 0 | fontawesome 137 KB gzip + 多 webfont | — |
| 合并单元格 | ✓ colspan/rowspan + `id="sjs-A1"` 坐标 | ✓ | 必须 |
| 数字格式 | 通过 `data-z` 属性传递 | 内置渲染 | 必须 |
| jQuery 依赖 | 无 | jquery@2.2.4（已废弃） | 越少越好 |
| Vue 3 兼容 | 框架无关 | IIFE 全局，需要适配层 | 必须 |
| 双向溯源 | sheet_to_html 自带坐标 ID | 内部 API，需 hack | 加分项 |

**关键发现**：

1. **SheetJS 是解析库 + 渲染输出工具，不是完整 UI 组件**。`sheet_to_html(ws)` 给出可直接渲染的 `<table>`，每个 `<td>` 带 `id="sjs-A1"` 的坐标 ID 和 `data-v` 原值、`data-z` 数字格式。这正好满足产品方案 §4.4 双向溯源（前端可以在 hover/click 时通过 ID 反查源字段）。
2. **Luckysheet 不适合本工作台**：体积 9 倍于 SheetJS，含 jQuery，是个完整在线 Excel 替代品，而 MVP 只需要"只读预览 + 高亮 overlay"。引入它会让安装包多 ~ 800 KB，且工作台的克制视觉风格与 Luckysheet 默认 UI 冲突。
3. SheetJS 的 `cellStyles: true` 选项可以读取格式信息（字体、对齐、边框），但 `sheet_to_html` 默认不输出这些样式——产品方案接受这一点：MVP 预览只保证**结构和数值**正确，**样式由最终下载的 .xlsx 文件保证**。
4. 视觉对比受本机限制（无法跑端到端），但 Phase 3 集成时可以补回：用 LibreOffice 转 PDF 做参考，与浏览器渲染的 SheetJS 表对比。

**回退方案**：未触发。如未来 SheetJS 不能满足"hover 显示样式细节"等扩展需求，可按 implementation-guide §4.2 回退到自研最小渲染或 `xlsx-viewer`。

**Phase 1 / 3 影响**：

- 锁定前端依赖：`xlsx@^0.18`，不再评估其他候选。
- 不需要在 SheetJS 之外引入额外的 grid/table 库；数据视图（产品方案 §8.3）由 `@tanstack/vue-table` 承担，与预览栏完全独立。
- 双向溯源在前端实现时，文档预览 hover/click 监听器直接读取 `target.id`（如 `sjs-F18`），通过坐标查后端构建的 source_index。
- UI 设计文档 §15 / §17 中"预览组件"项已在 Phase 0 选定，可清理待决问题 1。

---

## Spike C：启动器打包 ⏳ 待跑

> Spike C（PyInstaller + FastAPI + 自动开浏览器 + 托盘）尚未开始。

预期工作量 3–5 个工作日，本机为 macOS arm64。Windows + Apple Silicon Intel 的覆盖建议在 CI 矩阵中补做。

预期阻塞项：

- macOS 公证（Apple Developer ID）：本地无证书，预计只能验证 ad-hoc 签名 + 本机运行，公证流程作为文档产出。
- Windows 测试：本机不可达，需要在 GitHub Actions Windows runner 上跑构建后下载手工验证。

详细任务进入 implementation-guide §5.4。
