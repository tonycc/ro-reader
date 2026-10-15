import { test, expect } from "@playwright/test";
import { resolve } from "node:path";
import { execFileSync } from "node:child_process";

test("real HTTP workspace bootstrap survives a page reload", async ({ page }) => {
  const baseFile = resolve(process.cwd(), "../tests/fixtures/synthetic_base.xlsx");
  await page.goto("/");
  await expect(page.getByTestId("workspace-switcher-trigger")).toContainText("未配置工作区");

  await page.getByTestId("workspace-settings-button").click();
  const settings = page.getByTestId("workspace-settings");
  await settings.getByRole("button", { name: /新增工作区/ }).click();
  await settings.getByLabel("工作区名称").fill("真实 HTTP RO");
  await settings.getByLabel("Base 文件路径").fill(baseFile);
  await settings.getByTestId("workspace-path-check").click();
  await expect(settings.getByTestId("workspace-path-status")).toContainText("可用");
  await settings.getByRole("button", { name: "保存工作区" }).click();

  const card = settings.locator(".workspace-card").filter({ hasText: "真实 HTTP RO" });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "检测" }).click();
  await expect(card).toContainText("可用");
  await card.getByRole("button", { name: "设为当前" }).click();
  await expect(card).toContainText("当前");
  await settings.getByTestId("close-workspace-settings").click();

  const trigger = page.getByTestId("workspace-switcher-trigger");
  await expect(trigger).toContainText("真实 HTTP RO");
  await expect(page.locator(".po-card")).toHaveCount(3);
  await expect(page.locator(".po-card").filter({ hasText: "4500099999" })).toHaveCount(1);

  await page.reload();
  await expect(page.getByTestId("workspace-switcher-trigger")).toContainText("真实 HTTP RO");
  await expect(page.locator(".po-card")).toHaveCount(3);
  await expect(page.locator(".po-card").filter({ hasText: "4500099999" })).toHaveCount(1);
});

test("SHEFISH workspace previews both factory POs and exports them together", async ({ page }) => {
  const baseFile = test.info().outputPath("shefish.xlsx");
  execFileSync(resolve(process.cwd(), "../.venv/bin/python"), [
    resolve(process.cwd(), "../tests/fixtures/generate_shefish_base.py"), baseFile,
  ]);
  await page.goto("/");
  await page.getByTestId("workspace-settings-button").click();
  const settings = page.getByTestId("workspace-settings");
  await settings.getByRole("button", { name: /新增工作区/ }).click();
  await settings.getByLabel("工作区名称").fill("SHEFISH 合成验收");
  await settings.getByLabel("Customer Profile").selectOption("shefish");
  await settings.getByLabel("Base 文件路径").fill(baseFile);
  await settings.getByTestId("workspace-path-check").click();
  await expect(settings.getByTestId("workspace-path-status")).toContainText("可用");
  await settings.getByRole("button", { name: "保存工作区" }).click();
  const card = settings.locator(".workspace-card").filter({ hasText: "SHEFISH 合成验收" });
  await card.getByRole("button", { name: "设为当前" }).click();
  await expect(card).toContainText("当前");
  await settings.getByTestId("close-workspace-settings").click();
  await page.locator(".po-card").filter({ hasText: "TEST-PO-01" }).click();
  await page.locator(".tab").filter({ hasText: "单据预览" }).click();
  await page.getByRole("button", { name: "GS PTE", exact: true }).click();
  await page.getByRole("button", { name: "PO", exact: true }).click();
  const documents = page.locator(".preview-doc-section");
  await expect(documents).toHaveCount(2);
  await expect(documents.first()).toContainText("PURCHASE ORDER · SK");
  await expect(documents.first()).toContainText("$6.00");
  await expect(documents.first()).toContainText("$1,260.00");
  await expect(documents.last()).toContainText("PURCHASE ORDER · YM");
  await expect(documents.last()).toContainText("$4.00");
  await expect(documents.last()).toContainText("$720.00");
  await expect(page.getByRole("button", { name: "YM", exact: true })).toHaveCount(0);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "导出 PO", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.zip$/);
  await page.screenshot({ path: test.info().outputPath("shefish-po-preview.png"), fullPage: true });

  await page.getByTestId("preview-scope-invoice").click();
  await page.locator(".invoice-card").filter({ hasText: "G26010101" }).click();
  await page.locator(".tab").filter({ hasText: "单据预览" }).click();
  await page.getByRole("button", { name: "SK", exact: true }).click();
  await page.getByRole("button", { name: "Invoice", exact: true }).click();
  await expect(documents).toHaveCount(1);
  await expect(documents.first()).toContainText("$630.00");
  await page.getByRole("button", { name: "PL", exact: true }).click();
  await expect(documents).toHaveCount(1);
  await expect(documents.first()).toContainText("PACKING LIST");
  await page.screenshot({ path: test.info().outputPath("shefish-pl-preview.png"), fullPage: true });

  await page.reload();
  await expect(page.getByTestId("workspace-switcher-trigger")).toContainText("SHEFISH 合成验收");
  await expect(page.locator(".po-card")).toHaveCount(1);
});
