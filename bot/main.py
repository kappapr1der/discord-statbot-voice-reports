from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from .config import ConfigError, Settings
from .embeds import (
    build_afk_embeds,
    build_active_embeds,
    build_error_embed,
    build_inactive_embed,
    build_report_embed,
    build_voice_top_embed,
)
from .providers import StatbotVoiceStatsProvider, VoiceStatsProvider
from .statbot_client import (
    StatbotClient,
    StatbotEmptyDataError,
    StatbotError,
    StatbotHTTPError,
)
from .voice_session_store import VoiceSessionStore


LOGGER = logging.getLogger(__name__)
ALLOWED_ROLE_NAMES = {"officer", "admin"}


class PeriodInputError(ValueError):
    """Raised when a slash command receives an invalid date period."""


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    days: int
    label: str
    start_at: datetime | None = None
    end_at: datetime | None = None


class VoiceStatsBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True

        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.voice_stats: VoiceStatsProvider | None = None
        self.voice_sessions: VoiceSessionStore | None = None
        self.weekly_report_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        statbot_client = StatbotClient(
            api_key=self.settings.statbot_api_key,
            guild_id=self.settings.guild_id,
            base_url=self.settings.statbot_api_base_url,
            auth_header=self.settings.statbot_auth_header,
            timeout=self.settings.statbot_request_timeout,
        )
        self.voice_stats = StatbotVoiceStatsProvider(
            client=statbot_client,
            active_voice_states=self.settings.statbot_active_voice_states,
            afk_voice_states=self.settings.statbot_afk_voice_states,
        )

        if self.settings.voice_session_tracking_enabled:
            self.voice_sessions = VoiceSessionStore(
                db_path=self.settings.voice_activity_db_path,
                afk_channel_ids=self.settings.afk_channel_ids,
            )
            await self.voice_sessions.start()

        guild = discord.Object(id=self.settings.guild_id)
        self.tree.add_command(voice_top, guild=guild)
        self.tree.add_command(active, guild=guild)
        self.tree.add_command(afk, guild=guild)
        self.tree.add_command(inactive, guild=guild)
        self.tree.add_command(report, guild=guild)
        self.tree.add_command(test_report, guild=guild)
        synced = await self.tree.sync(guild=guild)
        LOGGER.info("Synced %s slash commands for guild %s", len(synced), guild.id)
        if self.settings.weekly_report_enabled:
            self.weekly_report_task = asyncio.create_task(self._weekly_report_loop())

    async def close(self) -> None:
        if self.weekly_report_task:
            self.weekly_report_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.weekly_report_task
        if self.voice_stats:
            await self.voice_stats.close()
        if self.voice_sessions:
            await self.voice_sessions.close()
        await super().close()

    async def on_ready(self) -> None:
        LOGGER.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        if self.voice_sessions is None:
            return

        guild = self.get_guild(self.settings.guild_id)
        if guild is None:
            with suppress(discord.HTTPException):
                guild = await self.fetch_guild(self.settings.guild_id)
        if isinstance(guild, discord.Guild):
            await self.voice_sessions.reconcile_guild(guild)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if self.voice_sessions is None:
            return
        await self.voice_sessions.handle_voice_update(member, before.channel, after.channel)

    async def _weekly_report_loop(self) -> None:
        await self.wait_until_ready()

        while not self.is_closed():
            try:
                next_run = self._next_weekly_report_at()
                delay = max(1, (next_run - self._schedule_now()).total_seconds())
                LOGGER.info("Next weekly report scheduled at %s", next_run.isoformat())
                await asyncio.sleep(delay)
                await self.send_weekly_report()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Weekly report task failed")
                await asyncio.sleep(300)

    def report_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.settings.weekly_report_timezone)
        except ZoneInfoNotFoundError:
            LOGGER.warning(
                "Unknown WEEKLY_REPORT_TIMEZONE=%s, falling back to UTC",
                self.settings.weekly_report_timezone,
            )
            return ZoneInfo("UTC")

    def _schedule_now(self) -> datetime:
        return datetime.now(self.report_timezone())

    def _next_weekly_report_at(self) -> datetime:
        now = self._schedule_now()
        target_time = self.settings.weekly_report_time
        days_until = (self.settings.weekly_report_weekday - now.weekday()) % 7
        target = (now + timedelta(days=days_until)).replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=7)
        return target

    async def send_weekly_report(self) -> None:
        channel = await self.resolve_report_channel()
        if channel is None:
            LOGGER.warning("Weekly report skipped: REPORT_CHANNEL_ID is not configured")
            return

        guild = self.get_guild(self.settings.guild_id)
        if guild is None:
            guild = await self.fetch_guild(self.settings.guild_id)

        embed = await build_guild_report_embed(
            self,
            guild,
            period=_rolling_period(self.settings.weekly_report_days),
            title="Еженедельный отчёт по голосовой активности",
            top_limit=10,
        )
        await channel.send(embed=embed)
        LOGGER.info("Weekly report sent to channel %s", channel.id)

    async def resolve_report_channel(
        self,
    ) -> discord.TextChannel | discord.Thread | None:
        channel_id = self.settings.report_channel_id
        if channel_id is None:
            return None

        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel

        LOGGER.warning("REPORT_CHANNEL_ID=%s is not a text channel", channel_id)
        return None


