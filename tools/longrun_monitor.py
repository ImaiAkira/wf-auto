# -*- coding: utf-8 -*-
"""#98 长跑监管：20s 心跳采帧 + 90s 卡住报警 + 证据落盘。

运维原话：「你的监管一直都非常不及时，经常出问题」——原来的做法是**跑完才看日志**，
真机卡住只能事后翻 ``debug/maafw*.log``。本模块把监管搬进**跑的过程里**：

    每 interval 秒抓一帧 ─→ 64x64 灰度 → 4bit 量化（粗指纹）─→ 与上一帧 + 状态比
                                                        ├─ 变了：刷新「上次变化」时刻
                                                        └─ 画面+状态都不变 ≥ stall 秒
                                                             → 落帧 PNG + 高亮报警 + 响铃

每轮无条件写一行 JSONL（``--out`` 目录下 ``<serial>-<ts>.jsonl``），字段见
:data:`REQUIRED_FIELDS`，运维可以边跑边 ``Get-Content -Wait`` 跟着看。

设计约束（都是真机坑换来的）
---------------------------
* **只读**：默认采集是 ``adb -s <serial> exec-out screencap -p``，不点屏幕、不按键、不换机
  （spec §4.5：只报警，不自动换机），因此不会干扰正在跑的 MAA 任务。
* **采集可注入**：``capture`` 是零参可调用对象（返回 PNG bytes / PIL Image / 路径）。
  测试与守卫注入假帧，**永不碰设备**；默认 adb 实现在 :func:`adb_capture`，CLI 才用。
* **可被外部停**：:meth:`LongrunMonitor.stop` 线程安全（``threading.Event``），
  runner 在任务收工 / Ctrl-C 时一调，最多等一个 ``interval`` 就退出；而且等待本身是
  ``Event.wait``，会被**立刻**打断，不会白等满 20 秒。
* **抓帧失败不崩**：一次 adb 抖动不该让监管整个死掉（那正是「监管不及时」的老毛病）。
  失败写进 ``note`` 并计入小结，静止计时**不重置**（连不上设备本身也该被看见）。
* **画面 + 状态都不变才算卡住**（spec §4.5）：``state_fn`` 由 runner 注入当前页面/进度
  （如 ``第3/10次 战斗``）。状态在动时哪怕画面是同一张也**不算**卡住。
* **量化即容差**：4bit（步长 16 灰度）把真机上小精灵 / 闪烁那种个位数抖动吸收掉；
  真要调灵敏度改 :data:`QUANT_LEVELS`（越小越迟钝、越大越敏感）。
* **判据单调**：卡住判定就是一个纯函数 :func:`is_stalled`（``unchanged_sec >= stall``），
  守卫 ``hooks_98`` 的 prove-red 正是把它换成恒 ``False`` 来验证报警链路真的被覆盖。

跑法::

    # 盯着一台设备跑 10 分钟，90s 不动就落帧 + 响铃
    .venv\\Scripts\\python.exe tools\\longrun_monitor.py --serial 127.0.0.1:16384 --duration 600 --beep

    # runner 集成（交给 runner 自己起停）
    mon = monitor_for_serial("127.0.0.1:16384", state_fn=runner.current_state)
    mon.start()
    try:
        ...跑任务...
    finally:
        mon.stop(); mon.join()
        print(mon.summary.as_line())

线程安全边界：``stop()`` / ``jsonl_path`` / ``summary`` 可从任意线程读；
``run()`` 只允许一个线程（同一个实例不要并发 ``run()``）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

#: 默认 adb（与 ``tools/live_harness.py`` 共用同一套环境变量，不新增配置面）。
DEFAULT_ADB = os.environ.get("WF_LIVE_ADB") or "adb"
#: 默认设备串号（同 harness 的 ``WF_LIVE_ADDRESS``）。
DEFAULT_SERIAL = os.environ.get("WF_LIVE_ADDRESS") or ""

#: spec §4.5：20s 采帧心跳。
DEFAULT_INTERVAL = 20.0
#: spec §4.5：画面 + 状态不变 ≥90s 报警。
DEFAULT_STALL = 90.0
#: 默认输出目录（``debug`` 已在 .gitignore 里）。
DEFAULT_OUT = "debug/longrun"

#: 粗指纹的边长：与 #23 stall 看门狗同一把尺（64x64 灰度）。
SIGNATURE_SIZE = 64
#: 每格量化档数（16 = 4bit，步长 16 灰度）。
QUANT_LEVELS = 16

#: JSONL 每行**必带**的字段（hooks_98 逐字段核对；改名=破坏契约，别改）。
REQUIRED_FIELDS = ("ts", "frame_hash", "changed", "unchanged_sec", "note")

_STOP = "stop"
_DURATION = "duration"
_STATE_UNKNOWN = "unknown"
_STATE_ERROR = "<state-error>"


# ---------------------------------------------------------------------------
# 帧 → 粗指纹
# ---------------------------------------------------------------------------
def _pil():
    """延迟导入 Pillow：缺依赖时给一句人话，而不是 import 期就炸掉整个套件。"""
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - .venv 里有 Pillow
        raise RuntimeError(
            "长跑监管需要 Pillow（仓库 .venv 里已有）：.venv\\Scripts\\python.exe -m pip install pillow"
        ) from exc
    return Image


def _resample():
    """Pillow 9.1+ 用 ``Image.Resampling.LANCZOS``，老版本退回 ``Image.LANCZOS``。"""
    Image = _pil()
    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def _as_bytes(frame: Any) -> bytes | None:
    if isinstance(frame, (bytes, bytearray, memoryview)):
        return bytes(frame)
    return None


def to_image(frame: Any):
    """把采集可能吐出来的东西统一成 ``PIL.Image``（PNG bytes / PIL Image / 路径）。"""
    Image = _pil()
    if isinstance(frame, Image.Image):
        return frame
    raw = _as_bytes(frame)
    if raw is not None:
        return Image.open(io.BytesIO(raw))
    if isinstance(frame, (str, os.PathLike)):
        return Image.open(frame)
    raise TypeError(f"不认识的帧类型 {type(frame)!r}（要 PNG bytes / PIL.Image / 路径）")


def frame_signature(frame: Any) -> bytes:
    """粗指纹：缩到 64x64 灰度，再把每格量化成 4bit（返回 4096 字节）。

    同一张图必然同一指纹；量化步长（16 灰度）以内的抖动会被吸收 —— 这就是容差。
    """
    img = to_image(frame).convert("L").resize((SIGNATURE_SIZE, SIGNATURE_SIZE), _resample())
    step = max(1, 256 // QUANT_LEVELS)
    return bytes(v // step for v in img.tobytes())


def signature_digest(signature: bytes) -> str:
    """把指纹压成 16 位 hex 摘要（JSONL 里的 ``frame_hash``，人眼可比、机器可 diff）。"""
    return hashlib.sha1(signature).hexdigest()[:16]


def frame_hash(frame: Any) -> str:
    """一帧的粗哈希（16 hex chars）。同一个画面 → 同一个值。"""
    return signature_digest(frame_signature(frame))


def save_frame(frame: Any, path: str | os.PathLike) -> Path:
    """把**当时那一帧**原样落盘（PNG bytes 直接写，绝不重编码）。

    证据的意义在于「报警时画面就是这个样子」——所以能原样写就原样写。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _as_bytes(frame)
    if raw is not None and raw[:8] == b"\x89PNG\r\n\x1a\n":
        path.write_bytes(raw)
        return path
    to_image(frame).save(path)
    return path


