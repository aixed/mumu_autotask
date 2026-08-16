local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function call(obj, method)
    if obj == nil or type(obj[method]) ~= "function" then
        return nil
    end
    local ok, a, b = pcall(obj[method], obj)
    if ok then
        return a, b
    end
    return nil
end

local function field(obj, name)
    if obj == nil then
        return nil
    end
    local ok, value = pcall(function() return obj[name] end)
    if ok then
        return value
    end
    return nil
end

local function screen_point(transform, camera)
    if transform == nil or type(UnityEngine) ~= "table"
        or UnityEngine.RectTransformUtility == nil then
        return nil
    end
    local ok, point = pcall(
        UnityEngine.RectTransformUtility.WorldToScreenPoint,
        camera,
        transform.position
    )
    if ok and point ~= nil then
        return point
    end
    return nil
end

local view = GModule.UIModule:FindOpenedView(GViewId.RADAR)
add("RADAR_TARGETS", type(view), tostring(view))
if type(view) ~= "table" then
    add("END")
    return table.concat(lines, "\n")
end

local camera = nil
if view.__graphicRaycaster ~= nil then
    camera = field(view.__graphicRaycaster, "eventCamera")
end
local screen_width = type(CS) == "table"
    and type(CS.UnityEngine) == "table"
    and CS.UnityEngine.Screen
    and CS.UnityEngine.Screen.width
    or type(UnityEngine) == "table"
    and UnityEngine.Screen
    and UnityEngine.Screen.width
    or "?"
local screen_height = type(CS) == "table"
    and type(CS.UnityEngine) == "table"
    and CS.UnityEngine.Screen
    and CS.UnityEngine.Screen.height
    or type(UnityEngine) == "table"
    and UnityEngine.Screen
    and UnityEngine.Screen.height
    or "?"
add("SCREEN", screen_width, screen_height, "CAMERA", tostring(camera))

local function dump_item(source, key, item)
    if type(item) ~= "table" then
        return
    end
    local quest = item._questData
    if type(quest) ~= "table" then
        return
    end
    local runtime_id = call(quest, "GetId") or field(quest, "_id") or field(quest, "id")
    local quest_id = field(quest, "_questId")
    local quest_type = call(quest, "GetQuestType")
    local quality = call(quest, "GetQuality") or field(quest, "_quality")
    local status = field(quest, "_status")
    local world_x, world_y = call(quest, "GetWorldPos")
    local transform = item.transform
    local local_x, local_y, local_z = "?", "?", "?"
    if transform ~= nil then
        local lp = transform.localPosition
        if lp ~= nil then
            local_x, local_y, local_z = lp.x, lp.y, lp.z
        end
    end
    local point = screen_point(transform, camera)
    local screen_x, screen_y, adb_x, adb_y = "?", "?", "?", "?"
    if point ~= nil then
        screen_x = point.x
        screen_y = point.y
        adb_x = point.x
        if type(screen_height) == "number" then
            adb_y = screen_height - point.y
        end
    end
    add(
        "ITEM",
        source,
        key,
        "ID",
        runtime_id,
        "QUEST",
        quest_id,
        "TYPE",
        quest_type,
        "QUALITY",
        quality,
        "STATUS",
        status,
        "WORLD",
        world_x,
        world_y,
        "LOCAL",
        local_x,
        local_y,
        local_z,
        "SCREEN",
        screen_x,
        screen_y,
        "ADB",
        adb_x,
        adb_y
    )
end

for key, item in pairs(view.__subitems or {}) do
    dump_item("__subitems", key, item)
end
for key, item in pairs(view._sortedItems or {}) do
    dump_item("_sortedItems", key, item)
end
for key, item in pairs(view._showItemMap or {}) do
    dump_item("_showItemMap", key, item)
end

add("END")
return table.concat(lines, "\n")
