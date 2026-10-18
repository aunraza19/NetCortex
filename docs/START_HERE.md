# Running and understanding Workstream B

Start with the dashboard to explore the incident workflow. It runs independently
of Aun's pending backend and always identifies its simulated data.

```powershell
cd apps/web
npm ci
npm run dev
```

Open http://localhost:3000. The Overview links to incident evidence, proposed
commands, rollback, a confirmation step, and the simulated result. The Demo page
creates fixture scenarios. Fixture approvals never contact a router.

For the Python workspace, install Python 3.12 and uv, then from the repo root:

```powershell
uv sync --all-packages --locked
uv run ruff check .
uv run pytest packages .github/tests
uv run simgen --help
uv run netcortex-detector --help
```

If uv is installed as a Python module on Windows, replace `uv` with `python -m uv`.
Base installation excludes the optional model dependencies and needs no API keys.

## Code map

| Component | Start reading | Decisions and API flow |
| --- | --- | --- |
| Lead integration | [implementation plan](WORKSTREAM_B_PLAN.md) | [decision](../decision.md), [flow](../flow.md) |
| Simulator and RIPE data | [simgen](../packages/simgen/README.md) | [decision](../packages/simgen/decision.md), [flow](../packages/simgen/flow.md) |
| Detection and forecasts | [detector](../packages/detector/README.md) | [decision](../packages/detector/decision.md), [flow](../packages/detector/flow.md) |
| RouterOS retrieval | [runbook](../packages/runbook/README.md) | [decision](../packages/runbook/decision.md), [flow](../packages/runbook/flow.md) |
| Voice and outage news | [notify](../packages/notify/README.md) | [decision](../packages/notify/decision.md), [flow](../packages/notify/flow.md) |
| Dashboard | [web](../apps/web/README.md) | [decision](../apps/web/decision.md), [flow](../apps/web/flow.md) |
| CI and CHR | [admin setup](../.github/admin-setup.md) | [decision](../.github/decision.md), [flow](../.github/flow.md) |
| Hosting | [Render](../infra/render/README.md) | [decision](../infra/render/decision.md), [flow](../infra/render/flow.md) |

## Switching to the shared runtime

[Contract requests](CONTRACT_REQUESTS.md) describe the exact missing shared
schemas, configuration and endpoints. [Setup](SETUP.md) explains credentials,
model/database setup and deployment. Public Python wrappers deliberately refuse
to construct invented shared objects while `netcortex_core` is absent. Internal
engines accept ordinary data/configuration for independent testing.

For live UI mode, use the documented environment variables and generate API types
from Aun's actual OpenAPI. Live errors remain visible. A successful mocked API
browser test establishes transport behavior, not a working backend or router.

[Validation results](VALIDATION_RESULTS.md) separates measured checks from
pending model, backend, provider and deployment checks. Raw RIPE rows, generated
datasets and credentials are ignored by Git; regenerate them locally using the
documented commands.
