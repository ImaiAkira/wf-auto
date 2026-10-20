# -*- coding: utf-8 -*-
"""#143（map #7 / 票 #8）：五重决战的**进度行** + 两个输出出口委托 :mod:`reporting`。

## 为什么有这张票

运维要求「五重决战 / 深渊等模式要显示进度」。裁决与唯一口径在
``docs/spec/progress-visibility.md``：面板只看**本次任务的步进**；进度行的格式只允许由
``agent/reporting.py::format_progress`` 实现一次。

本票的 lane 是**五重决战**：

* ``_say`` / ``_log`` **委托** ``reporting.say`` / ``reporting.log``，同时保留 #86 的
  ``debug/wuchong_agent.log`` 落盘与 ``QUIET`` 语义（``hooks_86`` 的
  ``wuchong-user-output-quiet`` 契约不许动）；
* ``reporting.Progress("五重决战", total=打几次, unit="次", note="打几次=N")``：
  - ``start()`` —— 任务开始、读到 ``target_fights`` 时；
  - ``step(n)`` —— **进入一场战斗**时（#76 的计数点，规格 B2；★一个字都不许搬到结算页★）；
  - ``done(reason)`` —— 收工兜底出口（``WuchongGiveUp``）把既有 reason 原文带出来。

## 契约（守卫口径）

- **P1 起点**（``wuchong-progress-start-at-target``）：任务开始读到「打几次」→
  ``[进度] 五重决战 开始（共 N 次）``；同一任务只一条，重复 tick 不刷屏。
- **P2 步进**（``wuchong-progress-step-at-fight-entry``）：**进入一场战斗** →
  ``[进度] 五重决战 i/N 次（打几次=N）``；结算页**不出**步进；``fights_done`` 与账本
  ``wuchong/fight/{n}`` 的口径不变（#76）。
- **P3 收工**（``wuchong-progress-done-carries-reason``）：``WuchongGiveUp`` 的既有 reason
  **原文**进 ``[进度] 五重决战 收工：<reason>``（不新造文案），旧的
  ``五重决战：收工 —— reason`` 照旧（#86 / hooks_87）。
- **P4 格式唯一**（``wuchong-progress-no-handmade-format``）：``wuchong_impl`` 源码里没有
  第二份 ``[进度]`` 拼接（docstring 不算）。
- **P5 委托**（``wuchong-say-log-delegate-reporting``）：``_say`` 真的调 ``reporting.say``、
  ``_log`` 真的调 ``reporting.log``；``debug/wuchong_agent.log`` 逐行落盘、``QUIET`` 时机制
  日志不进 stdout、面板吞不掉 —— #86 的三条语义都还在。

## prove-red（5 条破坏实验，全部在内存里改属性 / 造临时源码副本）

1. ``_start_progress`` 变哑 → **P1 红**；
2. 把计数点从「战斗」搬到「结算」（``WUCHONG_BATTLE`` 指向 ``WUCHONG_SETTLE``）→ **P2 红**；
3. ``_done_progress`` 丢掉 reason → **P3 红**；
4. 造一份「自己拼 ``[进度]``」的源码副本 → **P4 红**；
5. ``_say`` / ``_log`` 改回裸 ``print``（不委托 reporting）→ **P5 红**。

跑法::

    .venv\\Scripts\\python.exe tools\\contract_hooks\\hooks_143.py
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"

#: 模式页（带门票读数）—— 与 hooks_86 的 ``_MODE_TICKETS`` 同一份假帧。
MODE_ITEMS = [
    ("今天剩余次数x 3", [381, 922, 319, 42]),
    ("单人游戏", [100, 700, 150, 40]),
]
#: 真机合并框战斗 HUD（#74 证据帧）→ classify = wuchong_battle（= 进本场战斗）。
BATTLE_ITEMS = [("时间 29:30 分数 38629797530", [34, 1221, 402, 40])]

TID_START = 570_930_001
TID_STEP = 570_930_002
TID_DONE = 570_930_003


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _reporting():
    _paths()
    import reporting  # noqa: PLC0415

    return reporting


def _impl():
    _paths()
    import wuchong_impl  # noqa: PLC0415

    return wuchong_impl


class _Argv:
    """``CustomRecognition.analyze`` 的最小 argv 假件（字段与 hooks_86 的 ``_RecArgv`` 同形）。"""

    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


@contextlib.contextmanager
def _panel(reporting):
    """把「面板」换成可读缓冲（生产里它就是进程真实 stdout，见 ``reporting.say``）。"""
    old = reporting._REAL_STDOUT
    buf = io.StringIO()
    reporting._REAL_STDOUT = buf
    try:
        yield buf
    finally:
        reporting._REAL_STDOUT = old


@contextlib.contextmanager
def _isolated(impl, reporting):
    """把会话 / 账本 / 日志路径 / 进度线钉成**已知起点**，离开时逐项还原。

    ★必须还原★：``test_offline_contract`` 会在同一进程里依次跑所有 hook 的探针，
    任何一项漏还原都会污染别人的判据（#115 的教训）。
    """
    saved_session = dict(impl._SESSION)
    saved_progress = impl._PROGRESS
    saved_log_path = impl._LOG_PATH
    saved_quiet = impl.QUIET
    saved_ocr = impl._ocr
    saved_ledger = getattr(impl.ledger, "_DEFAULT", None)
    saved_rep_quiet = reporting.is_quiet()
    if saved_rep_quiet:  # 防御：别的探针若忘了关静音，先关掉才能看 stdout 取证
        reporting.set_quiet(False)
    td = Path(tempfile.mkdtemp(prefix="hooks_143_"))
    impl.ledger.set_file(td / "progress.json")
    impl.ledger.reset(impl.LEDGER_SCOPE)
    impl._LOG_PATH = td / "wuchong_agent.log"
    impl._PROGRESS = None
    with impl._LOCK:
        # task_id=None → 下一次 analyze 的 _sync_task 真的做一次换任务复位。
        impl._SESSION["task_id"] = None
        # _sync_task 不复位这几项（由 giveup 每轮现读；hooks_86 也是显式钉的）。
        impl._SESSION["said_target"] = False
        impl._SESSION["settle_said"] = False
        impl._SESSION["remaining_plays"] = None
        impl._SESSION["unknown_streak"] = 0
        impl._SESSION["room_beat_ts"] = 0.0
        impl._SESSION["last_state"] = None
        impl._SESSION["last_observe_ts"] = 0.0
        impl._SESSION["fights_done"] = 0
        impl._SESSION["target_fights"] = 0
        impl._SESSION["in_fight"] = False
        impl._SESSION["battle_had_continue"] = False
        impl._SESSION["start_ts"] = time.monotonic()
        impl._SESSION["last_progress_ts"] = time.monotonic()
    try:
        yield td
    finally:
        impl._ocr = saved_ocr
        impl._PROGRESS = saved_progress
        impl.set_quiet(saved_quiet)
        impl._LOG_PATH = saved_log_path
        with impl._LOCK:
            impl._SESSION.clear()
            impl._SESSION.update(saved_session)
        impl.ledger.set_file(None)
        if saved_ledger is not None:
            impl.ledger._DEFAULT = saved_ledger
        if saved_rep_quiet:
            reporting.set_quiet(True)


def _run_giveup(impl, reporting, items, target, tid):
    """跑一次真实 ``WuchongGiveUpRecognition.analyze``；返回 (结果, 面板, 被重定向的 stdout)。"""
    impl._ocr = lambda context, image, entry="OcrTask": list(items)
    out = io.StringIO()
    with _panel(reporting) as panel, contextlib.redirect_stdout(out):
        res = impl.WuchongGiveUpRecognition().analyze(
            None,
            _Argv(tid, {"ocr_entry": "OcrTask", "room_wait_sec": 300,
                        "no_progress_sec": 900, "target_fights": target}),
        )
    return res, panel.getvalue(), out.getvalue()


def _observe(impl, reporting, state) -> None:
    """直接喂一个分类结果给 ``_observe``（hooks_74 同款单元缝；不经过 OCR）。"""
    with _panel(reporting), contextlib.redirect_stdout(io.StringIO()):
        impl._observe(state, {}, [])


# ---------------------------------------------------------------------------
# P1：start 行（任务开始、读到「打几次」）
# ---------------------------------------------------------------------------
def _start_failures(impl, reporting=None) -> list:
    msgs: list[str] = []
    rep = reporting or _reporting()
    with _isolated(impl, rep):
        _run_giveup(impl, rep, MODE_ITEMS, 3, TID_START)
        expect = ["[进度] 五重决战 开始（共 3 次）"]
        lines = list(impl._progress().lines)
        if lines != expect:
            msgs.append(f"读到「打几次」没打出 start 行：{lines!r}（应 {expect!r}）")
        _run_giveup(impl, rep, MODE_ITEMS, 3, TID_START)
        again = list(impl._progress().lines)
        if again != expect:
            msgs.append(f"同一任务重复 tick 又出了进度行：{again!r}")
        # ★换任务：进度线按任务重开★（不能依赖 #86 的 ``said_target`` 闩锁 —— 它跨任务不复位；
        #   可靠性来自 _sync_task 把 _PROGRESS 置 None + Progress.start 自己的去重）。
        _run_giveup(impl, rep, MODE_ITEMS, 3, TID_START + 1)
        next_lines = list(impl._progress().lines)
        if next_lines != expect:
            msgs.append(f"换任务后没有新的 start 行：{next_lines!r}（应 {expect!r}）")
    return msgs


def probe_wuchong_progress_start() -> bool:
    return _start_failures(_impl()) == []


# ---------------------------------------------------------------------------
# P2：step 行（进入一场战斗 = 一步；结算页不步进）
# ---------------------------------------------------------------------------
def _step_failures(impl, reporting=None) -> list:
    msgs: list[str] = []
    rep = reporting or _reporting()
    with _isolated(impl, rep):
        _run_giveup(impl, rep, MODE_ITEMS, 2, TID_STEP)
        _run_giveup(impl, rep, BATTLE_ITEMS, 2, TID_STEP)
        expect = [
            "[进度] 五重决战 开始（共 2 次）",
            "[进度] 五重决战 1/2 次（打几次=2）",
        ]
        lines = list(impl._progress().lines)
        if lines != expect:
            msgs.append(f"进入一场战斗没打出 step 行：{lines!r}（应 {expect!r}）")
        with impl._LOCK:
            fights = int(impl._SESSION["fights_done"])
        if fights != 1:
            msgs.append(f"进场计数被改了：fights_done={fights}（应 1；规格 B2「打几次 = 进场几次」）")
        keys = impl.ledger.scope(impl.FIGHT_LEDGER_PREFIX)
        if keys != ["wuchong/fight/1"]:
            msgs.append(f"场次账本 key 被改了：{keys!r}（应 ['wuchong/fight/1']）")
        # ★计数点必须在「进场」不是「结算」★：结算帧不许再出一步。
        _observe(impl, rep, impl.WUCHONG_SETTLE)
        settled = list(impl._progress().lines)
        if settled != expect:
            msgs.append(f"结算页也出了一步（计数点被搬到结算）：{settled!r}")
        # 真正离开本场后再进一场 → 第二场照常一步。
        _observe(impl, rep, impl.WUCHONG_TEAM)
        _run_giveup(impl, rep, BATTLE_ITEMS, 2, TID_STEP)
        last = impl._progress().lines[-1] if impl._progress().lines else ""
        if last != "[进度] 五重决战 2/2 次（打几次=2）":
            msgs.append(f"第二场没继续步进：{last!r}")
    return msgs


def probe_wuchong_progress_step() -> bool:
    return _step_failures(_impl()) == []


# ---------------------------------------------------------------------------
# P3：done 行（收工兜底出口带既有 reason 原文）
# ---------------------------------------------------------------------------
def _done_failures(impl, reporting=None) -> list:
    msgs: list[str] = []
    rep = reporting or _reporting()
    with _isolated(impl, rep):
        _run_giveup(impl, rep, MODE_ITEMS, 1, TID_DONE)
        _run_giveup(impl, rep, BATTLE_ITEMS, 1, TID_DONE)
        _observe(impl, rep, impl.WUCHONG_TEAM)             # 本场收场（收工时机 #76）
        res, _panel_text, out = _run_giveup(impl, rep, MODE_ITEMS, 1, TID_DONE)
        reason = str((res.detail or {}).get("reason") or "")
        if res.box != [0, 0, 0, 0]:
            msgs.append(f"打够了却没命中既有收工出口：{res.detail!r}")
        if reason != "已打够 1 次（打几次=1）":
            msgs.append(f"收工 reason 被改写了：{reason!r}（应沿用既有文案）")
        expected = f"[进度] 五重决战 收工：{reason}"
        lines = list(impl._progress().lines)
        if not lines or lines[-1] != expected:
            msgs.append(f"done 行不是「收工：<既有 reason>」：{lines!r}（应 {expected!r}）")
        if impl._progress().done_reason != reason:
            msgs.append(f"done 没把 reason 交给进度线：{impl._progress().done_reason!r}")
        if f"五重决战：收工 —— {reason}" not in out:
            msgs.append(f"旧的「五重决战：收工 —— 原因」没打出来（#86 / hooks_87 契约）：{out!r}")
        before = len(lines)
        _run_giveup(impl, rep, MODE_ITEMS, 1, TID_DONE)
        if len(impl._progress().lines) != before:
            msgs.append(f"done 之后又出了进度行：{impl._progress().lines!r}")
    return msgs


def probe_wuchong_progress_done() -> bool:
    return _done_failures(_impl()) == []


# ---------------------------------------------------------------------------
# P4：格式唯一（场景里不许自己拼 [进度]）
# ---------------------------------------------------------------------------
def _format_failures(impl=None, path=None) -> list:
    """源码里有没有**第二份** ``[进度]`` 拼接（docstring 不计）。"""
    impl = impl or _impl()
    source = Path(path or impl.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    bad = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "[进度]" in node.value
        and id(node) not in docstrings
    ]
    return [f"场景里自己拼 [进度]（第二份格式，真源只能是 reporting.format_progress）：{bad[:3]}"] if bad else []


def probe_wuchong_progress_format() -> bool:
    return _format_failures(_impl()) == []


# ---------------------------------------------------------------------------
# P5：_say / _log 委托 reporting（且 #86 的三条语义不变）
# ---------------------------------------------------------------------------
def _delegate_failures(impl, reporting=None) -> list:
    msgs: list[str] = []
    rep = reporting or _reporting()
    with _isolated(impl, rep) as td:
        log = td / "wuchong_agent.log"
        seen = {"say": [], "log": []}
        real_say, real_log = rep.say, rep.log
        try:
            rep.say = lambda text="": seen["say"].append(text)
            rep.log = lambda text="": seen["log"].append(str(text))
            impl._say("用户可见行")
            impl._log("[wuchong] 机制行")
        finally:
            rep.say, rep.log = real_say, real_log
        if "用户可见行" not in seen["say"]:
            msgs.append("_say 没有委托 reporting.say（用户行进不了面板）")
        if "[wuchong] 机制行" not in seen["log"]:
            msgs.append("_log 没有委托 reporting.log（机制日志绕过了唯一出口）")
        body = _read(log)
        if "[say] 用户可见行" not in body or "[wuchong] 机制行" not in body:
            msgs.append(f"#86 的 debug/wuchong_agent.log 落盘变了：{body[:120]!r}")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            impl._log("[wuchong] 非静音机制行")
        if "[wuchong] 非静音机制行" not in out.getvalue():
            msgs.append("非静音时机制日志没进 stdout（离线取证 / 真机 runner 会失明）")

        real_quiet = impl.QUIET
        try:
            impl.set_quiet(True)
            quiet_out = io.StringIO()
            with _panel(rep) as panel, contextlib.redirect_stdout(quiet_out):
                impl._log("[wuchong] 静音机制行")
                impl._say("静音用户行")
            if "[wuchong] 静音机制行" in quiet_out.getvalue():
                msgs.append("QUIET 时机制日志仍进 stdout（#86 静音失效）")
            if "[wuchong] 静音机制行" not in _read(log):
                msgs.append("QUIET 时机制日志没落盘（#86 落盘路径失效）")
            if "静音用户行" not in panel.getvalue():
                msgs.append("QUIET 时面板被吞（#86 承重契约失效）")
        finally:
            impl.set_quiet(real_quiet)
    return msgs


def probe_wuchong_say_log_delegate() -> bool:
    return _delegate_failures(_impl()) == []


HOOKS = [
    (
        "wuchong-progress-start-at-target",
        "#8",
        "五重决战：任务开始读到「打几次」→ `[进度] 五重决战 开始（共 N 次）`（同一任务只一条）；"
        "进度行必须走 reporting.Progress（格式唯一）",
        probe_wuchong_progress_start,
    ),
    (
        "wuchong-progress-step-at-fight-entry",
        "#8",
        "五重决战：**进入一场战斗**（#76 计数点 / 规格 B2）→ `[进度] 五重决战 i/N 次（打几次=N）`；"
        "结算页不出步进，fights_done 与 wuchong/fight/{n} 账本口径不变",
        probe_wuchong_progress_step,
    ),
    (
        "wuchong-progress-done-carries-reason",
        "#8",
        "五重决战：收工兜底出口（WuchongGiveUp）把既有 reason **原文**交给 Progress.done"
        "（`[进度] 五重决战 收工：<reason>`）；旧「五重决战：收工 —— 原因」照旧（#86 / hooks_87）",
        probe_wuchong_progress_done,
    ),
    (
        "wuchong-progress-no-handmade-format",
        "#8",
        "五重决战：场景文件里不许自己拼 `[进度]` 字符串（唯一格式真源 = reporting.format_progress）",
        probe_wuchong_progress_format,
    ),
    (
        "wuchong-say-log-delegate-reporting",
        "#8",
        "五重决战：`_say` / `_log` **委托** reporting.say / reporting.log；#86 的 "
        "debug/wuchong_agent.log 逐行落盘、QUIET 时机制日志不进 stdout、面板吞不掉 —— 三条都不变",
        probe_wuchong_say_log_delegate,
    ),
]


# ---------------------------------------------------------------------------
# prove-red：5 条破坏实验（全部在内存里改属性 / 造临时源码副本，跑完还原）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    impl = _impl()
    rep = _reporting()
    print("hooks_143 prove-red：逐一破坏实现，要求五个守卫各自变红")
    green = (
        probe_wuchong_progress_start() is True
        and probe_wuchong_progress_step() is True
        and probe_wuchong_progress_done() is True
        and probe_wuchong_progress_format() is True
        and probe_wuchong_say_log_delegate() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：五个守卫全绿")
    if not green:
        for m in (
            _start_failures(impl, rep)
            + _step_failures(impl, rep)
            + _done_failures(impl, rep)
            + _format_failures(impl)
            + _delegate_failures(impl, rep)
        )[:6]:
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    # ① start 变哑 → P1 红
    real_start = impl._start_progress
    try:
        impl._start_progress = lambda target_fights: ""  # noqa: ARG005
        m1 = _start_failures(impl, rep)
        red1 = len(m1) > 0
        print(f"  [{'PASS' if red1 else 'FAIL'}] 关掉 start 进度线 -> {'红' if red1 else '仍绿'}"
              + (f"  {m1[0]}" if m1 else ""))
    finally:
        impl._start_progress = real_start
    checks.append(red1)

    # ② 计数点搬到结算页 → P2 红（规格 B2 / #76 的计数点不许动）
    real_battle = impl.WUCHONG_BATTLE
    try:
        impl.WUCHONG_BATTLE = impl.WUCHONG_SETTLE
        m2 = _step_failures(impl, rep)
        red2 = len(m2) > 0
        print(f"  [{'PASS' if red2 else 'FAIL'}] 把计数点从「战斗」搬到「结算」-> {'红' if red2 else '仍绿'}"
              + (f"  {m2[0]}" if m2 else ""))
    finally:
        impl.WUCHONG_BATTLE = real_battle
    checks.append(red2)

    # ③ done 丢掉既有 reason → P3 红
    real_done = impl._done_progress
    try:
        impl._done_progress = lambda reason: impl._progress().done("")  # noqa: ARG005
        m3 = _done_failures(impl, rep)
        red3 = len(m3) > 0
        print(f"  [{'PASS' if red3 else 'FAIL'}] done 丢掉既有 reason -> {'红' if red3 else '仍绿'}"
              + (f"  {m3[0]}" if m3 else ""))
    finally:
        impl._done_progress = real_done
    checks.append(red3)

    # ④ 造一份「自己拼 [进度]」的源码副本 → P4 红
    source = Path(impl.__file__).read_text(encoding="utf-8")
    needle = "    _step_progress(n)\n"
    broken_source = source.replace(
        needle,
        needle + '    _say("[进度] 五重决战 " + str(n) + " 次")\n',
        1,
    )
    broken_path = Path(tempfile.mkdtemp(prefix="hooks_143_broken_")) / "wuchong_impl_handmade.py"
    broken_path.write_text(broken_source, encoding="utf-8")
    m4 = _format_failures(impl, path=broken_path)
    red4 = len(m4) > 0 and broken_source != source
    print(f"  [{'PASS' if red4 else 'FAIL'}] 造一份自己拼 [进度] 的源码副本 -> {'红' if red4 else '仍绿'}"
          + (f"  {m4[0]}" if m4 else "  （锚点没命中：源码里的 _step_progress(n) 行变了？）"))
    checks.append(red4)

    # ⑤ _say / _log 改回裸 print（不委托 reporting）→ P5 红
    real_say, real_log = impl._say, impl._log
    try:
        impl._say = lambda msg: print(msg, flush=True)  # noqa: ARG005
        impl._log = lambda msg="": print(msg, flush=True)  # noqa: ARG005
        m5 = _delegate_failures(impl, rep)
        red5 = len(m5) > 0
        print(f"  [{'PASS' if red5 else 'FAIL'}] _say/_log 改回裸 print（不委托 reporting）-> "
              f"{'红' if red5 else '仍绿'}" + (f"  {m5[0]}" if m5 else ""))
    finally:
        impl._say, impl._log = real_say, real_log
    checks.append(red5)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


def main() -> int:
    probes = (
        ("wuchong-progress-start-at-target", probe_wuchong_progress_start),
        ("wuchong-progress-step-at-fight-entry", probe_wuchong_progress_step),
        ("wuchong-progress-done-carries-reason", probe_wuchong_progress_done),
        ("wuchong-progress-no-handmade-format", probe_wuchong_progress_format),
        ("wuchong-say-log-delegate-reporting", probe_wuchong_say_log_delegate),
    )
    print("真实实现（agent/wuchong_impl.py + agent/reporting.py）：")
    bad = [hook_id for hook_id, fn in probes if not fn()]
    for hook_id, _fn in probes:
        print(f"  [{'FAIL' if hook_id in bad else 'PASS'}] {hook_id}")
    if bad:
        print("结果：★守卫失败★ " + ", ".join(bad))
        return 1
    return 0 if prove_red() else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
