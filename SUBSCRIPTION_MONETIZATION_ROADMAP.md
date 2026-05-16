# Subscription & Monetization Roadmap

**Проект:** MP Control / Seller Profit Bot / KUZ’KA.SELLER BOT  
**Базовая версия:** 1.5.4  
**Целевая линейка:** 1.6.1 → 1.6.6  
**Статус:** План реализации системы подписок, тарифных ограничений и коммерческой готовности продукта  
**Дата создания:** 2026-05-16

---

# 1. Цель roadmap

Цель данной дорожной карты — превратить текущую заготовку подписок и монетизации в полноценную, надёжную и коммерчески пригодную систему.

После завершения этапов **1.6.1–1.6.6** проект должен иметь:

- стабильную интеграцию с ЮКасса;
- корректную обработку webhook;
- защищённую и идемпотентную обработку платежей;
- полноценный жизненный цикл подписок;
- monthly / yearly планы;
- trial PRO на 14 дней;
- upgrade тарифов;
- единый механизм feature gating;
- реальные различия между FREE / BASIC / PRO / ENTERPRISE;
- ограничения по функциям, кабинетам, заказам, SKU и истории;
- paywall UX в Telegram и Web;
- уведомления о завершении подписки;
- актуальную документацию для деплоя и сопровождения.

---

# 2. Тарифная стратегия

## 2.1. Тарифы

| Тариф | Цена | Целевая аудитория |
|---|---:|---|
| FREE | 0 ₽ | Новые пользователи, тест сервиса |
| BASIC | 490 ₽ / мес, 4 900 ₽ / год | Небольшие селлеры, базовый ежедневный контроль |
| PRO | 1 490 ₽ / мес, 14 900 ₽ / год | Активные селлеры, управленческая аналитика |
| ENTERPRISE | Индивидуально | Агентства, бренды, команды |

---

# 3. Отличия тарифов

## 3.1. Лимиты

| Лимит | FREE | BASIC | PRO | ENTERPRISE |
|---|---:|---:|---:|---:|
| Подключённых кабинетов МП | 1 | 2 | 5 | Индивидуально |
| Заказов в месяц | 100 | 1 000 | Без ограничений | Индивидуально |
| SKU в аналитике | 100 | 1 000 | 10 000 | Индивидуально |
| Глубина истории | 7 дней | 90 дней | 365 дней | Индивидуально |

---

## 3.2. Базовый функционал

| Функция | FREE | BASIC | PRO | ENTERPRISE |
|---|---:|---:|---:|---:|
| Подключение WB / Ozon | Да | Да | Да | Да |
| Уведомления о новых заказах | Да | Да | Да | Да |
| Уведомления о выкупах | Да | Да | Да | Да |
| Плановая прибыль в карточке заказа | Да | Да | Да | Да |
| Web-кабинет | Да | Да | Да | Да |
| Базовая ежедневная сводка | Да | Да | Да | Да |
| Расширенная ежедневная сводка | Нет | Да | Да | Да |

---

## 3.3. Контроль и алерты

| Функция | FREE | BASIC | PRO | ENTERPRISE |
|---|---:|---:|---:|---:|
| Низкая маржа | Нет | Да | Да | Да |
| Низкие остатки | Нет | Да | Да | Да |
| FBS дедлайны | Нет | Да | Да | Да |
| Настройка порогов | Нет | Да | Да | Да |
| Расширенное качество данных | Нет | Да | Да | Да |

---

## 3.4. Аналитика

| Функция | FREE | BASIC | PRO | ENTERPRISE |
|---|---:|---:|---:|---:|
| Аналитика прибыли по SKU | Нет | Да | Да | Да |
| Фактическая прибыль | Нет | Да | Да | Да |
| План / факт | Нет | Нет | Да | Да |
| Безубыточная цена | Нет | Нет | Да | Да |
| Прогноз остатков | Нет | Нет | Да | Да |
| MasterProduct аналитика | Нет | Просмотр | Полноценно | Полноценно |
| Ручное сопоставление товаров | Нет | Нет | Да | Да |

---

## 3.5. Экспорт и расширенные инструменты

| Функция | FREE | BASIC | PRO | ENTERPRISE |
|---|---:|---:|---:|---:|
| Базовый экспорт в Excel | Нет | Да | Да | Да |
| Расширенный экспорт | Нет | Нет | Да | Да |
| Приоритетная поддержка | Нет | Нет | Да | Да |
| API-доступ | Нет | Нет | Нет | Да |
| Роли и команда | Нет | Нет | Нет | Да |

