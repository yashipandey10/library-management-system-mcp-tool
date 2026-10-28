from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .config import settings


def origin_allowed(origin: str | None) -> bool:
    """Return True when origin matches allowlist or wildcard."""
    if not origin:
        return True  # allow tools/curl with no Origin
    if not settings.allowed_origins:
        return False
    if "*" in settings.allowed_origins:
        return True
    return origin in settings.allowed_origins


class McpStreamCompatibilityMiddleware(BaseHTTPMiddleware):
    """Return a clear message when a browser or non-streaming client hits /mcp."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            accept_header = request.headers.get("accept", "").lower()
            if "text/event-stream" not in accept_header:
                return JSONResponse(
                    {
                        "error": "Not Acceptable",
                        "message": "This endpoint requires a Streamable HTTP MCP client. Use Accept: text/event-stream and connect to http://127.0.0.1:<port>/mcp.",
                        "hint": "Do not open /mcp in a browser. Use /health for a browser health check.",
                    },
                    status_code=406,
                )

        return await call_next(request)


class McpAuthMiddleware(BaseHTTPMiddleware):
    """Protect /mcp with optional API key and origin checks."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            origin = request.headers.get("origin")
            if not origin_allowed(origin):
                return PlainTextResponse("Origin not allowed.", status_code=403)

            if settings.mcp_api_keys:
                auth_header = request.headers.get("authorization", "")
                token = (
                    auth_header.split(" ", 1)[1]
                    if auth_header.lower().startswith("bearer ")
                    else None
                )
                if not token or token not in settings.mcp_api_keys:
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)

