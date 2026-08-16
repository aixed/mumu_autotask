local EXPECTED_KINGDOM = 4549
local ALLOWED_ROLES = {
    ["打工人"] = true,
    ["打工魂"] = true,
    ["打工的"] = true,
    ["打工客"] = true,
    ["打工仔"] = true,
}

local TRACE_KEY = "__MUMU_AUTOTASK_RESCUE_TRACE"
local INSTALLED_KEY = "__MUMU_AUTOTASK_RESCUE_TRACE_INSTALLED"
local MAX_RECORDS = 300

local function fail(message)
    error("mumu-autotask rescue trace: " .. tostring(message), 0)
end

local function call(object, name)
    if type(object) ~= "table" or type(object[name]) ~= "function" then
        fail("missing method " .. tostring(name))
    end
    local ok, value = pcall(object[name], object)
    if not ok then
        fail("method failed " .. tostring(name))
    end
    return value
end

if type(GCtrl) ~= "table" or type(GCtrl.PlayerCtrl) ~= "table" then
    fail("PlayerCtrl unavailable")
end
local role = call(GCtrl.PlayerCtrl, "GetPlayerName")
local kid = call(GCtrl.PlayerCtrl, "GetPlayerKid")
local server = call(GCtrl.PlayerCtrl, "GetPlayerServerId")
if ALLOWED_ROLES[role] ~= true then
    fail("active role is not whitelisted: " .. tostring(role))
end
if kid ~= EXPECTED_KINGDOM or server ~= EXPECTED_KINGDOM then
    fail("active server is not 4549")
end

local function safe_tostring(value)
    local ok, text = pcall(tostring, value)
    if not ok then
        return "<tostring failed>"
    end
    text = text:gsub("[\r\n\t]", " ")
    if #text > 180 then
        text = text:sub(1, 180) .. "...<truncated>"
    end
    return text
end

local function table_keys(tbl)
    local keys = {}
    for key, _ in pairs(tbl) do
        keys[#keys + 1] = key
        if #keys >= 40 then
            break
        end
    end
    table.sort(keys, function(left, right)
        return safe_tostring(left) < safe_tostring(right)
    end)
    return keys
end

local function add_value(lines, prefix, value, depth, seen)
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
        seen[value] = nil
        return
    end
    for _, key in ipairs(table_keys(value)) do
        local child = value[key]
        local child_type = type(child)
        if child_type ~= "function" and child_type ~= "userdata" then
            add_value(
                lines,
                prefix .. "." .. safe_tostring(key),
                child,
                depth - 1,
                seen
            )
        end
    end
    seen[value] = nil
end

local function trace(label, argument_count, ...)
    local records = rawget(_G, TRACE_KEY)
    if type(records) ~= "table" then
        records = {}
        rawset(_G, TRACE_KEY, records)
    end
    if #records >= MAX_RECORDS then
        return
    end
    local lines = {
        table.concat({
            "TRACE",
            label,
            "role=" .. safe_tostring(role),
            "kid=" .. tostring(kid),
            "server=" .. tostring(server),
            "argc=" .. tostring(argument_count),
        }, "\t"),
    }
    local start_index = 1
    if label:find("Ctrl.", 1, true) or label:find("UIModule.", 1, true) then
        lines[#lines + 1] = "SELF_SKIPPED\t1"
        start_index = 2
    end
    for index = start_index, math.min(argument_count, start_index + 5) do
        add_value(lines, "arg" .. tostring(index), select(index, ...), 2, {})
    end
    records[#records + 1] = table.concat(lines, "\n")
end

local function restore_existing()
    local installed = rawget(_G, INSTALLED_KEY)
    local restored = 0
    if type(installed) == "table" then
        for _, item in ipairs(installed) do
            if type(item.owner) == "table" and item.owner[item.key] == item.wrapper then
                item.owner[item.key] = item.original
                restored = restored + 1
            end
        end
    end
    rawset(_G, INSTALLED_KEY, {})
    return restored
end

local function install(owner, key, label)
    if type(owner) ~= "table" or type(owner[key]) ~= "function" then
        return false
    end
    local original = owner[key]
    local wrapper = function(...)
        pcall(trace, label, select("#", ...), ...)
        return original(...)
    end
    owner[key] = wrapper
    local installed = rawget(_G, INSTALLED_KEY)
    installed[#installed + 1] = {
        owner = owner,
        key = key,
        label = label,
        original = original,
        wrapper = wrapper,
    }
    return true
end

local restored = restore_existing()
rawset(_G, TRACE_KEY, {})

local hooked = {}
local function hook_named(owner, label, names)
    local count = 0
    for _, key in ipairs(names) do
        if install(owner, key, label .. "." .. key) then
            count = count + 1
        end
    end
    hooked[#hooked + 1] = label .. "=" .. tostring(count)
end

if type(NetMsg) == "table" then
    hook_named(NetMsg, "NetMsg", { "SendMsg" })
end
if type(GCtrl) == "table" and type(GCtrl.RadarCtrl) == "table" then
    local names = {
        "RequestStartBattle",
        "RequestEndBattle",
        "ReqCancelBattle",
        "RequestReceiveQuestReward",
        "RequestReceiveAllQuestReward",
        "RequestRefresh",
        "RequestQuest",
        "RequestRadar",
    }
    hook_named(GCtrl.RadarCtrl, "RadarCtrl", names)
    hook_named(GCtrl.RadarCtrl.class, "RadarCtrl.class", names)
end
if type(GModule) == "table" and type(GModule.UIModule) == "table" then
    hook_named(GModule.UIModule, "UIModule", { "OpenView", "CloseView" })
end

return table.concat({
    "MUMU_AUTOTASK_RESCUE_TRACE_HOOK\t1",
    "ROLE\t" .. safe_tostring(role),
    "KINGDOM\t" .. tostring(server),
    "RESTORED\t" .. tostring(restored),
    "HOOKED\t" .. table.concat(hooked, ","),
    "END\t1",
}, "\n")
