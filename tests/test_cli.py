from __future__ import annotations

import argparse
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from mumu_autotask.adb import AdbDevice, ForegroundActivity
from mumu_autotask.cli import build_parser, execute, main
from mumu_autotask.business import (
    BusinessError,
    build_inspect_intel_lua,
    build_intel_status_lua,
    build_scene_status_lua,
    script_sha256,
)
from mumu_autotask.config import DeviceProfile, Settings
from mumu_autotask.frida_driver import (
    FridaDriverError,
    LuaExecutionError,
    LuaExecutionResult,
)
from mumu_autotask.kingdom import KingdomGuardError
from mumu_autotask.lua_state import LuaStateScanError
from mumu_autotask.lua_safety import LuaSafetyError


def prefs_xml(value: int) -> str:
    return f'<map><int name="__KEY_KINGDOM__" value="{value}" /></map>'


def sdk_xml(value: int) -> str:
    return (
        '<map><string name="CONTEXT_UTILS_RECENTLY_SERVERID">'
        f"{value}</string></map>"
    )


class FakeAdb:
    def __init__(
        self,
        events: list[str],
        *,
        playerprefs_kingdom: int = 4549,
        sdk_server_id: int = 4549,
        pids: tuple[int, ...] = (7359,),
        activity: str | None = "com.gof.global/com.unity3d.player.MyMainPlayerActivity",
        activities: tuple[str | None, ...] | None = None,
        window_size: tuple[int, int] = (720, 1280),
    ) -> None:
        self.events = events
        self.playerprefs_kingdom = playerprefs_kingdom
        self.sdk_server_id = sdk_server_id
        self.pids = list(pids)
        self.activities = list(activities) if activities is not None else [activity]
        self.window_size_value = window_size

    def require_connected(self, serials) -> None:
        self.events.append("adb-ready")

    def devices(self):
        self.events.append("adb-devices")
        return [
            AdbDevice("device-1", "device", {"model": "fake"}),
            AdbDevice("device-2", "device", {"model": "fake"}),
        ]

    def connect_configured(self, targets):
        self.events.append("adb-connect:" + ",".join(targets))
        return [
            AdbDevice(str(target), "device", {"model": "fake"})
            for target in targets
        ]

    def forward_list(self):
        self.events.append("forward-list")
        return []

    def forward(self, serial: str, local: str, remote: str) -> str:
        self.events.append(f"forward:{serial}:{local}->{remote}")
        return local.rpartition(":")[2]

    def forward_remove(self, serial: str, local: str) -> str:
        self.events.append(f"forward-remove:{serial}:{local}")
        return ""

    def shell(self, serial: str, *args: str) -> str:
        if args[-1].endswith("com.cg.sdk.xml"):
            self.events.append("sdk-read")
            return sdk_xml(self.sdk_server_id)
        self.events.append("prefs-read")
        return prefs_xml(self.playerprefs_kingdom)

    def pidof(self, serial: str, package_name: str) -> int:
        self.events.append("adb-pid")
        if len(self.pids) > 1:
            return self.pids.pop(0)
        return self.pids[0]

    def foreground_activity(self, serial: str) -> ForegroundActivity:
        self.events.append("foreground-activity")
        if len(self.activities) > 1:
            component = self.activities.pop(0)
        else:
            component = self.activities[0]
        return ForegroundActivity(component, "fake", f"fake {component}")

    def window_size(self, serial: str):
        self.events.append("window-size")
        return SimpleNamespace(
            width=self.window_size_value[0],
            height=self.window_size_value[1],
        )

    def input_tap(self, serial: str, x: int, y: int) -> str:
        self.events.append(f"input-tap:{x},{y}")
        return ""


class FakeClient:
    def __init__(
        self,
        events: list[str],
        *,
        fail_initialize: bool = False,
        fail_execute: bool = False,
        output: str = "Lua 5.1",
        outputs: tuple[str | Exception, ...] | None = None,
        thread_name: str = "UnityMain",
    ) -> None:
        self.events = events
        self.fail_initialize = fail_initialize
        self.fail_execute = fail_execute
        self.output = output
        self.outputs = list(outputs) if outputs is not None else None
        self.thread_name = thread_name
        self.candidate = SimpleNamespace(
            address=0x7B7029221380,
            address_text="0x7b7029221380",
            cframe=0,
        )

    def __enter__(self):
        self.events.append("frida-attach")
        return self

    def __exit__(self, *args) -> None:
        self.events.append("frida-detach")

    def inspect_process(self):
        self.events.append("frida-inspect")
        return SimpleNamespace(pid=7359, name="Whiteout Survival")

    def initialize_bridge(self, path: str):
        self.events.append("bridge-initialize")
        if self.fail_initialize:
            raise FridaDriverError("initialize failed")
        return {"arch": "x64", "probe": "81985529216486895"}

    def execute_lua(self, state_address: int, code: str, **kwargs):
        self.events.append("lua-execute")
        if self.fail_execute:
            raise LuaExecutionError(
                "execution failed",
                output="load error",
                result_code=-12,
            )
        output = self.outputs.pop(0) if self.outputs is not None else self.output
        if isinstance(output, Exception):
            raise output
        return LuaExecutionResult(output, 8, 8123, self.thread_name)


class FakeScanner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.candidate = SimpleNamespace(
            address=0x7B7029221380,
            address_text="0x7b7029221380",
            cframe=0,
        )

    def find_unique_idle_main(self, pid: int):
        self.events.append("state-scan")
        return self.candidate

    def verify_idle_main(self, pid: int, address: int):
        self.events.append("state-verify")
        return self.candidate


