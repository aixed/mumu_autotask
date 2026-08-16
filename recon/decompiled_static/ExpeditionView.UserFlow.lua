function ExpeditionView.OnBtnAverageClick(self)
    self.soldierList = GHelper.FormationHelper.GetAverageSoldierList(
        self.marchMapType,
        self.soldierList,
        self.formationNumLimt,
        self.exclusive or self.organize,
        self:GetExtra()
    )
    self.formationNumLimt = self:UpdateFormationNumLimit()

    local selected, isLimited = self:StatisticalMagnitudeSoldiers(
        self.soldierList,
        self.formationNumLimt,
        0
    )
    self.isLimitStatisticalMagnitude = isLimited
    self:UpdateAttribute1(selected, self.formationNumLimt)
    self:UpdateSoldierLoopNestScroll()
    self:UpdateBottomOperationGroup(
        selected > 0,
        GHelper.FormationHelper.IsHaveCaptain(self.showHeroList),
        self.soldierList
    )
end

function ExpeditionView.OnBtnGoOnClick(self)
    if GHelper.ExpeditionHelper.IsUnusualTip({
        isGoOn = self.isGoOn,
        isRecover = self.isRecover,
        isGateDefend = self.isGateDefend,
    }) then
        return
    end

    if GHelper.WorldMarchHelper.CheckSpecialWar(self.marchMapType) then
        return
    end

    if self.allStamina < self:GetCostStaminaEduce(
        self.stamina,
        self.showHeroList
    ) then
        GHelper.ViewHelper.OpenGetResource({
            {
                count = 1,
                id = ResDefine.COMMANDER_STAMINA,
            },
        })
        return
    end

    local blocked = GHelper.ExpeditionHelper.IsBeforehandMarch(
        self.marchMapType,
        self.marchType,
        self.mapObjType,
        self:GetExtra(),
        true
    )
    if blocked then
        return
    end

    self:GoOnMarch()
end

function ExpeditionView.GoOnMarch(self)
    local resourcePlunder = self:CheckResourcePlunder(
        self.marchMapType,
        self.marchType,
        self.pointEnd.x,
        self.pointEnd.y,
        self.kid
    )
    local bossPlunder = self:CheckBossPlunder(
        self.marchMapType,
        self.pointEnd.x,
        self.pointEnd.y,
        self.kid
    )
    local skipShieldTip = self:CheckMarchType(
        GHelper.ExpeditionHelper.Check_Not_City_Shield,
        self.isAttack
    )
    if GHelper.WorldMarchHelper.IsNotCityShieldTips[self.marchMapType] then
        skipShieldTip = true
    end

    self:CheckMarchCondition(
        not skipShieldTip and handler(self, self.CheckCityShieldTips) or nil,
        self:CheckMarchType(
            GHelper.ExpeditionHelper.Check_Gather_Time,
            false
        ) and handler(self, self.CheckGatherTimeTips) or nil,
        resourcePlunder and handler(self, self.CheckResourcesPlunderTips) or nil,
        bossPlunder and handler(self, self.CheckBossPlunderTips) or nil
    )
end

function ExpeditionView.GoOnMarchEx(self)
    if not GHelper.WorldMarchHelper.CheckHasIdleMarch(
        self.marchMapType,
        self.marchType
    ) then
        return
    end

    local heroId, soldier = GHelper.FormationHelper.DealWithExpeditionInfo(
        self.showHeroList,
        self.soldierList
    )
    GHelper.WorldMarchHelper.RequestMarchStartOff(
        self.marchMapType,
        self.marchType,
        self.pointEnd.x,
        self.pointEnd.y,
        {
            hero_id = heroId,
            soldier = soldier,
        },
        self.extra
    )
end
