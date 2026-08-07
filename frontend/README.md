# RO Workbench Frontend

Vue 3 + TypeScript + Pinia 前端。业务规则由 Python `ro_generator` 提供，前端只负责交互、状态和结构化预览展示。

## 开发

先在仓库根目录准备后端和合成 fixture：

```bash
uv sync --all-packages
uv run python tests/fixtures/generate_synthetic_base.py
uv run uvicorn ro_workbench_api.app:app --reload --host 127.0.0.1 --port 54321
```

再启动前端：

```bash
cd frontend
pnpm install
pnpm run dev
```

Vite 开发服务器把 `/api` 代理到 `127.0.0.1:54321`。

## 命令

```bash
pnpm run type-check
pnpm run build
pnpm run test:e2e
```

`lint` 和 `test` 当前是占位 script；不要把它们视为有效的 lint/unit-test 覆盖。前端质量门槛是 TypeScript、生产构建和 Playwright。

## 结构

```text
src/
  App.vue
  stores/
    api.ts            HTTP 类型、session header、ApiError
    workbench.ts      业务对象选择、数据、预览、导出状态
  components/
    layout/           TopBar、StatusBar
    po-list/          PO/Invoice 队列
    data-view/        PO/Invoice 检查
    preview/          结构化单据预览
    export/           导出确认
    common/           LibreOffice 提示
  styles/tokens.css
e2e/workbench.spec.ts
```

## 边界

- 不在前端计算价格、数量、主体、发票号或校验结果。
- 不在前端拼接最终文件名。
- 组合预览可以并行请求真实单据，但合并 workbook/PDF 由核心包负责。
- PDF 转换器缺失时显示 API 返回的错误，不自动降级。
- 当前没有 SheetJS；预览来自后端 `PreviewPayload` JSON。

详细交互见 [`../docs/development/ro-document-workbench-ui-design.md`](../docs/development/ro-document-workbench-ui-design.md)。
