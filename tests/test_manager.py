import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "scripts" / "firefox_sessions.py"
SPEC = importlib.util.spec_from_file_location("firefox_sessions", MANAGER)
firefox_sessions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firefox_sessions)


class LayoutTest(unittest.TestCase):
    def test_single_workspace_expands_to_hold_sixteen_sessions_each(self):
        self.assertEqual(
            firefox_sessions.workspace_targets(["special:firefox-sessions"], 48),
            ["special:firefox-sessions", "special:firefox-sessions-2", "special:firefox-sessions-3"],
        )
        self.assertEqual(firefox_sessions.workspace_targets(["3"], 48), ["3", "4", "5"])

    def test_sessions_are_assigned_in_groups_of_sixteen(self):
        targets = ["3", "4", "5"]
        self.assertEqual(firefox_sessions.workspace_for_session(1, targets), "3")
        self.assertEqual(firefox_sessions.workspace_for_session(16, targets), "3")
        self.assertEqual(firefox_sessions.workspace_for_session(17, targets), "4")
        self.assertEqual(firefox_sessions.workspace_for_session(48, targets), "5")

    def test_sixteen_windows_fill_an_equal_four_by_four_grid(self):
        monitor = {
            "x": 0,
            "y": 0,
            "width": 3840,
            "height": 2160,
            "scale": 1.6,
            "reserved": [0, 26, 0, 0],
        }

        cells = firefox_sessions.grid_cells(monitor, 16)

        self.assertEqual(len(cells), 16)
        self.assertEqual(len({width for _, _, width, _ in cells}), 1)
        self.assertEqual(len({height for _, _, _, height in cells}), 1)
        self.assertEqual(len({x for x, _, _, _ in cells}), 4)
        self.assertEqual(len({y for _, y, _, _ in cells}), 4)


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.home = self.root / "home"
        self.runtime = self.root / "runtime"
        self.bin = self.root / "bin"
        self.home.mkdir()
        self.runtime.mkdir(mode=0o700)
        self.bin.mkdir()
        self.firefox = self.bin / "firefox"
        self.firefox.write_text(
            "#!/usr/bin/env python3\n"
            "import signal\n"
            "import time\n"
            "signal.signal(signal.SIGTERM, lambda *_: raise_exit())\n"
            "def raise_exit():\n"
            "    raise SystemExit(0)\n"
            "while True:\n"
            "    time.sleep(1)\n"
        )
        self.firefox.chmod(0o755)
        self.env = os.environ | {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "FIREFOX_SESSIONS_FIREFOX": str(self.firefox),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
        }

    def tearDown(self):
        self.run_cli("stop", check=False)
        self.tempdir.cleanup()

    def run_cli(self, *args, check=True):
        return subprocess.run(
            [sys.executable, str(MANAGER), *args],
            env=self.env,
            text=True,
            capture_output=True,
            check=check,
            timeout=10,
        )

    def status(self):
        result = self.run_cli("status", "--json")
        return json.loads(result.stdout)

    def test_defaults_and_configuration_are_persisted(self):
        status = self.status()
        self.assertEqual(status["configured"], 48)
        self.assertEqual(status["running"], 0)
        self.assertEqual(status["url"], "about:blank")
        self.assertEqual(status["workspaces"], ["special:firefox-sessions"])

        self.run_cli(
            "configure",
            "--count",
            "24",
            "--url",
            "https://example.com/path?a=1",
            "--workspaces",
            "4, 5, special:research",
        )

        status = self.status()
        self.assertEqual(status["configured"], 24)
        self.assertEqual(status["url"], "https://example.com/path?a=1")
        self.assertEqual(status["workspaces"], ["4", "5", "special:research"])

    def test_launch_starts_only_missing_sessions(self):
        first = self.run_cli(
            "launch", "--count", "2", "--url", "https://example.com", "--stagger-ms", "1", "--json"
        )
        events = [json.loads(line) for line in first.stdout.splitlines()]
        self.assertEqual(events[-1]["launched"], 2)
        self.assertEqual(self.status()["running"], 2)

        second = self.run_cli("launch", "--json", "--stagger-ms", "1")
        final = json.loads(second.stdout.splitlines()[-1])
        self.assertEqual(final["launched"], 0)
        self.assertEqual(final["running"], 2)

        profiles = self.home / ".local" / "share" / "firefox-sessions"
        self.assertTrue((profiles / "profile-01").is_dir())
        self.assertTrue((profiles / "profile-02").is_dir())
        state_file = self.runtime / "firefox-sessions" / "state.json"
        state = json.loads(state_file.read_text())
        first_args = Path(f"/proc/{state['sessions']['1']['pid']}/cmdline").read_bytes().split(b"\0")
        self.assertIn(b"firefox-sessions-01", first_args)

    def test_stop_does_not_touch_untracked_process(self):
        outside = subprocess.Popen(
            [str(self.firefox), "--profile", str(self.root / "ordinary")],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.run_cli("launch", "--count", "1", "--stagger-ms", "1")
            self.run_cli("stop")
            self.assertIsNone(outside.poll())
            self.assertEqual(self.status()["running"], 0)
        finally:
            outside.terminate()
            outside.wait(timeout=5)

    def test_reset_requires_confirmation_and_removes_only_profile_root(self):
        self.run_cli("launch", "--count", "1", "--stagger-ms", "1")
        unrelated = self.home / ".local" / "share" / "keep-me"
        unrelated.mkdir(parents=True)

        denied = self.run_cli("reset", check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertTrue((self.home / ".local" / "share" / "firefox-sessions").exists())

        self.run_cli("reset", "--yes")

        self.assertFalse((self.home / ".local" / "share" / "firefox-sessions").exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(self.status()["running"], 0)

    def test_reset_refuses_a_linked_profile_root(self):
        data_home = self.home / ".local" / "share"
        profiles = data_home / "firefox-sessions"
        unrelated = data_home / "keep-me"
        unrelated.mkdir(parents=True)
        profiles.symlink_to(unrelated, target_is_directory=True)

        result = self.run_cli("reset", "--yes", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(unrelated.exists())
        self.assertTrue(profiles.is_symlink())

    def test_invalid_values_are_rejected(self):
        bad_count = self.run_cli("configure", "--count", "0", check=False)
        bad_url = self.run_cli("configure", "--url", "javascript:alert(1)", check=False)
        self.assertNotEqual(bad_count.returncode, 0)
        self.assertNotEqual(bad_url.returncode, 0)

    def test_focus_cycles_through_normal_and_special_workspaces(self):
        calls = self.root / "hyprctl-calls"
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> '{calls}'\n"
            "case \"$*\" in *'-j'*) printf '[]\\n' ;; esac\n"
        )
        hyprctl.chmod(0o755)
        self.run_cli("configure", "--workspaces", "4,5,special:research")

        self.run_cli("focus")
        self.run_cli("focus")
        self.run_cli("focus")

        self.assertEqual(
            calls.read_text().splitlines(),
            [
                'eval hl.dispatch(hl.dsp.focus({ workspace = "4" }))',
                'eval hl.dispatch(hl.dsp.focus({ workspace = "5" }))',
                'eval hl.dispatch(hl.dsp.workspace.toggle_special("research"))',
            ],
        )

    def test_placement_targets_only_managed_window_classes(self):
        calls = self.root / "placement-calls"
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text(
            "#!/bin/sh\n"
            "if [ \"$*\" = 'clients -j' ]; then\n"
            "  printf '%s\\n' '[{\"address\":\"0x1\",\"initialClass\":\"firefox\",\"monitor\":0},{\"address\":\"0x2\",\"initialClass\":\"firefox-sessions-01\",\"monitor\":0}]'\n"
            "elif [ \"$*\" = 'monitors -j' ]; then\n"
            "  printf '%s\\n' '[{\"id\":0,\"x\":0,\"y\":0,\"width\":3840,\"height\":2160,\"scale\":1.6,\"reserved\":[0,26,0,0]}]'\n"
            "else\n"
            f"  printf '%s\\n' \"$*\" >> '{calls}'\n"
            "fi\n"
        )
        hyprctl.chmod(0o755)

        self.run_cli("_place", '{"firefox-sessions-01":"special:research"}')

        self.assertEqual(
            calls.read_text().splitlines(),
            [
                'eval hl.dispatch(hl.dsp.window.move({ workspace = "special:research", follow = false, window = "address:0x2" }))',
                'eval hl.dispatch(hl.dsp.window.float({ action = "enable", window = "address:0x2" }))',
                'eval hl.dispatch(hl.dsp.window.resize({ x = 2380, y = 1304, relative = false, window = "address:0x2" }))',
                'eval hl.dispatch(hl.dsp.window.move({ x = 10, y = 36, relative = false, window = "address:0x2" }))',
            ],
        )

    def install_fake_systemctl(self):
        calls = self.root / "systemctl-calls"
        systemctl = self.bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> '{calls}'\n"
        )
        systemctl.chmod(0o755)
        return calls

    def add_schedule(self, action="launch"):
        at = (datetime.now().astimezone() + timedelta(days=2)).replace(microsecond=0)
        result = self.run_cli(
            "schedule",
            "add",
            "--at",
            at.strftime("%Y-%m-%d %H:%M:%S"),
            "--action",
            action,
            "--json",
        )
        return at, json.loads(result.stdout)

    def test_one_off_schedule_can_be_listed_and_cancelled(self):
        calls = self.install_fake_systemctl()

        at, created = self.add_schedule("relaunch")
        listed = json.loads(self.run_cli("schedule", "list", "--json").stdout)

        self.assertEqual(listed, [created])
        self.assertEqual(created["action"], "relaunch")
        timer = self.home / ".config" / "systemd" / "user" / f"{created['unit']}.timer"
        service = timer.with_suffix(".service")
        self.assertIn(f"OnCalendar={at.strftime('%Y-%m-%d %H:%M:%S')}", timer.read_text())
        self.assertIn("Persistent=true", timer.read_text())
        self.assertIn(f"_scheduled {created['id']}", service.read_text())
        self.assertIn("KillMode=process", service.read_text())

        self.run_cli("schedule", "cancel", created["id"])

        self.assertFalse(timer.exists())
        self.assertFalse(service.exists())
        self.assertEqual(json.loads(self.run_cli("schedule", "list", "--json").stdout), [])
        self.assertIn(f"--user enable --now {created['unit']}.timer", calls.read_text())
        self.assertIn(f"--user disable --now {created['unit']}.timer", calls.read_text())

    def test_schedule_rejects_a_past_time(self):
        self.install_fake_systemctl()
        past = (datetime.now().astimezone() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

        result = self.run_cli("schedule", "add", "--at", past, "--action", "launch", check=False)

        self.assertNotEqual(result.returncode, 0)

    def test_schedule_rolls_back_when_timer_activation_fails(self):
        systemctl = self.bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in *'enable --now'*) printf 'activation failed\\n' >&2; exit 1 ;; esac\n"
        )
        systemctl.chmod(0o755)
        at = (datetime.now().astimezone() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

        result = self.run_cli(
            "schedule", "add", "--at", at, "--action", "launch", check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.run_cli("schedule", "list", "--json").stdout), [])
        unit_root = self.home / ".config" / "systemd" / "user"
        self.assertEqual(list(unit_root.glob("firefox-sessions-*")), [])

    def test_executed_schedule_runs_once_and_removes_itself(self):
        calls = self.install_fake_systemctl()
        self.run_cli("configure", "--count", "1")
        _, created = self.add_schedule("launch")

        self.run_cli("_scheduled", created["id"])

        self.assertEqual(self.status()["running"], 1)
        self.assertEqual(json.loads(self.run_cli("schedule", "list", "--json").stdout), [])
        unit_root = self.home / ".config" / "systemd" / "user"
        self.assertFalse((unit_root / f"{created['unit']}.timer").exists())
        self.assertFalse((unit_root / f"{created['unit']}.service").exists())
        self.assertIn(f"--user disable --now {created['unit']}.timer", calls.read_text())


if __name__ == "__main__":
    unittest.main()
