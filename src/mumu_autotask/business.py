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
BATTLE_CATEGORY_TYPES = {
    "rescue": 2,
    "hero": 3,
}
BATTLE_CATEGORY_BY_TYPE = {
    value: key for key, value in BATTLE_CATEGORY_TYPES.items()
}
BATTLE_CATEGORY_ALIASES = {
    "营救幸存者": "rescue",
    "营救": "rescue",
    "rescue_survivors": "rescue",
    "survivors": "rescue",
    "英雄之旅": "hero",
    "英雄": "hero",
    "hero_journey": "hero",
    "rpg_stage": "hero",
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
    recommended_power: int = 0


@dataclass(frozen=True, slots=True)
class IntelSnapshot:
    role: str
    kingdom: int
    items: tuple[IntelItem, ...]
    current_stamina: int | None = None


@dataclass(frozen=True, slots=True)
class BattleIntelItem:
    runtime_id: int
    quest_id: int
    status: int
    world_x: int
    world_y: int
    expires_at: int
    category: str
    quest_type: int
    quality: str
    quality_id: int
    condition: int
    level: int
    stamina_cost: int
    power_level: int


@dataclass(frozen=True, slots=True)
class BattleIntelSnapshot:
    role: str
    kingdom: int
    items: tuple[BattleIntelItem, ...]


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
class MarchPrepareReceipt:
    ready_to_commit: bool
    current_stamina: int
    required_stamina: int
    base_stamina: int
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MarchCommitReceipt:
    request_dispatched: bool
    current_stamina: int
    required_stamina: int
    base_stamina: int
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class WorldMonsterSearchReceipt:
    role: str
    kingdom: int
    level: int
    ready: bool
    world_x: int | None
    world_y: int | None
    monster_id: int | None
    recommended_power: int | None
    current_stamina: int


@dataclass(frozen=True, slots=True)
class WorldMonsterHuntReceipt:
    role: str
    kingdom: int
    level: int
    monster_id: int
    world_x: int
    world_y: int
    request_dispatched: bool
    current_stamina: int
    required_stamina: int
    base_stamina: int
    current_marches: int
    max_marches: int
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class WorldMonsterMarchReceipt:
    role: str
    kingdom: int
    level: int
    monster_id: int
    world_x: int
    world_y: int
    march_id: int | None
    current_stamina: int


@dataclass(frozen=True, slots=True)
class WorldMonsterMarchStatus:
    march_id: int
    state: str


@dataclass(frozen=True, slots=True)
class WorldMarchCapacity:
    role: str
    kingdom: int
    current_marches: int
    max_marches: int
    current_stamina: int


@dataclass(frozen=True, slots=True)
class WorldMonsterStatusSnapshot:
    role: str
    kingdom: int
    current_stamina: int
    current_marches: int
    max_marches: int
    statuses: tuple[WorldMonsterMarchStatus, ...]


@dataclass(frozen=True, slots=True)
class YetiRallyStatus:
    role: str
    kingdom: int
    current_stamina: int
    current_marches: int
    max_marches: int
    active_rallies: int
    prepared: bool
    world_x: int | None = None
    world_y: int | None = None
    monster_id: int | None = None


@dataclass(frozen=True, slots=True)
class YetiSearchReceipt:
    role: str
    kingdom: int
    ready: bool
    world_x: int | None
    world_y: int | None
    monster_id: int | None


@dataclass(frozen=True, slots=True)
class YetiCommitReceipt:
    role: str
    kingdom: int
    request_dispatched: bool
    current_stamina: int
    required_stamina: int
    current_marches: int
    max_marches: int
    active_rallies: int
    monster_id: int | None
    world_x: int | None
    world_y: int | None
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class YetiSpawnReceipt:
    role: str
    kingdom: int
    request_dispatched: bool
    blocked_reason: str | None = None


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


def normalize_battle_category(value: str) -> str:
    if not isinstance(value, str):
        raise BusinessError("intelligence category must be text")
    category = value.strip().lower()
    category = BATTLE_CATEGORY_ALIASES.get(category, category)
    if category not in BATTLE_CATEGORY_TYPES:
        allowed = ", ".join((*BATTLE_CATEGORY_TYPES, *BATTLE_CATEGORY_ALIASES))
        raise BusinessError(f"intelligence category must be one of: {allowed}")
    return category


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


def normalize_world_monster_level(level: int) -> int:
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 20:
        raise BusinessError("world monster level must be between 1 and 20")
    return level


def normalize_world_monster_count(count: int) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4:
        raise BusinessError("world monster hunt count must be between 1 and 4")
    return count


def normalize_world_monster_march_ids(march_ids: Sequence[int]) -> tuple[int, ...]:
    if isinstance(march_ids, (str, bytes)):
        raise BusinessError("world monster march ids must be an array")
    result: list[int] = []
    seen: set[int] = set()
    for index, march_id in enumerate(march_ids):
        if isinstance(march_id, bool) or not isinstance(march_id, int) or march_id <= 0:
            raise BusinessError(
                f"world monster march ids[{index}] must be a positive integer"
            )
        if march_id in seen:
            raise BusinessError(f"world monster march id {march_id} is duplicated")
        seen.add(march_id)
        result.append(march_id)
    if not result:
        raise BusinessError("at least one world monster march id is required")
    if len(result) > 16:
        raise BusinessError("cannot track more than 16 world monster marches")
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
    if next(ALLOWED_ROLES) ~= nil and ALLOWED_ROLES[role_hex] ~= true then
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
    if kid ~= server_id then
        fail("active player kingdom/server disagree")
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
            if type(GConfig) ~= "table" or type(GConfig.world_map_monster) ~= "table" then
                fail("world monster config is unavailable")
            end
            local monster_config = GConfig.world_map_monster[monster_id]
            if type(monster_config) ~= "table" then
                fail("selected monster config is unavailable")
            end
            local recommended_power = integer(
                monster_config.recommendPower,
                "recommended power",
                false
            )
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
                recommended_power = recommended_power,
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
            local quest_type = quest_integer(quest, "GetQuestType", "quest type", false)
            if quest_type ~= 1 and quest_type ~= 2 and quest_type ~= 3 then
                fail("requested intelligence id is not a claimable intelligence quest")
            end
            local status = integer(quest._status, "quest status", true)
            local completed = call(quest, "IsCompleted", "quest completion")
            if type(completed) ~= "boolean" then
                fail("quest completion is not boolean")
            end
            raw_status = tostring(status)
            if status == 2 or completed == true then
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
if type(GCtrl) ~= "table"
    or type(GCtrl.RecoverCtrl) ~= "table"
    or type(GCtrl.RecoverCtrl.GetLeftCount) ~= "function"
    or type(ResDefine) ~= "table"
    or ResDefine.COMMANDER_STAMINA == nil then
    fail("commander stamina API is unavailable")
end
local stamina_ok, current_stamina = pcall(
    GCtrl.RecoverCtrl.GetLeftCount,
    GCtrl.RecoverCtrl,
    ResDefine.COMMANDER_STAMINA
)
if not stamina_ok then
    fail("commander stamina lookup failed")
end
current_stamina = integer(current_stamina, "current commander stamina", true)
local lines = {
    "MUMU_AUTOTASK\t1\tINTEL",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "STAMINA\t" .. tostring(current_stamina),
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
        tostring(item.recommended_power),
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


_LUA_BATTLE_COMMON = r'''
local ALLOWED_ROLES = { __ROLE_TABLE__ }
local QUALITY_NAMES = { [2] = "green", [3] = "blue", [4] = "purple", [5] = "yellow" }
local CATEGORY_NAMES = { [2] = "rescue", [3] = "hero" }

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
    if next(ALLOWED_ROLES) ~= nil and ALLOWED_ROLES[role_hex] ~= true then
        fail("active role is not in this device whitelist")
    end
    local kid = integer(call(GCtrl.PlayerCtrl, "GetPlayerKid", "player kingdom"), "player kingdom", false)
    local server_id = integer(call(GCtrl.PlayerCtrl, "GetPlayerServerId", "player server"), "player server", false)
    if kid ~= server_id then
        fail("active player kingdom/server disagree")
    end
    return role_hex, server_id
end

local function quest_integer(quest, method_name, label, allow_zero)
    return integer(call(quest, method_name, label), label, allow_zero)
end

local function config_integer(config, name, label, allow_zero)
    local value = config[name]
    if value == nil then
        return 0
    end
    return integer(value, label, allow_zero)
end

local function collect_battle_intel(quest_type_filter)
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
        if quest_type == quest_type_filter and CATEGORY_NAMES[quest_type] ~= nil then
            local quality_id = quest_integer(quest, "GetQuality", "quality", false)
            local quality = QUALITY_NAMES[quality_id]
            local shown = call(quest, "IsShowInWorld", "world visibility")
            local status = integer(quest._status, "quest status", true)
            local expires_at = integer(quest._expireTime, "expire time", true)
            local valid_time = quest_integer(quest, "GetValidTime", "valid time", true)
            if quality ~= nil and shown == true and status == 1 and valid_time > 30 then
                local config = call(quest, "GetQuestConfig", "quest config")
                if type(config) ~= "table" then
                    fail("quest config is unavailable")
                end
                local runtime_value = integer(runtime_id, "runtime id", false)
                if quest_integer(quest, "GetId", "quest runtime id", false) ~= runtime_value then
                    fail("quest map key and runtime id disagree")
                end
                items[#items + 1] = {
                    runtime_id = runtime_value,
                    quest_id = integer(quest._questId, "quest id", false),
                    status = status,
                    world_x = integer(quest._worldX, "world x", true),
                    world_y = integer(quest._worldY, "world y", true),
                    expires_at = expires_at,
                    category = CATEGORY_NAMES[quest_type],
                    quest_type = quest_type,
                    quality = quality,
                    quality_id = quality_id,
                    condition = config_integer(config, "condition", "condition", true),
                    level = quest_integer(quest, "GetLevel", "quest level", true),
                    stamina_cost = config_integer(config, "stamtina_expend", "stamina cost", true),
                    power_level = config_integer(config, "power_level", "power level", true),
                    object = quest,
                }
            end
        end
    end
    if #items > 128 then
        fail("battle intelligence count exceeds 128")
    end
    table.sort(items, function(left, right)
        if left.quest_type ~= right.quest_type then
            return left.quest_type < right.quest_type
        end
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

local function hero_config_id(hero)
    if type(hero) ~= "table" then
        return nil
    end
    for _, key in ipairs({ "id", "_id", "hero_id" }) do
        if type(hero[key]) == "number" then
            return hero[key]
        end
    end
    local config = hero.hero_config
    if type(config) == "table" then
        for _, key in ipairs({ "id", "hero_id" }) do
            if type(config[key]) == "number" then
                return config[key]
            end
        end
    end
    for _, method in ipairs({ "GetId", "GetHeroId", "GetConfigId" }) do
        if type(hero[method]) == "function" then
            local ok, value = pcall(hero[method], hero)
            if ok and type(value) == "number" then
                return value
            end
        end
    end
    return nil
end

local function hero_power(hero)
    if type(hero) ~= "table" then
        return 0
    end
    for _, key in ipairs({ "powerFight", "fight", "power", "_power" }) do
        if type(hero[key]) == "number" then
            return hero[key]
        end
    end
    return 0
end

local function recommended_pve_heroes()
    if type(GCtrl) ~= "table" or type(GCtrl.HeroCtrl) ~= "table" then
        fail("HeroCtrl is unavailable")
    end
    local list = call(GCtrl.HeroCtrl, "GetRecruitedHeroList", "recruited hero list")
    if type(list) ~= "table" then
        fail("recruited hero list is unavailable")
    end
    local heroes = {}
    local seen = {}
    for _, hero in ipairs(list) do
        local id = hero_config_id(hero)
        if type(id) == "number" and id > 0 and seen[id] ~= true then
            seen[id] = true
            heroes[#heroes + 1] = {
                id = integer(id, "hero id", false),
                power = hero_power(hero),
            }
        end
    end
    table.sort(heroes, function(left, right)
        if left.power ~= right.power then
            return left.power > right.power
        end
        return left.id < right.id
    end)
    if #heroes == 0 then
        fail("no recruited hero is available")
    end
    local selected = {}
    local limit = math.min(5, #heroes)
    for index = 1, limit do
        selected[#selected + 1] = heroes[index].id
    end
    return selected
end

local function require_battle_target(
    runtime_id,
    quest_id,
    quest_type,
    quality_id,
    world_x,
    world_y,
    expires_at,
    condition,
    level,
    stamina_cost,
    power_level
)
    local quest_map = call(GCtrl.RadarCtrl, "GetQuestDataMap", "quest map")
    local quest = quest_map[runtime_id]
    if type(quest) ~= "table" then
        fail("selected intelligence no longer exists")
    end
    if quest_integer(quest, "GetId", "quest runtime id", false) ~= runtime_id
        or integer(quest._questId, "quest id", false) ~= quest_id
        or quest_integer(quest, "GetQuestType", "quest type", false) ~= quest_type
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
    if quest_integer(quest, "GetLevel", "quest level", true) ~= level then
        fail("selected intelligence level changed")
    end
    local config = call(quest, "GetQuestConfig", "quest config")
    if type(config) ~= "table" then
        fail("quest config is unavailable")
    end
    if config_integer(config, "condition", "condition", true) ~= condition
        or config_integer(config, "stamtina_expend", "stamina cost", true) ~= stamina_cost
        or config_integer(config, "power_level", "power level", true) ~= power_level then
        fail("selected intelligence config changed")
    end
    return quest
end
'''


def _battle_category_constant(category: str) -> str:
    normalized = normalize_battle_category(category)
    return f"local TARGET_QUEST_TYPE = {BATTLE_CATEGORY_TYPES[normalized]}\n"


_INSPECT_BATTLE_INTEL_BODY = r'''
local role_hex, kingdom = checked_identity()
local items = collect_battle_intel(TARGET_QUEST_TYPE)
local lines = {
    "MUMU_AUTOTASK\t1\tBATTLE_INTEL",
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
        item.category,
        tostring(item.quest_type),
        item.quality,
        tostring(item.quality_id),
        tostring(item.condition),
        tostring(item.level),
        tostring(item.stamina_cost),
        tostring(item.power_level),
    }, "\t")
end
lines[#lines + 1] = "END\t" .. tostring(#items)
local output = table.concat(lines, "\n")
if #output > 15000 then
    fail("battle intelligence output exceeds 15000 bytes")
end
return output
'''


def build_inspect_battle_intel_lua(
    roles: Sequence[str],
    category: str,
) -> str:
    common = _LUA_BATTLE_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(
        textwrap.dedent(
            common + _battle_category_constant(category) + _INSPECT_BATTLE_INTEL_BODY
        )
    )


def _battle_target_constants(target: BattleIntelItem) -> str:
    if not isinstance(target, BattleIntelItem):
        raise BusinessError("battle intelligence target must be a BattleIntelItem")
    category = normalize_battle_category(target.category)
    if category != target.category:
        raise BusinessError("battle intelligence target category must be canonical")
    if BATTLE_CATEGORY_TYPES[category] != target.quest_type:
        raise BusinessError("battle intelligence category/type disagree")
    quality = normalize_quality(target.quality)
    if quality != target.quality or QUALITY_IDS[quality] != target.quality_id:
        raise BusinessError("battle intelligence quality name/id disagree")
    numeric = {
        "runtime id": target.runtime_id,
        "quest id": target.quest_id,
        "status": target.status,
        "world x": target.world_x,
        "world y": target.world_y,
        "expiry": target.expires_at,
        "quest type": target.quest_type,
        "quality id": target.quality_id,
        "condition": target.condition,
        "level": target.level,
        "stamina cost": target.stamina_cost,
        "power level": target.power_level,
    }
    for label, value in numeric.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BusinessError(f"battle intelligence target {label} must be non-negative")
    if target.runtime_id == 0 or target.quest_id == 0 or target.expires_at == 0:
        raise BusinessError("battle intelligence target identifiers and expiry must be positive")
    if target.status != 1:
        raise BusinessError("battle intelligence target is not available")
    return textwrap.dedent(
        f'''\
        local TARGET_RUNTIME_ID = {target.runtime_id}
        local TARGET_QUEST_ID = {target.quest_id}
        local TARGET_QUEST_TYPE = {target.quest_type}
        local TARGET_QUALITY_ID = {target.quality_id}
        local TARGET_WORLD_X = {target.world_x}
        local TARGET_WORLD_Y = {target.world_y}
        local TARGET_EXPIRES_AT = {target.expires_at}
        local TARGET_CONDITION = {target.condition}
        local TARGET_LEVEL = {target.level}
        local TARGET_STAMINA_COST = {target.stamina_cost}
        local TARGET_POWER_LEVEL = {target.power_level}
        '''
    )


def _battle_target_lua(
    roles: Sequence[str],
    target: BattleIntelItem,
    body: str,
) -> str:
    common = _LUA_BATTLE_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _battle_target_constants(target) + body))


