# Partner technology audit (19 Oct 2026, before the post)

What each partner technology does in the local demo, with the evidence. LIVE = it does
real work in the demo path. STUBBED = wired in, but returns nothing useful today.
NOT USED = not in the running system.

| Technology | Status | Evidence |
|---|---|---|
| Gemma 4 E4B (agent) | LIVE | Ollama on the Mac mini; `check_ollama.py` passes. Every incident's report comes from it: 5 `gen_ai.chat` spans in trace `1ffec884...` with token counts. 10/11 valid reports with the right template and params (`packages/agent/scripts/reliability.py`). |
| EmbeddingGemma + pgvector (runbook search) | STUBBED | Model present (768-dim embeddings, `check_ollama.py`); `vector` 0.8.7 extension installed; `runbook_chunks` table exists but has **0 rows**. The partner's `search_runbook()` is the one the agent calls, and it returns `[]`. The partner's README: "No live ingestion or search has been run." |
| TabPFN (second opinion) | NOT USED in the demo | No `TABPFN_TOKEN`, no `DETECTOR_ARTIFACT`; `forecasts` holds only `rules-v0` rows; 0 incident reports carry TabPFN evidence. Never answered a real incident. One bounded cloud smoke by the partner (`eval/results/gate2.md`): plumbing worked, predicted `uplink_down` for an `uplink_congestion` injection, setup 271.7 s, detection 114.8 s. |
| Temporal | LIVE | `MonitorSiteWorkflow` per site, `IncidentWorkflow` per incident (Pydantic AI `TemporalAgent`: model calls and tool calls are activities). Dev server holds 25 workflow runs, 17 incident workflows. Approve/reject are Temporal signals. |
| Sentry | LIVE | Project `netcortex-backend`. One trace per incident (trace ID = incident ID). `gen_ai.chat` spans with model and input/output tokens (trace `1ffec8847bc44c8f89a8b0b66a04e4f3`: input 1,136-1,879, output 16-238). The real rollback is trace `5837ffbbe394489280260f42a5c969e4`. |
| Tiger Data (TimescaleDB) | LIVE | Tiger Cloud, `timescaledb` 2.30.2. Hypertables: `probe_metrics`, `iface_metrics`, `subscriber_metrics`, `forecasts`. 12,478 live probe rows from the home collector (7 targets) plus simulated rows; events table with NOTIFY feeds the dashboard. pgvector: installed, unused (see runbook). |
| SerpApi (`check_news`) | STUBBED | No `SERPAPI_API_KEY`. The partner's `check_news()` is the one the agent calls; it returns `available: false, "SerpApi key is not configured"`. 0 incidents have a real news check. |
| Entire | LIVE | 42 `refs/entire/checkpoints/*` on GitHub; 42 of Aun's commits carry an `Entire-Checkpoint` trailer. The partner's commits (made with Codex) have none. |
| GitHub Actions | LIVE | 61 runs. `CI` (ruff + pytest on every package) and `CHR template integration`, which installs QEMU on the runner, boots CHR, and runs `infra/chr/test_templates.py` (apply, read back, roll back) on each PR; last runs passed. Copilot PR review: no evidence, don't claim it. |
| Render, .tech domain | NOT USED | Removed (`infra/render` deleted); local demo only. |
| Tinker | NOT USED | Optional; never started. |
| ElevenLabs | NOT USED | Voice dropped (migration `002_drop_voice`). |

## Turning on the stubbed ones

| Technology | What to do | Time | Risk |
|---|---|---|---|
| SerpApi | Create a free SerpApi account, put `SERPAPI_API_KEY` in `.env`, restart the worker. | 5-10 min | Low. Each incident uses one search from the free quota. |
| Runbook search | Run the partner's `runbook ingest` (fetches the approved MikroTik pages, embeds with EmbeddingGemma on the Mac, writes `runbook_chunks`), then `runbook search "simple queue max-limit"` to check. | 20-40 min | Medium: the ingest has never been run, so expect fixes. |
| TabPFN second opinion | Get a Prior Labs token, generate eval cases (`netcortex-simgen eval-cases`), build the artifact (`prepare_detector`), set `TABPFN_TOKEN` and `DETECTOR_ARTIFACT`, restart. Each incident then waits up to ~2 min for it. | 45-90 min | High: 115 s per detection, wrong cause in its only test; sends metrics to Prior Labs; free licence is non-commercial. Not worth it before the deadline. |
