from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from .adb import AdbClient, AdbError, ForegroundActivity
from .business import (
    BusinessError,
    INTEL_COMPLETED,
    INTEL_MISSING,
    INTEL_PENDING,
    IntelStatusSnapshot,
    build_claim_intel_lua,
    build_close_expedition_lua,
    build_commit_march_lua,
    build_inspect_intel_lua,
    build_intel_status_lua,
    build_march_ready_lua,
    build_open_march_lua,
    build_verify_march_lua,
    normalize_quality,
    normalize_target_ids,
    parse_claim_intel_output,
    parse_commit_output,
    parse_intel_output,
    parse_intel_status_output,
    parse_open_output,
    parse_ready_output,
    parse_verify_output,
    select_march_target,
    script_sha256,
    validate_role_whitelist,
)
from .config import ConfigError, DeviceProfile, Settings, load_settings
from .frida_driver import (
    FridaDriverError,
    FridaLuaClient,
    LuaExecutionError,
    LuaExecutionResult,
    ProcessInfo,
)
from .kingdom import KingdomGuard, KingdomGuardError, KingdomStatus
from .logging_utils import configure_logging
from .lua_safety import LuaSafetyError, require_safe_lua
from .lua_state import AdbLuaStateScanner, LuaStateCandidate, LuaStateScanError


LOGGER = logging.getLogger(__name__)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mumu-autotask",
        description="Inspect and drive MuMu game sessions through Frida and Lua.",
    )
    parser.add_argument("--config", default="config.json", help="JSON configuration file")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--log-file")
    parser.add_argument("--json-logs", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate configuration only")
    devices = subparsers.add_parser("devices", help="list ADB devices")
    devices.add_argument("--connect", action="store_true", help="connect configured targets first")

    status = subparsers.add_parser(
        "status", help="check ADB, kingdom, Frida, and the game process"
    )
    status_target = status.add_mutually_exclusive_group()
    status_target.add_argument("--serial")
    status_target.add_argument(
        "--all", action="store_true", help="check every configured device (default)"
    )

    exec_lua = subparsers.add_parser(
        "exec-lua", help="execute Lua through the in-process ARM64 bridge"
    )
    exec_lua.add_argument("--serial", required=True)
    source = exec_lua.add_mutually_exclusive_group(required=True)
    source.add_argument("--code", help="Lua source text")
    source.add_argument("--file", type=Path, help="UTF-8 Lua source file")
    exec_lua.add_argument(
        "--allow-unsafe-lua",
        action="store_true",
        help="explicitly authorize Lua outside the built-in read-only probes",
    )
    exec_lua.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="execute after all guards pass (default: validation-only dry-run)",
    )
    exec_lua.set_defaults(dry_run=True)

    inspect_intel = subparsers.add_parser(
        "inspect-intel",
        help="inspect skull intelligence through the in-process game state",
    )
    inspect_intel.add_argument("--serial", required=True)
    inspect_intel.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="run the read-only inspection after all guards pass",
    )
    inspect_intel.set_defaults(dry_run=True)

    wait_intel = subparsers.add_parser(
        "wait-intel",
        help="wait for exact intelligence runtime IDs to leave the pending state",
    )
    wait_intel.add_argument("--serial", required=True)
    wait_intel.add_argument(
        "--expected-role",
        required=True,
        help="lock every poll to the role that produced these runtime IDs",
    )
    wait_intel.add_argument(
        "--target-id",
        dest="target_ids",
        action="append",
        type=int,
        required=True,
        help="exact intelligence runtime ID (repeat for multiple targets)",
    )
    wait_intel.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="maximum wait time in seconds (default: 1800)",
    )
    wait_intel.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="seconds between guarded status polls (default: 2)",
    )
    wait_intel.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="run the read-only polling after all guards pass",
    )
    wait_intel.set_defaults(dry_run=True)

    claim_intel = subparsers.add_parser(
        "claim-intel",
        help="claim completed exact intelligence targets with one native request",
    )
    claim_intel.add_argument("--serial", required=True)
    claim_intel.add_argument(
        "--expected-role",
        required=True,
        help="lock precheck, claim, and verification to the originating role",
    )
    claim_intel.add_argument(
        "--target-id",
        dest="target_ids",
        action="append",
        type=int,
        required=True,
        help="exact intelligence runtime ID (repeat for multiple targets)",
    )
    claim_intel.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="maximum reward-removal verification time in seconds (default: 20)",
    )
    claim_intel.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between guarded verification polls (default: 0.5)",
    )
    claim_intel.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="send one native one-key claim request after all guards pass",
    )
    claim_intel.set_defaults(dry_run=True)

    march = subparsers.add_parser(
        "march",
        help="prepare a guarded average-formation march by skull quality",
    )
    march.add_argument("--serial", required=True)
    march.add_argument(
        "--expected-role",
        help="require this exact active role before target selection",
    )
    march.add_argument(
        "--quality",
        required=True,
        help=(
            "green/绿色, blue/蓝色, purple/紫色, yellow/黄色 "
            "(orange/橙色 is an alias for yellow)"
        ),
    )
    march.add_argument(
        "--target-id",
        type=int,
        help="require this exact intelligence runtime ID instead of choosing by quality",
    )
    march.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="average the formation and march after all guards pass",
    )
    march.set_defaults(dry_run=True)
    return parser


