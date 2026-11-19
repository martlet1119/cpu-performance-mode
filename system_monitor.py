#!/usr/bin/env python3
"""SSH audit and local miner containment for Ubuntu."""

import hashlib
import ipaddress
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

STATUS = Path("/run/cpu-performance-mode-monitor/status.json")
HISTORY = Path("/var/lib/cpu-performance-mode-monitor/actions.json")
KNOWN_SAMPLES = {
    40539808: ("d5124a8698fdf02114a729c7b50011dd637634821d9872947ca600d641cfa38a", "WildRig Multi"),
}
MINER_NAMES = {
    "wildrig-multi": b"wildrig",
    "xmrig": b"xmrig",
    "lolminer": b"lolminer",
    "t-rex": b"t-rex",
    "gminer": b"gminer",
    "srbminer-multi": b"srbminer",
    "nbminer": b"nbminer",
    "teamredminer": b"teamredminer",
    "rigel": b"rigel",
    "bzminer": b"bzminer",
}
ACCEPTED = re.compile(r"^Accepted (\S+) for (\S+) from (\S+) port (\d+)")
FAILED = re.compile(r"^Failed (\S+) for (?:invalid user )?(\S+) from (\S+) port (\d+)")
INVALID = re.compile(r"^Invalid user (\S+) from (\S+) port (\d+)")
CACHE = OrderedDict()


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=6, check=False)


def ssh_event(entry):
    msg = entry.get("MESSAGE", "")
    if not isinstance(msg, str):
        return None
    match = ACCEPTED.match(msg)
    if match:
        method, user, address, port = match.groups()
        result = "成功"
    elif match := FAILED.match(msg):
        method, user, address, port = match.groups()
        result = "失败"
    elif match := INVALID.match(msg):
        user, address, port = match.groups()
        method, result = "—", "无效账号"
    else:
        return None
    try:
        address = str(ipaddress.ip_address(address))
        timestamp = int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000
    except (KeyError, ValueError, TypeError):
        return None
    return {
        "time": timestamp,
        "result": result,
        "user": user[:80],
        "address": address,
        "port": port,
        "method": method[:24],
    }


def ssh_snapshot():
    statuses = run("/usr/bin/systemctl", "is-active", "ssh.socket", "ssh.service")
    units = statuses.stdout.splitlines()
    if "active" in units:
        ssh_state = "已开启"
    elif len(units) == 2 and all(unit in {"inactive", "failed", "unknown"} for unit in units):
        ssh_state = "已关闭"
    else:
        ssh_state = "状态未知"
    events = []
    for pattern in ("^Accepted ", "^(Failed |Invalid user )"):
        log = run(
            "/usr/bin/journalctl", "--no-pager", "--output=json", "--since=14 days ago",
            "-u", "ssh.service", "-u", "sshd.service", "--grep", pattern, "-n", "150",
        )
        if log.returncode not in (0, 1) or log.stderr.strip():
            raise RuntimeError("无法读取 SSH 日志")
        for line in log.stdout.splitlines():
            try:
                event = ssh_event(json.loads(line))
            except (json.JSONDecodeError, AttributeError):
                continue
            if event:
                events.append(event)
    return ssh_state, sorted(events, key=lambda event: event["time"], reverse=True)


def matches_miner(fd, name, metadata):
    """Verify the pinned executable using a known hash or two product markers."""
    if not stat.S_ISREG(metadata.st_mode):
        return None
    sample = KNOWN_SAMPLES.get(metadata.st_size)
    brand = MINER_NAMES.get(name.lower())
    if not sample and not brand:
        return None
    key = (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns,
           metadata.st_ctime_ns, metadata.st_size, name.lower())
    if key in CACHE:
        CACHE.move_to_end(key)
        return CACHE[key]
    product = None
    with os.fdopen(os.dup(fd), "rb") as executable:
        if executable.read(4) != b"\x7fELF":
            return None
        executable.seek(0)
        if sample and hashlib.file_digest(executable, "sha256").hexdigest() == sample[0]:
            product = sample[1]
        elif brand and metadata.st_size <= 128 * 1024 * 1024:
            executable.seek(0)
            seen_brand = seen_protocol = False
            tail = b""
            while chunk := executable.read(1024 * 1024):
                data = tail + chunk.lower()
                seen_brand = seen_brand or brand in data
                seen_protocol = seen_protocol or b"stratum" in data
                if seen_brand and seen_protocol:
                    product = name
                    break
                tail = data[-32:]
    CACHE[key] = product
    if len(CACHE) > 256:
        CACHE.popitem(last=False)
    return product


