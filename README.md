# Discord Statbot Voice Reports

Python-бот для Discord со slash-командами:

- `/voice_top days start_date end_date` - топ участников по времени в голосовых каналах.
- `/active days start_date end_date` - все участники с голосовой активностью и их время.
- `/inactive days start_date end_date` - участники без голосовой активности.
- `/report days start_date end_date` - общий отчёт.
- `/test_report days start_date end_date channel` - отправляет тестовый отчёт в текстовый канал.

Данные берутся из официального Statbot API. По умолчанию используется:
`https://api.statbot.net/v1/guilds/{GUILD_ID}/voice/tops/members`.

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
```

Опционально:

```env
STATBOT_API_BASE_URL=https://api.statbot.net
STATBOT_AUTH_HEADER=Authorization
STATBOT_REQUEST_TIMEOUT=45
WEEKLY_REPORT_ENABLED=true
WEEKLY_REPORT_DAYS=7
WEEKLY_REPORT_WEEKDAY=6
WEEKLY_REPORT_TIME=12:00
WEEKLY_REPORT_TIMEZONE=Europe/Moscow
```

Если Statbot выдаёт ключ с другим заголовком, например `X-API-Key`, укажи:

```env
STATBOT_AUTH_HEADER=X-API-Key
```

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

## Уведомления в канал

`REPORT_CHANNEL_ID` - ID текстового канала, куда бот будет отправлять автоматический отчёт.
Чтобы скопировать ID канала, включи Developer Mode в Discord, нажми правой кнопкой на канал и выбери **Copy Channel ID**.

Для проверки отправь slash-команду:

```text
/test_report days:7
```

Если указать параметр `channel`, тестовый отчёт уйдёт в выбранный канал. Если не указать, бот сначала попробует `REPORT_CHANNEL_ID`, потом текущий канал.

Автоматический отчёт по умолчанию включается, когда задан `REPORT_CHANNEL_ID`, и отправляется каждое воскресенье в `12:00` по `Europe/Moscow`. В `WEEKLY_REPORT_WEEKDAY` используется формат Python: `0` - понедельник, `6` - воскресенье.

## Запуск через Docker

```bash
docker compose up -d --build
docker compose logs -f
```

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
