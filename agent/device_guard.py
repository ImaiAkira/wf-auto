# -*- coding: utf-8 -*-
"""设备身份闸门：任务开跑前核对「执行器实际连的设备」是不是本实例这一次要用的那台。

背景（2026-10-21 03:04 真机实证）
--------------------------------
配置 2 指定 ``127.0.0.1:16448``（448），「自动刷深渊」整场却跑在 ``127.0.0.1:16385``（385）上：

* ``maafw.log`` 里 16448 的控制器**一条 screencap / 输入事件都没有**（出现 0 次），
  158 条控制器动作事件全是 16385；
* 两个任务器的 OCR 帧逐字符相同（结算页的 ``00:21.93`` / ``99,999,999,999`` 都一样，
  相差 120~500ms）——它们看的是同一块屏幕；
* 成因在壳：刷新 / 切设备会**异步**重建控制器，而任务队列在切换落地前就抓了旧的
  执行器，之后一直沿用。

★本模块只保证一件事★：**绝不允许在错误的设备上静默开跑**。

* 开跑前核对一次（每个 ``task_id`` 一次）：不符 → 面板报原因 + ``tasker.post_stop()``；
* 核对不了（拿不到任何一侧）→ 只记日志、**不误停**（fail-open）；
* 命中（一致）→ 记一行机制日志，面板不加噪声。

「这次该用哪台」从哪来
----------------------
**首选 GUI 自己的启动记录**：``logs/log-YYYYMMDD.log`` 里本实例最近一条

    [inst=配置 2/b57463f7] ... 用户操作：启动任务 | controller=Adb, ... device=...（127.0.0.1:16448)

这条是**用户这一次点开始时界面上真正选中的设备**，没有延迟、不会拿到旧值。
为什么不用 ``config/instances/<id>.json`` 的 ``AdbDevice.AdbSerial``：那是**持久化**
的保存值，切设备之后可能还没落盘（真机 03:04:27 的文件内容仍是 16448，而界面此刻
已经切到 16385）—— 拿它当判据会把**正常的**切设备误杀。配置文件只作**兜底**（离线
harness / 没有 GUI 日志时）。

为什么不放进场景
----------------
这是**跨场景**的会话级不变量（深渊 / 幻想 / 五重 / 领主战 / 抽卡都会中）。放进任何
一个场景就是再抄 N 份 —— 与 ADR 0005 / #119 要消灭的「三份漂移」同理。

为什么不依赖 GUI 改代码
----------------------
壳（MFAAvalonia）是预编译的第三方二进制，改不了它的调度；但它把每个任务都交给
MaaFramework 的 tasker，而 ``tasker.controller`` 能说出**实际**连的 adb 序列号。
本闸门就钉在这两个唯一可信的事实上：**用户这次点的是哪台**（GUI 日志）与
**执行器实际是哪台**（控制器 info）。
"""

from __future__ import annotations

import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import reporting

#: 本项目根的上一级约定与 :mod:`progress` / :mod:`reporting` 一致：
#: agent 包所在目录的**上一级** = 项目根（``config/`` ``logs/`` 与 ``agent/`` 同级）。
DEFAULT_ROOT = Path(__file__).resolve().parent.parent

#: 实例配置目录（相对项目根）。
INSTANCES_RELATIVE = Path("config") / "instances"

#: GUI 日志目录 + 文件名前缀（MFAAvalonia：``logs/log-YYYYMMDD.log``）。
GUI_LOG_RELATIVE = Path("logs")
GUI_LOG_PREFIX = "log-"

#: 只看 GUI 日志尾部这么多字节（真机单日几十 MB，任务在跑时只有尾部有关）。
GUI_LOG_TAIL = 256 * 1024

#: device 标签形如 ``...（127.0.0.1:16448)``（壳用的是全角括号）。
_SERIAL_RE = re.compile(r"[（(]([0-9A-Za-z_.\-]+:\d+)[）)]")

_LOCK = threading.Lock()
#: 已经核对过的 task_id（同一个任务只核对一次，不刷屏、不重复停）。
_CHECKED: set[int] = set()
#: 上一次的降级原因（只记一次，避免每帧一行）。
_WARNED: set[str] = set()

_INSTANCE_ID = ""
_INSTANCE_NAME = ""
_ROOT: Path = DEFAULT_ROOT


