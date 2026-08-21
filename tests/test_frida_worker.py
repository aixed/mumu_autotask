from __future__ import annotations

import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mumu_autotask.config import DeviceProfile
from mumu_autotask.frida_driver import LuaExecutionResult
from mumu_autotask.frida_worker import (
    PersistentFridaClient,
    _QueuedRequest,
    _WorkerServer,
    _profile_for_serial,
    worker_port,
)


class _FakeAdb:
    def __init__(self, pid: int, *, fail: bool = False) -> None:
        self.pid = pid
        self.fail = fail

    def pidof(self, serial: str, package_name: str) -> int:
        if self.fail:
            raise RuntimeError("temporary ADB timeout")
        return self.pid


class _FakeClient:
    def __init__(self) -> None:
        self.session_detached = False
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def execute_lua(self, state_address, code: str, *, output_capacity: int):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.01)
            self.calls.append(code)
            return LuaExecutionResult(code, 2, 99, "UnityMain")
        finally:
            with self.lock:
                self.active -= 1


class _FailingClient(_FakeClient):
    def execute_lua(self, state_address, code: str, *, output_capacity: int):
        raise RuntimeError("Lua globals are not ready")


class FridaWorkerTests(unittest.TestCase):
    def test_worker_discovers_profile_when_portable_config_has_no_devices(self) -> None:
        profile = DeviceProfile(
            "127.0.0.1:16384",
            frida_host="127.0.0.1:26384",
        )
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"devices": []}', encoding="utf-8")
            with patch(
                "mumu_autotask.mumu_manager.discover_profile_for_serial",
                return_value=profile,
            ) as discover:
                resolved = _profile_for_serial(config, profile.serial)

        self.assertEqual(resolved, profile)
        discover.assert_called_once()

    def test_worker_ports_are_deterministic_and_per_frida_endpoint(self) -> None:
        first = DeviceProfile("device-1", frida_host="127.0.0.1:27042")
        second = DeviceProfile("device-2", frida_host="127.0.0.1:27052")
        self.assertEqual(worker_port(first), worker_port(first))
        self.assertNotEqual(worker_port(first), worker_port(second))

    def test_business_client_close_does_not_stop_the_worker(self) -> None:
        profile = DeviceProfile("device-1", frida_host="127.0.0.1:27042")
        client = PersistentFridaClient(profile, "config.json", pid=7359)
        client.close()

    def test_worker_serializes_concurrent_business_requests_fifo(self) -> None:
        profile = DeviceProfile("device-1")
        client = _FakeClient()
        server = _WorkerServer(
            profile,
            client,  # type: ignore[arg-type]
            7359,
            {"arch": "x64"},
            _FakeAdb(7359),
        )
        server.executor.start()
        first = _QueuedRequest(
            {
                "state_address": "0x1000",
                "code": "first",
                "output_capacity": 128,
            },
            threading.Event(),
        )
        second = _QueuedRequest(
            {
                "state_address": "0x1000",
                "code": "second",
                "output_capacity": 128,
            },
            threading.Event(),
        )
        server.requests.put(first)
        server.requests.put(second)
        self.assertTrue(first.finished.wait(1.0))
        self.assertTrue(second.finished.wait(1.0))
        server.requests.put(None)
        server.executor.join(1.0)
        self.assertEqual(client.calls, ["first", "second"])
        self.assertEqual(client.max_active, 1)

    def test_temporary_adb_failure_does_not_release_live_hooks(self) -> None:
        profile = DeviceProfile("device-1")
        client = _FakeClient()
        server = _WorkerServer(
            profile,
            client,  # type: ignore[arg-type]
            7359,
            {"arch": "x64"},
            _FakeAdb(7359, fail=True),
        )
        self.assertTrue(server._process_alive())
        client.session_detached = True
        self.assertFalse(server._process_alive())

    def test_successful_execution_caches_lua_state_address(self) -> None:
        profile = DeviceProfile("device-1")
        client = _FakeClient()
        server = _WorkerServer(
            profile,
            client,  # type: ignore[arg-type]
            7359,
            {"arch": "x64"},
            _FakeAdb(7359),
        )
        server.executor.start()
        request = _QueuedRequest(
            {
                "state_address": "0x1234",
                "code": "return 1",
                "output_capacity": 128,
            },
            threading.Event(),
        )
        server.requests.put(request)
        self.assertTrue(request.finished.wait(1.0))
        server.requests.put(None)
        server.executor.join(1.0)
        self.assertEqual(server.cached_state_address, 0x1234)

    def test_failed_execution_still_caches_verified_lua_state_address(self) -> None:
        profile = DeviceProfile("device-1")
        server = _WorkerServer(
            profile,
            _FailingClient(),  # type: ignore[arg-type]
            7359,
            {"arch": "x64"},
            _FakeAdb(7359),
        )
        server.executor.start()
        request = _QueuedRequest(
            {
                "state_address": "0x5678",
                "code": "return 1",
                "output_capacity": 128,
            },
            threading.Event(),
        )
        server.requests.put(request)
        self.assertTrue(request.finished.wait(1.0))
        server.requests.put(None)
        server.executor.join(1.0)
        self.assertEqual(server.cached_state_address, 0x5678)


if __name__ == "__main__":
    unittest.main()
