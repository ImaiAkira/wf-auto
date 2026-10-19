# -*- coding: utf-8 -*-
"""#140：长跑监管 JSONL 0 字节 + 「有动作但无进展」不该无声 —— 三条契约。

## 为什么有这张票（真机 484 / 第 6 轮验收，2026-10-18）

现场 80 次滚动 × 6.0s/次 = **474s 空转**，0 条「页读」、0 个目标；事后报告说
``debug/longrun/127.0.0.1_16448-20261018-183349.jsonl`` 是 **0 字节**，「监管一行都没写」。
取证结论（写进 ``tools/longrun_monitor.py`` 的模块 docstring）：

1. **0 字节的窗口**：``_open_jsonl`` 在循环开头就建文件，但第一行要等第一轮采集返回后才写；
   默认 ``adb exec-out screencap -p`` 原来**没有超时**，设备/ adb 一卡，文件就一直 0 字节 ——
   和「监管根本没启动」长得一模一样（处置却完全不同）。
2. **心跳不能只在状态变化时写**：那一跑其实写了 53 行心跳（18:33:49→18:51:22），但全是
   ``changed=true / unchanged_sec=0.0`` —— 每次滚动画面都在变，旧判据只看得见「画面在动」。
3. **「有动作但无进展」是独立形态**：连续动作 ≥20 次且业务进展 ≥180s 没推进 → 必须能报警，
   而且告警行里要带动作数与停滞秒数（比「卡住不动」隐蔽得多）。

## 契约（守卫口径）

- **H1 心跳周期 + 非空**（``longrun-heartbeat-periodic-nonempty``）：60s 无状态/画面变化 ⇒
  **≥3 条 ``kind="heartbeat"`` 行**（20s 一条，不许改稀）+ 一条更早的 ``kind="start"`` 启动行 +
  文件字节数 > 0 + 每条心跳带 ``state/progress_marker/actions/last_progress_ts``。
  ⇒ 「0 字节」从此只能是「监管没启动 / 写盘失败」。
- **H2 有动作无进展必报**（``longrun-actions-without-progress``）：80 次动作 + 业务指标
  180s 不动 ⇒ 一条 ``★★ 有动作无进展 ★★``，行里 ``actions_since_progress=80``、
  ``progress_stalled_sec=180.0``，文本同时带「80 次动作」「180.0s」；并且**不误报**：
  业务指标每轮都变 / 动作不足 20 次 / 动作未接线 → 零告警。
- **H3 0 字节 = 显式错误**（``longrun-empty-jsonl-is-error``）：写盘被掐断（模拟「监管没喂到
  数据」）⇒ 结束时 ``summary.error`` 非空、控制台有 ``✗`` 行、CLI ``main()`` 非零退出，
  不许静默通过。

## prove-red（破坏实验 5 条，全部在内存里，不碰设备）

1. 把心跳改成「仅 ``changed=True`` 才写」→ **H1 红**；
2. 把 :func:`longrun_monitor.is_action_without_progress` 换成恒 ``False`` → **H2 红**；
3. 把 ``LongrunMonitor._audit``（结束自检）换成空实现 → **H3 红**；
4. 把 ``LongrunMonitor._write_start_line``（启动行）换成空实现 → **H1 红**；
5. 把真源 :data:`longrun_monitor.NO_PROGRESS_SEC` 调成 ``1e9``（阈值调歪）→ **H2 红**。

红 = 可用信号。驱动（假帧 / 假时钟 / 静默写盘）的唯一实现在
``tools/test_longrun_monitor.py``，本文件只做挂点，避免两边分叉。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import longrun_monitor as lm  # noqa: E402
import test_longrun_monitor as tlm  # noqa: E402

HOOK_ID_HEARTBEAT = "longrun-heartbeat-periodic-nonempty"
HOOK_ID_NO_PROGRESS = "longrun-actions-without-progress"
HOOK_ID_EMPTY_LOG = "longrun-empty-jsonl-is-error"

#: 与真机现场同量级：20s 心跳、90s 卡住阈值、80 次动作 / 12 轮（t=0..220）。
INTERVAL = 20.0
STALL = 900.0
ACTIONS_PER_ROUND = 8
ROUNDS = 12
PROGRESS_FROZEN = "rows:0 targets:0"
#: t=180（第 10 轮）时累计的动作数：8 次/轮 × 10 轮 = 80（现场 474s 的 1/6，已足够报警）。
ACTIONS_AT_ALARM = ACTIONS_PER_ROUND * (int(lm.NO_PROGRESS_SEC / INTERVAL) + 1)


# ---------------------------------------------------------------------------
# H1 心跳周期 + 非空（0 字节与「没启动」可区分）
# ---------------------------------------------------------------------------
def _heartbeat_failures() -> list[str]:
    msgs: list[str] = []
    if lm.DEFAULT_INTERVAL != 20.0:
        msgs.append(f"心跳间隔真源不是 20s（{lm.DEFAULT_INTERVAL!r}）——「20s 一行」的契约没依据了")
    if not (0 < lm.CAPTURE_TIMEOUT_SEC < lm.DEFAULT_INTERVAL):
        msgs.append(
            f"抓屏超时 {lm.CAPTURE_TIMEOUT_SEC!r}s 不在 (0, 心跳间隔) 内："
            f"设备卡住时第一轮仍可能永远不返回（0 字节窗口）"
        )
    with tlm.monitor_run([tlm.solid_frame(40)], duration=60, interval=INTERVAL, stall=STALL) as res:
        rows = res.jsonl_lines
        hb = res.heartbeats
        if len(hb) < 3:
            msgs.append(
                f"60s 无状态变化只写了 {len(hb)} 条心跳（应 ≥3，20s 一条）——"
                f"「只在状态变化时写」会让长跑再次变成 0 字节/稀疏日志"
            )
        if res.summary.jsonl_bytes <= 0:
            msgs.append("JSONL 是 0 字节（应 ≥1 字节，心跳周期落盘）")
        kinds = [r.get("kind") for r in rows]
        if "start" not in kinds:
            msgs.append("缺 kind=\"start\" 启动行：0 字节无法与「监管没启动」区分")
        else:
            start_at = kinds.index("start")
            first_hb = next((i for i, k in enumerate(kinds) if k == "heartbeat"), None)
            if first_hb is None or first_hb < start_at:
                msgs.append(f"start 行不在第一条心跳之前：kinds={kinds}")
        if res.summary.error is not None:
            msgs.append(f"正常跑完却带自检错误：{res.summary.error}")
        for i, row in enumerate(hb, 1):
            missing = [f for f in lm.HEARTBEAT_FIELDS if f not in row]
            if missing:
                msgs.append(f"第 {i} 条心跳缺字段 {missing}（运维看不到动作/进展）")
                break
    return msgs


def probe_heartbeat_periodic_nonempty() -> bool:
    """#140：状态不变也每 20s 一行；启动行在最前；0 字节只能意味着没启动/写盘失败。"""
    return _heartbeat_failures() == []


