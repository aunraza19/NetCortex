# Development setup

## Local development

Install Python 3.12, uv, Node.js/npm for the web app, and Git. From the repository root:

```powershell
uv sync --all-packages --locked
uv run ruff check .
uv run pytest
```

`uv sync --all-packages --locked` installs all four workspace packages in editable mode from the committed lockfile. The lead maintains the root manifest and lockfile. Optional TabPFN/cloud/local extras are excluded from this base installation.

For the web app:

```powershell
cd apps/web
npm ci
npm run lint
npm run typecheck
npm run build
npm run test:e2e
npm run test:e2e:live
```

Playwright browser setup may also require `npx playwright install --with-deps` on Linux CI.

## Local environment and secrets

Copy `.env.example` to `.env` when the relevant integration modules provide it. Keep `.env` local; never add credentials to source control. Use mock/offline modes for unit tests. External credentials such as database, Sentry, TabPFN, ElevenLabs, and SerpApi keys are optional and should be supplied only for the corresponding integration. No credentials are required for linting or offline unit tests.

Store secrets in the local shell environment or the hosting provider's encrypted environment settings. Do not place production secrets in frontend variables: values embedded into a browser bundle are public.

## Account and sign-in steps

The API authentication and role contract is awaiting Aun's decision, so there is no supported account-creation or login procedure yet. Once that contract is published, the operator setup guide must explain how to create the first owner account, sign in, invite or provision other roles, and recover access. Do not expose an unauthenticated hosted dashboard with real subscriber data while this gate is open; the planned demo should use simulated/replayed data and follow the eventual auth policy.

## Free tiers and credits

The hosted demo may use Render, Tiger Data, Sentry, and vendor trial/free credits if current eligibility and limits allow. Availability, quotas, and credit terms change; check each provider's current account dashboard before relying on a free tier. Do not put paid usage on an account without its owner's authorization. The local development and offline test path must not require a paid service.

## Integration gates

The core package name and shared schemas, Settings, API and SSE contract, role mapping, and CHR harness are awaiting Aun's confirmation. See [CONTRACT_REQUESTS.md](CONTRACT_REQUESTS.md). The Render blueprint describes the Next.js Node web service; an API service must not be added until Aun's backend exists and its deployment contract is known.

## Agent add-ons configured on this workstation

- RouterOS QEMU and Sentry instrumentation skills were installed from their
  official source repositories. They were read and applied to the corresponding implementation.
- TabPFN MCP is configured at `https://api.priorlabs.ai/mcp/server`, using the
  local `TABPFN_API_KEY` environment variable. No key is supplied yet, so the
  connection has not been verified. The runtime Python client maps this same
  setting through its supported token API.
- Tiger CLI is installed. Its MCP uses `tiger mcp start` and requires Tiger
  authentication plus Aun's database access. Do not call it connected until a
  real authenticated query succeeds.
- Entire is enabled locally with telemetry and automatic session uploads
  disabled. Publishing selected coding-session provenance remains a separate,
  deliberate action after reviewing what the captured session includes.

Do not paste secrets into code, commit messages, documentation or chat. Use local
environment configuration and each provider's authentication flow.
