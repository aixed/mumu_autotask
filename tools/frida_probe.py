from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a MuMu game process through Frida")
    parser.add_argument("--host", default="127.0.0.1:27042")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--process", default="Whiteout Survival")
    parser.add_argument("--library")
    parser.add_argument("--symbol")
    parser.add_argument("--shorty", action="append", default=[])
    parser.add_argument("--bridge-module", default="libhoudini.so")
    parser.add_argument("--invoke", action="store_true")
    parser.add_argument(
        "--script",
        type=Path,
        default=Path(__file__).with_name("frida_probe.js"),
    )
    parser.add_argument(
        "command", choices=("native-bridge", "modules", "trampoline")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    device = frida.get_device_manager().add_remote_device(args.host)
    process = args.pid
    if process is None:
        matches = [item for item in device.enumerate_processes() if item.name == args.process]
        if len(matches) != 1:
            names = ", ".join(f"{item.pid}:{item.name}" for item in matches) or "none"
            raise RuntimeError(
                f"expected one process named {args.process!r}, found {names}"
            )
        process = matches[0].pid

    session = device.attach(process)
    try:
        script = session.create_script(args.script.read_text(encoding="utf-8"))
        script.load()
        if args.command == "native-bridge":
            result = script.exports_sync.native_bridge()
        elif args.command == "trampoline":
            if not args.library or not args.symbol:
                raise RuntimeError("trampoline requires --library and --symbol")
            result = script.exports_sync.trampoline_probe(
                args.bridge_module,
                args.library,
                args.symbol,
                args.shorty,
                args.invoke,
            )
        else:
            result = script.exports_sync.modules()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
