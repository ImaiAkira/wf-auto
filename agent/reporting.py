# -*- coding: utf-8 -*-
"""用户可见输出 / 机制日志 / 进度行 —— agent 侧**唯一**出口。

背景（为什么不是各场景各写一套）
--------------------------------
#86 只给五重开了「``_say``（用户可见）/ ``_log``（机制）」两路；其余场景
（深渊连战 / 深渊连战EX / 幻想连战 / 领主战 / 外传）的机制日志与进度混在同一个
stdout 里 → MFAAvalonia 面板被点击 / 校验 / 心跳刷满，用户看不到「打到哪了」。

本模块把三件事分开，并且**只在这里实现一次**：

    say(text)        用户可见 —— 永远进 GUI 面板（进程真实 stdout）
    log(text)        机制日志 —— quiet 时只落盘；非 quiet 时也进 stdout（守卫 / runner 取证）
    Progress(...)    进度行 —— 只走 say；同一步只出一条（GUI 不刷屏）

quiet 的做法是**一次**把 ``sys.stdout`` 换成落盘 sink：场景文件里既有的
``print(...)`` 全部自动归入机制日志，**不需要逐行改成 log(...)**。这是把 #86
从五重推广到全场景的最小改动，也是「只有一处会漏」的原因。

进度行的形状只有一个真源 :func:`format_progress`
-----------------------------------------------

    [进度] 深渊连战EX 12/30 战
    [进度] 幻想连战 4/15 关（第 1/2 套）
    [进度] 五重决战 已 2 次                 ← total=0（总量未知）时
    [进度] 五重决战 收工：已打够 2 次（打几次=2）

调用方约定：**场景只负责「什么时候算一步」与「一共几步」**；格式、去重、静音
都由本模块管。★不要在场景里自己拼 ``[进度]`` 字符串★（一拼就有第二份格式）。

失败语义（本仓既有纪律）
------------------------
* ``say`` / ``log`` / ``Progress`` **绝不抛异常**：日志坏了不许影响跑图。
* quiet 打开时如果日志文件打不开，**不静音**（宁可面板吵，也不许把日志丢掉），
  并用一行 ``[reporting]`` 说明原因。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, TextIO

#: 日志文件名（相对「agent 包所在目录的上一级」= 项目根 / install 根），与
#: :mod:`progress` 的落盘口径一致：**不依赖进程 CWD**（MFAAvalonia 决定 CWD）。
DEFAULT_LOG_RELATIVE = Path("debug") / "agent.log"

#: 环境变量覆盖（测试 / 调试用）。
ENV_LOG_PATH = "MAA_AGENT_LOG"

#: 日志有界：超过这个大小就清空重来（真机长跑 + save_draw 的教训，8MB 够用）。
MAX_LOG_BYTES = 8 * 1024 * 1024

#: ``say()`` 真正写的地方。导入时抓一次，之后 quiet 改的只是 ``sys.stdout``。
_REAL_STDOUT: TextIO = sys.stdout
#: 打开 quiet 之前的 ``sys.stdout``（用来精确还原，而不是还原成 ``_REAL_STDOUT``）。
_SAVED_STDOUT: Optional[TextIO] = None
_QUIET = False
_LOG_FILE: Optional[TextIO] = None
_LOG_PATH: Optional[Path] = None


class _Sink:
    """把 ``sys.stdout`` 写进日志文件。写失败**静默**（绝不影响主流程）。"""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, handle: TextIO) -> None:
        self._handle = handle

    def write(self, data):  # noqa: ANN001, ANN201
        try:
            self._handle.write(data)
            self._handle.flush()
        except Exception:  # noqa: BLE001
            pass
        return len(data) if isinstance(data, str) else 0

    def flush(self) -> None:
        try:
            self._handle.flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def reconfigure(self, **kwargs) -> None:  # noqa: ANN003
        return None

    def fileno(self) -> int:
        return self._handle.fileno()


# ---------------------------------------------------------------------------
# quiet：一次重定向 sys.stdout
# ---------------------------------------------------------------------------
def is_quiet() -> bool:
    return _QUIET


def log_path() -> Optional[Path]:
    return _LOG_PATH


def _default_log_path() -> Path:
    import os

    env = os.environ.get(ENV_LOG_PATH)
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / DEFAULT_LOG_RELATIVE


def _open_log(path: Path) -> Optional[TextIO]:
    """打开日志文件；失败返回 None（调用方据此决定要不要静音）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.write_text("", encoding="utf-8")          # 有界：超限清空重来
        return open(path, "a", encoding="utf-8", errors="replace")
    except OSError as exc:  # noqa: BLE001
        say(f"[reporting] 日志打不开（{path}）：{exc} —— 不静音，机制日志继续进面板")
        return None


