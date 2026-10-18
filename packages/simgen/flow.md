# Simulator flow and integration boundaries

## Entry points

```mermaid
flowchart TD
    CLI[simgen CLI] --> GEN[generate]
    CLI --> INJ[inject fixture]
    CLI --> RIPE[ripe fetch]
    CLI --> CAL[calibrate]
    CLI --> LOAD[load and replay]
    CLI --> EVAL[eval-cases]
    GEN --> TABLES[core probe and interface DataFrames]
    GEN --> SUPP[supplemental experimental DataFrame]
    INJ --> TABLES
    TABLES --> PARQUET[ignored generated Parquet]
    SUPP --> EXPPARQUET[supplemental experimental Parquet]
    RIPE --> API[RIPE Atlas v2 API]
    API --> CACHE[ignored cached JSON and RIPE Parquet]
    CACHE --> CAL
    CAL --> CALFILE[data/calibration.json]
    CALFILE --> GEN
    LOAD -->|DATABASE_URL| DB[(core metric tables)]
    LOAD -->|mock| STOP[validate only]
    INJ --> ACTIVE[active_scenarios.json]
    ACTIVE --> LOAD
    EVAL --> CASES[eval/cases split sidecars + observations]
    PUBLIC[inject(site_id, Cause, duration_min, seed)] --> TX[site advisory lock + overlap check]
    TX --> WRITE[atomic core metrics + ScenarioLabel]
```

## Python API

`src/netcortex_simgen/simulator.py` exports:

- `generate(days=1, seed=42, start=None, scenario_type=None, duration_min=15, site_id=None, normal_only=False, hours=None) -> (probe_df, iface_df, labels)`. Without a selected scenario and without `normal_only`, it schedules each of seven causes once per selected site. Probe frame columns match core `probe_metrics`, including separate DNS lookup kind; interface frame columns match `iface_metrics`. An optional `hours` argument bounds a case window to at most 24 hours per requested day. Both frames carry `attrs["calibration"]` with per-target mode and any explicit proxy provenance.
- `inject_frames(site_id, scenario_type, duration_min=15, seed=42, start=None) -> (probe_df, iface_df, label_dict)`. This internal fixture helper emits table-shaped frames and a plain label dict. It does not persist on its own.
- `generate_subscribers(labels, *, start, end, seed=42, site_ids=None) -> DataFrame`. Emits continuous core-shaped SubscriberMetric rows with healthy baseline and active heavy-user traffic. `generate_supplemental(...)` continues to emit experimental backhaul quality rows and legacy supplemental exports.
- `inject(site_id, scenario_type: Cause, duration_min, seed=None) -> ScenarioLabel`. It imports the actual core contract, fixes the event window at injected UTC now through now plus duration, locks the site, rejects overlapping simulator labels, preserves existing site topology, and inserts probe/interface/subscriber metrics plus the scenario label in one transaction. Duration is limited to 1..1320 minutes so metric generation covers the full label. Unknown fixture sites fail as ValueError. Optional `now` and `database` keyword arguments make clock and transaction behavior testable offline.
- `sites() -> dict` reads committed `data/sites.yaml` when running from a checkout and falls back to the bundled `netcortex_simgen.resources/sites.yaml` for an installed wheel.

`src/netcortex_simgen/ripe.py` exports `parse_result(item, site_id="ripe-pk")` and `fetch(days=14, out=None, cache_dir=None, client=None, page_limit=20, max_measurements=5, max_probes=5, deadline_seconds=300)`. A parsed row has `source=ripe`, measurement ID, probe ID, ASN, and target. A packet-loss row with no received packets has `loss_pct=100`, `rtt_ms=None`, and `jitter_ms=None`.

## CLI commands and file/table effects

