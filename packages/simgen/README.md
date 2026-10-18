# netcortex-simgen

Deterministic network telemetry fixtures and bounded RIPE Atlas collection. The fixture CLI works without NetCortex core. Generated Parquet and raw downloads stay under ignored `data/generated/` and `data/raw/` paths.

Install this package through the workspace when integrated. From the package directory, an isolated offline run is:

```powershell
python -m uv run --no-project --with pytest --with-editable . pytest
```

Typical commands:

```powershell
simgen generate --days 7 --seed 42 --mock
simgen generate --days 7 --seed 42 --normal-only --mock
simgen inject --site north-tower --type uplink_congestion --duration 15 --seed 42 --mock
simgen replay --speed 60 --mock
simgen eval-cases --n 80 --seed 1000 --mock
simgen ripe --days 14
simgen calibrate
simgen load --source sim --last 2d --mock
```

Default generation schedules all seven causes once per configured site; `--normal-only` generates baseline traffic. Ping samples use 10-second cadence, interfaces use 30-second cadence, and daily demand follows Pakistan local time. Timestamps remain UTC. Seeded NumPy produces the samples. One site/day contains 8,640 ping observations per target and 2,880 interface observations per configured interface.

`generate()` returns core-shaped probe/interface DataFrames and plain fixture labels. `inject_frames()` returns fixture rows and a plain dict label. Public `inject(site_id, scenario_type, duration_min, seed)` lazy-imports the actual `netcortex_core` Cause and ScenarioLabel symbols, then fails clearly until the approved lifecycle adapter is implemented. It never returns a locally invented shared object.

Scenario signals affect both ping and interface data. Complete uplink loss is exactly 100% with missing RTT/jitter; gateway ping remains available and a configured backup receives traffic. DNS timing and synthetic subscriber evidence are written to separate supplemental experimental Parquet with explicit status. Unsupported columns are never added to core table frames.

RIPE collection discovers active Pakistan probes and public ping measurements dynamically, then fetches bounded UTC-day result windows for selected probes. Requests have a total deadline and response/row/pagination limits; cache keys include selected probe IDs, and partial daily gaps stay visible in the fetch report. Fetched rows retain probe/ASN/measurement/target/time provenance; no real records are fabricated. Offline tests do not call the network.

The integration checkout contains 11,819 public RIPE ping records from 2026-10-11 through 2026-10-17: three Pakistan probes in three ASNs, across measurements 1001 and 1004. Measurement 1001 has all seven days; measurement 1004 has four successful days and three recorded request timeouts. These targets measure root-DNS-server reachability, not DNS resolution latency. Exact target calibration always wins. An opt-in role proxy is available only with both an exact-target mapping and `--allow-role-proxy`; it applies per-hour RTT, jitter, and loss medians only to unmatched configured public-DNS targets `1.1.1.1` and `8.8.8.8`. Its source, destination, and route-equivalence uncertainty are included in `generation_metadata.json`. Reproduce the explicitly approved mapping with `simgen calibrate --target-role-map data/ripe-target-roles.json --allow-role-proxy`. See [calibration-report.md](../../data/calibration-report.md). `simgen calibrate --mock` exits without writing because no mock observation dataset is bundled.

Run that calibration command from the workspace root so the relative mapping path resolves. The mapping file records exact observed-source roles; omitting `--allow-role-proxy` stores role statistics but does not transfer them into generated target baselines.

`eval-cases --n 80` writes 80 cases for each of train, validation, and held-out test, balanced at ten cases per class per split. Seeds and calendar windows are separate. JSON sidecars contain event bounds, seed, split, `as_of`, history window, and expected labels. Metric feature rows end at `as_of`; labels are not feature columns. Supplemental experimental evidence has a separate file.

Database load and live injection remain unavailable until Aun confirms core table conflict keys, transaction behavior, and injection lifecycle. Mock load reads and validates the selected fixture but performs no database writes. CLI `inject` persists a fixture at the deterministic simulator clock (default base `2026-10-12T00:00:00Z`, single-cause event at +2 hours); Python `inject_frames(..., start=...)` accepts another fixture start. `replay` merges active persisted injection fixtures with generated rows and consumes them in timestamp order; only speed 1 uses wall-clock pauses. These commands do not act on a router or claim a live injection. Core database persistence stays gated.

See [decision.md](decision.md) for material choices and [flow.md](flow.md) for entry points, files, external APIs, failure paths, and contract gates. Passing offline tests does not establish a live RIPE, core, database, router, or workflow integration.