_START_BATTLE_INTEL_BODY = r'''
local role_hex, kingdom = checked_identity()
local quest = require_battle_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUEST_TYPE,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_CONDITION,
    TARGET_LEVEL,
    TARGET_STAMINA_COST,
    TARGET_POWER_LEVEL
)
local heroes = recommended_pve_heroes()
if type(GCtrl.RadarCtrl._pveBattleStartMap) == "table"
    and GCtrl.RadarCtrl._pveBattleStartMap[TARGET_RUNTIME_ID] then
    fail("selected intelligence battle is already starting")
end
local ok_start = pcall(
    GCtrl.RadarCtrl.RequestStartBattle,
    GCtrl.RadarCtrl,
    1,
    heroes,
    quest,
    {}
)
if not ok_start then
    fail("battle start request failed")
end
local end_request = false
__END_REQUEST_BLOCK__
local lines = {
    "MUMU_AUTOTASK\t1\tBATTLE_COMMIT",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "START\t1",
    "END_REQUEST\t" .. (end_request and "1" or "0"),
}
for index, hero_id in ipairs(heroes) do
    lines[#lines + 1] = table.concat({ "HERO", tostring(index), tostring(hero_id) }, "\t")
end
lines[#lines + 1] = "END\t1"
return table.concat(lines, "\n")
'''


def build_start_battle_intel_lua(
    roles: Sequence[str],
    target: BattleIntelItem,
) -> str:
    category = normalize_battle_category(target.category)
    should_request_end = category == "hero"
    end_block = (
        r'''
        local ok_end = pcall(
            GCtrl.RadarCtrl.RequestEndBattle,
            GCtrl.RadarCtrl,
            TARGET_RUNTIME_ID
        )
        if not ok_end then
            fail("battle end request failed")
        end
        end_request = true
        '''
        if should_request_end
        else ""
    )
    body = _START_BATTLE_INTEL_BODY.replace("__END_REQUEST_BLOCK__", end_block)
    return _battle_target_lua(roles, target, body)


_START_RESCUE_INTEL_BODY = r'''
local role_hex, kingdom = checked_identity()
if TARGET_QUEST_TYPE ~= 2 then
    fail("selected intelligence is not a rescue survivor quest")
end
local quest = require_battle_target(
    TARGET_RUNTIME_ID,
    TARGET_QUEST_ID,
    TARGET_QUEST_TYPE,
    TARGET_QUALITY_ID,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    TARGET_EXPIRES_AT,
    TARGET_CONDITION,
    TARGET_LEVEL,
    TARGET_STAMINA_COST,
    TARGET_POWER_LEVEL
)
if type(quest) ~= "table" then
    fail("selected rescue intelligence is unavailable")
end
if type(NetMsg) ~= "table" or type(NetMsg.SendMsg) ~= "function" then
    fail("NetMsg.SendMsg is unavailable")
end
local payload = {
    type = 301,
    endpoint = {
        x = TARGET_WORLD_X,
        y = TARGET_WORLD_Y,
    },
    extra = {
        event_id = TARGET_RUNTIME_ID,
    },
    MarchMapType = 1,
}
local ok = pcall(NetMsg.SendMsg, "req_world_march", payload, true)
if not ok then
    fail("rescue world march request failed")
end
return table.concat({
    "MUMU_AUTOTASK\t1\tRESCUE_COMMIT",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "WORLD_MARCH\t1",
    "TYPE\t301",
    "MARCH_MAP_TYPE\t1",
    "END\t1",
}, "\n")
'''


def build_start_rescue_intel_lua(
    roles: Sequence[str],
    target: BattleIntelItem,
) -> str:
    if normalize_battle_category(target.category) != "rescue":
        raise BusinessError("rescue intelligence target category must be rescue")
    return _battle_target_lua(roles, target, _START_RESCUE_INTEL_BODY)


_VERIFY_BATTLE_INTEL_BODY = r'''
local role_hex, kingdom = checked_identity()
local quest_map = call(GCtrl.RadarCtrl, "GetQuestDataMap", "quest map")
local quest = quest_map[TARGET_RUNTIME_ID]
local status_text = "missing"
local accepted = false
if quest == nil then
    status_text = "missing"
    accepted = true
else
    if quest_integer(quest, "GetId", "quest runtime id", false) ~= TARGET_RUNTIME_ID
        or integer(quest._questId, "quest id", false) ~= TARGET_QUEST_ID
        or quest_integer(quest, "GetQuestType", "quest type", false) ~= TARGET_QUEST_TYPE
        or quest_integer(quest, "GetQuality", "quality", false) ~= TARGET_QUALITY_ID
        or integer(quest._worldX, "world x", true) ~= TARGET_WORLD_X
        or integer(quest._worldY, "world y", true) ~= TARGET_WORLD_Y then
        fail("selected intelligence identity changed after battle request")
    end
    local status = integer(quest._status, "quest status", true)
    local completed = call(quest, "IsCompleted", "quest completion")
    status_text = tostring(status)
    if status == 2 or completed == true then
        accepted = true
    elseif status ~= 1 and status ~= 3 then
        fail("selected intelligence entered an unexpected status")
    end
end
return table.concat({
    "MUMU_AUTOTASK\t1\tBATTLE_VERIFY",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "ACCEPTED\t" .. (accepted and "1" or "0") .. "\tSTATUS\t" .. status_text,
    "END\t1",
}, "\n")
'''


def build_verify_battle_intel_lua(
    roles: Sequence[str],
    target: BattleIntelItem,
) -> str:
    return _battle_target_lua(roles, target, _VERIFY_BATTLE_INTEL_BODY)


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
local current_stamina = integer(
    call(
        GCtrl.RecoverCtrl,
        "GetLeftCount",
        "current commander stamina",
        ResDefine.COMMANDER_STAMINA
    ),
    "current commander stamina",
    true
)
local required_stamina = integer(
    call(
        view,
        "GetCostStaminaEduce",
        "actual march stamina cost",
        TARGET_STAMINA_COST,
        view.showHeroList
    ),
    "actual march stamina cost",
    true
)
if current_stamina < required_stamina then
    return table.concat({
        "MUMU_AUTOTASK\t1\tCOMMIT",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
        "AVERAGE\t1",
        "STAMINA\t" .. tostring(current_stamina)
            .. "\t" .. tostring(required_stamina)
            .. "\t" .. tostring(TARGET_STAMINA_COST),
        "GO\t0",
        "REASON\tINSUFFICIENT_STAMINA",
        "END\t1",
    }, "\n")
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
    "STAMINA\t" .. tostring(current_stamina)
        .. "\t" .. tostring(required_stamina)
        .. "\t" .. tostring(TARGET_STAMINA_COST),
    "GO\t1",
    "REASON\tNONE",
    "END\t1",
}, "\n")
'''


_INSPECT_FORMATION_BODY = r'''
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
    fail("selected intelligence was not available before formation inspection")
end
local world_ok, quest_x, quest_y = pcall(quest.GetWorldPos, quest)
if not world_ok or quest_x ~= TARGET_WORLD_X or quest_y ~= TARGET_WORLD_Y then
    fail("selected intelligence world position changed")
end
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.transaction_slg
local map_object_type = WorldMapDefine.mapobj_type.map_monster
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
    fail("formation inspection selected no captain")
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
    fail("formation inspection soldier list is unavailable")
end
local averaged_soldiers = GHelper.FormationHelper.GetAverageSoldierList(
    march_map_type,
    soldier_list,
    formation_limit,
    false,
    extra
)
if type(averaged_soldiers) ~= "table" then
    fail("formation inspection average soldier list is unavailable")
end
local selected = 0
for _, soldier_info in ipairs(averaged_soldiers) do
    if type(soldier_info) == "table"
        and type(soldier_info.selectNum) == "number" then
        selected = selected + soldier_info.selectNum
    end
end
if selected <= 0 then
    fail("formation inspection selected no soldiers")
end
local hero_id, soldier = GHelper.FormationHelper.DealWithExpeditionInfo(
    hero_list,
    averaged_soldiers
)
if type(hero_id) ~= "table" or type(soldier) ~= "table" then
    fail("formation inspection payload is unavailable")
end
local lines = {
    "MUMU_AUTOTASK\t1\tFORMATION",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "STATUS\t" .. tostring(initial_status),
    "POINT_END\t" .. tostring(TARGET_WORLD_X) .. "\t" .. tostring(TARGET_WORLD_Y),
    "MONSTER\t" .. tostring(config.condition),
    "STAMINA\t" .. tostring(TARGET_STAMINA_COST),
    "MARCH_MAP_TYPE\t" .. tostring(march_map_type),
    "MARCH_TYPE\t" .. tostring(march_type),
    "MAP_OBJECT_TYPE\t" .. tostring(map_object_type),
    "FORMATION_MARCH_TYPE\t" .. tostring(formation_march_type),
    "FORMATION_LIMIT\t" .. tostring(formation_limit),
    "SELECTED\t" .. tostring(selected),
}
for key, value in pairs(hero_id) do
    if type(key) == "number" then
        lines[#lines + 1] = table.concat({
            "HERO",
            tostring(key),
            tostring(value),
        }, "\t")
    end
end
for key, value in pairs(soldier) do
    if type(key) == "number" then
        lines[#lines + 1] = table.concat({
            "SOLDIER",
            tostring(key),
            tostring(value),
        }, "\t")
    end
