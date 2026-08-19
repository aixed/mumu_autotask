local previous = _G.__MUMU_AUTOTASK_MAPOBJ_CAPTURE
if type(previous) == "table" then
    pcall(GameMsg.RemoveMessageByTarget, previous)
end

local state = { level = 16, view_id = 99160001 }
state.map_callback = function(first, second, third)
    state.map_called = (state.map_called or 0) + 1
    state.map_arg1 = first
    state.map_arg2 = second
    state.map_arg3 = third
    if type(first) == "table" and first ~= state then state.mapobj = first end
    if type(second) == "table" and second ~= state then state.mapobj = second end
    if type(third) == "table" and third ~= state then state.mapobj = third end
end
state.search_callback = function(_, point, response_view_id)
    if response_view_id ~= state.view_id or type(point) ~= "table" then
        return
    end
    state.point = point
    GCtrl.WorldMapCtrl:ReqWorldMapObjByPos(
        GCtrl.PlayerCtrl:GetPlayerKid(),
        point.x,
        point.y
    )
end
GameMsg.AddMessage(
    state,
    GameMsgId.WORLD_REQ_MAPOBJ_BYPOS,
    state.map_callback
)
GameMsg.AddMessage(
    state,
    GameMsgId.REQ_WORLD_SEARCH_BACK,
    state.search_callback
)
_G.__MUMU_AUTOTASK_MAPOBJ_CAPTURE = state
GCtrl.WorldPlayerCtrl:ReqWorldMapSearch(
    WorldMapDefine.mapobj_type.map_monster,
    state.level,
    state.level,
    nil,
    nil,
    false,
    state.view_id
)
return "CAPTURE_STARTED\t1"
