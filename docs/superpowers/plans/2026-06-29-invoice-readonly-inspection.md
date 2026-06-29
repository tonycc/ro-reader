# Invoice Read-Only Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Invoice data-check perspective that shows the exact shipment rows used by an invoice group and explains resolver, identifier, and cross-PO header issues with the same interaction model as PO data check.

**Architecture:** `ro_generator` owns invoice-group membership, row projection, issue severity, and deduplication. A session-bound FastAPI route serializes the frozen inspection result without accepting `base_file`. Vue loads the result only while the data-check tab is showing Invoice scope, renders a read-only table, and reuses one issue-summary component for PO and Invoice checks.

**Tech Stack:** Python 3.11 frozen dataclasses, FastAPI/Pydantic, pytest, Vue 3, TypeScript, Pinia, Vite, Playwright.

---

## File Map

- Create `packages/ro_generator/src/ro_generator/invoice_inspection.py`: shared invoice-group resolution, inspection rows, issue construction, and issue deduplication.
- Create `packages/ro_generator/tests/test_invoice_inspection.py`: member-row, resolver-message, identifier-conflict, header-conflict, and unknown-key tests.
- Modify `packages/ro_generator/src/ro_generator/generator.py`: replace private invoice-group resolution/header helpers with the shared core functions.
- Modify `packages/ro_generator/tests/test_generator.py`: preserve Invoice/PL preview and export behavior after helper extraction.
- Modify `packages/ro_workbench_api/src/ro_workbench_api/app.py`: add the session-bound inspection route and serialization.
- Modify `packages/ro_workbench_api/tests/test_app.py`: verify response and session contract.
- Modify `frontend/src/stores/api.ts`: add inspection response types and API method.
- Modify `frontend/src/stores/workbench.ts`: add inspection state and refresh action.
- Create `frontend/src/components/data-view/IssueSummaryBar.vue`: shared PO/Invoice issue badges and panels.
- Create `frontend/src/components/data-view/InvoiceDataCheck.vue`: read-only Invoice summary and member-row table.
- Modify `frontend/src/components/data-view/DataCheckScreen.vue`: select PO editable or Invoice read-only view and reuse `IssueSummaryBar`.
- Modify `frontend/src/components/po-list/QueueSidebar.vue`: expose scope switching on data check again.
- Modify `frontend/src/App.vue`: preserve current scope when entering data check.
- Modify `frontend/e2e/workbench.spec.ts`: replace the PO-only invariant with Invoice inspection coverage.
- Modify `docs/product/ro-document-generator-product-plan.md`: change data-check scope from PO-only to current business object.
- Modify `docs/development/ro-document-workbench-ui-design.md`: document read-only Invoice inspection behavior.
- Modify `docs/development/implementation-guide.md`: record implementation and verification status.

### Task 1: Core Invoice Inspection Model

**Files:**
- Create: `packages/ro_generator/src/ro_generator/invoice_inspection.py`
- Create: `packages/ro_generator/tests/test_invoice_inspection.py`

- [x] **Step 1: Write failing result-model and member-row tests**

Add tests with these exact behaviors:

```python
def test_inspection_returns_only_indexed_positive_ship_qty_rows(snapshot):
    group = next(item for item in snapshot.invoice_summary if item.display_invoice_no == "INV-001")
    result = inspect_invoice_group_from_snapshot(snapshot, group.invoice_group_key)

    assert result.invoice_group_key == group.invoice_group_key
    assert [row.source_row for row in result.rows] == sorted(row.source_row for row in result.rows)
    assert {row.po_no for row in result.rows} == {"PO-1", "PO-2"}
    assert all(row.ship_qty > 0 for row in result.rows)


def test_inspection_unknown_key_returns_structured_blocking_error(snapshot):
    result = inspect_invoice_group_from_snapshot(snapshot, "invgrp::missing")

    assert result.rows == ()
    assert [message.code for message in result.blocking_errors] == ["INVOICE_GROUP_NOT_FOUND"]
```

