function ViewBase.Open(self, params)
    self.__openCount = self.__openCount + 1
    self._openParams = params

    if self._loadState == GViewLoadState.None then
        self:Load()
    elseif self._loadState == GViewLoadState.Loaded then
        if self._isOpenView then
            self:MultiOpenView()
        else
            self:OpenViewAfterLoaded()
        end
    end
end

function ViewBase.Load(self)
    if self._loadState ~= GViewLoadState.None then
        return
    end

    self._loadState = GViewLoadState.Loading
    GModule.LoadModule:LoadUI(self.panelName, function(prefab)
        if not prefab then
            return
        end

        self._loadState = GViewLoadState.Loaded
        self.gameObject = GenerateUtil.Instantiate(
            prefab,
            GModule.UIModule:GetLayerRoot(self.layerName),
            string.getLastStringBySeparator(self.panelName, "/")
        )
        self.transform = self.gameObject.transform
        HierarchyUtil.ExportHierarchy(self)
        self:InitCanvasComponent()
        self:DoAutoWorkOnLoad()
        self:OnLoaded()
        self:OpenViewAfterLoaded()
    end, self.isAsyncLoad)
end

function ViewBase.OpenViewAfterLoaded(self)
    GameMsg.SendMessage(GameMsgId.VIEW_BEFORE_OPEN, self)
    self:DoOpenView()
    self:DoAutoWorkOnOpen()
    self:OnOpen()
    GameMsg.SendMessage(GameMsgId.PANEL_SUBPANEL_OPEN, self)
    self:UpdateView()
end
