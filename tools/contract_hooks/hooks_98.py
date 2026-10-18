# -*- coding: utf-8 -*-
"""#98：长跑监管（20s 心跳 / 90s 卡住报警 / 证据落盘）的四道契约。

## 为什么有这张票（运维原话）

「你的监管一直都非常不及时，经常出问题」——原来的做法是**跑完才看日志**，真机卡住只能
事后翻 ``debug/maafw*.log``。spec §4.5 要求：20s 采帧心跳；画面 + 状态不变 ≥90s →
截图 + 高亮报警（**不自动换机**）。实现是 ``tools/longrun_monitor.py``。

## 契约（真机就绪的最低标准）

- **T1 卡住必报必落盘**：同一帧重复喂到 ≥90s → ``stall_count ≥ 1`` + ``stall_<ts>.png``
  里是**当时那一帧**（真 PNG 头）+ 控制台出现 ``★★ 卡住 X 秒 ★★``，且报警时机落在
  ``[stall, stall+interval)`` 里（20s 心跳下 90〜110s，不会拖到「跑完才说」）。
- **T2 帧在变不许误报**：12 轮互不相同的帧 → 零报警、零落盘、零高亮行。
  （#23 的教训：把「画面在动」判成卡死比漏报更伤人。）
- **T3 心跳 JSONL 每轮一行、字段齐全**：``{ts, frame_hash, changed, unchanged_sec, note}``
  每行都在，且每轮恰好一行、``idx`` 递增、静止秒数单调不减、文件以换行收尾。
- **T4 CLI 契约**：默认 ``--interval 20`` / ``--stall 90`` / ``--out debug/longrun``；
  抓屏 argv 是**只读**的 ``exec-out screencap -p``；非法参数在**起采集之前**就退 2。
- **T5 可被外部停**：``stop()`` 从别的线程调能立刻打断等待，``join()`` 有界归还，
  退出时出小结（运行时长 / 帧数 / 最长静止 / 卡住次数 / 退出原因）。

## prove-red（破坏实验 ≥2）

``python tools\\contract_hooks\\hooks_98.py`` 依次破坏实现，要求守卫各自变红：

1. ``is_stalled`` 恒 ``False``（关掉卡住判定）→ **T1 红**；
2. ``save_frame`` 空实现（不落盘）→ **T1 红**；
3. ``frame_signature`` 返回常量（等于「看不出来画面在动」）→ **T2 红**；
4. ``_write_line`` 空实现（不写心跳）→ **T3 红**。

红 = 可用信号。真相（驱动假帧 / 假时钟的唯一实现）在 ``tools/test_longrun_monitor.py``，
本文件只做挂点，避免两边分叉。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import longrun_monitor as lm  # noqa: E402
import test_longrun_monitor as tlm  # noqa: E402

#: 假帧驱动的参数（20s 心跳 / 90s 阈值；7 轮 = t 到 120s，第 1 次报警在 t=100s）。
ROUNDS = 7
INTERVAL = 20.0
STALL = 90.0


# ---------------------------------------------------------------------------
# T1 卡住必报 + 必落盘
# ---------------------------------------------------------------------------
def _stall_failures() -> list[str]:
    msgs: list[str] = []
    with tlm.monitor_run(
        [tlm.solid_frame(40)], rounds=ROUNDS, interval=INTERVAL, stall=STALL
    ) as res:
        summary = res.summary
        if summary.stall_count < 1:
            msgs.append(f"同一帧重复 {INTERVAL * (ROUNDS - 1):.0f}s 没判卡住（stall_count={summary.stall_count}）")
        pngs = res.pngs()
        if not pngs:
            msgs.append("卡住了但没落帧（stall_<ts>.png 缺失）")
        elif pngs[0].read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            msgs.append(f"落盘证据不是 PNG：{pngs[0].name}")
        alarm = [line for line in res.log_lines if "★★" in line and "卡住" in line]
        if len(alarm) != 1:
            msgs.append(f"高亮报警行应恰好 1 行，实际 {len(alarm)} 行：{alarm}")
        elif not (alarm[0].startswith("★★ 卡住") and "秒 ★★" in alarm[0]):
            msgs.append(f"高亮报警行格式不对：{alarm[0]!r}")
        stalled_rows = [r for r in res.jsonl_lines if "★★" in r["note"]]
        if not stalled_rows:
            msgs.append("JSONL 里没有卡住行（事后无法从心跳里定位卡住时刻）")
        else:
            sec = float(stalled_rows[0]["unchanged_sec"])
            if not (STALL <= sec < STALL + INTERVAL):
                msgs.append(f"报警时机不对：{sec}s（应在 {STALL:.0f}~{STALL + INTERVAL:.0f}s，不能拖到跑完才说）")
            if not stalled_rows[0].get("frame_png"):
                msgs.append("卡住那一行没记 frame_png（证据与心跳对不上）")
        if not any("长跑监管小结" in line and "卡住" in line for line in res.log_lines):
            msgs.append("退出时没有小结行（运行时长/帧数/卡住次数）")
    return msgs


def probe_stall_alarm_and_evidence() -> bool:
    """#98：静帧重复到 ≥90s → 报警 + 落帧 + 高亮行，且报警时机在 90〜110s。"""
    return _stall_failures() == []