# ---------------------------------------------------------------------------
# H2 有动作无进展 → 告警（且不误报）
# ---------------------------------------------------------------------------
def _action_no_progress_failures() -> list[str]:
    msgs: list[str] = []
    if (lm.NO_PROGRESS_ACTIONS, lm.NO_PROGRESS_SEC) != (20, 180.0):
        msgs.append(
            f"阈值真源被改动：NO_PROGRESS_ACTIONS={lm.NO_PROGRESS_ACTIONS!r} / "
            f"NO_PROGRESS_SEC={lm.NO_PROGRESS_SEC!r}（应为 20 / 180.0，来历见常量注释）"
        )
    with tlm.monitor_run(
        [tlm.solid_frame(40)],
        rounds=ROUNDS,
        interval=INTERVAL,
        stall=STALL,
        actions_per_round=ACTIONS_PER_ROUND,
        progress_fn=lambda: PROGRESS_FROZEN,
    ) as res:
        hb = res.heartbeats
        alarms = [r for r in hb if "★★ 有动作无进展" in r["note"]]
        if not alarms:
            msgs.append(
                f"{ACTIONS_PER_ROUND * ROUNDS} 次动作、业务指标一直不动，JSONL 没有「有动作无进展」告警行"
            )
        else:
            alarm = alarms[0]
            if len(alarms) != 1:
                msgs.append(f"同一段只该报警一次（不刷屏），实际 {len(alarms)} 条")
            if alarm.get("actions_since_progress") != ACTIONS_AT_ALARM:
                msgs.append(
                    f"告警行的动作数不是 {ACTIONS_AT_ALARM}：{alarm.get('actions_since_progress')!r}"
                )
            if alarm.get("progress_stalled_sec") != lm.NO_PROGRESS_SEC:
                msgs.append(
                    f"告警行的停滞秒数不是 {lm.NO_PROGRESS_SEC}：{alarm.get('progress_stalled_sec')!r}"
                )
            if f"{ACTIONS_AT_ALARM} 次动作" not in alarm["note"] or f"{lm.NO_PROGRESS_SEC:.1f}s" not in alarm["note"]:
                msgs.append(f"告警文本没有同时带动作数与停滞秒数：{alarm['note']!r}")
        if res.summary.no_progress_alarms != 1:
            msgs.append(f"summary.no_progress_alarms={res.summary.no_progress_alarms}（应 1）")
        if not any("有动作无进展" in line for line in res.log_lines):
            msgs.append("控制台没有高亮「有动作无进展」行（无人值守时看不见）")

    # 不误报：动作在刷但业务指标每轮都变 / 动作不足 / 没接线动作计数。
    progress = {"n": 0}

    def moving_progress() -> str:
        progress["n"] += 1
        return f"rows:{progress['n']}"

    with tlm.monitor_run(
        [tlm.solid_frame(40)],
        rounds=ROUNDS,
        interval=INTERVAL,
        stall=STALL,
        actions_per_round=ACTIONS_PER_ROUND,
        progress_fn=moving_progress,
    ) as res:
        if res.summary.no_progress_alarms:
            msgs.append("业务指标每轮都在变却报了「有动作无进展」（误报）")
    with tlm.monitor_run(
        [tlm.solid_frame(40)],
        rounds=10,
        interval=INTERVAL,
        stall=STALL,
        actions_per_round=1,
        progress_fn=lambda: PROGRESS_FROZEN,
    ) as res:
        if res.summary.no_progress_alarms:
            msgs.append("只有 10 次动作（<20）却报了「有动作无进展」（阈值被改松）")
    with tlm.monitor_run([tlm.solid_frame(40)], rounds=10, interval=INTERVAL, stall=STALL) as res:
        if res.summary.no_progress_alarms:
            msgs.append("没接线动作计数（actions=None）却报警（凭空编动作）")
    return msgs


