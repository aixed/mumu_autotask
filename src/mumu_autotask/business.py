from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass
from typing import Sequence


class BusinessError(ValueError):
    """Raised when a built-in game operation cannot be proven safe."""


ALLOWED_KINGDOM = 4549
QUALITY_IDS = {
    "green": 2,
    "blue": 3,
    "purple": 4,
    "yellow": 5,
}
QUALITY_BY_ID = {value: key for key, value in QUALITY_IDS.items()}
QUALITY_ALIASES = {
    "orange": "yellow",
    "绿色": "green",
    "蓝色": "blue",
    "紫色": "purple",
    "黄色": "yellow",
    "橙色": "yellow",
}
_INTEGER_PATTERN = re.compile(r"0|[1-9][0-9]*\Z")
_ROLE_HEX_PATTERN = re.compile(r"(?:[0-9a-f]{2})+\Z")
_PROTOCOL_PREFIX = "MUMU_AUTOTASK\t1\t"
LUA_BRIDGE_CODE_CAPACITY = 16384


@dataclass(frozen=True, slots=True)
class IntelItem:
    runtime_id: int
    quest_id: int
    status: int
    world_x: int
    world_y: int
    expires_at: int
    quality: str
    quality_id: int
    monster_id: int
    level: int
    stamina_cost: int


@dataclass(frozen=True, slots=True)
class IntelSnapshot:
    role: str
    kingdom: int
    items: tuple[IntelItem, ...]


@dataclass(frozen=True, slots=True)
class IntelTargetStatus:
    runtime_id: int
    state: str
    quest_status: int | None


@dataclass(frozen=True, slots=True)
class IntelStatusSnapshot:
    role: str
    kingdom: int
    targets: tuple[IntelTargetStatus, ...]


@dataclass(frozen=True, slots=True)
class MarchReceipt:
    role: str
    kingdom: int
    quality: str
    quality_id: int
    target: IntelItem
    request_dispatched: bool


@dataclass(frozen=True, slots=True)
class ClaimReceipt:
    role: str
    kingdom: int
    target_ids: tuple[int, ...]
    request_dispatched: bool
    idempotent: bool


@dataclass(frozen=True, slots=True)
class SceneStatus:
    role: str
    kingdom: int
    scene_type: int | None
    map_type: int | None
    class_name: str
    is_world: bool
    is_city: bool
    loading: bool | None
    transition: bool | None


INTEL_PENDING = "PENDING"
INTEL_COMPLETED = "COMPLETED"
INTEL_MISSING = "MISSING"
INTEL_STATES = frozenset((INTEL_PENDING, INTEL_COMPLETED, INTEL_MISSING))


def normalize_quality(value: str) -> str:
    if not isinstance(value, str):
        raise BusinessError("quality must be text")
    quality = value.strip().lower()
    quality = QUALITY_ALIASES.get(quality, quality)
    if quality not in QUALITY_IDS:
        allowed = ", ".join((*QUALITY_IDS, *QUALITY_ALIASES))
        raise BusinessError(f"quality must be one of: {allowed}")
    return quality


def validate_role_whitelist(roles: Sequence[str]) -> tuple[str, ...]:
    if isinstance(roles, (str, bytes)):
        raise BusinessError("device roles must be a configured array")
    result: list[str] = []
    seen: set[str] = set()
    for index, role in enumerate(roles):
        if not isinstance(role, str) or not role:
            raise BusinessError(f"device roles[{index}] must be non-empty text")
        encoded = role.encode("utf-8")
        if len(encoded) > 64:
            raise BusinessError(f"device roles[{index}] exceeds 64 UTF-8 bytes")
        if any(ord(char) < 32 or ord(char) == 127 for char in role):
            raise BusinessError(f"device roles[{index}] contains control characters")
        if role in seen:
            raise BusinessError(f"device role {role!r} is duplicated")
        seen.add(role)
        result.append(role)
    if not result:
        raise BusinessError(
            "the selected device has no configured role whitelist"
        )
    if len(result) > 16:
        raise BusinessError("a device role whitelist cannot exceed 16 entries")
    return tuple(result)


def normalize_target_ids(target_ids: Sequence[int]) -> tuple[int, ...]:
    if isinstance(target_ids, (str, bytes)):
        raise BusinessError("intelligence target ids must be an array")
    result: list[int] = []
    seen: set[int] = set()
    for index, runtime_id in enumerate(target_ids):
        if (
            isinstance(runtime_id, bool)
            or not isinstance(runtime_id, int)
            or runtime_id <= 0
        ):
            raise BusinessError(
                f"intelligence target ids[{index}] must be a positive integer"
            )
        if runtime_id in seen:
            raise BusinessError(
                f"intelligence target id {runtime_id} is duplicated"
            )
        seen.add(runtime_id)
        result.append(runtime_id)
    if not result:
        raise BusinessError("at least one intelligence target id is required")
    if len(result) > 128:
        raise BusinessError("cannot track more than 128 intelligence targets")
    return tuple(result)


def script_sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _finalize_lua(source: str) -> str:
    # The native bridge has a fixed source buffer. Removing indentation and
    # blank lines preserves Lua token boundaries while keeping guarded stage
    # scripts comfortably below that hard limit.
    code = "\n".join(line.strip() for line in source.splitlines() if line.strip()) + "\n"
    size = len(code.encode("utf-8"))
    if size >= LUA_BRIDGE_CODE_CAPACITY:
        raise BusinessError(
            f"generated Lua source is {size} UTF-8 bytes; bridge limit is "
            f"{LUA_BRIDGE_CODE_CAPACITY - 1}"
        )
    return code


def _lua_role_table(roles: Sequence[str]) -> str:
    validated = validate_role_whitelist(roles)
    return ", ".join(
        f'["{role.encode("utf-8").hex()}"] = true' for role in validated
    )


