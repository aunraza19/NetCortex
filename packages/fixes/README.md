# netcortex-fixes

RouterOS fix templates are the only source of router commands in NetCortex. The agent
picks a template and fills in its params. This package checks those params and renders the
commands.

```python
import netcortex_fixes as fixes

fixes.templates_for("heavy_user")  # [queue_limit, none]
fixes.validate("queue_limit", params, observed)  # normalised params, or ParamError
apply, rollback = fixes.render("queue_limit", params)
```

## Templates (`templates/routeros/*.yaml`)

| id | For cause | Does |
| --- | --- | --- |
| `queue_limit` | `heavy_user` | Simple queue capping one IP or subnet |
| `failover_route` | `uplink_down` | Backup default route; `check-gateway=ping` on the primary |
| `priority_queue` | `uplink_congestion` | Mangle marks DNS and game UDP; queue tree gives them priority 1 |
| `dns_servers` | `dns_slow` | Switch `/ip dns` servers and flush the cache |
| `none` (built-in) | any | No commands; notify only |

Each file has `id`, `description`, `allowed_causes`, typed `params`, `apply` and `rollback`
(Jinja), and `verify` (which metric must move and by how much). All four are marked
**untested on CHR** until the CHR dry run (A4/A6) has passed them.

## Safety

- Every param has a type:
  - `ipv4`, `ipv4_or_cidr` and `ipv4_list` are checked with `ipaddress`.
  - `int` has bounds.
  - `str` must fully match a strict regex.
- Unknown or missing params are rejected.
- Rendering uses a sandboxed Jinja environment with `StrictUndefined`, so only validated
  values reach the commands.
- Templates can name **checks** against live observations (`checks.py`). These run when
  the caller passes `observed=`.
  - `queue_limit` uses `cap_below_current_rate`: in the subscriber's busier direction, the
    cap must be at most 50% of its current rate.
  - A subscriber using under 2 Mbit/s can't be capped at all.
  - The error names the allowed maximum (for example "at most 67"), so the agent's retry
    can fix it.
- Params marked `set_by: router` (for example `dns_servers.previous_servers`) are filled in
  by the fix checker from the router, never by the agent.

```bash
uv run pytest packages/fixes
```
