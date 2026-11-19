#!/usr/bin/python3 -I
"""Control Ubuntu’s inbound OpenSSH socket."""

import fcntl
import os
from pathlib import Path
import subprocess
import sys


SYSTEMCTL = "/usr/bin/systemctl"
SSHD = "/usr/sbin/sshd"
SOCKET = "ssh.socket"
UNITS = (SOCKET, "ssh.service")
CONFIG = Path("/etc/ssh/sshd_config.d/00-cpu-performance-mode-key-only.conf")
AUTH = {
    "PubkeyAuthentication": "yes",
    "AuthenticationMethods": "publickey",
    "PasswordAuthentication": "no",
    "KbdInteractiveAuthentication": "no",
    "PermitRootLogin": "no",
}
CONFIG_TEXT = "".join(f"{key} {value}\n" for key, value in AUTH.items())


def command(*args, check=True):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=20)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{args[0]} 执行失败。")
    return result.stdout.strip()


def enable_ssh(config=CONFIG, runtime_dir=Path("/run/sshd"), run=command):
    states = run(SYSTEMCTL, "is-active", *UNITS, check=False).splitlines()
    if "active" in states:
        return "入站 SSH 已在运行。"
    if len(states) != len(UNITS) or any(state not in {"inactive", "failed", "unknown"} for state in states):
        raise RuntimeError("无法确认当前 SSH 服务状态。")

    original = {unit: run(SYSTEMCTL, "is-enabled", unit, check=False) for unit in UNITS}
    if any(state not in {"masked", "masked-runtime", "enabled", "disabled", "static"}
           for state in original.values()):
        raise RuntimeError("未找到 OpenSSH 服务或其状态无法识别。请检查 openssh-server。")

    created = False
    unmask_attempted = False
    start_attempted = False
    try:
        runtime_dir.mkdir(mode=0o755, exist_ok=True)
        try:
            with config.open("x", encoding="utf-8") as handle:
                created = True
                handle.write(CONFIG_TEXT)
        except FileExistsError:
            if config.is_symlink() or config.read_text(encoding="utf-8") != CONFIG_TEXT:
                raise RuntimeError(f"已有自定义配置，请检查 {config}。")
        run(SSHD, "-t")
        effective = dict(line.split(None, 1) for line in run(SSHD, "-T").splitlines() if " " in line)
        for directive, value in AUTH.items():
            if effective.get(directive.lower()) != value:
                raise RuntimeError(f"现有 SSH 配置覆盖了 {directive}，请检查配置顺序。")

        unmask_attempted = True
        run(SYSTEMCTL, "unmask", *UNITS)
        run(SYSTEMCTL, "unmask", "--runtime", *UNITS)
        run(SYSTEMCTL, "daemon-reload")
        start_attempted = True
        run(SYSTEMCTL, "enable", "--now", SOCKET)
        run(SYSTEMCTL, "is-active", "--quiet", SOCKET)
        return "入站 SSH 已开启。对方可使用已授权的公钥连接。"
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        # 启动可能在单元链接已变动后失败，恢复原来的服务状态。
        rollback_errors = []

        def restore(*args):
            try:
                run(*args)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                rollback_errors.append(str(error))

        if start_attempted:
            restore(SYSTEMCTL, "stop", *UNITS)
            if original[SOCKET] != "enabled":
                restore(SYSTEMCTL, "disable", SOCKET)
        if unmask_attempted:
            for unit, state in original.items():
                if state == "masked":
                    restore(SYSTEMCTL, "mask", unit)
                elif state == "masked-runtime":
                    restore(SYSTEMCTL, "mask", "--runtime", unit)
        if created:
            try:
                config.unlink(missing_ok=True)
            except OSError as error:
                rollback_errors.append(str(error))
        if unmask_attempted:
            restore(SYSTEMCTL, "daemon-reload")
        if rollback_errors:
            raise RuntimeError(f"{exc}\n恢复时遇到错误：{'；'.join(rollback_errors)}") from exc
        raise


def disable_ssh(run=command):
    # Ubuntu uses both a socket and an sshd service. Both can hold the listener.
    run(SYSTEMCTL, "stop", *UNITS)
    enabled = [
        unit for unit in UNITS
        if run(SYSTEMCTL, "is-enabled", unit, check=False) in {"enabled", "enabled-runtime"}
    ]
    if enabled:
        run(SYSTEMCTL, "disable", *enabled)
    run(SYSTEMCTL, "mask", *UNITS)

    states = run(SYSTEMCTL, "is-active", *UNITS, check=False).splitlines()
    if len(states) != len(UNITS) or any(state not in {"inactive", "failed"} for state in states):
        raise RuntimeError("无法确认 SSH 监听已停止。")
    if any(run(SYSTEMCTL, "is-enabled", unit, check=False) != "masked" for unit in UNITS):
        raise RuntimeError("SSH 已停止，但无法确认开机自动启动已关闭。")
    return "入站 SSH 已关闭。"


def main():
    actions = {"enable": enable_ssh, "disable": disable_ssh}
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in actions:
        print("请从桌面应用请求管理员授权。", file=sys.stderr)
        return 1

    try:
        with Path("/run/cpu-performance-mode-enable-ssh.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(actions[sys.argv[1]]())
    except BlockingIOError:
        print("正在处理另一项 SSH 操作。", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
