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
  await expect(page.getByText("API status unavailable").first()).toBeVisible();
  await expect(page.getByText("Demo: replayed data")).toHaveCount(0);
});

test("named stream events refetch data, duplicate ids are ignored, and listeners close with the page", async ({
  page,
}) => {
  let incidentReads = 0;
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/health") {
      await route.fulfill({ json: { status: "ok", demo_mode: false } });
    } else if (url.pathname === "/sites") {
      await route.fulfill({
        json: [
          {
            id: "demo-live",
            name: "Live Test Site",
            health: "ok",
            worst_rtt_ms: 15,
            max_loss_pct: 0,
            uplink_util_pct: 20,
            open_incidents: 0,
            updated_at: "2026-10-18T10:00:00Z",
            uplinks: [
              { role: "primary", iface: "ether1", capacity_mbps: 180 },
              { role: "backup", iface: "ether2", capacity_mbps: 80 },
            ],
          },
        ],
      });
    } else if (url.pathname === "/incidents") {
      incidentReads += 1;
      await route.fulfill({ json: [] });
    } else if (url.pathname === "/metrics") {
      await route.fulfill({
        json: [
          {
            series_key: "probe:1.1.1.1:rtt_ms",
            points: [{ time: "2026-10-18T10:00:00Z", value: 15 }],
            forecast: [
              { time: "2026-10-18T10:01:00Z", p10: 10, p50: 14, p90: 19 },
            ],
          },
        ],
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
  await expect.poll(() => incidentReads).toBe(1);
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
  await expect.poll(() => incidentReads).toBe(2);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        dispatchNetCortexEvent: (type: string, id: string) => void;
      }
    ).dispatchNetCortexEvent("incident.opened", "event-17"),
  );
  await page.waitForTimeout(150);
  expect(incidentReads).toBe(2);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        netCortexSource: { onerror: ((event: Event) => void) | null };
      }
    ).netCortexSource.onerror?.(new Event("error")),
  );
  await expect.poll(() => incidentReads).toBe(3);
  await page.evaluate(() =>
    (
      window as unknown as Window & {
        netCortexSource: { onopen: (() => void) | null };
      }
    ).netCortexSource.onopen?.(),
  );
  await expect.poll(() => incidentReads).toBe(4);
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
    incident: {
      id: "LIVE-1",
      site_id: "live-site",
      cause: "uplink_congestion",
      status: "awaiting_approval",
      confidence: 0.9,
      opened_at: "2026-10-18T10:00:00Z",
      source: "sim",
      report: {
        summary: "Live record",
        likely_cause: "uplink_congestion",
        confidence: 0.9,
        evidence: ["Recorded probe evidence"],
        template_id: "priority_queue",
        template_params: {},
        customer_message_en: "English update",
        customer_message_ur: "اردو اپ ڈیٹ",
      },
    },
    fix_plan: {
      incident_id: "LIVE-1",
      template_id: "priority_queue",
      params: {},
      commands: "/queue tree add name=priority",
      rollback: "/queue tree remove priority",
      dry_run_ok: true,
      dry_run_log: "Passed",
    },
    timeline: [],
  };
  let reads = 0;
  let posted = false;
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/health") {
      await route.fulfill({ json: { status: "ok", demo_mode: false } });
    } else if (url.pathname === "/sites") {
      await route.fulfill({
        json: [
          {
            id: "live-site",
            name: "Live Site",
            health: "ok",
            open_incidents: 1,
            uplinks: [],
          },
        ],
      });
    } else if (
      url.pathname === "/incidents/LIVE-1" &&
      request.method() === "GET"
    ) {
      reads += 1;
      await route.fulfill({
        json: {
          ...incident,
          incident: {
            ...incident.incident,
            status: posted ? "verifying" : "awaiting_approval",
          },
          timeline: posted
            ? [
                {
                  time: "2026-10-18T10:01:00Z",
                  kind: "incident.updated",
                  payload: { label: "Accepted", detail: "Server update" },
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
        json: {
          incident_id: "LIVE-1",
          decision: "approved",
          note: "signal sent to the workflow",
        },
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
  await expect(page.getByText("verifying", { exact: true })).toBeVisible();
  expect(reads).toBeGreaterThanOrEqual(2);
});

test("live site adapters preserve primary and backup interfaces and unavailable readings", async ({
  page,
}) => {
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/health") {
      await route.fulfill({ json: { status: "ok", demo_mode: false } });
    } else if (url.pathname === "/sites") {
      await route.fulfill({
        json: [
          {
            id: "unknown-site",
            name: "Unknown Site",
            health: "unknown",
            worst_rtt_ms: null,
            max_loss_pct: null,
            uplink_util_pct: null,
            open_incidents: 1,
            uplinks: [
              { role: "primary", iface: "ether1", capacity_mbps: 180 },
              { role: "backup", iface: "ether2", capacity_mbps: 80 },
            ],
          },
        ],
      });
    } else if (url.pathname === "/incidents") {
      await route.fulfill({
        json: [
          {
            id: "00000000-0000-0000-0000-000000000002",
            site_id: "unknown-site",
            opened_at: "2026-10-18T10:00:00Z",
            closed_at: null,
            status: "awaiting_approval",
            cause: "uplink_congestion",
            confidence: null,
            summary: "Recorded incident",
            template_id: null,
          },
        ],
      });
    } else if (url.pathname === "/metrics") {
      await route.fulfill({
        json: [
          {
            series_key: "probe:1.1.1.1:rtt_ms",
            points: [{ time: "2026-10-18T10:00:00Z", value: null }],
            forecast: [
              { time: "2026-10-18T10:00:00Z", p10: 10, p50: 15, p90: 20 },
            ],
          },
        ],
      });
    } else {
      await route.fulfill({ status: 204, body: "" });
    }
  });
  await page.addInitScript(() => {
    class QuietEventSource {
      onerror = null;
      onopen = null;
      addEventListener() {}
      removeEventListener() {}
      close() {}
    }
    Object.assign(window, { EventSource: QuietEventSource });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Unknown Site" }),
  ).toBeVisible();
  await expect(page.getByText("Unknown", { exact: true })).toBeVisible();
  await expect(page.locator(".site-footer").first()).toContainText("ether1");
  await expect(page.locator(".site-footer").first()).toContainText(
    "Backup ether2",
  );
  await expect(page.locator(".site-metrics").first()).toContainText("—");
  await expect(page.getByText("Confidence unavailable")).toBeVisible();
  await expect(
    page.getByRole("img", {
      name: "Latency chart with 0 actual readings and 1 forecast readings",
    }),
  ).toBeVisible();
});

test("unknown API mode keeps scenario injection disabled", async ({ page }) => {
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/health")
      await route.fulfill({ status: 503, json: { detail: "unavailable" } });
    else if (url.pathname === "/sites")
      await route.fulfill({
        json: [
          {
            id: "live-site",
            name: "Live Site",
            health: "ok",
            open_incidents: 0,
            uplinks: [],
          },
        ],
      });
    else await route.fulfill({ json: [] });
  });
  await page.goto("/demo");
  await expect(
    page.getByRole("button", { name: "Replay scenario" }),
  ).toBeDisabled();
  await expect(
    page.getByText(
      "API mode could not be confirmed. Scenario actions remain disabled.",
    ),
  ).toBeVisible();
});

