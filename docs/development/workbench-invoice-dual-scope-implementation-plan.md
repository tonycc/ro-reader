# Workbench Invoice Dual-Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Invoice perspective that groups `SHIP QTY > 0` rows across POs, previews and exports Invoice/PL by stable `invoice_group_key`, and keeps the existing PO perspective for PI/PO.

**Architecture:** All grouping, seller-specific invoice identity, cross-PO header validation, preview assembly, and export assembly live in `ro_generator`. FastAPI only resolves `X-Session-Id`, calls core functions, and serializes results. Vue keeps independent PO and Invoice selections and routes each perspective to its dedicated endpoint.

**Tech Stack:** Python 3.11 frozen dataclasses, openpyxl, pytest, FastAPI/Pydantic, Vue 3, TypeScript, Pinia, Vite, Playwright.

---

## File Map

- Create `packages/ro_generator/src/ro_generator/invoice_groups.py`: grouping, stable key generation, summaries, row membership, and header conflict diagnostics.
- Modify `packages/ro_generator/src/ro_generator/workbook_snapshot.py`: persist `invoice_summary` and `invoice_index` alongside existing PO indexes.
- Create `packages/ro_generator/tests/test_invoice_groups.py`: focused grouping and conflict tests.
- Modify `packages/ro_generator/src/ro_generator/generator.py`: public cross-PO preview and export entry points that consume snapshot groups.
- Modify `packages/ro_generator/src/ro_generator/packager.py`: ticket-group filenames without a single PO token.
- Modify `packages/ro_generator/tests/test_generator.py` and `test_packager.py`: cross-PO preview/export regressions.
- Modify `packages/ro_workbench_api/src/ro_workbench_api/app.py`: session-bound Invoice list, preview, and export routes.
- Modify `packages/ro_workbench_api/tests/test_app.py`: API contract and invalid-session tests.
- Modify `frontend/src/stores/api.ts`: Invoice summary and endpoint types.
- Modify `frontend/src/stores/workbench.ts`: independent perspective state and loading/export actions.
- Modify `frontend/src/App.vue`: pass active workflow tab to the adaptive sidebar.
- Modify `frontend/src/components/po-list/QueueSidebar.vue`: PO/Invoice perspective control and Invoice group list.
- Modify `frontend/src/components/preview/PreviewScreen.vue`: perspective-specific document tabs, title, seller availability, preview, and export.
- Modify `frontend/src/components/export/ExportScreen.vue`: perspective-specific export choices.
- Modify `frontend/src/components/layout/StatusBar.vue`: show selected PO or Invoice group status.
- Modify `frontend/e2e/workbench.spec.ts`: dual-scope navigation and Invoice preview flow.

### Task 1: Invoice Group Domain Model

**Files:**
- Create: `packages/ro_generator/src/ro_generator/invoice_groups.py`
- Create: `packages/ro_generator/tests/test_invoice_groups.py`

- [x] **Step 1: Write failing grouping tests**

Cover these exact test names and behaviors:

- `test_groups_cross_po_rows_by_cooccurring_invoice_identifiers`: two PO rows sharing `INV-001`, with one row also containing `SKYM-001`, produce one group covering both POs.
- `test_excludes_zero_and_missing_ship_qty_before_building_edges`: zero/missing shipment rows neither join components nor appear in `invoice_index`.
- `test_group_key_is_stable_under_row_reordering`: reversing input rows produces the same key and sorted PO list.
- `test_group_key_matches_canonical_sha256_example`: `("INV-001", "SKYM-001")` produces `invgrp::5c4da065fc2a5b64`.
- `test_seller_invoice_numbers_apply_emax_suffix_and_factory_number`: GS uses `INV-001`, EMAX uses `INV-001-P`, and SK/YM use `SKYM-001`.

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest packages/ro_generator/tests/test_invoice_groups.py -q
```

Expected: collection/import failure because `ro_generator.invoice_groups` does not exist.

- [x] **Step 3: Implement the minimal domain API**

```python
@dataclass(frozen=True)
class InvoiceInspection:
    invoice_group_key: str
    display_invoice_no: str
    status: str
    po_nos: tuple[str, ...]
    po_count: int
    sellers: tuple[str, ...]
    seller_invoice_numbers: dict[str, str]
    blocking_count: int
    conflict_count: int

