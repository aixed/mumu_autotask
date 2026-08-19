from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adb import AdbClient, AdbError, ForegroundActivity
from .business import (
    BattleIntelItem,
    BusinessError,
    INTEL_COMPLETED,
    INTEL_MISSING,
    INTEL_PENDING,
    IntelItem,
    IntelStatusSnapshot,
    SceneStatus,
    build_claim_intel_lua,
    build_commit_prepared_march_lua,
    build_install_march_capture_hook_lua,
    build_inspect_battle_intel_lua,
    build_inspect_formation_lua,
    build_inspect_intel_lua,
    build_intel_status_lua,
    build_prepare_direct_march_lua,
    build_read_march_capture_hook_lua,
    build_scene_status_lua,
    build_start_battle_intel_lua,
    build_start_rescue_intel_lua,
    build_uninstall_march_capture_hook_lua,
    build_verify_battle_intel_lua,
    build_verify_march_lua,
    build_world_monster_commit_lua,
    build_world_monster_search_lua,
    build_world_monster_search_result_lua,
    build_world_monster_status_lua,
    build_world_monster_verify_lua,
    normalize_battle_category,
    normalize_quality,
    normalize_target_ids,
    normalize_world_monster_level,
    normalize_world_monster_count,
    normalize_world_monster_march_ids,
    parse_battle_commit_output,
    parse_battle_intel_output,
    parse_battle_verify_output,
    parse_claim_intel_output,
    parse_commit_output,
    parse_intel_output,
    parse_intel_status_output,
    parse_prepare_output,
    parse_rescue_commit_output,
    parse_scene_status_output,
    parse_verify_output,
    parse_world_monster_commit_output,
    parse_world_monster_search_output,
    parse_world_monster_search_sent_output,
    parse_world_monster_status_output,
    parse_world_monster_verify_output,
    select_battle_target,
    select_march_target,
    script_sha256,
    validate_role_whitelist,
)
from .config import ConfigError, DeviceProfile, Settings, load_settings
from .frida_driver import (
    FridaDriverError,
    FridaLuaClient,
    FridaServerRecovery,
    LuaExecutionError,
    LuaExecutionResult,
    ProcessInfo,
)
from .kingdom import KingdomGuard, KingdomGuardError, KingdomStatus
from .logging_utils import configure_logging
from .lua_safety import LuaSafetyError, require_safe_lua
from .lua_state import AdbLuaStateScanner, LuaStateCandidate, LuaStateScanError
from .mumu_manager import (
    MumuManagerError,
    discover_profile_for_serial,
    discover_running_mumu_profiles,
)


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
    status.add_argument(
        "--prepare-frida",
        action="store_true",
        help=(
            "when the game is foreground, recover Frida if needed and attach once "
            "to initialize the native bridge"
        ),
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

    inspect_battle = subparsers.add_parser(
        "inspect-battle-intel",
        help="inspect hero journey or rescue survivor intelligence",
    )
    inspect_battle.add_argument("--serial", required=True)
    inspect_battle.add_argument(
        "--category",
        required=True,
        help="hero/英雄之旅 or rescue/营救幸存者",
    )
    inspect_battle.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="run the read-only inspection after all guards pass",
    )
    inspect_battle.set_defaults(dry_run=True)

    inspect_tasks = subparsers.add_parser(
        "inspect-tasks",
        help="inspect monster, hero journey, and rescue intelligence in one session",
    )
    inspect_tasks.add_argument("--serial", required=True)
    inspect_tasks.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="run the read-only inspection after all guards pass",
    )
    inspect_tasks.set_defaults(dry_run=True)

    ensure_world = subparsers.add_parser(
        "ensure-world",
        help="ensure the game is on the outdoor world map",
    )
    ensure_world.add_argument("--serial", required=True)
    ensure_world.add_argument(
        "--expected-role",
        help="require this exact active role before tapping the world button",
    )
    ensure_world.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="maximum time in seconds to wait for WorldScene (default: 12)",
    )
    ensure_world.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between scene polls (default: 0.5)",
    )
    ensure_world.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="tap the lower-right world button when the current scene is not WorldScene",
    )
    ensure_world.set_defaults(dry_run=True)

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
        "--return-on-any",
        action="store_true",
        help="return as soon as at least one exact target leaves the pending state",
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

    battle = subparsers.add_parser(
        "battle-intel",
        help="run a guarded hero journey or rescue survivor intelligence battle",
    )
    battle.add_argument("--serial", required=True)
    battle.add_argument(
        "--expected-role",
        help="require this exact active role before target selection",
    )
    battle.add_argument(
        "--category",
        required=True,
        help="hero/英雄之旅 or rescue/营救幸存者",
    )
    battle.add_argument(
        "--target-id",
        type=int,
        help="require this exact intelligence runtime ID instead of choosing by category",
    )
    battle.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="send native battle requests after all guards pass",
    )
    battle.set_defaults(dry_run=True)

    batch_intel = subparsers.add_parser(
        "batch-intel",
        help="dispatch one GUI intelligence wave through a single guarded Frida session",
    )
    batch_intel.add_argument("--serial", required=True)
    batch_intel.add_argument(
        "--expected-role",
        help="require this exact active role before batch target selection",
    )
    batch_intel.add_argument(
        "--target",
        dest="batch_targets",
        action="append",
        help=(
            "exact target spec; use monster:<runtime_id>:<quality>, "
            "hero:<runtime_id>, or rescue:<runtime_id>"
        ),
    )
    batch_intel.add_argument(
        "--target-json",
        dest="batch_target_json",
        action="append",
        help=(
            "exact JSON target copied from inspect-tasks; this avoids "
            "re-reading intelligence before dispatch"
        ),
    )
    batch_intel.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="dispatch every target in one guarded Frida session",
    )
    batch_intel.set_defaults(dry_run=True)

    formation = subparsers.add_parser(
        "inspect-formation",
        help="compute a read-only average-formation payload by skull quality",
    )
    formation.add_argument("--serial", required=True)
    formation.add_argument(
        "--expected-role",
        help="require this exact active role before target selection",
    )
    formation.add_argument(
        "--quality",
        required=True,
        help=(
            "green/绿色, blue/蓝色, purple/紫色, yellow/黄色 "
            "(orange/橙色 is an alias for yellow)"
        ),
    )
    formation.add_argument(
        "--target-id",
        type=int,
        help="require this exact intelligence runtime ID instead of choosing by quality",
    )
    formation.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="run the read-only formation inspection after all guards pass",
    )
    formation.set_defaults(dry_run=True)

    capture_march = subparsers.add_parser(
        "capture-march",
        help="install a temporary hook and capture one real UI march payload",
    )
    capture_march.add_argument("--serial", required=True)
    capture_march.add_argument(
        "--expected-role",
        help="require this exact active role before installing the hook",
    )
    capture_march.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="maximum time in seconds to wait for the real UI click (default: 90)",
    )
    capture_march.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between hook-record polls (default: 0.5)",
    )
    capture_march.add_argument(
        "--output-file",
        type=Path,
        help="optional UTF-8 file to save the raw captured hook records",
    )
    capture_march.add_argument(
        "--keep-hook",
        action="store_true",
        help=(
            "leave the march capture hook installed after capture; "
            "use unhook-march-capture to restore it later"
        ),
    )
    capture_march.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="install the temporary hook after all guards pass",
    )
    capture_march.set_defaults(dry_run=True)

    unhook_march = subparsers.add_parser(
        "unhook-march-capture",
        help="restore methods wrapped by capture-march --keep-hook",
    )
    unhook_march.add_argument("--serial", required=True)
    unhook_march.add_argument(
        "--expected-role",
        help="require this exact active role before uninstalling the hook",
    )
    unhook_march.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="uninstall the march capture hook after all guards pass",
    )
    unhook_march.set_defaults(dry_run=True)

    hunt_world_monster = subparsers.add_parser(
        "hunt-world-monster",
        help="search and attack one normal world monster through native Lua APIs",
    )
    hunt_world_monster.add_argument("--serial", required=True)
    hunt_world_monster.add_argument(
        "--level",
        required=True,
        type=int,
        help="normal world monster level (1-20)",
    )
    hunt_world_monster.add_argument(
        "--count",
        type=int,
        default=1,
        help="number of monsters to search and dispatch sequentially (1-4; default: 1)",
    )
    hunt_world_monster.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="maximum search/march verification time in seconds (default: 15)",
    )
    hunt_world_monster.add_argument(
        "--poll-interval",
        type=float,
        default=0.2,
        help="seconds between native-state verification polls (default: 0.2)",
    )
    hunt_world_monster.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="search, average the formation, and dispatch after all guards pass",
    )
    hunt_world_monster.set_defaults(dry_run=True)

    world_monster_loop = subparsers.add_parser(
        "world-monster-loop",
        help="continuously keep normal world monster marches filled in one Frida session",
    )
    world_monster_loop.add_argument("--serial", required=True)
    world_monster_loop.add_argument(
        "--level",
        required=True,
        type=int,
        help="normal world monster level (1-20)",
    )
    world_monster_loop.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="maximum active world monster marches (1-4; default: 4)",
    )
    world_monster_loop.add_argument(
        "--poll-interval",
        type=float,
        default=1.5,
        help="seconds between active-march polls (default: 1.5)",
    )
    world_monster_loop.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="hold one Frida session and continuously refill returned marches",
    )
    world_monster_loop.set_defaults(dry_run=True)

    world_monster_status = subparsers.add_parser(
        "world-monster-status",
        help="read ACTIVE/RETURNED state for verified world monster marches",
    )
    world_monster_status.add_argument("--serial", required=True)
    world_monster_status.add_argument(
        "--march-id",
        dest="march_ids",
        action="append",
        required=True,
        type=int,
        help="verified world monster march ID (repeat for multiple marches)",
    )
    world_monster_status.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="read live march and stamina state",
    )
    world_monster_status.set_defaults(dry_run=True)
    return parser


def _adb(settings: Settings) -> AdbClient:
    return AdbClient(
        settings.adb.executable,
        timeout_seconds=settings.adb.command_timeout_seconds,
    )


def _profiles(settings: Settings, serial: str | None) -> list[DeviceProfile]:
    if serial:
        try:
            profiles = [settings.device(serial)]
        except ConfigError:
            profiles = [discover_profile_for_serial(settings, serial)]
    else:
        discovered = discover_running_mumu_profiles(settings, connect_adb=True)
        profiles = list(discovered or settings.devices)
    if not profiles:
        raise ConfigError("no device profiles are configured")
    return profiles


