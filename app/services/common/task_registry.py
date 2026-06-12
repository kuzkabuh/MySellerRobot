"""Registry of all background tasks, translation dictionaries, and display helpers."""

STATUS_TRANSLATION: dict[str, str] = {
    "success": "Успешно",
    "warning": "Предупреждение",
    "error": "Ошибка",
    "failed": "Ошибка",
    "running": "Выполняется",
    "pending": "Ожидает запуска",
    "skipped": "Пропущено",
    "started": "Выполняется",
    "no_runs": "Не запускалась",
}

STATUS_COLORS: dict[str, str] = {
    "success": "#27ae60",
    "warning": "#f39c12",
    "error": "#e74c3c",
    "failed": "#e74c3c",
    "running": "#3498db",
    "pending": "#95a5a6",
    "skipped": "#95a5a6",
    "started": "#3498db",
    "no_runs": "#95a5a6",
}

CATEGORY_TRANSLATION: dict[str, str] = {
    "marketplaces": "Маркетплейсы",
    "wb": "Wildberries",
    "ozon": "Ozon",
    "system": "Системные",
    "notifications": "Уведомления",
    "finance": "Финансы",
    "unknown": "Неизвестная",
}

COUNTER_TRANSLATION: dict[str, str] = {
    "duplicates": "Дубликатов",
    "accounts_total": "Кабинетов всего",
    "accounts_success": "Кабинетов успешно",
    "accounts_failed": "Кабинетов с ошибкой",
    "orders_created": "Заказов создано",
    "orders_fetched": "Заказов загружено",
    "sales_fetched": "Продаж загружено",
    "returns_fetched": "Возвратов загружено",
    "prices_updated": "Цен обновлено",
    "products_fetched": "Товаров загружено",
    "recovery_warnings": "Предупреждений восстановления",
    "notifications_sent": "Уведомлений отправлено",
    "notifications_failed": "Ошибок уведомлений",
    "failed": "Ошибок",
    "created": "Создано",
    "updated": "Обновлено",
    "prices_fetched": "Цен загружено",
    "prices_upserted": "Цен обновлено",
    "products_synced": "Товаров синхронизировано",
    "days_synced": "Дней загружено",
    "rows_upserted": "Строк обновлено",
    "snapshots_upserted": "Слепков прибыли создано",
    "promotions_fetched": "Акций загружено",
    "nomenclatures_fetched": "Номенклатур загружено",
    "wb_report_rows_relinked": "Строк отчётов привязано",
    "accounts_processed": "Кабинетов обработано",
    "scanned": "Проверено",
    "matched": "Сопоставлено",
    "pending": "Ожидает",
    "ambiguous": "Неоднозначных",
    "errors": "Ошибок",
    "period_days": "Период дозагрузки, дней",
    "rows_fetched": "Строк загружено",
    "rows_created": "Строк создано",
    "rows_updated": "Строк обновлено",
    "orders_linked": "Связано с заказами",
    "orders_not_found": "Заказы не найдены",
    "pages_fetched": "Страниц загружено",
}

ERROR_TRANSLATIONS: dict[str, str] = {
    "completed with warnings": "Задача завершилась, но часть операций выполнена с ошибками.",
    "completed with failures": "Задача завершилась с ошибками: часть операций не выполнена.",
    "poll_new_orders completed with warnings": "Загрузка заказов завершилась с предупреждениями.",
    "sync_sale_events completed with failures": "Синхронизация продаж завершилась с ошибками.",
}

