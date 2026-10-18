# -*- coding: utf-8 -*-
"""#100 第 4、5 个真机缺口：领主战**自己的**模式选择页 + 非列表页的降噪与有界出口。

真机现场（484，2026-10-18 12:4x，``f5c2bc4`` 之后）
--------------------------------------------------
::

    [lords] 点 row @720(298,512) -> 阶段 detail（本轮第 1 次点击）
    [lords] 点 tier @720(104,509) -> 阶段 team（本轮第 2 次点击）
    （此后 state=wuchong_mode，不再变化）

证据帧 ``tools/frames/lords_mode_page_stuck.png``（12:47 真机 1080x1920）是**领主战的模式选择页**：
``单人游戏 / 单人挑战领主`` 在左上、``多人游戏 / 召集同伴挑战领主`` 在右下。
旧链把它判成 ``wuchong_mode``（**五重场景**的状态名）⇒ lords 状态机不认识 ⇒ 卡住；
同时 ``mode=tab`` 在非列表页每帧刷一行
``页签：cannot / 不在领主战列表页（读不到「更新列表」）``，而 **20s「点不出去」死线只在
``mode=read`` 判**（非列表页读不到 ``通关数``）⇒ 这一页没有任何有界出口。

本票的两条修法
--------------
1. **lords 自己的模式页状态**（``lords_mode``）+ 点「单人游戏」（:mod:`scene.lords_nav` 的
   ``page_state`` / ``mode_evidence``；pipeline 节点 ``LordsModeSolo``）::

      detail → tier → mode(单人) → 编队页(挑战) → 开打

   判据（★两帧真机证据，720 空间 = 1080 ÷1.5★）::

      单人游戏          [78, 497, 184, 52]     左上象限（中心 (170,523)）
      单人挑战领主      [78, 573, 136, 28]     左上象限
      多人游戏          [345, 839, 184, 51]    右下象限（中心 (437,864)）
      召集同伴挑战领主  [345, 940, 187, 27]    右下象限

   ★点的是「单人游戏」自己的**当帧 OCR 框中心**★（不写死坐标；该中心 (170,523) 与
   ``special_dungeon.json::SpecialModeSolo`` 的实测点 (170,523) 对得上）。绝不点「多人游戏」
   （那是共斗房 = 开别人的房间）。
2. **非列表页的降噪 + 有界**（``agent/lords_impl._tab_log_once`` / ``_non_list_stuck``）::

      [lords] 页签：cannot / 不在领主战列表页（…）（state=lords_mode）   ← 同一 (状态, 行) 只打一次
      [lords] 收工 —— 卡在「lords_mode」这类非列表页 10s 没有任何进展（不在列表页，无法导航）

   降噪键 = **(页面状态名, 那一行)**：状态名一变就允许再打一次（页面变了本身是信息）；
   有界判据 = **状态名** ``NON_LIST_STUCK_SEC``（9s，票面 8–10s 区间）不变，
   ★战斗/结算整类排除★（``LORDS_ACTIVE_STATES``）—— 不靠「状态名恰好在变」这种运气。

十个挂点
--------
1. ``lords-mode-page-state``：``lords_mode`` 判据来自两帧证据（文案 + 象限 + 单人卡更高），
   **状态词表里不许出现别的场景的状态名**（``wuchong*``），只给多人卡的帧**不许**判成模式页。
2. ``lords-mode-solo-click``：点的是「单人游戏」的框中心（不是副标题、不是多人卡）；
   点一下、等 ≥2.5s 再读、读到编队页才算成功；换了页面还能再点。
3. ``lords-non-list-noise``：同一原因连续命中只打印一次（注入 print 计数）。
4. ``lords-non-list-bound``：非列表页 K 秒无状态变化 ⇒ 收工且原因**带状态名**。
5. ``lords-active-not-cut``：``battle → settle → battle``（以及长战斗）**不会**被这条误判。
6. ``lords-mode-snapshot-parity``：安装态冻结副本 == 真源（常量 + 判据表 + 同一批帧的行为），
   且真源的判据表逐字段 == ``scene/page_rules.py``（ADR-0003）。

★#100 第 7、8 个真机缺口（本文件新增的三个挂点）★
--------------------------------------------------
真机现场（484，14:0x，``debug/lords_run14.log``）::

    [lords] 模式页：点「单人游戏」@720(170,523) …
    [lords] 模式页复核：点「单人游戏」后 离开了模式页但落在 left_mode_page:lords_unknown（不是编队页）
    [lords] 收工：收工 —— 卡在「lords_unknown」这类非列表页 9s 没有任何进展（不在列表页，无法导航）
    [lords] 点页签 @720(0,0) —— 切完由 mode=tab / mode=pick 复核确认

* **缺口 7（假成功 + 点击无效不换点）**：那一下**根本没生效**（15s 后手工 screencap 设备仍停在
  模式页，单人/多人两张卡都在），而复核读到的是一张**瞬时帧**（``lords_unknown``）——
  旧判据「离开了模式页 ⇒ 成功」把它判成成功。修法两条：
  ①**正向证据**：只有 ``team_page_confirmed``（有【挑战】∧ ``SET`` / ``Party`` / ``自动续战``
  至少一个）才算 ``mode_verify=team_page``；``unknown`` / 模式页一律不算成功；
  ②**换点阶梯**（有界 4 次）：中心 → 下方 100px → 右侧 120px → 下方 180px，每次点完等
  ≥2.5s 再重新抓帧读；四个点都试过 ⇒ 带量收工（原因含「4 个点都试过」）。
* **缺口 8（盲点 (0,0)）**：``点页签 @720(0,0)`` 是框无效（识别没给 / 尺寸 0 / 中心 (0,0)）
  时**照样点了**。修法：``agent/lords_impl._click_target`` 统一框闸 —— 无效框**拒绝点击**
  并打日志，所有真正发点击的路径（页签 / 普通点击 / 模式页阶梯）都先过它。

新增挂点
--------
7. ``lords-mode-positive-verify``：复核只认正向证据 —— 「点完 → 瞬时 unknown → 又回模式页」
   **必须判失败**（旧判据会判成功）；unknown 不清账、模式页判 ``still_mode``、
   只有编队页帧才 ``team_page``。
8. ``lords-mode-click-ladder``：中心无效 → 下方有效 ⇒ **2 个点 / 2 次点击**、第 2 个成功；
   全无效 ⇒ **4 次后带量收工**，原因含「4 个点都试过」，且 ``override_next`` 到 ``LordsStop``。
9. ``lords-click-no-blind-point``：``box=(0,0,0,0)`` / 缺失 / 零尺寸 Rect ⇒ 点击函数**不被调用**
   （注入 ``_click_hook`` 计数）；有效框仍然点（闸不许过宽）。★收工语义★已判收工时动作必须
   「成功但不点」—— 否则框架走 ``on_error`` 回枢纽，``override_next(LordsStop)`` 作废，
   收工会在枢纽里无限重来（修前是靠「点 (0,0) 返回 True」混过去的）。

破坏实验（``python tools\\contract_hooks\\hooks_122.py``，全部在内存里做）
----------------------------------------------------------------------
① 判据退回 ``wuchong_mode``（把 ``LORDS_STATE_MODE`` 改掉）→ 挂点 1 / 4 红；
② 点「多人游戏」（把 ``mode_evidence`` 的单人卡换成多人卡）→ 挂点 2 红；
③ 去掉降噪（``_tab_log_once`` 恒真）→ 挂点 3 红；
④ 去掉有界出口（``_non_list_stuck`` 恒空）→ 挂点 4 红；
⑤ 战斗/结算不再排除（``LORDS_ACTIVE_STATES = ()``）→ 挂点 5 红；
⑥ 快照漂移（把快照的状态名改一位）→ 挂点 6 红；
⑦ 复核退回「离开模式页即成功」（否定式判据）→ 挂点 7 红；
⑧ 去掉换点阶梯（``LORDS_MODE_CLICK_LADDER`` 只剩中心）→ 挂点 8 红；
⑨ 允许 (0,0) 盲点（``_box_center`` 不再拒绝无效框）→ 挂点 9 红；
⑩ 收工后动作忽略 ``stop_requested``（返回 False → on_error 回枢纽）→ 挂点 9 红
   （「成功但不点」的收工语义被破坏）。

#100 补充（真机 484，14:5x）：过渡态不许被「无进展」死线误杀
--------------------------------------------------------------
现场：``--home`` 把设备送回主城后**立刻**跑 ``--trace LordsEntry`` ——
::

    [lords] 页签：cannot / 不在领主战列表页（读不到「更新列表」）—— state=lords_unknown
    [lords] 收工：收工 —— 卡在「lords_unknown」这类非列表页 10s 没有任何进展（不在列表页，无法导航）

随后手工 ``screencap``：设备其实**好好地在主城**（活动 / 主城 / 关卡 / 领主战 / 菜单全部可见）。
⇒ 死线在**启动瞬间的过渡帧**上触发了：刚回主城那几秒是 loading / 半渲染，旧判据里它们没有
名字（= ``lords_unknown``），连续 9s 不变 ⇒ **任务还没开始就被判死**。

修法（★不放松未知画面的死线★）：

* ``scene/lords_nav.LORDS_STATE_LOADING``（``lords_loading``）—— 加载 / 过场帧的**名字**；
  判据 ``LORDS_LOADING_ANCHORS`` = ``common.json::PubLoadingText`` 的「请耐心等待」+
  #119 加载分支的「健康游戏忠告」（同样是**子串**，带百分比的帧也算）；
* ``LORDS_TRANSITION_STATES`` = ``(lords_loading, loading, relogin)`` —— 过渡态集合。
  ``loading`` / ``relogin`` 是共享层的裸名（lords 自己的词表全是 ``lords_*``，今天不会返回它们；
  列出来只为兜底）。★``lords_unknown`` 绝不在里面★。
* ``agent/lords_impl._non_list_stuck``：读到过渡态 ⇒ 把 ``non_list_state`` 清成 ``None`` 并清零
  计时 —— **不是**「跳过这一帧」：过渡结束后的第一帧必须从零起算。

两个新挂点
----------
10. ``lords-transition-not-stuck``：``unknown(2s) → loading(3s) → unknown(2s)`` 不收工；
    连续 15s 的 loading 帧也不收工（★这条才是「过渡集」的判据★）；
    ``unknown(8s) → loading → unknown(8s)`` 不收工（证明**重置**而非只跳过）；
    ``page_state(加载帧) == lords_loading``、``page_state(认不出) == lords_unknown``；
    ``lords_unknown`` / ``lords_list`` 不在过渡集里。
11. ``lords-unknown-still-bounded``：``lords_unknown`` 连续 12s（没有 loading 打断）⇒ **必须**收工，
    原因带状态名 + override 到 ``LordsStop``，超过死线后仍成立；``battle`` / ``settle`` 仍不触发
    （回归）；``LORDS_ACTIVE_STATES`` 与过渡集不相交。

破坏实验（新增三条）
--------------------
⑪ 把 loading 移出过渡集（``LORDS_TRANSITION_STATES = ()``）→ 挂点 10 红；
⑫ 把 ``lords_unknown`` 也当过渡态 → 挂点 11 红（证明没放行过头）；
⑬ 不再认加载页（``LORDS_LOADING_ANCHORS = ()``）→ 挂点 10 红。

#100 第 9 个真机缺口（2026-10-18 夜，真机 484）：模式页点不动的**真因**
------------------------------------------------------------------
现场（``debug/lords_diag2.log`` + 真机复现）::

    [lords] 模式页换点 1/4：「中心」@720(170,523)（点击派发成功）→ 读到 不是编队页（state=lords_unknown）
    …（4 个点都一样；固定等 2.5s 那一帧永远是 lords_unknown）

**点击是生效的**：点完「单人游戏」+1.8s 弹出的是**加成点数确认框**::

    要使用增加报酬的「领主加成点数」吗？ / 可能随挑战人数有所不同 / 今天剩余次数x3
    [是] [否]

它落在 ``lords_unknown``（背景仍是模式页、但「单人游戏」被遮住）；旧实现固定 ``sleep(2.5)``
只读一帧，随后换点阶梯的 4 个点全打在遮罩上 —— 「画面仍是模式页」这句**结论**其实是错的。
真机实测：点「否」后 +3.9s 到编队页（挑战 + SET 1 / Party A / 自动续战）。

修法：
* 点完**轮询读帧**（0.4s / 单点 ≤8s），读到稳定分类才下结论；连续 3 帧模式页才算「没生效」；
* 读到确认框（问题锚 + 当帧「否」按钮框）就点「否」（不消耗每天有限的加成次数）；
* 失败文案**只写读数**（``state=… 锚=…``），不再写「画面仍是模式页」；
* ``mode=pick`` 的空转诊断正式化 + 限流（状态一变就打；同一原因每 5 轮一次）。

三个新挂点
----------
12. ``lords-mode-bonus-dialog``：确认框判据（问题锚 + 「否」框）、点「否」→ 轮询到编队页、
    按钮换位置时点击跟着当帧 OCR 框走（不写死）、残留确认框时 ``mode=solo`` 直接命中它。
13. ``lords-pick-diag-rate-limit``：同一原因连续 12 轮只在第 1/6/11 轮打印；状态一变立刻打印；
    行里带 ``state / 行框 / stage / attempts / pending``（下次真机卡住一眼看出卡在哪）。

破坏实验（新增三条）
--------------------
⑭ 换点阶梯无限试（20 个点）→ 挂点 8 红；
⑮ 确认框点击目标写死（不跟当帧 OCR 框）→ 挂点 12 红；
⑯ pick 空转诊断每轮都打（限流失效）→ 挂点 13 红。

★诚实边界★
* 本守卫**不碰设备**：帧是两帧真机 OCR 的**逐条读数**（720 空间）与合成帧；它证的是「实现能按这些
  读数做出正确判决」，不是「今天真机还是这样」。
* 模式页的「四段文案齐全」是**故意从严**的：缺一段就**不点**（有界出口会给一句带状态名的收工理由），
  宁可不打也不点错（点错就是开别人的房间）。
* 「点完『单人游戏』之后一定是编队页」这条**已按仓内帧对账**（``lord_team_page.png`` 底部有
  ``挑战`` [296,1055,82,45] ⇒ ``lords_team``），但仍需真机确认一次落点。
* 本文件**不含任何本机绝对路径**（``REPO_ROOT`` 由 ``__file__`` 推出来；不碰 adb / 设备 / 临时目录），
  所以脱敏（``tools/portable_paths.py``）不需要在这里改引用。
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = Path(__file__).resolve().parent

HOOK_ID_MODE_STATE = "lords-mode-page-state"
HOOK_ID_MODE_CLICK = "lords-mode-solo-click"
HOOK_ID_NOISE = "lords-non-list-noise"
HOOK_ID_BOUND = "lords-non-list-bound"
#: ★#100 补充（真机 484，14:5x）★：过渡态不累加「无进展」计时 / 未知画面的死线仍在。
HOOK_ID_TRANSITION = "lords-transition-not-stuck"
HOOK_ID_UNKNOWN_BOUND = "lords-unknown-still-bounded"
HOOK_ID_ACTIVE = "lords-active-not-cut"
HOOK_ID_PARITY = "lords-mode-snapshot-parity"
#: ★#100 缺口 7/8★：正向复核 / 换点阶梯 / 盲点拒绝。
HOOK_ID_MODE_VERIFY = "lords-mode-positive-verify"
HOOK_ID_MODE_LADDER = "lords-mode-click-ladder"
HOOK_ID_CLICK_GUARD = "lords-click-no-blind-point"
#: ★#100 第 9 个真机缺口（2026-10-18 夜）★：加成点数确认框 / pick 空转诊断限流。
HOOK_ID_BONUS_DIALOG = "lords-mode-bonus-dialog"
HOOK_ID_PICK_DIAG = "lords-pick-diag-rate-limit"

_TICKET = "#100"

#: ★禁止出现在 lords 状态名里的词★：本票第 4 个缺口就是用它（五重的状态名）判 lords 的页面。
FORBIDDEN_STATE_WORDS: tuple = ("wuchong", "五重")

#: 证据帧 A（``tools/frames/lords_mode_page_stuck.png``，12:47 真机；顶部小标题「降临讨伐」）。
#: 720 空间（1080 原值 ÷1.5，逐条见模块 docstring 的 1080 表）。
MODE_FRAME_A: tuple = (
    ("降临讨伐", [149, 216, 98, 53]),          # 1080 224/324/147/80 —— 页头子族名（不是判据）
    ("光芒荒龙", [163, 200, 367, 160]),         # 1080 244/300/550/240 —— 领主名（艺术字，不参与）
    ("单人游戏", [78, 497, 184, 52]),
    ("单人挑战领主", [78, 573, 136, 28]),
    ("多人游戏", [345, 839, 184, 51]),
    ("建立房间", [347, 917, 93, 24]),
    ("召集同伴挑战领主", [345, 940, 187, 27]),
    ("返回", [30, 1246, 47, 26]),
    ("主城", [157, 1248, 44, 26]),
    ("菜单", [636, 1248, 45, 27]),
)

#: 证据帧 B（``tools/frames/lord_mode_select.png``，仓内既有帧；顶部小标题「领主战」）。
#: ★两帧同一页、逐项差 ≤2px★（证明这不是某一族的特例）。
MODE_FRAME_B: tuple = (
    ("领主战", [324, 269, 79, 28]),             # 1080 486/404/119/42
    ("猩红巨熊", [230, 195, 258, 69]),           # 1080 345/292/387/104
    ("单人游戏", [78, 497, 184, 52]),
    ("单人挑战领主", [78, 573, 136, 28]),
    ("多人游戏", [345, 839, 184, 51]),
    ("建立房间", [347, 917, 93, 24]),
    ("召集同伴挑战领主", [345, 940, 187, 27]),
)

#: 反例①：**只给多人卡**（进页动画 / OCR 漏读单人卡）⇒ 不许判成模式页、更不许点。
MULTI_ONLY_FRAME: tuple = (
    ("多人游戏", [345, 839, 184, 51]),
    ("建立房间", [347, 917, 93, 24]),
    ("召集同伴挑战领主", [345, 940, 187, 27]),
)

#: 反例②：**只给单人卡**（同上）⇒ 也不许判成模式页（四段文案缺一段就不点）。
SOLO_ONLY_FRAME: tuple = (
    ("单人游戏", [78, 497, 184, 52]),
    ("单人挑战领主", [78, 573, 136, 28]),
)

#: 反例③：**文案对、位置反**（单人卡跑到右下、多人卡跑到左上）⇒ 不许判成模式页。
SWAPPED_POSITION_FRAME: tuple = (
    ("单人游戏", [345, 839, 184, 51]),
    ("单人挑战领主", [345, 940, 187, 27]),
    ("多人游戏", [78, 497, 184, 52]),
    ("召集同伴挑战领主", [78, 573, 136, 28]),
)

#: 反例④：**文案与位置都对、但单人卡没比多人卡高 ≥200px**（两张卡几乎同高）。
SAME_HEIGHT_FRAME: tuple = (
    ("单人游戏", [78, 497, 184, 52]),
    ("单人挑战领主", [78, 573, 136, 28]),
    ("多人游戏", [80, 560, 184, 51]),
    ("召集同伴挑战领主", [80, 640, 187, 27]),
)

#: 计算目标框中心用的三个框（720 空间；与证据帧逐字相同）。
SOLO_BOX: tuple = (78, 497, 184, 52)
SOLO_NOTE_BOX: tuple = (78, 573, 136, 28)
MULTI_BOX: tuple = (345, 839, 184, 51)
MULTI_NOTE_BOX: tuple = (345, 940, 187, 27)

#: 主城帧（``主城`` 判据 ROI = [480,1080,240,140]；点 (608,1135) 是 SpecialOpenLord 的实测点）。
CITY_FRAME: tuple = (("领主战", [568, 1113, 80, 22]),)

#: 反例⑤（#100 缺口 7）：**转场帧** —— 认不出任何页面。旧判据「离开了模式页」会把它当成功。
#: 真机 484（14:0x）复核读到的就是这种帧，而 15s 后手工 screencap 设备仍停在模式页。
UNKNOWN_FRAME: tuple = (("Foo", [10, 10, 20, 20]),)

#: ★#100 第 9 个真机缺口（2026-10-18 夜，真机 484 实测 OCR）★：点完「单人游戏」后弹出的
#: **加成点数确认框**（720 空间，逐条照抄当时的 OCR）::
#:
#:     要使用增加报酬的「领主加成点数」吗？ / 可能随挑战人数有所不同 / 今天剩余次数x3
#:     是 [504,805,36,36]        否 [178,805,37,37]
#:
#: ★它落在 ``lords_unknown``★（背景仍是模式页，但「单人游戏」被遮住 ⇒ 四段文案缺一段）。
#: 修前的「画面仍是模式页 / 转场帧」判断就是被这张帧骗的。
BONUS_DIALOG_FRAME: tuple = (
    ("返回", [31, 1246, 44, 26]),
    ("否", [178, 805, 37, 37]),
    ("是", [504, 805, 36, 36]),
    ("“领主加成点数”吗？", [235, 538, 250, 32]),
    ("要使用增加报酬的", [248, 504, 223, 28]),
    ("可能随挑战人数有所不同", [247, 1130, 249, 30]),
    ("今天剩余次数x3", [254, 614, 213, 28]),
    ("建立房间", [344, 914, 96, 28]),
    ("召集同伴挑战领主", [345, 938, 187, 28]),
)

#: 同上，但**读不到「否」按钮框**（OCR 漏读）：认出来也点不了 ⇒ 绝不盲点。
BONUS_DIALOG_NO_DECLINE_FRAME: tuple = tuple(
    item for item in BONUS_DIALOG_FRAME if item[0] != "否"
)

#: 同上，但「否」按钮**换了位置**（+40/+30px）：点击必须跟着**当帧 OCR 框**走（不许写死坐标）。
BONUS_DIALOG_SHIFTED_FRAME: tuple = tuple(
    (text, [218, 835, 37, 37] if text == "否" else box) for text, box in BONUS_DIALOG_FRAME
)

#: ★加载 / 过场帧★（真机 484，14:5x）：``--home`` 把设备送回主城后**立刻**跑
#: ``--trace LordsEntry``，刚回主城那几秒的帧就是这种 —— 判据与 ``common.json::PubLoadingText``
#: 同一条文案（「请耐心等待」；``PubLoadingWait`` 的子识别，lords.json 里到处是它的 JumpBack）。
#: ★这是**过渡态**，不是「认不出的页」★：旧判据里它没有名字（= ``lords_unknown``），
#: 于是 9s 死线在任务还没开始时就收工（设备其实好好地在主城）。
LOADING_FRAME: tuple = (("请耐心等待", [300, 600, 200, 40]),)

#: 带百分比的加载页（另一帧真机读数 ``请耐心等待 79.28%``，见 ``scene/auto_switch.py``）：
#: 锚点是**子串**，所以这一帧也必须认成过渡态（整串锚定会把它漏成 lords_unknown）。
LOADING_FRAME_PCT: tuple = (("请耐心等待 79.28%", [300, 600, 260, 40]),)

#: 战斗 HUD / 结算帧（判据 = page_rules 的 ``战斗HUD`` / ``结算页``；★状态名必须是 lords_*★）。
BATTLE_FRAME: tuple = (
    ("时间 09:53", [100, 60, 120, 30]),
    ("分数 00000082254", [300, 60, 160, 30]),
)
SETTLE_FRAME: tuple = (("继续", [320, 1100, 80, 40]),)


# ---------------------------------------------------------------------------
# 惰性导入（与同目录其它 hooks 同一手法：挂点模块 import 期必须保持轻）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR), str(AGENT_DIR), str(HOOKS_DIR)):
        if path not in sys.path:
            sys.path.append(path)


def _impl():
    _paths()
    import lords_impl

    return lords_impl


def _lords_nav():
    _paths()
    import scene.lords_nav as nav

    return nav


def _page_rules():
    _paths()
    import importlib

    # ★必须走 importlib★：``import scene.page_rules as rules`` 会拿到 ``scene`` 包上同名
    # **函数**（``scene/__init__.py`` 重导出了 ``page_rules()``），而不是模块。
    return importlib.import_module("scene.page_rules")


def _fakes():
    """假 OCR / 假时钟 / 假 argv 借 ``hooks_100``（同一批真机帧与假 I/O，不抄第二份）。"""
    _paths()
    import hooks_100

    return hooks_100


def _tab(impl, ctx, task: int, node: str = "LordsSwitchTab"):
    return impl.LordsProgressRecognition().analyze(
        ctx, _fakes().FakeArgv(reco_param={"mode": "tab"}, task_id=task, node_name=node)
    )


def _solo(impl, ctx, task: int):
    return impl.LordsProgressRecognition().analyze(
        ctx,
        _fakes().FakeArgv(reco_param={"mode": "solo"}, task_id=task, node_name="LordsModeSolo"),
    )


def _detail(res) -> dict:
    return dict(getattr(res, "detail", None) or {})


def _center(box) -> tuple:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


@contextlib.contextmanager
def _frame(impl, frame):
    """只换「下一帧 OCR」——**不重置会话**（嵌套 ``FakeOcr`` 会 reset_sessions，把待验证的状态清掉）。"""
    saved = impl._ocr
    impl._ocr = lambda *a, **k: [tuple(item) for item in frame]
    try:
        yield
    finally:
        impl._ocr = saved


def _rect_fakes():
    """``hooks_120.FakeRect``（假 maa v5 ``Rect``：只有 .x/.y/.w/.h，没有 ``__len__``）。"""
    _paths()
    import hooks_120

    return hooks_120


@contextlib.contextmanager
def _ladder_env(impl, reads, calls=None):
    """替换「换点阶梯」的两个注入点：``_click_hook``（记下点在哪）与 ``_read_items_hook``
    （**点完等过之后读到的帧**，按队列依次给；队列空 = 读不到任何东西）。

    只替换这两个：识别用的 ``_ocr`` 仍由 ``FakeOcr`` 管（两边互不抢帧，剧本才好读）。
    """
    saved_click = impl._click_hook
    saved_read = impl._read_items_hook
    recorded = [] if calls is None else calls
    queue = [list(frame) for frame in reads]

    def _click(context, cx, cy):
        recorded.append((cx, cy))
        return True

    def _read(context, entry=None):
        return list(queue.pop(0)) if queue else []

    impl._click_hook = _click
    impl._read_items_hook = _read
    try:
        yield recorded
    finally:
        impl._click_hook = saved_click
        impl._read_items_hook = saved_read


# ---------------------------------------------------------------------------
# 1. 模式页判据（lords 自己的状态名 + 两帧证据 + 位置）
# ---------------------------------------------------------------------------
def _norm_evidence(ev) -> tuple:
    """模式页证据 → 纯数据（真源与快照的 dataclass 都能被同一份归一化吃掉）。"""
    return (
        tuple(ev.solo or ()),
        tuple(ev.solo_note or ()),
        tuple(ev.multi or ()),
        tuple(ev.multi_note or ()),
        bool(ev.is_mode_page),
        tuple(ev.solo_click_box or ()),
    )


def _norm_dialog(dialog) -> tuple:
    """加成点数确认框证据 → 纯数据（真源与快照都必须逐项相同）。"""
    return (
        dialog.question,
        tuple(dialog.decline or ()),
        tuple(dialog.accept or ()),
        bool(dialog.is_dialog),
        tuple(dialog.decline_click_box or ()),
    )


def _mode_state_failures(nav=None) -> list:
    """★模式页判据必须来自 lords 自己★（状态名 / 文案 / 位置 / 反例）。"""
    nav = _lords_nav() if nav is None else nav
    msgs: list = []

    # (a) 状态名：lords 自己的词表，不许出现别的场景的状态名
    if str(nav.LORDS_STATE_MODE) != "lords_mode":
        msgs.append(
            f"LORDS_STATE_MODE = {nav.LORDS_STATE_MODE!r} != 'lords_mode' —— "
            f"领主战模式页必须有自己的状态名（#100 第 4 个缺口：被判成 wuchong_mode 才卡住）"
        )
    blob = " ".join(str(name) for name in nav.LORDS_STATES) + " " + str(nav.LORDS_STATE_MODE)
    lower = blob.lower()
    for word in FORBIDDEN_STATE_WORDS:
        if word.lower() in lower:
            msgs.append(
                f"lords 状态词表里出现了别的场景的状态名（{word!r}）：{blob!r} —— "
                f"跨场景状态名混用会让排查时说不清是谁的页面"
            )
    for name in nav.LORDS_STATES:
        if not str(name).startswith("lords_"):
            msgs.append(f"状态名 {name!r} 不是 lords_* 前缀 —— 词表必须是 lords 自己的")
    if tuple(nav.LORDS_ACTIVE_STATES) != (nav.LORDS_STATE_BATTLE, nav.LORDS_STATE_SETTLE):
        msgs.append(
            f"LORDS_ACTIVE_STATES = {nav.LORDS_ACTIVE_STATES!r} != "
            f"({nav.LORDS_STATE_BATTLE!r}, {nav.LORDS_STATE_SETTLE!r}) —— "
            f"战斗/结算必须整类排除在非列表页死线之外"
        )

    # (b) 两帧真机证据都必须判成 lords_mode
    for label, frame in (("A", MODE_FRAME_A), ("B", MODE_FRAME_B)):
        state = nav.page_state(frame)
        if state != nav.LORDS_STATE_MODE:
            msgs.append(f"证据帧 {label} 的 page_state = {state!r}，应为 {nav.LORDS_STATE_MODE!r}")
        ev = nav.mode_evidence(frame)
        if not ev.is_mode_page:
            msgs.append(f"证据帧 {label} 的四段文案没被判成模式页（{ev.summary()}）")
        if tuple(ev.solo_click_box or ()) != SOLO_BOX:
            msgs.append(
                f"证据帧 {label} 的可点框 = {ev.solo_click_box!r}，应为「单人游戏」框 {SOLO_BOX}"
            )

    # (c) 位置判据：两张卡必须在**各自象限**（分界线 = 720x1280 的一半 = 360/640）
    ev_a = nav.mode_evidence(MODE_FRAME_A)
    solo_cx, solo_cy = _center(ev_a.solo)
    multi_cx, multi_cy = _center(ev_a.multi)
    if not (solo_cx < 360 and solo_cy < 640):
        msgs.append(f"「单人游戏」不在左上象限：中心 ({solo_cx:.0f},{solo_cy:.0f})")
    if not (multi_cx >= 360 and multi_cy >= 640):
        msgs.append(f"「多人游戏」不在右下象限：中心 ({multi_cx:.0f},{multi_cy:.0f})")
    if multi_cy - solo_cy < nav.LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY:
        msgs.append(
            f"「单人游戏」没有比「多人游戏」高 ≥{nav.LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY}px："
            f"Δy = {multi_cy - solo_cy:.0f}（实测 ≈342）"
        )
    if tuple(nav.LORDS_MODE_SOLO_ROI) != (0, 0, 360, 640) or tuple(nav.LORDS_MODE_MULTI_ROI) != (360, 640, 360, 640):
        msgs.append(
            f"两张卡的象限不是 (0,0,360,640)/(360,640,360,640)："
            f"{nav.LORDS_MODE_SOLO_ROI!r} / {nav.LORDS_MODE_MULTI_ROI!r}"
        )
    if str(nav.LORDS_MODE_SOLO) != "单人游戏" or str(nav.LORDS_MODE_MULTI) != "多人游戏":
        msgs.append(
            f"模式页文案漂移：单人={nav.LORDS_MODE_SOLO!r} 多人={nav.LORDS_MODE_MULTI!r}"
        )

    # (d) 反例：只给一张卡 / 位置反了 / 两张卡同高 —— 一律**不许**判成模式页、不许给可点框
    for label, frame in (
        ("只给多人卡", MULTI_ONLY_FRAME),
        ("只给单人卡", SOLO_ONLY_FRAME),
        ("单人/多人位置互换", SWAPPED_POSITION_FRAME),
        ("两张卡几乎同高", SAME_HEIGHT_FRAME),
    ):
        ev = nav.mode_evidence(frame)
        state = nav.page_state(frame)
        if ev.solo_click_box is not None:
            msgs.append(
                f"反例「{label}」竟给出了可点框 {ev.solo_click_box!r} —— 会点到不存在的/别人的卡"
            )
        if state == nav.LORDS_STATE_MODE:
            msgs.append(f"反例「{label}」竟被判成 {nav.LORDS_STATE_MODE!r}（证据不足时不许说自己在模式页）")

    # (e) 其余页面的状态名（列表/详情/编队/主城/战斗/结算/认不出）
    fakes = _fakes()
    for label, frame, want in (
        ("列表页", fakes.LIST_FRAME, nav.LORDS_STATE_LIST),
        ("详情页", fakes.DETAIL_FRAME, nav.LORDS_STATE_DETAIL),
        ("编队页", fakes.TEAM_FRAME, nav.LORDS_STATE_TEAM),
        ("主城", CITY_FRAME, nav.LORDS_STATE_CITY),
        ("战斗 HUD", BATTLE_FRAME, nav.LORDS_STATE_BATTLE),
        ("结算页", SETTLE_FRAME, nav.LORDS_STATE_SETTLE),
        ("认不出", [("Foo", [10, 10, 20, 20])], nav.LORDS_STATE_UNKNOWN),
    ):
        got = nav.page_state(frame)
        if got != want:
            msgs.append(f"{label} 的 page_state = {got!r}，应为 {want!r}")
    return msgs


def probe_lords_mode_page_state() -> bool:
    """#100-4：模式页判据来自 lords 自己（状态名 + 两帧文案/位置 + 反例）。"""
    return _mode_state_failures() == []


