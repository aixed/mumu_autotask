local groups = {
    {"CTRL", assert(GCtrl.RadarCtrl.class, "RadarCtrl class unavailable")},
}
for _, quest in pairs(GCtrl.RadarCtrl:GetQuestDataMap()) do
    groups[#groups + 1] = {"QUEST", assert(quest.class, "quest class unavailable")}
    break
end

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
