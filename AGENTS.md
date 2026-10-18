# Workstream B repository rules

## Ownership

- Workstream B owns only the root tooling/bootstrap files, `docs/`, `infra/render/`, `.github/`, `packages/simgen/`, `packages/detector/`, `packages/runbook/`, `packages/notify/`, `apps/web/`, `data/`, and `eval/` as assigned in the build plan.
- Aun owns `packages/core/`, `packages/agent/`, `packages/fixes/`, `services/api/`, `services/worker/`, `services/collector/`, shared schemas and Settings, Temporal workflows, and the router harness. Do not create, edit, or redefine those contracts.
- Core is merged: distribution `netcortex-core`, import `netcortex_core`. Import actual schemas, Settings and ModuleUnavailable directly. Main's core code is authoritative.
- Workstream B distribution/import pairs are `netcortex-simgen` / `netcortex_simgen`, `netcortex-detector` / `netcortex_detector`, `netcortex-runbook` / `netcortex_runbook`, and `netcortex-notify` / `netcortex_notify`.
- Never copy shared types into a Workstream B package. Import them from the approved core package after it exists.
- Root files, `uv.lock`, integration wiring, and shared deployment decisions are owned by the workstream lead. Do not regenerate or edit `uv.lock` from a worker branch.
- Keep main's pyproject.toml, .gitignore, LICENSE and .gitattributes. Never re-add .entire/ to .gitignore; regenerate uv.lock with uv, never merge it manually.
- Never open .env or credential files, dump environment variables, or expose provider errors containing secrets. Tests use Settings(_env_file=None). Obtain runtime credentials through the process environment and unwrap SecretStr at the point of use.
- Database migration 001 is already applied on Tiger Cloud. Do not run any migrations. detect() never writes forecasts; the worker owns forecast writes.
- Voice is removed. Keep English/Urdu customer messages as text; remove speak, audio routes/players and voice configuration from B-owned code/docs.
- EMBED_MODEL is exactly embeddinggemma. Do not require a version suffix.

## Implementation expectations

- Every network call has a finite timeout and a mock/offline mode where applicable.
- Unit tests run offline with fixtures; do not depend on live credentials or services.
- Model or provider errors must be reported explicitly. Do not return fallback output that implies inference or a successful check occurred when it did not.
- Keep secrets in local environment variables or secret stores. Never commit `.env`, credentials, raw downloads, or generated Parquet.
- Use only approved cause and template identifiers from the shared build plan. Contract changes require Aun's approval.
- Keep package READMEs and progress notes current. State external integration gates plainly rather than claiming unfinished behavior works.
- Each agent must maintain `decision.md` and `flow.md` in its package/app (the lead maintains both at repository root). Explain material choices and reasons, and document actual CLI/Python/HTTP entry points, outputs, connected APIs, errors and fixture/live boundaries in plain language.
