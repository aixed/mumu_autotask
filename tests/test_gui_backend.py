from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mumu_autotask.gui import CATEGORY_META, QUALITY_META, build_parser
from mumu_autotask.gui_backend import (
    CliRunner,
    CommandResult,
    GuiBackend,
    GuiBackendError,
    GuiPreferences,
    console_python_executable,
    parse_json_lines,
)


class FakeRunner:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def run(self, arguments, *, timeout: float) -> CommandResult:
        arguments = tuple(arguments)
        self.calls.append((arguments, timeout))
        return CommandResult(arguments, 0, self.outputs.pop(0), "")


class GuiBackendTests(unittest.TestCase):
    def test_preferences_save_and_reload_each_device_section_independently(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gui_preferences.json"
            preferences = GuiPreferences(path)
            preferences.set_selected_qualities(
                "127.0.0.1:16384",
                ("blue", "purple"),
            )
            preferences.set_selected_qualities(
                "127.0.0.1:16416",
                ("green", "yellow"),
            )
            preferences.set_selected_categories(
                "127.0.0.1:16384",
                ("monster", "hero"),
            )
            preferences.set_selected_categories(
                "127.0.0.1:16416",
                ("rescue",),
            )

            reloaded = GuiPreferences(path)

            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16384"),
                ("blue", "purple"),
            )
            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16416"),
                ("green", "yellow"),
            )
            self.assertEqual(
                reloaded.get_selected_categories("127.0.0.1:16384"),
                ("monster", "hero"),
            )
            self.assertEqual(
                reloaded.get_selected_categories("127.0.0.1:16416"),
                ("rescue",),
            )
            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16480"),
                ("purple",),
            )
            self.assertEqual(
                reloaded.get_selected_categories("127.0.0.1:16480"),
                tuple(CATEGORY_META),
            )

    def test_updating_one_device_does_not_modify_another_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gui_preferences.json"
            preferences = GuiPreferences(path)
            preferences.set_selected_qualities(
                "127.0.0.1:16384",
                ("blue",),
            )
            preferences.set_selected_qualities(
                "127.0.0.1:16416",
                ("yellow",),
            )

            preferences.set_selected_qualities(
                "127.0.0.1:16384",
                ("green", "purple"),
            )

            reloaded = GuiPreferences(path)
            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16384"),
                ("green", "purple"),
            )
            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16416"),
                ("yellow",),
            )

    def test_preferences_reject_invalid_serials_and_qualities(self) -> None:
        preferences = GuiPreferences(None)
        for serial in ("", "device\n2"):
            with self.subTest(serial=repr(serial)):
                with self.assertRaisesRegex(GuiBackendError, "ADB serial"):
                    preferences.set_selected_qualities(serial, ("purple",))
        with self.assertRaisesRegex(GuiBackendError, "未知值"):
            preferences.set_selected_qualities("127.0.0.1:16384", ("orange",))

    def test_json_lines_accepts_one_or_more_objects(self) -> None:
        payloads = parse_json_lines('{"serial":"a"}\n\n{"serial":"b"}\n')
        self.assertEqual(payloads, ({"serial": "a"}, {"serial": "b"}))

    def test_json_lines_rejects_empty_invalid_or_non_object_output(self) -> None:
        for output, message in (
            ("", "没有返回"),
            ("not-json", "不是有效"),
            ("[]", "必须是对象"),
        ):
            with self.subTest(output=output):
                with self.assertRaisesRegex(GuiBackendError, message):
                    parse_json_lines(output)

    def test_runner_builds_module_command_with_absolute_config(self) -> None:
        runner = CliRunner("config.json", python_executable="python.exe")
        command = runner.command("status", "--all")
        self.assertEqual(command[0:3], ("python.exe", "-m", "mumu_autotask"))
        self.assertEqual(command[-2:], ("status", "--all"))
        self.assertTrue(Path(command[4]).is_absolute())

    def test_runner_serial_cancellation_matches_only_explicit_serial_argument(self) -> None:
        runner = CliRunner("config.json", python_executable="python.exe")

        self.assertTrue(
            runner._command_targets_serial(  # type: ignore[attr-defined]
                ("python.exe", "-m", "mumu_autotask", "status", "--serial", "device-1"),
                "device-1",
            )
        )
        self.assertFalse(
            runner._command_targets_serial(  # type: ignore[attr-defined]
                ("python.exe", "-m", "mumu_autotask", "devices", "--connect"),
                "device-1",
            )
        )
        self.assertFalse(
            runner._command_targets_serial(  # type: ignore[attr-defined]
                ("python.exe", "-m", "mumu_autotask", "status", "--serial", "device-2"),
                "device-1",
            )
        )

    def test_runner_preserves_bounded_frida_error_context_without_stdout(self) -> None:
        class FailedProcess:
            returncode = 2

            def communicate(self, timeout=None):
                return (
                    '{"serial":"device-1","unrelated":"payload"}\n',
                    "2026-08-16 15:55:53,000 WARNING mumu_autotask.cli "
                    "startup warning\n"
                    "2026-08-16 15:55:54,000 ERROR mumu_autotask.cli "
                    "cannot execute Lua code: \x1b[31mTypeError: invalid argument\x1b[0m\n"
                    "    at invoke (/node_modules/frida-java-bridge/lib/class-factory.js:1800)\n"
                    "    at <anonymous> "
                    "(/node_modules/frida-java-bridge/lib/class-factory.js:1866)\n",
                )

        runner = CliRunner("config.json", python_executable="python.exe")
        with (
            patch(
                "mumu_autotask.gui_backend.subprocess.Popen",
                return_value=FailedProcess(),
            ),
            self.assertRaises(GuiBackendError) as raised,
        ):
            runner.run(("march", "--serial", "device-1"), timeout=150)

        error = raised.exception
        self.assertEqual(
            error.summary,
            "cannot execute Lua code: TypeError: invalid argument",
        )
        self.assertIn("class-factory.js:1800", error.diagnostic)
        self.assertIn("class-factory.js:1866", error.diagnostic)
        self.assertEqual(str(error), error.diagnostic)
        self.assertNotIn("startup warning", error.diagnostic)
        self.assertNotIn("unrelated", error.diagnostic)
        self.assertNotIn("\x1b", error.diagnostic)

    def test_runner_stdout_fallback_keeps_only_the_final_plain_error_line(self) -> None:
        class FailedProcess:
            returncode = 2

            def communicate(self, timeout=None):
                return (
                    '{"serial":"device-1","unrelated":"payload"}\n'
                    "plain command failure\n",
                    "",
                )

        runner = CliRunner("config.json", python_executable="python.exe")
        with (
            patch(
                "mumu_autotask.gui_backend.subprocess.Popen",
                return_value=FailedProcess(),
            ),
            self.assertRaises(GuiBackendError) as raised,
        ):
            runner.run(("status", "--serial", "device-1"), timeout=30)

        self.assertEqual(str(raised.exception), "plain command failure")
        self.assertNotIn("serial", raised.exception.diagnostic)

    def test_runner_bounds_oversized_error_context_and_keeps_tail_frames(self) -> None:
        stack = "\n".join(
            f"    at frame{index} (/node_modules/frida-java-bridge/index.js:{index})"
            for index in range(200)
        )

        class FailedProcess:
            returncode = 2

            def communicate(self, timeout=None):
                return (
                    "",
                    "2026-08-16 15:55:54,000 ERROR mumu_autotask.cli "
                    f"TypeError: root cause\n{stack}\n",
                )

        runner = CliRunner("config.json", python_executable="python.exe")
        with (
            patch(
                "mumu_autotask.gui_backend.subprocess.Popen",
                return_value=FailedProcess(),
            ),
            self.assertRaises(GuiBackendError) as raised,
        ):
            runner.run(("march", "--serial", "device-1"), timeout=150)

        diagnostic = raised.exception.diagnostic
        self.assertTrue(diagnostic.startswith("TypeError: root cause\n"))
        self.assertIn("已省略中间部分", diagnostic)
        self.assertIn("index.js:199", diagnostic)
        self.assertLessEqual(len(diagnostic.splitlines()), 80)

    def test_pythonw_is_replaced_with_console_python_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pythonw = root / "pythonw.exe"
            python = root / "python.exe"
            pythonw.touch()
            python.touch()
            self.assertEqual(console_python_executable(str(pythonw)), str(python))

    def test_backend_status_and_inspection_require_single_json_object(self) -> None:
        runner = FakeRunner(
            [
                '{"serial":"device-1","kingdom":4549}\n',
                '{"serial":"device-1","items":[]}\n',
                '{"serial":"device-1","items":[],"categories":{"monster":0,"hero":0,"rescue":0}}\n',
            ]
        )
        backend = GuiBackend(runner)  # type: ignore[arg-type]
        self.assertEqual(backend.status("device-1")["kingdom"], 4549)
        self.assertEqual(backend.inspect_intel("device-1")["items"], [])
        self.assertEqual(backend.inspect_tasks("device-1")["categories"]["rescue"], 0)
        self.assertEqual(
            runner.calls,
            [
                (("status", "--serial", "device-1", "--prepare-frida"), 60),
                (("inspect-intel", "--serial", "device-1", "--execute"), 90),
                (("inspect-tasks", "--serial", "device-1", "--execute"), 90),
            ],
        )

    def test_backend_march_always_uses_explicit_execute(self) -> None:
        runner = FakeRunner(
            ['{"serial":"device-1","request_dispatched":true}\n']
        )
        backend = GuiBackend(runner)  # type: ignore[arg-type]
        payload = backend.march("device-1", "purple")
        self.assertTrue(payload["request_dispatched"])
        self.assertEqual(
            runner.calls[0],
            (
                (
                    "march",
                    "--serial",
                    "device-1",
                    "--quality",
                    "purple",
                    "--execute",
                ),
                150,
            ),
        )

    def test_backend_ensure_world_uses_explicit_execute_and_expected_role(self) -> None:
        runner = FakeRunner(
            ['{"serial":"device-1","world_ready":true}\n']
        )
        backend = GuiBackend(runner)  # type: ignore[arg-type]

        payload = backend.ensure_world("device-1", expected_role="打工人")

        self.assertTrue(payload["world_ready"])
        self.assertEqual(
            runner.calls[0],
            (
                (
                    "ensure-world",
                    "--serial",
                    "device-1",
                    "--expected-role",
                    "打工人",
                    "--execute",
                ),
                45,
            ),
        )

    def test_backend_march_can_bind_an_exact_runtime_id(self) -> None:
        runner = FakeRunner(
            ['{"serial":"device-1","request_dispatched":true}\n']
        )
        backend = GuiBackend(runner)  # type: ignore[arg-type]

        backend.march(
            "device-1",
            "purple",
            runtime_id=436,
            expected_role="打工人",
        )

        self.assertEqual(
            runner.calls[0][0],
            (
                "march",
                "--serial",
                "device-1",
                "--quality",
                "purple",
                "--target-id",
                "436",
                "--expected-role",
                "打工人",
                "--execute",
            ),
        )

    def test_backend_batch_intel_uses_one_explicit_execute_command(self) -> None:
        runner = FakeRunner(['{"serial":"device-1","results":[]}\n'])
        backend = GuiBackend(runner)  # type: ignore[arg-type]

        backend.batch_intel(
            "device-1",
            (
                {"category": "monster", "runtime_id": 420, "quality": "yellow"},
                {"category": "hero", "runtime_id": 501, "quality": "blue"},
                {"category": "rescue", "runtime_id": 601, "quality": "green"},
            ),
            expected_role="打工人",
        )

        arguments, timeout = runner.calls[0]
        self.assertEqual(timeout, 300)
        self.assertEqual(
            arguments[:4],
            (
                "batch-intel",
                "--serial",
                "device-1",
                "--target-json",
            ),
        )
        self.assertEqual(
            arguments[-3:],
            ("--expected-role", "打工人", "--execute"),
        )
        payloads = [
            json.loads(arguments[index + 1])
            for index, value in enumerate(arguments)
            if value == "--target-json"
        ]
        self.assertEqual(
            payloads,
            [
                {"category": "monster", "runtime_id": 420, "quality": "yellow"},
                {"category": "hero", "runtime_id": 501, "quality": "blue"},
                {"category": "rescue", "runtime_id": 601, "quality": "green"},
            ],
        )

    def test_backend_wait_and_claim_keep_every_exact_target_id(self) -> None:
        runner = FakeRunner(
            [
                '{"serial":"device-1","completed_target_ids":[436,437]}\n',
                '{"serial":"device-1","statuses_after":[]}\n',
                '{"serial":"device-1","claimed_target_ids":[436,437]}\n',
            ]
        )
        backend = GuiBackend(runner)  # type: ignore[arg-type]

        backend.wait_intel("device-1", (436, 437), expected_role="打工人")
        backend.intel_status("device-1", (436, 437), expected_role="打工人")
        backend.claim_intel("device-1", (436, 437), expected_role="打工人")

        self.assertEqual(
            runner.calls,
            [
                (
                    (
                        "wait-intel",
                        "--serial",
                        "device-1",
                        "--target-id",
                        "436",
                        "--target-id",
                        "437",
                        "--expected-role",
                        "打工人",
                        "--execute",
                    ),
                    1860,
                ),
                (
                    (
                        "claim-intel",
                        "--serial",
                        "device-1",
                        "--target-id",
                        "436",
                        "--target-id",
                        "437",
                        "--expected-role",
                        "打工人",
                    ),
                    120,
                ),
                (
                    (
                        "claim-intel",
                        "--serial",
                        "device-1",
                        "--target-id",
                        "436",
                        "--target-id",
                        "437",
                        "--expected-role",
                        "打工人",
                        "--execute",
                    ),
                    180,
                ),
            ],
        )

    def test_backend_wait_and_claim_reject_invalid_target_sets(self) -> None:
        backend = GuiBackend(FakeRunner([]))  # type: ignore[arg-type]
        for target_ids in ((), (1, 1), (0,), (True,)):
            with self.subTest(target_ids=target_ids):
                with self.assertRaises(GuiBackendError):
                    backend.wait_intel("device-1", target_ids)  # type: ignore[arg-type]

    def test_backend_rejects_invalid_expected_role_before_running(self) -> None:
        runner = FakeRunner([])
        backend = GuiBackend(runner)  # type: ignore[arg-type]
        for role in ("", "打工\n人", "a" * 65):
            with self.subTest(role=repr(role)):
                with self.assertRaisesRegex(GuiBackendError, "预期角色"):
                    backend.march(
                        "device-1",
                        "purple",
                        runtime_id=436,
                        expected_role=role,
                    )
        self.assertEqual(runner.calls, [])

    def test_backend_rejects_ambiguous_single_device_response(self) -> None:
        runner = FakeRunner(['{"serial":"a"}\n{"serial":"b"}\n'])
        backend = GuiBackend(runner)  # type: ignore[arg-type]
        with self.assertRaisesRegex(GuiBackendError, "意外的数据条数"):
            backend.status("device-1")

    def test_gui_exposes_four_supported_qualities(self) -> None:
        self.assertEqual(
            tuple(QUALITY_META),
            ("green", "blue", "purple", "yellow"),
        )

    def test_gui_parser_accepts_an_explicit_config(self) -> None:
        args = build_parser().parse_args(("--config", "custom.json"))
        self.assertEqual(args.config, "custom.json")

    def test_batch_launcher_starts_the_gui_module(self) -> None:
        batch = (
            Path(__file__).resolve().parents[1] / "start_mumu_autotask.bat"
        ).read_text(encoding="utf-8")
        self.assertIn("-m mumu_autotask.gui", batch)
        self.assertIn("%~dp0config.json", batch)
        self.assertIn("PYTHONPATH", batch)


if __name__ == "__main__":
    unittest.main()