def _adb(settings: Settings) -> AdbClient:
    return AdbClient(
        settings.adb.executable,
        timeout_seconds=settings.adb.command_timeout_seconds,
    )


def _profiles(settings: Settings, serial: str | None) -> list[DeviceProfile]:
    profiles = [settings.device(serial)] if serial else list(settings.devices)
    if not profiles:
        raise ConfigError("no device profiles are configured")
    return profiles


def _polling_options(args: argparse.Namespace) -> tuple[float, float]:
    timeout = args.timeout
    poll_interval = args.poll_interval
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
        or timeout > 86400
    ):
        raise BusinessError("poll timeout must be between 0 and 86400 seconds")
    if (
        not isinstance(poll_interval, (int, float))
        or isinstance(poll_interval, bool)
        or not math.isfinite(poll_interval)
        or poll_interval < 0.05
        or poll_interval > 60
    ):
        raise BusinessError("poll interval must be between 0.05 and 60 seconds")
    return float(timeout), float(poll_interval)


def _operation_roles(
    profile: DeviceProfile,
    expected_role: str | None,
) -> tuple[str, ...]:
    configured_roles = validate_role_whitelist(profile.roles)
    if expected_role is None:
        return configured_roles
    if not isinstance(expected_role, str) or not expected_role:
        raise BusinessError("expected role must be non-empty text")
    if expected_role not in configured_roles:
        raise BusinessError(
            f"expected role {expected_role!r} is not in the device whitelist"
        )
    return (expected_role,)


def _lua_source(args: argparse.Namespace) -> str:
    if args.code is not None:
        return args.code
    try:
        return args.file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read Lua file {args.file}: {exc}") from exc


def _client(profile: DeviceProfile, *, pid: int | None = None) -> FridaLuaClient:
    return FridaLuaClient(
        profile.frida_host,
        process_name=profile.process_name,
        pid=pid if pid is not None else profile.pid,
        process_aliases=(profile.package_name,),
    )


def _adb_pid(adb: AdbClient, profile: DeviceProfile) -> int:
    pid = adb.pidof(profile.serial, profile.package_name)
    if profile.pid is not None and profile.pid != pid:
        raise FridaDriverError(
            f"{profile.serial}: configured PID {profile.pid} does not match "
            f"ADB PID {pid}"
        )
    return pid


def _foreground_activity(adb: AdbClient, profile: DeviceProfile) -> ForegroundActivity:
    return adb.foreground_activity(profile.serial)


def _require_game_foreground(
    adb: AdbClient,
    profile: DeviceProfile,
) -> ForegroundActivity:
    activity = _foreground_activity(adb, profile)
    if not activity.matches(profile.activity_name):
        current = activity.component or "none"
        raise FridaDriverError(
            f"{profile.serial}: game activity is not in foreground; "
            f"expected {profile.activity_name}, current {current}"
        )
    return activity