end
lines[#lines + 1] = "END\t1"
return table.concat(lines, "\n")
'''


_DIRECT_MARCH_COMMON = r'''
local ALLOWED_ROLES = { __ROLE_TABLE__ }

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
    if next(ALLOWED_ROLES) ~= nil and ALLOWED_ROLES[role_hex] ~= true then
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
    if kid ~= server_id then
        fail("active player kingdom/server disagree")
    end
    return role_hex, server_id
end

local function quest_integer(quest, method_name, label, allow_zero)
    return integer(call(quest, method_name, label), label, allow_zero)
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
    if type(GCtrl) ~= "table" or type(GCtrl.RadarCtrl) ~= "table" then
        fail("RadarCtrl is unavailable")
    end
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

local function capture_self_march_ids(server_id)
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
    local ids = {}
    for key, march in pairs(march_map) do
        local value = nil
        if type(march) == "table" or type(march) == "userdata" then
            local method = march.GetId
            if type(method) == "function" then
                local id_ok, id = pcall(method, march)
                if id_ok then
                    value = id
                end
            end
        end
        if type(value) ~= "number" then
            value = key
        end
        if type(value) == "number"
            and value == math.floor(value)
            and value > 0 then
            ids[value] = true
        end
    end
    _G.__MUMU_AUTOTASK_SELF_MARCH_IDS = ids
end
'''


_PREPARE_DIRECT_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
_G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
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
    fail("selected intelligence was not available before march preparation")
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
    fail("average formation selected no captain")
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
    fail("soldier list is unavailable")
end
local averaged_soldiers = GHelper.FormationHelper.GetAverageSoldierList(
    march_map_type,
    soldier_list,
    formation_limit,
    false,
    extra
)
if type(averaged_soldiers) ~= "table" then
    fail("average soldier list is unavailable")
end
local selected = 0
for _, soldier in ipairs(averaged_soldiers) do
    if type(soldier) == "table" and type(soldier.selectNum) == "number" then
        selected = selected + soldier.selectNum
    end
end
if selected <= 0 then
    fail("average formation selected no soldiers")
end
local hero_id, soldier = GHelper.FormationHelper.DealWithExpeditionInfo(
    hero_list,
    averaged_soldiers
)
if type(hero_id) ~= "table" or type(soldier) ~= "table" then
    fail("formation payload is unavailable")
end
local current_stamina = integer(
    GCtrl.RecoverCtrl:GetLeftCount(ResDefine.COMMANDER_STAMINA),
    "current stamina",
    true
)
local stamina_reduction = GHelper.AttributeHelper.GetCostStaminaEduce(hero_list)
if type(stamina_reduction) ~= "number"
    or stamina_reduction < 0
    or stamina_reduction > 1 then
    fail("stamina reduction is invalid")
end
local required_stamina = integer(
    math.ceil(TARGET_STAMINA_COST * (1 - stamina_reduction)),
    "required stamina",
    true
)
local ready = current_stamina >= required_stamina
local reason = ready and "NONE" or "INSUFFICIENT_STAMINA"
if ready then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = {
        runtime_id = TARGET_RUNTIME_ID,
        quest_id = TARGET_QUEST_ID,
        quality_id = TARGET_QUALITY_ID,
        world_x = TARGET_WORLD_X,
        world_y = TARGET_WORLD_Y,
        expires_at = TARGET_EXPIRES_AT,
        monster_id = TARGET_MONSTER_ID,
        level = TARGET_LEVEL,
        base_stamina = TARGET_STAMINA_COST,
        required_stamina = required_stamina,
        hero_id = hero_id,
        soldier = soldier,
        extra = extra,
        march_map_type = march_map_type,
        march_type = march_type,
        map_object_type = map_object_type,
        initial_status = initial_status,
    }
end
return table.concat({
    "MUMU_AUTOTASK\t1\tPREPARE",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
    "AVERAGE\t1",
    "STAMINA\t" .. tostring(current_stamina)
        .. "\t" .. tostring(required_stamina)
        .. "\t" .. tostring(TARGET_STAMINA_COST),
    "READY\t" .. (ready and "1" or "0"),
    "REASON\t" .. reason,
    "END\t1",
}, "\n")
'''


_COMMIT_PREPARED_MARCH_BODY = r'''
local role_hex, kingdom = checked_identity()
local cache = _G.__MUMU_AUTOTASK_DIRECT_MARCH
if type(cache) ~= "table" then
    fail("prepared march payload is unavailable")
end
if cache.runtime_id ~= TARGET_RUNTIME_ID
    or cache.quest_id ~= TARGET_QUEST_ID
    or cache.quality_id ~= TARGET_QUALITY_ID
    or cache.world_x ~= TARGET_WORLD_X
    or cache.world_y ~= TARGET_WORLD_Y
    or cache.expires_at ~= TARGET_EXPIRES_AT
    or cache.monster_id ~= TARGET_MONSTER_ID
    or cache.level ~= TARGET_LEVEL
    or cache.base_stamina ~= TARGET_STAMINA_COST then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
    fail("prepared march payload does not match the selected intelligence")
end
if type(cache.hero_id) ~= "table"
    or type(cache.soldier) ~= "table"
    or type(cache.extra) ~= "table" then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
    fail("prepared formation payload is invalid")
end
local quest = require_target(
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
if initial_status ~= cache.initial_status or initial_status ~= 1 then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
    fail("selected intelligence status changed after march preparation")
end
local required_stamina = integer(
    cache.required_stamina,
    "required stamina",
    true
)
local current_stamina = integer(
    GCtrl.RecoverCtrl:GetLeftCount(ResDefine.COMMANDER_STAMINA),
    "current stamina",
    true
)
local function commit_result(go, reason)
    return table.concat({
        "MUMU_AUTOTASK\t1\tCOMMIT",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "TARGET\t" .. tostring(TARGET_RUNTIME_ID),
        "AVERAGE\t1",
        "STAMINA\t" .. tostring(current_stamina)
            .. "\t" .. tostring(required_stamina)
            .. "\t" .. tostring(TARGET_STAMINA_COST),
        "GO\t" .. go,
        "REASON\t" .. reason,
        "END\t1",
    }, "\n")
end
if current_stamina < required_stamina then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
    return commit_result("0", "INSUFFICIENT_STAMINA")
end
if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
    cache.march_map_type,
    cache.march_type,
    nil,
    true
) then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
    fail("no idle march queue is available")
end
local blocked_ok, blocked = pcall(
    GHelper.ExpeditionHelper.IsBeforehandMarch,
    cache.march_map_type,
    cache.march_type,
    cache.map_object_type,
    cache.extra,
    true
)
if blocked_ok and blocked then
    _G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
    fail("selected intelligence is already marching")
end
capture_self_march_ids(kingdom)
_G.__MUMU_AUTOTASK_INITIAL_STATUS = initial_status
_G.__MUMU_AUTOTASK_GO_INVOKED = true
local request_ok = pcall(
    GHelper.WorldMarchHelper.RequestMarchStartOff,
    cache.march_map_type,
    cache.march_type,
    TARGET_WORLD_X,
    TARGET_WORLD_Y,
    {
        hero_id = cache.hero_id,
        soldier = cache.soldier,
    },
    cache.extra
)
_G.__MUMU_AUTOTASK_DIRECT_MARCH = nil
if not request_ok then
    fail("direct march request failed")
end
return commit_result("1", "NONE")
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
wrap(GCtrl and GCtrl.WorldPlayerCtrl, "ReqWorldMapSearch",
    "WorldPlayerCtrl.ReqWorldMapSearch")
wrap(GCtrl and GCtrl.WorldPlayerCtrl, "OnReqWorldSearch",
    "WorldPlayerCtrl.OnReqWorldSearch")
wrap(GHelper and GHelper.WorldHelper, "SearchToMapObj",
    "WorldHelper.SearchToMapObj")
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
    if next(ALLOWED_ROLES) ~= nil and ALLOWED_ROLES[role_hex] ~= true then
        fail("active role is not in this device whitelist")
    end
    local ok_kid, kid = pcall(player.GetPlayerKid, player)
    local ok_server, server_id = pcall(player.GetPlayerServerId, player)
    if not ok_kid or not ok_server or kid ~= server_id then
        fail("active player kingdom/server disagree")
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


def build_inspect_formation_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _INSPECT_FORMATION_BODY)


def _direct_march_target_lua(
    roles: Sequence[str],
    target: IntelItem,
    body: str,
) -> str:
    common = _DIRECT_MARCH_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _target_constants(target) + body))


def build_prepare_direct_march_lua(
    roles: Sequence[str],
    target: IntelItem,
) -> str:
    return _direct_march_target_lua(roles, target, _PREPARE_DIRECT_MARCH_BODY)


def build_commit_prepared_march_lua(
    roles: Sequence[str],
    target: IntelItem,
) -> str:
    return _direct_march_target_lua(roles, target, _COMMIT_PREPARED_MARCH_BODY)


def build_direct_commit_march_lua(roles: Sequence[str], target: IntelItem) -> str:
    """Build the commit half of the split direct-march workflow.

    Callers must execute :func:`build_prepare_direct_march_lua` first on the
    same Lua state. The legacy name remains available for external callers.
    """
    return build_commit_prepared_march_lua(roles, target)


def build_verify_march_lua(roles: Sequence[str], target: IntelItem) -> str:
    return _target_lua(roles, target, _VERIFY_MARCH_BODY)


_WORLD_MONSTER_COMMON = r'''
local function fail(message)
    error("mumu-autotask: " .. message, 0)
end

local function integer(value, label, allow_zero)
    if type(value) ~= "number" or value ~= math.floor(value)
        or value < 0 or (not allow_zero and value == 0) then
        fail(label .. " is not a valid integer")
    end
    return value
end

local function call(object, method_name, label, ...)
    if type(object) ~= "table" or type(object[method_name]) ~= "function" then
        fail(label .. " method is unavailable")
    end
    local ok, first, second = pcall(object[method_name], object, ...)
    if not ok then
        fail(label .. " method failed")
    end
    return first, second
end

local function hex(value)
    if type(value) ~= "string" or value == "" then
        fail("active role is unavailable")
    end
    return (value:gsub(".", function(character)
        return string.format("%02x", string.byte(character))
    end))
end

local function identity()
    local role = call(GCtrl.PlayerCtrl, "GetPlayerName", "player name")
    local kid = integer(call(GCtrl.PlayerCtrl, "GetPlayerKid", "player kingdom"),
        "player kingdom", false)
    return hex(role), kid
end

local function current_stamina()
    return integer(call(GCtrl.RecoverCtrl, "GetLeftCount", "commander stamina",
        ResDefine.COMMANDER_STAMINA), "commander stamina", true)
end

local function self_marches(kingdom)
    local marches = call(GCtrl.WorldMarchCtrl, "GetSelfMarchMap",
        "self march map", kingdom)
    if type(marches) ~= "table" then
        fail("self march map is unavailable")
    end
    return marches
end

local function march_capacity()
    local current = integer(call(GCtrl.WorldMarchCtrl, "GetSelfMarchCount",
        "current self march count"), "current self march count", true)
    if type(GHelper) ~= "table" or type(GHelper.WorldMarchHelper) ~= "table"
        or type(GHelper.WorldMarchHelper.GetCurrentMaxMarchCount) ~= "function" then
        fail("maximum self march count method is unavailable")
    end
    local ok, maximum = pcall(
        GHelper.WorldMarchHelper.GetCurrentMaxMarchCount
    )
    if not ok then fail("maximum self march count method failed") end
    maximum = integer(maximum, "maximum self march count", false)
    if current > maximum then
        fail("current self march count exceeds the maximum")
    end
    return current, maximum
end

local function march_call(march, method_name)
    if (type(march) ~= "table" and type(march) ~= "userdata")
        or type(march[method_name]) ~= "function" then
        return nil
    end
    local ok, first, second = pcall(march[method_name], march)
    if not ok then return nil end
    return first, second
end

local function march_id(march, fallback)
    local value = march_call(march, "GetId")
    if type(value) == "number" and value == math.floor(value) and value > 0 then
        return value
    end
    if type(fallback) == "number" and fallback == math.floor(fallback)
        and fallback > 0 then
        return fallback
    end
    return nil
end
'''


_TOGGLE_WORLD_BODY = r'''
local role_hex, kingdom = checked_identity()
if type(GModule) ~= "table" or type(GModule.UIModule) ~= "table" then
    fail("UIModule is unavailable")
end
if type(GViewId) ~= "table" or GViewId.MAIN_FRAME == nil then
    fail("MAIN_FRAME view id is unavailable")
end
local main = GModule.UIModule:FindOpenedView(GViewId.MAIN_FRAME)
if main == nil then
    fail("MAIN_FRAME is not open")
end
local get_entrance = main.GetHomeEntrance
if type(get_entrance) ~= "function" then
    fail("HomeEntrance method is unavailable")
end
local button_ok, button = pcall(get_entrance, main)
if not button_ok or button == nil then
    fail("HomeEntrance button is unavailable")
end
local on_click = button.onClick
if on_click == nil or type(on_click.Invoke) ~= "function" then
    fail("HomeEntrance onClick event is unavailable")
end
local invoke_ok, invoke_error = pcall(on_click.Invoke, on_click)
if not invoke_ok then
    fail("HomeEntrance onClick invocation failed: " .. tostring(invoke_error))
end
return table.concat({
    "MUMU_AUTOTASK\t1\tTOGGLE_WORLD",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "INVOKED\t1",
    "END\t1",
}, "\n")
'''


_WORLD_MONSTER_SEARCH_BODY = r'''
local LEVEL = __LEVEL__
local role_hex, kingdom = identity()
local previous = _G.__MUMU_AUTOTASK_WORLD_MONSTER_SEARCH
if type(previous) == "table" and type(GameMsg) == "table"
    and type(GameMsg.RemoveMessageByTarget) == "function" then
    pcall(GameMsg.RemoveMessageByTarget, previous)
end
local max_level = integer(call(GCtrl.WorldPlayerCtrl,
    "GetPlayerCanKillMonsterMaxLv", "maximum monster level"),
    "maximum monster level", true)
if LEVEL > max_level then
    fail("requested monster level exceeds the player's attack limit")
end
local view_id = 207
-- ReqWorldMapSearch argument 6 controls map navigation. Keep background
-- searches silent so repeated hunts do not move the player's camera.
local auto_jump = false
-- The UI sends an explicit zero resource id for monster searches.  Passing
-- nil here looks harmless in Lua, but the game's request handler treats it as
-- a different overload and does not dispatch the normal search callback.
local state = { level = LEVEL, view_id = view_id, resource_id = 0 }
state.map_callback = function(first, second, third)
    state.map_called = (state.map_called or 0) + 1
    state.map_arg1 = first
    state.map_arg2 = second
    state.map_arg3 = third
    -- SearchToMapObj completion callbacks differ by client build: a map object
    -- may be supplied as the first, second, or third callback argument. Keep
    -- all table-shaped candidates and let the result stage validate them.
    for _, candidate in ipairs({ first, second, third }) do
        if (type(candidate) == "table" or type(candidate) == "userdata")
            and candidate ~= state then
            local ok, x, y = pcall(function()
                if type(candidate.GetPos) == "function" then
                    return candidate:GetPos()
                end
            end)
            if ok and type(x) == "number" and type(y) == "number" then
                state.mapobj = candidate
                state.mapobj_x = x
                state.mapobj_y = y
            end
        end
    end
end
state.search_callback = function(_, point, response_view_id)
    if response_view_id ~= state.view_id or type(point) ~= "table"
        or type(point.x) ~= "number" or type(point.y) ~= "number" then
        return
    end
    state.world_x = point.x
    state.world_y = point.y
    state.callback_received = true
    -- This is the same second-stage call made by WorldSearchObjView after
    -- OnSearchBack. ReqWorldMapObjByPos is a different map-cache request and
    -- does not populate the monster object used by the expedition flow.
    if type(GHelper) == "table" and type(GHelper.WorldHelper) == "table"
        and type(GHelper.WorldHelper.SearchToMapObj) == "function" then
        local ok, request_error = pcall(
            GHelper.WorldHelper.SearchToMapObj,
            point.x,
            point.y,
            kingdom,
            1,
            1,
            true,
            state.map_callback,
            false
        )
        state.map_object_requested = ok
        if not ok then state.map_object_error = tostring(request_error) end
    elseif type(GCtrl) == "table" and type(GCtrl.WorldMapCtrl) == "table"
        and type(GCtrl.WorldMapCtrl.ReqWorldMapObjByPos) == "function" then
        -- Compatibility fallback for older clients without WorldHelper.
        local ok, request_error = pcall(
            GCtrl.WorldMapCtrl.ReqWorldMapObjByPos,
            GCtrl.WorldMapCtrl,
            kingdom,
            point.x,
            point.y
        )
        state.map_object_requested = ok
        if not ok then state.map_object_error = tostring(request_error) end
    else
        state.map_object_error = "world map object lookup API is unavailable"
    end
end
state.start = function()
    if type(GameMsg) ~= "table" or type(GameMsg.AddMessage) ~= "function"
        or type(GameMsgId) ~= "table"
        or GameMsgId.REQ_WORLD_SEARCH_BACK == nil then
        state.search_error = "world search callback API is unavailable"
        return false
    end
    local add_ok, add_error = pcall(
        GameMsg.AddMessage,
        state,
        GameMsgId.REQ_WORLD_SEARCH_BACK,
        state.search_callback
    )
    if not add_ok then
        state.search_error = tostring(add_error)
        return false
    end
    local request_ok, request_error = pcall(
        GCtrl.WorldPlayerCtrl.ReqWorldMapSearch,
        GCtrl.WorldPlayerCtrl,
        WorldMapDefine.mapobj_type.map_monster,
        LEVEL,
        LEVEL,
        state.resource_id,
        nil,
        auto_jump,
        view_id
    )
    if not request_ok then
        pcall(GameMsg.RemoveMessageByTarget, state)
        state.search_error = tostring(request_error)
        return false
    end
    state.request_started = true
    return true
end
_G.__MUMU_AUTOTASK_WORLD_MONSTER_SEARCH = state
state.start()
return table.concat({
    "MUMU_AUTOTASK\t1\tWORLD_MONSTER_SEARCH_SENT",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "LEVEL\t" .. tostring(LEVEL),
    "SENT\t1",
    "END\t1",
}, "\n")
'''


_WORLD_MONSTER_SEARCH_RESULT_BODY = r'''
local LEVEL = __LEVEL__
local role_hex, kingdom = identity()
local state = _G.__MUMU_AUTOTASK_WORLD_MONSTER_SEARCH
if type(state) ~= "table" or state.level ~= LEVEL then
    fail("matching world monster search state is unavailable")
end
local stamina = current_stamina()
if state.search_error ~= nil then
    fail("world monster search failed: " .. tostring(state.search_error))
end
if state.request_started ~= true then
    state.start()
    if state.search_error ~= nil then
        fail("world monster search failed: " .. tostring(state.search_error))
    end
end
if type(state.world_x) ~= "number" or type(state.world_y) ~= "number" then
    return table.concat({
        "MUMU_AUTOTASK\t1\tWORLD_MONSTER_SEARCH",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "LEVEL\t" .. tostring(LEVEL),
        "READY\t0",
        "POINT\tmissing\tmissing",
        "MONSTER\tmissing\tmissing",
        "STAMINA\t" .. tostring(stamina),
        "END\t1",
    }, "\n")
end
state.world_x = integer(state.world_x, "monster world x", true)
state.world_y = integer(state.world_y, "monster world y", true)
-- The map-object response is delivered separately from the search response.
-- Prefer that exact callback object; on some builds it is not inserted into
-- GetMapDataDic until the map view is rendered.
local map_object = state.mapobj
if map_object ~= nil then
    local ok, x, y = pcall(function()
        if type(map_object.GetPos) == "function" then
            return map_object:GetPos()
        end
    end)
    if not ok or x ~= state.world_x or y ~= state.world_y then
        map_object = nil
    end
end
local map_data = call(GCtrl.WorldMapCtrl, "GetMapDataDic",
    "world map data", kingdom)
if type(map_data) ~= "table" then fail("world map data is unavailable") end
if map_object == nil then
    map_object = map_data[state.world_x * 10000 + state.world_y]
end
if map_object == nil then
    for _, candidate in pairs(map_data) do
        if type(candidate) == "table" or type(candidate) == "userdata" then
            local pos_method = candidate.GetPos
            if type(pos_method) == "function" then
                local ok, x, y = pcall(pos_method, candidate)
                if ok and x == state.world_x and y == state.world_y then
                    if map_object ~= nil then
                        fail("multiple world map objects matched the searched position")
                    end
                    map_object = candidate
                end
            end
        end
    end
end
if map_object == nil then
    return table.concat({
        "MUMU_AUTOTASK\t1\tWORLD_MONSTER_SEARCH",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "LEVEL\t" .. tostring(LEVEL),
        "READY\t0",
        "POINT\t" .. tostring(state.world_x) .. "\t" .. tostring(state.world_y),
        "MONSTER\tmissing\tmissing",
        "STAMINA\t" .. tostring(stamina),
        "END\t1",
    }, "\n")
end
local object_type = integer(call(map_object, "GetType", "map object type"),
    "map object type", false)
local object_level = integer(call(map_object, "GetLevel", "monster level"),
    "monster level", false)
local object_x, object_y = call(map_object, "GetPos", "monster position")
if object_type ~= WorldMapDefine.mapobj_type.map_monster
    or object_level ~= LEVEL or object_x ~= state.world_x
    or object_y ~= state.world_y then
    fail("searched world map object identity does not match the request")
end
local monster_id = integer(call(map_object, "GetId", "monster id"),
    "monster id", false)
local config = GRead.WorldRead.GetMapMonsterConfig(monster_id)
if type(config) ~= "table" then fail("monster configuration is unavailable") end
local recommended_power = integer(config.recommendPower,
    "recommended power", false)
local base_stamina = integer(call(map_object, "GetAttackCostEnergy",
    "monster stamina cost"), "monster stamina cost", false)
state.monster_id = monster_id
state.recommended_power = recommended_power
state.base_stamina = base_stamina
if type(GameMsg.RemoveMessageByTargetAndMsgId) == "function" then
    pcall(GameMsg.RemoveMessageByTargetAndMsgId, state,
        GameMsgId.REQ_WORLD_SEARCH_BACK)
end
return table.concat({
    "MUMU_AUTOTASK\t1\tWORLD_MONSTER_SEARCH",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "LEVEL\t" .. tostring(LEVEL),
    "READY\t1",
    "POINT\t" .. tostring(state.world_x) .. "\t" .. tostring(state.world_y),
    "MONSTER\t" .. tostring(monster_id) .. "\t" .. tostring(recommended_power),
    "STAMINA\t" .. tostring(stamina),
    "END\t1",
}, "\n")
'''


_WORLD_MONSTER_COMMIT_BODY = r'''
local LEVEL = __LEVEL__
local role_hex, kingdom = identity()
local state = _G.__MUMU_AUTOTASK_WORLD_MONSTER_SEARCH
if type(state) ~= "table" or state.level ~= LEVEL
    or type(state.world_x) ~= "number" or type(state.world_y) ~= "number"
    or type(state.monster_id) ~= "number" then
    fail("prepared world monster search result is unavailable")
end
local map_data = call(GCtrl.WorldMapCtrl, "GetMapDataDic",
    "world map data", kingdom)
local map_object = state.mapobj
if map_object == nil then
    map_object = type(map_data) == "table"
        and map_data[state.world_x * 10000 + state.world_y] or nil
end
if map_object == nil and type(map_data) == "table" then
    for _, candidate in pairs(map_data) do
        if type(candidate) == "table" or type(candidate) == "userdata" then
            local pos_method = candidate.GetPos
            if type(pos_method) == "function" then
                local ok, x, y = pcall(pos_method, candidate)
                if ok and x == state.world_x and y == state.world_y then
                    if map_object ~= nil then
                        fail("multiple world map objects matched the searched position")
                    end
                    map_object = candidate
                end
            end
        end
    end
end
if map_object == nil or (
    call(map_object, "GetId", "monster id") ~= state.monster_id
    or call(map_object, "GetLevel", "monster level") ~= LEVEL
) then
    fail("searched world monster is no longer available")
end
local march_map_type = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
local march_type = WorldMapDefine.march_type.atk_monster
local map_object_type = WorldMapDefine.mapobj_type.map_monster
local extra = { monsterid = state.monster_id }
local hero_list = GHelper.ExpeditionHelper.GetRecommendedHeroList(
    false, false, march_type, state.monster_id, march_map_type, extra)
if type(hero_list) ~= "table"
    or GHelper.FormationHelper.IsHaveCaptain(hero_list) ~= true then
    fail("average formation selected no captain")
end
local formation_limit = integer(GHelper.ExpeditionHelper.GetTroopLimit(
    march_map_type, hero_list, GDefine.HeroDefine.HeroAttrType.SLG, extra),
    "formation limit", false)
local yields = GHelper.ExpeditionHelper.GetResourceYields(march_type, nil)
local open_params = {
    marchMapType = march_map_type,
    marchType = march_type,
    formationNumLimt = formation_limit,
    targetId = state.monster_id,
    yields = yields,
    isAttack = true,
}
local soldier_list = GHelper.ExpeditionHelper.GetSoldierInfoByMarchType(
    march_type, 0, false, open_params, nil)
if type(soldier_list) ~= "table" then
    fail("soldier list is unavailable")
end
local averaged = GHelper.FormationHelper.GetAverageSoldierList(
    march_map_type, soldier_list, formation_limit, false, extra)
if type(averaged) ~= "table" then
    fail("average soldier list is unavailable")
end
local selected = 0
for _, item in ipairs(averaged) do
    if type(item) == "table" and type(item.selectNum) == "number" then
        selected = selected + item.selectNum
    end
end
if selected <= 0 then fail("average formation selected no soldiers") end
local hero_id, soldier = GHelper.FormationHelper.DealWithExpeditionInfo(
    hero_list, averaged)
if type(hero_id) ~= "table" or type(soldier) ~= "table" then
    fail("formation payload is unavailable")
end
local base_stamina = integer(state.base_stamina,
    "base stamina", false)
local reduction = GHelper.AttributeHelper.GetCostStaminaEduce(hero_list)
if type(reduction) ~= "number" or reduction < 0 or reduction > 1 then
    fail("stamina reduction is invalid")
end
local required_stamina = integer(math.ceil(base_stamina * (1 - reduction)),
    "required stamina", true)
local stamina = current_stamina()
local current_marches, max_marches = march_capacity()
local function result(sent, reason)
    return table.concat({
        "MUMU_AUTOTASK\t1\tWORLD_MONSTER_COMMIT",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "LEVEL\t" .. tostring(LEVEL),
        "MONSTER\t" .. tostring(state.monster_id),
        "POINT\t" .. tostring(state.world_x) .. "\t" .. tostring(state.world_y),
        "AVERAGE\t1",
        "STAMINA\t" .. tostring(stamina) .. "\t"
            .. tostring(required_stamina) .. "\t" .. tostring(base_stamina),
        "QUEUE\t" .. tostring(current_marches) .. "\t" .. tostring(max_marches),
        "SENT\t" .. sent,
        "REASON\t" .. reason,
        "END\t1",
    }, "\n")
end
if current_marches >= max_marches then
    return result("0", "NO_IDLE_MARCH_QUEUE")
end
if stamina < required_stamina then
    return result("0", "INSUFFICIENT_STAMINA")
end
-- The last flag controls the game's queue-full prompt. Capacity was already
-- checked above, so keep this secondary guard silent if state changes.
if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
    march_map_type, march_type, nil, false) then
    return result("0", "NO_IDLE_MARCH_QUEUE")
