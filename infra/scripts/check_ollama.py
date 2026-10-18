"""Check the model server: reachable, both models present, embeddings have 768 dimensions.

    uv run python infra/scripts/check_ollama.py

Reads OLLAMA_BASE_URL, AGENT_MODEL and EMBED_MODEL from Settings. Exits 1 on any failure;
a missing agent model is reported but allowed while it's still downloading (--allow-missing-agent).
"""

import argparse
import sys
import time

import httpx
from netcortex_core import EMBED_DIM, get_settings


def has_model(names: list[str], wanted: str) -> bool:
    return any(n == wanted or n == f"{wanted}:latest" for n in names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allow-missing-agent", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    ok = True

    try:
        started = time.monotonic()
        tags = httpx.get(f"{base}/api/tags", timeout=10).json()
        print(f"PASS  model server reachable ({(time.monotonic() - started) * 1000:.0f} ms)")
    except (httpx.HTTPError, ValueError) as exc:
        print(f"FAIL  model server not reachable: {type(exc).__name__} (check OLLAMA_BASE_URL)")
        return 1
    names = [m["name"] for m in tags.get("models", [])]

    if has_model(names, settings.agent_model):
        print(f"PASS  agent model {settings.agent_model} is present")
    elif args.allow_missing_agent:
        print(f"WARN  agent model {settings.agent_model} missing (still downloading?)")
    else:
        print(f"FAIL  agent model {settings.agent_model} missing; have {names}")
        ok = False

    if not has_model(names, settings.embed_model):
        print(f"FAIL  embedding model {settings.embed_model} missing; have {names}")
        return 1
    try:
        reply = httpx.post(
            f"{base}/api/embed",
            json={"model": settings.embed_model, "input": "limit bandwidth for one IP"},
            timeout=60,
        ).json()
        dims = len(reply["embeddings"][0])
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        print(f"FAIL  embedding request failed: {type(exc).__name__}")
        return 1
    if dims == EMBED_DIM:
        print(f"PASS  {settings.embed_model} returns {dims}-dimension embeddings")
    else:
        print(f"FAIL  {settings.embed_model} returned {dims} dimensions, expected {EMBED_DIM}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
