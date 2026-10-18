"""Lead-written behavioral acceptance cases for the real core boundary."""

from netcortex_core import NewsCheck, Settings
from netcortex_notify import service


def test_public_news_unavailable_is_not_success(monkeypatch):
    monkeypatch.setattr(service, "_load_settings", lambda: Settings(_env_file=None))
    result = service.check_news("ExampleISP", "Dubai")
    assert isinstance(result, NewsCheck)
    assert result.available is False
    assert not result.outage_reported


def test_news_unwraps_secret_and_normalizes_relative_date(monkeypatch):
    settings = Settings(_env_file=None, serpapi_api_key="synthetic-test-value")
    monkeypatch.setattr(service, "_load_settings", lambda: settings)

    def search(provider, target, *, api_key, **kwargs):
        assert api_key == "synthetic-test-value"
        return {
            "available": True,
            "outage_reported": True,
            "summary": "Reported outage",
            "links": [
                {
                    "title": "ExampleISP outage",
                    "url": "https://example.com/news",
                    "published": "2 hours ago",
                }
            ],
        }

    monkeypatch.setattr(service, "_check_news", search)
    result = service.check_news("ExampleISP", "Dubai")
    assert isinstance(result, NewsCheck)
    assert result.available and result.items[0].published is not None
    assert result.items[0].published.tzinfo is not None


def test_voice_public_export_removed():
    import netcortex_notify

    assert not hasattr(netcortex_notify, "speak")
    assert not hasattr(service, "speak")
