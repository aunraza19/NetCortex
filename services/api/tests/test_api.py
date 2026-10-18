import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from netcortex_api import main
from netcortex_api.store import DemoStore, health_of
from netcortex_core import Cause, DetectionResult, Incident, IncidentStatus

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    waiting, done = uuid4(), uuid4()
    detection = DetectionResult(
        is_anomaly=True, score=0.9, cause_guess=Cause.HEAVY_USER, cause_confidence=0.75,
        model="rules-v0", mode="mock",
    )  # fmt: skip

    def incident(incident_id, status):
        return Incident(id=incident_id, site_id="sim-tower", opened_at=NOW, status=status,
                        cause=Cause.HEAVY_USER, confidence=0.75, detection=detection,
                        source="sim").model_dump(mode="json")  # fmt: skip

    snapshot = {
        "sites": [{"id": "sim-tower", "name": "Sim Tower", "health": "degraded"}],
        "series": [{"series_key": "probe:8.8.8.8:rtt_ms", "points": [], "forecast": []}],
        "incidents": [
            {"incident": incident(waiting, "awaiting_approval"), "fix_plan": None, "timeline": []},
            {"incident": incident(done, "resolved"), "fix_plan": None, "timeline": []},
        ],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    monkeypatch.setattr(main, "store", DemoStore(path))
    test_client = TestClient(main.app)
    test_client.ids = {"waiting": waiting, "done": done}
    return test_client


def test_health_and_openapi(client):
    assert client.get("/health").json()["status"] == "ok"
    paths = client.get("/openapi.json").json()["paths"]
    for path in ["/sites", "/metrics", "/incidents", "/incidents/{incident_id}",
                 "/incidents/{incident_id}/approve", "/incidents/{incident_id}/reject",
                 "/demo/scenarios", "/stream"]:  # fmt: skip
        assert path in paths
    assert "/incidents/{incident_id}/voice" not in paths


def test_incidents_list_filter_and_detail(client):
    assert len(client.get("/incidents").json()) == 2
    waiting = client.get("/incidents", params={"status": "awaiting_approval"}).json()
    assert [i["id"] for i in waiting] == [str(client.ids["waiting"])]
    assert client.get(f"/incidents/{uuid4()}").status_code == 404


def test_approve_only_when_awaiting_approval(client):
    reply = client.post(f"/incidents/{client.ids['waiting']}/approve", json={"decided_by": "test"})
    assert reply.status_code == 202 and reply.json()["decision"] == "approved"
    detail = client.get(f"/incidents/{client.ids['waiting']}").json()
    assert detail["incident"]["status"] == IncidentStatus.RESOLVED.value
    again = client.post(f"/incidents/{client.ids['done']}/reject")
    assert again.status_code == 409


def test_metrics_returns_saved_series(client):
    reply = client.get(
        "/metrics", params={"site_id": "sim-tower", "series": "probe:8.8.8.8:rtt_ms"}
    )
    assert reply.status_code == 200 and reply.json()[0]["series_key"] == "probe:8.8.8.8:rtt_ms"


def test_site_health_rules():
    assert health_of([], 0) == "unknown"
    assert health_of([("1.1.1.1", None, 100.0), ("10.0.0.1", 2.0, 0.0)], 1) == "down"
    assert health_of([("1.1.1.1", 20.0, 0.0)], 1) == "degraded"
    assert health_of([("1.1.1.1", 20.0, 0.0)], 0) == "ok"
