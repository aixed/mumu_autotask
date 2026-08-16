from __future__ import annotations

import argparse
import ipaddress
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


class PcapError(ValueError):
    """Raised when a capture is malformed or uses an unsupported link type."""


@dataclass(frozen=True, slots=True)
class TcpPayload:
    timestamp: float
    source: str
    source_port: int
    destination: str
    destination_port: int
    sequence: int
    payload: bytes


def iter_tcp_payloads(path: str | Path) -> Iterator[TcpPayload]:
    """Yield IPv4 TCP payloads from classic PCAP with Ethernet or Linux SLL."""
    capture = Path(path)
    with capture.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24:
            raise PcapError("truncated PCAP global header")
        magic = header[:4]
        if magic == b"\xd4\xc3\xb2\xa1":
            byte_order, timestamp_scale = "<", 1_000_000
        elif magic == b"\xa1\xb2\xc3\xd4":
            byte_order, timestamp_scale = ">", 1_000_000
        elif magic == b"\x4d\x3c\xb2\xa1":
            byte_order, timestamp_scale = "<", 1_000_000_000
        elif magic == b"\xa1\xb2\x3c\x4d":
            byte_order, timestamp_scale = ">", 1_000_000_000
        else:
            raise PcapError(f"unsupported PCAP magic: {magic.hex()}")
        link_type = struct.unpack_from(f"{byte_order}I", header, 20)[0]
        if link_type not in {1, 113}:
            raise PcapError(f"unsupported PCAP link type: {link_type}")

        while True:
            record = stream.read(16)
            if not record:
                return
            if len(record) != 16:
                raise PcapError("truncated PCAP record header")
            seconds, fraction, captured_size, _original_size = struct.unpack(
                f"{byte_order}IIII", record
            )
            frame = stream.read(captured_size)
            if len(frame) != captured_size:
                raise PcapError("truncated PCAP packet")
            network_offset = 14 if link_type == 1 else 16
            if len(frame) < network_offset + 20:
                continue
            if link_type == 1:
                ether_type = struct.unpack_from(">H", frame, 12)[0]
            else:
                ether_type = struct.unpack_from(">H", frame, 14)[0]
            if ether_type != 0x0800:
                continue
            ip = frame[network_offset:]
            if ip[0] >> 4 != 4 or ip[9] != 6:
                continue
            ip_header_size = (ip[0] & 0x0F) * 4
            if ip_header_size < 20 or len(ip) < ip_header_size + 20:
                continue
            total_size = struct.unpack_from(">H", ip, 2)[0]
            tcp = ip[ip_header_size:total_size]
            if len(tcp) < 20:
                continue
            source_port, destination_port, sequence = struct.unpack_from(">HHI", tcp, 0)
            tcp_header_size = (tcp[12] >> 4) * 4
            if tcp_header_size < 20 or tcp_header_size > len(tcp):
                continue
            payload = bytes(tcp[tcp_header_size:])
            if not payload:
                continue
            yield TcpPayload(
                timestamp=seconds + fraction / timestamp_scale,
                source=str(ipaddress.IPv4Address(ip[12:16])),
                source_port=source_port,
                destination=str(ipaddress.IPv4Address(ip[16:20])),
                destination_port=destination_port,
                sequence=sequence,
                payload=payload,
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List TCP application payloads in PCAP")
    parser.add_argument("pcap")
    parser.add_argument("--port", type=int)
    parser.add_argument("--minimum-size", type=int, default=1)
    args = parser.parse_args(argv)
    for packet in iter_tcp_payloads(args.pcap):
        if args.port and args.port not in {packet.source_port, packet.destination_port}:
            continue
        if len(packet.payload) < args.minimum_size:
            continue
        print(
            f"{packet.timestamp:.6f} "
            f"{packet.source}:{packet.source_port} -> "
            f"{packet.destination}:{packet.destination_port} "
            f"{len(packet.payload)} {packet.payload.hex()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
