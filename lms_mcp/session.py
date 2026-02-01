from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


@dataclass
class TokenBundle:
    """Access + refresh token pair for a single MCP session."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None

    def is_expired(self, leeway_seconds: int = 30) -> bool:
        """Return True when access token is expired or about to expire."""
        if not self.expires_at:
            return False
        now = datetime.now(timezone.utc)
        return now >= self.expires_at - timedelta(seconds=leeway_seconds)


class SessionStore:
    """Per-MCP-session token cache (memory only, cleared on restart)."""

    DEFAULT_KEY = "default"

    def __init__(self):
        self._tokens: Dict[str, TokenBundle] = {}

    def set_bundle(self, session_id: str, bundle: TokenBundle) -> None:
        self._tokens[session_id] = bundle

    def get_bundle(self, session_id: str) -> Optional[TokenBundle]:
        return self._tokens.get(session_id)

    def clear_bundle(self, session_id: str) -> None:
        self._tokens.pop(session_id, None)

    # Convenience helpers using a single shared key when no session id is available
    def set_for_current(self, bundle: TokenBundle) -> None:
        self.set_bundle(self.DEFAULT_KEY, bundle)

    def get_for_current(self) -> Optional[TokenBundle]:
        return self.get_bundle(self.DEFAULT_KEY)

    def clear_current(self) -> None:
        self.clear_bundle(self.DEFAULT_KEY)


session_store = SessionStore()
