import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DistributionTest(unittest.TestCase):
    def test_marketplace_layout_and_bundled_manager(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        panel = ROOT / manifest["entryPoints"]["barWidget"]
        self.assertTrue(panel.is_file())
        source = panel.read_text()
        self.assertIn('Qt.resolvedUrl("../scripts/firefox_sessions.py")', source)
        self.assertNotIn('["firefox-sessions",', source)

    def test_cli_install_update_and_removal_keep_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = os.environ | {"HOME": directory, "XDG_CONFIG_HOME": str(home / "config"),
                                "XDG_DATA_HOME": str(home / "data"),
                                "XDG_RUNTIME_DIR": str(home / "runtime")}
            bin_dir = home / "bin"
            bin_dir.mkdir()
            for command in ("omarchy", "omarchy-shell", "systemctl"):
                stub = bin_dir / command
                stub.write_text("#!/bin/sh\nexit 0\n")
                stub.chmod(0o755)
            env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
            profile = home / "data/firefox-sessions/profile-01"
            profile.mkdir(parents=True)
            marker = profile / "cookies"
            marker.write_text("keep")
            timer = home / "config/systemd/user/firefox-sessions-other.timer"
            timer.parent.mkdir(parents=True)
            timer.write_text("keep")
            for _ in range(2):
                subprocess.run([str(ROOT / "install.sh")], env=env, check=True, capture_output=True)
            self.assertFalse((home / "config/omarchy/plugins").exists())
            result = subprocess.run([str(home / ".local/bin/firefox-sessions"), "status", "--json"],
                                    env=env, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout)["running"], 0)
            subprocess.run([str(ROOT / "uninstall.sh")], env=env, check=True, capture_output=True)
            self.assertEqual(marker.read_text(), "keep")
            self.assertEqual(timer.read_text(), "keep")
            self.assertFalse((home / ".local/bin/firefox-sessions").exists())

    def test_purge_rejects_linked_roots_and_keeps_other_files(self):
        for root in ("data", "config"):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                env = os.environ | {"HOME": directory, "XDG_CONFIG_HOME": str(home / "config"),
                                    "XDG_DATA_HOME": str(home / "data"),
                                    "XDG_RUNTIME_DIR": str(home / "runtime")}
                outside = home / "outside"
                outside.mkdir()
                marker = outside / "keep"
                marker.write_text("keep")
                if root == "config":
                    data = home / "data/firefox-sessions"
                    data.mkdir(parents=True)
                    (data / "keep").write_text("keep")
                parent = home / root
                parent.mkdir()
                (parent / "firefox-sessions").symlink_to(outside, target_is_directory=True)
                result = subprocess.run([str(ROOT / "uninstall.sh"), "--purge", "--yes"],
                                        env=env, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(marker.read_text(), "keep")
                if root == "config":
                    self.assertEqual((data / "keep").read_text(), "keep")

    def test_purge_requires_confirmation_before_cli_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = os.environ | {"HOME": directory, "XDG_CONFIG_HOME": str(home / "config"),
                                "XDG_DATA_HOME": str(home / "data"),
                                "XDG_RUNTIME_DIR": str(home / "runtime")}
            subprocess.run([str(ROOT / "install.sh")], env=env, check=True, capture_output=True)
            result = subprocess.run([str(ROOT / "uninstall.sh"), "--purge"],
                                    env=env, input="", text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((home / ".local/bin/firefox-sessions").exists())

    def test_purge_removes_only_application_data(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = os.environ | {"HOME": directory, "XDG_CONFIG_HOME": str(home / "config"),
                                "XDG_DATA_HOME": str(home / "data"),
                                "XDG_RUNTIME_DIR": str(home / "runtime")}
            for root in ("data", "config"):
                app = home / root / "firefox-sessions"
                app.mkdir(parents=True)
                (app / "remove").write_text("remove")
                (app.parent / "keep").write_text("keep")
            subprocess.run([str(ROOT / "uninstall.sh"), "--purge", "--yes"],
                           env=env, check=True, capture_output=True)
            for root in ("data", "config"):
                self.assertFalse((home / root / "firefox-sessions").exists())
                self.assertEqual((home / root / "keep").read_text(), "keep")
