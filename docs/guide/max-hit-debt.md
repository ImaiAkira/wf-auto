# `max_hit` 债务清单（机器可读版在 `tools/max_hit_baseline.json`）

## 规则

MAA 的 `max_hit` 是**整个任务共享**的计数器，用光后节点**静默跳过**（不报错、不打印）。
所以只有「一局里本来就只该发生一次」的强动作才配用它；会反复命中的节点要用
**时间闩锁**（`latch: <名字>`，≤1 次/`LATCH_RETRY_S`）或 **agent 侧每 episode 计数**（进房/进战复位）。

- 想新增 `max_hit`：要么在节点注释里写 `max_hit-reason: …`，要么登记进 `tools/max_hit_baseline.json`。
- 守卫：`pipeline-no-unregistered-maxhit`（#84）—— 未登记就红；**基线陈旧也红**（账目只减不增）。
- 真机事故先例：#79（`WuchongRecruitOpen: 3` → 打 3 把后第 4 间房静默失效 → 卡房 302s，运维看到的「打几把画面就卡死」）。

## 现在的账目

- `reasoned` **24 条**：已想清楚的刻意上限。其中一条容易被误读为债：
  `SpecialRecruitOpen / SpecialStartRecruit / SpecialRecruitRandom / SpecialRecruitFans / SpecialRecruitMutual`
  的 `max_hit: 1` 是 **`hooks_30.py:255` 明确钉住的设计**（「它只负责**打开一次**招募方式页」，
  之后由幻想/深渊专属节点接手），不是误用。
- `debt` **19 条**：见下方分组，每条的「怎么修 / 怎么验」写在 `tools/max_hit_baseline.json` 的 `debt` 里。

## 债务分组（按修法归类）

| 组 | 节点 | 修法 | 风险 |
|---|---|---|---|
| 退房 / 返回 / 导航 | `SpecialLeaveRoom` `SideLeaveRoom` `SideBack` `SideNavStage` `SideNavStoryTab` `SideClearPickTab` | 时间闩锁（需把 `latch` 从 `wuchong_act` 抽到共享动作） | 🟠 长线多阶段后静默失效 → 卡在页面 |
| 掉登录 / 回标题 / 账号确认 | `PubLoginContinue` `PubTitleStart` `PhantomLoginContinue` `PhantomTitleStart` `RecoverTitleStart` `RecoverAccountConfirm` | 时间闩锁 | 🟠 长跑掉登录 ≥4 次后就没人接（**五重也吃这个**） |
| 列表搜索 / 重试 | `FarmScroll` `FarmScrollUp` `FarmRetry` `FarmMazeEntry` | 改成「本关搜索预算」由场景侧计数、每次进关复位 | 🟡 连刷多套后搜不动 |
| 推进 / 房间开关 | `PushAdvanceTap` `SpecialAutoContinueSet` `SpecialFullNoNew` | 每场/每房复位计数 | 🟡 多局后失效 |
| 战败续关 | `PubGameOverGiveUp` `PubGameOverGiveUpFallback` `PubGameOverConfirm` `PubGameOverConfirmFallback` | 保留（10 次/任务，配合 giveup 的 `no_progress`） —— 属 `reasoned` | — |

## 为什么不在 #80 里一把梭

改这些节点要**逐场景真机回归**（幻想连战 / 深渊 / 主线 / 农场 / 推图各一套状态），
而本仓库的真机验收一向要求「改完在有状态的那台设备上跑一次」。盲改会把「打几把就停」
换成「卡在页面里出不来」，比现状更糟。

因此 #80 的第一刀只做**不出错的部分**：修正登记簿的错误分类（上面那 5 条），
把 19 笔真债的「修法 / 验法」写清，守卫继续只挡新增。
逐条清扫按场景排期，每清一条就从 `debt` 删一条（守卫会强制这一点）。