# ---------------------------------------------------------------------------
# 2. 点「单人游戏」（当帧框中心、点一次、点完复核）
# ---------------------------------------------------------------------------
def _mode_click_failures(impl=None, nav=None) -> list:
    """★点「单人游戏」= 当帧框中心 + **轮询读帧** + 正向复核★（#100 缺口 7/9）。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []
    task = 12201

    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(3000.0), fakes.FakeSleeper() as sleeper:
        ctx = fakes.FakeContext()
        res = _solo(impl, ctx, task)
        detail = _detail(res)
        if res.box is None:
            return [f"模式页上 mode=solo 没命中（{detail.get('reason')!r}）—— 修前就是这样卡住的"]
        if tuple(res.box) != SOLO_BOX:
            msgs.append(
                f"mode=solo 给的框 {tuple(res.box)!r} != 「单人游戏」框 {SOLO_BOX} —— "
                f"点别的卡就是开别人的房间"
            )
        if detail.get("state") != nav.LORDS_STATE_MODE:
            msgs.append(f"mode=solo 的 detail.state = {detail.get('state')!r}，应为 lords_mode")
        # ★状态名 / 理由里都不许出现别的场景的词★（票面：断言 reason/state 名里不含 wuchong）
        for label, value in (
            ("detail.state", str(detail.get("state"))),
            ("detail.reason", str(detail.get("reason") or "")),
        ):
            for word in FORBIDDEN_STATE_WORDS:
                if word.lower() in value.lower():
                    msgs.append(f"{label} 里出现了别的场景的状态名（{word!r}）：{value!r}")
        if detail.get("state") not in nav.LORDS_STATES:
            msgs.append(f"detail.state = {detail.get('state')!r} 不在 lords 状态词表 {nav.LORDS_STATES!r} 里")
        if detail.get("what") != impl.WHAT_MODE:
            msgs.append(f"mode=solo 的 detail.what = {detail.get('what')!r}，应为 {impl.WHAT_MODE!r}")

        action = impl.LordsUnlockAction()
        session = impl._session(task)
        # 第一点就成功：点中心 → 轮询读帧 → 读到编队页（正向证据）
        with _ladder_env(impl, [fakes.TEAM_FRAME]) as calls:
            ok = action.run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        if not ok:
            msgs.append("点了「单人游戏」却返回失败（动作如实失败，不吞成成功）")
        if len(calls) != 1:
            msgs.append(f"第一点就成功却点了 {len(calls)} 下（应只点 1 下：{calls!r}）")
        got = calls[0] if calls else None
        want = _center(SOLO_BOX)
        if got is not None:
            if abs(got[0] - want[0]) > 1 or abs(got[1] - want[1]) > 1:
                msgs.append(f"第一个点 {got} 不是「单人游戏」框中心 {want}")
            if got == _center(MULTI_BOX):
                msgs.append(f"点到了「多人游戏」的位置 {got} —— 那是共斗房（开别人的房间）")
            if got == _center(SOLO_NOTE_BOX):
                msgs.append(f"点到了「单人挑战领主」的位置 {got} —— 那是副标题，点了没反应")
        interval = float(nav.LORDS_MODE_POLL_INTERVAL_SEC)
        if sleeper.calls.count(interval) < 1:
            msgs.append(
                f"点完没有按轮询间隔（{interval:g}s）读帧（sleep 记录 {sleeper.calls!r}）—— "
                f"固定等 2.5s 的那一帧正是加成确认框（lords_unknown）"
            )
        if session.attempts_since_read != 1:
            msgs.append(
                f"点「单人游戏」没有记成「一次目标点击」（attempts={session.attempts_since_read}）"
                f"—— 它是目标流程上的一跳（行 → 档 → 模式 → 编队 → 挑战）"
            )
        if session.stage != impl.STAGE_TEAM:
            msgs.append(f"点完模式页的 stage = {session.stage!r}，应为 {impl.STAGE_TEAM!r}")
        if session.mode_clicks != 1:
            msgs.append(f"点了一次后 mode_clicks = {session.mode_clicks}，应为 1")
        if not session.mode_verified:
            msgs.append("读到编队页后没有记下正向证据（mode_verified 仍为 False）")

        # 点完复核：下一帧是编队页 ⇒ mode_verify=team_page，且点击账清零
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), _frame(impl, fakes.TEAM_FRAME):
            team = _solo(impl, ctx, task)
        team_detail = _detail(team)
        if team.box is not None:
            msgs.append(f"到了编队页 mode=solo 还在命中（box={team.box!r}）")
        if team_detail.get("state") != nav.LORDS_STATE_TEAM:
            msgs.append(f"编队页的 state = {team_detail.get('state')!r}，应为 lords_team")
        if team_detail.get("mode_verify") != "team_page":
            msgs.append(
                f"点完「单人游戏」没有复核出「已到编队页」：mode_verify="
                f"{team_detail.get('mode_verify')!r}（期望 'team_page'）"
            )
        if impl._session(task).mode_clicks != 0:
            msgs.append("复核成功后没有清掉点击账 —— 下一轮再回到模式页就再也点不动了")
        log = buf.getvalue()
        if "离开了模式页" in log:
            msgs.append(f"复核日志还在用否定式判据「离开了模式页」：{log!r}")
        if "✓" not in log:
            msgs.append(f"复核成功的日志没有正向标记 ✓：{log!r}")

        # 下一轮再回到模式页还能再点一次
        again_mode = _solo(impl, ctx, task)
        if tuple(again_mode.box or ()) != SOLO_BOX:
            msgs.append(f"复核后再次进入模式页却不能点了：box={again_mode.box!r}")

    # 反例：只给多人卡 ⇒ 不许点、不许判成模式页可点
    impl.reset_sessions()
    with fakes.FakeOcr(frame=MULTI_ONLY_FRAME), fakes.FakeClock(3100.0), fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        res = _solo(impl, ctx, 12202)
        detail = _detail(res)
        if res.box is not None:
            msgs.append(f"只给「多人游戏」的帧却给出可点框 {res.box!r} —— 必须不点")
        if detail.get("mode_page"):
            msgs.append("只给「多人游戏」的帧却被判成模式页（四段文案缺一段就不该认）")
        if detail.get("state") == nav.LORDS_STATE_MODE:
            msgs.append("只给「多人游戏」的帧 page_state 竟是 lords_mode")
    impl.reset_sessions()
    return msgs


def probe_lords_mode_solo_click() -> bool:
    """#100-4：点「单人游戏」的当帧框中心、点一次不重试、点完复核到编队页。"""
    return _mode_click_failures() == []


