import { test, expect } from "@playwright/test";

const BASE_FILE = "/Users/max/projects/ro-reader/tests/fixtures/synthetic_base.xlsx";

test.describe("RO Workbench E2E", () => {
  test("open base file and see PO list", async ({ page }) => {
    await page.goto("/");

    // Click filename to trigger prompt
    await page.getByText("点击打开 base 文件…").click();

    // Handle the prompt dialog
    const dialogPromise = page.waitForEvent("dialog");
    const dialog = await dialogPromise;
    await dialog.accept(BASE_FILE);

    // Wait for API response
    await page.waitForTimeout(2000);

    // Expect 3 PO items
    const items = page.locator(".po-item");
    await expect(items).toHaveCount(3);
    await expect(items.first()).toContainText("4500030844");
  });

  test("select PO shows data view and preview", async ({ page }) => {
    await page.goto("/");
    await page.getByText("点击打开 base 文件…").click();
    const d1 = await page.waitForEvent("dialog");
    await d1.accept(BASE_FILE);
    await page.waitForTimeout(2000);

    // Click PO 4500099999
    await page.getByText("●4500099999").click();
    await page.waitForTimeout(2000);

    // Data view should have a table
    const table = page.locator("table");
    await expect(table).toBeVisible();

    // Preview should load (SheetJS HTML table)
    const previewTable = page.locator(".html-preview table");
    await expect(previewTable).toBeVisible({ timeout: 5000 });

    // Chain selector should show segments
    const chainBtns = page.locator(".chain-btn");
    await expect(chainBtns).toHaveCount(3);
  });

  test("inline edit persists to data view", async ({ page }) => {
    await page.goto("/");
    await page.getByText("点击打开 base 文件…").click();
    const d1 = await page.waitForEvent("dialog");
    await d1.accept(BASE_FILE);
    await page.waitForTimeout(2000);
    await page.getByText("●4500099999").click();
    await page.waitForTimeout(2000);

    // Double-click the FINALQTY cell (value ~100)
    const qtyCell = page.getByRole("cell", { name: "100" }).first();
    await qtyCell.dblclick();

    // Input should appear
    const input = page.locator(".edit-input");
    await expect(input).toBeVisible();

    // Clear and type new value
    await input.fill("150");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1500);

    // Value should have changed
    await expect(qtyCell).toContainText("150");
  });

  test("export generates file", async ({ page }) => {
    await page.goto("/");
    await page.getByText("点击打开 base 文件…").click();
    const d1 = await page.waitForEvent("dialog");
    await d1.accept(BASE_FILE);
    await page.waitForTimeout(2000);
    await page.getByText("●4500099999").click();
    await page.waitForTimeout(2000);

    // Click export button
    const exportBtn = page.getByRole("button", { name: /导出/ });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();
    await page.waitForTimeout(2000);

    // Status bar should show exported file
    const statusBar = page.locator("footer");
    await expect(statusBar).toContainText("已导出");
    await expect(statusBar).toContainText(".xlsx");
  });

  test("blocked PO shows correct status", async ({ page }) => {
    await page.goto("/");
    await page.getByText("点击打开 base 文件…").click();
    const d1 = await page.waitForEvent("dialog");
    await d1.accept(BASE_FILE);
    await page.waitForTimeout(2000);

    // PO 4500088888 should have the "blocked" class
    const blockedItem = page.locator(".po-item.blocked");
    await expect(blockedItem).toHaveCount(1);
    await expect(blockedItem).toContainText("4500088888");
  });
});
