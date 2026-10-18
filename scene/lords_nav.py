# -*- coding: utf-8 -*-
"""领主战「全难度解禁」的**导航真源**（#100 第 1、2、3 条真机缺口的离线部分）。

本文件只回答四个问题，回答方式都是**可离线复核的纯数据 + 纯函数**（无 I/O、不碰设备、
不 import ``maa``）：

1. 这一帧的列表页**停在哪个页签**上？（:func:`tab_state` —— 只认**行族身份证据**）
2. 该不该**切页签**、点哪里、切完怎么算**确认**？（:meth:`NavState.switch_decision`）
3. 列表**滚到哪里了**、一次滚多少、怎么算**到底**？（:data:`SCROLL_PLAN` /
   :meth:`NavState.observe` / :meth:`NavState.may_scroll`）
4. ★**点目标之前该干什么**★：目标行不在屏上时，先**对页签**、再**上下找**
   （:class:`PickNav` / :meth:`PickNav.decide`）—— 三种失败原因必须分开（`:data:`PICK_REASON_TAB`
   / :data:`PICK_REASON_NOT_FOUND` / :data:`PICK_REASON_CLICK`）。
5. ★**这一帧是什么页面**（lords **自己的**状态名）+ **非列表页卡多久必须收工**★
   （:func:`page_state` / :data:`LORDS_STATES` / :data:`NON_LIST_STUCK_SEC`）——
   #100 第 4、5 个真机缺口：领主战也有「单人/多人」模式选择页，而旧链把它判成别的场景的
   状态名（``wuchong_mode``）后既不认识也没有有界出口。

★判据全部是**引用**，一条都不是本文件发明的★
--------------------------------------------
* **页签判据** = :mod:`scene.page_rules` 的 ``领主战页签`` / ``降临讨伐页签``（ADR-0003：
  页面判据全局唯一，场景只按名引用）。它们的来源链是：
  ``scene/page_rules.py`` ← ``special_dungeon.json::SpecialTabLord`` / ``::SpecialTabJoss``
  ← 真机帧 ``tools/frames/lord_page_tab_lord.png`` 的 OCR
  （``docs/research/lord-battle-difficulty-registry.md`` §2.1，**1080 空间原值逐字照抄**）。
  换算到本文件用的 **720 空间**（÷1.5，见 :mod:`scene.pixels`）后是::

      领主战（页签）    [135, 388, 90, 35]   （1080 空间原值 202/582/135/52，score 0.9998）
      降临讨伐（页签）  [481, 389, 117, 33]  （1080 空间原值 722/584/175/50，score 0.9997）
      更新列表          [615, 328, 82, 28]   （1080 空间原值 923/492/123/42，score 0.9998）

   ★本文件只写 720 空间的框★：1080 原值用 ``x/y/w/h`` 的写法标注出处，不写成四元组字面量
  （``hooks_99`` 的静态越界守卫会把它当 720 空间的框，>720 即红）。
* **点击点 = 该页签当帧 OCR 框的中心**（绝不写死坐标）。对账（720 空间）::

      领主战 框 [135, 388, 90, 35]   中心 (180.0, 405.5) ≈ SpecialTabLord 的 target (180, 405)
      降临讨伐 框 [481, 389, 117, 33] 中心 (539.5, 405.5) ≈ SpecialTabJoss 的 target (540, 404)

  ⇒ 「点标签框中心」与真机实测点击点**是同一处**（``hooks_100`` 的 ``lords-tab-confirm``
  逐帧对账这两组数字，飘开 2.5px 就红）。

* **行族判据** = ``scene/lords.py`` 的 ``kind`` + ``row_regex`` + ``SUBFAMILY_BY_KIND``
  （真源，本文件**不抄行名表**）。

* **滚动几何** = ``special_dungeon.json::SpecialScrollList`` 的真机实测值（#36/#42/#50 三次
  真机修正的产物）::

      Swipe begin [360, 1040] → end [360, 640]   （720 空间，行程 400px，duration 800ms）
      post_delay 2600                            （#42：受控滚动后列表还有惯性）
      列表体 y ∈ [440, 1180]                     （#36：手势两端都必须在列表体内）
      行距 ≈ 144px（720 空间）⇒ 400px ≈ 2~3 行

★六条纪律（都是踩过的坑，别在本票里重踩）★
------------------------------------------
1. **页签由目标决定，绝不靠 ``max_hit`` 竞速**（#19：两个页签节点各带 ``max_hit: 1``，
   首轮用尽后重进列表必被另一个抢先 → 列表翻到错子族 → 目标行不可见 → 归位 → 重开 →
   ~4.3s 一圈空转到 stall）。本文件的页签**只有一个**目标（:meth:`NavState.desired_tab`），
   而且切换后的确认条件**不是**「读得到标签」——两个标签**常驻同屏**
   （:data:`TAB_LABELS_ALWAYS_PRESENT`），读得到它什么也证明不了。
   确认 = **可见行族的身份证据**（真源里 ``kind`` → 子族），且**只允许点 1 次**
   （:data:`TAB_SWITCH_MAX_ATTEMPTS`，= 不重试）。
2. **滚动的上限绝不是 ``max_hit``**（#50：框架的命中计数是**按任务**共享的，一个 chunk
   里几个深行成员共用一个预算，用尽后节点被**静默跳过** → 目标行永远滚不到 → 空转）。
   本文件的停止条件是「**时间闩**（:attr:`ScrollPlan.min_interval_sec` ≥1.2s）+
   **明确的到底判据**（:meth:`NavState.observe`）」；计数
   (:attr:`ScrollPlan.max_scrolls_per_page`) 只是**最后一道兜底**，用尽时**带原因收工**，
   而**不是**静默跳过（半扫一遍的列表不能用来判「全部解禁」）。
3. **同一页里同一行只读一次**（:func:`row_key` = ``(行名, "N/M")``）：滚动会把上一屏的行
   带进下一屏，不去重就会把同一行读两遍 —— ``rows_read`` 虚高、
   ``plan_round`` 收到重复读数、日志里同一行打两遍。
4. ★**累计表按「行名」只留最新读数**★（:meth:`NavState.add_rows`）：``row_key`` 只用来判
   「**这一帧**里这一行读没读过」，**不是**累计表的键。按 ``(行名, N/M)`` 累计会让第 2 轮
   同时留着 ``(领主, 1/4)`` 与 ``(领主, 2/4)``，而 ``plan_round`` 对同名行只看**第一条** ⇒
   把**刚打完的档**当成新目标反复打，最后以「连续 2 轮无新解锁」误收工 ——
   「打没打过的，直到全 M/M」在第一次通关之后就再也到不了（R1）。
5. ★**扫描每轮重新武装**★（:meth:`NavState.begin_round`）：``complete_scan`` 之后若不复位
   ``sweep``，第 2 轮 ``page_pending`` 为真、``desired_tab()`` 却是 ``None`` ⇒ 不切页签、
   页签闸被跳过、``advance_tab`` 立刻宣布「两个页签都扫到底」（其实一个都没扫）（R2）。
   ★``reset()`` 全仓无人调用★：所以「新一轮重开」只能由 ``begin_round`` 承担。
6. ★**行名只在「列表行 ROI」里找**★（:data:`ROW_ROI` / :func:`row_roi_hit`）：名字出现在
   **标题 / 横幅 / 页签 / 底栏**里是**常态**，按名字找控件而不限定区域就一定会误点。真机 484
   第二轮验收（``debug/lords_accept3.log``）：tier 点完进的是**模式选择页**，页顶领主名
   ``无猾机兵`` 的框 ``[157, 154, 379, 94]``（中心 (346.5, 201)）被 ``find_row_box`` 当成
   列表行，连点同一个坐标 3 次无反应 —— 而真正的入口 ``单人游戏`` 在 (170,523)。
   ROI 的数值**不是本文件发明的**（引用 :data:`scene.options.TARGET_ROW_ROI`），见那里的对账。

★本文件不碰的边界★
------------------
* 不判「某账号能打哪几档」（账号状态；见 :mod:`scene.lords` 的 docstring）；
* 不判「列表页有几行」（那是 OCR 的事）；
* ★切页签后列表**不会**自动回顶部 —— 已由真机标定推翻旧假设★（``debug/lords_accept6.log``：
  第 2 轮「领主战」只读 4 行就判到底、切「降临讨伐」后两页签共 4 行 / 目标 0）。所以本文件
  现在把「回顶部」做成**每页开扫前的必做步骤**（:meth:`NavState.rewind_pending` /
  :meth:`NavState.observe_rewind`）：向上滚到「连续 N 个世代无新行 + 无位移」为止，
  有界（:attr:`ScrollPlan.max_rewinds_per_page`）、可验证（日志/detail 带滚了几次、是否到顶）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .config import DIFFICULTIES
from .lords import LORDS, SUBFAMILY_BY_KIND
from .lords_unlock import (
    MAX_NAME_DY,
    MIN_NAME_LEFT_GAP,
    NOT_A_ROW_NAME,
    RowReading,
    parse_progress,
)
from .options import TARGET_ROW_ROI
from .page_rules import page_rule
from .pixels import BASE_H, BASE_W

# ---------------------------------------------------------------------------
# 1. 页签：扫哪两个、判据在哪、点哪里、怎么算确认
# ---------------------------------------------------------------------------
#: 列表页的两个子族页签，**顺序 = 界面从左到右**（真机帧 ``lord_page_tab_lord.png``：
#: 领主战 x∈[202,337]、降临讨伐 x∈[722,897]，1080 空间）。
#: 值域与 ``scene.lords.SUBFAMILY_BY_KIND`` 一致（★这是同一个词表，不是第二份★）。
LORD_TABS: tuple[str, ...] = ("领主战", "降临讨伐")

#: ★两个页签标签**常驻同屏**★（真机帧同一帧里读到两个标签，score 0.9998 / 0.9997）。
#: 后果：**「读得到目标页签的标签」不能当作「当前就在这个页签上」** ——
#: 这正是 #19 那种「点一下就当切好了」的自我欺骗。确认条件见 :func:`tab_state`。
TAB_LABELS_ALWAYS_PRESENT: bool = True

#: 列表页判据的字面量（= :mod:`scene.page_rules` 的 ``领主战列表页``；详情页没有它）。
LIST_PAGE_ANCHOR: str = "更新列表"

#: 确认条件的**口径**（写成一个常量是为了让守卫能把它和实现一起钉住，而不是只写在注释里）。
CONFIRM_BASIS: str = (
    "切页签后的确认 = ①这一帧仍是列表页（读得到「更新列表」）∧ "
    "②可见行的族身份**一致**指向目标页签（scene/lords.py 的 kind + row_regex → SUBFAMILY_BY_KIND）。"
    "★「读得到页签标签」不算确认★：两个标签常驻同屏，读得到它什么也证明不了"
)

#: 页签切换的**尝试上限（含首次）**。= **1** ⇒ **不重试**。
#: 依据 #19：切页签失败后重试会把「点 A → 未确认 → 点 B → 未确认」变成 ~4.3s 一圈的竞速
#: 死循环。所以切一次、确认一次；确认不过就回枢纽，由枢纽走别的路（或带原因收工）。
TAB_SWITCH_MAX_ATTEMPTS: int = 1

#: 连续多少次「已无重试余量、却仍未确认」→ **带原因收工**（而不是回枢纽无限轮询）。
TAB_UNCONFIRMED_LIMIT: int = 2

#: 「未确认」的**宽限期**（秒）：点了页签之后至少给它这么久，慢帧才不会被算成「失败」。
#: 没有它的话，枢纽 800ms 一圈会把「页面还在加载」连记成两三次失败 —— 一次慢加载
#: 就把整趟任务判死（那是 #19 的反面：那次是太急着重试，这次会变成太急着收工）。
#: 宽限期过后才开始累计 :data:`TAB_UNCONFIRMED_LIMIT`。
TAB_CONFIRM_GRACE_SEC: float = 4.0

#: 搜索「列表到底了」的**尾部锚点**文本（例如某天出现「已无更多」这种行）。
#: ★现在是空的，这是诚实的空缺★：仓内**没有**滚到列表底部的真机帧
#: （``docs/research/lord-battle-all-difficulty-unlock.md`` §4 第 13 项仍待采集），
#: 所以到底判据用**几何证据**（:meth:`NavState.observe`：滚完之后有没有新行 / 有没有位移），
#: 不猜任何不存在的文案。将来拿到帧就在这张表里登记原文（机制已经接好并单测过：
#: 注入一个命中即当到底，见 ``tools/test_lords_nav.py``）。
END_ANCHORS: tuple[str, ...] = ()


@dataclass(frozen=True)
class TabAnchor:
    """一个页签的判据 + 点击落点（坐标一律 **720 空间**）。"""

    tab: str
    #: 标签的 OCR 正则（逐字来自 :mod:`scene.page_rules`，**不是**本文件写的）。
    expected: tuple[str, ...]
    #: 标签所在 ROI（720 空间；限在页签行，避免列表行里的分类字命中）。
    roi: tuple[int, int, int, int]
    #: 既有的真机点击点（``special_dungeon.json::SpecialTab*`` 的 ``action.target``）。
    #: ★只作**对账**用★：运行时点的是**当帧 OCR 框的中心**，不是这个常量。
    click_hint: tuple[int, int]
    #: 判据 / 数字的出处（人读 + 守卫可机械核对的那一串）。
    source: str

    def hits(self, text: str) -> bool:
        """这段文本是不是这个页签的标签（正则来自 page_rules）。"""
        return any(re.search(p, text or "") for p in self.expected)


def _anchor(tab: str, page_name: str, click_hint: tuple[int, int], upstream: str) -> TabAnchor:
    """从 :mod:`scene.page_rules` **引用**判据，拼出一个页签锚点（绝不复制判据）。"""
    rule = page_rule(page_name)
    param = rule.recognition.get("param") or {}
    expected = tuple(param.get("expected") or ())
    roi = tuple(param.get("roi") or (0, 0, 720, 1280))
    return TabAnchor(
        tab=tab,
        expected=expected,
        roi=(int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])),
        click_hint=tuple(click_hint),
        source=f"scene/page_rules.py::{page_name} ← {upstream}（{rule.note}）",
    )


#: ``{页签: 判据}``（★引用 page_rules，不复制★；守卫 hooks_100 逐字段对账）。
TAB_ANCHORS: dict[str, TabAnchor] = {
    "领主战": _anchor(
        "领主战",
        "领主战页签",
        (180, 405),
        "special_dungeon.json::SpecialTabLord；点击点真机实测 (180,405)",
    ),
    "降临讨伐": _anchor(
        "降临讨伐",
        "降临讨伐页签",
        (540, 404),
        "special_dungeon.json::SpecialTabJoss；点击点真机实测 (540,404)",
    ),
}


# ---------------------------------------------------------------------------
# 2. 页签状态：**只认行族身份证据**
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TabEvidence:
    """一帧的页签证据（纯数据；由 :func:`tab_state` 从 OCR 项算出来）。"""

    #: 这一帧是不是列表页（判据 ``更新列表``）。
    list_page: bool
    #: 这一帧读到了哪些页签标签（★常驻两枚，所以它**不是**「当前选中谁」的证据★）。
    labels: frozenset[str]
    #: **确认出来的**当前页签；``None`` = 证据不足或自相矛盾（★不猜★）。
    confirmed: str | None
    #: 这一帧认出来的行族（``lord`` / ``joss``，可能两种都有 = 矛盾）。
    kinds: tuple[str, ...]
    #: 认不出族的行名（新成员 / 活动行 / OCR 读错）—— ★不参与确认，但也不静默丢★。
    unknown_rows: tuple[str, ...]


def _box4(box) -> tuple[int, int, int, int]:
    return (int(box[0]), int(box[1]), int(box[2]), int(box[3]))


def _center(box) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


# ---------------------------------------------------------------------------
# 2b. 屏幕边界：「行在屏上」的判据（#100 回归：解禁 0 场）
# ---------------------------------------------------------------------------
#: 屏幕边界（720 空间）—— **引用** :mod:`scene.pixels` 的基准空间，不抄第二份数字。
SCREEN_W: int = BASE_W
SCREEN_H: int = BASE_H


def on_screen(box) -> bool:
    """这个框是不是**整框落在 720x1280 屏幕内**（``0 <= x`` ∧ ``x+w <= 720`` ∧
    ``0 <= y`` ∧ ``y+h <= 1280``）。

    ★为什么需要★：``agent/lords_impl._synthesize_items`` 把两个页签的累计读数还原成一帧
    「合成 OCR」，行名 y = 460 + k*144 —— 720 空间只有 1280 高，**从第 7 行（k=6，y=1324）
    起就不在屏幕上**；``find_row_box`` 在诊断路径（``apply_roi=False``）上照样找得到它。若据此断言
    「行就在屏上」，就会把「扫描读到的第 N 行」说成「实时卡住」（真机 #100 解禁 0 场的误收工
    现场；框的写法按本仓约定写成 ``x/y/w/h`` —— 它 y+h 早已越过 1280）::

        [lords] 收工：找到了但点不动：目标「无猾机兵」的行就在屏上
                （行框 202/1468/197/28），却已经 52s 点不出去

    ）。真实抓帧同形：行框越界 = 行不在屏上（刚被滚出屏幕 / OCR 给了屏外框）。

    ``box`` = 四元组/四元序列（720 空间，``[x, y, w, h]``）。解不开（``None`` / 非四元 /
    不可转数）或越界一律 ``False`` —— ★越界就是不在屏上，绝不拿「找到了框」冒充「行在屏上」★。
    """
    try:
        x, y, w, h = (float(value) for value in box)
    except (TypeError, ValueError):
        return False
    return 0 <= x and 0 <= y and x + w <= SCREEN_W and y + h <= SCREEN_H


def _row_cy(row):
    """行读数的**纵向中心**（720 空间）；拿不到框返回 ``None``（★不拿 0 冒充★）。"""
    box = getattr(row, "name_box", None)
    if box is None and isinstance(row, Mapping):
        box = row.get("name_box")
    if not box or len(tuple(box)) != 4:
        return None
    return _center(tuple(box))[1]


def label_box(items, anchor: TabAnchor):
    """页签标签的 OCR 框（720 空间）；认不出返回 ``None``。

    判据与 :mod:`scene.drift` / ``hooks_19`` 同一口径：正则命中 **且** 框中心落在
    ``anchor.roi`` 内（ROI 限页签行，列表行里的同名分类字不算）。
    """
    x, y, w, h = anchor.roi
    for text, box in items or []:
        if not anchor.hits(str(text or "")):
            continue
        if len(box) != 4:
            continue
        cx, cy = _center(box)
        if x <= cx <= x + w and y <= cy <= y + h:
            return _box4(box)
    return None


def tab_labels(items) -> frozenset[str]:
    """这一帧读到了哪些页签标签（纯存在性；★不表示谁被选中★）。"""
    found = set()
    for tab, anchor in TAB_ANCHORS.items():
        if label_box(items, anchor) is not None:
            found.add(tab)
    return frozenset(found)


def list_page_present(items) -> bool:
    """这一帧是不是**领主战列表页**（判据 = ``更新列表``，详情页没有它）。"""
    return any(LIST_PAGE_ANCHOR in str(text or "") for text, _box in items or [])


def classify_kind(name: str, registry: Sequence | None = None) -> str | None:
    """把一个**行名**归到子族（``lord`` / ``joss``）；认不出返回 ``None``（★不猜★）。

    判据 = ``scene/lords.py`` 的 ``row_regex``（真机实测过的容错正则，如
    ``^红嫉族?机兵$``）。``registry`` 可注入（离线测试 / 安装态冻结花名册用）。
    """
    text = str(name or "").strip()
    if not text:
        return None
    for entry in (LORDS if registry is None else registry):
        try:
            if re.search(entry.row_regex, text):
                return entry.kind
        except re.error:                                   # 数据坏了：绝不静默当「不认识」
            raise
    return None


def tab_of_kind(kind: str | None) -> str | None:
    """``kind`` → 页签名（= ``scene.lords.SUBFAMILY_BY_KIND``，真源）。"""
    if not kind:
        return None
    return SUBFAMILY_BY_KIND.get(kind)


def tab_of_row(row_name: str, registry: Sequence | None = None) -> str | None:
    """行名 → 它所在页签（#19 的口径：**页签由目标决定**）。"""
    return tab_of_kind(classify_kind(row_name, registry))


