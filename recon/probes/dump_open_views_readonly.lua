local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function interesting(name)
    local text = string.lower(tostring(name))
    return string.find(text, "radar", 1, true)
        or string.find(text, "quest", 1, true)
        or string.find(text, "intel", 1, true)
        or string.find(text, "info", 1, true)
end

add("DUMP_OPEN_VIEWS")
if type(GViewId) == "table" then
    for name, id in pairs(GViewId) do
        if interesting(name) then
            add("GVIEW", name, id)
        end
    end
end

if type(GModule) == "table" and type(GModule.UIModule) == "table"
    and type(GViewId) == "table" then
    for name, id in pairs(GViewId) do
        local ok, view = pcall(GModule.UIModule.FindOpenedView, GModule.UIModule, id)
        if ok and type(view) == "table" then
            add("OPEN", name, id, view.class and tostring(view.class) or tostring(view))
            for key, value in pairs(view) do
                if type(key) == "string" and interesting(key) then
                    add("FIELD", name, key, type(value), tostring(value))
                end
            end
        end
    end
end

add("END")
return table.concat(lines, "\n")
