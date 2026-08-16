# Runtime and static findings (2026-08-16)

This note records read-only checks only. It does not switch characters, open an
expedition, or dispatch a march.

## Device and Frida checks

Configured devices were online through the MuMu ADB executable:

| ADB serial | PID observed | Frida endpoint | Frida process |
| --- | ---: | --- | --- |
| `127.0.0.1:16384` | `1875` (before a later user/agent restart) | `127.0.0.1:27042` | `Whiteout Survival` |
| `127.0.0.1:16416` | `24346` | `127.0.0.1:27052` | `Whiteout Survival` |
| `127.0.0.1:16480` | `12171` | `127.0.0.1:27062` | `Whiteout Survival` |

`python -c "import frida; print(frida.__version__)"` reports Frida `17.17.0`.
The three local Frida ports were listening and `enumerate_processes()` returned
exactly one matching game process per endpoint.

`status --all` independently reported both PlayerPrefs and SDK server IDs as
`4549` for all three configured serials.

## Read-only Lua observations

`inspect-intel --execute` succeeded on all three processes. At the time of the
check, the active roles and visible intelligence were:

| Serial | Active role | Visible items |
| --- | --- | --- |
| `16384` | `打工人` | runtime `354` blue Lv13 at `(769,782)`; runtime `352` yellow Lv13 at `(796,776)` |
| `16416` | `打工的` | no visible items |
| `16480` | `打工客` | runtime `403` blue Lv13 at `(763,729)`; runtime `402` purple Lv13 at `(751,738)` |

The self-march map was empty on all three instances during a subsequent
read-only probe, so no live server echo could be collected without dispatching
a march.

## Static `transaction_slg` semantics

From the recovered LuaJIT modules:

- `WorldMarchDataFactory` maps `WorldMapDefine.march_type.transaction_slg` to
  `MapAttackMonsterMarchData`.
- `WorldMapMarchData.Initialize` copies every field from the incoming march
  table into `_data` and sets `_extraDataName` to
  `WorldMarchHelper.GetMarchTypeString(GetType())`.
- `GetMarchTypeString(transaction_slg)` returns the literal string
  `"transaction_slg"`.
- `WorldBaseMarchData._GetExtraData()` therefore returns
  `_data.transaction_slg`, not `_data.extra`.
- `MapAttackMonsterMarchData:GetTargetMapObjectId()` reads `monster_id` from
  `_GetExtraData()`.
- `WorldMarchCtrl:GetSelfMarchMap(serverId)` and `GetSelfMarch(serverId,id)`
  are public read-only getters. The normal server ID is obtained from
  `WorldPlayerCtrl:GetPlayerCityKid()`.
- Runtime probe on `16480` returned
  `GDefine.WorldMarchDefine.MARCH_MAP_TYPE.NORMAL == 1` while
  `GCtrl.WorldPlayerCtrl:GetPlayerCityKid() == 4549`. These values are not
  interchangeable; pass the city/server kid (`4549`) to `GetSelfMarchMap`, not
  the map-type enum.
- `RequestWorldMarchStartOff(type,x,y,formation,extra)` sends the `extra`
  argument to `NetMsg.SendMsg("req_world_march", ...)`; if the server echoes
  the event ID into the march object it should appear under
  `march.transaction_slg.event_id` (and via `marchObject:_GetExtraData().event_id`).

## Verification implication

Do not accept a missing quest, a changed quest status, or a generic success code
as proof that the selected intelligence was dispatched. Strong verification
must first snapshot the normal-server self-march IDs, then poll for a new
`transaction_slg` march and require matching owner, endpoint, monster ID,
level, and `event_id == target.runtime_id`. If the server does not echo the
event ID, report an explicit `EVENT_ID_NOT_ECHOED` result instead of claiming a
verified dispatch.
