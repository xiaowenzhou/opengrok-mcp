import os
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any
import httpx
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server.stdio import stdio_server

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("opengrok-mcp")

# Configuration from environment variables
OPENGROK_URL = os.environ.get("OPENGROK_URL", "http://localhost:8080/source").rstrip("/")
# The API usually lives under /api/v1
OPENGROK_API_URL = f"{OPENGROK_URL}/api/v1"

server = Server("opengrok-mcp")

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

@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="search",
            description="Search for source code in OpenGrok using various fields (full text, definition, symbol, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "full": {"type": "string", "description": "Full text search query"},
                    "defs": {"type": "string", "description": "Symbol definitions"},
                    "refs": {"type": "string", "description": "Symbol references"},
                    "path": {"type": "string", "description": "File path pattern"},
                    "projects": {"type": "string", "description": "Comma-separated list of projects to search in"},
                    "maxresults": {"type": "integer", "description": "Maximum results to return (default 100)", "default": 100},
                },
            },
        ),
        types.Tool(
            name="get_file",
            description="Retrieve the raw content of a specific file from OpenGrok",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file relative to source root (e.g., /project/src/main.c)"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="list_projects",
            description="List all projects indexed in this OpenGrok instance",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: Optional[Dict[str, Any]]
) -> List[types.TextContent]:
    """Handle tool execution."""
    try:
        if name == "search":
            params = arguments or {}
            # OpenGrok API search params: full, def, symbol, path, hist, type, projects, maxresults, start, sort
            # Map common names to OpenGrok params
            api_params = {
                "full": params.get("full"),
                "def": params.get("defs"),
                "symbol": params.get("refs"),
                "path": params.get("path"),
                "projects": params.get("projects"),
                "maxresults": params.get("maxresults", 100)
            }
            # Remove None values
            api_params = {k: v for k, v in api_params.items() if v is not None}
            
            results = await fetch_opengrok_api("/search", params=api_params)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_file":
            path = arguments.get("path")
            if not path:
                raise ValueError("Path is required")
            
            # File content API expects path as a query param
            # Headers for plain text
            headers = {"Accept": "text/plain"}
            content = await fetch_opengrok_api("/file/content", params={"path": path}, headers=headers)
            return [types.TextContent(type="text", text=content)]

        elif name == "list_projects":
            projects = await fetch_opengrok_api("/projects")
            return [types.TextContent(type="text", text=json.dumps(projects, indent=2))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Tool execution failed: {str(e)}")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="opengrok-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
