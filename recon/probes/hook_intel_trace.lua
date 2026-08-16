local EXPECTED_KINGDOM = 4549
local ALLOWED_ROLES = {
    ["打工人"] = true,
    ["打工魂"] = true,
    ["打工的"] = true,
    ["打工客"] = true,
    ["打工仔"] = true,
}
local TRACE_KEY = "__MUMU_AUTOTASK_INTEL_TRACE_TEXTS"
local COUNT_KEY = "__MUMU_AUTOTASK_INTEL_TRACE_COUNT"
local INSTALLED_KEY = "__MUMU_AUTOTASK_INTEL_TRACE_INSTALLED"
local MAX_RECORDS = 500

local function fail(message)
    error("mumu-autotask trace: " .. tostring(message), 0)
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
    if ok then
        text = text:gsub("[\r\n\t]", " ")
        if #text > 240 then
            text = text:sub(1, 240) .. "...<truncated>"
        end
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
    local emitted = 0
    for _, key in ipairs(sorted_keys(value)) do
        emitted = emitted + 1
        if emitted > 80 then
            lines[#lines + 1] = table.concat({
                "VALUE",
                prefix .. ".*",
                "truncated",
                "max-keys",
            }, "\t")
            break
        end
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

local function append_trace(label, argument_count, ...)
    local captures = rawget(_G, TRACE_KEY)
    if type(captures) ~= "table" then
        captures = {}
        rawset(_G, TRACE_KEY, captures)
    end
    if #captures >= MAX_RECORDS then
        return
    end
    local lines = {
        table.concat({
            "MUMU_AUTOTASK_INTEL_TRACE",
            "1",
            label,
            "role=" .. tostring(role),
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
    for index = start_index, argument_count do
        emit_value(lines, "arg" .. tostring(index), select(index, ...), 5, {})
    end
    lines[#lines + 1] = "END_TRACE"
    captures[#captures + 1] = table.concat(lines, "\n")
    rawset(_G, COUNT_KEY, (rawget(_G, COUNT_KEY) or 0) + 1)
end

local function restore_all()
    local installed = rawget(_G, INSTALLED_KEY)
    if type(installed) ~= "table" then
        return 0
    end
    local restored = 0
    for _, item in ipairs(installed) do
        local owner = item.owner
        local key = item.key
        if type(owner) == "table" and owner[key] == item.wrapper then
            owner[key] = item.original
            restored = restored + 1
        end
    end
    rawset(_G, INSTALLED_KEY, nil)
    return restored
end

local function install(owner, key, label)
    if type(owner) ~= "table" or type(owner[key]) ~= "function" then
        return false
    end
    local original = owner[key]
    local wrapper = function(...)
        local argument_count = select("#", ...)
        pcall(append_trace, label, argument_count, ...)
        return original(...)
    end
    owner[key] = wrapper
    local installed = rawget(_G, INSTALLED_KEY)
    if type(installed) ~= "table" then
        installed = {}
        rawset(_G, INSTALLED_KEY, installed)
    end
    installed[#installed + 1] = {
        owner = owner,
        key = key,
        label = label,
        original = original,
        wrapper = wrapper,
    }
    return true
end

local function should_hook_method(name)
    return name:find("Request", 1, true) ~= nil
        or name:find("Req", 1, true) ~= nil
        or name:find("Receive", 1, true) ~= nil
        or name:find("Battle", 1, true) ~= nil
        or name:find("Quest", 1, true) ~= nil
        or name:find("Radar", 1, true) ~= nil
end

local function install_methods(owner, label)
    local count = 0
    if type(owner) ~= "table" then
        return count
    end
    local names = {}
    for key, value in pairs(owner) do
        if type(key) == "string" and type(value) == "function" and should_hook_method(key) then
            names[#names + 1] = key
        end
    end
    table.sort(names)
    for _, key in ipairs(names) do
        if install(owner, key, label .. "." .. key) then
            count = count + 1
        end
    end
    return count
end

local restored = restore_all()
rawset(_G, TRACE_KEY, {})
rawset(_G, COUNT_KEY, 0)

local radar_count = 0
if type(GCtrl) == "table" and type(GCtrl.RadarCtrl) == "table" then
    radar_count = radar_count + install_methods(GCtrl.RadarCtrl, "RadarCtrl")
    radar_count = radar_count + install_methods(GCtrl.RadarCtrl.class, "RadarCtrl.class")
end

local net_hooked = false
if type(NetMsg) == "table" and type(NetMsg.SendMsg) == "function" then
    net_hooked = install(NetMsg, "SendMsg", "NetMsg.SendMsg")
end

local ui_hooked = false
if type(GModule) == "table"
    and type(GModule.UIModule) == "table"
    and type(GModule.UIModule.OpenView) == "function" then
    ui_hooked = install(GModule.UIModule, "OpenView", "UIModule.OpenView")
end

return table.concat({
    "MUMU_AUTOTASK_INTEL_TRACE_HOOK\t1",
    "ROLE\t" .. tostring(role),
    "KINGDOM\t" .. tostring(server),
    "RESTORED\t" .. tostring(restored),
    "RADAR_METHODS\t" .. tostring(radar_count),
    "NETMSG\t" .. (net_hooked and "1" or "0"),
    "UI_OPEN_VIEW\t" .. (ui_hooked and "1" or "0"),
    "END\t1",
}, "\n")
