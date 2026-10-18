# Render deployment flow

**Entry:** a repository owner applies `infra/render/render.yaml` through Render Blueprint setup or updates an existing Blueprint connection. GitHub Actions does not publish the site itself.

1. Render reads the Blueprint and builds from `apps/web`.
2. It runs `npm ci`, then `npm run build`, and starts the Next.js server on `$PORT` bound to `0.0.0.0`.
3. Render checks `/` for service health.
4. The browser loads the hosted UI in mock mode. In the current Blueprint there is no UI-to-NetCortex-API network connection; API service deployment and authentication remain blocked on Aun's backend contract.

**Exit:** successful Render build and health response mean the UI service is healthy. They do not prove backend, live telemetry, CHR, approval, or end-to-end product behavior. Record the actual deploy URL/status only after an owner confirms it in Render.
