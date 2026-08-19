local state = _G.__MUMU_AUTOTASK_MAPOBJ_CAPTURE
if type(state) ~= "table" then
    return "STATE\tmissing"
end
local lines = {
    "POINT\t" .. tostring(state.point and state.point.x)
        .. "\t" .. tostring(state.point and state.point.y),
    "MAPOBJ\t" .. type(state.mapobj) .. "\t" .. tostring(state.mapobj),
    "CALLED\t" .. tostring(state.map_called),
    "ARG1\t" .. type(state.map_arg1) .. "\t" .. tostring(state.map_arg1),
    "ARG2\t" .. type(state.map_arg2) .. "\t" .. tostring(state.map_arg2),
    "ARG3\t" .. type(state.map_arg3) .. "\t" .. tostring(state.map_arg3),
}
local function dump(path, value, depth, seen)
    if type(value) ~= "table" or depth < 0 or seen[value] then return end
    seen[value] = true
    for key, item in pairs(value) do
        local item_path = path .. "." .. tostring(key)
        lines[#lines + 1] = table.concat({
            item_path,
            type(item),
            tostring(item),
        }, "\t")
        if type(item) == "table" then
            dump(item_path, item, depth - 1, seen)
        end
        if #lines >= 240 then return end
    end
end
dump("mapobj", state.mapobj, 4, {})
pcall(GameMsg.RemoveMessageByTarget, state)
_G.__MUMU_AUTOTASK_MAPOBJ_CAPTURE = nil
return table.concat(lines, "\n"):sub(1, 15000)
