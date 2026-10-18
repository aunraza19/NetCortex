# CI entry and exit flow

## Normal pull request

**Entry:** a push to `main` or a `b/**` branch, any pull request, or manual `workflow_dispatch` starts `.github/workflows/ci.yml`.

1. The Python job installs Python 3.12 and the complete locked uv workspace. It runs Ruff and pytest, including B's offline CHR bootstrap tests.
2. The web job checks whether `apps/web/package.json` exists. Before the app lands, it writes a pending note and exits without claiming web coverage. After the app exists, it requires the lockfile, lint/typecheck/build/e2e scripts, Playwright config, and Playwright dependency; then it runs `npm ci`, those four checks, and Chromium Playwright tests.
3. Jobs exit green only when their applicable checks pass. A missing integrated web app is reported as pending in the job summary.

## CHR template pull request

**Entry:** changes to RouterOS templates/fixes, Aun's harness, this bootstrap helper, its workflow, or a manual dispatch start `.github/workflows/chr-templates.yml`.

1. Readiness checks only for Aun's `infra/chr/test_templates.py`.
2. If missing, the template job is skipped and the summary says no CHR/template tests ran. A separate smoke job installs QEMU/the locked workspace, tests B's offline lifecycle code, and boots/provisions the pinned router.
3. If present, only the real template job runs; it installs QEMU/the locked workspace and boots/provisions one router before invoking Aun's harness. The smoke job stays skipped to avoid a duplicate boot.
4. Bootstrap downloads and verifies the pinned image, starts QEMU, skips the optional license text display, presses Enter at the continuation prompt, agrees only at the terms prompt, provisions a random admin password over its serial socket, enables REST support, and verifies the authenticated REST resource twice. It masks the password before provisioning and exposes `CHR_REST_URL`, `CHR_REST_USERNAME`, and `CHR_REST_PASSWORD` only to subsequent steps through `GITHUB_ENV`.
5. The real template job runs Aun's harness against `http://127.0.0.1:9180/rest`. On every outcome, the active router job uploads QEMU and sanitized serial logs when available and asks the helper to stop only its own verified QEMU process.

**Exit:** actual template coverage is reported only when Aun's harness ran. Bootstrap unit tests, boot smoke, job setup, and a missing-harness skip do not count as an actual router/template test pass.
