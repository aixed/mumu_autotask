local EXPECTED_KINGDOM = 4549
local ALLOWED_ROLES = {
    ["打工人"] = true,
    ["打工魂"] = true,
    ["打工的"] = true,
    ["打工客"] = true,
    ["打工仔"] = true,
}

local TRACE_KEY = "__MUMU_AUTOTASK_RESCUE_TRACE_SLIM"
local INSTALLED_KEY = "__MUMU_AUTOTASK_RESCUE_TRACE_SLIM_INSTALLED"
local LEGACY_INSTALLED_KEY = "__MUMU_AUTOTASK_RESCUE_TRACE_INSTALLED"
local MAX_RECORDS = 120
local RESCUE_VIEW_ID = 240

local function fail(message)
    error("mumu-autotask rescue slim trace: " .. tostring(message), 0)
end

local function text(value)
    local ok, raw = pcall(tostring, value)
    if not ok then
        raw = "<tostring failed>"
    end
    raw = raw:gsub("[\r\n\t]", " ")
    if #raw > 96 then
        raw = raw:sub(1, 96) .. "...<truncated>"
    end
    return raw
end

local function scalar(value)
    local kind = type(value)
    if kind == "number" or kind == "boolean" or kind == "string" then
        return text(value)
    end
    return ""
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

local function field(object, name)
    if type(object) ~= "table" then
        return nil
    end
    local ok, value = pcall(function()
        return object[name]
    end)
    if ok then
        return value
    end
    return nil
end

