from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time

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


def _parse_optional_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer Discord snowflake") from exc


def _parse_bool_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean value")


def _parse_range_env(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _parse_time_env(name: str, *, default: str) -> time:
    raw = (os.getenv(name) or default).strip()
    try:
        hour_raw, minute_raw = raw.split(":", maxsplit=1)
        hour = int(hour_raw)
        minute = int(minute_raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must use HH:MM format") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ConfigError(f"{name} must use HH:MM format")
    return time(hour=hour, minute=minute)


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
    report_channel_id: int | None
    weekly_report_enabled: bool
    weekly_report_days: int
    weekly_report_weekday: int
    weekly_report_time: time
    weekly_report_timezone: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        report_channel_id = _parse_optional_int_env("REPORT_CHANNEL_ID")
        weekly_report_enabled = _parse_bool_env(
            "WEEKLY_REPORT_ENABLED",
            default=report_channel_id is not None,
        )
        if weekly_report_enabled and report_channel_id is None:
            raise ConfigError(
                "REPORT_CHANNEL_ID is required when WEEKLY_REPORT_ENABLED is true"
            )

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
            report_channel_id=report_channel_id,
            weekly_report_enabled=weekly_report_enabled,
            weekly_report_days=_parse_range_env(
                "WEEKLY_REPORT_DAYS",
                default=7,
                minimum=1,
                maximum=365,
            ),
            weekly_report_weekday=_parse_range_env(
                "WEEKLY_REPORT_WEEKDAY",
                default=6,
                minimum=0,
                maximum=6,
            ),
            weekly_report_time=_parse_time_env("WEEKLY_REPORT_TIME", default="12:00"),
            weekly_report_timezone=os.getenv(
                "WEEKLY_REPORT_TIMEZONE",
                "Europe/Moscow",
            ).strip(),
        )
