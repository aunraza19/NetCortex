# CI and router integration decisions

## CI scope

GitHub Actions runs Python lint and offline tests on the locked workspace, plus the web app's required lint, typecheck, production build, and Playwright suite once `apps/web/package.json` exists. The web job may show a clearly labeled pending state before the app exists. Once it exists, missing lockfile, required scripts, Playwright config, or `@playwright/test` fails the job.

The root Python environment is installed with `uv sync --all-packages --locked`. This keeps workspace packages importable in tests and ensures CI does not silently resolve different dependencies from the reviewed lock.

## CHR selection and provenance

The router workflow pins the official x86 CHR artifact to RouterOS 7.24.5, rather than resolving the moving `stable` channel during each run. The official `NEWESTa7.stable` endpoint returned `7.24.5 1790691687` on 2026-10-18. The downloaded official `chr-7.24.5.img.zip` was 45,293,979 bytes and its SHA-256 is `16f07222a3213352c9c4fbea4f4dec6a8ffb78fdc0fa5e398c23103ed357c6eb`.

The helper uses QEMU directly because CI needs an isolated RouterOS instance with the real REST API and a writable disk for testing apply/read-back/rollback. It chooses KVM only when `/dev/kvm` is writable and otherwise uses TCG. The router is exposed through host forwarding bound to `127.0.0.1` for REST and SSH; the serial console stays on a Unix socket. This keeps the test router off public and shared network interfaces.

Provisioning handles the first-login license flow by answering `n` to the optional software-license display prompt, sending Enter at its continuation prompt, and answering `y` only when RouterOS asks to agree to the license terms. Each prompt is handled once within the bounded serial provisioning deadline. The first serial read uses the remaining deadline rather than a shorter per-read cap because TCG startup may take longer than 20 seconds before the login prompt appears. It creates a random per-run admin password through the serial console and enables `www` with `rest-plain=yes`. MikroTik's [IP services reference](https://help.mikrotik.com/docs/spaces/ROS/pages/103841820/Services) documents `rest-plain` as the REST API support property for HTTP `www`. The helper fails on CLI error text rather than treating a returned prompt as proof the command worked. It emits the GitHub Actions secret mask before sending the generated password, writes the credential to later steps through `GITHUB_ENV`, and stores redacted serial transcript diagnostics after successful provisioning and on failures so later REST readiness errors retain console context. Serial input lines end with a single carriage return: the failed real boot transcript showed the password prompt repeated twice followed by New passwords do not match after CRLF submissions. The helper now detects password rejection immediately and preserves prompt text already buffered after a match. The readiness gate makes two consecutive authenticated calls to `/rest/system/resource` and requires the expected single resource object with a `board-name` field. A bare HTTP 200 is insufficient evidence that RouterOS REST is ready.

## External router test gate

The bootstrap, router lifecycle, QEMU command, credential handling, license/password prompts, CLI error handling, and response-shape checks are B-owned and tested offline with fake console/process/network responses. `infra/chr/test_templates.py` is Aun-owned. When it is absent, a separate smoke job boots CHR and verifies authenticated REST readiness, while the real template job remains skipped with a pending summary. Unit tests and boot smoke do not count as template/router integration tests.

The workflow retains `/tmp/netcortex-chr/qemu.log` as an artifact and cleanup validates both the recorded PID and its QEMU command line before signaling it. The disk and log remain in the runner temp directory until the job is discarded; no downloaded router image is committed.

## Copilot review

Repository instructions can shape Copilot's review, but automatic review still requires repository/organization admin configuration and a qualifying Copilot plan. See [admin-setup.md](admin-setup.md). The repository does not claim Copilot review is enabled until an owner verifies the setting in GitHub.
