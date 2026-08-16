from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path


GC64_POINTER_MASK = (1 << 47) - 1
LUAJIT_TYPE_NAMES = {
    -1: "nil",
    -2: "false",
    -3: "true",
    -4: "lightuserdata",
    -5: "string",
    -6: "upvalue",
    -7: "thread",
    -8: "prototype",
    -9: "function",
    -10: "trace",
    -11: "cdata",
    -12: "table",
    -13: "userdata",
    -14: "integer",
}


@dataclass(frozen=True, slots=True)
class TableEntry:
    key: str
    value_type: str
    value_address: int | None
    value_raw: int


@dataclass(frozen=True, slots=True)
class Mapping:
    start: int
    end: int
    permissions: str

    @property
    def size(self) -> int:
        return self.end - self.start

    def contains(self, address: int, size: int = 1) -> bool:
        return self.start <= address and address + size <= self.end


def adb_command(adb: Path, serial: str, *arguments: str) -> list[str]:
    return [str(adb), "-s", serial, *arguments]


def get_pid(adb: Path, serial: str) -> int:
    result = subprocess.run(
        adb_command(adb, serial, "shell", "pidof", "com.gof.global"),
        check=True,
        capture_output=True,
        text=True,
    )
    pids = result.stdout.split()
    if len(pids) != 1:
        raise RuntimeError(f"expected one game pid, found {pids!r}")
    return int(pids[0])


def get_maps(adb: Path, serial: str, pid: int) -> list[Mapping]:
    result = subprocess.run(
        adb_command(adb, serial, "shell", "su", "0", "cat", f"/proc/{pid}/maps"),
        check=True,
        capture_output=True,
        text=True,
    )
    mappings: list[Mapping] = []
    for line in result.stdout.splitlines():
        match = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)", line)
        if match:
            mappings.append(
                Mapping(
                    int(match.group(1), 16),
                    int(match.group(2), 16),
                    match.group(3),
                )
            )
    return mappings


def read_memory(
    adb: Path,
    serial: str,
    pid: int,
    address: int,
    size: int,
) -> bytes:
    result = subprocess.run(
        adb_command(
            adb,
            serial,
            "exec-out",
            "su",
            "0",
            "dd",
            f"if=/proc/{pid}/mem",
            "iflag=skip_bytes,count_bytes",
            f"skip={address}",
            f"count={size}",
            "status=none",
        ),
        check=True,
        capture_output=True,
    )
    if len(result.stdout) != size:
        raise RuntimeError(
            f"short read at 0x{address:x}: expected {size}, got {len(result.stdout)}"
        )
    return result.stdout


def tvalue_type(raw: int) -> int | None:
    tag = (raw >> 47) & 0x1FFFF
    if tag < 0x10000:
        return None
    return tag - 0x20000


def tvalue_pointer(raw: int) -> int:
    return raw & GC64_POINTER_MASK


def read_gc_string_cached(
    mappings: list[Mapping],
    cache: dict[int, bytes],
    address: int,
    max_length: int = 4096,
) -> str:
    mapping = next(
        (candidate for candidate in mappings if candidate.contains(address, 24)),
        None,
    )
    if mapping is None or mapping.start not in cache:
        raise RuntimeError(f"GC string at 0x{address:x} has no cached mapping")
    data = cache[mapping.start]
    offset = address - mapping.start
    header = data[offset : offset + 24]
    if header[9] != 4:
        raise RuntimeError(f"0x{address:x} is not a GC string (gct={header[9]})")
    length = struct.unpack_from("<I", header, 20)[0]
    if length > max_length:
        raise RuntimeError(f"GC string at 0x{address:x} is too long: {length}")
    if not mapping.contains(address + 24, length):
        raise RuntimeError(f"GC string at 0x{address:x} crosses a mapping boundary")
    value = data[offset + 24 : offset + 24 + length]
    return value.decode("utf-8", errors="replace")


def read_gc_string(
    adb: Path,
    serial: str,
    pid: int,
    address: int,
    max_length: int = 4096,
) -> str:
    header = read_memory(adb, serial, pid, address, 24)
    if header[9] != 4:
        raise RuntimeError(f"0x{address:x} is not a GC string (gct={header[9]})")
    length = struct.unpack_from("<I", header, 20)[0]
    if length > max_length:
        raise RuntimeError(f"GC string at 0x{address:x} is too long: {length}")
    return read_memory(adb, serial, pid, address + 24, length).decode(
        "utf-8", errors="replace"
    )


