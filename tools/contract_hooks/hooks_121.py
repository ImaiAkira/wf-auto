# -*- coding: utf-8 -*-
"""#100 第 3 条真机缺口：**pick 阶段点不到目标** —— 先对页签、再上下找，三种原因分开。

真机现场（484，12:0x，``--trace LordsEntry``，滚动到底已经修好之后）
-------------------------------------------------------------------
::

    [lords] 两个页签都扫到底（['领主战', '降临讨伐']）—— 扫描阶段结束
    [lords] 两个页签共扫到 26 行 —— 交给 mode=read 判一轮
    [lords] 收工：目标「无猾机兵」已经 51s 点不出去（死线 20s，口径照 #62 的有界跳过）

修前 ``mode=pick`` 只做 ``pick_click``（三跳：行 / 该档【战斗】/【挑战】），它**不切页签、
也不滚动**。而扫描阶段一结束，导航链就停了 —— 目标行既不在当前页签、又滚出了屏幕时，每一圈
都 no-hit，最后只能干等「点不出去」死线。

证据帧 ``tools/frames/lords_pick_stuck_on_joss_tab.png``（2026-10-18 12:07，仓内已入库）
的逐条读数（1080 空间，OCR 原文）::

    领主战      [202,582,135,52]      降临讨伐（页签）[722,584,175,48]   更新列表 [923,492,123,42]
    伊尔梅塔雷讨伐 [301,744,292,48]  + 通关数1/4 [821,818,191,42]
    伊尔格拉乌讨伐 [303,962,288,42]  + 通关数1/4 [821,1032,191,42]
    伊劳德雷斯讨伐 [301,1176,292,48] + 通关数1/4 [821,1248,191,42]
    伊萨巴迪卡讨伐 [299,1388,294,52] + 通关数1/4 [821,1466,191,42]
    伊尔考普斯讨伐 [303,1608,290,48] + 通关数1/4 [821,1682,191,42]

⇒ ★这张帧纠正了票面的一句判断★：``无猾机兵`` 不在「领主战」页签上。``scene/lords.py`` 里
它是 ``kind='joss'``（``slug='joss/无猾机兵'``，真机帧 ``lord_page_tab_joss.png`` 的同一行
``通关数5/5``），这张帧里的 5 行**全是 joss 成员**且 ``tab_state`` 确认 ``降临讨伐``。
所以现场真正缺的是**向上找**（目标在列表更靠上的位置，画面停在中部/底部），页签本身是对的；
「先对页签」这条仍然必须做（跨页签的目标在别的轮次里会出现），但**它不是这次现场的第一病因**。

四个挂点
--------
1. ``lords-pick-tab-first``
   ★页签先行★：目标 ``tab=joss``、当前 ``tab=lord`` ⇒ pick 必须**先点页签**（点当帧标签框中心）、
   **再**去点目标行；页签点击**不许**记成「点了一次目标」（``attempts_since_read`` 不变），
   也**不许**消耗「点不出去」死线（``last_click_at`` 被刷新 ⇒ 过 1s 的 ``mode=read`` 不收工，
   而没刷新时同一时刻会收工 —— 两边都断言）。
2. ``lords-pick-scroll-search``
   ★上下找★：目标行不在当帧 ⇒ 先**向下**滚（最多 ``SCROLL_PLAN.max_scrolls_per_page`` 次），
   向下到底再**向上**滚（**同一个手势反向**，几何仍只有 ``SCROLL_PLAN`` 一份）；
   「行在第 3 屏」的剧本必须**滚 2 次后找到**，不是当场放弃；两向都到底 ⇒ 带原因收工。
   滚动**不消耗**「点不出去」死线，且**自己补足** ``settle_ms`` 的稳定等待
   （``LordsPickTarget`` 的 ``post_delay`` 只有 800ms < 2600，#42 惯性）。
3. ``lords-pick-reasons``
   ★三种失败原因必须分开★（今晚因为「症状离病因太远」浪费过时间）：三段剧本各自收工，
   ``reason`` 里分别含 ``目标不在这个页签`` / ``滚到底也没找到`` / ``找到了但点不动``，
   且**互不含**对方的分句；最后一种带行框、前两种带页签名与滚动次数。
4. ``lords-pick-nav-snapshot-parity``
   ★安装态单源★：``agent/lords_impl._PickNavSnapshot`` == ``scene/lords_nav.PickNav``
   （常量逐项 + 同一段剧本的判决/次数/文案逐项相等），``SCROLL_PLAN.up_begin/up_end`` 逐字段相等。

★诚实边界★
* 本守卫**不碰设备**：假 OCR 用的是证据帧的**逐条读数**（720 空间，1080 ÷1.5）与合成帧；
  它证的是「实现能按这些读数做出正确判决」，不是「今天真机还是这样」。
* 「切页签后列表是否回到顶部」仍未真机标定（见 ``scene/lords_nav.reset_page`` 的假设）——
  本票的上下找对两种情形都成立（先下后上），所以不依赖那条假设。
* 页签真的切不过去时，``LordsSwitchTab``（枢纽里排在 pick 之前）会先收工；那条路径的
  文案由 ``agent/lords_impl._tab_unreachable_reason`` 与 pick 统一成同一句「目标不在这个页签」。

破坏实验（``python tools\\contract_hooks\\hooks_121.py``，全部在内存里做）
----------------------------------------------------------------------
① **pick 不找只点**（把 ``_pick_locate`` 摘掉 = 修前的老行为）→ 挂点 1/2/3 红；
② **页签对齐失效**（``switch_decision`` 恒 ``ok``）→ 挂点 1 红；
③ **去掉向上找**（向下到底就直接判「找不到」）→ 挂点 2 红；
④ **滚动也消耗死线**（滚完把 ``last_click_at`` 还原）→ 挂点 2 红；
⑤ **三原因合并成一句**（三个 ``PICK_REASON_*`` 改成同一个词）→ 挂点 3 红。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = Path(__file__).resolve().parent

HOOK_ID_TAB = "lords-pick-tab-first"
HOOK_ID_SCROLL = "lords-pick-scroll-search"
HOOK_ID_REASONS = "lords-pick-reasons"
HOOK_ID_PARITY = "lords-pick-nav-snapshot-parity"

_TICKET = "#100"

#: 真机证据帧里找不到的那一行（也是这张票的目标行）。
#: ★它的页签是**降临讨伐**（``scene/lords.py`` 的 ``kind='joss'``）★，不是票面说的「领主战」。
PICK_TARGET_ROW = "无猾机兵"
PICK_TARGET_TAB = "降临讨伐"
PICK_TARGET_M = 5

#: 证据帧（``tools/frames/lords_pick_stuck_on_joss_tab.png``）的逐条读数，**720 空间**
#: （1080 原值 ÷1.5，见模块 docstring 的原文表；行上方的「降临讨伐」小标签是分类 chip，
#: 也照抄进来 —— 它必须既不参与归属、也不被当成页签标签）。
PICK_FRAME_JOSS_BOTTOM: tuple = (
    ("领主战", [135, 388, 90, 35]),
    ("降临讨伐", [481, 389, 117, 32]),            # 1080 [722,584,175,48]
    ("更新列表", [615, 328, 82, 28]),
    ("降临讨伐", [199, 610, 92, 28]),              # 行上方的分类 chip（不参与归属）
    ("伊尔梅塔雷讨伐", [201, 496, 195, 32]), ("通关数1/4", [547, 545, 127, 28]),
    ("降临讨伐", [201, 754, 92, 28]),
    ("伊尔格拉乌讨伐", [202, 641, 192, 28]), ("通关数1/4", [547, 688, 127, 28]),
    ("降临讨伐", [201, 900, 94, 28]),
    ("伊劳德雷斯讨伐", [201, 784, 195, 32]), ("通关数1/4", [547, 832, 127, 28]),
    ("降临讨伐", [199, 1044, 92, 28]),
    ("伊萨巴迪卡讨伐", [199, 925, 196, 35]), ("通关数1/4", [547, 977, 127, 28]),
    ("降临讨伐", [202, 1188, 92, 28]),
    ("伊尔考普斯讨伐", [202, 1072, 193, 32]), ("通关数1/4", [547, 1121, 127, 28]),
)

#: 合成帧的行距 / 行名起点（720 空间）—— 与 ``agent/lords_impl._synthesize_items`` 同口径
#: （真机行距 ≈144px，``tools/frames`` 的读数也是这个间距）。
SYNTH_TOP_Y = 460
SYNTH_PITCH = 144
SYNTH_PROGRESS_DY = 48

#: 上下找的剧本用到的三屏（行名都取自真机证据帧，``无猾机兵`` 只在第 3 屏出现）。
SCREEN_1 = ("伊尔梅塔雷讨伐", "伊尔格拉乌讨伐", "伊劳德雷斯讨伐")
SCREEN_2 = ("伊劳德雷斯讨伐", "伊萨巴迪卡讨伐", "伊尔考普斯讨伐")
SCREEN_3 = ("红嫉机兵", PICK_TARGET_ROW, "苍叹机兵")


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


def _fakes():
    """假 argv / 假 context / 假时钟 / 假睡眠借 ``hooks_100``（同一批真机帧与假 I/O，不抄第二份）。"""
    _paths()
    import hooks_100

    return hooks_100


# ---------------------------------------------------------------------------
# 假件
# ---------------------------------------------------------------------------
def _list_frame(names) -> tuple:
    """一屏列表页（两个页签标签常驻 + ``更新列表`` 判据 + 每行行名与进度）。"""
    items = [
        ("领主战", [135, 388, 90, 35]),
        ("降临讨伐", [481, 389, 117, 33]),
        ("更新列表", [615, 328, 82, 28]),
    ]
    for index, name in enumerate(names):
        y = SYNTH_TOP_Y + index * SYNTH_PITCH
        items.append((name, [202, y, 197, 28]))
        items.append(("通关数1/4", [547, y + SYNTH_PROGRESS_DY, 127, 28]))
    return tuple(items)


class _ScreenFrames:
    """三个剧本屏（名字取自真机证据帧；``无猾机兵`` 只在 :data:`SCREEN_3` 里）。"""

    FIRST = _list_frame(SCREEN_1)
    SECOND = _list_frame(SCREEN_2)
    FOUND = _list_frame(SCREEN_3)


class PickContext:
    """``hooks_100.FakeContext`` + **记下 pipeline_override**（反向手势的几何从这里看）。"""

    def __init__(self) -> None:
        self._fakes = _fakes()
        self.inner = self._fakes.FakeContext()
        self.run_actions: list = []      # [(node, box, override)]
        self.pubclicks: list = []        # [(cx-1, cy-1)] —— 与 clicked_centers 同口径

    # -- 被 agent 调用的两个口子 -------------------------------------------
    def override_next(self, node_name, next_list) -> None:  # noqa: D102
        self.inner.override_next(node_name, list(next_list))

    def run_action(self, action_name, box=None, **kwargs) -> bool:  # noqa: D102
        override = kwargs.get("pipeline_override")
        self.run_actions.append((action_name, box, override))
        if action_name == "PubClick" and box is not None:
            self.pubclicks.append((box[0], box[1]))
        return self.inner.run_action(action_name, box, **kwargs)

    # -- 断言辅助 -----------------------------------------------------------
    @property
    def overrides(self) -> list:
        return list(self.inner.overrides)

    def clicked_centers(self) -> list:
        """把 ``PubClick`` 的 ``(cx-1, cy-1, 2, 2)`` 还原成点击中心。"""
        return [(x + 1, y + 1) for x, y in self.pubclicks]

    def gestures(self) -> list:
        """执行过的手势（节点 + 覆盖参数；``PubClick`` 不算手势）。"""
        return [(node, override) for node, _box, override in self.run_actions if node != "PubClick"]

    def stop_overrides(self) -> list:
        stop = _impl().STOP_NODE
        return [item for item in self.overrides if list(item[1]) == [stop]]


class _Patched:
    """临时替换对象属性（退出必定恢复）。"""

    def __init__(self, owner, name: str, value) -> None:
        self.owner = owner
        self.name = name
        self.value = value
        self.saved = None

    def __enter__(self):
        self.saved = getattr(self.owner, self.name)
        setattr(self.owner, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.owner, self.name, self.saved)
        return False


# ---------------------------------------------------------------------------
# 跑一段 pick 的公共件
# ---------------------------------------------------------------------------
def _ready_session(impl, nav, task, row=PICK_TARGET_ROW, *, n=2, m=PICK_TARGET_M, now=0.0):
    """建一个**停在 pick 阶段**的会话：有目标、扫描已结束（``page_pending`` 为假）。"""
    session = impl._session(task)
    logic = impl._logic()
    session.targets = [logic.Target(row, None, n, m)]
    state = impl._nav_state(session)
    state.complete_scan(session.round_index, now)
    return session, state


def _pick(impl, ctx, task: int):
    """跑一次 ``mode=pick``（假 OCR 帧由 ``hooks_100.FakeOcr`` 的队列依次给出）。"""
    arg = _fakes().FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget")
    return impl.LordsProgressRecognition().analyze(ctx, arg)


def _read(impl, ctx, task: int):
    """跑一次 ``mode=read``（判「点不出去」死线用）。"""
    arg = _fakes().FakeArgv(reco_param={"mode": "read"}, task_id=task, node_name="LordsReadProgress")
    return impl.LordsProgressRecognition().analyze(ctx, arg)


def _detail(res) -> dict:
    return dict(getattr(res, "detail", None) or {})


def _box_list(res):
    return None if res.box is None else list(res.box)


def _rows(frame) -> tuple:
    """一帧 OCR 项 → 行读数（借真源的几何分组；快照那边拿同一批**已分组**的读数）。"""
    logic = _impl()._logic()
    if logic is None:
        return ()
    rows, _orphans = logic.group_progress_rows(frame)
    return tuple(rows)


# ---------------------------------------------------------------------------
# 1. 页签先行（点一次页签，不记「点目标」，不消耗死线）
# ---------------------------------------------------------------------------
def _tab_first_failures(impl=None, nav=None) -> list:
    """★pick 前先对页签★：目标 joss、当前 lord ⇒ 先点页签；页签点击不消耗「点不出去」死线。

    ``impl`` / ``nav`` 可注入（破坏实验用：把 ``switch_decision`` 换成恒 ``ok``、
    或把 ``_pick_locate`` 整段摘掉）。
    """
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []
    task = 12101
    action = impl.LordsUnlockAction()

    with fakes.FakeOcr(frames=[fakes.LIST_FRAME, fakes.TAB_FRAME_JOSS, fakes.LIST_FRAME]), \
            fakes.FakeClock(1000.0) as clock, fakes.FakeSleeper():
        ctx = PickContext()
        session, state = _ready_session(impl, nav, task, now=clock.now)
        # 死线基准故意拨到「离 20s 只差 1s」：页签点击若不刷新它，下一步就会被误判「点不出去」
        session.last_click_at = clock.now - (impl.STUCK_SEC - 1.0)
        res = _pick(impl, ctx, task)
        detail = _detail(res)
        want = nav.label_box(fakes.LIST_FRAME, nav.TAB_ANCHORS[PICK_TARGET_TAB])
        if want is None:
            msgs.append("真机帧里读不到「降临讨伐」页签的标签框 —— 本挂点的前提没了")
            return msgs
        if detail.get("what") != impl.WHAT_TAB:
            msgs.append(
                f"目标页签≠当前页签时 pick 应先点页签（what=tab），实际 what={detail.get('what')!r}"
                f"（locate={detail.get('locate')!r}）—— 修前就是这里直接去点行、点不到就干等死线"
            )
        if detail.get("locate") != nav.PICK_ACTION_TAB:
            msgs.append(f"locate 应为 {nav.PICK_ACTION_TAB!r}，实际 {detail.get('locate')!r}")
        if _box_list(res) != list(want):
            msgs.append(f"页签点击框应为当帧标签框 {list(want)}，实际 {_box_list(res)!r}")
        if detail.get("tab") != PICK_TARGET_TAB:
            msgs.append(f"目标页签应为 {PICK_TARGET_TAB!r}，实际 {detail.get('tab')!r}")

        # 动作：点**标签框中心**；不记「点了一次目标」；刷新死线基准
        before_deadline = session.last_click_at
        if not action.run(ctx, fakes.FakeArgv(task_id=task, box=res.box)):
            msgs.append("pick 阶段的页签点击动作返回 False（页签根本没点下去）")
        centers = ctx.clicked_centers()
        want_center = (want[0] + want[2] / 2.0, want[1] + want[3] / 2.0)
        if not centers:
            msgs.append("页签没有产生任何点击")
        else:
            cx, cy = centers[-1]
            if abs(cx - want_center[0]) > 1 or abs(cy - want_center[1]) > 1:
                msgs.append(f"点页签的中心 {cx,cy} 不是标签框中心 {want_center}")
        if session.attempts_since_read != 0:
            msgs.append(
                f"页签点击被记成了「一次目标点击」（attempts_since_read={session.attempts_since_read}）"
                f"—— 会让扫完一轮后的首读误判「本轮结束」→ played==0 触发防死循环收工"
            )
        if session.last_click_at <= before_deadline:
            msgs.append(
                f"页签点击没有刷新「点不出去」死线基准（{before_deadline} → {session.last_click_at}）"
                f"—— 导航不许消耗死线时间"
            )
        if ctx.gestures():
            msgs.append(f"页签还没确认就先滚了列表：{ctx.gestures()!r}")

        # ② 页签确认之后：不再点页签，而是直接点目标行
        res = _pick(impl, ctx, task)
        detail = _detail(res)
        if detail.get("what") != impl.WHAT_ROW:
            msgs.append(
                f"页签确认后 pick 应直接点目标行（what=row），实际 what={detail.get('what')!r}"
                f"（locate={detail.get('locate')!r}）"
            )
        elif detail.get("row") != PICK_TARGET_ROW:
            msgs.append(f"点到的行应为 {PICK_TARGET_ROW!r}，实际 {detail.get('row')!r}")
        if len(ctx.clicked_centers()) != 1:
            msgs.append(f"一帧只许点一次：本段共点了 {ctx.clicked_centers()!r}")

        # ③ 页签**不许重试**（#19）：点过 1 次仍未确认 ⇒ 这一圈什么都不做
        res = _pick(impl, ctx, task)
        detail = _detail(res)
        if _box_list(res) is not None:
            msgs.append(
                f"页签点过 1 次仍未确认，却又要再点一次（box={_box_list(res)!r}）—— #19 的竞速死循环"
            )
        if detail.get("locate") != nav.PICK_ACTION_WAIT:
            msgs.append(f"未确认期间 locate 应为 {nav.PICK_ACTION_WAIT!r}，实际 {detail.get('locate')!r}")
        if getattr(state, "switch_attempts", -1) != nav.TAB_SWITCH_MAX_ATTEMPTS:
            msgs.append(
                f"页签尝试次数应为 {nav.TAB_SWITCH_MAX_ATTEMPTS}，"
                f"实际 {getattr(state, 'switch_attempts', '?')}"
            )

    # ④ 行为证据：**页签点击过的那一趟**在 1s 后不会按「点不出去」收工（死线基准被刷新了）
    task1b = 12103
    with fakes.FakeOcr(frames=[fakes.LIST_FRAME, fakes.LIST_FRAME]), \
            fakes.FakeClock(1500.0) as clock1b, fakes.FakeSleeper():
        ctx = PickContext()
        session, _state = _ready_session(impl, nav, task1b, now=clock1b.now)
        session.last_click_at = clock1b.now - (impl.STUCK_SEC - 1.0)
        res = _pick(impl, ctx, task1b)
        action.run(ctx, fakes.FakeArgv(task_id=task1b, box=res.box))
        clock1b.advance(1.0)
        read = _detail(_read(impl, ctx, task1b))
        if read.get("stop"):
            msgs.append(
                f"页签点击后 1s 就被判「点不出去」收工（{read.get('reason')!r}）—— "
                f"页签是导航，不许消耗死线时间"
            )

    # ⑤ 反证：**没有**这次刷新时同一时刻真的会收工（证明上面那条不是空断言）
    task2 = 12102
    with fakes.FakeOcr(frame=fakes.LIST_FRAME), fakes.FakeClock(2000.0) as clock2, fakes.FakeSleeper():
        ctx2 = PickContext()
        session2, _state2 = _ready_session(impl, nav, task2, now=clock2.now)
        session2.last_click_at = clock2.now - (impl.STUCK_SEC + 1.0)
        read = _detail(_read(impl, ctx2, task2))
        if not read.get("stop") or "点不出去" not in str(read.get("reason")):
            msgs.append(
                "反证失败：死线基准已经过期、又没有任何导航刷新，mode=read 却没按「点不出去」收工"
                f"（stop={read.get('stop')!r} reason={read.get('reason')!r}）—— 那第一条断言就是空的"
            )
    impl.reset_sessions()
    return msgs


def probe_lords_pick_tab_first() -> bool:
    """#100-3：pick 前先对页签（点一次标签框中心；不记点目标、不消耗死线；确认后不再点）。"""
    return _tab_first_failures() == []


