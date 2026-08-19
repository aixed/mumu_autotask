from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class GuiBackendError(RuntimeError):
    """Raised when a background CLI operation cannot be completed."""

    def __init__(self, message: str, *, diagnostic: str | None = None) -> None:
        self.summary = message
        self.diagnostic = diagnostic or message
        super().__init__(self.diagnostic)


GUI_QUALITY_ORDER = ("green", "blue", "purple", "yellow")
GUI_CATEGORY_ORDER = ("monster", "hero", "rescue")
DEFAULT_GUI_QUALITIES = ("purple",)
DEFAULT_GUI_CATEGORY = "monster"
DEFAULT_GUI_CATEGORIES = GUI_CATEGORY_ORDER
MIN_HUNT_CONCURRENCY = 1
MAX_HUNT_CONCURRENCY = 4
DEFAULT_HUNT_CONCURRENCY = 3
MIN_WORLD_MONSTER_LEVEL = 1
MAX_WORLD_MONSTER_LEVEL = 20
DEFAULT_WORLD_MONSTER_LEVEL = 16
MIN_WORLD_MONSTER_CONCURRENCY = 1
MAX_WORLD_MONSTER_CONCURRENCY = 4
DEFAULT_WORLD_MONSTER_CONCURRENCY = 4
GUI_PREFERENCES_FILENAME = "mumu_autotask_gui_preferences.json"


