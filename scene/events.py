# -*- coding: utf-8 -*-
"""跨场景通用【事件】层：异常组（#5）+ 归位（#8）+ 两类注入位置（#18）。

术语（``GLOSSARY.md``，不可换词）：

* **事件 (event)**：跨场景通用、需要「响一下」的页面级情况（加载 / 结算 / 弹窗…），
  落到 pipeline 上就是那些 ``Pub*`` 节点；
* **归位 (return-home)**：把游戏从任意页面带回主城的通用事件。

本模块是这些情况的**【唯一一处】定义**（#5）：

* ``EXCEPTION_EVENTS`` —— 九类跨场景异常（加载 / 结算 / 换日 / 等级 / 新角色 /
  剧情 / 挑战 / 加成弹窗 / 招募），只在这里定义一次；
* ``RETURN_HOME``      —— 归位，被提升为通用事件（#8），**不是**每条场景链的链尾职责。

两类事件、两种注入位置（#18 —— 修复归位在「主城」自匹配导致的死循环）
------------------------------------------------------------------------
每个 ``Event`` 现在带一个 ``kind``：

* **打断型 (interrupting) ``kind="interrupt"``** —— 加载 / 结算 / 换日 / 等级 / 新角色 /
  剧情 / 挑战 / 加成弹窗 / 招募。它们是「看到就先处理掉」的全局打断，注入在【每个流程
  节点的原有后继**之前**（前缀），行为与 #5 一致。
* **兜底型 (fallback) ``kind="fallback"``** —— 归位（以及任何「本来就在那儿也算命中」的
  判据）。它必须是最低优先级的回退，注入在【原有后继**之后**、兜底/恢复边之前】（后缀）。

为什么必须分两类（#13 真机实证）：归位原先作为**优先前缀**注入每个流程节点，而主城页
常驻的底部导航标签「主城」（720 ``box=[157,1248,44,25]``，中心 ``(179,1260)``）落在
归位的 ROI ``[0,1180,720,100]`` 内 → 在主城上恒命中归位 → 点空 → ``[JumpBack]`` 重扫
→ 再命中 → **死循环**（370 节点全 ``PubReturnHome``，7 分钟没离开主城）。

★兜底型判据不得自匹配目标状态★：归位不能再以「已经看到主城」为命中条件。现判据改为
``And(主城底部导航可见, 底部导航最左槽是「返回」)`` —— 主城页最左槽是「主角色」、没有
「返回」，故归位只在【非主城】子页面上命中（见 :data:`RETURN_HOME_NODE_SPEC`）。

★#29 追加约束：兜底型判据不得自匹配【链上步骤页面】★
#18 的 ``And(主城底导, 返回)`` 仍太宽 —— 领主战**列表页 / 详情页同样同时具备这两者**
（真机实证，见 `#29`）。于是归位在这些**链上步骤页面**上自匹配：它作为兜底后缀紧跟
``SpecialEnterBoss`` 之后，目标行在屏幕外时 ``SpecialEnterBoss`` 不命中 → 兜底归位先触发
→ 点主城 → 回主城 → 枢纽重进；而负责滚动找行的 ``SpecialScrollList`` 只挂在枢纽候选表里
→ **永远轮不到** → 15 个领主战成员只有首屏 3 个能打到。
故判据再追加**页面范围**判别叶 ``PubReturnHomeOtherSection``：**当前一级分区不是主城**。
底导六个槽 ``[上下文] [主城] [角色] [商店] [扭蛋] [菜单]``，只有被选中一级分区页签是橙色；
主城分区的**任何**页面（含链上所有步骤页）「主城」页签高亮 → 判别叶为假 → 归位不命中。
MAA 识别无 ``Not``，故用**正向**的 ``Or(其余四个页签中某一个橙色)`` 表达「不在主城分区」。
真机帧实测（720 空间，见 ``tools/contract_hooks/hooks_29.py``）：主城分区页四个其它页签
橙色像素 = 0；扭蛋分区页「扭蛋」页签 = 918。守卫见 :func:`scene.drift.chain_page_fallback_drift`。

注入契约（ADR-0001 的「幂等注入」职责）：

* ``inject_events(nodes)`` 把**打断型**引用写进每个流程节点候选集的**前缀**、
  **兜底型**引用写进**后缀**（在原有后继之后、该节点最后的「恢复边 / 终点」之前）；
  链的**形状**本身不含事件（``strip_events`` 能把壳剥回原形，见测试里的
  ``strip_events(inject_events(x)) == x`` 不变量）；
* 注入是**幂等**的：``inject_events(inject_events(x))`` 与 ``inject_events(x)``
  序列化后字节完全一致（重跑不改字节，``git status`` 不会永久假脏）；
* 事件只是**引用**既有公共节点（``common.json`` / ``special_dungeon.json``），
  不复制判据（ADR-0003）。

链上页面与打断型事件不相交（#27）
----------------------------------
★**已是链上一步的页面，不得同时作为打断型事件注入**★（「链上页面 ∩ 打断型事件 = ∅」）。
前缀优先级更高：同一页面上，注入的打断型事件会**先命中并吃掉该帧**，链上的那一步
（显式后继）**永远轮不到**被评估。领主战族的「结算」页正是这种设计冲突：它既是链上的
一步（:data:`scene.chain.NODE_结算` → pipeline 的 ``SpecialResultContinue``，挂着 #22 的
收工闸），又曾被打断型事件组当成全局前缀（``PubResultContinue`` / ``PubQuestResult``）
注入每个节点 → 结算帧被前缀抢走、链上结算节点从不执行（#26 真机实证）。故「结算」事件
带 ``chain_page="结算页"``，不进 :data:`INTERRUPT_EVENTS`。守卫见
``scene.drift.chain_page_interrupt_drift``（``check_all`` 第 5 条）。

任何被注入的事件都不得命中链上步骤页面（#37 —— #18/#29/#37 的共同教训）
----------------------------------------------------------------------------
#18（归位自匹配【主城】）/#29（归位自匹配【列表页/详情页】）/#37（新角色自匹配
【降临讨伐列表页】）是同一族事故：一个被注入的事件，其判据命中了【链上本要执行另一步】
的页面，于是抢在那一步之前命中、吃掉这一帧，链无法恢复 → 循环到超时。

#27 只把这条不变量做在「打断型事件」这一半、且只到「结构性识别引用」这一层；
#29 只把「兜底型」那一半的判据收紧到能在真机帧上区分页面。**本票（#37）把它提升为
一条覆盖全部注入事件（打断型前缀 + 兜底型后缀）的通用不变量**，并用**真机帧模型**
逐「事件 × 链上步骤页面」验证（不只是 #37 这一个节点）：

    链上步骤页面 ∩ 被注入事件 = ∅        （页面集合见 ``scene.page_rules.chain_step_pages``）

枚举源是本模块的 :func:`injected_event_nodes`（打断型 + 兜底型的全部节点名）；
验证器与 prove-red 在 ``tools/contract_hooks/hooks_37.py``，离线跑法
``tools/test_inject_scope.py``。合法的「同判据」例外（如「挑战」事件 ``PubChallenge``
与链步 ``SpecialChallenge`` 认的是同一页同一按钮）在 hooks_37 里**显式豁免并点名**，
绝不静默放过。

明确**不做**：

* **卡死兜底不进事件层**（#5）：卡死是【活性】问题（画面连续静止），不是页面级情况。
  它保留为独立看门狗 ``WATCHDOG`` —— 本模块只声明它，并保证它不在事件层里
  （``watchdog_in_event_layer`` 恒为 ``False``）。

对应 ADR-0001（配置为真源 / 幂等注入）/ ADR-0002（兜底/恢复边在后）/ ADR-0003
（页面判据全局唯一，事件只引用）。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Iterable

from .page_rules import page_rules

# 注入类别（#18）：位置由类别决定，见 :func:`inject_events`。
INTERRUPT_KIND = "interrupt"  # 打断型 —— 注入在原有后继【之前】（前缀）
FALLBACK_KIND = "fallback"  # 兜底型 —— 注入在原有后继【之后】（后缀，最低优先级）
EVENT_KINDS = (INTERRUPT_KIND, FALLBACK_KIND)


@dataclass(frozen=True)
class Event:
    """一条跨场景通用事件。

    ``name``  情况名（GLOSSARY 用语，如「加载」「归位」）；
    ``nodes`` 注入到候选集里的 pipeline 节点名（按名引用既有公共节点）；
    ``note``  为什么它在事件层里；
    ``kind``  注入类别（#18）：``"interrupt"`` = 打断型（前缀）/ ``"fallback"`` = 兜底型
              （后缀，最低优先级回退）。**位置由 kind 决定**，见 :func:`inject_events`。
    ``chain_page``  非 None = 该事件锚定的页面是**链上的一步**（#27）：把它当打断型前缀
              注入会**遮蔽**链上的那一步（前缀优先级更高，见 :func:`inject_events`），
              故它不进 :data:`INTERRUPT_EVENTS`（仍在 :data:`EXCEPTION_EVENTS` 分类里）。
    """

    name: str
    nodes: tuple[str, ...]
    note: str = ""
    kind: str = INTERRUPT_KIND
    chain_page: str | None = None

    @property
    def refs(self) -> tuple[str, ...]:
        """注入到 ``next`` 里的引用形式（``[JumpBack]`` 调用，执行完回调用者重扫）。"""
        return tuple(f"[JumpBack]{n}" for n in self.nodes)


# ---------------------------------------------------------------------------
# 九类跨场景异常 —— 全项目【唯一一处】定义（#5）。顺序 = 注入顺序 = 候选集优先级。
# 它们全是**打断型**（前缀）：看到就先处理掉，再回到本节点的后继。
#
# ★开放决定★ 组内顺序沿用本票的枚举。真实 pipeline 把「换日」放最前（最临时的全局
#   打断：任何画面都可能弹）。#7 写 JSON 时若需完全贴合真实优先级，只改本元组顺序即可
#   （数据驱动，逻辑不动）。本票验收只要求「排在原有后继之前」，未规定组内顺序。
# ---------------------------------------------------------------------------
EXCEPTION_EVENTS: tuple[Event, ...] = (
    Event("加载", ("PubLoadingWait",), "公共加载等待（common.json）：只等待、不点击"),
    Event("结算", ("PubResultContinue", "PubQuestResult"), "结算推进 + QUESTRESULT 快进（common.json）", chain_page="结算页"),
    Event("换日", ("PubDailyPopup",), "换日弹窗（common.json）：最临时的全局打断"),
    Event("等级", ("PubLevelUpContinue",), "升级 / 等级最大结算页（common.json）"),
    Event("新角色", ("PubNewCharTap",), "新角色加入画面（common.json）"),
    Event("剧情", ("PubSkipStory",), "剧情页右上角「跳过」（common.json）"),
    Event("挑战", ("PubChallenge",), "编队页底部「挑战」（common.json）"),
    Event("加成弹窗", ("SpecialBonusNo",), "领主加成点数弹窗（special_dungeon.json）"),
    Event("招募", ("SpecialRecruitOpen",), "多人房间页「招募」（special_dungeon.json）"),
)

EXCEPTION_EVENT_NAMES: tuple[str, ...] = tuple(e.name for e in EXCEPTION_EVENTS)

# 打断型事件组（#18 命名）：= 九类异常；注入在候选集【前缀】。
# ★#27 更新★：不再是九类全量 —— 链上页面事件（「结算」）已从本组剔出（见下方 #27 说明），
#   否则它会以更高优先级遮蔽链上的结算节点。
# ★#27★：链上已有的页面不得同时作为打断型事件注入（「链上页面 ∩ 打断型事件 = ∅」）。
#   · 「结算」页是领主战族链上的一步（scene.chain.NODE_结算 → pipeline 的
#     SpecialResultContinue）；若再把它当全局前缀注入（旧：PubResultContinue /
#     PubQuestResult），前缀优先级更高 → 结算帧被 PubResultContinue 先吃掉、链上的
#     结算节点从未被评估（#26 真机实证：三个结算节点命中各 0、special_batch_finish
#     执行 0、SpecialBatchStop 0），#22 的收工闸永不执行。
#   · 故这里按事件的 chain_page 字段剔除链上页面事件：它仍在 EXCEPTION_EVENTS 的九类
#     分类里（taxonomy 不变），只是不再作为【注入】的全局打断前缀。
#   · 幻想 / 战阵 / 迷宫三条由枢纽分派的既有路径各有自己的结算链节点
#     （PhantomSettleContinueChallenge / PhantomSettleFallback / RaidContinue* /
#     FarmRetry），不依赖这个全局前缀，故行为不变。
INTERRUPT_EVENTS: tuple[Event, ...] = tuple(e for e in EXCEPTION_EVENTS if e.chain_page is None)


def chain_page_events(events: Iterable[Event] | None = None) -> tuple[Event, ...]:
    """链上页面事件（#27）：页面已是链的一步 → 不得作为打断型事件注入。"""
    src = EXCEPTION_EVENTS if events is None else tuple(events)
    return tuple(e for e in src if e.chain_page is not None)