def _profile(settings: Settings, serial: str) -> DeviceProfile:
    try:
        return settings.device(serial)
    except ConfigError:
        try:
            return discover_profile_for_serial(settings, serial)
        except MumuManagerError as exc:
            raise ConfigError(str(exc)) from exc


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


def _parse_positive_id(value: str, label: str) -> int:
    try:
        runtime_id = int(value)
    except ValueError as exc:
        raise BusinessError(f"{label} must be a positive integer") from exc
    if runtime_id <= 0:
        raise BusinessError(f"{label} must be a positive integer")
    return runtime_id


def _normalize_batch_target_mapping(
    value: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    category_value = value.get("category", "monster")
    if not isinstance(category_value, str):
        raise BusinessError(f"{label} category must be text")
    category = category_value.strip().lower()
    if category == "monster":
        normalized_category = "monster"
    else:
        normalized_category = normalize_battle_category(category)
    runtime_id = value.get("runtime_id")
    if (
        isinstance(runtime_id, bool)
        or not isinstance(runtime_id, int)
        or runtime_id <= 0
    ):
        raise BusinessError(f"{label} runtime id must be a positive integer")
    item = dict(value)
    item["category"] = normalized_category
    item["runtime_id"] = runtime_id
    if normalized_category == "monster":
        quality = value.get("quality")
        if not isinstance(quality, str):
            raise BusinessError(f"{label} monster target must include quality")
        item["quality"] = normalize_quality(quality)
    return item


def _parse_batch_target_json_specs(specs: Sequence[str]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        if not isinstance(spec, str) or not spec.strip():
            raise BusinessError(f"batch target json {index} is empty")
        try:
            raw = json.loads(spec)
        except json.JSONDecodeError as exc:
            raise BusinessError(
                f"batch target json {index} is not valid JSON"
            ) from exc
        if not isinstance(raw, Mapping):
            raise BusinessError(f"batch target json {index} must be an object")
        parsed.append(_normalize_batch_target_mapping(raw, f"batch target json {index}"))
    return parsed


def _parse_batch_target_specs(
    specs: Sequence[str],
    json_specs: Sequence[str] = (),
) -> tuple[dict[str, Any], ...]:
    if not specs and not json_specs:
        raise BusinessError("batch-intel requires at least one target")
    parsed: list[dict[str, Any]] = _parse_batch_target_json_specs(json_specs)
    seen: set[int] = set()
    for item in parsed:
        seen.add(int(item["runtime_id"]))
    for index, spec in enumerate(specs, start=1):
        if not isinstance(spec, str) or not spec.strip():
            raise BusinessError(f"batch target {index} is empty")
        parts = spec.strip().split(":")
        category = parts[0].strip().lower()
        if category == "monster":
            if len(parts) != 3:
                raise BusinessError(
                    "monster batch target must use monster:<runtime_id>:<quality>"
                )
            runtime_id = _parse_positive_id(parts[1], "monster runtime id")
            quality = normalize_quality(parts[2])
            item = {
                "category": "monster",
                "runtime_id": runtime_id,
                "quality": quality,
            }
        else:
            category = normalize_battle_category(category)
            if len(parts) != 2:
                raise BusinessError(
                    f"{category} batch target must use {category}:<runtime_id>"
                )
            runtime_id = _parse_positive_id(parts[1], f"{category} runtime id")
            item = {
                "category": category,
                "runtime_id": runtime_id,
            }
        if runtime_id in seen:
            raise BusinessError("batch target runtime ids must be unique")
        seen.add(runtime_id)
        parsed.append(item)
    return tuple(parsed)


def _spec_integer(
    spec: Mapping[str, Any],
    key: str,
    *,
    allow_zero: bool = False,
) -> int:
    value = spec.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or (not allow_zero and value == 0)
    ):
        expectation = "non-negative" if allow_zero else "positive"
        raise BusinessError(f"batch target field {key!r} must be a {expectation} integer")
    return value


def _full_target_from_batch_spec(
    spec: Mapping[str, Any],
) -> tuple[dict[str, Any], IntelItem | BattleIntelItem] | None:
    category = str(spec.get("category", "monster"))
    if category == "monster":
        required = {
            "runtime_id",
            "quest_id",
            "status",
            "world_x",
            "world_y",
            "expires_at",
            "quality",
            "quality_id",
            "monster_id",
            "level",
            "stamina_cost",
            "recommended_power",
        }
        if not required.issubset(spec):
            return None
        target = IntelItem(
            runtime_id=_spec_integer(spec, "runtime_id"),
            quest_id=_spec_integer(spec, "quest_id"),
            status=_spec_integer(spec, "status", allow_zero=True),
            world_x=_spec_integer(spec, "world_x", allow_zero=True),
            world_y=_spec_integer(spec, "world_y", allow_zero=True),
            expires_at=_spec_integer(spec, "expires_at"),
            quality=normalize_quality(str(spec["quality"])),
            quality_id=_spec_integer(spec, "quality_id"),
            monster_id=_spec_integer(spec, "monster_id"),
            level=_spec_integer(spec, "level", allow_zero=True),
            stamina_cost=_spec_integer(spec, "stamina_cost", allow_zero=True),
            recommended_power=_spec_integer(spec, "recommended_power"),
        )
        return dict(spec), target
    required = {
        "runtime_id",
        "quest_id",
        "status",
        "world_x",
        "world_y",
        "expires_at",
        "category",
        "quest_type",
        "quality",
        "quality_id",
        "condition",
        "level",
        "stamina_cost",
        "power_level",
    }
    if not required.issubset(spec):
        return None
    normalized_category = normalize_battle_category(category)
    target = BattleIntelItem(
        runtime_id=_spec_integer(spec, "runtime_id"),
        quest_id=_spec_integer(spec, "quest_id"),
        status=_spec_integer(spec, "status", allow_zero=True),
        world_x=_spec_integer(spec, "world_x", allow_zero=True),
        world_y=_spec_integer(spec, "world_y", allow_zero=True),
        expires_at=_spec_integer(spec, "expires_at"),
        category=normalized_category,
        quest_type=_spec_integer(spec, "quest_type"),
        quality=normalize_quality(str(spec["quality"])),
        quality_id=_spec_integer(spec, "quality_id"),
        condition=_spec_integer(spec, "condition", allow_zero=True),
        level=_spec_integer(spec, "level", allow_zero=True),
        stamina_cost=_spec_integer(spec, "stamina_cost", allow_zero=True),
        power_level=_spec_integer(spec, "power_level", allow_zero=True),
    )
    copied = dict(spec)
    copied["category"] = normalized_category
    return copied, target


def _full_targets_from_batch_specs(
    specs: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], IntelItem | BattleIntelItem]] | None:
    targets: list[tuple[dict[str, Any], IntelItem | BattleIntelItem]] = []
    for spec in specs:
        target = _full_target_from_batch_spec(spec)
        if target is None:
            return None
        targets.append(target)
    return targets


def _operation_roles(
    profile: DeviceProfile,
    expected_role: str | None,
) -> tuple[str, ...]:
    configured_roles = validate_role_whitelist(profile.roles)
    if expected_role is None:
        return configured_roles
    if not isinstance(expected_role, str) or not expected_role:
        raise BusinessError("expected role must be non-empty text")
    if configured_roles and expected_role not in configured_roles:
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


def _client(
    profile: DeviceProfile,
    *,
    pid: int | None = None,
    adb: AdbClient | None = None,
) -> FridaLuaClient:
    return FridaLuaClient(
        profile.frida_host,
        process_name=profile.process_name,
        pid=pid if pid is not None else profile.pid,
        process_aliases=(profile.package_name,),
        server_recovery=(
            FridaServerRecovery(profile.frida_host, adb=adb)
            if adb is not None
            else None
        ),
    )


def _should_manage_frida_forward(profile: DeviceProfile) -> bool:
    host = profile.frida_host.rpartition(":")[0].strip().lower()
    return host in {"127.0.0.1", "localhost"}


def _ensure_frida_forward(adb: AdbClient, profile: DeviceProfile) -> bool:
    if not _should_manage_frida_forward(profile):
        return False
    local = f"tcp:{profile.frida_local_port}"
    remote = f"tcp:{profile.frida_remote_port}"
    forwards = adb.forward_list()
    matches = [forward for forward in forwards if forward.local == local]
    for forward in matches:
        if forward.serial != profile.serial:
            raise AdbError(
                f"Frida local port {local} is already forwarded by "
                f"{forward.serial}, not {profile.serial}"
            )
    if any(forward.remote == remote for forward in matches):
        return False
    if matches:
        adb.forward_remove(profile.serial, local)
    adb.forward(profile.serial, local, remote)
    return True


def _bundled_bridge_path() -> Path:
    return Path(__file__).resolve().parents[2] / "tools" / "bin" / "libmumu_bridge.so"


def _ensure_bridge_binary(adb: AdbClient, profile: DeviceProfile) -> bool:
    """Install the bridge library for a newly discovered or reset emulator."""

    try:
        adb.shell(profile.serial, "test", "-r", profile.bridge_remote_path)
        return False
    except (AdbError, OSError):
        local_path = _bundled_bridge_path()
        if not local_path.is_file():
            raise FridaDriverError(
                "game bridge is missing on the device and the bundled runtime "
                f"asset was not found: {local_path}"
            )
        try:
            adb.push(local_path, profile.bridge_remote_path)
            adb.shell(
                profile.serial,
                "su",
                "0",
                "chmod",
                "644",
                profile.bridge_remote_path,
            )
        except (AdbError, OSError) as exc:
            raise FridaDriverError(
                f"cannot install game bridge on {profile.serial}: {exc}"
            ) from exc
        return True


def _ensure_frida_forwards(
    adb: AdbClient,
    profiles: Sequence[DeviceProfile],
) -> dict[str, bool]:
    return {
        profile.serial: _ensure_frida_forward(adb, profile)
        for profile in profiles
    }


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
    try:
        return scanner.verify_idle_main_once(process.pid, state.address)
    except LuaStateScanError as exc:
        LOGGER.info(
            "%s Lua state %s no longer validates after execution; rescanning "
            "the unchanged game process once",
            operation,
            state.address_text,
        )
        try:
            relocated = scanner.find_unique_idle_main(process.pid)
        except LuaStateScanError:
            raise exc
        if relocated.address != state.address:
            LOGGER.info(
                "%s Lua state moved after execution: %s -> %s",
                operation,
                state.address_text,
                relocated.address_text,
            )
        return relocated


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
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "Lua state initialization",
    )
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = _wait_idle_lua_state(scanner, process, state)
        try:
            result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                code,
                output_capacity=output_capacity,
                operation="Lua execution",
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


