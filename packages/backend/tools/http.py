"""Shared HTTP client with retries, rate limiting, and per-namespace tuning.

All MCP servers should call into here instead of instantiating their own
``httpx.AsyncClient``. Centralizes:
  - Sane timeouts (connect 5s, read 15s) and a single connection pool.
  - Exponential backoff on 429 / 5xx / connection errors.
  - Per-namespace rate limiting (Nominatim policy = 1 req/s).

``HTTPError.code`` is one of: ``rate_limit``, ``timeout``, ``connection``,
``upstream_unavailable``. Callers translate that into the structured error
dicts the LLM sees.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


_USER_AGENT = "CursorUrbanPlanners/1.0"

_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)

# Per-namespace minimum interval between requests, in seconds. Zero = no limit.
_RATE_LIMITS: dict[str, float] = {
    "nominatim": 1.0,    # OSM usage policy
    "photon": 0.0,       # Komoot fair-use, no fixed limit
    "overpass": 0.0,     # mirror-rotated separately by callers
    "osrm": 0.0,
    "geoboundaries": 0.0,
    "worldpop": 0.5,
    "open-meteo": 0.0,
    "overture": 0.0,     # S3 reads via DuckDB, not via this client
    # Google Maps Platform — soft 20 RPS cap so a runaway loop doesn't burn quota.
    # Real per-API limits are far higher; this is just a sanity gate.
    "google_geocoding": 0.05,
    "google_places": 0.05,
    "google_environment": 0.05,
    "google_elevation": 0.05,
}

_last_request: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}
_client: httpx.AsyncClient | None = None


def _lock_for(namespace: str) -> asyncio.Lock:
    lock = _locks.get(namespace)
    if lock is None:
        lock = asyncio.Lock()
        _locks[namespace] = lock
    return lock


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            limits=_LIMITS,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
    return _client


class HTTPError(Exception):
    def __init__(self, message: str, *, code: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


_RETRY_STATUSES = {429, 500, 502, 503, 504}
_BACKOFF = (0.5, 1.0, 2.0, 4.0)


async def _wait_for_rate_limit(namespace: str) -> None:
    interval = _RATE_LIMITS.get(namespace, 0.0)
    if interval <= 0:
        return
    async with _lock_for(namespace):
        now = time.monotonic()
        last = _last_request.get(namespace, 0.0)
        wait = (last + interval) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request[namespace] = time.monotonic()


async def fetch_json(
    url: str,
    *,
    namespace: str,
    method: str = "GET",
    params: dict | None = None,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
) -> Any:
    """Fetch a URL and return parsed JSON. Raises ``HTTPError`` on terminal failure."""
    client = _get_client()
    last_status: int | None = None
    last_err: str | None = None

    for attempt in range(retries + 1):
        await _wait_for_rate_limit(namespace)
        try:
            resp = await client.request(
                method, url, params=params, json=json_body, headers=headers,
            )
            if resp.status_code in _RETRY_STATUSES:
                last_status = resp.status_code
                last_err = f"HTTP {resp.status_code}"
            elif resp.status_code >= 400:
                raise HTTPError(
                    f"{namespace} returned HTTP {resp.status_code}",
                    code="upstream_unavailable",
                    status=resp.status_code,
                )
            elif not (resp.text or "").strip():
                last_status = resp.status_code
                last_err = "empty body"
            else:
                try:
                    return resp.json()
                except ValueError as e:
                    raise HTTPError(
                        f"{namespace} returned non-JSON response",
                        code="upstream_unavailable",
                        status=resp.status_code,
                    ) from e
        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.RequestError as e:
            last_err = f"network error: {e}"

        if attempt < retries:
            await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])

    code = (
        "rate_limit" if last_status == 429
        else "timeout" if last_err == "timeout"
        else "connection" if last_err and "network" in last_err
        else "upstream_unavailable"
    )
    raise HTTPError(
        f"{namespace} failed after {retries + 1} attempts: {last_err}",
        code=code,
        status=last_status,
    )


async def fetch_text(
    url: str,
    *,
    namespace: str,
    method: str = "GET",
    params: dict | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
) -> str:
    """Same retry/rate-limit semantics as :func:`fetch_json`, returns raw text."""
    client = _get_client()
    last_status: int | None = None
    last_err: str | None = None

    for attempt in range(retries + 1):
        await _wait_for_rate_limit(namespace)
        try:
            resp = await client.request(method, url, params=params, headers=headers)
            if resp.status_code in _RETRY_STATUSES:
                last_status = resp.status_code
                last_err = f"HTTP {resp.status_code}"
            elif resp.status_code >= 400:
                raise HTTPError(
                    f"{namespace} returned HTTP {resp.status_code}",
                    code="upstream_unavailable",
                    status=resp.status_code,
                )
            else:
                return resp.text
        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.RequestError as e:
            last_err = f"network error: {e}"

        if attempt < retries:
            await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])

    code = (
        "rate_limit" if last_status == 429
        else "timeout" if last_err == "timeout"
        else "connection" if last_err and "network" in last_err
        else "upstream_unavailable"
    )
    raise HTTPError(
        f"{namespace} failed after {retries + 1} attempts: {last_err}",
        code=code,
        status=last_status,
    )


async def aclose() -> None:
    """Close the shared client. FastAPI lifespan should call this on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
