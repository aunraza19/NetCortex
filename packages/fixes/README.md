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
(Jinja), and `verify` (which metric must move and by how much). All four are
marked **tested on CHR (RouterOS 7.24.5)**.

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

## Dry run and apply (CHR only)

```python
plan = fixes.check_fix(incident_id, "queue_limit", params)  # dry-run on CHR, stored in fix_plans
fixes.apply(plan)  # only if plan.decision == "approved" and plan.dry_run_ok
fixes.rollback(plan)
```

`dry_run` exports the config, applies the commands, exports again and diffs, rolls back, and
checks the config is exactly the original. It passes only if all four steps hold.
Router-filled params, such as the DNS servers before the change, are read from CHR first.

- `RouterClient` talks REST to `CHR_REST_URL` and runs one command line per
  `POST /rest/execute`, so a failure names the line.
- `apply` and `rollback` refuse anything but `APPLY_TARGET=chr`.

All four templates pass on CHR 7.24.5 (`infra/chr/test_templates.py`).

```bash
uv run pytest packages/fixes            # unit tests with a fake router
uv run pytest -m live packages/fixes    # against the running CHR
```
