# -*- coding: utf-8 -*-
"""#141：把动作计数与业务进展接进 runner，让「有动作无进展」报警**真机生效**。

## 为什么有这张票

#140 把报警器造好了（``is_action_without_progress``：动作 ≥20 且业务进展 ≥180s 未推进），
但**没人给它喂数据**：``run_wuchong_live.py`` 起监管时只传 ``state_fn``，``actions`` 永远是
``null``，``progress_source`` 永远退回 ``state`` ⇒ 真机上「80 次滚动、0 个目标」照样一声不吭。
#140 的结案评论写得很清楚：「新报警要真机生效需 runner 提供动作计数与进展快照 —— 另开 #141」。

## 契约（守卫口径）

- **H1 接线生效**（``monitor-feed-actions-progress``）：跑 **80 次动作**（10 轮 × 8）而业务进展
  快照一直不动 ⇒ JSONL 里**恰好 1 条** ``★★ 有动作无进展 ★★``，行里
  ``actions_since_progress=80``、``progress_stalled_sec=180.0``，文本同时带「80 次动作」
  「180.0s」；心跳的 ``progress_source`` 必须是 ``progress_fn``（真接上了，不是退回 state）。
- **H2 不误报**（``monitor-feed-no-false-positive``）：业务进展每轮都在变 / 动作只有 10 次
  （<20）/ 动作计数**未接线** ⇒ 三条路径都必须是 0 条告警（未接线时 ``actions=null``，
  绝不拿「画面在动」凭空编动作）。
- **H3 失败语义**（``monitor-summary-error-fails-task``）：注入 ``summary.error`` ⇒
  ``runner.main()`` 打印 ✗ **且返回非零退出码**（CLI 入口 ``raise SystemExit(main())``）；
  正常收工仍返回 0 —— 不许「只打印一行 ✗ 然后正常退出」。
- **H4 未接线喊出来**（``monitor-unwired-is-loud``）：不传 ``actions_fn`` / ``progress_fn``
  ⇒ 日志必须含「未接线」+「有动作无进展报警不会触发」；接上时必须打
  ``已接线：actions_fn / progress_fn``。**静默降级 = 本次守卫要钉的那个洞**。

## 怎么假跑（不碰设备、不真睡）

驱动复用 ``tools/test_longrun_monitor.py`` 的假帧 + 假时钟（``FakeClock`` / ``solid_frame``），
但**入口走 runner 自己**：把 ``longrun_monitor.monitor_for_serial`` 换成工厂，返回一个用假
采集/假时钟构建的真 :class:`LongrunMonitor`，再调 ``run_wuchong_live.start_monitor()`` ——
所以「runner 是否把 actions_fn / progress_fn 传进监管」这条连接是被真实验证的，不是旁路。

## prove-red（破坏实验 4 条，全部在内存里）

1. 把 ``lords_impl.actions_total`` 换成恒 0（断掉动作计数）→ **H1 红**；
2. 把 ``lords_impl.progress_snapshot`` 换成恒定串（有进展也报）→ **H2 红**；
3. 把 ``run_wuchong_live.MONITOR_ERROR_EXIT`` 换成 0（只打印不非零）→ **H3 红**；
4. 删掉「未接线」警告文案（``MONITOR_UNWIRED_WARNING = ""``）→ **H4 红**。

    .venv\\Scripts\\python.exe tools\\contract_hooks\\hooks_141.py
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
for _path in (str(TOOLS_DIR), str(AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import longrun_monitor as lm  # noqa: E402
import test_longrun_monitor as tlm  # noqa: E402

HOOK_ID_WIRING = "monitor-feed-actions-progress"
HOOK_ID_NO_FALSE_POSITIVE = "monitor-feed-no-false-positive"
HOOK_ID_FAILURE_SEMANTICS = "monitor-summary-error-fails-task"
HOOK_ID_UNWIRED = "monitor-unwired-is-loud"

#: 与 #140 的判据真源对齐：20s 心跳；卡住阈值的秒数关掉（只看「有动作无进展」）。
INTERVAL = 20.0
STALL = 900.0
ACTIONS_PER_ROUND = 8
#: 10 轮（t=0..180）× 8 次 = **80 次动作**，恰好是 #140 现场（80 次滚动）的量级；
#: 第 10 轮（t=180）时 ``progress_stalled_sec=180`` 与动作数 80 同时达到阈值 → 唯一一条告警。
ROUNDS = 10
ACTIONS_AT_ALARM = ACTIONS_PER_ROUND * ROUNDS

#: 注入的收工自检错误（H3 要看它被 ✗ 打出来）。
ERROR_TEXT = "JSONL 为空（0 字节；守卫注入的收工自检失败）"


def _runner():
    """惰性 import runner（会被本模块当脚本跑，也会被 ``_load_module`` 扫描）。"""
    import run_wuchong_live  # noqa: PLC0415

    return run_wuchong_live


def _lords():
    import lords_impl  # noqa: PLC0415

    return lords_impl


# ---------------------------------------------------------------------------
# 假跑：runner.start_monitor + 假帧/假时钟
# ---------------------------------------------------------------------------
class _FakeBackend:
    """把 ``monitor_for_serial`` 换成「假采集 + 假时钟」的真 ``LongrunMonitor``。

    每轮采集时模拟真机这一轮发出的 ``actions_per_round`` 次滚动（走 ``lords_impl.note_action``
    —— 与真机 ``_click_hook`` / 滚动成功后的调用**同一个函数**）。
    """

    def __init__(self, *, rounds: int, actions_per_round: int, on_round, out_dir: Path, log_sink: list) -> None:
        self.rounds = int(rounds)
        self.actions_per_round = int(actions_per_round)
        self.on_round = on_round
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log = log_sink
        self.clock = tlm.FakeClock()
        self.calls = 0
        self.monitor = None

    def _capture(self):
        self.calls += 1
        lords = _lords()
        for _ in range(self.actions_per_round):
            lords.note_action("scroll")
        if self.on_round is not None:
            self.on_round(self.calls)
        if self.calls >= self.rounds and self.monitor is not None:
            self.monitor.stop()
        return tlm.solid_frame(40)

    def factory(self, serial, **kwargs):
        """``monitor_for_serial`` 的替身：吃 runner 传进来的接线参数，换成假采集/假时钟。"""
        kwargs.pop("out", None)            # 用临时目录，绝不污染 debug/longrun
        kwargs.pop("capture_timeout", None)
        mon = lm.LongrunMonitor(
            self._capture,
            serial=str(serial),
            out=self.out_dir,
            now=self.clock,
            wait=self.clock.advance,
            log=self.log.append,
            **kwargs,
        )
        self.monitor = mon
        return mon


@contextlib.contextmanager
def _fake_run(*, rounds: int = ROUNDS, actions_per_round: int = ACTIONS_PER_ROUND, on_round=None, wire: bool = True):
    """起一次「runner 真入口 + 假设备」的长跑，产出 JSONL / 日志 / 小结。

    ``wire=False`` = 模拟「没人给监管喂料」（不传 actions_fn / progress_fn）。
    """
    runner = _runner()
    root = Path(tempfile.mkdtemp(prefix="wf_hook141_"))
    log_sink: list = []
    backend = _FakeBackend(
        rounds=rounds,
        actions_per_round=actions_per_round,
        on_round=on_round,
        out_dir=root / "longrun",
        log_sink=log_sink,
    )
    saved = lm.monitor_for_serial
    lm.monitor_for_serial = backend.factory  # type: ignore[assignment]
    mon = None
    try:
        if wire:
            actions_fn, progress_fn, source = runner.monitor_feed()
        else:
            actions_fn, progress_fn, source = None, None, None
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            mon = runner.start_monitor(
                "fake-hook141",
                interval=INTERVAL,
                stall=STALL,
                actions_fn=actions_fn,
                progress_fn=progress_fn,
                feed_source=source,
            )
            mon.join(timeout=10.0)
            error = runner.finish_monitor()
        text = buf.getvalue()
        rows = tlm.read_jsonl(mon.jsonl_path) if mon is not None and mon.jsonl_path else []
        yield {
            "monitor": mon,
            "summary": mon.summary if mon is not None else None,
            "rows": rows,
            "heartbeats": tlm.heartbeats(rows),
            "text": text,
            "error": error,
            "log": log_sink,
        }
    finally:
        lm.monitor_for_serial = saved  # type: ignore[assignment]
        runner._MON["mon"] = None      # type: ignore[attr-defined]
        shutil.rmtree(root, ignore_errors=True)


def _alarm_rows(heartbeats: list) -> list:
    return [row for row in heartbeats if "★★ 有动作无进展" in (row.get("note") or "")]


# ---------------------------------------------------------------------------
# H1 接线生效：80 次动作 + 业务零进展 ⇒ 恰好一条告警
# ---------------------------------------------------------------------------
def _wiring_failures() -> list[str]:
    msgs: list[str] = []
    _lords().reset_sessions()                 # 业务快照从零开始（动作计数照旧跨场景累计）
    with _fake_run(rounds=ROUNDS, actions_per_round=ACTIONS_PER_ROUND, wire=True) as res:
        text = res["text"]
        if "已接线：actions_fn / progress_fn" not in text:
            msgs.append("起监管时没打「已接线：actions_fn / progress_fn」（接线不可见）")
        hb = res["heartbeats"]
        sources = {row.get("progress_source") for row in hb}
        if "progress_fn" not in sources:
            msgs.append(
                f"心跳的 progress_source={sorted(map(str, sources))}，不是 progress_fn —— "
                f"业务进展快照没接进监管（退回 state 判不了「业务零进展」）"
            )
        if any(row.get("actions") is None for row in hb):
            msgs.append("心跳里 actions=null —— 动作计数没接线，「有动作无进展」永远不触发")
        alarms = _alarm_rows(hb)
        if len(alarms) != 1:
            msgs.append(
                f"{ACTIONS_PER_ROUND * ROUNDS} 次动作 + 业务快照一直不动 ⇒ 应恰好 1 条告警，"
                f"实际 {len(alarms)} 条"
            )
        else:
            alarm = alarms[0]
            if alarm.get("actions_since_progress") != ACTIONS_AT_ALARM:
                msgs.append(
                    f"告警行动作数不是 {ACTIONS_AT_ALARM}：{alarm.get('actions_since_progress')!r}"
                )
            if alarm.get("progress_stalled_sec") != lm.NO_PROGRESS_SEC:
                msgs.append(
                    f"告警行停滞秒数不是 {lm.NO_PROGRESS_SEC}：{alarm.get('progress_stalled_sec')!r}"
                )
            note = alarm.get("note") or ""
            if f"{ACTIONS_AT_ALARM} 次动作" not in note or f"{lm.NO_PROGRESS_SEC:.1f}s" not in note:
                msgs.append(f"告警文本没有同时带动作数与停滞秒数：{note!r}")
        if res["summary"] is not None and res["summary"].no_progress_alarms != 1:
            msgs.append(f"summary.no_progress_alarms={res['summary'].no_progress_alarms}（应 1）")
        if not any("有动作无进展" in line for line in res["log"]):
            msgs.append("控制台没有高亮「有动作无进展」行（无人值守时看不见）")
        if res["error"] is not None:
            msgs.append(f"正常跑完却带收工自检错误：{res['error']}")
    return msgs


def probe_actions_progress_wiring() -> bool:
    """#141-H1：80 次动作 + 业务零进展 ⇒ 恰好 1 条告警（带动作数与停滞秒数）。"""
    return _wiring_failures() == []