_LUA_COMMON = r'''
local EXPECTED_KINGDOM = 4549
local ALLOWED_ROLES = { __ROLE_TABLE__ }
local QUALITY_NAMES = { [2] = "green", [3] = "blue", [4] = "purple", [5] = "yellow" }

local function fail(message)
    error("mumu-autotask: " .. message, 0)
end

local function integer(value, label, allow_zero)
    if type(value) ~= "number" or value ~= math.floor(value) then
        fail(label .. " is not an integer")
    end
    if value < 0 or (not allow_zero and value == 0) then
        fail(label .. " is outside the accepted range")
    end
    return value
end

local function call(object, method_name, label)
    if type(object) ~= "table" or type(object[method_name]) ~= "function" then
        fail(label .. " method is unavailable")
    end
    local ok, value = pcall(object[method_name], object)
    if not ok then
        fail(label .. " method failed")
    end
    return value
end

local function hex(value)
    if type(value) ~= "string" or value == "" then
        fail("active role is unavailable")
    end
    return (value:gsub(".", function(character)
        return string.format("%02x", string.byte(character))
    end))
end

local function checked_identity()
    if type(GCtrl) ~= "table" or type(GCtrl.PlayerCtrl) ~= "table" then
        fail("PlayerCtrl is unavailable")
    end
    local role_hex = hex(call(GCtrl.PlayerCtrl, "GetPlayerName", "player name"))
    if ALLOWED_ROLES[role_hex] ~= true then
        fail("active role is not in this device whitelist")
    end
    local kid = integer(
        call(GCtrl.PlayerCtrl, "GetPlayerKid", "player kingdom"),
        "player kingdom",
        false
    )
    local server_id = integer(
        call(GCtrl.PlayerCtrl, "GetPlayerServerId", "player server"),
        "player server",
        false
    )
    if kid ~= EXPECTED_KINGDOM or server_id ~= EXPECTED_KINGDOM then
        fail("active player kingdom/server is not 4549")
    end
    return role_hex, server_id
end

local function quest_integer(quest, method_name, label, allow_zero)
    return integer(call(quest, method_name, label), label, allow_zero)
end

local function collect_monster_intel()
    if type(GCtrl) ~= "table" or type(GCtrl.RadarCtrl) ~= "table" then
        fail("RadarCtrl is unavailable")
    end
    local quest_map = call(GCtrl.RadarCtrl, "GetQuestDataMap", "quest map")
    if type(quest_map) ~= "table" then
        fail("quest map is not a table")
    end
    local items = {}
    for runtime_id, quest in pairs(quest_map) do
        local quest_type = quest_integer(quest, "GetQuestType", "quest type", false)
        local quality_id = quest_integer(quest, "GetQuality", "quality", false)
        local quality = QUALITY_NAMES[quality_id]
        if quest_type == 1 and quality ~= nil then
            local shown = call(quest, "IsShowInWorld", "world visibility")
            local status = integer(quest._status, "quest status", true)
            local expires_at = integer(quest._expireTime, "expire time", true)
            local valid_time = quest_integer(quest, "GetValidTime", "valid time", true)
            if shown == true and status == 1 and valid_time > 30 then
            local config = call(quest, "GetQuestConfig", "quest config")
            if type(config) ~= "table" then
                fail("quest config is unavailable")
            end
            local monster_id = integer(config.condition, "monster id", false)
            local stamina_cost = integer(
                config.stamtina_expend,
                "stamina cost",
                false
            )
            local runtime_value = integer(runtime_id, "runtime id", false)
            local object_id = quest_integer(quest, "GetId", "quest runtime id", false)
            if object_id ~= runtime_value then
                fail("quest map key and runtime id disagree")
            end
            local item = {
                runtime_id = runtime_value,
                quest_id = integer(quest._questId, "quest id", false),
                status = status,
                world_x = integer(quest._worldX, "world x", true),
                world_y = integer(quest._worldY, "world y", true),
                expires_at = expires_at,
                quality = quality,
                quality_id = quality_id,
                monster_id = monster_id,
                level = quest_integer(quest, "GetLevel", "monster level", false),
                stamina_cost = stamina_cost,
                object = quest,
            }
            items[#items + 1] = item
            end
        end
    end
    if #items > 128 then
        fail("monster intelligence count exceeds 128")
    end
    table.sort(items, function(left, right)
        if left.quality_id ~= right.quality_id then
            return left.quality_id < right.quality_id
        end
        if left.expires_at ~= right.expires_at then
            return left.expires_at < right.expires_at
        end
        return left.runtime_id < right.runtime_id
    end)
    return items
end

local function exact_intel_statuses(target_ids)
    if type(target_ids) ~= "table" or #target_ids == 0 or #target_ids > 128 then
        fail("target id list is invalid")
    end
    if type(GCtrl) ~= "table" or type(GCtrl.RadarCtrl) ~= "table" then
        fail("RadarCtrl is unavailable")
    end
    local quest_map = call(GCtrl.RadarCtrl, "GetQuestDataMap", "quest map")
    if type(quest_map) ~= "table" then
        fail("quest map is not a table")
    end
    local statuses = {}
    for _, runtime_id in ipairs(target_ids) do
        local quest = quest_map[runtime_id]
        local state = "MISSING"
        local raw_status = "missing"
        if quest ~= nil then
            if type(quest) ~= "table"
                or quest_integer(
                    quest,
                    "GetId",
                    "quest runtime id",
                    false
                ) ~= runtime_id then
                fail("quest map key and runtime id disagree")
            end
            if quest_integer(quest, "GetQuestType", "quest type", false) ~= 1 then
                fail("requested intelligence id is not a monster quest")
            end
            local status = integer(quest._status, "quest status", true)
            local completed = call(quest, "IsCompleted", "quest completion")
            if type(completed) ~= "boolean" then
                fail("quest completion is not boolean")
            end
            raw_status = tostring(status)
            if completed == true then
                state = "COMPLETED"
            else
                state = "PENDING"
            end
        end
        statuses[#statuses + 1] = {
            runtime_id = runtime_id,
            state = state,
            raw_status = raw_status,
        }
    end
    return statuses
end

local function require_target(
    runtime_id,
    quest_id,
    quality_id,
    world_x,
    world_y,
    expires_at,
    monster_id,
    level,
    stamina_cost
)
    local quest_map = call(GCtrl.RadarCtrl, "GetQuestDataMap", "quest map")
    local quest = quest_map[runtime_id]
    if type(quest) ~= "table" then
        fail("selected intelligence no longer exists")
    end
    if quest_integer(quest, "GetId", "quest runtime id", false) ~= runtime_id
        or integer(quest._questId, "quest id", false) ~= quest_id
        or quest_integer(quest, "GetQuestType", "quest type", false) ~= 1
        or quest_integer(quest, "GetQuality", "quality", false) ~= quality_id
        or integer(quest._worldX, "world x", true) ~= world_x
        or integer(quest._worldY, "world y", true) ~= world_y
        or integer(quest._expireTime, "expire time", false) ~= expires_at then
        fail("selected intelligence identity changed")
    end
    if integer(quest._status, "quest status", true) ~= 1 then
        fail("selected intelligence is not available")
    end
    if call(quest, "IsShowInWorld", "world visibility") ~= true then
        fail("selected intelligence is no longer shown in world")
    end
    if quest_integer(quest, "GetValidTime", "valid time", true) <= 30 then
        fail("selected intelligence is expired or too close to expiry")
    end
    if quest_integer(quest, "GetLevel", "monster level", false) ~= level then
        fail("selected intelligence monster level changed")
    end
    local config = call(quest, "GetQuestConfig", "quest config")
    if type(config) ~= "table" then
        fail("quest config is unavailable")
    end
    if integer(config.condition, "monster id", false) ~= monster_id then
        fail("selected intelligence monster id changed")
    end
    if integer(config.stamtina_expend, "stamina cost", false) ~= stamina_cost then
        fail("selected intelligence stamina cost changed")
    end
    return quest, config
end

local function exact_expedition_view(runtime_id, config, world_x, world_y, require_ready)
    if type(GModule) ~= "table" or type(GModule.UIModule) ~= "table"
        or type(GViewId) ~= "table" or GViewId.EXPEDITION == nil then
        fail("expedition UI module is unavailable")
    end
    local view = GModule.UIModule:FindOpenedView(GViewId.EXPEDITION)
    if view == nil then
        return nil, false
    end
    if type(view) ~= "table" or type(view.pointEnd) ~= "table"
        or type(view.extra) ~= "table"
        or view.pointEnd.x ~= world_x or view.pointEnd.y ~= world_y
        or view.extra.event_id ~= runtime_id
        or view.targetId ~= config.condition
        or view.marchMapType ~= GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
        or view.marchType ~= WorldMapDefine.march_type.transaction_slg
        or view.mapObjType ~= WorldMapDefine.mapobj_type.map_monster then
        fail("opened expedition does not match the selected intelligence")
    end
    local ready = type(view.IsLoaded) == "function"
        and type(view.IsOpen) == "function"
        and view:IsLoaded()
        and view:IsOpen()
        and type(view.showHeroList) == "table"
        and type(view.soldierList) == "table"
        and type(view.formationNumLimt) == "number"
        and view.allStamina ~= nil
        and view.isGoOn ~= nil
    if require_ready and not ready then
        fail("expedition view is not fully initialized")
    end
    return view, ready
end

local function march_method(march, method_name)
    local object_type = type(march)
    if object_type ~= "table" and object_type ~= "userdata" then
        return nil
    end
    local method = march[method_name]
    if type(method) ~= "function" then
        return nil
    end
    local ok, first, second, third, fourth = pcall(method, march)
    if not ok then
        return nil
    end
    return first, second, third, fourth
end

local function march_event_id(march)
    local data = march_method(march, "GetData")
    if type(data) == "table" and type(data.transaction_slg) == "table" then
        local event_id = data.transaction_slg.event_id
        if type(event_id) == "number"
            and event_id == math.floor(event_id)
            and event_id > 0 then
            return event_id
        end
    end
    local extra = march_method(march, "_GetExtraData")
    if type(extra) == "table" then
        local event_id = extra.event_id
        if type(event_id) == "number"
            and event_id == math.floor(event_id)
            and event_id > 0 then
            return event_id
        end
    end
    return nil
end

local function self_march_map(server_id)
    if type(GCtrl) ~= "table"
        or type(GCtrl.WorldMarchCtrl) ~= "table"
        or type(GCtrl.WorldMarchCtrl.GetSelfMarchMap) ~= "function" then
        fail("self march map is unavailable")
    end
    local ok, march_map = pcall(
        GCtrl.WorldMarchCtrl.GetSelfMarchMap,
        GCtrl.WorldMarchCtrl,
        server_id
    )
    if not ok or type(march_map) ~= "table" then
        fail("self march map lookup failed")
    end
    return march_map
end

local function march_id(march, fallback)
    local value = march_method(march, "GetId")
    if type(value) == "number" and value == math.floor(value) and value > 0 then
        return value
    end
    if type(fallback) == "number" and fallback == math.floor(fallback) and fallback > 0 then
        return fallback
    end
    return nil
end

local function capture_self_march_ids(server_id)
    local ids = {}
    for key, march in pairs(self_march_map(server_id)) do
        local id = march_id(march, key)
        if id ~= nil then
            ids[id] = true
        end
    end
    _G.__MUMU_AUTOTASK_SELF_MARCH_IDS = ids
end

local function march_matches_target(
    march,
    fallback_id,
    runtime_id,
    monster_id,
    world_x,
    world_y
)
    local id = march_id(march, fallback_id)
    if id == nil or _G.__MUMU_AUTOTASK_SELF_MARCH_IDS[id] == true then
        return false
    end

    local data = march_method(march, "GetData")
    local transaction = type(data) == "table" and data.transaction_slg or nil
    if type(transaction) ~= "table" then
        return false
    end
    local target_monster = march_method(march, "GetTargetMapObjectId")
    if target_monster == nil then
        target_monster = transaction.monster_id
    end
    if target_monster ~= monster_id then
        return false
    end

    local end_x, end_y = march_method(march, "GetEndPos")
    if end_x ~= world_x or end_y ~= world_y then
        return false
    end
    -- The world_march Sproto response defines transaction_slg as atk_monster,
    -- whose only field is monster_id. Some servers therefore do not echo the
    -- request-only event_id. If it is present it must still match exactly.
    local event_id = march_event_id(march)
    if event_id ~= nil and event_id ~= runtime_id then
        return false
    end
    return true, event_id
end

local function has_self_march(runtime_id, server_id, monster_id, world_x, world_y)
    local snapshot = _G.__MUMU_AUTOTASK_SELF_MARCH_IDS
    if type(snapshot) ~= "table" then
        fail("self march snapshot is unavailable")
    end
    for key, march in pairs(self_march_map(server_id)) do
        local matched, event_id = march_matches_target(
            march,
            key,
            runtime_id,
            monster_id,
            world_x,
            world_y
        )
        if matched then
            return true, event_id
        end
    end
    return false, nil
end
'''


