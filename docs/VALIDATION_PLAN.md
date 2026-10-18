# Validation plan

Tests must distinguish fixtures, real provider smoke tests and end-to-end checks.
Only the latter two establish external integration. No network in unit tests.

## Scenarios

| Cause | Distinguishing evidence | Expected template |
| --- | --- | --- |
| normal | ordinary peaks and isolated noise | none |
| uplink_congestion | high utilization, outside targets bad, gateway healthy | priority_queue |
| heavy_user | observed individual subscriber dominates traffic | queue_limit |
| upstream_degradation | external targets bad, local utilization normal | none |
| game_route_issue | only game target degrades | none |
| wireless_interference | evidence localized to a backhaul | none |
| uplink_down | primary fails, configured backup exists | failover_route |
| dns_slow | measured DNS resolution slow, other connectivity healthy | dns_servers |

An uplink failure without a backup must never invent backup route parameters.
Heavy-user fix parameters must come from observed subscriber telemetry, not labels.

## Required cases

- Simulator: reproducibility, physical ranges/units, UTC and PK hour boundaries,
  cadence/site isolation, overlaps, repeat-safe loads and time-correct replay.
- RIPE: complete packet loss, malformed/missing RTT values, bounded pagination,
  cache hits, timeouts, rate limits and provenance.
- Detector: empty/sparse/out-of-order windows, total loss, missing interfaces,
  insufficient history, cold starts, provider failures, finite bounded confidence,
  ordered quantiles and strictly past-only features/training/forecasts.
- Evaluate 80 held-out cases (10 per cause including normal); split entire
  incidents, seeds and time windows. Freeze thresholds on validation, not tests.
- Retrieval: correct top-three result for four fix topics; repeat-safe indexing;
  dimension/model mismatch; missing database/model; official source attribution.
- News: missing keys, timeout/rate limit, malformed search results and unavailable
  checks distinct from confirmed no outage.
- UI: mobile layout; loading/empty/error states; approval/rejection confirmation;
  duplicate clicks; failed CHR check; request errors; preserved English/Urdu customer text;
  reconnect/refetch and duplicate SSE events; live mode must not fall back to mocks.
- Integration: inject -> detect -> investigate -> CHR check -> approve/reject ->
  resolved/rolled_back. Verify workflow rejection and expiry with Aun.
- Deployment: HTTPS, deep links, replay disclosure, restart recovery, isolated
  public demo actions and a visitor walkthrough.

## Release targets

- Every controlled scenario detected during a seven-day scenario run.
- Held-out event precision and recall >= 90%; sustained-event delay <= 3 minutes.
- <= 1 false alert/site/day in a normal-only run.
- Warm detector p95 < 5 seconds/site for every mode claimed as supported.
- Correct runbook page within top three for every fix topic.
- Every actionable fix has valid params and a passing CHR check before approval.

Record actual counts, denominators, configuration, model/checkpoint identities,
hardware, cold/warm timing and unavailable checks in result reports. A passing
mock test cannot satisfy a database, provider, router or deployment gate.
