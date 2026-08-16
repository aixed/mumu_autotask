from __future__ import annotations

import struct
import unittest

from mumu_autotask.lua_state import (
    AdbLuaStateScanner,
    LuaStateScanError,
    MemoryMapping,
    parse_process_maps,
    validate_lua_state_candidate,
)


ARENA_START = 0x10000000
ARENA_SIZE = 0x20000
PID = 7359


def place_state(
    data: bytearray,
    state_offset: int,
    *,
    glref_offset: int,
    stack_offset: int,
    env_offset: int,
    main_offset: int | None = None,
    cframe: int = 0,
) -> int:
    state = ARENA_START + state_offset
    glref = ARENA_START + glref_offset
    stack = ARENA_START + stack_offset
    env = ARENA_START + env_offset
    main_state = state if main_offset is None else ARENA_START + main_offset

    struct.pack_into("4B", data, state_offset + 8, 4, 6, 1, 0)
    struct.pack_into("<Q", data, state_offset + 0x10, glref)
    struct.pack_into("<Q", data, state_offset + 0x20, stack + 0x80)
    struct.pack_into("<Q", data, state_offset + 0x28, stack + 0x100)
    struct.pack_into("<Q", data, state_offset + 0x30, stack + 0x200)
    struct.pack_into("<Q", data, state_offset + 0x38, stack)
    struct.pack_into("<Q", data, state_offset + 0x40, 0)
    struct.pack_into("<Q", data, state_offset + 0x48, env)
    struct.pack_into("<Q", data, state_offset + 0x50, cframe)
    struct.pack_into("<I", data, state_offset + 0x58, 64)
    struct.pack_into("<Q", data, glref_offset + 0xC0, main_state)
    data[env_offset + 9] = 11
    return state


def main_arena(*, cframe: int = 0) -> tuple[bytes, int]:
    data = bytearray(ARENA_SIZE)
    state = place_state(
        data,
        0x1000,
        glref_offset=0x8000,
        stack_offset=0x4000,
        env_offset=0x9000,
        cframe=cframe,
    )
    return bytes(data), state


class FakeAdb:
    def __init__(
        self,
        memories: list[bytes],
        *,
        maps_outputs: list[str] | None = None,
    ) -> None:
        self.memories = memories
        self.memory_index = 0
        self.maps_outputs = maps_outputs or [self.arena_map()]
        self.maps_index = 0
        self.shell_calls: list[tuple[str, ...]] = []
        self.exec_calls: list[tuple[str, ...]] = []

    @staticmethod
    def arena_map(start: int = ARENA_START) -> str:
        return (
            f"{start:x}-{start + ARENA_SIZE:x} "
            "rw-p 00000000 00:00 0\n"
        )

    @staticmethod
    def _next_repeating(values, index: int):
        return values[min(index, len(values) - 1)]

    def shell(self, serial: str, *args: str) -> str:
        self.shell_calls.append((serial, *args))
        result = self._next_repeating(self.maps_outputs, self.maps_index)
        self.maps_index += 1
        return result

    def exec_out(self, serial: str, *args: str) -> bytes:
        self.exec_calls.append((serial, *args))
        result = self._next_repeating(self.memories, self.memory_index)
        self.memory_index += 1
        return result


def scanner(adb: FakeAdb, **kwargs) -> AdbLuaStateScanner:
    return AdbLuaStateScanner(
        adb,
        "device-1",
        retry_delay_seconds=0,
        **kwargs,
    )


