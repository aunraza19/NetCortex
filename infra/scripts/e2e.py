"""End-to-end run through the API, like the dashboard would do it.

    uv run python infra/scripts/e2e.py heavy_user [--api http://127.0.0.1:8000] [--reject]

Injects a scenario on sim-tower, waits for the incident, shows the agent's report and the
CHR dry run, approves (or rejects), waits for the final status and prints the timeline.
It approves only after the scenario ends: the simulated recovery starts then, and with a
short watch (VERIFY_WAIT_S=60) an earlier approval would be judged on incident data.
Needs the worker, Temporal, CHR and the API running.
"""

import argparse
import sys
import time
from datetime import UTC, datetime

import httpx

FINAL = {"resolved", "rolled_back", "rejected"}


def wait_for(fetch, done, timeout_s: float, every_s: float = 3):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = fetch()
        if done(value):
            return value
        time.sleep(every_s)
    raise TimeoutError("gave up waiting")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["heavy_user", "uplink_down", "dns_slow"])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=int, default=3)
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--incident", help="follow this existing incident instead of injecting")
    args = parser.parse_args()
    api = httpx.Client(base_url=args.api, timeout=30)

    started = time.monotonic()
    if args.incident:
        incident = api.get(f"/incidents/{args.incident}").json()["incident"]
        return follow(api, incident["id"], args.reject, started, None)
    known = {i["id"] for i in api.get("/incidents").json()}
    label = api.post(
        "/demo/scenarios",
        json={
            "site_id": "sim-tower",
            "scenario_type": args.scenario,
            "duration_min": args.duration,
        },
    )
    if label.status_code != 201:
        print(f"inject failed: {label.status_code} {label.text}")
        return 1
    print(f"[{0:6.1f}s] injected {args.scenario} on sim-tower")

    def new_incident():
        found = [i for i in api.get("/incidents").json() if i["id"] not in known]
        matching = [i for i in found if i["cause"] == args.scenario]
        return (matching or found or [None])[0]

    incident = wait_for(new_incident, bool, timeout_s=600)  # cooldown after the last run: 4 min
    incident_id = incident["id"]
    print(
        f"[{time.monotonic() - started:6.1f}s] incident {incident_id} opened: {incident['cause']}"
    )
    scenario_end = datetime.fromisoformat(label.json()["end_at"])
    return follow(api, incident_id, args.reject, started, scenario_end)


def follow(api: httpx.Client, incident_id: str, reject: bool, started: float, scenario_end) -> int:

    detail = wait_for(
        lambda: api.get(f"/incidents/{incident_id}").json(),
        lambda d: d["incident"]["status"] != "open",
        timeout_s=600,
    )
    report, plan = detail["incident"]["report"], detail["fix_plan"]
    print(f"[{time.monotonic() - started:6.1f}s] status {detail['incident']['status']}")
    if report:
        print(f"    report: {report['likely_cause']} ({report['confidence']:.2f}) -> "
              f"{report['template_id']} {report['template_params']}")  # fmt: skip
        print(f"    summary: {report['summary']}")
    if plan:
        print(f"    dry run ok: {plan['dry_run_ok']}; commands:")
        print("      " + plan["commands"].replace("\n", "\n      "))

    if detail["incident"]["status"] == "awaiting_approval":
        wait_s = 0 if scenario_end is None else (scenario_end - datetime.now(UTC)).total_seconds()
        if wait_s > 0 and not reject:
            print(f"    approving after the scenario ends ({wait_s:.0f} s)")
            time.sleep(wait_s + 5)
        action = "reject" if reject else "approve"
        reply = api.post(f"/incidents/{incident_id}/{action}", json={"decided_by": "e2e-script"})
        print(f"[{time.monotonic() - started:6.1f}s] {action}: HTTP {reply.status_code}")

    final = wait_for(
        lambda: api.get(f"/incidents/{incident_id}").json(),
        lambda d: d["incident"]["status"] in FINAL,
        timeout_s=900,
        every_s=10,
    )
    print(f"[{time.monotonic() - started:6.1f}s] final status: {final['incident']['status']}")
    print("timeline:")
    first = None
    for event in final["timeline"]:
        at = datetime.fromisoformat(event["time"])
        first = first or at
        payload = event["payload"]
        extra = payload.get("status") or ""
        if "dry_run_ok" in payload:
            extra = f"dry_run_ok={payload['dry_run_ok']}"
        note = payload.get("note", "")
        print(f"  +{(at - first).total_seconds():6.1f}s {event['kind']:17} {extra} {note}")
    return 0 if final["incident"]["status"] in {"resolved", "rejected"} else 1


if __name__ == "__main__":
    sys.exit(main())
