local state = _G.__MUMU_AUTOTASK_WORLD_MONSTER_SEARCH
if type(state) ~= "table" then
    return "STATE\tmissing"
end

local kingdom = GCtrl.PlayerCtrl:GetPlayerKid()
local x = state.world_x
local y = state.world_y
local lines = {
    "LEVEL\t" .. tostring(state.level),
    "VIEW\t" .. tostring(state.view_id),
    "POINT\t" .. tostring(x) .. "\t" .. tostring(y),
    "REQUESTED\t" .. tostring(state.map_object_requested),
}
if type(x) == "number" and type(y) == "number" then
    local data = GCtrl.WorldMapCtrl:GetMapDataDic(kingdom)
    local keys = {
        x * 10000 + y,
        y * 10000 + x,
        tostring(x * 10000 + y),
        tostring(y * 10000 + x),
    }
    for index, key in ipairs(keys) do
        local object = type(data) == "table" and data[key] or nil
        lines[#lines + 1] = table.concat({
            "CELL",
            tostring(index),
            tostring(key),
            type(object),
            tostring(object),
        }, "\t")
    end
end
return table.concat(lines, "\n")
