local KEY = "__MUMU_AUTOTASK_LIGHT_SEARCH_TRACE"
local trace = _G[KEY]
local restored = 0
if type(trace) == "table" and type(trace.originals) == "table" then
    for _, entry in pairs(trace.originals) do
        if type(entry) == "table" and entry.owner[entry.method_name] == entry.wrapper then
            entry.owner[entry.method_name] = entry.original
            restored = restored + 1
        end
    end
end
_G[KEY] = nil
return "LIGHT_SEARCH_TRACE\tUNINSTALLED\t" .. tostring(restored)