# ---------------------------------------------------------------------------
# T2 帧在变不许误报
# ---------------------------------------------------------------------------
def _no_false_alarm_failures() -> list[str]:
    msgs: list[str] = []
    rounds = 12
    frames = tlm.moving_frames(rounds)
    with tlm.monitor_run(frames, rounds=rounds, interval=INTERVAL, stall=STALL) as res:
        if res.summary.stall_count:
            msgs.append(f"帧一直在变却报了 {res.summary.stall_count} 次卡住（误报）")
        if res.pngs():
            msgs.append(f"没有卡住却落了帧：{[p.name for p in res.pngs()]}")
        if any("★★" in line for line in res.log_lines):
            msgs.append("没有卡住却打了高亮报警行")
        rows = res.jsonl_lines
        if not all(r["changed"] is True for r in rows):
            msgs.append(f"帧在变却记了 changed=False：{[r['changed'] for r in rows]}")
        if {r["unchanged_sec"] for r in rows} != {0.0}:
            msgs.append(f"帧在变却累积了静止时长：{sorted({r['unchanged_sec'] for r in rows})}")
    return msgs


def probe_no_false_alarm() -> bool:
    """#98：帧一直在变 → 零报警、零落盘（#23 的教训：误报比漏报更伤人）。"""
    return _no_false_alarm_failures() == []


# ---------------------------------------------------------------------------
# T3 心跳 JSONL
# ---------------------------------------------------------------------------
def _jsonl_failures() -> list[str]:
    msgs: list[str] = []
    rounds = 5
    with tlm.monitor_run([tlm.solid_frame(60)], rounds=rounds, interval=INTERVAL, stall=900.0) as res:
        path = res.summary.jsonl_path
        if path is None or not path.is_file():
            return [f"没写 JSONL：{path}"]
        if not path.name.startswith("fake-serial-"):
            msgs.append(f"文件名不是 <serial>-<ts>.jsonl：{path.name}")
        text = path.read_text(encoding="utf-8")
        raw_lines = text.splitlines()
        if len(raw_lines) != rounds:
            msgs.append(f"{rounds} 轮应写 {rounds} 行，实际 {len(raw_lines)} 行")
        if not text.endswith("\n"):
            msgs.append("JSONL 最后一行没有换行收尾（Get-Content -Wait 会读不到）")
        rows = tlm.read_jsonl(path)
        msgs.extend(tlm._required_field_failures(rows))
        if not rows:
            msgs.append("JSONL 一行都没有（心跳没写盘）")
            return msgs
        if [r.get("idx") for r in rows] != list(range(1, len(rows) + 1)):
            msgs.append(f"idx 不是 1..N 递增：{[r.get('idx') for r in rows]}")
        secs = [r["unchanged_sec"] for r in rows]
        if secs[0] != 0.0:
            msgs.append(f"首轮 unchanged_sec 应是 0.0，实际 {secs[0]}")
        if secs != sorted(secs):
            msgs.append(f"unchanged_sec 应单调不减：{secs}")
        if len({r["frame_hash"] for r in rows}) != 1:
            msgs.append("同一张画面的 frame_hash 应稳定（粗指纹不可用）")
    return msgs


