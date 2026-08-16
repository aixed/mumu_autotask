local EXPECTED_KINGDOM = 4549
local ALLOWED_ROLES = {
    ["打工人"] = true,
    ["打工魂"] = true,
    ["打工的"] = true,
    ["打工客"] = true,
    ["打工仔"] = true,
}

local function call(object, name)
    if type(object) ~= "table" or type(object[name]) ~= "function" then
        error("missing method " .. tostring(name), 0)
    end
    local ok, value = pcall(object[name], object)
    if not ok then
        error("method failed " .. tostring(name), 0)
    end
    return value
end

local role = call(GCtrl.PlayerCtrl, "GetPlayerName")
local kid = call(GCtrl.PlayerCtrl, "GetPlayerKid")
local server = call(GCtrl.PlayerCtrl, "GetPlayerServerId")
if ALLOWED_ROLES[role] ~= true then
    error("active role is not whitelisted: " .. tostring(role), 0)
end
if kid ~= EXPECTED_KINGDOM or server ~= EXPECTED_KINGDOM then
    error("active server is not 4549", 0)
end

local function safe_tostring(value)
    local ok, text = pcall(tostring, value)
    if ok then
        return text
    end
    return "<tostring failed>"
end

local function sorted_keys(tbl)
    local keys = {}
    for key, _ in pairs(tbl) do
        keys[#keys + 1] = key
    end
    table.sort(keys, function(left, right)
        local left_type = type(left)
        local right_type = type(right)
        if left_type == right_type then
            return safe_tostring(left) < safe_tostring(right)
        end
        return left_type < right_type
    end)
    return keys
end

local function emit_value(lines, prefix, value, depth, seen)
    local value_type = type(value)
    if value_type ~= "table" then
        lines[#lines + 1] = table.concat({
            "VALUE",
            prefix,
            value_type,
            safe_tostring(value),
        }, "\t")
        return
    end
    if seen[value] then
        lines[#lines + 1] = table.concat({
            "VALUE",
            prefix,
            "table",
            "<cycle>",
        }, "\t")
        return
    end
    seen[value] = true
    lines[#lines + 1] = table.concat({
        "VALUE",
        prefix,
        "table",
        safe_tostring(value),
    }, "\t")
    if depth <= 0 then
        lines[#lines + 1] = table.concat({
            "VALUE",
            prefix .. ".*",
            "truncated",
            "max-depth",
        }, "\t")
        seen[value] = nil
        return
    end
    for _, key in ipairs(sorted_keys(value)) do
        emit_value(
            lines,
            prefix .. "." .. safe_tostring(key),
            value[key],
            depth - 1,
            seen
        )
    end
    seen[value] = nil
end

local function should_capture(label, argument_count, ...)
    if label == "RadarCtrl.RequestStartBattle" then
        return true
    end
    if label == "NetMsg.SendMsg" then
        local message_name = select(1, ...)
        return type(message_name) == "string"
            and message_name:find("intelligence", 1, true) ~= nil
    end
    if label:find("RadarCtrl.", 1, true) == 1 then
        return true
    end
    return false
end

