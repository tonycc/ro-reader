import { test, expect } from "@playwright/test";
import { copyFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE_BASE_FILE = fileURLToPath(
  new URL("../../tests/fixtures/synthetic_base.xlsx", import.meta.url),
);

/** Set base file path via window hook (bypasses prompt() for headless E2E). */
async function openBaseFile(page: import("@playwright/test").Page) {
  const baseFile = test.info().outputPath("synthetic_base.xlsx");
  await mkdir(dirname(baseFile), { recursive: true });
  await copyFile(SOURCE_BASE_FILE, baseFile);
  await page.goto("/");
  await page.evaluate(
    (path) => (window as any).__workbench__?.openSession(path),
    baseFile,
  );
  await page.waitForTimeout(2000);
}

async function selectGsSeller(page: import("@playwright/test").Page) {
  await page.locator(".filter-pill").filter({ hasText: "GS PTE" }).click();
}

async function selectPiDocument(page: import("@playwright/test").Page) {
  await page.locator(".filter-pill").filter({ hasText: "PI" }).click();
}

async function toggleExportByTestId(page: import("@playwright/test").Page, id: string) {
  await page.getByTestId(id).locator(".checkbox").click();
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

  test("invoice data check shows read-only shipment rows and issues", async ({ page }) => {
    await openBaseFile(page);
    await page.getByTestId("preview-scope-invoice").click();
    await expect(page.locator(".invoice-card")).toHaveCount(2);
    await page.locator(".invoice-card").filter({ hasText: "INV-2601-001" }).click();

    const table = page.getByTestId("invoice-inspection-table");
    await expect(table).toBeVisible();
    await expect(table.locator("tbody tr")).toHaveCount(3);
    await expect(table).toContainText("4500030844");
    await expect(table).toContainText("SHIP QTY");
    await expect(page.getByTestId("cell-edit-input")).toHaveCount(0);
    await expect(page.locator(".issue-bar")).toContainText("Invoice 基础检查");

    const warningBadge = page.locator(".issue-badge.fix");
    await expect(warningBadge).toBeVisible();
    await warningBadge.click();
    await expect(page.locator(".data-warning-panel")).toContainText("NO_PRICES");
  });

  test("invoice data check explains blocking issues", async ({ page }) => {
    await page.route("**/api/invoice/*/inspection", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.blocking_count = 1;
      data.blocking_errors = [{
        kind: "blocking_error",
        code: "INVOICE_GROUP_HEADER_CONFLICT",
        message: "票据组跨 PO 的 ship_to 不一致",
        sheet: "PO record",
        row: 5,
        field: "ship_to",
        severity: null,
      }];
      await route.fulfill({ response, json: data });
    });
    await openBaseFile(page);
    await page.getByTestId("preview-scope-invoice").click();

    const blockedBadge = page.locator(".issue-badge.blocked");
    await expect(blockedBadge).toBeVisible();
    await blockedBadge.click();
    await expect(page.locator(".data-issue-panel")).toContainText("ship_to 不一致");
  });

  test("invoice scope lists groups and previews invoice", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await page.getByTestId("preview-scope-invoice").click();

    const groups = page.locator(".invoice-card");
    await expect(groups).toHaveCount(2);
    await groups.filter({ hasText: "INV-2603-001" }).click();

    await expect(page.getByTestId("invoice-document-INVOICE_PL")).toBeVisible();
    await expect(page.locator(".document-card").first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator(".document-card").first()).toContainText("INV-2603-001");
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

    // The structured header uses the exact label from the Excel template.
    await expect(page.getByRole("row", { name: /PI Number: 4500099999/ })).toBeVisible();
  });

  test("PI preview header matches its Excel template", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);
    await selectPiDocument(page);
    await expect(page.locator(".lines-table th").first()).toHaveText(
      "Country of The Origin",
    );
  });

  test("PO preview defaults to PI and never offers Invoice PL quick export", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);

    await expect(page.getByRole("button", { name: "导出 Invoice & Packing List", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "导出 PI", exact: true })).toBeVisible();
    await expect(page.locator(".preview-doc-title")).toContainText("PROFORMA INVOICE");
  });

  test("PO preview keeps invoice documents in their own scope", async ({ page }) => {
    await openBaseFile(page);
    const poCard = page.locator(".po-card").filter({ hasText: "4500099999" });
    await expect(poCard).toContainText("PO record 1 行");
    await poCard.click();

    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await selectGsSeller(page);
    await selectPiDocument(page);
    await expect(page.locator(".preview-scope")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "PI", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "PO", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Invoice", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "PL", exact: true })).toHaveCount(0);
    await expect(page.locator(".invoice-filter-group")).toHaveCount(0);
    await expect(page.locator(".invoice-select")).toHaveCount(0);

    await page.getByTestId("preview-scope-invoice").click();
    await expect(page.locator(".invoice-card")).toHaveCount(2);
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

    await expect(page.locator('[data-testid$="-INVOICE_PL"]')).toHaveCount(0);
    await expect(page.locator('[data-testid^="export-invoice-"]')).toHaveCount(0);

    for (const row of await page.locator(".check-line").all()) {
      const testId = await row.getAttribute("data-testid");
      const checkbox = row.locator(".checkbox");
      if (testId !== "export-doc-GS_PTE-PI") await checkbox.click();
    }

    const exportBtn = page.locator("button").filter({ hasText: "确认导出" });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();
    await page.waitForTimeout(2000);

    const statusBar = page.locator("footer");
    await expect(statusBar).toContainText("已导出");
    await expect(statusBar).toContainText(".xlsx");
  });

  test("invoice export uses the selected group contract", async ({ page }) => {
    const exportRequests: unknown[] = [];
    await page.route("**/api/invoice/*/export-batch", async (route) => {
      exportRequests.push(route.request().postDataJSON());
      await route.fulfill({
        json: {
          status: "success",
          summary: {},
          files: ["GS_PTE-GS-INVOICE-INV_2603_001.xlsx"],
          output_file: "GS_PTE-GS-INVOICE-INV_2603_001.xlsx",
          errors: [],
          warnings: [],
          missing_inputs: [],
          source_index: [],
        },
      });
    });

    await openBaseFile(page);
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await page.getByTestId("preview-scope-invoice").click();
    await page.locator(".invoice-card").filter({ hasText: "INV-2603-001" }).click();

    await page.locator(".tab").filter({ hasText: "导出确认" }).click();
    await expect(page.getByTestId("export-doc-GS_PTE-INVOICE")).toContainText("GS-INVOICE");
    await expect(page.getByTestId("export-doc-GS_PTE-PL")).toContainText("GS-PL");
    await toggleExportByTestId(page, "export-doc-GS_PTE-PL");

    const exportBtn = page.locator("button").filter({ hasText: "确认导出" });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();

    await expect.poll(() => exportRequests.length).toBe(1);
    expect(exportRequests[0]).toMatchObject({
      groups: expect.arrayContaining([
        expect.objectContaining({ seller: "GS PTE", documents: ["INVOICE"] }),
      ]),
    });
  });

  test("export format selector controls output_formats", async ({ page }) => {
    const exportRequests: unknown[] = [];
    await page.route("**/api/po/*/export-batch", async (route) => {
      exportRequests.push(route.request().postDataJSON());
      await route.fulfill({
        json: {
          status: "success",
          summary: {},
          files: ["GS_PTE-GS-PI-4500099999.xlsx"],
          output_file: "GS_PTE-GS-PI-4500099999.xlsx",
          errors: [],
          warnings: [],
          missing_inputs: [],
          source_index: [],
        },
      });
    });

    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(1500);
    await page.locator(".tab").filter({ hasText: "导出确认" }).click();

    // 默认只勾 Excel；加勾 PDF 后，请求应带 output_formats: ["xlsx","pdf"]
    await page.getByTestId("export-format-pdf").click();

    const exportBtn = page.locator("button").filter({ hasText: "确认导出" });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();

    await expect.poll(() => exportRequests.length).toBe(1);
    expect(exportRequests[0]).toMatchObject({ output_formats: ["xlsx", "pdf"] });
  });

  test("export screen disables documents that are not exportable for seller", async ({ page }) => {
    await page.route("**/api/session/open", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      for (const po of data.po_list ?? []) {
        if (po.po_no === "4500099999") {
          po.exportable_documents_by_seller = {
            ...(po.exportable_documents_by_seller ?? {}),
            SK: [],
          };
        }
      }
      await route.fulfill({ response, json: data });
    });

    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.locator(".tab").filter({ hasText: "导出确认" }).click();

    const skPi = page.getByTestId("export-doc-SK-PI");
    await expect(skPi).toHaveClass(/disabled/);
    await expect(skPi.locator(".checkbox")).toHaveClass(/disabled/);
    await expect(skPi.locator(".checkbox")).not.toHaveClass(/on/);
    await skPi.locator(".checkbox").click();
    await expect(skPi.locator(".checkbox")).not.toHaveClass(/on/);
  });

  test("export surfaces core blocking error for SK PI", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500030844" }).click();
    await page.waitForTimeout(2000);

    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await page.locator(".filter-pill").filter({ hasText: "SK" }).click();
    await selectPiDocument(page);

    await page.locator(".tab").filter({ hasText: "导出确认" }).click();
    const exportBtn = page.locator("button").filter({ hasText: "确认导出" });
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();

    await expect(page.locator(".export-err")).toContainText("QTY_MISSING");
    await expect(page.locator(".export-err")).toContainText("Material = 21-44642");
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

  test("PF MOQ and full-carton reminders are visible in data check", async ({ page }) => {
    await page.route("**/api/po/*/issues?*", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.warnings_count = 2;
      data.warnings = [
        {
          kind: "warning",
          code: "MOQ_NOT_MET",
          message: "SAP 10001 的客户订单数量 90 低于 MOQ 100，请确认是否调整订单数量",
          sheet: "new PO template",
          row: 2,
          field: "Order Quantity",
          severity: "high",
        },
        {
          kind: "warning",
          code: "FULL_CARTON_NOT_MET",
          message: "SAP 10001 的客户订单数量 90 不是整箱数量 24 的整数倍（余数 18），请确认装箱安排",
          sheet: "new PO template",
          row: 2,
          field: "Order Quantity",
          severity: "high",
        },
      ];
      await route.fulfill({ response, json: data });
    });

    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    const warningBadge = page.locator(".issue-badge.fix");
    await expect(warningBadge).toContainText("2 项警告");
    await warningBadge.click();

    const warningPanel = page.locator(".data-warning-panel");
    await expect(warningPanel).toContainText("低于 MOQ 100");
    await expect(warningPanel).toContainText("不是整箱数量 24 的整数倍");
    await expect(warningPanel).toContainText("new PO template / row 2 / Order Quantity");
    await expect(warningPanel).toContainText("MOQ_NOT_MET");
    await expect(warningPanel).toContainText("FULL_CARTON_NOT_MET");
  });

  test("customer-PO-only rows are shown as read-only projections", async ({ page }) => {
    await page.route("**/api/po/4500099999?*", async (route) => {
      await route.fulfill({
        json: {
          po_no: "4500099999",
          headers: ["PO NO.", "SAP Number", "DESCRIPTION"],
          rows: [{ "PO NO.": "4500099999", "SAP Number": "10001", DESCRIPTION: "PF test item" }],
        },
      });
    });

    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();

    await expect(page.locator(".projection-note")).toContainText("客户订单只读投影");
    await expect(page.locator(".data-table tbody .row-num")).toHaveText("—");
    await page.locator(".data-table tbody td").nth(1).dblclick();
    await expect(page.getByTestId("cell-edit-input")).toHaveCount(0);
  });

  test("invoice and PL previews render together in combined tab", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await page.getByTestId("preview-scope-invoice").click();
    await page.locator(".invoice-card").filter({ hasText: "INV-2603-001" }).click();

    await expect(page.getByTestId("invoice-document-INVOICE_PL")).toBeVisible();
    await expect(page.locator(".preview-doc-section")).toHaveCount(2, { timeout: 8000 });
    await expect(page.locator(".preview-doc-title").first()).toContainText(/Invoice|COMMERCIAL INVOICE/);
    await expect(page.locator(".preview-doc-title").last()).toContainText(/PL|PACKING LIST/);
    await expect(page.locator(".preview-body > .alert")).toHaveCount(0);
  });

  test("data check ignores preview blocking issues for ready PO", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();

    const issueBadge = page.locator(".issue-badge.blocked");
    await expect(issueBadge).toHaveCount(0);
    await expect(page.locator(".issue-bar")).toContainText("PO 基础检查");
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

  test("preview screen exports PDF", async ({ page }) => {
    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);

    // Navigate to preview tab, pick seller + document
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await page.waitForTimeout(2000);
    // select GS PTE seller (filter pills on preview)
    await page.locator(".filter-pill").filter({ hasText: "GS PTE" }).click();
    await page.waitForTimeout(1000);
    // select PI document
    await page.locator(".filter-pill").filter({ hasText: "PI" }).click();
    await page.waitForTimeout(2000);

    // Click the "导出 PDF" button and capture download
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "导出 PDF" }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  });

  test("shows LibreOffice prompt when converter is unavailable", async ({ page }) => {
    // 拦截导出请求，模拟后端"未装 LibreOffice"阻断错误（与 CI 是否装了 soffice 无关）。
    await page.route("**/api/po/*/export", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "error",
          summary: {},
          files: [],
          output_file: null,
          errors: [
            {
              kind: "blocking_error",
              code: "PDF_CONVERTER_UNAVAILABLE",
              message: "未检测到 LibreOffice",
              sheet: null,
              row: null,
              field: null,
            },
          ],
          warnings: [],
          missing_inputs: [],
          source_index: [],
        }),
      }),
    );

    await openBaseFile(page);
    await page.locator(".po-card").filter({ hasText: "4500099999" }).click();
    await page.waitForTimeout(2000);
    await page.locator(".tab").filter({ hasText: "单据预览" }).click();
    await page.waitForTimeout(2000);
    await selectGsSeller(page);
    await page.waitForTimeout(1000);
    await selectPiDocument(page);
    await page.waitForTimeout(2000);

    await page.getByRole("button", { name: "导出 PDF" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("需要安装 LibreOffice");
    await expect(dialog.getByRole("link", { name: "前往下载" })).toHaveAttribute(
      "href",
      /libreoffice\.org/,
    );

    await dialog.getByRole("button", { name: "关闭" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});
