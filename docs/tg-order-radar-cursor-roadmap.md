# TG Order Radar — пошаговая реализация в Cursor

## Как пользоваться

1. Создай пустую папку `tg-order-radar`.
2. Внутри создай папку `docs`.
3. Положи исходную спецификацию в `docs/tg-order-radar-spec.md`.
4. Положи этот файл в `docs/tg-order-radar-cursor-roadmap.md`.
5. Открой корневую папку проекта в Cursor.
6. Запускай этапы строго по порядку.
7. После каждого этапа запускай тесты и Docker Compose.
8. Не переходи к следующему этапу, пока критерии готовности текущего не выполнены.

---

## Главный промпт для Cursor

```text
Ты — senior Python backend/DevOps-разработчик, специализирующийся на FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, Redis, Celery, Telethon, aiogram и Docker.

В репозитории находятся:
- docs/tg-order-radar-spec.md — основной источник требований;
- docs/tg-order-radar-cursor-roadmap.md — порядок реализации.

Правила работы:
1. Сначала полностью изучи оба документа.
2. Не пытайся реализовать весь проект за один раз.
3. Выполняй только тот этап, который я укажу.
4. Перед изменениями перечисляй, какие файлы создашь или изменишь.
5. Не используй заглушки, псевдокод, TODO вместо обязательной функциональности текущего этапа.
6. Соблюдай Python 3.12, строгую типизацию и async-подход там, где это предусмотрено архитектурой.
7. Используй SQLAlchemy 2.0 typed declarative mappings и Pydantic v2.
8. Все настройки получай через environment variables; реальные секреты никогда не добавляй в репозиторий.
9. Все операции обработки сообщений проектируй идемпотентными.
10. Система должна работать только с публичными Telegram-каналами и группами. Приватные ссылки, обход ограничений, CAPTCHA, антибот-защиты и массовые рассылки запрещены.
11. Для каждого этапа добавляй необходимые unit/integration-тесты.
12. После изменений обязательно запускай доступные проверки: форматирование, lint, type-check, тесты и сборку контейнеров.
13. Не изменяй уже работающую архитектуру без явной необходимости. Если обнаружено противоречие в ТЗ, сначала опиши его и выбери наиболее безопасный вариант.
14. В конце ответа покажи:
   - что реализовано;
   - какие файлы изменены;
   - какие команды проверки выполнены;
   - результаты проверок;
   - что осталось до завершения этапа.

Сейчас не пиши код. Подтверди, что изучил документы, кратко опиши архитектуру и дождись номера этапа.
```

---

# Часть 1. Рабочий MVP

## Этап 0. Проверка окружения и фиксация решений

### Промпт

```text
Выполни этап 0 проекта TG Order Radar.

Изучи docs/tg-order-radar-spec.md и текущий репозиторий. Код приложения пока не создавай.

Нужно:
1. Проверить наличие и версии Python, Docker, Docker Compose, Git и Node.js.
2. Составить ADR-документ docs/adr/0001-mvp-scope.md.
3. Зафиксировать состав MVP:
   - ручное добавление публичных Telegram-источников;
   - проверка публичности;
   - polling/backfill сообщений не глубже 7 дней плюс небольшой буфер;
   - нормализация текста;
   - keyword/negative keyword matcher;
   - rules-классификация;
   - извлечение типа проекта, бюджета, срока и контактов;
   - relevance score;
   - базовая дедупликация по source/message id и content hash;
   - REST API;
   - Telegram-бот уведомлений;
   - Docker Compose и тесты.
4. Явно исключить из первой версии: Next.js, ML, LLM, pgvector, импорт из внешних каталогов, мультиаккаунт, Traefik, Grafana и production-деплой.
5. Составить короткий список рисков и решений, которые нельзя откладывать: идемпотентность, Alembic, tg_peer_id, защита session-файла, correlation_id.

Не создавай прикладной код. В конце покажи результат проверки окружения и содержимое ADR.
```

### Готово, когда
- окружение проверено;
- MVP зафиксирован;
- нет попытки реализовать весь production сразу.

---

## Этап 1. Каркас монорепозитория и локальная инфраструктура

### Промпт

