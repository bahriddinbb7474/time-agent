# ТЗ Time-Agent: план реализации до финала — версия архитектора (v8.1)

**Дата:** 15.06.2026
**Назначение:** единый рабочий план от текущего production-состояния до завершённого основного Time-Agent и отдельных post-final модулей.
**Принцип:** документ отражает фактическое состояние проекта, реальные зависимости между подсистемами и зафиксированную потребность владельца в полном планировании и учёте времени.

**v8.1:** финальная корректировка после независимого ревью v8.0: исполнитель больше не зафиксирован жёстко — перед каждым этапом владелец выбирает Codex или Claude Code по доступному лимиту; добавлены защита от забытых start/stop-таймеров, общий бюджет утреннего брифинга, точная семантика `daily_schedules.version` и правило учёта activity, пересекающей полночь.

**v8.0:** по итогам трёх архитектурных проходов Daily Targets и Daily Control включены в основной продукт. Добавлен Stage 18.7 (дневные нормы без LLM), новый Stage 20 (расписание 24/7, check-in, фактический журнал и plan-vs-fact после Stage 19), Task Lifecycle сдвинут на Stage 21, Production hardening + основной DoD — на Stage 22, Idea Vault — на Stage 23, Statistics & Forecasting — на Stage 24. Check-in работает rules-first: кнопки и типовые ответы бесплатны, LLM вызывается только для свободного текста/голоса. Сон закреплён как защищённый показатель: бот учитывает факт и дефицит, но не оптимизирует день путём сокращения сна.

---

## 1. Миссия продукта

Time-Agent — Telegram-first персональный диспетчер, внешняя память и личный бухгалтер времени владельца.

Он должен помогать:

- быстро фиксировать текстовые и голосовые мысли;
- превращать их в понятные задачи, Later Inbox, boss-задачи и позже идеи;
- задавать постоянные цели суток и учитывать частичное выполнение;
- составлять расписание дня по времени;
- учитывать фактические действия, включая полезные дела вне плана;
- задавать короткие check-in вопросы каждый час или два;
- принимать ответ голосом, текстом, кнопкой или `не помню`;
- сравнивать план и факт без выдумывания отсутствующих данных;
- защищать намаз, сон, семью, работу и здоровье;
- снижать mental load утром, в течение дня и вечером;
- не терять данные после рестартов;
- работать 24/7 на VPS;
- не совершать действий без подтверждения владельца.

Главные инварианты:

> AI предлагает и структурирует. Владелец подтверждает. Кодовые валидаторы имеют приоритет над LLM.

> Неучтённое время не равно потерянному. Категорию `впустую` может поставить только владелец.

> Сон — защищённый ресурс и измеряемый показатель. Бот не предлагает сокращать сон ради размещения дополнительных задач.

---

## 2. Зафиксированные решения владельца

1. **Интерфейс:** Telegram-first, owner-only.
2. **Часовой пояс:** `Asia/Tashkent`.
3. **Намаз:** высший приоритет; Hanafi, `school=1`.
4. **STT:** OpenRouter, модель `openai/whisper-large-v3`.
5. **Язык STT:** `OPENROUTER_STT_LANGUAGE=ru`.
6. **Узбекский и смешанная речь:** best-effort; владелец всегда видит транскрипт и подтверждает результат.
7. **LLM:** OpenRouter, модель задаётся через config; архитектура не привязывается к одной модели.
8. **Расход API:** usage в БД, `/usage`, hard limits до подключения реального LLM.
9. **Google Calendar:** владельцу не нужен; активный GCal-код удаляется после read-only аудита.
10. **Деплой:** VPS, Docker Compose, production SQLite.
11. **Миграции:** только migration runner и `schema_migrations`; никаких новых production-изменений схемы через `create_all()`.
12. **Git:** один этап — один ограниченный commit; push и deployment выполняются отдельными шагами.
13. **Безопасность:** ключи только в `.env`/secrets; transcript, task text, API keys и audio/base64 не попадают в обычные логи.
14. **Дневные нормы:** вода, сон, каза-намаз, Коран, английский, занятия с детьми и другие цели поддерживают количественный прогресс.
15. **Расписание:** владелец хочет планировать все сутки, включая сон, намаз, работу, семью, обучение, дорогу, отдых и буфер.
16. **Check-in:** интервал настраивается, базово 60 или 120 минут; во время сна вопросы не отправляются.
17. **Факт:** `не помню` — допустимый честный ответ; бот записывает `неучтённое`, а не придумывает действие.
18. **Впустую:** только owner-selected категория.
19. **Буфер:** рекомендуемый настраиваемый резерв расписания — 10–15% бодрствующего времени.
20. **Исполнитель этапа:** выбирается владельцем перед каждой задачей по доступному лимиту и типу работы:
   - **Codex** сначала читает и строго соблюдает корневой `AGENTS.md`;
   - **Claude Code** сначала читает и строго соблюдает корневой `CLAUDE.md`;
   - инструкции одного исполнителя не подменяют инструкции другого;
   - архитектурный scope, acceptance criteria и запреты одинаковы независимо от выбранного кодера;
   - смена исполнителя между этапами допустима только после полного отчёта, commit и чистого working tree.

