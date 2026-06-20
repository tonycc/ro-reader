# 导出确认页独立状态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让导出确认页为每个主体独立维护发票选择，并将该选择准确传给单个 ZIP 的批量导出请求。

**Architecture:** 导出确认页组件持有主体级发票状态，与预览页 `selectedSeller` 和 `selectedInvoiceNo` 解耦。组件把主体、已勾选单据和该主体的发票号组成 `BatchExportGroup`，工作台 store 只透传该请求；核心包和 API 的 ZIP 生成流程不改动。

**Tech Stack:** Vue 3、TypeScript、Pinia、Playwright。

---

## 文件结构

- 修改：`frontend/src/components/export/ExportScreen.vue`：维护主体级发票选择、显示发票下拉框、生成与实际选择一致的文件名。
- 修改：`frontend/src/stores/workbench.ts`：让批量导出方法直接使用确认页提交的 `invoice_no`，不读取预览状态。
- 修改：`frontend/e2e/workbench.spec.ts`：覆盖预览/确认页状态隔离和请求参数。

### Task 1: 为独立发票选择写失败的 E2E 测试

**Files:**
- Modify: `frontend/e2e/workbench.spec.ts:175-221`
- Test: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: 替换现有的“按主体分组导出”测试，使其提供两个 GS PTE 发票号，并记录批量导出请求。**

```ts
po.invoice_options_by_seller = {
  ...(po.invoice_options_by_seller ?? {}),
  "GS PTE": ["INV-GS-001", "INV-GS-002"],
};

const invoiceSelect = page.getByTestId("export-invoice-GS_PTE");
await expect(invoiceSelect).toHaveValue("INV-GS-001");
await invoiceSelect.selectOption("INV-GS-002");
```

- [x] **Step 2: 在切换到导出确认页前，将预览页 GS PTE 发票设为 `INV-GS-002`；确认页仍必须默认显示 `INV-GS-001`。**

```ts
await page.evaluate(() => (window as any).__workbench__?.selectSeller("GS PTE"));
await page.evaluate(() => (window as any).__workbench__?.selectInvoice("INV-GS-002"));
await page.locator(".tab").filter({ hasText: "导出确认" }).click();
await expect(page.getByTestId("export-invoice-GS_PTE")).toHaveValue("INV-GS-001");
```

- [x] **Step 3: 只勾选 GS PTE 的 Invoice/PL，选择 `INV-GS-002` 后断言请求使用该主体的选择。**

```ts
expect(exportRequests[0]).toMatchObject({
  po_no: "4500099999",
  groups: [{
    seller: "GS PTE",
    documents: ["INVOICE", "PL"],
    invoice_no: "INV-GS-002",
  }],
});
```

- [x] **Step 4: 运行测试，确认它因缺少确认页发票下拉框而失败。**

Run: `pnpm exec playwright test --grep "export confirmation keeps seller invoice independent from preview"`

Expected: FAIL，找不到 `export-invoice-GS_PTE`。

### Task 2: 在确认页维护主体级发票状态

**Files:**
- Modify: `frontend/src/components/export/ExportScreen.vue:25-105`
- Test: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: 添加局部状态和辅助函数；默认发票来自当前主体的第一个可用选项。**

```ts
const selectedInvoices = ref<Record<string, string | null>>({});

function invoiceOptionsForSeller(seller: string): string[] {
  const po = wb.poEntry;
  if (!po) return [];
  const options = po.invoice_options_by_seller?.[seller] ?? [];
  return options.length ? options : po.invoice_nos;
}

function selectedInvoiceForSeller(seller: string): string | null {
  return selectedInvoices.value[seller] ?? invoiceOptionsForSeller(seller)[0] ?? null;
}
```

- [x] **Step 2: 在 `watch(exportGroups, ...)` 中初始化每个主体的发票值，并让导出组携带其本地发票号。仅含 PI/PO 的组传 `null`。**

```ts
selectedInvoices.value = Object.fromEntries(groups.map(({ seller }) => [
  seller,
  invoiceOptionsForSeller(seller)[0] ?? null,
]));

invoice_no: group.documents.some((document) => document === "INVOICE" || document === "PL")
  ? selectedInvoiceForSeller(group.seller)
  : null,
```

- [x] **Step 3: 更新 `buildExportEntry` / `buildFilename`，使 Invoice/PL 文件名读取 `selectedInvoiceForSeller(seller)`。**

```ts
if (document === "INVOICE_PL" && selectedInvoiceForSeller(seller)) {
  return `${base}-${safeToken(selectedInvoiceForSeller(seller) ?? "")}.xlsx`;
}
```

- [x] **Step 4: 在主体标题下增加普通下拉框；仅当该主体的 Invoice/PL 可导出时显示。**

```vue
<label v-if="exportableDocumentsForSeller(group.seller).includes('INVOICE_PL')" class="invoice-field">
  <span>发票号</span>
  <select
    :data-testid="`export-invoice-${safeToken(group.seller)}`"
    :value="selectedInvoiceForSeller(group.seller) ?? ''"
    @change="selectExportInvoice(group.seller, $event)"
  >
    <option v-for="invoiceNo in invoiceOptionsForSeller(group.seller)" :key="invoiceNo" :value="invoiceNo">
      {{ invoiceNo }}
    </option>
  </select>
</label>
```

- [x] **Step 5: 补充紧凑样式，保证标签、下拉框和主体标题对齐，且窄视口下不溢出。**

```css
.invoice-field { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; }
.invoice-field select { min-width: 0; max-width: 260px; height: 30px; }
```

- [x] **Step 6: 重新运行目标 E2E 测试，确认通过。**

Run: `pnpm exec playwright test --grep "export confirmation keeps seller invoice independent from preview"`

Expected: PASS。

### Task 3: 让 store 透传确认页选择并完成回归验证

**Files:**
- Modify: `frontend/src/stores/workbench.ts:140-184`
- Test: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: 导入 `BatchExportGroup`，保留单文件导出类型，并让 `doExportGroups` 接受 `BatchExportGroup[]`。**

```ts
import type { BatchExportGroup, /* existing types */ } from "./api";

async function doExportGroups(groups: BatchExportGroup[]) {
```

- [x] **Step 2: 批量导出请求直接透传每个组的 `invoice_no`，不再调用 `invoiceNoForSeller`。**

```ts
groups: groups.map((group) => ({
  seller: group.seller,
  documents: group.documents,
  invoice_no: group.invoice_no ?? null,
})),
```

- [x] **Step 3: 运行完整前端检查与 E2E 回归。**

Run: `pnpm run build && pnpm run test:e2e`

Expected: 构建成功，所有 Playwright 用例通过。

- [x] **Step 4: 检查改动范围并提交。**

Run: `git diff --check && git status --short`

Expected: 仅 `ExportScreen.vue`、`workbench.ts`、`workbench.spec.ts` 与本计划涉及的文档发生变化。

Run: `git add frontend/src/components/export/ExportScreen.vue frontend/src/stores/workbench.ts frontend/e2e/workbench.spec.ts && git commit -m "fix: isolate export confirmation selections"`

Expected: 创建一个聚焦的功能提交。