def probe_heartbeat_jsonl() -> bool:
    """#98：每轮恰好一行 JSONL，五个必带字段齐全且类型对。"""
    return _jsonl_failures() == []


# ---------------------------------------------------------------------------
# T4 CLI 契约（默认值 + 只读抓屏 + 参数校验都不碰设备）
# ---------------------------------------------------------------------------
def _cli_failures() -> list[str]:
    msgs: list[str] = []
    args = lm.build_parser().parse_args(["--serial", "127.0.0.1:16384"])
    if args.interval != 20.0:
        msgs.append(f"--interval 默认值不是 20s：{args.interval!r}（spec §4.5）")
    if args.stall != 90.0:
        msgs.append(f"--stall 默认值不是 90s：{args.stall!r}（spec §4.5）")
    if args.out != "debug/longrun":
        msgs.append(f"--out 默认值不是 debug/longrun：{args.out!r}")
    cmd = lm.screencap_cmd("127.0.0.1:16384", adb="adb")
    if cmd != ["adb", "-s", "127.0.0.1:16384", "exec-out", "screencap", "-p"]:
        msgs.append(f"抓屏 argv 不是只读 exec-out screencap：{cmd}")
    for bad in (["--serial", "x", "--interval", "0"], ["--serial", "x", "--stall", "0"]):
        code = tlm._system_exit_code(lambda argv=bad: lm.main(argv))
        if code != 2:
            msgs.append(f"非法参数 {bad} 应退 2，实际 {code}")
    real_default = lm.DEFAULT_SERIAL
    lm.DEFAULT_SERIAL = ""
    try:
        code = tlm._system_exit_code(lambda: lm.main([]))
    finally:
        lm.DEFAULT_SERIAL = real_default
    if code != 2:
        msgs.append(f"缺 --serial 应退 2（不许去连设备），实际 {code}")
    if (lm.DEFAULT_INTERVAL, lm.DEFAULT_STALL) != (20.0, 90.0):
        msgs.append(f"模块常量不是 20/90：{lm.DEFAULT_INTERVAL}/{lm.DEFAULT_STALL}")
    return msgs


def probe_cli_contract() -> bool:
    """#98：CLI 默认就是 spec 的 20/90/debug/longrun；抓屏只读；非法参数不碰设备。"""
    return _cli_failures() == []


# ---------------------------------------------------------------------------
# T5 可被外部停 + 小结
# ---------------------------------------------------------------------------
def _stoppable_failures() -> list[str]:
    msgs: list[str] = []
    facts = tlm.stop_after_two_frames()
    if not facts["fired"] or facts["alive"]:
        msgs.append(f"stop() 后线程没按时退出：{facts}")
    if not facts["has_summary"] or facts["stop_reason"] != "stop":
        msgs.append(f"外部 stop 的退出原因不是 stop：{facts.get('stop_reason')!r}")
    if facts["frames"] < 1:
        msgs.append("外部 stop 一次都没采到帧")
    if not facts["jsonl_is_file"]:
        msgs.append("外部 stop 后 JSONL 没落盘（证据随进程消失）")
    return msgs


def probe_stoppable() -> bool:
    """#98：``stop()`` 可从别的线程打断，``join()`` 有界归还，退出有小结（runner 集成面）。"""
    return _stoppable_failures() == []


