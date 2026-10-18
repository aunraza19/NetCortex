# Decisions made by the workstream lead

This is the running record of what we chose, why, and what it means. Package
`decision.md` files explain implementation details. See [flow.md](flow.md) for
how the pieces connect and [the implementation plan](docs/WORKSTREAM_B_PLAN.md).

| Decision | Reason | Consequence / alternative |
| --- | --- | --- |
| Build B1-B9 and B11; exclude Tinker | Agreed scope; establish the working product before optional fine-tuning | No fine-tuned planner is claimed |
| Start on `b/workstream-b`; isolate parallel workers in `b/data-simgen`, `b/runbook-notify`, `b/web-dashboard` worktrees | Keep main untouched and concurrent writes separate | Lead integrates owned paths and validates before pushing |
| Coding workers use `gpt-6-luna`, medium reasoning | User requested this model and lead/worker division | Lead specifies, reviews, tests and handles integration |
| Aun owns core, Settings, migrations, API, workflows, agent and router infrastructure | The shared build brief explicitly reserves those contracts | Import merged core directly; no replacement schemas |
| Build independent engines with plain data and explicit fixture modes | Core was initially absent; its merged contracts now bind public wrappers | Fixture success does not establish live integration |
| Use core DNS/subscriber contracts for the corresponding observations | Core now carries subscriber IP/traffic and DNS-kind probes; ICMP remains separate | Never fabricate offending IPs or claim DNS diagnosis from ping alone |
| Separate training, validation and final evaluation | Tuning thresholds on final tests inflates measured quality | Freeze thresholds before held-out scoring and report actual denominators |
| Failure is unavailable, never an implicit normal result | A failed diagnostic must not tell the operator a broken network is healthy | Provider errors stay visible; live transport never silently falls back to fixtures |
| Use TabPFN Python adapters in the application; MCP only for experiments | The detector needs a stable callable and explicit configuration | Connecting an MCP does not replace the runtime integration |
| Use Render Node hosting for the Next.js dashboard | SSR routes and dynamic incident URLs require the actual Next server | Static `dist` hosting is unsuitable for this application |
| Host the merged API in DEMO_MODE alongside the Next.js dashboard on Render | The saved replay API is part of Aun's merged contract and needs no DB/model/router on Render | Public browser origins need CORS and a confirmed .tech domain; deploy only on free services |
| Use free tiers and credits only | User's chosen spending limit | Any purchase or paid upgrade needs separate authorization |
| Add the MIT license specified in Aun's brief | The challenge plan explicitly requires MIT-licensed project code | Third-party model/data licenses still apply separately |
| Enable Entire before the first implementation commit | Capture coding provenance required by the brief | Hook installation is verified separately from transcript/checkpoint capture |
| Git author is `techieworld2` with the email the user supplied | User explicitly provided their commit identity | Repository-local identity; unrelated repositories are unchanged |
| Bind GitHub Git operations to `techieworld2` in Credential Manager | This machine has multiple stored accounts | Verified repo push/workflow permission without printing or committing tokens |
| Persist decisions, flow documentation and progress handoffs | User wants to understand the code and context must survive compaction | Every package/app has both documents; lead keeps these root documents current |
| Normalize tracked text to LF | The team develops on Windows and macOS and tests on Linux | Git whitespace checks and generated diffs behave consistently |
| Do not promise exact 60% compaction in this running session | Exposed agent controls do not set or trigger that threshold | Host compaction remains automatic; handoffs preserve state independently |
| Preserve a frozen aggregate calibration profile | Seeded evaluation also depends on the baseline statistics | Reproduce the recorded run without committing raw RIPE rows or relying on a moving download window |
| Require explicit opt-in for RIPE role transfer | Measured root-server routes differ from configured DNS destinations | Transfer can affect public DNS ping baselines only; provenance and uncertainty travel with generated data |
| Validate quantile layout, forecast time and freshness independently | SDK array shape and future rows can silently corrupt an otherwise plausible forecast | Regression tests cover each horizon, physical bounds, mixed sources and gaps |
| Treat live decision POST responses as acknowledgements | A workflow can still be applying or rolling back after the HTTP request succeeds | Fetch authoritative incident state and follow SSE updates |
| Separate CHR boot smoke from template validation | A real router can boot even while Aun's template harness is absent | CI reports those outcomes separately; no fabricated template pass |
| Keep the unpatched braces advisory documented | npm proposes an incompatible Next lint downgrade and no patched braces release exists | Production audit is clean; five development audit entries share one advisory |
| Use core Cause, PROBE_COLUMNS, IFACE_COLUMNS, and get_settings() in the detector | Shared contracts are merged and Settings is cached/configured centrally | Required detector observations are selected from those shared columns; optional core fields remain optional for lower-level legacy inputs |
| Make Gemma investigation and CHR dry-run explicit eval CLI options | Default scoring remains reproducible and offline; these steps need external model/router services | `--with-agent` calls the merged agent and fixes validator; `--chr-dry-run` additionally applies and rolls back on configured CHR |
| Use one phone-sized API browser project for approve-flow verification | The saved API fixture contains one pending approval that is consumed by approval | The Pixel 7 run exercises the actual REST approval through resolved state |
| Restore only non-voice partner plan rows and hosted-demo limits | Voice was dropped, while SerpApi, partner hardware, and TabPFN caveats remain in scope | Plan and implementation boundaries stay consistent |

