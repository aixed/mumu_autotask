from __future__ import annotations

import argparse
import io
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence


class UnityFSError(ValueError):
    """Raised when a UnityFS bundle is unsupported or malformed."""


def decompress_lz4_block(data: bytes, expected_size: int) -> bytes:
    """Decode the raw LZ4 block format used by UnityFS bundles."""
    source = memoryview(data)
    output = bytearray()
    cursor = 0

    def extended_length(initial: int) -> int:
        nonlocal cursor
        length = initial
        if length != 15:
            return length
        while True:
            if cursor >= len(source):
                raise UnityFSError("truncated LZ4 length")
            value = source[cursor]
            cursor += 1
            length += value
            if value != 255:
                return length

    while cursor < len(source):
        token = source[cursor]
        cursor += 1
        literal_length = extended_length(token >> 4)
        literal_end = cursor + literal_length
        if literal_end > len(source):
            raise UnityFSError("truncated LZ4 literal")
        output.extend(source[cursor:literal_end])
        cursor = literal_end
        if cursor == len(source):
            break
        if cursor + 2 > len(source):
            raise UnityFSError("truncated LZ4 match offset")
        offset = source[cursor] | (source[cursor + 1] << 8)
        cursor += 2
        if offset == 0 or offset > len(output):
            raise UnityFSError(f"invalid LZ4 match offset: {offset}")
        match_length = extended_length(token & 0x0F) + 4
        match_start = len(output) - offset
        for index in range(match_length):
            output.append(output[match_start + index])
        if len(output) > expected_size:
            raise UnityFSError("LZ4 block expands past its declared size")

    if len(output) != expected_size:
        raise UnityFSError(
            f"LZ4 size mismatch: expected {expected_size}, got {len(output)}"
        )
    return bytes(output)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise UnityFSError(f"unexpected end of file while reading {size} bytes")
    return value


def _read_cstring(stream: BinaryIO) -> str:
    value = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            raise UnityFSError("unterminated string in UnityFS header")
        if byte == b"\0":
            return value.decode("utf-8", errors="replace")
        value.extend(byte)


def _align(stream: BinaryIO, boundary: int = 16) -> None:
    position = stream.tell()
    aligned = (position + boundary - 1) & ~(boundary - 1)
    stream.seek(aligned)


def _decompress(data: bytes, compression: int, expected_size: int) -> bytes:
    if compression == 0:
        if len(data) != expected_size:
            raise UnityFSError(
                f"uncompressed size mismatch: expected {expected_size}, got {len(data)}"
            )
        return data
    if compression in {2, 3}:
        return decompress_lz4_block(data, expected_size)
    raise UnityFSError(f"unsupported UnityFS compression type: {compression}")


@dataclass(frozen=True, slots=True)
class StorageBlock:
    uncompressed_size: int
    compressed_size: int
    flags: int


@dataclass(frozen=True, slots=True)
class BundleNode:
    offset: int
    size: int
    flags: int
    path: str


@dataclass(frozen=True, slots=True)
class UnityFSBundle:
    unity_version: str
    unity_revision: str
    blocks: tuple[StorageBlock, ...]
    nodes: tuple[BundleNode, ...]
    data: bytes

    @classmethod
    def load(cls, path: str | Path) -> "UnityFSBundle":
        bundle_path = Path(path)
        with bundle_path.open("rb") as stream:
            signature = _read_cstring(stream)
            if signature != "UnityFS":
                raise UnityFSError(f"unsupported bundle signature: {signature!r}")
            version = struct.unpack(">I", _read_exact(stream, 4))[0]
            unity_version = _read_cstring(stream)
            unity_revision = _read_cstring(stream)
            file_size, compressed_info_size, info_size, flags = struct.unpack(
                ">QIII", _read_exact(stream, 20)
            )
            actual_size = bundle_path.stat().st_size
            if file_size != actual_size:
                raise UnityFSError(
                    f"bundle size mismatch: header={file_size}, actual={actual_size}"
                )
            if version >= 7:
                _align(stream)

            info_at_end = bool(flags & 0x80)
            if info_at_end:
                data_start = stream.tell()
                stream.seek(file_size - compressed_info_size)
                compressed_info = _read_exact(stream, compressed_info_size)
            else:
                compressed_info = _read_exact(stream, compressed_info_size)
                if flags & 0x200:
                    _align(stream)
                data_start = stream.tell()

            info = io.BytesIO(
                _decompress(compressed_info, flags & 0x3F, info_size)
            )
            _read_exact(info, 16)  # content hash
            block_count = struct.unpack(">I", _read_exact(info, 4))[0]
            blocks = tuple(
                StorageBlock(*struct.unpack(">IIH", _read_exact(info, 10)))
                for _ in range(block_count)
            )
            node_count = struct.unpack(">I", _read_exact(info, 4))[0]
            nodes: list[BundleNode] = []
            for _ in range(node_count):
                offset, size, node_flags = struct.unpack(">QQI", _read_exact(info, 20))
                nodes.append(BundleNode(offset, size, node_flags, _read_cstring(info)))

            stream.seek(data_start)
            uncompressed = bytearray()
            for block in blocks:
                compressed = _read_exact(stream, block.compressed_size)
                uncompressed.extend(
                    _decompress(
                        compressed,
                        block.flags & 0x3F,
                        block.uncompressed_size,
                    )
                )
            return cls(
                unity_version,
                unity_revision,
                blocks,
                tuple(nodes),
                bytes(uncompressed),
            )

    def node_bytes(self, node: BundleNode) -> bytes:
        end = node.offset + node.size
        if node.offset < 0 or end > len(self.data):
            raise UnityFSError(f"node {node.path!r} is outside the bundle data")
        return self.data[node.offset:end]

    def extract(self, output_dir: str | Path) -> list[Path]:
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for index, node in enumerate(self.nodes):
            relative = Path(node.path.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                relative = Path(f"node_{index:04d}.bin")
            target = (root / relative).resolve()
            if root not in target.parents and target != root:
                raise UnityFSError(f"unsafe bundle node path: {node.path!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.node_bytes(node))
            written.append(target)
        return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List or extract a UnityFS bundle")
    parser.add_argument("bundle")
    parser.add_argument("--extract")
    args = parser.parse_args(argv)
    bundle = UnityFSBundle.load(args.bundle)
    print(f"Unity {bundle.unity_revision}; {len(bundle.blocks)} blocks")
    for node in bundle.nodes:
        print(f"{node.size:10d}  {node.path}")
    if args.extract:
        paths = bundle.extract(args.extract)
        print(f"extracted {len(paths)} node(s) to {Path(args.extract).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
