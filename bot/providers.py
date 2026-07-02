from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import VoiceStats
from .statbot_client import StatbotClient


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
        return await self.client.fetch_voice_stats(
            days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            voice_states=self.active_voice_states,
        )

    async def fetch_afk_stats(
        self,
        days: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        period_label: str | None = None,
    ) -> VoiceStats:
        return await self.client.fetch_voice_stats(
            days,
            start_at=start_at,
            end_at=end_at,
            period_label=period_label,
            voice_states=self.afk_voice_states,
        )
