from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from netcortex_core import NewsCheck  # type: ignore[import-not-found]

VOICE_MODEL = "eleven_v3"  # official docs list Urdu for v3; multilingual_v2 lacks Urdu support
ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
SERP_URL = "https://serpapi.com/search.json"
logger = logging.getLogger(__name__)


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


def _load_settings() -> Any:
    try:
        from netcortex_core import Settings  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "live notification calls require Aun's published netcortex_core.Settings"
        ) from exc
    return Settings()


def _speak(
    text: str,
    lang: str,
    *,
    api_key: str | None,
    voice_id: str | None,
    client: httpx.Client | None = None,
) -> bytes:
    if lang not in {"en", "ur"}:
        raise ValueError("lang must be 'en' or 'ur'")
    if not text.strip() or len(text.split()) > 40:
        raise ValueError("voice alert must contain 1..40 words")
    if not api_key or not voice_id:
        return b""
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(3, connect=2), follow_redirects=False)
    try:
        with client.stream(
            "POST",
            ELEVEN_URL.format(voice_id=voice_id),
            params={"output_format": "mp3_44100_128"},
            headers={
                "xi-api-key": api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": VOICE_MODEL,
                "language_code": "ur" if lang == "ur" else "en",
            },
        ) as response:
            if response.status_code == 429:
                raise RuntimeError("ElevenLabs rate limit; voice is unavailable")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and "audio/" not in content_type and "octet-stream" not in content_type:
                raise RuntimeError("ElevenLabs returned a non-audio response")
            audio = _read_body(response, max_bytes=1_000_000, total_seconds=12)
            if not audio:
                raise RuntimeError("ElevenLabs returned an empty audio response")
            return audio
    finally:
        if own:
            client.close()


def speak(text: str, lang: str) -> bytes:
    """Return MP3 bytes; an unconfigured voice service is safely unavailable as b''."""
    settings = _load_settings()
    try:
        return _speak(
            text, lang, api_key=settings.elevenlabs_api_key, voice_id=settings.elevenlabs_voice_id
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning("ElevenLabs voice unavailable (%s)", type(exc).__name__)
        return b""


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


def _recent_date(value: Any, now: datetime) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    # SerpApi commonly gives relative labels; accept explicit recent durations and ISO dates.
    text = value.strip().lower()
    if text in {
        "today",
        "1 hour ago",
        "2 hours ago",
        "3 hours ago",
        "4 hours ago",
        "5 hours ago",
        "6 hours ago",
        "12 hours ago",
    }:
        return True
    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return now - timedelta(hours=24) <= parsed.astimezone(UTC) <= now + timedelta(minutes=5)
    except ValueError:
        pass
    match = re.fullmatch(r"(\d+)\s*(minute|hour|day)s?\s+ago", text)
    if match:
        amount = int(match.group(1))
        return (
            (match.group(2) == "minute" and amount <= 1440)
            or (match.group(2) == "hour" and amount <= 24)
            or (match.group(2) == "day" and amount == 1)
        )
    return False


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
            if not isinstance(item, dict) or not _recent_date(item.get("date"), timestamp):
                continue
            url = _safe_url(item.get("link"))
            title = item.get("title")
            if url and isinstance(title, str) and title.strip():
                links.append(
                    {
                        "title": title.strip()[:200],
                        "url": url,
                        "published": str(item.get("date", ""))[:100],
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
    """Search recent outage reports and return core NewsCheck once the shared contract exists."""
    settings = _load_settings()
    result = _check_news(provider, target, api_key=settings.serpapi_api_key)
    try:
        from netcortex_core import NewsCheck, NewsItem  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "check_news requires Aun's published netcortex_core.NewsCheck and NewsItem contracts"
        ) from exc
    items = [
        NewsItem(title=item["title"], url=item["url"], published=item["published"])
        for item in result["links"]
    ]
    return NewsCheck(
        outage_reported=result.get("outage_reported", False), summary=result["summary"], items=items
    )
