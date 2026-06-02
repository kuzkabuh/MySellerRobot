#!/usr/bin/env bash
# version: 1.0.0
# description: Delete Telegram webhook and switch to polling mode.
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

echo "Deleting Telegram webhook..."

response=$(curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook?drop_pending_updates=true")
echo "Response: ${response}"

if echo "${response}" | grep -q '"ok":true'; then
    echo "Webhook deleted successfully. Bot can now use polling mode."
else
    echo "ERROR: Failed to delete webhook"
    exit 1
fi
