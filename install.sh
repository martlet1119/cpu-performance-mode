#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}"
APP_DIR="${DATA_ROOT}/cpu-performance-mode"
APPLICATIONS_DIR="${DATA_ROOT}/applications"
ICON_DIR="${DATA_ROOT}/icons/hicolor/scalable/apps"

install -d "$APP_DIR" "$APPLICATIONS_DIR" "$ICON_DIR"
install -m 644 "$SCRIPT_DIR/cpu_mode_backend.py" "$APP_DIR/cpu_mode_backend.py"
install -m 644 "$SCRIPT_DIR/gpu_power_backend.py" "$APP_DIR/gpu_power_backend.py"
install -m 644 "$SCRIPT_DIR/monitor_panel.py" "$APP_DIR/monitor_panel.py"
install -m 755 "$SCRIPT_DIR/app.py" "$APP_DIR/app.py"
install -m 644 "$SCRIPT_DIR/icons/cpu-performance-mode.svg" "$ICON_DIR/cpu-performance-mode.svg"

sed \
  -e "s|@APP_DIR@|${APP_DIR}|g" \
  -e "s|@ICON_PATH@|${ICON_DIR}/cpu-performance-mode.svg|g" \
  "$SCRIPT_DIR/cpu-performance-mode.desktop.in" > "$APPLICATIONS_DIR/cpu-performance-mode.desktop"
chmod 755 "$APPLICATIONS_DIR/cpu-performance-mode.desktop"

if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
else
  DESKTOP_DIR="${HOME}/Desktop"
fi

if [[ -d "$DESKTOP_DIR" ]]; then
  install -m 755 "$APPLICATIONS_DIR/cpu-performance-mode.desktop" "$DESKTOP_DIR/CPU性能模式.desktop"
  if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/CPU性能模式.desktop" metadata::trusted true >/dev/null 2>&1 || true
  fi
  echo "桌面快捷方式：$DESKTOP_DIR/CPU性能模式.desktop"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

echo "安装完成。可从应用列表搜索“CPU 性能模式”。"
