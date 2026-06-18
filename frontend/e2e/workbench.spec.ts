import { test, expect } from "@playwright/test";

const BASE_FILE = "/Users/max/projects/ro-reader/tests/fixtures/synthetic_base.xlsx";

/** Set base file path via window hook (bypasses prompt() for headless E2E). */
async function openBaseFile(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.evaluate(
    (path) => (window as any).__workbench__?.openSession(path),
    BASE_FILE,
  );
  await page.waitForTimeout(2000);
}

async function selectGsSeller(page: import("@playwright/test").Page) {
  await page.locator(".filter-pill").filter({ hasText: "GS PTE" }).click();
}

async function selectPiDocument(page: import("@playwright/test").Page) {
  await page.locator(".filter-pill").filter({ hasText: "PI" }).click();
}

test.describe("RO Workbench E2E", () => {
  test("open base file and see PO list", async ({ page }) => {
    await openBaseFile(page);
    const items = page.locator(".po-card");
    await expect(items).toHaveCount(3);
    await expect(page.locator(".po-card").filter({ hasText: "4500030844" })).toBeVisible();
    await expect(page.locator(".po-card").filter({ hasText: "4500099999" })).toBeVisible();
    await expect(page.locator(".po-card").filter({ hasText: "4500088888" })).toBeVisible();
  });

  test("select PO shows data view and preview", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);

    // Data view tab should show PO data table
    const table = page.locator("table").first();
    await expect(table).toBeVisible();

    // Switch to preview tab
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);
    await selectPiDocument(page);
    await page.waitForTimeout(2000);

    // Document card with lines should be visible
    const docCard = page.locator(".document-card");
    await expect(docCard).toBeVisible({ timeout: 5000 });

    // Filter pills for seller selection
    const sellerBtns = page.locator(".filter-pill");
    await expect(sellerBtns.first()).toBeVisible();
  });

  test("preview shows document title and content", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);

    // Switch to preview tab
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);
    await selectPiDocument(page);
    await page.waitForTimeout(3000);

    // Should show a document title
    const title = page.locator(".top-right h1");
    await expect(title).toBeVisible({ timeout: 5000 });

    // Should show seller/buyer/PO info
    await expect(page.getByRole("row", { name: /PI # 4500099999/ })).toBeVisible();
  });

  test("field source summary toggles", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);

    // Switch to preview tab
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);
    await selectPiDocument(page);
    await page.waitForTimeout(3000);

    // Click "字段来源" button to show source summary
    const sourceBtn = page.locator(".ghost-btn").filter({ hasText: "字段来源" });
    await expect(sourceBtn).toBeVisible({ timeout: 5000 });
    await sourceBtn.click();
    await page.waitForTimeout(500);

    // Source summary should appear
    const sourceSummary = page.locator(".source-summary");
    await expect(sourceSummary).toBeVisible({ timeout: 3000 });

    // Should have source entries
    const sourceRows = page.locator(".source-table tbody tr");
    await expect(sourceRows.first()).toBeVisible({ timeout: 3000 });
  });

  test("inline edit persists to data view", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);

    // Double-click FINALQTY in the first data row.
    const qtyCell = page.locator(".data-table tbody tr").first().locator("td").nth(7);
    await qtyCell.dblclick();

    const input = page.locator('[data-testid="cell-edit-input"]');
    await expect(input).toBeVisible({ timeout: 3000 });
    await input.fill("175");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1500);

    // After edit + refresh, the cell should show the new value.
    await expect(page.getByRole("cell", { name: "175" }).first()).toBeVisible({ timeout: 5000 });
  });

  test("export generates file", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);

    // Choose a stable exportable preview first
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);
    await selectPiDocument(page);

    // Switch to export tab
    await page.locator(".tab").filter({ hasText: "导出确认" }).click();
    await page.waitForTimeout(1000);

    const exportBtn = page.locator("button").filter({ hasText: "确认导出" });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();
    await page.waitForTimeout(2000);

    const statusBar = page.locator("footer");
    await expect(statusBar).toContainText("已导出");
    await expect(statusBar).toContainText(".xlsx");
  });

  test("blocked PO shows correct status", async ({ page }) => {
    await openBaseFile(page);
    const blockedCard = page.locator(".po-card").filter({ hasText: "4500088888" });
    await expect(blockedCard).toHaveCount(1);
    await expect(blockedCard).toContainText("阻断");
  });

  test("blocked badge in data check opens issue panel", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500088888" }).click();

    const issueBadge = page.locator(".issue-badge.blocked");
    await expect(issueBadge).toBeVisible({ timeout: 5000 });
    await issueBadge.click();

    const issuePanel = page.locator(".data-issue-panel");
    await expect(issuePanel).toBeVisible();
    await expect(issuePanel).toContainText("阻断原因");
    await expect(issuePanel).toContainText("SAP");

    await page.locator(".data-issue-close-btn").click();
    await expect(issuePanel).toBeHidden();

    await issueBadge.click();
    await expect(issuePanel).toBeVisible();
    await page.mouse.click(1000, 760);
    await expect(issuePanel).toBeHidden();
  });

  test("warning badge in data check opens warning panel", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();

    const warningBadge = page.locator(".issue-badge.fix");
    await expect(warningBadge).toBeVisible({ timeout: 5000 });
    await warningBadge.click();

    const warningPanel = page.locator(".data-warning-panel");
    await expect(warningPanel).toBeVisible();
    await expect(warningPanel).toContainText("预警详情");
    await expect(warningPanel).toContainText("NO_PRICES");

    await page.locator(".data-warning-close-btn").click();
    await expect(warningPanel).toBeHidden();

    await warningBadge.click();
    await expect(warningPanel).toBeVisible();
    await page.mouse.click(1000, 760);
    await expect(warningPanel).toBeHidden();
  });

  test("invoice and PL previews for selected seller share one page", async ({ page }) => {
    await openBaseFile(page);
    await page.evaluate(() => (window as any).__workbench__?.selectPo("4500099999"));
    await page.evaluate(() => (window as any).__workbench__?.selectInvoice(null));
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();

    await expect(page.getByRole("button", { name: "Invoice / PL", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Invoice", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "PL", exact: true })).toHaveCount(0);

    await expect(page.locator(".preview-doc-section")).toHaveCount(2, { timeout: 8000 });
    await expect(page.locator(".preview-body > .alert")).toHaveCount(0);
    await expect(page.locator(".preview-doc-title").filter({ hasText: "SK · COMMERCIAL INVOICE" })).toBeVisible();
    await expect(page.locator(".preview-doc-title").filter({ hasText: "SK · PACKING LIST" })).toBeVisible();
    await expect(page.getByRole("row", { name: "Invoice No." })).toHaveCount(2);
    const previewExportBtn = page.locator(".export-btn");
    await expect(previewExportBtn).toBeVisible();
    await expect(previewExportBtn).toContainText("Invoice / PL");
    await previewExportBtn.click();
    await expect(page.locator("footer")).toContainText("INVOICE&PL", { timeout: 8000 });
    await expect(page.locator("footer")).toContainText(".xlsx");

    await page.locator(".filter-pill").filter({ hasText: "GS PTE" }).click();
    await expect(page.locator(".preview-doc-section")).toHaveCount(2, { timeout: 8000 });
    await expect(page.locator(".preview-doc-title").filter({ hasText: "GS PTE · Invoice" })).toBeVisible();
    await expect(page.locator(".preview-doc-title").filter({ hasText: "GS PTE · PL" })).toBeVisible();
  });

  test("preview blocking issues contribute to data check badge", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();

    const issueBadge = page.locator(".issue-badge.blocked");
    await expect(issueBadge).toBeVisible({ timeout: 5000 });
    await issueBadge.click();

    const issuePanel = page.locator(".data-issue-panel");
    await expect(issuePanel).toBeVisible();
    await expect(issuePanel).toContainText("INVOICE#");
  });

  test("blocked badge in preview opens issue panel", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500088888" }).click();
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();

    const issueBadge = page.locator(".issue-badge-btn");
    await expect(issueBadge).toBeVisible({ timeout: 5000 });
    await issueBadge.click();

    const issuePanel = page.locator(".issue-panel");
    await expect(issuePanel).toBeVisible();
    await expect(issuePanel).toContainText("阻断原因");
    await expect(issuePanel).toContainText("SAP");
  });
});
