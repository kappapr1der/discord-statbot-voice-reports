from __future__ import annotations

import discord

from .models import VoiceMember, VoiceStats


BRAND_COLOR = discord.Color.from_rgb(88, 101, 242)
SUCCESS_COLOR = discord.Color.from_rgb(46, 204, 113)
WARNING_COLOR = discord.Color.from_rgb(241, 196, 15)
ERROR_COLOR = discord.Color.from_rgb(231, 76, 60)


def format_minutes(minutes: float) -> str:
    total = max(0, int(round(minutes)))
    hours, mins = divmod(total, 60)
    days, hours = divmod(hours, 24)

    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if mins or not parts:
        parts.append(f"{mins} мин")
    return " ".join(parts)


def build_voice_top_embed(stats: VoiceStats, *, limit: int = 10) -> discord.Embed:
    embed = discord.Embed(
        title="Топ по голосовой активности",
        description=f"Период: {stats.display_period}.",
        color=BRAND_COLOR,
    )

    members = stats.top_members[:limit]
    if not members:
        embed.description += "\n\nЗа этот период голосовой активности не найдено."
        return embed

    embed.add_field(
        name="Участники",
        value=_format_member_rows(members),
        inline=False,
    )
    embed.add_field(
        name="Всего в голосе",
        value=format_minutes(stats.total_minutes),
        inline=True,
    )
    embed.add_field(
        name="Активных участников",
        value=str(stats.active_member_count or len(stats.active_member_ids)),
        inline=True,
    )
    return embed


def build_inactive_embed(
    *,
    days: int,
    inactive_members: list[discord.Member],
    active_count: int,
    total_checked: int,
    period_label: str | None = None,
    limit: int = 25,
) -> discord.Embed:
    color = SUCCESS_COLOR if not inactive_members else WARNING_COLOR
    embed = discord.Embed(
        title="Участники без голосовой активности",
        description=f"Период: {period_label or f'последние {days} дн'}.",
        color=color,
    )
    embed.add_field(name="Проверено участников", value=str(total_checked), inline=True)
    embed.add_field(name="Активных", value=str(active_count), inline=True)
    embed.add_field(name="Неактивных", value=str(len(inactive_members)), inline=True)

    if not inactive_members:
        embed.add_field(
            name="Результат",
            value="Все проверенные участники были активны в голосовых каналах.",
            inline=False,
        )
        return embed

    visible = inactive_members[:limit]
    lines = [f"{index}. {member.mention}" for index, member in enumerate(visible, start=1)]
    if len(inactive_members) > limit:
        lines.append(f"...и ещё {len(inactive_members) - limit}")
    embed.add_field(name="Список", value="\n".join(lines), inline=False)
    return embed


def build_report_embed(
    *,
    stats: VoiceStats,
    inactive_members: list[discord.Member],
    total_checked: int,
    top_limit: int = 5,
) -> discord.Embed:
    embed = discord.Embed(
        title="Общий отчёт по голосовой активности",
        description=f"Период: {stats.display_period}.",
        color=BRAND_COLOR,
    )
    embed.add_field(
        name="Всего времени",
        value=format_minutes(stats.total_minutes),
        inline=True,
    )
    embed.add_field(
        name="Активных",
        value=str(stats.active_member_count or len(stats.active_member_ids)),
        inline=True,
    )
    embed.add_field(name="Неактивных", value=str(len(inactive_members)), inline=True)
    embed.add_field(name="Проверено участников", value=str(total_checked), inline=True)

    if stats.top_members:
        embed.add_field(
            name=f"Топ {min(top_limit, len(stats.top_members))}",
            value=_format_member_rows(stats.top_members[:top_limit]),
            inline=False,
        )
    else:
        embed.add_field(
            name="Топ",
            value="За этот период голосовой активности не найдено.",
            inline=False,
        )

    return embed


def build_error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="Не удалось получить данные",
        description=message,
        color=ERROR_COLOR,
    )


def _format_member_rows(members: list[VoiceMember]) -> str:
    rows = []
    for index, member in enumerate(members, start=1):
        rank = member.rank or index
        display_name = _safe_display_name(member)
        rows.append(
            f"**{rank}.** {display_name} — {format_minutes(member.minutes)}"
        )
    return "\n".join(rows)


def _safe_display_name(member: VoiceMember) -> str:
    display_name = member.display_name.strip() or f"Пользователь {member.user_id}"
    display_name = discord.utils.escape_markdown(display_name)
    return discord.utils.escape_mentions(display_name)
