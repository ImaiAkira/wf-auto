# -*- coding: utf-8 -*-
"""长跑监管：20s 心跳 + 90s 卡住报警 + 「有动作无进展」报警 + 证据落盘。

#98 的起点
----------
运维原话：「你的监管一直都非常不及时，经常出问题」——原来的做法是**跑完才看日志**，
真机卡住只能事后翻 ``debug/maafw*.log``。本模块把监管搬进**跑的过程里**：

    每 interval 秒抓一帧 ─→ 64x64 灰度 → 4bit 量化（粗指纹）─→ 与上一帧 + 状态比
                                                        ├─ 变了：刷新「上次变化」时刻
                                                        └─ 画面+状态都不变 ≥ stall 秒
                                                             → 落帧 PNG + 高亮报警 + 响铃

每轮无条件写一行 JSONL（``--out`` 目录下 ``<serial>-<ts>.jsonl``），字段见
:data:`REQUIRED_FIELDS`，运维可以边跑边 ``Get-Content -Wait`` 跟着看。

#140 补的三个洞（真机 484 / 第 6 轮验收，2026-10-18 18:38:17–18:46:11）
----------------------------------------------------------------------
现场：80 次滚动 × 6.0s/次 = **474s 空转**，0 条「页读」、0 个目标；事后有人报
``debug/longrun/127.0.0.1_16448-20261018-183349.jsonl = 0 字节``。取证后三件事各自成立：

1. **0 字节是「文件已建、第一行还没写」的窗口**：``_open_jsonl`` 在 ``_loop`` 开头就
   建文件，但第一行要等**第一轮采集返回后**才写；默认采集 ``adb exec-out screencap -p``
   原来没有超时，设备/ adb 一卡，文件就一直是 0 字节 —— 和「监管根本没启动」长得一模一样。
   现在：① 文件一打开就落一条 ``kind="start"`` 行；② adb 采集带超时（:data:`CAPTURE_TIMEOUT_SEC`），
   超时记一次采帧失败、心跳继续；③ 收工落 ``kind="stop"`` 行；④ 跑完自检，日志为空就
   **显式报错**（:attr:`Summary.error` + 控制台 ✗ + CLI 非零退出），不许静默通过。
2. **心跳不能只在「状态变化」时写**：现场那一跑其实写了 53 行（18:33:49→18:51:22，每 20s
   一行），但 53 行全是 ``changed=true / unchanged_sec=0.0`` —— 每次滚动画面都在变，
   旧判据只能看见「画面在动」。现在每行都带 ``state / progress_marker / actions /
   last_progress_ts``，**状态不变也照写**（每轮一行，沿用 20s 心跳）。
3. **「有动作但无进展」要单独报警**：连续动作 ≥ :data:`NO_PROGRESS_ACTIONS` 次、且业务
   进展 ≥ :data:`NO_PROGRESS_SEC` 秒没推进 → 一条 ``★★ 有动作无进展 ★★``，含动作数与
   停滞秒数（比「卡住不动」隐蔽得多，现场正是这一形态）。判据是纯函数
   :func:`is_action_without_progress`，守卫 ``hooks_140`` 的破坏实验就是把它换成恒
   ``False`` 来验证报警链路真的被覆盖。

设计约束（都是真机坑换来的）
---------------------------
* **只读**：默认采集是 ``adb -s <serial> exec-out screencap -p``，不点屏幕、不按键、不换机
  （spec §4.5：只报警，不自动换机），因此不会干扰正在跑的 MAA 任务。
* **采集可注入**：``capture`` 是零参可调用对象（返回 PNG bytes / PIL Image / 路径）。
  测试与守卫注入假帧，**永不碰设备**；默认 adb 实现在 :func:`adb_capture`，CLI 才用。
* **可被外部停**：:meth:`LongrunMonitor.stop` 线程安全（``threading.Event``），
  runner 在任务收工 / Ctrl-C 时一调，最多等一个 ``interval`` 就退出；而且等待本身是
  ``Event.wait``，会被**立刻**打断，不会白等满 20 秒。
* **抓帧失败不崩**：一次 adb 抖动/超时不该让监管整个死掉（那正是「监管不及时」的老毛病）。
  失败写进 ``note`` 并计入小结，静止计时**不重置**（连不上设备本身也该被看见）。
* **画面 + 状态都不变才算卡住**（spec §4.5）：``state_fn`` 由 runner 注入当前页面/进度
  （如 ``第3/10次 战斗``）。状态在动时哪怕画面是同一张也**不算**卡住。
* **量化即容差**：4bit（步长 16 灰度）把真机上小精灵 / 闪烁那种个位数抖动吸收掉；
  真要调灵敏度改 :data:`QUANT_LEVELS`（越小越迟钝、越大越敏感）。
* **判据单调**：卡住判定是纯函数 :func:`is_stalled`（``unchanged_sec >= stall``）；
  「有动作无进展」是纯函数 :func:`is_action_without_progress`。守卫的 prove-red 正是把它们
  换成恒 ``False`` / 调歪阈值来验证报警链路真的被覆盖。

跑法::

    # 盯着一台设备跑 10 分钟，90s 不动就落帧 + 响铃
    .venv\\Scripts\\python.exe tools\\longrun_monitor.py --serial 127.0.0.1:16384 --duration 600 --beep

    # runner 集成（交给 runner 自己起停）
    mon = monitor_for_serial("127.0.0.1:16384", state_fn=runner.current_state)
    mon.start()
    try:
        ...跑任务（每次滚动/点击后 mon.note_action("scroll")，每次读到新行/新目标后
           mon.note_progress("rows:12")；也可以直接注入 actions_fn / progress_fn）...
    finally:
        mon.stop(); mon.join()
        print(mon.summary.as_line())
        if mon.summary.error:  # ★#140★ 日志为空 / 写盘失败 = 显式错误，不许静默
            raise SystemExit(mon.summary.error)

线程安全边界：``stop()`` / ``note_action()`` / ``note_progress()`` / ``jsonl_path`` /
``summary`` 可从任意线程读；``run()`` 只允许一个线程（同一个实例不要并发 ``run()``）。
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

#: spec §4.5：20s 采帧心跳（也是 JSONL 心跳频率：状态不变也照写）。
DEFAULT_INTERVAL = 20.0
#: spec §4.5：画面 + 状态不变 ≥90s 报警。
DEFAULT_STALL = 90.0
#: 默认输出目录（``debug`` 已在 .gitignore 里）。
DEFAULT_OUT = "debug/longrun"

#: 粗指纹的边长：与 #23 stall 看门狗同一把尺（64x64 灰度）。
SIGNATURE_SIZE = 64
#: 每格量化档数（16 = 4bit，步长 16 灰度）。
QUANT_LEVELS = 16

#: ★#140★ 「有动作无进展」的**动作数**阈值：连续 ≥N 次滚动/点击而业务进展指标没变 → 可报警。
#: 来历：真机第 6 轮验收是 **80 次滚动 × 6.0s/次 = 474s** 空转。取 20 次 ≈ 现场的 1/4
#: 动作量（约 120s）：足够排除「点一下等演出」的偶发动作，又能在 8 分钟空转的前 1/4 就叫。
NO_PROGRESS_ACTIONS = 20
#: ★#140★ 「有动作无进展」的**停滞秒数**阈值：业务进展指标 ≥N 秒没推进才允许报警。
#: 来历：180s = 2× 卡住阈值（:data:`DEFAULT_STALL` 90s）= 9 个 20s 心跳；比纯静止多等
#: 一倍，避免把正常的战斗长演出 / 切页加载误报成「无进展」（#23 的教训：误报比漏报更伤人）。
NO_PROGRESS_SEC = 180.0
#: ★#140★ 默认 adb 抓屏超时（秒）：必须 < :data:`DEFAULT_INTERVAL`。
#: 没有超时 = 设备卡住时第一轮永远不返回，JSONL 一直是 0 字节（现场那个窗口）。
CAPTURE_TIMEOUT_SEC = 10.0

#: JSONL 每行**必带**的字段（hooks_98/hooks_140 逐字段核对；改名=破坏契约，别改）。
REQUIRED_FIELDS = ("ts", "frame_hash", "changed", "unchanged_sec", "note")
#: ★#140★ 心跳行（``kind="heartbeat"``）额外必带的字段：状态不变也要能看见「有没有动作、业务有没有进展」。
HEARTBEAT_FIELDS = ("state", "progress_marker", "actions", "last_progress_ts")

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
# 报警判据（纯函数 —— prove-red 就换掉它们/调歪阈值）
# ---------------------------------------------------------------------------
def is_stalled(unchanged_sec: float, stall: float) -> bool:
    """画面 + 状态连续不变 ``unchanged_sec`` 秒，是否已达到报警阈值（≥）。"""
    return float(unchanged_sec) >= float(stall)


def is_action_without_progress(
    actions_since_progress: int | None,
    progress_stalled_sec: float,
    *,
    actions: int | None = None,
    seconds: float | None = None,
) -> bool:
    """「有动作但无进展」：连续动作 ≥ ``actions`` 次 **且** 业务进展 ≥ ``seconds`` 秒没推进。

    ★#140★ 两个条件必须同时成立：
    * 只看秒数：正常的战斗长演出（状态/业务指标不变但屏幕在动）会被误报；
    * 只看动作数：点得再多也不能说「业务没进展」——业务指标才是唯一真相。
    动作数取「自上次业务进展以来的动作数」，不是累计动作数。

    阈值缺省从模块真源 :data:`NO_PROGRESS_ACTIONS` / :data:`NO_PROGRESS_SEC` **运行时**读，
    不把值冻进默认参数 —— 否则改真源不改默认值，守卫钉的「阈值真源」就成了一句空话。
    """
    if actions_since_progress is None:
        return False
    try:
        count = int(actions_since_progress)
    except (TypeError, ValueError):
        return False
    need_actions = NO_PROGRESS_ACTIONS if actions is None else actions
    need_seconds = NO_PROGRESS_SEC if seconds is None else seconds
    return count >= int(need_actions) and float(progress_stalled_sec) >= float(need_seconds)


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
    """单行日志出口：控制台编码打不出 ``✗``/``★★`` 时降级成可编码字符，绝不因此炸掉监管。

    Windows 控制台默认是 GBK（cp936），``✗``（U+2717）不在里面 —— 报警行/自检错误行
    恰恰带这些符号，不能让「打印错误」本身变成新的错误。
    """
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        text = text.encode(encoding, "replace").decode(encoding, "replace")
    try:
        print(text, flush=True)
    except UnicodeEncodeError:  # pragma: no cover - 双保险：ASCII 一定打得出来
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def _call_str(fn: Callable[[], Any] | None, *, default: str = _STATE_UNKNOWN) -> str:
    """调一个取值回调并转成稳定字符串；没注入 / 读炸了都给占位串（不让监管死掉）。"""
    if fn is None:
        return default
    try:
        value = fn()
    except Exception:  # noqa: BLE001 - runner 的回调坏了也不能把监管弄死
        return _STATE_ERROR
    return default if value is None else str(value)


def _read_state(state_fn: Callable[[], Any] | None) -> str:
    """读 runner 注入的状态；没注入 / 读炸了都给一个稳定的占位串（不让监管死掉）。"""
    return _call_str(state_fn)


# ---------------------------------------------------------------------------
# 采集：默认 adb 实现（只读，只抓屏）
# ---------------------------------------------------------------------------
def screencap_cmd(serial: str, *, adb: str = DEFAULT_ADB) -> list[str]:
    """抓屏命令（纯函数，测试可以在不碰设备的前提下核对 argv）。"""
    return [str(adb), "-s", str(serial), "exec-out", "screencap", "-p"]


def adb_capture(
    serial: str,
    *,
    adb: str = DEFAULT_ADB,
    timeout: float = CAPTURE_TIMEOUT_SEC,
) -> Callable[[], bytes]:
    """默认采集：``adb exec-out screencap -p`` 拿 PNG 原始字节（只读，不发任何输入）。

    ★#140★ 必须带 ``timeout``：没有超时的 ``subprocess.run`` 会在设备不响应时无限阻塞，
    监管的第一轮永远不返回、JSONL 停在 0 字节，而且**一声不吭**。超时按「采帧失败」记账，
    循环继续走，心跳照写 —— 让「设备卡住」和「监管没启动」在日志里分得开。
    """
    cmd = screencap_cmd(serial, adb=adb)
    limit = float(timeout)

    def _capture() -> bytes:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=limit)  # noqa: S603 - 固定的只读抓屏 argv
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"adb screencap 超时（>{limit:g}s，设备没响应；记一次采帧失败，心跳继续）"
            ) from exc
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
    """一次监管跑完的账（runner 收工时打这一行就够运维看）。

    ★#140★ ``error`` 是**显式失败**：``None`` = 日志非空且写得进去；非空 = 日志为空 /
    写盘失败，runner 必须把它当错误处理（打印 / 非零退出 / 告警），不许静默通过。
    """

    serial: str
    started_ts: float
    elapsed_sec: float
    frames: int
    longest_unchanged_sec: float
    stall_count: int
    capture_failures: int
    jsonl_path: Path | None
    stop_reason: str
    actions: int | None = None
    no_progress_alarms: int = 0
    progress_marker: str | None = None
    jsonl_bytes: int = 0
    jsonl_lines: int = 0
    write_failures: int = 0
    error: str | None = None

    def as_line(self) -> str:
        actions = "未接线" if self.actions is None else f"{self.actions} 次"
        line = (
            f"[长跑监管小结] {self.serial or 'device'} 运行 {self.elapsed_sec:.1f}s / "
            f"采帧 {self.frames} 帧 / 最长静止 {self.longest_unchanged_sec:.1f}s / "
            f"卡住 {self.stall_count} 次 / 采帧失败 {self.capture_failures} 次 / "
            f"动作 {actions} / 无进展报警 {self.no_progress_alarms} 次 / "
            f"退出原因 {self.stop_reason} / 日志 {self.jsonl_path if self.jsonl_path else '（未写）'} / "
            f"落盘 {self.jsonl_lines} 行 {self.jsonl_bytes} 字节"
        )
        if self.error:
            line += f" / ✗ {self.error}"
        return line


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
    progress_fn : ★#140★ 可选，返回**业务进展指标**（页读行数 / 目标数 / 轮次）。值变化 =
        有进展，刷新 ``last_progress_ts`` 并把动作基线清零。没注入时退回 ``state_fn``
        （心跳里 ``progress_source="state"``，弱一些但总比没有强）。
    actions_fn : ★#140★ 可选，返回**单调不减**的动作计数（滚动 + 点击）。没注入时可用
        :meth:`note_action` 推；两者都没有 → 心跳里 ``actions=null``，不做「有动作无进展」报警
        （绝不拿「画面在动」冒充动作，避免误报）。
    beep : 卡住 / 有动作无进展时响铃（Windows ``winsound``，退回终端 ``\\a``）。
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
        progress_fn: Callable[[], Any] | None = None,
        actions_fn: Callable[[], Any] | None = None,
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
        for name, fn in (("state_fn", state_fn), ("progress_fn", progress_fn), ("actions_fn", actions_fn)):
            if fn is not None and not callable(fn):
                raise TypeError(f"{name} 必须可调用或 None")
        self.capture = capture
        self.interval = float(interval)
        self.stall = float(stall)
        self.out = Path(out)
        self.serial = str(serial or "")
        self.state_fn = state_fn
        self.progress_fn = progress_fn
        self.actions_fn = actions_fn
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
        # ★#140★ 双锁：一只护 JSONL 写盘，一只护动作/进展计数（runner 可从别的线程推）。
        self._write_lock = threading.RLock()
        self._feed_lock = threading.Lock()
        self.summary: Summary | None = None
        self.started_ts = 0.0
        self._fed_actions = 0
        self._fed_actions_wired = actions_fn is not None
        self._last_action_kind = ""
        self._pushed_progress: str | None = None
        self._progress_push_seq = 0
        self._reset()

    # -- 计数 / 状态复位 ---------------------------------------------------
    def _reset(self) -> None:
        self.frames = 0
        self.stall_count = 0
        self.capture_failures = 0
        self.longest_unchanged_sec = 0.0
        self.no_progress_alarms = 0
        self.write_failures = 0
        self._idx = 0
        self._prev_sig: bytes | None = None
        self._prev_state: str | None = None
        self._prev_progress: str | None = None
        self._progress_seen = False
        self._have_base = False
        self._last_frame: Any = None
        self._last_change = 0.0
        self._last_progress = 0.0
        self._actions_at_progress = 0
        self._actions_seen = False
        self._stall_open = False
        self._no_progress_open = False
        self._stop_reason = _STOP
        self._jsonl = None
        self._jsonl_path = None
        self._write_error: str | None = None

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

    @property
    def error(self) -> str | None:
        """★#140★ 显式失败（``None`` = 日志非空且写得进去）。"""
        return self.summary.error if self.summary is not None else self._write_error

    # -- 外部喂料（线程安全） ---------------------------------------------
    def note_action(self, kind: str = "action", n: int = 1) -> None:
        """★#140★ runner 每发一次滚动/点击就调一次；``n`` 允许批量。

        计数器是单调不减的累计值；``run()`` 启动时以当时的累计值为基线，所以调用方可以在
        ``start()`` 之后随时调，也可以在之前先攒（启动那一刻的存量不算本次运行的动作）。
        """
        try:
            step = int(n)
        except (TypeError, ValueError):
            step = 1
        with self._feed_lock:
            self._fed_actions = max(0, self._fed_actions + max(0, step))
            self._fed_actions_wired = True
            self._last_action_kind = str(kind)

    def note_progress(self, marker: Any = None) -> None:
        """★#140★ runner 每发生一次业务进展（读到新行 / 新目标 / 新一轮）就调一次。

        ``marker`` 给业务进展的快照（如 ``"rows:12 targets:3 round:4"``）；不给就自动生成
        一个递增序号 —— 两者都算「进展变了」，会刷新 ``last_progress_ts`` 并清零动作基线。
        """
        with self._feed_lock:
            if marker is None:
                self._progress_push_seq += 1
                marker = f"progress#{self._progress_push_seq}"
            self._pushed_progress = str(marker)

    # -- 生命周期 ----------------------------------------------------------
    def stop(self) -> None:
        """线程安全、幂等：任何线程都能调，等待中的循环会立刻醒来退出。"""
        self._stop.set()

    def run(self) -> Summary:
        """阻塞跑监管循环，退出时做**落盘自检**并打小结，返回 :class:`Summary`。"""
        if self._running:
            raise RuntimeError("同一个 LongrunMonitor 不能并发 run()（先 stop()/join()）")
        self._running = True
        self.summary = None
        try:
            self.summary = self._loop()
            return self.summary
        finally:
            self._running = False
            self._close_jsonl()
            # ★#140★ 结束自检：日志为空 = 显式错误（打印 + summary.error + CLI 非零），不许静默。
            self._audit(self.summary)

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
            self._write_error = f"循环异常退出：{exc!r}"
            self._log(f"[长跑监管] ✗ 循环异常退出：{exc!r}")

    # -- 主循环 ------------------------------------------------------------
    def _loop(self) -> Summary:
        self._reset()
        start = float(self._now())
        self.started_ts = start
        self._last_change = start
        self._last_progress = start
        self._open_jsonl(start)
        # ★#140★ 先把「监管启动」落盘：文件一建立就非空，0 字节从此只能是「没启动/写盘失败」。
        total = self._expected_rounds()
        self._write_start_line(total, start)
        # 动作基线：runner 的计数可能是进程累计值，以启动那一刻为 0 点。
        baseline = self._read_actions()
        self._actions_at_progress = 0 if baseline is None else baseline
        self._actions_seen = baseline is not None

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
        self._write_stop_line(self._idx, total, float(self._now()), elapsed)
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
            actions=self._read_actions(),
            no_progress_alarms=self.no_progress_alarms,
            progress_marker=self._prev_progress,
        )
        return self.summary

    def _expected_rounds(self) -> int | None:
        """``--duration`` 下的计划轮数（JSONL 的 ``total``，即「第 i/N 轮」的 N）。

        与 ``_loop`` 的实际轮数一致：t=0 起每 ``interval`` 一轮，到 ``duration`` 收工 ——
        所以轮数 = ceil(duration / interval)（duration=60/interval=20 → 3 轮：0/20/40）。
        """
        if self.duration is None:
            return None
        return max(1, int(math.ceil(self.duration / self.interval)))

    # -- 进展 / 动作的读取 -------------------------------------------------
    def _read_progress(self, state: str) -> tuple[str, str]:
        """返回 ``(progress_marker, source)``。

        source：``"push"``（``note_progress`` 推的）/ ``"progress_fn"``（轮询注入的回调）/
        ``"state"``（没注入进展回调，退回状态串 —— 弱，但至少能看出状态一直没变）。
        """
        with self._feed_lock:
            pushed = self._pushed_progress
            self._pushed_progress = None
        if pushed is not None:
            return pushed, "push"
        if self.progress_fn is not None:
            return _call_str(self.progress_fn), "progress_fn"
        return state, "state"

    def _read_actions(self) -> int | None:
        """动作累计数：``actions_fn`` 优先（轮询），否则用 ``note_action`` 推送值；都没接线 → None。

        两个来源**不混用**（取 max 会在「polled 已是 100、push 从 0 开始」时永远看不见增长）。
        """
        if self.actions_fn is not None:
            try:
                return int(self.actions_fn())
            except Exception:  # noqa: BLE001 - 计数回调坏了也不能把监管弄死
                return None
        with self._feed_lock:
            return self._fed_actions if self._fed_actions_wired else None

    # -- 一轮 --------------------------------------------------------------
    def _round(self, idx: int, total: int | None, now: float) -> None:
        state = _read_state(self.state_fn)
        sig: bytes | None = None
        note = ""
        try:
            frame = self.capture()
        except Exception as exc:  # noqa: BLE001 - 一次 adb 抖动/超时不许让监管整体死掉
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

        # ★#140★ 进展与动作在采集**之后**读：这一轮刚读到的行/刚发出的滚动都算进本行心跳。
        progress_marker, progress_source = self._read_progress(state)
        actions = self._read_actions()
        if actions is not None and not self._actions_seen:
            # 动作计数中途才接线：从接线那一刻开始算，别把接线前的存量算成本次运行的动作。
            self._actions_at_progress = actions
            self._actions_seen = True
        progress_changed = progress_marker != self._prev_progress
        if progress_changed:
            self._prev_progress = progress_marker
            self._last_progress = now
            # 首次观察只建立进展基线；动作基线保持「启动那一刻」的值，
            # 这样「启动后一直没进展」也能按从启动起的动作数判断（现场形态）。
            if actions is not None and self._progress_seen:
                self._actions_at_progress = actions
            self._progress_seen = True
            self._no_progress_open = False

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

        notes = [note] if note else []
        png: Path | None = None
        if is_stalled(unchanged, self.stall):
            if not self._stall_open:
                self._stall_open = True
                self.stall_count += 1
                png = self._dump_stall_frame(now)
                self._print_alarm(unchanged, png)
                self._beep_once()
                notes.append(
                    f"★★ 卡住 {unchanged:.1f}s ★★"
                    + (f"（帧已落盘 {png.name}）" if png else "（无帧可落：还没抓到过任何一帧）")
                )
            else:
                notes.append(f"仍卡住 {unchanged:.1f}s（已报警，不重复落盘）")

        actions_since_progress = 0 if actions is None else max(0, actions - self._actions_at_progress)
        progress_stalled = max(0.0, now - self._last_progress)
        if self._fed_actions_wired or self.actions_fn is not None:
            if is_action_without_progress(actions_since_progress, progress_stalled):
                if not self._no_progress_open:
                    self._no_progress_open = True
                    self.no_progress_alarms += 1
                    message = (
                        f"★★ 有动作无进展：{actions_since_progress} 次动作 / "
                        f"业务进展 {progress_stalled:.1f}s 未推进 ★★"
                    )
                    notes.append(message)
                    self._log(f"{message}  状态 {state!r}")
                    self._beep_once()
                else:
                    notes.append(
                        f"仍无进展：{actions_since_progress} 次动作 / {progress_stalled:.1f}s"
                        f"（已报警，不重复）"
                    )

        self._write_line(
            idx,
            total,
            now,
            sig,
            changed,
            unchanged,
            state,
            "；".join(notes),
            png,
            progress_marker=progress_marker,
            progress_source=progress_source,
            progress_changed=progress_changed,
            actions=actions,
            actions_since_progress=actions_since_progress,
            progress_stalled=progress_stalled,
        )

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
        """建/打开日志。失败不抛：记 ``_write_error``，报警退回控制台，收工自检报错。"""
        path = self.out / f"{_slug(self.serial)}-{_stamp(start)}.jsonl"
        self._jsonl_path = path
        try:
            self.out.mkdir(parents=True, exist_ok=True)
            self._jsonl = open(path, "a", encoding="utf-8")  # noqa: SIM115 - 生命周期与 run() 绑定
        except Exception as exc:  # noqa: BLE001
            self._jsonl = None
            self._write_error = f"打开日志失败（{path}）：{type(exc).__name__}: {exc}"
            self._log(f"[长跑监管] ✗ {self._write_error}（报警只打控制台）")

    def _close_jsonl(self) -> None:
        handle, self._jsonl = self._jsonl, None
        if handle is not None:
            try:
                handle.close()
            except Exception as exc:  # noqa: BLE001
                self.write_failures += 1
                if self._write_error is None:
                    self._write_error = f"关闭日志失败：{type(exc).__name__}: {exc}"

    def _write_record(self, payload: dict) -> bool:
        """写一行并 flush（运维 ``Get-Content -Wait`` 才跟得上），失败只记账不掐死循环。"""
        with self._write_lock:
            handle = self._jsonl
            if handle is None and self._write_error is None:
                self._open_jsonl(float(payload.get("ts_epoch") or self._now()))
                handle = self._jsonl
            if handle is None:
                return False
            try:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                handle.flush()  # 每行刷盘：崩了也不丢，0 字节 = 真的没写出来
                return True
            except Exception as exc:  # noqa: BLE001 - 盘满/句柄坏：记账，别让监管整个死掉
                self.write_failures += 1
                if self._write_error is None:
                    self._write_error = f"写盘失败（{self._jsonl_path}）：{type(exc).__name__}: {exc}"
                    self._log(f"[长跑监管] ✗ {self._write_error}")
                return False

    def _write_start_line(self, total: int | None, now: float) -> bool:
        """★#140★ 文件一建立就写：它让「0 字节」只可能是没启动/写盘失败。"""
        return self._write_record(
            {
                "ts": _iso(now),
                "frame_hash": None,
                "changed": False,
                "unchanged_sec": 0.0,
                "note": (
                    f"监管启动：JSONL 已建立（此后每 {self.interval:g}s 一行心跳；"
                    f"文件停在 0 字节 = 监管没启动 / 写盘失败）"
                ),
                "ts_epoch": round(float(now), 3),
                "idx": 0,
                "total": total,
                "state": _STATE_UNKNOWN,
                "kind": "start",
                "frame_png": None,
                "progress_marker": None,
                "progress_source": "start",
                "progress_changed": False,
                "actions": None,
                "actions_since_progress": 0,
                "progress_stalled_sec": 0.0,
                "last_progress_ts": _iso(now),
                "last_progress_epoch": round(float(now), 3),
            }
        )

    def _write_stop_line(self, idx: int, total: int | None, now: float, elapsed: float) -> bool:
        """★#140★ 收工行：跑 0 轮也有 start+stop 两行，空文件不再有合法解释。"""
        actions = self._read_actions()
        unchanged = max(0.0, now - self._last_change)
        return self._write_record(
            {
                "ts": _iso(now),
                "frame_hash": None,
                "changed": False,
                "unchanged_sec": round(unchanged, 1),
                "note": (
                    f"监管收工（{self._stop_reason}）：{idx} 轮 / {elapsed:.1f}s / "
                    f"动作 {('未接线' if actions is None else actions)} / "
                    f"卡住 {self.stall_count} 次 / 无进展报警 {self.no_progress_alarms} 次"
                ),
                "ts_epoch": round(float(now), 3),
                "idx": idx,
                "total": total,
                "state": self._prev_state or _STATE_UNKNOWN,
                "kind": "stop",
                "frame_png": None,
                "progress_marker": self._prev_progress,
                "progress_source": "stop",
                "progress_changed": False,
                "actions": actions,
                "actions_since_progress": (
                    0 if actions is None else max(0, actions - self._actions_at_progress)
                ),
                "progress_stalled_sec": round(max(0.0, now - self._last_progress), 1),
                "last_progress_ts": _iso(self._last_progress),
                "last_progress_epoch": round(float(self._last_progress), 3),
            }
        )

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
        *,
        progress_marker: str | None = None,
        progress_source: str = "state",
        progress_changed: bool = False,
        actions: int | None = None,
        actions_since_progress: int = 0,
        progress_stalled: float = 0.0,
    ) -> bool:
        return self._write_record(
            {
                "ts": _iso(now),
                "frame_hash": signature_digest(sig) if sig is not None else None,
                "changed": bool(changed),
                "unchanged_sec": round(float(unchanged), 1),
                "note": note,
                "ts_epoch": round(float(now), 3),
                "idx": idx,
                "total": total,
                "state": state,
                "kind": "heartbeat",
                "frame_png": str(png) if png is not None else None,
                # ★#140★ 状态不变也要能看见「有没有动作、业务有没有进展」。
                "progress_marker": progress_marker,
                "progress_source": progress_source,
                "progress_changed": bool(progress_changed),
                "actions": actions,
                "actions_since_progress": int(actions_since_progress),
                "progress_stalled_sec": round(float(progress_stalled), 1),
                "last_progress_ts": _iso(self._last_progress),
                "last_progress_epoch": round(float(self._last_progress), 3),
            }
        )

    def _audit(self, summary: Summary | None) -> None:
        """★#140★ 结束自检：数行 / 数字节，日志为空或写不进去 → 显式错误（打印 + 返回）。"""
        path = self._jsonl_path
        size = 0
        lines = 0
        if path is not None:
            try:
                size = int(path.stat().st_size)
                with open(path, "r", encoding="utf-8", errors="replace") as handle:  # noqa: SIM115
                    lines = sum(1 for line in handle if line.strip())
            except OSError:
                size, lines = 0, 0

        error = self._write_error
        if error is None and self.write_failures:
            error = f"JSONL 有 {self.write_failures} 次写盘失败（日志可能不完整）：{path}"
        if error is None and (path is None or size <= 0 or lines <= 0):
            error = (
                f"JSONL 为空（{size} 字节）：{path if path else '（没有路径）'} —— "
                f"监管没有写出任何一行（启动失败 / 写盘失败 / 没喂到数据）"
            )

        if summary is not None:
            summary.jsonl_bytes = size
            summary.jsonl_lines = lines
            summary.write_failures = self.write_failures
            if summary.error is None:
                summary.error = error

        if error:
            self._log(f"[长跑监管] ✗ {error}")
        if summary is not None:
            self._log(summary.as_line())


