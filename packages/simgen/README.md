# netcortex-simgen

Deterministic network telemetry fixtures and bounded RIPE Atlas collection. The package imports the shared NetCortex core schemas directly. Offline fixture commands require no database credentials. Generated Parquet and raw downloads stay under ignored `data/generated/` and `data/raw/` paths.

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

`generate()` returns core-shaped probe/interface DataFrames and plain fixture labels, including DNS lookup observations. `generate_subscribers()` returns continuous core SubscriberMetric-shaped rows. `inject_frames()` remains a local fixture helper; public `inject(site_id, scenario_type, duration_min, seed)` returns a core ScenarioLabel and transactionally inserts sim metrics after a per-site advisory lock and overlap check. Existing site rows are preserved.

Scenario signals affect both ping and interface data. Complete uplink loss is exactly 100% with missing RTT/jitter; gateway ping remains available and a configured backup receives traffic. DNS timing uses core probe rows (`kind=dns`, target `dns:1.1.1.1`), separate from ICMP. Continuous subscriber evidence uses core SubscriberMetric rows. Experimental backhaul quality remains in supplemental Parquet.

RIPE collection discovers active Pakistan probes and public ping measurements dynamically, then fetches bounded UTC-day result windows for selected probes. Requests have a total deadline and response/row/pagination limits; cache keys include selected probe IDs, and partial daily gaps stay visible in the fetch report. Fetched rows retain probe/ASN/measurement/target/time provenance; no real records are fabricated. Offline tests do not call the network.

The integration checkout contains 11,819 public RIPE ping records from 2026-10-11 through 2026-10-17: three Pakistan probes in three ASNs, across measurements 1001 and 1004. Measurement 1001 has all seven days; measurement 1004 has four successful days and three recorded request timeouts. These targets measure root-DNS-server reachability, not DNS resolution latency. Exact target calibration always wins. An opt-in role proxy is available only with both an exact-target mapping and `--allow-role-proxy`; it applies per-hour RTT, jitter, and loss medians only to unmatched configured public-DNS targets `1.1.1.1` and `8.8.8.8`. Its source, destination, and route-equivalence uncertainty are included in `generation_metadata.json`. Reproduce the explicitly approved mapping with `simgen calibrate --target-role-map data/ripe-target-roles.json --allow-role-proxy`. See [calibration-report.md](../../data/calibration-report.md). `simgen calibrate --mock` exits without writing because no mock observation dataset is bundled.

Run that calibration command from the workspace root so the relative mapping path resolves. The mapping file records exact observed-source roles; omitting `--allow-role-proxy` stores role statistics but does not transfer them into generated target baselines.

`eval-cases --n 80` writes 80 cases for each of train, validation, and held-out test, balanced at ten cases per class per split. Seeds and calendar windows are separate. JSON sidecars contain event bounds, seed, split, `as_of`, history window, and expected labels. Metric feature rows end at `as_of`; labels are not feature columns. Supplemental experimental evidence has a separate file.

Database load and live injection use the merged core schemas and DB helpers. Load/replay append source-tagged metric rows in bounded batches; mock mode validates without writes. Injection inserts probes, interfaces, subscribers, and one scenario label in one transaction. Repeating a load appends another copy because metric rows have no unique key. CLI `inject --mock` persists a fixture at the deterministic simulator clock; real CLI injection calls the transactional Python `inject` lifecycle. Injection supports durations from 1 minute through 22 hours, which fits its generated probe/interface window. Python `inject_frames(..., start=...)` accepts a fixture start. `replay` merges active persisted injection fixtures with generated rows and consumes them in timestamp order; only speed 1 uses wall-clock pauses. These commands do not act on a router or claim a live injection. Mock tests cover the transaction boundary; real database operation still requires configured credentials.

Runtime injection also supports a dedicated `sim-tower` topology matching the CHR test router: `ether1` via `10.0.2.2`, `ether2` via `192.0.2.1`, three subscriber queues, and separate ICMP and DNS probe targets including `dns:192.0.2.53`. This runtime-only site is excluded from ordinary fixture and evaluation generation, preserving the original three-site case counts. Injecting it fills missing 30-minute normal history, writes the incident for its requested duration, then writes 20 minutes of scripted normal recovery. Repeated runs deduplicate existing sim metric keys; an earlier scenario's still-future recovery is replaced only within its bounded recovery interval and only for `source=sim`. Existing site topology is preserved. This remains simulated data and does not send traffic to or configure the router.

On `sim-tower`, runtime injection rejects `game_route_issue` and `wireless_interference` because the topology has no game-server probe or wireless backhaul, so neither cause can be simulated truthfully. DNS labels include the validated resolver replacement list. The original three sites retain their existing scenario support and DNS lookup target.

See [decision.md](decision.md) for material choices and [flow.md](flow.md) for entry points, files, external APIs, failure paths, and contract gates. Passing offline tests does not establish a live RIPE, core, database, router, or workflow integration.
