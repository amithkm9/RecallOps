import { test, expect } from "@playwright/test";
test("operator follows an actual recall through revision and contradiction", async ({
  page,
}) => {
  test.setTimeout(90000); // The real provider may take up to 20s for each investigation.
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Command overview" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run incident simulation" }).click();
  await expect(
    page.getByRole("heading", { name: "Decision time machine" }),
  ).toBeVisible();
  await expect(page.getByText("Stage 1 of 3")).toBeVisible();
  await page.getByRole("button", { name: "Inject next evidence" }).click();
  await expect(page.getByText("Stage 2 of 3")).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("24 units · Lot 24326020")).toBeVisible();
  await page.getByRole("button", { name: "Inject next evidence" }).click();
  await expect(page.getByText("Scenario complete")).toBeVisible({
    timeout: 30000,
  });
  await page.screenshot({
    path: "../docs/screenshots/time-machine.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Open incident", exact: true }).click();
  await expect(page.getByText("24 units on internal hold")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Human review", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Evidence & execution" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence & contradictions" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add supplier evidence" }).click();
  await page
    .getByRole("combobox", { name: "Inventory lot", exact: true })
    .selectOption({ label: "SALMON-UNVERIFIED · 24326020 · 24 units" });
  await page
    .getByLabel("Supplier’s stated lot")
    .fill("BROWSER-TEST-DISPUTED-LOT");
  await page
    .getByLabel("Document or message reference")
    .fill("Browser verification statement");
  await page
    .getByLabel("What does the supplier say?")
    .fill("Fictional browser test: the supplier disputes this warehouse lot.");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "../docs/screenshots/supplier-evidence.png",
    fullPage: false,
  });
  await page.getByRole("button", { name: "Save & reassess" }).click();
  await expect(
    page.getByText("Reassessment completed.", { exact: false }),
  ).toBeVisible({ timeout: 45000 });
  await expect(page.getByText("24 units on internal hold")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Human review", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Decision & response" }).click();
  await expect(page.locator(".draft")).toContainText(
    "Active internal holds at the time of this draft: 24 units.",
  );
  await expect(page.locator(".draft")).not.toContainText(
    "UNVERIFIED MODEL WORDING",
  );
  await page
    .getByRole("textbox", { name: "Review notes" })
    .fill("Testing the release confirmation without releasing stock.");
  await page.getByRole("button", { name: "Authorize release" }).click();
  await expect(
    page.getByRole("region", { name: "Confirm hold release" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Keep hold" }).click();
  await expect(
    page.getByRole("region", { name: "Confirm hold release" }),
  ).toHaveCount(0);
  await page.getByRole("textbox", { name: "Review notes" }).fill("");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../docs/screenshots/incident-redesign.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Explore evidence graph" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence graph", exact: true }),
  ).toBeVisible();
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "Official recall" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Stored node record" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Inventory", exact: true }).click();
  await page
    .getByPlaceholder("Search SKU, GTIN, product or lot")
    .fill("SALMON-UNVERIFIED");
  await expect(page.getByText("24326020", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Command overview" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Your investigation queue" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/dashboard.png",
    fullPage: true,
  });
});
test("layout stays usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Data & settings" }).click();
  await expect(
    page.getByRole("heading", { name: "Data & settings", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
