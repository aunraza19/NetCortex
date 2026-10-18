"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Play, RadioTower } from "lucide-react";
import { scenarios, sites as fixtureSites } from "@/lib/fixtures";
import { apiMode, transport } from "@/lib/transport";
import type { Incident, Scenario } from "@/lib/types";
import { ErrorBox, SectionTitle } from "./ui";

const labels: Record<Scenario, string> = {
  uplink_congestion: "Uplink congestion",
  heavy_user: "Heavy user",
  upstream_degradation: "Upstream degradation",
  game_route_issue: "Game route issue",
  wireless_interference: "Wireless interference",
  uplink_down: "Uplink down",
  dns_slow: "Slow DNS",
  normal: "Normal traffic",
};

export function DemoPanel() {
  const [site, setSite] = useState("north-tower");
  const [scenario, setScenario] = useState<Scenario>("uplink_congestion");
  const [duration, setDuration] = useState(10);
  const [busy, setBusy] = useState(false);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [sites, setSites] = useState(apiMode === "mock" ? fixtureSites : []);
  const [apiReplay, setApiReplay] = useState(false);
  const [modeReady, setModeReady] = useState(apiMode === "mock");
  useEffect(() => {
    if (apiMode !== "live") return;
    void Promise.all([transport.health(), transport.sites()])
      .then(([health, availableSites]) => {
        setApiReplay(!!health?.demo_mode);
        setModeReady(!!health);
        setSites(availableSites);
        if (
          !availableSites.some((item) => item.id === site) &&
          availableSites[0]
        )
          setSite(availableSites[0].id);
      })
      .catch((cause) =>
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not load network sites.",
        ),
      );
  }, [site]);

  const run = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    setIncident(null);
    try {
      const result = await transport.inject(site, scenario, duration);
      setIncident(result.incident ?? null);
      setMessage(result.message);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The scenario could not be replayed.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <SectionTitle eyebrow="Guided walkthrough" title="Demo panel">
        <span className="demo-badge">
          <span />
          {apiMode === "mock"
            ? "Demo: replayed data"
            : !modeReady
              ? error
                ? "API status unavailable"
                : "Checking API mode"
              : apiReplay
                ? "Demo: replayed data"
                : "Live network data"}
        </span>
      </SectionTitle>
      <div className="demo-layout">
        <section className="panel demo-form">
          <div className="demo-intro">
            <span className="demo-icon">
              <RadioTower size={19} />
            </span>
            <div>
              <h2>Replay a network scenario</h2>
              <p>
                {apiReplay
                  ? "Saved API replay is read only. Scenarios cannot be injected into replay data."
                  : !modeReady
                    ? "Scenario actions remain disabled until the API mode is confirmed."
                    : "Choose a site and situation to see how NetCortex investigates an incident."}
              </p>
            </div>
          </div>
          <label className="form-field">
            <span>NETWORK SITE</span>
            <select
              aria-label="Network site"
              value={site}
              onChange={(event) => setSite(event.target.value)}
            >
              {sites.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.location}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span>SCENARIO</span>
            <select
              aria-label="Scenario"
              value={scenario}
              onChange={(event) => setScenario(event.target.value as Scenario)}
            >
              {scenarios.map((item) => (
                <option value={item} key={item}>
                  {labels[item]}
                </option>
              ))}
            </select>
            <small>
              Some scenarios provide advice only and do not include router
              commands.
            </small>
          </label>
          <label className="form-field">
            <span>SCENARIO LENGTH</span>
            <select
              aria-label="Scenario length"
              value={duration}
              onChange={(event) => setDuration(Number(event.target.value))}
            >
              <option value={5}>5 minutes</option>
              <option value={10}>10 minutes</option>
              <option value={15}>15 minutes</option>
              <option value={30}>30 minutes</option>
            </select>
          </label>
          <div className="demo-safety">
            <CheckCircle2 size={15} />
            <span>
              {apiMode === "mock"
                ? "This browser demo uses local replay data; actions stay in the simulation."
                : !modeReady
                  ? error
                    ? "API mode could not be confirmed. Scenario actions remain disabled."
                    : "Checking API mode. Scenario actions remain disabled until the service mode is known."
                  : apiReplay
                    ? "This is saved API replay data. Scenario injection is disabled; saved approvals update the replay snapshot only."
                    : "Scenario injection writes to the simulator. Approving a proposal may run its commands against the connected CHR."}
            </span>
          </div>
          {error && <ErrorBox message={error} />}
          <button
            className="button button-primary inject-button"
            disabled={busy || !modeReady || apiReplay || sites.length === 0}
            onClick={() => void run()}
          >
            <Play size={15} fill="currentColor" />
            {busy ? "Replaying scenario…" : "Replay scenario"}
          </button>
        </section>
        <aside className="demo-aside">
          <div className="demo-step">
            <span>01</span>
            <div>
              <strong>Choose a scenario</strong>
              <p>Replay a known network pattern with sample evidence.</p>
            </div>
          </div>
          <div className="demo-step">
            <span>02</span>
            <div>
              <strong>Review the incident</strong>
              <p>See the findings, router check and rollback plan.</p>
            </div>
          </div>
          <div className="demo-step">
            <span>03</span>
            <div>
              <strong>Make a decision</strong>
              <p>Approve or reject to complete the simulated response.</p>
            </div>
          </div>
        </aside>
      </div>
      {message && (
        <div className="panel demo-result">
          <CheckCircle2 size={18} />
          <span>{message}</span>
          {incident ? (
            <Link href={`/incidents/${incident.id}`}>
              Open incident <ArrowRight size={14} />
            </Link>
          ) : apiMode === "live" ? (
            <Link href="/incidents">
              View incidents <ArrowRight size={14} />
            </Link>
          ) : null}
        </div>
      )}
    </div>
  );
}
