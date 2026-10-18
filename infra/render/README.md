# Render dashboard deployment

Use `render.yaml` as the Blueprint file path when creating the service from the
tested branch. This is a Next.js Node web service with the root directory
`apps/web`, Node 22, a production build and the Render-assigned port.

Select Render's free service tier. The blueprint creates no database, API or paid
resources. Verify the selected tier before creating the service in the dashboard.
Account access and the `.tech` domain are required to publish; no deployment has
been performed by this branch.

The default environment uses fixture mode. Keep the persistent demo disclosure.
Add Aun's API URL and switch transport only after the shared API is available and
its browser/CORS/authentication contract is verified. `NEXT_PUBLIC_*` variables
are embedded at build time, so rebuild after changing them. Provider, database and
router credentials belong on the backend and must never be public variables.

See [setup](../../docs/SETUP.md), [decisions](decision.md) and [flow](flow.md).
