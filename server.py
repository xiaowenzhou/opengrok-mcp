import argparse
import asyncio
import difflib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import httpx
from mcp.server.fastmcp import FastMCP


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("opengrok-mcp")


def _read_int_env(
    name: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid integer %s=%r, using default %d", name, raw, default)
        return default
    if value < min_value:
        logger.warning("%s=%d is too small, clamping to %d", name, value, min_value)
        return min_value
    if value > max_value:
        logger.warning("%s=%d is too large, clamping to %d", name, value, max_value)
        return max_value
    return value


def _read_float_env(
    name: str,
    default: float,
    min_value: float,
    max_value: float,
) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid float %s=%r, using default %.2f", name, raw, default)
        return default
    if value < min_value:
        logger.warning("%s=%.2f is too small, clamping to %.2f", name, value, min_value)
        return min_value
    if value > max_value:
        logger.warning("%s=%.2f is too large, clamping to %.2f", name, value, max_value)
        return max_value
    return value


def _clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def _normalize_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        raise ValueError("path must not be empty")
    return normalized


TAG_PATTERN = re.compile(r"<[^>]+>")


def clean_html(text: str) -> str:
    return TAG_PATTERN.sub("", text)


def _normalize_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip().lstrip("/")
    if not normalized:
        raise ValueError("endpoint must not be empty")
    return normalized


def _build_cache_key(
    endpoint: str,
    params: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
) -> str:
    params_items = tuple(sorted((key, str(value)) for key, value in (params or {}).items()))
    headers_items = tuple(
        sorted((key.lower(), str(value)) for key, value in (headers or {}).items())
    )
    return json.dumps(
        (endpoint, params_items, headers_items),
        ensure_ascii=True,
        separators=(",", ":"),
    )


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
    ) -> None:
        self.base_url = f"{base_url.rstrip('/')}/"
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_max_entries = cache_max_entries

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
        normalized_endpoint = _normalize_endpoint(endpoint)
        cache_key = _build_cache_key(normalized_endpoint, params, headers)

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
                    logger.warning(
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
                logger.error("OpenGrok API error %d for %s: %s", status, endpoint, detail)
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
                    logger.warning(
                        "OpenGrok API request failed for %s (%s), retry %d/%d in %.2fs",
                        endpoint,
                        type(exc).__name__,
                        attempt + 1,
                        self.retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("Connection failure for %s: %s", endpoint, exc)
                raise RuntimeError(
                    f"Failed to connect to OpenGrok endpoint /{normalized_endpoint}: {exc}"
                ) from exc

        raise RuntimeError(f"Unexpected retry loop termination for /{normalized_endpoint}")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


OPENGROK_URL = os.environ.get("OPENGROK_URL", "http://localhost:8080/source").rstrip("/")
OPENGROK_API_URL = f"{OPENGROK_URL}/api/v1"

REQUEST_TIMEOUT_SECONDS = _read_float_env(
    "OPENGROK_TIMEOUT_SECONDS",
    default=30.0,
    min_value=1.0,
    max_value=300.0,
)
HTTP_RETRIES = _read_int_env(
    "OPENGROK_HTTP_RETRIES",
    default=2,
    min_value=0,
    max_value=10,
)
HTTP_RETRY_BACKOFF_SECONDS = _read_float_env(
    "OPENGROK_HTTP_RETRY_BACKOFF_SECONDS",
    default=0.25,
    min_value=0.05,
    max_value=10.0,
)
HTTP_MAX_CONNECTIONS = _read_int_env(
    "OPENGROK_HTTP_MAX_CONNECTIONS",
    default=100,
    min_value=1,
    max_value=1000,
)
HTTP_MAX_KEEPALIVE_CONNECTIONS = _read_int_env(
    "OPENGROK_HTTP_MAX_KEEPALIVE_CONNECTIONS",
    default=20,
    min_value=1,
    max_value=1000,
)
if HTTP_MAX_KEEPALIVE_CONNECTIONS > HTTP_MAX_CONNECTIONS:
    HTTP_MAX_KEEPALIVE_CONNECTIONS = HTTP_MAX_CONNECTIONS

CACHE_TTL_SECONDS = _read_float_env(
    "OPENGROK_CACHE_TTL_SECONDS",
    default=10.0,
    min_value=0.0,
    max_value=3600.0,
)
CACHE_MAX_ENTRIES = _read_int_env(
    "OPENGROK_CACHE_MAX_ENTRIES",
    default=256,
    min_value=1,
    max_value=10000,
)
MAX_RESULTS_CAP = _read_int_env(
    "OPENGROK_MAX_RESULTS_CAP",
    default=500,
    min_value=1,
    max_value=10000,
)

mcp = FastMCP("opengrok-mcp")

api_client = OpenGrokApiClient(
    base_url=OPENGROK_API_URL,
    timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    retries=HTTP_RETRIES,
    retry_backoff_seconds=HTTP_RETRY_BACKOFF_SECONDS,
    max_connections=HTTP_MAX_CONNECTIONS,
    max_keepalive_connections=HTTP_MAX_KEEPALIVE_CONNECTIONS,
    cache_ttl_seconds=CACHE_TTL_SECONDS,
    cache_max_entries=CACHE_MAX_ENTRIES,
)


async def fetch_opengrok_api(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    return await api_client.get(endpoint, params=params, headers=headers)


def _format_hits(
    file_path: str,
    hits: List[Dict[str, Any]],
    max_hits: Optional[int] = None,
    line_limit: int = 240,
) -> List[str]:
    output = [f"**File: `{file_path}`**"]
    displayed = hits if max_hits is None else hits[:max_hits]

    for hit in displayed:
        line_number = hit.get("lineNumber", "?")
        tag = str(hit.get("tag", "")).strip()
        line_text = clean_html(str(hit.get("line", "")).strip())
        if len(line_text) > line_limit:
            line_text = f"{line_text[:line_limit]}..."
        if tag:
            output.append(f"- Line {line_number} ({tag}): `{line_text}`")
        else:
            output.append(f"- Line {line_number}: `{line_text}`")

    if max_hits is not None and len(hits) > max_hits:
        output.append(f"- ... and {len(hits) - max_hits} more matches")

    output.append("")
    return output


@mcp.tool()
async def search(
    full: Optional[str] = None,
    defs: Optional[str] = None,
    refs: Optional[str] = None,
    path: Optional[str] = None,
    projects: Optional[str] = None,
    maxresults: int = 100,
) -> str:
    """
    Search for source code in OpenGrok using various fields.

    Args:
        full: Full text search query.
        defs: Symbol definitions.
        refs: Symbol references.
        path: File path pattern.
        projects: Comma-separated list of projects to search in.
        maxresults: Maximum results to return (default 100).
    """
    if not any([full, defs, refs, path]):
        return "At least one of full, defs, refs, or path must be provided."

    maxresults = _clamp(maxresults, 1, MAX_RESULTS_CAP)
    api_params = {
        "full": full,
        "def": defs,
        "symbol": refs,
        "path": path,
        "projects": projects,
        "maxresults": maxresults,
    }
    api_params = {key: value for key, value in api_params.items() if value is not None}

    results = await fetch_opengrok_api("search", params=api_params)
    if not isinstance(results, dict) or "results" not in results:
        return "No results found."

    output: List[str] = []
    total_found = results.get("resultCount", 0)
    output.append(f"### OpenGrok Search Results (Found {total_found})")
    output.append("")

    for file_path, hits in results.get("results", {}).items():
        output.extend(_format_hits(file_path, hits))

    return "\n".join(output)


@mcp.tool()
async def get_file(path: str) -> str:
    """
    Retrieve raw content of a specific file from OpenGrok.

    Args:
        path: Path of the file relative to source root.
    """
    normalized_path = _normalize_path(path)
    headers = {"Accept": "text/plain"}
    content = await fetch_opengrok_api(
        "file/content",
        params={"path": normalized_path},
        headers=headers,
    )
    return str(content)


@mcp.tool()
async def get_defs(path: str) -> str:
    """Get symbol definitions for a specific file."""
    normalized_path = _normalize_path(path)
    results = await fetch_opengrok_api("file/defs", params={"path": normalized_path})
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_history(path: str, withFiles: bool = False, max: int = 1000) -> str:
    """Get revision history for a file or directory."""
    normalized_path = _normalize_path(path)
    max_items = _clamp(max, 1, 10000)
    api_params = {"path": normalized_path, "withFiles": withFiles, "max": max_items}
    results = await fetch_opengrok_api("history", params=api_params)
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_annotations(path: str) -> str:
    """Get blame/annotation information for a file."""
    normalized_path = _normalize_path(path)
    results = await fetch_opengrok_api("annotation", params={"path": normalized_path})
    return json.dumps(results, indent=2)


@mcp.tool()
async def list_directory(path: str) -> str:
    """List entries in a directory."""
    normalized_path = _normalize_path(path)
    results = await fetch_opengrok_api("list", params={"path": normalized_path})
    return json.dumps(results, indent=2)


@mcp.tool()
async def list_projects() -> str:
    """List all projects indexed in this OpenGrok instance."""
    projects = await fetch_opengrok_api("projects")
    return json.dumps(projects, indent=2)


@mcp.tool()
async def search_symbols_global(
    symbol: str,
    projects: Optional[str] = None,
    search_type: str = "defs",
    maxresults: int = 100,
) -> str:
    """
    Search for symbol definitions or references across indexed projects.

    Args:
        symbol: Symbol name to search for.
        projects: Comma-separated list of projects to limit search to.
        search_type: One of defs, refs, or both.
        maxresults: Maximum results to return.
    """
    normalized_symbol = symbol.strip()
    if not normalized_symbol:
        return "symbol must not be empty."

    normalized_search_type = search_type.strip().lower()
    if normalized_search_type not in {"defs", "refs", "both"}:
        return "search_type must be one of: defs, refs, both."

    maxresults = _clamp(maxresults, 1, MAX_RESULTS_CAP)
    grouped_results: List[Tuple[str, Dict[str, Any]]] = []

    if normalized_search_type in {"defs", "both"}:
        defs_params = {
            "def": normalized_symbol,
            "projects": projects,
            "maxresults": maxresults,
        }
        defs_params = {key: value for key, value in defs_params.items() if value is not None}
        defs_results = await fetch_opengrok_api("search", params=defs_params)
        if isinstance(defs_results, dict) and "results" in defs_results:
            grouped_results.append(("DEFINITIONS", defs_results))

    if normalized_search_type in {"refs", "both"}:
        refs_params = {
            "symbol": normalized_symbol,
            "projects": projects,
            "maxresults": maxresults,
        }
        refs_params = {key: value for key, value in refs_params.items() if value is not None}
        refs_results = await fetch_opengrok_api("search", params=refs_params)
        if isinstance(refs_results, dict) and "results" in refs_results:
            grouped_results.append(("REFERENCES", refs_results))

    if not grouped_results:
        return f"No symbol definitions or references found for '{normalized_symbol}'."

    output = [f"### Cross-file Symbol Search: `{normalized_symbol}`", ""]
    for section_label, search_data in grouped_results:
        total_found = search_data.get("resultCount", 0)
        output.append(f"#### {section_label} ({total_found} found)")
        output.append("")
        for file_path, hits in search_data.get("results", {}).items():
            output.extend(_format_hits(file_path, hits))

    return "\n".join(output)


@mcp.tool()
async def compare_revisions(
    path: str,
    rev1: str,
    rev2: str,
    context: int = 3,
) -> str:
    """
    Compare two revisions of a file to show differences.

    Args:
        path: Path to the file relative to source root.
        rev1: First revision ID.
        rev2: Second revision ID.
        context: Number of context lines (default 3).
    """
    normalized_path = _normalize_path(path)
    rev1 = rev1.strip()
    rev2 = rev2.strip()
    if not rev1 or not rev2:
        return "rev1 and rev2 must not be empty."
    if rev1 == rev2:
        return "rev1 and rev2 are identical; no differences to compare."

    context = _clamp(context, 0, 50)
    headers = {"Accept": "text/plain"}
    content1 = await fetch_opengrok_api(
        "file/content",
        params={"path": normalized_path, "revision": rev1},
        headers=headers,
    )
    content2 = await fetch_opengrok_api(
        "file/content",
        params={"path": normalized_path, "revision": rev2},
        headers=headers,
    )

    lines1 = str(content1).splitlines()
    lines2 = str(content2).splitlines()
    diff = list(
        difflib.unified_diff(
            lines1,
            lines2,
            fromfile=f"rev1 ({rev1[:8]})",
            tofile=f"rev2 ({rev2[:8]})",
            lineterm="",
            n=context,
        )
    )

    if not diff:
        return f"No differences found between {rev1[:8]} and {rev2[:8]}."

    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

    output = [
        f"### Diff: {normalized_path}",
        "",
        f"Comparing: {rev1[:8]}... vs {rev2[:8]}...",
        "",
        "```diff",
        *diff,
        "```",
        "",
        f"Summary: +{added} lines added, -{removed} lines removed",
    ]
    return "\n".join(output)


@mcp.tool()
async def search_enhanced(
    full: Optional[str] = None,
    defs: Optional[str] = None,
    refs: Optional[str] = None,
    path: Optional[str] = None,
    projects: Optional[str] = None,
    file_types: Optional[str] = None,
    maxresults: int = 100,
    page: int = 1,
    summarize: bool = True,
) -> str:
    """
    Enhanced search with filters, pagination, and summarization.

    Args:
        full: Full text search query.
        defs: Symbol definitions.
        refs: Symbol references.
        path: File path pattern.
        projects: Comma-separated list of projects.
        file_types: Comma-separated file extensions, e.g. "java,py,js".
        maxresults: Maximum results per page.
        page: Page number (1-based).
        summarize: Summarize if result set is large.
    """
    if not any([full, defs, refs, path]):
        return "At least one of full, defs, refs, or path must be provided."

    maxresults = _clamp(maxresults, 1, MAX_RESULTS_CAP)
    page = max(page, 1)
    api_params = {
        "full": full,
        "def": defs,
        "symbol": refs,
        "path": path,
        "projects": projects,
        "maxresults": maxresults,
        "page": page,
    }
    api_params = {key: value for key, value in api_params.items() if value is not None}

    results = await fetch_opengrok_api("search", params=api_params)
    if not isinstance(results, dict) or "results" not in results:
        return "No results found."

    all_results: Dict[str, List[Dict[str, Any]]] = dict(results.get("results", {}))
    total_found = int(results.get("resultCount", 0))

    if file_types:
        extensions = {
            f".{item.strip().lstrip('.').lower()}"
            for item in file_types.split(",")
            if item.strip()
        }
        all_results = {
            file_path: hits
            for file_path, hits in all_results.items()
            if os.path.splitext(file_path)[1].lower() in extensions
        }
        total_found = sum(len(hits) for hits in all_results.values())

    output = ["### OpenGrok Enhanced Search Results"]
    output.append(f"**Total Found:** {total_found} | **Page:** {page}")
    if projects:
        output.append(f"**Projects:** {projects}")
    if file_types:
        output.append(f"**File Types:** {file_types}")
    output.append("")

    file_count = len(all_results)
    hit_count = sum(len(hits) for hits in all_results.values())

    if summarize and hit_count > 80:
        output.append(f"**Summary:** Found {hit_count} matches across {file_count} files.")
        output.append("Showing top results:")
        output.append("")
        top_files = sorted(all_results.items(), key=lambda item: len(item[1]), reverse=True)[:10]
        for file_path, hits in top_files:
            output.extend(_format_hits(file_path, hits, max_hits=5, line_limit=120))
        output.append("_Results truncated for large dataset. Use page/maxresults for details._")
    else:
        for file_path, hits in all_results.items():
            output.extend(_format_hits(file_path, hits))

    return "\n".join(output)


@mcp.tool()
async def get_suggestions(
    query: str,
    projects: Optional[str] = None,
    max_results: int = 10,
) -> str:
    """
    Get search suggestions based on query prefix.

    Args:
        query: Query prefix.
        projects: Optional project filter.
        max_results: Maximum number of suggestions.
    """
    normalized_query = query.strip()
    if not normalized_query:
        return "query must not be empty."

    max_results = _clamp(max_results, 1, 100)
    api_params = {
        "query": normalized_query,
        "projects": projects,
        "maxResults": max_results,
    }
    api_params = {key: value for key, value in api_params.items() if value is not None}

    suggestions = await fetch_opengrok_api("suggest", params=api_params)
    if not suggestions:
        return f"No suggestions found for '{normalized_query}'."

    output = [f"### Search Suggestions for: `{normalized_query}`", ""]
    if isinstance(suggestions, dict) and "suggestions" in suggestions:
        for item in suggestions.get("suggestions", []):
            word = item.get("word", "")
            score = item.get("score", 0)
            output.append(f"- **{word}** ({score} matches)")
    elif isinstance(suggestions, list):
        for item in suggestions:
            if isinstance(item, dict):
                word = item.get("word", item.get("text", ""))
                output.append(f"- **{word}**")
            else:
                output.append(f"- **{item}**")
    else:
        return json.dumps(suggestions, indent=2)
    return "\n".join(output)


@mcp.tool()
async def health_check() -> str:
    """Return runtime and OpenGrok connectivity status."""
    payload: Dict[str, Any] = {
        "server": "opengrok-mcp",
        "opengrok_url": OPENGROK_URL,
        "opengrok_api_url": OPENGROK_API_URL,
        "http_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        "http_retries": HTTP_RETRIES,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "cache_max_entries": CACHE_MAX_ENTRIES,
    }
    try:
        projects = await fetch_opengrok_api("projects")
        payload["opengrok_reachable"] = True
        if isinstance(projects, list):
            payload["project_count"] = len(projects)
        elif isinstance(projects, dict):
            if isinstance(projects.get("projects"), list):
                payload["project_count"] = len(projects["projects"])
            elif isinstance(projects.get("items"), list):
                payload["project_count"] = len(projects["items"])
        return json.dumps(payload, indent=2)
    except Exception as exc:
        payload["opengrok_reachable"] = False
        payload["error"] = str(exc)
        return json.dumps(payload, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenGrok MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", os.environ.get("MCP_PORT", 8081))),
        help="Port (default: 8081, can be overridden by PORT or MCP_PORT)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("HOST", "0.0.0.0"),
        help="Host to bind (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    logger.info(
        "Starting OpenGrok MCP Server on %s:%d with transport=%s",
        args.host,
        args.port,
        args.transport,
    )
    logger.info("OpenGrok API URL: %s", OPENGROK_API_URL)
    logger.info(
        "HTTP timeout=%ss retries=%d backoff=%ss pool=%d keepalive=%d cache_ttl=%ss cache_size=%d",
        REQUEST_TIMEOUT_SECONDS,
        HTTP_RETRIES,
        HTTP_RETRY_BACKOFF_SECONDS,
        HTTP_MAX_CONNECTIONS,
        HTTP_MAX_KEEPALIVE_CONNECTIONS,
        CACHE_TTL_SECONDS,
        CACHE_MAX_ENTRIES,
    )

    try:
        if args.transport == "streamable-http":
            mcp.run(transport="streamable-http")
        elif args.transport == "sse":
            mcp.run(transport="sse")
        else:
            mcp.run(transport="stdio")
    except Exception:
        logger.exception("Server terminated with error")
        raise
    finally:
        try:
            asyncio.run(api_client.close())
        except RuntimeError:
            pass


if __name__ == "__main__":
    main()
