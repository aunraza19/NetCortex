# Notifications

`check_news(provider, target)` checks recent provider outage reports through SerpApi and returns the shared core `NewsCheck` schema. Unavailable searches set `available: false` and never claim that no outage exists. Relative search dates are converted to timezone-aware datetimes. The package imports actual `netcortex_core` contracts and unwraps the SerpApi `SecretStr` only at the HTTP boundary.

Offline fixture: `python -m netcortex_notify.cli news ExampleISP game-server --mock`. Live command: `python -m netcortex_notify.cli live-news ExampleISP game-server`. Tests use mocked HTTP responses and do not require credentials. Network timeouts and response size are bounded.
