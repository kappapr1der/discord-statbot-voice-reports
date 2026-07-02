from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
import sqlite3

import discord

from .models import VoiceMember, VoiceStats


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VoicePresence:
    guild_id: int
    user_id: int
    channel_id: int
    channel_name: str
    state: str


class VoiceSessionStore:
    def __init__(self, *, db_path: str, afk_channel_ids: set[int]) -> None:
        self.db_path = Path(db_path)
        self.afk_channel_ids = afk_channel_ids
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
            self._create_schema()
        LOGGER.info("Voice session tracking enabled at %s", self.db_path)

    async def close(self) -> None:
        async with self._lock:
            if self._connection is None:
                return
            self._close_all_open_sync(_utc_now(), reason="bot_shutdown")
            self._connection.close()
            self._connection = None

    async def handle_voice_update(
        self,
        member: discord.Member,
        before_channel: discord.VoiceChannel | discord.StageChannel | None,
        after_channel: discord.VoiceChannel | discord.StageChannel | None,
    ) -> None:
        if member.bot:
            return

        before = self._presence_from_channel(member, before_channel)
        after = self._presence_from_channel(member, after_channel)
        if before == after:
            return

        now = _utc_now()
        async with self._lock:
            if before is not None:
                reason = "moved" if after is not None else "left"
                self._close_open_for_user_sync(before.guild_id, before.user_id, now, reason)
            if after is not None:
                self._open_session_sync(after, now)

    async def reconcile_guild(self, guild: discord.Guild) -> None:
        presences = self._current_guild_presences(guild)
        now = _utc_now()

        async with self._lock:
            self._close_all_open_sync(now, reason="bot_startup_reconcile")
            for presence in presences:
                self._open_session_sync(presence, now, close_existing=False)

        LOGGER.info(
            "Voice session tracker reconciled %s current voice sessions for guild %s",
            len(presences),
            guild.id,
        )

    async def fetch_stats(
        self,
        *,
        guild_id: int,
        state: str,
        days: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
        source_label: str | None = None,
    ) -> VoiceStats:
        start_at, end_at = _resolve_period(days, start_at=start_at, end_at=end_at)
        now = _utc_now()

        async with self._lock:
            rows = self._conn().execute(
                """
                SELECT user_id, started_at, ended_at
                FROM voice_sessions
                WHERE guild_id = ?
                  AND state = ?
                  AND started_at < ?
                  AND COALESCE(ended_at, ?) > ?
                """,
                (
                    guild_id,
                    state,
                    _format_time(end_at),
                    _format_time(now),
                    _format_time(start_at),
                ),
            ).fetchall()

        minutes_by_user: dict[int, float] = {}
        for row in rows:
            session_start = _parse_time(row["started_at"])
            raw_end = row["ended_at"]
            session_end = _parse_time(raw_end) if raw_end else now
            overlap_start = max(session_start, start_at)
            overlap_end = min(session_end, end_at, now)
            duration_seconds = max(0, int((overlap_end - overlap_start).total_seconds()))
            if duration_seconds <= 0:
                continue
            user_id = int(row["user_id"])
            minutes_by_user[user_id] = minutes_by_user.get(user_id, 0) + duration_seconds / 60

        members = [
            VoiceMember(
                user_id=user_id,
                display_name=f"User {user_id}",
                minutes=minutes,
                rank=index,
            )
            for index, (user_id, minutes) in enumerate(
                sorted(minutes_by_user.items(), key=lambda item: item[1], reverse=True),
                start=1,
            )
        ]

        return VoiceStats(
            days=days,
            period_label=period_label,
            source_label=source_label,
            total_minutes=sum(minutes_by_user.values()),
            active_member_count=len(members),
            top_members=members,
        )

    def _presence_from_channel(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel | discord.StageChannel | None,
    ) -> VoicePresence | None:
        if channel is None:
            return None

        return VoicePresence(
            guild_id=member.guild.id,
            user_id=member.id,
            channel_id=channel.id,
            channel_name=channel.name,
            state=self._channel_state(member.guild, channel),
        )

    def _current_guild_presences(self, guild: discord.Guild) -> list[VoicePresence]:
        presences: list[VoicePresence] = []
        channels = [*guild.voice_channels, *guild.stage_channels]
        for channel in channels:
            for member in channel.members:
                if member.bot:
                    continue
                presences.append(
                    VoicePresence(
                        guild_id=guild.id,
                        user_id=member.id,
                        channel_id=channel.id,
                        channel_name=channel.name,
                        state=self._channel_state(guild, channel),
                    )
                )
        return presences

    def _channel_state(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel | discord.StageChannel,
    ) -> str:
        guild_afk_channel = guild.afk_channel
        if guild_afk_channel is not None and channel.id == guild_afk_channel.id:
            return "afk"
        if channel.id in self.afk_channel_ids:
            return "afk"
        return "active"

    def _create_schema(self) -> None:
        connection = self._conn()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS voice_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('active', 'afk')),
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds INTEGER,
                ended_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_voice_sessions_open
                ON voice_sessions (guild_id, user_id, ended_at);

            CREATE INDEX IF NOT EXISTS idx_voice_sessions_period
                ON voice_sessions (guild_id, started_at, ended_at, state);
            """
        )
        connection.commit()

    def _open_session_sync(
        self,
        presence: VoicePresence,
        now: datetime,
        *,
        close_existing: bool = True,
    ) -> None:
        connection = self._conn()
        if close_existing:
            self._close_open_for_user_sync(
                presence.guild_id,
                presence.user_id,
                now,
                reason="reopened",
            )
        connection.execute(
            """
            INSERT INTO voice_sessions (
                guild_id,
                user_id,
                channel_id,
                channel_name,
                state,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                presence.guild_id,
                presence.user_id,
                presence.channel_id,
                presence.channel_name,
                presence.state,
                _format_time(now),
            ),
        )
        connection.commit()

    def _close_open_for_user_sync(
        self,
        guild_id: int,
        user_id: int,
        now: datetime,
        reason: str,
    ) -> None:
        rows = self._conn().execute(
            """
            SELECT id, started_at
            FROM voice_sessions
            WHERE guild_id = ? AND user_id = ? AND ended_at IS NULL
            """,
            (guild_id, user_id),
        ).fetchall()
        for row in rows:
            self._close_session_sync(row["id"], row["started_at"], now, reason)

    def _close_all_open_sync(self, now: datetime, *, reason: str) -> None:
        rows = self._conn().execute(
            """
            SELECT id, started_at
            FROM voice_sessions
            WHERE ended_at IS NULL
            """
        ).fetchall()
        for row in rows:
            self._close_session_sync(row["id"], row["started_at"], now, reason)

    def _close_session_sync(
        self,
        session_id: int,
        started_at_raw: str,
        now: datetime,
        reason: str,
    ) -> None:
        started_at = _parse_time(started_at_raw)
        duration = max(0, int((now - started_at).total_seconds()))
        self._conn().execute(
            """
            UPDATE voice_sessions
            SET ended_at = ?, duration_seconds = ?, ended_reason = ?
            WHERE id = ? AND ended_at IS NULL
            """,
            (_format_time(now), duration, reason, session_id),
        )
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("VoiceSessionStore is not started")
        return self._connection


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _resolve_period(
    days: int,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    if start_at is None:
        start_at = _utc_now() - timedelta(days=days)
        start_at = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    if end_at is None:
        end_at = _utc_now()
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=UTC)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=UTC)
    return start_at.astimezone(UTC), end_at.astimezone(UTC)
