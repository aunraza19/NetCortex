import { expect, test } from "@playwright/test";

test("merged API replay renders sites, nested incident detail, text and real REST decisions", async ({
  page,
  request,
}) => {
  const root = "http://127.0.0.1:8137";
  const sites = await (await request.get(`${root}/sites`)).json();
  expect(sites[0].id).toBe("sim-tower");
  const incidents = await (await request.get(`${root}/incidents`)).json();
  const pending = incidents.find(
    (item: { status: string }) => item.status === "awaiting_approval",
  );
  expect(pending).toBeTruthy();
  const detail = await (
    await request.get(`${root}/incidents/${pending.id}`)
  ).json();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: sites[0].name, exact: true }),
  ).toBeVisible();
  const primary = sites[0].uplinks.find(
    (uplink: { role: string }) => uplink.role === "primary",
  );
  expect(primary.iface).toBeTruthy();
  await expect(
    page.getByText(primary.iface, { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Demo: replayed data", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("API request failed", { exact: false }),
  ).toHaveCount(0);
  await page.goto(`/incidents/${pending.id}`);
  await expect(
    page.getByText(detail.incident.report.summary, { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText(detail.incident.report.customer_message_en, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(detail.incident.report.customer_message_ur, { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Approve change", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Approve change", exact: true })
    .click();
  await expect(page.locator(".status-resolved")).toBeVisible();
  const updated = await (
    await request.get(`${root}/incidents/${pending.id}`)
  ).json();
  expect(updated.incident.status).toBe("resolved");
});

test("saved API replay disables scenario injection and uses real site choices", async ({
  page,
}) => {
  await page.goto("/demo");
  await expect(page.getByRole("option", { name: /Sim Tower/ })).toHaveCount(1);
  await expect(
    page.getByRole("button", {
      name: /Replay scenario|Inject scenario|Run scenario/,
    }),
  ).toBeDisabled();
});