@dataclass(frozen=True)
class InvoiceGroupBuild:
    summaries: tuple[InvoiceInspection, ...]
    index: dict[str, tuple[int, ...]]

def build_invoice_group_key(identifiers: tuple[str, ...]) -> str:
    normalized = sorted({value.strip() for value in identifiers if value.strip()})
    payload = json.dumps(
        {"identifiers": normalized},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"invgrp::{digest}"
```

Implement `build_invoice_groups(lines_by_row)` around the two frozen dataclasses above. Filter `ship_qty is None or ship_qty <= 0` before creating identifier edges, union co-occurring identifiers, then emit sorted summaries and row-index tuples.

- [x] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest packages/ro_generator/tests/test_invoice_groups.py -q
```

### Task 2: Snapshot Invoice Index

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/workbook_snapshot.py`
- Modify: `packages/ro_generator/tests/test_workbook_snapshot.py`

- [x] **Step 1: Write failing snapshot tests**

Assert that `build_workbook_snapshot()` exposes `invoice_summary`, maps every key through `invoice_index`, excludes the missing-SAP/zero-shipment rows from groups, and returns source rows through `invoice_rows_for_group(key)`.

- [x] **Step 2: Run tests and verify RED**

```bash
uv run pytest packages/ro_generator/tests/test_workbook_snapshot.py -q
```

- [x] **Step 3: Build groups while constructing the snapshot**

Resolve each PO independently with its matching customer PO rows, retain `(raw_row_index, OrderLine)` pairs, then call `build_invoice_groups`. Add immutable defaults:

```python
invoice_summary: tuple[InvoiceInspection, ...] = ()
invoice_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
```

- [x] **Step 4: Run focused tests and verify GREEN**

```bash
uv run pytest packages/ro_generator/tests/test_invoice_groups.py packages/ro_generator/tests/test_workbook_snapshot.py -q
```

### Task 3: Cross-PO Preview and Export

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/generator.py`
- Modify: `packages/ro_generator/src/ro_generator/packager.py`
- Modify: `packages/ro_generator/tests/test_generator.py`
- Modify: `packages/ro_generator/tests/test_packager.py`

- [x] **Step 1: Write failing preview tests**

Test `preview_invoice_group_from_snapshot(snapshot, key, seller, document)` for Invoice and PL, including comma-joined PO display, seller-specific invoice number, `SHIP QTY` quantities, unknown key, unavailable seller, and conflicting `ship_to` / `manufacturer_address` headers.

- [x] **Step 2: Verify preview tests fail for missing entry point**

```bash
uv run pytest packages/ro_generator/tests/test_generator.py -k invoice_group -q
```

- [x] **Step 3: Implement cross-PO line resolution and header validation**

Resolve each member PO independently, combine resolved lines only after resolver messages are collected, apply the selected seller filter, validate invariant headers in core, and call the existing `build_document_model()` / `build_preview()` path with:

```python
po_display = ", ".join(group.po_nos)
invoice_no = group.seller_invoice_numbers[seller]
```

- [x] **Step 4: Verify preview tests pass**

```bash
uv run pytest packages/ro_generator/tests/test_generator.py -k invoice_group -q
```

- [x] **Step 5: Write failing export and filename tests**

Assert Invoice/PL filenames are `<SELLER>-RO-<DOCUMENT>-<INVOICE_NO>.xlsx`, the API-facing result is a ZIP, and SK/YM Invoice+PL remains a two-sheet workbook.

- [x] **Step 6: Implement `export_invoice_group_from_snapshot()` and verify GREEN**

```bash
uv run pytest packages/ro_generator/tests/test_generator.py packages/ro_generator/tests/test_packager.py -q
```

### Task 4: Session-Bound Invoice API

**Files:**
- Modify: `packages/ro_workbench_api/src/ro_workbench_api/app.py`
- Modify: `packages/ro_workbench_api/tests/test_app.py`

- [x] **Step 1: Write failing endpoint tests**

Cover:

```text
GET  /api/invoices
POST /api/invoice/{invoice_group_key}/preview
POST /api/invoice/{invoice_group_key}/export
```

Every endpoint must reject missing/expired sessions, derive `base_file` from session, and reject any request-body `base_file` dependency.

- [x] **Step 2: Run tests and verify RED**

```bash
uv run pytest packages/ro_workbench_api/tests/test_app.py -k invoice_group -q
```

- [x] **Step 3: Add thin request models and routes**

```python
class InvoicePreviewRequest(BaseModel):
    seller: str
    document: Literal["INVOICE", "PL"]

class InvoiceExportRequest(BaseModel):
    seller: str
    documents: list[Literal["INVOICE", "PL"]]
```

Routes may only resolve session/cache, invoke core functions, and serialize dataclasses/results.

- [x] **Step 4: Run API and core regression tests**

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
```

### Task 5: Frontend API and Store State

**Files:**
- Modify: `frontend/src/stores/api.ts`
- Modify: `frontend/src/stores/workbench.ts`

- [x] **Step 1: Add TypeScript contracts and API methods**

```ts
export type PreviewScope = "po" | "invoice"
export interface InvoiceListItem {
  invoice_group_key: string
  display_invoice_no: string
  status: "ready" | "partial" | "blocked" | "done"
  po_count: number
  po_nos: string[]
  sellers: string[]
  seller_invoice_numbers: Record<string, string>
  blocking_count: number
  conflict_count: number
}
```

Add `getInvoices`, `previewInvoiceGroup`, and `exportInvoiceGroup`; none accepts `base_file`.

- [x] **Step 2: Split store selection state**

Keep `selectedPo` for data check/PO preview and add `previewScope`, `invoiceList`, `selectedInvoiceGroup`, and per-scope seller/document selections. Invoice scope loads only Invoice/PL and uses the new endpoints.

- [x] **Step 3: Verify TypeScript compilation**

```bash
cd frontend && pnpm run build
```

Expected: successful `vue-tsc` and Vite build.

### Task 6: Dual-Scope UI

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/po-list/QueueSidebar.vue`
- Modify: `frontend/src/components/preview/PreviewScreen.vue`
- Modify: `frontend/src/components/export/ExportScreen.vue`
- Modify: `frontend/src/components/layout/StatusBar.vue`

- [x] **Step 1: Implement the perspective control and adaptive sidebar**

Match the approved visual: a compact `PO 视角 / Invoice 视角` segmented control, flat list rows, Invoice number as primary text, compact PO-count/seller metadata, and semantic status badges.

- [x] **Step 2: Implement perspective-specific preview controls**

PO scope shows PI/PO; Invoice scope shows Invoice/PL, keeps group selection while seller changes, disables unavailable sellers, and shows group title plus `SHIP QTY` metadata.

- [x] **Step 3: Implement perspective-specific export confirmation**

PO scope exports PI/PO by PO. Invoice scope exports Invoice/PL by group and defaults both selected. Never mix the two object types in one action.

- [x] **Step 4: Build and inspect responsive layout**

```bash
cd frontend && pnpm run build
```

Check 1440x900 and 1024x768 layouts for clipping, overlapping controls, and unstable list widths.

### Task 7: End-to-End Regression

**Files:**
- Modify: `frontend/e2e/workbench.spec.ts`

- [x] **Step 1: Add a failing Invoice-scope E2E scenario**

Open the synthetic base, enter preview, switch to Invoice scope, select a group, switch seller, verify Invoice and PL previews, and invoke group export.

- [x] **Step 2: Run E2E and fix integration defects**

```bash
cd frontend && pnpm run test:e2e
```

- [x] **Step 3: Run final verification**

```bash
uv run pytest packages/ro_generator packages/ro_workbench_api -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages
cd frontend && pnpm run build && pnpm run test:e2e
git diff --check
```

Expected: all commands exit 0; only the existing Starlette/httpx deprecation warning is acceptable.
