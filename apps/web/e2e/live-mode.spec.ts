import { expect, test } from "@playwright/test";

test("live API errors remain visible and never show fixture records", async ({
  page,
}) => {
  await page.route("http://127.0.0.1:3137/**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "service unavailable" }),
    }),
  );
  await page.goto("/");
  await expect(
    page.getByText("API request failed (503). Try again."),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "North Tower" })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("No latency forecast data is available yet."),
  ).toBeVisible();
  await expect(page.getByText("Live network data")).toBeVisible();
  await expect(page.getByText("Demo: replayed data")).toHaveCount(0);
});

test("named stream events refetch data, duplicate ids are ignored, and listeners close with the page", async ({
  page,
}) => {
  let siteReads = 0;
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/sites") {
      siteReads += 1;
      await route.fulfill({
        json: [
          {
            id: "demo-live",
            name: "Live Test Site",
            location: "Lahore",
            subscribers: 12,
            health: "ok",
            utilization: 20,
            latency: 15,
            loss: 0,
            uplink: "ether1",
          },
        ],
      });
    } else if (url.pathname === "/incidents") {
      await route.fulfill({ json: [] });
    } else if (url.pathname === "/metrics") {
      await route.fulfill({
        json: [{ time: "10:00", actual: 15, p10: 10, p50: 14, p90: 19 }],
      });
    } else {
      await route.fulfill({ status: 204, body: "" });
    }
  });
  await page.addInitScript(() => {
    const listeners = new Map<string, Set<(event: Event) => void>>();
    class FakeEventSource {
      onerror: ((event: Event) => void) | null = null;
      onopen: (() => void) | null = null;
      constructor() {
        Object.assign(window, { netCortexSource: this });
      }
      addEventListener(type: string, callback: (event: Event) => void) {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type)?.add(callback);
      }
      removeEventListener(type: string, callback: (event: Event) => void) {
        listeners.get(type)?.delete(callback);
      }
      close() {
        Object.assign(window, { streamClosed: true });
      }
    }
    Object.assign(window, {
      EventSource: FakeEventSource,
      dispatchNetCortexEvent: (type: string, id: string) =>
        listeners
          .get(type)
          ?.forEach((callback) =>
            callback(new MessageEvent(type, { lastEventId: id })),
          ),
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Live Test Site" }),
  ).toBeVisible();
  await expect.poll(() => siteReads).toBe(1);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        netCortexSource: { onopen: (() => void) | null };
      }
    ).netCortexSource.onopen?.(),
  );
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        dispatchNetCortexEvent: (type: string, id: string) => void;
      }
    ).dispatchNetCortexEvent("incident.opened", "event-17"),
  );
  await expect.poll(() => siteReads).toBe(2);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        dispatchNetCortexEvent: (type: string, id: string) => void;
      }
    ).dispatchNetCortexEvent("incident.opened", "event-17"),
  );
  await page.waitForTimeout(150);
  expect(siteReads).toBe(2);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        netCortexSource: { onerror: ((event: Event) => void) | null };
      }
    ).netCortexSource.onerror?.(new Event("error")),
  );
  await expect.poll(() => siteReads).toBe(3);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        netCortexSource: { onopen: (() => void) | null };
      }
    ).netCortexSource.onopen?.(),
  );
  await expect.poll(() => siteReads).toBe(4);
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as unknown as Window & { streamClosed?: boolean })
            .streamClosed,
      ),
    )
    .toBe(true);
});

test("live approval treats POST as an acknowledgement and reloads incident state", async ({
  page,
}) => {
  const incident = {
    id: "LIVE-1",
    siteId: "live-site",
    siteName: "Live Site",
    cause: "uplink_congestion",
    title: "Live uplink congestion",
    status: "awaiting_approval",
    confidence: 0.9,
    openedAt: "2026-10-18T10:00:00Z",
    summary: "Live record",
    evidence: ["Recorded probe evidence"],
    template: "priority_queue",
    fix: ["/queue tree add name=priority"],
    rollback: ["/queue tree remove priority"],
    dryRun: "passed",
    dryRunMessage: "Passed",
    timeline: [],
  };
  let reads = 0;
  let posted = false;
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/incidents/LIVE-1" && request.method() === "GET") {
      reads += 1;
      await route.fulfill({
        json: {
          ...incident,
          status: posted ? "applying" : "awaiting_approval",
          timeline: posted
            ? [
                {
                  at: "2026-10-18T10:01:00Z",
                  label: "Accepted",
                  detail: "Server update",
                  state: "active",
                },
              ]
            : [],
        },
      });
    } else if (
      url.pathname === "/incidents/LIVE-1/approve" &&
      request.method() === "POST"
    ) {
      posted = true;
      await route.fulfill({
        status: 202,
        json: { accepted: true, message: "queued" },
      });
    } else {
      await route.fulfill({ status: 204, body: "" });
    }
  });
  await page.goto("/incidents/LIVE-1");
  await page.getByRole("button", { name: "Approve change" }).first().click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Approve change" })
    .click();
  await expect(page.getByText("applying", { exact: true })).toBeVisible();
  expect(reads).toBeGreaterThanOrEqual(2);
});