# ---------------------------------------------------------------------------
# 卡住判定（纯函数 —— prove-red 就把它换成恒 False）
# ---------------------------------------------------------------------------
def is_stalled(unchanged_sec: float, stall: float) -> bool:
    """画面 + 状态连续不变 ``unchanged_sec`` 秒，是否已达到报警阈值（≥）。"""
    return float(unchanged_sec) >= float(stall)


# ---------------------------------------------------------------------------
# 时间 / 文件名
# ---------------------------------------------------------------------------
def _iso(ts: float) -> str:
    """本地时间 ISO（带毫秒），如 ``2026-10-17T20:15:00.123``。"""
    return datetime.fromtimestamp(float(ts)).isoformat(timespec="milliseconds")


def _stamp(ts: float) -> str:
    """文件名用紧凑时间戳，如 ``20261017-201500``。"""
    return datetime.fromtimestamp(float(ts)).strftime("%Y%m%d-%H%M%S")


def _slug(text: str) -> str:
    """串号 → 文件名安全片段（``127.0.0.1:16384`` → ``127.0.0.1_16384``）。"""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "")).strip("_") or "device"


def _print_line(message: str) -> None:
    print(message, flush=True)


def _read_state(state_fn: Callable[[], Any] | None) -> str:
    """读 runner 注入的状态；没注入 / 读炸了都给一个稳定的占位串（不让监管死掉）。"""
    if state_fn is None:
        return _STATE_UNKNOWN
    try:
        value = state_fn()
    except Exception:  # noqa: BLE001 - runner 的状态回调用坏了也不能把监管弄死
        return _STATE_ERROR
    return _STATE_UNKNOWN if value is None else str(value)