# ---------------------------------------------------------------------------
# 2. 上下找（先下后上；2 次滚动就要找到；两向都到底才判找不到）
# ---------------------------------------------------------------------------
def _scroll_search_failures(impl=None, nav=None) -> list:
    """★先下后上★：目标不在当帧 ⇒ 滚（不是直接放弃）；向下到底 ⇒ 反向向上找。

    ``nav`` 可注入（破坏实验：向下到底直接判失败 / 滚动也消耗死线）。
    """
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    frames = _ScreenFrames
    msgs: list = []
    action = impl.LordsUnlockAction()
    plan = nav.SCROLL_PLAN
    settle = float(plan.settle_ms) / 1000.0

    def run_case(task, queue, *, steps: int):
        """每圈 pick → 有 pending 步骤就执行；返回 (逐圈 detail, 逐圈记账快照, ctx, session, sleeper)。"""
        out, snaps = [], []
        with fakes.FakeOcr(frames=queue), fakes.FakeClock(3000.0) as clock, fakes.FakeSleeper() as sleeper:
            ctx = PickContext()
            session, _state = _ready_session(impl, nav, task, now=clock.now)
            for _ in range(steps):
                res = _pick(impl, ctx, task)
                detail = _detail(res)
                out.append(detail)
                if detail.get("stop"):
                    break
                if session.pending is not None:
                    action.run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
                    snaps.append(
                        {
                            "what": detail.get("what"),
                            "attempts": session.attempts_since_read,
                            "deadline": session.last_click_at,
                            "now": clock.now,
                        }
                    )
                    clock.advance(float(plan.min_interval_sec) + 0.5)
            return out, snaps, ctx, session, sleeper

    # (a) 「行在第 3 屏」⇒ 滚了 2 次就找到，不是当场放弃
    got, snaps, ctx, session, sleeper = run_case(
        12111, [frames.FIRST, frames.SECOND, frames.FOUND], steps=3
    )
    dirs = [item.get("what") for item in got]
    if dirs[:2] != [impl.WHAT_SCROLL_DOWN, impl.WHAT_SCROLL_DOWN]:
        msgs.append(
            f"「行在第 3 屏」应连滚 2 次向下（what=scroll_down ×2），实际 {dirs!r} —— "
            f"修前是直接放弃（no_hit → 等死线）"
        )
    if len(got) < 3 or got[2].get("what") != impl.WHAT_ROW:
        msgs.append(f"滚到第 3 屏后应点目标行（what=row），实际 {dirs!r}")
    elif got[2].get("row") != PICK_TARGET_ROW:
        msgs.append(f"找到后应点 {PICK_TARGET_ROW!r}，实际 {got[2].get('row')!r}")
    gestures = ctx.gestures()
    if len(gestures) != 2:
        msgs.append(f"「行在第 3 屏」应滚 2 次，实际 {len(gestures)} 次：{gestures!r}")
    for node, override in gestures:
        if node != impl.SCROLL_NODE:
            msgs.append(f"手势节点应为 {impl.SCROLL_NODE!r}，实际 {node!r}")
            continue
        param = ((override or {}).get(impl.SCROLL_NODE) or {}).get("action", {}).get("param", {})
        if list(param.get("begin") or []) != list(plan.begin) or list(param.get("end") or []) != list(plan.end):
            msgs.append(f"向下滚的手势应为 {plan.begin}→{plan.end}，实际 {param!r}")
    if settle not in sleeper.calls:
        msgs.append(
            f"滚动之后没有补足 {plan.settle_ms}ms 的稳定等待（sleep 调用 {sleeper.calls!r}）—— "
            f"LordsPickTarget 的 post_delay 只有 800ms < settle_ms（#42 惯性会把行点飞）"
        )
    for snap in snaps:
        if snap["what"] not in (impl.WHAT_SCROLL_DOWN, impl.WHAT_SCROLL_UP):
            continue
        if snap["attempts"] != 0:
            msgs.append(
                f"找行滚动被记成了「点目标」（attempts_since_read={snap['attempts']}）—— "
                f"导航不是打目标"
            )
        if snap["deadline"] != snap["now"]:
            msgs.append(
                f"找行滚动没有刷新「点不出去」死线（{snap['deadline']} != {snap['now']}）—— "
                f"导航在推进，不该算作点不动"
            )

    # (b) 向下到底 ⇒ 向上找（同一个手势反向，几何仍只有 SCROLL_PLAN 一份）
    got, snaps, ctx, session, sleeper = run_case(
        12112, [frames.FIRST, frames.FIRST, frames.FIRST, frames.FOUND], steps=4
    )
    dirs = [item.get("what") for item in got]
    if impl.WHAT_SCROLL_UP not in dirs:
        msgs.append(
            f"向下到底后必须**向上**找（what=scroll_up），实际 {dirs!r} —— "
            f"现场证据帧就停在列表中部/底部，目标在更靠上的位置"
        )
    elif dirs.index(impl.WHAT_SCROLL_UP) < 2:
        msgs.append(f"向上找必须排在「向下到底」之后（先下后上），实际 {dirs!r}")
    if not any("改向上找" in str(item.get("reason") or "") for item in got):
        msgs.append(f"换方向的理由没说清「改向上找」：{[item.get('reason') for item in got]!r}")
    up_params = []
    for node, override in ctx.gestures():
        param = ((override or {}).get(node) or {}).get("action", {}).get("param", {})
        if list(param.get("end") or []) == list(plan.up_end):
            up_params.append(param)
    if not up_params:
        msgs.append(
            f"没有一次手势是**反向**的（应为 {plan.up_begin}→{plan.up_end}）—— "
            f"向上找必须复用同一个手势的端点交换，不写第二份坐标"
        )
    elif list(up_params[0].get("begin") or []) != list(plan.up_begin):
        msgs.append(f"反向手势的起点应为 {plan.up_begin}，实际 {up_params[0].get('begin')!r}")
    if got and got[-1].get("what") != impl.WHAT_ROW:
        msgs.append(f"向上找找到后应点行（what=row），实际 {dirs!r}")

    # (c) 两向都到底 ⇒ 带原因收工
    got, snaps, ctx, session, _sleeper = run_case(12113, [frames.FIRST] * 8, steps=8)
    last = got[-1] if got else {}
    if not last.get("stop"):
        msgs.append(f"两向都到底却还没收工：{[item.get('what') for item in got]!r}")
    elif last.get("fail_kind") != nav.PICK_FAIL_NOT_FOUND:
        msgs.append(
            f"两向都到底的 fail_kind 应为 {nav.PICK_FAIL_NOT_FOUND!r}，实际 {last.get('fail_kind')!r}"
        )
    if not ctx.stop_overrides():
        msgs.append("两向都到底却没有 override_next 到收工出口（会原地空转）")

    # (d) 真机证据帧：页签本身是对的（joss），所以第一下必须是**滚**，不是当场收工
    task = 12114
    with fakes.FakeOcr(frames=[PICK_FRAME_JOSS_BOTTOM, PICK_FRAME_JOSS_BOTTOM]), \
            fakes.FakeClock(4000.0) as clock, fakes.FakeSleeper():
        ctx = PickContext()
        session, _state = _ready_session(impl, nav, task, now=clock.now)
        res = _pick(impl, ctx, task)
        detail = _detail(res)
        if detail.get("confirmed") != PICK_TARGET_TAB:
            msgs.append(
                f"证据帧的页签应确认为 {PICK_TARGET_TAB!r}（5 行全是 joss 成员），"
                f"实际 {detail.get('confirmed')!r} —— 若这里变了，本挂点的剧本要跟着改"
            )
        if detail.get("what") != impl.WHAT_SCROLL_DOWN:
            msgs.append(
                f"证据帧上目标行不在屏上（画面停在 joss 列表中部），第一下必须是向下滚，"
                f"实际 what={detail.get('what')!r}（locate={detail.get('locate')!r}）"
            )
        if detail.get("stop"):
            msgs.append(f"证据帧上第一圈就收工了（{detail.get('reason')!r}）")
    impl.reset_sessions()
    return msgs


