import asyncio
import httpx
from mcp.client.sse import sse_client

async def test_http():
    print("Testing OpenGrok MCP HTTP Server...")
    try:
        async with sse_client("http://localhost:8001/sse") as (read, write):
            from mcp.client.session import ClientSession
            async with ClientSession(read, write) as session:
                print("Initializing session...")
                await session.initialize()
                
                print("\nListing tools...")
                tools = await session.list_tools()
                print(f"Available tools: {[t.name for t in tools.tools]}")
                
                print("\nCalling list_projects...")
                result = await session.call_tool("list_projects", {})
                print(f"Result (truncated): {result.content[0].text[:200]}...")

    except Exception as e:
        print(f"Connection failed (is the server running?): {e}")

if __name__ == "__main__":
    asyncio.run(test_http())
