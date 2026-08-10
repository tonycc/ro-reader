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
pnpm run test:e2e:http
```

`lint` 和 `test` 当前是占位 script；不要把它们视为有效的 lint/unit-test 覆盖。前端质量门槛是 TypeScript、生产构建、默认 Playwright 回归和独立真实 HTTP 验收。

Playwright 不复用用户正在运行的 `54321` 服务或用户工作区配置：默认回归使用临时配置目录及 `54322/6174`，真实 HTTP 验收使用 `54323/6175`。生产开发代理仍保持 `54321`。

## 结构

```text
src/
  App.vue
  stores/
    api.ts            HTTP 类型、session header、ApiError
    workbench.ts      业务对象选择、数据、预览、导出状态
    workspace.ts      Profile、工作区、bootstrap 和激活状态
  services/
    workspace.ts      WorkspaceService 类型契约
    workspace.http.ts 真实 FastAPI 工作区适配器
    workspace.mock.ts 仅用于 ?workspace-prototype=1 的交互评审
  components/
    layout/           TopBar、StatusBar
    workspace/        工作区切换器、设置、表单和状态
    po-list/          PO/Invoice 队列
    data-view/        PO/Invoice 检查
    preview/          结构化单据预览
    export/           导出确认
    common/           LibreOffice 提示
  styles/tokens.css
e2e/workbench.spec.ts
e2e/workspace-prototype.spec.ts
e2e/workspace-http.spec.ts  # 隔离临时配置的真实 HTTP 验收
```

## 边界

- 不在前端计算价格、数量、主体、发票号或校验结果。
- 不在前端拼接最终文件名。
- RO 的组合预览可以并行请求真实单据；PF 的 Invoice 与 PL 使用独立预览页。合并 workbook/PDF 由核心包负责。
- PDF 转换器缺失时显示 API 返回的错误，不自动降级。
- 当前没有 SheetJS；预览来自后端 `PreviewPayload` JSON。
- 正式模式通过 `/api/bootstrap` 和 `/api/workspaces*` 管理工作区；旧 `ro-workbench-base-path` 只在创建并激活 RO 工作区成功后迁移删除。
- 编辑当前工作区的 Profile/base 后，旧 session 保留但 store 标记 `needsActivation`；重新激活成功后才替换 PO、Invoice 和 session 状态。
- `ro` 与 `pf` 都是正式可用 Profile；`?workspace-prototype=1` 仅用于开发环境的工作区交互评审。
- PF 的 MOQ/整箱判断来自后端 warning，前端只在 `IssueSummaryBar` 展示。
- 只有真实 PO 记录行可双击编辑；客户 PO 先行的投影行显示只读提示，避免提交无效源行号。

详细交互见 [`../docs/development/ro-document-workbench-ui-design.md`](../docs/development/ro-document-workbench-ui-design.md)。
