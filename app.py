"""Entry point for the Library Management System MCP server."""

import uvicorn

from lms_mcp.server import build_app
from lms_mcp.config import settings

app = build_app(settings)


if __name__ == "__main__":
    uvicorn.run("app:app", host=settings.host, port=settings.port, reload=False)