def probe_lords_pick_scroll_search() -> bool:
    """#100-3：上下找（先下后上、2 次滚动就找到、反向几何、settle、两向到底才收工）。"""
    return _scroll_search_failures() == []


# ---------------------------------------------------------------------------
# 3. 三种失败原因必须分开
# ---------------------------------------------------------------------------
def _reason_tab(impl, nav, fakes) -> str:
    """剧本 ①：目标在别的页签、页签点了也切不过去 ⇒「目标不在这个页签」。"""
    task = 12121
    action = impl.LordsUnlockAction()
    with fakes.FakeOcr(frames=[fakes.LIST_FRAME] * 8), fakes.FakeClock(5000.0) as clock, fakes.FakeSleeper():
        ctx = PickContext()
        _ready_session(impl, nav, task, now=clock.now)
        for _ in range(8):
            res = _pick(impl, ctx, task)
            detail = _detail(res)
            if detail.get("stop"):
                return str(detail.get("reason") or "")
            if res.box is not None:
                action.run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
            # 页签点了以后画面仍是领主战 ⇒ 每圈都推进过宽限期（真实时间也会这样走）
            clock.advance(nav.TAB_CONFIRM_GRACE_SEC / 2.0 + 0.5)
    return ""


def _reason_not_found(impl, nav, fakes) -> str:
    """剧本 ②：在本页签上下都扫到底也没有这一行 ⇒「滚到底也没找到」。"""
    task = 12122
    action = impl.LordsUnlockAction()
    first = _ScreenFrames.FIRST
    with fakes.FakeOcr(frames=[first] * 10), fakes.FakeClock(6000.0) as clock, fakes.FakeSleeper():
        ctx = PickContext()
        session, _state = _ready_session(impl, nav, task, now=clock.now)
        for _ in range(10):
            res = _pick(impl, ctx, task)
            detail = _detail(res)
            if detail.get("stop"):
                return str(detail.get("reason") or "")
            if session.pending is not None:
                action.run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
                clock.advance(float(nav.SCROLL_PLAN.min_interval_sec) + 0.5)
    return ""


