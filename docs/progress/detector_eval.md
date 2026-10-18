# Detector and evaluator handoff

Implemented Workstream B3 and the offline portion of B9 on `b/detector-eval`. Detector ownership: `packages/detector/`; evaluation ownership: `eval/`; this note is the assigned progress record.

The engine builds past-only one-minute features from probe and interface observations, validates timestamps/site/source boundaries and rejects mixed measurement sources, returns explicit unavailable results for missing, stale, and sparse input, and accepts injected backends. Optional cloud/local TabPFN 3.5 adapters request quantiles, use shifted forecast targets, raw-only metrics, horizon-wise quantile conversion, and a deterministic 2,048-row expanded training cap, train unsupervised detection on normal TRAIN data, and normalize against normal VALIDATION scores; failures remain explicit. Core `detect()` raises `DetectorUnavailable` until Aun publishes the real core result/window mapping. Fixture backend provenance is carried into output.

The evaluator validates split IDs, seeds, and event intervals, blocks path traversal, and uses TRAIN labels only as targets, VALIDATION labels for threshold calibration, and TEST only for measurement. Validation calibration and reported false alerts/site-day now share the unioned normal detection-window exposure per site; positive windows do not enlarge the threshold budget. The existing smoke report predates this correction and should be regenerated with the full validation/test suite. The 8-case fixture smoke report is in `eval/results/detector.md`; it explicitly is not a TabPFN result. `eval/results/agent.md` records that agent/template/params/CHR metrics are unavailable because their actual APIs/contracts were not available in this worktree.

Commands completed:

```powershell
python -m uv run --no-project --with-editable packages/detector --with pytest pytest packages/detector/tests
python -m uv run --no-project --with-editable packages/detector --with ruff ruff check packages/detector eval/run.py
python -m uv run --no-project --with-editable packages/detector --with-editable C:\Users\nigga\Documents\NetCortex-data\packages\simgen --with pyarrow python -c "from netcortex_simgen.cli import make_eval_cases; from pathlib import Path; make_eval_cases(8, 1000, Path('eval/cases'))"
python -m uv run --no-project --with-editable packages/detector --with pyarrow python eval/run.py --mode mock --limit 8
```

Validation passed: 34 offline tests and Ruff. The 8-case fixture smoke completed; the cloud smoke recorded all cases unavailable without credentials. A wheel build and installed CLI help check passed outside the checkout. No live key, TabPFN inference, core binding, forecast persistence, agent investigation, parameter validation, CHR check, or GPU compatibility is claimed. Full 80-test evaluation per split still requires running the simulator's `make_eval_cases(80, ...)` generation, followed by the cloud/local mode only when credentials or local model setup exist.
