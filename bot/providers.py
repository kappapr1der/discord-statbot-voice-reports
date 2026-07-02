from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time
from typing import Awaitable, Callable, Protocol

from .models import VoiceStats
from .statbot_client import StatbotClient, StatbotError
from .voice_session_store import VoiceSessionStore


LOGGER = logging.getLogger(__name__)
SourceAlertCallback = Callable[[str], Awaitable[None]]


class VoiceStatsProvider(Protocol):
    async def close(self) -> None:
        """Release provider resources."""

    async def fetch_activity_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        """Fetch voice activity that counts toward active time."""

    async def fetch_afk_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        """Fetch AFK voice time separately from active time."""


class StatbotVoiceStatsProvider:
    def __init__(
        self,
        *,
        client: StatbotClient,
        active_voice_states: tuple[str, ...],
        afk_voice_states: tuple[str, ...],
    ) -> None:
        self.client = client
        self.active_voice_states = active_voice_states
        self.afk_voice_states = afk_voice_states

    async def close(self) -> None:
        await self.client.close()

    async def fetch_activity_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        stats = await self.client.fetch_voice_stats(
            days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            voice_states=self.active_voice_states,
        )
        stats.source_label = "Statbot"
        return stats

    async def fetch_afk_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        stats = await self.client.fetch_voice_stats(
            days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            voice_states=self.afk_voice_states,
        )
        stats.source_label = "Statbot"
        return stats


class LocalVoiceStatsProvider:
    def __init__(
        self,
        *,
        store: VoiceSessionStore,
        guild_id: int,
        source_label: str = "локальная база",
    ) -> None:
        self.store = store
        self.guild_id = guild_id
        self.source_label = source_label

    async def close(self) -> None:
        return None

    async def fetch_activity_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
        source_label: str | None = None,
    ) -> VoiceStats:
        return await self.store.fetch_stats(
            guild_id=self.guild_id,
            state="active",
            days=days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            source_label=source_label or self.source_label,
        )

    async def fetch_afk_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
        source_label: str | None = None,
    ) -> VoiceStats:
        return await self.store.fetch_stats(
            guild_id=self.guild_id,
            state="afk",
            days=days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            source_label=source_label or self.source_label,
        )


class AutoVoiceStatsProvider:
    def __init__(
        self,
        *,
        statbot: StatbotVoiceStatsProvider,
        local: LocalVoiceStatsProvider,
        failure_threshold: int,
        recovery_check_seconds: int,
        on_degraded: SourceAlertCallback | None = None,
        on_recovered: SourceAlertCallback | None = None,
    ) -> None:
        self.statbot = statbot
        self.local = local
        self.failure_threshold = failure_threshold
        self.recovery_check_seconds = recovery_check_seconds
        self.on_degraded = on_degraded
        self.on_recovered = on_recovered
        self._lock = asyncio.Lock()
        self._failure_count = 0
        self._using_local = False
        self._degraded_alert_sent = False
        self._last_failure_at = 0.0

    async def close(self) -> None:
        await self.statbot.close()

    async def fetch_activity_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        return await self._fetch(
            kind="activity",
            statbot_fetch=self.statbot.fetch_activity_stats,
            local_fetch=self.local.fetch_activity_stats,
            days=days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
        )

    async def fetch_afk_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        return await self._fetch(
            kind="afk",
            statbot_fetch=self.statbot.fetch_afk_stats,
            local_fetch=self.local.fetch_afk_stats,
            days=days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
        )

    async def _fetch(
        self,
        *,
        kind: str,
        statbot_fetch,
        local_fetch,
        days: int,
        start_at: datetime | None,
        end_at: datetime | None,
        period_label: str | None,
    ) -> VoiceStats:
        if await self._should_use_local_without_probe():
            return await self._fetch_local(
                local_fetch,
                days=days,
                start_at=start_at,
                end_at=end_at,
                period_label=period_label,
                source_label="локальная база (Statbot недоступен)",
            )

        try:
            stats = await statbot_fetch(
                days,
                start_at=start_at,
                end_at=end_at,
                period_label=period_label,
            )
        except StatbotError as exc:
            LOGGER.warning("Statbot %s fetch failed, using local fallback: %s", kind, exc)
            source_label = await self._record_failure(exc)
            return await self._fetch_local(
                local_fetch,
                days=days,
                start_at=start_at,
                end_at=end_at,
                period_label=period_label,
                source_label=source_label,
            )

        await self._record_success()
        return stats

    async def _fetch_local(
        self,
        local_fetch,
        *,
        days: int,
        start_at: datetime | None,
        end_at: datetime | None,
        period_label: str | None,
        source_label: str,
    ) -> VoiceStats:
        return await local_fetch(
            days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            source_label=source_label,
        )

    async def _should_use_local_without_probe(self) -> bool:
        async with self._lock:
            if not self._using_local:
                return False
            return (time.monotonic() - self._last_failure_at) < self.recovery_check_seconds

    async def _record_failure(self, error: StatbotError) -> str:
        notify_message: str | None = None
        async with self._lock:
            self._failure_count += 1
            self._last_failure_at = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._using_local = True
                source_label = "локальная база (Statbot недоступен)"
                if not self._degraded_alert_sent:
                    self._degraded_alert_sent = True
                    notify_message = (
                        "Statbot API не отвечает стабильно, временно считаю голосовые "
                        "отчёты из локальной SQLite-базы."
                    )
            else:
                source_label = "локальная база (резерв после ошибки Statbot)"

        if notify_message and self.on_degraded:
            await self.on_degraded(notify_message)
        return source_label

    async def _record_success(self) -> None:
        notify_message: str | None = None
        async with self._lock:
            was_degraded = self._using_local or self._degraded_alert_sent
            self._failure_count = 0
            self._using_local = False
            self._last_failure_at = 0.0
            if was_degraded:
                self._degraded_alert_sent = False
                notify_message = "Statbot API снова отвечает, возвращаю отчёты на Statbot."

        if notify_message and self.on_recovered:
            await self.on_recovered(notify_message)