# ---------------------------------------------------------------------------
HOOKS = [
    (
        "longrun-stall-alarm-and-evidence",
        "#98",
        "长跑监管：同一帧重复到 ≥90s 必须判卡住 + 落 stall_<ts>.png（真 PNG）+ 打 ★★ 卡住 X 秒 ★★，"
        "且报警时机落在 90〜110s（20s 心跳）——不许拖到跑完才说",
        probe_stall_alarm_and_evidence,
    ),
    (
        "longrun-no-false-alarm",
        "#98",
        "长跑监管：帧一直在变 → 零报警、零落盘、零高亮行（#23 教训：误报比漏报更伤人）",
        probe_no_false_alarm,
    ),
    (
        "longrun-heartbeat-jsonl",
        "#98",
        "长跑监管：每轮恰好一行 JSONL，{ts, frame_hash, changed, unchanged_sec, note} 齐全、类型对、"
        "idx 递增、静止秒数单调、换行收尾",
        probe_heartbeat_jsonl,
    ),
    (
        "longrun-cli-contract",
        "#98",
        "长跑监管 CLI：--interval 20 / --stall 90 / --out debug/longrun；抓屏只读 exec-out screencap；"
        "非法参数在起采集之前就退 2",
        probe_cli_contract,
    ),
    (
        "longrun-stoppable",
        "#98",
        "长跑监管：stop() 从别的线程可立刻打断等待、join() 有界归还、退出出小结（runner 的集成面）",
        probe_stoppable,
    ),
]


# ---------------------------------------------------------------------------
def _run_all() -> list[tuple[str, bool]]:
    return [
        ("T1 卡住必报必落盘", probe_stall_alarm_and_evidence()),
        ("T2 帧在变不误报", probe_no_false_alarm()),
        ("T3 心跳 JSONL", probe_heartbeat_jsonl()),
        ("T4 CLI 契约", probe_cli_contract()),
        ("T5 可被外部停", probe_stoppable()),
    ]


def prove_red() -> bool:
    print("hooks_98 prove-red：逐一破坏实现，要求守卫各自变红")
    green = _run_all()
    for name, ok in green:
        print(f"  [{'PASS' if ok else 'FAIL'}] 真实实现：{name}")
    if not all(ok for _n, ok in green):
        for m in _stall_failures() + _no_false_alarm_failures() + _jsonl_failures() + _cli_failures() + _stoppable_failures():
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    # ① 关掉卡住判定 → T1 红
    real = lm.is_stalled
    try:
        lm.is_stalled = lambda *_a, **_k: False  # type: ignore[assignment]
        msgs = _stall_failures()
        red = bool(msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 把卡住判定换成恒 False -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
    finally:
        lm.is_stalled = real  # type: ignore[assignment]
    checks.append(red)

    # ② 不落盘 → T1 红
    real = lm.save_frame
    try:
        lm.save_frame = lambda *_a, **_k: None  # type: ignore[assignment]
        msgs = _stall_failures()
        red = bool(msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 把落帧换成空实现 -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
    finally:
        lm.save_frame = real  # type: ignore[assignment]
    checks.append(red)

    # ③ 粗指纹返回常量（看不出画面在动）→ T2 红
    real = lm.frame_signature
    try:
        lm.frame_signature = lambda _frame: b"\x00" * (lm.SIGNATURE_SIZE * lm.SIGNATURE_SIZE)  # type: ignore[assignment]
        msgs = _no_false_alarm_failures()
        red = bool(msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 让粗指纹恒等（看不出画面在动）-> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
    finally:
        lm.frame_signature = real  # type: ignore[assignment]
    checks.append(red)

    # ④ 不写心跳 → T3 红
    real_write = lm.LongrunMonitor._write_line
    try:
        lm.LongrunMonitor._write_line = lambda *_a, **_k: None  # type: ignore[assignment]
        msgs = _jsonl_failures()
        red = bool(msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 把心跳写盘换成空实现 -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
    finally:
        lm.LongrunMonitor._write_line = real_write  # type: ignore[assignment]
    checks.append(red)

    ok = all(ok for _n, ok in green) and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
