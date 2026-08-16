-- Normalized from chunk_6343_05642818.ljbc.
function RadarQuestExecuteView._InitSlgMonsterContentElements(self, quest)
    local staminaCost = 0
    local config = quest:GetQuestConfig()
    if config then
        staminaCost = config.stamtina_expend
        -- Banner, text, power, reward, and sound initialization omitted.
    end
    self:_InitExecuteButtonElements(
        GDefine.RadarDefine.QUEST_TYPE.SLG_MONSTER,
        staminaCost
    )
end

function RadarQuestExecuteView._InitExecuteButtonElements(
    self,
    questType,
    staminaCost
)
    -- Button sprite and text initialization omitted.
    self.TxtCost.text = staminaCost
    self._staminaCost = staminaCost
end
