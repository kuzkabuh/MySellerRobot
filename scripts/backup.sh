#!/usr/bin/env bash
# version: 1.0.0
# description: Manual backup entrypoint for MP Control production.
# updated: 2026-06-07

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
export PROJECT_DIR

exec "${PROJECT_DIR}/scripts/backup_daily.sh" "$@"