def _get_bot(interaction: discord.Interaction) -> VoiceStatsBot:
    if not isinstance(interaction.client, VoiceStatsBot):
        raise RuntimeError("Unexpected Discord client type")
    return interaction.client


async def _has_allowed_role(interaction: discord.Interaction) -> bool:
    bot = _get_bot(interaction)
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False

    for role in member.roles:
        if role.id in bot.settings.allowed_role_ids:
            return True
        if role.name.casefold() in ALLOWED_ROLE_NAMES:
            return True
    return False


def _role_check() -> app_commands.Check:
    async def predicate(interaction: discord.Interaction) -> bool:
        allowed = await _has_allowed_role(interaction)
        if not allowed:
            raise app_commands.CheckFailure("missing officer/admin role")
        return True

    return app_commands.check(predicate)


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    embed = build_error_embed(message)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def _send_embed_pages(
    interaction: discord.Interaction,
    embeds: list[discord.Embed],
) -> None:
    for index in range(0, len(embeds), 10):
        await interaction.followup.send(embeds=embeds[index : index + 10])


async def _fetch_guild_members(guild: discord.Guild | None) -> list[discord.Member]:
    if guild is None:
        return []

    members: list[discord.Member] = []
    async for member in guild.fetch_members(limit=None):
        if not member.bot:
            members.append(member)
    return members


async def _inactive_members(
    interaction: discord.Interaction,
    active_member_ids: set[int],
) -> list[discord.Member]:
    members = await _fetch_guild_members(interaction.guild)
    return [member for member in members if member.id not in active_member_ids]


async def _hydrate_top_member_names(
    bot: VoiceStatsBot,
    guild: discord.Guild | None,
    stats,
    *,
    members: list[discord.Member] | None = None,
) -> None:
    members_by_id = {member.id: member for member in members or []}

    for voice_member in stats.top_members:
        member = members_by_id.get(voice_member.user_id)
        if member is None and guild is not None:
            member = guild.get_member(voice_member.user_id)
        if member is None and guild is not None:
            with suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = await guild.fetch_member(voice_member.user_id)

        if member is not None:
            voice_member.display_name = member.display_name
            continue

        user = bot.get_user(voice_member.user_id)
        if user is None:
            with suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                user = await bot.fetch_user(voice_member.user_id)
        if user is not None:
            voice_member.display_name = user.global_name or user.name


def _rolling_period(days: int) -> ReportPeriod:
    return ReportPeriod(days=days, label=f"последние {days} дн")