end
local before_ids = {}
for key, march in pairs(self_marches(kingdom)) do
    local id = march_id(march, key)
    if id ~= nil then before_ids[id] = true end
end
state.before_ids = before_ids
state.requested = true
local ok = pcall(GHelper.WorldMarchHelper.RequestMarchStartOff,
    march_map_type, march_type, state.world_x, state.world_y,
    { hero_id = hero_id, soldier = soldier }, extra)
if not ok then
    state.requested = false
    fail("world monster march request failed")
end
return result("1", "NONE")
'''


_WORLD_MONSTER_VERIFY_BODY = r'''
local LEVEL = __LEVEL__
local role_hex, kingdom = identity()
local state = _G.__MUMU_AUTOTASK_WORLD_MONSTER_SEARCH
if type(state) ~= "table" or state.level ~= LEVEL or state.requested ~= true
    or type(state.before_ids) ~= "table" then
    fail("world monster march verification state is unavailable")
end
local found_id = nil
for key, march in pairs(self_marches(kingdom)) do
    local id = march_id(march, key)
    if id ~= nil and state.before_ids[id] ~= true then
        local target = march_call(march, "GetTargetMapObjectId")
        local data = march_call(march, "GetData")
        if target == nil and type(data) == "table" then
            local attack = data.atk_monster or data.transaction_slg
            if type(attack) == "table" then target = attack.monster_id end
        end
        local x, y = march_call(march, "GetEndPos")
        if target == state.monster_id and x == state.world_x and y == state.world_y then
            if found_id ~= nil then
                fail("multiple new marches matched the searched monster")
            end
            found_id = id
        end
    end
