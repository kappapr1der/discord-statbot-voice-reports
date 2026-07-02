# Discord Statbot Voice Reports

Python-бот для Discord со slash-командами:

- `/voice_top days start_date end_date` - топ участников по времени в голосовых каналах.
- `/active days start_date end_date` - все участники с голосовой активностью и их время.
- `/afk days start_date end_date` - участники и время в AFK отдельно от активности.
- `/inactive days start_date end_date` - участники без голосовой активности.
- `/report days start_date end_date` - общий отчёт.
- `/test_report days start_date end_date channel` - отправляет тестовый отчёт в текстовый канал.

Данные отчётов в режиме `auto` сначала берутся из официального Statbot API. По умолчанию используется:
`https://api.statbot.net/v1/guilds/{GUILD_ID}/voice/tops/members`.

Если Statbot API начинает фейлиться, бот временно переключает отчёты на локальную SQLite-базу и отправляет уведомление в `REPORT_CHANNEL_ID`.

AFK исключён из обычной активности и считается отдельной выборкой.

## Требования

- Python 3.11+.
- Discord bot token.
- Statbot API key.
- Включённый **Server Members Intent** в Discord Developer Portal, иначе `/inactive` и `/report` не смогут получить полный список участников.
- Роли `Officer`/`Admin` на сервере или ID разрешённых ролей в `ALLOWED_ROLE_IDS`.

## Настройка `.env`

Скопируй пример:

```bash
cp .env.example .env
```

Заполни:

```env
DISCORD_TOKEN=your_discord_bot_token
STATBOT_API_KEY=your_statbot_api_key
GUILD_ID=123456789012345678
ALLOWED_ROLE_IDS=123456789012345678,987654321098765432
REPORT_CHANNEL_ID=123456789012345678
VOICE_STATS_SOURCE=auto
```

Опционально:

```env
STATBOT_API_BASE_URL=https://api.statbot.net
STATBOT_AUTH_HEADER=Authorization
STATBOT_REQUEST_TIMEOUT=45
STATBOT_ACTIVE_VOICE_STATES=normal,self_mute,self_deaf,server_mute,server_deaf
STATBOT_AFK_VOICE_STATES=afk
STATBOT_FALLBACK_FAILURE_THRESHOLD=3
STATBOT_RECOVERY_CHECK_SECONDS=900
STATBOT_FALLBACK_ALERTS=true
WEEKLY_REPORT_ENABLED=true
WEEKLY_REPORT_DAYS=7
WEEKLY_REPORT_WEEKDAY=6
WEEKLY_REPORT_TIME=12:00
WEEKLY_REPORT_TIMEZONE=Europe/Moscow
VOICE_SESSION_TRACKING_ENABLED=true
VOICE_ACTIVITY_DB_PATH=/data/voice_activity.sqlite3
AFK_CHANNEL_IDS=123456789012345678
```

Если Statbot выдаёт ключ с другим заголовком, например `X-API-Key`, укажи:

```env
STATBOT_AUTH_HEADER=X-API-Key
```

`STATBOT_ACTIVE_VOICE_STATES` задаёт, какие Statbot voice states считаются активностью. По умолчанию `afk` туда не входит.
`STATBOT_AFK_VOICE_STATES` задаёт отдельную AFK-выборку для `/afk` и блока AFK в `/report`.

`VOICE_STATS_SOURCE` поддерживает:

- `statbot` - всегда читать отчёты только из Statbot API;
- `local` - читать отчёты только из локальной SQLite-базы;
- `auto` - сначала пробовать Statbot, а при ошибках использовать локальную базу.

В режиме `auto` бот всегда возвращает отчёт, если локальная база доступна. После `STATBOT_FALLBACK_FAILURE_THRESHOLD` ошибок Statbot подряд он отправляет алерт в `REPORT_CHANNEL_ID` и помечает отчёты как локальные. Раз в `STATBOT_RECOVERY_CHECK_SECONDS` секунд бот снова проверяет Statbot; когда API оживает, он отправляет алерт о возврате на Statbot.

`AFK_CHANNEL_IDS` нужен для локального SQLite-сборщика. Если на сервере Discord задан системный AFK-канал, бот определит его автоматически; ID нужны только для дополнительных AFK-каналов.

## Запуск локально

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m bot.main
```

Команды синхронизируются только в сервер из `GUILD_ID`, поэтому появляются обычно сразу.

## Периоды отчётов

Если даты не указаны, команды смотрят последние `days` дней. По умолчанию `days` равен `7`.

Конкретный день:

```text
/report start_date:2026-06-20
```

Диапазон дат:

```text
/voice_top start_date:2026-06-17 end_date:2026-06-23
```

`end_date` включается в отчёт. Формат дат: `YYYY-MM-DD`.

Чтобы посмотреть не топ, а всех активных за период:

```text
/active start_date:2026-06-27
```

Чтобы посмотреть AFK отдельно:

```text
/afk start_date:2026-06-27
```

`/inactive` считает активностью только не-AFK время. Если участник за период сидел только в AFK, он попадёт в неактивных.

## Уведомления в канал

`REPORT_CHANNEL_ID` - ID текстового канала, куда бот будет отправлять автоматический отчёт.
Чтобы скопировать ID канала, включи Developer Mode в Discord, нажми правой кнопкой на канал и выбери **Copy Channel ID**.

Для проверки отправь slash-команду:

```text
/test_report days:7
```

Если указать параметр `channel`, тестовый отчёт уйдёт в выбранный канал. Если не указать, бот сначала попробует `REPORT_CHANNEL_ID`, потом текущий канал.

Автоматический отчёт по умолчанию включается, когда задан `REPORT_CHANNEL_ID`, и отправляется каждое воскресенье в `12:00` по `Europe/Moscow`. В `WEEKLY_REPORT_WEEKDAY` используется формат Python: `0` - понедельник, `6` - воскресенье.

В еженедельном отчёте активное время показывается без AFK, а AFK выводится отдельным блоком.

## Подготовка к своему сбору данных

Бот умеет параллельно вести локальный журнал голосовых сессий в SQLite. Это нужно для аварийного fallback с Statbot API на собственный источник данных.

Включить сбор:

```env
VOICE_SESSION_TRACKING_ENABLED=true
VOICE_ACTIVITY_DB_PATH=/data/voice_activity.sqlite3
```

В SQLite пишутся сессии с состоянием `active` или `afk`, каналом, участником, временем начала/конца и длительностью. История локальной базы начинается только с момента включения сборщика, поэтому старые периоды до запуска сборщика Statbot всё ещё покрывает лучше.

## Запуск через Docker

```bash
docker compose up -d --build
docker compose logs -f
```

Compose монтирует `./data` в контейнер как `/data`, чтобы SQLite-база переживала пересборку контейнера.

Остановить:

```bash
docker compose down
```

## Запуск на VPS

1. Установи Docker и Docker Compose plugin.
2. Скопируй проект на сервер.
3. Создай `.env` рядом с `docker-compose.yml`.
4. Запусти:

```bash
docker compose up -d --build
```

Проверить логи:

```bash
docker compose logs -f discord-statbot
```

Обновление:

```bash
git pull
docker compose up -d --build
```

## Права доступа

Команды доступны пользователям, у которых есть:

- роль с именем `Officer`;
- роль с именем `Admin`;
- роль, ID которой указан в `ALLOWED_ROLE_IDS`.

Ошибки доступа, пустые ответы Statbot и ошибки API показываются аккуратным ephemeral embed-сообщением.
