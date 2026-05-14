# version: 1.0.1
# description: Runtime image for Seller Profit Bot services. Исправлен порядок копирования файлов перед установкой проекта.
# updated: 2026-05-14

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем системные зависимости,
# необходимые для сборки Python-пакетов
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем весь проект,
# чтобы pip видел папку app/
COPY . .

# Устанавливаем зависимости и сам проект
RUN pip install --no-cache-dir ".[dev]"

# Запуск API-сервиса
CMD ["uvicorn", "app.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]