def set_quiet(on: bool = True, path: Optional[Path | str] = None) -> bool:
    """打开 / 关闭 quiet。返回**实际生效**的状态。

    * ``on=True``：把 ``sys.stdout`` 换成落盘 sink。日志打不开时**不静音**
      （返回 False），否则用户面板会「安静得像死了」。
    * ``on=False``：还原 ``sys.stdout`` 并关闭文件。
    * 重复调用幂等。
    """
    global _QUIET, _LOG_FILE, _LOG_PATH, _SAVED_STDOUT
    want = bool(on)
    if want and _QUIET:
        return True
    if not want:
        if _QUIET:
            _QUIET = False
            if _SAVED_STDOUT is not None:
                sys.stdout = _SAVED_STDOUT
                _SAVED_STDOUT = None
            if _LOG_FILE is not None:
                try:
                    _LOG_FILE.close()
                except Exception:  # noqa: BLE001
                    pass
                _LOG_FILE = None
        return False

    target = Path(path) if path is not None else _default_log_path()
    handle = _open_log(target)
    if handle is None:
        return False
    _LOG_PATH = target
    _LOG_FILE = handle
    _SAVED_STDOUT = sys.stdout
    sys.stdout = _Sink(handle)
    _QUIET = True
    return True


# ---------------------------------------------------------------------------
# 三个出口
# ---------------------------------------------------------------------------
def say(text: str = "") -> None:
    """★用户可见★：永远进 GUI 面板（进程真实 stdout），与 quiet 无关。"""
    try:
        print(text, file=_REAL_STDOUT, flush=True)
    except Exception:  # noqa: BLE001
        pass


def log(text: str = "") -> None:
    """机制日志：quiet 时只落盘；非 quiet 时也进 stdout（守卫 / runner 取证）。"""
    line = str(text)
    if _QUIET:
        if _LOG_FILE is not None:
            try:
                _LOG_FILE.write(line + "\n")
                _LOG_FILE.flush()
            except Exception:  # noqa: BLE001
                pass
        return
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 进度行：格式唯一真源
# ---------------------------------------------------------------------------
def format_progress(
    display: str,
    index: int = 0,
    total: int = 0,
    unit: str = "",
    note: str = "",
) -> str:
    """拼一行进度。**唯一的格式实现**；场景/测试都不许自己拼 ``[进度]``。"""
    name = (display or "").strip() or "任务"
    u = (unit or "").strip()
    try:
        i = max(0, int(index))
    except (TypeError, ValueError):
        i = 0
    try:
        n = max(0, int(total))
    except (TypeError, ValueError):
        n = 0
    unit_part = f" {u}" if u else ""
    if n > 0:
        head = f"[进度] {name} {i}/{n}{unit_part}"
    else:
        head = f"[进度] {name} 已 {i}{unit_part}"
    suffix = (note or "").strip()
    return f"{head}（{suffix}）" if suffix else head


class Progress:
    """一条进度线：``start`` 一次、``step`` 若干次、``done`` 一次。

    * ``total > 0`` → ``i/N``；``total == 0`` → ``已 i``（总量未知/无固定上限）。
    * ``step`` **单调且去重**：同一步重复报只出一条，倒退直接忽略
      （GUI 面板不刷屏，也不会把 12 层报成 11 层）。
    * ``done`` 之后不再出任何 step（收工了就不该再报进度）。
    * 每一步都过 :func:`format_progress`，所以格式只有一份。
    """

    def __init__(self, display: str, total: int = 0, unit: str = "", note: str = "") -> None:
        self.display = display
        self.total = _as_int(total, 0)
        self.unit = unit or ""
        self.note = note or ""
        self._last = 0
        self._done = False
        self._started = False
        self._reason = ""
        self._lines: list[str] = []

    # -- 查询（守卫 / 场景自检用） -----------------------------------------
    @property
    def count(self) -> int:
        return self._last

    @property
    def done_reason(self) -> str:
        return self._reason

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    # -- 输出 ---------------------------------------------------------------
    def start(self, total: Optional[int] = None) -> str:
        if total is not None:
            self.total = _as_int(total, 0)
        if self._started or self._done:
            return ""
        self._started = True
        unit_part = f" {self.unit}" if self.unit else ""
        if self.total > 0:
            text = f"[进度] {self.display} 开始（共 {self.total}{unit_part}）"
        else:
            text = f"[进度] {self.display} 开始"
        return self._emit(text)

    def step(self, index: Optional[int] = None, note: Optional[str] = None) -> str:
        if self._done:
            return ""
        if index is None:
            n = self._last + 1
        else:
            n = _as_int(index, self._last + 1)
        if n <= self._last or n <= 0:
            return ""
        self._last = n
        text = format_progress(
            self.display,
            n,
            self.total,
            self.unit,
            self.note if note is None else note,
        )
        return self._emit(text)

    def done(self, reason: str = "") -> str:
        if self._done:
            return ""
        self._done = True
        self._reason = str(reason or "").strip()
        text = f"[进度] {self.display} 收工" + (f"：{self._reason}" if self._reason else "")
        return self._emit(text)

    def _emit(self, text: str) -> str:
        self._lines.append(text)
        say(text)
        return text


def _as_int(value, default: int = 0) -> int:  # noqa: ANN001
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


__all__ = [
    "DEFAULT_LOG_RELATIVE",
    "ENV_LOG_PATH",
    "MAX_LOG_BYTES",
    "Progress",
    "format_progress",
    "is_quiet",
    "log",
    "log_path",
    "say",
    "set_quiet",
]
