local view = GModule.UIModule:FindOpenedView(GViewId.WORLD_SEARCH_OBJ)
if type(view) ~= "table" or type(view.OnBtnSearchClick) ~= "function" then
    error("world search view is unavailable", 0)
end
view._selectedObjType = 1
view.objLvMap[1] = 16
if type(view._commonSlider) == "table" and type(view._commonSlider.SetSliderValue) == "function" then
    view._commonSlider:SetSliderValue(16)
end
view:OnBtnSearchClick()
return "SEARCH_REQUESTED\t1\t16\t" .. tostring(view.viewId)
