import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import system_monitor


class SystemMonitorTests(unittest.TestCase):
    def test_identifies_miner_using_both_product_markers(self):
        with tempfile.TemporaryDirectory() as root:
            sample = Path(root) / "xmrig"
            for payload, expected in (
                (b"\x7fELF xmrig stratum", "xmrig"),
                (b"\x7fELF xmrig", None),
                (b"xmrig stratum", None),
            ):
                with self.subTest(payload=payload):
                    sample.write_bytes(payload)
                    with sample.open("rb") as executable:
                        fd = executable.fileno()
                        self.assertEqual(system_monitor.matches_miner(fd, sample.name, os.fstat(fd)), expected)

    def test_parses_ssh_login_for_the_monitor_table(self):
        entry = {
            "MESSAGE": "Accepted publickey for tester from 192.0.2.1 port 32111 ssh2",
            "__REALTIME_TIMESTAMP": "1720000000000000",
        }
        event = system_monitor.ssh_event(entry)
        self.assertEqual(event["result"], "成功")
        self.assertEqual(event["address"], "192.0.2.1")
        self.assertEqual(event["port"], "32111")

    def test_contains_the_matched_process_and_its_executable(self):
        with tempfile.TemporaryDirectory() as root:
            sandbox = Path(root)
            executable = sandbox / "xmrig"
            executable.write_bytes(b"\x7fELF xmrig stratum")
            executable.chmod(0o755)
            proc = sandbox / "proc"
            pid = 1234
            (proc / str(pid)).mkdir(parents=True)
            (proc / str(pid) / "exe").symlink_to(executable)
            pidfd = os.open(os.devnull, os.O_RDONLY)

            with patch.object(os, "pidfd_open", return_value=pidfd) as open_pidfd:
                with patch.object(signal, "pidfd_send_signal") as send_signal:
                    event = system_monitor.contain(pid, proc=proc)

            open_pidfd.assert_called_once_with(pid)
            send_signal.assert_called_once_with(pidfd, signal.SIGKILL)
            self.assertEqual(executable.stat().st_mode & 0o777, 0o644)
            self.assertEqual(event["action"], "已发送终止信号 · 禁止执行")

    def test_writes_readable_heartbeat_atomically(self):
        with tempfile.TemporaryDirectory() as root:
            status = Path(root) / "status.json"
            snapshot = {"time": 10, "actions": [], "ssh_state": "已关闭"}
            system_monitor.write_json(status, snapshot)
            self.assertEqual(json.loads(status.read_text()), snapshot)
            self.assertEqual(status.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(root).iterdir()), [status])

    def test_supports_proc_scan_without_busybox(self):
        with patch.object(Path, "is_file", return_value=False):
            self.assertIn(os.getpid(), system_monitor.process_ids())