TASK_REGISTRY: dict[str, dict[str, object]] = {
    "poll_new_orders": {
        "title": "Загрузка новых заказов",
        "description": "Проверяет новые заказы маркетплейсов и создает их в базе данных.",
        "category": "marketplaces",
        "is_key": True,
        "expected_interval": "каждые 3 мин",
    },
    "sync_sale_events": {
        "title": "Синхронизация продаж и возвратов",
        "description": "Загружает события продаж и возвратов, связывает их с заказами и обновляет финансовые данные.",
        "category": "marketplaces",
        "is_key": True,
        "expected_interval": "каждые 15 мин",
    },
    "sync_wb_product_prices": {
        "title": "Синхронизация цен Wildberries",
        "description": "Получает актуальные цены товаров Wildberries и обновляет их в системе.",
        "category": "wb",
        "is_key": True,
        "expected_interval": "каждые 30 мин",
    },
    "check_auto_promo_prices": {
        "title": "Проверка автоматических промо-цен",
        "description": "Проверяет товары с автоматическими промо-ценами и выявляет расхождения.",
        "category": "wb",
        "is_key": True,
        "expected_interval": "каждые 30 мин",
    },
    "sync_products": {
        "title": "Синхронизация товаров",
        "description": "Обновляет каталог товаров всех маркетплейсов.",
        "category": "marketplaces",
        "is_key": False,
        "expected_interval": "каждый час",
    },
    "send_daily_reports": {
        "title": "Ежедневные отчёты",
        "description": "Формирует и отправляет ежедневные отчёты по продажам.",
        "category": "notifications",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "send_alert_notifications": {
        "title": "Доставка оповещений",
        "description": "Отправляет накопившиеся оповещения пользователям.",
        "category": "notifications",
        "is_key": False,
        "expected_interval": "каждые 5 мин",
    },
    "send_fbo_digests": {
        "title": "FBO-дайджесты",
        "description": "Формирует и отправляет дайджесты по заказам FBO.",
        "category": "notifications",
        "is_key": False,
        "expected_interval": "каждые 30 мин",
    },
    "process_history_backfills": {
        "title": "Обработка фоновой загрузки истории",
        "description": "Выполняет задачи по загрузке исторических данных для новых кабинетов.",
        "category": "system",
        "is_key": False,
        "expected_interval": "каждые 10 мин",
    },
    "relink_wb_report_rows": {
        "title": "Привязка отчётов WB",
        "description": "Связывает строки финансовых отчётов Wildberries с заказами.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "каждые 2 ч",
    },
    "check_fbs_deadlines": {
        "title": "Контроль сроков FBS",
        "description": "Проверяет приближающиеся дедлайны отгрузки FBS и создаёт оповещения.",
        "category": "system",
        "is_key": False,
        "expected_interval": "каждые 15 мин",
    },
    "check_low_stocks": {
        "title": "Контроль остатков",
        "description": "Проверяет остатки товаров и создаёт оповещения о низком уровне и прогнозируемом отсутствии.",
        "category": "system",
        "is_key": False,
        "expected_interval": "3 раза в день",
    },
    "sync_wb_daily_sales_reports": {
        "title": "Ежедневные отчёты по продажам WB",
        "description": "Загружает ежедневные отчёты по продажам Wildberries за последние 3 дня.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "sync_ozon_catalog_enrichment": {
        "title": "Обогащение каталога Ozon",
        "description": "Синхронизирует склады, цены и промо-товары Ozon.",
        "category": "ozon",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "sync_ozon_balances": {
        "title": "Балансы Ozon",
        "description": "Загружает текущие балансы аккаунтов Ozon.",
        "category": "ozon",
        "is_key": False,
        "expected_interval": "3 раза в день",
    },
    "reconcile_ozon_finance": {
        "title": "Сверка финансов Ozon",
        "description": "Создаёт фактические снапшоты прибыли для заказов Ozon, по которым есть финансовые данные.",
        "category": "ozon",
        "is_key": False,
        "expected_interval": "3 раза в день",
    },
    "sync_wb_account_profiles": {
        "title": "Профили кабинетов WB",
        "description": "Обновляет информацию о профилях кабинетов Wildberries.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "2 раза в день",
    },
    "check_wb_financial_reports": {
        "title": "Проверка финансовых отчётов WB",
        "description": "Проверяет доступность ежедневных и еженедельных финансовых отчётов Wildberries.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "sync_wb_daily_financial_details": {
        "title": "Детали финансов WB",
        "description": "Загружает детальные финансовые данные Wildberries за вчерашний день.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "backfill_wb_daily_financial_details": {
        "title": "Дозагрузка финансов WB",
        "description": "Перезагружает финансовые данные Wildberries за последние 50 дней для исправления расхождений.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "reconcile_pending_payments": {
        "title": "Сверка платежей",
        "description": "Проверяет статусы ожидающих платежей YooKassa и обновляет их.",
        "category": "finance",
        "is_key": False,
        "expected_interval": "каждые 20 мин",
    },
    "resend_unnotified_orders": {
        "title": "Повторная отправка уведомлений",
        "description": "Доставляет сохранённые уведомления о заказах, которые не были отправлены ранее.",
        "category": "system",
        "is_key": False,
        "expected_interval": "каждые 15 мин",
    },
    "sync_wb_commissions": {
        "title": "Комиссии Wildberries",
        "description": "Синхронизирует актуальные тарифы комиссий Wildberries из официального API.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "check_ozon_commission_source": {
        "title": "Мониторинг комиссий Ozon",
        "description": "Проверяет страницу комиссий Ozon на наличие новых тарифов.",
        "category": "ozon",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "sync_wb_logistics_tariffs": {
        "title": "Тарифы логистики WB",
        "description": "Синхронизирует тарифы доставки Wildberries из API.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "раз в день",
    },
    "sync_wb_daily_promotions": {
        "title": "Акции Wildberries",
        "description": "Синхронизирует календарь акций Wildberries и номенклатуры в них.",
        "category": "wb",
        "is_key": False,
        "expected_interval": "каждые 30 мин",
    },
}


def get_task_info(task_name: str) -> dict[str, object]:
    return TASK_REGISTRY.get(
        task_name,
        {
            "title": task_name,
            "description": "Описание для этой фоновой задачи пока не задано.",
            "category": "unknown",
            "is_key": False,
        },
    )


def translate_status(status: str | None) -> str:
    if status is None:
        return "Нет данных"
    return STATUS_TRANSLATION.get(status, status)


def status_color(status: str | None) -> str:
    if status is None:
        return "#95a5a6"
    return STATUS_COLORS.get(status, "#95a5a6")


def translate_category(category: str) -> str:
    return CATEGORY_TRANSLATION.get(category, category)


def format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "—"
    if duration_ms < 1000:
        return f"{duration_ms} мс"
    seconds = duration_ms / 1000
    if seconds < 60:
        return f"{seconds:.2f} сек".replace(".", ",")
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes} мин {secs} сек"


def translate_counters(counters: dict[str, int] | None) -> list[tuple[str, int]]:
    if not counters:
        return []
    result: list[tuple[str, int]] = []
    for key, value in counters.items():
        label = COUNTER_TRANSLATION.get(key, key)
        result.append((label, value))
    return result


def translate_error(error: str | None) -> str:
    if not error:
        return ""
    translated = ERROR_TRANSLATIONS.get(error)
    if translated:
        return translated
    if any(kw in error for kw in ("completed with warnings", "completed with failures")):
        return "Задача завершилась, но часть операций выполнена с ошибками."
    return f"Техническая ошибка: {error}"
