# -*- coding: utf-8 -*-
"""#104 / D9：设备**独占租约**的三道契约（独占排队 / 过期接管与 steal / live_harness 接线）。

## 为什么要有这张票（D9 已裁决，不可再争）
同一台设备会被多个「人」同时用：真机验收脚本、运维在 MFAAvalonia 里点、以后的子代理。
两个 runner 同时驱动一台设备 = 谁也说不清是谁的点击在生效，任何失败都无法归因。
所以设备必须**独占**、被占**排队等**、可 ``--steal`` 强抢 —— 这三件事全靠
``tools/device_lease.py`` 保证，本文件就是它的守卫。

## 契约
- **L1 独占 + 排队**：活租约存在时，第二个 ``acquire(wait=False)`` **必须**抛
  :class:`LeaseBusy`（带持有者 owner/pid/since）；``wait=True`` **必须**一直等到第一个
  ``release()`` 才拿到（实测挂钟，不是「看起来等了」）。
- **L2 过期接管 + steal**：心跳超过 ``ttl`` 视为死锁 -> 可接管，且**必须打印**
  「接管过期租约」（不许静默抢）；``steal=True`` 能立刻抢走**活**租约并打印被抢者；被抢者的
  ``heartbeat()`` 抛 :class:`LeaseLost`、``release()`` 绝不删新持有者的租约。
- **L3 接线**：``live_harness.connect_device`` 在**连设备之前**用
  ``owner="runner:<pid>"`` 拿租约；连不上 / 抛错时立刻还租；同地址重复登记不自己等自己；
  runner 的 ``--steal`` 须能透传（``connect_device(..., steal=True)``）。

## prove-red（``python tools\\contract_hooks\\hooks_104.py``）
三处破坏，要求三个守卫各自变红：
  ① 把 ``_is_live`` 改成恒假（谁都能抢）-> L1 红；
  ② 把 ``_is_live`` 改成恒真（永不过期）-> L2 红；
  ③ 摘掉 ``live_harness._lease_acquire``（连接不再拿租约）-> L3 红。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★（同 hooks_20/25/40）：万一有人用 PYTHONPATH 抢先塞一份
# 坏副本做破坏实验，副本仍优先命中，不被真实的 tools/ 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

import device_lease as dl  # noqa: E402

#: 排队实测的持有时长（秒）：守卫要测出「第二个真的等了」，不是只测「最终拿到了」。
_HOLD_SEC = 0.6
#: 排队的宽松下限：线程调度抖动不该让守卫假红。
_MIN_WAITED = _HOLD_SEC - 0.15
#: 假的「设备地址」—— 守卫绝不连真设备（不 adb、不连真机）。
FAKE_SERIAL = "127.0.0.1:1"
FAKE_SERIAL_2 = "127.0.0.1:2"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _temp_root() -> Path:
    """临时租约根：守卫绝不写 ``debug/``（那会把真机租约搅乱）。"""
    return Path(tempfile.mkdtemp(prefix="wf_hook104_"))


@contextlib.contextmanager
def _lease_root(path: Path):
    """把 ``device_lease.LEASE_ROOT`` 指到临时目录，退出还原（绝不污染真目录）。"""
    saved = dl.LEASE_ROOT
    dl.LEASE_ROOT = Path(path)
    try:
        yield Path(path)
    finally:
        dl.LEASE_ROOT = saved


@contextlib.contextmanager
def _quiet():
    """吞掉 acquire/release 的正常打印（要断言「必须打印」的用例自己收 buffer）。"""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def _write_stale(serial: str, owner: str, *, ttl: float, age: float) -> Path:
    """手写一份「心跳停在 age 秒前」的租约（模拟持有者被 taskkill / 断电 / 搬走）。"""
    path = dl.lease_path(serial)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    path.write_text(
        json.dumps(
            {
                "owner": owner,
                "pid": 424242,
                "host": "dead-box",
                "since": now - age - 30.0,
                "heartbeat": now - age,
                "ttl": ttl,
                "serial": serial,
            }
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# L1：独占 + 排队
# ---------------------------------------------------------------------------
class _Waiter(threading.Thread):
    """在后台跑一次 ``acquire(wait=True)``，记录「等了多久」与「拿到没有」。"""

    def __init__(self, serial: str, owner: str, ttl: float) -> None:
        super().__init__(name=f"hook104-waiter-{owner}", daemon=True)
        self.serial = serial
        self.owner = owner
        self.ttl = ttl
        self.waited: float | None = None
        self.owner_seen: str | None = None
        self.error: str | None = None

    def run(self) -> None:  # noqa: D102
        started = time.monotonic()
        try:
            with _quiet():
                lease = dl.acquire(self.serial, self.owner, ttl=self.ttl, wait=True)
        except BaseException as exc:  # noqa: BLE001 -- 线程里的异常要带回主线程判红
            self.error = repr(exc)
            return
        self.waited = time.monotonic() - started
        # 拿到的那一刻文件里的 owner 必须是新人（否则「排队」只是假象）；随后放手，
        # 别让守卫自己把租约留到进程退出（那会遮住后面的用例）。
        self.owner_seen = (dl.read_lease(self.serial) or {}).get("owner")
        with _quiet():
            lease.release()


def probe_lease_exclusive_queue() -> bool:
    """L1：活租约 + ``wait=False`` -> LeaseBusy；``wait=True`` -> 等到 release 才拿到。"""
    root = _temp_root()
    try:
        with _lease_root(root):
            return _exclusive_queue_case()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _exclusive_queue_case() -> bool:
    serial = FAKE_SERIAL
    with _quiet():
        first = dl.acquire(serial, "runner:first", ttl=60)
    try:
        # (a) 不想等 = 立刻报忙，且报出持有者（owner / pid / since）
        try:
            with _quiet():
                dl.acquire(serial, "runner:second", ttl=60, wait=False)
        except dl.LeaseBusy as exc:
            if (exc.owner, exc.pid) != ("runner:first", os.getpid()) or not exc.since:
                return False
        else:
            return False  # 没抛 = 独占失效（两个人都拿到了）

        # (b) 想等 = 必须真的等到 release
        waiter = _Waiter(serial, "runner:second", 60)
        waiter.start()
        time.sleep(_HOLD_SEC)
        early = waiter.waited is not None  # 还没 release 就拿到 = 根本没排队
        with _quiet():
            first.release()
        waiter.join(timeout=5.0)
        if waiter.is_alive() or early or waiter.error or waiter.waited is None:
            return False
        if waiter.waited < _MIN_WAITED:
            return False
        # 接手后 owner 必须换成新人（否则「排队」只是假象）
        return waiter.owner_seen == "runner:second"
    finally:
        with _quiet():
            first.release()


# ---------------------------------------------------------------------------
# L2：过期接管 + steal
# ---------------------------------------------------------------------------
def probe_lease_expiry_and_steal() -> bool:
    """L2：过期租约可接管并打印；``steal`` 抢活租约并打印被抢者。"""
    root = _temp_root()
    try:
        with _lease_root(root):
            return _expiry_steal_case()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _expiry_steal_case() -> bool:  # noqa: PLR0911 -- 每条 return False 都是一条独立的契约
    serial = FAKE_SERIAL
    _write_stale(serial, "dead-runner", ttl=5.0, age=300.0)
    if dl._is_live(dl.read_lease(serial)):
        return False  # 前提不成立：这份租约其实没过期，后面测的就不是接管

    buffer = io.StringIO()
    taken = None
    try:
        with contextlib.redirect_stdout(buffer):
            taken = dl.acquire(serial, "runner:alive", ttl=60, wait=False)
        printed = buffer.getvalue()
        if "接管过期租约" not in printed:
            return False  # 静默接管 = 出事了没人能追溯「谁抢了谁」
        if "dead-runner" not in printed or "424242" not in printed:
            return False  # 打印里没有原持有者，等于没线索
        if (dl.read_lease(serial) or {}).get("owner") != "runner:alive":
            return False

        # steal：抢一个**活**租约
        buffer2 = io.StringIO()
        with contextlib.redirect_stdout(buffer2):
            thief = dl.acquire(serial, "runner:thief", ttl=60, steal=True)
        stolen = buffer2.getvalue()
        try:
            if "runner:alive" not in stolen:
                return False  # 没打印被抢者
            if (dl.read_lease(serial) or {}).get("owner") != "runner:thief":
                return False
            if taken.is_mine():
                return False  # 被抢了还说租约是我的 = 独占失效
            try:
                with _quiet():
                    taken.heartbeat()
            except dl.LeaseLost:
                pass
            else:
                return False  # 被抢了还假装修租成功
            with _quiet():
                deleted = taken.release()
            if deleted:
                return False  # 删掉别人的租约 = 偷偷把设备让出去了
            return (dl.read_lease(serial) or {}).get("owner") == "runner:thief"
        finally:
            with _quiet():
                thief.release()
    finally:
        if taken is not None:
            with _quiet():
                taken.release()


# ---------------------------------------------------------------------------
# L3：live_harness 接线（假 controller，绝不连设备）
# ---------------------------------------------------------------------------
class _FakeJob:
    def __init__(self, ok: bool) -> None:
        self.succeeded = ok

    def wait(self) -> "_FakeJob":
        return self


class _FakeCtrl:
    """只回答 ``post_connection().wait().succeeded``：不 adb、不连真机。"""

    next_ok = True

    def __init__(self, adb: str, address: str) -> None:
        self.adb = adb
        self.address = address

    def post_connection(self) -> _FakeJob:
        return _FakeJob(type(self).next_ok)


class _NullLease:
    """破坏实验用的「假租约」：接口在、事不做。"""

    def __init__(self, serial: str) -> None:
        self.serial = serial

    def is_mine(self) -> bool:
        return False

    def heartbeat(self) -> dict:
        return {}

    def release(self) -> bool:
        return False


def probe_lease_wired_into_harness() -> bool:
    """L3：``connect_device`` 连设备前拿租约（owner=runner:<pid>），连不上立刻还租。"""
    root = _temp_root()
    try:
        return _wired_case(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _wired_case(root: Path) -> bool:  # noqa: PLR0911,PLR0912 -- 同上，每条 return 都是契约
    import live_harness as ca  # 延迟导入：hook 发现阶段不为每个套件都拖进 maa/numpy

    serial, serial2 = FAKE_SERIAL, FAKE_SERIAL_2
    saved = {
        "root": dl.LEASE_ROOT,
        "ctrl_cls": ca.AdbController,
        "adb": ca.ADB,
        "address": ca.ADDRESS,
        "ctrl": ca._ctrl_ref.get("ctrl"),
        "lease": ca._DEVICE_LEASE.get("lease"),
        "acquire": ca._lease_acquire,
    }
    ca._DEVICE_LEASE["lease"] = None
    calls: list = []
    real_acquire = ca._lease_acquire

    def spy(serial_arg, owner, **kwargs):
        calls.append((serial_arg, owner, dict(kwargs)))
        return real_acquire(serial_arg, owner, **kwargs)

    try:
        dl.LEASE_ROOT = Path(root)
        ca.AdbController = _FakeCtrl  # type: ignore[assignment]
        ca._lease_acquire = spy  # type: ignore[assignment]

        # (a) 连接成功：租约已经落盘，owner = runner:<pid>
        _FakeCtrl.next_ok = True
        with _quiet():
            ca.connect_device("fake-adb", serial)
        if not calls or calls[0][0] != serial:
            return False  # 连接前没拿租约
        if calls[0][1] != f"runner:{os.getpid()}":
            return False  # owner 形状不对（排队的人认不出是谁）
        record = dl.read_lease(serial)
        if not record or record.get("pid") != os.getpid():
            return False  # 租约文件没落盘
        if ca.held_device_lease() is None:
            return False  # harness 自己不记得持有租约 = 没法 release
        if ca.ADDRESS != serial:
            return False  # 既有行为被改坏了（地址必须照样登记）

        # (b) 同地址重复登记：不许自己等自己（重入路径不重新 acquire）
        with _quiet():
            ca.connect_device("fake-adb", serial)
        if len(calls) != 1:
            return False  # 又 acquire 了一次 = 同一进程会自己等自己
        if ca.held_device_lease() is None:
            return False

        # (b2) --steal 必须能透传到 device_lease.acquire（runner 的 --steal 靠这条缝）
        with _quiet():
            ca.release_device_lease()
        calls.clear()
        with _quiet():
            ca.connect_device("fake-adb", serial, steal=True)
        if not calls or calls[0][2].get("steal") is not True:
            return False  # --steal 被吞掉了 = 抢不动

        # (c) 连不上：require=True -> 抛错，且租约立刻还回去（别让排队的人白等一个 TTL）
        _FakeCtrl.next_ok = False
        try:
            with _quiet():
                ca.connect_device("fake-adb", serial2, require=True)
        except RuntimeError:
            pass
        else:
            return False  # 连不上还不抛 = 行为变了
        if dl.read_lease(serial2) is not None:
            return False  # 连不上还占着设备
        return ca.held_device_lease() is None
    finally:
        # 先放掉守卫自己拿的租约，再还原一切（顺序反了会把临时文件留给 atexit 去删）
        with contextlib.suppress(Exception):
            ca.release_device_lease()
        dl.LEASE_ROOT = saved["root"]
        ca.AdbController = saved["ctrl_cls"]  # type: ignore[assignment]
        ca.ADB = saved["adb"]  # type: ignore[assignment]
        ca.ADDRESS = saved["address"]  # type: ignore[assignment]
        ca._ctrl_ref["ctrl"] = saved["ctrl"]
        ca._DEVICE_LEASE["lease"] = saved["lease"]
        ca._lease_acquire = saved["acquire"]  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_104.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """真实绿；三处破坏，要求三个守卫各自变红（红 = 可用信号）。"""
    print("hooks_104 prove-red：三处破坏，要求三个守卫各自变红")
    green = (
        probe_lease_exclusive_queue() is True
        and probe_lease_expiry_and_steal() is True
        and probe_lease_wired_into_harness() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：独占排队 + 过期接管/steal + 接线（绿）")
    if not green:
        return False

    checks: list[bool] = []

    # ① 活/死判定恒假（谁都算死）-> 排队守卫红（第二个不再等，直接抢）。
    real_live = dl._is_live
    try:
        dl._is_live = lambda *a, **k: False  # type: ignore[assignment]
        red = probe_lease_exclusive_queue() is not True
        print(f"  [{'PASS' if red else 'FAIL'}] 把活/死判定改成恒假（谁都能抢）-> "
              f"{'红' if red else '仍绿'}")
    finally:
        dl._is_live = real_live  # type: ignore[assignment]
    checks.append(red)

    # ② 活/死判定恒真（永不过期）-> 过期接管守卫红（死锁永远解不开）。
    try:
        dl._is_live = lambda *a, **k: True  # type: ignore[assignment]
        red = probe_lease_expiry_and_steal() is not True
        print(f"  [{'PASS' if red else 'FAIL'}] 把活/死判定改成恒真（永不过期）-> "
              f"{'红' if red else '仍绿'}")
    finally:
        dl._is_live = real_live  # type: ignore[assignment]
    checks.append(red)

    # ③ 摘掉连接路径上的 acquire -> 接线守卫红（连设备不拿租约）。
    import live_harness as ca

    real_acquire = ca._lease_acquire
    try:
        ca._lease_acquire = lambda serial, owner, **kw: _NullLease(serial)  # type: ignore[assignment]
        red = probe_lease_wired_into_harness() is not True
        print(f"  [{'PASS' if red else 'FAIL'}] 摘掉 connect_device 的租约 acquire -> "
              f"{'红' if red else '仍绿'}")
    finally:
        ca._lease_acquire = real_acquire  # type: ignore[assignment]
    checks.append(red)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "lease-exclusive-queue",
        "#104",
        "设备独占 + 被占排队：活租约时第二个 acquire(wait=False) 抛 LeaseBusy（带 owner/pid/since），"
        "wait=True 必须等到第一个 release 才拿到（实测挂钟，接手后 owner 换人）",
        probe_lease_exclusive_queue,
    ),
    (
        "lease-expiry-and-steal",
        "#104",
        "心跳超 ttl = 死锁可接管且必须打印「接管过期租约」（带原持有者）；steal 能抢活租约并打印被抢者；"
        "被抢者 heartbeat 抛 LeaseLost、release 不删新租约",
        probe_lease_expiry_and_steal,
    ),
    (
        "lease-wired-into-harness",
        "#104",
        "live_harness.connect_device 连设备前拿租约 owner=runner:<pid>、同地址重复登记不自己等自己、"
        "连不上立刻还租、--steal 能透传（既有行为不变：地址照样登记）",
        probe_lease_wired_into_harness,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