class LuaStateTests(unittest.TestCase):
    def test_parse_process_maps_preserves_anonymous_mapping(self) -> None:
        mappings = parse_process_maps(
            "10000000-10020000 rw-p 00000000 00:00 0\n"
            "70000000-70001000 r-xp 00000000 00:01 1 /system/lib64/x.so\n"
        )
        self.assertEqual(
            mappings[0],
            MemoryMapping(ARENA_START, ARENA_START + ARENA_SIZE, "rw-p", ""),
        )
        self.assertEqual(mappings[1].path, "/system/lib64/x.so")

    def test_finds_unique_idle_main_state(self) -> None:
        memory, state = main_arena()
        adb = FakeAdb([memory])
        candidate = scanner(adb).find_unique_idle_main(PID)
        self.assertEqual(candidate.address, state)
        self.assertTrue(candidate.is_main)
        self.assertEqual(candidate.cframe, 0)
        self.assertIn(f"skip={ARENA_START}", adb.exec_calls[0])
        self.assertIn(f"count={ARENA_SIZE}", adb.exec_calls[0])

    def test_duplicate_main_states_are_rejected(self) -> None:
        data = bytearray(ARENA_SIZE)
        first = place_state(
            data,
            0x1000,
            glref_offset=0x8000,
            stack_offset=0x4000,
            env_offset=0x9000,
        )
        second = place_state(
            data,
            0x2000,
            glref_offset=0xA000,
            stack_offset=0x6000,
            env_offset=0xB000,
        )
        state_scanner = scanner(FakeAdb([bytes(data)]))
        with self.assertRaises(LuaStateScanError) as raised:
            state_scanner.find_unique_idle_main(PID)
        self.assertIn(f"0x{first:x}", str(raised.exception))
        self.assertIn(f"0x{second:x}", str(raised.exception))

    def test_nonzero_cframe_is_rejected(self) -> None:
        memory, state = main_arena(cframe=0x1234)
        state_scanner = scanner(FakeAdb([memory]))
        with self.assertRaisesRegex(
            LuaStateScanError,
            rf"0x{state:x} is busy .*cframe=0x1234",
        ):
            state_scanner.find_unique_idle_main(PID)

    def test_structural_failure_is_rejected(self) -> None:
        memory, state = main_arena()
        corrupted = bytearray(memory)
        corrupted[state - ARENA_START + 9] = 5
        state_scanner = scanner(FakeAdb([bytes(corrupted)]))
        with self.assertRaisesRegex(LuaStateScanError, "found none"):
            state_scanner.find_unique_idle_main(PID)

        mapping = MemoryMapping(
            ARENA_START,
            ARENA_START + ARENA_SIZE,
            "rw-p",
            "",
        )
        self.assertIsNone(
            validate_lua_state_candidate(
                mapping,
                bytes(corrupted),
                state - ARENA_START,
                [mapping],
            )
        )

    def test_pre_and_post_revalidation_detect_state_becoming_busy(self) -> None:
        memory, state = main_arena()
        busy_memory, _ = main_arena(cframe=0x8888)
        state_scanner = scanner(FakeAdb([memory, memory, busy_memory]))
        found = state_scanner.find_unique_idle_main(PID)
        before = state_scanner.verify_idle_main(PID, found.address)
        self.assertEqual(before.address, state)
        with self.assertRaisesRegex(LuaStateScanError, "is busy"):
            state_scanner.verify_idle_main(PID, found.address)

    def test_revalidation_rejects_structural_change(self) -> None:
        memory, state = main_arena()
        corrupted = bytearray(memory)
        corrupted[state - ARENA_START + 0x10 : state - ARENA_START + 0x18] = b"\0" * 8
        state_scanner = scanner(FakeAdb([bytes(corrupted)]))
        with self.assertRaisesRegex(LuaStateScanError, "structural validation"):
            state_scanner.verify_idle_main(PID, state)

    def test_empty_maps_are_retried_as_a_complete_scan(self) -> None:
        memory, state = main_arena()
        delays: list[float] = []
        adb = FakeAdb(
            [memory],
            maps_outputs=["", "", FakeAdb.arena_map()],
        )
        state_scanner = AdbLuaStateScanner(
            adb,
            "device-1",
            retry_delay_seconds=0.125,
            sleep=delays.append,
        )
        candidate = state_scanner.find_unique_idle_main(PID)
        self.assertEqual(candidate.address, state)
        self.assertEqual(len(adb.shell_calls), 3)
        self.assertEqual(delays, [0.125, 0.125])

    def test_zero_and_partial_mapping_reads_are_retried(self) -> None:
        memory, state = main_arena()
        delays: list[float] = []
        adb = FakeAdb([b"", b"x" * 43, memory])
        state_scanner = AdbLuaStateScanner(
            adb,
            "device-1",
            retry_delay_seconds=0.05,
            sleep=delays.append,
        )
        candidate = state_scanner.find_unique_idle_main(PID)
        self.assertEqual(candidate.address, state)
        self.assertEqual(len(adb.exec_calls), 3)
        self.assertEqual(delays, [0.05, 0.05])

    def test_dynamic_mapping_failure_does_not_abort_remaining_reads(self) -> None:
        memory, state = main_arena()
        dynamic_start = 0x20000000
        first_maps = FakeAdb.arena_map(dynamic_start) + FakeAdb.arena_map()
        adb = FakeAdb(
            [b"x" * 43, memory, memory],
            maps_outputs=[first_maps, FakeAdb.arena_map()],
        )
        candidate = scanner(adb).find_unique_idle_main(PID)
        self.assertEqual(candidate.address, state)
        self.assertEqual(len(adb.shell_calls), 2)
        self.assertEqual(len(adb.exec_calls), 3)

    def test_revalidation_retries_a_transient_short_read(self) -> None:
        memory, state = main_arena()
        adb = FakeAdb([b"", memory])
        candidate = scanner(adb).verify_idle_main(PID, state)
        self.assertEqual(candidate.address, state)
        self.assertEqual(len(adb.exec_calls), 2)

    def test_short_reads_fail_closed_after_bounded_attempts(self) -> None:
        memory, _ = main_arena()
        adb = FakeAdb([memory[:43]])
        with self.assertRaisesRegex(
            LuaStateScanError,
            "failed after 3 attempts.*short read",
        ):
            scanner(adb).find_unique_idle_main(PID)
        self.assertEqual(len(adb.shell_calls), 3)
        self.assertEqual(len(adb.exec_calls), 3)


if __name__ == "__main__":
    unittest.main()
