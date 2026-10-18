# MaaFramework 机制坑（本仓真机踩出来的，改 pipeline 前先读）

> 目标读者：改 `assets/resource/pipeline/*.json` 或写 `agent/` 自定义识别/动作的人。
> 每条都是**真机事故**换来的，附「怎么判断自己踩了」。

---

## 1. `max_hit` 是**整任务共享**计数，不是「每次/每回合」

- 语义：`max_hit` 由 MAA 按**一个任务**累计；用光后该节点**静默跳过**（不报错、不打印）。
- 事故（#79，2026-10-17 真机）：`WuchongRecruitOpen` 写 `max_hit: 3`，打 3 把后第 4 间房起
  再也不点「招募」→ 房间永远「未进行招募」→ 别人进不来 → 干等 `room_wait_sec`(300s) 收工。
  运维看到的是「打了几把画面就卡死」。
- 规则：**会在一局里反复命中的节点不许用 `max_hit`**。要「限速」用**时间闩锁**（本仓 `latch: <名字>`，
  ≤1 次/`LATCH_RETRY_S`）；要「每回合有限次」用 **agent 侧每 episode 计数**（进房/进战复位）。
- 判断：`grep '"max_hit"' assets/resource/pipeline/*.json`；守卫 `pipeline-no-unregistered-maxhit`（#84）
  要求每处要么登记在 `tools/max_hit_baseline.json`，要么注释里写 `max_hit-reason:`。

## 2. `timeout` 只约束**识别**；空转重试会一直耗到它超时才 `on_error`

- 事故（#78，实测 12.3-12.4s/轮）：结算节点的 `timeout: 12000` 让「本步候选全不中」的空转循环
  白跑 12 秒才回枢纽 → 结算 62s、人齐→开战 63s。
- 规则：流程节点 `timeout ≤ 3000`、`post_delay ≤ 1000`（真源 `scene/wuchong.FLOW_TIMEOUT_MS` /
  `FLOW_POST_DELAY_MS`，守卫 `wuchong-cadence-pact`）。
- 判断：看框架日志 `debug/maafw*.log` 里同一节点两次 `PipelineNode.Starting` 的间隔；
  `debug/wc77_node_period.py <节点名>` 直接算。

## 3. `[JumpBack]` 前缀每轮都会**抢帧**

- 语义：`next` 是**有序候选**；`[JumpBack]X` 排在前缀 = 每轮优先检查 X，命中就插进去执行。
- 事故（#27 历史 / #78b 复现）：把「点结算横幅」的节点放前缀，横幅一直在屏上 → 每轮都被它抢走，
  链上真正的结算按钮**永远轮不到**。
- 规则：结算类「一直在屏上」的节点只能放**别的节点之后**（本仓 `[JumpBack]PubQuestResult` 放在
  三个结算节点 `next` 的**末尾**）；守卫 `wuchong-cadence-pact` 的 W6 断言这条。

## 4. 识别很快，`prefetch_batch_ocr` 会合并一批候选的 OCR

- 实测：单次识别 `OcrTask` avg **0.107s**、其余节点 0.001-0.013s；扫完 25 个候选 ≈ **0.5s**。
- 推论：**别再为了「快点」去自写连点循环**（#77 干过，被运维当场否掉并撤销）。
  真慢的地方去查 `timeout` / `post_delay` / 页面切换等待，而不是识别。

## 5. 代理侧「每 episode」状态要自己复位

- 本仓做法：`_SESSION` 里放 episode 闩锁（`in_fight` / `battle_auto_off_tried` / `room_beat_ts` …），
  在 `_observe` 的 `_FIGHT_LEAVE_STATES` / 房间序列离开处复位。
- 事故（#79）：`unknown` 帧在**战斗内**会天然反复出现（技能演出/换波），累计计数（`unknown_limit`）
  会把长战斗判成「迷路」→ 打完就被收工掐死。已在战斗 episode 内不计（#76）。

## 6. 用户可见输出与机制日志要分开

- 规则（#86 起，**#142 推广到全场景**）：`agent/reporting.py` 是**唯一出口**——
  - `say()` → 用户可见，永远进 MFAAvalonia 面板；
  - `log()` → 机制日志，quiet 时只落盘；
  - `Progress(...)` → 进度行 `[进度] 场景 i/N`（格式只有 `format_progress` 一份，**场景里不许自己拼**）。
- **quiet 不是逐行改出来的**：`agent/main.py --quiet` 调 `reporting.set_quiet(True)`，把
  `sys.stdout` **一次**换成落盘 sink（`debug/agent.log`）——所以 `side_impl` / `lords_impl` 里
  那几百个既有 `print(...)` 不用动就自动归入机制日志。**新写的 `print` 同理**（它进文件，不进面板）。
- 日志打不开 → **不静音**（宁可吵，不许丢日志）+ 面板里说明原因；这是刻意的 fail-open。
- 判断：`hooks_142` 的 `progress-quiet-single-seam` / `progress-say-never-swallowed`；
  全仓口径见 `docs/spec/progress-visibility.md`。

---

## 附：真机取证套路

```powershell
# 1) 谁在拖时间（同一节点的真实重复周期）
python debug\wc77_node_period.py WuchongSettleContinue WuchongRoomWait

# 2) 某一轮到底花了多久（节点事件时间线，带与上一事件的间隔）
python debug\wc77_timeline.py 19:06:44.700 19:06:58.000 debug\maafw.log

# 3) 单节点识别耗时排行
python debug\wc77_profile_rounds.py debug\maafw.log --top 18
```

> 这三支脚本是 #76/#78 排障时写的，读的是 MaaFramework 自己的 `debug/maafw*.log`，不需要连设备。
