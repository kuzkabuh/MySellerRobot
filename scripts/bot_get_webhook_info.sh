#!/usr/bin/env bash
# version: 1.0.0
# description: Get current Telegram webhook info.
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

echo "Fetching Telegram webhook info..."
echo ""

response=$(curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo")

echo "Webhook Info:"
echo "${response}" | python3 -m json.tool 2>/dev/null || echo "${response}"

echo ""
echo "Expected URL: ${BOT_WEBHOOK_BASE_URL%/}${BOT_WEBHOOK_PATH:-/webhook/telegram}"
