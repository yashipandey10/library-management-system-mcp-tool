import mimetypes
import os
from typing import Any, Dict, Optional, Tuple

import httpx


class HttpClient:
    """Thin wrapper around httpx for talking to the Library API."""

    def __init__(self, base_url: str, default_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.default_token = default_token

    def _auth_header(self, token: Optional[str]) -> Dict[str, str]:
        bearer = token or self.default_token
        return {"Authorization": f"Bearer {bearer}"} if bearer else {}

    async def _handle(self, response: httpx.Response) -> Dict[str, Any]:
        if response.is_success:
            return response.json()
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("error") or payload
        except Exception:
            message = response.text
        raise RuntimeError(f"Library API error ({response.status_code}): {message}")

    async def request(
        self,
        method: str,
        path: str,
        *,
        access_token: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        capture_response: bool = False,
    ) -> Dict[str, Any] | Tuple[Dict[str, Any], httpx.Response]:
        """
        Make an HTTP request to the Library API.

        When capture_response=True, returns (json, httpx.Response) so callers can read cookies.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = self._auth_header(access_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                files=files,
                headers=headers,
                cookies=cookies,
            )
        payload = await self._handle(response)
        if capture_response:
            return payload, response
        return payload

    @staticmethod
    def file_payload(file_path: str):
        """Return (filename, bytes, mime) tuple suitable for httpx files=."""
        with open(file_path, "rb") as fh:
            data = fh.read()
        filename = os.path.basename(file_path)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return (filename, data, mime_type)
