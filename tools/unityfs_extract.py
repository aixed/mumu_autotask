from __future__ import annotations

import argparse
import io
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class UnityFSError(ValueError):
    pass


def _read_cstring(stream: io.BufferedIOBase | io.BytesIO) -> str:
    value = bytearray()
    while True:
        chunk = stream.read(1)
        if not chunk:
            raise UnityFSError("unexpected end of file while reading a string")
        if chunk == b"\0":
            return value.decode("utf-8", errors="replace")
        value.extend(chunk)


def _read_be(stream: io.BufferedIOBase | io.BytesIO, fmt: str) -> int:
    size = struct.calcsize(fmt)
    value = stream.read(size)
    if len(value) != size:
        raise UnityFSError("unexpected end of file")
    return struct.unpack(">" + fmt, value)[0]


def _align(stream: io.BufferedIOBase, boundary: int = 16) -> None:
    position = stream.tell()
    stream.seek((position + boundary - 1) & ~(boundary - 1))


def decompress_lz4_block(data: bytes, expected_size: int) -> bytes:
    source = memoryview(data)
    output = bytearray()
    cursor = 0

    while cursor < len(source):
        token_position = cursor
        token = source[cursor]
        cursor += 1

        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if cursor >= len(source):
                    raise UnityFSError("truncated LZ4 literal length")
                extension = source[cursor]
                cursor += 1
                literal_length += extension
                if extension != 255:
                    break

        literal_end = cursor + literal_length
        if literal_end > len(source):
            raise UnityFSError("truncated LZ4 literal data")
        output.extend(source[cursor:literal_end])
        cursor = literal_end

        if cursor == len(source):
            break
        if cursor + 2 > len(source):
            raise UnityFSError("truncated LZ4 match offset")

        match_offset = source[cursor] | (source[cursor + 1] << 8)
        cursor += 2
        if match_offset == 0 or match_offset > len(output):
            raise UnityFSError(
                "invalid LZ4 match offset "
                f"{match_offset} at input {cursor - 2}, output {len(output)}, "
                f"token 0x{token:02x} at input {token_position}; "
                f"decoded prefix={output[:96].hex()}"
            )

        match_length = token & 0x0F
        if match_length == 15:
            while True:
                if cursor >= len(source):
                    raise UnityFSError("truncated LZ4 match length")
                extension = source[cursor]
                cursor += 1
                match_length += extension
                if extension != 255:
                    break
        match_length += 4

        match_start = len(output) - match_offset
        for index in range(match_length):
            output.append(output[match_start + index])

    if len(output) != expected_size:
        raise UnityFSError(
            f"LZ4 size mismatch: expected {expected_size}, got {len(output)}"
        )
    return bytes(output)


def _decompress(data: bytes, expected_size: int, flags: int) -> bytes:
    compression = flags & 0x3F
    if compression == 0:
        result = data
    elif compression in (2, 3):
        result = decompress_lz4_block(data, expected_size)
    else:
        raise UnityFSError(f"unsupported UnityFS compression type: {compression}")

    if len(result) != expected_size:
        raise UnityFSError(
            f"block size mismatch: expected {expected_size}, got {len(result)}"
        )
    return result


@dataclass(frozen=True)
class Block:
    uncompressed_size: int
    compressed_size: int
    flags: int


@dataclass(frozen=True)
class Node:
    offset: int
    size: int
    flags: int
    path: str


def _parse_block_info(data: bytes) -> tuple[list[Block], list[Node]]:
    stream = io.BytesIO(data)
    if len(stream.read(16)) != 16:
        raise UnityFSError("truncated block-info hash")

    blocks = [
        Block(
            uncompressed_size=_read_be(stream, "I"),
            compressed_size=_read_be(stream, "I"),
            flags=_read_be(stream, "H"),
        )
        for _ in range(_read_be(stream, "I"))
    ]

    nodes = [
        Node(
            offset=_read_be(stream, "q"),
            size=_read_be(stream, "q"),
            flags=_read_be(stream, "I"),
            path=_read_cstring(stream),
        )
        for _ in range(_read_be(stream, "I"))
    ]
    return blocks, nodes


def read_unityfs(bundle_path: Path) -> tuple[bytes, list[Node]]:
    with bundle_path.open("rb") as stream:
        if _read_cstring(stream) != "UnityFS":
            raise UnityFSError("not a UnityFS bundle")

        format_version = _read_be(stream, "I")
        _read_cstring(stream)  # minimum player version
        _read_cstring(stream)  # engine version
        file_size = _read_be(stream, "Q")
        compressed_info_size = _read_be(stream, "I")
        uncompressed_info_size = _read_be(stream, "I")
        archive_flags = _read_be(stream, "I")

        if file_size != bundle_path.stat().st_size:
            raise UnityFSError(
                f"bundle size mismatch: header={file_size}, file={bundle_path.stat().st_size}"
            )

        if format_version >= 7:
            _align(stream)
        header_end = stream.tell()

        if archive_flags & 0x80:
            stream.seek(file_size - compressed_info_size)
        compressed_info = stream.read(compressed_info_size)
        if len(compressed_info) != compressed_info_size:
            raise UnityFSError("truncated block information")
        block_info = _decompress(
            compressed_info, uncompressed_info_size, archive_flags
        )
        blocks, nodes = _parse_block_info(block_info)

        if archive_flags & 0x80:
            stream.seek(header_end)
        if archive_flags & 0x200:
            _align(stream)

        content = bytearray()
        for block in blocks:
            compressed = stream.read(block.compressed_size)
            if len(compressed) != block.compressed_size:
                raise UnityFSError("truncated bundle data block")
            content.extend(
                _decompress(compressed, block.uncompressed_size, block.flags)
            )
        return bytes(content), nodes


def _safe_destination(root: Path, archive_path: str) -> Path:
    relative = PurePosixPath(archive_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise UnityFSError(f"unsafe archive path: {archive_path!r}")
    destination = root.joinpath(*relative.parts).resolve()
    if root.resolve() not in destination.parents and destination != root.resolve():
        raise UnityFSError(f"archive path escapes output directory: {archive_path!r}")
    return destination


def extract(bundle_path: Path, output_dir: Path) -> list[Path]:
    content, nodes = read_unityfs(bundle_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for node in nodes:
        end = node.offset + node.size
        if node.offset < 0 or end > len(content):
            raise UnityFSError(f"node outside bundle data: {node.path!r}")
        destination = _safe_destination(output_dir, node.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content[node.offset:end])
        written.append(destination)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a UnityFS bundle")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    for path in extract(args.bundle, args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
