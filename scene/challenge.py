# -*- coding: utf-8 -*-
"""「挑战」按钮的**点击判据** —— 全项目唯一真源（ticket #110）。

## 事实：同一个按钮，两种渲染

真机帧 / 识别调研（``docs/research/recognition-ocr-vs-template.md`` §1.2 例 1 + §1.3「两态」）：

* 底部【挑战】按钮被 OCR 读成 ``挑战`` 或 ``挑战→``；
* 两种读法**各自像素稳定**（``挑战`` score 1.000 / ``挑战→`` score 0.962，长跑里一字不差），
  统计 **8/17 帧**带箭头 —— 这不是随机抖动，是**两个稳定的视觉状态**（按钮带不带箭头装饰）；
* 整串 ``^挑战$`` **不匹配** ``挑战→`` ⇒ 用旧形状时约**一半的帧上判据不成立**。

## 为什么必须**整串锚定**（``^…$``）

MaaFramework 的 OCR **默认是子串匹配**（调研 §3.2：``fullMatch: false``）；本仓一律写
``^…$`` 是**有意的更严格档**。写成裸 ``挑战``（或 ``挑战.*``）会把这些**别的控件**点上：

* ``再次挑战`` / ``继续挑战`` —— 结算页按钮（点了是「再打一局 / 换流程」，不是开打）；
* ``挑战深渊连战`` / ``挑战深渊连战EX`` —— 进关前的**确认框文案**（点了弹框，不是开战）；
* ``高难挑战`` / ``连续挑战次数`` / ``挑战其他关卡前请先卸下或更换`` —— 各处标签与提示。

故本模块给出**唯一形状**：``^挑战(→)?$`` —— 只多容忍**一个**箭头。
``(→)?`` 不是 ``(→)*`` / ``.*``：``挑战→→``（两个箭头）与 ``→挑战``（箭头在前 = 另一个控件）
都必须继续被拒收。

## 这条判据落在哪（JSON 是手写的，ADR-0001）

pipeline JSON **不被整体生成**（ADR-0001），所以 JSON 里的落地形式就是 :data:`CHALLENGE_CLICK_PATTERNS`
这个**同一个字面量**，每个节点注释里写明「真源 ``scene/challenge.py``」。
:data:`CLICK_CRITERIA` 是那几处的**机器可读清单**：守卫 ``tools/contract_hooks/hooks_110.py``
与测试 ``tools/test_challenge_click.py`` 按它逐条比对 —— 少一处、改一处回 ``^挑战$``、
或者放宽成裸「挑战」，都当场变红。

字段名说明（两种承载方式，语义相同：都是「点哪个按钮」的判据）：

* ``expected`` —— OCR 识别节点的 ``recognition.param.expected``（MAA 自己匹配，``Click target: true``
  点自己的识别框，或作为 ``And`` 的 ``box_index`` 被点）；
* ``what`` —— 自定义动作（``wuchong_act`` / ``phantom_act`` / ``abyss_act``）的
  ``custom_action_param.what``：按正则挑按钮再点它。

★agent 侧是**逐字快照**，不是 import★：``agent/side_impl.py::_PUBCHALLENGE_ORIGINAL``
在运行期用 ``pipeline_override`` 把公共打断 ``PubChallenge`` 收窄/还原（#30），它**必须**
与本模块同形，否则「白改」——但 ``agent/`` 是**安装态的独立目录（没有 ``scene/``）**，
不能 ``from scene.challenge import``；故那里存一份快照，由 hooks_110 钉「快照 == 真源」。

## 不归本模块管

**页面判据**（这个画面算不算「编队页」）：#109 已把 ``scene.auto_switch.TEAM_PAGE_ANCHORS``
与 ``scene.page_rules`` 的「编队页」改成同一形状，由 ``hooks_109`` 钉住，本票**不重复改**
（两处是「页面判据」，本模块是「点击判据」；同一颗按钮的两个不同问题，改一个错一个就是两套真源）。

★agent 侧还有一处**同名的精确比较**不归本票★：``agent/abyss_impl.py`` / ``wuchong_impl.py`` /
``battle_loop_core.py`` 的页面状态分类里有 ``any(t == "挑战" for t in texts)``（**逐字相等**，
不是正则）—— 那同样是「带箭头那一半帧会漏」，但它是**页面状态判据**、且改它要连带重测三条
状态机，故留作后续票（本票只动点击判据 + 它的运行期快照）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 唯一形状
# ---------------------------------------------------------------------------
#: 「挑战」按钮点击判据的**唯一**正则：整串锚定 + 至多**一个**箭头。
CHALLENGE_CLICK_PATTERN: str = r"^挑战(→)?$"

#: 列表形态（MAA 的 ``expected`` / ``what`` 都是**列表**，允许一节点多串；
#: 本按钮只有一种渲染族，故列表恒为这一项 —— JSON 里落地的就是这个字面量）。
CHALLENGE_CLICK_PATTERNS: tuple[str, ...] = (CHALLENGE_CLICK_PATTERN,)

#: 反例：整串锚定必须继续**拒收**的文字（放宽成裸「挑战」/``挑战.*`` 就会全中）。
#: 每条都对应真机屏上真的存在、且**点错就会跑偏**的控件（见模块 docstring）。
REJECTED_TEXTS: tuple[str, ...] = (
    "再次挑战",          # 结算页【再次挑战】（farm / raid 循环）
    "继续挑战",          # 结算页【继续挑战】（深渊 / 幻想单人连打）
    "挑战深渊连战",      # 深渊进关确认框（普通版）
    "挑战深渊连战EX",    # 深渊EX 进关确认框
    "高难挑战",          # 关卡标签
    "连续挑战次数",      # 幻想连战「连续挑战次数：N次」确认框
    "挑战→→",           # 只允许**一个**箭头（`(→)?` 不是 `(→)*`）
    "→挑战",             # 箭头在前 = 另一个控件（不是这颗按钮）
)


@dataclass(frozen=True)
class ClickCriterion:
    """一处「挑战」点击判据在 pipeline 里的落点。

    ``field``：
      * ``"expected"`` → ``recognition.param.expected``；
      * ``"what"``     → ``action.param.custom_action_param.what``（自定义动作挑按钮用）。

    ``page``：这颗按钮在哪个页面（决定离线求值时用哪份真机框 —— 同名的两颗「挑战」
    在屏幕上**不同位置**：单人编队页底部 y≈1092、共斗房里 y≈929）。
    """

    file: str
    node: str
    field: str
    page: str = "solo_team"
    note: str = ""

    def path(self) -> str:
        """给人看的路径串（报红时点名用）。"""
        return f"{self.file}::{self.node}"


#: 点击判据的**全部**落点（7 处，逐条登记 —— 少一处 / 多一处未登记都会被 hooks_110 打红）。
#: 新增一处「点挑战」= 加进本表 + 把 JSON 写成 :data:`CHALLENGE_CLICK_PATTERNS`。
#:
#: 7 处 = 单人编队页 5 处（底部那颗「挑战」）+ 共斗房 2 处（房间里那颗「挑战」，720 中心 y≈929）。
#: ★共斗房那两处为什么也算「本按钮」★：识别调研里带箭头样本的框 ``[297,905,156,47]`` 与共斗房
#: 「挑战」的 ``[297,906,81,46]`` **同高** —— 箭头症状的现场很可能就是它；而五重多人（运维
#: 主用模式）开战走的正是 ``WuchongCoopChallenge``，漏了它等于多人永远开不了战。
CLICK_CRITERIA: tuple[ClickCriterion, ...] = (
    ClickCriterion(
        "common.json", "PubChallenge", "expected", "solo_team",
        "公共「挑战」：编队页点挑战开打（公共打断事件，贯穿 auto_push/farm/raid/side_story）",
    ),
    ClickCriterion(
        "wuchong.json", "WuchongChallengeText", "expected", "solo_team",
        "五重编队页【挑战】的 OCR 门（WuchongTeamChallenge 的 And 叶，box_index=1）",
    ),
    ClickCriterion(
        "wuchong.json", "WuchongTeamChallenge", "what", "solo_team",
        "五重编队页点【挑战】（wuchong_act 的按钮挑选）",
    ),
    ClickCriterion(
        "wuchong.json", "WuchongCoopChallenge", "what", "coop_room",
        "五重共斗房点【挑战】（人齐后转亮；roi y820-980 = 房间里那颗，不是编队页底部那颗）",
    ),
    ClickCriterion(
        "phantom.json", "PhantomSoloChallenge", "what", "solo_team",
        "幻想单人编队页点【挑战】（phantom_act 的按钮挑选）",
    ),
    ClickCriterion(
        "phantom.json", "PhantomCoopChallenge", "what", "coop_room",
        "幻想共斗房点【挑战】（phantom_state=phantom_coop_room 门控页面，不靠 roi）",
    ),
    ClickCriterion(
        "abyss.json", "AbyssSoloChallenge", "what", "solo_team",
        "深渊单人编队页点【挑战】（abyss_act 的按钮挑选）",
    ),
)

_RE = re.compile(CHALLENGE_CLICK_PATTERN)


def matches(text: str) -> bool:
    """这段 OCR 文本是不是「挑战」按钮（整串 + 至多一个箭头）。"""
    return _RE.search((text or "").strip()) is not None


def is_challenge_pattern(pattern: str) -> bool:
    """某个 ``expected`` / ``what`` 串是否**就是**真源形状（逐字相等，不做语义等价）。"""
    return pattern == CHALLENGE_CLICK_PATTERN