```text
Выполни этап 1 проекта TG Order Radar: каркас репозитория и локальная инфраструктура.

Создай production-oriented, но минимальный каркас Python-монорепозитория для MVP.

Требования:
1. Используй Python 3.12 и современный pyproject.toml.
2. Создай пакеты/модули:
   - app/core
   - app/db
   - app/models
   - app/schemas
   - app/api
   - app/services
   - app/workers
   - app/collector
   - app/bot
   - tests/unit
   - tests/integration
3. Добавь FastAPI-приложение с endpoints:
   - GET /health/live
   - GET /health/ready
4. Добавь конфигурацию через pydantic-settings.
5. Добавь PostgreSQL 16 и Redis 7 в docker-compose.yml.
6. Добавь контейнер API и отдельные placeholders-контейнеры collector, worker и bot, которые используют реальный общий образ, но пока запускают безопасные команды без бизнес-логики.
7. Добавь .env.example без реальных секретов.
8. Добавь Makefile или Taskfile с командами setup, up, down, logs, lint, format, typecheck, test.
9. Настрой Ruff, MyPy и Pytest.
10. Добавь структурированное логирование и middleware correlation_id.
11. Добавь README с командами запуска.
12. Добавь .gitignore для .env, __pycache__, Telegram session-файлов, IDE и временных данных.

Не реализуй модели предметной области, Telegram Collector и Celery-задачи.

После реализации запусти lint, typecheck, тесты и docker compose config. Исправь найденные ошибки.
```

### Готово, когда
- `docker compose up -d postgres redis api` работает;
- `/health/live` возвращает 200;
- проверки зелёные.

---

## Этап 2. База данных, модели и Alembic

### Промпт

```text
Выполни этап 2 проекта TG Order Radar: база данных и миграции.

Основывайся на разделе 11 docs/tg-order-radar-spec.md, но реализуй только таблицы, необходимые MVP.

Обязательно создай SQLAlchemy 2.0 async-модели и Alembic-миграции для:
- users;
- telegram_accounts;
- telegram_sources;
- messages;
- keywords;
- negative_keywords;
- message_entities;
- classifications;
- orders;
- duplicate_groups или эквивалентной связи для базовой дедупликации;
- notification_deliveries;
- favorites;
- audit_logs.

Требования:
1. UUID primary keys, где это уместно.
2. У telegram_sources должен быть стабильный tg_peer_id; username не является главным идентификатором.
3. У messages должен быть unique constraint по source_id + tg_message_id.
4. Храни raw payload в JSONB только там, где это оправдано.
5. Добавь created_at, updated_at и необходимые индексы.
6. Заложи мягкое удаление сообщений.
7. Заложи статусную модель order: new, viewed, contacted, irrelevant, archived.
8. Реализуй async engine/session factory.
9. Добавь readiness-проверку БД и Redis.
10. Добавь seed-команду для базовых positive/negative keywords.
11. Добавь integration-тест миграции с чистой БД.

Не реализуй API CRUD и Telegram Collector.

После реализации выполни alembic upgrade head с чистой БД, seed и тесты.
```

### Готово, когда
- миграции поднимаются с нуля;
- повторный запуск не ломает БД;
- уникальные ограничения протестированы.

---

## Этап 3. CRUD источников и базовый API

### Промпт

```text
Выполни этап 3 проекта TG Order Radar: CRUD публичных Telegram-источников.

Реализуй API /api/v1/sources в соответствии с FR-1 и релевантными частями раздела 12.

Нужно:
1. Нормализовать @username, t.me/username, https://t.me/username и ссылки на конкретный пост.
2. Отклонять t.me/joinchat/... и t.me/+... с кодом SOURCE_NOT_PUBLIC.
3. Отклонять явно невалидные usernames.
4. Создавать источник со статусом pending_validation.
5. Обеспечить защиту от дублей по нормализованному username, а после валидации — по tg_peer_id.
6. Реализовать list/get/update-enable/delete-or-disable endpoints.
7. Добавить единый формат API-ошибок.
8. Добавить пагинацию.
9. Добавить audit log для изменений.
10. Добавить unit и API integration tests.

На этом этапе не подключай Telethon и не утверждай, что источник реально существует. Реальная проверка будет на следующем этапе.
```

### Готово, когда
- формы ссылок нормализуются;
- приватные ссылки отклоняются;
- дубли не создаются.

---

## Этап 4. Telethon-авторизация и валидация публичных источников

### Промпт

