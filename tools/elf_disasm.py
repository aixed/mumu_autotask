from __future__ import annotations

import argparse
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, Cs
from elftools.elf.elffile import ELFFile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Disassemble one ELF symbol")
    parser.add_argument("elf", type=Path)
    parser.add_argument("symbol")
    parser.add_argument("--bytes", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.elf.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = []
        for section_name in (".dynsym", ".symtab"):
            section = elf.get_section_by_name(section_name)
            if section is not None:
                symbols.extend(symbol for symbol in section.iter_symbols())
        matches = [symbol for symbol in symbols if symbol.name == args.symbol]
        if not matches:
            raise RuntimeError(f"symbol {args.symbol!r} was not found")
        symbol = max(matches, key=lambda item: item.entry.st_size)
        address = int(symbol.entry.st_value)
        size = args.bytes or int(symbol.entry.st_size)
        if size <= 0:
            raise RuntimeError("symbol has no size; pass --bytes")

        segment = next(
            candidate
            for candidate in elf.iter_segments()
            if candidate.header.p_type == "PT_LOAD"
            and candidate.header.p_vaddr <= address
            and address + size
            <= candidate.header.p_vaddr + candidate.header.p_filesz
        )
        offset = int(segment.header.p_offset + address - segment.header.p_vaddr)
        stream.seek(offset)
        code = stream.read(size)

    disassembler = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for instruction in disassembler.disasm(code, address):
        print(
            f"0x{instruction.address:08x}: "
            f"{instruction.mnemonic:<8} {instruction.op_str}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
