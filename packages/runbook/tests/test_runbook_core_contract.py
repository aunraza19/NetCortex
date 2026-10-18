"""Lead acceptance cases; no model download, database or secrets required."""

import httpx
import pytest
from netcortex_core import ModuleUnavailable
from netcortex_runbook import service


def test_agreed_embedding_name_and_dimensions():
    def reply(request):
        assert b'"model":"embeddinggemma"' in request.content
        return httpx.Response(200, json={"model": "embeddinggemma", "embeddings": [[0.0] * 768]})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        assert (
            len(service._embed(client, "failover", "http://localhost:11434", "embeddinggemma"))
            == 768
        )


def test_invalid_embedding_dimensions_rejected():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"model": "embeddinggemma", "embeddings": [[0.0] * 2]}
            )
        )
    ) as client:
        with pytest.raises((ValueError, ModuleUnavailable)):
            service._embed(client, "failover", "http://localhost:11434", "embeddinggemma")
