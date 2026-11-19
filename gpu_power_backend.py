"""Read and set NVIDIA GPU power limits through nvidia-smi."""

from __future__ import annotations

import csv
import math
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


class GpuPowerError(RuntimeError):
    """Raised when GPU power limits cannot be read or changed."""


@dataclass(frozen=True)
class GpuPowerState:
    index: int
    uuid: str
    name: str
    min_watts: float | None
    max_watts: float | None
    limit_watts: float | None

    @property
    def allowed_range(self) -> tuple[float, float] | None:
        if self.min_watts is None or self.max_watts is None or self.min_watts > self.max_watts:
            return None
        return self.min_watts, self.max_watts


class GpuPowerBackend:
    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.runner = runner
        self.which = which

    def get_states(self) -> list[GpuPowerState]:
        result = self._run(
            [
                self._find_nvidia_smi(),
                "--query-gpu=index,uuid,name,power.min_limit,power.max_limit,power.limit",
                "--format=csv,noheader,nounits",
            ],
            action="无法读取 GPU 功率上限",
            timeout=15,
        )
        if result.strip() == "No devices were found":
            return []
        states = []
        try:
            for row in csv.reader(result.splitlines(), skipinitialspace=True):
                if not row:
                    continue
                index, uuid, name, minimum, maximum, limit = (item.strip() for item in row)
                states.append(GpuPowerState(
                    index=int(index),
                    uuid=uuid,
                    name=name,
                    min_watts=self._read_watts(minimum),
                    max_watts=self._read_watts(maximum),
                    limit_watts=self._read_watts(limit),
                ))
        except (ValueError, csv.Error) as exc:
            raise GpuPowerError("无法解析 nvidia-smi 返回的 GPU 功率数据。") from exc
        return sorted(states, key=lambda state: state.index)

    def set_limit(self, gpu_uuid: str, watts: float) -> list[GpuPowerState]:
        gpu = next((state for state in self.get_states() if state.uuid == gpu_uuid), None)
        if gpu is None:
            raise GpuPowerError("找不到所选 GPU，请刷新 GPU 列表。")
        limits = gpu.allowed_range
        if limits is None:
            raise GpuPowerError(f"GPU {gpu.index} 未报告可设置的功率范围。")
        minimum, maximum = limits
        if not math.isfinite(watts) or not minimum <= watts <= maximum:
            raise GpuPowerError(f"GPU {gpu.index} 的功率上限须在 {minimum:g}–{maximum:g} W 之间。")

        pkexec = self.which("pkexec")
        if not pkexec:
            raise GpuPowerError("系统缺少 pkexec，无法请求管理员权限设置 GPU 功率上限。")
        self._run(
            [pkexec, self._find_nvidia_smi(), "-i", gpu.uuid, "-pl", str(watts)],
            action=f"无法设置 GPU {gpu.index} 的功率上限",
            timeout=60,
        )
        try:
            states = self.get_states()
        except GpuPowerError as exc:
            raise GpuPowerError(f"设置命令已执行，回读失败。{exc}") from exc
        if not any(state.uuid == gpu_uuid for state in states):
            raise GpuPowerError("设置命令已执行，回读时找不到所选 GPU。")
        return states

    def _find_nvidia_smi(self) -> str:
        nvidia_smi = self.which("nvidia-smi")
        if not nvidia_smi:
            raise GpuPowerError("未找到 nvidia-smi，请检查 NVIDIA 驱动是否已安装。")
        return nvidia_smi

    def _run(self, args: list[str], *, action: str, timeout: int) -> str:
        try:
            result = self.runner(args, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise GpuPowerError(f"{action}：操作超时。") from exc
        except OSError as exc:
            raise GpuPowerError(f"{action}：{exc}") from exc
        if result.returncode:
            output = (result.stderr or result.stdout or "").strip()
            if result.returncode == 126 and args[0].endswith("/pkexec"):
                output = "已取消管理员授权。"
            detail = output or f"命令退出码 {result.returncode}"
            raise GpuPowerError(f"{action}：{detail}")
        return result.stdout

    @staticmethod
    def _read_watts(value: str) -> float | None:
        if value.upper() in {"N/A", "[N/A]", "[NOT SUPPORTED]"}:
            return None
        watts = float(value)
        return watts if math.isfinite(watts) and watts >= 0 else None