def _scene_status_payload(status: SceneStatus) -> dict[str, Any]:
    return {
        "role": status.role,
        "scene": {
            "type": status.scene_type,
            "map_type": status.map_type,
            "class": status.class_name,
            "is_world": status.is_world,
            "is_city": status.is_city,
            "loading": status.loading,
            "transition": status.transition,
        },
    }


def _scene_world_ready(status: SceneStatus) -> bool:
    return status.is_world and status.loading is not True and status.transition is not True


def _world_button_tap_coordinates(adb: AdbClient, profile: DeviceProfile) -> tuple[int, int]:
    return _scaled_tap_coordinates(adb, profile, 0.906, 0.948, (652, 1214))


def _scaled_tap_coordinates(
    adb: AdbClient,
    profile: DeviceProfile,
    x_ratio: float,
    y_ratio: float,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    try:
        size = adb.window_size(profile.serial)
        x = int(size.width * x_ratio)
        y = int(size.height * y_ratio)
        return (
            max(0, min(size.width - 1, x)),
            max(0, min(size.height - 1, y)),
        )
    except Exception as exc:
        LOGGER.warning("could not read window size for %s: %s", profile.serial, exc)
        return fallback


def _require_same_foreground_process(
    adb: AdbClient,
    profile: DeviceProfile,
    process: ProcessInfo,
    operation: str,
) -> None:
    _require_game_foreground(adb, profile)
    after_pid = adb.pidof(profile.serial, profile.package_name)
    if after_pid != process.pid:
        raise FridaDriverError(
            f"{profile.serial}: game PID changed during {operation} "
            f"({process.pid} -> {after_pid})"
        )


def _wait_idle_lua_state(
    scanner: AdbLuaStateScanner,
    process: ProcessInfo,
    state: LuaStateCandidate,
    *,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.05,
) -> LuaStateCandidate:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while True:
        try:
            return scanner.verify_idle_main(process.pid, state.address)
        except LuaStateScanError as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll_interval_seconds)


def _wait_unique_idle_lua_state(
    adb: AdbClient,
    profile: DeviceProfile,
    scanner: AdbLuaStateScanner,
    process: ProcessInfo,
    operation: str,
    *,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.5,
) -> LuaStateCandidate:
    deadline = time.monotonic() + timeout_seconds
    first_attempt = True
    while True:
        if not first_attempt:
            _require_same_foreground_process(adb, profile, process, operation)
        first_attempt = False
        try:
            return scanner.find_unique_idle_main(process.pid)
        except LuaStateScanError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll_interval_seconds)


def _transient_bridge_fault(error: Exception) -> bool:
    text = str(error)
    return "breakpoint triggered" in text


def _execute_lua_when_idle(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    scanner: AdbLuaStateScanner,
    state: LuaStateCandidate,
    code: str,
    *,
    output_capacity: int,
    operation: str,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.05,
) -> LuaExecutionResult:
    deadline = time.monotonic() + timeout_seconds
    while True:
        _require_same_foreground_process(adb, profile, process, operation)
        _wait_idle_lua_state(
            scanner,
            process,
            state,
            timeout_seconds=max(0.05, min(1.0, timeout_seconds)),
            poll_interval_seconds=poll_interval_seconds,
        )
        try:
            return client.execute_lua(
                state.address,
                code,
                output_capacity=output_capacity,
            )
        except FridaDriverError as exc:
            if not _transient_bridge_fault(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(poll_interval_seconds)


def _execute_ensure_world(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    *,
    initial_roles: Sequence[str],
    dry_run: bool,
    output_capacity: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    code = build_scene_status_lua(locked_initial_roles)
    stage_hashes = {"scene": script_sha256(code)}
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "scene status initialization",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    final_status: SceneStatus | None = None
    initial_status: SceneStatus | None = None
    tapped = False
    tap_coordinates: tuple[int, int] | None = None
    poll_count = 0

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            first_deadline = time.monotonic() + timeout_seconds
            last_scene_error: Exception | None = None
            while True:
                try:
                    first_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        code,
                        output_capacity=output_capacity,
                        operation="scene status",
                        timeout_seconds=1.5,
                    )
                    last_result = first_result
                    initial_status = parse_scene_status_output(
                        first_result.output,
                        locked_initial_roles,
                    )
                    break
                except LuaExecutionError as exc:
                    last_scene_error = exc
                    if dry_run or time.monotonic() >= first_deadline:
                        raise BusinessError(
                            "game scene state was not ready before timeout; "
                            f"last error: {exc}"
                        ) from exc
                    time.sleep(poll_interval_seconds)
                    _require_same_foreground_process(
                        adb,
                        profile,
                        process,
                        "scene initialization wait",
                    )
            final_status = initial_status
            active_roles = (initial_status.role,)
            if not dry_run and not _scene_world_ready(initial_status):
                if not initial_status.is_world:
                    tap_coordinates = _world_button_tap_coordinates(adb, profile)
                    adb.input_tap(profile.serial, *tap_coordinates)
                    tapped = True
                deadline = time.monotonic() + timeout_seconds
                while True:
                    time.sleep(poll_interval_seconds)
                    _require_game_foreground(adb, profile)
                    after_pid = adb.pidof(profile.serial, profile.package_name)
                    if after_pid != process.pid:
                        raise FridaDriverError(
                            f"{profile.serial}: game PID changed while switching "
                            f"to world ({process.pid} -> {after_pid})"
                        )
                    try:
                        poll_result = _execute_lua_when_idle(
                            adb,
                            profile,
                            client,
                            process,
                            scanner,
                            state,
                            build_scene_status_lua(active_roles),
                            output_capacity=output_capacity,
                            operation="scene status poll",
                            timeout_seconds=1.5,
                        )
                        last_result = poll_result
                        poll_count += 1
                        final_status = parse_scene_status_output(
                            poll_result.output,
                            active_roles,
                        )
                    except LuaExecutionError as exc:
                        last_scene_error = exc
                    if _scene_world_ready(final_status):
                        break
                    if time.monotonic() >= deadline:
                        detail = (
                            f"; last error: {last_scene_error}"
                            if last_scene_error is not None
                            else ""
                        )
                        raise BusinessError(
                            "WorldScene did not become ready "
                            f"before timeout; current scene is "
                            f"{final_status.class_name}{detail}"
                        )
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "ensure-world",
            )

    if initial_status is None or final_status is None:
        raise BusinessError("ensure-world produced no scene status")
    result = _execution_payload(initialization, state, before, after, last_result)
    result.update(
        {
            "dry_run": dry_run,
            "world_ready": _scene_world_ready(final_status),
            "tap_invoked": tapped,
            "tap_coordinates": list(tap_coordinates) if tap_coordinates else None,
            "poll_count": poll_count,
            "scene_before": _scene_status_payload(initial_status)["scene"],
            "scene_after": _scene_status_payload(final_status)["scene"],
            "role": final_status.role,
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def _execute_inspect_formation(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    quality: str,
    *,
    initial_roles: Sequence[str],
    target_runtime_id: int | None = None,
    output_capacity: int,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    inspect_code = build_inspect_intel_lua(locked_initial_roles)
    stage_hashes: dict[str, str] = {
        "inspect": script_sha256(inspect_code),
    }
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "formation inspection initialization",
    )
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            inspect_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                inspect_code,
                output_capacity=output_capacity,
                operation="formation intelligence inspection",
            )
            snapshot = parse_intel_output(
                inspect_result.output,
                locked_initial_roles,
            )
            target = select_march_target(snapshot, quality, target_runtime_id)
            active_roles = (snapshot.role,)
            formation_code = build_inspect_formation_lua(active_roles, target)
            stage_hashes["formation"] = script_sha256(formation_code)
            formation_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                formation_code,
                output_capacity=output_capacity,
                operation="read-only formation inspection",
            )
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "inspect-formation",
            )

    result = _execution_payload(
        initialization,
        state,
        before,
        after,
        formation_result,
    )
    result.update(
        {
            "dry_run": False,
            "role": snapshot.role,
            "item_count": len(snapshot.items),
            "target": asdict(target),
            "request_dispatched": False,
            "output": formation_result.output,
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def _execute_inspect_battle_intel(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    category: str,
    *,
    initial_roles: Sequence[str],
    output_capacity: int,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    inspect_code = build_inspect_battle_intel_lua(locked_initial_roles, category)
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "battle intelligence inspection initialization",
    )
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            inspect_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                inspect_code,
                output_capacity=output_capacity,
                operation="battle intelligence inspection",
            )
            snapshot = parse_battle_intel_output(
                inspect_result.output,
                locked_initial_roles,
                category,
            )
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "inspect-battle-intel",
            )
    result = _execution_payload(initialization, state, before, after, inspect_result)
    result.update(
        {
            "role": snapshot.role,
            "category": normalize_battle_category(category),
            "item_count": len(snapshot.items),
            "items": [asdict(item) for item in snapshot.items],
            "stage_script_sha256": {"inspect": script_sha256(inspect_code)},
        }
    )
    return result


