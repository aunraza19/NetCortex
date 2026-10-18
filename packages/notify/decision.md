# Decisions

News uses SerpApi Google search with a one-day filter. Missing credentials, timeouts, provider errors, malformed JSON, and malformed result structures return the shared `NewsCheck` with `available=False`; they never claim no outage. Valid searches with no qualifying recent links return `available=True`, `outage_reported=False`. SerpApi relative dates are normalized to timezone-aware UTC datetimes before creating core `NewsItem` objects.

The public function imports the actual core `Settings`, `NewsCheck`, and `NewsItem` contracts. It unwraps `SecretStr` only when passing the SerpApi key to the HTTP request. The internal helper takes explicit credentials and an injectable `httpx.Client`, so tests stay offline. Fixture CLI commands make no HTTP calls and cannot claim a provider was checked.