# ---------------------------------------------------------------------------
# 采集：默认 adb 实现（只读，只抓屏）
# ---------------------------------------------------------------------------
def screencap_cmd(serial: str, *, adb: str = DEFAULT_ADB) -> list[str]:
    """抓屏命令（纯函数，测试可以在不碰设备的前提下核对 argv）。"""
    return [str(adb), "-s", str(serial), "exec-out", "screencap", "-p"]


def adb_capture(serial: str, *, adb: str = DEFAULT_ADB) -> Callable[[], bytes]:
    """默认采集：``adb exec-out screencap -p`` 拿 PNG 原始字节（只读，不发任何输入）。"""
    cmd = screencap_cmd(serial, adb=adb)

    def _capture() -> bytes:
        proc = subprocess.run(cmd, capture_output=True)  # noqa: S603 - 固定的只读抓屏 argv
        if proc.returncode != 0 or not proc.stdout:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            tail = err[-1] if err else ""
            raise RuntimeError(f"adb screencap 失败（rc={proc.returncode}）{('：' + tail) if tail else ''}")
        return proc.stdout

    return _capture


# ---------------------------------------------------------------------------
# 小结
# ---------------------------------------------------------------------------
@dataclass
class Summary:
    """一次监管跑完的账（runner 收工时打这一行就够运维看）。"""

    serial: str
    started_ts: float
    elapsed_sec: float
    frames: int
    longest_unchanged_sec: float
    stall_count: int
    capture_failures: int
    jsonl_path: Path | None
    stop_reason: str

    def as_line(self) -> str:
        return (
            f"[长跑监管小结] {self.serial or 'device'} 运行 {self.elapsed_sec:.1f}s / "
            f"采帧 {self.frames} 帧 / 最长静止 {self.longest_unchanged_sec:.1f}s / "
            f"卡住 {self.stall_count} 次 / 采帧失败 {self.capture_failures} 次 / "
            f"退出原因 {self.stop_reason} / 日志 {self.jsonl_path if self.jsonl_path else '（未写）'}"
        )


