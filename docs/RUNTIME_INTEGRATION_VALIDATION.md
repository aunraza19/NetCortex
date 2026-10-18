# Runtime integration: lead acceptance plan

Base: main f062f9d, merged runtime PR #7. Keep b/workstream-b and PR #1.
Lead acceptance cases are written before Luna medium implementation workers.

1. Merge main, restore its four required root files, regenerate uv.lock with uv.
   Keep Python 3.12. Never run migrations or open dotenv/credential files.
2. Generate TypeScript from the actual merged API's /openapi.json, served locally
   in DEMO_MODE with Settings(_env_file=None). Bind live HTTP through generated
   types and explicit adapters. Match nullable health fields, nested incident/
   report/fix_plan/timeline and metric series points/bands. Keep missing values
   visibly unavailable, never fabricate site metadata or model evidence.
3. Live selectors fetch sites; use /health to distinguish saved API replay from
   live operation. Replay cannot inject scenarios. Render actual English/Urdu
   report messages and actual CHR commands. Reject only awaiting_approval, just
   like the API. Approve POST is acknowledgement followed by authoritative GET.
4. Refresh metric views on a bounded interval and named SSE updates/reconnect;
   retain duplicate-event handling and dispose timers/listeners. Test actual API
   replay in browser, including a pending snapshot incident approved via real
   REST handlers. Existing fake-payload tests must use the real contract shapes.
5. Add sim-tower as a dedicated CHR-compatible simulator topology. Preserve the
   original three data fixtures and every existing Site (especially home-lab).
   Match 10.0.2.2/192.0.2.1 gateways, subscriber 10.0.0.42/57/63, DNS probes for
   dns:192.0.2.53 and dns:1.1.1.1, source=sim and core models. Seed missing normal
   history, inject incident rows, add explicitly scripted normal recovery.
   Preserve transaction/overlap locks and avoid deleting live rows or duplicating
   previously generated normal/recovery intervals on repeat injection.
6. Provide a B-owned worker launcher that configures the detector before calling
   the unchanged Temporal worker in the same process. Invalid setup fails closed.
   No core/agent/worker ownership changes. Initialization is outside the 120 s
   monitor activity; detect has no forecast DB writes. Improve real call cost
   through batching/reuse/bounded concurrency without weakening causal forecast
   checks, reading TEST labels, changing the anomaly rule, or substituting mocks.
7. Validate offline suites, lint, browser/build checks and actual API replay.
   A bounded real-provider check records real timing/cause limitations; never
   call a fake-provider test an end-to-end real stack pass. Preserve public
   transcript protections, scan changed contents, push and inspect CI/GitGuardian.

Each worker owns its component decision.md/flow.md; the lead owns these acceptance
tests, root decision/flow, CI integration, merge, lockfile and final verification.
