# netcortex-collector

Probes the home-lab network around the clock and writes `source = live` rows for
`SITE_ID_LIVE` (default `home-lab`). The partner's calibration uses these rows.

```bash
uv run collector                  # run until Ctrl+C
uv run collector --dry-run        # print rows, don't touch the database
uv run collector --duration 120   # stop after two minutes
```

**At startup** it runs the system traceroute (`tracert -d` on Windows) towards the first
public target. Hop 1 is the gateway and hop 2 is the upstream hop. Override them with
`COLLECTOR_GATEWAY` / `COLLECTOR_UPSTREAM_HOP`. The site's targets are saved to `sites`.

**Every 10 s**, for every target at once:

| Target | Probe | Row |
| --- | --- | --- |
| gateway, upstream hop, 1.1.1.1, 8.8.8.8, `COLLECTOR_GAME_SERVER` | 5 ICMP echoes (icmplib, unprivileged: no admin needed) | `kind = icmp`, target = the IP |
| resolvers 1.1.1.1 and 8.8.8.8 | 5 DNS A lookups of `COLLECTOR_DNS_QUERY` with a 2 s timeout | `kind = dns`, target = `dns:<resolver>` |

Each row has `rtt_ms` (average), `jitter_ms` (standard deviation) and `loss_pct`.
`rtt_ms` is NULL when every attempt was lost.

**Router stats** (`COLLECTOR_ROUTER_STATS=true` plus `CHR_REST_URL`, `CHR_USERNAME` and
`CHR_PASSWORD`): every 30 s it reads `/rest/interface` and `/rest/queue/simple`. It writes
`iface_metrics` (bits/s; drops and errors counted during the interval) and
`subscriber_metrics` (one row per `/32` simple queue).

**Errors:**
- A probe that crashes is skipped, never reported as 100% loss.
- A round that fails (for example, the database is down) is logged and skipped.
- Database errors are logged by type only, so the host never appears in logs.

```bash
uv run pytest services/collector   # unit tests, no network
```
