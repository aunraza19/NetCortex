# Shared contract answers and remaining runtime checks

Aun answered the original questions in [merged core PR #2](https://github.com/aunraza19/NetCortex/pull/2).
The code in packages/core is authoritative. [PR #5](https://github.com/aunraza19/NetCortex/pull/5)
removed speech generation and its database storage. This file supersedes the original unanswered checklist.

- Python 3.12; netcortex-core / netcortex_core. Import shared schemas and Settings directly.
- Secrets are SecretStr: unwrap at their network/DB boundary; never log raw values.
- MetricsWindow includes probe, interface and subscriber DataFrames with UTC as_of.
- DNS observations: kind=dns, target=dns:<resolver>, rtt_ms is lookup response time.
- SubscriberMetric carries IP and traffic; hosted demos use synthetic addresses only.
- Site combines primary, backup and backhaul uplinks; ProbeTarget carries role/kind/host.
- detect returns DetectionResult (score, cause_guess, series, cloud/local/mock mode).
- Only the worker persists forecasts, uniquely keyed by site/series/model/time.
- inject writes source=sim rows from now for duration plus one ScenarioLabel; reject
  overlapping active injection for a site. Keep these writes atomic.
- get_pool, insert metric helpers, upsert_site and fetch_site are shared DB helpers.
- search_runbook score is one minus cosine distance. EMBED_MODEL=embeddinggemma.
- check_news returns NewsCheck(available=False, ...) when unavailable.
- Text customer messages remain English and Urdu.
- Migration 001 is already applied on Tiger Cloud: do not rerun it or run migrations
  as part of partner setup, tests, injection or detection.

## API and workflow agreements

Root paths follow the plan; actual generated client types wait for OpenAPI from A9.
Errors use detail with 404/409/503; an empty successful collection stays 200 [].
The hackathon build has one owner role, no authentication. Settings stays read-only.
SSE events use numeric IDs, named events and JSON payloads, replay Last-Event-ID,
and a 15-second comment heartbeat. Metric events are transient.

Approval waits up to two hours. The workflow verifies five minutes after applying
and rolls back on failed improvement. Public demo approvals replay saved timelines.
The template harness contract is infra/chr/test_templates.py with --json PATH;
CI keeps the readiness gate until that file exists.

## Scope now

Finish core binding and removal, push the existing PR and mark ready after checks.
Then work only on Gate 2: real simgen injection to actual TabPFN detect returning
DetectionResult. Agent, fixes and runtime services remain Aun-owned. Provider-free
checks cannot establish Gate 2. No new shared contract is needed to prepare a
legitimate detector training artifact from TRAIN and VALIDATION data.
