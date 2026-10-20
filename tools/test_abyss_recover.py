# -*- coding: utf-8 -*-
"""#21 / ADR 0005 第 4 条：深渊「迷路」先归位重导航（2 次预算）—— 离线，零设备。

    .venv\\Scripts\\python.exe tools\\test_abyss_recover.py

判据全部在进程内：真实 ``abyss_impl.is_home_section_deep_page`` / ``AbyssGiveUpRecognition``
/ ``AbyssRecoverGateRecognition`` / ``AbyssRecoverAction``，只替换 OCR / 截图（不连设备、
不写仓里的 ``progress.json``）。证据帧是 ``tools/frames`` 的两张真机 720 空间 OCR 侧车：
  · ``lord_mode_select.png``（五重决战详情页）—— ``classify`` = **unknown**，本判据 **True**；
  · ``lord_home_city.png``（主城）—— ``classify`` = **main_city**，本判据 **False**。

覆盖（照票面 + #21 验收）：
  1. 页面判据：五重决战页 True / 主城 False / 合成反例（只有返回、返回不在左槽）False；
  2. 预算：连喂 3 次迷路帧 —— 第 1/2 次只置 ``recover_pending``、**不写收工标记**；
     第 3 次收工，原因 = ``连续 {n}s 认不出画面（归位 2 次失败）``；
  3. 门控叶：``recover_pending=False`` 恒不命中；``True`` + 当前帧 unknown 才命中；
  4. 动作：深层页点「主城」框中心 / 否则点左槽「返回」 / 都不在**不点击**；
     ``recoveries`` 累计、``recover_pending`` 清、**迷路时钟清零**；
  5. 连续失败不会背靠背烧预算：归位后 ``lost_seconds`` 从 0 重新累计，第 2 次触发要再等
     ``lost_sec``（本测试用假 ``now`` 推进）；期间再跑 giveup 不会收工、也不吃第二次预算；
  6. 结构：``AbyssRecover`` 紧贴 ``AbyssGiveUp`` 之后（索引 3）、GiveUp 留在前段探针区
     （索引 2，**不许挪到链尾**，否则 #117 的 ``request_giveup`` 永远没人消费）、
     两者各只出现一次；节点接线 recognition=abyss_recover_gate / action=abyss_recover。

★为什么「GiveUp 留在前段」是硬要求★：``AbyssNavTab`` 在 ``zhongshi`` 页每轮恒命中；
GiveUp 一旦排到业务节点之后，动作层 ``request_giveup(...)`` 就永远轮不到消费 →
#117 真机的「三个空页签无限三连」复活。守卫见 ``tools/contract_hooks/hooks_abyss.py``。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import abyss_impl as impl  # noqa: E402
import battle_loop_core as core  # noqa: E402
import jsonc  # noqa: E402

FAILS: list[str] = []

#: 与 argv 里的 task_id 一致：``_sync_task`` 见到同一个 id 就不会复位会话
#: （复位会清掉本文件预置的「已连续迷路 N 秒」与预算计数）。
_TASK_ID = 21_000_001

FRAMES = TOOLS / "frames"


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 证据帧：720 空间 OCR 侧车（text<TAB>[x,y,w,h]）
# ---------------------------------------------------------------------------
def load_sidecar(name: str) -> list[tuple[str, list[int]]]:
    path = FRAMES / f"{name}.ocr.txt"
    items: list[tuple[str, list[int]]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        text, _, box = raw.partition("\t")
        x, y, w, h = (int(v) for v in box.strip().strip("[]").split(","))
        items.append((text.strip(), [x, y, w, h]))
    return items


MODE_PAGE = load_sidecar("lord_mode_select")   # 五重决战详情页（主城分区深层页，classify=unknown）
HOME_CITY = load_sidecar("lord_home_city")     # 主城（负例，classify=main_city）

#: 合成反例：只有「返回」、没有「主城」。
BACK_ONLY = [("返回", [30, 1247, 47, 25]), ("商店", [397, 1247, 45, 25])]
#: 合成反例：「主城」在，但「返回」不在最左槽（x 中心 > 110）。
BACK_NOT_IN_SLOT = [("主城", [156, 1245, 45, 28]), ("返回", [200, 1247, 47, 25])]


# ---------------------------------------------------------------------------
# 离线驱动：argv 桩 + 临时账本 + 会话复位
# ---------------------------------------------------------------------------
class _RecoArgv:
    """识别器只读 ``image`` / ``task_detail.task_id`` / 自定义参数。"""

    class _TaskDetail:
        task_id = _TASK_ID

    def __init__(self, param, image=("frame",), task_id: int = _TASK_ID):
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        detail = self._TaskDetail()
        detail.task_id = int(task_id)
        self.task_detail = detail
        self.image = image


class _ActionArgv:
    """动作只读 ``custom_action_param``。"""

    def __init__(self, param):
        self.custom_action_param = json.dumps(param, ensure_ascii=False)


class _CtxStub:
    """记录 ``abyss_recover`` 通过 ``AbyssClick`` 点的框（真实的 _click_box 路径）。"""

    def __init__(self):
        self.clicks: list[tuple] = []

    def run_action(self, name, box=None, **kwargs):  # noqa: ANN001
        self.clicks.append((name, tuple(box or ())))
        return True

    @property
    def clicked_centers(self) -> list[tuple[int, int]]:
        """把 (cx-1, cy-1, 2, 2) 还原成点击中心。"""
        return [(x + 1, y + 1) for _n, (x, y, _w, _h) in self.clicks]


@contextlib.contextmanager
def _sandbox():
    """临时账本：真正触发收工时会写「本轮已收工」标记 —— 绝不写仓里的 ``progress.json``。"""
    saved = impl.ledger._DEFAULT
    with tempfile.TemporaryDirectory() as td:
        impl.ledger.set_file(Path(td) / "progress.json")
        try:
            yield
        finally:
            impl.ledger._DEFAULT = saved


def _reset_session() -> None:
    """一场干净的任务会话（task_id 与 argv 相同，``_sync_task`` 不会二次复位）。"""
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION.update(
            {
                "task_id": _TASK_ID,
                "cur_stage": None,
                "in_fight": False,
                "start_ts": now,
                "last_progress_ts": now,
                "last_state": None,
                "last_observe_ts": 0.0,
                "total_marks": 0,
                "max_done": 0,
                "session_max_done": 0,
                "joined_stage": None,
                "ladder_cleared": False,
                "giveup_reason": None,
                "tab_selected": None,
                "tab_sigs": {},
                "tab_empty": {},
                "tab_fail_streak": 0,
                "tab_switches": 0,
                "lap": 1,
                "progress": None,
                "progress_done_reason": None,
                # ★#21★ 归位预算按会话复位（与 ``_sync_task`` 的新任务分支同一份）。
                "recoveries": 0,
                "recover_pending": False,
            }
        )
        impl._SESSION["lost"].reset()


def _arm_lost(seconds: float = 61.4) -> None:
    """把迷路时钟预置成「已连续 N 秒 unknown」，且让 giveup 内部这帧不重复打点。"""
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION["last_state"] = "unknown"
        impl._SESSION["last_observe_ts"] = now
        impl._SESSION["last_progress_ts"] = now
        lost = impl._SESSION["lost"]
        lost.observe("unknown", now - float(seconds))
    check(
        f"预置：连续 {seconds:g}s unknown",
        float(seconds) - 1.0 <= impl._SESSION["lost"].seconds_lost(time.monotonic()) < float(seconds) + 1.0,
        str(impl._SESSION["lost"].seconds_lost(time.monotonic())),
    )


@contextlib.contextmanager
def _patch_io(items, image=("frame",), grab=None):
    """替换 OCR / 截屏（零设备），退出时还原。"""
    saved_ocr = impl._ocr
    saved_grab = impl._grab
    impl._ocr = lambda context, img, entry="OcrTask": list(items or [])
    impl._grab = grab or (lambda context: image)
    try:
        yield
    finally:
        impl._ocr = saved_ocr
        impl._grab = saved_grab


def _run_giveup(items, capture: io.StringIO | None = None):
    with _patch_io(items):
        if capture is None:
            return impl.AbyssGiveUpRecognition().analyze(None, _RecoArgv({}))
        with contextlib.redirect_stdout(capture):
            return impl.AbyssGiveUpRecognition().analyze(None, _RecoArgv({}))


def _run_gate(items):
    with _patch_io(items):
        return impl.AbyssRecoverGateRecognition().analyze(None, _RecoArgv({}))


def _run_recover(items, ctx: _CtxStub | None = None, capture: io.StringIO | None = None):
    ctx = ctx if ctx is not None else _CtxStub()
    with _patch_io(items):
        if capture is None:
            return impl.AbyssRecoverAction().run(ctx, _ActionArgv({})), ctx
        with contextlib.redirect_stdout(capture):
            return impl.AbyssRecoverAction().run(ctx, _ActionArgv({})), ctx


def _detail(result) -> dict:
    return getattr(result, "detail", None) or {}


# ---------------------------------------------------------------------------
# 1. 页面判据：五重决战页 True / 主城 False / 合成反例 False
# ---------------------------------------------------------------------------
def test_predicate() -> None:
    print("\n== 1. is_home_section_deep_page：两张证据帧正反例 + 合成反例 ==")
    mode_state, _ = impl.classify(MODE_PAGE)
    home_state, _ = impl.classify(HOME_CITY)
    check("证据：五重决战详情页 classify == unknown（#21 要救的页面）", mode_state == "unknown", mode_state)
    check("证据：主城 classify == main_city（负例）", home_state == "main_city", home_state)

    check("五重决战详情页（主城 + 左槽返回）⇒ True", impl.is_home_section_deep_page(MODE_PAGE) is True)
    check(
        "主城（主城 在、左槽是主角色）⇒ False",
        impl.is_home_section_deep_page(HOME_CITY) is False,
        str([t for t, _b in HOME_CITY if "主" in t or "返" in t]),
    )
    check("合成：只有「返回」没有「主城」⇒ False", impl.is_home_section_deep_page(BACK_ONLY) is False)
    check(
        "合成：「主城」在但「返回」不在最左槽 ⇒ False",
        impl.is_home_section_deep_page(BACK_NOT_IN_SLOT) is False,
    )
    check("空帧 ⇒ False", impl.is_home_section_deep_page([]) is False)


# ---------------------------------------------------------------------------
# 2. 预算：三次迷路帧 —— 前两次只置 pending，第三次收工
# ---------------------------------------------------------------------------
def test_budget() -> None:
    print("\n== 2. 预算 2 次：第 1/2 次只置 recover_pending，第 3 次收工（含归位 2 次失败）==")
    _reset_session()
    run_done_key = f"{impl._cfg().ledger_scope}/run/completed"

    buf = io.StringIO()
    with _sandbox():
        # --- 第 1 次迷路 ---------------------------------------------------
        _arm_lost(61.4)
        first = _run_giveup(MODE_PAGE, capture=buf)
        d1 = _detail(first)
        check("第 1 次：不命中（box=None）", getattr(first, "box", None) is None, str(d1))
        check("第 1 次：detail.recover_pending=True", d1.get("recover_pending") is True, str(d1))
        check("第 1 次：detail.giveup=False", d1.get("giveup") is False, str(d1))
        check("第 1 次：recoveries 仍为 0", impl._SESSION["recoveries"] == 0, str(impl._SESSION["recoveries"]))
        check("第 1 次：不写收工标记", impl.ledger.is_done(run_done_key) is False)
        check("第 1 次：日志不出现『收工 ——』", "收工 ——" not in buf.getvalue(), buf.getvalue().splitlines()[-2:])
        check(
            "第 1 次：日志说明先归位（第 1/2 次预算）",
            "先归位重导航（第 1/2 次预算）" in buf.getvalue(),
            [ln for ln in buf.getvalue().splitlines() if "先归位" in ln],
        )

        # 闸门 + 动作消费第 1 次预算（真实链路：GiveUp → Gate → Action）。
        gate1 = _run_gate(MODE_PAGE)
        check("第 1 次：门控叶命中（pending + unknown）", getattr(gate1, "box", None) == [0, 0, 0, 0], str(_detail(gate1)))
        _ok, ctx1 = _run_recover(MODE_PAGE)
        check("第 1 次：动作后 recoveries=1", impl._SESSION["recoveries"] == 1, str(impl._SESSION["recoveries"]))
        check("第 1 次：动作后 recover_pending=False", impl._SESSION["recover_pending"] is False)
        check("第 1 次：动作点了「主城」中心", ctx1.clicked_centers == [(178, 1259)], str(ctx1.clicks))
        check("第 1 次：动作后迷路时钟清零", impl._SESSION["lost"].seconds_lost(time.monotonic()) == 0.0)

        # --- 第 2 次迷路 ---------------------------------------------------
        _arm_lost(61.4)
        second = _run_giveup(MODE_PAGE, capture=buf)
        d2 = _detail(second)
        check("第 2 次：不命中（box=None）", getattr(second, "box", None) is None, str(d2))
        check("第 2 次：detail.recover_pending=True", d2.get("recover_pending") is True, str(d2))
        check("第 2 次：recoveries 仍为 1", impl._SESSION["recoveries"] == 1, str(impl._SESSION["recoveries"]))
        check("第 2 次：仍不写收工标记", impl.ledger.is_done(run_done_key) is False)
        check(
            "第 2 次：日志说明第 2/2 次预算",
            "先归位重导航（第 2/2 次预算）" in buf.getvalue(),
            [ln for ln in buf.getvalue().splitlines() if "先归位" in ln],
        )
        gate2 = _run_gate(MODE_PAGE)
        check("第 2 次：门控叶命中", getattr(gate2, "box", None) == [0, 0, 0, 0], str(_detail(gate2)))
        _ok, ctx2 = _run_recover(MODE_PAGE)
        check("第 2 次：动作后 recoveries=2", impl._SESSION["recoveries"] == 2, str(impl._SESSION["recoveries"]))
        check("第 2 次：动作后迷路时钟清零", impl._SESSION["lost"].seconds_lost(time.monotonic()) == 0.0)

        # --- 第 3 次迷路：预算用尽 → 收工 ----------------------------------
        _arm_lost(61.4)
        third = _run_giveup(MODE_PAGE, capture=buf)
        d3 = _detail(third)
        want = "连续 61s 认不出画面（归位 2 次失败）"
        check("第 3 次：命中（box=[0,0,0,0]）", getattr(third, "box", None) == [0, 0, 0, 0], str(d3))
        check("第 3 次：detail.giveup=True", d3.get("giveup") is True, str(d3))
        check("第 3 次：原因含『归位 2 次失败』", d3.get("reason") == want, repr(d3.get("reason")))
        check(
            "第 3 次：原因前半句 = core.lost_reason（三场景同一句，不另造）",
            str(d3.get("reason", "")).startswith(core.lost_reason(61.4, None).split("（", 1)[0]),
            repr(d3.get("reason")),
        )
        check("第 3 次：写收工标记", impl.ledger.is_done(run_done_key) is True)
        check(
            "第 3 次：用户可见行『[abyss] 收工 —— 连续 61s 认不出画面（归位 2 次失败）』",
            "[abyss] 收工 —— 连续 61s 认不出画面（归位 2 次失败）" in buf.getvalue(),
            [ln for ln in buf.getvalue().splitlines() if "收工 ——" in ln][:2],
        )


# ---------------------------------------------------------------------------
# 3. 门控叶：pending 是唯一开关；当前帧不是 unknown 不命中
# ---------------------------------------------------------------------------
def test_gate() -> None:
    print("\n== 3. abyss_recover_gate：只有 recover_pending + 当前帧 unknown 才命中 ==")
    _reset_session()
    with impl._LOCK:
        impl._SESSION["recover_pending"] = False
    got = _run_gate(MODE_PAGE)
    check("pending=False + unknown 帧 ⇒ 不命中", getattr(got, "box", None) is None, str(_detail(got)))
    check("pending=False：detail.recover_pending=False", _detail(got).get("recover_pending") is False, str(_detail(got)))

    with impl._LOCK:
        impl._SESSION["recover_pending"] = True
    got = _run_gate(MODE_PAGE)
    check("pending=True + unknown 帧 ⇒ 命中", getattr(got, "box", None) == [0, 0, 0, 0], str(_detail(got)))
    check("pending=True：detail.state=unknown", _detail(got).get("state") == "unknown", str(_detail(got)))

    got = _run_gate(HOME_CITY)
    check("pending=True + 已知页（主城）⇒ 不命中", getattr(got, "box", None) is None, str(_detail(got)))
    check("不命中时不动 pending（交给 _observe 清）", impl._SESSION["recover_pending"] is True)
    check("门控叶从不产生可点击框", getattr(got, "box", None) != [0, 0, 0, 0])


# ---------------------------------------------------------------------------
# 4. 动作：主城 / 返回 / 都不在；预算累计 + 旗标清 + 时钟清零
# ---------------------------------------------------------------------------
def test_action() -> None:
    print("\n== 4. abyss_recover：点主城 / 点返回 / 都不在绝不盲点 ==")
    _reset_session()
    with impl._LOCK:
        impl._SESSION["recover_pending"] = True

    buf = io.StringIO()
    _ok, ctx = _run_recover(MODE_PAGE, capture=buf)
    check(
        "深层页：点「主城」框中心 (720:178,1259)",
        ctx.clicks == [("AbyssClick", (177, 1258, 2, 2))],
        str(ctx.clicks),
    )
    check("深层页：recoveries 累计到 1", impl._SESSION["recoveries"] == 1, str(impl._SESSION["recoveries"]))
    check("深层页：recover_pending 被清", impl._SESSION["recover_pending"] is False)
    check(
        "深层页：日志格式『[abyss] 归位第 1/2 次：unknown → 点了「主城」@720(178,1259)』",
        "[abyss] 归位第 1/2 次：unknown → 点了「主城」@720(178,1259)" in buf.getvalue(),
        [ln for ln in buf.getvalue().splitlines() if "归位第" in ln],
    )

    # 兜底：不是深层页、但左槽仍能读到一个「返回」→ 点返回。
    _reset_session()
    with impl._LOCK:
        impl._SESSION["recover_pending"] = True
        impl._SESSION["lost"].observe("unknown", time.monotonic() - 30.0)
    back_frame = [("返回", [30, 1247, 47, 25])]
    buf2 = io.StringIO()
    _ok, ctx2 = _run_recover(back_frame, capture=buf2)
    check("兜底：点「返回」框中心", ctx2.clicked_centers == [(53, 1259)], str(ctx2.clicks))
    check(
        "兜底：日志说明点了返回",
        "点了「返回」@720(53,1259)" in buf2.getvalue(),
        [ln for ln in buf2.getvalue().splitlines() if "归位第" in ln],
    )
    check("动作后迷路时钟清零（归位即重新计时）", impl._SESSION["lost"].seconds_lost(time.monotonic()) == 0.0)

    # 都不在：不点击，但仍然消耗一次预算（票面「无论如何 recoveries += 1」）。
    _reset_session()
    with impl._LOCK:
        impl._SESSION["recover_pending"] = True
    buf3 = io.StringIO()
    _ok, ctx3 = _run_recover(HOME_CITY, capture=buf3)
    check("都不在：一次点击都没有（绝不盲点）", ctx3.clicks == [], str(ctx3.clicks))
    check("都不在：预算仍 +1", impl._SESSION["recoveries"] == 1, str(impl._SESSION["recoveries"]))
    check(
        "都不在：日志写明『没找到…不点击』",
        "没找到（主城/返回都不在）→ 不点击" in buf3.getvalue(),
        [ln for ln in buf3.getvalue().splitlines() if "归位第" in ln],
    )
    check("都不在：recover_pending 照样清", impl._SESSION["recover_pending"] is False)


# ---------------------------------------------------------------------------
# 5. 归位后时钟清零 ⇒ 连续失败不会背靠背烧预算（#21 裁决）
# ---------------------------------------------------------------------------
def test_clock_reset_prevents_back_to_back_budget() -> None:
    print("\n== 5. 归位后迷路时钟清零：下一帧 unknown 从 0 累计，第 2 次触发要再等 lost_sec ==")
    _reset_session()
    with _sandbox():
        _arm_lost(61.4)
        _run_giveup(MODE_PAGE)                       # 第 1 次：置 pending
        _ok, _ctx = _run_recover(MODE_PAGE)          # 归位：预算 1、时钟清零
        check("归位后：recoveries=1", impl._SESSION["recoveries"] == 1)
        check("归位后：seconds_lost 从 0 起算", impl._SESSION["lost"].seconds_lost(time.monotonic()) == 0.0)

        # 紧接着的下一帧仍是 unknown（过渡帧）：从 0 累计 2s —— **不该**触发第 2 次。
        with impl._LOCK:
            impl._SESSION["lost"].observe("unknown", time.monotonic() - 2.0)
            impl._SESSION["last_state"] = "unknown"
            impl._SESSION["last_observe_ts"] = time.monotonic()
        right_after = _run_giveup(MODE_PAGE)
        check(
            "归位后 2s 的 unknown：不收工、也不吃第 2 次预算",
            getattr(right_after, "box", None) is None
            and _detail(right_after).get("recover_pending") in (None, False)
            and impl._SESSION["recoveries"] == 1,
            f"box={getattr(right_after, 'box', None)} detail={_detail(right_after)} "
            f"recoveries={impl._SESSION['recoveries']}",
        )

        # 时间真的走满 lost_sec（用假 now 推进）：第 2 次归位才允许触发。
        now = time.monotonic()
        with impl._LOCK:
            impl._SESSION["lost"].reset()
            impl._SESSION["lost"].observe("unknown", now - 60.5)
            impl._SESSION["last_state"] = "unknown"
            impl._SESSION["last_observe_ts"] = now
        second = _run_giveup(MODE_PAGE)
        check(
            "再等 60.5s：第 2 次预算触发（pending=True、recoveries 仍 1）",
            _detail(second).get("recover_pending") is True and impl._SESSION["recoveries"] == 1,
            f"{_detail(second)} recoveries={impl._SESSION['recoveries']}",
        )


# ---------------------------------------------------------------------------
# 6. 结构：紧贴 AbyssGiveUp、GiveUp 留在前段、各只出现一次、接线正确
# ---------------------------------------------------------------------------
def test_structure() -> None:
    print("\n== 6. abyss.json 结构：AbyssRecover 紧随 AbyssGiveUp，GiveUp 不许挪到链尾 ==")
    pipes = jsonc.load(open(ROOT / "assets" / "resource" / "pipeline" / "abyss.json", encoding="utf-8"))
    entry = list((pipes.get("AbyssEntry") or {}).get("next") or [])

    check("AbyssEntry.next 里 AbyssGiveUp 只出现一次", entry.count("AbyssGiveUp") == 1, str(entry.count("AbyssGiveUp")))
    check("AbyssEntry.next 里 AbyssRecover 只出现一次", entry.count("AbyssRecover") == 1, str(entry.count("AbyssRecover")))
    check(
        "AbyssRecover 的索引紧贴 AbyssGiveUp 之后",
        "AbyssGiveUp" in entry
        and "AbyssRecover" in entry
        and entry.index("AbyssRecover") == entry.index("AbyssGiveUp") + 1,
        f"giveup={entry.index('AbyssGiveUp') if 'AbyssGiveUp' in entry else None} "
        f"recover={entry.index('AbyssRecover') if 'AbyssRecover' in entry else None}",
    )
    check(
        "AbyssGiveUp 留在前段探针区（索引 <= 3，挪到链尾会复活 #117 空转）",
        "AbyssGiveUp" in entry and entry.index("AbyssGiveUp") <= 3,
        str(entry.index("AbyssGiveUp") if "AbyssGiveUp" in entry else None),
    )
    check("AbyssGiveUp 索引 = 2（现状：LevelRequired / Native 之后）", entry.index("AbyssGiveUp") == 2, str(entry.index("AbyssGiveUp")))
    check("AbyssRecover 索引 = 3", entry.index("AbyssRecover") == 3, str(entry.index("AbyssRecover")))
    check("AbyssWait 仍是链尾兜底", entry[-1] == "AbyssWait", str(entry[-1:]))

    node = pipes.get("AbyssRecover") or {}
    rec = node.get("recognition") or {}
    act = node.get("action") or {}
    check("AbyssRecover.recognition.type == Custom", rec.get("type") == "Custom", str(rec.get("type")))
    check(
        "AbyssRecover.recognition = abyss_recover_gate",
        (rec.get("param") or {}).get("custom_recognition") == "abyss_recover_gate",
        str((rec.get("param") or {}).get("custom_recognition")),
    )
    check("AbyssRecover.action.type == Custom", act.get("type") == "Custom", str(act.get("type")))
    check(
        "AbyssRecover.action = abyss_recover",
        (act.get("param") or {}).get("custom_action") == "abyss_recover",
        str((act.get("param") or {}).get("custom_action")),
    )
    check("AbyssRecover.next = ['AbyssEntry']", node.get("next") == ["AbyssEntry"], str(node.get("next")))
    check("AbyssRecover 有 post_delay（给主城加载留时间）", int(node.get("post_delay") or 0) >= 1000, str(node.get("post_delay")))
    check(
        "AbyssGiveUp 仍是 StopTask 出口",
        (pipes.get("AbyssGiveUp") or {}).get("action", {}).get("type") == "StopTask",
    )


def main() -> int:
    print("=" * 78)
    print("#21 / ADR 0005 第 4 条：迷路 → 先归位重导航（2 次预算），用尽才收工 —— 离线零设备")
    print("=" * 78)
    test_predicate()
    test_budget()
    test_gate()
    test_action()
    test_clock_reset_prevents_back_to_back_budget()
    test_structure()
    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_abyss_recover: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