class BusyThenIdleScanner(FakeScanner):
    def __init__(self, events: list[str], busy_count: int) -> None:
        super().__init__(events)
        self.busy_count = busy_count

    def find_unique_idle_main(self, pid: int):
        self.events.append("state-scan")
        if self.busy_count > 0:
            self.busy_count -= 1
            raise LuaStateScanError("main Lua state is busy")
        return self.candidate


def exec_args(code: str, *, dry_run: bool = True) -> argparse.Namespace:
    return argparse.Namespace(
        command="exec-lua",
        serial="device-1",
        code=code,
        file=None,
        allow_unsafe_lua=False,
        dry_run=dry_run,
    )


def business_args(
    command: str,
    *,
    dry_run: bool = True,
    category: str | None = None,
    quality: str | None = None,
    target_id: int | None = None,
    target_ids: list[int] | None = None,
    batch_targets: list[str] | None = None,
    timeout: float = 1.0,
    poll_interval: float = 0.05,
    expected_role: str | None = None,
    output_file=None,
    keep_hook: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        serial="device-1",
        category=category,
        quality=quality,
        target_id=target_id,
        target_ids=target_ids,
        batch_targets=batch_targets,
        timeout=timeout,
        poll_interval=poll_interval,
        expected_role=expected_role,
        output_file=output_file,
        keep_hook=keep_hook,
        dry_run=dry_run,
    )


def status_protocol(role: str, *targets: str) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tINTEL_STATUS",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            *targets,
            f"END\t{len(targets)}",
        )
    )


def battle_intel_protocol(role: str, *items: str) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tBATTLE_INTEL",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            *items,
            f"END\t{len(items)}",
        )
    )


def rescue_commit_protocol(role: str, target_id: int) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tRESCUE_COMMIT",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            f"TARGET\t{target_id}",
            "WORLD_MARCH\t1",
            "TYPE\t301",
            "MARCH_MAP_TYPE\t1",
            "END\t1",
        )
    )


def battle_verify_protocol(
    role: str,
    target_id: int,
    *,
    accepted: bool = True,
    status: str = "2",
) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tBATTLE_VERIFY",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            f"TARGET\t{target_id}",
            f"ACCEPTED\t{int(accepted)}\tSTATUS\t{status}",
            "END\t1",
        )
    )


def claim_protocol(role: str, target_ids: tuple[int, ...], *, sent: bool) -> str:
    targets = "\t".join(str(runtime_id) for runtime_id in target_ids)
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tCLAIM_INTEL",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            f"TARGETS\t{len(target_ids)}\t{targets}",
            f"SENT\t{int(sent)}",
            f"IDEMPOTENT\t{int(not sent)}",
            "END\t1",
        )
    )


def capture_records_protocol(role: str) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tMARCH_CAPTURE_RECORDS",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            "COUNT\t1",
            "BEGIN_RECORD\t1",
            "RECORD\t1\tWorldMarchHelper.RequestMarchStartOff",
            "ARGC\t6",
            "END_RECORD\t1",
            "END\t1",
        )
    )


def capture_install_protocol(role: str) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tMARCH_CAPTURE_HOOK",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            "INSTALLED\t1",
            "END\t1",
        )
    )


def capture_unhook_protocol(role: str) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tMARCH_CAPTURE_UNHOOK",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            "RESTORED\t2",
            "END\t1",
        )
    )


def formation_protocol(role: str, target_id: int = 70) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tFORMATION",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            f"TARGET\t{target_id}",
            "STATUS\t1",
            "CITY\t700\t701",
            "POINT_END\t759\t774",
            "MONSTER\t813",
            "STAMINA\t10",
            "MARCH_MAP_TYPE\t1",
            "MARCH_TYPE\t302",
            "MAP_OBJECT_TYPE\t4",
            "FORMATION_MARCH_TYPE\t302",
            "FORMATION_LIMIT\t14000",
            "SELECTED\t14000",
            "HERO_COUNT\t3",
            "HERO\t1\t50006",
            "SOLDIER_COUNT\t1",
            "SOLDIER\t10100\t14000",
            "END\t1",
        )
    )