end
if found_id ~= nil then
    local known = _G.__MUMU_AUTOTASK_WORLD_MONSTER_MARCHES
    if type(known) ~= "table" then known = {} end
    known[found_id] = {
        level = LEVEL,
        monster_id = state.monster_id,
        world_x = state.world_x,
        world_y = state.world_y,
    }
    _G.__MUMU_AUTOTASK_WORLD_MONSTER_MARCHES = known
end
return table.concat({
    "MUMU_AUTOTASK\t1\tWORLD_MONSTER_VERIFY",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "LEVEL\t" .. tostring(LEVEL),
    "MONSTER\t" .. tostring(state.monster_id),
    "POINT\t" .. tostring(state.world_x) .. "\t" .. tostring(state.world_y),
    "MARCH\t" .. (found_id ~= nil and tostring(found_id) or "missing"),
    "STAMINA\t" .. tostring(current_stamina()),
    "END\t1",
}, "\n")
'''


_WORLD_MARCH_CAPACITY_BODY = r'''
local role_hex, kingdom = identity()
local current, maximum = march_capacity()
return table.concat({
    "MUMU_AUTOTASK\t1\tWORLD_MARCH_CAPACITY",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "QUEUE\t" .. tostring(current) .. "\t" .. tostring(maximum),
    "STAMINA\t" .. tostring(current_stamina()),
    "END\t1",
}, "\n")
'''


_WORLD_MONSTER_STATUS_BODY = r'''
local MARCH_IDS = { __MARCH_IDS__ }
local role_hex, kingdom = identity()
local current_marches, max_marches = march_capacity()
local active = {}
for key, march in pairs(self_marches(kingdom)) do
    local id = march_id(march, key)
    if id ~= nil then active[id] = true end
