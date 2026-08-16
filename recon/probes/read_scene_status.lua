local function safe_call(object, name)
    if type(object) ~= "table" or type(object[name]) ~= "function" then
        return false, "missing"
    end
    return pcall(object[name], object)
end

local player = GCtrl and GCtrl.PlayerCtrl
local name_ok, name = safe_call(player, "GetPlayerName")
local kid_ok, kid = safe_call(player, "GetPlayerKid")
local server_ok, server = safe_call(player, "GetPlayerServerId")

local scene_module = GModule and GModule.SceneModule
local scene_type_ok, scene_type = safe_call(scene_module, "GetSceneType")
local map_type_ok, map_type = safe_call(scene_module, "GetMapType")
local is_city_world_ok, is_city_world = safe_call(scene_module, "IsCityWorld")
local loading_ok, loading = safe_call(scene_module, "IsLoading")
local transition_ok, transition = safe_call(scene_module, "IsInTransition")
local cur_scene = scene_module and scene_module._curScene or nil
local class = type(cur_scene) == "table" and cur_scene.class or nil
local class_name = type(class) == "table" and tostring(class.__cname) or "nil"

return table.concat({
    "SCENE_STATUS",
    "role=" .. tostring(name_ok and name or "unknown"),
    "kid=" .. tostring(kid_ok and kid or "unknown"),
    "server=" .. tostring(server_ok and server or "unknown"),
    "scene_type=" .. tostring(scene_type_ok and scene_type or "unknown"),
    "map_type=" .. tostring(map_type_ok and map_type or "unknown"),
    "is_city_world=" .. tostring(is_city_world_ok and is_city_world or "unknown"),
    "loading=" .. tostring(loading_ok and loading or "unknown"),
    "transition=" .. tostring(transition_ok and transition or "unknown"),
    "class=" .. class_name,
}, "\n")
