import {
  initialIncidents,
  makeSeries,
  sites as fixtureSites,
} from "./fixtures";
import type { Incident, IncidentStatus, Scenario, Site } from "./types";

export interface InjectionResult {
  incident?: Incident;
  message: string;
}

export interface Transport {
  sites(): Promise<Site[]>;
  incidents(status?: string, siteId?: string): Promise<Incident[]>;
  incident(id: string): Promise<Incident>;
  metrics(siteId: string): Promise<ReturnType<typeof makeSeries>>;
  voice(id: string): Promise<string>;
  inject(
    siteId: string,
    scenario: Scenario,
    duration: number,
  ): Promise<InjectionResult>;
  decide(
    id: string,
    decision: "approve" | "reject",
    onUpdate?: (incident: Incident) => void,
  ): Promise<Incident>;
  subscribe(
    onEvent: (event: MessageEvent) => void,
    onReconnect: () => void,
  ): () => void;
}

const mode = process.env.NEXT_PUBLIC_API_MODE ?? "mock";
const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 7000);
  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok)
      throw new Error(`API request failed (${response.status}). Try again.`);
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error) throw error;
    throw new Error(
      "The API could not be reached. Check the connection and try again.",
    );
  } finally {
    clearTimeout(timer);
  }
}

async function requestAck(path: string, init?: RequestInit): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 7000);
  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok)
      throw new Error(`API request failed (${response.status}). Try again.`);
  } catch (error) {
    if (error instanceof Error) throw error;
    throw new Error(
      "The API could not be reached. Check the connection and try again.",
    );
  } finally {
    clearTimeout(timer);
  }
}

let mockIncidents = initialIncidents.map((incident) => ({ ...incident }));
const pause = (ms = 100) => new Promise((resolve) => setTimeout(resolve, ms));

function update(
  id: string,
  status: IncidentStatus,
  label: string,
  detail = "Recorded by the local replay.",
) {
  mockIncidents = mockIncidents.map((incident) =>
    incident.id === id
      ? {
          ...incident,
          status,
          timeline: [
            ...incident.timeline,
            { at: new Date().toISOString(), label, detail, state: "done" },
          ],
        }
      : incident,
  );
}

function currentSites(): Site[] {
  return fixtureSites.map((site) => {
    const active = mockIncidents.filter(
      (incident) =>
        incident.siteId === site.id &&
        ["open", "awaiting_approval", "applying", "verifying"].includes(
          incident.status,
        ),
    );
    const severe = active.some((incident) => incident.cause === "uplink_down");
    if (!active.length) return site;
    return { ...site, health: severe ? "down" : "degraded" };
  });
}