The fixture must include a zero-shipment row with the same invoice identifier and assert that its source row is absent.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest packages/ro_generator/tests/test_invoice_inspection.py -q
```

Expected: collection fails because `ro_generator.invoice_inspection` does not exist.

- [x] **Step 3: Add frozen inspection types and minimal entry point**

Implement:

```python
@dataclass(frozen=True)
class InvoiceInspectionRow:
    source_row: int
    po_no: str
    sap: str
    description: str
    category: int | None
    ship_qty: Decimal
    invoice_no: str | None
    factory_document_no: str | None
    sellers: tuple[str, ...]


@dataclass(frozen=True)
class InvoiceGroupInspection:
    invoice_group_key: str
    display_invoice_no: str
    po_nos: tuple[str, ...]
    rows: tuple[InvoiceInspectionRow, ...]
    blocking_errors: tuple[ValidationMessage, ...]
    warnings: tuple[ValidationMessage, ...]
```

Add `inspect_invoice_group_from_snapshot(snapshot, invoice_group_key)`. It must read membership exclusively through `snapshot.invoice_rows_for_group()`, resolve each covered PO independently with matching customer-PO rows, and sort projected rows by `source_row`.

Compute row sellers in core:

```python
def _sellers_for_line(line: OrderLine) -> tuple[str, ...]:
    sellers: list[str] = []
    if line.invoice_no:
        sellers.extend(("GS PTE", "EMAX PTE"))
    factory_seller = factory_seller_for_line(line)
    if line.sk_ym_invoice_no and factory_seller:
        sellers.append(factory_seller)
    return tuple(seller for seller in SELLERS if seller in sellers)
```

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit the core model**

```bash
git add packages/ro_generator/src/ro_generator/invoice_inspection.py packages/ro_generator/tests/test_invoice_inspection.py
git commit -m "feat: add invoice group inspection model"
```

### Task 2: Shared Issue Construction and Generator Reuse

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/invoice_inspection.py`
- Modify: `packages/ro_generator/src/ro_generator/generator.py`
- Modify: `packages/ro_generator/tests/test_invoice_inspection.py`
- Modify: `packages/ro_generator/tests/test_generator.py`

- [x] **Step 1: Write failing issue tests**

Cover resolver and group-level messages:

```python
def test_inspection_deduplicates_resolver_messages(snapshot_with_duplicate_warning):
    result = inspect_invoice_group_from_snapshot(snapshot_with_duplicate_warning, GROUP_KEY)
    keys = [(m.kind, m.code, m.message, m.sheet, m.row, m.field) for m in result.warnings]
    assert len(keys) == len(set(keys))


def test_identifier_conflict_is_high_warning(conflicting_identifier_snapshot):
    result = inspect_invoice_group_from_snapshot(conflicting_identifier_snapshot, GROUP_KEY)
    message = next(m for m in result.warnings if m.code == "INVOICE_IDENTIFIER_CONFLICT")
    assert message.severity == "high"


def test_header_conflict_is_blocking(header_conflict_snapshot):
    result = inspect_invoice_group_from_snapshot(header_conflict_snapshot, GROUP_KEY)
    assert next(m for m in result.blocking_errors if m.code == "INVOICE_GROUP_HEADER_CONFLICT")
```

- [x] **Step 2: Verify the tests fail for missing messages**

```bash
uv run pytest packages/ro_generator/tests/test_invoice_inspection.py -k "deduplicates or identifier_conflict or header_conflict" -q
```

Expected: assertions fail because inspection currently returns only resolver output or no group messages.

- [x] **Step 3: Implement stable issue construction**

Add constants and helpers to `invoice_inspection.py`:

```python
CODE_INVOICE_GROUP_NOT_FOUND = "INVOICE_GROUP_NOT_FOUND"
CODE_INVOICE_GROUP_HEADER_CONFLICT = "INVOICE_GROUP_HEADER_CONFLICT"
CODE_INVOICE_IDENTIFIER_CONFLICT = "INVOICE_IDENTIFIER_CONFLICT"


def dedupe_messages(messages: Iterable[ValidationMessage]) -> tuple[ValidationMessage, ...]:
    seen: set[tuple[object, ...]] = set()
    result: list[ValidationMessage] = []
    for message in messages:
        key = (message.kind, message.code, message.message, message.sheet, message.row, message.field)
        if key not in seen:
            seen.add(key)
            result.append(message)
    return tuple(result)
```

Use `snapshot.invoice_header_context[group_key]` for header conflicts. Emit one `severity="high"` warning when `summary.conflict_count > summary.blocking_count`; include the display invoice number and conflicting identifier values in the reason.

- [x] **Step 4: Replace generator-private group resolution**

Expose this frozen result from `invoice_inspection.py`:

```python
@dataclass(frozen=True)
class InvoiceGroupResolution:
    summary: InvoiceInspection | None
    lines: tuple[OrderLine, ...]
    blocking_errors: tuple[ValidationMessage, ...]
    warnings: tuple[ValidationMessage, ...]


def resolve_invoice_group_from_snapshot(
    snapshot: WorkbookSnapshot,
    invoice_group_key: str,
) -> InvoiceGroupResolution:
    summary = next(
        (item for item in snapshot.invoice_summary if item.invoice_group_key == invoice_group_key),
        None,
    )
    if summary is None:
        error = ValidationMessage(
            kind="blocking_error",
            code=CODE_INVOICE_GROUP_NOT_FOUND,
            message=f"票据组 {invoice_group_key!r} 不存在",
        )
        return InvoiceGroupResolution(None, (), (error,), ())

    po_field = base_schema().field("PO record", "po_no")
    member_rows = snapshot.invoice_rows_for_group(invoice_group_key)
    lines: list[OrderLine] = []
    blocking: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []
    for po_no in summary.po_nos:
        po_rows = tuple(row for row in member_rows if str(row.get(po_field, "")).strip() == po_no)
        resolved = resolve_po_rows(
            po_rows,
            snapshot.product_index,
            po_no=po_no,
            customer_po_rows=snapshot.customer_po_rows_for_po(po_no),
        )
        lines.extend(resolved.lines)
        blocking.extend(message for message in resolved.messages if message.kind == "blocking_error")
        warnings.extend(message for message in resolved.messages if message.kind == "warning")

    group_blocking, group_warnings = _group_messages(snapshot, summary)
    return InvoiceGroupResolution(
        summary=summary,
        lines=tuple(lines),
        blocking_errors=dedupe_messages((*blocking, *group_blocking)),
        warnings=dedupe_messages((*warnings, *group_warnings)),
    )
```

Implement `_group_messages(snapshot, summary)` in Step 3: iterate `snapshot.invoice_header_context[summary.invoice_group_key].conflicts` to create blocking messages with field values and source rows; when `summary.conflict_count > summary.blocking_count`, add one high-severity identifier warning. Replace `generator._resolve_invoice_group_lines()` and `_invoice_group_header_conflict()` with this shared result in both `preview_invoice_group_from_snapshot()` and `export_invoice_group_from_snapshot()`.

Do not change seller filtering, document building, filenames, or rendering behavior.

- [x] **Step 5: Run inspection and generator regression tests**

```bash
uv run pytest packages/ro_generator/tests/test_invoice_inspection.py packages/ro_generator/tests/test_generator.py -q
```

Expected: all pass, including existing cross-PO preview and export tests.

- [ ] **Step 6: Commit shared business logic**

```bash
git add packages/ro_generator/src/ro_generator/invoice_inspection.py packages/ro_generator/src/ro_generator/generator.py packages/ro_generator/tests/test_invoice_inspection.py packages/ro_generator/tests/test_generator.py
git commit -m "refactor: share invoice group inspection rules"
```

### Task 3: Session-Bound Inspection API

**Files:**
- Modify: `packages/ro_workbench_api/src/ro_workbench_api/app.py`
- Modify: `packages/ro_workbench_api/tests/test_app.py`

