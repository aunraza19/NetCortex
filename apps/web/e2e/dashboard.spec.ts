import { expect, test } from "@playwright/test";
import path from "node:path";

test("overview and site layout render at desktop and phone widths", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Network overview" }),
  ).toBeVisible();
  await expect(page.getByText("Demo: replayed data").first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "North Tower" }),
  ).toBeVisible();
  await expect(page.getByText("Rawalpindi · 120 subscribers")).toBeVisible();
  await expect(page.getByText("ether1 · 180 Mbps")).toBeVisible();
  await expect(page.getByText("Lahore · 48 subscribers")).toBeVisible();
  await expect(page.getByText("ether1 · 100 Mbps")).toBeVisible();
  await expect(page.getByText("Islamabad · 165 subscribers")).toBeVisible();
  await expect(page.getByText("ether1 · 250 Mbps")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Latency forecast" }),
  ).toBeVisible();
  await page.addStyleTag({
    content: "nextjs-portal { display: none !important; }",
  });
  await page.screenshot({
    path: path.resolve(
      process.cwd(),
      "test-results",
      `overview-${testInfo.project.name}.png`,
    ),
    fullPage: true,
  });
});

test("approval needs confirmation and visibly simulates each stage", async ({
  page,
}) => {
  await page.goto("/incidents/INC-2084");
  await page.getByRole("button", { name: "Approve change" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Go back" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("button", { name: "Approve change" }).first().click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Approve change" })
    .dblclick();
  await expect(page.getByText("applying", { exact: true })).toBeVisible();
  await expect(page.getByText("verifying", { exact: true })).toBeVisible();
  await expect(page.getByText("resolved", { exact: true })).toBeVisible();
});

test("failed router check blocks approval and rejection is confirmed", async ({
  page,
}) => {
  await page.goto("/incidents/INC-2083");
  await expect(page.getByText("Router test failed").first()).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve change" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Reject change" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Reject change" })
    .click();
  await expect(page.getByText("rejected", { exact: true })).toBeVisible();
});

test("demo injection opens a new coherent incident", async ({ page }) => {
  await page.goto("/demo");
  await page.getByLabel("Scenario", { exact: true }).selectOption("dns_slow");
  await page.getByRole("button", { name: "Replay scenario" }).click();
  await expect(
    page.getByText("Scenario replayed. A reviewable incident is ready."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Open incident" }).click();
  await expect(
    page.getByText(
      "CHR test simulated · replay fixture only · no router command was sent",
    ),
  ).toBeVisible();
});

test("uplink down at a site without backup is notify-only", async ({
  page,
}) => {
  await page.goto("/demo");
  await page.getByLabel("Network site").selectOption("market-cafe");
  await page
    .getByLabel("Scenario", { exact: true })
    .selectOption("uplink_down");
  await page.getByRole("button", { name: "Replay scenario" }).click();
  await expect(page.getByText(/no router change is proposed/i)).toBeVisible();
  await page.getByRole("link", { name: "Open incident" }).click();
  await expect(page.getByText(/no backup uplink is configured/i)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve change" }),
  ).toHaveCount(0);
});

test("an approved backup failover can simulate rollback", async ({ page }) => {
  await page.goto("/demo");
  await page
    .getByLabel("Scenario", { exact: true })
    .selectOption("uplink_down");
  await page.getByRole("button", { name: "Replay scenario" }).click();
  await page.getByRole("link", { name: "Open incident" }).click();
  await page.getByRole("button", { name: "Approve change" }).first().click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Approve change" })
    .click();
  await expect(page.getByText("applying", { exact: true })).toBeVisible();
  await expect(page.getByText("verifying", { exact: true })).toBeVisible();
  await expect(page.getByText("rolled back", { exact: true })).toBeVisible();
});

test("unknown incident reports an explicit missing record", async ({
  page,
}) => {
  await page.goto("/incidents/unknown");
  await expect(
    page.getByText("Incident not found. Refresh the list and try again."),
  ).toBeVisible();
});
