"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  ExternalLink,
  Info,
  Play,
  RotateCcw,
  ShieldCheck,
  Volume2,
} from "lucide-react";
import { transport } from "@/lib/transport";
import type { Incident } from "@/lib/types";
import { Confirm, CopyButton, ErrorBox, Status } from "./ui";
function Pst({ date }: { date: string }) {
  return (
    <time dateTime={date}>
      {new Intl.DateTimeFormat("en-PK", {
        timeZone: "Asia/Karachi",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(date))}{" "}
      PKT
    </time>
  );
}
export function IncidentDetail({ id }: { id: string }) {
  const [item, setItem] = useState<Incident | null>(null),
    [err, setErr] = useState(""),
    [dialog, setDialog] = useState<"approve" | "reject" | null>(null),
    [busy, setBusy] = useState(false),
    [voiceErr, setVoiceErr] = useState(""),
    [voiceUrl, setVoiceUrl] = useState("");
  const busyRef = useRef(false);
  const load = useCallback(
    () =>
      transport
        .incident(id)
        .then(setItem)
        .catch((e) => setErr(e.message)),
    [id],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    const unsubscribe = transport.subscribe(
      () => void load(),
      () => void load(),
    );
    return () => {
      window.clearTimeout(timer);
      unsubscribe();
    };
  }, [load]);
  const decide = async () => {
    if (!dialog || !item || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setErr("");
    try {
      const updated = await transport.decide(item.id, dialog, setItem);
      setItem(updated);
      setDialog(null);
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : "The decision could not be recorded.",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  if (!item)
    return (
      <div className="page">
        {err ? (
          <ErrorBox message={err} onRetry={load} />
        ) : (
          <div className="loading">Loading incident…</div>
        )}
      </div>
    );
  const canApprove =
    item.status === "awaiting_approval" &&
    item.dryRun === "passed" &&
    item.template !== "none" &&
    item.fix.length > 0;
  const canReject =
    item.status === "awaiting_approval" || item.status === "open";
  return (
    <div className="page">
      <Link href="/incidents" className="back-link">
        <ArrowLeft size={15} /> All incidents
      </Link>
      {err && <ErrorBox message={err} onRetry={load} />}
      <div className="detail-title">
        <div>
          <div className="eyebrow">
            {item.id} <span>·</span> <Pst date={item.openedAt} />
          </div>
          <h1>{item.title}</h1>
          <p>
            {item.siteName} <span>·</span> {item.cause.replaceAll("_", " ")}
          </p>
        </div>
        <Status status={item.status} />
      </div>
      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel narrative-panel">
            <div className="narrative-head">
              <div className="agent-avatar">N</div>
              <div>
                <strong>Network summary</strong>
                <small>
                  Investigation complete <span>·</span>{" "}
                  {Math.round(item.confidence * 100)}% confidence
                </small>
              </div>
              <span className="agent-tag">AGENT REPORT</span>
            </div>
            <p className="summary-copy">{item.summary}</p>
            <div className="evidence-block">
              <h3>
                <ShieldCheck size={15} /> What we observed
              </h3>
              {item.evidence.map((e) => (
                <div className="evidence-row" key={e}>
                  <span className="evidence-check">
                    <Check size={12} />
                  </span>
                  {e}
                </div>
              ))}
            </div>
          </section>
          <section className="panel timeline-panel">
            <div className="panel-heading">
              <div>
                <h2>Incident timeline</h2>
                <p>Events recorded for this incident</p>
              </div>
            </div>
            <div className="timeline">
              {item.timeline.map((t, idx) => (
                <div
                  className={`timeline-item timeline-${t.state}`}
                  key={`${t.at}-${idx}`}
                >
                  <span className="timeline-marker">
                    {t.state === "done" ? <Check size={12} /> : <span />}
                  </span>
                  <div>
                    <strong>{t.label}</strong>
                    <p>{t.detail}</p>
                    <small>
                      <Pst date={t.at} />
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </section>
          {item.news && (
            <section className="panel news-panel">
              <div className="news-icon">
                <Info size={16} />
              </div>
              <div>
                <h3>Upstream check</h3>
                <p>{item.news.label}</p>
                <a href={item.news.url} target="_blank" rel="noreferrer">
                  View source <ExternalLink size={13} />
                </a>
                <small>
                  News links are external references and may not reflect your
                  network.
                </small>
              </div>
            </section>
          )}
        </div>
        <aside className="detail-aside">
          <section className="panel fix-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">PROPOSED CHANGE</div>
                <h2>
                  {item.template === "none"
                    ? "No router change"
                    : item.template.replaceAll("_", " ")}
                </h2>
              </div>
            </div>
            {item.template === "none" ? (
              <div className="notify-note">
                This incident calls for monitoring or an upstream follow-up. No
                router commands are proposed.
              </div>
            ) : (
              <>
                <div className="test-result">
                  <span
                    className={
                      item.dryRun === "passed" ? "test-check" : "test-failed"
                    }
                  >
                    {item.dryRun === "passed" ? (
                      <Check size={13} />
                    ) : (
                      <Info size={13} />
                    )}
                  </span>
                  <div>
                    <strong>
                      {item.dryRun === "passed"
                        ? "Router test passed"
                        : item.dryRun === "failed"
                          ? "Router test failed"
                          : "Router test pending"}
                    </strong>
                    <p>{item.dryRunMessage}</p>
                  </div>
                </div>
                <div className="code-heading">
                  <span>APPLY COMMANDS</span>
                  {item.fix.length > 0 && (
                    <CopyButton text={item.fix.join("\n")} />
                  )}
                </div>
                {item.fix.length > 0 ? (
                  <pre className="command-block">
                    {item.fix.map((x) => (
                      <code key={x}>
                        {x}
                        {"\n"}
                      </code>
                    ))}
                  </pre>
                ) : (
                  <div className="code-empty">No commands are proposed.</div>
                )}
                <div className="code-heading rollback-heading">
                  <span>
                    <RotateCcw size={12} /> ROLLBACK COMMANDS
                  </span>
                  {item.rollback.length > 0 && (
                    <CopyButton text={item.rollback.join("\n")} />
                  )}
                </div>
                {item.rollback.length > 0 ? (
                  <pre className="command-block rollback-block">
                    {item.rollback.map((x) => (
                      <code key={x}>
                        {x}
                        {"\n"}
                      </code>
                    ))}
                  </pre>
                ) : (
                  <div className="code-empty">No rollback commands.</div>
                )}
              </>
            )}
            <div className="approval-note">
              <ShieldCheck size={15} />
              <span>Commands are not applied until you approve.</span>
            </div>
            {(canApprove || canReject) && (
              <div className="decision-actions">
                {canReject && (
                  <button
                    className="button button-secondary full-button"
                    onClick={() => setDialog("reject")}
                  >
                    Reject change
                  </button>
                )}
                {canApprove && (
                  <button
                    className="button button-primary full-button"
                    onClick={() => setDialog("approve")}
                  >
                    Approve change <ChevronRight size={16} />
                  </button>
                )}
              </div>
            )}
            {!canApprove && !canReject && (
              <div className="terminal-state">
                {item.status === "rolled_back"
                  ? "The change was rolled back."
                  : item.status === "rejected"
                    ? "The proposed change was rejected."
                    : item.status === "resolved"
                      ? "This incident is resolved."
                      : "Approval is unavailable until the router test passes."}
              </div>
            )}
          </section>
          <section className="panel voice-panel">
            <div className="voice-icon">
              <Volume2 size={16} />
            </div>
            <div className="voice-copy">
              <strong>Voice alert</strong>
              <small>Short incident summary</small>
            </div>
            <button
              className="play-button"
              aria-label="Play voice alert"
              onClick={() => {
                setVoiceErr("");
                void transport
                  .voice(item.id)
                  .then(setVoiceUrl)
                  .catch((e) => setVoiceErr(e.message));
              }}
            >
              <Play size={14} fill="currentColor" />
            </button>
            {voiceErr && <p className="voice-error">{voiceErr}</p>}
            {voiceUrl && (
              <audio
                className="voice-player"
                controls
                src={voiceUrl}
                aria-label="Incident voice alert"
              />
            )}
          </section>
        </aside>
      </div>
      <Confirm
        open={dialog === "approve"}
        onOpenChange={(v) => !v && setDialog(null)}
        title="Approve this router change?"
        description="The approved commands will be sent to the network service. You can review the rollback commands above."
        confirmLabel="Approve change"
        onConfirm={decide}
        busy={busy}
      />
      <Confirm
        open={dialog === "reject"}
        onOpenChange={(v) => !v && setDialog(null)}
        title="Reject this router change?"
        description="The proposed commands will not be applied. This decision will be recorded on the incident."
        confirmLabel="Reject change"
        onConfirm={decide}
        destructive
        busy={busy}
      />
    </div>
  );
}
