"""Async transport: bounded concurrency, host pacing, retries and proxy fallback."""

import asyncio
import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx


class APIError(RuntimeError):
    """A source is unavailable or returned an invalid response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AsyncAPIClient:
    def __init__(
        self,
        *,
        proxy: str | None = None,
        fallback_proxy: str | None = "socks5://127.0.0.1:2080",
        retries: int = 3,
        concurrency: int = 5,
        timeout: float = 20,
        transport: httpx.AsyncBaseTransport | None = None,
        host_intervals: dict[str, float] | None = None,
    ) -> None:
        if retries < 1 or concurrency < 1 or timeout <= 0:
            raise ValueError("retries, concurrency and timeout must be positive")
        self.retries = retries
        self.proxy = proxy or os.getenv("ANIME_HOOK_PROXY")
        self.fallback_proxy = fallback_proxy
        self.timeout = timeout
        self.transport = transport
        self._semaphore = asyncio.Semaphore(concurrency)
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_request: dict[str, float] = {}
        self._rate_limited_until: dict[str, float] = {}
        self._intervals = host_intervals if host_intervals is not None else {
            "shikimori.one": 0.25,
            "shikimori.io": 0.25,
            "graphql.anilist.co": 1.0,
            "api.jikan.moe": 0.5,
        }
        self._clients: dict[str | None, httpx.AsyncClient] = {}

    async def __aenter__(self) -> "AsyncAPIClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await asyncio.gather(*(client.aclose() for client in self._clients.values()))
        self._clients.clear()

    def _client(self, proxy: str | None) -> httpx.AsyncClient:
        if proxy not in self._clients:
            self._clients[proxy] = httpx.AsyncClient(
                proxy=proxy,
                transport=self.transport,
                timeout=4.0,
                follow_redirects=True,
                trust_env=False,
                headers={"User-Agent": "anime-hook/0.1 (personal recommendation research)",
                         "Accept": "application/json"},
            )
        return self._clients[proxy]

    async def _pace(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            while (wait := self._next_request.get(host, 0) - time.monotonic()) > 0:
                await asyncio.sleep(wait)
            self._next_request[host] = time.monotonic() + self._intervals.get(host, 0)

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        value = response.headers.get("Retry-After") if response is not None else None
        if value:
            try:
                delay = float(value)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    delay = 0
            return max(0, delay)
        if response is not None:
            try:
                reset = float(response.headers.get("X-RateLimit-Reset", "0"))
                if reset > time.time():
                    return reset - time.time()
            except ValueError:
                pass
            if response.status_code == 429:
                return 60.0
        return min(2 ** attempt + random.uniform(0, 0.25), 30)

    async def request_json(
        self, method: str, url: str, *, fail_fast_on_rate_limit: bool = False,
        **kwargs: Any,
    ) -> Any:
        host = urlsplit(url).hostname or ""
        if (fail_fast_on_rate_limit
                and self._rate_limited_until.get(host, 0) > time.monotonic()):
            raise APIError(f"{host}: HTTP 429 (host cooldown)", status_code=429)
        route = self.proxy
        last_error = "request failed"
        last_status = None
        for attempt in range(self.retries):
            response = None
            try:
                async with self._semaphore:
                    if (fail_fast_on_rate_limit
                            and self._rate_limited_until.get(host, 0) > time.monotonic()):
                        raise APIError(f"{host}: HTTP 429 (host cooldown)", status_code=429)
                    await self._pace(host)
                    if (fail_fast_on_rate_limit
                            and self._rate_limited_until.get(host, 0) > time.monotonic()):
                        raise APIError(f"{host}: HTTP 429 (host cooldown)", status_code=429)
                    response = await self._client(route).request(method, url, **kwargs)
                if response.headers.get("X-RateLimit-Remaining") == "0":
                    reset_delay = self._retry_delay(response, attempt)
                    self._next_request[host] = max(
                        self._next_request.get(host, 0), time.monotonic() + reset_delay
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"{host}: HTTP {response.status_code}"
                    last_status = response.status_code
                    # Defer all requests to this host, not only this coroutine.
                    delay = self._retry_delay(response, attempt)
                    self._next_request[host] = max(
                        self._next_request.get(host, 0), time.monotonic() + delay
                    )
                    if response.status_code == 429:
                        self._rate_limited_until[host] = time.monotonic() + delay
                        if fail_fast_on_rate_limit:
                            raise APIError(last_error, status_code=429)
                    if attempt + 1 < self.retries:
                        await asyncio.sleep(delay)
                        continue
                    break
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError as exc:
                    raise APIError(f"{host}: invalid JSON") from exc
            except httpx.TransportError as exc:
                last_error = f"{host}: {type(exc).__name__}"
                # Never send rejected requests (401/403) via another route.
                if self.fallback_proxy and route != self.fallback_proxy:
                    route = self.fallback_proxy
            except httpx.HTTPStatusError as exc:
                raise APIError(
                    f"{host}: HTTP {exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc
            if attempt + 1 < self.retries:
                await asyncio.sleep(self._retry_delay(response, attempt))
        raise APIError(last_error, status_code=last_status)

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = await self.request_json(
            "POST", "https://graphql.anilist.co", json={"query": query, "variables": variables}
        )
        if not isinstance(payload, dict):
            raise APIError("AniList: invalid GraphQL response")
        if payload.get("errors"):
            messages = "; ".join(str(error.get("message", "GraphQL error"))
                                 for error in payload["errors"] if isinstance(error, dict))
            raise APIError(f"AniList: {messages or 'GraphQL error'}")
        if not isinstance(payload.get("data"), dict):
            raise APIError("AniList: missing GraphQL data")
        return payload["data"]
