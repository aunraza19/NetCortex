import asyncio
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest
import sentry_sdk
from netcortex_agent import stub_injector
from netcortex_agent.stub_detector import detect
from netcortex_core import (
    IFACE_COLUMNS,
    PROBE_COLUMNS,
    SUBSCRIBER_COLUMNS,
    Cause,
    MetricsWindow,
    TemplateId,
)
from netcortex_worker import activities
from netcortex_worker.main import run_traced, trace_id_for
from sentry_sdk.transport import Transport

NOW = datetime.now(UTC).replace(microsecond=0)


def window(spans: list[tuple[datetime, datetime, Cause | None]]) -> MetricsWindow:
    rng, parts = random.Random(3), []
    for start, end, cause in spans:
        parts.append(stub_injector._rows(start, end, cause, rng))
    frames = [
        pd.DataFrame([r.model_dump() for p in parts for r in p[i]], columns=list(cols))
        for i, cols in enumerate((PROBE_COLUMNS, IFACE_COLUMNS, SUBSCRIBER_COLUMNS))
    ]
    return MetricsWindow(as_of=NOW, probe_metrics=frames[0], iface_metrics=frames[1],
                         subscriber_metrics=frames[2])  # fmt: skip


def test_incident_workflows_share_a_trace_named_after_the_incident():
    incident_id = uuid4()
    assert trace_id_for(f"incident-{incident_id}") == incident_id.hex
    assert trace_id_for("monitor-sim-tower") is None


@pytest.fixture
def sent():
    """Transactions Sentry would send, kept here instead of sent."""
    transactions = []

    class Keep(Transport):
        def capture_envelope(self, envelope):
            transactions.extend(i.payload.json for i in envelope.items if i.type == "transaction")

    sentry_sdk.init(transport=Keep(), traces_sample_rate=1.0, default_integrations=False)
    yield transactions
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def test_concurrent_activities_keep_their_spans_apart(sent):
    incident_id = uuid4()
    incident_running, monitor_running, dry_run_done = (asyncio.Event() for _ in range(3))

    async def check_fix():  # an incident activity; the monitor starts while it runs
        incident_running.set()
        await monitor_running.wait()
        with sentry_sdk.start_span(op="netcortex.check_fix", name="dry run queue_limit"):
            pass
        dry_run_done.set()

    async def monitor_site():
        await incident_running.wait()
        monitor_running.set()
        await dry_run_done.wait()
        with sentry_sdk.start_span(op="netcortex.detect", name="detect home-lab"):
            pass

    async def worker():
        # The worker's own task has used both scopes before any activity starts.
        sentry_sdk.get_current_scope().set_tag("service", "worker")
        sentry_sdk.get_isolation_scope().set_tag("service", "worker")
        await asyncio.gather(
            run_traced(f"incident-{incident_id}", "check_fix", check_fix),
            run_traced("monitor-home-lab", "monitor_site", monitor_site),
        )

    asyncio.run(worker())
    spans = {t["transaction"]: [s["description"] for s in t["spans"]] for t in sent}
    assert spans == {"check_fix": ["dry run queue_limit"], "monitor_site": ["detect home-lab"]}
    [incident] = [t for t in sent if t["transaction"] == "check_fix"]
    assert incident["contexts"]["trace"]["trace_id"] == incident_id.hex


def _verify_with(monkeypatch, recovered: bool, since_fix=timedelta(minutes=5), applied_at=None):
    opened = NOW - timedelta(minutes=6)
    after = None if recovered else Cause.HEAVY_USER
    data = window([
        (opened - timedelta(minutes=10), opened - timedelta(minutes=4), None),
        (opened - timedelta(minutes=4), NOW - since_fix, Cause.HEAVY_USER),
        (NOW - since_fix, NOW + timedelta(seconds=10), after),
    ])  # fmt: skip
    detection = detect("sim-tower", window([
        (opened - timedelta(minutes=30), opened - timedelta(minutes=3), None),
        (opened - timedelta(minutes=3), opened, Cause.HEAVY_USER),
    ]).model_copy(update={"as_of": opened}), MetricsWindow(as_of=opened))  # fmt: skip

    class Pool:
        def connection(self):
            from contextlib import nullcontext

            return nullcontext(None)

    monkeypatch.setattr(activities.db, "get_pool", lambda settings=None: Pool())
    monkeypatch.setattr(activities.db, "fetch_window", lambda conn, site, start, end: data)
    return activities._verify("sim-tower", detection, TemplateId.QUEUE_LIMIT, opened, applied_at)


def test_verify_passes_when_latency_drops_after_the_fix(monkeypatch):
    result = _verify_with(monkeypatch, recovered=True)
    assert result.improved, result.detail
    assert "rtt_ms" in result.detail


def test_verify_fails_when_latency_stays_high(monkeypatch):
    result = _verify_with(monkeypatch, recovered=False)
    assert not result.improved, result.detail


def test_a_short_watch_is_judged_only_on_the_time_since_the_fix(monkeypatch):
    minute = timedelta(seconds=60)  # VERIFY_WAIT_S=60: the last 2 minutes would mix in pre-fix data
    mixed = _verify_with(monkeypatch, True, since_fix=minute)
    clean = _verify_with(monkeypatch, True, since_fix=minute, applied_at=NOW - minute)

    def after(result) -> float:  # "probe:1.1.1.1:rtt_ms: 102.6 -> 24.9 (...)"
        return float(result.detail.split("-> ")[1].split()[0])

    assert clean.improved and after(clean) < 0.6 * after(mixed)


def test_stale_data_skips_detection(monkeypatch):
    old = window([(NOW - timedelta(minutes=40), NOW - timedelta(minutes=10), None)])

    class Pool:
        def connection(self):
            from contextlib import nullcontext

            return nullcontext(None)

    monkeypatch.setattr(activities.db, "get_pool", lambda settings=None: Pool())
    monkeypatch.setattr(activities.db, "fetch_window", lambda conn, site, start, end: old)
    result = activities._monitor("sim-tower")
    assert result.status == "skipped" and "stale" in result.reason


def test_no_second_opinion_without_tabpfn(monkeypatch):
    from netcortex_agent import modules

    monkeypatch.setattr(modules, "_tabpfn_ready", False)
    monkeypatch.setattr(activities.db, "get_pool", lambda: pytest.fail("no DB needed"))
    assert activities._second_opinion(uuid4(), "sim-tower", NOW) is None
