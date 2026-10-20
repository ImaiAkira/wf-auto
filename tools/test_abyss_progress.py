# -*- coding: utf-8 -*-
"""#11（进度可见 3/5）：深渊连战 + 深渊连战EX 的用户可见进度行 —— 离线单测（零设备）。

    .venv\\Scripts\\python.exe tools\\test_abyss_progress.py

口径唯一真源 = ``docs/spec/progress-visibility.md``（§B 出口 API / §C 深渊那两行）：
进度显示在 MFAAvalonia 日志面板（= agent 进程真实 stdout），报的是**本次任务的步进**，
机制日志全场景静音到 ``debug/agent.log``。

本文件断言六件事（全部零设备：只驱动 ``agent/abyss_impl.py`` 的纯逻辑，OCR/点击一律替换）：

1. **中途接管**：``start()`` 开一条线；第一条带数字的线 = **画面读数**（12/30，不是 1/30）；
2. **step 只在「该战记账成功处」**：账本 ``{scope}/stage/{N}`` 真的落盘之后才出线，
   ``N`` = 真实战号；重复结算 / 已记账的战 / 圈末之后的帧都不多出线；
3. **收工**：三处点名出口（零进度超时 / 无新关卡 / 已打完一圈）把**既有原因文案**原样带出来；
4. **两个场景同一份实现**：``abyss``（深渊连战EX）与 ``abyss_plain``（深渊连战）只差
   ``display``（都从 ``scene.abyss`` 读，不写死）；
5. **quiet**：#142 的一次 stdout 重定向对深渊生效 —— 面板里**只有** ``[进度]`` 行，
   点击 / 账本 / 收工这些机制日志进日志文件；
6. **守卫接线**：``tools/contract_hooks/hooks_144.py`` 的挂点真的被 ``discover_hooks()`` 收进来。

★真机不阻塞：面板实际长什么样由运维在 GUI 上双签（#4 的口径），本文件只证明离线口径。★
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
AGENT = ROOT / "agent"
for _p in (str(TOOLS), str(ROOT), str(AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import reporting  # noqa: E402

#: 本文件用的 task_id（与被驱动的识别器**同一个**：``_sync_task`` 见到新 task_id 会复位会话）。
TID = 11_000_002

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _impl():
    import abyss_impl as impl  # noqa: PLC0415

    return impl


def _scene():
    from scene import abyss as scene_abyss  # noqa: PLC0415

    return scene_abyss


def _scratch(name: str = "progress.json") -> Path:
    """临时目录（与全仓其它离线测试同口径：``tempfile.mkdtemp``）。"""
    return Path(tempfile.mkdtemp(prefix="wf_abyss_progress_")) / name


# ---------------------------------------------------------------------------
# 面板 / 账本 / 会话：三个沙箱（每个用例用完还原，绝不写仓里的 progress.json）
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _panel():
    """把「面板」换成可读缓冲。生产里它就是进程真实 stdout（:mod:`reporting` 导入时抓的）。"""
    saved = reporting._REAL_STDOUT
    buf = io.StringIO()
    reporting._REAL_STDOUT = buf
    try:
        yield buf
    finally:
        reporting._REAL_STDOUT = saved
        reporting.set_quiet(False)


@contextlib.contextmanager
def _ledger_sandbox(impl):
    """临时账本文件（驱动真实 ``_observe`` 时绝不写仓库根的 progress.json）。"""
    saved = getattr(impl.ledger, "_DEFAULT", None)
    path = _scratch()
    impl.ledger.set_file(path)
    try:
        yield path
    finally:
        impl.ledger.set_file(None)
        if saved is not None:
            impl.ledger._DEFAULT = saved


def _reset(impl, scene: str = "abyss") -> None:
    """把会话复位成「新任务刚起来」的形态（与 ``_sync_task`` 的新任务分支同形）。"""
    with impl._LOCK:
        impl._SESSION.update(
            {
                "task_id": TID,
                "cur_stage": None,
                "max_done": 0,
                "session_max_done": 0,
                "joined_stage": None,
                "total_marks": 0,
                "ladder_cleared": False,
                "in_fight": False,
                "start_ts": 0.0,
                "last_progress_ts": 0.0,
                # ★ADR 0005 / #19★ 与 ``_sync_task`` 的新任务分支同形：复位的是迷路**时钟**，
                #   不再是旧帧数计数器。
                "lost": impl.core.LostClock(),
                "last_state": None,
                "last_observe_ts": 0.0,
                "tab_index": 0,
                "tab_selected": None,
                "tab_sigs": {},
                "tab_empty": {},
                "tab_fail_streak": 0,
                "tab_switches": 0,
                "giveup_reason": None,
                "lap": 1,
                "progress": None,
            }
        )
    impl._set_active_scene(scene)


def _feed(impl, state: str, items=None):
    """喂一帧给真实 ``_observe``（先戳掉「同状态 1.2s 内只记一次」的合并）。"""
    with impl._LOCK:
        impl._SESSION["last_observe_ts"] = 0.0
        impl._SESSION["last_state"] = None
    impl._observe(state, {}, list(items or []))


def _main_frame(stage: int, display: str = "深渊连战EX") -> list:
    """关卡选择页的合成 OCR 帧（只要求能解析出「第N战」；判据本体不归本票测）。"""
    return [
        (f"{display}第{stage}战", [201, 1040, 237, 32]),
        ("不可续战", [300, 980, 90, 30]),
        ("推荐编成", [56, 1114, 96, 30]),
    ]


def _clear_stage(impl, stage: int, *, in_fight: bool = True):
    """模拟「进战斗 → 结算」两帧（结算页 = 记账点）。"""
    if in_fight:
        _feed(impl, "abyss_battle")
    else:
        with impl._LOCK:
            impl._SESSION["in_fight"] = False
    _feed(impl, "abyss_settle")


def _lines() -> list[str]:
    with _impl()._LOCK:
        line = _impl()._SESSION["progress"]
    return list(line.lines) if line is not None else []


# ---------------------------------------------------------------------------
# 1. 中途接管：start + 第一条数字线 = 画面读数
# ---------------------------------------------------------------------------
def test_takeover_baseline() -> None:
    print("\n== 1. 中途接管：第一条带数字的线 = 画面读数（12/30，不是 1/30） ==")
    impl, scene_abyss = _impl(), _scene()
    with _ledger_sandbox(impl), _panel() as buf:
        _reset(impl)
        # 接管首帧：关卡选择页写着「第 12 战」。
        _feed(impl, "abyss_main", _main_frame(12))
        check(
            "首次观察基准：start 一条线（display/总量从 scene.abyss 读）",
            _lines() == ["[进度] 深渊连战EX 开始（共 30 战）"],
            str(_lines()),
        )
        check(
            "★start 不带假数字★（还没打任何一战，面板上不许出现 1/30）",
            not any("/30" in line for line in _lines()),
            str(_lines()),
        )
        _clear_stage(impl, 12)
        lines = _lines()
        check(
            "★第一条带数字的线 = 画面读数 12/30（不是从 1 数）★",
            lines[-1] == "[进度] 深渊连战EX 12/30 战（第 1 圈）",
            lines[-1] if lines else "",
        )
        check(
            "★这一战真的落了账★（abyss/stage/12）",
            impl.ledger.is_done("abyss/stage/12") is True,
            str(impl.ledger.scope("abyss/stage")),
        )
        check(
            "display 来自配置（EX = 深渊连战EX）",
            impl._cfg("abyss").display == scene_abyss.ABYSS_EX.display == "深渊连战EX",
            impl._cfg("abyss").display,
        )
        check("总量来自配置（30）", impl._cfg("abyss").max_stages == 30, str(impl._cfg("abyss").max_stages))
        check("两条线都进了面板", all(line in buf.getvalue() for line in lines), buf.getvalue()[:160])


# ---------------------------------------------------------------------------
# 2. step 只在「该战记账成功处」
# ---------------------------------------------------------------------------
def test_step_at_ledger_write() -> None:
    print("\n== 2. step 只在记账成功处：重复结算 / 已记账 / 圈末之后都不多出线 ==")
    impl = _impl()
    with _ledger_sandbox(impl), _panel():
        _reset(impl)
        _feed(impl, "abyss_main", _main_frame(7))
        _clear_stage(impl, 7)
        check("第 7 战记账 → 出 7/30", _lines()[-1] == "[进度] 深渊连战EX 7/30 战（第 1 圈）", str(_lines()))
        n_after_first = len(_lines())

        # 同一结算页再被观察两次（真实里 1.2s 老化会重进这个分支）：Progress 单调去重，不多出线。
        _clear_stage(impl, 7)
        _clear_stage(impl, 7)
        check(
            "★同一战重复结算不重复出线★",
            len(_lines()) == n_after_first,
            f"{n_after_first} -> {len(_lines())}",
        )

        # 账本里**已经有**第 9 战（例如上一轮会话记过、本轮中途接管）：mark_done=False ⇒ 不出线。
        impl.ledger.mark_done("abyss/stage/9")
        _feed(impl, "abyss_main", _main_frame(9))
        _clear_stage(impl, 9)
        check(
            "★账本已记过的战不再当作本次的一步★",
            not any("9/30" in line for line in _lines()),
            str(_lines()),
        )

        # 继续下一战：8 还是新的 ⇒ 出线（N = 真实战号，不是「第几步」）。
        _feed(impl, "abyss_main", _main_frame(8))
        _clear_stage(impl, 8)
        check(
            "下一战出 8/30（真实战号）",
            _lines()[-1] == "[进度] 深渊连战EX 8/30 战（第 1 圈）",
            str(_lines()),
        )

        # 圈末 30：出 30/30 + 一条收工；其后的帧不再出 step。
        _feed(impl, "abyss_main", _main_frame(30))
        _clear_stage(impl, 30)
        check(
            "圈末两条：30/30 + 收工（既有「已打完一圈」文案）",
            _lines()[-2:]
            == [
                "[进度] 深渊连战EX 30/30 战（第 1 圈）",
                "[进度] 深渊连战EX 收工：已打完第 30 战（一圈 30 层全清）",
            ],
            str(_lines()[-2:]),
        )
        n_done = len(_lines())
        _clear_stage(impl, 30)
        check("收工之后的结算帧不再出 step", len(_lines()) == n_done, f"{n_done} -> {len(_lines())}")


# ---------------------------------------------------------------------------
# 3. 三处点名收工出口：原因 = 既有文案
# ---------------------------------------------------------------------------
class _CtxStub:
    """最小 context 桩（识别器只经被替换的 ``_ocr``，不碰设备）。"""


class _RecoArgv:
    """识别侧 argv 桩（``abyss_giveup`` 只读 ``custom_recognition_param`` / ``image`` / task_id）。"""

    class _TaskDetail:
        task_id = TID

    def __init__(self, param: dict, task_id: int = TID):
        import json  # noqa: PLC0415

        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        detail = self._TaskDetail()
        detail.task_id = int(task_id)
        self.task_detail = detail
        self.image = ("frame",)


#: 主城帧（让 ``abyss_giveup`` 的 ``_observe`` 什么都不记账；只测收工那一段）。
_MAIN_CITY = [
    ("修行之道", [15, 725, 161, 45]),
    ("成长任务", [47, 368, 118, 33]),
    ("当前进度", [366, 928, 60, 20]),
    ("活动", [80, 1120, 62, 34]),
    ("领主战", [569, 1121, 78, 29]),
]


def _giveup(impl, param: dict | None = None):
    """真跑一次 ``AbyssGiveUpRecognition``（OCR 替换成主城帧），返回 (AnalyzeResult, 机制 stdout)。"""
    saved = impl._ocr
    impl._ocr = lambda context, image, entry="OcrTask": list(_MAIN_CITY)
    mech = io.StringIO()
    try:
        with contextlib.redirect_stdout(mech):
            got = impl.AbyssGiveUpRecognition().analyze(_CtxStub(), _RecoArgv(param or {}))
    finally:
        impl._ocr = saved
    return got, mech.getvalue()


def test_done_reasons() -> None:
    print("\n== 3. 三处点名收工出口：原因原样带出（不新造文案） ==")
    impl = _impl()

    # (a) 已打完一圈 —— 原因必须与机制日志里那句「一圈 N 层全清」**同源**。
    with _ledger_sandbox(impl), _panel():
        _reset(impl)
        _feed(impl, "abyss_main", _main_frame(30))
        mech = io.StringIO()
        with contextlib.redirect_stdout(mech):
            _clear_stage(impl, 30)
        lines = _lines()
        body = mech.getvalue()
        check(
            "已打完一圈：收工原因 = 既有『已打完第 30 战（一圈 30 层全清）』",
            lines[-1] == "[进度] 深渊连战EX 收工：已打完第 30 战（一圈 30 层全清）",
            lines[-1] if lines else "",
        )
        check(
            "★收工原因与机制日志同一句话★（不是第二份文案）",
            "★已打完第 30 战（一圈 30 层全清）★" in body
            and "已打完第 30 战（一圈 30 层全清）" in lines[-1],
            body.strip().splitlines()[-1:] or "",
        )

    # (b) 零进度超时（#118 的 300s）—— 原因 = 既有 zero-progress 文案。
    with _ledger_sandbox(impl), _panel():
        _reset(impl)
        _feed(impl, "abyss_main", _main_frame(3))
        with impl._LOCK:
            impl._SESSION["session_max_done"] = 0
            impl._SESSION["last_progress_ts"] = time.monotonic() - 400.0
        got, mech = _giveup(impl, {"zero_progress_sec": 300, "no_progress_sec": 900})
        detail = getattr(got, "detail", None) or {}
        reason = detail.get("reason")
        lines = _lines()
        check("零进度：#118 的 300s 文案（既有原因）", reason == "300s 一场都没有完成（关卡打不过？）", repr(reason))
        check(
            "零进度：面板收工行 = [进度] … 收工：<既有原因>",
            lines[-1] == f"[进度] 深渊连战EX 收工：{reason}",
            lines[-1] if lines else "",
        )
        check("零进度：机制日志里是同一句原因", f"收工 —— {reason}" in mech, mech.strip().splitlines()[-1:] or "")
        # 同一帧被重复观察：同一条收工原因只许出现在面板一次。
        _giveup(impl, {"zero_progress_sec": 300, "no_progress_sec": 900})
        check(
            "★同一条收工原因重复回来不刷第二行★",
            len([line for line in _lines() if "收工：" in line]) == 1,
            str([line for line in _lines() if "收工：" in line]),
        )

    # (c) 无新关卡（900s）—— 原因 = 既有 no-progress 文案。
    with _ledger_sandbox(impl), _panel():
        _reset(impl)
        _feed(impl, "abyss_main", _main_frame(3))
        with impl._LOCK:
            impl._SESSION["session_max_done"] = 5
            impl._SESSION["last_progress_ts"] = time.monotonic() - 1000.0
        got, mech = _giveup(impl, {"zero_progress_sec": 300, "no_progress_sec": 900})
        detail = getattr(got, "detail", None) or {}
        reason = detail.get("reason")
        lines = _lines()
        check("无新关卡：既有 900s 文案", reason == "900s 无新关卡完成", repr(reason))
        check(
            "无新关卡：面板收工行带出同一句",
            lines[-1] == f"[进度] 深渊连战EX 收工：{reason}",
            lines[-1] if lines else "",
        )
        check("无新关卡：机制日志里是同一句原因", f"收工 —— {reason}" in mech, mech.strip().splitlines()[-1:] or "")

    # (d) 既有 giveup 的另一条原因（页签三连空）也带进面板（#117 的出口，文案来自真源）。
    with _ledger_sandbox(impl), _panel():
        _reset(impl)
        _feed(impl, "abyss_main", _main_frame(3))
        empty_reason = impl.ZHONGSHI_EMPTY_REASON
        with impl._LOCK:
            impl._SESSION["giveup_reason"] = empty_reason
        got, _mech = _giveup(impl)
        lines = _lines()
        check(
            "页签全空收工：同一条真源原因进面板（不新造第二条收工语义）",
            (getattr(got, "detail", None) or {}).get("reason") == empty_reason
            and lines[-1] == f"[进度] 深渊连战EX 收工：{empty_reason}",
            lines[-1] if lines else "",
        )


# ---------------------------------------------------------------------------
# 4. 深渊连战与深渊连战EX：同一份实现，只差 display
# ---------------------------------------------------------------------------
def test_plain_scene_same_impl() -> None:
    print("\n== 4. 深渊连战 = 同一份实现 + 场景数据（display 不同） ==")
    impl, scene_abyss = _impl(), _scene()
    with _ledger_sandbox(impl), _panel():
        _reset(impl, "abyss_plain")
        _feed(impl, "abyss_main", _main_frame(5, display="深渊连战"))
        _clear_stage(impl, 5)
        lines = _lines()
        check(
            "普通深渊的进度行 display = 深渊连战（数据来自 scene.abyss.ABYSS_PLAIN）",
            lines[-1] == "[进度] 深渊连战 5/30 战（第 1 圈）",
            lines[-1] if lines else "",
        )
        check(
            "账本范围也按场景分（abyss_plain/stage/5，不污染 EX 的 abyss/*）",
            impl.ledger.is_done("abyss_plain/stage/5") is True
            and impl.ledger.is_done("abyss/stage/5") is False,
            str(impl.ledger.scope("abyss_plain/stage")) + " / " + str(impl.ledger.scope("abyss/stage")),
        )
        check(
            "两个场景的 display 不同、实现同一份（不 fork 状态机）",
            scene_abyss.ABYSS_EX.display != scene_abyss.ABYSS_PLAIN.display
            and impl._cfg("abyss").display == "深渊连战EX"
            and impl._cfg("abyss_plain").display == "深渊连战",
            f"{impl._cfg('abyss').display} / {impl._cfg('abyss_plain').display}",
        )


# ---------------------------------------------------------------------------
# 5. quiet：机制日志进文件、面板只剩 [进度]
# ---------------------------------------------------------------------------
def test_quiet_keeps_two_streams() -> None:
    print("\n== 5. quiet（#142 一次重定向）：面板只有 [进度]，机制日志进日志文件 ==")
    impl = _impl()
    log = _scratch("agent.log")
    with _ledger_sandbox(impl), _panel() as panel:
        _reset(impl)
        ok = reporting.set_quiet(True, log)
        try:
            _feed(impl, "abyss_main", _main_frame(12))
            _clear_stage(impl, 12)
        finally:
            reporting.set_quiet(False)
        body = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        shown = panel.getvalue()
    check("set_quiet 生效", ok is True and body != "", f"ok={ok} log_bytes={len(body)}")
    check("机制日志（首次观察基准 / 第 12 战完成）落盘", "★首次观察基准：画面第 12 战★" in body and "第 12 战完成" in body, body[:120])
    check("机制日志没漏进面板", "[abyss]" not in shown, shown[:160])
    check(
        "★面板里只有 [进度] 行★",
        all(line.startswith("[进度] ") for line in shown.strip().splitlines()) and shown.strip() != "",
        shown[:200],
    )
    check(
        "进度行同时是 12/30 与开始（两条）",
        shown.strip().splitlines()
        == ["[进度] 深渊连战EX 开始（共 30 战）", "[进度] 深渊连战EX 12/30 战（第 1 圈）"],
        shown[:200],
    )


# ---------------------------------------------------------------------------
# 6. 守卫接线（hooks_144 不是只活在文件里）
# ---------------------------------------------------------------------------
def test_hooks_wired() -> None:
    print("\n== 6. 守卫接线：hooks_144 的挂点被 discover_hooks() 收进来 ==")
    from contract_hooks import discover_hooks  # noqa: PLC0415
    from contract_hooks import hooks_144 as h144  # noqa: PLC0415

    ids = {hook_id for hook_id, _t, _w, _p in discover_hooks()}
    for hook_id in (
        "abyss-progress-start-baseline",
        "abyss-progress-step-at-ledger-write",
        "abyss-progress-done-reasons",
        "abyss-progress-lap-lines",
        "abyss-progress-single-exit",
    ):
        check(f"挂点 {hook_id} 被发现", hook_id in ids)
    check("五条守卫探针全绿", all(p() is True for _i, _t, _w, p in h144.HOOKS))
    check("prove_red 成立（红于自己造的坏件）", h144.prove_red() is True)


def main() -> int:
    print("=" * 78)
    print("#11：深渊连战 + 深渊连战EX 接入 reporting（第 n/30 战 · 第 j 圈 · 收工原因）")
    print("=" * 78)
    test_takeover_baseline()
    test_step_at_ledger_write()
    test_done_reasons()
    test_plain_scene_same_impl()
    test_quiet_keeps_two_streams()
    test_hooks_wired()
    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + " / ".join(FAILS))
        return 1
    print("test_abyss_progress: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