def _parse_date(raw: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise PeriodInputError(
            f"`{field_name}` должен быть датой в формате `YYYY-MM-DD`."
        ) from exc


def _command_period(
    bot: VoiceStatsBot,
    *,
    days: int,
    start_date: str | None,
    end_date: str | None,
) -> ReportPeriod:
    if not start_date and not end_date:
        return _rolling_period(days)

    if not start_date:
        raise PeriodInputError(
            "Для периода по датам укажи `start_date` в формате `YYYY-MM-DD`."
        )

    start = _parse_date(start_date, field_name="start_date")
    end = _parse_date(end_date, field_name="end_date") if end_date else start
    if end < start:
        raise PeriodInputError("`end_date` не может быть раньше `start_date`.")

    period_days = (end - start).days + 1
    if period_days > 365:
        raise PeriodInputError("Период по датам не должен быть длиннее 365 дней.")

    timezone = bot.report_timezone()
    start_at = datetime.combine(start, datetime_time.min, tzinfo=timezone)
    end_at = datetime.combine(end + timedelta(days=1), datetime_time.min, tzinfo=timezone)
    label = start.isoformat() if start == end else f"{start.isoformat()} - {end.isoformat()}"
    return ReportPeriod(
        days=period_days,
        label=label,
        start_at=start_at,
        end_at=end_at,
    )


def _voice_stats_provider(bot: VoiceStatsBot) -> VoiceStatsProvider:
    if bot.voice_stats is None:
        raise RuntimeError("Voice stats provider is not initialized")
    return bot.voice_stats


async def _fetch_activity_stats(bot: VoiceStatsBot, period: ReportPeriod):
    return await _voice_stats_provider(bot).fetch_activity_stats(
        period.days,
        start_at=period.start_at,
        end_at=period.end_at,
        period_label=period.label,
    )


async def _fetch_afk_stats(bot: VoiceStatsBot, period: ReportPeriod):
    return await _voice_stats_provider(bot).fetch_afk_stats(
        period.days,
        start_at=period.start_at,
        end_at=period.end_at,
        period_label=period.label,
    )


async def build_guild_report_embed(
    bot: VoiceStatsBot,
    guild: discord.Guild | None,
    *,
    period: ReportPeriod,
    title: str | None = None,
    top_limit: int = 5,
) -> discord.Embed:
    stats, afk_stats = await asyncio.gather(
        _fetch_activity_stats(bot, period),
        _fetch_afk_stats(bot, period),
    )
    members = await _fetch_guild_members(guild)
    await _hydrate_top_member_names(bot, guild, stats, members=members)
    await _hydrate_top_member_names(bot, guild, afk_stats, members=members)
    inactive_list = [member for member in members if member.id not in stats.active_member_ids]
    embed = build_report_embed(
        stats=stats,
        afk_stats=afk_stats,
        inactive_members=inactive_list,
        total_checked=len(members),
        top_limit=top_limit,
    )
    if title is not None:
        embed.title = title
    return embed


def _statbot_error_message(error: StatbotError) -> str:
    if isinstance(error, StatbotHTTPError):
        if error.status in {401, 403}:
            return (
                "Statbot отклонил запрос. Проверь `STATBOT_API_KEY`, права ключа "
                "и `GUILD_ID`."
            )
        if error.status == 404:
            return "Statbot не нашёл сервер или endpoint. Проверь `GUILD_ID` и базовый URL API."
        if error.status == 429:
            return "Statbot временно ограничил запросы. Попробуй ещё раз чуть позже."
        return f"Statbot вернул HTTP {error.status}. Подробности есть в логах контейнера/процесса."

    if isinstance(error, StatbotEmptyDataError):
        return "Statbot вернул пустой ответ без данных голосовой активности."

    return str(error)


@app_commands.command(
    name="voice_top",
    description="Показывает топ участников по времени в голосовых каналах.",
)
@app_commands.describe(
    days="Период отчёта в днях, если даты не указаны",
    start_date="Начало периода в формате YYYY-MM-DD",
    end_date="Конец периода в формате YYYY-MM-DD включительно",
)
@_role_check()
async def voice_top(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365] = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)

    try:
        period = _command_period(
            bot,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        stats = await _fetch_activity_stats(bot, period)
        await _hydrate_top_member_names(bot, interaction.guild, stats)
    except PeriodInputError as exc:
        await _send_error(interaction, str(exc))
        return
    except StatbotError as exc:
        LOGGER.exception("Statbot voice_top request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return

    await interaction.followup.send(embed=build_voice_top_embed(stats))


@app_commands.command(
    name="active",
    description="Показывает всех участников с голосовой активностью.",
)
@app_commands.describe(
    days="Период отчёта в днях, если даты не указаны",
    start_date="Начало периода в формате YYYY-MM-DD",
    end_date="Конец периода в формате YYYY-MM-DD включительно",
)
@_role_check()
async def active(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365] = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)

    try:
        period = _command_period(
            bot,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        stats = await _fetch_activity_stats(bot, period)
        await _hydrate_top_member_names(bot, interaction.guild, stats)
    except PeriodInputError as exc:
        await _send_error(interaction, str(exc))
        return
    except StatbotError as exc:
        LOGGER.exception("Statbot active request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return

    await _send_embed_pages(interaction, build_active_embeds(stats))


@app_commands.command(
    name="afk",
    description="Показывает AFK-время отдельно от голосовой активности.",
)
@app_commands.describe(
    days="Период отчёта в днях, если даты не указаны",
    start_date="Начало периода в формате YYYY-MM-DD",
    end_date="Конец периода в формате YYYY-MM-DD включительно",
)
@_role_check()
async def afk(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365] = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)

    try:
        period = _command_period(
            bot,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        stats = await _fetch_afk_stats(bot, period)
        await _hydrate_top_member_names(bot, interaction.guild, stats)
    except PeriodInputError as exc:
        await _send_error(interaction, str(exc))
        return
    except StatbotError as exc:
        LOGGER.exception("Statbot afk request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return

    await _send_embed_pages(interaction, build_afk_embeds(stats))


@app_commands.command(
    name="inactive",
    description="Показывает участников без голосовой активности.",
)
@app_commands.describe(
    days="Период отчёта в днях, если даты не указаны",
    start_date="Начало периода в формате YYYY-MM-DD",
    end_date="Конец периода в формате YYYY-MM-DD включительно",
)
@_role_check()
async def inactive(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365] = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)

    try:
        period = _command_period(
            bot,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        stats = await _fetch_activity_stats(bot, period)
        members = await _fetch_guild_members(interaction.guild)
    except PeriodInputError as exc:
        await _send_error(interaction, str(exc))
        return
    except StatbotError as exc:
        LOGGER.exception("Statbot inactive request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return
    except discord.Forbidden:
        await _send_error(
            interaction,
            "Discord не разрешил получить список участников. Проверь права бота и Members Intent.",
        )
        return

    active_ids = stats.active_member_ids
    inactive_list = [member for member in members if member.id not in active_ids]
    embed = build_inactive_embed(
        days=period.days,
        inactive_members=inactive_list,
        active_count=len(active_ids),
        total_checked=len(members),
        period_label=period.label,
    )
    await interaction.followup.send(embed=embed)


@app_commands.command(
    name="report",
    description="Показывает общий отчёт по голосовой активности.",
)
@app_commands.describe(
    days="Период отчёта в днях, если даты не указаны",
    start_date="Начало периода в формате YYYY-MM-DD",
    end_date="Конец периода в формате YYYY-MM-DD включительно",
)
@_role_check()
async def report(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365] = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)

    try:
        period = _command_period(
            bot,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        embed = await build_guild_report_embed(bot, interaction.guild, period=period)
    except PeriodInputError as exc:
        await _send_error(interaction, str(exc))
        return
    except StatbotError as exc:
        LOGGER.exception("Statbot report request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return
    except discord.Forbidden:
        await _send_error(
            interaction,
            "Discord не разрешил получить список участников. Проверь права бота и Members Intent.",
        )
        return

    await interaction.followup.send(embed=embed)


@app_commands.command(
    name="test_report",
    description="Отправляет тестовый отчёт в текстовый канал.",
)
@app_commands.describe(
    days="Период отчёта в днях, если даты не указаны",
    start_date="Начало периода в формате YYYY-MM-DD",
    end_date="Конец периода в формате YYYY-MM-DD включительно",
    channel="Канал для тестового отчёта. Если не указан, используется REPORT_CHANNEL_ID или текущий канал.",
)
@_role_check()
async def test_report(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365] = 7,
    start_date: str | None = None,
    end_date: str | None = None,
    channel: discord.TextChannel | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = _get_bot(interaction)

    target_channel = channel or await bot.resolve_report_channel() or interaction.channel
    if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
        await _send_error(
            interaction,
            "Не удалось определить текстовый канал для тестового отчёта.",
        )
        return

    try:
        period = _command_period(
            bot,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        embed = await build_guild_report_embed(
            bot,
            interaction.guild,
            period=period,
            title="Тестовый отчёт по голосовой активности",
            top_limit=10,
        )
        await target_channel.send(embed=embed)
    except PeriodInputError as exc:
        await _send_error(interaction, str(exc))
        return
    except StatbotError as exc:
        LOGGER.exception("Statbot test_report request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return
    except discord.Forbidden:
        await _send_error(
            interaction,
            "Discord не разрешил отправить сообщение в выбранный канал. Проверь права бота.",
        )
        return

    await interaction.followup.send(
        f"Тестовый отчёт отправлен в {target_channel.mention}.",
        ephemeral=True,
    )


@voice_top.error
@active.error
@afk.error
@inactive.error
@report.error
@test_report.error
async def on_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CheckFailure):
        await _send_error(
            interaction,
            "Команда доступна только ролям Officer/Admin или ролям из `ALLOWED_ROLE_IDS`.",
        )
        return

    LOGGER.exception("Unhandled slash command error", exc_info=error)
    await _send_error(interaction, "Произошла внутренняя ошибка бота.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc

    bot = VoiceStatsBot(settings)
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
