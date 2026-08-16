from __future__ import annotations

import unittest

from mumu_autotask.config import DeviceProfile
from mumu_autotask.kingdom import (
    KingdomGuard,
    KingdomGuardError,
    PLAYERPREFS_PATH,
    SDK_PREFS_PATH,
    parse_playerprefs_kingdom,
    parse_sdk_server_id,
)


class FakeAdb:
    def __init__(self, playerprefs_output: str, sdk_output: str) -> None:
        self.outputs = {
            PLAYERPREFS_PATH: playerprefs_output,
            SDK_PREFS_PATH: sdk_output,
        }
        self.calls: list[tuple[str, ...]] = []

    def shell(self, serial: str, *args: str) -> str:
        self.calls.append((serial, *args))
        return self.outputs[args[-1]]


def prefs(kingdom: int) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'
        f'<map><int name="__KEY_KINGDOM__" value="{kingdom}" /></map>'
    )


def sdk_prefs(server_id: int) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'
        '<map><string name="CONTEXT_UTILS_RECENTLY_SERVERID">'
        f"{server_id}</string></map>"
    )


class KingdomTests(unittest.TestCase):
    def test_parses_playerprefs_integer(self) -> None:
        self.assertEqual(parse_playerprefs_kingdom(prefs(4549)), 4549)

    def test_parses_sdk_server_string(self) -> None:
        self.assertEqual(parse_sdk_server_id(sdk_prefs(4549)), 4549)

    def test_guard_reads_playerprefs_with_read_only_adb_command(self) -> None:
        adb = FakeAdb(prefs(4549), sdk_prefs(4549))
        profile = DeviceProfile("127.0.0.1:16384")
        status = KingdomGuard(adb).require(profile)
        self.assertEqual(status.kingdom, 4549)
        self.assertEqual(status.playerprefs_kingdom, 4549)
        self.assertEqual(status.sdk_server_id, 4549)
        self.assertEqual(
            adb.calls,
            [
                (
                    "127.0.0.1:16384",
                    "su",
                    "0",
                    "cat",
                    "/data/data/com.gof.global/shared_prefs/"
                    "com.gof.global.v2.playerprefs.xml",
                ),
                (
                    "127.0.0.1:16384",
                    "su",
                    "0",
                    "cat",
                    "/data/data/com.gof.global/shared_prefs/com.cg.sdk.xml",
                ),
            ],
        )

    def test_guard_blocks_wrong_active_kingdom(self) -> None:
        with self.assertRaisesRegex(KingdomGuardError, "active kingdom is 4583"):
            KingdomGuard(FakeAdb(prefs(4583), sdk_prefs(4583))).require(
                DeviceProfile("device-1")
            )

    def test_guard_blocks_disagreement_between_sources(self) -> None:
        with self.assertRaisesRegex(KingdomGuardError, "sources disagree"):
            KingdomGuard(FakeAdb(prefs(4549), sdk_prefs(4583))).require(
                DeviceProfile("device-1")
            )

    def test_missing_key_fails_closed(self) -> None:
        with self.assertRaisesRegex(KingdomGuardError, "exactly one"):
            parse_playerprefs_kingdom("<map />")

    def test_missing_sdk_key_fails_closed(self) -> None:
        with self.assertRaisesRegex(KingdomGuardError, "exactly one"):
            parse_sdk_server_id("<map />")

    def test_duplicate_keys_fail_closed(self) -> None:
        duplicate_playerprefs = (
            '<map><int name="__KEY_KINGDOM__" value="4549" />'
            '<int name="__KEY_KINGDOM__" value="4549" /></map>'
        )
        duplicate_sdk = (
            '<map><string name="CONTEXT_UTILS_RECENTLY_SERVERID">4549</string>'
            '<string name="CONTEXT_UTILS_RECENTLY_SERVERID">4549</string></map>'
        )
        with self.assertRaisesRegex(KingdomGuardError, "found 2"):
            parse_playerprefs_kingdom(duplicate_playerprefs)
        with self.assertRaisesRegex(KingdomGuardError, "found 2"):
            parse_sdk_server_id(duplicate_sdk)


if __name__ == "__main__":
    unittest.main()
