"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Filter, Search } from "lucide-react";
import { transport } from "@/lib/transport";
import type { Incident, Site } from "@/lib/types";
import { SectionTitle, Status, ErrorBox } from "./ui";
export function IncidentList({ initialSite = "" }: { initialSite?: string }) {
  const [items, setItems] = useState<Incident[]>([]),
    [status, setStatus] = useState(""),
    [site, setSite] = useState(initialSite),
    [query, setQuery] = useState(""),
    [sites, setSites] = useState<Site[]>([]),
    [err, setErr] = useState("");
  const load = useCallback(
    () =>
      transport
        .incidents(status || undefined, site || undefined)
        .then(setItems)
        .catch((e) => setErr(e.message)),
    [status, site],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    void transport
      .sites()
      .then(setSites)
      .catch(() => setSites([]));
    const unsubscribe = transport.subscribe(
      () => void load(),
      () => void load(),
    );
    return () => {
      window.clearTimeout(timer);
      unsubscribe();
    };
  }, [load]);
  const filtered = items.filter((i) =>
    `${i.title} ${i.siteName} ${i.cause}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <div className="page">
      <SectionTitle eyebrow="Operations" title="Incidents">
        <span className="muted-caption">{items.length} total</span>
      </SectionTitle>
      {err && <ErrorBox message={err} onRetry={load} />}
      <section className="panel table-panel">
        <div className="filter-row">
          <label className="search-box">
            <Search size={16} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search incidents"
              aria-label="Search incidents"
            />
          </label>
          <label className="select-wrap">
            <Filter size={15} />
            <select
              value={site}
              onChange={(e) => setSite(e.target.value)}
              aria-label="Filter by site"
            >
              <option value="">All sites</option>
              {sites.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <select
            className="status-select"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {[
              "open",
              "awaiting_approval",
              "applying",
              "verifying",
              "resolved",
              "rolled_back",
              "rejected",
            ].map((s) => (
              <option key={s} value={s}>
                {s.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </div>
        <div className="incident-table">
          <div className="table-head">
            <span>INCIDENT</span>
            <span>SITE</span>
            <span>STATUS</span>
            <span>OPENED</span>
            <span />
          </div>
          {filtered.map((i) => (
            <Link className="table-row" href={`/incidents/${i.id}`} key={i.id}>
              <span>
                <strong>{i.title}</strong>
                <small>
                  {i.id} <i>·</i> {i.cause.replaceAll("_", " ")}
                </small>
              </span>
              <span>{i.siteName}</span>
              <span>
                <Status status={i.status} />
              </span>
              <span>
                {new Intl.DateTimeFormat("en-PK", {
                  timeZone: "Asia/Karachi",
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                }).format(new Date(i.openedAt))}{" "}
                PKT
              </span>
              <ArrowRight size={16} />
            </Link>
          ))}
          {!filtered.length && (
            <div className="empty-state">No incidents match these filters.</div>
          )}
        </div>
      </section>
    </div>
  );
}
