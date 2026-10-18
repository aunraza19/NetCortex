# Development setup

## Local development

Install Python 3.12, uv, Node.js/npm for the web app, and Git. From the repository root:

```powershell
uv sync --all-packages --locked
uv run ruff check .
uv run pytest -m "not live"
```

`uv sync --all-packages --locked` installs the merged workspace packages in editable mode from the committed lockfile. The lead maintains the lockfile and preserves main's root manifest. Optional TabPFN/cloud/local extras are excluded from this base installation.

For the web app:

```powershell
cd apps/web
npm ci
npm run lint
npm run typecheck
npm run build
npm run test:e2e
npm run test:e2e:live
npm run test:e2e:api
```

Playwright browser setup may also require `npx playwright install --with-deps` on Linux CI.

## Local environment and secrets

Copy `.env.example` to `.env` when the relevant integration modules provide it. Keep `.env` local; never add credentials to source control. Use mock/offline modes for unit tests. External credentials such as database, Sentry, TabPFN, and SerpApi keys are optional and should be supplied only for the corresponding integration. No credentials are required for linting or offline unit tests.

Store secrets in the local shell environment or the hosting provider's encrypted environment settings. Do not place production secrets in frontend variables: values embedded into a browser bundle are public.

## Account and sign-in steps

The API authentication and role contract is awaiting Aun's decision, so there is no supported account-creation or login procedure yet. Once that contract is published, the operator setup guide must explain how to create the first owner account, sign in, invite or provision other roles, and recover access. Do not expose an unauthenticated hosted dashboard with real subscriber data while this gate is open; the planned demo should use simulated/replayed data and follow the eventual auth policy.

## Free tiers and credits

The hosted demo may use Render, Tiger Data, Sentry, and vendor trial/free credits if current eligibility and limits allow. Availability, quotas, and credit terms change; check each provider's current account dashboard before relying on a free tier. Do not put paid usage on an account without its owner's authorization. The local development and offline test path must not require a paid service.

## Integration gates

Core, agent, fixes, collector, Temporal worker, API/OpenAPI/SSE and the real CHR
harness are merged. The dashboard can use the real API: configure
`NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_BASE_URL` before building it.
Regenerate API types using `npm run api:types` with `OPENAPI_URL` pointing to
the actual service's `/openapi.json`. Its `/health` response identifies saved
replay; scenario injection is disabled for replay or unknown mode.

For the real detector worker, install `uv sync --all-packages --extra cloud --locked`
and prepare a data-only TRAIN/normal-VALIDATION artifact as described in
[the detector README](../packages/detector/README.md). Start
`uv run --no-sync netcortex-detector-worker --artifact artifacts/detector-training.json`
so provider setup happens in the same process before Temporal monitoring starts.
The worker needs the configured Temporal server, database and other runtime
dependencies. Never run migration 001 again; it is already applied on Tiger Cloud.

See [runtime verification](../eval/results/runtime.md) for actual checks and
limitations. Cause accuracy, embeddings/ingestion, public hosting and a new local
full-stack run remain separate gates. The Render blueprint still defaults to
fixture mode until an API deployment URL and access policy are supplied.

## Agent add-ons configured on this workstation

- RouterOS QEMU and Sentry instrumentation skills were installed from their
  official source repositories. They were read and applied to the corresponding implementation.
- TabPFN MCP is configured at `https://api.priorlabs.ai/mcp/server`, using the
  local `TABPFN_API_KEY` environment variable. Its MCP connection has not been
  verified. The separate Python runtime client has completed bounded real cloud
  checks using locally configured credentials; that does not verify the MCP.
- Tiger CLI is installed. Its MCP uses `tiger mcp start` and requires Tiger
  authentication plus Aun's database access. Do not call it connected until a
  real authenticated query succeeds.
- Entire is enabled locally with telemetry and automatic session uploads
  disabled. Publishing selected coding-session provenance remains a separate,
  deliberate action after reviewing what the captured session includes.

Do not paste secrets into code, commit messages, documentation or chat. Use local
environment configuration and each provider's authentication flow.
