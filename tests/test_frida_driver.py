from __future__ import annotations

import unittest
from types import SimpleNamespace

from mumu_autotask.frida_driver import (
    FridaDriverError,
    FridaLuaClient,
    LuaExecutionError,
    load_agent_source,
    load_houdini_guard_source,
)


class FakeExports:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.state_response = {
            "address": "0x7b7029221380",
            "marked": 4,
            "status": 0,
            "glref": "0x7b7029228000",
            "base": "0x7b7029230080",
            "top": "0x7b7029230100",
            "maxstack": "0x7b7029230200",
            "stack": "0x7b7029230000",
            "openupval": "0x0",
            "env": "0x7b7029229000",
            "cframe": "0x0",
            "stacksize": 64,
            "mainThread": "0x7b7029221380",
            "isMain": True,
        }
        self.execute_response = {
            "ok": True,
            "result": 8,
            "output": "Lua 5.1",
            "threadId": 8123,
            "threadName": "UnityMain",
        }

    def initialize(self, path: str):
        self.calls.append(("initialize", path))
        return {"arch": "x64", "probe": "81985529216486895"}

    def find_lua_states(self):
        self.calls.append(("find-lua-states",))
        return {
            "candidates": [self.state_response],
            "failures": [],
            "scannedRanges": 1,
            "usedFallback": False,
        }

    def validate_lua_state(self, address: str):
        self.calls.append(("validate-lua-state", address))
        return self.state_response

    def execute(self, state_address: str, code: str, capacity: int):
        self.calls.append(("execute", state_address, code, capacity))
        return self.execute_response


class FakeScript:
    def __init__(self, exports: FakeExports, *, fail_load: bool = False) -> None:
        self.exports_sync = exports
        self.loaded = False
        self.unloaded = False
        self.fail_load = fail_load
        self.handlers = {}

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler

    def load(self) -> None:
        if self.fail_load:
            raise RuntimeError("synthetic script load failure")
        self.loaded = True

    def unload(self) -> None:
        self.unloaded = True


class FakeSession:
    def __init__(
        self,
        exports: FakeExports,
        *,
        fail_guard_load: bool = False,
        fail_main_load: bool = False,
    ) -> None:
        self.exports = exports
        self.sources: list[str] = []
        self.scripts: list[FakeScript] = []
        self.fail_guard_load = fail_guard_load
        self.fail_main_load = fail_main_load
        self.script: FakeScript | None = None
        self.detached = False

    def create_script(self, source: str) -> FakeScript:
        self.sources.append(source)
        is_guard = len(self.sources) == 1
        script = FakeScript(
            self.exports,
            fail_load=(self.fail_guard_load if is_guard else self.fail_main_load),
        )
        self.scripts.append(script)
        self.script = script
        return self.script

    def detach(self) -> None:
        self.detached = True


class FakeDevice:
    def __init__(self, processes, *, fail_guard_load: bool = False, fail_main_load: bool = False) -> None:
        self.processes = processes
        self.exports = FakeExports()
        self.session = FakeSession(
            self.exports,
            fail_guard_load=fail_guard_load,
            fail_main_load=fail_main_load,
        )
        self.attached: list[int] = []

    def enumerate_processes(self):
        return self.processes

    def attach(self, pid: int) -> FakeSession:
        self.attached.append(pid)
        return self.session


class FakeManager:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.hosts: list[str] = []

    def add_remote_device(self, host: str) -> FakeDevice:
        self.hosts.append(host)
        return self.device


class FakeFrida:
    def __init__(self, device: FakeDevice) -> None:
        self.manager = FakeManager(device)

    def get_device_manager(self) -> FakeManager:
        return self.manager


