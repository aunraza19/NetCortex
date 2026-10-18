# Core detector integration progress

The detector now imports the merged core contracts directly. `DetectorUnavailable` is a `ModuleUnavailable` subtype, and `detect(site_id, window, history)` consumes core `MetricsWindow` inputs and returns `DetectionResult` with canonical forecast series, including DNS target names containing colons. Results stay in memory; detector code does not call the forecast database writer.

The public API has no labels for cause fitting and no normal validation scores for anomaly calibration. It does not infer either from expected evaluation labels or templates. Consequently, public real TabPFN inference raises a sanitized unavailable error until an approved training/reference source is connected. An explicitly injected fixture backend is mapped to `mode="mock"` and `model="fixture_persistence"` for offline contract tests.

Cloud credentials come from core `Settings`; `.env` loading is disabled at the detector boundary, and `SecretStr` is unwrapped only when constructing the cloud provider. Provider exceptions are reduced to their type by the engine.

Offline verification: detector tests and lead-authored core contract tests pass (37 tests total), and `ruff check packages/detector` passes. Root `ruff check .` reports 19 findings in concurrently changed notify, runbook, and simgen files; it reports no detector findings. No real TabPFN call was made.