def tab_state(items, registry: Sequence | None = None) -> TabEvidence:
    """一帧 OCR 项 → :class:`TabEvidence`（页签证据）。

    确认规则（**这是切换后的确认条件**，见 :data:`CONFIRM_BASIS`）：

    * ``list_page`` 为假 → ``confirmed=None``（不在列表页，什么都不算）；
    * 认出来的行族**恰好一种** → 该族对应的页签即 ``confirmed``；
    * 两种都出现（矛盾）/ 一种都没有（证据不足）→ ``confirmed=None``。

    ★为什么不用「读得到标签」当确认★：两个标签**常驻同屏**（:data:`TAB_LABELS_ALWAYS_PRESENT`），
    用它确认等于「点完就当成功」—— #19 的死循环就是这么来的。
    """
    rows: list[str] = []
    for text, _box in items or []:
        stripped = str(text or "").strip()
        if not stripped:
            continue
        if any(anchor.hits(stripped) for anchor in TAB_ANCHORS.values()):
            continue                                   # 页签标签自己不是行名
        if LIST_PAGE_ANCHOR in stripped:
            continue                                   # 列表页固定元素
        if stripped in NOT_A_ROW_NAME:
            continue                                   # 列表页上的固定字（与 group_progress_rows 同口径）
        if parse_progress(stripped) is not None:
            continue                                   # 「通关数 N/M」不是行名
        rows.append(stripped)

    kinds: list[str] = []
    unknown: list[str] = []
    for text in rows:
        kind = classify_kind(text, registry)
        if kind is None:
            unknown.append(text)
            continue
        if kind not in kinds:
            kinds.append(kind)

    listed = list_page_present(items)
    confirmed = None
    if listed and len(kinds) == 1:
        confirmed = tab_of_kind(kinds[0])
    return TabEvidence(
        list_page=listed,
        labels=tab_labels(items),
        confirmed=confirmed,
        kinds=tuple(kinds),
        unknown_rows=tuple(unknown),
    )


def end_anchor_hit(items) -> str | None:
    """这一帧里出现的**列表尾锚点**原文（:data:`END_ANCHORS`）；没有则 ``None``。

    ★当前数据是空的★（仓内没有滚到底的真机帧）—— 机制已经接好：将来登记文案即生效，
    判据一经命中就当「到底」，不必再等两次「滚不动」。
    """
    for text, _box in items or []:
        stripped = str(text or "").strip()
        for anchor in END_ANCHORS:
            if anchor and anchor in stripped:
                return anchor
    return None


# ---------------------------------------------------------------------------
# 3. 滚动计划（一次多少 / 最多几次 / 怎么算到底）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScrollPlan:
    """列表滚动计划（数值逐条有出处；★没有一条是随手取的★）。"""

    #: 一次滚动的**行程**（720 空间像素）= ``SpecialScrollList`` 的 begin→end。
    travel_px: int
    #: 手势起点 / 终点（720 空间；★两端都落在列表体内★，见 :attr:`list_body`）。
    begin: tuple[int, int]
    end: tuple[int, int]
    #: 手势时长（ms）。800 = 「明确的拖拽」而不是「甩动」（#42：甩动会把抬手读成选行）。
    duration_ms: int
    #: 滚完之后的**稳定等待**（ms；= ``SpecialScrollList.post_delay`` 2600，#42 惯性）。
    settle_ms: int
    #: ★时间闩★：两次滚动之间至少隔这么久（秒）。这是**主停止条件之一**（#50 的反面）。
    min_interval_sec: float
    #: 每页（= 每个页签的一轮扫描）最多滚几次。★这是**最后一道兜底**，不是主判据★：
    #: 用尽时**带原因收工**（半扫一遍的列表不能用来判「全部解禁」），绝不静默跳过。
    #: 数值 = 80，与 ``SpecialScrollList.max_hit`` 同口径（#50 真机：29 行列表里最深的行
    #: 要 ~23 次受控滚动，30 会把它误判成「不可达」，故抬到 80 且仍有界）。
    max_scrolls_per_page: int
    #: **到底判据**：连续这么多次滚动「既没有新行、纵向位移也 ≤ :attr:`no_move_px`」= 到底。
    #: 2 = 一次可能是偶发（加载/惯性抖动），两次才算数（"数连续几次没滑动" 是同类实现的通行做法）。
    stable_times: int
    #: 判定「没动」的纵向位移阈值（720 空间）。真机一次滚动 400px、OCR 框抖动 ≤2px，
    #: 两者差两个数量级，取 4 既不会把「滚了」误判成「没滚」，也不会把抖动当成滚动。
    no_move_px: int
    #: ★每轮扫描开始前「回顶部」的上滚次数上限★（#100 第 6 轮真机验收：战后列表停在被点行处，
    #: 第 2 轮只向下滚 ⇒ 只读到 4 行就判「到底」）。「到底」是**相对滚动位置**的概念 ——
    #: 每轮必须从**顶部**开始扫，否则第二轮的「到底」毫无意义。
    #: 数值依据：花名册 46 位 / 一次上滚露出 ~2 行 ≈ 23 次 ⇒ 取 **24**（有界，且留一次余量）；
    #: ★这是**回顶部**的预算，与向下扫的 :attr:`max_scrolls_per_page` 分开记账★（两本账互不影响）。
    max_rewinds_per_page: int
    #: 列表体（720 空间 ``(y_top, y_bottom)``）：手势两端都必须在里面（#36 真机事故）。
    list_body: tuple[int, int]
    source: str

    # -- 派生 ---------------------------------------------------------------
    @property
    def max_scrolls_total(self) -> int:
        """两个页签各一份预算 → 整趟扫描的**滚动次数上限**（有界性的算术表达）。"""
        return self.max_scrolls_per_page * len(LORD_TABS)

    def in_list_body(self, point: tuple[int, int]) -> bool:
        """这个点是否落在列表体内（#36：手势两端都必须在列表体里）。"""
        return self.list_body[0] <= point[1] <= self.list_body[1]

    @property
    def up_begin(self) -> tuple[int, int]:
        """★**向上**滚（回顶部）的起点★ = :attr:`end`（**反向**同一个手势，不新增第二份数字）。

        为什么要它：:attr:`begin` / :attr:`end` 描述的是「手指上移 ⇒ 内容上移 ⇒ 露出**下面**的行」
        （= 向下滚）。要找**上面**的行就得反着来（手指下移）。几何仍然只能有**一份**来源，
        所以这里只是把同一对端点**交换**，不写死新坐标（两端仍在 :attr:`list_body` 内 ⇒
        :attr:`geometry_ok` 对两个方向同时成立）。
        """
        return self.end

    @property
    def up_end(self) -> tuple[int, int]:
        """★**向上**滚的终点★ = :attr:`begin`（见 :attr:`up_begin`）。"""
        return self.begin

    @property
    def geometry_ok(self) -> bool:
        """手势两端都在列表体内（守卫 / 破坏实验直接读这一条）。"""
        return self.in_list_body(self.begin) and self.in_list_body(self.end)


#: 唯一一份滚动计划。
SCROLL_PLAN: ScrollPlan = ScrollPlan(
    travel_px=400,
    begin=(360, 1040),
    end=(360, 640),
    duration_ms=800,
    settle_ms=2600,
    min_interval_sec=1.2,
    max_scrolls_per_page=80,
    stable_times=2,
    no_move_px=4,
    max_rewinds_per_page=24,
    list_body=(440, 1180),
    source=(
        "special_dungeon.json::SpecialScrollList（begin [360,1040] → end [360,640]，duration 800，"
        "post_delay 2600 = #42 惯性；列表体 y∈[440,1180] = #36；400px≈2~3 行，行距≈144px）；"
        "次数 80 = #50 真机上调（29 行列表最深行 ~23 次）；时间闩 1.2s = 本票硬要求；"
        "回顶部上限 24 = 46 位成员 / 一次上滚露 ~2 行 ≈ 23（每轮都要从顶部开始扫，#100 第 6 轮真机）"
    ),
)

#: 两个滚动端点之间是不是**严格竖直**（dx=0）。SPECIAL：MAA 的 Swipe 四元素写法会被当成
#: 「区域」而不是「定点」，于是 dx 会随机乱跳（#42 真机：begin x∈[362,710]）——
#: 这里把「严格竖直」变成一条可断言的属性，守卫据此钉住。
assert SCROLL_PLAN.begin[0] == SCROLL_PLAN.end[0], "滚动必须严格竖直（dx=0）"

#: 导航侧的**无进展死线**（秒）：页签/滚动/读页都不再有进展这么久 → 带原因收工。
#: 口径照 ``agent/lords_impl.STUCK_SEC``（20s）与 #62 的有界跳过：一个读不出的页面不许
#: 把整趟解禁拖死。这里给 30s，因为「滚一次 + 等稳定」本身就要 ~2.6s。
NAV_STUCK_SEC: float = 30.0


# ---------------------------------------------------------------------------
# 3b. 列表**行名**的 ROI：行名只可能在列表体里（#100 第三轮真机：模式页标题被当成行）
# ---------------------------------------------------------------------------
#: 列表行名的 OCR 区域（720 空间 ``(x, y, w, h)``）—— ★行名**只可能**在这里★。
#:
#: ★数值不是本文件发明的★：直接引用 :data:`scene.options.TARGET_ROW_ROI`
#: （= ``assets/interface.json::SpecialEnterBoss`` 的**行名 OCR ROI**；``scene/drift.py``
#: 逐字钉着它与 pipeline 的关系；``scene/lord_battle.py`` 的真机读数也引用同一个框）。
#: 720 空间 ``(150, 440, 320, 800)`` ⇒ ``x ∈ [150, 470]``、``y ∈ [440, 1240]``。
#: **不写第三份数字**：这里只引用 + 与既有列表几何对账（见下面的 assert）：
#:
#: * 上边界 == :attr:`ScrollPlan.list_body` 的起点（440 = 列表体，#36 真机事故的产物）；
#: * 上边界在**页签行之下**（:data:`TAB_ANCHORS` 的 ROI 下沿 435；页签栏 y≈386–424）；
#: * 整框落在 720x1280 屏内，且下边界 1240 在**底部导航带**（y≥1244）之上。
#:
#: ★为什么必须有它（真机 484 第二轮验收，``debug/lords_accept3.log``）★：tier 点完后设备进的
#: 是**模式选择页**（``state=lords_mode``），页顶领主名的框是 ``[157, 154, 379, 94]``
#: （中心 **(346.5, 201)**）；旧 ``find_row_box`` **只按名字匹配、不限定区域**，把**标题**
#: 当成了列表行，于是连点 ``@720(346,201)`` 三次无反应 —— 而真正的入口 ``单人游戏`` 在
#: ``[78, 497, 184, 52]``（中心 (170,523)）。名字出现在标题 / 横幅 / 页签 / 底栏里是**常态**，
#: 不限定区域就一定会误点。
ROW_ROI: tuple[int, int, int, int] = tuple(TARGET_ROW_ROI)

#: 页签行的**底边**（= 两个页签 ROI 的下沿最大值；**由数据算出**，不另写数字）。
TAB_BAND_BOTTOM: int = max(
    TAB_ANCHORS[tab].roi[1] + TAB_ANCHORS[tab].roi[3] for tab in LORD_TABS
)

assert len(ROW_ROI) == 4, "行名 ROI 必须是一个四元组（720 空间 x/y/w/h）"
assert ROW_ROI[1] == SCROLL_PLAN.list_body[0], "行名 ROI 的上边界必须 = 列表体起点（440）"
assert ROW_ROI[1] >= TAB_BAND_BOTTOM, "行名 ROI 必须在页签行之下（页签栏不是列表行）"
assert ROW_ROI[0] >= 0 and ROW_ROI[1] >= 0, "行名 ROI 不许越过屏幕左上角"
assert ROW_ROI[0] + ROW_ROI[2] <= SCREEN_W, "行名 ROI 不许越过屏幕右边界"
assert ROW_ROI[1] + ROW_ROI[3] <= SCREEN_H, "行名 ROI 不许越过屏幕下边界"


def row_roi_hit(box) -> bool:
    """这个框是不是**列表行**的框：**框中心**落在 :data:`ROW_ROI` 内。

    口径与 :func:`label_box` / ``scene.lords_nav._text_box_in_roi`` 一致（都用框中心：
    OCR 框可能贴边溢出一两个像素，中心才是控件的位置），所以这里的判定与
    ``agent/lords_impl.find_row_box`` 的 ROI 过滤是**同一条**判据。

    ★越界 / 解不开的框一律 ``False``★：标题 / 横幅 / 页签 / 底栏都不是列表行 ——
    绝不拿「读到一个同名框」冒充「目标行在列表里」。
    """
    try:
        quad = _box4(box)
    except (TypeError, IndexError, KeyError, ValueError):
        return False
    cx, cy = _center(quad)
    x, y, w, h = ROW_ROI
    return x <= cx <= x + w and y <= cy <= y + h


# ---------------------------------------------------------------------------
# 4. 去重键：同一页里同一行只读一次
# ---------------------------------------------------------------------------
#: ``N/M`` 的字面分隔符（与真机读数 ``通关数3/4`` 一致；去重键是给人看的，所以用它）。
PAIR_SEP: str = "/"


def _row_triple(row) -> tuple[str, int, int]:
    """一行读数归一成 ``(行名, N, M)``。

    容忍 :class:`scene.lords_unlock.RowReading` / 三元组 / 含 ``name``/``n``/``m`` 的映射
    （离线测试与真机注入同一个入口；安装态快照 ``agent/lords_impl`` 有逐字副本）。
    """
    if isinstance(row, RowReading):
        name, n, m = row.name, row.n, row.m
    elif isinstance(row, Mapping):
        name, n, m = str(row.get("name", "")), int(row["n"]), int(row["m"])
    else:
        name, n, m = str(row[0]), int(row[1]), int(row[2])
    return (str(name).strip(), int(n), int(m))


def row_key(row) -> tuple[str, str]:
    """一行的**本帧去重键** = ``(行名, "N/M")``。

    为什么是这两段：滚动会把上一屏的行带进下一屏，只按行名去重会把「同一行、进度变了」
    误吞（那是真·新信息）；只按进度去重会把不同行合并。``(行名, N/M)`` 同时满足：
    同一行同一进度**只记一次**，行或进度任一变化都算「这一帧的新读数」。

    ★它**不是**累计表的键★：累计表按**行名**存最新读数（见
    :meth:`NavState.add_rows` 与模块 docstring 第 4 条纪律）—— 用 ``row_key`` 当累计键会让
    同一行跨轮留下旧/新两条读数，``plan_round`` 取第一条 ⇒ 反复打刚打完的档（R1）。

    容忍 :class:`scene.lords_unlock.RowReading` / 三元组 / 含 ``name``/``n``/``m`` 的映射
    （离线测试与真机注入同一个入口）。
    """
    name, n, m = _row_triple(row)
    return (name, f"{n}{PAIR_SEP}{m}")


# ---------------------------------------------------------------------------
# 5. 导航状态机（页签扫描 + 页内滚动 + 去重累计）—— 纯逻辑，无 I/O
# ---------------------------------------------------------------------------
#: :class:`TabDecision` 的 action 取值（★每一条都有各自的处置★）。
ACTION_OK = "ok"                 # 已在目标页签且已确认 —— 什么都不做
ACTION_CLICK = "click"           # 点这个框切页签（唯一一种「动手」）
ACTION_GIVE_UP = "give_up"       # 已无重试余量仍未确认 —— 回枢纽，**不重试**
ACTION_STOP = "stop"             # 连续多次未确认 —— 带原因收工（防 #19 那种竞速空转）
ACTION_CANNOT = "cannot"         # 这一帧什么也做不了（不在列表页 / 读不到标签框）


@dataclass(frozen=True)
class TabDecision:
    """「页签这一步该干什么」的判决（纯数据；由 :meth:`NavState.switch_decision` 给出）。"""

    action: str
    #: 目标页签（``ACTION_CANNOT`` 时可能是 ``None``）。
    target: str | None
    #: ``ACTION_CLICK`` 时要点的框（720 空间；= 当帧 OCR 框，绝不写死坐标）。
    box: tuple[int, int, int, int] | None
    #: 为什么（人读；日志与 detail 都带它）。
    reason: str


