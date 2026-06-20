> Historical document.
> Superseded by `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.
> Do not use this file for planning new stages.

# ARCHIVED / SUPERSEDED — ТЗ Time-Agent v7.1

> This document is historical only. The authoritative roadmap is
> `docs/TZ_TIME_AGENT_FINAL_v8_1.md` with the v8.2 roadmap correction.
> Do not use Stage numbering, Google Calendar references, or acceptance scope here
> for new implementation work.

**Дата:** 14.06.2026
**Назначение:** единый рабочий план от текущего production-состояния до завершённого Time-Agent.
**Принцип:** документ отражает фактическое состояние проекта, а не историческую последовательность старых планов.

**v7.1:** закрыты замечания независимого ревью: формализован restore PASS-критерий; Telegram nightly backup вынесен как OPEN/HIGH остаток Stage 17 до доказательств; token-поля стали обязательным Stage 18.6-C0 до `/usage` и LLM; добавлена проверка proposed time в прошлом; специфицирована callback idempotency; observation унифицирован на 14 дней и заменён субъективный критерий использования на измеримый.

---

## 1. Миссия продукта

Time-Agent — Telegram-first персональный диспетчер и внешняя память владельца.

Он должен помогать:

- быстро фиксировать текстовые и голосовые мысли;
- превращать их в понятные задачи, Later Inbox, boss-задачи и позже идеи;
- защищать обязательные приоритеты: намаз, семья, работа, здоровье;
- снижать mental load утром, в течение дня и вечером;
- не терять данные после рестартов;
- работать 24/7 на VPS;
- не совершать действий без подтверждения владельца.

Главный инвариант:

> AI предлагает и структурирует. Владелец подтверждает. Кодовые валидаторы имеют приоритет над LLM.

---

## 2. Зафиксированные решения владельца

1. **Интерфейс:** Telegram-first, owner-only.
2. **Часовой пояс:** `Asia/Tashkent`.
3. **Намаз:** высший приоритет; Hanafi, `school=1`.
4. **STT:** OpenRouter, модель `openai/whisper-large-v3`.
5. **Язык STT:** `OPENROUTER_STT_LANGUAGE=ru`.
6. **Узбекский и смешанная речь:** best-effort; владелец всегда видит транскрипт и подтверждает результат.
7. **LLM:** OpenRouter, модель задаётся через config; архитектура не привязывается к одному поставщику.
8. **Расход API:** usage в БД, команда `/usage`, hard limit до подключения реального LLM.
9. **Google Calendar:** владельцу не нужен; активный GCal-код должен быть удалён после read-only аудита.
10. **Деплой:** VPS, Docker Compose, production SQLite.
11. **Миграции:** только migration runner и `schema_migrations`; никаких новых production-изменений схемы через `create_all()`.
12. **Git:** один этап — один ограниченный commit; push и deployment выполняются отдельными командами.
13. **Безопасность:** ключи только в `.env`/secrets; transcript, task text, API keys и audio/base64 не попадают в обычные логи.
14. **Текущий исполнитель:** Claude Code. Перед каждой задачей он обязан сначала прочитать и соблюдать корневой `CLAUDE.md`.

---

## 3. Фактическое текущее состояние

### Закрыто

- VPS deployment и работа бота 24/7.
- Docker production-контур.

**Уточнение по Stage 17:** production runtime на VPS закрыт, но Telegram nightly backup, retention и проверенный restore пока не считаются закрытыми без доказательств. Если аудит не подтвердит их работу, это незакрытый HIGH-приоритетный остаток Stage 17, который должен быть выполнен до основного Definition of Done.
- SQLite + SQLAlchemy Async.
- Migration runner и `schema_migrations`.
- Pending capture drafts в БД через `CaptureDraftRecord`.
- Voice download в temp и гарантированное удаление.
- OpenRouter STT.
- Safe handling ожидаемых и неожиданных STT-ошибок.
- A/B-тест языка; production оставлен на `language=ru`.
- Таблица `api_usage`.
- ORM-модель и `ApiUsageService`.
- Запись STT usage.
- Различение:
  - HTTP-запрос выполнен успешно;
  - HTTP-запрос выполнен с ошибкой;
  - HTTP-запрос не выполнялся.
- Проверка NaN/Infinity.
- Commit chain до `fd23d87` отправлена в `main`.

### Закрыто дополнительно (Stage 18.6-P)

**Stage 18.6-P — CLOSED / PRODUCTION PASS**

Доказанный результат:
- production HEAD: `fd23d87`;
- migration `20260614_2000_add_api_usage` применена один раз;
- `PRAGMA integrity_check = ok`;
- backup создан и проверен;
- `api_usage` существует;
- voice smoke прошёл;
- одна voice-обработка создала одну STT usage-строку: provider `openrouter`, model `openai/whisper-large-v3`, status `success`;
- container running, restart count: `0`;
- transcript и secrets не появились в логах или `api_usage`.

### Сейчас выполняется

**Следующий этап: Stage 18.6-C0** — расширение `api_usage` полями `input_tokens` и `output_tokens`.

После него: `18.6-C /usage → 18.6-D hard limits → pre-Stage-19 audit → Stage 19`.

### Не подтверждено

- Полное удаление Google Calendar.
- Удаление мёртвого crisis-фильтра по `Task.user_id`.

Эти два пункта требуют read-only аудита до начала реального Stage 19.

---

# 4. Ближайший маршрут

```text
18.6 production close
→ 18.6-C0 token usage schema
→ 18.6-C /usage
→ 18.6-D API limits
→ pre-Stage-19 debt audit
→ при необходимости GCal/crisis cleanup
→ Stage 19 LLM Capture Intelligence
→ Stage 20 Task Lifecycle
→ Stage 21 Production hardening and finalization
→ Definition of Done
→ Stage 22 Idea Vault
```

---

# STAGE 18.6 — Закрытие STT usage

## 18.6-P — Production deployment и smoke

**Status: CLOSED / PRODUCTION PASS**

### Цель

Подтвердить на production:

```text
voice
→ OpenRouter STT
→ confirmation draft
→ api_usage row
```

### Обязательные проверки

- backup production DB создан и читается;
- `PRAGMA integrity_check = ok`;
- миграция применена ровно один раз;
- `api_usage` содержит только технические поля;
- voice создаёт ровно одну строку usage;
- отмена confirmation не создаёт тестовую задачу;
- container running, restart count стабилен;
- в логах нет transcript, ключей, Authorization и base64.

### Acceptance

Stage закрывается только после production PASS.

---

## 18.6-C0 — Расширение `api_usage` для LLM

### Цель

До первого реального LLM-вызова добавить отдельной migration:

```text
input_tokens INTEGER NOT NULL DEFAULT 0
output_tokens INTEGER NOT NULL DEFAULT 0
```

### Правила

- migration применяется только через runner;
- существующие STT-строки получают нули;
- значения неотрицательные;
- для STT token-поля остаются `0`;
- для LLM `audio_seconds=0`;
- schema/model/service/tests обновляются до реализации `/usage`;
- prompt, response body, transcript и task text не сохраняются;
- production deployment: backup → integrity check → migration → read-only schema verification → smoke.

### Acceptance

- clean/temp migration PASS;
- idempotency PASS;
- существующие STT usage-тесты PASS;
- LLM-строка с token values сохраняется и агрегируется;
- production migration применена ровно один раз;
- до завершения этого шага реальный LLM provider запрещён.

---

## 18.6-C — Команда `/usage`

### Цель

Владелец видит понятный расход API без SQL и доступа к VPS.

### UX v1

```text
📊 Использование API