def _click_never_lands(impl):
    """把点击 hook 换成「永远失败」（行在屏上却点不动）。"""
    return _Patched(impl, "_click_hook", lambda *a, **k: False)


def _reason_click_stuck(impl, nav, fakes) -> str:
    """剧本 ③：行在屏上、点击却点不动 ⇒「找到了但点不动」（带行框）。"""
    task = 12123
    action = impl.LordsUnlockAction()
    with fakes.FakeOcr(frames=[fakes.LIST_FRAME] * 3), fakes.FakeClock(7000.0) as clock, fakes.FakeSleeper():
        ctx = PickContext()
        session, _state = _ready_session(
            impl, nav, task, row="艾基尔·嫉妒讨伐", n=1, m=4, now=clock.now
        )
        session.last_click_at = clock.now
        res = _pick(impl, ctx, task)
        if _detail(res).get("what") != impl.WHAT_ROW:
            return ""
        # 点击 hook 永远失败（= 行在屏上却点不动）；动作如实返回 False，不记账
        with _click_never_lands(impl):
            action.run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        clock.advance(impl.STUCK_SEC + 1.0)
        read = _detail(_read(impl, ctx, task))
        return str(read.get("reason") or "") if read.get("stop") else ""


def _reasons_failures(impl=None, nav=None) -> list:
    """★三种失败原因必须分开★：文案各自点名 + 互不含对方的分句 + 各自带量。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    fakes = _fakes()
    msgs: list = []
    marks = (
        (nav.PICK_REASON_TAB, "页签"),
        (nav.PICK_REASON_NOT_FOUND, "滚到底"),
        (nav.PICK_REASON_CLICK, "点不动"),
    )
    if len({mark for mark, _label in marks}) != 3:
        msgs.append(f"三种失败原因的文案不是三段不同的字：{marks!r}")
        return msgs

    got = {
        "tab": _reason_tab(impl, nav, fakes),
        "not_found": _reason_not_found(impl, nav, fakes),
        "click": _reason_click_stuck(impl, nav, fakes),
    }
    impl.reset_sessions()
    by_key = dict(zip(("tab", "not_found", "click"), marks))
    for key in ("tab", "not_found", "click"):
        mark, label = by_key[key]
        if not got[key]:
            msgs.append(f"剧本「{label}」没有收工 —— 这段剧本本身没跑起来（期望 reason 含 {mark!r}）")
        elif mark not in got[key]:
            msgs.append(
                f"剧本「{label}」的收工原因里没有 {mark!r}：{got[key]!r} —— "
                f"三种原因混成一句就是这张票要修的病（症状离病因太远）"
            )
    # 互不含对方的分句：一眼就要能分开
    for left, right in (("tab", "not_found"), ("tab", "click"), ("not_found", "click")):
        if not got[left] or not got[right]:
            continue
        other_mark = by_key[right][0]
        if other_mark in got[left]:
            msgs.append(f"「{left}」的原因里混进了「{right}」的分句 {other_mark!r}：{got[left]!r}")
    # 各自带量
    if not got["tab"] or "页签" not in got["tab"]:
        msgs.append(f"「不在这个页签」的原因没说清是哪个页签：{got['tab']!r}")
    if not got["not_found"] or PICK_TARGET_TAB not in got["not_found"]:
        msgs.append(
            f"「滚到底也没找到」的原因没点明本页签 {PICK_TARGET_TAB!r}：{got['not_found']!r}"
        )
    if not got["not_found"] or "向下滚" not in got["not_found"] or "向上滚" not in got["not_found"]:
        msgs.append(f"「滚到底也没找到」没带两个方向的次数：{got['not_found']!r}")
    if not got["click"] or "行框" not in got["click"]:
        msgs.append(f"「找到了但点不动」没带行框：{got['click']!r}")
    if not got["click"] or "点不出去" not in got["click"]:
        msgs.append(f"「找到了但点不动」没保留「点不出去」这个既有口径：{got['click']!r}")
    return msgs


def probe_lords_pick_reasons() -> bool:
    """#100-3：目标不在这个页签 / 滚到底也没找到 / 找到了但点不动 —— 三段文案各自可辨。"""
    return _reasons_failures() == []