def _execute_inspect_tasks(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    *,
    initial_roles: Sequence[str],
    output_capacity: int,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    monster_code = build_inspect_intel_lua(locked_initial_roles)
    stage_hashes: dict[str, str] = {
        "inspect_monster": script_sha256(monster_code),
    }
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "task intelligence inspection initialization",
    )
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            monster_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                monster_code,
                output_capacity=output_capacity,
                operation="monster intelligence inspection",
            )
            last_result = monster_result
            monster_snapshot = parse_intel_output(
                monster_result.output,
                locked_initial_roles,
            )
            active_roles = (monster_snapshot.role,)
            battle_snapshots: dict[str, Any] = {}
            for category in ("hero", "rescue"):
                battle_code = build_inspect_battle_intel_lua(active_roles, category)
                stage_hashes[f"inspect_{category}"] = script_sha256(battle_code)
                battle_result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    battle_code,
                    output_capacity=output_capacity,
                    operation=f"{category} intelligence inspection",
                )
                last_result = battle_result
                battle_snapshots[category] = parse_battle_intel_output(
                    battle_result.output,
                    active_roles,
                    category,
                )
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "inspect-tasks",
            )

    items: list[dict[str, Any]] = []
    for item in monster_snapshot.items:
        copied = asdict(item)
        copied["category"] = "monster"
        items.append(copied)
    for category in ("hero", "rescue"):
        snapshot = battle_snapshots[category]
        if snapshot.role != monster_snapshot.role or snapshot.kingdom != monster_snapshot.kingdom:
            raise BusinessError(
                "active role or kingdom changed during task intelligence inspection"
            )
        items.extend(asdict(item) for item in snapshot.items)
    result = _execution_payload(initialization, state, before, after, last_result)
    result.update(
        {
            "role": monster_snapshot.role,
            "current_stamina": monster_snapshot.current_stamina,
            "item_count": len(items),
            "items": items,
            "categories": {
                "monster": len(monster_snapshot.items),
                "hero": len(battle_snapshots["hero"].items),
                "rescue": len(battle_snapshots["rescue"].items),
            },
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def _execute_battle_intel(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    category: str,
    *,
    initial_roles: Sequence[str],
    target_runtime_id: int | None = None,
    dry_run: bool,
    output_capacity: int,
    verify_timeout_seconds: float = 20.0,
    verify_poll_interval_seconds: float = 0.25,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    normalized_category = normalize_battle_category(category)
    inspect_code = build_inspect_battle_intel_lua(
        locked_initial_roles,
        normalized_category,
    )
    request_dispatched = False
    end_request_dispatched = False
    accepted = False
    status_after = "not-sent"
    verification_polls = 0
    selected_heroes: tuple[int, ...] = ()
    stage_hashes: dict[str, str] = {
        "inspect": script_sha256(inspect_code),
    }
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "battle workflow initialization",
    )
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            inspect_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                inspect_code,
                output_capacity=output_capacity,
                operation="battle intelligence inspection",
            )
            last_result = inspect_result
            snapshot = parse_battle_intel_output(
                inspect_result.output,
                locked_initial_roles,
                normalized_category,
            )
            target = select_battle_target(
                snapshot,
                normalized_category,
                target_runtime_id,
            )
            active_roles = (snapshot.role,)
            if not dry_run:
                if normalized_category == "rescue":
                    commit_code = build_start_rescue_intel_lua(active_roles, target)
                else:
                    commit_code = build_start_battle_intel_lua(active_roles, target)
                verify_code = build_verify_battle_intel_lua(active_roles, target)
                stage_hashes.update(
                    {
                        "commit": script_sha256(commit_code),
                        "verify": script_sha256(verify_code),
                    }
                )
                commit_result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    commit_code,
                    output_capacity=output_capacity,
                    operation=(
                        "battle start/end request"
                        if normalized_category == "hero"
                        else "rescue world march request"
                    ),
                )
                if normalized_category == "rescue":
                    parse_rescue_commit_output(
                        commit_result.output,
                        active_roles,
                        target,
                    )
                    selected_heroes = ()
                else:
                    selected_heroes = parse_battle_commit_output(
                        commit_result.output,
                        active_roles,
                        target,
                    )
                last_result = commit_result
                request_dispatched = True
                end_request_dispatched = normalized_category == "hero"
                verify_deadline = time.monotonic() + verify_timeout_seconds
                while True:
                    verify_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        verify_code,
                        output_capacity=output_capacity,
                        operation="battle result verification",
                    )
                    last_result = verify_result
                    verification_polls += 1
                    accepted, status_after = parse_battle_verify_output(
                        verify_result.output,
                        active_roles,
                        target,
                    )
                    if accepted:
                        break
                    if time.monotonic() >= verify_deadline:
                        request_label = (
                            "rescue world march request"
                            if normalized_category == "rescue"
                            else "battle request"
                        )
                        raise BusinessError(
                            f"{request_label} was invoked but no completed or "
                            "removed intelligence state appeared before timeout "
                            f"for target {target.runtime_id}; last quest status was "
                            f"{status_after} after {verification_polls} polls"
                        )
                    time.sleep(verify_poll_interval_seconds)
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "battle workflow",
            )

    result = _execution_payload(initialization, state, before, after, last_result)
    result.update(
        {
            "dry_run": dry_run,
            "battle_executed": not dry_run,
            "category": normalized_category,
            "request_dispatched": accepted if not dry_run else False,
            "start_request_dispatched": (
                request_dispatched and normalized_category == "hero"
            ),
            "world_march_request_dispatched": (
                request_dispatched and normalized_category == "rescue"
            ),
            "end_request_dispatched": end_request_dispatched,
            "quest_status_after": status_after,
            "verification_polls": verification_polls,
            "selected_heroes": list(selected_heroes),
            "role": snapshot.role,
            "item_count": len(snapshot.items),
            "target": asdict(target),
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


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
    average_tapped = False
    go_tapped = False
    stamina_receipt = None
    dispatch_mode = "dry-run"
    average_tap_coordinates: tuple[int, int] | None = None
    go_tap_coordinates: tuple[int, int] | None = None
    status_after = "not-sent"
    verification_polls = 0
    stage_hashes: dict[str, str] = {
        "inspect": script_sha256(inspect_code),
    }
    last_result: LuaExecutionResult
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "march workflow initialization",
    )
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            inspect_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                inspect_code,
                output_capacity=output_capacity,
                operation="march intelligence inspection",
            )
            last_result = inspect_result
            snapshot = parse_intel_output(
                inspect_result.output,
                locked_initial_roles,
            )
            target = select_march_target(snapshot, quality, target_runtime_id)
            active_roles = (snapshot.role,)

            if not dry_run:
                dispatch_mode = "direct"
                verify_code = build_verify_march_lua(active_roles, target)
                prepare_code = build_prepare_direct_march_lua(active_roles, target)
                commit_code = build_commit_prepared_march_lua(active_roles, target)
                stage_hashes.update(
                    {
                        "prepare": script_sha256(prepare_code),
                        "commit": script_sha256(commit_code),
                        "verify": script_sha256(verify_code),
                    }
                )
                prepare_result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    prepare_code,
                    output_capacity=output_capacity,
                    operation="direct march preparation",
                )
                prepare_receipt = parse_prepare_output(
                    prepare_result.output,
                    active_roles,
                    target,
                )
                stamina_receipt = prepare_receipt
                last_result = prepare_result
                if prepare_receipt.ready_to_commit:
                    commit_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        commit_code,
                        output_capacity=output_capacity,
                        operation="direct march request",
                    )
                    stamina_receipt = parse_commit_output(
                        commit_result.output,
                        active_roles,
                        target,
                    )
                    last_result = commit_result

                if stamina_receipt.blocked_reason is not None:
                    status_after = "insufficient-stamina"
                else:
                    verify_deadline = time.monotonic() + verify_timeout_seconds
                    while True:
                        verify_result = _execute_lua_when_idle(
                            adb,
                            profile,
                            client,
                            process,
                            scanner,
                            state,
                            verify_code,
                            output_capacity=output_capacity,
                            operation="march result verification",
                        )
                        last_result = verify_result
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
            "dispatch_mode": dispatch_mode,
            "request_dispatched": accepted,
            "expedition_opened": opened,
            "average_tapped": average_tapped,
            "go_tapped": go_tapped,
            "average_tap_coordinates": (
                list(average_tap_coordinates) if average_tap_coordinates else None
            ),
            "go_tap_coordinates": list(go_tap_coordinates) if go_tap_coordinates else None,
            "quest_status_after": status_after,
            "verification_polls": verification_polls,
            "blocked_reason": (
                stamina_receipt.blocked_reason if stamina_receipt is not None else None
            ),
            "current_stamina": (
                stamina_receipt.current_stamina if stamina_receipt is not None else None
            ),
            "required_stamina": (
                stamina_receipt.required_stamina if stamina_receipt is not None else None
            ),
            "base_stamina": (
                stamina_receipt.base_stamina if stamina_receipt is not None else None
            ),
            "role": snapshot.role,
            "item_count": len(snapshot.items),
            "target": asdict(target),
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


def _batch_result_error(
    profile: DeviceProfile,
    role: str,
    kingdom: int,
    category: str,
    runtime_id: int,
    detail: str,
    *,
    quality: str | None = None,
) -> dict[str, Any]:
    target: dict[str, Any] = {"runtime_id": runtime_id}
    if quality is not None:
        target["quality"] = quality
    return {
        "serial": profile.serial,
        "kingdom": kingdom,
        "role": role,
        "category": category,
        "quality": quality,
        "request_dispatched": False,
        "target": target,
        "quest_status_after": "error",
        "error": detail or "batch target dispatch failed",
    }