- [x] **Step 1: Write failing API tests**

Add tests for the exact route:

```python
def test_invoice_inspection_requires_valid_session():
    response = client.get(
        "/api/invoice/invgrp%3A%3Amissing/inspection",
        headers={"X-Session-Id": "expired"},
    )
    assert response.status_code == 400


def test_invoice_inspection_returns_rows_and_issue_counts():
    session_id = open_fixture_session()
    group = get_first_invoice_group(session_id)
    response = client.get(
        f"/api/invoice/{quote(group['invoice_group_key'], safe='')}/inspection",
        headers={"X-Session-Id": session_id},
    )
    data = response.json()
    assert response.status_code == 200
    assert data["line_count"] == len(data["rows"])
    assert data["blocking_count"] == len(data["blocking_errors"])
    assert data["warnings_count"] == len(data["warnings"])
    assert "base_file" not in data
```

- [x] **Step 2: Run tests and verify RED**

```bash
uv run pytest packages/ro_workbench_api/tests/test_app.py -k invoice_inspection -q
```

Expected: route returns 404.

- [x] **Step 3: Add a thin GET route**

Implement:

```python
@app.get("/api/invoice/{invoice_group_key}/inspection")
def inspect_invoice_group(
    invoice_group_key: str,
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> dict[str, Any]:
    session = _get_session(x_session_id)
    if session is None:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_SESSION",
                "message": f"session {x_session_id!r} 无效或已过期",
            },
        )
    snapshot = get_cache_manager().get_snapshot(session.base_file)
    result = inspect_invoice_group_from_snapshot(snapshot, invoice_group_key)
    return _invoice_inspection_to_dict(result)
```

The serializer converts `Decimal` to JSON-safe values, tuple sellers to lists, and `ValidationMessage` through the existing message serializer. It reports `line_count`, `blocking_count`, and `warnings_count`; it performs no validation or grouping.

- [x] **Step 4: Run API and core tests**

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
```

Expected: all pass.

- [ ] **Step 5: Commit the API contract**

```bash
git add packages/ro_workbench_api/src/ro_workbench_api/app.py packages/ro_workbench_api/tests/test_app.py
git commit -m "feat: expose invoice inspection endpoint"
```

### Task 4: Frontend Inspection State

**Files:**
- Modify: `frontend/src/stores/api.ts`
- Modify: `frontend/src/stores/workbench.ts`

- [x] **Step 1: Add response types and API method**

Define:

```ts
export interface InvoiceInspectionRow {
  source_row: number
  po_no: string
  sap: string
  description: string
  category: number | null
  ship_qty: number
  invoice_no: string | null
  factory_document_no: string | null
  sellers: string[]
}

export interface InvoiceInspectionResponse {
  invoice_group_key: string
  display_invoice_no: string
  po_nos: string[]
  line_count: number
  blocking_count: number
  warnings_count: number
  rows: InvoiceInspectionRow[]
  blocking_errors: ValidationIssue[]
  warnings: ValidationIssue[]
}
```

Add `getInvoiceInspection(invoiceGroupKey)` using the session header and no `base_file`.

- [x] **Step 2: Add isolated store state**

Add:

```ts
const invoiceInspection = ref<InvoiceInspectionResponse | null>(null)
const invoiceInspectionLoading = ref(false)
const invoiceInspectionError = ref("")