---

## 3. Фактическое текущее состояние

### Закрыто

- VPS production runtime и Docker-контур;
- SQLite + SQLAlchemy Async;
- migration runner и `schema_migrations`;
- pending capture drafts в БД через `CaptureDraftRecord`;
- voice temp lifecycle и безопасное удаление;
- OpenRouter STT;
- safe handling STT-ошибок;
- language A/B test; production оставлен на `ru`;
- `api_usage`, ORM и `ApiUsageService`;
- STT usage classification: success / error / no-HTTP-call;
- NaN/Infinity guard;
- Stage 18.6-P production deployment — PASS;
- production code HEAD на момент smoke: `fd23d87`;
- documentation и canonical-plan commits отправлены в `origin/main` до `41fd89c`.

### Следующий этап

```text
18.6-C0 — input_tokens/output_tokens
→ 18.6-C /usage
→ 18.6-D hard limits
→ PRE-18.7 / PRE-19 audits and fixes
→ 18.7 Daily Targets MVP
```

### Не подтверждено / требует аудита

- полное удаление Google Calendar;
- удаление мёртвого crisis-фильтра по `Task.user_id`;
- migration failure rollback test;
- Telegram nightly backup, retention и первый формальный restore;
- single-instance guard.

---

# 4. Итоговый маршрут

```text
18.6-C0  token-поля в api_usage
18.6-C   /usage
18.6-D   hard limits
PRE-18.7 GCal + crisis + migration failure-test audits/fixes
18.7     Daily Targets MVP
19       LLM Capture Intelligence
20       Daily Control 24/7
21       Task Lifecycle
22       Production hardening + основной DoD
23       Idea Vault — post-final module
24       Statistics & Forecasting — post-final, data-gated
```

Основной продукт считается завершённым после Stage 22 и выполнения Definition of Done. Stages 23–24 не двигают основной DoD.

---

# STAGE 18.6 — Закрытие STT usage

## 18.6-P — Production deployment и smoke — CLOSED / PRODUCTION PASS

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

### Фактический production-результат

- production code HEAD на момент smoke: `fd23d87`;
- backup production DB создан, SHA и размер совпали, backup integrity = `ok`;
- migration `20260614_2000_add_api_usage` применена ровно один раз;
- `PRAGMA integrity_check = ok`;
- voice smoke прошёл;
- confirmation draft появился и был отменён;
- тестовая задача не создана;
- одна voice-обработка создала ровно одну STT usage-строку;
- provider `openrouter`;
- model `openai/whisper-large-v3`;
- status `success`;
- container running, restart count `0`;
- transcript, secrets, Authorization и base64 не появились в INFO-логах или `api_usage`.

**Verdict:** PASS. Следующий этап — 18.6-C0.

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

---

# PRE-18.7 / PRE-STAGE 19 — Долги и архитектурный аудит

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

---

# STAGE 18.7 — Daily Targets MVP

## Цель

Дать владельцу постоянные количественные нормы суток без расписания, почасового журнала и обязательного LLM.

Примеры:

```text
Вода: 3 литра
Сон: 6 часов
Каза-намаз: 5
Коран: 20 листов
Английский: 30 минут
Коран с детьми: 30 минут
```

---

## 18.7.0 — Read-only audit

Перед схемой проверить существующие health, Quran, hydration, siyam, briefing и daily-plan модели, чтобы не создать дублирующий контур.

Результат аудита должен определить:

- какие показатели уже существуют;
- что можно переиспользовать;
- где нужен adapter;
- какие старые команды останутся совместимыми.

---

## 18.7.1 — Модель целей

Минимально две сущности.

### `daily_target_definitions`

```text
id
title
category
unit
target_value
target_mode
priority
weekdays_mask
active
created_at
updated_at
```

`target_mode`:

```text
minimum
exact
maximum
```

### `daily_target_progress`

```text
id
target_id
usage_date
planned_value_snapshot
actual_value
status
note
updated_at
```

Инварианты:

- unique `(target_id, usage_date)`;
- значения конечные и неотрицательные;
- единица определения не меняется для уже созданного daily snapshot;
- день считается по `Asia/Tashkent`;
- изменение нормы не переписывает историю прошлых дней.

---

## 18.7.2 — Поддерживаемые единицы v1

```text
count
ml
liters
minutes
hours
pages
```

Внутреннее хранение должно быть нормализовано: например, вода в ml, время в minutes.

---

## 18.7.3 — UX без LLM

Поддержать кнопки и явные шаблоны:

```text
Вода +500 мл
Коран +5 листов
Каза +1
Английский 20 минут
Сон 5 часов 40 минут
```

Если parser не уверен — ничего не обновлять, а показать выбор цели и значения.

Любое изменение прогресса owner-confirmed или идемпотентно применено из однозначной команды.

---

## 18.7.4 — Утро и вечер

Утром:

- показать активные цели дня;
- разрешить отключить или изменить цель только на текущий день;
- не превращать briefing в длинный список.

Вечером:

- цель / факт / процент;
- частичное выполнение;
- причина не обязательна;
- сон показывается отдельно как защищённый показатель;
- отсутствие отметки означает `нет данных`, а не `0`, если факт нельзя вывести надёжно.

---

## 18.7.5 — Сон

- бот хранит целевой и фактический сон;
- сон может пересекать полночь;
- бот не предлагает сокращать сон для размещения задач;
- если владелец задаёт короткую норму, система принимает настройку, но показывает нейтральное предупреждение о дефиците;
- медицинских диагнозов и автономных решений нет.

---

## 18.7.6 — Acceptance

- migration через runner;
- clean install и upgrade tests;
- timezone boundary;
- partial progress;
- duplicate command idempotency;
- target edit не меняет историю;
- morning/evening smoke;
- нет LLM call;
- нет пользовательских значений в INFO-логах;
- production backup/deploy/smoke отдельным шагом.

---

## Не входит в 18.7

- расписание по времени;
- check-in;
- activity journal;
- plan-vs-fact;
- прогнозирование;
- embeddings;
- автоматическое наказание за невыполнение.

---

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

Не добавлять `idea` до Stage 23.

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

---

# STAGE 20 — Daily Control 24/7

## Цель

Построить основной личный контур времени:

```text
цели суток
→ расписание по времени
→ check-in
→ фактический журнал
→ вечерний plan-vs-fact
```

Stage зависит от Stage 19: свободные текстовые и голосовые ответы структурируются через отдельный activity-parser поверх общего LLM provider layer.

---

## 20.0 — Product and domain audit

Проверить:

- существующий daily plan;
- briefing scheduler;
- prayer windows;
- family/sleep protections;
- task planned times;
- drafts;
- scheduler jobs;
- текущие команды `/today`, `/plan_tomorrow`, `/focus`, `/crisis`.

До реализации зафиксировать границы между:

- Task;
- planned Time Block;
- actual Activity Entry;
- Daily Target;
- Check-in.

---

## 20.1 — Модель расписания и факта

### `daily_schedules`

```text
id
usage_date
status
version
created_at
updated_at
confirmed_at
```

`version` в v1 — монотонный integer-счётчик текущей редакции расписания. Отдельная таблица истории версий не создаётся. Изменение подтверждённого расписания увеличивает `version`; исторический факт хранится в `activity_entries` и не переписывается.

