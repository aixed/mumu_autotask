from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adb import AdbError, resolve_adb_executable
from .config import DeviceProfile, load_settings
from .frida_driver import (
    FridaDriverError,
    FridaLuaClient,
    FridaServerRecovery,
    LuaExecutionError,
    LuaExecutionResult,
)


MAX_WORKER_MESSAGE_BYTES = 128 * 1024
WORKER_START_TIMEOUT_SECONDS = 35.0


def worker_port(profile: DeviceProfile) -> int:
    """Return a deterministic localhost port for one emulator's worker."""

    return 38000 + (profile.frida_local_port % 20000)


def _read_json_line(connection: socket.socket) -> Mapping[str, Any]:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = connection.recv(4096)
        if not chunk:
            raise FridaDriverError("persistent worker connection closed before a reply")
        newline = chunk.find(b"\n")
        if newline >= 0:
            chunks.append(chunk[:newline])
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_WORKER_MESSAGE_BYTES:
            raise FridaDriverError("persistent worker message exceeded the size limit")
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FridaDriverError("persistent worker returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise FridaDriverError("persistent worker response must be a JSON object")
    return value


def _send_json_line(connection: socket.socket, payload: Mapping[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_WORKER_MESSAGE_BYTES:
        raise FridaDriverError("persistent worker message exceeded the size limit")
    connection.sendall(encoded)


class PersistentFridaClient:
    """FridaLuaClient-compatible proxy backed by a per-device worker process."""

    def __init__(
        self,
        profile: DeviceProfile,
        config_path: str | Path,
        *,
        pid: int,
        python_executable: str | None = None,
    ) -> None:
        self.profile = profile
        self.config_path = Path(config_path).resolve()
        self.requested_pid = int(pid)
        self.port = worker_port(profile)
        self.python_executable = python_executable or sys.executable
        self.messages: list[Mapping[str, Any]] = []
        self._initialization: dict[str, Any] | None = None
        self._cached_state_address: int | None = None

    def _request(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as connection:
                connection.settimeout(timeout)
                _send_json_line(connection, payload)
                response = _read_json_line(connection)
        except (OSError, FridaDriverError) as exc:
            raise FridaDriverError(
                f"cannot reach persistent Frida worker on 127.0.0.1:{self.port}: {exc}"
            ) from exc
        if response.get("ok") is not True:
            message = str(response.get("error") or "persistent Frida worker request failed")
            if response.get("error_type") == "LuaExecutionError":
                raise LuaExecutionError(
                    message,
                    output=str(response.get("output") or ""),
                    result_code=int(response.get("result_code") or -1),
                )
            raise FridaDriverError(message)
        return response

    def _ping(self, *, timeout: float = 1.0) -> Mapping[str, Any]:
        response = self._request(
            {
                "operation": "ping",
                "serial": self.profile.serial,
                "pid": self.requested_pid,
            },
            timeout=timeout,
        )
        if response.get("serial") != self.profile.serial:
            raise FridaDriverError("persistent Frida worker belongs to another device")
        if response.get("pid") != self.requested_pid:
            raise FridaDriverError(
                "persistent Frida worker is attached to an earlier game process"
            )
        cached_state_address = response.get("cached_state_address")
        if cached_state_address is not None:
            try:
                self._cached_state_address = int(str(cached_state_address), 0)
            except (TypeError, ValueError):
                self._cached_state_address = None
        return response

    def ensure_started(self) -> Mapping[str, Any]:
        try:
            response = self._ping()
        except FridaDriverError:
            self._launch()
        else:
            self._initialization = dict(response.get("initialization") or {})
            return response

        deadline = time.monotonic() + WORKER_START_TIMEOUT_SECONDS
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            current_pid = self._current_adb_pid()
            if current_pid is not None and current_pid != self.requested_pid:
                raise FridaDriverError(
                    "game restarted while the persistent Frida worker was starting "
                    f"({self.requested_pid} -> {current_pid}); retry the operation"
                )
            try:
                response = self._ping()
                self._initialization = dict(response.get("initialization") or {})
                return response
            except FridaDriverError as exc:
                last_error = exc
                time.sleep(0.2)
        detail = self._log_tail()
        suffix = f"; worker log: {detail}" if detail else ""
        raise FridaDriverError(
            f"persistent Frida worker did not become ready: {last_error}{suffix}"
        )

    def _current_adb_pid(self) -> int | None:
        settings = load_settings(self.config_path)
        try:
            executable = resolve_adb_executable(settings.adb.executable)
        except AdbError:
            return None
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                (
                    executable,
                    "-s",
                    self.profile.serial,
                    "shell",
                    "pidof",
                    self.profile.package_name,
                ),
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        values = [value for value in completed.stdout.split() if value.isdecimal()]
        return int(values[0]) if len(values) == 1 else None

    def _launch(self) -> None:
        command = (
            self.python_executable,
            "-m",
            "mumu_autotask.frida_worker",
            "--config",
            str(self.config_path),
            "--serial",
            self.profile.serial,
            "--pid",
            str(self.requested_pid),
        )
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        log_path = self._log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | 0x00000008  # DETACHED_PROCESS
            )
        try:
            with log_path.open("a", encoding="utf-8") as log:
                subprocess.Popen(
                    command,
                    cwd=self.config_path.parent,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    creationflags=creationflags,
                    close_fds=True,
                )
        except OSError as exc:
            raise FridaDriverError(f"cannot start persistent Frida worker: {exc}") from exc

    def _log_path(self) -> Path:
        safe_serial = "".join(
            character if character.isalnum() else "_"
            for character in self.profile.serial
        )
        return self.config_path.parent / f".mumu-frida-worker-{safe_serial}.log"

    def _log_tail(self) -> str:
        try:
            lines = self._log_path().read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return " | ".join(lines[-3:])

    def inspect_process(self):
        response = self.ensure_started()
        from .frida_driver import ProcessInfo

        return ProcessInfo(int(response["pid"]), str(response["process"]))

    def connect(self):
        return self.inspect_process()

    def initialize_bridge(self, remote_path: str) -> Mapping[str, Any]:
        if remote_path != self.profile.bridge_remote_path:
            raise FridaDriverError("persistent worker bridge path does not match the device profile")
        self.ensure_started()
        if not self._initialization:
            raise FridaDriverError("persistent Frida worker omitted bridge initialization data")
        return dict(self._initialization)

    @property
    def cached_state_address(self) -> int | None:
        self.ensure_started()
        return self._cached_state_address

    def execute_lua(
        self,
        state_address: int | str,
        code: str,
        *,
        output_capacity: int = 16384,
    ) -> LuaExecutionResult:
        response = self._request(
            {
                "operation": "execute",
                "serial": self.profile.serial,
                "pid": self.requested_pid,
                "state_address": str(state_address),
                "code": code,
                "output_capacity": output_capacity,
            },
            timeout=120.0,
        )
        return LuaExecutionResult(
            str(response.get("output") or ""),
            int(response["result_code"]),
            int(response["thread_id"]),
            str(response["thread_name"]),
        )

    def close(self) -> None:
        # Business commands release only their IPC connection. The injected
        # scripts stay resident until Android confirms that the game PID died.
        return

    def __enter__(self) -> "PersistentFridaClient":
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


@dataclass(slots=True)
class _QueuedRequest:
    payload: Mapping[str, Any]
    finished: threading.Event
    response: Mapping[str, Any] | None = None


class _WorkerServer:
    def __init__(
        self,
        profile: DeviceProfile,
        client: FridaLuaClient,
        pid: int,
        initialization: Mapping[str, Any],
        adb: Any,
    ) -> None:
        self.profile = profile
        self.client = client
        self.pid = pid
        self.initialization = dict(initialization)
        self.adb = adb
        self.cached_state_address: int | None = None
        self.requests: queue.Queue[_QueuedRequest | None] = queue.Queue()
        self.executor = threading.Thread(
            target=self._execute_requests,
            name=f"frida-worker-executor-{profile.serial}",
            daemon=True,
        )

    def _process_alive(self) -> bool:
        if self.client.session_detached:
            return False
        try:
            return self.adb.pidof(self.profile.serial, self.profile.package_name) == self.pid
        except Exception:
            # MuMu can briefly stop answering ADB while the game is busy.
            # That weak signal must never cause live native hooks to unload.
            return True

    def _execute_requests(self) -> None:
        while True:
            request = self.requests.get()
            if request is None:
                return
            try:
                if not self._process_alive():
                    raise FridaDriverError("game PID changed before queued Lua execution")
                payload = request.payload
                self.cached_state_address = int(str(payload.get("state_address")), 0)
                result = self.client.execute_lua(
                    payload.get("state_address"),
                    str(payload.get("code") or ""),
                    output_capacity=int(payload.get("output_capacity") or 16384),
                )
                request.response = {
                    "ok": True,
                    "output": result.output,
                    "result_code": result.result_code,
                    "thread_id": result.thread_id,
                    "thread_name": result.thread_name,
                }
            except Exception as exc:
                response: dict[str, Any] = {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
                if isinstance(exc, LuaExecutionError):
                    response["output"] = exc.output
                    response["result_code"] = exc.result_code
                request.response = response
            finally:
                request.finished.set()

    def _handle_connection(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(125.0)
            payload = _read_json_line(connection)
            if payload.get("serial") != self.profile.serial:
                raise FridaDriverError("worker request device does not match")
            if payload.get("pid") != self.pid:
                raise FridaDriverError("worker request PID does not match")
            operation = payload.get("operation")
            if operation == "ping":
                response: Mapping[str, Any] = {
                    "ok": True,
                    "serial": self.profile.serial,
                    "pid": self.pid,
                    "process": self.profile.process_name,
                    "initialization": self.initialization,
                    "queue_depth": self.requests.qsize(),
                    "cached_state_address": (
                        hex(self.cached_state_address)
                        if self.cached_state_address is not None
                        else None
                    ),
                }
            elif operation == "execute":
                queued = _QueuedRequest(payload, threading.Event())
                self.requests.put(queued)
                if not queued.finished.wait(timeout=120.0):
                    raise FridaDriverError("queued Unity Lua execution exceeded 120 seconds")
                assert queued.response is not None
                response = queued.response
            else:
                raise FridaDriverError(f"unsupported worker operation: {operation!r}")
        except Exception as exc:
            response = {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        try:
            _send_json_line(connection, response)
        except (OSError, FridaDriverError):
            pass
        finally:
            connection.close()

    def serve(self, listener: socket.socket) -> None:
        self.executor.start()
        listener.listen(16)
        listener.settimeout(0.5)
        next_process_check = 0.0
        try:
            while True:
                now = time.monotonic()
                if now >= next_process_check:
                    if not self._process_alive():
                        break
                    next_process_check = now + 2.0
                try:
                    connection, _address = listener.accept()
                except TimeoutError:
                    continue
                threading.Thread(
                    target=self._handle_connection,
                    args=(connection,),
                    name=f"frida-worker-client-{self.profile.serial}",
                    daemon=True,
                ).start()
        finally:
            listener.close()
            self.requests.put(None)
            self.executor.join(timeout=2.0)


def _profile_for_serial(config_path: str | Path, serial: str) -> DeviceProfile:
    settings = load_settings(config_path)
    matches = [profile for profile in settings.devices if profile.serial == serial]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise FridaDriverError(f"expected one device profile for {serial!r}")
    from .mumu_manager import MumuManagerError, discover_profile_for_serial

    try:
        return discover_profile_for_serial(settings, serial)
    except MumuManagerError as exc:
        raise FridaDriverError(str(exc)) from exc


def run_worker(config_path: str | Path, serial: str, pid: int) -> int:
    profile = _profile_for_serial(config_path, serial)
    port = worker_port(profile)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError:
        listener.close()
        return 0

    # Importing these helpers lazily avoids a module cycle when the normal CLI
    # imports PersistentFridaClient.
    from .cli import (
        _adb,
        _adb_pid,
        _ensure_bridge_binary,
        _ensure_frida_forward,
    )

    settings = load_settings(config_path)
    adb = _adb(settings)
    direct_client: FridaLuaClient | None = None
    try:
        adb.require_connected([profile.serial])
        _ensure_frida_forward(adb, profile)
        _ensure_bridge_binary(adb, profile)
        startup_deadline = time.monotonic() + 10.0
        while True:
            try:
                actual_pid = _adb_pid(adb, profile)
                break
            except Exception:
                if time.monotonic() >= startup_deadline:
                    raise
                time.sleep(0.25)
        if actual_pid != pid:
            raise FridaDriverError(
                f"game PID changed before worker startup ({pid} -> {actual_pid})"
            )
        direct_client = FridaLuaClient(
            profile.frida_host,
            process_name=profile.process_name,
            pid=pid,
            process_aliases=(profile.package_name,),
            server_recovery=FridaServerRecovery(profile.frida_host, adb=adb),
        )
        direct_client.connect()
        initialization = direct_client.initialize_bridge(profile.bridge_remote_path)
        _WorkerServer(
            profile,
            direct_client,
            pid,
            initialization,
            adb,
        ).serve(listener)
        # The target process has already gone away. Releasing the dead Frida
        # session cannot invalidate a trampoline in a live game process.
        direct_client.close()
        return 0
    except Exception as exc:
        print(f"persistent Frida worker failed: {exc}", flush=True)
        listener.close()
        # The protection guard is installed before bridge initialization. If
        # anything fails after that point, keep the process resident until the
        # target dies instead of unloading a live native trampoline.
        if direct_client is not None:
            if direct_client.native_hooks_installed:
                while not direct_client.session_detached:
                    try:
                        if _adb_pid(adb, profile) != pid:
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
            direct_client.close()
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent per-device Frida worker")
    parser.add_argument("--config", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--pid", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_worker(args.config, args.serial, args.pid)


if __name__ == "__main__":
    raise SystemExit(main())
