import { test, expect } from "@playwright/test";

test("priority links preserve review context and filters can be cleared", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("link").filter({ hasText: "Awaiting review" }).click();
  await expect(page).toHaveURL(/attention=review/);
  await expect(
    page.getByText("Showing cases that need human review", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear view" }).click();
  await page
    .getByRole("textbox", { name: "Search incidents" })
    .fill("no-such-product-984927");
  await expect(
    page.getByRole("heading", { name: "No incidents match these filters" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(
    page.getByRole("textbox", { name: "Search incidents" }),
  ).toHaveValue("");
});

test("workspace selection persists across a reload", async ({ page }) => {
  await page.goto("/inventory");
  await page.getByRole("combobox", { name: "Data mode" }).selectOption("live");
  await expect(page).toHaveURL(/\/$/);
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Data mode" })).toHaveValue(
    "live",
  );
  await page
    .getByRole("combobox", { name: "Data mode" })
    .selectOption("replay");
});

test("mobile navigation supports Escape and all primary pages fit", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const menu = page.getByRole("button", { name: "Open navigation" });
  await menu.click();
  await expect(
    page.getByRole("button", { name: "Close navigation" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  for (const [path, heading] of [
    ["/", "Command overview"],
    ["/incidents", "Incidents"],
    ["/inventory", "Inventory & lots"],
    ["/evidence", "Evidence graph"],
    ["/time-machine", "Decision time machine"],
    ["/evaluation", "Evaluation lab"],
    ["/settings", "Data & settings"],
  ]) {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Loading recorded data" }),
    ).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    if (path === "/")
      await expect(
        page.getByRole("heading", { name: "Your investigation queue" }),
      ).toBeVisible();
    const layout = await page.evaluate(() => ({
      width: window.innerWidth,
      scroll: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll("body *")]
        .filter((e) => e.getBoundingClientRect().right > window.innerWidth)
        .map((e) => ({
          tag: e.tagName,
          class: e.className,
          right: e.getBoundingClientRect().right,
        }))
        .slice(0, 12),
    }));
    expect(
      layout.scroll,
      JSON.stringify({ path: page.url(), ...layout }),
    ).toBeLessThanOrEqual(layout.width);
    if (path === "/")
      await page.screenshot({
        path: "../docs/screenshots/dashboard-mobile.png",
        fullPage: true,
      });
  }
});

test("desktop overview fits tablet and desktop widths", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your investigation queue" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/overview-redesign.png",
    fullPage: true,
  });
  for (const width of [768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const layout = await page.evaluate(() => ({
      width: window.innerWidth,
      scroll: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll("body *")]
        .filter((e) => e.getBoundingClientRect().right > window.innerWidth)
        .map((e) => ({
          tag: e.tagName,
          class: e.className,
          right: e.getBoundingClientRect().right,
        }))
        .slice(0, 12),
    }));
    expect(
      layout.scroll,
      JSON.stringify({ path: page.url(), ...layout }),
    ).toBeLessThanOrEqual(layout.width);
  }
});

test("operator can verify the real configured model connection", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_LIVE_PROVIDER_TESTS !== "1",
    "Explicit opt-in required for a real paid provider request.",
  );
  await page.goto("/settings");
  await page.getByRole("button", { name: "Test model connection" }).click();
  await expect(
    page.getByText("Connection verified", { exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page.screenshot({
    path: "../docs/screenshots/model-connection.png",
    fullPage: true,
  });
});