### `time_blocks`

```text
id
schedule_id
start_at
end_at
title
category
block_type
flexibility
source_type
source_id nullable
status
created_at
updated_at
```

### `activity_entries`

```text
id
usage_date
start_at
end_at
title
category
source
confidence nullable
owner_confirmed
waste_marked_by_owner
created_at
updated_at
```

### `checkins`

```text
id
window_start
window_end
prompted_at
answered_at nullable
status
response_mode nullable
created_at
updated_at
```

Обязательные guards:

- `end_at > start_at`;
- aware datetimes;
- запрет двойного фактического учёта одного интервала;
- overlap detection;
- cross-midnight support;
- local day = `Asia/Tashkent`;
- `activity_entries.usage_date` определяется по локальной дате `start_at`;
- при формировании суточных отчётов interval, пересекающий полночь, обрезается по границам каждого локального дня и учитывается пропорционально в обоих днях без двойного счёта;
- idempotent callbacks;
- один check-in на одно окно.

---

## 20.2 — Построение плана суток

Порядок размещения:

1. обязательные намазы и protected windows;
2. защищённый сон;
3. фиксированная работа, встречи и дорога;
4. семья;
5. Daily Targets, которым нужен временной блок;
6. задачи;
7. отдых;
8. настраиваемый буфер 10–15%.

План может покрывать все 24 часа, включая сон. При этом пользователь вправе оставить свободные или неопределённые интервалы.

Бот:

- не допускает overlaps;
- не помещает задачи в прошлое;
- прогоняет task slots через `ContextValidator`;
- не изменяет расписание без подтверждения;
- при перегрузке показывает, что всё не помещается, а не сокращает сон или намаз.

---

## 20.3 — Утреннее и вечернее планирование

Вечером:

- взять фиксированные события и задачи;
- предложить план завтра;
- показать перегрузку;
- запросить подтверждение.

Утром:

- показать компактный график;
- разрешить точечные изменения;
- не пересобирать подтверждённый день автономно.

### Общий бюджет утреннего брифинга

Утреннее сообщение объединяет задачи, Daily Targets и расписание, поэтому действует единый UX-лимит:

- основной экран — не более 15 содержательных строк по умолчанию;
- показать только protected times, 3 главных приоритета, ближайший блок и краткий прогресс целей;
- полный график открывается кнопкой `Расписание`;
- полный список норм — кнопкой `Цели`;
- остальные задачи — кнопкой `Все задачи`;
- превышение лимита не ведёт к отправке нескольких длинных сообщений подряд;
- лимит конфигурируемый, но его увеличение требует owner approval.

---

## 20.4 — Check-in scheduler

Настройки:

```text
enabled
interval_minutes: 60 | 120
quiet_hours
wake_window
defer_minutes
```

Check-in не отправляется:

- во время сна;
- в prayer protected interval;
- если предыдущий check-in ещё открыт и не истёк;
- чаще установленного интервала.

Пример:

```text
Проверка 10:00–12:00

По плану:
• Английский — 30 мин
• Договоры — 90 мин

Отмечено:
• Английский — 30 мин

Чем был занят оставшийся час?
```

---

## 20.5 — Rules-first ответы

Кнопки без LLM:

```text
Всё по плану
Работа
Дорога
Семья
Намаз
Обучение
Отдых
Не помню
Ответить голосом
Ответить текстом
Отложить
```

- `Всё по плану` создаёт фактические entries только после проверки окна и отсутствия ранее записанного факта;
- категория-кнопка создаёт простой owner-confirmed entry;
- `Не помню` создаёт `unaccounted`;
- `Отложить` переносит вопрос один раз в пределах дня;
- кнопочные пути не вызывают LLM.

---

## 20.6 — Свободный текст и голос

Stage 19 provider layer переиспользуется, но schema отдельная:

```json
{
  "entries": [
    {
      "title": "Совещание с директором",
      "category": "work",
      "start_at": "ISO datetime|null",
      "end_at": "ISO datetime|null",
      "duration_minutes": 60,
      "confidence": 0.88
    }
  ],
  "needs_clarification": false
}
```

