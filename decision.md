# Decisions made by the workstream lead

This is the running record of what we chose, why, and what it means. Package
`decision.md` files explain implementation details. See [flow.md](flow.md) for
how the pieces connect and [the implementation plan](docs/WORKSTREAM_B_PLAN.md).

| Decision | Reason | Consequence / alternative |
| --- | --- | --- |
| Build B1-B9 and B11; exclude Tinker | Agreed scope; establish the working product before optional fine-tuning | No fine-tuned planner is claimed |
| Start on `b/workstream-b`; isolate parallel workers in `b/data-simgen`, `b/runbook-notify`, `b/web-dashboard` worktrees | Keep main untouched and concurrent writes separate | Lead integrates owned paths and validates before pushing |
| Coding workers use `gpt-6-luna`, medium reasoning | User requested this model and lead/worker division | Lead specifies, reviews, tests and handles integration |
| Aun owns core, Settings, migrations, API, workflows, agent and router infrastructure | The shared build brief explicitly reserves those contracts | We write requests and use lazy imports; no replacement schemas |
| Build independent engines with plain data and explicit fixture modes | Core and external credentials are absent | Fixture success does not establish live integration |
| Gate heavy-user and DNS claims on new telemetry contracts | Aggregate interface stats cannot identify a subscriber, and ping is not DNS resolution timing | Never fabricate offending IPs or claim DNS diagnosis from ping alone |
| Separate training, validation and final evaluation | Tuning thresholds on final tests inflates measured quality | Freeze thresholds before held-out scoring and report actual denominators |
| Failure is unavailable, never an implicit normal result | A failed diagnostic must not tell the operator a broken network is healthy | Provider errors stay visible; live transport never silently falls back to fixtures |
| Use TabPFN Python adapters in the application; MCP only for experiments | The detector needs a stable callable and explicit configuration | Connecting an MCP does not replace the runtime integration |
| Use Render Node hosting for the Next.js dashboard | SSR routes and dynamic incident URLs require the actual Next server | Static `dist` hosting is unsuitable for this application |
| Keep the API deployment gated on Aun's backend | Creating a second backend would break ownership and integration | Infrastructure docs may be ready before a public complete demo |
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

## Findings from actual GitHub CI

The first Linux CI run passed. The parallel PR run exposed a browser assertion
against a short-lived fixture state, so tests now control the clock explicitly.
The first real CHR boot reached RouterOS login and exposed CRLF being treated as
two Enter keys during password confirmation. The serial helper now submits CR
and retains redacted diagnostics. Fake-console tests alone did not reveal this.

## Current external gates

At the final integration refresh, upstream main still contains only README.md. Aun must publish
core/backend contracts. Database, tailnet, API keys, Sentry projects, Render and
domain access are not yet supplied. Their live checks remain pending until
verified; none are replaced with invented pass results.
