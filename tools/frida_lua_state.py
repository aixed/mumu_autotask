from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida


def main() -> int:
    parser = argparse.ArgumentParser(description="Locate live LuaJIT states")
    parser.add_argument("--host", default="127.0.0.1:27042")
    parser.add_argument("--process", default="Whiteout Survival")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--validate")
    parser.add_argument(
        "--script",
        type=Path,
        default=Path(__file__).with_name("frida_lua_state.js"),
    )
    args = parser.parse_args()

    device = frida.get_device_manager().add_remote_device(args.host)
    pid = args.pid
    if pid is None:
        matches = [
            process
            for process in device.enumerate_processes()
            if process.name == args.process
        ]
        if len(matches) != 1:
            found = ", ".join(f"{item.pid}:{item.name}" for item in matches)
            raise RuntimeError(f"expected one game process, found {found or 'none'}")
        pid = matches[0].pid

    session = device.attach(pid)
    try:
        script = session.create_script(args.script.read_text(encoding="utf-8"))
        script.load()
        if args.validate:
            result = script.exports_sync.validate_lua_state(args.validate)
        else:
            result = script.exports_sync.find_lua_states()
        print(json.dumps(result, indent=2))
    finally:
        session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
