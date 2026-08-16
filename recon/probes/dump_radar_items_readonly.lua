local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function scalar(value)
    local kind = type(value)
    if kind == "nil" or kind == "number" or kind == "string" or kind == "boolean" then
        return tostring(value)
    end
    return kind .. ":" .. tostring(value)
end

local function dump_table(name, table_value, depth)
    add("TABLE", name, type(table_value), tostring(table_value))
    if type(table_value) ~= "table" then
        return
    end
    local count = 0
    for key, value in pairs(table_value) do
        count = count + 1
        if count > 80 then
            add("TRUNCATED", name)
            break
        end
        add("ENTRY", name, scalar(key), type(value), scalar(value))
        if depth > 0 and type(value) == "table" then
            local inner_count = 0
            for inner_key, inner_value in pairs(value) do
                inner_count = inner_count + 1
                if inner_count > 60 then
                    add("INNER_TRUNCATED", name, scalar(key))
                    break
                end
                add(
                    "FIELD",
                    name,
                    scalar(key),
                    scalar(inner_key),
                    type(inner_value),
                    scalar(inner_value)
                )
                if tostring(inner_key) == "transform" and inner_value ~= nil then
                    local ok, lp = pcall(function() return inner_value.localPosition end)
                    if ok and lp ~= nil then
                        add("FIELD_TRANSFORM_LOCAL", name, scalar(key), lp.x, lp.y, lp.z)
                    end
                end
            end
        end
    end
end

local view = GModule.UIModule:FindOpenedView(GViewId.RADAR)
add("RADAR_ITEMS", type(view), tostring(view))
if type(view) == "table" then
    dump_table("__items", view.__items, 1)
    dump_table("__subitems", view.__subitems, 1)
    dump_table("_sortedItems", view._sortedItems, 1)
    dump_table("_showItemMap", view._showItemMap, 1)
    dump_table("_cacheItems", view._cacheItems, 1)
    dump_table("_tempItems", view._tempItems, 1)
end

add("END")
return table.concat(lines, "\n")
