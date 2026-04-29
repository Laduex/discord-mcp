from __future__ import annotations

import os
from dataclasses import dataclass


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


@dataclass(frozen=True)
class Settings:
    token: str
    default_guild_id: str
    host: str
    port: int
    log_level: str
    api_base_url: str

    @property
    def masked_token(self) -> str:
        return _mask(self.token)


def load_settings() -> Settings:
    return Settings(
        token=_require_env("DISCORD_TOKEN"),
        default_guild_id=os.getenv("DISCORD_GUILD_ID", "").strip(),
        host=os.getenv("MCP_HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.getenv("MCP_PORT", "8085")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip() or "INFO",
        api_base_url=(
            os.getenv("DISCORD_API_BASE_URL", "https://discord.com/api/v10").strip()
            or "https://discord.com/api/v10"
        ),
    )
