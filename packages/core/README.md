# netcortex-core

Shared contracts for every NetCortex package. Import from here; never redefine these types.

```python
from netcortex_core import Cause, DetectionResult, MetricsWindow, Settings, get_settings
```

| Module | What it holds |
| --- | --- |
| `schemas.py` | `Cause`, `TemplateId`, `IncidentStatus`, metric rows, `MetricsWindow`, `DetectionResult`, `RunbookChunk`, `NewsCheck`, `ScenarioLabel`, `IncidentReport`, `FixPlan`, `Incident`, `Event`, `Site`, series-key helpers |
| `settings.py` | `Settings`: one field per env var, lowercase (`DATABASE_URL` -> `database_url`). Secrets are `SecretStr`. |
| `interfaces.py` | `Protocol`s for `detect`, `search_runbook`, `speak`, `check_news`, `inject`, `investigate`; `ModuleUnavailable`; `conforms()` for tests |
| `db.py` | psycopg 3 pool (`get_pool()`) and insert helpers for metrics, forecasts, incidents and events |
| `migrations/` | SQL migrations, applied by `netcortex-migrate` |

## Conventions

- Times are timezone-aware UTC. `MetricsWindow` rejects naive `as_of`.
- `probe_metrics.rtt_ms` is the response time: ICMP round trip, or DNS lookup time when
  `kind = 'dns'`. DNS targets use keys like `dns:1.1.1.1`. `rtt_ms` is NULL on total loss.
- Series keys: `probe:<target>:<metric>`, `iface:<iface>:<metric>`, `subscriber:<ip>:<metric>`.
  Use `series_key()` / `parse_series_key()`; target names may contain colons.
- Failure rules for modules are in the `interfaces.py` docstring.

## Database

```bash
uv run netcortex-migrate          # apply pending migrations to DATABASE_URL (safe to re-run)
uv run netcortex-migrate --list   # list bundled migrations, no connection
```

It reads `DATABASE_URL` through `Settings` (from `.env`) and never prints it.

## Tests

```bash
uv run pytest packages/core
```

Unit tests only, with no network and no `.env`.
