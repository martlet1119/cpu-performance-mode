from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from cpu_mode_backend import CpuModeBackend, ModeError


def make_cpu_files(root: Path, governor: str, available: str = "performance powersave") -> None:
    for cpu in ("cpu0", "cpu1"):
        path = root / cpu / "cpufreq"
        path.mkdir(parents=True)
        (path / "scaling_governor").write_text(governor + "\n", encoding="utf-8")
        (path / "scaling_available_governors").write_text(available + "\n", encoding="utf-8")


class FakeCpupowerRunner:
    def __init__(self, root: Path, *, fails: bool = False) -> None:
        self.root = root
        self.fails = fails
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if self.fails:
            return subprocess.CompletedProcess(args, 1, "", "permission denied")
        for path in self.root.glob("cpu[0-9]*/cpufreq/scaling_governor"):
            path.write_text(args[-1] + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")


def fake_which(name: str) -> str | None:
    return {"cpupower": "/usr/bin/cpupower", "pkexec": "/usr/bin/pkexec"}.get(name)


class CpuModeBackendTests(unittest.TestCase):
    def test_reads_cpufreq_governor_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_cpu_files(root, "performance")
            backend = CpuModeBackend(config_dir=root / "config", sysfs_root=root, which=fake_which)
            state = backend.get_state()
        self.assertTrue(state.performance)
        self.assertEqual(state.source, "Linux CPUFreq governor")

    def test_enables_and_restores_previous_governor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_cpu_files(root, "powersave")
            runner = FakeCpupowerRunner(root)
            backend = CpuModeBackend(config_dir=root / "config", sysfs_root=root, runner=runner, which=fake_which)
            self.assertTrue(backend.enable_performance().performance)
            self.assertFalse(backend.disable_performance().performance)
            self.assertEqual((root / "cpu0/cpufreq/scaling_governor").read_text().strip(), "powersave")
            self.assertEqual(runner.calls[0], ["/usr/bin/pkexec", "/usr/bin/cpupower", "frequency-set", "--governor", "performance"])

    def test_rejects_driver_without_performance_governor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_cpu_files(root, "powersave", "powersave schedutil")
            backend = CpuModeBackend(config_dir=root / "config", sysfs_root=root, which=fake_which)
            with self.assertRaisesRegex(ModeError, "不提供 performance"):
                backend.enable_performance()

    def test_reports_cpupower_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_cpu_files(root, "powersave")
            backend = CpuModeBackend(config_dir=root / "config", sysfs_root=root, runner=FakeCpupowerRunner(root, fails=True), which=fake_which)
            with self.assertRaisesRegex(ModeError, "permission denied"):
                backend.enable_performance()

    def test_reports_unreadable_cpufreq(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            backend = CpuModeBackend(config_dir=Path(temp) / "config", sysfs_root=Path(temp), which=fake_which)
            with self.assertRaises(ModeError):
                backend.get_state()


if __name__ == "__main__":
    unittest.main()
