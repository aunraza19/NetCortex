# Render deployment decisions

The Render blueprint deploys only the Next.js web app as a Node web service. Its build runs `npm ci` and `npm run build`; the start command binds Next.js to Render's assigned `$PORT`. The health check targets `/`.

The service explicitly sets `plan: free` to honor the user's spending limit and
avoid inheriting a paid service default. Account eligibility and current Render
limits still need verification at deployment time.

The UI is configured for mock mode with `NEXT_PUBLIC_API_MODE=mock`. No API service is declared because Aun's backend, authentication, and deployment contract are not available in this branch. Adding an invented backend service or public API URL would imply an integration that does not exist.

Do not put secrets in `NEXT_PUBLIC_*` variables; Next.js embeds those values into browser code. Once Aun publishes the service and auth contract, the service owner must choose the API URL, CORS/auth behavior, and private environment variables, then update the blueprint deliberately. Until the team confirms the public site is deployed and usable, describe Render as configured/planned rather than live.
