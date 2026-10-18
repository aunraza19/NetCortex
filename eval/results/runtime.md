# Merged runtime integration verification

Base: main f062f9d (runtime PR #7), Python 3.12. No migrations, core/API/worker
changes, live-router operations or published coding transcripts.

## Actual SQL round trip

Public simgen.inject on sim-tower wrote core probe, interface, subscriber and
scenario-label rows inside an outer force-rollback transaction. Existing Site
topology was unchanged. Counts returned exactly to their initial values:

| Table | Before | During | After rollback |
| --- | ---: | ---: | ---: |
| probe_metrics | 3020 | 3895 | 3020 |
| iface_metrics | 402 | 520 | 402 |
| subscriber_metrics | 603 | 780 | 603 |
| scenario_labels | 6 | 7 | 6 |

The test preserves shared database contents and does not claim Temporal or CHR
execution. Offline acceptance also covers overlap rejection, deduplication,
bounded simulated recovery replacement, topology and schema-valid template data.

## Actual TabPFN Cloud v3.5

The bounded canary uses full in-memory sim-tower observations: five probe targets,
two interfaces and subscriber rows, with a final three-minute heavy_user episode.
The model is configured from an existing data-only TRAIN/normal-VALIDATION
artifact; TEST is excluded. Public detect returns an actual core DetectionResult.
The canary validates provenance, finite scores and ordered five-minute quantiles.

The first measurement before parallel inference took 120.0 seconds for setup
and 131.6 seconds for detection. Overlapping forecasts, walk-forward checks,
cause and anomaly calls initially took 129.2/147.1 seconds. Batching the three
walk-forward queries by matching training fingerprint then measured setup/detect
at 99.1/62.1 seconds. The latest call returned seven series with five future
points each, passed the core DetectionResult contract, and stayed under both the
110-second target and unchanged worker's 120-second activity limit. Cause was
still uplink_down (confidence 0.323), not heavy_user.
The artifact's original three-site domain and tiny calibration reference do not
establish cause quality on sim-tower. Subscriber rows are generated for the
agent's investigation; they are not current detector features.

Batching improved measured inference latency in the latest run; repeated runs
may still vary with the cloud service. Setup occurs before worker startup.
Per-batch provider timeouts do not guarantee a whole-activity deadline. The
latest measurement establishes this scenario's integration and timing only, not
cause quality, broad reliability or production performance. Cause calibration
and broader repeated provider measurements remain open.

## Browser contract boundary

Browser acceptance starts the actual merged FastAPI app and saved DemoStore
without dotenv. It renders actual sites, uplinks, metrics, nested incident reports,
English/Urdu messages and plans, then approves a pending in-memory snapshot via
the real REST handlers. Saved replay blocks scenario injection. Mock and mocked
live browser suites separately test UI transitions and failure handling.

This is real HTTP integration with saved observations. It is not an end-to-end
Temporal/model/router run. Aun's previously reported real-stack scenarios remain
his verification; they are not relabeled as new Workstream B results.