def _execute_batch_intel(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    target_specs: Sequence[dict[str, Any]],
    *,
    initial_roles: Sequence[str],
    initial_kingdom: int | None = None,
    output_capacity: int,
    verify_timeout_seconds: float = 8.0,
    verify_poll_interval_seconds: float = 0.2,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    specs = tuple(target_specs)
    if not specs:
        raise BusinessError("batch-intel requires at least one target")
    if len({int(spec["runtime_id"]) for spec in specs}) != len(specs):
        raise BusinessError("batch target runtime ids must be unique")

    full_targets = _full_targets_from_batch_specs(specs)
    needs_inspection = full_targets is None
    needs_monster = (
        any(spec["category"] == "monster" for spec in specs)
        if needs_inspection
        else False
    )
    battle_categories = (
        tuple(
            category
            for category in ("hero", "rescue")
            if any(spec["category"] == category for spec in specs)
        )
        if needs_inspection
        else ()
    )
    inspect_monster_code = (
        build_inspect_intel_lua(locked_initial_roles) if needs_monster else None
    )
    inspect_battle_codes = {
        category: build_inspect_battle_intel_lua(locked_initial_roles, category)
        for category in battle_categories
    }
    stage_hashes: dict[str, Any] = {}
    if inspect_monster_code is not None:
        stage_hashes["inspect_monster"] = script_sha256(inspect_monster_code)
    for category, code in inspect_battle_codes.items():
        stage_hashes[f"inspect_{category}"] = script_sha256(code)

    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "batch intelligence initialization",
    )
    role: str | None = locked_initial_roles[0] if len(locked_initial_roles) == 1 else None
    kingdom: int | None = initial_kingdom
    selected_targets: list[tuple[dict[str, Any], Any]] = []
    results: list[dict[str, Any]] = []

    def lock_identity(candidate_role: str, candidate_kingdom: int) -> None:
        nonlocal role, kingdom
        if role is None:
            role = candidate_role
            kingdom = candidate_kingdom
        elif role != candidate_role:
            raise BusinessError("active role changed during batch target inspection")
        elif kingdom != candidate_kingdom:
            raise BusinessError("active kingdom changed during batch target inspection")

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            last_result: LuaExecutionResult | None = None
            monster_snapshot = None
            if full_targets is not None:
                selected_targets = list(full_targets)
                if role is None or kingdom is None:
                    identity_code = build_scene_status_lua(locked_initial_roles)
                    stage_hashes["identity"] = script_sha256(identity_code)
                    identity_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        identity_code,
                        output_capacity=output_capacity,
                        operation="batch identity check",
                    )
                    last_result = identity_result
                    identity = parse_scene_status_output(
                        identity_result.output,
                        locked_initial_roles,
                    )
                    role = identity.role
                    kingdom = identity.kingdom
            else:
                if inspect_monster_code is not None:
                    monster_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        inspect_monster_code,
                        output_capacity=output_capacity,
                        operation="batch monster intelligence inspection",
                    )
                    last_result = monster_result
                    monster_snapshot = parse_intel_output(
                        monster_result.output,
                        locked_initial_roles,
                    )
                    lock_identity(monster_snapshot.role, monster_snapshot.kingdom)

                battle_snapshots: dict[str, Any] = {}
                for category, inspect_code in inspect_battle_codes.items():
                    battle_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        inspect_code,
                        output_capacity=output_capacity,
                        operation=f"batch {category} intelligence inspection",
                    )
                    last_result = battle_result
                    snapshot = parse_battle_intel_output(
                        battle_result.output,
                        locked_initial_roles,
                        category,
                    )
                    lock_identity(snapshot.role, snapshot.kingdom)
                    battle_snapshots[category] = snapshot

                assert role is not None
                assert kingdom is not None
                for spec in specs:
                    category = str(spec["category"])
                    runtime_id = int(spec["runtime_id"])
                    if category == "monster":
                        if monster_snapshot is None:
                            raise BusinessError("monster snapshot is unavailable")
                        target = select_march_target(
                            monster_snapshot,
                            str(spec["quality"]),
                            runtime_id,
                        )
                    else:
                        target = select_battle_target(
                            battle_snapshots[category],
                            category,
                            runtime_id,
                        )
                    selected_targets.append((spec, target))

            assert role is not None
            assert kingdom is not None
            active_roles = (role,)

            for index, (spec, target) in enumerate(selected_targets, start=1):
                category = str(spec["category"])
                runtime_id = int(spec["runtime_id"])
                quality = str(spec.get("quality", getattr(target, "quality", "")))
                try:
                    if category == "monster":
                        prepare_code = build_prepare_direct_march_lua(
                            active_roles,
                            target,
                        )
                        commit_code = build_commit_prepared_march_lua(
                            active_roles,
                            target,
                        )
                        verify_code = build_verify_march_lua(active_roles, target)
                        stage_hashes[f"target_{runtime_id}_prepare"] = script_sha256(
                            prepare_code
                        )
                        stage_hashes[f"target_{runtime_id}_commit"] = script_sha256(
                            commit_code
                        )
                        stage_hashes[f"target_{runtime_id}_verify"] = script_sha256(
                            verify_code
                        )
                        prepare_result = _execute_lua_when_idle(
                            adb,
                            profile,
                            client,
                            process,
                            scanner,
                            state,
                            prepare_code,
                            output_capacity=output_capacity,
                            operation=f"batch march preparation {runtime_id}",
                        )
                        last_result = prepare_result
                        prepare_receipt = parse_prepare_output(
                            prepare_result.output,
                            active_roles,
                            target,
                        )
                        if not prepare_receipt.ready_to_commit:
                            results.append(
                                {
                                    "serial": profile.serial,
                                    "kingdom": kingdom,
                                    "role": role,
                                    "category": "monster",
                                    "quality": quality,
                                    "request_dispatched": False,
                                    "blocked_reason": prepare_receipt.blocked_reason,
                                    "current_stamina": prepare_receipt.current_stamina,
                                    "required_stamina": prepare_receipt.required_stamina,
                                    "base_stamina": prepare_receipt.base_stamina,
                                    "target": asdict(target),
                                    "quest_status_after": "insufficient-stamina",
                                    "verification_polls": 0,
                                }
                            )
                            continue
                        commit_result = _execute_lua_when_idle(
                            adb,
                            profile,
                            client,
                            process,
                            scanner,
                            state,
                            commit_code,
                            output_capacity=output_capacity,
                            operation=f"batch direct march request {runtime_id}",
                        )
                        last_result = commit_result
                        commit_receipt = parse_commit_output(
                            commit_result.output,
                            active_roles,
                            target,
                        )

                        if not commit_receipt.request_dispatched:
                            results.append(
                                {
                                    "serial": profile.serial,
                                    "kingdom": kingdom,
                                    "role": role,
                                    "category": "monster",
                                    "quality": quality,
                                    "request_dispatched": False,
                                    "blocked_reason": commit_receipt.blocked_reason,
                                    "current_stamina": commit_receipt.current_stamina,
                                    "required_stamina": commit_receipt.required_stamina,
                                    "base_stamina": commit_receipt.base_stamina,
                                    "target": asdict(target),
                                    "quest_status_after": "insufficient-stamina",
                                    "verification_polls": 0,
                                }
                            )
                            continue

                        # Wait only until this march is visible locally. The next
                        # formation must be computed after the game has reserved
                        # this march's heroes and soldiers, otherwise a rapid batch
                        # can reuse the same stale availability snapshot.
                        verify_deadline = time.monotonic() + verify_timeout_seconds
                        verification_polls = 0
                        accepted = False
                        status_after = "not-sent"
                        while True:
                            verify_result = _execute_lua_when_idle(
                                adb,
                                profile,
                                client,
                                process,
                                scanner,
                                state,
                                verify_code,
                                output_capacity=output_capacity,
                                operation=f"batch march acceptance {runtime_id}",
                            )
                            last_result = verify_result
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
                                    "batch march request was invoked but no matching "
                                    "server-created self march or quest acceptance "
                                    f"appeared before timeout for target {runtime_id}; "
                                    f"last quest status was {status_after} after "
                                    f"{verification_polls} polls"
                                )
                            time.sleep(verify_poll_interval_seconds)
                        results.append(
                            {
                                "serial": profile.serial,
                                "kingdom": kingdom,
                                "role": role,
                                "category": "monster",
                                "quality": quality,
                                "request_dispatched": True,
                                "target": asdict(target),
                                "quest_status_after": status_after,
                                "verification_polls": verification_polls,
                                "blocked_reason": None,
                                "current_stamina": commit_receipt.current_stamina,
                                "required_stamina": commit_receipt.required_stamina,
                                "base_stamina": commit_receipt.base_stamina,
                            }
                        )
                    else:
                        if category == "rescue":
                            commit_code = build_start_rescue_intel_lua(
                                active_roles,
                                target,
                            )
                        else:
                            commit_code = build_start_battle_intel_lua(
                                active_roles,
                                target,
                            )
                        stage_hashes[f"target_{runtime_id}_commit"] = script_sha256(
                            commit_code
                        )
                        commit_result = _execute_lua_when_idle(
                            adb,
                            profile,
                            client,
                            process,
                            scanner,
                            state,
                            commit_code,
                            output_capacity=output_capacity,
                            operation=(
                                f"batch battle request {runtime_id}"
                                if category == "hero"
                                else f"batch rescue world march request {runtime_id}"
                            ),
                        )
                        last_result = commit_result
                        if category == "rescue":
                            parse_rescue_commit_output(
                                commit_result.output,
                                active_roles,
                                target,
                            )
                            selected_heroes = ()
                        else:
                            selected_heroes = parse_battle_commit_output(
                                commit_result.output,
                                active_roles,
                                target,
                            )
                        status_after = "1" if category == "rescue" else "2"
                        results.append(
                            {
                                "serial": profile.serial,
                                "kingdom": kingdom,
                                "role": role,
                                "category": category,
                                "quality": getattr(target, "quality", None),
                                "request_dispatched": True,
                                "start_request_dispatched": category == "hero",
                                "world_march_request_dispatched": category == "rescue",
                                "end_request_dispatched": category == "hero",
                                "target": asdict(target),
                                "quest_status_after": status_after,
                                "verification_polls": 0,
                                "selected_heroes": list(selected_heroes),
                            }
                        )
                except Exception as exc:
                    results.append(
                        _batch_result_error(
                            profile,
                            role,
                            kingdom,
                            category,
                            runtime_id,
                            str(exc),
                            quality=quality if quality else None,
                        )
                    )
                    LOGGER.warning(
                        "batch target %s/%s failed: %s",
                        index,
                        len(selected_targets),
                        exc,
                    )
            if last_result is None:
                raise BusinessError("batch intelligence inspection produced no result")
        finally:
            after = _verify_process_after_lua_finally(
                adb,
                profile,
                scanner,
                process,
                state,
                "batch intelligence workflow",
            )

    assert role is not None
    result = _execution_payload(initialization, state, before, after, last_result)
    result.update(
        {
            "dry_run": False,
            "batch_executed": True,
            "role": role,
            "item_count": len(selected_targets),
            "target_count": len(selected_targets),
            "request_dispatched": all(
                item.get("request_dispatched") is True for item in results
            ),
            "results": results,
            "stage_script_sha256": stage_hashes,
        }
    )
    return result


_MARCH_CAPTURE_REQUEST_MARKERS = (
    "WorldMarchHelper.RequestMarchStartOff",
    "WorldMarchCtrl.RequestWorldMarchStartOff",
)


