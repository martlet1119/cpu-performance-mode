#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
unit=cpu-performance-mode-monitor.service
unit_path="/etc/systemd/system/$unit"
exec_dir=/usr/local/libexec/cpu-performance-mode-monitor
state_dir=/var/lib/cpu-performance-mode-monitor
status_path=/run/cpu-performance-mode-monitor/status.json
legacy_unit=ssh-login-monitor.service
legacy_unit_path="/etc/systemd/system/$legacy_unit"
legacy_exec=/usr/local/libexec/ssh-login-monitor/monitor.py
legacy_history=/var/lib/ssh-login-monitor/actions.json

case "${1:-}" in
  install|migrate|remove) action="$1" ;;
  *) printf '用法：sudo %s {install|migrate|remove}\n' "$0" >&2; exit 2 ;;
esac
if (( EUID != 0 )); then
    printf '安装或移除系统监控服务需要管理员权限。\n' >&2
    exit 1
fi

exec 9>/run/lock/cpu-performance-mode-monitor.lock
flock 9

if [[ "$action" == remove ]]; then
    if [[ -f "$unit_path" ]]; then
        systemctl disable --now "$unit"
        rm -f -- "$unit_path"
        systemctl daemon-reload
    fi
    rm -f -- "$exec_dir/system_monitor.py" "$exec_dir/ssh-control" "$exec_dir/enable-ssh"
    exit 0
fi

install -d -o root -g root -m 0755 "$exec_dir"
install -o root -g root -m 0644 "$source_dir/system_monitor.py" "$exec_dir/system_monitor.py"
install -o root -g root -m 0755 "$source_dir/ssh_control.py" "$exec_dir/ssh-control"
rm -f -- "$exec_dir/enable-ssh"
install -o root -g root -m 0644 "$source_dir/$unit" "$unit_path"
systemd-analyze verify "$unit_path"
systemctl daemon-reload

restore_legacy=false
restore_if_failed() {
    local exit_code=$?
    if (( exit_code != 0 )) && "$restore_legacy"; then
        systemctl disable --now "$unit" || true
        systemctl start "$legacy_unit" || true
    fi
}
trap restore_if_failed EXIT

if [[ "$action" == migrate && -f "$legacy_unit_path" ]]; then
    if systemctl is-active --quiet "$legacy_unit"; then
        restore_legacy=true
        systemctl stop "$legacy_unit"
    fi
    if [[ -f "$legacy_history" && ! -f "$state_dir/actions.json" ]]; then
        install -d -o root -g adm -m 0750 "$state_dir"
        install -o root -g adm -m 0640 "$legacy_history" "$state_dir/actions.json"
    fi
fi

systemctl enable "$unit"
systemctl restart "$unit"

for attempt in {1..45}; do
    if [[ -s "$status_path" ]] && systemctl is-active --quiet "$unit"; then
        restore_legacy=false
        break
    fi
    sleep 1
done
if [[ ! -s "$status_path" ]] || ! systemctl is-active --quiet "$unit"; then
    printf '新版后台未生成监控状态。请检查 %s。\n' "$unit" >&2
    exit 1
fi

if [[ "$action" == migrate && -f "$legacy_unit_path" ]]; then
    systemctl disable "$legacy_unit"
    rm -f -- "$legacy_exec" "$legacy_unit_path"
    systemctl daemon-reload
fi

printf '运行中：%s\n' "$unit"