```text
Выполни этап 4 проекта TG Order Radar: Telethon-клиент и проверка публичности источников.

Требования безопасности:
- только чтение публичных каналов/групп;
- никаких рассылок;
- никаких приватных чатов;
- никаких обходов FloodWait или ограничений Telegram;
- session-файл исключён из Git и хранится в выделенном volume;
- секреты только через env.

Реализуй:
1. Отдельный модуль Telethon client factory.
2. CLI-команду интерактивной первичной авторизации аккаунта.
3. Сервис validate_source(source_id).
4. Проверку entity.username, типа сущности и доступности чтения.
5. Сохранение tg_peer_id, title, username, participants_count при доступности, is_public, access_status и last_checked_at.
6. Обработку UsernameNotOccupiedError, ChannelPrivateError, FloodWaitError, сетевых и RPC-ошибок.
7. При FloodWait не делать обход: записать pause_until и корректно перепланировать задачу.
8. Endpoint запуска повторной валидации.
9. Моки Telethon для unit-тестов и один opt-in integration test для реального публичного канала, который по умолчанию пропускается без env-переменных.

Не реализуй сбор сообщений.
```

### Готово, когда
- публичный источник получает tg_peer_id и статус ok;
- приватный/несуществующий корректно помечается;
- FloodWait не приводит к циклическим повторным вызовам.

---

## Этап 5. Celery, очереди, retry и идемпотентность

### Промпт

```text
Выполни этап 5 проекта TG Order Radar: фоновые задачи Celery.

Реализуй:
1. Celery app с Redis broker/backend.
2. Очереди source_validation, telegram_collection, message_processing, classification, duplicate_detection и notifications.
3. Маршрутизацию задач по очередям.
4. acks_late, reject_on_worker_lost, ограниченные retry с exponential backoff и jitter.
5. Механизм dead-letter: после исчерпания retries сохранять failed task/event в БД с причиной и correlation_id.
6. Идемпотентные task entrypoints.
7. Периодическую задачу валидации pending-источников.
8. Периодическую maintenance-задачу для архивации заказов старше 7 дней.
9. Health/readiness worker-зависимостей.
10. Тесты retry, повторной доставки и отсутствия дублей.

Не реализуй бизнес-обработку текста и уведомления.
```

### Готово, когда
- повтор задачи не создаёт повторные записи;
- исчерпанные задачи видны в dead-letter storage;
- worker стартует через Compose.

---

## Этап 6. Сбор и backfill сообщений

### Промпт

```text
Выполни этап 6 проекта TG Order Radar: Telegram Collector.

Реализуй polling/backfill MVP для публичных источников со статусом ok.

Нужно:
1. Получать новые сообщения после last_seen_message_id.
2. При первом подключении собирать историю только за последние 7 дней плюс буфер 1 день.
3. Сохранять raw message идемпотентно по source_id + tg_message_id.
4. Сохранять published_at в UTC, collected_at, edited_at, forward original date при доступности, text/caption, views/replies при доступности и прямую ссылку на оригинал.
5. После успешного сохранения ставить message_id в message_processing.
6. Обновлять offset только после успешной фиксации данных.
7. Обрабатывать edited messages и soft-delete deleted messages.
8. Уважать FloodWait и pause_until аккаунта.
9. Добавить distributed lease/lock источника, чтобы два collector-процесса не собирали один источник одновременно.
10. Добавить тесты на повторный сбор, gap, edited, deleted и FloodWait.

Не реализуй realtime event subscription и мультиаккаунтную ротацию.
```

### Готово, когда
- повторный backfill не создаёт дубли;
- offset не перескакивает при ошибке;
- в messages появляется корректная ссылка на оригинал.

---

## Этап 7. Нормализация, словари и извлечение сущностей

### Промпт

```text
Выполни этап 7 проекта TG Order Radar: первичная обработка сообщений.

Основывайся на разделах 8.1–8.9 спецификации.

Реализуй чистые, хорошо тестируемые сервисы:
1. Нормализация Unicode, пробелов, переносов и регистра без потери исходного текста.
2. Определение языка с фокусом на русский.
3. Keyword matcher с границами слов.
4. Negative keyword matcher с приоритетом отрицательных правил.
5. Поддержку phrase и regex keywords с предварительной валидацией regex.
6. Опциональный fuzzy match с расстоянием Левенштейна <=1 только для слов длиной >=6.
7. Извлечение project_type.
8. Извлечение бюджета: сумма, диапазон, валюта, negotiable.
9. Извлечение сроков.
10. Извлечение контактов: Telegram username, телефон, email, URL.
11. Сохранение message_entities и keyword hits.
12. passed_prefilter=false для пустого текста или явного negative match.
13. Redis-кэш словарей и безопасную hot reload-инвалидацию.
14. Набор параметризованных тестов на реальные русскоязычные формулировки заказов и рекламы исполнителей.

Не подключай ML или внешнюю LLM.
```

