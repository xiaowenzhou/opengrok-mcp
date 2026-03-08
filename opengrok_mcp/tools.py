import difflib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

from .api_client import OpenGrokApiClient
from .config import ServerConfig
from .utils import clamp, format_hits, normalize_path


def register_tools(mcp: FastMCP, api_client: OpenGrokApiClient, config: ServerConfig) -> None:
    async def fetch_opengrok_api(
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        return await api_client.get(endpoint, params=params, headers=headers)

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

        maxresults = clamp(maxresults, 1, config.max_results_cap)
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
            output.extend(format_hits(file_path, hits))

        return "\n".join(output)

    @mcp.tool()
    async def get_file(path: str) -> str:
        """
        Retrieve raw content of a specific file from OpenGrok.

        Args:
            path: Path of the file relative to source root.
        """
        normalized_path = normalize_path(path)
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
        normalized_path = normalize_path(path)
        results = await fetch_opengrok_api("file/defs", params={"path": normalized_path})
        return json.dumps(results, indent=2)

    @mcp.tool()
    async def get_history(path: str, withFiles: bool = False, max: int = 1000) -> str:
        """Get revision history for a file or directory."""
        normalized_path = normalize_path(path)
        max_items = clamp(max, 1, 10000)
        api_params = {"path": normalized_path, "withFiles": withFiles, "max": max_items}
        results = await fetch_opengrok_api("history", params=api_params)
        return json.dumps(results, indent=2)

    @mcp.tool()
    async def get_annotations(path: str) -> str:
        """Get blame/annotation information for a file."""
        normalized_path = normalize_path(path)
        results = await fetch_opengrok_api("annotation", params={"path": normalized_path})
        return json.dumps(results, indent=2)

    @mcp.tool()
    async def list_directory(path: str) -> str:
        """List entries in a directory."""
        normalized_path = normalize_path(path)
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

        maxresults = clamp(maxresults, 1, config.max_results_cap)
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
                output.extend(format_hits(file_path, hits))

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
        normalized_path = normalize_path(path)
        rev1 = rev1.strip()
        rev2 = rev2.strip()
        if not rev1 or not rev2:
            return "rev1 and rev2 must not be empty."
        if rev1 == rev2:
            return "rev1 and rev2 are identical; no differences to compare."

        context = clamp(context, 0, 50)
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

        maxresults = clamp(maxresults, 1, config.max_results_cap)
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
            top_files = sorted(all_results.items(), key=lambda item: len(item[1]), reverse=True)[
                :10
            ]
            for file_path, hits in top_files:
                output.extend(format_hits(file_path, hits, max_hits=5, line_limit=120))
            output.append("_Results truncated for large dataset. Use page/maxresults for details._")
        else:
            for file_path, hits in all_results.items():
                output.extend(format_hits(file_path, hits))

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

        max_results = clamp(max_results, 1, 100)
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
            "opengrok_url": config.opengrok_url,
            "opengrok_api_url": config.opengrok_api_url,
            "http_timeout_seconds": config.request_timeout_seconds,
            "http_retries": config.http_retries,
            "cache_ttl_seconds": config.cache_ttl_seconds,
            "cache_max_entries": config.cache_max_entries,
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