function newMockIncident(
  site: Site,
  scenario: Scenario,
  duration: number,
): Incident {
  const noFix = [
    "upstream_degradation",
    "game_route_issue",
    "wireless_interference",
  ].includes(scenario);
  const noBackup = scenario === "uplink_down" && !site.backupUplink;
  const adviceOnly = noFix || noBackup;
  const templates: Partial<Record<Scenario, string>> = {
    uplink_congestion: "priority_queue",
    heavy_user: "queue_limit",
    uplink_down: "failover_route",
    dns_slow: "dns_servers",
  };
  const commands: Partial<Record<Scenario, string[]>> = {
    uplink_congestion: [
      "/queue tree add name=demo-priority parent=global packet-mark=priority priority=1",
    ],
    heavy_user: [
      "/queue simple add name=demo-user target=192.0.2.8/32 max-limit=10M/10M",
    ],
    uplink_down: ['/ip route set [find comment="primary"] distance=2'],
    dns_slow: ["/ip dns set servers=1.1.1.1,8.8.8.8"],
  };
  const rollback: Partial<Record<Scenario, string[]>> = {
    uplink_congestion: ['/queue tree remove [find name="demo-priority"]'],
    heavy_user: ['/queue simple remove [find name="demo-user"]'],
    uplink_down: ['/ip route set [find comment="primary"] distance=1'],
    dns_slow: ["/ip dns set servers=192.0.2.53"],
  };
  const timestamp = new Date().toISOString();
  const id = `INC-${2085 + mockIncidents.length}`;
  return {
    ...mockIncidents[0],
    id,
    siteId: site.id,
    siteName: site.name,
    cause: scenario === "normal" ? "upstream_degradation" : scenario,
    title:
      scenario === "normal"
        ? `Normal traffic at ${site.name}`
        : `${scenario.replaceAll("_", " ")} at ${site.name}`,
    status: "awaiting_approval",
    openedAt: timestamp,
    summary: noBackup
      ? `The primary uplink is down at ${site.name}, which has no configured backup uplink. The replay provides notify-only guidance; no route change is proposed.`
      : `A ${scenario.replaceAll("_", " ")} replay was injected at ${site.name}. Review the recorded evidence${adviceOnly ? " and service guidance" : " and router test"} before deciding.`,
    template: adviceOnly ? "none" : (templates[scenario] ?? "none"),
    fix: adviceOnly ? [] : (commands[scenario] ?? []),
    rollback: adviceOnly ? [] : (rollback[scenario] ?? []),
    dryRun: adviceOnly ? "pending" : "passed",
    dryRunMessage: noBackup
      ? "No backup uplink is configured. Notify-only guidance; no router change or CHR test is available."
      : adviceOnly
        ? "No router change proposed for this scenario."
        : "CHR test simulated · replay fixture only · no router command was sent",
    simulatedOutcome:
      scenario === "uplink_down" && !noBackup ? "rolled_back" : "resolved",
    evidence: noBackup
      ? [
          `Primary uplink down for ${duration} minutes`,
          "No backup uplink is configured for this site",
        ]
      : [
          `${scenario.replaceAll("_", " ")} signal replayed for ${duration} minutes`,
          `Sample evidence recorded at ${site.name}`,
        ],
    timeline: [
      {
        at: timestamp,
        label: "Demo incident replayed",
        detail: "Scenario and evidence generated from the local fixture.",
        state: "done",
      },
      ...(!adviceOnly
        ? [
            {
              at: timestamp,
              label: "Router test passed",
              detail: "Fixture result only. No CHR was contacted.",
              state: "done" as const,
            },
          ]
        : []),
      {
        at: timestamp,
        label: "Waiting for your decision",
        detail: "Approval advances the local simulation only.",
        state: "active",
      },
    ],
  };
}