def _march_capture_record_count(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("COUNT\t"):
            try:
                return int(line.split("\t", 1)[1])
            except ValueError as exc:
                raise BusinessError("capture hook returned an invalid COUNT") from exc
    raise BusinessError("capture hook output is missing COUNT")


def _march_capture_has_request(output: str) -> bool:
    return any(marker in output for marker in _MARCH_CAPTURE_REQUEST_MARKERS)


def _execute_capture_march(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    *,
    initial_roles: Sequence[str],
    output_capacity: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
    output_file: Path | None,
    keep_hook: bool = False,
) -> dict[str, Any]:
    locked_initial_roles = validate_role_whitelist(initial_roles)
    install_code = build_install_march_capture_hook_lua(locked_initial_roles)
    read_code = build_read_march_capture_hook_lua(locked_initial_roles)
    uninstall_code = build_uninstall_march_capture_hook_lua(locked_initial_roles)
    stage_hashes = {
        "install": script_sha256(install_code),
        "read": script_sha256(read_code),
        "uninstall": script_sha256(uninstall_code),
    }
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "capture-march initialization",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    deadline = time.monotonic() + timeout_seconds
    poll_count = 0
    record_count = 0
    captured_request = False
    records_output = ""
    uninstall_output = ""
    last_result: LuaExecutionResult | None = None

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = _wait_idle_lua_state(scanner, process, state)
        try:
            install_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                install_code,
                output_capacity=output_capacity,
                operation="capture hook installation",
            )
            last_result = install_result
            while True:
                read_result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    read_code,
                    output_capacity=output_capacity,
                    operation="capture hook read",
                )
                last_result = read_result
                poll_count += 1
                records_output = read_result.output
                record_count = _march_capture_record_count(records_output)
                captured_request = _march_capture_has_request(records_output)
                if captured_request:
                    break
                now = time.monotonic()
                if now >= deadline:
                    raise BusinessError(
                        "capture-march timed out before a real UI march request "
                        "was observed"
                    )
                time.sleep(min(poll_interval_seconds, deadline - now))
        finally:
            try:
                if not keep_hook:
                    uninstall_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        uninstall_code,
                        output_capacity=output_capacity,
                        operation="capture hook uninstall",
                    )
                    uninstall_output = uninstall_result.output
                    last_result = uninstall_result if last_result is None else last_result
            finally:
                after = _verify_process_after_lua_finally(
                    adb,
                    profile,
                    scanner,
                    process,
                    state,
                    "capture-march",
                )

    if last_result is None:
        raise BusinessError("capture-march did not execute any Lua stage")
    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(records_output, encoding="utf-8")

    result = _execution_payload(initialization, state, before, after, last_result)
    result.update(
        {
            "dry_run": False,
            "hook_installed": True,
            "hook_uninstalled": bool(uninstall_output),
            "hook_left_installed": keep_hook and not bool(uninstall_output),
            "captured_request": captured_request,
            "record_count": record_count,
            "poll_count": poll_count,
            "records_output": records_output,
            "uninstall_output": uninstall_output,
            "output_file": str(output_file) if output_file is not None else None,
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
    return_on_any: bool = False,
) -> dict[str, Any]:
    normalized_ids = normalize_target_ids(target_ids)
    locked_initial_roles = validate_role_whitelist(initial_roles)
    initial_code = build_intel_status_lua(locked_initial_roles, normalized_ids)
    stage_hashes = {"initial": script_sha256(initial_code)}
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "wait-intel initialization",
        timeout_seconds=min(timeout_seconds, 10.0),
        poll_interval_seconds=min(poll_interval_seconds, 0.5),
    )
    deadline = time.monotonic() + timeout_seconds
    poll_count = 0
    locked_role: str | None = None
    snapshot: IntelStatusSnapshot | None = None
    last_result: LuaExecutionResult | None = None

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = _wait_idle_lua_state(scanner, process, state)
        try:
            while True:
                allowed_roles = (
                    locked_initial_roles if locked_role is None else (locked_role,)
                )
                code = build_intel_status_lua(allowed_roles, normalized_ids)
                result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    code,
                    output_capacity=output_capacity,
                    operation="wait-intel status poll",
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
                terminal_ids = [
                    target.runtime_id
                    for target in snapshot.targets
                    if target.state != INTEL_PENDING
                ]
                if not pending_ids or (return_on_any and terminal_ids):
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
            "wait_completed": not any(
                target.state == INTEL_PENDING for target in snapshot.targets
            ),
            "returned_on_any": return_on_any,
            "terminal_target_ids": [
                target.runtime_id
                for target in snapshot.targets
                if target.state != INTEL_PENDING
            ],
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
    state = _wait_unique_idle_lua_state(
        adb,
        profile,
        scanner,
        process,
        "claim-intel initialization",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    request_dispatched = False
    idempotent = False
    claim_invoked = False
    verification_polls = 0

    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = _wait_idle_lua_state(scanner, process, state)
        try:
            initial_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                initial_code,
                output_capacity=output_capacity,
                operation="claim-intel initial status",
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
                claim_result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    claim_code,
                    output_capacity=output_capacity,
                    operation="claim-intel request",
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
                    verify_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        status_code,
                        output_capacity=output_capacity,
                        operation="claim-intel verification",
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


def _execute_hunt_world_monster(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    level: int,
    count: int,
    *,
    output_capacity: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    requested_level = normalize_world_monster_level(level)
    requested_count = normalize_world_monster_count(count)
    search_code = build_world_monster_search_lua(requested_level)
    search_result_code = build_world_monster_search_result_lua(requested_level)
    commit_code = build_world_monster_commit_lua(requested_level)
    verify_code = build_world_monster_verify_lua(requested_level)
    stage_hashes = {
        "search": script_sha256(search_code),
        "search_result": script_sha256(search_result_code),
        "commit": script_sha256(commit_code),
        "verify": script_sha256(verify_code),
    }
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb, profile, scanner, process, "world monster hunt initialization"
    )
    search_polls = 0
    verification_polls = 0
    marches: list[dict[str, Any]] = []
    blocked_reason: str | None = None
    current_stamina: int | None = None
    last_search = None
    last_commit = None
    with client:
        initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
        before = scanner.verify_idle_main(process.pid, state.address)
        try:
            for hunt_index in range(requested_count):
                search_result = _execute_lua_when_idle(
                    adb, profile, client, process, scanner, state, search_code,
                    output_capacity=output_capacity,
                    operation=f"world monster search request {hunt_index + 1}",
                )
                parse_world_monster_search_sent_output(
                    search_result.output, requested_level
                )
                last_result = search_result
                search_deadline = time.monotonic() + timeout_seconds
                while True:
                    result = _execute_lua_when_idle(
                        adb, profile, client, process, scanner, state,
                        search_result_code,
                        output_capacity=output_capacity,
                        operation=f"world monster search result {hunt_index + 1}",
                    )
                    last_result = result
                    search_polls += 1
                    search = parse_world_monster_search_output(
                        result.output, requested_level
                    )
                    if search.ready:
                        break
                    if time.monotonic() >= search_deadline:
                        raise BusinessError(
                            "world monster search did not return an actual map object "
                            "before timeout"
                        )
                    time.sleep(poll_interval_seconds)
                last_search = search

                result = _execute_lua_when_idle(
                    adb, profile, client, process, scanner, state, commit_code,
                    output_capacity=output_capacity,
                    operation=f"world monster formation and dispatch {hunt_index + 1}",
                )
                last_result = result
                commit = parse_world_monster_commit_output(result.output, search)
                last_commit = commit
                current_stamina = commit.current_stamina
                if not commit.request_dispatched:
                    blocked_reason = commit.blocked_reason
                    break
                verify_deadline = time.monotonic() + timeout_seconds
                while True:
                    result = _execute_lua_when_idle(
                        adb, profile, client, process, scanner, state, verify_code,
                        output_capacity=output_capacity,
                        operation=f"world monster march verification {hunt_index + 1}",
                    )
                    last_result = result
                    verification_polls += 1
                    verification = parse_world_monster_verify_output(
                        result.output, search
                    )
                    if verification.march_id is not None:
                        current_stamina = verification.current_stamina
                        marches.append(
                            {
                                "march_id": verification.march_id,
                                "verified": True,
                                "request_dispatched": True,
                                "status": "ACTIVE",
                                "state": "ACTIVE",
                                "level": search.level,
                                "monster_id": search.monster_id,
                                "recommended_power": search.recommended_power,
                                "world_x": search.world_x,
                                "world_y": search.world_y,
                                "current_stamina": verification.current_stamina,
                                "required_stamina": commit.required_stamina,
                                "base_stamina": commit.base_stamina,
                            }
                        )
                        break
                    if time.monotonic() >= verify_deadline:
                        raise BusinessError(
                            "world monster request was dispatched but no matching "
                            "server-created self march appeared before timeout"
                        )
                    time.sleep(poll_interval_seconds)
        finally:
            after = _verify_process_after_lua_finally(
                adb, profile, scanner, process, state, "world monster hunt"
            )

    result_payload = _execution_payload(
        initialization, state, before, after, last_result
    )
    status_rows = [
        {
            "march_id": march["march_id"],
            "status": march["state"],
            "state": march["state"],
        }
        for march in marches
    ]
    march_ids = [int(march["march_id"]) for march in marches]
    if last_search is None or last_commit is None:
        raise BusinessError("world monster hunt produced no search result")
    result_payload.update(
        {
            "role": last_search.role,
            "level": requested_level,
            "requested_count": requested_count,
            "completed_count": len(marches),
            "monster_id": last_search.monster_id,
            "recommended_power": last_search.recommended_power,
            "world_x": last_search.world_x,
            "world_y": last_search.world_y,
            "request_dispatched": bool(marches),
            "verified": len(marches) == requested_count,
            "march_id": march_ids[-1] if march_ids else None,
            "march_ids": march_ids,
            "marches": marches,
            "statuses": status_rows,
            "current_stamina": current_stamina,
            "required_stamina": last_commit.required_stamina,
            "base_stamina": last_commit.base_stamina,
            "blocked_reason": blocked_reason,
            "search_polls": search_polls,
            "verification_polls": verification_polls,
            "stage_script_sha256": stage_hashes,
        }
    )
    return result_payload


def _execute_world_monster_loop(
    adb: AdbClient,
    profile: DeviceProfile,
    client: FridaLuaClient,
    process: ProcessInfo,
    level: int,
    concurrency: int,
    *,
    output_capacity: int,
    poll_interval_seconds: float,
    operation_timeout_seconds: float = 30.0,
) -> int:
    requested_level = normalize_world_monster_level(level)
    requested_concurrency = normalize_world_monster_count(concurrency)
    if (
        isinstance(poll_interval_seconds, bool)
        or not isinstance(poll_interval_seconds, (int, float))
        or not math.isfinite(poll_interval_seconds)
        or not 0.05 <= poll_interval_seconds <= 60
    ):
        raise BusinessError("world monster loop poll interval must be between 0.05 and 60 seconds")

    search_code = build_world_monster_search_lua(requested_level)
    search_result_code = build_world_monster_search_result_lua(requested_level)
    commit_code = build_world_monster_commit_lua(requested_level)
    verify_code = build_world_monster_verify_lua(requested_level)
    scanner = _scanner(adb, profile)
    state = _wait_unique_idle_lua_state(
        adb, profile, scanner, process, "world monster loop initialization"
    )
    active: dict[int, dict[str, Any]] = {}
    current_stamina: int | None = None
    dispatch_count = 0
    stop_requested = False
    previous_status_signature: tuple[tuple[int, str], ...] | None = None

    def emit(event: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "event": event,
            "serial": profile.serial,
            "level": requested_level,
            "concurrency": requested_concurrency,
            "current_stamina": current_stamina,
            "active_march_ids": sorted(active),
            "marches": [active[march_id] for march_id in sorted(active)],
        }
        payload.update(extra)
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    def check_stop() -> None:
        if stop_requested:
            raise KeyboardInterrupt

    def recover_lua_state(operation: str, error: LuaStateScanError) -> None:
        nonlocal state
        previous = state
        _require_same_foreground_process(adb, profile, process, operation)
        state = _wait_unique_idle_lua_state(
            adb,
            profile,
            scanner,
            process,
            f"{operation} Lua state recovery",
            timeout_seconds=60.0,
        )
        emit(
            "recover",
            stage="lua_state",
            previous_lua_state=previous.address_text,
            lua_state=state.address_text,
            detail=(
                f"检测到游戏 Lua 状态变化（{previous.address_text} -> "
                f"{state.address_text}），已在当前模拟器内重新绑定并继续。"
            ),
            recovery_cause=str(error),
        )

    def dispatch_one() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        nonlocal current_stamina, dispatch_count
        while True:
            check_stop()
            try:
                search_result = _execute_lua_when_idle(
                    adb,
                    profile,
                    client,
                    process,
                    scanner,
                    state,
                    search_code,
                    output_capacity=output_capacity,
                    operation=(
                        f"world monster loop search request {dispatch_count + 1}"
                    ),
                )
                parse_world_monster_search_sent_output(
                    search_result.output, requested_level
                )
                search_deadline = time.monotonic() + operation_timeout_seconds
                while True:
                    check_stop()
                    search_result = _execute_lua_when_idle(
                        adb,
                        profile,
                        client,
                        process,
                        scanner,
                        state,
                        search_result_code,
                        output_capacity=output_capacity,
                        operation=(
                            f"world monster loop search result {dispatch_count + 1}"
                        ),
                    )
                    search = parse_world_monster_search_output(
                        search_result.output, requested_level
                    )
                    current_stamina = search.current_stamina
                    if search.ready:
                        break
                    now = time.monotonic()
                    if now >= search_deadline:
                        emit(
                            "retry",
                            stage="search",
                            detail=(
                                "本次地图搜索暂未返回可攻击目标；继续等待同一搜索回调，"
                                "不会停止或叠加新的搜索请求。"
                            ),
                        )
                        search_deadline = now + operation_timeout_seconds
                    # The search result is delivered by a game-side callback.
                    # Keep polling the same request; issuing another one here can
                    # overlap native callbacks and crash the game.
                    time.sleep(poll_interval_seconds)
            except LuaStateScanError as exc:
                recover_lua_state("world monster search", exc)
                continue
            if search.ready:
                break

        commit_result = _execute_lua_when_idle(
            adb,
            profile,
            client,
            process,
            scanner,
            state,
            commit_code,
            output_capacity=output_capacity,
            operation=f"world monster loop formation and dispatch {dispatch_count + 1}",
        )
        commit = parse_world_monster_commit_output(commit_result.output, search)
        current_stamina = commit.current_stamina
        if not commit.request_dispatched:
            return None, {
                "blocked_reason": commit.blocked_reason,
                "required_stamina": commit.required_stamina,
                "base_stamina": commit.base_stamina,
                "detail": (
                    f"current stamina {commit.current_stamina} is below required "
                    f"stamina {commit.required_stamina}"
                ),
            }

        verify_deadline = time.monotonic() + operation_timeout_seconds
        while True:
            check_stop()
            verify_result = _execute_lua_when_idle(
                adb,
                profile,
                client,
                process,
                scanner,
                state,
                verify_code,
                output_capacity=output_capacity,
                operation=f"world monster loop march verification {dispatch_count + 1}",
            )
            verification = parse_world_monster_verify_output(
                verify_result.output, search
            )
            current_stamina = verification.current_stamina
            if verification.march_id is not None:
                dispatch_count += 1
                march = {
                    "march_id": verification.march_id,
                    "status": "ACTIVE",
                    "state": "ACTIVE",
                    "level": search.level,
                    "monster_id": search.monster_id,
                    "recommended_power": search.recommended_power,
                    "world_x": search.world_x,
                    "world_y": search.world_y,
                    "required_stamina": commit.required_stamina,
                    "base_stamina": commit.base_stamina,
                }
                return march, None
            if time.monotonic() >= verify_deadline:
                raise BusinessError(
                    "world monster request was dispatched but no matching "
                    "server-created self march appeared before timeout"
                )
            time.sleep(poll_interval_seconds)

    def emit_blocked(blocked: Mapping[str, Any]) -> None:
        emit(
            "blocked",
            blocked_reason=blocked.get("blocked_reason"),
            required_stamina=blocked.get("required_stamina"),
            base_stamina=blocked.get("base_stamina"),
            detail=blocked.get("detail"),
        )

    old_sigterm: Any = None
    sigterm_installed = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    terminal_outcome = False
    try:
        try:
            old_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, request_stop)
            sigterm_installed = True
        except (AttributeError, ValueError):
            pass

        with client:
            initialization = dict(client.initialize_bridge(profile.bridge_remote_path))
            scanner.verify_idle_main(process.pid, state.address)
            emit(
                "start",
                bridge_arch=initialization.get("arch"),
                pid=process.pid,
            )
            try:
                while True:
                    check_stop()
                    while len(active) < requested_concurrency:
                        try:
                            march, blocked = dispatch_one()
                        except LuaExecutionError as exc:
                            if "requested monster level exceeds" not in str(exc):
                                raise
                            blocked = {
                                "blocked_reason": "level_locked",
                                "detail": str(exc),
                            }
                            march = None
                        if blocked is not None:
                            emit_blocked(blocked)
                            emit("stopped", reason=str(blocked.get("blocked_reason")))
                            terminal_outcome = True
                            return 0
                        assert march is not None
                        march_id = int(march["march_id"])
                        if march_id in active:
                            raise BusinessError(
                                f"world monster loop received duplicate march id {march_id}"
                            )
                        active[march_id] = march
                        emit("dispatch", dispatched_march=march)

                    check_stop()
                    status_code = build_world_monster_status_lua(tuple(sorted(active)))
                    try:
                        status_result = _execute_lua_when_idle(
                            adb,
                            profile,
                            client,
                            process,
                            scanner,
                            state,
                            status_code,
                            output_capacity=output_capacity,
                            operation="world monster loop status",
                        )
                    except LuaStateScanError as exc:
                        recover_lua_state("world monster status", exc)
                        previous_status_signature = None
                        continue
                    snapshot = parse_world_monster_status_output(
                        status_result.output, tuple(sorted(active))
                    )
                    current_stamina = snapshot.current_stamina
                    signature = tuple(
                        (status.march_id, status.state)
                        for status in snapshot.statuses
                    )
                    for status in snapshot.statuses:
                        if status.march_id in active:
                            active[status.march_id]["status"] = status.state
                            active[status.march_id]["state"] = status.state
                    if signature != previous_status_signature:
                        emit(
                            "status",
                            statuses=[
                                {
                                    "march_id": status.march_id,
                                    "status": status.state,
                                    "state": status.state,
                                }
                                for status in snapshot.statuses
                            ],
                        )
                        previous_status_signature = signature
                    returned = [
                        status.march_id
                        for status in snapshot.statuses
                        if status.state in {"RETURNED", "UNKNOWN"}
                    ]
                    if returned:
                        for march_id in returned:
                            active.pop(march_id, None)
                        previous_status_signature = None
                        emit("returned", returned_march_ids=returned)
                        continue
                    time.sleep(poll_interval_seconds)
            except KeyboardInterrupt:
                emit("stopped", reason="signal")
                terminal_outcome = True
                return 0
            except Exception as exc:
                emit("error", error=str(exc), error_type=type(exc).__name__)
                terminal_outcome = True
                return 2
            finally:
                try:
                    _verify_process_after_lua(
                        adb,
                        profile,
                        scanner,
                        process,
                        state,
                        "world monster loop",
                    )
                except Exception as final_error:
                    if not terminal_outcome:
                        raise
                    LOGGER.warning(
                        "world monster loop post-check failed after terminal event; "
                        "preserving the terminal result: %s",
                        final_error,
                    )
    except KeyboardInterrupt:
        emit("stopped", reason="signal")
        return 0
    except Exception as exc:
        emit("error", error=str(exc), error_type=type(exc).__name__)
        return 2
    finally:
        if sigterm_installed:
            signal.signal(signal.SIGTERM, old_sigterm)


