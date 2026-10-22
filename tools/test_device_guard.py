# -*- coding: utf-8 -*-
"""设备身份闸门（agent/device_guard.py）—— 离线单测，零设备。

    .venv\\Scripts\\python.exe tools\\test_device_guard.py

背景见 ``agent/device_guard.py`` 的模块注释：2026-10-21 03:04 真机，配置 2 指定
448（127.0.0.1:16448），任务整场跑在 385（127.0.0.1:16385）上。本文件钉住闸门的
**唯一判据**与**两条失败路径**：

  1. **一致 → 放行**：``实例配置.AdbDevice.AdbSerial == 控制器 info.adb_serial``；
  2. **不一致 → 阻断**：面板两行（带两边的 serial + 原因）、``tasker.post_stop()`` 正好一次；
  3. **核对不了 → 只记日志、不误停**（fail-open）：没有实例配置 / 控制器 info 里没有
     ``adb_serial`` / 询问抛异常 —— 三种都必须是 True 且**不 stop**；
  4. **每个 task_id 只核对一次**：同一任务重复触发不重复停，换 task_id 才重新核对；
  5. **配置来源**：``instance_id`` 精确文件名优先；拿不到 id 时按 ``InstanceName`` 回退；
  6. **argv 顺序无关**：壳传参的先后变过，``instance_id=`` / ``instance_name=`` 按前缀扫描。

★为什么 fail-open 是硬要求★：闸门拿不到一侧的信息时停任务，等于把「偶尔能跑」变成
「永远跑不了」；宁可少拦一次，也不能误杀正常任务。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import device_guard as guard  # noqa: E402

FAILS: list[str] = []

#: 临时根：本机 Temp 在沙箱里不可写，统一落在仓库的 .tmp（已 gitignore）。
_TMP = ROOT / ".tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_SEQ = 0


@contextmanager
def tmp_root():
    """建一个本测试专用的临时目录（不用 tempfile：它 mkdtemp 的 0700 会被拒写）。"""
    global _SEQ
    _SEQ += 1
    path = _TMP / f"dg-{os.getpid()}-{_SEQ}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 假件：tasker / controller / 捕获 reporting
# ---------------------------------------------------------------------------
class FakeController:
    def __init__(self, info):
        self.info = info


class FakeTasker:
    def __init__(self, info=None, controller_missing=False):
        self.stopped = 0
        self._controller = None if controller_missing else FakeController(info)

    @property
    def controller(self):
        if self._controller is None:
            raise RuntimeError("no controller")
        return self._controller

    def post_stop(self):
        self.stopped += 1


class Capture:
    """把 device_guard.reporting 换成只记事儿的假件。"""

    def __init__(self):
        self.said: list[str] = []
        self.logged: list[str] = []
        self._real = None

    def __enter__(self):
        self._real = guard.reporting
        capture = self

        class _Rep:
            @staticmethod
            def say(text=""):
                capture.said.append(text)

            @staticmethod
            def log(text=""):
                capture.logged.append(text)

        guard.reporting = _Rep
        return self

    def __exit__(self, *exc):
        guard.reporting = self._real
        return False


def write_instance(root: Path, filename: str, serial: str, name: str = "配置 2") -> Path:
    directory = root / "config" / "instances"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        json.dumps(
            {
                "InstanceName": name,
                "AdbDevice": {"Name": "MuMu安卓设备-2", "AdbSerial": serial},
                "CurrentTasks": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


WANT = "127.0.0.1:16448"
OTHER = "127.0.0.1:16385"


# ---------------------------------------------------------------------------
# 1. argv 解析（顺序无关）
# ---------------------------------------------------------------------------
def case_argv() -> None:
    print("\n== 1. argv 解析 ==")
    guard.reset()
    guard.configure(["--quiet", "XaoAPoDa", "socket_id=XaoAPoDa", "instance_id=b57463f7", "instance_name=配置 2"])
    check("instance_id 命中", guard.instance_id() == "b57463f7", guard.instance_id())

    guard.reset()
    guard.configure(["instance_name=配置 2", "instance_id=b57463f7", "XaoAPoDa"])
    check("换顺序仍命中", guard.instance_id() == "b57463f7", guard.instance_id())

    guard.reset()
    guard.configure(["python", "main.py", "--quiet", "XaoAPoDa"])
    check("没有 instance_id 时为空", guard.instance_id() == "")


# ---------------------------------------------------------------------------
# 2. 配置来源（id → 名回退）
# ---------------------------------------------------------------------------
def case_expected() -> None:
    print("\n== 2. 实例配置 → 期望设备 ==")
    with tmp_root() as tmp:
        root = Path(tmp)
        write_instance(root, "b57463f7.json", WANT, name="配置 2")
        write_instance(root, "default.json", OTHER, name="配置 1")

        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        check("按 id 精确命中", guard.expected_serial() == WANT, guard.expected_serial())

        guard.reset()
        guard.configure(["instance_name=配置 2"], root=root)
        check("没有 id 时按名字回退", guard.expected_serial() == WANT, guard.expected_serial())

        guard.reset()
        guard.configure(["instance_id=nope"], root=root)
        check("id 不存在 → 名字也没有 → 不出错误", isinstance(guard.expected_serial(), str))

        with tmp_root() as empty:
            guard.reset()
            guard.configure(["instance_id=b57463f7"], root=empty)
            check("没有 config/instances → 空串", guard.expected_serial() == "", repr(guard.expected_serial()))


# ---------------------------------------------------------------------------
# 3. 「这一次要用的设备」= GUI 启动记录（首选）/ 实例配置（兜底）
# ---------------------------------------------------------------------------
def _write_gui_log(root: Path, lines: list[str]) -> Path:
    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"log-{datetime.now():%Y%m%d}.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


START_LINE_1 = (
    "[2026-10-21 00:34:19.884][INF] [cfg=Default][inst=配置 1/default][src=UI][op=StartTask] "
    "用户操作：启动任务 | controller=Adb, resource=官服, "
    "device=MuMu安卓设备-MuMuPlayer v5+（127.0.0.1:16385), selectedTasks=1 [自动刷深渊EX]"
)
START_LINE_2 = (
    "[2026-10-21 03:04:30.172][INF] [cfg=Default][inst=配置 2/b57463f7][src=UI][op=StartTask] "
    "用户操作：启动任务 | controller=Adb, resource=官服, "
    "device=MuMu安卓设备-2-MuMuPlayer v5+（127.0.0.1:16448), selectedTasks=1 [自动刷深渊]"
)
START_LINE_2_SWITCHED = (
    "[2026-10-21 04:00:00.000][INF] [cfg=Default][inst=配置 2/b57463f7][src=UI][op=StartTask] "
    "用户操作：启动任务 | controller=Adb, resource=官服, "
    "device=MuMu安卓设备-MuMuPlayer v5+（127.0.0.1:16385), selectedTasks=1 [自动刷深渊]"
)


def case_gui_log() -> None:
    print("\n== 3. GUI 启动记录 = 这一次选中的设备（首选，防误杀） ==")
    with tmp_root() as tmp:
        root = Path(tmp)
        # 配置文件是「持久化值」，故意写成 16448（真机 03:04:27 就是这样滞后的）
        write_instance(root, "b57463f7.json", WANT)
        _write_gui_log(root, [START_LINE_1, START_LINE_2])

        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        serial, source = guard.expected_source()
        check("取本实例最近一条启动记录（不看别的实例）", serial == WANT and source == "gui-log", f"{serial}/{source}")

        # 用户在界面上切到 385 后再开始 —— 判据必须跟着变，绝不误杀正常任务
        _write_gui_log(root, [START_LINE_1, START_LINE_2, START_LINE_2_SWITCHED])
        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        serial2, source2 = guard.expected_source()
        check("切设备后以最新一条为准（不会误杀）", serial2 == OTHER and source2 == "gui-log", f"{serial2}/{source2}")

        # 没有 GUI 日志 → 退回实例配置
        with tmp_root() as no_log:
            write_instance(no_log, "b57463f7.json", WANT)
            guard.reset()
            guard.configure(["instance_id=b57463f7"], root=no_log)
            serial3, source3 = guard.expected_source()
            check("没有 GUI 日志 → 退回实例配置", serial3 == WANT and source3 == "config", f"{serial3}/{source3}")


# ---------------------------------------------------------------------------
# 4. 运行时设备读取
# ---------------------------------------------------------------------------
def case_actual() -> None:
    print("\n== 4. 控制器 info → 实际设备 ==")
    check("info 是属性", guard.actual_serial(FakeTasker({"adb_serial": WANT})) == WANT)

    class CallableInfo:
        @property
        def controller(self):
            return type("C", (), {"info": staticmethod(lambda: {"adb_serial": OTHER})})()

    check("info 是方法", guard.actual_serial(CallableInfo()) == OTHER)
    check("没有 controller → 空串", guard.actual_serial(FakeTasker(controller_missing=True)) == "")
    check("info 里没有 adb_serial → 空串", guard.actual_serial(FakeTasker({})) == "")

    class Boom:
        @property
        def controller(self):
            raise RuntimeError("ipc 挂了")

    check("询问抛异常 → 空串（不炸）", guard.actual_serial(Boom()) == "")


# ---------------------------------------------------------------------------
# 4. 闸门：一致 / 不一致 / 核对不了
# ---------------------------------------------------------------------------
def case_gate() -> None:
    print("\n== 5. 闸门判据 ==")
    with tmp_root() as tmp:
        root = Path(tmp)
        write_instance(root, "b57463f7.json", WANT)

        # 4a. 一致 → 放行
        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        tasker = FakeTasker({"adb_serial": WANT})
        with Capture() as cap:
            ok = guard.check(tasker, 200_004_692)
        check("一致 → 放行", ok is True)
        check("一致 → 不停任务", tasker.stopped == 0)
        check("一致 → 面板不加噪声（只记机制日志）", cap.said == [] and len(cap.logged) == 1, str(cap.logged))

        # 4b. 不一致 → 阻断
        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        tasker = FakeTasker({"adb_serial": OTHER})
        with Capture() as cap:
            ok = guard.check(tasker, 200_004_693)
        check("不一致 → 拦住", ok is False)
        check("不一致 → post_stop 一次", tasker.stopped == 1, str(tasker.stopped))
        text = " | ".join(cap.said)
        check("面板带两边的 serial", WANT in text and OTHER in text, text)
        check("面板给出原因/处置", "原因" in text and "重新连接" in text, text)
        check("面板正好两行", len(cap.said) == 2, str(cap.said))

        # 4c. 核对不了 → fail-open
        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        tasker = FakeTasker({})
        with Capture() as cap:
            ok = guard.check(tasker, 200_004_694)
        check("没有 adb_serial → 放行（不误停）", ok is True and tasker.stopped == 0)
        check("没有 adb_serial → 记一行降级日志", any("无法核对" in line for line in cap.logged), str(cap.logged))

        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=(root / "missing"))
        tasker = FakeTasker({"adb_serial": OTHER})
        with Capture() as cap:
            ok = guard.check(tasker, 200_004_695)
        check("没有实例配置 → 放行（不误停）", ok is True and tasker.stopped == 0)
        check("没有实例配置 → 记一行降级日志", any("无法核对" in line for line in cap.logged), str(cap.logged))


# ---------------------------------------------------------------------------
# 5. 每任务一次
# ---------------------------------------------------------------------------
def case_once_per_task() -> None:
    print("\n== 6. 每个 task_id 只核对一次 ==")
    with tmp_root() as tmp:
        root = Path(tmp)
        write_instance(root, "b57463f7.json", WANT)
        guard.reset()
        guard.configure(["instance_id=b57463f7"], root=root)
        tasker = FakeTasker({"adb_serial": OTHER})
        with Capture():
            first = guard.check(tasker, 7)
            stopped_first = tasker.stopped
            second = guard.check(tasker, 7)
            stopped_second = tasker.stopped
            third = guard.check(tasker, 8)
        check("同一 task 第一次就拦住", first is False and stopped_first == 1, str(stopped_first))
        check("同一 task 第二次不再重复停", second is True and stopped_second == 1, str(stopped_second))
        check("换 task 重新核对", third is False and tasker.stopped == 2, str(tasker.stopped))


# ---------------------------------------------------------------------------
# 6. 降级日志只记一次
# ---------------------------------------------------------------------------
def case_warn_once() -> None:
    print("\n== 7. 降级日志不刷屏 ==")
    guard.reset()
    guard.configure(["instance_id=b57463f7"], root=_TMP / "dg-missing-config")
    with Capture() as cap:
        for i in range(5):
            guard.check(FakeTasker({"adb_serial": OTHER}), 100 + i)
    warnings = [line for line in cap.logged if "无法核对" in line]
    check("只记一次", len(warnings) == 1, str(warnings))
    check("五次都放行", all(True for _ in range(5)))


def main() -> int:
    print("# 设备身份闸门：任务开跑前核对执行器实际连的设备（2026-10-21 448/385 串号事故）")
    case_argv()
    case_expected()
    case_gui_log()
    case_actual()
    case_gate()
    case_once_per_task()
    case_warn_once()

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
