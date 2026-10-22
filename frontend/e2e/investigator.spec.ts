import { test, expect } from "@playwright/test";

const operatorToken = process.env.E2E_OPERATOR_TOKEN;

test("delivery investigator requires confirmation, preserves frozen experiments, and records resolution", async ({
  page,
}, testInfo) => {
  test.skip(
    !operatorToken,
    "Set E2E_OPERATOR_TOKEN for the authorized evidence-review journey.",
  );
  test.setTimeout(120000);
  await page.addInitScript(
    (value) => sessionStorage.setItem("recallops-token", value),
    operatorToken!,
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Start investigator demo" }).click();
  await expect(
    page.getByRole("heading", { name: "Investigate the missing evidence" }),
  ).toBeVisible({ timeout: 45000 });
  const incidentId = new URL(page.url()).pathname.split("/").at(-1)!;
  const headers = { Authorization: `Bearer ${operatorToken}` };
  await expect(
    page.getByText("0 units on internal hold", { exact: true }),
  ).toBeVisible();
  const candidate = page
    .locator(".investigator-claim")
    .filter({ hasText: "D-104" });
  await expect(candidate).toHaveCount(1);
  const accept = candidate.getByRole("button", {
    name: "Confirm association & reassess",
  });
  await expect(accept).toBeDisabled();
  await candidate
    .getByLabel("Stock described by this record")
    .selectOption({ label: "SALMON-DELIVERY · 24 units · Batch unknown" });
  await candidate
    .getByLabel("Reason for this evidence decision")
    .fill(
      "Fictional demonstration: receiving reference D-104 matches these 24 units and the document batch.",
    );
  await expect(accept).toBeDisabled();
  await candidate.getByRole("checkbox").check();
  await accept.click();
  await expect(candidate.getByText("accepted", { exact: true })).toBeVisible({
    timeout: 30000,
  });
  await expect(
    page.getByText("24 units on internal hold", { exact: true }),
  ).toBeVisible({ timeout: 45000 });
  await expect(page.locator(".investigator-changes")).toContainText("affected");

  const detailBefore = await (
    await page.request.get(`/api/incidents/${incidentId}`, { headers })
  ).json();
  const latestRunId = detailBefore.runs.at(-1).id;
  await page.getByLabel("Frozen investigation").selectOption(latestRunId);
  await page.getByRole("button", { name: "Run isolated comparison" }).click();
  await expect(page.locator(".investigator-simulation")).toContainText(
    "review",
  );
  await page.getByRole("button", { name: "Select saved evidence" }).click();
  await page.getByRole("button", { name: "Run isolated comparison" }).click();
  await expect(page.locator(".investigator-simulation")).toContainText(
    "affected",
  );
  const detailAfter = await (
    await page.request.get(`/api/incidents/${incidentId}`, { headers })
  ).json();
  expect(detailAfter.holds).toEqual(detailBefore.holds);
  expect(detailAfter.decisions.length).toBe(detailBefore.decisions.length);

  const resolution = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "Document the human resolution" }),
  });
  await resolution
    .getByLabel("Reviewed finding and reason")
    .fill(
      "Reviewed the D-104 source and confirmed the association. Affected stock remains held for physical withdrawal.",
    );
  const validation = detailAfter.evidence.find(
    (e: { kind: string; payload: { accept?: boolean } }) =>
      e.kind === "claim_validation" && e.payload.accept,
  );
  await resolution
    .getByRole("checkbox", { name: validation.label, exact: true })
    .check();
  await resolution
    .getByRole("button", { name: "Record review resolution" })
    .click();
  await expect(resolution).toContainText("Review status: resolved", {
    timeout: 30000,
  });
  await expect(
    page.getByText("24 units on internal hold", { exact: true }),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("investigator-mobile.png"),
    fullPage: false,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("investigator-desktop.png"),
    fullPage: false,
  });
  await candidate
    .getByRole("button", { name: "Revise evidence decision" })
    .click();
  await candidate
    .getByLabel("Reason for this evidence decision")
    .fill(
      "Fictional review correction: this source association is no longer supported; preserve the existing hold.",
    );
  await candidate.getByRole("button", { name: "Reject claim" }).click();
  await expect(candidate.getByText("rejected", { exact: true })).toBeVisible({
    timeout: 30000,
  });
  await expect(
    page.getByText("24 units on internal hold", { exact: true }),
  ).toBeVisible();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/incidents/${incidentId}`, { headers })
          ).json()
        ).incident.review_status,
    )
    .not.toBe("resolved");
  await page.getByRole("link", { name: "Inspect the unresolved case" }).click();
  await expect(
    page.getByRole("heading", {
      name: /What batch is printed on these 7 units|Check the physical label/,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("0 units on internal hold", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".investigator-conclusions")).toContainText(
    "review",
  );
});

test("investigator comparison reports human setup work and execution mode", async ({
  page,
}) => {
  test.skip(
    !operatorToken,
    "Set E2E_OPERATOR_TOKEN for the authorized evaluation run.",
  );
  test.setTimeout(120000);
  await page.addInitScript(
    (value) => sessionStorage.setItem("recallops-token", value),
    operatorToken!,
  );
  await page.goto("/evaluation");
  await expect(
    page.getByText(/Offline adaptive retrieval measures a policy/),
  ).toBeVisible();
  const measured = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/investigator/evaluation") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Compare investigation strategies" })
    .click();
  const measuredResponse = await measured;
  expect(measuredResponse.ok()).toBeTruthy();
  const measuredResult = await measuredResponse.json();
  expect(measuredResult.results.length).toBeGreaterThanOrEqual(3);
  await expect(
    page.getByRole("cell", { name: "Existing workflow", exact: false }),
  ).toBeVisible({ timeout: 90000 });
  await expect(
    page.getByRole("columnheader", {
      name: "Operator interventions / setup confirmations",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Fixed retrieval", exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Adaptive investigator", exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Dataset provenance", { exact: true }),
  ).toBeVisible();
});

test("external investigation labels retain declared provenance", async ({
  page,
}) => {
  test.skip(!operatorToken, "Set E2E_OPERATOR_TOKEN for external evaluation.");
  test.setTimeout(120000);
  await page.addInitScript(
    (value) => sessionStorage.setItem("recallops-token", value),
    operatorToken!,
  );
  await page.goto("/evaluation");
  await page
    .getByText("Use a separately labeled investigation dataset", {
      exact: true,
    })
    .click();
  await page
    .getByLabel("Investigator evaluation JSON (optional, maximum 2 MB)")
    .setInputFiles({
      name: "browser-labels.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        JSON.stringify({
          source: "Browser synthetic validation dataset",
          labeler: "Test fixture author",
          independent_review_declared: false,
          cases: [
            {
              name: "No delivery remains unresolved",
              lot: null,
              claims: [],
              expected: "review",
              split: "held_out",
            },
          ],
        }),
      ),
    });
  await expect(
    page.getByText(/Independence and held-out status are author declarations/),
  ).toBeVisible();
  const measured = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/investigator/evaluation") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Compare investigation strategies" })
    .click();
  const response = await measured;
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.sample_size).toBe(1);
  expect(result.benchmark).toContain("Browser synthetic validation dataset");
  const provenance = result.cases.find(
    (item: { name: string }) => item.name === "Dataset provenance",
  );
  expect(provenance.independent_review_verified).toBe(false);
  expect(provenance.labeler).toBe("Test fixture author");
  await expect(
    page.getByText("No delivery remains unresolved", { exact: true }),
  ).toBeVisible();
});

test("original recall replay still reaches a held conflict", async ({
  page,
}) => {
  test.skip(
    !operatorToken,
    "Set E2E_OPERATOR_TOKEN for the authenticated development workspace.",
  );
  test.setTimeout(90000);
  await page.addInitScript(
    (value) => sessionStorage.setItem("recallops-token", value),
    operatorToken!,
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Run incident simulation" }).click();
  await expect(page.getByText("Stage 1 of 3")).toBeVisible();
  await page.getByRole("button", { name: "Inject next evidence" }).click();
  await expect(page.getByText("Stage 2 of 3")).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Inject next evidence" }).click();
  await expect(page.getByText("Scenario complete")).toBeVisible({
    timeout: 30000,
  });
  await page.getByRole("link", { name: "Open incident", exact: true }).click();
  await expect(
    page.getByText("24 units on internal hold", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".decision-conflict")).toBeVisible();
});