class FridaDriverTests(unittest.TestCase):
    def test_guard_is_loaded_before_agent_and_unloaded_on_close(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            self.assertEqual(len(device.session.sources), 2)
            self.assertIn("libhoudini.so", device.session.sources[0])
            self.assertEqual(device.session.sources[1], "rpc.exports = {};")
            self.assertTrue(device.session.scripts[0].loaded)
            self.assertTrue(device.session.scripts[1].loaded)
        self.assertTrue(device.session.scripts[0].unloaded)
        self.assertTrue(device.session.scripts[1].unloaded)
        self.assertTrue(device.session.detached)

    def test_guard_load_failure_detaches_session(self) -> None:
        device = FakeDevice(
            [SimpleNamespace(pid=7359, name="Whiteout Survival")],
            fail_guard_load=True,
        )
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with self.assertRaisesRegex(FridaDriverError, "cannot attach"):
            client.connect()
        self.assertTrue(device.session.detached)
        self.assertEqual(len(device.session.scripts), 1)
        self.assertTrue(device.session.scripts[0].unloaded)

    def test_agent_load_failure_unloads_guard_and_detaches(self) -> None:
        device = FakeDevice(
            [SimpleNamespace(pid=7359, name="Whiteout Survival")],
            fail_main_load=True,
        )
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with self.assertRaisesRegex(FridaDriverError, "cannot attach"):
            client.connect()
        self.assertTrue(device.session.detached)
        self.assertEqual(len(device.session.scripts), 2)
        self.assertTrue(all(script.unloaded for script in device.session.scripts))

    def test_guard_source_has_exact_gate_signature_and_exit_group_only(self) -> None:
        source = load_houdini_guard_source()
        self.assertIn('const GATE_OFFSET = 0x314890;', source)
        self.assertIn(
            'const EXPECTED = [0x48, 0x89, 0xf8, 0x48, 0x89, 0xf7, 0x0f, 0x05, 0xc3];',
            source,
        )
        self.assertIn('if (args[0].toUInt32() === EXIT_GROUP)', source)
        self.assertNotIn('args[0].toUInt32() === 60', source)

    def test_agent_distinguishes_native_sentinels_from_short_lua_errors(self) -> None:
        source = load_agent_source()
        self.assertIn("executeGLThreadJobs", source)
        self.assertIn("unity-frame-hook", source)
        self.assertNotIn("Java.registerClass", source)
        self.assertIn("output.writeU8(0);", source)
        self.assertIn("nativeBridgeError(result, output)", source)
        self.assertIn("if (output.readU8() !== 0)", source)
        sentinel_guard = source.index("if (output.readU8() !== 0)")
        sentinel_switch = source.index("switch (result)", sentinel_guard)
        self.assertLess(sentinel_guard, sentinel_switch)
        for result in (-2, -3, -10, -11):
            with self.subTest(result=result):
                self.assertIn(f"case {result}:", source)
                self.assertIn(f"execute failed ({result})", source)

    def test_attach_initialize_execute_and_detach(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            initialization = client.initialize_bridge(
                "/data/local/tmp/libmumu_bridge.so"
            )
            result = client.execute_lua(
                0x7B7029221380,
                "return tostring(_VERSION)",
            )

        self.assertEqual(device.attached, [7359])
        self.assertTrue(device.session.script.loaded)
        self.assertEqual(initialization["arch"], "x64")
        self.assertEqual(result.output, "Lua 5.1")
        self.assertEqual(result.thread_id, 8123)
        self.assertEqual(result.thread_name, "UnityMain")
        self.assertTrue(device.session.detached)
        self.assertEqual(
            device.exports.calls,
            [
                ("initialize", "/data/local/tmp/libmumu_bridge.so"),
                (
                    "execute",
                    "0x7b7029221380",
                    "return tostring(_VERSION)",
                    16384,
                ),
            ],
        )

    def test_process_name_must_be_unique(self) -> None:
        processes = [
            SimpleNamespace(pid=1, name="Whiteout Survival"),
            SimpleNamespace(pid=2, name="Whiteout Survival"),
        ]
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="",
            frida_api=FakeFrida(FakeDevice(processes)),
        )
        with self.assertRaisesRegex(FridaDriverError, "expected one process"):
            client.inspect_process()

    def test_explicit_pid_still_validates_process_name(self) -> None:
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            pid=7,
            agent_source="",
            frida_api=FakeFrida(
                FakeDevice([SimpleNamespace(pid=7, name="wrong-process")])
            ),
        )
        with self.assertRaisesRegex(FridaDriverError, "not one of"):
            client.inspect_process()

    def test_explicit_pid_accepts_configured_package_alias(self) -> None:
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            process_aliases=("com.gof.global",),
            pid=7,
            agent_source="",
            frida_api=FakeFrida(
                FakeDevice([SimpleNamespace(pid=7, name="com.gof.global")])
            ),
        )
        self.assertEqual(client.inspect_process().pid, 7)

    def test_probe_mismatch_prevents_initialization(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        device.exports.initialize = lambda path: {"probe": "0xdeadbeef"}
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            with self.assertRaisesRegex(FridaDriverError, "probe mismatch"):
                client.initialize_bridge("/data/local/tmp/wrong.so")

    def test_execute_requires_initialization(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            with self.assertRaisesRegex(FridaDriverError, "not initialized"):
                client.execute_lua(0xABC, "return 1")

    def test_execute_failure_preserves_bridge_output(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        device.exports.execute_response = {
            "ok": False,
            "result": -12,
            "output": "load error",
            "threadId": 8123,
            "threadName": "UnityMain",
        }
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            client.initialize_bridge("/data/local/tmp/libmumu_bridge.so")
            with self.assertRaises(LuaExecutionError) as raised:
                client.execute_lua("0xabc", "return 1")
        self.assertEqual(raised.exception.result_code, -12)
        self.assertEqual(raised.exception.output, "load error")

    def test_execute_rejects_non_unity_thread(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        device.exports.execute_response["threadName"] = "gum-js-loop"
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            client.initialize_bridge("/data/local/tmp/libmumu_bridge.so")
            with self.assertRaisesRegex(FridaDriverError, "approved queued"):
                client.execute_lua(0xABC, "return 1")

    def test_execute_accepts_declared_direct_bridge_thread(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        device.exports.execute_response["threadName"] = "gum-js-loop"
        device.exports.execute_response["threadMode"] = "frida-direct"
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            client.initialize_bridge("/data/local/tmp/libmumu_bridge.so")
            result = client.execute_lua(0xABC, "return 1")
        self.assertEqual(result.output, "Lua 5.1")

    def test_execute_validates_address_and_capacity_before_rpc(self) -> None:
        device = FakeDevice([SimpleNamespace(pid=7359, name="Whiteout Survival")])
        client = FridaLuaClient(
            "127.0.0.1:27042",
            process_name="Whiteout Survival",
            agent_source="rpc.exports = {};",
            frida_api=FakeFrida(device),
        )
        with client:
            client.initialize_bridge("/data/local/tmp/libmumu_bridge.so")
            with self.assertRaisesRegex(FridaDriverError, "positive integer"):
                client.execute_lua(0, "return 1")
            with self.assertRaisesRegex(FridaDriverError, "between 2 and 16384"):
                client.execute_lua(0xABC, "return 1", output_capacity=16385)
            with self.assertRaisesRegex(
                FridaDriverError, "16384 UTF-8 bytes; bridge limit is 16383"
            ):
                client.execute_lua(0xABC, "x" * 16384)
        self.assertEqual(
            [call[0] for call in device.exports.calls],
            ["initialize"],
        )


if __name__ == "__main__":
    unittest.main()
