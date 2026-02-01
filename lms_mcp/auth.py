import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .http_client import HttpClient
from .session import SessionStore, TokenBundle


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Best-effort conversion of API expiry values to aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _exp_from_jwt(token: str) -> Optional[datetime]:
    """Extract exp from JWT without verifying signature (used only for local expiry checks)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception:
        return None
    return None


class AuthManager:
    """Handles login + refresh flows and per-session token caching."""

    def __init__(self, client: HttpClient, store: SessionStore, session_key: str = SessionStore.DEFAULT_KEY):
        self.client = client
        self.store = store
        self.session_key = session_key

    def _bundle_from_payload(
        self,
        payload: Dict[str, Any],
        response_cookies,
        fallback_refresh: Optional[str] = None,
    ) -> TokenBundle:
        data = payload.get("data") if isinstance(payload, dict) else payload
        data = data or {}

        access_token = data.get("accessToken") or data.get("access_token")
        refresh_token = (
            data.get("refreshToken")
            or data.get("refresh_token")
            or (response_cookies.get("refreshToken") if response_cookies else None)
            or fallback_refresh
        )

        expires_at = _parse_datetime(data.get("expiresAt") or data.get("expires_at"))
        if not expires_at and access_token:
            expires_at = _exp_from_jwt(access_token)

        if not access_token:
            raise RuntimeError("Library API login failed: access token missing in response.")

        return TokenBundle(access_token=access_token, refresh_token=refresh_token, expires_at=expires_at)

    async def login(self, email: str, password: str) -> TokenBundle:
        """Authenticate with email/password and cache tokens for the current MCP session."""
        payload, response = await self.client.request(
            "POST",
            "auth/login",
            json_body={"email": email, "password": password},
            capture_response=True,
        )
        bundle = self._bundle_from_payload(payload, response.cookies)
        self.store.set_bundle(self.session_key, bundle)
        return bundle

    async def refresh(self, bundle: Optional[TokenBundle] = None) -> TokenBundle:
        """Refresh the access token using the cached refresh token."""
        session_id = self.session_key
        active_bundle = bundle or self.store.get_bundle(session_id)
        if not active_bundle:
            raise RuntimeError("No cached session. Please run the login tool first.")
        if not active_bundle.refresh_token:
            raise RuntimeError("No refresh token cached. Please login again.")

        payload, response = await self.client.request(
            "POST",
            "auth/refresh-token",
            cookies={"refreshToken": active_bundle.refresh_token},
            capture_response=True,
        )
        new_bundle = self._bundle_from_payload(
            payload,
            response.cookies,
            fallback_refresh=active_bundle.refresh_token,
        )
        self.store.set_bundle(session_id, new_bundle)
        return new_bundle

    async def ensure_valid_bundle(self) -> Optional[TokenBundle]:
        """Return a fresh token bundle for the current session, refreshing if needed."""
        bundle = self.store.get_bundle(self.session_key)
        if not bundle:
            return None
        if bundle.refresh_token and bundle.is_expired():
            bundle = await self.refresh(bundle)
        return bundle

    async def access_token_for_call(self, provided: Optional[str]) -> Tuple[Optional[str], Optional[TokenBundle]]:
        """
        Decide which token to use for an API call.
        Returns (token_to_use, bundle_used_for_refreshes)
        """
        if provided:
            return provided, None
        bundle = await self.ensure_valid_bundle()
        token = bundle.access_token if bundle else None
        return token, bundle

    async def refresh_after_unauthorized(self, bundle: Optional[TokenBundle]) -> Optional[TokenBundle]:
        """Attempt a refresh after a 401 response; clears cache on failure."""
        if not bundle or not bundle.refresh_token:
            return None
        try:
            return await self.refresh(bundle)
        except Exception as exc:  # pragma: no cover - defensive clear
            self.store.clear_bundle(self.session_key)
            raise RuntimeError("Authorization failed and refresh could not be completed; please login again.") from exc
