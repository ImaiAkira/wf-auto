# -*- coding: utf-8 -*-
"""#124：把「切 SET」改成「切 Party」—— 横向滑动 + 三重校验的离线守卫。

真机交互模型（``394eb66``，A，720x1280；受控实验见 ``tools/probe_team_carousel.py``）
----------------------------------------------------------------------------------------
::

    左滑（手指右→左，600→200）= Party +1
    右滑（手指左→右，200→600）= Party −1
    SET **不变** —— 那一行是队伍轮播，不是 SET 页签
    战力随 Party 变 ⇒ 可作独立证据

★2026-10-18 追加真机标定（A；结论已在 #124 评论，**不要重测**）★
----------------------------------------------------------------
- Party **1..10，环形轮播**：左滑 10→1、右滑 1→10，**没有滑不动的边界**；两方向各走完整一圈
  都回到原点。边界画面无异常：SET 全程 1、战力 10 队各不相同（10452…11588）、两侧箭头在、
  底部 10 个圆点。
- 1..10 内最大 ``|Δ|=9 ≤ TEAM_PARTY_SWIPE_MAX(12)`` ⇒ **环形不改变算法**（不按环取模）。
- 真机缺陷（本票修）：``switch_party(11)`` 从 Party 10 起**滑了 11 次**才失败，还把轮播**留在
  Party 1**（副作用）；且 ``TEAM_PARTY_COUNT=6`` 会让 **7..10 被两个动作直接拒**。
- 新铁律：**先判「目标是否存在（1..TEAM_PARTY_COUNT）」，再判「要滑几步（|Δ| 上限）」**，
  两条都在任何 read / swipe 之前；**绝不默认夹紧**（越界 = 一步不滑直接失败），要夹紧必须是
  调用方显式 ``clamp=True`` 且打印夹紧结果；队名字母表长度必须 == ``TEAM_PARTY_COUNT``。

四个挂点 + 两个接线挂点 + 三个标定收尾挂点
------------------------------------------
1. ``party-swipe-direction``：**左滑 = +1、右滑 = −1**（方向不能反）；滑动行 y 必须来自
   ``read_team`` 的 SET 框中心（**不许写死**）；正常换队**不许点屏幕**（真机证据：只要滑）。
2. ``party-triple-check``：**SET 不变 ∧ Party == target ∧ 战力变化** 三者同时成立才算成功；
   三个剧本各缺一票都要 False 且日志带量（纯函数 + 全流程两条腿分开跑）。
3. ``party-swipe-bounded``：``|Δ| > 12`` ⇒ **一步不滑**、直接带量失败；``|Δ| == 12`` 允许
   （有界不是「一律拒动」）。绝不无限滑。
4. ``party-switch-seams``：已在目标 ⇒ 幂等成功且不滑；没有 ``swipe_hook`` ⇒ 带原因失败（不盲动）；
   ``read_hook`` 可独立注入；第 1 次尝试一步没动且给了 ``tap_hook`` 时**只轻点一次** SET 条中心。
5. ``party-constants-source-of-truth``（★接线★）：6 个 ``TEAM_PARTY_*`` 常量已搬进真源
   ``scene/team.py``；agent 侧只剩**逐字冻结快照**（``_TEAM_PARTY_*_SNAPSHOT``）。守卫逐项比对
   「真源 == 快照 == 运行时」且「真源 == 真机 394eb66 的标定值」—— 任何一侧改动都红。
6. ``party-action-wiring``（★接线★）：``TeamSwitchBattleAction`` 在 A 类页 + 目标 Party 时
   **必须调 ``switch_party``**（注入假 IO 计数），且**不许退回「点 SET 条」**（零点击 + 真滑到目标）；
   不在 A 类页 / 读不到编队 ⇒ **零调用**（旧的「拒动」保留的一半）；三重校验不过 ⇒ 不打印成功。
7. ``party-target-bounds``（★真机后续①+②★）：越界目标（0 / 11 / 99）⇒ **零滑动、零读数**、
   返回 False、日志含「一步没滑」；**默认绝不夹紧**（``switch_party(11)`` 不许返回 True，也不许把
   轮播留在别处）；``clamp=True`` 时才夹紧、**打印夹紧到几**、并能真的切过去。
8. ``party-alphabet-count``（★真机后续③★）：``TEAM_PARTY_COUNT == 10`` 且
   ``len(TEAM_PARTY_LETTERS) == TEAM_PARTY_COUNT``（真源 + agent 运行时两侧），
   ``party_ordinal`` A..J == 1..10（``Party I/J`` 不许退化成「读不到 Party」）。
9. ``party-count-actions``（★真机后续③★）：``team_switch`` / ``team_switch_battle`` 的
   1..10 **全部放行**（不让 7..10 被拒），**显式** ``party=0`` / ``11`` 越界拒动且零 IO，
   不给 ``party`` 才是「只切 SET」（旧语义）。

破坏实验（``python tools\\contract_hooks\\hooks_124.py --run-prove-red``，全部在内存里做）
------------------------------------------------------------------------------
① 滑动方向写反（``party_swipe_geometry`` 取反）→ 挂点 1 红；
② 去掉三重校验（``verify_party_switch`` 恒 ``(True, [])``）→ 挂点 2 红；
③ 去掉有界（``party_swipe_gap_ok`` 恒 True，上限常量仍 12）→ 挂点 3 红；
④ 把滑动行 y 写死成 465（不取 SET 框）→ 挂点 1 红；
⑤ **常量改值**（agent 快照改一次 / scene 真源改一次）→ 挂点 5 红；
⑥ **动作退回「点 SET 条」**（``switch_party`` 换成点圆点）→ 挂点 6 红；
⑦ **非 A 类页也调 ``switch_party``**（页判据恒真）→ 挂点 6 红；
⑧ **切完不校验**（``switch_party`` 恒 True）→ 挂点 6 红（战力没变却打印成功）；
⑨ **越界检查放到滑动之后**（先滑 |Δ| 次再判目标）→ 挂点 7 红（老缺陷形态）；
⑩ **默认夹紧**（不显式要求也把 11 夹成 10）→ 挂点 7 红（静默错队）；
⑪ **字母表退回 8 个**（Party I/J 读不出）→ 挂点 8 红；
⑫ **``TEAM_PARTY_COUNT`` 退回 6**（7..10 又被拒）→ 挂点 8/9 红。

★诚实边界★
* 本守卫**不碰设备**：假设备 ``FakeScreen`` 的读数是「左滑 +1 / 右滑 −1」这一条真机口径的
  实现，它证的是「算法按这条口径做对判决」，不是「今天真机还是这样」。``FakeBattlePage``
  同理：它证的是「动作层按页判据选路径、按 ``switch_party`` 的返回值判成功」，不是「真机点对了」。
* 真机入口两个：探针 ``tools/probe_team_carousel.py --target N``；动作
  ``custom_action="team_switch_battle"``（参数 ``party``）。
* 上下界与是否循环**已由真机回答**（2026-10-18：1..10 环形，见上）—— 本文件不再把它们当未知项。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
AGENT_DIR = REPO_ROOT / "agent"

HOOK_ID_DIRECTION = "party-swipe-direction"
HOOK_ID_TRIPLE = "party-triple-check"
HOOK_ID_BOUND = "party-swipe-bounded"
HOOK_ID_SEAMS = "party-switch-seams"
HOOK_ID_CONSTANTS = "party-constants-source-of-truth"
HOOK_ID_WIRING = "party-action-wiring"
HOOK_ID_TARGET_BOUNDS = "party-target-bounds"
HOOK_ID_ALPHABET = "party-alphabet-count"
HOOK_ID_COUNT_ACTIONS = "party-count-actions"

_TICKET = "#124"

#: 真机 394eb66 的滑动几何（720 空间；与票面逐项一致）。
SWIPE_LEFT = (600, 200)
SWIPE_RIGHT = (200, 600)
#: 票面建议的 ``|Δ|`` 上限。
MAX_DELTA = 12
#: 真机 10 队（2026-10-18，A 实测 1..10 环形轮播）—— 队数与字母表长度都按它钉。
PARTY_COUNT = 10
#: 真机队名字母表（字母序号 == 队号）：A..J 共 10 个，长度必须 == :data:`PARTY_COUNT`。
PARTY_LETTERS = "ABCDEFGHIJ"
#: 假的 ``SET 1`` 框：y 中心 = 458 + 20/2 = 468。守卫要求滑动 y **从框里取**，不是 465。
SET_BOX = [90, 458, 60, 20]
SET_ROW_Y = 468
#: 假 SET 条的「轻点」中心（x = 90 + 60/2）。
SET_ROW_X = 120

#: 归本票管的 6 个常量（真源 ``scene/team.py``；agent 侧 ``_<名字>_SNAPSHOT`` 逐字冻结）。
PARTY_CONSTANTS = (
    "TEAM_PARTY_SWIPE_LEFT",
    "TEAM_PARTY_SWIPE_RIGHT",
    "TEAM_PARTY_SWIPE_MS",
    "TEAM_PARTY_STEP_SLEEP",
    "TEAM_PARTY_SWIPE_MAX",
    "TEAM_PARTY_RETRIES",
)
#: 真机 394eb66 的标定值 —— **改它 = 换了一次真机标定**，必须附新证据（截图/日志）。
PARTY_CONSTANT_VALUES = {
    "TEAM_PARTY_SWIPE_LEFT": (600, 200),
    "TEAM_PARTY_SWIPE_RIGHT": (200, 600),
    "TEAM_PARTY_SWIPE_MS": 450,
    "TEAM_PARTY_STEP_SLEEP": 1.6,
    "TEAM_PARTY_SWIPE_MAX": 12,
    "TEAM_PARTY_RETRIES": 1,
}


# ---------------------------------------------------------------------------
# 惰性导入（挂点模块 import 期必须保持轻：只 import 本文件不该把 maa 拉起来）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR), str(AGENT_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)


def _impl():
    _paths()
    import team_impl  # noqa: PLC0415

    return team_impl


def _scene():
    """``scene.team``（常量真源）。"""
    _paths()
    from scene import team as sc  # noqa: PLC0415

    return sc


# ---------------------------------------------------------------------------
# 假设备：读数由手势驱动（左滑 +1 / 右滑 −1 = 真机口径）
# ---------------------------------------------------------------------------
class FakeScreen:
    """一台只存在于内存里的 A 类战前编队页。

    ``read_team`` 返回 ``((SET 号, 框), Party, 战力)``；``swipe`` 按**真机口径**驱动 Party：

    * ``x_from > x_to``（左滑，600→200）⇒ Party +1；
    * ``x_from < x_to``（右滑，200→600）⇒ Party −1。

    ★方向守卫就靠这条★：实现要是把方向写反，FakeScreen 会照真机口径把 Party 滑向反面，
    于是「连滑 |Δ| 次」达不到目标，测试当场红 —— 不是靠看日志里写了「左滑」两个字。
    """

    def __init__(
        self,
        party: int = 3,
        set_no: int = 1,
        *,
        stuck: bool = False,
        frozen_power: bool = False,
        set_after: int | None = None,
        unstick_on_tap: bool = False,
        power_base: int = 10000,
        power_step: int = 137,
    ) -> None:
        self.party = int(party)
        self.set_no = int(set_no)
        self.stuck = bool(stuck)
        self.frozen_power = bool(frozen_power)
        self.set_after = set_after
        self.unstick_on_tap = bool(unstick_on_tap)
        self.power_base = int(power_base)
        self.power_step = int(power_step)
        self.swipes: list = []
        self.taps: list = []
        self.reads = 0

    def power(self, party: int) -> int:
        if self.frozen_power:
            return 12345
        return self.power_base + self.power_step * int(party)

    def read(self, items=None, hits=None):
        """假的 ``team_impl.read_team``（签名对齐真函数：``(items, hits=None)``）。"""
        self.reads += 1
        return ((self.set_no, list(SET_BOX)), self.party, self.power(self.party))

    def swipe(self, x_from: int, x_to: int, y: int, ms: int) -> None:
        """假的横向滑动：按真机口径驱动 Party（左滑 +1 / 右滑 −1）。"""
        self.swipes.append((int(x_from), int(x_to), int(y), int(ms)))
        if x_from == x_to:
            raise AssertionError("横向滑动不能原地不动（x_from == x_to）")
        if self.stuck:
            return
        if x_from > x_to:  # 手指右→左 = 左滑 = Party +1
            self.party += 1
        else:  # 手指左→右 = 右滑 = Party −1
            self.party -= 1
        if self.set_after is not None and len(self.swipes) >= int(self.set_after):
            self.set_no = 2

    def tap(self, x: int, y: int) -> None:
        self.taps.append((int(x), int(y)))
        if self.unstick_on_tap:
            self.stuck = False


@contextlib.contextmanager
def _patched(ti, screen=None, read=None, sleep=None):
    """把 ``read_team`` / ``_sleep`` 换成假的；退出必定还原（顺序：read 优先于 screen）。"""
    saved_read = ti.read_team
    saved_sleep = ti._sleep
    if read is not None:
        ti.read_team = read
    elif screen is not None:
        ti.read_team = screen.read
    ti._sleep = sleep if sleep is not None else (lambda _seconds: None)
    try:
        yield ti
    finally:
        ti.read_team = saved_read
        ti._sleep = saved_sleep


def _capture(fn):
    """跑一次 ``fn``，返回 ``(返回值, stdout)``（日志断言用）。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = fn()
    return got, buf.getvalue()


