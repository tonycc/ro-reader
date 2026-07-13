# RO 工作台前端

Vue 3 + TypeScript + Pinia + Vite 构建。

## 开发

```bash
pnpm install
pnpm run dev              # Vite 开发服务器 :5173
pnpm run build            # vue-tsc + vite build → dist/
pnpm run test:e2e         # Playwright E2E（23 场景）
pnpm run type-check       # vue-tsc --noEmit
```

## 架构

```text
src/
  App.vue                    # 根组件：三 tab 布局 + 侧边栏
  main.ts                    # 入口：创建 app, pinia, router
  stores/
    api.ts                   # HTTP 客户端（X-Session-Id 管理）
    workbench.ts             # 工作台 Pinia store（session, PO, preview, export）
  components/
    layout/
      TopBar.vue             # 顶部栏：文件路径、撤销/重做、导出按钮
      StatusBar.vue          # 底部状态栏：PO 状态、阻断/警告数
    po-list/
      QueueSidebar.vue       # 左侧 PO 队列：搜索、筛选、多选
    data-view/
      DataCheckScreen.vue    # "数据检查" tab：PO 行表格 + inline 编辑
      InvoiceDataCheck.vue   # Invoice 数据检查：只读出货行 + 校验信息
      IssueSummaryBar.vue    # 阻断/警告问题摘要栏
    preview/
      PreviewScreen.vue      # "单据预览" tab：链段选择 + 文档预览
      PreviewDocumentPanel.vue  # 文档预览面板：header/table/totals/notes 区域渲染
      LayoutTopZone.vue      # 预览顶部区域渲染
    export/
      ExportScreen.vue       # "导出确认" tab：勾选单据类型和格式 → 下载
    common/
      LibreOfficePrompt.vue  # LibreOffice 未安装时的提示组件
```

工作台不引入 UI 框架或 CSS 库，所有样式通过 `src/styles/tokens.css` 的 CSS 变量控制。