_INSPECT_INTEL_BODY = r'''
local role_hex, kingdom = checked_identity()
local items = collect_monster_intel()
local lines = {
    "MUMU_AUTOTASK\t1\tINTEL",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
}
for _, item in ipairs(items) do
    lines[#lines + 1] = table.concat({
        "ITEM",
        tostring(item.runtime_id),
        tostring(item.quest_id),
        tostring(item.status),
        tostring(item.world_x),
        tostring(item.world_y),
        tostring(item.expires_at),
        item.quality,
        tostring(item.quality_id),
        tostring(item.monster_id),
        tostring(item.level),
        tostring(item.stamina_cost),
    }, "\t")
end
lines[#lines + 1] = "END\t" .. tostring(#items)
local output = table.concat(lines, "\n")
if #output > 15000 then
    fail("intelligence output exceeds 15000 bytes")
end
return output
'''


def build_inspect_intel_lua(roles: Sequence[str]) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _INSPECT_INTEL_BODY))


def _target_ids_constants(target_ids: Sequence[int]) -> str:
    normalized = normalize_target_ids(target_ids)
    values = ", ".join(str(runtime_id) for runtime_id in normalized)
    return f"local TARGET_RUNTIME_IDS = {{ {values} }}\n"


_INTEL_STATUS_BODY = r'''
local role_hex, kingdom = checked_identity()
local statuses = exact_intel_statuses(TARGET_RUNTIME_IDS)
local lines = {
    "MUMU_AUTOTASK\t1\tINTEL_STATUS",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
}
for _, target in ipairs(statuses) do
    lines[#lines + 1] = table.concat({
        "TARGET",
        tostring(target.runtime_id),
        target.state,
        target.raw_status,
    }, "\t")
end
lines[#lines + 1] = "END\t" .. tostring(#statuses)
local output = table.concat(lines, "\n")
if #output > 15000 then
    fail("intelligence status output exceeds 15000 bytes")
end
return output
'''


_CLAIM_INTEL_BODY = r'''
local role_hex, kingdom = checked_identity()
local statuses = exact_intel_statuses(TARGET_RUNTIME_IDS)
local completed = 0
local pending = 0
for _, target in ipairs(statuses) do
    if target.state == "COMPLETED" then
        completed = completed + 1
    elseif target.state == "PENDING" then
        pending = pending + 1
    end
end
if pending ~= 0 then
    fail("cannot claim while requested intelligence is pending")
end
local sent = false
if completed > 0 then
    call(
        GCtrl.RadarCtrl,
        "RequestReceiveAllQuestReward",
        "receive all intelligence rewards"
    )
    sent = true
end
local target_line = { "TARGETS", tostring(#TARGET_RUNTIME_IDS) }
for _, runtime_id in ipairs(TARGET_RUNTIME_IDS) do
    target_line[#target_line + 1] = tostring(runtime_id)
end
return table.concat({
    "MUMU_AUTOTASK\t1\tCLAIM_INTEL",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    table.concat(target_line, "\t"),
    "SENT\t" .. (sent and "1" or "0"),
    "IDEMPOTENT\t" .. (sent and "0" or "1"),
    "END\t1",
}, "\n")
'''


def _target_ids_lua(
    roles: Sequence[str],
    target_ids: Sequence[int],
    body: str,
) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    constants = _target_ids_constants(target_ids)
    return _finalize_lua(textwrap.dedent(common + constants + body))


def build_intel_status_lua(
    roles: Sequence[str],
    target_ids: Sequence[int],
) -> str:
    return _target_ids_lua(roles, target_ids, _INTEL_STATUS_BODY)


def build_claim_intel_lua(
    roles: Sequence[str],
    target_ids: Sequence[int],
) -> str:
    return _target_ids_lua(roles, target_ids, _CLAIM_INTEL_BODY)


def _target_constants(target: IntelItem) -> str:
    if not isinstance(target, IntelItem):
        raise BusinessError("march target must be an IntelItem")
    numeric = {
        "runtime id": target.runtime_id,
        "quest id": target.quest_id,
        "status": target.status,
        "world x": target.world_x,
        "world y": target.world_y,
        "expiry": target.expires_at,
        "quality id": target.quality_id,
        "monster id": target.monster_id,
        "level": target.level,
        "stamina cost": target.stamina_cost,
    }
    for label, value in numeric.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BusinessError(f"march target {label} must be a non-negative integer")
    if (
        target.runtime_id == 0
        or target.quest_id == 0
        or target.expires_at == 0
        or target.monster_id == 0
        or target.level == 0
        or target.stamina_cost == 0
    ):
        raise BusinessError(
            "march target identifiers, expiry, monster id, and level must be positive"
        )
    quality = normalize_quality(target.quality)
    if quality != target.quality or QUALITY_IDS[quality] != target.quality_id:
        raise BusinessError("march target quality name/id disagree")
    if target.status != 1:
        raise BusinessError("march target is not available")
    return textwrap.dedent(
        f'''\
        local TARGET_RUNTIME_ID = {target.runtime_id}
        local TARGET_QUEST_ID = {target.quest_id}
        local TARGET_QUALITY_ID = {target.quality_id}
        local TARGET_WORLD_X = {target.world_x}
        local TARGET_WORLD_Y = {target.world_y}
        local TARGET_EXPIRES_AT = {target.expires_at}
        local TARGET_MONSTER_ID = {target.monster_id}
        local TARGET_LEVEL = {target.level}
        local TARGET_STAMINA_COST = {target.stamina_cost}
        '''
    )


def _target_lua(roles: Sequence[str], target: IntelItem, body: str) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _target_constants(target) + body))


_OPEN_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
local quest, config = require_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_MONSTER_ID,
    TARGET_LEVEL,
    TARGET_STAMINA_COST
)
local initial_status = integer(quest._status, "initial quest status", false)
if initial_status ~= 1 then
    fail("selected intelligence was not available at expedition open")
end
_G.__MUMU_AUTOTASK_INITIAL_STATUS = initial_status
_G.__MUMU_AUTOTASK_GO_INVOKED = false
local existing = GModule.UIModule:FindOpenedView(GViewId.EXPEDITION)
if existing ~= nil then
    fail("an expedition view is already open")
end
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.transaction_slg
local map_object_type = WorldMapDefine.mapobj_type.map_monster
if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
    march_map_type,
    march_type,
    nil,
    true
) then
    fail("no idle march queue is available")
