from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock

from gpu_power_backend import GpuPowerBackend, GpuPowerError


GPU_0 = "0, GPU-a, NVIDIA GeForce RTX 4090, 150.00, 480.00, 450.00\n"
GPU_1 = '1, GPU-b, "NVIDIA GPU, second card", 100.00, 350.00, 300.00\n'
GPU_UNSUPPORTED = "2, GPU-c, NVIDIA GPU, [N/A], [N/A], [N/A]\n"


def response(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class GpuPowerBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = Mock(return_value=response(GPU_0))
        self.paths = {"nvidia-smi": "/usr/bin/nvidia-smi", "pkexec": "/usr/bin/pkexec"}
        self.backend = GpuPowerBackend(runner=self.runner, which=self.paths.get)

    def test_queries_power_ranges_without_privileges(self) -> None:
        self.runner.return_value = response(GPU_1 + GPU_UNSUPPORTED + GPU_0)
        first, second, unsupported = self.backend.get_states()
        self.assertEqual((first.index, first.allowed_range, first.limit_watts), (0, (150, 480), 450))
        self.assertEqual(second.name, "NVIDIA GPU, second card")
        self.assertIsNone(unsupported.allowed_range)
        self.assertIsNone(unsupported.limit_watts)
        self.runner.assert_called_once_with(
            ["/usr/bin/nvidia-smi", "--query-gpu=index,uuid,name,power.min_limit,power.max_limit,power.limit",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=False,
        )

    def test_applies_limit_at_either_boundary_and_reads_it_back(self) -> None:
        for watts in (100.0, 350.0):
            with self.subTest(watts=watts):
                self.runner.reset_mock()
                self.runner.side_effect = [
                    response(GPU_0 + GPU_1),
                    response("Limit applied"),
                    response(GPU_0 + GPU_1.replace("300.00", f"{watts:.2f}")),
                ]
                first, second = self.backend.set_limit("GPU-b", watts)
                self.assertEqual(first.limit_watts, 450)
                self.assertEqual(second.limit_watts, watts)
                query, setting, readback = [call.args[0] for call in self.runner.call_args_list]
                self.assertEqual(setting, ["/usr/bin/pkexec", "/usr/bin/nvidia-smi", "-i", "GPU-b", "-pl", str(watts)])
                self.assertEqual(query, readback)

    def test_rejects_out_of_range_or_nonfinite_input_before_authorization(self) -> None:
        for watts in (149.99, 480.01, float("nan"), float("inf")):
            with self.subTest(watts=watts):
                self.runner.reset_mock()
                with self.assertRaisesRegex(GpuPowerError, "150–480 W"):
                    self.backend.set_limit("GPU-a", watts)
                self.assertEqual(self.runner.call_count, 1)

    def test_rejects_unsupported_or_disappeared_gpu_before_authorization(self) -> None:
        self.runner.return_value = response(GPU_UNSUPPORTED)
        with self.assertRaisesRegex(GpuPowerError, "未报告可设置"):
            self.backend.set_limit("GPU-c", 200)
        with self.assertRaisesRegex(GpuPowerError, "找不到所选"):
            self.backend.set_limit("GPU-a", 200)
        self.assertEqual(self.runner.call_count, 2)

    def test_handles_missing_tool_and_no_devices(self) -> None:
        del self.paths["nvidia-smi"]
        with self.assertRaisesRegex(GpuPowerError, "未找到 nvidia-smi"):
            self.backend.get_states()
        self.runner.assert_not_called()
        self.paths["nvidia-smi"] = "/usr/bin/nvidia-smi"
        self.runner.return_value = response("No devices were found\n")
        self.assertEqual(self.backend.get_states(), [])

    def test_reports_authorization_cancelled(self) -> None:
        self.runner.side_effect = [response(GPU_0), response(returncode=126)]
        with self.assertRaisesRegex(GpuPowerError, "已取消管理员授权"):
            self.backend.set_limit("GPU-a", 480)
        self.assertEqual(self.runner.call_count, 2)

    def test_reports_readback_failure_after_setting(self) -> None:
        self.runner.side_effect = [response(GPU_0), response(), response(returncode=9, stderr="driver error")]
        with self.assertRaisesRegex(GpuPowerError, "回读失败.*driver error"):
            self.backend.set_limit("GPU-a", 480)


if __name__ == "__main__":
    unittest.main()
