slot1 = slot0:CheckResourcePlunder(slot0.marchMapType, slot0.marchType, slot0.pointEnd.x, slot0.pointEnd.y, slot0.kid)
slot2 = slot0:CheckBossPlunder(slot0.marchMapType, slot0.pointEnd.x, slot0.pointEnd.y, slot0.kid)
slot3 = slot0:CheckMarchType(uv0, slot0.isAttack)

if uv1.IsNotCityShieldTips[slot0.marchMapType] then
	slot3 = true
end

slot0:CheckMarchCondition(not slot3 and handler(slot0, slot0.CheckCityShieldTips) or nil, slot0:CheckMarchType(uv2, false) and handler(slot0, slot0.CheckGatherTimeTips) or nil, slot1 and handler(slot0, slot0.CheckResourcesPlunderTips) or nil, slot2 and handler(slot0, slot0.CheckBossPlunderTips) or nil)