@dataclass
class NavState:
    """一趟解禁任务的**导航状态**（页签扫描进度 + 页内滚动计数 + 去重累计）。

    ★它只存「喂给纯函数的事实」★：判定在方法里，I/O 在 ``agent/lords_impl.py``。
    字段语义：

    * ``sweep_index`` / ``sweep_done`` —— 两个页签的**扫描进度**（顺序 = :data:`LORD_TABS`）；
    * ``sweep_round`` —— 已扫完的那一轮（``Session.round_index`` 的值），用于「每轮重扫」；
    * ``switch_attempts`` / ``switch_for`` —— 当前这次切换已经点了几次（**上限 1**）；
    * ``unconfirmed`` —— 连续多少次「无重试余量仍未确认」（达 :data:`TAB_UNCONFIRMED_LIMIT` 收工）；
    * ``scrolls_in_page`` / ``stable_scrolls`` / ``last_scroll_at`` / ``last_rows`` —— 页内滚动；
      ``scroll_gen`` / ``stable_gen`` —— **滚动世代**：到底判据按世代记账（同一世代只记一次，
      没真的滚过就不记账；见 :meth:`observe`）；
    * ★``rewind_*`` —— **每页开扫前的「回顶部」**★（#100 第 6 轮真机验收）：战后列表停在
      被点行处，第 2 轮只向下滚 ⇒ 只读到 4 行就判「到底」。判据 = 连续 ``stable_times`` 个
      **回顶部世代**都没有新行 + 纵向上移位移 ≤ ``no_move_px``（见 :meth:`observe_rewind`）；
      预算 = :attr:`ScrollPlan.max_rewinds_per_page`（有界，用尽**带原因收工**）；
    * ``dropped_in_scan`` / ``top_unconfirmed`` / ``tab_switch_failed`` —— ★本轮扫描的
      **完整性账**★（只在 :meth:`begin_round` 复位）：被徽标剔掉的行数 / 没确认到顶就收尾的
      页数 / 页签没切成功。零目标时用它们写**正确原因**（绝不再落到「滚动上限」）；
    * ``no_move_*`` / ``bottom_unprovable`` —— 有行被徽标剔掉时，用**位移**判「列表滚不动了
      但底不可证」（本页按扫描不完整收尾，绝不宣布「到底」）；
    * ``seen`` —— 累计读数 ``{**行名**: 最新 RowReading}``（★不是 ``{row_key: 读数}``★：同一行
      只留 ``N`` 最大的那一条，见 :meth:`add_rows`）；
    * ``last_progress_at`` —— 最近一次**有进展**的时刻（页签确认 / 滚动 / 读到新行 / 判完一轮）。
    """

    sweep_index: int = 0
    sweep_done: bool = False
    sweep_round: int = -1
    switch_attempts: int = 0
    switch_for: str | None = None
    unconfirmed: int = 0
    scrolls_in_page: int = 0
    stable_scrolls: int = 0
    #: ★滚动世代★：:meth:`note_scroll` 每真的滚一次 +1。到底判据按**世代**记账（同一世代
    #: 只记一次）—— 否则 ``LordsScanPage`` 被 ``[JumpBack]PubLoadingWait`` / ``PubDailyPopup``
    #: 弹回来重读**同一屏**，两帧就判「到底」了（其实一次都没滚）。
    scroll_gen: int = 0
    #: 最近一次**记过账**的滚动世代（``-1`` = 还没记过）。
    stable_gen: int = -1
    last_scroll_at: float = 0.0
    last_rows: tuple = ()
    #: ★累计读数：``{行名: 最新 RowReading}``★（同一行只留 N 最大的那一条）。
    seen: dict = field(default_factory=dict)
    last_progress_at: float = 0.0
    # -- ★本票 a：每页开扫前「回顶部」（有界 + 可验证）★ --------------------
    #: 本页是否已**确认**在顶部（``False`` = 还没回完，先别向下扫）。
    #: ★默认 ``False``★：**每一页**（含第一轮）都先证明自己在顶上，不拿「列表大概在顶部」赌。
    rewind_done: bool = False
    #: 回顶部已经上滚了几次 / 回顶部世代 / 记过账的世代 / 连续「上滚无位移 + 无新行」次数。
    rewind_scrolls: int = 0
    rewind_gen: int = 0
    rewind_stable_gen: int = -1
    rewind_stable: int = 0
    rewind_last_rows: tuple = ()
    #: ★回顶部预算用尽仍未到顶★（sticky）：调用方据此**带原因收工**，绝不无限上滚。
    rewind_failed: bool = False
    # -- ★本票 c/d：本轮扫描的完整性账（只在 begin_round 复位）★ -------------
    #: 扫描期间被徽标**整行剔掉**的行数（= 有行读不出 ⇒ 这一帧不能用来证明「到底」）。
    dropped_in_scan: int = 0
    #: 没确认到顶就收尾的页数（:meth:`advance_tab` 记账）。
    top_unconfirmed: int = 0
    #: 页签没切换成功（sticky；扫描会停在错的页签上，绝不许宣布「两个页签都扫到底」）。
    tab_switch_failed: bool = False
    # -- 页内「滚不动」的位移记账（有被剔行时用它判「底不可证」）--------------
    no_move_stable_gen: int = -1
    no_move_stable: int = 0
    #: 这一页「有行被剔 + 连续滚不动」⇒ 底不可证（本页按扫描不完整收尾，不判「到底」）。
    bottom_unprovable: bool = False

    # -- 页签 ---------------------------------------------------------------
    def desired_tab(self, target_row: str | None = None, registry: Sequence | None = None):
        """**目标页签**：有目标行 → 它的族（#19 口径）；否则 → 扫描顺序里的下一个。"""
        if target_row:
            tab = tab_of_row(target_row, registry)
            if tab is not None:
                return tab
        if self.sweep_done:
            return None
        if 0 <= self.sweep_index < len(LORD_TABS):
            return LORD_TABS[self.sweep_index]
        return None

    def page_pending(self, round_index: int) -> bool:
        """现在该不该做「页扫描」（= 两个页签各滚到底）？

        两段条件：**扫描没做完** 时一直算待办；做完之后**每开一轮新的重扫**
        （``round_index`` 前进 ⇒ D6 的「回列表重读」）。
        """
        return (not self.sweep_done) or int(round_index) > int(self.sweep_round)

    def switch_decision(self, evidence: TabEvidence, desired: str | None, box, now: float) -> TabDecision:
        """该不该切页签（**含切后确认**）—— 唯一的「动手」出口。

        判决顺序（每一条都带原因）：

        1. 没有目标页签 → ``cannot``；
        2. 不在列表页 → ``cannot``（绝不盲点：主城/详情页的同名标签位置完全不同）；
        3. ``evidence.confirmed == desired`` → ``ok``（★这就是确认条件★，并清掉重试计数）；
        4. 这次切换已经点满 :data:`TAB_SWITCH_MAX_ATTEMPTS` 次 → 不再点：
           ``unconfirmed`` 累加，未达 :data:`TAB_UNCONFIRMED_LIMIT` → ``give_up``（回枢纽），
           达到 → ``stop``（带原因收工，防 #19 竞速空转）；
        5. 读不到目标页签的标签框 → ``cannot``（★不盲点★）；
        6. 否则 → ``click``，并把这次尝试记上（**先记账再点**：点失败也不许重试）。
        """
        if desired is None:
            return TabDecision(ACTION_CANNOT, None, None, "没有目标页签（扫描已结束且当前无目标行）")
        if not evidence.list_page:
            return TabDecision(
                ACTION_CANNOT,
                desired,
                None,
                f"不在领主战列表页（读不到「{LIST_PAGE_ANCHOR}」）—— 不在这里点页签",
            )
        if evidence.confirmed == desired:
            self.switch_attempts = 0
            self.switch_for = None
            self.unconfirmed = 0
            self.note_progress(now)
            return TabDecision(
                ACTION_OK,
                desired,
                None,
                f"已确认停在「{desired}」页签（可见行族 = {evidence.kinds}）—— 无需切换",
            )
        if self.switch_for != desired:
            self.switch_for = desired
            self.switch_attempts = 0
        if self.switch_attempts >= TAB_SWITCH_MAX_ATTEMPTS:
            # ★宽限期★：点完页签先给它 TAB_CONFIRM_GRACE_SEC，慢帧不算失败
            if self.last_progress_at > 0 and (now - self.last_progress_at) >= TAB_CONFIRM_GRACE_SEC:
                self.unconfirmed += 1
            why = (
                f"页签未确认到「{desired}」（已点 {self.switch_attempts}/{TAB_SWITCH_MAX_ATTEMPTS} 次，"
                f"可见行族 = {evidence.kinds}，确认值 = {evidence.confirmed!r}）"
            )
            if self.unconfirmed >= TAB_UNCONFIRMED_LIMIT:
                return TabDecision(
                    ACTION_STOP,
                    desired,
                    None,
                    why
                    + f"；连续 {self.unconfirmed} 次（上限 {TAB_UNCONFIRMED_LIMIT}）—— 带原因收工"
                    f"（重试只会变成 #19 那种页签竞速死循环）",
                )
            return TabDecision(
                ACTION_GIVE_UP,
                desired,
                None,
                why + " —— 不重试（#19），回枢纽",
            )
        if box is None:
            return TabDecision(
                ACTION_CANNOT,
                desired,
                None,
                f"读不到「{desired}」页签的标签框（ROI {TAB_ANCHORS[desired].roi}）—— 不盲点",
            )
        self.switch_attempts += 1
        self.note_progress(now)
        return TabDecision(
            ACTION_CLICK,
            desired,
            _box4(box),
            f"点「{desired}」页签（第 {self.switch_attempts}/{TAB_SWITCH_MAX_ATTEMPTS} 次，"
            f"点框中心；切完必须复核确认 = 可见行族一致指向目标页签）",
        )

    # -- ★a 回顶部（有界 + 可验证）★ ---------------------------------------
    def rewind_pending(self) -> bool:
        """这一页是否还需要「先回顶部」（本票 a：每轮扫描必须从**顶部**开始）。

        ★「到底」是**相对滚动位置**的概念★：战后列表停在**被点行**处，不回顶部就向下扫，
        只会读到目标行附近那几行就判「到底」（真机 484 第 2 轮：领主战 4 行、降临讨伐 0 行）。
        """
        return (not self.rewind_done) and (not self.rewind_failed)

    def rewind_budget_exhausted(self) -> bool:
        """回顶部次数是否用尽（用尽 ⇒ 调用方**带原因收工**，绝不无限上滚）。"""
        return self.rewind_scrolls >= SCROLL_PLAN.max_rewinds_per_page

    def note_rewind_scroll(self, now: float) -> None:
        """记一次**回顶部上滚**（★独立账★：不动向下扫的 ``scrolls_in_page`` / ``scroll_gen``）。

        为什么分开：``scroll_gen`` 是「到底判据」的世代，只有**向下扫**才该让「没有新行」
        变得有意义；上滚不是扫描步骤。混在一起会让「回顶部」把到底计数推进。
        """
        self.rewind_scrolls += 1
        self.rewind_gen += 1
        self.last_scroll_at = now
        self.note_progress(now)
        if self.rewind_budget_exhausted():
            self.rewind_failed = True

    def observe_rewind(self, rows, *, dropped: int = 0) -> tuple[bool, str]:
        """**回顶部判据**：上滚后这一帧 vs 上一帧 —— 连续 ``stable_times`` 个**回顶部世代**
        都「没有新行 ∧ 纵向上移位移 ≤ ``no_move_px``」⇒ 已到顶部。

        * ``dropped``：这一帧被徽标剔除的行数（只累加本轮扫描的完整性账；★不影响到顶判定★：
          到顶是**几何**事实 —— 再往上滚也不动，徽标读不出并不改变它）；
        * **空帧不算**（那一帧可能根本不是列表页 / 全是徽标）：判不了「没动」，不记账；
        * 返回 ``(at_top, reason)``；``reason`` 里带**上滚次数 / 上限 / 位移 / 连续次数**，
          因为「已到顶部」必须能从日志复核，而不是一句断言。
        """
        rows = tuple(rows or ())
        if dropped:
            self.dropped_in_scan += int(dropped)
        prev: dict = {}
        for row in self.rewind_last_rows:
            cy = _row_cy(row)
            if cy is not None:
                prev[row_key(row)] = cy
        moved: float | None = None
        fresh: list[tuple] = []
        for row in rows:
            key = row_key(row)
            if key not in prev:
                fresh.append(key)
                continue
            cy = _row_cy(row)
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
        no_move = moved is None or moved <= SCROLL_PLAN.no_move_px
        if no_move and self.rewind_gen > 0 and self.rewind_stable_gen != self.rewind_gen:
            self.rewind_stable_gen = self.rewind_gen
            self.rewind_stable += 1
        if self.rewind_stable >= SCROLL_PLAN.stable_times:
            self.rewind_done = True
            return (
                True,
                f"已到顶部：向上滚 {self.rewind_scrolls} 次（上限 "
                f"{SCROLL_PLAN.max_rewinds_per_page}），连续 {self.rewind_stable} 个世代"
                f"没有新行 / 纵向位移 {shown} ≤ {SCROLL_PLAN.no_move_px}px —— 可以开始向下扫",
            )
        return (
            False,
            f"未到顶：连续 {self.rewind_stable}/{SCROLL_PLAN.stable_times} 个世代无新行 / "
            f"纵向位移 {shown}（第 {self.rewind_gen} 次上滚那一代；上滚 {self.rewind_scrolls}/"
            f"{SCROLL_PLAN.max_rewinds_per_page} 次）",
        )

    def may_rewind(self, now: float) -> tuple[bool, str]:
        """能不能再上滚一次（回顶部的**时间闩 + 预算**；用尽/未到都**带原因**）。

        与 :meth:`may_scroll` 同一条时间闩（:attr:`ScrollPlan.min_interval_sec`）：回顶部也是
        受控滚动，绝不连甩（连甩会把列表甩过头，又把「到顶」判据打穿）。
        """
        if self.rewind_budget_exhausted():
            return (
                False,
                f"回顶部预算用尽（已上滚 {self.rewind_scrolls} 次，上限 "
                f"{SCROLL_PLAN.max_rewinds_per_page}）—— 必须带原因收工，绝不无限上滚",
            )
        waited = now - self.last_scroll_at
        if self.last_scroll_at > 0 and waited < SCROLL_PLAN.min_interval_sec:
            return (
                False,
                f"回顶部时间闩未到（距上次滚动 {waited:.2f}s < "
                f"{SCROLL_PLAN.min_interval_sec}s）—— 等下一圈",
            )
        return (
            True,
            f"回顶部：向上滚第 {self.rewind_scrolls + 1}/"
            f"{SCROLL_PLAN.max_rewinds_per_page} 次（行程 {SCROLL_PLAN.travel_px}px，"
            f"同一个手势反向）",
        )

    # -- 页内滚动 / 到底 ----------------------------------------------------
    def add_rows(self, rows, *, now: float | None = None) -> tuple[tuple, tuple]:
        """把这一帧的行读数并进累计；返回 ``(本帧新读数键, 本帧重复读数键)``。

        ★累计表按**行名**存**最新**读数（``N`` 变大即覆盖）★，不是按 ``(行名, N/M)`` 存多条。
        后者会让第 2 轮同时留着 ``(领主, 1/4)`` 与 ``(领主, 2/4)``，而 ``plan_round`` 对同名行
        只看第一条 ⇒ 把**刚打完的档**当成目标、反复打刚打完的档，「打没打过的」永远到不了
        （然后以「连续 2 轮无新解锁」误收工）。

        ``row_key`` 只用于「**本帧**这一行读没读过」：同一帧里 OCR 出重复框只认第一条；
        比累计更旧的读数（``N`` 没变大 —— 上一屏的行被滚回来、或回读到旧帧）算重复、
        **不覆盖**最新读数。
        """
        new: list[tuple] = []
        dup: list[tuple] = []
        frame_keys: set = set()
        for row in rows or ():
            key = row_key(row)
            if key in frame_keys:
                dup.append(key)
                continue
            frame_keys.add(key)
            name, n, _m = _row_triple(row)
            previous = self.seen.get(name)
            if previous is not None:
                if n > _row_triple(previous)[1]:
                    self.seen[name] = row      # 进度变大 = 真·新信息 → 覆盖成最新读数
                    new.append(key)
                else:
                    dup.append(key)            # 不比累计更新 → 不覆盖、不记账
                continue
            self.seen[name] = row
            new.append(key)
        if new and now is not None:
            self.note_progress(now)
        return (tuple(new), tuple(dup))

    def rows(self) -> tuple:
        """累计到的**最新**行读数（每行一条，按第一次出现的顺序；★已按行名去重★）。"""
        return tuple(self.seen.values())

    def observe(self, rows, *, anchor_hit: str | None = None, dropped: int = 0) -> tuple[bool, str]:
        """**到底判据**：拿「滚动后这一帧」和「滚动前那一帧」比，**按滚动世代记账**。

        ``at_end`` 成立当且仅当（满足其一）：

        * **尾部锚点命中**（:data:`END_ANCHORS`，当前为空 —— 见那里的诚实空缺）；或
        * **连续 :attr:`ScrollPlan.stable_times` 次滚动之后**：**没有任何没见过的行**
          （= 末行下方不再有新行）**且**共有行的纵向位移 ≤ :attr:`ScrollPlan.no_move_px`
          （= 列表根本没动）。

        ★``dropped``：这一帧被徽标整行剔掉的行数★（真机 484 第 5 轮验收）：剔掉的行**算
        「见到行」**—— 那一行可能正是 ``N<M`` 的那一行，所以：

        * 只要这一帧有被剔的行，``at_end`` 一律为 ``False``（不许用一帧「读不全的读数」证明到底）；
        * 但位移仍然记账：连续 ``stable_times`` 个世代**滚不动** ⇒ 置
          :attr:`bottom_unprovable`（列表停住了，可读不到的行让我们**无法证明**这是真底），
          由调用方按「扫描不完整」收尾，**不判「到底」**、也绝不再空滚到上限。

        ★「连续几次」= 连续几个**滚动世代**★（:attr:`scroll_gen` 在 :meth:`note_scroll` 里 +1，
        :attr:`stable_gen` 记住上一次记账的世代）：

        * **同一世代只记一次** —— ``LordsScanPage`` 的 ``next`` 里有
          ``[JumpBack]PubLoadingWait`` / ``PubDailyPopup``，它们会把控制权弹回来**重读同一屏**；
          修前每调一次 ``observe`` 都可能 ``stable_scrolls+=1``，于是「连读两帧同一屏」就判到底
          （其实一次都没滚）。
        * **没真的滚过就没有「到底」** —— 世代 0（本页还没滚过一次）时一律不记账：
          「列表没动」只有在**确实滚过**之后才说明「已经到底」。
        * **空帧不算** —— 一行 ``通关数`` 都读不到时判不了「没动」（那一帧可能根本不是列表页）。

        返回 ``(at_end, reason)``；``reason`` 里带量（新行数 / 位移 / 连续次数 / 世代 / 被剔行数），
        因为「到底了」必须能从日志复核，而不是一句断言。
        """
        rows = tuple(rows or ())
        if dropped:
            self.dropped_in_scan += int(dropped)
        prev: dict = {}
        for row in self.last_rows:
            cy = _row_cy(row)
            if cy is not None:
                prev[row_key(row)] = cy
        moved: float | None = None
        fresh: list[tuple] = []
        for row in rows:
            key = row_key(row)
            if key not in prev:
                fresh.append(key)
                continue
            cy = _row_cy(row)
            if cy is None:
                continue
            moved = abs(cy - prev[key]) if moved is None else max(moved, abs(cy - prev[key]))
        self.last_rows = rows

        if anchor_hit and not dropped:
            self.stable_scrolls = SCROLL_PLAN.stable_times
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
        # moved is None = 没有任何一行能跨帧量位移（框缺失）⇒ 只能靠「有没有新行」判
        no_move = moved is None or moved <= SCROLL_PLAN.no_move_px
        shown = "无法量出（跨帧没有共有行框）" if moved is None else f"{moved:.0f}px"
        # ★本票 c（位移记账）★：与「有没有新行」分开记 —— 有被剔行时用它判「底不可证」。
        if fresh or not no_move:
            self.no_move_stable = 0
        elif self.scroll_gen > 0 and self.no_move_stable_gen != self.scroll_gen:
            self.no_move_stable_gen = self.scroll_gen
            self.no_move_stable += 1
        note = ""
        # ★#100 真机★ 只要求「没有新行」：滚到底后会有**橡皮筋回弹**（内容动了 432px 又弹回），
        #   若把「位移」当否决条件，`stable_scrolls` 永远不涨 ⇒ 无限滚动（真机 39 次仍在滚）。
        #   位移仍打进 reason，供人复核「回弹 vs 真没动」。
        #   唯一保留的安全网：位移 ≥ 一屏行程却**一行共有行都没有**（moved is None 已覆盖）时不记账。
        if dropped:
            # ★本票 c★：被徽标剔掉的行**算「见到行」** —— 只要这一帧有被剔的行，就不许判到底。
            self.stable_scrolls = 0
            self.stable_gen = self.scroll_gen
            if self.no_move_stable >= SCROLL_PLAN.stable_times:
                first_time = not self.bottom_unprovable
                self.bottom_unprovable = True
                return (
                    False,
                    f"未到底：这一帧有 {dropped} 行被徽标剔除（可能是 N<M 的行）—— 不许判到底；"
                    f"但连续 {self.no_move_stable} 个世代**滚不动**（纵向位移 {shown} ≤ "
                    f"{SCROLL_PLAN.no_move_px}px）⇒ 底不可证，本页按「扫描不完整」收尾"
                    + ("（首次记下）" if first_time else ""),
                )
            return (
                False,
                f"未到底：这一帧有 {dropped} 行被徽标剔除（可能是 N<M 的行）—— 不许判到底；"
                f"滚不动连续 {self.no_move_stable}/{SCROLL_PLAN.stable_times} 个世代"
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
        if self.stable_scrolls >= SCROLL_PLAN.stable_times:
            return (
                True,
                f"到底：连续 {self.stable_scrolls} 次**滚动**后都没有新行"
                f"（末次纵向位移 {shown}；滚到底的橡皮筋回弹也算「没有新行」，故位移不作否决）",
            )
        return (
            False,
            f"未到底：新行 {len(fresh)} 个 / 纵向位移 {shown}（连续无变化 "
            f"{self.stable_scrolls}/{SCROLL_PLAN.stable_times} 次）{note}",
        )

    def at_end(self) -> bool:
        """当前的到底结论（= 上一次 :meth:`observe` 的结果，不改状态）。"""
        return self.stable_scrolls >= SCROLL_PLAN.stable_times

    def page_finished(self) -> bool:
        """这一页的扫描能否**先收尾**（推进到下一个页签 / 交给判定）。

        = 真到底（:meth:`at_end`）**或** 底不可证（:attr:`bottom_unprovable`：
        有行被徽标剔掉 + 连续滚不动）。后者**不是**「到底」，只是「再滚也没有可读的新证据」，
        由调用方按**扫描不完整**记账（零目标时据此写正确原因）。
        """
        return self.at_end() or self.bottom_unprovable

    def scan_incomplete_reason(self) -> str:
        """★本轮扫描的**不完整证据**★（空串 = 完整）。

        本票 d 的唯一用途：零目标收工时**把病因指对**（扫描不完整 / 页签没切 / 没回顶），
        绝不再落到「本页已滚 80 次（上限 80）仍未到底」那个把病因指错的兜底文案。
        """
        parts: list[str] = []
        if self.dropped_in_scan > 0:
            parts.append(f"有行被徽标剔除 {self.dropped_in_scan} 行")
        if self.top_unconfirmed > 0:
            parts.append(f"未确认回到顶部 {self.top_unconfirmed} 页")
        if self.tab_switch_failed:
            parts.append("页签未切换")
        return " / ".join(parts)

    def scan_complete(self) -> bool:
        """本轮扫描是否**完整**（没有读不出的行 / 每页都确认到顶 / 页签都切成功）。"""
        return not (self.dropped_in_scan or self.top_unconfirmed or self.tab_switch_failed)

    def note_tab_switch_failed(self) -> None:
        """页签没切换成功（sticky 到 :meth:`begin_round`）：扫描会停在错的页签上。"""
        self.tab_switch_failed = True

    def may_scroll(
        self,
        now: float,
        *,
        confirmed: str | None,
        desired: str | None,
        target_visible: bool,
        scanning: bool,
        anchor_hit: str | None = None,
    ) -> tuple[bool, str]:
        """能不能滚一次（★时间闩 + 到底判据在前，计数兜底在后★）。

        拒绝的理由逐条给清（全都不静默）：

        1. 已到底（含尾部锚点）→ 不再滚；
        2. 页内滚动次数已达 :attr:`ScrollPlan.max_scrolls_per_page` → **不是静默跳过**：
           调用方据此**带原因收工**（半扫的列表判不了「全部解禁」）；
        3. 页签没确认到目标页签 → 先切页签（#19：在错的页签上滚 = 滚错列表）；
        4. **时间闩**未到（:attr:`ScrollPlan.min_interval_sec`）；
        5. 没有滚动的理由：既不在扫描阶段、目标行又已在屏上（#29：选行先于滚动）。
        """
        if anchor_hit:
            return (False, f"已到底（尾部锚点「{anchor_hit}」）—— 不再滚")
        if self.at_end():
            return (False, f"已到底（连续 {self.stable_scrolls} 次无新行/无位移）—— 不再滚")
        if self.scrolls_in_page >= SCROLL_PLAN.max_scrolls_per_page:
            return (
                False,
                f"本页已滚 {self.scrolls_in_page} 次（上限 {SCROLL_PLAN.max_scrolls_per_page}，"
                f"#50 同口径的**兜底**）仍未到底 —— 必须带原因收工，绝不静默跳过（半扫的列表"
                f"判不了「全部解禁」）",
            )
        if desired is not None and confirmed != desired:
            return (False, f"页签未确认到「{desired}」（当前确认值 {confirmed!r}）—— 先切页签再滚（#19）")
        waited = now - self.last_scroll_at
        if self.last_scroll_at > 0 and waited < SCROLL_PLAN.min_interval_sec:
            return (
                False,
                f"时间闩未到（距上次滚动 {waited:.2f}s < {SCROLL_PLAN.min_interval_sec}s）—— 等下一圈",
            )
        if not scanning and target_visible:
            return (False, "目标行已在屏上 —— 先选行、再滚（#29：滚动不许抢在选行前面）")
        return (True, f"可以滚一次（本页第 {self.scrolls_in_page + 1} 次，行程 {SCROLL_PLAN.travel_px}px）")

    def note_scroll(self, now: float) -> None:
        """记一次滚动（时间闩基准 + 页内计数 + **滚动世代 +1** + 进展时刻）。"""
        self.scrolls_in_page += 1
        self.scroll_gen += 1
        self.last_scroll_at = now
        self.note_progress(now)

    def scroll_budget_exhausted(self) -> bool:
        """本页滚动次数是否已用尽。

        ★用尽时的处置是「**带原因收工**」，不是静默跳过★（#50 的反面）：半扫一遍的列表
        判不了「全部解禁」，所以这里宁可收工也不许继续。
        """
        return self.scrolls_in_page >= SCROLL_PLAN.max_scrolls_per_page

    # -- 扫描进度 -----------------------------------------------------------
    def reset_page(self) -> None:
        """换页（切页签 / 下一页签 / 新一轮）时清页内状态，并★重新武装「回顶部」★。

        ★本票 a★：每一页开扫前都必须先回顶部（有界 + 可验证）—— 修前这里默认「列表已回顶部」，
        而真机第 6 轮验收证明**切页签/战后都保留滚动位置**（``debug/lords_accept6.log``：
        第 2 轮「领主战」只读 4 行就判到底；切「降临讨伐」后两页签共 4 行、目标 0）。
        ★「到底」是相对滚动位置的概念★：不回顶部，第二轮的「到底」毫无意义。
        """
        self.scrolls_in_page = 0
        self.stable_scrolls = 0
        self.last_rows = ()
        # ★回顶部（每页一次）★
        self.rewind_done = False
        self.rewind_scrolls = 0
        self.rewind_gen = 0
        self.rewind_stable_gen = -1
        self.rewind_stable = 0
        self.rewind_last_rows = ()
        self.rewind_failed = False
        # ★「底不可证」与位移记账是页内的★（本轮扫描的完整性账不在这里清）
        self.bottom_unprovable = False
        self.no_move_stable_gen = -1
        self.no_move_stable = 0

    def advance_tab(self, now: float | None = None) -> tuple[bool, str]:
        """当前页签扫完了 → 轮到下一个；两个都扫完 → ``(True, ...)``（扫描阶段结束）。

        ★本票 a/b★：推进前记一笔「这一页有没有确认到顶」（没有 ⇒ 本轮扫描不完整，
        零目标时原因里要写「未确认回到顶部」）；然后 ``reset_page`` 为**下一页**重新武装回顶部。
        """
        if not self.rewind_done:
            self.top_unconfirmed += 1
        self.reset_page()
        if self.sweep_index + 1 >= len(LORD_TABS):
            self.sweep_done = True
            if now is not None:
                self.note_progress(now)
            return (True, f"两个页签都扫到底（{list(LORD_TABS)}）—— 扫描阶段结束")
        self.sweep_index += 1
        if now is not None:
            self.note_progress(now)
        return (False, f"「{LORD_TABS[self.sweep_index - 1]}」扫到底，轮到「{LORD_TABS[self.sweep_index]}」")

    def complete_scan(self, round_index: int, now: float | None = None) -> None:
        """一轮全量扫描收尾（读完两个页签、已交给判定）。下一轮（``round_index`` 前进）重扫。

        ★这里**只**把扫描标记为「本轮做完」★：``sweep_done=True`` / ``sweep_index`` 推到末位 /
        ``sweep_round`` 记成这一轮。**复位**是 :meth:`begin_round` 的事（R2：修前没人复位，
        第 2 轮 ``desired_tab()`` 是 ``None`` ⇒ 一个页签都不切、``advance_tab`` 立刻说「两个都扫完」）。
        """
        self.sweep_done = True
        self.sweep_round = int(round_index)
        self.sweep_index = len(LORD_TABS)
        self.reset_page()
        if now is not None:
            self.note_progress(now)

    def begin_round(self, now: float | None = None) -> None:
        """★新一轮开始：重新武装扫描★（R2）—— 复位 sweep + 清页内状态 + **清累计读数**（R1）。

        为什么必须由**这个方法**承担（而不是 ``reset()``）：``reset()`` 全仓无人调用，
        所以「扫描做完 → 下一轮重开两个页签」这条路只有这里能走。
        调用点 = ``page_pending(round_index)`` 为真的入口（``agent/lords_impl._ensure_round``，
        四个导航 mode 开头各一次）。

        ★清累计★的理由（R1）：新一轮要读的是**这一轮**的最新读数；旧轮次的 ``seen`` 留着只会
        让「同一行的旧 N」混进来（虽然 :meth:`add_rows` 已按行名留最新，清掉更干脆、也让
        「本轮到底读到几行」在日志里可信）。

        ★本票 a/d★：新一轮同时把**扫描完整性账**清零（``dropped_in_scan`` /
        ``top_unconfirmed`` / ``tab_switch_failed``），并由 ``reset_page`` 重新武装**回顶部**。
        """
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
        """整份清零（换任务 / 离线测试用；★运行期无人调用，别指望它来复位扫描★）。"""
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
    def note_progress(self, now: float) -> None:
        """记一次「有进展」（页签确认 / 滚动 / 读到新行 / 判完一轮）。"""
        self.last_progress_at = now

    def stuck_reason(self, now: float) -> str:
        """页签/滚动/读页都不再有进展 ≥ :data:`NAV_STUCK_SEC` → 返回收工理由（否则 ``""``）。

        ★为什么要它★：MAA 的 ``next`` 扫不到任何节点时不会自己收工，枢纽会自环轮询。
        「滚到底了但目标行始终不见 / 页签确认不过」这两种形态都会让新加的导航节点**全部
        no-hit** —— 没有这条死线就是**静默空转**（#50 拦的正是这种形态）。
        """
        if self.last_progress_at <= 0:
            return ""
        idle = now - self.last_progress_at
        if idle < NAV_STUCK_SEC:
            return ""
        return (
            f"导航 {idle:.0f}s 没有任何进展（死线 {NAV_STUCK_SEC:.0f}s）：页签={self.desired_tab()!r} "
            f"已滚 {self.scrolls_in_page} 次 / 到底={self.at_end()} —— 带原因收工"
        )


# ---------------------------------------------------------------------------
# 6. 点目标之前的「归位」：先对页签，再上下找（#100 第 3 条真机缺口）
# ---------------------------------------------------------------------------
#: 归位动作的取值（★每一种都有各自的处置，绝不含并★）。
PICK_ACTION_READY = "ready"      # 目标行在屏上（或不在列表页）→ 交给 pick_click 的老三跳
PICK_ACTION_TAB = "tab"          # 先点目标页签（导航，**不算**点目标）
PICK_ACTION_SCROLL = "scroll"    # 滚一次去找（方向见 :data:`PICK_SCROLL_DOWN` / ``_UP``）
PICK_ACTION_WAIT = "wait"        # 页签还没确认（点过 1 次，宽限期内）—— 这一圈什么都不做
PICK_ACTION_FAIL = "fail"        # 带原因收工（三种原因分开，见 :data:`PICK_REASON_*`）

#: 滚动方向（**按内容命名**：``down`` = 露出下面的行 = 手指上移）。
PICK_SCROLL_DOWN = "down"
PICK_SCROLL_UP = "up"

#: 归位的两个阶段（先下后上；都到底 ⇒ 找不到）。
PICK_PHASE_DOWN = "down"
PICK_PHASE_UP = "up"
PICK_PHASE_DONE = "done"

#: 三种失败原因的 **kind**（写进 detail，机器可判）与**用户可见文案**（人可读，SOP 口径）。
#:
#: ★为什么必须分开（#100 第 3 条真机缺口的教训）★：修前三者混成一句「点不出去」，
#: 于是「目标在另一个页签 / 目标滚出屏幕 / 找到了却点不动」在日志里长得一模一样 ——
#: 症状离病因太远，一晚上全花在猜上。文案里的这三个子串由守卫 ``hooks_121`` 逐字钉住。
PICK_FAIL_TAB = "tab_unreachable"
PICK_FAIL_NOT_FOUND = "not_found"
PICK_FAIL_CLICK = "click_stuck"
#: 第四种（诚实补位）：**滚动手势本身连续执行失败**（设备/手势异常）。
#: 不并进上面三条 —— 那会把「手势没跑起来」说成「列表里没有这一行」（又一次谎报）。
#: 为什么必须有它：动作失败时 MAA 走 ``on_error`` 回枢纽，而枢纽里 pick 在所有「读列表」
#: 节点之前 —— 不进这条出口就是**无限空转**（#50 拦的正是这种形态）。
PICK_FAIL_SCROLL = "scroll_error"
PICK_REASON_TAB = "目标不在这个页签"
PICK_REASON_NOT_FOUND = "滚到底也没找到"
PICK_REASON_CLICK = "找到了但点不动"
PICK_REASON_SCROLL = "滚动手势执行失败"

#: 页签「还没确认」最多等多久（秒）= 宽限期 × 未确认上限。
#: ★不新造数字★：两个因子都来自 :data:`TAB_CONFIRM_GRACE_SEC` / :data:`TAB_UNCONFIRMED_LIMIT`
#: （#19 的「切一次、确认一次」；这段时间里 pick **什么都不做**，也**不算**「点不动」）。
PICK_TAB_WAIT_SEC: float = TAB_CONFIRM_GRACE_SEC * TAB_UNCONFIRMED_LIMIT


@dataclass(frozen=True)
class PickDecision:
    """「点目标之前该干什么」的判决（纯数据；由 :meth:`PickNav.decide` 给出）。"""

    action: str
    #: 目标页签（``lord`` / ``joss`` 对应的页签名；不知时 ``None``）。
    tab: str | None = None
    #: :data:`PICK_ACTION_SCROLL` 时的方向（``down`` / ``up``）。
    direction: str | None = None
    #: :data:`PICK_ACTION_FAIL` 时的原因 kind（:data:`PICK_FAIL_*`）。
    kind: str | None = None
    #: 为什么（人读；日志 / detail / 收工原因都用它）。
    reason: str = ""


@dataclass
class PickNav:
    """**目标行归位**的状态机（先对页签，再「先下后上」找；纯逻辑、无 I/O）。

    为什么需要它（#100 第 3 条真机缺口，484 12:0x）：扫描阶段结束后导航链就停了，而
    ``mode=pick`` 只做 ``pick_click`` —— 目标行既不在当前页签、又滚出了屏幕时，它每一圈都
    no-hit，最后干等「点不出去」死线 20s 收工（现场只看到「已经 51s 点不出去」，看不到
    「目标行根本不在这一屏」）。本类把「点之前该先干什么」变成可离线复核的判决。

    字段语义：

    * ``row_name`` / ``tab`` —— 当前归位的是哪个目标、它该在哪个页签；目标变了 ⇒
      :meth:`begin_target` 整份清零；
    * ``phase`` —— ``down``（先向下滚，列表可能在上方/下方都先试这一向）→ ``up``（回顶部）→
      ``done``（两向都到底 ⇒ 找不到）；
    * ``scrolls_down`` / ``scrolls_up`` —— 两个方向各滚了几次（上限都是
      :attr:`ScrollPlan.max_scrolls_per_page`，**不是** ``max_hit``）；
    * ``scroll_gen`` / ``stable_gen`` / ``stable_scrolls`` —— **按滚动世代**记「这一方向到底」
      （与 :meth:`NavState.observe` 同一条纪律：没真的滚过不记账、同一世代只记一次）；
    * ``scroll_errors`` —— 滚动手势**连续执行失败**的次数（成功一次就清零）。达
      :data:`TAB_UNCONFIRMED_LIMIT` 就带原因收工（:data:`PICK_FAIL_SCROLL`）——
      动作失败会走 ``on_error`` 回枢纽，而枢纽里 pick 排在所有「读列表」节点**之前**，
      没有这条出口就是**无限空转**；
    * ``fail_kind`` / ``fail_reason`` —— **结论一旦下就粘住**（不许下一圈又假装还能找到）；
    * ``wait_since`` —— 页签「还没确认」的起点（到 :data:`PICK_TAB_WAIT_SEC` 就判
      :data:`PICK_FAIL_TAB`；★页签没确认的这段时间不算「点不动」★）。
    """

    row_name: str | None = None
    tab: str | None = None
    phase: str = PICK_PHASE_DOWN
    scrolls_down: int = 0
    scrolls_up: int = 0
    scroll_gen: int = 0
    stable_gen: int = -1
    stable_scrolls: int = 0
    last_scroll_at: float = 0.0
    last_rows: tuple = ()
    scroll_errors: int = 0
    fail_kind: str | None = None
    fail_reason: str = ""
    wait_since: float = 0.0

    # -- 目标 / 页签 ---------------------------------------------------------
    def begin_target(self, row_name: str | None, tab: str | None) -> bool:
        """切换到新目标（同一目标则什么都不做）。返回「是否真的换了目标」。"""
        if self.row_name == row_name and self.tab == tab:
            self.row_name = row_name
            self.tab = tab
            return False
        self.row_name = row_name
        self.tab = tab
        self.reset_search()
        return True

    def reset_search(self) -> None:
        """把「找」的进度清零（换目标 / 切了页签 / 换了一页列表）。

        ``last_scroll_at`` **不清**：时间闩（:attr:`ScrollPlan.min_interval_sec`）是跨页的
        「绝不连甩」，换页也不许绕过它。
        """
        self.phase = PICK_PHASE_DOWN
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
    def note_scroll(self, direction: str, now: float) -> None:
        """记一次**真的滚过**（方向计数 + 滚动世代 +1 + 时间闩基准 + 手势失败计数清零）。"""
        if direction == PICK_SCROLL_UP:
            self.scrolls_up += 1
        else:
            self.scrolls_down += 1
        self.scroll_gen += 1
        self.last_scroll_at = now
        self.scroll_errors = 0

    def note_scroll_error(self) -> int:
        """记一次**滚动手势执行失败**（返回连续失败次数；``decide`` 据此带原因收工）。"""
        self.scroll_errors += 1
        return self.scroll_errors

    def _restart_direction(self, phase: str) -> None:
        """换方向：清「这一方向到底」的计数，并把当前世代标成**已记过**。

        ★为什么要把 ``stable_gen`` 设成当前世代★：换方向那一下还没真的滚过，若留 ``-1``，
        下一帧同一屏就会被记一次「这一方向到底」（虚报）。与 :meth:`NavState.observe` 同口径。
        """
        self.phase = phase
        self.stable_scrolls = 0
        self.stable_gen = self.scroll_gen

    def observe(self, rows) -> tuple[bool, str]:
        """**这一方向到底了吗**：拿这一帧和上一帧比，**只认「有没有没见过的行」**。

        与 :meth:`NavState.observe` 同一条真机口径（#100 真机）：滚到底会有橡皮筋回弹
        （内容动了 400+px 又弹回），把位移当否决条件会让计数永不涨 ⇒ 无限滚动。
        所以到底 = **连续** :attr:`ScrollPlan.stable_times` 个**滚动世代**都没有新行。
        空帧不算（那一帧可能根本不是列表页）。
        """
        plan = SCROLL_PLAN
        rows = tuple(rows or ())
        previous: set = set()
        for row in self.last_rows:
            if _row_cy(row) is not None:
                previous.add(row_key(row))
        fresh = [row_key(row) for row in rows if row_key(row) not in previous]
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
        desired: str | None = None,
        tab_decision=None,
        target_visible: bool = False,
        list_page: bool = True,
        now: float = 0.0,
    ) -> PickDecision:
        """**这一圈该干什么**（判决顺序即优先级，每条都带原因）。

        1. 已经下过结论（``fail_kind``）→ 原样重放该结论（不假装还能找到）；
        2. 目标行在屏上、或不在列表页（详情/编队页）→ ``ready``（交给 ``pick_click`` 的老三跳；
           选行永远先于滚动，#29）；
        3. 页签：``tab_decision`` 说 ``click`` → ``tab``（**导航，不算点目标**）；
           说 ``stop`` / ``cannot`` → ``tab`` **失败**（:data:`PICK_REASON_TAB`）；
           说 ``give_up`` → ``wait``，等满 :data:`PICK_TAB_WAIT_SEC` 仍不确认 ⇒ 同一个失败；
           ``None``（行族证据不足，**不猜也不盲点**）→ 直接进 4；
        4. 「先下后上」：``down`` 阶段到底/用尽 ⇒ 换 ``up``；``up`` 阶段到底/用尽 ⇒
           :data:`PICK_REASON_NOT_FOUND`（带两个方向的次数）；
        5. 否则 → ``scroll``（方向 = 当前阶段）。

        ``evidence`` / ``tab_decision`` 都由调用方算好（页签判据的唯一真源是
        :func:`tab_state` 与 :meth:`NavState.switch_decision`，本方法**不复制**它们）。
        """
        plan = SCROLL_PLAN
        if self.fail_kind is not None:
            return PickDecision(PICK_ACTION_FAIL, self.tab, None, self.fail_kind, self.fail_reason)
        if not list_page or target_visible:
            self.wait_since = 0.0
            return PickDecision(
                PICK_ACTION_READY,
                desired if desired is not None else self.tab,
                None,
                None,
                "目标行在屏上（或不在列表页）—— 交给 pick_click 的老三跳（#29：选行先于滚动）",
            )

        # ① 页签：不一致就先切；证据不足既不切也不猜
        if tab_decision is not None:
            if tab_decision.action == ACTION_CLICK:
                self.wait_since = 0.0
                return PickDecision(PICK_ACTION_TAB, desired, None, None, tab_decision.reason)
            if tab_decision.action in (ACTION_STOP, ACTION_CANNOT):
                return self._fail(
                    PICK_FAIL_TAB,
                    f"{PICK_REASON_TAB}：目标「{self.row_name}」应在「{desired}」页签，"
                    f"但页签切不过去（{tab_decision.reason}；本页签向下 {self.scrolls_down} 次 /"
                    f" 向上 {self.scrolls_up} 次都没机会开始）—— 带原因收工",
                )
            if tab_decision.action == ACTION_GIVE_UP:
                if self.wait_since <= 0:
                    self.wait_since = now
                waited = now - self.wait_since
                if waited >= PICK_TAB_WAIT_SEC:
                    return self._fail(
                        PICK_FAIL_TAB,
                        f"{PICK_REASON_TAB}：目标「{self.row_name}」应在「{desired}」页签，"
                        f"点过页签后等了 {waited:.0f}s（宽限 {PICK_TAB_WAIT_SEC:.0f}s ="
                        f" {TAB_CONFIRM_GRACE_SEC:.0f}s × {TAB_UNCONFIRMED_LIMIT}）仍未确认 —— "
                        f"{tab_decision.reason} —— 带原因收工（#19：不重试）",
                    )
                return PickDecision(
                    PICK_ACTION_WAIT,
                    desired,
                    None,
                    None,
                    f"等页签确认到「{desired}」（已等 {waited:.1f}/{PICK_TAB_WAIT_SEC:.0f}s）—— "
                    f"这段时间**不算**「点不动」：页签是导航，不是点目标",
                )
        else:
            self.wait_since = 0.0

        # ①b 滚动手势连续失败 → 带原因收工（动作失败会回枢纽，而枢纽里 pick 在「读列表」之前）
        if self.scroll_errors >= TAB_UNCONFIRMED_LIMIT:
            return self._fail(
                PICK_FAIL_SCROLL,
                f"{PICK_REASON_SCROLL}：目标「{self.row_name}」的列表滚了"
                f" {self.scroll_errors} 次都没滚成（手势节点执行异常；本页签向下 {self.scrolls_down} 次 /"
                f" 向上 {self.scrolls_up} 次）—— 带原因收工（不回枢纽空转）",
            )

        # ② 上下找：先下（列表可能在上方或下方）→ 到底再向上（回顶部）
        at_end, why = self.observe(rows)
        if self.phase == PICK_PHASE_DOWN:
            if at_end or self.scrolls_down >= plan.max_scrolls_per_page:
                self._restart_direction(PICK_PHASE_UP)
                return PickDecision(
                    PICK_ACTION_SCROLL,
                    self.tab,
                    PICK_SCROLL_UP,
                    None,
                    f"{why} —— 向下已到底（{self.scrolls_down}/{plan.max_scrolls_per_page} 次），"
                    f"改向上找（回顶部）",
                )
            return PickDecision(
                PICK_ACTION_SCROLL,
                self.tab,
                PICK_SCROLL_DOWN,
                None,
                f"目标行不在屏上：向下滚找（{self.scrolls_down + 1}/{plan.max_scrolls_per_page}）"
                f"—— {why}",
            )
        if self.phase == PICK_PHASE_UP:
            if at_end or self.scrolls_up >= plan.max_scrolls_per_page:
                return self._fail(
                    PICK_FAIL_NOT_FOUND,
                    f"{PICK_REASON_NOT_FOUND}：目标「{self.row_name}」在本页签（{self.tab}）"
                    f"向下滚 {self.scrolls_down} 次 / 向上滚 {self.scrolls_up} 次，"
                    f"上下都扫到底（{why}）也没有这一行 —— 数据与画面不一致"
                    f"（列表里没有这一行：花名册/进度与画面不符）—— 带原因收工",
                )
            return PickDecision(
                PICK_ACTION_SCROLL,
                self.tab,
                PICK_SCROLL_UP,
                None,
                f"向下没找到，向上滚找（{self.scrolls_up + 1}/{plan.max_scrolls_per_page}）—— {why}",
            )
        return self._fail(
            PICK_FAIL_NOT_FOUND,
            f"{PICK_REASON_NOT_FOUND}：目标「{self.row_name}」在本页签（{self.tab}）—— "
            f"上下都找过了，带原因收工",
        )

    def _fail(self, kind: str, reason: str) -> PickDecision:
        """下结论（★粘住★：下一圈原样重放，不许再假装能找）。"""
        self.fail_kind = kind
        self.fail_reason = reason
        self.phase = PICK_PHASE_DONE
        return PickDecision(PICK_ACTION_FAIL, self.tab, None, kind, reason)