def execute(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "validate":
        for profile in settings.devices:
            validate_role_whitelist(profile.roles)
        print(f"configuration is valid: {Path(args.config).resolve()}")
        return 0

    if args.command == "devices":
        adb = _adb(settings)
        if args.connect:
            devices = adb.connect_configured(settings.adb.connect_targets)
            _ensure_frida_forwards(adb, settings.devices)
        else:
            devices = adb.devices()
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
        forwarded = _ensure_frida_forwards(adb, profiles)
        guard = KingdomGuard(adb)
        for profile in profiles:
            kingdom = guard.require(profile)
            activity = _foreground_activity(adb, profile)
            adb_pid = _adb_pid(adb, profile)
            process = ProcessInfo(adb_pid, "-")
            frida_ready = False
            bridge_initialized = False
            bridge_arch: str | None = None
            if activity.matches(profile.activity_name):
                client = _client(profile, pid=adb_pid, adb=adb)
                if getattr(args, "prepare_frida", False):
                    _ensure_bridge_binary(adb, profile)
                    with client:
                        initialization = dict(
                            client.initialize_bridge(profile.bridge_remote_path)
                        )
                        process = client.inspect_process()
                    frida_ready = True
                    bridge_initialized = True
                    bridge_arch = str(initialization.get("arch", ""))
                else:
                    process = client.inspect_process()
                    frida_ready = True
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
                        "frida_forward_ready": True,
                        "frida_forward_created": forwarded.get(profile.serial, False),
                        "frida_ready": frida_ready,
                        "bridge_initialized": bridge_initialized,
                        "bridge_arch": bridge_arch,
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

    profile = _profile(settings, args.serial)
    expected_role = getattr(args, "expected_role", None)
    operation_roles = (
        _operation_roles(profile, expected_role)
        if args.command
        in {
            "inspect-intel",
            "inspect-tasks",
            "inspect-battle-intel",
            "ensure-world",
            "wait-intel",
            "claim-intel",
            "march",
            "battle-intel",
            "batch-intel",
            "inspect-formation",
            "capture-march",
            "unhook-march-capture",
        }
        else tuple(profile.roles)
    )
    quality: str | None = None
    battle_category: str | None = None
    batch_target_specs: tuple[dict[str, Any], ...] | None = None
    target_runtime_id: int | None = None
    target_ids: tuple[int, ...] | None = None
    world_monster_level: int | None = None
    world_monster_count: int | None = None
    world_monster_loop_concurrency: int | None = None
    world_monster_march_ids: tuple[int, ...] | None = None
    timeout_seconds: float | None = None
    poll_interval_seconds: float | None = None
    if args.command == "exec-lua":
        code = _lua_source(args)
        require_safe_lua(code, allow_unsafe=args.allow_unsafe_lua)
    elif args.command == "inspect-intel":
        code = build_inspect_intel_lua(operation_roles)
    elif args.command == "inspect-tasks":
        code = build_inspect_intel_lua(operation_roles)
    elif args.command == "inspect-battle-intel":
        battle_category = normalize_battle_category(args.category)
        code = build_inspect_battle_intel_lua(operation_roles, battle_category)
    elif args.command == "ensure-world":
        timeout_seconds, poll_interval_seconds = _polling_options(args)
        code = build_scene_status_lua(operation_roles)
    elif args.command in {"wait-intel", "claim-intel"}:
        target_ids = normalize_target_ids(args.target_ids)
        timeout_seconds, poll_interval_seconds = _polling_options(args)
        code = build_intel_status_lua(operation_roles, target_ids)
    elif args.command in {"march", "inspect-formation"}:
        quality = normalize_quality(args.quality)
        target_runtime_id = getattr(args, "target_id", None)
        if target_runtime_id is not None and target_runtime_id <= 0:
            raise BusinessError(
                f"{args.command} target runtime id must be a positive integer"
            )
        code = build_inspect_intel_lua(operation_roles)
    elif args.command == "battle-intel":
        battle_category = normalize_battle_category(args.category)
        target_runtime_id = getattr(args, "target_id", None)
        if target_runtime_id is not None and target_runtime_id <= 0:
            raise BusinessError(
                f"{args.command} target runtime id must be a positive integer"
            )
        code = build_inspect_battle_intel_lua(operation_roles, battle_category)
    elif args.command == "batch-intel":
        batch_target_specs = _parse_batch_target_specs(
            getattr(args, "batch_targets", None) or (),
            getattr(args, "batch_target_json", None) or (),
        )
        code = build_scene_status_lua(operation_roles)
    elif args.command == "capture-march":
        timeout_seconds, poll_interval_seconds = _polling_options(args)
        code = build_install_march_capture_hook_lua(operation_roles)
    elif args.command == "unhook-march-capture":
        code = build_uninstall_march_capture_hook_lua(operation_roles)
    elif args.command == "hunt-world-monster":
        world_monster_level = normalize_world_monster_level(args.level)
        world_monster_count = normalize_world_monster_count(args.count)
        timeout_seconds, poll_interval_seconds = _polling_options(args)
        code = build_world_monster_search_lua(world_monster_level)
    elif args.command == "world-monster-loop":
        world_monster_level = normalize_world_monster_level(args.level)
        world_monster_loop_concurrency = normalize_world_monster_count(
            args.concurrency
        )
        poll_interval_seconds = float(args.poll_interval)
        if (
            isinstance(args.poll_interval, bool)
            or not math.isfinite(poll_interval_seconds)
            or not 0.05 <= poll_interval_seconds <= 60
        ):
            raise BusinessError(
                "world monster loop poll interval must be between 0.05 and 60 seconds"
            )
        code = build_world_monster_search_lua(world_monster_level)
    elif args.command == "world-monster-status":
        world_monster_march_ids = normalize_world_monster_march_ids(args.march_ids)
        code = build_world_monster_status_lua(world_monster_march_ids)
    else:
        raise ConfigError(f"unsupported command {args.command!r}")

    adb = _adb(settings)
    adb.require_connected([profile.serial])
    kingdom = KingdomGuard(adb).require(profile)
    activity = _require_game_foreground(adb, profile)
    adb_pid = _adb_pid(adb, profile)
    _ensure_frida_forward(adb, profile)
    _ensure_bridge_binary(adb, profile)
    client = _client(profile, pid=adb_pid, adb=adb)
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
    if battle_category is not None:
        payload["category"] = battle_category
    if batch_target_specs is not None:
        payload["requested_batch_targets"] = list(batch_target_specs)
    if target_runtime_id is not None:
        payload["requested_target_id"] = target_runtime_id
    if target_ids is not None:
        payload["requested_target_ids"] = list(target_ids)
    if world_monster_level is not None:
        payload["level"] = world_monster_level
    if world_monster_count is not None:
        payload["requested_count"] = world_monster_count
    if world_monster_loop_concurrency is not None:
        payload["concurrency"] = world_monster_loop_concurrency
    if world_monster_march_ids is not None:
        payload["march_ids"] = list(world_monster_march_ids)
    if expected_role is not None:
        payload["expected_role"] = expected_role

    if args.dry_run and args.command not in {
        "march",
        "battle-intel",
        "batch-intel",
        "claim-intel",
        "ensure-world",
        "hunt-world-monster",
        "world-monster-loop",
    }:
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

    if args.command == "inspect-battle-intel":
        assert battle_category is not None
        payload.update(
            _execute_inspect_battle_intel(
                adb,
                profile,
                client,
                process,
                battle_category,
                initial_roles=operation_roles,
                output_capacity=settings.frida.output_capacity,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "hunt-world-monster":
        assert world_monster_level is not None
        assert world_monster_count is not None
        assert timeout_seconds is not None
        assert poll_interval_seconds is not None
        if args.dry_run:
            payload.update(
                {
                    "dry_run": True,
                    "lua_executed": False,
                    "request_dispatched": False,
                    "verified": False,
                    "march_id": None,
                    "march_ids": [],
                    "marches": [],
                    "statuses": [],
                    "current_stamina": None,
                    "required_stamina": None,
                    "base_stamina": None,
                    "blocked_reason": None,
                }
            )
        else:
            payload.update(
                _execute_hunt_world_monster(
                    adb,
                    profile,
                    client,
                    process,
                    world_monster_level,
                    world_monster_count,
                    output_capacity=settings.frida.output_capacity,
                    timeout_seconds=timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                )
            )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "world-monster-loop":
        assert world_monster_level is not None
        assert world_monster_loop_concurrency is not None
        assert poll_interval_seconds is not None
        if args.dry_run:
            payload.update(
                {
                    "dry_run": True,
                    "lua_executed": False,
                    "active_march_ids": [],
                    "marches": [],
                    "current_stamina": None,
                }
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        return _execute_world_monster_loop(
            adb,
            profile,
            client,
            process,
            world_monster_level,
            world_monster_loop_concurrency,
            output_capacity=settings.frida.output_capacity,
            poll_interval_seconds=poll_interval_seconds,
        )

    if args.command == "inspect-tasks":
        payload.update(
            _execute_inspect_tasks(
                adb,
                profile,
                client,
                process,
                initial_roles=operation_roles,
                output_capacity=settings.frida.output_capacity,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "battle-intel":
        assert battle_category is not None
        payload.update(
            _execute_battle_intel(
                adb,
                profile,
                client,
                process,
                battle_category,
                initial_roles=operation_roles,
                target_runtime_id=target_runtime_id,
                dry_run=args.dry_run,
                output_capacity=settings.frida.output_capacity,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "batch-intel":
        assert batch_target_specs is not None
        if args.dry_run:
            payload.update({"dry_run": True, "lua_executed": False})
        else:
            payload.update(
                _execute_batch_intel(
                    adb,
                    profile,
                    client,
                    process,
                    batch_target_specs,
                    initial_roles=operation_roles,
                    initial_kingdom=kingdom.kingdom,
                    output_capacity=settings.frida.output_capacity,
                )
            )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "inspect-formation":
        payload.update(
            _execute_inspect_formation(
                adb,
                profile,
                client,
                process,
                quality,
                initial_roles=operation_roles,
                target_runtime_id=target_runtime_id,
                output_capacity=settings.frida.output_capacity,
            )
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "ensure-world":
        assert timeout_seconds is not None
        assert poll_interval_seconds is not None
        payload.update(
            _execute_ensure_world(
                adb,
                profile,
                client,
                process,
                initial_roles=operation_roles,
                dry_run=args.dry_run,
                output_capacity=settings.frida.output_capacity,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
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
                return_on_any=bool(getattr(args, "return_on_any", False)),
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

    if args.command == "capture-march":
        assert timeout_seconds is not None
        assert poll_interval_seconds is not None
        payload.update(
            _execute_capture_march(
                adb,
                profile,
                client,
                process,
                initial_roles=operation_roles,
                output_capacity=settings.frida.output_capacity,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                output_file=args.output_file,
                keep_hook=args.keep_hook,
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
                "current_stamina": snapshot.current_stamina,
                "item_count": len(snapshot.items),
                "items": [asdict(item) for item in snapshot.items],
            }
        )
    elif args.command == "world-monster-status":
        assert world_monster_march_ids is not None
        snapshot = parse_world_monster_status_output(
            result.output, world_monster_march_ids
        )
        statuses = [
            {
                "march_id": status.march_id,
                "status": status.state,
                "state": status.state,
            }
            for status in snapshot.statuses
        ]
        payload.update(
            {
                "role": snapshot.role,
                "current_stamina": snapshot.current_stamina,
                "blocked_reason": None,
                "march_ids": list(world_monster_march_ids),
                "statuses": statuses,
                "marches": [
                    {
                        "march_id": status.march_id,
                        "status": status.state,
                        "state": status.state,
                    }
                    for status in snapshot.statuses
                ],
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
        MumuManagerError,
    ) as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        LOGGER.warning("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
