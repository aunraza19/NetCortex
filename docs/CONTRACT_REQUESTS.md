# Contract questions for Aun

These are proposals and integration questions only. They do not change shared contracts. Aun must approve the answers and publish the source-of-truth definitions before Workstream B binds to them.

## Core package and shared types

- Confirm the distribution name and import name for `packages/core`; `netcortex_core` is the expected import namespace, but the distribution name is unresolved.
- Publish supported Python version, package exports, schema versions, and compatibility policy.
- Confirm exact types and field names for probe/interface metrics, forecasts, incidents, detection results, incident reports, fix plans, and template parameters.
- Clarify timestamp timezone/format, units, nullability, source labels, and identifier formats.

## Settings and API

- Confirm Settings field names, defaults, environment variable names, validation behavior, and secret handling.
- Confirm API base path, auth mechanism, owner/user role mapping, and how demo mode is represented.
- Provide request/response examples and explicit status/error payloads for incident list/detail, approval/rejection, history, and health endpoints.
- Define explicit failure semantics for upstream timeouts, unavailable model/provider, stale data, authorization failure, and partial results. Errors must remain distinguishable from a successful empty response.

## SSE and subscriber telemetry

- Confirm SSE endpoint, event envelope, event IDs/replay behavior, heartbeat cadence, reconnect expectations, and event names/payloads (`incident.opened`, `fix.tested`, and others).
- Specify whether subscriber identifiers/IPs are exposed, redacted, or role-gated in API events and the UI; identify retention and access policy.
- Clarify how a subscriber can be identified for heavy-user analysis without exposing unnecessary personal data.

## Timing and role mapping

- Confirm collection intervals, detector lookback/history window, forecast horizon, and freshness thresholds for probe and interface telemetry.
- Confirm role mapping for owner, operator, and read-only/demo viewers, including permissions for approve/reject and subscriber-level evidence.
- Confirm workflow timing and expiry behavior for approvals and for post-change observation/rollback.

## Forecast persistence and injection lifecycle

- Define a unique key and conflict/upsert policy for forecasts, including site, metric/target, model/version, and forecast timestamp dimensions as appropriate.
- Identify the sole forecast writer and the expected transactional behavior when a detection run retries.
- Define simulator injection start/end semantics, source labeling, scenario-label linkage, cleanup/expiry behavior, and whether injections can overlap.
- Clarify how generated/replayed rows differ from injected rows and which records are safe to retain in a hosted demo.

## Router test integration

- Confirm location and invocation contract for Aun's CHR harness, expected CHR image/license setup, and machine-readable result format.
- Workstream B CI will call `infra/chr/test_templates.py` only when Aun provides it. Until then, the router template CI gate is pending; no substitute test will be reported as a router test.
