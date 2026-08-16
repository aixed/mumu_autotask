slot1 = slot0:CheckMarchType(uv0, slot0.isAttack)
slot2 = slot0.organize
slot3 = slot0.stamina

if slot0.exclusive then
	uv1.SaveExclusiveFormationPrefabs({
		hero_id = uv0.MakeHeroListForKey(slot0.showHeroList),
		soldier = uv0.MakeListForKey(slot0.soldierList)
	}, slot0:GetExtra(), handler(slot0, slot0.Close))
elseif slot2 then
	slot0:OnBtnSaveFormationClick()
else
	if uv1.IsUnusualTip({
		isGoOn = slot0.isGoOn,
		isRecover = slot0.isRecover,
		isGateDefend = slot0.isGateDefend
	}) then
		return
	end

	if uv2.CheckSpecialWar(slot0.marchMapType) then
		return
	end

	if uv1.CheckAllianceSafeResource(slot0.marchType)
		and not GCtrl.AllianceCtrl:IsHadAllaince() then
		uv3.OpenToast(i18n("common_tips_232"))
		return
	end

	if slot0.allStamina < slot0:GetCostStaminaEduce(
		slot3,
		slot0.showHeroList
	) then
		uv3.OpenGetResource({
			{
				count = 1,
				id = ResDefine.COMMANDER_STAMINA
			}
		})
		return
	end

	slot6, slot7 = uv1.IsBeforehandMarch(
		slot0.marchMapType,
		slot0.marchType,
		slot0.mapObjType,
		slot0:GetExtra(),
		true
	)

	if slot6 then
		return
	end

	slot0:GoOnMarch()
end