# ---------------------------------------------------------------------------
# 2b. ★缺口 7：复核只认正向证据（「点完 → 瞬时 unknown → 又回模式页」必须判失败）★
# ---------------------------------------------------------------------------
def _mode_verify_failures(impl=None, nav=None) -> list:
    """★复核 = 正向证据★：unknown 不算成功；回到模式页 = 点击没生效（旧判据会判成功）。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []

    # (a) 判据本身：编队页 = 挑战 + 三个锚之一；缺一半 / 别的页面都不算
    if nav.team_page_confirmed(UNKNOWN_FRAME):
        msgs.append("认不出的转场帧被判成编队页 —— 否定式判据（「不是模式页」）复活了")
    if not nav.team_page_confirmed(fakes.TEAM_FRAME):
        msgs.append("真机编队页帧（挑战 + 自动续战）没被 team_page_confirmed 确认")
    if nav.team_page_confirmed((("挑战", [297, 1069, 80, 47]),)):
        msgs.append("只有【挑战】、没有 SET/Party/自动续战 也被当成编队页 —— 正向证据缺了一半")
    if nav.team_anchor_hit(fakes.TEAM_FRAME) != "自动续战":
        msgs.append(
            f"编队页帧命中的锚 = {nav.team_anchor_hit(fakes.TEAM_FRAME)!r}，应为 '自动续战'"
        )

    # (b) 帧序列：点完 → 瞬时 unknown → 又回模式页 ⇒ 两次都**不是成功**
    task = 12251
    impl.reset_sessions()
    session = impl._session(task)
    session.mode_clicks = 1                       # 模拟「刚点过一下」
    got = impl._note_mode_result(session, nav.LORDS_STATE_UNKNOWN, nav, UNKNOWN_FRAME)
    if got != f"unconfirmed:{nav.LORDS_STATE_UNKNOWN}":
        msgs.append(
            f"瞬时 unknown 帧的复核结论 = {got!r}，应为 'unconfirmed:lords_unknown' —— "
            f"旧判据（'left_mode_page:...'）就是把它当成功（14:0x 的假成功）"
        )
    if session.mode_clicks != 1:
        msgs.append("瞬时 unknown 帧把点击账清了 —— 等于判成功（假成功）")
    got = impl._note_mode_result(session, nav.LORDS_STATE_MODE, nav, MODE_FRAME_A)
    if got != "still_mode":
        msgs.append(f"又回到模式页的复核结论 = {got!r}，应为 'still_mode'（点击没生效）")
    if session.mode_clicks != 1:
        msgs.append("回到模式页却把点击账清了 —— 下一轮不会再点，等于假成功")
    got = impl._note_mode_result(session, nav.LORDS_STATE_TEAM, nav, fakes.TEAM_FRAME)
    if got != "team_page":
        msgs.append(f"编队页帧的复核结论 = {got!r}，应为 'team_page'（正向证据）")
    if session.mode_clicks != 0:
        msgs.append("正向确认后没有清掉点击账 —— 下一轮再回到模式页就点不动了")

    # (c) 完整阶梯：点完 → unknown → 又回模式页 ×3 ⇒ 4 个点都试过，必须判失败
    impl.reset_sessions()
    task = 12252
    buf = io.StringIO()
    per_point = [UNKNOWN_FRAME, MODE_FRAME_A, MODE_FRAME_A, MODE_FRAME_A]
    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(13000.0), fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        res = _solo(impl, ctx, task)
        with _ladder_env(impl, per_point * 4) as calls, \
                contextlib.redirect_stdout(buf):
            ok = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        if ok:
            msgs.append("「点完 → 瞬时 unknown → 又回模式页」被判成了成功 —— 这正是 14:0x 的假成功")
        if len(calls) != 4:
            msgs.append(f"unknown→模式页 的序列只试了 {len(calls)} 个点，应为 4（{calls!r}）")
        detail = _detail(_solo(impl, ctx, task))
        if not detail.get("stop"):
            msgs.append("四个点都试过仍没到编队页，却没有收工（又回到「看起来在跑」）")
        reason = str(detail.get("reason") or "")
        if "4 个点都试过" not in reason:
            msgs.append(f"收工原因没带量（缺「4 个点都试过」）：{reason!r}")
        if not any(
            impl.STOP_NODE in [str(x) for x in (nxt or ())] for _name, nxt in ctx.overrides
        ):
            msgs.append(f"没有 override 到 {impl.STOP_NODE}：{ctx.overrides}")
    log = buf.getvalue()
    for needle in ("离开了模式页", "left_mode_page"):
        if needle in log:
            msgs.append(f"日志里出现了否定式判据 {needle!r} —— 旧判据复活")
    impl.reset_sessions()
    return msgs


def probe_lords_mode_positive_verify() -> bool:
    """#100-7：复核只认正向证据（unknown / 模式页都不算成功），否定式判据不许复活。"""
    return _mode_verify_failures() == []


