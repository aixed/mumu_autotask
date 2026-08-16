local function to_hex(value)
    return (value:gsub(".", function(char)
        return string.format("%02x", string.byte(char))
    end))
end

local targets = {
    {"RequestStartBattle", GCtrl.RadarCtrl.RequestStartBattle},
    {"RequestEndBattle", GCtrl.RadarCtrl.RequestEndBattle},
    {"ReqCancelBattle", GCtrl.RadarCtrl.ReqCancelBattle},
    {"RequestReceiveQuestReward", GCtrl.RadarCtrl.RequestReceiveQuestReward},
    {"RequestReceiveAllQuestReward", GCtrl.RadarCtrl.RequestReceiveAllQuestReward},
}

local lines = {}
for _, target in ipairs(targets) do
    local name, fn = target[1], target[2]
    if type(fn) == "function" then
        lines[#lines + 1] = name .. "\t" .. to_hex(string.dump(fn))
    else
        lines[#lines + 1] = name .. "\tMISSING"
    end
end
return table.concat(lines, "\n")
