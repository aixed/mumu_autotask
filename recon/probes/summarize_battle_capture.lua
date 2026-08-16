local captures = rawget(_G, "__MUMU_AUTOTASK_BATTLE_CAPTURE_TEXTS")
local out = {
    "MUMU_AUTOTASK_BATTLE_CAPTURE_SUMMARY\t1",
    "COUNT\t" .. tostring(type(captures) == "table" and #captures or 0),
}
if type(captures) ~= "table" then
    out[#out + 1] = "END\t1"
    return table.concat(out, "\n")
end

local wanted_exact = {
    ["arg1"] = true,
    ["arg2"] = true,
    ["arg3"] = true,
    ["arg4"] = true,
    ["arg5"] = true,
    ["arg2.id"] = true,
    ["arg2.fight_heros_data"] = true,
    ["arg2.fight_heros_data.source"] = true,
    ["arg2.fight_heros_data.fight_heros"] = true,
    ["arg2.extraData"] = true,
    ["arg2.otherData"] = true,
    ["arg2.extraData._id"] = true,
    ["arg2.extraData._questId"] = true,
    ["arg2.extraData._status"] = true,
    ["arg2.extraData._worldX"] = true,
    ["arg2.extraData._worldY"] = true,
    ["arg2.extraData._expireTime"] = true,
    ["arg2.extraData._questConfig.type"] = true,
    ["arg2.extraData._questConfig.quality_type"] = true,
    ["arg2.extraData._questConfig.quality_desc"] = true,
    ["arg2.extraData._questConfig.condition"] = true,
    ["arg2.extraData._questConfig.stamtina_expend"] = true,
    ["arg2.extraData._questConfig.power_level"] = true,
    ["arg2.extraData._questConfig.name"] = true,
    ["arg2.extraData._questConfig.situation_map"] = true,
    ["arg2.extraData._questConfig.icon"] = true,
    ["arg4._id"] = true,
    ["arg4._questId"] = true,
    ["arg4._status"] = true,
    ["arg4._worldX"] = true,
    ["arg4._worldY"] = true,
    ["arg4._expireTime"] = true,
    ["arg4._questConfig.type"] = true,
    ["arg4._questConfig.quality_type"] = true,
    ["arg4._questConfig.quality_desc"] = true,
    ["arg4._questConfig.condition"] = true,
    ["arg4._questConfig.stamtina_expend"] = true,
    ["arg4._questConfig.power_level"] = true,
    ["arg4._questConfig.name"] = true,
    ["arg4._questConfig.situation_map"] = true,
    ["arg4._questConfig.icon"] = true,
}

local wanted_prefix = {
    "arg3.",
    "arg2.fight_heros_data.fight_heros.",
}

local function keep_path(path)
    if wanted_exact[path] then
        return true
    end
    for _, prefix in ipairs(wanted_prefix) do
        if path:sub(1, #prefix) == prefix then
            local rest = path:sub(#prefix + 1)
            local dot_count = 0
            for _ in rest:gmatch("%.") do
                dot_count = dot_count + 1
            end
            return dot_count <= 1
        end
    end
    return false
end

local function capture_label(text)
    local first = text:match("([^\n]+)")
    if first == nil then
        return ""
    end
    return first
end

for index, text in ipairs(captures) do
    out[#out + 1] = "CAPTURE_INDEX\t" .. tostring(index)
    out[#out + 1] = capture_label(text)
    for line in tostring(text):gmatch("[^\n]+") do
        local prefix = line:match("^VALUE\t([^\t]+)\t")
        if prefix ~= nil and keep_path(prefix) then
            out[#out + 1] = line
        end
    end
end
out[#out + 1] = "END\t1"
return table.concat(out, "\n"):sub(1, 15000)
