from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .config import ConfigError, Settings
from .embeds import (
    build_error_embed,
    build_inactive_embed,
    build_report_embed,
    build_voice_top_embed,
)
from .statbot_client import StatbotClient, StatbotEmptyDataError, StatbotError, StatbotHTTPError


LOGGER = logging.getLogger(__name__)
ALLOWED_ROLE_NAMES = {"officer", "admin"}


class VoiceStatsBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True

        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.statbot: StatbotClient | None = None

    async def setup_hook(self) -> None:
        self.statbot = StatbotClient(
            api_key=self.settings.statbot_api_key,
            guild_id=self.settings.guild_id,
            base_url=self.settings.statbot_api_base_url,
            auth_header=self.settings.statbot_auth_header,
            timeout=self.settings.statbot_request_timeout,
        )

        guild = discord.Object(id=self.settings.guild_id)
        self.tree.add_command(voice_top, guild=guild)
        self.tree.add_command(inactive, guild=guild)
        self.tree.add_command(report, guild=guild)
        synced = await self.tree.sync(guild=guild)
        LOGGER.info("Synced %s slash commands for guild %s", len(synced), guild.id)

    async def close(self) -> None:
        if self.statbot:
            await self.statbot.close()
        await super().close()

    async def on_ready(self) -> None:
        LOGGER.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")


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


async def _fetch_guild_members(interaction: discord.Interaction) -> list[discord.Member]:
    guild = interaction.guild
    if guild is None:
        return []

    members: list[discord.Member] = []
    async for member in guild.fetch_members(limit=None):
        if not member.bot:
            members.append(member)
    return members


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
@app_commands.describe(days="Период отчёта в днях")
@_role_check()
async def voice_top(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365],
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)
    assert bot.statbot is not None

    try:
        stats = await bot.statbot.fetch_voice_stats(days)
    except StatbotError as exc:
        LOGGER.exception("Statbot voice_top request failed")
        await _send_error(interaction, _statbot_error_message(exc))
        return

    await interaction.followup.send(embed=build_voice_top_embed(stats))


@app_commands.command(
    name="inactive",
    description="Показывает участников без голосовой активности.",
)
@app_commands.describe(days="Период отчёта в днях")
@_role_check()
async def inactive(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365],
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)
    assert bot.statbot is not None

    try:
        stats = await bot.statbot.fetch_voice_stats(days)
        members = await _fetch_guild_members(interaction)
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
        days=days,
        inactive_members=inactive_list,
        active_count=len(active_ids),
        total_checked=len(members),
    )
    await interaction.followup.send(embed=embed)


@app_commands.command(
    name="report",
    description="Показывает общий отчёт по голосовой активности.",
)
@app_commands.describe(days="Период отчёта в днях")
@_role_check()
async def report(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 1, 365],
) -> None:
    await interaction.response.defer()
    bot = _get_bot(interaction)
    assert bot.statbot is not None

    try:
        stats = await bot.statbot.fetch_voice_stats(days)
        members = await _fetch_guild_members(interaction)
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

    inactive_list = [member for member in members if member.id not in stats.active_member_ids]
    embed = build_report_embed(
        stats=stats,
        inactive_members=inactive_list,
        total_checked=len(members),
    )
    await interaction.followup.send(embed=embed)


@voice_top.error
@inactive.error
@report.error
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