# ---------------------------------------------------------------------------
# 配置：本实例「这一次」该用哪台
# ---------------------------------------------------------------------------
def configure(
    argv: Optional[Iterable[str]] = None,
    root: Optional[Path | str] = None,
) -> None:
    """从 argv 里认出本实例（``instance_id=`` / ``instance_name=``），并记住项目根。

    ★不依赖 argv 顺序★：壳传参的先后在版本之间变过，这里按前缀扫描，
    与 ``main.py`` 里「取最后一个参数当 socket_id」的旧写法互不影响。
    """
    global _INSTANCE_ID, _INSTANCE_NAME, _ROOT
    if root is not None:
        _ROOT = Path(root)
    for arg in list(argv or []):
        if not isinstance(arg, str):
            continue
        if arg.startswith("instance_id="):
            _INSTANCE_ID = arg.split("=", 1)[1].strip()
        elif arg.startswith("instance_name="):
            _INSTANCE_NAME = arg.split("=", 1)[1].strip()


def instance_id() -> str:
    return _INSTANCE_ID


def _today_gui_log(base: Path) -> Path:
    return base / GUI_LOG_RELATIVE / f"{GUI_LOG_PREFIX}{datetime.now():%Y%m%d}.log"


def _tail_text(path: Path, limit: int = GUI_LOG_TAIL) -> str:
    try:
        with path.open("rb") as fh:
            try:
                fh.seek(-limit, io.SEEK_END)
            except OSError:
                fh.seek(0)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _expected_from_gui_log(base: Path, want_id: str, want_name: str) -> str:
    """从 GUI 日志里找本实例**最近一次**「启动任务」选的设备序列号。"""
    if not want_id and not want_name:
        return ""
    text = _tail_text(_today_gui_log(base))
    if not text:
        return ""
    serial = ""
    for line in text.splitlines():
        if "启动任务" not in line or "device=" not in line:
            continue
        tagged = (want_id and f"/{want_id}]" in line) or (want_name and f"inst={want_name}/" in line)
        if not tagged:
            continue
        match = _SERIAL_RE.search(line)
        if match:
            serial = match.group(1).strip()
    return serial


def _expected_from_config(base: Path, want_id: str, want_name: str) -> str:
    """兜底：实例配置里的 ``AdbDevice.AdbSerial``（持久化值，可能滞后）。"""
    directory = base / INSTANCES_RELATIVE
    candidates: list[Path] = []
    if want_id:
        exact = directory / f"{want_id}.json"
        if exact.is_file():
            candidates.append(exact)
    if not candidates:
        try:
            candidates = sorted(directory.glob("*.json"))
        except OSError:
            return ""

    for path in candidates:
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if not want_id and want_name:
            if str(data.get("InstanceName") or "").strip() != want_name:
                continue
        device = data.get("AdbDevice")
        if isinstance(device, dict):
            serial = str(device.get("AdbSerial") or "").strip()
            if serial:
                return serial
    return ""


def expected_source(
    root: Optional[Path | str] = None,
    instance_id_: Optional[str] = None,
) -> tuple[str, str]:
    """返回 ``(serial, 来源)``；来源 ∈ ``gui-log`` / ``config`` / ``""``。"""
    base = Path(root) if root is not None else _ROOT
    want_id = (_INSTANCE_ID if instance_id_ is None else instance_id_).strip()
    want_name = _INSTANCE_NAME.strip()

    serial = _expected_from_gui_log(base, want_id, want_name)
    if serial:
        return serial, "gui-log"

    serial = _expected_from_config(base, want_id, want_name)
    if serial:
        return serial, "config"
    return "", ""


def expected_serial(
    root: Optional[Path | str] = None,
    instance_id_: Optional[str] = None,
) -> str:
    return expected_source(root, instance_id_)[0]


# ---------------------------------------------------------------------------
# 运行时：执行器「实际」是哪台
# ---------------------------------------------------------------------------
def actual_serial(tasker: Any) -> str:
    """问 MaaFramework：这个 tasker 绑的控制器实际连哪个 adb 序列号。

    兼容三种形态：``info`` 是属性 / 是方法 / 整个对象拿不到。
    """
    try:
        controller = getattr(tasker, "controller", None)
        if controller is None:
            return ""
        info = getattr(controller, "info", None)
        if callable(info):
            info = info()
        if not isinstance(info, dict):
            return ""
        return str(info.get("adb_serial") or "").strip()
    except Exception:  # noqa: BLE001 —— 询问失败绝不能影响跑图
        return ""


