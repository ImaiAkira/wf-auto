# -*- coding: utf-8 -*-
"""#98 离线单测：长跑监管（20s 心跳 / 90s 卡住 / 证据落盘 / 可被外部停）。

**纯单元测试**：注入假帧 + 假时钟 + 假等待，全部落盘在临时目录（``tempfile.mkdtemp``），
不碰设备、不碰仓库 ``debug/``、不真睡（除最后一个线程用例真的 sleep 0.01s 级）。

    .venv\\Scripts\\python.exe tools\\test_longrun_monitor.py

覆盖：

  1. 粗指纹：同图同值 / 异图异值 / 量化步长内的抖动被吸收 / PNG bytes 与 PIL 等价 / 落盘是真 PNG；
  2. 心跳：每轮**恰好一行** JSONL，字段齐全（:data:`longrun_monitor.REQUIRED_FIELDS`）；
  3. 卡住：同一帧重复 → ≥90s 报警 + ``stall_*.png`` 落盘 + ``★★ 卡住 X 秒 ★★`` 高亮行；
  4. 不误报：帧一直在变 → 零报警、零落盘；
  5. 报警去重 + 重新武装：卡住→恢复→再卡住 = 两次报警两张图；
  6. 状态在动（画面同一张）不算卡住（spec §4.5 的「画面 + 状态」）；
  7. ``--duration`` 自动退出 + 小结（运行时长 / 帧数 / 最长静止 / 卡住次数）；
  8. 抓帧失败不掐死监管（note 记原因、不重置静止计时、不崩）；
  9. ``stop()`` 可被别的线程随时打断（真实线程 + 真实短暂等待）；
 10. CLI 契约：默认值就是 spec 的 20/90/``debug/longrun``，非法参数在**碰设备之前**就报错；
 11. 判据边界（``≥``）与构造参数校验（interval/stall ≤ 0、capture 不可调用）；
 12. 默认 adb 采集确实接在循环上：用一个**不存在**的 adb 名字验证「采集失败只记账不崩」
     （连 adb 二进制都不会被解析，绝不碰设备）。

守卫本体（含 prove-red 破坏实验）在 ``tools/contract_hooks/hooks_98.py``；本文件的
``run_monitor`` / ``FakeClock`` / ``FakeCapture`` 是两边共用的唯一驱动实现（避免分叉）。
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import longrun_monitor as lm  # noqa: E402

FRAME_W, FRAME_H = 180, 320  # 够 64x64 分格用，又比真机 1080p 快得多
#: 假时钟起点（真实纪元，避免文件名出现 1970 那种噪声）。
EPOCH0 = 1_700_000_000.0

FAILS: list[str] = []


# ---------------------------------------------------------------------------
# 假设备：帧 / 采集 / 时钟
# ---------------------------------------------------------------------------
def _draw_rect(left: int, size: int = 40) -> Any:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    img = Image.new("RGB", (FRAME_W, FRAME_H), (20, 22, 30))
    ImageDraw.Draw(img).rectangle([left, 60, left + size, 60 + size], fill=(250, 250, 250))
    return img


def solid_frame(color: int = 40):
    """纯色帧（同一张画面重复喂 = 真·冻结）。"""
    from PIL import Image  # noqa: PLC0415

    return Image.new("RGB", (FRAME_W, FRAME_H), (color, color, color))


def moving_frames(count: int) -> list:
    """``count`` 张互不相同的帧（画面一直在动 → 不许误报）。"""
    return [_draw_rect(4 + (i * 11) % (FRAME_W - 50)) for i in range(count)]


def noisy_frame(base: int = 200, delta: int = 3):
    """与 ``solid_frame(base)`` 差 ``delta`` 灰度的帧（量化步长内 → 指纹相同）。"""
    from PIL import Image  # noqa: PLC0415

    return Image.new("RGB", (FRAME_W, FRAME_H), (base + delta, base + delta, base + delta))


class FakeClock:
    """受控时钟：``wait`` 用它推进，``run()`` 因此瞬间跑完，绝不真睡。"""

    def __init__(self, start: float = EPOCH0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> float:
        self.t += float(seconds)
        return self.t


class FakeCapture:
    """把一串帧按顺序吐出来；元素可以是异常实例（模拟 adb 抖动）。"""

    def __init__(self, frames: Sequence[Any], *, loop: bool = True) -> None:
        if not frames:
            raise ValueError("frames 不能为空")
        self.frames = list(frames)
        self.loop = loop
        self.calls = 0

    def __call__(self) -> Any:
        idx = self.calls % len(self.frames) if self.loop else self.calls
        if idx >= len(self.frames):
            raise RuntimeError("帧序列已耗尽")
        self.calls += 1
        item = self.frames[idx]
        if isinstance(item, BaseException):
            raise item
        return item


class _StopAfter:
    """抓够 N 轮就调 ``monitor.stop()`` —— 用真实 stop 路径结束循环，不靠 duration。"""

    def __init__(self, capture: FakeCapture, rounds: int) -> None:
        self._capture = capture
        self._rounds = int(rounds)
        self.calls = 0
        self.monitor: lm.LongrunMonitor | None = None

    def __call__(self) -> Any:
        self.calls += 1
        try:
            return self._capture()
        finally:
            # 抓帧抛异常也要能收工，否则循环会一直转（监管本身「失败也不退出」是设计，驱动不是）。
            if self.calls >= self._rounds and self.monitor is not None:
                self.monitor.stop()


# ---------------------------------------------------------------------------
# 一次可复现的「假设备长跑」
# ---------------------------------------------------------------------------
@dataclass
class RunResult:
    summary: lm.Summary
    monitor: lm.LongrunMonitor
    root: Path
    out: Path
    log_lines: list[str]

    @property
    def jsonl_lines(self) -> list[dict]:
        assert self.summary.jsonl_path is not None
        return read_jsonl(self.summary.jsonl_path)

    def pngs(self) -> list[Path]:
        return sorted(self.out.glob("stall_*.png"))


def read_jsonl(path: str | Path) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def run_monitor(
    frames: Sequence[Any],
    *,
    rounds: int | None = None,
    interval: float = lm.DEFAULT_INTERVAL,
    stall: float = lm.DEFAULT_STALL,
    out: str | Path | None = None,
    serial: str = "fake-serial",
    state_fn: Callable[[], Any] | None = None,
    beep: bool = False,
    duration: float | None = None,
    clock: FakeClock | None = None,
) -> RunResult:
    """在临时目录里跑一遍监管（假帧 + 假时钟 + 假等待），返回全部证据。"""
    if duration is None and rounds is None:
        raise ValueError("rounds 或 duration 必须给一个（否则循环不会自己停）")
    clock = clock or FakeClock()
    if out is None:
        root = Path(tempfile.mkdtemp(prefix="wf_98_longrun_"))
        out = root / "longrun"
    else:
        out = Path(out)
        root = out.parent
    log_lines: list[str] = []
    capture: Any = FakeCapture(frames)
    if duration is None:
        capture = _StopAfter(capture, int(rounds or 0))
    monitor = lm.LongrunMonitor(
        capture,
        interval=interval,
        stall=stall,
        out=out,
        serial=serial,
        state_fn=state_fn,
        beep=beep,
        duration=duration,
        now=clock,
        wait=clock.advance,
        log=log_lines.append,
    )
    if isinstance(capture, _StopAfter):
        capture.monitor = monitor
    summary = monitor.run()
    return RunResult(summary=summary, monitor=monitor, root=root, out=Path(out), log_lines=log_lines)


@contextmanager
def monitor_run(*args: Any, **kwargs: Any) -> Iterator[RunResult]:
    """``run_monitor`` + 自动清临时目录（每个用例都不许污染工作树）。"""
    result = run_monitor(*args, **kwargs)
    try:
        yield result
    finally:
        shutil.rmtree(result.root, ignore_errors=True)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _required_field_failures(rows: list[dict]) -> list[str]:
    """JSONL 契约：每行都是对象且五个必带字段齐全（类型也顺手核一下）。"""
    msgs: list[str] = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            msgs.append(f"第 {i} 行不是 JSON 对象")
            continue
        missing = [f for f in lm.REQUIRED_FIELDS if f not in row]
        if missing:
            msgs.append(f"第 {i} 行缺字段 {missing}")
            continue
        if not isinstance(row["ts"], str) or not row["ts"]:
            msgs.append(f"第 {i} 行 ts 不是非空字符串：{row['ts']!r}")
        if row["frame_hash"] is not None and not isinstance(row["frame_hash"], str):
            msgs.append(f"第 {i} 行 frame_hash 既不是 null 也不是字符串：{row['frame_hash']!r}")
        if not isinstance(row["changed"], bool):
            msgs.append(f"第 {i} 行 changed 不是 bool：{row['changed']!r}")
        if not isinstance(row["unchanged_sec"], (int, float)) or isinstance(row["unchanged_sec"], bool):
            msgs.append(f"第 {i} 行 unchanged_sec 不是数字：{row['unchanged_sec']!r}")
        if not isinstance(row["note"], str) or not row["note"]:
            msgs.append(f"第 {i} 行 note 不是非空字符串：{row['note']!r}")
    return msgs


# ---------------------------------------------------------------------------
# 1. 粗指纹
# ---------------------------------------------------------------------------
def test_coarse_hash() -> None:
    print("\n== 1. 粗指纹：64x64 灰度 4bit 量化 ==")
    a = lm.frame_hash(solid_frame(40))
    b = lm.frame_hash(solid_frame(40))
    check("同一张图 → 同一个 hash", a == b, f"hash={a}")
    check("hash 是 16 位 hex", len(a) == 16 and all(c in "0123456789abcdef" for c in a), f"hash={a}")
    check("不同画面 → 不同 hash", lm.frame_hash(_draw_rect(10)) != lm.frame_hash(_draw_rect(120)))

    base, noise = solid_frame(200), noisy_frame(200, 3)
    check(
        "量化步长内的抖动（±3 灰度）被吸收 → 同一指纹",
        lm.frame_hash(base) == lm.frame_hash(noise),
        f"base={lm.frame_hash(base)} noise={lm.frame_hash(noise)}",
    )
    big = solid_frame(200 + lm.QUANT_LEVELS * 2)
    check("超过量化步长 → 不同指纹", lm.frame_hash(base) != lm.frame_hash(big))

    sig = lm.frame_signature(solid_frame(40))
    check(
        "指纹长度 = 64x64 且每格 < QUANT_LEVELS",
        len(sig) == lm.SIGNATURE_SIZE * lm.SIGNATURE_SIZE and max(sig) < lm.QUANT_LEVELS,
        f"len={len(sig)} max={max(sig)}",
    )

    # PNG bytes 与 PIL.Image 等价（默认 adb 采集吐的就是 PNG bytes）
    import io  # noqa: PLC0415

    buf = io.BytesIO()
    _draw_rect(30).save(buf, format="PNG")
    raw = buf.getvalue()
    check("PNG bytes 与 PIL.Image 同指纹", lm.frame_hash(raw) == lm.frame_hash(_draw_rect(30)))

    root = Path(tempfile.mkdtemp(prefix="wf_98_png_"))
    try:
        out = lm.save_frame(raw, root / "stall_test.png")
        head = out.read_bytes()[:8]
        check("落盘是真 PNG（原样写、不重编码）", head == b"\x89PNG\r\n\x1a\n", f"head={head!r}")
        check("落盘后再读回，指纹不变", lm.frame_hash(out) == lm.frame_hash(raw))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 2. 心跳 JSONL
# ---------------------------------------------------------------------------
def test_heartbeat_jsonl() -> None:
    print("\n== 2. 每轮一行 JSONL，字段齐全 ==")
    with monitor_run([solid_frame(40)], rounds=3, stall=900) as res:
        rows = res.jsonl_lines
        check("3 轮 → 3 行（每轮恰好一行）", len(rows) == 3, f"lines={len(rows)}")
        bad = _required_field_failures(rows)
        check("五个必带字段齐全且类型对", bad == [], "; ".join(bad))
        check("file 名 <serial>-<ts>.jsonl", res.summary.jsonl_path.name.startswith("fake-serial-"), res.summary.jsonl_path.name)
        check("idx 连续 1..3", [r.get("idx") for r in rows] == [1, 2, 3], f"{[r.get('idx') for r in rows]}")
        check(
            "unchanged_sec 随心跳累积（0/20/40s）",
            [r["unchanged_sec"] for r in rows] == [0.0, 20.0, 40.0],
            f"{[r['unchanged_sec'] for r in rows]}",
        )
        check("首帧 changed=True 且 note 说明是建立基准",
              rows[0]["changed"] is True and "首帧" in rows[0]["note"], f"{rows[0]['note']!r}")
        check("后续轮 changed=False", rows[1]["changed"] is False and rows[2]["changed"] is False)
        check("同一画面 frame_hash 不变", len({r["frame_hash"] for r in rows}) == 1)
        check("state 缺省为 unknown", {r["state"] for r in rows} == {"unknown"})
        check("输出目录被自动创建", res.out.is_dir())
        check("临时目录隔离（没写仓库 debug/）", res.root.name.startswith("wf_98_longrun_"), str(res.root))


# ---------------------------------------------------------------------------
# 3. 卡住 → 报警 + 落盘
# ---------------------------------------------------------------------------
def test_stall_alarm() -> None:
    print("\n== 3. 同一帧重复 ≥90s → 报警 + 帧落盘 ==")
    with monitor_run([solid_frame(40)], rounds=7, interval=20, stall=90) as res:
        s = res.summary
        check("判定卡住（stall_count == 1）", s.stall_count == 1, f"stall_count={s.stall_count}")
        pngs = res.pngs()
        check("落了一张 stall_<ts>.png", len(pngs) == 1, f"pngs={[p.name for p in pngs]}")
        if pngs:
            check("证据是真 PNG", pngs[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", pngs[0].name)
        alarm = [line for line in res.log_lines if "★★" in line and "卡住" in line]
        check("打了一行高亮报警 ★★ 卡住 X 秒 ★★", len(alarm) == 1, alarm[0] if alarm else "无")
        if alarm:
            check("报警行带具体秒数", "★★ 卡住 100.0 秒 ★★" in alarm[0], alarm[0])
        rows = res.jsonl_lines
        notes = [r["note"] for r in rows]
        check("第 6 轮（t=100s）才开始报警（第 5 轮 t=80 < 90）",
              "★★ 卡住" in notes[5] and "★★" not in notes[4], f"notes[4]={notes[4]!r} notes[5]={notes[5]!r}")
        check("报警轮的 frame_png 指向落盘证据", bool(rows[5].get("frame_png")) and Path(rows[5]["frame_png"]).is_file())
        check("最长静止 = 120s（跑到 t=120）", s.longest_unchanged_sec == 120.0, f"{s.longest_unchanged_sec}")
        check("小结行在退出时打印（含运行时长/帧数/最长静止/卡住次数）",
              any("长跑监管小结" in line and "卡住 1 次" in line and "最长静止" in line for line in res.log_lines),
              res.log_lines[-1] if res.log_lines else "无")


# ---------------------------------------------------------------------------
# 4. 帧在变 → 不许误报
# ---------------------------------------------------------------------------
def test_moving_frames_no_false_alarm() -> None:
    print("\n== 4. 帧一直在变 → 零报警、零落盘 ==")
    frames = moving_frames(12)
    with monitor_run(frames, rounds=12, interval=20, stall=90) as res:
        check("零报警", res.summary.stall_count == 0, f"stall_count={res.summary.stall_count}")
        check("零落盘", res.pngs() == [])
        rows = res.jsonl_lines
        check("12 行全 changed=True（除首帧也应为 True）", all(r["changed"] is True for r in rows),
              f"{[r['changed'] for r in rows]}")
        check("unchanged_sec 始终 0（每轮都刷新）", {r["unchanged_sec"] for r in rows} == {0.0})
        check("没有高亮报警行", not any("★★" in line for line in res.log_lines))


# ---------------------------------------------------------------------------
# 5. 报警去重 + 重新武装
# ---------------------------------------------------------------------------
def test_stall_dedup_and_rearm() -> None:
    print("\n== 5. 卡住不刷屏、恢复后能再次报警 ==")
    frozen, other = solid_frame(40), solid_frame(210)
    frames = [frozen] * 7 + [other] + [frozen] * 7
    with monitor_run(frames, rounds=15, interval=20, stall=90) as res:
        check("两段冻结 → 两次报警", res.summary.stall_count == 2, f"stall_count={res.summary.stall_count}")
        check("两次报警 → 两张证据（不覆盖）", len(res.pngs()) == 2, f"{[p.name for p in res.pngs()]}")
        alarm = [line for line in res.log_lines if "★★" in line]
        check("高亮行也只有两行（不刷屏）", len(alarm) == 2, f"{alarm}")
        rows = res.jsonl_lines
        dedup = [r["note"] for r in rows if "不重复落盘" in r["note"]]
        check("同一段里后续轮次说明「已报警，不重复落盘」", bool(dedup), dedup[0] if dedup else "无")
        check("恢复那一轮 changed=True（第 8 轮）", rows[7]["changed"] is True, f"{rows[7]['note']!r}")


# ---------------------------------------------------------------------------
# 6. 状态在动 ≠ 卡住
# ---------------------------------------------------------------------------
def test_state_keeps_moving() -> None:
    print("\n== 6. 画面同一张但状态在动 → 不算卡住（spec §4.5）==")
    counter = {"n": 0}

    def state_fn() -> str:
        counter["n"] += 1
        return f"第{counter['n'] % 4 + 1}/4次"

    # 帧始终是**同一张**（指纹恒定），只有状态在变 —— 这正是「画面不动但流程在走」。
    with monitor_run([solid_frame(40)], rounds=12, interval=20, stall=90, state_fn=state_fn) as res:
        rows = res.jsonl_lines
        check("零报警（状态变化刷新了静止计时）", res.summary.stall_count == 0, f"stall_count={res.summary.stall_count}")
        check("12 轮 frame_hash 全相同（画面确实没动）", len({r["frame_hash"] for r in rows}) == 1,
              f"{len({r['frame_hash'] for r in rows})} 种")
        check("JSONL 记下了 runner 的状态", rows[0]["state"].startswith("第"), rows[0]["state"])
        check("状态每轮都在变 → changed 全 True", all(r["changed"] is True for r in rows),
              f"changed={[r['changed'] for r in rows]}")
        check("unchanged_sec 始终 0", {r["unchanged_sec"] for r in rows} == {0.0})
        # 对照：同一批轮次若 state 恒定，就一定会报警（证明差别来自 state）
    with monitor_run([solid_frame(40)], rounds=12, interval=20, stall=90) as res2:
        check("对照：state 恒定时同长度一定会报警", res2.summary.stall_count >= 1,
              f"stall_count={res2.summary.stall_count}")


# ---------------------------------------------------------------------------
# 7. duration 自动退出
# ---------------------------------------------------------------------------
def test_duration_exit() -> None:
    print("\n== 7. --duration 自动退出 + 小结 ==")
    with monitor_run([solid_frame(40)], duration=60, interval=20, stall=900) as res:
        s = res.summary
        check("退出原因 = duration", s.stop_reason == "duration", s.stop_reason)
        check("t=0/20/40 共 3 轮", s.frames == 3, f"frames={s.frames}")
        check("运行时长 60s", abs(s.elapsed_sec - 60.0) < 1e-6, f"elapsed={s.elapsed_sec}")
        check("JSONL 的 total = 3（第 i/N 的 N 与实际轮数一致）",
              {r.get("total") for r in res.jsonl_lines} == {3}, f"{[r.get('total') for r in res.jsonl_lines]}")


# ---------------------------------------------------------------------------
# 8. 抓帧失败不掐死监管
# ---------------------------------------------------------------------------
def test_capture_failure_survives() -> None:
    print("\n== 8. 抓帧失败：记原因、不崩、不重置静止计时 ==")
    good = solid_frame(40)
    frames = [good, RuntimeError("adb: device offline"), good, RuntimeError("timeout"), good]
    with monitor_run(frames, rounds=5, interval=20, stall=900) as res:
        s = res.summary
        check("失败 2 次被记账", s.capture_failures == 2, f"capture_failures={s.capture_failures}")
        check("成功 3 帧", s.frames == 3, f"frames={s.frames}")
        rows = res.jsonl_lines
        check("失败的轮次也写一行（每轮一行不变）", len(rows) == 5, f"lines={len(rows)}")
        check("失败轮 frame_hash=None 且 note 说明原因",
              rows[1]["frame_hash"] is None and "采帧失败" in rows[1]["note"],
              f"{rows[1]['frame_hash']!r} / {rows[1]['note']!r}")
        check("失败不重置静止计时（unchanged_sec 继续走）",
              [r["unchanged_sec"] for r in rows] == [0.0, 20.0, 40.0, 60.0, 80.0],
              f"{[r['unchanged_sec'] for r in rows]}")


# ---------------------------------------------------------------------------
# 9. 外部 stop（真实线程）
# ---------------------------------------------------------------------------
def stop_after_two_frames(interval: float = 0.02, stall: float = 900.0) -> dict:
    """真实线程 + 真实短暂等待：``start()`` → 抓够 2 帧 → ``stop()`` → ``join()``。

    返回退出事实（**在清临时目录之前**取好，单测与 ``hooks_98`` 共用这一份实现）。
    """
    root = Path(tempfile.mkdtemp(prefix="wf_98_thread_"))
    two_calls = threading.Event()
    calls = {"n": 0}

    def capture() -> Any:
        calls["n"] += 1
        if calls["n"] >= 2:
            two_calls.set()
        return solid_frame(40)

    monitor = lm.LongrunMonitor(
        capture,
        interval=interval,
        stall=stall,
        out=root / "longrun",
        serial="thread-serial",
        log=lambda _line: None,
    )
    try:
        monitor.start()
        fired = two_calls.wait(5.0)
        monitor.stop()
        monitor.join(timeout=5.0)
        summary = monitor.summary
        return {
            "fired": fired,
            "alive": monitor.is_alive,
            "has_summary": summary is not None,
            "stop_reason": summary.stop_reason if summary else None,
            "frames": summary.frames if summary else 0,
            "elapsed_sec": summary.elapsed_sec if summary else 0.0,
            "jsonl_is_file": bool(summary and summary.jsonl_path and summary.jsonl_path.is_file()),
        }
    finally:
        monitor.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_stop_from_other_thread() -> None:
    print("\n== 9. 别的线程随时能 stop()（真实线程 + 短暂真实等待）==")
    facts = stop_after_two_frames()
    check("stop() 后线程按时退出（不会白等满 interval）", facts["fired"] and not facts["alive"], str(facts))
    check("小结已生成且退出原因 = stop", facts["has_summary"] and facts["stop_reason"] == "stop",
          str(facts.get("stop_reason")))
    check("至少采到 1 帧", facts["frames"] >= 1, f"frames={facts['frames']}")
    check("JSONL 已落盘", facts["jsonl_is_file"] is True)
    check("运行时长很短（stop 打断的是等待，不是跑满 interval）", 0.0 < facts["elapsed_sec"] < 5.0,
          f"elapsed={facts['elapsed_sec']:.3f}s")


# ---------------------------------------------------------------------------
# 10. CLI 契约（默认值 = spec；非法参数在碰设备之前就报错）
# ---------------------------------------------------------------------------
def _system_exit_code(fn: Callable[[], Any]) -> int | None:
    """跑一个应当立刻退出的调用，返回退出码（顺手吞掉 argparse 打到 stderr 的 usage）。"""
    sink = io.StringIO()
    try:
        with contextlib.redirect_stderr(sink):
            fn()
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2
    return None


def test_cli_contract() -> None:
    print("\n== 10. CLI 契约：默认值 + 参数校验（不碰设备）==")
    args = lm.build_parser().parse_args(["--serial", "127.0.0.1:16384"])
    check("--interval 默认 20", args.interval == 20.0, f"{args.interval}")
    check("--stall 默认 90", args.stall == 90.0, f"{args.stall}")
    check("--out 默认 debug/longrun", args.out == "debug/longrun", f"{args.out!r}")
    check("--duration 默认 None（一直跑）", args.duration is None)
    check("--beep 默认关", args.beep is False)
    check(
        "抓屏 argv 是只读的 exec-out screencap -p",
        lm.screencap_cmd("127.0.0.1:16384", adb="adb") == ["adb", "-s", "127.0.0.1:16384", "exec-out", "screencap", "-p"],
        str(lm.screencap_cmd("127.0.0.1:16384", adb="adb")),
    )
    check("--interval 0 在起采集之前就拒绝",
          _system_exit_code(lambda: lm.main(["--serial", "x", "--interval", "0"])) == 2)
    check("--stall 0 在起采集之前就拒绝",
          _system_exit_code(lambda: lm.main(["--serial", "x", "--stall", "0"])) == 2)
    check("--duration 0 在起采集之前就拒绝",
          _system_exit_code(lambda: lm.main(["--serial", "x", "--duration", "0"])) == 2)

    # 缺 --serial：把默认值临时置空再验（防止本机 WF_LIVE_ADDRESS 让这一步真的去连设备）
    real_default = lm.DEFAULT_SERIAL
    lm.DEFAULT_SERIAL = ""
    try:
        check("缺 --serial 直接报错退出（不会去连设备）",
              _system_exit_code(lambda: lm.main([])) == 2)
    finally:
        lm.DEFAULT_SERIAL = real_default

    check("串号进文件名时被清洗成安全片段", lm._slug("127.0.0.1:16384") == "127.0.0.1_16384",
          lm._slug("127.0.0.1:16384"))
    check("空串号退回 device", lm._slug("") == "device")


# ---------------------------------------------------------------------------
# 11. 判据边界 + 构造参数校验
# ---------------------------------------------------------------------------
def test_boundaries() -> None:
    print("\n== 11. 判据边界（≥）+ 构造参数校验 ==")
    check("89.9s < 90s 不报警", lm.is_stalled(89.9, 90) is False)
    check("90.0s 正好报警（判据是 ≥）", lm.is_stalled(90.0, 90) is True)
    check("120s ≥ 90s 报警", lm.is_stalled(120.0, 90) is True)
    check("阈值常量就是 spec 的 20/90", (lm.DEFAULT_INTERVAL, lm.DEFAULT_STALL) == (20.0, 90.0))
    check("JSONL 必带字段顺序固定（改名=破坏契约）",
          lm.REQUIRED_FIELDS == ("ts", "frame_hash", "changed", "unchanged_sec", "note"), str(lm.REQUIRED_FIELDS))

    try:
        lm.LongrunMonitor(lambda: solid_frame(1), interval=0)
    except ValueError:
        check("interval<=0 拒绝构造", True)
    else:
        check("interval<=0 拒绝构造", False)
    try:
        lm.LongrunMonitor("不是可调用对象")
    except TypeError:
        check("capture 不可调用 → TypeError", True)
    else:
        check("capture 不可调用 → TypeError", False)


# ---------------------------------------------------------------------------
# 12. 默认 adb 采集确实接在循环上（用一个**不存在**的 adb，绝不连设备）
# ---------------------------------------------------------------------------
def test_default_capture_wiring() -> None:
    print("\n== 12. 默认 adb 采集已接线：采集失败只记账、不崩（不碰设备）==")
    clock = FakeClock()
    lines: list[str] = []
    root = Path(tempfile.mkdtemp(prefix="wf_98_adb_"))
    # adb 名字根本不存在 → subprocess 立刻 FileNotFoundError，连 adb 二进制都没被解析。
    capture = _StopAfter(lm.adb_capture("wf-no-such-serial", adb="wf98-no-such-adb-xyz"), 1)
    monitor = lm.LongrunMonitor(
        capture,
        interval=20,
        stall=90,
        out=root / "longrun",
        serial="no-such-device",
        now=clock,
        wait=clock.advance,
        log=lines.append,
    )
    capture.monitor = monitor
    try:
        summary = monitor.run()  # 不许抛
        rows = read_jsonl(summary.jsonl_path) if summary.jsonl_path else []
    finally:
        shutil.rmtree(root, ignore_errors=True)
    check("采集抛异常也没把监管弄崩（有小结）", summary is not None and summary.stop_reason == "stop",
          str(getattr(summary, "stop_reason", None)))
    check("失败被记账", summary.capture_failures == 1, f"capture_failures={summary.capture_failures}")
    check("成功帧 0", summary.frames == 0, f"frames={summary.frames}")
    check("失败的那一轮照样写一行心跳",
          len(rows) == 1 and rows[0]["frame_hash"] is None and "采帧失败" in rows[0]["note"],
          f"{rows[0]['note']!r}" if rows else "无")
    check("没误报卡住", summary.stall_count == 0)


# ---------------------------------------------------------------------------
def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 76)
    print("#98 离线单测：长跑监管（20s 心跳 / 90s 卡住 / 证据落盘）")
    print("=" * 76)
    test_coarse_hash()
    test_heartbeat_jsonl()
    test_stall_alarm()
    test_moving_frames_no_false_alarm()
    test_stall_dedup_and_rearm()
    test_state_keeps_moving()
    test_duration_exit()
    test_capture_failure_survives()
    test_stop_from_other_thread()
    test_cli_contract()
    test_boundaries()
    test_default_capture_wiring()

    print("\n" + "=" * 76)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
