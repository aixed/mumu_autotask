slot8 = slot0.isAttack

slot0:UpdateSoldierLoopNestScrollSize(
	slot0.exclusive,
	slot0.organize,
	slot0.exclusiveType,
	slot8,
	slot0.monsterId,
	slot0.isHideHero,
	slot0.warnings,
	slot0:GetExtra()
)

slot0.allStamina = uv0:GetLeftCount(ResDefine.COMMANDER_STAMINA)
slot15 = slot0:CheckMarchType(uv1, slot8)
slot0.showHeroList = slot1 or uv2.GetRecommendedHeroList(
	slot0:IsWhole(true, slot0:GetExtra()),
	slot0.isGuide,
	slot15,
	slot0.targetId,
	slot0.marchMapType,
	slot0:GetExtra()
)
slot0.formationNumLimt = slot0:UpdateFormationNumLimit(function ()
	uv0 = nil
end)
slot17, slot18, slot19, slot20 = uv2.GetSoldierInfoByMarchType(
	slot15,
	0,
	slot0:IsWhole(nil, slot0:GetExtra()),
	slot0:GetExtra(),
	nil
)
slot0.soldierList = slot3 or slot17
slot21, slot0.isLimitStatisticalMagnitude, slot23 =
	slot0:StatisticalMagnitudeSoldiers(
		slot0.soldierList,
		slot0.formationNumLimt,
		0
	)

slot0:UpdateObjectiveName()
slot0.formationPrefabs = slot0:GetFormationPrefabs()
slot0:UpdateFormationsInformation(slot0.formationPrefabs, nil, 0)
slot0:UpdateAttribute1(slot21, slot0.formationNumLimt)

slot25 = uv4.IsHaveCaptain(slot0.showHeroList)

slot0:UpdateFormationHerosGroup(slot0.showHeroList, nil, 1, slot2)
slot0:UpdateSoldierLoopNestScroll()
slot0:UpdateBtnSaveFormation(slot21 > 0, slot25, slot11)
slot0:UpdateBottomOperationGroup(slot21 > 0, slot25, slot0.soldierList)
slot0:UpdateFormationsCommonTip(
	slot0:UpdateAttribute2(
		uv3.GetSoldierCarryWeight(slot15, slot0.soldierList)
	)
)
slot0:OnTimer()
