# mumu-autotask

这是一个针对当前三台 MuMu Android 实例的 Python 自动化项目。业务动作不是
HTTP POST：游戏使用带登录态的 Sproto + safeComm 自定义 TCP 协议。项目通过
Frida 在已登录的游戏进程内读取原生 Lua 状态，用于确认角色、服务器、场景和情报
目标。真实验证表明，在 FridaDirect 线程中直接打开出征页或直接发出征包都有概率
使游戏退出，因此正式流程已禁用这些写入式 Lua 出征动作。

Lua 主状态由 ADB 只读扫描 `/proc/<pid>/maps` 与 `/proc/<pid>/mem` 定位。正式流程
不会发送 HOME、不会后台化游戏，也不会安装 Lua inline hook 或直接调用
`RequestMarchStartOff` 发出征包。所有 Lua 执行前都会等待主 Lua 状态空闲，并对
Frida 的瞬态 `breakpoint triggered` 做短重试；`access violation` 会被视为危险信号并立即停止，不继续重试。

## 安全边界

- 只允许王国/服务器 `4549`。配置加载、ADB PlayerPrefs/SDK 文件、Lua 中的
  `GetPlayerKid()` 和 `GetPlayerServerId()` 都会独立校验。
- 实例角色白名单固定如下；活动角色不在对应白名单时立即停止。
- 双角色实例在 INTEL 阶段确定活动角色后，OPEN/READY/COMMIT/VERIFY/CLOSE
  全部锁定为该角色。窗口批次也会冻结“刷新情报”读到的角色；出征、等待、领取和
  失败后的只读核对回执都必须是同一角色，流程中切换角色会立即停止。
- 目标绑定运行 ID、任务 ID、品质、坐标、过期时间、怪物 ID、等级和体力消耗；
  任一字段变化都会停止。
- 当前可安全执行的是：返回野外、只读读取情报、等待情报完成、一键领取。真实出征
  的 FridaDirect 写入路径已被硬保护拦截；下一步需要补齐纯 UI marker 定位后再恢复
  “平均配置 -> 出征”。

| ADB serial | MuMu 实例 | 允许角色 | 本机 Frida 地址 | 实例内端口 |
| --- | --- | --- | --- | --- |
| `127.0.0.1:16384` | `MuMuPlayer-12.0-0` | `打工人`, `打工魂` | `127.0.0.1:27042` | `27042` |
| `127.0.0.1:16416` | `MuMuPlayer-12.0-1` | `打工的` | `127.0.0.1:27052` | `38417` |
| `127.0.0.1:16480` | `MuMuPlayer-12.0-3` | `打工客`, `打工仔` | `127.0.0.1:27062` | `27042` |

不要选择角色管理中的 `#4583` 分组，其他任何服务器也都不允许。

## 安装

要求 Python 3.11+、MuMu 自带 ADB、三个实例中的 x86_64 Frida Server，以及
每台实例的 `/data/local/tmp/libmumu_bridge.so`。

```powershell
python -m pip install "frida==17.17.0" "frida-tools==14.10.4"
python -m pip install -e .
Copy-Item config.example.json config.json
python -m mumu_autotask --config config.json validate
```

当前使用的 ARM64 bridge 位于 `tools/bin/libmumu_bridge.so`，预期 SHA256 为：

```text
F9AB67F631A53A7E2EB144C06886B6A26A6987DF2B144CA5C13FAE1D6111A60F
```

16384 和 16480 的 Frida Server 内部监听 `27042`；16416 的实例使用内部端口
`38417`。运行 `devices --connect` 或 GUI“刷新设备”时会按配置自动补齐本机端口转发：

```powershell
$adb = "D:\Program Files\Netease\MuMu\nx_main\adb.exe"
& $adb -s 127.0.0.1:16384 forward tcp:27042 tcp:27042
& $adb -s 127.0.0.1:16416 forward tcp:27052 tcp:38417
& $adb -s 127.0.0.1:16480 forward tcp:27062 tcp:27042
```

`frida.exe` 一般安装在
`C:\Users\Administrator\AppData\Roaming\Python\Python313\Scripts`。项目运行使用
Python Frida API，因此该目录未加入 `PATH` 也不影响 CLI。

Frida 枚举或连接遇到明确的 Server/transport 断开错误时，客户端会读取
`adb forward --list`，从本机 Frida 端口反查对应 ADB serial 和实例内端口，以
`su 0` 重启该实例的 Frida Server，然后只重试原操作一次。同一 serial 的恢复操作
使用独立锁串行化；权限错误、脚本错误等非连接故障不会触发自动恢复。

