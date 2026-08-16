slot0 = slot0 or GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
slot5 = uv0.GetCurrentMaxMarchCount(slot0) - (slot3 and 0 or uv0.GetSelfMarchCountByCounterType(slot0))

if slot4 and (slot4.isSlg3League or slot4.isClimbTower or slot4.isBaseWar) then
	slot5 = 1
end

for slot11, slot12 in ipairs(slot1) do
	slot7 = 0 + (slot3 and slot12.allNum or slot12.cityNum)
end

slot9 = 0
slot10 = 0
slot11 = 0

for slot15, slot16 in ipairs(slot1) do
	if slot9 <= slot2 then
		slot11 = slot3 and slot16.allNum or slot16.cityNum
		slot10 = 0

		if ((slot7 / slot5 > slot2 or math.ceil(slot11 * 1 / slot5)) and math.ceil(slot11 * slot2 / slot7)) <= slot11 then
			slot16.selectNum = slot10
		else
			slot16.selectNum = slot11
		end

		if slot16.selectNum > slot2 - slot9 then
			slot16.selectNum = slot2 - slot9
		end

		slot9 = slot9 + slot16.selectNum
	end
end

return slot1