---

# 4. Будущие функции, которые нужно заранее заложить в feature flags

Следующие возможности могут быть реализованы позднее, но должны быть предусмотрены в тарифной архитектуре уже на этапе 1.6.x:

| Feature code | Назначение | Тариф |
|---|---|---|
| `financial_pnl` | P&L-отчёт | PRO |
| `cashflow_forecast` | Прогноз поступлений / cashflow | PRO |
| `abc_analysis` | ABC-анализ товаров | PRO |
| `bcg_matrix` | BCG-матрица | PRO |
| `price_optimization` | Оптимизация цен | PRO |
| `scheduled_reports` | Автоотчёты | BASIC / PRO |
| `api_access` | API для разработчиков | ENTERPRISE |
| `team_roles` | Роли сотрудников | ENTERPRISE |
| `multi_user_access` | Командная работа | ENTERPRISE |
| `custom_integrations` | Индивидуальные интеграции | ENTERPRISE |

---

# 5. Этапы реализации

---

# Release 1.6.1 — Payment Infrastructure Finalization

## Цель

Довести базовую интеграцию подписок и ЮКассы до технически корректного рабочего состояния.

## Основные задачи

### 1. Синхронизация версий

- обновить `VERSION`;
- обновить `pyproject.toml`;
- обновить FastAPI metadata;
- актуализировать `README.md`.

### 2. Переменные окружения

Добавить в `.env.example`:

