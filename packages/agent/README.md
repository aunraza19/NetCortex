# netcortex-agent

The incident investigator. It's a Pydantic AI agent running on local Gemma (`AGENT_MODEL`
through Ollama's OpenAI-compatible API at `OLLAMA_BASE_URL/v1`), and it returns an
`IncidentReport`.

```python
from netcortex_agent.agent import investigate

report = await investigate(site_id, detection, window)  # netcortex_core.Investigate
```

## How it works

1. **Prompt:** the site's uplinks and gateways, the detector's guess and evidence, and the
   list of series the model can query.
2. **Tools:**

   | Tool | What it does |
   | --- | --- |
   | `get_metrics(series, minutes)` | Summary of one series from the window |
   | `get_forecast(series)` | The detector's p10/p50/p90 bands |
   | `list_templates(cause)` | The templates allowed for that cause, plus `none`, with their param schemas |
   | `search_runbook(query)` | MikroTik docs |
   | `check_news(provider, target)` | Outage news |

   `search_runbook` and `check_news` use the stubs in `stubs.py` until `packages/runbook`
   and `packages/notify` are installed; `modules.py` then switches to the real ones
   automatically.
3. **Output check:** the template must be allowed for the report's cause, and its params
   must pass `netcortex_fixes.validate`.
   - The error, including the template's full param schema, goes back to the model once.
   - If the second try also fails, the report falls back to template `none`, with the
     detector's cause and a confidence of at most 0.3.
   - Router-filled params are dropped, and defaults are filled in.
4. The model never writes router commands. They're rendered from templates later.

Thinking is off by default (`reasoning_effort=none`); see the comparison below.
Connection errors are not caught, so a Temporal activity can retry them.

## Thinking on vs off (measured 2026-10-18)

`gemma4:e4b` on a Mac mini M4 over home Wi-Fi. Three hand-made incidents (`cases.py`), two
runs each per mode.

| | Median time | Cause right | Template right | Params right | Fallbacks to `none` |
| --- | --- | --- | --- | --- | --- |
| Thinking off | **9.0 s** | **6/6** | **5/6** | **5/6** | 1 |
| Thinking on | 33.6 s | 4/6 | 3/6 | 3/6 | 1 |

- Thinking on was about 3.7× slower and less accurate. In one `heavy_user` run it called the
  incident `uplink_congestion`; in one `uplink_down` run it blamed the upstream provider.
- Both modes made real tool calls, about 4–5 per run: `get_metrics` on the uplink, latency
  and subscriber series, then `list_templates`. Every run that chose `queue_limit` found the
  offending IP (10.0.0.42) on its own from the subscriber series.
- The thinking-off fallback (`uplink_down`) did not reproduce in 4 further runs, all of
  which returned `failover_route` with the right gateways.
- Urdu customer messages came back in Urdu script in 12 of 12 runs.

## Tests

```bash
uv run pytest packages/agent -m "not live"   # TestModel / FunctionModel, no network
uv run pytest packages/agent -m live         # real Gemma on OLLAMA_BASE_URL
uv run python packages/agent/scripts/compare_thinking.py --runs 2
```