# ---------------------------------------------------------------------------
# 2c. ★缺口 7：换点阶梯（中心无效 → 下方有效 = 2 个点；全无效 = 4 次后带量收工）★
# ---------------------------------------------------------------------------
def _mode_ladder_failures(impl=None, nav=None) -> list:
    """★换点阶梯：中心 → 下方100 → 右侧120 → 下方180；每点**轮询读帧**；有界 4 个点★。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []

    # (a) 阶梯数据 = 票面指定（顺序、偏移、轮询参数、次数、确认框）
    want_ladder = (("中心", 0, 0), ("下方", 0, 100), ("右侧", 120, 0), ("底部", 0, 180))
    if tuple(nav.LORDS_MODE_CLICK_LADDER) != want_ladder:
        msgs.append(
            f"换点阶梯 = {tuple(nav.LORDS_MODE_CLICK_LADDER)!r}，应为 {want_ladder!r}"
        )
    if int(nav.LORDS_MODE_MAX_ATTEMPTS) != 4:
        msgs.append(f"尝试上限 = {nav.LORDS_MODE_MAX_ATTEMPTS}，应为 4")
    interval = float(nav.LORDS_MODE_POLL_INTERVAL_SEC)
    timeout = float(nav.LORDS_MODE_POLL_TIMEOUT_SEC)
    if not 0.2 <= interval <= 0.5:
        msgs.append(f"轮询间隔 = {interval}s，票面要求 ~0.4s（每 0.4s 读一次）")
    if not 5.0 <= timeout <= 10.0:
        msgs.append(f"单点轮询窗口 = {timeout}s，票面要求最多 8s")
    if int(nav.LORDS_MODE_STABLE_READS) != 2 or int(nav.LORDS_MODE_STILL_MODE_READS) != 3:
        msgs.append(
            f"稳定读判定 = {nav.LORDS_MODE_STABLE_READS}/{nav.LORDS_MODE_STILL_MODE_READS}，"
            f"应为 2/3（一帧不算稳定；连续 3 帧模式页才算没生效）"
        )
    if tuple(nav.LORDS_MODE_BONUS_QUESTION_ANCHORS) != ("领主加成点数", "增加报酬"):
        msgs.append(
            f"确认框问题锚 = {tuple(nav.LORDS_MODE_BONUS_QUESTION_ANCHORS)!r}，"
            f"应为 ('领主加成点数', '增加报酬')"
        )
    if (
        nav.LORDS_MODE_BONUS_ACCEPT,
        nav.LORDS_MODE_BONUS_DECLINE,
        nav.LORDS_MODE_BONUS_CHOICE,
    ) != ("是", "否", "否"):
        msgs.append(
            f"确认框按钮 = {(nav.LORDS_MODE_BONUS_ACCEPT, nav.LORDS_MODE_BONUS_DECLINE, nav.LORDS_MODE_BONUS_CHOICE)!r}，"
            f"应为 ('是','否','否') —— 默认不消耗加成次数"
        )
    if int(nav.LORDS_MODE_MAX_DIALOG_CLICKS) != 1:
        msgs.append(f"确认框点击上限 = {nav.LORDS_MODE_MAX_DIALOG_CLICKS}，应为 1（它只该出现一次）")
    reason = nav.mode_click_exhausted_reason("lords_unknown", None)
    for needle in (
        "模式页点不出去",
        "单人游戏",
        "中心/下方/右侧/底部",
        "4 个点都试过",
        "不是编队页",
        "state=lords_unknown",
        "锚=None",
    ):
        if needle not in reason:
            msgs.append(f"收工文案缺 {needle!r}：{reason!r}")
    if "画面仍是模式页" in reason:
        msgs.append(
            f"收工文案还在写结论「画面仍是模式页」（应只写读数）：{reason!r}"
        )
    if tuple(nav.mode_click_points((0, 0, 0, 0))) or tuple(nav.mode_click_points(None)):
        msgs.append("无效框竟然还能算出换点阶梯 —— 会点出 (0,0) 盲点")

    base = _center(SOLO_BOX)
    want_points = [
        (base[0], base[1]),
        (base[0], base[1] + 100),
        (base[0] + 120, base[1]),
        (base[0], base[1] + 180),
    ]

    # (b) 中心无效、下方有效 ⇒ 2 个点、第 2 个成功、共 2 次点击（第 1 个点连续 3 帧模式页）
    impl.reset_sessions()
    task = 12261
    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(14000.0), fakes.FakeSleeper() as sleeper:
        ctx = fakes.FakeContext()
        res = _solo(impl, ctx, task)
        with _ladder_env(impl, [MODE_FRAME_A] * 3 + [fakes.TEAM_FRAME]) as calls:
            ok = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        if not ok:
            msgs.append("中心无效、下方有效：换点阶梯没有成功（应第 2 个点成功）")
        if len(calls) != 2:
            msgs.append(f"中心无效、下方有效：点了 {len(calls)} 次（应为 2：中心 + 下方）{calls!r}")
        for index, (got, exp) in enumerate(zip(calls, want_points[:2])):
            if abs(got[0] - exp[0]) > 1 or abs(got[1] - exp[1]) > 1:
                msgs.append(f"第 {index + 1} 个点 {got} != 期望 {exp}")
        if sleeper.calls.count(interval) != 4:
            msgs.append(
                f"两个点应该各轮询读帧（共 4 次 ×{interval:g}s）：sleeper={sleeper.calls!r}"
            )
        session = impl._session(task)
        if session.mode_clicks != 2:
            msgs.append(f"试了 2 个点但 mode_clicks = {session.mode_clicks}，应为 2")
        if not session.mode_verified:
            msgs.append("第 2 个点读到编队页却没有记下正向证据")
        if session.stage != impl.STAGE_TEAM:
            msgs.append(f"换点成功后 stage = {session.stage!r}，应为 {impl.STAGE_TEAM!r}")
        with _frame(impl, fakes.TEAM_FRAME):
            team_detail = _detail(_solo(impl, ctx, task))
        if team_detail.get("mode_verify") != "team_page":
            msgs.append(f"换点成功后复核 mode_verify = {team_detail.get('mode_verify')!r}，应为 'team_page'")
        if impl._session(task).mode_clicks != 0:
            msgs.append("换点成功后复核没有清掉点击账")

    # (c) 全无效 ⇒ 4 个点后收工且原因**只写读数**（含 state=lords_mode）
    impl.reset_sessions()
    task = 12262
    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(15000.0), fakes.FakeSleeper() as sleeper:
        ctx = fakes.FakeContext()
        res = _solo(impl, ctx, task)
        with _ladder_env(impl, [MODE_FRAME_A] * 12) as calls:
            ok = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        if ok:
            msgs.append("四个点全无效却返回了成功（假成功）")
        if len(calls) != 4:
            msgs.append(f"全无效时点了 {len(calls)} 次，应为 4（{calls!r}）")
        for index, (got, exp) in enumerate(zip(calls, want_points)):
            if abs(got[0] - exp[0]) > 1 or abs(got[1] - exp[1]) > 1:
                msgs.append(f"第 {index + 1} 个点 {got} != 期望 {exp}")
        if sleeper.calls.count(interval) != 12:
            msgs.append(
                f"四个点应该各轮询读帧（共 12 次 ×{interval:g}s）：sleeper={sleeper.calls!r}"
            )
        session = impl._session(task)
        if "4 个点都试过" not in session.mode_fail_reason:
            msgs.append(f"全无效后没有粘住带量收工理由：{session.mode_fail_reason!r}")
        if "state=lords_mode" not in session.mode_fail_reason:
            msgs.append(f"收工理由没写读数（缺 state=lords_mode）：{session.mode_fail_reason!r}")
        detail = _detail(_solo(impl, ctx, task))
        if not detail.get("stop"):
            msgs.append("四个点都试过仍没到编队页，却没有立刻收工")
        reason = str(detail.get("reason") or "")
        if "4 个点都试过" not in reason:
            msgs.append(f"收工原因缺「4 个点都试过」：{reason!r}")
        if "画面仍是模式页" in reason:
            msgs.append(f"收工原因还在写结论「画面仍是模式页」：{reason!r}")
        if not any(
            impl.STOP_NODE in [str(x) for x in (nxt or ())] for _name, nxt in ctx.overrides
        ):
            msgs.append(f"收工没有 override 到 {impl.STOP_NODE}：{ctx.overrides}")
    impl.reset_sessions()
    return msgs


def probe_lords_mode_click_ladder() -> bool:
    """#100-7/9：中心无效→下方有效 = 2 个点/2 次点击；全无效 = 4 个点后带读数收工。"""
    return _mode_ladder_failures() == []


# ---------------------------------------------------------------------------
# 2e. ★缺口 9（2026-10-18 夜真机 484）：点完「单人游戏」弹的是「加成点数」确认框★
# ---------------------------------------------------------------------------
def _bonus_dialog_failures(impl=None, nav=None) -> list:
    """★确认框：问题锚 + 「否」按钮框（当帧 OCR）→ 点「否」→ 继续轮询到编队页★。

    真机时间线（484）：点「单人游戏」+1.8s 弹框（是/否）→ 点「否」→ +3.9s 编队页。
    修前的固定 ``sleep(2.5)`` 读到的正是这个框（``lords_unknown``），随后换点阶梯全打在遮罩上。
    """
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []

    # (a) 判据：问题锚 + 「否」按钮框，缺一个都不是确认框
    dialog = nav.bonus_dialog(BONUS_DIALOG_FRAME)
    if not dialog.is_dialog:
        msgs.append(f"真机确认框帧没被判成确认框：{dialog.summary()}")
    if tuple(dialog.decline or ()) != (178, 805, 37, 37):
        msgs.append(f"「否」按钮框 = {dialog.decline!r}，应为真机 OCR 框 (178,805,37,37)")
    if tuple(dialog.accept or ()) != (504, 805, 36, 36):
        msgs.append(f"「是」按钮框 = {dialog.accept!r}，应为 (504,805,36,36)")
    if "领主加成点数" not in str(dialog.question or ""):
        msgs.append(f"确认框的问题原文没带上「领主加成点数」：{dialog.question!r}")
    if nav.bonus_dialog(BONUS_DIALOG_NO_DECLINE_FRAME).is_dialog:
        msgs.append("读不到「否」按钮框也被当成确认框 —— 接下来会盲点")
    if nav.bonus_dialog(UNKNOWN_FRAME).is_dialog or nav.bonus_dialog(MODE_FRAME_A).is_dialog:
        msgs.append("普通帧被当成加成确认框 —— 会把正常页面点掉")
    if dialog.decline_click_box != dialog.decline:
        msgs.append("decline_click_box 不等于当帧「否」框 —— 点击目标不是 OCR 框")

    # (b) 行为：点单人 → 读帧 1 = 确认框（点「否」）→ 读帧 2 = 编队页 ⇒ 成功
    impl.reset_sessions()
    task = 12281
    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(16000.0), fakes.FakeSleeper() as sleeper:
        ctx = fakes.FakeContext()
        res = _solo(impl, ctx, task)
        with _ladder_env(impl, [BONUS_DIALOG_FRAME, fakes.TEAM_FRAME]) as calls:
            ok = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        if not ok:
            msgs.append("确认框 → 点「否」→ 编队页 这一跳没有成功（会退回收工）")
        want = [_center(SOLO_BOX), _center(dialog.decline)]
        if len(calls) != 2:
            msgs.append(f"应点 2 下（单人卡 + 确认框「否」），实际 {len(calls)}：{calls!r}")
        for index, (got, exp) in enumerate(zip(calls, want)):
            if abs(got[0] - exp[0]) > 1 or abs(got[1] - exp[1]) > 1:
                msgs.append(f"第 {index + 1} 下点击 {got} != 期望 {exp}")
        session = impl._session(task)
        if session.mode_clicks != 1:
            msgs.append(f"确认框成功后 mode_clicks = {session.mode_clicks}，应为 1（只试了 1 个点）")
        if session.mode_dialog_clicks != 1:
            msgs.append(f"确认框点了 {session.mode_dialog_clicks} 次，应为 1")
        if session.attempts_since_read != 1:
            msgs.append(
                f"确认框那一下被记成又一次目标点击（attempts={session.attempts_since_read}）—— "
                f"同一次「模式→编队」跳只该记 1 次"
            )
        if not session.mode_verified or session.stage != impl.STAGE_TEAM:
            msgs.append("确认框后没有记下正向证据 / stage 不是 team")
        if sleeper.calls.count(float(nav.LORDS_MODE_POLL_INTERVAL_SEC)) != 2:
            msgs.append(f"确认框前后应各轮询读帧（共 2 次 ×0.4s）：sleeper={sleeper.calls!r}")

        # ★点击目标来自当帧 OCR 框（不是写死坐标）★：把「否」按钮挪 +40/+30px，点击必须跟着走
        impl.reset_sessions()
        task2 = 12282
        shifted = nav.bonus_dialog(BONUS_DIALOG_SHIFTED_FRAME)
        if not shifted.is_dialog:
            msgs.append("挪过位置的确认框帧没被认出来（问题锚不该依赖按钮位置）")
        with _ladder_env(impl, [BONUS_DIALOG_SHIFTED_FRAME, fakes.TEAM_FRAME]) as calls2:
            res2 = _solo(impl, ctx, task2)
            ok2 = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task2, box=res2.box))
        exp2 = _center(shifted.decline)
        if not ok2:
            msgs.append("挪过位置的确认框：这一跳没有成功")
        if len(calls2) != 2 or abs(calls2[1][0] - exp2[0]) > 1 or abs(calls2[1][1] - exp2[1]) > 1:
            msgs.append(
                f"确认框换位置后点击没跟着当帧 OCR 框走（期望 {exp2}，实际 {calls2!r}）—— 坐标被写死了"
            )

    # (c) 残留确认框：mode=solo 识别必须命中它（what=WHAT_MODE_CONFIRM），动作只点一下那个框
    impl.reset_sessions()
    task3 = 12283
    with fakes.FakeOcr(frame=BONUS_DIALOG_FRAME), fakes.FakeClock(17000.0):
        ctx = fakes.FakeContext()
        res3 = _solo(impl, ctx, task3)
        detail3 = _detail(res3)
        if res3.box is None or tuple(res3.box) != dialog.decline:
            msgs.append(f"残留确认框帧上 mode=solo 没给出「否」框：box={res3.box!r}")
        if detail3.get("what") != impl.WHAT_MODE_CONFIRM:
            msgs.append(f"残留确认框的 detail.what = {detail3.get('what')!r}，应为 WHAT_MODE_CONFIRM")
        with _ladder_env(impl, [], calls=[]) as calls3:
            ok3 = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task3, box=res3.box))
        if not ok3:
            msgs.append("残留确认框：动作没有点成「否」")
        if len(calls3) != 1 or abs(calls3[0][0] - _center(dialog.decline)[0]) > 1:
            msgs.append(f"残留确认框：应只点 1 下「否」框中心，实际 {calls3!r}")
    # (d) 确认框「否」点击派发失败 ⇒ 同一个确认框只尝试 1 次（不连点），并带原因超时
    impl.reset_sessions()
    session = impl._session(12284)
    attempts: list = []
    saved_click, saved_read = impl._click_hook, impl._read_items_hook
    impl._click_hook = lambda c, x, y: (attempts.append((x, y)), False)[1]
    impl._read_items_hook = lambda c, entry=None: list(BONUS_DIALOG_FRAME)
    try:
        verdict, st, anchor, note, declined = impl.LordsUnlockAction()._watch_mode_click(
            fakes.FakeContext(), nav, session, 0, 1, "中心"
        )
    finally:
        impl._click_hook, impl._read_items_hook = saved_click, saved_read
    if len(attempts) != 1:
        msgs.append(f"确认框「否」派发失败后又被连点了 {len(attempts)} 次（应为 1）")
    if verdict != "timeout" or declined:
        msgs.append(f"确认框点失败却判了 {verdict!r}（应 timeout / declined=False）")
    if "不盲点/不连点" not in note:
        msgs.append(f"确认框点失败的 note 没写清楚：{note!r}")
    impl.reset_sessions()
    return msgs


