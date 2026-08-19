local lines = {}
for key, value in pairs(GCtrl.WorldMapCtrl.class or {}) do
    local name = tostring(key)
    local lower = string.lower(name)
    if type(value) == "function" and (
        string.find(lower, "obj", 1, true)
        or string.find(lower, "map", 1, true)
        or string.find(lower, "grid", 1, true)
        or string.find(lower, "pos", 1, true)
    ) then
        lines[#lines + 1] = name .. "\t" .. tostring(value)
    end
end
table.sort(lines)
return table.concat(lines, "\n")
