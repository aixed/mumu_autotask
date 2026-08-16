local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        local value = select(index, ...)
        parts[#parts + 1] = tostring(value)
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function safe(label, fn)
    local ok, a, b, c, d = pcall(fn)
    if ok then
        return true, a, b, c, d
    end
    add("ERR", label, a)
    return false
end

local view = GModule.UIModule:FindOpenedView(GViewId.RADAR)
add("RADAR_VIEW", type(view), tostring(view))
if type(view) ~= "table" then
    add("END")
    return table.concat(lines, "\n")
end

for key, value in pairs(view) do
    if type(key) == "string" then
        add("VIEW_FIELD", key, type(value), tostring(value))
    end
end

local content = view.QuestContent
add("CONTENT", type(content), tostring(content))
if content ~= nil then
    safe("content.name", function() add("CONTENT_NAME", content.name) end)
    safe("content.childCount", function()
        add("CONTENT_CHILD_COUNT", content.childCount)
        local count = tonumber(content.childCount) or 0
        for index = 0, count - 1 do
            local child = content:GetChild(index)
            add("CHILD", index, tostring(child), child.name or "-")
            local lp = child.localPosition
            if lp ~= nil then
                add("CHILD_LOCAL", index, lp.x, lp.y, lp.z)
            end
            local pos = child.position
            if pos ~= nil then
                add("CHILD_WORLD", index, pos.x, pos.y, pos.z)
            end
            local go = child.gameObject
            if go ~= nil then
                add("CHILD_GO", index, go.name or "-", tostring(go))
                local active = go.activeSelf
                add("CHILD_ACTIVE", index, tostring(active))
            end
        end
    end)
end

add("END")
return table.concat(lines, "\n")
