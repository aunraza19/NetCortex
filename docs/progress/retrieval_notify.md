# B4/B5 runbook and notifications handoff

## Owned files delivered

- `packages/runbook/`: hatchling package `netcortex-runbook` / `netcortex_runbook`, official-doc ingestion, vector search adapter, fixture CLI, unit tests, README, decision guide, and flow guide.
- `packages/notify/`: hatchling package `netcortex-notify` / `netcortex_notify`, ElevenLabs and SerpApi helpers, unavailable-only fixture CLI, unit tests, README, decision guide, and flow guide.
- This handoff.

No core schema, Settings, root manifest, lockfile, or other team-owned file was changed. No credentials, live embedding calls, database writes, TTS calls, or SerpApi calls were used.

## Checks run

Command:

```powershell
python -m uv run --with-editable packages/runbook --with-editable packages/notify --with pytest pytest packages/runbook/tests packages/notify/tests
```

Result: **18 passed** on Python 3.12.0. These are offline unit tests using `httpx.MockTransport` and fixture data. Coverage includes four fixture topics with source metadata plus a canonical six-page allowlist/crawl-delay policy test, chunk boundaries, EmbeddingGemma identity/dimension/non-finite values, robots denial, model-specific idempotent persistence, body deadline, voice language/word validation, MP3 response, output-format query, voice rate limit and public failure handling, absent credentials, malformed news payloads, unsafe links, date filtering, outage relevance, and SerpApi rate limit/timeout.

The smoke CLIs were run:

```powershell
python -m uv run --with-editable packages/runbook runbook fixture "failover default route" --mock
python -m uv run --with-editable packages/notify notify speak "Uplink is degraded" --lang ur --mock
python -m uv run --with-editable packages/notify notify news ExampleISP game-server --mock
```

Runbook returned source-linked `fixture=true` excerpts with source titles and retrieval date. Notification fixtures returned unavailable outputs and made no provider calls.

Ruff formatting and checks passed against `C:\Users\nigga\Documents\NetCortex\pyproject.toml` (Python 3.12, E/F/I/UP/B rules, 100-character lines). `git diff --check` passed. `uv build --wheel` built both distributions successfully. The ignored wheel outputs remain under each package's `.build-check` folder because cleanup commands were blocked by the execution policy.

## Decisions and live gates

- Official RouterOS sources are restricted to six canonical `help.mikrotik.com` pages: queues, route, failover, DNS, mangle, and interface stats/traffic. A one-time live source validation on 2026-10-18 got `robots.txt` HTTP 200 with `Crawl-delay: 5`; all six canonical pages returned HTTP 200 with expected titles. The indexer reads robots once, checks each URL, and honors its parsed delay between page fetches. The page fetches were not retained as a raw corpus. Responses stream with a 2 MB cap and finite HTTP timeouts.
- No Ollama tag is guessed. The shared configured value must be a full `embeddinggemma:<tag>`; responses are checked for exact identity and 768 finite dimensions. Aun still must confirm the shared tag and Settings fields before public search can use `netcortex_core`.
- Chunking targets 400 words, accepts a target from 300 through 500, balances page remainder, and preserves headings in section metadata. Source pages were validated but no raw corpus was retained.
- Existing `runbook_chunks` schema has no content uniqueness key. Indexing therefore takes a PostgreSQL transaction advisory lock and selects by source/title/section/text/model before inserting; the schema is not changed. A model change keeps a distinct embedding row. The database write path has not been exercised against PostgreSQL.
- Vector-only pgvector cosine search returns Aun's `RunbookChunk` objects and source URLs. Search quality is not measured until the shared DB/model is available.
- ElevenLabs `eleven_v3` was chosen because its current official model docs list Urdu; `eleven_multilingual_v2` does not support the API language-code parameter. MP3 format is an API query parameter. SerpApi Google search uses `tbs=qdr:d`; result dates, relevant outage wording, and HTTP(S) URLs are checked. These API/model choices are recorded in package docs.
- Public functions are contract-gated: `search_runbook` needs core `Settings` and `RunbookChunk`; `speak` needs core `Settings`; `check_news` needs core `Settings`, `NewsCheck`, and `NewsItem`. Internal functions support passed config and injected clients. There are no copied shared types or alternate Settings classes.

Pending before integration claims: Aun publishes the core package/schema/settings fields and confirms the EmbeddingGemma tag; a real test database and Ollama host are available; run ingestion twice and verify idempotence; run all four retrieval topics and verify correct top-three hits; test real Urdu/English MP3 playback and SerpApi known/empty/error cases. No external integration or real retrieval/voice/news pass is claimed.
