local level = 16
local lines = {}

local search_helper = package.loaded["game.helper.WorldMapSearchHelper"]
    or package.loaded["game.helper.WorldSearchHelper"]
local config = nil
if type(search_helper) == "table" and type(search_helper.GetMapSearchConfig) == "function" then
    config = search_helper.GetMapSearchConfig(1)
else
    for name, value in pairs(package.loaded) do
        if type(value) == "table" and type(value.GetMapSearchConfig) == "function" then
            lines[#lines + 1] = "CONFIG_OWNER\t" .. tostring(name)
            search_helper = value
            config = value.GetMapSearchConfig(1)
            break
        end
    end
end
lines[#lines + 1] = "CONFIG\t" .. type(config) .. "\t" .. tostring(config)
if type(config) == "table" then
    local keys = {}
    for key, _ in pairs(config) do
        keys[#keys + 1] = key
    end
    table.sort(keys, function(left, right) return tostring(left) < tostring(right) end)
    for _, key in ipairs(keys) do
        local value = config[key]
        if type(value) ~= "table" then
            lines[#lines + 1] = table.concat({
                "FIELD", tostring(key), type(value), tostring(value)
            }, "\t")
        end
    end
end

local map_config = package.loaded["game.config.default.world_map_monster"]
lines[#lines + 1] = "MONSTER_CONFIG\t" .. type(map_config)
if type(map_config) == "table" then
    for key, row in pairs(map_config) do
        if type(row) == "table" then
            local row_level = row.level or row.lv or row.monster_level
            if row_level == level or key == 7100016 then
                local fields = {}
                for row_key, value in pairs(row) do
                    if type(value) == "number" or type(value) == "string" or type(value) == "boolean" then
                        fields[#fields + 1] = tostring(row_key) .. "=" .. tostring(value)
                    end
                end
                table.sort(fields)
                lines[#lines + 1] = "MONSTER\t" .. tostring(key) .. "\t" .. table.concat(fields, ",")
            end
        end
    end
end
return table.concat(lines, "\n"):sub(1, 15000)
