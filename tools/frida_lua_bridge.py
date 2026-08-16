from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import frida


DEFAULT_ADB = Path(r"D:\Program Files\Netease\MuMu\nx_main\adb.exe")
DEFAULT_CODE = "return tostring(_VERSION)"


def adb_command(adb: Path, serial: str, *arguments: str) -> list[str]:
    return [str(adb), "-s", serial, *arguments]


def run_adb(adb: Path, serial: str, *arguments: str) -> str:
    result = subprocess.run(
        adb_command(adb, serial, *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def game_pid(adb: Path, serial: str, package: str) -> int:
    values = run_adb(adb, serial, "shell", "pidof", package).split()
    if len(values) != 1:
        raise RuntimeError(f"expected one {package} pid, found {values!r}")
    return int(values[0])


def emit(stage: str, value: Any) -> None:
    print(json.dumps({"stage": stage, "value": value}, ensure_ascii=False), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load the ARM64 MuMu JNI bridge and execute Lua on its main thread"
    )
    parser.add_argument("--host", default="127.0.0.1:27042")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--process", default="Whiteout Survival")
    parser.add_argument("--library", default="/data/local/tmp/libmumu_bridge.so")
    parser.add_argument("--code", default=DEFAULT_CODE)
    parser.add_argument("--initialize-only", action="store_true")
    parser.add_argument("--direct-state")
    parser.add_argument("--unsafe-inline-hook", action="store_true")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    parser.add_argument("--manage-activity", action="store_true")
    parser.add_argument("--serial", default="127.0.0.1:16384")
    parser.add_argument("--adb", type=Path, default=DEFAULT_ADB)
    parser.add_argument("--package", default="com.gof.global")
    parser.add_argument(
        "--activity",
        default="com.gof.global/com.unity3d.player.MyMainPlayerActivity",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=Path(__file__).with_name("frida_lua_bridge.js"),
    )
    return parser.parse_args()


def resolve_pid(device: frida.core.Device, pid: int | None, process_name: str) -> int:
    if pid is not None:
        return pid
    matches = [item for item in device.enumerate_processes() if item.name == process_name]
    if len(matches) != 1:
        found = ", ".join(f"{item.pid}:{item.name}" for item in matches) or "none"
        raise RuntimeError(f"expected one process named {process_name!r}, found {found}")
    return matches[0].pid


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.poll_interval <= 0:
        raise ValueError("timeout and poll interval must be positive")
    if args.direct_state and not args.manage_activity:
        raise ValueError("direct execution requires --manage-activity")
    if not args.direct_state and not args.initialize_only and not args.unsafe_inline_hook:
        raise ValueError(
            "inline hook is disabled by default; use --direct-state or --initialize-only"
        )

    adb_pid = None
    backgrounded = False
    if args.manage_activity:
        adb_pid = game_pid(args.adb, args.serial, args.package)
        if args.pid is not None and args.pid != adb_pid:
            raise RuntimeError(f"Frida pid {args.pid} does not match ADB pid {adb_pid}")
        run_adb(args.adb, args.serial, "shell", "input", "keyevent", "KEYCODE_HOME")
        backgrounded = True
        time.sleep(0.75)
        if game_pid(args.adb, args.serial, args.package) != adb_pid:
            raise RuntimeError("game pid changed while moving it to the background")
        emit("backgrounded", {"pid": adb_pid, "serial": args.serial})

    session = None
    try:
        device = frida.get_device_manager().add_remote_device(args.host)
        pid = resolve_pid(device, args.pid or adb_pid, args.process)
        session = device.attach(pid)
        script = session.create_script(args.script.read_text(encoding="utf-8"))
        script.load()
        bridge = script.exports_sync
        emit("initialize", bridge.initialize(args.library))
        if args.initialize_only:
            return 0
        if args.direct_state:
            result = bridge.execute(args.direct_state, args.code, 16384)
            emit("execute", result)
            return 0 if result.get("ok") else 2
        installed = bridge.install()
        emit("install", installed)
        if installed != 1:
            raise RuntimeError(f"bridge rejected inline hook installation: {installed}")

        if args.manage_activity:
            run_adb(args.adb, args.serial, "shell", "am", "start", "-n", args.activity)
            backgrounded = False
            emit("foregrounded", {"activity": args.activity})

        deadline = time.monotonic() + args.timeout
        state = "0x0"
        while time.monotonic() < deadline:
            state = bridge.state()
            if state != "0x0":
                break
            time.sleep(args.poll_interval)
        if state == "0x0":
            raise TimeoutError("bridge did not observe a Lua state before the timeout")
        emit("state", state)

        submitted = bridge.submit(args.code)
        emit("submit", submitted)
        if submitted != 1:
            raise RuntimeError(f"bridge rejected Lua request with status {submitted}")

        while time.monotonic() < deadline:
            result = bridge.poll(16384)
            if not result.get("pending"):
                emit("poll", result)
                if result.get("idle") or not result.get("ok"):
                    return 2
                return 0
            time.sleep(args.poll_interval)
        raise TimeoutError("Lua request did not complete before the timeout")
    finally:
        if session is not None:
            session.detach()
        if backgrounded:
            run_adb(args.adb, args.serial, "shell", "am", "start", "-n", args.activity)


if __name__ == "__main__":
    raise SystemExit(main())
