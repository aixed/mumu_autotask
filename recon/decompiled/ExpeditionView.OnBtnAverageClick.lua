slot0.soldierList = uv0.GetAverageSoldierList(slot0.marchMapType, slot0.soldierList, slot0.formationNumLimt, slot0.exclusive or slot0.organize, slot0:GetExtra())
slot0.formationNumLimt = slot0:UpdateFormationNumLimit()
slot1, slot0.isLimitStatisticalMagnitude, slot3 = slot0:StatisticalMagnitudeSoldiers(slot0.soldierList, slot0.formationNumLimt, 0)

slot0:UpdateAttribute1(slot1, slot0.formationNumLimt)

slot7 = uv0.IsHaveCaptain(slot0.showHeroList)

slot0:UpdateSoldierLoopNestScroll()
slot0:UpdateBtnSaveFormation(slot1 > 0, slot7, slot0.organize)
slot0:UpdateBottomOperationGroup(slot1 > 0, slot7, slot0.soldierList)
slot0:UpdateFormationsCommonTip(slot0:UpdateAttribute2(uv2.GetSoldierCarryWeight(slot0:CheckMarchType(uv1), slot0.soldierList)))
slot0:UpdateFormationAllocationTip()