# ---------------------------------------------------------------------------
# 归位（#8）：提升为通用事件，注入每个流程节点 —— 不再由各条场景链的链尾各自实现。
#
# ★#18 修正判据：兜底型判据不得自匹配目标状态★
#   原判据 OCR ^主城$ + ROI [0,1180,720,100]（照抄 recover.json::RecoverTapMainCityNav）
#   在主城页【恒为真】—— 主城页常驻底部导航标签「主城」实测 720 box=[157,1248,44,25]，
#   中心 (179,1260) 落在该 ROI 内。作为优先前缀注入时 → 自匹配 → 点空 → 死循环。
#   #18 起为 And（两段实测，真机帧 r1/r2/r3 vs pre_shot）：
#     · ^主城$ 在底部导航 ROI [0,1180,720,100] —— 「回主城」入口（底部导航）还在；
#     · ^返回$ 在底部导航【最左槽】ROI [0,1180,110,100] —— 说明当前是【非主城】子页面
#       （主城页最左槽是「主角色」，没有「返回」；列表页 / 详情页最左槽是「返回」）。
#
#   ★#29 再追加第三条：页面范围判别叶 PubReturnHomeOtherSection★
#     #18 的两叶 And 对**链上步骤页面**（列表 / 详情）仍然成立（它们也有 返回 + 主城底导）
#     → 兜底归位抢跑，滚动找行的 SpecialScrollList 永不执行（见上方 #29 段）。第三条把
#     范围收到「当前一级分区不是主城」：底导里**另一个**一级分区页签处于选中（橙色）。
#     主城分区的任何页面（含链上所有步骤页）都是「主城」页签高亮 → 第三条为假 → 不命中。
#     于是归位只在**真正该回主城**的页面（漂到别的分区）上命中。
#   点击目标（box_index=0）仍是「主城」标签框中心 —— 动作与原来一致，入口逐次收紧。
# ---------------------------------------------------------------------------
RETURN_HOME_NODE_NAME = "PubReturnHome"
# 子识别（判据分片；见 common.json 同名的三个手写节点，与 #5 的 PubDailyText/PubDailyOk 同型）：
RETURN_HOME_TEXT_NODE = "PubReturnHomeText"  # OCR ^主城$（底部导航，「回主城」入口还在）
RETURN_HOME_BACK_TAB_NODE = "PubReturnHomeBackTab"  # OCR ^返回$（底部导航最左槽 = 子页面）
RETURN_HOME_OTHER_SECTION_NODE = "PubReturnHomeOtherSection"  # #29：一级分区不是主城（另一分区页签高亮）
RETURN_HOME_NODE_SPEC: dict = {
    "recognition": {
        "type": "And",
        "param": {
            "all_of": [
                RETURN_HOME_TEXT_NODE,
                RETURN_HOME_BACK_TAB_NODE,
                RETURN_HOME_OTHER_SECTION_NODE,
            ],
            "box_index": 0,
        },
    },
    "action": {"type": "Click", "param": {}},
    "post_delay": 500,
    "next": [],
}

