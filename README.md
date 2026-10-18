# NetCortex

An on-call network engineer for small ISPs and gaming cafés that runs on local hardware.
It watches a site, opens an incident when something goes wrong, has a local Gemma model
explain the likely cause and pick one fix from tested MikroTik templates, dry-runs that fix
on a virtual router, waits for a person to approve it, applies it, and rolls it back if the
key metric doesn't improve.

```
collector -> TimescaleDB -> rule-based detector -> Temporal incident workflow
  -> Gemma agent (tools) -> template-only fix -> CHR dry run -> human approval
  -> apply -> watch -> verify -> resolved, or automatic rollback
```

## Run the demo

Needs: Windows, [uv](https://docs.astral.sh/uv/), the Temporal CLI, QEMU (for the CHR test
router), Ollama with `gemma4:e4b` reachable at `OLLAMA_BASE_URL`, and a `.env` made from
[.env.example](.env.example) (Tiger Cloud `DATABASE_URL`, `CHR_PASSWORD`, optional
`SENTRY_DSN_BACKEND`).

```powershell
uv sync
powershell -ExecutionPolicy Bypass -File infra\scripts\start-demo.ps1
```

[start-demo.ps1](infra/scripts/start-demo.ps1) opens a window each for the Temporal dev
server (`var/temporal.db`, UI on :8233), the CHR test router (REST on :9180), the worker,
the API and the live collector (from `..\NetCortex-run`, a second checkout). Anything
already running is left alone. It then checks the model server and prints the dashboard
URL: **http://localhost:8000/**

In the dashboard, pick a scenario under "Simulate incident" (heavy user, uplink down, slow
DNS) and press Inject. Within a minute or two an incident opens with Gemma's report, the
router commands and the CHR dry-run result. Approve it after the scenario ends (the note
under Inject gives the time): the simulated site recovers then, and the fix is judged
after a 60-second watch (`VERIFY_WAIT_S`; production would use 300). The same scenario
can run again 4 minutes after its last incident closes.

To stop everything:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\stop-demo.ps1            # all of it
powershell -ExecutionPolicy Bypass -File infra\scripts\stop-demo.ps1 -KeepCollector
```

From a terminal instead of the dashboard: `uv run python infra/scripts/e2e.py heavy_user`
injects, waits, approves and prints the timeline.

## Layout

| Path | What it is |
|---|---|
| `packages/core` | Shared schemas, settings, database helpers, migrations |
| `packages/agent` | The Pydantic AI agent on Gemma, the rule-based detector, the scenario injector |
| `packages/fixes` | Fix templates' validation, rendering, CHR dry run, apply and rollback |
| `templates/routeros` | The four fix templates (YAML) |
| `services/worker` | Temporal workflows and activities, Sentry tracing |
| `services/api` | FastAPI: REST, server-sent events, approvals, and the dashboard at `/` |
| `services/collector` | Live pings and DNS timings from a real connection |
| `infra/chr` | The MikroTik CHR test router in QEMU, and the template test harness |
| `packages/detector`, `simgen`, `runbook`, `notify`, `eval`, `data` | The partner's experimental TabPFN detector, simulator, docs search and news check; not used by the running system |

Tests: `uv sync --all-packages`, then `uv run pytest -m "not live"` and `uv run ruff check .`

MIT licence.
