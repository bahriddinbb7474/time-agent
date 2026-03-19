# Project Map — Time-Agent

## Назначение проекта
Time-Agent — Telegram-бот для управления задачами и временем с учетом контекста (правила, сон, намаз), планировщиком напоминаний и интеграцией с Google Calendar.

## Структура проекта

```text
time-agent/
│
├─ src/
│  └─ app/
│     ├─ handlers/              # Telegram-команды и callback-обработчики
│     ├─ services/              # Бизнес-логика (задачи, валидация, синхронизация, Quran, prayer)
│     ├─ scheduler/             # Планировщик и фоновые jobs
│     ├─ db/                    # ORM-модели, CRUD, репозитории, сессии БД
│     ├─ integrations/
│     │  └─ google/             # OAuth и клиент Google Calendar
│     ├─ core/                  # Время и timezone-утилиты
│     ├─ config.py              # Загрузка конфигурации из .env
│     ├─ logging_setup.py       # Конфигурация логирования
│     ├─ security.py            # Middleware доступа (owner-only)
│     └─ main.py                # Инициализация приложения и запуск бота
│
├─ data/                        # Локальная SQLite БД (app.db)
├─ logs/                        # Логи приложения
├─ secrets/                     # Секреты (например, Google credentials)
├─ Dockerfile                   # Контейнеризация приложения
├─ docker-compose.yml           # Запуск сервиса в Docker Compose
├─ requirements.txt             # Python-зависимости
├─ CODEX_RULES.md
├─ CONSTRUCTOR_TASK_TEMPLATE.md
├─ BUG_FIX_TEMPLATE.md
└─ PROJECT_MAP.md
```

## Основные модули
- `src/app/handlers` — слой взаимодействия с Telegram (команды `/add`, `/today`, `/gcal_*`, `/quran` и т.д.).
- `src/app/services` — ключевая логика: задачи, контекстная валидация, синхронизация с Google, prayer/quran сервисы.
- `src/app/db` — доступ к данным: SQLAlchemy модели, CRUD, репозитории и middleware сессии.
- `src/app/scheduler` — периодические задачи и восстановление/исполнение алертов.
- `src/app/integrations/google` — OAuth, хранение/обновление credentials, работа с Google Calendar API.
- `src/app/core` — базовые утилиты времени и timezone.

## Возможная точка входа
`src/app/main.py` (также подтверждается запуском в Docker через `python -m app.main`).

## Основные библиотеки
- `aiogram`
- `SQLAlchemy`
- `aiosqlite`
- `APScheduler`
- `aiohttp`
- `python-dotenv`
- `google-api-python-client`
- `google-auth`
- `google-auth-oauthlib`
