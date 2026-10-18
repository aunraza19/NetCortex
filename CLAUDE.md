  # NetCortex — Claude Code context (Workstream A, Aun)

## Read first

- **`docs/PARTNER_PLAN.md`** holds the full project context. Read it before any task. Key sections:
  - §2 hackathon rules and partner prizes
  - §3 product
  - §4 end-to-end flow
  - §5 machines and networking
  - §6 who builds what
  - §7 stack, repo layout, conventions
  - §8 shared contracts
  - §10 datasets
  - §11 timeline and gates
  - §13 risks and cut order
- **§9 of that doc is the partner's task list (Workstream B).** Do not build those parts.
- **This file covers Aun's tasks (Workstream A) and the current state of the machines.**
  - If this file and the plan disagree about Workstream A, this file wins.
  - Once `packages/core` is merged, the code is the source of truth for contracts.

**Deadline:** publish the DEV post by **Mon 19 Oct 2026, 10:00 AM Pakistan time** (hard deadline 11:59 AM PKT). Prefer working and simple over complete and clever.

## Current state (keep this section updated)

| Machine | Role | Status |
|---|---|---|
| Laptop (this machine): i7 10th gen, 32 GB RAM, Quadro P520 4 GB | Integration host. All code runs here: Docker, Temporal, CHR, API, workers, collector. | Active. Claude Code in VS Code. |
| Mac mini M4, 16 GB | **Model server only.** Ollama with `gemma4:e4b` (agent) and `embeddinggemma` (embeddings). `OLLAMA_HOST=0.0.0.0`, `OLLAMA_KEEP_ALIVE=24h`. **No git, no repo, no code runs there.** | Ready. On the same Wi-Fi as the laptop, reached over the LAN (no Tailscale). Its DHCP address changed once (192.168.1.5 → .6); if the agent can't connect, check `OLLAMA_BASE_URL` in `.env`. |
| Partner PC: GTX 1660 6 GB, 16 GB RAM, remote | Workstream B via Codex. Runs his own local Ollama for embeddings, plus Gemma 4 E2B/E4B for development. | Working from `docs/PARTNER_PLAN.md`, against the draft contracts. **Needs `packages/core` merged ASAP.** |

