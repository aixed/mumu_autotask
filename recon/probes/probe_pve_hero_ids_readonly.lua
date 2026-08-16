local lines = {}

local function add(...)
    local parts = {}
    for index = 1, select("#", ...) do
        parts[#parts + 1] = tostring(select(index, ...))
    end
    lines[#lines + 1] = table.concat(parts, "\t")
end

local function field(obj, name)
    local ok, value = pcall(function() return obj and obj[name] end)
    if ok then
        return value
    end
    return nil
end

local function call(obj, name)
    if type(obj) ~= "table" or type(obj[name]) ~= "function" then
        return nil
    end
    local ok, value = pcall(obj[name], obj)
    if ok then
        return value
    end
    return nil
end

local function hero_id(hero)
    local direct = field(hero, "id") or field(hero, "_id") or field(hero, "hero_id")
    if type(direct) == "number" then
        return direct
    end
    local config = field(hero, "hero_config")
    if type(config) == "table" then
        local config_id = field(config, "id") or field(config, "hero_id")
        if type(config_id) == "number" then
            return config_id
        end
    end
    for _, method in ipairs({"GetId", "GetHeroId", "GetConfigId"}) do
        local value = call(hero, method)
        if type(value) == "number" then
            return value
        end
    end
    return nil
end

local function power(hero)
    for _, key in ipairs({"powerFight", "fight", "power", "_power"}) do
        local value = field(hero, key)
        if type(value) == "number" then
            return value
        end
    end
    return nil
end

local function dump_list(label, list)
    if type(list) ~= "table" then
        add("LIST", label, type(list), tostring(list))
        return
    end
    add("LIST", label, "count", #list)
    for index, hero in ipairs(list) do
        add(
            "HERO",
            label,
            index,
            hero_id(hero) or "nil",
            power(hero) or "nil",
            field(hero, "quality") or "nil",
            field(hero, "profession") or "nil"
        )
    end
end

local hero_ctrl = assert(GCtrl and GCtrl.HeroCtrl, "HeroCtrl unavailable")
local ok_had, had = pcall(hero_ctrl.GetHadHeroList, hero_ctrl)
if ok_had then
    dump_list("GetHadHeroList", had)
else
    add("ERR", "GetHadHeroList", tostring(had))
end
local ok_order, ordered = pcall(hero_ctrl.GetHeroesByOrder, hero_ctrl)
if ok_order then
    dump_list("GetHeroesByOrder", ordered)
else
    add("ERR", "GetHeroesByOrder", tostring(ordered))
end
local ok_recruited, recruited = pcall(hero_ctrl.GetRecruitedHeroList, hero_ctrl)
if ok_recruited then
    dump_list("GetRecruitedHeroList", recruited)
else
    add("ERR", "GetRecruitedHeroList", tostring(recruited))
end
add("END")
return table.concat(lines, "\n"):sub(1, 15000)
