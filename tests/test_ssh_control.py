import tempfile
import unittest
from pathlib import Path

from ssh_control import AUTH, CONFIG_TEXT, SSHD, SOCKET, SYSTEMCTL, UNITS, disable_ssh, enable_ssh


class EnableSshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / "key-only.conf"
        self.runtime = Path(temporary.name) / "sshd"
        self.calls = []
        self.effective = {key.lower(): value for key, value in AUTH.items()}
        self.active = "inactive\ninactive"
        self.fail_start = False

    def run_command(self, *args, check=True):
        self.calls.append(args)
        if args == (SYSTEMCTL, "is-active", *UNITS):
            return self.active
        if args[0:2] == (SYSTEMCTL, "is-enabled"):
            return "masked"
        if args == (SSHD, "-T"):
            return "\n".join(f"{key} {value}" for key, value in self.effective.items())
        if self.fail_start and args == (SYSTEMCTL, "enable", "--now", SOCKET):
            raise RuntimeError("socket startup failed")
        return ""

    def enable(self):
        return enable_ssh(self.config, self.runtime, self.run_command)

    def test_validates_key_only_policy_before_starting_socket(self):
        self.assertIn("已开启", self.enable())
        self.assertEqual(self.config.read_text(), CONFIG_TEXT)
        validation = self.calls.index((SSHD, "-T"))
        unmask = self.calls.index((SYSTEMCTL, "unmask", *UNITS))
        self.assertLess(validation, unmask)
        self.assertEqual(self.calls[-2:], [
            (SYSTEMCTL, "enable", "--now", SOCKET),
            (SYSTEMCTL, "is-active", "--quiet", SOCKET),
        ])

    def test_conflicting_effective_auth_never_unmasks_or_starts(self):
        self.effective["passwordauthentication"] = "yes"
        with self.assertRaisesRegex(RuntimeError, "PasswordAuthentication"):
            self.enable()
        self.assertFalse(self.config.exists())
        self.assertFalse(any(call[1] in {"unmask", "enable"} for call in self.calls))

    def test_start_failure_restores_masks_and_new_configuration(self):
        self.fail_start = True
        with self.assertRaisesRegex(RuntimeError, "socket startup failed"):
            self.enable()
        self.assertFalse(self.config.exists())
        self.assertIn((SYSTEMCTL, "stop", *UNITS), self.calls)
        self.assertIn((SYSTEMCTL, "disable", SOCKET), self.calls)
        for unit in UNITS:
            self.assertIn((SYSTEMCTL, "mask", unit), self.calls)

    def test_running_ssh_is_left_alone(self):
        self.active = "active\ninactive"
        self.assertIn("已在运行", self.enable())
        self.assertEqual(self.calls, [(SYSTEMCTL, "is-active", *UNITS)])
        self.assertFalse(self.config.exists())


class DisableSshTests(unittest.TestCase):
    def call(self, *, after="inactive\ninactive", enabled="enabled"):
        calls = []
        masked = False

        def run(*args, check=True):
            nonlocal masked
            calls.append(args)
            if args == (SYSTEMCTL, "mask", *UNITS):
                masked = True
            if args == (SYSTEMCTL, "is-active", *UNITS):
                return after
            if args[:2] == (SYSTEMCTL, "is-enabled"):
                return "masked" if masked else enabled if args[2] == SOCKET else "disabled"
            return ""

        return calls, run

    def test_stops_both_units_and_disables_socket(self):
        calls, run = self.call()
        self.assertIn("已关闭", disable_ssh(run))
        self.assertEqual(calls[0], (SYSTEMCTL, "stop", *UNITS))
        self.assertIn((SYSTEMCTL, "disable", SOCKET), calls)
        self.assertIn((SYSTEMCTL, "mask", *UNITS), calls)

    def test_already_stopped_units_do_not_need_disable(self):
        calls, run = self.call(enabled="masked")
        self.assertIn("已关闭", disable_ssh(run))
        self.assertFalse(any(call[1] == "disable" for call in calls))

    def test_reports_if_socket_remains_active(self):
        _, run = self.call(after="active\ninactive")
        with self.assertRaisesRegex(RuntimeError, "监听已停止"):
            disable_ssh(run)


if __name__ == "__main__":
    unittest.main()
