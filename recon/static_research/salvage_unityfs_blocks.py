from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unityfs_extract import (
    _align,
    _decompress,
    _parse_block_info,
    _read_be,
    _read_cstring,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover valid UnityFS blocks and zero-fill protected ones."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with args.bundle.open("rb") as stream:
        if _read_cstring(stream) != "UnityFS":
            raise ValueError("not a UnityFS bundle")
        format_version = _read_be(stream, "I")
        _read_cstring(stream)
        _read_cstring(stream)
        file_size = _read_be(stream, "Q")
        compressed_info_size = _read_be(stream, "I")
        uncompressed_info_size = _read_be(stream, "I")
        archive_flags = _read_be(stream, "I")

        if format_version >= 7:
            _align(stream)
        header_end = stream.tell()

        if archive_flags & 0x80:
            stream.seek(file_size - compressed_info_size)
        block_info = _decompress(
            stream.read(compressed_info_size),
            uncompressed_info_size,
            archive_flags,
        )
        blocks, nodes = _parse_block_info(block_info)

        if archive_flags & 0x80:
            stream.seek(header_end)
        if archive_flags & 0x200:
            _align(stream)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        logical_offset = 0
        failures: list[tuple[int, int, int, str]] = []
        with args.output.open("wb") as output:
            for index, block in enumerate(blocks):
                file_offset = stream.tell()
                compressed = stream.read(block.compressed_size)
                try:
                    decoded = _decompress(
                        compressed, block.uncompressed_size, block.flags
                    )
                except Exception as error:
                    decoded = bytes(block.uncompressed_size)
                    failures.append(
                        (index, file_offset, logical_offset, str(error))
                    )
                output.write(decoded)
                logical_offset += block.uncompressed_size

    print(
        f"blocks={len(blocks)} failures={len(failures)} "
        f"decoded={logical_offset} nodes={len(nodes)} output={args.output}"
    )
    for index, file_offset, logical_offset, error in failures:
        print(
            f"failed_block={index} file_offset={file_offset} "
            f"logical_offset={logical_offset} error={error}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
