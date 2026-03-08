import asyncio
import os

import httpx


MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8081").rstrip("/")


async def raw_http_test() -> None:
    print(f"Performing raw HTTP probe on {MCP_BASE_URL} ...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(MCP_BASE_URL)
            print(f"Root endpoint status: {response.status_code}")
            if response.status_code in (200, 404, 405):
                print("Server is active and listening.")
            else:
                print("Server responded, but status is unexpected.")
        except Exception as exc:
            print(f"Probe failed: {exc}")


if __name__ == "__main__":
    asyncio.run(raw_http_test())
