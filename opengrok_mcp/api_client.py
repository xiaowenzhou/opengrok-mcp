import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

import httpx

from .utils import build_cache_key, normalize_endpoint


class OpenGrokApiClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        retries: int,
        retry_backoff_seconds: float,
        max_connections: int,
        max_keepalive_connections: int,
        cache_ttl_seconds: float,
        cache_max_entries: int,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = f"{base_url.rstrip('/')}/"
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_max_entries = cache_max_entries
        self.logger = logger or logging.getLogger("opengrok-mcp")

        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        self._cache: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
        self._cache_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    limits = httpx.Limits(
                        max_connections=self.max_connections,
                        max_keepalive_connections=self.max_keepalive_connections,
                    )
                    timeout = httpx.Timeout(self.timeout_seconds)
                    self._client = httpx.AsyncClient(
                        base_url=self.base_url,
                        limits=limits,
                        timeout=timeout,
                        follow_redirects=True,
                    )
        return self._client

    @staticmethod
    def _parse_response(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime == "application/json" or mime.endswith("+json"):
            return response.json()
        return response.text

    async def _cache_get(self, key: str) -> Optional[Any]:
        if self.cache_ttl_seconds <= 0:
            return None
        now = time.monotonic()
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            expires_at, value = cached
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return value

    async def _cache_set(self, key: str, value: Any) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        async with self._cache_lock:
            self._cache[key] = (time.monotonic() + self.cache_ttl_seconds, value)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_max_entries:
                self._cache.popitem(last=False)

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        normalized_endpoint = normalize_endpoint(endpoint)
        cache_key = build_cache_key(normalized_endpoint, params, headers)

        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached

        client = await self._get_client()
        for attempt in range(self.retries + 1):
            try:
                response = await client.get(
                    normalized_endpoint,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                payload = self._parse_response(response)
                await self._cache_set(cache_key, payload)
                return payload
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable_status = status == 429 or status >= 500
                if retryable_status and attempt < self.retries:
                    delay = self.retry_backoff_seconds * (2**attempt)
                    self.logger.warning(
                        "OpenGrok API %s returned %d (retry %d/%d in %.2fs)",
                        normalized_endpoint,
                        status,
                        attempt + 1,
                        self.retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                detail = exc.response.text[:300]
                self.logger.error("OpenGrok API error %d for %s: %s", status, endpoint, detail)
                raise RuntimeError(
                    f"OpenGrok API error {status} for /{normalized_endpoint}: {detail}"
                ) from exc
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as exc:
                if attempt < self.retries:
                    delay = self.retry_backoff_seconds * (2**attempt)
                    self.logger.warning(
                        "OpenGrok API request failed for %s (%s), retry %d/%d in %.2fs",
                        endpoint,
                        type(exc).__name__,
                        attempt + 1,
                        self.retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                self.logger.error("Connection failure for %s: %s", endpoint, exc)
                raise RuntimeError(
                    f"Failed to connect to OpenGrok endpoint /{normalized_endpoint}: {exc}"
                ) from exc

        raise RuntimeError(f"Unexpected retry loop termination for /{normalized_endpoint}")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