def _run(ti, screen, fn, *, read=None):
    """在假 IO 里跑一次 ``fn``：``read_team``/``_sleep`` 都被替掉，返回 ``(返回值, stdout)``。"""
    with _patched(ti, screen, read=read):
        return _capture(fn)


def _tail(text: str, lines: int = 2) -> str:
    return " / ".join((text or "").strip().splitlines()[-lines:])


# ---------------------------------------------------------------------------
# 1. 方向：左滑 +1 / 右滑 −1；y 来自 SET 框；正常换队不点屏幕
# ---------------------------------------------------------------------------
def _direction_failures() -> list:
    ti = _impl()
    msgs: list = []

    # (a) 左滑：Party 3 → 5
    left = FakeScreen(party=3)
    ok, out = _run(
        ti, left, lambda: ti.switch_party(5, swipe_hook=left.swipe, tap_hook=left.tap)
    )
    if not ok:
        msgs.append(f"左滑 3→5 返回 False（日志尾：{_tail(out)!r}）")
    if left.party != 5:
        msgs.append(f"左滑 2 次后 Party = {left.party}，应为 5（方向反了？）")
    got_left = [s[:2] for s in left.swipes]
    if got_left != [SWIPE_LEFT, SWIPE_LEFT]:
        msgs.append(f"Party 变大应左滑 {SWIPE_LEFT}，实际 {got_left}")
    ys = sorted({s[2] for s in left.swipes})
    if ys != [SET_ROW_Y]:
        msgs.append(
            f"滑动行 y = {ys}，应为 SET 框中心 {SET_ROW_Y}"
            f"（票面：从 read_team 的 set 框取 y，不写死 465）"
        )
    if any(s[3] != int(ti.TEAM_PARTY_SWIPE_MS) for s in left.swipes):
        msgs.append(f"滑动时长不是 TEAM_PARTY_SWIPE_MS：{left.swipes}")
    if left.taps:
        msgs.append(f"正常换队却点了屏幕 {left.taps}（真机证据：切 Party 只需滑动，绝不盲点）")
    if "Party 4" not in out or "Party 5" not in out:
        msgs.append(f"每步复核的日志没印出 Party 逐步变化：{_tail(out, 4)!r}")
    if "SET 1（不变）" not in out:
        msgs.append(f"成功日志没印出「SET 不变」这一票：{_tail(out)!r}")

    # (b) 右滑：Party 5 → 3
    right = FakeScreen(party=5)
    ok, out = _run(ti, right, lambda: ti.switch_party(3, swipe_hook=right.swipe))
    if not ok:
        msgs.append(f"右滑 5→3 返回 False（日志尾：{_tail(out)!r}）")
    if right.party != 3:
        msgs.append(f"右滑 2 次后 Party = {right.party}，应为 3（方向反了？）")
    got_right = [s[:2] for s in right.swipes]
    if got_right != [SWIPE_RIGHT, SWIPE_RIGHT]:
        msgs.append(f"Party 变小应右滑 {SWIPE_RIGHT}，实际 {got_right}")
    if "Party 4" not in out or "Party 3" not in out:
        msgs.append(f"右滑每步日志没印出 Party 逐步变化：{_tail(out, 4)!r}")

    # (c) 纯函数：方向 ↔ 几何必须一一对应
    if ti.party_swipe_geometry(1, SET_ROW_Y)[:2] != SWIPE_LEFT:
        msgs.append(f"party_swipe_geometry(+1) = {ti.party_swipe_geometry(1, SET_ROW_Y)}，应左滑")
    if ti.party_swipe_geometry(-1, SET_ROW_Y)[:2] != SWIPE_RIGHT:
        msgs.append(f"party_swipe_geometry(-1) = {ti.party_swipe_geometry(-1, SET_ROW_Y)}，应右滑")
    return msgs


def probe_party_swipe_direction() -> bool:
    """#124-1：左滑 = Party +1、右滑 = Party −1；y 取自 SET 框；正常换队不点屏幕。"""
    return _direction_failures() == []


