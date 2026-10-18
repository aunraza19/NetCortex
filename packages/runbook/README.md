# netcortex-runbook

Official MikroTik RouterOS documentation ingestion and pgvector retrieval. The ingestion allowlist is limited to `help.mikrotik.com`, checks `robots.txt`, uses finite HTTP/database timeouts, caps downloads at 2 MB, and chunks source text with headings. The ingest transaction takes an advisory lock and checks approved content columns before inserting, because the shared schema has no natural uniqueness constraint. It does not change the shared schema.

The exact Ollama model must be passed/configured as a full `embeddinggemma:<tag>` value. No default tag is guessed while Aun's shared tag decision is pending. Ingestion and search reject a different returned model and any embedding dimension other than 768. Search ranks by vector distance only.

Offline illustration (fixture excerpts link to official pages and do not use EmbeddingGemma): `python -m netcortex_runbook.cli fixture "failover default route" --mock`. This CLI labels every item as a fixture and includes source titles and retrieval date. Live `search_runbook(query, k=5)` awaits Aun's `netcortex_core.Settings` and `RunbookChunk` exports; it fails explicitly until those exist. Live CLI operations are `runbook search QUERY` and `runbook ingest`; both consume only shared core Settings.

Live smoke steps: provision approved core/schema and an isolated database; run Ollama with the agreed exact EmbeddingGemma tag; call `ingest`; repeat it and check row count is unchanged; query each of the four topics in the validation plan and verify the right page in top three. Those live checks have not been run on this branch.
