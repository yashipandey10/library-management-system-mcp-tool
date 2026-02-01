import anyio
import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

async def main():
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http_client) as (read, write, _get_session_id):
            session = ClientSession(read, write)
            await session.initialize()
            tools = await session.list_tools()
            print("tools", [t.name for t in tools.tools])

anyio.run(main)