# ---------------------------------------------------------------------------
# 7. 页面状态（classify 的 lords 版）+ 模式选择页（#100 第 4、5 个真机缺口）
# ---------------------------------------------------------------------------
# 真机证据（**两帧、两个子族，同一页同一版式**）：
#
#   A. ``tools/frames/lords_mode_page_stuck.png``（2026-10-18 12:47，1080x1920，真机 484）——
#      从「降临讨伐 · 光芒荒龙」详情页点完 tier 之后落到这一页；
#   B. ``tools/frames/lord_mode_select.png``（仓内既有帧）—— 从「领主战 · 猩红巨熊」进入。
#
# 两帧的 OCR（**1080 原值 ÷1.5 = 720 空间**，两帧逐项差 ≤2px）::
#
#     文案                帧A（1080 原值）      帧B（1080 原值）      720 空间（本文件使用）      象限
#     单人游戏            117/746/276/78        117/746/276/78        [78, 497, 184, 52]         左上
#     单人挑战领主        117/860/204/42        117/860/204/42        [78, 573, 136, 28]         左上
#     多人游戏            518/1260/276/76       516/1258/276/76       [345, 839, 184, 51]        右下
#     建立房间            520/1376/139/36       520/1376/139/36       [347, 917, 93, 24]         右下
#     召集同伴挑战领主    518/1410/280/40       518/1410/280/40       [345, 940, 187, 27]        右下
#     顶部小标题          224/324/147/80        486/404/119/42        ——（= 子族名，**不是判据**）
#     底部导航带          y ≈ 1870（1080）      ——                    y ≈ 1246（返回/主城/角色/商店/扭蛋/菜单）
#
# ★1080 原值一律写成 ``x/y/w/h``（**不写成四元组字面量**）★：``hooks_99`` 的静态越界守卫按
#   720x1280 扫 scene/*.py 里的四整数字面量，1080 原值会被它当成越界坐标（它是对的）。
#
# ★对账（不是新猜的坐标）★
#   * 单人游戏框中心 (170.0, 523.0) ≈ ``special_dungeon.json::SpecialModeSolo`` 的
#     ``action.target`` **(170,523)**（既有真机实测点）；
#   * 建立房间框中心 (393.0, 929.0) ≈ ``SpecialModeMulti`` 的 **(392,929)**；
#   * 与 ``scene/wuchong.py`` 的三帧实测（单人 [78,497,184,52] / 多人 [345,840,184,52]，
#     且「单人卡必须比多人卡高 ≥200px」）**逐项一致** —— 模式选择页是两个子族共用的同一版式。
#
# ★但状态名与判据**各归各的场景**★
#   #100 第 4 条缺口的原病就是「lords 的页面被判成 ``wuchong_mode``」：跨场景状态名混用，
#   现场看到的是一个属于别的场景的词，排查时说不清是谁的页面。所以本文件给 lords 自己的
#   状态词表（:data:`LORDS_STATES`，全部 ``lords_*`` 前缀），判据由 lords 自己的四段文案 +
#   象限位置组成，**不 import 别的场景的常量、也不复用别的场景的状态名**。
# ---------------------------------------------------------------------------
#: lords 自己的页面状态词表（★全部 ``lords_`` 前缀；绝不出现别的场景的状态名★）。
LORDS_STATE_CITY = "lords_city"          # 主城（右下角【领主战】入口）
LORDS_STATE_LIST = "lords_list"          # 领主战列表页（判据 = 更新列表）
LORDS_STATE_DETAIL = "lords_detail"      # 详情页（判据 = 推荐编成）
LORDS_STATE_TEAM = "lords_team"          # 编队页 / 队伍页（判据 = 挑战）
LORDS_STATE_MODE = "lords_mode"          # ★模式选择页（单人/多人）—— 本票新增★
LORDS_STATE_BATTLE = "lords_battle"      # 战斗 HUD（时间 mm:ss + 分数 N）
LORDS_STATE_SETTLE = "lords_settle"      # 结算页（继续）
#: ★过渡态★ 加载 / 过场中（不是「这个页面停住了」）。真机 484（14:5x）：``--home`` 之后
#: 立刻跑 ``--trace LordsEntry``，刚回主城那几秒的帧就是这种，旧判据里它没有名字
#: （= ``lords_unknown``），于是 9s 死线在**任务还没开始**时就把任务判死。
LORDS_STATE_LOADING = "lords_loading"
LORDS_STATE_UNKNOWN = "lords_unknown"    # 认不出的页（不猜）