def inspect_table(
    adb: Path,
    serial: str,
    pid: int,
    table_address: int,
) -> list[TableEntry]:
    mappings = get_maps(adb, serial, pid)
    header = read_memory(adb, serial, pid, table_address, 0x40)
    if header[9] != 11:
        raise RuntimeError(
            f"0x{table_address:x} is not a GC table (gct={header[9]})"
        )
    array_address = struct.unpack_from("<Q", header, 0x10)[0]
    node_address = struct.unpack_from("<Q", header, 0x28)[0]
    asize = struct.unpack_from("<I", header, 0x30)[0]
    hmask = struct.unpack_from("<I", header, 0x34)[0]
    if asize > 1 << 20 or hmask > (1 << 20) - 1:
        raise RuntimeError(f"unreasonable table size: asize={asize}, hmask=0x{hmask:x}")
    nodes = read_memory(adb, serial, pid, node_address, (hmask + 1) * 24)

    pending: list[tuple[int, int, int]] = []
    numeric_entries: list[tuple[str, int]] = []
    for index in range(hmask + 1):
        offset = index * 24
        value_raw, key_raw = struct.unpack_from("<QQ", nodes, offset)
        key_tag = tvalue_type(key_raw)
        if key_tag == -5:
            pending.append((tvalue_pointer(key_raw), value_raw, index))
        elif key_tag == -14:
            key = struct.unpack("<i", struct.pack("<Q", key_raw)[:4])[0]
            numeric_entries.append((str(key), value_raw))
        elif key_tag is None:
            key = struct.unpack("<d", struct.pack("<Q", key_raw))[0]
            numeric_entries.append((repr(key), value_raw))

    needed_mappings = {
        mapping.start: mapping
        for key_address, _value_raw, _index in pending
        for mapping in mappings
        if mapping.contains(key_address, 24) and mapping.size <= 64 << 20
    }
    cache: dict[int, bytes] = {}
    for mapping in needed_mappings.values():
        try:
            cache[mapping.start] = read_memory(
                adb, serial, pid, mapping.start, mapping.size
            )
        except (OSError, RuntimeError, subprocess.CalledProcessError):
            continue

    entries: list[TableEntry] = []
    if asize:
        array = read_memory(adb, serial, pid, array_address, asize * 8)
        for index in range(asize):
            value_raw = struct.unpack_from("<Q", array, index * 8)[0]
            if tvalue_type(value_raw) != -1:
                numeric_entries.append((str(index), value_raw))

    for key, value_raw in numeric_entries:
        value_tag = tvalue_type(value_raw)
        value_type = LUAJIT_TYPE_NAMES.get(value_tag, "number")
        value_address = None
        if value_tag is not None and -13 <= value_tag <= -4:
            value_address = tvalue_pointer(value_raw)
        entries.append(TableEntry(key, value_type, value_address, value_raw))

    for key_address, value_raw, _index in pending:
        try:
            key = read_gc_string_cached(mappings, cache, key_address)
        except (OSError, RuntimeError, subprocess.CalledProcessError):
            continue
        value_tag = tvalue_type(value_raw)
        value_type = LUAJIT_TYPE_NAMES.get(value_tag, "number")
        value_address = None
        if value_tag is not None and -13 <= value_tag <= -4:
            value_address = tvalue_pointer(value_raw)
        entries.append(TableEntry(key, value_type, value_address, value_raw))
    return sorted(entries, key=lambda entry: entry.key.casefold())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read LuaJIT table keys from a live game using root ADB"
    )
    parser.add_argument("--serial", default="127.0.0.1:16416")
    parser.add_argument(
        "--adb",
        type=Path,
        default=Path(r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--state", type=lambda value: int(value, 0))
    source.add_argument("--table", type=lambda value: int(value, 0))
    parser.add_argument("--filter", default="")
    parser.add_argument("--show-values", action="store_true")
    args = parser.parse_args()

    pid = get_pid(args.adb, args.serial)
    table_address = args.table
    if table_address is None:
        state = read_memory(args.adb, args.serial, pid, args.state, 0x50)
        table_address = struct.unpack_from("<Q", state, 0x48)[0]

    pattern = re.compile(args.filter, re.IGNORECASE) if args.filter else None
    entries = inspect_table(args.adb, args.serial, pid, table_address)
    table_header = read_memory(args.adb, args.serial, pid, table_address, 0x40)
    metatable_address = struct.unpack_from("<Q", table_header, 0x20)[0]
    output = []
    sensitive_key = re.compile(
        r"account|token|password|passwd|email|secret|credential|session|cookie",
        re.IGNORECASE,
    )
    for entry in entries:
        if pattern is not None and not pattern.search(entry.key):
            continue
        item = {
            "key": entry.key,
            "type": entry.value_type,
            **(
                {"address": f"0x{entry.value_address:x}"}
                if entry.value_address is not None
                else {}
            ),
        }
        if args.show_values:
            if sensitive_key.search(entry.key):
                item["value"] = "<redacted>"
            elif entry.value_type == "integer":
                item["value"] = struct.unpack(
                    "<i", struct.pack("<Q", entry.value_raw)[:4]
                )[0]
            elif entry.value_type == "number":
                item["value"] = struct.unpack("<d", struct.pack("<Q", entry.value_raw))[0]
            elif entry.value_type == "true":
                item["value"] = True
            elif entry.value_type == "false":
                item["value"] = False
            elif entry.value_type == "nil":
                item["value"] = None
            elif entry.value_type == "string" and entry.value_address is not None:
                item["value"] = read_gc_string(
                    args.adb, args.serial, pid, entry.value_address
                )
        output.append(item)
    print(
        json.dumps(
            {
                "pid": pid,
                "table": f"0x{table_address:x}",
                "metatable": (
                    f"0x{metatable_address:x}" if metatable_address else None
                ),
                "entry_count": len(entries),
                "entries": output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