end
local city_ok, city_x, city_y = pcall(
    GCtrl.WorldPlayerCtrl.GetPlayerCityPos,
    GCtrl.WorldPlayerCtrl
)
if not city_ok then
    fail("player city position lookup failed")
end
city_x = integer(city_x, "player city x", true)
city_y = integer(city_y, "player city y", true)
local world_ok, quest_x, quest_y = pcall(quest.GetWorldPos, quest)
if not world_ok or quest_x ~= TARGET_WORLD_X or quest_y ~= TARGET_WORLD_Y then
    fail("selected intelligence world position changed")
end
local open_ok = pcall(
    GModule.UIModule.OpenView,
    GModule.UIModule,
    GViewId.EXPEDITION,
    {
        marchMapType = march_map_type,
        marchType = march_type,
        mapObjType = map_object_type,
        targetId = config.condition,
        stamina = TARGET_STAMINA_COST,
        pointStart = { x = city_x, y = city_y },
        pointEnd = { x = TARGET_WORLD_X, y = TARGET_WORLD_Y },
        extra = { event_id = TARGET_RUNTIME_ID },
        guide = false,
    }
)
if not open_ok then
    fail("expedition view open failed")
end
return table.concat({
    "MUMU_AUTOTASK\t1\tOPEN",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "OPENED\t1",
    "END\t1",
}, "\n")
'''


_READY_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
local _, config = require_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_MONSTER_ID,
    TARGET_LEVEL,
    TARGET_STAMINA_COST
)
local _, ready = exact_expedition_view(
    TARGET_RUNTIME_ID,
    config,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    false
)
return table.concat({
    "MUMU_AUTOTASK\t1\tREADY",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "READY\t" .. (ready and "1" or "0"),
    "END\t1",
}, "\n")
'''


_COMMIT_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
local _, config = require_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_MONSTER_ID,
    TARGET_LEVEL,
    TARGET_STAMINA_COST
)
local view = exact_expedition_view(
    TARGET_RUNTIME_ID,
    config,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    true
)
capture_self_march_ids(kingdom)
if type(view.OnBtnAverageClick) ~= "function"
    or not pcall(view.OnBtnAverageClick, view) then
    fail("average formation failed")
end
local selected_ok, selected = pcall(
    view.StatisticalMagnitudeSoldiers,
    view,
    view.soldierList,
    view.formationNumLimt,
    0
)
if not selected_ok or type(selected) ~= "number" or selected <= 0 then
    fail("average formation selected no soldiers")
end
if GHelper.FormationHelper.IsHaveCaptain(view.showHeroList) ~= true then
    fail("average formation selected no captain")
end
_, config = require_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_MONSTER_ID,
    TARGET_LEVEL,
    TARGET_STAMINA_COST
)
view = exact_expedition_view(
    TARGET_RUNTIME_ID,
    config,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    true
)
_G.__MUMU_AUTOTASK_GO_INVOKED = true
if type(view.OnBtnGoOnClick) ~= "function"
    or not pcall(view.OnBtnGoOnClick, view) then
    fail("expedition go action failed")
end
return table.concat({
    "MUMU_AUTOTASK\t1\tCOMMIT",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "AVERAGE\t1",
    "GO\t1",
    "END\t1",
}, "\n")
'''


_DIRECT_COMMIT_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
local quest, config = require_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_MONSTER_ID,
    TARGET_LEVEL,
    TARGET_STAMINA_COST
)
local initial_status = integer(quest._status, "initial quest status", false)
if initial_status ~= 1 then
    fail("selected intelligence was not available before direct march")
end
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.transaction_slg
local map_object_type = WorldMapDefine.mapobj_type.map_monster
if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
    march_map_type,
    march_type,
    nil,
    true
) then
    fail("no idle march queue is available")
end
local world_ok, quest_x, quest_y = pcall(quest.GetWorldPos, quest)
if not world_ok or quest_x ~= TARGET_WORLD_X or quest_y ~= TARGET_WORLD_Y then
    fail("selected intelligence world position changed")
end
local extra = { event_id = TARGET_RUNTIME_ID }
local formation_march_type = GHelper.WorldMarchHelper.GetAttackMarchType(
    map_object_type
)
local hero_list = GHelper.ExpeditionHelper.GetRecommendedHeroList(
    false,
    false,
    formation_march_type,
    config.condition,
    march_map_type,
    extra
)
if type(hero_list) ~= "table"
    or GHelper.FormationHelper.IsHaveCaptain(hero_list) ~= true then
    fail("direct average formation selected no captain")
end
local fight_type = GDefine.HeroDefine.HeroAttrType.SLG
local formation_limit = GHelper.ExpeditionHelper.GetTroopLimit(
    march_map_type,
    hero_list,
    fight_type,
    extra
)
formation_limit = integer(formation_limit, "formation limit", false)
local yields = GHelper.ExpeditionHelper.GetResourceYields(march_type, nil)
if type(yields) ~= "number" then
    fail("resource yields is not numeric")
end
local open_params = {
    marchMapType = march_map_type,
    marchType = march_type,
    formationNumLimt = formation_limit,
    targetId = config.condition,
    yields = yields,
    isAttack = false,
}
local soldier_list = GHelper.ExpeditionHelper.GetSoldierInfoByMarchType(
    formation_march_type,
    0,
    false,
    open_params,
    nil
)
if type(soldier_list) ~= "table" then
    fail("direct soldier list is unavailable")
end
local averaged_soldiers = GHelper.FormationHelper.GetAverageSoldierList(
    march_map_type,
    soldier_list,
    formation_limit,
    false,
    extra
)
if type(averaged_soldiers) ~= "table" then
    fail("direct average soldier list is unavailable")
end
local selected = 0
for _, soldier in ipairs(averaged_soldiers) do
    if type(soldier) == "table" and type(soldier.selectNum) == "number" then
        selected = selected + soldier.selectNum
    end
end
if selected <= 0 then
    fail("direct average formation selected no soldiers")
end
local hero_id, soldier = GHelper.FormationHelper.DealWithExpeditionInfo(
    hero_list,
    averaged_soldiers
)
if type(hero_id) ~= "table" or type(soldier) ~= "table" then
    fail("direct formation payload is unavailable")
end
local blocked_ok, blocked = pcall(
    GHelper.ExpeditionHelper.IsBeforehandMarch,
    march_map_type,
    march_type,
    map_object_type,
    extra,
    true
)
if blocked_ok and blocked then
    fail("selected intelligence is already marching")
end
capture_self_march_ids(kingdom)
_G.__MUMU_AUTOTASK_INITIAL_STATUS = initial_status
_G.__MUMU_AUTOTASK_GO_INVOKED = true
local request_ok = pcall(
    GHelper.WorldMarchHelper.RequestMarchStartOff,
    march_map_type,
    march_type,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    {
        hero_id = hero_id,
        soldier = soldier,
    },
    extra
)
if not request_ok then
    fail("direct march request failed")
end
return table.concat({
    "MUMU_AUTOTASK\t1\tCOMMIT",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "AVERAGE\t1",
    "GO\t1",
    "END\t1",
}, "\n")
'''


_VERIFY_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
local quest_map = call(GCtrl.RadarCtrl, "GetQuestDataMap", "quest map")
local quest = quest_map[TARGET_RUNTIME_ID]
local status_text = "missing"
local status_proof = false
if quest == nil then
    status_text = "missing"
else
    if type(quest) ~= "table"
        or quest_integer(quest, "GetId", "quest runtime id", false) ~= TARGET_RUNTIME_ID
        or integer(quest._questId, "quest id", false) ~= TARGET_QUEST_ID
        or quest_integer(quest, "GetQuestType", "quest type", false) ~= 1
        or quest_integer(quest, "GetQuality", "quality", false) ~= TARGET_QUALITY_ID
        or integer(quest._worldX, "world x", true) ~= TARGET_WORLD_X
        or integer(quest._worldY, "world y", true) ~= TARGET_WORLD_Y
        or quest_integer(quest, "GetLevel", "monster level", false) ~= TARGET_LEVEL then
        fail("selected intelligence identity changed after go action")
    end
    local config = call(quest, "GetQuestConfig", "quest config")
    if type(config) ~= "table"
        or integer(config.condition, "monster id", false) ~= TARGET_MONSTER_ID then
        fail("selected intelligence monster changed after go action")
    end
    local status = integer(quest._status, "quest status", true)
    status_text = tostring(status)
    if status ~= 1 and status ~= 2 and status ~= 3 then
        fail("selected intelligence entered an unexpected status")
    end
    if _G.__MUMU_AUTOTASK_GO_INVOKED == true
        and _G.__MUMU_AUTOTASK_INITIAL_STATUS == 1
        and (status == 2 or status == 3) then
        status_proof = true
    end