def _scanner(adb: AdbClient, profile: DeviceProfile) -> AdbLuaStateScanner:
    return AdbLuaStateScanner(adb, profile.serial)


def _base_payload(
    profile: DeviceProfile,
    kingdom: KingdomStatus,
    process: ProcessInfo,
    activity: ForegroundActivity,
) -> dict[str, Any]:
    return {
        "serial": profile.serial,
        "instance_name": profile.instance_name,
        "roles": list(profile.roles),
        "kingdom": kingdom.kingdom,
        "playerprefs_kingdom": kingdom.playerprefs_kingdom,
        "sdk_server_id": kingdom.sdk_server_id,
        "frida_host": profile.frida_host,
        "pid": process.pid,
        "process": process.name,
        "activity": activity.component,
        "activity_source": activity.source,
        "game_activity_foreground": activity.matches(profile.activity_name),
    }


def _verify_process_after_lua(
    adb: AdbClient,
    profile: DeviceProfile,
    scanner: AdbLuaStateScanner,
    process: ProcessInfo,
    state: LuaStateCandidate,
    operation: str,
) -> LuaStateCandidate:
    _require_game_foreground(adb, profile)
    after_pid = adb.pidof(profile.serial, profile.package_name)
    if after_pid != process.pid:
        raise FridaDriverError(
            f"{profile.serial}: game PID changed during {operation} "
            f"({process.pid} -> {after_pid})"
        )
    return scanner.verify_idle_main(process.pid, state.address)


def _verify_process_after_lua_finally(
    adb: AdbClient,
    profile: DeviceProfile,
    scanner: AdbLuaStateScanner,
    process: ProcessInfo,
    state: LuaStateCandidate,
    operation: str,
) -> LuaStateCandidate | None:
    original_error = sys.exc_info()[1]
    try:
        return _verify_process_after_lua(
            adb,
            profile,
            scanner,
            process,
            state,
            operation,
        )
    except Exception as final_error:
        if original_error is None:
            raise
        LOGGER.warning(
            "%s post-check failed after earlier error; preserving original error: %s",
            operation,
            final_error,
        )
        return None


def _execute_lua(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    code: str,
    *,
    output_capacity: int,
) -> tuple[
    LuaExecutionResult,
    dict[str, Any],
    LuaStateCandidate,
    LuaStateCandidate,
    LuaStateCandidate,
]:
    scanner = _scanner(adb, profile)
    state = scanner.find_unique_idle_main(process.pid)
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            result = client.execute_lua(
                before.address,
                code,
                output_capacity=output_capacity,
            )
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "Lua execution",
            )
    return result, initialization, state, before, after


def _execution_payload(
    initialization: dict[str, Any],
    state: LuaStateCandidate,
    before: LuaStateCandidate,
    after: LuaStateCandidate,
    result: LuaExecutionResult,
) -> dict[str, Any]:
    return {
        "bridge_arch": initialization.get("arch"),
        "lua_state": state.address_text,
        "lua_state_cframe_before": before.cframe,
        "lua_state_cframe_after": after.cframe,
        "result_code": result.result_code,
        "execution_thread_id": result.thread_id,
        "execution_thread_name": result.thread_name,
        "dry_run": False,
        "lua_executed": True,
    }


