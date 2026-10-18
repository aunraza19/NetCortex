# netcortex-detector

Past-only feature construction and injected TabPFN 3.5 adapters for network metrics. The package has no dependency on Aun's unpublished core types. `run_engine()` accepts probe and interface DataFrames, aware UTC `as_of`, site, an injected backend, and optional train/validation inputs. `detect(site_id, window, history)` is the future core adapter and raises `DetectorUnavailable` until the real `netcortex_core.DetectionResult` and `MetricsWindow` contract can be bound.

Base installation keeps the heavy inference stack optional:

```powershell
python -m uv run --no-project --with-editable packages/detector --with pytest pytest packages/detector/tests
python -m uv run --no-project --with-editable packages/detector --with ruff ruff check packages/detector eval/run.py
```

For live inference install the optional `cloud` extra (tabpfn-client >=0.6.1, tabpfn >=9.2.0, tabpfn-extensions >=0.6.3, torch >=2.14.1) and provide `TABPFN_TOKEN` (or `TABPFN_API_KEY`), or install the `local` extra with compatible PyTorch/CUDA. Cloud calls use a 30-second client timeout. Cloud sends supplied telemetry to Prior Labs; check its current terms and commercial licensing before product use. Local checkpoint download may require Hugging Face access and acceptance of model terms. GTX 1660 6 GB compatibility has not been verified. No live credentials or successful external inference are claimed here.

The evaluator supports `--mode mock`, `--mode cloud`, and `--mode local`. `mock` uses a deterministic persistence/heuristic backend only for exercising the pipeline; it does not represent TabPFN accuracy. Cloud/local modes fail visibly when dependencies, credentials, or model calls fail. Example after the simulator has generated its three splits:

```powershell
python -m uv run --no-project --with-editable packages/detector --with pyarrow --with pandas python eval/run.py --mode mock --limit 8
python -m uv run --no-project --with-editable "packages/detector[cloud]" --with pyarrow python eval/run.py --mode cloud
python -m uv run --no-project --with-editable "packages/detector[local]" --with pyarrow python eval/run.py --mode local
```

Expected labels are read only from case sidecars for training targets and scoring. They are not joined to feature rows. Validation labels select a cutoff by F1 subject to the false-alert budget; it is frozen before TEST scoring. The unsupervised model is fit on normal TRAIN observations and normalized against normal VALIDATION scores. Sustained evidence requires three consecutive observed values to exceed forecasts made before each value. DNS, subscriber, and supplemental backhaul observations are not accepted as core telemetry. Template parameter validity, Aun agent investigation, CHR results, and detection delay (single as-of snapshots provide no event trajectory) stay unavailable until real interfaces/data exist.

See [decision.md](decision.md) and [flow.md](flow.md) for design choices and boundaries.