RETURN_HOME = Event(
    "归位",
    (RETURN_HOME_NODE_NAME,),
    "#8：从任意【非主城】页面一步回主城的通用事件；#18 起为兜底型（后缀），且判据不再自匹配主城",
    kind=FALLBACK_KIND,
)


# 兜底型事件组（#18 命名）：目前只有归位；注入在候选集【后缀】。
FALLBACK_EVENTS: tuple[Event, ...] = (RETURN_HOME,)

# 注入到每个流程节点候选集里的**事件组** = 打断型（前缀）+ 兜底型（后缀）。
EVENTS: tuple[Event, ...] = (*INTERRUPT_EVENTS, *FALLBACK_EVENTS)

# 事件层自带的节点定义（引用悬空时会一并注入，避免 next 指向不存在的节点）。
EVENT_NODE_DEFS: dict[str, dict] = {RETURN_HOME_NODE_NAME: RETURN_HOME_NODE_SPEC}


# ---------------------------------------------------------------------------
# 卡死兜底【不进事件层】（#5）：它是活性问题，保留为独立看门狗。
# 判据 / 动作照抄 special_dungeon.json::SpecialStallRecover（stall_recover + restart_game）。
# ---------------------------------------------------------------------------
WATCHDOG_NODE_NAME = "StallRecover"
WATCHDOG_NODE_SPEC: dict = {
    "recognition": {
        "type": "Custom",
        "param": {
            "custom_recognition": "stall_recover",
            "custom_recognition_param": {"threshold_sec": 180},
        },
    },
    "action": {"type": "Custom", "param": {"custom_action": "restart_game"}},
    "next": [],
}


