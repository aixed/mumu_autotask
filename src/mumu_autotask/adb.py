from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class AdbError(RuntimeError):
    """Raised when ADB cannot be located or a command fails."""


@dataclass(frozen=True, slots=True)
class AdbDevice:
    serial: str
    state: str
    details: dict[str, str]

    @property
    def connected(self) -> bool:
        return self.state == "device"


@dataclass(frozen=True, slots=True)
class AdbForward:
    serial: str
    local: str
    remote: str


@dataclass(frozen=True, slots=True)
class ForegroundActivity:
    component: str | None
    source: str | None
    line: str | None

    @property
    def present(self) -> bool:
        return self.component is not None

    def matches(self, expected_component: str) -> bool:
        if self.component is None:
            return False
        return self.component == _canonical_component(expected_component)


@dataclass(frozen=True, slots=True)
class WindowSize:
    width: int
    height: int


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
BinaryCommandRunner = Callable[
    [Sequence[str], float], subprocess.CompletedProcess[bytes]
]


_ACTIVITY_COMPONENT_PATTERN = re.compile(
    r"\b([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)\b"
)
_ACTIVITY_MARKERS = (
    "topResumedActivity",
    "mResumedActivity",
    "ResumedActivity",
    "mCurrentFocus",
    "mFocusedApp",
)
_WINDOW_SIZE_PATTERN = re.compile(r"\b(\d+)x(\d+)\b")


def _pid_tokens(output: str) -> list[int]:
    pids: list[int] = []
    for token in output.split():
        if token.isdecimal():
            pids.append(int(token))
    return pids


def _pid_from_ps(output: str, process_name: str) -> list[int]:
    """Return PIDs whose final ps name column exactly equals process_name."""

    pids: list[int] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        if fields[0].upper() == "USER" or fields[-1] != process_name:
            continue
        pid: int | None = None
        if fields[0].isdecimal():
            pid = int(fields[0])
        elif fields[1].isdecimal():
            pid = int(fields[1])
        if pid is not None:
            pids.append(pid)
    return pids


def _canonical_component(component: str) -> str:
    package, separator, activity = component.partition("/")
    if not separator:
        return component
    if activity.startswith("."):
        activity = f"{package}{activity}"
    return f"{package}/{activity}"


def _foreground_from_dump(output: str, source: str) -> ForegroundActivity:
    for marker in _ACTIVITY_MARKERS:
        for line in output.splitlines():
            if marker not in line:
                continue
            matches = [
                _canonical_component(f"{match.group(1)}/{match.group(2)}")
                for match in _ACTIVITY_COMPONENT_PATTERN.finditer(line)
            ]
            if matches:
                return ForegroundActivity(matches[-1], source, line.strip())
    return ForegroundActivity(None, source, None)


