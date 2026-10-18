"""领主战「全难度解禁」（#100）—— 两个自定义识别/动作，★只做「点到位」这一件事★。

本模块**不打战斗**：它只负责把「该打的领主 → 该打的那一档 → 开打」这三下点击落到正确的位置，
然后把控制权交回 pipeline（``lords.json`` 的 ``LordsAfterFight`` 与既有战斗/结算/失败链）。

两个名字（注册见 ``agent/my_reco.py`` / ``agent/my_action.py``；runner 侧见
``tools/live_harness.py`` 的静态注册表）::

    custom_recognition = "lords_progress"      → :class:`LordsProgressRecognition`
    custom_action      = "lords_unlock_step"   → :class:`LordsUnlockAction`

``lords_progress`` 有 **七个 mode**（同一个识别器 —— 拆成多个名字就要多注册一遍，
而注册表不在本泳道的改写范围里；仓内先例：``special_batch_fight{row_click:true}``，#20/#42）：

* ``mode="read"``（缺省）：读**列表页每一行**的 ``通关数 N/M``，交给判定真源
  :mod:`scene.lords_unlock` 规划本轮目标、并在轮次边界判「该不该收工」；
  ★扫描闸★：扫描阶段（``page_pending`` 为真）且页签**未确认到目标页签**时，它**不按单帧规划**
  （返回未命中，让枢纽继续推进导航）—— 错页签的一帧会把别的子族的行记进本轮；
  扫描收尾（``mode="end"``）喂的合成帧走 ``synthesized=True``，不受扫描闸影响；
* ``mode="pick"``：把「下一处该点的框」选出来（列表页的目标行 / 详情页该档的【战斗】 /
  编队页的【挑战】），由 ``lords_unlock_step`` 点下去。★#100 第 3 条真机缺口★：点之前先
  **归位** —— 目标行不在屏上就先**对页签**（点一次标签框，切后仍以「可见行族」复核），
  再**先向下、后向上**滚动找（:class:`scene.lords_nav.PickNav`）；三种失败原因分开
  （目标不在这个页签 / 滚到底也没找到 / 找到了但点不动），各自带量。
  ★第二轮验收（真机 484）★：tier 点完进的是**模式选择页**（``state=lords_mode``），
  所以 ``_pick`` **先按页面状态分派**（:func:`_mode_step_state`）—— 模式页 / 加成确认框
  一律交给 :meth:`~LordsProgressRecognition._mode`（``WHAT_MODE`` / ``WHAT_MODE_CONFIRM``，
  由已验证的 ``_mode_click`` 执行：轮询读帧 + 点「单人游戏」+ 点确认框「否」），
  **绝不**掉进 ``pick_click`` 的 row/tier 分支；同时 :func:`find_row_box` **自带列表行 ROI**
  （:data:`scene.lords_nav.ROW_ROI`）—— 标题/横幅/页签/底栏里的同名文字越界即忽略并留日志。
* ``mode="page"``：读当前页**全部**行（滚动前）→ 去重累计（键 = 行名 + N/M）+ 到底判据；
* ``mode="tab"``：页签状态 + 该不该切（**含切后确认**；失败只许 1 次）；同时负责
  ★#100 第 5 个真机缺口★的**降噪**（同一 (页面状态, 那一行) 只打一次）与**非列表页死线**
  （状态名 K 秒不变 ⇒ 带原因收工）；
* ``mode="scroll"``：该不该滚一次（时间闩 + 到底 + 页签确认 + 选行优先）；
* ``mode="end"``：「列表到底了」判据（命中 = 到底），并推进页签扫描；两个页签都扫完时
  把**整份读数**交给 ``mode="read"`` 判一轮（合成帧逐项复原核对）。
* ``mode="top"``：★#100 第 6 轮真机验收★ **每页开扫前先回顶部**（有界 + 可验证）——
  战后列表停在被点行处、切页签也停在上次的滚动位置，不回顶部就向下扫 ⇒ 只读到 4 行就判
  「到底」（真机现场：``第 2 轮：读到 4 行，本轮目标 0 个``，而画面上还有 红嫉机兵 1/4 /
  妖狐 3/4）。动作 ``do=scroll_top`` 向上滚到「连续 2 个世代无新行 + 无位移」为止。
* ``mode="solo"``：★#100 第 4、7 个真机缺口★ 领主战**自己的**模式选择页（单人/多人）→
  点「单人游戏」的**当帧 OCR 框中心**（判据在 ``scene/lords_nav.page_state`` /
  ``mode_evidence``：四段文案 + 象限位置 + 单人卡更高；状态名 ``lords_mode``，
  **不借用五重的 ``wuchong_mode``**）。★#100 第 7 个缺口★：点完有**换点阶梯**
  （中心 → 下方100 → 右侧120 → 下方180，**每个点轮询读帧** ≤8s，最多 4 个点），
  复核**只认正向证据**（``team_page_confirmed``：挑战 + SET/Party/自动续战 之一）——
  「瞬时 unknown ⇒ 离开了模式页 ⇒ 成功」这种否定式判据已删除（14:0x 的假成功）。
  ★#100 第 9 个缺口★：点完弹的是**加成点数确认框**（是/否）—— 读到它就点**当帧框里的「否」**
  （不消耗加成次数），确认后继续轮询到编队页；「画面仍是模式页」那句错误结论已删（只写读数）。
  ★#100 第 8 个缺口★：所有点击前都过 ``_click_target`` 框闸，框无效绝不点 (0,0)。

``lords_unlock_step`` 同理有 ``do``：缺省 = 点识别选出的那一处；``do="tab"`` = 点页签
（当帧 OCR 框中心）；``do="scroll"`` = 按 ``SCROLL_PLAN`` 滚一次（**自带时间闩 ≥1.2s**）。
★pick 阶段的两条导航走的是同一条动作、但**另记一本账**★：识别把
``what=tab`` / ``what=scroll_down|scroll_up`` 放进 ``session.pending``，动作照它执行 ——
页签**不记**「点了一次目标」，滚动**重置**「点不出去」死线（导航不是点目标）。

★判据全部是**引用**，不是本模块自造★
------------------------------------
* ``通关数 N/M`` 的解析、``M``/解锁链的对账、三条终结条件与防死循环 = ``scene.lords_unlock``
  （#100 的**判定真源**，纯逻辑、无 I/O，离线可单测）；
* 「这一行/这一档是不是我要的」的行正则 = ``scene.lords``（``row_regex`` / ``tier_chain``）；
* 详情页判据 ``推荐编成``、难度行 → 【战斗】的几何配对 = ``agent.side_impl``
  （``on_detail_page`` / ``pick_target_battle_box``；#35/#62 真机修正过的实现，**别再写一份**）；
* 编队页【挑战】的点击判据 = ``battle_loop_core.PAGE_CHALLENGE_PATTERNS``
  —— 它是 ``scene/challenge.py`` 在 **agent 侧的唯一逐字快照**（``agent/`` 在安装态没有
  ``scene/``，不能 import），守卫 ``hooks_100`` 钉「快照 == 真源 == lords.json 里的字面量」。

★``scene.*`` 惰性 import + 安装态**冻结快照**回落★
--------------------------------------------------
``agent/`` 会被 ``tools/install.py`` **整目录**拷到 ``install/agent``（那里**没有** ``scene/``）。
顶层 ``from scene... import`` 会让安装态一 import 就 ImportError，连带整个 agent 起不来
（``my_reco`` / ``my_action`` 都 import 本模块）。所以这里一律函数内 import，并且只在
``ModuleNotFoundError``（= 安装态没有 ``scene/``，一种**预期内**的缺席）时回落到本文件里的
**逐字冻结快照**：

* **仓库态**（有 ``scene/``）→ 一律用真源 :mod:`scene.lords_unlock` / :mod:`scene.lords`；
* **安装态**（没有 ``scene/``）→ 用 ``_PARSE_PROGRESS_SNAPSHOT`` / ``_PLAN_ROUND_SNAPSHOT`` /
  ``_SHOULD_STOP_SNAPSHOT`` / ``_LORDS_M_SNAPSHOT`` 等冻结副本 —— 识别**照常命中**、
  动作**照做**（这正是本文件的安装态可用性）。

快照**不是**第二真源：``tools/contract_hooks/hooks_100.py`` 的守卫钉着它 ——
``lords-install-snapshot-parity``（正则串 / M 表 / 链表 / 行名表 / 阈值逐项相等）与
``lords-install-behavior-parity``（同一批样例分别跑真源与快照，结果**逐项相等**，
含 ``no_chain`` / ``m_conflict`` / ``unknown_row`` / ``duplicate_row`` / ``played==0`` / ``N>M`` 抛错）。
两条路都不通（例如运行期把 :func:`_logic` 打桩成 ``None``）时才 :data:`INSTALL_STATE_REASON`：
不崩、不假成功、识别不命中。

导航（页签 + 滚动）走**同一条纪律**：真源 :mod:`scene.lords_nav`（+ :mod:`scene.page_rules`
的判据），安装态回落到 ``_NavSnapshotLogic``（数据 + 行为逐项由 ``lords-nav-snapshot-parity``
钉住）；两条路都不通时 :data:`NAV_INSTALL_STATE_REASON`，四个导航 mode 一律不命中。

★R1/R2 两条修正与真源同名同形★（快照必须跟着改，否则安装态又退回老坑）：
``NavState.add_rows`` 把累计表按**行名**留**最新**读数（``row_key`` 只判「本帧新不新」）；
``NavState.begin_round`` 在 ``page_pending`` 为真的入口复位 sweep + 清累计（见
:func:`_ensure_round`）；``observe`` 的「连续 2 次无变化」按**滚动世代**记账。

★#100 第 6 轮真机验收（``debug/lords_accept6.log``，18:40–18:47）的五条修正★
----------------------------------------------------------------------------
1. **每页开扫前回顶部**（``mode=top`` / ``do=scroll_top`` / ``LordsScrollTop``）：战后列表停在
   被点行处、切页签也保留滚动位置 —— 不回顶部，第二轮的「到底」毫无意义。判据 =
   ``NavState.observe_rewind``（连续 2 个回顶部世代「无新行 ∧ 无位移」）；预算 24（有界）。
2. **切页签必须真点 + 复核**：扫描期的目标页签 = **sweep 顺序**（旧目标不再把 desired 钉住）；
   错的页签上 ``mode=end`` 不推进（``_scan_tab_mismatch``）；切不过去 ⇒ 原因「页签未切换 …
   扫描不完整」，不许宣布「两个页签都扫到底」。
3. **被徽标剔掉的行算「见到行」**：``observe(..., dropped=n)`` 遇被剔行一律不判「到底」；
   两代滚不动 ⇒ ``bottom_unprovable``（底不可证，按扫描不完整收尾）。
4. **零目标收工原因指对病因**：``ZERO_TARGET_INCOMPLETE_REASON``（扫描不完整 / 未回顶 /
   页签没切），不再落到「本页已滚 80 次」。
5. **arm sweep 在 plan 之前**：关轮那一帧 ``mode=read`` 不命中（``gate=scan_due``，单帧 plan
   只进 ``plans_discarded``）；plan 只接受 ``mode=end`` 的整轮交接。

★可测试性★
-----------
``_grab`` / ``_ocr`` / ``_click_box`` / ``_now`` / ``_sleep`` 是**模块级**函数（测试可以
``li._ocr = lambda ...`` / ``li._now = 假时钟`` / ``li._sleep = 假睡眠`` 打桩，
类工厂拿到的是运行时才查模块全局名的 lambda，见 :func:`_ocr_hook`）。所以本模块的
「点哪、点了没点、记了几场、滚了几次、页签切没切」全部可以离线断言，不需要设备。
"""

from __future__ import annotations

import re
import sys
import threading
import time
import traceback
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from maa_util import ocr_all, read_action_param, read_param

# 编队页【挑战】的点击判据 —— agent 侧唯一逐字快照（真源 scene/challenge.py，守卫 hooks_100 钉住）
from battle_loop_core import PAGE_CHALLENGE_PATTERNS

# 难度词表的**安装态冻结副本**（真源 scene/config.py 的 DIFFICULTIES；batch_plan 那份由 hooks_34 钉着，
# 这里直接复用同一个元组，绝不抄第二份 —— 抄一份就是第二套真源）
from batch_plan import _DIFFICULTIES_SNAPSHOT as _DIFFICULTIES_FROZEN

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
#: 借用的全屏 OCR 节点（common.json 的 ``OcrTask``：``expected: [".*"]`` 取回所有文本框）。
DEFAULT_OCR_ENTRY = "OcrTask"

#: 收工出口节点（``lords.json::LordsStop`` = DirectHit + StopTask，照 ``SpecialBatchStop``）。
#: 由本模块用 ``context.override_next`` 把「判定该收工」的那个节点指向它。
STOP_NODE = "LordsStop"

#: 详情页独有标记（真源 ``agent/side_impl._DETAIL_PAGE_MARKER``）。这里只是**文档用**，
#: 真正的判据一律走 ``side_impl.on_detail_page``（不复制第二份）。
DETAIL_PAGE_MARKER = "推荐编成"

#: ``lords_progress`` 的两种 mode。
MODE_READ = "read"
MODE_PICK = "pick"
#: #100 第 1、2 条真机缺口（页签切换 + 列表滚动）新增的 mode —— ★同一个识别名，按 mode 分支★。
#:
#: ★为什么不新注册一个名字★：``lords_scroll`` / ``lords_list_end`` 这种新名字要同时改三处
#: 注册（``agent/my_reco.py`` / ``agent/my_action.py`` / ``tools/live_harness.py``），
#: 而那三处不在本票的改写范围内；仓内既有先例正是「复用一个已注册名 + 显式参数区分语义」：
#: ``special_dungeon.json::SpecialEnterBoss`` 的动作 ``special_batch_fight{row_click:true}``
#: （原文：「#20 把 runner 侧注册表锁死在 live_harness（本泳道不可改），新增自定义名会让
#: 套件变红；故用显式参数区分语义」）。所以这里照抄那条先例，而不是新造名字。
MODE_PAGE = "page"      # 读当前页**全部**行（滚动前）→ 去重累计 + 到底判据
MODE_TAB = "tab"        # 页签状态 + 该不该切（含切后确认；失败只许 1 次）
MODE_SCROLL = "scroll"  # 该不该滚一次（时间闩 + 到底判据 + 页签确认）
MODE_END = "end"        # 「列表到底了」判据（命中 = 到底；并推进页签扫描）
#: ★#100 第 4 个真机缺口★ 领主战**自己的**模式选择页（单人/多人）→ 点「单人游戏」。
#: 真机现场（484，12:4x）：点完 row → detail、点完 tier → 这一页，而旧链把它判成别的场景的
#: 状态名（``wuchong_mode``），lords 状态机不认识 ⇒ 卡住。判据/文案/位置全部在
#: ``scene/lords_nav.py``（:func:`scene.lords_nav.page_state` / :func:`mode_evidence`），
#: 本模块只做胶水（绝不在这里写死坐标或抄第二份文案）。
MODE_SOLO = "solo"
#: ★#100 第 6 轮真机验收（``debug/lords_accept6.log``，18:40–18:47）★「每页开扫前先回顶部」。
#: 真机现场：战后列表停在**被点行**处，第 2 轮对「领主战」只滚 1–6 次就判「到底」（只读到 4 行），
#: 而画面上「降临讨伐」顶部还有 红嫉机兵 1/4、苍叹机兵 1/4，「领主战」还有 妖狐讨伐 3/4
#: —— 全是没读到的未通关行。★「到底」是**相对滚动位置**的概念★：不回顶部，第二轮的「到底」
#: 毫无意义。本 mode 只做一件事：**有界**上滚直到「连续 2 个世代无新行 + 无位移」。
MODE_TOP = "top"

#: ``lords_unlock_step`` 的 ``do`` 取值（缺省 = 既有的「点识别选出的那一处」）。
DO_CLICK = "click"
DO_TAB = "tab"          # 点页签（点**当帧 OCR 框中心**，绝不写死坐标）
DO_SCROLL = "scroll"    # 滚一次（自带时间闩 ≥1.2s + 稳定等待由节点 post_delay 承担）
#: ★每页开扫前的「回顶部」上滚★（= ``mode=top`` 的动作；收尾由动作自己补稳定等待）。
#: ★它**不是** ``do=scroll`` 的反向参数★：两条路分开记账（回顶部不推进「到底」的滚动世代，
#: 也不消耗向下扫的 80 次预算），这样「到底判据」的语义不会被「回顶部」污染。
DO_SCROLL_TOP = "scroll_top"

#: 执行滚动手势的 pipeline 节点（``DirectHit + Swipe``，几何在 ``lords.json``，只由本模块
#: ``run_action`` 调用、不进任何 ``next`` —— 与 ``common.json::PubClick`` 同一手法）。
SCROLL_NODE = "LordsSwipeOnce"

#: 收工出口 / 枢纽（页签确认不过时回枢纽；连续不过则收工）。
HUB_NODE = "LordsEntry"

#: 导航真源（``scene/lords_nav.py``）与它的冻结快照两条路都不通时的理由串。
NAV_INSTALL_STATE_REASON = (
    "取不到导航真源：仓库态应有 scene/lords_nav.py，安装态应有本文件的逐字冻结快照"
    "（_NavSnapshotLogic）；两条路都不通 —— 这里不假成功，识别不命中"
)

#: ★零目标收工的**正确原因**★（#100 第 6 轮真机验收）：修前这种情况一路空滚 80 次，
#: 理由写成「本页已滚 80 次（上限 80）仍未到底」—— **把病因指错了**（那不是滚动的问题，
#: 是扫描不完整：有行被徽标剔除 / 没确认回到顶部 / 页签没切成功）。
#: ``{evidence}`` = :meth:`scene.lords_nav.NavState.scan_incomplete_reason`（带量）。
ZERO_TARGET_INCOMPLETE_REASON = (
    "收工 —— 本轮零目标，但扫描不完整（{evidence}）—— 数据与画面可能不一致"
)

#: ★回顶部预算用尽仍未到顶★ → 带原因收工（★有界★：绝不无限上滚；也绝不以「滚动上限」收工）。
REWIND_FAILED_REASON = (
    "收工 —— 回顶部失败：向上滚 {scrolls} 次（上限 {max}）仍未确认到顶 —— "
    "扫描不完整（未确认回到顶部），数据与画面可能不一致"
)

#: ★页签没切换成功★ → 带原因收工（★不许宣布「两个页签都扫到底」★：那会把只扫了一个页签的
#: 4 行当成整轮读数 —— 真机 484 第 6 轮就是「目标 0、两页签共 4 行」）。
TAB_SWITCH_UNCONFIRMED_REASON = (
    "页签未切换（可见行族仍指向「{confirmed}」，目标「{desired}」）—— 扫描不完整：{why} —— 带原因收工"
)

#: 「点了什么」的三种取值（记账与日志用；未知 = 识别给的框但没有 what）。
WHAT_ROW = "row"
WHAT_TIER = "tier"
WHAT_CHALLENGE = "challenge"
WHAT_TAB = "tab"
#: ★#100 第 4 个真机缺口★ 模式选择页点「单人游戏」（点**当帧 OCR 框中心**）。
#: 它不是纯导航：它是「目标 → 档位 → 模式 → 编队 → 挑战」这条目标流程上的一跳，
#: 所以照「点了一次目标」记账（与点行/点档同口径），而不是照页签/滚动那条纯导航口径。
WHAT_MODE = "mode"
#: ★#100 第 9 个真机缺口★ 点完「单人游戏」后弹出的**加成点数确认框**里那个「否」。
#: 它和 ``mode`` 是两段动作（先点卡、再点确认），但同属「模式 → 编队」这一跳：
#: **不**记第二次 ``attempts_since_read``（否则一次跳被记成两次点击）。
WHAT_MODE_CONFIRM = "mode_confirm"
#: ★pick 阶段的两次导航★（#100 第 3 条真机缺口）：滚动去找目标行，方向按内容命名。
#: ★它们**不是**「点了一次目标」★：不记 ``attempts_since_read``、不消耗「点不动」死线。
WHAT_SCROLL_DOWN = "scroll_down"
WHAT_SCROLL_UP = "scroll_up"
#: ★本票 ②★ 详情页左下角【返回】—— 打完一场（或全档已通关）回列表的**导航**一跳。
#: 与页签/滚动同口径：不记 ``attempts_since_read``、不消耗死线；但它**会**置
#: ``session.back_to_list_pending``：回列表的第一件事必须是 ``mode=read`` 重读 `通关数 N/M`。
WHAT_BACK = "back"
WHAT_UNKNOWN = "unknown"

#: 会话阶段（仅诊断用；**不**参与判定 —— 判定一律看当前这一帧的画面）。
STAGE_LIST = "list"
STAGE_DETAIL = "detail"
STAGE_TEAM = "team"
STAGE_FIGHT = "fight"

#: **点不出去的死线**（秒）。有目标待点、却连续这么久一次都没点成功 → 带原因收工。
#: 20s 是照 #62 的 ``_UNFIGHTABLE_DETAIL_SEC``（停在自家详情页 20s 就记因跳过）同一口径：
#: 「一个读不出的成员不许把整批吃掉」。
STUCK_SEC = 20.0

#: 点下【挑战】之后，**最多**等这么久就当作这一场已经结束（清掉「刚开打」的闩）。
#: 防的是「点完挑战、画面既没进战斗也没回列表」把会话卡成永久 no-hit。
#: 180s 与 ``agent/side_impl.py`` 的 ``_SPECIAL_NAV_DEADLINE_SEC`` 同量级（单目标死线）。
FIGHT_GRACE_SEC = 180.0

#: 两条路（``scene/`` 真源 + 本文件的冻结快照）都取不到时的统一理由串。
#: ★它是「不假成功」的证据★：真源不在场**且**快照不可用时识别器**不命中**，任务不会假装跑完。
#: （安装态有快照回落，正常不会走到这里；它还守在「有人把 :func:`_logic` 打桩成 ``None``」那条路上。）
INSTALL_STATE_REASON = (
    "取不到判定真源：仓库态应有 scene/lords_unlock.py，安装态应有本文件的逐字冻结快照"
    "（_PARSE_PROGRESS_SNAPSHOT / _PLAN_ROUND_SNAPSHOT / _SHOULD_STOP_SNAPSHOT）；"
    "两条路都不通 —— 这里不假成功，识别不命中"
)


# ---------------------------------------------------------------------------
# I/O 三个 monkeypatch 点（测试在这里注入假 OCR / 假点击）
# ---------------------------------------------------------------------------
def _grab(context):
    """当前帧（720 空间位图）。"""
    return context.tasker.controller.post_screencap().wait().get()


def _ocr(context, image, entry=DEFAULT_OCR_ENTRY):
    """全屏 OCR -> ``[(text, box[4]), ...]``（借 pipeline 的 ``OcrTask`` 节点）。"""
    return ocr_all(context, image, entry)


def _click_box(context, cx, cy):
    """点 720 空间的 ``(cx, cy)``。

    ★取整只在这里★（离 ``context.run_action`` 最近的一层）：上游一路都是**浮点中心**
    （``_tab_click`` / ``run`` 的 ``cx, cy`` 都不截断，见 :func:`_box_xywh` 的纪律）。

    ★走 pipeline 原生 ``PubClick``（``target: true`` 点框中心），不用
    ``controller.post_click``★：部分原生库未导出 ``MaaControllerPostClickV2``，直接
    ACCESS_VIOLATION（见 ``common.json::PubClick`` 的注释与 ``agent/my_action.py``）。
    """
    try:
        context.run_action("PubClick", box=(int(cx) - 1, int(cy) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001 - 点不动就是这一下失败，不吞成「成功」
        print(f"[lords] 点击失败 ({cx},{cy})：{exc}")
        return False


#: 「动作异常」的醒目标记：logcat / stderr 里**一行**就能把它跟「识别失败（不命中）」分开。
#: 守卫 ``tools/contract_hooks/hooks_120.py`` 钉着它（注入一个必抛的 hook, 断言这行真的出现）。
ACTION_ERROR_MARK = "★动作异常★"


def _announce_action_error(exc, argv=None) -> None:
    """把动作里的异常**喊出来**：一行 ``★动作异常★`` + 完整栈，然后如实返回失败。

    ★为什么必须自己打★：``maa.custom_action.CustomAction._c_run_agent`` 是 ctypes 回调，
    在它里面抛出的异常会被 CPython 记成
    ``Exception ignored on calling ctypes callback function ...`` 之后**丢掉**：
    框架把动作当失败（回调返回 0），但**没有任何人**看得到栈。于是症状离病因极远 ——
    #120 真机：``len(Rect)`` 崩在「点页签」那一步，现场只看到 #19 那条正确的
    「页签未确认到「领主战」…可见行族=('joss',)」收工理由。

    ★为什么是 print 而不是 logging★：agent 侧既有的现场诊断全部走 ``print``
    （见 ``_click_box`` / ``_override_next``），logcat 与 stderr 都能收到，不引入新依赖。
    """
    node = getattr(argv, "node_name", "?") if argv is not None else "?"
    print(
        f"[lords] {ACTION_ERROR_MARK} {type(exc).__name__}: {exc} —— 本步不做，交回枢纽"
        f"（node={node!r}）",
        flush=True,
    )
    traceback.print_exc()
    try:
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - 刷不动也不能让「留痕」自己再抛一次
        pass


# 类工厂拿到的是「运行时才查模块全局名」的 lambda ⇒ 测试替换 li._ocr 立刻生效
# （与 agent/phantom_impl.py 的 _ocr_hook / _click_hook 同一手法）。
_ocr_hook = lambda *a, **k: _ocr(*a, **k)           # noqa: E731
_click_hook = lambda *a, **k: _click_box(*a, **k)   # noqa: E731


def _read_items(context, entry=DEFAULT_OCR_ENTRY):
    """**重新抓一帧**再 OCR（★#100 第 7 个真机缺口：点完等过之后靠它复核落点★）。

    绝不复用点击前那一帧的 OCR 结果：模式页换点阶梯每点一次都 ``_sleep`` 后重新抓图，
    否则读到的还是「点之前」的模式页 / 转场帧（旧判据的假成功就是这么来的）。
    """
    return _ocr_hook(context, _grab(context), entry)


#: 与 ``_ocr_hook`` 同一手法：守卫可替换 ``_read_items`` 注入一段「点完读到的帧」序列。
_read_items_hook = lambda *a, **k: _read_items(*a, **k)   # noqa: E731


def _now() -> float:
    """单调时钟（死线计算用）。**测试在这里注入假时钟**，不必真等 20s。"""
    return time.monotonic()


def _sleep(seconds: float) -> None:
    """睡眠（滚动时间闩的补睡 / 模式页点完后的**轮询间隔**）。测试在这里注入假睡眠，不必真等。"""
    time.sleep(max(0.0, float(seconds)))


# ---------------------------------------------------------------------------
# ★矩形解包：maa v5 的 ``Rect`` 不是 list★（#120 真机 TypeError）
# ---------------------------------------------------------------------------
# 真机现场（484，``--trace LordsEntry``）::
#
#     File "agent/lords_impl.py", line 2465, in _tab_click
#         if box is None or len(box) != 4:
#     TypeError: object of type 'Rect' has no len()
#     Exception ignored on calling ctypes callback function <function CustomAction._c_run_agent ...>
#
# ``maa.define.Rect`` 是 ``@dataclass(x, y, w, h)``：有 ``__iter__`` / ``__getitem__``，
# **没有** ``__len__``。于是 ``box[0]`` 能跑、``len(box)`` 当场抛 —— 而离线测试的假 argv 给的是
# list，所以「页签框」这条路径当初全绿、真机第一下就炸，且 ``len()`` 抛在 ctypes 回调里被吞掉
# （症状 =「页签根本没点下去」，离病因一个 len 那么远）。
#
# ★纪律（#120 的核心）★
# * 解包一律走 :func:`_box_xywh`（``.x/.y/.w/.h`` 优先，其次下标），它**保留浮点**；
# * **绝不**在解包里 ``int()`` 截断：``tools/test_lords_unlock.py`` / ``hooks_100`` 拿浮点中心
#   跟手算值对账，截断立刻红（半个像素的偏差落在页签 ROI 边界上就是「点不到」）；
# * 取整只许发生在**真正发点击/手势**那一下 —— :func:`_click_box` 里的 ``int()``，
#   也就是离 ``context.run_action`` 最近的那一层。
# ---------------------------------------------------------------------------
def _box_xywh(box):
    """矩形 → ``(x, y, w, h)``（**原样保留数值类型，绝不 int() 截断**）；解不出返回 ``None``。

    两条路：

    * ``maa.define.Rect`` 这类「有 ``.x/.y/.w/.h`` 的对象」→ 取属性；
    * ``list`` / ``tuple`` / ``numpy.ndarray`` → ``tuple(box)``，长度必须是 4。

    ★不许用 ``len(box)`` 判断★：``Rect`` 没有 ``__len__``，#120 的 TypeError 就是它。
    """
    if box is None:
        return None
    x = getattr(box, "x", None)
    y = getattr(box, "y", None)
    w = getattr(box, "w", None)
    h = getattr(box, "h", None)
    if x is not None and y is not None and w is not None and h is not None:
        return (x, y, w, h)
    try:
        values = tuple(box)
    except TypeError:
        return None
    if len(values) != 4:                  # 注意：这里判的是**解出来的元组**，不是 Rect 本身
        return None
    return values


def _box_center(box):
    """框中心 ``(cx, cy)``（720 空间）。★浮点，不取整★；框**无效**返回 ``None``。

    ★#100 第 8 个真机缺口（盲点）★：``box`` 缺失、尺寸为 0、或中心恰好是 ``(0,0)``
    一律当「没有框」—— 修前真机日志里出现过 ``[lords] 点页签 @720(0,0)``：
    识别没给框（或给了 ``[0,0,0,0]``），动作照样点了一下 (0,0)。

    ★尺寸判断用 ``float()`` 比较★：``maa.define.Rect`` 的 w/h 可能是浮点；
    0 与负数都不是可点的框。中心 (0,0) 在 720x1280 上不可能是真控件，只可能是无效框。
    """
    values = _box_xywh(box)
    if values is None:
        return None
    x, y, w, h = values
    try:
        if float(w) <= 0 or float(h) <= 0:
            return None
    except (TypeError, ValueError):
        return None
    cx, cy = x + w / 2.0, y + h / 2.0
    if cx == 0 and cy == 0:
        return None
    return (cx, cy)


def _click_target(box, what: str = ""):
    """点击前的**框闸**：返回可点的中心；框无效则返回 ``None`` + 一行拒绝日志。

    ★#100 第 8 个真机缺口★：这里就是「绝不允许 ``点页签 @720(0,0)``」的那道闸 ——
    所有真正发点击的路径（``_tab_click`` / ``lords_unlock_step`` 的普通点击 /
    模式页换点阶梯）都必须先过它。拒绝时**绝不调用** ``_click_hook``。
    """
    center = _box_center(box)
    if center is not None:
        return center
    values = _box_xywh(box)
    suffix = f"（{what}）" if what else ""
    print(
        f"[lords] 拒绝点击{suffix}：框无效（box={values!r}；缺失 / 尺寸为 0 / 中心在 (0,0)）"
        f" —— 绝不点 (0,0)"
    )
    return None


def _box4_int(box):
    """框 → ``(int x, int y, int w, int h)``；解不出返回 ``None``。

    ★只给「与 ``scene/`` 真源对账的输出」用★：``scene/lords_nav._box4`` 与
    ``scene/lords_unlock.group_progress_rows`` 都是 int 截断的逐字副本，快照必须跟它们
    **逐项相等**（``lords-nav-snapshot-parity`` / ``lords-install-behavior-parity`` 按整数对账）。
    **点击中心不许走这里** —— 中心见 :func:`_box_center`。
    """
    values = _box_xywh(box)
    if values is None:
        return None
    return (int(values[0]), int(values[1]), int(values[2]), int(values[3]))


# ---------------------------------------------------------------------------
# ★安装态冻结快照★（真源 = scene/lords_unlock.py + scene/lords.py 的**逐字副本**）
# ---------------------------------------------------------------------------
# 为什么需要：``agent/`` 会被 ``tools/install.py`` **整目录**拷到 ``install/agent``，那里
# **没有** ``scene/``。仓库态一律用真源（:func:`_logic` 先试 ``scene.lords_unlock``），
# 取不到（``ModuleNotFoundError``）时回落到这里的冻结副本 —— 装好的产品**识别照常命中、
# 动作照做**，而不是「识别不命中、动作如实失败」。
# 先例（同一套路，别另发明）：``battle_loop_core.PAGE_CHALLENGE_PATTERNS``（#112）、
#   ``auto_switch_impl._TEAM_PAGE_ANCHORS_SNAPSHOT``（#109）、``batch_plan._DIFFICULTIES_SNAPSHOT``（#34）。
#
# ★纪律★：这里**不是**第二真源 —— 每个正则 / 数值 / 文案 / 分支都是 ``scene/`` 的逐字副本，
# 由 ``tools/contract_hooks/hooks_100.py`` 的两条守卫钉住：
#   · ``lords-install-snapshot-parity``：正则串 / M 表 / 链表 / 行名表 / 行名正则表 / 阈值 逐项相等；
#   · ``lords-install-behavior-parity``：同一批样例分别跑真源与快照，结果**逐项相等**
#     （含 no_chain / m_conflict / unknown_row / duplicate_row / played==0 / N>M 抛错 这些分支）。
# **别手改快照**：先改 ``scene/``，再把同一份抄过来（守卫会点名差在哪一项）。
# ---------------------------------------------------------------------------
#: ``scene/lords_unlock.PROGRESS_RE`` 的逐字冻结（**字符串**；守卫逐字对账）。
_PROGRESS_RE_SNAPSHOT: str = (
    r"通\s*关\s*数"
    r"[\s:·.．・\-—–_=全共满]*"
    r"(\d{1,2})"
    r"\s*[/|\\⁄╱]\s*"
    r"(\d{1,2})"
    r"(?!\s*[/|\\⁄╱]\s*\d)"
)
_PROGRESS_RES_SNAPSHOT = re.compile(_PROGRESS_RE_SNAPSHOT)

#: 终结阈值（= :data:`scene.lords_unlock.SESSION_CAP` / ``IDLE_ROUND_LIMIT``；运维裁决 D6 的值）。
_SESSION_CAP_SNAPSHOT = 60
_IDLE_ROUND_LIMIT_SNAPSHOT = 2

#: 行名 ↔ 进度的几何阈值（= ``MAX_NAME_DY`` / ``MIN_NAME_LEFT_GAP`` / ``NOT_A_ROW_NAME``）。
_MAX_NAME_DY_SNAPSHOT = 60
_MIN_NAME_LEFT_GAP_SNAPSHOT = 20
_NOT_A_ROW_NAME_SNAPSHOT: tuple = ("更新列表", "NEW", "首次报酬", "通过房间号码参加")

#: ``RoundPlan.problems`` 的 kind（= ``PROBLEM_*``；★每一条都是「不静默」的姿态★）。
_PROBLEM_UNKNOWN_ROW_SNAPSHOT = "unknown_row"
_PROBLEM_NO_CHAIN_SNAPSHOT = "no_chain"
_PROBLEM_M_CONFLICT_SNAPSHOT = "m_conflict"
_PROBLEM_DUPLICATE_SNAPSHOT = "duplicate_row"

#: 难度词表：与 ``batch_plan`` 用**同一份**冻结表（那边由 hooks_34 钉着 ``scene.config.DIFFICULTIES``，
#: 这里只 import 不重抄 —— 两处各写一份就是两套真源）。
_DIFFICULTIES_SNAPSHOT: tuple = tuple(_DIFFICULTIES_FROZEN)

#: ``scene/lords.py`` 的**行名表**（= ``LORDS`` 的 ``row_name``，顺序照抄）。
#: ★它是「成员身份」不是「数据」★：不在表里的行会被 :func:`_PLAN_ROUND_SNAPSHOT` 报
#: ``unknown_row``（点错人），所以安装态必须知道**全部**成员，哪怕其余字段还没采集。
_LORDS_ROWS_SNAPSHOT: tuple = (
    # ==== 已采集：字段来自仓内真机帧 ====
    "猩红巨熊讨伐",
    "背鳍三兄弟讨伐",
    "八岐大蛇讨伐",
    "艾基尔·嫉妒讨伐",
    "妖狐讨伐",
    "诅咒弧魔艾基尔讨伐",
    "无猾机兵",
    "红嫉机兵",
    "苍叹机兵",
    # ==== 未采集（占位）：M / 解锁链 / 认证文本都还没有仓内证据 ====
    "管理者讨伐",
    "Sec-5200Li讨伐",
    "白虎讨伐",
    "风将獠牙骑士讨伐",
    "寄居蟹船长讨伐",
    "潮汐巨妖讨伐",
    "废墟魔像讨伐",
    "废墟守卫·火讨伐",
    "雷霆树妖讨伐",
    "维·索拉斯讨伐",
    "不死王瑞西塔尔讨伐",
    "橙悚机兵",
    "闪哭机兵",
    "暗凛机兵",
    "始龙之眼",
    "为你奏响的镇魂歌",
    "圣夜的淘气鬼",
    "怨炎精灵兽",
    "水狂精灵兽",
    "魁雷精灵兽",
    "威风精灵兽",
    "巫光精灵兽",
    "暗唤精灵兽",
    "方舟守护者讨伐",
    "赤之女王讨伐",
    "青之女王讨伐",
    "碧之女王讨伐",
    "皓之女王讨伐",
    "墨之女王讨伐",
    "伊尔昂斯拉讨伐",
    "伊尔梅塔雷讨伐",
    "碧愁机兵",
    "金之女王讨伐",
    "伊尔格拉乌讨伐",
    "伊劳德雷斯讨伐",
    "伊萨巴迪卡讨伐",
    "伊尔考普斯讨伐",
)

#: ``{行名: M}`` = ``scene/lords.py`` 的 ``max_tiers``（★只收**有仓内证据**的 M★）。
#: 表里没有的行按 ``M=None`` 处理（= pending / 未采集）—— 与真源里 ``max_tiers=None`` 等价：
#: 不参与 M 冲突判定，链未采集时仍会给 ``difficulty=None`` 的目标。
_LORDS_M_SNAPSHOT: dict = {
    "猩红巨熊讨伐": 4,
    "背鳍三兄弟讨伐": 4,
    "八岐大蛇讨伐": 4,
    "艾基尔·嫉妒讨伐": 4,
    "妖狐讨伐": 4,
    "无猾机兵": 5,
    "红嫉机兵": 4,
    "苍叹机兵": 4,
}

#: ``{行名: 解锁链}`` = ``scene/lords.py`` 的 ``tier_chain``（★只收**已验证**的完整链★）。
#: 表里没有的行按 ``()`` 处理（= 链未采集）—— :func:`_PLAN_ROUND_SNAPSHOT` 会报 ``no_chain``
#: 并把档位交给运行时（详情页 ``NEW`` / ``首次报酬``），**绝不静默跳过**。
_LORDS_CHAIN_SNAPSHOT: dict = {
    "妖狐讨伐": ("中级", "高级", "高级+", "超级"),
    "红嫉机兵": ("中级", "高级", "高级+", "超级"),
}

#: ``{行名: 行名容错正则}`` = ``scene/lords.py`` 的 ``row_regex``（★只收与 ``^{行名}$`` 不同的★）。
#: 表里没有的行按 ``^{行名}$`` 处理（= 真机没见过别的读法）。
_LORDS_ROW_REGEX_SNAPSHOT: dict = {
    "红嫉机兵": r"^红嫉族?机兵$",
}

#: ``{行名: kind}`` = ``scene/lords.py`` 的 ``kind``（``lord`` / ``joss``）。
#: ★它是**页签归属的唯一依据**★（#100 导航：页签由目标子族的 kind 决定，不看行名后缀 ——
#: ``无猾机兵`` / ``始龙之眼`` 都不带「讨伐」但都是降临讨伐成员）。
_LORDS_KIND_SNAPSHOT: dict = {
    '猩红巨熊讨伐': 'lord',
    '背鳍三兄弟讨伐': 'lord',
    '八岐大蛇讨伐': 'lord',
    '艾基尔·嫉妒讨伐': 'lord',
    '妖狐讨伐': 'lord',
    '诅咒弧魔艾基尔讨伐': 'lord',
    '无猾机兵': 'joss',
    '红嫉机兵': 'joss',
    '苍叹机兵': 'joss',
    '管理者讨伐': 'lord',
    'Sec-5200Li讨伐': 'lord',
    '白虎讨伐': 'lord',
    '风将獠牙骑士讨伐': 'lord',
    '寄居蟹船长讨伐': 'lord',
    '潮汐巨妖讨伐': 'lord',
    '废墟魔像讨伐': 'lord',
    '废墟守卫·火讨伐': 'lord',
    '雷霆树妖讨伐': 'lord',
    '维·索拉斯讨伐': 'lord',
    '不死王瑞西塔尔讨伐': 'lord',
    '橙悚机兵': 'joss',
    '闪哭机兵': 'joss',
    '暗凛机兵': 'joss',
    '始龙之眼': 'joss',
    '为你奏响的镇魂歌': 'joss',
    '圣夜的淘气鬼': 'joss',
    '怨炎精灵兽': 'joss',
    '水狂精灵兽': 'joss',
    '魁雷精灵兽': 'joss',
    '威风精灵兽': 'joss',
    '巫光精灵兽': 'joss',
    '暗唤精灵兽': 'joss',
    '方舟守护者讨伐': 'joss',
    '赤之女王讨伐': 'joss',
    '青之女王讨伐': 'joss',
    '碧之女王讨伐': 'joss',
    '皓之女王讨伐': 'joss',
    '墨之女王讨伐': 'joss',
    '伊尔昂斯拉讨伐': 'joss',
    '伊尔梅塔雷讨伐': 'joss',
    '碧愁机兵': 'joss',
    '金之女王讨伐': 'joss',
    '伊尔格拉乌讨伐': 'joss',
    '伊劳德雷斯讨伐': 'joss',
    '伊萨巴迪卡讨伐': 'joss',
    '伊尔考普斯讨伐': 'joss',
}

#: ``{kind: 页签名}`` = ``scene/lords.SUBFAMILY_BY_KIND`` 的逐字冻结。
_SUBFAMILY_BY_KIND_SNAPSHOT: dict = {"lord": "领主战", "joss": "降临讨伐"}


@dataclass(frozen=True)
class _RowReadingSnapshot:
    """``scene/lords_unlock.RowReading`` 的冻结版（字段与派生属性逐一照抄）。"""

    name: str
    n: int
    m: int
    name_box: tuple
    progress_box: tuple

    @property
    def pair(self) -> tuple:
        """``(N, M)``。"""
        return (self.n, self.m)

    @property
    def complete(self) -> bool:
        """该领主是否已 ``M/M``（= 已解禁到底，连详情页都不用进）。"""
        return self.n == self.m


@dataclass(frozen=True)
class _ProblemSnapshot:
    """``scene/lords_unlock.Problem`` 的冻结版：一行「读到了、但这一轮没法按它打」的原因。"""

    kind: str
    row_name: str
    detail: str


@dataclass(frozen=True)
class _TargetSnapshot:
    """``scene/lords_unlock.Target`` 的冻结版：本轮要打的**一个**目标（哪一行 + 哪一档）。"""

    row_name: str
    difficulty: object
    n: int
    m: int

    @property
    def pair(self) -> tuple:
        """``(行名, 档位)``。"""
        return (self.row_name, self.difficulty)

    @property
    def tier_index(self) -> int:
        """该档在解锁链上的**位置**（0 = 起始档；``N`` 个已通关 ⇒ 目标 = ``链[N]``）。"""
        return self.n


@dataclass(frozen=True)
class _RoundPlanSnapshot:
    """``scene/lords_unlock.RoundPlan`` 的冻结版（纯数据）。"""

    targets: tuple
    all_done: bool
    rows: tuple
    problems: tuple = ()

    @property
    def pairs(self) -> tuple:
        """本轮要打的 ``[(行名, 档位), ...]``（按列表页顺序）。"""
        return tuple(target.pair for target in self.targets)

    @property
    def needs_detail(self) -> tuple:
        """档位待定的目标（静态链未采集）—— 到详情页按 ``NEW``/``首次报酬`` 定档。"""
        return tuple(t for t in self.targets if t.difficulty is None)


class _LordsDataErrorSnapshot(ValueError):
    """``scene/lords_unlock.LordsDataError`` 的冻结版：读数脏到无法规划（★绝不静默跳过★）。"""


@dataclass(frozen=True)
class _UnlockStateSnapshot:
    """``scene/lords_unlock.UnlockState`` 的冻结版（:func:`_SHOULD_STOP_SNAPSHOT` 的输入）。"""

    all_done: bool = False
    rows_read: int = 0
    planned: int = 0
    played: int = 0
    sessions: int = 0
    no_progress_rounds: int = 0
    session_cap: int = _SESSION_CAP_SNAPSHOT
    idle_round_limit: int = _IDLE_ROUND_LIMIT_SNAPSHOT


@dataclass(frozen=True)
class _LordSnapshot:
    """``scene/lords.Lord`` 在**判定里用得到的那几项**（不在场的字段不编造）。"""

    row_name: str
    row_regex: str
    max_tiers: object
    tier_chain: tuple
    #: ``scene/lords.py`` 的 ``kind``（``lord`` / ``joss``）—— 页签归属的唯一依据（#100 导航）。
    kind: str = ""

    def unlock_requires(self, difficulty: str) -> tuple:
        """打 ``difficulty`` 这一档**必须先通关**的档（= 链上所有更低的档，逐字照抄真源）。"""
        if difficulty not in self.tier_chain:
            return ()
        return tuple(self.tier_chain[: self.tier_chain.index(difficulty)])


def _snapshot_registry() -> tuple:
    """安装态花名册：按 ``scene/lords.LORDS`` 的行名序，用上面三张表拼出条目。"""
    return tuple(
        _LordSnapshot(
            row_name=name,
            row_regex=_LORDS_ROW_REGEX_SNAPSHOT.get(name) or "^" + name + "$",
            max_tiers=_LORDS_M_SNAPSHOT.get(name),
            tier_chain=_LORDS_CHAIN_SNAPSHOT.get(name, ()),
            kind=_LORDS_KIND_SNAPSHOT.get(name, ""),
        )
        for name in _LORDS_ROWS_SNAPSHOT
    )


_SNAPSHOT_REGISTRY: tuple = _snapshot_registry()
_SNAPSHOT_BY_ROW_NAME: dict = {entry.row_name: entry for entry in _SNAPSHOT_REGISTRY}


# -- 冻结逻辑（逐字 = scene/lords_unlock.py 的同名函数）-------------------------
def _PARSE_PROGRESS_SNAPSHOT(text: str):
    """冻结版 :func:`scene.lords_unlock.parse_progress`：NFKC → 冻结正则 → ``(N, M)`` / ``None``。

    ★只做语法判定★：``N > M`` 照样返回 ``(N, M)``（语义脏数据由
    :func:`_PLAN_ROUND_SNAPSHOT` 抛错）；``M == 0`` 在语法上毫无意义，直接当读错。
    """
    if not text:
        return None
    # NFKC：全角数字/全角斜杠/全角冒号 → 半角（真机帧里两种都出现过）
    normalized = unicodedata.normalize("NFKC", str(text))
    match = _PROGRESS_RES_SNAPSHOT.search(normalized)
    if match is None:
        return None
    n, m = int(match.group(1)), int(match.group(2))
    if m <= 0:
        return None
    return (n, m)


def _center_snapshot(box):
    """框中心（720 空间）。★浮点，不取整★；框解不开返回 ``None``（Rect 兼容见 :func:`_box_xywh`）。"""
    return _box_center(box)


def _is_name_candidate_snapshot(text: str) -> bool:
    """这段文本有没有资格当「领主行名」（逐字照抄真源）。"""
    stripped = (text or "").strip()
    if not stripped or stripped in _NOT_A_ROW_NAME_SNAPSHOT:
        return False
    if _PARSE_PROGRESS_SNAPSHOT(stripped) is not None:      # 进度自己不是行名
        return False
    if re.fullmatch(r"[\d\s/|\\⁄╱.,:：]+", stripped):        # 纯数字/纯符号不是行名
        return False
    return True


def _row_sort_key_snapshot(row):
    """行排序键 = ``(行名框 y, 行名框 x)``（解包，不写 ``name_box[0]`` / ``[1]``）。"""
    values = _box_xywh(getattr(row, "name_box", None))
    if values is None:
        return (0, 0)
    x, y, _w, _h = values
    return (y, x)


def _GROUP_ROWS_SNAPSHOT(
    items,
    *,
    max_dy: int = _MAX_NAME_DY_SNAPSHOT,
    min_left_gap: int = _MIN_NAME_LEFT_GAP_SNAPSHOT,
) -> tuple:
    """冻结版 :func:`scene.lords_unlock.group_progress_rows`：一屏 OCR 项 → ``(rows, orphans)``。

    归属判据是**几何**（进度在行名右侧、纵向间距 ≤ ``max_dy``、取纵向最近再取横向更靠右），
    读到了 ``通关数`` 却挂不上行名的进 ``orphans``（★不静默丢★）。
    """
    materialized = []
    for text, box in items:
        box4 = _box4_int(box)          # ★Rect 也认；解不开的框跳过（绝不 len() 崩）★
        if box4 is None:
            continue
        materialized.append((str(text or "").strip(), box4))

    names = [item for item in materialized if _is_name_candidate_snapshot(item[0])]
    rows = []
    orphans = []

    for text, box in materialized:
        parsed = _PARSE_PROGRESS_SNAPSHOT(text)
        if parsed is None:
            continue
        progress_center = _center_snapshot(box)
        if progress_center is None:                       # 解不开的框进 orphans（不静默丢）
            orphans.append((text, box))
            continue
        progress_cx, progress_cy = progress_center
        best = None
        for name_text, name_box in names:
            name_center = _center_snapshot(name_box)
            if name_center is None:
                continue
            name_cx, name_cy = name_center
            name_left, _name_y, name_w, _name_h = name_box   # 解包，不写 box[0] + box[2]
            if name_cx >= progress_cx:                     # 行名必须在进度左侧
                continue
            if progress_cx - (name_left + name_w) < min_left_gap:
                continue                                    # 太挤：不是「左名右进度」的版式
            dy = abs(progress_cy - name_cy)
            if dy > max_dy:
                continue
            # 先比纵向最近，再比横向更靠右（同一行内更贴近进度的那个）
            key = (dy, -name_cx)
            if best is None or key < best[0:2]:
                best = (dy, -name_cx, (name_text, name_box))
        if best is None:
            orphans.append((text, box))
            continue
        rows.append(
            _RowReadingSnapshot(
                name=best[2][0],
                n=parsed[0],
                m=parsed[1],
                name_box=best[2][1],
                progress_box=box,
            )
        )

    rows.sort(key=_row_sort_key_snapshot)
    return (tuple(rows), tuple(orphans))


def _as_reading_snapshot(row) -> tuple:
    """把一行读数归一成 ``(行名, N, M)``（容忍本文件的 RowReading / 三元组 / 映射）。"""
    if isinstance(row, _RowReadingSnapshot):
        return (row.name, row.n, row.m)
    if isinstance(row, Mapping):
        return (str(row.get("name", "")), int(row["n"]), int(row["m"]))
    name, n, m = row
    return (str(name), int(n), int(m))


def _ROUND_GAINED_SNAPSHOT(previous, rows) -> tuple:
    """冻结版 :func:`scene.lords_unlock.round_gained`：本轮**是否有任何领主新解锁**。

    某行 ``N`` 比上一轮**大**即算；首次见到的行也算（``N >= 0 > -1``）。
    """
    prev = dict(previous or {})
    gained = []
    for raw in rows:
        name, n, _m = _as_reading_snapshot(raw)
        if n > prev.get(name, -1):
            gained.append(name)
    return (bool(gained), tuple(gained))


def _index_registry_snapshot(registry) -> dict:
    """``{行名: 条目}``（``registry`` 缺省 = 安装态花名册）。"""
    if registry is None:
        registry = _SNAPSHOT_REGISTRY
    return {entry.row_name: entry for entry in registry}


def _PLAN_ROUND_SNAPSHOT(rows, registry=None):
    """冻结版 :func:`scene.lords_unlock.plan_round`（规则 / 顺序 / 文案逐字照抄）。

    ``rows``：列表页一趟的读数（:class:`_RowReadingSnapshot` / 三元组 / 映射）。
    ``registry``：静态花名册（缺省 = :data:`_SNAPSHOT_REGISTRY`）；真源条目也认
    （只用到 ``row_name`` / ``max_tiers`` / ``tier_chain`` / ``unlock_requires``）。
    """
    index = _index_registry_snapshot(registry)
    targets = []
    problems = []
    readings = []
    seen = {}

    for raw in rows:
        name, n, m = _as_reading_snapshot(raw)
        if m <= 0:
            raise _LordsDataErrorSnapshot(f"行「{name}」的 通关数 {n}/{m} 分母 ≤ 0 —— 这不是档数读数")
        if n > m:
            raise _LordsDataErrorSnapshot(
                f"行「{name}」的 通关数 {n}/{m} 分子大于分母 —— 脏数据（已通关档数不可能超过总档数）；"
                f"正常形态见 tools/frames/lord_page_tab_lord.png（1/4、3/4、1/4、4/4）。"
                f"★不当成 0 档、也不静默跳过★：读错就重读，别按错的读数去打。"
            )
        readings.append(raw if isinstance(raw, _RowReadingSnapshot) else None)

        if name in seen:
            if seen[name] != (n, m):
                problems.append(
                    _ProblemSnapshot(
                        _PROBLEM_DUPLICATE_SNAPSHOT,
                        name,
                        f"同一行读到两个不同的 通关数：先 {seen[name][0]}/{seen[name][1]}、"
                        f"后 {n}/{m} —— 只按第一次的读数规划（多趟拼接时请先去重）",
                    )
                )
            continue
        seen[name] = (n, m)

        if n == m:
            continue                              # 已解禁到底

        entry = index.get(name)
        if entry is None:
            problems.append(
                _ProblemSnapshot(
                    _PROBLEM_UNKNOWN_ROW_SNAPSHOT,
                    name,
                    f"列表页读到「{name}」的通关数 {n}/{m}，但静态花名册（scene/lords.py）没有这一行 —— "
                    f"OCR 读错 / 新领主 / 活动行；按错的字去点行 = 点错人，故本轮不为它规划",
                )
            )
            continue

        chain = tuple(entry.tier_chain)
        static_m = entry.max_tiers if entry.max_tiers is not None else (len(chain) or None)
        if static_m is not None and static_m != m:
            problems.append(
                _ProblemSnapshot(
                    _PROBLEM_M_CONFLICT_SNAPSHOT,
                    name,
                    f"列表页 M={m}，静态 max_tiers={entry.max_tiers} / 链长={len(chain)} —— "
                    f"两边对不上就不按任何一边取档（宁可不打，也不打错档）；"
                    f"需要一帧新的列表页或详情页读数来定谁对",
                )
            )
            continue

        if not chain:
            targets.append(_TargetSnapshot(name, None, n, m))
            problems.append(
                _ProblemSnapshot(
                    _PROBLEM_NO_CHAIN_SNAPSHOT,
                    name,
                    f"静态解锁链未采集（scene/lords.py 的 tier_chain 为空）⇒ 档位待定："
                    f"到详情页按 `NEW` / `首次报酬` 定档（不是跳过，是交给运行时判据）",
                )
            )
            continue

        if len(chain) != m:
            problems.append(
                _ProblemSnapshot(
                    _PROBLEM_M_CONFLICT_SNAPSHOT,
                    name,
                    f"列表页 M={m}，静态链只有 {len(chain)} 档（{chain}）—— 链不完整，不取档",
                )
            )
            continue

        difficulty = chain[n]
        if difficulty not in _DIFFICULTIES_SNAPSHOT:
            problems.append(
                _ProblemSnapshot(
                    _PROBLEM_M_CONFLICT_SNAPSHOT,
                    name,
                    f"链上第 {n} 档 {difficulty!r} 不在难度词表 {_DIFFICULTIES_SNAPSHOT} 里 —— 静态数据坏了",
                )
            )
            continue
        requires = entry.unlock_requires(difficulty)
        if len(requires) != n:
            problems.append(
                _ProblemSnapshot(
                    _PROBLEM_M_CONFLICT_SNAPSHOT,
                    name,
                    f"已通关 {n} 档，但「打 {difficulty} 需先通关 {len(requires)} 档」"
                    f"（{requires}）—— 解锁链与 N 不自洽，不取档",
                )
            )
            continue
        targets.append(_TargetSnapshot(name, difficulty, n, m))

    all_done = bool(seen) and all(n == m for (n, m) in seen.values())
    return _RoundPlanSnapshot(
        targets=tuple(targets),
        all_done=all_done,
        rows=tuple(r for r in readings if r is not None),
        problems=tuple(problems),
    )


def _SHOULD_STOP_SNAPSHOT(state) -> tuple:
    """冻结版 :func:`scene.lords_unlock.should_stop`（分支顺序与用户可见文案逐字照抄）。

    1. 全 ``M/M``（主；``rows_read == 0`` 时按**失败**收工，不许假收工）
    2. 场次上限（兜底）
    3. ★防死循环★：``played <= 0`` 一律停（零目标 / 计划了却没打，两种文案不同）
    4. 连续 ``idle_round_limit`` 轮无新解锁（兜底）
    """
    if state.all_done:
        if state.rows_read <= 0:
            # ★注意措辞★：这里**不许**出现「全部解禁」这四个字 —— 守卫用
            # 「reason 里有没有『全部解禁』」来区分「真收工」与「假收工」。
            return (
                True,
                "收工（可疑）：判了「全通」却一行都没读到 —— "
                "把「零行」当全通就是假收工，按失败收工，绝不假记账",
            )
        return (
            True,
            f"全部解禁：本轮读到 {state.rows_read} 个领主，全部 `通关数 M/M`"
            f"（累计 {state.sessions} 场）",
        )

    if state.sessions >= state.session_cap:
        return (
            True,
            f"场次上限 {state.session_cap} 已用尽（累计 {state.sessions} 场，"
            f"本轮计划 {state.planned} 个）—— 尚未全通，带原因收工",
        )

    if state.played <= 0:
        if state.planned == 0:
            return (
                True,
                f"防死循环：本轮零目标（读到 {state.rows_read} 行，但没有一行 N<M 可打）"
                f"却未判全通 —— 继续下去只会空转，带原因收工",
            )
        return (
            True,
            f"防死循环：本轮计划 {state.planned} 个目标却一场没打（累计 {state.sessions} 场）"
            f"—— 每轮必须至少打一场才允许继续，带原因收工",
        )

    if state.no_progress_rounds >= state.idle_round_limit:
        return (
            True,
            f"连续 {state.no_progress_rounds} 轮没有新解锁（兜底阈值 "
            f"{state.idle_round_limit}，累计 {state.sessions} 场）—— 带原因收工",
        )

    return (False, "")


class _SnapshotLogic:
    """安装态回退的**判定真源替身**：字段名与 ``scene.lords_unlock`` 逐一相同。

    只有 :func:`_logic` 会返回它 —— 调方（:class:`LordsProgressRecognition`）不感知差别。
    """

    # kind 取值
    PROBLEM_UNKNOWN_ROW = _PROBLEM_UNKNOWN_ROW_SNAPSHOT
    PROBLEM_NO_CHAIN = _PROBLEM_NO_CHAIN_SNAPSHOT
    PROBLEM_M_CONFLICT = _PROBLEM_M_CONFLICT_SNAPSHOT
    PROBLEM_DUPLICATE = _PROBLEM_DUPLICATE_SNAPSHOT
    # 阈值 / 判据常量
    SESSION_CAP = _SESSION_CAP_SNAPSHOT
    IDLE_ROUND_LIMIT = _IDLE_ROUND_LIMIT_SNAPSHOT
    PROGRESS_RE = _PROGRESS_RE_SNAPSHOT
    MAX_NAME_DY = _MAX_NAME_DY_SNAPSHOT
    MIN_NAME_LEFT_GAP = _MIN_NAME_LEFT_GAP_SNAPSHOT
    NOT_A_ROW_NAME = _NOT_A_ROW_NAME_SNAPSHOT
    # 数据类 / 异常
    RowReading = _RowReadingSnapshot
    Problem = _ProblemSnapshot
    Target = _TargetSnapshot
    RoundPlan = _RoundPlanSnapshot
    UnlockState = _UnlockStateSnapshot
    LordsDataError = _LordsDataErrorSnapshot
    # 纯函数
    parse_progress = staticmethod(_PARSE_PROGRESS_SNAPSHOT)
    group_progress_rows = staticmethod(_GROUP_ROWS_SNAPSHOT)
    round_gained = staticmethod(_ROUND_GAINED_SNAPSHOT)
    plan_round = staticmethod(_PLAN_ROUND_SNAPSHOT)
    should_stop = staticmethod(_SHOULD_STOP_SNAPSHOT)


# ---------------------------------------------------------------------------
# 取真源：仓库态 ``scene.*`` / 安装态冻结快照（两条路都不通 → None，绝不抛穿）
# ---------------------------------------------------------------------------
_SNAPSHOT_ANNOUNCED = False


def _announce_snapshot_once() -> None:
    """安装态回落只播报**一次**（每帧都打会把 agent 日志刷爆）。"""
    global _SNAPSHOT_ANNOUNCED
    if _SNAPSHOT_ANNOUNCED:
        return
    _SNAPSHOT_ANNOUNCED = True
    print(
        "[lords] 取不到 scene/lords_unlock.py（安装态：install/agent 没有 scene/）—— "
        "改用本文件的逐字冻结快照（_PARSE_PROGRESS_SNAPSHOT / _PLAN_ROUND_SNAPSHOT / "
        "_SHOULD_STOP_SNAPSHOT），行为与真源逐项等价（hooks_100 两条守卫钉住）"
    )


def _scene_logic():
    """``scene.lords_unlock``（判定真源，纯逻辑）；安装态（模块不在场）返回 ``None``。

    ★只吞 ``ModuleNotFoundError``★：安装态没有 ``scene/`` 是一种**预期内**的缺席；
    真源在场却自己炸（语法错 / 数据错）必须响亮失败 —— 那才是需要人看的问题，
    悄悄换成快照会把「真源坏了」伪装成「一切正常」。
    """
    try:
        import importlib

        return importlib.import_module("scene.lords_unlock")
    except ModuleNotFoundError:
        return None


def _logic():
    """判定真源：仓库态 = ``scene.lords_unlock``；安装态 = 本文件的冻结快照。

    ★两条路都不通时返回 ``None``★（不崩、也不假成功）：调用方据此**不命中**，
    见 :data:`INSTALL_STATE_REASON`。
    """
    scene = _scene_logic()
    if scene is not None:
        return scene
    _announce_snapshot_once()
    return _SnapshotLogic


def _scene_lords():
    """``scene.lords``（静态花名册：M / 解锁链 / 行名正则）；安装态返回 ``None``。"""
    try:
        import importlib

        return importlib.import_module("scene.lords")
    except ModuleNotFoundError:
        return None


def _registry():
    """静态花名册：仓库态 = ``scene.lords.LORDS``；安装态 = 冻结花名册。

    ★两种条目可以混用★（``_PLAN_ROUND_SNAPSHOT`` / 真源 ``plan_round`` 都只读
    ``row_name`` / ``max_tiers`` / ``tier_chain`` / ``unlock_requires``），
    所以「只有 ``scene/lords.py`` 在场、``scene/lords_unlock.py`` 不在」这种半残状态也不会炸。
    """
    scene = _scene_lords()
    if scene is None:
        return _SNAPSHOT_REGISTRY
    return tuple(scene.LORDS)


def _row_regex(row_name):
    """该行名的**容错正则**（``scene.lords`` 里真机实测过的变体，如 ``^红嫉族?机兵$``）。

    安装态取冻结表（表里没有的行 = ``^{行名}$``）；不在花名册里的行返回 ``None``（= 不猜）。
    """
    scene = _scene_lords()
    if scene is None:
        entry = _SNAPSHOT_BY_ROW_NAME.get(row_name)
    else:
        entry = scene.by_row_name(row_name)
    return entry.row_regex if entry is not None else None


def _detail():
    """``agent.side_impl``（详情页判据 + 难度行→战斗框的几何配对）；取不到返回 ``None``。"""
    try:
        import side_impl  # noqa: PLC0415 - 惰性：它 import numpy，本模块要能在最小环境被 import
    except Exception as exc:  # noqa: BLE001
        print(f"[lords] 取不到 agent/side_impl.py（详情页判据/战斗框配对）：{exc!r}")
        return None
    return side_impl


# ---------------------------------------------------------------------------
# ★导航（页签切换 + 列表滚动）的安装态冻结快照★
# 真源 = ``scene/lords_nav.py``（纯数据 + 纯逻辑）+ ``scene/page_rules.py``（页签判据）
#        + ``scene/lords.py``（kind）+ ``special_dungeon.json::SpecialScrollList``（滚动几何）。
# 为什么需要：``agent/`` 会被整个拷到 ``install/agent``（那里**没有** ``scene/``）。
# 纪律与上一条快照同：**别手改快照** —— 先改 ``scene/``，再把同一份抄过来；
# ``tools/contract_hooks/hooks_100.py`` 的 ``lords-nav-snapshot-parity`` 逐项钉住数据 +
# 行为表（页签确认 / 切换判决 / 到底判定 / 去重 / 滚动闸）。
# ---------------------------------------------------------------------------
#: 两个子族页签（= ``scene/lords_nav.LORD_TABS``；顺序 = 界面从左到右）。
_LORD_TABS_SNAPSHOT: tuple = ("领主战", "降临讨伐")
_LIST_PAGE_ANCHOR_SNAPSHOT = "更新列表"
_TAB_LABELS_ALWAYS_PRESENT_SNAPSHOT = True
_TAB_SWITCH_MAX_ATTEMPTS_SNAPSHOT = 1
_TAB_UNCONFIRMED_LIMIT_SNAPSHOT = 2
_TAB_CONFIRM_GRACE_SEC_SNAPSHOT = 4.0
_END_ANCHORS_SNAPSHOT: tuple = ()
_NAV_STUCK_SEC_SNAPSHOT = 30.0
_CONFIRM_BASIS_SNAPSHOT = (
    "切页签后的确认 = ①这一帧仍是列表页（读得到「更新列表」）∧ "
    "②可见行的族身份**一致**指向目标页签（scene/lords.py 的 kind + row_regex → SUBFAMILY_BY_KIND）。"
    "★「读得到页签标签」不算确认★：两个标签常驻同屏，读得到它什么也证明不了"
)

#: 滚动计划的冻结数值（= ``scene/lords_nav.SCROLL_PLAN``；真机出处见那里的 docstring）。
_SCROLL_TRAVEL_PX_SNAPSHOT = 400
_SCROLL_BEGIN_SNAPSHOT = (360, 1040)
_SCROLL_END_SNAPSHOT = (360, 640)
_SCROLL_DURATION_MS_SNAPSHOT = 800
_SCROLL_SETTLE_MS_SNAPSHOT = 2600
_SCROLL_MIN_INTERVAL_SEC_SNAPSHOT = 1.2
_SCROLL_MAX_PER_PAGE_SNAPSHOT = 80
_SCROLL_STABLE_TIMES_SNAPSHOT = 2
_SCROLL_NO_MOVE_PX_SNAPSHOT = 4
#: ★每轮扫描前「回顶部」的上滚次数上限★（= ``scene/lords_nav.SCROLL_PLAN.max_rewinds_per_page``；
#: 「到底」是相对滚动位置的概念 —— 战后列表停在被点行处，不回顶部就向下扫只会读到几行）。
_SCROLL_MAX_REWINDS_PER_PAGE_SNAPSHOT = 24
_LIST_BODY_SNAPSHOT = (440, 1180)

#: ★列表**行名** ROI★（= ``scene/lords_nav.ROW_ROI`` ← ``scene.options.TARGET_ROW_ROI``
#: ← ``assets/interface.json::SpecialEnterBoss`` 的行名 OCR ROI；720 空间 ``(150,440,320,800)``）。
#: ★行名只可能出现在列表体里★：标题/横幅/页签/底栏里的同名文字**一律不算**（真机 484 第二轮：
#: 模式页顶部的领主名 ``无猾机兵`` ``[157,154,379,94]`` 被当成列表行，连点 (346,201) 三次）。
#: ``hooks_122`` 的 ``lords-row-roi-title-not-row`` / ``lords-mode-snapshot-parity`` 钉住。
_ROW_ROI_SNAPSHOT = (150, 440, 320, 800)

#: ★屏幕边界★（= ``scene/lords_nav.SCREEN_W`` / ``SCREEN_H`` ← ``scene/pixels.BASE_W/BASE_H``）：
#: 「行在屏上」必须**整框**落在 720x1280 内。``_synthesize_items`` 的行 y = 460 + k*144，
#: 第 7 行起就超出 1280 —— 合成帧的框**不是屏幕位置**，绝不能拿它断言「行就在屏上」
#: （#100 回归：解禁 0 场）。hooks_122 的 ``lords-synth-frame-no-stuck`` 钉住。
_SCREEN_W_SNAPSHOT = 720
_SCREEN_H_SNAPSHOT = 1280

#: ★#100 第 4、5 个真机缺口的冻结副本★（页面状态 + 模式选择页 + 非列表页死线 + 过渡态）。
#: 真源 = ``scene/lords_nav.py`` 的同名常量 / ``page_state`` / ``loading_frame`` /
#: ``mode_evidence`` / ``non_list_stuck_reason``，以及 ``scene/page_rules.py`` 的五条判据；
#: 由 ``tools/contract_hooks/hooks_122.py`` 的 ``lords-mode-snapshot-parity``
#: **逐项 + 逐帧**对账（数据一项不相同就红）。
_LORDS_STATE_CITY_SNAPSHOT = "lords_city"
_LORDS_STATE_LIST_SNAPSHOT = "lords_list"
_LORDS_STATE_DETAIL_SNAPSHOT = "lords_detail"
_LORDS_STATE_TEAM_SNAPSHOT = "lords_team"
_LORDS_STATE_MODE_SNAPSHOT = "lords_mode"
_LORDS_STATE_BATTLE_SNAPSHOT = "lords_battle"
_LORDS_STATE_SETTLE_SNAPSHOT = "lords_settle"
#: ★过渡态★ 加载 / 过场中（= ``scene/lords_nav.LORDS_STATE_LOADING``）。
_LORDS_STATE_LOADING_SNAPSHOT = "lords_loading"
_LORDS_STATE_UNKNOWN_SNAPSHOT = "lords_unknown"
_LORDS_STATES_SNAPSHOT: tuple = (
    _LORDS_STATE_LOADING_SNAPSHOT,
    _LORDS_STATE_BATTLE_SNAPSHOT,
    _LORDS_STATE_SETTLE_SNAPSHOT,
    _LORDS_STATE_MODE_SNAPSHOT,
    _LORDS_STATE_TEAM_SNAPSHOT,
    _LORDS_STATE_DETAIL_SNAPSHOT,
    _LORDS_STATE_LIST_SNAPSHOT,
    _LORDS_STATE_CITY_SNAPSHOT,
    _LORDS_STATE_UNKNOWN_SNAPSHOT,
)
#: ★主动作状态（战斗/结算）★：整类排除在「非列表页死线」之外（一场仗打几分钟是正常的）。
_LORDS_ACTIVE_STATES_SNAPSHOT: tuple = (
    _LORDS_STATE_BATTLE_SNAPSHOT,
    _LORDS_STATE_SETTLE_SNAPSHOT,
)
#: ★「点过【挑战】」的闩**放开证据**★（= ``scene/lords_nav.LORDS_CHALLENGE_RELEASE_STATES``；
#: 真机 484 第 3 轮验收：战斗/结算实际发生了，旧实现却只在 180s 超时时放闩 ⇒ 每场白等 ~182s）。
#: ★只放**正向认出**的别的页★：team（还在编队页）/ loading（转场）/ unknown（认不出）
#: 一律不放 —— 宁可多等兜底超时，不可凭一张认不出的帧再点一次挑战。
_LORDS_CHALLENGE_RELEASE_STATES_SNAPSHOT: tuple = (
    _LORDS_STATE_BATTLE_SNAPSHOT,
    _LORDS_STATE_SETTLE_SNAPSHOT,
    _LORDS_STATE_LIST_SNAPSHOT,
    _LORDS_STATE_DETAIL_SNAPSHOT,
    _LORDS_STATE_CITY_SNAPSHOT,
    _LORDS_STATE_MODE_SNAPSHOT,
)
#: ★加载/过场帧的文案锚点★（= ``scene/lords_nav.LORDS_LOADING_ANCHORS``；与项目唯一一份
#: 画面分类同口径：``common.json::PubLoadingText`` 的「请耐心等待」+ 健康忠告页）。
_LORDS_LOADING_ANCHORS_SNAPSHOT: tuple = ("请耐心等待", "健康游戏忠告")
#: ★过渡态集合★（= ``scene/lords_nav.LORDS_TRANSITION_STATES``）：不累加「无进展」计时。
#: ★``lords_unknown`` 绝不在此列★ —— 未知画面的死线必须保留。
_LORDS_TRANSITION_STATES_SNAPSHOT: tuple = (
    _LORDS_STATE_LOADING_SNAPSHOT,
    "loading",
    "relogin",
)

#: 模式选择页的四段文案 + 两个象限（= ``scene/lords_nav.LORDS_MODE_*``，720 空间）。
_LORDS_MODE_SOLO_SNAPSHOT = "单人游戏"
_LORDS_MODE_SOLO_NOTE_SNAPSHOT = "单人挑战领主"
_LORDS_MODE_MULTI_SNAPSHOT = "多人游戏"
_LORDS_MODE_MULTI_NOTE_SNAPSHOT = "召集同伴挑战领主"
_LORDS_MODE_SOLO_ROI_SNAPSHOT = (0, 0, 360, 640)
_LORDS_MODE_MULTI_ROI_SNAPSHOT = (360, 640, 360, 640)
_LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY_SNAPSHOT = 200
#: ★#100 第 7 个真机缺口★ 编队页正向锚 + 换点阶梯（= ``scene/lords_nav`` 的同名常量）。
#: 「到了编队页」= 有【挑战】∧ 三个锚里至少一个；点「单人游戏」= 中心 → 下方100 → 右侧120 →
#: 下方180，最多 4 个点。★第 9 个缺口之后等待改为**轮询**（``_LORDS_MODE_POLL_*``）★：
#: ``_LORDS_MODE_CLICK_WAIT_SEC_SNAPSHOT`` 只作兼容/文档用。hooks_122 的
#: ``lords-mode-snapshot-parity`` 逐项对账。
_TEAM_ANCHORS_SNAPSHOT: tuple = ("SET", "Party", "自动续战")
_LORDS_MODE_CLICK_LADDER_SNAPSHOT: tuple = (
    ("中心", 0, 0),
    ("下方", 0, 100),
    ("右侧", 120, 0),
    ("底部", 0, 180),
)
_LORDS_MODE_CLICK_WAIT_SEC_SNAPSHOT = 2.5
_LORDS_MODE_MAX_ATTEMPTS_SNAPSHOT = len(_LORDS_MODE_CLICK_LADDER_SNAPSHOT)
_LORDS_MODE_CONFIRM_GRACE_SEC_SNAPSHOT = 4.0

#: 非列表页死线（= ``scene/lords_nav.NON_LIST_STUCK_SEC`` / ``NON_LIST_STUCK_REASON``）。
_NON_LIST_STUCK_SEC_SNAPSHOT = 9.0
_NON_LIST_STUCK_REASON_SNAPSHOT = (
    "收工 —— 卡在「{state}」这类非列表页 {seconds:.0f}s 没有任何进展"
    "（不在列表页，无法导航）"
)

#: 页面判据的冻结副本（= ``scene/page_rules.py`` 的五条；★真源唯一，这里只做安装态替身★）。
#: 只实现 OCR / And 两种形态（与 ``scene.lords_nav._recognition_hit`` 逐字同形）。
_PAGE_RULE_NAMES_SNAPSHOT: tuple = ("战斗HUD", "结算页", "编队页", "详情页", "主城")
_PAGE_RULE_RECOGNITION_SNAPSHOT: dict = {
    "战斗HUD": {
        "type": "And",
        "param": {
            "all_of": [
                {"type": "OCR", "param": {"expected": ["时间 \\d+:\\d+"]}},
                {"type": "OCR", "param": {"expected": ["分数 \\d"]}},
            ]
        },
    },
    "结算页": {"type": "OCR", "param": {"expected": ["^继续$"]}},
    "编队页": {
        "type": "OCR",
        # ★不抄字面量★：`battle_loop_core.PAGE_CHALLENGE_PATTERNS` 是这份判据在 agent 侧的
        # **唯一**快照（hooks_112 明令：`^挑战(→)?$` 在 agent/ 里只许三处合法落点 —— 页面状态 /
        # 点击判据 / 编队页锚点）。这里**引用同一个对象**，绝不写第四份（第四份 = 第三套真源）。
        "param": {"expected": list(PAGE_CHALLENGE_PATTERNS), "roi": [180, 1000, 400, 180]},
    },
    "详情页": {"type": "OCR", "param": {"expected": ["推荐编成"]}},
    "主城": {"type": "OCR", "param": {"expected": ["领主战"], "roi": [480, 1080, 240, 140]}},
}


def _mode_center(box):
    """框中心（720 空间浮点）—— 只给模式页证据/死线用。

    ★一律走 :func:`_box_xywh`★：不写 ``box[...]`` / ``len(box)``（``maa.define.Rect`` 没有
    ``__len__``，#120 的 TypeError 就是它；hooks_120 的静态挂点按 AST 抓这两种写法）。
    """
    x, y, w, h = _box_xywh(box)
    return (x + w / 2.0, y + h / 2.0)


class _ModeEvidenceSnapshot:
    """``scene/lords_nav.ModeEvidence`` 的逐字冻结副本（四段文案 + 象限 + 单人卡更高）。"""

    def __init__(self, solo=None, solo_note=None, multi=None, multi_note=None):
        self.solo = solo
        self.solo_note = solo_note
        self.multi = multi
        self.multi_note = multi_note

    @property
    def is_mode_page(self) -> bool:
        if self.solo is None or self.solo_note is None:
            return False
        if self.multi is None or self.multi_note is None:
            return False
        return (
            _mode_center(self.multi)[1] - _mode_center(self.solo)[1]
        ) >= _LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY_SNAPSHOT

    @property
    def solo_click_box(self):
        return self.solo if self.is_mode_page else None

    def summary(self) -> str:
        def _at(box):
            if box is None:
                return "缺"
            cx, cy = _mode_center(box)
            return f"({cx:.0f},{cy:.0f})"

        return (
            f"单人游戏{_at(self.solo)}/单人挑战领主{_at(self.solo_note)}/"
            f"多人游戏{_at(self.multi)}/召集同伴挑战领主{_at(self.multi_note)}"
        )


def _MODE_TEXT_BOX_SNAPSHOT(items, text: str, roi):
    x, y, w, h = roi
    for item_text, box in items or []:
        if str(item_text or "").strip() != text:
            continue
        quad = _box4_snapshot(box)
        if quad is None:
            continue
        cx, cy = _mode_center(quad)
        if x <= cx <= x + w and y <= cy <= y + h:
            return quad
    return None


def _MODE_EVIDENCE_SNAPSHOT(items):
    return _ModeEvidenceSnapshot(
        solo=_MODE_TEXT_BOX_SNAPSHOT(items, _LORDS_MODE_SOLO_SNAPSHOT, _LORDS_MODE_SOLO_ROI_SNAPSHOT),
        solo_note=_MODE_TEXT_BOX_SNAPSHOT(
            items, _LORDS_MODE_SOLO_NOTE_SNAPSHOT, _LORDS_MODE_SOLO_ROI_SNAPSHOT
        ),
        multi=_MODE_TEXT_BOX_SNAPSHOT(
            items, _LORDS_MODE_MULTI_SNAPSHOT, _LORDS_MODE_MULTI_ROI_SNAPSHOT
        ),
        multi_note=_MODE_TEXT_BOX_SNAPSHOT(
            items, _LORDS_MODE_MULTI_NOTE_SNAPSHOT, _LORDS_MODE_MULTI_ROI_SNAPSHOT
        ),
    )


def _RECOGNITION_HIT_SNAPSHOT(items, recognition) -> bool:
    kind = str((recognition or {}).get("type") or "")
    param = (recognition or {}).get("param") or {}
    if kind == "OCR":
        expected = tuple(param.get("expected") or ())
        roi = param.get("roi")
        roi4 = None if not roi else (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
        for text, box in items or []:
            stripped = str(text or "")
            if not any(re.search(pattern, stripped) for pattern in expected):
                continue
            if roi4 is None:
                return True
            quad = _box4_snapshot(box)
            if quad is None:
                continue
            cx, cy = _mode_center(quad)
            if roi4[0] <= cx <= roi4[0] + roi4[2] and roi4[1] <= cy <= roi4[1] + roi4[3]:
                return True
        return False
    if kind == "And":
        return all(_RECOGNITION_HIT_SNAPSHOT(items, sub) for sub in (param.get("all_of") or ()))
    return False


def _PAGE_RULE_HIT_SNAPSHOT(items, name: str) -> bool:
    return _RECOGNITION_HIT_SNAPSHOT(items, _PAGE_RULE_RECOGNITION_SNAPSHOT[name])


def _LOADING_FRAME_SNAPSHOT(items) -> bool:
    """冻结版 :func:`scene.lords_nav.loading_frame`：加载/过场帧（锚点**子串**命中）。"""
    for text, _box in items or []:
        stripped = str(text or "")
        if any(anchor in stripped for anchor in _LORDS_LOADING_ANCHORS_SNAPSHOT):
            return True
    return False


def _TEAM_ANCHOR_HIT_SNAPSHOT(items):
    """冻结版 :func:`scene.lords_nav.team_anchor_hit`：编队页正向锚（子串匹配）。"""
    for text, _box in items or []:
        stripped = str(text or "")
        for anchor in _TEAM_ANCHORS_SNAPSHOT:
            if anchor in stripped:
                return anchor
    return None


def _TEAM_PAGE_CONFIRMED_SNAPSHOT(items) -> bool:
    """冻结版 :func:`scene.lords_nav.team_page_confirmed`：★正向证据★（挑战 + 锚）。"""
    if not _PAGE_RULE_HIT_SNAPSHOT(items, "编队页"):
        return False
    return _TEAM_ANCHOR_HIT_SNAPSHOT(items) is not None


#: ★#100 第 9 个真机缺口（点完「单人游戏」弹加成点数确认框）★ 的冻结副本
#: （= ``scene/lords_nav.LORDS_MODE_POLL_*`` / ``LORDS_MODE_BONUS_*`` / ``BonusDialog`` /
#: ``bonus_dialog``；hooks_122 的 ``lords-mode-snapshot-parity`` 逐项 + 逐帧对账）。
_LORDS_MODE_POLL_INTERVAL_SEC_SNAPSHOT = 0.4
_LORDS_MODE_POLL_TIMEOUT_SEC_SNAPSHOT = 8.0
_LORDS_MODE_STABLE_READS_SNAPSHOT = 2
_LORDS_MODE_STILL_MODE_READS_SNAPSHOT = 3
_LORDS_MODE_BONUS_QUESTION_ANCHORS_SNAPSHOT: tuple = ("领主加成点数", "增加报酬")
_LORDS_MODE_BONUS_ACCEPT_SNAPSHOT = "是"
_LORDS_MODE_BONUS_DECLINE_SNAPSHOT = "否"
_LORDS_MODE_BONUS_CHOICE_SNAPSHOT = _LORDS_MODE_BONUS_DECLINE_SNAPSHOT
_LORDS_MODE_MAX_DIALOG_CLICKS_SNAPSHOT = 1


class _BonusDialogSnapshot:
    """``scene/lords_nav.BonusDialog`` 的逐字冻结副本（问题锚 + 是/否按钮框）。"""

    def __init__(self, question=None, decline=None, accept=None):
        self.question = question
        self.decline = decline
        self.accept = accept

    @property
    def is_dialog(self) -> bool:
        return self.question is not None and self.decline is not None

    @property
    def decline_click_box(self):
        return self.decline if self.is_dialog else None

    def summary(self) -> str:
        def _at(box):
            if box is None:
                return "缺"
            cx, cy = _mode_center(box)
            return f"({cx:.0f},{cy:.0f})"

        return f"问题={self.question!r}/是{_at(self.accept)}/否{_at(self.decline)}"


def _EXACT_TEXT_BOX_SNAPSHOT(items, text: str):
    """冻结版 :func:`scene.lords_nav._exact_text_box`：逐字相等的 OCR 框（720 空间）。"""
    for item_text, box in items or []:
        if str(item_text or "").strip() != text:
            continue
        return _box4_snapshot(box)
    return None


def _BONUS_DIALOG_SNAPSHOT(items):
    """冻结版 :func:`scene.lords_nav.bonus_dialog`（问题锚 + 否/是 按钮）。"""
    question = None
    for text, _box in items or []:
        stripped = str(text or "")
        if any(anchor in stripped for anchor in _LORDS_MODE_BONUS_QUESTION_ANCHORS_SNAPSHOT):
            question = stripped
            break
    return _BonusDialogSnapshot(
        question=question,
        decline=_EXACT_TEXT_BOX_SNAPSHOT(items, _LORDS_MODE_BONUS_DECLINE_SNAPSHOT),
        accept=_EXACT_TEXT_BOX_SNAPSHOT(items, _LORDS_MODE_BONUS_ACCEPT_SNAPSHOT),
    )


def _MODE_CLICK_POINTS_SNAPSHOT(box):
    """冻结版 :func:`scene.lords_nav.mode_click_points`：框 → 换点阶梯四点（无效框返回空）。"""
    if box is None:
        return ()
    try:
        quad = _box4_snapshot(box)
    except (TypeError, IndexError, KeyError, ValueError):
        return ()
    if quad is None or quad[2] <= 0 or quad[3] <= 0:
        return ()
    cx, cy = _mode_center(quad)
    if cx == 0 and cy == 0:
        return ()
    return tuple(
        (label, cx + dx, cy + dy) for label, dx, dy in _LORDS_MODE_CLICK_LADDER_SNAPSHOT
    )


def _MODE_CLICK_EXHAUSTED_REASON_SNAPSHOT(
    last_state: str | None = None,
    last_anchor: str | None = None,
    note: str = "",
) -> str:
    """冻结版 :func:`scene.lords_nav.mode_click_exhausted_reason`（★只写读数，不写结论★）。"""
    labels = "/".join(label for label, _dx, _dy in _LORDS_MODE_CLICK_LADDER_SNAPSHOT)
    if last_state:
        reading = f"最后一次读回 state={last_state} 锚={last_anchor!r}"
    else:
        reading = "一次有效读回都没有（每帧都是转场帧）"
    if note:
        reading += f"；{note}"
    return (
        f"模式页点不出去：{_LORDS_MODE_SOLO_SNAPSHOT} {labels} "
        f"{len(_LORDS_MODE_CLICK_LADDER_SNAPSHOT)} 个点都试过"
        f"（每点轮询 ≤{_LORDS_MODE_POLL_TIMEOUT_SEC_SNAPSHOT:g}s、"
        f"间隔 {_LORDS_MODE_POLL_INTERVAL_SEC_SNAPSHOT:g}s），"
        f"{reading} —— 不是编队页（不假成功）"
    )


def _PAGE_STATE_SNAPSHOT(items) -> str:
    # ★过渡态最先判★（= scene/lords_nav.page_state 的第 0 步）：加载/过场帧可以叠在任何页面上。
    if _LOADING_FRAME_SNAPSHOT(items):
        return _LORDS_STATE_LOADING_SNAPSHOT
    if _PAGE_RULE_HIT_SNAPSHOT(items, "战斗HUD"):
        return _LORDS_STATE_BATTLE_SNAPSHOT
    if _PAGE_RULE_HIT_SNAPSHOT(items, "结算页"):
        return _LORDS_STATE_SETTLE_SNAPSHOT
    if _MODE_EVIDENCE_SNAPSHOT(items).is_mode_page:
        return _LORDS_STATE_MODE_SNAPSHOT
    if _PAGE_RULE_HIT_SNAPSHOT(items, "编队页"):
        return _LORDS_STATE_TEAM_SNAPSHOT
    if _PAGE_RULE_HIT_SNAPSHOT(items, "详情页"):
        return _LORDS_STATE_DETAIL_SNAPSHOT
    if _LIST_PAGE_PRESENT_SNAPSHOT(items):
        return _LORDS_STATE_LIST_SNAPSHOT
    if _PAGE_RULE_HIT_SNAPSHOT(items, "主城"):
        return _LORDS_STATE_CITY_SNAPSHOT
    return _LORDS_STATE_UNKNOWN_SNAPSHOT


def _CHALLENGE_RELEASE_EVIDENCE_SNAPSHOT(items) -> str:
    """放闩证据（= ``scene/lords_nav.challenge_release_evidence``；逐字同形）。

    点过【挑战】后这一帧**正向认出**了 battle/settle（或别的正向页）⇒ 返回状态名；否则 ``""``。
    """
    state = _PAGE_STATE_SNAPSHOT(items)
    return state if state in _LORDS_CHALLENGE_RELEASE_STATES_SNAPSHOT else ""


# ---- 详情页逐档状态（= scene/lords_nav 第 7b 节；真机 484 第 3 轮验收）--------
# ★为什么必须冻结到这里★：装好的产品只带 ``agent/``（没有 ``scene/``）。旧假设
# 「未通关的 NEW 行永远最上 ⇒ difficulty=None 就取最上面那个战斗框」在真机被推翻：
# 地狱级已 COMPLETE!! 却仍在最上 ⇒ 第 4/5/6 场全在重打已通关的档。选档改由**状态徽标**决定，
# 安装态必须与真源同判据，否则设备上照样重打。
_DETAIL_STATUS_COMPLETE_SNAPSHOT = "complete"
_DETAIL_STATUS_NEW_SNAPSHOT = "new"
_DETAIL_MARK_COMPLETE_SNAPSHOT = "PLETE!!"
_DETAIL_MARK_NEW_SNAPSHOT = "NEW"
_DETAIL_MARK_MAX_DY_SNAPSHOT = 120
_DETAIL_BACK_TEXT_SNAPSHOT = "返回"
_DETAIL_BACK_ROI_SNAPSHOT = (0, 1180, 110, 100)
_DETAIL_PICK_READY_SNAPSHOT = "pick"
_DETAIL_PICK_ALL_COMPLETE_SNAPSHOT = "all_complete"
_DETAIL_PICK_NO_STATUS_SNAPSHOT = "no_status"
_DETAIL_PICK_NO_TIERS_SNAPSHOT = "no_tiers"
_DETAIL_TIER_NO_STATUS_REASON_SNAPSHOT = (
    "详情页读不到任何档状态（{n} 档里 0 档有 COMPLETE!!/NEW）—— 不盲点"
    "（绝不回到「取最上面那个战斗框」的旧行为）"
)
_DETAIL_TIER_ALL_DONE_REASON_SNAPSHOT = (
    "详情页全部 {n} 档都是 COMPLETE!!（本账号这一行可见档已清空）—— "
    "不点任何档，点【返回】回列表重读 `通关数 N/M`（D6 关轮）"
)
_DETAIL_TIER_UNREAD_REASON_SNAPSHOT = (
    "详情页有 {k} 档读不到状态（{names}）—— 不盲点（读不出的档不能当未通关）"
)
_DETAIL_TIER_SUFFIX_SNAPSHOT = "|".join(
    re.escape(name) for name in sorted(_DIFFICULTIES_SNAPSHOT, key=len, reverse=True)
)
_DETAIL_TIER_NAME_RE_SNAPSHOT = re.compile(
    rf"^(?P<prefix>.*?)(?P<difficulty>{_DETAIL_TIER_SUFFIX_SNAPSHOT})$", re.DOTALL
)


def _quad_snapshot(box):
    """框 → 四整数元组；解不开 / 零尺寸返回 ``None``（= ``scene/lords_nav._quad``）。"""
    values = _box_xywh(box)
    if values is None:
        return None
    try:
        x, y, w, h = (float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (int(x), int(y), int(w), int(h))


def _detail_status_text_snapshot(status) -> str:
    if status == _DETAIL_STATUS_COMPLETE_SNAPSHOT:
        return "COMPLETE!!"
    if status == _DETAIL_STATUS_NEW_SNAPSHOT:
        return "NEW"
    return "未读数"


def _detail_tier_name_snapshot(text):
    match = _DETAIL_TIER_NAME_RE_SNAPSHOT.match(str(text or "").strip())
    if match is None:
        return None
    return (match.group("prefix"), match.group("difficulty"))


def _detail_mark_status_snapshot(text):
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if _DETAIL_MARK_COMPLETE_SNAPSHOT in stripped:
        return _DETAIL_STATUS_COMPLETE_SNAPSHOT
    if stripped.upper().startswith(_DETAIL_MARK_NEW_SNAPSHOT):
        return _DETAIL_STATUS_NEW_SNAPSHOT
    return None


@dataclass(frozen=True)
class _DetailTierSnapshot:
    difficulty: str
    label: str
    name_box: tuple
    status: object = None
    mark_box: object = None


@dataclass(frozen=True)
class _DetailTierChoiceSnapshot:
    status: str
    difficulty: object = None
    label: object = None
    name_box: object = None
    mark_box: object = None
    tiers: tuple = ()
    reason: str = ""

    @property
    def picked(self) -> bool:
        return self.status == _DETAIL_PICK_READY_SNAPSHOT

    def summary(self) -> str:
        return " / ".join(
            f"{tier.difficulty}={_detail_status_text_snapshot(tier.status)}"
            for tier in self.tiers
        )


def _DETAIL_TIER_ROWS_SNAPSHOT(items) -> tuple:
    """冻结版 ``scene.lords_nav.detail_tier_rows``（配对几何逐字同形）。"""
    names: list = []
    marks: list = []
    for text, box in items or []:
        quad = _quad_snapshot(box)
        if quad is None:
            continue
        stripped = str(text or "").strip()
        if not stripped:
            continue
        parsed = _detail_tier_name_snapshot(stripped)
        if parsed is not None:
            names.append((parsed, stripped, quad))
            continue
        status = _detail_mark_status_snapshot(stripped)
        if status is not None:
            marks.append((status, quad))
    rows: list = []
    for (_prefix, difficulty), label, box in names:
        ncx, ncy = _center_snapshot2(box)
        best = None
        for status, mark_box in marks:
            mcx, mcy = _center_snapshot2(mark_box)
            if mcx >= ncx:
                continue
            dy = ncy - mcy
            if dy <= 0 or dy > _DETAIL_MARK_MAX_DY_SNAPSHOT:
                continue
            if best is None or dy < best[0]:
                best = (dy, status, mark_box)
        rows.append(
            _DetailTierSnapshot(
                difficulty=difficulty,
                label=label,
                name_box=box,
                status=best[1] if best is not None else None,
                mark_box=best[2] if best is not None else None,
            )
        )
    rows.sort(key=lambda row: _center_snapshot2(row.name_box)[1])
    return tuple(rows)


def _PICK_UNCLEARED_TIER_SNAPSHOT(items, difficulty=None):
    """冻结版 ``scene.lords_nav.pick_uncleared_tier``（分支/文案逐字同形）。"""
    tiers = _DETAIL_TIER_ROWS_SNAPSHOT(items)
    if not tiers:
        return _DetailTierChoiceSnapshot(
            _DETAIL_PICK_NO_TIERS_SNAPSHOT,
            reason="详情页一档行名都没读出来（不是详情页 / 行名被 OCR 读丢）—— 不盲点",
        )
    read_tiers = [tier for tier in tiers if tier.status is not None]
    if not read_tiers:
        return _DetailTierChoiceSnapshot(
            _DETAIL_PICK_NO_STATUS_SNAPSHOT,
            tiers=tiers,
            reason=_DETAIL_TIER_NO_STATUS_REASON_SNAPSHOT.format(n=len(tiers)),
        )
    unread = [tier for tier in tiers if tier.status is None]
    declared = None
    if difficulty:
        declared = next((tier for tier in tiers if tier.difficulty == difficulty), None)
    if declared is not None and declared.status == _DETAIL_STATUS_NEW_SNAPSHOT:
        return _DetailTierChoiceSnapshot(
            _DETAIL_PICK_READY_SNAPSHOT,
            difficulty=declared.difficulty,
            label=declared.label,
            name_box=declared.name_box,
            mark_box=declared.mark_box,
            tiers=tiers,
            reason=f"目标档「{declared.difficulty}」状态 NEW（未通关）",
        )
    fresh = [tier for tier in tiers if tier.status == _DETAIL_STATUS_NEW_SNAPSHOT]
    if fresh:
        chosen = fresh[0]
        why = f"从上往下第一个 NEW = 第 {tiers.index(chosen) + 1} 档「{chosen.difficulty}」"
        if declared is not None and declared.status == _DETAIL_STATUS_COMPLETE_SNAPSHOT:
            why += f"（目标档「{declared.difficulty}」已 COMPLETE!! —— 不点它）"
        return _DetailTierChoiceSnapshot(
            _DETAIL_PICK_READY_SNAPSHOT,
            difficulty=chosen.difficulty,
            label=chosen.label,
            name_box=chosen.name_box,
            mark_box=chosen.mark_box,
            tiers=tiers,
            reason=why,
        )
    if not unread:
        return _DetailTierChoiceSnapshot(
            _DETAIL_PICK_ALL_COMPLETE_SNAPSHOT,
            tiers=tiers,
            reason=_DETAIL_TIER_ALL_DONE_REASON_SNAPSHOT.format(n=len(tiers)),
        )
    names = "、".join(tier.difficulty for tier in unread)
    return _DetailTierChoiceSnapshot(
        _DETAIL_PICK_NO_STATUS_SNAPSHOT,
        tiers=tiers,
        reason=_DETAIL_TIER_UNREAD_REASON_SNAPSHOT.format(k=len(unread), names=names),
    )


def _DETAIL_BACK_BOX_SNAPSHOT(items):
    """冻结版 ``scene.lords_nav.detail_back_box``：详情页左下角【返回】的框。"""
    if _PAGE_STATE_SNAPSHOT(items) != _LORDS_STATE_DETAIL_SNAPSHOT:
        return None
    x, y, w, h = _DETAIL_BACK_ROI_SNAPSHOT
    for item_text, box in items or []:
        if str(item_text or "").strip() != _DETAIL_BACK_TEXT_SNAPSHOT:
            continue
        quad = _quad_snapshot(box)
        if quad is None:
            continue
        cx, cy = _center_snapshot2(quad)
        if x <= cx <= x + w and y <= cy <= y + h:
            return quad
    return None


def _NON_LIST_STUCK_REASON_SNAPSHOT_FN(state: str, seconds: float) -> str:
    return _NON_LIST_STUCK_REASON_SNAPSHOT.format(state=state, seconds=float(seconds))

#: 页签判据（= ``scene/page_rules.py`` 的 ``领主战页签`` / ``降临讨伐页签``，逐字冻结）。
_TAB_ANCHOR_SNAPSHOT: dict = {
    "领主战": {
        "expected": ("^领主战$",),
        "roi": (0, 375, 360, 60),
        "click_hint": (180, 405),
    },
    "降临讨伐": {
        "expected": ("降临讨伐",),
        "roi": (360, 375, 360, 60),
        "click_hint": (540, 404),
    },
}

#: ``TabDecision.action`` 的取值（= ``scene/lords_nav.ACTION_*``）。
_ACTION_OK_SNAPSHOT = "ok"
_ACTION_CLICK_SNAPSHOT = "click"
_ACTION_GIVE_UP_SNAPSHOT = "give_up"
_ACTION_STOP_SNAPSHOT = "stop"
_ACTION_CANNOT_SNAPSHOT = "cannot"

#: ★目标行归位（pick 前先对页签、再上下找）★ 的冻结常量
#: （= ``scene/lords_nav.PICK_*``；``hooks_121`` 的 ``lords-pick-nav-snapshot-parity`` 逐项钉住）。
_PICK_ACTION_READY_SNAPSHOT = "ready"
_PICK_ACTION_TAB_SNAPSHOT = "tab"
_PICK_ACTION_SCROLL_SNAPSHOT = "scroll"
_PICK_ACTION_WAIT_SNAPSHOT = "wait"
_PICK_ACTION_FAIL_SNAPSHOT = "fail"
_PICK_SCROLL_DOWN_SNAPSHOT = "down"
_PICK_SCROLL_UP_SNAPSHOT = "up"
_PICK_PHASE_DOWN_SNAPSHOT = "down"
_PICK_PHASE_UP_SNAPSHOT = "up"
_PICK_PHASE_DONE_SNAPSHOT = "done"
_PICK_FAIL_TAB_SNAPSHOT = "tab_unreachable"
_PICK_FAIL_NOT_FOUND_SNAPSHOT = "not_found"
_PICK_FAIL_CLICK_SNAPSHOT = "click_stuck"
_PICK_FAIL_SCROLL_SNAPSHOT = "scroll_error"
#: 三种失败原因的**用户可见文案**（★三种必须能一眼分开★，见 scene/lords_nav 的同名常量）。
_PICK_REASON_TAB_SNAPSHOT = "目标不在这个页签"
_PICK_REASON_NOT_FOUND_SNAPSHOT = "滚到底也没找到"
_PICK_REASON_CLICK_SNAPSHOT = "找到了但点不动"
_PICK_REASON_SCROLL_SNAPSHOT = "滚动手势执行失败"
#: 页签「还没确认」最多等多久（秒）= 宽限期 × 未确认上限（不新造数字）。
_PICK_TAB_WAIT_SEC_SNAPSHOT = (
    _TAB_CONFIRM_GRACE_SEC_SNAPSHOT * _TAB_UNCONFIRMED_LIMIT_SNAPSHOT
)


@dataclass(frozen=True)
class _TabAnchorSnapshot:
    """``scene.lords_nav.TabAnchor`` 的冻结版。"""

    tab: str
    expected: tuple
    roi: tuple
    click_hint: tuple
    source: str = "冻结快照"

    def hits(self, text: str) -> bool:
        """这段文本是不是这个页签的标签。"""
        return any(re.search(p, text or "") for p in self.expected)


@dataclass(frozen=True)
class _TabEvidenceSnapshot:
    """``scene.lords_nav.TabEvidence`` 的冻结版（字段逐一照抄）。"""

    list_page: bool
    labels: frozenset
    confirmed: object
    kinds: tuple
    unknown_rows: tuple


@dataclass(frozen=True)
class _TabDecisionSnapshot:
    """``scene.lords_nav.TabDecision`` 的冻结版。"""

    action: str
    target: object
    box: object
    reason: str


@dataclass(frozen=True)
class _ScrollPlanSnapshot:
    """``scene.lords_nav.ScrollPlan`` 的冻结版（数值逐一照抄）。"""

    travel_px: int = _SCROLL_TRAVEL_PX_SNAPSHOT
    begin: tuple = _SCROLL_BEGIN_SNAPSHOT
    end: tuple = _SCROLL_END_SNAPSHOT
    duration_ms: int = _SCROLL_DURATION_MS_SNAPSHOT
    settle_ms: int = _SCROLL_SETTLE_MS_SNAPSHOT
    min_interval_sec: float = _SCROLL_MIN_INTERVAL_SEC_SNAPSHOT
    max_scrolls_per_page: int = _SCROLL_MAX_PER_PAGE_SNAPSHOT
    stable_times: int = _SCROLL_STABLE_TIMES_SNAPSHOT
    no_move_px: int = _SCROLL_NO_MOVE_PX_SNAPSHOT
    #: ★每页开扫前「回顶部」的预算★（= 真源 ``max_rewinds_per_page``；用尽**带原因收工**）。
    max_rewinds_per_page: int = _SCROLL_MAX_REWINDS_PER_PAGE_SNAPSHOT
    list_body: tuple = _LIST_BODY_SNAPSHOT
    source: str = "冻结快照"

    @property
    def max_scrolls_total(self) -> int:
        """两个页签各一份预算 → 整趟扫描的滚动次数上限。"""
        return self.max_scrolls_per_page * len(_LORD_TABS_SNAPSHOT)

    def in_list_body(self, point) -> bool:
        """这个点是否落在列表体内（#36：手势两端都必须在列表体里）。"""
        return self.list_body[0] <= point[1] <= self.list_body[1]

    @property
    def geometry_ok(self) -> bool:
        """手势两端都在列表体内。"""
        return self.in_list_body(self.begin) and self.in_list_body(self.end)

    @property
    def up_begin(self) -> tuple:
        """★向上滚（回顶部）的起点★ = :attr:`end`（反向同一个手势，见真源同名属性）。"""
        return self.end

    @property
    def up_end(self) -> tuple:
        """★向上滚的终点★ = :attr:`begin`。"""
        return self.begin


_SCROLL_PLAN_SNAPSHOT = _ScrollPlanSnapshot()


def _box4_snapshot(box):
    """框归一成四元组**整数**（= ``scene/lords_nav._box4`` 的逐字副本；Rect / list 都认）。"""
    return _box4_int(box)


def _center_snapshot2(box):
    """框中心（浮点；Rect / list 都认，见 :func:`_box_xywh`）。"""
    return _box_center(box)


def _row_cy_snapshot(row):
    """行读数的纵向中心；拿不到框返回 ``None``。"""
    box = getattr(row, "name_box", None)
    if box is None and isinstance(row, Mapping):
        box = row.get("name_box")
    center = _center_snapshot2(box)          # ★框架给的 Rect 没有 len，这里一律走解包★
    if center is None:
        return None
    return center[1]


def _CLASSIFY_KIND_SNAPSHOT(name, registry=None) -> object:
    """冻结版 ``classify_kind``：行名 → ``lord`` / ``joss``；认不出 ``None``（不猜）。"""
    text = str(name or "").strip()
    if not text:
        return None
    for entry in (_SNAPSHOT_REGISTRY if registry is None else registry):
        if re.search(entry.row_regex, text):
            return getattr(entry, "kind", None) or None
    return None


def _TAB_OF_KIND_SNAPSHOT(kind) -> object:
    """冻结版 ``tab_of_kind``：``kind`` → 页签名。"""
    if not kind:
        return None
    return _SUBFAMILY_BY_KIND_SNAPSHOT.get(kind)


def _TAB_OF_ROW_SNAPSHOT(row_name, registry=None) -> object:
    """冻结版 ``tab_of_row``：行名 → 页签名（#19：页签由目标决定）。"""
    return _TAB_OF_KIND_SNAPSHOT(_CLASSIFY_KIND_SNAPSHOT(row_name, registry))


def _LABEL_BOX_SNAPSHOT(items, anchor):
    """冻结版 ``label_box``：页签标签的 OCR 框（正则命中 + 框中心落在 ROI 内）。"""
    x, y, w, h = anchor.roi
    for text, box in items or []:
        if not anchor.hits(str(text or "")):
            continue
        center = _center_snapshot2(box)      # ★Rect / list 都认★（不许 len(box)）
        if center is None:
            continue
        cx, cy = center
        if x <= cx <= x + w and y <= cy <= y + h:
            return _box4_snapshot(box)
    return None


def _TAB_LABELS_SNAPSHOT(items) -> frozenset:
    """冻结版 ``tab_labels``：这一帧读到了哪些页签标签（★不表示谁被选中★）。"""
    found = set()
    for tab, spec in _TAB_ANCHOR_SNAPSHOT.items():
        if _LABEL_BOX_SNAPSHOT(items, _TabAnchorSnapshot(tab, **spec)) is not None:
            found.add(tab)
    return frozenset(found)


def _LIST_PAGE_PRESENT_SNAPSHOT(items) -> bool:
    """冻结版 ``list_page_present``：这一帧是不是领主战列表页。"""
    return any(_LIST_PAGE_ANCHOR_SNAPSHOT in str(text or "") for text, _box in items or [])


def _TAB_STATE_SNAPSHOT(items, registry=None):
    """冻结版 ``tab_state``：一帧 OCR 项 → 页签证据（★只认行族身份证据★）。"""
    texts = []
    for text, _box in items or []:
        stripped = str(text or "").strip()
        if not stripped:
            continue
        if any(
            _TabAnchorSnapshot(tab, **spec).hits(stripped) for tab, spec in _TAB_ANCHOR_SNAPSHOT.items()
        ):
            continue
        if _LIST_PAGE_ANCHOR_SNAPSHOT in stripped:
            continue
        if stripped in _NOT_A_ROW_NAME_SNAPSHOT:
            continue
        if _PARSE_PROGRESS_SNAPSHOT(stripped) is not None:
            continue
        texts.append(stripped)

    kinds = []
    unknown = []
    for text in texts:
        kind = _CLASSIFY_KIND_SNAPSHOT(text, registry)
        if kind is None:
            unknown.append(text)
            continue
        if kind not in kinds:
            kinds.append(kind)

    listed = _LIST_PAGE_PRESENT_SNAPSHOT(items)
    confirmed = _TAB_OF_KIND_SNAPSHOT(kinds[0]) if (listed and len(kinds) == 1) else None
    return _TabEvidenceSnapshot(
        list_page=listed,
        labels=_TAB_LABELS_SNAPSHOT(items),
        confirmed=confirmed,
        kinds=tuple(kinds),
        unknown_rows=tuple(unknown),
    )


def _END_ANCHOR_HIT_SNAPSHOT(items):
    """冻结版 ``end_anchor_hit``：这一帧里的列表尾锚点原文（当前数据为空）。"""
    for text, _box in items or []:
        stripped = str(text or "").strip()
        for anchor in _END_ANCHORS_SNAPSHOT:
            if anchor and anchor in stripped:
                return anchor
    return None


def _ROW_TRIPLE_SNAPSHOT(row) -> tuple:
    """冻结版 ``scene.lords_nav._row_triple``：一行读数归一成 ``(行名, N, M)``。"""
    if isinstance(row, _RowReadingSnapshot):
        name, n, m = row.name, row.n, row.m
    elif isinstance(row, Mapping):
        name, n, m = str(row.get("name", "")), int(row["n"]), int(row["m"])
    elif hasattr(row, "n") and hasattr(row, "m") and hasattr(row, "name"):
        name, n, m = str(row.name), int(row.n), int(row.m)
    else:
        name, n, m = str(row[0]), int(row[1]), int(row[2])
    return (str(name).strip(), int(n), int(m))


def _ROW_KEY_SNAPSHOT(row) -> tuple:
    """冻结版 ``row_key``：**本帧去重键** = ``(行名, "N/M")``（★不是累计表的键★）。"""
    name, n, m = _ROW_TRIPLE_SNAPSHOT(row)
    return (name, f"{n}/{m}")


def _ON_SCREEN_SNAPSHOT(box) -> bool:
    """冻结版 ``scene.lords_nav.on_screen``：整框落在 720x1280 内才算「在屏上」。

    ★越界 = 不在屏上★（``0 <= x`` ∧ ``x+w <= SCREEN_W`` ∧ ``0 <= y`` ∧ ``y+h <= SCREEN_H``）。
    解不开（``None`` / 非四元 / 不可转数）一律 ``False``。真源行为由 hooks_122 的
    ``lords-mode-snapshot-parity`` 逐项对账（同一批框两边必须同结论）。
    """
    try:
        x, y, w, h = (float(value) for value in box)
    except (TypeError, ValueError):
        return False
    return (
        0 <= x
        and 0 <= y
        and x + w <= _SCREEN_W_SNAPSHOT
        and y + h <= _SCREEN_H_SNAPSHOT
    )


def _ROW_ROI_HIT_SNAPSHOT(box) -> bool:
    """冻结版 ``scene.lords_nav.row_roi_hit``：**框中心**落在列表行 ROI 内才算「列表行」。

    ★与真源同一条判据★：标题 / 横幅 / 页签 / 底栏里的同名文字一律 ``False``（越界忽略）。
    解不开的框（``None`` / 非四元）一律 ``False``。``hooks_122`` 的
    ``lords-mode-snapshot-parity`` 用同一批框对账真源与快照（逐项相同），
    ``lords-row-roi-title-not-row`` 用真机模式页帧钉住「标题不是行」。
    """
    try:
        quad = _box4_snapshot(box)
    except (TypeError, IndexError, KeyError, ValueError):
        return False
    if quad is None:
        return False
    cx, cy = _mode_center(quad)
    x, y, w, h = _ROW_ROI_SNAPSHOT
    return x <= cx <= x + w and y <= cy <= y + h


#: 冻结版 :data:`scene.lords_nav.LIST_BADGE_MARKS`（**徽标不是行名**；真机 484 第 5 轮验收）。
#: 元素与真源逐字相同（``COMPLETE!!`` / 弱读 ``PLETE!!`` / ``NEW`` / ``首次报酬`` / ``SS``），
#: 值由 ``hooks_122`` 的 ``lords-mode-snapshot-parity`` 逐项对账。
_LIST_BADGE_MARKS_SNAPSHOT: tuple = ("COMPLETE!!", "PLETE!!", "NEW", "首次报酬", "SS")


def _IS_BADGE_TEXT_SNAPSHOT(text) -> bool:
    """冻结版 ``scene.lords_nav.is_badge_text``：**行名不能是徽标**。

    ★真机 484 第 5 轮验收（``debug/lords_accept5.log``，18:12–18:18）★：关轮后重读的列表里
    ``rows: COMPLETE!! 4/4、COMPLETE!! 4/4、八岐大蛇讨伐 4/4、妖狐讨伐 1/4`` —— 4 行里 2 行的
    行名被读成了 ``COMPLETE!!``（徽标与行名在同一行带，几何分组把更贴近进度的徽标挂成了行名）。
    假行名会污染 ``plan_round`` 的目标集合与 ``round_gained`` 的「新解锁」。

    判据与真源逐字相同：大写折叠后**按包含判**（徽标会读成半串 ``PLETE!!`` 或连串
    ``COMPLETE!! SS``）。``hooks_122`` 的 ``lords-mode-snapshot-parity`` 用同一批文本对账。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return False
    folded = stripped.upper()
    return any(str(mark).upper() in folded for mark in _LIST_BADGE_MARKS_SNAPSHOT)


#: 行名修复的几何窗口（= 真源 :data:`scene.lords_nav.BADGE_RECOVERY_MAX_DY` /
#: ``BADGE_RECOVERY_MIN_LEFT_GAP``；数值引用 ``scene.lords_unlock`` 的同一对阈值，不另发明）。
_BADGE_RECOVERY_MAX_DY_SNAPSHOT: int = _MAX_NAME_DY_SNAPSHOT
_BADGE_RECOVERY_MIN_LEFT_GAP_SNAPSHOT: int = _MIN_NAME_LEFT_GAP_SNAPSHOT


def _RECOVER_BADGE_ROW_NAME_SNAPSHOT(
    items,
    progress_box,
    *,
    max_dy: int = _BADGE_RECOVERY_MAX_DY_SNAPSHOT,
    min_left_gap: int = _BADGE_RECOVERY_MIN_LEFT_GAP_SNAPSHOT,
):
    """冻结版 ``scene.lords_nav.recover_badge_row_name``：行名被读成徽标 ⇒ 用几何找回来。

    ★真机 484 accept7（``debug/lords_accept7.log``，领主战累计 41–46 行被剔）★：徽标属于
    **下一张卡**，却比本卡真名更贴近本卡的「通关数」（44–45px vs 47–48px）⇒ 几何分组把它挂成了
    行名。真名**在帧里、也读出来了**（``accept6_lords_list_bottom_MM.png``：COMPLETE!!
    [13,735,127,27] / 不死王瑞西塔尔讨伐 [203,787,245,28] / 通关数4/4 [547,833,126,28]）——
    所以这里把徽标从候选里剔掉后按同一条几何判据重新配对。

    ★不按花名册筛★：``五王连战 1/1`` 这类**不在花名册**的活动行同样会被徽标抢走进度
    （``accept6_jianglin_hongji_cangtan_1of4.png``）；只认花名册会让它永远找不回来、
    ``dropped_in_scan`` 把 ``all_done`` 永远压成 False。名字认不认得交给 ``plan_round``。

    返回 ``(行名, 行名框)``；找不到返回 ``None``（调用方必须退回「整行不读」，绝不猜名字）。
    行名只可能是列表体里的文本：``ROW_ROI`` 过滤 + 徽标/进度/页签/固定元素排除。
    """
    try:
        px, py, pw, ph = _box4_snapshot(progress_box)
    except (TypeError, IndexError, KeyError, ValueError):
        return None
    if pw <= 0 or ph <= 0:
        return None
    progress_cx = px + pw / 2.0
    progress_cy = py + ph / 2.0
    best = None
    for text, box in items or ():
        stripped = str(text or "").strip()
        if not stripped or _IS_BADGE_TEXT_SNAPSHOT(stripped):
            continue                                  # ★徽标永远不是行名★
        if stripped in _NOT_A_ROW_NAME_SNAPSHOT or stripped in _LORD_TABS_SNAPSHOT:
            continue                                  # 固定元素 / 页签副标题
        if _PARSE_PROGRESS_SNAPSHOT(stripped) is not None:
            continue                                  # 进度自己不是行名
        if re.fullmatch(r"[\d\s/|\\⁄╱.,:：]+", stripped):
            continue                                  # 纯数字/纯符号不是行名
        try:
            quad = _box4_snapshot(box)
        except (TypeError, IndexError, KeyError, ValueError):
            continue
        if quad[2] <= 0 or quad[3] <= 0:
            continue
        if not _ROW_ROI_HIT_SNAPSHOT(quad):
            continue                                  # 行名只在列表体里
        name_center = _center_snapshot2(quad)
        if name_center is None:
            continue
        name_cx, name_cy = name_center
        if name_cx >= progress_cx:
            continue                                  # 行名必须在进度左侧
        if progress_cx - (quad[0] + quad[2]) < min_left_gap:
            continue
        dy = abs(progress_cy - name_cy)
        if dy > max_dy:
            continue
        key = (dy, -name_cx)
        if best is None or key < best[0]:
            best = (key, stripped, quad)
    if best is None:
        return None
    return (best[1], best[2])


@dataclass
class _NavStateSnapshot:
    """``scene.lords_nav.NavState`` 的冻结版（字段/分支/文案逐一照抄）。"""

    sweep_index: int = 0
    sweep_done: bool = False
    sweep_round: int = -1
    switch_attempts: int = 0
    switch_for: object = None
    unconfirmed: int = 0
    scrolls_in_page: int = 0
    stable_scrolls: int = 0
    #: ★滚动世代★（= 真源 ``scene/lords_nav.NavState.scroll_gen``）：note_scroll 每滚一次 +1；
    #: 到底判据按世代记账（同一世代只记一次、没真的滚过不记账）。
    scroll_gen: int = 0
    stable_gen: int = -1
    last_scroll_at: float = 0.0
    last_rows: tuple = ()
    #: ★累计读数：``{行名: 最新读数}``★（不是 ``{row_key: 读数}``，见 add_rows）。
    seen: dict = field(default_factory=dict)
    last_progress_at: float = 0.0
    # -- ★每页开扫前「回顶部」（= 真源同名字段，逐项照抄）★ ------------------
    rewind_done: bool = False
    rewind_scrolls: int = 0
    rewind_gen: int = 0
    rewind_stable_gen: int = -1
    rewind_stable: int = 0
    rewind_last_rows: tuple = ()
    rewind_failed: bool = False
    # -- ★本轮扫描的完整性账（只在 begin_round 复位）★ ----------------------
    dropped_in_scan: int = 0
    top_unconfirmed: int = 0
    tab_switch_failed: bool = False
    # -- 页内「滚不动」的位移记账（有被剔行时判「底不可证」）-----------------
    no_move_stable_gen: int = -1
    no_move_stable: int = 0
    bottom_unprovable: bool = False

    # -- 页签 ---------------------------------------------------------------
    def desired_tab(self, target_row=None, registry=None):
        """**目标页签**：有目标行 → 它的族；否则 → 扫描顺序里的下一个。"""
        if target_row:
            tab = _TAB_OF_ROW_SNAPSHOT(target_row, registry)
            if tab is not None:
                return tab
        if self.sweep_done:
            return None
        if 0 <= self.sweep_index < len(_LORD_TABS_SNAPSHOT):
            return _LORD_TABS_SNAPSHOT[self.sweep_index]
        return None

    def page_pending(self, round_index) -> bool:
        """现在该不该做页扫描。"""
        return (not self.sweep_done) or int(round_index) > int(self.sweep_round)

    def switch_decision(self, evidence, desired, box, now):
        """该不该切页签（含切后确认；失败只许 1 次）。"""
        if desired is None:
            return _TabDecisionSnapshot(_ACTION_CANNOT_SNAPSHOT, None, None,
                                        "没有目标页签（扫描已结束且当前无目标行）")
        if not evidence.list_page:
            return _TabDecisionSnapshot(
                _ACTION_CANNOT_SNAPSHOT,
                desired,
                None,
                f"不在领主战列表页（读不到「{_LIST_PAGE_ANCHOR_SNAPSHOT}」）—— 不在这里点页签",
            )
        if evidence.confirmed == desired:
            self.switch_attempts = 0
            self.switch_for = None
            self.unconfirmed = 0
            self.note_progress(now)
            return _TabDecisionSnapshot(
                _ACTION_OK_SNAPSHOT,
                desired,
                None,
                f"已确认停在「{desired}」页签（可见行族 = {evidence.kinds}）—— 无需切换",
            )
        if self.switch_for != desired:
            self.switch_for = desired
            self.switch_attempts = 0
        if self.switch_attempts >= _TAB_SWITCH_MAX_ATTEMPTS_SNAPSHOT:
            # ★宽限期★：点完页签先给它 grace，慢帧不算失败
            if self.last_progress_at > 0 and (now - self.last_progress_at) >= _TAB_CONFIRM_GRACE_SEC_SNAPSHOT:
                self.unconfirmed += 1
            why = (
                f"页签未确认到「{desired}」（已点 {self.switch_attempts}/{_TAB_SWITCH_MAX_ATTEMPTS_SNAPSHOT} 次，"
                f"可见行族 = {evidence.kinds}，确认值 = {evidence.confirmed!r}）"
            )
            if self.unconfirmed >= _TAB_UNCONFIRMED_LIMIT_SNAPSHOT:
                return _TabDecisionSnapshot(
                    _ACTION_STOP_SNAPSHOT,
                    desired,
                    None,
                    why
                    + f"；连续 {self.unconfirmed} 次（上限 {_TAB_UNCONFIRMED_LIMIT_SNAPSHOT}）—— 带原因收工"
                    f"（重试只会变成 #19 那种页签竞速死循环）",
                )
            return _TabDecisionSnapshot(_ACTION_GIVE_UP_SNAPSHOT, desired, None,
                                        why + " —— 不重试（#19），回枢纽")
        if box is None:
            return _TabDecisionSnapshot(
                _ACTION_CANNOT_SNAPSHOT,
                desired,
                None,
                f"读不到「{desired}」页签的标签框（ROI {_TAB_ANCHOR_SNAPSHOT[desired]['roi']}）—— 不盲点",
            )
        self.switch_attempts += 1
        self.note_progress(now)
        return _TabDecisionSnapshot(
            _ACTION_CLICK_SNAPSHOT,
            desired,
            _box4_snapshot(box),
            f"点「{desired}」页签（第 {self.switch_attempts}/{_TAB_SWITCH_MAX_ATTEMPTS_SNAPSHOT} 次，"
            f"点框中心；切完必须复核确认 = 可见行族一致指向目标页签）",
        )

    # -- ★每页开扫前「回顶部」（= 真源同名方法，逐字照抄）★ -----------------
    def rewind_pending(self) -> bool:
        """这一页是否还需要先回顶部。"""
        return (not self.rewind_done) and (not self.rewind_failed)

    def rewind_budget_exhausted(self) -> bool:
        """回顶部次数是否用尽（用尽 → 调用方带原因收工）。"""
        return self.rewind_scrolls >= _SCROLL_PLAN_SNAPSHOT.max_rewinds_per_page

    def note_rewind_scroll(self, now) -> None:
        """记一次回顶部上滚（独立账：不动向下扫的 scrolls_in_page / scroll_gen）。"""
        self.rewind_scrolls += 1
        self.rewind_gen += 1
        self.last_scroll_at = now
        self.note_progress(now)
        if self.rewind_budget_exhausted():
            self.rewind_failed = True

    def observe_rewind(self, rows, dropped=0) -> tuple:
        """回顶部判据：连续 stable_times 个回顶部世代「无新行 ∧ 无位移」⇒ 到顶。"""
        rows = tuple(rows or ())
        if dropped:
            self.dropped_in_scan += int(dropped)
        prev = {}
        for row in self.rewind_last_rows:
            cy = _row_cy_snapshot(row)
            if cy is not None:
                prev[_ROW_KEY_SNAPSHOT(row)] = cy
        moved = None
        fresh = []
        for row in rows:
            key = _ROW_KEY_SNAPSHOT(row)
            if key not in prev:
                fresh.append(key)
                continue
            cy = _row_cy_snapshot(row)
            if cy is None:
                continue
            moved = abs(cy - prev[key]) if moved is None else max(moved, abs(cy - prev[key]))
        self.rewind_last_rows = rows
        if not rows:
            self.rewind_stable = 0
            self.rewind_stable_gen = self.rewind_gen
            return (
                False,
                "未到顶：这一帧一行 `通关数 N/M` 都没读到（空帧 / 全被徽标剔除）—— "
                "判不了「再往上滚也不动」，不记账",
            )
        shown = "无法量出（跨帧没有共有行框）" if moved is None else f"{moved:.0f}px"
        if fresh:
            self.rewind_stable = 0
            self.rewind_stable_gen = self.rewind_gen
            return (
                False,
                f"未到顶：上滚后出现 {len(fresh)} 个新行（上面还有没读到的行）—— 继续向上滚",
            )
        no_move = moved is None or moved <= _SCROLL_PLAN_SNAPSHOT.no_move_px
        if no_move and self.rewind_gen > 0 and self.rewind_stable_gen != self.rewind_gen:
            self.rewind_stable_gen = self.rewind_gen
            self.rewind_stable += 1
        if self.rewind_stable >= _SCROLL_PLAN_SNAPSHOT.stable_times:
            self.rewind_done = True
            return (
                True,
                f"已到顶部：向上滚 {self.rewind_scrolls} 次（上限 "
                f"{_SCROLL_PLAN_SNAPSHOT.max_rewinds_per_page}），连续 {self.rewind_stable} 个世代"
                f"没有新行 / 纵向位移 {shown} ≤ {_SCROLL_PLAN_SNAPSHOT.no_move_px}px —— 可以开始向下扫",
            )
        return (
            False,
            f"未到顶：连续 {self.rewind_stable}/{_SCROLL_PLAN_SNAPSHOT.stable_times} 个世代无新行 / "
            f"纵向位移 {shown}（第 {self.rewind_gen} 次上滚那一代；上滚 {self.rewind_scrolls}/"
            f"{_SCROLL_PLAN_SNAPSHOT.max_rewinds_per_page} 次）",
        )

    def may_rewind(self, now) -> tuple:
        """能不能再上滚一次（回顶部的**时间闩 + 预算**）。"""
        if self.rewind_budget_exhausted():
            return (
                False,
                f"回顶部预算用尽（已上滚 {self.rewind_scrolls} 次，上限 "
                f"{_SCROLL_PLAN_SNAPSHOT.max_rewinds_per_page}）—— 必须带原因收工，绝不无限上滚",
            )
        waited = now - self.last_scroll_at
        if self.last_scroll_at > 0 and waited < _SCROLL_PLAN_SNAPSHOT.min_interval_sec:
            return (
                False,
                f"回顶部时间闩未到（距上次滚动 {waited:.2f}s < "
                f"{_SCROLL_PLAN_SNAPSHOT.min_interval_sec}s）—— 等下一圈",
            )
        return (
            True,
            f"回顶部：向上滚第 {self.rewind_scrolls + 1}/"
            f"{_SCROLL_PLAN_SNAPSHOT.max_rewinds_per_page} 次（行程 "
            f"{_SCROLL_PLAN_SNAPSHOT.travel_px}px，同一个手势反向）",
        )

    # -- 页内滚动 / 到底 ----------------------------------------------------
    def add_rows(self, rows, now=None) -> tuple:
        """冻结版 ``NavState.add_rows``：累计表按**行名**留**最新**读数（N 变大即覆盖）。

        ``row_key`` 只用于「本帧这一行读没读过」；比累计更旧的读数算重复、不覆盖。
        """
        new = []
        dup = []
        frame_keys = set()
        for row in rows or ():
            key = _ROW_KEY_SNAPSHOT(row)
            if key in frame_keys:
                dup.append(key)
                continue
            frame_keys.add(key)
            name, n, _m = _ROW_TRIPLE_SNAPSHOT(row)
            previous = self.seen.get(name)
            if previous is not None:
                if n > _ROW_TRIPLE_SNAPSHOT(previous)[1]:
                    self.seen[name] = row
                    new.append(key)
                else:
                    dup.append(key)
                continue
            self.seen[name] = row
            new.append(key)
        if new and now is not None:
            self.note_progress(now)
        return (tuple(new), tuple(dup))

    def rows(self) -> tuple:
        """累计到的**最新**行读数（每行一条，按第一次出现的顺序）。"""
        return tuple(self.seen.values())

    def observe(self, rows, anchor_hit=None, dropped=0) -> tuple:
        """冻结版 ``NavState.observe``：到底判据按**滚动世代**记账（同一世代只记一次）。

        ``dropped`` = 这一帧被徽标整行剔掉的行数（= 真源同名参数）：有被剔行时**不许判到底**，
        只按「滚不动」判 ``bottom_unprovable``（底不可证）。
        """
        plan = _SCROLL_PLAN_SNAPSHOT
        rows = tuple(rows or ())
        if dropped:
            self.dropped_in_scan += int(dropped)
        prev = {}
        for row in self.last_rows:
            cy = _row_cy_snapshot(row)
            if cy is not None:
                prev[_ROW_KEY_SNAPSHOT(row)] = cy
        moved = None
        fresh = []
        for row in rows:
            key = _ROW_KEY_SNAPSHOT(row)
            if key not in prev:
                fresh.append(key)
                continue
            cy = _row_cy_snapshot(row)
            if cy is None:
                continue
            moved = abs(cy - prev[key]) if moved is None else max(moved, abs(cy - prev[key]))
        self.last_rows = rows

        if anchor_hit and not dropped:
            self.stable_scrolls = plan.stable_times
            self.stable_gen = self.scroll_gen
            return (True, f"到底：读到列表尾锚点「{anchor_hit}」")
        if not rows:
            self.stable_scrolls = 0
            self.stable_gen = self.scroll_gen
            self.no_move_stable = 0
            note = f"（这一帧有 {dropped} 行被徽标剔除）" if dropped else ""
            return (
                False,
                "未到底：这一帧一行 `通关数 N/M` 都没读到 —— 空帧不能当「列表没动」" + note,
            )
        no_move = moved is None or moved <= plan.no_move_px
        shown = "无法量出（跨帧没有共有行框）" if moved is None else f"{moved:.0f}px"
        if fresh or not no_move:
            self.no_move_stable = 0
        elif self.scroll_gen > 0 and self.no_move_stable_gen != self.scroll_gen:
            self.no_move_stable_gen = self.scroll_gen
            self.no_move_stable += 1
        note = ""
        # ★#100 真机★ 只要求「没有新行」：滚到底后有橡皮筋回弹，位移不作否决（仍打进 reason）。
        if dropped:
            self.stable_scrolls = 0
            self.stable_gen = self.scroll_gen
            if self.no_move_stable >= plan.stable_times:
                first_time = not self.bottom_unprovable
                self.bottom_unprovable = True
                return (
                    False,
                    f"未到底：这一帧有 {dropped} 行被徽标剔除（可能是 N<M 的行）—— 不许判到底；"
                    f"但连续 {self.no_move_stable} 个世代**滚不动**（纵向位移 {shown} ≤ "
                    f"{plan.no_move_px}px）⇒ 底不可证，本页按「扫描不完整」收尾"
                    + ("（首次记下）" if first_time else ""),
                )
            return (
                False,
                f"未到底：这一帧有 {dropped} 行被徽标剔除（可能是 N<M 的行）—— 不许判到底；"
                f"滚不动连续 {self.no_move_stable}/{plan.stable_times} 个世代"
                f"（纵向位移 {shown}），继续滚着看",
            )
        if not fresh:
            if self.scroll_gen > 0 and self.stable_gen != self.scroll_gen:
                self.stable_gen = self.scroll_gen
                self.stable_scrolls += 1
                note = f"（第 {self.scroll_gen} 次滚动那一代）"
            elif self.scroll_gen <= 0:
                note = "（本页还一次都没滚过 —— 「没动」不成立，不记账）"
            else:
                note = f"（第 {self.scroll_gen} 次滚动那一代已经记过 —— 同一屏重复读不重复记账）"
        else:
            self.stable_scrolls = 0
            self.stable_gen = self.scroll_gen
        if self.stable_scrolls >= plan.stable_times:
            return (
                True,
                f"到底：连续 {self.stable_scrolls} 次**滚动**后都没有新行"
                f"（末次纵向位移 {shown}；滚到底的橡皮筋回弹也算「没有新行」，故位移不作否决）",
            )
        return (
            False,
            f"未到底：新行 {len(fresh)} 个 / 纵向位移 {shown}（连续无变化 "
            f"{self.stable_scrolls}/{plan.stable_times} 次）{note}",
        )

    def at_end(self) -> bool:
        """当前的到底结论。"""
        return self.stable_scrolls >= _SCROLL_PLAN_SNAPSHOT.stable_times

    def page_finished(self) -> bool:
        """这一页能否先收尾（真到底 或 底不可证）。"""
        return self.at_end() or self.bottom_unprovable

    def scan_incomplete_reason(self) -> str:
        """本轮扫描的不完整证据（空串 = 完整）；零目标收工的**正确原因**靠它。"""
        parts = []
        if self.dropped_in_scan > 0:
            parts.append(f"有行被徽标剔除 {self.dropped_in_scan} 行")
        if self.top_unconfirmed > 0:
            parts.append(f"未确认回到顶部 {self.top_unconfirmed} 页")
        if self.tab_switch_failed:
            parts.append("页签未切换")
        return " / ".join(parts)

    def scan_complete(self) -> bool:
        """本轮扫描是否完整。"""
        return not (self.dropped_in_scan or self.top_unconfirmed or self.tab_switch_failed)

    def note_tab_switch_failed(self) -> None:
        """页签没切换成功（sticky 到 begin_round）。"""
        self.tab_switch_failed = True

    def may_scroll(self, now, *, confirmed, desired, target_visible, scanning, anchor_hit=None) -> tuple:
        """能不能滚一次（时间闩 + 到底判据 + 上限兜底）。"""
        plan = _SCROLL_PLAN_SNAPSHOT
        if anchor_hit:
            return (False, f"已到底（尾部锚点「{anchor_hit}」）—— 不再滚")
        if self.at_end():
            return (False, f"已到底（连续 {self.stable_scrolls} 次无新行/无位移）—— 不再滚")
        if self.scrolls_in_page >= plan.max_scrolls_per_page:
            return (
                False,
                f"本页已滚 {self.scrolls_in_page} 次（上限 {plan.max_scrolls_per_page}，"
                f"#50 同口径的**兜底**）仍未到底 —— 必须带原因收工，绝不静默跳过（半扫的列表"
                f"判不了「全部解禁」）",
            )
        if desired is not None and confirmed != desired:
            return (False, f"页签未确认到「{desired}」（当前确认值 {confirmed!r}）—— 先切页签再滚（#19）")
        waited = now - self.last_scroll_at
        if self.last_scroll_at > 0 and waited < plan.min_interval_sec:
            return (
                False,
                f"时间闩未到（距上次滚动 {waited:.2f}s < {plan.min_interval_sec}s）—— 等下一圈",
            )
        if not scanning and target_visible:
            return (False, "目标行已在屏上 —— 先选行、再滚（#29：滚动不许抢在选行前面）")
        return (True, f"可以滚一次（本页第 {self.scrolls_in_page + 1} 次，行程 {plan.travel_px}px）")

    def note_scroll(self, now) -> None:
        """记一次滚动（时间闩基准 + 页内计数 + **滚动世代 +1**）。"""
        self.scrolls_in_page += 1
        self.scroll_gen += 1
        self.last_scroll_at = now
        self.note_progress(now)

    def scroll_budget_exhausted(self) -> bool:
        """本页滚动次数是否已用尽（用尽 → 调用方**带原因收工**，绝不静默跳过）。"""
        return self.scrolls_in_page >= _SCROLL_PLAN_SNAPSHOT.max_scrolls_per_page

    # -- 扫描进度 -----------------------------------------------------------
    def reset_page(self) -> None:
        """冻结版 ``reset_page``：清页内状态 + 重新武装「回顶部」。"""
        self.scrolls_in_page = 0
        self.stable_scrolls = 0
        self.last_rows = ()
        self.rewind_done = False
        self.rewind_scrolls = 0
        self.rewind_gen = 0
        self.rewind_stable_gen = -1
        self.rewind_stable = 0
        self.rewind_last_rows = ()
        self.rewind_failed = False
        self.bottom_unprovable = False
        self.no_move_stable_gen = -1
        self.no_move_stable = 0

    def advance_tab(self, now=None) -> tuple:
        """当前页签扫完了 → 轮到下一个；两个都扫完 → ``(True, ...)``。"""
        if not self.rewind_done:
            self.top_unconfirmed += 1
        self.reset_page()
        if self.sweep_index + 1 >= len(_LORD_TABS_SNAPSHOT):
            self.sweep_done = True
            if now is not None:
                self.note_progress(now)
            return (True, f"两个页签都扫到底（{list(_LORD_TABS_SNAPSHOT)}）—— 扫描阶段结束")
        self.sweep_index += 1
        if now is not None:
            self.note_progress(now)
        return (
            False,
            f"「{_LORD_TABS_SNAPSHOT[self.sweep_index - 1]}」扫到底，"
            f"轮到「{_LORD_TABS_SNAPSHOT[self.sweep_index]}」",
        )

    def complete_scan(self, round_index, now=None) -> None:
        """冻结版 ``complete_scan``：把扫描标记为「本轮做完」（复位是 ``begin_round`` 的事）。"""
        self.sweep_done = True
        self.sweep_round = int(round_index)
        self.sweep_index = len(_LORD_TABS_SNAPSHOT)
        self.reset_page()
        if now is not None:
            self.note_progress(now)

    def begin_round(self, now=None) -> None:
        """冻结版 ``NavState.begin_round``：★新一轮重新武装扫描★（复位 sweep + 清累计）。"""
        self.sweep_index = 0
        self.sweep_done = False
        self.reset_page()
        self.seen.clear()
        self.dropped_in_scan = 0
        self.top_unconfirmed = 0
        self.tab_switch_failed = False
        if now is not None:
            self.note_progress(now)

    def reset(self) -> None:
        """整份清零。"""
        self.sweep_index = 0
        self.sweep_done = False
        self.sweep_round = -1
        self.switch_attempts = 0
        self.switch_for = None
        self.unconfirmed = 0
        self.scrolls_in_page = 0
        self.stable_scrolls = 0
        self.scroll_gen = 0
        self.stable_gen = -1
        self.last_scroll_at = 0.0
        self.last_rows = ()
        self.rewind_done = False
        self.rewind_scrolls = 0
        self.rewind_gen = 0
        self.rewind_stable_gen = -1
        self.rewind_stable = 0
        self.rewind_last_rows = ()
        self.rewind_failed = False
        self.dropped_in_scan = 0
        self.top_unconfirmed = 0
        self.tab_switch_failed = False
        self.bottom_unprovable = False
        self.no_move_stable_gen = -1
        self.no_move_stable = 0
        self.seen.clear()
        self.last_progress_at = 0.0

    # -- 无进展死线 ---------------------------------------------------------
    def note_progress(self, now) -> None:
        """记一次「有进展」。"""
        self.last_progress_at = now

    def stuck_reason(self, now) -> str:
        """页签/滚动/读页都不再有进展 ≥ 死线 → 返回收工理由（否则 ``""``）。"""
        if self.last_progress_at <= 0:
            return ""
        idle = now - self.last_progress_at
        if idle < _NAV_STUCK_SEC_SNAPSHOT:
            return ""
        return (
            f"导航 {idle:.0f}s 没有任何进展（死线 {_NAV_STUCK_SEC_SNAPSHOT:.0f}s）："
            f"页签={self.desired_tab()!r} 已滚 {self.scrolls_in_page} 次 / 到底={self.at_end()} —— 带原因收工"
        )


@dataclass(frozen=True)
class _PickDecisionSnapshot:
    """``scene.lords_nav.PickDecision`` 的冻结版（字段逐一照抄）。"""

    action: str
    tab: object = None
    direction: object = None
    kind: object = None
    reason: str = ""


class _PickNavSnapshot:
    """``scene.lords_nav.PickNav`` 的冻结版（字段 / 分支 / 文案逐一照抄）。

    ★为什么它也必须冻结★：``agent/`` 会被整个拷到 ``install/agent``（那里**没有** ``scene/``）。
    装好的产品在「目标行不在屏上」时同样得先对页签、再上下找 —— 否则真机缺口在安装态照样复发。
    行为与真源逐项等价由 ``tools/contract_hooks/hooks_121.py`` 的
    ``lords-pick-nav-snapshot-parity`` 钉住（同一段剧本分别跑真源与快照，判决/次数/文案逐项相等）。
    """

    row_name: object = None
    tab: object = None
    phase: str = _PICK_PHASE_DOWN_SNAPSHOT
    scrolls_down: int = 0
    scrolls_up: int = 0
    scroll_gen: int = 0
    stable_gen: int = -1
    stable_scrolls: int = 0
    last_scroll_at: float = 0.0
    last_rows: tuple = ()
    scroll_errors: int = 0
    fail_kind: object = None
    fail_reason: str = ""
    wait_since: float = 0.0

    # -- 目标 / 页签 ---------------------------------------------------------
    def begin_target(self, row_name, tab) -> bool:
        """切换到新目标（同一目标则什么都不做）。"""
        if self.row_name == row_name and self.tab == tab:
            self.row_name = row_name
            self.tab = tab
            return False
        self.row_name = row_name
        self.tab = tab
        self.reset_search()
        return True

    def reset_search(self) -> None:
        """把「找」的进度清零（``last_scroll_at`` 不清：时间闩跨页也生效）。"""
        self.phase = _PICK_PHASE_DOWN_SNAPSHOT
        self.scrolls_down = 0
        self.scrolls_up = 0
        self.scroll_gen = 0
        self.stable_gen = -1
        self.stable_scrolls = 0
        self.last_rows = ()
        self.scroll_errors = 0
        self.fail_kind = None
        self.fail_reason = ""
        self.wait_since = 0.0

    # -- 滚动记账 -----------------------------------------------------------
    def note_scroll(self, direction, now) -> None:
        """记一次**真的滚过**（方向计数 + 滚动世代 +1 + 时间闩基准 + 手势失败计数清零）。"""
        if direction == _PICK_SCROLL_UP_SNAPSHOT:
            self.scrolls_up += 1
        else:
            self.scrolls_down += 1
        self.scroll_gen += 1
        self.last_scroll_at = now
        self.scroll_errors = 0

    def note_scroll_error(self) -> int:
        """记一次**滚动手势执行失败**（返回连续失败次数）。"""
        self.scroll_errors += 1
        return self.scroll_errors

    def _restart_direction(self, phase) -> None:
        """换方向：清「这一方向到底」的计数，并把当前世代标成已记过（虚报防护）。"""
        self.phase = phase
        self.stable_scrolls = 0
        self.stable_gen = self.scroll_gen

    def observe(self, rows) -> tuple:
        """**这一方向到底了吗**：只认「有没有没见过的行」（同真源 ``PickNav.observe``）。"""
        plan = _SCROLL_PLAN_SNAPSHOT
        rows = tuple(rows or ())
        previous = set()
        for row in self.last_rows:
            if _row_cy_snapshot(row) is not None:
                previous.add(_ROW_KEY_SNAPSHOT(row))
        fresh = [_ROW_KEY_SNAPSHOT(row) for row in rows if _ROW_KEY_SNAPSHOT(row) not in previous]
        self.last_rows = rows
        if not rows:
            return (False, "空帧不算「这一方向到底」（可能根本不是列表页）")
        if fresh:
            self.stable_scrolls = 0
            self.stable_gen = self.scroll_gen
            return (False, f"新行 {len(fresh)} 个 —— 列表还在动")
        if self.scroll_gen > 0 and self.stable_gen != self.scroll_gen:
            self.stable_gen = self.scroll_gen
            self.stable_scrolls += 1
        at_end = self.stable_scrolls >= plan.stable_times
        return (
            at_end,
            f"连续 {self.stable_scrolls}/{plan.stable_times} 个滚动世代没有新行"
            f"（第 {self.scroll_gen} 次滚动那一代）",
        )

    # -- 判决 ---------------------------------------------------------------
    def decide(
        self,
        rows,
        *,
        evidence=None,
        desired=None,
        tab_decision=None,
        target_visible=False,
        list_page=True,
        now=0.0,
    ):
        """冻结版 ``PickNav.decide``（判决顺序 / 文案与真源逐字相同）。"""
        plan = _SCROLL_PLAN_SNAPSHOT
        if self.fail_kind is not None:
            return _PickDecisionSnapshot(
                _PICK_ACTION_FAIL_SNAPSHOT, self.tab, None, self.fail_kind, self.fail_reason
            )
        if not list_page or target_visible:
            self.wait_since = 0.0
            return _PickDecisionSnapshot(
                _PICK_ACTION_READY_SNAPSHOT,
                desired if desired is not None else self.tab,
                None,
                None,
                "目标行在屏上（或不在列表页）—— 交给 pick_click 的老三跳（#29：选行先于滚动）",
            )

        if tab_decision is not None:
            if tab_decision.action == _ACTION_CLICK_SNAPSHOT:
                self.wait_since = 0.0
                return _PickDecisionSnapshot(
                    _PICK_ACTION_TAB_SNAPSHOT, desired, None, None, tab_decision.reason
                )
            if tab_decision.action in (_ACTION_STOP_SNAPSHOT, _ACTION_CANNOT_SNAPSHOT):
                return self._fail(
                    _PICK_FAIL_TAB_SNAPSHOT,
                    f"{_PICK_REASON_TAB_SNAPSHOT}：目标「{self.row_name}」应在「{desired}」页签，"
                    f"但页签切不过去（{tab_decision.reason}；本页签向下 {self.scrolls_down} 次 /"
                    f" 向上 {self.scrolls_up} 次都没机会开始）—— 带原因收工",
                )
            if tab_decision.action == _ACTION_GIVE_UP_SNAPSHOT:
                if self.wait_since <= 0:
                    self.wait_since = now
                waited = now - self.wait_since
                if waited >= _PICK_TAB_WAIT_SEC_SNAPSHOT:
                    return self._fail(
                        _PICK_FAIL_TAB_SNAPSHOT,
                        f"{_PICK_REASON_TAB_SNAPSHOT}：目标「{self.row_name}」应在「{desired}」页签，"
                        f"点过页签后等了 {waited:.0f}s（宽限 {_PICK_TAB_WAIT_SEC_SNAPSHOT:.0f}s ="
                        f" {_TAB_CONFIRM_GRACE_SEC_SNAPSHOT:.0f}s × {_TAB_UNCONFIRMED_LIMIT_SNAPSHOT}）仍未确认 —— "
                        f"{tab_decision.reason} —— 带原因收工（#19：不重试）",
                    )
                return _PickDecisionSnapshot(
                    _PICK_ACTION_WAIT_SNAPSHOT,
                    desired,
                    None,
                    None,
                    f"等页签确认到「{desired}」（已等 {waited:.1f}/{_PICK_TAB_WAIT_SEC_SNAPSHOT:.0f}s）—— "
                    f"这段时间**不算**「点不动」：页签是导航，不是点目标",
                )
        else:
            self.wait_since = 0.0

        # ①b 滚动手势连续失败 → 带原因收工（= 真源同一条出口，防「回枢纽空转」）
        if self.scroll_errors >= _TAB_UNCONFIRMED_LIMIT_SNAPSHOT:
            return self._fail(
                _PICK_FAIL_SCROLL_SNAPSHOT,
                f"{_PICK_REASON_SCROLL_SNAPSHOT}：目标「{self.row_name}」的列表滚了"
                f" {self.scroll_errors} 次都没滚成（手势节点执行异常；本页签向下 {self.scrolls_down} 次 /"
                f" 向上 {self.scrolls_up} 次）—— 带原因收工（不回枢纽空转）",
            )

        # ② 上下找：先下（列表可能在上方或下方）→ 到底再向上（回顶部）
        at_end, why = self.observe(rows)
        if self.phase == _PICK_PHASE_DOWN_SNAPSHOT:
            if at_end or self.scrolls_down >= plan.max_scrolls_per_page:
                self._restart_direction(_PICK_PHASE_UP_SNAPSHOT)
                return _PickDecisionSnapshot(
                    _PICK_ACTION_SCROLL_SNAPSHOT,
                    self.tab,
                    _PICK_SCROLL_UP_SNAPSHOT,
                    None,
                    f"{why} —— 向下已到底（{self.scrolls_down}/{plan.max_scrolls_per_page} 次），"
                    f"改向上找（回顶部）",
                )
            return _PickDecisionSnapshot(
                _PICK_ACTION_SCROLL_SNAPSHOT,
                self.tab,
                _PICK_SCROLL_DOWN_SNAPSHOT,
                None,
                f"目标行不在屏上：向下滚找（{self.scrolls_down + 1}/{plan.max_scrolls_per_page}）"
                f"—— {why}",
            )
        if self.phase == _PICK_PHASE_UP_SNAPSHOT:
            if at_end or self.scrolls_up >= plan.max_scrolls_per_page:
                return self._fail(
                    _PICK_FAIL_NOT_FOUND_SNAPSHOT,
                    f"{_PICK_REASON_NOT_FOUND_SNAPSHOT}：目标「{self.row_name}」在本页签（{self.tab}）"
                    f"向下滚 {self.scrolls_down} 次 / 向上滚 {self.scrolls_up} 次，"
                    f"上下都扫到底（{why}）也没有这一行 —— 数据与画面不一致"
                    f"（列表里没有这一行：花名册/进度与画面不符）—— 带原因收工",
                )
            return _PickDecisionSnapshot(
                _PICK_ACTION_SCROLL_SNAPSHOT,
                self.tab,
                _PICK_SCROLL_UP_SNAPSHOT,
                None,
                f"向下没找到，向上滚找（{self.scrolls_up + 1}/{plan.max_scrolls_per_page}）—— {why}",
            )
        return self._fail(
            _PICK_FAIL_NOT_FOUND_SNAPSHOT,
            f"{_PICK_REASON_NOT_FOUND_SNAPSHOT}：目标「{self.row_name}」在本页签（{self.tab}）—— "
            f"上下都找过了，带原因收工",
        )

    def _fail(self, kind, reason):
        """下结论（粘住：下一圈原样重放）。"""
        self.fail_kind = kind
        self.fail_reason = reason
        self.phase = _PICK_PHASE_DONE_SNAPSHOT
        return _PickDecisionSnapshot(
            _PICK_ACTION_FAIL_SNAPSHOT, self.tab, None, kind, reason
        )


class _NavSnapshotLogic:
    """安装态回退的**导航真源替身**：字段名与 ``scene.lords_nav`` 逐一相同。"""

    LORD_TABS = _LORD_TABS_SNAPSHOT
    LIST_PAGE_ANCHOR = _LIST_PAGE_ANCHOR_SNAPSHOT
    TAB_LABELS_ALWAYS_PRESENT = _TAB_LABELS_ALWAYS_PRESENT_SNAPSHOT
    TAB_SWITCH_MAX_ATTEMPTS = _TAB_SWITCH_MAX_ATTEMPTS_SNAPSHOT
    TAB_UNCONFIRMED_LIMIT = _TAB_UNCONFIRMED_LIMIT_SNAPSHOT
    TAB_CONFIRM_GRACE_SEC = _TAB_CONFIRM_GRACE_SEC_SNAPSHOT
    CONFIRM_BASIS = _CONFIRM_BASIS_SNAPSHOT
    END_ANCHORS = _END_ANCHORS_SNAPSHOT
    NAV_STUCK_SEC = _NAV_STUCK_SEC_SNAPSHOT
    SCROLL_PLAN = _SCROLL_PLAN_SNAPSHOT
    #: ★屏幕边界 + 「行在屏上」判据★（= scene/lords_nav.SCREEN_W/H/on_screen）。
    #: 「找到了但点不动」只许在**整框在屏内**时说「行就在屏上」（#100 回归：合成帧越界）。
    SCREEN_W = _SCREEN_W_SNAPSHOT
    SCREEN_H = _SCREEN_H_SNAPSHOT
    #: ★列表行 ROI + 「这个框是不是列表行」判据★（= scene/lords_nav.ROW_ROI / row_roi_hit）。
    #: 行名只可能在列表体里：标题/横幅/页签/底栏里的同名文字一律不算（越界忽略 + 日志）。
    ROW_ROI = _ROW_ROI_SNAPSHOT
    ACTION_OK = _ACTION_OK_SNAPSHOT
    ACTION_CLICK = _ACTION_CLICK_SNAPSHOT
    ACTION_GIVE_UP = _ACTION_GIVE_UP_SNAPSHOT
    ACTION_STOP = _ACTION_STOP_SNAPSHOT
    ACTION_CANNOT = _ACTION_CANNOT_SNAPSHOT
    #: ★pick 前先对页签、再上下找★（#100 第 3 条真机缺口；= scene/lords_nav.PICK_*）
    PICK_ACTION_READY = _PICK_ACTION_READY_SNAPSHOT
    PICK_ACTION_TAB = _PICK_ACTION_TAB_SNAPSHOT
    PICK_ACTION_SCROLL = _PICK_ACTION_SCROLL_SNAPSHOT
    PICK_ACTION_WAIT = _PICK_ACTION_WAIT_SNAPSHOT
    PICK_ACTION_FAIL = _PICK_ACTION_FAIL_SNAPSHOT
    PICK_SCROLL_DOWN = _PICK_SCROLL_DOWN_SNAPSHOT
    PICK_SCROLL_UP = _PICK_SCROLL_UP_SNAPSHOT
    PICK_PHASE_DOWN = _PICK_PHASE_DOWN_SNAPSHOT
    PICK_PHASE_UP = _PICK_PHASE_UP_SNAPSHOT
    PICK_PHASE_DONE = _PICK_PHASE_DONE_SNAPSHOT
    PICK_FAIL_TAB = _PICK_FAIL_TAB_SNAPSHOT
    PICK_FAIL_NOT_FOUND = _PICK_FAIL_NOT_FOUND_SNAPSHOT
    PICK_FAIL_CLICK = _PICK_FAIL_CLICK_SNAPSHOT
    PICK_FAIL_SCROLL = _PICK_FAIL_SCROLL_SNAPSHOT
    PICK_REASON_TAB = _PICK_REASON_TAB_SNAPSHOT
    PICK_REASON_NOT_FOUND = _PICK_REASON_NOT_FOUND_SNAPSHOT
    PICK_REASON_CLICK = _PICK_REASON_CLICK_SNAPSHOT
    PICK_REASON_SCROLL = _PICK_REASON_SCROLL_SNAPSHOT
    PICK_TAB_WAIT_SEC = _PICK_TAB_WAIT_SEC_SNAPSHOT
    TabAnchor = _TabAnchorSnapshot
    TabEvidence = _TabEvidenceSnapshot
    TabDecision = _TabDecisionSnapshot
    ScrollPlan = _ScrollPlanSnapshot
    NavState = _NavStateSnapshot
    PickDecision = _PickDecisionSnapshot
    PickNav = _PickNavSnapshot
    TAB_ANCHORS = {
        tab: _TabAnchorSnapshot(tab=tab, **spec) for tab, spec in _TAB_ANCHOR_SNAPSHOT.items()
    }
    label_box = staticmethod(_LABEL_BOX_SNAPSHOT)
    tab_labels = staticmethod(_TAB_LABELS_SNAPSHOT)
    list_page_present = staticmethod(_LIST_PAGE_PRESENT_SNAPSHOT)
    classify_kind = staticmethod(_CLASSIFY_KIND_SNAPSHOT)
    tab_of_kind = staticmethod(_TAB_OF_KIND_SNAPSHOT)
    tab_of_row = staticmethod(_TAB_OF_ROW_SNAPSHOT)
    tab_state = staticmethod(_TAB_STATE_SNAPSHOT)
    row_key = staticmethod(_ROW_KEY_SNAPSHOT)
    end_anchor_hit = staticmethod(_END_ANCHOR_HIT_SNAPSHOT)
    on_screen = staticmethod(_ON_SCREEN_SNAPSHOT)
    #: ★列表行 ROI 判据★（= scene/lords_nav.row_roi_hit；find_row_box 的 ROI 过滤靠它）。
    row_roi_hit = staticmethod(_ROW_ROI_HIT_SNAPSHOT)
    #: ★行名不能是徽标★（= scene/lords_nav.LIST_BADGE_MARKS / is_badge_text）：徽标被读成
    #: 行名会污染 ``plan_round`` 与「新解锁」（真机 484 第 5 轮验收：2 行读成 ``COMPLETE!!``）。
    LIST_BADGE_MARKS = _LIST_BADGE_MARKS_SNAPSHOT
    is_badge_text = staticmethod(_IS_BADGE_TEXT_SNAPSHOT)
    #: ★行名被读成徽标 ⇒ 用几何把真名找回来★（= scene/lords_nav.recover_badge_row_name；
    #: 真机 484 accept7：领主战每轮扫描累计被剔 41–46 行，真名其实就在帧里）。
    BADGE_RECOVERY_MAX_DY = _BADGE_RECOVERY_MAX_DY_SNAPSHOT
    BADGE_RECOVERY_MIN_LEFT_GAP = _BADGE_RECOVERY_MIN_LEFT_GAP_SNAPSHOT
    recover_badge_row_name = staticmethod(_RECOVER_BADGE_ROW_NAME_SNAPSHOT)

    # -- ★#100 第 4、5 个真机缺口：页面状态 + 模式选择页 + 非列表页死线★ ----------
    # （= scene/lords_nav 的同名常量/函数 + scene/page_rules 的五条判据；hooks_122 对账）
    LORDS_STATE_CITY = _LORDS_STATE_CITY_SNAPSHOT
    LORDS_STATE_LIST = _LORDS_STATE_LIST_SNAPSHOT
    LORDS_STATE_DETAIL = _LORDS_STATE_DETAIL_SNAPSHOT
    LORDS_STATE_TEAM = _LORDS_STATE_TEAM_SNAPSHOT
    LORDS_STATE_MODE = _LORDS_STATE_MODE_SNAPSHOT
    LORDS_STATE_BATTLE = _LORDS_STATE_BATTLE_SNAPSHOT
    LORDS_STATE_SETTLE = _LORDS_STATE_SETTLE_SNAPSHOT
    LORDS_STATE_LOADING = _LORDS_STATE_LOADING_SNAPSHOT
    LORDS_STATE_UNKNOWN = _LORDS_STATE_UNKNOWN_SNAPSHOT
    LORDS_STATES = _LORDS_STATES_SNAPSHOT
    LORDS_ACTIVE_STATES = _LORDS_ACTIVE_STATES_SNAPSHOT
    #: ★放闩证据★（= ``scene/lords_nav.LORDS_CHALLENGE_RELEASE_STATES``）：见到 battle/settle
    #: 等**正向页**就立刻放开「刚点过挑战」的闩（主路径；180s 只是兜底）。
    LORDS_CHALLENGE_RELEASE_STATES = _LORDS_CHALLENGE_RELEASE_STATES_SNAPSHOT
    #: ★过渡态集合 + 加载帧判据★（= scene/lords_nav 的同名常量/函数；hooks_122 逐项对账）。
    #: 过渡态在「非列表页死线」里**不累加**计时（真机 484 14:5x：--home 后立刻跑被误杀）。
    LORDS_LOADING_ANCHORS = _LORDS_LOADING_ANCHORS_SNAPSHOT
    LORDS_TRANSITION_STATES = _LORDS_TRANSITION_STATES_SNAPSHOT
    LORDS_MODE_SOLO = _LORDS_MODE_SOLO_SNAPSHOT
    LORDS_MODE_SOLO_NOTE = _LORDS_MODE_SOLO_NOTE_SNAPSHOT
    LORDS_MODE_MULTI = _LORDS_MODE_MULTI_SNAPSHOT
    LORDS_MODE_MULTI_NOTE = _LORDS_MODE_MULTI_NOTE_SNAPSHOT
    LORDS_MODE_SOLO_ROI = _LORDS_MODE_SOLO_ROI_SNAPSHOT
    LORDS_MODE_MULTI_ROI = _LORDS_MODE_MULTI_ROI_SNAPSHOT
    LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY = _LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY_SNAPSHOT
    LORDS_MODE_MAX_ATTEMPTS = _LORDS_MODE_MAX_ATTEMPTS_SNAPSHOT
    LORDS_MODE_CONFIRM_GRACE_SEC = _LORDS_MODE_CONFIRM_GRACE_SEC_SNAPSHOT
    #: ★#100 缺口 7/8★：编队页正向锚 + 换点阶梯 + 盲点拒绝（= scene/lords_nav 的同名常量/函数）。
    LORDS_TEAM_ANCHORS = _TEAM_ANCHORS_SNAPSHOT
    LORDS_MODE_CLICK_LADDER = _LORDS_MODE_CLICK_LADDER_SNAPSHOT
    LORDS_MODE_CLICK_WAIT_SEC = _LORDS_MODE_CLICK_WAIT_SEC_SNAPSHOT
    LORDS_PAGE_RULE_NAMES = _PAGE_RULE_NAMES_SNAPSHOT
    LORDS_PAGE_RULES = _PAGE_RULE_RECOGNITION_SNAPSHOT
    NON_LIST_STUCK_SEC = _NON_LIST_STUCK_SEC_SNAPSHOT
    NON_LIST_STUCK_REASON = _NON_LIST_STUCK_REASON_SNAPSHOT
    ModeEvidence = _ModeEvidenceSnapshot
    page_state = staticmethod(_PAGE_STATE_SNAPSHOT)
    #: ★放闩证据★（= ``scene/lords_nav.challenge_release_evidence``）：见到 battle/settle ⇒ 放闩。
    challenge_release_evidence = staticmethod(_CHALLENGE_RELEASE_EVIDENCE_SNAPSHOT)
    #: ★详情页逐档状态（本票 ①）★：只点**未通关**的那一档，绝不盲取最上面那个战斗框
    #: （= ``scene/lords_nav`` 第 7b 节；真机 484 第 3 轮验收：地狱级已 COMPLETE!! 仍在最上）。
    DETAIL_STATUS_COMPLETE = _DETAIL_STATUS_COMPLETE_SNAPSHOT
    DETAIL_STATUS_NEW = _DETAIL_STATUS_NEW_SNAPSHOT
    DETAIL_MARK_COMPLETE = _DETAIL_MARK_COMPLETE_SNAPSHOT
    DETAIL_MARK_NEW = _DETAIL_MARK_NEW_SNAPSHOT
    DETAIL_MARK_MAX_DY = _DETAIL_MARK_MAX_DY_SNAPSHOT
    DETAIL_BACK_TEXT = _DETAIL_BACK_TEXT_SNAPSHOT
    DETAIL_BACK_ROI = _DETAIL_BACK_ROI_SNAPSHOT
    DETAIL_PICK_READY = _DETAIL_PICK_READY_SNAPSHOT
    DETAIL_PICK_ALL_COMPLETE = _DETAIL_PICK_ALL_COMPLETE_SNAPSHOT
    DETAIL_PICK_NO_STATUS = _DETAIL_PICK_NO_STATUS_SNAPSHOT
    DETAIL_PICK_NO_TIERS = _DETAIL_PICK_NO_TIERS_SNAPSHOT
    DETAIL_TIER_NO_STATUS_REASON = _DETAIL_TIER_NO_STATUS_REASON_SNAPSHOT
    DETAIL_TIER_ALL_DONE_REASON = _DETAIL_TIER_ALL_DONE_REASON_SNAPSHOT
    DETAIL_TIER_UNREAD_REASON = _DETAIL_TIER_UNREAD_REASON_SNAPSHOT
    DETAIL_TIER_NAME_RE = _DETAIL_TIER_NAME_RE_SNAPSHOT
    DetailTier = _DetailTierSnapshot
    DetailTierChoice = _DetailTierChoiceSnapshot
    detail_status_text = staticmethod(_detail_status_text_snapshot)
    detail_tier_name = staticmethod(_detail_tier_name_snapshot)
    detail_mark_status = staticmethod(_detail_mark_status_snapshot)
    detail_tier_rows = staticmethod(_DETAIL_TIER_ROWS_SNAPSHOT)
    pick_uncleared_tier = staticmethod(_PICK_UNCLEARED_TIER_SNAPSHOT)
    detail_back_box = staticmethod(_DETAIL_BACK_BOX_SNAPSHOT)
    loading_frame = staticmethod(_LOADING_FRAME_SNAPSHOT)
    mode_evidence = staticmethod(_MODE_EVIDENCE_SNAPSHOT)
    page_rule_hit = staticmethod(_PAGE_RULE_HIT_SNAPSHOT)
    non_list_stuck_reason = staticmethod(_NON_LIST_STUCK_REASON_SNAPSHOT_FN)
    team_anchor_hit = staticmethod(_TEAM_ANCHOR_HIT_SNAPSHOT)
    team_page_confirmed = staticmethod(_TEAM_PAGE_CONFIRMED_SNAPSHOT)
    mode_click_points = staticmethod(_MODE_CLICK_POINTS_SNAPSHOT)
    mode_click_exhausted_reason = staticmethod(_MODE_CLICK_EXHAUSTED_REASON_SNAPSHOT)
    #: ★#100 第 9 个缺口★：点完「单人游戏」后的**轮询读帧** + 「加成点数」确认框
    #: （= scene/lords_nav 的同名常量 / BonusDialog / bonus_dialog；hooks_122 逐项对账）。
    LORDS_MODE_POLL_INTERVAL_SEC = _LORDS_MODE_POLL_INTERVAL_SEC_SNAPSHOT
    LORDS_MODE_POLL_TIMEOUT_SEC = _LORDS_MODE_POLL_TIMEOUT_SEC_SNAPSHOT
    LORDS_MODE_STABLE_READS = _LORDS_MODE_STABLE_READS_SNAPSHOT
    LORDS_MODE_STILL_MODE_READS = _LORDS_MODE_STILL_MODE_READS_SNAPSHOT
    LORDS_MODE_BONUS_QUESTION_ANCHORS = _LORDS_MODE_BONUS_QUESTION_ANCHORS_SNAPSHOT
    LORDS_MODE_BONUS_ACCEPT = _LORDS_MODE_BONUS_ACCEPT_SNAPSHOT
    LORDS_MODE_BONUS_DECLINE = _LORDS_MODE_BONUS_DECLINE_SNAPSHOT
    LORDS_MODE_BONUS_CHOICE = _LORDS_MODE_BONUS_CHOICE_SNAPSHOT
    LORDS_MODE_MAX_DIALOG_CLICKS = _LORDS_MODE_MAX_DIALOG_CLICKS_SNAPSHOT
    BonusDialog = _BonusDialogSnapshot
    bonus_dialog = staticmethod(_BONUS_DIALOG_SNAPSHOT)


_NAV_ANNOUNCED = False


def _announce_nav_snapshot_once() -> None:
    """安装态导航回落只播报**一次**。"""
    global _NAV_ANNOUNCED
    if _NAV_ANNOUNCED:
        return
    _NAV_ANNOUNCED = True
    print(
        "[lords] 取不到 scene/lords_nav.py（安装态）—— 改用本文件的逐字冻结快照"
        "（_NavSnapshotLogic），行为与真源逐项等价（hooks_100 的 lords-nav-snapshot-parity 钉住）"
    )


def _scene_nav():
    """``scene.lords_nav``（导航真源，纯逻辑）；安装态（模块不在场）返回 ``None``。"""
    try:
        import importlib

        return importlib.import_module("scene.lords_nav")
    except ModuleNotFoundError:
        return None


def _nav():
    """导航真源：仓库态 = ``scene.lords_nav``；安装态 = 本文件的冻结快照。

    ★两条路都不通时返回 ``None``★（不崩、不假成功）：调用方据此**不命中**，
    见 :data:`NAV_INSTALL_STATE_REASON`。
    """
    scene = _scene_nav()
    if scene is not None:
        return scene
    _announce_nav_snapshot_once()
    return _NavSnapshotLogic


def _challenge_release_state(items) -> str:
    """这一帧是不是「点过【挑战】之后已经离开编队页」的**正向证据**（状态名 / 空串）。

    真源 = ``scene.lords_nav.challenge_release_evidence``（安装态 = 冻结快照的同名函数）；
    两条路都拿不到 / 拿不到帧 ⇒ ``""``（= 没有证据，继续等，交给 180s 兜底）。
    """
    navl = _nav()
    checker = getattr(navl, "challenge_release_evidence", None)
    if not items or checker is None:
        return ""
    try:
        return str(checker(items) or "")
    except Exception:  # noqa: BLE001 - 判据异常绝不许把「等战斗」这条路打崩（退回兜底）
        return ""


def _page_state(items) -> str:
    """这一帧的 lords 页面状态名（真源 / 安装态快照两条路；都取不到 ⇒ ``""``）。"""
    navl = _nav()
    checker = getattr(navl, "page_state", None)
    if not items or checker is None:
        return ""
    try:
        return str(checker(items) or "")
    except Exception:  # noqa: BLE001 - 诊断/记账绝不许把识别打崩
        return ""


def _note_after_fight(session, items=None) -> bool:
    """★D6 关轮的起点★：见到 ``战斗HUD`` / ``结算页`` ⇒ 记「这一场打完了，回列表要重读」。

    为什么在**每一帧**都记（``analyze`` 里与放闩同一处）：战斗可能打几分钟，中间任何一帧
    都可能先于「结算」被读到；只要确认过战斗/结算，这一局就**已经发生过**了 —— 之后无论落在
    详情页（点【返回】）还是列表页（让 ``mode=read`` 先读），都必须先关掉这一轮。
    返回是否**新**置位（只用于日志，不参与判定）。
    """
    if session.back_to_list_pending:
        return False
    navl = _nav()
    states = tuple(getattr(navl, "LORDS_ACTIVE_STATES", ())) if navl is not None else ()
    state = _page_state(items)
    if not state or state not in states:
        return False
    session.back_to_list_pending = True
    print(
        f"[lords] 见到 {state}（这一场已经打起来了）—— 记下「回列表后必须先重读 通关数、关本轮」"
        f"（D6：每轮重开列表；修前 round 从不关闭，第 4/5/6 场全在重打已通关的档）",
        flush=True,
    )
    return True


def _back_to_list_gate(session, items) -> str:
    """``back_to_list_pending`` 期间**列表页**上的让路理由（非列表页返回 ``""``）。

    ★为什么必须让路★：回到列表后枢纽里 ``LordsPickTarget`` 排在 ``LordsReadProgress`` **之前**；
    不让路就会按**上一轮**的 ``session.targets`` 再点一次行（真机：一直重打开头那一族），
    永远走不到「关轮 → 重新 plan_round」。让路之后这一圈只剩 ``mode=read`` 能命中。
    """
    if not session.back_to_list_pending:
        return ""
    navl = _nav()
    checker = getattr(navl, "list_page_present", None) if navl is not None else None
    if not items or checker is None or not checker(items):
        return ""
    return (
        "这一场刚打完 / 刚点过【返回】—— 回合还没关闭：把这一圈让给 mode=read 重读 `通关数 N/M`"
        "（D6；先关本轮再选新目标，绝不再按旧目标点一次）"
    )


def _detail_tier_choice(items, difficulty):
    """详情页逐档状态 → 选档判决（真源 / 安装态快照；都没有 ⇒ ``None``）。

    ★``None`` 的语义是「读不了档状态 ⇒ 不点」★ —— 调用方**不许**退回「取最上面那个战斗框」。
    """
    navl = _nav()
    picker = getattr(navl, "pick_uncleared_tier", None) if navl is not None else None
    if picker is None:
        return None
    try:
        return picker(list(items or ()), difficulty)
    except Exception as exc:  # noqa: BLE001 - 选档炸了也绝不盲点（这一圈不点，死线兜底）
        print(f"[lords] 详情页档状态读不出（{exc!r}）—— 本圈不点任何档（绝不盲点）")
        return None


def _detail_back(items):
    """详情页左下角【返回】的框（真源 / 安装态快照；都没有 ⇒ ``None``）。"""
    navl = _nav()
    finder = getattr(navl, "detail_back_box", None) if navl is not None else None
    if finder is None or not items:
        return None
    try:
        return finder(list(items))
    except Exception:  # noqa: BLE001 - 读不出返回 = 本圈不点，死线兜底
        return None


# ---------------------------------------------------------------------------
# 会话（按 task_id 分槽；换任务即清零，与 agent/my_reco.py 的 _sync_task 同语义）
# ---------------------------------------------------------------------------
@dataclass
class Session:
    """一趟解禁任务的运行状态。★判定不在本类里★ —— 只存「喂给 should_stop 的事实」。"""

    task_id: int | None = None
    round_index: int = 0                # 已关闭的轮数（0 = 还没打完过第一轮）
    sessions_played: int = 0            # 累计场次（点下【挑战】即 +1）
    attempts_since_read: int = 0        # 上次读列表之后点了几次（用于判定「一轮结束」）
    sessions_at_last_read: int = 0      # 上次读列表时的累计场次
    played_this_round: int = 0          # 本轮实际打掉的场次
    no_progress_rounds: int = 0         # 连续多少轮没有新解锁
    #: ★上一轮**完整扫描**的 ``{行名: N}``★（真机 484 第 7 轮验收：绝不能再被「战后单帧」覆盖）。
    #: 只由 :meth:`LordsProgressRecognition._settle_round_gain` 在 ``mode=end`` 的合成帧上写。
    prev_cleared: dict = field(default_factory=dict)
    #: ★本票 ①「关轮只认整轮扫描帧」★：已经关了一轮，但「这一轮有没有新解锁」**还没判** ——
    #: 等下一次**完整扫描**（``mode=end`` 的合成帧）的读数来判。置位：
    #: :meth:`LordsProgressRecognition._close_round_if_needed`。清零：**只有真判过才清零**——
    #: 「无法判断」（扫描里有行被徽标剔除）**保持挂起**，等下一次干净扫描。
    gain_pending: bool = False
    #: ★本票 ②「徽标剔行 = 不可判」的账★：因为「整轮扫描里有行被徽标剔除」而**判不了**新解锁的
    #: 次数。只用于日志 / detail（说清「为什么这条兜底没动」）；**绝不**用来累加 ``no_progress``。
    gain_undecidable: int = 0
    targets: list = field(default_factory=list)        # 本轮目标（scene.lords_unlock.Target）
    pending: object = None              # 识别选出、等动作点下去的 ClickStep
    stage: str = STAGE_LIST
    last_reason: str = ""
    # 点下【挑战】之后置位：**这一场没结束前不许再点挑战**（禁双击开打）。
    # 由「点到行/档」（说明已经翻页了）或「读回列表页」清掉；主路径 = **见到 battle/settle
    # 等正向证据就当场放**（`_release_challenge_latch_on_evidence`，见 analyze），
    # `FIGHT_GRACE_SEC` = 180s 只是「点了没反应」的兜底超时
    # （真机 484 第 3 轮验收：旧实现只靠超时 ⇒ 每场白等 ~182s）。
    challenge_pending: bool = False
    challenge_clicked_at: float = 0.0
    #: ★本票 ②（D6 关轮）★：这一场已经打完 / 刚点过【返回】，但**还没回列表重读** `通关数 N/M`。
    #: 置位：① 见到 ``lords_battle`` / ``lords_settle``（战斗真的发生了，见 ``_note_after_fight``）；
    #: ② 动作点了 ``WHAT_BACK``（回列表那一跳）。清零：``mode=read`` **真的读到了行**。
    #: 置位期间：详情页只点【返回】（不选档）、列表页把这一圈**让给 mode=read**（不点行/不滚/不推页签）
    #: —— 否则「结算 → 详情 → 返回 → 列表」之后会先按**旧的**目标重打，永远关不了这一轮
    #: （真机 484 第 3 轮验收：第 4/5/6 场全在重打已通关的地狱级，日志里一次「第 N 轮结束」都没有）。
    back_to_list_pending: bool = False
    #: ★行名徽标过滤的账★（真机 484 第 5 轮验收，18:12–18:18）：本轮被剔掉的**假行名**
    #: （徽标被读成行名，见 :data:`scene.lords_nav.LIST_BADGE_MARKS`）。只用于两件事：
    #: ① 日志 / detail 里说清「这一轮为什么少了这几行」（**绝不静默丢**）；
    #: ② ★有行被剔掉时不许宣布「全部解禁」★ —— 丢的那一行可能正是 ``N<M`` 的那一行。
    badge_dropped: list = field(default_factory=list)
    last_click_at: float = 0.0          # 最近一次**成功**点击的时刻（死线基准）
    # 导航状态（页签扫描 + 页内滚动 + 去重累计；#100 第 1、2 条缺口）。
    # ★延迟到第一次用的时候才建★：`_session()` 在 import 期就会跑，那时 `_nav()` 可能还
    # 没准备好（安装态回落要 import），所以这里给 None，由 :func:`_nav_state` 惰性补上。
    nav: object = None
    # 目标行归位状态（pick 前先对页签、再上下找；#100 第 3 条缺口）—— 同样惰性创建，
    # 由 :func:`_pick_nav_state` 补上。
    pick_nav: object = None
    # ★#100 第 5 个真机缺口：噪声 + 有界★ -----------------------------------
    #: 上一次打印的「页签：…」那一行 + 当时的页面状态（**同一 (state, 行) 连续命中只打一次**）。
    #: 修前 ``mode=tab`` 在非列表页每帧打一行「页签：cannot / 不在领主战列表页…」，
    #: 一分钟几十行，长跑日志直接被淹。
    last_tab_log: tuple = ()
    #: 非列表页死线的**状态名**与起点：状态名一变就重新计时（「在不在动」只看状态名，
    #: 不看画面 —— 画面每帧都在抖，拿它判会把正常页也判成没进展）。
    non_list_state: str | None = None
    non_list_since: float = 0.0
    #: 模式选择页点「单人游戏」的账（#100 第 4、7 个真机缺口）：
    #: 当前**换点阶梯**点了几次（0..``LORDS_MODE_MAX_ATTEMPTS``）；阶梯全失败时留着 4 作证据。
    mode_clicks: int = 0
    mode_clicked_at: float = 0.0
    #: 阶梯里读到过**正向证据**（当帧明确是编队页：挑战 + SET/Party/自动续战 之一）。
    #: ★这是复核唯一的成功依据★——没有它一律不算成功（不许用「离开了模式页」否定式判据）。
    mode_verified: bool = False
    #: 四个点都试过仍停在模式页 ⇒ 收工理由（★粘住★；由 ``_tab`` / ``_mode`` 立刻
    #: override 到 ``LordsStop``，不许被通用的非列表页死线抢先 —— 那条的病因太远）。
    mode_fail_reason: str = ""
    #: ★#100 第 9 个缺口★：点「单人游戏」后弹出的**加成点数确认框**一共点了几次
    #: （每次 ``_mode_click`` 归零；上限 ``LORDS_MODE_MAX_DIALOG_CLICKS`` —— 它只该出现一次）。
    mode_dialog_clicks: int = 0
    #: ``mode=pick`` **空转诊断**的限流账（同一原因每 ``PICK_DIAG_EVERY`` 轮打一行）：
    #: 修前这条诊断是「每帧一行」，长跑时会把日志淹掉（与 ``_tab_log_once`` 同一条降噪纪律）。
    pick_diag_key: tuple = ()
    pick_diag_same: int = 0
    #: ★已判收工★（识别 override 到 ``LordsStop`` 的同时置位）：动作**成功但不点不滚**。
    #: 为什么必须这样：识别命中 + ``override_next`` 改的是本节点的 ``next``，而框架只有在
    #: **动作成功**时才走 ``next``；动作若失败会走 ``on_error``（= 回枢纽）—— override 作废，
    #: 「收工」就会在枢纽里无限重来。修前没有这个闩，收工节点的动作靠**点 (0,0) 返回 True**
    #: 混过去（#100 第 8 个缺口的盲点）；现在框闸拒绝 (0,0)，必须有显式的「成功但不做」。
    stop_requested: bool = False

    def reset_round_counters(self) -> None:
        self.attempts_since_read = 0
        self.badge_dropped = []          # 新一轮重新记账（上一轮剔掉的假行名不再影响「全通」判断）


_SESSIONS: dict = {}
_LOCK = threading.Lock()


def _session(task_id) -> Session:
    """取（或建）当前任务的会话；``task_id`` 变了就整份换新。"""
    with _LOCK:
        session = _SESSIONS.get(task_id)
        if session is None or session.task_id != task_id:
            session = Session(task_id=task_id)
            _SESSIONS[task_id] = session
        return session


def reset_sessions() -> None:
    """清空全部会话（换任务 / 离线测试用）。"""
    global _SNAPSHOT_ANNOUNCED, _NAV_ANNOUNCED
    with _LOCK:
        _SESSIONS.clear()
    _SNAPSHOT_ANNOUNCED = False      # 安装态回落的那行播报也跟着重来（测试可重复观察）
    _NAV_ANNOUNCED = False


def _nav_state(session):
    """会话的导航状态（惰性创建；真源与冻结快照都取不到时返回 ``None``）。"""
    if session.nav is None:
        navl = _nav()
        if navl is None:
            return None
        session.nav = navl.NavState()
    return session.nav


def _pick_nav_state(session):
    """会话的**目标行归位**状态（惰性创建；真源与冻结快照都取不到时返回 ``None``）。

    ★为什么单独一个状态★：扫描期（``page_pending``）的滚动计数 / 到底世代归
    :class:`scene.lords_nav.NavState` 管；pick 期的「先对页签、再上下找」是**另一件事**
    （自己的两向计数、自己的失败结论）。两套账不混，下一轮 ``begin_round`` 只清扫描那本账。
    """
    if session.pick_nav is None:
        navl = _nav()
        if navl is None:
            return None
        pick_cls = getattr(navl, "PickNav", None)
        if pick_cls is None:
            return None
        session.pick_nav = pick_cls()
    return session.pick_nav


def _ensure_round(navl, nav, session, now: float | None = None) -> bool:
    """★扫描入口的「重新武装」★（R2）：``page_pending`` 为真、而扫描已被上一轮置成「做完」时，
    调 ``NavState.begin_round`` 复位 sweep + 清页内状态 + **清累计读数**。

    ★为什么必须有它★：``NavState.reset()`` 全仓无人调用，``complete_scan()`` 只把
    ``sweep_done`` 置真、``sweep_index`` 推到末位，**没有任何地方复位**。于是第 2 轮
    ``page_pending()`` 为真、``desired_tab()`` 却是 ``None`` ⇒ 不切页签、页签闸被跳过、
    ``advance_tab`` 立刻返回「两个页签都扫到底」（其实一个都没扫）——「打没打过的，直到
    全 M/M」在第一次通关之后就停在半路。

    返回「这一圈是否刚重新武装」（写进 detail，便于日志复核）。
    """
    if not nav.page_pending(session.round_index):
        return False
    if not (nav.sweep_done or int(nav.sweep_index) >= len(navl.LORD_TABS)):
        return False
    nav.begin_round(now)
    print(
        f"[lords] 第 {session.round_index} 轮开始：扫描重新武装"
        f"（sweep 复位 + 页内计数清零 + 累计读数清空）"
    )
    return True


# ---------------------------------------------------------------------------
# ★页面状态（classify 的 lords 版）+ 日志降噪 + 模式页复核★（#100 第 4、5 个真机缺口）
# ---------------------------------------------------------------------------
def classify(items) -> str:
    """**lords 自己的**页面分类（真源 = ``scene/lords_nav.page_state``；安装态 = 冻结快照）。

    ★为什么必须自己有一份★（#100 第 4 个真机缺口）：真机现场 lords 的页面被判成
    ``wuchong_mode``（**别的场景**的状态名），于是 lords 状态机不认识这一页、也没有任何
    有界出口。这里返回的状态名**全部**是 ``lords_*``（见 :data:`_LORDS_STATES_SNAPSHOT` /
    ``scene.lords_nav.LORDS_STATES``）—— 跨场景状态名混用会让排查时说不清是谁的页面。

    ★两条路都不通★（真源与快照都取不到）时返回空串：不猜一个假状态（不假成功）。
    """
    navl = _nav()
    if navl is None:
        return ""
    return navl.page_state(items)


def _mode_step_state(items, navl) -> str:
    """★页面状态分派（本票核心 ②）★：这一帧该不该走「模式选择页」那条路？

    返回 :data:`MODE_SOLO`（该走 :meth:`LordsProgressRecognition._mode`）/ ``""``（不走）。

    判据（★都在 ``scene/lords_nav``，这里只做分派、不复制判据★）：

    * ``navl.page_state(items) == navl.LORDS_STATE_MODE`` —— 模式选择页（单人/多人）；
    * ``navl.bonus_dialog(items).is_dialog`` —— 点完「单人游戏」后弹出的**加成点数确认框**
      （背景仍是模式页，但「单人游戏」被遮住 ⇒ ``page_state`` 只能给 ``lords_unknown``）。

    ★为什么必须有它（真机 484 第二轮验收）★：tier 点完进的是模式页，而 ``_pick`` 当时只判
    ``_pick_locate`` + ``pick_click`` —— ``pick_click`` 的「列表行」分支把模式页**顶部的领主名
    标题**当成了列表行，连点同一个坐标（346,201）3 次无反应。分派必须排在 ``pick_click``
    **之前**（``hooks_122`` 的 ``lords-row-roi-title-not-row`` / ``lords-row-roi-ignore`` 钉住）。
    """
    if navl is None:
        return ""
    if navl.page_state(items) == navl.LORDS_STATE_MODE:
        return MODE_SOLO
    if navl.bonus_dialog(items).is_dialog:
        return MODE_SOLO
    return ""


def _tab_log_once(session, state: str, line: str) -> bool:
    """这条「页签：…」该不该打印（**同一 ``(state, line)`` 连续命中只打一次**）。

    ★#100 第 5 个真机缺口的降噪★：修前 ``mode=tab`` 每帧打一行
    ``[lords] 页签：cannot / 不在领主战列表页（读不到「更新列表」）—— 不在这里点页签``，
    在非列表页上一分钟几十行，长跑日志被淹。现在**状态名一变就允许再打一次**
    （``state`` 进键里），同一状态里的同一句只打一次 —— 既不刷屏，也不丢「页面变了」这个信息。

    单独一个函数是为了让守卫能**注入一条恒真的坏实现**（``lambda ...: True``）做破坏实验。
    """
    key = (state, line)
    if session.last_tab_log == key:
        return False
    session.last_tab_log = key
    return True


#: 同一原因连续出现时，``mode=pick`` 的**空转诊断**每 N 轮打一行（首行必打）。
#: 取值 5 = 票面给的「每 5 轮打一次」（与 ``_tab_log_once`` 的「状态变化才打」互补：
#: 状态一变立刻打，状态不变时每 5 轮给一个心跳，既看得见卡在哪、又不刷屏）。
PICK_DIAG_EVERY: int = 5


def _pick_diag_once(session, key, line: str) -> bool:
    """``mode=pick`` 空转诊断的限流（★#100 第 9 个缺口：卡住时要一眼看出卡在哪★）。

    打印规则：
    * **键一变就打**（键 = 页面状态 / 行框在不在 / 阶段）—— 页面变了本身是信息；
    * 键不变时**每 :data:`PICK_DIAG_EVERY` 轮打一次**（心跳，证明它还活着、还卡在同一处）。

    ★为什么必须限流★：``mode=pick`` 是枢纽里最热的节点；修前那条临时诊断**每帧一行**，
    真机长跑一分钟几十行，把「卡在哪」本身淹掉（与 ``_tab_log_once`` 同一条降噪纪律）。
    单独一个函数是为了让守卫能注入一条恒真的坏实现（``lambda ...: True``）做破坏实验。
    """
    key = tuple(key)
    if key != session.pick_diag_key:
        session.pick_diag_key = key
        session.pick_diag_same = 0
        return True
    session.pick_diag_same += 1
    return session.pick_diag_same % PICK_DIAG_EVERY == 0


def _note_mode_result(session, state: str, navl, items=None) -> str:
    """点过「单人游戏」之后的**正向复核**（``""`` = 没有待复核的点击）。

    返回值写进 detail 的 ``mode_verify``（★#100 第 7 个真机缺口：只认正向证据★）：

    * ``"team_page"`` —— ★成功★：当帧**明确是编队页**（``navl.team_page_confirmed``：
      有【挑战】∧ ``SET`` / ``Party`` / ``自动续战`` 至少一个）；
    * ``"still_mode"`` —— 又回到模式页（点击**没生效**；换点阶梯继续试，绝不判成功）；
    * ``"unconfirmed:<state>"`` —— 别的页面（瞬时帧 / 转场）：**不算成功、不清账**，
      等下一帧再判。

    ★为什么不再用「离开了模式页」★：真机 484（14:0x）点完「单人游戏」后复核读到瞬时帧
    ``lords_unknown``，旧判据把它当成「离开了模式页」= **假成功**；15s 后手工 screencap
    设备**仍停在模式页**（单人/多人两张卡都在）。否定式判据分不清「转场帧」与「到了」。

    ★只有正向成功才清点击账★：``mode_clicks`` / ``mode_verified`` 只有在编队页确认后才归零，
    这样「unknown → 又回模式页」既不会被误判成功，也不会把阶梯的账抹掉。
    """
    if session.mode_clicks <= 0:
        return ""
    # ★当前帧又回到模式页 ⇒ 一律「没生效」★：即使阶梯那一次读曾确认过编队页，
    # 现在人在模式页也不许再报成功（判据看**当帧**，不看记忆）。
    if state == navl.LORDS_STATE_MODE:
        return "still_mode"
    if session.mode_verified:
        session.mode_clicks = 0
        session.mode_clicked_at = 0.0
        session.mode_verified = False
        return "team_page"
    if navl.team_page_confirmed(items):
        session.mode_clicks = 0
        session.mode_clicked_at = 0.0
        return "team_page"
    return f"unconfirmed:{state}"


def _mode_verify_line(verify: str) -> str:
    """复核结论 → 一行日志（★「成功」只许出现在正向证据那一支★）。"""
    if verify == "team_page":
        return "已在编队页（挑战 + SET/Party/自动续战 至少一个）✓ —— 正向证据"
    if verify == "still_mode":
        return "又回到模式页（点击没生效）—— 交给换点阶梯，绝不判成功"
    return f"画面是 {verify.split(':', 1)[-1]}，不是编队页 —— 未确认（不假成功）"


def _is_stop_requested(session) -> bool:
    """★已判收工？★（``Session.stop_requested``；单独一个函数便于守卫注入坏实现）。

    识别在 ``override_next(..., [LordsStop])`` 的同一处置位；动作看到它必须**成功但不点**
    —— 见 :meth:`LordsUnlockAction._dispatch` 的注释（返回 False 会走 on_error 回枢纽）。
    """
    return bool(getattr(session, "stop_requested", False))


# ---------------------------------------------------------------------------
# 「下一处该点的框」—— 纯函数（注入 OCR 项即可离线断言）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ClickStep:
    """一处待点击：框（720 空间）+ 它是什么 + 点完该在哪个阶段。"""

    box: tuple
    what: str
    stage: str


def find_challenge_box(items):
    """编队页底部【挑战】按钮的框；认不出返回 ``None``。

    判据 = :data:`PAGE_CHALLENGE_PATTERNS`（``^挑战(→)?$`` 的同形快照）—— **整串锚定**，
    绝不放宽成裸「挑战」：``再次挑战`` / ``继续挑战`` / ``挑战深渊连战`` 都是**别的控件**，
    点错就是「再打一局 / 弹确认框」而不是开打（见 ``scene/challenge.py`` 的反例表）。
    """
    patterns = [re.compile(p) for p in PAGE_CHALLENGE_PATTERNS]
    for text, box in items or []:
        stripped = (text or "").strip()
        candidate = _box4_snapshot(box)       # ★Rect / list 都认；解不开就是「没有框」★
        if not stripped or candidate is None:
            continue
        if any(p.search(stripped) for p in patterns):
            return candidate
    return None


def find_row_box(items, row_name, row_regex=None, *, apply_roi=True):
    """列表页里目标行的**行名框**；先逐字、再用 ``row_regex`` 容错（OCR 变体）。

    ★只在「列表行 ROI」内找（本票核心 ①）★：行名**只可能**出现在列表体里。名字出现在
    **标题 / 横幅 / 页签 / 底栏**里是**常态**，按名字找控件而不限定区域就一定会误点 ——
    真机 484 第二轮验收（``debug/lords_accept3.log``）：tier 点完进的是**模式选择页**，
    页顶领主名 ``无猾机兵`` 的框 ``[157, 154, 379, 94]``（中心 **(346.5, 201)**）被当成
    列表行，连点 ``@720(346,201)`` 三次无反应；真正的入口 ``单人游戏`` 在 (170,523)。

    ★越界的同名匹配**一律忽略**（不是报错、也不产生点击）★，并打一行带 ROI 的日志
    （``… 不在列表行 ROI … 内 —— 忽略``），现场能看出「为什么没点它」。

    ``apply_roi``：★缺省 ``True`` = 用真源 :data:`scene.lords_nav.ROW_ROI`
    （安装态 = ``_NavSnapshotLogic.ROW_ROI``）★。``False`` **只给诊断用**
    （:meth:`LordsProgressRecognition._stuck_reason` 要区分「框不在当帧」与「框在屏外」，
    而合成帧的行坐标本来就是合成的）——**所有点击路径一律用缺省值**。

    取不到导航真源（真源与快照都不在）时不做 ROI 过滤：那时整条导航链都不命中，本函数也
    不会被用来点击（不假成功）。
    """
    navl = _nav()
    checker = (
        getattr(navl, "row_roi_hit", None)
        if (navl is not None and apply_roi)
        else None
    )
    roi = getattr(navl, "ROW_ROI", ()) if checker is not None else ()
    fuzzy = None
    ignored = []
    compiled = re.compile(row_regex) if row_regex else None
    for text, box in items or []:
        stripped = (text or "").strip()
        candidate = _box4_snapshot(box)       # ★Rect / list 都认；解不开就是「没有框」★
        if not stripped or candidate is None:
            continue
        is_name = stripped == row_name or (
            compiled is not None and compiled.search(stripped)
        )
        if checker is not None and not checker(candidate):
            if is_name:
                ignored.append((stripped, candidate))
            continue                          # ★越界：标题/横幅/页签/底栏，绝不据此点击★
        if stripped == row_name:
            return candidate                  # 逐字命中优先（容错正则只作兜底）
        if fuzzy is None and compiled is not None and compiled.search(stripped):
            fuzzy = candidate
    if ignored:
        text, box = ignored[0]
        print(
            f"[lords] 行名「{text}」的框 {list(box)} 不在列表行 ROI {list(roi)} 内 —— "
            f"忽略（标题/横幅/页签/底栏不是列表行，绝不据此点击）",
            flush=True,
        )
    return fuzzy


def pick_click(items, target, *, row_regex=None, detail=None):
    """**该点哪里**：把当前帧的 OCR 项 + 本轮目标 → :class:`ClickStep`（或 ``None``）。

    三跳，顺序即页面优先级：

    1. **编队页**：认得出【挑战】就点它（``what=challenge``，``stage=fight``）——
       这一下点下去战斗就开始了，控制权随外交回 pipeline；
    2. **详情页**（判据 ``推荐编成``）：★先读**每一档**的状态，再点**未通关**那一档的【战斗】★
       （``what=tier``，``stage=team``）。★绝不按位置选★：旧实现「``difficulty=None`` ⇒ 取最上面
       那个战斗框（假设未通关的 NEW 永远最上）」已被真机 484 证伪 —— 地狱级已 ``COMPLETE!!``
       却仍在最上，于是第 4/5/6 场全在重打已通关的档（``debug/lords_accept4.log`` 17:19–17:40）。
       选档判据 = ``scene.lords_nav.pick_uncleared_tier``（``COMPLETE!!`` / ``NEW`` 徽标 +
       档名几何配对）；**一档状态都读不到 ⇒ 返回 None（不盲点）**。
       全档 ``COMPLETE!!`` ⇒ 产出【返回】步（``what=back``）回列表重读，而不是随便挑一档；
    3. **列表页**：点目标行的行名框（``what=row``，``stage=detail``）。

    认不出任何一处 → ``None``（★绝不盲点★：宁可这轮空着让看门狗/场次上限收工，
    也不点一个没验证过的坐标）。

    ``detail`` 可注入（默认取 ``agent.side_impl``）—— 离线测试用假实现，
    真机用 #35/#62 真机修正过的那一份。
    """
    # ① 编队页【挑战】
    box = find_challenge_box(items)
    if box is not None:
        return ClickStep(box, WHAT_CHALLENGE, STAGE_FIGHT)

    if detail is None:
        detail = _detail()

    # ② 详情页：先读逐档状态，再点**未通关**那一档的【战斗】
    if detail is not None and detail.on_detail_page(list(items)):
        difficulty = getattr(target, "difficulty", None)
        choice = _detail_tier_choice(items, difficulty)
        if choice is None:
            print(
                "[lords] 详情页档状态读不出（导航真源与安装态快照都不在）—— 本圈不点任何档"
                "（绝不回到「取最上面那个战斗框」的旧行为）",
                flush=True,
            )
            return None
        print(
            f"[lords] 详情页档状态：{choice.summary()} ⇒ "
            + (
                f"选「{choice.difficulty}」（{choice.reason}）"
                if getattr(choice, "picked", False)
                else f"不点任何档（{choice.reason}）"
            ),
            flush=True,
        )
        if not getattr(choice, "picked", False):
            # ★全档 COMPLETE!! ⇒ 回列表（D6：回列表重读 通关数、关本轮）★
            # ★读不到状态 ⇒ 什么都不点（绝不猜；死线兜底）★
            back = _detail_back(items)
            if back is not None and choice.status == _DETAIL_PICK_ALL_COMPLETE_SNAPSHOT:
                print(
                    "[lords] 本行可见档已全 COMPLETE!! → 点【返回】回列表重读 `通关数 N/M`"
                    "（关本轮；不再挑一档重打）",
                    flush=True,
                )
                return ClickStep(back, WHAT_BACK, STAGE_LIST)
            return None
        pattern = re.escape(choice.difficulty) + "$"
        # ★注意返回的是 ``(box, detail)`` 二元组★（#35/#49/#54 的接口），不是裸框。
        picked = detail.pick_target_battle_box(list(items), pattern)
        box = picked[0] if isinstance(picked, tuple) else picked
        quad = _box4_snapshot(box)            # ★Rect / list 都认★
        if quad is None:
            print(
                f"[lords] 详情页选出了「{choice.difficulty}」，但配不到它那一行的【战斗】"
                f"（{choice.reason}）—— 本圈不点（等下一帧），绝不换一档/盲点",
                flush=True,
            )
            return None
        return ClickStep(quad, WHAT_TIER, STAGE_TEAM)

    # ③ 列表页：目标行
    box = find_row_box(items, getattr(target, "row_name", ""), row_regex)
    if box is None:
        return None
    return ClickStep(box, WHAT_ROW, STAGE_DETAIL)


def _no_hit(reason: str, **extra):
    """不命中（``box=None``）+ 说清为什么。"""
    detail = {"reason": reason}
    detail.update(extra)
    return CustomRecognition.AnalyzeResult(box=None, detail=detail)


def _hit_box_zero(**detail):
    """命中但**没有要点的框**（``box=[0,0,0,0]``）—— 与 ``side_impl.StageAllDoneRecognition``
    同一手法：节点要命中才能继续走它自己的 ``next``，但这一轮不点任何东西。"""
    return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)


def _override_next(context, node_name, next_nodes) -> bool:
    """把当前节点的 ``next`` 改写成 ``next_nodes``（收工/换出口用）。失败只打印，不抛。"""
    try:
        context.override_next(node_name, list(next_nodes))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[lords] override_next({node_name!r}) 失败：{exc!r}")
        return False


def _drop_badge_rows(rows, *, items=None, session=None, where=""):
    """「行名其实是**徽标**」的读数：**先把真名找回来**，找不回来才整行剔掉。

    ★真机 484 accept7（2026-10-18 夜，领主战每轮扫描累计被剔 **41–46 行**）★::

        [lords] 行名过滤（page）：4 行的行名读成了徽标 ['COMPLETE!!', ...]
        [lords] 页读「领主战」：本帧 1 行（新 1 / 重复 0，累计 1）

    ★病因是**配对**，不是 OCR 没读到★（帧见 ``screenshots/accept6_lords_list_bottom_MM.png``，
    720 空间 OCR 原值，行距 144px）::

        行 k 的徽标  COMPLETE!!             [13,735,127,27]   ← 在**自己**行名上方 ≈52px
        行 k 的行名  不死王瑞西塔尔讨伐      [203,787,245,28]  ← 真名读出来了
        行 k 的通关数 通关数4/4             [547,833,126,28]

    对**行 k-1** 的通关数 [547,689,126,28]（中心 610,703）来说：

      * 行 k-1 的真名 废墟守卫·火讨伐 [203,641,197,28]（中心 301.5,655）⇒ dy = **48**
      * 行 k 的徽标   COMPLETE!!      [13,735,127,27]（中心 76.5,748.5）⇒ dy = **45.5**
      * ⇒ 徽标以 **2.5px** 之差胜出，被 ``group_progress_rows`` 挂成了行 k-1 的**行名**

    整屏全 M/M 时每张卡的徽标都抢走**上一行**的进度 ⇒ 真机就是「本帧 1 行 + 4 行被徽标剔除」。

    ⇒ 修法分两步（本函数）：
      1. **修复行名**（首选）：用 :func:`scene.lords_nav.recover_badge_row_name` 从当帧 OCR 里
         把这一行**真正的行名框**按几何找回来（排除徽标/进度/页签/固定元素）⇒ 这一行照常参与
         规划 / 全通判定 / 新解锁（真名有了，``通关数 N/M`` 就不会挂错人）；
      2. **整行不读**（兜底）：排除徽标后**仍找不到真名** ⇒ 这个 ``通关数 N/M`` 属于谁无从判断，
         宁可这一行不读，也不产生假行名（拿它规划 = 打错档，拿它记「新解锁」= 假进展）。

    ★安全线不松★：只要能找回来的行都找回；找不回来的行仍进 ``dropped``，调用方据此
    **不许宣布「全部解禁」**（``all_done`` 要求 ``dropped`` 与 ``dropped_in_scan`` 都为空）。

    ``items``：这一帧的 OCR 项（行名修复的候选来源；不给就只做过滤，不能修）。
    返回 ``(kept, dropped, recovered)``：``kept`` 过滤/修复后的行读数（顺序不变）；
    ``dropped`` = ``[(假行名, N, M), ...]``（★必须写进 detail/日志，绝不静默丢★）；
    ``recovered`` = ``[(假行名, 真行名, N, M), ...]``（同样进 detail/日志，现场能复核）。
    传了 ``session`` 时把**找不回来**的假行名记账到 :attr:`Session.badge_dropped`。
    """
    navl = _nav()
    judge = getattr(navl, "is_badge_text", None) if navl is not None else None
    if judge is None:                       # 真源与快照都不在：用冻结判据（与真源逐字相同）
        judge = _IS_BADGE_TEXT_SNAPSHOT
    recover = getattr(navl, "recover_badge_row_name", None) if navl is not None else None
    if recover is None:                     # 安装态：冻结副本（与真源逐字相同）
        recover = _RECOVER_BADGE_ROW_NAME_SNAPSHOT
    kept: list = []
    dropped: list = []
    recovered: list = []
    for row in rows or ():
        name = str(getattr(row, "name", "") or "").strip()
        if name and judge(name):
            found = None
            if items:
                try:
                    found = recover(items, getattr(row, "progress_box", None))
                except Exception as exc:    # noqa: BLE001 - 修复失败只许退回「整行不读」
                    print(f"[lords] 行名修复失败（{where}）：{exc!r} —— 这一行按整行不读处理")
                    found = None
            if found is not None:
                true_name, true_box = found
                try:
                    row = replace(row, name=true_name, name_box=true_box)
                except (TypeError, ValueError):   # 不是 dataclass（离线注入的裸读数）：退回剔行
                    row = None
                if row is not None:
                    recovered.append(
                        (name, true_name, int(getattr(row, "n", 0)), int(getattr(row, "m", 0)))
                    )
                    kept.append(row)
                    continue
            dropped.append((name, int(getattr(row, "n", 0)), int(getattr(row, "m", 0))))
            continue
        kept.append(row)
    if recovered:
        print(
            f"[lords] 行名修复{('（' + where + '）') if where else ''}：{len(recovered)} 行的行名"
            f"读成了徽标，已按几何还原成真名 "
            f"{[(old, new) for old, new, _n, _m in recovered]}"
            f"（徽标属于下一张卡、比本卡真名更贴近进度；真名 = 列表体里最近的非徽标行名框）"
        )
    if dropped:
        if session is not None:
            for name, _n, _m in dropped:
                if name not in session.badge_dropped:   # 同一假行名每帧都会读到：只记一次
                    session.badge_dropped.append(name)
        print(
            f"[lords] 行名过滤{('（' + where + '）') if where else ''}：{len(dropped)} 行的行名"
            f"读成了徽标 {[name for name, _n, _m in dropped]} —— 这些行**连真名都找不到**，"
            f"整行不读（宁可这一行不读，也不产生假行名；徽标词表见 "
            f"scene.lords_nav.LIST_BADGE_MARKS）"
        )
    return (kept, dropped, recovered)


def _rows_detail(rows):
    """行读数 -> 可序列化的 detail（★每行都带 name/n/m/box★，便于日志与现场复核）。"""
    out = []
    for row in rows:
        out.append(
            {
                "name": row.name,
                "n": row.n,
                "m": row.m,
                "name_box": list(row.name_box),
                "progress_box": list(row.progress_box),
            }
        )
    return out


def _target_row(session):
    """本轮第一个目标的**行名**（页签由它决定，#19）；还没目标返回 ``None``。"""
    if not session.targets:
        return None
    return getattr(session.targets[0], "row_name", None)


#: 合成帧的行距（720 空间）= 真机行距 144px（``scene/lord_battle.py``「行高约 144px」）。
SYNTH_ROW_PITCH = 144
#: 合成帧的行名起点 y（720 空间）—— **不是屏幕位置**，只为了让几何分组一一对应。
SYNTH_TOP_Y = 460
#: 行名与 ``通关数`` 的纵向错位（= 真机版式 48px，见 ``scene.lords_unlock.MAX_NAME_DY``）。
SYNTH_PROGRESS_DY = 48


def _synthesize_items(rows):
    """把**累计读数**还原成一帧「合成 OCR 项」，交给既有的 ``_read`` 判一轮。

    ★为什么要合成★：一轮的「全部解禁」判定必须落在**两个页签都滚到底**之后的读数上；
    而 ``mode=read`` 只看得见当前这一帧（滚到底时只剩最后几行）—— 直接在列表底部判
    ``all_done`` 会把「末屏恰好都 M/M」当成「全部解禁」（假收工）。

    ★为什么不复制 ``_read`` 的规划逻辑★：``_read`` 是 #100 已经真机校准过的那一条
    （plan → 关轮 → 死线 → 三条终结 → override_next 到 ``LordsStop``）。本函数把累计读数
    还原成它认得的输入，**一行判定代码都不重写**。

    ★坐标是合成的★（``SYNTH_TOP_Y`` 起、行距 144px）：真实坐标在 ``detail.rows`` 里；
    这里只需要让 :func:`scene.lords_unlock.group_progress_rows` 的几何分组**一一对应**。
    调用方必须先用它跑一次 ``group_progress_rows`` 并核对读数**逐项复原**（对不上就不规划）。
    """
    items = []
    for index, row in enumerate(rows):
        y = SYNTH_TOP_Y + index * SYNTH_ROW_PITCH
        items.append((row.name, [202, y, 197, 28]))
        items.append((f"通关数{row.n}/{row.m}", [547, y + SYNTH_PROGRESS_DY, 127, 28]))
    return items


# ---------------------------------------------------------------------------
# custom_recognition = "lords_progress"
# ---------------------------------------------------------------------------
class LordsProgressRecognition(CustomRecognition):
    """读列表页 ``通关数 N/M``（``mode=read``）或选出下一处该点的框（``mode=pick``）。

    可用参数（``custom_recognition_param``）：

    * ``mode``：``"read"``（缺省）/ ``"pick"``；
    * ``ocr_entry``：借用的 OCR 节点名，缺省 ``OcrTask``。

    ``mode=read`` 的 detail（结构化的行列表，★每行带 name/n/m/box★）::

        {"round": 0, "all_done": false, "stop": false, "reason": "",
         "rows": [{"name": "艾基尔·嫉妒讨伐", "n": 1, "m": 4,
                   "name_box": [...], "progress_box": [...]}, ...],
         "targets": [["艾基尔·嫉妒讨伐", null]], "problems": [...], "orphans": [...]}

    ``mode=pick`` 的 detail：``{"what": "row|tier|challenge", "stage": ...,
    "row": 行名, "difficulty": 档位}``。

    ``mode=solo`` 的 detail（#100 第 4 个真机缺口）：``{"mode": "solo", "state": "lords_mode",
    "solo": [x,y,w,h], "multi": [...], "mode_page": true, "what": "mode", "box": [...]}``。
    """

    def analyze(self, context, argv) -> CustomRecognition.AnalyzeResult:  # noqa: D102
        param = read_param(argv)
        mode = str(param.get("mode") or MODE_READ)
        ocr_entry = param.get("ocr_entry") or DEFAULT_OCR_ENTRY

        logic = _logic()
        if logic is None:
            return _no_hit(INSTALL_STATE_REASON)

        items = _ocr_hook(context, argv.image, ocr_entry)
        session = _session(getattr(argv.task_detail, "task_id", None))

        # ★闩的主路径（每一帧、每个 mode 都先问一次证据）★：点过【挑战】之后，只要这一帧
        # **正向认出**了 battle/settle（或列表/详情/主城/模式页），就说明那一下已经生效、人已经
        # 离开编队页 ⇒ **当场**放开闩并把 `last_click_at` 拨到现在。
        # 真机 484 第 3 轮验收（`debug/lords_accept4.log` 17:26–17:33）：战斗/结算实际发生了
        # （`trace13: state=wuchong_settle`），旧实现却只在 180s 超时时放 ⇒ 每场白等 ~182s。
        # ★不放在某一个 mode 里★：hub 里 LordsSwitchTab 排在 LordsPickTarget 之前，只挂在 pick
        # 上就晚一拍；而且任何一帧都可能是「战斗已经开打」的证据。180s 兜底仍在
        # （`_release_challenge_latch`，由 pick 每圈调一次）。
        # （`_release_challenge_latch_on_evidence` 自己先看 challenge_pending，没闩时零成本返回。）
        self._release_challenge_latch_on_evidence(session, items)

        # ★本票 ②（D6 关轮）★：见到战斗/结算 ⇒ 记「这一场打完了、回列表要重读 `通关数 N/M`」。
        # ★与放闩分开★：放闩管「别再点第二次挑战」，这条管「回合怎么关、别拿旧目标重打」；
        # 两者都在**每一帧**判，因为战斗可能打几分钟、任何一帧都可能是这一局的证据。
        _note_after_fight(session, items)

        if mode in (MODE_PAGE, MODE_TAB, MODE_SCROLL, MODE_END, MODE_SOLO, MODE_TOP):
            navl = _nav()
            nav = _nav_state(session)
            if navl is None or nav is None:
                return _no_hit(NAV_INSTALL_STATE_REASON)
            if mode == MODE_TOP:
                return self._top(items, context, argv, session, logic, navl, nav)
            if mode == MODE_PAGE:
                return self._page(items, session, logic, navl, nav)
            if mode == MODE_TAB:
                return self._tab(items, context, argv, session, navl, nav)
            if mode == MODE_SCROLL:
                return self._scroll(items, context, argv, session, navl, nav)
            if mode == MODE_SOLO:
                return self._mode(items, context, argv, session, navl, nav)
            return self._end(items, context, argv, session, logic, navl, nav)

        if mode == MODE_PICK:
            return self._pick(items, context, argv, session)
        return self._read(items, context, argv, session, logic)

    # -- mode=read ---------------------------------------------------------
    def _read(self, items, context, argv, session, logic, *, synthesized: bool = False):
        """``mode=read``：按**这一帧**规划本轮目标，并在轮次边界判收工。

        ``synthesized=True`` 只有 :meth:`_end` 用：它喂的是**两个页签扫完后合成的一帧**
        （没有「更新列表」/页签标签），此时扫描闸已经由 ``mode=end`` 走完了 —— 不能再按
        「本帧页签未确认」把它拦掉。

        ★#100 回归（解禁 0 场）★：合成帧**不是真实屏幕** —— 它的行 y 是
        ``SYNTH_TOP_Y + k*144``（第 7 行起 > 1280），拿它求值「点不出去」死线必然误判。
        所以这里做两件事：① 合成帧**不判**死线（死线只许在真实抓帧上求值）；
        ② 把死线基准拨到**现在**（扫描结束 → pick 阶段从这里起算）。
        """
        if synthesized:
            # ★扫描 → pick 的交接点★：扫描两个页签的几十秒是**导航**，不是「点目标」。
            # 真机现场（debug/lords_accept.log）：扫完 52s，pick 一起步就背着 52s 被判死。
            session.last_click_at = _now()
        else:
            gate = self._scan_gate(items, session)
            if gate:
                return _no_hit(gate, mode=MODE_READ, gate="scan")
        rows, orphans = logic.group_progress_rows(items)
        # ★徽标不是行名★（真机 484 第 5 轮验收）：**先用几何把真名找回来**，找不回来才整行不读
        #   （真机 accept7：领主战每轮累计被剔 41–46 行 —— 真名其实就在帧里，错的是配对）。
        # 位置必须在 `plan_round` 之前：假行名一旦进规划，目标集合与「新解锁」都会被污染。
        rows, badge_dropped, badge_recovered = _drop_badge_rows(
            rows, items=items, session=session, where="read"
        )
        if not rows:
            if badge_dropped:
                return _no_hit(
                    "这一帧的行名全被徽标过滤掉了（"
                    f"{[name for name, _n, _m in badge_dropped]}）—— 不规划、不点、不收工"
                    "（宁可这一行不读，也不产生假行名）",
                    dropped=[[name, n, m] for name, n, m in badge_dropped],
                    orphans=[[text, list(box)] for text, box in orphans],
                )
            return _no_hit(
                "这一帧读不到任何 `通关数 N/M`（不像是领主战列表页）",
                orphans=[[text, list(box)] for text, box in orphans],
            )

        try:
            plan = logic.plan_round(rows, _registry())
        except logic.LordsDataError as exc:
            # ★脏数据不静默处置★：不点、不规划，把原因写进 detail 让日志能看见；
            # 停在原地会让 stall 看门狗/场次上限兜底，绝不按错的读数去打。
            print(f"[lords] 列表页读数脏，本轮不规划：{exc}")
            return _no_hit(f"列表页读数脏，本轮不规划：{exc}", rows=_rows_detail(rows))

        closed = self._close_round_if_needed(session, rows, logic)
        # ★D6 关轮到此完成★：这一刻手里是**回到列表后重读**的 `通关数 N/M`（不是战前那一份），
        # 关轮与重新 plan_round 都已做完 ⇒ 后面的 pick/scroll/page 可以重新干活。
        # ★必须放在 `closed` 之后★：读脏（上面早退）时不能解锁，否则又回到「没重读就点」。
        session.back_to_list_pending = False
        if closed:
            # ★进入新一轮 = pick 阶段重新起算★：上一轮的点击早就过去了（中间隔着战斗 / 结算），
            # 那段「幽灵时间」不许算成「点不出去」。
            session.last_click_at = _now()
        nav = _nav_state(session)
        # ★本票 ①②（真机 484 第 7 轮验收）★：**关轮只认整轮扫描帧** ——
        #   `round_gained` / `prev_cleared` 只在 `mode=end` 交给这里的**合成帧**（两个页签
        #   从顶部扫到底的累计读数）上判。战后停在目标行位置的那一帧**不是**完整扫描产出：
        #     · 它不更新 ``prev_cleared``（否则基线被 1 行/几行的局部读数覆盖，下一次比什么都错）；
        #     · 它不判 ``round_gained``（被徽标剔掉的行很可能正是 ``N<M`` 的那一行 ⇒ 漏判进展）；
        #   现场（``debug/lords_accept7.log``，L1054–L1055 / L1210–L1212）：第 7、8 场都真打了，
        #   但关轮那帧「3 行读成徽标、只剩 1 行」⇒ 新解锁=无 ×2 ⇒ 19:52 假收工（余下 25 分钟空转）。
        # ★本票 ②：有行被徽标剔除的扫描帧只允许「无法判断」★—— 绝不据此累加 no_progress。
        gain = self._settle_round_gain(
            session,
            rows,
            logic,
            complete_scan=self._is_full_scan_frame(nav, synthesized),
            scan_incomplete=(nav.scan_incomplete_reason() if nav is not None else ""),
            dropped=len(badge_dropped),
        )
        session.challenge_pending = False
        # ★本票 ③（防过度放宽）★：整轮扫描真的判出「没有新解锁」时，要在**判完这一刻**就检查
        #   兜底 —— 关轮那一帧已经不判进展，等它 = 永远等不到「连续 2 轮」。
        if gain == "flat":
            idle_limit = int(getattr(logic, "IDLE_ROUND_LIMIT", 2) or 2)
            if session.no_progress_rounds >= idle_limit:
                state = logic.UnlockState(
                    all_done=False,
                    rows_read=len(rows),
                    planned=0,
                    played=max(1, int(session.played_this_round)),
                    sessions=session.sessions_played,
                    no_progress_rounds=session.no_progress_rounds,
                )
                terminal, terminal_reason = logic.should_stop(state)
                if terminal:
                    session.last_reason = terminal_reason
                    print(f"[lords] 收工：{terminal_reason}")
                    session.stop_requested = True
                    _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
                    return _hit_box_zero(
                        round=session.round_index,
                        rows=_rows_detail(rows),
                        gate="round_gain",
                        round_gain=gain,
                        no_progress_rounds=int(session.no_progress_rounds),
                        stop=True,
                        reason=terminal_reason,
                    )

        # ★本票 e：arm sweep 必须在 plan 之前 —— 关轮后**不许拿这一帧（单帧）读数点目标**★
        #   真机 484 第 6 轮验收（``debug/lords_accept6.log``）::
        #
        #       L133 第 1 轮结束 → L134 单帧读 2 行 → 1 目标（妖狐 高级+）
        #       → L135 点 row → L136 「第 1 轮开始：扫描重新武装」
        #
        #   ⇒ 第 1 轮**压根没扫**（用单帧 2 行做计划就点了）。这里把这一帧的规划**作废**
        #   （plan 只当读数校验用，不落地成 targets），把这一圈交回枢纽：由 `LordsSwitchTab`
        #   的 `_ensure_round` 先 arm sweep（打「第 N 轮开始」），再回顶部 + 扫两个页签，
        #   最后 `mode=end` 把**整轮**读数交给 `mode=read(synthesized=True)` 才允许规划。
        #   ★``scanning_due`` 是第二条入口★：``mode=end`` 的交接里可能顺手关轮，此时
        #   ``complete_scan`` 记的是**被扫的那一轮** ⇒ 下一轮 ``page_pending`` 为真、
        #   ``sweep_done`` 仍为真（= 还没 arm）—— 同一帧也不许再规划。
        scanning_due = bool(
            nav is not None and nav.page_pending(session.round_index) and nav.sweep_done
        )
        if (closed or scanning_due) and not synthesized:
            session.targets = []
            session.stage = STAGE_LIST
            # ★终局判定不能等到扫完★：场次上限 / 连续 N 轮无新解锁**与扫描完整性无关**，
            #   它们必须在关轮这一刻就能成立（否则会先白扫一整轮才收工）。这里给 should_stop
            #   的输入做了两处**故意**的钉死：
            #     · ``all_done=False`` —— 这一帧只是列表的一角，不许拿它判「全部解禁」；
            #     · ``planned=0 / played=max(1, played)`` —— 单帧 plan 已作废（不落地目标），
            #       防死循环那两条（零目标 / 计划了没打）不能在「扫描还没做」时误触发。
            state = logic.UnlockState(
                all_done=False,
                rows_read=len(rows),
                planned=0,
                played=max(1, int(session.played_this_round)),
                sessions=session.sessions_played,
                no_progress_rounds=session.no_progress_rounds,
            )
            terminal, terminal_reason = logic.should_stop(state)
            if terminal:
                session.last_reason = terminal_reason
                print(f"[lords] 收工：{terminal_reason}")
                session.stop_requested = True
                _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
                return _hit_box_zero(
                    round=session.round_index,
                    rows=_rows_detail(rows),
                    gate="scan_due",
                    stop=True,
                    reason=terminal_reason,
                    stop_before_scan=True,
                    round_gain=gain,
                    dropped=[[name, n, m] for name, n, m in badge_dropped],
                    recovered=[[old, new, n, m] for old, new, n, m in badge_recovered],
                )
            reason = (
                f"第 {session.round_index} 轮已结束（关轮完成）—— 新的一轮必须先把两个页签"
                f"从顶部扫完再规划：这一帧 {len(rows)} 行的 plan 只作读数校验，**不落地目标**"
                f"（arm 在 LordsSwitchTab；不拿单帧读数点目标）"
            )
            print(f"[lords] {reason}")
            return _no_hit(
                reason,
                round=session.round_index,
                rows=_rows_detail(rows),
                plans_discarded=[list(pair) for pair in plan.pairs],
                gate="scan_due",
                synthesized=False,
                round_gain=gain,
                # ★被剔掉的假行名也进 detail★（关轮那一帧正是现场证据：真机 L1054 3 行被剔）
                dropped=[[name, n, m] for name, n, m in badge_dropped],
                recovered=[[old, new, n, m] for old, new, n, m in badge_recovered],
                dropped_in_scan=getattr(nav, "dropped_in_scan", 0) if nav is not None else 0,
            )

        session.targets = list(plan.targets)
        session.stage = STAGE_LIST

        # ★有行**连真名都找不到** ⇒ 不许宣布「全部解禁」★（真机 484 第 5 轮验收）：丢的那一行
        # 可能正是 ``N<M`` 的那一行；把「剩下几行恰好都 M/M」当全通 = 假收工（与「零行 ≠ 全通」
        # 同一条纪律）。★本票 c★：**本轮扫描**里被剔的行也算（``nav.dropped_in_scan``）。
        # ★真机 accept7 修法（本票 A）★：行名被读成徽标时**先按几何找回真名**（``badge_recovered``）
        # —— 找回来的行是**完整读数**，照常参与 ``plan.all_done``；``all_done`` 只被
        # **找不回来**的行（``badge_dropped`` / ``dropped_in_scan``）压住。
        scan_incomplete = nav.scan_incomplete_reason() if nav is not None else ""
        all_done = (
            bool(plan.all_done)
            and not badge_dropped
            and not session.badge_dropped
            and not (nav is not None and nav.dropped_in_scan)
        )
        detail = {
            "round": session.round_index,
            "all_done": all_done,
            "rows": _rows_detail(rows),
            "targets": [list(pair) for pair in plan.pairs],
            "needs_detail": [t.row_name for t in plan.needs_detail],
            "problems": [[p.kind, p.row_name, p.detail] for p in plan.problems],
            "orphans": [[text, list(box)] for text, box in orphans],
            # ★被剔掉的假行名也进 detail★（现场一眼看出「这一行为什么没了」，绝不静默丢）
            "dropped": [[name, n, m] for name, n, m in badge_dropped],
            # ★被**修复**的行名也进 detail★（现场一眼看出「这行的真名是几何找回来的」）
            "recovered": [[old, new, n, m] for old, new, n, m in badge_recovered],
            "recovered_n": len(badge_recovered),
            "dropped_in_scan": getattr(nav, "dropped_in_scan", 0) if nav is not None else 0,
            "scan_incomplete": scan_incomplete,
            "synthesized": bool(synthesized),
            # ★本票 ①② 的判据与账都进 detail★（现场一眼看出「这一帧有没有被判进展」）
            "round_gain": gain,
            "gain_pending": bool(session.gain_pending),
            "gain_undecidable": int(session.gain_undecidable),
            "no_progress_rounds": int(session.no_progress_rounds),
            "stop": False,
            "reason": "",
        }

        # ① 死线：有目标却连续 STUCK_SEC 一次都没点成功 → 带原因收工（照 #62 的有界跳过精神）
        #    第三种原因（行在屏上却点不动）就落在这里；前两种由 mode=pick 的归位当场判。
        #    ★合成帧不参与★：它不是真实屏幕（行 y 是合成坐标，见 _synthesize_items），
        #    不能用来判「实时卡住」—— 死线只许在真实抓帧上求值（#100 回归：解禁 0 场）。
        stuck = "" if synthesized else self._stuck_reason(session, items)
        if stuck:
            session.last_reason = stuck
            print(f"[lords] 收工：{stuck}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail["stop"] = True
            detail["reason"] = stuck
            return _hit_box_zero(**detail)

        # ② 收工判定只在三种时刻做：全通 / 轮次边界（打过一场回来了）/ 本轮零目标。
        # ★第一轮刚读完（还没打）不判★：此时 played=0 是正常的，判了就会当场退。
        if plan.all_done or closed or not plan.targets:
            state = logic.UnlockState(
                all_done=all_done,
                rows_read=len(rows),
                planned=len(plan.targets),
                played=session.played_this_round,
                sessions=session.sessions_played,
                no_progress_rounds=session.no_progress_rounds,
            )
            stop, reason = logic.should_stop(state)
            # ★本票 d：零目标必须**把病因指对**★（真机 484 第 6 轮：空滚 80 次 / 7 分 54 秒，
            #   理由写成「本页已滚 80 次（上限 80）仍未到底」—— 那不是滚动的问题）。只有
            #   **整轮扫描交接过来的完整读数**才允许做这个判决；零目标时：
            #     · 扫描不完整（有行被剔 / 没回顶 / 页签没切）⇒ 点在「扫描不完整」上；
            #     · 扫描完整却没目标（全是不认识的行 / M 冲突）⇒ 点「零目标」，也不许空滚。
            #   ★判据用 ``all_done``（已被徽标剔除压成 False）而不是 ``plan.all_done``★：
            #   「每行都 M/M 但有几行被剔掉」= 零目标 + 扫描不完整，同样必须带原因收工。
            zero_target = synthesized and not plan.targets and not all_done
            if zero_target:
                if scan_incomplete:
                    stop = True
                    reason = ZERO_TARGET_INCOMPLETE_REASON.format(evidence=scan_incomplete)
                else:
                    stop = True
                    reason = (
                        f"防死循环：本轮零目标（完整扫描读到 {len(rows)} 行，"
                        f"但没有一行 N<M 可打）却未判全通 —— 带原因收工"
                    )
            detail["stop"] = bool(stop)
            detail["reason"] = reason
            detail["zero_target"] = bool(not plan.targets)
            detail["zero_target_incomplete"] = bool(zero_target and scan_incomplete)
            if stop:
                session.last_reason = reason
                print(f"[lords] 收工：{reason}")
                session.stop_requested = True
                # ★只有「该收工」才 override 到 LordsStop★（★本票最后一个阻塞点★）：
                # 修前这一行在 `if stop:` **外面**，于是 `stop=False`（`reason=''`、没有「收工：」
                # 那一行）的**关轮**照样把 next 改成 LordsStop —— 真机 484 第 5 轮验收
                # （`debug/lords_accept5.log`，18:13:19–18:13:20）::
                #
                #     18:13:19.240 MaaContextOverrideNext [node_name=LordsReadProgress] [next=["LordsStop"]]
                #     18:13:20.046 LordsStop DirectHit → StopTask
                #     18:13:20.247 need_to_stop [node.name=LordsReadProgress] + task end: entry=LordsEntry
                #
                # ⇒ 第一次关轮就把 `LordsEntry` 任务结束，整轮只打了 1 场（此后 5 分钟零动作）。
                # ★不收工时让 `LordsReadProgress.next` 正常回到 pick / 枢纽★（= 继续下一轮）：
                # 那一条 next = [PubLoadingWait, PubDailyPopup, LordsPickTarget, LordsEntry]。
                _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])

        if not detail["stop"]:
            print(
                f"[lords] 第 {session.round_index} 轮：读到 {len(rows)} 行，"
                f"本轮目标 {len(plan.targets)} 个={plan.pairs}，"
                f"累计 {session.sessions_played} 场"
            )
        return _hit_box_zero(**detail)

    @staticmethod
    def _scan_gate(items, session) -> str:
        """★扫描闸★（R1/R2 的那条洞）：扫描阶段 + 页签未确认 ⇒ **不按单帧规划**。

        ``LordsReadProgress`` 是枢纽里 **nav 节点全不命中**之后的兜底读法：它只看得见**当前
        这一帧**。扫描阶段（``page_pending`` 为真）页签还没确认到目标页签时，这一帧很可能是
        **错页签的列表**（甚至详情页）—— 按它规划 = 把别的子族的行记进本轮、或把「首屏恰好
        都 M/M」当成「全部解禁」（假收工）。

        所以这里**只说不做**：返回理由串（调用方据此 ``_no_hit``），把控制权交回枢纽，由
        ``LordsSwitchTab`` / ``LordsScanPage`` / ``LordsListEnd`` 继续推进导航。
        不在扫描阶段（``page_pending`` 为假）= 正常读列表，闸不生效。
        """
        navl = _nav()
        nav = _nav_state(session)
        if navl is None or nav is None:
            return ""
        if not nav.page_pending(session.round_index):
            return ""
        registry = _registry()
        # ★扫描期不拿旧目标行定页签★（本票 b）：扫描期该扫哪个页签由 sweep 顺序决定。
        desired = nav.desired_tab(None, registry)
        if desired is None:
            return ""
        evidence = navl.tab_state(items, registry)
        if evidence.confirmed == desired:
            return ""
        return (
            f"扫描阶段（page_pending）且页签未确认到「{desired}」（本帧 confirmed={evidence.confirmed!r}，"
            f"list_page={evidence.list_page}）—— 不按单帧规划（错页签的行会被记进本轮；"
            f"先让 LordsSwitchTab / LordsScanPage 把这一轮扫完）"
        )

    @staticmethod
    def _stuck_reason(session, items=None) -> str:
        """有目标、却连续 :data:`STUCK_SEC` 一次都没点成功 → 返回收工理由（否则 ``""``）。

        ★为什么要它★：``next`` 扫不到任何节点时 MAA 不会自己收工（``lords.json`` 的枢纽会
        自环轮询），而「屏上认不出目标行/战斗/挑战」正是真机 #62 那种「停在自家详情页空转」
        的形态。没有这条死线，一个读不出的成员就能把整趟解禁拖死。
        战斗期间不受它管（``challenge_pending``）—— 一场打完本来就要几十秒。

        ★#100 第 3 条真机缺口★：这条死线**只**负责第三种原因
        （``scene.lords_nav.PICK_REASON_CLICK``：**行在屏上却点不动**）。另外两种
        （目标不在这个页签 / 滚到底也没找到）由 :meth:`_pick_locate` 当场判定并收工 ——
        修前三者混成一句「点不出去」，现场只能猜。

        ★#100 回归（解禁 0 场）★：「找到行框」**不等于**「行在屏上」—— 必须过
        :func:`scene.lords_nav.on_screen` 的整框边界校验（720x1280）。合成帧的
        ``y = SYNTH_TOP_Y + k*144`` 从第 7 行起就越界（k=7 → 1468）；真机在这里说过
        「行就在屏上（行框 [202, 1468, 197, 28]）」，把「扫描读数」当成了「实时卡住」。
        越界一律按「不在屏上」处理（绝不拿一个屏外框冒充可点的行）。
        """
        if not session.targets:
            return ""
        if session.last_click_at <= 0:
            session.last_click_at = _now()      # 第一次进来看时间，不算「卡住」
            return ""
        if session.challenge_pending:            # 战斗/结算中：等待是正常的
            return ""
        idle = _now() - session.last_click_at
        if idle < STUCK_SEC:
            return ""
        row = session.targets[0].row_name
        navl = _nav()
        mark = getattr(navl, "PICK_REASON_CLICK", "找到了但点不动") if navl is not None else "找到了但点不动"
        # ★这里**故意**用 ``apply_roi=False``（不限定列表行 ROI）★：本方法只**诊断**、不点击，
        # 要区分的是「框不在当帧」与「框在屏外」两种形态；而 ``_synthesize_items`` 的行坐标
        # 本来就是合成的（第 6 行起就出了行 ROI）。★所有点击路径一律用缺省 ROI★。
        box = find_row_box(items, row, _row_regex(row), apply_roi=False) if items else None
        # ★「行在屏上」= 整框落在 720x1280 内★（不是「找到了框」）：真源与安装态快照都实现了
        #   ``on_screen``；两条路都拿不到时**保守地**当成不在屏上（宁可不这么说）。
        checker = getattr(navl, "on_screen", None) if navl is not None else None
        on_screen = bool(box is not None and checker is not None and checker(box))
        if on_screen:
            return (
                f"{mark}：目标「{row}」的行就在屏上（行框 {list(box)}），却已经 {idle:.0f}s 点不出去"
                f"（死线 {STUCK_SEC:.0f}s，口径照 #62 的有界跳过）—— 带原因收工"
            )
        if box is not None:
            where = f"行框 {list(box)} 不在屏幕内（合成帧 / 已滚出屏幕"
            if navl is not None:
                where += f"；720 空间只有 {navl.SCREEN_W}x{navl.SCREEN_H}"
            where += "）"
        else:
            where = "行不在当帧（可能刚被滚出屏幕）"
        return (
            f"目标「{row}」已经 {idle:.0f}s 点不出去（{where} —— 行不在屏上；"
            f"死线 {STUCK_SEC:.0f}s，口径照 #62 的有界跳过）—— 带原因收工"
        )

    @staticmethod
    def _is_full_scan_frame(nav, synthesized) -> bool:
        """★这一帧是不是**整轮扫描**的产物★（本票 ① 的判据；真机 484 第 7 轮验收）。

        「完整扫描」= ``mode=end`` 交给 ``mode=read`` 的那一帧：``synthesized=True``（不是真实屏幕，
        而是两个页签**从顶部扫到底**的累计读数）**且** ``NavState.sweep_done``（两个页签都扫完了）。

        ★为什么不能只看「读到了几行」★：战后停在目标行位置的那一帧也能读到 1~3 行，但它只是
        列表的一角 —— 拿它跟「上一轮的全扫读数」比，就是在**用局部观测代表全局**（正是本票的
        假收工：3 行被徽标剔掉、只剩 1 行 ⇒ 漏判第 7/8 场的新解锁）。
        """
        if not synthesized:
            return False
        if nav is None:                      # 没有导航状态就无法确认「整轮」—— 保守地不判
            return False
        return bool(getattr(nav, "sweep_done", False))

    @staticmethod
    def _settle_round_gain(session, rows, logic, *, complete_scan, scan_incomplete="", dropped=0):
        """★判「上一轮有没有新解锁」——只认整轮扫描帧（本票 ①②）★。

        ``complete_scan``：这一帧是不是整轮扫描产出（见 :meth:`_is_full_scan_frame`）。
        ``scan_incomplete``：本轮扫描的完整性证据（``NavState.scan_incomplete_reason()``：
        被徽标剔除 N 行 / 未确认回顶 N 页 / 页签未切换）。
        ``dropped``：这一帧本身被徽标整行剔掉的行数。

        返回值（写进 ``detail.round_gain``，现场/守卫都能看见走了哪条路）：

        * ``"not_scan"``：**不是**整轮扫描产出（战后单帧 / 页内单帧）⇒ **不判、不更新基线**；
        * ``"undecidable"``：整轮扫描帧，但**有行被徽标剔除**（``dropped`` 或 ``scan_incomplete``）
          ⇒ 只允许「无法判断」：被剔的很可能正是 ``N<M`` 的那一行，**绝不累加 no_progress**；
          基线也**不动**（下一次干净扫描再跟最后一次**判过的**基线比）；
        * ``"baseline"``：整轮扫描帧、且没有「已关轮待判」的轮次 ⇒ 只把基线前进到这一帧；
        * ``"gained"`` / ``"flat"``：真判了 —— 有新解锁（``no_progress`` 归零）/ 确实没有
          （此时**才**允许累加 ``no_progress``，本票 ③ 的收工靠它）。
        """
        if not complete_scan:
            return "not_scan"
        blocked = int(dropped or 0)
        evidence = str(scan_incomplete or "")
        if blocked or evidence:
            why = f"这一帧有 {blocked} 行被徽标剔除" if blocked else ""
            if evidence:
                why = (why + " + " if why else "") + f"扫描不完整（{evidence}）"
            if session.gain_pending:
                session.gain_undecidable += 1
                print(
                    f"[lords] 本轮新解锁=无法判断：{why} —— 被剔/漏读的行很可能正是 N<M 的那一行，"
                    f"不累加「连续无新解锁」（保持挂起，等下一次完整扫描），也不动基线"
                )
            else:
                print(
                    f"[lords] 整轮扫描不完整（{why}）—— 不更新新解锁基线，"
                    f"等一次干净的完整扫描再起算"
                )
            return "undecidable"
        if not session.gain_pending:
            session.prev_cleared = {row.name: row.n for row in rows}
            print(
                f"[lords] 整轮扫描基线：{len(rows)} 行（新解锁判定从这里起算；"
                f"只有完整扫描帧才会更新它）"
            )
            return "baseline"
        gained, names = logic.round_gained(session.prev_cleared, rows)
        session.no_progress_rounds = 0 if gained else session.no_progress_rounds + 1
        session.prev_cleared = {row.name: row.n for row in rows}
        session.gain_pending = False
        print(
            f"[lords] 整轮扫描复核：新解锁={list(names) or '无'}，"
            f"连续无新解锁 {session.no_progress_rounds} 轮"
            f"（基线 {len(session.prev_cleared)} 行 / 本帧 {len(rows)} 行）"
        )
        return "gained" if gained else "flat"

    @staticmethod
    def _close_round_if_needed(session, rows, logic) -> bool:
        """回到列表页的这一次读数**是否关闭了一轮**（打过/点过才关）。

        关闭时**只**记两件事：本轮实际打了几场、关了多少轮 —— 以及置位 ``gain_pending``
        （「这一轮有没有新解锁」**还没判**）。★新解锁的判定不在这里★：本方法看到的通常是
        「战后回到列表的那一帧」（局部读数），按它判 = 用局部观测代表全局（本票的假收工）。
        真判在 :meth:`_settle_round_gain`，且只接受**整轮扫描帧**。

        ★不关闭就不动计数★ —— 否则在同一屏上反复读会把轮数刷爆，'连续 2 轮无进展' 会瞬间误触发。
        """
        if session.attempts_since_read <= 0 and session.sessions_played <= session.sessions_at_last_read:
            return False
        # ★本票 ①：不判 round_gained、不动 prev_cleared★ —— 交给下一次整轮扫描（mode=end 的合成帧）。
        session.gain_pending = True
        session.round_index += 1
        session.played_this_round = session.sessions_played - session.sessions_at_last_read
        session.sessions_at_last_read = session.sessions_played
        session.reset_round_counters()
        print(
            f"[lords] 第 {session.round_index} 轮结束：本轮打 {session.played_this_round} 场，"
            f"新解锁=待整轮扫描复核（这一帧不是完整扫描产出），"
            f"连续无新解锁 {session.no_progress_rounds} 轮"
        )
        return True

    # -- mode=pick ---------------------------------------------------------
    def _pick(self, items, context, argv, session):
        """``mode=pick``：**先按页面状态分派，再归位（对页签 + 上下找），最后才点**。

        ★顺序就是优先级（本票核心 ②）★：

        1. ★**模式选择页 / 加成确认框 → 交给模式页那条路**（:meth:`_mode`）★ —— 它的
           ``what=WHAT_MODE`` / ``WHAT_MODE_CONFIRM`` 由已验证过的 ``_mode_click`` 执行
           （轮询读帧 + 点「单人游戏」+ 点确认框「否」）。**绝不允许**掉进 ``pick_click``
           的 row/tier 分支：真机 484 第二轮验收里，模式页**顶部的领主名标题**被当成列表行，
           连点 ``@720(346,201)`` 3 次无反应（真正的入口「单人游戏」在 (170,523)）；
        2. :meth:`_pick_locate` 判「该切页签 / 该滚一次 / 该等页签确认 / 该带原因收工」
           （三种收工原因**各是各的文案**：页签 / 滚到底 / 点不动）；
        3. 只有它说 ``ready``（行在屏上 / 不在列表页）才走原来的三跳
           （行 → 该档【战斗】 → 【挑战】）。

        ★``find_row_box`` 自带列表行 ROI★：即使走到第 3 步，标题/横幅/页签/底栏里的同名文字
        也不会再被当成行（越界忽略 + 日志，见 :func:`find_row_box`）。
        """
        if not session.targets:
            return _no_hit("还没规划出目标（先让 lords_progress mode=read 读一轮列表）")
        target = session.targets[0]
        # ★证据路径已经在 :meth:`analyze` 里按**这一帧**放过了★（见到 battle/settle 即放）；
        # 这里只读结果，另外跑一次 **180s 兜底**（点了没反应的情形）。
        # ★别把闩的释放只挂在这个 mode 上★：那就是旧实现「等 180s」的入口
        # （真机 484 第 3 轮验收：每场白等 ~182s）。
        self._release_challenge_latch(session)
        if session.challenge_pending:
            return _no_hit(
                f"刚点过【挑战】（{_now() - session.challenge_clicked_at:.0f}s 前），这一场还没结束 —— "
                f"先让战斗/结算链跑完，绝不再点一次挑战（禁双击开打）",
                row=target.row_name,
            )
        # ★本票 ②（D6 关轮）★：这一场已经打完（或刚从详情页点了【返回】）——
        #   详情页：**只点【返回】**（不选档、不再开一局）；其它页：这一圈让给 mode=read。
        #   ★为什么需要★：结算落回的是**详情页**；旧链在那里继续按「最上面那个战斗框」开第 N+1 场，
        #   于是第 4/5/6 场全是同一档、`第 N 轮结束` 一行都没有（真机 484 第 3 轮验收）。
        if session.back_to_list_pending:
            state = _page_state(items)
            if state == _LORDS_STATE_DETAIL_SNAPSHOT:
                back = _detail_back(items)
                if back is None:
                    return _no_hit(
                        "这一场打完了、落在详情页，但读不到底部「返回」—— 不盲点"
                        "（绝不按旧目标再开一场；由非列表页死线兜底）",
                        row=target.row_name,
                        state=state,
                    )
                print(
                    "[lords] 这一场已打完（回列表还没重读 通关数）→ 点【返回】回列表关本轮"
                    "（D6：settle → 继续 → detail → 返回 → list）",
                    flush=True,
                )
                session.pending = ClickStep(back, WHAT_BACK, STAGE_LIST)
                return CustomRecognition.AnalyzeResult(
                    box=list(back),
                    detail={
                        "what": WHAT_BACK,
                        "stage": STAGE_LIST,
                        "state": state,
                        "row": target.row_name,
                        "difficulty": getattr(target, "difficulty", None),
                        "box": list(back),
                    },
                )
            return _no_hit(
                "这一场刚打完 / 刚点过【返回】—— 回合还没关闭：这一圈让给 mode=read 重读 "
                "`通关数 N/M`（D6：先关本轮再选新目标，绝不再按旧目标点一次）",
                row=target.row_name,
                state=state,
            )
        # ★① 页面状态分派（mode 必须先于 pick_click）★
        navl = _nav()
        nav = _nav_state(session)
        if _mode_step_state(items, navl):
            state = classify(items)
            print(
                f"[lords] pick 分派：state={state} —— 这是模式选择页（或加成确认框），"
                f"不是列表行；**不走 row/tier 分支** → 交给模式页：点「"
                f"{navl.LORDS_MODE_SOLO}」/ 确认框「{navl.LORDS_MODE_BONUS_DECLINE}」",
                flush=True,
            )
            return self._mode(items, context, argv, session, navl, nav)
        located = self._pick_locate(items, context, argv, session, target)
        if located is not None:
            return located
        step = pick_click(items, target, row_regex=_row_regex(target.row_name))
        if step is None:
            box = find_row_box(items, target.row_name, _row_regex(target.row_name))
            # ★正式诊断（#100 第 9 个真机缺口）★：这一轮为什么不动 —— 每次 pick 空转都算一遍，
            # 但**限流**：状态一变就打；同一原因连续出现时每 ``PICK_DIAG_EVERY`` 轮打一行。
            # 真机卡住时这行就是现场：`state=… 行框=… stage=… attempts=…`。
            try:
                state = classify(items) or "<no-nav>"
            except Exception as exc:  # noqa: BLE001 - 诊断绝不许把识别打崩
                state = f"<err {exc!r}>"
            challenge_box = find_challenge_box(items)
            diag = (
                f"[lords] pick 空转诊断：state={state} 行框={box} 行在屏={box is not None} "
                f"challenge_box={challenge_box} stage={session.stage} "
                f"attempts={session.attempts_since_read} pending={session.pending} "
                f"target={target.row_name!r}"
            )
            if _pick_diag_once(
                session,
                (state, box is not None, challenge_box is not None, session.stage),
                diag,
            ):
                print(diag, flush=True)
            where = f"在屏上（行框 {list(box)}）" if box is not None else "不在当帧"
            return _no_hit(
                f"当前画面认不出可点的那一处：目标行「{target.row_name}」{where} —— "
                f"既不是列表行、也不是该档【战斗】/【挑战】；先不点（绝不盲点），"
                f"由「点不出去」死线 {STUCK_SEC:.0f}s 兜底",
                row=target.row_name,
                difficulty=target.difficulty,
            )
        session.pending = step
        session.stage = step.stage
        return CustomRecognition.AnalyzeResult(
            box=list(step.box),
            detail={
                "what": step.what,
                "stage": step.stage,
                "row": target.row_name,
                "difficulty": target.difficulty,
                "box": list(step.box),
            },
        )

    # -- mode=pick 的前置：归位（先对页签，再上下找）--------------------------
    def _pick_locate(self, items, context, argv, session, target):
        """**点之前先归位**（#100 第 3 条真机缺口）—— 返回 ``None`` = 交给 ``pick_click``。

        返回 ``AnalyzeResult`` 的四种形态（前三种都是**命中**，因为都要动一下）：

        * 页签不对 → ``box=`` 页签标签框，``what=tab``（动作走 ``do=tab`` 那条路：
          **不计**「点了一次目标」、**不消耗**「点不出去」死线）；
        * 目标行不在屏上 → ``box=[0,0,0,0]``，``what=scroll_down`` / ``scroll_up``
          （动作按 :data:`SCROLL_NODE` 的手势滚一次；同样是导航，不是点目标）；
        * 判出失败 → ``override_next(LordsStop)`` 并带**各自的**原因收工（页签切不过去 /
          上下都扫到底 / 滚动手势连续失败 —— 每条各有文案，见 ``scene.lords_nav``）；
        * 页签还没确认 → **不命中**（这一圈什么都不做，页签是导航，不算「点不动」）。

        ★只在「扫描阶段已结束（``page_pending`` 为假）」时接管★：扫描期由
        ``LordsScanPage`` / ``LordsListEnd`` 负责把两个页签读全，这里不许抢（否则会把
        「还没扫完」误当「目标行不在屏上」去滚）。

        ★页签证据不足（``confirmed is None``）时既不切也不猜★（#19：两个标签常驻同屏，
        「读得到标签」不算确认）—— 就地上下找；真找不到会以「滚到底也没找到」收工，
        而不是拿一个猜的页签去点。
        """
        navl = _nav()
        nav = _nav_state(session)
        pick = _pick_nav_state(session)
        if navl is None or nav is None or pick is None:
            return None                        # 没有导航真源 → 退回老的「只点不找」
        if nav.page_pending(session.round_index):
            return None                        # 扫描期归 LordsScanPage / LordsListEnd 管
        registry = _registry()
        row_name = getattr(target, "row_name", None)
        desired = nav.desired_tab(row_name, registry)
        if desired is None:
            return None                        # 行不在花名册 → 页签不可判，不猜
        now = _now()
        pick.begin_target(row_name, desired)

        list_page = navl.list_page_present(items)
        visible = find_row_box(items, row_name, _row_regex(row_name)) is not None
        evidence = navl.tab_state(items, registry)
        tab_decision = None
        if list_page and not visible and evidence.confirmed is not None:
            anchor = navl.TAB_ANCHORS.get(desired)
            label = navl.label_box(items, anchor) if anchor is not None else None
            tab_decision = nav.switch_decision(evidence, desired, label, now)
        rows, _orphans = (_logic().group_progress_rows(items) if _logic() is not None else ((), ()))
        # ★徽标不是行名★：pick 归位只看得到这一帧，假行名会让它以为「列表里有别的行」。
        # ★先修复行名★（accept7：真名就在帧里）—— 修不回来的才剔掉。
        rows, _badge, _recovered = _drop_badge_rows(
            rows, items=items, session=session, where="pick"
        )
        decision = pick.decide(
            rows,
            evidence=evidence,
            desired=desired,
            tab_decision=tab_decision,
            target_visible=visible,
            list_page=list_page,
            now=now,
        )
        detail = {
            "mode": MODE_PICK,
            "locate": decision.action,
            "tab": desired,
            "confirmed": evidence.confirmed,
            "kinds": list(evidence.kinds),
            "row": row_name,
            "difficulty": getattr(target, "difficulty", None),
            "target_visible": visible,
            "phase": pick.phase,
            "scrolls": [pick.scrolls_down, pick.scrolls_up],
            "stable": f"{pick.stable_scrolls}/{navl.SCROLL_PLAN.stable_times}",
            "reason": decision.reason,
        }
        if decision.action == navl.PICK_ACTION_READY:
            return None                        # 行在屏上 / 不在列表页 → 老三跳
        if decision.action == navl.PICK_ACTION_WAIT:
            return _no_hit(**detail)           # 这一圈什么都不做（detail 里已带 reason）
        if decision.action == navl.PICK_ACTION_FAIL:
            reason = decision.reason
            session.last_reason = reason
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "fail_kind": decision.kind})
            return _hit_box_zero(**detail)
        if decision.action == navl.PICK_ACTION_TAB:
            box = _box4_snapshot(getattr(tab_decision, "box", None))
            if box is None:
                detail["reason"] = f"页签该切到「{desired}」但拿不到它的标签框 —— 不盲点（等下一帧）"
                return _no_hit(**detail)
            step = ClickStep(box, WHAT_TAB, session.stage)
            session.pending = step
            detail.update({"what": WHAT_TAB, "box": list(step.box)})
            center = _box_center(step.box)        # ★浮点中心；不许对框下标取值（#120）★
            at = f"{center[0]:.0f},{center[1]:.0f}" if center is not None else "?"
            print(
                f"[lords] pick 前先对页签：点「{desired}」@720({at})"
                f"（导航，不计「点了一次目标」，也不消耗「点不出去」死线）"
            )
            return CustomRecognition.AnalyzeResult(box=list(step.box), detail=detail)
        # PICK_ACTION_SCROLL：滚一次继续找（方向 = 当前阶段）
        what = WHAT_SCROLL_UP if decision.direction == navl.PICK_SCROLL_UP else WHAT_SCROLL_DOWN
        step = ClickStep((0, 0, 0, 0), what, session.stage)
        session.pending = step
        detail.update({"what": what, "direction": decision.direction})
        print(f"[lords] pick 前先找行：{decision.reason}")
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)

    @staticmethod
    def _release_challenge_latch_on_evidence(session, items=None) -> bool:
        """★闩的**主路径**★：见到「已经离开编队页」的正向证据就**立刻**放（返回是否放了）。

        日志（证据路径）::

            [lords] 点【挑战】后见到 lords_battle（已离开编队页）—— 放闩（证据路径 0.8s；不等 180s 兜底）

        ★为什么需要★（真机 484 第 3 轮验收，``debug/lords_accept4.log``，17:26–17:33）：
        战斗/结算**实际发生了**（``trace13: state=wuchong_settle``），旧实现却只在 180s 超时时
        放闩 ⇒ 每场白等 ~182s（战斗本身才 ~3 分钟），整条解禁循环被拖慢一倍。
        判据在 :func:`scene.lords_nav.challenge_release_evidence`（正向列举 battle/settle 等；
        team / loading / unknown 一律不算证据）。

        ★为什么不合并进 :meth:`_release_challenge_latch`★：那条是**兜底**（点了没反应时要靠它），
        两条路径的触发条件与日志都必须能分开看（真机一眼看出走的是主路径还是兜底）。
        """
        if not session.challenge_pending:
            return False
        state = _challenge_release_state(items)
        if not state:
            return False
        waited = _now() - session.challenge_clicked_at
        session.challenge_pending = False
        session.last_click_at = _now()
        print(
            f"[lords] 点【挑战】后见到 {state}（已离开编队页）—— 放闩"
            f"（证据路径 {waited:.1f}s；不等 {FIGHT_GRACE_SEC:.0f}s 兜底）"
        )
        return True

    @staticmethod
    def _release_challenge_latch(session) -> None:
        """★闩的**兜底**★：超过 :data:`FIGHT_GRACE_SEC` 就当这一场已经结束（日志写「超时」）。

        日志（兜底路径）::

            [lords] 点【挑战】后已等 182s 仍未见战斗/结算 —— 放开闩（180s 超时兜底），重新找目标

        ★为什么兜底必须留着★：点下【挑战】之后画面可能既没进战斗、也没回列表（加载慢 / 体力
        弹窗 / 意外页）。没有这条超时，会话会永久停在 no-hit —— 既不打也不收工。
        ★正常路径不靠它★：见到 battle/settle 由 :meth:`_release_challenge_latch_on_evidence`
        当场放（真机 484 第 3 轮验收：旧实现只靠这条 ⇒ 每场白等 ~182s）。
        """
        if not session.challenge_pending:
            return
        waited = _now() - session.challenge_clicked_at
        if waited >= FIGHT_GRACE_SEC:
            session.challenge_pending = False
            session.last_click_at = _now()
            print(
                f"[lords] 点【挑战】后已等 {waited:.0f}s 仍未见战斗/结算 —— 放开闩"
                f"（{FIGHT_GRACE_SEC:.0f}s 超时兜底），重新找目标"
            )

    # -- mode=page / tab / scroll / end（#100 第 1、2 条真机缺口）-------------
    @staticmethod
    def _nav_stuck(session, nav, items, navl, now) -> str:
        """导航死线：**只在「在列表页、且目标行不在屏上」时**判卡死。

        ★为什么要这么窄★：战斗/详情/编队页上本来就没有任何导航进展，拿死线去判会把
        正常战斗打断。所以只在「明明该导航、却什么都推不动」这一形态下判 ——
        这正是 #50 拦的那种静默空转。
        """
        if session.challenge_pending:            # 点过【挑战】，这一场还没结束
            return ""
        if not navl.list_page_present(items):    # 不在列表页：导航无事可做
            return ""
        target = _target_row(session)
        if target is not None and find_row_box(items, target, _row_regex(target)) is not None:
            return ""                            # 目标行就在屏上 —— 选行那条路还在干活
        return nav.stuck_reason(now)

    def _top(self, items, context, argv, session, logic, navl, nav):
        """``mode=top``：★每页开扫前先回顶部★（有界 + 可验证；#100 第 6 轮真机验收）。

        真机现场（``debug/lords_accept6.log``，18:40–18:47）::

            第 2 轮：领主战 滚 1–6 次 ⇒ 「到底」（本帧 1 行，累计 4）
            两个页签共扫到 4 行 —— 交给 mode=read 判一轮
            第 2 轮：读到 4 行，本轮目标 0 个=()      ← 画面上还有 红嫉机兵 1/4 / 妖狐 3/4

        「到底」是**相对滚动位置**的概念：战后列表停在**被点行**处，不先回顶部，第二轮的
        「到底」毫无意义。本方法：

        1. **只在扫描阶段**、且这一帧是领主战列表页时才动手（不在列表页就交给别的节点）；
           页签证据**只用来排除「明确在另一个页签」**——``confirmed is None`` 不拦回顶部：
           列表底部的行可能是花名册外的活动/联动行（``004_trace04.png`` 最后 5 行就是），
           回顶部是**几何**动作，行族认不出不等于不能把列表滚到顶部；
        2. 判据 = :meth:`NavState.observe_rewind`：连续 ``stable_times`` 个**回顶部世代**都
           「无新行 ∧ 纵向上移位移 ≤ ``no_move_px``」⇒ 已到顶部；
        3. **有界**：最多 ``SCROLL_PLAN.max_rewinds_per_page`` 次；用尽 ⇒
           :data:`REWIND_FAILED_REASON` **带原因收工**（★不是「滚动上限」★）；
        4. 每次上滚都打日志（滚了几次 / 位移 / 是否到顶），detail 里带同样的量 ——
           「已到顶部」必须能从日志复核，而不是一句断言。

        返回形状：命中 ``box=[0,0,0,0]`` = 这一圈上滚一次（动作 ``do=scroll_top``）；
        不命中 = 已到顶部 / 不需要回顶（交给 ``LordsScanPage`` 往下扫）；收工 = 预算用尽。
        """
        now = _now()
        registry = _registry()
        rearmed = _ensure_round(navl, nav, session, now)
        scanning = nav.page_pending(session.round_index)
        evidence = navl.tab_state(items, registry)
        desired = nav.desired_tab(None, registry)
        detail = {
            "mode": MODE_TOP,
            "scanning": scanning,
            "round_rearmed": rearmed,
            "tab": evidence.confirmed,
            "desired_tab": desired,
            "rewind_done": bool(nav.rewind_done),
            "rewind_scrolls": nav.rewind_scrolls,
            "rewind_max": int(navl.SCROLL_PLAN.max_rewinds_per_page),
            "rewind_failed": bool(nav.rewind_failed),
        }
        if not scanning:
            return _no_hit(
                "不在扫描阶段（page_pending 为假）—— 回顶部只在每轮扫描开始前做",
                **detail,
            )
        if not navl.list_page_present(items):
            return _no_hit(
                f"不在领主战列表页（读不到「{navl.LIST_PAGE_ANCHOR}」）—— 回顶部无从谈起", **detail
            )
        if desired is not None and evidence.confirmed is not None and evidence.confirmed != desired:
            return _no_hit(
                f"页签未确认到「{desired}」（当前确认值 {evidence.confirmed!r}）—— "
                f"先切页签再回顶部（在错的页签上回顶部 = 把另一页的滚动位置当这一页的）",
                **detail,
            )
        # ★``confirmed is None`` 不拦回顶部★：列表底部的行可能是花名册外的活动/联动行
        # （真机 484 第 6 轮 ``004_trace04.png`` 的最后 5 行就是 废墟魔像 / 不死王 / 雷霆树妖…），
        # 行族证据认不出 ≠ 不能把列表滚到顶部。回顶部是**几何**动作，只要求「在列表页」。
        if nav.rewind_done:
            return _no_hit(
                f"本页已确认在顶部（上滚 {nav.rewind_scrolls} 次）—— 交给 LordsScanPage 向下扫",
                **detail,
            )
        # ★先判「预算用尽」再判「已完成」★：``rewind_failed`` 时 ``rewind_pending()`` 也是
        # False；若把它当「已完成」就会把失败谎报成成功（本票 d 的反面）。
        if nav.rewind_failed or nav.rewind_budget_exhausted():
            reason = REWIND_FAILED_REASON.format(
                scrolls=nav.rewind_scrolls,
                max=int(navl.SCROLL_PLAN.max_rewinds_per_page),
            )
            session.last_reason = reason
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "reason": reason})
            return _hit_box_zero(**detail)
        # ★兜底：回顶部期间也要有有界出口★（手势节点连续执行失败时 note_rewind_scroll 不会被调用，
        #   没有这条就会在「识别命中 → 动作失败 → on_error 回枢纽」之间无限重来）。
        idle = nav.stuck_reason(now)
        if idle:
            session.last_reason = idle
            print(f"[lords] 收工：{idle}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "reason": idle})
            return _hit_box_zero(**detail)
        rows, _orphans = logic.group_progress_rows(items)
        # ★先修复行名、找不回来才剔★（真机 accept7：每轮 41–46 行、真名其实在帧里）
        rows, badge_dropped, badge_recovered = _drop_badge_rows(
            rows, items=items, session=session, where="top"
        )
        at_top, why = nav.observe_rewind(rows, dropped=len(badge_dropped))
        detail.update(
            {
                "rows": _rows_detail(rows),
                "dropped": [[name, n, m] for name, n, m in badge_dropped],
                "recovered": [[old, new, n, m] for old, new, n, m in badge_recovered],
                "at_top": bool(at_top),
                "rewind_reason": why,
                "rewind_scrolls": nav.rewind_scrolls,
            }
        )
        if at_top:
            print(f"[lords] {why}")
            return _no_hit(f"回顶部完成：{why}", **detail)
        if nav.rewind_budget_exhausted():
            reason = REWIND_FAILED_REASON.format(
                scrolls=nav.rewind_scrolls,
                max=int(navl.SCROLL_PLAN.max_rewinds_per_page),
            )
            session.last_reason = reason
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "reason": reason})
            return _hit_box_zero(**detail)
        allowed, why_scroll = nav.may_rewind(now)
        detail["gate"] = why_scroll
        if not allowed:
            return _no_hit(why_scroll, **detail)
        print(f"[lords] {why_scroll} —— 回顶部中（{why}）")
        return _hit_box_zero(**detail)

    def _page(self, items, session, logic, navl, nav):
        """``mode=page``：读当前页**全部**行（滚动前）→ 去重累计 + 到底判据。

        ★它不改判定★：这里只做「这一页读到什么 / 到底了没有」，规划与收工仍归
        ``mode=read``（:meth:`_read`）与 ``mode=end``（:meth:`_end` 在扫描收尾时把累计
        读数交给 ``_read``）。

        ★D6 关轮期间让路★：``back_to_list_pending`` 为真且已回到列表页时，本节点**不累计**
        —— 先让 ``mode=read`` 把这一轮关掉（否则会在旧目标的页签上重新扫一遍、把旧读数当新轮）。
        ★扫描期例外★：``page_pending`` 为真时让路会**死锁**（read 的扫描闸也不会规划）——
        这时照常扫，扫完 ``_end`` 会把累计读数交给 ``mode=read`` 关轮。
        """
        if not nav.page_pending(session.round_index):
            gate = _back_to_list_gate(session, items)
            if gate:
                return _no_hit(gate, mode=MODE_PAGE, gate="back_to_list")
        now = _now()
        registry = _registry()
        rearmed = _ensure_round(navl, nav, session, now)
        scanning = nav.page_pending(session.round_index)
        # ★扫描期的目标页签 = 扫描顺序，**不是**旧目标行的子族★（真机 484 第 6 轮验收）：
        #   战后的旧目标会把 desired 钉在「领主战」，于是「降临讨伐」那一步**根本没点**
        #   （L187「轮到降临讨伐」之后没有任何 `页签：click`），却照样宣布「两个页签都扫到底」。
        desired = nav.desired_tab(None if scanning else _target_row(session), registry)
        evidence = navl.tab_state(items, registry)
        detail = {
            "mode": MODE_PAGE,
            "tab": evidence.confirmed,
            "labels": sorted(evidence.labels),
            "kinds": list(evidence.kinds),
            "desired_tab": desired,
            "sweep": [nav.sweep_index, list(navl.LORD_TABS)],
            "round_rearmed": rearmed,
        }
        if not nav.page_pending(session.round_index):
            return _no_hit(
                f"页扫描不在这一轮（已扫完 round={nav.sweep_round}，当前 round={session.round_index}）"
                f"—— 交回读列表 / 选行节点",
                **detail,
            )
        if desired is not None and evidence.confirmed != desired:
            return _no_hit(
                f"页签未确认到「{desired}」（当前确认值 {evidence.confirmed!r}）—— 先切页签再读"
                f"（在错的页签上读 = 把别的子族的行记进本轮）",
                **detail,
            )

        rows, orphans = logic.group_progress_rows(items)
        # ★徽标不是行名★：扫描累计里绝不能出现假行名（否则 `classify_kind` 认不出 ⇒ 页签证据
        # 也会被污染）。★先按几何找回真名★（accept7：真名就在帧里，每轮 41–46 行白丢）；
        # 找不回来的才整行不读，并留账（session.badge_dropped ⇒ 本轮不许宣布全通）。
        rows, badge_dropped, badge_recovered = _drop_badge_rows(
            rows, items=items, session=session, where="page"
        )
        anchor = navl.end_anchor_hit(items)
        # ★本票 c★：被徽标剔掉的行**算「见到行」**—— 这一帧不许用来证明「到底」
        #   （真机 484 第 6 轮：每帧都有 4~5 行读成 `COMPLETE!!`，旧实现剔完就判「连续两帧无新行」）。
        at_end, end_reason = nav.observe(rows, anchor_hit=anchor, dropped=len(badge_dropped))
        new_keys, dup_keys = nav.add_rows(rows, now=now)
        detail.update(
            {
                "at_end": at_end,
                "end_reason": end_reason,
                "rows": _rows_detail(rows),
                "orphans": [[text, list(box)] for text, box in orphans],
                "dropped": [[name, n, m] for name, n, m in badge_dropped],
                "dropped_n": len(badge_dropped),
                "recovered": [[old, new, n, m] for old, new, n, m in badge_recovered],
                "recovered_n": len(badge_recovered),
                "dropped_in_scan": nav.dropped_in_scan,
                "bottom_unprovable": bool(nav.bottom_unprovable),
                "page_finished": bool(nav.page_finished()),
                "new": len(new_keys),
                "dup": len(dup_keys),
                "scanned": len(nav.rows()),
                "scrolls_in_page": nav.scrolls_in_page,
            }
        )
        if not rows:
            return _no_hit(
                (
                    "这一帧的行名全被徽标过滤掉了（"
                    f"{[name for name, _n, _m in badge_dropped]}）—— 不累计、不规划"
                )
                if badge_dropped
                else "这一帧读不到任何 `通关数 N/M`（不像是领主战列表页）",
                **detail,
            )
        print(
            f"[lords] 页读「{evidence.confirmed}」：本帧 {len(rows)} 行（新 {len(new_keys)} / 重复 "
            f"{len(dup_keys)}，累计 {len(nav.rows())}），{end_reason}"
        )
        return _hit_box_zero(**detail)

    def _tab(self, items, context, argv, session, navl, nav):
        """``mode=tab``：页签状态 + 该不该切（**含切后确认**；失败只许 1 次）。

        返回形状（判据全在 ``scene/lords_nav.NavState.switch_decision``）：

        * ``click`` → ``box=`` 页签标签框，动作 ``lords_unlock_step{do:tab}`` 点它的中心；
        * ``ok`` → **不命中**（已确认，交给后继节点：读页 / 选行）；
        * ``give_up`` → 命中但 ``override_next`` 回枢纽（**不重试**，#19）；
        * ``stop`` → 命中但 ``override_next`` 到 ``LordsStop`` 并带原因（连续不确认）。
        """
        now = _now()
        registry = _registry()
        rearmed = _ensure_round(navl, nav, session, now)
        # ★扫描期的目标页签 = 扫描顺序，不是旧目标行的子族★（本票 b；真机 484 第 6 轮：
        #   旧目标把 desired 钉在「领主战」⇒ 「降临讨伐」那一步**根本没点**，却宣布两页签扫完）。
        scanning = nav.page_pending(session.round_index)
        state = navl.page_state(items)                    # ★lords 自己的页面状态名★
        # ★#100 第 7 个真机缺口★：模式页换点阶梯全失败 ⇒ 立刻用「4 个点都试过」的原因收工。
        # 必须排在非列表页死线之前：那条只会说「卡在 lords_mode 9s」，症状离病因太远。
        if session.mode_fail_reason:
            reason = session.mode_fail_reason
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            return _hit_box_zero(mode=MODE_TAB, state=state, stop=True, reason=reason)
        # 点过「单人游戏」→ 逐帧**正向复核**（只有编队页才算成功；unknown 不算）
        verify = _note_mode_result(session, state, navl, items)
        if verify:
            print(f"[lords] 模式页复核：点「{navl.LORDS_MODE_SOLO}」后 " + _mode_verify_line(verify))
        evidence = navl.tab_state(items, registry)
        desired = nav.desired_tab(None if scanning else _target_row(session), registry)
        anchor = navl.TAB_ANCHORS.get(desired) if desired else None
        box = navl.label_box(items, anchor) if anchor is not None else None
        decision = nav.switch_decision(evidence, desired, box, now)

        detail = {
            "mode": MODE_TAB,
            "action": decision.action,
            "what": WHAT_TAB,
            "target": decision.target,
            "confirmed": evidence.confirmed,
            "labels": sorted(evidence.labels),
            "kinds": list(evidence.kinds),
            "round_rearmed": rearmed,
            "scanning": scanning,
            "state": state,                                # 现场一眼看出卡在哪个页面
        }
        if verify:
            detail["mode_verify"] = verify
        if decision.box is not None:
            detail["box"] = list(decision.box)
        # ★降噪（#100 第 5 个真机缺口）★：同一 (页面状态, 这一行) 连续命中只打一次 ——
        # 修前在非列表页每帧一行「页签：cannot …」，一分钟几十行把日志淹了。
        line = f"[lords] 页签：{decision.action} / {decision.reason}（state={state}）"
        if _tab_log_once(session, state, line):
            print(line)

        # ★非列表页有界出口（#100 第 5 个真机缺口）★：状态名 K 秒不变 ⇒ 带原因收工。
        # 排在 _nav_stuck 之前：那条只看列表页，非列表页它一句都不说（= 修前的空转）。
        bounded = self._non_list_stuck(session, state, navl, now)
        if bounded:
            session.last_reason = bounded
            print(f"[lords] 收工：{bounded}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "reason": bounded})
            return _hit_box_zero(**detail)

        # ★时间死线★：页签确认不过时，重试是被禁的（#19），有界出口只能是「带原因收工」。
        stuck = self._nav_stuck(session, nav, items, navl, now)
        if stuck and decision.action != navl.ACTION_CLICK:
            print(f"[lords] 收工：{stuck}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "reason": stuck})
            return _hit_box_zero(**detail)

        if decision.action == navl.ACTION_CLICK:
            return CustomRecognition.AnalyzeResult(box=list(decision.box), detail=detail)
        if decision.action == navl.ACTION_STOP:
            # ★扫描期：页签没切换到目标 ⇒ 不许宣布「两个页签都扫到底」★（本票 b；真机 484
            #   第 6 轮：`轮到降临讨伐` 之后一次 `页签：click` 都没有，却照样收尾并给出
            #   「两页签共 4 行 / 目标 0」）。原因必须点名「页签未切换 / 扫描不完整」，
            #   **不是**「目标不在这个页签」（扫描期根本没有目标），更不是「滚动上限」。
            if scanning:
                nav.note_tab_switch_failed()
                reason = TAB_SWITCH_UNCONFIRMED_REASON.format(
                    confirmed=evidence.confirmed if evidence.confirmed is not None else "未确认（None）",
                    desired=decision.target,
                    why=decision.reason,
                )
            else:
                # ★文案与 pick 阶段同一条★（#100 第 3 条真机缺口）：页签切不过去时，人一眼就要能
                # 把「目标不在这个页签」跟「滚到底也没找到」「找到了但点不动」分开。
                reason = self._tab_unreachable_reason(session, decision.reason, navl)
            session.last_reason = reason
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            detail.update({"stop": True, "reason": reason})
            return _hit_box_zero(**detail)
        # ok / give_up / cannot → **不命中**：把这一圈让给后继节点（读页 / 到底 / 选行）。
        # ★give_up 也走这条路★：不 override 回枢纽，是因为枢纽本来就会再扫一遍；
        # 真正的有界出口是时间死线（NAV_STUCK_SEC），不是「一圈没成马上就退」。
        if scanning and decision.action == navl.ACTION_GIVE_UP:
            # 记一笔「本轮页签没切成功」：零目标收工的原因里必须能看出来（本票 d）。
            nav.note_tab_switch_failed()
        return _no_hit(decision.reason, **detail)

    @staticmethod
    def _non_list_stuck(session, state: str, navl, now: float) -> str:
        """★#100 第 5 个真机缺口★ **非列表页 + 状态名 K 秒不变** → 收工理由（否则 ``""``）。

        判据（每一条都为了不误伤）：
        * ``lords_list`` —— 列表页不在本死线管：列表页有自己的 ``NAV_STUCK_SEC``（它认得列表）；
        * ``LORDS_ACTIVE_STATES``（**战斗 / 结算**）—— **整类排除**：这两个页面上「没有导航
          进展」是正常的，一场仗可以打几分钟；★不靠「状态名恰好在变」来排除★（那只是运气）；
        * ★``LORDS_TRANSITION_STATES``（**加载 / 过场**）—— 整类排除**并重置计时**★：
          真机 484（14:5x）``--home`` 把设备送回主城后**立刻**跑 ``--trace LordsEntry``，
          刚回主城那几秒的帧是 loading / 半渲染，旧判据里它们没有名字（= ``lords_unknown``），
          连续 9s 不变 ⇒ **任务还没开始就被判死**（手工 screencap 设备其实好好地在主城）。
          ★只「跳过这一帧」不够★：必须把 ``non_list_state`` 清成 ``None``，让过渡结束后的
          第一帧**从零起算**（否则过渡前攒下的秒数还能凑满死线）；
        * ``challenge_pending`` —— 点过【挑战】、这一场还没结束：同样不许打断；
        * 其余非列表页：**状态名一变就重新计时**；同名持续 ≥ ``NON_LIST_STUCK_SEC`` ⇒ 收工。
          ★``lords_unknown`` 就在这一支里★：未知画面的死线**必须保留**（那是「看起来在跑」
          的兜底）—— 把它也当过渡态放行，认不出的画面就永远没有有界出口了（hooks_122 ② 抓）。

        ★为什么必须按「状态名」而不是「画面」★：画面每帧都在抖（OCR 框、动画、倒计时），
        按画面判会把正常的慢页面判成卡死；状态名是**离散**的，同一名字持续 K 秒才是真的没换页。
        """
        if state == navl.LORDS_STATE_LIST or state in navl.LORDS_ACTIVE_STATES:
            session.non_list_state = None
            session.non_list_since = 0.0
            return ""
        if state in navl.LORDS_TRANSITION_STATES:
            # ★过渡态：不累加，且**重置**计时★（清成 None ⇒ 过渡结束后第一帧重新起算）。
            session.non_list_state = None
            session.non_list_since = 0.0
            return ""
        if session.challenge_pending:
            session.non_list_state = None
            session.non_list_since = 0.0
            return ""
        if session.non_list_state != state:
            session.non_list_state = state
            session.non_list_since = now
            return ""
        idle = now - session.non_list_since
        if idle < navl.NON_LIST_STUCK_SEC:
            return ""
        return navl.non_list_stuck_reason(state, idle)

    @staticmethod
    def _tab_unreachable_reason(session, why: str, navl=None) -> str:
        """页签切不过去 ⇒ 用**三种原因里那一条**（``目标不在这个页签``）的文案。

        为什么两个地方（``mode=tab`` 的收工、``mode=pick`` 的归位）要用同一条：真机上
        ``LordsSwitchTab`` 排在枢纽更前面，页签真的切不过去时**它先收工** —— 若它写的是
        「页签未确认到「x」…」，现场就又回到「症状离病因太远」的老毛病。有目标时一律改成
        点名「目标不在这个页签」；没目标（扫描期）才保留原来的通用文案。
        """
        row = _target_row(session)
        if row is None:
            return why
        navl = _nav() if navl is None else navl
        mark = getattr(navl, "PICK_REASON_TAB", "目标不在这个页签") if navl is not None else "目标不在这个页签"
        return f"{mark}：目标「{row}」所在页签切不过去（{why}）—— 带原因收工（#19：不重试）"

    def _mode(self, items, context, argv, session, navl, nav):
        """``mode=solo``：领主战**模式选择页** → 点「单人游戏」（#100 第 4 个真机缺口）。

        真机现场（484，12:4x）：点完 row → 详情页、点完 tier → 这一页
        （``单人游戏 / 单人挑战领主 / 多人游戏 / 召集同伴挑战领主``），而旧链把它判成
        **别的场景**的状态名 ``wuchong_mode`` ⇒ lords 状态机不认识 ⇒ 卡住。现在：

        1. 判据 = **lords 自己的** :func:`scene.lords_nav.page_state`（状态名 ``lords_mode``）
           + :func:`scene.lords_nav.mode_evidence`（四段文案 + 象限位置 + 单人卡更高）；
        2. 点的是 **``单人游戏`` 自己的当帧 OCR 框中心**（★绝不写死坐标、绝不点
           ``单人挑战领主`` / ``多人游戏``★：后者是共斗房，点错就是开别人的房间）；
        3. **点完有换点阶梯**（#100 第 7 个真机缺口，动作 :meth:`LordsUnlockAction._mode_click`
           执行）：中心 → 下方 100px → 右侧 120px → 下方 180px，**每个点轮询读帧**
           （≤ :data:`LORDS_MODE_POLL_TIMEOUT_SEC`，间隔 :data:`LORDS_MODE_POLL_INTERVAL_SEC`），
           **最多 4 个点**；四个点都试过仍没到编队页 ⇒ ``mode_fail_reason`` 粘住，
           由 ``_tab`` / 本方法立刻 override 到 ``LordsStop``（带读数收工，不让通用死线抢走原因）；
        3b. ★#100 第 9 个真机缺口★：点完「单人游戏」弹出的是**加成点数确认框**
           （「要使用增加报酬的『领主加成点数』吗？」是/否）—— 背景仍是模式页、但「单人游戏」
           被遮住 ⇒ ``page_state`` 只能给 ``lords_unknown``。识别到它（:func:`bonus_dialog`）
           就点**当帧 OCR 框里的「否」**（不消耗每天有限的加成次数；真机实测同样进编队页），
           这条命中形态的 ``what=WHAT_MODE_CONFIRM``，动作只点一下；
        4. **点完复核 = 正向证据**（#100 第 7 个真机缺口）：只有当帧
           :func:`scene.lords_nav.team_page_confirmed`（有【挑战】∧ ``SET`` / ``Party`` /
           ``自动续战`` 至少一个）才算 ``mode_verify=team_page``；瞬时帧 ``lords_unknown``
           **不算成功**（旧判据「离开了模式页」就是这次的假成功）。

        命中的形态：``box = 单人游戏框``（动作执行换点阶梯）；不命中（不点）的形态都写清原因：
        不是模式页 / 证据不完整 / 阶梯已失败（收工）。
        """
        now = _now()
        state = navl.page_state(items)
        # ★四个点都试过仍没到编队页 ⇒ 立刻带量收工★（粘住；不许被通用死线抢先）
        if session.mode_fail_reason:
            reason = session.mode_fail_reason
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            return _hit_box_zero(mode=MODE_SOLO, state=state, stop=True, reason=reason)
        evidence = navl.mode_evidence(items)
        verify = _note_mode_result(session, state, navl, items)
        detail = {
            "mode": MODE_SOLO,
            "state": state,
            "mode_page": bool(evidence.is_mode_page),
            "solo": list(evidence.solo) if evidence.solo is not None else None,
            "solo_note": list(evidence.solo_note) if evidence.solo_note is not None else None,
            "multi": list(evidence.multi) if evidence.multi is not None else None,
            "multi_note": list(evidence.multi_note) if evidence.multi_note is not None else None,
        }
        if verify:
            detail["mode_verify"] = verify
            print(f"[lords] 模式页复核：点「{navl.LORDS_MODE_SOLO}」后 " + _mode_verify_line(verify))
        # ★#100 第 9 个缺口★：点完「单人游戏」后的**加成点数确认框**。
        # 背景仍是模式页，但「单人游戏」被遮住 ⇒ page_state 只能给 lords_unknown。
        # 识别到它就必须**先点「否」**，否则每一轮都只会在遮罩上换点 —— 真机 484（10-18 夜）
        # 的「模式页点不动」就是这么来的（点击其实生效了，只是没人点那个「否」）。
        dialog = navl.bonus_dialog(items)
        if dialog.is_dialog:
            max_dialogs = max(1, int(getattr(navl, "LORDS_MODE_MAX_DIALOG_CLICKS", 1)))
            if session.mode_dialog_clicks >= max_dialogs:
                # ★有界★：同一个确认框不连点（点过还不消失 ⇒ 交给非列表页死线带原因收工）
                return _no_hit(
                    f"「{navl.LORDS_MODE_BONUS_QUESTION_ANCHORS[0]}」确认框已点过 "
                    f"{session.mode_dialog_clicks} 次仍未消失 —— 不连点（由非列表页死线收工）",
                    **detail,
                )
            session.mode_clicks = 0
            session.mode_clicked_at = 0.0
            session.mode_verified = False
            session.mode_fail_reason = ""
            step = ClickStep(dialog.decline, WHAT_MODE_CONFIRM, STAGE_TEAM)
            session.pending = step
            center = _box_center(dialog.decline)
            at = f"{center[0]:.0f},{center[1]:.0f}" if center is not None else "?"
            detail.update(
                {
                    "what": WHAT_MODE_CONFIRM,
                    "box": list(dialog.decline),
                    "dialog": dialog.summary(),
                    "reason": (
                        f"读到「{navl.LORDS_MODE_BONUS_QUESTION_ANCHORS[0]}」确认框"
                        f"（{dialog.summary()}）—— 点「{navl.LORDS_MODE_BONUS_DECLINE}」"
                        f"@720({at})（默认不消耗加成次数；真机实测点它同样进编队页）"
                    ),
                }
            )
            print(f"[lords] 模式页：{detail['reason']}")
            return CustomRecognition.AnalyzeResult(box=list(dialog.decline), detail=detail)
        if state != navl.LORDS_STATE_MODE:
            return _no_hit(
                f"当前不是领主战模式选择页（state={state}）—— 不点（判据见 scene/lords_nav.page_state）",
                **detail,
            )
        box = evidence.solo_click_box
        if box is None:
            return _no_hit(
                f"模式选择页证据不完整（{evidence.summary()}；需要四段文案同时在各自象限、"
                f"且「{navl.LORDS_MODE_SOLO}」比「{navl.LORDS_MODE_MULTI}」高 ≥"
                f"{navl.LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY}px）—— 不点（绝不盲点）",
                **detail,
            )
        # 新的一轮换点阶梯：点击账归零（上一次成功的复核已由 _note_mode_result 清账）
        session.mode_clicks = 0
        session.mode_clicked_at = now
        session.mode_verified = False
        session.mode_fail_reason = ""
        step = ClickStep(box, WHAT_MODE, STAGE_TEAM)
        session.pending = step
        center = _box_center(step.box)
        at = f"{center[0]:.0f},{center[1]:.0f}" if center is not None else "?"
        labels = "/".join(label for label, _dx, _dy in navl.LORDS_MODE_CLICK_LADDER)
        detail.update(
            {
                "what": WHAT_MODE,
                "box": list(step.box),
                "ladder": [list(point) for point in navl.mode_click_points(step.box)],
                "reason": (
                    f"点「{navl.LORDS_MODE_SOLO}」的当帧 OCR 框中心（不写死坐标）；失败换点 "
                    f"{labels}（每点轮询读帧 ≤{navl.LORDS_MODE_POLL_TIMEOUT_SEC:g}s、"
                    f"间隔 {navl.LORDS_MODE_POLL_INTERVAL_SEC:g}s），最多 "
                    f"{navl.LORDS_MODE_MAX_ATTEMPTS} 个点 → 期望进入编队页（{navl.LORDS_STATE_TEAM}），"
                    f"读到「{navl.LORDS_MODE_BONUS_QUESTION_ANCHORS[0]}」确认框就点"
                    f"「{navl.LORDS_MODE_BONUS_DECLINE}」；"
                    f"复核只认正向证据（挑战 + SET/Party/自动续战 至少一个）"
                ),
            }
        )
        print(
            f"[lords] 模式页：点「{navl.LORDS_MODE_SOLO}」@720({at}) —— "
            f"首选框中心，失败依次换点 {labels}（每点轮询读帧 ≤"
            f"{navl.LORDS_MODE_POLL_TIMEOUT_SEC:g}s、间隔 {navl.LORDS_MODE_POLL_INTERVAL_SEC:g}s，"
            f"最多 {navl.LORDS_MODE_MAX_ATTEMPTS} 个点）；读到「"
            f"{navl.LORDS_MODE_BONUS_QUESTION_ANCHORS[0]}」确认框就点"
            f"「{navl.LORDS_MODE_BONUS_DECLINE}」；"
            f"★复核必须是编队页（挑战 + SET/Party/自动续战）★，不点「{navl.LORDS_MODE_MULTI}」★"
        )
        return CustomRecognition.AnalyzeResult(box=list(step.box), detail=detail)

    def _scroll(self, items, context, argv, session, navl, nav):
        """``mode=scroll``：该不该滚一次（时间闩 / 到底 / 页签 / 选行优先 / 上限兜底）。

        ★D6 关轮期间让路★：``back_to_list_pending`` 为真且已在列表页时**不滚** ——
        先让 ``mode=read`` 读这一屏并关轮；否则会在旧位置继续找旧目标，读不到完整的一屏。
        ★扫描期例外★：``page_pending`` 为真时照常扫（read 的扫描闸此时也不会规划，让路只会死锁）。
        """
        if not nav.page_pending(session.round_index):
            gate = _back_to_list_gate(session, items)
            if gate:
                return _no_hit(gate, mode=MODE_SCROLL, gate="back_to_list")
        now = _now()
        registry = _registry()
        plan = navl.SCROLL_PLAN
        _ensure_round(navl, nav, session, now)
        stuck = self._nav_stuck(session, nav, items, navl, now)
        if stuck:
            print(f"[lords] 收工：{stuck}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            return _hit_box_zero(mode=MODE_SCROLL, stop=True, reason=stuck)

        evidence = navl.tab_state(items, registry)
        scanning = nav.page_pending(session.round_index)
        detail = {
            "mode": MODE_SCROLL,
            "tab": evidence.confirmed,
            "scrolls_in_page": nav.scrolls_in_page,
            "stable": f"{nav.stable_scrolls}/{plan.stable_times}",
            "rewind_done": bool(nav.rewind_done),
            "scan_incomplete": nav.scan_incomplete_reason(),
        }
        if not evidence.list_page:
            return _no_hit(
                f"不在领主战列表页（读不到「{navl.LIST_PAGE_ANCHOR}」）—— 不滚", **detail
            )
        # ★上限用尽 → 带原因收工★（#50 的反面：那里是静默跳过，这里绝不）。
        # ★但这是**最后兜底**，不该是主路径★（本票 d）：若本轮扫描本来就不完整，原因里必须点名
        #   「扫描不完整（…）」，否则现场又会被「本页已滚 80 次」把病因带偏。
        if nav.scroll_budget_exhausted():
            reason = (
                f"本页已滚 {nav.scrolls_in_page} 次（上限 {plan.max_scrolls_per_page}）仍未到底 —— "
                f"带原因收工（半扫一遍的列表判不了「全部解禁」；#50 同口径的兜底，不用 max_hit）"
            )
            incomplete = nav.scan_incomplete_reason()
            if incomplete:
                reason += f"；并且本轮扫描不完整（{incomplete}）—— 数据与画面可能不一致"
            print(f"[lords] 收工：{reason}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            return _hit_box_zero(**detail, stop=True, reason=reason)

        target = _target_row(session)
        visible = bool(
            target is not None and find_row_box(items, target, _row_regex(target)) is not None
        )
        desired = nav.desired_tab(None if scanning else target, registry)
        anchor = navl.end_anchor_hit(items)
        allowed, why = nav.may_scroll(
            now,
            confirmed=evidence.confirmed,
            desired=desired,
            target_visible=visible,
            scanning=scanning,
            anchor_hit=anchor,
        )
        detail.update({"desired_tab": desired, "scanning": scanning, "gate": why})
        if not allowed:
            return _no_hit(why, **detail)
        print(f"[lords] {why}")
        return _hit_box_zero(**detail)

    @staticmethod
    def _scan_tab_mismatch(evidence, desired) -> bool:
        """★本票 b 的判据★：这一帧的页签证据是否**不是**本轮该扫的那个。

        单独成一个方法是为了让守卫能**定点破坏**（把它恒 False = 退回「页签没切也宣布
        两个页签都扫到底」的修前形态），而不是只能连 `_end` 一起打桩。
        """
        return desired is not None and evidence.confirmed != desired

    def _end(self, items, context, argv, session, logic, navl, nav):
        """``mode=end``：**到底判据**（命中 = 这一页滚到底了），并推进页签扫描。

        两个都扫到底之后，把**累计读数**交给既有的 :meth:`_read` 判一轮（plan / 三条终结 /
        收工出口全部复用，一行判定都不重写）。合成帧先做**逐项复原核对**，对不上就不规划。

        ★D6 关轮期间让路★：``back_to_list_pending`` 为真且已在列表页时不推进页签扫描 ——
        先让 ``mode=read`` 关本轮，再用**新一轮**的重扫（``begin_round``）读全量。
        ★扫描期例外★：``page_pending`` 为真时照常推进（否则 read 的扫描闸 + 这里的让路会死锁）。
        """
        if not nav.page_pending(session.round_index):
            gate = _back_to_list_gate(session, items)
            if gate:
                return _no_hit(gate, mode=MODE_END, gate="back_to_list")
        now = _now()
        registry = _registry()
        _ensure_round(navl, nav, session, now)
        scanning = nav.page_pending(session.round_index)
        evidence = navl.tab_state(items, registry)
        desired = nav.desired_tab(None, registry)
        detail = {
            "mode": MODE_END,
            "tab": evidence.confirmed,
            "desired_tab": desired,
            "scanning": scanning,
            "at_end": nav.at_end(),
            "page_finished": nav.page_finished(),
            "bottom_unprovable": bool(nav.bottom_unprovable),
            "rewind_done": bool(nav.rewind_done),
            "scan_incomplete": nav.scan_incomplete_reason(),
            "stable": f"{nav.stable_scrolls}/{navl.SCROLL_PLAN.stable_times}",
        }
        stuck = self._nav_stuck(session, nav, items, navl, now)
        if stuck:
            print(f"[lords] 收工：{stuck}")
            session.stop_requested = True
            _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
            return _hit_box_zero(**detail, stop=True, reason=stuck)
        if not evidence.list_page:
            return _no_hit(
                f"不在领主战列表页（读不到「{navl.LIST_PAGE_ANCHOR}」）—— 到底判据无从谈起", **detail
            )
        if not nav.page_pending(session.round_index):
            return _no_hit(
                f"扫描阶段已结束（round={session.round_index} 已扫完）—— 到底也不再推进页签"
                f"（后面的滚是「找目标行」，由 mode=scroll 判）",
                **detail,
            )
        # ★本票 b：页签没切成功 ⇒ 不许宣布「两个页签都扫到底」★（真机 484 第 6 轮验收：
        #   `轮到降临讨伐` 之后一次 `页签：click` 都没有，同一帧「领主战」再读 3 次 + 滚 2 次
        #   就收尾，于是「两页签共 4 行 / 目标 0」—— 画面上 降临讨伐 还有 红嫉机兵 1/4）。
        #   这里只做**拒绝推进**（交给 LordsSwitchTab 真点 + 复核）；切不过去的收工原因由
        #   `_tab` 的 ACTION_STOP 分支写「页签未切换 … 扫描不完整」。
        if self._scan_tab_mismatch(evidence, desired):
            return _no_hit(
                f"到底判据不成立：当前页签不是本轮该扫的「{desired}」（可见行族="
                f"{evidence.confirmed!r}）—— 先让 LordsSwitchTab 切到目标页签并复核；"
                f"★页签没切成功就不许宣布「两个页签都扫到底」★",
                **detail,
            )
        if not nav.page_finished():
            return _no_hit(
                f"还没到底（连续无变化 {nav.stable_scrolls}/{navl.SCROLL_PLAN.stable_times} 次）",
                **detail,
            )
        if nav.bottom_unprovable and not nav.at_end():
            print(
                f"[lords] 本页底不可证：有行被徽标剔除（累计 {nav.dropped_in_scan} 行）+ 连续滚不动 "
                f"⇒ 不判「到底」，按**扫描不完整**收尾（零目标时原因会点名这一点）"
            )

        anchor = navl.end_anchor_hit(items)
        if anchor:
            detail["anchor"] = anchor
        done, why = nav.advance_tab(now)
        detail.update(
            {"tab_done": list(navl.LORD_TABS)[: nav.sweep_index + 1], "sweep_done": done, "advance": why}
        )
        print(f"[lords] {why}")
        if not done:
            return _hit_box_zero(**detail)

        # ★扫描阶段到此结束 = pick 阶段从这里起算★：把「点不出去」死线基准拨到**现在**。
        # 扫描两个页签的几十秒是**导航**，不是「点目标」；不重置的话，扫完这一帧的 pick
        # 一起步就背着一整段扫描时间（#100 回归：解禁 0 场）。★放在三个出口之前★：
        # 合成帧为空 / 逐项复原对不上这两条早退也已经是「扫描结束」，同样要重置。
        session.last_click_at = _now()
        # ★arm/plan 的轮次对齐★（本票 e）：`_read` 可能在这一次交接里**关本轮**
        #   （session.round_index += 1），`complete_scan` 必须记在**被扫的那一轮**上，
        #   否则「新一轮」会被误标成「已扫完」—— 正是「sweep 比 plan 晚一步」的另一半。
        scan_round = session.round_index

        # ---- 两个页签都扫到底：把累计读数交给既有的 read 判定 ----
        scanned = nav.rows()
        detail["scanned"] = len(scanned)
        synth = _synthesize_items(scanned)
        if not synth:
            nav.complete_scan(scan_round, now)
            incomplete = nav.scan_incomplete_reason()
            if incomplete:
                reason = ZERO_TARGET_INCOMPLETE_REASON.format(evidence=incomplete)
                session.last_reason = reason
                print(f"[lords] 收工：{reason}")
                session.stop_requested = True
                _override_next(context, getattr(argv, "node_name", ""), [STOP_NODE])
                return _hit_box_zero(
                    **detail, stop=True, reason=reason, zero_target_incomplete=True
                )
            return _no_hit(
                "两个页签都扫到底，但一行 `通关数 N/M` 都没读到 —— 不判全通（零行 ≠ 全通）",
                **detail,
            )
        back, _orphans = logic.group_progress_rows(synth)
        keys_back = tuple(navl.row_key(row) for row in back)
        keys_src = tuple(navl.row_key(row) for row in scanned)
        if keys_back != keys_src:
            # ★绝不按复原不对的读数规划★：宁可让既有的单帧读法接手，也不打错档。
            # 同时把扫描闸关掉（complete_scan）—— 否则下一圈会又推进一次页签，
            # 而 advance_tab 每次都会记「有进展」，时间死线永远不会到（= 静默空转）。
            nav.complete_scan(scan_round, _now())
            return _no_hit(
                f"合成帧复原不出同一批读数（源 {len(keys_src)} 行 / 复原 {len(keys_back)} 行）"
                f"—— 绝不按错的读数规划（本轮改由 mode=read 按当前帧读）",
                **detail,
            )
        print(f"[lords] 两个页签共扫到 {len(scanned)} 行 —— 交给 mode=read 判一轮")
        result = self._read(synth, context, argv, session, logic, synthesized=True)
        nav.complete_scan(scan_round, _now())
        merged = dict(getattr(result, "detail", None) or {})
        merged["nav"] = detail
        return CustomRecognition.AnalyzeResult(box=result.box, detail=merged)


# ---------------------------------------------------------------------------
# custom_action = "lords_unlock_step"
# ---------------------------------------------------------------------------
class LordsUnlockAction(CustomAction):
    """把 ``lords_progress mode=pick`` 选出来的那一处**点下去**，并记账。

    ★一次只点一下★（三跳 = 三次命中）：这样每次点击之前都有一次**新鲜 OCR**，
    不会出现「凭记忆连点三下」——真机上中间任何一页慢一拍都会点飞。

    记账口径：

    * 点的是【挑战】（``what=challenge``）→ ``sessions_played += 1``（= D6 的「场次」）；
    * 任何一次成功点击都会 ``attempts_since_read += 1``（用于判定「这一轮结束了」）；
    * 点失败 → 返回 ``False``（动作失败，交给 pipeline 的 ``on_error`` 回枢纽），**不记账**。

    ★#120：异常绝不许被 ctypes 吞掉★
    ---------------------------------
    ``CustomAction._c_run_agent`` 是 ctypes 回调 —— 在它里面冒出去的异常会被 CPython 记成
    ``Exception ignored on calling ctypes callback function ...`` 然后**丢掉**：框架只知道
    「动作失败」，**没有人看得到栈**。真机现场就是 ``len(Rect)`` 崩在点页签那一步，现场却只看到
    #19 那条正确的「页签未确认…」收工理由（症状离病因一个 len 那么远）。
    所以 ``run()`` 只做一件事：**兜住一切异常 → 喊一行 ``★动作异常★`` + 栈 → 如实返回 False**。
    """

    def run(self, context, argv) -> bool:  # noqa: D102
        try:
            return self._dispatch(context, argv)
        except Exception as exc:  # noqa: BLE001 - ★本回调的异常只会被 ctypes 静默丢弃★
            _announce_action_error(exc, argv)
            return False                    # 本步不做，交回枢纽（框架按动作失败走 on_error）

    def _dispatch(self, context, argv) -> bool:
        """真正的一步（异常处理在 :meth:`run`；这里只管「点哪、记什么账」）。"""
        session = _session(getattr(argv.task_detail, "task_id", None))
        # ★已判收工★：识别已把本节点的 next 覆盖成 LordsStop，动作要**成功但什么都不做**。
        # 返回 False 会让框架走 on_error 回枢纽，覆盖的 next 作废 → 收工在枢纽里无限重来。
        if _is_stop_requested(session):
            print("[lords] 已判收工：本步不点不滚（按识别覆盖的 next 去 LordsStop）")
            session.pending = None
            return True
        param = read_action_param(argv)
        do = str(param.get("do") or DO_CLICK)
        if do == DO_TAB:
            return self._tab_click(context, argv, session)
        if do == DO_SCROLL:
            return self._scroll_once(context, session)
        if do == DO_SCROLL_TOP:
            return self._scroll_top(context, session)

        step = session.pending
        if step is None:
            quad = _box4_snapshot(getattr(argv, "box", None))   # ★Rect / list 都认★
            if quad is None:
                print(
                    "[lords] 拒绝点击：没有可点的框（识别没给、会话也没有待点步骤；"
                    "缺失 / 尺寸为 0 / 中心在 (0,0) 都算无效框）—— 绝不点 (0,0)"
                )
                return False
            step = ClickStep(quad, WHAT_UNKNOWN, session.stage)

        # ★pick 阶段的两条导航★（#100 第 3 条真机缺口）：都不是「点目标」——
        #   页签：**不记** attempts_since_read（否则会误判「这一轮结束了」）；
        #   滚动：**重置**「点不出去」死线（导航在推进，不该算作点不动）。
        what = getattr(step, "what", None)
        if what == WHAT_TAB:
            return self._tab_click(context, argv, session, box=step.box)
        if what in (WHAT_SCROLL_DOWN, WHAT_SCROLL_UP):
            return self._scroll_search(context, session, what)
        # ★本票 ②★：详情页【返回】= 回列表的导航一跳（不记 attempts；点完置「先重读」闸）。
        if what == WHAT_BACK:
            return self._back_click(context, session, step.box)
        # ★#100 第 7 个真机缺口★：模式页点「单人游戏」= 换点阶梯（点完轮询读帧 +
        #   只认正向证据）；不进下面的「点一下就完」路径。
        if what == WHAT_MODE:
            return self._mode_click(context, session, step.box)
        # ★#100 第 9 个真机缺口★：点完「单人游戏」后弹出的「加成点数」确认框 → 点「否」。
        if what == WHAT_MODE_CONFIRM:
            return self._mode_dialog_click(context, session, step.box)

        center = _click_target(step.box, str(step.what))   # ★#100 缺口 8：框闸（绝不点 (0,0)）★
        if center is None:
            return False
        cx, cy = center
        if not _click_hook(context, cx, cy):
            return False

        session.pending = None
        session.attempts_since_read += 1
        session.last_click_at = _now()
        if step.what == WHAT_CHALLENGE:
            session.sessions_played += 1
            session.stage = STAGE_FIGHT
            session.challenge_pending = True          # 这一场没结束前不许再点挑战
            session.challenge_clicked_at = session.last_click_at
            print(f"[lords] 点【挑战】-> 第 {session.sessions_played} 场（本轮第 {session.attempts_since_read} 次点击）")
        else:
            # 点到行/档 = 已经翻页了 ⇒ 上一场早就结束了，「刚开打」的闩可以放开
            session.challenge_pending = False
            session.stage = step.stage
            print(
                f"[lords] 点 {step.what} @720({cx:.0f},{cy:.0f}) -> 阶段 {step.stage}"
                f"（本轮第 {session.attempts_since_read} 次点击）"
            )
        return True


    # -- do=tab / do=scroll（#100 第 1、2、3 条真机缺口）----------------------
    def _tab_click(self, context, argv, session, box=None) -> bool:
        """点页签：点**当帧 OCR 框的中心**（绝不写死坐标）。

        ★不记 ``attempts_since_read``★：那是「点了一次目标（行/档/挑战）」的计数，
        页签是**导航**不是打目标；算进去会让扫完一轮后的第一读就误判「这一轮结束了」，
        进而 ``played == 0`` 触发防死循环收工（一枪不放就退）。

        ★``box`` 参数★：``do=tab``（``mode=tab`` 那条路）从 ``argv.box`` 取；pick 阶段对页签时
        识别已经把标签框放进 ``session.pending``，这里直接用它（同一条「点框中心」语义）。

        ★框一律走 :func:`_click_target`★（= ``_box_center`` + 盲点拒绝日志）：真机的
        ``argv.box`` 是 maa v5 的 ``Rect``（只有 ``.x/.y/.w/.h``，**没有** ``__len__``）——
        #120 就是 ``len(box) != 4`` 在这里抛 TypeError、又被 ctypes 吞掉，于是「页签根本没点下去」
        而框架不报错。★#100 缺口 8★：框缺失 / 尺寸为 0 / 中心在 (0,0) 时**拒绝点击**
        （真机修前出现过 ``点页签 @720(0,0)`` 的盲点）。
        中心**保留浮点**，取整交给 :func:`_click_box`（真正发点击那一下）。
        """
        center = _click_target(box if box is not None else getattr(argv, "box", None), "页签")
        if center is None:
            return False
        cx, cy = center
        if not _click_hook(context, cx, cy):
            return False
        session.pending = None                       # 这一下已经落地，别让下一步复用旧框
        session.last_click_at = _now()
        nav = _nav_state(session)
        if nav is not None:
            # 换了页签 = 换了一张列表页 → 页内滚动计数/到底计数/上一帧读数全部清零
            # （★假设：切页签后列表回到顶部★ —— 待真机标定，见 scene/lords_nav.reset_page）
            nav.reset_page()
        pick = _pick_nav_state(session)
        if pick is not None:
            # 归位也跟着换页：两向计数 / 失败结论 / 上一帧读数全部作废（同一页才谈「到底」）
            pick.reset_search()
        print(f"[lords] 点页签 @720({cx:.0f},{cy:.0f}) —— 切完由 mode=tab / mode=pick 复核确认")
        return True

    # -- do=click(what=back)：详情页【返回】= 回列表（本票 ②：settle → detail → 返回 → list）--
    def _back_click(self, context, session, box) -> bool:
        """点详情页左下角【返回】，回列表后**先重读 `通关数 N/M`**（D6 关轮）。

        ★为什么是导航、不记 ``attempts_since_read``★：它不打开任何目标，只换页面；
        记进去会让「关轮」的判据提前误成立（和页签/滚动同一口径）。

        ★点完置 ``back_to_list_pending``★：回到列表后枢纽里 ``LordsPickTarget`` 排在
        ``LordsReadProgress`` 之前，不置闸就会按**上一轮**的目标再点一次行；置闸后
        ``_pick`` / ``_scroll`` / ``_page`` / ``_end`` 在列表页一律让路，只有 ``mode=read``
        能命中 —— 读到行的那一刻 ``_read`` 会关轮并重新 ``plan_round``（并清掉本闸）。

        ★不改 targets / challenge_pending★：旧目标等重读后再规划；闩只归放闩那两条路径管。
        """
        center = _click_target(box, "详情页·返回")
        if center is None:
            return False
        cx, cy = center
        if not _click_hook(context, cx, cy):
            return False
        session.pending = None
        session.last_click_at = _now()
        session.back_to_list_pending = True
        print(
            f"[lords] 点【返回】@720({cx:.0f},{cy:.0f}) —— 回列表后先重读 通关数、关本轮"
            f"（D6：每轮重开列表）"
        )
        return True

    # -- do=click(what=mode)：模式页换点阶梯（#100 第 7、9 个真机缺口）-------------
    def _mode_click(self, context, session, box) -> bool:
        """点「单人游戏」：点当帧框中心 → **轮询读帧**（≤8s）→ 遇到「加成点数」确认框
        就点「否」→ 直到读到**编队页正向证据**；这一点不成立才换下一个点（有界 4 个）。

        真机 484（2026-10-18 夜）实测时间线::

            点「单人游戏」@720(170,523)
            +1.8s  弹出「要使用增加报酬的『领主加成点数』吗？」（是 / 否）
            +2.6s  点「否」
            +3.9s  编队页（挑战 + SET 1 / Party A / 自动续战 = 正向证据）

        ★这就是「模式页点不动」的真因★：点击**是生效的**，弹的是一个旧判据不认识的
        **模态确认框**；旧实现固定等 2.5s 只读一帧（正好读到它 = ``lords_unknown``），
        随后换点阶梯的 4 个点全打在遮罩上。

        * 任一点确认到编队页 ⇒ 成功（``stage=team``，``mode_verified=True``）；
        * 确认框最多点 ``LORDS_MODE_MAX_DIALOG_CLICKS`` 次（正常只出现一次）；
        * 四个点都试过仍没到 ⇒ ``mode_fail_reason`` 粘住 + 打印**带读数**的文案并返回
          ``False``，下一圈由 ``_tab`` / ``_mode`` 立刻 override 到 ``LordsStop``（带量收工）。

        ★有界★：点阶梯 ≤ 4 次 + 确认框 ≤ 1 次；每次点完的读帧也有上限
        （次数 = 轮询超时 / 间隔）。
        """
        navl = _nav()
        if navl is None:
            print(f"[lords] {NAV_INSTALL_STATE_REASON}")
            return False
        center = _click_target(box, "模式页·单人游戏")     # ★#100 缺口 8：无效框绝不点★
        if center is None:
            return False
        points = navl.mode_click_points(box)
        if not points:
            print(
                f"[lords] 模式页：单人游戏框无效（{list(center)}）—— 换点阶梯为空，拒绝点击（绝不盲点）"
            )
            return False
        total = len(points)
        interval = float(navl.LORDS_MODE_POLL_INTERVAL_SEC)
        timeout = float(navl.LORDS_MODE_POLL_TIMEOUT_SEC)
        session.mode_dialog_clicks = 0
        print(
            f"[lords] 模式页换点阶梯：{total} 个点（"
            + " → ".join(f"{label}@720({cx:.0f},{cy:.0f})" for label, cx, cy in points)
            + f"），每个点：点完轮询读帧 ≤{timeout:g}s（间隔 {interval:g}s）；"
            f"读到「{navl.LORDS_MODE_BONUS_QUESTION_ANCHORS[0]}」确认框就点"
            f"「{navl.LORDS_MODE_BONUS_DECLINE}」；复核只认编队页（挑战 + SET/Party/自动续战）"
        )
        last_state = ""
        last_anchor = None
        note = ""
        for index, (label, cx, cy) in enumerate(points):
            clicked = _click_hook(context, cx, cy)
            session.mode_clicks = index + 1
            session.mode_clicked_at = _now()
            session.last_click_at = session.mode_clicked_at
            if clicked:
                session.attempts_since_read += 1
            print(
                f"[lords] 模式页换点 {index + 1}/{total}：「{label}」@720({cx:.0f},{cy:.0f})"
                f"（点击{'派发成功' if clicked else '派发失败'}）→ 轮询读帧"
            )
            verdict, last_state, last_anchor, note, declined = self._watch_mode_click(
                context, navl, session, index, total, label
            )
            if verdict == "team":
                session.mode_verified = True
                session.stage = STAGE_TEAM
                session.pending = None
                session.challenge_pending = False     # 走到模式页 = 上一场早结束了
                print(
                    f"[lords] 模式页：第 {index + 1} 个点成功（共试 {index + 1}/{total} 个点，"
                    f"确认框点 {session.mode_dialog_clicks} 次）"
                    f" -> 阶段 {STAGE_TEAM}（本轮第 {session.attempts_since_read} 次点击）"
                )
                return True
            if verdict == "other" or declined:
                # 页面已经不是模式页（或确认框已经点过）：继续点只会点在别的页面上
                print(
                    f"[lords] 模式页换点 {index + 1}/{total}：{verdict}（state={last_state}，"
                    f"锚={last_anchor!r}）—— 停止换点，绝不盲点"
                )
                break
        # ★点阶梯用尽（或页面已变）⇒ 带读数收工★（粘住理由；下一圈 _tab/_mode 立刻收工）
        reason = navl.mode_click_exhausted_reason(last_state or None, last_anchor, note)
        session.mode_fail_reason = reason
        session.last_reason = reason
        session.pending = None
        print(f"[lords] 模式页换点阶梯用尽：{reason}")
        return False

    def _watch_mode_click(self, context, navl, session, index, total, label):
        """点完一次后的**轮询读帧**（#100 第 9 个真机缺口）。

        返回 ``(verdict, last_state, last_anchor, note, declined)``：

        * ``"team"`` —— 读到编队页正向证据（★唯一成功★）；
        * ``"still_mode"`` —— 连续 ``LORDS_MODE_STILL_MODE_READS`` 帧都是模式页（这一点没生效）；
        * ``"other"`` —— 连续 ``LORDS_MODE_STABLE_READS`` 帧停在**别的**稳定页（不是编队页）；
        * ``"timeout"`` —— 轮询窗口内没有稳定分类（转场帧 / 认不出）。

        ``declined`` = 这次轮询里点过「否」（加成确认框）。调用方据此不再换点：
        确认框都点过了还到不了编队页，继续点只会点在别的页面上。
        """
        interval = max(0.05, float(navl.LORDS_MODE_POLL_INTERVAL_SEC))
        timeout = max(interval, float(navl.LORDS_MODE_POLL_TIMEOUT_SEC))
        stable_reads = max(1, int(navl.LORDS_MODE_STABLE_READS))
        still_reads = max(1, int(navl.LORDS_MODE_STILL_MODE_READS))
        max_dialogs = max(0, int(getattr(navl, "LORDS_MODE_MAX_DIALOG_CLICKS", 1)))
        max_reads = max(2, int(timeout / interval) + 1)
        deadline = _now() + timeout
        same_state = None
        same_count = 0
        mode_count = 0
        last_state = ""
        last_anchor = None
        note = ""
        declined = False
        dialog_tried = False          # ★同一轮里只尝试一次「否」（派发失败也不连点）★
        for read in range(1, max_reads + 1):
            _sleep(interval)
            items = _read_items_hook(context)
            state = navl.page_state(items)
            anchor = navl.team_anchor_hit(items)
            confirmed = bool(navl.team_page_confirmed(items))
            last_state, last_anchor = state, anchor
            print(
                f"[lords] 模式页换点 {index + 1}/{total}「{label}」读 {read}："
                f"state={state} 锚={anchor!r} 编队页={confirmed}"
            )
            if confirmed:
                return ("team", state, anchor, note, declined)
            dialog = navl.bonus_dialog(items)
            if (
                dialog.is_dialog
                and not declined
                and not dialog_tried
                and session.mode_dialog_clicks < max_dialogs
            ):
                dialog_tried = True                  # 先记账再点：派发失败也不重试（有界）
                center = _click_target(dialog.decline, "加成点数确认框·否")
                if center is not None and _click_hook(context, center[0], center[1]):
                    declined = True
                    session.mode_dialog_clicks += 1
                    session.last_click_at = _now()
                    print(
                        f"[lords] 模式页读到「加成点数」确认框（{dialog.summary()}）→ 点"
                        f"「{navl.LORDS_MODE_BONUS_DECLINE}」@720({center[0]:.0f},{center[1]:.0f})"
                        f"（不消耗加成次数；真机实测同样进编队页）"
                    )
                    # 确认之后是页面切换：重新给一个完整的轮询窗口
                    deadline = _now() + timeout
                    same_state, same_count, mode_count = None, 0, 0
                    continue
                note = "加成确认框出现过，但「否」按钮框读不到或点击派发失败（不盲点/不连点）"
                print(f"[lords] 模式页：{note}（{dialog.summary()}）")
            if state == navl.LORDS_STATE_MODE:
                mode_count += 1
                same_state, same_count = state, mode_count
                if mode_count >= still_reads:
                    return ("still_mode", state, anchor, note, declined)
            elif state in (
                navl.LORDS_STATE_UNKNOWN,
                navl.LORDS_STATE_LOADING,
                navl.LORDS_STATE_TEAM,
            ):
                # 转场帧 / 编队页但还没读到正向锚：都不算「稳定停在别的页」，继续等
                same_state, same_count, mode_count = None, 0, 0
            else:
                mode_count = 0
                if state == same_state:
                    same_count += 1
                else:
                    same_state, same_count = state, 1
                if same_count >= stable_reads:
                    return ("other", state, anchor, note, declined)
            if _now() >= deadline or read >= max_reads:
                break
        return ("timeout", last_state, last_anchor, note, declined)

    def _mode_dialog_click(self, context, session, box) -> bool:
        """点「加成点数」确认框的「否」（**框来自当帧 OCR**，绝不写死坐标）。

        这是「模式页 → 编队页」这一跳的第二段：只点一下、**不**记
        ``attempts_since_read``（同一次跳，第一段已经记过），点完由下一轮
        ``mode=solo`` / ``mode=pick`` 复核。
        """
        center = _click_target(box, "加成点数确认框·否")
        if center is None:
            return False
        if not _click_hook(context, center[0], center[1]):
            return False
        session.pending = None
        session.last_click_at = _now()
        session.mode_dialog_clicks += 1
        session.stage = STAGE_TEAM
        print(
            f"[lords] 点「加成点数」确认框的「否」@720({center[0]:.0f},{center[1]:.0f})"
            f" —— 不消耗加成次数，等编队页复核"
        )
        return True

    def _scroll_search(self, context, session, what) -> bool:
        """pick 阶段**滚一次去找目标行**（方向 = :data:`WHAT_SCROLL_DOWN` / ``_UP``）。

        与 ``do=scroll``（扫描期那条）的区别有三条，每条都有真机依据：

        1. **方向可反**：向上滚（回顶部）是**同一个手势反向**（:attr:`ScrollPlan.up_begin` /
           :attr:`ScrollPlan.up_end`）—— 几何只有 :data:`SCROLL_PLAN` 一份来源，节点参数用
           ``pipeline_override`` 按方向覆盖（先例：``agent/wuchong_impl.swipe``）。
        2. **自己补足稳定等待**：``LordsPickTarget`` 的 ``post_delay`` 只有 800ms
           （< :attr:`ScrollPlan.settle_ms` 2600 = #42 惯性），本动作里补睡，绝不趁列表还在滑
           的时候去读下一帧（那会点飞）。
        3. **不消耗「点不出去」死线**：滚动是导航；每滚一次都刷新
           ``session.last_click_at``，并把导航死线的「有进展」也记上（否则 30s 的
           ``NAV_STUCK_SEC`` 会把正在找的这根线程误判成卡死）。
        """
        navl = _nav()
        pick = _pick_nav_state(session)
        nav = _nav_state(session)
        if navl is None or pick is None:
            print(f"[lords] {NAV_INSTALL_STATE_REASON}")
            return False
        plan = navl.SCROLL_PLAN
        up = what == WHAT_SCROLL_UP
        begin, end = (plan.up_begin, plan.up_end) if up else (plan.begin, plan.end)
        now = _now()
        # ★时间闩★：与扫描期同一把（距上次滚动不足 1.2s 就补睡差额，绝不连甩）
        if pick.last_scroll_at > 0:
            waited = now - pick.last_scroll_at
            if waited < plan.min_interval_sec:
                gap = plan.min_interval_sec - waited
                print(
                    f"[lords] 找行滚动时间闩：距上次滚动 {waited:.2f}s < {plan.min_interval_sec}s —— "
                    f"补睡 {gap:.2f}s 再滚（绝不连甩）"
                )
                _sleep(gap)
        # 手势几何：反向时用 pipeline_override 盖住节点参数（**不写第二份坐标**）
        override = {
            SCROLL_NODE: {
                "action": {
                    "param": {
                        "begin": [int(begin[0]), int(begin[1])],
                        "end": [int(end[0]), int(end[1])],
                        "duration": int(plan.duration_ms),
                    }
                }
            }
        }
        try:
            context.run_action(SCROLL_NODE, pipeline_override=override)
        except Exception as exc:  # noqa: BLE001 - 滚不动就是这一下失败，不吞成「成功」
            print(f"[lords] 找行滚动手势节点 {SCROLL_NODE} 执行失败：{exc!r}")
            # ★连续失败要有界★：动作失败会让框架走 on_error 回枢纽，而枢纽里 pick 排在
            #   所有「读列表」节点之前 —— 不记这笔就会无限空转（#50 拦的正是这种形态）。
            failures = pick.note_scroll_error()
            print(
                f"[lords] 找行滚动手势连续失败 {failures}/"
                f"{navl.TAB_UNCONFIRMED_LIMIT} 次（超过就带原因收工）"
            )
            return False
        pick.note_scroll(navl.PICK_SCROLL_UP if up else navl.PICK_SCROLL_DOWN, _now())
        session.pending = None
        session.last_click_at = _now()       # ★导航不算「点不动」★
        if nav is not None:
            nav.note_progress(_now())        # 找行是真进展：30s 导航死线不该在这里响
        print(
            f"[lords] 找行{'向上' if up else '向下'}滚一次："
            f"下 {pick.scrolls_down} / 上 {pick.scrolls_up} 次，"
            f"行程 {abs(int(end[1]) - int(begin[1]))}px "
            f"（{'反' if up else '正'}向，{'露出上面的行' if up else '露出下面的行'}）"
        )
        # ★#42 惯性★：``LordsPickTarget.post_delay`` 800ms < settle_ms 2600 —— 在这里补足
        _sleep(plan.settle_ms / 1000.0)
        return True

    def _scroll_top(self, context, session) -> bool:
        """★回顶部上滚一次★（``mode=top`` 命中后由 ``LordsScrollTop`` 节点调用）。

        ★与 ``do=scroll`` **分开记账**★（本票 a）：
        * 不消耗向下扫的 ``max_scrolls_per_page`` 预算；
        * 不推进「到底」的滚动世代（``scroll_gen``）—— 上滚不是扫描步骤，混进去会让
          「没有新行」在回顶部期间被记成「到底」的一代；
        * 只记回顶部自己的账（``rewind_scrolls`` / ``rewind_gen``），用尽时 ``rewind_failed``。

        ★几何只有一份★：:attr:`ScrollPlan.up_begin` / :attr:`ScrollPlan.up_end`
        （= 向下手势的**同一对端点交换**，不写第二份坐标），用 ``pipeline_override`` 盖住节点参数
        （先例：``agent/wuchong_impl.swipe``）。

        ★#42 惯性★：``lords.json::LordsScrollTop`` 的 ``post_delay`` 只有 800ms
        （节拍契约 ≤1000），在这里补足 ``SCROLL_PLAN.settle_ms`` —— 绝不趁列表还在滑就去读下一帧。
        """
        navl = _nav()
        nav = _nav_state(session)
        if navl is None or nav is None:
            print(f"[lords] {NAV_INSTALL_STATE_REASON}")
            return False
        plan = navl.SCROLL_PLAN
        now = _now()
        # ★时间闩★：与向下扫同一把（距上次滚动不足 1.2s 就补睡差额，绝不连甩）
        if nav.last_scroll_at > 0:
            waited = now - nav.last_scroll_at
            if waited < plan.min_interval_sec:
                gap = plan.min_interval_sec - waited
                print(
                    f"[lords] 回顶部时间闩：距上次滚动 {waited:.2f}s < {plan.min_interval_sec}s —— "
                    f"补睡 {gap:.2f}s 再滚（绝不连甩）"
                )
                _sleep(gap)
        begin, end = plan.up_begin, plan.up_end
        override = {
            SCROLL_NODE: {
                "action": {
                    "param": {
                        "begin": [int(begin[0]), int(begin[1])],
                        "end": [int(end[0]), int(end[1])],
                        "duration": int(plan.duration_ms),
                    }
                }
            }
        }
        try:
            context.run_action(SCROLL_NODE, pipeline_override=override)
        except Exception as exc:  # noqa: BLE001 - 滚不动就是这一下失败，不吞成「成功」
            print(f"[lords] 回顶滚动手势节点 {SCROLL_NODE} 执行失败：{exc!r}")
            return False
        nav.note_rewind_scroll(_now())
        session.pending = None
        session.last_click_at = _now()       # ★导航不算「点不动」★
        print(
            f"[lords] 回顶部上滚一次：第 {nav.rewind_scrolls}/"
            f"{plan.max_rewinds_per_page} 次，行程 {abs(int(end[1]) - int(begin[1]))}px "
            f"（反向同一个手势，露出上面的行），稳定等待 {plan.settle_ms}ms（动作里补足）"
        )
        _sleep(plan.settle_ms / 1000.0)
        return True

    def _scroll_once(self, context, session) -> bool:
        """按 ``SCROLL_PLAN`` 滚一次（**自带时间闩**：两次滚动之间 ≥ ``min_interval_sec``）。

        分工：

        * **时间闩**在这里执行（若距上次滚动不足 1.2s，只补睡差额；正常路径上枢纽的
          ``post_delay`` 已经超过它，所以通常不睡）；
        * **手势几何**在 ``lords.json::LordsSwipeOnce``（``DirectHit + Swipe``，由守卫
          ``lords-nav-pipeline-wiring`` 钉成 ``SCROLL_PLAN`` 的逐字段副本 —— 两处各写一份
          数字就会漂移，所以那一份是「被守卫钉住的副本」而不是第二真源）；
        * **滚完的稳定等待**由节点 ``post_delay`` 承担（2600ms，#42 惯性）。
        """
        navl = _nav()
        nav = _nav_state(session)
        if navl is None or nav is None:
            print(f"[lords] {NAV_INSTALL_STATE_REASON}")
            return False
        plan = navl.SCROLL_PLAN
        now = _now()
        if nav.last_scroll_at > 0:
            waited = now - nav.last_scroll_at
            if waited < plan.min_interval_sec:
                gap = plan.min_interval_sec - waited
                print(
                    f"[lords] 滚动时间闩：距上次滚动 {waited:.2f}s < {plan.min_interval_sec}s —— "
                    f"补睡 {gap:.2f}s 再滚（绝不连甩）"
                )
                _sleep(gap)
        try:
            context.run_action(SCROLL_NODE)
        except Exception as exc:  # noqa: BLE001 - 滚不动就是这一下失败，不吞成「成功」
            print(f"[lords] 滚动手势节点 {SCROLL_NODE} 执行失败：{exc!r}")
            return False
        nav.note_scroll(_now())
        # ★扫描滚动是导航，不是「点目标」★（与找行滚动 :meth:`_scroll_search` 同一口径）：
        # 每滚一次都把「点不出去」死线基准拨到现在。否则扫两个页签的几十秒会全部记进
        # 「点不出去」的账里（#100 回归现场：扫完 52s，pick 一起步就被判死）。
        session.last_click_at = _now()
        print(
            f"[lords] 滚动一次：本页第 {nav.scrolls_in_page}/{plan.max_scrolls_per_page} 次，"
            f"行程 {plan.travel_px}px，稳定等待 {plan.settle_ms}ms（节点 post_delay）"
        )
        return True


__all__ = [
    "Session",
    "ClickStep",
    "ACTION_ERROR_MARK",
    "DEFAULT_OCR_ENTRY",
    "DETAIL_PAGE_MARKER",
    "DO_CLICK",
    "DO_SCROLL",
    "DO_SCROLL_TOP",
    "DO_TAB",
    "FIGHT_GRACE_SEC",
    "HUB_NODE",
    "INSTALL_STATE_REASON",
    "MODE_END",
    "MODE_PAGE",
    "MODE_PICK",
    "MODE_READ",
    "MODE_SCROLL",
    "MODE_SOLO",
    "MODE_TAB",
    "MODE_TOP",
    "NAV_INSTALL_STATE_REASON",
    "PICK_DIAG_EVERY",
    "REWIND_FAILED_REASON",
    "SCROLL_NODE",
    "STOP_NODE",
    "TAB_SWITCH_UNCONFIRMED_REASON",
    "ZERO_TARGET_INCOMPLETE_REASON",
    "STAGE_DETAIL",
    "STAGE_FIGHT",
    "STAGE_LIST",
    "STAGE_TEAM",
    "STUCK_SEC",
    "WHAT_CHALLENGE",
    "WHAT_BACK",
    "WHAT_MODE",
    "WHAT_MODE_CONFIRM",
    "WHAT_ROW",
    "WHAT_SCROLL_DOWN",
    "WHAT_SCROLL_UP",
    "WHAT_TAB",
    "WHAT_TIER",
    "LordsProgressRecognition",
    "LordsUnlockAction",
    "classify",
    "find_challenge_box",
    "find_row_box",
    "pick_click",
    "reset_sessions",
    "_announce_action_error",
    "_back_to_list_gate",
    "_box4_int",
    "_box_center",
    "_box_xywh",
    "_challenge_release_state",
    "_click_box",
    "_click_target",
    "_detail_back",
    "_detail_tier_choice",
    "_drop_badge_rows",
    "_ensure_round",
    "_grab",
    "_is_stop_requested",
    "_mode_step_state",
    "_nav",
    "_nav_state",
    "_note_after_fight",
    "_note_mode_result",
    "_now",
    "_ocr",
    "_page_state",
    "_pick_diag_once",
    "_pick_nav_state",
    "_read_items",
    "_scene_nav",
    "_sleep",
    "_synthesize_items",
    "_tab_log_once",
    # 安装态冻结快照（真源 scene/lords_unlock.py + scene/lords.py；hooks_100 钉着一致性）
    "_LORDS_CHAIN_SNAPSHOT",
    "_LORDS_KIND_SNAPSHOT",
    "_LORDS_M_SNAPSHOT",
    "_LORDS_ROW_REGEX_SNAPSHOT",
    "_LORDS_ROWS_SNAPSHOT",
    "_PARSE_PROGRESS_SNAPSHOT",
    "_PLAN_ROUND_SNAPSHOT",
    "_SHOULD_STOP_SNAPSHOT",
    "_SnapshotLogic",
    # 安装态冻结快照（导航：真源 scene/lords_nav.py + scene/page_rules.py；hooks_100/hooks_121 钉着一致性）
    "_NavSnapshotLogic",
    "_NavStateSnapshot",
    "_ON_SCREEN_SNAPSHOT",
    "_PickDecisionSnapshot",
    "_PickNavSnapshot",
    "_ROW_ROI_HIT_SNAPSHOT",
    "_ROW_ROI_SNAPSHOT",
    "_SCROLL_MAX_REWINDS_PER_PAGE_SNAPSHOT",
    "_SCROLL_PLAN_SNAPSHOT",
    "_SCREEN_H_SNAPSHOT",
    "_SCREEN_W_SNAPSHOT",
    "_TAB_ANCHOR_SNAPSHOT",
    # 安装态冻结快照（页面状态 + 模式选择页 + 非列表页死线；hooks_122 的 lords-mode-snapshot-parity 钉着）
    "_CHALLENGE_RELEASE_EVIDENCE_SNAPSHOT",
    "_IS_BADGE_TEXT_SNAPSHOT",
    "_LIST_BADGE_MARKS_SNAPSHOT",
    "_RECOVER_BADGE_ROW_NAME_SNAPSHOT",
    "_BADGE_RECOVERY_MAX_DY_SNAPSHOT",
    "_BADGE_RECOVERY_MIN_LEFT_GAP_SNAPSHOT",
    "_DETAIL_BACK_BOX_SNAPSHOT",
    "_DETAIL_BACK_ROI_SNAPSHOT",
    "_DETAIL_BACK_TEXT_SNAPSHOT",
    "_DETAIL_MARK_COMPLETE_SNAPSHOT",
    "_DETAIL_MARK_MAX_DY_SNAPSHOT",
    "_DETAIL_MARK_NEW_SNAPSHOT",
    "_DETAIL_PICK_ALL_COMPLETE_SNAPSHOT",
    "_DETAIL_PICK_NO_STATUS_SNAPSHOT",
    "_DETAIL_PICK_READY_SNAPSHOT",
    "_DETAIL_STATUS_COMPLETE_SNAPSHOT",
    "_DETAIL_STATUS_NEW_SNAPSHOT",
    "_DETAIL_TIER_ALL_DONE_REASON_SNAPSHOT",
    "_DETAIL_TIER_NAME_RE_SNAPSHOT",
    "_DETAIL_TIER_NO_STATUS_REASON_SNAPSHOT",
    "_DETAIL_TIER_ROWS_SNAPSHOT",
    "_DetailTierChoiceSnapshot",
    "_DetailTierSnapshot",
    "_PICK_UNCLEARED_TIER_SNAPSHOT",
    "_LORDS_ACTIVE_STATES_SNAPSHOT",
    "_LORDS_CHALLENGE_RELEASE_STATES_SNAPSHOT",
    "_LORDS_LOADING_ANCHORS_SNAPSHOT",
    "_LORDS_STATES_SNAPSHOT",
    "_LORDS_STATE_LOADING_SNAPSHOT",
    "_LORDS_STATE_MODE_SNAPSHOT",
    "_LORDS_TRANSITION_STATES_SNAPSHOT",
    "_BonusDialogSnapshot",
    "_BONUS_DIALOG_SNAPSHOT",
    "_LORDS_MODE_BONUS_ACCEPT_SNAPSHOT",
    "_LORDS_MODE_BONUS_CHOICE_SNAPSHOT",
    "_LORDS_MODE_BONUS_DECLINE_SNAPSHOT",
    "_LORDS_MODE_BONUS_QUESTION_ANCHORS_SNAPSHOT",
    "_LORDS_MODE_MAX_DIALOG_CLICKS_SNAPSHOT",
    "_LORDS_MODE_POLL_INTERVAL_SEC_SNAPSHOT",
    "_LORDS_MODE_POLL_TIMEOUT_SEC_SNAPSHOT",
    "_LORDS_MODE_STABLE_READS_SNAPSHOT",
    "_LORDS_MODE_STILL_MODE_READS_SNAPSHOT",
    "_ModeEvidenceSnapshot",
    "_NON_LIST_STUCK_REASON_SNAPSHOT",
    "_NON_LIST_STUCK_SEC_SNAPSHOT",
    "_PAGE_RULE_RECOGNITION_SNAPSHOT",
]

