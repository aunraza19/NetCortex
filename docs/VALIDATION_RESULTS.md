# Workstream B validation

Measured on 2026-10-18. This report distinguishes independent implementation
checks from the shared runtime and external services that are still pending.

| Check | Actual result |
| --- | --- |
| Locked base Python workspace | Four packages installed successfully with Python 3.12; optional heavy model extras excluded |
| Python lint and tests | Ruff passed; 87 tests passed in 7.30 seconds; combined branch coverage 68% (live services excluded) |
| Distribution build | All four source distributions and wheels built successfully |
| CLI startup | Installed `simgen --help` and `netcortex-detector --help` passed |
| Frontend | Prettier, ESLint, TypeScript and production Next.js build passed |
| Dashboard browser flows | 14 Chromium tests passed across desktop and phone widths |
| Live transport browser behavior | Three tests passed against mocked HTTP/SSE, including visible failure, deduplication/reconnect, and acknowledgement followed by authoritative refetch |
| Dependency audit | Production dependencies: zero findings. Five high development entries share unpatched braces advisory GHSA-vfj7-8cjw-p6xm; see web decisions |
| RIPE download | 11,819 real public ping records, three PK probes / three ASNs, October 11–17; three daily request gaps recorded |
| Calibration | Actual per-target/hour and explicitly opted-in public DNS role-proxy statistics; no DNS lookup timing claim |
| CHR offline lifecycle | 15 fake-console/network/process tests passed; these do not count as a real boot |
| GitHub Actions | [Python/frontend CI](https://github.com/aunraza19/NetCortex/actions/runs/39131915864) passed on implementation commit `d60ffac`; all 87 Python and 17 browser tests passed |
| Real isolated CHR | [Router smoke](https://github.com/aunraza19/NetCortex/actions/runs/39131915789) passed: pinned RouterOS boot, console provisioning, two authenticated REST resource checks and cleanup. Template job skipped pending Aun harness |

The detector regressions cover past-only features, finite physical bounds, SDK
quantile layout, all five horizons, capped fit contexts, stale/future and mixed
source rows, total-loss RTT absence, gaps in historical forecast comparison,
nonfinite model outputs, separate split windows and safe observation paths.
Provider tests cover malformed responses, timeouts, unavailable audio/news and
embedding identity/dimension checks. UI tests cover confirmation, failed router
checks, duplicate submissions, missing incidents, site backup topology and rollback.

The first real runs exposed serial CRLF double submission and a transient browser
assertion. Both were corrected before the successful runs linked above. The
report update changes documentation only. [Draft PR #1](https://github.com/aunraza19/NetCortex/pull/1)
contains the implementation and the remaining shared-runtime gates.

## Evaluation

The reproducible run creates 80 training, 80 validation and 80 held-out cases,
with ten per class in each split:

```powershell
Copy-Item data/baselines/ripe-pk-2026-10-11--17.json data/calibration.json
uv run simgen eval-cases --n 80 --seed 1000 --mock
uv run python eval/run.py --mode mock
```

[The detector report](../eval/results/detector.md) scored 80/80 held-out fixture
cases: cause accuracy 37.5%, event precision 100% (62 predicted positives), recall
88.6% (62/70 events), median about 97 ms/case. Zero false alerts were observed
over only 0.20833 normal site-days; this small snapshot sample does not establish
a continuous-operation false-alert rate. This does not measure TabPFN performance. The separate
[cloud-unavailable report](../eval/results/cloud-unavailable.md) scores 0/80 cases
when the provider cannot run. Expected labels stay in
sidecars, out of detector inputs. Thresholds use validation only. Agent/template,
parameter and real-router metrics remain unavailable until Aun's integration runs.
Single-snapshot evaluation cannot establish detection delay; replay is required.

The frozen aggregate [calibration profile](../data/baselines/ripe-pk-2026-10-11--17.json)
preserves the exact statistical input used for this run. Copying it as above
explicitly opts into the narrow role proxy; use `cp` in a POSIX shell. No raw
measurements are included in the profile. Raw/generated files and the active
`data/calibration.json` remain ignored. Committed provenance and
coverage live in [the RIPE summary](../data/ripe-baseline-summary.json) and
[calibration report](../data/calibration-report.md).

## Pending shared and external checks

Upstream `main` still contained only README.md at the integration refresh. There
is no verified `netcortex_core`, backend, workflow, collector or template harness
to integrate against. [Contract requests](CONTRACT_REQUESTS.md) specify what is
needed. Public Python wrappers fail explicitly at those boundaries.

No live database/pgvector query, EmbeddingGemma search, TabPFN inference,
ElevenLabs audio, SerpApi outage check, Sentry event, deployed Render/domain or
live approval/apply/verification/rollback has been established. Their account
access, credentials, exact model identity and/or Aun's code are pending. No
provider-free result is presented as evidence for those integrations.

See [the start guide](START_HERE.md) to run the independent implementation.
