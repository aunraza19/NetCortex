# NetCortex — Partner Build Plan

Oct 18, 2026 · @Aun Raza

## 1. How to use this document

This is the build brief for **Workstream B (partner)** of NetCortex. It is written to be pasted into a Codex session, which should turn it into a step-by-step task plan and then build it.

- **Who reads it:** the partner and their Codex session. Aun (Workstream A) builds with Claude Code from the same repo: [github.com/aunraza19/NetCortex](https://github.com/aunraza19/NetCortex).
- **What Codex should do first:** read the whole document, then write a task plan for Workstream B only, in the order of section 9, with the checkpoints in section 11.
- **What Codex must not do:** change the shared contracts in section 8 on its own. They belong to Aun. If a contract is wrong or missing something, stop, write the proposed change in a PR description, and ask Aun.
- **When something is unknown** (an exact model tag, an API field name, a package version): check the official docs, pick the current stable option, and note the choice in the PR. Do not guess silently.
- **Where things in this document stop being true:** once Aun merges `packages/core`, that code is the source of truth for schemas and interfaces. This document is the starting point.

Save a copy of this document in the repo as `docs/PARTNER_PLAN.md` so both agents can read it.

## 2. Hackathon context

We are entering the DEV **Hacktoberfest Open-Source AI Challenge, Week 2: "Side Hustle"**. The deadline is **Monday 19 October 2026, 11:59 AM Pakistan time**. Our own target is to publish by **10:00 AM**.

- **The prompt:** build something with open-source AI at its core that someone would actually pay for. The open pieces (open-weight models, open frameworks, local inference) must be what makes the project work.
- **The deadline in other time zones:** the page says 18 October. Week 1 ended at 11:59 PM PDT, so we assume Week 2 does too. That is 11:59 AM Monday in Pakistan. Confirm on the Week 2 contest rules page.
- **What we submit:** a post on DEV using the challenge template (it adds the `#devchallenge` and `#hf26challenge` tags). The post explains what we built, who would pay, a demo, why open innovation matters for it, and ideally our first real user.
- **Judging, in order of weight:** writing quality (weighted most heavily), relevance to the prompt and theme, creativity, technical execution, and use of partner technology (optional).
- **Repo rules to respect:** public repo, an open-source license (MIT), and work created during the challenge week.

**Partner prize categories we target.** Each one must do a real job in the system and be clearly shown in the post.

| Partner | Prize | Its job in NetCortex | Built by |
| --- | --- | --- | --- |
| Prior Labs (TabPFN) | $200 | Forecasting, anomaly scoring, cause guessing | Partner |
| Gemma | $200 | The agent model and the embedding model | Aun (agent), Partner (embeddings index) |
| Render | $200 | Hosts the public demo | Partner |
| Tinker (optional) | $200 | Fine-tune a small fix planner and compare with Gemma | Partner, only if time allows |
| Temporal | $100 | Durable monitoring and incident workflows | Aun |
| Sentry | $100 | Traces every agent and model step | Aun (backend), Partner (UI) |
| Tiger Data | $100 | Metrics storage (TimescaleDB) and docs search (pgvector) | Shared database, Aun sets it up |
| ElevenLabs | $100 | Voice alert for the owner, Urdu or English | Partner |
| SerpApi | $100 | "Is it us or them?" outage check | Partner |
| .tech domain | $100 | The demo's public address | Partner |
| GitHub | $100 | CI that tests every fix on a virtual router, Copilot PR review | Partner |
| Entire | $100 | Records our coding-agent sessions for the post | Both |

Check the rules for whether one post can win more than one category. Either way, judges reward real use, not logos.

## 3. The product: NetCortex

NetCortex watches a small network, warns before customers start complaining, explains what is wrong in plain words, and proposes a tested router fix that a human approves.

**Who pays and why.** Small neighbourhood internet providers (WISPs), gaming cafes and freelance network engineers. When latency spikes or a link fails, usually in the evening, they get flooded with complaints and lose customers. They don't have a network operations team. NetCortex gives them one for the price of a small box.

**What it does, in order:**

1. Collects ping results and router interface stats around the clock.
2. Forecasts what "normal" should look like for the next few minutes and flags when reality drifts badly away from it.
3. Investigates: is the uplink full, is one user hogging it, is the upstream ISP having a bad day, or is one game server's route broken?
4. Proposes one fix from a set of tested MikroTik RouterOS templates, with the exact commands and the commands to undo them.
5. Tests that fix on a virtual MikroTik router before any human sees it.
6. Alerts the owner (dashboard, plus a short voice note in Urdu or English) and waits for Approve or Reject.
7. After an approved fix, watches the metrics and rolls back automatically if things did not improve.

**Why open models matter here** (this is a required part of the post):

- **Privacy:** router configs, network layout and subscriber traffic never leave the premises when the on-site version runs with local models.
- **Works when the internet doesn't:** the tool that diagnoses a broken uplink can't depend on that uplink. Gemma runs locally.
- **Cost:** no per-token bills, so a small ISP can afford it.
- **Control:** we can swap models, fine-tune for RouterOS, and constrain the agent's output.

**Honest limits to state in the post:** TabPFN-3.5's cloud API sends anonymised metrics out, and its free license is non-commercial (a paid product would need a commercial license). Cloud add-ons (ElevenLabs, SerpApi, TabPFN cloud) are optional switches. The hosted demo uses replayed and simulated data.

**Vendor scope:** MikroTik RouterOS only. It is common among small ISPs and has a free virtual router image (CHR) we can test on. Cisco is out of scope.

## 4. System overview and end-to-end flow

Data flows from the network into one shared database. Temporal runs detection, the agent and the fix check. The owner approves the fix in the web UI.

&#91;embedded content: NetCortex architecture · who builds each part\]

The highlighted boxes are the partner's. Every partner box is a plain function or CLI that Aun's workflows call.

### The flow, step by step

1. **Data in.** The live collector (`source = live`) or the simulator (`source = sim`, via generate, replay or inject) writes rows to `probe_metrics` and `iface_metrics`.
2. **Watch.** Every minute, `MonitorSiteWorkflow` calls the partner's `detect()` with the last 30 minutes plus recent history. Forecasts are written to `forecasts`.
3. **Open.** If `is_anomaly` is true and no incident is open for that site and cause, an `incidents` row is created and `IncidentWorkflow` starts.
4. **Investigate.** Aun's agent runs `investigate()`. It reads the detection result and calls tools: metrics lookup, the partner's `search_runbook()` and `check_news()`, and the template list. It returns an `IncidentReport`.
5. **Check the fix.** The fix checker validates the template values, fills the template, applies it on the virtual MikroTik router, reads back the config, then rolls it back. The result goes in `fix_plans`.
6. **Alert.** The partner's `speak()` makes a short voice note. The API pushes `incident.opened` and `fix.tested` events to the UI.
7. **Decide.** The owner opens the incident in the UI and presses Approve or Reject. The API sends a Temporal signal. The workflow waits up to 2 hours.
8. **Apply and verify.** If approved, the fix is applied (to the virtual router in the demo). The workflow watches the key metric for 5 minutes. Improved → `resolved`. Not improved → automatic rollback → `rolled_back`.
9. **Trace and score.** Sentry traces every step. The partner's eval runner replays the same path offline to measure accuracy.

### Two ways it runs

- **On-site product:** one Docker Compose file with self-hosted TimescaleDB, Temporal, the API, the UI and Ollama on a small box at the ISP. Works offline; cloud add-ons are optional switches.
- **Hosted demo:** Render + the .tech domain + Tiger Cloud, with replayed simulator data and saved agent reports, clearly labelled.

## 5. Team, machines and networking

Two people on two networks. Tailscale joins the machines into one private network, and one cloud database holds the shared data.

| Person | Machine | Specs | Runs |
| --- | --- | --- | --- |
| Aun | Mac mini M4 | 16 GB RAM, 256 GB disk | Ollama: Gemma 4 E4B (agent) and EmbeddingGemma (embeddings), shared over Tailscale |
| Aun | Laptop | Intel i7 10th gen, 32 GB RAM, NVIDIA Quadro P520 4 GB | Docker: Temporal dev server, MikroTik CHR virtual router (QEMU), FastAPI, Temporal workers, live collector. This is the integration host. |
| Partner | PC | NVIDIA GTX 1660 6 GB, 16 GB RAM | Simulator, detector, docs indexer, voice and news modules, web UI, CI and deploy work. Local TabPFN and local EmbeddingGemma. |

**Shared services:**

| Service | Where | Who uses it | How to reach it |
| --- | --- | --- | --- |
| Tailscale network | All three machines | Both | Install, join Aun's tailnet. Use Tailscale IPs or MagicDNS names. |
| Ollama (Gemma models) | Aun's Mac mini | Both | `http://<mac-tailscale-name>:11434` (OpenAI-compatible at `/v1`) |
| Database (Tiger Cloud, free plan) | Cloud | Both | One `DATABASE_URL`, shared privately. TimescaleDB + pgvector are included. |
| Temporal, FastAPI, CHR | Aun's laptop | Partner for integration tests | `http://<laptop-tailscale-name>:8000` (API), `:7233` (Temporal), CHR REST via the laptop |
| Sentry | Cloud | Both | Two projects: `netcortex-backend`, `netcortex-web` |
| Render + .tech | Cloud | Partner | Public demo |

**Rules that follow from this setup:**

- The partner's code must run and be tested **without** Temporal, CHR or Aun's laptop. Each partner module is a plain Python function or CLI with its own tests.
- Embeddings must come from the **same model and tag** on both sides, or search breaks. Agree the exact EmbeddingGemma tag in the contracts call and pin it in `.env.example`.
- Ollama has no login. Never expose it to the public internet. Tailscale only.
- The free Tiger Cloud service has a storage limit (about 750 MB). Keep raw simulator output in Parquet files, and load only what the demo and the detector need. Use a `source` column (`live`, `sim`, `ripe`) to keep data apart.
- If Tailscale fails for any reason, the fallback is: partner runs Ollama locally with Gemma 4 E2B (or E4B if it fits the 6 GB card) and EmbeddingGemma, and points `OLLAMA_BASE_URL` at localhost.

## 6. Who builds what

Aun builds everything that needs his hardware, the router or the runtime glue. The partner builds everything that can be built and tested on its own: data, detection, search, side services, the UI and deployment.

**Workstream A: Aun (Claude Code). Read this so you know what you plug into.**

| Part | What it is | Folder |
| --- | --- | --- |
| Shared contracts | Schemas, DB tables, module interfaces, template format | `packages/core` |
| Infra | Docker Compose, Tailscale, Temporal dev server, CHR in QEMU | `infra/` |
| Model serving | Ollama on the Mac: Gemma 4 E4B + EmbeddingGemma | Mac mini |
| Live collector | Pings 5 targets every 10 s; reads router interface and queue stats every 30 s; writes `source = live` rows | `services/collector` |
| Fix templates | 4 RouterOS templates in YAML, each with apply, rollback and success metric | `templates/routeros/` |
| Fix checker | Validates values, fills the template, applies on CHR, reads back, rolls back, stores the result | `packages/fixes` |
| Agent | Pydantic AI agent on Gemma 4 E4B. Calls the partner's modules as tools. Returns `IncidentReport`. | `packages/agent` |
| Workflows | `MonitorSiteWorkflow`, `IncidentWorkflow` (approve/reject signals, verify, rollback) | `services/worker` |
| API | FastAPI REST + SSE stream for the UI | `services/api` |
| Backend tracing | Sentry agent tracing on API, workers and agent | `services/*` |
| CHR template test script | `infra/chr/test_templates.py`, used by the partner's CI | `infra/chr` |

**Workstream B: Partner (Codex). Your job.**

| Part | What it is | Folder |
| --- | --- | --- |
| B1 Setup | Tailscale, Entire, keys, local Ollama embeddings, repo tooling | — |
| B2 Datasets + simulator | Real data ingest (RIPE Atlas, live collector export), simulator, scenarios, labels, network layout, eval set | `packages/simgen`, `data/`, `eval/` |
| B3 Detector | TabPFN forecasting, anomaly score, cause classifier → `detect()` | `packages/detector` |
| B4 Docs search | MikroTik docs → chunks → EmbeddingGemma → pgvector → `search_runbook()` | `packages/runbook` |
| B5 Side modules | `speak()` with ElevenLabs, `check_news()` with SerpApi | `packages/notify` |
| B6 Web UI | Next.js dashboard, mobile-first, mock mode first | `apps/web` |
| B7 Hosted demo | Render + .tech domain, demo mode with replay | `infra/render` |
| B8 CI | GitHub Actions: lint, tests, CHR template tests; Copilot PR review | `.github/workflows` |
| B9 Eval runner | Scores the agent on the eval set | `eval/` |
| B10 Tinker (optional) | Fine-tune a small fix planner, compare with Gemma | `experiments/tinker` |
| B11 Post | Story sections of the DEV post | `docs/post/` |

## 7. Tech stack, repo layout and conventions

Python for everything except the UI, which is TypeScript. One repo, one `uv` workspace.

**Stack:**

| Layer | Choice |
| --- | --- |
| Python | 3.12, `uv` workspace, `ruff` (lint + format), `pytest`, `pydantic` v2 |
| Database | PostgreSQL with TimescaleDB + pgvector on Tiger Cloud; `psycopg` 3; SQL migrations in `packages/core/migrations` |
| Detector | `tabpfn-client` (cloud, TabPFN-3.5) and `tabpfn` (local, on the GTX 1660); `tabpfn-extensions` for unsupervised anomaly detection; `pandas`, `pyarrow` |
| Models | Ollama: Gemma 4 E4B (agent), EmbeddingGemma (768-dim embeddings). Confirm exact Ollama tags. |
| Agent | Pydantic AI (Aun) |
| Workflows | Temporal Python SDK + Pydantic AI `TemporalAgent` (Aun) |
| API | FastAPI + SSE (Aun) |
| Web | Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts, `@sentry/nextjs` |
| Side services | ElevenLabs (TTS), SerpApi (Google search) |
| Hosting | Render (web + API demo), .tech domain |
| CI | GitHub Actions, QEMU for CHR |

**Repo layout:**

```
netcortex/
  apps/web/                 Next.js UI                         (Partner)
  services/api/             FastAPI                            (Aun)
  services/worker/          Temporal workflows + activities    (Aun)
  services/collector/       live collector                     (Aun)
  packages/core/            schemas, DB, migrations, settings  (Aun; partner reviews)
  packages/agent/           Pydantic AI agent + tools          (Aun)
  packages/fixes/           fix checker                        (Aun)
  packages/detector/        TabPFN detection                   (Partner)
  packages/runbook/         docs ingest + search               (Partner)
  packages/notify/          ElevenLabs + SerpApi               (Partner)
  packages/simgen/          simulator + data tools             (Partner)
  templates/routeros/       fix templates (YAML)               (Aun)
  data/                     small fixtures, sites.yaml, scenario catalog (Partner)
  eval/                     eval set + runner                  (Partner)
  experiments/tinker/       optional fine-tune                 (Partner)
  infra/                    docker-compose, chr/, render/      (Aun; render/ Partner)
  .github/workflows/        CI                                 (Partner)
  docs/                     PARTNER_PLAN.md, post drafts
  CLAUDE.md                 Aun's agent instructions
  AGENTS.md                 Partner's Codex instructions
```

**Conventions:**

- Every package imports schemas from `packages/core`. No package redefines a shared type.
- Every partner module has a `--mock` or fixture mode so it can be used before its real dependency is ready.
- Settings come from environment variables through one `Settings` class in `packages/core` (see section 8).
- Timestamps are UTC `timestamptz` everywhere. The UI shows Pakistan time (UTC+5).
- Large data (Parquet, raw downloads) goes in `data/raw/` and `data/generated/`, both in `.gitignore`. Only small fixtures are committed.
- Each package has a short README: what it does, how to run it, how to test it.

## 8. Shared contracts (draft, owned by Aun)

Both workstreams build against these. They are agreed in the first-hour call and merged as `packages/core`. After that, the code wins over this text.

### Database tables

All `time` columns are `timestamptz` (UTC). Tables marked hypertable use TimescaleDB.

```sql
sites(id text pk, name text, uplinks jsonb, targets jsonb, subscribers int, created_at timestamptz)

probe_metrics(time, site_id, target text, rtt_ms float, jitter_ms float, loss_pct float,
              source text)                                -- hypertable; source: live | sim | ripe

iface_metrics(time, site_id, iface text, rx_bps bigint, tx_bps bigint, util_pct float,
              drops bigint, errors bigint, source text)   -- hypertable

forecasts(time, site_id, series_key text, p10 float, p50 float, p90 float, model text)  -- hypertable

incidents(id uuid pk, site_id, opened_at, closed_at, status text, cause text,
          confidence float, detection jsonb, report jsonb, source text)
          -- status: open | awaiting_approval | applying | verifying | resolved | rolled_back | rejected

fix_plans(id uuid pk, incident_id uuid, template_id text, params jsonb, commands text,
          rollback text, dry_run_ok bool, dry_run_log text, decision text,
          decided_by text, decided_at timestamptz)

scenario_labels(id uuid pk, site_id, scenario_type text, start_at, end_at, affected jsonb,
                expected_cause text, expected_template text, expected_params jsonb,
                seed int, source text)

runbook_chunks(id uuid pk, source_url text, title text, section text, text text,
               embedding vector(768), embed_model text)
```

`series_key` format: `probe:<target>:rtt_ms`, `probe:<target>:loss_pct`, `iface:<iface>:util_pct`.

### Cause and template vocabulary

These strings are used by the simulator, detector, agent, eval and UI. Do not invent others.

- **Causes:** `uplink_congestion`, `heavy_user`, `upstream_degradation`, `game_route_issue`, `wireless_interference`, `uplink_down`, `dns_slow`, `normal`.
- **Fix templates:** `queue_limit` (limit one IP or subnet), `failover_route` (backup default route with `check-gateway=ping`), `priority_queue` (prioritise gaming and DNS traffic), `dns_servers` (switch DNS resolvers), `none` (no config fix; notify only).

### Partner module interfaces (Python)

Aun's agent and workflows call exactly these. Types live in `packages/core/schemas.py`.

```python
# packages/detector
def detect(site_id: str, window: MetricsWindow, history: MetricsWindow) -> DetectionResult: ...
# DetectionResult: is_anomaly: bool, score: float (0..1), series: list[SeriesForecast],
#   cause_guess: Cause, cause_confidence: float, evidence: list[str], model: str, mode: "cloud" | "local"

# packages/runbook
def search_runbook(query: str, k: int = 5) -> list[RunbookChunk]:  ...
# RunbookChunk: title, section, text, source_url, score

# packages/notify
def speak(text: str, lang: Literal["en", "ur"]) -> bytes: ...          # MP3 bytes
def check_news(provider: str | None, target: str | None) -> NewsCheck: ...
# NewsCheck: outage_reported: bool, summary: str, items: list[NewsItem(title, url, published)]

# packages/agent (Aun builds; partner's eval runner calls it)
async def investigate(site_id: str, detection: DetectionResult, window: MetricsWindow) -> IncidentReport: ...

# packages/simgen (also a CLI)
def inject(site_id: str, scenario_type: Cause, duration_min: int, seed: int | None) -> ScenarioLabel: ...
```

`MetricsWindow` is a pydantic wrapper around two pandas DataFrames (probe rows and interface rows) with the columns of the tables above.

### What the agent returns: `IncidentReport`

```text
summary: str                      # 1–2 sentences, plain English
likely_cause: Cause
confidence: float                 # 0..1
evidence: list[str]               # e.g. "uplink ether1 at 97% for 6 min"
upstream_check: NewsCheck | None
template_id: TemplateId
template_params: dict
customer_message_en: str
customer_message_ur: str
```

### API (Aun builds, UI consumes)

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/sites` | Sites with current health (`ok`, `degraded`, `down`) |
| GET | `/metrics?site_id&from&to&series` | Time series for charts, including forecast bands |
| GET | `/incidents?status` | Incident list, newest first |
| GET | `/incidents/{id}` | Incident, detection, report, fix plan, dry-run log, timeline |
| GET | `/incidents/{id}/voice` | MP3 voice alert |
| POST | `/incidents/{id}/approve` | Sends the Temporal approve signal |
| POST | `/incidents/{id}/reject` | Sends the Temporal reject signal |
| POST | `/demo/scenarios` | Body `{site_id, scenario_type, duration_min}` → injects a scenario |
| GET | `/stream` | SSE events: `metric`, `incident.opened`, `incident.updated`, `fix.tested`, `fix.applied` |

Aun publishes the OpenAPI JSON at `/openapi.json`. The partner generates TypeScript types from it (`openapi-typescript`).

### Environment variables (`.env.example`)

```
DATABASE_URL=
OLLAMA_BASE_URL=http://<mac-tailscale-name>:11434
AGENT_MODEL=<gemma 4 e4b tag>
EMBED_MODEL=<embeddinggemma tag>
TABPFN_MODE=cloud            # cloud | local
TABPFN_API_KEY=              # name per tabpfn-client docs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
SERPAPI_API_KEY=
SENTRY_DSN_BACKEND=
NEXT_PUBLIC_SENTRY_DSN=
NEXT_PUBLIC_API_BASE_URL=http://<laptop-tailscale-name>:8000
NEXT_PUBLIC_API_MODE=mock    # mock | live
TEMPORAL_ADDRESS=<laptop-tailscale-name>:7233
CHR_REST_URL=
DEMO_MODE=false
```

## 9. Partner tasks in detail

Do them in this order. Each task lists what it needs, what to build and when it counts as done.

### B1. Setup (first hour, during the contracts call)

- [ ] Install Tailscale and join Aun's tailnet. Check `curl http://<mac>:11434/api/tags` works.
- [ ] Install Entire and run `entire enable --agent codex` in the repo **before the first commit**.
- [ ] Install `uv`, Node LTS, Docker. Clone the repo.
- [ ] Get API keys: Prior Labs (accept the free non-commercial license at platform.priorlabs.ai), ElevenLabs, SerpApi. Claim the .tech domain and Render credits at hacktoberfest.com/my/promos.
- [ ] Install Ollama locally and pull EmbeddingGemma (same tag as Aun). Optional: install local `tabpfn` with CUDA and run its quick-start on the GTX 1660.
- [ ] Create `AGENTS.md` for Codex: point it to `docs/PARTNER_PLAN.md`, the folder ownership in section 7, and the rules in section 12.

**Done when:** Partner can reach Aun's Ollama and the shared database, and all keys are in a local `.env`.

### B2. Datasets and simulator

Full detail is in section 10. Summary:

- [ ] `simgen ripe` downloads RIPE Atlas ping results for probes in Pakistan → `source = ripe`.
- [ ] `simgen calibrate` computes baseline latency, jitter and loss per target type from RIPE data and Aun's live collector rows → `data/calibration.json`.
- [ ] `data/sites.yaml` and `data/scenarios.yaml` (scenario catalog).
- [ ] `simgen generate --days 7 --seed 42` → Parquet + `scenario_labels`.
- [ ] `simgen replay --speed 60` streams generated data into the database as if live.
- [ ] `simgen inject` (CLI and the `inject()` function the API calls).
- [ ] Eval set in `eval/cases/`.

**Done when:** Aun can run `simgen inject --site north-tower --type uplink_congestion` and see rows land in the database within seconds.

### B3. Detector (TabPFN)

Three jobs inside one `detect()`:

1. **Forecast.** For each key series (latency and loss per target, uplink utilisation), predict the next 1–5 minutes with p10/p50/p90 bands. Approach: build lag features (last N values, rolling mean and std, time-of-day, day-of-week, current utilisation) and use TabPFN regression with quantile output, or the TabPFN time-series package if it fits better. Check the Prior Labs docs and pick one.
2. **Anomaly score.** Use TabPFN's unsupervised anomaly detection (`tabpfn-extensions`) on a snapshot vector (utilisation, drops, errors, latency and loss across targets). Normalise to 0..1.
3. **Cause guess.** Train a TabPFN classifier on feature vectors from labelled simulator windows (`scenario_labels`). Output one of the cause strings plus confidence.

**Anomaly rule (tunable):** `is_anomaly` when a key series stays above its p90 for 3 points in a row **or** the anomaly score passes a threshold picked on the eval set.

**Practical rules:**

- Keep training context small (a few thousand rows). Cache fitted context per site.
- `TABPFN_MODE=cloud` uses `tabpfn-client` (TabPFN-3.5). `TABPFN_MODE=local` uses the local package on the GTX 1660. Same interface either way.
- Write each forecast to the `forecasts` table so the UI can draw bands.
- Fill `evidence` with short plain sentences ("uplink ether1 at 97% for 6 min").
- Report precision, recall and detection delay on the eval set in `eval/results/detector.md`.

**Done when:** `detect()` flags all injected incidents in a 7-day simulated run with few false alarms, and runs in under 5 seconds per site per call.

### B4. Docs search

- [ ] Download a small set of official MikroTik RouterOS help pages: queues (simple and queue tree), mangle, routing failover / `check-gateway`, DNS, interface monitoring. Respect the site's terms and robots rules. Save the source URL.
- [ ] Split into chunks of about 300–500 words, keeping section titles.
- [ ] Embed with EmbeddingGemma through Ollama. Store in `runbook_chunks` with `embed_model`.
- [ ] `search_runbook()`: vector search, plus keyword search if time allows (hybrid). Return top `k`.

**Done when:** queries like "limit bandwidth for one IP" and "failover default route" return the right page in the top 3.

### B5. Side modules

- [ ] `speak(text, lang)`: ElevenLabs text-to-speech, a multilingual model that supports Urdu. Return MP3 bytes. Keep text under \~40 words.
- [ ] `check_news(provider, target)`: SerpApi search for recent outage reports about the upstream provider or a game server, past 24 hours. Return a short summary and links.
- [ ] Both have a mock mode and a timeout. Failing services must never block an incident.

**Done when:** both work from a script, and both return safely when keys are missing.

### B6. Web UI

Build in mock mode first (`NEXT_PUBLIC_API_MODE=mock`, fixtures that follow the API in section 8). Switch to live once Aun's API is up. Mobile-first, dark mode included, Pakistan time on screen.

| Page | What it shows | Actions |
| --- | --- | --- |
| Overview | One card per site: health, uplink usage, worst latency now; a live chart of latency with the forecast band | Open a site or incident |
| Incident detail | Timeline; evidence charts; agent summary, cause and confidence; upstream news result; fix commands and rollback commands; CHR test result; voice alert player | Approve, Reject (with confirm) |
| Incidents | List, newest first, filter by status and site | Open |
| Demo panel | Scenario picker, site picker, duration | Inject scenario |
| Settings | Targets per site; switches for TabPFN cloud/local, ElevenLabs, SerpApi | Save |

- Live updates through the SSE `/stream`.
- Show the fix commands in a monospace block with a copy button. Never imply they were applied before approval.
- Add `@sentry/nextjs`.

**Done when:** the full approve flow works on a phone screen against the live API.

### B7. Hosted demo

- [ ] Point the .tech domain at Render.
- [ ] Render web service for the UI; Render web service for the API in `DEMO_MODE=true`.
- [ ] In demo mode, the API replays simulator data and serves saved agent reports from real runs (Render has no GPU for Gemma). Label this clearly on the page: "Demo: replayed data."
- [ ] Optional: during judging, point demo mode at Aun's Mac through a Tailscale Funnel or similar for live agent runs. Only if it's stable.

**Done when:** a stranger can open the .tech link and walk through an incident end to end.

### B8. CI and GitHub

- [ ] Workflow `ci.yml`: `ruff`, `pytest` for Python; lint, type-check and build for `apps/web`.
- [ ] Workflow `chr-templates.yml`: boot the CHR x86 image in QEMU on the runner, wait for the REST API, run Aun's `infra/chr/test_templates.py` against every template. The free CHR license (1 Mbps) is enough.
- [ ] Enable Copilot code review on PRs.

**Done when:** both workflows pass on `main`.

### B9. Eval runner

- [ ] `eval/run.py` loads each case, rebuilds its metrics window, calls `detect()` and then Aun's `investigate()` function.
- [ ] Scores: cause accuracy, template accuracy, valid params rate, CHR dry-run pass rate, time per case.
- [ ] Writes `eval/results/agent.md`. These numbers go in the post.

### B10. Tinker (optional, only after B1–B9 are working)

Tinker does not list Gemma, so this is a comparison, not a replacement. Fine-tune a small Qwen or Llama model on simulator cases (input: detection + evidence; output: cause + template + params). Compare with Gemma 4 E4B on the held-out eval set. Report accuracy, latency and cost.

### B11. Post

Draft in `docs/post/` from the +8 hour checkpoint: who pays and why, the data story (real Pakistani baselines + simulated incidents), why open models, the first user, the demo link. Aun writes the architecture, agent and safety sections.

## 10. Datasets

Use real data wherever a source exists, and seed the rest with a simulator calibrated on that real data. The coding agent (Codex or Claude) writes the **generators and scenario specs**, never the raw numbers: LLM-typed time series look fake and have no real structure.

### What we need and where it comes from

| Dataset | Columns / content | Real source | Seeded? | Output |
| --- | --- | --- | --- | --- |
| Ping results | time, site, target, latency, jitter, loss | Aun's live collector (from Sunday); RIPE Atlas public ping results for probes in Pakistan | Yes, simulator adds incidents | `probe_metrics` |
| Interface stats | time, site, interface, rx/tx, usage %, drops, errors | Rarely public at this detail | Yes | `iface_metrics` |
| Incident labels | scenario type, start/end, affected objects, expected cause, template, params | None | Yes | `scenario_labels` |
| Network layout | sites, uplinks, capacity, subscribers, targets | None | Yes, hand-written | `data/sites.yaml` |
| Docs for search | MikroTik RouterOS help pages | Official MikroTik docs | No | `runbook_chunks` |
| Eval set | 60–100 held-out cases with expected answers | None | Yes, different seeds | `eval/cases/` |
| Customer messages | Example English and Urdu messages per cause | None | Yes, agent-written examples | `data/messages.yaml` |
| Tinker training set (optional) | detection + evidence → cause + template + params | None | Yes, from simulator | `experiments/tinker/data/` |

Optional extra real source: M-Lab's open speed-test data (BigQuery) includes latency for Pakistani networks. Only use it if RIPE Atlas is not enough.

### RIPE Atlas (real baselines)

1. Find connected probes in Pakistan through the probes API (`/api/v2/probes/` filtered by country code `PK`). Note their network (ASN) to cover several ISPs.
2. Find public built-in ping measurements those probes take part in (for example, pings to root DNS servers). Do not hardcode measurement IDs; look them up through `/api/v2/measurements/`.
3. Download results through `/api/v2/measurements/<id>/results/` with `start`, `stop` and `probe_ids`. Results come as JSON; parse the RTT list per result into avg latency, jitter (std of RTTs) and loss (sent vs received).
4. Pull 7–14 days. Store as Parquet in `data/raw/ripe/` and load a sample into `probe_metrics` with `source = ripe`.
5. Be polite to the API: cache downloads, no tight loops.

### Calibration

`simgen calibrate` reads RIPE rows and Aun's `source = live` rows and writes `data/calibration.json`: per target type (gateway, upstream hop, public DNS, game server) the typical latency, jitter and loss by hour of day. The simulator starts from these values. This lets the post honestly say: "simulated incidents on top of real Pakistani network baselines."

### Network layout (`data/sites.yaml`)

3 sites, for example `north-tower`, `market-cafe`, `east-relay`. Each has: 1 primary uplink (capacity in Mbps), 0–1 backup uplink, 1–2 wireless backhaul links, 40–200 subscribers, and 5 ping targets (gateway, upstream hop, 1.1.1.1, 8.8.8.8, one regional game server).

### Simulator model

Time step: 10 s for pings, 30 s for interface stats.

- **Demand per subscriber:** a daily curve with a low overnight, a rise in the afternoon and a peak roughly 20:00–01:00 Pakistan time; a weekend boost; random noise; a few random heavy users.
- **Uplink usage** = total demand ÷ capacity.
- **Latency** = calibrated base + queueing delay that grows gently with usage and shoots up as usage nears 100% (a curve like `k × u / (1 − u)`, capped).
- **Loss** starts once usage passes about 95%; jitter grows with usage.
- **Noise:** small random spikes so normal data is not too clean.

### Scenario catalog (`data/scenarios.yaml`)

| Cause | What the data shows | Expected fix template |
| --- | --- | --- |
| `uplink_congestion` | Uplink usage above 95% for minutes; latency up on all outside targets; gateway fine | `priority_queue` |
| `heavy_user` | One subscriber IP takes a large share of the uplink; others slow down | `queue_limit` (that IP) |
| `upstream_degradation` | Gateway and usage normal; all outside targets slow or lossy | `none` (notify, check news) |
| `game_route_issue` | Only the game server target is bad | `none` (notify, check news) |
| `wireless_interference` | Loss and jitter on one backhaul link; usage normal | `none` (send a technician) |
| `uplink_down` | Primary uplink loss 100%; backup present | `failover_route` |
| `dns_slow` | DNS target slow; other targets fine | `dns_servers` |

Each injected scenario writes one `scenario_labels` row with the expected cause, template and params.

### Commands to build

```
simgen ripe --days 14                 # download RIPE Atlas data
simgen calibrate                      # write data/calibration.json
simgen generate --days 7 --seed 42    # Parquet + labels in data/generated/
simgen load --source sim --last 2d    # load a slice into the database
simgen replay --speed 60              # stream generated data as if live
simgen inject --site north-tower --type heavy_user --duration 15
simgen eval-cases --n 80 --seed 1000  # write eval/cases/
```

## 11. Timeline and checkpoints

Five phases, each ending in a gate both people check together on a short call. Hours count from the start of the contracts call on Sunday.

&#91;embedded content: Build timeline, 5 phases and 4 gates for both workstreams\]

Highlighted cells are the partner's. A gate is passed only when its line is true on Aun's laptop, not just on one machine.

**How to run the gates:**

- Each gate is a 10-minute call: demo what works, list what is blocked, re-plan the next phase.
- If a gate slips by more than an hour, cut scope using the order in section 13. Don't push the post later.
- Merge to `main` before every gate, so the integration host always runs the latest code.

## 12. Git workflow and rules for Codex

Small PRs, owned folders, and no surprise changes to shared code.

**Git:**

- `main` is protected. Work on short branches named `b/<task>` (partner) and `a/<task>` (Aun), for example `b/detector-forecast`.
- Merge through PRs. Copilot reviews every PR; the other person skims and approves. Aim to merge at least every 2 hours so integration never piles up.
- Commit early and often: Entire creates a checkpoint on each commit, and those sessions are linked in the post.
- Rebase on `main` before opening a PR.

**Rules for the Codex session:**

1. Only edit folders owned by Workstream B (section 7). To change anything else, open a PR comment or ask Aun.
2. Import shared types from `packages/core`. Never copy or redefine them.
3. Every module needs: a mock mode, a timeout on every network call, and tests with `pytest` (no network in unit tests; use recorded fixtures).
4. Never commit secrets, `.env`, raw downloads or generated Parquet.
5. Pin dependencies through `uv.lock` and `package-lock.json`.
6. Use only the cause and template strings from section 8.
7. Prefer boring, readable code over clever code. Judges and Aun will read it.
8. When something in this plan doesn't work as written (an API changed, a package is missing), choose the closest working option, write it down in the PR, and continue.
9. Write a short README for every package you create.
10. Keep a running `docs/post/notes.md` of interesting findings and numbers. The post needs them.

## 13. Risks, fallbacks and definition of done

The project is complete when a stranger can open the demo, inject an incident, read the agent's explanation, see a tested fix, approve it, and read a post that explains why open models made it possible.

**Risks and fallbacks:**

| Risk | Fallback |
| --- | --- |
| Tailscale can't connect the two networks | Partner runs Ollama locally (Gemma 4 E2B, or E4B if it fits); integration happens on Aun's laptop only |
| TabPFN cloud is slow or rate-limited | Switch to `TABPFN_MODE=local` on the GTX 1660; reduce context rows |
| TabPFN forecasting too weak on some series | Keep the forecast for latency and usage; rely more on the anomaly score for loss |
| RIPE Atlas data is thin for Pakistan | Use Aun's live data + sensible defaults; mention it in the post |
| Gemma picks wrong templates | Narrow the agent: pass the detector's cause guess and only the templates allowed for that cause |
| CHR won't boot in GitHub Actions | Keep CHR tests on Aun's laptop; CI runs unit tests only; note it in the README |
| Render demo can't run Gemma | Saved reports from real runs, clearly labelled |
| Tiger Cloud storage fills up | Load fewer days; keep the rest in Parquet |
| Running out of time | Cut in this order: Tinker → Settings page → hybrid search → live agent in hosted demo. Never cut the post. |

**Definition of done for Workstream B:**

- [ ] RIPE Atlas data downloaded and calibration written
- [ ] Simulator generates, replays and injects all 7 scenarios with labels
- [ ] `detect()` passes on the eval set, results in `eval/results/detector.md`
- [ ] `search_runbook()` returns the right docs for the 4 template topics
- [ ] `speak()` and `check_news()` work and fail safely
- [ ] Web UI: full approve flow works live on a phone
- [ ] Hosted demo live on the .tech domain
- [ ] CI green; Copilot review enabled
- [ ] Agent eval numbers in `eval/results/agent.md`
- [ ] Post sections drafted, first-user story written