test("simulator injection errors stay visible without presenting a result", async ({
  page,
}) => {
  let submitted = false;
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/health")
      await route.fulfill({ json: { status: "ok", demo_mode: false } });
    else if (url.pathname === "/sites")
      await route.fulfill({
        json: [
          {
            id: "sim-tower",
            name: "Sim Tower",
            health: "ok",
            open_incidents: 0,
            uplinks: [],
          },
        ],
      });
    else if (
      url.pathname === "/demo/scenarios" &&
      route.request().method() === "POST"
    ) {
      submitted = true;
      await route.fulfill({
        status: 400,
        json: { detail: "unsupported scenario for this topology" },
      });
    } else await route.fulfill({ json: [] });
  });
  await page.goto("/demo");
  await expect(
    page.getByRole("button", { name: "Replay scenario" }),
  ).toBeEnabled();
  await page
    .getByLabel("Scenario", { exact: true })
    .selectOption("game_route_issue");
  await page.getByRole("button", { name: "Replay scenario" }).click();
  await expect(
    page.getByText("API request failed (400). Try again."),
  ).toBeVisible();
  expect(submitted).toBe(true);
  await expect(page.locator(".demo-result")).toHaveCount(0);
});

test("dashboard refreshes live metrics every 30 seconds", async ({ page }) => {
  let metricReads = 0;
  await page.route("http://127.0.0.1:3137/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/health")
      await route.fulfill({ json: { status: "ok", demo_mode: false } });
    else if (url.pathname === "/sites")
      await route.fulfill({
        json: [
          {
            id: "live-site",
            name: "Live Site",
            health: "ok",
            open_incidents: 0,
            uplinks: [],
          },
        ],
      });
    else if (url.pathname === "/incidents") await route.fulfill({ json: [] });
    else if (url.pathname === "/metrics") {
      metricReads += 1;
      await route.fulfill({
        json: [
          { series_key: "probe:1.1.1.1:rtt_ms", points: [], forecast: [] },
        ],
      });
    } else await route.fulfill({ status: 204, body: "" });
  });
  await page.addInitScript(() => {
    class QuietEventSource {
      onerror = null;
      onopen = null;
      addEventListener() {}
      removeEventListener() {}
      close() {}
    }
    Object.assign(window, { EventSource: QuietEventSource });
  });
  await page.clock.install({ time: new Date("2026-10-18T10:00:00Z") });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Live Site" })).toBeVisible();
  await expect.poll(() => metricReads).toBe(1);
  await page.clock.runFor(30000);
  await expect.poll(() => metricReads).toBe(2);
});
