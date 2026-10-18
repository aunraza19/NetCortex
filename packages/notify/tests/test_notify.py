from datetime import UTC, datetime

import httpx
import pytest
from netcortex_notify import service
from netcortex_notify.service import _check_news, _read_body, _recent_date, _safe_url


def test_response_reader_enforces_total_deadline(monkeypatch):
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(ticks))

    class Response:
        def iter_bytes(self):
            yield b"piece"

    with pytest.raises(httpx.TimeoutException, match="total deadline"):
        _read_body(Response(), max_bytes=100, total_seconds=1)


def test_news_does_not_flag_unrelated_or_non_outage_results():
    data = {
        "news_results": [
            {
                "title": "Unrelated story outage elsewhere",
                "link": "https://news.example/a",
                "date": "1 hour ago",
            },
            {
                "title": "ExampleISP service is degraded",
                "link": "https://status.example/b",
                "date": "1 hour ago",
            },
        ]
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    )
    result = _check_news("ExampleISP", "game", api_key="test", client=client)
    assert result["outage_reported"] is True
    client.close()
    data["news_results"][1]["title"] = "ExampleISP launches new plans"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    )
    result = _check_news("ExampleISP", "game", api_key="test", client=client)
    assert result["outage_reported"] is False
    client.close()


def test_news_timeout_is_unavailable():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("simulated"))
        )
    )
    result = _check_news("isp", "target", api_key="test", client=client)
    assert result["available"] is False
    assert "unavailable" in result["summary"].lower()
    client.close()


def test_news_missing_key_and_unsafe_urls_are_not_outages():
    assert _check_news("isp", "game", api_key=None)["available"] is False
    assert _safe_url("javascript:alert(1)") is None
    assert _safe_url("//evil.example") is None
    assert _safe_url("https://example.com/outage") == "https://example.com/outage"


def test_public_check_news_preserves_unavailable_state(monkeypatch):
    from netcortex_core import Settings

    monkeypatch.setattr(service, "_load_settings", lambda: Settings(_env_file=None))
    result = service.check_news("isp", None)
    assert result.outage_reported is False
    assert "unavailable" in result.summary.lower()


def test_recent_dates_and_malformed_search_response():
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    assert _recent_date("2 hours ago", now)
    assert _recent_date("2026-10-18T01:00:00Z", now)
    assert not _recent_date("3 days ago", now)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"organic_results": "bad"})
        )
    )
    assert _check_news("isp", "game", api_key="secret", client=client)["available"] is False
    client.close()


def test_news_filters_malformed_items_and_relative_urls():
    data = {
        "news_results": [
            {"title": "recent", "link": "https://status.example/a", "date": "1 hour ago"},
            {"title": "unsafe", "link": "javascript:evil", "date": "1 hour ago"},
            {"title": "old", "link": "https://status.example/old", "date": "3 days ago"},
            "bad",
        ]
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    )
    result = _check_news(
        "isp", "target", api_key="secret", client=client, now=datetime(2026, 10, 18, 12, tzinfo=UTC)
    )
    assert result["available"] is True
    assert [x["title"] for x in result["links"]] == ["recent"]
    client.close()


def test_news_rate_limit_is_unavailable():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    result = _check_news("isp", "target", api_key="secret", client=client)
    assert result["available"] is False
    client.close()
