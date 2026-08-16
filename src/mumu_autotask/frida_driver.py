from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import shlex
import threading
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

from .adb import AdbClient, AdbError

class FridaDriverError(RuntimeError):
    """Raised when a Frida connection or bridge RPC fails."""


class LuaExecutionError(FridaDriverError):
    def __init__(self, message: str, *, output: str = "", result_code: int = 0):
        super().__init__(message)
        self.output = output
        self.result_code = result_code


EXPECTED_BRIDGE_PROBE = 0x0123456789ABCDEF
FRIDA_SERVER_REMOTE_PATH = "/data/local/tmp/frida-server-x64-17.17.0"
LUA_BRIDGE_CODE_CAPACITY = 16384

_FRIDA_CONNECTION_MARKERS = (
    "connection closed",
    "connection is closed",
    "server is not running",
    "server unavailable",
    "unable to connect",
    "failed to connect",
    "connection refused",
    "connection reset",
    "transport error",
    "transport endpoint",
    "broken pipe",
    "peer closed",
    "device is gone",
    "timed out",
)
_FRIDA_CONNECTION_TYPES = {
    "servernotrunningerror",
    "transporterror",
    "timedouterror",
    "connectionerror",
}
_SERVER_LOCKS: dict[tuple[str, int, str], threading.Lock] = {}
_SERVER_RECOVERY_GENERATIONS: dict[tuple[str, int, str], int] = {}
_SERVER_LOCKS_GUARD = threading.Lock()


