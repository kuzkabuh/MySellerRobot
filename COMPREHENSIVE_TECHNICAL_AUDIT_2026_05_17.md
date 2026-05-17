# Комплексный технический аудит MP Control от 17.05.2026

## Краткий итог

Проведён дополнительный аудит критичных production-зон проекта: синхронизация остатков,
интеграции Wildberries/Ozon, сохранение карточек товаров, FBS-уведомления, WEB-навигация,
миграции и тесты.

Главный исправленный риск: остатки могли отображаться нулевыми не потому, что маркетплейс
вернул `0`, а из-за неполной интеграции и некорректного разбора ответов API.

## Найдено и исправлено

### Wildberries

- FBS-остатки складов продавца не читались через `POST /api/v3/stocks/{warehouseId}`.
- Карточки WB не сохраняли `chrtID`, поэтому запросить остатки по размерам было невозможно.
- Габариты WB-карточек не сохранялись, поэтому расчёты логистики не имели надёжной базы.
- Добавлены методы клиента:
  - `GET /api/v3/warehouses`;
  - `POST /api/v3/stocks/{warehouseId}`;
  - `GET /api/v1/seller-info`;
  - `GET /api/communications/v2/news`;
  - `POST /api/v2/search-report/product/search-texts`.
- Синхронизация WB-остатков теперь отдельно пишет:
  - FBS-остатки продавца с источником `WB_SELLER_STOCKS`;
  - аналитические остатки WB-складов.
- Ошибка API больше не превращается в запись с нулевым остатком.

### Ozon

- Парсер остатков Ozon ожидал `stocks` как dict, хотя актуальные ответы часто содержат список
  складских/схемных записей. Теперь список корректно агрегируется.
- Добавлены методы клиента:
  - `POST /v1/seller/info`;
  - `POST /v1/product/info/stocks-by-warehouse/fbs`;
  - `POST /v5/product/info/prices`;
  - `POST /v2/warehouse/list`;
  - `POST /v1/actions/products`.
- Слой клиента не логирует ключи и продолжает использовать общий `AsyncApiClient` с retry/backoff.

### Модели и миграции

- В `products` добавлены поля:
  - `chrt_id`;
  - `length_cm`;
  - `width_cm`;
  - `height_cm`;
  - `volume_liters`;
  - `dimensions_source`.
- Добавлена безопасная Alembic-миграция:
  - `20260517_0016_product_dimensions_and_wb_chrt.py`.

### Расчёты и диагностика

- Добавлен helper расчёта литража:
  - `volume_liters = length_cm × width_cm × height_cm / 1000`.
- Для неполных/некорректных габаритов возвращается `None`, а не фиктивное значение.
- База для будущей точной WB-логистики подготовлена: проект теперь хранит габариты и литраж.

## Тесты

Добавлены и обновлены тесты:

- `tests/unit/test_product_dimensions.py`;
- `tests/unit/test_stock_service.py`;
- `tests/unit/test_product_normalizers.py`;
- `tests/integration/test_marketplace_clients.py`.

Покрыты сценарии:

- разбор `chrtID` и габаритов WB-карточки;
- расчёт литража;
- FBS-остатки WB по `chrtIds`;
- агрегация nested Ozon `stocks`;
- новые методы WB/Ozon клиентов;
- отсутствие падения на некорректных stock-значениях.

## Что осталось как следующий безопасный этап

- Полная фактическая WB-логистика требует отдельного слоя тарифов склада, коэффициентов и индексов.
  Сейчас устранён блокер: в БД появились габариты и литраж, без которых точный расчёт невозможен.
- Для новостей WB и поисковых запросов добавлена backend-основа клиента. Пользовательский UI/рассылки
  нужно проектировать отдельно, чтобы не спамить пользователей.
- Для Ozon отчётов реализации/транзакций уже есть базовый report API, но полноценный P&L требует
  отдельной сверки planned/actual и защиты от двойного учёта.

## Команды после деплоя

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -c "import app.api.main; print('API OK')"
docker compose exec bot python -c "import app.bot.main; print('BOT OK')"
docker compose exec worker python -c "import app.workers.tasks; print('TASKS OK')"
docker compose exec api pytest -q
```
