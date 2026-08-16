from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from mumu_autotask.pcap import iter_tcp_payloads


class PcapTests(unittest.TestCase):
    def test_reads_linux_sll_ipv4_tcp_payload(self) -> None:
        sll = b"\x00\x04\x00\x01\x00\x06" + b"\0" * 8 + b"\x08\x00"
        tcp = struct.pack(">HHIIHHHH", 1234, 30101, 7, 0, 0x5018, 65535, 0, 0)
        payload = b"\x00\x03abc"
        ip_size = 20 + len(tcp) + len(payload)
        ip = bytearray(20)
        ip[0] = 0x45
        struct.pack_into(">H", ip, 2, ip_size)
        ip[8] = 64
        ip[9] = 6
        ip[12:16] = b"\x0a\x00\x02\x0f"
        ip[16:20] = b"\x01\x02\x03\x04"
        frame = sll + bytes(ip) + tcp + payload
        global_header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 113)
        record = struct.pack("<IIII", 10, 500000, len(frame), len(frame)) + frame
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            path.write_bytes(global_header + record)
            packets = list(iter_tcp_payloads(path))
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].timestamp, 10.5)
        self.assertEqual(packets[0].destination_port, 30101)
        self.assertEqual(packets[0].payload, payload)


if __name__ == "__main__":
    unittest.main()
