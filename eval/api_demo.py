"""Serve the merged API's saved replay for browser contract checks, without services."""

import argparse
from uuid import UUID

import netcortex_core
import uvicorn
from netcortex_core import IncidentStatus, Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8137)
    parser.add_argument("--awaiting", action="store_true")
    args = parser.parse_args()
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        sentry_dsn_backend=None,
        api_cors_origins=["http://127.0.0.1:3002", "http://localhost:3002"],
    )
    netcortex_core.get_settings = lambda: settings
    from netcortex_api import main as api

    if args.awaiting:
        # Seed one pending review using the real saved report/plan and core models.
        # This is private in-memory DemoStore state; never a DB/router operation.
        for item in api.store.incidents(None):
            detail = api.store.incident(UUID(str(item.id)))
            if detail.fix_plan and detail.fix_plan.dry_run_ok and detail.incident.report:
                detail.incident.status = IncidentStatus.AWAITING_APPROVAL
                detail.incident.closed_at = None
                break
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
