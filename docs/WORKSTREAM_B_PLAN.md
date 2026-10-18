# Workstream B implementation plan

Approved 2026-10-18. Workstream B includes B1-B9 and B11; Tinker is excluded.
The supplied brief is preserved in PARTNER_PLAN.md. Aun owns core, API, agent,
workflows, collector, migrations and router infrastructure. Their merged code is
the source of truth. Never create replacement shared schemas or Settings.

## Delivery and ownership

Use short `b/<task>` branches created before editing, isolated worktrees for
concurrent workers, and tested PRs for Aun to review and merge. The lead reviews,
integrates, manages shared manifests/lockfiles and reports actual validation.
Coding workers use `gpt-6-luna` with medium reasoning, at most three concurrently.
Every worker records its files, commands, results, decisions and blockers in a
handoff. Exact 60% compaction is controlled by the host; use token thresholds
where supported and persist handoffs regardless.

Core and voice removal are now merged. Follow [the lead acceptance cases](CORE_INTEGRATION_VALIDATION.md)
for the current integration, then limit follow-up work to Gate 2.

## Prerequisites and contracts

- Python 3.12, uv, Node LTS, Entire Codex hooks, GitHub authentication.
- Tailscale/Ollama/database/third-party setup may remain pending while independent
  modules and serialized fixtures are built. Secrets never enter source control.
- Aun supplies core plus subscriber traffic/IP evidence, DNS resolution timing,
  target/interface roles, backup topology, forecast write/upsert ownership,
  replay/injection lifecycle and Settings/API/SSE failure contracts.
- Require those additions before claiming affected features work. Never infer
  subscriber IPs or causes from evaluation labels.
- Free tiers and credits only; no purchase or paid upgrade is authorized.

## Implementation

1. G0: initialize tooling/instructions, preserve brief, document contracts and
   fixture mode. Enable Entire before the first implementation commit.
2. Data/simulator: discover RIPE Pakistan probes/measurements; bounded cached
   downloads; correct RTT/jitter/loss; calibration with provenance; three sites;
   daily/weekend demand and seven incident scenarios; deterministic Parquet and
   labels; load/replay/inject/held-out-case CLIs. Raw/generated data stays ignored.
   Live playback uses wall-clock timing; accelerated offline playback explicitly
   advances a virtual clock. Do not leak future observations into live windows.
3. G1: valid deterministic scenarios and repeat-safe persistence; current metrics
   appear within seconds of injection when the replay runtime is active.
4. Detector: past-only one-minute lag/rolling/calendar/utilization features;
   TabPFN 3.5 cloud/local regression quantiles for 1-5 minutes, unsupervised
   scoring, cause classification. Bound contexts, cache fits and batch requests.
   Normalize scores on validation data; freeze thresholds before held-out tests.
   Compare observations only to forecasts created earlier. Return series; the worker
   alone persists forecasts.
   Inference failures are unavailable, never healthy or silently mocked.
5. Retrieval: official RouterOS sources and headings, 300-500-word chunks,
   EmbeddingGemma through Ollama, pgvector, source URLs and top-k search. Verify
   768 dimensions and matching model identity. Vector search first; hybrid optional.
6. News: SerpApi recent provider/target outage search, finite deadlines and explicit
   unavailable states. Customer messages remain English and Urdu text.
7. G2: offline module tests pass; actual service smoke results reported separately.
8. Dashboard: Next.js App Router/TypeScript/Tailwind/shadcn/Recharts; Overview,
   Incidents, Incident Detail, Demo Panel; Settings waits for a backend interface.
   Responsive dark UI with Pakistan times, forecast bands, evidence, commands,
   rollback, CHR results, customer messages and timeline. Fixture/live transports share one
   interface. Generate API types from Aun's OpenAPI. SSE reconnect/refetch and
   duplicate-event handling. Confirm decisions and prevent duplicate submissions;
   commands are applied only when the API confirms the corresponding state.
9. Hosting/CI: Render UI and Aun's demo API, HTTPS/domain, persistent replay
   disclosure and recorded reports from real runs. Public actions only affect
   demo resources. Ruff/pytest/frontend checks/browser flow CI. CHR workflow runs
   Aun's harness on a pinned image with readiness polling, logs and VM cleanup;
   absent infrastructure is pending, never a fabricated router pass.
10. G3: phone-width live approval flow passes on Aun's host; hosted replay demo
    works; CI evidence exists. External accounts/contracts remain explicit gates.
11. Evaluation: 80 held-out cases, ten per cause including normal, independent
    training/validation/test seeds/time windows. Report detection and agent cause,
    template, params, CHR success and latency; missing metrics remain unavailable.
12. G4: post drafts include verified data provenance, target customer, open-model
    benefits/limits, demo guide and actual user feedback. Never invent users,
    measurements, sessions, report provenance or deployment claims.

## Integrations

Tiger MCP supports database inspection after Aun provisions it; app access uses
psycopg. TabPFN MCP supports experiments; runtime uses Python adapters. Use the
official Sentry Codex plugin for frontend monitoring and RouterOS QEMU skill for
CI. Authentication and a successful call are required before calling an MCP
connected. Keep Aun's private model/router services private.

## Deadline and fallback

Target 2026-10-19 10:00 Asia/Karachi; official submission deadline 11:59.
Defer Settings and hybrid search if necessary; retain saved-report hosting.
Do not cut meaningful validation, the incident walkthrough or post drafts.
