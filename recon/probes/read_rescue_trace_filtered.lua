local records = rawget(_G, "__MUMU_AUTOTASK_RESCUE_TRACE")
local lines = {
    "MUMU_AUTOTASK_RESCUE_TRACE_FILTERED\t1",
}

local function append(text)
    lines[#lines + 1] = tostring(text)
end

local function interesting(record)
    if type(record) ~= "string" then
        return false
    end
    if record:find("req_heartbeat", 1, true)
        or record:find("req_trigger_opinion", 1, true)
        or record:find("req_save_client_data", 1, true)
        or record:find("req_dun163_risk_check", 1, true)
        or record:find("req_players_base_info", 1, true) then
        return false
    end
    return record:find("req_", 1, true) ~= nil
        or record:find("RadarCtrl", 1, true) ~= nil
        or record:find("UIModule.OpenView", 1, true) ~= nil
        or record:find("UIModule.CloseView", 1, true) ~= nil
end

local function compact_record(record)
    local out = {}
    for line in tostring(record):gmatch("[^\n]+") do
        if line:find("^TRACE\t")
            or line:find("^SELF_SKIPPED")
            or line:find("VALUE\targ1\tstring\t")
            or line:find("VALUE\targ2\tnumber\t")
            or line:find("VALUE\targ2.sid\t")
            or line:find("VALUE\targ3._id\t")
            or line:find("VALUE\targ3._questId\t")
            or line:find("VALUE\targ3._status\t")
            or line:find("VALUE\targ3._worldX\t")
            or line:find("VALUE\targ3._worldY\t")
            or line:find("VALUE\targ3._expireTime\t")
            or line:find("VALUE\targ3._questConfig.type\t")
            or line:find("VALUE\targ3._questConfig.quality_type\t")
            or line:find("VALUE\targ3._questConfig.power_level\t")
            or line:find("VALUE\targ3._questConfig.stamtina_expend\t")
            or line:find("VALUE\targ3._questConfig.name\t")
            or line:find("VALUE\targ3._questConfig.condition\t")
            or line:find("VALUE\targ2._id\t")
            or line:find("VALUE\targ2._questId\t")
            or line:find("VALUE\targ2._status\t")
            or line:find("VALUE\targ2._questConfig.type\t")
            or line:find("VALUE\targ2._questConfig.quality_type\t")
            or line:find("VALUE\targ2._questConfig.power_level\t")
            or line:find("VALUE\targ2._questConfig.stamtina_expend\t") then
            out[#out + 1] = line
        end
    end
    return table.concat(out, "\n")
end

if type(records) ~= "table" then
    append("COUNT\t0")
    append("END\t0")
    return table.concat(lines, "\n")
end

local kept = {}
for index, record in ipairs(records) do
    if interesting(record) then
        kept[#kept + 1] = {
            index = index,
            text = compact_record(record),
        }
    end
end

append("TOTAL\t" .. tostring(#records))
append("COUNT\t" .. tostring(#kept))
for _, item in ipairs(kept) do
    append("BEGIN_RECORD\t" .. tostring(item.index))
    append(item.text)
    append("END_RECORD\t" .. tostring(item.index))
end
append("END\t" .. tostring(#kept))
return table.concat(lines, "\n")