Сегодня:
STT: 7 запросов, 84 сек, $0.00xx
LLM: 0 запросов, 0 токенов, $0.00

7 дней:
STT: ...
LLM: ...
```

### Требования

- owner-only;
- read-only запросы;
- today рассчитывается по `Asia/Tashkent`, а не UTC;
- показываются:
  - request count;
  - STT audio seconds;
  - LLM input/output tokens;
  - estimated cost;
  - success/error/limit-exceeded count;
- отсутствие записей отображается как ноль;
- никакого transcript или task text;
- команда не падает при старой/пустой БД;
- focused tests и production smoke.

### Зафиксированное решение

Token-поля добавляются в обязательном шаге 18.6-C0 до `/usage` и до первого реального LLM-вызова. `/usage` сразу строится на окончательной универсальной схеме STT + LLM, чтобы не переделывать команду после запуска Stage 19.

---

## 18.6-D — Hard limits

### Цель

Ни STT, ни будущий LLM не могут бесконтрольно расходовать бюджет.

### Конфигурация

Предпочтительно раздельно:

```text
STT_DAILY_REQUEST_LIMIT
STT_DAILY_SECONDS_LIMIT
LLM_DAILY_REQUEST_LIMIT
LLM_DAILY_COST_USD_LIMIT
```

`0` означает unlimited.

### Правила STT

Проверка выполняется до OpenRouter-запроса.

При достижении лимита:

```text
Лимит распознавания на сегодня достигнут.
Напиши сообщение текстом.
```

- HTTP не вызывается;
- usage можно записать как `limit_exceeded` только если это не создаёт рекурсивной зависимости;
- DB-error при проверке лимита не должен полностью блокировать владельца: разрешить запрос и записать warning без чувствительных данных.

### Правила LLM

- hard limit обязан работать до включения реального advisor;
- при лимите используется rules-only fallback;
- владельцу отправляется одно понятное уведомление, а не сообщение на каждый capture;
- лимит считается по локальному дню `Asia/Tashkent`.

### Acceptance

- boundary tests;
- limit=1 smoke;
- второй provider call не выполняется;
- no double-count;
- no transcript in logs;
- production config меняется отдельным approval-шагом.

---

# PRE-STAGE 19 — Долги и архитектурный аудит

## A. Google Calendar audit

Проверить:

- router registration;
- handlers;
- services;
- integrations;
- OAuth server;
- config/env;
- Docker port 8085;
- Google dependencies;
- GCal-контекст в morning/evening briefings;
- таблицы `task_external_links`, `oauth_state`;
- документы и команды.

### Решение после аудита

Если активный код существует:

1. отключить интерфейс;
2. удалить активный GCal runtime-код и зависимости;
3. не дропать production-таблицы сразу;
4. вручную проверить morning/evening briefings;
5. отдельный commit и production deployment.

## B. Crisis audit

Проверить:

- все обращения к `Task.user_id`;
- crisis trigger;
- focus/crisis handlers;
- реальные колонки других моделей с `user_id`.

Если мёртвый фильтр существует — удалить минимальным commit и прогнать crisis/focus tests.

## C. Migration coverage debt

Добавить failure-тест migration runner:

- битая migration;
- transaction rollback;
- version не записана;
- приложение получает ясный `MigrationError`.

Это желательно закрыть до новых миграций Stage 19/20.

---

# STAGE 19 — LLM Capture Intelligence

## Цель

Любая осмысленная мысль:

```text
text или voice transcript
→ deterministic rules
→ при необходимости один LLM call
→ structured proposal
→ owner confirmation
→ сохранение
```

Никакого автономного создания задач.

---

## 19.0 — Input quality guard

### Важная корректировка

Нельзя надёжно определить «бессмыслицу» только эвристикой длины или одного слова.

Одно слово может быть валидной мыслью:

```text
Договор
Мама
Книга
Налоги
```

Поэтому guard должен быть консервативным.

### Жёстко отклонять только

- пустой текст;
- только пробелы/пунктуация;
- очевидный STT noise marker;
- слишком короткий технический мусор без букв/цифр;
- результат, который сам STT пометил как пустой.

### Не отклонять автоматически

- одно осмысленное слово;
- короткую фразу;
- узбекскую/русскую смесь;
- текст с орфографическими ошибками.

При низкой уверенности бот показывает transcript и спрашивает:

```text
Я не уверен, что правильно понял голос.
Исправь текст или отправь заново.
```

LLM не должен выдумывать отсутствующий смысл.

---

## 19.1 — Capture contract

Создать единый DTO результата capture:

```text
source
raw_text
source_transcript
suggested_type
category
title
planned_at
confidence
needs_owner_clarification
provider_metadata
```

- raw/transcript остаются только в draft;
- подтверждённая сущность получает очищенное значение;
- LLM output никогда не пишется напрямую в Task без validation.

---

## 19.2 — Rules-first classifier

До LLM:

- явные команды;
- `boss`;
- `later`;
- «напомни»;
- дата/время;
- срочность;
- понятные категории.

Rules должны возвращать:

```text
matched
confidence
structured proposal
reason code
```

Если confidence достаточен — LLM не вызывается.

Не фиксировать искусственную KPI «50–70%» как acceptance. Сначала собрать реальные capture-примеры владельца и измерить фактический результат.

---

## 19.3 — LLM usage integration

Схема token-полей уже обязана быть добавлена на Stage 18.6-C0.

На этом шаге advisor provider возвращает нормализованные usage metadata:

```text
input_tokens
output_tokens
estimated_cost_usd
request_made
```

Handler/service записывает одну LLM usage-строку на один завершённый provider flow.

Допустимо добавить `provider_request_id` только отдельным решением, если он не содержит пользовательские данные и доказана диагностическая ценность.

Не хранить:

- prompt;
- response body;
- transcript;
- task text.

---

## 19.4 — Advisor provider

### Интерфейс

- `DisabledAdvisorProvider`;
- `FakeAdvisorProvider`;
- `OpenRouterAdvisorProvider`;
- factory по config.

### Вызов

- stateless;
- один capture = максимум один основной LLM-вызов;
- timeout;
- ограниченный retry только для transient network errors;
- no retry для invalid JSON;
- fallback rules/manual confirmation.

### Output schema

```json
{
  "type": "task|later|boss",
  "category": "work|family|health|personal|other",
  "title": "string",
  "when": "ISO datetime|null",
  "confidence": 0.0,
  "needs_clarification": false
}
```

Не добавлять `idea` до Stage 22.

### Parsing

- строгая schema validation;
- запрещены неизвестные поля либо они игнорируются по явно выбранному правилу;
- markdown fences удаляются безопасно;
- invalid JSON не приводит ко второму «исправляющему» LLM-вызову.

---

## 19.5 — Prompt-injection boundary

Любой пользовательский текст и transcript считаются недоверенными данными.

Промпт должен явно разделять:

```text
SYSTEM INSTRUCTIONS
UNTRUSTED USER CAPTURE
```

Модель не может:

- менять системные правила;
- обходить owner confirmation;
- обходить ContextValidator;
- выполнять команды из transcript;
- возвращать произвольный Telegram markup.

---

## 19.6 — Prayer and time validation

После rules или LLM:

1. parse proposed datetime;
2. применить timezone `Asia/Tashkent`;
3. проверить, не находится ли proposed datetime в прошлом;
4. если время уже прошло — не принимать его как валидное: переспросить владельца или предложить ближайший безопасный будущий слот;
5. прогнать через `ContextValidator`;
6. проверить prayer/family/sleep protections;
7. предложить безопасное время;
8. только затем показать confirmation.

LLM не имеет права объявить слот безопасным.

---

## 19.7 — Confirmation UX

Одно компактное сообщение:

```text
Понял так:

