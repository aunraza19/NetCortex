# netcortex-api

FastAPI service for the dashboard.

```bash
uv run uvicorn netcortex_api.main:app --host 0.0.0.0 --port 8000   # OpenAPI at /openapi.json
```

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/health` | `{"status", "demo_mode"}` |
| GET | `/sites` | Health per site: `ok`, `degraded`, `down` or `unknown`, from the last 2 minutes |
| GET | `/metrics?site_id&series=...&from&to` | Points plus p10/p50/p90 forecast bands; `series` repeats |
| GET | `/incidents?status=` | Newest first |
| GET | `/incidents/{id}` | Incident (detection and report), fix plan with dry-run log, timeline |
| POST | `/incidents/{id}/approve`, `/reject` | Sends the Temporal signal. 409 unless `awaiting_approval` |
| POST | `/demo/scenarios` | `{site_id, scenario_type, duration_min}`: injects and makes sure the site is monitored |
| GET | `/stream` | Server-sent events (details below) |

`/stream` carries `incident.opened`, `incident.updated`, `fix.tested` and `fix.applied`.
Each message's `id:` is the `events.id`, so a client can reconnect with `Last-Event-ID` to
replay what it missed. A `: ping` heartbeat goes out every 15 s.

`DEMO_MODE=true` serves `src/netcortex_api/demo/snapshot.json` (saved from real runs with
`uv run python -m netcortex_api.snapshot`). It needs no database, Temporal, model or router.
CORS origins come from `API_CORS_ORIGINS`.
