import httpx
import pytest
from netcortex_runbook.service import (
    SOURCES,
    USER_AGENT,
    Chunk,
    _embed,
    _robots_allowed,
    _robots_policy,
    _store_chunks,
    chunk_text,
    fixture_search,
)

MODEL = "embeddinggemma:300m"


def test_fixture_topics_have_official_source_and_are_explicit():
    queries = [
        ("limit bandwidth for one IP", "Queues"),
        ("failover default route", "Failover WAN Backup"),
        ("priority queue for gaming", "Queues"),
        ("DNS resolver", "DNS"),
    ]
    for query, expected_title in queries:
        result = fixture_search(query, 3)
        assert result[0]["source_title"] == expected_title
        assert result[0]["fixture"] == "true"
        assert result[0]["retrieved_on"] == "2026-10-18"
        assert result[0]["source_url"].startswith("https://help.mikrotik.com/")


def test_chunk_boundaries_keep_section_titles():
    text = "# Queue limits\n" + "word " * 610
    chunks = chunk_text("RouterOS", "https://help.mikrotik.com/docs/x", text)
    assert [len(chunk.text.split()) for chunk in chunks] == [305, 305]
    assert all(chunk.section == "Queue limits" for chunk in chunks)
    with pytest.raises(ValueError):
        chunk_text("x", "u", "body", words=299)


def test_embed_enforces_model_dimensions_and_finite_values():
    def valid(request):
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"model": MODEL, "embeddings": [[0.1] * 768]})

    with httpx.Client(transport=httpx.MockTransport(valid)) as client:
        assert len(_embed(client, "query", "http://ollama", MODEL)) == 768

    def wrong_model(request):
        return httpx.Response(
            200, json={"model": "embeddinggemma:other", "embeddings": [[0.1] * 768]}
        )

    with (
        httpx.Client(transport=httpx.MockTransport(wrong_model)) as client,
        pytest.raises(ValueError, match="model mismatch"),
    ):
        _embed(client, "query", "http://ollama", MODEL)

    def wrong_size(request):
        return httpx.Response(200, json={"model": MODEL, "embeddings": [[0.1] * 767]})

    with (
        httpx.Client(transport=httpx.MockTransport(wrong_size)) as client,
        pytest.raises(ValueError, match="768"),
    ):
        _embed(client, "query", "http://ollama", MODEL)

    for invalid in [float("nan"), float("inf"), True]:

        def nonfinite(request, invalid=invalid):
            invalid_json = (
                "true" if invalid is True else ("NaN" if invalid != invalid else "Infinity")
            )
            values = ",".join([invalid_json] + ["0.1"] * 767)
            return httpx.Response(200, content=f'{{"model":"{MODEL}","embeddings":[[{values}]]}}')

        with (
            httpx.Client(transport=httpx.MockTransport(nonfinite)) as client,
            pytest.raises(ValueError, match="non-finite"),
        ):
            _embed(client, "query", "http://ollama", MODEL)


def test_ingestion_respects_robots_rules():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="User-agent: *\nDisallow: /docs/")
        )
    )
    assert not _robots_allowed(client, "https://help.mikrotik.com/docs/example")
    client.close()


def test_source_allowlist_is_canonical_and_honors_published_crawl_delay():
    assert len(SOURCES) == 6
    assert all(
        url.startswith("https://help.mikrotik.com/docs/spaces/ROS/pages/")
        for url in SOURCES.values()
    )
    assert all("/display/" not in url for url in SOURCES.values())
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="User-agent: *\nAllow: /docs/spaces/\nCrawl-delay: 5\n",
            )
        )
    )
    rules = _robots_policy(client, next(iter(SOURCES.values())))
    assert rules.crawl_delay(USER_AGENT) == 5
    assert all(rules.can_fetch(USER_AGENT, url) for url in SOURCES.values())
    client.close()


def test_embed_timeout_is_a_provider_failure():
    def slow(request):
        raise httpx.ReadTimeout("simulated timeout")

    with (
        httpx.Client(transport=httpx.MockTransport(slow)) as client,
        pytest.raises(httpx.ReadTimeout),
    ):
        _embed(client, "query", "http://ollama", MODEL)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.found = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT id"):
            key = tuple(params)
            self.found = key if key in self.rows else None
        elif sql.startswith("INSERT"):
            self.rows.add((params[0], params[1], params[2], params[3], params[-1]))

    def fetchone(self):
        return ("existing",) if self.found else None


class FakeConnection:
    def __init__(self):
        self.rows = set()

    def cursor(self):
        return FakeCursor(self.rows)


def test_database_upsert_is_repeat_safe_per_model():
    conn = FakeConnection()
    chunk = Chunk("https://help.mikrotik.com/docs/example", "title", "section", "body")
    _store_chunks(conn, [(chunk, [0.0] * 768)], MODEL)
    _store_chunks(conn, [(chunk, [0.0] * 768)], MODEL)
    _store_chunks(conn, [(chunk, [0.0] * 768)], "embeddinggemma:other")
    assert len(conn.rows) == 2
