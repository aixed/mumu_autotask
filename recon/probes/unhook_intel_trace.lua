local installed = rawget(_G, "__MUMU_AUTOTASK_INTEL_TRACE_INSTALLED")
local restored = 0
if type(installed) == "table" then
    for _, item in ipairs(installed) do
        local owner = item.owner
        local key = item.key
        if type(owner) == "table" and owner[key] == item.wrapper then
            owner[key] = item.original
            restored = restored + 1
        end
    end
end
rawset(_G, "__MUMU_AUTOTASK_INTEL_TRACE_INSTALLED", nil)
return table.concat({
    "MUMU_AUTOTASK_INTEL_TRACE_UNHOOK\t1",
    "RESTORED\t" .. tostring(restored),
    "END\t1",
}, "\n")