## Findings from actual GitHub CI

The first Linux CI run passed. The parallel PR run exposed a browser assertion
against a short-lived fixture state, so tests now control the clock explicitly.
The first real CHR boot reached RouterOS login and exposed CRLF being treated as
two Enter keys during password confirmation. The serial helper now submits CR
and retains redacted diagnostics. Fake-console tests alone did not reveal this. The corrected
[Python/frontend CI](https://github.com/aunraza19/NetCortex/actions/runs/39131915864) and
[real CHR smoke](https://github.com/aunraza19/NetCortex/actions/runs/39131915789) both passed
on implementation commit `d60ffac`.

## Current external gates

Core, agent, fixes and collector are now merged. Database and TabPFN credentials
are configured locally for the bounded Gate 2 check. Embedding setup, retrieval
ingestion and hosting remain separate verification gates; fixture results do not
establish those integrations.

## Core integration and scope update

Rebased after PR #5 onto main fc297c1. Main's four root files remain byte-identical;
uv lock regenerated the lockfile. The lead wrote contract/validation cases before
three Luna medium agents changed owned paths. Public adapters import real core
models, preserve SecretStr and ModuleUnavailable, and never write forecasts from
detect. DNS/subscriber observations and atomic simulator injection now use core.
The embedding model setting is embeddinggemma. Customer messages stay text.

Current follow-up is Gate 2 only, on the same branch and PR #1: prepare legitimate TRAIN
and VALIDATION contexts, inject sim rows, and call actual TabPFN through detect.
A missing trained backend is an explicit unavailable result, not mock inference.
See [security verification](docs/SECURITY_VERIFICATION.md) for the redacted public
history/checkpoint audit and the current sandbox enforcement limitation.

The lead wrote preparation and runner acceptance tests before implementation.
Startup uses a versioned JSON artifact rather than serialized provider objects,
so credentials and SDK state never enter the artifact. TRAIN supplies supervised
cause context and normal density context; three normal VALIDATION snapshots
provide a limited plumbing reference. TEST files are excluded. This does not
establish detector accuracy or a production threshold. Repeated detect calls
reuse the configured backend, and the worker remains responsible for persistence.

The first credentialed setup exposed a real SDK assertion for constant training
metrics. Density fitting now excludes constant columns using normal TRAIN only;
it fails if no varying metric remains. Reference and live scores use the same
seeded feature order and CPU noise, with caller RNG state restored. Review also
found that rotated credentials or changed timeouts could reuse stale setup;
the cache now includes an internal configuration digest and rebuilds on changes.

The credentialed Gate 2 run returned a valid cloud DetectionResult with four
five-point series and no forecast-table row change. Setup took 271.7 seconds and
detect took 114.8 seconds. It predicted uplink_down for uplink_congestion. These
results establish integration only; model quality and latency need separate work.
The [sanitized report](eval/results/gate2.md) records the measured result.

Main advanced during verification with Aun's CHR PR #6. The same branch was
rebased again onto d70f76f and uv lock rerun. Main's four required root files
remain identical. The combined suite passes 220 offline tests with three live
tests deselected, including with unmocked Torch imports blocked.

The newly enabled CHR harness exposed a CI topology mismatch: B's boot smoke
created one NIC with DHCP defaults, while Aun's template tests require the
three-NIC baseline, static primary route and existing DNS resolver. The workflow
now uses Aun's canonical start/stop commands and unchanged template harness.
Credentials are random per job, masked before sharing through GITHUB_ENV, and
only QEMU logs and the template JSON report are uploaded. Lead acceptance cases
were written first; a boot-only pass cannot substitute for four restored fixes.

## Merged runtime integration (main f062f9d)

Continue on b/workstream-b and PR #1 as the user requested. Merge the runtime
without changing Aun's core, agent, API, worker, collector or router code. Keep
main's four required root files identical and regenerate uv.lock with uv.

The lead wrote docs/RUNTIME_INTEGRATION_VALIDATION.md and acceptance cases before
delegating implementation to three gpt-6-luna medium workers. The dashboard now
adapts generated types from the merged API's actual /openapi.json. Its fixture
view model stays a presentation detail; nullable API values remain unavailable,
and live HTTP errors never become fixture successes. /health determines whether
the API serves saved replay. Unknown health disables scenario injection. Dynamic
sites, actual EN/UR report text and commands, SSE invalidation, periodic metrics
refresh, and POST acknowledgement followed by authoritative GET match the runtime.

sim-tower is a dedicated runtime topology, excluded from the original three-site
evaluation generation. Its injection preserves any existing Site and source=live
rows, supplies missing normal observations and scripted recovery, and serializes
overlap checks and writes in one transaction. Recovery is simulated input, not
evidence that a router fix caused improvement. Unsupported game/wireless scenarios
on this topology fail explicitly rather than inventing missing targets.

The B-owned netcortex-detector-worker launcher configures a legitimate TRAIN/
normal-VALIDATION artifact before entering the unchanged worker in the same
process. This is necessary because prepared provider state is process-local.
Initialization stays outside the 120-second monitor activity. Independent TabPFN
inference paths overlap only through an explicit backend capability; custom
backends keep sequential behavior. Forecasts retain all eligible varying raw metrics, bounded
parallelism and past-only walk-forward checks. The 90-second forecast budget is
per batch, not a guarantee for the entire monitor activity. Worker-owned forecast
persistence stays unchanged. Measured results and limitations are recorded in
eval/results/runtime.md; a contract pass does not establish cause accuracy. The
latest real full-series inference takes 62.1 seconds (setup 99.1 seconds), within
the worker's 120-second activity limit. Cause accuracy and repeated-run
reliability remain unverified.

Browser acceptance runs the actual merged API's DemoStore with dotenv disabled,
including real REST decisions against an in-memory pending snapshot incident.
This tests the HTTP integration without claiming a local Temporal/router run.
The credentialed SQL check rolls back all test writes. Real-provider diagnostics
are captured privately and sanitized; no current transcript is published.

## Current review follow-up

The branch now includes the latest `main` merge and a regenerated `uv.lock`.
The saved-run API approve flow passes in Playwright at Pixel 7 dimensions. The
real API host on Aun's laptop was not reachable from this machine, so the check
used its merged `DEMO_MODE=true` DemoStore path. The Render blueprint now defines
both the UI and saved-snapshot API as free web services; adding the actual `.tech`
hostname and CORS origin requires the domain and Render/DNS account access.

The detector now gets settings from `get_settings()` and uses core Cause and
metric-column contracts. The four requested detector files were formatted.
`eval/run.py --with-agent` uses the merged async investigator and fix validator;
`--chr-dry-run` opts into applying and rolling back on the configured test CHR.
The complete offline suite passes after updating settings mocks. The public
credential scan reports generic-key matches in historical Entire transcript
objects; the known TabPFN key prefix and provider key names were absent from the
redacted scan metadata, and new edits are scanned before pushing.