### Готово, когда
- реальные заказы проходят prefilter;
- объявления «делаю сайты» в основном отсекаются;
- сущности корректно сохраняются.

---

## Этап 8. Rules-классификация и Relevance Score

### Промпт

```text
Выполни этап 8 проекта TG Order Radar: rules-классификация и оценка релевантности.

Реализуй классы:
- order;
- vacancy;
- service_ad;
- resume;
- partnership;
- spam;
- discussion;
- irrelevant.

Требования:
1. Используй детерминированные правила из спецификации и конфигурируемые веса.
2. Сохраняй label, confidence, method=rules и объяснение сработавших факторов.
3. При низкой уверенности помечай manual_review, но не отправляй уведомление.
4. Реализуй Relevance Score строго по разделу 9 с нормализацией 0..100.
5. Учитывай свежесть <=7 дней.
6. Создавай order только для подходящего класса и порога relevance.
7. Сохраняй extracted summary, project_type, budget, deadline, contacts, source/message relation и message_url.
8. Все пороги вынеси в settings.
9. Добавь regression dataset в tests/fixtures с минимум 50 примерами: реальные заказы и негативные классы.
10. Выведи precision на тестовом датасете; не утверждай production-качество по маленькой выборке.

Не добавляй ML/LLM.
```

### Готово, когда
- order создаётся только для свежего сообщения;
- explainability показывает причины решения;
- тестовый набор не деградирует при следующих изменениях.

---

## Этап 9. Базовая дедупликация

### Промпт

```text
Выполни этап 9 проекта TG Order Radar: базовая дедупликация MVP.

Реализуй уровни:
1. Точный дубль source_id + tg_message_id блокируется ограничением БД.
2. Нормализованный content_hash для одинакового текста.
3. Дополнительный fingerprint из нормализованного текста, контакта, бюджета и project_type.
4. Окно сравнения ограничь последними 7 днями.
5. Выбирай canonical order по правилам спецификации: наиболее ранний/полный/релевантный экземпляр, зафиксируй детерминированный порядок.
6. Дубли связывай с duplicate_group и canonical_order_id.
7. Только canonical order может перейти в очередь notifications.
8. Ручное изменение duplicate/canonical должно попадать в audit log.
9. Добавь тест: один и тот же заказ в нескольких каналах создаёт одно уведомляемое canonical order.

Не используй embeddings и pgvector.
```

### Готово, когда
- одинаковые сообщения из разных источников группируются;
- уведомление возможно только одно.

---

## Этап 10. Orders API, статусы, избранное и экспорт

### Промпт

```text
Выполни этап 10 проекта TG Order Radar: рабочий REST API заказов.

Реализуй релевантную MVP-часть /api/v1 из раздела 12:
1. GET /orders с фильтрами date, budget, project_type, relevance, source, status и q.
2. GET /orders/{id}.
3. Изменение статуса по state-machine new -> viewed/contacted/irrelevant/archived с допустимыми переходами.
4. Optimistic locking через version или updated_at.
5. Favorites: add/remove/list, идемпотентное добавление.
6. CRUD keywords и negative keywords с Redis hot reload.
7. Statistics summary для количества заказов, источников и классов.
8. CSV и JSON экспорт для ограниченной выборки; XLSX можно отложить до production-этапа.
9. Полнотекстовый поиск PostgreSQL или безопасный ILIKE для первой версии с индексами, соответствующими выбранному решению.
10. Единые ошибки и audit logs.
11. OpenAPI descriptions и API tests.

Для MVP реализуй простой API-key/JWT auth с ролями admin/operator/viewer, не добавляя внешний OAuth.
```

### Готово, когда
- лента заказов фильтруется;
- статусы и избранное работают;
- роли ограничивают изменения.

---

## Этап 11. Telegram-бот уведомлений

### Промпт

