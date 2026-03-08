import asyncio
import os

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8081").rstrip("/")
MCP_STREAMABLE_HTTP_URL = os.environ.get(
    "MCP_STREAMABLE_HTTP_URL", f"{MCP_BASE_URL}/mcp"
).rstrip("/")


async def test_deployed_service() -> None:
    print(f"Testing deployed OpenGrok MCP service: {MCP_STREAMABLE_HTTP_URL}")
    async with streamable_http_client(MCP_STREAMABLE_HTTP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            print("Connecting and initializing...")
            await session.initialize()

            print("\nListing tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")

            print("\nCalling health_check tool...")
            result = await session.call_tool("health_check", {})
            print(f"Result (first 300 chars): {result.content[0].text[:300]}...")


if __name__ == "__main__":
    try:
        asyncio.run(test_deployed_service())
    except Exception as exc:
        import traceback

        print(f"\nTest failed: {exc!r}")
        traceback.print_exc()