def scene_protocol(
    role: str,
    *,
    scene_type: str = "3",
    class_name: str = "WorldScene",
    map_type: str = "1",
    is_world: bool = True,
    is_city: bool = False,
    loading: str = "false",
    transition: str = "false",
) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tSCENE",
            f"ROLE\t{role.encode('utf-8').hex()}",
            "KINGDOM\t4549",
            f"SCENE\t{scene_type}\tCLASS\t{class_name}",
            f"MAP\t{map_type}",
            f"WORLD\t{int(is_world)}\tCITY\t{int(is_city)}",
            f"BUSY\tLOADING\t{loading}\tTRANSITION\t{transition}",
            "END\t1",
        )
    )


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        scanner_patch = patch(
            "mumu_autotask.cli._scanner",
            side_effect=lambda adb, profile: FakeScanner(adb.events),
        )
        scanner_patch.start()
        self.addCleanup(scanner_patch.stop)

    def test_parser_defaults_to_dry_run_and_requires_execute_opt_in(self) -> None:
        parser = build_parser()
        base = [
            "exec-lua",
            "--serial",
            "device-1",
            "--code",
            "return tostring(_VERSION)",
        ]
        self.assertTrue(parser.parse_args(base).dry_run)
        self.assertFalse(parser.parse_args([*base, "--execute"]).dry_run)
        for command in (
            "inspect-intel",
            "ensure-world",
            "wait-intel",
            "claim-intel",
            "march",
            "batch-intel",
            "inspect-formation",
            "capture-march",
            "unhook-march-capture",
        ):
            with self.subTest(command=command):
                args = [command, "--serial", "device-1"]
                if command in {"march", "inspect-formation"}:
                    args.extend(("--quality", "orange"))
                elif command == "batch-intel":
                    args.extend(("--target", "monster:71:yellow"))
                elif command in {"wait-intel", "claim-intel"}:
                    args.extend(
                        (
                            "--expected-role",
                            "打工的",
                            "--target-id",
                            "71",
                            "--target-id",
                            "72",
                        )
                    )
                self.assertTrue(parser.parse_args(args).dry_run)
                self.assertFalse(parser.parse_args([*args, "--execute"]).dry_run)
        capture_args = parser.parse_args(
            ["capture-march", "--serial", "device-1", "--execute", "--keep-hook"]
        )
        self.assertFalse(capture_args.dry_run)
        self.assertTrue(capture_args.keep_hook)
        for command in ("wait-intel", "claim-intel"):
            with self.subTest(command=command, missing="expected-role"):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(
                            [command, "--serial", "device-1", "--target-id", "71"]
                        )

    def test_capture_march_keep_hook_skips_uninstall(self) -> None:
        events: list[str] = []
        role = "打工的"
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(
                        capture_install_protocol(role),
                        capture_records_protocol(role),
                    ),
                ),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "capture-march",
                        dry_run=False,
                        expected_role=role,
                        keep_hook=True,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["captured_request"])
        self.assertEqual(result["record_count"], 1)
        self.assertFalse(result["hook_uninstalled"])
        self.assertTrue(result["hook_left_installed"])
        self.assertEqual(events.count("lua-execute"), 2)
        self.assertEqual(events.count("frida-attach"), 1)
        self.assertEqual(events.count("frida-detach"), 1)

    def test_capture_march_default_uninstalls_after_capture(self) -> None:
        events: list[str] = []
        role = "打工的"
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(
                        capture_install_protocol(role),
                        capture_records_protocol(role),
                        capture_unhook_protocol(role),
                    ),
                ),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "capture-march",
                        dry_run=False,
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["hook_uninstalled"])
        self.assertFalse(result["hook_left_installed"])
        self.assertEqual(events.count("lua-execute"), 3)

    def test_unhook_march_capture_executes_uninstall_script(self) -> None:
        events: list[str] = []
        role = "打工的"
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(capture_unhook_protocol(role),),
                ),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "unhook-march-capture",
                        dry_run=False,
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertIn("MARCH_CAPTURE_UNHOOK", result["output"])
        self.assertEqual(events.count("lua-execute"), 1)

    def test_inspect_formation_executes_readonly_payload(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        intel = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tINTEL",
                f"ROLE\t{role_hex}",
                "KINGDOM\t4549",
                "ITEM\t70\t1700\t1\t759\t774\t1900000000"
                "\tpurple\t4\t813\t13\t10",
                "END\t1",
            )
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(intel, formation_protocol(role, 70)),
                ),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "inspect-formation",
                        dry_run=False,
                        quality="purple",
                        target_id=70,
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["target"]["runtime_id"], 70)
        self.assertFalse(result["request_dispatched"])
        self.assertIn("MARCH_TYPE\t302", result["output"])
        self.assertEqual(events.count("lua-execute"), 2)
        self.assertFalse(any(event.startswith("input-tap:") for event in events))

    def test_devices_connect_restores_configured_frida_forwards(self) -> None:
        events: list[str] = []
        settings = Settings.from_dict(
            {
                "adb": {"connect_targets": ["device-1", "device-2"]},
                "devices": [
                    {
                        "serial": "device-1",
                        "frida_host": "127.0.0.1:27042",
                    },
                    {
                        "serial": "device-2",
                        "frida_host": "127.0.0.1:27052",
                        "frida_remote_port": 38417,
                    },
                ],
            }
        )
        output = io.StringIO()
        args = argparse.Namespace(command="devices", connect=True)

        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(execute(args, settings), 0)

        self.assertIn("adb-connect:device-1,device-2", events)
        self.assertIn("forward:device-1:tcp:27042->tcp:27042", events)
        self.assertIn("forward:device-2:tcp:27052->tcp:38417", events)
        self.assertIn("device-1\tdevice\tfake", output.getvalue())
        self.assertIn("device-2\tdevice\tfake", output.getvalue())

    def test_status_reports_both_kingdom_sources_without_ui_input(self) -> None:
        events: list[str] = []
        settings = Settings(
            devices=(
                DeviceProfile(
                    "device-1",
                    instance_name="MuMuPlayer-12.0-1",
                    roles=("打工的",),
                ),
            )
        )
        output = io.StringIO()
        args = argparse.Namespace(command="status", serial="device-1")
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(execute(args, settings), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["playerprefs_kingdom"], 4549)
        self.assertEqual(result["sdk_server_id"], 4549)
        self.assertEqual(result["roles"], ["打工的"])
        self.assertTrue(result["frida_forward_ready"])
        self.assertTrue(result["frida_forward_created"])
        self.assertTrue(result["frida_ready"])
        self.assertFalse(result["bridge_initialized"])
        self.assertIsNone(result["bridge_arch"])
        self.assertEqual(
            result["activity"],
            "com.gof.global/com.unity3d.player.MyMainPlayerActivity",
        )
        self.assertTrue(result["game_activity_foreground"])
        self.assertNotIn("background", events)
        self.assertIn("foreground-activity", events)
        self.assertIn("forward:device-1:tcp:27042->tcp:27042", events)
        self.assertIn("frida-inspect", events)
        self.assertNotIn("frida-attach", events)
        self.assertNotIn("bridge-initialize", events)

    def test_status_prepare_frida_initializes_bridge_once(self) -> None:
        events: list[str] = []
        settings = Settings(
            devices=(
                DeviceProfile(
                    "device-1",
                    instance_name="MuMuPlayer-12.0-1",
                    roles=("打工的",),
                ),
            )
        )
        output = io.StringIO()
        args = argparse.Namespace(
            command="status",
            serial="device-1",
            prepare_frida=True,
        )
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(execute(args, settings), 0)

        result = json.loads(output.getvalue())
        self.assertTrue(result["frida_ready"])
        self.assertTrue(result["bridge_initialized"])
        self.assertEqual(result["bridge_arch"], "x64")
        self.assertIn("frida-attach", events)
        self.assertIn("bridge-initialize", events)
        self.assertIn("frida-detach", events)
        self.assertLess(events.index("frida-attach"), events.index("bridge-initialize"))

    def test_default_dry_run_stops_before_scan_or_attach(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(exec_args("return tostring(_VERSION)"), settings),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["lua_executed"])
        self.assertLess(events.index("prefs-read"), events.index("frida-inspect"))
        self.assertLess(events.index("sdk-read"), events.index("frida-inspect"))
        self.assertLess(events.index("foreground-activity"), events.index("frida-inspect"))
        self.assertLess(events.index("adb-pid"), events.index("frida-inspect"))
        self.assertNotIn("state-scan", events)
        self.assertNotIn("frida-attach", events)
        self.assertNotIn("bridge-initialize", events)
        self.assertNotIn("lua-execute", events)

    def test_execute_uses_direct_rpc_with_pre_and_post_state_checks(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["lua_executed"])
        self.assertEqual(result["lua_state"], "0x7b7029221380")
        self.assertEqual(result["execution_thread_name"], "UnityMain")
        self.assertEqual(events.count("state-verify"), 3)
        self.assertEqual(events.count("foreground-activity"), 3)
        self.assertEqual(events.count("adb-pid"), 3)
        ordered = [
            "prefs-read",
            "sdk-read",
            "foreground-activity",
            "adb-pid",
            "frida-inspect",
            "state-scan",
            "frida-attach",
            "bridge-initialize",
            "state-verify",
            "foreground-activity",
            "adb-pid",
            "state-verify",
            "lua-execute",
            "foreground-activity",
            "adb-pid",
            "state-verify",
            "frida-detach",
        ]
        positions: list[int] = []
        for item in ordered:
            positions.append(events.index(item, positions[-1] + 1 if positions else 0))
        self.assertEqual(positions, sorted(positions))

    def test_wrong_or_disagreeing_kingdom_stops_before_frida(self) -> None:
        for playerprefs, sdk in ((4550, 4550), (4549, 4550)):
            with self.subTest(playerprefs=playerprefs, sdk=sdk):
                events: list[str] = []
                settings = Settings(devices=(DeviceProfile("device-1"),))
                with (
                    patch(
                        "mumu_autotask.cli._adb",
                        return_value=FakeAdb(
                            events,
                            playerprefs_kingdom=playerprefs,
                            sdk_server_id=sdk,
                        ),
                    ),
                    patch(
                        "mumu_autotask.cli._client",
                        return_value=FakeClient(events),
                    ),
                ):
                    with self.assertRaises(KingdomGuardError):
                        execute(
                            exec_args(
                                "return tostring(_VERSION)",
                                dry_run=False,
                            ),
                            settings,
                        )
                self.assertNotIn("frida-inspect", events)
                self.assertNotIn("frida-attach", events)

    def test_access_violation_stops_without_retrying_lua(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(
                        FridaDriverError(
                            "cannot execute Lua code: access violation accessing 0x0"
                        ),
                        "Lua 5.1",
                    ),
                ),
            ),
        ):
            with self.assertRaisesRegex(FridaDriverError, "access violation"):
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                )
        self.assertEqual(events.count("lua-execute"), 1)
        self.assertEqual(events.count("frida-detach"), 1)

    def test_background_service_pid_stops_before_frida(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with (
            patch(
                "mumu_autotask.cli._adb",
                return_value=FakeAdb(
                    events,
                    activity="com.android.launcher/.Launcher",
                ),
            ),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
        ):
            with self.assertRaisesRegex(FridaDriverError, "not in foreground"):
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                )
        self.assertIn("foreground-activity", events)
        self.assertNotIn("adb-pid", events)
        self.assertNotIn("frida-inspect", events)
        self.assertNotIn("frida-attach", events)

    def test_status_reports_background_service_as_not_foreground_without_frida(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1", roles=("打工的",)),))
        output = io.StringIO()
        with (
            patch(
                "mumu_autotask.cli._adb",
                return_value=FakeAdb(
                    events,
                    activity="com.android.launcher/.Launcher",
                ),
            ),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(argparse.Namespace(command="status", serial="device-1"), settings),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertFalse(result["game_activity_foreground"])
        self.assertEqual(result["process"], "-")
        self.assertFalse(result["frida_ready"])
        self.assertFalse(result["bridge_initialized"])
        self.assertIsNone(result["bridge_arch"])
        self.assertNotIn("frida-inspect", events)

    def test_unsafe_lua_is_rejected_before_adb(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)):
            with self.assertRaises(LuaSafetyError):
                execute(exec_args("GoOnMarch()", dry_run=False), settings)
        self.assertEqual(events, [])

    def test_initialize_failure_detaches_after_adb_state_scan(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, fail_initialize=True),
            ),
        ):
            with self.assertRaisesRegex(FridaDriverError, "initialize failed"):
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                )
        self.assertEqual(events.count("state-scan"), 1)
        self.assertEqual(events[-2:], ["bridge-initialize", "frida-detach"])

    def test_execute_failure_still_revalidates_and_detaches(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, fail_execute=True),
            ),
        ):
            with self.assertRaises(LuaExecutionError):
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                )
        self.assertEqual(events.count("state-verify"), 3)
        self.assertEqual(events[-4:], ["foreground-activity", "adb-pid", "state-verify", "frida-detach"])

    def test_changed_adb_pid_fails_after_execution_and_before_post_verify(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with (
            patch(
                "mumu_autotask.cli._adb",
                return_value=FakeAdb(events, pids=(7359, 9001)),
            ),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
        ):
            with self.assertRaisesRegex(FridaDriverError, "PID changed"):
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                )
        self.assertEqual(events[-3:], ["foreground-activity", "adb-pid", "frida-detach"])
        self.assertEqual(events.count("state-verify"), 1)

    def test_foreground_drift_before_execution_fails_before_lua_call(self) -> None:
        events: list[str] = []
        settings = Settings(devices=(DeviceProfile("device-1"),))
        with (
            patch(
                "mumu_autotask.cli._adb",
                return_value=FakeAdb(
                    events,
                    activities=(
                        "com.gof.global/com.unity3d.player.MyMainPlayerActivity",
                        "com.android.launcher/.Launcher",
                    ),
                ),
            ),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
        ):
            with self.assertRaisesRegex(FridaDriverError, "not in foreground"):
                execute(
                    exec_args("return tostring(_VERSION)", dry_run=False),
                    settings,
                )
        self.assertEqual(events.count("lua-execute"), 0)
        self.assertEqual(events.count("state-verify"), 1)
        self.assertEqual(events[-2:], ["foreground-activity", "frida-detach"])

    def test_inspect_intel_dry_run_validates_roles_before_adb(self) -> None:
        settings = Settings(devices=(DeviceProfile("device-1", roles=()),))
        with patch("mumu_autotask.cli._adb") as adb_factory:
            with self.assertRaisesRegex(BusinessError, "no configured role"):
                execute(business_args("inspect-intel"), settings)
        adb_factory.assert_not_called()

    def test_main_converts_business_errors_to_exit_code_two(self) -> None:
        settings = Settings(
            devices=(DeviceProfile("device-1", roles=("打工的",)),)
        )
        with (
            patch("mumu_autotask.cli.load_settings", return_value=settings),
            patch(
                "mumu_autotask.cli.execute",
                side_effect=BusinessError("blocked business operation"),
            ),
        ):
            self.assertEqual(main(["--config", "ignored.json", "validate"]), 2)

    def test_inspect_intel_dry_run_reports_script_hash_without_attach(self) -> None:
        events: list[str] = []
        roles = ("打工的",)
        settings = Settings(devices=(DeviceProfile("device-1", roles=roles),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(execute(business_args("inspect-intel"), settings), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(
            result["script_sha256"],
            script_sha256(build_inspect_intel_lua(roles)),
        )
        self.assertEqual(result["operation"], "inspect-intel")
        self.assertNotIn("frida-attach", events)
        self.assertNotIn("state-scan", events)

    def test_inspect_intel_execute_parses_role_and_items(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        protocol = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tINTEL",
                f"ROLE\t{role_hex}",
                "KINGDOM\t4549",
                "ITEM\t70\t1700\t0\t700\t701\t1800000000\tgreen\t2\t808\t8\t10",
                "END\t1",
            )
        )
        settings = Settings(
            devices=(DeviceProfile("device-1", roles=(role,)),)
        )
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, output=protocol),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args("inspect-intel", dry_run=False),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["role"], role)
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["items"][0]["quality"], "green")

    def test_ensure_world_dry_run_reports_scene_without_tapping(self) -> None:
        events: list[str] = []
        role = "打工的"
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    output=scene_protocol(role),
                ),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(execute(business_args("ensure-world"), settings), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(
            result["script_sha256"],
            script_sha256(build_scene_status_lua((role,))),
        )
        self.assertTrue(result["world_ready"])
        self.assertFalse(result["tap_invoked"])
        self.assertEqual(result["scene_after"]["class"], "WorldScene")
        self.assertNotIn("input-tap:652,1213", events)

    def test_ensure_world_waits_for_busy_lua_state_without_tapping(self) -> None:
        events: list[str] = []
        role = "打工的"
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._scanner",
                side_effect=lambda adb, profile: BusyThenIdleScanner(
                    adb.events,
                    busy_count=2,
                ),
            ),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    output=scene_protocol(role),
                ),
            ),
            patch("mumu_autotask.cli.time.sleep") as sleep,
            redirect_stdout(output),
        ):
            self.assertEqual(execute(business_args("ensure-world"), settings), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["world_ready"])
        self.assertFalse(result["tap_invoked"])
        self.assertEqual(events.count("state-scan"), 3)
        self.assertNotIn("input-tap:652,1213", events)
        sleep.assert_any_call(0.05)
        self.assertEqual(sleep.call_count, 2)

    def test_ensure_world_execute_taps_city_and_waits_until_world_ready(self) -> None:
        events: list[str] = []
        role = "打工的"
        outputs = (
            scene_protocol(
                role,
                scene_type="2",
                class_name="CityScene",
                is_world=False,
                is_city=True,
            ),
            scene_protocol(role, loading="true", transition="true"),
            scene_protocol(role),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            patch("mumu_autotask.cli.time.sleep"),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args("ensure-world", dry_run=False),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["world_ready"])
        self.assertTrue(result["tap_invoked"])
        self.assertEqual(result["tap_coordinates"], [652, 1213])
        self.assertEqual(result["poll_count"], 2)
        self.assertIn("input-tap:652,1213", events)

    def test_ensure_world_execute_waits_for_scene_modules_after_cold_start(self) -> None:
        events: list[str] = []
        role = "打工的"
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(
                        LuaExecutionError(
                            "Lua execution failed with bridge result -80: "
                            "game/module/logic/PlayerTop:0: "
                            "attempt to index field 'm_modules' (a nil value)",
                            output="not ready",
                            result_code=-80,
                        ),
                        scene_protocol(role),
                    ),
                ),
            ),
            patch("mumu_autotask.cli.time.sleep") as sleep,
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args("ensure-world", dry_run=False),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["world_ready"])
        self.assertFalse(result["tap_invoked"])
        self.assertEqual(events.count("lua-execute"), 2)
        self.assertNotIn("input-tap:652,1213", events)
        sleep.assert_called_once_with(0.05)

    def test_march_dry_run_selects_target_without_opening_expedition(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        protocol = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tINTEL",
                f"ROLE\t{role_hex}",
                "KINGDOM\t4549",
                "ITEM\t70\t1700\t1\t700\t701\t1900000000\tyellow\t5\t808\t8\t10",
                "END\t1",
            )
        )
        settings = Settings(
            devices=(DeviceProfile("device-1", roles=(role,)),)
        )
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, output=protocol),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(business_args("march", quality="orange"), settings),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["quality"], "yellow")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["march_executed"])
        self.assertFalse(result["request_dispatched"])
        self.assertEqual(result["target"]["runtime_id"], 70)
        self.assertEqual(events.count("lua-execute"), 1)

    def test_march_execute_accepts_new_self_march_before_status_change(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        item = (
            "ITEM\t70\t1700\t1\t700\t701\t1900000000"
            "\tpurple\t4\t808\t8\t10"
        )
        target_lines = (
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tINTEL",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    item,
                    "END\t1",
                )
            ),
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tOPEN",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    "OPENED\t1",
                    "END\t1",
                )
            ),
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tREADY",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    "READY\t1",
                    "END\t1",
                )
            ),
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tVERIFY",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    "ACCEPTED\t1\tSTATUS\t1",
                    "MARCH\t1\tEVENT\tmissing",
                    "PROOF\tMARCH_FIELDS",
                    "END\t1",
                )
            ),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=target_lines),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args("march", dry_run=False, quality="purple"),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["request_dispatched"])
        self.assertEqual(result["quest_status_after"], "1")
        self.assertTrue(result["average_tapped"])
        self.assertTrue(result["go_tapped"])
        self.assertEqual(events.count("frida-attach"), 1)
        self.assertEqual(events.count("frida-detach"), 1)
        self.assertEqual(events.count("lua-execute"), 4)
        self.assertEqual(result["verification_polls"], 1)

    def test_march_execute_uses_direct_commit_on_frida_direct(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        outputs = (
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tINTEL",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "ITEM\t70\t1700\t1\t700\t701\t1900000000"
                    "\tpurple\t4\t808\t8\t10",
                    "END\t1",
                )
            ),
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tCOMMIT",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    "AVERAGE\t1",
                    "GO\t1",
                    "END\t1",
                )
            ),
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tVERIFY",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    "ACCEPTED\t1\tSTATUS\t2",
                    "MARCH\t0\tEVENT\t0",
                    "PROOF\tQUEST_STATUS",
                    "END\t1",
                )
            ),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=outputs,
                    thread_name="FridaDirect",
                ),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args("march", dry_run=False, quality="purple"),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["request_dispatched"])
        self.assertEqual(result["dispatch_mode"], "direct")
        self.assertEqual(result["quest_status_after"], "2")
        self.assertFalse(any(event.startswith("input-tap:") for event in events))
        self.assertEqual(events.count("lua-execute"), 3)

    def test_battle_intel_rescue_execute_uses_world_march_commit(self) -> None:
        events: list[str] = []
        role = "打工的"
        target_id = 438
        outputs = (
            battle_intel_protocol(
                role,
                "ITEM\t438\t2438\t1\t789\t728\t1900000000"
                "\trescue\t2\tblue\t3\t1\t1\t0\t0",
            ),
            rescue_commit_protocol(role, target_id),
            battle_verify_protocol(role, target_id, status="2"),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "battle-intel",
                        dry_run=False,
                        category="rescue",
                        target_id=target_id,
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["category"], "rescue")
        self.assertTrue(result["request_dispatched"])
        self.assertTrue(result["world_march_request_dispatched"])
        self.assertFalse(result["start_request_dispatched"])
        self.assertFalse(result["end_request_dispatched"])
        self.assertEqual(result["selected_heroes"], [])
        self.assertEqual(result["quest_status_after"], "2")
        self.assertEqual(events.count("lua-execute"), 3)

    def test_batch_intel_rescue_execute_uses_world_march_commit(self) -> None:
        events: list[str] = []
        role = "打工的"
        target_id = 438
        outputs = (
            battle_intel_protocol(
                role,
                "ITEM\t438\t2438\t1\t789\t728\t1900000000"
                "\trescue\t2\tblue\t3\t1\t1\t0\t0",
            ),
            rescue_commit_protocol(role, target_id),
            battle_verify_protocol(role, target_id, status="missing"),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "batch-intel",
                        dry_run=False,
                        batch_targets=[f"rescue:{target_id}"],
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["request_dispatched"])
        self.assertEqual(len(result["results"]), 1)
        rescue_result = result["results"][0]
        self.assertEqual(rescue_result["category"], "rescue")
        self.assertTrue(rescue_result["request_dispatched"])
        self.assertTrue(rescue_result["world_march_request_dispatched"])
        self.assertFalse(rescue_result["start_request_dispatched"])
        self.assertFalse(rescue_result["end_request_dispatched"])
        self.assertEqual(rescue_result["selected_heroes"], [])
        self.assertEqual(rescue_result["quest_status_after"], "missing")
        self.assertEqual(events.count("lua-execute"), 3)

    def test_march_execute_surfaces_open_protocol_errors_without_ui_taps(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        protocol = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tINTEL",
                f"ROLE\t{role_hex}",
                "KINGDOM\t4549",
                "ITEM\t70\t1700\t1\t700\t701\t1900000000"
                "\tpurple\t4\t808\t8\t10",
                "END\t1",
            )
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(
                    events,
                    outputs=(protocol, protocol),
                ),
            ),
        ):
            with self.assertRaisesRegex(BusinessError, "OPEN protocol"):
                execute(
                    business_args("march", dry_run=False, quality="purple"),
                    settings,
                )
        self.assertEqual(events.count("lua-execute"), 2)
        self.assertFalse(any(event.startswith("input-tap:") for event in events))
        self.assertEqual(events.count("frida-detach"), 1)

    def test_march_retries_until_exact_server_proof_appears(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()

        def stage(kind: str, *body: str) -> str:
            return "\n".join(
                (
                    f"MUMU_AUTOTASK\t1\t{kind}",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    *body,
                    "END\t1",
                )
            )

        outputs = (
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tINTEL",
                    f"ROLE\t{role_hex}",
                    "KINGDOM\t4549",
                    "ITEM\t70\t1700\t1\t700\t701\t1900000000"
                    "\tpurple\t4\t808\t8\t10",
                    "END\t1",
                )
            ),
            stage("OPEN", "OPENED\t1"),
            stage("READY", "READY\t1"),
            stage(
                "VERIFY",
                "ACCEPTED\t0\tSTATUS\t1",
                "MARCH\t0\tEVENT\t0",
                "PROOF\tNONE",
            ),
            stage(
                "VERIFY",
                "ACCEPTED\t1\tSTATUS\t1",
                "MARCH\t1\tEVENT\tmissing",
                "PROOF\tMARCH_FIELDS",
            ),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            patch("mumu_autotask.cli.time.sleep") as sleep,
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args("march", dry_run=False, quality="purple"),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["request_dispatched"])
        self.assertEqual(result["verification_polls"], 2)
        self.assertEqual(events.count("lua-execute"), 5)
        sleep.assert_any_call(0.35)
        sleep.assert_any_call(0.2)

    def test_march_rejects_role_drift_after_intel_stage(self) -> None:
        events: list[str] = []
        first_role = "打工人"
        second_role = "打工魂"
        first_hex = first_role.encode("utf-8").hex()
        second_hex = second_role.encode("utf-8").hex()
        outputs = (
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tINTEL",
                    f"ROLE\t{first_hex}",
                    "KINGDOM\t4549",
                    "ITEM\t70\t1700\t1\t700\t701\t1900000000"
                    "\tpurple\t4\t808\t8\t10",
                    "END\t1",
                )
            ),
            "\n".join(
                (
                    "MUMU_AUTOTASK\t1\tOPEN",
                    f"ROLE\t{second_hex}",
                    "KINGDOM\t4549",
                    "TARGET\t70",
                    "OPENED\t1",
                    "END\t1",
                )
            ),
        )
        settings = Settings(
            devices=(
                DeviceProfile("device-1", roles=(first_role, second_role)),
            )
        )
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
        ):
            with self.assertRaisesRegex(BusinessError, "device whitelist"):
                execute(
                    business_args("march", dry_run=False, quality="purple"),
                    settings,
                )
        self.assertEqual(events.count("frida-attach"), 1)
        self.assertEqual(events.count("frida-detach"), 1)
        self.assertEqual(events.count("lua-execute"), 2)

    def test_wait_intel_dry_run_hashes_exact_ids_without_attach(self) -> None:
        events: list[str] = []
        role = "打工的"
        target_ids = [71, 72]
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch("mumu_autotask.cli._client", return_value=FakeClient(events)),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "wait-intel",
                        target_ids=target_ids,
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["requested_target_ids"], target_ids)
        self.assertEqual(result["expected_role"], role)
        self.assertEqual(
            result["script_sha256"],
            script_sha256(build_intel_status_lua((role,), target_ids)),
        )
        self.assertNotIn("frida-attach", events)
        self.assertNotIn("state-scan", events)

    def test_expected_role_outside_device_whitelist_stops_before_adb(self) -> None:
        settings = Settings(
            devices=(DeviceProfile("device-1", roles=("打工的",)),)
        )
        with patch("mumu_autotask.cli._adb") as adb_factory:
            with self.assertRaisesRegex(BusinessError, "device whitelist"):
                execute(
                    business_args(
                        "wait-intel",
                        target_ids=[71],
                        expected_role="4583角色",
                    ),
                    settings,
                )
        adb_factory.assert_not_called()

    def test_wait_intel_polls_exact_ids_until_all_are_terminal(self) -> None:
        events: list[str] = []
        role = "打工的"
        outputs = (
            status_protocol(
                role,
                "TARGET\t71\tPENDING\t3",
                "TARGET\t72\tMISSING\tmissing",
            ),
            status_protocol(
                role,
                "TARGET\t71\tCOMPLETED\t2",
                "TARGET\t72\tMISSING\tmissing",
            ),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            patch("mumu_autotask.cli.time.sleep"),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "wait-intel",
                        dry_run=False,
                        target_ids=[71, 72],
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["wait_completed"])
        self.assertEqual(result["poll_count"], 2)
        self.assertEqual(result["status_counts"], {"pending": 0, "completed": 1, "missing": 1})
        self.assertEqual(events.count("lua-execute"), 2)
        self.assertEqual(events.count("frida-attach"), 1)
        self.assertEqual(events.count("frida-detach"), 1)

    def test_wait_intel_rejects_role_drift_between_polls(self) -> None:
        events: list[str] = []
        outputs = (
            status_protocol("打工人", "TARGET\t71\tPENDING\t1"),
            status_protocol("打工魂", "TARGET\t71\tCOMPLETED\t2"),
        )
        settings = Settings(
            devices=(DeviceProfile("device-1", roles=("打工人", "打工魂")),)
        )
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            patch("mumu_autotask.cli.time.sleep"),
        ):
            with self.assertRaisesRegex(BusinessError, "device whitelist"):
                execute(
                    business_args(
                        "wait-intel",
                        dry_run=False,
                        target_ids=[71],
                        expected_role="打工人",
                    ),
                    settings,
                )
        self.assertEqual(events.count("lua-execute"), 2)

    def test_claim_intel_all_missing_is_idempotent_without_request_stage(self) -> None:
        events: list[str] = []
        role = "打工的"
        precheck = status_protocol(
            role,
            "TARGET\t71\tMISSING\tmissing",
            "TARGET\t72\tMISSING\tmissing",
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, output=precheck),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "claim-intel",
                        dry_run=False,
                        target_ids=[71, 72],
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["idempotent"])
        self.assertFalse(result["claim_invoked"])
        self.assertFalse(result["request_dispatched"])
        self.assertTrue(result["verified_missing"])
        self.assertEqual(events.count("lua-execute"), 1)

    def test_claim_intel_pending_target_blocks_before_request_stage(self) -> None:
        events: list[str] = []
        role = "打工的"
        precheck = status_protocol(
            role,
            "TARGET\t71\tCOMPLETED\t2",
            "TARGET\t72\tPENDING\t3",
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, output=precheck),
            ),
        ):
            with self.assertRaisesRegex(BusinessError, "pending: 72"):
                execute(
                    business_args(
                        "claim-intel",
                        dry_run=False,
                        target_ids=[71, 72],
                        expected_role=role,
                    ),
                    settings,
                )
        self.assertEqual(events.count("lua-execute"), 1)

    def test_claim_intel_sends_once_then_verifies_all_ids_missing(self) -> None:
        events: list[str] = []
        role = "打工的"
        target_ids = (71, 72)
        outputs = (
            status_protocol(
                role,
                "TARGET\t71\tCOMPLETED\t2",
                "TARGET\t72\tMISSING\tmissing",
            ),
            claim_protocol(role, target_ids, sent=True),
            status_protocol(
                role,
                "TARGET\t71\tCOMPLETED\t2",
                "TARGET\t72\tMISSING\tmissing",
            ),
            status_protocol(
                role,
                "TARGET\t71\tMISSING\tmissing",
                "TARGET\t72\tMISSING\tmissing",
            ),
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
            patch("mumu_autotask.cli.time.sleep"),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "claim-intel",
                        dry_run=False,
                        target_ids=list(target_ids),
                        expected_role=role,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertTrue(result["claim_invoked"])
        self.assertTrue(result["request_dispatched"])
        self.assertFalse(result["idempotent"])
        self.assertTrue(result["verified_missing"])
        self.assertEqual(result["verification_polls"], 2)
        self.assertEqual(events.count("lua-execute"), 4)

    def test_claim_intel_rejects_role_drift_at_claim_stage(self) -> None:
        events: list[str] = []
        outputs = (
            status_protocol("打工人", "TARGET\t71\tCOMPLETED\t2"),
            claim_protocol("打工魂", (71,), sent=True),
        )
        settings = Settings(
            devices=(DeviceProfile("device-1", roles=("打工人", "打工魂")),)
        )
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, outputs=outputs),
            ),
        ):
            with self.assertRaisesRegex(BusinessError, "device whitelist"):
                execute(
                    business_args(
                        "claim-intel",
                        dry_run=False,
                        target_ids=[71],
                        expected_role="打工人",
                    ),
                    settings,
                )
        self.assertEqual(events.count("lua-execute"), 2)

    def test_march_dry_run_honors_exact_runtime_id(self) -> None:
        events: list[str] = []
        role = "打工的"
        role_hex = role.encode("utf-8").hex()
        protocol = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tINTEL",
                f"ROLE\t{role_hex}",
                "KINGDOM\t4549",
                "ITEM\t71\t1701\t1\t700\t701\t1900000000\tpurple\t4\t808\t8\t10",
                "ITEM\t72\t1702\t1\t702\t703\t1900000100\tpurple\t4\t809\t9\t10",
                "END\t2",
            )
        )
        settings = Settings(devices=(DeviceProfile("device-1", roles=(role,)),))
        output = io.StringIO()
        with (
            patch("mumu_autotask.cli._adb", return_value=FakeAdb(events)),
            patch(
                "mumu_autotask.cli._client",
                return_value=FakeClient(events, output=protocol),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                execute(
                    business_args(
                        "march",
                        quality="purple",
                        target_id=72,
                    ),
                    settings,
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["requested_target_id"], 72)
        self.assertEqual(result["target"]["runtime_id"], 72)

if __name__ == "__main__":
    unittest.main()
