"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Clock3,
  Globe2,
  MoreHorizontal,
  RadioTower,
  Signal,
  Wifi,
} from "lucide-react";
import { apiMode, transport } from "@/lib/transport";
import { makeSeries, sites as seedSites } from "@/lib/fixtures";
import type { Incident, Point, Site } from "@/lib/types";
import { LatencyChart } from "./latency-chart";
import { SectionTitle, Status } from "./ui";
function Pst({ date }: { date: string }) {
  const [value, setValue] = useState("—");
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        setValue(
          new Intl.DateTimeFormat("en-PK", {
            timeZone: "Asia/Karachi",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }).format(new Date(date)) + " PKT",
        ),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [date]);
  return <>{value}</>;
}
export function Dashboard() {
  const [sites, setSites] = useState<Site[]>(
      apiMode === "mock" ? seedSites : [],
    ),
    [incidents, setIncidents] = useState<Incident[]>([]),
    [series, setSeries] = useState<Point[]>(
      apiMode === "mock" ? makeSeries() : [],
    ),
    [error, setError] = useState("");
  const refresh = async () => {
    try {
      const [siteRows, i] = await Promise.all([
        transport.sites(),
        transport.incidents(),
      ]);
      const metrics = siteRows.length
        ? await transport.metrics(siteRows[0].id)
        : [];
      setSites(siteRows);
      setIncidents(i);
      setSeries(metrics);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load network data.");
    }
  };
  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    const interval = window.setInterval(() => void refresh(), 30000);
    const unsubscribe = transport.subscribe(
      () => void refresh(),
      () => void refresh(),
    );
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
      unsubscribe();
    };
  }, []);
  const urgent = incidents.filter((i) =>
    ["open", "awaiting_approval", "applying", "verifying"].includes(i.status),
  );
  return (
    <div className="page">
      <SectionTitle eyebrow="Network operations" title="Network overview">
        <div className="updated-label">
          <span className="pulse" /> Refreshing every 30 seconds{" "}
          <MoreHorizontal size={17} />
        </div>
      </SectionTitle>
      {error && (
        <div className="inline-error">
          {error} <button onClick={() => void refresh()}>Retry</button>
        </div>
      )}
      <div className="summary-strip">
        <div>
          <span className="summary-icon teal">
            <RadioTower size={17} />
          </span>
          <div>
            <small>Sites monitored</small>
            <strong>
              {sites.length} <em>connected</em>
            </strong>
          </div>
        </div>
        <div>
          <span className="summary-icon amber">
            <Signal size={17} />
          </span>
          <div>
            <small>Active incidents</small>
            <strong>
              {urgent.length} <em>need attention</em>
            </strong>
          </div>
        </div>
        <div>
          <span className="summary-icon blue">
            <Globe2 size={17} />
          </span>
          <div>
            <small>Network availability</small>
            <strong>
              {apiMode === "mock" ? "99.92" : "—"}
              <em>
                {apiMode === "mock" ? "% · replay sample" : "API field pending"}
              </em>
            </strong>
          </div>
        </div>
        <div>
          <span className="summary-icon violet">
            <Clock3 size={17} />
          </span>
          <div>
            <small>Avg. response time</small>
            <strong>
              {apiMode === "mock" ? "4.2" : "—"}{" "}
              <em>
                {apiMode === "mock"
                  ? "min · replay sample"
                  : "API field pending"}
              </em>
            </strong>
          </div>
        </div>
      </div>
      <div className="section-heading">
        <div>
          <h2>Site health</h2>
          <p>Current service conditions across your network</p>
        </div>
        <Link className="text-link" href="/incidents">
          All incidents <ArrowRight size={15} />
        </Link>
      </div>
      <div className="site-grid">
        {sites.map((s) => (
          <Link
            href={`/incidents?site=${s.id}`}
            className="panel site-card"
            key={s.id}
          >
            <div className="site-top">
              <div>
                <span className={`health-indicator health-${s.health}`} />
                <span className="site-health-label">
                  {s.health === "ok"
                    ? "Operational"
                    : s.health === "degraded"
                      ? "Degraded"
                      : s.health === "down"
                        ? "Down"
                        : "Unknown"}
                </span>
              </div>
              <span className="more-button" aria-hidden="true">
                <MoreHorizontal size={17} />
              </span>
            </div>
            <h3>{s.name}</h3>
            <p className="site-location">
              {s.location === "—" ? "—" : s.location} <span>·</span>{" "}
              {s.subscribers ?? "—"} subscribers
            </p>
            <div className="site-metrics">
              <div>
                <small>UPLINK USAGE</small>
                <strong>
                  {s.utilization ?? "—"}
                  {s.utilization !== null && <i>%</i>}
                </strong>
                <div className="meter">
                  <span
                    style={{ width: `${s.utilization ?? 0}%` }}
                    className={`${s.health === "down" ? "meter-red" : ""} ${s.utilization === null ? "meter-empty" : ""}`}
                  />
                </div>
              </div>
              <div>
                <small>WORST LATENCY</small>
                <strong>
                  {s.latency ?? "—"}
                  {s.latency !== null && <i>ms</i>}
                </strong>
              </div>
            </div>
            <div className="site-footer">
              <span>
                <Wifi size={13} />
                {s.uplink}
                {s.backupUplink && <small> · Backup {s.backupUplink}</small>}
              </span>
              <ArrowRight size={15} />
            </div>
          </Link>
        ))}
        {sites.length === 0 && !error && (
          <div className="panel empty-state">
            Waiting for site data from the API.
          </div>
        )}
      </div>
      <div className="content-grid">
        <section className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <h2>Latency forecast</h2>
              <p>
                {sites[0]?.name ?? "Selected site"} · external probe · past 24
                hours, Pakistan time
              </p>
            </div>
            <span className="chart-units">MILLISECONDS</span>
          </div>
          <div className="chart-legend">
            <span>
              <i className="legend-actual" /> Actual
            </span>
            <span>
              <i className="legend-forecast" /> Expected
            </span>
            <span>
              <i className="legend-band" /> Forecast range
            </span>
          </div>
          {series.length > 0 ? (
            <LatencyChart data={series} />
          ) : (
            <div className="empty-state chart-empty">
              No latency forecast data is available yet.
            </div>
          )}
          <div className="chart-foot">
            <span>
              FORECAST DATA{" "}
              <b>{apiMode === "mock" ? "Replay fixture" : "API response"}</b>
            </span>
            <span>
              UPDATED{" "}
              <b>
                <Pst date={new Date().toISOString()} />
              </b>
            </span>
          </div>
        </section>
        <section className="panel incident-panel">
          <div className="panel-heading">
            <div>
              <h2>Needs attention</h2>
              <p>Incidents that may need a decision</p>
            </div>
            <span className="count-badge">{urgent.length}</span>
          </div>
          <div className="compact-list">
            {urgent.slice(0, 3).map((i) => (
              <Link
                href={`/incidents/${i.id}`}
                className="compact-incident"
                key={i.id}
              >
                <span
                  className={`incident-icon ${i.cause === "uplink_down" ? "incident-danger" : ""}`}
                >
                  {i.cause === "uplink_down" ? (
                    <ArrowDownRight size={16} />
                  ) : (
                    <ArrowUpRight size={16} />
                  )}
                </span>
                <span className="compact-copy">
                  <strong>{i.title}</strong>
                  <small>
                    {i.siteName} <i>·</i> <Pst date={i.openedAt} /> <i>·</i>{" "}
                    {i.confidence === null
                      ? "Confidence unavailable"
                      : `${Math.round(i.confidence * 100)}% confidence`}
                  </small>
                </span>
                <Status status={i.status} />
              </Link>
            ))}
            {urgent.length === 0 && (
              <div className="empty-state">
                {apiMode === "mock"
                  ? "No active incidents in the replay sample."
                  : "No incident data available yet."}
              </div>
            )}
          </div>
          <Link className="panel-link" href="/incidents">
            View incident history <ArrowRight size={14} />
          </Link>
        </section>
      </div>
    </div>
  );
}
