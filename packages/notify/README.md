# netcortex-notify

` speak(text, lang)` generates a short MP3 through ElevenLabs `eleven_v3`, which lists Urdu support. ElevenLabs documents that `eleven_multilingual_v2` does not support `language_code`, so it is not selected. Missing voice credentials return empty bytes to represent unavailable voice; HTTP failures and rate limits remain errors.

`check_news(provider, target)` uses SerpApi Google search with `tbs=qdr:d`, then validates result shape, relative/ISO dates, and safe HTTP(S) URLs. A failed lookup produces `available: false` explicitly and never claims there was no outage. The public functions await Aun's `netcortex_core.Settings` and `NewsCheck` contract. Internal helpers accept passed credentials and are usable offline without shadow settings.

Fixture examples: `python -m netcortex_notify.cli speak "Uplink is degraded" --lang en --mock` and `python -m netcortex_notify.cli news ExampleISP game-server --mock`. They only report unavailable fixtures and make no network requests. `live-speak` and `live-news` invoke the public core-gated functions.

Live smoke steps: configure test credentials through the eventual core Settings, make one short English and one Urdu alert and verify MP3 playback, then query a known provider and target. Exercise missing keys and rate limits separately. No live credentials or external calls were used on this branch.
