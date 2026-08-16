local function restore(owner, key, label)
    local original_key = "__MUMU_AUTOTASK_ORIGINAL_" .. label
    local wrapper_key = "__MUMU_AUTOTASK_WRAPPER_" .. label
    local original = rawget(_G, original_key)
    local wrapper = rawget(_G, wrapper_key)
    if type(owner) == "table"
        and type(original) == "function"
        and owner[key] == wrapper then
        owner[key] = original
    end
    rawset(_G, original_key, nil)
    rawset(_G, wrapper_key, nil)
end

restore(
    GHelper.WorldMarchHelper,
    "RequestMarchStartOff",
    "WorldMarchHelper.RequestMarchStartOff"
)
restore(
    GCtrl.WorldMarchCtrl,
    "RequestWorldMarchStartOff",
    "WorldMarchCtrl.RequestWorldMarchStartOff"
)
_G.__MUMU_AUTOTASK_MARCH_CAPTURE_TEXT = nil
_G.__MUMU_AUTOTASK_MARCH_CAPTURE_COUNT = nil

return "MUMU_AUTOTASK_UNHOOK\t1\nEND\t1"
