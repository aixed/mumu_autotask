if slot0._pveBattleStartMap[slot3:GetId()] then
	printYCJError("RadarCtrl:RequestStartBattle 重复请求战斗，任务ID:", slot5)
else
	slot6[slot5] = true
end

uv0.SendMsg("req_intelligence_start_battle", {
	id = slot5,
	fight_heros_data = {
		source = slot1,
		fight_heros = slot2
	},
	extraData = slot3,
	otherData = slot4
}, true)
