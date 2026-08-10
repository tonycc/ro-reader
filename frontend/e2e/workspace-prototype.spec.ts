import { test, expect } from "@playwright/test";

test.describe("Workspace interaction prototype", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/?workspace-prototype=1");
    await expect(page.getByTestId("workspace-switcher-trigger")).toContainText("RO 2026");
  });

  test("switcher keeps the current workspace when activation fails", async ({ page }) => {
    await page.getByTestId("workspace-switcher-trigger").click();
    await expect(page.getByTestId("workspace-option-ro-test")).toContainText("RO 测试");

    await page.getByTestId("workspace-option-ro-test").click();

    const error = page.getByTestId("workspace-switch-error");
    const trigger = page.getByTestId("workspace-switcher-trigger");
    const topbar = page.locator("header.topbar");
    const workflowTabs = page.locator(".mode-tabs");
    await expect(error).toContainText("找不到 base 文件");
    await expect(trigger).toContainText("RO 2026");
    const topbarBox = await topbar.boundingBox();
    const tabsBox = await workflowTabs.boundingBox();
    expect(topbarBox).not.toBeNull();
    expect(tabsBox).not.toBeNull();
    expect(tabsBox!.y).toBeGreaterThanOrEqual(topbarBox!.y + topbarBox!.height - 1);
    await trigger.click();
    await expect(page.getByTestId("workspace-option-ro-test")).toBeVisible();
  });

  test("settings supports creating, validating and activating a workspace", async ({ page }) => {
    await page.getByTestId("workspace-settings-button").click();
    const settings = page.getByTestId("workspace-settings");
    await expect(settings).toBeVisible();

    await settings.getByRole("button", { name: /新增工作区/ }).click();
    await expect(settings.getByTestId("workspace-form-dialog")).toBeVisible();
    await expect(settings.getByTestId("close-workspace-settings")).toHaveCount(0);
    await settings.getByLabel("工作区名称").fill("RO 备用");
    await settings.getByLabel("Base 文件路径").fill("/data/ro/missing-backup.xlsx");
    await settings.getByTestId("workspace-path-check").click();
    await expect(settings.getByTestId("workspace-path-status")).toContainText("文件不存在");
    await settings.getByLabel("Base 文件路径").fill("/data/ro/backup-base.xlsx");
    await settings.getByTestId("workspace-path-check").click();
    await expect(settings.getByTestId("workspace-path-status")).toContainText("可用");
    await settings.getByRole("button", { name: "保存工作区" }).click();

    const card = settings.locator(".workspace-card").filter({ hasText: "RO 备用" });
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "编辑" }).click();
    await expect(settings.getByTestId("workspace-form-dialog")).toBeVisible();
    await settings.getByLabel("Base 文件路径").fill("/data/ro/schema-error-base.xlsx");
    await settings.getByTestId("workspace-path-check").click();
    await expect(settings.getByTestId("workspace-path-status")).toContainText("格式不匹配");
    await settings.getByRole("button", { name: "取消" }).click();
    await expect(settings.getByTestId("workspace-form-dialog")).toHaveCount(0);
    await card.getByRole("button", { name: "检测" }).click();
    await expect(card).toContainText("可用");
    await card.getByRole("button", { name: "设为当前" }).click();
    await expect(page.getByTestId("workspace-switcher-trigger")).toContainText("RO 备用");
  });

  test("editing the current workspace leaves an explicit reactivation action", async ({ page }) => {
    await page.getByTestId("workspace-settings-button").click();
    const settings = page.getByTestId("workspace-settings");
    const current = settings.locator(".workspace-card").filter({ hasText: "RO 2026" });
    await current.getByRole("button", { name: "编辑" }).click();
    await settings.getByLabel("Base 文件路径").fill("/data/ro/updated-base.xlsx");
    await settings.getByRole("button", { name: "保存工作区" }).click();

    await expect(current).toContainText("待重新激活");
    const reactivate = current.getByRole("button", { name: "重新激活" });
    await expect(reactivate).toBeEnabled();
    await reactivate.click();
    await expect(page.getByTestId("workspace-switcher-trigger")).toContainText("RO 2026");
    await expect(current).not.toContainText("待重新激活");
  });
});
