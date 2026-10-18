"""Save real runs for DEMO_MODE: `uv run python -m netcortex_api.snapshot [--site sim-tower]`.

Writes demo/snapshot.json with the sites, the finished incidents of one site (with fix
plans and timelines) and its key metric series over the same period. The hosted demo
serves this file instead of a database, model and router.
"""

import argparse
from datetime import timedelta

from netcortex_core import db

from netcortex_api.store import SNAPSHOT, LiveStore

KEY_SERIES = [
    "probe:8.8.8.8:rtt_ms",
    "probe:1.1.1.1:rtt_ms",
    "probe:1.1.1.1:loss_pct",
    "probe:dns:192.0.2.53:rtt_ms",
    "iface:ether1:util_pct",
    "subscriber:10.0.0.42:rx_bps",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", default="sim-tower")
    parser.add_argument("--limit", type=int, default=6, help="newest finished incidents to keep")
    parser.add_argument(
        "--statuses", default="resolved,rolled_back", help="final statuses worth showing"
    )
    args = parser.parse_args()
    store = LiveStore()

    summaries = [i for i in store.incidents(None) if i.site_id == args.site]
    wanted = set(args.statuses.split(","))
    finished = [i for i in summaries if i.status.value in wanted and i.template_id][: args.limit]
    details = [store.incident(i.id) for i in finished]
    if not details:
        print(f"No finished incidents for {args.site}; nothing saved")
        return 1
    start = min(d.incident.opened_at for d in details) - timedelta(minutes=15)
    end = max(d.incident.closed_at or d.incident.opened_at for d in details) + timedelta(minutes=5)
    series = store.metrics(args.site, start, end, KEY_SERIES)
    sites = [s for s in store.sites() if s.id == args.site]

    import json

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(
            {
                "note": "Saved from real runs on the laptop stack; replayed in DEMO_MODE.",
                "sites": [s.model_dump(mode="json") for s in sites],
                "series": [s.model_dump(mode="json") for s in series],
                "incidents": [d.model_dump(mode="json") for d in details],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    db.close_pool()
    print(f"Saved {len(details)} incidents and {len(series)} series to {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
