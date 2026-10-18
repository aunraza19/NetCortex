# NetCortex web dashboard

Next.js App Router dashboard for the NetCortex operator. It supports a deterministic local fixture mode and a live API mode.

## Run locally

```powershell
cd apps/web
npm ci
$env:NEXT_PUBLIC_API_MODE = 'mock'
npm run dev
```

Use `NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_BASE_URL` to connect to Aun's API. Live mode calls the draft routes in `decision.md`; request timeouts and errors appear in the UI and never switch to fixtures. Those API payload types remain provisional until Aun publishes OpenAPI and shared contracts. The fixture values and CHR outcomes are invented demo records; the UI labels them “Demo: replayed data.” Mock approval simulates workflow states in browser memory only. No router is contacted. Customer messages remain English or Urdu text.

`NEXT_PUBLIC_SENTRY_DSN` enables browser monitoring; server monitoring reads `SENTRY_DSN`. No DSN is committed. Sentry setup is code-ready but not connected or verified without the project DSN.

For production, run `npm run build` then `npm run start -- --hostname 0.0.0.0 --port 3000`. Render should run the app as a Node web service, not a static export. When Aun publishes the schema, run `$env:OPENAPI_URL = 'http://…/openapi.json'; npm run api:types`. The generator requires that URL, uses a bounded fetch, and writes `lib/generated/openapi.d.ts`. No generated API types are included until the actual schema is available.