# ---------------------------------------------------------------------------
# 2. 三重校验：SET 不变 ∧ Party 命中 ∧ 战力变化，缺一即失败
# ---------------------------------------------------------------------------
def _triple_failures() -> list:
    ti = _impl()
    msgs: list = []

    # (a) 纯函数：三票齐全才绿；三个剧本各缺一票，各自要红且原因带量。
    good = ti.TeamReading(1, 3, 1234, tuple(SET_BOX))
    hit = ti.TeamReading(1, 5, 5678, tuple(SET_BOX))
    ok, reasons = ti.verify_party_switch(good, hit, 5)
    if not ok:
        msgs.append(f"三票齐全的正确换队被判失败：{reasons}")
    for label, bad, needle in (
        ("SET 变了", ti.TeamReading(2, 5, 5678, tuple(SET_BOX)), "SET 变了"),
        ("Party 没到", ti.TeamReading(1, 4, 5678, tuple(SET_BOX)), "Party 没到位"),
        ("战力没变", ti.TeamReading(1, 5, 1234, tuple(SET_BOX)), "战力没变"),
    ):
        ok, reasons = ti.verify_party_switch(good, bad, 5)
        if ok:
            msgs.append(f"三票缺「{label}」却判成功（三重校验漏了一票）")
        elif not any(needle in reason for reason in reasons):
            msgs.append(f"三票缺「{label}」的失败原因没说清（缺 {needle!r}）：{reasons}")

    # (b) 全流程：三个剧本各跑一遍 switch_party，都必须 False，且日志带量。
    for label, screen, target in (
        ("SET 变了", FakeScreen(party=3, set_after=1), 5),
        ("Party 没到", FakeScreen(party=3, stuck=True), 5),
        ("战力没变", FakeScreen(party=3, frozen_power=True), 5),
    ):
        ok, out = _run(
            ti, screen, lambda s=screen, t=target: ti.switch_party(t, swipe_hook=s.swipe)
        )
        if ok:
            msgs.append(f"剧本「{label}」却返回 True（三重校验没兜住）")
            continue
        if "✗ 切队失败" not in out:
            msgs.append(f"剧本「{label}」失败日志没有收尾结论：{_tail(out)!r}")
        for needle in (f"目标 Party {target}", "共滑", "战力"):
            if needle not in out:
                msgs.append(f"剧本「{label}」的失败日志缺 {needle!r}（票面：失败原因要带量）：{_tail(out)!r}")
        if label == "SET 变了" and "SET" not in out:
            msgs.append(f"剧本「SET 变了」的日志没点名 SET：{_tail(out)!r}")
        if label == "Party 没到" and "没按预期" not in out:
            msgs.append(f"剧本「Party 没到」没报「每步没按预期」：{_tail(out, 3)!r}")
        if label == "战力没变" and "战力没变" not in out:
            msgs.append(f"剧本「战力没变」没点名战力没变：{_tail(out)!r}")
    return msgs


def probe_party_triple_check() -> bool:
    """#124-2：SET 不变 ∧ Party 命中 ∧ 战力变化；缺任一票即失败（纯函数 + 全流程）。"""
    return _triple_failures() == []


# ---------------------------------------------------------------------------
# 3. 有界：|Δ| 超上限 ⇒ 一步不滑；= 上限允许
# ---------------------------------------------------------------------------
def _bound_failures() -> list:
    ti = _impl()
    msgs: list = []

    if int(ti.TEAM_PARTY_SWIPE_MAX) != MAX_DELTA:
        msgs.append(f"TEAM_PARTY_SWIPE_MAX = {ti.TEAM_PARTY_SWIPE_MAX}，票面建议 {MAX_DELTA}")

    # ★前提★ 真机 1..10 轮播时，合法目标之间的 |Δ| 最大只有 9（= PARTY_COUNT − 1）≤ 12，
    #   所以 |Δ| 上限是**第二道闸**（只有读数越界/范围将来变大时才可能触发）。先用合法范围
    #   证明「环里的最大跨度不被误杀」，再用越界读数把这道闸本身逼出来。
    span = FakeScreen(party=1)
    ok, out = _run(ti, span, lambda: ti.switch_party(PARTY_COUNT, swipe_hook=span.swipe))
    if not ok or span.party != PARTY_COUNT:
        msgs.append(f"环内最大跨度 1→{PARTY_COUNT} 被误杀：ok={ok} party={span.party}（{_tail(out)!r}）")
    if len(span.swipes) != PARTY_COUNT - 1:
        msgs.append(f"1→{PARTY_COUNT} 应滑 {PARTY_COUNT - 1} 次，实际 {len(span.swipes)}")

    # (a) 超上限：读数在环外（Party -5，Δ = PARTY_COUNT + 5 = 15 > 12）⇒ 一步不滑、直接失败。
    #     读数来自 OCR，本身可能错 —— 上限就是给这种「不在 1..10 的读数」兜底的。
    over = FakeScreen(party=-5)
    ok, out = _run(ti, over, lambda: ti.switch_party(PARTY_COUNT, swipe_hook=over.swipe))
    if ok:
        msgs.append(f"|Δ| = {PARTY_COUNT + 5} 超上限却返回 True")
    if over.swipes:
        msgs.append(f"|Δ| 超上限还是滑了 {len(over.swipes)} 次（票面：不滑、直接失败）")
    if "上限" not in out or str(MAX_DELTA) not in out:
        msgs.append(f"超上限的失败日志没带量（上限值/|Δ|）：{_tail(out)!r}")

    # (b) 刚好上限：读数 Party -2 → 目标 10，Δ = 12 ⇒ 允许滑满 12 次并成功（有界 ≠ 一律拒动）
    edge = FakeScreen(party=-2)
    ok, out = _run(ti, edge, lambda: ti.switch_party(PARTY_COUNT, swipe_hook=edge.swipe))
    if not ok:
        msgs.append(f"|Δ| = {MAX_DELTA}（正好在界内）却失败：{_tail(out)!r}")
    if len(edge.swipes) != MAX_DELTA:
        msgs.append(f"|Δ| = {MAX_DELTA} 时滑了 {len(edge.swipes)} 次，应为 {MAX_DELTA}")
    if edge.party != PARTY_COUNT:
        msgs.append(f"|Δ| = {MAX_DELTA} 后 Party = {edge.party}，应为 {PARTY_COUNT}")

    # (c) 非法目标：不滑、不抛（#124 起：日志说「不存在」而不是旧的「必须 ≥1」）
    for bad in (0, -3):
        screen = FakeScreen(party=3)
        ok, out = _run(ti, screen, lambda s=screen, b=bad: ti.switch_party(b, swipe_hook=s.swipe))
        if ok or screen.swipes:
            msgs.append(f"目标 Party {bad} 不存在却动了：ok={ok} swipes={screen.swipes}")
        if "不存在" not in out:
            msgs.append(f"目标 Party {bad} 的失败没说清「不存在」：{_tail(out)!r}")
    return msgs


def probe_party_swipe_bounded() -> bool:
    """#124-3：|Δ| > 12 ⇒ 不滑直接失败；|Δ| == 12 允许；目标越界不动。"""
    return _bound_failures() == []


