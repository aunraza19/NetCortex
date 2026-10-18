# Decisions

Search uses pgvector cosine distance and returns the actual core `RunbookChunk` schema with higher-is-better `score=1-distance`. No keyword fallback is used, so an empty list means no matching rows. The package imports `Settings`, `RunbookChunk`, and `ModuleUnavailable` directly from core.

`EMBED_MODEL=embeddinggemma` is the shared default and is sent unchanged to Ollama. Ollama's equivalent response alias `embeddinggemma:latest` is accepted only for that bare requested model; a different model or tag fails explicitly. Every returned vector must have 768 finite numeric dimensions.

Database credentials are unwrapped from `SecretStr` only at the psycopg connection boundary. Provider, database, and model failures from live search raise `ModuleUnavailable` with exception details suppressed to the class name, so credentials in driver messages are not surfaced.
