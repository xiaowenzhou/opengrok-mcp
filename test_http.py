import asyncio
import os

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8081").rstrip("/")
MCP_SSE_URL = os.environ.get("MCP_SSE_URL", f"{MCP_BASE_URL}/sse")


async def test_http() -> None:
    print(f"Testing OpenGrok MCP SSE endpoint: {MCP_SSE_URL}")
    try:
        async with sse_client(MCP_SSE_URL) as (read, write):
            async with ClientSession(read, write) as session:
                print("Initializing session...")
                await session.initialize()

                print("\nListing tools...")
                tools = await session.list_tools()
                tool_names = [tool.name for tool in tools.tools]
                print(f"Available tools ({len(tool_names)}): {tool_names}")

                print("\nCalling health_check...")
                health = await session.call_tool("health_check", {})
                print(health.content[0].text[:300])
    except Exception as exc:
        print(f"Connection failed (is SSE transport enabled?): {exc}")


if __name__ == "__main__":
    asyncio.run(test_http())
