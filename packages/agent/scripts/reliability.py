"""How often does Gemma produce a valid report with the right template, on e2e-like inputs?

    uv run python packages/agent/scripts/reliability.py [--heavy 5 --down 3 --dns 3]

Builds each incident the way the live run sees it, without the database: the stand-in
injector's rows for sim-tower (30 min normal, then the incident for ONSET), the stand-in
detector, and the agent with the worker's settings (thinking off, temperature 0.2).
Needs the model server (OLLAMA_BASE_URL).
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta

import pandas as pd
from netcortex_agent import stub_detector, stub_injector
from netcortex_agent.agent import run_investigation
from netcortex_core import (
    IFACE_COLUMNS,
    PROBE_COLUMNS,
    SUBSCRIBER_COLUMNS,
    Cause,
    MetricsWindow,
)

ONSET = timedelta(seconds=90)  # incidents opened 60-150 s after injection in the e2e runs
SITE = stub_injector.SIM_SITE


def frames(parts, as_of: datetime) -> MetricsWindow:
    data = [
        pd.DataFrame([r.model_dump() for p in parts for r in p[i]], columns=list(columns))
        for i, columns in enumerate((PROBE_COLUMNS, IFACE_COLUMNS, SUBSCRIBER_COLUMNS))
    ]
    return MetricsWindow(
        as_of=as_of, probe_metrics=data[0], iface_metrics=data[1], subscriber_metrics=data[2]
    )


def incident(cause: Cause, seed: int):
    rng = random.Random(seed)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    start = now - ONSET
    window = frames(
        [
            stub_injector._rows(now - timedelta(minutes=30), start, None, rng),
            stub_injector._rows(start, now + timedelta(seconds=1), cause, rng),
        ],
        now,
    )
    return window, stub_detector.detect(SITE.id, window, frames([], now - timedelta(minutes=30)))


def right_params(cause: Cause, params: dict) -> bool:
    template, expected, _ = stub_injector.EXPECTED[cause]
    if cause is Cause.DNS_SLOW:
        return "192.0.2.53" not in params.get("servers", ["192.0.2.53"])
    return all(params.get(key) == value for key, value in expected.items())


async def main(counts: dict[Cause, int]) -> None:
    rows = []
    for cause, n in counts.items():
        for run in range(n):
            window, detection = incident(cause, seed=run)
            report, stats = await run_investigation(SITE.id, detection, window, site=SITE)
            template = stub_injector.EXPECTED[cause][0]
            ok = not stats.fell_back and report.template_id == template
            ok_params = ok and right_params(cause, report.template_params)
            rows.append((cause, ok, ok_params, stats))
            print(
                f"{cause.value:12} run{run + 1} {stats.seconds:5.1f}s "
                f"detector={detection.cause_guess.value:12} "
                f"template={report.template_id.value:15} right={'Y' if ok else 'n'} "
                f"params={'Y' if ok_params else 'n'} retries={stats.output_retries} "
                f"fallback={stats.fell_back} {report.template_params}",
                flush=True,
            )
            for reason in stats.retry_reasons:
                print(f"    retry: {reason}")
    n = len(rows)
    print(
        f"\n{sum(r[1] for r in rows)}/{n} valid with the right template, "
        f"{sum(r[2] for r in rows)}/{n} also with the right params; "
        f"{sum(r[3].fell_back for r in rows)}/{n} failed validation twice (fallback), "
        f"{sum(r[3].output_retries > 0 for r in rows)}/{n} needed a retry"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--heavy", type=int, default=5)
    parser.add_argument("--down", type=int, default=3)
    parser.add_argument("--dns", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(
        main({Cause.HEAVY_USER: args.heavy, Cause.UPLINK_DOWN: args.down, Cause.DNS_SLOW: args.dns})
    )
