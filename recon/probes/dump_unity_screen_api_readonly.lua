local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function try(label, fn)
    local ok, value = pcall(fn)
    add(label, ok, value, type(value), tostring(value))
    return ok, value
end

add("TYPE_CS", type(CS), tostring(CS))
try("CS_UnityEngine", function() return CS.UnityEngine end)
try("CS_Screen", function() return CS.UnityEngine.Screen end)
try("CS_Screen_width", function() return CS.UnityEngine.Screen.width end)
try("CS_RectTransformUtility", function() return CS.UnityEngine.RectTransformUtility end)
try("UnityEngine", function() return UnityEngine end)
try("UE_Screen", function() return UnityEngine.Screen end)
try("UE_Screen_width", function() return UnityEngine.Screen.width end)
try("UE_RectTransformUtility", function() return UnityEngine.RectTransformUtility end)

local view = GModule.UIModule:FindOpenedView(GViewId.RADAR)
if type(view) == "table" then
    add("CANVAS", tostring(view.__canvas), type(view.__canvas))
    try("canvas_scale", function() return view.__canvas.scaleFactor end)
    try("canvas_rect", function() return view.transform.rect end)
    try("canvas_size", function()
        local rect = view.transform.rect
        return tostring(rect.width) .. "x" .. tostring(rect.height)
    end)
    local item = view._showItemMap and view._showItemMap[377]
    if item ~= nil then
        add("ITEM", tostring(item), tostring(item.transform))
        try("item_position", function()
            local p = item.transform.position
            return tostring(p.x) .. "," .. tostring(p.y) .. "," .. tostring(p.z)
        end)
        try("item_anchored", function()
            local p = item.transform.anchoredPosition
            return tostring(p.x) .. "," .. tostring(p.y)
        end)
    end
end

add("END")
return table.concat(lines, "\n")
