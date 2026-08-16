from __future__ import annotations

import unittest

from mumu_autotask.unityfs import UnityFSError, decompress_lz4_block


class Lz4Tests(unittest.TestCase):
    def test_literal_only_block(self) -> None:
        self.assertEqual(decompress_lz4_block(b"\x50hello", 5), b"hello")

    def test_overlapping_match(self) -> None:
        # One literal 'a', offset 1, match length 5.
        self.assertEqual(decompress_lz4_block(b"\x11a\x01\x00", 6), b"aaaaaa")

    def test_rejects_invalid_offset(self) -> None:
        with self.assertRaisesRegex(UnityFSError, "offset"):
            decompress_lz4_block(b"\x00\x01\x00", 4)


if __name__ == "__main__":
    unittest.main()
