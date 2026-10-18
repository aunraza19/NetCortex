# Flow

`python -m netcortex_notify.cli news ExampleISP game-server --mock` runs an offline unavailable-news fixture. `python -m netcortex_notify.cli live-news ExampleISP game-server` invokes the public live search.

`netcortex_notify.check_news(provider, target)` reads shared `Settings.serpapi_api_key` and returns core `NewsCheck` and `NewsItem` objects. The secret is unwrapped only when passed to SerpApi. `_check_news` accepts explicit credentials and an optional injected `httpx.Client`; tests use `httpx.MockTransport` and make no network calls.

The helper calls SerpApi Google search with a one-day filter, a finite connection and request timeout, an 8-second response deadline, and a 1 MB body cap. It retains only safe absolute HTTP(S) URLs with recent dates, up to five items. Relative or ISO dates become aware UTC datetimes before constructing `NewsItem`. Outage wording alone does not mark an outage: the supplied provider or target must also appear in the result. A valid empty search is available with no outage claim. Missing credentials, timeouts, provider errors, malformed JSON, or malformed result structures return `available=False` with an explicit unavailable summary.

Core contracts are imported directly from `netcortex_core`; there are no local copies or runtime discovery. Fixture CLI output is marked unavailable and makes no HTTP call.
