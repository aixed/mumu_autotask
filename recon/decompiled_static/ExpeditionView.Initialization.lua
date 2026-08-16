function ExpeditionView.InitData(self)
    self.fightType = GDefine.HeroDefine.HeroAttrType.SLG
    self.mapObjType = self._openParams.mapObjType or 0
    self.pointStart = self._openParams.pointStart
    self.pointEnd = self._openParams.pointEnd
    self.extra = self._openParams.extra
    self.marchMapType = self._openParams.marchMapType
        or GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL
    self.marchType = self._openParams.marchType
    self.massMarchType = self._openParams.massMarchType
    self.battleType = self._openParams.battleType
        or GRead.WorldRead.GetMarchBattleType(
            self.marchMapType,
            GHelper.ExpeditionHelper.GetMarchType(
                self.massMarchType,
                self.marchType
            )
        )
    self.targetId = self._openParams.targetId
    self.resIcon = self._openParams.resIcon
    self.stamina = self._openParams.stamina or 0
    self.yields = GHelper.ExpeditionHelper.GetResourceYields(
        self._openParams.marchType,
        self._openParams.yields
    )
    self.objectiveName = self._openParams.objectiveName
    self.gatherEndTimestamp = self._openParams.gather_end_timestamp or 0
    self.expeditionTime = 0
    self.exclusive = self._openParams.exclusive or false
    self.exclusiveType = self._openParams.exclusive_type
        or GHelper.ExpeditionHelper.ExclusiveType.AutoMass
    self.organize = self._openParams.organize or false
    self.isSupport = self._openParams.isSupport or false
    self.supportData = self._openParams.support_data
    self.formationNumLimtNet = GHelper.ExpeditionHelper.GetFormationNumLimit(
        self._openParams.isSupport,
        self._openParams.support_data,
        self._openParams.formationNumLimt
    )
    self.isAttack = self._openParams.isAttack or false
    self.monsterId = self._openParams.monsterId or 0
    self.kid = self._openParams.kid
    self.isGuide = self._openParams.guide
    self.isHideHero = self._openParams.isHideHero or false
    self.warnings = self._openParams.warnings or ""
    self.description = self._openParams.description or ""
    self.formationNo = self._openParams.formationNo or 0
    self.isEdit = self._openParams.isEdit or false
    self.soldierExtra = self._openParams.soldierExtra
    self.prepareTime = self._openParams.prepareTime
end

function ExpeditionView.OnOpen(self)
    ExpeditionView.super.OnOpen(self)
    self:RegisterMessageEvent()
    self:InitData()
end

function ExpeditionView.UpdateView(self)
    self:UpdateFormationTopMenu()
    self.formationNumLimtPrevious = nil

    if not self:UpdateExclusiveFormationsInformation(false) then
        self:UpdateFormationMain(nil, nil, nil, true)
    end

    self:UpdateFormationAllocation(true)
    self:UpdateAlphaCanvas(false)
end

function ExpeditionView.UpdateFormationMain(
    self,
    heroList,
    updateHero,
    soldierList,
    updateFormationInfo
)
    local marchType = self:CheckMarchType(
        GHelper.ExpeditionHelper.Check_Monster,
        self.isAttack
    )
    self.allStamina = GHelper.ResHelper:GetLeftCount(
        ResDefine.COMMANDER_STAMINA
    )
    self.showHeroList = heroList
        or GHelper.ExpeditionHelper.GetRecommendedHeroList(
            self:IsWhole(true, self:GetExtra()),
            self.isGuide,
            marchType,
            self.targetId,
            self.marchMapType,
            self:GetExtra()
        )
    self.formationNumLimt = self:UpdateFormationNumLimit()

    local generatedSoldiers = GHelper.ExpeditionHelper.GetSoldierInfoByMarchType(
        marchType,
        0,
        self:IsWhole(nil, self:GetExtra()),
        self:GetExtra(),
        nil
    )
    self.soldierList = soldierList or generatedSoldiers

    local selected = self:StatisticalMagnitudeSoldiers(
        self.soldierList,
        self.formationNumLimt,
        0
    )
    self:UpdateObjectiveName()
    self.formationPrefabs = self:GetFormationPrefabs()
    self:UpdateFormationsInformation(self.formationPrefabs, nil, 0)
    self:UpdateAttribute1(selected, self.formationNumLimt)
    self:UpdateFormationHerosGroup(
        self.showHeroList,
        nil,
        1,
        updateHero
    )
    self:UpdateSoldierLoopNestScroll()
    self:UpdateBottomOperationGroup(
        selected > 0,
        GHelper.FormationHelper.IsHaveCaptain(self.showHeroList),
        self.soldierList
    )
end
