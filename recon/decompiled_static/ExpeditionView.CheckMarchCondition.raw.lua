-- This is raw LJD output. slot5 is the continuation and slot6 is the
-- remaining gather lifetime; LJD did not recover their initial assignments.
if (slot0.gatherEndTimestamp > 0
	and slot0.gatherEndTimestamp - TimeUtil.GetServerTime()
	or 0) < slot0.expeditionTime and slot6 > 0 then
	if not slot4 then
		function (slot0)
			if not uv0 then
				if not uv1 then
					uv2:CheckLower(slot0)
				else
					uv1(slot0)
				end
			else
				uv0(slot0, uv1)
			end
		end(handler(slot0, slot0.GoOnMarchEx))
	else
		slot4(function ()
			uv0(uv1)
		end)
	end

	return
end

if slot3 then
	slot3(slot5)
elseif not slot4 then
	function (slot0)
		if not uv0 then
			uv1:CheckLower(slot0)
		else
			uv0(slot0)
		end
	end(slot5)
else
	slot4(function ()
		uv0(uv1)
	end)
end
