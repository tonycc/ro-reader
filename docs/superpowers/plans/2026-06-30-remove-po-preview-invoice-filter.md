# Remove PO Preview Invoice Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete invoice-number dropdown from the PO document preview without changing Invoice-scope previews.

**Architecture:** Treat preview scope as the ownership boundary: PO scope exposes only seller and PI/PO document controls, while Invoice scope continues to select its invoice group from the sidebar. Remove only component-local selector code and CSS that no longer has a valid consumer.

**Tech Stack:** Vue 3, TypeScript, CSS, Playwright

---

### Task 1: Define the PO preview control contract

**Files:**
- Modify: `frontend/e2e/workbench.spec.ts:139-156`
- Test: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: Add the failing assertion**

Add this assertion to `PO preview keeps invoice documents in their own scope` before switching to Invoice scope:

```ts
await expect(page.locator(".invoice-filter-group")).toHaveCount(0);
await expect(page.locator(".invoice-select")).toHaveCount(0);
```

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd frontend && pnpm exec playwright test e2e/workbench.spec.ts --grep "PO preview keeps invoice documents"
```

Expected: FAIL because `.invoice-filter-group` and `.invoice-select` each currently have one match.

### Task 2: Remove the obsolete PO-scope selector

**Files:**
- Modify: `frontend/src/components/preview/PreviewScreen.vue:59-60`
- Modify: `frontend/src/components/preview/PreviewScreen.vue:85-88`
- Modify: `frontend/src/components/preview/PreviewScreen.vue:238-251`
- Modify: `frontend/src/components/preview/PreviewScreen.vue:473-511`

- [x] **Step 1: Remove selector-only script state**

Delete these computed properties:

```ts
const invoiceSelectValue = computed(() => wb.selectedInvoiceNo ?? "");
const invoiceSelectDisabled = computed(() => !isInvoicePlMode.value);
```

Delete the selector change handler:

```ts
async function onInvoiceChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  await wb.selectInvoice(value || null);
}
```

Keep `isInvoicePlMode`; it remains responsible for the current document label.

- [x] **Step 2: Remove the selector template**

Delete the complete `.invoice-filter-group` block containing the `发票` label and `.invoice-select`. Leave the company and document filter groups adjacent.

- [x] **Step 3: Remove selector-only CSS**

Delete the `.invoice-filter-group`, `.invoice-select`, `.invoice-select:disabled`, and `.invoice-select:not(:disabled)` rules. Do not change shared `.filter-group` styles.

- [x] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
cd frontend && pnpm exec playwright test e2e/workbench.spec.ts --grep "PO preview keeps invoice documents"
```

Expected: 1 passed.

### Task 3: Verify frontend behavior

**Files:**
- Verify: `frontend/src/components/preview/PreviewScreen.vue`
- Verify: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: Build the frontend**

Run:

```bash
cd frontend && pnpm run build
```

Expected: `vue-tsc` and Vite complete with exit code 0.

- [x] **Step 2: Run the full E2E suite**

Run:

```bash
cd frontend && pnpm run test:e2e
```

Expected: all scenarios pass, including Invoice-scope preview and export scenarios.

- [x] **Step 3: Check the patch**

Run:

```bash
git diff --check
```

Expected: exit code 0 with no output.

- [x] **Step 4: Commit the implementation**

```bash
git add frontend/src/components/preview/PreviewScreen.vue frontend/e2e/workbench.spec.ts docs/superpowers/plans/2026-06-30-remove-po-preview-invoice-filter.md
git commit -m "fix: remove invoice filter from PO preview"
```
