from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

from .adb import AdbClient, AdbError


class LuaStateScanError(RuntimeError):
    """Raised when a unique main LuaJIT state cannot be proven."""


@dataclass(frozen=True, slots=True)
class MemoryMapping:
    start: int
    end: int
    permissions: str
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start

    def contains(self, address: int, size: int = 1) -> bool:
        return self.start <= address and address + size <= self.end


@dataclass(frozen=True, slots=True)
class LuaStateCandidate:
    address: int
    marked: int
    status: int
    glref: int
    base: int
    top: int
    maxstack: int
    stack: int
    openupval: int
    env: int
    cframe: int
    stacksize: int
    main_thread: int

    @property
    def is_main(self) -> bool:
        return self.address == self.main_thread

    @property
    def address_text(self) -> str:
        return f"0x{self.address:x}"


_MAP_PATTERN = re.compile(
    r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)$"
)
_FAST_ARENA_SIZE_PRIORITY = (0x160000, 0xA0000, 0x80000, 0x60000, 0x40000, 0x20000)
_FAST_ARENA_SIZES = frozenset(_FAST_ARENA_SIZE_PRIORITY)
_FAST_ARENA_SIZE_RANK = {
    size: index for index, size in enumerate(_FAST_ARENA_SIZE_PRIORITY)
}
_MAX_FALLBACK_MAPPING_SIZE = 256 << 20
_DEFAULT_SCAN_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 0.1
_T = TypeVar("_T")


def parse_process_maps(text: str) -> list[MemoryMapping]:
    mappings: list[MemoryMapping] = []
    for line in text.splitlines():
        match = _MAP_PATTERN.match(line)
        if match is None:
            continue
        mappings.append(
            MemoryMapping(
                int(match.group(1), 16),
                int(match.group(2), 16),
                match.group(3),
                match.group(4),
            )
        )
    if not mappings:
        raise LuaStateScanError("process maps contained no parseable mappings")
    return mappings


def _containing_mapping(
    mappings: Sequence[MemoryMapping], address: int, size: int = 1
) -> MemoryMapping | None:
    return next(
        (mapping for mapping in mappings if mapping.contains(address, size)),
        None,
    )


def validate_lua_state_candidate(
    mapping: MemoryMapping,
    data: bytes,
    offset: int,
    mappings: Sequence[MemoryMapping],
) -> LuaStateCandidate | None:
    if offset < 0 or offset + 0x60 > len(data):
        return None
    address = mapping.start + offset
    marked, gct, dummy_ffid, status = struct.unpack_from("4B", data, offset + 8)
    if gct != 6 or dummy_ffid != 1 or status > 14:
        return None

    glref = struct.unpack_from("<Q", data, offset + 0x10)[0]
    base = struct.unpack_from("<Q", data, offset + 0x20)[0]
    top = struct.unpack_from("<Q", data, offset + 0x28)[0]
    maxstack = struct.unpack_from("<Q", data, offset + 0x30)[0]
    stack = struct.unpack_from("<Q", data, offset + 0x38)[0]
    openupval = struct.unpack_from("<Q", data, offset + 0x40)[0]
    env = struct.unpack_from("<Q", data, offset + 0x48)[0]
    cframe = struct.unpack_from("<Q", data, offset + 0x50)[0]
    stacksize = struct.unpack_from("<I", data, offset + 0x58)[0]

    if any(pointer & 7 for pointer in (glref, base, top, maxstack, stack, env)):
        return None
    if not stack <= base <= top <= maxstack:
        return None
    if not 32 <= stacksize <= 1_000_000:
        return None
    stack_bytes = maxstack - stack
    if stack_bytes > stacksize * 8 or stack_bytes + 128 < stacksize * 8:
        return None
    for pointer, size in (
        (glref, 0xC8),
        (stack, 8),
        (maxstack - 1, 1),
        (env, 16),
    ):
        target = _containing_mapping(mappings, pointer, size)
        if target is None or not target.permissions.startswith("r"):
            return None

    if not mapping.contains(glref + 0xC0, 8):
        return None
    main_thread = struct.unpack_from(
        "<Q", data, glref + 0xC0 - mapping.start
    )[0]
    if not mapping.contains(main_thread, 0x60):
        return None
    main_offset = main_thread - mapping.start
    if data[main_offset + 9] != 6:
        return None
    if struct.unpack_from("<Q", data, main_offset + 0x10)[0] != glref:
        return None
    if mapping.contains(env, 16) and data[env - mapping.start + 9] != 11:
        return None

    return LuaStateCandidate(
        address,
        marked,
        status,
        glref,
        base,
        top,
        maxstack,
        stack,
        openupval,
        env,
        cframe,
        stacksize,
        main_thread,
    )