#: 全部状态（顺序 = :func:`page_state` 的判定顺序；守卫据此断言「词表没被换成别的场景的」）。
#: ★``lords_loading`` 排第一★：过渡帧可以叠在任何页面上（半渲染的主城 / 加载中的列表页），
#: 晚判就会被后面的判据当成「某一页的稳定状态」—— 正是「无进展」计时被启动瞬间误伤的机制。
LORDS_STATES: tuple[str, ...] = (
    LORDS_STATE_LOADING,
    LORDS_STATE_BATTLE,
    LORDS_STATE_SETTLE,
    LORDS_STATE_MODE,
    LORDS_STATE_TEAM,
    LORDS_STATE_DETAIL,
    LORDS_STATE_LIST,
    LORDS_STATE_CITY,
    LORDS_STATE_UNKNOWN,
)

#: ★**主动作状态**：战斗 / 结算★（这两个页面上「没有导航进展」是**正常**的，不许被死线打断）。
#: 它们由 :func:`page_state` 的专门判据识别，而不是靠「状态名恰好在变」—— 一场仗打几分钟
#: 里状态名一直是 ``lords_battle``，用「名字不变」去判会把正常战斗打断（#100 第 5 个缺口的★注意★）。
LORDS_ACTIVE_STATES: tuple[str, ...] = (LORDS_STATE_BATTLE, LORDS_STATE_SETTLE)

#: ★「点过【挑战】」的闩**放开证据**（真机 484 第 3 轮验收，``debug/lords_accept4.log``）★
#:
#: 点下【挑战】后会话置 ``challenge_pending``（禁双击开打）。这个闩**不是**「等 180s」——
#: 只要这一帧**正向认出**了下面任何一页，就说明那一下已经生效、人已经离开编队页：
#:
#:   * :data:`LORDS_STATE_BATTLE` / :data:`LORDS_STATE_SETTLE` —— 本票点名的两条；
#:   * :data:`LORDS_STATE_LIST` / :data:`LORDS_STATE_DETAIL` / :data:`LORDS_STATE_CITY` /
#:     :data:`LORDS_STATE_MODE` —— 也全是**正向认出的别的页**（点挑战后回到这些页面，
#:     说明这一场早结束了，重新找目标即可）。
#:
#: ★**故意不放**的三类★（它们不是「已经离开编队页」的**证据**）：
#:   * :data:`LORDS_STATE_TEAM` —— 还停在编队页：这一下可能没生效，必须继续等（禁双击）；
#:   * :data:`LORDS_STATE_LOADING` —— 转场帧（可能只是加载，还没离开）；
#:   * :data:`LORDS_STATE_UNKNOWN` —— 认不出的帧（可能是个没点动的体力弹窗）。
#:   ⇒ **宁可多等**（``agent/lords_impl.FIGHT_GRACE_SEC`` = 180s 兜底仍在），
#:     不可凭一张认不出的帧再点一次挑战（那不是「证据」，是猜）。
#:
#: 消费方：``agent/lords_impl._release_challenge_latch_on_evidence``（主路径 = 见到即放；
#: 180s 只作「点了没反应」的兜底）。守卫 ``hooks_122`` 的三条放闩挂点钉住。
LORDS_CHALLENGE_RELEASE_STATES: tuple[str, ...] = (
    LORDS_STATE_BATTLE,
    LORDS_STATE_SETTLE,
    LORDS_STATE_LIST,
    LORDS_STATE_DETAIL,
    LORDS_STATE_CITY,
    LORDS_STATE_MODE,
)

#: ★加载 / 过场帧的文案锚点★（与项目**唯一一份**画面分类同口径，不是本场景新发明的）：
#:   * ``请耐心等待`` —— ``assets/resource/pipeline/common.json::PubLoadingText`` 的实测判据
#:     （``PubLoadingWait`` 的子识别；``lords.json`` 里那些 ``[JumpBack]PubLoadingWait`` 就是它）；
#:   * ``健康游戏忠告`` —— 启动健康忠告页（``agent/battle_loop_core._branch_loading`` 的第二条）。
#: ★为什么照抄字面量而不 import★：``scene/`` 是纯逻辑层，不能反向 import ``agent/``（层向反了）；
#: 判据的**归属**仍是上面那两处（这里是「引用 + 注释对账」，不是第二套真源）。守卫
#: ``hooks_122`` 的 ``lords-transition-not-stuck`` 把这两段文案与 :data:`LORDS_STATE_LOADING`
#: 一起钉住 —— 改一处漏一处就红。
LORDS_LOADING_ANCHORS: tuple[str, ...] = ("请耐心等待", "健康游戏忠告")

#: ★过渡态集合★：正在加载 / 转场 —— **不算「没有进展」**，且每读到一个就**重置**计时。
#:
#: 真机现场（484，14:5x）：``--home`` 把设备送回主城后**立刻**跑 ``--trace LordsEntry``，
#: 日志 ``state=lords_unknown`` 连续 ~10s → 收工；随后手工 ``screencap``：设备**好好地在主城**
#: （活动 / 主城 / 关卡 / 领主战 / 菜单 全部可见）—— 任务还没开始就被判死了。
#:
#: 组成：
#:   * :data:`LORDS_STATE_LOADING` —— lords 自己的加载页状态名（:func:`page_state` 会返回它，
#:     判据 = :data:`LORDS_LOADING_ANCHORS`）；
#:   * ``loading`` / ``relogin`` —— **共享层**（#119 的画面分类 / pipeline 的加载等待）的裸状态名。
#:     lords 自己的词表全是 ``lords_*``（#100 第 4 个缺口的教训），所以它们**今天不会被
#:     :func:`page_state` 返回**；列在这里是**兜底**：万一从共享层漏进来，也必须按过渡处理 ——
#:     ★宁可晚收工，不可误杀一个刚回主城、还没开始的任务★。
#: ★``lords_unknown`` 绝不在此列★：未知画面的死线必须保留（那是「看起来在跑」的兜底），
#: 放进来的话「认不出的画面」就永远没有有界出口了（守卫 ② 专门抓这个）。
LORDS_TRANSITION_STATES: tuple[str, ...] = (
    LORDS_STATE_LOADING,
    "loading",
    "relogin",
)