def probe_lords_mode_bonus_dialog() -> bool:
    """#100-9：加成点数确认框（问题锚 + 「否」按钮当帧框）→ 点否 → 轮询到编队页；有界。"""
    return _bonus_dialog_failures() == []


# ---------------------------------------------------------------------------
# 2f. ★缺口 9：pick 空转诊断（限流）—— 卡住时一眼看出卡在哪★
# ---------------------------------------------------------------------------
def _pick_diag_failures(impl=None) -> list:
    """★诊断必须带读数 + 限流★：同一原因只在第 1/6/11… 轮打印；状态一变立刻打印。"""
    impl = _impl() if impl is None else impl
    fakes = _fakes()
    msgs: list = []

    # (a) 限流函数本身
    impl.reset_sessions()
    session = impl._session(12291)
    key = ("lords_unknown", False, "team")
    printed = [i for i in range(1, 13) if impl._pick_diag_once(session, key, "same-line")]
    if printed != [1, 6, 11]:
        msgs.append(f"同一原因连续 12 轮只该在第 1/6/11 轮打印，实际 {printed}")
    if not impl._pick_diag_once(session, ("lords_mode", True, "team"), "changed"):
        msgs.append("页面状态变了却吞掉了 pick 空转诊断（降噪不许盖掉「页面变了」）")

    # (b) 真实 _pick 空转：行里必须带 state / 行框 / stage / attempts；连续两轮只打一行
    impl.reset_sessions()
    task = 12292
    lu = fakes._lords_unlock()
    ctx = fakes.FakeContext()
    argv = fakes.FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget")
    reco = impl.LordsProgressRecognition()
    # ★注意：FakeOcr 进入时会 reset_sessions★，所以 targets 必须在 with 里面设。
    with fakes.FakeOcr(frame=UNKNOWN_FRAME), fakes.FakeClock(18000.0):
        impl._session(task).targets = [lu.Target("妖狐讨伐", None, 0, 4)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reco.analyze(ctx, argv)
            reco.analyze(ctx, argv)
        first = buf.getvalue()
        count = first.count("pick 空转诊断")
        if count != 1:
            msgs.append(f"同一个空转原因连续两轮应只打 1 行，实际 {count} 行：{first!r}")
        for needle in ("state=lords_unknown", "行框=None", "stage=", "attempts=", "pending="):
            if needle not in first:
                msgs.append(f"空转诊断缺 {needle!r}（真机卡住时要一眼看出卡在哪）：{first!r}")

        # 同一原因第 6 轮（第 5 次重复）必须再给一行心跳
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            for _ in range(4):
                reco.analyze(ctx, argv)
        if buf2.getvalue().count("pick 空转诊断") != 1:
            msgs.append(
                f"同一原因第 6 轮应给一行心跳（每 5 轮一次），实际 {buf2.getvalue()!r}"
            )
    impl.reset_sessions()
    return msgs


def probe_lords_pick_diag_rate_limit() -> bool:
    """#100-9：pick 空转诊断带读数且限流（状态变化才打 / 同一原因每 5 轮一次）。"""
    return _pick_diag_failures() == []


# ---------------------------------------------------------------------------
# 2d. ★缺口 8：框无效（缺失 / 尺寸 0 / 中心 (0,0)）⇒ 点击函数不被调用★
# ---------------------------------------------------------------------------
def _click_guard_failures(impl=None, nav=None) -> list:
    """★绝不允许 ``点页签 @720(0,0)``★：无效框必须拒绝点击并打日志；有效框照旧。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    rects = _rect_fakes()
    msgs: list = []
    action = impl.LordsUnlockAction()
    task = 12271

    def _run_case(label: str, box, *, mode: bool = False, do_tab: bool = False):
        impl.reset_sessions()
        calls: list = []
        saved = impl._click_hook
        impl._click_hook = lambda _c, x, y: (calls.append((x, y)), True)[1]
        logs = io.StringIO()
        try:
            with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(16000.0), \
                    fakes.FakeSleeper(), contextlib.redirect_stdout(logs):
                ctx = fakes.FakeContext()
                session = impl._session(task)
                if mode:
                    session.pending = impl.ClickStep(box, impl.WHAT_MODE, impl.STAGE_TEAM)
                if do_tab:
                    ok = action._tab_click(
                        ctx, fakes.FakeArgv(task_id=task, box=box), session
                    )
                else:
                    ok = action.run(ctx, fakes.FakeArgv(task_id=task, box=box))
        finally:
            impl._click_hook = saved
        if ok:
            msgs.append(f"{label}：框无效却返回成功")
        if calls:
            msgs.append(f"{label}：框无效却调用了点击 {calls!r} —— 盲点 (0,0) 复活")
        if "拒绝点击" not in logs.getvalue():
            msgs.append(f"{label}：拒绝点击时没有打日志（现场查不到为什么没点）")
        return ctx

    _run_case("box=[0,0,0,0]", (0, 0, 0, 0))
    _run_case("box 缺失", None)
    _run_case("零尺寸 Rect(0,0,0,0)", rects.FakeRect(0, 0, 0, 0))
    _run_case("what=mode + box=[0,0,0,0]", (0, 0, 0, 0), mode=True)
    _run_case("do=tab + box=[0,0,0,0]", (0, 0, 0, 0), do_tab=True)

    # 对照：有效框仍然点（框闸不许过宽 —— 那会把正常页签也挡掉）
    impl.reset_sessions()
    calls = []
    saved = impl._click_hook
    impl._click_hook = lambda _c, x, y: (calls.append((x, y)), True)[1]
    try:
        ok = action._tab_click(
            fakes.FakeContext(), fakes.FakeArgv(task_id=task, box=SOLO_BOX), impl._session(task)
        )
    finally:
        impl._click_hook = saved
    if not ok or len(calls) != 1:
        msgs.append(f"有效框竟被框闸挡住（ok={ok!r} calls={calls!r}）—— 闸过宽")
    if calls and tuple(calls[0]) != _center(SOLO_BOX):
        msgs.append(f"有效框的点击中心 = {calls[0]!r}，应为 {_center(SOLO_BOX)!r}")

    # ★收工命中（识别 override 到 LordsStop）⇒ 动作必须「成功但不点」★：
    # 返回 False 会走 on_error 回枢纽，覆盖的 next 作废 → 收工在枢纽里无限重来。
    # 修前收工节点的动作靠「点 (0,0) 返回 True」混过去（正是 #100 缺口 8 的盲点）。
    impl.reset_sessions()
    task = 12272
    stop_calls: list = []
    saved = impl._click_hook
    impl._click_hook = lambda _c, x, y: (stop_calls.append((x, y)), True)[1]
    try:
        with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(17000.0) as clock, fakes.FakeSleeper():
            ctx = fakes.FakeContext()
            _tab(impl, ctx, task)
            clock.advance(float(nav.NON_LIST_STUCK_SEC) + 1.0)
            stop_detail = _detail(_tab(impl, ctx, task))
            if not stop_detail.get("stop"):
                msgs.append("非列表页超过死线却没有判收工（前置条件不成立）")
            session = impl._session(task)
            if not impl._is_stop_requested(session):
                msgs.append(
                    "判了收工却没有置 stop_requested —— 收工节点的动作会失败并走 on_error 回枢纽"
                )
            ok = action.run(ctx, fakes.FakeArgv(task_id=task, box=(0, 0, 0, 0)))
    finally:
        impl._click_hook = saved
    if not ok:
        msgs.append(
            "收工后动作返回 False —— 框架会走 on_error 回枢纽，override 的 LordsStop 作废"
            "（收工在枢纽里无限重来）"
        )
    if stop_calls:
        msgs.append(f"收工后动作还点了一下 {stop_calls!r} —— 收工必须是「成功但不点」")
    impl.reset_sessions()
    return msgs


def probe_lords_click_no_blind_point() -> bool:
    """#100-8：框缺失 / 尺寸 0 / 中心 (0,0) ⇒ 点击函数不被调用；有效框照旧点。"""
    return _click_guard_failures() == []


# ---------------------------------------------------------------------------
# 3. 降噪（同一原因连续命中只打印一次）
# ---------------------------------------------------------------------------
def _noise_failures(impl=None) -> list:
    """★同一 (页面状态, 那一行) 连续命中只打印一次★：注入 print 捕获计数。"""
    impl = _impl() if impl is None else impl
    fakes = _fakes()
    msgs: list = []
    task = 12211
    impl.reset_sessions()

    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(4000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for _ in range(6):
                _tab(impl, ctx, task)
                clock.advance(0.1)
        out = buf.getvalue()
        count = out.count("页签：cannot")
        if count != 1:
            msgs.append(
                f"同一非列表页上「页签：cannot」打印了 {count} 次（应为 1）—— "
                f"每帧一行会把长跑日志淹掉（#100 第 5 个缺口）"
            )
        if "lords_mode" not in out:
            msgs.append(f"降噪后的那一行没有带页面状态名：{out!r}")

        # 页面状态变了 ⇒ 允许再打一次（「页面变了」本身是信息）
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), _frame(impl, fakes.DETAIL_FRAME):
            _tab(impl, ctx, task)
        out2 = buf.getvalue()
        if out2.count("页签：cannot") != 1:
            msgs.append(f"换了页面（lords_mode → lords_detail）却打了 {out2.count('页签：cannot')} 次，应为 1")
        if "lords_detail" not in out2:
            msgs.append(f"换页后的那一行没有带新状态名：{out2!r}")

    # 判据本身（可注入的坏实现入口）：同一 (state, line) 第二次必须被吞
    session = impl.Session(task_id=12212)
    first = impl._tab_log_once(session, "lords_mode", "same-line")
    second = impl._tab_log_once(session, "lords_mode", "same-line")
    third = impl._tab_log_once(session, "lords_detail", "same-line")
    if not (first and not second and third):
        msgs.append(f"_tab_log_once 去重口径不对：{first}/{second}/{third}（期望 True/False/True）")
    impl.reset_sessions()
    return msgs


def probe_lords_non_list_noise() -> bool:
    """#100-5：同一原因连续命中只打印一次（页面状态一变才允许再打）。"""
    return _noise_failures() == []


# ---------------------------------------------------------------------------
# 4. 有界出口（非列表页 K 秒无状态变化 ⇒ 收工且原因带状态名）
# ---------------------------------------------------------------------------
def _bound_failures(impl=None, nav=None) -> list:
    """★非列表页 K 秒无状态变化 ⇒ 收工，原因带状态名★；列表页不走这条死线。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []

    # (a) 常量：票面给 8–10s；9 = 区间内
    if not (8.0 <= float(nav.NON_LIST_STUCK_SEC) <= 10.0):
        msgs.append(
            f"NON_LIST_STUCK_SEC = {nav.NON_LIST_STUCK_SEC} 不在票面的 8–10s 区间内"
        )
    reason_tmpl = nav.non_list_stuck_reason("lords_mode", float(nav.NON_LIST_STUCK_SEC))
    for needle in ("收工", "卡在「lords_mode」", "非列表页", "无法导航"):
        if needle not in reason_tmpl:
            msgs.append(f"死线文案缺 {needle!r}：{reason_tmpl!r}")

    # (b) 模式页：状态名不变 ≥K ⇒ 收工
    task = 12221
    impl.reset_sessions()
    with fakes.FakeOcr(frame=MODE_FRAME_A), fakes.FakeClock(5000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        first = _tab(impl, ctx, task)
        if _detail(first).get("stop"):
            msgs.append("刚进非列表页就收工 —— 死线没等够时间")
        clock.advance(float(nav.NON_LIST_STUCK_SEC) - 0.5)
        before = _tab(impl, ctx, task)
        if _detail(before).get("stop"):
            msgs.append("还没到 K 秒就收工 —— 死线提前了")
        clock.advance(1.0)
        over = _tab(impl, ctx, task)
        detail = _detail(over)
        if not detail.get("stop"):
            msgs.append("非列表页状态名不变超过 K 秒却没收工 —— 又是「看起来在跑」")
        else:
            reason = str(detail.get("reason") or "")
            if "lords_mode" not in reason:
                msgs.append(f"收工原因没带状态名：{reason!r}")
            if "非列表页" not in reason or "无法导航" not in reason:
                msgs.append(f"收工原因没说清「非列表页、无法导航」：{reason!r}")
            if "wuchong" in reason.lower():
                msgs.append(f"收工原因里出现了别的场景的状态名：{reason!r}")
            if not any(
                impl.STOP_NODE in [str(x) for x in (nxt or ())] for _name, nxt in ctx.overrides
            ):
                msgs.append(f"收工没有 override 到 {impl.STOP_NODE}：{ctx.overrides}")

    # (c) 详情页卡住也走同一条（状态名各自带出来）
    task = 12222
    impl.reset_sessions()
    with fakes.FakeOcr(frame=fakes.DETAIL_FRAME), fakes.FakeClock(6000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        _tab(impl, ctx, task)
        clock.advance(float(nav.NON_LIST_STUCK_SEC) + 1.0)
        detail = _detail(_tab(impl, ctx, task))
        if not detail.get("stop"):
            msgs.append("详情页状态名不变超过 K 秒却没收工")
        elif "lords_detail" not in str(detail.get("reason") or ""):
            msgs.append(f"详情页的收工原因没带状态名 lords_detail：{detail.get('reason')!r}")

    # (d) 列表页**不走**这条死线（K < NAV_STUCK_SEC，所以这段时间里它不能收工）
    task = 12223
    impl.reset_sessions()
    with fakes.FakeOcr(frame=fakes.LIST_FRAME), fakes.FakeClock(7000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        _tab(impl, ctx, task)
        clock.advance(float(nav.NON_LIST_STUCK_SEC) + 0.5)
        detail = _detail(_tab(impl, ctx, task))
        if detail.get("stop"):
            msgs.append(
                f"列表页被非列表页死线误判收工（reason={detail.get('reason')!r}）—— "
                f"列表页有自己的 NAV_STUCK_SEC"
            )
    impl.reset_sessions()
    return msgs


def probe_lords_non_list_bound() -> bool:
    """#100-5：非列表页 K 秒无状态变化 ⇒ 带原因收工（原因含状态名）；列表页不误判。"""
    return _bound_failures() == []


# ---------------------------------------------------------------------------
# 4b. ★过渡态（加载 / 过场）不许累加「无进展」计时★（真机 484，14:5x 的误杀）
# ---------------------------------------------------------------------------
def _tab_read(impl, ctx, task: int, frame) -> dict:
    """换一帧读一次 ``mode=tab``，返回 detail（只换 ``_ocr``，**不重置会话**）。"""
    with _frame(impl, frame):
        return _detail(_tab(impl, ctx, task))


def _transition_failures(impl=None, nav=None) -> list:
    """★过渡态不许被「非列表页死线」收工★：loading 帧不累加、且**重置**计时。

    真机现场（484，14:5x）：``--home`` 把设备送回主城后**立刻**跑 ``--trace LordsEntry``，
    日志 ``state=lords_unknown`` 连续 ~10s → 收工；随后手工 ``screencap``：设备好好地在主城
    （活动 / 主城 / 关卡 / 领主战 / 菜单 全部可见）。
    ⇒ 死线在**启动瞬间的过渡帧**上触发了 —— 任务还没开始就被判死。

    ★但放行的只能是真的过渡态★：``lords_unknown`` 必须留在死线里（挂点 11 抓「放行过头」）。
    """
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []
    threshold = float(nav.NON_LIST_STUCK_SEC)

    # (a) 数据：过渡态 = lords 自己的加载页 + 共享层的裸名；★lords_unknown / lords_list 绝不入列★
    transition = tuple(getattr(nav, "LORDS_TRANSITION_STATES", ()) or ())
    if str(getattr(nav, "LORDS_STATE_LOADING", "")) != "lords_loading":
        msgs.append(
            f"LORDS_STATE_LOADING = {getattr(nav, 'LORDS_STATE_LOADING', None)!r} != 'lords_loading' —— "
            f"过渡态必须有自己的名字（否则加载帧只能落进 lords_unknown）"
        )
    if nav.LORDS_STATE_LOADING not in transition:
        msgs.append(
            f"LORDS_TRANSITION_STATES = {transition!r} 里没有 {nav.LORDS_STATE_LOADING!r} —— "
            f"加载帧会重新累加「没有进展」（14:5x 的误杀复活）"
        )
    for bare in ("loading", "relogin"):
        if bare not in transition:
            msgs.append(
                f"LORDS_TRANSITION_STATES 里没有共享层的过渡名 {bare!r}：{transition!r} —— "
                f"它从共享层漏进来时必须按过渡处理（宁可晚收工，不可误杀刚回主城的任务）"
            )
    for label, bad in (
        ("lords_unknown（未知画面）", nav.LORDS_STATE_UNKNOWN),
        ("lords_list（列表页）", nav.LORDS_STATE_LIST),
    ):
        if bad in transition:
            msgs.append(f"★{label} 混进了过渡态集合★：{transition!r} —— 那条死线就再也不会触发了")
    for name in (nav.LORDS_STATE_BATTLE, nav.LORDS_STATE_SETTLE):
        if name in transition:
            msgs.append(f"{name!r} 混进了过渡态集合 —— 战斗/结算有自己的整类排除（LORDS_ACTIVE_STATES）")
    if nav.LORDS_STATE_LOADING not in nav.LORDS_STATES:
        msgs.append(
            f"LORDS_STATE_LOADING 不在 LORDS_STATES 里 —— page_state 不可能返回它（词表：{nav.LORDS_STATES!r}）"
        )
    if nav.LORDS_STATE_LOADING in nav.LORDS_ACTIVE_STATES:
        msgs.append(
            "加载页混进了 LORDS_ACTIVE_STATES —— 那是「战斗/结算」的整类排除，"
            "过渡态有自己的一套（LORDS_TRANSITION_STATES）"
        )

    # (b) 判据：加载帧 = lords_loading（子串锚定，带百分比的帧也算）；认不出的帧仍是 lords_unknown
    for label, frame in (("加载页", LOADING_FRAME), ("加载页（带百分比）", LOADING_FRAME_PCT)):
        got = str(nav.page_state(frame))
        if got != nav.LORDS_STATE_LOADING:
            msgs.append(
                f"{label}的 page_state = {got!r}，应为 {nav.LORDS_STATE_LOADING!r} —— "
                f"过渡帧必须先有自己的名字，才谈得上「不累加计时」"
            )
    got = str(nav.page_state(UNKNOWN_FRAME))
    if got != nav.LORDS_STATE_UNKNOWN:
        msgs.append(f"认不出的转场帧 page_state = {got!r}，应为 {nav.LORDS_STATE_UNKNOWN!r}（不猜）")

    # (c) 票面点名的序列：lords_unknown(2s) → loading(3s) → lords_unknown(2s) ⇒ **不许**收工
    task = 12281
    impl.reset_sessions()
    with fakes.FakeOcr(frame=UNKNOWN_FRAME), fakes.FakeClock(18000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        first = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        clock.advance(2.0)
        second = _tab_read(impl, ctx, task, LOADING_FRAME)
        clock.advance(3.0)
        third = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        clock.advance(2.0)
        fourth = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        for label, detail in (
            ("unknown(2s)", first),
            ("loading(3s)", second),
            ("回到 unknown", third),
            ("unknown 再 2s", fourth),
        ):
            if detail.get("stop"):
                msgs.append(
                    f"过渡帧序列里 {label} 被收工了：{detail.get('reason')!r} —— "
                    f"刚回主城的 loading 帧不许判死（任务还没开始）"
                )
        if str(first.get("state")) != nav.LORDS_STATE_UNKNOWN:
            msgs.append(f"序列起点 state = {first.get('state')!r}，应为 lords_unknown")
        if str(second.get("state")) != nav.LORDS_STATE_LOADING:
            msgs.append(
                f"加载帧的 state = {second.get('state')!r}，应为 {nav.LORDS_STATE_LOADING!r}"
            )

        # (d) 连续 15s 的加载帧（≫ 死线）⇒ 仍不许收工（★这条才是「过渡集」的判据★）
        clock.advance(30.0)
        for index in range(6):
            detail = _tab_read(impl, ctx, task, LOADING_FRAME)
            if detail.get("stop"):
                msgs.append(
                    f"连续 loading {3 * index}s 后判了收工：{detail.get('reason')!r} —— "
                    f"刚回主城/过场可以久到几十秒，过渡态不许累加「没有进展」"
                )
                break
            if str(detail.get("state")) != nav.LORDS_STATE_LOADING:
                msgs.append(f"加载页第 {index} 圈的 state = {detail.get('state')!r}，应为 lords_loading")
                break
            clock.advance(3.0)

    # (e) 计时被**重置**（不是只「跳过这一帧」）：unknown 8s → loading → unknown 8s ⇒ 不收工
    task = 12283
    impl.reset_sessions()
    with fakes.FakeOcr(frame=UNKNOWN_FRAME), fakes.FakeClock(20000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        _tab_read(impl, ctx, task, UNKNOWN_FRAME)                     # 起点
        clock.advance(threshold - 1.0)                                # 8s（还差 1s 到线）
        before = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        if before.get("stop"):
            msgs.append("还没到死线就收工了（(e) 的前置条件不成立）")
        clock.advance(1.0)                                            # 9s：正好到线
        loading = _tab_read(impl, ctx, task, LOADING_FRAME)            # 过渡态打断（必须救回来）
        if loading.get("stop"):
            msgs.append("正好卡在死线上读到的过渡帧被收工了 —— 过渡态连「到线那一帧」都要算数")
        clock.advance(threshold - 1.0)                                # 过渡后再 8s
        after = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        if after.get("stop"):
            msgs.append(
                "过渡态之后又把「过渡前攒的秒数」算进去了（8s + 8s ≥ 死线）—— "
                "过渡态必须**重置**计时（non_list_state 清空），不是只跳过那一帧"
            )
    impl.reset_sessions()
    return msgs


def probe_lords_transition_not_stuck() -> bool:
    """★过渡态不累加「无进展」计时★：loading 帧不判死、且重置计时；unknown 仍是自己的状态。"""
    return _transition_failures() == []


# ---------------------------------------------------------------------------
# 5b. ★未知画面的死线必须保留★（证明上面没有放行过头）
# ---------------------------------------------------------------------------
def _unknown_bound_failures(impl=None, nav=None) -> list:
    """★``lords_unknown`` 连续 12s（没有 loading 打断）⇒ **必须**收工★；战斗/结算仍不触发。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []
    threshold = float(nav.NON_LIST_STUCK_SEC)
    transition = tuple(getattr(nav, "LORDS_TRANSITION_STATES", ()) or ())

    # (a) 数据：未知画面与列表页都不在过渡集里
    if nav.LORDS_STATE_UNKNOWN in transition:
        msgs.append(
            f"★lords_unknown 被当成了过渡态★（{transition!r}）—— 认不出的画面就永远没有有界出口了，"
            f"「看起来在跑」的兜底被拆掉"
        )
    if nav.LORDS_STATE_LIST in transition:
        msgs.append(f"lords_list 混进了过渡态集合：{transition!r} —— 列表页有自己的 NAV_STUCK_SEC")

    # (b) unknown 连续 12s（★没有 loading 打断★）⇒ 死线照旧收工，原因带状态名
    task = 12291
    impl.reset_sessions()
    with fakes.FakeOcr(frame=UNKNOWN_FRAME), fakes.FakeClock(21000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        _tab_read(impl, ctx, task, UNKNOWN_FRAME)                     # 起点
        clock.advance(threshold - 1.0)                                # 8s
        early = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        if early.get("stop"):
            msgs.append("未知画面还没到死线就收工 —— 死线提前了")
        clock.advance(4.0)                                            # 累计 12s
        over = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        if not over.get("stop"):
            msgs.append(
                f"lords_unknown 连续 ~12s（没有 loading 打断）却没收工 —— "
                f"过渡态的放行范围过宽，真正的未知画面没人管了"
            )
        else:
            reason = str(over.get("reason") or "")
            for needle in (nav.LORDS_STATE_UNKNOWN, "非列表页", "无法导航"):
                if needle not in reason:
                    msgs.append(f"收工原因缺 {needle!r}：{reason!r}")
            if not any(
                impl.STOP_NODE in [str(x) for x in (nxt or ())] for _name, nxt in ctx.overrides
            ):
                msgs.append(f"收工没有 override 到 {impl.STOP_NODE}：{ctx.overrides}")
        clock.advance(1.0)                                            # 累计 13s
        later = _tab_read(impl, ctx, task, UNKNOWN_FRAME)
        if not later.get("stop"):
            msgs.append("超过死线后又「放过」了未知画面 —— 死线必须一直成立，不是只响一次")

    # (c) ③ 回归：battle / settle 仍不触发（LORDS_ACTIVE_STATES 的既有排除不许动）
    task = 12292
    impl.reset_sessions()
    with fakes.FakeOcr(frame=BATTLE_FRAME), fakes.FakeClock(22000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        for index in range(3):                                        # 长战斗：3 圈 × 20s
            detail = _tab_read(impl, ctx, task, BATTLE_FRAME)
            if detail.get("stop"):
                msgs.append(
                    f"战斗第 {index} 圈被收工了：{detail.get('reason')!r} —— 会打断正常战斗"
                )
            if str(detail.get("state")) != nav.LORDS_STATE_BATTLE:
                msgs.append(f"战斗帧第 {index} 圈 state = {detail.get('state')!r}，应为 lords_battle")
            clock.advance(20.0)
        settle = _tab_read(impl, ctx, task, SETTLE_FRAME)
        if settle.get("stop"):
            msgs.append(f"结算帧被收工了：{settle.get('reason')!r} —— 正常的结算不许被打断")
        if str(settle.get("state")) != nav.LORDS_STATE_SETTLE:
            msgs.append(f"结算帧 state = {settle.get('state')!r}，应为 lords_settle")
    if tuple(nav.LORDS_ACTIVE_STATES) != (nav.LORDS_STATE_BATTLE, nav.LORDS_STATE_SETTLE):
        msgs.append(
            f"LORDS_ACTIVE_STATES = {nav.LORDS_ACTIVE_STATES!r} 被改了 —— 战斗/结算的整类排除不许动"
        )
    if set(transition) & set(nav.LORDS_ACTIVE_STATES):
        msgs.append(
            f"过渡态集合与 LORDS_ACTIVE_STATES 相交（{set(transition) & set(nav.LORDS_ACTIVE_STATES)}）—— "
            f"两套排除口径混在一起就说不清是谁在放行"
        )
    impl.reset_sessions()
    return msgs


def probe_lords_unknown_still_bounded() -> bool:
    """★未知画面的死线仍在★：unknown 连续 12s ⇒ 收工；battle / settle 仍不触发（回归）。"""
    return _unknown_bound_failures() == []


# ---------------------------------------------------------------------------
# 5. 战斗 / 结算不许被这条死线打断
# ---------------------------------------------------------------------------
def _active_failures(impl=None, nav=None) -> list:
    """★battle → settle → battle 序列（以及长战斗）不许触发非列表页死线★。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []
    task = 12231
    impl.reset_sessions()

    with fakes.FakeOcr(frame=BATTLE_FRAME), fakes.FakeClock(8000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        # 长战斗：同一帧、状态名一直是 lords_battle —— 绝不能收工（一场仗打几分钟是正常的）
        for index in range(4):
            detail = _detail(_tab(impl, ctx, task))
            if detail.get("state") != nav.LORDS_STATE_BATTLE:
                msgs.append(f"战斗帧第 {index} 圈 state = {detail.get('state')!r}，应为 lords_battle")
            if detail.get("stop"):
                msgs.append(f"战斗第 {index} 圈被收工了：{detail.get('reason')!r} —— 会打断正常战斗")
            clock.advance(45.0)

        # battle → settle → battle（票面点名的序列）
        for label, frame, want in (
            ("settle", SETTLE_FRAME, nav.LORDS_STATE_SETTLE),
            ("battle", BATTLE_FRAME, nav.LORDS_STATE_BATTLE),
            ("settle", SETTLE_FRAME, nav.LORDS_STATE_SETTLE),
        ):
            with _frame(impl, frame):
                detail = _detail(_tab(impl, ctx, task))
            if detail.get("state") != want:
                msgs.append(f"序列里的 {label} 帧 state = {detail.get('state')!r}，应为 {want!r}")
            if detail.get("stop"):
                msgs.append(
                    f"序列里的 {label} 帧被收工了：{detail.get('reason')!r} —— "
                    f"正常的战斗/结算不许被打断"
                )
            clock.advance(45.0)

    # 点过【挑战】、这一场还没结束的编队页/加载页同样不许被打断
    impl.reset_sessions()
    with fakes.FakeOcr(frame=fakes.TEAM_FRAME), fakes.FakeClock(9000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        session = impl._session(task)
        session.challenge_pending = True
        session.challenge_clicked_at = clock.now
        _tab(impl, ctx, task)
        clock.advance(60.0)
        detail = _detail(_tab(impl, ctx, task))
        if detail.get("stop"):
            msgs.append(f"点过【挑战】后的等待页被收工了：{detail.get('reason')!r}")
    impl.reset_sessions()
    return msgs


def probe_lords_active_not_cut() -> bool:
    """#100-5：battle/settle（以及点过挑战后的等待）不会被非列表页死线误判。"""
    return _active_failures() == []


# ---------------------------------------------------------------------------
# 6. 安装态快照 == 真源（数据 + 判据表 + 同一批帧的行为）
# ---------------------------------------------------------------------------
#: 必须逐项相等的常量（= ``scene/lords_nav`` 的页面状态 / 模式页 / 死线）。
STATE_PARITY_FIELDS: tuple = (
    "LORDS_STATE_CITY",
    "LORDS_STATE_LIST",
    "LORDS_STATE_DETAIL",
    "LORDS_STATE_TEAM",
    "LORDS_STATE_MODE",
    "LORDS_STATE_BATTLE",
    "LORDS_STATE_SETTLE",
    # ★#100 补充（真机 484，14:5x）★：过渡态（loading）与它的判据/集合
    "LORDS_STATE_LOADING",
    "LORDS_STATE_UNKNOWN",
    "LORDS_STATES",
    "LORDS_ACTIVE_STATES",
    "LORDS_LOADING_ANCHORS",
    "LORDS_TRANSITION_STATES",
    "LORDS_MODE_SOLO",
    "LORDS_MODE_SOLO_NOTE",
    "LORDS_MODE_MULTI",
    "LORDS_MODE_MULTI_NOTE",
    "LORDS_MODE_SOLO_ROI",
    "LORDS_MODE_MULTI_ROI",
    "LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY",
    "LORDS_MODE_MAX_ATTEMPTS",
    "LORDS_MODE_CONFIRM_GRACE_SEC",
    # ★#100 缺口 7/8★：编队页正向锚 + 换点阶梯（数据必须与真源逐项相等）
    "LORDS_TEAM_ANCHORS",
    "LORDS_MODE_CLICK_LADDER",
    "LORDS_MODE_CLICK_WAIT_SEC",
    # ★#100 第 9 个真机缺口（2026-10-18 夜）★：轮询读帧 + 加成点数确认框
    "LORDS_MODE_POLL_INTERVAL_SEC",
    "LORDS_MODE_POLL_TIMEOUT_SEC",
    "LORDS_MODE_STABLE_READS",
    "LORDS_MODE_STILL_MODE_READS",
    "LORDS_MODE_BONUS_QUESTION_ANCHORS",
    "LORDS_MODE_BONUS_ACCEPT",
    "LORDS_MODE_BONUS_DECLINE",
    "LORDS_MODE_BONUS_CHOICE",
    "LORDS_MODE_MAX_DIALOG_CLICKS",
    "LORDS_PAGE_RULE_NAMES",
    "LORDS_PAGE_RULES",
    "NON_LIST_STUCK_SEC",
    "NON_LIST_STUCK_REASON",
)


def _state_scenario(navl) -> tuple:
    """一批确定性帧 → 可比较的状态/证据观测（真源与快照必须逐项相同）。"""
    fakes = _fakes()
    out: list = []
    frames = (
        ("mode_a", MODE_FRAME_A),
        ("mode_b", MODE_FRAME_B),
        ("multi_only", MULTI_ONLY_FRAME),
        ("solo_only", SOLO_ONLY_FRAME),
        ("swapped", SWAPPED_POSITION_FRAME),
        ("same_height", SAME_HEIGHT_FRAME),
        ("list", fakes.LIST_FRAME),
        ("detail", fakes.DETAIL_FRAME),
        ("team", fakes.TEAM_FRAME),
        ("city", CITY_FRAME),
        ("battle", BATTLE_FRAME),
        ("settle", SETTLE_FRAME),
        # ★过渡态（真机 484，14:5x）★：加载帧必须与真源一样判成 lords_loading，认不出的仍是 unknown。
        ("loading", LOADING_FRAME),
        ("loading_pct", LOADING_FRAME_PCT),
        ("unknown", (("Foo", [10, 10, 20, 20]),)),
    )
    for label, frame in frames:
        out.append((label, str(navl.page_state(frame)), _norm_evidence(navl.mode_evidence(frame))))
    for name in ("战斗HUD", "结算页", "编队页", "详情页", "主城"):
        out.append(
            (
                "rule:" + name,
                bool(navl.page_rule_hit(MODE_FRAME_A, name)),
                bool(navl.page_rule_hit(fakes.TEAM_FRAME, name)),
            )
        )
    out.append(("reason", navl.non_list_stuck_reason("lords_mode", 9.4)))
    out.append(("reason_team", navl.non_list_stuck_reason("lords_team", float(navl.NON_LIST_STUCK_SEC))))
    # ★#100 缺口 7/8★：正向证据 / 换点阶梯 / 无效框拒绝（真源与快照必须逐项相同）
    out.append(
        (
            "team_confirm",
            bool(navl.team_page_confirmed(fakes.TEAM_FRAME)),
            bool(navl.team_page_confirmed(MODE_FRAME_A)),
            bool(navl.team_page_confirmed(UNKNOWN_FRAME)),
            bool(navl.team_page_confirmed((("挑战", [297, 1069, 80, 47]),))),
            navl.team_anchor_hit(fakes.TEAM_FRAME),
        )
    )
    out.append(
        (
            "mode_points",
            tuple(tuple(point) for point in navl.mode_click_points(SOLO_BOX)),
            tuple(navl.mode_click_points((0, 0, 0, 0))),
            tuple(navl.mode_click_points(None)),
        )
    )
    out.append(("mode_reason", navl.mode_click_exhausted_reason()))
    # ★#100 第 9 个缺口★：加成点数确认框（真源与快照必须逐帧相同）
    out.append(
        (
            "bonus_dialog",
            _norm_dialog(navl.bonus_dialog(BONUS_DIALOG_FRAME)),
            _norm_dialog(navl.bonus_dialog(BONUS_DIALOG_SHIFTED_FRAME)),
            _norm_dialog(navl.bonus_dialog(BONUS_DIALOG_NO_DECLINE_FRAME)),
            _norm_dialog(navl.bonus_dialog(UNKNOWN_FRAME)),
        )
    )
    out.append(
        (
            "mode_reason_readback",
            navl.mode_click_exhausted_reason("lords_unknown", None),
            navl.mode_click_exhausted_reason("lords_mode", "自动续战", "note"),
        )
    )
    return tuple(out)


def _parity_failures(impl=None, nav=None) -> list:
    """★安装态单源★：快照 == 真源（常量 + 判据表 == page_rules + 行为表）。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    rules = _page_rules()
    snap = getattr(impl, "_NavSnapshotLogic", None)
    if snap is None:
        return ["agent/lords_impl 缺 _NavSnapshotLogic —— 安装态没有导航真源替身"]
    msgs: list = []

    # (a) 常量逐项
    for name in STATE_PARITY_FIELDS:
        want, got = getattr(nav, name, None), getattr(snap, name, None)
        if name == "LORDS_PAGE_RULES":
            continue                       # 单独按字段比（dict 的形状不同：tuple vs list）
        if got != want:
            msgs.append(f"导航快照 {name} = {got!r} != 真源 {want!r}")

    # (b) 判据表：真源 == scene/page_rules.py（ADR-0003）+ 快照 == 真源
    want_rules = {
        name: dict(rules.page_rule(name).recognition) for name in nav.LORDS_PAGE_RULE_NAMES
    }
    if dict(nav.LORDS_PAGE_RULES) != want_rules:
        msgs.append(
            f"scene/lords_nav.LORDS_PAGE_RULES != scene/page_rules.py 的同名判据："
            f"{dict(nav.LORDS_PAGE_RULES)!r} vs {want_rules!r} —— 判据必须按名引用 page_rules（ADR-0003）"
        )
    snap_rules = {name: dict(rec) for name, rec in dict(getattr(snap, "LORDS_PAGE_RULES", {})).items()}
    if snap_rules != want_rules:
        msgs.append(f"安装态快照的页面判据表 != page_rules：{snap_rules!r} vs {want_rules!r}")
    if tuple(getattr(snap, "LORDS_PAGE_RULE_NAMES", ())) != tuple(nav.LORDS_PAGE_RULE_NAMES):
        msgs.append(
            f"导航快照 LORDS_PAGE_RULE_NAMES = {getattr(snap, 'LORDS_PAGE_RULE_NAMES', None)!r} "
            f"!= 真源 {nav.LORDS_PAGE_RULE_NAMES!r}"
        )

    # (c) 状态名不许出现别的场景的词（快照也要）
    snap_blob = " ".join(str(n) for n in getattr(snap, "LORDS_STATES", ())) + " " + str(
        getattr(snap, "LORDS_STATE_MODE", "")
    )
    for word in FORBIDDEN_STATE_WORDS:
        if word.lower() in snap_blob.lower():
            msgs.append(f"安装态快照的状态词表里出现了别的场景的状态名（{word!r}）：{snap_blob!r}")

    # (d) 行为表：同一批帧分别跑真源与快照
    mine = _state_scenario(nav)
    theirs = _state_scenario(snap)
    for a, b in zip(mine, theirs):
        if a != b:
            msgs.append(f"页面状态行为表不一致：真源 {a!r} / 快照 {b!r}")
    if len(mine) != len(theirs):
        msgs.append(f"页面状态行为表长度不一致：{len(mine)} vs {len(theirs)}")
    labels = tuple(item[0] for item in mine)
    for must in (
        "mode_a",
        "mode_b",
        "multi_only",
        "list",
        "battle",
        "settle",
        # ★过渡态（真机 484，14:5x）★：加载帧必须同一结论（真源 vs 安装态快照）
        "loading",
        "loading_pct",
        "reason",
        "team_confirm",
        "mode_points",
        "mode_reason",
    ):
        if must not in labels:
            msgs.append(f"页面状态行为表没走到 {must!r}（剧本被删空 = 守卫瞎了）")

    # (e) classify（lords 版）必须能认出模式页
    state = impl.classify(MODE_FRAME_A)
    if state != nav.LORDS_STATE_MODE:
        msgs.append(f"agent.lords_impl.classify(模式页) = {state!r}，应为 lords_mode")
    if "wuchong" in str(state).lower():
        msgs.append(f"agent.lords_impl.classify 返回了别的场景的状态名：{state!r}")
    return msgs


def probe_lords_mode_snapshot_parity() -> bool:
    """#100-4/5：安装态冻结副本 == 真源（常量 + page_rules + 同一批帧的行为）。"""
    return _parity_failures() == []


# ---------------------------------------------------------------------------
# 7. pipeline 接线（LordsModeSolo 在枢纽里、排在 mode=read 之前、不写死坐标）
# ---------------------------------------------------------------------------
def _wiring_failures(files: dict | None = None, impl=None) -> list:
    """``lords.json::LordsModeSolo`` 的形状 + 枢纽位置 + 不写死坐标。"""
    impl = _impl() if impl is None else impl
    files = _fakes()._pipelines() if files is None else files
    data = files.get("lords.json")
    if not isinstance(data, dict):
        return ["assets/resource/pipeline/lords.json 读不到 —— 模式页节点无从检查"]
    msgs: list = []
    node = data.get("LordsModeSolo")
    if not isinstance(node, dict):
        return ["lords.json 缺 LordsModeSolo —— 领主战模式选择页没人接"]
    reco = (node.get("recognition") or {}).get("param") or {}
    if str(reco.get("custom_recognition")) != "lords_progress":
        msgs.append(f"LordsModeSolo 的识别应是 lords_progress，实际 {reco.get('custom_recognition')!r}")
    if str((reco.get("custom_recognition_param") or {}).get("mode")) != impl.MODE_SOLO:
        msgs.append(
            f"LordsModeSolo 的识别参数缺 mode={impl.MODE_SOLO!r}"
            f"（实际 {(reco.get('custom_recognition_param') or {}).get('mode')!r}）"
        )
    act = (node.get("action") or {}).get("param") or {}
    if str(act.get("custom_action")) != "lords_unlock_step":
        msgs.append(f"LordsModeSolo 的动作应是 lords_unlock_step，实际 {act.get('custom_action')!r}")
    blob = str(node.get("action") or {})
    if "target" in blob:
        msgs.append(
            "LordsModeSolo 的动作里出现写死坐标 target —— 坐标必须来自当帧 OCR 框（绝不猜）"
        )
    if "wuchong" in str(node).lower():
        msgs.append("LordsModeSolo 引用了别的场景（wuchong）的名字 —— lords 必须走自己的判据")
    if node.get("timeout") is None or int(node.get("timeout")) > 3000:
        msgs.append(f"LordsModeSolo 的 timeout = {node.get('timeout')!r}，必须 ≤3000ms")
    if int(node.get("post_delay") or 0) > 1000:
        msgs.append(f"LordsModeSolo 的 post_delay = {node.get('post_delay')!r}，必须 ≤1000ms")
    if list(node.get("on_error") or []) != ["LordsEntry"]:
        msgs.append(f"LordsModeSolo.on_error 必须回枢纽，实际 {node.get('on_error')!r}")
    nxt = list(node.get("next") or [])
    if not nxt or nxt[-1] != "LordsEntry":
        msgs.append(f"LordsModeSolo.next 末项应回枢纽 LordsEntry，实际 {nxt[-1] if nxt else None!r}")
    if "LordsEntry" not in nxt:
        msgs.append("LordsModeSolo.next 里没有枢纽 —— 点完它就没法复核/继续")

    hub_next = list((data.get("LordsEntry") or {}).get("next") or [])
    if "LordsModeSolo" not in hub_next:
        msgs.append("LordsEntry.next 里没有 LordsModeSolo —— 枢纽扫不到它，链路断开")
    else:
        i_mode = hub_next.index("LordsModeSolo")
        i_read = hub_next.index("LordsReadProgress") if "LordsReadProgress" in hub_next else -1
        if i_read >= 0 and i_mode > i_read:
            msgs.append(
                f"LordsModeSolo（第 {i_mode} 项）排在 LordsReadProgress（第 {i_read} 项）之后 —— "
                f"票面要求**在 mode=read 之前**把它接进枢纽"
            )
        i_pick = hub_next.index("LordsPickTarget") if "LordsPickTarget" in hub_next else -1
        if i_pick >= 0 and i_pick > i_mode:
            msgs.append("LordsModeSolo 排在了 LordsPickTarget 之前 —— 会抢在选行前面点模式页")
    return msgs


def probe_lords_mode_wiring() -> bool:
    """#100-4：``lords.json::LordsModeSolo`` 接线（枢纽位置 / 参数 / 不写死坐标 / 节拍）。"""
    return _wiring_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_MODE_STATE,
        _TICKET,
        "★领主战自己的模式页状态★`lords_mode`（不是 wuchong_mode）：判据 = 两帧真机证据的"
        "「单人游戏/单人挑战领主（左上）+ 多人游戏/召集同伴挑战领主（右下）」+ 单人卡更高 ≥200px；"
        "状态词表全 lords_* 前缀、不许出现别的场景的词；只给一张卡 / 位置反了 / 同高 ⇒ 不判模式页",
        probe_lords_mode_page_state,
    ),
    (
        HOOK_ID_MODE_CLICK,
        _TICKET,
        "★点的是「单人游戏」自己的当帧 OCR 框中心★（不是副标题、不是多人卡）；点完**轮询读帧**"
        "（间隔 0.4s、单点 ≤8s）再读；只有编队页正向证据才算 mode_verify=team_page，换页后还能再点；"
        "只给多人卡的帧 ⇒ 不许点、不许判成模式页可点",
        probe_lords_mode_solo_click,
    ),
    (
        HOOK_ID_MODE_VERIFY,
        _TICKET,
        "★复核只认正向证据★「点完 → 瞬时 unknown → 又回到模式页」必须判失败（旧判据"
        "「离开了模式页」会判成功 = 14:0x 的假成功）；unknown ⇒ unconfirmed（不清账）、"
        "模式页 ⇒ still_mode、只有编队页（挑战 + SET/Party/自动续战 之一）⇒ team_page",
        probe_lords_mode_positive_verify,
    ),
    (
        HOOK_ID_MODE_LADDER,
        _TICKET,
        "★模式页换点阶梯（有界 4 个点）★中心 → 下方100 → 右侧120 → 下方180，每个点**轮询读帧**"
        "（0.4s / ≤8s，连续 3 帧模式页才算没生效）；中心无效、下方有效 ⇒ 2 个点 / 第 2 个成功；"
        "全无效 ⇒ 4 个点后**带读数**收工（state=… 不是编队页，不再写「画面仍是模式页」），"
        "并 override 到 LordsStop",
        probe_lords_mode_click_ladder,
    ),
    (
        HOOK_ID_BONUS_DIALOG,
        _TICKET,
        "★点「单人游戏」后的加成点数确认框（真机 484，2026-10-18 夜）★问题锚 + 「否」按钮框都来自"
        "当帧 OCR：点「否」→ 继续轮询到编队页（挑战 + 锚）；按钮换位置时点击跟着走（不写死）；"
        "读不到「否」按钮框 ⇒ 不盲点；残留确认框时 mode=solo 直接命中它（what=WHAT_MODE_CONFIRM）",
        probe_lords_mode_bonus_dialog,
    ),
    (
        HOOK_ID_PICK_DIAG,
        _TICKET,
        "★pick 空转诊断★每轮都算，但同一原因只在第 1/6/11… 轮打印、状态一变立刻打印；"
        "行里带 state / 行框 / stage / attempts / pending —— 下次真机卡住能一眼看出卡在哪",
        probe_lords_pick_diag_rate_limit,
    ),
    (
        HOOK_ID_CLICK_GUARD,
        _TICKET,
        "★盲点 (0,0) 拒绝★框缺失 / 尺寸为 0 / 中心在 (0,0) ⇒ 点击函数不被调用（注入 _click_hook "
        "计数）且打一行拒绝日志；有效框仍点（框闸不许过宽）—— 绝不允许「点页签 @720(0,0)」。"
        "★收工语义★已判收工时动作必须「成功但不点」（返回 False 会走 on_error 回枢纽、"
        "override 的 LordsStop 作废 → 收工无限重来）",
        probe_lords_click_no_blind_point,
    ),
    (
        HOOK_ID_NOISE,
        _TICKET,
        "★非列表页降噪★同一 (页面状态, 「页签：…」那一行) 连续命中只打印一次（注入 print 捕获计数）；"
        "页面状态一变允许再打一次（「页面变了」本身是信息）",
        probe_lords_non_list_noise,
    ),
    (
        HOOK_ID_BOUND,
        _TICKET,
        "★非列表页有界出口★状态名 NON_LIST_STUCK_SEC（9s，票面 8–10s）不变 ⇒ override LordsStop 并"
        "带原因收工：原因含状态名 / 「非列表页」/「无法导航」；详情页同样有界；列表页不走这条死线",
        probe_lords_non_list_bound,
    ),
    (
        HOOK_ID_ACTIVE,
        _TICKET,
        "★不打断正常战斗/结算★LORDS_ACTIVE_STATES（battle/settle）整类排除：长战斗、"
        "battle→settle→battle 序列、点过【挑战】后的等待页，都不许被非列表页死线收工",
        probe_lords_active_not_cut,
    ),
    (
        HOOK_ID_TRANSITION,
        _TICKET,
        "★过渡态不累加「无进展」计时★（真机 484，14:5x：--home 之后立刻跑 LordsEntry，"
        "刚回主城的 loading 帧被当成 lords_unknown，9s 死线在任务还没开始时就收工）："
        "lords_loading 帧 ⇒ 不判死且**重置**计时；unknown(2s)→loading(3s)→unknown(2s) 不收工；"
        "连续 15s 的 loading 也不收工；lords_unknown / lords_list 绝不入过渡集",
        probe_lords_transition_not_stuck,
    ),
    (
        HOOK_ID_UNKNOWN_BOUND,
        _TICKET,
        "★没放行过头：未知画面的死线仍在★lords_unknown 连续 12s（无 loading 打断）⇒ 必须收工"
        "且原因带状态名、override 到 LordsStop；battle/settle 仍不触发（回归）；"
        "LORDS_ACTIVE_STATES 与过渡集不相交",
        probe_lords_unknown_still_bounded,
    ),
    (
        HOOK_ID_PARITY,
        _TICKET,
        "★安装态单源★agent/lords_impl._NavSnapshotLogic 的页面状态/模式页/死线常量与判据表 == "
        "scene/lords_nav + scene/page_rules（ADR-0003）；同一批帧的状态/证据/文案逐项相同；"
        "agent.lords_impl.classify 认得出 lords_mode",
        probe_lords_mode_snapshot_parity,
    ),
    (
        "lords-mode-pipeline-wiring",
        _TICKET,
        "lords.json::LordsModeSolo 接线：识别 lords_progress{mode:solo}、动作 lords_unlock_step、"
        "动作里没有写死 target、timeout≤3000 / post_delay≤1000、on_error 回枢纽、"
        "枢纽里排在 LordsReadProgress 之前且不抢在 LordsPickTarget 之前",
        probe_lords_mode_wiring,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _record(name: str, msgs: list, checks: list) -> None:
    """记一条破坏实验：``msgs`` 非空 = 守卫成功变红。"""
    red = bool(msgs)
    checks.append((name, red, msgs[0] if msgs else ""))
    print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))


def _prove_red_checks() -> list:
    """十条破坏实验（全部在内存里做，退出必定还原实现）。"""
    impl = _impl()
    nav = _lords_nav()
    checks: list = []

    # ① 判据退回 wuchong_mode（跨场景状态名混用 = 本票的病）
    real_state_mode = nav.LORDS_STATE_MODE
    try:
        nav.LORDS_STATE_MODE = "wuchong_mode"
        _record(
            "① 模式页状态名退回 wuchong_mode",
            _mode_state_failures() + _bound_failures(),
            checks,
        )
    finally:
        nav.LORDS_STATE_MODE = real_state_mode
        impl.reset_sessions()

    # ② 点「多人游戏」（把证据里的单人卡换成多人卡）
    real_evidence = nav.mode_evidence

    def _broken_evidence(items):
        ev = real_evidence(items)
        return nav.ModeEvidence(
            solo=ev.multi, solo_note=ev.multi_note, multi=ev.multi, multi_note=ev.multi
        )

    try:
        nav.mode_evidence = _broken_evidence
        _record("② 点「多人游戏」（证据里把单人卡换成多人卡）", _mode_click_failures(), checks)
    finally:
        nav.mode_evidence = real_evidence
        impl.reset_sessions()

    # ③ 去掉降噪（恒打印）
    real_log_once = impl._tab_log_once
    try:
        impl._tab_log_once = lambda *a, **k: True
        _record("③ 去掉降噪（_tab_log_once 恒真）", _noise_failures(), checks)
    finally:
        impl._tab_log_once = real_log_once
        impl.reset_sessions()

    # ④ 去掉有界出口（恒不收工）
    real_stuck = impl.LordsProgressRecognition._non_list_stuck
    try:
        impl.LordsProgressRecognition._non_list_stuck = staticmethod(lambda *a, **k: "")
        _record("④ 去掉有界出口（_non_list_stuck 恒空）", _bound_failures(), checks)
    finally:
        impl.LordsProgressRecognition._non_list_stuck = staticmethod(real_stuck)
        impl.reset_sessions()

    # ⑤ 战斗/结算不再排除（长战斗会被收工）
    real_active = nav.LORDS_ACTIVE_STATES
    try:
        nav.LORDS_ACTIVE_STATES = ()
        _record("⑤ 战斗/结算不再排除（LORDS_ACTIVE_STATES 清空）", _active_failures(), checks)
    finally:
        nav.LORDS_ACTIVE_STATES = real_active
        impl.reset_sessions()

    # ⑥ 快照漂移（安装态状态名改一位）
    snap = impl._NavSnapshotLogic
    real_snap_mode = snap.LORDS_STATE_MODE
    try:
        snap.LORDS_STATE_MODE = "lords_mode_drifted"
        _record("⑥ 安装态快照状态名漂移", _parity_failures(), checks)
    finally:
        snap.LORDS_STATE_MODE = real_snap_mode
        impl.reset_sessions()

    # ⑦ ★#100 缺口 7★：复核退回「离开模式页即成功」（否定式判据）
    real_note = impl._note_mode_result

    def _old_note(session, state, navl, items=None):
        if session.mode_clicks <= 0 or state == navl.LORDS_STATE_MODE:
            return ""
        session.mode_clicks = 0
        if state == navl.LORDS_STATE_TEAM:
            return "team_page"
        return f"left_mode_page:{state}"

    try:
        impl._note_mode_result = _old_note
        _record("⑦ 复核退回「离开模式页即成功」（否定式判据）", _mode_verify_failures(), checks)
    finally:
        impl._note_mode_result = real_note
        impl.reset_sessions()

    # ⑧ ★#100 缺口 7★：去掉换点阶梯（只剩中心）
    real_ladder = nav.LORDS_MODE_CLICK_LADDER
    try:
        nav.LORDS_MODE_CLICK_LADDER = (("中心", 0, 0),)
        _record("⑧ 去掉换点阶梯（只剩中心）", _mode_ladder_failures(), checks)
    finally:
        nav.LORDS_MODE_CLICK_LADDER = real_ladder
        impl.reset_sessions()

    # ⑨ ★#100 缺口 8★：允许 (0,0) 盲点（框闸失效）
    real_center = impl._box_center

    def _loose_center(box):
        values = impl._box_xywh(box)
        if values is None:
            return (0.0, 0.0)              # 盲点：没有框也给一个 (0,0)
        x, y, w, h = values
        return (x + w / 2.0, y + h / 2.0)

    try:
        impl._box_center = _loose_center
        _record("⑨ 允许 (0,0) 盲点（框闸失效）", _click_guard_failures(), checks)
    finally:
        impl._box_center = real_center
        impl.reset_sessions()

    # ⑩ 收工后的动作不再「成功但不点」（返回 False → on_error 回枢纽，override 作废）
    real_dispatch = impl.LordsUnlockAction._dispatch

    def _broken_dispatch(self, context, argv):
        session = impl._session(getattr(argv.task_detail, "task_id", None))
        saved = session.stop_requested
        session.stop_requested = False      # 破坏点：无视「已判收工」
        try:
            return real_dispatch(self, context, argv)
        finally:
            session.stop_requested = saved

    try:
        impl.LordsUnlockAction._dispatch = _broken_dispatch
        _record("⑩ 收工后动作忽略 stop_requested", _click_guard_failures(), checks)
    finally:
        impl.LordsUnlockAction._dispatch = real_dispatch
        impl.reset_sessions()

    # ⑪ ★#100 补充（真机 484，14:5x）★：把 loading 移出过渡集 ⇒ 加载帧重新累加计时 ⇒ 挂点 10 红
    real_transition = nav.LORDS_TRANSITION_STATES
    try:
        nav.LORDS_TRANSITION_STATES = ()
        _record(
            "⑪ 把 loading 移出过渡集（LORDS_TRANSITION_STATES 清空）",
            _transition_failures(),
            checks,
        )
    finally:
        nav.LORDS_TRANSITION_STATES = real_transition
        impl.reset_sessions()

    # ⑫ 把 unknown 也当过渡态 ⇒ 未知画面的死线被放行 ⇒ 挂点 11 红（证明没放行过头）
    try:
        nav.LORDS_TRANSITION_STATES = tuple(real_transition) + (nav.LORDS_STATE_UNKNOWN,)
        _record(
            "⑫ 把 lords_unknown 也当过渡态（放行过头）",
            _unknown_bound_failures(),
            checks,
        )
    finally:
        nav.LORDS_TRANSITION_STATES = real_transition
        impl.reset_sessions()

    # ⑬ 不再认加载页（锚点清空）⇒ loading 帧退回 lords_unknown ⇒ 挂点 10 红
    real_anchors = nav.LORDS_LOADING_ANCHORS
    try:
        nav.LORDS_LOADING_ANCHORS = ()
        _record("⑬ 不再认加载页（LORDS_LOADING_ANCHORS 清空）", _transition_failures(), checks)
    finally:
        nav.LORDS_LOADING_ANCHORS = real_anchors
        impl.reset_sessions()

    # ⑭ ★#100 第 9 个缺口★：换点阶梯无限试（20 个点）⇒ 「有界 4」失效 ⇒ 挂点 8 红
    real_points = nav.mode_click_points

    def _many_points(box):
        pts = real_points(box)
        if not pts:                       # 无效框仍然算不出点（别把盲点守卫也一起破坏）
            return pts
        return tuple((f"p{i}", 100.0 + i, 200.0) for i in range(20))

    try:
        nav.mode_click_points = _many_points
        _record("⑭ 换点阶梯无限试（20 个点）", _mode_ladder_failures(), checks)
    finally:
        nav.mode_click_points = real_points
        impl.reset_sessions()

    # ⑮ ★#100 第 9 个缺口★：确认框点击目标写死（不跟当帧 OCR 框）⇒ 挂点 12 红
    real_bonus = nav.bonus_dialog
    try:
        nav.bonus_dialog = lambda items: nav.BonusDialog(
            question="“领主加成点数”吗？",
            decline=(178, 805, 37, 37),
            accept=(504, 805, 36, 36),
        )
        _record("⑮ 确认框点击目标写死（不跟当帧 OCR 框）", _bonus_dialog_failures(), checks)
    finally:
        nav.bonus_dialog = real_bonus
        impl.reset_sessions()

    # ⑯ ★#100 第 9 个缺口★：pick 空转诊断每轮都打（限流失效）⇒ 挂点 13 红
    real_diag = impl._pick_diag_once
    try:
        impl._pick_diag_once = lambda *a, **k: True
        _record("⑯ pick 空转诊断每轮都打（限流失效）", _pick_diag_failures(), checks)
    finally:
        impl._pick_diag_once = real_diag
        impl.reset_sessions()
    return checks


def prove_red() -> bool:
    """真实绿；十六条破坏实验各自如愿变红。"""
    print("hooks_122 prove-red：逐一破坏实现，要求十四个挂点各自变红")
    green = (
        probe_lords_mode_page_state()
        and probe_lords_mode_solo_click()
        and probe_lords_mode_positive_verify()
        and probe_lords_mode_click_ladder()
        and probe_lords_mode_bonus_dialog()
        and probe_lords_pick_diag_rate_limit()
        and probe_lords_click_no_blind_point()
        and probe_lords_non_list_noise()
        and probe_lords_non_list_bound()
        and probe_lords_active_not_cut()
        and probe_lords_transition_not_stuck()
        and probe_lords_unknown_still_bounded()
        and probe_lords_mode_snapshot_parity()
        and probe_lords_mode_wiring()
    )
    print(
        f"  [{'PASS' if green else 'FAIL'}] 真实实现：模式页判据 / 单人点击 / 正向复核 / "
        f"换点阶梯 / 加成确认框 / pick 诊断限流 / 盲点拒绝 / 降噪 / 有界 / 战斗不误杀 / "
        f"过渡态不误杀 / 未知死线仍在 / 安装态单源 / 接线（绿）"
    )
    if not green:
        for msg in (
            _mode_state_failures()
            + _mode_click_failures()
            + _mode_verify_failures()
            + _mode_ladder_failures()
            + _bonus_dialog_failures()
            + _pick_diag_failures()
            + _click_guard_failures()
            + _noise_failures()
            + _bound_failures()
            + _active_failures()
            + _transition_failures()
            + _unknown_bound_failures()
            + _parity_failures()
            + _wiring_failures()
        ):
            print(f"      - {msg}")
        return False

    checks = _prove_red_checks()
    ok = green and all(red for _name, red, _first in checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    # 本模块只有一个出口：prove_red。`--run-prove-red` 与无参等价（hooks_115 的跑器也按无参执行）。
    raise SystemExit(0 if prove_red() else 1)
