# Gate 2: lead acceptance cases before implementation

PR #1 passed CI/GitGuardian and is ready at ce6a1b4. These updates stay on
b/workstream-b and PR #1, as requested, and focus on simulator injection and real
TabPFN detection.

1. Prepare a data-only artifact from TRAIN and VALIDATION cases. Never open TEST
   files at model startup/inference. Validate paths, split IDs, distinct seeds and
   time ranges. Cause labels are supervised TRAIN targets, not metric columns.
2. Fit the cause classifier from TRAIN. Fit the anomaly estimator only on normal
   TRAIN snapshots. Calibrate it with at least three normal VALIDATION scores.
   Exclude lag/rolling columns from density features; preserve predictor schema.
3. Explicit startup configuration loads this artifact and caches a prepared real
   provider. Repeated public detect calls reuse it; missing/corrupt setup is
   ModuleUnavailable. Do not pickle SDK objects or save credentials.
4. The public three-argument detect returns actual core DetectionResult, with
   cloud/local mode, canonical series keys, finite ordered quantiles at +1..5
   minutes, causal timestamps and no database writes.
5. Real smoke uses shared Settings internally, never prints credentials and never
   runs migrations. Preserve home-lab. Prepare a bounded normal history for a
   dedicated simulated site, inject a current scenario through public inject,
   fetch source=sim past-only observations, and call public detect.
6. Bound preparation/inference calls and record exact series subset and timing.
   A small normal reference/default threshold can establish plumbing only, not
   production accuracy, target recall/false-alert rates or warm p95 latency.
7. Save only sanitized result fields/timing/provider identity to a report. Capture
   vendor logs privately in memory and emit sanitized error classes/messages if
   a call fails. Never substitute a fixture when a provider fails.
8. Reuse setup only while artifact, provider mode, token and timeout match.
   Rotating a dummy token or changing timeout must rebuild the backend; identical
   configuration must reuse it. Store no raw token in artifact or cache metadata.

Lead tests for preparation leakage, setup reuse, actual engine/core mapping and
invalid artifacts are written before implementation delegation. The real smoke
is a separate credentialed check, not a CI unit test. Credentials stay in ignored
.env for application runtime; the agent never opens that file itself.