async function refreshInvoiceInspection() {
  if (!selectedInvoiceGroup.value) return
  invoiceInspectionLoading.value = true
  invoiceInspectionError.value = ""
  try {
    invoiceInspection.value = await api.getInvoiceInspection(selectedInvoiceGroup.value)
  } catch (error) {
    invoiceInspection.value = null
    invoiceInspectionError.value = error instanceof ApiError ? error.message : String(error)
  } finally {
    invoiceInspectionLoading.value = false
  }
}
```

Clear stale inspection state when the session or selected group changes. Do not derive issues or sellers in the store.

- [x] **Step 3: Verify TypeScript compilation**

```bash
cd frontend && pnpm run build
```

Expected: `vue-tsc` and Vite both exit 0.

- [ ] **Step 4: Commit frontend data state**

```bash
git add frontend/src/stores/api.ts frontend/src/stores/workbench.ts
git commit -m "feat: add invoice inspection state"
```

### Task 5: Shared Issue UI and Read-Only Table

**Files:**
- Create: `frontend/src/components/data-view/IssueSummaryBar.vue`
- Create: `frontend/src/components/data-view/InvoiceDataCheck.vue`
- Modify: `frontend/src/components/data-view/DataCheckScreen.vue`
- Modify: `frontend/src/components/po-list/QueueSidebar.vue`
- Modify: `frontend/src/App.vue`

- [x] **Step 1: Extract the existing PO issue summary without behavior changes**

Create `IssueSummaryBar.vue` with props:

```ts
const props = defineProps<{
  objectLabel: string
  metaLabel: string
  blockingErrors: ValidationIssue[]
  warnings: ValidationIssue[]
  loading: boolean
  error: string
}>()
```

Move the current panel open/close, Escape/outside-click handling, issue dedupe key, location formatting, badges, and panel styles from `DataCheckScreen.vue` into this component. Preserve existing classes such as `.issue-badge`, `.data-issue-panel`, and `.data-warning-panel` so PO E2E behavior remains stable.

- [x] **Step 2: Build the Invoice read-only view**

`InvoiceDataCheck.vue` must watch `wb.selectedInvoiceGroup` with `{ immediate: true }` and call `wb.refreshInvoiceInspection()`. Render:

```vue
<IssueSummaryBar
  :object-label="inspection.display_invoice_no"
  :meta-label="`${inspection.line_count} 行 · ${inspection.po_nos.length} 个 PO · Invoice 基础检查`"
  :blocking-errors="inspection.blocking_errors"
  :warnings="inspection.warnings"
  :loading="wb.invoiceInspectionLoading"
  :error="wb.invoiceInspectionError"
/>
```

Render a `<table data-testid="invoice-inspection-table">` with the fixed columns from the spec. Cells contain plain text only; do not attach `dblclick`, inputs, buttons, or links.

Render these explicit states before the table: no selection uses `选择左侧 Invoice 开始数据检查`; loading uses `正在读取 Invoice 检查结果…`; request failure shows `wb.invoiceInspectionError`; a successful zero-row result keeps `IssueSummaryBar` visible and shows `该票据组没有可检查的出货行`.

- [x] **Step 3: Branch the data-check screen by scope**

At the top level of `DataCheckScreen.vue`:

```vue
<InvoiceDataCheck v-if="wb.previewScope === 'invoice'" />
<template v-else>
  <!-- existing PO data check -->