# ---------------------------------------------------------------------------
# 4. 接缝：幂等 / 无 swipe_hook / read_hook / tap_hook
# ---------------------------------------------------------------------------
def _seam_failures() -> list:
    ti = _impl()
    msgs: list = []

    # (a) 已在目标：幂等成功，一步不滑
    same = FakeScreen(party=4)
    ok, out = _run(ti, same, lambda: ti.switch_party(4, swipe_hook=same.swipe))
    if not ok or same.swipes:
        msgs.append(f"已在目标 Party 4：ok={ok} swipes={same.swipes}（应 True 且不滑）")
    if "已在目标" not in out:
        msgs.append(f"幂等成功没说明「已在目标」：{_tail(out)!r}")

    # (b) 没有 swipe_hook：带原因失败，绝不盲动
    no_hook = FakeScreen(party=3)
    ok, out = _run(ti, no_hook, lambda: ti.switch_party(5, read_hook=no_hook.read))
    if ok:
        msgs.append("没有 swipe_hook 却返回 True（没有任何滑动被执行）")
    if "swipe_hook" not in out:
        msgs.append(f"没有 swipe_hook 的失败原因没说清：{_tail(out)!r}")

    # (c) read_hook 可独立注入：模块级 read_team 换成「一读就炸」，也不该影响 read_hook 路径
    def _boom(*_a, **_k):
        raise RuntimeError("read_team 不该被 read_hook 路径调用")

    screen = FakeScreen(party=3)
    ok, out = _run(
        ti,
        None,
        lambda: ti.switch_party(5, read_hook=screen.read, swipe_hook=screen.swipe),
        read=_boom,
    )
    if not ok or screen.party != 5:
        msgs.append(f"read_hook 注入没生效：ok={ok} party={screen.party}（日志尾：{_tail(out)!r}）")

    # (d) 读数异常必须留痕（不吞、不崩）
    raised = FakeScreen(party=3)

    def _raise_read():
        raise RuntimeError("假帧源炸了")

    ok, out = _run(
        ti, None, lambda: ti.switch_party(5, read_hook=_raise_read, swipe_hook=raised.swipe)
    )
    if ok or raised.swipes:
        msgs.append(f"读数异常却动了：ok={ok} swipes={raised.swipes}")
    if "读帧异常" not in out or "RuntimeError" not in out:
        msgs.append(f"读数异常没有留痕（类型/原因）：{_tail(out)!r}")

    # (e) 第 1 次一步没动 + 给了 tap_hook ⇒ 只轻点一次 SET 框中心，重试后成功
    sticky = FakeScreen(party=3, stuck=True, unstick_on_tap=True)
    ok, out = _run(
        ti, sticky, lambda: ti.switch_party(5, swipe_hook=sticky.swipe, tap_hook=sticky.tap)
    )
    if not ok:
        msgs.append(f"轻点后重试仍失败（第 2 次尝试白做）：{_tail(out, 3)!r}")
    if sticky.taps != [(SET_ROW_X, SET_ROW_Y)]:
        msgs.append(
            f"轻点位置/次数不对：{sticky.taps}，应为一次 SET 框中心 ({SET_ROW_X},{SET_ROW_Y})"
        )
    if "一步没动" not in out:
        msgs.append(f"轻点前的日志没说清「一步没动」：{_tail(out, 4)!r}")

    # (f) 没给 tap_hook 时，就算一步没动也绝不点（默认不盲点）
    frozen = FakeScreen(party=3, stuck=True, unstick_on_tap=True)
    ok, _out = _run(ti, frozen, lambda: ti.switch_party(5, swipe_hook=frozen.swipe))
    if ok or frozen.taps:
        msgs.append(f"没给 tap_hook 却点了屏幕：ok={ok} taps={frozen.taps}")
    return msgs


def probe_party_switch_seams() -> bool:
    """#124-4：幂等 / 无 swipe_hook / read_hook 注入 / 读数异常留痕 / 轻点只在给了 tap_hook 时发生。"""
    return _seam_failures() == []


# ---------------------------------------------------------------------------
# 5. 常量真源：scene/team.py ⇄ agent 的逐字冻结快照 ⇄ 运行时读数
# ---------------------------------------------------------------------------
def _constants_failures() -> list:
    ti = _impl()
    sc = _scene()
    msgs: list = []
    for name in PARTY_CONSTANTS:
        snap_name = f"_{name}_SNAPSHOT"
        src = getattr(sc, name, "<missing>")
        snap = getattr(ti, snap_name, "<missing>")
        live = getattr(ti, name, "<missing>")
        want = PARTY_CONSTANT_VALUES[name]
        if src == "<missing>":
            msgs.append(f"真源 scene/team.py 缺 {name}（6 个常量没搬进真源？）")
            continue
        if snap == "<missing>":
            msgs.append(f"agent/team_impl.py 缺逐字快照 {snap_name}（安装态会没数可用）")
            continue
        # 逐字：值 + 类型一起比（(600,200) 与 [600,200] 不是同一份数据）。
        if type(src) is not type(snap) or src != snap:
            msgs.append(
                f"{name} 快照漂移：scene={src!r}({type(src).__name__}) / "
                f"snapshot={snap!r}({type(snap).__name__})（安装态用的就是快照，漂移=真机手势错）"
            )
        if src != want or type(src) is not type(want):
            msgs.append(
                f"{name} 真源值变了：{src!r}，真机 394eb66 标定是 {want!r}"
                f"（改数值必须附新的真机标定证据）"
            )
        if live != src:
            msgs.append(f"{name} 运行时没读真源：agent={live!r} / scene={src!r}（运行时必须是真源的值）")
    if getattr(ti, "CFG_SOURCE", None) != "scene":
        msgs.append(f"team_impl 没读到 scene（CFG_SOURCE={getattr(ti, 'CFG_SOURCE', None)!r}）—— 仓库态应当读真源")
    return msgs


def probe_party_constants_source_of_truth() -> bool:
    """#124-5：6 个 TEAM_PARTY_* 常量在 scene/team.py（真源）== agent 逐字快照 == 运行时。"""
    return _constants_failures() == []


# ---------------------------------------------------------------------------
# 6. 动作接线：A 类页 + 目标 Party ⇒ 调 switch_party；非 A 类页 / 读不到 ⇒ 不调
# ---------------------------------------------------------------------------
class FakeBattlePage:
    """一台只存在于内存里的**整页**（A 类战前编队页 / B 类编辑器）。

    与 :class:`FakeScreen` 的分工：``FakeScreen`` 打的是 ``read_team``（算法层），本类打的是
    ``ocr_all`` + 原生 Swipe（**动作层**），所以「页判据读的是哪一帧」「目标队参数怎么用」
    「成功判据是不是 switch_party 的返回值」都被覆盖到。

    ``swipe`` 按**真机口径**驱动 Party（左滑 +1 / 右滑 −1）；``战力`` 随 Party 变
    （真机 394eb66：Party 变 ⇒ 战力变），三重校验的第三票才有东西可验。
    """

    #: 队号 → 字母（与真源 ``TEAM_PARTY_LETTERS`` 同口径；只为造帧，不参与判据）。
    #: 真机 10 队 ⇒ A..J（2026-10-18）；造帧时优先读真源，漂了也造得出 10 队帧。
    LETTERS = "ABCDEFGHIJ"

    def __init__(
        self,
        party: int = 3,
        set_no: int = 1,
        *,
        page: str = "A",
        party_readable: bool = True,
        frozen_power: bool = False,
        power_base: int = 10000,
        power_step: int = 137,
    ) -> None:
        self.party = int(party)
        self.set_no = int(set_no)
        self.page = str(page)
        self.party_readable = bool(party_readable)
        self.frozen_power = bool(frozen_power)
        self.power_base = int(power_base)
        self.power_step = int(power_step)
        self.swipes: list = []
        self.clicks: list = []
        self.reads = 0

    def power(self) -> int:
        if self.frozen_power:
            return 12345
        return self.power_base + self.power_step * int(self.party)

    def _letter(self, party: int) -> str:
        """队号 → 字母（优先真源 ``TEAM_PARTY_LETTERS``；真源漂了也照真源造帧）。"""
        letters = str(getattr(_scene(), "TEAM_PARTY_LETTERS", self.LETTERS))
        idx = int(party) - 1
        return letters[idx] if 0 <= idx < len(letters) else "?"

    def frame(self) -> list:
        """当帧 OCR 项（720 空间）。A 类锚点从**真源常量**取，不在这里抄第三份。"""
        if self.page != "A":
            # B 类编辑器帧：有「切换」锚点，没有 A 类独有锚点。
            return [
                ("SET 1", [30, 14, 48, 19]),
                ("5 Party E", [78, 74, 96, 24]),
                ("切换", [633, 685, 40, 24]),
                ("战力 13,116", [560, 74, 140, 24]),
            ]
        anchor = getattr(_scene(), "TEAM_PAGE_ANCHOR_A", None)
        items = [
            (f"SET {self.set_no}", list(SET_BOX)),
            (anchor, [20, 1060, 80, 24]),
        ]
        if self.party_readable:
            items.append(
                (f"{self.party}  Party {self._letter(self.party)}", [35, 520, 130, 24])
            )
        items.append((f"战力 {self.power():,}", [500, 516, 130, 24]))
        return items

    def read(self) -> list:
        """假的 ``ocr_all``：每次调用给一帧（读多少次都自洽）。"""
        self.reads += 1
        return self.frame()

    def swipe(self, x_from: int, x_to: int, y: int, ms: int) -> bool:
        """假的 ``team_impl.swipe_party_row``：按真机口径驱动 Party。"""
        self.swipes.append((int(x_from), int(x_to), int(y), int(ms)))
        if x_from == x_to:
            raise AssertionError("横向滑动不能原地不动（x_from == x_to）")
        if x_from > x_to:  # 手指右→左 = 左滑 = Party +1
            self.party += 1
        else:  # 手指左→右 = 右滑 = Party −1
            self.party -= 1
        return True

    def tap(self, x: int, y: int) -> bool:
        self.clicks.append((int(x), int(y)))
        return True


class _ActionArgv:
    """``read_action_param`` 要的 ``argv``（只有 ``custom_action_param`` 有用）。"""

    def __init__(self, param: dict) -> None:
        self.custom_action_param = json.dumps(param)