# ---------------------------------------------------------------------------
# 给 runner 的一行式入口
# ---------------------------------------------------------------------------
def monitor_for_serial(
    serial: str,
    *,
    adb: str = DEFAULT_ADB,
    capture_timeout: float = CAPTURE_TIMEOUT_SEC,
    **kwargs: Any,
) -> LongrunMonitor:
    """按串号建默认 adb 采集的监管（runner 集成入口，见模块 docstring）。"""
    if float(capture_timeout) <= 0:
        raise ValueError(f"capture_timeout 必须 > 0（给的 {capture_timeout!r}）")
    return LongrunMonitor(
        adb_capture(serial, adb=adb, timeout=capture_timeout),
        serial=serial,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _state_file_feed(
    path: str | os.PathLike | None,
) -> tuple[Callable[[], Any], Callable[[], Any], Callable[[], Any]] | None:
    """``--state-file``：一行文本 / 一行 JSON 都行（★#140★ JSON 可带进度与动作）。

    兼容两种写法：

    * 纯文本：首行就是 state（#98 的老协议）；
    * JSON 对象：``{"state": "...", "progress": "...", "actions": 123}`` ——
      ``progress`` 是业务进展指标，``actions`` 是单调不减的滚动/点击计数。
      缺字段就退回可用项（``progress`` 缺省用 ``state``，``actions`` 缺省 None）。
    """
    if not path:
        return None
    target = Path(path)
    missing = f"<state-file-missing:{target.name}>"

    def _payload() -> dict:
        try:
            text = target.read_text(encoding="utf-8").strip()
        except OSError:
            return {"state": missing}
        if not text:
            return {"state": _STATE_UNKNOWN}
        first = text.splitlines()[0]
        try:
            obj = json.loads(first)
        except (TypeError, ValueError):
            return {"state": first}
        return obj if isinstance(obj, dict) else {"state": first}

    def _state() -> Any:
        return _payload().get("state")

    def _progress() -> Any:
        payload = _payload()
        return payload.get("progress", payload.get("state"))

    def _actions() -> Any:
        value = _payload().get("actions")
        if value is None:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None

    return _state, _progress, _actions


def _file_state_reader(path: str | os.PathLike | None) -> Callable[[], str] | None:
    """``--state-file`` 的老入口：只取 state（实现与 :func:`_state_file_feed` 同一份）。"""
    feed = _state_file_feed(path)
    return None if feed is None else feed[0]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="longrun_monitor.py",
        description=(
            "#98/#140 长跑监管：20s 心跳 / 90s 卡住报警 / 有动作无进展报警 / 证据落盘"
            "（只读抓帧，不点屏幕）"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--serial", default=DEFAULT_SERIAL, help="设备串号，如 127.0.0.1:16384（也可用 WF_LIVE_ADDRESS）")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="采帧/心跳间隔（秒）")
    ap.add_argument("--stall", type=float, default=DEFAULT_STALL, help="画面+状态不变的报警阈值（秒）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="JSONL 与卡住帧的输出目录")
    ap.add_argument("--duration", type=float, default=None, help="跑多少秒自动退出（缺省=一直跑到 Ctrl-C）")
    ap.add_argument("--beep", action="store_true", help="卡住 / 有动作无进展时响铃（Windows winsound，退回终端 \\a）")
    ap.add_argument("--adb", default=DEFAULT_ADB, help="adb 可执行文件（也可用 WF_LIVE_ADB）")
    ap.add_argument(
        "--capture-timeout",
        type=float,
        default=CAPTURE_TIMEOUT_SEC,
        help="单次 adb 抓屏超时（秒）；超时只记一次采帧失败，不许把心跳饿死",
    )
    ap.add_argument(
        "--state-file",
        default=None,
        help='可选：读这个文件的首行当 state；一行 JSON 时支持 {"state","progress","actions"}',
    )
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
    if args.capture_timeout <= 0:
        ap.error(f"--capture-timeout 必须 > 0（给的 {args.capture_timeout}）")

    feed = _state_file_feed(args.state_file)
    state_fn, progress_fn, actions_fn = (None, None, None) if feed is None else feed
    monitor = monitor_for_serial(
        args.serial,
        adb=args.adb,
        capture_timeout=args.capture_timeout,
        interval=args.interval,
        stall=args.stall,
        out=args.out,
        state_fn=state_fn,
        progress_fn=progress_fn,
        actions_fn=actions_fn,
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
        summary = monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
        print("\n[长跑监管] Ctrl-C：已停", flush=True)
        return 130
    # ★#140★ 结束自检失败 = 非零退出，不许静默通过。
    if summary is not None and summary.error:
        _print_line(f"[长跑监管] ✗ 收工自检失败：{summary.error}")
        return 2
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