Правила:

- максимум один основной LLM-вызов на свободный ответ;
- hard limit проверяется до вызова;
- transcript — недоверенные данные;
- no autonomous save;
- владелец видит предложение и подтверждает;
- если времена не указаны, использовать только check-in window и спросить распределение;
- не выдумывать точность;
- invalid JSON → ручной fallback, не второй repair-call.

---

## 20.7 — `не помню`, неучтённое и `впустую`

- `не помню` сохраняет честное `unaccounted`;
- незаписанный интервал остаётся `нет данных`;
- бот никогда сам не маркирует время `waste`;
- `waste_marked_by_owner=true` появляется только после явного выбора владельца;
- отчёт отдельно показывает отдых и owner-marked waste.

---

## 20.8 — Изменения вне плана

Владелец может сообщить:

```text
С 11 до 12 был у директора
Начал договоры
Закончил
Сейчас еду на завод
Приехал
```

Для start/stop допускается только один активный таймер на владельца.

### Защита от забытого таймера

- после `OPEN_TIMER_REVIEW_MINUTES` (по умолчанию 120 минут) бот задаёт ненавязчивый вопрос: продолжить / завершить сейчас / указать фактическое время;
- открытый таймер не может молча пройти через начало защищённого сна;
- при наступлении sleep window таймер переводится в `needs_review`, а не закрывается с выдуманным временем;
- hard maximum открытого таймера — конфигурируемый, по умолчанию 8 часов;
- при hard maximum таймер ставится на паузу и требует решения владельца;
- после рестарта активный таймер восстанавливается из БД;
- вечерний closeout не завершается, пока у открытого таймера нет решения: завершить / исправить / `не помню`;
- никакое автоматическое завершение не маркирует время `впустую`.

Любое изменение плана:

- не переписывает исторический факт;
- создаёт перенос/изменение версии;
- требует подтверждение;
- сохраняет причину опционально.

---

## 20.9 — Вечерний plan-vs-fact

Отчёт показывает:

### Daily Targets

- цель;
- факт;
- частичное выполнение.

### Время

- сон;
- намаз/ибадат;
- работа;
- семья;
- обучение;
- здоровье;
- дорога;
- отдых;
- полезное вне плана;
- unaccounted;
- waste — только owner-marked.

### План

- выполнено по плану;
- частично;
- перенесено;
- пропущено;
- полезное вне плана;
- расхождение planned vs actual durations.

Никакого морального оценивания.

---

## 20.10 — Cost and privacy

- кнопки и типовые команды — без LLM;
- free-form — один LLM call;
- `/usage` показывает расходы Daily Control как LLM usage;
- prompt/response/transcript/activity text не сохраняются в `api_usage`;
- activity text не логируется в INFO;
- check-in notifications не содержат лишние чувствительные детали на lock screen, если включён privacy mode.

---

## 20.11 — Acceptance

- schedule build with prayer/sleep/buffer;
- no overlap;
- cross-midnight sleep;
- past-time rejection;
- hourly and 2-hour check-in;
- quiet hours;
- duplicate callback no-op;
- `не помню`;
- buttons produce zero LLM calls;
- free voice produces max one LLM call;
- hard limit fallback;
- owner confirmation;
- plan-vs-fact totals do not double count;
- total accounted + unaccounted does not exceed day window;
- restart recovery of open check-ins/timers;
- forgotten-timer review at 120 minutes;
- sleep-window auto-pause to `needs_review`;
- morning briefing respects the shared 15-line budget;
- cross-midnight activity is attributed to both local days without double count;
- production smoke over at least 3 real days before Stage close.

---

## Не входит в Stage 20

- predictive scheduling;
- automatic optimization from historical averages;
- embeddings;
- autonomous schedule changes;
- punishment/scoring;
- automatic classification as wasted time.

---

---

# STAGE 21 — Task Lifecycle Semantics

## 21.0 — Read-only domain audit

До миграции проверить существующие:

- statuses;
- callbacks;
- alert cancellation;
- daily plan behavior;
- evening summary;
- boss loop.

Не добавлять новые статусы, пока не определена совместимость со старыми строками БД.

---

