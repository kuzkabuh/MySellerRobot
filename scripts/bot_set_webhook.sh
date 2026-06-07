#!/usr/bin/env bash
# version: 1.0.0
# description: Set Telegram webhook URL from .env configuration.
# updated: 2026-06-02

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
cd "$PROJECT_DIR"

set -a
source .env
set +a

if [ -z "${BOT_TOKEN:-}" ]; then
    echo "ERROR: BOT_TOKEN is not set in .env"
    exit 1
fi

if [ -z "${BOT_WEBHOOK_BASE_URL:-}" ]; then
    echo "ERROR: BOT_WEBHOOK_BASE_URL is not set in .env"
    exit 1
fi

WEBHOOK_URL="${BOT_WEBHOOK_BASE_URL%/}${BOT_WEBHOOK_PATH:-/webhook/telegram}"
WEBHOOK_SECRET="${BOT_WEBHOOK_SECRET:-${TELEGRAM_WEBHOOK_SECRET:-}}"
APP_ENV_VALUE="${APP_ENV:-local}"
INSECURE_ALLOWED="${WEBHOOK_ALLOW_INSECURE_DEV:-0}"

if [ -z "${WEBHOOK_SECRET}" ] && { [ "${APP_ENV_VALUE}" = "production" ] || [ "${APP_ENV_VALUE}" = "prod" ] || [ "${APP_ENV_VALUE}" = "staging" ]; } && [ "${INSECURE_ALLOWED}" != "1" ]; then
    echo "ERROR: BOT_WEBHOOK_SECRET or TELEGRAM_WEBHOOK_SECRET is required in production."
    exit 1
fi

echo "Setting Telegram webhook to: ${WEBHOOK_URL}"

CURL_ARGS=(
    -sS
    "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook"
    -F "url=${WEBHOOK_URL}"
    -F 'allowed_updates=["message","callback_query"]'
)

if [ -n "${WEBHOOK_SECRET}" ]; then
    CURL_ARGS+=(-F "secret_token=${WEBHOOK_SECRET}")
    echo "Secret token: configured"
else
    echo "Secret token: not configured (local insecure mode only)"
fi

response=$(curl "${CURL_ARGS[@]}")
echo "Response: ${response}"

if echo "${response}" | grep -q '"ok":true'; then
    echo "Webhook set successfully"
else
    echo "ERROR: Failed to set webhook"
    exit 1
fi
