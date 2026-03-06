import os
import json
import logging
import argparse
from typing import Optional, List, Dict, Any
import httpx
from mcp.server.fastmcp import FastMCP
import mcp.types as types

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("opengrok-mcp")

# Configuration from environment variables
OPENGROK_URL = os.environ.get("OPENGROK_URL", "http://localhost:8080/source").rstrip("/")
OPENGROK_API_URL = f"{OPENGROK_URL}/api/v1"

# Initialize FastMCP
mcp = FastMCP("opengrok-mcp")

async def fetch_opengrok_api(endpoint: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
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
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e.response.text}")
            raise Exception(f"OpenGrok API error: {e.response.status_code} - {e.response.text}")
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
    maxresults: int = 100
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
        "maxresults": maxresults
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
            # Clean up Lucene bold tags if present
            line_text = line_text.replace("<b>", "").replace("</b>", "")
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
    content = await fetch_opengrok_api("/file/content", params={"path": path}, headers=headers)
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenGrok MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport type (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")

    args = parser.parse_args()

    if args.transport == "http":
        # FastMCP internal uses 'streamable-http' for the new streaming mode
        # We also need to handle the port, but FastMCP.run() is a bit high-level.
        # Usually it uses environment variables or we can use a custom runner.
        # For simplicity, we'll map 'http' to 'streamable-http'
        mcp.run(transport="streamable-http")
    elif args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
