from __future__ import annotations

import base64
import time
from typing import Any
from urllib.parse import quote

import requests


class DiscordApiError(RuntimeError):
    """Raised when the Discord API returns an error."""


class DiscordApiClient:
    def __init__(self, token: str, api_base_url: str) -> None:
        self._token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._session = requests.Session()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
        absolute_url: str | None = None,
        use_bot_auth: bool = True,
    ) -> Any:
        url = absolute_url or f"{self._api_base_url}{path}"
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "discord-mcp-fastmcp/0.1.0",
        }
        if use_bot_auth:
            request_headers["Authorization"] = f"Bot {self._token}"
        if headers:
            request_headers.update(headers)

        last_error: DiscordApiError | None = None
        for _attempt in range(3):
            response = self._session.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json,
                headers=request_headers,
                timeout=30,
            )
            if response.status_code != 429:
                break
            retry_after = 1.0
            try:
                payload = response.json()
                retry_after = float(payload.get("retry_after", retry_after))
            except Exception:
                pass
            time.sleep(min(max(retry_after, 0.25), 5.0))
        if response.status_code >= 400:
            last_error = self._error_from_response(response)
            raise last_error
        if response.status_code == 204:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        if response.text:
            return response.text
        return None

    def fetch_data_uri(self, url: str) -> str:
        response = self._session.get(
            url,
            headers={"User-Agent": "discord-mcp-fastmcp/0.1.0"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise self._error_from_response(response, prefix="Failed to fetch image URL")
        content_type = response.headers.get("content-type", "image/png").split(";")[0]
        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    @staticmethod
    def audit_headers(reason: str | None) -> dict[str, str]:
        if not reason:
            return {}
        return {"X-Audit-Log-Reason": quote(reason, safe="")}

    @staticmethod
    def _error_from_response(
        response: requests.Response,
        *,
        prefix: str | None = None,
    ) -> DiscordApiError:
        message = f"Discord API error {response.status_code}"
        details: Any = None
        try:
            payload = response.json()
            details = payload
            if isinstance(payload, dict):
                if payload.get("message"):
                    message = str(payload["message"])
                if payload.get("errors"):
                    message = f"{message}: {payload['errors']}"
        except Exception:
            if response.text:
                message = response.text.strip()
        if prefix:
            message = f"{prefix}: {message}"
        if details is not None:
            message = f"{message} ({details})"
        return DiscordApiError(message)
