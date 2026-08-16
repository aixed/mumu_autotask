if not uv0.CheckHasIdleMarch(slot0.marchMapType, slot0.marchType) then
	return
end

function ()
	slot0, slot1 = uv0.DealWithExpeditionInfo(uv1.showHeroList, uv1.soldierList)

	uv2.RequestMarchStartOff(uv1.marchMapType, uv1.marchType, uv1.pointEnd.x, uv1.pointEnd.y, {
		hero_id = slot0,
		soldier = slot1
	}, uv1.extra)
end()