def exception_event_names(events: Iterable[Event] | None = None) -> tuple[str, ...]:
    """九类异常的名称（默认取唯一一处定义 ``EXCEPTION_EVENTS``）。"""
    src = EXCEPTION_EVENTS if events is None else tuple(events)
    return tuple(e.name for e in src)


def event_refs(events: Iterable[Event] | None = None) -> tuple[str, ...]:
    """事件组注入到 ``next`` 里的全部引用（默认 = ``EVENTS``：九类异常 + 归位）。

    顺序 = 注入顺序（打断型前缀在前、兜底型后缀在后）；本函数不做位置区分，
    只给「全部引用」。要按注入位置分别取用 :func:`interrupt_refs` / :func:`fallback_refs`。
    """
    src = EVENTS if events is None else tuple(events)
    out: list[str] = []
    for e in src:
        out.extend(e.refs)
    return tuple(out)


def injected_event_nodes(events: Iterable[Event] | None = None) -> tuple[str, ...]:
    """被注入到流程节点候选集里的**全部事件节点名**（打断型前缀 + 兜底型后缀）。

    #37 的通用不变量「链上步骤页面 ∩ 被注入事件 = ∅」以此为枚举源：任何出现在这里的
    节点，其判据都不得命中 ``scene.page_rules.chain_step_pages`` 里的任一页面。
    保序去重（便于报告点名）。验证器见 ``tools/contract_hooks/hooks_37.py``。
    """
    src = EVENTS if events is None else tuple(events)
    out: list[str] = []
    for e in src:
        for n in e.nodes:
            if n not in out:
                out.append(n)
    return tuple(out)


