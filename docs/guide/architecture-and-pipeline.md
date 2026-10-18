# MAA Pipeline 原理 + 本仓库结构（自己动手改的入门）

> 目标读者：运维本人。目的：让你能**自己定位并修改**（例：五重手操不生效）。
> 本文只讲**事实**；凡是我没验证过的，会标 【未验证】。

---

## 一、MAA pipeline 是怎么跑起来的

### 1. 三个层次

```
MFAAvalonia.exe          ← GUI 外壳（.NET），选任务、传选项、显示日志
   └─ python -u agent/main.py   ← 常驻 agent 进程（本仓库 agent/ 下），注册"自定义识别/动作"
        └─ MaaFramework 原生库（deps/bin）← 真正的截图 / OCR / 模板匹配 / 点击 / 节点调度
              └─ resource/pipeline/*.json ← 节点图（真正的"逻辑"在这里）
```

- **`install/`** 是可运行产物：`MFAAvalonia.exe` + `python/` + `resource/` + `agent/` + `interface.json`。
- ⚠️ **`agent/*.py` 是常驻进程在启动时载入的** → 改了 `agent/` 必须**完全退出 MFAAvalonia 再启动**（不热载）。
  pipeline JSON 同理（资源也不热载）。判据：`Get-Process` 里 agent `python` 的 `StartTime` 早于文件修改时间 = 你跑的是旧代码。

### 2. 节点（node）= 识别 + 动作 + 去向

一个 pipeline JSON 就是一堆节点。**调度器反复做一件事**：在"当前候选集合"里**按顺序**逐个试节点的**识别**，**第一个命中的**就执行它的**动作**，然后按它的 `next` 进入下一批候选。

```jsonc
"SpecialScrollList": {
  "recognition": { "type": "TemplateMatch" | "OCR" | "And" | "Or" | "DirectHit" | "Custom",
                   "param": { ... } },
  "action":      { "type": "Click" | "Swipe" | "DoNothing" | "StopTask" | "Custom",
                   "param": { ... } },
  "next":        [ "A", "B", "[JumpBack]C" ],   // 有序候选；先命中的先走
  "max_hit":     6,                              // 本任务内该节点的命中上限
  "pre_delay": 200, "post_delay": 300            // 毫秒
}
```

关键语义（都是本仓库踩过的）：

| 语义 | 说明 |
|---|---|
| `next` 顺序 | **有序候选**，不是"并行"。所以"顺序 = 优先级"，排错了就抢跑（#18/#29/#37 全是这个病） |
| `[JumpBack]X` | **打断型**：命中 X 就插进去执行，然后**回到被打断的地方继续扫**。放在"候选前缀"里 = 每轮都优先检查 |
| 兜底（不加 JumpBack，挂在 `next` 末尾） | **兜底型**：前面都不中才轮到。适合"归位/放弃"这类 |
| `And` + `box_index` | 复合识别；`box_index` 决定"用哪个子识别的框"作为动作目标 |
| `max_hit` | **按任务**计数的命中上限；用光后该节点**静默跳过**（#50 的坑：一个 chunk = 一个任务，预算会被多条条目共享） |
| `Click: {target: true}` | 点**该节点识别框自己的中心** ✅ 本仓库铁律 |
| `Click: {target: [x,y,w,h]}` | **四元素 = "区域"**：`w/h=0` 会被当成"随机取区域内一点" → **斜向乱拉**（#58/#66 的坑）。**要点就写两元素 `[x,y]`** |
| `Swipe` | 同上：**必须两元素精确点 + 竖直**（列表是卡片一行一个） |
| `OCR` `expected` | **正则**；`box_index`/`roi` 决定裁剪范围（`roi` 是**先裁剪再 OCR**） |
| `TemplateMatch` | `roi` + `threshold`；**阈值不够高会误命中**（深渊 EX 模板对普通横幅 0.87 会误判 → 定 0.90） |

### 3. `interface.json`（ProjectInterface V2）= 任务与选项

