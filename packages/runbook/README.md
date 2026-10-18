# Runbook retrieval

Offline example: `python -m netcortex_runbook.cli fixture "failover default route" --mock`. Fixture excerpts are marked and do not use EmbeddingGemma. Live `runbook search QUERY` embeds through Ollama and queries pgvector; `runbook ingest` fetches approved MikroTik documentation and indexes it. Both use the actual core `Settings` and require a database URL and Ollama service. Search returns core `RunbookChunk` objects with cosine similarity scores (`1 - distance`); failures raise `ModuleUnavailable`.

The shared model is `EMBED_MODEL=embeddinggemma`, with 768 dimensional vectors. Search embeds the query before accessing the database. No live ingestion or search has been run on this branch.
