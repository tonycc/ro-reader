import { test, expect } from "@playwright/test";
import { resolve } from "node:path";

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
