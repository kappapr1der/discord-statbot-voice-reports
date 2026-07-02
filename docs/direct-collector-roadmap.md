# Переход на собственный сбор голосовой активности

Сейчас бот считает отчёты через Statbot API, но параллельно может писать новые голосовые сессии в SQLite. Это даёт мягкий переход: история Statbot остаётся доступной, а собственная база начинает копиться уже сейчас.

## Что уже подготовлено

- `VOICE_STATS_SOURCE=statbot` оставляет отчёты на Statbot.
- `VOICE_STATS_SOURCE=local` читает отчёты только из SQLite.
- `VOICE_STATS_SOURCE=auto` сначала пробует Statbot, а при ошибках использует SQLite.
- `STATBOT_ACTIVE_VOICE_STATES` исключает `afk` из активности.
- `STATBOT_AFK_VOICE_STATES=afk` даёт отдельную AFK-выборку для `/afk` и `/report`.
- `VOICE_SESSION_TRACKING_ENABLED=true` включает локальный SQLite-журнал.
- `AFK_CHANNEL_IDS` позволяет пометить дополнительные AFK-каналы; системный Discord AFK-канал определяется автоматически.
- `STATBOT_FALLBACK_FAILURE_THRESHOLD` задаёт, после скольких ошибок Statbot подряд отправлять алерт о переходе на локальную базу.
- `STATBOT_RECOVERY_CHECK_SECONDS` задаёт, как часто в fallback-режиме проверять восстановление Statbot.

## Как копится локальная история

Таблица `voice_sessions` хранит:

- `guild_id`, `user_id`;
- `channel_id`, `channel_name`;
- `state`: `active` или `afk`;
- `started_at`, `ended_at`, `duration_seconds`;
- `ended_reason`: `left`, `moved`, `reopened`, `bot_shutdown`, `bot_startup_reconcile`.

При старте бот закрывает старые открытые сессии и заново открывает текущие подключения. Так база не засчитывает время, когда бот был выключен.

## План переключения

1. Держать `VOICE_STATS_SOURCE=auto`, чтобы Statbot оставался основным источником, а SQLite был резервом.
2. Дать локальному сбору поработать 2-4 недели параллельно со Statbot.
3. Сравнить отчёты Statbot и SQLite на одинаковых периодах.
4. После проверки можно переключить `VOICE_STATS_SOURCE=local`.
5. Statbot можно оставить как ручной fallback через возврат к `VOICE_STATS_SOURCE=auto`.
