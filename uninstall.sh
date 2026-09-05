#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}"
APP_DIR="${DATA_ROOT}/cpu-performance-mode"
APPLICATION_FILE="${DATA_ROOT}/applications/cpu-performance-mode.desktop"
ICON_FILE="${DATA_ROOT}/icons/hicolor/scalable/apps/cpu-performance-mode.svg"

rm -rf -- "$APP_DIR"
rm -f -- "$APPLICATION_FILE" "$ICON_FILE"

if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_FILE="$(xdg-user-dir DESKTOP)/CPU性能模式.desktop"
else
  DESKTOP_FILE="${HOME}/Desktop/CPU性能模式.desktop"
fi
rm -f -- "$DESKTOP_FILE"

echo "CPU 性能模式已卸载。"
