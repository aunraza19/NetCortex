import type { Incident, Point, Scenario, Site } from "./types";
// Subscriber counts and link capacities mirror data/sites.yaml. Health, utilization, latency, and loss below are illustrative replay samples.
export const sites: Site[] = [
  {
    id: "north-tower",
    name: "North Tower",
    location: "Rawalpindi",
    subscribers: 120,
    health: "degraded",
    utilization: 91,
    latency: 64,
    loss: 1.2,
    uplink: "ether1 · 180 Mbps",
    backupUplink: "ether2 · 80 Mbps",
  },
  {
    id: "market-cafe",
    name: "Market Cafe",
    location: "Lahore",
    subscribers: 48,
    health: "ok",
    utilization: 48,
    latency: 22,
    loss: 0,
    uplink: "ether1 · 100 Mbps",
  },
  {
    id: "east-relay",
    name: "East Relay",
    location: "Islamabad",
    subscribers: 165,
    health: "down",
    utilization: 18,
    latency: 184,
    loss: 32,
    uplink: "ether1 · 250 Mbps",
    backupUplink: "ether2 · 100 Mbps",
  },
];
export const scenarios: Scenario[] = [
  "uplink_congestion",
  "heavy_user",
  "upstream_degradation",
  "game_route_issue",
  "wireless_interference",
  "uplink_down",
  "dns_slow",
  "normal",
];
const now = Date.now();
export const initialIncidents: Incident[] = [
  {
    id: "INC-2084",
    siteId: "north-tower",
    siteName: "North Tower",
    cause: "uplink_congestion",
    title: "Uplink congestion on ether1",
    status: "awaiting_approval",
    confidence: 0.94,
    openedAt: new Date(now - 12 * 60000).toISOString(),
    summary:
      "Latency is rising across external targets while ether1 remains above 90% utilization. The gateway is healthy, which points to a saturated uplink rather than a local radio issue.",
    evidence: [
      "ether1 at 91% utilization for 8 minutes",
      "1.1.1.1 latency reached 64 ms (baseline 24 ms)",
      "Gateway latency remains steady at 2 ms",
    ],
    template: "priority_queue",
    fix: [
      "/queue tree add name=priority-traffic parent=global packet-mark=priority",
      "/queue tree set priority-traffic priority=1 limit-at=20M max-limit=35M",
    ],
    rollback: ['/queue tree remove [find name="priority-traffic"]'],
    dryRun: "passed",
    dryRunMessage:
      "Demo fixture: router test passed in a recorded sample; no CHR was contacted.",
    news: {
      label:
        "Demo fixture: placeholder upstream result; no live check was made.",
      url: "https://status.example.net",
    },
    timeline: [
      {
        at: new Date(now - 12 * 60000).toISOString(),
        label: "Incident detected",
        detail: "Latency exceeded forecast range for 3 consecutive samples.",
        state: "done",
      },
      {
        at: new Date(now - 10 * 60000).toISOString(),
        label: "Investigation complete",
        detail: "Agent found uplink saturation across all external targets.",
        state: "done",
      },
      {
        at: new Date(now - 8 * 60000).toISOString(),
        label: "Router test passed",
        detail: "Recorded fixture result; no virtual router was contacted.",
        state: "done",
      },
      {
        at: new Date(now - 7 * 60000).toISOString(),
        label: "Waiting for your decision",
        detail: "Review the tested change before it is applied.",
        state: "active",
      },
    ],
  },
  {
    id: "INC-2083",
    siteId: "east-relay",
    siteName: "East Relay",
    cause: "uplink_down",
    title: "Primary uplink unreachable",
    status: "open",
    confidence: 0.99,
    openedAt: new Date(now - 28 * 60000).toISOString(),
    summary:
      "The primary uplink has stopped responding. Loss is confirmed across external targets.",
    evidence: [
      "Primary uplink loss at 100% for 6 minutes",
      "Configured backup uplink detected",
    ],
    template: "failover_route",
    fix: ['/ip route set [find comment="primary"] distance=2'],
    rollback: ['/ip route set [find comment="primary"] distance=1'],
    dryRun: "failed",
    dryRunMessage:
      "Demo fixture: router test failed in a recorded sample; no CHR was contacted.",
    timeline: [
      {
        at: new Date(now - 28 * 60000).toISOString(),
        label: "Incident detected",
        detail: "No response from primary uplink.",
        state: "done",
      },
      {
        at: new Date(now - 27 * 60000).toISOString(),
        label: "Router test failed",
        detail: "Backup gateway could not be reached in CHR.",
        state: "active",
      },
    ],
  },
  {
    id: "INC-2082",
    siteId: "market-cafe",
    siteName: "Market Cafe",
    cause: "upstream_degradation",
    title: "Upstream provider latency",
    status: "resolved",
    confidence: 0.82,
    openedAt: new Date(now - 95 * 60000).toISOString(),
    summary:
      "External targets showed elevated latency while local utilization stayed within normal range. No router change was required.",
    evidence: [
      "External latency elevated on 4 targets",
      "Uplink utilization at 48%",
    ],
    template: "none",
    fix: [],
    rollback: [],
    dryRun: "pending",
    dryRunMessage: "No router change proposed for this incident.",
    news: {
      label:
        "Demo fixture: placeholder provider result; no live outage check was made.",
      url: "https://status.example.net",
    },
    timeline: [
      {
        at: new Date(now - 95 * 60000).toISOString(),
        label: "Incident detected",
        detail: "External latency rose.",
        state: "done",
      },
      {
        at: new Date(now - 83 * 60000).toISOString(),
        label: "Resolved",
        detail: "Provider service recovered.",
        state: "done",
      },
    ],
  },
];
export function makeSeries(): Point[] {
  return Array.from({ length: 24 }, (_, i) => {
    const base = 27 + Math.sin(i / 3) * 4 + (i > 16 ? (i - 16) * 5 : 0);
    return {
      time: `${String(i).padStart(2, "0")}:00`,
      actual: Math.round(base + Math.sin(i * 2.2) * 5),
      p10: Math.round(base - 7),
      p50: Math.round(base),
      p90: Math.round(base + 8),
    };
  });
}
