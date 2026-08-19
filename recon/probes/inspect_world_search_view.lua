local view = GModule.UIModule:FindOpenedView(GViewId.WORLD_SEARCH_OBJ)
if type(view) ~= "table" then
    return "VIEW\tmissing"
end

local lines = {"VIEW\t" .. tostring(view)}
local function scalar(value)
    local kind = type(value)
    return kind == "string" or kind == "number" or kind == "boolean"
end

local function dump_table(label, value, depth, seen)
    if type(value) ~= "table" or seen[value] or depth < 0 then
        return
    end
    seen[value] = true
    local keys = {}
    for key, _ in pairs(value) do
        keys[#keys + 1] = key
    end
    table.sort(keys, function(left, right)
        return tostring(left) < tostring(right)
    end)
    for _, key in ipairs(keys) do
        local item = value[key]
        local path = label .. "." .. tostring(key)
        if scalar(item) or type(item) == "function" then
            lines[#lines + 1] = table.concat({path, type(item), tostring(item)}, "\t")
        elseif type(item) == "table" and depth > 0 then
            dump_table(path, item, depth - 1, seen)
        end
        if #lines >= 500 then
            break
        end
    end
end

dump_table("view", view, 2, {})
return table.concat(lines, "\n"):sub(1, 15000)