## 连接检查

```powershell
python -m mumu_autotask --config config.json devices --connect
python -m mumu_autotask --config config.json status --all
```

`status` 不执行 Lua、不点击 UI、不发送游戏请求。它要求 PlayerPrefs 中的
`__KEY_KINGDOM__` 与 SDK 中的 `CONTEXT_UTILS_RECENTLY_SERVERID` 同时等于 `4549`，
再核对 ADB PID 和 Frida 中的游戏进程。

## 情报与出征

### 窗口启动器

双击项目根目录的 `start_mumu_autotask.bat`。启动器会自动连接并检查配置中的
三台 MuMu 实例，只将 ADB、Frida、游戏进程、PlayerPrefs 和 SDK Server ID
全部通过且等于 `4549` 的实例标记为在线。

1. 在启动器表格中选中需要操作的模拟器。
2. 点击“启动管理”，打开只绑定该 ADB serial 的管理窗口。
3. 管理窗口会先确认当前角色和 `4549`，如果游戏在城内会点击右下角“野外”，
   等到 `WorldScene` 加载完成后再读取可用骷髅目标。
4. 复选绿色、蓝色、紫色和黄色中的一个或多个品质。
5. 用“同时出征”滑块选择每波 `1-3` 队。
6. 点击“情报-自动狩猎野兽”不会再弹出二次确认；在纯 UI 出征路径补齐前，程序会在
   FridaDirect 环境下阻止真实出征，避免再次触发游戏退出。

管理窗口会显示当前可用目标和运行记录。真实出征执行期间会禁用其他操作和窗口
关闭，避免同一个 Frida 会话中途切换角色或终止。角色切换仍在游戏的
“头像 -> 设置 -> 角色管理”中完成；只能选择 `#4549` 分组，切换完成并等待游戏
加载后再刷新情报。

品质复选和同时出征数会在每次调整后立即保存到项目目录的
`mumu_autotask_gui_preferences.json`，并按 ADB serial 分开记录三台设备；首次打开
某台设备时默认只选紫色、同时出征 `3` 队。每个管理窗口使用独立的复选变量和
滑块变量，不会把一台设备的临时界面状态共享给另一台。任务开始后会冻结当次
并发数；运行期间滑块和品质复选都会禁用。

多品质任务先按 `绿色 -> 蓝色 -> 紫色 -> 黄色` 固定顺序建立精确目标队列，再按
冻结的并发数切成波次。一波代表游戏内最多同时在路上的 `1-3` 队；为避免同一个
游戏进程被多个控制流抢占，程序会在同一波内按顺序提交这些精确目标，提交前再次
确认处于野外且角色未变，提交完成后再一起等待本波目标完成。只有该波每个精确
runtime ID 都由只读状态轮询证明为 `COMPLETED/MISSING` 后，才会启动下一波。任一波
等待失败时会先做一次只读角色和情报核对，然后立即停止批次，把尚未发起的后续波次
标记为“跳过”，并禁止领取，避免在状态不确定时继续出征。

所有目标均成功或已确认完成时，窗口只调用一次游戏原生“一键领取”业务方法，随后
再做一次独立只读检查，要求原始目标 ID 全部为 `MISSING`。存在任何未解决失败时
不会领取；领取后仍有目标存在时也不会报告成功。结束摘要统一显示成功、刷新确认、
失败、跳过和领取核验结果。

也可以从终端启动同一个窗口：

```powershell
python -m mumu_autotask.gui --config config.json
```

仅验证情报脚本和外部保护，不附加 Frida：

```powershell
python -m mumu_autotask --config config.json inspect-intel `
  --serial 127.0.0.1:16480
```

执行只读情报检查：

```powershell
python -m mumu_autotask --config config.json inspect-intel `
  --serial 127.0.0.1:16480 --execute
```

确保游戏已经回到野外；如果在城内，会点击右下角“野外”，并等待加载完成：

```powershell
python -m mumu_autotask --config config.json ensure-world `
  --serial 127.0.0.1:16480 --execute
```

按品质选择目标但不打开出征页、不发送请求：

```powershell
python -m mumu_autotask --config config.json march `
  --serial 127.0.0.1:16480 --quality purple
```

注意：`march` 的默认 dry-run 会附加 Frida 并执行只读 INTEL Lua，以便从动态任务
列表选择精确目标；它不会执行 OPEN/COMMIT。支持 `green/绿色`、`blue/蓝色`、
`purple/紫色`、`yellow/黄色`，其中 `orange/橙色` 是 `yellow` 的别名。

