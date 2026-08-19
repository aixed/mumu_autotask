local targets = {
    {"WorldPlayerCtrl.class", GCtrl and GCtrl.WorldPlayerCtrl and GCtrl.WorldPlayerCtrl.class},
    {"Search_FrameSubView", package.loaded["game.module.ui.item.main.Search_FrameSubView"]},
    {"WorldMapMonsterView", package.loaded["game.module.scene.world.ui.view.WorldMapMonsterView"]},
    {"MapMonsterData", package.loaded["game.module.logic.module.world.mapobj.data.MapMonsterData"]},
}

local lines = {}
for _, target in ipairs(targets) do
    local label, value = target[1], target[2]
    lines[#lines + 1] = table.concat({"TARGET", label, type(value), tostring(value)}, "\t")
    if type(value) == "table" then
        local keys = {}
        for key, _ in pairs(value) do
            keys[#keys + 1] = key
        end
        table.sort(keys, function(left, right)
            return tostring(left) < tostring(right)
        end)
        for _, key in ipairs(keys) do
            local item = value[key]
            local name = tostring(key)
            local lower = string.lower(name)
            if label ~= "WorldPlayerCtrl.class"
                or string.find(lower, "search", 1, true) then
                lines[#lines + 1] = table.concat({
                    "ITEM", label, name, type(item), tostring(item)
                }, "\t")
            end
        end
    end
end
return table.concat(lines, "\n"):sub(1, 15000)
