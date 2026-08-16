from __future__ import annotations

import argparse
from pathlib import Path


SIGNATURE = b"\x1bLJ\x02"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carve stripped LuaJIT dumps from an offline binary container."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--contains",
        action="append",
        default=[],
        help="only emit chunks whose source span contains this ASCII text",
    )
    args = parser.parse_args()

    data = args.source.read_bytes()
    starts: list[int] = []
    cursor = 0
    while True:
        cursor = data.find(SIGNATURE, cursor)
        if cursor < 0:
            break
        starts.append(cursor)
        cursor += len(SIGNATURE)

    needles = [value.encode("ascii") for value in args.contains]
    args.output.mkdir(parents=True, exist_ok=True)
    emitted = 0
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(data)
        span = data[start:end]
        if needles and not any(needle in span for needle in needles):
            continue
        path = args.output / f"chunk_{index:04d}_{start:08x}.ljbc"
        path.write_bytes(span)
        print(f"{path}\t{len(span)}")
        emitted += 1
    print(f"found={len(starts)} emitted={emitted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