# ---------------------------------------------------------------------------
# 4. 安装态快照 == 真源
# ---------------------------------------------------------------------------
#: 必须逐项相等的常量（= ``scene/lords_nav.PICK_*``）。
PICK_PARITY_FIELDS: tuple = (
    "PICK_ACTION_READY",
    "PICK_ACTION_TAB",
    "PICK_ACTION_SCROLL",
    "PICK_ACTION_WAIT",
    "PICK_ACTION_FAIL",
    "PICK_SCROLL_DOWN",
    "PICK_SCROLL_UP",
    "PICK_PHASE_DOWN",
    "PICK_PHASE_UP",
    "PICK_PHASE_DONE",
    "PICK_FAIL_TAB",
    "PICK_FAIL_NOT_FOUND",
    "PICK_FAIL_CLICK",
    "PICK_FAIL_SCROLL",
    "PICK_REASON_TAB",
    "PICK_REASON_NOT_FOUND",
    "PICK_REASON_CLICK",
    "PICK_REASON_SCROLL",
    "PICK_TAB_WAIT_SEC",
)


def _norm_pick(dec) -> tuple:
    """判决 → 纯数据（真源与快照的 dataclass 都能被同一份归一化吃掉）。"""
    return (dec.action, dec.tab, dec.direction, dec.kind, dec.reason)


