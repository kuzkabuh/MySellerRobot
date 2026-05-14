# version: 1.0.0
# description: Developer shortcuts for local operations.
# updated: 2026-05-14
.PHONY: install lint format test migrate revision up down api bot worker

install:
	pip install -e ".[dev]"

lint:
	ruff check app tests migrations
	mypy app

format:
	black app tests migrations
	ruff check app tests migrations --fix

test:
	pytest

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

up:
	docker compose up --build

down:
	docker compose down

api:
	uvicorn app.api.main:create_app --factory --reload

bot:
	python -m app.bot.main

worker:
	arq app.workers.settings.WorkerSettings
