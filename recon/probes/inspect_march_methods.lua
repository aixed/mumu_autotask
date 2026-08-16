local groups = {
    {"MARCH", assert(GCtrl.WorldMarchCtrl.class, "WorldMarchCtrl class unavailable")},
}

local lines = {}
for _, group in ipairs(groups) do
    for key, value in pairs(group[2]) do
        if type(value) == "function" then
            lines[#lines + 1] = group[1] .. "\t" .. tostring(key)
        end
    end
end
table.sort(lines)
return table.concat(lines, "\n")
