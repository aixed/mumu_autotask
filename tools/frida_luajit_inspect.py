from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from mumu_autotask.adb import AdbClient
from mumu_autotask.config import load_settings
from mumu_autotask.lua_state import AdbLuaStateScanner


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect live LuaJIT tables without executing Lua code"
    )
    parser.add_argument("--config", default="config.example.json")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--state", type=lambda value: int(value, 0))
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--filter", default="")
    parser.add_argument("--show-values", action="store_true")
    parser.add_argument(
        "--script",
        type=Path,
        default=Path(__file__).with_suffix(".js"),
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    profile = settings.device(args.serial)
    adb = AdbClient(
        settings.adb.executable,
        timeout_seconds=settings.adb.command_timeout_seconds,
    )
    pid = adb.pidof(profile.serial, profile.package_name)
    state = args.state
    if state is None:
        state = AdbLuaStateScanner(adb, profile.serial).find_unique_idle_main(pid).address

    device = frida.get_device_manager().add_remote_device(profile.frida_host)
    process_matches = [
        process
        for process in device.enumerate_processes()
        if process.pid == pid and process.name == profile.process_name
    ]
    if len(process_matches) != 1:
        raise RuntimeError(
            f"ADB PID {pid} is not the unique {profile.process_name!r} Frida process"
        )

    session = device.attach(pid)
    try:
        script = session.create_script(args.script.read_text(encoding="utf-8"))
        script.load()
        result = script.exports_sync.inspect(
            f"0x{state:x}", args.path, args.filter, args.show_values
        )
    finally:
        session.detach()

    final_pid = adb.pidof(profile.serial, profile.package_name)
    if final_pid != pid:
        raise RuntimeError(f"game PID changed during inspection: {pid} -> {final_pid}")
    print(
        json.dumps(
            {"serial": profile.serial, "pid": pid, "state": f"0x{state:x}", **result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
