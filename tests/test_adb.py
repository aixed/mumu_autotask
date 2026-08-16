from __future__ import annotations

import subprocess
import unittest
from collections.abc import Sequence

from mumu_autotask.adb import AdbClient, AdbError


class FakeRunner:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(
        self, args: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, self.output, "")


class MappingRunner:
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def __call__(
        self, args: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        key = tuple(args)
        return subprocess.CompletedProcess(args, 0, self.outputs.get(key, ""), "")


class FakeBinaryRunner:
    def __init__(self, output: bytes, *, returncode: int = 0) -> None:
        self.output = output
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(
        self, args: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(args))
        return subprocess.CompletedProcess(
            args,
            self.returncode,
            self.output,
            b"binary failure" if self.returncode else b"",
        )


class AdbTests(unittest.TestCase):
    def test_parses_connected_devices(self) -> None:
        runner = FakeRunner(
            "List of devices attached\n"
            "127.0.0.1:5557 device product:x model:V2344A transport_id:1\n"
            "emulator-5558 offline transport_id:2\n"
        )
        client = AdbClient("fake-adb", runner=runner)
        devices = client.devices()
        self.assertEqual([item.serial for item in devices], ["127.0.0.1:5557", "emulator-5558"])
        self.assertTrue(devices[0].connected)
        self.assertEqual(devices[0].details["model"], "V2344A")

    def test_requires_ready_state(self) -> None:
        runner = FakeRunner("List of devices attached\nemulator-1 offline\n")
        client = AdbClient("fake-adb", runner=runner)
        with self.assertRaisesRegex(AdbError, "offline"):
            client.require_connected(["emulator-1"])

    def test_parses_forward_list_with_distinct_local_and_remote_ports(self) -> None:
        runner = FakeRunner(
            "127.0.0.1:16384 tcp:27042 tcp:27042\n"
            "127.0.0.1:16416 tcp:27052 tcp:38417\n"
        )
        client = AdbClient("fake-adb", runner=runner)

        forwards = client.forward_list()

        self.assertEqual(
            [
                (forward.serial, forward.local, forward.remote)
                for forward in forwards
            ],
            [
                ("127.0.0.1:16384", "tcp:27042", "tcp:27042"),
                ("127.0.0.1:16416", "tcp:27052", "tcp:38417"),
            ],
        )
        self.assertEqual(runner.calls, [["fake-adb", "forward", "--list"]])

    def test_rejects_malformed_forward_list_entry(self) -> None:
        client = AdbClient(
            "fake-adb",
            runner=FakeRunner("127.0.0.1:16384 tcp:27042\n"),
        )
        with self.assertRaisesRegex(AdbError, "invalid ADB forward entry"):
            client.forward_list()

    def test_pidof_requires_exactly_one_numeric_pid(self) -> None:
        runner = FakeRunner("7359\n")
        client = AdbClient("fake-adb", runner=runner)
        self.assertEqual(client.pidof("device-1", "com.gof.global"), 7359)
        self.assertEqual(
            runner.calls[-1],
            ["fake-adb", "-s", "device-1", "shell", "pidof", "com.gof.global"],
        )

    def test_pidof_rejects_multiple_processes(self) -> None:
        client = AdbClient("fake-adb", runner=FakeRunner("7359 7360"))
        with self.assertRaisesRegex(AdbError, "expected one main PID"):
            client.pidof("device-1", "com.gof.global")

    def test_pidof_selects_exact_main_process_when_child_process_matches_prefix(self) -> None:
        runner = MappingRunner(
            {
                (
                    "fake-adb",
                    "-s",
                    "device-1",
                    "shell",
                    "pidof",
                    "com.gof.global",
                ): "7359 7360\n",
                (
                    "fake-adb",
                    "-s",
                    "device-1",
                    "shell",
                    "ps",
                    "-A",
                ): (
                    "USER PID PPID VSZ RSS WCHAN ADDR S NAME\n"
                    "u0_a123 7359 333 123 45 0 0 S com.gof.global\n"
                    "u0_a123 7360 333 123 45 0 0 S com.gof.global:push\n"
                ),
            }
        )
        client = AdbClient("fake-adb", runner=runner)

        self.assertEqual(client.pidof("device-1", "com.gof.global"), 7359)

    def test_pidof_rejects_ambiguous_exact_main_processes(self) -> None:
        runner = MappingRunner(
            {
                (
                    "fake-adb",
                    "-s",
                    "device-1",
                    "shell",
                    "pidof",
                    "com.gof.global",
                ): "7359 7360\n",
                (
                    "fake-adb",
                    "-s",
                    "device-1",
                    "shell",
                    "ps",
                    "-A",
                ): (
                    "USER PID PPID VSZ RSS WCHAN ADDR S NAME\n"
                    "u0_a123 7359 333 123 45 0 0 S com.gof.global\n"
                    "u0_a123 7360 333 123 45 0 0 S com.gof.global\n"
                ),
            }
        )
        client = AdbClient("fake-adb", runner=runner)

        with self.assertRaisesRegex(AdbError, "expected one main PID"):
            client.pidof("device-1", "com.gof.global")

    def test_foreground_activity_parses_resumed_activity(self) -> None:
        runner = FakeRunner(
            "    mResumedActivity: ActivityRecord{abc u0 "
            "com.gof.global/.MyMainPlayerActivity t12}\n"
        )
        client = AdbClient("fake-adb", runner=runner)

        activity = client.foreground_activity("device-1")

        self.assertEqual(
            activity.component,
            "com.gof.global/com.gof.global.MyMainPlayerActivity",
        )
        self.assertEqual(activity.source, "activity")
        self.assertTrue(
            activity.matches("com.gof.global/com.gof.global.MyMainPlayerActivity")
        )
        self.assertEqual(
            runner.calls[-1],
            [
                "fake-adb",
                "-s",
                "device-1",
                "shell",
                "dumpsys",
                "activity",
                "activities",
            ],
        )

    def test_foreground_activity_falls_back_to_window_focus(self) -> None:
        runner = MappingRunner(
            {
                (
                    "fake-adb",
                    "-s",
                    "device-1",
                    "shell",
                    "dumpsys",
                    "activity",
                    "activities",
                ): "no resumed app\n",
                (
                    "fake-adb",
                    "-s",
                    "device-1",
                    "shell",
                    "dumpsys",
                    "window",
                ): "mCurrentFocus=Window{123 u0 "
                "com.gof.global/com.unity3d.player.MyMainPlayerActivity}\n",
            }
        )
        client = AdbClient("fake-adb", runner=runner)

        activity = client.foreground_activity("device-1")

        self.assertEqual(
            activity.component,
            "com.gof.global/com.unity3d.player.MyMainPlayerActivity",
        )
        self.assertEqual(activity.source, "window")
        self.assertTrue(
            activity.matches(
                "com.gof.global/com.unity3d.player.MyMainPlayerActivity"
            )
        )

    def test_foreground_activity_reports_absent_focus(self) -> None:
        client = AdbClient("fake-adb", runner=FakeRunner("no focus\n"))

        activity = client.foreground_activity("device-1")

        self.assertFalse(activity.present)
        self.assertFalse(
            activity.matches(
                "com.gof.global/com.unity3d.player.MyMainPlayerActivity"
            )
        )

    def test_exec_out_uses_binary_runner_without_text_conversion(self) -> None:
        binary = FakeBinaryRunner(b"\x00\xff\r\n")
        client = AdbClient(
            "fake-adb",
            runner=FakeRunner(""),
            binary_runner=binary,
        )
        result = client.exec_out("device-1", "su", "0", "cat", "/proc/7/mem")
        self.assertEqual(result, b"\x00\xff\r\n")
        self.assertEqual(
            binary.calls,
            [
                [
                    "fake-adb",
                    "-s",
                    "device-1",
                    "exec-out",
                    "su",
                    "0",
                    "cat",
                    "/proc/7/mem",
                ]
            ],
        )

    def test_exec_out_surfaces_binary_stderr(self) -> None:
        binary = FakeBinaryRunner(b"", returncode=1)
        client = AdbClient(
            "fake-adb",
            runner=FakeRunner(""),
            binary_runner=binary,
        )
        with self.assertRaisesRegex(AdbError, "binary failure"):
            client.exec_out("device-1", "su", "0", "cat", "/proc/7/mem")

    def test_input_tap_uses_adb_shell_coordinates(self) -> None:
        runner = FakeRunner("")
        client = AdbClient("fake-adb", runner=runner)

        client.input_tap("device-1", 200, 1212)

        self.assertEqual(
            runner.calls[-1],
            ["fake-adb", "-s", "device-1", "shell", "input", "tap", "200", "1212"],
        )

    def test_input_tap_rejects_invalid_coordinates(self) -> None:
        client = AdbClient("fake-adb", runner=FakeRunner(""))

        for x, y in ((-1, 0), (0, -1), (True, 0), (0, False)):
            with self.subTest(x=x, y=y):
                with self.assertRaisesRegex(AdbError, "tap coordinates"):
                    client.input_tap("device-1", x, y)  # type: ignore[arg-type]

    def test_window_size_parses_physical_size(self) -> None:
        runner = FakeRunner("Physical size: 720x1280\n")
        client = AdbClient("fake-adb", runner=runner)

        size = client.window_size("device-1")

        self.assertEqual((size.width, size.height), (720, 1280))
        self.assertEqual(
            runner.calls[-1],
            ["fake-adb", "-s", "device-1", "shell", "wm", "size"],
        )

    def test_window_size_rejects_unparseable_output(self) -> None:
        client = AdbClient("fake-adb", runner=FakeRunner("no size here\n"))

        with self.assertRaisesRegex(AdbError, "could not parse window size"):
            client.window_size("device-1")


if __name__ == "__main__":
    unittest.main()
