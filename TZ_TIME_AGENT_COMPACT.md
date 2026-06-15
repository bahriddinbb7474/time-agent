> Historical or summary document.
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.
> Older stage ordering below is preserved as historical context.

# TZ Time-Agent — Compact Reference (v6.2)

## Цель проекта

Telegram-first personal mental-load dispatcher. Owner-only.
Поток: `capture → organize → remind → protect → plan → review`.
Снижать нагрузку на владельца, а не добавлять сложности.

---

## Зафиксированные решения владельца (не пересматривать)

1. **Google Calendar удаляется** — не используется. Вся GCal-логика вырезается в этапе 16a.
2. **STT** — Groq Whisper large-v3, без принудительного `language` (смешанная русско-узбекская речь). Перед реализацией — обязательный ручной тест владельца.
3. **LLM** — недорогая модель через OpenRouter (кандидат: Qwen). Бюджет минимальный.
4. **Экономия токенов**: rules-first, stateless-вызовы, жёсткий JSON-ответ, дневной hard limit, счётчик `api_usage` в БД.
5. **Деплой** — VPS, 24/7. Backup приходит в Telegram ночью.
6. **Неизменные принципы**: Telegram-first, owner-only, намаз — высший приоритет, AI helps — owner confirms, никаких автономных действий с задачами.

---

## Порядок этапов

```text
16 → 16a → 17 → [ручной STT-тест владельца] → 18 → 19 → 20 → 21
```

Менять порядок нельзя. 17 (деплой) идёт до 18/19 (AI): деплоить простую систему безопаснее, чем сложную.

---

## Этапы — краткое содержание

### Этап 16 — Фундамент (технические долги)

| Шаг | Суть |
|-----|------|
| 16.1а | Migration runner + baseline-миграция. Тест идемпотентности + failure-тест (откат транзакции, версия не записана). |
| 16.1б | Убрать `create_all()` из production-пути (`main.py`). Только после PASS тестов 16.1а. |
| 16.2 | Применить отложенную миграцию Stage 14 к production `data/app.db`. Backup → approval → миграция → smoke-тест. |
| 16.3 | Capture drafts в БД (`capture_drafts`). TTL 48 ч; expired → Later Inbox с пометкой (молча не теряем). |
| 16.4 | Crisis fix: убрать фильтр по несуществующему `Task.user_id`. |
| 16.5 | Provider foundation: config-флаги, фабрики, fake-провайдеры, voice safety helper. Всё disabled by default. |

**Критерии приёмки 16:** production стартует без `create_all()`; рестарт не теряет drafts; crisis-код чист; все провайдеры за фабриками, реальных ключей нет.

### Этап 16a — Удаление Google Calendar

| Шаг | Суть |
|-----|------|
| 16a.1 | Read-only инвентаризация всех точек касания GCal. |
| 16a.2 | Снять регистрацию gcal-роутера, убрать GCal из брифингов. |
| 16a.3 | Удалить `integrations/google`, google-сервисы, sync-policy, oauth_server. Убрать порт 8085, Google env, зависимости. |
| 16a.4 | Таблицы `task_external_links` и `oauth_state` НЕ удалять из production БД (отложено в backlog этапа 21). |
| 16a.5 | Прогон smoke-тестов + ручная проверка брифингов (обязательно, не только тестами). |

### Этап 17 — VPS + Telegram backup

- Linux-совместимый compose (secrets path, Docker healthcheck, log rotation).
- Single-instance guard: второй процесс падает с ясным сообщением.
- Перенос production `data/app.db` на VPS.
- Ночной backup job: `sqlite3 .backup` → zip → отправка в Telegram. Хранить 7 копий локально.
- 7 дней наблюдения.

### Этап 18 — Реальный STT (Groq Whisper)

- Реализация `STTProvider`: загрузка файла, вызов Whisper, timeout + 2 retry, graceful degradation.
- `GROQ_API_KEY` только через env/secrets; транскрипт не в INFO-логах.
- Поток из 16.5 уже готов — замена fake → реальный провайдер.

### Этап 19 — LLM Capture Intelligence (OpenRouter)

- Rules-first: 50–70% capture без LLM.
- Таблица `api_usage` + hard limit (`LLM_DAILY_LIMIT`). `/usage` команда.
- Stateless-вызов: системный промпт ~300 токенов + текст. Ответ — строгий JSON. Max 2 retry.
- LLM-предложение времени → обязательно через `ContextValidator` (prayer protection после LLM, на стороне кода).
- UX: одно сообщение + кнопки (подтвердить / изменить тип / изменить время / отмена).

### Этап 20 — Task Lifecycle Semantics

- Добавить `postponed`, `skipped`, нормальный `cancelled`. Миграция через runner.
- Кнопки в `/today` и брифингах: ✅ / ⏭ / 📅 / ❌.
- Evening planning: одна кнопка на задачу; массовое «всё на завтра» — одной кнопкой с показом списка.
- Boss alert cleanup при закрытии boss-задачи.

### Этап 21 — Финальная полировка

- Weekly review (воскресный обзор).
- Расширенный `/health`: размер БД, активные задачи, pending drafts, последний backup, usage.
- Чистка backlog: дроп-миграция GCal-таблиц, mojibake-строка в `main.py`, документация.
- Финальный аудит безопасности.

---

## Критерии финала (Definition of Done)

1. Бот работает на VPS 24/7 ≥ 2 недель без вмешательства.
2. Голос и текст (русский/узбекский/вперемешку) → подтверждённые задачи.
3. Ни одно действие с задачами без подтверждения владельца.
4. Намазные окна не нарушаются ни одним путём, включая LLM-предложения.
5. Утро: готовый план. Вечер: день закрыт, завтра спланировано.
6. Backup в Telegram каждую ночь; restore проверен дважды.
7. Расход API виден в `/usage`; hard limit работает.
8. Установка с нуля на чистый VPS воспроизводима по README.

---

## Ключевые запреты

- Не применять миграцию к production `data/app.db` без backup + explicit owner approval.
- Не создавать/перемещать/удалять задачи без подтверждения владельца.
- Не обходить prayer protection ни одним путём (включая LLM-предложения).
- Не включать реальные STT/LLM провайдеры до утверждённого этапа.
- Не хранить реальные секреты в коде, git, логах, тестах, документации.
- Не применять частичную миграцию: ошибка → откат транзакции, версия не записана, запуск остановлен.
- Не запускать два экземпляра бота одновременно (Telegram polling conflict + расхождение БД).
- Runner — единственный владелец регистрации версий миграций.
- Промпт LLM фиксируется; изменения только через approval владельца.
- Retry-циклы провайдеров: max 2, потом graceful degradation.
