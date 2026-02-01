import os
from dataclasses import dataclass, field
from typing import List


def _csv_env(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    """Centralised configuration for the MCP server and downstream API."""

    library_api_base_url: str = os.getenv(
        "LIBRARY_API_BASE_URL",
        "https://librarymanagementsystem-be.vercel.app/api",
    ).rstrip("/")
    library_api_access_token: str | None = os.getenv("LIBRARY_API_ACCESS_TOKEN") or None
    mcp_api_keys: List[str] = field(default_factory=lambda: _csv_env("MCP_API_KEYS"))
    allowed_origins: List[str] = field(default_factory=lambda: _csv_env("MCP_ALLOWED_ORIGINS", "*"))
    host: str = os.getenv("MCP_HOST", "0.0.0.0")
    port: int = int(os.getenv("MCP_PORT", "8000"))


settings = Settings()