local function record(...)
    local records = rawget(_G, TRACE_KEY)
    if type(records) ~= "table" then
        records = {}
        rawset(_G, TRACE_KEY, records)
    end
    if #records >= MAX_RECORDS then
        return
    end
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = text(select(index, ...))
    end
    records[#records + 1] = table.concat(parts, "\t")
end

local function append_scalar_fields(out, prefix, value, depth, seen)
    local kind = type(value)
    if kind ~= "table" then
        out[#out + 1] = prefix .. "=" .. text(value)
        return
    end
    if seen[value] then
        out[#out + 1] = prefix .. "=<cycle>"
        return
    end
    if depth <= 0 then
        out[#out + 1] = prefix .. "=" .. text(value)
        return
    end
    seen[value] = true
    local keys = {}
    for key, child in pairs(value) do
        local child_kind = type(child)
        if child_kind == "number"
            or child_kind == "boolean"
            or child_kind == "string"
            or child_kind == "table" then
            keys[#keys + 1] = key
            if #keys >= 40 then
                break
            end
        end
    end
    table.sort(keys, function(left, right)
        return text(left) < text(right)
    end)
    for _, key in ipairs(keys) do
        local child = value[key]
        local child_kind = type(child)
        if child_kind == "number" or child_kind == "boolean" or child_kind == "string" then
            out[#out + 1] = prefix .. "." .. text(key) .. "=" .. text(child)
        elseif child_kind == "table" then
            append_scalar_fields(out, prefix .. "." .. text(key), child, depth - 1, seen)
        end
        if #out >= 80 then
            break
        end
    end
    seen[value] = nil
end

local function record_payload(label, payload, depth)
    local parts = { label }
    append_scalar_fields(parts, "payload", payload, depth, {})
    local current = {}
    local budget = 0
    for _, part in ipairs(parts) do
        local part_text = text(part)
        if budget + #part_text > 850 then
            if #current > 0 then
                record(unpack(current))
            end
            current = {}
            budget = 0
        end
        current[#current + 1] = part_text
        budget = budget + #part_text + 1
    end
    if #current > 0 then
        record(unpack(current))
    end
end

local function restore_key(key)
    local installed = rawget(_G, key)
    local restored = 0
    if type(installed) == "table" then
        for _, item in ipairs(installed) do
            if type(item.owner) == "table" and item.owner[item.key] == item.wrapper then
                item.owner[item.key] = item.original
                restored = restored + 1
            end
        end
    end
    rawset(_G, key, {})
    return restored
end

local player = assert(GCtrl and GCtrl.PlayerCtrl, "PlayerCtrl unavailable")
local role = call(player, "GetPlayerName")
local kid = call(player, "GetPlayerKid")
local server = call(player, "GetPlayerServerId")
if ALLOWED_ROLES[role] ~= true then
    fail("active role is not whitelisted: " .. tostring(role))
end
if kid ~= EXPECTED_KINGDOM or server ~= EXPECTED_KINGDOM then
    fail("active server is not 4549")
end

local restored = restore_key(INSTALLED_KEY) + restore_key(LEGACY_INSTALLED_KEY)
rawset(_G, TRACE_KEY, {})
local installed = rawget(_G, INSTALLED_KEY)
if type(installed) ~= "table" then
    installed = {}
    rawset(_G, INSTALLED_KEY, installed)
end
local hooked_labels = {}

local function install(owner, key, label, recorder)
    if type(owner) ~= "table" or type(owner[key]) ~= "function" then
        return false
    end
    local original = owner[key]
    for _, item in ipairs(installed) do
        if item.owner == owner and item.key == key then
            return false
        end
    end
    local wrapper = function(...)
        pcall(recorder, label, select("#", ...), ...)
        return original(...)
    end
    owner[key] = wrapper
    installed[#installed + 1] = {
        owner = owner,
        key = key,
        label = label,
        original = original,
        wrapper = wrapper,
    }
    hooked_labels[#hooked_labels + 1] = label
    return true
end

local function describe_quest(prefix, quest)
    if type(quest) ~= "table" then
        record(prefix, "quest_type", type(quest), "quest", quest)
        return
    end
    local config = field(quest, "_questConfig") or {}
    record(
        prefix,
        "runtime", field(quest, "_id"),
        "quest", field(quest, "_questId"),
        "status", field(quest, "_status"),
        "world", field(quest, "_worldX"), field(quest, "_worldY"),
        "type", field(config, "type"),
        "quality", field(config, "quality_type"),
        "power", field(config, "power_level"),
        "stamina", field(config, "stamtina_expend"),
        "condition", field(config, "condition"),
        "name", field(config, "name"),
        "class", field(field(quest, "class"), "__cname")
    )
end

local function should_hook_view_method(name)
    local lower = tostring(name):lower()
    if lower:find("update", 1, true) ~= nil then
        return false
    end
    return lower:find("click", 1, true) ~= nil
        or lower:find("btn", 1, true) ~= nil
        or lower:find("execute", 1, true) ~= nil
        or lower:find("rescue", 1, true) ~= nil
        or lower:find("battle", 1, true) ~= nil
        or lower:find("start", 1, true) ~= nil
        or lower:find("go", 1, true) ~= nil
        or lower:find("reward", 1, true) ~= nil
        or lower:find("quest", 1, true) ~= nil
        or lower:find("formation", 1, true) ~= nil
end

local function view_method_recorder(label, argc, ...)
    local arg2 = select(2, ...)
    local arg3 = select(3, ...)
    record("VIEW240_CALL", label, "argc", argc, "arg2", scalar(arg2), "arg3", scalar(arg3))
end

local function hook_view_methods(view)
    if type(view) ~= "table" then
        record("VIEW240", "missing_view", type(view), text(view))
        return
    end
    local count = 0
    local names = {}
    local function inspect_owner(owner, owner_label)
        if type(owner) ~= "table" then
            return
        end
        for key, value in pairs(owner) do
            if type(key) == "string" and type(value) == "function" and should_hook_view_method(key) then
                names[#names + 1] = owner_label .. "." .. key
                if install(owner, key, owner_label .. "." .. key, view_method_recorder) then
                    count = count + 1
                end
                if #names >= 48 then
                    break
                end
            end
        end
    end
    inspect_owner(view, "view")
    inspect_owner(field(view, "class"), "class")
    table.sort(names)
    record("VIEW240_METHODS", "hooked", count, "candidate_count", #names)
    for _, name in ipairs(names) do
        record("VIEW240_METHOD", name)
    end
end

local function netmsg_recorder(label, argc, ...)
    local name = select(1, ...)
    if type(name) ~= "string" then
        return
    end
    if name == "req_heartbeat" then
        return
    end
    if not name:find("req_", 1, true) then
        return
    end
    local payload = select(2, ...)
    local arg3 = select(3, ...)
    if name == "req_world_map_info" or name == "req_world_march" then
        record("NET_DEEP", name, "argc", argc, "arg3", scalar(arg3))
        record_payload("NET_PAYLOAD\t" .. name, payload, 2)
        return
    end
    if type(payload) == "table" then
        record(
            "NET",
            name,
            "argc", argc,
            "arg3", scalar(arg3),
            "id", field(payload, "id"),
            "sid", field(payload, "sid"),
            "qid", field(payload, "qid"),
            "quest_id", field(payload, "quest_id"),
            "target", field(payload, "target_id")
        )
    else
        record("NET", name, "argc", argc, "payload", scalar(payload))
    end
end

local function radar_recorder(label, argc, ...)
    record("RADAR", label, "argc", argc, "arg2", scalar(select(2, ...)))
end

local function ui_recorder(label, argc, ...)
    local view_id = select(2, ...)
    if label == "UIModule.OpenView" then
        record("OPEN", view_id, "argc", argc)
        if view_id == RESCUE_VIEW_ID then
            describe_quest("OPEN240_ARG", select(3, ...))
        end
    elseif label == "UIModule.CloseView" then
        record("CLOSE", view_id, "argc", argc)
    end
end

local original_open_view = type(GModule) == "table"
    and type(GModule.UIModule) == "table"
    and GModule.UIModule.OpenView
    or nil

if type(NetMsg) == "table" then
    install(NetMsg, "SendMsg", "NetMsg.SendMsg", netmsg_recorder)
end
if type(GCtrl) == "table" and type(GCtrl.RadarCtrl) == "table" then
    for _, key in ipairs({
        "RequestStartBattle",
        "RequestEndBattle",
        "RequestReceiveQuestReward",
        "RequestReceiveAllQuestReward",
        "RequestRefresh",
        "RequestQuest",
        "RequestRadar",
    }) do
        install(GCtrl.RadarCtrl, key, "RadarCtrl." .. key, radar_recorder)
        install(GCtrl.RadarCtrl.class, key, "RadarCtrl.class." .. key, radar_recorder)
    end
end
if original_open_view ~= nil then
    local function open_recorder(label, argc, ...)
        ui_recorder(label, argc, ...)
    end
    local function close_recorder(label, argc, ...)
        ui_recorder(label, argc, ...)
    end
    install(GModule.UIModule, "CloseView", "UIModule.CloseView", close_recorder)
    local original = GModule.UIModule.OpenView
    local unpack_fn = table.unpack or unpack
    local wrapper = function(...)
        pcall(open_recorder, "UIModule.OpenView", select("#", ...), ...)
        local results = { original(...) }
        local view_id = select(2, ...)
        if view_id == RESCUE_VIEW_ID then
            pcall(function()
                local view = nil
                if type(GModule.UIModule.FindOpenedView) == "function" then
                    view = GModule.UIModule:FindOpenedView(RESCUE_VIEW_ID)
                end
                hook_view_methods(view)
            end)
        end
        return unpack_fn(results)
    end
    GModule.UIModule.OpenView = wrapper
    installed[#installed + 1] = {
        owner = GModule.UIModule,
        key = "OpenView",
        label = "UIModule.OpenView",
        original = original,
        wrapper = wrapper,
    }
    hooked_labels[#hooked_labels + 1] = "UIModule.OpenView"
end

record("HOOK_READY", "role", role, "kid", kid, "server", server, "restored", restored)

return table.concat({
    "MUMU_AUTOTASK_RESCUE_TRACE_SLIM_HOOK\t1",
    "ROLE\t" .. text(role),
    "KINGDOM\t" .. tostring(server),
    "RESTORED\t" .. tostring(restored),
    "HOOKED\t" .. table.concat(hooked_labels, ","),
    "END\t1",
}, "\n")
