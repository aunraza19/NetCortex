export type Health = "ok" | "degraded" | "down";
export type IncidentStatus =
  | "open"
  | "awaiting_approval"
  | "applying"
  | "verifying"
  | "resolved"
  | "rolled_back"
  | "rejected";
export type Cause =
  | "uplink_congestion"
  | "heavy_user"
  | "upstream_degradation"
  | "game_route_issue"
  | "wireless_interference"
  | "uplink_down"
  | "dns_slow";
export type Site = {
  id: string;
  name: string;
  location: string;
  subscribers: number;
  health: Health;
  utilization: number;
  latency: number;
  loss: number;
  uplink: string;
  backupUplink?: string;
};
export type Point = {
  time: string;
  actual: number | null;
  p10: number | null;
  p50: number | null;
  p90: number | null;
};
export type Incident = {
  id: string;
  siteId: string;
  siteName: string;
  cause: Cause;
  title: string;
  status: IncidentStatus;
  confidence: number;
  openedAt: string;
  summary: string;
  evidence: string[];
  template: string;
  fix: string[];
  rollback: string[];
  dryRun: "passed" | "failed" | "pending";
  dryRunMessage: string;
  simulatedOutcome?: "resolved" | "rolled_back";
  news?: { label: string; url: string };
  timeline: {
    at: string;
    label: string;
    detail: string;
    state: "done" | "active" | "pending";
  }[];
};
export type Scenario = Cause | "normal";
