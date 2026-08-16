from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from inspect_luajit_adb import get_pid, read_gc_string, read_memory


OPCODES = """
ISLT ISGE ISLE ISGT ISEQV ISNEV ISEQS ISNES ISEQN ISNEN ISEQP ISNEP
ISTC ISFC IST ISF ISTYPE ISNUM MOV NOT UNM LEN
ADDVN SUBVN MULVN DIVVN MODVN ADDNV SUBNV MULNV DIVNV MODNV
ADDVV SUBVV MULVV DIVVV MODVV POW CAT
KSTR KCDATA KSHORT KNUM KPRI KNIL UGET USETV USETS USETN USETP UCLO FNEW
TNEW TDUP GGET GSET TGETV TGETS TGETB TGETR TSETV TSETS TSETB TSETM TSETR
CALLM CALL CALLMT CALLT ITERC ITERN VARG ISNEXT
RETM RET RET0 RET1 FORI JFORI FORL IFORL JFORL ITERL IITERL JITERL
LOOP ILOOP JLOOP JMP
FUNCF IFUNCF JFUNCF FUNCV IFUNCV JFUNCV FUNCC FUNCCW
""".split()

GC_TYPE_NAMES = {
    4: "string",
    5: "upvalue",
    6: "thread",
    7: "prototype",
    8: "function",
    9: "trace",
    10: "cdata",
    11: "table",
    12: "userdata",
}

D_STRING_OPS = {"ISEQS", "ISNES", "KSTR", "USETS", "GGET", "GSET"}
C_STRING_OPS = {"TGETS", "TSETS"}


def inspect_function(
    adb: Path,
    serial: str,
    pid: int,
    function_address: int,
) -> dict[str, object]:
    function = read_memory(adb, serial, pid, function_address, 0x28)
    input_gc_type = function[9]
    if input_gc_type == 8:
        ffid = function[0x0A]
        if ffid != 0:
            return {
                "function": f"0x{function_address:x}",
                "kind": "C/fast function",
                "ffid": ffid,
            }
        pc = struct.unpack_from("<Q", function, 0x20)[0]
        prototype_address = pc - 104
    elif input_gc_type == 7:
        prototype_address = function_address
        pc = prototype_address + 104
    else:
        raise RuntimeError(
            f"0x{function_address:x} is not a GC function or prototype "
            f"(gct={input_gc_type})"
        )
    prototype = read_memory(adb, serial, pid, prototype_address, 104)
    if prototype[9] != 7:
        raise RuntimeError(
            f"0x{prototype_address:x} is not a GC prototype (gct={prototype[9]})"
        )

    numparams = prototype[0x0A]
    framesize = prototype[0x0B]
    sizebc = struct.unpack_from("<I", prototype, 0x0C)[0]
    constants_address = struct.unpack_from("<Q", prototype, 0x20)[0]
    sizekgc = struct.unpack_from("<I", prototype, 0x30)[0]
    sizekn = struct.unpack_from("<I", prototype, 0x34)[0]
    chunk_address = struct.unpack_from("<Q", prototype, 0x40)[0]
    firstline = struct.unpack_from("<I", prototype, 0x48)[0]
    numline = struct.unpack_from("<I", prototype, 0x4C)[0]
    chunk = read_gc_string(adb, serial, pid, chunk_address)

    gc_constants: list[dict[str, object]] = []
    string_constants: dict[int, str] = {}
    if sizekgc:
        refs = read_memory(
            adb,
            serial,
            pid,
            constants_address - sizekgc * 8,
            sizekgc * 8,
        )
        for index in range(sizekgc):
            offset = (sizekgc - index - 1) * 8
            address = struct.unpack_from("<Q", refs, offset)[0]
            header = read_memory(adb, serial, pid, address, 10)
            gc_type = header[9]
            item: dict[str, object] = {
                "index": index,
                "type": GC_TYPE_NAMES.get(gc_type, f"gct:{gc_type}"),
                "address": f"0x{address:x}",
            }
            if gc_type == 4:
                value = read_gc_string(adb, serial, pid, address)
                item["value"] = value
                string_constants[index] = value
            gc_constants.append(item)

    number_constants = []
    if sizekn:
        raw_numbers = read_memory(adb, serial, pid, constants_address, sizekn * 8)
        number_constants = [
            struct.unpack_from("<d", raw_numbers, index * 8)[0]
            for index in range(sizekn)
        ]

    instructions = read_memory(adb, serial, pid, pc, sizebc * 4)
    bytecode: list[dict[str, object]] = []
    for instruction_index in range(sizebc):
        raw = struct.unpack_from("<I", instructions, instruction_index * 4)[0]
        opcode = raw & 0xFF
        name = OPCODES[opcode] if opcode < len(OPCODES) else f"OP_{opcode}"
        a = (raw >> 8) & 0xFF
        b = (raw >> 24) & 0xFF
        c = (raw >> 16) & 0xFF
        d = (raw >> 16) & 0xFFFF
        item = {
            "pc": instruction_index,
            "op": name,
            "a": a,
            "b": b,
            "c": c,
            "d": d,
        }
        constant_index = None
        if name in D_STRING_OPS:
            constant_index = d
        elif name in C_STRING_OPS:
            constant_index = c
        if constant_index is not None and constant_index in string_constants:
            item["constant"] = string_constants[constant_index]
        if name == "KSHORT":
            item["literal"] = struct.unpack("<h", struct.pack("<H", d))[0]
        elif name == "KNUM" and d < len(number_constants):
            item["constant"] = number_constants[d]
        elif name in {"JMP", "UCLO", "FORI", "JFORI", "FORL", "IFORL", "ITERL", "IITERL", "LOOP", "ILOOP", "ISNEXT"}:
            item["target"] = instruction_index + 1 + d - 0x8000
        bytecode.append(item)

    return {
        "function": f"0x{function_address:x}",
        "input_kind": "prototype" if input_gc_type == 7 else "function",
        "prototype": f"0x{prototype_address:x}",
        "chunk": chunk,
        "first_line": firstline,
        "last_line": firstline + numline,
        "parameters": numparams,
        "frame_size": framesize,
        "gc_constants": gc_constants,
        "number_constants": number_constants,
        "bytecode": bytecode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read and decode a live LuaJIT function through root ADB"
    )
    parser.add_argument("function", type=lambda value: int(value, 0))
    parser.add_argument("--serial", default="127.0.0.1:16416")
    parser.add_argument(
        "--adb",
        type=Path,
        default=Path(r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"),
    )
    args = parser.parse_args()
    pid = get_pid(args.adb, args.serial)
    result = inspect_function(args.adb, args.serial, pid, args.function)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