Тип: Задача
Название: Позвонить поставщику
Время: завтра, 10:00
Категория: Работа

[Сохранить] [Изменить] [Later] [Boss] [Отмена]
```

Для voice выше показывается редактируемый transcript.

Нужны пути:

- изменить title;
- изменить type;
- изменить time;
- отменить;
- повторно отправить voice/text.

Любое сохранение — только после callback владельца.

---

## 19.8 — Evaluation before production enablement

Подготовить owner dataset без помещения данных в Git:

- русские capture;
- узбекские;
- смешанные;
- шумные transcript;
- task/later/boss;
- даты и время;
- low-confidence cases.

Оценить:

- правильность type;
- title;
- date/time;
- false invention rate;
- rules-only rate;
- average cost;
- latency.

Модель выбирается по факту этих тестов, а не заранее только по названию.

---

## 19.9 — Production rollout

1. provider disabled by default;
2. backup DB;
3. deploy code;
4. enable на минимальном лимите;
5. manual smoke;
6. проверить usage;
7. проверить logs/privacy;
8. увеличить лимит только после owner approval.

---

# STAGE 20 — Task Lifecycle Semantics

## 20.0 — Read-only domain audit

До миграции проверить существующие:

- statuses;
- callbacks;
- alert cancellation;
- daily plan behavior;
- evening summary;
- boss loop.

Не добавлять новые статусы, пока не определена совместимость со старыми строками БД.

---

## 20.1 — Статусы и переходы

Целевые состояния:

```text
todo
done
postponed
skipped
cancelled
```

Определить разрешённые переходы кодом.

Пример:

```text
todo → done
todo → postponed
todo → skipped
todo → cancelled
postponed → done
postponed → postponed
```

Нельзя иметь статус без ясной семантики в `/today`, alerts и reporting.

---

## 20.2 — Postpone model

Рекомендуется не только менять status, но сохранять историю переноса минимально:

- old planned time;
- new planned time;
- postponed_at.

Если отдельная history-таблица избыточна, минимум — поля на Task, позволяющие отличить перенос от обычного редактирования.

Все новые времена проходят ContextValidator.

---

## 20.3 — Telegram actions

В `/today`, briefing и карточке задачи:

```text
✅ Сделано
📅 Перенести
⏭ Пропустить сегодня
❌ Отменить
```

Нужны idempotency и защита от повторного callback.

Минимальный механизм v1:

- перед переходом перечитать текущий status из БД;
- разрешить только валидный переход из текущего состояния;
- повторный callback в уже установленный тот же status — безопасный no-op с коротким ответом;
- callback по устаревшему состоянию не повторяет side effects и не создаёт новые scheduler jobs;
- для действий с временным draft/action-token токен после успешного применения помечается использованным.

---

## 20.4 — Evening closeout

Вечером показывать только нерешённые элементы.

UX:

- по одной задаче;
- массовое «перенести подходящие на завтра»;
- Later;
- skip;
- cancel.

Перед массовым действием бот показывает список и требует подтверждение.

---

## 20.5 — Boss alert lifecycle

При `done/cancelled/skipped/postponed` текущий alert-cycle должен корректно остановиться или пересчитаться.

Проверить:

- scheduled jobs;
- stale callbacks;
- restart recovery;
- duplicate alerts.

---

# STAGE 21 — Production hardening и финализация

## 21.1 — Telegram backup и проверяемый restore

### Статус

До получения доказательств Telegram nightly backup считается **OPEN / HIGH**, даже если VPS runtime работает стабильно. Это незакрытый остаток Stage 17, а не необязательная финальная полировка.

### Что должно быть реализовано или подтверждено

- ночной SQLite backup;
- отправка внешней копии владельцу в Telegram;
- локальная retention последних копий;
- безопасные permissions;
- уведомление при failure;
- restore runbook.

### Критерий успешного restore

Restore считается PASS только если:

1. backup восстановлен в изолированную temp DB, не поверх production;
2. `PRAGMA integrity_check = ok`;
3. row counts ключевых таблиц совпадают с источником на момент backup, минимум:
   - `tasks`;
   - `capture_drafts`;
   - `api_usage`;
   - `schema_migrations`;
   - другие критичные таблицы, существующие на момент проверки;
4. migration versions совпадают с backup source;
5. приложение или отдельный smoke-контур успешно стартует на восстановленной БД;
6. выполняются безопасные smoke-проверки чтения (`/health`, `/today` или эквивалент без отправки production alerts);
7. процедура и результат записаны в restore runbook.

Restore проверяется дважды за проект:

- первый раз после реализации Telegram backup;
- второй раз в финальном Stage 21 перед DoD.

---

## 21.2 — Single-instance and health

Проверить факт:

- single-instance guard;
- Docker restart policy;
- healthcheck;
- log rotation;
- disk usage;
- DB writable;
- last successful backup;
- scheduler alive.

`/health` показывает только безопасные технические данные.

---

## 21.3 — Weekly review

Сводка:

- завершено;
- перенесено;
- skipped/cancelled;
- Later Inbox;
- boss items;
- Quran/health progress, если эти модули реально активны;
- STT/LLM usage;
- забытые pending drafts.

Review должен снижать нагрузку, а не превращаться в длинный отчёт.

---

## 21.4 — GCal final cleanup

После удаления runtime-кода решить судьбу старых таблиц:

- оставить архивно;
- экспортировать;
- удалить отдельной migration.

Дроп разрешён только после backup и проверки, что runtime больше не читает таблицы.

---

## 21.5 — Documentation

README должен содержать:

- clean VPS install;
- env template без secrets;
- deploy;
- migration behavior;
- backup;
- restore;
- key rotation;
- troubleshooting polling conflict;
- rollback procedure;
- commands inventory.

---

## 21.6 — Security and privacy audit

Проверить:

- Git history на случайно добавленные ключи;
- текущий tree;
- production logs;
- Docker inspect output;
- env permissions;
- backups permissions;
- transcript/task text in logs;
- request/response bodies;
- Telegram IDs.

Секреты при подозрении ротируются.

---

## 21.7 — Observation window

Единое окно наблюдения для всего документа: **14 последовательных дней production**.

Критерии:

- нет ручного ремонта БД;
- нет restart loop;
- нет polling conflict;
- Telegram backup приходит по расписанию;
- briefings приходят по `Asia/Tashkent`;
- usage limit работает;
- минимум 10 подтверждённых capture владельца за окно наблюдения, включая минимум:
  - 3 text;
  - 3 voice;
  - 1 перенос/изменение перед подтверждением;
  - 1 rules-only;
  - 1 LLM-assisted после включения Stage 19.

Если LLM ещё не включён, observation для финального DoD не начинается.

---

# 5. Definition of Done

Проект считается завершённым, когда подтверждены все пункты:

1. Production работает на VPS минимум 14 последовательных дней стабильно по единому observation-критерию Stage 21.7.
2. Telegram backup приходит владельцу; restore дважды прошёл формальный критерий Stage 21.1: temp DB, integrity `ok`, совпадающие row counts и migration versions, успешный isolated application smoke и задокументированный runbook.
3. Migration runner — единственный production schema path.
4. Pending drafts переживают рестарт.
5. Google runtime-код удалён.
6. Crisis dead code устранён.
7. Voice capture стабилен и privacy-safe.
8. `/usage` показывает STT/LLM.
9. Hard limits реально блокируют provider call.
10. Rules-first и LLM capture протестированы на реальных примерах владельца.
11. Никакая задача не создаётся/переносится без owner confirmation.
12. Все proposed times проходят ContextValidator.
13. Prayer protection проверена для text, voice, rules и LLM.
14. Task lifecycle согласован с alerts и evening closeout.
15. README позволяет поднять проект на чистом VPS.
16. Логи и БД не содержат запрещённых API payload данных.
17. Нет открытых BLOCKER/HIGH дефектов.
18. Известные MEDIUM/LOW долги перечислены в backlog с решением владельца.

---

# STAGE 22 — Idea Vault / Инкубатор идей

## Статус

Post-final функциональный модуль. Начинается только после основного DoD.

Однако саму пользовательскую потребность нужно сохранить уже сейчас в backlog.

## 22.0 — Product discovery

До схемы данных собрать 10–20 реальных идей владельца и проверить:

- какие темы реально используются;
- нужны ли вложенные темы;
- что означает прогресс;
- как часто нужен review;
- нужны ли paused и archived одновременно;
- нужна ли идея без title;
- нужно ли несколько next steps.

Не проектировать по абстрактным примерам.

---

## 22.1 — Минимальная модель

### `ideas`

```text
id
title
theme
description
stage
progress_done
progress_total
next_step
next_review_at
created_at
updated_at
archived_at nullable
```

### `idea_notes`

```text
id
idea_id
text
created_at
```

Stage:

```text
someday
thinking
planning
in_progress
paused
done
archived
```

Инварианты:

- `progress_done >= 0`;
- `progress_total >= 0`;
- если total > 0, done <= total;
- archived согласован со stage;
- idea без срока всё равно имеет `next_review_at`.

---

## 22.2 — Capture UX

Явные команды:

```text
/idea <текст>
/ideas
```

LLM не нужен для `/idea`.

При обычном capture тип `idea` добавляется в classifier только на Stage 22.

Граница:

- task — действие;
- later — действие без текущего срока;
- idea — долгоживущий объект развития.

При сомнении бот спрашивает владельца.

---

## 22.3 — Карточка идеи

Показывает:

- название;
- тема;
- stage;
- progress;
- next step;
- next review;
- latest note.

Кнопки:

```text
Добавить мысль
Изменить этап
Обновить прогресс
Следующий шаг
Напомнить позже
Создать задачу
Завершить
Архив
```

---

## 22.4 — Review engine

Показывать идеи, у которых:

```text
next_review_at <= now
```

Действия:

- открыть;
- добавить заметку;
- назначить next step;
- отложить обзор;
- paused;
- archive.

Не использовать только `updated_at > N days`: владелец сам задаёт review cadence.

---

## 22.5 — Idea → Task

Создание обычной task из next step:

- owner confirmation;
- ContextValidator;
- ссылка на source idea.

В v1 допустимо поле `source_idea_id` в Task отдельной migration. Это надёжнее свободной текстовой пометки, если связь реально нужна.

---

## 22.6 — Не делать по умолчанию

- embeddings;
- vector DB;
- автоматическая группировка;
- шесть таблиц;
- сложная milestone history;
- автономное продвижение stage.

Эти функции появляются только после доказанной пользовательской потребности.

---

# 6. Порядок исполнения

```text
A. Закрыть production deploy 18.6
B. Добавить token-поля в `api_usage` (18.6-C0)
C. Реализовать `/usage`
D. Реализовать hard limits
E. Провести GCal + crisis read-only audit
F. Закрыть найденные долги
G. Подтвердить/реализовать Telegram nightly backup и первый restore
H. Реализовать Stage 19 по маленьким подэтапам
I. Реализовать Stage 20
J. Выполнить Stage 21 и единое 14-дневное наблюдение
K. Выполнить второй restore и подтвердить Definition of Done
L. Начать Stage 22 Idea Vault
```

Каждый подэтап:

```text
ANALYZE
→ IMPLEMENT
→ VERIFY
→ REPORT
→ COMMIT
→ independent review
→ PUSH
→ production backup/deploy/smoke
```

Нельзя объединять несколько рискованных миграций или production-изменений в одну задачу.

---

# 7. Известные текущие долги

1. GCal status — needs audit.
2. Crisis `Task.user_id` — needs audit.
3. Migration failure rollback test — проверить/добавить.
4. `_normalize_usage_float` принимает bool как число — LOW, исправить отдельным focused commit.
5. `isinstance(OpenRouterSTTProvider)` в usage flow — техническая связанность; заменить provider metadata/capability при следующем provider refactor.
6. STT language `ru` ухудшает узбекский — product limitation, не скрывать.
7. Usage durability зависит от outer transaction commit — принятое поведение, документировать.
8. Token columns для LLM usage ещё не определены.
9. Telegram nightly backup и первый формальный restore — OPEN/HIGH до доказательств; single-instance guard также нужно подтвердить. Единое observation window — 14 дней, упоминаний 7 дней в актуальном плане быть не должно.

---

# 8. Запреты для всего оставшегося проекта

- Не менять production DB вручную.
- Не использовать `docker compose down -v`.
- Не удалять volume.
- Не делать force push.
- Не хранить secrets в Git.
- Не логировать transcript/task text/API payload.
- Не позволять LLM обходить owner confirmation.
- Не позволять LLM обходить prayer/time validators.
- Не начинать Idea Vault до основного DoD.
- Не объявлять Stage закрытым только по наличию кода: нужен тест и, где применимо, production smoke.
