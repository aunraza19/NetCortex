from types import SimpleNamespace

import pytest
from netcortex_agent import facts, modules, stub_detector, stub_injector
from netcortex_core import Cause, DetectionResult, Inject, SeriesForecast, conforms

TABPFN = DetectionResult(
    is_anomaly=True, score=0.91, cause_guess=Cause.UPLINK_CONGESTION, cause_confidence=0.6,
    model="tabpfn-cloud:v3.5", mode="cloud",
    series=[SeriesForecast(series_key="iface:ether1:util_pct", points=[])],
)  # fmt: skip


@pytest.fixture
def calls(monkeypatch):
    """Which injector ran, with the partner's simulator knowing only north-tower."""
    seen = []
    partner = SimpleNamespace(
        sites=lambda: {"sites": [{"id": "north-tower"}, {"id": "sim-tower"}]},
        inject=lambda site_id, *args: seen.append(("partner", site_id)),
    )
    monkeypatch.setattr(modules, "_simgen", partner)
    monkeypatch.setattr(stub_injector, "inject", lambda site_id, *a: seen.append(("ours", site_id)))
    return seen


def test_sim_tower_and_unknown_sites_use_our_injector(calls):
    for site_id in ("sim-tower", "north-tower", "home-lab"):
        modules.inject(site_id, Cause.HEAVY_USER, 5, None)
    assert calls == [("ours", "sim-tower"), ("partner", "north-tower"), ("ours", "home-lab")]
    assert conforms(modules.inject, Inject)


def test_rules_always_trigger_incidents():
    assert modules.detect is stub_detector.detect


def test_tabpfn_is_used_only_after_it_was_configured(monkeypatch):
    monkeypatch.setattr(modules, "_tabpfn_ready", False)
    monkeypatch.setattr(modules, "_detector", SimpleNamespace(
        configure_detector=lambda artifact: (_ for _ in ()).throw(RuntimeError("no token")),
        detect=lambda *args: TABPFN,
    ))  # fmt: skip
    assert modules.tabpfn_detect("sim-tower", None, None) is None
    assert modules.configure_tabpfn("missing.json") is False
    assert not modules.tabpfn_ready()

    modules._detector.configure_detector = lambda artifact: None
    assert modules.configure_tabpfn("artifact.json") is True
    assert modules.tabpfn_detect("sim-tower", None, None) is TABPFN


def test_without_the_partner_package_tabpfn_stays_off(monkeypatch):
    monkeypatch.setattr(modules, "_tabpfn_ready", False)
    monkeypatch.setattr(modules, "_detector", None)
    assert modules.configure_tabpfn("artifact.json") is False


def test_second_opinion_reaches_the_prompt_and_the_report():
    prompt = facts.second_opinion_prompt(TABPFN)
    assert "uplink_congestion (confidence 0.60)" in prompt
    assert "iface:ether1:util_pct" in prompt
    assert facts.second_opinion_evidence(TABPFN) == (
        "TabPFN second opinion: uplink_congestion (confidence 0.60, anomaly score 0.91)"
    )