</template>
```

Use `IssueSummaryBar` for the PO branch with the existing `poIssues` data. Preserve PO inline editing exactly.

- [x] **Step 4: Restore data-check scope switching**

- Remove `v-if="activeTab !== 'check'"` from `.scope-switch` in `QueueSidebar.vue`.
- Remove the forced `selectPreviewScope("po")` branch from `App.selectWorkflowTab()`.
- Remove the now-unused `activeTab` prop from `QueueSidebar.vue` and change `<QueueSidebar :active-tab="activeTab" />` back to `<QueueSidebar />` in `App.vue`.
- Preserve independent `selectedPo` and `selectedInvoiceGroup` state.

- [x] **Step 5: Build and inspect both views**

```bash
cd frontend && pnpm run build
```

In the browser verify:

- PO scope still edits cells and opens both issue panels.
- Invoice scope shows rows and issue reasons.
- Invoice table has no editable control.
- Switching tabs and scopes does not clear either selected object.

- [ ] **Step 6: Commit the UI**

```bash
git add frontend/src/App.vue frontend/src/components/data-view/IssueSummaryBar.vue frontend/src/components/data-view/InvoiceDataCheck.vue frontend/src/components/data-view/DataCheckScreen.vue frontend/src/components/po-list/QueueSidebar.vue
git commit -m "feat: add read-only invoice data check"
```

### Task 6: Product Documentation and End-to-End Regression

**Files:**
- Modify: `docs/product/ro-document-generator-product-plan.md`
- Modify: `docs/development/ro-document-workbench-ui-design.md`
- Modify: `docs/development/implementation-guide.md`
- Modify: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: Replace the obsolete PO-only E2E**

Replace `data check always keeps the PO queue` with:

```ts
test("invoice data check shows read-only shipment rows and issues", async ({ page }) => {
  await openBaseFile(page)
  await page.getByTestId("preview-scope-invoice").click()
  await page.locator(".invoice-card").filter({ hasText: "INV-2601-001" }).click()

  const table = page.getByTestId("invoice-inspection-table")
  await expect(table).toBeVisible()
  await expect(table.locator("tbody tr")).toHaveCount(2)
  await expect(table).toContainText("4500030844")
  await expect(table).toContainText("SHIP QTY")
  await expect(page.getByTestId("cell-edit-input")).toHaveCount(0)
  await expect(page.locator(".issue-bar")).toContainText("Invoice 基础检查")
})
```

In the same test, verify the real fixture warning panel:

```ts
const warningBadge = page.locator(".issue-badge.fix")
await expect(warningBadge).toBeVisible()
await warningBadge.click()
await expect(page.locator(".data-warning-panel")).toBeVisible()
await expect(page.locator(".data-warning-panel")).toContainText("NO_PRICES")
```

Add a separate blocking-panel test by intercepting only the inspection response:

```ts
test("invoice data check explains blocking issues", async ({ page }) => {
  await page.route("**/api/invoice/*/inspection", async (route) => {
    const response = await route.fetch()
    const data = await response.json()
    data.blocking_count = 1
    data.blocking_errors = [{
      kind: "blocking_error",
      code: "INVOICE_GROUP_HEADER_CONFLICT",
      message: "票据组跨 PO 的 ship_to 不一致",
      sheet: "PO record",
      row: 5,
      field: "ship_to",
      severity: null,
    }]
    await route.fulfill({ response, json: data })
  })
  await openBaseFile(page)
  await page.getByTestId("preview-scope-invoice").click()
  await page.locator(".invoice-card").first().click()
  await page.locator(".issue-badge.blocked").click()
  await expect(page.locator(".data-issue-panel")).toContainText("ship_to 不一致")
})
```

- [x] **Step 2: Run the new scenario and fix only integration defects**

```bash
cd frontend && pnpm exec playwright test --grep "invoice data check" --reporter=line
```

Expected: pass.

- [x] **Step 3: Update authoritative docs**

Change the product/UI rule to:

```text
数据检查按当前 PO / Invoice 视角检查对应业务对象：PO 展示可编辑源行，Invoice 展示票据组实际出货行和问题原因且保持只读。
```

Record the endpoint, core ownership boundary, non-editability, and completed verification in the implementation guide. Remove contradictory statements that data check always forces PO scope.

- [x] **Step 4: Run final verification**

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run ruff check .
uv run ruff format --check packages/ro_generator/src/ro_generator/invoice_inspection.py packages/ro_generator/src/ro_generator/generator.py packages/ro_generator/tests/test_invoice_inspection.py packages/ro_generator/tests/test_generator.py packages/ro_workbench_api/src/ro_workbench_api/app.py packages/ro_workbench_api/tests/test_app.py
uv run mypy packages
cd frontend && pnpm run build && pnpm run test:e2e
git diff --check
```

Expected: all commands exit 0. The repository-wide `ruff format --check .` remains outside this feature because the unchanged `packages/ro_generator/src/ro_generator/resolver.py` has a known pre-existing format difference.

- [ ] **Step 5: Commit docs and regression test**

```bash
git add docs/product/ro-document-generator-product-plan.md docs/development/ro-document-workbench-ui-design.md docs/development/implementation-guide.md frontend/e2e/workbench.spec.ts
git commit -m "docs: record invoice inspection workflow"
```
