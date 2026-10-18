from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from netcortex_core import NewsCheck, NewsItem, Settings

SERP_URL = "https://serpapi.com/search.json"


def _load_settings() -> Settings:
    """Load the shared core settings for the public entry point."""
    return Settings()


def _read_body(response: httpx.Response, *, max_bytes: int, total_seconds: float) -> bytes:
    started = time.monotonic()
    body = bytearray()
    for part in response.iter_bytes():
        body.extend(part)
        if len(body) > max_bytes:
            raise RuntimeError("provider response exceeded its size limit")
        if time.monotonic() - started > total_seconds:
            raise httpx.TimeoutException("provider response exceeded its total deadline")
    return bytes(body)


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return value


def _published_date(value: Any, now: datetime) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().lower()
    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        return parsed if now - timedelta(hours=24) <= parsed <= now + timedelta(minutes=5) else None
    except ValueError:
        pass
    if text == "today":
        parsed = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return parsed
    if text == "yesterday":
        return now.astimezone(UTC) - timedelta(hours=24)
    match = re.fullmatch(r"(\d+)\s*(minute|hour|day)s?\s+ago", text)
    if match:
        amount = int(match.group(1))
        delta = {
            "minute": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
        }[match.group(2)]
        if delta <= timedelta(hours=24):
            return now.astimezone(UTC) - delta
    return None


def _recent_date(value: Any, now: datetime) -> bool:
    return _published_date(value, now) is not None


def _check_news(
    provider: str | None,
    target: str | None,
    *,
    api_key: str | None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    provider = (provider or "").strip()
    target = (target or "").strip()
    if not provider and not target:
        return {
            "available": False,
            "summary": "Upstream outage check unavailable: no provider or target was supplied.",
            "links": [],
        }
    if not api_key:
        return {
            "available": False,
            "summary": "Upstream outage check unavailable: SerpApi key is not configured.",
            "links": [],
        }
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(3, connect=2), follow_redirects=False)
    try:
        terms = " ".join(value for value in (provider, target) if value)
        with client.stream(
            "GET",
            SERP_URL,
            params={
                "engine": "google",
                "q": f'"{terms}" outage',
                "tbs": "qdr:d",
                "api_key": api_key,
            },
        ) as response:
            if response.status_code == 429:
                return {
                    "available": False,
                    "summary": "Upstream outage check unavailable: SerpApi rate limit.",
                    "links": [],
                }
            response.raise_for_status()
            payload = json.loads(_read_body(response, max_bytes=1_000_000, total_seconds=8))
        if not isinstance(payload, dict) or payload.get("error"):
            return {
                "available": False,
                "summary": "Upstream outage check unavailable: malformed search response.",
                "links": [],
            }
        timestamp = now or datetime.now(UTC)
        items = payload.get("news_results") or payload.get("organic_results") or []
        if not isinstance(items, list):
            return {
                "available": False,
                "summary": "Upstream outage check unavailable: malformed search results.",
                "links": [],
            }
        links: list[dict[str, str]] = []
        outage_reported = False
        terms = [word.lower() for word in (provider, target) if word]
        outage_pattern = re.compile(
            r"\b(?:outages?|down|degraded|disruptions?|unavailable|failures?|incidents?|offline)\b"
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            published = _published_date(item.get("date"), timestamp)
            if published is None:
                continue
            url = _safe_url(item.get("link"))
            title = item.get("title")
            if url and isinstance(title, str) and title.strip():
                links.append(
                    {
                        "title": title.strip()[:200],
                        "url": url,
                        "published": published.isoformat(),
                    }
                )
                snippet = str(item.get("snippet", ""))
                description = f"{title} {snippet}".lower()
                relevant = any(term in description for term in terms)
                outage_reported = outage_reported or (
                    relevant and bool(outage_pattern.search(description))
                )
        if links:
            summary = (
                f"Recent outage-related reports may mention {terms}; "
                "verify with the provider before treating this as an outage."
                if outage_reported
                else f"Recent search results mention {terms}, "
                "but no relevant outage wording was found."
            )
            return {
                "available": True,
                "outage_reported": outage_reported,
                "summary": summary,
                "links": links[:5],
            }
        return {
            "available": True,
            "outage_reported": False,
            "summary": f"No qualifying outage reports found for {terms} in the past 24 hours.",
            "links": [],
        }
    except (httpx.HTTPError, RuntimeError, ValueError):
        return {
            "available": False,
            "summary": "Upstream outage check unavailable: search request failed or "
            "returned invalid JSON.",
            "links": [],
        }
    finally:
        if own:
            client.close()


def check_news(provider: str | None, target: str | None) -> NewsCheck:
    """Search recent outage reports and return the shared core contract."""
    settings = _load_settings()
    api_key = settings.serpapi_api_key.get_secret_value() if settings.serpapi_api_key else None
    result = _check_news(provider, target, api_key=api_key)
    timestamp = datetime.now(UTC)
    items = [
        NewsItem(
            title=item["title"],
            url=item["url"],
            published=_published_date(item.get("published"), timestamp),
        )
        for item in result["links"]
    ]
    return NewsCheck(
        available=result["available"],
        outage_reported=result.get("outage_reported", False),
        summary=result["summary"],
        items=items,
    )