- `task[]`：每个任务一个 `entry`（进入哪个节点）。
- `option[]`：选项（`select` / `input`），每个 case 会生成一份 **`pipeline_override`**（覆盖某些节点的识别/动作参数）。
- **本仓库的规矩（ADR-0001）**：**配置是唯一真源** —— `scene/*.py` 声明事实，`scene/options.py` **自动派生**出 `interface.json` 里的选项块，`scene/drift.py` 校验"配置 ↔ interface ↔ pipeline"三方一致。**不要手写选项块**（会和配置打架）。
- 命令行驱动（不用 GUI）时，`tools/interface_options.py` 能把界面的选项**等价地**变成 `pipeline_override` 传给 `post_task` —— 这是"命令行结果能代表 GUI"的关键。

### 4. `agent/` 里的"自定义识别/动作"

pipeline 里 `"custom_recognition": "xxx"` / `"custom_action": "xxx"` 必须在 **`agent/my_reco.py` / `agent/my_action.py` 注册**，否则该节点**永远不会命中**（注册漏了是静默失败）。

本仓库的自定义（对照修改时用）：

| 模块 | 干什么 |
|---|---|
| `agent/main.py` | agent 入口（注册所有自定义 + 起服务） |
| `agent/side_impl.py` | **批量清单指挥官**：解析清单、切目标、记账、收工、卡死兜底、`special_*` 自定义 |
| `agent/battle_loop_core.py` | 共享的"战斗循环/账本/卡死/重启"引擎（`SceneConfig` 数据化） |
| `agent/phantom_impl.py` / `abyss_impl.py` / `wuchong_impl.py` | 三个场景的状态机（五重在这里） |
| `agent/auto_switch_impl.py` | 「自动」开关的**定位 + 读状态 + 切**（跨模式共用） |
| `agent/batch_plan.py` | 清单解析 / 种类判定 |

---

## 二、本仓库目录与职责

```
assets/
  interface.json            # 任务 + 选项（选项块由 scene/options.py 派生，别手写）
  resource/pipeline/*.json   # 节点图：common / special_dungeon / phantom / abyss / wuchong / raid / farm / side_story / auto_push / gacha / pull / recover
  resource/image/**          # 模板图（域横幅、五重行、自动开关、深渊横幅…）
  resource/model/ocr/        # OCR 模型（gitignored，worktree 里没有要拷）
scene/                       # ★配置面（唯一真源）
  config.py                  # family 模板 + 成员 delta + 难度词表
  lord_battle.py             # 领主战类成员表（46 个）
  options.py                 # 由配置派生 GUI 选项块
  drift.py                   # 三方一致性校验（不空就是坏了）
  chain.py / events.py / page_rules.py   # 链拓扑 / 事件注入 / 页面判据表
  stamina.py / abyss.py / wuchong.py     # 体力恢复 / 深渊 / 五重 的**场景数据**
agent/                       # 上面那张表
tools/
  run_*_live.py              # 真机 runner（命令行入口）
  live_harness.py            # 连设备(按身份) / 归位规则表 / save_draw 闸口
  interface_options.py       # 把界面选项变成 pipeline_override
  install.py                 # 生成 install/ 可运行产物
  run_all_tests.ps1          # 一键：单元 + contract hooks + schema + drift
  contract_hooks/hooks_*.py  # 每个修复配的"守卫 + 破坏实验"
docs/spec/wuchong-spec.md    # 五重的已裁决规格（含待改点）
docs/adr/0001..0003          # 配置真源 / 链+恢复边 / 页面判据全局唯一
```

**三条铁律（破坏它们 = 报错或行为漂移）**
1. **ADR-0001**：配置是唯一真源，JSON 是"被注入/校验"的，不是"被生成"的。
2. **ADR-0002**：链是"页面锚定的拓扑 + 一条显式恢复边"；不要写"轮询环"式拓扑。
3. **ADR-0003**：页面判据**全局唯一**，场景可以覆盖但**必须被上报**。
4. 另外：`special_dungeon.json` 里有**承重注释**（`批量副本清单指挥官` / `幻想连战分派器` / `最临时的全局打断` / `紧挨卡死兜底` / `绝不会`）——**改文件时不许删掉它们**（有守卫断言各 ≥1）。

