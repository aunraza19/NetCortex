"use strict";
// NetCortex dashboard: plain DOM, fetch and EventSource. No framework, no build step.
// Text from the API is only ever set as text (never as HTML).

const STATUS = {
  open: "OPEN",
  awaiting_approval: "AWAITING APPROVAL",
  applying: "APPLYING",
  verifying: "VERIFYING",
  resolved: "RESOLVED",
  rolled_back: "ROLLED BACK",
  rejected: "REJECTED",
};
const HEALTH = { ok: "OK", degraded: "DEGRADED", down: "DOWN", unknown: "NO DATA" };
const EVENT_KINDS = ["incident.opened", "incident.updated", "fix.tested", "fix.applied"];
const SVG = "http://www.w3.org/2000/svg";

let selected = location.hash.slice(1) || null; // incident shown in the detail pane

// --- Helpers ---------------------------------------------------------------------------

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  setAttrs(el, attrs);
  el.append(...children.flat(2).filter((c) => c != null && c !== false));
  return el;
}

function svg(tag, attrs = {}, text) {
  const el = document.createElementNS(SVG, tag);
  setAttrs(el, attrs);
  if (text != null) el.textContent = text;
  return el;
}

function setAttrs(el, attrs) {
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

const words = (value) => String(value).replaceAll("_", " ");
const clock = (iso) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const when = (iso) =>
  `${new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" })} ${clock(iso)}`;
const statusLabel = (status) =>
  h("span", { class: status === "awaiting_approval" ? "label action" : "label" },
    STATUS[status] ?? status.toUpperCase());

// --- Sites -----------------------------------------------------------------------------

async function loadSites() {
  const sites = await api("/sites");
  document.getElementById("sites").replaceChildren(
    ...sites.map((site) =>
      h("li", {},
        h("span", {}, site.name),
        h("span", { class: "label" }, HEALTH[site.health] ?? site.health),
        h("span", { class: "mono muted" },
          site.worst_rtt_ms == null ? "-" : `${Math.round(site.worst_rtt_ms)} ms`),
      ),
    ),
  );
  const picker = document.getElementById("sim-site");
  const current = picker.value || "sim-tower";
  picker.replaceChildren(
    ...sites.map((site) => h("option", { value: site.id, selected: site.id === current }, site.name)),
  );
}

// --- Incident list ---------------------------------------------------------------------

async function loadIncidents() {
  const incidents = await api("/incidents");
  if (!selected && incidents.length) selected = incidents[0].id;
  const list = document.getElementById("incidents");
  if (!incidents.length) {
    list.replaceChildren(h("li", { class: "muted" }, "No incidents yet."));
    return;
  }
  list.replaceChildren(
    ...incidents.slice(0, 40).map((incident) =>
      h("li", {
          tabindex: 0,
          class: incident.id === selected ? "selected" : null,
          onclick: () => show(incident.id),
          onkeydown: (event) => event.key === "Enter" && show(incident.id),
        },
        h("div", { class: "row" }, statusLabel(incident.status),
          h("span", { class: "muted" }, when(incident.opened_at))),
        h("div", {}, `${words(incident.cause)} - ${incident.site_id}`),
      ),
    ),
  );
}

async function show(id) {
  selected = id;
  history.replaceState(null, "", `#${id}`);
  await Promise.all([loadIncidents(), loadDetail()]);
}

// --- Incident detail -------------------------------------------------------------------

async function loadDetail() {
  if (!selected) return;
  const { incident, fix_plan: plan, timeline } = await api(`/incidents/${selected}`);
  if (incident.id !== selected) return;
  const report = incident.report;
  document.getElementById("detail").replaceChildren(
    ...[
      h("div", { class: "head" },
        statusLabel(incident.status),
        h("span", {}, words(incident.cause)),
        h("span", { class: "muted" }, `${incident.site_id}, opened ${when(incident.opened_at)}`),
      ),
      report ? h("p", { class: "summary" }, report.summary)
             : h("p", { class: "note" }, "The agent is investigating."),
      decision(incident, plan),
      watching(incident, timeline),
      report && diagnosis(incident, report),
      h("div", { class: "chart", id: "chart" }),
      plan && fixPlan(plan),
      report && messages(report),
      events(timeline),
    ].filter(Boolean),
  );
  drawChart(incident);
}

function decision(incident, plan) {
  if (incident.status !== "awaiting_approval") return null;
  const note = h("p", { class: "note", role: "status" });
  const decide = (action) => async () => {
    buttons.forEach((button) => (button.disabled = true));
    try {
      await post(`/incidents/${incident.id}/${action}`, { decided_by: "dashboard" });
      note.textContent = action === "reject" ? "Rejected."
        : plan ? "Approved. Applying on the test router." : "Acknowledged.";
    } catch (error) {
      note.textContent = error.message;
      buttons.forEach((button) => (button.disabled = false));
    }
  };
  const buttons = [
    h("button", { onclick: decide("approve") }, plan ? "Approve fix" : "Acknowledge"),
    h("button", { class: "secondary", onclick: decide("reject") }, "Reject"),
  ];
  return h("div", {}, h("div", { class: "actions" }, buttons), note);
}

function watching(incident, timeline) {
  if (incident.status !== "verifying") return null;
  const due = timeline.findLast((event) => event.payload.verdict_at)?.payload.verdict_at;
  const at = due && new Date(due).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return h("p", { class: "watch" }, at ? `Watching results, verdict at ${at}.` : "Watching results.");
}

function diagnosis(incident, report) {
  const detection = incident.detection;
  const params = Object.entries(report.template_params)
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : value}`)
    .join("  ");
  return h("div", {},
    h("h3", {}, "Diagnosis"),
    h("dl", { class: "facts" },
      h("dt", {}, "Likely cause"),
      h("dd", {}, `${words(report.likely_cause)} (confidence ${report.confidence.toFixed(2)})`),
      h("dt", {}, "Detector"),
      h("dd", {}, `${words(detection.cause_guess)}, anomaly score ${detection.score.toFixed(2)}`),
      h("dt", {}, "Proposed fix"),
      h("dd", { class: "mono" },
        report.template_id === "none" ? "none (notify only)" : `${report.template_id}  ${params}`),
      report.upstream_check?.available && [
        h("dt", {}, "Upstream"), h("dd", {}, report.upstream_check.summary),
      ],
    ),
    report.evidence.length > 0 && [
      h("h3", {}, "Evidence"),
      h("ul", { class: "plain" }, report.evidence.map((line) => h("li", {}, line))),
    ],
  );
}

function fixPlan(plan) {
  const last = plan.dry_run_log.trim().split("\n").at(-1) ?? "";
  const reason = last.startsWith("Result: FAILED: ") ? last.slice("Result: FAILED: ".length) : "";
  const result = plan.dry_run_ok == null ? "TESTING" : plan.dry_run_ok ? "PASSED" : "FAILED";
  return h("div", {},
    h("h3", {}, "Router commands"),
    h("pre", {}, plan.commands),
    h("h3", {}, "Rollback"),
    h("pre", {}, plan.rollback),
    h("h3", {}, "Dry run on the test router"),
    h("p", {}, h("span", { class: "label" }, result), reason && h("span", { class: "muted" }, `  ${reason}`)),
    h("details", {}, h("summary", {}, "Full dry-run log"), h("pre", {}, plan.dry_run_log)),
  );
}

function messages(report) {
  return h("div", {},
    h("h3", {}, "Customer message"),
    h("p", {}, report.customer_message_en),
    h("p", { class: "ur", lang: "ur", dir: "rtl" }, report.customer_message_ur),
  );
}

function events(timeline) {
  if (!timeline.length) return null;
  const start = new Date(timeline[0].time);
  const what = (event) => {
    const p = event.payload;
    if (event.kind === "fix.tested") return p.dry_run_ok ? "DRY RUN PASSED" : "DRY RUN FAILED";
    if (event.kind === "fix.applied") return "APPLIED";
    return STATUS[p.status] ?? event.kind;
  };
  return h("div", {},
    h("h3", {}, "Timeline"),
    h("ol", { class: "timeline" },
      timeline.map((event) =>
        h("li", {},
          h("span", { class: "mono muted" }, `+${Math.round((new Date(event.time) - start) / 1000)}s`),
          h("span", { class: "label" }, what(event)),
          h("span", { class: "note-cell muted" }, event.payload.note || event.payload.reason || ""),
        ),
      ),
    ),
  );
}

// --- Key metric chart (inline SVG) ----------------------------------------------------

async function drawChart(incident) {
  const key = incident.detection.series[0]?.series_key;
  if (!key) return;
  const opened = new Date(incident.opened_at);
  const from = new Date(opened.getTime() - 15 * 60e3);
  const to = incident.closed_at ? new Date(new Date(incident.closed_at).getTime() + 5 * 60e3) : new Date();
  const query = new URLSearchParams({
    site_id: incident.site_id, series: key, from: from.toISOString(), to: to.toISOString(),
  });
  const [series] = await api(`/metrics?${query}`);
  const box = document.getElementById("chart");
  if (!box || incident.id !== selected || !series) return;

  const W = 640, H = 170, left = 40, right = 8, top = 10, bottom = 22;
  const points = series.points.filter((p) => p.value != null);
  const peak = Math.max(1, ...points.map((p) => p.value));
  const x = (t) => left + ((new Date(t) - from) / (to - from)) * (W - left - right);
  const y = (v) => top + (1 - v / peak) * (H - top - bottom);

  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": key });
  chart.append(
    svg("polyline", { class: "line", points: points.map((p) => `${x(p.time)},${y(p.value)}`).join(" ") }),
    svg("line", { class: "mark", x1: x(opened), x2: x(opened), y1: top, y2: H - bottom }),
    svg("text", { x: x(opened) + 4, y: H - bottom - 4 }, "opened"),
    svg("text", { x: 4, y: top + 10 }, Math.round(peak)),
    svg("text", { x: 4, y: H - bottom }, "0"),
    svg("text", { x: left, y: H - 6 }, clock(from)),
    svg("text", { x: W - right, y: H - 6, "text-anchor": "end" }, clock(to)),
  );
  box.replaceChildren(h("h3", {}, key), chart);
}

// --- Simulate --------------------------------------------------------------------------

document.getElementById("simulate").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const note = document.getElementById("sim-note");
  const button = event.target.querySelector("button");
  button.disabled = true;
  note.textContent = "Injecting.";
  try {
    const label = await post("/demo/scenarios", {
      site_id: form.get("site_id"),
      scenario_type: form.get("scenario_type"),
      duration_min: Number(form.get("duration_min")),
    });
    note.textContent = `Injected ${words(label.scenario_type)} on ${label.site_id} until ` +
      `${clock(label.end_at)}. The monitor checks every minute.`;
  } catch (error) {
    note.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

// --- Live updates ----------------------------------------------------------------------

let refreshTimer;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => Promise.all([loadIncidents(), loadDetail()]).catch(console.error), 300);
}

function connect() {
  const live = document.getElementById("live");
  const source = new EventSource("/stream");
  source.onopen = () => (live.textContent = "LIVE");
  source.onerror = () => (live.textContent = "RECONNECTING");
  for (const kind of EVENT_KINDS) {
    source.addEventListener(kind, (event) => {
      const payload = JSON.parse(event.data);
      if (kind === "incident.opened" && payload.incident_id) selected = payload.incident_id;
      refreshSoon();
    });
  }
}

async function start() {
  try {
    await Promise.all([loadSites(), loadIncidents()]);
    await loadDetail();
  } catch (error) {
    document.getElementById("detail").replaceChildren(h("p", { class: "note" }, error.message));
  }
  connect();
  setInterval(() => loadSites().catch(console.error), 15000);
}

start();