class GuiPreferences:
    """Persist per-device GUI choices without changing the guarded config."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path).resolve() if path is not None else None
        self._lock = threading.Lock()
        self._memory_data: dict[str, Any] = self._empty_data()

    @classmethod
    def for_config(cls, config_path: str | Path) -> "GuiPreferences":
        config = Path(config_path).resolve()
        return cls(config.with_name(GUI_PREFERENCES_FILENAME))

    def get_selected_qualities(self, serial: str) -> tuple[str, ...]:
        serial = self._validate_serial(serial)
        with self._lock:
            data = self._read()
            devices = data["devices"]
            section = devices.get(serial)
            if section is None:
                return DEFAULT_GUI_QUALITIES
            qualities = section["qualities"]
            return tuple(
                quality
                for quality in GUI_QUALITY_ORDER
                if qualities[quality]
            )

    def get_category(self, serial: str) -> str:
        categories = self.get_selected_categories(serial)
        return categories[0] if categories else DEFAULT_GUI_CATEGORY

    def get_selected_categories(self, serial: str) -> tuple[str, ...]:
        serial = self._validate_serial(serial)
        with self._lock:
            data = self._read()
            section = data["devices"].get(serial)
            if section is None:
                return DEFAULT_GUI_CATEGORIES
            categories = section["categories"]
            return tuple(
                category
                for category in GUI_CATEGORY_ORDER
                if categories[category]
            )

    def set_category(self, serial: str, category: str) -> None:
        self.set_selected_categories(serial, (category,))

    def set_selected_categories(
        self,
        serial: str,
        categories: Sequence[str],
    ) -> None:
        serial = self._validate_serial(serial)
        selected = self._validate_categories(categories)
        with self._lock:
            data = self._read()
            devices = dict(data["devices"])
            section = dict(devices.get(serial, self._default_device_section()))
            section["categories"] = {
                category: category in selected for category in GUI_CATEGORY_ORDER
            }
            devices[serial] = section
            updated = {"version": 1, "devices": devices}
            self._write(updated)
            self._memory_data = updated

    def set_selected_qualities(
        self,
        serial: str,
        qualities: Sequence[str],
    ) -> None:
        serial = self._validate_serial(serial)
        selected = self._validate_qualities(qualities)
        with self._lock:
            data = self._read()
            devices = dict(data["devices"])
            section = dict(devices.get(serial, self._default_device_section()))
            section["qualities"] = {
                quality: quality in selected for quality in GUI_QUALITY_ORDER
            }
            devices[serial] = section
            updated = {"version": 1, "devices": devices}
            self._write(updated)
            self._memory_data = updated

    def get_concurrency(self, serial: str) -> int:
        serial = self._validate_serial(serial)
        with self._lock:
            data = self._read()
            section = data["devices"].get(serial)
            if section is None:
                return DEFAULT_HUNT_CONCURRENCY
            return int(section["concurrency"])

    def set_concurrency(self, serial: str, value: int) -> None:
        serial = self._validate_serial(serial)
        concurrency = self._validate_concurrency(value)
        with self._lock:
            data = self._read()
            devices = dict(data["devices"])
            section = dict(devices.get(serial, self._default_device_section()))
            section["concurrency"] = concurrency
            devices[serial] = section
            updated = {"version": 1, "devices": devices}
            self._write(updated)
            self._memory_data = updated

    def get_world_monster_level(self, serial: str) -> int:
        serial = self._validate_serial(serial)
        with self._lock:
            data = self._read()
            section = data["devices"].get(serial)
            if section is None:
                return DEFAULT_WORLD_MONSTER_LEVEL
            return int(section["world_monster_level"])

    def set_world_monster_level(self, serial: str, value: int) -> None:
        serial = self._validate_serial(serial)
        level = self._validate_world_monster_level(value)
        with self._lock:
            data = self._read()
            devices = dict(data["devices"])
            section = dict(devices.get(serial, self._default_device_section()))
            section["world_monster_level"] = level
            devices[serial] = section
            updated = {"version": 1, "devices": devices}
            self._write(updated)
            self._memory_data = updated

    def get_world_monster_concurrency(self, serial: str) -> int:
        serial = self._validate_serial(serial)
        with self._lock:
            data = self._read()
            section = data["devices"].get(serial)
            if section is None:
                return DEFAULT_WORLD_MONSTER_CONCURRENCY
            return int(section["world_monster_concurrency"])

    def set_world_monster_concurrency(self, serial: str, value: int) -> None:
        serial = self._validate_serial(serial)
        concurrency = self._validate_world_monster_concurrency(value)
        with self._lock:
            data = self._read()
            devices = dict(data["devices"])
            section = dict(devices.get(serial, self._default_device_section()))
            section["world_monster_concurrency"] = concurrency
            devices[serial] = section
            updated = {"version": 1, "devices": devices}
            self._write(updated)
            self._memory_data = updated

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {"version": 1, "devices": {}}

    @staticmethod
    def _default_device_section() -> dict[str, Any]:
        return {
            "categories": {
                category: category in DEFAULT_GUI_CATEGORIES
                for category in GUI_CATEGORY_ORDER
            },
            "qualities": {
                quality: quality in DEFAULT_GUI_QUALITIES
                for quality in GUI_QUALITY_ORDER
            },
            "concurrency": DEFAULT_HUNT_CONCURRENCY,
            "world_monster_level": DEFAULT_WORLD_MONSTER_LEVEL,
            "world_monster_concurrency": DEFAULT_WORLD_MONSTER_CONCURRENCY,
        }

    @staticmethod
    def _validate_serial(serial: str) -> str:
        if not isinstance(serial, str) or not serial.strip():
            raise GuiBackendError("ADB serial 不能为空")
        if any(ord(char) < 32 or ord(char) == 127 for char in serial):
            raise GuiBackendError("ADB serial 包含控制字符")
        return serial

    @staticmethod
    def _validate_qualities(qualities: Sequence[str]) -> set[str]:
        if isinstance(qualities, (str, bytes)):
            raise GuiBackendError("GUI 品质偏好必须是列表")
        selected = set(qualities)
        invalid = sorted(selected.difference(GUI_QUALITY_ORDER))
        if invalid:
            raise GuiBackendError(f"GUI 品质偏好包含未知值：{invalid}")
        return selected

    @staticmethod
    def _validate_category(category: str) -> str:
        if not isinstance(category, str):
            raise GuiBackendError("GUI 情报类别必须是文本")
        normalized = category.strip().lower()
        if normalized not in GUI_CATEGORY_ORDER:
            raise GuiBackendError(f"GUI 情报类别无效：{category!r}")
        return normalized

    @staticmethod
    def _validate_categories(categories: Sequence[str]) -> set[str]:
        if isinstance(categories, (str, bytes)):
            raise GuiBackendError("GUI 情报类别偏好必须是列表")
        selected = set()
        for category in categories:
            selected.add(GuiPreferences._validate_category(category))
        return selected

    @staticmethod
    def _validate_concurrency(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not MIN_HUNT_CONCURRENCY <= value <= MAX_HUNT_CONCURRENCY
        ):
            raise GuiBackendError(
                f"并发出征数必须是 {MIN_HUNT_CONCURRENCY}-{MAX_HUNT_CONCURRENCY} 的整数"
            )
        return value

    @staticmethod
    def _validate_world_monster_level(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not MIN_WORLD_MONSTER_LEVEL <= value <= MAX_WORLD_MONSTER_LEVEL
        ):
            raise GuiBackendError(
                f"野兽等级必须是 {MIN_WORLD_MONSTER_LEVEL}-{MAX_WORLD_MONSTER_LEVEL} 的整数"
            )
        return value

    @staticmethod
    def _validate_world_monster_concurrency(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not MIN_WORLD_MONSTER_CONCURRENCY
            <= value
            <= MAX_WORLD_MONSTER_CONCURRENCY
        ):
            raise GuiBackendError(
                "搜索野兽并发出征数必须是 "
                f"{MIN_WORLD_MONSTER_CONCURRENCY}-{MAX_WORLD_MONSTER_CONCURRENCY} 的整数"
            )
        return value

    def _read(self) -> dict[str, Any]:
        if self.path is None:
            return {
                "version": self._memory_data["version"],
                "devices": dict(self._memory_data["devices"]),
            }
        if not self.path.exists():
            return self._empty_data()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise GuiBackendError(f"无法读取 GUI 偏好文件：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise GuiBackendError(
                f"GUI 偏好文件不是有效 JSON：第 {exc.lineno} 行"
            ) from exc
        return self._validate_data(raw)

    @classmethod
    def _validate_data(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise GuiBackendError("GUI 偏好文件版本无效")
        devices = raw.get("devices")
        if not isinstance(devices, dict):
            raise GuiBackendError("GUI 偏好文件缺少 devices 配置段")
        validated: dict[str, Any] = {}
        for serial, section in devices.items():
            serial = cls._validate_serial(serial)
            if not isinstance(section, dict):
                raise GuiBackendError(f"{serial} 的 GUI 偏好配置段无效")
            raw_categories = section.get("categories")
            if raw_categories is None:
                if "category" in section:
                    selected_categories = {
                        cls._validate_category(section["category"])
                    }
                else:
                    selected_categories = set(DEFAULT_GUI_CATEGORIES)
                categories = {
                    category: category in selected_categories
                    for category in GUI_CATEGORY_ORDER
                }
            else:
                if not isinstance(raw_categories, dict):
                    raise GuiBackendError(f"{serial} 的 categories 配置段无效")
                unknown_categories = sorted(
                    set(raw_categories).difference(GUI_CATEGORY_ORDER)
                )
                if unknown_categories:
                    raise GuiBackendError(
                        f"{serial} 包含未知情报类别：{unknown_categories}"
                    )
                categories = {}
                for category in GUI_CATEGORY_ORDER:
                    selected = raw_categories.get(category, False)
                    if not isinstance(selected, bool):
                        raise GuiBackendError(
                            f"{serial}.{category} 的 GUI 类别偏好必须是布尔值"
                        )
                    categories[category] = selected
            qualities = section.get("qualities")
            if not isinstance(qualities, dict):
                raise GuiBackendError(f"{serial} 的 qualities 配置段无效")
            unknown = sorted(set(qualities).difference(GUI_QUALITY_ORDER))
            if unknown:
                raise GuiBackendError(f"{serial} 包含未知品质：{unknown}")
            normalized: dict[str, bool] = {}
            for quality in GUI_QUALITY_ORDER:
                selected = qualities.get(quality, False)
                if not isinstance(selected, bool):
                    raise GuiBackendError(
                        f"{serial}.{quality} 的 GUI 偏好必须是布尔值"
                    )
                normalized[quality] = selected
            concurrency = cls._validate_concurrency(
                section.get("concurrency", DEFAULT_HUNT_CONCURRENCY)
            )
            world_monster_level = cls._validate_world_monster_level(
                section.get("world_monster_level", DEFAULT_WORLD_MONSTER_LEVEL)
            )
            world_monster_concurrency = cls._validate_world_monster_concurrency(
                section.get(
                    "world_monster_concurrency",
                    DEFAULT_WORLD_MONSTER_CONCURRENCY,
                )
            )
            validated[serial] = {
                "categories": categories,
                "qualities": normalized,
                "concurrency": concurrency,
                "world_monster_level": world_monster_level,
                "world_monster_concurrency": world_monster_concurrency,
            }
        return {"version": 1, "devices": validated}

    def _write(self, data: Mapping[str, Any]) -> None:
        if self.path is None:
            return
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise GuiBackendError(f"无法保存 GUI 偏好文件：{exc}") from exc


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def console_python_executable(executable: str | None = None) -> str:
    """Return a console Python executable suitable for captured subprocess I/O."""

    current = Path(executable or sys.executable)
    lowered = current.name.lower()
    if lowered == "pythonw.exe":
        candidate = current.with_name("python.exe")
        if candidate.is_file():
            return str(candidate)
    if lowered == "pyw.exe":
        candidate = current.with_name("py.exe")
        if candidate.is_file():
            return str(candidate)
    return str(current)


def parse_json_lines(output: str) -> tuple[dict[str, Any], ...]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise GuiBackendError("命令没有返回 JSON 数据")
    payloads: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GuiBackendError(f"第 {index} 行不是有效的 JSON 数据") from exc
        if not isinstance(payload, dict):
            raise GuiBackendError(f"第 {index} 行 JSON 必须是对象")
        payloads.append(payload)
    return tuple(payloads)


_MAX_ERROR_CONTEXT_LINES = 80
_MAX_ERROR_CONTEXT_CHARS = 16_384
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LOG_RECORD_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\S+\s+(?P<message>.*)$"
)
_ERROR_START_RE = re.compile(
    r"^(?:Traceback \(most recent call last\):|"
    r"(?:[A-Za-z_][\w.]*)?(?:Error|Exception)(?::|$))"
)


def _clean_error_lines(source: str) -> list[str]:
    cleaned = _ANSI_CSI_RE.sub("", source)
    cleaned = _CONTROL_RE.sub("?", cleaned)
    return [line.rstrip() for line in cleaned.splitlines() if line.strip()]


def _select_error_lines(source: str) -> list[str]:
    lines = _clean_error_lines(source)
    if not lines:
        return []

    log_records = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _LOG_RECORD_RE.match(line)) is not None
    ]
    error_records = [
        (index, match)
        for index, match in log_records
        if match.group("level") in {"ERROR", "CRITICAL"}
    ]
    if error_records:
        # The CLI emits its handled terminal error last.  Keep that record and
        # its multiline Frida continuation, but omit earlier startup warnings.
        start, record = error_records[-1]
        selected = [record.group("message").strip(), *lines[start + 1 :]]
        return selected

    for index, line in enumerate(lines):
        if _ERROR_START_RE.match(line.lstrip()):
            return lines[index:]

    # stdout is only a fallback for tools that do not use stderr.  A single
    # final line avoids copying unrelated JSON or successful command output.
    return [lines[-1].strip()]


def _bound_error_context(lines: Sequence[str]) -> str:
    selected = list(lines)
    truncated = False
    if len(selected) > _MAX_ERROR_CONTEXT_LINES:
        head_count = (_MAX_ERROR_CONTEXT_LINES * 3) // 4
        tail_count = _MAX_ERROR_CONTEXT_LINES - head_count - 1
        selected = [
            *selected[:head_count],
            "... 错误上下文行数过多，已省略中间部分 ...",
            *selected[-tail_count:],
        ]
        truncated = True

    context = "\n".join(selected)
    if len(context) > _MAX_ERROR_CONTEXT_CHARS:
        marker = "\n... 错误上下文过长，已省略中间部分 ...\n"
        available = _MAX_ERROR_CONTEXT_CHARS - len(marker)
        head_count = (available * 3) // 4
        tail_count = available - head_count
        context = f"{context[:head_count]}{marker}{context[-tail_count:]}"
        truncated = True

    if truncated:
        return context.rstrip()
    return context


def _command_error_context(stderr: str, stdout: str) -> str:
    # stderr is authoritative.  Never append stdout when stderr exists: CLI
    # stdout may contain normal JSON payloads that are unrelated to the error.
    lines = _select_error_lines(stderr)
    if not lines:
        lines = _select_error_lines(stdout)
    if not lines:
        return "命令执行失败，未返回错误信息"
    return _bound_error_context(lines)


def _last_error_line(stderr: str, stdout: str) -> str:
    """Return the concise first line of the bounded command diagnostic."""

    return _command_error_context(stderr, stdout).splitlines()[0]


class CliRunner:
    def __init__(
        self,
        config_path: str | Path,
        *,
        python_executable: str | None = None,
    ) -> None:
        self.config_path = Path(config_path).resolve()
        self.python_executable = console_python_executable(python_executable)
        self._processes: dict[subprocess.Popen[str], tuple[str, ...]] = {}
        self._lock = threading.Lock()

    def command(self, *arguments: str) -> tuple[str, ...]:
        return (
            self.python_executable,
            "-m",
            "mumu_autotask",
            "--config",
            str(self.config_path),
            *arguments,
        )

    def run(self, arguments: Sequence[str], *, timeout: float) -> CommandResult:
        command = self.command(*arguments)
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=self.config_path.parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except OSError as exc:
            raise GuiBackendError(f"无法启动 Python 命令：{exc}") from exc
        with self._lock:
            self._processes[process] = command
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                stdout, stderr = process.communicate()
                raise GuiBackendError(f"命令等待超过 {int(timeout)} 秒") from exc
        finally:
            with self._lock:
                self._processes.pop(process, None)
        result = CommandResult(command, process.returncode, stdout, stderr)
        if result.returncode != 0:
            diagnostic = _command_error_context(result.stderr, result.stdout)
            raise GuiBackendError(
                diagnostic.splitlines()[0],
                diagnostic=diagnostic,
            )
        return result

    def run_json_stream(
        self,
        arguments: Sequence[str],
        on_payload: Callable[[Mapping[str, Any]], None],
    ) -> CommandResult:
        command = self.command(*arguments)
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=self.config_path.parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                bufsize=1,
            )
        except OSError as exc:
            raise GuiBackendError(f"无法启动 Python 命令：{exc}") from exc
        with self._lock:
            self._processes[process] = command
        stderr_parts: list[str] = []

        def read_stderr() -> None:
            if process.stderr is None:
                return
            stderr_parts.extend(process.stderr.readlines())

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()
        stdout_parts: list[str] = []
        try:
            if process.stdout is None:
                raise GuiBackendError("后台命令没有可读取的标准输出")
            for line in process.stdout:
                stdout_parts.append(line)
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    process.kill()
                    raise GuiBackendError(
                        f"常驻命令返回了无效 JSON：第 {exc.lineno} 行"
                    ) from exc
                if not isinstance(payload, dict):
                    process.kill()
                    raise GuiBackendError("常驻命令事件必须是 JSON 对象")
                on_payload(payload)
            returncode = process.wait()
        finally:
            stderr_thread.join(timeout=2)
            with self._lock:
                self._processes.pop(process, None)
        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        result = CommandResult(command, returncode, stdout, stderr)
        if returncode != 0:
            diagnostic = _command_error_context(stderr, stdout)
            raise GuiBackendError(
                diagnostic.splitlines()[0],
                diagnostic=diagnostic,
            )
        return result

    def cancel_all(self) -> None:
        with self._lock:
            processes = tuple(self._processes)
        for process in processes:
            if process.poll() is None:
                process.kill()

    def cancel_serial(self, serial: str) -> None:
        with self._lock:
            processes = tuple(
                process
                for process, command in self._processes.items()
                if self._command_targets_serial(command, serial)
            )
        for process in processes:
            if process.poll() is None:
                process.kill()

    @staticmethod
    def _command_targets_serial(command: Sequence[str], serial: str) -> bool:
        for index, value in enumerate(command[:-1]):
            if value == "--serial" and command[index + 1] == serial:
                return True
        return False


class GuiBackend:
    def __init__(
        self,
        runner: CliRunner,
        preferences: GuiPreferences | None = None,
    ) -> None:
        self.runner = runner
        config_path = getattr(runner, "config_path", None)
        self.preferences = preferences or (
            GuiPreferences.for_config(config_path)
            if config_path is not None
            else GuiPreferences(None)
        )

    def get_selected_qualities(self, serial: str) -> tuple[str, ...]:
        return self.preferences.get_selected_qualities(serial)

    def get_category(self, serial: str) -> str:
        return self.preferences.get_category(serial)

    def get_selected_categories(self, serial: str) -> tuple[str, ...]:
        return self.preferences.get_selected_categories(serial)

    def set_category(self, serial: str, category: str) -> None:
        self.preferences.set_category(serial, category)

    def set_selected_categories(
        self,
        serial: str,
        categories: Sequence[str],
    ) -> None:
        self.preferences.set_selected_categories(serial, categories)

    def set_selected_qualities(
        self,
        serial: str,
        qualities: Sequence[str],
    ) -> None:
        self.preferences.set_selected_qualities(serial, qualities)

    def get_concurrency(self, serial: str) -> int:
        return self.preferences.get_concurrency(serial)

    def set_concurrency(self, serial: str, value: int) -> None:
        self.preferences.set_concurrency(serial, value)

    def get_world_monster_level(self, serial: str) -> int:
        return self.preferences.get_world_monster_level(serial)

    def set_world_monster_level(self, serial: str, value: int) -> None:
        self.preferences.set_world_monster_level(serial, value)

    def get_world_monster_concurrency(self, serial: str) -> int:
        return self.preferences.get_world_monster_concurrency(serial)

    def set_world_monster_concurrency(self, serial: str, value: int) -> None:
        self.preferences.set_world_monster_concurrency(serial, value)

    def connect_devices(self) -> str:
        result = self.runner.run(("devices", "--connect"), timeout=30)
        return result.stdout

    def status_all(self) -> tuple[dict[str, Any], ...]:
        result = self.runner.run(("status", "--all"), timeout=45)
        return parse_json_lines(result.stdout)

    def status(self, serial: str) -> Mapping[str, Any]:
        result = self.runner.run(
            ("status", "--serial", serial, "--prepare-frida"),
            timeout=60,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("设备状态命令返回了意外的数据条数")
        return payloads[0]

    def inspect_intel(self, serial: str) -> Mapping[str, Any]:
        result = self.runner.run(
            ("inspect-intel", "--serial", serial, "--execute"),
            timeout=90,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("情报检查命令返回了意外的数据条数")
        return payloads[0]

    def inspect_tasks(self, serial: str) -> Mapping[str, Any]:
        result = self.runner.run(
            ("inspect-tasks", "--serial", serial, "--execute"),
            timeout=90,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("多类别情报检查命令返回了意外的数据条数")
        return payloads[0]

    def _inspect_battle_intel(self, serial: str, category: str) -> Mapping[str, Any]:
        result = self.runner.run(
            (
                "inspect-battle-intel",
                "--serial",
                serial,
                "--category",
                category,
                "--execute",
            ),
            timeout=90,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("战斗情报检查命令返回了意外的数据条数")
        return payloads[0]

    def ensure_world(
        self,
        serial: str,
        *,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        arguments = ["ensure-world", "--serial", serial]
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.append("--execute")
        result = self.runner.run(arguments, timeout=45)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("返回野外命令返回了意外的数据条数")
        return payloads[0]

    def toggle_world(self, serial: str) -> Mapping[str, Any]:
        """Invoke the game's native city/world entrance Button event."""

        result = self.runner.run(
            ("toggle-world", "--serial", serial, "--execute"),
            timeout=45,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("野外/城镇切换命令返回了意外的数据条数")
        return payloads[0]

    def restart_game(self, serial: str) -> Mapping[str, Any]:
        result = self.runner.run(
            ("restart-game", "--serial", serial, "--execute"),
            timeout=45,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("重启游戏命令返回了意外的数据条数")
        return payloads[0]

    def march(
        self,
        serial: str,
        quality: str,
        *,
        runtime_id: int | None = None,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        if (
            runtime_id is not None
            and (
                isinstance(runtime_id, bool)
                or not isinstance(runtime_id, int)
                or runtime_id <= 0
            )
        ):
            raise GuiBackendError("情报目标 ID 必须是正整数")
        arguments = [
            "march",
            "--serial",
            serial,
            "--quality",
            quality,
        ]
        if runtime_id is not None:
            arguments.extend(("--target-id", str(runtime_id)))
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.append("--execute")
        result = self.runner.run(
            arguments,
            timeout=150,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("自动狩猎命令返回了意外的数据条数")
        return payloads[0]

    def battle_intel(
        self,
        serial: str,
        category: str,
        *,
        runtime_id: int | None = None,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        if category not in {"hero", "rescue"}:
            raise GuiBackendError("战斗情报类别必须是 hero 或 rescue")
        if (
            runtime_id is not None
            and (
                isinstance(runtime_id, bool)
                or not isinstance(runtime_id, int)
                or runtime_id <= 0
            )
        ):
            raise GuiBackendError("情报目标 ID 必须是正整数")
        arguments = [
            "battle-intel",
            "--serial",
            serial,
            "--category",
            category,
        ]
        if runtime_id is not None:
            arguments.extend(("--target-id", str(runtime_id)))
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.append("--execute")
        result = self.runner.run(
            arguments,
            timeout=150,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("自动处理战斗情报命令返回了意外的数据条数")
        return payloads[0]

    def batch_intel(
        self,
        serial: str,
        targets: Sequence[Mapping[str, Any]],
        *,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        if isinstance(targets, (str, bytes)) or not targets:
            raise GuiBackendError("批量情报目标必须是非空列表")
        arguments = ["batch-intel", "--serial", serial]
        for target in targets:
            if not isinstance(target, Mapping):
                raise GuiBackendError("批量情报目标必须是对象")
            category = target.get("category", "monster")
            runtime_id = target.get("runtime_id")
            if (
                not isinstance(category, str)
                or isinstance(runtime_id, bool)
                or not isinstance(runtime_id, int)
                or runtime_id <= 0
            ):
                raise GuiBackendError("批量情报目标缺少有效类别或目标 ID")
            normalized_category = category.strip().lower()
            payload = dict(target)
            payload["category"] = normalized_category
            payload["runtime_id"] = runtime_id
            if normalized_category == "monster":
                quality = target.get("quality")
                if not isinstance(quality, str):
                    raise GuiBackendError("野兽批量目标缺少品质")
                payload["quality"] = quality.strip().lower()
                arguments.extend(
                    (
                        "--target-json",
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                )
            elif normalized_category in {"hero", "rescue"}:
                arguments.extend(
                    (
                        "--target-json",
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                )
            else:
                raise GuiBackendError(f"不支持的批量情报类别：{category!r}")
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.append("--execute")
        result = self.runner.run(arguments, timeout=300)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("批量情报命令返回了意外的数据条数")
        return payloads[0]

    def hunt_world_monsters(
        self,
        serial: str,
        level: int,
        count: int,
    ) -> Mapping[str, Any]:
        level = GuiPreferences._validate_world_monster_level(level)
        count = GuiPreferences._validate_world_monster_concurrency(count)
        result = self.runner.run(
            (
                "hunt-world-monster",
                "--serial",
                serial,
                "--level",
                str(level),
                "--count",
                str(count),
                "--execute",
            ),
            timeout=180,
        )
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("搜索野兽出征命令返回了意外的数据条数")
        return payloads[0]

    def world_monster_status(
        self,
        serial: str,
        march_ids: Sequence[int],
    ) -> Mapping[str, Any]:
        ids = _validate_target_ids(march_ids)
        arguments = ["world-monster-status", "--serial", serial]
        for march_id in ids:
            arguments.extend(("--march-id", str(march_id)))
        arguments.append("--execute")
        result = self.runner.run(arguments, timeout=45)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("世界野兽行军状态命令返回了意外的数据条数")
        return payloads[0]

    def world_monster_loop(
        self,
        serial: str,
        level: int,
        concurrency: int,
        on_event: Callable[[Mapping[str, Any]], None],
    ) -> None:
        level = GuiPreferences._validate_world_monster_level(level)
        concurrency = GuiPreferences._validate_world_monster_concurrency(concurrency)
        self.runner.run_json_stream(
            (
                "world-monster-loop",
                "--serial",
                serial,
                "--level",
                str(level),
                "--concurrency",
                str(concurrency),
                "--execute",
            ),
            on_event,
        )

    def wait_intel(
        self,
        serial: str,
        target_ids: Sequence[int],
        *,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        ids = _validate_target_ids(target_ids)
        arguments = ["wait-intel", "--serial", serial]
        for target_id in ids:
            arguments.extend(("--target-id", str(target_id)))
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.append("--execute")
        # The CLI owns the 1800-second guarded poll deadline; leave a full
        # minute for its final PID/Lua-state verification and serialization.
        result = self.runner.run(arguments, timeout=1860)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("情报等待命令返回了意外的数据条数")
        return payloads[0]

    def wait_intel_any(
        self,
        serial: str,
        target_ids: Sequence[int],
        *,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        """Wait for one exact intelligence target, without waiting for all."""

        ids = _validate_target_ids(target_ids)
        arguments = ["wait-intel", "--serial", serial]
        for target_id in ids:
            arguments.extend(("--target-id", str(target_id)))
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.extend(("--return-on-any", "--execute"))
        result = self.runner.run(arguments, timeout=1860)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("情报单项等待命令返回了意外的数据条数")
        return payloads[0]

    def intel_status(
        self,
        serial: str,
        target_ids: Sequence[int],
        *,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        ids = _validate_target_ids(target_ids)
        arguments = ["claim-intel", "--serial", serial]
        for target_id in ids:
            arguments.extend(("--target-id", str(target_id)))
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        result = self.runner.run(arguments, timeout=120)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("情报状态命令返回了意外的数据条数")
        return payloads[0]

    def claim_intel(
        self,
        serial: str,
        target_ids: Sequence[int],
        *,
        expected_role: str | None = None,
    ) -> Mapping[str, Any]:
        ids = _validate_target_ids(target_ids)
        arguments = ["claim-intel", "--serial", serial]
        for target_id in ids:
            arguments.extend(("--target-id", str(target_id)))
        if expected_role is not None:
            arguments.extend(("--expected-role", _validate_expected_role(expected_role)))
        arguments.append("--execute")
        result = self.runner.run(arguments, timeout=180)
        payloads = parse_json_lines(result.stdout)
        if len(payloads) != 1:
            raise GuiBackendError("情报领取命令返回了意外的数据条数")
        return payloads[0]


def _validate_target_ids(target_ids: Sequence[int]) -> tuple[int, ...]:
    if isinstance(target_ids, (str, bytes)):
        raise GuiBackendError("情报目标 ID 必须是列表")
    ids = tuple(target_ids)
    if not ids:
        raise GuiBackendError("情报目标 ID 列表不能为空")
    if any(
        isinstance(target_id, bool)
        or not isinstance(target_id, int)
        or target_id <= 0
        for target_id in ids
    ):
        raise GuiBackendError("情报目标 ID 必须是正整数")
    if len(ids) != len(set(ids)):
        raise GuiBackendError("情报目标 ID 不能重复")
    return ids


def _validate_expected_role(role: str) -> str:
    if not isinstance(role, str) or not role:
        raise GuiBackendError("预期角色不能为空")
    if len(role.encode("utf-8")) > 64:
        raise GuiBackendError("预期角色名称过长")
    if any(ord(char) < 32 or ord(char) == 127 for char in role):
        raise GuiBackendError("预期角色包含控制字符")
    return role


__all__ = [
    "CliRunner",
    "CommandResult",
    "DEFAULT_GUI_CATEGORIES",
    "DEFAULT_GUI_CATEGORY",
    "DEFAULT_GUI_QUALITIES",
    "DEFAULT_HUNT_CONCURRENCY",
    "GUI_CATEGORY_ORDER",
    "GUI_PREFERENCES_FILENAME",
    "GUI_QUALITY_ORDER",
    "GuiBackend",
    "GuiBackendError",
    "GuiPreferences",
    "MAX_HUNT_CONCURRENCY",
    "MIN_HUNT_CONCURRENCY",
    "console_python_executable",
    "parse_json_lines",
]
