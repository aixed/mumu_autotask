from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when configuration is missing or unsafe."""


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ANDROID_PACKAGE_PATTERN = re.compile(r"[A-Za-z0-9_.]+\Z")
_ANDROID_ACTIVITY_PATTERN = re.compile(r"[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+\Z")
_DEVICE_PATH_PATTERN = re.compile(r"/[A-Za-z0-9._/:+-]+\Z")
ALLOWED_KINGDOM = 4549
DEFAULT_PACKAGE = "com.gof.global"
DEFAULT_PROCESS_NAME = "Whiteout Survival"
DEFAULT_ACTIVITY_NAME = "com.gof.global/com.unity3d.player.MyMainPlayerActivity"
DEFAULT_BRIDGE_REMOTE_PATH = "/data/local/tmp/libmumu_bridge.so"


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"environment variable {name!r} is not set")
            return os.environ[name]

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{location} must be an object")
    return value


def _string(value: Any, location: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{location} must be a non-empty string")
    return value


def _positive_number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{location} must be a positive number")
    return float(value)


def _positive_integer(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{location} must be a positive integer")
    return value


def _tcp_port(value: Any, location: str) -> int:
    port = _positive_integer(value, location)
    if port > 65535:
        raise ConfigError(f"{location} must be between 1 and 65535")
    return port


def _frida_host(value: Any, location: str) -> str:
    host = _string(value, location)
    name, separator, raw_port = host.rpartition(":")
    if not separator or not name or not raw_port.isdecimal():
        raise ConfigError(f"{location} must have the form HOST:PORT")
    _tcp_port(int(raw_port), f"{location} port")
    return host


def _string_map(value: Any, location: str) -> dict[str, str]:
    raw = _mapping(value, location)
    result: dict[str, str] = {}
    for key, item in raw.items():
        result[_string(key, f"{location} key")] = _string(
            item, f"{location}.{key}", allow_empty=True
        )
    return result


def _string_tuple(value: Any, location: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{location} must be an array")
    return tuple(
        _string(item, f"{location}[{index}]")
        for index, item in enumerate(value)
    )


@dataclass(frozen=True, slots=True)
class AdbSettings:
    executable: str | None = None
    connect_targets: tuple[str, ...] = ()
    command_timeout_seconds: float = 10.0

    @classmethod
    def from_dict(cls, value: Any) -> "AdbSettings":
        raw = _mapping(value, "adb")
        executable = raw.get("executable")
        if executable is not None:
            executable = _string(executable, "adb.executable")
        targets_raw = raw.get("connect_targets", [])
        if not isinstance(targets_raw, list):
            raise ConfigError("adb.connect_targets must be an array")
        targets = tuple(
            _string(item, f"adb.connect_targets[{index}]")
            for index, item in enumerate(targets_raw)
        )
        timeout = _positive_number(
            raw.get("command_timeout_seconds", 10),
            "adb.command_timeout_seconds",
        )
        return cls(executable, targets, timeout)


@dataclass(frozen=True, slots=True)
class HttpSettings:
    timeout_seconds: float = 15.0
    verify_tls: bool = True
    user_agent: str = "mumu-autotask/0.1"

    @classmethod
    def from_dict(cls, value: Any) -> "HttpSettings":
        raw = _mapping(value, "http")
        verify_tls = raw.get("verify_tls", True)
        if not isinstance(verify_tls, bool):
            raise ConfigError("http.verify_tls must be a boolean")
        return cls(
            timeout_seconds=_positive_number(
                raw.get("timeout_seconds", 15), "http.timeout_seconds"
            ),
            verify_tls=verify_tls,
            user_agent=_string(
                raw.get("user_agent", "mumu-autotask/0.1"), "http.user_agent"
            ),
        )


@dataclass(frozen=True, slots=True)
class FridaSettings:
    output_capacity: int = 16384

    @classmethod
    def from_dict(cls, value: Any) -> "FridaSettings":
        raw = _mapping(value, "frida")
        output_capacity = _positive_integer(
            raw.get("output_capacity", 16384), "frida.output_capacity"
        )
        if not 2 <= output_capacity <= 16384:
            raise ConfigError(
                "frida.output_capacity must be between 2 and 16384"
            )
        return cls(output_capacity=output_capacity)


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    serial: str
    # These two fields preserve the old direct-construction signature for
    # capture-analysis callers. They are not part of the CLI execution path.
    base_url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    frida_host: str = "127.0.0.1:27042"
    frida_remote_port: int = 27042
    bridge_remote_path: str = DEFAULT_BRIDGE_REMOTE_PATH
    expected_kingdom: int = ALLOWED_KINGDOM
    package_name: str = DEFAULT_PACKAGE
    process_name: str = DEFAULT_PROCESS_NAME
    activity_name: str = DEFAULT_ACTIVITY_NAME
    pid: int | None = None
    playerprefs_path: str | None = None
    instance_name: str | None = None
    roles: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Any, index: int) -> "DeviceProfile":
        location = f"devices[{index}]"
        raw = _mapping(value, location)
        serial = _string(raw.get("serial"), f"{location}.serial")
        frida_host = _frida_host(
            raw.get("frida_host", "127.0.0.1:27042"),
            f"{location}.frida_host",
        )
        frida_remote_port = _tcp_port(
            raw.get("frida_remote_port", 27042),
            f"{location}.frida_remote_port",
        )
        expected_kingdom = raw.get("expected_kingdom", ALLOWED_KINGDOM)
        if (
            isinstance(expected_kingdom, bool)
            or not isinstance(expected_kingdom, int)
            or expected_kingdom != ALLOWED_KINGDOM
        ):
            raise ConfigError(
                f"{location}.expected_kingdom must be {ALLOWED_KINGDOM}; "
                "other kingdoms are blocked"
            )
        package_name = _string(
            raw.get("package_name", DEFAULT_PACKAGE), f"{location}.package_name"
        )
        if not _ANDROID_PACKAGE_PATTERN.fullmatch(package_name):
            raise ConfigError(f"{location}.package_name is not an Android package name")
        canonical_playerprefs_path = (
            f"/data/data/{package_name}/shared_prefs/"
            f"{package_name}.v2.playerprefs.xml"
        )
        playerprefs_path = raw.get("playerprefs_path")
        if playerprefs_path is not None:
            playerprefs_path = _string(
                playerprefs_path, f"{location}.playerprefs_path"
            )
            if not _DEVICE_PATH_PATTERN.fullmatch(playerprefs_path):
                raise ConfigError(
                    f"{location}.playerprefs_path must be a safe absolute device path"
                )
            if playerprefs_path != canonical_playerprefs_path:
                raise ConfigError(
                    f"{location}.playerprefs_path must be the canonical Unity "
                    "PlayerPrefs path"
                )
        pid = raw.get("pid")
        if pid is not None:
            pid = _positive_integer(pid, f"{location}.pid")
        activity_name = _string(
            raw.get("activity_name", DEFAULT_ACTIVITY_NAME),
            f"{location}.activity_name",
        )
        if not _ANDROID_ACTIVITY_PATTERN.fullmatch(activity_name):
            raise ConfigError(f"{location}.activity_name is not a safe component name")
        instance_name = raw.get("instance_name")
        if instance_name is not None:
            instance_name = _string(instance_name, f"{location}.instance_name")

        base_url = raw.get("base_url")
        if base_url is not None:
            base_url = _string(base_url, f"{location}.base_url").rstrip("/")
            parts = urlsplit(base_url)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise ConfigError(f"{location}.base_url must be an http(s) URL")
            if parts.query or parts.fragment:
                raise ConfigError(
                    f"{location}.base_url cannot contain query or fragment"
                )
        bridge_remote_path = _string(
            raw.get("bridge_remote_path", DEFAULT_BRIDGE_REMOTE_PATH),
            f"{location}.bridge_remote_path",
        )
        if not _DEVICE_PATH_PATTERN.fullmatch(bridge_remote_path):
            raise ConfigError(
                f"{location}.bridge_remote_path must be a safe absolute device path"
            )
        return cls(
            serial=serial,
            frida_host=frida_host,
            frida_remote_port=frida_remote_port,
            bridge_remote_path=bridge_remote_path,
            expected_kingdom=ALLOWED_KINGDOM,
            package_name=package_name,
            process_name=_string(
                raw.get("process_name", DEFAULT_PROCESS_NAME),
                f"{location}.process_name",
            ),
            activity_name=activity_name,
            pid=pid,
            playerprefs_path=playerprefs_path,
            instance_name=instance_name,
            roles=_string_tuple(raw.get("roles", []), f"{location}.roles"),
            base_url=base_url,
            headers=_string_map(raw.get("headers", {}), f"{location}.headers"),
        )

    @property
    def resolved_playerprefs_path(self) -> str:
        canonical = (
            f"/data/data/{self.package_name}/shared_prefs/"
            f"{self.package_name}.v2.playerprefs.xml"
        )
        return self.playerprefs_path or canonical

    @property
    def frida_local_port(self) -> int:
        return int(self.frida_host.rpartition(":")[2])


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, Any] = field(default_factory=dict)
    json_body: Any | None = None
    form_body: Mapping[str, Any] | None = None
    expected_status: tuple[int, ...] = (200,)
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: Any, name: str) -> "EndpointSpec":
        location = f"endpoints.{name}"
        raw = _mapping(value, location)
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{location}.enabled must be a boolean")
        path = _string(raw.get("path", ""), f"{location}.path", allow_empty=not enabled)
        parsed_path = urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc:
            raise ConfigError(f"{location}.path must be relative to the configured base_url")
        method = _string(raw.get("method", "POST"), f"{location}.method").upper()
        json_body = raw.get("json")
        form_body = raw.get("form")
        if json_body is not None and form_body is not None:
            raise ConfigError(f"{location} cannot define both json and form")
        if form_body is not None:
            form_body = dict(_mapping(form_body, f"{location}.form"))
        query = dict(_mapping(raw.get("query", {}), f"{location}.query"))
        status_raw = raw.get("expected_status", [200])
        if not isinstance(status_raw, list) or not status_raw:
            raise ConfigError(f"{location}.expected_status must be a non-empty array")
        statuses: list[int] = []
        for index, status in enumerate(status_raw):
            if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                raise ConfigError(
                    f"{location}.expected_status[{index}] must be an HTTP status"
                )
            statuses.append(status)
        return cls(
            method=method,
            path=path,
            headers=_string_map(raw.get("headers", {}), f"{location}.headers"),
            query=query,
            json_body=json_body,
            form_body=form_body,
            expected_status=tuple(statuses),
            enabled=enabled,
        )


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    action: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    extract: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any, workflow: str, index: int) -> "WorkflowStep":
        location = f"workflows.{workflow}.steps[{index}]"
        raw = _mapping(value, location)
        return cls(
            action=_string(raw.get("action"), f"{location}.action"),
            inputs=dict(_mapping(raw.get("inputs", {}), f"{location}.inputs")),
            extract=_string_map(raw.get("extract", {}), f"{location}.extract"),
        )


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    steps: tuple[WorkflowStep, ...]

    @classmethod
    def from_dict(cls, value: Any, name: str) -> "WorkflowSpec":
        location = f"workflows.{name}"
        raw = _mapping(value, location)
        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ConfigError(f"{location}.steps must be a non-empty array")
        return cls(
            tuple(
                WorkflowStep.from_dict(step, name, index)
                for index, step in enumerate(steps_raw)
            )
        )


@dataclass(frozen=True, slots=True)
class Settings:
    adb: AdbSettings = field(default_factory=AdbSettings)
    http: HttpSettings = field(default_factory=HttpSettings)
    devices: tuple[DeviceProfile, ...] = ()
    endpoints: Mapping[str, EndpointSpec] = field(default_factory=dict)
    workflows: Mapping[str, WorkflowSpec] = field(default_factory=dict)
    frida: FridaSettings = field(default_factory=FridaSettings)

    @classmethod
    def from_dict(cls, value: Any) -> "Settings":
        raw = _mapping(value, "root")
        devices_raw = raw.get("devices", [])
        if not isinstance(devices_raw, list):
            raise ConfigError("devices must be an array")
        devices = tuple(
            DeviceProfile.from_dict(item, index)
            for index, item in enumerate(devices_raw)
        )
        serials = [device.serial for device in devices]
        if len(serials) != len(set(serials)):
            raise ConfigError("device serials must be unique")
        frida_hosts = [device.frida_host for device in devices]
        if len(frida_hosts) != len(set(frida_hosts)):
            raise ConfigError("device Frida hosts must be unique")
        configured_roles = [role for device in devices for role in device.roles]
        if len(configured_roles) != len(set(configured_roles)):
            raise ConfigError("device roles must be unique across device profiles")

        endpoints_raw = _mapping(raw.get("endpoints", {}), "endpoints")
        endpoints = {
            _string(name, "endpoint name"): EndpointSpec.from_dict(spec, name)
            for name, spec in endpoints_raw.items()
        }
        workflows_raw = _mapping(raw.get("workflows", {}), "workflows")
        workflows = {
            _string(name, "workflow name"): WorkflowSpec.from_dict(spec, name)
            for name, spec in workflows_raw.items()
        }
        for workflow_name, workflow in workflows.items():
            for step in workflow.steps:
                if step.action not in endpoints:
                    raise ConfigError(
                        f"workflow {workflow_name!r} references unknown endpoint "
                        f"{step.action!r}"
                    )
        return cls(
            adb=AdbSettings.from_dict(raw.get("adb", {})),
            frida=FridaSettings.from_dict(raw.get("frida", {})),
            http=HttpSettings.from_dict(raw.get("http", {})),
            devices=devices,
            endpoints=endpoints,
            workflows=workflows,
        )

    def device(self, serial: str) -> DeviceProfile:
        for profile in self.devices:
            if profile.serial == serial:
                return profile
        raise ConfigError(f"no device profile is configured for ADB serial {serial!r}")


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read configuration {config_path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"invalid JSON in {config_path} at line {exc.lineno}, column {exc.colno}"
        ) from exc
    return Settings.from_dict(_expand_environment(raw))