#: 模式选择页的**四段文案**（逐字来自上面两帧的 OCR；★不是正则、也不是别的场景的常量★）。
LORDS_MODE_SOLO = "单人游戏"
LORDS_MODE_SOLO_NOTE = "单人挑战领主"
LORDS_MODE_MULTI = "多人游戏"
LORDS_MODE_MULTI_NOTE = "召集同伴挑战领主"

#: 两张卡所在的**象限**（720 空间 ``(x, y, w, h)``；分界线 = 基准分辨率的一半 = 360 / 640）。
#: 位置本身就是判据的第二半：单人卡在左上、多人卡在右下（两帧实测一致）。
LORDS_MODE_SOLO_ROI: tuple[int, int, int, int] = (0, 0, BASE_W // 2, BASE_H // 2)
LORDS_MODE_MULTI_ROI: tuple[int, int, int, int] = (
    BASE_W // 2,
    BASE_H // 2,
    BASE_W - BASE_W // 2,
    BASE_H - BASE_H // 2,
)

#: 单人卡必须比多人卡**高**至少这么多像素（两帧实测 Δy≈342；取 200 = 58% 余量，与
#: ``scene/wuchong.py::MODE_MIN_SOLO_ABOVE_MULTI_DY`` 同口径 —— ★但这是 lords 自己的常量★，
#: 跨场景只做对账、不 import：判据唯一 ≠ 状态名共用）。
LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY: int = 200

#: 编队页的**正向锚**（★#100 第 7 个真机缺口：复核只认正向证据★）。
#:
#: 「到了编队页」的判据 = 【挑战】**且** 下面三个锚里**至少一个**：
#:   * ``SET`` —— 顶部 SET 选择器标签（真机帧 ``SET 1``）；
#:   * ``Party`` —— 队标签（真机帧 ``5 Party E`` / ``Party A``，见 ``scene/team.py``）；
#:   * ``自动续战`` —— 战前编队页的开关标签（``lord_team_page.png`` / ``TEAM_FRAME``）。
#:
#: ★为什么不能只看【挑战】★：详情页/编队页的提示条也可能 OCR 出「挑战」两个字；
#: 三个锚是**编队页独有**的（``scene/team.py`` 的真机标定 + ``lord_team_page.png``）。
#: ★为什么不能用「离开了模式页」★：真机 484（14:0x）点完「单人游戏」复核读到瞬时帧
#: ``lords_unknown``，旧判据据此判「离开了模式页」= **假成功**；15s 后手工 screencap
#: 设备其实**仍停在模式页**（单人/多人两张卡都在）。否定式判据分不清「转场帧」与「到了」。
LORDS_TEAM_ANCHORS: tuple[str, ...] = ("SET", "Party", "自动续战")

#: 点「单人游戏」的**换点阶梯**（★#100 第 7 个真机缺口★；720 空间 px，相对「单人游戏」框中心）：
#: 第一次点文字中心（当帧 OCR 框中心），无效后依次换 ``下方 100px`` → ``右侧 120px`` →
#: ``下方 180px``。★有界★：最多 4 次，每次点完等 :data:`LORDS_MODE_CLICK_WAIT_SEC` 再读。
#: 真机依据：484（14:0x）中心点下去**没生效**（画面仍停模式页），所以不能「点一次就不管了」。
LORDS_MODE_CLICK_LADDER: tuple[tuple[str, int, int], ...] = (
    ("中心", 0, 0),
    ("下方", 0, 100),
    ("右侧", 120, 0),
    ("底部", 0, 180),
)

#: 每次点完到「重新抓帧读」之间的**最小等待**（秒）—— 票面 2.5s（页面转场 + OCR 慢帧）。
LORDS_MODE_CLICK_WAIT_SEC: float = 2.5

#: 点「单人游戏」的**尝试上限（含首次）** = 换点阶梯的长度（4）。
#: 中心 → 下方 100px → 右侧 120px → 下方 180px，每次等 ≥2.5s 再读；
#: 四个点都试过 ⇒ 带量收工（:func:`mode_click_exhausted_reason`）。
LORDS_MODE_MAX_ATTEMPTS: int = len(LORDS_MODE_CLICK_LADDER)

#: 点完之后给页面切换的**宽限期**（秒）= :data:`TAB_CONFIRM_GRACE_SEC`（★不新造数字★）。
#: ★#100 第 7 个缺口之后它只作**文档/兼容**用★：复核已改成逐帧正向证据 + 换点阶梯
#: （阶梯自己每次等 :data:`LORDS_MODE_CLICK_WAIT_SEC`），不再用「宽限期后仍停在模式页」判失败。
LORDS_MODE_CONFIRM_GRACE_SEC: float = TAB_CONFIRM_GRACE_SEC

#: ★点完「单人游戏」后的**轮询读帧**参数（#100 第 9 个真机缺口）★
#:
#: 真机 484（2026-10-18 夜）实测时间线::
#:
#:     点「单人游戏」@720(170,523)
#:     +1.8s  弹出「要使用增加报酬的『领主加成点数』吗？」（是 / 否）   ← 旧判据读到 lords_unknown
#:     +2.6s  点「否」
#:     +3.9s  编队页（挑战 + SET 1 / Party A / 自动续战 = 正向证据）
#:
#: 旧实现固定 ``sleep(2.5)`` 只读**一帧**：那帧正是确认框（``lords_unknown``）⇒ 既判不出
#: 「到了编队页」，也看不见「有个「否」没人点」；换点阶梯随后全打在模态遮罩上。
#: 现在点完**轮询**（间隔 :data:`LORDS_MODE_POLL_INTERVAL_SEC`，单点最多
#: :data:`LORDS_MODE_POLL_TIMEOUT_SEC`），读到稳定分类再下结论。
LORDS_MODE_POLL_INTERVAL_SEC: float = 0.4
LORDS_MODE_POLL_TIMEOUT_SEC: float = 8.0
#: 连续读到几次同一个「稳定页」（非 unknown / 非 loading / 非编队页 / 非模式页）才接受它。
#: 2 = 一次可能是转场残留，两次才算数（OCR 一帧本身 ~1s，0.4s 间隔下约 1~2s）。
LORDS_MODE_STABLE_READS: int = 2
#: 连续读到几次**都是模式页**才判「这一点没生效」。
#: 3 = 点击后可能先闪一帧旧的模式页再转场；只看一帧会把正常转场误判成「点不动」。
LORDS_MODE_STILL_MODE_READS: int = 3

#: ★#100 第 9 个真机缺口：点「单人游戏」后弹的是**加成点数确认框**★（不是转场、也不是没点动）::
#:
#:     要使用增加报酬的「领主加成点数」吗？
#:     可能随挑战人数有所不同
#:     今天剩余次数x3
#:                       [是]   [否]
#:
#: 问题锚（OCR 实测两段，任一命中 + 读到「否」按钮框才算这个框）。
LORDS_MODE_BONUS_QUESTION_ANCHORS: tuple[str, ...] = ("领主加成点数", "增加报酬")
#: 两个按钮的**逐字**文案（★点的是「否」★）。
LORDS_MODE_BONUS_ACCEPT: str = "是"
LORDS_MODE_BONUS_DECLINE: str = "否"
#: ★默认点「否」★：不消耗每天有限的加成次数；真机 484（2026-10-18 夜）实测点「否」
#: 同样进入编队页（挑战 + SET 1 / Party A / 自动续战 = 正向证据）。
LORDS_MODE_BONUS_CHOICE: str = LORDS_MODE_BONUS_DECLINE
#: 每次 ``_mode_click`` 里**最多点几次确认框**（有界：确认框只该出现一次）。
LORDS_MODE_MAX_DIALOG_CLICKS: int = 1



@dataclass(frozen=True)
class ModeEvidence:
    """模式选择页一帧的证据（四段文案的 OCR 框，720 空间；缺哪段就是 ``None``）。

    ★为什么四段都要★：只看到一张卡的帧（进页动画 / OCR 漏读）**不许**当成模式页，
    更不许点 —— #116 的真机教训（五重那边）就是「只看到多人卡也照样算模式页」。
    位置（象限 + 单人卡必须更高）是**独立于字符串**的第二道证据。
    """

    solo: tuple[int, int, int, int] | None = None
    solo_note: tuple[int, int, int, int] | None = None
    multi: tuple[int, int, int, int] | None = None
    multi_note: tuple[int, int, int, int] | None = None

    @property
    def is_mode_page(self) -> bool:
        """四段文案齐 **且** 单人卡在多人卡上方 ≥ :data:`LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY`。"""
        if self.solo is None or self.solo_note is None:
            return False
        if self.multi is None or self.multi_note is None:
            return False
        return (_center(self.multi)[1] - _center(self.solo)[1]) >= LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY

    @property
    def solo_click_box(self) -> tuple[int, int, int, int] | None:
        """该点的框 = **``单人游戏`` 自己的当帧 OCR 框**（证据不足时 ``None`` ⇒ 不点）。

        ★不点 ``单人挑战领主``、更不点 ``多人游戏``★：前者是副标题（点了没反应），
        后者是**另一条路径**（共斗房）—— 点错就是开一局别人的房间。
        """
        return self.solo if self.is_mode_page else None

    def summary(self) -> str:
        """人读的一句话（日志 / detail 用；缺哪段一眼能看出来）。"""
        def _at(box):
            if box is None:
                return "缺"
            cx, cy = _center(box)
            return f"({cx:.0f},{cy:.0f})"

        return (
            f"单人游戏{_at(self.solo)}/单人挑战领主{_at(self.solo_note)}/"
            f"多人游戏{_at(self.multi)}/召集同伴挑战领主{_at(self.multi_note)}"
        )


def _text_box_in_roi(items, text: str, roi: tuple[int, int, int, int]):
    """在 ``roi`` 里找**逐字**等于 ``text`` 的 OCR 框（720 空间）；找不到返回 ``None``。

    ★逐字★（不是子串）：``单人游戏`` 不会吃掉 ``多人`` + ``游戏`` 那两颗被拆开的子框，
    也不会把 ``召集同伴挑战领主`` 里的「挑战」当成编队页按钮（那个判据是整串锚定的）。
    """
    x, y, w, h = roi
    for item_text, box in items or []:
        if str(item_text or "").strip() != text:
            continue
        quad = _box4(box)
        cx, cy = _center(quad)
        if x <= cx <= x + w and y <= cy <= y + h:
            return quad
    return None


def mode_evidence(items) -> ModeEvidence:
    """一帧 OCR 项 → :class:`ModeEvidence`（模式选择页的四段文案 + 各自象限）。"""
    return ModeEvidence(
        solo=_text_box_in_roi(items, LORDS_MODE_SOLO, LORDS_MODE_SOLO_ROI),
        solo_note=_text_box_in_roi(items, LORDS_MODE_SOLO_NOTE, LORDS_MODE_SOLO_ROI),
        multi=_text_box_in_roi(items, LORDS_MODE_MULTI, LORDS_MODE_MULTI_ROI),
        multi_note=_text_box_in_roi(items, LORDS_MODE_MULTI_NOTE, LORDS_MODE_MULTI_ROI),
    )


def team_anchor_hit(items):
    """这一帧命中的编队页**正向锚**（:data:`LORDS_TEAM_ANCHORS` 之一）；一个都没有 = ``None``。

    锚是**子串**匹配（OCR 会把 ``SET 1`` / ``5 Party E`` 连成一串，也可能把标签拆开）：
    ``SET`` / ``Party`` / ``自动续战`` 三个词在编队页之外几乎不出现，子串足够区分，
    而且不像位置判据那样会被版式抖动打穿。
    """
    for text, _box in items or []:
        stripped = str(text or "")
        for anchor in LORDS_TEAM_ANCHORS:
            if anchor in stripped:
                return anchor
    return None


def team_page_confirmed(items) -> bool:
    """★正向证据★：这一帧**明确是编队页** = 有【挑战】∧ :data:`LORDS_TEAM_ANCHORS` 至少一个。

    ★这是「点完单人游戏之后算不算成功」的唯一判据★（#100 第 7 个真机缺口）：
    不许再用「离开了模式页」这种否定式判据 —— 瞬时帧 / 转场帧都会「不是模式页」，
    但那**不是**到了编队页（真机 484 14:0x 的假成功正是这么来的）。

    消费方：``agent/lords_impl._note_mode_result`` / 换点阶梯的每次「点完重读」。
    """
    if not page_rule_hit(items, "编队页"):
        return False
    return team_anchor_hit(items) is not None


def _exact_text_box(items, text: str):
    """``text`` 逐字相等的 OCR 框（720 空间）；找不到返回 ``None``。

    ★逐字、不做子串★：确认框上的「否」只有两个字，子串匹配会把任何带「否」的长句
    （提示条 / 公告）当成按钮 —— 点错就是另一条路径。
    """
    for item_text, box in items or []:
        if str(item_text or "").strip() != text:
            continue
        return _box4(box)
    return None


@dataclass(frozen=True)
class BonusDialog:
    """「领主加成点数」确认框的证据（问题原文 + 两个按钮的 OCR 框，720 空间）。

    ★为什么必须单独认它★（#100 第 9 个真机缺口）：点完「单人游戏」后弹的是**模态确认框**，
    背景仍是模式页但「单人游戏」被遮住 ⇒ :func:`page_state` 只能给 ``lords_unknown``。
    修前把它当成「画面仍是模式页 / 转场帧」：换点阶梯的 4 个点全打在遮罩上，
    最后 9s 有界出口收工 —— 「点不动」的真因是**没人点那个「否」**。
    """

    #: 命中的问题原文（:data:`LORDS_MODE_BONUS_QUESTION_ANCHORS` 之一所在的整条文本）。
    question: str | None = None
    #: 「否」按钮的框（★默认点的那个★）。
    decline: tuple[int, int, int, int] | None = None
    #: 「是」按钮的框（只作证据/对账，运行时不点它 —— 会消耗每天有限的加成次数）。
    accept: tuple[int, int, int, int] | None = None

    @property
    def is_dialog(self) -> bool:
        """问题锚命中 **且** 读到「否」按钮框。

        ★读不到按钮框就不算★：认出来却点不了等于没认（调用方据此**不盲点**，
        继续轮询 / 带原因收工）。
        """
        return self.question is not None and self.decline is not None

    @property
    def decline_click_box(self) -> tuple[int, int, int, int] | None:
        """该点的框 = **「否」按钮自己的当帧 OCR 框**（不是固定坐标）。"""
        return self.decline if self.is_dialog else None

    def summary(self) -> str:
        """人读的一句话（日志 / detail 用；缺哪一半一眼能看出来）。"""

        def _at(box):
            if box is None:
                return "缺"
            cx, cy = _center(box)
            return f"({cx:.0f},{cy:.0f})"

        return f"问题={self.question!r}/是{_at(self.accept)}/否{_at(self.decline)}"


def bonus_dialog(items) -> BonusDialog:
    """一帧 OCR 项 → 「领主加成点数」确认框的证据（问题锚 + 「否」/「是」按钮）。

    真机 484（2026-10-18 夜）实测的 OCR 原文（720 空间）::

        要使用增加报酬的 / “领主加成点数”吗？ / 可能随挑战人数有所不同 / 今天剩余次数x3
        是 [504,805,36,36]        否 [178,805,37,37]

    ★为什么不用 ``page_state`` 加一个状态名★：这个框是**模态**的，背景仍是模式页；
    它只需要在「点完单人游戏之后」被处理一次，不是一整类页面（加状态名会牵动词表/快照/
    死线的全部判据，收益不成比例）。
    """
    question = None
    for text, _box in items or []:
        stripped = str(text or "")
        if any(anchor in stripped for anchor in LORDS_MODE_BONUS_QUESTION_ANCHORS):
            question = stripped
            break
    return BonusDialog(
        question=question,
        decline=_exact_text_box(items, LORDS_MODE_BONUS_DECLINE),
        accept=_exact_text_box(items, LORDS_MODE_BONUS_ACCEPT),
    )


def mode_click_points(box):
    """「单人游戏」框 → 换点阶梯的四个点 ``[(label, x, y), ...]``（720 空间，浮点）。

    点序 = :data:`LORDS_MODE_CLICK_LADDER`：中心 → 下方 100px → 右侧 120px → 下方 180px。

    ★框无效时返回空元组★（解不开 / 尺寸为 0 / 中心在 (0,0)）—— 调用方据此**绝不点**
    （#100 第 8 个真机缺口：识别没给框时绝不允许出现 ``点页签 @720(0,0)`` 这种盲点）。
    """
    if box is None:
        return ()
    try:
        quad = _box4(box)
    except (TypeError, IndexError, KeyError, ValueError):
        return ()
    if quad[2] <= 0 or quad[3] <= 0:
        return ()
    cx, cy = _center(quad)
    if cx == 0 and cy == 0:
        return ()
    return tuple((label, cx + dx, cy + dy) for label, dx, dy in LORDS_MODE_CLICK_LADDER)


def mode_click_exhausted_reason(
    last_state: str | None = None,
    last_anchor: str | None = None,
    note: str = "",
) -> str:
    """换点阶梯用尽仍没到编队页 ⇒ 带量收工的文案（★票面要求含「4 个点都试过」★）。

    修前写的是「画面仍是模式页」—— 那是**结论**，不是读数：真机 484（2026-10-18 夜）点完
    2.5s 读到的其实是 ``lords_unknown``（加成点数确认框），文案却断言「仍是模式页」，
    现场排查因此多绕了几小时。现在**只写读数**（最后一次的 state / 锚），再加上
    轮询参数（有界性可复核）。

    例：``模式页点不出去：单人游戏 中心/下方/右侧/底部 4 个点都试过（每点轮询 ≤8s、
    间隔 0.4s），最后一次读回 state=lords_unknown 锚=None —— 不是编队页（不假成功）``。
    """
    labels = "/".join(label for label, _dx, _dy in LORDS_MODE_CLICK_LADDER)
    if last_state:
        reading = f"最后一次读回 state={last_state} 锚={last_anchor!r}"
    else:
        reading = "一次有效读回都没有（每帧都是转场帧）"
    if note:
        reading += f"；{note}"
    return (
        f"模式页点不出去：{LORDS_MODE_SOLO} {labels} "
        f"{len(LORDS_MODE_CLICK_LADDER)} 个点都试过"
        f"（每点轮询 ≤{LORDS_MODE_POLL_TIMEOUT_SEC:g}s、间隔 {LORDS_MODE_POLL_INTERVAL_SEC:g}s），"
        f"{reading} —— 不是编队页（不假成功）"
    )


#: :func:`page_state` **按名引用**的页面判据（ADR-0003：判据全局唯一，场景只按名引用）。
#: ★本文件不复制 expected / roi★：表由 :func:`page_rule` 在 import 期取来（守卫 hooks_122
#: 逐字段对账「表 == scene/page_rules.py」，改一处漏一处就红）。
LORDS_PAGE_RULE_NAMES: tuple[str, ...] = ("战斗HUD", "结算页", "编队页", "详情页", "主城")

LORDS_PAGE_RULES: dict[str, dict] = {
    name: dict(page_rule(name).recognition) for name in LORDS_PAGE_RULE_NAMES
}


def _recognition_hit(items, recognition) -> bool:
    """一条 page_rule 形态的 recognition 在当前帧是否命中（只实现 OCR / And 两种）。

    与 pipeline 的语义一致：``OCR`` = 任一 ``expected`` 正则命中（带 ``roi`` 时框中心必须在
    ROI 内）；``And`` = 所有子判据都命中（战斗 HUD 就是 ``And(时间, 分数)`` —— 只命中
    「时间」**不算**战斗中，否则编队页的提示条会把整条链带偏）。
    """
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
            cx, cy = _center(_box4(box))
            if roi4[0] <= cx <= roi4[0] + roi4[2] and roi4[1] <= cy <= roi4[1] + roi4[3]:
                return True
        return False
    if kind == "And":
        return all(_recognition_hit(items, sub) for sub in (param.get("all_of") or ()))
    return False


def page_rule_hit(items, name: str) -> bool:
    """这一帧是不是 ``scene.page_rules`` 里那条页面（按名引用，不复制判据）。"""
    return _recognition_hit(items, LORDS_PAGE_RULES[name])


def loading_frame(items) -> bool:
    """这一帧是不是**加载 / 过场**帧（:data:`LORDS_LOADING_ANCHORS` 任一**子串**命中）。

    ★子串而不是整串★：真机的加载页会把百分比一起 OCR 出来（``请耐心等待 79.28%``，
    同一处读数见 ``scene/auto_switch.py``），整串锚定会把这种帧漏成 ``lords_unknown``。

    消费方：:func:`page_state`（→ :data:`LORDS_STATE_LOADING`）与
    ``agent/lords_impl._non_list_stuck``（过渡态不累加「无进展」计时）。
    """
    for text, _box in items or []:
        stripped = str(text or "")
        if any(anchor in stripped for anchor in LORDS_LOADING_ANCHORS):
            return True
    return False


def page_state(items) -> str:
    """一帧 OCR 项 → **lords 自己的页面状态名**（:data:`LORDS_STATES` 之一；认不出 = ``lords_unknown``）。

    判定顺序（先特异、后一般；★每一条都能说清为什么排在这里★）：

    0. ★**加载 / 过场**（本票新增的过渡态，:func:`loading_frame`）—— 最先判：它可以叠在
       任何页面上（半渲染的主城 / 加载中的列表页），晚判会把转场帧当成某一页的「稳定状态」
       （= 真机 484 14:5x 的误杀：``--home`` 之后立刻跑，9s 死线在任务还没开始时就收工）；
    1. **战斗 HUD**（``And(时间 mm:ss, 分数 N)``）—— 在**已知页面**里排第一：战斗中页面底部也画着
       各种字，晚判会被别的判据抢走；
    2. **结算页**（``^继续$``）；
    3. ★**模式选择页**（本票新增）★：四段文案 + 象限 + 单人卡更高（:class:`ModeEvidence`）；
    4. **编队页**（``^挑战(→)?$``，ROI 限底部按钮区）；
    5. **详情页**（``推荐编成``）；
    6. **列表页**（``更新列表``）；
    7. **主城**（右下角【领主战】入口）；
    8. 都不是 → ``lords_unknown``（★不猜★：认不出就说认不出，由有界出口收工）。

    ★消费方★：``lords_progress mode=solo`` 只在 ``lords_mode`` 上点「单人游戏」；
    ``mode=tab`` 用它做**日志降噪**（同一状态 + 同一原因只打一次）与**非列表页死线**
    （:data:`LORDS_TRANSITION_STATES` 里的过渡态在那条死线里**不累加**计时）。
    """
    if loading_frame(items):
        return LORDS_STATE_LOADING
    if page_rule_hit(items, "战斗HUD"):
        return LORDS_STATE_BATTLE
    if page_rule_hit(items, "结算页"):
        return LORDS_STATE_SETTLE
    if mode_evidence(items).is_mode_page:
        return LORDS_STATE_MODE
    if page_rule_hit(items, "编队页"):
        return LORDS_STATE_TEAM
    if page_rule_hit(items, "详情页"):
        return LORDS_STATE_DETAIL
    if list_page_present(items):
        return LORDS_STATE_LIST
    if page_rule_hit(items, "主城"):
        return LORDS_STATE_CITY
    return LORDS_STATE_UNKNOWN


def challenge_release_evidence(items) -> str:
    """这一帧是不是「点过【挑战】之后**已经离开编队页**」的正向证据（返回状态名，否则 ``""``）。

    ★这是闩的**主路径**★（真机 484 第 3 轮验收，``debug/lords_accept4.log``，17:26–17:33）：
    战斗/结算**实际发生了**（``trace13: state=wuchong_settle``），但旧实现只在 180s 超时时放闩
    ⇒ 每场白等 ~182s（战斗本身才 ~3 分钟），整条解禁循环被拖慢一倍。

    判据 = :func:`page_state` 的结果落在 :data:`LORDS_CHALLENGE_RELEASE_STATES` 里
    （★正向列举，绝不用「不是编队页」这种否定式判据★：转场帧 / 认不出的帧会被它骗）。

    ★为什么见到战斗/结算反而要放闩★：闩管的是「**别在同一个编队页上点第二次挑战**」。
    既然已经看到战斗 HUD / 结算页，那一下**确定生效**了；这两页上也没有【挑战】可点，
    继续闩着没有任何防双击价值，只会让 ``mode=pick`` 空转到 180s。
    """
    state = page_state(items)
    return state if state in LORDS_CHALLENGE_RELEASE_STATES else ""


# ---------------------------------------------------------------------------
# 7b. 详情页：逐档状态（``COMPLETE!!`` / ``NEW``）→ 只点**未通关**的那一档
# ---------------------------------------------------------------------------
# ★真机证据（真机 484 第 3 轮验收，``debug/lords_accept4.log`` 17:19–17:40）★
#
# 现象：解禁机制**能跑通一次**（`超级` NEW → COMPLETE!! SS 17:29:52 → 解锁 `地狱级` →
# 17:33 也 COMPLETE!! SS），但闭环没走完 —— 第 4/5/6 场全在重打**同一档**：
#   ``[lords] 点 tier @720(104,509)`` = 详情页**最上面**那一档（已是通关的地狱级）。
# 旧假设「未通关的 NEW 行永远最上（难度行降序 + 新解锁即最高档）」被真机推翻：
# 地狱级已通关却仍在最上 ⇒ 盲取最上面的战斗框 = 永远重打已通关的档。
#
# 版式（720 空间；全部是仓内帧的真实 OCR 读数）：
#   * ``tools/frames/lord_detail_multidiff.png``（妖狐，4 档全 COMPLETE!!）::
#         COMPLETE!! [15,388,126,22]  [15,578,125,23]  [15,769,123,24]  [15,960,127,22]
#         妖狐超级   [202,456,119,33]  妖狐高级+ [201,648,139,32]
#         妖狐高级   [202,837,119,33]  妖狐中级  [201,1028,121,33]
#   * ``tools/frames/lord_detail_redjoss_cleared.png``：4 档全 COMPLETE!!，第 2 档**弱读**
#     成 ``MPLETE!!``（[48,578,88,23]，丢首字母）；
#   * ``tools/frames/lord_detail_redjoss_early.png``：只有中级 + ``NEW`` [18,389,46,20] + 首次报酬。
#
# 三个数字就是判据（不是拍的）：
#   1. 徽标在**档名上方 ≈70px**（388 vs 456 / 578 vs 648 / 389 vs 458）；
#   2. 档名行距 ≈190px（456 → 648 → 837 → 1028）⇒ 120px 的纵向窗口**不可能跨行**；
#   3. 徽标在档名**左侧**（x≈15~48 vs 档名 x≈202）。
DETAIL_STATUS_COMPLETE = "complete"
DETAIL_STATUS_NEW = "new"
#: 「已通关」徽标的判据（★弱读兜底★：真机 ``COMPLETE!!`` 会丢首字母读成 ``MPLETE!!``；
#: 与 ``tools/gen_lord_registry.COMPLETE_MARK`` 同一串，两处都是「徽标本体」）。
DETAIL_MARK_COMPLETE = "PLETE!!"
DETAIL_MARK_NEW = "NEW"
#: 徽标与档名的**最大**纵向距离（= 同行带宽）。实测 ≈70px、行距 ≈190px ⇒ 120 不会跨行，
#: 又给 OCR 框抖动留了 50px。★超出它 = 不是这一档的徽标，宁可当「读不到状态」★。
DETAIL_MARK_MAX_DY = 120

# ---------------------------------------------------------------------------
# 7c. 列表页的**行名不能是徽标**（真机 484 第 5 轮验收，18:12–18:18）
# ---------------------------------------------------------------------------
#: 徽标词表：列表页上的这一行**行名**一旦等于/包含它们，就是「行名被读成了徽标」。
#:
#: 真机现场（``debug/lords_accept5.log``，第 1 轮关轮后重读的那一屏）::
#:
#:     rows: COMPLETE!! 4/4、COMPLETE!! 4/4、八岐大蛇讨伐 4/4、妖狐讨伐 1/4
#:
#: 4 行里 2 行的行名被读成了 ``COMPLETE!!``。原因不在 OCR 抽风：徽标与行名在列表行里是
#: **同一行带的两段文字**（徽标在左、行名在右），而 ``scene.lords_unlock.group_progress_rows``
#: 只按「左名右进度 + 纵向最近」做几何分组 —— 徽标比真行名更贴近进度时就会被挂成行名。
#: 后果不是「少读一行」而是**假行名**：``plan_round`` 会把它算进目标集合，
#: ``round_gained`` 也会把它当「新解锁」。所以纪律是：**宁可这一行不读，也不产生假行名**。
#:
#: 判据用**包含**而不是相等：徽标会被读成半串（``PLETE!!``，与 :data:`DETAIL_MARK_COMPLETE`
#: 同一串），也可能与别的字连成一串（``COMPLETE!! SS``）。
#: ★``SS`` 为什么按包含判也不会误杀★：它是评分徽标（详情页 ``COMPLETE!! SS``）；
#: 领主战花名册 ``scene.lords.LORDS`` 的行名逐条核对过，一个都不含 ``SS``/``NEW``/``COMPLETE!!``。
LIST_BADGE_MARKS: tuple[str, ...] = (
    "COMPLETE!!",
    DETAIL_MARK_COMPLETE,      # 弱读 ``PLETE!!`` / ``MPLETE!!`` —— 同一个「徽标本体」
    DETAIL_MARK_NEW,           # ``NEW``（= 未通关徽标）
    "首次报酬",
    "SS",                      # 评分徽标（``COMPLETE!! SS``）
)


def is_badge_text(text) -> bool:
    """这段 OCR 文本是不是**徽标**（而不是行名）。

    见 :data:`LIST_BADGE_MARKS`：空串 ⇒ ``False``；否则**大写折叠后按包含判**（徽标会被读成
    半串/连串）。调用方（``agent/lords_impl._drop_badge_rows``）**先**用
    :func:`recover_badge_row_name` 把这一行的真名找回来；找不回来才整行剔掉 ——
    ★不是把它当行名，而是这一行不读★：认不出是谁的进度，就不能拿它规划。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return False
    folded = stripped.upper()
    return any(str(mark).upper() in folded for mark in LIST_BADGE_MARKS)


# ---------------------------------------------------------------------------
# 7d. 行名被读成徽标 ⇒ **用几何把真名框找回来**（真机 484 accept7，2026-10-18 夜）
# ---------------------------------------------------------------------------
# ★病因（不是猜的：真机帧逐条的 OCR 框）★
#
# ``screenshots/accept6_lords_list_bottom_MM.png``（720 空间，MaaFramework OCR 原值，
# 领主战页签、5 行全 M/M）—— 每一行是**四段竖排**：
#
#     行 1 的徽标  COMPLETE!!             [15, 448, 121, 24]   ← 在自己的行名上方 ≈52px
#     行 1 的副标题 领主战                [201, 467, 70, 28]
#     行 1 的行名   废墟魔像讨伐           [202, 496, 165, 32]   ← 真名**读出来了**
#     行 1 的通关数 通关数4/4              [547, 545, 127, 28]
#     行 2 的徽标  COMPLETE!!             [14, 592, 127, 24]
#     行 2 的行名   废墟守卫·火讨伐         [203, 641, 197, 28]
#     行 2 的通关数 通关数4/4              [547, 689, 126, 28]
#
# 行距 144px。对**行 2** 的通关数（中心 610,703）来说：
#
#   * 行 2 的真名 废墟守卫·火讨伐（中心 301.5,655）⇒ dy = **48**   ← 真名在这里
#   * 行 3 的徽标 COMPLETE!! [13,735,127,27]（中心 76.5,748.5）⇒ dy = **45.5**  ← 更近 2.5px
#
# ``group_progress_rows`` 只按「左名右进度 + 纵向最近」分组 ⇒ 行 3 的徽标被挂成了
# 行 2 的**行名**。整屏 5 行全 M/M 时，前 4 行的进度全被「下一行的徽标」抢走，
# 只剩最后一行（维·索拉斯讨伐 3/3）一个真名 ⇒ 真机日志逐字对上::
#
#     [lords] 行名过滤（page）：4 行的行名读成了徽标 ['COMPLETE!!', ...]
#     [lords] 页读「领主战」：本帧 1 行（新 1 / 重复 0，累计 1）…
#
# 另三帧同病、但丢的是**未通关行 / 花名册外的活动行**（不只是少读一行，而是**漏规划**或
# **永远判不了全通**）：
#
#   * ``screenshots/accept6_yaohu_3of4.png``：COMPLETE!! [13,1160,126,27]（下一行的徽标，
#     被滚到屏幕下沿）抢走 妖狐讨伐 3/4 [201,1067,114,33] / 通关数3/4 [549,1119,125,24]；
#   * ``screenshots/accept7_list_2.png``：COMPLETE!! [14,769,125,24]（闪哭机兵那行的徽标）
#     抢走 **碧愁机兵 1/4** / 通关数1/4 [549,723,126,28]；
#   * ``screenshots/accept6_jianglin_hongji_cangtan_1of4.png``（降临讨伐）：
#     COMPLETE!! [15,735,122,23] 抢走 **五王连战 1/1** [201,637,115,32] / [547,688,123,28]。
#     ★这一行**不在领主花名册里**（它是五重决战的活动行）★ ⇒ 恢复候选**不能按花名册筛**：
#     只认花名册的话它永远找不回来，``dropped_in_scan`` 每帧 +1 ⇒ ``all_done`` 照样永远 False
#     （本票会被「换个角落」重演）。
#
# ⇒ 结论：**真名框在帧里、OCR 也读出来了，错的是配对**（徽标属于下一张卡、却比本卡真名
# 更贴近本卡的进度 2.5–4px）。所以修法是**把真名找回来**，不是整行不读；候选只排除
# **确定不是行名**的文本（徽标 / 进度 / 页签副标题 / 固定元素 / 列表体外的底栏横幅），
# 行名到底是谁交给 ``plan_round`` 的花名册与 M 校验（不在册的报 ``unknown_row``，不猜着打）。
# 只有「排除这些后仍找不到行名」时才退回到本文件既有的纪律：这一行不读、不判全通。
BADGE_RECOVERY_MAX_DY: int = MAX_NAME_DY
#: 真名与进度的横向最小间隙（= :data:`scene.lords_unlock.MIN_NAME_LEFT_GAP`，不另发明）。
BADGE_RECOVERY_MIN_LEFT_GAP: int = MIN_NAME_LEFT_GAP


def recover_badge_row_name(
    items,
    progress_box,
    *,
    max_dy: int = BADGE_RECOVERY_MAX_DY,
    min_left_gap: int = BADGE_RECOVERY_MIN_LEFT_GAP,
):
    """一行读数**行名被读成了徽标**时，按几何把这一行**真行名框**找回来。

    候选 = 当帧 OCR 里**不是徽标、不是进度、不是页签/副标题/固定元素**的文本
    （:func:`is_badge_text` / :func:`scene.lords_unlock.parse_progress` /
    :data:`scene.lords_unlock.NOT_A_ROW_NAME` / :data:`LORD_TABS`），并且：

    * 框中心落在 :data:`ROW_ROI` 内（行名只可能在列表体里 —— 底栏/横幅/页签不是行名）；
    * 在「通关数」左侧且横向间隙 ≥ ``min_left_gap``（左名右进度的版式）；
    * 纵向 |dy| ≤ ``max_dy``，取**纵向最近**、再取横向更靠右（与
      ``group_progress_rows`` 的配对判据**同一条**，只是把徽标从候选里剔掉）。

    ★为什么不按花名册筛★：真机列表里有**不在花名册**的活动行（``五王连战 1/1``，
    ``screenshots/accept6_jianglin_hongji_cangtan_1of4.png``），它的徽标同样会抢走自己的进度；
    只认花名册 ⇒ 这行永远找不回来 ⇒ ``dropped_in_scan`` 把 ``all_done`` 永远压成 False。
    行名认不认得由 ``plan_round`` 决定（不在册 ⇒ ``unknown_row``，**不猜着打**），
    这里只负责「把这一行的名字从帧里找回来」。

    返回 ``(行名, 行名框)``；找不到返回 ``None``（★调用方必须退回「整行不读」★，
    绝不拿一个猜出来的名字去规划）。

    ``progress_box`` 是那一行的「通关数」框（:attr:`RowReading.progress_box`）。
    """
    try:
        px, py, pw, ph = _box4(progress_box)
    except (TypeError, IndexError, KeyError, ValueError):
        return None
    if pw <= 0 or ph <= 0:
        return None
    progress_cx = px + pw / 2.0
    progress_cy = py + ph / 2.0
    best = None
    for text, box in items or ():
        stripped = str(text or "").strip()
        if not stripped or is_badge_text(stripped):
            continue                                  # ★徽标永远不是行名★
        if stripped in NOT_A_ROW_NAME or stripped in LORD_TABS:
            continue                                  # 固定元素 / 页签副标题
        if parse_progress(stripped) is not None:
            continue                                  # 进度自己不是行名
        if re.fullmatch(r"[\d\s/|\\⁄╱.,:：]+", stripped):
            continue                                  # 纯数字/纯符号不是行名
        try:
            quad = _box4(box)
        except (TypeError, IndexError, KeyError, ValueError):
            continue
        if quad[2] <= 0 or quad[3] <= 0:
            continue
        if not row_roi_hit(quad):
            continue                                  # 行名只在列表体里
        name_cx, name_cy = _center(quad)
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


#: 详情页左下角的【返回】（= 底部导航最左槽；``common.json::PubReturnHomeBackTab`` 的 ROI
#: ``[0,1180,110,100]``，与 ``scene/events.py`` #18 的实测注释同一处）。点它回到列表。
DETAIL_BACK_TEXT = "返回"
DETAIL_BACK_ROI: tuple[int, int, int, int] = (0, 1180, 110, 100)

#: :func:`pick_uncleared_tier` 的四种结论（机器可判；日志/detail 都带它）。
DETAIL_PICK_READY = "pick"                  # 选出了未通关的一档
DETAIL_PICK_ALL_COMPLETE = "all_complete"   # 每一档都 COMPLETE!! ⇒ 不点任何档
DETAIL_PICK_NO_STATUS = "no_status"         # 读不到状态 ⇒ 不盲点（这是本票要的那条）
DETAIL_PICK_NO_TIERS = "no_tiers"           # 一档行名都没读出来（不是详情页）

#: 三条用户可见文案（守卫 hooks_122 逐字钉「不是旧的取最上面」）。
DETAIL_TIER_NO_STATUS_REASON = (
    "详情页读不到任何档状态（{n} 档里 0 档有 COMPLETE!!/NEW）—— 不盲点"
    "（绝不回到「取最上面那个战斗框」的旧行为）"
)
DETAIL_TIER_ALL_DONE_REASON = (
    "详情页全部 {n} 档都是 COMPLETE!!（本账号这一行可见档已清空）—— "
    "不点任何档，点【返回】回列表重读 `通关数 N/M`（D6 关轮）"
)
DETAIL_TIER_UNREAD_REASON = (
    "详情页有 {k} 档读不到状态（{names}）—— 不盲点（读不出的档不能当未通关）"
)


def _quad(box):
    """OCR 框 → 四整数元组；解不开 / 零尺寸返回 ``None``（★不抛★）。

    ★为什么不直接下标★：一帧里只要有一个坏框（``None`` / 2 元组 / maa ``Rect``），
    整条选档逻辑都会炸 —— 而**认不出**的后果必须只是「这一档没读数」，不是任务崩。
    """
    if box is None:
        return None
    try:
        x, y, w, h = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (int(x), int(y), int(w), int(h))


def detail_status_text(status: str | None) -> str:
    """状态名 → 人读文案（``COMPLETE!!`` / ``NEW`` / ``未读数``）。"""
    if status == DETAIL_STATUS_COMPLETE:
        return "COMPLETE!!"
    if status == DETAIL_STATUS_NEW:
        return "NEW"
    return "未读数"


#: 难度后缀的整串正则（长词优先：``高级+`` 必须排在 ``高级`` 前面，否则会被切错）。
_TIER_SUFFIX = "|".join(
    re.escape(name) for name in sorted(DIFFICULTIES, key=len, reverse=True)
)
DETAIL_TIER_NAME_RE = re.compile(
    rf"^(?P<prefix>.*?)(?P<difficulty>{_TIER_SUFFIX})$", re.DOTALL
)


def detail_tier_name(text: str):
    """详情页档名 → ``(前缀, 难度)``；不是档名返回 ``None``。

    例：``机工神兵菲诺梅那超级`` → ``("机工神兵菲诺梅那", "超级")``。
    判据 = **难度词表整串锚定**（:data:`scene.config.DIFFICULTIES`，尾部长词优先）——
    不是「行名里含难度字」，所以 ``超级`` 不会命中 ``超级管理员`` 那种别的控件。
    """
    match = DETAIL_TIER_NAME_RE.match(str(text or "").strip())
    if match is None:
        return None
    return (match.group("prefix"), match.group("difficulty"))


def detail_mark_status(text: str):
    """徽标文字 → :data:`DETAIL_STATUS_COMPLETE` / :data:`DETAIL_STATUS_NEW`；不是徽标返回 ``None``。

    ★顺序★：先判 COMPLETE（含弱读 ``MPLETE!!``），再判 NEW —— 两串不会互相包含
    （``COMPLETE!!`` 里没有 ``NEW``），顺序只是让「坏读成半串」的帧也归到已通关那一侧。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if DETAIL_MARK_COMPLETE in stripped:
        return DETAIL_STATUS_COMPLETE
    if stripped.upper().startswith(DETAIL_MARK_NEW):
        return DETAIL_STATUS_NEW
    return None


@dataclass(frozen=True)
class DetailTier:
    """详情页上的一档：难度、整串行名、行名框、状态（可能读不到）、徽标框。"""

    difficulty: str
    label: str
    name_box: tuple[int, int, int, int]
    status: str | None = None
    mark_box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class DetailTierChoice:
    """「该点哪一档」的判决（纯数据；:func:`pick_uncleared_tier` 的唯一输出）。"""

    status: str
    difficulty: str | None = None
    label: str | None = None
    name_box: tuple[int, int, int, int] | None = None
    mark_box: tuple[int, int, int, int] | None = None
    tiers: tuple[DetailTier, ...] = ()
    reason: str = ""

    @property
    def picked(self) -> bool:
        """是否选出了**可以点**的一档（= ``status == DETAIL_PICK_READY``）。"""
        return self.status == DETAIL_PICK_READY

    def summary(self) -> str:
        """人读一行：``地狱级=COMPLETE!! / 超级=NEW / …``（按详情页从上到下）。"""
        return " / ".join(
            f"{tier.difficulty}={detail_status_text(tier.status)}" for tier in self.tiers
        )


def detail_tier_rows(items) -> tuple[DetailTier, ...]:
    """读详情页**每一档**的（难度, 行名框, 状态徽标）；按**从上到下**排序。

    配对规则（纯几何，三个数字见本节抬头）：
      * 徽标中心必须在档名中心的**左侧**（``mark.cx < name.cx``）；
      * 徽标在档名**上方**且距离 ``0 < dy <= DETAIL_MARK_MAX_DY``（120）；
      * 多个徽标同时满足 ⇒ 取**纵向最近**的那个（同一行带里只有这一个）。

    ★读不到不是猜★：配对失败的那一档 ``status=None``（由 :func:`pick_uncleared_tier`
    决定「不点」），绝不按「它是第几行」推测它通关了没有。
    """
    names: list = []
    marks: list = []
    for text, box in items or []:
        quad = _quad(box)
        if quad is None:
            continue
        stripped = str(text or "").strip()
        if not stripped:
            continue
        parsed = detail_tier_name(stripped)
        if parsed is not None:
            names.append((parsed, stripped, quad))
            continue
        status = detail_mark_status(stripped)
        if status is not None:
            marks.append((status, quad))
    rows: list[DetailTier] = []
    for (_prefix, difficulty), label, box in names:
        ncx, ncy = _center(box)
        best = None
        for status, mark_box in marks:
            mcx, mcy = _center(mark_box)
            if mcx >= ncx:                 # 徽标必须在这一档的**左侧**
                continue
            dy = ncy - mcy                 # 且在**上方**（真机 ≈70px）
            if dy <= 0 or dy > DETAIL_MARK_MAX_DY:
                continue
            if best is None or dy < best[0]:
                best = (dy, status, mark_box)
        rows.append(
            DetailTier(
                difficulty=difficulty,
                label=label,
                name_box=box,
                status=best[1] if best is not None else None,
                mark_box=best[2] if best is not None else None,
            )
        )
    rows.sort(key=lambda row: _center(row.name_box)[1])
    return tuple(rows)


def pick_uncleared_tier(items, difficulty: str | None = None) -> DetailTierChoice:
    """详情页 → **未通关**的那一档（★本票 ① 的核心：按状态选，不按位置选★）。

    判决顺序：

    1. 一档行名都读不出 → ``no_tiers``（这不是详情页 / 行名被 OCR 读丢）；
    2. **一档状态都读不到** → ``no_status``（★绝不盲点、绝不回到「取最上面」★）；
    3. 目标档（``difficulty``，来自 ``plan_round``）状态是 ``NEW`` → 就选它（尊重本轮规划）；
    4. 否则取**从上往下第一个 ``NEW``**（= 当前能打的最高未通关档；
       正常账号最多只有一档 NEW，多档时取最上面的那个）；
       若目标档读到了、但已 ``COMPLETE!!`` ⇒ 不点它（日志写明），改选别的 NEW；
    5. 每一档都读到了状态且全是 ``COMPLETE!!`` → ``all_complete``（不点任何档）；
    6. 有档读不到状态、且没有 NEW → ``no_status``（读不出的档不能当未通关，也不当已通关）。

    ★为什么第 4 条是「从上往下第一个 NEW」而不是「最上面那一档」★：详情页是**降序**
    （顶 = 最高档），未通关的档就散落在行里；「最上面」只在「新解锁即最高档」时碰巧等于
    NEW，而真机 484 已经证伪了那个假设（地狱级已 COMPLETE!! 却仍在最上）。
    """
    tiers = detail_tier_rows(items)
    if not tiers:
        return DetailTierChoice(
            DETAIL_PICK_NO_TIERS,
            reason="详情页一档行名都没读出来（不是详情页 / 行名被 OCR 读丢）—— 不盲点",
        )
    read_tiers = [tier for tier in tiers if tier.status is not None]
    if not read_tiers:
        return DetailTierChoice(
            DETAIL_PICK_NO_STATUS,
            tiers=tiers,
            reason=DETAIL_TIER_NO_STATUS_REASON.format(n=len(tiers)),
        )
    unread = [tier for tier in tiers if tier.status is None]
    declared = None
    if difficulty:
        declared = next((tier for tier in tiers if tier.difficulty == difficulty), None)
    if declared is not None and declared.status == DETAIL_STATUS_NEW:
        return DetailTierChoice(
            DETAIL_PICK_READY,
            difficulty=declared.difficulty,
            label=declared.label,
            name_box=declared.name_box,
            mark_box=declared.mark_box,
            tiers=tiers,
            reason=f"目标档「{declared.difficulty}」状态 NEW（未通关）",
        )
    fresh = [tier for tier in tiers if tier.status == DETAIL_STATUS_NEW]
    if fresh:
        chosen = fresh[0]
        why = f"从上往下第一个 NEW = 第 {tiers.index(chosen) + 1} 档「{chosen.difficulty}」"
        if declared is not None and declared.status == DETAIL_STATUS_COMPLETE:
            why += f"（目标档「{declared.difficulty}」已 COMPLETE!! —— 不点它）"
        return DetailTierChoice(
            DETAIL_PICK_READY,
            difficulty=chosen.difficulty,
            label=chosen.label,
            name_box=chosen.name_box,
            mark_box=chosen.mark_box,
            tiers=tiers,
            reason=why,
        )
    if not unread:
        return DetailTierChoice(
            DETAIL_PICK_ALL_COMPLETE,
            tiers=tiers,
            reason=DETAIL_TIER_ALL_DONE_REASON.format(n=len(tiers)),
        )
    names = "、".join(tier.difficulty for tier in unread)
    return DetailTierChoice(
        DETAIL_PICK_NO_STATUS,
        tiers=tiers,
        reason=DETAIL_TIER_UNREAD_REASON.format(k=len(unread), names=names),
    )


def detail_back_box(items):
    """详情页左下角【返回】的 OCR 框（720 空间）；不在详情页 / 读不到返回 ``None``。

    判据 = :data:`DETAIL_BACK_ROI`（底部导航最左槽）+ :func:`page_state` == ``lords_detail``。
    ★为什么必须限定详情页★：列表页最左槽也是【返回】，但那一屏该做的是读 `通关数`，
    不能把「回到列表」当成「离开列表」。
    """
    if page_state(items) != LORDS_STATE_DETAIL:
        return None
    return _text_box_in_roi(items, DETAIL_BACK_TEXT, DETAIL_BACK_ROI)


#: ★#100 第 5 个真机缺口★ 非列表页「**状态名** K 秒不变」→ 带原因收工的死线（秒）。
#:
#: 取值依据（不是随手取的）：票面给的区间是 **8–10s**，取 **9** = 区间中值；
#: * 下限为什么不能更小：一次点击后的页面转场（``lords.json`` 各业务节点 ``post_delay``
#:   ≤2500ms）+ 两次 OCR 慢帧（~2s）最多 ~5s，8s 起才不会被正常转场误伤；
#: * 上限为什么不放大：模式选择页/详情页/编队页上原本**没有任何有界出口**（20s「点不出去」
#:   死线只在 ``mode=read`` 判，而这些页面读不到 ``通关数``）—— 越大越接近「看起来在跑」；
#: * ★**战斗/结算不靠这个数字排除**★：它们由 :data:`LORDS_ACTIVE_STATES` 整类排除
#:   （那里「没有导航进展」是正常的，且一场仗可以打几分钟）。
NON_LIST_STUCK_SEC: float = 9.0

#: 非列表页死线的**收工文案**（用户可见；守卫 hooks_122 逐字钉住「带状态名」）。
#: ``{state}`` / ``{seconds}`` 由调用方填。
NON_LIST_STUCK_REASON = (
    "收工 —— 卡在「{state}」这类非列表页 {seconds:.0f}s 没有任何进展"
    "（不在列表页，无法导航）"
)


def non_list_stuck_reason(state: str, seconds: float) -> str:
    """非列表页死线的收工理由（★带状态名与秒数★：现场一眼能看出卡在哪个页面）。"""
    return NON_LIST_STUCK_REASON.format(state=state, seconds=float(seconds))


__all__ = [
    "ACTION_CANNOT",
    "ACTION_CLICK",
    "ACTION_GIVE_UP",
    "ACTION_OK",
    "ACTION_STOP",
    "BADGE_RECOVERY_MAX_DY",
    "BADGE_RECOVERY_MIN_LEFT_GAP",
    "BonusDialog",
    "CONFIRM_BASIS",
    "DETAIL_BACK_ROI",
    "DETAIL_BACK_TEXT",
    "DETAIL_MARK_COMPLETE",
    "DETAIL_MARK_MAX_DY",
    "DETAIL_MARK_NEW",
    "DETAIL_PICK_ALL_COMPLETE",
    "DETAIL_PICK_NO_STATUS",
    "DETAIL_PICK_NO_TIERS",
    "DETAIL_PICK_READY",
    "DETAIL_STATUS_COMPLETE",
    "DETAIL_STATUS_NEW",
    "DETAIL_TIER_ALL_DONE_REASON",
    "DETAIL_TIER_NAME_RE",
    "DETAIL_TIER_NO_STATUS_REASON",
    "DETAIL_TIER_UNREAD_REASON",
    "DetailTier",
    "DetailTierChoice",
    "END_ANCHORS",
    "LIST_BADGE_MARKS",
    "LIST_PAGE_ANCHOR",
    "LORD_TABS",
    "LORDS_ACTIVE_STATES",
    "LORDS_CHALLENGE_RELEASE_STATES",
    "LORDS_LOADING_ANCHORS",
    "LORDS_MODE_BONUS_ACCEPT",
    "LORDS_MODE_BONUS_CHOICE",
    "LORDS_MODE_BONUS_DECLINE",
    "LORDS_MODE_BONUS_QUESTION_ANCHORS",
    "LORDS_MODE_CLICK_LADDER",
    "LORDS_MODE_CLICK_WAIT_SEC",
    "LORDS_MODE_CONFIRM_GRACE_SEC",
    "LORDS_MODE_MAX_ATTEMPTS",
    "LORDS_MODE_MAX_DIALOG_CLICKS",
    "LORDS_MODE_MIN_SOLO_ABOVE_MULTI_DY",
    "LORDS_MODE_MULTI",
    "LORDS_MODE_MULTI_NOTE",
    "LORDS_MODE_MULTI_ROI",
    "LORDS_MODE_POLL_INTERVAL_SEC",
    "LORDS_MODE_POLL_TIMEOUT_SEC",
    "LORDS_MODE_SOLO",
    "LORDS_MODE_SOLO_NOTE",
    "LORDS_MODE_SOLO_ROI",
    "LORDS_MODE_STABLE_READS",
    "LORDS_MODE_STILL_MODE_READS",
    "LORDS_PAGE_RULES",
    "LORDS_PAGE_RULE_NAMES",
    "LORDS_STATES",
    "LORDS_STATE_BATTLE",
    "LORDS_STATE_CITY",
    "LORDS_STATE_DETAIL",
    "LORDS_STATE_LIST",
    "LORDS_STATE_LOADING",
    "LORDS_STATE_MODE",
    "LORDS_STATE_SETTLE",
    "LORDS_STATE_TEAM",
    "LORDS_STATE_UNKNOWN",
    "LORDS_TEAM_ANCHORS",
    "LORDS_TRANSITION_STATES",
    "ModeEvidence",
    "NAV_STUCK_SEC",
    "NON_LIST_STUCK_REASON",
    "NON_LIST_STUCK_SEC",
    "NavState",
    "PAIR_SEP",
    "PICK_ACTION_FAIL",
    "PICK_ACTION_READY",
    "PICK_ACTION_SCROLL",
    "PICK_ACTION_TAB",
    "PICK_ACTION_WAIT",
    "PICK_FAIL_CLICK",
    "PICK_FAIL_NOT_FOUND",
    "PICK_FAIL_SCROLL",
    "PICK_FAIL_TAB",
    "PICK_PHASE_DONE",
    "PICK_PHASE_DOWN",
    "PICK_PHASE_UP",
    "PICK_REASON_CLICK",
    "PICK_REASON_NOT_FOUND",
    "PICK_REASON_SCROLL",
    "PICK_REASON_TAB",
    "PICK_SCROLL_DOWN",
    "PICK_SCROLL_UP",
    "PICK_TAB_WAIT_SEC",
    "PickDecision",
    "PickNav",
    "ROW_ROI",
    "SCROLL_PLAN",
    "SCREEN_H",
    "SCREEN_W",
    "ScrollPlan",
    "TAB_ANCHORS",
    "TAB_CONFIRM_GRACE_SEC",
    "TAB_LABELS_ALWAYS_PRESENT",
    "TAB_SWITCH_MAX_ATTEMPTS",
    "TAB_UNCONFIRMED_LIMIT",
    "TabAnchor",
    "TabDecision",
    "TabEvidence",
    "classify_kind",
    "bonus_dialog",
    "challenge_release_evidence",
    "detail_back_box",
    "detail_mark_status",
    "detail_status_text",
    "detail_tier_name",
    "detail_tier_rows",
    "end_anchor_hit",
    "is_badge_text",
    "label_box",
    "list_page_present",
    "loading_frame",
    "mode_click_exhausted_reason",
    "mode_click_points",
    "mode_evidence",
    "non_list_stuck_reason",
    "on_screen",
    "page_rule_hit",
    "page_state",
    "pick_uncleared_tier",
    "recover_badge_row_name",
    "row_key",
    "row_roi_hit",
    "tab_labels",
    "tab_of_kind",
    "tab_of_row",
    "tab_state",
    "team_anchor_hit",
    "team_page_confirmed",
]