def _refs_of_kind(events: Iterable[Event], kind: str) -> tuple[str, ...]:
    """按类别取引用（保序）。"""
    out: list[str] = []
    for e in events:
        if e.kind == kind:
            out.extend(e.refs)
    return tuple(out)


def interrupt_refs(events: Iterable[Event] | None = None) -> tuple[str, ...]:
    """打断型事件的引用（默认 = ``INTERRUPT_EVENTS``）；注入在每个流程节点的**前缀**。"""
    src = INTERRUPT_EVENTS if events is None else tuple(events)
    return _refs_of_kind(src, INTERRUPT_KIND)


def fallback_refs(events: Iterable[Event] | None = None) -> tuple[str, ...]:
    """兜底型事件的引用（默认 = ``FALLBACK_EVENTS``）；注入在每个流程节点的**后缀**。"""
    src = FALLBACK_EVENTS if events is None else tuple(events)
    return _refs_of_kind(src, FALLBACK_KIND)


def return_home_ref() -> str:
    """归位事件的注入引用（单步：一个节点）。"""
    return RETURN_HOME.refs[0]


def _event_node_names(events: tuple[Event, ...]) -> set[str]:
    """事件层自带节点定义的节点名（需要一并注入的那些）。"""
    return {n for e in events for n in e.nodes if n in EVENT_NODE_DEFS}