```text
Выполни этап 11 проекта TG Order Radar: aiogram 3 Telegram-бот.

Реализуй:
1. Отдельный bot process.
2. Отправку только canonical orders, свежих <=7 дней и relevance >= configured threshold.
3. Карточку: источник, дата, тип, краткое описание, бюджет, срок, контакт, relevance score и ссылка на оригинал.
4. Inline-кнопки: Открыть, В избранное, Связался, Неактуально.
5. Callback handlers с проверкой прав пользователя.
6. notification_deliveries с unique constraint, исключающим повторную отправку одному получателю.
7. Rate limiting и retry для Bot API без спама.
8. HTML/Markdown escaping пользовательского контента.
9. Настройку списка разрешённых Telegram user IDs через БД/env для MVP.
10. Тесты карточек, callbacks и повторной доставки.

Используй polling локально. Webhook оставь для production-этапа.
```

### Готово, когда
- новый canonical order вызывает одно уведомление;
- повтор задачи не отправляет вторую карточку;
- callbacks изменяют данные в БД.

---

## Этап 12. Сквозной MVP и исправление ошибок

### Промпт

```text
Выполни этап 12 проекта TG Order Radar: сквозная проверка MVP.

Не добавляй новые крупные функции. Проведи аудит и доведи существующий MVP до рабочего состояния.

Проверь сценарий:
1. Admin добавляет публичный источник.
2. Источник валидируется через Telethon.
3. Collector получает сообщения за последние 7 дней.
4. Сообщение сохраняется идемпотентно.
5. Pipeline нормализует текст, применяет словари, извлекает сущности, классифицирует и рассчитывает relevance.
6. Дубликаты объединяются.
7. Создаётся canonical order.
8. Бот отправляет ровно одно уведомление.
9. Кнопки меняют статус/избранное.
10. Заказ виден через API и фильтры.

Нужно:
- добавить e2e-тест с моками Telegram/Bot API;
- добавить opt-in smoke test с реальным публичным источником;
- проверить падение worker между получением и подтверждением задачи;
- проверить повторную доставку;
- проверить сообщение старше 7 дней;
- проверить приватную ссылку;
- проверить дубликат в двух источниках;
- обновить README пошаговым запуском;
- создать docs/troubleshooting.md;
- удалить неиспользуемый код и зависимости;
- запустить полный lint, mypy, test и docker compose build.

В конце составь честный список известных ограничений MVP.
```

### Готово, когда
- полный сценарий проходит;
- проект запускается по README;
- известные ограничения задокументированы.

---

# Часть 2. После рабочего MVP

Следующие этапы выполняй только после стабильной работы этапов 0–12.

## Этап 13. Минимальная админ-панель

Next.js + TypeScript: Orders, Sources, Keywords, Statistics, login, роли, фильтры, статусы и избранное. Не внедрять дизайн раньше работающего API.

## Этап 14. Ручная модерация и датасет

Очередь manual_review, подтверждение/отклонение, исправление полей, audit log, экспорт размеченных данных.

## Этап 15. Activity Score

Реализовать раздел 7, периодический расчёт и приоритизацию активных источников.

## Этап 16. ML-классификатор

TF-IDF + Logistic Regression/LinearSVC, versioned model artifact, holdout dataset, метрики precision/recall, rules fallback.

## Этап 17. Semantic dedup

sentence-transformers + pgvector, только после накопления данных и измерения качества базового дедупа.

## Этап 18. Пользовательские подписки и фильтры уведомлений

Порог relevance, типы проектов, бюджет, источники, quiet hours, защита от повторов.

## Этап 19. Monitoring

Prometheus, Grafana, Sentry, alert rules, collector lag, queue depth, classification latency, failed tasks.

## Этап 20. Production deploy

Traefik/TLS, VPS hardening, encrypted secrets/session storage, PostgreSQL backup + restore test, CI/CD, runbooks.

## Этап 21. Масштабирование

Мультиаккаунт только для распределения законной нагрузки чтения, leases, conservative limits, никакого обхода FloodWait; партиционирование messages и retention jobs.

---

# Команда проверки после каждого этапа

Перед переходом дальше проси Cursor выполнить эквивалент:

```bash
ruff format --check .
ruff check .
mypy app
pytest -q
docker compose config
docker compose build
```

После этапа 2 дополнительно:

```bash
docker compose up -d postgres redis
alembic upgrade head
```

---

# Как общаться с Cursor после ошибки

```text
Не добавляй обходной костыль. Найди первопричину ошибки, объясни её простыми словами, исправь минимально необходимый код и добавь regression test, который падал бы до исправления. Затем снова запусти все проверки текущего этапа.
```

# Главное правило

Не проси Cursor: «Сделай весь production-ready проект по ТЗ».

Проси: «Выполни только этап N. Не переходи к следующему этапу. Заверши проверки и покажи результат».