export const transport: Transport = {
  async sites() {
    return mode === "live"
      ? request<Site[]>("/sites")
      : (await pause(), currentSites());
  },
  async incidents(status, siteId) {
    const list =
      mode === "live"
        ? await request<Incident[]>(
            `/incidents${status ? `?status=${encodeURIComponent(status)}` : ""}`,
          )
        : (await pause(), mockIncidents);
    return list
      .filter(
        (incident) =>
          (!status || incident.status === status) &&
          (!siteId || incident.siteId === siteId),
      )
      .sort((a, b) => Date.parse(b.openedAt) - Date.parse(a.openedAt));
  },
  async incident(id) {
    const result =
      mode === "live"
        ? await request<Incident>(`/incidents/${encodeURIComponent(id)}`)
        : (await pause(), mockIncidents.find((incident) => incident.id === id));
    if (!result)
      throw new Error("Incident not found. Refresh the list and try again.");
    return result;
  },
  async metrics(siteId) {
    const to = new Date();
    const from = new Date(to.getTime() - 24 * 60 * 60 * 1000);
    const series = `probe:1.1.1.1:rtt_ms`;
    const query = new URLSearchParams({
      site_id: siteId,
      series,
      from: from.toISOString(),
      to: to.toISOString(),
    });
    return mode === "live"
      ? request(`/metrics?${query}`)
      : (await pause(), makeSeries());
  },
  async voice(id) {
    if (mode === "mock")
      throw new Error(
        "Voice alert unavailable in replay fixtures. No audio has been generated.",
      );
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 7000);
    try {
      const response = await fetch(
        `${base}/incidents/${encodeURIComponent(id)}/voice`,
        { signal: controller.signal },
      );
      if (!response.ok)
        throw new Error(
          response.status === 404
            ? "No voice alert is available for this incident."
            : `Voice alert request failed (${response.status}).`,
        );
      return URL.createObjectURL(await response.blob());
    } catch (error) {
      if (error instanceof Error) throw error;
      throw new Error("Voice alert could not be reached.");
    } finally {
      clearTimeout(timer);
    }
  },
  async inject(siteId, scenario, duration) {
    if (mode === "live") {
      await requestAck("/demo/scenarios", {
        method: "POST",
        body: JSON.stringify({
          site_id: siteId,
          scenario_type: scenario,
          duration_min: duration,
        }),
      });
      return {
        message:
          "Diagnosis queued. Refresh the incident list shortly to review results.",
      };
    }
    await pause(250);
    const site = currentSites().find((item) => item.id === siteId);
    if (!site) throw new Error("Choose a site before replaying a scenario.");
    if (scenario === "normal")
      return {
        message:
          "Normal traffic replayed. No incident or router change was created.",
      };
    const incident = newMockIncident(site, scenario, duration);
    mockIncidents = [incident, ...mockIncidents];
    return {
      incident,
      message:
        incident.template === "none"
          ? "Scenario replayed. It provides guidance only; no router change is proposed."
          : "Scenario replayed. A reviewable incident is ready.",
    };
  },
  async decide(id, decision, onUpdate) {
    if (mode === "live") {
      await requestAck(`/incidents/${encodeURIComponent(id)}/${decision}`, {
        method: "POST",
        body: "{}",
      });
      const authoritative = await this.incident(id);
      onUpdate?.(authoritative);
      return authoritative;
    }
    await pause(250);
    const current = mockIncidents.find((incident) => incident.id === id);
    if (!current) throw new Error("Incident not found.");
    if (
      (decision === "approve" && current.status !== "awaiting_approval") ||
      (decision === "reject" &&
        !["awaiting_approval", "open"].includes(current.status))
    ) {
      throw new Error(
        "This incident is no longer available for that decision.",
      );
    }
    if (decision === "reject") {
      update(id, "rejected", "Change rejected");
      return this.incident(id);
    }
    if (
      current.template === "none" ||
      current.dryRun !== "passed" ||
      !current.fix.length
    ) {
      throw new Error("This incident is not eligible for approval.");
    }
    update(
      id,
      "applying",
      "Applying simulated change",
      "Local fixture only; no router command was sent.",
    );
    onUpdate?.(await this.incident(id));
    await pause(400);
    update(
      id,
      "verifying",
      "Verifying simulated change",
      "Local fixture only; outcome is illustrative.",
    );
    onUpdate?.(await this.incident(id));
    await pause(500);
    const outcome = current.simulatedOutcome ?? "resolved";
    update(
      id,
      outcome,
      outcome === "rolled_back"
        ? "Simulated check failed; rollback completed"
        : "Simulation resolved",
      "Simulated replay outcome; no router command was sent.",
    );
    return this.incident(id);
  },
  subscribe(onEvent, onReconnect) {
    if (mode === "live") {
      const source = new EventSource(`${base}/stream`);
      const seen = new Set<string>();
      const events = [
        "metric",
        "incident.opened",
        "incident.updated",
        "fix.tested",
        "fix.applied",
      ];
      const listeners = events.map((name) => {
        const listener = (raw: Event) => {
          const event = raw as MessageEvent;
          const key = event.lastEventId
            ? `${event.type}:${event.lastEventId}`
            : "";
          if (key && seen.has(key)) return;
          if (key) {
            seen.add(key);
            if (seen.size > 500)
              seen.delete(seen.values().next().value as string);
          }
          onEvent(event);
        };
        source.addEventListener(name, listener);
        return [name, listener] as const;
      });
      let opened = false;
      source.onopen = () => {
        if (opened) onReconnect();
        opened = true;
      };
      source.onerror = () => onReconnect();
      return () => {
        listeners.forEach(([name, listener]) =>
          source.removeEventListener(name, listener),
        );
        source.close();
      };
    }
    const timer = setTimeout(onReconnect, 45000);
    return () => clearTimeout(timer);
  },
};

export const apiMode = mode;
