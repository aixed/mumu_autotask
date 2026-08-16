from __future__ import annotations

import argparse
from pathlib import Path


MAGIC = b"\x1bLJ"
STRIPPED_FLAG = 0x02


def read_uleb128(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("truncated ULEB128")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def dump_end(data: bytes) -> tuple[int, int]:
    if len(data) < 5 or data[:3] != MAGIC:
        raise ValueError("not a LuaJIT bytecode dump")

    offset = 5
    if not data[4] & STRIPPED_FLAG:
        name_size, offset = read_uleb128(data, offset)
        offset += name_size

    prototypes = 0
    while True:
        prototype_size, offset = read_uleb128(data, offset)
        if prototype_size == 0:
            return offset, prototypes
        end = offset + prototype_size
        if end > len(data):
            raise ValueError("prototype extends past input")
        offset = end
        prototypes += 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trim a carved LuaJIT file at its zero-size dump terminator."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = args.input.read_bytes()
    end, prototypes = dump_end(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data[:end])
    print(
        f"input={len(data)} dump={end} trailing={len(data) - end} "
        f"prototypes={prototypes} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