## 21.1 — Статусы и переходы

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

## 21.2 — Postpone model

Рекомендуется не только менять status, но сохранять историю переноса минимально:

- old planned time;
- new planned time;
- postponed_at.

Если отдельная history-таблица избыточна, минимум — поля на Task, позволяющие отличить перенос от обычного редактирования.

Все новые времена проходят ContextValidator.

---

## 21.3 — Telegram actions

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

## 21.4 — Evening closeout

Вечером показывать только нерешённые элементы.

UX:

- по одной задаче;
- массовое «перенести подходящие на завтра»;
- Later;
- skip;
- cancel.

Перед массовым действием бот показывает список и требует подтверждение.

---

## 21.5 — Boss alert lifecycle

При `done/cancelled/skipped/postponed` текущий alert-cycle должен корректно остановиться или пересчитаться.

Проверить:

- scheduled jobs;
- stale callbacks;
- restart recovery;
- duplicate alerts.

---

---

# STAGE 22 — Production hardening и финализация

## 22.1 — Telegram backup и проверяемый restore

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
- второй раз в финальном Stage 22 перед DoD.

---

## 22.2 — Single-instance and health

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

## 22.3 — Weekly review

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

## 22.4 — GCal final cleanup

После удаления runtime-кода решить судьбу старых таблиц:

- оставить архивно;
- экспортировать;
- удалить отдельной migration.

Дроп разрешён только после backup и проверки, что runtime больше не читает таблицы.

---

## 22.5 — Documentation

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

## 22.6 — Security and privacy audit

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

## 22.7 — Observation window

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

---

# DEFINITION OF DONE — основной продукт

Проект считается завершённым, когда подтверждены все пункты:

1. Production работает на VPS минимум 14 последовательных дней стабильно по единому observation-критерию Stage 22.7.
2. Telegram backup приходит владельцу; restore дважды прошёл формальный критерий Stage 22.1: temp DB, integrity `ok`, совпадающие row counts и migration versions, успешный isolated application smoke и задокументированный runbook.
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
14. Daily Targets работает: постоянные нормы, частичный прогресс, утреннее отображение и вечерний итог.
15. Daily Control работает: расписание, check-in, фактический журнал, `не помню`, plan-vs-fact и owner-only маркировка `впустую`.
16. Task lifecycle согласован с alerts и evening closeout.
17. README позволяет поднять проект на чистом VPS.
18. Логи и БД не содержат запрещённых API payload данных.
19. Сон учитывается как защищённый показатель; бот не предлагает сокращать сон ради размещения задач.
20. Нет открытых BLOCKER/HIGH дефектов.
21. Известные MEDIUM/LOW долги перечислены в backlog с решением владельца.

---

---

# STAGE 23 — Idea Vault / Инкубатор идей

## Статус

Post-final функциональный модуль. Начинается только после основного DoD, который фиксируется после Stage 22.

Однако саму пользовательскую потребность нужно сохранить уже сейчас в backlog.

## 23.0 — Product discovery

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

## 23.1 — Минимальная модель

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

## 23.2 — Capture UX

Явные команды:

```text
/idea <текст>
/ideas
```

LLM не нужен для `/idea`.

При обычном capture тип `idea` добавляется в classifier только на Stage 23.

Граница:

- task — действие;
- later — действие без текущего срока;
- idea — долгоживущий объект развития.

При сомнении бот спрашивает владельца.

---

## 23.3 — Карточка идеи

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

## 23.4 — Review engine

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

## 23.5 — Idea → Task

Создание обычной task из next step:

- owner confirmation;
- ContextValidator;
- ссылка на source idea.

В v1 допустимо поле `source_idea_id` в Task отдельной migration. Это надёжнее свободной текстовой пометки, если связь реально нужна.

---

## 23.6 — Не делать по умолчанию

- embeddings;
- vector DB;
- автоматическая группировка;
- шесть таблиц;
- сложная milestone history;
- автономное продвижение stage.

Эти функции появляются только после доказанной пользовательской потребности.

---

---

# STAGE 24 — Statistics & Forecasting (post-final, data-gated)

## Статус

Отдельный post-final модуль. Не является условием основного DoD.

