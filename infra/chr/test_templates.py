"""Dry-run every fix template on the CHR test router.

    uv run python infra/chr/test_templates.py [--json results.json]

For each template: apply it with valid sample params, check the config change contains
what the template should add, roll back, and check the config matches the baseline again.
Exits 1 if any template fails. Reads CHR_REST_URL, CHR_USERNAME and CHR_PASSWORD
(CHR_REST_USERNAME / CHR_REST_PASSWORD also work, for the CI bootstrap).
"""

import argparse
import json
import sys
import time

from netcortex_core import TemplateId
from netcortex_fixes import RouterClient, RouterError, dry_run, load_templates

# Sample params that fit infra/chr/baseline.rsc, and lines each fix must add.
SAMPLES = {
    TemplateId.QUEUE_LIMIT: (
        {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 10},
        ["+/queue simple add", "name=netcortex-limit-10.0.0.42", "max-limit=5M/10M"],
    ),
    TemplateId.FAILOVER_ROUTE: (
        {"primary_gateway": "10.0.2.2", "backup_gateway": "192.0.2.1"},
        ["check-gateway=ping", "gateway=192.0.2.1", "netcortex:failover_route"],
    ),
    TemplateId.PRIORITY_QUEUE: (
        {"uplink": "ether1", "uplink_mbps": 90},
        ["new-packet-mark=netcortex-priority", "name=netcortex-uplink", "packet-mark=no-mark"],
    ),
    TemplateId.DNS_SERVERS: (
        {"servers": ["1.1.1.1", "8.8.8.8"]},
        ["servers=1.1.1.1,8.8.8.8"],
    ),
}


def settled_export(client: RouterClient, timeout_s: float = 120) -> list[str]:
    """The config once it has stopped changing (RouterOS adds defaults shortly after boot)."""
    deadline = time.monotonic() + timeout_s
    previous, stable_polls = client.export(), 0
    while stable_polls < 3 and time.monotonic() < deadline:
        time.sleep(3)
        current = client.export()
        stable_polls = stable_polls + 1 if current == previous else 0
        previous = current
    return previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="write machine-readable results to this file")
    args = parser.parse_args()

    try:
        client = RouterClient.chr()
        baseline = settled_export(client)
    except RouterError as exc:
        print(f"CHR not reachable: {exc}", file=sys.stderr)
        return 1

    results = []
    for template_id in (t for t in load_templates() if t is not TemplateId.NONE):
        params, expected = SAMPLES[template_id]
        started = time.monotonic()
        try:
            result = dry_run(template_id, params, client)
            added = "\n".join(result.diff)
            missing = [marker for marker in expected if marker not in added]
            ok = result.ok and not missing
            detail = result.log + (f"\nMissing from the change: {missing}" if missing else "")
        except RouterError as exc:
            ok, detail = False, f"Router error: {exc}"
        restored = client.export() == baseline
        ok = ok and restored
        seconds = round(time.monotonic() - started, 1)
        print(f"{'PASS' if ok else 'FAIL'}  {template_id.value:15} {seconds:5.1f}s", flush=True)
        if not ok:
            print("      " + detail.replace("\n", "\n      "))
        results.append({"template": template_id.value, "ok": ok, "seconds": seconds, "log": detail})

    if args.json:
        with open(args.json, "w", encoding="utf-8") as output:
            json.dump(results, output, indent=2)
    failed = [r["template"] for r in results if not r["ok"]]
    print(f"{len(results) - len(failed)}/{len(results)} templates passed on CHR")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
