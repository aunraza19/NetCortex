# Retrieval and news handoff

Superseded by [core integration](core_news_ui.md). The original independent
packages were integrated before core was available. Public functions now import
actual core models and Settings. The accepted embedding name is exactly
embeddinggemma; the former full-tag prerequisite is removed.

News uses SerpApi and returns NewsCheck, preserving available=False. Retrieval
uses official source URLs, checked 768-dimensional embeddings and cosine
similarity. Runtime credentials are SecretStr and are unwrapped only at the
network/database boundary. Tests use mocked providers and Settings(_env_file=None).
English and Urdu customer messages are text. No speech generation remains.

Live provider/database retrieval quality remains separate from offline tests.
