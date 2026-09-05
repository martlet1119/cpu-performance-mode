"""Backend for reading and changing the Linux CPUFreq governor."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class ModeError(RuntimeError):
    """Raised when the requested CPU frequency policy cannot be applied."""


@dataclass(frozen=True)
class ModeState:
    performance: bool
    mode: str
    source: str
    detail: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


class CpuModeBackend:
    """Read and change only the kernel CPUFreq scaling governor."""

    def __init__(
        self,
        *,
        config_dir: Path | None = None,
        sysfs_root: Path = Path("/sys/devices/system/cpu"),
        runner: Runner = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.config_dir = config_dir or Path.home() / ".config" / "cpu-performance-mode"
        self.state_file = self.config_dir / "previous-state.json"
        self.sysfs_root = sysfs_root
        self.runner = runner
        self.which = which

    def get_state(self) -> ModeState:
        governors = self._read_governors()
        if not governors:
            raise ModeError("无法读取 CPUFreq 调频策略。当前内核或 CPU 可能未启用 CPUFreq。")

        common = Counter(governors).most_common(1)[0][0]
        all_performance = all(item == "performance" for item in governors)
        mixed = " · 部分核心策略不同" if len(set(governors)) > 1 else ""
        available = self._read_available_governors()
        available_text = " / ".join(available) if available else "未知"
        return ModeState(
            performance=all_performance,
            mode="性能策略" if all_performance else self._friendly_name(common),
            source="Linux CPUFreq governor",
            detail=f"当前：{common}{mixed}  ·  可用：{available_text}",
        )

    def enable_performance(self) -> ModeState:
        current = self.get_state()
        if current.performance:
            return current

        available = self._read_available_governors()
        if available and "performance" not in available:
            raise ModeError("当前 CPUFreq 驱动不提供 performance 调频策略。")

        self._save_previous_governor()
        try:
            self._set_governor("performance")
            updated = self.get_state()
            if not updated.performance:
                raise ModeError("命令已执行，但并非所有 CPU 核心都切换到了 performance。")
            return updated
        except Exception:
            self._discard_previous()
            raise

    def disable_performance(self) -> ModeState:
        previous = self._load_previous()
        target = previous.get("governor") or self._default_non_performance_governor()
        self._set_governor(target)
        self._discard_previous()
        return self.get_state()

    def _governor_paths(self) -> list[Path]:
        return sorted(self.sysfs_root.glob("cpu[0-9]*/cpufreq/scaling_governor"))

    def _read_governors(self) -> list[str]:
        return self._read_values(self._governor_paths())

    def _read_available_governors(self) -> list[str]:
        paths = sorted(self.sysfs_root.glob("cpu[0-9]*/cpufreq/scaling_available_governors"))
        values: set[str] = set()
        for entry in self._read_values(paths):
            values.update(entry.split())
        preferred = ["performance", "schedutil", "ondemand", "powersave", "conservative", "userspace"]
        return sorted(values, key=lambda item: (preferred.index(item) if item in preferred else len(preferred), item))

    @staticmethod
    def _read_values(paths: list[Path]) -> list[str]:
        values: list[str] = []
        for path in paths:
            try:
                value = path.read_text(encoding="utf-8").strip().lower()
            except OSError:
                continue
            if value:
                values.append(value)
        return values

    def _save_previous_governor(self) -> None:
        governors = self._read_governors()
        if not governors:
            raise ModeError("无法保存当前 CPUFreq 调频策略。")
        payload = {"governor": Counter(governors).most_common(1)[0][0]}
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise ModeError(f"无法保存原 CPU 调频策略：{exc}") from exc

    def _load_previous(self) -> dict[str, str]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _default_non_performance_governor(self) -> str:
        available = self._read_available_governors()
        for candidate in ("powersave", "schedutil", "ondemand", "conservative"):
            if not available or candidate in available:
                return candidate
        raise ModeError("未找到可用于关闭性能策略的 CPUFreq governor。")

    def _set_governor(self, governor: str) -> None:
        cpupower = self.which("cpupower")
        pkexec = self.which("pkexec")
        if not cpupower:
            raise ModeError("系统缺少 cpupower，请安装 linux-tools-common 与当前内核对应的 linux-tools。")
        if not pkexec:
            raise ModeError("系统缺少 pkexec，无法请求管理员权限修改 CPUFreq。")

        result = self._run([pkexec, cpupower, "frequency-set", "--governor", governor], timeout=60)
        if result.returncode != 0:
            raise ModeError(f"无法设置 CPUFreq governor 为 {governor}：{self._error_text(result)}")

    def _discard_previous(self) -> None:
        try:
            self.state_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _run(self, args: Sequence[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(list(args), capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(list(args), 124, "", "操作超时")
        except OSError as exc:
            return subprocess.CompletedProcess(list(args), 127, "", str(exc))

    @staticmethod
    def _error_text(result: subprocess.CompletedProcess[str]) -> str:
        text = (result.stderr or result.stdout or "").strip()
        if result.returncode in {126, 127} and not text:
            return "用户取消了管理员授权"
        return text.splitlines()[-1] if text else f"命令退出码 {result.returncode}"

    @staticmethod
    def _friendly_name(value: str) -> str:
        return {
            "powersave": "节能/动态策略",
            "schedutil": "动态调频策略",
            "ondemand": "按需调频策略",
            "conservative": "保守调频策略",
            "userspace": "用户调频策略",
        }.get(value, value)