end
local march_ok, march_found, march_event_id = pcall(
    has_self_march,
    TARGET_RUNTIME_ID,
    kingdom,
    TARGET_MONSTER_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y
)
if not march_ok then
    march_found = false
    march_event_id = nil
end
local accepted = march_found or status_proof
local proof = "NONE"
if march_found then
    proof = march_event_id ~= nil and "MARCH_EVENT" or "MARCH_FIELDS"
elseif status_proof then
    proof = "QUEST_STATUS"
end
return table.concat({
    "MUMU_AUTOTASK\t1\tVERIFY",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "ACCEPTED\t" .. (accepted and "1" or "0") .. "\tSTATUS\t" .. status_text,
    "MARCH\t" .. (march_found and "1" or "0") .. "\tEVENT\t"
        .. (march_event_id ~= nil and tostring(march_event_id)
            or (march_found and "missing" or "0")),
    "PROOF\t" .. proof,
    "END\t1",
}, "\n")
'''


_CLOSE_EXPEDITION_BODY = r'''
checked_identity()
_G.__MUMU_AUTOTASK_SELF_MARCH_IDS = nil
_G.__MUMU_AUTOTASK_INITIAL_STATUS = nil
_G.__MUMU_AUTOTASK_GO_INVOKED = nil
if type(GModule) == "table" and type(GModule.UIModule) == "table"
    and type(GViewId) == "table" and GViewId.EXPEDITION ~= nil
    and GModule.UIModule:FindOpenedView(GViewId.EXPEDITION) ~= nil then
    GModule.UIModule:CloseView(GViewId.EXPEDITION)
end
return "MUMU_AUTOTASK\t1\tCLOSE\nEND\t1"
'''


_SCENE_STATUS_BODY = r'''
local role_hex, kingdom = checked_identity()

local function maybe_call(object, method_name)
    if type(object) ~= "table" or type(object[method_name]) ~= "function" then
        return nil
    end
    local ok, value = pcall(object[method_name], object)
    if not ok then
        return nil
    end
    return value
end

local scene_module = type(GModule) == "table" and GModule.SceneModule or nil
local scene_type = maybe_call(scene_module, "GetSceneType")
local map_type = maybe_call(scene_module, "GetMapType")
local loading = maybe_call(scene_module, "IsLoading")
local transition = maybe_call(scene_module, "IsInTransition")
local cur_scene = type(scene_module) == "table" and scene_module._curScene or nil
local class_name = "unknown"
if type(cur_scene) == "table"
    and type(cur_scene.class) == "table"
    and type(cur_scene.class.__cname) == "string" then
    class_name = cur_scene.class.__cname
end
local is_world = class_name == "WorldScene" or scene_type == 3
local is_city = class_name == "CityScene" or scene_type == 2

return table.concat({
    "MUMU_AUTOTASK\t1\tSCENE",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "SCENE\t" .. (type(scene_type) == "number" and tostring(scene_type) or "missing")
        .. "\tCLASS\t" .. class_name,
    "MAP\t" .. (type(map_type) == "number" and tostring(map_type) or "missing"),
    "WORLD\t" .. (is_world and "1" or "0")
        .. "\tCITY\t" .. (is_city and "1" or "0"),
    "BUSY\tLOADING\t" .. (type(loading) == "boolean" and tostring(loading) or "missing")
        .. "\tTRANSITION\t" .. (type(transition) == "boolean" and tostring(transition) or "missing"),
    "END\t1",
}, "\n")
'''


_INSTALL_MARCH_CAPTURE_HOOK_BODY = r'''
local role_hex, kingdom = checked_identity()
local HOOK_KEY = "__MUMU_AUTOTASK_MARCH_CAPTURE_HOOK"

local function safe_text(value)
    local text = tostring(value)
    text = text:gsub("\\", "\\\\")
        :gsub("\t", "\\t")
        :gsub("\r", "\\r")
        :gsub("\n", "\\n")
    if #text > 240 then
        text = text:sub(1, 240) .. "...<truncated>"
    end
    return text
end

local function key_text(value)
    if type(value) == "number" or type(value) == "boolean" then
        return tostring(value)
    end
    return safe_text(value)
end

local function emit(lines, path, value, depth, seen, budget)
    if budget.count >= budget.limit then
        return
    end
    local value_type = type(value)
    if value_type == "nil"
        or value_type == "boolean"
        or value_type == "number"
        or value_type == "string" then
        budget.count = budget.count + 1
        lines[#lines + 1] = table.concat({
            "FIELD",
            path,
            value_type,
            safe_text(value),
        }, "\t")
        return
    end
    if value_type ~= "table" then
        budget.count = budget.count + 1
        lines[#lines + 1] = table.concat({
            "FIELD",
            path,
            value_type,
            safe_text(value),
        }, "\t")
        return
    end
    if seen[value] then
        budget.count = budget.count + 1
        lines[#lines + 1] = table.concat({
            "FIELD",
            path,
            "table",
            "<cycle>",
        }, "\t")
        return
    end
    seen[value] = true
    budget.count = budget.count + 1
    lines[#lines + 1] = table.concat({
        "FIELD",
        path,
        "table",
        safe_text(value),
    }, "\t")
    if depth >= 5 then
        return
    end
    local ok, first_key = pcall(next, value, nil)
    if not ok then
        budget.count = budget.count + 1
        lines[#lines + 1] = table.concat({
            "FIELD",
            path .. ".<pairs>",
            "error",
            safe_text(first_key),
        }, "\t")
        return
    end
    local keys = {}
    local key = first_key
    local guard = 0
    while key ~= nil and guard < 120 do
        guard = guard + 1
        keys[#keys + 1] = key
        local next_ok, next_key = pcall(next, value, key)
        if not next_ok then
            break
        end
        key = next_key
    end
    table.sort(keys, function(left, right)
        local left_type = type(left)
        local right_type = type(right)
        if left_type == right_type and left_type == "number" then
            return left < right
        end
        return tostring(left) < tostring(right)
    end)
    for _, child_key in ipairs(keys) do
        if budget.count >= budget.limit then
            break
        end
        local child_ok, child_value = pcall(function()
            return value[child_key]
        end)
        if child_ok then
            emit(
                lines,
                path .. "." .. key_text(child_key),
                child_value,
                depth + 1,
                seen,
                budget
            )
        else
            budget.count = budget.count + 1
            lines[#lines + 1] = table.concat({
                "FIELD",
                path .. "." .. key_text(child_key),
                "error",
                safe_text(child_value),
            }, "\t")
        end
    end
end

