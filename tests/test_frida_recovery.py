from __future__ import annotations

import shlex
import threading
import unittest
from types import SimpleNamespace

from mumu_autotask.adb import AdbForward
from mumu_autotask.frida_driver import (
    FRIDA_SERVER_REMOTE_PATH,
    FridaDriverError,
    FridaLuaClient,
    FridaServerRecovery,
)


class FakeAdb:
    def __init__(self, forwards: list[AdbForward]) -> None:
        self.forwards = forwards
        self.forward_list_calls = 0
        self.shell_calls: list[tuple[str, tuple[str, ...]]] = []

    def forward_list(self) -> list[AdbForward]:
        self.forward_list_calls += 1
        return list(self.forwards)

    def shell(self, serial: str, *args: str) -> str:
        self.shell_calls.append((serial, args))
        return "started"


class FakeRecovery:
    def __init__(self) -> None:
        self.calls = 0

    def recover(self) -> None:
        self.calls += 1


class EnumeratingDevice:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.enumerate_calls = 0

    def enumerate_processes(self):
        self.enumerate_calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class StaticManager:
    def __init__(self, device: EnumeratingDevice) -> None:
        self.device = device
        self.add_calls = 0

    def add_remote_device(self, host: str) -> EnumeratingDevice:
        self.add_calls += 1
        return self.device


class FlakyManager(StaticManager):
    def __init__(self, device: EnumeratingDevice) -> None:
        super().__init__(device)
        self.failures = 1

    def add_remote_device(self, host: str) -> EnumeratingDevice:
        self.add_calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("connection is closed")
        return self.device


class FakeFrida:
    def __init__(self, manager: StaticManager) -> None:
        self.manager = manager

    def get_device_manager(self) -> StaticManager:
        return self.manager


class LoadableScript:
    def __init__(self) -> None:
        self.exports_sync = SimpleNamespace()

    def load(self) -> None:
        pass

    def unload(self) -> None:
        pass


class LoadableSession:
    def __init__(self) -> None:
        self.created_scripts = 0

    def create_script(self, source: str) -> LoadableScript:
        self.created_scripts += 1
        return LoadableScript()

    def detach(self) -> None:
        pass


class TimeoutThenAttachDevice:
    def __init__(self) -> None:
        self.attach_calls = 0
        self.session = LoadableSession()

    def enumerate_processes(self):
        return [SimpleNamespace(pid=7359, name="Whiteout Survival")]

    def attach(self, pid: int) -> LoadableSession:
        self.attach_calls += 1
        if self.attach_calls == 1:
            raise RuntimeError("timed out while attaching to target")
        return self.session


def client_for(
    manager: StaticManager,
    recovery: FakeRecovery,
) -> FridaLuaClient:
    return FridaLuaClient(
        "127.0.0.1:27052",
        process_name="Whiteout Survival",
        agent_source="rpc.exports = {};",
        frida_api=FakeFrida(manager),
        server_recovery=recovery,
    )


