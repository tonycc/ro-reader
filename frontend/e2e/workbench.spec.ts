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

test.describe("RO Workbench E2E", () => {
  test("open base file and see PO list", async ({ page }) => {
    await openBaseFile(page);
    const items = page.locator(".po-item");
    await expect(items).toHaveCount(3);
    await expect(items.first()).toContainText("4500030844");
  });

  test("select PO shows data view and preview", async ({ page }) => {
    await openBaseFile(page);
    await page.getByText("●4500099999").click();
    await page.waitForTimeout(2000);

    const table = page.locator("table").first();
    await expect(table).toBeVisible();

    const previewTable = page.locator(".html-preview table");
    await expect(previewTable).toBeVisible({ timeout: 5000 });

    const chainBtns = page.locator(".chain-btn");
    await expect(chainBtns).toHaveCount(3);
  });

  test("inline edit persists to data view", async ({ page }) => {
    await openBaseFile(page);
    await page.getByText("●4500099999").click();
    await page.waitForTimeout(2000);

    // Double-click to start editing
    const qtyCell = page.getByRole("cell", { name: "100" }).first();
    await qtyCell.dblclick();

    const input = page.locator(".edit-input");
    await expect(input).toBeVisible({ timeout: 3000 });
    await input.fill("150");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1500);

    // After edit + refresh, the cell should show the new value.
    // Re-query the locator since the DOM was re-rendered.
    await expect(page.getByRole("cell", { name: "150" }).first()).toBeVisible({ timeout: 5000 });
  });

  test("export generates file", async ({ page }) => {
    await openBaseFile(page);
    await page.getByText("●4500099999").click();
    await page.waitForTimeout(2000);

    const exportBtn = page.getByRole("button", { name: /导出/ });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();
    await page.waitForTimeout(2000);

    const statusBar = page.locator("footer");
    await expect(statusBar).toContainText("已导出");
    await expect(statusBar).toContainText(".xlsx");
  });

  test("blocked PO shows correct status", async ({ page }) => {
    await openBaseFile(page);
    const blockedItem = page.locator(".po-item.blocked");
    await expect(blockedItem).toHaveCount(1);
    await expect(blockedItem).toContainText("4500088888");
  });
});