- **Networking:** the laptop and Mac share the home Wi-Fi, so the laptop uses the Mac's LAN address (Tailscale isn't installed on the laptop). The partner reaches the Mac through Tailscale.
- **Fallback:** if Tailscale fails, pull the partner's code from GitHub and run everything on the laptop. The laptop reaches the Mac over the home LAN.
- **Database:** Tiger Cloud (TimescaleDB + pgvector), shared by both people.
- **CHR test router:** QEMU for Windows (TCG; WHPX loses the NICs) runs RouterOS 7.24.5 locally. `infra\chr\start.ps1` boots it (REST `127.0.0.1:9180`, SSH `127.0.0.1:9122`), `reset.ps1` restores the baseline. `CHR_PASSWORD` is in `.env` only. All 4 templates pass `infra/chr/test_templates.py`.
- **Runtime (A2/A8/A9):** `infra\scripts\start-demo.ps1` starts everything (Temporal dev server with `var/temporal.db`, UI :8233; CHR; `uv run worker`; the API with the dashboard at http://localhost:8000/; the collector from `..\NetCortex-run`), and `stop-demo.ps1` stops it. The rule-based `stub_detector.detect()` is the only detector, and `stub_injector.inject()` (site `sim-tower`, laid out like the CHR baseline) is the only injector. `VERIFY_WAIT_S` defaults to 60 s for the demo.
- **The partner (Workstream B) is gone; Aun owns everything.** His packages (TabPFN detector, simulator, runbook search, news check) stay in the repo as experimental code. The running system doesn't call them (decision on 19 Oct: not reliable enough before the deadline).
- **Laptop quirks:** the Fedora WSL distro is broken (missing disk), Docker Desktop is usually off, and `uv` lives in `%APPDATA%\Python\Python315\Scripts`.

**Do not download large files on the laptop while the Mac model download runs.** Both share the home connection. Small Docker images and the CHR image are fine.

## Folder ownership

**Workstream A (edit freely):**
- `packages/core`, `packages/agent`, `packages/fixes`
- `services/api`, `services/worker`, `services/collector`
- `templates/routeros`
- `infra/` (except `infra/render`)
- `CLAUDE.md`

**Workstream B (do not edit; call their interfaces):**
- `apps/web`
- `packages/detector`, `packages/runbook`, `packages/notify`, `packages/simgen`
- `data/`, `eval/`, `experiments/`
- `.github/workflows`, `infra/render`, `AGENTS.md`

If a partner module is not merged yet, put a stub with the **same interface** in `packages/agent/stubs.py` and switch it out when theirs lands. Never fix a bug in their folders. Write it up for the partner instead.

## Tasks, in order

### A0. Setup (15 min)

- `uv` workspace at the repo root, Python 3.12 (pinned in `.python-version`; root `pyproject.toml` requires `>=3.12,<3.13`, matching the partner's packages).
- `ruff` and `pytest` configured.
- `.gitignore`: `.env`, `data/raw`, `data/generated`, `var/`, `.venv`, `node_modules`.
- MIT `LICENSE` if missing.
- Install Entire: `entire enable --agent claude-code`, before the first commit.

### A1. Contracts: `packages/core` (MOST URGENT, the partner is blocked)

1. **`schemas.py`** (pydantic v2): `Cause` and `TemplateId` enums (exact strings from plan §8), `MetricsWindow`, `SeriesForecast`, `DetectionResult`, `RunbookChunk`, `NewsItem`, `NewsCheck`, `ScenarioLabel`, `IncidentReport`, `FixPlan`, `IncidentStatus`.
2. **`settings.py`**: one `Settings` class (pydantic-settings) for every env var in plan §8. Add:
   - `APPLY_TARGET` (`chr` by default; `real` must be set explicitly)
   - `SITE_ID_LIVE` (default `home-lab`)
3. **`interfaces.py`**: `Protocol`s for `detect`, `search_runbook`, `check_news`, `inject`, `investigate`, with signatures exactly as in plan §8. (`speak` was removed with the voice feature.)
4. **`db.py`**: psycopg 3 connection pool and small helpers to insert metrics and incidents.
5. **`migrations/001_init.sql`**:
   - Enable the extensions `timescaledb` and `vector`.
   - Create all tables from plan §8.
   - Make `probe_metrics`, `iface_metrics` and `forecasts` hypertables.
   - Add indexes on `(site_id, time DESC)`.
6. **Additions beyond the plan** (Aun owns contracts, so add them now and tell the partner):
   - ~~Table `incident_audio`~~: voice was dropped; migration `002_drop_voice` removes the table.
   - Table `events(id bigserial, time, kind text, payload jsonb)`, plus a `NOTIFY netcortex_events` trigger. The API's SSE stream reads from it.
   - Seed a `home-lab` site for the live collector.
7. **`.env.example`** with every variable, and these values filled in:
   - `AGENT_MODEL=gemma4:e4b`
   - `EMBED_MODEL=embeddinggemma`
   - `OLLAMA_BASE_URL=http://<mac-tailscale-name>:11434`

**Done when:**
- `uv run pytest packages/core` passes.
- The migration applies cleanly to Tiger Cloud.
- The code is merged to `main`.
- A short message to the partner lists the merged interfaces and the additions in step 6.

### A2. Infra

- **`infra/docker-compose.yml`:**
  - Temporal dev server (or document `temporal server start-dev` if the CLI is simpler).
  - Optional local TimescaleDB with pgvector for offline work.
- **`infra/scripts/check_ollama.py`:** confirms the Mac is reachable, both models are listed, and an embedding has 768 dimensions.

**Done when:** Temporal UI opens on the laptop and `check_ollama.py` passes. Until the model finishes downloading, it is allowed to report "agent model missing".

### A3. Live collector: `services/collector`

- An async loop using `icmplib`.
- **Pings, every 10 s, for each target:**
  - Targets: gateway (home router), upstream hop (find it with a traceroute at startup, then fix it), `1.1.1.1`, `8.8.8.8`, one regional game server (configurable).
  - Send a burst of 5 pings per target.
  - Latency = average RTT; jitter = standard deviation of the RTTs; loss = % of pings lost.
- **Router stats, every 30 s:** read interface and queue stats from the RouterOS REST API (CHR now, a real MikroTik if one is available). If no router is configured, collect pings only.
- Writes rows with `source = live` and `site_id = SITE_ID_LIVE`.
- Survives errors: log, skip the round, keep running.
- One command starts it: `uv run collector`.

**Done when:** it runs unattended for an hour and rows keep appearing. **Start it as early as possible.** The partner's calibration needs hours of real data.

### A4. Virtual router: `infra/chr`

- **`start.sh`:**
  - Downloads the CHR x86 image (free license, 1 Mbps cap is fine).
  - Boots it in QEMU and forwards the REST API (HTTP) and SSH ports to localhost.
  - Waits until the REST API answers.
- **`reset.sh`:** restores a clean snapshot.
- **`baseline.rsc`:** baseline config:
  - `ether1` = primary uplink, `ether2` = backup uplink, `ether3` = LAN
  - A couple of simple queues
  - A DNS config
- **`test_templates.py`:** for every template, applies it with valid sample params, checks the result with `/export`, rolls back, and checks the config matches baseline. Exits non-zero on failure. **The partner's GitHub Actions workflow runs this script.**

### A5. Fix templates: `templates/routeros/*.yaml`

Four files: `queue_limit`, `failover_route`, `priority_queue`, `dns_servers`. Each has:
- `id`
- `description` (one plain sentence)
- `allowed_causes`
- `params` (each with a type plus range, regex or enum)
- `apply` (Jinja template of RouterOS commands)
- `rollback` (Jinja template)
- `verify` (which series should improve, and by how much)

`none` is a built-in with no commands.

Check every command against RouterOS v7 syntax. If unsure, test it on CHR before committing.

### A6. Fix checker: `packages/fixes`

1. `validate(template_id, params)`: rejects any value outside the schema.
2. `render(template_id, params)`: returns `(commands, rollback)`.
3. `dry_run(template_id, params)`, on CHR:
   - export the config before
   - apply
   - export the config after and diff it
   - roll back
   - export again and confirm it matches the original
4. Store the result in `fix_plans`.
5. `apply(...)`: used after human approval. It targets CHR unless `APPLY_TARGET=real`.

Talk to CHR through the REST API; SSH (`asyncssh`) is the fallback if a command can't run via REST. **Never touch a real router unless `APPLY_TARGET=real` is set explicitly.**

### A7. Agent: `packages/agent`

- **Model:** a Pydantic AI `Agent` using an OpenAI-compatible provider at `OLLAMA_BASE_URL/v1`, model `AGENT_MODEL`. Output type: `IncidentReport`.
- **Tools:**
  - `get_metrics(series, minutes)`
  - `get_forecast(series)`
  - `search_runbook(query)` (partner)
  - `check_news(provider, target)` (partner)
  - `list_templates(cause)`: returns only the templates allowed for that cause, plus `none`
- **Instructions to the model:**
  - Pick `template_id` only from `list_templates`.
  - Params must fit the schema.
  - Never write raw commands.
  - Say "unsure" with low confidence rather than guessing.
  - Customer messages must be short, in English and Urdu.
- **`investigate(site_id, detection, window) -> IncidentReport`**, async. If the model's output fails validation, retry once with the validation error fed back to the model. If it fails again, fall back to `template_id = none`.
- **Until `gemma4:e4b` finishes downloading:** develop and test with Pydantic AI `TestModel` / `FunctionModel`. Add one live smoke test marked `@pytest.mark.live`.

### A8. Workflows: `services/worker` (Temporal)

**`MonitorSiteWorkflow`**, one per site:
- Every 60 s, an activity:
  - loads the last 30 minutes plus history
  - calls `detect()` and writes forecasts
  - opens an incident if `is_anomaly` is true and no open incident exists for that site and cause
  - starts `IncidentWorkflow`
- Uses continue-as-new periodically.

**`IncidentWorkflow`:**
1. Investigate with Pydantic AI's `TemporalAgent` wrapper.
2. Run the fix check (`dry_run`).
3. Set the status to `awaiting_approval` and wait for an `approve` or `reject` signal, up to 2 h.
4. If approved: `apply()`, wait 5 minutes, verify.
5. If the key metric improved, mark `resolved`. If not, run rollback and mark `rolled_back`. If rejected or timed out, mark `rejected`.

Every status change writes an `events` row. Every partner call has a timeout, and a failed partner call never kills the workflow.

### A9. API: `services/api` (FastAPI)

- Endpoints exactly as in plan §8, except `GET /incidents/{id}/voice` (voice was dropped). Publish `/openapi.json`; the partner generates TypeScript types from it.
- `/stream` = SSE fed by Postgres `LISTEN netcortex_events`.
- Approve and reject send Temporal signals.
- `/demo/scenarios` calls the partner's `simgen.inject()`.
- Enable CORS for the partner's UI (local dev and the Render domain).
- `DEMO_MODE=true`: serve saved reports and replayed data, with no agent calls. Render has no GPU.

### A10. Backend tracing

- `sentry-sdk` with tracing on in the API and the workers, plus the Pydantic AI integration (agent and model spans).
- Manual spans for `detect()`, `dry_run()` and `apply()`.
- Take screenshots of good traces for the post. The Sentry category requires them.

### A11. Integration (Gate 3 in plan §11)

- Swap the stubs for the partner's real modules.
- Run end to end on 3 scenarios (`heavy_user`, `uplink_down`, `dns_slow`), then all 7.
- Save the agent reports from real runs for `DEMO_MODE`.

### A12. Post (technical sections)

Write these in `docs/post/`, using findings from `docs/post/notes.md`:
- architecture
- agent design and safety (templates, CHR dry-run, human approval, auto-rollback)
- Sentry traces
- why local Gemma

Also record the demo video.

## What the partner delivers (plan §9), and when it lands

| Partner module | Interface you call | Expected by |
|---|---|---|
| Simulator + datasets | `simgen.inject()`, `simgen replay` CLI, `sim` rows in the DB | Gate 2 |
| Detector (TabPFN) | `detect()` | Gate 2 |
| Docs search | `search_runbook()` | Gate 3 |
| News | `check_news()` | Gate 3 |
| Web UI | consumes your API + SSE | mock mode by Gate 2, live by Gate 3 |
| Eval runner | calls your `investigate()` | Gate 3 |
| Hosted demo, CI | uses your `DEMO_MODE` and `infra/chr/test_templates.py` | Gate 4 |

## Rules for this session

- After `packages/core` is merged, any change to it is a **breaking change for the partner**: do it in a small PR, explain it, and tell the partner.
- No hardcoded hosts, ports or model names. Everything comes from `Settings`.
- Every network call has a timeout. Optional services (SerpApi, TabPFN cloud) never block an incident.
- Generated router commands come only from templates. No free-form commands from the model, ever.
- Small, frequent commits on `a/<task>` branches, merged via PR (Entire checkpoints on each commit).
- Prefer simple, readable code. Judges will read it.
- Add interesting findings and numbers to `docs/post/notes.md` as you go.

## Useful commands

```bash
uv sync                                   # install workspace
uv run pytest -m "not live"               # unit tests
uv run pytest -m live                     # needs the Mac model
temporal server start-dev --db-filename var/temporal.db   # Temporal + UI on :8233
uv run worker                             # Temporal worker (monitors + incidents)
uv run python infra/scripts/check_ollama.py
uv run python infra/scripts/e2e.py heavy_user             # inject -> approve -> resolved
uv run collector                          # live collector
bash infra/chr/start.sh                   # boot CHR
uv run python infra/chr/test_templates.py # test all fix templates on CHR
uv run uvicorn netcortex_api.main:app --host 0.0.0.0 --port 8000
```
