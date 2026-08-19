from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import (
    DEFAULT_ACTIVITY_NAME,
    DEFAULT_BRIDGE_REMOTE_PATH,
    DEFAULT_PACKAGE,
    DEFAULT_PROCESS_NAME,
    DeviceProfile,
    Settings,
)


class MumuManagerError(RuntimeError):
    """Raised when MuMu's official manager CLI cannot be queried."""


@dataclass(frozen=True, slots=True)
class MumuInstance:
    index: int
    name: str
    android_version: str
    adb_host_ip: str | None
    adb_port: int | None
    is_android_started: bool
    is_process_started: bool
    player_state: str | None
    pid: int | None
    main_wnd: int | None = None
    render_wnd: int | None = None

    @property
    def running(self) -> bool:
        return self.is_android_started and self.is_process_started

    @property
    def serial(self) -> str | None:
        if not self.adb_host_ip or self.adb_port is None:
            return None
        return f"{self.adb_host_ip}:{self.adb_port}"


def resolve_mumu_manager_executable(settings: Settings) -> str:
    adb_executable = settings.adb.executable
    candidates: list[Path] = []
    if adb_executable:
        candidates.append(Path(adb_executable).expanduser().parent / "MuMuManager.exe")
    candidates.extend(
        [
            Path("D:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe"),
            Path("C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe"),
            Path("C:/Program Files/Netease/MuMu Player 12/shell/MuMuManager.exe"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise MumuManagerError("找不到 MuMuManager.exe，无法动态枚举 MuMu 多开实例")


class MumuManagerClient:
    def __init__(self, executable: str, *, timeout_seconds: float = 10.0) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def _run(self, args: Sequence[str]) -> str:
        command = [self.executable, *args]
        try:
            run_options: dict[str, Any] = {}
            if os.name == "nt":
                # MuMuManager is a console-subsystem executable.  Without
                # CREATE_NO_WINDOW every periodic discovery briefly creates a
                # black console and steals focus from the emulator.
                run_options["creationflags"] = subprocess.CREATE_NO_WINDOW
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                **run_options,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MumuManagerError(
                f"MuMuManager 命令启动失败：{' '.join(command)}：{exc}"
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise MumuManagerError(
                f"MuMuManager 命令返回 {completed.returncode}："
                f"{' '.join(command)}：{detail}"
            )
        return completed.stdout.strip()

    def info_all(self) -> tuple[MumuInstance, ...]:
        output = self._run(("info", "--vmindex", "all"))
        try:
            raw = json.loads(output)
        except json.JSONDecodeError as exc:
            raise MumuManagerError("MuMuManager info 返回的不是 JSON") from exc
        if not isinstance(raw, dict):
            raise MumuManagerError("MuMuManager info 返回结构无效")
        instances: list[MumuInstance] = []
        for raw_index, raw_item in raw.items():
            if not isinstance(raw_item, Mapping):
                continue
            try:
                index = int(str(raw_item.get("index", raw_index)))
            except ValueError:
                continue
            adb_port = raw_item.get("adb_port")
            if isinstance(adb_port, bool) or not isinstance(adb_port, int):
                adb_port = None
            pid = raw_item.get("pid")
            if isinstance(pid, bool) or not isinstance(pid, int):
                pid = None

            def parse_hwnd(value: Any) -> int | None:
                if isinstance(value, bool):
                    return None
                if isinstance(value, int) and value > 0:
                    return value
                if isinstance(value, str) and value.strip():
                    try:
                        return int(value.strip(), 16)
                    except ValueError:
                        return None
                return None

            instances.append(
                MumuInstance(
                    index=index,
                    name=str(raw_item.get("name", f"MuMuPlayer-{index}")),
                    android_version=str(raw_item.get("android_version", "")),
                    adb_host_ip=(
                        str(raw_item["adb_host_ip"])
                        if isinstance(raw_item.get("adb_host_ip"), str)
                        else None
                    ),
                    adb_port=adb_port,
                    is_android_started=raw_item.get("is_android_started") is True,
                    is_process_started=raw_item.get("is_process_started") is True,
                    player_state=(
                        str(raw_item["player_state"])
                        if isinstance(raw_item.get("player_state"), str)
                        else None
                    ),
                    pid=pid,
                    main_wnd=parse_hwnd(raw_item.get("main_wnd")),
                    render_wnd=parse_hwnd(raw_item.get("render_wnd")),
                )
            )
        return tuple(sorted(instances, key=lambda item: item.index))

    def connect_adb(self, indexes: Sequence[int]) -> None:
        if not indexes:
            return
        selected = ",".join(str(index) for index in sorted(set(indexes)))
        self._run(("adb", "--vmindex", selected, "--cmd", "connect"))


def _configured_profile_by_serial(settings: Settings) -> dict[str, DeviceProfile]:
    return {profile.serial: profile for profile in settings.devices}


def _profile_from_instance(
    instance: MumuInstance,
    configured: Mapping[str, DeviceProfile],
) -> DeviceProfile | None:
    serial = instance.serial
    if serial is None:
        return None
    base = configured.get(serial)
    adb_port = int(serial.rpartition(":")[2])
    frida_local_port = adb_port + 10000
    return DeviceProfile(
        serial=serial,
        frida_host=f"127.0.0.1:{frida_local_port}",
        frida_remote_port=base.frida_remote_port if base else 27042,
        bridge_remote_path=(
            base.bridge_remote_path if base else DEFAULT_BRIDGE_REMOTE_PATH
        ),
        expected_kingdom=base.expected_kingdom if base else 1,
        package_name=base.package_name if base else DEFAULT_PACKAGE,
        process_name=base.process_name if base else DEFAULT_PROCESS_NAME,
        activity_name=base.activity_name if base else DEFAULT_ACTIVITY_NAME,
        playerprefs_path=base.playerprefs_path if base else None,
        instance_name=f"#{instance.index} {instance.name}".strip(),
        roles=(),
        mumu_hwnd=instance.main_wnd,
        mumu_pid=instance.pid,
        base_url=base.base_url if base else None,
        headers=base.headers if base else {},
    )


def discover_running_mumu_profiles(
    settings: Settings,
    *,
    connect_adb: bool = True,
) -> tuple[DeviceProfile, ...]:
    manager = MumuManagerClient(
        resolve_mumu_manager_executable(settings),
        timeout_seconds=max(5.0, settings.adb.command_timeout_seconds),
    )
    instances = manager.info_all()
    running = [instance for instance in instances if instance.running and instance.serial]
    if connect_adb:
        manager.connect_adb([instance.index for instance in running])
    configured = _configured_profile_by_serial(settings)
    profiles = [
        profile
        for instance in running
        if (profile := _profile_from_instance(instance, configured)) is not None
    ]
    return tuple(profiles)


def discover_profile_for_serial(settings: Settings, serial: str) -> DeviceProfile:
    for profile in discover_running_mumu_profiles(settings, connect_adb=True):
        if profile.serial == serial:
            return profile
    raise MumuManagerError(f"当前运行的 MuMu 实例中没有 ADB 设备 {serial!r}")
