from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mumu_autotask.config import Settings
from mumu_autotask.mumu_manager import (
    MumuManagerClient,
    _profile_from_instance,
    resolve_mumu_manager_executable,
)


class MumuManagerTests(unittest.TestCase):
    def test_manager_is_resolved_beside_auto_detected_adb(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory)
            adb = install / "adb.exe"
            manager = install / "MuMuManager.exe"
            adb.touch()
            manager.touch()

            with patch(
                "mumu_autotask.mumu_manager.resolve_adb_executable",
                return_value=str(adb),
            ):
                resolved = resolve_mumu_manager_executable(Settings())

            self.assertEqual(resolved, str(manager.resolve()))

    @unittest.skipUnless(os.name == "nt", "Windows-only process flag")
    def test_manager_commands_never_create_a_console_window(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        client = MumuManagerClient("MuMuManager.exe")

        with patch("mumu_autotask.mumu_manager.subprocess.run", return_value=completed) as run:
            client.info_all()

        self.assertEqual(
            run.call_args.kwargs["creationflags"],
            subprocess.CREATE_NO_WINDOW,
        )

    def test_info_all_parses_official_window_handles(self) -> None:
        client = MumuManagerClient("MuMuManager.exe")
        client._run = lambda _args: json.dumps(
            {
                "3": {
                    "index": "3",
                    "name": "instance-three",
                    "android_version": "12.0",
                    "adb_host_ip": "127.0.0.1",
                    "adb_port": 16480,
                    "is_android_started": True,
                    "is_process_started": True,
                    "main_wnd": "003100D8",
                    "render_wnd": "094A0BFE",
                    "pid": 21920,
                }
            }
        )

        instance = client.info_all()[0]

        self.assertEqual(instance.main_wnd, int("003100D8", 16))
        self.assertEqual(instance.render_wnd, int("094A0BFE", 16))
        self.assertEqual(instance.serial, "127.0.0.1:16480")

    def test_discovered_profile_carries_mumu_window_identity(self) -> None:
        client = MumuManagerClient("MuMuManager.exe")
        client._run = lambda _args: json.dumps(
            {
                "0": {
                    "index": "0",
                    "name": "instance-zero",
                    "android_version": "12.0",
                    "adb_host_ip": "127.0.0.1",
                    "adb_port": 16384,
                    "is_android_started": True,
                    "is_process_started": True,
                    "main_wnd": "0ACC06D2",
                    "pid": 31992,
                }
            }
        )
        instance = client.info_all()[0]

        profile = _profile_from_instance(instance, {})

        self.assertIsNotNone(profile)
        self.assertEqual(profile.mumu_hwnd, int("0ACC06D2", 16))
        self.assertEqual(profile.mumu_pid, 31992)


if __name__ == "__main__":
    unittest.main()
