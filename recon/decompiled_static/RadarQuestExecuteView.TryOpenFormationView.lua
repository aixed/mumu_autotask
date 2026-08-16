-- Normalized from the stripped LuaJIT prototype and its pseudo-assembly.
-- The original decompiler lost the local alias for transaction_slg.
function RadarQuestExecuteView.TryOpenFormationView(self, questData, guide)
    local marchMapType = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
    local marchType = WorldMapDefine.march_type.transaction_slg

    if GHelper.WorldMarchHelper.CheckSpecialWar(marchMapType) then
        return
    end

    if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
        marchMapType,
        marchType,
        nil,
        true
    ) then
        return
    end

    local startX, startY = GCtrl.WorldPlayerCtrl:GetPlayerCityPos()
    local endX, endY = questData:GetWorldPos()
    local questConfig = questData:GetQuestConfig()

    GModule.UIModule:OpenView(GViewId.EXPEDITION, {
        marchMapType = marchMapType,
        marchType = marchType,
        mapObjType = WorldMapDefine.mapobj_type.map_monster,
        targetId = questConfig and questConfig.condition or nil,
        stamina = self._staminaCost,
        pointStart = {
            x = startX,
            y = startY,
        },
        pointEnd = {
            x = endX,
            y = endY,
        },
        extra = {
            event_id = questData:GetId(),
        },
        guide = guide,
    })
end
