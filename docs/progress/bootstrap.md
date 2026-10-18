# Bootstrap progress

Date: 2026-10-18

The root tooling and partner-owned bootstrap docs were laid down first. The workstream lead now owns the shared Python manifest and `uv.lock`; workers must not regenerate that lock independently.

## CI and CHR

- Python CI installs all locked workspace packages, runs Ruff, and runs the package tests plus `.github/tests/test_chr_bootstrap.py`.
- Web CI has a pending summary until `apps/web` exists. Once it exists, missing lockfile/scripts/Playwright configuration/dependency fails instead of silently skipping the required checks.
- `.github/scripts/chr_bootstrap.py` pins official x86 CHR 7.24.5 and SHA-256 `16f07222a3213352c9c4fbea4f4dec6a8ffb78fdc0fa5e398c23103ed357c6eb` (official zip size 45,293,979 bytes). It uses QEMU with loopback-only management ports, handles the optional license-display prompt separately from actual terms acceptance, provisions a random admin password over serial, and requires two authenticated REST resource responses before reporting ready.
- Twelve offline lifecycle tests use fake console/process/network responses. They cover first-login display/acceptance prompts, bounded provisioning, GitHub secret masking, and password-redacted serial diagnostics. They do not boot a real router and are not counted as router/template coverage.
- The CHR template workflow owns QEMU setup and bootstrap; it uploads both QEMU and sanitized serial logs when available. When Aun's `infra/chr/test_templates.py` is absent, a separate CI smoke job boots CHR and checks authenticated REST readiness; the actual template job is skipped and the workflow summary says no template tests ran.
- The actual GitHub-hosted CHR smoke has not run from this branch yet. No real router boot or template pass is claimed here.
- The [official RouterOS REST API documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST%2BAPI) states REST uses the RouterOS HTTP/HTTPS service and Basic Auth.

## Render

`infra/render/render.yaml` is a Next.js Node web service in mock mode. It deploys no API. Aun's backend URL, auth, and deployment contract remain pending; Render health for `/` alone does not prove end-to-end product behavior.

## Still open

Core package naming and shared schemas, Settings/API/SSE contracts, subscriber telemetry/privacy and role policy, forecast key/writer semantics, simulator injection lifecycle, web app merge, API deployment integration, and the real CHR harness remain open. The demo and post notes contain no fabricated users, evaluation figures, or live deployment claims.
