local keys = {
    "__MUMU_AUTOTASK_RESCUE_TRACE_SLIM_INSTALLED",
    "__MUMU_AUTOTASK_RESCUE_TRACE_INSTALLED",
}
local restored = 0
for _, key in ipairs(keys) do
    local installed = rawget(_G, key)
    if type(installed) == "table" then
        for _, item in ipairs(installed) do
            if type(item.owner) == "table" and item.owner[item.key] == item.wrapper then
                item.owner[item.key] = item.original
                restored = restored + 1
            end
        end
    end
    rawset(_G, key, {})
end
rawset(_G, "__MUMU_AUTOTASK_RESCUE_TRACE_SLIM", {})
return table.concat({
    "MUMU_AUTOTASK_RESCUE_TRACE_SLIM_UNHOOK\t1",
    "RESTORED\t" .. tostring(restored),
    "END\t1",
}, "\n")