def _pick_scenario(navl) -> tuple:
    """一段确定性的归位剧本 → 可比较的观测元组（真源与快照必须逐项相同）。"""
    frames = _ScreenFrames
    out: list = []
    out.append(("begin", navl.PickNav is not None))
    tab_state = navl.NavState()
    tab_state.complete_scan(0, 0.0)
    lord = navl.tab_state(_fakes().LIST_FRAME)
    joss = navl.tab_state(PICK_FRAME_JOSS_BOTTOM)
    out.append(("evidence_lord", lord.confirmed, tuple(lord.kinds)))
    out.append(("evidence_joss", joss.confirmed, tuple(joss.kinds)))

    pick = navl.PickNav()
    out.append(("begin_target", pick.begin_target(PICK_TARGET_ROW, PICK_TARGET_TAB)))
    out.append(("begin_same", pick.begin_target(PICK_TARGET_ROW, PICK_TARGET_TAB)))

    # 页签不对 → tab；点过 1 次仍未确认 → wait；等满宽限 → tab 失败
    box = navl.label_box(_fakes().LIST_FRAME, navl.TAB_ANCHORS[PICK_TARGET_TAB])
    decision = pick.decide(
        _rows(frames.FIRST),
        evidence=lord,
        desired=PICK_TARGET_TAB,
        tab_decision=tab_state.switch_decision(lord, PICK_TARGET_TAB, box, 1.0),
        target_visible=False,
        list_page=True,
        now=1.0,
    )
    out.append(("decide_tab", _norm_pick(decision)))
    decision = pick.decide(
        _rows(frames.FIRST),
        evidence=lord,
        desired=PICK_TARGET_TAB,
        tab_decision=tab_state.switch_decision(lord, PICK_TARGET_TAB, None, 2.0),
        target_visible=False,
        list_page=True,
        now=2.0,
    )
    out.append(("decide_wait", _norm_pick(decision)))
    later = 2.0 + navl.PICK_TAB_WAIT_SEC + 1.0
    decision = pick.decide(
        _rows(frames.FIRST),
        evidence=lord,
        desired=PICK_TARGET_TAB,
        tab_decision=tab_state.switch_decision(lord, PICK_TARGET_TAB, None, later),
        target_visible=False,
        list_page=True,
        now=later,
    )
    out.append(("decide_tab_fail", _norm_pick(decision)))

    # 页签已确认 → 先下后上 → 两向都到底判找不到
    fresh = navl.PickNav()
    fresh.begin_target(PICK_TARGET_ROW, PICK_TARGET_TAB)
    clock = 10.0
    for label, frame in (
        ("down1", frames.FIRST),
        ("down2", frames.FIRST),
        ("up1", frames.FIRST),
        ("up2", frames.FIRST),
        ("fail", frames.FIRST),
    ):
        decision = fresh.decide(
            _rows(frame),
            evidence=joss,
            desired=PICK_TARGET_TAB,
            tab_decision=tab_state.switch_decision(joss, PICK_TARGET_TAB, None, clock),
            target_visible=False,
            list_page=True,
            now=clock,
        )
        out.append((label, _norm_pick(decision), fresh.phase, fresh.scrolls_down, fresh.scrolls_up))
        if decision.action == navl.PICK_ACTION_SCROLL:
            fresh.note_scroll(decision.direction, clock)
            clock += 3.0

    # 找到后 ready（交给 pick_click）
    found = navl.PickNav()
    found.begin_target(PICK_TARGET_ROW, PICK_TARGET_TAB)
    out.append(
        (
            "ready",
            _norm_pick(
                found.decide(
                    _rows(frames.FOUND),
                    evidence=joss,
                    desired=PICK_TARGET_TAB,
                    tab_decision=tab_state.switch_decision(joss, PICK_TARGET_TAB, None, 50.0),
                    target_visible=True,
                    list_page=True,
                    now=50.0,
                )
            ),
        )
    )
    out.append(("up_geometry", tuple(navl.SCROLL_PLAN.up_begin), tuple(navl.SCROLL_PLAN.up_end)))
    out.append(
        (
            "plan_geometry_ok",
            bool(navl.SCROLL_PLAN.geometry_ok),
            bool(navl.SCROLL_PLAN.in_list_body(navl.SCROLL_PLAN.up_begin)),
            bool(navl.SCROLL_PLAN.in_list_body(navl.SCROLL_PLAN.up_end)),
        )
    )
    return tuple(out)