# ---------------------------------------------------------------------------
# H2 不误报：有进展 / 动作<20 / 未接线 ⇒ 0 条告警
# ---------------------------------------------------------------------------
def _no_false_positive_failures() -> list[str]:
    msgs: list[str] = []
    lords = _lords()

    # (a) 业务进展每轮都在变 —— 画面/状态全冻住也不许报「无进展」。
    lords.reset_sessions()
    session = lords._session(14101)           # type: ignore[attr-defined]

    def moving_progress(round_no: int) -> None:
        session.note_rows([(f"靶子{round_no}", 0, 4)])

    with _fake_run(
        rounds=ROUNDS, actions_per_round=ACTIONS_PER_ROUND, on_round=moving_progress, wire=True
    ) as res:
        if res["summary"].no_progress_alarms or _alarm_rows(res["heartbeats"]):
            msgs.append("业务进展每轮都在变却报了「有动作无进展」（误报）")
        markers = [row.get("progress_marker") for row in res["heartbeats"]]
        if len(set(markers)) < 2:
            msgs.append(f"进展快照没有随页读新行变化：{markers[:3]!r} —— progress_fn 没真读会话")

    # (b) 动作不足 20 次 —— 哪怕业务真的一直不动也不许报。
    lords.reset_sessions()
    with _fake_run(rounds=10, actions_per_round=1, wire=True) as res:
        if res["summary"].no_progress_alarms or _alarm_rows(res["heartbeats"]):
            msgs.append("只有 10 次动作（<20）却报了「有动作无进展」（阈值被改松）")

    # (c) 未接线 —— 绝不能拿「画面在动」冒充动作。
    lords.reset_sessions()
    with _fake_run(rounds=ROUNDS, actions_per_round=ACTIONS_PER_ROUND, wire=False) as res:
        if res["summary"].no_progress_alarms or _alarm_rows(res["heartbeats"]):
            msgs.append("没接线动作计数却报警（凭空编动作）")
        actions = {row.get("actions") for row in res["heartbeats"]}
        if actions != {None}:
            msgs.append(f"未接线时心跳 actions 应为 null，实际 {actions!r}")
    return msgs