```env
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=

Документировать назначение:

WEB_BASE_URL;
return URL;
webhook URL.
### 3. Подключение webhook router
импортировать app.api.webhooks.router;
подключить в app/api/main.py;
убедиться, что маршрут POST /webhooks/yookassa зарегистрирован.
### 4. Страница возврата после оплаты

Создать публичный маршрут:

/payment/success

или эквивалентный согласованный URL.

Страница должна сообщать:

платёж принят;
подписка активируется после подтверждения;
пользователю следует вернуться в Telegram-бот.
### 5. Корректная обработка ошибок webhook
invalid payload → 400 Bad Request;
неожиданные ошибки → 500 Internal Server Error;
не перехватывать HTTPException общим except Exception.
### 6. Защита логов

Маскировать чувствительные заголовки:

Authorization;
Cookie;
X-API-Key;
X-Admin-Secret.
### 7. Подписочный UI

Проверить стабильность:

/subscription;
выбор тарифа;
переход к оплате;
возврат назад;
история платежей.
### 8. Тесты

Добавить тесты:

registration of subscription_router;
registration of webhooks_router;
/payment/success;
invalid webhook payload;
sanitization-sensitive headers.
Критерии готовности
бот импортируется;
API импортируется;
/subscription работает;
webhook route существует;
return URL не ведёт на 404;
тесты проходят.
Release 1.6.2 — Secure & Idempotent Payment Processing
Цель

Сделать обработку платежей надёжной, устойчивой к дублям и безопасной.

Основные задачи
1. Идемпотентность payment.succeeded
повторный webhook не должен повторно продлевать подписку;
если платёж уже SUCCEEDED, событие игнорируется.
2. Идемпотентность payment.canceled
повторный canceled не ломает данные;
canceled не должен переводить успешный платёж обратно в отменённый.
3. Повторная проверка статуса платежа через ЮКасса API

После получения webhook:

запросить платёж по payment_id;
убедиться, что статус соответствует событию;
только потом менять локальное состояние.
4. Валидация платежных данных

Проверять:

provider_payment_id;
user_id;
tier_code;
period;
наличие ожидаемой metadata.
5. Логирование событий оплаты

Добавить структурированные события:

payment_created;
payment_success_received;
payment_success_verified;
payment_success_duplicate_ignored;
payment_cancel_received;
payment_cancel_verified;
payment_webhook_invalid;
payment_not_found.
6. Тесты

Добавить тесты:

successful payment activates subscription;
duplicate success webhook ignored;
canceled after succeeded ignored;
unknown payment logged safely;
invalid metadata does not activate subscription.
Критерии готовности
повторные webhook не ломают подписку;
статус оплаты подтверждается через провайдера;
все негативные кейсы обрабатываются корректно.
Release 1.6.3 — Subscription Lifecycle
Цель

Реализовать корректную бизнес-логику подписок.

Основные задачи
1. Monthly / Yearly
monthly = 30 дней;
yearly = 365 дней;
период передаётся из платежа в логику подписки.
2. Продление подписки

Если тариф тот же:

продлевать от expires_at, если подписка ещё активна;
продлевать от now, если подписка истекла.
3. Upgrade

Поддержать:

FREE → BASIC;
FREE → PRO;
BASIC → PRO.

Для BASIC → PRO:

предыдущая подписка закрывается;
создаётся новая PRO-подписка;
доступ меняется сразу.
4. Trial
один раз на пользователя;
рекомендованный trial — 14 дней PRO;
trial должен считаться активной подпиской;
trial отображается в /subscription.
5. Expiration
истёкшие подписки не считаются активными;
пользователь автоматически получает FREE;
данные не удаляются.
6. Статусы

Использовать статусы:

ACTIVE;
TRIAL;
CANCELLED;
EXPIRED;
REPLACED — при upgrade, если выбран такой подход.
7. Тесты

Добавить тесты:

monthly = 30 дней;
yearly = 365 дней;
renewal from expires_at;
renewal from now;
upgrade BASIC → PRO;
active trial;
expired trial;
expired paid subscription.
Критерии готовности
подписки ведут себя бизнес-корректно;
annual не превращается в 30 дней;
upgrade не ломает текущий тариф.
Release 1.6.4 — Unified Subscription Architecture & Feature Access
Цель

Устранить двойную подписочную архитектуру и внедрить единый механизм проверки доступа.

Текущая проблема

В проекте существуют две параллельные модели:

Старая:
SubscriptionPlan;
Subscription.
Новая:
SubscriptionTier;
UserSubscription;
Payment.

Платежи используют новую модель, а FeatureAccessService — старую.

Основные задачи
1. Аудит старой модели

Проверить использование:

SubscriptionPlan;
Subscription;
User.tariff;
User.subscription_until.
2. Выбрать единую рабочую архитектуру

Основной системой сделать:

SubscriptionTier;
UserSubscription;
Payment.
3. Переписать FeatureAccessService

Он должен использовать новую подписочную модель.

4. Реализовать унифицированные проверки
can_use_feature;
can_add_marketplace_account;
can_sync_more_skus;
can_process_order;
get_history_window_days.
5. Feature flags

Поддержать расширенный набор feature codes:

web_cabinet;
basic_dashboard;
order_notifications;
buyout_notifications;
profit_in_order_card;
daily_summary_basic;
daily_summary_extended;
analytics;
profit_page_extended;
plan_fact;
break_even;
stock_forecast;
alerts;
low_margin_alerts;
low_stock_alerts;
fbs_deadline_alerts;
data_quality_extended;
master_products;
manual_product_matching;
excel_exports;
extended_excel_exports;
api_access;
priority_support;
financial_pnl;
cashflow_forecast;
abc_analysis;
bcg_matrix;
price_optimization;
scheduled_reports;
team_roles;
multi_user_access;
custom_limits;
custom_integrations.
6. Старые модели
либо полностью вывести из runtime;
либо пометить как deprecated;
документировать выбранный путь.
7. Тесты

Добавить тесты:

BASIC даёт BASIC-функции;
PRO даёт PRO-функции;
FREE не получает PRO-доступ;
runtime не зависит от старых SubscriptionPlan / Subscription.
Критерии готовности
вся проверка доступа работает через одну систему;
оплаченный тариф реально открывает функции;
будущие фичи легко подключаются к feature flags.
Release 1.6.5 — Tariff Matrix Enforcement & Paywall UX
Цель

Сделать различия тарифов реальными в продукте.

Основные задачи
1. Обновить тарифы в seed / миграциях

Использовать следующую матрицу:

FREE
1 кабинет;
100 заказов / месяц;
100 SKU;
7 дней истории;
базовые уведомления;
без алертов и расширенной аналитики.
BASIC
2 кабинета;
1 000 заказов / месяц;
1 000 SKU;
90 дней истории;
расширенная сводка;
алерты;
расширенная прибыль;
базовый экспорт.
PRO
5 кабинетов;
заказы без ограничений;
10 000 SKU;
365 дней истории;
plan/fact;
break-even;
stock forecast;
manual matching;
расширенный экспорт;
приоритетная поддержка.
ENTERPRISE
индивидуальные лимиты;
API;
роли;
командная работа;
кастомные интеграции.
2. Ограничения кабинетов
блокировать добавление кабинета сверх лимита;
показывать понятное предложение перейти на следующий тариф.
3. Ограничения заказов
считать количество заказов за календарный месяц;
заказы сверх лимита сохранять, но ограничивать платную ценность согласно выбранной политике;
показывать paywall-сообщения.
4. Ограничения SKU
контролировать импорт / синхронизацию / аналитику;
не ломать данные при превышении лимита.
5. История данных
FREE: 7 дней;
BASIC: 90 дней;
PRO: 365 дней.
6. Web paywall

Для недоступных разделов показывать красивую paywall-страницу, а не голый 403.

Примеры:

Plan / Fact — PRO;
Break-even — PRO;
Stock Forecast — PRO;
Manual Product Matching — PRO.
7. Telegram paywall

При недоступной кнопке:

Эта функция доступна на тарифе PRO.
Откройте /subscription, чтобы выбрать тариф.
8. Обновить /subscription

Показывать:

текущий тариф;
лимиты;
список доступных функций;
преимущества апгрейда.
9. Тесты

Добавить тесты:

account limit;
SKU limit;
order limit;
history depth;
web paywall;
Telegram paywall;
PRO-only features.
Критерии готовности
FREE / BASIC / PRO действительно отличаются;
пользователь понимает, за что платит;
ограничения не выглядят случайными.
Release 1.6.6 — Monetization UX, Subscription Reminders & Sales Readiness
Цель

Подготовить коммерческую механику к реальному запуску.

Основные задачи
1. Улучшить /subscription

Показать:

текущий тариф;
статус;
дату окончания;
trial;
преимущества плана;
monthly / yearly цены;
кнопки перехода на BASIC / PRO.
2. Экран сравнения тарифов

Реализовать публичный или web-экран:

/pricing

или:

/web/pricing

Содержимое:

карточки тарифов;
таблица различий;
CTA к оформлению в Telegram.
3. Напоминания о завершении подписки

Отправлять уведомления:

за 3 дня;
за 1 день;
в день окончания.
4. Напоминания о trial
за 3 дня до завершения trial;
в день окончания trial.
5. Win-back сообщение

После завершения платной подписки:

Подписка завершена. Ваши данные сохранены, но расширенные функции отключены.
Вернуться на тариф можно через /subscription.
6. Subscription events

Предусмотреть события:

pricing_opened;
tariff_selected;
payment_created;
payment_succeeded;
payment_cancelled;
trial_started;
trial_expired;
subscription_upgraded;
subscription_expired.
7. Документация

Создать файл:

SUBSCRIPTIONS_AND_BILLING.md

Описать:

тарифы;
оплату;
webhook;
trial;
monthly/yearly;
upgrade;
feature gating;
деплой и диагностику.
8. Тесты

Добавить тесты:

reminder schedule;
trial status UI;
pricing screen;
subscription event logging;
expired subscription notification.
Критерии готовности
продукт можно уверенно переводить к платящим пользователям;
тарифы объяснены;
возврат и продление подписки поддерживаются;
коммерческий UX выглядит завершённым.
6. Приоритет внедрения
Обязательный порядок
1.6.1 — починить инфраструктуру.
1.6.2 — сделать оплату надёжной.
1.6.3 — сделать подписки бизнес-корректными.
1.6.4 — объединить архитектуру.
1.6.5 — ввести реальные тарифные ограничения.
1.6.6 — улучшить UX и подготовить продажи.
7. Что не делать в рамках 1.6.x

В рамках данной линейки не смешивать подписочную архитектуру с крупными продуктовыми модулями:

P&L;
Cashflow;
ABC;
BCG;
Price Optimization;
1С;
AI-ассистент;
Telegram Mini App;
Mobile App.

Эти функции должны идти после стабилизации monetization-layer, используя уже готовые feature flags.

8. Ожидаемое состояние продукта после 1.6.6

После завершения этапов проект должен иметь:

готовую к production оплату;
полноценные тарифы;
работающее разграничение доступа;
монетизацию, которую не стыдно запускать на реальных пользователях;
архитектурную основу для дальнейших крупных функций:
P&L;
ABC;
Cashflow;
AI;
API.

9. Рекомендуемый следующий большой этап после 1.6.6

После завершения монетизации логично переходить к следующей продуктовой линейке:

1.7.x — Financial Analytics

В неё могут войти:

P&L-отчёт;
финансовая сводка по периодам;
управленческая прибыль;
выгрузка финансового отчёта;
подготовка для cashflow.