def inject_events(
    nodes: Mapping[str, object],
    flow_nodes: Iterable[str] | None = None,
    events: Iterable[Event] | None = None,
) -> dict:
    """把事件组注入到每个流程节点的候选集（``next``）里，**两类位置不同**（#18）。

    * ``nodes``       JSON 形映射 ``{节点名: 节点对象}``（不就地改入参，返回新 dict）；
    * ``flow_nodes``  要注入的流程节点名；缺省 = 所有含非空 ``next`` 的节点
                      （事件层自带节点不注入自己）；
    * ``events``      要注入的事件组；缺省 = ``EVENTS``（九类异常 + 归位）。

    注入形状（规范形）：

    ``next = [打断型前缀] + [原有后继…（最后一个除外）] + [兜底型后缀] + [最后一个原有后继]``

    即**打断型**（``kind="interrupt"``）排在原有后继**之前**；**兜底型**
    （``kind="fallback"``，如归位）排在原有后继**之后**、但补在节点**最后那条
    「恢复边 / 终点」之前**。为什么补在最后一条之前而不是整个列表末尾：本项目的每个流程
    节点，其 ``next`` 末位都是 DirectHit 兜底（枢纽 ``SpecialEntry``、``SpecialWait``、
    ``PhantomWait``），DirectHit **恒命中**，会遮蔽其后的任何候选；把兜底事件放在它后面
    等于死代码。放在它前面 = 「后继都不匹配时、落到兜底终点前的最低优先级回退」，既
    可达又最低优先（#18 的离线死循环复现依赖这一点）。

    **幂等**（ADR-0001）：对同一输入连续调用两次，结果序列化字节完全一致。
    做法：先把候选集里已有的全部事件引用摘掉，再按规范形重建 ——
    因此第二次调用与第一次得到同一份结果（不是「检测到就不再插」，而是「重建为规范形」）。
    """
    src = EVENTS if events is None else tuple(events)
    prefix = list(_refs_of_kind(src, INTERRUPT_KIND))
    suffix = list(_refs_of_kind(src, FALLBACK_KIND))
    ref_set = set(prefix) | set(suffix)

    injected: dict = copy.deepcopy(dict(nodes))

    # 事件层自带节点（如归位）必须在场，否则引用悬空。
    for name in _event_node_names(src):
        injected.setdefault(name, copy.deepcopy(EVENT_NODE_DEFS[name]))

    if flow_nodes is None:
        own = {n for e in src for n in e.nodes}
        flow_nodes = [
            name
            for name, spec in nodes.items()
            if name not in own and isinstance(spec, Mapping) and spec.get("next")
        ]

    for name in flow_nodes:
        spec = injected.get(name)
        if not isinstance(spec, MutableMapping):
            continue
        nxt = list(spec.get("next") or [])
        body = [x for x in nxt if x not in ref_set]
        tail = body[-1:] if body else []
        middle = body[:-1] if body else []
        spec["next"] = [*prefix, *middle, *suffix, *tail]

    return injected


