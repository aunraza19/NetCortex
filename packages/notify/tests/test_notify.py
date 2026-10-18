import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from netcortex_notify import service
from netcortex_notify.service import _check_news, _read_body, _recent_date, _safe_url, _speak


def test_speak_missing_keys_and_validation():
    assert _speak("alert", "en", api_key=None, voice_id=None) == b""
    with pytest.raises(ValueError):
        _speak("hello", "fr", api_key=None, voice_id=None)
    with pytest.raises(ValueError):
        _speak("word " * 41, "en", api_key=None, voice_id=None)


def test_speak_validates_audio_and_propagates_rate_limit():
    def audio(request):
        assert request.url.params["output_format"] == "mp3_44100_128"
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"mp3")

    client = httpx.Client(transport=httpx.MockTransport(audio))
    assert _speak("short alert", "ur", api_key="test", voice_id="voice", client=client) == b"mp3"
    client.close()


def test_speak_non_audio_timeout_and_public_failure_are_safe(monkeypatch):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"{}"
            )
        )
    )
    with pytest.raises(RuntimeError, match="non-audio"):
        _speak("short alert", "en", api_key="test", voice_id="voice", client=client)
    client.close()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("simulated"))
        )
    )
    with pytest.raises(httpx.ReadTimeout):
        _speak("short alert", "en", api_key="test", voice_id="voice", client=client)
    client.close()
    monkeypatch.setattr(
        service,
        "_load_settings",
        lambda: SimpleNamespace(elevenlabs_api_key="test", elevenlabs_voice_id="voice"),
    )
    monkeypatch.setattr(
        service,
        "_speak",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("simulated")),
    )
    assert service.speak("short alert", "en") == b""


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
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    with pytest.raises(RuntimeError, match="rate limit"):
        _speak("short alert", "en", api_key="test", voice_id="voice", client=client)
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
    class NewsCheck:
        def __init__(self, *, outage_reported, summary, items):
            self.outage_reported = outage_reported
            self.summary = summary
            self.items = items

    class NewsItem:
        def __init__(self, **fields):
            self.fields = fields

    core = SimpleNamespace(NewsCheck=NewsCheck, NewsItem=NewsItem)
    monkeypatch.setitem(sys.modules, "netcortex_core", core)
    monkeypatch.setattr(service, "_load_settings", lambda: SimpleNamespace(serpapi_api_key=None))
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