def _action_run(ti, screen: FakeBattlePage, param: dict):
    """跑一次 ``TeamSwitchBattleAction``：OCR / 滑 / 点 / 睡全部换成假设备。

    返回 ``(stdout, calls)``；``calls["switch_party"]`` 是**目标队号**的调用记录
    （包装真实 ``switch_party``，不是替身 —— 这样「调用计数」与「真算法」同时被验）。
    """
    calls = {"switch_party": []}
    real_switch = ti.switch_party

    def _counting_switch(target, **kwargs):
        calls["switch_party"].append(target)
        return real_switch(target, **kwargs)

    saved = (ti.ocr_all, ti._grab, ti._click_box, ti.swipe_party_row, ti._sleep, ti.switch_party)
    ti.ocr_all = lambda context, image, entry="OcrTask": screen.read()
    ti._grab = lambda context: object()
    ti._click_box = lambda context, cx, cy: screen.tap(cx, cy)
    # 注意签名：生产侧是 ``swipe_party_row(context, x_from, x_to, y, ms)``（context 在前）。
    ti.swipe_party_row = lambda context, x_from, x_to, y, ms: screen.swipe(x_from, x_to, y, ms)
    ti._sleep = lambda _seconds: None
    ti.switch_party = _counting_switch
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ti.TeamSwitchBattleAction().run(None, _ActionArgv(param))
        out = buf.getvalue()
    finally:
        (ti.ocr_all, ti._grab, ti._click_box, ti.swipe_party_row, ti._sleep, ti.switch_party) = saved
    return out, calls


def run_battle_action(screen: FakeBattlePage, param: dict):
    """公开给兄弟守卫（``hooks_105`` 的 V5）复用：跑一次动作，返回 ``(stdout, calls)``。"""
    return _action_run(_impl(), screen, param)


def _wiring_failures() -> list:
    ti = _impl()
    msgs: list = []

    # (a) 不在 A 类页（B 类编辑器帧）：**零调用**，不滑不点
    b_page = FakeBattlePage(party=3, page="B")
    out, calls = _action_run(ti, b_page, {"set": 1, "party": 5})
    if calls["switch_party"]:
        msgs.append(f"B 类页（非 A 类）也调了 switch_party：{calls['switch_party']}（应零调用）")
    if b_page.swipes or b_page.clicks:
        msgs.append(f"B 类页上动了：swipes={b_page.swipes} clicks={b_page.clicks}")
    if "不是战前编队页" not in out:
        msgs.append(f"B 类页没说明「不是战前编队页」：{_tail(out)!r}")

    # (b) A 类页但读不到编队（Party 读不到）：零调用（旧的「读不到就不动」）
    blind = FakeBattlePage(party=3, party_readable=False)
    out, calls = _action_run(ti, blind, {"set": 1, "party": 5})
    if calls["switch_party"]:
        msgs.append(f"读不到编队却调了 switch_party：{calls['switch_party']}（应零调用）")
    if blind.swipes or blind.clicks:
        msgs.append(f"读不到编队却动了：swipes={blind.swipes} clicks={blind.clicks}")
    if "拒动" not in out:
        msgs.append(f"读不到编队没有明确「拒动」：{_tail(out)!r}")

    # (c) 三重校验不过（战力没变）：可以滑，但**绝不打印成功**
    frozen = FakeBattlePage(party=3, frozen_power=True)
    out, calls = _action_run(ti, frozen, {"set": 1, "party": 5})
    if calls["switch_party"] != [5]:
        msgs.append(f"战力不变时也应先走 switch_party（调用记录 {calls['switch_party']}）")
    if "✓ 收尾" in out or "切队成功" in out:
        msgs.append(f"三重校验不过（战力没变）却打印了成功：{_tail(out, 3)!r}")
    if "✗" not in out:
        msgs.append(f"三重校验不过没有失败收尾：{_tail(out)!r}")

    # (d) A 类页 + 目标 Party：必须调 switch_party，真滑到目标，全程**零点击**
    page = FakeBattlePage(party=3)
    out, calls = _action_run(ti, page, {"set": 1, "party": 5})
    if calls["switch_party"] != [5]:
        msgs.append(
            f"A 类页 + 目标 Party 5 没有调用 switch_party（调用记录 {calls['switch_party']}）"
            "—— 动作可能退回旧的「点 SET 条」路径"
        )
    if page.party != 5:
        msgs.append(f"动作跑完 Party = {page.party}，应为 5（横向滑动没接上？）")
    if [s[:2] for s in page.swipes] != [SWIPE_LEFT, SWIPE_LEFT]:
        msgs.append(f"Party 3→5 应左滑 {SWIPE_LEFT} 两次，实际 {[s[:2] for s in page.swipes]}")
    if any(s[2] != SET_ROW_Y for s in page.swipes):
        msgs.append(f"滑动行 y 不是 SET 框中心 {SET_ROW_Y}：{page.swipes}")
    if page.clicks:
        msgs.append(
            f"切 Party 时点了屏幕 {page.clicks}（真机证据：切队只需横向滑动，点 SET 条无效 —— "
            "动作退回点条就是这条）"
        )
    if "✓ 收尾" not in out:
        msgs.append(f"动作没打印成功收尾：{_tail(out)!r}")
    if "SET 1（不变）" not in out or "切队成功" not in out:
        msgs.append(f"动作日志里没有 switch_party 的三重校验成功行（SET 不变 / 切队成功）：{_tail(out)!r}")

    # (e) 已在目标：幂等成功且零滑动（switch_party 仍然被调用一次）
    same = FakeBattlePage(party=5)
    out, calls = _action_run(ti, same, {"set": 1, "party": 5})
    if calls["switch_party"] != [5]:
        msgs.append(f"已在目标 Party 5 没走 switch_party：{calls['switch_party']}")
    if same.swipes:
        msgs.append(f"已在目标却滑了 {len(same.swipes)} 次（幂等被破坏）")
    if "✓ 收尾" not in out:
        msgs.append(f"已在目标却没有成功收尾：{_tail(out)!r}")
    return msgs


def probe_party_action_wiring() -> bool:
    """#124-6：A 类页 + 目标 Party ⇒ 调 switch_party（真滑到目标、零点击）；非 A 类页 / 读不到 ⇒ 零调用。"""
    return _wiring_failures() == []