---

## 三、改哪里？—— 以"五重手操不生效"（#71）为例

改动会**散落在 4 个地方**，按这个顺序查：

1. **选项是否传到**：`assets/interface.json` 里五重任务的「是否手操」→ 它的 case 必须覆盖 `WuchongBattle.custom_action_param.manual = true`。
   命令行等价物看 `tools/interface_options.py`；**真机日志看 `[wuchong_switch]`/选项 dump**。
2. **节点是否被允许命中**：`assets/resource/pipeline/wuchong.json` 的 `WuchongBattle`（原始识别通常是 `__NONE__`，靠选项打开）+ 它在 `next` 里的**位置**。
   还要看 `agent/wuchong_impl.py` 里 `battle_loop_core.is_battle_hud`（**战斗 HUD 的唯一判据源**）与"每 2~4 轮 `stopped=yield` 让位一次"的设计 —— **如果 `yield` 之后节点没再进来，"持续"就断了**。
3. **自定义是否注册**：`agent/my_reco.py` / `agent/my_action.py` 里有没有 `wuchong_battle` / `wuchong_state`。**没注册 = 静默永不命中**。
4. **动作真的在点吗**：`agent/wuchong_impl.py::WuchongBattleAction`（手操循环、`stopped=` 的取值、几何来自 `scene/wuchong.py::WUCHONG_BATTLE`）。

**最小调试手册**（跑一次手操，抓这三类行就够定性）：

```powershell
# 在 install/ 或仓库根跑，日志在 debug/maafw.log 与 install/logs/
Select-String -Path .\debug\maafw.log -Pattern 'wuchong_switch|wuchong_battle|WuchongBattle|Node.Action|Node.Recognition'
```

| 日志长相 | 含义 | 去改哪 |
|---|---|---|
| `[wuchong_switch] 定位不到『自动』开关` | 开关定位失败 | `scene/auto_switch.py` + `agent/auto_switch_impl.py` |
| `custom_action_param` 里 `manual` 不是 `true` | **选项没生效** | `assets/interface.json` 的选项 case / `tools/interface_options.py` |
| `[wuchong_battle] … stopped=manual_off` | 动作进来了但认为"手操是关的" | `agent/wuchong_impl.py` 的 `manual` 取值来源 |
| `… stopped=yield` 之后**再无** `wuchong_battle` | **节点没再进来**（"持续"断在这里） | `wuchong.json` 的 `next` / `FLOW_STEPS`（`scene/wuchong.py`） |
| `Node.Recognition` 里**根本没有** `WuchongBattle` | 识别从未命中（被 `__NONE__` 挡着） | 选项是否把它打开 |
| 有 `Node.Action` 但画面无反应 | 点在错的地方 | 几何/`target:true`（截图对照） |

---

## 四、怎么验（别只信"应该好了"）

```powershell
cd <repo>\projects\wf-auto
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run_all_tests.ps1   # 单元 + hooks + schema
python -c "import sys;sys.path.insert(0,'.');from scene import drift;print(drift.check_all())"  # 必须 []
python tools\install.py v1.2.0 win x86_64                                       # 刷新 install/
```

真机：
```powershell
& "<repo>\ops\toolchain\platform-tools\adb.exe" connect 127.0.0.1:16384
python tools\run_wuchong_live.py --addr 127.0.0.1:16384 --manual 手操 --mode 多人 --fights 2
```
（`--help` 看确切的参数名；**`save_draw` 保持关** —— 开着会 1.4GB/小时写盘，曾把我们 26GB 打满。）

---

## 五、我给不了的部分

- 我**没能**定位 #71 的具体断点（会话上下文耗尽 + 你要求别开子代理）。上面第三节那张表是**按代码结构给的排查顺序**，不是"已经找到的结论"。
- 凡是标 【未验证】 的，都是我**没在真机上确认过**的推断。
