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

local function capture(label, argument_count, ...)
    local lines = {
        table.concat({
            "MUMU_AUTOTASK_CAPTURE",
            "1",
            label,
            "role=" .. role,
            "kid=" .. tostring(kid),
            "server=" .. tostring(server),
            "argc=" .. tostring(argument_count),
        }, "\t"),
    }
    for index = 1, argument_count do
        emit_value(lines, "arg" .. tostring(index), select(index, ...), 6, {})
    end
    lines[#lines + 1] = "END_CAPTURE"
    _G.__MUMU_AUTOTASK_MARCH_CAPTURE_COUNT =
        (_G.__MUMU_AUTOTASK_MARCH_CAPTURE_COUNT or 0) + 1
    _G.__MUMU_AUTOTASK_MARCH_CAPTURE_TEXT = table.concat(lines, "\n")
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
        pcall(capture, label, argument_count, ...)
        return original(...)
    end
    rawset(_G, wrapper_key, wrapper)
    owner[key] = wrapper
    return true
end

_G.__MUMU_AUTOTASK_MARCH_CAPTURE_TEXT = nil
_G.__MUMU_AUTOTASK_MARCH_CAPTURE_COUNT = 0
local helper_hooked = install(
    GHelper.WorldMarchHelper,
    "RequestMarchStartOff",
    "WorldMarchHelper.RequestMarchStartOff"
)
local ctrl_hooked = install(
    GCtrl.WorldMarchCtrl,
    "RequestWorldMarchStartOff",
    "WorldMarchCtrl.RequestWorldMarchStartOff"
)

return table.concat({
    "MUMU_AUTOTASK_HOOK\t1",
    "ROLE\t" .. role,
    "KINGDOM\t" .. tostring(server),
    "HELPER\t" .. (helper_hooked and "1" or "0"),
    "CTRL\t" .. (ctrl_hooked and "1" or "0"),
    "END\t1",
}, "\n")
