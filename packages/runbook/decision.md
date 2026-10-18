# Runbook design decisions

The indexer reads only official MikroTik RouterOS pages from `help.mikrotik.com`. It checks that host's `robots.txt`, rejects redirects outside the official HTTPS host, and caps each page at 2 MB while streaming. The source set is finite: queues, route, failover, DNS, mangle, and interface stats/traffic. Every HTTP request has finite connect/read/write/pool timeouts. The indexer honors the crawl delay advertised by robots.txt between page fetches.

Chunking targets 400 words and accepts configured sizes only from 300 through 500. Section titles remain in metadata. The vector model is supplied explicitly from the approved shared Settings; there is no guessed default while Aun's exact model tag decision is pending. The configured value must be a full `embeddinggemma:<tag>`, and Ollama's returned model must match it exactly. Every vector must contain 768 finite numbers.

The current `runbook_chunks` schema has no natural unique key. Indexing therefore takes a transaction-scoped advisory lock and selects by source URL, title, section, text, and model before inserting. The model is part of the key so an approved model change cannot silently reuse the old embedding. Writes use only the shared columns; this package does not alter the schema. PostgreSQL connection and statement deadlines are both finite.

Search uses pgvector cosine distance only. Keyword fallback is omitted so the order and score remain clear. Results are instantiated as Aun's `RunbookChunk` with source URL and higher-is-better score `1 - distance`. No local copy of that schema is defined. Live search waits for Aun's `netcortex_core.Settings` and `RunbookChunk` exports and fields.

Fixture excerpts are manually written, source-linked paraphrases checked against official MikroTik docs. Each has source title, retrieval date, and `fixture=true`. They are lexical examples only; no model vectors are used and their tests do not establish live search quality.
