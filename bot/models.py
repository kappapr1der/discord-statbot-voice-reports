from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class VoiceMember:
    user_id: int
    display_name: str
    minutes: float
    rank: int | None = None


@dataclass(slots=True)
class VoiceStats:
    days: int
    total_minutes: float = 0
    active_member_count: int = 0
    total_member_count: int = 0
    top_members: list[VoiceMember] = field(default_factory=list)

    @property
    def has_activity(self) -> bool:
        return self.total_minutes > 0 or bool(self.top_members)

    @property
    def active_member_ids(self) -> set[int]:
        return {member.user_id for member in self.top_members if member.minutes > 0}