class FridaServerRecoveryTests(unittest.TestCase):
    def test_recovery_uses_remote_port_from_matching_adb_forward(self) -> None:
        adb = FakeAdb(
            [
                AdbForward("127.0.0.1:16384", "tcp:27042", "tcp:27042"),
                AdbForward("127.0.0.1:16416", "tcp:27052", "tcp:38417"),
            ]
        )

        output = FridaServerRecovery(
            "127.0.0.1:27052",
            adb=adb,  # type: ignore[arg-type]
        ).recover()

        self.assertEqual(output, "started")
        self.assertEqual(adb.forward_list_calls, 1)
        self.assertEqual(len(adb.shell_calls), 1)
        serial, args = adb.shell_calls[0]
        self.assertEqual(serial, "127.0.0.1:16416")
        self.assertEqual(args[:4], ("su", "0", "sh", "-c"))
        launch = shlex.split(args[4])
        self.assertEqual(len(launch), 1)
        script = launch[0]
        self.assertIn(
            "server_path=/data/local/tmp/frida-server-x64-17.17.0", script
        )
        self.assertIn("endpoint=127.0.0.1:38417", script)
        self.assertNotIn("127.0.0.1:27042", script)
        self.assertIn('readlink "$candidate_proc/exe"', script)
        self.assertIn('tr "\\000" "\\n"', script)
        self.assertIn('owns_listener "$old_pid"', script)
        self.assertIn('kill -TERM "$old_pid"', script)
        self.assertIn('kill -KILL "$old_pid"', script)
        self.assertNotIn("pkill", script)
        self.assertNotIn("killall", script)

    def test_recovery_rejects_any_server_path_other_than_fixed_binary(self) -> None:
        adb = FakeAdb(
            [AdbForward("127.0.0.1:16416", "tcp:27052", "tcp:38417")]
        )

        with self.assertRaisesRegex(FridaDriverError, "unexpected server path"):
            FridaServerRecovery(
                "127.0.0.1:27052",
                adb=adb,  # type: ignore[arg-type]
                server_path="/data/local/tmp/frida server",
            ).recover()

        self.assertEqual(adb.shell_calls, [])

    def test_recovery_rejects_non_loopback_host_before_adb_lookup(self) -> None:
        adb = FakeAdb(
            [AdbForward("127.0.0.1:16416", "tcp:27052", "tcp:38417")]
        )

        with self.assertRaisesRegex(FridaDriverError, "must be loopback"):
            FridaServerRecovery(
                "192.0.2.4:27052",
                adb=adb,  # type: ignore[arg-type]
            ).recover()

        self.assertEqual(adb.forward_list_calls, 0)
        self.assertEqual(adb.shell_calls, [])

    def test_recovery_fails_closed_on_ambiguous_local_forward(self) -> None:
        adb = FakeAdb(
            [
                AdbForward("127.0.0.1:16384", "tcp:27042", "tcp:27042"),
                AdbForward("127.0.0.1:16416", "tcp:27042", "tcp:38417"),
            ]
        )

        with self.assertRaisesRegex(FridaDriverError, "found 2"):
            FridaServerRecovery(
                "127.0.0.1:27042",
                adb=adb,  # type: ignore[arg-type]
            ).recover()

        self.assertEqual(adb.shell_calls, [])

    def test_remote_connection_failure_recovers_and_retries(self) -> None:
        device = EnumeratingDevice(
            [[SimpleNamespace(pid=7359, name="Whiteout Survival")]]
        )
        manager = FlakyManager(device)
        recovery = FakeRecovery()

        process = client_for(manager, recovery).inspect_process()

        self.assertEqual(process.pid, 7359)
        self.assertEqual(recovery.calls, 1)
        self.assertEqual(manager.add_calls, 2)
        self.assertEqual(device.enumerate_calls, 1)

    def test_enumeration_failure_recovers_and_retries(self) -> None:
        device = EnumeratingDevice(
            [
                RuntimeError("connection closed by remote peer"),
                [SimpleNamespace(pid=7359, name="Whiteout Survival")],
            ]
        )
        manager = StaticManager(device)
        recovery = FakeRecovery()

        process = client_for(manager, recovery).inspect_process()

        self.assertEqual(process.pid, 7359)
        self.assertEqual(recovery.calls, 1)
        self.assertEqual(device.enumerate_calls, 2)
        self.assertEqual(manager.add_calls, 2)

    def test_attach_timeout_recovers_and_retries_once(self) -> None:
        device = TimeoutThenAttachDevice()
        manager = StaticManager(device)  # type: ignore[arg-type]
        recovery = FakeRecovery()
        client = client_for(manager, recovery)

        process = client.connect()

        self.assertEqual(process.pid, 7359)
        self.assertEqual(recovery.calls, 1)
        self.assertEqual(device.attach_calls, 2)
        self.assertEqual(manager.add_calls, 2)
        self.assertEqual(device.session.created_scripts, 2)
        client.close()

    def test_persistent_connection_failure_is_retried_only_once(self) -> None:
        device = EnumeratingDevice(
            [
                RuntimeError("connection closed"),
                RuntimeError("connection closed"),
            ]
        )
        recovery = FakeRecovery()

        with self.assertRaisesRegex(FridaDriverError, "connection closed"):
            client_for(StaticManager(device), recovery).inspect_process()

        self.assertEqual(recovery.calls, 1)
        self.assertEqual(device.enumerate_calls, 2)

    def test_non_connection_failure_does_not_start_or_retry(self) -> None:
        device = EnumeratingDevice([RuntimeError("permission denied")])
        recovery = FakeRecovery()

        with self.assertRaisesRegex(FridaDriverError, "permission denied"):
            client_for(StaticManager(device), recovery).inspect_process()

        self.assertEqual(recovery.calls, 0)
        self.assertEqual(device.enumerate_calls, 1)


class BlockingAdb(FakeAdb):
    def __init__(self, forward: AdbForward) -> None:
        super().__init__([forward])
        self.state_lock = threading.Lock()
        self.second_lookup = threading.Event()
        self.first_shell_entered = threading.Event()
        self.release_first_shell = threading.Event()
        self.active_shells = 0
        self.max_active_shells = 0

    def forward_list(self) -> list[AdbForward]:
        with self.state_lock:
            self.forward_list_calls += 1
            if self.forward_list_calls == 2:
                self.second_lookup.set()
        return list(self.forwards)

    def shell(self, serial: str, *args: str) -> str:
        with self.state_lock:
            self.active_shells += 1
            self.max_active_shells = max(
                self.max_active_shells,
                self.active_shells,
            )
            first = len(self.shell_calls) == 0
            self.shell_calls.append((serial, args))
        if first:
            self.first_shell_entered.set()
            if not self.release_first_shell.wait(timeout=2):
                raise RuntimeError("test release timed out")
        with self.state_lock:
            self.active_shells -= 1
        return "started"


class FridaServerLockTests(unittest.TestCase):
    def test_recovery_is_serialized_per_adb_serial(self) -> None:
        adb = BlockingAdb(
            AdbForward("127.0.0.1:16416", "tcp:27052", "tcp:38417")
        )
        recovery = FridaServerRecovery(
            "127.0.0.1:27052",
            adb=adb,  # type: ignore[arg-type]
        )
        errors: list[BaseException] = []

        def run() -> None:
            try:
                recovery.recover()
            except BaseException as exc:  # captured for assertion in main thread
                errors.append(exc)

        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start()
        self.assertTrue(adb.first_shell_entered.wait(timeout=2))
        second.start()
        self.assertTrue(adb.second_lookup.wait(timeout=2))
        self.assertEqual(adb.max_active_shells, 1)
        adb.release_first_shell.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(adb.max_active_shells, 1)
        self.assertEqual(len(adb.shell_calls), 1)


if __name__ == "__main__":
    unittest.main()