def probe_no_false_positive() -> bool:
    """#141-H2：有进展 / 动作不足 20 / 未接线 ⇒ 零告警。"""
    return _no_false_positive_failures() == []


# ---------------------------------------------------------------------------
# H3 失败语义：summary.error ⇒ ✗ + 非零退出码
# ---------------------------------------------------------------------------
class _StubMonitor:
    """带 ``summary.error`` 的监管替身（不跑线程；只验 runner 的收工判据）。"""

    def __init__(self, error: str | None) -> None:
        self.summary = lm.Summary(
            serial="stub-hook141",
            started_ts=0.0,
            elapsed_sec=0.0,
            frames=0,
            longest_unchanged_sec=0.0,
            stall_count=0,
            capture_failures=0,
            jsonl_path=None,
            stop_reason="stop",
            error=error,
        )

    def stop(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        pass


def _failure_semantics_failures() -> list[str]:
    msgs: list[str] = []
    runner = _runner()
    real_body = runner._main_body                     # type: ignore[attr-defined]
    try:
        for error, want_fail in ((ERROR_TEXT, True), (None, False)):
            runner._main_body = lambda argv=None: None  # type: ignore[assignment]  # 不碰设备
            runner._MON["mon"] = _StubMonitor(error)    # type: ignore[attr-defined]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = runner.main([])
            runner._MON["mon"] = None                   # type: ignore[attr-defined]
            out = buf.getvalue()
            if want_fail:
                if code == 0:
                    msgs.append(f"summary.error={error!r} 却退出码 0（只打印不失败）")
                if "✗" not in out:
                    msgs.append("summary.error 非空但控制台没有 ✗ 行")
                if error not in out:
                    msgs.append("✗ 行没带 summary.error 原文（上层看不到失败原因）")
            elif code != 0:
                msgs.append(f"正常收工却退出码 {code}（应 0）")
    finally:
        runner._main_body = real_body               # type: ignore[assignment]
        runner._MON["mon"] = None                   # type: ignore[attr-defined]
    source = (TOOLS_DIR / "run_wuchong_live.py").read_text(encoding="utf-8-sig")
    if "raise SystemExit(main())" not in source:
        msgs.append("CLI 入口没有 raise SystemExit(main())：main 返回的非零退出码传不到进程")
    if "def monitor_exit_code(" not in source:
        msgs.append("runner 没有 monitor_exit_code()：收工失败语义没有单一出口")
    return msgs


def probe_summary_error_fails_task() -> bool:
    """#141-H3：注入 summary.error ⇒ runner 打印 ✗ 且返回非零（正常收工仍 0）。"""
    return _failure_semantics_failures() == []


# ---------------------------------------------------------------------------
# H4 未接线必须喊出来（不许静默降级）
# ---------------------------------------------------------------------------
def _unwired_warning_failures() -> list[str]:
    msgs: list[str] = []
    _lords().reset_sessions()
    with _fake_run(rounds=3, actions_per_round=0, wire=False) as res:
        text = res["text"]
        if "未接线" not in text:
            msgs.append("不传 actions_fn/progress_fn，日志里没有「未接线」警告（静默降级）")
        if "有动作无进展报警不会触发" not in text:
            msgs.append("「未接线」警告没有点明后果（有动作无进展报警不会触发）")
    with _fake_run(rounds=3, actions_per_round=0, wire=True) as res:
        if "已接线：actions_fn / progress_fn" not in res["text"]:
            msgs.append("接上了 actions_fn/progress_fn，日志却没打「已接线：actions_fn / progress_fn」")
    return msgs


def probe_unwired_is_loud() -> bool:
    """#141-H4：未接线 ⇒ 日志显式喊「未接线」+ 后果；接线成功 ⇒ 日志显式「已接线」。"""
    return _unwired_warning_failures() == []


# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_WIRING,
        "#141",
        "长跑监管：#141 把动作计数/业务进展接进 runner —— 80 次动作 + 业务零进展 ⇒ 一条"
        "「★★ 有动作无进展 ★★」（带 80 次动作 / 180.0s），progress_source=progress_fn",
        probe_actions_progress_wiring,
    ),
    (
        HOOK_ID_NO_FALSE_POSITIVE,
        "#141",
        "长跑监管：有进展 / 动作不足 20 / 未接线 ⇒ 零告警（未接线时 actions=null，绝不编动作）",
        probe_no_false_positive,
    ),
    (
        HOOK_ID_FAILURE_SEMANTICS,
        "#141",
        "runner 收工：summary.error 非空 ⇒ 打印 ✗ + 非零退出码（CLI raise SystemExit(main())）；"
        "正常收工仍 0",
        probe_summary_error_fails_task,
    ),
    (
        HOOK_ID_UNWIRED,
        "#141",
        "runner 起监管：未接线必须显式喊「未接线：有动作无进展报警不会触发」；接上必须打「已接线」",
        probe_unwired_is_loud,
    ),
]


