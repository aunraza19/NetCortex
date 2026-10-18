import pytest
from netcortex_core import Cause, TemplateId
from netcortex_fixes import ParamError, load_templates, render, templates_for, validate

VALID = {
    "queue_limit": {"target": "10.0.0.42", "upload_mbps": 2, "download_mbps": 10},
    "failover_route": {"primary_gateway": "192.0.2.1", "backup_gateway": "198.51.100.1"},
    "priority_queue": {"uplink": "ether1", "uplink_mbps": 90},
    "dns_servers": {"servers": ["1.1.1.1", "8.8.8.8"], "previous_servers": ["192.0.2.53"]},
}


def test_every_template_loads_and_is_marked_untested():
    templates = load_templates()
    assert set(templates) == set(TemplateId)
    for template_id, template in templates.items():
        if template_id is not TemplateId.NONE:
            assert template.status == "untested on CHR"
            assert template.apply and template.rollback and template.verify


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (Cause.HEAVY_USER, ["queue_limit", "none"]),
        (Cause.UPLINK_DOWN, ["failover_route", "none"]),
        (Cause.UPLINK_CONGESTION, ["priority_queue", "none"]),
        (Cause.DNS_SLOW, ["dns_servers", "none"]),
        (Cause.UPSTREAM_DEGRADATION, ["none"]),
        (Cause.WIRELESS_INTERFERENCE, ["none"]),
    ],
)
def test_templates_for_cause_match_the_scenario_catalog(cause, expected):
    assert [t.id.value for t in templates_for(cause)] == expected


@pytest.mark.parametrize("template_id", VALID)
def test_valid_params_render_apply_and_rollback(template_id):
    apply, rollback = render(template_id, VALID[template_id])
    assert apply.startswith("/") and rollback.startswith("/")
    assert "{{" not in apply + rollback


def test_rendered_commands_contain_only_validated_values():
    apply, rollback = render("queue_limit", {**VALID["queue_limit"], "target": "10.0.0.40/29"})
    assert "target=10.0.0.40/29 max-limit=2M/10M" in apply
    assert 'name="netcortex-limit-10.0.0.40_29"' in rollback


def test_defaults_are_filled_in():
    apply, _ = render("failover_route", VALID["failover_route"])
    assert "distance=2" in apply
    assert (
        "dst-port=3074,3478-3480,27015-27050"
        in render("priority_queue", VALID["priority_queue"])[0]
    )


@pytest.mark.parametrize(
    ("template_id", "params", "message"),
    [
        ("queue_limit", {**VALID["queue_limit"], "upload_mbps": 0}, "between 1 and 1000"),
        ("queue_limit", {**VALID["queue_limit"], "upload_mbps": True}, "integer"),
        ("queue_limit", {**VALID["queue_limit"], "target": "10.0.0.42; /system reboot"}, "IPv4"),
        ("queue_limit", {**VALID["queue_limit"], "target": "10.0.0.1/29"}, "IPv4"),
        ("queue_limit", {"target": "10.0.0.42"}, "missing param"),
        ("queue_limit", {**VALID["queue_limit"], "comment": "x"}, "unknown params"),
        (
            "priority_queue",
            {**VALID["priority_queue"], "uplink": 'ether1" ; /system reset'},
            "match",
        ),
        ("priority_queue", {**VALID["priority_queue"], "game_ports": "53;80"}, "match"),
        ("dns_servers", {"servers": []}, "1 to 3"),
        ("dns_servers", {"servers": ["dns.google"]}, "IPv4"),
    ],
)
def test_bad_params_are_rejected(template_id, params, message):
    with pytest.raises(ParamError, match=message):
        validate(template_id, params)


def test_none_takes_no_params_and_renders_nothing():
    assert render("none", {}) == ("", "")
    with pytest.raises(ParamError):
        validate("none", {"ip": "10.0.0.42"})


def test_router_filled_params_are_hidden_from_the_agent():
    dns = load_templates()[TemplateId.DNS_SERVERS]
    assert list(dns.agent_params()) == ["servers"]


HEAVY = {"current_download_mbps": 140.0, "current_upload_mbps": 14.0}


def test_queue_limit_cap_must_be_at_most_half_the_current_rate():
    ok = {**VALID["queue_limit"], "download_mbps": 70}
    assert validate("queue_limit", ok, HEAVY)["download_mbps"] == 70
    too_high = {**VALID["queue_limit"], "download_mbps": 140}
    with pytest.raises(ParamError) as error:
        validate("queue_limit", too_high, HEAVY)
    message = str(error.value)
    assert "not clearly below 10.0.0.42's current download rate of 140 Mbit/s" in message
    assert "at most 70" in message


def test_queue_limit_checks_the_busier_direction():
    uploader = {"current_download_mbps": 3.0, "current_upload_mbps": 60.0}
    params = {**VALID["queue_limit"], "upload_mbps": 50, "download_mbps": 2}
    with pytest.raises(ParamError, match="upload_mbps=50 .* at most 30"):
        validate("queue_limit", params, uploader)


def test_queue_limit_rejects_capping_a_light_user():
    with pytest.raises(ParamError, match="only uses 0.8 Mbit/s"):
        validate("queue_limit", VALID["queue_limit"], {"current_download_mbps": 0.8})


def test_queue_limit_checks_skip_without_observations():
    params = {**VALID["queue_limit"], "download_mbps": 900}
    assert validate("queue_limit", params)["download_mbps"] == 900
    assert validate("queue_limit", params, {})["download_mbps"] == 900