def probe_actions_without_progress() -> bool:
    """#140：连续动作 ≥20 次而业务指标 ≥180s 不动 → 一条带动作数 + 停滞秒数的告警。"""
    return _action_no_progress_failures() == []


# ---------------------------------------------------------------------------
# H3 0 字节 = 显式错误（结束自检）
# ---------------------------------------------------------------------------
def _empty_log_failures() -> list[str]:
    msgs: list[str] = []
    with tlm.silent_monitor_run(
        [tlm.solid_frame(40)], rounds=2, interval=INTERVAL, stall=STALL
    ) as res:
        if not res.summary.error:
            msgs.append("JSONL 0 字节但 summary.error 为空（静默通过）")
        elif "为空" not in res.summary.error and "0 字节" not in res.summary.error:
            msgs.append(f"错误文本没指明「JSONL 为空 / 0 字节」：{res.summary.error!r}")
        if not any("✗" in line and ("为空" in line or "0 字节" in line) for line in res.log_lines):
            msgs.append("控制台没有显式 ✗ 错误行（0 字节被静默吞掉）")
        if not any("长跑监管小结" in line and "✗" in line for line in res.log_lines):
            msgs.append("小结行没带 ✗（运维扫一眼看不出来失败）")
        if res.summary.jsonl_bytes != 0 or res.summary.jsonl_lines != 0:
            msgs.append(
                f"自检统计不对：{res.summary.jsonl_lines} 行 / {res.summary.jsonl_bytes} 字节"
            )
    code = tlm.empty_log_cli_exit_code()
    if code in (0, None):
        msgs.append(f"CLI 在日志为空时退出码 {code!r}（必须非零，不许静默通过）")
    return msgs


def probe_empty_jsonl_is_error() -> bool:
    """#140：跑完日志为空 → 打印 + 返回显式错误 + CLI 非零退出。"""
    return _empty_log_failures() == []


# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_HEARTBEAT,
        "#140",
        "长跑监管：60s 无状态变化 → ≥3 条心跳（20s 一条）+ start 启动行 + 文件非 0 字节；"
        "状态不变也写（0 字节只能意味着没启动/写盘失败）",
        probe_heartbeat_periodic_nonempty,
    ),
    (
        HOOK_ID_NO_PROGRESS,
        "#140",
        "长跑监管：80 次动作 + 业务指标 180s 不动 → 一条「★★ 有动作无进展 ★★」（带动作数与"
        "停滞秒数）；有进展 / 动作不足 / 未接线 → 零告警",
        probe_actions_without_progress,
    ),
    (
        HOOK_ID_EMPTY_LOG,
        "#140",
        "长跑监管：跑完 JSONL 为空 → summary.error + 控制台 ✗ + CLI 非零退出（不许静默通过）",
        probe_empty_jsonl_is_error,
    ),
]


# ---------------------------------------------------------------------------
def _run_all() -> list[tuple[str, bool]]:
    return [
        ("H1 心跳周期 + 非空", probe_heartbeat_periodic_nonempty()),
        ("H2 有动作无进展必报", probe_actions_without_progress()),
        ("H3 0 字节 = 显式错误", probe_empty_jsonl_is_error()),
    ]


def _all_messages() -> list[str]:
    return _heartbeat_failures() + _action_no_progress_failures() + _empty_log_failures()


def prove_red() -> bool:
    print("hooks_140 prove-red：逐一破坏实现，要求守卫各自变红")
    green = _run_all()
    for name, ok in green:
        print(f"  [{'PASS' if ok else 'FAIL'}] 真实实现：{name}")
    if not all(ok for _n, ok in green):
        for msg in _all_messages():
            print(f"      - {msg}")
        return False

    checks: list[bool] = []

    # ① 心跳改成「仅状态/画面变化才写」→ H1 红
    real_write = lm.LongrunMonitor._write_line

    def only_if_changed(self, idx, total, now, sig, changed, unchanged, state, note, png, **kwargs):
        if not changed:
            return False
        return real_write(self, idx, total, now, sig, changed, unchanged, state, note, png, **kwargs)

    try:
        lm.LongrunMonitor._write_line = only_if_changed  # type: ignore[assignment]
        msgs = _heartbeat_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把心跳改成「仅状态变化才写」 -> {'红' if red else '仍绿'}"
            + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lm.LongrunMonitor._write_line = real_write  # type: ignore[assignment]
    checks.append(red)

    # ② 删掉「有动作无进展」判据（恒 False）→ H2 红
    real_criterion = lm.is_action_without_progress
    try:
        lm.is_action_without_progress = lambda *_a, **_k: False  # type: ignore[assignment]
        msgs = _action_no_progress_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把「有动作无进展」判据换成恒 False -> {'红' if red else '仍绿'}"
            + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lm.is_action_without_progress = real_criterion  # type: ignore[assignment]
    checks.append(red)

    # ③ 删掉结束自检（_audit 空实现）→ H3 红
    real_audit = lm.LongrunMonitor._audit
    try:
        lm.LongrunMonitor._audit = lambda *_a, **_k: None  # type: ignore[assignment]
        msgs = _empty_log_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 删掉结束自检（_audit） -> {'红' if red else '仍绿'}"
            + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lm.LongrunMonitor._audit = real_audit  # type: ignore[assignment]
    checks.append(red)

    # ④ 删掉启动行 → H1 红（0 字节又和「没启动」混在一起）
    real_start = lm.LongrunMonitor._write_start_line
    try:
        lm.LongrunMonitor._write_start_line = lambda *_a, **_k: False  # type: ignore[assignment]
        msgs = _heartbeat_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 删掉启动行（_write_start_line） -> {'红' if red else '仍绿'}"
            + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lm.LongrunMonitor._write_start_line = real_start  # type: ignore[assignment]
    checks.append(red)

    # ⑤ 把停滞阈值调歪（真源 NO_PROGRESS_SEC = 1e9）→ H2 红
    real_seconds = lm.NO_PROGRESS_SEC
    try:
        lm.NO_PROGRESS_SEC = 1e9  # type: ignore[assignment]
        msgs = _action_no_progress_failures()
        red = bool(msgs)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 NO_PROGRESS_SEC 调成 1e9（阈值调歪） -> "
            f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        lm.NO_PROGRESS_SEC = real_seconds  # type: ignore[assignment]
    checks.append(red)

    ok = all(ok for _n, ok in green) and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