def _is_connection_failure(error: BaseException) -> bool:
    """Return whether an exception indicates a lost/unavailable Frida server."""

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        type_name = type(current).__name__.lower()
        if type_name in _FRIDA_CONNECTION_TYPES:
            return True
        message = str(current).lower()
        if any(marker in message for marker in _FRIDA_CONNECTION_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _recovery_lock(key: tuple[str, int, str]) -> threading.Lock:
    with _SERVER_LOCKS_GUARD:
        lock = _SERVER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SERVER_LOCKS[key] = lock
        return lock


class FridaServerRecovery:
    """Restart the Frida server belonging to a forwarded ADB device."""

    def __init__(
        self,
        host: str,
        *,
        adb: AdbClient | None = None,
        server_path: str = FRIDA_SERVER_REMOTE_PATH,
    ) -> None:
        self.host = host
        self.adb = adb
        self.server_path = server_path

    def _adb_client(self) -> AdbClient:
        if self.adb is None:
            self.adb = AdbClient()
        return self.adb

    def _local_forward_name(self) -> str:
        host, separator, raw_port = self.host.rpartition(":")
        if not separator or not raw_port.isdecimal():
            raise FridaDriverError(
                f"cannot recover Frida server: invalid host {self.host!r}"
            )
        if host not in {"127.0.0.1", "localhost"}:
            raise FridaDriverError(
                "cannot recover Frida server: recovery host must be loopback"
            )
        port = int(raw_port)
        if not 1 <= port <= 65535:
            raise FridaDriverError(
                f"cannot recover Frida server: invalid port {port}"
            )
        return f"tcp:{port}"

    def _find_forward(self) -> tuple[str, int]:
        local = self._local_forward_name()
        try:
            forwards = self._adb_client().forward_list()
        except (AdbError, OSError) as exc:
            raise FridaDriverError(
                f"cannot recover Frida server: cannot inspect ADB forwards: {exc}"
            ) from exc
        matches = [forward for forward in forwards if forward.local == local]
        if len(matches) != 1:
            raise FridaDriverError(
                f"cannot recover Frida server: expected one ADB forward for "
                f"{local}, found {len(matches)}"
            )
        remote = matches[0].remote
        prefix, separator, raw_port = remote.partition(":")
        if prefix != "tcp" or not separator or not raw_port.isdecimal():
            raise FridaDriverError(
                f"cannot recover Frida server: invalid remote forward {remote!r}"
            )
        remote_port = int(raw_port)
        if not 1 <= remote_port <= 65535:
            raise FridaDriverError(
                f"cannot recover Frida server: invalid remote port {remote_port}"
            )
        return matches[0].serial, remote_port

    def _restart_script(self, remote_port: int) -> str:
        if self.server_path != FRIDA_SERVER_REMOTE_PATH:
            raise FridaDriverError(
                "cannot recover Frida server: unexpected server path"
            )
        endpoint = f"127.0.0.1:{remote_port}"
        return (
            f"server_path={shlex.quote(self.server_path)}; "
            f"endpoint={shlex.quote(endpoint)}; "
            'expected_cmdline=$(printf "%s\\n-D\\n-l\\n%s" '
            '"$server_path" "$endpoint"); '
            "process_matches() { "
            'candidate_pid="$1"; candidate_proc="/proc/$candidate_pid"; '
            '[ -d "$candidate_proc" ] || return 1; '
            '[ "$(readlink "$candidate_proc/exe" 2>/dev/null)" = '
            '"$server_path" ] || return 1; '
            'actual_cmdline=$(tr "\\000" "\\n" '
            '<"$candidate_proc/cmdline" 2>/dev/null) || return 1; '
            '[ "$actual_cmdline" = "$expected_cmdline" ]; '
            "}; "
            "owns_listener() { "
            'candidate_pid="$1"; '
            'ss -ltnp 2>/dev/null | awk -v endpoint="$endpoint" '
            '-v pidtoken="pid=$candidate_pid," '
            "'$1 == \"LISTEN\" && $4 == endpoint && "
            "index($0, pidtoken) > 0 { found = 1 } "
            "END { exit found ? 0 : 1 }'; "
            "}; "
            "endpoint_is_listening() { "
            'ss -ltn 2>/dev/null | awk -v endpoint="$endpoint" '
            "'$1 == \"LISTEN\" && $4 == endpoint { found = 1 } "
            "END { exit found ? 0 : 1 }'; "
            "}; "
            'matches=""; match_count=0; '
            "for candidate_proc in /proc/[0-9]*; do "
            '[ -d "$candidate_proc" ] || continue; '
            'candidate_pid="${candidate_proc##*/}"; '
            'if process_matches "$candidate_pid"; then '
            'matches="$matches $candidate_pid"; '
            'match_count=$((match_count + 1)); fi; '
            "done; "
            '[ "$match_count" -le 1 ] || { '
            'echo "multiple exact Frida server processes found" >&2; exit 20; }; '
            "if endpoint_is_listening; then "
            '[ "$match_count" -eq 1 ] || { '
            'echo "Frida endpoint is owned by an unexpected process" >&2; '
            "exit 21; }; "
            'old_pid="${matches# }"; owns_listener "$old_pid" || { '
            'echo "exact Frida process does not own its endpoint" >&2; '
            "exit 22; }; "
            "fi; "
            'restarted=0; if [ "$match_count" -eq 1 ]; then '
            'old_pid="${matches# }"; process_matches "$old_pid" || { '
            'echo "Frida process identity changed before termination" >&2; '
            "exit 23; }; "
            'kill -TERM "$old_pid" || exit 24; attempt=0; '
            'while process_matches "$old_pid" && [ "$attempt" -lt 20 ]; do '
            'attempt=$((attempt + 1)); sleep 0.1; done; '
            'if process_matches "$old_pid"; then '
            'kill -KILL "$old_pid" || exit 25; attempt=0; '
            'while process_matches "$old_pid" && [ "$attempt" -lt 20 ]; do '
            'attempt=$((attempt + 1)); sleep 0.1; done; fi; '
            'process_matches "$old_pid" && { '
            'echo "exact Frida process did not stop" >&2; exit 26; }; '
            "restarted=1; fi; "
            'attempt=0; while endpoint_is_listening && '
            '[ "$attempt" -lt 20 ]; do '
            'attempt=$((attempt + 1)); sleep 0.1; done; '
            'endpoint_is_listening && { '
            'echo "Frida endpoint remained busy after termination" >&2; '
            "exit 27; }; "
            '"$server_path" -D -l "$endpoint" '
            "</dev/null >/dev/null 2>&1 & "
            'attempt=0; while [ "$attempt" -lt 50 ]; do '
            'listener_pid=""; listener_count=0; '
            "for candidate_proc in /proc/[0-9]*; do "
            '[ -d "$candidate_proc" ] || continue; '
            'candidate_pid="${candidate_proc##*/}"; '
            'if process_matches "$candidate_pid" && '
            'owns_listener "$candidate_pid"; then '
            'listener_pid="$candidate_pid"; '
            'listener_count=$((listener_count + 1)); fi; done; '
            '[ "$listener_count" -le 1 ] || { '
            'echo "multiple exact Frida listeners found" >&2; exit 28; }; '
            'if [ "$listener_count" -eq 1 ]; then '
            'if [ "$restarted" -eq 1 ]; then printf "restarted:%s\\n" '
            '"$listener_pid"; else printf "started:%s\\n" '
            '"$listener_pid"; fi; exit 0; fi; '
            'attempt=$((attempt + 1)); sleep 0.1; done; '
            'if endpoint_is_listening; then '
            'echo "Frida endpoint was claimed by an unexpected process" >&2; '
            'exit 29; fi; '
            'echo "Frida server did not acquire its endpoint" >&2; exit 30'
        )

    def recover(self) -> str:
        serial, remote_port = self._find_forward()
        recovery_key = (serial, remote_port, self.server_path)
        lock = _recovery_lock(recovery_key)
        with _SERVER_LOCKS_GUARD:
            observed_generation = _SERVER_RECOVERY_GENERATIONS.get(recovery_key, 0)
        with lock:
            with _SERVER_LOCKS_GUARD:
                if (
                    _SERVER_RECOVERY_GENERATIONS.get(recovery_key, 0)
                    != observed_generation
                ):
                    return "already recovered"
            launch = self._restart_script(remote_port)
            try:
                output = self._adb_client().shell(
                    serial,
                    "su",
                    "0",
                    "sh",
                    "-c",
                    shlex.quote(launch),
                )
            except Exception as exc:
                raise FridaDriverError(
                    f"cannot recover Frida server on {serial}: {exc}"
                ) from exc
            with _SERVER_LOCKS_GUARD:
                _SERVER_RECOVERY_GENERATIONS[recovery_key] = observed_generation + 1
        return output

# The game runs through Houdini on MuMu's x86_64 images.  Its protection
# threads use this syscall gate directly, so libc exit hooks never see the
# exit_group request.  Keep the guard deliberately narrow and fail closed if
# the emulator image changes.
HOUDINI_GUARD_MODULE = "libhoudini.so"
HOUDINI_GUARD_OFFSET = 0x314890
HOUDINI_GUARD_SIGNATURE = bytes.fromhex("48 89 f8 48 89 f7 0f 05 c3")
HOUDINI_EXIT_GROUP = 231
HOUDINI_GETPID = 39


def load_houdini_guard_source() -> str:
    """Return the small, signature-checked Frida bootstrap guard."""

    return r'''"use strict";

const MODULE_NAME = "libhoudini.so";
const GATE_OFFSET = 0x314890;
const EXPECTED = [0x48, 0x89, 0xf8, 0x48, 0x89, 0xf7, 0x0f, 0x05, 0xc3];
const EXIT_GROUP = 231;
const GETPID = 39;

const module = Process.findModuleByName(MODULE_NAME);
if (module === null) {
  throw new Error(`${MODULE_NAME} is not loaded`);
}

const gate = module.base.add(GATE_OFFSET);
const raw = gate.readByteArray(EXPECTED.length);
if (raw === null) {
  throw new Error("could not read Houdini syscall gate");
}
const actual = Array.from(new Uint8Array(raw));
for (let index = 0; index < EXPECTED.length; index += 1) {
  if (actual[index] !== EXPECTED[index]) {
    throw new Error(
      `unexpected Houdini syscall gate signature at ${gate}: ` +
        actual.map((value) => value.toString(16).padStart(2, "0")).join(" "),
    );
  }
}

Interceptor.attach(gate, {
  onEnter(args) {
    // Only neutralize exit_group.  Ordinary exit(2) and every other syscall
    // must retain their original number.
    if (args[0].toUInt32() === EXIT_GROUP) {
      args[0] = ptr(GETPID);
    }
  },
});
'''


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    name: str


@dataclass(frozen=True, slots=True)
class LuaExecutionResult:
    output: str
    result_code: int
    thread_id: int
    thread_name: str


def load_agent_source() -> str:
    return resources.files("mumu_autotask").joinpath("frida_agent.bundle.js").read_text(
        encoding="utf-8"
    )


def _load_frida() -> ModuleType:
    try:
        import frida
    except ImportError as exc:
        raise FridaDriverError(
            "Frida is not installed; install the project dependencies first"
        ) from exc
    return frida


def _integer(value: Any, location: str) -> int:
    if isinstance(value, bool):
        raise FridaDriverError(f"{location} returned a boolean instead of an integer")
    try:
        return int(str(value), 10)
    except (TypeError, ValueError) as exc:
        raise FridaDriverError(f"{location} returned an invalid integer: {value!r}") from exc


def _probe_integer(value: Any) -> int:
    try:
        return int(str(value), 0)
    except (TypeError, ValueError) as exc:
        raise FridaDriverError(
            f"bridge initialize returned an invalid probe: {value!r}"
        ) from exc


class FridaLuaClient:
    def __init__(
        self,
        host: str,
        *,
        process_name: str,
        pid: int | None = None,
        process_aliases: Sequence[str] = (),
        agent_source: str | None = None,
        frida_api: Any | None = None,
        server_recovery: FridaServerRecovery | Callable[[], Any] | None = None,
    ) -> None:
        self.host = host
        self.process_name = process_name
        self.requested_pid = pid
        self.process_aliases = tuple(process_aliases)
        self.agent_source = agent_source
        self._frida = frida_api
        self._server_recovery = server_recovery
        self._device: Any | None = None
        self._session: Any | None = None
        self._guard_script: Any | None = None
        self._script: Any | None = None
        self._exports: Any | None = None
        self._process: ProcessInfo | None = None
        self._initialized = False
        self.messages: list[Mapping[str, Any]] = []

    def _api(self) -> Any:
        if self._frida is None:
            self._frida = _load_frida()
        return self._frida

    def _remote_device(self) -> Any:
        if self._device is None:
            try:
                manager = self._api().get_device_manager()
                self._device = manager.add_remote_device(self.host)
            except Exception as exc:
                raise FridaDriverError(
                    f"cannot connect to Frida server at {self.host}: {exc}"
                ) from exc
        return self._device

    def _reset_after_server_recovery(self) -> None:
        try:
            self.close()
        finally:
            self._device = None
            self._session = None
            self._guard_script = None
            self._script = None
            self._exports = None
            self._process = None
            self._initialized = False

    def _recover_server(self) -> None:
        recovery = self._server_recovery
        if recovery is None:
            recovery = FridaServerRecovery(self.host)
            self._server_recovery = recovery
        try:
            if callable(recovery):
                recovery()
            else:
                recovery.recover()
        except FridaDriverError:
            raise
        except Exception as exc:
            raise FridaDriverError(
                f"cannot recover Frida server at {self.host}: {exc}"
            ) from exc

    def _with_server_recovery(self, action: Callable[[], Any]) -> Any:
        try:
            return action()
        except Exception as exc:
            if not _is_connection_failure(exc):
                raise
            self._recover_server()
            self._reset_after_server_recovery()
            # Deliberately retry exactly once.  A second failure is returned
            # directly to the caller and cannot recurse into recovery.
            return action()

    def _inspect_process_once(self) -> ProcessInfo:
        if self._process is not None:
            return self._process
        try:
            processes = list(self._remote_device().enumerate_processes())
        except Exception as exc:
            raise FridaDriverError(
                f"cannot enumerate processes through Frida at {self.host}: {exc}"
            ) from exc

        if self.requested_pid is not None:
            matches = [item for item in processes if item.pid == self.requested_pid]
            if len(matches) != 1:
                raise FridaDriverError(
                    f"expected PID {self.requested_pid} at {self.host}, found "
                    f"{len(matches)} matches"
                )
            process = matches[0]
            allowed_names = {self.process_name, *self.process_aliases}
            allowed_names.discard("")
            if allowed_names and process.name not in allowed_names:
                raise FridaDriverError(
                    f"PID {process.pid} is {process.name!r}, not one of "
                    f"{sorted(allowed_names)!r}"
                )
        else:
            matches = [item for item in processes if item.name == self.process_name]
            if len(matches) != 1:
                found = ", ".join(f"{item.pid}:{item.name}" for item in matches) or "none"
                raise FridaDriverError(
                    f"expected one process named {self.process_name!r} at "
                    f"{self.host}, found {found}"
                )
            process = matches[0]
        self._process = ProcessInfo(process.pid, process.name)
        return self._process

    def inspect_process(self) -> ProcessInfo:
        if self._process is not None:
            return self._process
        return self._with_server_recovery(self._inspect_process_once)

    def _connect_once(self) -> ProcessInfo:
        process = self._inspect_process_once()
        session = None
        guard_script = None
        script = None
        exports = None
        try:
            session = self._remote_device().attach(process.pid)
            guard_script = session.create_script(load_houdini_guard_source())
            if hasattr(guard_script, "on"):
                guard_script.on("message", self._on_message)
            guard_script.load()

            script = session.create_script(self.agent_source or load_agent_source())
            if hasattr(script, "on"):
                script.on("message", self._on_message)
            script.load()
            exports = script.exports_sync
        except Exception as exc:
            for candidate in (script, guard_script):
                if candidate is not None and hasattr(candidate, "unload"):
                    try:
                        candidate.unload()
                    except Exception:
                        pass
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
            raise FridaDriverError(
                f"cannot attach to PID {process.pid} at {self.host}: {exc}"
            ) from exc
        self._session = session
        self._guard_script = guard_script
        self._script = script
        self._exports = exports
        return process

    def connect(self) -> ProcessInfo:
        if self._session is not None:
            return self.inspect_process()
        return self._with_server_recovery(self._connect_once)

    def _on_message(self, message: Mapping[str, Any], data: bytes | None) -> None:
        entry = dict(message)
        if data is not None:
            entry["data_length"] = len(data)
        self.messages.append(entry)

    def _require_exports(self) -> Any:
        if self._exports is None:
            raise FridaDriverError("connect() must be called before bridge RPCs")
        return self._exports

    def initialize_bridge(self, remote_path: str) -> Mapping[str, Any]:
        if not remote_path or not remote_path.strip():
            raise FridaDriverError("bridge path cannot be empty")
        exports = self._require_exports()
        try:
            initialization = exports.initialize(remote_path)
        except Exception as exc:
            raise FridaDriverError(f"cannot initialize ARM64 bridge: {exc}") from exc
        if not isinstance(initialization, Mapping):
            raise FridaDriverError(
                f"bridge initialize returned invalid data: {initialization!r}"
            )
        probe = _probe_integer(initialization.get("probe"))
        if probe != EXPECTED_BRIDGE_PROBE:
            raise FridaDriverError(
                f"ARM64 bridge probe mismatch: 0x{probe:x} != "
                f"0x{EXPECTED_BRIDGE_PROBE:x}"
            )
        self._initialized = True
        return dict(initialization)

    def execute_lua(
        self,
        state_address: int | str,
        code: str,
        *,
        output_capacity: int = 16384,
    ) -> LuaExecutionResult:
        if not self._initialized:
            raise FridaDriverError("the ARM64 bridge is not initialized")
        if isinstance(state_address, bool):
            raise FridaDriverError("Lua state address must be a positive integer")
        try:
            address = (
                state_address
                if isinstance(state_address, int)
                else int(str(state_address), 0)
            )
        except (TypeError, ValueError) as exc:
            raise FridaDriverError(
                f"Lua state address is invalid: {state_address!r}"
            ) from exc
        if address <= 0:
            raise FridaDriverError("Lua state address must be a positive integer")
        if not code or not code.strip():
            raise FridaDriverError("Lua code cannot be empty")
        code_size = len(code.encode("utf-8"))
        if code_size >= LUA_BRIDGE_CODE_CAPACITY:
            raise FridaDriverError(
                f"Lua code is {code_size} UTF-8 bytes; bridge limit is "
                f"{LUA_BRIDGE_CODE_CAPACITY - 1}"
            )
        if (
            isinstance(output_capacity, bool)
            or not isinstance(output_capacity, int)
            or not 2 <= output_capacity <= 16384
        ):
            raise FridaDriverError(
                "output capacity must be an integer between 2 and 16384"
            )
        exports = self._require_exports()
        try:
            response = exports.execute(f"0x{address:x}", code, output_capacity)
        except Exception as exc:
            raise FridaDriverError(f"cannot execute Lua code: {exc}") from exc
        if not isinstance(response, Mapping):
            raise FridaDriverError(
                f"bridge execute returned invalid data: {response!r}"
            )
        ok = response.get("ok")
        if not isinstance(ok, bool):
            raise FridaDriverError(
                f"bridge execute returned invalid success state: {ok!r}"
            )
        result_code = _integer(response.get("result"), "bridge execute")
        output = str(response.get("output", ""))
        thread_id = _integer(response.get("threadId"), "bridge execute threadId")
        thread_name = response.get("threadName")
        thread_mode = response.get("threadMode")
        if thread_id <= 0 or (
            thread_name != "UnityMain" and thread_mode != "frida-direct"
        ):
            raise FridaDriverError(
                "bridge execute did not run on a valid Unity thread or "
                "approved direct bridge thread: "
                f"id={thread_id}, name={thread_name!r}, mode={thread_mode!r}"
            )
        if not ok or result_code <= 0:
            raise LuaExecutionError(
                f"Lua execution failed with bridge result {result_code}: {output}",
                output=output,
                result_code=result_code,
            )
        return LuaExecutionResult(output, result_code, thread_id, thread_name)

    def close(self) -> None:
        session = self._session
        script = self._script
        guard_script = self._guard_script
        if session is None:
            return
        for candidate in (script, guard_script):
            if candidate is not None and hasattr(candidate, "unload"):
                try:
                    candidate.unload()
                except Exception:
                    pass
        try:
            session.detach()
        finally:
            self._session = None
            self._guard_script = None
            self._script = None
            self._exports = None
            self._initialized = False

    def __enter__(self) -> "FridaLuaClient":
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
