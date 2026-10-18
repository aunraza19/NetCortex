"""A small RouterOS v7 REST client: run CLI scripts, export the config, read resources.

Fix commands are RouterOS CLI text rendered from templates, so they go through
POST /rest/execute (one call per command line, so a failure names the line).
"""

from __future__ import annotations

from typing import Any

import httpx
from netcortex_core import Settings, get_settings


class RouterError(RuntimeError):
    """The router refused a command or couldn't be reached."""


class RouterClient:
    def __init__(self, base_url: str, username: str, password: str, timeout_s: float = 30) -> None:
        base = base_url.rstrip("/").removesuffix("/rest")
        self._http = httpx.Client(
            base_url=f"{base}/rest", auth=(username, password), timeout=timeout_s
        )

    @classmethod
    def chr(cls, settings: Settings | None = None) -> RouterClient:
        """The CHR test router from Settings. Real routers are never reached from here."""
        settings = settings or get_settings()
        if not (settings.chr_rest_url and settings.chr_password):
            raise RouterError("CHR_REST_URL and CHR_PASSWORD must be set (see infra/chr)")
        return cls(
            settings.chr_rest_url,
            settings.chr_username or "admin",
            settings.chr_password.get_secret_value(),
        )

    def run(self, script: str) -> str:
        """Run CLI commands one line at a time; stop at the first one RouterOS rejects."""
        output = []
        for line in (line.strip() for line in script.splitlines()):
            if not line:
                continue
            response = self._post("/execute", {"script": line, "as-string": ""})
            result = str(response.get("ret", "")) if isinstance(response, dict) else ""
            if _looks_like_error(result):
                raise RouterError(f"{line!r} failed: {result.strip()}")
            output.append(f"> {line}" + (f"\n{result.strip()}" if result.strip() else ""))
        return "\n".join(output)

    def export(self) -> list[str]:
        """The config as `/export terse` lines, without comments and blank lines."""
        response = self._post("/execute", {"script": "/export terse", "as-string": ""})
        text = str(response.get("ret", "")) if isinstance(response, dict) else ""
        return [
            line.strip()
            for line in text.replace("\r", "").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def get(self, path: str) -> Any:
        try:
            response = self._http.get(path)
        except httpx.HTTPError as exc:
            raise RouterError(f"CHR unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise RouterError(f"GET {path}: HTTP {response.status_code} {response.text[:200]}")
        return response.json()

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            response = self._http.post(path, json=body)
        except httpx.HTTPError as exc:
            raise RouterError(f"CHR unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            detail = _detail(response)
            raise RouterError(f"{body.get('script', path)!r} failed: {detail}")
        return response.json()

    def close(self) -> None:
        self._http.close()


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    return str(body.get("detail") or body.get("message") or body)


# RouterOS reports many command errors as normal output with HTTP 200.
_ERROR_WORDS = (
    "failure:",
    "syntax error",
    "bad command name",
    "no such item",
    "expected end",
    "invalid or unexpected",
    "invalid value",
    "input does not match",
    "ambiguous value",
    "already have",
)


def _looks_like_error(output: str) -> bool:
    lowered = output.lower()
    return any(word in lowered for word in _ERROR_WORDS)
