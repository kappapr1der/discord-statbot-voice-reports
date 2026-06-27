# Discord Statbot Voice Reports

Python-бот для Discord со slash-командами:

- `/voice_top days` - топ участников по времени в голосовых каналах за N дней.
- `/inactive days` - участники без голосовой активности за N дней.
- `/report days` - общий отчёт.

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
```

Опционально:

```env
STATBOT_API_BASE_URL=https://api.statbot.net
STATBOT_AUTH_HEADER=Authorization
STATBOT_REQUEST_TIMEOUT=45
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
