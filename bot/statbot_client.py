from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

import aiohttp

from .models import VoiceMember, VoiceStats


class StatbotError(RuntimeError):
    """Base class for Statbot API failures."""


class StatbotHTTPError(StatbotError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Statbot API returned HTTP {status}: {body[:500]}")


class StatbotEmptyDataError(StatbotError):
    """Raised when Statbot returns no parseable voice data."""


class StatbotClient:
    def __init__(
        self,
        *,
        api_key: str,
        guild_id: int,
        base_url: str,
        auth_header: str = "Authorization",
        timeout: float = 45,
    ) -> None:
        self.guild_id = guild_id
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        self.headers = self._build_headers(api_key)

    async def close(self) -> None:
        await self.session.close()

    async def fetch_voice_stats(self, days: int) -> VoiceStats:
        query = self._build_voice_query(days)
        url = f"{self.base_url}/guilds/{self.guild_id}/voice"

        try:
            async with self.session.post(
                url,
                json={"query": query},
                headers=self.headers,
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise StatbotHTTPError(response.status, body)
        except asyncio.TimeoutError as exc:
            raise StatbotError("Statbot API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise StatbotError(f"Could not reach Statbot API: {exc}") from exc

        stats = self._parse_response(body, days)
        if not stats.has_activity:
            return stats

        stats.top_members.sort(key=lambda item: item.minutes, reverse=True)
        for index, member in enumerate(stats.top_members, start=1):
            member.rank = index
        if not stats.total_minutes:
            stats.total_minutes = sum(member.minutes for member in stats.top_members)
        if not stats.active_member_count:
            stats.active_member_count = len(stats.active_member_ids)
        return stats

    def _build_headers(self, api_key: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "discord-statbot-voice-report/1.0",
        }

        if self.auth_header.lower() == "authorization":
            value = api_key
            if not value.lower().startswith(("bearer ", "token ")):
                value = f"Bearer {value}"
            headers[self.auth_header] = value
        else:
            headers[self.auth_header] = api_key

        return headers

    @staticmethod
    def _build_voice_query(days: int) -> dict[str, Any]:
        start = datetime.now(UTC) - timedelta(days=days)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ms = int(start.timestamp() * 1000)

        return {
            "type": "query",
            "start": start_ms,
            "interval": "day",
            "timezone_offset": 0,
            "stats": ["voice"],
            "voice_states": [
                "normal",
                "afk",
                "self_deaf",
                "self_mute",
                "server_deaf",
                "server_mute",
            ],
        }

    def _parse_response(self, body: str, days: int) -> VoiceStats:
        stats = VoiceStats(days=days)
        parsed_any = False

        for event in self._iter_events(body):
            parsed_any = True
            self._apply_event(stats, event)

        if not parsed_any:
            raise StatbotEmptyDataError("Statbot API returned an empty response")

        return stats

    def _iter_events(self, body: str) -> Iterable[Any]:
        body = body.strip()
        if not body:
            return []

        try:
            parsed = json.loads(body)
            return self._flatten_json_events(parsed)
        except json.JSONDecodeError:
            pass

        events: list[Any] = []
        for raw_event in body.split("\n\n"):
            data_lines = []
            for line in raw_event.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
            if not data_lines:
                continue
            data = "\n".join(data_lines)
            if data == "[DONE]":
                continue
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                continue

        if events:
            return events

        ndjson_events: list[Any] = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ndjson_events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return ndjson_events

    def _flatten_json_events(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        if "type" in payload and "payload" in payload:
            return [payload]

        for key in ("events", "messages", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return [value]

        wrapped_payload = payload.get("payload")
        if isinstance(wrapped_payload, dict):
            return [wrapped_payload]

        return [payload]

    def _apply_event(self, stats: VoiceStats, event: Any) -> None:
        if isinstance(event, list):
            self._merge_members(stats, event)
            return
        if not isinstance(event, dict):
            return

        event_type = event.get("type")
        payload = event.get("payload", event)

        if event_type == "data":
            self._merge_summary(stats, payload)
        elif event_type == "top_members_chunk":
            self._merge_members(stats, payload or [])
        elif event_type in {"top_members", "members"}:
            self._merge_members(stats, payload or [])
        elif event_type is None:
            self._merge_direct_payload(stats, event)

    def _merge_direct_payload(self, stats: VoiceStats, payload: dict[str, Any]) -> None:
        self._merge_summary(stats, payload)
        for key in ("topMembers", "top_members", "members", "users", "results"):
            members = payload.get(key)
            if isinstance(members, list):
                self._merge_members(stats, members)
        for key in ("data", "payload"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                self._merge_direct_payload(stats, nested)

    def _merge_summary(self, stats: VoiceStats, payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        total = self._read_number(
            payload,
            "total",
            "totalVoice",
            "total_voice",
            "totalMinutes",
            "total_minutes",
        )
        if total is not None:
            stats.total_minutes = max(stats.total_minutes, total)

        total_seconds = self._read_number(payload, "totalSeconds", "total_seconds")
        if total_seconds is not None:
            stats.total_minutes = max(stats.total_minutes, total_seconds / 60)

        active = self._read_number(
            payload,
            "uniqueMembers",
            "unique_members",
            "activeMembers",
            "active_members",
        )
        if active is not None:
            stats.active_member_count = int(active)

        total_members = self._read_number(
            payload,
            "totalMembers",
            "total_members",
            "memberCount",
            "member_count",
        )
        if total_members is not None:
            stats.total_member_count = int(total_members)

    def _merge_members(self, stats: VoiceStats, members: Any) -> None:
        if not isinstance(members, list):
            return

        existing = {member.user_id: member for member in stats.top_members}
        for raw in members:
            member = self._parse_member(raw)
            if not member:
                continue
            current = existing.get(member.user_id)
            if current is None or member.minutes > current.minutes:
                existing[member.user_id] = member

        stats.top_members = list(existing.values())

    def _parse_member(self, raw: Any) -> VoiceMember | None:
        if not isinstance(raw, dict):
            return None

        nested_user = raw.get("user") or raw.get("member")
        if isinstance(nested_user, dict):
            raw = {**nested_user, **raw}

        user_id_raw = self._read_value(
            raw,
            "id",
            "user_id",
            "userId",
            "member_id",
            "memberId",
            "discord_id",
            "discordId",
            "source_id",
        )
        if user_id_raw is None:
            return None

        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return None

        minutes = self._read_number(
            raw,
            "count",
            "minutes",
            "voice",
            "total",
            "duration",
            "value",
        )
        seconds = self._read_number(raw, "seconds", "totalSeconds", "duration_seconds")
        if seconds is not None:
            minutes = seconds / 60
        if minutes is None:
            minutes = 0

        display_name = str(
            self._read_value(
                raw,
                "display_name",
                "displayName",
                "name",
                "username",
                "label",
            )
            or f"User {user_id}"
        )

        rank_raw = self._read_value(raw, "rank")
        rank = int(rank_raw) if str(rank_raw or "").isdigit() else None
        return VoiceMember(
            user_id=user_id,
            display_name=display_name,
            minutes=float(minutes),
            rank=rank,
        )

    @staticmethod
    def _read_value(payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return None

    @classmethod
    def _read_number(cls, payload: dict[str, Any], *keys: str) -> float | None:
        value = cls._read_value(payload, *keys)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
