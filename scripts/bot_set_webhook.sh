#!/usr/bin/env bash
# version: 1.0.0
# description: Set Telegram webhook URL from .env configuration.
# updated: 2026-06-02

set -euo pipefail

cd /opt/mpcontrol

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

echo "Setting Telegram webhook to: ${WEBHOOK_URL}"

CURL_ARGS=(
    -sS
    "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook"
    -F "url=${WEBHOOK_URL}"
)

if [ -n "${BOT_WEBHOOK_SECRET:-}" ]; then
    CURL_ARGS+=(-F "secret_token=${BOT_WEBHOOK_SECRET}")
    echo "Secret token: configured"
else
    echo "Secret token: not configured (recommended to set BOT_WEBHOOK_SECRET)"
fi

response=$(curl "${CURL_ARGS[@]}")
echo "Response: ${response}"

if echo "${response}" | grep -q '"ok":true'; then
    echo "Webhook set successfully"
else
    echo "ERROR: Failed to set webhook"
    exit 1
fi
