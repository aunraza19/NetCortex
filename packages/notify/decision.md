# Notification design decisions

Voice uses ElevenLabs' HTTP text-to-speech endpoint with `eleven_v3`. Current official model documentation lists Urdu for v3; the API reference says `language_code` is unsupported by `eleven_multilingual_v2`, so v2 is not selected. The MP3 `output_format` is an endpoint query parameter. English and Urdu are the only accepted language values, and alerts are limited to 40 words.

Missing voice credentials produce empty bytes. Provider timeouts, HTTP failures, rate limits, and malformed audio are logged by exception class only and produce empty bytes in the public `speak()` wrapper so an incident alert does not wait on voice. Input validation and missing shared Settings remain explicit errors. The internal adapter retains provider errors so tests and callers can inspect them.

SerpApi Google Search uses `tbs=qdr:d`; returned relative or ISO dates are checked against a 24-hour window. A result must have an absolute HTTP(S) URL without embedded credentials. Recent results alone do not assert an outage: text must mention a supplied provider or target and contain outage language. Search text remains untrusted evidence and the summary asks the operator to verify. No HTML or result content is fetched.

Missing news credentials, timeout, rate limit, provider/API error, malformed JSON, or malformed result structure returns an explicit unavailable summary. A valid search with no qualifying recent links is a successful check with a distinct no-reports summary. The shared draft `NewsCheck` carries `outage_reported`, `summary`, and `items`; unavailable state is spelled out in the summary while `outage_reported` remains false.

Internal adapters accept explicit credentials and injected `httpx.Client` instances. Public functions read only the eventual `netcortex_core.Settings` and return Aun's shared schemas. There is no package-local Settings class or environment-variable fallback. Fixture commands make no HTTP calls and cannot claim real provider results.
