# -*- coding: utf-8 -*-
"""五重决战（wuchong）场景配置【数据】（#56 Phase 4 / 架构裁决：混合方案）。

本文件**只放数据**：一个「场景」（scenario）的导航关键词 / 目标行与详情页的模板 /
单人·多人模式点 / 编队页与战斗中的开关（自动 / 自动续战 / 暂停的自动）几何量 /
共斗开房流程点 / **手操战斗的节奏参数（弹板间隔·技能间隔·每几次弹板放技能·连点批量）**
（★#71★：已删「手操连点时长」—— 手操无固定时长截断。★2026-10-16 运维裁决★：也删了
「HUD 丢失上限」—— 手操引擎**不再用战斗 HUD 做判据**，改成「一直点 + 三个正面终止点
（续关屏 / 结算页 / 被推出战斗）」，认不出的帧一律继续点）
/ 流程链。它**不导入 maa、不跑逻辑**（ADR：``scene/`` 离线可导入、是唯一配置
权威；运行时机制在 ``agent/wuchong_impl.py``）。

为什么是第二类配置（不是领主战类成员）
--------------------------------------
领主战类的形状是「family 模板 + 成员 delta + 难度」（点行名进详情）。五重决战是**共斗
活动场景**：导航走「主城 → 领主战 → 降临讨伐 → 滚动找『五王连战』行 → 五重决战·超级
详情 → 单人/多人 → 编队/房间 → 招募 → 挑战 → 战斗 → 结算」，没有成员/难度矩阵。
硬套 ``FamilyTemplate``/``MemberDelta`` = brief 说的坏抽象（kernel 也不这么做）。

★运维原话（本文件逐条落地，出处 ``<local>\\AppData\\Local\\Temp\\opencode\\hist_req.md``）★
  · 「1.点击领主战 2.点击降临讨伐 3.滚动寻找包含『五王连战』的行 4.二级选单(选
    五重决战 超级) 5.决定是否使用单人/多人」→ :data:`LORD_TAB` / :data:`JOVEN_TAB` /
    :data:`ROW_NAME` / :data:`DETAIL_TITLE` / :data:`WUCHONG_BUTTONS`。
  · 「编队页：1.是否打开自动续展 2.是否打开自动」→ :data:`WUCHONG_SWITCHES`
    （``cont_*`` = 自动续战；「自动」按钮改为**定位**，见 :mod:`scene.auto_switch`）。
  · 「顺序：点招募 + 开始招募，检测是否人齐，人齐了点挑战」→ :data:`WUCHONG_BUTTONS`
    的 ``recruit_open`` / ``recruit_start`` / ``challenge``。
  · 「唯一分歧点：①自动按 user 要求配置 ②进入挑战后若手动开启，需要全程点板子+放技能」
    → :data:`WUCHONG_BATTLE` + :data:`BATTLE_PARAMS`。
  · 「点击的频率、弹板的频率和放技能的频率，都是可以通过参数控制的。这些都是要写在
    参数面板上的」→ :data:`BATTLE_PARAMS`（每项都带 GUI 字段名 / 默认值 / 校验）。
  · 「除了『五重决战』可以选择自动或手动以外，其他所有战斗都需要勾选『自动』。检测位置：
    **编队界面(自动按钮)**」→ :func:`manual_allowed` / :func:`auto_is_optional` /
    :func:`effective_auto_state`（跨模式硬规则）。★二批：检测位置只在战斗外的编队页/房间页，
    且按定位读状态（战斗内的暂停→自动滑块已删除）。★
  · 「我们要按照流程走，只是额外的会有一些异常处理的部分，挂在每个节点上的」→
    :data:`FLOW_EXCEPTIONS`（打断型前缀）+ :data:`FLOW_STEPS`（按真实游戏顺序）。

★模板裁片真机来源★（设备A / 帧 ``tools/frames/20_lord_tab_降临讨伐_列表首行五王连战.png``
与 ``21_wuchong_详情页_五重决战超级.png``，720 空间裁片；自证 ZNCC=1.0，跨帧 ≤ 0.53，阈值
0.80 余量充足）。运维要求「尽量用图片识别」（艺术字/行名 OCR 不可靠）→ 行与详情页**模板
优先、OCR 兜底**。

★二批：自动的切换移到「战斗外」（运维裁决②，真机实测后）★
  · **删除战斗内的自动切换**（原 ``WuchongBattleAutoGuard``：暂停→自动滑块）——战斗里不再切自动；
  · 「自动」开关**不再写死坐标**：一律经 :mod:`scene.auto_switch`（数据）+ ``agent/auto_switch_impl``
    （机制）**定位**（模板/OCR）后读状态、点识别框中心。不同页面位置不同（编队页左下 / 房间页右上）。
  · 跨模式「其他所有战斗都要开自动」：由 ``SpecialTeamAutoSet``（special 分派）/
    ``AbyssTeamAutoSet``（abyss）/ ``auto_switch_state``（机制）在**编队页/房间页**落实。

★待真机校准★（离线无设备，本票只落数据形状与守卫；见报告「deferred」）：
  编队页/房间页「自动」标签裁片的跨机型阈值、共斗开房的 ``recruit_*`` 坐标、
  「自动续战功能」确认框在别的入口是否也会弹出。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Override
from .page_rules import SceneSelection  # noqa: F401  供守卫做注册表复用（re-export）
from .stamina import recovery_refs as _stamina_recovery_refs

# ---------------------------------------------------------------------------
# ① 导航关键词 / 目标行 / 详情页（运维：领主战 → 降临讨伐 → 五王连战 → 五重决战 超级）
# ---------------------------------------------------------------------------
LORD_TAB = "领主战"
JOVEN_TAB = "降临讨伐"
# ★「降临讨伐」既是顶部页签（y≈405）又是每行前缀（列表 y≈550+）★ —— 限定页签区，
#   只命中页签（kernel 真机教训 R21：不加约束会点到列表行）。
JOVEN_TAB_Y_MAX = 450
ROW_NAME = "五王连战"
ROW_PATTERNS = (r"五王连战",)
ROW_TEMPLATE = "wuchong/row_wuwang.png"          # 行副标题「五重决战 / 五王连战」裁片
DETAIL_TITLE = "五重决战超级"
DETAIL_PATTERNS = (r"五重决战\s*超级",)
DETAIL_TEMPLATE = "wuchong/detail_wuchong.png"   # 详情页标题「五重决战 / 五重决战 超级」裁片
TEMPLATE_THRESHOLD = 0.80
SOLO_TEXT = "单人游戏"
MULTI_TEXT = "多人游戏"

# ---------------------------------------------------------------------------
# ①b ★#116★ 模式页「单人游戏 / 多人游戏」：**每张卡只准点自己**（相对位置判据）
#
# 真机缺陷（2026-10-18 07:17:55，`debug/wuchong_agent.log` + `debug/maafw...07.20.11.63.log`）：
#   `[wuchong_act] state=wuchong_mode 点击 '多人游戏' @720(437,866)` → 进共斗房。
#   ★归因当场核对过★：那一枪的框架行是 ``node_name=WuchongModeMulti``，即**多人卡那一支**被派中了
#   —— 那次的选项是「游戏模式」默认值（= 多人），所以点多人是对的。**但本票的病是真的**：
#   · 两个模式节点（``WuchongModeSolo`` / ``WuchongModeMulti``）的**识别完全同形**
#     （都只是 ``wuchong_state == wuchong_mode``，见 ``classify()``：屏幕上有「单人」**或**「多人」即判
#     模式页）⇒ 站在模式页上，**两个节点都命中**；
#   · 谁被选中只取决于「另一张卡有没有被选项关掉」：``--mode 单人`` 把 ``WuchongModeMulti`` 改成
#     ``__NONE__``（``--mode 多人`` 反之）。于是「单人路径」= 「关掉多人」**实现**的 ——
#     ``WuchongModeSolo`` 自己**从来没被单独验证过**。这是**假安全**：override 一失效（选项没应用 /
#     新入口没带 override），单人链路就会静默走进共斗房（真机 07:45 的 ``leg_b`` 就是这么又开了一局）。
#   · 更糟的是「只有一个卡片在屏」的帧（进页动画 / 半屏 / OCR 只读到一张）照样算模式页 ⇒
#     节点在下**它自己那颗按钮根本不存在**的页面上被派中。
#
# 落地（两条，都是「只点自己」）：
#   ① **识别**必须同时要求**自己那张卡的标题串**（pipeline 的 ``WuchongSoloText`` /
#      ``WuchongMultiText`` + ``WuchongModeState`` 的 And）—— 只看到「多人游戏」的帧上
#      ``WuchongModeSolo`` **不命中**（反例见 hooks_116 的 ``wuchong-mode-solo-is-solo``）；
#   ② **点击**除了 ``what`` 只锚定整串（``^单人游戏$`` **不可能**匹配「多人游戏」，且**不会**误吃多人卡里
#      被 OCR 拆成两半的「多人」「游戏」两颗子框）之外，再加一条**相对位置判据**（:data:`SOLO_ABOVE`）：
#      同一份 OCR 结果集合里，目标框的中心必须**在「多人游戏」框上方** ≥
#      :data:`MODE_MIN_SOLO_ABOVE_MULTI_DY` 像素。这是**独立于字符串**的第二道证据：
#      OCR 把多人那张卡的标题读成「单人游戏」时，位置仍然证伪它。
#
# ★几何是**实测**的，不是编的★（720 空间；三帧、两次会话、两种分辨率，÷1.5 后逐像素一致）：
#   · ``leg_c2_multi_from_stale_sample002_wuchong_mode.png``（720p 原始帧）：
#       单人游戏 [78,497,184,52] 中心 (170,523) / 多人游戏 [345,840,184,52] 中心 (437,866)
#   · ``leg_c3_room_sample010_wuchong_mode.png``（720p 原始帧）：
#       单人游戏 [78,497,184,52] 中心 (170,523) / 多人游戏 [342,832,204,57] 中心 (444,860)
#   · ``tools/frames/lord_mode_select.png``（1080p 原始帧，÷1.5 换算到 720）：
#       单人游戏 [117,746,276,78]→[78,497,184,52] / 多人游戏 [516,1258,276,76]→[344,839,184,51]
#   ⇒ 单人卡在**左上**、多人卡在**右下**；两卡中心 **Δy≈343px**（单人更高）、Δx≈+267。
#   ⇒ 判据取 Δy ≥ 200 而不是「只要在下面就行」：200 是实测 343 的 ~58%，容忍 1080/720 机型抖动，
#     又远大于任何 OCR 框高（52）——「差不多同高」的帧一律不放行。
#
# ★为什么不写成绝对落点★：模式页会随窗口/机型缩放（1080 vs 720 的框宽 276 vs 184 = 正好 1.5）；
#   相对判据在三帧上都成立，绝对坐标只在其中一种分辨率上成立。
SOLO_PATTERNS: tuple[str, ...] = (r"^单人游戏$",)
MULTI_PATTERNS: tuple[str, ...] = (r"^多人游戏$",)
#: 两卡标题框的实测几何（720 空间；★只给守卫/复核做绝对锚点，pipeline 里用相对判据★）。
#: 取 ``leg_c2..._wuchong_mode.png`` 那一帧的原值；另两帧逐项差 ≤2px（见上面的三帧对账）。
MODE_SOLO_BOX: tuple[int, int, int, int] = (78, 497, 184, 52)
MODE_MULTI_BOX: tuple[int, int, int, int] = (345, 840, 184, 52)
#: 单人卡中心必须比多人卡中心高的**最小**像素（实测 343；取 200 = 留 42% 余量）。
MODE_MIN_SOLO_ABOVE_MULTI_DY = 200
#: 相对位置判据（``wuchong_act`` 的 ``above`` 参数）—— **单人卡专用**，多人卡不设
#: （多人卡靠自己的整串 + ``WuchongMultiText`` 识别门；「必须在下面」对它是同一件事的镜像，
#:  但本票只要求单人这一侧，多一步就在最热的路径上加一次 OCR 判断，不值）。
SOLO_ABOVE: dict = {"what": list(MULTI_PATTERNS), "min_dy": MODE_MIN_SOLO_ABOVE_MULTI_DY}


@dataclass(frozen=True)
class SceneButtons:
    """五重决战的固定落点（720 空间；★共斗开房坐标为 kernel 真机/占位，待复核★）。

    ``lord`` 主城「领主战」；``mode_solo`` / ``mode_multi`` 模式选择页；
    ``recruit_open`` 房间页「招募」；``recruit_start`` 招募方式弹窗「开始招募」；
    ``challenge`` 编队页「挑战」。
    （★二批：``battle_pause`` 已删除 —— 战斗内不再切自动，不再需要暂停屏落点。★）
    """

    lord: tuple[int, int]
    mode_solo: tuple[int, int]
    mode_multi: tuple[int, int]
    recruit_open: tuple[int, int]
    recruit_start: tuple[int, int]
    challenge: tuple[int, int]


WUCHONG_BUTTONS = SceneButtons(
    lord=(608, 1136),
    mode_solo=(360, 540),
    mode_multi=(437, 866),
    recruit_open=(388, 828),
    recruit_start=(522, 919),
    challenge=(360, 1073),
)


# ---------------------------------------------------------------------------
# ② 开关（自动 / 自动续战）的几何量 + 判据（运维：「检测位置 = 编队界面」；
#    ★二批：自动的切换移到战斗外，且不得写死坐标★）
# ---------------------------------------------------------------------------
# ★「自动」按钮一律【定位】，绝不写死坐标★（运维裁决②）：
#   数据/机制在 :mod:`scene.auto_switch` + ``agent/auto_switch_impl``（模板优先 / OCR 整串
#   ``^自动$`` 兜底）；本文件不再为「自动」保留任何绝对探针/落点。
#   本类只保留**「自动续战」**这一组固定几何（它不被当作按钮到处点：只在「确保关」时读一次）。
#   【标定来源】2026-10-11/14 真机 16384 + 帧：编队页 标签 (17,1062,79,24) / probe (20,1102,78,1133)。
AUTO_ON_RATIO = 0.15


@dataclass(frozen=True)
class SwitchGeometry:
    """「自动续战」开关的几何量（多个 pattern 数据）。自动按钮已改由定位处理，不在此表。"""

    cont_probes: tuple[tuple[int, int, int, int], ...]
    cont_toggles: tuple[tuple[int, int], ...]
    on_ratio: float


WUCHONG_SWITCHES = SwitchGeometry(
    cont_probes=((20, 1102, 78, 1133),),
    cont_toggles=((49, 1117),),
    on_ratio=AUTO_ON_RATIO,
)

# 开关的「which」取值（action 参数）：auto=自动；cont=自动续战。
# （``pause_auto`` 已删除 —— 战斗内不再切换自动，见运维裁决②。）
SWITCH_AUTO = "auto"
SWITCH_CONT = "cont"
SWITCH_WHICH_VALUES: tuple[str, ...] = (SWITCH_AUTO, SWITCH_CONT)


# ---------------------------------------------------------------------------
# ②b 共斗房间「有界重试 + 有界收工」（P0 真机缺陷修复：coop-fix2）
#
# 真机 127.0.0.1:16384 / 06:34 的缺陷（独立审计）：
#   1. ``WuchongRecruitOpen.next`` 把 ``WuchongTeamAutoSet`` 排在 ``WuchongRecruitStart``
#      **之前** —— 招募方式弹窗一出现，流程就选「自动」开关，点识别框中心落在**弹窗背板**上
#      → 招募弹窗被自己点掉，``WuchongRecruitStart`` 全程 0 命中；
#   2. ``WuchongRoomWait.next`` **没有回「招募 / 开始招募」的边** —— 落入房间后死等，
#      一直到超时被杀。
#
# 落地（两条）：
#   · 弹窗在屏时先走「开始招募」：``WuchongRecruitOpen.next`` 把 ``WuchongRecruitStart``
#     提到 ``WuchongTeamAutoSet`` 之前，**并且**机制侧开关动作见到弹窗画面一律**拒绝点击**
#     （点在弹窗背板上 = 点错东西，见 :data:`MODAL_BLOCK_STATES`）；
#   · 房间有出路：``WuchongRoomWait.next`` 有**有界**重试招募（``WuchongRecruitOpen``
#     带 ``max_hit``）；房间停留过久仍未开战则由 ``wuchong_giveup`` **有理由地**收工
#     （``room_wait_sec``），绝不无限死等。
# ---------------------------------------------------------------------------
#: 「招募」按钮在共斗房内允许被点的**总次数**（首次 + 有界重试），落到
#: ``WuchongRecruitOpen.max_hit``。用尽后不再重开招募弹窗（房间转入有界收工）。
#: ★#79★ 历史常量，**已不再用于 pipeline 的 max_hit**：MAA 的 `max_hit` 是**整任务**共享计数，
#:   真机（18:33:45 / 18:45:44 / 19:06:16 三次「招募」后）第 4 间房起 `WuchongRecruitOpen` 被静默跳过 →
#:   房里再也招不到人 → 干等 ``ROOM_WAIT_SEC`` 收工（运维看到的就是「打几把画面卡死」）。
#:   现在的界 = 时间闩锁 ``recruit_open``（≤1 次/LATCH_RETRY_S）+ ``recruit_state: not_started`` 自限
#:   + ``ROOM_WAIT_SEC``。常量保留只为守卫 pin（配置漂移）与历史语义，**别再加回 pipeline**。
RECRUIT_OPEN_MAX_HIT = 3
#: ★#87★ 「当前不满足出战条件」弹窗（点【挑战】后游戏拒绝出场）。真机帧
#: ``debug/wc448_popup_ready.png`` 的 pipeline OCR：
#:   `当前不满足出战条件。` / `请检查关卡开放状态、入场门票和队伍限制。` /
#:   `幻想连战专属装备及魂珠仅限幻想连战使用，` / `挑战其他关卡前请先卸下或更换。` / `OK`
#: ★判据取**整句**，绝不用「不满足」这种宽串★（别处也可能出现那三个字）。
WUCHONG_NO_ENTRY = "wuchong_no_entry"
NO_ENTRY_TEXT = "当前不满足出战条件"
#: 共斗房「停留多久仍未开战 / 人齐」→ 有理由收工（``wuchong_giveup`` 的 ``room_wait_sec``）。
ROOM_WAIT_SEC = 300
#: 共斗房**序列**状态（都算「还在房间里」→ 停留时钟**不清零**）。
ROOM_SEQUENCE_STATES: tuple[str, ...] = ("wuchong_room", "wuchong_recruit_dialog")
#: 真正**离开**共斗房的状态（此时把停留时钟清零；否则「人齐开战」会被误判成停留超时）。
ROOM_LEAVE_STATES: tuple[str, ...] = (
    "wuchong_team",        # 人齐 → 编队页
    "wuchong_battle",      # 开战
    "wuchong_settle",      # 结算
    "wuchong_mode",        # 退回模式选择
    "wuchong_detail",      # 退回详情
    "wuchong_lord_list",   # 退回列表
    "main_city",
    "activity",
    "relogin",
    "wuchong_level_required",
)
#: 出现这些画面时，开关动作（``wuchong_switch``）一律**拒绝点击** —— 点位会落在弹窗背板上
#: （真机 P0：招募方式弹窗被「自动」开关的定点点击点掉）。这是「绝不点在错的东西上」的落地。
MODAL_BLOCK_STATES: tuple[str, ...] = ("wuchong_recruit_dialog",)


# ---------------------------------------------------------------------------
# ②c ★手操引擎「关」时 WuchongBattle 绝不被选中★（P0：真机 07:15 空框空转 ×13）
#
# 真机缺陷（独立审计 .slim/worktrees/coop-fix/debug/maafw.log 07:15:02）：
#   ``WuchongBattle`` 的识别（``wuchong_state == wuchong_battle``）在**手操引擎关**时照样命中
#   → 动作收到**空识别框**（``box=[0,0,0,0]``，框架 WRN「custom action target rect is empty」），
#   且 ``manual=off`` → 引擎**故意不点任何东西** → 于是 ``WuchongBattle ×13`` 空转、没有一次点击
#   落地。审计序列：``WuchongBattle ×13 → WuchongBonusNo → … → WuchongGiveUp ×5 → WuchongBattle ×8``。
#
# 落地（三条）：
#   · raw 默认 ``WuchongBattle`` **关闭**（识别 = ``__NONE__``）—— 手操引擎关 ⇔ 结点不被选中，
#     绝不空转重选（选项层「自动」case 也是 ``__NONE__``，与此一致）；
#   · 「是否手操=手操」选项**显式开启**该结点（识别回到 ``wuchong_state``）并把动作
#     ``custom_action_param.manual = true`` —— 手动开关**确定性**来自选项，不依赖会话里
#     「自动开关真的被点下去」这个脆弱前提；
#   · 动作自己**只用场景几何**（:data:`WUCHONG_BATTLE` centre/flipper），**绝不用识别的空框**；
#     若被以 ``manual=off`` 直接调用，则**带原因停下**（不空转、不盲点）。
# ---------------------------------------------------------------------------
#: WuchongBattle 动作里「是否手操」的参数键；界面「手操」case 落此（确定性手动）。
BATTLE_MANUAL_FIELD = "manual"
#: raw 默认（未应用界面选项）时 ``WuchongBattle`` 的识别 —— **关闭**（安全中性：手操引擎关）。
BATTLE_DISABLED_EXPECTED: tuple[str, ...] = ("__NONE__",)


# ---------------------------------------------------------------------------
# ②d ★「打几次」= 打够 N 次就收工（本票）★ —— 数据声明
#
# 运维原话：「五重决战少了需要打的次数」。落地：GUI 选项「打几次」（``type=input``，字段
# ``次数``）覆盖 ``WuchongGiveUp.recognition`` 的 ``target_fights``；引擎（``agent/wuchong_impl``）
# 用**既有账本 + 既有收工机制**记「★每进入一场战斗（战斗 HUD 首次出现）= 打了一场★」
# （key = ``wuchong/fight/{n}``；★#74 修正规格 B2/D2★：计数点在**进入战斗**，不在结算页 ——
# 真机所有战斗都以 GAMEOVER/关卡失败收场、从不出现结算页，旧口径会让账本恒为 0，且
# 「打输后续关不算新的一次（同一场）」由 battle_had_continue 标记保证），
# 打够 N 次即由 ``wuchong_giveup`` 按同一理由收工（``StopTask`` + 写 ``wuchong/run/completed``）。
# ``target_fights <= 0`` = 不限制（保持旧行为：一直刷到异常兜底）；GUI 选项默认 1 = 打一次。
# ★不新造并行机制★：计数落既有 ``agent/progress`` 账本，收工走既有 ``WuchongGiveUp``。
# ---------------------------------------------------------------------------
#: 账本里「本场景打过的场次」前缀（key = ``wuchong/fight/{n}``）。
FIGHT_LEDGER_PREFIX = "wuchong/fight"
#: 「打几次」在 ``wuchong_giveup`` 识别参数里的字段名（GUI「打几次」-> 这里）。
TARGET_FIGHTS_FIELD = "target_fights"
#: 「打几次」缺省（0 = 不限制，保持旧行为；GUI 选项默认 1）。
TARGET_FIGHTS_DEFAULT = 0
#: GUI 上「打几次」的选项名（供守卫/派生引用）。
#: ★为何带「五重」前缀（本票真机外修复）★：interface.json 的 ``option`` 是**全局命名空间**
#: （按名字索引；``tools/interface_options.load_interface`` 与 MFAAvalonia 都按名取块）。
#: 早先本选项名写作「打几次」，与「自动刷副本」任务既有的同名选项**撞键** ——
#: 同名 JSON 键在 ``json.loads`` / ``jsonc.load`` 下**后者覆盖前者**，于是
#: 「自动刷副本」的「打几次」（写 ``SpecialFightTargetRow.max_hit``）被本选项整体顶掉，
#: 该功能静默失效（``install/interface.json`` 的落盘副本只剩 WuchongGiveUp 一份，可复核）。
#: 故本选项名 = 「五重打几次」（GUI 可见 label 仍是「打几次」），既不撞键、命名与
#: 其它「…几次」次数项一致。
TARGET_FIGHTS_OPTION = "五重打几次"


# ---------------------------------------------------------------------------
# ②e ★「开始类」闩锁 = 【重试窗口】，绝不是「永不再点」★ —— 数据声明（本票）
#
# 运维原话：「五重进去没打几分钟就结束了」/「少了需要打的次数」。真源：``WuchongActAction``
#   （``wuchong_act``）对「挑战（``battle_start``）/ 开始招募（``recruit_start``）」用一次性闩锁
#   防连点。**但闩锁必须是有界重试窗口**：
#     · 「永不再点」→ 第一局点过「开始招募 / 挑战」后，闩锁对本**任务进程**永久为真。单人链路
#       每局都要在编队页重新点「挑战」（``WuchongSettleContinue.next`` 首项 = ``WuchongTeamChallenge``，
#       见 ⑥）→ 闩锁一律挡下 → **只打得动一局**，随后在编队页空转 → 有界收工
#       （= 运维的「记一次就收工 / 没打几分钟就结束」；即本票缺陷 1 与 3 的同一根因）。
#       历史同类回归：``02c3630``（弹窗关不掉时「永不再点」→ 死循环）。
#     · 落地：点击成功后记**时间戳**；``LATCH_RETRY_S`` 秒内不重复点（防连击）；超过窗口仍停在
#       同一个按钮/弹窗 = 上次没点中 → **允许重试**。换任务（新 task_id）时时间戳清零，绝不残留。
#   机制在 ``agent/wuchong_impl.py``（``WuchongActAction``，同口径常量 ``LATCH_RETRY_S``）；
#   守卫 ``wuchong-latch-retries`` 把守「窗口内不连点 / 超窗可重试 / 换任务清零」。
# ---------------------------------------------------------------------------
#: 「开始类」闩锁（挑战 / 开始招募）的**重试窗口**（秒）。
#: ★#113★ 服务端断连（`暂时无法连接` / `客户端接入提示`）的重试冷却秒数。
#: 为什么与 ``LATCH_RETRY_S`` 分开：闩锁是「防连击」（几秒），这里是「别打服务器」（十秒级）。
#: 真机证据：2026-10-18 夜 A/B 两个账号两台设备同时被服务端拒（本地 ping 0% 丢包）。
SERVER_RETRY_COOLDOWN_S = 10.0
LATCH_RETRY_S = 8.0
#: 受**重试窗口**约束的闩锁名（与 ``WuchongActAction._LATCHES`` 同源；供守卫 / 派生引用）。
LATCH_RETRY_NAMES: tuple[str, ...] = (
    "recruit_start",
    "battle_start",
    # ★#79★ 这两个是替掉「任务级 max_hit」用的（见 ``RECRUIT_OPEN_MAX_HIT`` 的注释）：
    #   招募 / stale 编队页「返回」都可能在一局里反复发生，而 `max_hit` 是**整任务**共享计数。
    "recruit_open",
    "stale_team",
    # ★#83★ 单人模式的房间出口（点【返回】离开遗留共斗房）。
    "room_leave",
)

# ---------------------------------------------------------------------------
# ②e' ★#116★ 共斗房「挑战」：**狂点**形态（真机 7 连点）→ 时间闩 + 单点
#
# 真机现场（2026-10-18 07:18:14–07:18:45，`debug/wuchong_agent.log` + `debug/maafw...07.20.11.63.log`）：
#   ```
#   07:18:14 state=wuchong_room 点击 '挑战' @720(338,919)   → [!] 校验未通过：state=loading
#   07:18:19 …（同上）
#   07:18:24 / 07:18:29 / 07:18:35 / 07:18:40 / 07:18:45 … 共 **7 次**
#   ```
#   ★机制核对（本票第 4 问，读码 + 数框架日志得出）★：那 7 次**不是**一个 ``run()`` 里的循环 ——
#   框架日志里 ``node_name=WuchongCoopChallenge`` 的 ``CustomAction::run ... | enter`` 也是 **7 行**
#   （07:18:14/19/24/29/35/40/45），一次 enter 一次点击。``WuchongActAction.run`` 内部是
#   「抓帧 → 定位 → **点一次** → 等 wait_ms → 抓帧 → 校验 → return」，**没有任何重试循环**。
#   ⇒ 狂点是**节点被反复命中**造成的（房间页下一轮又把 ``WuchongCoopChallenge`` 排在候选最前），
#     所以修法只能是**跨命中**的时间闩（本段），而不是「动作内部改成只点一次」（它本来就是只点一次）。
#
# 为什么窗口**不能**取票面建议的 2.5–3s（实测推翻建议值）：
#   · 房间页一轮的重复周期实测 **≈5.2s**（14→19→24→29→35→40→45，post_delay 600 + wait 700 + OCR）；
#   · 闩锁判据是``now - 上次点击 < 窗口 ⇒ 不点``。窗口 3s < 周期 5.2s ⇒ **每一轮都放行** ⇒
#     闩锁形同虚设（绿着但不改变真机行为 = 又一处「假安全」）；
#   · 窗口 8s = 实测周期的 1.5 倍（留 OCR 抖动余量），真机行为变成「≤1 次/8s」；
#     代价 = 人齐那一刻最多多等 8s（房间的总容忍是 ``ROOM_WAIT_SEC``=300s，可忽略）。
#   ⇒ 值 = :data:`COOP_CHALLENGE_LATCH_S`（8.0），守卫 hooks_116 钉住下限 6s（必须 > 实测周期）。
#
# 为什么**不用**一次性的「点了就永不再点」（旧 ``#83`` 形态的顾虑）：
#   「挑战」在人齐前是灰的（点了只会闪一下 loading 再回房）。一次性闩锁会被**第一次过早点击**烧掉，
#   真·人齐时反而点不了 —— 这正是 ②e 的「重试窗口」语义要解决的：超窗仍停在同一个按钮 = 上次没点中
#   → 允许重试（每窗口一次，有界）。这不是「每回合有限次」，也不许用任务级 ``max_hit``（#79）。
# ---------------------------------------------------------------------------
#: 共斗房「挑战」的时间闩名（与 ``WuchongActAction._LATCHES`` 同源；★新闩，不复用 battle_start★
#: —— 编队页的「挑战」与共斗房的「挑战」是**两颗不同的按钮**，共享一个时间戳会互相压制）。
COOP_CHALLENGE_LATCH = "coop_challenge"
#: 该闩的窗口（秒）。★必须 > 房间页一轮的重复周期（实测 5.2s）★，否则闩锁不生效（见上面的推导）。
COOP_CHALLENGE_LATCH_S = 8.0


# ---------------------------------------------------------------------------
# ②f ★GAMEOVER 续关（不是放弃）★ —— 数据声明（本票 #72）
#
# 运维原话（真机现场）：「他现在问我要不要续关，这个逻辑你要 handle 的，需要点**是**的」。
# 规格 ``docs/spec/wuchong-spec.md`` B3 / B6 / D3 / D6：
#   · 战斗失败进 GAMEOVER（``GAMEOVER`` / ``是否续关?`` / ``使用星导石 ×50`` / ``放弃`` | ``续关``）
#     → **点「续关」**（不是「放弃」）；续关**次数由 user 指定**（B3 / D6）。
#   · ★此屏的 ``使用星导石 ×50`` 是【续关费】，与 B4 的「体力不足 → 恢复体力」**不是同一屏**★
#     （D6）：两套节点必须**互不误命中**。体力恢复节点另要求 ``请选择要使用的道具/体力不足``，
#     且本屏的 ``使用星导石×50`` 在 y≈875（真机 [275,864,171,23]），位于体力星导石行 ROI
#     y 900-980 **之上** → 互不误命中（守卫 hooks_72 的 ``gameover-not-stamina-and-vice-versa``）。
#   · ★不改 ``agent/wuchong_impl.classify()``★：GAMEOVER 页底部**仍画战斗 HUD**（时间/分数），
#     五重 ``classify`` 本就判 ``wuchong_battle``；续关由挂在**每个流程节点**的异常前缀
#     （:data:`FLOW_EXCEPTIONS`）里的识别节点处理（不是新页面分类）。
# 落地（★不新造并行机制★，与 ②d「打几次」同口径）：
#   · 公共节点 ``PubGameOverContinueBtn``（OCR 只认右侧【续关】）+ ``PubGameOverContinue``
#     （``And(横幅 + 「是否续关?」+ 续关按钮)`` ``box_index=2`` → ``Click target:true``，
#     点**识别框中心**、零死坐标；公共定义在 ``common.json``，各链以 ``[JumpBack]`` 引用）；
#   · 上限闸 :data:`CONTINUE_GUARD_NODE`（``wuchong.json``，``action=StopTask``）：续关次数用尽
#     → **带原因收工**（绝不空转）；
#   · 引擎（``agent/wuchong_impl``）用**既有账本 + 既有收工机制**记「已续关第 N 次」
#     （key = ``wuchong/continue/{n}``，跨重开恢复）。
# ★本链**不再引用** #38 的「放弃」节点★（``[JumpBack]PubGameOverGiveUp`` /
#   ``[JumpBack]PubGameOverConfirm``）：五重在 GAMEOVER 屏点续关，放弃不再出现在本链。
# ---------------------------------------------------------------------------
#: GAMEOVER 页横幅（= ``side_impl.GAMEOVER_TITLE``；公共节点 ``PubGameOverTitle`` 的判据）。
CONTINUE_TITLE_TEXT = "GAMEOVER"
#: 续关询问「是否续关?」（= ``side_impl.GAMEOVER_PROMPT``；公共节点 ``PubGameOverPrompt`` 的判据）。
CONTINUE_PROMPT_TEXT = "是否续关"
#: 右侧【续关】按钮的两端锚定串（公共节点 ``PubGameOverContinueBtn`` 的判据）。
CONTINUE_BTN_TEXT = "^续关$"
#: 【续关】按钮所在 ROI（720 空间）：圈定右半按钮，避开左侧【放弃】[180,1043,66,39]。
CONTINUE_BTN_ROI = (400, 1000, 320, 110)
#: 公共叶子 / 动作节点名（定义在 ``common.json``）。
CONTINUE_BTN_NODE = "PubGameOverContinueBtn"
CONTINUE_NODE = "PubGameOverContinue"
#: 上限闸节点名（定义在 ``wuchong.json``，``action=StopTask``）。
CONTINUE_GUARD_NODE = "WuchongContinueGuard"
#: 账本里「本场景已续关次数」前缀（key = ``wuchong/continue/{n}``）。
CONTINUE_LEDGER_PREFIX = "wuchong/continue"
#: 「续关几次」在 ``WuchongContinueGuard`` 识别参数里的字段名（GUI「续关几次」-> 这里）。
TARGET_CONTINUES_FIELD = "target_continues"
#: 「续关几次」缺省（0 = 不限制，保持「续关无限」；GUI 选项默认 0）。
TARGET_CONTINUES_DEFAULT = 0
#: GUI 上「续关几次」的选项名。★带「五重」前缀（避撞键，同 ②d）★：interface.json 的 ``option``
#: 是**全局命名空间**（按名索引）；裸名会与既有同名选项撞键（后者覆盖前者）。
TARGET_CONTINUES_OPTION = "五重续关几次"
#: ★#72 有界卡住等待★：**同一个 GAMEOVER 屏**持续这么久仍未推进 → 判定「续关点击无效 /
#: 星导石不足」（点了续关但画面没变、或又弹回同一屏）→ **带原因收工**（``WuchongContinueGuard``）。
#: 为什么必须有界（先例 :data:`ROOM_WAIT_SEC` / ``RECRUIT_OPEN_MAX_HIT``）：guard 的**每 episode
#: 去抖**让「点了但没生效」时**上限永不触发** —— 若不设这道界，``[JumpBack]PubGameOverContinue``
#: 会每轮重敲（重敲续关 = 反复尝试花星导石），直到**通用**的 ``WuchongGiveUp`` 900s 无进展兜底
#: 才停 —— 这正是运维要的「用完 → 带原因收工，**不空转**」所禁止的。60s ≫ 一帧排队 + 点击
#: post_delay（2s），足以区分「真的卡住」与「正常一帧延迟」。
CONTINUE_STUCK_SEC = 60.0


def continue_refs() -> tuple[str, ...]:
    """五重 ``FLOW_EXCEPTIONS`` 里注入的**续关链引用**（有序，``[JumpBack]`` 形式）。

    ★order 承重★：``guard``（:data:`CONTINUE_GUARD_NODE`）**必须在前** —— 上限用尽时它
    （``StopTask``）先判定收工，才轮得到 ``[JumpBack]PubGameOverContinue`` 去点续关。
    若把点击放在前，超限的那一帧会先点一次续关（多花一颗星导石）。
    """
    return (CONTINUE_GUARD_NODE, f"[JumpBack]{CONTINUE_NODE}")


# ---------------------------------------------------------------------------
# ②g ★「战斗页关自动」★ —— 数据声明（本票 #71 / spec B1/D4）
#   （合并说明：#72 落地后原「②f」顺延为「②g」；本段与 ②f 的续关链互不相干。）
#
# 运维裁决（spec B1/D4）：编队页关自动**不管用** —— 游戏会在进入战斗后又把它打开，所以手操时
#   必须**在战斗页**再关一次。落地：
#   · pipeline 新增节点 :data:`BATTLE_AUTO_NODE`（``WuchongBattleAutoOff``）—— 只在「是否手操=手操」
#     时被选中（raw 默认关，识别 = ``__NONE__``，与 ``WuchongBattle`` 同形）；
#   · ★只关不开★（``on=false``）、★判不出就不动★（``on_unknown=""``，绝不盲点）；
#   · ★一场战斗只尝试一次★：闩锁在 **agent 侧**（key = :data:`BATTLE_AUTO_ONCE_KEY`），
#     故本节点**不设 max_hit** —— 否则会在整局任务里用尽 → 第二局就不会再关自动了。
# ---------------------------------------------------------------------------
#: 「战斗页关自动」节点名（pipeline 与界面 override 共用）。
BATTLE_AUTO_NODE = "WuchongBattleAutoOff"
#: 该节点的作用域标记（战斗页）。
BATTLE_AUTO_SCOPE = "battle"
#: 一场战斗只尝试一次的闩锁键（agent 侧，跨重开恢复）。
BATTLE_AUTO_ONCE_KEY = "battle_auto_off_tried"


# ---------------------------------------------------------------------------
# ②h ★#114★ 三种断连文案 + 有界重启客户端（真机 R1，docs/spec/runner-delivery.md）
#
# 真机实测（2026-10-18 夜，A/B 两账号两设备**同时**被服务端拒；本地 ping 0% 丢包）：
#   长跑中客户端会断开，现场只有三种文案；点【重试】**无效**，`am force-stop` + 重新拉起
#   客户端才能恢复（重启后 ≈40s 回到「登录成功」→【继续游戏】→ 主城）：
#     · F2032      ：未能连网 / 请确认 / (No.F2032) + 【OK】           帧 net_error_f2032.png
#     · A4050      ：发生意想不到的错误 / 回到登录界面 (No.A4050) + 【OK】 帧 session_error_a4050.png
#     · 暂时无法连接：登录页 /【重新连接】/【重试】                       帧 server_unreachable.png
#   ⇒ 三种文案的**判据只允许一份**：``wuchong_impl.net_disconnect_kinds()`` 按
#   :data:`NET_DISCONNECT_TEXTS` 统一切分；pipeline 的 ``wuchong_net`` custom recognition 是
#   唯一入口（mode=retry / restart），三个断连节点**都不再各写一份 OCR expected 列表**。
#
# 有界重启策略（★本段是真源；agent 侧 ``_Snapshot`` 冻结同值，hooks_114 钉死漂移★）：
#   · 单次断连：先按既有 :data:`SERVER_RETRY_COOLDOWN_S`(10s) 冷却**重试一次** —— 冷却窗口内
#     ``mode=retry`` 命中（动作点【OK】/【重新连接】），窗口外 retry **不再命中**；
#   · 仍停在同一断连屏 ⇒ ``WuchongNetGuard``（mode=restart）**重启客户端**（第 1..3 次）；
#   · 重启动作复用已注册的 :data:`NET_RESTART_ACTION`（设备无关的 am force-stop → 重新拉起），
#     等待 :data:`RELAUNCH_WAIT_SEC`(45s)；重启后的「继续游戏 / 点击开始 / 有正在进行中的关卡」
#     由**既有** ``[JumpBack]PubLoginContinue`` / ``[JumpBack]PubTitleStart`` /
#     ``WuchongResumeQuest`` 接回（绝不另造一套、绝不自己乱点）；
#   · 上限 :data:`NET_RESTART_LIMIT`(3 次/任务)：第 4 次仍断连 ⇒ **既有** ``WuchongGiveUp``
#     带原因收工（:data:`NET_RESTART_EXHAUSTED_REASON`），绝不无限重启；
#   · 计数在 ``agent/wuchong_impl._SESSION``（换 task_id 清零），不落账本（重启次数是任务内状态）。
# ---------------------------------------------------------------------------
NET_DISCONNECT_F2032 = "F2032"
NET_DISCONNECT_A4050 = "A4050"
NET_DISCONNECT_UNREACHABLE = "UNREACHABLE"
NET_DISCONNECT_KINDS: tuple[str, ...] = (
    NET_DISCONNECT_F2032,
    NET_DISCONNECT_A4050,
    NET_DISCONNECT_UNREACHABLE,
)
#: 每种断连的**身份判据**（唯一一份；agent 与守卫都从这里派生）。
#: ★只取「离开这块弹窗就不可能出现」的锚点★：F2032 的「请确认」/ A4050 的「回到登录界面」
#: 都太通用（别的确认框也长这样），单独出现时**不许**判成断连 —— 身份靠标题句或错误码。
NET_DISCONNECT_TEXTS: dict[str, tuple[str, ...]] = {
    NET_DISCONNECT_F2032: ("未能连网", r"\(No\.F2032\)"),
    NET_DISCONNECT_A4050: ("发生意想不到的错误", r"\(No\.A4050\)"),
    NET_DISCONNECT_UNREACHABLE: (
        "暂时无法连接",
        "暂时连接不上服务器",
        "客户端接入提示",
        "连接暂时不可用",
    ),
}
#: 日志/收工原因里的可读名（三种必须互不相同）。
NET_DISCONNECT_LABELS: dict[str, str] = {
    NET_DISCONNECT_F2032: "F2032 掉线",
    NET_DISCONNECT_A4050: "A4050 会话错误",
    NET_DISCONNECT_UNREACHABLE: "暂时无法连接",
}
#: 收工原因里的三种文案简称（用户可见，逐字）。
NET_DISCONNECT_LABEL = "F2032/A4050/暂时无法连接"
#: 两种错误码弹窗共用一颗【OK】（同位置同文案）；登录页用【重新连接】/【重试】。
NET_ERROR_OK_KINDS: tuple[str, ...] = (NET_DISCONNECT_F2032, NET_DISCONNECT_A4050)
NET_RECONNECT_KINDS: tuple[str, ...] = (NET_DISCONNECT_UNREACHABLE,)
#: 重启次数上限（次/任务）。超过 ⇒ WuchongGiveUp 带原因收工。
NET_RESTART_LIMIT = 3
#: 重启后等待客户端回到可识别界面的秒数（真机实测重启后 ≈40s 回到「登录成功」）。
RELAUNCH_WAIT_SEC = 45.0
#: 超限收工原因（``{n}`` = 已重启次数；用户可见）。
NET_RESTART_EXHAUSTED_REASON = (
    "客户端重启 {n} 次仍连不上服务器（F2032/A4050/暂时无法连接）—— 带原因收工"
)
#: 重启动作（已在 ``agent/my_action.py`` 注册；★不新增 custom 名★）。
NET_RESTART_ACTION = "restart_game"
#: 承载重启的**既有**异常节点名（#114 起语义 = 有界重启；名字沿用，避免动 #103 的接口层投影）。
NET_RESTART_NODE = "WuchongNetGuard"
#: 「有正在进行中的关卡 / 是否继续关卡？」的既有识别文案（``WuchongResumeQuest`` 的判据；
#: 重启后必须经它接回本场，不许直接点屏幕乱点）。
RESUME_QUEST_TEXTS: tuple[str, ...] = ("正在进行中的关卡", "^是否继续关卡$")


# ---------------------------------------------------------------------------
# ③ 手操战斗几何量（运维：「进入挑战后若手动开启，需要全程点板子 + 放技能」）
# ---------------------------------------------------------------------------
# ★坐标 720★（kernel 真机A 单人局校准：起点 (360,600)、距离 160 可触发技能；弹板 (360,1067)）。
@dataclass(frozen=True)
class BattleGeometry:
    center: tuple[int, int]      # 技能滑动起点
    swipe_dist: int              # 滑动距离（技能1左/技能2上/技能3右）
    flipper: tuple[int, int]     # 弹板点
    swipe_ms: int                # 单次滑动时长


WUCHONG_BATTLE = BattleGeometry(center=(360, 600), swipe_dist=160, flipper=(360, 1067), swipe_ms=300)


# ---------------------------------------------------------------------------
# ③b ★节拍契约（#78）★ —— 别让「延时」把整条链拖成 20s/次
#
# 运维质疑（2026-10-17，逐字）：「动作内狂点 这是干啥的啊，我觉得这个要么是你**延时设计太大了**，
#   要么就是**一直没 hit 到期望的内容**。」→ 对。#77 的狂点是把症结绕过去；本段是真因与修法。
#
# 真机实测（MaaFramework 自己的 Node 事件日志 `debug/maafw*.log`）：
#   · 单次识别 **0.001-0.013s**，`OcrTask` avg 0.107s（框架 `prefetch_batch_ocr` 已合并一批候选的 OCR）；
#     一次「扫完 25 个候选」≈ **0.5s** —— 识别一点都不慢；
#   · 但 `WuchongSettleContinue` 的**真实重复周期 = 12.3-12.4s**（连续 15 次），
#     12s 全花在 ``timeout: 12000`` 的**空转重试**上：`NextList.Failed` → +0.77s 再扫 → 全不中 → …
#     直到 timeout 到了才 `on_error: WuchongEntry`（时间线 03:38:41.663 → 03:38:53.678）；
#   · `WuchongRoomWait` 周期 **4.5-5.5s** = 自身 ``post_delay: 3500`` → 人齐后要等它下一轮才看见；
#   · `WuchongCoopChallenge`：``post_delay: 12000`` **且** ``timeout: 12000`` ⇒ 一次尝试 ≈20s
#     （与运维日志 18:33:59 → 18:34:19 → 18:34:38 完全对上）。
#   ⇒ 62s 结算 / 63s 人齐→开战，是这两个旋钮直接乘出来的，不是「点得不够狠」。
#
# 契约（守卫 `tools/contract_hooks/hooks_78.py` 把守）：
#   · 每个流程节点 ``timeout`` ≤ :data:`FLOW_TIMEOUT_MS`（默认 3000）：页面加载 ≤2s 够用；
#     空转最多代 3s，而枢纽本身 ~1s 一轮会立刻重派（``WuchongWait.post_delay`` 400ms）；
#   · 每个流程节点 ``post_delay`` ≤ :data:`FLOW_POST_DELAY_MS`（默认 1000）；
#   · `wuchong_act` 的 ``wait_ms`` = :data:`ACT_WAIT_MS`（700）：点完立刻校验，没推进交给下一轮；
#   · ``expect`` 里**不许出现 ``loading``**（过渡帧不是「已到达」——灰「挑战」闪一下 loading 又回房）。
# ---------------------------------------------------------------------------
#: 流程节点 `timeout` 上限（ms）：空转重试最多代这么久，超时即 `on_error` 回枢纽。
FLOW_TIMEOUT_MS = 3000
#: 流程节点 `post_delay` 上限（ms）：动作后的固定等待。
FLOW_POST_DELAY_MS = 1000
#: `wuchong_act` 点击后等待（ms），仅在**校验前**等一次；页面没推进就交给下一轮。
ACT_WAIT_MS = 700
#: 战斗节点不参与上面的上限（它的动作本身就是长阻塞，`post_delay` 300ms）。
FLOW_DELAY_EXEMPT_NODES: tuple[str, ...] = ("WuchongBattle",)
#: `expect` 里**不许出现 `loading`** 的节点 —— 只有这几个的 `expect` 是在断言「**真的到达了目标页**」
#: （开战了 / 结算推进到房间或编队页）。导航类节点把 `loading` 当「点击已被接受」是可以的，
#: 但那几个推进类节点不行：灰「挑战」点下去会闪一下 loading 又回房（真机 18:34:02 现场）。
STRICT_EXPECT_NODES: tuple[str, ...] = (
    "WuchongCoopChallenge",
    "WuchongTeamChallenge",
    "WuchongSettleContinue",
    "WuchongSettleReturnRoom",
    "WuchongSettleDisband",
)


@dataclass(frozen=True)
class BattleParam:
    """一个**手操节奏参数**：custom_action_param 字段 + GUI 字段名 + 默认值 + 校验。

    运维：「点击的频率、弹板的频率和放技能的频率，都是可以通过参数控制的。这些都是要写在
    参数面板上的」。每个参数都在 GUI 上有一个可调字段（:data:`CADENCE_OPTION`），落点为
    ``WuchongBattle`` 节点的 ``custom_action_param[field]``。
    """

    field: str        # custom_action_param 的键
    option: str       # GUI 参数面板上的字段名（= 运维点名的那几个词）
    default: int
    minimum: int
    label: str
    msg: str


# ★#71★：手操不再有「点 N 秒就交出」——引擎持续点板/放技能直到【结算】或【关卡失败】才交还；
# 故「手操连点时长」这个截断旋钮已从参数表与 GUI 一并删除。
BATTLE_PARAMS: tuple[BattleParam, ...] = (
    BattleParam("flipper_gap_ms", "弹板间隔", 220, 20, "弹板间隔（毫秒）", "请输入正整数毫秒（≥20）"),
    BattleParam("skill_gap_ms", "技能间隔", 800, 0, "技能间隔（毫秒）", "请输入非负整数毫秒"),
    BattleParam("skill_every", "每几次弹板放技能", 6, 0, "每几次弹板放技能", "0=不放技能；否则正整数"),
    BattleParam("burst", "连点批量", 10, 1, "连点批量（每次原生连点几下）", "请输入正整数（≥1）"),
)
#: 手操节奏参数在 GUI 上落在同一个输入选项块（多字段），避免多个选项各自整体替换同一节点
#: 的 action 而互相覆盖（MAA 的 pipeline_override 整体替换 action 对象）。
CADENCE_OPTION = "手操节奏参数"
#: 判据采样**最小间隔**（毫秒）：引擎每隔这么多毫秒采一次画面判「是否到续关屏 / 结算页 /
#: 被推出战斗」。★#71★：从「每 N 次点击」改成「每 N 毫秒」—— 循环不再有次数上限。★2026-10-16
#: 运维裁决★：原来的 ``HUD_MISS_LIMIT``（连续几次看不到战斗 HUD 就停手）已删除 —— 手操引擎
#: **不再用战斗 HUD 做判据**（真机 HUD 会间歇性认不出 → 点板断续 + 虚计），认不出的帧一律继续点。
CHECK_MIN_GAP_MS = 2000
#: 心跳日志间隔（毫秒）：引擎按此周期打一条「手操仍在继续」的日志，作为「持续到结算/失败」
#: 的验收证据来源（证明没被固定时长截断）。
BATTLE_HEARTBEAT_MS = 60000
#: 日志 tag。
BATTLE_TAG = "wuchong_battle"


def cadence_defaults() -> dict:
    """手操节奏参数的**默认值**（字段 -> 值）；机制层缺任一项则拒绝动作（不猜坐标/节奏）。"""
    return {p.field: p.default for p in BATTLE_PARAMS}


def cadence_option_fields() -> tuple[str, ...]:
    """GUI 参数面板上暴露的字段名（= BATTLE_PARAMS 的 ``option``，顺序即面板顺序）。"""
    return tuple(p.option for p in BATTLE_PARAMS)


# ---------------------------------------------------------------------------
# ④ ★跨模式硬规则★ —— 只有「五重决战」允许手动（= 把自动关掉）
#
# 运维原话：「除了『五重决战』可以选择自动或手动以外，其他所有战斗都需要勾选『自动』。
#   这是一项确认项，如果你发现没有自动，就需要把它勾选上。检测位置：战斗中(左上暂停→
#   自动滑块) 以及 编队界面(自动按钮)。」
#
# 落地：本表是**唯一**真源；开关动作 ``wuchong_switch`` 通过 :func:`effective_auto_state`
# 把「想关自动」的意图夹到合法值 —— 非五重场景一律夹回 True（自动必开）。
# 守卫 ``wuchong-cross-mode-auto`` 证明这条规则（含「五重是唯一允许手动的场景」）。
# ---------------------------------------------------------------------------
MANUAL_SCENE = "wuchong"
#: 允许「自动 / 手动」二选一的场景 —— **只有五重决战**。
MANUAL_ALLOWED_SCENES: tuple[str, ...] = (MANUAL_SCENE,)
#: 其余一切战斗场景：自动是**必勾项**（默认开、检测到没开就开）。
AUTO_REQUIRED_SCENES: tuple[str, ...] = (
    "phantom",       # 幻想连战
    "abyss",         # 深渊连战EX
    "abyss_plain",   # 深渊连战
    "farm",          # 摇曳的迷宫
    "raid",          # 战阵之宴
    "special",       # 领主战/降临讨伐批量
    "maze",          # 迷宫（按域）
)


def manual_allowed(scene: str) -> bool:
    """该场景是否允许手动（= 允许把「自动」关掉）。**只有五重决战**。"""
    return scene in MANUAL_ALLOWED_SCENES


def auto_is_optional(scene: str) -> bool:
    """该场景的「自动」是否可选（可关）。等价于 :func:`manual_allowed`（手操 = 自动关）。"""
    return manual_allowed(scene)


def effective_auto_state(scene: str, want_on: bool) -> bool:
    """把「想让自动处于什么状态」夹到**合法值**：非五重场景一律 True（自动必开）。

    * ``scene == "wuchong"`` -> 尊重 ``want_on``（手动 = False 合法）；
    * 其它场景 -> 恒 ``True``（运维：其他所有战斗都需要勾选自动）。
    """
    return bool(want_on) if manual_allowed(scene) else True


def auto_rule_table() -> dict:
    """跨模式自动规则的**数据视图**（守卫/文档用）：{scene: 自动是否可选}。"""
    table = {s: True for s in MANUAL_ALLOWED_SCENES}
    table.update({s: False for s in AUTO_REQUIRED_SCENES})
    return table


# ---------------------------------------------------------------------------
# ⑤ 页面选取（复用 Phase 0 的 PageRuleRegistry：场景只**按名引用**全局判据，不新增页面）
#
# 五重链上走到的页面里，主城/领主战列表页/页签/详情/模式/加成弹窗/编队/战斗HUD/结算
# **都是全局注册表里已有的判据**（ADR-0003：判据全局唯一）；场景只在确有差异时声明
# **具名 Override**（owner + reason）——五重专有的是：
#   · 详情页必须是【五重决战 超级】的详情页（模板门控），绝不在别的领主战详情页上按「战斗」；
#   · 列表页的行用【五王连战】模板/串定位（行名，不是页面判据 → 放在 options/impl 落点）。
# ★本表不往全局 PAGE_RULES 塞任何页面★（否则 #37 的链页集会退化成各场景并集）。
# ---------------------------------------------------------------------------
SCENE_PAGES: tuple[str, ...] = (
    "主城",
    "领主战列表页",
    "领主战页签",
    "降临讨伐页签",
    "详情页",
    "模式选择页",
    "加成弹窗",
    "编队页",
    "战斗HUD",
    "结算页",
)

SCENE_OVERRIDES: tuple[Override, ...] = (
    Override(
        rule="详情页",
        recognition={
            "type": "And",
            "param": {
                "all_of": [
                    {"type": "OCR", "param": {"expected": ["推荐编成"]}},
                    {
                        "type": "TemplateMatch",
                        "param": {"template": [DETAIL_TEMPLATE], "threshold": TEMPLATE_THRESHOLD},
                    },
                ]
            },
        },
        owner=MANUAL_SCENE,
        reason="五重详情页必须是【五重决战 超级】的详情页（模板门控），绝不在别的领主战详情页上按「战斗」",
    ),
)


def register_wuchong(reg) -> SceneSelection:
    """把五重登记为一个场景（有序选取全局判据 + 具名覆盖）；供守卫/派生复用。

    刻意**不**在 ``scene.page_rules`` 的缺省注册表里登记（那是领主战族的缺省场景）；
    本函数让守卫用**新注册表**证明「五重只引用全局判据、不撑大全局表」。
    """
    return reg.register(MANUAL_SCENE, SCENE_PAGES, SCENE_OVERRIDES)


# ---------------------------------------------------------------------------
# ⑥ 流程链（运维：按真实游戏顺序走，异常挂在每个节点上）
# ---------------------------------------------------------------------------
FLOW_HUB = "WuchongEntry"
FLOW_HUB_TIMEOUT_MS = 15000


@dataclass(frozen=True)
class FlowStep:
    """一步流程：节点 + 本步的后继候选（有序）+ 前驱等待（ms）。"""

    node: str
    next: tuple[str, ...]
    timeout_ms: int | None = None
    jumpback: bool = False


#: 打断型异常 ++ 兜底（前缀注入到**每个**流程节点）。次序即注入顺序。
#: ★关键安全前提（kernel 已核实）★：首项 ``[JumpBack]PubReturnHome`` 的识别带页面范围判别叶
#: （#29），且 ``NotMainCity`` 的「任务已在跑」闸让它跑起来后不乱触发。
FLOW_EXCEPTIONS: tuple[str, ...] = (
    "[JumpBack]PubReturnHome",
    # ★「体力不足 → 星岛石恢复」★（scene/stamina.py 是真源，运维裁决「只用星岛石恢复」）：
    #   五重「挑战」消耗体力（≈35），不足时游戏弹「回复体力」弹窗 —— 用共享节点恢复
    #   （先点星导石行、再点确认框 OK）。插在归位之后、卡死看门狗（WuchongStall）之前：
    #   静止的弹窗帧不得被当成「卡死」重开游戏。
    *_stamina_recovery_refs(),
    # ★#107 真机（2026-10-18）★ 游戏掉网模态「未能连网 / 请确认 / No.F2032 / OK」：
    #   它是一块**静止**的模态，必须排在 ``WuchongStall`` 之前 —— 否则静止帧会被当成「卡死」
    #   去强杀重开游戏（反而更慢）。点 OK 重连即可（真机帧 tools/frames/net_error_f2032.png）。
    "WuchongNetError",
    # ★#107 真机（2026-10-18 01:3x）★ 崩溃/掉线重连后的「有正在进行中的关卡 / 是否继续关卡？」：
    #   点【继续】接回当前这场（保留进度），点【放弃】会白丢一张票。同样是静止模态，
    #   必须排在 ``WuchongStall`` 之前。证据帧 tools/frames/resume_quest_modal.png。
    "WuchongResumeQuest",
    # ★#107 真机（2026-10-18 03:0x）★ 登录页「星点启程 / 暂时无法连接 / [重新连接]」：
    #   同一时刻设备 ping 0% 丢包、游戏域名 11ms 可达 ⇒ **服务端断开**，不是本地网络。
    #   点【重新连接】但把间隔放长（服务端在限流时密集重试更糟），整体仍由 giveup 的
    #   no_progress_sec 兜底。证据帧 tools/frames/server_unreachable.png。
    "WuchongServerUnreachable",
    "WuchongGiveUp",
    "WuchongStall",
    "WuchongNetGuard",
    "WuchongRenav",
    "WuchongResume",
    # ★五重 在 GAMEOVER 屏点【续关】（#72；见 ②f）★：guard 在前 = 上限闸（cap 用尽即
    #   StopTask 带原因收工）；随后才是 [JumpBack]PubGameOverContinue（点识别的续关框中心）。
    #   ★「放弃」不再出现在本链★（原 #38 的 PubGameOverGiveUp / PubGameOverConfirm 已移除）。
    *continue_refs(),
    "[JumpBack]PubDailyPopup",
    "[JumpBack]WuchongBonusNo",
    "WuchongNetDisconnect",
    "[JumpBack]PubLoginContinue",
    "[JumpBack]PubTitleStart",
)

#: 流程步（按真实游戏顺序）。每步 ``next`` = 有序候选集（可能不存在的一步就一起列进去）。
FLOW_STEPS: tuple[FlowStep, ...] = (
    FlowStep("WuchongNavLord", ("WuchongNavJoss",), 8000),
    FlowStep("WuchongNavJoss", ("WuchongNavRow",), 8000),
    # 滚动找「五王连战」行（模板/OCR 定位，找不到就滚列表）。
    FlowStep("WuchongNavRow", ("WuchongScrollList", "WuchongDetailFight"), 8000),
    FlowStep("WuchongScrollList", ("WuchongNavRow",), 6000),
    FlowStep("WuchongDetailFight", ("WuchongModeSolo", "WuchongModeMulti"), 10000),
    # 模式页：单人 → 编队页；多人 → 共斗房间页（招募流程）。
    FlowStep(
        "WuchongModeSolo",
        ("WuchongTeamAutoSet", "WuchongTeamContSet", "WuchongTeamChallenge",
         "WuchongRoomWait", "WuchongBattle"),
        10000,
    ),
    FlowStep(
        "WuchongModeMulti",
        ("WuchongTeamAutoSet", "WuchongTeamContSet", "WuchongRecruitOpen",
         "WuchongRoomWait", "WuchongBattle"),
        10000,
    ),
    FlowStep(
        "WuchongRecruitOpen",
        # ★P0 修复（coop-fix2）★：招募方式弹窗在屏时**先**走「开始招募」，绝不先走「自动」开关。
        #   真机缺陷：``WuchongTeamAutoSet`` 在前 → 弹窗一出现就选它 → 点识别框中心落在弹窗背板上
        #   → 招募弹窗被自己点掉（``WuchongRecruitStart`` 0 命中）。顺序 + 机制侧拒点
        #   （MODAL_BLOCK_STATES）双重保证。
        ("WuchongRecruitStart", "WuchongTeamAutoSet", "WuchongTeamContSet", "WuchongRoomWait"),
        8000,
    ),
    FlowStep(
        "WuchongRecruitStart",
        ("WuchongTeamAutoSet", "WuchongTeamContSet", "WuchongRoomWait", "WuchongBattle"),
        8000,
    ),
    # ★coop-fix2 P0★ 共斗房「挑战」：共斗房的「挑战」在 720 中心 y≈929（灰→人齐转亮），
    #   与单人编队页的「挑战」（y≈1092）**不同位置**；单人的 WuchongTeamChallenge 的 roi
    #   y>980 永远点不到它。所以多人必须有自己的房间挑战节点 —— 否则**多人永远开不了战**
    #   （招募完只在房里等，直到有界收工）。★多人专用★（raw 默认关；「游戏模式=多人游戏」开启）。
    FlowStep(
        "WuchongCoopChallenge",
        ("WuchongTeamAutoSet", "WuchongTeamContSet", "WuchongRoomWait", "WuchongBattle"),
        12000,
    ),
    # ★coop-fix2 P0★ stale 单人编队页出口：多人模式下若落在**本轮从未进过共斗房**的编队页
    #   （上一轮单人留下的），点「返回」离开、重走模式选择 —— 绝不把它的「挑战」当成多人的
    #   （真机 07:45 leg_b：正是这样又开了一局单人）。★多人专用★（raw 默认关）。
    # ★#83★ 单人模式的房间出口（raw 默认关；「游戏模式=单人游戏」case 打开）：
    #   单人链路里出现共斗房 = 上一轮遗留 → 点【返回】离开，绝不干等 room_wait_sec。
    FlowStep("WuchongRoomLeave", ("WuchongEntry",), 8000),
    FlowStep("WuchongStaleTeam", ("WuchongEntry",), 8000),
    # 编队页/房间页开关（★二批：自动=定位 + 跨模式「其他战斗都要开自动」；自动续战=确保关★）。
    # 条件门控（auto_switch_state）：只在状态**不对**时命中 —— 因此放在房间里/编队页的候选最前
    # 也不会死循环，且能覆盖共斗房间页（「自动」在右上，位置与编队页不同）。
    FlowStep("WuchongTeamAutoSet", ("WuchongTeamContSet", "WuchongTeamChallenge", "WuchongRoomWait"), 8000),
    FlowStep("WuchongTeamContSet", ("WuchongTeamChallenge", "WuchongRoomWait"), 8000),
    FlowStep("WuchongTeamChallenge", ("WuchongBattle", "WuchongRoomWait"), 20000),
    # 房间页等人齐（自环继续等，人齐了进战斗）。★先兜一次自动（房间页「自动」在右上）★。
    # ★P0 修复（coop-fix2）★：先【有界重试招募】（``WuchongRecruitOpen`` 带 max_hit，
    #   仅在「未进行招募」时命中 → 重开招募弹窗 → 重走开始招募），再兜一次自动/续战，
    #   人齐 → 挑战；自环继续等；开战。★绝不无回「招募」的边死等★。
    #   （停留过久仍未开战 → ``wuchong_giveup`` 的 room_wait_sec 有理由收工，见 ②b。）
    FlowStep(
        "WuchongRoomWait",
        ("WuchongCoopChallenge", "WuchongRecruitOpen", "WuchongTeamAutoSet", "WuchongTeamContSet",
         "WuchongTeamChallenge", "WuchongRoomWait", "WuchongBattle"),
        20000,
    ),
    # ★本票 #71★：进战斗先「在战斗页关一次自动」（编队页关不住 —— 游戏会在战斗里又打开）。
    #   只在「是否手操=手操」时被选中（raw 默认关，识别 = __NONE__）；只关一次（闩锁在 agent 侧）。
    FlowStep(
        "WuchongBattleAutoOff",
        ("WuchongBattle", "WuchongSettleContinue", "WuchongSettleReturnRoom", "WuchongSettleDisband"),
        15000,
    ),
    # 战斗：手操引擎自环继续打；打完了走结算三去向。★战斗内不再切自动（二批删除 AutoGuard）★。
    # ★本票 #71★：自环之前先兜一次「战斗页关自动」（WuchongBattleAutoOff 排在本步 next 最前）。
    FlowStep(
        "WuchongBattle",
        ("WuchongBattleAutoOff", "WuchongBattle", "WuchongSettleContinue",
         "WuchongSettleReturnRoom", "WuchongSettleDisband"),
        15000,
    ),
    # ★#107 撤线★ 这里原本挂 `[JumpBack]PubQuestResult`（#78b 的「狂点 QUESTRESULT 横幅」）。
#   真机 00:01–00:10（单人）在结算页静默 9 分钟、零点击；单独 post WuchongSettleContinue 却能过
#   ⇒ 横幅每轮都命中且 next=[] 会弹栈重扫，把结算按钮的帧抢掉。它的收益从未量化（#78 的提速来自
#   砍 timeout/post_delay），代价是卡死 ⇒ 撤掉接线；节点本身留在 common.json 给别的场景用。
#   原文（保留供追溯）：
    #   （判据 `QUESTRE` 只在 common.json 一份）。★必须排在结算后继之后★：它每轮都会命中（横幅
    #   一直都在），排前面就会把结算按钮的帧抢掉（#27 的抢帧教训）—— 排最后才是「按钮能点就点、
    #   点不了就去点横幅加速动画」。
    FlowStep(
        "WuchongSettleContinue",
        ("WuchongTeamChallenge", "WuchongRoomWait", "WuchongBattle"),
        12000,
    ),
    FlowStep(
        "WuchongSettleReturnRoom",
        ("WuchongTeamChallenge", "WuchongRoomWait"),
        12000,
    ),
    FlowStep("WuchongSettleDisband", ("WuchongEntry",), 12000),
)

#: 链尾 = 唯一「永不失败」的 DirectHit 兜底（枢纽永不因全不命中而失败）。
FLOW_TAIL: tuple[str, ...] = ("WuchongWait",)
#: 已废弃节点（本线不落地）；仅为数据完备。
FLOW_OBSOLETE: tuple[str, ...] = ("WuchongReturnHome",)

# ---------------------------------------------------------------------------
# ⑦ ★#103 B 方案：场景接口层（MaaEnd 式 SceneManager）★ —— 20 项前缀 → 真后继 + 末位兜底
#
# 上位依据：``docs/spec/wuchong-scene-interface.md``（本段是它的**真源落地**）、
#   ``docs/spec/runner-delivery.md`` D5、``docs/research/pipeline-exception-patterns.md`` §3.2/§4.2。
# 投影：``assets/resource/pipeline/wuchong_scene.json``（3 个接口节点 + 7 个验证器 = 10）。
#
# ★实测口径（2026-10-18，别信文档里的旧数字）★：``wuchong.json`` 有 **66 个节点**
#   （#114 把 F2032/A4050/断连重试的 4 个 OCR 叶子收进共享判据后从 70 降到 66）；
#   ``FLOW_EXCEPTIONS`` = **20 项**（不是设计文档写的 16 —— #72 续关链 2 项 + #107 三个
#   掉线/重连节点把它撑大了；#114 只换判据，不增删异常项）；**带该前缀的节点 = 22 个** = 21 个
#   业务节点（``FLOW_STEPS``）+ 枢纽 ``WuchongEntry``（``hub_next()`` 以同一前缀开头）。
#   口径与复算过程见 ``hooks_103.print_stats()``（现算，不手抄）。
#   本段只动那 21 个**业务**节点；枢纽仍是「异常 + 全部流程节点 + 链尾」（它本来就是分派表）。
#
# ★两次修正（第二次是 2026-10-18 真机冒烟当场抓到的，R1b）★
#   · R1（#103 交付时）：验证器不能 next=[] —— 那是**任务流程终止**，命中即在第一步「完成」；
#     交回枢纽 ``WuchongEntry``（:data:`IN_NEXT`）。
#   · R1b（★真机 05:0x / A 现场★）：业务 next 只剩「验证器 + 跳转」**必然打转** ——
#     验证器在**当前页**上恒真（``WuchongInLordList`` 在列表页永远命中），于是业务 next[0]
#     直接命中 ⇒「点页签」那个动作**永不发生**（零点击）⇒ 回枢纽 ⇒ 枢纽按声明序又派回同一个
#     节点 ⇒ 2.5 分钟 11 次采样全是 ``wuchong_lord_list``、零进展、零战斗。
#     ⇒ 修法：业务 next **保留真后继（``FLOW_STEPS[i].next``）**，把 ``[JumpBack]SceneEnter``
#       放**末位**。进度由真后继提供（改造前的线性 next 正是这么活的），验证器退回本职：
#       只被 ``SceneEnterWuchong`` 用做「到达确认」。
#
# 形状（本段改的是**真源**，JSON 是投影，两者必须逐字一致 —— 守卫 hooks_103 把守）：
#     "WuchongNavJoss": {"next": ["WuchongNavRow", "[JumpBack]SceneEnterWuchong"]}
# 即 ``step_next(node) = FLOW_STEPS[i].next + (STEP_TAIL,)``：长度 = 真后继条数 + 1
#   （真后继通常 1–3 项，最长 ``WuchongRoomWait`` 7 项；远小于旧形状的 21–27）。
#
# 为什么「验证器必须 next == IN_NEXT（= ["WuchongEntry"]）」—— ★不是 next=[]★：
#   MaaFramework 的语义是「当前节点的 next 列表为空（若存在 [JumpBack] 会先回跳）⇒ **任务流程终止**」
#   （``.research/3.1-pipeline.md:48-52``）—— 真机一跑就会在第一步「任务完成」，这是 #103-R1 判定的
#   **致命形态**。交回枢纽 ``WuchongEntry`` 则不同：它是按 ``FLOW_STEPS`` 声明序的分派表，
#   验证器命中 → 回枢纽 → 由枢纽按当前页分派，既不会「继续乱走」、也不会「直接终止」。
#   守卫 hooks_103 用**绝对**断言钉住（``list(IN_NEXT) == ["WuchongEntry"]``；
#   只断言「投影 == IN_NEXT」是相对的 —— 真源改成 () 会整体变绿）。
#
# ★R1b 的教训落成可判形式：守卫 ⑥「识别必须可终结」★
#   枢纽是「按 ``FLOW_STEPS`` 声明序分派」的：某个业务节点的识别若在**动作之后仍然为真**，
#   它就会在同一页被反复派中（R1b 的两个同谋：``WuchongNavJoss`` 的页签文字永远可见、
#   ``WuchongScrollList`` 只认 state）。故 21 个业务节点里凡是**识别不随屏幕内容翻转**的，
#   必须登记进 :data:`IDEMPOTENT_UNSAFE` 并**逐条写明「为什么动作后它不会再次命中」**；
#   没登记的 = 红（守卫 hooks_103 ⑥）。豁免表本身就是这张票的设计结论，不是注释。
# 为什么 ``SceneEnterWuchong`` 只能放 next 的**最后一项**（死循环守卫 hooks_103 ③）：
#   它是 DirectHit（永远命中）→ 放首位/中间就等于「后续候选永不评估」→ 在接口层里打转。
# 为什么中继 ``WuchongGuardChain`` 内部**不得回指** ``SceneEnter*``（守卫 hooks_103 ③b）：
#   DirectHit 中继 → SceneEnter（DirectHit）→ 中继 … 是零成本的自环，真机上表现为「一秒几百帧、
#   一次点击都不发生」。
# ---------------------------------------------------------------------------
#: 接口层所在文件（与 ``wuchong.json`` 分开：导航/异常收进一层，业务文件只留业务）。
SCENE_FILE = "wuchong_scene.json"
#: 万能跳转（DirectHit）：从任意界面到「五重流程的某个已知页」。
SCENE_ENTER = "SceneEnterWuchong"
#: 异常中继（DirectHit）：今天 21 个业务节点开头的 20 项前缀，**顺序不变**地收在这里。
SCENE_GUARD_CHAIN = "WuchongGuardChain"
#: 中继的回跳闩（DirectHit，next=[]）：扫完阶梯立刻弹栈，绝不让中继悬在那里。
SCENE_GUARD_DONE = "WuchongGuardDone"

#: 7 个页面验证器 → 它们识别的 ``wuchong_state`` 状态值。
#: ★值与 ``agent/wuchong_impl`` 的 ``classify()`` 状态名逐字一致★（守卫 hooks_103 ① 比对）。
#: ★字典顺序 = ``SceneEnterWuchong.next`` 的候选顺序★（= 设计文档 §1 的 7 项顺序）。
IN_STATES: dict[str, str] = {
    "WuchongInLordList": "wuchong_lord_list",   # 领主战/降临讨伐 列表页
    "WuchongInDetail": "wuchong_detail",        # 五重决战·超级 详情页
    "WuchongInMode": "wuchong_mode",            # 模式选择页（单人/多人）
    "WuchongInRoom": "wuchong_room",            # 共斗房间页
    "WuchongInTeam": "wuchong_team",            # 编队页
    "WuchongInFight": "wuchong_battle",         # 战斗中
    "WuchongInSettle": "wuchong_settle",        # 结算/奖励页
}
#: 7 个验证器（顺序即 ``SceneEnterWuchong.next`` 的候选顺序）。
IN_SCENE_ORDER: tuple[str, ...] = tuple(IN_STATES)

#: 21 个业务节点 → 它们「这一步做完之后该在的那一页」的验证器。
#: ★R1b 之后它**不再进业务节点的 next**★（业务 next = 真后继 + 末位兜底）：验证器只被
#:   ``SceneEnterWuchong`` 用来「确认我现在已经在哪一页」。本表仍是**必需**的，理由是两条：
#:   ① 它把「这一步动作的落点页」登记下来 —— 图论自检靠它证明「7 个 state 每个都有业务节点
#:      在等它」（无死状态）；② 守卫 ⑥ 靠它算「动作后是否必然离开当前页」（识别可终结性）。
#: ★为什么逐个写而不是按页面猜★：落点写错 = 识别可终结性判错 / 死状态误判；
#:   守卫 hooks_103 ⑤ 钉死「键集 == 流程链节点集」，新增流程步必须同时补一条。
#: ★唯一有歧义的三类已就地注明★（结算三去向 / 编队页与房间页共用开关），见每条注释。
IN_NODES: dict[str, str] = {
    # —— 开场导航（主城 → 列表 → 页签 → 行 → 详情 → 模式）——
    "WuchongNavLord": "WuchongInLordList",       # 点【领主战】→ 领主战列表页
    "WuchongNavJoss": "WuchongInLordList",       # 点【降临讨伐】页签 → 仍列表页（只换页签）
    "WuchongNavRow": "WuchongInDetail",          # 点「五王连战」行 → 五重详情页
    "WuchongScrollList": "WuchongInLordList",    # 滚动列表找行 → 仍列表页
    "WuchongDetailFight": "WuchongInMode",       # 详情页点【战斗】→ 模式选择页
    "WuchongModeSolo": "WuchongInTeam",          # 点【单人游戏】→ 单人的编队页
    "WuchongModeMulti": "WuchongInRoom",         # 点【多人游戏】→ 共斗房间页
    # —— 共斗开房（招募 → 人齐 → 挑战）——
    "WuchongRecruitOpen": "WuchongInRoom",       # 房间点【招募】→ 招募方式弹窗（仍在房间里）
    "WuchongRecruitStart": "WuchongInRoom",      # 弹窗点【开始招募】→ 回到房间页
    "WuchongCoopChallenge": "WuchongInFight",    # 房间点【挑战】→ 战斗
    # —— 出口 / 门控（stale 页面 / 模式回退）——
    "WuchongRoomLeave": "WuchongInMode",         # 房间点【返回】→ 退回模式选择页
    "WuchongStaleTeam": "WuchongInMode",         # stale 编队页点【返回】→ 退回模式选择页
    # —— 编队页/房间页开关（★歧义：同两个节点在两页都跑★，取主战页 = 编队页）——
    "WuchongTeamAutoSet": "WuchongInTeam",       # 切「自动」→ 页面不变（编队页 / 房间页）
    "WuchongTeamContSet": "WuchongInTeam",       # 确保「自动续战」关 → 页面不变
    "WuchongTeamChallenge": "WuchongInFight",    # 编队页点【挑战】→ 战斗
    # —— 房间等人齐（自环）——
    "WuchongRoomWait": "WuchongInRoom",          # 人齐前一直在房间里
    # —— 战斗 ——
    "WuchongBattleAutoOff": "WuchongInFight",    # 战斗页关自动 → 仍在战斗
    # 打完一场落在**结算页**（不是战斗页 —— 那是它刚离开的页；图论自检抓到过）。
    # ★旧的「手操战斗 → 仍在战斗」残片已删（#103 的语义作废它：本节点是**打完**那一下，
    #   落点由 WuchongBattle 的 action 决定，与「还在战斗里」无关）★
    "WuchongBattle": "WuchongInSettle",
    # —— 结算三去向（★歧义：落点不唯一★，取各自**主按钮**的落点）——
    "WuchongSettleContinue": "WuchongInTeam",    # 【再次挑战】=首选按钮 → 编队页（【OK】才回详情页，D13）
    "WuchongSettleReturnRoom": "WuchongInRoom",  # 【返回房间】→ 房间页（也可能是编队页）
    "WuchongSettleDisband": "WuchongInLordList", # 【解散】→ 回列表页（也可能回编队/房间/主城）
}

#: ``SceneEnterWuchong.next``：7 个页面验证器 → 回主城重来 → 其余异常（中继）。
#: ★顺序承重★：验证器在最前（「已经在某个已知页」必须先判，否则会白跑一趟归位）。
SCENE_ENTER_NEXT: tuple[str, ...] = IN_SCENE_ORDER + ("[JumpBack]PubReturnHome", SCENE_GUARD_CHAIN)

#: ★#103-R1 修正★ 验证器的后继 = **交回枢纽** WuchongEntry。
#: 不是 next: [] —— MaaFramework 里「next 为空且无 [JumpBack]」= **任务流程终止**
#: （第一步就「任务完成」）；验证器不命中时 DirectHit 会进接口层再弹回业务节点 →
#: **零点击乒乓**到 no_progress_sec=900s。枢纽本就是按 FLOW_STEPS 声明序的分派表，
#: 交回它 = 状态机模型，且不引入空 next。
IN_NEXT: tuple[str, ...] = ("WuchongEntry",)

#: ``WuchongGuardChain.next``：**今天 FLOW_EXCEPTIONS 的 20 项，顺序一字不改** + 回跳闩。
#: ★绝不设 max_hit★（一局要扫成百上千次；#79 真机：用尽即静默跳过 → 打几把就卡死）。
GUARD_CHAIN_NEXT: tuple[str, ...] = FLOW_EXCEPTIONS + (SCENE_GUARD_DONE,)

#: ★R1b★ 业务 next 的**末位兜底**（带 ``[JumpBack]`` 的写法，逐字比较用）。
#: 每个业务节点的 ``next[-1]`` 必须是它、且**只有一项**（守卫 hooks_103 ①/③）。
STEP_TAIL: str = f"[JumpBack]{SCENE_ENTER}"

# ---------------------------------------------------------------------------
# ⑦b 守卫 ⑥「识别必须可终结」的**豁免表**（R1b 的核心教训，落成可判形式）
#
# 判据（守卫 hooks_103 ⑥ 从 pipeline 静态推导，**不靠这张表**）：
#   一个业务节点的识别算「可终结」，当且仅当能证明**动作成功后它必然翻假**，即下面两条之一：
#     (a) 页面变化：识别引用的 ``wuchong_state`` 里**没有**本节点动作的落点页（``IN_NODES``）——
#         动作成功 ⇒ 离开该 state ⇒ 识别翻假（例：``WuchongNavLord`` 认主城、落点列表页）；
#     (b) 开关翻转：识别是 ``auto_switch_state`` 且要求的态与本节点动作写下去的态**相反**——
#         动作成功 ⇒ 开关读数变为目标态 ⇒ 识别翻假（例：``WuchongTeamAutoSet`` 认 off、写 on）。
#   两条都证不出来（识别是纯 state / 恒可见文字 / 动作不改判据 / raw 默认 ``__NONE__``）
#   ⇒ **必须登记在这张表里**，并写清楚「为什么动作后它不会再次命中」。未登记 = 红。
#
# ★为什么这条守卫必须存在（真机 R1b 的原话）★：「2.5 分钟内 11 个采样全是
#   ``state=wuchong_lord_list``、零进展、零战斗」—— 根因就是枢纽按声明序**反复派中**
#   两个识别恒真的节点。识别不可终结 + 枢纽派发 = 打转；这条守卫把「不可终结」变成
#   **必须署名的例外**，而不是谁都没注意到的默认。
#
# 表内 9 条 = 今天证不出 (a)/(b) 的全部业务节点（其余 12 个由守卫现算为可终结，不在此表）。
# ---------------------------------------------------------------------------
IDEMPOTENT_UNSAFE: dict[str, str] = {
    "WuchongNavJoss": (
        "识别 = And[领主战列表页 state, 顶部『降临讨伐』页签文字] —— 页签文字在列表页"
        "**永远可见**（R1b 现场同谋之一），动作后仍为真。终止性来自**真后继**：点页签 = 切到"
        "『降临讨伐』列表，它的**首行就是「五王连战」**（真机帧 "
        "tools/frames/20_lord_tab_降临讨伐_列表首行五王连战.png）⇒ 末位之前的 WuchongNavRow "
        "（模板门控）立刻接手离开本页。★残余：若行始终不可见，枢纽会再次派中它（每轮只点一次"
        "页签、不前进）—— 与改造前同形（旧形状里异常扫空 → on_error → 枢纽 → 还是它），"
        "有界出口 = WuchongGiveUp.no_progress_sec★"
    ),
    "WuchongScrollList": (
        "识别 = 纯 state（wuchong_lord_list），与屏幕内容无关 ⇒ 动作后**仍为真**"
        "（R1b 另一个同谋）。它命中时动作是**上滑一屏**：滚动必然改变列表内容与候选顺序，"
        "『五王连战』那一行滚进视野后由 WuchongNavRow（模板门控）接手。★不设 max_hit"
        "（#79：任务级共享计数用尽即静默跳过）⇒ 有界性由 WuchongGiveUp.no_progress_sec"
        "（900s）兜底，且滚动本身是有意义的工作（不是空转）★"
    ),
    "WuchongRecruitOpen": (
        "识别 = 房间页 state + recruit_state=not_started（『未进行招募』）。动作点【招募】后"
        "**招募方式弹窗**出现 ⇒ classify() 变 wuchong_recruit_dialog、recruit_state 变 started，"
        "两条判据同时翻假（动作 expect 已含 wuchong_recruit_dialog）。静态推导证不出这条"
        "（判据在 state 之外），故登记豁免"
    ),
    "WuchongCoopChallenge": (
        "raw 默认关（recognition = __NONE__，永不命中）。只在『游戏模式=多人游戏』case 打开；"
        "打开后识别 = 共斗房（已招募）+ 底部『挑战』，动作 expect=wuchong_battle ⇒ 点下去页面"
        "变战斗页、房间判据翻假。★真实识别来自界面选项，静态不可判 ⇒ 豁免★"
    ),
    "WuchongRoomLeave": (
        "raw 默认关。单人 case 打开后识别 = 共斗房 + 左下【返回】，动作 expect 含 "
        "wuchong_mode/detail/lord_list/main_city（**都是房间之外**的页）⇒ 点下去离开房间页、"
        "判据翻假；再叠 agent 侧时间闩锁 latch=room_leave"
    ),
    "WuchongStaleTeam": (
        "raw 默认关。多人 case 打开后识别 = 编队页 + room_seen=false（本轮没进过共斗房），"
        "动作点【返回】且 expect 同样含房间/编队之外的页；room_seen 一旦进房即置真 ⇒ 翻假；"
        "叠 latch=stale_team"
    ),
    "WuchongRoomWait": (
        "识别 = 纯 state（房间页），动作 = **DoNothing**（不点任何东西）⇒「动作后仍为真」是"
        "**设计**：它的命中就是『等待』语义，真后继里含自己（自环继续等）+ 房间的三条出路"
        "（招募 / 挑战 / 自动开关）。有界出口 = room_wait_sec=300s 的有理由收工"
    ),
    "WuchongBattleAutoOff": (
        "raw 默认关。只在『是否手操=手操』case 打开；打开后识别 = 战斗页 + 自动开，动作只"
        "**关一次**、闩锁在 agent 侧（一场战斗一次，见 BATTLE_AUTO_ONCE_KEY）⇒ 关掉后 "
        "auto_switch_state 翻假"
    ),
    "WuchongBattle": (
        "raw 默认关（#56 P0：手操引擎关时若开着就会空转 ×13）。打开后动作是**长阻塞的手操"
        "引擎**（自己既是识别又是引擎）：一场战斗内它**就该**每轮命中（next 里含自己 = 自环），"
        "只在续关屏 / 结算页 / 被推出战斗三个正面终止点交还；有界由引擎自身 + WuchongGiveUp 兜底"
    ),
}

#: ★逃生门★：True = 退回旧形状（异常前缀 + 本步后继）。
#: 回滚口径（设计 §4）：翻成 True **同时**把 ``wuchong.json`` 的 21 个业务 next 改成
#: ``FLOW_EXCEPTIONS + FLOW_STEPS[i].next``；只翻一半会让 hooks_103 / hooks_wuchong 一起红
#: （那是故意的 —— 别让半迁移上线）。
LEGACY_NEXT = False


#: 需要注入异常前缀的流程节点（WuchongEntry 用 hub 语义；滚动节点也注入兜底）。
def flow_step_nodes() -> tuple[str, ...]:
    """按声明顺序的流程节点名（不含 jumpback 步）。"""
    return tuple(s.node for s in FLOW_STEPS if not s.jumpback)


def hub_next() -> tuple[str, ...]:
    """枢纽 ``WuchongEntry.next`` 的**数据派生**：异常前缀 + 全部流程节点 + 链尾兜底。"""
    return FLOW_EXCEPTIONS + flow_step_nodes() + FLOW_TAIL


def legacy_step_next(node: str) -> tuple[str, ...] | None:
    """**旧形状**（#103 之前）：某流程节点的候选集 = 异常前缀 + 本步后继。

    ★这是**改造前**的形状，不是 B 方案的第一版★：B 方案第一版（#103 交付）是
    ``[验证器, [JumpBack]SceneEnterWuchong]`` 两项，那版在真机上打转（R1b），已废弃。
    本函数只在 :data:`LEGACY_NEXT` 打开时被 :func:`step_next` 使用（逃生门；见 ⑦）。
    """
    for s in FLOW_STEPS:
        if s.node == node:
            return FLOW_EXCEPTIONS + s.next
    return None


def step_next(node: str) -> tuple[str, ...] | None:
    """某流程节点的候选集（★R1b 形状★：真后继 + 末位兜底；找不到该步返回 None）。

    ``FLOW_STEPS[i].next + (STEP_TAIL,)`` —— 例：
    ``("WuchongNavRow", "[JumpBack]SceneEnterWuchong")``。

    * **真后继在前**：提供「下一步做什么」（R1b 的修法 —— 进度不能再靠枢纽分派，因为枢纽
      按声明序派发时会把识别恒真的节点反复派中，真机 2.5 分钟零进展）；
    * **末位兜底**：真后继全不命中 ⇒ ``[JumpBack]SceneEnterWuchong``（DirectHit）→ 7 个
      页面验证器确认「我现在在哪一页」→ 由它交回枢纽；中继里才是 20 项异常。

    :data:`LEGACY_NEXT` 为 True 时退回旧形状（异常前缀 + 本步后继）—— ★那是逃生门，
    翻开关的同时必须把 ``wuchong.json`` 的 21 个业务 next 一起改回旧形状★（漂移会红着提醒你）。
    """
    for s in FLOW_STEPS:
        if s.node == node:
            if LEGACY_NEXT:
                return legacy_step_next(s.node)
            return s.next + (STEP_TAIL,)
    return None


def step_successors() -> dict[str, tuple[str, ...]]:
    """{业务节点: 真后继}（= ``FLOW_STEPS`` 的声明序与声明内容，供守卫/统计复用）。"""
    return {s.node: s.next for s in FLOW_STEPS if not s.jumpback}
