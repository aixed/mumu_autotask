local function value_text(value)
    if value == nil then
        return "nil"
    end
    return tostring(value)
end

local function call_method(object, name)
    if object == nil or type(object[name]) ~= "function" then
        return nil, nil
    end
    local ok, first, second = pcall(object[name], object)
    if not ok then
        return "error", nil
    end
    return first, second
end

local kingdom = GCtrl.PlayerCtrl:GetPlayerKid()
local server = GCtrl.PlayerCtrl:GetPlayerServerId()
assert(kingdom == 4549 and server == 4549, "unexpected kingdom")

local marches = GCtrl.WorldMarchCtrl:GetSelfMarchMap(kingdom)
local lines = {
    "KINGDOM\t" .. value_text(kingdom),
    "COUNT\t" .. value_text(table.nums and table.nums(marches) or 0),
}

for key, march in pairs(marches) do
    local data = call_method(march, "GetData")
    local extra = call_method(march, "_GetExtraData")
    local end_x, end_y = call_method(march, "GetEndPos")
    local transaction = type(data) == "table" and data.transaction_slg or nil
    lines[#lines + 1] = table.concat({
        "MARCH",
        "key=" .. value_text(key),
        "id=" .. value_text(call_method(march, "GetId")),
        "server=" .. value_text(call_method(march, "GetServerId")),
        "map_type=" .. value_text(call_method(march, "GetMarchMapType")),
        "type=" .. value_text(call_method(march, "GetType")),
        "monster=" .. value_text(call_method(march, "GetTargetMapObjectId")),
        "level=" .. value_text(call_method(march, "GetLevel")),
        "end_x=" .. value_text(end_x),
        "end_y=" .. value_text(end_y),
        "event_data=" .. value_text(type(transaction) == "table" and transaction.event_id or nil),
        "event_extra=" .. value_text(type(extra) == "table" and extra.event_id or nil),
    }, "\t")
end

table.sort(lines)
return table.concat(lines, "\n")
