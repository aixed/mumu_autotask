local lines = {}
local value = GHelper.ExpeditionHelper.Check_Monster
lines[#lines + 1] = "Check_Monster_type=" .. type(value)
if type(value) == "table" then
    for key, item in pairs(value) do
        lines[#lines + 1] = "Check_Monster_entry=" .. tostring(key) .. ":" .. tostring(item) .. ":" .. type(item)
    end
end
return table.concat(lines, "\n")