def strip_events(
    nodes: Mapping[str, object],
    events: Iterable[Event] | None = None,
) -> dict:
    """把注入的「事件壳」剥掉，还原链的**形状**（不含任何事件引用）。

    与 ``inject_events`` 互为逆操作：``strip_events(inject_events(x)) == x``
    （当 ``x`` 本身事件免入时）—— 用来证明注入只是「加壳」，没有改链的形状。
    """
    src = EVENTS if events is None else tuple(events)
    ref_set = set(event_refs(src))
    own = _event_node_names(src)

    out: dict = {}
    for name, spec in nodes.items():
        if name in own:
            continue
        if isinstance(spec, Mapping):
            spec = dict(spec)
            nxt = spec.get("next")
            if isinstance(nxt, list):
                spec["next"] = [x for x in nxt if x not in ref_set]
        out[name] = spec
    return out


def is_event_free(
    nodes: Mapping[str, object],
    events: Iterable[Event] | None = None,
) -> bool:
    """链的形状里**看不到**事件：既无事件节点定义，也无事件引用。"""
    src = EVENTS if events is None else tuple(events)
    ref_set = set(event_refs(src))
    if _event_node_names(src) & set(nodes):
        return False
    for spec in nodes.values():
        if isinstance(spec, Mapping):
            for x in spec.get("next") or []:
                if x in ref_set:
                    return False
    return True


def watchdog_in_event_layer(events: Iterable[Event] | None = None) -> bool:
    """卡死兜底是否（错误地）出现在事件层里。恒应为 ``False``。"""
    src = EVENTS if events is None else tuple(events)
    if WATCHDOG_NODE_NAME in set(event_refs(src)):
        return True
    return any(WATCHDOG_NODE_NAME in e.nodes for e in src)


def validate_events(events: Iterable[Event] | None = None) -> list[str]:
    """校验事件层，返回错误列表（空 = 通过）。"""
    src = EVENTS if events is None else tuple(events)
    errors: list[str] = []

    counts: dict[str, int] = {}
    for e in src:
        counts[e.name] = counts.get(e.name, 0) + 1
        if not e.nodes:
            errors.append(f"事件 {e.name!r} 没有任何节点")
        if e.kind not in EVENT_KINDS:
            errors.append(
                f"事件 {e.name!r} 的注入类别 {e.kind!r} 非法（只允许 {EVENT_KINDS}）"
            )
    for name, n in counts.items():
        if n > 1:
            errors.append(f"事件名重复：{name!r} 被声明了 {n} 次（不得静默覆盖）")

    # #27：链上页面事件不得出现在打断型注入组里（构造上已保证；此处锁死，防手改）。
    for e in EXCEPTION_EVENTS:
        if e.chain_page is not None and e in INTERRUPT_EVENTS:
            errors.append(
                f"链上页面事件 {e.name!r}（页面 {e.chain_page!r}）不得作为打断型事件注入"
                f"（会遮蔽链上的那一步；#27）"
            )

    if watchdog_in_event_layer(src):
        errors.append(
            f"卡死兜底 {WATCHDOG_NODE_NAME!r} 不得出现在事件层里（它是活性看门狗，不是页面级事件）"
        )
    return errors


def injection_report(events: Iterable[Event] | None = None) -> dict:
    """注入报告：事件 → 引用 → 注入位置 → 看门狗（供人核对，不含实现细节）。"""
    src = EVENTS if events is None else tuple(events)
    return {
        "事件": [
            {"name": e.name, "refs": list(e.refs), "kind": e.kind, "note": e.note}
            for e in src
        ],
        "引用": list(event_refs(src)),
        "打断型前缀": list(_refs_of_kind(src, INTERRUPT_KIND)),
        "兜底型后缀": list(_refs_of_kind(src, FALLBACK_KIND)),
        "看门狗": WATCHDOG_NODE_NAME,
    }


def known_pages() -> tuple[str, ...]:
    """已知页面（全局判据注册表里的页面名，ADR-0003）。"""
    return tuple(r.name for r in page_rules())
