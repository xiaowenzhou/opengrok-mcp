import asyncio
import httpx

async def raw_http_test():
    print("Performing raw HTTP probe on http://localhost:8081...")
    async with httpx.AsyncClient() as client:
        try:
            # MCP Streamable HTTP uses a specific handshake or endpoint structure.
            # Even a GET on root or a common endpoint should tell us if it's alive.
            response = await client.get("http://localhost:8081/status")
            print(f"Status endpoint: {response.status_code}")
            
            # Try to list tools via the standard MCP HTTP JSON-RPC POST (if applicable)
            # but usually, we just need to see if the server responds to confirm deployment.
            print("Server is active and listening.")
        except Exception as e:
            print(f"Probe failed: {e}")

if __name__ == "__main__":
    asyncio.run(raw_http_test())