local function snapshot_call(event_name, ...)
    local hook = _G[HOOK_KEY]
    if type(hook) ~= "table" then
        return
    end
    local lines = {
        "RECORD\t" .. tostring((hook.sequence or 0) + 1) .. "\t" .. event_name,
    }
    hook.sequence = (hook.sequence or 0) + 1
    local argc = select("#", ...)
    lines[#lines + 1] = "ARGC\t" .. tostring(argc)
    local budget = { count = 0, limit = 360 }
    for index = 1, argc do
        local value = select(index, ...)
        emit(lines, "arg" .. tostring(index), value, 0, {}, budget)
    end
    local record = table.concat(lines, "\n")
    if #record > 12000 then
        record = record:sub(1, 12000) .. "\nTRUNCATED\t1"
    end
    hook.records[#hook.records + 1] = record
    while #hook.records > 12 do
        table.remove(hook.records, 1)
    end
end

local function protected_snapshot(event_name, ...)
    local ok, err = pcall(snapshot_call, event_name, ...)
    if not ok then
        local hook = _G[HOOK_KEY]
        if type(hook) == "table" and type(hook.records) == "table" then
            hook.sequence = (hook.sequence or 0) + 1
            hook.records[#hook.records + 1] = table.concat({
                "RECORD\t" .. tostring(hook.sequence) .. "\t" .. event_name,
                "CAPTURE_ERROR\t" .. safe_text(err),
            }, "\n")
        end
    end
end

local hook = _G[HOOK_KEY]
if type(hook) ~= "table" then
    hook = {
        installed = false,
        originals = {},
        records = {},
        sequence = 0,
    }
    _G[HOOK_KEY] = hook
end

local wrapped = {}
local function wrap(owner, method_name, event_name)
    if type(owner) ~= "table" or type(method_name) ~= "string" then
        return false, "owner unavailable"
    end
    local original = owner[method_name]
    if type(original) ~= "function" then
        return false, "function unavailable"
    end
    if hook.originals[event_name] ~= nil then
        wrapped[#wrapped + 1] = event_name .. ":already"
        return true, "already wrapped"
    end
    local wrapper = function(...)
        protected_snapshot(event_name, ...)
        return original(...)
    end
    hook.originals[event_name] = {
        owner = owner,
        method_name = method_name,
        original = original,
        wrapper = wrapper,
    }
    owner[method_name] = wrapper
    wrapped[#wrapped + 1] = event_name .. ":wrapped"
    return true, "wrapped"
end

local expedition_view = nil
local view_ok, view_or_error = pcall(
    require,
    "game.module.ui.view.formation.ExpeditionView"
)
if view_ok and type(view_or_error) == "table" then
    expedition_view = view_or_error
end

wrap(GHelper and GHelper.WorldMarchHelper, "RequestMarchStartOff",
    "WorldMarchHelper.RequestMarchStartOff")
wrap(GCtrl and GCtrl.WorldMarchCtrl, "RequestWorldMarchStartOff",
    "WorldMarchCtrl.RequestWorldMarchStartOff")
hook.installed = true

local lines = {
    "MUMU_AUTOTASK\t1\tMARCH_CAPTURE_HOOK",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "INSTALLED\t1",
    "EXPEDITION_VIEW\t" .. (expedition_view ~= nil and "1" or "0"),
}
for _, item in ipairs(wrapped) do
    lines[#lines + 1] = "WRAP\t" .. item
end
lines[#lines + 1] = "END\t1"
return table.concat(lines, "\n")
'''


_MARCH_CAPTURE_COMMON = r'''
local EXPECTED_KINGDOM = 4549
local ALLOWED_ROLES = { __ROLE_TABLE__ }

local function fail(message)
    error("mumu-autotask: " .. message, 0)
end

local function hex(value)
    if type(value) ~= "string" or value == "" then
        fail("active role is unavailable")
    end
    return (value:gsub(".", function(character)
        return string.format("%02x", string.byte(character))
    end))
end

local function checked_identity()
    if type(GCtrl) ~= "table" or type(GCtrl.PlayerCtrl) ~= "table" then
        fail("PlayerCtrl is unavailable")
    end
    local player = GCtrl.PlayerCtrl
    if type(player.GetPlayerName) ~= "function"
        or type(player.GetPlayerKid) ~= "function"
        or type(player.GetPlayerServerId) ~= "function" then
        fail("player identity methods are unavailable")
    end
    local ok_name, name = pcall(player.GetPlayerName, player)
    if not ok_name then
        fail("player name lookup failed")
    end
    local role_hex = hex(name)
    if ALLOWED_ROLES[role_hex] ~= true then
        fail("active role is not in this device whitelist")
    end
    local ok_kid, kid = pcall(player.GetPlayerKid, player)
    local ok_server, server_id = pcall(player.GetPlayerServerId, player)
    if not ok_kid or not ok_server or kid ~= EXPECTED_KINGDOM
        or server_id ~= EXPECTED_KINGDOM then
        fail("active player kingdom/server is not 4549")
    end
    return role_hex, server_id
end
'''


_READ_MARCH_CAPTURE_HOOK_BODY = r'''
local role_hex, kingdom = checked_identity()
local HOOK_KEY = "__MUMU_AUTOTASK_MARCH_CAPTURE_HOOK"
local hook = _G[HOOK_KEY]
local records = {}
if type(hook) == "table" and type(hook.records) == "table" then
    records = hook.records
end
local lines = {
    "MUMU_AUTOTASK\t1\tMARCH_CAPTURE_RECORDS",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "COUNT\t" .. tostring(#records),
}
for index, record in ipairs(records) do
    lines[#lines + 1] = "BEGIN_RECORD\t" .. tostring(index)
    lines[#lines + 1] = record
    lines[#lines + 1] = "END_RECORD\t" .. tostring(index)
end
lines[#lines + 1] = "END\t1"
local output = table.concat(lines, "\n")
if #output > 15000 then
    output = output:sub(1, 15000) .. "\nOUTPUT_TRUNCATED\t1\nEND\t1"
end
return output
'''


_UNINSTALL_MARCH_CAPTURE_HOOK_BODY = r'''
local role_hex, kingdom = checked_identity()
local HOOK_KEY = "__MUMU_AUTOTASK_MARCH_CAPTURE_HOOK"
local hook = _G[HOOK_KEY]
local restored = 0
if type(hook) == "table" and type(hook.originals) == "table" then
    for _, entry in pairs(hook.originals) do
        if type(entry) == "table"
            and type(entry.owner) == "table"
            and type(entry.method_name) == "string"
            and type(entry.original) == "function"
            and entry.owner[entry.method_name] == entry.wrapper then
            entry.owner[entry.method_name] = entry.original
            restored = restored + 1
        end
    end
end
_G[HOOK_KEY] = nil
return table.concat({
    "MUMU_AUTOTASK\t1\tMARCH_CAPTURE_UNHOOK",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "RESTORED\t" .. tostring(restored),
    "END\t1",
}, "\n")
'''


def build_open_march_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _OPEN_MARCH_BODY)


def build_march_ready_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _READY_MARCH_BODY)


def build_commit_march_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _COMMIT_MARCH_BODY)


def build_direct_commit_march_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _DIRECT_COMMIT_MARCH_BODY)


def build_verify_march_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _VERIFY_MARCH_BODY)


def build_close_expedition_lua(roles: Sequence[str]) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _CLOSE_EXPEDITION_BODY))


def build_scene_status_lua(roles: Sequence[str]) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _SCENE_STATUS_BODY))


def build_install_march_capture_hook_lua(roles: Sequence[str]) -> str:
    common = _MARCH_CAPTURE_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(
        textwrap.dedent(common + _INSTALL_MARCH_CAPTURE_HOOK_BODY)
    )


def build_read_march_capture_hook_lua(roles: Sequence[str]) -> str:
    common = _MARCH_CAPTURE_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _READ_MARCH_CAPTURE_HOOK_BODY))


def build_uninstall_march_capture_hook_lua(roles: Sequence[str]) -> str:
    common = _MARCH_CAPTURE_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(
        textwrap.dedent(common + _UNINSTALL_MARCH_CAPTURE_HOOK_BODY)
    )


def select_march_target(
    snapshot: IntelSnapshot,
    quality: str,
    runtime_id: int | None = None,
) -> IntelItem:
    requested = normalize_quality(quality)
    if snapshot.kingdom != ALLOWED_KINGDOM:
        raise BusinessError("cannot select a march target outside kingdom 4549")
    if runtime_id is not None:
        if isinstance(runtime_id, bool) or not isinstance(runtime_id, int) or runtime_id <= 0:
            raise BusinessError("march target runtime id must be a positive integer")
        exact = [item for item in snapshot.items if item.runtime_id == runtime_id]
        if not exact:
            raise BusinessError(
                f"requested intelligence target {runtime_id} is no longer available"
            )
        target = exact[0]
        if target.status != 1:
            raise BusinessError(
                f"requested intelligence target {runtime_id} is not available"
            )
        if target.quality != requested:
            raise BusinessError(
                f"requested intelligence target {runtime_id} is {target.quality}, "
                f"not {requested}"
            )
        return target
    matches = [
        item
        for item in snapshot.items
        if item.quality == requested and item.status == 1
    ]
    if not matches:
        raise BusinessError(f"no available {requested} skull intelligence was found")
    return min(matches, key=lambda item: (item.expires_at, item.runtime_id))


def _parse_integer(value: str, location: str, *, allow_zero: bool) -> int:
    if _INTEGER_PATTERN.fullmatch(value) is None:
        raise BusinessError(f"{location} is not a canonical non-negative integer")
    result = int(value)
    if not allow_zero and result == 0:
        raise BusinessError(f"{location} must be positive")
    return result


def _parse_role(value: str, allowed_roles: Sequence[str]) -> str:
    if _ROLE_HEX_PATTERN.fullmatch(value) is None:
        raise BusinessError("ROLE is not canonical lowercase UTF-8 hex")
    try:
        role = bytes.fromhex(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise BusinessError("ROLE is not valid UTF-8 hex") from exc
    roles = validate_role_whitelist(allowed_roles)
    if role not in roles:
        raise BusinessError("reported role is not in the device whitelist")
    return role


def _parse_item(fields: list[str], location: str) -> IntelItem:
    if len(fields) != 12 or fields[0] != "ITEM":
        raise BusinessError(f"{location} must contain exactly 12 ITEM fields")
    quality = normalize_quality(fields[7])
    if quality != fields[7]:
        raise BusinessError(f"{location} quality must use its canonical name")
    quality_id = _parse_integer(fields[8], f"{location} quality id", allow_zero=False)
    if QUALITY_IDS[quality] != quality_id:
        raise BusinessError(f"{location} quality name/id disagree")
    return IntelItem(
        runtime_id=_parse_integer(fields[1], f"{location} runtime id", allow_zero=False),
        quest_id=_parse_integer(fields[2], f"{location} quest id", allow_zero=False),
        status=_parse_integer(fields[3], f"{location} status", allow_zero=True),
        world_x=_parse_integer(fields[4], f"{location} world x", allow_zero=True),
        world_y=_parse_integer(fields[5], f"{location} world y", allow_zero=True),
        expires_at=_parse_integer(fields[6], f"{location} expiry", allow_zero=False),
        quality=quality,
        quality_id=quality_id,
        monster_id=_parse_integer(fields[9], f"{location} monster id", allow_zero=False),
        level=_parse_integer(fields[10], f"{location} level", allow_zero=False),
        stamina_cost=_parse_integer(
            fields[11], f"{location} stamina cost", allow_zero=False
        ),
    )


def _protocol_lines(output: str, kind: str) -> list[list[str]]:
    if not isinstance(output, str) or not output:
        raise BusinessError("Lua business output is empty")
    if len(output.encode("utf-8")) > 15000:
        raise BusinessError("Lua business output exceeds 15000 bytes")
    if "\r" in output or output.endswith("\n"):
        raise BusinessError("Lua business output has non-canonical line endings")
    lines = output.split("\n")
    if any(not line for line in lines):
        raise BusinessError("Lua business output contains an empty line")
    fields = [line.split("\t") for line in lines]
    if fields[0] != ["MUMU_AUTOTASK", "1", kind]:
        raise BusinessError(f"Lua business output is not {kind} protocol v1")
    return fields


def parse_intel_output(
    output: str,
    allowed_roles: Sequence[str],
) -> IntelSnapshot:
    lines = _protocol_lines(output, "INTEL")
    if len(lines) < 4 or len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("INTEL output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    if len(lines[2]) != 2 or lines[2][0] != "KINGDOM":
        raise BusinessError("INTEL output is missing KINGDOM")
    kingdom = _parse_integer(lines[2][1], "KINGDOM", allow_zero=False)
    if kingdom != ALLOWED_KINGDOM:
        raise BusinessError("INTEL output kingdom is not 4549")
    if len(lines[-1]) != 2 or lines[-1][0] != "END":
        raise BusinessError("INTEL output is missing END")
    count = _parse_integer(lines[-1][1], "END count", allow_zero=True)
    item_lines = lines[3:-1]
    if count != len(item_lines):
        raise BusinessError("INTEL END count does not match ITEM lines")
    if count > 128:
        raise BusinessError("INTEL output contains more than 128 items")
    items = tuple(
        _parse_item(fields, f"ITEM[{index}]")
        for index, fields in enumerate(item_lines)
    )
    runtime_ids = [item.runtime_id for item in items]
    if len(runtime_ids) != len(set(runtime_ids)):
        raise BusinessError("INTEL output contains duplicate runtime ids")
    expected_order = sorted(
        items,
        key=lambda item: (item.quality_id, item.expires_at, item.runtime_id),
    )
    if list(items) != expected_order:
        raise BusinessError("INTEL items are not in canonical order")
    return IntelSnapshot(role=role, kingdom=kingdom, items=items)


def parse_intel_status_output(
    output: str,
    allowed_roles: Sequence[str],
    target_ids: Sequence[int],
) -> IntelStatusSnapshot:
    expected_ids = normalize_target_ids(target_ids)
    lines = _protocol_lines(output, "INTEL_STATUS")
    if len(lines) != len(expected_ids) + 4:
        raise BusinessError("INTEL_STATUS output has an unexpected line count")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("INTEL_STATUS output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    if lines[2] != ["KINGDOM", str(ALLOWED_KINGDOM)]:
        raise BusinessError("INTEL_STATUS output kingdom is not 4549")

    targets: list[IntelTargetStatus] = []
    for index, (runtime_id, fields) in enumerate(
        zip(expected_ids, lines[3:-1], strict=True)
    ):
        if (
            len(fields) != 4
            or fields[0] != "TARGET"
            or fields[1] != str(runtime_id)
            or fields[2] not in INTEL_STATES
        ):
            raise BusinessError(
                f"INTEL_STATUS TARGET[{index}] does not match the request"
            )
        state = fields[2]
        raw_status = fields[3]
        quest_status: int | None
        if state == INTEL_MISSING:
            if raw_status != "missing":
                raise BusinessError(
                    f"INTEL_STATUS TARGET[{index}] missing state is inconsistent"
                )
            quest_status = None
        else:
            quest_status = _parse_integer(
                raw_status,
                f"INTEL_STATUS TARGET[{index}] quest status",
                allow_zero=True,
            )
        targets.append(IntelTargetStatus(runtime_id, state, quest_status))

    if lines[-1] != ["END", str(len(expected_ids))]:
        raise BusinessError("INTEL_STATUS output has an invalid terminator")
    return IntelStatusSnapshot(
        role=role,
        kingdom=ALLOWED_KINGDOM,
        targets=tuple(targets),
    )


def parse_claim_intel_output(
    output: str,
    allowed_roles: Sequence[str],
    target_ids: Sequence[int],
) -> ClaimReceipt:
    expected_ids = normalize_target_ids(target_ids)
    lines = _protocol_lines(output, "CLAIM_INTEL")
    if len(lines) != 7:
        raise BusinessError("CLAIM_INTEL output must contain exactly 7 lines")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("CLAIM_INTEL output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    if lines[2] != ["KINGDOM", str(ALLOWED_KINGDOM)]:
        raise BusinessError("CLAIM_INTEL output kingdom is not 4549")
    expected_target_line = [
        "TARGETS",
        str(len(expected_ids)),
        *(str(runtime_id) for runtime_id in expected_ids),
    ]
    if lines[3] != expected_target_line:
        raise BusinessError("CLAIM_INTEL output targets do not match the request")
    if lines[4] not in (["SENT", "0"], ["SENT", "1"]):
        raise BusinessError("CLAIM_INTEL output has an invalid dispatch state")
    if lines[5] not in (["IDEMPOTENT", "0"], ["IDEMPOTENT", "1"]):
        raise BusinessError("CLAIM_INTEL output has an invalid idempotent state")
    sent = lines[4][1] == "1"
    idempotent = lines[5][1] == "1"
    if sent == idempotent:
        raise BusinessError("CLAIM_INTEL dispatch/idempotent states are inconsistent")
    if lines[6] != ["END", "1"]:
        raise BusinessError("CLAIM_INTEL output has an invalid terminator")
    return ClaimReceipt(
        role=role,
        kingdom=ALLOWED_KINGDOM,
        target_ids=expected_ids,
        request_dispatched=sent,
        idempotent=idempotent,
    )


def _parse_missing_integer(value: str, location: str) -> int | None:
    if value == "missing":
        return None
    return _parse_integer(value, location, allow_zero=True)


def _parse_missing_bool(value: str, location: str) -> bool | None:
    if value == "missing":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise BusinessError(f"{location} must be true, false, or missing")


def parse_scene_status_output(
    output: str,
    allowed_roles: Sequence[str],
) -> SceneStatus:
    lines = _protocol_lines(output, "SCENE")
    if len(lines) != 8:
        raise BusinessError("SCENE output must contain exactly 8 lines")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("SCENE output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    if lines[2] != ["KINGDOM", str(ALLOWED_KINGDOM)]:
        raise BusinessError("SCENE output kingdom is not 4549")
    scene_line = lines[3]
    if (
        len(scene_line) != 4
        or scene_line[0] != "SCENE"
        or scene_line[2] != "CLASS"
        or not scene_line[3]
        or any(ord(char) < 32 or ord(char) == 127 for char in scene_line[3])
    ):
        raise BusinessError("SCENE output has an invalid scene descriptor")
    scene_type = _parse_missing_integer(scene_line[1], "SCENE scene type")
    map_line = lines[4]
    if len(map_line) != 2 or map_line[0] != "MAP":
        raise BusinessError("SCENE output is missing MAP")
    map_type = _parse_missing_integer(map_line[1], "SCENE map type")
    world_line = lines[5]
    if (
        len(world_line) != 4
        or world_line[0] != "WORLD"
        or world_line[1] not in {"0", "1"}
        or world_line[2] != "CITY"
        or world_line[3] not in {"0", "1"}
    ):
        raise BusinessError("SCENE output has an invalid world/city state")
    busy_line = lines[6]
    if (
        len(busy_line) != 5
        or busy_line[0] != "BUSY"
        or busy_line[1] != "LOADING"
        or busy_line[3] != "TRANSITION"
    ):
        raise BusinessError("SCENE output has an invalid busy state")
    if lines[7] != ["END", "1"]:
        raise BusinessError("SCENE output has an invalid terminator")
    return SceneStatus(
        role=role,
        kingdom=ALLOWED_KINGDOM,
        scene_type=scene_type,
        map_type=map_type,
        class_name=scene_line[3],
        is_world=world_line[1] == "1",
        is_city=world_line[3] == "1",
        loading=_parse_missing_bool(busy_line[2], "SCENE loading"),
        transition=_parse_missing_bool(busy_line[4], "SCENE transition"),
    )


def _parse_target_stage(
    output: str,
    kind: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> list[list[str]]:
    lines = _protocol_lines(output, kind)
    if len(lines) < 6:
        raise BusinessError(f"{kind} output is incomplete")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError(f"{kind} output is missing ROLE")
    _parse_role(lines[1][1], allowed_roles)
    if lines[2] != ["KINGDOM", str(ALLOWED_KINGDOM)]:
        raise BusinessError(f"{kind} output kingdom is not 4549")
    if lines[3] != ["TARGET", str(target.runtime_id)]:
        raise BusinessError(f"{kind} output target does not match the request")
    if lines[-1] != ["END", "1"]:
        raise BusinessError(f"{kind} output has an invalid terminator")
    return lines


def parse_open_output(
    output: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> None:
    lines = _parse_target_stage(output, "OPEN", allowed_roles, target)
    if len(lines) != 6 or lines[4] != ["OPENED", "1"]:
        raise BusinessError("OPEN output did not confirm the expedition view request")


def parse_ready_output(
    output: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> bool:
    lines = _parse_target_stage(output, "READY", allowed_roles, target)
    if len(lines) != 6 or lines[4] not in (["READY", "0"], ["READY", "1"]):
        raise BusinessError("READY output has an invalid readiness state")
    return lines[4][1] == "1"


def parse_commit_output(
    output: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> None:
    lines = _parse_target_stage(output, "COMMIT", allowed_roles, target)
    if (
        len(lines) != 7
        or lines[4] != ["AVERAGE", "1"]
        or lines[5] != ["GO", "1"]
    ):
        raise BusinessError("COMMIT output did not confirm average and go actions")


def parse_verify_output(
    output: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> tuple[bool, str]:
    lines = _parse_target_stage(output, "VERIFY", allowed_roles, target)
    if (
        len(lines) != 8
        or len(lines[4]) != 4
        or lines[4][0] != "ACCEPTED"
        or lines[4][1] not in {"0", "1"}
        or lines[4][2] != "STATUS"
    ):
        raise BusinessError("VERIFY output has an invalid acceptance state")
    status = lines[4][3]
    if status != "missing":
        _parse_integer(status, "VERIFY status", allow_zero=True)
        if status not in {"1", "2", "3"}:
            raise BusinessError("VERIFY entered an unexpected quest status")
    march = lines[5]
    if (
        len(march) != 4
        or march[0] != "MARCH"
        or march[1] not in {"0", "1"}
        or march[2] != "EVENT"
    ):
        raise BusinessError("VERIFY output is missing the self-march proof")
    march_found = march[1] == "1"
    event_missing = march[3] == "missing"
    event_id: int | None = None
    if event_missing:
        if not march_found:
            raise BusinessError("VERIFY pending march proof cannot omit its event id")
    else:
        event_id = _parse_integer(
            march[3], "VERIFY march event id", allow_zero=not march_found
        )
        if march_found and event_id != target.runtime_id:
            raise BusinessError("VERIFY march event does not match the target")
        if not march_found and event_id != 0:
            raise BusinessError("VERIFY pending march proof must use event id 0")
    accepted = lines[4][1] == "1"
    if len(lines[6]) != 2 or lines[6][0] != "PROOF":
        raise BusinessError("VERIFY output is missing its proof type")
    proof = lines[6][1]
    if proof not in {"MARCH_EVENT", "MARCH_FIELDS", "QUEST_STATUS", "NONE"}:
        raise BusinessError("VERIFY output has an invalid proof type")
    if march_found:
        expected_proof = "MARCH_FIELDS" if event_missing else "MARCH_EVENT"
        if proof != expected_proof:
            raise BusinessError("VERIFY march proof type is inconsistent")
    if not march_found and accepted:
        if proof == "NONE":
            raise BusinessError("VERIFY acceptance does not match the self-march proof")
        if proof != "QUEST_STATUS" or status not in {"2", "3"}:
            raise BusinessError("VERIFY accepted without a valid quest-status proof")
    if not accepted and proof != "NONE":
        raise BusinessError("VERIFY pending output has an unexpected proof type")
    if not accepted and status not in {"1", "2", "3", "missing"}:
        raise BusinessError("VERIFY pending state has an unexpected quest status")
    return accepted, status


def parse_march_output(
    output: str,
    allowed_roles: Sequence[str],
    expected_quality: str,
) -> MarchReceipt:
    quality = normalize_quality(expected_quality)
    lines = _protocol_lines(output, "MARCH")
    if len(lines) != 8:
        raise BusinessError("MARCH output must contain exactly 8 lines")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("MARCH output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    if lines[2] != ["KINGDOM", str(ALLOWED_KINGDOM)]:
        raise BusinessError("MARCH output kingdom is not 4549")
    if lines[3] != ["QUALITY", quality, str(QUALITY_IDS[quality])]:
        raise BusinessError("MARCH output quality does not match the request")
    target_fields = list(lines[4])
    if not target_fields or target_fields[0] != "TARGET":
        raise BusinessError("MARCH output is missing TARGET")
    target_fields[0] = "ITEM"
    target = _parse_item(target_fields, "TARGET")
    if target.quality != quality:
        raise BusinessError("MARCH target quality does not match the request")
    if lines[5] != ["AVERAGE", "1"]:
        raise BusinessError("MARCH output did not confirm average formation")
    if lines[6] != ["SENT", "1"]:
        raise BusinessError("MARCH output did not confirm request dispatch")
    if lines[7] != ["END", "1"]:
        raise BusinessError("MARCH output has an invalid terminator")
    return MarchReceipt(
        role=role,
        kingdom=ALLOWED_KINGDOM,
        quality=quality,
        quality_id=QUALITY_IDS[quality],
        target=target,
        request_dispatched=True,
    )


__all__ = [
    "ALLOWED_KINGDOM",
    "BusinessError",
    "ClaimReceipt",
    "INTEL_COMPLETED",
    "INTEL_MISSING",
    "INTEL_PENDING",
    "INTEL_STATES",
    "IntelItem",
    "IntelSnapshot",
    "IntelStatusSnapshot",
    "IntelTargetStatus",
    "MarchReceipt",
    "QUALITY_ALIASES",
    "QUALITY_BY_ID",
    "QUALITY_IDS",
    "SceneStatus",
    "build_claim_intel_lua",
    "build_close_expedition_lua",
    "build_commit_march_lua",
    "build_direct_commit_march_lua",
    "build_install_march_capture_hook_lua",
    "build_inspect_intel_lua",
    "build_intel_status_lua",
    "build_march_ready_lua",
    "build_open_march_lua",
    "build_read_march_capture_hook_lua",
    "build_scene_status_lua",
    "build_uninstall_march_capture_hook_lua",
    "build_verify_march_lua",
    "normalize_quality",
    "normalize_target_ids",
    "parse_claim_intel_output",
    "parse_commit_output",
    "parse_intel_output",
    "parse_intel_status_output",
    "parse_march_output",
    "parse_open_output",
    "parse_ready_output",
    "parse_scene_status_output",
    "parse_verify_output",
    "select_march_target",
    "script_sha256",
    "validate_role_whitelist",
]