class AdbLuaStateScanner:
    def __init__(
        self,
        adb: AdbClient,
        serial: str,
        *,
        max_attempts: int = _DEFAULT_SCAN_ATTEMPTS,
        retry_delay_seconds: float = _DEFAULT_RETRY_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise ValueError("max_attempts must be a positive integer")
        if max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        self.adb = adb
        self.serial = serial
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    def _maps(self, pid: int) -> list[MemoryMapping]:
        text = self.adb.shell(
            self.serial, "su", "0", "cat", f"/proc/{pid}/maps"
        )
        return parse_process_maps(text)

    def _read_mapping(self, pid: int, mapping: MemoryMapping) -> bytes:
        data = self.adb.exec_out(
            self.serial,
            "su",
            "0",
            "dd",
            f"if=/proc/{pid}/mem",
            "iflag=skip_bytes,count_bytes",
            f"skip={mapping.start}",
            f"count={mapping.size}",
            "status=none",
        )
        if len(data) != mapping.size:
            raise LuaStateScanError(
                f"short read for mapping 0x{mapping.start:x}-0x{mapping.end:x}: "
                f"expected {mapping.size}, got {len(data)}"
            )
        return data

    def _scan_mappings(
        self,
        pid: int,
        mappings: Sequence[MemoryMapping],
        selected: Sequence[MemoryMapping],
        *,
        stop_after_main_size_group: bool = False,
    ) -> tuple[list[LuaStateCandidate], list[str]]:
        found: dict[int, LuaStateCandidate] = {}
        failures: list[str] = []
        main_size_group: int | None = None
        for mapping in selected:
            if (
                stop_after_main_size_group
                and main_size_group is not None
                and mapping.size != main_size_group
            ):
                break
            try:
                data = self._read_mapping(pid, mapping)
            except (AdbError, LuaStateScanError) as exc:
                failures.append(
                    f"0x{mapping.start:x}-0x{mapping.end:x}: {exc}"
                )
                continue
            cursor = 0
            while True:
                marker = data.find(b"\x06\x01", cursor)
                if marker < 0:
                    break
                candidate = validate_lua_state_candidate(
                    mapping, data, marker - 9, mappings
                )
                if candidate is not None:
                    found[candidate.address] = candidate
                    if (
                        stop_after_main_size_group
                        and candidate.is_main
                        and main_size_group is None
                    ):
                        main_size_group = mapping.size
                cursor = marker + 1
        return list(found.values()), failures

    @staticmethod
    def _eligible(mapping: MemoryMapping) -> bool:
        return (
            mapping.permissions.startswith("rw")
            and not mapping.path
            and 0x1000 <= mapping.size <= _MAX_FALLBACK_MAPPING_SIZE
        )

    @staticmethod
    def _require_unique_main(
        candidates: Sequence[LuaStateCandidate],
        pid: int,
        *,
        require_idle: bool,
    ) -> LuaStateCandidate:
        main_states = [candidate for candidate in candidates if candidate.is_main]
        if len(main_states) != 1:
            addresses = ", ".join(item.address_text for item in main_states) or "none"
            raise LuaStateScanError(
                f"PID {pid}: expected one main Lua state, found {addresses}"
            )
        state = main_states[0]
        if require_idle and state.cframe != 0:
            raise LuaStateScanError(
                f"PID {pid}: main Lua state {state.address_text} is busy "
                f"(cframe=0x{state.cframe:x})"
            )
        return state

    def _retry(
        self,
        pid: int,
        label: str,
        operation: Callable[[], _T],
    ) -> _T:
        errors: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except (AdbError, LuaStateScanError) as exc:
                errors.append(str(exc))
                if attempt < self.max_attempts:
                    self._sleep(self.retry_delay_seconds)
        detail = errors[-1] if errors else "unknown failure"
        raise LuaStateScanError(
            f"PID {pid}: {label} failed after {self.max_attempts} "
            f"attempts: {detail}"
        )

    def _find_unique_main_once(
        self, pid: int, *, require_idle: bool
    ) -> LuaStateCandidate:
        mappings = self._maps(pid)
        eligible = [mapping for mapping in mappings if self._eligible(mapping)]
        fast = [
            mapping
            for mapping in eligible
            if mapping.size in _FAST_ARENA_SIZES
        ]
        fast.sort(key=lambda mapping: (_FAST_ARENA_SIZE_RANK[mapping.size], mapping.start))
        candidates, failures = self._scan_mappings(
            pid,
            mappings,
            fast,
            stop_after_main_size_group=True,
        )
        if not any(candidate.is_main for candidate in candidates):
            fallback = [mapping for mapping in eligible if mapping not in fast]
            fallback_candidates, fallback_failures = self._scan_mappings(
                pid,
                mappings,
                fallback,
            )
            candidates.extend(fallback_candidates)
            failures.extend(fallback_failures)
        if failures:
            raise LuaStateScanError(
                f"PID {pid}: mapping set changed or could not be read: "
                + "; ".join(failures)
            )
        return self._require_unique_main(
            candidates, pid, require_idle=require_idle
        )

    def find_unique_main(self, pid: int) -> LuaStateCandidate:
        return self._retry(
            pid,
            "Lua state scan",
            lambda: self._find_unique_main_once(pid, require_idle=False),
        )

    def find_unique_idle_main(self, pid: int) -> LuaStateCandidate:
        return self._retry(
            pid,
            "Lua state scan",
            lambda: self._find_unique_main_once(pid, require_idle=True),
        )

    def _verify_main_once(
        self,
        pid: int,
        address: int,
        *,
        require_idle: bool,
    ) -> LuaStateCandidate:
        mappings = self._maps(pid)
        mapping = _containing_mapping(mappings, address, 0x60)
        if mapping is None or not self._eligible(mapping):
            raise LuaStateScanError(
                f"PID {pid}: Lua state 0x{address:x} is no longer in an "
                "eligible mapping"
            )
        data = self._read_mapping(pid, mapping)
        candidate = validate_lua_state_candidate(
            mapping, data, address - mapping.start, mappings
        )
        if candidate is None or candidate.address != address:
            raise LuaStateScanError(
                f"PID {pid}: Lua state 0x{address:x} failed structural validation"
            )
        return self._require_unique_main(
            [candidate], pid, require_idle=require_idle
        )

    def verify_main(self, pid: int, address: int) -> LuaStateCandidate:
        return self._retry(
            pid,
            f"Lua state 0x{address:x} revalidation",
            lambda: self._verify_main_once(pid, address, require_idle=False),
        )

    def verify_idle_main(self, pid: int, address: int) -> LuaStateCandidate:
        return self._retry(
            pid,
            f"Lua state 0x{address:x} revalidation",
            lambda: self._verify_main_once(pid, address, require_idle=True),
        )

    def verify_main_once(self, pid: int, address: int) -> LuaStateCandidate:
        return self._verify_main_once(pid, address, require_idle=False)

    def verify_idle_main_once(self, pid: int, address: int) -> LuaStateCandidate:
        return self._verify_main_once(pid, address, require_idle=True)


__all__ = [
    "AdbLuaStateScanner",
    "LuaStateCandidate",
    "LuaStateScanError",
    "MemoryMapping",
    "parse_process_maps",
    "validate_lua_state_candidate",
]
