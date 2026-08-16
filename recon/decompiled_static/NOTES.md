# Static call-chain notes

The radar skull path uses the live game's Lua business layer and its custom TCP
transport. It is not an HTTP POST endpoint.

## Quest selection

Use `GCtrl.RadarCtrl:GetQuestDataMap()` and retain entries satisfying all of:

```lua
quest:GetQuestType() == GDefine.RadarDefine.QUEST_TYPE.SLG_MONSTER
quest:IsShowInWorld()
quest:GetQuality() == requestedQuality
quest:GetQuestConfig() ~= nil
```

`quest:GetQuality()` returns the raw `RadarDefine.QUEST_QUALITY` value:

```text
1 = white
2 = green
3 = blue
4 = purple
5 = orange (the yellow/orange skull)
```

`RadarDefine.QUEST_TYPE.SLG_MONSTER` is `1`, matching the observed
`quest:GetQuestType() == 1` skull tasks.

## Expedition params

`RadarQuestExecuteView.TryOpenFormationView` constructs:

```lua
{
    marchMapType = GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL,
    marchType = WorldMapDefine.march_type.transaction_slg,
    mapObjType = WorldMapDefine.mapobj_type.map_monster,
    targetId = quest:GetQuestConfig().condition,
    stamina = quest:GetQuestConfig().stamtina_expend,
    pointStart = { x = cityX, y = cityY },
    pointEnd = { x = questX, y = questY },
    extra = { event_id = quest:GetId() },
    guide = false,
}
```

The original method passes `self._staminaCost`. The same class initializes that
field through this exact chain before the execute button is usable:

```lua
local config = quest:GetQuestConfig()
local staminaCost = config.stamtina_expend
self:_InitExecuteButtonElements(QUEST_TYPE.SLG_MONSTER, staminaCost)
-- _InitExecuteButtonElements:
self._staminaCost = staminaCost
```

Therefore `self._staminaCost` and `quest:GetQuestConfig().stamtina_expend` are
the same value for the skull path. See
`RadarQuestExecuteView.StaminaBinding.lua` for the normalized decompilation.

`cityX, cityY` come from
`GCtrl.WorldPlayerCtrl:GetPlayerCityPos()`. `questX, questY` come from
`quest:GetWorldPos()`.

## Stable ready predicate

`UIModule:FindOpenedView(GViewId.EXPEDITION)` can return the instance before its
panel finishes loading. `IsOpen()` is also set before `OnOpen()` and
`UpdateView()`. Poll until all of these hold:

```lua
view ~= nil
and view:IsLoaded()
and view:IsOpen()
and type(view.showHeroList) == "table"
and type(view.soldierList) == "table"
and type(view.formationNumLimt) == "number"
and view.allStamina ~= nil
and view.isGoOn ~= nil
and view.pointEnd ~= nil
and view.pointEnd.x ~= nil
and view.pointEnd.y ~= nil
```

After readiness, `view:OnBtnAverageClick()` followed by
`view:OnBtnGoOnClick()` is the same business-method sequence as the two UI
clicks. The second method preserves stamina, special-war, alliance,
beforehand-march, shield, gather, plunder, lower-tier, and idle-march checks.
It also calls `ExpeditionHelper.IsUnusualTip`, so directly invoking the method
does not bypass the gray-button formation guard.

Do not call `GoOnMarchEx()` directly in normal automation: doing so skips the
earlier validation chain. During development, never call `OnBtnGoOnClick()` or
any march request method against a live account.
