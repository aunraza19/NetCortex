from __future__ import annotations

import math
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from netcortex_core import ModuleUnavailable, RunbookChunk, Settings

SOURCES = {
    "queues": "https://help.mikrotik.com/docs/spaces/ROS/pages/328088/Queues",
    "routing": "https://help.mikrotik.com/docs/spaces/ROS/pages/59965493/routing%2Broute",
    "failover": "https://help.mikrotik.com/docs/spaces/ROS/pages/26476608/Failover%2BWAN%2BBackup",
    "dns": "https://help.mikrotik.com/docs/spaces/ROS/pages/37748767/DNS",
    "mangle": "https://help.mikrotik.com/docs/spaces/ROS/pages/48660587/Mangle",
    "interface": "https://help.mikrotik.com/docs/spaces/ROS/pages/139526175/Interface%20stats%20and%20monitor-traffic",
}
USER_AGENT = "NetCortexRunbook/0.1 (documentation retrieval; contact: project maintainers)"
MAX_PAGE_BYTES = 2_000_000


@dataclass(frozen=True)
class Chunk:
    source_url: str
    title: str
    section: str
    text: str


def chunk_text(title: str, source_url: str, text: str, *, words: int = 400) -> list[Chunk]:
    """Split text into bounded 300-500 word chunks while retaining section labels."""
    if not 300 <= words <= 500:
        raise ValueError("chunk size must be 300..500 words")
    sections: list[tuple[str, list[str]]] = []
    section = title
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if line.startswith("#"):
            section = line.lstrip("# ") or title
            sections.append((section, []))
        else:
            if not sections:
                sections.append((section, []))
            sections[-1][1].append(line)
    section_words = [
        (heading, word) for heading, lines in sections for word in " ".join(lines).split()
    ]
    total = len(section_words)
    if not total:
        return []
    count = 1 if total <= 500 else (total + words - 1) // words
    base, extra = divmod(total, count)
    output: list[Chunk] = []
    offset = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        part = section_words[offset : offset + size]
        offset += size
        headings = list(dict.fromkeys(heading for heading, _ in part))
        output.append(
            Chunk(source_url, title, " / ".join(headings), " ".join(word for _, word in part))
        )
    return output


def _robots_allowed(client: httpx.Client, url: str) -> bool:
    parser = _robots_policy(client, url)
    return parser.can_fetch(USER_AGENT, url)


