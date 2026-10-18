# netcortex-detector

Past-only feature construction and TabPFN 3.5 adapters for network metrics. `run_engine()` accepts probe and interface DataFrames, aware UTC `as_of`, site, an injected backend, and optional explicit training inputs. `detect(site_id, window, history)` consumes actual core `MetricsWindow` objects and returns core `DetectionResult` with grouped forecast series. Explicit fixture provenance is labeled `mode="mock"`; detector forecasts remain in memory and are never written to the database.

For Gate 2 runtime setup, `prepare_detector(cases_dir, artifact_path)` writes a versioned data-only JSON artifact from TRAIN cases and normal VALIDATION snapshots. It only opens `train/` and `validation/`; it validates split names, paths, unique IDs/seeds, disjoint time ranges, labels, and feature matrices. The artifact contains TRAIN labels as classifier targets, normal TRAIN features, and at most three normal VALIDATION feature rows. It contains no TEST content, SDK model object, or credential. `configure_detector(artifact_path)` fits the classifier and normal-only anomaly model (excluding constant raw metrics from the density fit), calibrates its reference, and caches the configured cloud/local backend for subsequent public `detect()` calls. It raises `ModuleUnavailable` if setup or provider initialization fails and never falls back to fixtures. The cache identity includes a one-way fingerprint of the configured token and timeout; call `configure_detector()` again after either setting changes to rebuild the backend. `clear_prepared_detector()` clears the process cache.

The prepared anomaly cutoff is fixed at `0.7` for Gate 2 plumbing; this small normal reference and cutoff do not establish model accuracy or production operating thresholds. Preparation can be run without model credentials. Provider setup/inference needs the selected cloud/local dependencies and credentials described below.

```python
from pathlib import Path
from netcortex_detector import configure_detector, prepare_detector

artifact = prepare_detector(Path("eval/cases"), Path("artifacts/detector-training.json"))
configure_detector(artifact)
# Application startup can now call netcortex_detector.detect(site_id, window, history).
```

The lead's [credentialed Gate 2 report](../../eval/results/gate2.md) records a real
TabPFN Cloud v3.5 result after public simulator injection. Four series with five
future points each validated; forecast-table rows stayed unchanged. Setup took
271.7 seconds and detection 114.8 seconds. The predicted cause was `uplink_down`
for an `uplink_congestion` injection, so this establishes the API path only;
cause accuracy and performance remain unfinished.

Base installation keeps the heavy inference stack optional:

```powershell
python -m uv run --no-project --with-editable packages/detector --with pytest pytest packages/detector/tests
python -m uv run --no-project --with-editable packages/detector --with ruff ruff check packages/detector eval/run.py
```

For live inference install the optional `cloud` extra (tabpfn-client >=0.6.1, tabpfn >=9.2.0, tabpfn-extensions >=0.6.3, torch >=2.14.1) and provide `TABPFN_TOKEN` (or `TABPFN_API_KEY`), or install the `local` extra with compatible PyTorch/CUDA. Cloud calls use a 30-second client timeout. Cloud sends supplied telemetry to Prior Labs; check its current terms and commercial licensing before product use. Local checkpoint download may require Hugging Face access and acceptance of model terms. GTX 1660 6 GB compatibility has not been verified. The bounded credentialed run is recorded above; local GPU inference remains unverified.

The evaluator supports `--mode mock`, `--mode cloud`, and `--mode local`. `mock` uses a deterministic persistence/heuristic backend only for exercising the pipeline; it does not represent TabPFN accuracy. Cloud/local modes fail visibly when dependencies, credentials, or model calls fail. Example after the simulator has generated its three splits:

```powershell
python -m uv run --no-project --with-editable packages/detector --with pyarrow --with pandas python eval/run.py --mode mock --limit 8
python -m uv run --no-project --with-editable "packages/detector[cloud]" --with pyarrow python eval/run.py --mode cloud
python -m uv run --no-project --with-editable "packages/detector[local]" --with pyarrow python eval/run.py --mode local
```

TRAIN cause labels are classifier targets and never become feature columns. Normal TRAIN snapshots fit the anomaly estimator after constant raw metrics are excluded from its continuous-density features; the first three normal VALIDATION snapshots provide its reference distribution. The Gate 2 setup uses a fixed 0.7 threshold and seeded feature ordering for density scores so reference and live calls use the same ordering; this is a plumbing configuration, not a performance claim. The evaluator separately uses VALIDATION labels for threshold selection before TEST scoring. Public detection consumes core probe and interface metrics; DNS-kind probes use those metrics directly, while the simulator's supplemental DNS-resolution sidecar is unused. Subscriber observations are outside its feature model. Forecast persistence belongs to the core worker; the detector returns forecasts in memory. Sustained evidence requires three consecutive observed values to exceed forecasts made before each value.

See [decision.md](decision.md) and [flow.md](flow.md) for design choices and boundaries.