def _execute_march(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    quality: str,
    *,
    initial_roles: Sequence[str],
    target_runtime_id: int | None = None,
    dry_run: bool,
    output_capacity: int,
    ready_timeout_seconds: float = 10.0,
    verify_timeout_seconds: float = 15.0,
    verify_poll_interval_seconds: float = 0.2,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    inspect_code = build_inspect_intel_lua(locked_initial_roles)
    opened = False
    accepted = False
    status_after = "not-sent"
    verification_polls = 0
    stage_hashes: dict[str, str] = {
        "inspect": script_sha256(inspect_code),
    }
    last_result: LuaExecutionResult
    scanner = _scanner(adb, profile)
    state = scanner.find_unique_idle_main(process.pid)
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            inspect_result = client.execute_lua(
                before.address,
                inspect_code,
                output_capacity=output_capacity,
            )
            last_result = inspect_result
            snapshot = parse_intel_output(
                inspect_result.output,
                locked_initial_roles,
            )
            target = select_march_target(snapshot, quality, target_runtime_id)
            active_roles = (snapshot.role,)

            if not dry_run:
                if inspect_result.thread_name != "UnityMain":
                    raise BusinessError(
                        "已安全停止：当前直连模式不能使用旧的出征界面链路，"
                        "否则可能导致游戏卡死"
                    )
                open_code = build_open_march_lua(active_roles, target)
                ready_code = build_march_ready_lua(active_roles, target)
                commit_code = build_commit_march_lua(active_roles, target)
                verify_code = build_verify_march_lua(active_roles, target)
                stage_hashes.update(
                    {
                        "open": script_sha256(open_code),
                        "ready": script_sha256(ready_code),
                        "commit": script_sha256(commit_code),
                        "verify": script_sha256(verify_code),
                    }
                )
                open_result = client.execute_lua(
                    state.address,
                    open_code,
                    output_capacity=output_capacity,
                )
                opened = True
                parse_open_output(open_result.output, active_roles, target)

                ready_deadline = time.monotonic() + ready_timeout_seconds
                while True:
                    ready_result = client.execute_lua(
                        state.address,
                        ready_code,
                        output_capacity=output_capacity,
                    )
                    if parse_ready_output(ready_result.output, active_roles, target):
                        break
                    if time.monotonic() >= ready_deadline:
                        raise BusinessError(
                            "expedition view did not finish initializing before timeout"
                        )
                    time.sleep(0.2)

                commit_result = client.execute_lua(
                    state.address,
                    commit_code,
                    output_capacity=output_capacity,
                )
                parse_commit_output(commit_result.output, active_roles, target)
                last_result = commit_result

                verify_deadline = time.monotonic() + verify_timeout_seconds
                while True:
                    verify_result = client.execute_lua(
                        state.address,
                        verify_code,
                        output_capacity=output_capacity,
                    )
                    verification_polls += 1
                    accepted, status_after = parse_verify_output(
                        verify_result.output,
                        active_roles,
                        target,
                    )
                    if accepted:
                        break
                    if time.monotonic() >= verify_deadline:
                        raise BusinessError(
                            "go action was invoked but no matching server-created "
                            "self march or quest acceptance appeared before timeout "
                            f"for target {target.runtime_id}; last quest status was "
                            f"{status_after} after {verification_polls} polls"
                        )
                    time.sleep(verify_poll_interval_seconds)
        except Exception:
            if opened and not accepted:
                try:
                    close_code = build_close_expedition_lua(active_roles)
                    stage_hashes["cleanup"] = script_sha256(close_code)
                    client.execute_lua(
                        state.address,
                        close_code,
                        output_capacity=output_capacity,
                    )
                except Exception as cleanup_error:
                    LOGGER.warning("expedition cleanup failed: %s", cleanup_error)
            raise
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "march workflow",
            )

    result = _execution_payload(initialization, state, before, after, last_result)
    result.update(
        {
            "dry_run": dry_run,
            "march_executed": not dry_run,
            "request_dispatched": accepted,
            "quest_status_after": status_after,
            "verification_polls": verification_polls,
            "role": snapshot.role,
            "item_count": len(snapshot.items),
            "target": asdict(target),
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def _target_status_counts(snapshot: IntelStatusSnapshot) -> dict[str, int]:
    return {
        "pending": sum(
            target.state == INTEL_PENDING for target in snapshot.targets
        ),
        "completed": sum(
            target.state == INTEL_COMPLETED for target in snapshot.targets
        ),
        "missing": sum(
            target.state == INTEL_MISSING for target in snapshot.targets
        ),
    }


def _target_status_payload(snapshot: IntelStatusSnapshot) -> list[dict[str, Any]]:
    return [asdict(target) for target in snapshot.targets]


def _execute_wait_intel(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    target_ids: Sequence[int],
    *,
    initial_roles: Sequence[str],
    output_capacity: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    normalized_ids = normalize_target_ids(target_ids)
    locked_initial_roles = validate_role_whitelist(initial_roles)
    initial_code = build_intel_status_lua(locked_initial_roles, normalized_ids)
    stage_hashes = {"initial": script_sha256(initial_code)}
    scanner = _scanner(adb, profile)
    state = scanner.find_unique_idle_main(process.pid)
    deadline = time.monotonic() + timeout_seconds
    poll_count = 0
    locked_role: str | None = None
    snapshot: IntelStatusSnapshot | None = None
    last_result: LuaExecutionResult | None = None

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            while True:
                allowed_roles = (
                    locked_initial_roles if locked_role is None else (locked_role,)
                )
                code = build_intel_status_lua(allowed_roles, normalized_ids)
                result = client.execute_lua(
                    state.address,
                    code,
                    output_capacity=output_capacity,
                )
                poll_count += 1
                last_result = result
                snapshot = parse_intel_status_output(
                    result.output,
                    allowed_roles,
                    normalized_ids,
                )
                if locked_role is None:
                    locked_role = snapshot.role
                    locked_code = build_intel_status_lua(
                        (locked_role,),
                        normalized_ids,
                    )
                    stage_hashes["locked"] = script_sha256(locked_code)
                pending_ids = [
                    target.runtime_id
                    for target in snapshot.targets
                    if target.state == INTEL_PENDING
                ]
                if not pending_ids:
                    break
                now = time.monotonic()
                if now >= deadline:
                    joined = ", ".join(str(runtime_id) for runtime_id in pending_ids)
                    raise BusinessError(
                        f"wait-intel timed out with pending target ids: {joined}"
                    )
                time.sleep(min(poll_interval_seconds, deadline - now))
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "wait-intel",
            )

    if snapshot is None or last_result is None or locked_role is None:
        raise BusinessError("wait-intel produced no guarded status snapshot")
    result = _execution_payload(
        initialization,
        state,
        before,
        after,
        last_result,
    )
    result.update(
        {
            "role": locked_role,
            "target_ids": list(normalized_ids),
            "statuses": _target_status_payload(snapshot),
            "status_counts": _target_status_counts(snapshot),
            "poll_count": poll_count,
            "wait_completed": True,
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def _execute_claim_intel(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    target_ids: Sequence[int],
    *,
    initial_roles: Sequence[str],
    dry_run: bool,
    output_capacity: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    normalized_ids = normalize_target_ids(target_ids)
    locked_initial_roles = validate_role_whitelist(initial_roles)
    initial_code = build_intel_status_lua(locked_initial_roles, normalized_ids)
    stage_hashes = {"initial": script_sha256(initial_code)}
    scanner = _scanner(adb, profile)
    state = scanner.find_unique_idle_main(process.pid)
    request_dispatched = False
    idempotent = False
    claim_invoked = False
    verification_polls = 0

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            initial_result = client.execute_lua(
                before.address,
                initial_code,
                output_capacity=output_capacity,
            )
            last_result = initial_result
            before_snapshot = parse_intel_status_output(
                initial_result.output,
                locked_initial_roles,
                normalized_ids,
            )
            locked_role = before_snapshot.role
            active_roles = (locked_role,)
            status_code = build_intel_status_lua(active_roles, normalized_ids)
            claim_code = build_claim_intel_lua(active_roles, normalized_ids)
            stage_hashes.update(
                {
                    "locked_status": script_sha256(status_code),
                    "claim": script_sha256(claim_code),
                }
            )
            before_counts = _target_status_counts(before_snapshot)
            pending_ids = [
                target.runtime_id
                for target in before_snapshot.targets
                if target.state == INTEL_PENDING
            ]
            final_snapshot = before_snapshot
            idempotent = before_counts["missing"] == len(normalized_ids)

            if pending_ids and not dry_run:
                joined = ", ".join(str(runtime_id) for runtime_id in pending_ids)
                raise BusinessError(
                    f"cannot claim while target ids are pending: {joined}"
                )

            if not dry_run and not pending_ids and not idempotent:
                claim_result = client.execute_lua(
                    state.address,
                    claim_code,
                    output_capacity=output_capacity,
                )
                claim_invoked = True
                last_result = claim_result
                receipt = parse_claim_intel_output(
                    claim_result.output,
                    active_roles,
                    normalized_ids,
                )
                request_dispatched = receipt.request_dispatched
                idempotent = receipt.idempotent

                deadline = time.monotonic() + timeout_seconds
                while True:
                    verify_result = client.execute_lua(
                        state.address,
                        status_code,
                        output_capacity=output_capacity,
                    )
                    verification_polls += 1
                    last_result = verify_result
                    final_snapshot = parse_intel_status_output(
                        verify_result.output,
                        active_roles,
                        normalized_ids,
                    )
                    remaining = [
                        target.runtime_id
                        for target in final_snapshot.targets
                        if target.state != INTEL_MISSING
                    ]
                    if not remaining:
                        break
                    now = time.monotonic()
                    if now >= deadline:
                        joined = ", ".join(
                            str(runtime_id) for runtime_id in remaining
                        )
                        raise BusinessError(
                            "claim request was issued but target ids did not "
                            f"disappear before timeout: {joined}"
                        )
                    time.sleep(min(poll_interval_seconds, deadline - now))
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "claim-intel",
            )

    result = _execution_payload(
        initialization,
        state,
        before,
        after,
        last_result,
    )
    final_counts = _target_status_counts(final_snapshot)
    result.update(
        {
            "dry_run": dry_run,
            "role": locked_role,
            "target_ids": list(normalized_ids),
            "statuses_before": _target_status_payload(before_snapshot),
            "statuses_after": _target_status_payload(final_snapshot),
            "status_counts_before": before_counts,
            "status_counts_after": final_counts,
            "claim_allowed": not pending_ids,
            "would_dispatch": not pending_ids and before_counts["completed"] > 0,
            "claim_invoked": claim_invoked,
            "request_dispatched": request_dispatched,
            "idempotent": idempotent,
            "verified_missing": final_counts["missing"] == len(normalized_ids),
            "verification_polls": verification_polls,
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def execute(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "validate":
        for profile in settings.devices:
            validate_role_whitelist(profile.roles)
        print(f"configuration is valid: {Path(args.config).resolve()}")
        return 0

    if args.command == "devices":
        adb = _adb(settings)
        devices = (
            adb.connect_configured(settings.adb.connect_targets)
            if args.connect
            else adb.devices()
        )
        for device in devices:
            model = device.details.get("model", "-")
            print(f"{device.serial}\t{device.state}\t{model}")
        return 0

    if args.command == "status":
        profiles = _profiles(settings, args.serial)
        for profile in profiles:
            validate_role_whitelist(profile.roles)
        adb = _adb(settings)
        adb.require_connected([profile.serial for profile in profiles])
        guard = KingdomGuard(adb)
        for profile in profiles:
            kingdom = guard.require(profile)
            activity = _foreground_activity(adb, profile)
            adb_pid = _adb_pid(adb, profile)
            process = (
                _client(profile, pid=adb_pid).inspect_process()
                if activity.matches(profile.activity_name)
                else ProcessInfo(adb_pid, "-")
            )
            print(
                json.dumps(
                    {
                        "serial": profile.serial,
                        "instance_name": profile.instance_name,
                        "roles": list(profile.roles),
                        "adb": "device",
                        "kingdom": kingdom.kingdom,
                        "playerprefs_kingdom": kingdom.playerprefs_kingdom,
                        "sdk_server_id": kingdom.sdk_server_id,
                        "frida_host": profile.frida_host,
                        "pid": process.pid,
                        "process": process.name,
                        "activity": activity.component,
                        "activity_source": activity.source,
                        "game_activity_foreground": activity.matches(profile.activity_name),
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    profile = settings.device(args.serial)
    expected_role = getattr(args, "expected_role", None)
    operation_roles = (
        _operation_roles(profile, expected_role)
        if args.command in {"inspect-intel", "wait-intel", "claim-intel", "march"}
        else tuple(profile.roles)
    )
    quality: str | None = None
    target_runtime_id: int | None = None
    target_ids: tuple[int, ...] | None = None
    timeout_seconds: float | None = None
    poll_interval_seconds: float | None = None
    if args.command == "exec-lua":
        code = _lua_source(args)
        require_safe_lua(code, allow_unsafe=args.allow_unsafe_lua)
    elif args.command == "inspect-intel":
        code = build_inspect_intel_lua(operation_roles)
    elif args.command in {"wait-intel", "claim-intel"}:
        target_ids = normalize_target_ids(args.target_ids)
        timeout_seconds, poll_interval_seconds = _polling_options(args)
        code = build_intel_status_lua(operation_roles, target_ids)
    elif args.command == "march":
        quality = normalize_quality(args.quality)
        target_runtime_id = getattr(args, "target_id", None)
        if target_runtime_id is not None and target_runtime_id <= 0:
            raise BusinessError("march target runtime id must be a positive integer")
        code = build_inspect_intel_lua(operation_roles)
    else:
        raise ConfigError(f"unsupported command {args.command!r}")

    adb = _adb(settings)
    adb.require_connected([profile.serial])
    kingdom = KingdomGuard(adb).require(profile)
    activity = _require_game_foreground(adb, profile)
    adb_pid = _adb_pid(adb, profile)
    client = _client(profile, pid=adb_pid)
    process = client.inspect_process()
    payload = _base_payload(profile, kingdom, process, activity)
    payload.update(
        {
            "operation": args.command,
            "script_sha256": script_sha256(code),
        }
    )
    if quality is not None:
        payload["quality"] = quality
    if target_runtime_id is not None:
        payload["requested_target_id"] = target_runtime_id
    if target_ids is not None:
        payload["requested_target_ids"] = list(target_ids)
    if expected_role is not None:
        payload["expected_role"] = expected_role

    if args.dry_run and args.command not in {"march", "claim-intel"}:
        payload.update({"dry_run": True, "lua_executed": False})
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "march":
        payload.update(
            _execute_march(
                adb,
                profile,
                client,
                process,
                quality,
                initial_roles=operation_roles,
                target_runtime_id=target_runtime_id,
                dry_run=args.dry_run,
                output_capacity=settings.frida.output_capacity,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "wait-intel":
        assert target_ids is not None
        assert timeout_seconds is not None
        assert poll_interval_seconds is not None
        payload.update(
            _execute_wait_intel(
                adb,
                profile,
                client,
                process,
                target_ids,
                initial_roles=operation_roles,
                output_capacity=settings.frida.output_capacity,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "claim-intel":
        assert target_ids is not None
        assert timeout_seconds is not None
        assert poll_interval_seconds is not None
        payload.update(
            _execute_claim_intel(
                adb,
                profile,
                client,
                process,
                target_ids,
                initial_roles=operation_roles,
                dry_run=args.dry_run,
                output_capacity=settings.frida.output_capacity,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    result, initialization, state, before, after = _execute_lua(
        adb,
        profile,
        client,
        process,
        code,
        output_capacity=settings.frida.output_capacity,
    )
    payload.update(_execution_payload(initialization, state, before, after, result))
    if args.command == "inspect-intel":
        snapshot = parse_intel_output(result.output, profile.roles)
        payload.update(
            {
                "role": snapshot.role,
                "item_count": len(snapshot.items),
                "items": [asdict(item) for item in snapshot.items],
            }
        )
    else:
        payload["output"] = result.output
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(
        verbose=args.verbose,
        log_file=args.log_file,
        json_format=args.json_logs,
    )
    try:
        settings = load_settings(args.config)
        return execute(args, settings)
    except (
        AdbError,
        BusinessError,
        ConfigError,
        FridaDriverError,
        KingdomGuardError,
        LuaExecutionError,
        LuaSafetyError,
        LuaStateScanError,
    ) as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        LOGGER.warning("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
