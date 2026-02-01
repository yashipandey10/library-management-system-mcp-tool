from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Settings, settings
from .http_client import HttpClient
from .middleware import McpAuthMiddleware, origin_allowed
from .tools import register_tools


def build_app(cfg: Settings = settings) -> Starlette:
    """Create the Starlette app with MCP routes and middleware."""
    mcp = FastMCP("Library Management System MCP")
    http_client = HttpClient(cfg.library_api_base_url, cfg.library_api_access_token)
    register_tools(mcp, http_client)

    async def health(_request):
        return JSONResponse({"status": "ok"})

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    routes = [
        Route("/health", health),
        # FastMCP already exposes /mcp; mount at root to avoid /mcp/mcp and 307->404.
        Mount("/", app=mcp.streamable_http_app()),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(McpAuthMiddleware)

    if cfg.allowed_origins:
        allow_origins = ["*"] if "*" in cfg.allowed_origins else cfg.allowed_origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    return app