def _default_runner(
    args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _default_binary_runner(
    args: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(args),
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def resolve_adb_executable(explicit: str | None = None) -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        located = shutil.which(explicit)
        if located:
            return located
        raise AdbError(f"configured ADB executable does not exist: {explicit}")

    located = shutil.which("adb")
    if located:
        return located

    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Netease" / "MuMu" / "nx_main" / "adb.exe")
    candidates.append(Path("D:/Program Files/Netease/MuMu/nx_main/adb.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise AdbError(
        "ADB was not found on PATH or in the standard MuMu installation; "
        "set adb.executable in config.json"
    )


class AdbClient:
    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: float = 10,
        runner: CommandRunner | None = None,
        binary_runner: BinaryCommandRunner | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self._binary_runner = binary_runner or _default_binary_runner
        self.executable = executable if runner else resolve_adb_executable(executable)
        if not self.executable:
            raise AdbError("ADB executable cannot be empty")
        self.timeout_seconds = timeout_seconds

    def _run(self, *args: str) -> str:
        command = [self.executable, *args]
        try:
            completed = self._runner(command, self.timeout_seconds)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(f"ADB command failed to start: {' '.join(command)}: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise AdbError(
                f"ADB command returned {completed.returncode}: {' '.join(command)}: {detail}"
            )
        return completed.stdout.strip()

    def _run_bytes(self, *args: str) -> bytes:
        command = [self.executable, *args]
        try:
            completed = self._binary_runner(command, self.timeout_seconds)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(
                f"ADB binary command failed to start: {' '.join(command)}: {exc}"
            ) from exc
        if completed.returncode != 0:
            stderr = completed.stderr
            if isinstance(stderr, bytes):
                detail = stderr.decode("utf-8", errors="replace").strip()
            else:
                detail = str(stderr or "").strip()
            raise AdbError(
                f"ADB binary command returned {completed.returncode}: "
                f"{' '.join(command)}: {detail}"
            )
        return bytes(completed.stdout)

    def connect(self, target: str) -> str:
        return self._run("connect", target)

    def devices(self) -> list[AdbDevice]:
        output = self._run("devices", "-l")
        devices: list[AdbDevice] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached") or line.startswith("*"):
                continue
            fields = line.split()
            if len(fields) < 2:
                continue
            details: dict[str, str] = {}
            for field in fields[2:]:
                if ":" in field:
                    key, value = field.split(":", 1)
                    details[key] = value
            devices.append(AdbDevice(fields[0], fields[1], details))
        return devices

    def connect_configured(self, targets: Sequence[str]) -> list[AdbDevice]:
        for target in targets:
            self.connect(target)
        return self.devices()

    def require_connected(self, serials: Sequence[str]) -> None:
        state_by_serial = {device.serial: device.state for device in self.devices()}
        failures = [
            f"{serial} ({state_by_serial.get(serial, 'missing')})"
            for serial in serials
            if state_by_serial.get(serial) != "device"
        ]
        if failures:
            raise AdbError("ADB devices are not ready: " + ", ".join(failures))

    def shell(self, serial: str, *args: str) -> str:
        if not args:
            raise AdbError("an explicit non-interactive shell command is required")
        return self._run("-s", serial, "shell", *args)

    def push(self, local_path: str | Path, remote_path: str) -> str:
        """Copy one trusted local runtime asset to an ADB device."""

        local = Path(local_path).expanduser()
        if not local.is_file():
            raise AdbError(f"local ADB push source does not exist: {local}")
        if not remote_path or not remote_path.startswith("/"):
            raise AdbError("remote ADB push path must be absolute")
        return self._run("push", str(local), remote_path)

    def pidof(self, serial: str, package_name: str) -> int:
        pids = _pid_tokens(self.shell(serial, "pidof", package_name))
        if len(pids) == 1:
            return pids[0]
        if len(pids) > 1:
            try:
                exact = _pid_from_ps(self.shell(serial, "ps", "-A"), package_name)
            except AdbError:
                exact = []
            if len(exact) == 1:
                return exact[0]
            raise AdbError(
                f"expected one main PID for {package_name!r} on {serial}, "
                f"found {pids!r}"
            )
        raise AdbError(
            f"expected one PID for {package_name!r} on {serial}, found {pids!r}"
        )

    def foreground_activity(self, serial: str) -> ForegroundActivity:
        for source, args in (
            ("activity", ("dumpsys", "activity", "activities")),
            ("window", ("dumpsys", "window")),
        ):
            state = _foreground_from_dump(self.shell(serial, *args), source)
            if state.present:
                return state
        return ForegroundActivity(None, None, None)

    def background_app(self, serial: str) -> str:
        return self.shell(serial, "input", "keyevent", "KEYCODE_HOME")

    def start_activity(self, serial: str, component: str) -> str:
        return self.shell(serial, "am", "start", "-n", component)

    def restart_package(self, serial: str, package_name: str, component: str) -> str:
        """Stop one package and start its configured activity again."""

        if not package_name or not component:
            raise AdbError("package name and activity component are required")
        self.shell(serial, "am", "force-stop", package_name)
        return self.start_activity(serial, component)

    def input_tap(self, serial: str, x: int, y: int) -> str:
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, int)
            or not isinstance(y, int)
            or x < 0
            or y < 0
        ):
            raise AdbError("tap coordinates must be non-negative integers")
        return self.shell(serial, "input", "tap", str(x), str(y))

    def window_size(self, serial: str) -> WindowSize:
        output = self.shell(serial, "wm", "size")
        match = _WINDOW_SIZE_PATTERN.search(output)
        if match is None:
            raise AdbError(f"could not parse window size on {serial}: {output!r}")
        width = int(match.group(1))
        height = int(match.group(2))
        if width <= 0 or height <= 0:
            raise AdbError(f"invalid window size on {serial}: {width}x{height}")
        return WindowSize(width, height)

    def exec_out(self, serial: str, *args: str) -> bytes:
        if not args:
            raise AdbError("an explicit non-interactive exec-out command is required")
        return self._run_bytes("-s", serial, "exec-out", *args)

    def forward(self, serial: str, local: str, remote: str) -> str:
        return self._run("-s", serial, "forward", local, remote)

    def forward_remove(self, serial: str, local: str) -> str:
        return self._run("-s", serial, "forward", "--remove", local)

    def forward_list(self) -> list[AdbForward]:
        output = self._run("forward", "--list")
        forwards: list[AdbForward] = []
        for line_number, line in enumerate(output.splitlines(), start=1):
            fields = line.split()
            if not fields:
                continue
            if len(fields) != 3 or not all(fields):
                raise AdbError(
                    f"invalid ADB forward entry on line {line_number}: {line!r}"
                )
            forwards.append(AdbForward(*fields))
        return forwards
