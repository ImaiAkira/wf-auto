# -*- coding: utf-8 -*-
"""#11（进度可见 3/5）：深渊连战 + 深渊连战EX 接入 :mod:`reporting` —— 契约挂点 + 破坏实验。

## 为什么有这张票

运维 2026-10-19：「深渊这类模式要显示进度」。裁决见
``docs/spec/progress-visibility.md``：进度显示在 MFAAvalonia 日志面板（= agent 进程真实
stdout），口径是**本次任务的步进** ``i/N``；机制日志全场景静音到 ``debug/agent.log``。

本票是四条场景 lane 里的第三条：``agent/abyss_impl.py`` 里的**深渊连战**（``abyss_plain``）
与**深渊连战EX**（``abyss``）共用同一份实现（只差 ``ScenarioTarget`` 的 display / 横幅 /
确认文案）。进度行统一走 ``agent/reporting.py::Progress``。

## 契约（守卫口径）

- **H1 起手用画面基准**（``abyss-progress-start-baseline``）：首次观察基准处 ``start()``；
  一步 = 一次「第 N 战」记账，``N`` 是**画面/账面真实战号** —— 中途接管的第一条数字线是
  ``12/30``，**不是**从 1 数出来的 ``1/30``。display / 总量从配置读（EX 与 plain 各自正确）。
- **H2 step 落在记账点**（``abyss-progress-step-at-ledger-write``）：``{scope}/stage/{N}``
  真的落盘之后才出线；同一战重复结算、账本里已记过的战、圈末之后的帧都**不多出线**；
  源码顺序上 ``ledger.mark_done(...)`` 必须在 ``_progress_step(...)`` **之前**。
- **H3 收工原因复用既有文案**（``abyss-progress-done-reasons``）：三处点名出口
  （零进度超时 / 无新关卡 / 已打完一圈）+ 既有 giveup 的另一条（页签全空）都调用
  ``Progress.done(既有 reason)`` —— 面板收工行与机制日志**同一句话**，不新造。
- **H4 按圈分段**（``abyss-progress-lap-lines``）：``Progress.step`` 单调去重，而深渊阶梯
  每圈从第 1 战重新数 ⇒ 一圈一条线（圈末 done、既有「阶梯重置」判据成立时新建下一条，
  note=第 j 圈）。**一条线跑到黑 ⇒ 第二圈被吞 ⇒ 红。**
- **H5 唯一出口**（``abyss-progress-single-exit``）：``agent/abyss_impl.py`` 里**没有**
  ``[进度]`` 字面量（格式只有 ``reporting.format_progress`` 一份）；``display`` / 总量从
  配置传入（写死即红）；quiet 打开后面板只剩 ``[进度]`` 行、机制日志进日志文件。

## prove-red（``prove_red()``，每条都由**自己造的坏件**驱动）

1. 把 step 改成「从 1 数」 ⇒ **H1 红**；
2. 让账本 ``mark_done`` 谎报成功（step 不再由真实落盘决定）⇒ **H2 红**；
3. 把收工原因换成新造的「收工」⇒ **H3 红**；
4. 新一圈复用旧进度线（一条线跑到黑）⇒ **H4 红**；
5. 把 display/总量写死 ⇒ **H5 红**；再往源码里塞一句 ``[进度]`` 字面量（第二份格式）
   ⇒ **H5 红**。

★判据函数命名纪律（hooks_115 的打瞎见证）★：探针一律 ``probe_*``（返回 bool）、判据一律
``*_failures``（返回 list[str]）；``prove_red()`` 只经它们下结论，所以「打瞎判据 → prove_red
变红」成立，恒真判红。

跑法::

    .venv\\Scripts\\python.exe tools\\contract_hooks\\hooks_144.py
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
import sys
import tempfile
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

#: 本票的 task_id（与被驱动的识别器同一个：``_sync_task`` 见到新 task_id 会复位会话）。
TICKET = "#11"
TID = 11_000_003

HOOK_ID_BASELINE = "abyss-progress-start-baseline"
HOOK_ID_STEP = "abyss-progress-step-at-ledger-write"
HOOK_ID_DONE = "abyss-progress-done-reasons"
HOOK_ID_LAP = "abyss-progress-lap-lines"
HOOK_ID_SINGLE_EXIT = "abyss-progress-single-exit"

#: 主城帧（喂 ``abyss_giveup`` 时让它什么都不记账，只测收工那一段）。
_MAIN_CITY = [
    ("修行之道", [15, 725, 161, 45]),
    ("成长任务", [47, 368, 118, 33]),
    ("当前进度", [366, 928, 60, 20]),
    ("活动", [80, 1120, 62, 34]),
    ("领主战", [569, 1121, 78, 29]),
]


def _paths() -> None:
    for p in (str(AGENT_DIR), str(TOOLS_DIR), str(REPO_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _impl():
    """``agent/abyss_impl.py``（被守卫的实现）。"""
    _paths()
    import abyss_impl  # noqa: PLC0415

    return abyss_impl


def _scene():
    """``scene/abyss.py``（配置权威）。"""
    _paths()
    from scene import abyss as scene_abyss  # noqa: PLC0415

    return scene_abyss


def _reporting():
    _paths()
    import reporting  # noqa: PLC0415

    return reporting


# ---------------------------------------------------------------------------
# 沙箱：面板 / 账本 / 会话（探针反复跑也不许留脏状态，更不许写仓里的 progress.json）
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _panel():
    """把「面板」换成可读缓冲（生产里它 = 进程真实 stdout，``say`` 走它）。"""
    reporting = _reporting()
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
    path = Path(tempfile.mkdtemp(prefix="wf_hook144_")) / "progress.json"
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
                "unknown_count": 0,
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


def _feed(impl, state: str, items=None) -> None:
    """喂一帧给真实 ``_observe``（先戳掉「同状态 1.2s 内只记一次」的合并）。"""
    with impl._LOCK:
        impl._SESSION["last_observe_ts"] = 0.0
        impl._SESSION["last_state"] = None
    impl._observe(state, {}, list(items or []))


def _main_frame(stage: int, display: str = "深渊连战EX") -> list:
    """关卡选择页的合成 OCR 帧（本票只测进度行，页面判据不归这里管）。"""
    return [
        (f"{display}第{stage}战", [201, 1040, 237, 32]),
        ("不可续战", [300, 980, 90, 30]),
        ("推荐编成", [56, 1114, 96, 30]),
    ]


def _clear_stage(impl, stage: int, *, enter_battle: bool = True) -> None:
    """模拟「进战斗 → 结算」（结算页 = 记账点）。"""
    if enter_battle:
        _feed(impl, "abyss_battle")
    _feed(impl, "abyss_settle")


def _lines(impl) -> list:
    with impl._LOCK:
        line = impl._SESSION["progress"]
    return list(line.lines) if line is not None else []


def _lap(impl) -> int:
    with impl._LOCK:
        return int(impl._SESSION["lap"])


def _run(failures_fn):
    """跑判据函数，并吞掉机制日志（非 quiet 模式机制日志本来进 stdout；守卫只要结论）。"""
    with contextlib.redirect_stdout(io.StringIO()):
        return failures_fn()


# ---------------------------------------------------------------------------
# 收工驱动：真跑 ``AbyssGiveUpRecognition``（OCR 替换成主城帧，零设备）
# ---------------------------------------------------------------------------
class _CtxStub:
    """最小 context 桩（识别器只经被替换的 ``_ocr``）。"""


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


def _run_giveup(impl, param: dict | None = None):
    """返回 ``(AnalyzeResult, 机制 stdout)``。"""
    saved = impl._ocr
    impl._ocr = lambda context, image, entry="OcrTask": list(_MAIN_CITY)
    mech = io.StringIO()
    try:
        with contextlib.redirect_stdout(mech):
            got = impl.AbyssGiveUpRecognition().analyze(_CtxStub(), _RecoArgv(param or {}))
    finally:
        impl._ocr = saved
    return got, mech.getvalue()


# ---------------------------------------------------------------------------
# 判据：H1 起手用画面基准（不从 1 数）
# ---------------------------------------------------------------------------
def _baseline_failures() -> list:
    impl = _impl()
    msgs: list[str] = []
    for scene_id in ("abyss", "abyss_plain"):
        cfg = impl._cfg(scene_id)
        with _ledger_sandbox(impl), _panel() as panel:
            try:
                _reset(impl, scene_id)
                _feed(impl, "abyss_main", _main_frame(12, display=cfg.display))
                lines = _lines(impl)
                start_want = f"[进度] {cfg.display} 开始（共 {cfg.max_stages} 战）"
                if not lines:
                    msgs.append(f"{scene_id}: 首次观察基准没有 start（进度线是空的）")
                elif lines[0] != start_want:
                    msgs.append(f"{scene_id}: start 行 {lines[0]!r} != {start_want!r}（display/总量必须读配置）")
                if any("/30" in line for line in lines):
                    msgs.append(f"{scene_id}: start 阶段就出现了带数字的进度（{lines!r}）—— 还没打任何一战")
                _clear_stage(impl, 12)
                lines = _lines(impl)
                want = f"[进度] {cfg.display} 12/30 战（第 1 圈）"
                if not lines or lines[-1] != want:
                    msgs.append(
                        f"{scene_id}: 中途接管第一条数字线 {lines[-1] if lines else None!r} != {want!r}"
                        "（★必须用画面读数 12，不许从 1 数★）"
                    )
                if not impl.ledger.is_done(f"{cfg.ledger_scope}/stage/12"):
                    msgs.append(f"{scene_id}: 进度线出在记账之前 —— 账本里没有 {cfg.ledger_scope}/stage/12")
                shown = panel.getvalue()
                if not all(line in shown for line in lines):
                    msgs.append(f"{scene_id}: 进度行没有全部进面板（say 通道）：{shown[:120]!r}")
            finally:
                _reset(impl)
    # display 两个场景必须不同（同一实现 + 场景数据，不 fork）。
    if impl._cfg("abyss").display == impl._cfg("abyss_plain").display:
        msgs.append("深渊连战EX 与深渊连战 display 相同（进度行分不出是哪个场景）")
    return msgs


def probe_abyss_progress_start_baseline() -> bool:
    """H1：start 在首次观察基准；第一条数字线 = 画面读数；display/总量从配置读。"""
    msgs = _run(_baseline_failures)
    if msgs:
        print("  [11] 进度起手不是「画面基准」：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [11] 起手：start 在首次观察基准；第一批数字线 = 画面读数 12/30（EX 与 plain 各一份）")
    return True


# ---------------------------------------------------------------------------
# 判据：H2 step 落在记账点（账本落盘之后；重复/已记的战不多出线）
# ---------------------------------------------------------------------------
def _step_order_failures(source: str) -> list:
    """静态：结算分支里 ``ledger.mark_done(...)`` 必须排在 ``_progress_step(...)`` 之前。"""
    msgs = []
    mark_at = source.find("_stage_key(cur, cfg))")
    step_at = source.find("_progress_step(cfg, cur)")
    if mark_at < 0:
        msgs.append("abyss_impl 里找不到结算记账点 _stage_key(cur, cfg)（守卫与实现脱节）")
    if step_at < 0:
        msgs.append("abyss_impl 里找不到结算处的 _progress_step(cfg, cur)（step 没接在记账点）")
    if mark_at >= 0 and step_at >= 0 and step_at < mark_at:
        msgs.append("_progress_step 排在 mark_done 之前 —— 进度会出在账本落盘之前（把 step 挪回记账之后）")
    return msgs


def _step_at_ledger_failures() -> list:
    impl = _impl()
    msgs: list[str] = []
    msgs.extend(_step_order_failures(Path(impl.__file__).read_text(encoding="utf-8")))
    with _ledger_sandbox(impl), _panel():
        try:
            _reset(impl)
            _feed(impl, "abyss_main", _main_frame(7))
            _clear_stage(impl, 7)
            lines = _lines(impl)
            want = "[进度] 深渊连战EX 7/30 战（第 1 圈）"
            if not lines or lines[-1] != want:
                msgs.append(f"第 7 战记账后 {lines[-1] if lines else None!r} != {want!r}")
            if not impl.ledger.is_done("abyss/stage/7"):
                msgs.append("第 7 战的进度线出了，但账本里没有 abyss/stage/7（记假账）")
            n_first = len(lines)
            _clear_stage(impl, 7)
            _clear_stage(impl, 7)
            if len(_lines(impl)) != n_first:
                msgs.append(f"同一战重复结算多出了进度线（{n_first} -> {len(_lines(impl))}）")
            # 账本里已记过的战（上一轮会话 / 中途接管）：mark_done=False ⇒ 不是本次的一步。
            impl.ledger.mark_done("abyss/stage/9")
            _feed(impl, "abyss_main", _main_frame(9))
            _clear_stage(impl, 9)
            if any("9/30" in line for line in _lines(impl)):
                msgs.append("账本里已记过的第 9 战被当成「本次新完成的一战」出线了")
            _feed(impl, "abyss_main", _main_frame(8))
            _clear_stage(impl, 8)
            lines = _lines(impl)
            want8 = "[进度] 深渊连战EX 8/30 战（第 1 圈）"
            if not lines or lines[-1] != want8:
                msgs.append(f"下一战 {lines[-1] if lines else None!r} != {want8!r}")
            _feed(impl, "abyss_main", _main_frame(30))
            _clear_stage(impl, 30)
            n_done = len(_lines(impl))
            _clear_stage(impl, 30)
            if len(_lines(impl)) != n_done:
                msgs.append("圈末收工之后结算帧还在出进度线（收工后必须静默）")
        finally:
            _reset(impl)
    return msgs


def probe_abyss_progress_step_at_ledger_write() -> bool:
    """H2：step 只在 ``{scope}/stage/{N}`` 落盘之后；重复/已记/收工后都不出线。"""
    msgs = _run(_step_at_ledger_failures)
    if msgs:
        print("  [11] 进度步进不在记账点：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [11] 步进：只在账本落盘之后出线；重复结算 / 已记过的战 / 收工后都不多出线")
    return True


# ---------------------------------------------------------------------------
# 判据：H3 收工原因复用既有文案（三处点名出口 + 页签全空）
# ---------------------------------------------------------------------------
def _done_reason_failures() -> list:
    impl = _impl()
    msgs: list[str] = []

    # (a) 已打完一圈：原因必须与机制日志里那句「一圈 N 层全清」同源。
    with _ledger_sandbox(impl), _panel():
        try:
            _reset(impl)
            _feed(impl, "abyss_main", _main_frame(30))
            mech = io.StringIO()
            with contextlib.redirect_stdout(mech):
                _clear_stage(impl, 30)
            lines = _lines(impl)
            want = "[进度] 深渊连战EX 收工：已打完第 30 战（一圈 30 层全清）"
            if not lines or lines[-1] != want:
                msgs.append(f"已打完一圈：收工行 {lines[-1] if lines else None!r} != {want!r}")
            if "★已打完第 30 战（一圈 30 层全清）★" not in mech.getvalue():
                msgs.append("已打完一圈：机制日志里没有既有那句「★已打完第 30 战（一圈 30 层全清）★」")
        finally:
            _reset(impl)

    # (b) 零进度超时 / (c) 无新关卡：原因 = 既有 reason（与 detail.reason、机制日志同一句）。
    for label, session_mx, ago, zero_sec, want in (
        ("零进度超时", 0, 400.0, 300, "300s 一场都没有完成（关卡打不过？）"),
        ("无新关卡", 5, 1000.0, 300, "900s 无新关卡完成"),
    ):
        with _ledger_sandbox(impl), _panel():
            try:
                _reset(impl)
                _feed(impl, "abyss_main", _main_frame(3))
                with impl._LOCK:
                    impl._SESSION["session_max_done"] = session_mx
                    impl._SESSION["last_progress_ts"] = time.monotonic() - ago
                got, mech = _run_giveup(
                    impl, {"zero_progress_sec": zero_sec, "no_progress_sec": 900}
                )
                detail = getattr(got, "detail", None) or {}
                if detail.get("reason") != want:
                    msgs.append(f"{label}: detail.reason={detail.get('reason')!r} != 既有 {want!r}")
                lines = _lines(impl)
                want_line = f"[进度] 深渊连战EX 收工：{want}"
                if not lines or lines[-1] != want_line:
                    msgs.append(f"{label}: 面板收工行 {lines[-1] if lines else None!r} != {want_line!r}")
                if f"收工 —— {want}" not in mech:
                    msgs.append(f"{label}: 面板与机制日志不是同一句原因（机制日志里找不到）")
            finally:
                _reset(impl)

    # (d) 既有 giveup 的另一条原因（页签三连空）也进面板，文案来自真源。
    with _ledger_sandbox(impl), _panel():
        try:
            _reset(impl)
            _feed(impl, "abyss_main", _main_frame(3))
            empty_reason = str(impl.ZHONGSHI_EMPTY_REASON)
            with impl._LOCK:
                impl._SESSION["giveup_reason"] = empty_reason
            got, _mech = _run_giveup(impl)
            lines = _lines(impl)
            if (getattr(got, "detail", None) or {}).get("reason") != empty_reason:
                msgs.append("页签全空：detail.reason 不是真源 ZHONGSHI_EMPTY_REASON")
            if not lines or lines[-1] != f"[进度] 深渊连战EX 收工：{empty_reason}":
                msgs.append("页签全空：收工原因没有带进面板（用户看不出为什么停）")
        finally:
            _reset(impl)

    # (e) 同一条收工原因重复回来（同一帧被重复观察两次）⇒ 面板只许有一行「收工：」。
    with _ledger_sandbox(impl), _panel():
        try:
            _reset(impl)
            _feed(impl, "abyss_main", _main_frame(3))
            with impl._LOCK:
                impl._SESSION["session_max_done"] = 0
                impl._SESSION["last_progress_ts"] = time.monotonic() - 400.0
            param = {"zero_progress_sec": 300, "no_progress_sec": 900}
            _run_giveup(impl, param)
            _run_giveup(impl, param)
            done_lines = [line for line in _lines(impl) if "收工：" in line]
            if len(done_lines) != 1:
                msgs.append(f"同一条收工原因重复回来出了 {len(done_lines)} 行收工：{done_lines!r}")
        finally:
            _reset(impl)
    return msgs


def probe_abyss_progress_done_reasons() -> bool:
    """H3：三处点名收工出口（+ 页签全空）都带出既有原因文案，一字不新造。"""
    msgs = _run(_done_reason_failures)
    if msgs:
        print("  [11] 收工原因没有复用既有文案：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [11] 收工：已打完一圈 / 零进度 / 无新关卡 / 页签全空 都带出既有 reason（面板与机制日志同一句）")
    return True


# ---------------------------------------------------------------------------
# 判据：H4 按圈分段（一圈一条线；第二圈不许被单调去重吞掉）
# ---------------------------------------------------------------------------
def _lap_lines_failures() -> list:
    impl = _impl()
    msgs: list[str] = []
    with _ledger_sandbox(impl), _panel():
        try:
            _reset(impl)
            _feed(impl, "abyss_main", _main_frame(30))
            _clear_stage(impl, 30)
            if not any("收工：已打完第 30 战" in line for line in _lines(impl)):
                msgs.append(f"第一圈没有收工（{_lines(impl)!r}）")
            if _lap(impl) != 1:
                msgs.append(f"开局圈次 {_lap(impl)} != 1")
            # 阶梯重置 = 既有判据（画面回第 1 战且本次已推进 ≥2 战）。
            _feed(impl, "abyss_main", _main_frame(1))
            if _lap(impl) != 2:
                msgs.append(f"阶梯重置后圈次 {_lap(impl)} != 2（新一圈没有开始）")
            lines = _lines(impl)
            want_start = "[进度] 深渊连战EX 开始（共 30 战）"
            if not lines or lines[-1] != want_start:
                msgs.append(f"新一圈没有 start 新进度线（最后一行 {lines[-1] if lines else None!r}）")
            _clear_stage(impl, 1)
            lines = _lines(impl)
            want = "[进度] 深渊连战EX 1/30 战（第 2 圈）"
            if not lines or lines[-1] != want:
                msgs.append(
                    f"第二圈第 1 战 {lines[-1] if lines else None!r} != {want!r}"
                    "（★一条线跑到黑会被单调去重吞掉★）"
                )
            if not impl.ledger.is_done("abyss/stage/1"):
                msgs.append("第二圈第 1 战没有重新落在账本里（重置后的记账）")
        finally:
            _reset(impl)
    return msgs


def probe_abyss_progress_lap_lines() -> bool:
    """H4：一圈一条进度线；既有「阶梯重置」判据成立时新建下一条（第 2 圈 1/30）。"""
    msgs = _run(_lap_lines_failures)
    if msgs:
        print("  [11] 进度线没有按圈分段：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [11] 按圈分段：圈末 done、阶梯重置后新建一条（第二圈 1/30 不被单调去重吞掉）")
    return True


# ---------------------------------------------------------------------------
# 判据：H5 唯一出口（格式只有 reporting 一份 / display+总量从配置读 / quiet 分流）
# ---------------------------------------------------------------------------
def _function_text(source: str, name: str) -> str:
    """取某个顶层函数的源码片段（找不到返回空串）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _format_literals(source: str) -> list:
    """源码里**非 docstring** 的字符串常量中含「进度行字面量」的那些。

    ★只认真字符串常量★：注释 / docstring 提到 ``[进度]`` 是文档（讲清楚纪律），
    真正会造成「第二份格式」的是**代码里拼出来的字符串**。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["<源码无法解析>"]
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_ids.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in doc_ids
        and "[进度]" in node.value
    ]


def _source_failures(source: str) -> list:
    """静态判据：进度行只能在 :mod:`reporting` 拼；display/总量必须从配置读。"""
    impl = _impl()
    msgs: list[str] = []
    if not source:
        return ["abyss_impl.py 读不出源码 —— 静态守卫失效"]
    leaked = _format_literals(source)
    if leaked:
        msgs.append(
            f"abyss_impl.py 的代码里拼了进度行字面量 {leaked[:2]!r} —— 第二份格式"
            "（§B：格式只有 reporting.format_progress 一份）"
        )
    if "reporting.Progress(" not in source:
        msgs.append("abyss_impl.py 没有通过 reporting.Progress 出进度行（出口不止 reporting 一处）")
    body = _function_text(source, "_new_progress")
    if not body:
        msgs.append("abyss_impl.py 缺 _new_progress（进度线的构造点被拿掉了）")
    else:
        if "cfg.display" not in body:
            msgs.append("_new_progress 没有用 cfg.display（display 写死了）")
        if "cfg.max_stages" not in body:
            msgs.append("_new_progress 没有用 cfg.max_stages（总量写死了）")
        if re.search(r"Progress\(\s*[\"']", body):
            msgs.append("_new_progress 给 reporting.Progress 传了字面量场景名（display 必须从配置读）")
    if re.search(r"max_stages\s*=\s*\d+", source):
        msgs.append("abyss_impl.py 把 max_stages 写成了数字（总量必须从配置读）")
    if getattr(impl, "PROGRESS_UNIT", None) != "战":
        msgs.append(f"abyss_impl.PROGRESS_UNIT={getattr(impl, 'PROGRESS_UNIT', None)!r} != '战'（§C 口径）")
    return msgs


def _single_exit_failures() -> list:
    impl = _impl()
    reporting = _reporting()
    msgs = _source_failures(Path(impl.__file__).read_text(encoding="utf-8"))

    # (a) display / 总量 / note 真的从配置与圈次来（换成桩配置，行的每一段都要跟着变）。
    stub = type("_StubCfg", (), {"display": "测试场景X", "max_stages": 7})()
    with _panel() as panel:
        line = impl._new_progress(stub, 2)
        line.start()
        line.step(3)
        lines = list(line.lines)
    want = ["[进度] 测试场景X 开始（共 7 战）", "[进度] 测试场景X 3/7 战（第 2 圈）"]
    if lines != want:
        msgs.append(f"配置驱动：进度线 {lines!r} != {want!r}（display/总量/圈次必须来自配置）")
    if not all(item in panel.getvalue() for item in lines):
        msgs.append("配置驱动的进度行没有进面板")

    # (b) quiet：#142 的一次重定向对深渊生效 —— 面板只剩 [进度]，机制日志进日志文件。
    log = Path(tempfile.mkdtemp(prefix="wf_hook144_log_")) / "agent.log"
    with _ledger_sandbox(impl), _panel() as panel:
        try:
            _reset(impl)
            ok = reporting.set_quiet(True, log)
            try:
                _feed(impl, "abyss_main", _main_frame(12))
                _clear_stage(impl, 12)
            finally:
                reporting.set_quiet(False)
            body = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            shown = panel.getvalue()
        finally:
            _reset(impl)
    if ok is not True:
        msgs.append("quiet 没能打开（日志文件打不开 ⇒ 面板会被机制日志刷满）")
    if "★首次观察基准：画面第 12 战★" not in body or "第 12 战完成" not in body:
        msgs.append("quiet 之后机制日志没有落盘（点击 / 账本 / 收工必须进 debug 日志）")
    if "[abyss]" in shown:
        msgs.append("quiet 之后机制日志仍漏进面板（静音没盖住深渊）")
    shown_lines = [line for line in shown.strip().splitlines() if line.strip()]
    if not shown_lines or not all(line.startswith("[进度] ") for line in shown_lines):
        msgs.append(f"quiet 之后面板里不只有 [进度] 行：{shown[:160]!r}")
    if len(shown_lines) != 2:
        msgs.append(f"quiet 之后面板应有 2 条进度行（start + 12/30），实际 {len(shown_lines)}：{shown_lines!r}")
    return msgs


def probe_abyss_progress_single_exit() -> bool:
    """H5：格式唯一（无 [进度] 字面量）、display/总量从配置读、quiet 后面板只剩 [进度]。"""
    msgs = _run(_single_exit_failures)
    if msgs:
        print("  [11] 进度行不是「唯一出口 / 配置驱动」：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [11] 唯一出口：无 [进度] 字面量、display/总量从配置读、quiet 后面板只剩 [进度]、机制日志落盘")
    return True


HOOKS = [
    (
        HOOK_ID_BASELINE,
        TICKET,
        "#11：深渊进度线在首次观察基准 start；第一条数字线 = 画面读数（中途接管 12/30，不从 1 数）；"
        "display/总量从 scene.abyss 读（深渊连战EX / 深渊连战各一份）",
        probe_abyss_progress_start_baseline,
    ),
    (
        HOOK_ID_STEP,
        TICKET,
        "#11：step 只在「第 N 战」记账成功处（{scope}/stage/N 落盘之后）出线；同一战重复结算 / "
        "账本已记过的战 / 圈末收工后都不多出线；源码顺序 mark_done 先于 _progress_step",
        probe_abyss_progress_step_at_ledger_write,
    ),
    (
        HOOK_ID_DONE,
        TICKET,
        "#11：三处点名收工出口（零进度超时 / 无新关卡 / 已打完一圈）+ 页签全空都调用 "
        "Progress.done(既有 reason)，面板收工行与机制日志同一句话（不新造文案）",
        probe_abyss_progress_done_reasons,
    ),
    (
        HOOK_ID_LAP,
        TICKET,
        "#11：一圈一条进度线（Progress.step 单调去重，第二圈 1..30 否则会被吞）；"
        "圈次只由既有「阶梯重置」判据推进，note=第 j 圈",
        probe_abyss_progress_lap_lines,
    ),
    (
        HOOK_ID_SINGLE_EXIT,
        TICKET,
        "#11：进度行唯一出口 = reporting（abyss_impl 无 [进度] 字面量）；display/总量从配置读；"
        "quiet 后面板只剩 [进度]、机制日志进 debug/agent.log",
        probe_abyss_progress_single_exit,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验：每条都由**自己造的坏件**驱动，要求对应守卫变红
# ---------------------------------------------------------------------------
def _expect_red(label: str, probe) -> bool:
    """装好坏件后跑 ``probe``；返回「它确实报红」。"""
    red = probe() is False
    print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红（守卫有灵敏度）' if red else '仍绿（守卫是假的）'}")
    return red


def _expect_source_red(label: str, mutated_source: str) -> bool:
    """静态破坏实验：把坏源码喂给 ``_source_failures``，要求它报出问题。"""
    msgs = _source_failures(mutated_source)
    red = len(msgs) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}")
    return red


def prove_red() -> bool:
    """五条破坏实验（全部在内存里改属性 / 造坏源码，跑完还原）。"""
    impl = _impl()
    print("hooks_144 prove-red：逐一装坏件，要求守卫各自变红")
    green = (
        probe_abyss_progress_start_baseline() is True
        and probe_abyss_progress_step_at_ledger_write() is True
        and probe_abyss_progress_done_reasons() is True
        and probe_abyss_progress_lap_lines() is True
        and probe_abyss_progress_single_exit() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：五条守卫全绿")
    if not green:
        return False

    real_new = impl._new_progress
    real_progress_new = impl._progress_new
    real_step = impl._progress_step
    real_done = impl._progress_done
    real_mark = getattr(impl.ledger, "mark_done", None)
    checks: list[bool] = []
    try:
        # ① 把 step 改成「从 1 数」（丢掉画面/账面的真实战号）。
        impl._progress_step = lambda cfg, stage_no: real_step(cfg, 1)
        checks.append(_expect_red("把 step 改成从 1 数（12/30 → 1/30）", probe_abyss_progress_start_baseline))
    finally:
        impl._progress_step = real_step

    try:
        # ② 让账本 mark_done 谎报成功 —— step 不再由「真实落盘」决定。
        impl.ledger.mark_done = lambda key: True
        checks.append(
            _expect_red(
                "账本 mark_done 谎报成功（step 不再由真实落盘决定）",
                probe_abyss_progress_step_at_ledger_write,
            )
        )
    finally:
        if real_mark is not None:
            impl.ledger.mark_done = real_mark

    try:
        # ③ 收工原因换成新造的一句（丢掉既有 reason 文案）。
        def _broken_done(cfg, reason):  # noqa: ANN001
            with impl._LOCK:
                line = impl._SESSION["progress"]
                lap = int(impl._SESSION["lap"])
                if line is None:
                    line = real_new(cfg, lap)
                    impl._SESSION["progress"] = line
            return line.done("收工")

        impl._progress_done = _broken_done
        checks.append(_expect_red("收工原因换成新造的『收工』", probe_abyss_progress_done_reasons))
    finally:
        impl._progress_done = real_done

    try:
        # ④ 一条线跑到黑：新一圈复用旧进度线（第二圈 1..30 被单调去重吞掉）。
        def _broken_new(cfg):  # noqa: ANN001
            with impl._LOCK:
                line = impl._SESSION["progress"]
                if line is None:
                    line = real_new(cfg, int(impl._SESSION["lap"]))
                    impl._SESSION["progress"] = line
                    start = True
                else:
                    start = False
            if start:
                line.start()
            return line

        impl._progress_new = _broken_new
        checks.append(_expect_red("新一圈复用旧进度线（一条线跑到黑）", probe_abyss_progress_lap_lines))
    finally:
        impl._progress_new = real_progress_new

    try:
        # ⑤ display / 总量写死（不读配置）。
        reporting = _reporting()

        def _broken_literal(cfg, lap):  # noqa: ANN001
            return reporting.Progress("深渊连战EX", total=30, unit="战", note=f"第 {int(lap)} 圈")

        impl._new_progress = _broken_literal
        checks.append(_expect_red("把 display/总量写死（不读配置）", probe_abyss_progress_single_exit))
    finally:
        impl._new_progress = real_new

    # ⑥ 静态坏源码：塞一句 [进度] 字面量（第二份格式）。
    source = Path(impl.__file__).read_text(encoding="utf-8")
    checks.append(
        _expect_source_red(
            "往源码里塞 `[进度]` 字面量（第二份格式）",
            source + '\n_LEAK = "[进度] 深渊连战EX 1/30 战"\n',
        )
    )
    # ⑦ 静态坏源码：把 total=cfg.max_stages 改成写死 30。
    checks.append(
        _expect_source_red(
            "把 _new_progress 的总量改成写死的 30",
            source.replace("total=cfg.max_stages,", "total=30,", 1),
        )
    )

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


def main() -> int:
    print("真实实现（agent/abyss_impl.py）：")
    bad = []
    for hook_id, _ticket, _why, probe in HOOKS:
        ok = probe() is True
        print(f"  [{'PASS' if ok else 'FAIL'}] {hook_id}")
        if not ok:
            bad.append(hook_id)
    if bad:
        print("结果：★守卫失败★ " + ", ".join(bad))
        return 1
    return 0 if prove_red() else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
