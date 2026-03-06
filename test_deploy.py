import asyncio
import httpx
from mcp.client.session import ClientSession
from mcp.client.http import HTTPClientTransport

async def test_deployed_service():
    print("Testing deployed OpenGrok MCP service on port 8081...")
    # Using the standardized Streamable HTTP transport
    async with HTTPClientTransport("http://localhost:8081") as transport:
        async with ClientSession(transport) as session:
            print("Connecting and initializing...")
            await session.initialize()
            
            print("\nListing tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")
            
            print("\nCalling list_projects tool...")
            result = await session.call_tool("list_projects", {})
            print(f"Result (first 100 chars): {result.content[0].text[:100]}...")

if __name__ == "__main__":
    try:
        asyncio.run(test_deployed_service())
    except Exception as e:
        print(f"\nTest failed: {e}")
