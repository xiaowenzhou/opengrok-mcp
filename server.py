import os
import json
import asyncio
import logging
import argparse
from typing import Optional, List, Dict, Any
import httpx
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server.stdio import stdio_server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
import uvicorn

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
            name="get_defs",
            description="Get symbol definitions for a specific file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file relative to source root"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="get_history",
            description="Get revision history for a file or directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to source root"},
                    "withFiles": {"type": "boolean", "description": "Include list of files in each revision"},
                    "max": {"type": "integer", "description": "Maximum entries to return (default 1000)"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="get_annotations",
            description="Get blame/annotation information for a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to source root"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="list_directory",
            description="List entries in a directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path starting with / (e.g., /project/src)"},
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

        elif name == "get_defs":
            path = arguments.get("path")
            if not path:
                raise ValueError("Path is required")
            results = await fetch_opengrok_api("/file/defs", params={"path": path})
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_history":
            path = arguments.get("path")
            if not path:
                raise ValueError("Path is required")
            api_params = {
                "path": path,
                "withFiles": arguments.get("withFiles"),
                "max": arguments.get("max")
            }
            api_params = {k: v for k, v in api_params.items() if v is not None}
            results = await fetch_opengrok_api("/history", params=api_params)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_annotations":
            path = arguments.get("path")
            if not path:
                raise ValueError("Path is required")
            results = await fetch_opengrok_api("/annotation", params={"path": path})
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "list_directory":
            path = arguments.get("path")
            if not path:
                raise ValueError("Path is required")
            results = await fetch_opengrok_api("/list", params={"path": path})
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "list_projects":
            projects = await fetch_opengrok_api("/projects")
            return [types.TextContent(type="text", text=json.dumps(projects, indent=2))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Tool execution failed: {str(e)}")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

async def run_stdio():
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

async def run_sse(host: str, port: int):
    sse = SseServerTransport("/messages")

    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (
            read_stream,
            write_stream,
        ):
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

    app = Starlette(
        debug=True,
        routes=[
            Route("/sse", handle_sse),
            Mount("/messages", sse.handle_post_message),
        ],
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenGrok MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport type (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="SSE host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="SSE port (default: 8000)")

    args = parser.parse_args()

    if args.transport == "stdio":
        asyncio.run(run_stdio())
    else:
        asyncio.run(run_sse(args.host, args.port))
