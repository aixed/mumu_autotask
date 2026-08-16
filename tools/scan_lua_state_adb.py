from __future__ import annotations

import argparse
import re
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Mapping:
    start: int
    end: int
    permissions: str
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start

    def contains(self, address: int, size: int = 1) -> bool:
        return self.start <= address and address + size <= self.end


MAP_PATTERN = re.compile(
    r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)$"
)


def adb_command(adb: Path, serial: str, *arguments: str) -> list[str]:
    return [str(adb), "-s", serial, *arguments]


def get_pid(adb: Path, serial: str) -> int:
    result = subprocess.run(
        adb_command(adb, serial, "shell", "pidof", "com.gof.global"),
        check=True,
        capture_output=True,
        text=True,
    )
    values = result.stdout.split()
    if len(values) != 1:
        raise RuntimeError(f"expected one game pid, found {values!r}")
    return int(values[0])


def get_maps(adb: Path, serial: str, pid: int) -> list[Mapping]:
    result = subprocess.run(
        adb_command(adb, serial, "shell", "su", "0", "cat", f"/proc/{pid}/maps"),
        check=True,
        capture_output=True,
        text=True,
    )
    mappings: list[Mapping] = []
    for line in result.stdout.splitlines():
        match = MAP_PATTERN.match(line)
        if match:
            mappings.append(
                Mapping(
                    int(match.group(1), 16),
                    int(match.group(2), 16),
                    match.group(3),
                    match.group(4),
                )
            )
    return mappings


def read_mapping(adb: Path, serial: str, pid: int, mapping: Mapping) -> bytes:
    command = adb_command(
        adb,
        serial,
        "exec-out",
        "su",
        "0",
        "dd",
        f"if=/proc/{pid}/mem",
        "iflag=skip_bytes,count_bytes",
        f"skip={mapping.start}",
        f"count={mapping.size}",
        "status=none",
    )
    result = subprocess.run(command, check=True, capture_output=True)
    if len(result.stdout) != mapping.size:
        raise RuntimeError(
            f"short read for {mapping.start:#x}-{mapping.end:#x}: "
            f"expected {mapping.size}, got {len(result.stdout)}; "
            f"stderr={result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def containing_mapping(
    mappings: list[Mapping], address: int, size: int = 1
) -> Mapping | None:
    return next((mapping for mapping in mappings if mapping.contains(address, size)), None)


def validate_candidate(
    mapping: Mapping,
    data: bytes,
    offset: int,
    mappings: list[Mapping],
) -> dict[str, int | str | bool] | None:
    if offset < 0 or offset + 0x60 > len(data):
        return None
    address = mapping.start + offset
    marked, gct, dummy_ffid, status = struct.unpack_from("4B", data, offset + 8)
    if gct != 6 or dummy_ffid != 1 or status > 14:
        return None

    glref = struct.unpack_from("<Q", data, offset + 0x10)[0]
    base = struct.unpack_from("<Q", data, offset + 0x20)[0]
    top = struct.unpack_from("<Q", data, offset + 0x28)[0]
    maxstack = struct.unpack_from("<Q", data, offset + 0x30)[0]
    stack = struct.unpack_from("<Q", data, offset + 0x38)[0]
    openupval = struct.unpack_from("<Q", data, offset + 0x40)[0]
    env = struct.unpack_from("<Q", data, offset + 0x48)[0]
    cframe = struct.unpack_from("<Q", data, offset + 0x50)[0]
    stacksize = struct.unpack_from("<I", data, offset + 0x58)[0]

    pointers = (glref, base, top, maxstack, stack, env)
    if any(pointer & 7 for pointer in pointers):
        return None
    if not (stack <= base <= top <= maxstack):
        return None
    if not 32 <= stacksize <= 1_000_000:
        return None
    stack_bytes = maxstack - stack
    if stack_bytes > stacksize * 8 or stack_bytes + 128 < stacksize * 8:
        return None
    for pointer, size in (
        (glref, 0xC8),
        (stack, 8),
        (maxstack - 1, 1),
        (env, 16),
    ):
        target = containing_mapping(mappings, pointer, size)
        if target is None or not target.permissions.startswith("r"):
            return None

    if not mapping.contains(glref + 0xC0, 8):
        return None
    main_thread = struct.unpack_from(
        "<Q", data, glref + 0xC0 - mapping.start
    )[0]
    if not mapping.contains(main_thread, 0x60):
        return None
    main_offset = main_thread - mapping.start
    if data[main_offset + 9] != 6:
        return None
    main_glref = struct.unpack_from("<Q", data, main_offset + 0x10)[0]
    if main_glref != glref:
        return None

    if mapping.contains(env, 16) and data[env - mapping.start + 9] != 11:
        return None

    return {
        "address": f"0x{address:x}",
        "marked": marked,
        "status": status,
        "glref": f"0x{glref:x}",
        "base": f"0x{base:x}",
        "top": f"0x{top:x}",
        "maxstack": f"0x{maxstack:x}",
        "stack": f"0x{stack:x}",
        "openupval": f"0x{openupval:x}",
        "env": f"0x{env:x}",
        "cframe": f"0x{cframe:x}",
        "stacksize": stacksize,
        "main_thread": f"0x{main_thread:x}",
        "is_main": address == main_thread,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Find live LuaJIT states over root ADB")
    parser.add_argument("--serial", default="127.0.0.1:16416")
    parser.add_argument(
        "--adb",
        type=Path,
        default=Path(r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"),
    )
    parser.add_argument("--range", action="append", default=[])
    parser.add_argument("--anonymous-only", action="store_true")
    parser.add_argument("--min-size", type=lambda value: int(value, 0), default=0x1000)
    parser.add_argument("--max-size", type=lambda value: int(value, 0), default=256 << 20)
    parser.add_argument("--address-ceiling", type=lambda value: int(value, 0))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    pid = get_pid(args.adb, args.serial)
    mappings = get_maps(args.adb, args.serial, pid)
    requested = {
        (int(value.split(":", 1)[0], 0), int(value.split(":", 1)[1], 0))
        for value in args.range
    }
    selected = [
        mapping
        for mapping in mappings
        if mapping.permissions.startswith("rw")
        and args.min_size <= mapping.size <= args.max_size
        and (args.address_ceiling is None or mapping.end <= args.address_ceiling)
        and "dalvik" not in mapping.path
        and "memfd:" not in mapping.path
        and mapping.path != "/dev/vaddress"
        and "gralloc-buffer" not in mapping.path
        and (not args.anonymous_only or not mapping.path)
        and (not requested or (mapping.start, mapping.size) in requested)
    ]

    found: dict[str, dict[str, int | str | bool]] = {}
    for mapping in selected:
        if not args.quiet:
            print(
                f"scan 0x{mapping.start:x}-0x{mapping.end:x} "
                f"({mapping.size:,} bytes) {mapping.path}",
                flush=True,
            )
        try:
            data = read_mapping(args.adb, args.serial, pid, mapping)
        except (RuntimeError, subprocess.CalledProcessError) as error:
            if not args.quiet:
                print(f"skip unreadable mapping: {error}", flush=True)
            continue
        cursor = 0
        while True:
            marker = data.find(b"\x06\x01", cursor)
            if marker < 0:
                break
            candidate = validate_candidate(mapping, data, marker - 9, mappings)
            if candidate is not None:
                found[str(candidate["address"])] = candidate
            cursor = marker + 1

    print("candidates:")
    for candidate in found.values():
        print(candidate)
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
