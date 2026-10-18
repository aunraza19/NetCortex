import re
from uuid import uuid4

import httpx
import pytest
from netcortex_core import FixPlan, Settings, TemplateId
from netcortex_fixes import (
    ApplyFailed,
    RouterClient,
    RouterError,
    apply,
    checker,
    dry_run,
    failure_reason,
    render,
    tag_for,
)

BASELINE = ["/ip dns set servers=192.0.2.53", "/queue simple add name=sub-10.0.0.42"]
QUEUE = {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 10}
PRIORITY = {"uplink": "ether1", "uplink_mbps": 160}


class FakeRouter:
    """Keeps config lines like RouterOS: `add` rejects a taken name, `remove [find x="y"]`
    deletes only lines containing y."""

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
            name = re.search(r' name="?([^" ]+)', line)
            if self.fail_on and self.fail_on in line:
                raise RouterError(f"{line!r} failed: bad command name")
            if " add " in line and not self.ignore_apply:
                if name and any(f"name={name[1]}" in c.replace('"', "") for c in self.config):
                    raise RouterError(f"{line!r} failed: already have such name")
                self.config.append(line)
            elif " remove " in line and not self.ignore_rollback:
                target = re.search(r'\[find \w+="([^"]+)"\]', line)[1]
                self.config = [c for c in self.config if target not in c]
            elif line.startswith("/ip dns set"):  # replaced in place, like a real export
                self.config = [line if c.startswith("/ip dns set") else c for c in self.config]
        return "ok"

    def export(self):
        return list(self.config)

    def get(self, path):
        return {"servers": "192.0.2.53"}


def test_dry_run_passes_when_the_fix_applies_and_rolls_back_exactly():
    router = FakeRouter()
    result = dry_run("queue_limit", QUEUE, router, tag="nc-1a2b3c4d")
    assert result.ok and result.reason == ""
    assert result.diff == [
        '+/queue simple add name="nc-1a2b3c4d-limit-10.0.0.42" target=10.0.0.42 '
        'max-limit=5M/10M comment="nc-1a2b3c4d:queue_limit"'
    ]
    assert result.log.endswith("Result: passed") and router.config == BASELINE


def test_dry_run_reads_router_params_for_rollback():
    result = dry_run("dns_servers", {"servers": ["1.1.1.1"]}, FakeRouter())
    assert result.params["previous_servers"] == ["192.0.2.53"]
    assert result.rollback.startswith("/ip dns set servers=192.0.2.53")
    assert result.ok


def test_dry_run_fails_when_rollback_leaves_changes():
    result = dry_run("queue_limit", QUEUE, FakeRouter(ignore_rollback=True))
    assert not result.ok
    assert "NOT RESTORED" in result.log
    assert result.reason == "not restored the config exactly"


def test_dry_run_fails_when_the_fix_changes_nothing():
    result = dry_run("queue_limit", QUEUE, FakeRouter(ignore_apply=True))
    assert not result.ok and result.reason == "not changed the config"


def test_a_rejected_first_command_changes_nothing_and_rolls_nothing_back():
    router = FakeRouter(fail_on="/queue simple add")
    result = dry_run("queue_limit", QUEUE, router)
    assert not result.ok and "nothing was applied" in result.reason
    assert not any(" remove " in line for line in router.ran)
    assert result.log.endswith(f"Result: FAILED: {result.reason}")


def test_an_existing_object_with_the_same_name_is_never_touched():
    router = FakeRouter()
    theirs = '/queue simple add name="nc-1a2b3c4d-limit-10.0.0.42" target=10.0.0.42'
    router.config.append(theirs)
    result = dry_run("queue_limit", QUEUE, router, tag="nc-1a2b3c4d")
    assert not result.ok and "already exist" in result.reason
    assert router.config == [*BASELINE, theirs]
    assert not any(" remove " in line for line in router.ran)


def test_a_partly_applied_fix_undoes_only_its_own_objects():
    router = FakeRouter(fail_on="/queue tree add")  # the two mangle rules go in first
    router.config.append('/ip firewall mangle add comment="netcortex:priority_queue"')
    before = list(router.config)
    result = dry_run("priority_queue", PRIORITY, router, tag="nc-1a2b3c4d")
    assert not result.ok and "the partial change was rolled back" in result.reason
    assert router.config == before  # including the older, untagged netcortex rule


def test_fixes_for_two_incidents_do_not_collide():
    router = FakeRouter()
    first, second = uuid4(), uuid4()
    applied = plan(incident_id=first, commands=render("queue_limit", QUEUE, tag_for(first))[0])
    apply(applied, router, Settings(_env_file=None))
    result = dry_run("queue_limit", QUEUE, router, tag=tag_for(second))
    assert result.ok and applied.commands in router.config  # the first fix stays in place


def test_a_failed_apply_says_why():
    router = FakeRouter(fail_on="/queue simple add")
    with pytest.raises(ApplyFailed, match="bad command name; nothing was applied"):
        apply(plan(), router, Settings(_env_file=None))


def test_template_none_needs_no_router():
    result = dry_run("none", {}, None)
    assert result.ok and result.commands == "" and result.diff == []


def plan(**changes) -> FixPlan:
    values = dict(
        incident_id=uuid4(), template_id=TemplateId.QUEUE_LIMIT, params=QUEUE,
        commands='/queue simple add name="x"', rollback='/queue simple remove [find name="x"]',
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
    assert f"{tag_for(incident_id)}-limit-10.0.0.42" in result.commands and result.rollback
    assert failure_reason(result) == ""


def test_failure_reason_comes_from_the_dry_run_log():
    failed = plan(dry_run_ok=False, dry_run_log="...\nResult: FAILED: not changed the config")
    assert failure_reason(failed) == "not changed the config"


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