def _pick_parity_failures(impl=None, nav=None) -> list:
    """★安装态单源★：``_PickNavSnapshot`` == ``scene/lords_nav.PickNav``（常量 + 行为）。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    snap = getattr(impl, "_NavSnapshotLogic", None)
    if snap is None:
        return ["agent/lords_impl 缺 _NavSnapshotLogic —— 安装态没有导航真源替身"]
    msgs: list = []
    if getattr(snap, "PickNav", None) is None:
        return msgs + [
            "安装态快照缺 PickNav —— 装好的产品在「目标行不在屏上」时又会退化成干等死线"
        ]

    for name in PICK_PARITY_FIELDS:
        want, got = getattr(nav, name, None), getattr(snap, name, None)
        if got != want:
            msgs.append(f"导航快照 {name} = {got!r} != 真源 {want!r}")
    plan = nav.SCROLL_PLAN
    snap_plan = getattr(snap, "SCROLL_PLAN", None)
    for field in ("up_begin", "up_end"):
        want = getattr(plan, field, None)
        got = getattr(snap_plan, field, None)
        if tuple(got or ()) != tuple(want or ()):
            msgs.append(f"导航快照 SCROLL_PLAN.{field} = {got!r} != 真源 {want!r}")

    mine = _pick_scenario(nav)
    theirs = _pick_scenario(snap)
    for a, b in zip(mine, theirs):
        if a != b:
            msgs.append(f"归位行为表不一致：真源 {a!r} / 快照 {b!r}")
    if len(mine) != len(theirs):
        msgs.append(f"归位行为表长度不一致：{len(mine)} vs {len(theirs)}")
    labels = tuple(item[0] for item in mine)
    for must in ("decide_tab", "decide_wait", "decide_tab_fail", "down1", "up1", "fail", "ready"):
        if must not in labels:
            msgs.append(f"归位行为表没走到 {must!r}（剧本被删空 = 守卫瞎了）")
    return msgs


def probe_lords_pick_nav_snapshot_parity() -> bool:
    """#100-3：安装态归位快照与 ``scene/lords_nav.PickNav`` 逐项相等（常量 + 行为）。"""
    return _pick_parity_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_TAB,
        _TICKET,
        "★pick 前先对页签★目标 tab 与当前 tab 不一致 ⇒ 先点当帧标签框中心、切后以可见行族复核；"
        "页签点击**不记**「点了一次目标」、**不消耗**「点不出去」死线（有反证：不刷新时同一时刻会收工）；"
        "确认后不再点、未确认只许 1 次（#19）",
        probe_lords_pick_tab_first,
    ),
    (
        HOOK_ID_SCROLL,
        _TICKET,
        "★pick 前先上下找★目标行不在当帧 ⇒ 先向下滚（上限 max_scrolls_per_page）、向下到底再反向向上；"
        "「行在第 3 屏」必须滚 2 次就找到（不是当场放弃）；反向手势复用同一份几何（up_begin/up_end）；"
        "滚动补足 settle_ms、不消耗死线；两向都到底 ⇒ 带原因收工",
        probe_lords_pick_scroll_search,
    ),
    (
        HOOK_ID_REASONS,
        _TICKET,
        "★三种失败原因分开★目标不在这个页签 / 滚到底也没找到 / 找到了但点不动 —— 三段剧本各自收工，"
        "reason 分别含对应子串且互不含对方的分句；页签原因带页签名、滚到底原因带两向次数、"
        "点不动原因带行框（并保留「点不出去」的既有口径）",
        probe_lords_pick_reasons,
    ),
    (
        HOOK_ID_PARITY,
        _TICKET,
        "★安装态单源★agent/lords_impl._PickNavSnapshot == scene/lords_nav.PickNav："
        "PICK_* 常量 / PICK_TAB_WAIT_SEC / SCROLL_PLAN.up_begin·up_end 逐项相等，"
        "且同一段归位剧本（页签 / 等待 / 失败 / 先下后上 / 找到）判决与次数逐项相同",
        probe_lords_pick_nav_snapshot_parity,
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


def _no_up_search_class(nav):
    """造一个「向下到底就直接判找不到」的坏类（= 去掉向上找这一档）。"""

    class _NoUpSearch(nav.PickNav):
        def decide(self, rows, **kwargs):  # noqa: D102
            dec = super().decide(rows, **kwargs)
            if dec.action == nav.PICK_ACTION_SCROLL and dec.direction == nav.PICK_SCROLL_UP:
                self.phase = nav.PICK_PHASE_UP
                return self._fail(nav.PICK_FAIL_NOT_FOUND, "向下到底，不向上找（破坏实验）")
            return dec

    return _NoUpSearch


def _prove_red_checks() -> list:
    """五条破坏实验（全部在内存里做，退出必定还原实现）。"""
    impl = _impl()
    nav = _lords_nav()
    checks: list = []

    # ① pick 不找只点（把归位整段摘掉 = 修前的老行为）
    real_locate = impl.LordsProgressRecognition._pick_locate
    try:
        impl.LordsProgressRecognition._pick_locate = lambda self, *a, **k: None
        _record(
            "① pick 不找只点（_pick_locate 被摘掉 = 修前的行为）",
            _tab_first_failures() + _scroll_search_failures() + _reasons_failures(),
            checks,
        )
    finally:
        impl.LordsProgressRecognition._pick_locate = real_locate
        impl.reset_sessions()

    # ② 页签对齐失效（switch_decision 恒 ok：就当页签已经对了）
    real_decision = nav.NavState.switch_decision

    def _always_ok(self, evidence, desired, box, now):
        return nav.TabDecision(nav.ACTION_OK, desired, None, "破坏实验：假装已经在本页签上")

    try:
        nav.NavState.switch_decision = _always_ok
        _record("② 页签对齐失效（switch_decision 恒 ok）", _tab_first_failures(), checks)
    finally:
        nav.NavState.switch_decision = real_decision
        impl.reset_sessions()

    # ③ 去掉向上找（向下到底就直接判找不到）
    real_pick = nav.PickNav
    try:
        nav.PickNav = _no_up_search_class(nav)
        _record("③ 去掉向上找（向下到底 → 直接判找不到）", _scroll_search_failures(), checks)
    finally:
        nav.PickNav = real_pick
        impl.reset_sessions()

    # ④ 滚动也消耗死线（滚完把 last_click_at 还原）
    real_search = impl.LordsUnlockAction._scroll_search

    def _broken_scroll_eats_deadline(this, context, session, what):
        saved = session.last_click_at
        ok = real_search(this, context, session, what)
        session.last_click_at = saved          # ← 破坏实验：把「导航不算点不动」撤掉
        return ok

    try:
        impl.LordsUnlockAction._scroll_search = _broken_scroll_eats_deadline
        _record("④ 滚动也消耗死线（滚完还原 last_click_at）", _scroll_search_failures(), checks)
    finally:
        impl.LordsUnlockAction._scroll_search = real_search
        impl.reset_sessions()

    # ⑤ 三原因合并成一句（文案退化成同一个词）
    real_reasons = (nav.PICK_REASON_TAB, nav.PICK_REASON_NOT_FOUND, nav.PICK_REASON_CLICK)
    try:
        nav.PICK_REASON_TAB = "失败"
        nav.PICK_REASON_NOT_FOUND = "失败"
        nav.PICK_REASON_CLICK = "失败"
        _record("⑤ 三原因合并成一句（PICK_REASON_* 全改成「失败」）", _reasons_failures(), checks)
    finally:
        nav.PICK_REASON_TAB, nav.PICK_REASON_NOT_FOUND, nav.PICK_REASON_CLICK = real_reasons
        impl.reset_sessions()
    return checks


def prove_red() -> bool:
    """真实绿；五条破坏实验各自如愿变红。"""
    print("hooks_121 prove-red：逐一破坏实现，要求四个挂点各自变红")
    green = (
        probe_lords_pick_tab_first()
        and probe_lords_pick_scroll_search()
        and probe_lords_pick_reasons()
        and probe_lords_pick_nav_snapshot_parity()
    )
    print(
        f"  [{'PASS' if green else 'FAIL'}] 真实实现：页签先行 / 上下找 / 三原因可分 / "
        f"安装态归位快照一致（绿）"
    )
    if not green:
        for msg in (
            _tab_first_failures()
            + _scroll_search_failures()
            + _reasons_failures()
            + _pick_parity_failures()
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
    raise SystemExit(0 if prove_red() else 1)