end
local known = _G.__MUMU_AUTOTASK_WORLD_MONSTER_MARCHES
if type(known) ~= "table" then known = {} end
local lines = {
    "MUMU_AUTOTASK\t1\tWORLD_MONSTER_STATUS",
    "ROLE\t" .. role_hex,
    "KINGDOM\t" .. tostring(kingdom),
    "QUEUE\t" .. tostring(current_marches) .. "\t" .. tostring(max_marches),
    "STAMINA\t" .. tostring(current_stamina()),
}
for _, id in ipairs(MARCH_IDS) do
    local status = "UNKNOWN"
    if active[id] then
        status = "ACTIVE"
        if known[id] == nil then known[id] = { observed = true } end
    elseif known[id] ~= nil then
        status = "RETURNED"
    end
    lines[#lines + 1] = "MARCH\t" .. tostring(id) .. "\t" .. status
end
_G.__MUMU_AUTOTASK_WORLD_MONSTER_MARCHES = known
lines[#lines + 1] = "END\t" .. tostring(#MARCH_IDS)
return table.concat(lines, "\n")
'''


def _world_monster_lua(level: int, body: str) -> str:
    normalized = normalize_world_monster_level(level)
    return _finalize_lua(
        textwrap.dedent(_WORLD_MONSTER_COMMON + body.replace("__LEVEL__", str(normalized)))
    )


def build_world_monster_search_lua(level: int) -> str:
    return _world_monster_lua(level, _WORLD_MONSTER_SEARCH_BODY)


def build_world_monster_search_result_lua(level: int) -> str:
    return _world_monster_lua(level, _WORLD_MONSTER_SEARCH_RESULT_BODY)


def build_world_monster_commit_lua(level: int) -> str:
    return _world_monster_lua(level, _WORLD_MONSTER_COMMIT_BODY)


def build_world_monster_verify_lua(level: int) -> str:
    return _world_monster_lua(level, _WORLD_MONSTER_VERIFY_BODY)


def build_world_march_capacity_lua() -> str:
    return _finalize_lua(textwrap.dedent(_WORLD_MONSTER_COMMON + _WORLD_MARCH_CAPACITY_BODY))


def build_world_monster_status_lua(march_ids: Sequence[int]) -> str:
    normalized = normalize_world_monster_march_ids(march_ids)
    ids = ", ".join(str(march_id) for march_id in normalized)
    return _finalize_lua(
        textwrap.dedent(
            _WORLD_MONSTER_COMMON
            + _WORLD_MONSTER_STATUS_BODY.replace("__MARCH_IDS__", ids)
        )
    )


_YETI_COMMON = r'''
local YETI_MARCH_TYPE = 501
local YETI_SOLDIER_ID = 10500

local function yeti_activity()
    if type(GDefine) ~= "table" or type(GDefine.ActivityDefine) ~= "table"
        or type(GDefine.ActivityDefine.ActivityType) ~= "table"
        or GDefine.ActivityDefine.ActivityType.IceFieldHunter == nil then
        fail("ice field hunter activity type is unavailable")
    end
    local show_state, activity_id, finish_time = call(
        GCtrl.ActivityCtrl,
        "GetShowStateByType",
        "ice field hunter activity",
        GDefine.ActivityDefine.ActivityType.IceFieldHunter
    )
    activity_id = integer(activity_id, "ice field hunter activity id", false)
    if type(GDefine.ActivityDefine.TabState) ~= "table"
        or show_state ~= GDefine.ActivityDefine.TabState.Show then
        fail("ice field hunter activity is not currently visible")
    end
    if type(finish_time) == "number" then
        if type(TimeUtil) ~= "table" or type(TimeUtil.GetServerTime) ~= "function" then
            fail("server time is unavailable")
        end
        if finish_time <= TimeUtil.GetServerTime() then
            fail("ice field hunter activity has ended")
        end
    end
    return show_state, activity_id, finish_time
end

local function yeti_boss(activity_id)
    local boss = call(GCtrl.IceFieldHunterCtrl, "GetBossData",
        "ice field hunter boss", activity_id)
    if boss == nil then return nil end
    if type(boss) ~= "table" then fail("ice field hunter boss data is invalid") end
    return {
        id = integer(boss.id, "yeti monster id", false),
        x = integer(boss.x, "yeti world x", true),
        y = integer(boss.y, "yeti world y", true),
    }
end

local function march_type(march)
    for _, method_name in ipairs({ "GetType", "GetMarchType" }) do
        local value = march_call(march, method_name)
        if type(value) == "number" then return value end
    end
    local data = march_call(march, "GetData")
    if type(data) == "table" then
        for _, key in ipairs({ "type", "march_type", "marchType" }) do
            if type(data[key]) == "number" then return data[key] end
        end
    end
    return nil
end

local function active_yeti_rallies(kingdom)
    local function contains_yeti(marches)
        if type(marches) ~= "table" then return false end
        for _, march in pairs(marches) do
            if march_type(march) == YETI_MARCH_TYPE then return true end
        end
        return false
    end
    if contains_yeti(self_marches(kingdom)) then return 1 end
    if type(GCtrl.WorldMarchCtrl.GetJoinedMassMarchMap) == "function" then
        local ok, joined = pcall(
            GCtrl.WorldMarchCtrl.GetJoinedMassMarchMap,
            GCtrl.WorldMarchCtrl
        )
        if ok and contains_yeti(joined) then return 1 end
    end
    if type(GHelper) == "table" and type(GHelper.WorldMarchHelper) == "table"
        and type(GHelper.WorldMarchHelper.HasOwnActiveMarchByType) == "function" then
        local ok, active = pcall(
            GHelper.WorldMarchHelper.HasOwnActiveMarchByType,
            GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL,
            YETI_MARCH_TYPE,
            true
        )
        if ok and active == true then return 1 end
    end
    return 0
end

local function yeti_status_lines(role_hex, kingdom)
    local _, activity_id = yeti_activity()
    local boss = yeti_boss(activity_id)
    local current, maximum = march_capacity()
    local active = active_yeti_rallies(kingdom)
    return boss, current, maximum, active, {
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "QUEUE\t" .. tostring(current) .. "\t" .. tostring(maximum),
        "STAMINA\t" .. tostring(current_stamina()),
        "ACTIVE_RALLIES\t" .. tostring(active),
        "SPAWN_PENDING\t0",
        "PREPARED\t" .. (boss ~= nil and "1" or "0"),
        "TARGET\t" .. (boss ~= nil and (
            tostring(boss.id) .. "\t" .. tostring(boss.x) .. "\t" .. tostring(boss.y)
        ) or "missing\tmissing\tmissing"),
    }
end
'''


_YETI_STATUS_BODY = r'''
local role_hex, kingdom = identity()
local _, _, _, _, lines = yeti_status_lines(role_hex, kingdom)
table.insert(lines, 1, "MUMU_AUTOTASK\t1\tYETI_STATUS")
lines[#lines + 1] = "END\t1"
return table.concat(lines, "\n")
'''


_YETI_SPAWN_BODY = r'''
local role_hex, kingdom = identity()
local _, activity_id = yeti_activity()
local boss = yeti_boss(activity_id)
local active = active_yeti_rallies(kingdom)
local function result(sent, reason)
    return table.concat({
        "MUMU_AUTOTASK\t1\tYETI_SPAWN",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "SENT\t" .. sent,
        "REASON\t" .. reason,
        "END\t1",
    }, "\n")
end
if boss ~= nil then return result("0", "TARGET_ALREADY_PREPARED") end
if active > 0 then return result("0", "YETI_RALLY_ACTIVE") end
local cost = GRead.IceFieldHunterRead.Cost(activity_id)
if type(cost) ~= "table" or type(cost[1]) ~= "number"
    or type(cost[2]) ~= "number" then
    fail("ice field hunter summon cost is unavailable")
end
local item_id = integer(cost[1], "ice field hunter summon item id", false)
local item_count = integer(cost[2], "ice field hunter summon item count", false)
local enough = false
if type(GHelper.ItemHelper) == "table"
    and type(GHelper.ItemHelper.CheckCount) == "function" then
    local ok, value = pcall(GHelper.ItemHelper.CheckCount, item_id, item_count)
    enough = ok and value == true
end
if not enough then return result("0", "INSUFFICIENT_SUMMON_ITEM") end
local ok = pcall(GCtrl.SpSummonCtrl.ReqIceFieldHunterSpawnMonster,
    GCtrl.SpSummonCtrl, nil, item_id)
if not ok then fail("ice field hunter summon request failed") end
return result("1", "NONE")
'''


_YETI_COMMIT_BODY = r'''
local PREPARE_TIME_INDEX = __PREPARE_TIME_INDEX__
local role_hex, kingdom = identity()
local _, activity_id = yeti_activity()
local boss = yeti_boss(activity_id)
local current, maximum = march_capacity()
local active = active_yeti_rallies(kingdom)
local stamina = current_stamina()
local function result(sent, reason, required)
    return table.concat({
        "MUMU_AUTOTASK\t1\tYETI_COMMIT",
        "ROLE\t" .. role_hex,
        "KINGDOM\t" .. tostring(kingdom),
        "TARGET\t" .. (boss ~= nil and (
            tostring(boss.id) .. "\t" .. tostring(boss.x) .. "\t" .. tostring(boss.y)
        ) or "missing\tmissing\tmissing"),
        "QUEUE\t" .. tostring(current) .. "\t" .. tostring(maximum),
        "STAMINA\t" .. tostring(stamina) .. "\t" .. tostring(required or 0),
        "ACTIVE_RALLIES\t" .. tostring(active),
        "SENT\t" .. sent,
        "REASON\t" .. reason,
        "END\t1",
    }, "\n")
end
if active > 0 then return result("0", "YETI_RALLY_ACTIVE", 0) end
if boss == nil then return result("0", "NO_PREPARED_TARGET", 0) end
if current >= maximum then return result("0", "NO_IDLE_MARCH_QUEUE", 0) end
local extra = {
    monsterid = boss.id,
    prepare_time_index = PREPARE_TIME_INDEX,
}
local heroes = GHelper.ExpeditionHelper.GetRecommendedHeroList(
    false, false, YETI_MARCH_TYPE, boss.id,
    GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL, extra)
if type(heroes) ~= "table"
    or GHelper.FormationHelper.IsHaveCaptain(heroes) ~= true then
    fail("yeti formation selected no available captain")
end
local hero_ids = GHelper.FormationHelper.DealWithExpeditionInfo(heroes, {})
if type(hero_ids) ~= "table" or next(hero_ids) == nil then
    fail("yeti recommended hero payload is unavailable")
end
local formation_limit = integer(GHelper.ExpeditionHelper.GetTroopLimit(
    GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL,
    heroes,
    GDefine.HeroDefine.HeroAttrType.SLG,
    extra
), "yeti formation limit", false)
local open_params = {
    marchMapType = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL,
    marchType = YETI_MARCH_TYPE,
    formationNumLimt = formation_limit,
    targetId = boss.id,
    isAttack = true,
}
local available = GHelper.ExpeditionHelper.GetSoldierInfoByMarchType(
    YETI_MARCH_TYPE, 0, false, open_params, nil)
local shield_available = false
if type(available) == "table" then
    for _, item in ipairs(available) do
        if type(item) == "table" and item.id == YETI_SOLDIER_ID
            and type(item.allNum) == "number" and item.allNum >= 1 then
            shield_available = true
            break
        end
    end
end
if not shield_available then return result("0", "NO_LEVEL5_SHIELD", 0) end
local base_stamina = integer(GRead.WorldRead.GetMapBossAttackCostEnergy(),
    "yeti base stamina", false)
local reduction = GHelper.AttributeHelper.GetCostStaminaEduce(heroes)
if type(reduction) ~= "number" or reduction < 0 or reduction > 1 then
    fail("yeti stamina reduction is invalid")
end
local required = integer(math.ceil(base_stamina * (1 - reduction)),
    "yeti required stamina", true)
if stamina < required then return result("0", "INSUFFICIENT_STAMINA", required) end
if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
    GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL,
    YETI_MARCH_TYPE,
    nil,
    false
) then
    return result("0", "NO_IDLE_MARCH_QUEUE", required)
end
local ok = pcall(GHelper.WorldMarchHelper.RequestMarchStartOff,
    GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL,
    YETI_MARCH_TYPE,
    boss.x,
    boss.y,
    { hero_id = hero_ids, soldier = { [YETI_SOLDIER_ID] = 1 } },
    extra)
if not ok then fail("yeti rally request failed") end
return result("1", "NONE", required)
'''


def normalize_yeti_rally_minutes(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {3, 5, 10}:
        raise BusinessError("yeti rally minutes must be one of 3, 5, or 10")
    return value


def _yeti_lua(body: str) -> str:
    return _finalize_lua(textwrap.dedent(_WORLD_MONSTER_COMMON + _YETI_COMMON + body))


def build_yeti_status_lua() -> str:
    return _yeti_lua(_YETI_STATUS_BODY)


def build_yeti_spawn_lua() -> str:
    return _yeti_lua(_YETI_SPAWN_BODY)


def build_yeti_commit_lua(rally_minutes: int) -> str:
    minutes = normalize_yeti_rally_minutes(rally_minutes)
    prepare_time_index = {3: 1, 5: 2, 10: 3}[minutes]
    return _yeti_lua(
        _YETI_COMMIT_BODY.replace("__PREPARE_TIME_INDEX__", str(prepare_time_index))
    )


def build_close_expedition_lua(roles: Sequence[str]) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _CLOSE_EXPEDITION_BODY))


def build_scene_status_lua(roles: Sequence[str]) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _SCENE_STATUS_BODY))


def build_toggle_world_lua(roles: Sequence[str]) -> str:
    common = _LUA_COMMON.replace("__ROLE_TABLE__", _lua_role_table(roles))
    return _finalize_lua(textwrap.dedent(common + _TOGGLE_WORLD_BODY))


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


def select_battle_target(
    snapshot: BattleIntelSnapshot,
    category: str,
    runtime_id: int | None = None,
) -> BattleIntelItem:
    requested = normalize_battle_category(category)
    if runtime_id is not None:
        if isinstance(runtime_id, bool) or not isinstance(runtime_id, int) or runtime_id <= 0:
            raise BusinessError("battle target runtime id must be a positive integer")
        exact = [item for item in snapshot.items if item.runtime_id == runtime_id]
        if not exact:
            raise BusinessError(
                f"requested battle intelligence target {runtime_id} is no longer available"
            )
        target = exact[0]
        if target.status != 1:
            raise BusinessError(
                f"requested battle intelligence target {runtime_id} is not available"
            )
        if target.category != requested:
            raise BusinessError(
                f"requested battle intelligence target {runtime_id} is "
                f"{target.category}, not {requested}"
            )
        return target
    matches = [
        item
        for item in snapshot.items
        if item.category == requested and item.status == 1
    ]
    if not matches:
        raise BusinessError(f"no available {requested} battle intelligence was found")
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
    if roles and role not in roles:
        raise BusinessError("reported role is not in the device whitelist")
    return role


def _parse_kingdom_line(fields: list[str], location: str) -> int:
    if len(fields) != 2 or fields[0] != "KINGDOM":
        raise BusinessError(f"{location} output is missing KINGDOM")
    return _parse_integer(fields[1], f"{location} KINGDOM", allow_zero=False)


def _parse_item(fields: list[str], location: str) -> IntelItem:
    if len(fields) != 13 or fields[0] != "ITEM":
        raise BusinessError(f"{location} must contain exactly 13 ITEM fields")
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
        recommended_power=_parse_integer(
            fields[12], f"{location} recommended power", allow_zero=False
        ),
    )


def _parse_battle_item(fields: list[str], location: str) -> BattleIntelItem:
    if len(fields) != 15 or fields[0] != "ITEM":
        raise BusinessError(f"{location} must contain 14 fields")
    category = normalize_battle_category(fields[7])
    quest_type = _parse_integer(fields[8], f"{location} quest type", allow_zero=False)
    if BATTLE_CATEGORY_TYPES[category] != quest_type:
        raise BusinessError(f"{location} category/type disagree")
    quality = normalize_quality(fields[9])
    if quality != fields[9]:
        raise BusinessError(f"{location} quality must use its canonical name")
    quality_id = _parse_integer(fields[10], f"{location} quality id", allow_zero=False)
    if QUALITY_IDS[quality] != quality_id:
        raise BusinessError(f"{location} quality name/id disagree")
    return BattleIntelItem(
        runtime_id=_parse_integer(fields[1], f"{location} runtime id", allow_zero=False),
        quest_id=_parse_integer(fields[2], f"{location} quest id", allow_zero=False),
        status=_parse_integer(fields[3], f"{location} status", allow_zero=True),
        world_x=_parse_integer(fields[4], f"{location} world x", allow_zero=True),
        world_y=_parse_integer(fields[5], f"{location} world y", allow_zero=True),
        expires_at=_parse_integer(fields[6], f"{location} expiry", allow_zero=False),
        category=category,
        quest_type=quest_type,
        quality=quality,
        quality_id=quality_id,
        condition=_parse_integer(fields[11], f"{location} condition", allow_zero=True),
        level=_parse_integer(fields[12], f"{location} level", allow_zero=True),
        stamina_cost=_parse_integer(
            fields[13], f"{location} stamina cost", allow_zero=True
        ),
        power_level=_parse_integer(
            fields[14], f"{location} power level", allow_zero=True
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
    kingdom = _parse_kingdom_line(lines[2], "INTEL")
    item_start = 3
    current_stamina: int | None = None
    if len(lines) > 3 and len(lines[3]) == 2 and lines[3][0] == "STAMINA":
        current_stamina = _parse_integer(
            lines[3][1],
            "INTEL current stamina",
            allow_zero=True,
        )
        item_start = 4
    if len(lines[-1]) != 2 or lines[-1][0] != "END":
        raise BusinessError("INTEL output is missing END")
    count = _parse_integer(lines[-1][1], "END count", allow_zero=True)
    item_lines = lines[item_start:-1]
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
    return IntelSnapshot(
        role=role,
        kingdom=kingdom,
        items=items,
        current_stamina=current_stamina,
    )


def parse_battle_intel_output(
    output: str,
    allowed_roles: Sequence[str],
    expected_category: str,
) -> BattleIntelSnapshot:
    category = normalize_battle_category(expected_category)
    lines = _protocol_lines(output, "BATTLE_INTEL")
    if len(lines) < 4 or len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("BATTLE_INTEL output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    kingdom = _parse_kingdom_line(lines[2], "BATTLE_INTEL")
    if len(lines[-1]) != 2 or lines[-1][0] != "END":
        raise BusinessError("BATTLE_INTEL output is missing END")
    count = _parse_integer(lines[-1][1], "END count", allow_zero=True)
    item_lines = lines[3:-1]
    if count != len(item_lines):
        raise BusinessError("BATTLE_INTEL END count does not match ITEM lines")
    if count > 128:
        raise BusinessError("BATTLE_INTEL output contains more than 128 items")
    items = tuple(
        _parse_battle_item(fields, f"ITEM[{index}]")
        for index, fields in enumerate(item_lines)
    )
    if any(item.category != category for item in items):
        raise BusinessError("BATTLE_INTEL output category does not match the request")
    runtime_ids = [item.runtime_id for item in items]
    if len(runtime_ids) != len(set(runtime_ids)):
        raise BusinessError("BATTLE_INTEL output contains duplicate runtime ids")
    expected_order = sorted(
        items,
        key=lambda item: (item.quest_type, item.quality_id, item.expires_at, item.runtime_id),
    )
    if list(items) != expected_order:
        raise BusinessError("BATTLE_INTEL items are not in canonical order")
    return BattleIntelSnapshot(role=role, kingdom=kingdom, items=items)


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
    kingdom = _parse_kingdom_line(lines[2], "INTEL_STATUS")

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
        kingdom=kingdom,
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
    kingdom = _parse_kingdom_line(lines[2], "CLAIM_INTEL")
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
        kingdom=kingdom,
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
    kingdom = _parse_kingdom_line(lines[2], "SCENE")
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
        kingdom=kingdom,
        scene_type=scene_type,
        map_type=map_type,
        class_name=scene_line[3],
        is_world=world_line[1] == "1",
        is_city=world_line[3] == "1",
        loading=_parse_missing_bool(busy_line[2], "SCENE loading"),
        transition=_parse_missing_bool(busy_line[4], "SCENE transition"),
    )


def parse_toggle_world_output(
    output: str,
    allowed_roles: Sequence[str],
) -> tuple[str, int]:
    """Validate the native city/world entrance invocation response."""

    lines = _protocol_lines(output, "TOGGLE_WORLD")
    if len(lines) != 5:
        raise BusinessError("TOGGLE_WORLD output must contain exactly 5 lines")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("TOGGLE_WORLD output is missing ROLE")
    role = _parse_role(lines[1][1], allowed_roles)
    kingdom = _parse_kingdom_line(lines[2], "TOGGLE_WORLD")
    if lines[3] != ["INVOKED", "1"]:
        raise BusinessError("TOGGLE_WORLD output did not confirm invocation")
    if lines[4] != ["END", "1"]:
        raise BusinessError("TOGGLE_WORLD output has an invalid terminator")
    return role, kingdom


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
    _parse_kingdom_line(lines[2], kind)
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


def _parse_stamina_stage(
    output: str,
    kind: str,
    action_name: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> tuple[bool, int, int, int, str | None]:
    lines = _parse_target_stage(output, kind, allowed_roles, target)
    if (
        len(lines) != 9
        or lines[4] != ["AVERAGE", "1"]
        or len(lines[5]) != 4
        or lines[5][0] != "STAMINA"
        or len(lines[6]) != 2
        or lines[6][0] != action_name
        or lines[6][1] not in {"0", "1"}
        or len(lines[7]) != 2
        or lines[7][0] != "REASON"
    ):
        raise BusinessError(
            f"{kind} output has invalid average, stamina, or {action_name.lower()} fields"
        )
    current_stamina = _parse_integer(
        lines[5][1], f"{kind} current stamina", allow_zero=True
    )
    required_stamina = _parse_integer(
        lines[5][2], f"{kind} required stamina", allow_zero=True
    )
    base_stamina = _parse_integer(
        lines[5][3], f"{kind} base stamina", allow_zero=False
    )
    if base_stamina != target.stamina_cost:
        raise BusinessError(f"{kind} base stamina does not match the target")
    succeeded = lines[6][1] == "1"
    reason = lines[7][1]
    if succeeded:
        if reason != "NONE" or current_stamina < required_stamina:
            raise BusinessError(f"{kind} state is inconsistent with stamina")
        blocked_reason = None
    else:
        if reason != "INSUFFICIENT_STAMINA" or current_stamina >= required_stamina:
            raise BusinessError(f"{kind} blocked state is inconsistent with stamina")
        blocked_reason = "insufficient_stamina"
    return (
        succeeded,
        current_stamina,
        required_stamina,
        base_stamina,
        blocked_reason,
    )


def parse_prepare_output(
    output: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> MarchPrepareReceipt:
    ready, current, required, base, blocked = _parse_stamina_stage(
        output,
        "PREPARE",
        "READY",
        allowed_roles,
        target,
    )
    return MarchPrepareReceipt(
        ready_to_commit=ready,
        current_stamina=current,
        required_stamina=required,
        base_stamina=base,
        blocked_reason=blocked,
    )


def parse_commit_output(
    output: str,
    allowed_roles: Sequence[str],
    target: IntelItem,
) -> MarchCommitReceipt:
    dispatched, current_stamina, required_stamina, base_stamina, blocked_reason = (
        _parse_stamina_stage(
            output,
            "COMMIT",
            "GO",
            allowed_roles,
            target,
        )
    )
    return MarchCommitReceipt(
        request_dispatched=dispatched,
        current_stamina=current_stamina,
        required_stamina=required_stamina,
        base_stamina=base_stamina,
        blocked_reason=blocked_reason,
    )


def _parse_world_monster_identity(
    lines: list[list[str]], kind: str
) -> tuple[str, int]:
    if len(lines) < 4 or len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError(f"{kind} output is missing ROLE")
    role = _parse_role(lines[1][1], ())
    kingdom = _parse_kingdom_line(lines[2], kind)
    return role, kingdom


def parse_world_monster_search_sent_output(output: str, level: int) -> None:
    requested_level = normalize_world_monster_level(level)
    lines = _protocol_lines(output, "WORLD_MONSTER_SEARCH_SENT")
    _parse_world_monster_identity(lines, "WORLD_MONSTER_SEARCH_SENT")
    if (
        len(lines) != 6
        or lines[3] != ["LEVEL", str(requested_level)]
        or lines[4] != ["SENT", "1"]
        or lines[5] != ["END", "1"]
    ):
        raise BusinessError("WORLD_MONSTER_SEARCH_SENT output is invalid")


def parse_world_monster_search_output(
    output: str, level: int
) -> WorldMonsterSearchReceipt:
    requested_level = normalize_world_monster_level(level)
    lines = _protocol_lines(output, "WORLD_MONSTER_SEARCH")
    role, kingdom = _parse_world_monster_identity(lines, "WORLD_MONSTER_SEARCH")
    if (
        len(lines) != 9
        or lines[3] != ["LEVEL", str(requested_level)]
        or lines[4] not in (["READY", "0"], ["READY", "1"])
        or len(lines[5]) != 3 or lines[5][0] != "POINT"
        or len(lines[6]) != 3 or lines[6][0] != "MONSTER"
        or len(lines[7]) != 2 or lines[7][0] != "STAMINA"
        or lines[8] != ["END", "1"]
    ):
        raise BusinessError("WORLD_MONSTER_SEARCH output is invalid")
    ready = lines[4][1] == "1"
    stamina = _parse_integer(
        lines[7][1], "WORLD_MONSTER_SEARCH stamina", allow_zero=True
    )
    if not ready:
        if (
            lines[6][1:] != ["missing", "missing"]
            or (
                lines[5][1:] != ["missing", "missing"]
                and any(
                    _INTEGER_PATTERN.fullmatch(value) is None
                    for value in lines[5][1:]
                )
            )
        ):
            raise BusinessError("WORLD_MONSTER_SEARCH pending state is inconsistent")
        return WorldMonsterSearchReceipt(
            role, kingdom, requested_level, False, None, None, None, None, stamina
        )
    world_x = _parse_integer(
        lines[5][1], "WORLD_MONSTER_SEARCH world x", allow_zero=True
    )
    world_y = _parse_integer(
        lines[5][2], "WORLD_MONSTER_SEARCH world y", allow_zero=True
    )
    monster_id = _parse_integer(
        lines[6][1], "WORLD_MONSTER_SEARCH monster id", allow_zero=False
    )
    recommended_power = _parse_integer(
        lines[6][2], "WORLD_MONSTER_SEARCH recommended power", allow_zero=False
    )
    return WorldMonsterSearchReceipt(
        role, kingdom, requested_level, True, world_x, world_y,
        monster_id, recommended_power, stamina
    )


def parse_world_monster_commit_output(
    output: str, search: WorldMonsterSearchReceipt
) -> WorldMonsterHuntReceipt:
    if not isinstance(search, WorldMonsterSearchReceipt) or not search.ready:
        raise BusinessError("world monster commit requires a ready search result")
    lines = _protocol_lines(output, "WORLD_MONSTER_COMMIT")
    role, kingdom = _parse_world_monster_identity(lines, "WORLD_MONSTER_COMMIT")
    if (
        len(lines) != 12 or role != search.role or kingdom != search.kingdom
        or lines[3] != ["LEVEL", str(search.level)]
        or lines[4] != ["MONSTER", str(search.monster_id)]
        or lines[5] != ["POINT", str(search.world_x), str(search.world_y)]
        or lines[6] != ["AVERAGE", "1"]
        or len(lines[7]) != 4 or lines[7][0] != "STAMINA"
        or len(lines[8]) != 3 or lines[8][0] != "QUEUE"
        or lines[9] not in (["SENT", "0"], ["SENT", "1"])
        or len(lines[10]) != 2 or lines[10][0] != "REASON"
        or lines[11] != ["END", "1"]
    ):
        raise BusinessError("WORLD_MONSTER_COMMIT output is invalid")
    current = _parse_integer(lines[7][1], "world monster stamina", allow_zero=True)
    required = _parse_integer(lines[7][2], "world monster required stamina", allow_zero=True)
    base = _parse_integer(lines[7][3], "world monster base stamina", allow_zero=False)
    current_marches = _parse_integer(
        lines[8][1], "world monster current marches", allow_zero=True
    )
    max_marches = _parse_integer(
        lines[8][2], "world monster maximum marches", allow_zero=False
    )
    if current_marches > max_marches:
        raise BusinessError("WORLD_MONSTER_COMMIT queue state is inconsistent")
    dispatched = lines[9][1] == "1"
    if dispatched:
        if lines[10][1] != "NONE" or current < required \
                or current_marches >= max_marches:
            raise BusinessError("WORLD_MONSTER_COMMIT dispatch state is inconsistent")
        blocked_reason = None
    else:
        reason = lines[10][1]
        if reason == "INSUFFICIENT_STAMINA":
            if current >= required:
                raise BusinessError("WORLD_MONSTER_COMMIT blocked state is inconsistent")
            blocked_reason = "insufficient_stamina"
        elif reason == "NO_IDLE_MARCH_QUEUE":
            blocked_reason = "no_idle_march_queue"
        else:
            raise BusinessError("WORLD_MONSTER_COMMIT blocked reason is invalid")
    return WorldMonsterHuntReceipt(
        role, kingdom, search.level, int(search.monster_id),
        int(search.world_x), int(search.world_y), dispatched,
        current, required, base, current_marches, max_marches, blocked_reason
    )


def parse_world_march_capacity_output(output: str) -> WorldMarchCapacity:
    lines = _protocol_lines(output, "WORLD_MARCH_CAPACITY")
    role, kingdom = _parse_world_monster_identity(lines, "WORLD_MARCH_CAPACITY")
    if (
        len(lines) != 6
        or len(lines[3]) != 3 or lines[3][0] != "QUEUE"
        or len(lines[4]) != 2 or lines[4][0] != "STAMINA"
        or lines[5] != ["END", "1"]
    ):
        raise BusinessError("WORLD_MARCH_CAPACITY output is invalid")
    current = _parse_integer(
        lines[3][1], "WORLD_MARCH_CAPACITY current marches", allow_zero=True
    )
    maximum = _parse_integer(
        lines[3][2], "WORLD_MARCH_CAPACITY maximum marches", allow_zero=False
    )
    stamina = _parse_integer(
        lines[4][1], "WORLD_MARCH_CAPACITY stamina", allow_zero=True
    )
    if current > maximum:
        raise BusinessError("WORLD_MARCH_CAPACITY queue state is inconsistent")
    return WorldMarchCapacity(role, kingdom, current, maximum, stamina)


def parse_world_monster_verify_output(
    output: str, search: WorldMonsterSearchReceipt
) -> WorldMonsterMarchReceipt:
    if not isinstance(search, WorldMonsterSearchReceipt) or not search.ready:
        raise BusinessError("world monster verification requires a ready search result")
    lines = _protocol_lines(output, "WORLD_MONSTER_VERIFY")
    role, kingdom = _parse_world_monster_identity(lines, "WORLD_MONSTER_VERIFY")
    if (
        len(lines) != 9 or role != search.role or kingdom != search.kingdom
        or lines[3] != ["LEVEL", str(search.level)]
        or lines[4] != ["MONSTER", str(search.monster_id)]
        or lines[5] != ["POINT", str(search.world_x), str(search.world_y)]
        or len(lines[6]) != 2 or lines[6][0] != "MARCH"
        or len(lines[7]) != 2 or lines[7][0] != "STAMINA"
        or lines[8] != ["END", "1"]
    ):
        raise BusinessError("WORLD_MONSTER_VERIFY output is invalid")
    march_id = None if lines[6][1] == "missing" else _parse_integer(
        lines[6][1], "WORLD_MONSTER_VERIFY march id", allow_zero=False
    )
    current_stamina = _parse_integer(
        lines[7][1], "WORLD_MONSTER_VERIFY stamina", allow_zero=True
    )
    return WorldMonsterMarchReceipt(
        role, kingdom, search.level, int(search.monster_id),
        int(search.world_x), int(search.world_y), march_id, current_stamina
    )


def parse_world_monster_status_output(
    output: str, march_ids: Sequence[int]
) -> WorldMonsterStatusSnapshot:
    expected_ids = normalize_world_monster_march_ids(march_ids)
    lines = _protocol_lines(output, "WORLD_MONSTER_STATUS")
    role, kingdom = _parse_world_monster_identity(lines, "WORLD_MONSTER_STATUS")
    if (
        len(lines) != len(expected_ids) + 6
        or len(lines[3]) != 3 or lines[3][0] != "QUEUE"
        or len(lines[4]) != 2 or lines[4][0] != "STAMINA"
        or lines[-1] != ["END", str(len(expected_ids))]
    ):
        raise BusinessError("WORLD_MONSTER_STATUS output is invalid")
    stamina = _parse_integer(
        lines[4][1], "WORLD_MONSTER_STATUS stamina", allow_zero=True
    )
    current_marches = _parse_integer(
        lines[3][1], "WORLD_MONSTER_STATUS current marches", allow_zero=True
    )
    max_marches = _parse_integer(
        lines[3][2], "WORLD_MONSTER_STATUS maximum marches", allow_zero=False
    )
    if current_marches > max_marches:
        raise BusinessError("WORLD_MONSTER_STATUS queue state is inconsistent")
    statuses: list[WorldMonsterMarchStatus] = []
    for index, (march_id, fields) in enumerate(
        zip(expected_ids, lines[5:-1], strict=True)
    ):
        if len(fields) != 3 or fields[0] != "MARCH" \
                or fields[1] != str(march_id):
            raise BusinessError(
                f"WORLD_MONSTER_STATUS MARCH[{index}] does not match the request"
            )
        if fields[2] == "UNKNOWN":
            raise BusinessError(
                f"world monster march id {march_id} was never observed in this game process"
            )
        if fields[2] not in {"ACTIVE", "RETURNED"}:
            raise BusinessError(f"WORLD_MONSTER_STATUS MARCH[{index}] is invalid")
        statuses.append(WorldMonsterMarchStatus(march_id, fields[2]))
    return WorldMonsterStatusSnapshot(
        role, kingdom, stamina, current_marches, max_marches, tuple(statuses)
    )


def parse_yeti_status_output(output: str) -> YetiRallyStatus:
    lines = _protocol_lines(output, "YETI_STATUS")
    role, kingdom = _parse_world_monster_identity(lines, "YETI_STATUS")
    if (
        len(lines) != 10
        or len(lines[3]) != 3 or lines[3][0] != "QUEUE"
        or len(lines[4]) != 2 or lines[4][0] != "STAMINA"
        or len(lines[5]) != 2 or lines[5][0] != "ACTIVE_RALLIES"
        or lines[6] not in (["SPAWN_PENDING", "0"], ["SPAWN_PENDING", "1"])
        or lines[7] not in (["PREPARED", "0"], ["PREPARED", "1"])
        or len(lines[8]) != 4 or lines[8][0] != "TARGET"
        or lines[9] != ["END", "1"]
    ):
        raise BusinessError("YETI_STATUS output is invalid")
    current = _parse_integer(lines[3][1], "YETI_STATUS current marches", allow_zero=True)
    maximum = _parse_integer(lines[3][2], "YETI_STATUS maximum marches", allow_zero=False)
    stamina = _parse_integer(lines[4][1], "YETI_STATUS stamina", allow_zero=True)
    active = _parse_integer(lines[5][1], "YETI_STATUS active rallies", allow_zero=True)
    if current > maximum or active > 1:
        raise BusinessError("YETI_STATUS queue state is inconsistent")
    prepared = lines[7][1] == "1"
    if prepared:
        monster_id = _parse_integer(lines[8][1], "YETI_STATUS monster id", allow_zero=False)
        world_x = _parse_integer(lines[8][2], "YETI_STATUS world x", allow_zero=True)
        world_y = _parse_integer(lines[8][3], "YETI_STATUS world y", allow_zero=True)
    else:
        if lines[8][1:] != ["missing", "missing", "missing"]:
            raise BusinessError("YETI_STATUS target state is inconsistent")
        monster_id = world_x = world_y = None
    return YetiRallyStatus(
        role, kingdom, stamina, current, maximum, active, prepared,
        world_x, world_y, monster_id,
    )


def parse_yeti_spawn_output(output: str) -> YetiSpawnReceipt:
    lines = _protocol_lines(output, "YETI_SPAWN")
    role, kingdom = _parse_world_monster_identity(lines, "YETI_SPAWN")
    if (
        len(lines) != 6
        or lines[3] not in (["SENT", "0"], ["SENT", "1"])
        or len(lines[4]) != 2 or lines[4][0] != "REASON"
        or lines[5] != ["END", "1"]
    ):
        raise BusinessError("YETI_SPAWN output is invalid")
    dispatched = lines[3][1] == "1"
    reason = lines[4][1]
    allowed = {
        "TARGET_ALREADY_PREPARED": "target_already_prepared",
        "YETI_RALLY_ACTIVE": "yeti_rally_active",
        "SPAWN_PENDING": "spawn_pending",
        "INSUFFICIENT_SUMMON_ITEM": "insufficient_summon_item",
    }
    if dispatched:
        if reason != "NONE":
            raise BusinessError("YETI_SPAWN dispatch state is inconsistent")
        blocked_reason = None
    else:
        if reason not in allowed:
            raise BusinessError("YETI_SPAWN blocked reason is invalid")
        blocked_reason = allowed[reason]
    return YetiSpawnReceipt(role, kingdom, dispatched, blocked_reason)


def parse_yeti_commit_output(output: str) -> YetiCommitReceipt:
    lines = _protocol_lines(output, "YETI_COMMIT")
    role, kingdom = _parse_world_monster_identity(lines, "YETI_COMMIT")
    if (
        len(lines) != 10
        or len(lines[3]) != 4 or lines[3][0] != "TARGET"
        or len(lines[4]) != 3 or lines[4][0] != "QUEUE"
        or len(lines[5]) != 3 or lines[5][0] != "STAMINA"
        or len(lines[6]) != 2 or lines[6][0] != "ACTIVE_RALLIES"
        or lines[7] not in (["SENT", "0"], ["SENT", "1"])
        or len(lines[8]) != 2 or lines[8][0] != "REASON"
        or lines[9] != ["END", "1"]
    ):
        raise BusinessError("YETI_COMMIT output is invalid")
    current = _parse_integer(lines[4][1], "YETI_COMMIT current marches", allow_zero=True)
    maximum = _parse_integer(lines[4][2], "YETI_COMMIT maximum marches", allow_zero=False)
    stamina = _parse_integer(lines[5][1], "YETI_COMMIT stamina", allow_zero=True)
    required = _parse_integer(lines[5][2], "YETI_COMMIT required stamina", allow_zero=True)
    active = _parse_integer(lines[6][1], "YETI_COMMIT active rallies", allow_zero=True)
    if current > maximum or active > 1:
        raise BusinessError("YETI_COMMIT queue state is inconsistent")
    if lines[3][1:] == ["missing", "missing", "missing"]:
        monster_id = world_x = world_y = None
    else:
        monster_id = _parse_integer(
            lines[3][1], "YETI_COMMIT monster id", allow_zero=False
        )
        world_x = _parse_integer(lines[3][2], "YETI_COMMIT world x", allow_zero=True)
        world_y = _parse_integer(lines[3][3], "YETI_COMMIT world y", allow_zero=True)
    dispatched = lines[7][1] == "1"
    reason = lines[8][1]
    allowed = {
        "YETI_RALLY_ACTIVE": "yeti_rally_active",
        "NO_PREPARED_TARGET": "no_prepared_target",
        "NO_IDLE_MARCH_QUEUE": "no_idle_march_queue",
        "NO_LEVEL5_SHIELD": "no_level5_shield",
        "INSUFFICIENT_STAMINA": "insufficient_stamina",
    }
    if dispatched:
        if reason != "NONE" or current >= maximum or stamina < required or active != 0:
            raise BusinessError("YETI_COMMIT dispatch state is inconsistent")
        blocked_reason = None
    else:
        if reason not in allowed:
            raise BusinessError("YETI_COMMIT blocked reason is invalid")
        blocked_reason = allowed[reason]
    return YetiCommitReceipt(
        role, kingdom, dispatched, stamina, required,
        current, maximum, active, monster_id, world_x, world_y, blocked_reason,
    )


def parse_battle_commit_output(
    output: str,
    allowed_roles: Sequence[str],
    target: BattleIntelItem,
) -> tuple[int, ...]:
    lines = _protocol_lines(output, "BATTLE_COMMIT")
    if len(lines) < 7:
        raise BusinessError("BATTLE_COMMIT output is incomplete")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("BATTLE_COMMIT output is missing ROLE")
    _parse_role(lines[1][1], allowed_roles)
    _parse_kingdom_line(lines[2], "BATTLE_COMMIT")
    if lines[3] != ["TARGET", str(target.runtime_id)]:
        raise BusinessError("BATTLE_COMMIT output target does not match the request")
    if lines[4] != ["START", "1"]:
        raise BusinessError("BATTLE_COMMIT output did not confirm start request")
    if (
        len(lines[5]) != 2
        or lines[5][0] != "END_REQUEST"
        or lines[5][1] not in {"0", "1"}
    ):
        raise BusinessError("BATTLE_COMMIT output has an invalid end-request state")
    category = normalize_battle_category(target.category)
    if category != "hero":
        raise BusinessError("BATTLE_COMMIT target category must be hero")
    if lines[5][1] != "1":
        raise BusinessError(
            f"BATTLE_COMMIT output end-request state does not match {category}"
        )
    if lines[-1] != ["END", "1"]:
        raise BusinessError("BATTLE_COMMIT output has an invalid terminator")
    heroes: list[int] = []
    for index, fields in enumerate(lines[6:-1], start=1):
        if len(fields) != 3 or fields[0] != "HERO" or fields[1] != str(index):
            raise BusinessError("BATTLE_COMMIT output has an invalid HERO line")
        heroes.append(
            _parse_integer(fields[2], f"BATTLE_COMMIT HERO[{index}]", allow_zero=False)
        )
    if not heroes:
        raise BusinessError("BATTLE_COMMIT output selected no heroes")
    return tuple(heroes)


def parse_rescue_commit_output(
    output: str,
    allowed_roles: Sequence[str],
    target: BattleIntelItem,
) -> None:
    if normalize_battle_category(target.category) != "rescue":
        raise BusinessError("RESCUE_COMMIT target category must be rescue")
    lines = _protocol_lines(output, "RESCUE_COMMIT")
    if len(lines) != 8:
        raise BusinessError("RESCUE_COMMIT output must contain exactly 8 lines")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("RESCUE_COMMIT output is missing ROLE")
    _parse_role(lines[1][1], allowed_roles)
    _parse_kingdom_line(lines[2], "RESCUE_COMMIT")
    if lines[3] != ["TARGET", str(target.runtime_id)]:
        raise BusinessError("RESCUE_COMMIT output target does not match the request")
    if lines[4] != ["WORLD_MARCH", "1"]:
        raise BusinessError("RESCUE_COMMIT output did not confirm world march")
    if lines[5] != ["TYPE", "301"]:
        raise BusinessError("RESCUE_COMMIT output has an invalid march type")
    if lines[6] != ["MARCH_MAP_TYPE", "1"]:
        raise BusinessError("RESCUE_COMMIT output has an invalid march map type")
    if lines[7] != ["END", "1"]:
        raise BusinessError("RESCUE_COMMIT output has an invalid terminator")


def parse_battle_verify_output(
    output: str,
    allowed_roles: Sequence[str],
    target: BattleIntelItem,
) -> tuple[bool, str]:
    lines = _protocol_lines(output, "BATTLE_VERIFY")
    if len(lines) != 6:
        raise BusinessError("BATTLE_VERIFY output must contain exactly 6 lines")
    if len(lines[1]) != 2 or lines[1][0] != "ROLE":
        raise BusinessError("BATTLE_VERIFY output is missing ROLE")
    _parse_role(lines[1][1], allowed_roles)
    _parse_kingdom_line(lines[2], "BATTLE_VERIFY")
    if lines[3] != ["TARGET", str(target.runtime_id)]:
        raise BusinessError("BATTLE_VERIFY output target does not match the request")
    if (
        len(lines[4]) != 4
        or lines[4][0] != "ACCEPTED"
        or lines[4][1] not in {"0", "1"}
        or lines[4][2] != "STATUS"
    ):
        raise BusinessError("BATTLE_VERIFY output has an invalid acceptance state")
    if lines[5] != ["END", "1"]:
        raise BusinessError("BATTLE_VERIFY output has an invalid terminator")
    status = lines[4][3]
    if status != "missing":
        _parse_integer(status, "BATTLE_VERIFY status", allow_zero=True)
        if status not in {"1", "2", "3"}:
            raise BusinessError("BATTLE_VERIFY entered an unexpected quest status")
    accepted = lines[4][1] == "1"
    if accepted and status not in {"2", "3", "missing"}:
        raise BusinessError("BATTLE_VERIFY accepted without a terminal status")
    return accepted, status


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
    kingdom = _parse_kingdom_line(lines[2], "MARCH")
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
        kingdom=kingdom,
        quality=quality,
        quality_id=QUALITY_IDS[quality],
        target=target,
        request_dispatched=True,
    )


__all__ = [
    "ALLOWED_KINGDOM",
    "BATTLE_CATEGORY_ALIASES",
    "BATTLE_CATEGORY_BY_TYPE",
    "BATTLE_CATEGORY_TYPES",
    "BattleIntelItem",
    "BattleIntelSnapshot",
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
    "MarchCommitReceipt",
    "MarchPrepareReceipt",
    "MarchReceipt",
    "QUALITY_ALIASES",
    "QUALITY_BY_ID",
    "QUALITY_IDS",
    "SceneStatus",
    "WorldMonsterHuntReceipt",
    "WorldMonsterMarchReceipt",
    "WorldMonsterMarchStatus",
    "WorldMonsterSearchReceipt",
    "WorldMonsterStatusSnapshot",
    "WorldMarchCapacity",
    "YetiCommitReceipt",
    "YetiRallyStatus",
    "YetiSpawnReceipt",
    "build_claim_intel_lua",
    "build_close_expedition_lua",
    "build_commit_march_lua",
    "build_commit_prepared_march_lua",
    "build_direct_commit_march_lua",
    "build_install_march_capture_hook_lua",
    "build_inspect_battle_intel_lua",
    "build_inspect_formation_lua",
    "build_inspect_intel_lua",
    "build_intel_status_lua",
    "build_march_ready_lua",
    "build_open_march_lua",
    "build_prepare_direct_march_lua",
    "build_read_march_capture_hook_lua",
    "build_scene_status_lua",
    "build_start_battle_intel_lua",
    "build_start_rescue_intel_lua",
    "build_toggle_world_lua",
    "build_uninstall_march_capture_hook_lua",
    "build_verify_battle_intel_lua",
    "build_verify_march_lua",
    "build_world_monster_commit_lua",
    "build_world_march_capacity_lua",
    "build_world_monster_search_lua",
    "build_world_monster_search_result_lua",
    "build_world_monster_status_lua",
    "build_world_monster_verify_lua",
    "build_yeti_commit_lua",
    "build_yeti_spawn_lua",
    "build_yeti_status_lua",
    "normalize_battle_category",
    "normalize_quality",
    "normalize_target_ids",
    "normalize_world_monster_level",
    "normalize_world_monster_count",
    "normalize_world_monster_march_ids",
    "normalize_yeti_rally_minutes",
    "parse_battle_commit_output",
    "parse_battle_intel_output",
    "parse_battle_verify_output",
    "parse_claim_intel_output",
    "parse_commit_output",
    "parse_intel_output",
    "parse_intel_status_output",
    "parse_march_output",
    "parse_open_output",
    "parse_prepare_output",
    "parse_ready_output",
    "parse_rescue_commit_output",
    "parse_scene_status_output",
    "parse_toggle_world_output",
    "parse_verify_output",
    "parse_world_monster_commit_output",
    "parse_yeti_commit_output",
    "parse_yeti_spawn_output",
    "parse_yeti_status_output",
    "parse_world_march_capacity_output",
    "parse_world_monster_search_output",
    "parse_world_monster_search_sent_output",
    "parse_world_monster_status_output",
    "parse_world_monster_verify_output",
    "select_battle_target",
    "select_march_target",
    "script_sha256",
    "validate_role_whitelist",
]
