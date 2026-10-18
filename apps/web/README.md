# NetCortex web dashboard

Next.js App Router dashboard for network operators. It supports local fixture mode and the merged FastAPI contract.

## Run locally

```powershell
cd apps/web
npm ci
$env:NEXT_PUBLIC_API_MODE = 'mock'
npm run dev
```

For the API, set `NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_BASE_URL` to the service origin. The app reads `/health` to distinguish a live operation from saved `DEMO_MODE` replay. API replay is read only for scenario injection; its incident approvals update the saved snapshot. Live injection targets the API simulator and approval can run the approved commands against the connected CHR. Requests have finite timeouts and visible errors; a failed API call never falls back to local fixtures.

Live payloads use generated `lib/generated/openapi.d.ts` types and explicit adapters in `lib/transport.ts`. Fields absent from the API, such as site location and subscriber totals, display as unavailable. Incident details render the nested report, fix plan, timeline and English/Urdu customer messages. Metric values and forecast bands are joined by timestamp. Metric views refresh every 30 seconds and named stream events trigger an immediate refresh.

Run `npm run test:e2e` for fixture browser coverage, `npm run test:e2e:live` for HTTP failure/stream contract mocks, and `npm run test:e2e:api` for browser coverage against the saved API replay. The API replay test starts a private in-memory snapshot service and needs no database, Temporal, model provider or router.

`NEXT_PUBLIC_SENTRY_DSN` enables browser monitoring; server monitoring reads `SENTRY_DSN`. No DSN is committed, and monitoring is not claimed as connected or verified without the project DSN.

For production, run `npm run build` and `npm run start -- --hostname 0.0.0.0 --port 3000`. Render should run the app as a Node service, not a static export. Regenerate API types from an authorized running API using `OPENAPI_URL=<origin>/openapi.json npm run api:types`.
