import os
import re
import json
import logging
import argparse
from typing import Optional, List, Dict, Any
import httpx
from mcp.server.fastmcp import FastMCP
import mcp.types as types


def clean_html(text: str) -> str:
    """Remove all HTML tags from text."""
    return re.sub(r"<[^>]+>", "", text)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("opengrok-mcp")

# Configuration from environment variables
OPENGROK_URL = os.environ.get("OPENGROK_URL", "http://localhost:8080/source").rstrip(
    "/"
)
OPENGROK_API_URL = f"{OPENGROK_URL}/api/v1"

# Initialize FastMCP
mcp = FastMCP("opengrok-mcp")


async def fetch_opengrok_api(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """Helper to make GET requests to OpenGrok API."""
    url = f"{OPENGROK_API_URL}{endpoint}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error {e.response.status_code} for {url}: {e.response.text}"
            )
            raise Exception(
                f"OpenGrok API error: {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            raise Exception(f"Failed to connect to OpenGrok: {str(e)}")


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
        full: Full text search query
        defs: Symbol definitions
        refs: Symbol references
        path: File path pattern
        projects: Comma-separated list of projects to search in
        maxresults: Maximum results to return (default 100)
    """
    api_params = {
        "full": full,
        "def": defs,
        "symbol": refs,
        "path": path,
        "projects": projects,
        "maxresults": maxresults,
    }
    api_params = {k: v for k, v in api_params.items() if v is not None}

    results = await fetch_opengrok_api("/search", params=api_params)

    # 改进搜索输出：结构化展示结果，方便 LLM 阅读
    if not results or "results" not in results:
        return "No results found."

    output = []
    total_found = results.get("resultCount", 0)
    output.append(f"### OpenGrok Search Results (Found {total_found})\n")

    for file_path, hits in results.get("results", {}).items():
        output.append(f"**File: `{file_path}`**")
        for hit in hits:
            line_num = hit.get("lineNumber", "?")
            line_text = hit.get("line", "").strip()
            line_text = clean_html(line_text)
            tag = hit.get("tag", "")
            output.append(f"- Line {line_num} ({tag}): `{line_text}`")
        output.append("")

    return "\n".join(output)


@mcp.tool()
async def get_file(path: str) -> str:
    """
    Retrieve the raw content of a specific file from OpenGrok.

    Args:
        path: Path of the file relative to source root (e.g., /project/src/main.c)
    """
    headers = {"Accept": "text/plain"}
    content = await fetch_opengrok_api(
        "/file/content", params={"path": path}, headers=headers
    )
    return content


@mcp.tool()
async def get_defs(path: str) -> str:
    """Get symbol definitions for a specific file."""
    results = await fetch_opengrok_api("/file/defs", params={"path": path})
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_history(path: str, withFiles: bool = False, max: int = 1000) -> str:
    """Get revision history for a file or directory."""
    api_params = {"path": path, "withFiles": withFiles, "max": max}
    results = await fetch_opengrok_api("/history", params=api_params)
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_annotations(path: str) -> str:
    """Get blame/annotation information for a file."""
    results = await fetch_opengrok_api("/annotation", params={"path": path})
    return json.dumps(results, indent=2)


@mcp.tool()
async def list_directory(path: str) -> str:
    """List entries in a directory."""
    results = await fetch_opengrok_api("/list", params={"path": path})
    return json.dumps(results, indent=2)


@mcp.tool()
async def list_projects() -> str:
    """List all projects indexed in this OpenGrok instance."""
    projects = await fetch_opengrok_api("/projects")
    return json.dumps(projects, indent=2)


@mcp.tool()
async def search_symbols_global(
    symbol: str,
    projects: Optional[str] = None,
    search_type: str = "defs",
    maxresults: int = 100,
) -> str:
    """
    Search for symbol definitions or references across all indexed projects.

    Args:
        symbol: Symbol name to search for
        projects: Comma-separated list of projects to limit search to
        search_type: Type of search - 'defs' (definitions), 'refs' (references), or 'both'
        maxresults: Maximum results to return (default 100)
    """
    results = []

    if search_type in ("defs", "both"):
        defs_params = {
            "def": symbol,
            "projects": projects,
            "maxresults": maxresults,
        }
        defs_params = {k: v for k, v in defs_params.items() if v is not None}
        defs_results = await fetch_opengrok_api("/search", params=defs_params)
        if defs_results and "results" in defs_results:
            results.append(("DEFINITIONS", defs_results))

    if search_type in ("refs", "both"):
        refs_params = {
            "symbol": symbol,
            "projects": projects,
            "maxresults": maxresults,
        }
        refs_params = {k: v for k, v in refs_params.items() if v is not None}
        refs_results = await fetch_opengrok_api("/search", params=refs_params)
        if refs_results and "results" in refs_results:
            results.append(("REFERENCES", refs_results))

    if not results:
        return f"No symbol definitions or references found for '{symbol}'"

    output = [f"### Cross-file Symbol Search: `{symbol}`\n"]

    for search_type_label, search_data in results:
        total_found = search_data.get("resultCount", 0)
        output.append(f"#### {search_type_label} ({total_found} found)")

        for file_path, hits in search_data.get("results", {}).items():
            output.append(f"**File: `{file_path}`**")
            for hit in hits:
                line_num = hit.get("lineNumber", "?")
                line_text = hit.get("line", "").strip()
                line_text = clean_html(line_text)
                tag = hit.get("tag", "")
                output.append(f"- Line {line_num} ({tag}): `{line_text}`")
            output.append("")

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
        path: Path to the file relative to source root
        rev1: First revision ID
        rev2: Second revision ID
        context: Number of context lines to show (default 3)
    """
    headers = {"Accept": "text/plain"}

    content1 = await fetch_opengrok_api(
        "/file/content", params={"path": path, "revision": rev1}, headers=headers
    )
    content2 = await fetch_opengrok_api(
        "/file/content", params={"path": path, "revision": rev2}, headers=headers
    )

    lines1 = content1.splitlines()
    lines2 = content2.splitlines()

    diff_output = [
        f"### Diff: {path}\n",
        f"Comparing: {rev1[:8]}... vs {rev2[:8]}...\n",
    ]

    import difflib

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
        return f"No differences found between {rev1[:8]} and {rev2[:8]}"

    diff_output.append("```diff")
    diff_output.extend(diff)
    diff_output.append("```")

    stats = {
        "added": len(
            [l for l in diff if l.startswith("+") and not l.startswith("+++")]
        ),
        "removed": len(
            [l for l in diff if l.startswith("-") and not l.startswith("---")]
        ),
    }
    diff_output.append(
        f"\nSummary: +{stats['added']} lines added, -{stats['removed']} lines removed"
    )

    return "\n".join(diff_output)


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
    Enhanced search with filters, pagination and auto-summarization.

    Args:
        full: Full text search query
        defs: Symbol definitions
        refs: Symbol references
        path: File path pattern (supports wildcards like *.java)
        projects: Comma-separated list of projects
        file_types: Comma-separated file extensions (e.g., "java,py,js")
        maxresults: Maximum results per page (default 100)
        page: Page number to retrieve (default 1)
        summarize: If true, summarize large results instead of showing all
    """
    api_params = {
        "full": full,
        "def": defs,
        "symbol": refs,
        "path": path,
        "projects": projects,
        "maxresults": maxresults,
        "page": page,
    }
    api_params = {k: v for k, v in api_params.items() if v is not None}

    results = await fetch_opengrok_api("/search", params=api_params)

    if not results or "results" not in results:
        return "No results found."

    all_results = results.get("results", {})
    total_found = results.get("resultCount", 0)

    if file_types:
        ft_filters = [f".{ft.lstrip('.')}" for ft in file_types.split(",")]
        filtered_results = {}
        for fp, hits in all_results.items():
            if any(fp.endswith(ft) for ft in ft_filters):
                filtered_results[fp] = hits
        all_results = filtered_results
        total_found = sum(len(hits) for hits in all_results.values())

    output = [f"### OpenGrok Enhanced Search Results"]
    output.append(f"**Total Found:** {total_found} | **Page:** {page}")
    if projects:
        output.append(f"**Projects:** {projects}")
    if file_types:
        output.append(f"**File Types:** {file_types}")
    output.append("")

    file_count = len(all_results)
    hit_count = sum(len(hits) for hits in all_results.values())

    if summarize and hit_count > 50:
        output.append(
            f"**Summary:** Found {hit_count} matches across {file_count} files."
        )
        output.append("Showing top results:\n")

        sorted_files = sorted(
            all_results.items(), key=lambda x: len(x[1]), reverse=True
        )[:10]

        for file_path, hits in sorted_files:
            output.append(f"**`{file_path}`** ({len(hits)} matches)")
            for hit in hits[:5]:
                line_num = hit.get("lineNumber", "?")
                line_text = clean_html(hit.get("line", "").strip())
                output.append(f"  - Line {line_num}: `{line_text[:100]}`")
            if len(hits) > 5:
                output.append(f"  - ... and {len(hits) - 5} more")
            output.append("")

        output.append(
            f"_Results truncated for large dataset. Use page parameter to fetch more._"
        )
    else:
        for file_path, hits in all_results.items():
            output.append(f"**File: `{file_path}`**")
            for hit in hits:
                line_num = hit.get("lineNumber", "?")
                line_text = clean_html(hit.get("line", "").strip())
                tag = hit.get("tag", "")
                output.append(f"- Line {line_num} ({tag}): `{line_text}`")
            output.append("")

    return "\n".join(output)


@mcp.tool()
async def get_suggestions(
    query: str,
    projects: Optional[str] = None,
    max_results: int = 10,
) -> str:
    """
    Get search suggestions based on query prefix for autocomplete.

    Args:
        query: Query prefix to get suggestions for
        projects: Optional project filter
        max_results: Maximum number of suggestions (default 10)
    """
    api_params = {
        "query": query,
        "projects": projects,
        "maxResults": max_results,
    }
    api_params = {k: v for k, v in api_params.items() if v is not None}

    suggestions = await fetch_opengrok_api("/suggest", params=api_params)

    if not suggestions:
        return f"No suggestions found for '{query}'"

    output = [f"### Search Suggestions for: `{query}`\n"]

    if isinstance(suggestions, dict) and "suggestions" in suggestions:
        for item in suggestions.get("suggestions", []):
            output.append(
                f"- **{item.get('word', '')}** ({item.get('score', 0)} matches)"
            )
    elif isinstance(suggestions, list):
        for item in suggestions:
            if isinstance(item, dict):
                output.append(f"- **{item.get('word', item.get('text', ''))}**")
            else:
                output.append(f"- **{item}**")
    else:
        return json.dumps(suggestions, indent=2)

    return "\n".join(output)


if __name__ == "__main__":
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
        help="Port (default: 8081, can be overridden by PORT or MCP_PORT env)",
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
        f"Starting OpenGrok MCP Server on {args.host}:{args.port} with transport {args.transport}"
    )
    logger.info(f"OpenGrok API URL: {OPENGROK_API_URL}")

    try:
        if args.transport == "streamable-http":
            mcp.run(transport="streamable-http")
        elif args.transport == "sse":
            mcp.run(transport="sse")
        else:
            mcp.run(transport="stdio")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