# ---------------------------------------------------------------------------
# 监管本体
# ---------------------------------------------------------------------------
class LongrunMonitor:
    """长跑监管：``run()`` 阻塞跑，``start()`` 后台跑，``stop()`` 随时打断。

    参数
    ----
    capture : 零参可调用，返回一帧（PNG bytes / PIL.Image / 路径）。**唯一**的采集入口，
        测试注入假帧即可完全离线。
    interval : 心跳间隔（秒），默认 20（spec §4.5）。
    stall : 卡住阈值（秒），默认 90（spec §4.5）。
    out : JSONL + 卡住帧的输出目录，默认 ``debug/longrun``。
    serial : 只用于文件名与日志（``<serial>-<ts>.jsonl``），不参与采集。
    state_fn : 可选，返回当前状态（页面 / 第 i/N 次）；状态变化也刷新「上次变化」。
    beep : 卡住时响铃（Windows ``winsound``，退回终端 ``\\a``）。
    duration : 跑多少秒自动退出；``None`` = 一直跑到 ``stop()``。
    now / wait : 可注入的时钟与等待（单元测试用假时钟推进，绝不真睡）。
    log : 单行日志出口，默认 ``print(flush=True)``。
    """

    def __init__(
        self,
        capture: Callable[[], Any],
        *,
        interval: float = DEFAULT_INTERVAL,
        stall: float = DEFAULT_STALL,
        out: str | os.PathLike = DEFAULT_OUT,
        serial: str = "",
        state_fn: Callable[[], Any] | None = None,
        beep: bool = False,
        duration: float | None = None,
        now: Callable[[], float] = time.time,
        wait: Callable[[float], Any] | None = None,
        log: Callable[[str], Any] | None = None,
    ) -> None:
        if not callable(capture):
            raise TypeError("capture 必须是零参可调用对象（返回 PNG bytes / PIL.Image / 路径）")
        if float(interval) <= 0:
            raise ValueError(f"interval 必须 > 0（给的 {interval!r}）")
        if float(stall) <= 0:
            raise ValueError(f"stall 必须 > 0（给的 {stall!r}）")
        self.capture = capture
        self.interval = float(interval)
        self.stall = float(stall)
        self.out = Path(out)
        self.serial = str(serial or "")
        self.state_fn = state_fn
        self.beep_enabled = bool(beep)
        self.duration = None if duration is None else float(duration)
        self._now = now
        self._log = log or _print_line

        self._stop = threading.Event()
        self._wait_fn: Callable[[float], Any] = wait if wait is not None else self._stop.wait
        self._thread: threading.Thread | None = None
        self._running = False
        self._jsonl = None
        self._jsonl_path: Path | None = None
        self.summary: Summary | None = None
        self.started_ts = 0.0
        self._reset()

    # -- 计数 / 状态复位 ---------------------------------------------------
    def _reset(self) -> None:
        self.frames = 0
        self.stall_count = 0
        self.capture_failures = 0
        self.longest_unchanged_sec = 0.0
        self._idx = 0
        self._prev_sig: bytes | None = None
        self._prev_state: str | None = None
        self._have_base = False
        self._last_frame: Any = None
        self._last_change = 0.0
        self._stall_open = False
        self._stop_reason = _STOP

    # -- 外部可读 ----------------------------------------------------------
    @property
    def jsonl_path(self) -> Path | None:
        return self._jsonl_path

    @property
    def stop_reason(self) -> str:
        return self._stop_reason

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- 生命周期 ----------------------------------------------------------
    def stop(self) -> None:
        """线程安全、幂等：任何线程都能调，等待中的循环会立刻醒来退出。"""
        self._stop.set()

    def run(self) -> Summary:
        """阻塞跑监管循环，退出时打小结并返回 :class:`Summary`。"""
        if self._running:
            raise RuntimeError("同一个 LongrunMonitor 不能并发 run()（先 stop()/join()）")
        self._running = True
        try:
            return self._loop()
        finally:
            self._running = False
            self._close_jsonl()

    def start(self) -> threading.Thread:
        """后台线程跑（runner 用这个）；返回线程对象，配合 :meth:`stop` / :meth:`join`。"""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("监管已经在跑（先 stop() + join()）")
        thread = threading.Thread(
            target=self._run_guarded,
            name=f"longrun-monitor-{_slug(self.serial)}",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return thread

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def __enter__(self) -> "LongrunMonitor":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.stop()
        self.join(timeout=max(5.0, self.interval + 1.0))
        return False

    def _run_guarded(self) -> None:
        try:
            self.run()
        except Exception as exc:  # noqa: BLE001 - 后台线程里炸掉会静默丢失监管
            self._log(f"[长跑监管] 循环异常退出：{exc!r}")

    # -- 主循环 ------------------------------------------------------------
    def _loop(self) -> Summary:
        self._reset()
        start = float(self._now())
        self.started_ts = start
        self._last_change = start
        self._open_jsonl(start)
        total = self._expected_rounds()

        while not self._stop.is_set():
            now = float(self._now())
            if self.duration is not None and self._idx > 0 and (now - start) >= self.duration:
                self._stop_reason = _DURATION
                break
            self._idx += 1
            self._round(self._idx, total, now)
            if self._stop.is_set():
                break
            pause = self.interval
            if self.duration is not None:
                pause = min(pause, max(0.0, self.duration - (float(self._now()) - start)))
            if pause > 0:
                self._wait_fn(pause)

        elapsed = max(0.0, float(self._now()) - start)
        self.summary = Summary(
            serial=self.serial,
            started_ts=start,
            elapsed_sec=elapsed,
            frames=self.frames,
            longest_unchanged_sec=self.longest_unchanged_sec,
            stall_count=self.stall_count,
            capture_failures=self.capture_failures,
            jsonl_path=self._jsonl_path,
            stop_reason=self._stop_reason,
        )
        self._log(self.summary.as_line())
        return self.summary

    def _expected_rounds(self) -> int | None:
        """``--duration`` 下的计划轮数（JSONL 的 ``total``，即「第 i/N 轮」的 N）。

        与 ``_loop`` 的实际轮数一致：t=0 起每 ``interval`` 一轮，到 ``duration`` 收工 ——
        所以轮数 = ceil(duration / interval)（duration=60/interval=20 → 3 轮：0/20/40）。
        """
        if self.duration is None:
            return None
        return max(1, int(math.ceil(self.duration / self.interval)))

    # -- 一轮 --------------------------------------------------------------
    def _round(self, idx: int, total: int | None, now: float) -> None:
        state = _read_state(self.state_fn)
        sig: bytes | None = None
        note = ""
        try:
            frame = self.capture()
        except Exception as exc:  # noqa: BLE001 - 一次 adb 抖动不许让监管整体死掉
            self.capture_failures += 1
            note = f"采帧失败: {exc!r}"
        else:
            try:
                sig = frame_signature(frame)
            except Exception as exc:  # noqa: BLE001 - 坏帧同样按采帧失败处理
                self.capture_failures += 1
                note = f"帧解析失败: {exc!r}"
            else:
                self.frames += 1
                self._last_frame = frame

        changed = False
        if sig is not None:
            if not self._have_base:
                self._have_base = True
                changed = True
                note = note or "首帧（建立基准）"
            else:
                frame_moved = sig != self._prev_sig
                state_moved = state != self._prev_state
                changed = frame_moved or state_moved
                if changed:
                    parts = []
                    if frame_moved:
                        parts.append("画面变化")
                    if state_moved:
                        parts.append(f"状态变化 {self._prev_state!r}→{state!r}")
                    note = note or "，".join(parts)
                else:
                    note = note or "画面+状态无变化"
            self._prev_sig = sig
            self._prev_state = state

        if changed:
            self._last_change = now
            self._stall_open = False

        unchanged = max(0.0, now - self._last_change)
        self.longest_unchanged_sec = max(self.longest_unchanged_sec, unchanged)

        png: Path | None = None
        if is_stalled(unchanged, self.stall):
            if not self._stall_open:
                self._stall_open = True
                self.stall_count += 1
                png = self._dump_stall_frame(now)
                self._print_alarm(unchanged, png)
                self._beep_once()
                note = f"★★ 卡住 {unchanged:.1f}s ★★" + (
                    f"（帧已落盘 {png.name}）" if png else "（无帧可落：还没抓到过任何一帧）"
                )
            else:
                note = f"仍卡住 {unchanged:.1f}s（已报警，不重复落盘）"

        self._write_line(idx, total, now, sig, changed, unchanged, state, note, png)

    # -- 报警 + 证据 -------------------------------------------------------
    def _print_alarm(self, unchanged: float, png: Path | None) -> None:
        line = f"★★ 卡住 {unchanged:.1f} 秒 ★★"
        tail = f"  帧证据 {png}" if png is not None else "  （无帧可落：还没抓到过任何一帧）"
        self._log(line + tail)

    def _dump_stall_frame(self, now: float) -> Path | None:
        frame = self._last_frame
        if frame is None:
            return None
        base = self.out / f"stall_{_stamp(now)}"
        path = base.with_suffix(".png")
        n = 1
        while path.exists():  # 同一秒里第二次报警也不覆盖上一张证据
            path = base.parent / f"{base.name}_{n}.png"
            n += 1
        try:
            return save_frame(frame, path)
        except Exception as exc:  # noqa: BLE001 - 落盘失败要吼一声，但不能掐死监管
            self._log(f"[长跑监管] 卡住帧落盘失败 {path}：{exc!r}")
            return None

    def _beep_once(self) -> None:
        if not self.beep_enabled:
            return
        try:
            import winsound  # noqa: PLC0415 - 只有 Windows 有

            winsound.Beep(1200, 400)
        except Exception:  # noqa: BLE001 - 非 Windows / 没声音设备就退回终端响铃
            try:
                sys.stderr.write("\a")
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass

    # -- JSONL -------------------------------------------------------------
    def _open_jsonl(self, start: float) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self.out / f"{_slug(self.serial)}-{_stamp(start)}.jsonl"
        self._jsonl = open(self._jsonl_path, "a", encoding="utf-8")  # noqa: SIM115 - 生命周期与 run() 绑定

    def _close_jsonl(self) -> None:
        if self._jsonl is not None:
            try:
                self._jsonl.close()
            finally:
                self._jsonl = None

    def _write_line(
        self,
        idx: int,
        total: int | None,
        now: float,
        sig: bytes | None,
        changed: bool,
        unchanged: float,
        state: str,
        note: str,
        png: Path | None,
    ) -> None:
        payload = {
            "ts": _iso(now),
            "frame_hash": signature_digest(sig) if sig is not None else None,
            "changed": bool(changed),
            "unchanged_sec": round(float(unchanged), 1),
            "note": note,
            "ts_epoch": round(float(now), 3),
            "idx": idx,
            "total": total,
            "state": state,
            "frame_png": str(png) if png is not None else None,
        }
        if self._jsonl is None:  # 兜底：没走 run() 就直接写一行（异常路径）
            self._open_jsonl(now)
        handle = self._jsonl
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()  # 每行刷盘：运维 Get-Content -Wait 才跟得上，崩了也不丢


# ---------------------------------------------------------------------------
# 给 runner 的一行式入口
# ---------------------------------------------------------------------------
def monitor_for_serial(serial: str, *, adb: str = DEFAULT_ADB, **kwargs: Any) -> LongrunMonitor:
    """按串号建默认 adb 采集的监管（runner 集成入口，见模块 docstring）。"""
    return LongrunMonitor(
        adb_capture(serial, adb=adb),
        serial=serial,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _file_state_reader(path: str | os.PathLike | None) -> Callable[[], str] | None:
    """``--state-file``：runner 把当前状态写进这个文件，本模块只读首行（不用改代码）。"""
    if not path:
        return None
    target = Path(path)

    def _read() -> str:
        text = target.read_text(encoding="utf-8").strip()
        return text.splitlines()[0] if text else _STATE_UNKNOWN

    return _read


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="longrun_monitor.py",
        description="#98 长跑监管：20s 心跳采帧 / 90s 卡住报警 / 证据落盘（只读抓帧，不点屏幕）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--serial", default=DEFAULT_SERIAL, help="设备串号，如 127.0.0.1:16384（也可用 WF_LIVE_ADDRESS）")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="采帧心跳间隔（秒）")
    ap.add_argument("--stall", type=float, default=DEFAULT_STALL, help="画面+状态不变的报警阈值（秒）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="JSONL 与卡住帧的输出目录")
    ap.add_argument("--duration", type=float, default=None, help="跑多少秒自动退出（缺省=一直跑到 Ctrl-C）")
    ap.add_argument("--beep", action="store_true", help="卡住时响铃（Windows winsound，退回终端 \\a）")
    ap.add_argument("--adb", default=DEFAULT_ADB, help="adb 可执行文件（也可用 WF_LIVE_ADB）")
    ap.add_argument("--state-file", default=None, help="可选：读这个文件的首行当 state（runner 写它即可）")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.serial:
        ap.error("--serial 必填（或用环境变量 WF_LIVE_ADDRESS）")
    if args.interval <= 0:
        ap.error(f"--interval 必须 > 0（给的 {args.interval}）")
    if args.stall <= 0:
        ap.error(f"--stall 必须 > 0（给的 {args.stall}）")
    if args.duration is not None and args.duration <= 0:
        ap.error(f"--duration 必须 > 0（给的 {args.duration}）")

    monitor = monitor_for_serial(
        args.serial,
        adb=args.adb,
        interval=args.interval,
        stall=args.stall,
        out=args.out,
        state_fn=_file_state_reader(args.state_file),
        beep=args.beep,
        duration=args.duration,
    )
    if args.stall < args.interval:
        print(
            f"[长跑监管] 注意：阈值 {args.stall}s 比心跳 {args.interval}s 还短，"
            f"实际报警精度 = 心跳间隔（最多晚一个 interval）",
            flush=True,
        )
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
        print("\n[长跑监管] Ctrl-C：已停", flush=True)
        return 130
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
