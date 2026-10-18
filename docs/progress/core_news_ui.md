# Core news, runbook, and UI integration

Implemented the shared core boundary for news and runbook search. News returns the real `NewsCheck` and `NewsItem` schemas, keeps provider failures unavailable, and normalizes relative SerpApi dates to aware UTC datetimes. Runbook imports actual `Settings`, `RunbookChunk`, and `ModuleUnavailable`; it accepts the shared bare `embeddinggemma` name, validates 768 finite dimensions, unwraps database `SecretStr` at psycopg use, and returns cosine similarity scores.

Removed voice exports, CLI commands, provider code and tests, web audio route/player/request, and related styles. English and Urdu customer messages remain text. Updated package and app README, decision, and flow documents.

Validation: notify and runbook existing plus lead acceptance tests passed (20 tests). Web lint, typecheck, production build, Prettier check, and all 17 browser tests passed (14 dashboard and 3 live-mode tests). Live SerpApi, Ollama, and database checks were not run. The worker used the existing `.venv` interpreter; the lead also reran through `python -m uv` with the regenerated locked workspace.
