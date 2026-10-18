# -*- coding: utf-8 -*-
"""#117：深渊在终始之战页「页签校验恒成立」死循环 + 空态不收工。

## 现场（真机A，2026-10-18 08:0x，跑 ``AbyssPlainEntry``）

::

    [abyss_act] state=activity 点击 '终始之战' → zhongshi
    [abyss_act] state=zhongshi 点击 '未通关' → 校验通过 zhongshi -> zhongshi
    [abyss_act] state=zhongshi 点击 '已通关' → 校验通过 zhongshi -> zhongshi
    [abyss_act] state=zhongshi 点击 '完成'   → 校验通过 zhongshi -> zhongshi
    （以上三连无限重复，直到人工停掉）

屏幕证据帧：``tools/frames/abyss_zhongshi_tabs.png``（**终始之战页，中间写「没有相关的活动」，
三个页签全空**；720 空间 OCR 侧车 = 同名 ``.ocr.txt``）。

## ① 页签校验恒成立（#19 同类：判据自证）

``AbyssNavTab`` 的 ``abyss_act`` 当时写 ``expect: ["zhongshi", "loading"]``，
``ok = state1 in expect`` —— 而**切二级页签时页面状态本来就该还是 zhongshi**：
判据的输入（当前 state）与判据本身（状态没变）是同一件事 ⇒ 恒成立 ⇒ 每次点击都"通过"。

正解（本票落地）：判据必须来自**页面给出的新证据**——
「点完后页签**内容区文本集合**必须变」（内容区 = ``scene.abyss.ZHONGSHI_CONTENT_BOX``，
页签栏 / 底导带都排除在外）。点到的页签本来就在选中态时内容区不变，那只记「一次无证据」：
**一整轮三页签都没证据 = 切换失败**，重试上限 = **1 轮**（``TAB_SWITCH_RETRY_LIMIT``，共 6 次），
之后 ``request_giveup(原因)`` 带原因退出（#19 的结论：不许多次重试）。

## ② 空态「没有相关的活动」必须收工

三个页签都没有内容时列表区写「没有相关的活动」。旧实现只认横幅，于是永远找不到、
永远在切页签。现在：每点一个页签就把「这个页签是空的」记一笔，**三个页签都记满** ⇒
收工原因是真源 ``scene.abyss.ZHONGSHI_EMPTY_REASON``：
``终始之战没有可打的关卡（三个页签均无内容）``。收工走**既有** ``abyss_giveup``
（``AbyssGiveUpRecognition`` 取走原因 → ``_mark_run_done`` → pipeline ``AbyssGiveUp`` ``StopTask``），
**不新造第二套收工语义**。

## ②b 顺带补上的第二条逃生路：整轮扫描上限

横幅节点排在切页签**之前**（只要横幅可见就不会再进 ``step=tab``），所以「还在切页签」等价于
「这一轮页签上都没有横幅」。**「账号有别的活动、没有深渊」**时，页签会一直切**成功**
（内容每轮都在变），①的「无证据」预算永远不触发 ⇒ 仍然无限切页签。所以再加一道：
切满 ``len(tabs) * TAB_SCAN_ROUND_LIMIT``（= 6 次 / 2 轮）还没被横幅节点接手 ⇒ 收工并说明
「终始之战扫过 2 轮页签都没有找到「深渊连战EX」横幅」。**这就是「账号没内容」在代码侧的答案**：
不静默空转，给运维一句明确的原因。

## 守卫（三条，冒烟口径）

* ``abyss-tab-switch-observable``：pipeline 的 ``step=tab`` 节点必须 ``validate=content_change``
  且**不许带任何 expect**（静态）；行为层用真机帧驱动真实 ``AbyssActAction``——
  内容区没变时**不许**出现「校验通过」，必须出现「切换未生效」，且三个页签各点一轮后
  能给出收工原因；内容真的变了才判「切换生效」。
* ``abyss-tab-retry-capped``：重试上限三处一致（真源 / 安装态快照 / pipeline）= **1**，
  ``tab_switch_budget`` = 6；行为层在「死点击」屏上**恰好点 6 次**就以「切换失败」收工
  （上限调大 ⇒ 点击数变多 ⇒ 红）；★整轮扫描上限★同理：三个页签**都有内容**但没有横幅时，
  切满 6 次必须收工并说明「没找到横幅」（第三条破坏实验打这条）；离开终始之战页必须复位页签账本。
* ``abyss-zhongshi-empty-giveup``：空态锚点必须来自**入库证据帧**（``.png`` + ``.ocr.txt`` 侧车，
  锚点在内容区内、``classify`` 判 zhongshi）；三处一致（真源 / 安装态快照 / pipeline）；
  行为层三个页签全空 ⇒ 恰 3 次点击后给出**空态原因**（不是「切换失败」），
  且 ``abyss_giveup`` 真的把它报出来（hit + reason）。**有内容的终始之战帧不得判空态**。

破坏实验（``python tools\\contract_hooks\\hooks_117.py``）：
① 把校验退回自证式（``expect: ["zhongshi","loading"]`` + 摘掉 validate）→ 红；
①b 判据函数退化成「永远 switched」→ 红；
② 重试上限改成 9（pipeline / 真源）→ 红；
②c 整轮扫描上限改成 99（pipeline / 真源）→ 红；
③ 摘掉 pipeline 的空态锚点 → 红；
③b 锚点改成一句不存在的字（= 空态识别失效）→ 红。
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"
PIPELINE_REL = Path("assets") / "resource" / "pipeline" / "abyss.json"

#: 真机证据帧 + 它的 720 空间 OCR 侧车（本仓惯例：帧与 ``.ocr.txt`` 同名同目录）。
EVIDENCE_FRAME = TOOLS / "frames" / "abyss_zhongshi_tabs.png"
EVIDENCE_OCR = TOOLS / "frames" / "abyss_zhongshi_tabs.ocr.txt"

_TICKET = "#117"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _impl():
    _paths()
    import abyss_impl as impl  # noqa: PLC0415

    return impl


def _scene():
    _paths()
    from scene import abyss as scene_abyss  # noqa: PLC0415

    return scene_abyss


def _pipeline(root: Path | None = None) -> dict:
    import jsonc  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    with open(base / PIPELINE_REL, encoding="utf-8") as f:
        return jsonc.load(f)


def _acp(node: dict) -> dict:
    """节点的 ``action.param.custom_action_param``。"""
    return ((node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}


def _tab_nodes(pipes: dict) -> list:
    """所有 ``abyss_act step=tab`` 的节点名（页签节点可能不止一个；一律受管辖）。"""
    return [
        name
        for name, node in (pipes or {}).items()
        if isinstance(node, dict) and _acp(node).get("step") == "tab"
    ]


# ---------------------------------------------------------------------------
# 真机帧 fixture：直接从入库侧车读（★锚点必须来自证据帧，不许凭空写★）
# ---------------------------------------------------------------------------
def _frame_items_from_sidecar(path: Path | None = None) -> list:
    """读 ``.ocr.txt`` 侧车 → ``[(text, [x, y, w, h])]``（格式与本仓其它侧车一致）。"""
    src = Path(path) if path is not None else EVIDENCE_OCR
    if not src.is_file():
        return []
    items = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        text, _, box = line.partition("\t")
        if not box:
            continue
        try:
            coords = json.loads(box.replace(" ", ""))
        except ValueError:
            continue
        if isinstance(coords, list) and len(coords) == 4:
            items.append((text, [int(v) for v in coords]))
    return items


#: 终始之战页签栏 + 空态锚点（真机帧的 720 空间读数；页签框中心就是点击落点）。
EMPTY_FRAME = _frame_items_from_sidecar()

#: 有内容的终始之战帧（**合成**，逐条照 ``docs/recon/abyss-calibration.md`` 对
#: ``04_zhongshi_tab_wancheng.png`` 的读数：「完成」页签里一条横幅 + 剩余天数）。
#: ★为什么是合成的★：入库帧里没有任何一张**有内容**的终始之战页（已扫过 tools/frames/ 全部帧），
#: 所以这条负例只能照 recon 的读数造，绝不冒充真机帧。
POPULATED_CONTENT: tuple[tuple[str, list], ...] = (
    ("深渊连战", [247, 485, 255, 65]),
    ("ABYSS ONSLAUGHT", [283, 560, 180, 16]),
    ("还有365天以上", [500, 640, 120, 24]),
)


def _tab_label(name: str):
    """真机帧里某个页签的 OCR 项（找不到返回 None）。"""
    for text, box in EMPTY_FRAME:
        if text == name:
            return (text, list(box))
    return None


def _frame_with(*extra) -> list:
    """页签栏 + 底部导航（真机帧原样）+ 该页签的内容区条目。"""
    base = [
        (text, list(box))
        for text, box in EMPTY_FRAME
        if text in ("终始之战", "BATTLE ÓF ORIGINS", "未通关", "已通关", "完成")
        or box[1] >= 1200  # 底部导航带
    ]
    base.extend((text, list(box)) for text, box in extra)
    return base


def _empty_tab_frame() -> list:
    """空页签的帧：页签栏 + 空态锚点（真机帧那一句，坐标原样）。"""
    anchor = [(t, b) for t, b in EMPTY_FRAME if "没有相关的活动" in t]
    return _frame_with(*anchor)


def _content_tab_frame() -> list:
    """有内容的页签的帧（合成，见 :data:`POPULATED_CONTENT`）。"""
    return _frame_with(*POPULATED_CONTENT)


# ---------------------------------------------------------------------------
# 行为层：假游戏屏 + 驱动真实 AbyssActAction（抓屏 / OCR / 点击全部替换，零设备）
# ---------------------------------------------------------------------------
class _CtxStub:
    """最小 context 桩（动作只经被替换掉的抓屏 / OCR / 点击）。"""


class _ActArgv:
    def __init__(self, param):
        self.custom_action_param = json.dumps(param, ensure_ascii=False)


class _RecoArgv:
    """识别侧的 argv 桩（``abyss_giveup`` 只读 ``image`` / ``task_detail.task_id`` / 参数）。

    ``task_id`` 必须与被驱动的动作**同一个**：``_sync_task`` 见到新 task_id 会复位会话
    （包括动作层请求的收工原因），那不是本守卫要测的东西。
    """

    class _TaskDetail:
        task_id = 117_000_002

    def __init__(self, param, image=("frame",), task_id: int = 117_000_002):
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        detail = self._TaskDetail()
        detail.task_id = int(task_id)
        self.task_detail = detail
        self.image = image


class _Clock:
    """注入时钟：动作里的 ``time.sleep`` 全走它（真机一轮 1.6s，套件里不可接受）。"""

    def __init__(self, t0: float = 1000.0):
        self.t = float(t0)

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds) -> None:
        self.t += max(0.0, float(seconds))

    def time(self) -> float:
        return self.t


class _FakeTime:
    def __init__(self, clock: _Clock, real):
        self._clock = clock
        self._real = real

    def monotonic(self) -> float:
        return self._clock.monotonic()

    def sleep(self, seconds) -> None:
        self._clock.sleep(seconds)

    def time(self) -> float:
        return self._clock.time()

    def strftime(self, fmt, *args):
        return self._real.strftime(fmt, *args)


class _TabScreen:
    """假游戏屏：三个页签各有自己的内容区；点页签框中心才切换。

    ``dead=True`` 模拟「点了但页面不理你」（页签栏是图 / 点击没落到按钮上）：
    内容区永远不变 —— 这正是「切换失败」该被有界收掉的那条路。
    """

    def __init__(self, contents: dict, *, start: str | None = None, dead: bool = False):
        self.contents = {name: list(items) for name, items in contents.items()}
        self.current = start or next(iter(self.contents))
        self.dead = dead
        self.clicks: list = []

    def frame(self) -> list:
        return self.contents[self.current]

    def on_click(self, cx: int, cy: int) -> None:
        self.clicks.append((int(cx), int(cy)))
        if self.dead:
            return
        for name in self.contents:
            label = _tab_label(name)
            if label is None:
                continue
            box = label[1]
            tx = box[0] + box[2] / 2.0
            ty = box[1] + box[3] / 2.0
            if abs(tx - cx) <= 2 and abs(ty - cy) <= 2:
                self.current = name
                return


@contextlib.contextmanager
def _sandbox(impl):
    """临时账本：驱动真实动作 / 收工识别时**绝不写仓里的 progress.json**。"""
    saved = getattr(impl.ledger, "_DEFAULT", None)
    with tempfile.TemporaryDirectory() as td:
        impl.ledger.set_file(Path(td) / "progress.json")
        try:
            yield
        finally:
            impl.ledger.set_file(None)
            if saved is not None:
                impl.ledger._DEFAULT = saved


def _reset_session(impl, task_id: int = 117_000_002) -> None:
    with impl._LOCK:
        impl._SESSION.update(
            {
                "task_id": task_id,
                "tab_index": 0,
                "tab_selected": None,
                "tab_sigs": {},
                "tab_empty": {},
                "tab_fail_streak": 0,
                "tab_switches": 0,
                "giveup_reason": None,
                "start_ts": 0.0,
                "last_progress_ts": 0.0,
                "unknown_count": 0,
                "last_state": None,
                "last_observe_ts": 0.0,
                "session_max_done": 0,
            }
        )


def _drive(impl, screen: _TabScreen, param: dict, *, max_runs: int = 12):
    """像 pipeline 那样一轮一轮走：每轮先看 ``abyss_giveup``（这里只看 requested reason），
    再跑一次 ``AbyssActAction``。返回 ``(点击列表, 日志, 收工原因)``。
    """
    saved = {k: getattr(impl, k) for k in ("_grab", "_ocr", "_click_box")}
    saved_time = getattr(impl, "time", None)
    clock = _Clock()
    buf = io.StringIO()
    try:
        impl._grab = lambda context: ("frame", id(screen.current))
        impl._ocr = lambda context, image, entry="OcrTask": list(screen.frame())
        impl._click_box = lambda context, cx, cy: (screen.on_click(cx, cy) or True)
        if saved_time is not None:
            impl.time = _FakeTime(clock, saved_time)
        with contextlib.redirect_stdout(buf):
            for _ in range(max_runs):
                with impl._LOCK:
                    pending = impl._SESSION["giveup_reason"]
                if pending:
                    break
                impl.AbyssActAction().run(_CtxStub(), _ActArgv(param))
    finally:
        for k, v in saved.items():
            setattr(impl, k, v)
        if saved_time is not None:
            impl.time = saved_time
    with impl._LOCK:
        reason = impl._SESSION["giveup_reason"]
    return list(screen.clicks), buf.getvalue(), reason


def _tab_param(pipes: dict) -> dict:
    """pipeline 里页签节点的真实参数（缺省退回真源数据 —— 但要能看出「没接线」）。"""
    nodes = _tab_nodes(pipes)
    if not nodes:
        return {}
    return _acp(pipes[nodes[0]])


def _tabs_of(impl, param: dict) -> list:
    return [str(t) for t in (param.get("tabs") or impl.ZHONGSHI_TABS)]


# ---------------------------------------------------------------------------
# 守卫 ①：页签校验必须是「页面给了新证据」，不是「state 没变」
# ---------------------------------------------------------------------------
def _tab_switch_observable_failures(root: Path | None = None) -> list:
    _paths()
    impl = _impl()
    scene_abyss = _scene()
    msgs: list[str] = []
    pipes = _pipeline(root)

    nodes = _tab_nodes(pipes)
    if not nodes:
        return ["abyss.json 里没有任何 abyss_act step=tab 的节点（页签切换节点被改名/删掉？）"]
    for name in nodes:
        cp = _acp(pipes[name])
        # (a) 判据必须显式声明「内容区变化」。
        if cp.get("validate") != "content_change":
            msgs.append(
                f"{name}: custom_action_param 缺 validate='content_change'"
                f"（实际 {cp.get('validate')!r}）—— 页签校验必须声明『点完内容区文本集合必须变』"
            )
        # (b) ★自证式判据一律拒收★：切页签时页面状态本来就该是 zhongshi，拿它当 expect 恒成立。
        expect = cp.get("expect") or []
        if expect:
            hard = [str(x) for x in expect if "zhongshi" in str(x)]
            msgs.append(
                f"{name}: custom_action_param 仍带 expect={expect!r}"
                + (
                    f"（含恒真项 {hard!r}：三个页签全空时 state 永远是 zhongshi ⇒ 每次点击都"
                    "『校验通过』⇒ 真机 2026-10-18 08:0x 的无限三连）"
                    if hard
                    else "（step=tab 不看页面状态，见 validate）"
                )
            )

    # (c) 行为层：state 恒 zhongshi + 内容区不变 ⇒ **不许**出现「校验通过」。
    _reset_session(impl)
    dead = _TabScreen({"未通关": _content_tab_frame()}, start="未通关", dead=True)
    clicks_dead, log_dead, _reason_dead = _drive(impl, dead, _tab_param(pipes), max_runs=1)
    if "校验通过" in log_dead:
        msgs.append(
            "★自证式回归★ 内容区文本集合没变，动作仍打印『校验通过』——"
            f"判据退化成「state 没变就算过」了。日志尾巴：{log_dead.strip().splitlines()[-1:]!r}"
        )
    if "未生效" not in log_dead and "请求收工" not in log_dead:
        msgs.append(
            "内容区没变时动作既没报『切换未生效』也没请求收工 —— 判据没有承重。"
            f"日志：{log_dead.strip().splitlines()[-1:]!r}"
        )

    # (d) 行为层：内容区**变了** ⇒ 必须判「切换生效」，且不许收工。
    _reset_session(impl)
    live = _TabScreen(
        {"未通关": _empty_tab_frame(), "已通关": _empty_tab_frame(), "完成": _content_tab_frame()},
        start="未通关",
    )
    clicks_live, log_live, reason_live = _drive(impl, live, _tab_param(pipes), max_runs=3)
    if "切换生效" not in log_live:
        msgs.append(
            "内容区真的变了（空页签 → 有横幅）时动作没有判『切换生效』——"
            f"判据方向反了。日志：{log_live.strip().splitlines()[-3:]!r}"
        )
    if reason_live:
        msgs.append(f"目标横幅所在的页签已被切到时仍请求收工：{reason_live!r}（会把能打的账号收掉）")

    # (e) 判据函数自身：内容变化 / 空态 / 无变化 三种输入必须给三种结论。
    if impl.tab_switch_verdict(("A",), ("B",), empty_after=False, streak=1, budget=6) != "switched":
        msgs.append("tab_switch_verdict：内容区文本集合变了却不判 switched")
    if impl.tab_switch_verdict(("A",), ("A",), empty_after=True, streak=1, budget=6) != "empty":
        msgs.append("tab_switch_verdict：空态锚点在屏却不判 empty")
    if impl.tab_switch_verdict(("A",), ("A",), empty_after=False, streak=6, budget=6) != "giveup":
        msgs.append("tab_switch_verdict：无证据次数用尽仍不给 giveup（会无限重试）")
    if impl.tab_switch_verdict(("A",), ("A",), empty_after=False, streak=1, budget=6) != "retry":
        msgs.append("tab_switch_verdict：第一次无证据就该继续扫（retry），不该立刻收工")

    # (f) 内容区必须排除页签栏与底导带（否则文本集合里永远有常驻元素 ⇒ 判据退化成恒真）。
    box = tuple(getattr(scene_abyss, "ZHONGSHI_CONTENT_BOX", ()))
    if len(box) != 4:
        msgs.append("scene.abyss.ZHONGSHI_CONTENT_BOX 不是 720 空间四元组")
    else:
        labels = [box_ for text, box_ in EMPTY_FRAME if text in ("未通关", "已通关", "完成")]
        for bx in labels:
            cy = bx[1] + bx[3] / 2.0
            if box[1] <= cy <= box[3]:
                msgs.append(
                    f"内容区 {box!r} 把页签栏也框进去了（页签中心 y={cy:.0f}）——"
                    "那样『内容区文本集合』永远含三颗页签字，判据恒真"
                )
                break
        for text, bx in EMPTY_FRAME:
            if bx[1] >= 1200 and box[1] <= bx[1] + bx[3] / 2.0 <= box[3]:
                msgs.append(f"内容区 {box!r} 把底部导航『{text}』也框进去了（常驻元素 ⇒ 判据恒真）")
                break
    if tuple(impl.ZHONGSHI_CONTENT_BOX) != box:
        msgs.append(
            f"abyss_impl.ZHONGSHI_CONTENT_BOX={impl.ZHONGSHI_CONTENT_BOX!r} 与真源 {box!r} 漂移"
        )

    # (g) 点的是页签文字本身的框中心（不是死坐标）。
    if clicks_live:
        want = [(_tab_label(name) or ("", [0, 0, 0, 0]))[1] for name in ("未通关", "已通关", "完成")]
        centers = [(b[0] + b[2] / 2.0, b[1] + b[3] / 2.0) for b in want]
        if any(abs(cx - x) > 2 or abs(cy - y) > 2 for (cx, cy), (x, y) in zip(clicks_live, centers)):
            msgs.append(f"页签点击落点 {clicks_live!r} 不是页签框中心 {centers!r}")
    return msgs


def probe_abyss_tab_switch_observable() -> bool:
    msgs = _tab_switch_observable_failures()
    if msgs:
        print("  [117] 页签校验不是「页面给了新证据」：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print(
        "  [117] 页签校验：validate=content_change、无自证式 expect、内容区不含页签栏/底导带、"
        "内容变了才判生效（点的是页签框中心）"
    )
    return True


# ---------------------------------------------------------------------------
# 守卫 ②：页签切换失败的重试上限 = 1（#19：不许多次重试，之后带原因退出）
# ---------------------------------------------------------------------------
def _tab_retry_capped_failures(root: Path | None = None) -> list:
    _paths()
    impl = _impl()
    scene_abyss = _scene()
    msgs: list[str] = []
    pipes = _pipeline(root)

    # (a) 三处一致：真源 / 安装态快照 / pipeline。
    want = int(getattr(scene_abyss, "TAB_SWITCH_RETRY_LIMIT", -1))
    if want != 1:
        msgs.append(f"scene.abyss.TAB_SWITCH_RETRY_LIMIT={want!r} != 1（#19：重试 1 次后带原因退出）")
    snap = int(getattr(impl, "_TAB_SWITCH_RETRY_LIMIT_SNAPSHOT", -1))
    if snap != want:
        msgs.append(f"abyss_impl._TAB_SWITCH_RETRY_LIMIT_SNAPSHOT={snap!r} != 真源 {want!r}（安装态漂移）")
    live = int(getattr(impl, "TAB_SWITCH_RETRY_LIMIT", -1))
    if live != want:
        msgs.append(f"abyss_impl.TAB_SWITCH_RETRY_LIMIT={live!r} != 真源 {want!r}")
    for name in _tab_nodes(pipes):
        cp = _acp(pipes[name])
        if "retry_limit" not in cp:
            msgs.append(f"{name}: 没写 retry_limit（页签切换失败的上限必须在 projection 里可见）")
            continue
        try:
            got = int(cp["retry_limit"])
        except (TypeError, ValueError):
            msgs.append(f"{name}: retry_limit={cp['retry_limit']!r} 不是整数")
            continue
        if got != want:
            msgs.append(f"{name}: retry_limit={got} != 真源 {want}")

    # (b) 预算：一整轮三页签 × (1 次 + 重试 1 轮) = 6 次无证据点击后必须收工。
    tabs = _tabs_of(impl, _tab_param(pipes))
    budget = impl.tab_switch_budget(tabs, want)
    if budget != len(tabs) * 2:
        msgs.append(f"tab_switch_budget({tabs})={budget} != {len(tabs) * 2}（三页签各 2 轮）")

    # (c) 行为：死点击屏上**恰好** budget 次点击后带原因收工。
    _reset_session(impl)
    dead = _TabScreen({name: _content_tab_frame() for name in tabs}, start=tabs[0], dead=True)
    clicks, log, reason = _drive(impl, dead, _tab_param(pipes), max_runs=budget + 4)
    if len(clicks) != budget:
        msgs.append(
            f"死点击屏上点了 {len(clicks)} 次才收（期望 {budget} = 三页签各 2 轮）——"
            "重试上限没有承重（多点是空转，少点是提前放弃）"
        )
    if not reason:
        msgs.append(f"死点击屏点了 {len(clicks)} 次仍未收工（无界空转）——必须带原因退出")
    elif "切换失败" not in reason:
        msgs.append(f"死点击屏的收工原因是 {reason!r} —— 必须说明是「页签切换失败」")
    if reason and not any(k in reason for k in ("轮", "次", "重试")):
        msgs.append(f"收工原因 {reason!r} 没有写清重试了几轮（运维看不出为什么放弃）")

    # (d) retry_limit=0（一次都不重试）与 3（重试三轮）都必须改变预算 —— 证明它真的被读。
    if impl.tab_switch_budget(tabs, 0) != len(tabs):
        msgs.append("tab_switch_budget(tabs, 0) != len(tabs)（retry_limit 没被读进去）")
    if impl.tab_switch_budget(tabs, 3) == budget:
        msgs.append("tab_switch_budget(tabs, 3) == 默认预算（retry_limit 没被读进去）")

    # (e) ★第二条逃生路：整轮扫描上限★「账号有别的活动、没有深渊」时，页签会一直**切成功**
    #     （内容每轮都变），上面那条「无证据」预算永远不触发 —— 必须另有扫描上限，否则无限切。
    rounds_want = int(getattr(scene_abyss, "TAB_SCAN_ROUND_LIMIT", -1))
    if rounds_want != 2:
        msgs.append(f"scene.abyss.TAB_SCAN_ROUND_LIMIT={rounds_want!r} != 2（首轮 + 重试 1 轮）")
    if int(getattr(impl, "_TAB_SCAN_ROUND_LIMIT_SNAPSHOT", -1)) != rounds_want:
        msgs.append(
            f"abyss_impl._TAB_SCAN_ROUND_LIMIT_SNAPSHOT={impl._TAB_SCAN_ROUND_LIMIT_SNAPSHOT!r} "
            f"!= 真源 {rounds_want!r}（安装态漂移）"
        )
    if int(getattr(impl, "TAB_SCAN_ROUND_LIMIT", -1)) != rounds_want:
        msgs.append(f"abyss_impl.TAB_SCAN_ROUND_LIMIT={impl.TAB_SCAN_ROUND_LIMIT!r} != 真源 {rounds_want!r}")
    for name in _tab_nodes(pipes):
        cp = _acp(pipes[name])
        if "scan_rounds" not in cp:
            msgs.append(f"{name}: 没写 scan_rounds（整轮扫描上限必须在 projection 里可见）")
            continue
        try:
            got = int(cp["scan_rounds"])
        except (TypeError, ValueError):
            msgs.append(f"{name}: scan_rounds={cp['scan_rounds']!r} 不是整数")
            continue
        if got != rounds_want:
            msgs.append(f"{name}: scan_rounds={got} != 真源 {rounds_want}")
    scan_limit = len(tabs) * rounds_want
    _reset_session(impl)
    # 三个页签**各有不同内容**（每点一次都切成功）+ 没有横幅 —— 真机上就是「只有别的活动」。
    distinct = _TabScreen(
        {
            name: _frame_with(("活动" + str(i), [200, 600 + 40 * i, 200, 30]))
            for i, name in enumerate(tabs)
        },
        start=tabs[0],
    )
    clicks_scan, _log_scan, reason_scan = _drive(
        impl, distinct, _tab_param(pipes), max_runs=scan_limit + 4
    )
    if not reason_scan:
        msgs.append(
            f"三个页签都有内容但没有横幅时，切了 {len(clicks_scan)} 次仍不收工（无界空转）——"
            f"必须有整轮扫描上限 {scan_limit} 次"
        )
    elif "横幅" not in reason_scan:
        msgs.append(f"扫空的收工原因 {reason_scan!r} 没有写清「没找到横幅」（运维看不出为什么放弃）")
    if len(clicks_scan) > scan_limit + 1:
        msgs.append(
            f"扫空时切了 {len(clicks_scan)} 次（上限 {scan_limit} + 最多 1 次「点到已选中页签」）"
        )

    # (f) 离开终始之战页必须复位页签账本（否则「进关 → 回列表页」会拼出假的扫描/空态结论）。
    _reset_session(impl)
    with impl._LOCK:
        impl._SESSION["tab_empty"] = {name: True for name in tabs}
        impl._SESSION["tab_switches"] = scan_limit
    impl._observe("main_city", {}, [("主城", [157, 1248, 44, 25])])
    with impl._LOCK:
        left = (dict(impl._SESSION["tab_empty"]), int(impl._SESSION["tab_switches"]))
    if left != ({}, 0):
        msgs.append(f"离开终始之战页后页签账本没有复位：tab_empty={left[0]!r} switches={left[1]}")
    return msgs


def probe_abyss_tab_retry_capped() -> bool:
    msgs = _tab_retry_capped_failures()
    if msgs:
        print("  [117] 页签切换失败的重试上限不成立：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print(
        "  [117] 重试上限：真源/快照/pipeline 三处 =1、预算 6 次、死点击屏恰 6 次后带原因收工；"
        "整轮扫描上限 = 2 轮（扫空必收工，不无限切页签）；离开终始之战页复位页签账本"
    )
    return True


# ---------------------------------------------------------------------------
# 守卫 ③：空态锚点来自入库证据帧，且三个页签全空 ⇒ 走既有 giveup 收工
# ---------------------------------------------------------------------------
def _empty_giveup_failures(root: Path | None = None) -> list:
    _paths()
    impl = _impl()
    scene_abyss = _scene()
    msgs: list[str] = []
    pipes = _pipeline(root)

    want = str(getattr(scene_abyss, "ZHONGSHI_EMPTY_ANCHOR", ""))
    reason_want = str(getattr(scene_abyss, "ZHONGSHI_EMPTY_REASON", ""))

    # (a) 三处一致（真源 / 安装态快照 / pipeline）。
    if str(getattr(impl, "_ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT", "")) != want:
        msgs.append(
            f"abyss_impl._ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT={impl._ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT!r} "
            f"!= 真源 {want!r}"
        )
    if str(getattr(impl, "ZHONGSHI_EMPTY_ANCHOR", "")) != want:
        msgs.append(f"abyss_impl.ZHONGSHI_EMPTY_ANCHOR={impl.ZHONGSHI_EMPTY_ANCHOR!r} != 真源 {want!r}")
    if str(getattr(impl, "ZHONGSHI_EMPTY_REASON", "")) != reason_want:
        msgs.append(f"abyss_impl.ZHONGSHI_EMPTY_REASON={impl.ZHONGSHI_EMPTY_REASON!r} != 真源 {reason_want!r}")
    giveup_param = (
        ((pipes.get("AbyssGiveUp") or {}).get("recognition") or {}).get("param") or {}
    ).get("custom_recognition_param") or {}
    if str(giveup_param.get("empty_anchor") or "") != want:
        msgs.append(
            f"abyss.json::AbyssGiveUp.empty_anchor={giveup_param.get('empty_anchor')!r} != 真源 {want!r}"
            "（空态锚点必须投影到既有 giveup 出口上）"
        )

    # (b) 锚点必须**来自入库证据帧**：帧 + 侧车都在，侧车里有这句、且框落在内容区。
    if not EVIDENCE_FRAME.is_file():
        msgs.append(f"证据帧缺失：{EVIDENCE_FRAME.relative_to(REPO_ROOT).as_posix()}（空态锚点没有出处）")
    if not EVIDENCE_OCR.is_file():
        msgs.append(f"证据帧侧车缺失：{EVIDENCE_OCR.relative_to(REPO_ROOT).as_posix()}")
    if not EMPTY_FRAME:
        return msgs + ["证据帧侧车读不出任何 OCR 项（格式坏了 / 文件空）"]
    anchor_hits = [(text, box) for text, box in EMPTY_FRAME if want and want in text]
    if not anchor_hits:
        msgs.append(f"侧车里没有空态锚点 {want!r} —— 锚点不是从证据帧读出来的")
    else:
        box = tuple(getattr(scene_abyss, "ZHONGSHI_CONTENT_BOX", ()))
        for _text, b in anchor_hits:
            cy = b[1] + b[3] / 2.0
            if len(box) == 4 and not (box[1] <= cy <= box[3]):
                msgs.append(
                    f"证据帧里锚点框 {b!r} 的中心 y={cy:.0f} 不在内容区 {box!r} 内"
                    "（内容区判据与证据帧脱节）"
                )
    state, _info = impl.classify(EMPTY_FRAME)
    if state != "zhongshi":
        msgs.append(f"证据帧被 classify 判成 {state!r}（应为 zhongshi；空态判据只在终始之战页有意义）")
    if not impl.has_empty_anchor(EMPTY_FRAME, want):
        msgs.append("has_empty_anchor 对证据帧返回 False —— 真机上永远认不出空态")

    # (c) 负例：一屏**有内容**的终始之战（recon 读数）不得判空态。
    populated = _content_tab_frame()
    if impl.has_empty_anchor(populated, want):
        msgs.append("有内容的终始之战帧被判成空态（会把能打的账号收掉）")
    if impl.classify(populated)[0] != "zhongshi":
        msgs.append("有内容的终始之战帧没有被判成 zhongshi（负例 fixture 坏了）")

    # (d) 行为：三页签全空 ⇒ 恰 3 次点击后给出**空态原因**（不是「切换失败」）。
    _reset_session(impl)
    tabs = _tabs_of(impl, _tab_param(pipes))
    empty = _TabScreen({name: _empty_tab_frame() for name in tabs}, start=tabs[-1])
    clicks, log, reason = _drive(impl, empty, _tab_param(pipes), max_runs=len(tabs) + 3)
    if len(clicks) != len(tabs):
        msgs.append(
            f"三页签全空时点了 {len(clicks)} 次（期望 {len(tabs)}：每个页签各记一笔空态就收工）"
        )
    if reason != reason_want:
        msgs.append(
            f"三页签全空的收工原因 {reason!r} != 真源 {reason_want!r}"
            "（必须是「没有可打的关卡」，不能报成页签切换失败）"
        )

    # (e) 收工真的走既有 abyss_giveup 出口：识别命中 + detail.reason + 写收工标记。
    if reason:
        _reset_session(impl)
        with _sandbox(impl):
            with impl._LOCK:
                impl._SESSION["giveup_reason"] = reason
            param = {"ocr_entry": "OcrTask", "max_task_sec": 0, "empty_anchor": want}
            saved = impl._ocr
            impl._ocr = lambda context, image, entry="OcrTask": list(_empty_tab_frame())
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    got = impl.AbyssGiveUpRecognition().analyze(_CtxStub(), _RecoArgv(param))
            finally:
                impl._ocr = saved
            detail = getattr(got, "detail", None) or {}
            if getattr(got, "box", None) is None:
                msgs.append("abyss_giveup 没把动作层请求的收工原因报出来（box=None ⇒ 节点不命中）")
            if detail.get("reason") != reason:
                msgs.append(f"abyss_giveup.detail.reason={detail.get('reason')!r} != {reason!r}")
            if "收工 —— " not in buf.getvalue():
                msgs.append("收工没有打用户可见的『[abyss] 收工 —— <原因>』那一行（#86 口径）")
            done_key = f"{impl._cfg().ledger_scope}/run/completed"
            if not impl.ledger.is_done(done_key):
                msgs.append(f"收工没有写收工标记 {done_key}（下一轮不会清账）")

    # (f) 不许新造出口：空态收工只能靠既有 giveup 节点，不许再来一颗 StopTask。
    stoppers = [
        name
        for name, node in pipes.items()
        if isinstance(node, dict)
        and ((node.get("action") or {}).get("type") == "StopTask")
        and "empty" in name.lower() + json.dumps(_acp(node), ensure_ascii=False).lower()
    ]
    if stoppers:
        msgs.append(f"{stoppers!r} 新造了空态收工出口 —— 必须走既有 abyss_giveup（单一收工语义）")
    return msgs


def probe_abyss_zhongshi_empty_giveup() -> bool:
    msgs = _empty_giveup_failures()
    if msgs:
        print("  [117] 终始之战空态不收工：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print(
        "  [117] 空态收工：锚点来自入库证据帧（帧+侧车）、三处一致、三页签全空恰 3 次点击后"
        "给出『终始之战没有可打的关卡（三个页签均无内容）』并走 abyss_giveup 出口"
    )
    return True


HOOKS = [
    (
        "abyss-tab-switch-observable",
        _TICKET,
        "#117①：终始之战页签校验必须是「页面给了新证据」（validate=content_change："
        "点完内容区文本集合必须变），不许带 expect=['zhongshi'] 这种自证式恒真项；"
        "内容区排除页签栏/底导带；点的是页签框中心 —— 真机 2026-10-18 08:0x 三个页签全空时"
        "『校验通过 zhongshi -> zhongshi』无限三连",
        probe_abyss_tab_switch_observable,
    ),
    (
        "abyss-tab-retry-capped",
        _TICKET,
        "#117：页签切换**有界**且带原因 —— 重试上限 = 1（真源/安装态快照/pipeline 三处一致），"
        "预算 = 三页签各 2 轮 = 6 次无证据点击；死点击屏上恰 6 次后以「页签切换失败」收工。"
        "另加第二条逃生路：整轮扫描上限 = 2 轮（scan_rounds），三个页签**都有内容**但没有横幅时"
        "切满 6 次必须收工并说明「没有找到横幅」（= 账号没这条活动的明确原因）；"
        "离开终始之战页复位页签账本",
        probe_abyss_tab_retry_capped,
    ),
    (
        "abyss-zhongshi-empty-giveup",
        _TICKET,
        "#117②：空态锚点『没有相关的活动』必须来自入库证据帧 tools/frames/abyss_zhongshi_tabs.png"
        "（+ .ocr.txt 侧车，框落在内容区内）；三个页签都记满 ⇒ 收工"
        "『终始之战没有可打的关卡（三个页签均无内容）』，走既有 abyss_giveup 出口（不新造 StopTask）；"
        "有内容的终始之战帧不得判空态",
        probe_abyss_zhongshi_empty_giveup,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook117_"))
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
    impl = _impl()

    print("hooks_117 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_abyss_tab_switch_observable() is True
        and probe_abyss_tab_retry_capped() is True
        and probe_abyss_zhongshi_empty_giveup() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三条守卫全绿")
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

    # ① 把校验退回自证式（真机那次无限三连的原始形态）。
    _break_pipeline(
        "把页签校验退回自证式（expect=[zhongshi, loading]，摘掉 validate）",
        lambda p: _sub(
            p,
            '"validate": "content_change",\n                    "retry_limit": 1',
            '"expect": ["zhongshi", "loading"],\n                    "retry_limit": 1',
        ),
        _tab_switch_observable_failures,
    )

    # ①b 判据函数退化成「永远 switched」（有 validate 字样、但没有真判据）。
    real_verdict = impl.tab_switch_verdict
    try:
        impl.tab_switch_verdict = lambda *a, **k: "switched"
        msgs = _tab_switch_observable_failures()
        red_1b = len(msgs) > 0
        print(
            f"  [{'PASS' if red_1b else 'FAIL'}] 判据函数退化成「永远 switched」-> "
            f"{'红' if red_1b else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
        checks.append(red_1b)
    finally:
        impl.tab_switch_verdict = real_verdict

    # ② 重试上限改成 9（= 空转；#19 的结论是不许多次重试）。
    _break_pipeline(
        "把 pipeline 的 retry_limit 改成 9（重试 9 轮 = 空转）",
        lambda p: _sub(p, '"retry_limit": 1', '"retry_limit": 9'),
        _tab_retry_capped_failures,
    )
    # ②b 真源上限改成 9（pipeline 跟着漂），守卫仍必须以「预算不对」变红。
    real_limit = impl.TAB_SWITCH_RETRY_LIMIT
    real_budget = impl.tab_switch_budget
    try:
        impl.TAB_SWITCH_RETRY_LIMIT = 9
        msgs = _tab_retry_capped_failures()
        red_2b = len(msgs) > 0
        print(
            f"  [{'PASS' if red_2b else 'FAIL'}] 把 abyss_impl.TAB_SWITCH_RETRY_LIMIT 改成 9 -> "
            f"{'红' if red_2b else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
        checks.append(red_2b)
    finally:
        impl.TAB_SWITCH_RETRY_LIMIT = real_limit
        impl.tab_switch_budget = real_budget

    # ②c 整轮扫描上限改成 99（= 「账号只有别的活动」时无限切页签）。
    _break_pipeline(
        "把 pipeline 的 scan_rounds 改成 99（扫空后无限切页签）",
        lambda p: _sub(p, '"scan_rounds": 2', '"scan_rounds": 99'),
        _tab_retry_capped_failures,
    )
    real_rounds = impl.TAB_SCAN_ROUND_LIMIT
    try:
        impl.TAB_SCAN_ROUND_LIMIT = 99
        msgs = _tab_retry_capped_failures()
        red_2c = len(msgs) > 0
        print(
            f"  [{'PASS' if red_2c else 'FAIL'}] 把 abyss_impl.TAB_SCAN_ROUND_LIMIT 改成 99 -> "
            f"{'红' if red_2c else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
        checks.append(red_2c)
    finally:
        impl.TAB_SCAN_ROUND_LIMIT = real_rounds

    # ③ 摘掉 pipeline 的空态锚点（空态识别没有接线）。
    _break_pipeline(
        "摘掉 AbyssGiveUp 的 empty_anchor（空态不再走既有无出口）",
        lambda p: _sub(p, '\n                    "empty_anchor": "没有相关的活动"', ""),
        _empty_giveup_failures,
    )
    # ③b 锚点改成一句不存在的字（= 空态识别失效，真机上永远认不出来）。
    real_anchor = impl.ZHONGSHI_EMPTY_ANCHOR
    real_snapshot = impl._ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT
    try:
        impl.ZHONGSHI_EMPTY_ANCHOR = "没有相关内容"
        impl._ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT = "没有相关内容"
        msgs = _empty_giveup_failures()
        red_3b = len(msgs) > 0
        print(
            f"  [{'PASS' if red_3b else 'FAIL'}] 把空态锚点改成一句不存在的字 -> "
            f"{'红' if red_3b else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
        checks.append(red_3b)
    finally:
        impl.ZHONGSHI_EMPTY_ANCHOR = real_anchor
        impl._ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT = real_snapshot

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
