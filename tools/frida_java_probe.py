from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect loaded Unity Java classes")
    parser.add_argument("--host", default="127.0.0.1:27042")
    parser.add_argument("--process", default="Whiteout Survival")
    parser.add_argument(
        "--script",
        type=Path,
        default=Path(__file__).with_name("frida_java_probe.js"),
    )
    args = parser.parse_args()

    device = frida.get_device_manager().add_remote_device(args.host)
    matches = [item for item in device.enumerate_processes() if item.name == args.process]
    if len(matches) != 1:
        found = ", ".join(f"{item.pid}:{item.name}" for item in matches) or "none"
        raise RuntimeError(f"expected one {args.process!r} process, found {found}")

    session = device.attach(matches[0].pid)
    try:
        script = session.create_script(args.script.read_text(encoding="utf-8"))
        script.load()
        print(json.dumps(script.exports_sync.inspect(), ensure_ascii=False, indent=2))
    finally:
        session.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
