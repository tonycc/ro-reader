# Remove PO Invoice Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure PO scope exports only PI and PO while Invoice scope retains Invoice and PL export.

**Architecture:** Make `ExportScreen.vue` follow the same scope ownership already used by preview: its PO branch builds PI/PO entries only, and its Invoice branch remains the sole owner of Invoice/PL controls. Remove legacy PO invoice selection code without changing store, API, core, or CLI contracts.

**Tech Stack:** Vue 3, TypeScript, Playwright

---

### Task 1: Lock the scope boundary with an E2E regression

**Files:**
- Modify: `frontend/e2e/workbench.spec.ts:205-233`

- [x] **Step 1: Add failing PO-scope assertions**

After opening the PO export tab, add:

```ts
await expect(page.locator('[data-testid$="-INVOICE_PL"]')).toHaveCount(0);
await expect(page.locator('[data-testid^="export-invoice-"]')).toHaveCount(0);
```

The existing Invoice export scenario at lines 235-272 continues to assert that `invoice-export-INVOICE` and `invoice-export-PL` are present.

- [x] **Step 2: Verify RED**

Run:

```bash
cd frontend && pnpm exec playwright test e2e/workbench.spec.ts --grep "export generates file"
```

Expected: FAIL because the PO export screen currently renders at least one `INVOICE_PL` entry and invoice selector.

### Task 2: Remove legacy Invoice/PL controls from the PO export branch

**Files:**
- Modify: `frontend/src/components/export/ExportScreen.vue:7-140`
- Modify: `frontend/src/components/export/ExportScreen.vue:184-220`
- Modify: `frontend/src/components/export/ExportScreen.vue:251-252`

- [x] **Step 1: Restrict PO export entries**

Change the PO document configuration to:

```ts
const docLabels: Record<string, string> = {
  PI: "形式发票（PI）",
  PO: "采购订单（PO）",
};

const docOrder = ["PI", "PO"];
```

Keep the existing seller filter that removes PO for SK and YM.

- [x] **Step 2: Simplify PO export state and payload projection**

Remove `selectedInvoices`. Make `selectedExportDocs` return only `seller` and selected `documents`. In the export-group watcher, initialize only `selectedDocs`.

Change `buildExportEntry` to use:

```ts
documents: [document],
```

Change `buildFilename` to return:

```ts
return `${safeToken(seller)}-RO-${document}-${safeToken(wb.selectedPo)}.xlsx`;
```

Delete `invoiceOptionsForSeller`, `selectedInvoiceForSeller`, `selectExportInvoice`, and `canExportInvoicePl`. Retain Invoice-branch helpers `selectedInvoiceDocuments`, `handleInvoiceGroupExport`, `toggleInvoiceDocument`, and `invoiceGroupFilename`.

- [x] **Step 3: Remove PO invoice selector markup and CSS**

Delete the `.invoice-field` label block from the PO seller section. Delete `.invoice-field` and `.invoice-field select` CSS rules. Keep the Invoice-scope template unchanged.

- [x] **Step 4: Verify GREEN**

Run:

```bash
cd frontend && pnpm exec playwright test e2e/workbench.spec.ts --grep "export generates file"
```

Expected: 1 passed.

### Task 3: Verify both export scopes

**Files:**
- Verify: `frontend/src/components/export/ExportScreen.vue`
- Verify: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: Build the frontend**

```bash
cd frontend && pnpm run build
```

Expected: `vue-tsc` and Vite exit 0.

- [x] **Step 2: Run the complete E2E suite**

```bash
cd frontend && pnpm run test:e2e
```

Expected: all scenarios pass, including PO export and Invoice-group export.

- [x] **Step 3: Check the patch**

```bash
git diff --check
```

Expected: exit code 0 with no output.

- [x] **Step 4: Commit**

```bash
git add frontend/src/components/export/ExportScreen.vue frontend/e2e/workbench.spec.ts docs/superpowers/plans/2026-06-30-remove-po-invoice-export.md
git commit -m "fix: remove invoice export from PO scope"
```

### Task 4: Prevent stale Invoice state in PO preview

**Files:**
- Modify: `frontend/e2e/workbench.spec.ts`
- Modify: `frontend/src/stores/workbench.ts`

- [x] **Step 1: Reproduce the first-entry path**

Add an E2E scenario that opens a PO preview without clicking PI and asserts that `导出 Invoice / PL` is absent, `导出 PI` is visible, and the document title is `PROFORMA INVOICE`.

- [x] **Step 2: Verify RED**

Run the focused scenario and confirm the PI quick-export button is missing because `previewDocType` starts as `INVOICE`.

- [x] **Step 3: Normalize preview document state**

Initialize PO preview state to `PI`. In `refreshPreview`, normalize requested documents to PI/PO in PO scope and Invoice/PL in Invoice scope before requesting preview data.

- [x] **Step 4: Verify GREEN**

Run the focused scenario and confirm the PI preview and quick-export assertions pass.