local function append_capture(label, argument_count, ...)
    if not should_capture(label, argument_count, ...) then
        return
    end
    local lines = {
        table.concat({
            "MUMU_AUTOTASK_BATTLE_CAPTURE",
            "1",
            label,
            "role=" .. role,
            "kid=" .. tostring(kid),
            "server=" .. tostring(server),
            "argc=" .. tostring(argument_count),
        }, "\t"),
    }
    local start_index = 1
    if label:find("RadarCtrl.", 1, true) == 1 then
        lines[#lines + 1] = "SELF_SKIPPED\t1"
        start_index = 2
    end
    for index = start_index, argument_count do
        emit_value(lines, "arg" .. tostring(index), select(index, ...), 7, {})
    end
    lines[#lines + 1] = "END_CAPTURE"
    local text = table.concat(lines, "\n")
    local captures = rawget(_G, "__MUMU_AUTOTASK_BATTLE_CAPTURE_TEXTS")
    if type(captures) ~= "table" then
        captures = {}
        rawset(_G, "__MUMU_AUTOTASK_BATTLE_CAPTURE_TEXTS", captures)
    end
    captures[#captures + 1] = text
    _G.__MUMU_AUTOTASK_BATTLE_CAPTURE_COUNT =
        (_G.__MUMU_AUTOTASK_BATTLE_CAPTURE_COUNT or 0) + 1
end

local function restore_previous(owner, key, label)
    local original_key = "__MUMU_AUTOTASK_ORIGINAL_" .. label
    local wrapper_key = "__MUMU_AUTOTASK_WRAPPER_" .. label
    local original = rawget(_G, original_key)
    local wrapper = rawget(_G, wrapper_key)
    if type(owner) == "table"
        and type(original) == "function"
        and owner[key] == wrapper then
        owner[key] = original
    end
    rawset(_G, original_key, nil)
    rawset(_G, wrapper_key, nil)
end

local function install(owner, key, label)
    if type(owner) ~= "table" or type(owner[key]) ~= "function" then
        return false
    end
    local original_key = "__MUMU_AUTOTASK_ORIGINAL_" .. label
    local wrapper_key = "__MUMU_AUTOTASK_WRAPPER_" .. label
    local original = rawget(_G, original_key)
    if type(original) ~= "function" then
        original = owner[key]
        rawset(_G, original_key, original)
    end
    local existing_wrapper = rawget(_G, wrapper_key)
    if owner[key] == existing_wrapper then
        return true
    end
    local wrapper = function(...)
        local argument_count = select("#", ...)
        pcall(append_capture, label, argument_count, ...)
        return original(...)
    end
    rawset(_G, wrapper_key, wrapper)
    owner[key] = wrapper
    return true
end

restore_previous(
    GCtrl.RadarCtrl,
    "RequestStartBattle",
    "RadarCtrl.RequestStartBattle"
)
restore_previous(
    GCtrl.RadarCtrl,
    "RequestEndBattle",
    "RadarCtrl.RequestEndBattle"
)
restore_previous(
    GCtrl.RadarCtrl,
    "ReqCancelBattle",
    "RadarCtrl.ReqCancelBattle"
)
restore_previous(
    GCtrl.RadarCtrl,
    "RequestReceiveQuestReward",
    "RadarCtrl.RequestReceiveQuestReward"
)
restore_previous(
    GCtrl.RadarCtrl,
    "RequestReceiveAllQuestReward",
    "RadarCtrl.RequestReceiveAllQuestReward"
)
if type(NetMsg) == "table" then
    restore_previous(NetMsg, "SendMsg", "NetMsg.SendMsg")
end

_G.__MUMU_AUTOTASK_BATTLE_CAPTURE_TEXTS = {}
_G.__MUMU_AUTOTASK_BATTLE_CAPTURE_COUNT = 0
local radar_hooked = install(
    GCtrl.RadarCtrl,
    "RequestStartBattle",
    "RadarCtrl.RequestStartBattle"
)
local radar_end_hooked = install(
    GCtrl.RadarCtrl,
    "RequestEndBattle",
    "RadarCtrl.RequestEndBattle"
)
local radar_cancel_hooked = install(
    GCtrl.RadarCtrl,
    "ReqCancelBattle",
    "RadarCtrl.ReqCancelBattle"
)
local radar_reward_hooked = install(
    GCtrl.RadarCtrl,
    "RequestReceiveQuestReward",
    "RadarCtrl.RequestReceiveQuestReward"
)
local radar_reward_all_hooked = install(
    GCtrl.RadarCtrl,
    "RequestReceiveAllQuestReward",
    "RadarCtrl.RequestReceiveAllQuestReward"
)
local net_hooked = false
if type(NetMsg) == "table" then
    net_hooked = install(NetMsg, "SendMsg", "NetMsg.SendMsg")
end

return table.concat({
    "MUMU_AUTOTASK_BATTLE_HOOK\t1",
    "ROLE\t" .. role,
    "KINGDOM\t" .. tostring(server),
    "RADAR\t" .. (radar_hooked and "1" or "0"),
    "RADAR_END\t" .. (radar_end_hooked and "1" or "0"),
    "RADAR_CANCEL\t" .. (radar_cancel_hooked and "1" or "0"),
    "RADAR_REWARD\t" .. (radar_reward_hooked and "1" or "0"),
    "RADAR_REWARD_ALL\t" .. (radar_reward_all_hooked and "1" or "0"),
    "NETMSG\t" .. (net_hooked and "1" or "0"),
    "END\t1",
}, "\n")
