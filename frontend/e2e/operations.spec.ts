import { test, expect } from "@playwright/test";

test("source history, quarantine and worker recovery are inspectable", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Operations & access" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Load archived fixture" }).click();
  await expect(page.getByText(/Source: snapshot/)).toBeVisible({
    timeout: 30000,
  });
  await page.getByRole("button", { name: "Inspect refresh" }).first().click();
  await expect(
    page.getByRole("heading", { name: "Refresh details & rejected records" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Worker recovery" }).click();
  await expect(page.getByText(/Worker heartbeat:/)).toBeVisible();
  await page.getByRole("button", { name: "Access & stores" }).click();
  await expect(
    page.getByRole("combobox", { name: "Credential role" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create scoped credential" }),
  ).toBeDisabled();
});

test("benchmark importer rejects invalid JSON visibly", async ({ page }) => {
  await page.goto("/evaluation");
  await page
    .getByLabel("Labeled benchmark JSON")
    .setInputFiles({
      name: "invalid.json",
      mimeType: "application/json",
      buffer: Buffer.from('{"source":"missing labels"}'),
    });
  await expect(page.getByRole("alert")).toContainText("required");
});
