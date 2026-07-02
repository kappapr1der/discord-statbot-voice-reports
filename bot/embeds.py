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
    _set_afk_footer(embed)

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


def build_active_embeds(stats: VoiceStats, *, page_size: int = 20) -> list[discord.Embed]:
    members = stats.top_members
    if not members:
        embed = discord.Embed(
            title="Активные участники в голосе",
            description=(
                f"Период: {stats.display_period}.\n\n"
                "За этот период голосовой активности не найдено."
            ),
            color=WARNING_COLOR,
        )
        _set_afk_footer(embed)
        return [embed]

    pages = [members[index : index + page_size] for index in range(0, len(members), page_size)]
    embeds: list[discord.Embed] = []
    for page_index, page_members in enumerate(pages, start=1):
        title = "Активные участники в голосе"
        if len(pages) > 1:
            title = f"{title} · {page_index}/{len(pages)}"

        embed = discord.Embed(
            title=title,
            description=f"Период: {stats.display_period}.",
            color=BRAND_COLOR,
        )
        _set_afk_footer(embed)
        if page_index == 1:
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
        embed.add_field(
            name="Кто был",
            value=_format_member_rows(page_members),
            inline=False,
        )
        embeds.append(embed)

    return embeds


def build_afk_embeds(stats: VoiceStats, *, page_size: int = 20) -> list[discord.Embed]:
    members = stats.top_members
    if not members:
        embed = discord.Embed(
            title="AFK отдельно",
            description=(
                f"Период: {stats.display_period}.\n\n"
                "За этот период AFK-времени не найдено."
            ),
            color=SUCCESS_COLOR,
        )
        return [embed]

    pages = [members[index : index + page_size] for index in range(0, len(members), page_size)]
    embeds: list[discord.Embed] = []
    for page_index, page_members in enumerate(pages, start=1):
        title = "AFK отдельно"
        if len(pages) > 1:
            title = f"{title} · {page_index}/{len(pages)}"

        embed = discord.Embed(
            title=title,
            description=f"Период: {stats.display_period}.",
            color=WARNING_COLOR,
        )
        if page_index == 1:
            embed.add_field(
                name="Всего AFK",
                value=format_minutes(stats.total_minutes),
                inline=True,
            )
            embed.add_field(
                name="Участников в AFK",
                value=str(stats.active_member_count or len(stats.active_member_ids)),
                inline=True,
            )
        embed.add_field(
            name="Кто был в AFK",
            value=_format_member_rows(page_members),
            inline=False,
        )
        embeds.append(embed)

    return embeds


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
    _set_afk_footer(embed)
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
    afk_stats: VoiceStats | None,
    inactive_members: list[discord.Member],
    total_checked: int,
    top_limit: int = 5,
) -> discord.Embed:
    embed = discord.Embed(
        title="Общий отчёт по голосовой активности",
        description=f"Период: {stats.display_period}.",
        color=BRAND_COLOR,
    )
    _set_afk_footer(embed)
    embed.add_field(
        name="Активного времени",
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

    if afk_stats is not None:
        afk_count = afk_stats.active_member_count or len(afk_stats.active_member_ids)
        embed.add_field(
            name="AFK отдельно",
            value=f"{format_minutes(afk_stats.total_minutes)} · {afk_count} чел.",
            inline=True,
        )

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

    if afk_stats is not None and afk_stats.top_members:
        embed.add_field(
            name=f"AFK топ {min(top_limit, len(afk_stats.top_members))}",
            value=_format_member_rows(afk_stats.top_members[:top_limit]),
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


def _set_afk_footer(embed: discord.Embed) -> None:
    embed.set_footer(text="AFK исключён из активности и считается отдельно.")
