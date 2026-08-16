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
    if kind == "number" or kind == "boolean" or kind == "string" then
        return tostring(value)
    end
    return kind .. ":" .. tostring(value)
end

local function summarize_table(prefix, value, depth)
    add(prefix, "TYPE", type(value), tostring(value))
    if type(value) ~= "table" or depth <= 0 then
        return
    end
    local keys = {}
    for key, _ in pairs(value) do
        keys[#keys + 1] = key
    end
    table.sort(keys, function(left, right)
        if type(left) == type(right) then
            return tostring(left) < tostring(right)
        end
        return type(left) < type(right)
    end)
    local limit = math.min(#keys, 20)
    for index = 1, limit do
        local key = keys[index]
        local child = value[key]
        add(prefix .. "." .. tostring(key), scalar(child))
        if type(child) == "table" and depth > 1 then
            local nested_count = 0
            for nested_key, nested_value in pairs(child) do
                if nested_count >= 12 then
                    break
                end
                nested_count = nested_count + 1
                add(
                    prefix .. "." .. tostring(key) .. "." .. tostring(nested_key),
                    scalar(nested_value)
                )
            end
        end
    end
end

local hero = assert(GCtrl and GCtrl.HeroCtrl, "HeroCtrl unavailable")
local candidates = {
    {"GetTopHeroListByArmys", {}},
    {"GetTopHeroListByArmys", {5}},
    {"GetTopHeroListByArmys", {1}},
    {"GetMostPowerData", {}},
    {"GetHadHeroList", {}},
    {"GetHeroesByOrder", {}},
    {"GetRecruitedHeroList", {}},
}

for _, candidate in ipairs(candidates) do
    local name, args = candidate[1], candidate[2]
    local fn = hero[name]
    if type(fn) ~= "function" then
        add("CALL", name, "MISSING")
    else
        local ok, value = pcall(fn, hero, unpack(args))
        add("CALL", name .. "(" .. table.concat(args, ",") .. ")", ok and "OK" or "ERR", scalar(value))
        if ok then
            summarize_table("RESULT." .. name .. "." .. tostring(#args), value, 2)
        end
    end
end

add("END")
return table.concat(lines, "\n"):sub(1, 15000)