真实执行“平均配置 -> 出征”（当前 FridaDirect 环境会被安全阻止）：

```powershell
python -m mumu_autotask --config config.json march `
  --serial 127.0.0.1:16480 --expected-role 打工仔 `
  --quality purple --target-id 425 --execute
```

`--target-id` 省略时按品质选择最早过期的目标；提供时只允许该精确 runtime ID，
且该目标的品质必须与 `--quality` 一致。目标已消失或品质不匹配都会在打开出征页前
失败。

当前 CLI 会先完成只读 INTEL；如果桥接线程是 FridaDirect，会在打开出征页前停止。
旧的 OPEN/READY/ADB 点击平均配置/出征/VERIFY 路径仅保留在代码保护之后，不会在
当前实机环境自动使用。VERIFY
优先寻找 COMMIT 前快照中不存在、且与目标坐标、怪物 ID、目标类型、行军类型和
服务器完全匹配的 self-march。服务器的 `world_march.transaction_slg` 回包只定义
`monster_id`，不保证回显请求中的 `event_id` 或怪物等级；存在 `event_id` 时仍要求
精确匹配，缺失时使用 `PROOF=MARCH_FIELDS`。如果行军很快完成并被删除，同一会话中
从初始状态 `1` 变为 `2/3` 也可作为 `PROOF=QUEST_STATUS`。没有这些证明就会失败，
不会把普通成功码或单纯按钮调用当成出征成功。

### 等待与领取

等待一个或多个已出征目标结束；`--target-id` 可重复：

```powershell
python -m mumu_autotask --config config.json wait-intel `
  --serial 127.0.0.1:16480 --expected-role 打工仔 `
  --target-id 425 --target-id 427 `
  --timeout 1800 --poll-interval 2 --execute
```

`wait-intel` 和 `claim-intel` 强制要求 `--expected-role`，将跨命令保存的 runtime
ID 绑定到产生它们的角色，避免双角色实例停在另一个白名单角色时误判。每轮只读取
这些精确 runtime ID，并重新校验锁定角色、`kingdom == 4549` 和
`server == 4549`。状态固定为：

- `PENDING`：`quest:IsCompleted()` 为 `false`，继续等待。
- `COMPLETED`：`quest:IsCompleted()` 为 `true`，可以领取。
- `MISSING`：ID 已不在任务表中，视为已经领取或不再存在。

回执中的 `quest_status` 是 `_status` 的诊断值，不参与完成判定；完成状态只以游戏
对象公开的 `IsCompleted()` 为准。

先做领取 dry-run，只检查状态，不发送请求：

```powershell
python -m mumu_autotask --config config.json claim-intel `
  --serial 127.0.0.1:16480 --expected-role 打工仔 `
  --target-id 425 --target-id 427
```

确认后执行一次游戏原生“一键领取”：

```powershell
python -m mumu_autotask --config config.json claim-intel `
  --serial 127.0.0.1:16480 --expected-role 打工仔 `
  --target-id 425 --target-id 427 --execute
```

真实调用是游戏 Lua 的 `RadarCtrl:RequestReceiveAllQuestReward()`，它经现有登录连接
发送 `req_intelligence_receive_onekey`，不是 HTTP POST。任何目标仍为 `PENDING` 时
不会进入请求阶段；目标全部为 `MISSING` 时幂等成功且不发送请求；存在
`COMPLETED` 时最多调用一次一键领取，并轮询到所有预期 ID 都变为 `MISSING` 才报告
成功。该原生“一键领取”会同时领取当前角色其他已经完成的情报；目标 ID 列表用于
发送前门禁和发送后验证。

## 通用 Lua

`exec-lua` 默认只允许内置只读表达式，并且默认只校验：

```powershell
python -m mumu_autotask --config config.json exec-lua `
  --serial 127.0.0.1:16384 `
  --code "return tostring(_VERSION)" --execute
```

任意 Lua 必须同时显式传入 `--allow-unsafe-lua --execute`。无论该开关是否存在，
`4549`、PID 和进程名保护都不会被跳过。

## 测试

```powershell
python -m unittest discover -s tests -t . -v
```

单元测试使用 fake ADB/Frida，不连接模拟器，也不会发送游戏请求。实机验证应避免
在同一游戏进程上反复 attach/detach；一次业务流程必须保持单一 Frida 会话。
