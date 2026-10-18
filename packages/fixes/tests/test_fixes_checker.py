from uuid import uuid4

import httpx
import pytest
from netcortex_core import FixPlan, Settings, TemplateId
from netcortex_fixes import RouterClient, RouterError, apply, checker, dry_run

BASELINE = ["/ip dns set servers=192.0.2.53", "/queue simple add name=sub-10.0.0.42"]
QUEUE = {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 10}


class FakeRouter:
    """Keeps config lines; `add` commands append, `remove [find name=...]` deletes."""

    def __init__(self, *, ignore_rollback=False, ignore_apply=False, fail_on=None):
        self.config = list(BASELINE)
        self.ignore_rollback, self.ignore_apply, self.fail_on = (
            ignore_rollback,
            ignore_apply,
            fail_on,
        )
        self.ran = []

    def run(self, script):
        for line in script.splitlines():
            self.ran.append(line)
            if self.fail_on and self.fail_on in line:
                raise RouterError(f"{line!r} failed: bad command name")
            if " add " in line and not self.ignore_apply:
                self.config.append(line)
            elif " remove " in line and not self.ignore_rollback:
                self.config = [c for c in self.config if "netcortex" not in c]
            elif line.startswith("/ip dns set"):  # replaced in place, like a real export
                self.config = [line if c.startswith("/ip dns set") else c for c in self.config]
        return "ok"

    def export(self):
        return list(self.config)

    def get(self, path):
        return {"servers": "192.0.2.53"}


def test_dry_run_passes_when_the_fix_applies_and_rolls_back_exactly():
    router = FakeRouter()
    result = dry_run("queue_limit", QUEUE, router)
    assert result.ok
    assert result.diff == [
        '+/queue simple add name="netcortex-limit-10.0.0.42" target=10.0.0.42 '
        'max-limit=5M/10M comment="netcortex:queue_limit"'
    ]
    assert "config restored exactly: yes" in result.log


def test_dry_run_reads_router_params_for_rollback():
    result = dry_run("dns_servers", {"servers": ["1.1.1.1"]}, FakeRouter())
    assert result.params["previous_servers"] == ["192.0.2.53"]
    assert result.rollback.startswith("/ip dns set servers=192.0.2.53")
    assert result.ok


def test_dry_run_fails_when_rollback_leaves_changes():
    result = dry_run("queue_limit", QUEUE, FakeRouter(ignore_rollback=True))
    assert not result.ok
    assert "NOT RESTORED" in result.log and "config restored exactly: NO" in result.log


def test_dry_run_fails_when_the_fix_changes_nothing():
    result = dry_run("queue_limit", QUEUE, FakeRouter(ignore_apply=True))
    assert not result.ok and "changed the config: NO" in result.log


def test_dry_run_fails_and_still_rolls_back_when_a_command_is_rejected():
    router = FakeRouter(fail_on="/queue simple add")
    result = dry_run("queue_limit", QUEUE, router)
    assert not result.ok and "APPLY FAILED" in result.log
    assert any(" remove " in line for line in router.ran)  # rollback still attempted


def test_template_none_needs_no_router():
    result = dry_run("none", {}, None)
    assert result.ok and result.commands == "" and result.diff == []


def plan(**changes) -> FixPlan:
    values = dict(
        incident_id=uuid4(), template_id=TemplateId.QUEUE_LIMIT, params=QUEUE,
        commands="/queue simple add name=x", rollback="/queue simple remove [find name=x]",
        dry_run_ok=True, decision="approved",
    )  # fmt: skip
    return FixPlan(**(values | changes))


def test_apply_runs_only_approved_tested_plans_on_chr():
    router = FakeRouter()
    settings = Settings(_env_file=None)
    assert apply(plan(), router, settings) == "ok"
    with pytest.raises(RouterError, match="not been approved"):
        apply(plan(decision=None), router, settings)
    with pytest.raises(RouterError, match="did not pass its dry run"):
        apply(plan(dry_run_ok=False), router, settings)


def test_apply_refuses_a_real_router_target():
    real = Settings(_env_file=None, apply_target="real")
    with pytest.raises(RouterError, match="Only APPLY_TARGET=chr"):
        apply(plan(), None, real)


def test_check_fix_stores_the_dry_run_in_fix_plans(monkeypatch):
    stored = []

    class Pool:
        def connection(self):
            from contextlib import nullcontext

            return nullcontext("conn")

    monkeypatch.setattr(checker.db, "get_pool", lambda settings=None: Pool())
    monkeypatch.setattr(checker.db, "insert_fix_plan", lambda conn, p: stored.append(p))
    incident_id = uuid4()
    result = checker.check_fix(incident_id, "queue_limit", QUEUE, FakeRouter())
    assert stored == [result]
    assert result.incident_id == incident_id and result.dry_run_ok
    assert "netcortex-limit-10.0.0.42" in result.commands and result.rollback


def client_with(handler) -> RouterClient:
    client = RouterClient("http://chr.invalid/rest", "tester", "not-a-real-password")
    client._http = httpx.Client(
        base_url="http://chr.invalid/rest", transport=httpx.MockTransport(handler)
    )
    return client


def test_client_treats_error_text_in_a_200_reply_as_a_failure():
    def handler(request):
        return httpx.Response(200, json={"ret": "invalid or unexpected argument base"})

    with pytest.raises(RouterError, match="invalid or unexpected"):
        client_with(handler).run("/ip dns set servers=not-an-ip")


def test_client_reports_http_errors_with_routeros_detail():
    def handler(request):
        return httpx.Response(400, json={"error": 400, "detail": "bad command name bogus"})

    with pytest.raises(RouterError, match="bad command name bogus"):
        client_with(handler).run("/bogus")


def test_export_drops_comments_and_blank_lines():
    def handler(request):
        text = "# 2026-10-18 by RouterOS 7.24.5\r\n/ip dns set servers=192.0.2.53\r\n\r\n"
        return httpx.Response(200, json={"ret": text})

    assert client_with(handler).export() == ["/ip dns set servers=192.0.2.53"]