## 24.0 — Data quality gate

Любая рекомендация разрешена только если:

- минимум 10 сопоставимых завершённых записей;
- фактическое время заполнено минимум в 70% релевантных случаев;
- нет критических overlaps/double counts;
- выборка не смешивает несопоставимые типы работы;
- владелец видит размер выборки.

Если gate не пройден — статистика показывается описательно, без советов.

---

## 24.1 — Базовые отчёты

- planned vs actual;
- среднее и медиана;
- диапазон;
- completion rate;
- unaccounted rate;
- частота переносов;
- Daily Targets trends;
- сон и субъективная продуктивность без медицинских выводов.

---

## 24.2 — Рекомендации

Форма только как предложение:

```text
По 12 прошлым случаям эта работа занимала 80–95 минут.
Предложить 90 минут?
```

Запрещено:

- выдавать прогноз как истину;
- автоматически менять будущие планы;
- строить совет на дырявых данных;
- сокращать сон/намаз ради оптимизации.

---

## 24.3 — Не делать по умолчанию

- ML-модели ради ML;
- vector DB;
- скрытый productivity score;
- сравнение владельца с другими людьми;
- автоматическое моральное оценивание.

---

---

# ПОРЯДОК ИСПОЛНЕНИЯ

```text
A. 18.6-C0 — token-поля
B. 18.6-C — /usage
C. 18.6-D — hard limits
D. PRE-18.7 / PRE-19 audits and fixes
E. 18.7 — Daily Targets MVP
F. 19 — LLM Capture Intelligence
G. 20 — Daily Control 24/7
H. 21 — Task Lifecycle
I. 22 — Production hardening
J. 14-дневное observation window + второй restore
K. Подтвердить основной Definition of Done
L. 23 — Idea Vault
M. 24 — Statistics & Forecasting при прохождении data-quality gate
```

Перед каждым подэтапом владелец явно выбирает исполнителя:

```text
Codex → корневой AGENTS.md
Claude Code → корневой CLAUDE.md
```

Выбор зависит от доступного лимита и характера задачи. Переход к другому исполнителю допускается только при чистом working tree и наличии полного отчёта предыдущего этапа.

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

Нельзя объединять несколько рискованных migrations или production-изменений в одну задачу.

---

# ИЗВЕСТНЫЕ ТЕКУЩИЕ ДОЛГИ

1. GCal status — needs audit.
2. Crisis `Task.user_id` — needs audit.
3. Migration failure rollback test — проверить/добавить до новых domain migrations.
4. `_normalize_usage_float` принимает bool как число — LOW, отдельный focused commit.
5. `isinstance(OpenRouterSTTProvider)` в usage flow — заменить metadata/capability при следующем provider touch.
6. STT `language=ru` ухудшает узбекский — честное product limitation.
7. Usage durability зависит от outer transaction commit — документировать.
8. Token columns для LLM — обязательный ближайший Stage 18.6-C0.
9. Telegram nightly backup и первый formal restore — OPEN/HIGH до доказательств.
10. Single-instance guard — подтвердить доказательством.
11. Новый v8.1 должен заменить v7.1 как canonical plan только отдельным documentation commit после независимого verdict.
12. Ни один project-plan файл не должен жёстко объявлять Codex или Claude Code единственным постоянным исполнителем.

---

# ЗАПРЕТЫ ДЛЯ ОСТАВШЕГОСЯ ПРОЕКТА

- Не менять production DB вручную.
- Не использовать `docker compose down -v`.
- Не удалять volumes.
- Не делать force push.
- Не хранить secrets в Git.
- Не логировать transcript, task/activity text или API payload.
- Не позволять LLM обходить owner confirmation.
- Не позволять LLM обходить prayer/time/sleep validators.
- Не называть время `впустую` без явного решения владельца.
- Не вычитать задачи из сна для «оптимизации».
- Не начинать predictive analytics до data-quality gate.
- Не переносить основной DoD после Stage 22.
- Не смешивать инструкции Codex (`AGENTS.md`) и Claude Code (`CLAUDE.md`).
- Не объявлять Stage закрытым только по наличию кода: нужен тест и, где применимо, production smoke.