def contain(pid, proc=Path("/proc")):
    """Block execution on the verified inode and signal the same process via pidfd."""
    executable = proc / str(pid) / "exe"
    try:
        pidfd = os.pidfd_open(pid)
    except OSError:
        return None
    try:
        filename = os.readlink(executable)
        name = Path(filename.removesuffix(" (deleted)")).name
        expected = executable.stat()
        if name.lower() not in MINER_NAMES and expected.st_size not in KNOWN_SAMPLES:
            return None
        fd = os.open(executable, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            metadata = os.fstat(fd)
            if not os.path.samestat(expected, metadata):
                return None
            family = matches_miner(fd, name, metadata)
            if not family or not os.path.samestat(executable.stat(), metadata):
                return None
            current = os.fstat(fd)
            if (current.st_ctime_ns, current.st_mtime_ns) != (metadata.st_ctime_ns, metadata.st_mtime_ns):
                return None
            blocked = "跳过共享或已删除文件"
            if current.st_nlink == 1:
                try:
                    os.fchmod(fd, stat.S_IMODE(current.st_mode) & ~0o111)
                    blocked = "禁止执行"
                except OSError as error:
                    blocked = f"阻止执行失败 ({error.strerror})"
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                stopped = "已发送终止信号"
            except ProcessLookupError:
                stopped = "进程已退出"
            except OSError as error:
                stopped = f"终止失败 ({error.strerror})"
            return {
                "time": time.time(),
                "name": family,
                "pid": pid,
                "path": filename,
                "action": f"{stopped} · {blocked}",
            }
        finally:
            os.close(fd)
    except OSError:
        return None
    finally:
        os.close(pidfd)


def process_ids():
    """Prefer an independent static process listing when Ubuntu provides it."""
    busybox = Path("/usr/bin/busybox")
    if busybox.is_file():
        try:
            result = run(str(busybox), "ps", "-o", "pid")
            if result.returncode == 0:
                return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return [int(path.name) for path in Path("/proc").iterdir() if path.name.isdecimal()]


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fchmod(handle.fileno(), 0o640)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def gpu_snapshot():
    try:
        result = run(
            "/usr/bin/nvidia-smi", "--query-gpu=utilization.gpu,power.draw",
            "--format=csv,noheader,nounits",
        )
        if result.returncode == 0:
            utilization, power = result.stdout.splitlines()[0].split(",")
            return {"utilization": int(utilization), "power": float(power)}
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return None


def main():
    try:
        actions = json.loads(HISTORY.read_text(encoding="utf-8"))[:150]
    except (OSError, ValueError, TypeError):
        actions = []
    ssh_state, ssh_events, gpu = "读取中", [], None
    while True:
        recent = [event for pid in process_ids() if (event := contain(pid))]
        if recent:
            actions = (recent + actions)[:150]
            write_json(HISTORY, actions)
            for action in recent:
                print(json.dumps(action, ensure_ascii=False), flush=True)
        ssh_error = None
        try:
            ssh_state, ssh_events = ssh_snapshot()
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            ssh_error = "SSH 日志读取异常，显示上一次结果"
        gpu = gpu_snapshot()
        write_json(STATUS, {
            "time": time.time(),
            "ssh_state": ssh_state,
            "ssh_events": ssh_events,
            "ssh_error": ssh_error,
            "gpu": gpu,
            "actions": actions,
        })
        time.sleep(4)


if __name__ == "__main__":
    main()
