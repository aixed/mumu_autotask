local function scalar(value)
    local kind = type(value)
    if kind == "number" or kind == "boolean" then
        return tostring(value)
    end
    if kind == "string" then
        return (value:gsub("[\r\n\t]", " ")):sub(1, 120)
    end
    return nil
end

local lines = {}
local function call_scalar(object, method)
    if type(object[method]) ~= "function" then
        return ""
    end
    local ok, value = pcall(object[method], object)
    return ok and scalar(value) or ""
end

local player = assert(GCtrl and GCtrl.PlayerCtrl, "PlayerCtrl unavailable")
lines[#lines + 1] = table.concat({
    "PLAYER",
    scalar(player:GetPlayerName()) or "",
    scalar(player:GetPlayerKid()) or "",
    scalar(player:GetPlayerServerId()) or "",
}, "\t")

local radar = assert(GCtrl.RadarCtrl, "RadarCtrl unavailable")
for runtime_id, quest in pairs(radar:GetQuestDataMap()) do
    local fields = {
        "QUEST",
        scalar(runtime_id) or "",
        scalar(quest._questId) or "",
        scalar(quest._status) or "",
        scalar(quest._worldX) or "",
        scalar(quest._worldY) or "",
        scalar(quest._expireTime) or "",
        "type=" .. call_scalar(quest, "GetQuestType"),
        "quality=" .. call_scalar(quest, "GetQuality"),
        "monster=" .. call_scalar(quest, "GetMonsterId"),
        "level=" .. call_scalar(quest, "GetLevel"),
        "completed=" .. call_scalar(quest, "IsCompleted"),
        "atk_res_time=" .. call_scalar(quest, "GetAtkResTime"),
    }
    local config_fields = {}
    for key, value in pairs(quest._questConfig or {}) do
        local encoded = scalar(value)
        if encoded ~= nil then
            config_fields[#config_fields + 1] = tostring(key) .. "=" .. encoded
        end
    end
    table.sort(config_fields)
    fields[#fields + 1] = table.concat(config_fields, ";")
    lines[#lines + 1] = table.concat(fields, "\t")
end
table.sort(lines)
return table.concat(lines, "\n"):sub(1, 15000)