# ---------------------------------------------------------------------------
# 闸门
# ---------------------------------------------------------------------------
def check(tasker: Any, task_id: Optional[int] = None) -> bool:
    """核对设备身份。返回 True = 放行；False = 已请求停止。

    每个 ``task_id`` 只核对一次。判据只有一条：**这一次要用的 serial == 控制器 info 的
    adb_serial**。任一方拿不到就降级为只记日志（fail-open），绝不误停正常任务。
    """
    if task_id is not None:
        with _LOCK:
            if task_id in _CHECKED:
                return True
            _CHECKED.add(task_id)

    want, source = expected_source()
    got = actual_serial(tasker)

    if not want:
        _log_once(
            "no-config",
            "[设备] 无法核对：找不到本实例这一次的设备（GUI 日志 / 实例配置都没有），跳过设备身份校验",
        )
        return True
    if not got:
        _log_once(
            "no-info",
            "[设备] 无法核对：控制器信息里没有 adb_serial，跳过设备身份校验",
        )
        return True

    if got == want:
        reporting.log(f"[设备] ✅ 执行器={got}（来源 {source}，与本实例一致）")
        return True

    reporting.say(f"[设备] ✗ 本次要用的设备是 {want}（{source}），但执行器实际接的是 {got} —— 任务已停止")
    reporting.say(
        "[设备] 原因：刷新/切设备后队列仍挂在上一台（控制器切换没落地）；"
        "请重新连接设备（或重启程序）后再启动"
    )
    reporting.log(f"[设备] 阻断：expected={want}({source}) actual={got} task_id={task_id}")
    _stop(tasker)
    return False


def _stop(tasker: Any) -> None:
    try:
        post_stop = getattr(tasker, "post_stop", None)
        if callable(post_stop):
            post_stop()
    except Exception:  # noqa: BLE001 —— 停不下来也不能抛，交给壳兜底
        pass


def _log_once(key: str, line: str) -> None:
    with _LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    reporting.log(line)


# ---------------------------------------------------------------------------
# 接线：MaaFramework 的 tasker 事件（任务开跑时响一次）
# ---------------------------------------------------------------------------
def install(
    argv: Optional[Iterable[str]] = None,
    root: Optional[Path | str] = None,
) -> bool:
    """把闸门挂到 AgentServer 的 tasker 事件上。返回是否挂上。

    ★必须在 ``AgentServer.start_up(...)`` 之后调用★（sink 要注册到已启动的服务）。
    """
    try:
        from maa.agent.agent_server import AgentServer
        from maa.event_sink import NotificationType
        from maa.tasker import TaskerEventSink
    except Exception:  # noqa: BLE001 —— 离线（无 maa.agent）时本模块仍可被 import
        return False

    configure(argv, root)

    class _DeviceGuardSink(TaskerEventSink):
        def on_tasker_task(self, tasker, noti_type, detail):  # noqa: ANN001
            if noti_type != NotificationType.Starting:
                return
            try:
                check(tasker, getattr(detail, "task_id", None))
            except Exception:  # noqa: BLE001 —— 事件里绝不抛
                pass

    try:
        AgentServer.add_tasker_sink(_DeviceGuardSink())
    except Exception:  # noqa: BLE001
        reporting.log("[设备] 身份闸门未挂载：add_tasker_sink 失败（本次不做设备校验）")
        return False

    serial, source = expected_source()
    reporting.log(
        f"[设备] 身份闸门已挂载：instance_id={_INSTANCE_ID or '?'} "
        f"expected={serial or '?'}（{source or '未取到'}）"
    )
    return True


def reset() -> None:
    """清空会话状态（离线测试用）。"""
    global _INSTANCE_ID, _INSTANCE_NAME, _ROOT
    with _LOCK:
        _CHECKED.clear()
        _WARNED.clear()
    _INSTANCE_ID = ""
    _INSTANCE_NAME = ""
    _ROOT = DEFAULT_ROOT