# ---------------------------------------------------------------------------
def _run_all() -> list[tuple[str, bool]]:
    return [
        ("H1 接线生效（80 动作零进展 ⇒ 1 条告警）", probe_actions_progress_wiring()),
        ("H2 不误报（有进展 / 动作<20 / 未接线）", probe_no_false_positive()),
        ("H3 收工失败语义（✗ + 非零退出码）", probe_summary_error_fails_task()),
        ("H4 未接线必须喊出来", probe_unwired_is_loud()),
    ]


def _all_messages() -> list[str]:
    return (
        _wiring_failures()
        + _no_false_positive_failures()
        + _failure_semantics_failures()
        + _unwired_warning_failures()
    )


def prove_red() -> bool:
    print("hooks_141 prove-red：先把接线 / 不误报 / 失败语义 / 未接线警告四条腿跑绿，再逐一破坏")
    green = _run_all()
    for name, ok in green:
        print(f"  [{'PASS' if ok else 'FAIL'}] 真实实现：{name}")
    if not all(ok for _n, ok in green):
        for msg in _all_messages():
            print(f"      - {msg}")
        return False

    checks: list[bool] = []

    # ① 断掉动作计数（actions_total 恒 0）→ H1 红
    lords = _lords()
    real_actions = lords.actions_total
    try:
        lords.actions_total = lambda: 0  # type: ignore[assignment]
        msgs = _wiring_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 actions_total 换成恒 0（断掉动作计数） -> "
            f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lords.actions_total = real_actions  # type: ignore[assignment]
    checks.append(red)

    # ② 进展快照恒定（有进展也报）→ H2 红
    real_progress = lords.progress_snapshot
    try:
        lords.progress_snapshot = lambda: "rows:0 targets:0 round:0 played:0"  # type: ignore[assignment]
        msgs = _no_false_positive_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 progress_snapshot 换成恒定串（有进展也报） -> "
            f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lords.progress_snapshot = real_progress  # type: ignore[assignment]
    checks.append(red)

    # ③ 只打印不返回非零（MONITOR_ERROR_EXIT = 0）→ H3 红
    runner = _runner()
    real_exit = runner.MONITOR_ERROR_EXIT
    try:
        runner.MONITOR_ERROR_EXIT = 0  # type: ignore[assignment]
        msgs = _failure_semantics_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 MONITOR_ERROR_EXIT 换成 0（只打印不非零） -> "
            f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        runner.MONITOR_ERROR_EXIT = real_exit  # type: ignore[assignment]
    checks.append(red)

    # ④ 删「未接线」警告 → H4 红
    real_warning = runner.MONITOR_UNWIRED_WARNING
    try:
        runner.MONITOR_UNWIRED_WARNING = ""  # type: ignore[assignment]
        msgs = _unwired_warning_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 删掉「未接线」警告文案 -> "
            f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        runner.MONITOR_UNWIRED_WARNING = real_warning  # type: ignore[assignment]
    checks.append(red)

    ok = all(ok for _n, ok in green) and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