# ---------------------------------------------------------------------------
# 7. 目标越界：一步不滑 + 不默认夹紧（真机后续 ①+②）
# ---------------------------------------------------------------------------
def _target_bounds_failures() -> list:
    """越界目标**连读数都不读**、更不滑；默认绝不夹紧；clamp=True 才夹且打印结果。

    真机缺陷（2026-10-18 报表）：``switch_party(11)`` 从 Party 10 起**滑了 11 次**才失败，还把
    轮播**留在 Party 1**。所以这里断言的不只是返回值，还有 ``swipes`` / ``reads`` 都为 0 ——
    「不存在的目标不配得到一次 IO」。
    """
    ti = _impl()
    msgs: list = []
    count = int(getattr(ti, "TEAM_PARTY_COUNT", 0))
    if count != PARTY_COUNT:
        msgs.append(
            f"TEAM_PARTY_COUNT = {count}，真机是 1..{PARTY_COUNT}（2026-10-18 A 实测 10 队）"
        )

    # (a) 目标存在性纯函数：1..10 可，0 / 11 / 99 / None 不可；夹紧只给 clamp 用。
    for want in range(1, PARTY_COUNT + 1):
        if ti.party_target_ok(want) is not True:
            msgs.append(f"party_target_ok({want}) = {ti.party_target_ok(want)!r}，应为 True")
    for bad in (0, -3, PARTY_COUNT + 1, 99, None, "x"):
        if ti.party_target_ok(bad) is not False:
            msgs.append(f"party_target_ok({bad!r}) = {ti.party_target_ok(bad)!r}，应为 False")
    if ti.clamp_party_target(PARTY_COUNT + 1) != PARTY_COUNT:
        msgs.append(f"clamp_party_target({PARTY_COUNT + 1}) = {ti.clamp_party_target(PARTY_COUNT + 1)}")
    if ti.clamp_party_target(0) != 1:
        msgs.append(f"clamp_party_target(0) = {ti.clamp_party_target(0)}，应为 1")

    # (b) 越界 ⇒ 零滑动、零读数、False、日志含「一步没滑」；默认路径**不许出现夹紧**。
    for bad in (0, PARTY_COUNT + 1, 99):
        screen = FakeScreen(party=PARTY_COUNT)  # 从 Party 10 起：老缺陷就是在这滑 11 次
        ok, out = _run(ti, screen, lambda s=screen, b=bad: ti.switch_party(b, swipe_hook=s.swipe))
        if ok is not False:
            msgs.append(f"目标 Party {bad} 不存在却返回 {ok!r}（静默夹紧/假成功）")
        if screen.swipes:
            msgs.append(
                f"目标 Party {bad} 不存在却滑了 {len(screen.swipes)} 次"
                f"（票面：一步没滑就失败；老缺陷是滑 {PARTY_COUNT + 1} 次还把轮播留在别处）"
            )
        if screen.reads:
            msgs.append(f"目标 Party {bad} 不存在却读了 {screen.reads} 次帧（存在性是纯目标属性，不该碰 IO）")
        if "一步没滑" not in out:
            msgs.append(f"目标 Party {bad} 的失败日志没说清「一步没滑」：{_tail(out)!r}")
        if "不存在" not in out or f"1..{PARTY_COUNT}" not in out:
            msgs.append(f"目标 Party {bad} 的失败日志没写「不存在（真机轮播 1..{PARTY_COUNT}）」：{_tail(out)!r}")
        if "夹紧" in out:
            msgs.append(f"目标 Party {bad} 的默认路径打印了夹紧（默认绝不夹紧）：{_tail(out)!r}")

    # (c) 显式 clamp=True：夹紧**要打印结果**并真的切过去（不是只改个返回值）。
    screen = FakeScreen(party=3)
    ok, out = _run(ti, screen, lambda: ti.switch_party(99, swipe_hook=screen.swipe, clamp=True))
    if not ok or screen.party != PARTY_COUNT:
        msgs.append(f"clamp=True 目标 99（Party 3 起）没夹到 {PARTY_COUNT}：ok={ok} party={screen.party}")
    if len(screen.swipes) != PARTY_COUNT - 3:
        msgs.append(f"clamp=True 目标 99 应滑 {PARTY_COUNT - 3} 次，实际 {len(screen.swipes)}")
    if "夹紧到" not in out or f"夹紧到 {PARTY_COUNT}" not in out:
        msgs.append(f"clamp=True 没打印夹紧结果：{_tail(out, 3)!r}")
    if "目标 Party 99" not in out:
        msgs.append(f"clamp=True 的日志没点名原始目标 99（调用方要能看出被夹过）：{_tail(out, 3)!r}")

    # (d) 显式 clamp=True 的下界：0 → 1。
    low = FakeScreen(party=3)
    ok, out = _run(ti, low, lambda: ti.switch_party(0, swipe_hook=low.swipe, clamp=True))
    if not ok or low.party != 1:
        msgs.append(f"clamp=True 目标 0（Party 3 起）没夹到 1：ok={ok} party={low.party}")
    if "夹紧到 1" not in out:
        msgs.append(f"clamp=True 目标 0 没打印「夹紧到 1」：{_tail(out, 3)!r}")

    # (e) clamp=True 且夹紧后已在目标：零滑动、幂等成功。
    same = FakeScreen(party=PARTY_COUNT)
    ok, _out = _run(ti, same, lambda: ti.switch_party(PARTY_COUNT + 1, swipe_hook=same.swipe, clamp=True))
    if not ok or same.swipes:
        msgs.append(f"clamp=True 夹到已在的目标却动了：ok={ok} swipes={len(same.swipes)}")
    return msgs


def probe_party_target_bounds() -> bool:
    """#124-7：越界目标零滑动零读数 + 默认绝不夹紧（clamp=True 才夹且打印）。"""
    return _target_bounds_failures() == []


# ---------------------------------------------------------------------------
# 8. 队数与字母表：TEAM_PARTY_COUNT == 10 且 len(TEAM_PARTY_LETTERS) == TEAM_PARTY_COUNT
# ---------------------------------------------------------------------------
def _alphabet_failures() -> list:
    """真机 10 队 ⇒ 队数 10、字母表 A..J 也是 10 个（真源 + agent 运行时两侧）。

    为什么盯长度：字母表只有 A..H 时，OCR 吞掉队号大字后 ``Party I`` / ``Party J`` 会退化成
    「读不到 Party」——编队页判定成立却读不出队（#105 修过的同一类坏点）。
    """
    ti = _impl()
    sc = _scene()
    msgs: list = []

    for label, mod in (("scene", sc), ("agent", ti)):
        count = int(getattr(mod, "TEAM_PARTY_COUNT", 0))
        letters = str(getattr(mod, "TEAM_PARTY_LETTERS", ""))
        if count != PARTY_COUNT:
            msgs.append(f"{label}.TEAM_PARTY_COUNT = {count}，真机 1..{PARTY_COUNT}（2026-10-18 A 实测）")
        if letters != PARTY_LETTERS:
            msgs.append(f"{label}.TEAM_PARTY_LETTERS = {letters!r}，应为 {PARTY_LETTERS!r}（真机 10 队 ⇒ A..J）")
        if len(letters) != count:
            msgs.append(
                f"{label} 队名字母表长度 {len(letters)} != TEAM_PARTY_COUNT {count} "
                f"（短了 Party I/J 会退化成「读不到 Party」）"
            )
        for idx, letter in enumerate(PARTY_LETTERS, 1):
            got = mod.party_ordinal(letter)
            if got != idx:
                msgs.append(f"{label}.party_ordinal({letter!r}) = {got!r}，应为 {idx}")
        for letter in ("K", "", "AA", "1"):
            if mod.party_ordinal(letter) is not None:
                msgs.append(f"{label}.party_ordinal({letter!r}) 不该有解（越界字母绝不猜）")

    # 真解析腿：队号大字被吞掉时 ``Party I`` / ``Party J`` 必须读成 9 / 10（不许退化成 None）。
    for letter, want in (("I", 9), ("J", 10)):
        state = ti.read_team(
            [
                ("SET 1", list(SET_BOX)),
                (f"Party {letter}", [35, 520, 130, 24]),
                ("战力 100", [500, 516, 130, 24]),
            ],
            None,
        )
        if state[1] != want:
            msgs.append(
                f"read_team 对「Party {letter}」的字母兜底 = {state[1]!r}，应为 {want}"
                f"（OCR 吞掉队号大字时读不出 Party {letter}）"
            )

    # GUI 值域是**另一件事**：interface.json 只列 1..6，别拿真机队数去撑它（hooks_91 会红）。
    option_parties = int(getattr(sc, "TEAM_OPTION_PARTIES", -1))
    if not (1 <= option_parties <= PARTY_COUNT):
        msgs.append(f"TEAM_OPTION_PARTIES = {option_parties}，应在 1..{PARTY_COUNT} 之间")
    values = sc.option_values()
    if len(values) != 1 + option_parties:
        msgs.append(
            f"scene.option_values() 给出 {len(values)} 项，应为 1 + TEAM_OPTION_PARTIES({option_parties})"
            f"（GUI 值域没扩；扩它要同时改 assets/interface.json）"
        )
    return msgs


def probe_party_alphabet_count() -> bool:
    """#124-8：队数 == 10 且字母表长度 == 队数（Party I/J 不许退化成「读不到 Party」）。"""
    return _alphabet_failures() == []


# ---------------------------------------------------------------------------
# 9. 动作层队数：team_switch / team_switch_battle 的 1..10 都放行、0 不当作队号、11 拒
# ---------------------------------------------------------------------------
class _GateIO:
    """动作层的假 IO 计数器（只回答一件事：这次动作碰没碰 OCR / 点击 / 滑动）。"""

    def __init__(self) -> None:
        self.ocr_calls = 0
        self.grabs = 0
        self.clicks: list = []
        self.swipes: list = []


def _run_action_gate(ti, action_cls, param: dict):
    """跑一次动作（OCR 恒空、点击/滑动全部计数），返回 ``(stdout, gate)``。"""
    gate = _GateIO()

    def _ocr_all(context, image, entry="OcrTask"):
        gate.ocr_calls += 1
        return []

    def _grab(context):
        gate.grabs += 1
        return object()

    def _click(context, x, y):
        gate.clicks.append((x, y))
        return True

    def _swipe(context, x_from, x_to, y, ms):
        gate.swipes.append((x_from, x_to, y, ms))
        return True

    saved = (ti.ocr_all, ti._grab, ti._click_box, ti._sleep, ti.swipe_party_row)
    ti.ocr_all, ti._grab, ti._click_box = _ocr_all, _grab, _click
    ti._sleep = lambda _seconds: None
    ti.swipe_party_row = _swipe
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            action_cls().run(None, _ActionArgv(param))
        out = buf.getvalue()
    finally:
        (ti.ocr_all, ti._grab, ti._click_box, ti._sleep, ti.swipe_party_row) = saved
    return out, gate