| Command | Input and steps | Output | Error or gate |
|---|---|---|---|
| `simgen generate --days 7 --seed 42 [--normal-only] [--mock]` | Generate all sites using seeded demand and scenario schedule, unless normal-only is selected. | `data/generated/probe_metrics.parquet`, `iface_metrics.parquet`, `supplemental_experimental.parquet`, `scenario_labels.json`, and `generation_metadata.json` describing target baseline mode, proxy scope, provenance, and uncertainty. | Days must be 1..30; invalid cause/site or non-aware Python start raises `ValueError`. |
| `simgen inject --site north-tower --type uplink_congestion --duration 15 [--mock]` | Mock mode writes a local fixture at the deterministic clock. Real mode calls core `inject()` for the current UTC interval. | Mock writes probe/interface/supplemental Parquets and `active_scenarios.json`; real mode returns a ScenarioLabel after atomic core DB inserts. | Real mode requires DATABASE_URL. Overlap raises ValueError and transaction failure rolls back. Failover labels use `failover_route` only when both gateways are explicitly present in fixture topology; otherwise expected template is `none`. It does not change router configuration. |
| `simgen ripe --days 14` | Discover active Pakistan probes, discover public ping measurements, then bounded results. | Cached JSON under `data/raw/ripe/cache/`; `data/raw/ripe/results.parquet`. | HTTP timeout/status errors and malformed responses fail; pagination stops/errors at 20 pages. `--mock` exits because no real observation fixture is bundled. |
| `simgen calibrate [--target-role-map roles.json --allow-role-proxy]` | Read available `data/raw/ripe/results.parquet` and `data/raw/live/collector.parquet`; compute Pakistan local hour medians, target/hour medians, and counts. Role/hour medians include only exact observed targets named in the map. | Ignored `data/calibration.json` and committed `data/calibration-report.md` with measured coverage, per-target/per-role medians, default coverage, opt-in transfer scope, uncertainty, and gaps. | Role proxy requires both options and at least one matching observed target mapped to `public_dns_reachability_proxy`. It fills only unmatched `1.1.1.1`/`8.8.8.8`; exact target calibration wins. If no input exists, exits without writing; `--mock` exits because no synthetic calibration fixture is bundled. |
| `simgen load --source sim --last 2d [--mock]` | Read generated SIM or RIPE source rows and filter to the last duration. | Mock reports actual selected rows without writing. Intended target tables are `probe_metrics` and `iface_metrics`. | `--last` must be positive `d` or `h`. Real mode requires `DATABASE_URL` from process settings and appends source-tagged rows in bounded batches; missing configuration raises `ModuleUnavailable`. |
| `simgen replay --speed 60 [--mock]` | Read base generated rows and active persisted fixture rows, sort by timestamp. Speed 1 waits wall time; speed greater than 1 consumes on a virtual accelerated clock. | Mock prints consumed row and active-fixture counts. Real persistence targets the same core metrics tables. | This is deterministic fixture replay, not router configuration. Missing base Parquet fails; real mode appends rows transactionally through core DB helpers. |
| `simgen eval-cases --n 80 --seed 1000 [--mock]` | Generate a balanced set independently for each split. N is positive multiple of eight. | 80 cases per split in `eval/cases/{train,validation,test}`; each has JSON sidecar including calibration mode/proxy provenance, probe/iface Parquets, and separate supplemental Parquet. | Invalid size raises `ValueError`. `test` is the 80-case held-out set; train/validation are distinct 80-case sets. |

Every eval JSON sidecar carries `case_id`, `split`, `seed`, `site_id`, `case_start`, `event_start`, `event_end`, `as_of`, `history_window`, `expected`, `calibration`, and observation paths. Exactly ten of each normal plus seven cause classes appear per split when n=80. Case causes and sites are shuffled; train/validation/test use different random seed ranges and nonoverlapping calendar blocks. The history window ends at `window_start=as_of-30m`, the detection interval ends at `as_of`, and event cases set `as_of=event_end-10s`. Probe/interface observations stop at `as_of`. Cause/template/params are absent from feature columns and only read after inference for scoring. The detector worker should use each sidecar's history window as the maximum available context and must not use any observation after `as_of`.

## Network, storage, and failures

The sole network client is httpx to RIPE Atlas v2 endpoints `/probes/`, `/measurements/`, and `/measurements/{id}/results/`. Probe and measurement discovery is dynamic; results are fetched in UTC-day requests filtered to selected probe IDs. Requests use at most 15-second timeouts (5-second connect) under a 300-second overall deadline by default. Result retrieval is paginated up to 20 pages, each response is capped at 8 MiB, and daily result rows are capped at 10,000. Requests are spaced by 0.25 seconds, including after failed responses. Cache keys include the selected probe set; partial-day gaps are preserved in the fetch report and never filled with generated observations. `--mock` makes no RIPE network call.

The integration checkout contains 11,819 real public RIPE ping records from 2026-10-11 through 2026-10-17: three Pakistan probes across three ASNs, measurements 1001 and 1004. Measurement 1001 covers all seven days; measurement 1004 has four successful days and three recorded timeouts. These are root-DNS-server reachability observations, not DNS resolution latency. Exact target calibration takes priority. The bundled role map is opt-in: it permits medians from those two observed targets to proxy only the configured public DNS reachability targets, while generated metadata names the transfer and warns that route equivalence is unproven. Gateway, upstream-hop, regional-game, and DNS resolution timing never use this transfer.

Pandas/NumPy make simulated rows, PyArrow stores Parquet, PyYAML reads sites/scenarios. The wheel bundles a copy of the topology file as a runtime fallback and was verified to generate a one-hour fixture outside the checkout (1,800 probes, 360 interface rows). Psycopg is declared for later database loading. The loader currently opens no transaction unless the explicit key-confirmation environment gate is set, then still exits in a transaction before any insert because the unique/upsert key has not been approved. There is no API, Temporal, CHR, or model integration.

## Missing core gates

`packages/core` is absent in this worktree. Aun must confirm Cause/ScenarioLabel exports; injection start/end, overlap, source, label linkage and cleanup lifecycle; unique table keys and transactional retry semantics; subscriber privacy and evidence policy; DNS resolution timing support; and explicit interface-role support. Supplemental fields are stored separately and never passed to draft core tables. Offline fake-transaction tests cover overlap and rollback behavior; they do not establish external database credentials, RIPE availability, router changes, or the downstream incident workflow.
