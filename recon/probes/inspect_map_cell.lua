local x, y = 782, 706
local dic = GCtrl.WorldMapCtrl:GetMapDataDic(4549)
local cell = dic[x * 10000 + y]
local lines = {"CELL\t" .. type(cell) .. "\t" .. tostring(cell)}
local function dump(label, value, depth, seen)
    if type(value) ~= "table" or seen[value] or depth < 0 then return end
    seen[value] = true
    for key, item in pairs(value) do
        local path = label .. "." .. tostring(key)
        lines[#lines + 1] = table.concat({path, type(item), tostring(item)}, "\t")
        if type(item) == "table" and depth > 0 then dump(path, item, depth - 1, seen) end
        if #lines > 300 then break end
    end
end
dump("cell", cell, 2, {})
return table.concat(lines, "\n"):sub(1, 15000)