def _count_action_failures() -> list:
    """两个动作的队数闸门：1..10 放行（#124 的真缺陷：7..10 被拒）、显式 0 / 越界拒且零 IO。"""
    ti = _impl()
    msgs: list = []
    for action_name, action_cls in (
        ("team_switch", ti.TeamSwitchAction),
        ("team_switch_battle", ti.TeamSwitchBattleAction),
    ):
        # (a) 1..10 全部放行：不许出现「不存在 / 越界」，且动作真的往下走了（读了帧）。
        for party in range(1, PARTY_COUNT + 1):
            out, gate = _run_action_gate(ti, action_cls, {"set": 1, "party": party})
            if "不存在" in out or "越界" in out:
                msgs.append(
                    f"{action_name}：目标队 {party}（真机 1..{PARTY_COUNT}）被拒了"
                    f" —— #124 的真缺陷（7..10 直接拒）复发：{_tail(out)!r}"
                )
            if gate.ocr_calls < 1:
                msgs.append(f"{action_name}：目标队 {party} 在闸门后没读帧（动作被提前挡掉了）")
            if gate.clicks or gate.swipes:
                msgs.append(
                    f"{action_name}：目标队 {party} 在空帧上动了 clicks={gate.clicks} swipes={gate.swipes}"
                )

        # (b) 越界 ⇒ 拒动且**零 IO**（OCR / 抓帧 / 点击 / 滑动都不许发生）。
        for bad in (PARTY_COUNT + 1, 99):
            out, gate = _run_action_gate(ti, action_cls, {"set": 1, "party": bad})
            if "不存在" not in out and "越界" not in out:
                msgs.append(f"{action_name}：目标队 {bad} 越界却没拒（日志：{_tail(out)!r}）")
            if gate.ocr_calls or gate.grabs or gate.clicks or gate.swipes:
                msgs.append(
                    f"{action_name}：目标队 {bad} 越界却做了 IO（ocr={gate.ocr_calls} grab={gate.grabs} "
                    f"clicks={gate.clicks} swipes={gate.swipes}）"
                )

        # (c) **显式** party=0 ⇒ 越界拒动（0 不是队号，真机 1..10）且零 IO；
        #     **不给** party 才是「只切 SET」的旧语义（不能把两者混成一句 0）。
        out, gate = _run_action_gate(ti, action_cls, {"set": 1, "party": 0})
        if "不存在" not in out and "越界" not in out:
            msgs.append(f"{action_name}：显式 party=0 没被拒（0 不是队号）：{_tail(out)!r}")
        if gate.ocr_calls or gate.grabs or gate.clicks or gate.swipes:
            msgs.append(
                f"{action_name}：显式 party=0 却做了 IO（ocr={gate.ocr_calls} grab={gate.grabs} "
                f"clicks={gate.clicks} swipes={gate.swipes}）"
            )
        out, gate = _run_action_gate(ti, action_cls, {"set": 1})
        if "不存在" in out or "越界" in out:
            msgs.append(f"{action_name}：不给 party 却报越界（旧「只切 SET」语义被破坏）：{_tail(out)!r}")
        if gate.clicks or gate.swipes:
            msgs.append(f"{action_name}：不给 party 却动了 clicks={gate.clicks} swipes={gate.swipes}")

    # (d) 端到端：真机 10 队上 party 7→10、10→7 都必须能切（老缺陷 7..10 会被闸门拒）。
    page = FakeBattlePage(party=7)
    out, calls = _action_run(ti, page, {"set": 1, "party": 10})
    if calls["switch_party"] != [10] or page.party != 10:
        msgs.append(f"动作：Party 7→10 没切到（调用 {calls['switch_party']} / 实际 {page.party}）")
    if "✓ 收尾" not in out:
        msgs.append(f"动作：Party 7→10 没打印成功收尾：{_tail(out, 3)!r}")
    back = FakeBattlePage(party=10)
    _out, calls = _action_run(ti, back, {"set": 1, "party": 7})
    if calls["switch_party"] != [7] or back.party != 7:
        msgs.append(f"动作：Party 10→7 没切到（调用 {calls['switch_party']} / 实际 {back.party}）")
    return msgs


def probe_party_count_actions() -> bool:
    """#124-9：两个动作的 1..10 都放行、显式 party=0 与越界拒动、不给 party 才是只切 SET。"""
    return _count_action_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_DIRECTION,
        _TICKET,
        "★滑方向不能反★左滑（600→200）= Party +1、右滑（200→600）= Party −1（FakeScreen 按真机口径"
        "驱动读数）；滑动行 y 必须取自 read_team 的 SET 框中心（不许写死 465）；正常换队不点屏幕",
        probe_party_swipe_direction,
    ),
    (
        HOOK_ID_TRIPLE,
        _TICKET,
        "★三重校验缺一即失败★SET 不变 ∧ Party == target ∧ 战力变化，三者同时成立才算成功；"
        "SET 变了 / Party 没到 / 战力没变 三个剧本各跑纯函数与全流程，都要 False 且失败日志带量",
        probe_party_triple_check,
    ),
    (
        HOOK_ID_BOUND,
        _TICKET,
        "★有界★|Δ| > TEAM_PARTY_SWIPE_MAX(12) ⇒ 一步不滑、直接带量失败；|Δ| == 12 允许滑满 "
        "（有界 ≠ 一律拒动）；目标 Party 越界不动",
        probe_party_swipe_bounded,
    ),
    (
        HOOK_ID_SEAMS,
        _TICKET,
        "★接缝★已在目标 ⇒ 幂等成功不滑；没有 swipe_hook ⇒ 带原因失败；read_hook 可独立注入；"
        "读数异常留痕不崩；第 1 次一步没动且给了 tap_hook 时只轻点一次 SET 框中心，默认绝不盲点",
        probe_party_switch_seams,
    ),
    (
        HOOK_ID_CONSTANTS,
        _TICKET,
        "★常量真源★6 个 TEAM_PARTY_* 常量在 scene/team.py（真源）；agent 侧只剩逐字冻结快照 "
        "_TEAM_PARTY_*_SNAPSHOT，运行时读真源。真源 == 快照（值+类型逐字）== 运行时，"
        "且等于真机 394eb66 的标定值 —— 任何一侧改动都红",
        probe_party_constants_source_of_truth,
    ),
    (
        HOOK_ID_WIRING,
        _TICKET,
        "★动作接线★TeamSwitchBattleAction 在 A 类页 + 目标 Party ⇒ 调 switch_party（假 IO 计数："
        "真滑到目标、零点击，绝不退回「点 SET 条」）；非 A 类页 / 读不到编队 ⇒ 零调用（旧「拒动」"
        "保留的一半）；三重校验不过 ⇒ 不打印成功",
        probe_party_action_wiring,
    ),
    (
        HOOK_ID_TARGET_BOUNDS,
        _TICKET,
        "★越界一步不滑★switch_party(0/11/99) ⇒ 零滑动、零读数、False、日志含「一步没滑」"
        "（老缺陷：从 Party 10 起为 11 滑了 11 次还把轮播留在别处）；★默认绝不夹紧★"
        "switch_party(11) 不许 True；只有显式 clamp=True 才夹到 1..TEAM_PARTY_COUNT 并打印夹紧结果",
        probe_party_target_bounds,
    ),
    (
        HOOK_ID_ALPHABET,
        _TICKET,
        "★队数与字母表★TEAM_PARTY_COUNT == 10（真机 1..10 环形轮播）且 "
        "len(TEAM_PARTY_LETTERS) == TEAM_PARTY_COUNT（真源 + agent 运行时两侧）；party_ordinal "
        "A..J == 1..10，Party I/J 在 read_team 里不许退化成「读不到 Party」；GUI 值域另算"
        "（TEAM_OPTION_PARTIES，interface.json 只有 1..6）",
        probe_party_alphabet_count,
    ),
    (
        HOOK_ID_COUNT_ACTIONS,
        _TICKET,
        "★动作队数★team_switch / team_switch_battle 的 1..10 全部放行（#124 真缺陷：7..10 被拒），"
        "显式 party=0 / 越界（11/99）拒动且零 IO（不 OCR / 不抓帧 / 不点 / 不滑）；"
        "不给 party 才是旧「只切 SET」；端到端 Party 7→10 / 10→7 都能切到",
        probe_party_count_actions,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（全部在内存里做；退出必定还原）
# ---------------------------------------------------------------------------
def _record(name: str, msgs: list, checks: list, focus: str = "") -> None:
    """记一条破坏实验：``msgs`` 非空 = 守卫成功变红。

    ``focus`` 用来挑一条**最能说明这次破坏**的消息打印（多条同时红时，别只显示第一条）。
    """
    red = bool(msgs)
    first = next((m for m in msgs if focus and focus in m), msgs[0] if msgs else "")
    checks.append((name, red, first))
    print(
        f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}"
        + (f"  {first}" if first else "")
    )


