# Workstream lead handoff

Current task: user required rebase after merged core/agent/removal, direct shared
contracts, SecretStr handling, real DNS/subscriber simulation, no forecast DB
writes in detect, removal of speech generation, push/ready existing PR, then
Gate 2 only in small follow-up PRs. Keep Python 3.12 and main root files exactly.

## Integration complete locally

- Rebased b/workstream-b onto origin/main fc297c1. Backup branch exists for the
  old public head; push must use explicit force-with-lease against 44e4a7b.
- Main pyproject.toml/.gitignore/LICENSE/.gitattributes are byte-identical.
  uv lock regenerated, uv sync --all-packages --locked succeeded.
- Lead wrote docs/CORE_INTEGRATION_VALIDATION.md and four contract test files
  before delegating to three Luna medium workers (shared integration owned paths).
- Direct core DetectionResult/MetricsWindow/Settings/ModuleUnavailable bindings;
  canonical forecast series including DNS colons; worker alone writes forecasts.
- Simgen DNS-kind probes, continuous subscriber rows, Site mapping, actual atomic
  injection with advisory locking/overlap protection, existing-site preservation.
- News returns real NewsCheck; embeddinggemma bare model accepted, SecretStr
  handled at DB/provider boundary. No speech code/player; customer text preserved.
- Ruff passed; 200 offline tests passed, 1 live agent test deselected. Frontend
  format/lint/typecheck/build + 14 dashboard/3 live browser cases passed.
- Public history plus 18 explicitly fetched Entire refs audited with Gitleaks:
  zero confirmed secrets. 2092 generic findings were all dated SDK feature flags.
  Reports ignored. Automatic checkpoint pushing remains disabled locally.
- A local masked-input window wrote ignored .env; agent did not open it. User
  pasted credentials in chat; never repeat them in tools, docs or responses.
  Do not publish this current transcript. No rotation or migrations performed.
- .codex/config.toml provides future-session deny-read rules. Current unrestricted
  host cannot acquire that sandbox retroactively; limitation documented honestly.

## Delivery sequence

Commit owned source/test/docs and regenerated lock; scan staged changes without
printing credentials. Force-with-lease push to existing PR #1, inspect CI and
GitGuardian, repair failures, mark ready only after checks pass. No migrations.

## Gate 2 follow-up only

Use a small new B branch from delivered integration and draft PR. Real TabPFN
public detect still lacks explicitly prepared TRAIN labels/normal VALIDATION
reference; this is our training responsibility, not missing Aun schemas. Proposed
startup API prepares a data-only artifact from simulator TRAIN/VALIDATION only,
loads/caches a configured backend, and lets public detect use it. No TEST sidecars
at inference; no pickled SDK models or fake real inference.

User credentials are in .env for application runtime only; never use tool reads
or output raw Settings/errors. Use dedicated simulated site, preserve home-lab,
no migrations. Inject now; obtain past-only context/current MetricsWindow; call
actual TabPFN and validate actual DetectionResult, mode/model, finite ordered
future forecast points and no detector DB writes. Save sanitized timing/result.
Embedding installation, deployment, broad evaluation and other work are outside
this requested follow-up. Prior Labs model/client adapters may need SDK fixes
based on actual calls; keep the patch and tests focused.

## Current handoff: runtime integration supersedes the sequence above

Continue on the existing b/workstream-b and PR #1; no new branch or PR. Merge
commit ce3325f incorporates main f062f9d/runtime PR #7. Main's four root files
remain identical; uv lock regenerated. Aun's ownership paths are unchanged.

Lead acceptance plan is docs/RUNTIME_INTEGRATION_VALIDATION.md. Three Luna medium
workers implement UI HTTP adapters, sim-tower runtime injection, and detector
startup/inference concurrency, maintaining component decision/flow/progress files.
Lead tests cover startup ordering, valid sim-tower rows/recovery, concurrency
parity, explicit failure and actual merged API browser decisions. CI now runs
the actual API browser suite in addition to existing mock/live UI coverage.

Latest offline Python run: 261 passed, 3 live deselected; Ruff passed. Mock UI
browser suite passed 16, live contract suite 7, and actual API replay suite 2.
Production build and formatting/type/lint checks passed. eval/results/runtime.md records measured external checks;
ignored .build-check holds sanitized detailed reports. Never open .env or publish
this credential-bearing conversation. No migration or router operations.

Public SQL injection was verified in a force-rollback transaction; all row counts
and the existing Site returned unchanged. Full sim-tower inference returns seven
five-point series. Batching past-only walk-forward queries reduced latest detect
to 62.1 seconds (setup 99.1), below the 120-second monitor timeout. It still
guessed uplink_down for heavy_user; cause quality, embeddings/ingestion, hosting
and a new local full Temporal stack are not claimed.
