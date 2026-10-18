# netcortex-worker

The Temporal worker that runs NetCortex's two workflows.

```bash
temporal server start-dev --db-filename var/temporal.db   # Temporal + UI on :8233
uv run worker                                             # also starts a monitor per MONITOR_SITES site
```

**MonitorSiteWorkflow** (`monitor-<site>`). Every `MONITOR_INTERVAL_S` (60 s) it:

1. loads the last 30 minutes, plus 2 hours of history;
2. skips the round if the data is older than 2 minutes;
3. runs `detect()` and stores the forecasts;
4. opens an incident if the detection is an anomaly and no incident is open for that cause;
5. starts an `IncidentWorkflow`.

It uses continue-as-new every 60 rounds.

**IncidentWorkflow** (`incident-<uuid>`):

1. Investigate with Pydantic AI's `TemporalAgent`. Every model request and tool call is a
   Temporal activity.
2. Dry-run the fix on CHR and store it in `fix_plans`. A failed dry run means `rejected`.
3. `awaiting_approval`: wait for the `approve` or `reject` signal (sent by the API), up to
   `APPROVAL_TIMEOUT_S`.
4. Apply on CHR, watch for `VERIFY_WAIT_S`, then verify the template's metric on the
   detection's series.
5. Improved means `resolved`. Not improved (or apply failed) means roll back, then `rolled_back`.

Every status change writes an `events` row, which the API streams over SSE. If the model
fails, the incident gets a notify-only report (template `none`); the workflow itself never
fails.

**Sentry:** every activity runs in a transaction. All activities of one incident share a
trace whose ID is the incident's UUID without dashes. There are manual spans for `detect`,
`check_fix`, `apply` and `rollback`, and a `gen_ai.chat` span (model, token counts) for each
Gemma request. Each activity has its own Sentry scope.
