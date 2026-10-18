# Web dashboard handoff

The B6 dashboard is implemented in `apps/web`. It includes responsive overview, incident list/detail, demo and read-only settings routes; a typed mock/live transport; guarded approval and rejection; replay-only scenario outcomes; optional Sentry initialization; and OpenAPI type generation that runs only when given a real schema URL.

Validation from `apps/web`:

- `npm run lint` — passed.
- `npm run typecheck` — passed.
- `npm run format:check` — passed.
- `npm run build` — passed with Next.js 16.4.2.
- `npm run test:e2e` — passed, 14 desktop/mobile tests. Covers the confirmation cancel path, duplicate approval clicks, failed CHR evidence blocking approval, rejection, notify-only uplink failure without a backup, simulated rollback, incident lookup failure, injection and responsive overview.
- `npm run test:e2e:live` — passed, 3 mocked-HTTP tests. Covers visible HTTP 503 without fixture fallback, named event deduplication and recovery refresh, EventSource cleanup, and decision POST acknowledgement followed by authoritative GET.
- `npm start -- --hostname 127.0.0.1 --port 3040` — verified the Render-compatible `next start` command; `/` and `/incidents` returned HTTP 200.

Visual review screenshots (ignored by Git):

- `C:\Users\nigga\Documents\NetCortex-web\apps\web\test-results\overview-desktop.png`
- `C:\Users\nigga\Documents\NetCortex-web\apps\web\test-results\overview-mobile.png`

Integration still requires Aun's published OpenAPI schema and backend contract review, especially payload field mappings, metrics series semantics, SSE replay/heartbeat behavior, and voice media response. No API schema was available, so generated API types were not produced. Sentry is initialized only when a DSN is supplied; no DSN or Sentry MCP connection was available, so delivery is not verified. The root CI and Render service configuration remain parent-owned.

Final topology correction: `apps/web/lib/fixtures.ts` subscriber counts and primary/backup capacities now match the canonical simulator source `data/sites.yaml` (North Tower 120 / 180 / 80 Mbps; Market Cafe 48 / 100 / no backup; East Relay 165 / 250 / 100 Mbps). Health, utilization, latency and loss remain illustrative replay values. The overview browser case asserts the subscriber and primary-capacity values on desktop and mobile; it passed again alongside lint, typecheck and format checks. Screenshots at the paths above were refreshed. No dashboard test server remained listening on ports 3000 or 3001 after the targeted run.

## Dependency audit review

`npm audit` reports five high entries but only one underlying advisory: GHSA-vfj7-8cjw-p6xm in `braces@3.0.3`, reached through the development-only lint chain `eslint-config-next@16.4.2` → `@next/eslint-plugin-next@16.4.2` → `fast-glob@3.3.1` → `micromatch@4.0.8` → `braces@3.0.3`. The advisory describes process-crashing stack exhaustion for deeply nested brace patterns and lists no patched release. `npm view braces versions` confirms 3.0.3 is the latest published release. `npm audit fix --dry-run` proposes downgrading `eslint-config-next` to 14.2.35, a breaking mismatch for Next.js 16, so no dependency override or blind downgrade was applied. `npm audit --omit=dev` reports zero vulnerabilities. Recheck when the advisory gains a patch or the compatible Next lint chain removes `braces`. References: [GitHub advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), [upstream issue](https://github.com/micromatch/braces/issues/84).