def _robots_policy(client: httpx.Client, url: str) -> urllib.robotparser.RobotFileParser:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    response = client.get(robots_url, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if len(response.content) > 256_000:
        raise ValueError("robots.txt exceeds the 256 KB size limit")
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    return parser


def _download(
    client: httpx.Client,
    url: str,
    *,
    robots: urllib.robotparser.RobotFileParser | None = None,
) -> tuple[str, str]:
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "help.mikrotik.com":
        raise ValueError("only official MikroTik help pages over HTTPS are allowed")
    robots = robots or _robots_policy(client, url)
    if not robots.can_fetch(USER_AGENT, url):
        raise RuntimeError(f"robots.txt disallows {url}")
    with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        final_url = urlparse(str(response.url))
        if final_url.scheme != "https" or final_url.hostname != "help.mikrotik.com":
            raise ValueError("documentation request redirected outside the official HTTPS host")
        body = bytearray()
        for piece in response.iter_bytes():
            body.extend(piece)
            if len(body) > MAX_PAGE_BYTES:
                raise ValueError("documentation page exceeds the 2 MB size limit")
    soup = BeautifulSoup(bytes(body), "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    main = soup.select_one("main") or soup.select_one("#main-content") or soup.body
    if main is None:
        raise ValueError("documentation page has no readable body")
    for element in main.select("script,style,nav,footer,header,aside"):
        element.decompose()
    lines: list[str] = []
    for element in main.select("h1,h2,h3,h4,p,li"):
        value = element.get_text(" ", strip=True)
        if element.name.startswith("h"):
            lines.append("# " + value)
        elif value:
            lines.append(value)
    return title, "\n".join(lines)


def _embed(client: httpx.Client, text: str, base_url: str, model: str) -> list[float]:
    _validate_model(model)
    response = client.post(
        f"{base_url.rstrip('/')}/api/embed", json={"model": model, "input": text}
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Ollama returned a malformed embedding response")
    reported_model = payload.get("model")
    if reported_model != model and not (
        model == "embeddinggemma" and reported_model == "embeddinggemma:latest"
    ):
        raise ValueError(f"Ollama model mismatch: requested {model!r}, received {reported_model!r}")
    embeddings = payload.get("embeddings")
    vector = embeddings[0] if isinstance(embeddings, list) and embeddings else None
    if not isinstance(vector, list) or len(vector) != 768:
        size = len(vector) if isinstance(vector, list) else "invalid"
        raise ValueError(f"EmbeddingGemma must return 768 dimensions; got {size}")
    if any(
        isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value)
        for value in vector
    ):
        raise ValueError("embedding contains invalid or non-finite values")
    return [float(value) for value in vector]


def _validate_model(model: str) -> None:
    if (
        not isinstance(model, str)
        or model != "embeddinggemma"
        and not re.fullmatch(r"embeddinggemma:[^\s:]+", model)
    ):
        raise ValueError("embed_model must be embeddinggemma or an explicit embeddinggemma tag")


def _store_chunks(conn: Any, chunks: list[tuple[Chunk, list[float]]], embed_model: str) -> None:
    with conn.cursor() as cur:
        # The current schema has no natural unique key; serialize writers and safely select/insert.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('netcortex.runbook_chunks.v1'))")
        for chunk, vector in chunks:
            cur.execute(
                "SELECT id FROM runbook_chunks WHERE source_url=%s AND title=%s "
                "AND section=%s AND text=%s AND embed_model=%s LIMIT 1",
                (chunk.source_url, chunk.title, chunk.section, chunk.text, embed_model),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO runbook_chunks (id,source_url,title,section,text,embedding,"
                    "embed_model) "
                    "VALUES (gen_random_uuid(),%s,%s,%s,%s,%s::vector,%s)",
                    (
                        chunk.source_url,
                        chunk.title,
                        chunk.section,
                        chunk.text,
                        "[" + ",".join(map(str, vector)) + "]",
                        embed_model,
                    ),
                )


def ingest(
    *,
    database_url: str,
    ollama_base_url: str,
    embed_model: str,
    sources: dict[str, str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    """Fetch official pages and transactionally upsert chunks into approved runbook columns."""
    _validate_model(embed_model)
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
    try:
        chunks: list[tuple[Chunk, list[float]]] = []
        topic_urls = list((sources or SOURCES).values())
        if not topic_urls:
            return 0
        robots = _robots_policy(client, topic_urls[0])
        delay = robots.crawl_delay(USER_AGENT) or 0
        last_request = time.monotonic()
        for topic_url in topic_urls:
            if not robots.can_fetch(USER_AGENT, topic_url):
                raise RuntimeError(f"robots.txt disallows {topic_url}")
            wait = delay - (time.monotonic() - last_request)
            if wait > 0:
                time.sleep(wait)
            title, body = _download(client, topic_url, robots=robots)
            last_request = time.monotonic()
            for chunk in chunk_text(title, topic_url, body):
                chunks.append((chunk, _embed(client, chunk.text, ollama_base_url, embed_model)))
        import psycopg

        with psycopg.connect(
            database_url, connect_timeout=5, options="-c statement_timeout=5000"
        ) as conn:
            _store_chunks(conn, chunks, embed_model)
        return len(chunks)
    except ModuleUnavailable:
        raise
    except Exception as exc:
        raise ModuleUnavailable(f"runbook ingest unavailable ({type(exc).__name__})") from exc
    finally:
        if own:
            client.close()


def search_runbook(query: str, k: int = 5) -> list[RunbookChunk]:
    """Search pgvector; return core RunbookChunk items after its contract is published."""
    if not query.strip() or not 1 <= k <= 20:
        raise ValueError("query must be non-empty and k must be 1..20")
    settings = Settings()
    model = settings.embed_model
    try:
        _validate_model(model)
    except ValueError as exc:
        raise ModuleUnavailable(f"runbook search unavailable: {exc}") from exc
    if settings.database_url is None:
        raise ModuleUnavailable("runbook search unavailable: database URL is not configured")
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=5)) as client:
            vector = _embed(client, query, settings.ollama_base_url, model)
        import psycopg

        database_url = settings.database_url.get_secret_value()
        with (
            psycopg.connect(
                database_url, connect_timeout=5, options="-c statement_timeout=5000"
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                "SELECT source_url,title,section,text,embedding <=> %s::vector AS distance "
                "FROM runbook_chunks WHERE embed_model=%s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (
                    "[" + ",".join(map(str, vector)) + "]",
                    model,
                    "[" + ",".join(map(str, vector)) + "]",
                    k,
                ),
            )
            rows = cur.fetchall()
    except ModuleUnavailable:
        raise
    except Exception as exc:
        raise ModuleUnavailable(f"runbook search unavailable ({type(exc).__name__})") from exc
    return [
        RunbookChunk(source_url=r[0], title=r[1], section=r[2], text=r[3], score=1.0 - float(r[4]))
        for r in rows
    ]


def fixture_search(query: str, k: int = 3) -> list[dict[str, str]]:
    """Small source-linked offline examples, explicitly lexical rather than model retrieval."""
    if not query.strip() or not 1 <= k <= 20:
        raise ValueError("query must be non-empty and k must be 1..20")
    q = query.lower()
    topics = [
        (
            "limit bandwidth",
            "Simple Queues",
            "Simple Queues and Queue Trees are RouterOS queue facilities for traffic shaping "
            "and limits.",
            SOURCES["queues"],
            "Queues",
        ),
        (
            "one ip",
            "Simple Queues",
            "RouterOS Simple Queues are a queue facility for applying traffic limits to "
            "selected traffic.",
            SOURCES["queues"],
            "Queues",
        ),
        (
            "priority gaming",
            "Queue Tree",
            "RouterOS queues use hierarchical token bucket; Simple Queues and Queue Trees "
            "provide traffic shaping and priority controls.",
            SOURCES["queues"],
            "Queues",
        ),
        (
            "failover",
            "Failover WAN Backup",
            "RouterOS route entries support check-gateway (ping, arp, or bfd) to monitor "
            "gateway reachability.",
            SOURCES["failover"],
            "Failover WAN Backup",
        ),
        (
            "default route",
            "Routing Route",
            "RouterOS route entries support check-gateway (ping, arp, or bfd), including "
            "for monitored default routes.",
            SOURCES["routing"],
            "Routing Route",
        ),
        (
            "dns",
            "DNS",
            "RouterOS DNS provides name resolution and can use configured static and dynamic "
            "DNS servers.",
            SOURCES["dns"],
            "DNS",
        ),
        (
            "mangle",
            "Mangle",
            "RouterOS mangle rules mark packets for later processing by queues, NAT, or "
            "routing facilities.",
            SOURCES["mangle"],
            "Mangle",
        ),
        (
            "interface monitoring",
            "Interface stats and monitor-traffic",
            "RouterOS interface statistics include receive/transmit counters, link downs, "
            "and queue drops; monitor-traffic reports traffic rates.",
            SOURCES["interface"],
            "Interface stats and monitor-traffic",
        ),
    ]
    matches = [x for x in topics if x[0] in q or x[1].lower() in q]
    if not matches and "queue" in q:
        matches = [topics[2], topics[0], topics[1]]
    if not matches:
        matches = topics
    return [
        {
            "source_url": x[3],
            "title": "RouterOS " + x[1],
            "section": x[1],
            "text": x[2],
            "source_title": x[4],
            "retrieved_on": "2026-10-18",
            "fixture": "true",
        }
        for x in matches[:k]
    ]
