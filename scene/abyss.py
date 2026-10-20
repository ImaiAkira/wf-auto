# -*- coding: utf-8 -*-
"""深渊EX（abyss）场景配置【数据】（#55 Phase 2；scenario = 领主战类之外的第二类配置）。

本文件**只放数据**：一个「场景」（scenario）的横幅模板 / 二级页签搜索 / 进关确认文案 /
关卡阶梯规模 / 账本范围 / 状态词表。它**不导入 maa、不跑逻辑**（ADR：``scene/`` 离线可导入、
是唯一配置权威；运行时机制在 ``agent/abyss_impl.py``）。

为什么是第二类配置（不是领主战类成员）
--------------------------------------
领主战类的形状是「family 模板 + 成员 delta + 难度」（点行名进详情）。深渊/深渊EX/幻想连战
是同一种**活动场景**：没有成员、没有难度，只有一条**线性关卡阶梯**；导航也不点行名，而是
「主城 → 活动 → 终始之战 → 在二级页签里搜目标横幅 → 进入」。硬套 FamilyTemplate/MemberDelta
= brief 说的坏抽象（kernel 的 ``FamilyTemplate`` 也不适用于它们）。

★三个二级页签不固定（运维澄清 2026-10-14）★
「深渊/深渊EX/幻想都是通过 活动 → 终始之战 进去的，然后他位于 **已通关/未通关/完成** 这三个
二级菜单中的哪一个是不固定的，随着账号的进度而定」——因此导航**不假定页签**：必须在
:data:`ZHONGSHI_TABS` 列出的三个页签里**搜**到目标横幅再进入。页签列表**数据化**（本文件），
搜索会处理「横幅在多个页签同时可见」（从**当前页签起按数据顺序**找到的第一个即进入）。
**幻想连战 / 深渊 / 深渊EX 共用这条导航**（同一张终始之战列表页、同一组页签）。

★两条横幅必须可靠区分（校准 §3.2）★
``banner_abyss_ex`` 模板对**纯深渊**横幅会假阳（校准实测 ZNCC **0.8708**，阈值 0.75 会命中）。
故每个场景带**自己的横幅模板 + 自己的阈值**，且模板匹配优先于 OCR：
``ABYSS_EX`` = ``banner_abyss_ex.png`` / ``ABYSS_PLAIN`` = ``banner_abyss_plain.png``，两条模板
在 0.90 阈值下互相区分（EX vs 纯深渊 ZNCC = **0.874** < 0.90；各自自证 = 1.0）。**纯深渊 =
本文件加一条 :data:`ABYSS_PLAIN` 数据增量**（Phase 3），不把 EX-only 假设烧进链里。

对应的真机帧 / 数字：``docs/recon/abyss-calibration.md``（2026-10-14，设备 127.0.0.1:16448）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# ---------------------------------------------------------------------------
# 共用的「终始之战」二级页签（★数据驱动、可配置★）——幻想连战 / 深渊 / 深渊EX 共用。
#
# 顺序 = 搜索顺序的**数据**（引擎会在这些页签间循环找目标横幅）；**不是**「目标在哪个」。
# 真机实测页签 OCR（720 空间）：未通关@(119,405) / 已通关@(360,405) / 完成@(599,406)。
# ---------------------------------------------------------------------------
ZHONGSHI_TABS: tuple[str, ...] = ("未通关", "已通关", "完成")

# ---------------------------------------------------------------------------
# ★#117★ 终始之战「空态」+「页签切换」判据 —— 真机证据在库，不是发明。
#
# 现场（真机 384，2026-10-18 08:0x，跑 ``AbyssPlainEntry``）::
#
#     [abyss_act] state=zhongshi 点击 '未通关' → 校验通过 zhongshi -> zhongshi
#     [abyss_act] state=zhongshi 点击 '已通关' → 校验通过 zhongshi -> zhongshi
#     [abyss_act] state=zhongshi 点击 '完成'   → 校验通过 zhongshi -> zhongshi
#     （三连无限重复，直到人工停掉）
#
# 两个病：
#   ① **自证式校验**：``expect=["zhongshi", ...]`` 在「点完还在这一页」时恒成立 ⇒ 每次点击都
#      "通过"（#19 同类：判据必须来自**新的页面证据**，不能来自「当前 state 没变」）；
#   ② **空态不收工**：三个页签都没有内容，列表区写着「没有相关的活动」，流程却继续找横幅。
#
# 证据帧：``tools/frames/abyss_zhongshi_tabs.png``（1080x1920 原图，720 空间 OCR 侧车 =
# 同名 ``.ocr.txt``）。本帧 720 空间实测读数::
#
#     终始之战   [199, 130, 299,  90]
#     未通关     [ 74, 386,  90,  35]   已通关 [316, 388, 89, 34]   完成 [566, 388, 66, 36]
#     **没有相关的活动** [240, 789, 237, 37]
#     底部导航带 y ≈ 1244（角色 / 商店 / 扭蛋 / 返回 / 主城 / 菜单）
# ---------------------------------------------------------------------------
#: 空态锚点（OCR 整句）。只出现在终始之战列表页、且三个页签都没有内容的时候。
ZHONGSHI_EMPTY_ANCHOR: str = "没有相关的活动"

#: 空态收工原因（用户可见的一句话；由既有 ``abyss_giveup`` 出口消费，不新造出口）。
ZHONGSHI_EMPTY_REASON: str = "终始之战没有可打的关卡（三个页签均无内容）"

#: 页签切换失败的重试上限（★#19 的结论★：不许多次重试；1 次之后必须带原因退出）。
TAB_SWITCH_RETRY_LIMIT: int = 1

#: 「页签内容区」= 页签栏之下、底部导航之上的那一条（720 空间 ``x0, y0, x1, y1``）。
#: 判「页签切换是否真的生效」只看这一条里的**文本集合**：
#: 页签栏自己占 y≈386..424、底部导航带起于 y≈1244 —— 两头都必须排除，否则「屏上文字集合」
#: 永远包含那几颗常驻元素，判据会退化成恒真。
ZHONGSHI_CONTENT_BOX: tuple[int, int, int, int] = (0, 445, 720, 1180)

#: 终始之战「整轮扫描」上限（★同一张票的第二条逃生路★）：横幅节点排在切页签**之前**
#: （只要目标横幅可见就不会再进 ``step=tab``），所以「还在切页签」等价于「这一轮页签上都没有
#: 横幅」。**扫过 2 轮**（6 次成功切换）还没找到 ⇒ 带原因收工 —— 否则「账号有别的活动、
#: 没有深渊」时会在这一页无限切页签（旧实现连 ``no_progress_sec`` 都兜不住：那条判据要求
#: 本次会话已打过至少一层，没内容的账号 ``session_max_done`` 永远是 0）。
TAB_SCAN_ROUND_LIMIT: int = 2

#: 扫完仍然找不到横幅时的收工原因模板（用户可见；``{rounds}`` / ``{display}`` 由引擎填）。
#: ★这是「账号没内容」在代码侧的**明确答案**★：不是静默空转，而是一句话告诉运维少了什么。
TAB_SCAN_FAIL_REASON: str = "终始之战扫过 {rounds} 轮页签都没有找到「{display}」横幅"

#: ★ADR 0005 / #19★ 「迷路」闸门：**连续**这么多秒认不出画面 → 带原因收工（不是累计帧数）。
#:
#: 为什么要换量纲：旧判据是「本轮任务里累计多少帧 unknown」，它随运行时长单调增长 ⇒
#: 无界会话**必然**越线（真机：深渊第 20 战正常转场的结算帧上以旧原因收工，19 战全部记账
#: 正常却死在第 20 战）。
#:
#: 为什么是 60s（真机证据，不是拍脑袋）：2026-10-19 深渊真机逐帧重建本轮 **725 帧 / 110 段
#: unknown**，连续驻留中位 **3s**、p95 **6s**、最长 **16s**；构成是「结算→下一战」53% +
#: 「战斗→结算」40% —— **没有一次是迷路**。60s = p95 的 10×、最长段的 **3.75×** 余量：
#: 正常转场不可能误杀，而真卡住的任务 1 分钟内一定带原因退出。
#:
#: 与 kernel ``battle_loop_core.DEFAULT_LOST_SEC`` 同值；override 里的 ``lost_sec`` 优先，
#: 见 ADR 0005。**JSON 里不再复制一份**（阈值真源只在本文件）。
LOST_SEC: int = 60


@dataclass(frozen=True)
class ScenarioTarget:
    """一个「活动场景」的**全部**配置（数据）。

    字段都来自真机校准（``docs/recon/abyss-calibration.md``），不是发明：

    * ``scene`` / ``display``      场景 id / 显示名；
    * ``banner_template``          终端横幅**模板图**（相对 ``assets/resource/image/``）——
                                   template 匹配优先于 OCR（艺术字 OCR 不可靠，且
                                   「深渊连战」⊂「深渊连战EX」子串歧义）；
    * ``banner_patterns``          横幅**文本**正则（仅作日志/兜底；判据靠模板）；
    * ``tabs``                     要搜索的二级页签（**数据驱动**，不假定目标在哪个）；
    * ``confirm_text``             hub→关卡 的进关确认框整句片段（校准 §3.2 坑 3：
                                   ``战斗`` 先弹确认框，``OK`` 后才到关卡选择页）；
    * ``max_stages``               线性阶梯规模（深渊 = 30 层）；
    * ``ledger_scope``             账本范围（``abyss/stage/{n}``）；
    * ``stage_re``                 阶梯编号正则（深渊 = ``第N战``）；
    * ``banner_threshold``         模板匹配阈值（必须 > 另一条横幅的假阳分）；
    * ``hub_match`` / ``main_match`` 枢纽 / 关卡选择页的状态词（与纯深渊**共享**）；
    * ``active_states``            该场景的「在局内」状态集（中途接管 / 上限判定用）。

    以下六个是 **#117** 加入的「终始之战页签 / 空态」判据数据（两个场景**共享**，故都有缺省值；
    缺省值就是真机证据帧 ``tools/frames/abyss_zhongshi_tabs.png`` 的读数）：

    * ``empty_anchor``             空态锚点（三个页签都没有内容时列表区的那句话）；
    * ``empty_reason``             空态收工原因（用户可见一句话，走既有 giveup 出口）；
    * ``tab_retry_limit``          页签切换失败的重试上限（#19：1 次，之后带原因退出）；
    * ``content_box``              「页签内容区」720 空间 ``x0, y0, x1, y1``（判切换是否生效的范围）；
    * ``tab_scan_rounds``          整轮页签扫描上限（扫完仍找不到横幅 ⇒ 带原因收工）；
    * ``tab_scan_reason``          扫完找不到横幅的收工原因模板（``{rounds}`` / ``{display}``）。

    ``lost_sec`` 是 **ADR 0005 / #19** 的「迷路」闸门（连续认不出画面的秒数，见
    :data:`LOST_SEC`）。两个深渊场景共享同一个阈值，故带缺省值、不在两处各写一遍。
    """

    scene: str
    display: str
    banner_template: str
    banner_patterns: tuple[str, ...]
    tabs: tuple[str, ...]
    confirm_text: str
    max_stages: int
    ledger_scope: str
    stage_re: str
    banner_threshold: float
    hub_match: tuple[str, ...]
    main_match: tuple[str, ...]
    active_states: tuple[str, ...]
    # --- #117（终始之战页签校验 + 空态收工）：两个场景共享，故带缺省值 ---
    empty_anchor: str = ZHONGSHI_EMPTY_ANCHOR
    empty_reason: str = ZHONGSHI_EMPTY_REASON
    tab_retry_limit: int = TAB_SWITCH_RETRY_LIMIT
    content_box: tuple[int, int, int, int] = ZHONGSHI_CONTENT_BOX
    tab_scan_rounds: int = TAB_SCAN_ROUND_LIMIT
    tab_scan_reason: str = TAB_SCAN_FAIL_REASON
    # --- ADR 0005 / #19（迷路闸门）：两个深渊场景共享，故带缺省值（EX / plain 都自动继承）---
    lost_sec: float = LOST_SEC


# hub 判据（校准 §3.1）：`深渊连战 & !(不可续战｜战斗记录｜推荐编成)`。
# ★用「深渊连战」子串（不含 EX）★：EX hub / 纯 hub **逐处同形**（只差艺术字里的 EX）。
_HUB_MATCH = ("深渊连战",)
_HUB_NONE = ("不可续战", "战斗记录", "推荐编成")

# main（关卡选择页）判据（校准 §3.1）：
# `(不可续战｜战斗记录) & (推荐编成｜ABYSS ONSLAUGHT｜战斗)` —— EX / 纯深渊共享。
_MAIN_MATCH = ("不可续战", "战斗记录", "推荐编成", "ABYSS ONSLAUGHT", "战斗")

# 状态名（与 agent/abyss_impl.py 一一对应；纯深渊与 EX **共享**这些页面词）。
ACTIVE_STATES = ("abyss_hub", "abyss_main", "abyss_solo_team", "abyss_settle", "abyss_battle")

#: ★#118★ 「零进度」的独立上限（秒）：**一场都没完成**时用这个，比 ``DEFAULT_NO_PROGRESS_SEC``（900s）更短。
#: 真机证据（484，08:3x）：深渊EX 第 1 战打不过 —— 手操 5 次弹板就 ``stopped=battle_over reason=结算``，
#: 20 秒一轮反复重进「深渊连战EX第1战」，而旧 no-progress 判据要求 ``session_max_done > 0``
#: ⇒ 零进度的任务**永不收工**（无限重进）。零进度 5 分钟必须带原因退出。
#: 与 ``agent/abyss_impl._ZERO_PROGRESS_SEC_SNAPSHOT`` 由守卫钉「逐字相等」。
ZERO_PROGRESS_SEC = 300


ABYSS_EX = ScenarioTarget(
    scene="abyss",
    display="深渊连战EX",
    banner_template="banner_abyss_ex.png",
    # 艺术字 OCR 不可靠（会把「五重决战」读成繁体「五重決战」）；判据靠模板，串只作兜底。
    banner_patterns=(r"深渊连战\s*EX", r"ABYSS ONSLAUGHT EX"),
    tabs=ZHONGSHI_TABS,
    # 校准 §3.2 坑 3：`战斗` 后弹的是「挑战深渊连战EX。」确认框，`OK` 才到关卡选择页。
    confirm_text="挑战深渊连战EX",
    max_stages=30,
    ledger_scope="abyss",
    stage_re=r"第\s*(\d{1,2})\s*战",
    # ★阈值必须 > 0.8708（EX 模板对纯深渊横幅的假阳分）★；0.90 落在这条与自证 1.0 之间。
    banner_threshold=0.90,
    hub_match=_HUB_MATCH,
    main_match=_MAIN_MATCH,
    active_states=ACTIVE_STATES,
)

# ★纯深渊 = 纯数据增量（Phase 3）★：只换横幅模板 / 横幅串 / 进关确认文案 / 场景 id；
#   页签搜索（ZHONGSHI_TABS）、hub/main 判据、阶梯（第N战）、状态集**全部共享**。
#   本票（Phase 2）只落地 ABYSS_EX；这里给出数据形状，Phase 3 只需把它接一个 task 即完成。
ABYSS_PLAIN = ScenarioTarget(
    scene="abyss_plain",
    display="深渊连战",
    banner_template="banner_abyss_plain.png",
    # 纯深渊横幅无 EX：模板为主判据；串用负向先行断言破「深渊连战」⊂「深渊连战EX」子串歧义。
    banner_patterns=(r"深渊连战(?!\s*EX)", r"ABYSS ONSLAUGHT(?!\s+EX)"),
    tabs=ZHONGSHI_TABS,
    confirm_text="挑战深渊连战",
    max_stages=30,
    ledger_scope="abyss_plain",
    stage_re=r"第\s*(\d{1,2})\s*战",
    banner_threshold=0.90,
    hub_match=_HUB_MATCH,
    main_match=_MAIN_MATCH,
    active_states=ACTIVE_STATES,
)

#: 全部已登记场景（数据）。按登记顺序。
SCENARIOS: tuple[ScenarioTarget, ...] = (ABYSS_EX, ABYSS_PLAIN)


def scenario(scene: str) -> ScenarioTarget:
    """按场景 id 取配置；未登记则 KeyError（绝不臆造）。"""
    for s in SCENARIOS:
        if s.scene == scene:
            return s
    raise KeyError(f"未登记的深渊场景：{scene!r}（已登记：{[s.scene for s in SCENARIOS]}）")


# ---------------------------------------------------------------------------
# 数据驱动的页签搜索（幻想连战 / 深渊 / 深渊EX **共用**）
#
# 引擎（pipeline 的 AbyssNavTab → agent abyss_act step="tab"）就是照这两个纯函数做的：
# 页签列表是**数据**，搜索是「从当前页签起、按数据顺序循环、找到目标横幅就进入」，
# 因此**不假定**目标在哪个页签，也天然处理「横幅在多个页签同时可见」（先撞见哪个用哪个）。
# ---------------------------------------------------------------------------
def tab_search_order(tabs: Sequence[str] = ZHONGSHI_TABS) -> tuple[str, ...]:
    """页签搜索会依次经过的顺序（= 数据顺序；不假定目标位置）。"""
    return tuple(tabs)


def enter_from_any(visible_tabs: Mapping[str, bool], tabs: Sequence[str] = ZHONGSHI_TABS) -> str | None:
    """给定「各页签当前是否可见目标横幅」，返回**搜索最先撞见**的那个页签。

    * ``visible_tabs`` 一个页签可见 → 返回它（无论它在数据顺序的第几位）；
    * 多个页签同时可见 → 返回**数据顺序最靠前**的那个（= 搜索会先撞见的）；
    * 都不见 → ``None``（引擎继续切下一个页签）。
    这是「banner 在多个页签同时可见」的数据模型（本票的离线守卫用它做正反例）。
    """
    for t in tabs:
        if visible_tabs.get(t):
            return t
    return None
