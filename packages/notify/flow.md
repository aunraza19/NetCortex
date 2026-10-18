# Notification execution flow

## Entry points

- `python -m netcortex_notify.cli speak "Uplink is degraded" --lang en --mock` runs the offline unavailable-voice fixture.
- `python -m netcortex_notify.cli news ExampleISP game-server --mock` runs the offline unavailable-news fixture.
- `netcortex_notify.speak(text, lang)` is the public live voice function; it awaits `netcortex_core.Settings` fields `elevenlabs_api_key` and `elevenlabs_voice_id`.
- `netcortex_notify.check_news(provider, target)` is the public live search function; it awaits `Settings.serpapi_api_key` and core `NewsCheck` and `NewsItem` exports.
- Internal `_speak` and `_check_news` accept explicit credentials and optional injected `httpx.Client`; tests use `httpx.MockTransport` and do not access a network.

## Voice path

```mermaid
flowchart TD
  A[text + en/ur] --> B{1-40 words?}
  B -->|No| C[ValueError]
  B -->|Yes| D{Key and voice ID?}
  D -->|No| E[Return empty bytes: unavailable]
  D -->|Yes| F[POST api.elevenlabs.io/v1/text-to-speech/{voice_id}]
  F --> G[eleven_v3 + language_code + MP3 format]
  G --> H[HTTP/status/content validation]
  H --> I[MP3 bytes]
```

The call uses finite connection and per-operation timeouts plus a 12-second response-body deadline and 1 MB body cap, with no automatic retry or redirects. MP3 format is sent as the endpoint's `output_format` query parameter. The public wrapper catches provider/time-limit/audio-response failures, logs only the exception class, and returns empty bytes so alerts do not block an incident. Invalid caller inputs and missing core Settings still fail explicitly. The fixture path supplies no keys and sends no HTTP request.

## News path

The helper accepts optional provider and target values; both absent returns an unavailable result without a request. Otherwise it calls `https://serpapi.com/search.json` with Google engine, available query terms, `tbs=qdr:d`, and the passed API key. The key is sent as a request parameter per SerpApi's API contract and must never be logged. Result items are parsed defensively from a streamed response capped at 1 MB with an 8-second body deadline and finite connection/per-operation timeouts. Only recent (relative or ISO) dates and absolute safe HTTP(S) URLs survive. Up to five items are returned with title, URL, and published date. `outage_reported` requires supplied provider/target text and outage wording; recent dates alone do not assert an outage. Valid zero results produce a successful no-reports summary; any unavailable or malformed call returns `available=false` internally and an explicit unavailable summary. Public output is constructed from Aun's actual core `NewsItem` and `NewsCheck` types; no local schema is defined.

Core imports are delayed until the public live entry point is called. Until the shared package and field names are published, those functions raise a clear `RuntimeError`. Fixture CLI outputs are dictionaries, visibly marked as fixture/unavailable, and never claim a provider was checked or an outage was confirmed.
