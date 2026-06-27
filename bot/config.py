from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when the runtime configuration is incomplete or invalid."""


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value.strip()


def _parse_int_env(name: str) -> int:
    raw = _require_env(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer Discord snowflake") from exc


def _parse_role_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()

    role_ids: set[int] = set()
    parts = raw.replace(";", ",").replace(" ", ",").split(",")
    for part in (part.strip() for part in parts):
        if not part:
            continue
        try:
            role_ids.add(int(part))
        except ValueError as exc:
            raise ConfigError(
                "ALLOWED_ROLE_IDS must contain comma-separated Discord role IDs"
            ) from exc
    return role_ids


@dataclass(frozen=True)
class Settings:
    discord_token: str
    statbot_api_key: str
    guild_id: int
    allowed_role_ids: set[int]
    statbot_api_base_url: str
    statbot_auth_header: str
    statbot_request_timeout: float

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        timeout_raw = os.getenv("STATBOT_REQUEST_TIMEOUT", "45")
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise ConfigError("STATBOT_REQUEST_TIMEOUT must be a number") from exc

        return cls(
            discord_token=_require_env("DISCORD_TOKEN"),
            statbot_api_key=_require_env("STATBOT_API_KEY"),
            guild_id=_parse_int_env("GUILD_ID"),
            allowed_role_ids=_parse_role_ids(os.getenv("ALLOWED_ROLE_IDS")),
            statbot_api_base_url=os.getenv(
                "STATBOT_API_BASE_URL", "https://api.statbot.net"
            ).rstrip("/"),
            statbot_auth_header=os.getenv("STATBOT_AUTH_HEADER", "Authorization"),
            statbot_request_timeout=timeout,
        )