def _prove_red_checks() -> list:
    ti = _impl()
    checks: list = []

    # ① 滑动方向写反：+1 给右滑几何、−1 给左滑几何
    real_geometry = ti.party_swipe_geometry

    def _reversed_geometry(direction, row_y):
        x_from, x_to, y = real_geometry(-int(direction), row_y)
        return x_from, x_to, y

    try:
        ti.party_swipe_geometry = _reversed_geometry
        _record("① 滑动方向写反（+1 变右滑 / −1 变左滑）", _direction_failures(), checks)
    finally:
        ti.party_swipe_geometry = real_geometry

    # ② 去掉三重校验（恒成功）
    real_verify = ti.verify_party_switch
    try:
        ti.verify_party_switch = lambda _origin, _final, _target: (True, [])
        _record("② 去掉三重校验（verify_party_switch 恒 (True, [])）", _triple_failures(), checks)
    finally:
        ti.verify_party_switch = real_verify

    # ③ 去掉有界（上限常量还是 12，但「越界就拒滑」的判据恒真）
    real_gap_ok = ti.party_swipe_gap_ok
    try:
        ti.party_swipe_gap_ok = lambda _gap: True
        _record("③ 去掉有界（party_swipe_gap_ok 恒 True）", _bound_failures(), checks)
    finally:
        ti.party_swipe_gap_ok = real_gap_ok

    # ④ 滑动行 y 写死 465（不取 SET 框）
    real_row_y = ti._set_row_y
    try:
        ti._set_row_y = lambda _reading: 465
        _record("④ 滑动行 y 写死 465（不取 SET 框）", _direction_failures(), checks)
    finally:
        ti._set_row_y = real_row_y

    # ⑤ 常量改值：agent 快照改一次 / scene 真源改一次（两侧都要能抓）
    snap_name = "_TEAM_PARTY_SWIPE_MS_SNAPSHOT"
    real_snap = getattr(ti, snap_name)
    try:
        setattr(ti, snap_name, 999)
        _record("⑤a agent 快照 TEAM_PARTY_SWIPE_MS 改成 999", _constants_failures(), checks, focus="快照漂移")
    finally:
        setattr(ti, snap_name, real_snap)

    sc = _scene()
    real_scene_ms = sc.TEAM_PARTY_SWIPE_MS
    try:
        sc.TEAM_PARTY_SWIPE_MS = 999
        _record(
            "⑤b 真源 scene/team.py 的 TEAM_PARTY_SWIPE_MS 改成 999",
            _constants_failures(),
            checks,
            focus="快照漂移",
        )
    finally:
        sc.TEAM_PARTY_SWIPE_MS = real_scene_ms

    # ⑥ 动作退回「点 SET 条」：switch_party 换成点圆点（返回 True，假装成功）
    real_switch = ti.switch_party

    def _click_set_strip(target, **_kwargs):
        ti._click_box(None, 113, ti.TEAM_BATTLE_SET_ROW_Y)
        return True

    try:
        ti.switch_party = _click_set_strip
        _record("⑥ 动作退回「点 SET 条」（switch_party 换成点圆点）", _wiring_failures(), checks, focus="点了屏幕")
    finally:
        ti.switch_party = real_switch

    # ⑦ 非 A 类页也调 switch_party（页判据恒真）
    real_page = ti.is_battle_team_page
    try:
        ti.is_battle_team_page = lambda _items, _hit_keys=(): True
        _record("⑦ 非 A 类页也调 switch_party（页判据恒真）", _wiring_failures(), checks, focus="也调了 switch_party")
    finally:
        ti.is_battle_team_page = real_page

    # ⑧ 切完不校验：照样滑到目标，但**跳过三重校验恒返回 True**（「到了就算成功」）
    def _slide_without_verify(target, **_kwargs):
        read = _kwargs.get("read_hook")
        swipe = _kwargs.get("swipe_hook")
        cur = ti.to_team_reading(read())
        gap = int(target) - int(cur.party)
        for _step in range(abs(gap)):
            direction = 1 if gap > 0 else -1
            x_from, x_to, y = ti.party_swipe_geometry(direction, ti._set_row_y(cur))
            swipe(x_from, x_to, y, int(ti.TEAM_PARTY_SWIPE_MS))
            cur = ti.to_team_reading(read())
        return True

    try:
        ti.switch_party = _slide_without_verify
        _record("⑧ 切完不校验（滑到就算成功，三重校验被跳过）", _wiring_failures(), checks, focus="战力没变")
    finally:
        ti.switch_party = real_switch

    # ⑨ 越界检查放到滑动之后（老缺陷形态：先滑 |Δ| 次，再判目标是否存在）→ 挂点 7 红
    def _bounds_after_swipe(target, **kwargs):
        read = kwargs.get("read_hook")
        swipe = kwargs.get("swipe_hook")
        cur = ti.to_team_reading(read() if read is not None else ti._default_read_state())
        if cur is None or not cur.readable:
            return False
        want = int(target)
        row_y = ti._set_row_y(cur)
        gap = want - int(cur.party)
        if swipe is not None and row_y is not None and gap:
            direction = 1 if gap > 0 else -1
            for _step in range(abs(gap)):
                x_from, x_to, y = ti.party_swipe_geometry(direction, row_y)
                swipe(x_from, x_to, y, int(ti.TEAM_PARTY_SWIPE_MS))
        if not ti.party_target_ok(want):
            print(
                f"[team_party] ✗ 目标 Party {want} 不存在（真机轮播 1..{ti.TEAM_PARTY_COUNT}）"
                f"—— 一步没滑"
            )
            return False
        return True

    try:
        ti.switch_party = _bounds_after_swipe
        _record("⑨ 越界检查放到滑动之后（先滑再判）", _target_bounds_failures(), checks, focus="滑了")
    finally:
        ti.switch_party = real_switch

    # ⑩ 默认夹紧（不显式要求也把 11 夹成 10 再切）→ 挂点 7 红（静默错队）
    def _default_clamp(target, **kwargs):
        kwargs.pop("clamp", None)
        return real_switch(ti.clamp_party_target(target), **kwargs)

    try:
        ti.switch_party = _default_clamp
        _record("⑩ 默认夹紧（switch_party(11) 静默夹成 10）", _target_bounds_failures(), checks, focus="静默夹紧")
    finally:
        ti.switch_party = real_switch

    # ⑪ 字母表退回 8 个（Party I/J 读不出）→ 挂点 8 红
    real_scene_letters = sc.TEAM_PARTY_LETTERS
    real_ti_letters = ti.TEAM_PARTY_LETTERS
    try:
        sc.TEAM_PARTY_LETTERS = "ABCDEFGH"
        ti.TEAM_PARTY_LETTERS = "ABCDEFGH"
        _record(
            "⑪ 字母表退回 8 个（Party I/J 退化成「读不到 Party」）",
            _alphabet_failures(),
            checks,
            focus="字母表",
        )
    finally:
        sc.TEAM_PARTY_LETTERS = real_scene_letters
        ti.TEAM_PARTY_LETTERS = real_ti_letters

    # ⑫ TEAM_PARTY_COUNT 退回 6（7..10 又被两个动作拒）→ 挂点 8/9 红
    real_scene_count = sc.TEAM_PARTY_COUNT
    real_ti_count = ti.TEAM_PARTY_COUNT
    try:
        sc.TEAM_PARTY_COUNT = 6
        ti.TEAM_PARTY_COUNT = 6
        _record(
            "⑫ TEAM_PARTY_COUNT 退回 6（7..10 又会被拒）",
            _alphabet_failures() + _count_action_failures(),
            checks,
            focus="TEAM_PARTY_COUNT",
        )
    finally:
        sc.TEAM_PARTY_COUNT = real_scene_count
        ti.TEAM_PARTY_COUNT = real_ti_count
    return checks


def prove_red() -> bool:
    """真实绿；十二条破坏实验各自如愿变红。"""
    print("hooks_124 prove-red：逐一破坏实现，要求九个挂点各自变红")
    green = (
        probe_party_swipe_direction()
        and probe_party_triple_check()
        and probe_party_swipe_bounded()
        and probe_party_switch_seams()
        and probe_party_constants_source_of_truth()
        and probe_party_action_wiring()
        and probe_party_target_bounds()
        and probe_party_alphabet_count()
        and probe_party_count_actions()
    )
    print(
        f"  [{'PASS' if green else 'FAIL'}] 真实实现：方向 / 三重校验 / 有界 / 接缝 / 常量真源 / "
        f"动作接线 / 目标越界 / 队数字母表 / 动作队数（绿）"
    )
    if not green:
        for msg in (
            _direction_failures()
            + _triple_failures()
            + _bound_failures()
            + _seam_failures()
            + _constants_failures()
            + _wiring_failures()
            + _target_bounds_failures()
            + _alphabet_failures()
            + _count_action_failures()
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
    # 套件跑器 / 手工都允许带 --run-prove-red（行为一致：跑 prove_red）
    raise SystemExit(0 if prove_red() else 1)
