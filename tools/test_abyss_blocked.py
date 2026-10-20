# -*- coding: utf-8 -*-
"""#27「正在挑战中的关卡」弹窗 + #28 归位预算回血 —— 离线，零设备。

    .venv\\Scripts\\python.exe tools\\test_abyss_blocked.py

判据全部在进程内：真实 ``abyss_impl.classify`` / ``AbyssBlockedAction`` / ``_observe``，
只替换截图与 OCR（不连设备、不写仓里的 ``progress.json``）。

覆盖：
  1. 弹窗帧 + 点「取消」→ 回到已知页：记 1 次受阻、**不请求收工**、
     点击落在「取消」框中心（不是 OK、不是底导）；
  2. 取消后仍是 unknown：``blocked_count`` 累计；到 ``MAX_BLOCKED`` 才 ``request_giveup``，
     原因必须写清「正在挑战中的关卡」+「需人工处理」；
  2b. **取消成功但立刻又弹**（点第 30 战 → 弹窗 → 取消 → 又点 → 又弹）也必须收敛：
     每次遇到弹窗都计数，到上限照样收工 —— 否则这个环是无界的；
  3. #28 预算回血：``recoveries=2`` 时**进入战斗** → 归零并打一行日志；
  4. #28 不误回血：unknown 帧不归零（连续失败仍然只有 2 次机会）；
  5. 结构契约：``AbyssChallengeBlocked`` 在 ``AbyssEntry.next`` 索引 4（GiveUp/Recover
     仍为 2/3）、接线 abyss_blocked、next 回 AbyssEntry、OCR 判据是弹窗正文片段；
     ``my_action.py`` 与 ``live_harness.CUSTOM_ACTIONS`` 都已注册 ``abyss_blocked``。
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
import jsonc  # noqa: E402

FAILS: list[str] = []
_TASK_ID = 27_000_001


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 合成帧（720 空间 OCR 文本 + 框）
# ---------------------------------------------------------------------------
#: 真机 01:25 的弹窗：整句被 OCR 拆成两行；按钮是「取消」/「OK」。
DIALOG = [
    ("挑战深渊连战EX。", [80, 700, 560, 30]),
    ("若非通关或放弃正在挑战中的关卡，则无法挑战其", [60, 760, 600, 30]),
    ("他难度的极限战斗关卡", [170, 800, 380, 30]),
    ("取消", [180, 1000, 160, 60]),
    ("OK", [560, 1000, 160, 60]),
]
#: 已知页（主城）：用仓里真机 720 空间 OCR 侧车，保证 classify 真的判成 main_city。
def _load_sidecar(name: str) -> list[tuple[str, list[int]]]:
    path = TOOLS / "frames" / f"{name}.ocr.txt"
    items: list[tuple[str, list[int]]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        text, _, box = raw.partition("\t")
        x, y, w, h = (int(v) for v in box.strip().strip("[]").split(","))
        items.append((text.strip(), [x, y, w, h]))
    return items


HOME_CITY = _load_sidecar("lord_home_city")
#: 取消后仍认不出（弹窗还在）。
STILL_UNKNOWN = DIALOG
#: 没有 OK 的弹窗（只剩「取消」）—— 验证兜底路径。
DIALOG_NO_OK = [item for item in DIALOG if item[0] != "OK"]


# ---------------------------------------------------------------------------
# 驱动桩
# ---------------------------------------------------------------------------
class _ActionArgv:
    def __init__(self, param):
        self.custom_action_param = json.dumps(param, ensure_ascii=False)


class _CtxStub:
    """记录 abyss_blocked 通过 AbyssClick 点的框。"""

    def __init__(self):
        self.clicks: list[tuple] = []

    def run_action(self, name, box=None, **kwargs):  # noqa: ANN001
        self.clicks.append((name, tuple(box or ())))
        return True

    @property
    def clicked_centers(self) -> list[tuple[int, int]]:
        return [(x + 1, y + 1) for _n, (x, y, _w, _h) in self.clicks]


@contextlib.contextmanager
def _patch_ocr(seq, sleep_ms: int = 0):
    """替换截图 / OCR：每次 OCR 依次取 ``seq`` 里的一帧。"""
    saved_ocr = impl._ocr
    saved_grab = impl._grab
    saved_sleep = time.sleep
    queue = list(seq)

    def _next_items():
        return list(queue.pop(0)) if queue else []

    impl._grab = lambda context: ("frame",)
    impl._ocr = lambda context, img, entry="OcrTask": _next_items()
    time.sleep = lambda _s: None  # 动作里有 1.2s 等待，测试里不真等
    try:
        yield
    finally:
        impl._ocr = saved_ocr
        impl._grab = saved_grab
        time.sleep = saved_sleep


@contextlib.contextmanager
def _sandbox():
    """临时账本：真触发收工时会写「本轮已收工」标记 —— 绝不写仓里的 progress.json。"""
    saved = impl.ledger._DEFAULT
    with tempfile.TemporaryDirectory() as td:
        impl.ledger.set_file(Path(td) / "progress.json")
        try:
            yield
        finally:
            impl.ledger._DEFAULT = saved


def _reset_session() -> None:
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
                "recoveries": 0,
                "recover_pending": False,
                "blocked_count": 0,
            }
        )
        impl._SESSION["lost"].reset()


def _run_blocked(seq, capture: io.StringIO | None = None):
    ctx = _CtxStub()
    with _sandbox(), _patch_ocr(seq):
        if capture is None:
            result = impl.AbyssBlockedAction().run(ctx, _ActionArgv({"ocr_entry": "OcrTask"}))
        else:
            with contextlib.redirect_stdout(capture):
                result = impl.AbyssBlockedAction().run(ctx, _ActionArgv({"ocr_entry": "OcrTask"}))
    return result, ctx


def _blocked_count() -> int:
    with impl._LOCK:
        return int(impl._SESSION["blocked_count"])


def _giveup_reason():
    with impl._LOCK:
        return impl._SESSION["giveup_reason"]


# ---------------------------------------------------------------------------
# 1. 弹窗 → 点「取消」→ 回已知页
# ---------------------------------------------------------------------------
def test_ok_reaches_known_page() -> None:
    print("\n[1] 弹窗点「OK（继续）」后回到已知页")
    _reset_session()
    out, ctx = _run_blocked([DIALOG, HOME_CITY], capture=io.StringIO())
    check("动作返回 True", out is True)
    check("点了一次且落在「OK」中心", ctx.clicked_centers == [(640, 1030)], str(ctx.clicked_centers))
    check("blocked_count 记了 1 次（遇到弹窗即计）", _blocked_count() == 1, str(_blocked_count()))
    check("未请求收工", _giveup_reason() is None, str(_giveup_reason()))


def test_fallback_cancel() -> None:
    print("\n[1b] 认不到 OK 时兜底点「取消」")
    _reset_session()
    out, ctx = _run_blocked([DIALOG_NO_OK, HOME_CITY], capture=io.StringIO())
    check("动作返回 True", out is True)
    check("兜底点了「取消」中心", ctx.clicked_centers == [(260, 1030)], str(ctx.clicked_centers))
    check("未请求收工", _giveup_reason() is None, str(_giveup_reason()))


# ---------------------------------------------------------------------------
# 2. 连续取消仍 unknown → 到上限才收工
# ---------------------------------------------------------------------------
def test_bounded_giveup() -> None:
    print("\n[2] 取消后仍 unknown：有界重试")
    _reset_session()
    buf = io.StringIO()
    for i in range(1, impl.MAX_BLOCKED):
        out, _ctx = _run_blocked([DIALOG, STILL_UNKNOWN], capture=buf)
        check(f"第 {i}/{impl.MAX_BLOCKED} 次：仍在重试、未收工", _giveup_reason() is None)
        check(f"第 {i} 次后 blocked_count={i}", _blocked_count() == i, str(_blocked_count()))

    out, ctx = _run_blocked([DIALOG, STILL_UNKNOWN], capture=buf)
    reason = _giveup_reason() or ""
    check(f"第 {impl.MAX_BLOCKED} 次触发 request_giveup", bool(reason), reason)
    check("原因含「正在挑战中的关卡」", "正在挑战中的关卡" in reason)
    check("原因含「需人工处理」", "需人工处理" in reason)
    check("每次都在点「OK」", len(ctx.clicked_centers) == 1)


def test_pingpong_bounded() -> None:
    print(f"\n[2b] 「弹窗 → 取消 → 又弹」也有界（取消成功 ≠ 问题解决）")
    _reset_session()
    buf = io.StringIO()
    for i in range(1, impl.MAX_BLOCKED):
        _run_blocked([DIALOG, HOME_CITY], capture=buf)
        check(f"第 {i} 次：取消后回到已知页、未收工", _giveup_reason() is None)
    _run_blocked([DIALOG, HOME_CITY], capture=buf)
    reason = _giveup_reason() or ""
    check(f"第 {impl.MAX_BLOCKED} 次取消后仍收敛到收工", bool(reason), reason)
    check("原因仍是「正在挑战中的关卡」", "正在挑战中的关卡" in reason, reason)


# ---------------------------------------------------------------------------
# 3/4. #28 归位预算：进战斗才回血；unknown 不回血
# ---------------------------------------------------------------------------
def test_recoveries_refill_on_battle() -> None:
    print("\n[3] #28 进入战斗 → 归位预算复位")
    _reset_session()
    with impl._LOCK:
        impl._SESSION["recoveries"] = impl.MAX_RECOVERIES
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        impl._observe(impl.ABYSS_BATTLE, {}, [])
    with impl._LOCK:
        after = int(impl._SESSION["recoveries"])
    check("recoveries 归零", after == 0, str(after))
    check("日志说明已复位", "归位预算复位" in buf.getvalue(), buf.getvalue().strip())


def test_recoveries_not_refilled_by_unknown() -> None:
    print("\n[4] #28 unknown 帧不回血（连续失败仍只有 2 次）")
    _reset_session()
    with impl._LOCK:
        impl._SESSION["recoveries"] = impl.MAX_RECOVERIES
    with contextlib.redirect_stdout(io.StringIO()):
        impl._observe("unknown", {}, [])
    with impl._LOCK:
        after = int(impl._SESSION["recoveries"])
    check("recoveries 保持满额", after == impl.MAX_RECOVERIES, str(after))


# ---------------------------------------------------------------------------
# 5. 结构契约
# ---------------------------------------------------------------------------
def test_contract() -> None:
    print("\n[5] 结构契约")
    data = jsonc.loads((ROOT / "assets" / "resource" / "pipeline" / "abyss.json").read_text(encoding="utf-8"))
    entry = data["AbyssEntry"]["next"]
    check("AbyssChallengeBlocked 在 AbyssEntry.next 里", "AbyssChallengeBlocked" in entry)
    check("索引为 4（GiveUp 仍 2 / Recover 仍 3）",
          entry.index("AbyssChallengeBlocked") == 4 and entry.index("AbyssGiveUp") == 2 and entry.index("AbyssRecover") == 3,
          str(entry[:6]))
    node = data.get("AbyssChallengeBlocked") or {}
    check("节点存在", bool(node))
    rec = (node.get("recognition") or {}).get("param") or {}
    check("OCR 判据是弹窗正文片段", rec.get("expected") == ["正在挑战中的关卡"], str(rec.get("expected")))
    act = (node.get("action") or {}).get("param") or {}
    check("接线 abyss_blocked", act.get("custom_action") == "abyss_blocked", str(act.get("custom_action")))
    check("next 回 AbyssEntry", node.get("next") == ["AbyssEntry"], str(node.get("next")))
    action_src = (ROOT / "agent" / "my_action.py").read_text(encoding="utf-8")
    check("my_action 注册 abyss_blocked", 'custom_action("abyss_blocked")' in action_src)
    harness_src = (ROOT / "tools" / "live_harness.py").read_text(encoding="utf-8")
    check("live_harness.CUSTOM_ACTIONS 覆盖 abyss_blocked",
          '"abyss_blocked": "abyss_impl:AbyssBlockedAction"' in harness_src)


def main() -> int:
    test_ok_reaches_known_page()
    test_fallback_cancel()
    test_bounded_giveup()
    test_pingpong_bounded()
    test_recoveries_refill_on_battle()
    test_recoveries_not_refilled_by_unknown()
    test_contract()
    print("\n" + ("FAIL: " + ", ".join(FAILS) if FAILS else "ALL PASS"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
