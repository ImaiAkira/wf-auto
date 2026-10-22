# -*- coding: utf-8 -*-
"""#116：两个真机 bug —— ①模式页「单人/多人」两张卡；②共斗房「挑战」7 连点。

## ① `WuchongModeSolo` 点进共斗房（假安全）

真机日志（``debug/wuchong_agent.log``）：
```
07:17:55 [wuchong_act] state=wuchong_mode 点击 '多人游戏' @720(437,866)   → 进共斗房
```
★归因当场核过，票面说法要比直觉更精确★：那一枪的框架行是
``[node_name=WuchongModeMulti] [param.custom_param={"what":["^多人游戏$"],...}]``
（``debug/maafw.bak.2026.10.18-07.20.11.63.log`` 07:17:55.291）—— 那次的「游戏模式」是**默认值多人**，
所以 `WuchongModeMulti` 点多人**是对的**。**但结构病是真的，而且正是本票要钉的**：

* 两个模式节点的**识别完全同形** —— 都只认 ``wuchong_state == wuchong_mode``，而
  ``classify()`` 第 8 条是「屏幕上有『单人游戏』**或**『多人游戏』即判模式页」⇒
  **站在模式页上，两个节点都命中**；谁被选中只取决于「另一张卡有没有被 options override 关成
  ``__NONE__``」。于是**单人路径 = 「关掉多人」实现**的 —— `WuchongModeSolo` 自己从没被单独验证过。
  override 一失效（选项没应用 / 新入口没带 override），单人链路就静默走进共斗房
  （真机 07:45 的 ``leg_b`` 就是这样又开了一局）。
* 更进一步：**「只有一个卡片在屏」的帧**（进页动画 / 半屏 / OCR 只读到一张）照样算模式页 ⇒
  节点在下**它自己那颗按钮根本不存在**的页面上被派中。这正是「假安全」的形状。

修法（两条，都是「只点自己」）：
1. **识别**加自己那张卡的标题串（``WuchongModeSolo`` = And[``WuchongModeState``, ``WuchongSoloText``]，
   多人卡对称）—— 只看到「多人游戏」的帧上 `WuchongModeSolo` **不命中**（本模块的反例断言）；
2. **点击**除了 ``what`` 整串锚定（``^单人游戏$`` 不可能匹配「多人游戏」，也不会误吃多人卡里被 OCR
   拆成两半的「多人」「游戏」子框）之外，再加**相对位置判据** ``above``：目标中心必须在同一份 OCR
   结果集合里「多人游戏」框的**上方 ≥200px**。这是**独立于字符串**的第二道证据 ——
   OCR 把多人卡的标题读成「单人游戏」时，位置仍然能证伪它。几何是真机帧实测（三帧一致，
   720 空间：单人卡 [78,497,184,52] 中心 (170,523)、多人卡 [345,840,184,52] 中心 (437,866)，Δy≈343）。

## ② `WuchongCoopChallenge` 在空房间里连点 7 次「挑战」

真机（``debug/wuchong_agent.log`` 07:18:14–07:18:45）每次都是
``点击 '挑战' @720(338,919)`` + ``[!] 校验未通过：点击后 state=loading``，共 **7 次**。

★票面第 4 问的明确答案★：``WuchongActAction.run()`` **内部没有任何重试循环** ——
「抓帧 → 定位 → **点一次** → 等 ``wait_ms`` → 抓帧 → 校验 → return」，一次 enter 一次点击。
证据是框架日志里同样 **7 行** ``node_name=WuchongCoopChallenge`` 的 ``CustomAction::run ... | enter``
（07:18:14/19/24/29/35/40/45 —— 与 agent 日志的 7 次点击一一对应）。⇒ 狂点是**节点被反复命中**
（房间页下一轮又把 `WuchongCoopChallenge` 排在候选最前），修法只能是**跨命中**的时间闩，
而不是「动作内部改成只点一次」（它本来就是只点一次）。

落地：``latch: coop_challenge``（新闩名，不与编队页的 ``battle_start`` 共享时间戳 ——
那是**两颗不同的按钮**）。窗口 = ``COOP_CHALLENGE_LATCH_S`` = **8.0s**：
★实测推翻票面「2.5–3s」的建议值★ —— 房间页一轮的重复周期实测 **5.2s**（14→19→24→29→35→40→45），
而闩锁判据是「距上次点击 < 窗口 ⇒ 不点」；窗口 3s < 周期 5.2s ⇒ **每一轮都放行**，闩锁形同虚设
（绿着但不改变真机行为 = 又一处假安全）。8s = 实测周期的 1.5 倍；代价是人齐那一下最多多等 8s
（房间总容忍 ``room_wait_sec``=300s）。★本守卫钉下限 6s★，窗口调到 3s 会红。

## 守卫（两条）+ 破坏实验

* ``wuchong-mode-solo-is-solo``：what 不含「多人」/ 与真源一致 / **反例帧（只有多人）不命中且不点** /
  点击落点 == 单人框中心 (170,523)（= 真机 10 连打里每一次的实际落点）/ 对调帧（多人跑到上面）拒绝点击。
* ``wuchong-coop-challenge-latch``：pipeline 挂闩 + 真源/agent/快照三处一致 + 窗口 ≥6s +
  **注入时钟**验「窗口内连续两轮只点一次」「超窗可再点」「一次 enter 只点一下」。

破坏实验（``python tools\\contract_hooks\\hooks_116.py``）：
① what 加回「多人」→ 红；② 去掉 ``above`` 位置判据 → 红；③ 识别退回「只认 state」→ 红；
④ 摘掉 ``latch`` → 红；⑤ 窗口设 0 → 红。
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"
PIPELINE_REL = Path("assets") / "resource" / "pipeline" / "wuchong.json"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _pipeline(root: Path | None = None) -> dict:
    import jsonc  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    with open(base / PIPELINE_REL, encoding="utf-8") as f:
        return jsonc.load(f)


def _acp(node: dict) -> dict:
    """节点的 ``action.param.custom_action_param``。"""
    return ((node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}


# ---------------------------------------------------------------------------
# 真机帧 fixture（★全部来自仓内真机帧的 OCR 结果，不是编的★）
# ---------------------------------------------------------------------------
#: 模式页完整帧（720 空间）。来源：``leg_c2_multi_from_stale_sample002_wuchong_mode.png``
#: （720x1280 原始帧，2026-10-18 07:17:5x，与 ``wuchong_agent.log`` 07:17:55 那次点击同一次会话）。
#: 同一页的三帧交叉核对（逐项差 ≤2px）：
#:   · ``leg_c3_room_sample010_wuchong_mode.png``：单人游戏 [78,497,184,52] / 多人游戏 [342,832,204,57]
#:   · ``tools/frames/lord_mode_select.png``（1080p，÷1.5）：[117,746,276,78]→[78,497,184,52] /
#:     [516,1258,276,76]→[344,839,184,51]
MODE_PAGE_ITEMS: tuple[tuple[str, list], ...] = (
    ("返回", [30, 1246, 46, 26]),
    ("五重決战", [225, 265, 271, 76]),
    ("深界连战", [295, 329, 119, 33]),
    ("单人游戏", [78, 497, 184, 52]),
    ("单人挑战领主", [76, 573, 138, 28]),
    ("多人", [248, 869, 61, 37]),
    ("游戏", [255, 896, 75, 42]),
    ("多人游戏", [345, 840, 184, 52]),
    ("建立房间", [344, 914, 96, 28]),
    ("召集同伴挑战领主", [345, 938, 187, 28]),
    ("领主性能和可获得的报酬", [250, 1105, 245, 23]),
    ("可能随挑战人数有所不同", [248, 1133, 248, 27]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [276, 1246, 46, 27]),
    ("商店", [397, 1245, 45, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [635, 1245, 47, 31]),
)

#: ★反例帧★：把模式页上**所有单人字样**删掉（只剩「多人游戏」那张卡 + 页面 chrome）。
#: 这条最要紧 —— 它能抓住「两个都点」的退化：`classify()` 仍然判 ``wuchong_mode``（第 8 条是「或」），
#: 所以**只认 state 的识别会命中**；而「只点自己」的节点必须既不命中、也不点。
MODE_MULTI_ONLY_ITEMS: tuple[tuple[str, list], ...] = tuple(
    (text, list(box)) for text, box in MODE_PAGE_ITEMS if "单人" not in text
)

#: ★对调帧★：两张卡的框上下互换（多人卡跑到上面去）。
#: 只用来看守「相对位置判据是不是承重的」：字符串仍然只有一颗「单人游戏」，但它**不在**多人卡上方 ⇒
#: 判据必须拒绝点击（位置证伪了字符串）。
MODE_INVERTED_ITEMS: tuple[tuple[str, list], ...] = tuple(
    (
        text,
        list([345, 840, 184, 52]) if text == "单人游戏" else (
            list([78, 497, 184, 52]) if text == "多人游戏" else list(box)
        ),
    )
    for text, box in MODE_PAGE_ITEMS
)

#: ★紧邻帧★：把多人卡标题**只上移一点**（840 → 680），两卡中心距 183px < 判据要求的 200px。
#: 用来钉「min_dy 这个数值本身」：只要它 > 0 就够拦「彻底颠倒」，但真机上两卡距离是 343px ——
#: 一个 183px 的帧说明**这一页根本不是实测那种布局**（缩放/滚动/别的活动页），必须拒绝点击。
MODE_TIGHT_ITEMS: tuple[tuple[str, list], ...] = tuple(
    (text, list([345, 680, 184, 52]) if text == "多人游戏" else list(box))
    for text, box in MODE_PAGE_ITEMS
)

#: 共斗房帧（真机 ``[297,906,81,46]`` 的「挑战」，中心 (337,929)，与 agent 日志 @720(338,919) 同框）。
ROOM_ITEMS: tuple[tuple[str, list], ...] = (
    ("返回", [30, 1246, 46, 26]),
    ("房间号码", [300, 300, 160, 30]),
    ("招募", [388, 828, 80, 40]),
    ("挑战", [297, 906, 81, 46]),
)

#: 点完一闪而过的转场帧（「挑战」是灰的时候点下去就是这样：闪一下 loading 又回房）。
LOADING_ITEMS: tuple[tuple[str, list], ...] = (
    ("健康游戏忠告", [200, 500, 300, 40]),
    ("返回", [30, 1246, 46, 26]),
)


def _center(box) -> tuple[int, int]:
    return (int(box[0] + box[2] / 2.0), int(box[1] + box[3] / 2.0))


# ---------------------------------------------------------------------------
# 识别树求值：给定一帧 OCR 结果，判「这个 pipeline 节点命中吗」
#
# 为什么不直接调框架：离线套件没有 Tasker（也不许连设备）。这里只实现本票用到的三种形态，
# **遇到不认识的形态一律记问题**（形态漂移要显形，绝不当成「命中/不命中」蒙过去）。
# ---------------------------------------------------------------------------
def _ocr_hits(expected, items) -> bool:
    pats = [str(p) for p in (expected or [])]
    if not pats:
        return False
    for text, _box in items:
        if any(re.search(p, text or "") for p in pats):
            return True
    return False


def _leaf_hits(leaf, pipes: dict, items, seen: set, problems: list) -> bool:
    if isinstance(leaf, str):
        if leaf in seen:
            problems.append(f"识别引用成环：{leaf}")
            return False
        seen.add(leaf)
        node = pipes.get(leaf)
        if not isinstance(node, dict):
            problems.append(f"识别引用了不存在的节点 {leaf!r}")
            return False
        return _reco_hits(node.get("recognition"), pipes, items, seen, problems)
    if isinstance(leaf, dict):
        inner = leaf.get("recognition")
        if isinstance(inner, dict):
            return _reco_hits(inner, pipes, items, seen, problems)
        if leaf.get("type"):
            return _reco_hits(leaf, pipes, items, seen, problems)
    problems.append(f"不认识的识别叶子：{leaf!r}")
    return False


def _reco_hits(rec, pipes: dict, items, seen=None, problems=None) -> bool:
    seen = set() if seen is None else seen
    problems = [] if problems is None else problems
    if not isinstance(rec, dict):
        problems.append(f"识别不是 dict：{rec!r}")
        return False
    typ = rec.get("type")
    param = rec.get("param") or {}
    if typ == "Custom":
        kind = param.get("custom_recognition")
        if kind != "wuchong_state":
            problems.append(f"守卫不认识 custom_recognition={kind!r}（识别形态漂移，必须补判据）")
            return False
        cap = param.get("custom_recognition_param") or {}
        import wuchong_impl as impl  # noqa: PLC0415

        state, _info = impl.classify(items)
        return state == cap.get("state")
    if typ == "OCR":
        return _ocr_hits(param.get("expected"), items)
    if typ == "And":
        for leaf in param.get("all_of") or []:
            if not _leaf_hits(leaf, pipes, items, seen, problems):
                return False
        return True
    problems.append(f"守卫不认识识别类型 {typ!r}（形态漂移，必须补判据）")
    return False


def _hits(node_name: str, pipes: dict, items) -> tuple[bool, list]:
    problems: list = []
    node = pipes.get(node_name)
    if not isinstance(node, dict):
        return False, [f"pipeline 里没有 {node_name}（守卫与实现脱节）"]
    got = _reco_hits(node.get("recognition"), pipes, items, problems=problems)
    return got, problems


# ---------------------------------------------------------------------------
# 行为层：驱动真实的 WuchongActAction（抓屏/OCR/点击全部 monkeypatch，零设备）
# ---------------------------------------------------------------------------
class _CtxStub:
    """最小 context 桩（动作只经被 monkeypatch 的抓屏/OCR/点击）。"""


class _ActArgv:
    def __init__(self, param):
        self.custom_action_param = json.dumps(param)


class _SeqOCR:
    def __init__(self, frames):
        self.frames = [list(f) for f in frames]
        self.calls = 0

    def __call__(self, context, image, entry="OcrTask"):
        i = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return [tuple(x) for x in self.frames[i]]


class _Clock:
    """注入时钟：动作里的 ``time.monotonic`` / ``time.sleep`` 全走它。

    为什么必须注入：真机的房间循环周期是 **5.2s**，而闩锁窗口是 8s ——
    用真时钟要等 8 秒才能验「超窗可再点」，套件里不可接受；而且「连续两轮只点一次」用真时钟
    会**碰巧**通过（真实间隔本来就 > 窗口）。注入后时间完全可控：窗口内的判定与窗口外的判定
    都是确定性的。
    """

    def __init__(self, t0: float = 5000.0):
        self.t = float(t0)
        self.sleeps: list = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds) -> None:
        self.sleeps.append(float(seconds))
        self.t += max(0.0, float(seconds))

    def advance(self, dt: float) -> None:
        self.t += float(dt)


class _FakeTime:
    """``mod.time`` 的替身（只覆盖动作路径用到的入口；日志时间戳仍走真时钟）。"""

    def __init__(self, clock: _Clock, real):
        self._clock = clock
        self._real = real

    def monotonic(self) -> float:
        return self._clock.monotonic()

    def sleep(self, seconds) -> None:
        self._clock.sleep(seconds)

    def strftime(self, fmt, *args):
        return self._real.strftime(fmt, *args)

    def time(self) -> float:
        return self._real.time()


@contextlib.contextmanager
def _sandbox(mod):
    """临时账本 + 临时日志：驱动真实动作时**绝不写仓里的 progress.json / debug 日志**。"""
    saved_ledger = getattr(mod.ledger, "_DEFAULT", None)
    saved_log = mod.__dict__.get("_LOG_PATH")
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p.json")
        mod._LOG_PATH = Path(td) / "agent.log"
        try:
            with mod._LOCK:
                mod._SESSION["task_id"] = 571_160_001
                for name in ("coop_challenge", "battle_start", "recruit_start", "recruit_open"):
                    mod._SESSION[f"latch_ts_{name}"] = 0.0
            yield
        finally:
            mod.ledger.set_file(None)
            mod._LOG_PATH = saved_log
            if saved_ledger is not None:
                mod.ledger._DEFAULT = saved_ledger


def _drive(mod, frames, param, clock: _Clock | None = None):
    """跑一次 ``WuchongActAction.run``，返回 (点击列表, stdout)。"""
    clicks: list = []
    saved = {k: mod.__dict__[k] for k in ("_grab", "_ocr", "_click_box")}
    saved_time = mod.__dict__.get("time")
    seq = _SeqOCR(frames)
    buf = io.StringIO()
    try:
        mod._grab = lambda context: ("frame", seq.calls)
        mod._ocr = seq
        mod._click_box = lambda context, cx, cy: (clicks.append((int(cx), int(cy))) or True)
        if clock is not None and saved_time is not None:
            mod.time = _FakeTime(clock, saved_time)
        with contextlib.redirect_stdout(buf):
            mod.WuchongActAction().run(_CtxStub(), _ActArgv(param))
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        if saved_time is not None:
            mod.time = saved_time
    return clicks, buf.getvalue()


# ---------------------------------------------------------------------------
# 守卫 ①：模式页 —— 单人卡只点自己
# ---------------------------------------------------------------------------
#: fixture 与真源几何的容差（三帧实测逐项差 ≤2px；给 3px 余量，只抓「换了一张卡」级别的漂移）。
_BOX_TOL = 3


def _mode_solo_failures(root: Path | None = None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _pipeline(root)
    node = pipes.get("WuchongModeSolo")
    if not isinstance(node, dict):
        return ["pipeline 里没有 WuchongModeSolo（守卫与实现脱节）"]
    cp = _acp(node)
    what = [str(x) for x in (cp.get("what") or [])]

    # ---- ① what 只许匹配「单人」 ----
    if not what:
        msgs.append(
            "WuchongModeSolo.what 为空 —— 空 what 会点任意一个 OCR 框（模式页上第一个框就是别的卡）"
        )
    solo_patterns = [str(x) for x in (getattr(w, "SOLO_PATTERNS", ()) or ())]
    if solo_patterns != what:
        msgs.append(
            f"WuchongModeSolo.what={what!r} != 真源 scene.wuchong.SOLO_PATTERNS={solo_patterns!r}"
            "（点击判据必须来自真源，不许在 JSON 里另写一份）"
        )
    for pat in what:
        if w.MULTI_TEXT in pat:
            msgs.append(
                f"WuchongModeSolo.what 含「多人」：{pat!r} —— 模式页上「多人游戏」是**另一张卡**，"
                "点它就是走进共斗房（真机 07:17:55 就是这样进的房；这是本票的第一条红线）"
            )
        try:
            if re.search(pat, w.MULTI_TEXT):
                msgs.append(
                    f"WuchongModeSolo.what 的正则 {pat!r} 能匹配「{w.MULTI_TEXT}」"
                    "（= 两张卡都能点：这就是要抓的「两个都点」退化）"
                )
        except re.error as exc:
            msgs.append(f"WuchongModeSolo.what 的正则非法：{pat!r}（{exc}）")
    # 反向：整条 what 必须**真的**点得到单人（别写成一条谁都不匹配的死正则）。
    alive = False
    for pat in what:
        try:
            if re.search(pat, w.SOLO_TEXT):
                alive = True
        except re.error:
            continue
    if what and not alive:
        msgs.append(f"WuchongModeSolo.what={what!r} 里没有任何一条能匹配「{w.SOLO_TEXT}」（永远点不到目标）")

    # ---- fixture 与真源几何对账（两份数据不得漂移）----
    fixture_solo = [list(b) for t, b in MODE_PAGE_ITEMS if t == w.SOLO_TEXT]
    fixture_multi = [list(b) for t, b in MODE_PAGE_ITEMS if t == w.MULTI_TEXT]
    for label, fixtures, truth in (
        ("MODE_SOLO_BOX", fixture_solo, list(w.MODE_SOLO_BOX)),
        ("MODE_MULTI_BOX", fixture_multi, list(w.MODE_MULTI_BOX)),
    ):
        if len(fixtures) != 1:
            msgs.append(f"fixture 里「{label}」对应的框不唯一：{fixtures!r}")
            continue
        got = fixtures[0]
        if any(abs(int(a) - int(b)) > _BOX_TOL for a, b in zip(got, truth)):
            msgs.append(
                f"fixture 框 {got!r} 与真源 {label}={truth!r} 差 >{_BOX_TOL}px"
                "（真机帧与真源几何脱节，先重新标定再谈判据）"
            )

    # ---- ② 反例帧：只有「多人游戏」→ 该节点**不命中** ----
    hit_neg, probs = _hits("WuchongModeSolo", pipes, MODE_MULTI_ONLY_ITEMS)
    msgs.extend(f"反例帧识别求值：{p}" for p in probs)
    if hit_neg:
        msgs.append(
            "★反例失败★ 只有「多人游戏」的帧上 WuchongModeSolo **命中了** —— 说明识别只认 "
            "wuchong_state（classify 第 8 条对单人/多人是「或」），节点会被派到一张**自己的按钮不存在**"
            "的页面上（假安全）。识别必须是 And[wuchong_state, 自己那张卡的标题串]"
        )
    hit_pos, probs_pos = _hits("WuchongModeSolo", pipes, MODE_PAGE_ITEMS)
    msgs.extend(f"正例帧识别求值：{p}" for p in probs_pos)
    if not hit_pos:
        msgs.append("正例帧（真机模式页，两张卡都在）上 WuchongModeSolo 不命中（识别门写死了 / fixture 坏了）")
    hit_multi_neg, probs_mn = _hits("WuchongModeMulti", pipes, MODE_MULTI_ONLY_ITEMS)
    msgs.extend(f"反例帧（多人）识别求值：{p}" for p in probs_mn)
    if not hit_multi_neg:
        msgs.append(
            "反例帧上 WuchongModeMulti 必须命中（多人卡在屏上，它就是该动的那一支）；"
            "它不命中说明多人卡的识别门写错了"
        )

    # ---- ③ 点击落点必须是「单人」框中心（行为层；最下面那道防线）----
    expected_solo = _center(w.MODE_SOLO_BOX)
    mod = _impl()
    with _sandbox(mod):
        clicks, out = _drive(mod, [MODE_PAGE_ITEMS], cp, clock=_Clock())
        if clicks != [expected_solo]:
            msgs.append(
                f"真机模式页帧上 WuchongModeSolo 的点击落点 {clicks!r} != 单人框中心 {expected_solo!r}"
                f"（真机 10 连打每一次都是 @720{expected_solo}）；日志尾巴：{out.strip().splitlines()[-1:]!r}"
            )
        # 反例帧的行为层：即使识别被绕过（动作被直接调用），也**不许**点任何东西。
        # 这是「最下面一道防线」——识别门失效时，动作自己也不许盲点。
        clicks_neg, out_neg = _drive(mod, [MODE_MULTI_ONLY_ITEMS], cp, clock=_Clock())
        if clicks_neg:
            msgs.append(
                f"★反例失败★ 只有「多人游戏」的帧上动作点了 {clicks_neg!r} —— 动作层没有守住"
                f"「只点单人」（真机后果 = 进共斗房）；日志：{out_neg.strip().splitlines()[-1:]!r}"
            )
        # ---- ④ 相对位置判据：承重且与真源一致 ----
        above = cp.get("above")
        if not isinstance(above, dict) or not above:
            msgs.append(
                "WuchongModeSolo.custom_action_param 缺 above 相对位置判据 —— 只靠字符串时，"
                "OCR 把多人卡标题读成「单人游戏」就再也拦不住（真源 scene.wuchong.SOLO_ABOVE）"
            )
        else:
            ref_what = [str(x) for x in (above.get("what") or [])]
            twin = [str(x) for x in (getattr(w, "MULTI_PATTERNS", ()) or ())]
            if ref_what != twin:
                msgs.append(f"above.what={ref_what!r} != 真源 MULTI_PATTERNS={twin!r}")
            try:
                min_dy = int(above.get("min_dy") or 0)
            except (TypeError, ValueError):
                min_dy = -1
            if min_dy != int(w.MODE_MIN_SOLO_ABOVE_MULTI_DY):
                msgs.append(
                    f"above.min_dy={above.get('min_dy')!r} != 真源 {w.MODE_MIN_SOLO_ABOVE_MULTI_DY}"
                    "（实测 Δy≈343，取 200 留 42% 余量；该值必须来自真源）"
                )
            clicks_inv, out_inv = _drive(mod, [MODE_INVERTED_ITEMS], cp, clock=_Clock())
            if clicks_inv:
                msgs.append(
                    f"★位置判据失效★ 对调帧（多人卡在上、单人卡在下）上仍然点了 {clicks_inv!r} —— "
                    "那说明 above 没生效（字符串是对的、位置是错的 ⇒ 必须拒绝点击）；"
                    f"日志：{out_inv.strip().splitlines()[-1:]!r}"
                )
            if "位置判据" not in out_inv:
                msgs.append("对调帧的日志里没有「位置判据」痕迹（判据没跑到 / 被短路了）")
            # ``min_dy`` 这个**数值**也要承重：两卡只差 183px（< 200）时同样必须拒绝 ——
            # 那种帧不是实测布局（343px），说明页面换了/根本没到模式页。
            clicks_tight, out_tight = _drive(mod, [MODE_TIGHT_ITEMS], cp, clock=_Clock())
            if clicks_tight:
                msgs.append(
                    f"★位置判据阈值失效★ 两卡中心只差 183px（< 要求 {w.MODE_MIN_SOLO_ABOVE_MULTI_DY}px）"
                    f"的帧上仍然点了 {clicks_tight!r} —— min_dy 必须真的比实测间距（343px）留余量，"
                    f"不能形同 0；日志：{out_tight.strip().splitlines()[-1:]!r}"
                )
    return msgs


def _impl():
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return impl


def probe_wuchong_mode_solo_is_solo() -> bool:
    msgs = _mode_solo_failures()
    if msgs:
        print("  [116] 模式页「只点单人」不成立：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [116] 模式页：what 只匹配单人、反例帧（只有多人）不命中也不点、落点 == 单人框中心、位置判据承重")
    return True


# ---------------------------------------------------------------------------
# 守卫 ②：共斗房「挑战」—— 时间闩（跨命中）+ 单点
# ---------------------------------------------------------------------------
#: 窗口下限（秒）。★实测依据★：房间页一轮的重复周期 07:18:14→19→24→29→35→40→45 ≈ **5.2s**；
#: 窗口 ≤ 该周期 ⇒ 「距上次点击 < 窗口」永远不成立 ⇒ 闩锁形同虚设。取 6s 作下限（>5.2s 留余量），
#: 票面建议的 2.5–3s 低于它 ⇒ 红。
_MIN_COOP_WINDOW_S = 6.0


def _coop_latch_failures(root: Path | None = None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415
    import wuchong_impl as impl  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _pipeline(root)
    node = pipes.get("WuchongCoopChallenge")
    if not isinstance(node, dict):
        return ["pipeline 里没有 WuchongCoopChallenge（守卫与实现脱节）"]
    cp = _acp(node)
    latch = str(cp.get("latch") or "")

    # ---- ① 接线：pipeline 挂闩 + 真源 / agent 常量 / 安装态快照三处一致 ----
    if latch != w.COOP_CHALLENGE_LATCH:
        msgs.append(
            f"WuchongCoopChallenge 的 latch={latch!r} != 真源 {w.COOP_CHALLENGE_LATCH!r}"
            "（真机 07:18:14–45 在同一节点内连点 7 次「挑战」；没有闩锁这形态会回来）"
        )
    latches = tuple(getattr(impl.WuchongActAction, "_LATCHES", ()) or ())
    if w.COOP_CHALLENGE_LATCH not in latches:
        msgs.append(
            f"WuchongActAction._LATCHES 没登记 {w.COOP_CHALLENGE_LATCH!r}（在 pipeline 上写的 latch 名"
            "会被静默忽略 —— 有参数、没行为）"
        )
    windows = dict(getattr(impl.WuchongActAction, "_LATCH_WINDOWS", {}) or {})
    window = float(windows.get(w.COOP_CHALLENGE_LATCH) or 0.0)
    if abs(window - float(w.COOP_CHALLENGE_LATCH_S)) > 1e-6:
        msgs.append(
            f"_LATCH_WINDOWS[{w.COOP_CHALLENGE_LATCH!r}]={window!r} != 真源 "
            f"COOP_CHALLENGE_LATCH_S={w.COOP_CHALLENGE_LATCH_S!r}"
        )
    if window < _MIN_COOP_WINDOW_S:
        msgs.append(
            f"闩锁窗口 {window}s < 下限 {_MIN_COOP_WINDOW_S}s —— 房间页一轮的实测重复周期是 5.2s，"
            "窗口必须**大于**它，否则每一轮都放行（闩锁绿着但不改变真机行为 = 假安全）"
        )
    live = float(getattr(impl, "COOP_CHALLENGE_LATCH_S", -1.0))
    if abs(live - float(w.COOP_CHALLENGE_LATCH_S)) > 1e-6:
        msgs.append(f"wuchong_impl.COOP_CHALLENGE_LATCH_S={live!r} 与真源漂移（安装态会失效）")
    snap = float(getattr(impl, "_COOP_CHALLENGE_LATCH_S_SNAPSHOT", -1.0))
    if abs(snap - float(w.COOP_CHALLENGE_LATCH_S)) > 1e-6:
        msgs.append(
            f"安装态快照 _COOP_CHALLENGE_LATCH_S_SNAPSHOT={snap!r} 与真源漂移"
            "（GUI 跑 install/agent 时就用了旧窗口）"
        )

    # ---- ② 行为：注入时钟 —— 窗口内连续两轮只点一次；超窗可再点 ----
    mod = impl
    with _sandbox(mod):
        clock = _Clock(5000.0)
        first, out1 = _drive(mod, [ROOM_ITEMS, LOADING_ITEMS], cp, clock=clock)
        if len(first) != 1:
            msgs.append(
                f"共斗房「挑战」一次 enter 点了 {len(first)} 下（应为 1 —— 动作里没有重试循环，"
                f"真机那 7 次是 7 次 enter）；日志：{out1.strip().splitlines()[-2:]!r}"
            )
        if first and first[0] != _center([297, 906, 81, 46]):
            msgs.append(f"「挑战」落点 {first!r} != 识别框中心 {_center([297, 906, 81, 46])!r}")
        # 同一窗口内再来一轮（真机实际是 ~5s 一轮，这里压到 1s 更严格）
        clock.advance(1.0)
        second, out2 = _drive(mod, [ROOM_ITEMS], cp, clock=clock)
        if second:
            msgs.append(
                f"★闩锁失效★ 窗口 {window}s 内第二次命中又点了 {second!r} —— "
                f"真机上就是 7 连点；日志：{out2.strip().splitlines()[-1:]!r}"
            )
        # 超窗：必须允许重试（否则人齐后永远点不到「挑战」= 多人永远开不了战）
        clock.advance(window + 0.5)
        third, out3 = _drive(mod, [ROOM_ITEMS], cp, clock=clock)
        if len(third) != 1:
            msgs.append(
                f"窗口过期（+{window + 0.5:.1f}s）后没有再点（{third!r}）—— 一次性闩锁会让"
                "「人齐」那一刻永远点不到挑战（真机 #83 的教训）；日志："
                f"{out3.strip().splitlines()[-1:]!r}"
            )
        if "闩锁" not in out2 and second:
            msgs.append("窗口内那一轮的日志里没有「闩锁」痕迹（判据没跑到？）")
    return msgs


def probe_wuchong_coop_challenge_latch() -> bool:
    msgs = _coop_latch_failures()
    if msgs:
        print("  [116] 共斗房「挑战」闩锁不成立：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print(
        "  [116] 共斗房「挑战」：latch=coop_challenge 三处一致、窗口 ≥6s、"
        "注入时钟下「窗口内只点一次 / 超窗可再点 / 一次 enter 只点一下」"
    )
    return True


HOOKS = [
    (
        "wuchong-mode-solo-is-solo",
        "#116",
        "模式页「只点单人」：WuchongModeSolo.what 只匹配 ^单人游戏$（含「多人」即红）、"
        "识别必须带自己那张卡的标题串（反例帧只有「多人游戏」⇒ 不命中且不点击）、"
        "落点 == 单人框中心 (170,523)、above 相对位置判据承重（对调帧拒绝点击）—— "
        "真机 07:17:55 走进共斗房的假安全：单人路径是「关掉多人」实现的",
        probe_wuchong_mode_solo_is_solo,
    ),
    (
        "wuchong-coop-challenge-latch",
        "#116",
        "共斗房「挑战」时间闩：latch=coop_challenge（真源 scene.wuchong ②e' + agent 常量 + 安装态快照"
        "三处一致）、窗口 ≥6s（实测房间循环 5.2s，票面 2.5–3s 不够）、注入时钟验"
        "「窗口内只点一次 / 超窗可再点」、一次 enter 只点一下 —— 真机 07:18:14–45 连点 7 次",
        probe_wuchong_coop_challenge_latch,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook116_"))
    (root / PIPELINE_REL).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / PIPELINE_REL, root / PIPELINE_REL)
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_116 prove-red：逐一破坏实现，要求守卫各自变红")
    green = probe_wuchong_mode_solo_is_solo() is True and probe_wuchong_coop_challenge_latch() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：两个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    def _break_pipeline(label: str, mutate, probe) -> None:
        root = _temp_pipeline()
        try:
            mutate(root / PIPELINE_REL)
            msgs = probe(root)
            red = len(msgs) > 0
            print(
                f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}"
                + (f"  {msgs[0]}" if msgs else "")
            )
            checks.append(red)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # ① 把「多人」加回 what（= 两张卡都能点；真机后果就是走进共斗房）
    _break_pipeline(
        "把 ^多人游戏$ 加回 WuchongModeSolo 的 what",
        lambda p: _sub(p, '"what": ["^单人游戏$"],', '"what": ["^单人游戏$", "^多人游戏$"],'),
        _mode_solo_failures,
    )

    # ② 去掉 above 相对位置判据（只剩字符串证据）
    _break_pipeline(
        "删掉 WuchongModeSolo 的 above 相对位置判据",
        lambda p: _sub(p, '"above": { "what": ["^多人游戏$"], "min_dy": 200 },', ""),
        _mode_solo_failures,
    )

    # ②b 把 above 的阈值压成 0（判据在、但不再要求两卡有实测那个间距 = 形同虚设）
    _break_pipeline(
        "把 above.min_dy 压成 0（位置判据形同虚设）",
        lambda p: _sub(p, '"min_dy": 200', '"min_dy": 0'),
        _mode_solo_failures,
    )

    # ③ 识别退回「只认 state」（反例帧上就会命中）
    _break_pipeline(
        "把 WuchongModeSolo 的识别退回「只认 wuchong_state」",
        lambda p: _sub(
            p,
            '"param": { "all_of": ["WuchongModeState", "WuchongSoloText"] }',
            '"param": { "all_of": ["WuchongModeState"] }',
        ),
        _mode_solo_failures,
    )

    # ④ 摘掉共斗房「挑战」的 latch（7 连点形态原样复活）
    _break_pipeline(
        "摘掉 WuchongCoopChallenge 的 latch=coop_challenge",
        lambda p: _sub(p, '                    "latch": "coop_challenge",\n', ""),
        _coop_latch_failures,
    )

    # ⑤ 窗口设 0（闩锁存在但永不生效 —— 「有参数、没行为」的最隐蔽形态）
    real_windows = dict(impl.WuchongActAction._LATCH_WINDOWS or {})
    try:
        broken_windows = dict(real_windows)
        broken_windows["coop_challenge"] = 0.0
        impl.WuchongActAction._LATCH_WINDOWS = broken_windows
        msgs = _coop_latch_failures()
        red5 = len(msgs) > 0
        print(
            f"  [{'PASS' if red5 else 'FAIL'}] 把 coop_challenge 的窗口设成 0s -> "
            f"{'红' if red5 else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
        checks.append(red5)
    finally:
        impl.WuchongActAction._LATCH_WINDOWS = real_windows

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
