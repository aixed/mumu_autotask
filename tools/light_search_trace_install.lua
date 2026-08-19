local KEY = "__MUMU_AUTOTASK_LIGHT_SEARCH_TRACE"
local existing = _G[KEY]
if type(existing) == "table" and existing.installed == true then
    return "LIGHT_SEARCH_TRACE\tALREADY_INSTALLED\t" .. tostring(#existing.records)
end

local trace = { installed = true, originals = {}, records = {}, sequence = 0 }
_G[KEY] = trace

local function scalar(value)
    local value_type = type(value)
    if value_type == "nil" then return "nil" end
    if value_type == "boolean" or value_type == "number" then
        return value_type .. ":" .. tostring(value)
    end
    if value_type == "string" then
        local text = value:gsub("[\r\n\t]", " ")
        return "string:" .. text:sub(1, 96)
    end
    if value_type == "table" then
        local x, y = rawget(value, "x"), rawget(value, "y")
        if type(x) == "number" or type(y) == "number" then
            return "table:point(" .. tostring(x) .. "," .. tostring(y) .. ")"
        end
    end
    return value_type
end

local function record(name, ...)
    local current = _G[KEY]
    if type(current) ~= "table" or type(current.records) ~= "table" then return end
    current.sequence = current.sequence + 1
    local fields = { tostring(current.sequence), name, tostring(select("#", ...)) }
    for index = 1, select("#", ...) do
        fields[#fields + 1] = tostring(index) .. "=" .. scalar(select(index, ...))
    end
    current.records[#current.records + 1] = table.concat(fields, "\t")
    while #current.records > 32 do table.remove(current.records, 1) end
end

local function wrap(owner, method_name, event_name)
    if type(owner) ~= "table" or type(owner[method_name]) ~= "function" then
        return event_name .. ":missing"
    end
    local original = owner[method_name]
    local wrapper = function(...)
        pcall(record, event_name, ...)
        return original(...)
    end
    trace.originals[event_name] = {
        owner = owner,
        method_name = method_name,
        original = original,
        wrapper = wrapper,
    }
    owner[method_name] = wrapper
    return event_name .. ":wrapped"
end

local results = {
    wrap(GCtrl and GCtrl.WorldPlayerCtrl, "ReqWorldMapSearch", "ReqWorldMapSearch"),
    wrap(GCtrl and GCtrl.WorldPlayerCtrl, "OnReqWorldSearch", "OnReqWorldSearch"),
    wrap(GHelper and GHelper.WorldHelper, "SearchToMapObj", "SearchToMapObj"),
}
return "LIGHT_SEARCH_TRACE\tINSTALLED\t" .. table.concat(results, "\t")
