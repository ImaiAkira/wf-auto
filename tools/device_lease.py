# -*- coding: utf-8 -*-
"""#104 / D9：设备**独占租约**（文件锁式；零第三方依赖）。

同一台设备会同时被多个「人」用：真机验收脚本、运维在 MFAAvalonia 里点、未来的子代理。
两个 runner 同时驱动一台设备 = 谁也看不出是谁的点击在生效，任何失败都无法归因。
本模块给设备加一把**跨进程**的独占锁，规则（D9 已裁决，不可再争）：

* **独占**：一个 serial 同时只有一份活租约（``<serial>.json``）；
* **被占排队等**：已有活租约（心跳未过期）且没 ``steal`` -> 轮询等，``wait=False`` 直接抛
  :class:`LeaseBusy`（带持有者的 owner/pid/since）；
* **死锁可接管**：心跳超过 ``ttl``（默认 120s）视为持有者已死 —— 可被接管，但**必须打印**
  「接管过期租约」（不许静默抢，否则「谁抢了谁」无从追溯）；
* **``steal=True`` 强抢**：立刻接管，并打印被抢者（只有运维显式 ``--steal`` 才该用）；
* **进程退出必放**：``try/finally`` + ``atexit`` 双保险（见 :meth:`Lease.release`）。

租约文件
--------
``debug/.device_lease/<serial 安全化>.json``（``:`` 等字符换成 ``_``；``debug/`` 已在
``.gitignore`` 里，租约是运行期产物，不进版本库）::

    {"owner": "runner:12345", "pid": 12345, "host": "DESKTOP-X",
     "since": 1770000000.0, "heartbeat": 1770000010.0, "ttl": 120.0, "serial": "127.0.0.1:16384"}

``since`` / ``heartbeat`` 都是 epoch 秒（浮点）。多出来的 ``ttl`` / ``serial`` 两个字段是
**故意**的：

* ``ttl`` 让**持有者**的过期判据说话 —— 否则一个用 ``ttl=30`` 续租的持有者，会被一个用
  ``ttl=120`` 的等待者误判成「已过期」而抢走活租约；
* ``serial`` 让 ``status`` 列表和诊断输出不必再从文件名反推。

为什么不用 OS 的 advisory lock（``msvcrt.locking`` / ``fcntl.flock``）
--------------------------------------------------------------------
那种锁**随进程死亡自动释放**，看着更省事，但它撑不起 D9 的 ``steal`` 语义：强抢要能
``--steal`` 掉一个**还活着**的持有者，也要能看出「谁占着、占了多久、心跳停在哪」。所以租约
是**记录文件 + 心跳 + TTL**，而不是一把内核锁。互相排斥靠 ``os.open(O_CREAT|O_EXCL)``
（Windows 上是 ``CREATE_NEW``，跨进程原子）保证；接管/续租这类「读-判-写」在
:func:`_mutex` 的短临界区里做，避免两个等待者同时接管同一份过期租约。

为什么同进程重入不算冲突
------------------------
``live_harness.connect_device`` 会在同一个进程里被调用多次（runner 先报身份再连、测试里
patch 掉 ``AdbController`` 再连）。若把「自己」也当外人，第二次调用就会**自己等自己**到
天荒地老。所以 owner + pid 都相同的活租约视为**重入**：只续租、不重复占，返回的
:class:`Lease` 标 ``reentrant``，它的 :meth:`Lease.release` 是 no-op（真正的持有者才释放）。

★#114 更正（真机踩坑）★：不要后台跑 ``--acquire --hold`` 长驻 —— 每个需要连设备的脚本内部
都会再 acquire，``--hold`` 持有期间它们**全部排队等死**。正确用法：每个进程自己
``acquire``（自动心跳）/ ``release``，**不要 --hold**。

跑法（只读诊断；运维想知道「谁占着设备」时用）::

    python tools\\device_lease.py                 # 列出全部租约（活/死、剩余秒数）
    python tools\\device_lease.py 127.0.0.1:16384 # 只看一台
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

try:  # host 只用于日志/诊断：拿不到就退化成 "?"
    import socket
except ImportError:  # pragma: no cover -- 极简运行时不带 socket
    socket = None  # type: ignore[assignment]

#: 仓库根（本文件在 ``<repo>/tools/`` 下）。
PROJECT = Path(__file__).resolve().parent.parent
#: 租约目录名（相对 ``debug/``；spec §4.5 / 票 #104）。
LEASE_DIR_NAME = ".device_lease"
#: 默认 TTL（秒）：心跳超过它就算死锁，可被接管（D9 / 票 #104）。
DEFAULT_TTL = 120.0
#: 排队轮询间隔（秒）。
POLL_INTERVAL = 0.5
#: 自动心跳间隔 = ttl / 这个数（续租足够密，又不会把磁盘打满）。
HEARTBEAT_FRACTION = 3.0
#: 短临界区互斥锁的最长等待（秒）。临界区只读写一个 JSON（微秒级），等这么久还没拿到
#: 说明上一个持有者崩在临界区里了 —— 交给下面的 ``_MUTEX_STALE_SEC`` 清僵尸锁。
_MUTEX_TIMEOUT = 5.0
#: 互斥锁文件「多久没动」算僵尸锁（上一个持有者崩在临界区里，锁文件没人删）。
_MUTEX_STALE_SEC = 10.0
#: serial 里不能进文件名的字符（``:`` / ``/`` / ``\`` 等）统统换成 ``_``。
_UNSAFE = re.compile(r"[^0-9A-Za-z._-]+")
#: 安全化后的文件名长度上限（serial 一般是 ``host:port`` / ``emulator-5554``，很短）。
_MAX_KEY_LEN = 100


def _default_root() -> Path:
    """租约目录：``WF_DEVICE_LEASE_DIR``（测试/换机器覆盖）否则 ``<repo>/debug/.device_lease``。"""
    env = os.environ.get("WF_DEVICE_LEASE_DIR", "").strip()
    return Path(env) if env else PROJECT / "debug" / LEASE_DIR_NAME


#: 租约根目录。**运行期可改**（测试把它指向临时目录，绝不在 ``debug/`` 里留垃圾）。
LEASE_ROOT: Path = _default_root()


def _root() -> Path:
    """每次都重新取模块级 ``LEASE_ROOT``（测试 monkeypatch 它才有效）。"""
    return Path(LEASE_ROOT)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class LeaseError(RuntimeError):
    """租约相关错误的基类。租约设施的故障**响亮失败**，绝不静默降级成「没锁」。"""


class LeaseBusy(LeaseError):
    """设备已被**活**租约占着，且调用方不想等（``wait=False``）或等超时了。

    属性 ``owner`` / ``pid`` / ``since`` 就是持有者的身份（``since`` = 租约开始时间，
    epoch 秒），``host`` 是哪台机器，``expires_in`` 是「还有多少秒过期」。
    """

    def __init__(self, serial: str, record: dict | None, *, reason: str = "被占用") -> None:
        record = record or {}
        self.serial = serial
        self.owner = str(record.get("owner") or "?")
        self.pid = record.get("pid")
        self.host = str(record.get("host") or "?")
        self.since = record.get("since")
        self.heartbeat = record.get("heartbeat")
        self.expires_in = remaining_sec(record)
        tail = f"，还有 {self.expires_in:.0f}s 过期" if self.expires_in is not None else ""
        super().__init__(
            f"设备 {serial} 已被占用：owner={self.owner} pid={self.pid} host={self.host}"
            f" since={fmt_ts(self.since)}{tail}（{reason}）"
        )


class LeaseLost(LeaseError):
    """本 :class:`Lease` 已经不再是持有者（被别人 ``steal`` / 过期接管 / 已 release）。"""

    def __init__(self, serial: str, record: dict | None, *, reason: str = "已被接管") -> None:
        record = record or {}
        self.serial = serial
        self.owner = str(record.get("owner") or "?")
        self.pid = record.get("pid")
        super().__init__(
            f"设备 {serial} 的租约已不在本进程手里（现在 owner={self.owner} pid={self.pid}，{reason}）"
        )


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def host() -> str:
    """本机名（诊断用：两台机器抢同一台设备时必须看得出是哪台）。"""
    env = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME")
    if env:
        return str(env)
    if socket is not None:
        try:
            return socket.gethostname() or "?"
        except OSError:  # pragma: no cover -- 取不到主机名不该让租约失败
            return "?"
    return "?"  # pragma: no cover


def fmt_ts(value) -> str:
    """epoch 秒 -> ``HH:MM:SS``（日志里看得懂即可；坏值原样转字符串）。"""
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return str(value)


def _number(value) -> float | None:
    """把记录里的值当数字取（坏值 -> None，绝不抛）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def serial_key(serial: str) -> str:
    """serial -> 安全文件名（``127.0.0.1:16384`` -> ``127.0.0.1_16384``）。"""
    key = _UNSAFE.sub("_", (serial or "").strip()).strip("._-")
    if len(key) > _MAX_KEY_LEN:  # 超长 serial：截断（租约文件只是标记，不做反推）
        key = key[:_MAX_KEY_LEN].rstrip("._-")
    return key or "unknown"


def lease_path(serial: str) -> Path:
    """这台设备的租约文件路径（``<LEASE_ROOT>/<安全化 serial>.json``）。"""
    return _root() / f"{serial_key(serial)}.json"


# ---------------------------------------------------------------------------
# 记录读写：原子创建 / 原子覆盖 / 容错读取
# ---------------------------------------------------------------------------
def _load(path: Path) -> dict | None:
    """读租约记录；文件不存在 / 读不出 / JSON 坏了都返回 ``None``（= 没有可用租约）。

    坏记录**不抛**：一个写了一半的 JSON 不该让所有人永久排队，它等同「没有租约」，
    由接管路径打印「原文件无可解析记录」后再覆盖（取证线索仍留在日志里）。
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return None
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return record if isinstance(record, dict) else None


def _record(serial: str, owner: str, ttl: float, now: float | None = None) -> dict:
    """新租约记录（``since`` = ``heartbeat`` = 现在）。"""
    stamp = time.time() if now is None else float(now)
    return {
        "owner": owner,
        "pid": os.getpid(),
        "host": host(),
        "since": stamp,
        "heartbeat": stamp,
        "ttl": float(ttl),
        "serial": serial,
    }


def _temp_path(path: Path) -> Path:
    """同目录唯一临时名（进程 + 线程 + 纳秒）：写坏也只坏临时文件，正式文件永远完整。"""
    suffix = f".{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    return Path(path).with_name(Path(path).name + suffix)


def _write(path: Path, record: dict) -> None:
    """原子覆盖租约记录（写临时文件 + ``os.replace``）：读的人绝不会读到半个 JSON。"""
    path = Path(path)
    tmp = _temp_path(path)
    payload = json.dumps(record, ensure_ascii=False, indent=1)
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()


def _create_exclusive(path: Path, record: dict) -> bool:
    """原子创建租约（``O_CREAT|O_EXCL``）：成功 = 抢到；已存在 = 没抢到（绝不覆盖）。

    这是「独占」的**第一道也是最重要的一道**保证：``O_CREAT|O_EXCL`` 在 Windows 上落到
    ``CreateFileW(CREATE_NEW)``，两个进程同时建同一个路径**必有且仅有一个**成功。
    """
    path = Path(path)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, json.dumps(record, ensure_ascii=False, indent=1).encode("utf-8"))
    except BaseException:
        # 写坏了就删掉：绝不留一个空文件把后来者永久挡在门外（下次按「无可解析记录」接管）。
        with contextlib.suppress(OSError):
            os.close(fd)
        fd = -1
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
    return True


@contextlib.contextmanager
def _mutex(path: Path, timeout: float = _MUTEX_TIMEOUT):
    """租约记录的**短临界区**互斥锁（``<lease>.json.lock``，``O_EXCL`` 创建）。

    为什么需要它：接管过期租约是「读 -> 判过期 -> 写」三步，两个等待者可能同时判「过期」
    然后各自写一遍，都以为自己抢到了。临界区里重判一次，第二个就会看到活租约而继续排队。
    锁只持有微秒级；持有者若崩在临界区里，锁文件的 mtime 会停在 ``_MUTEX_STALE_SEC`` 之前，
    下一个等待者按僵尸锁清掉（否则一次崩溃就让那台设备永久锁死）。
    """
    lock = Path(path).with_name(Path(path).name + ".lock")
    deadline = time.monotonic() + float(timeout)
    fd = -1
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with contextlib.suppress(OSError):
                os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            if age > _MUTEX_STALE_SEC:
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            if time.monotonic() >= deadline:
                raise LeaseError(
                    f"租约互斥锁等待超时（{lock.name}）：临界区只该占用微秒级，"
                    f"检查是否有进程崩在 {lock}"
                )
            time.sleep(0.01)
    try:
        yield
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


# ---------------------------------------------------------------------------
# 活/死判定
# ---------------------------------------------------------------------------
def remaining_sec(record: dict | None, now: float | None = None, default_ttl: float = DEFAULT_TTL) -> float | None:
    """距离心跳过期还有多少秒（<=0 = 已过期；``None`` = 记录里连心跳都没有）。

    ``ttl`` 以**记录里的**为准（持有者自己的续租节奏才是判据），缺省才用 ``default_ttl``。
    """
    if not isinstance(record, dict):
        return None
    beat = _number(record.get("heartbeat"))
    if beat is None:
        beat = _number(record.get("since"))
    if beat is None:
        return None
    ttl = _number(record.get("ttl"))
    if ttl is None or ttl <= 0:
        ttl = float(default_ttl)
    return ttl - ((time.time() if now is None else float(now)) - beat)


def _is_live(record: dict | None, now: float | None = None, default_ttl: float = DEFAULT_TTL) -> bool:
    """租约是否还活着（心跳没过期）。``_load`` 返回 ``None`` 时恒为假。

    ★探针/破坏实验的挂点★：``acquire`` 每次都用裸名字调用它（模块全局查表），所以
    ``device_lease._is_live = lambda *a, **k: False`` 能当场把「排队」变成「谁都能抢」，
    ``= lambda *a, **k: True`` 能当场把「过期可接管」变成「永不过期」。
    """
    rem = remaining_sec(record, now, default_ttl)
    return rem is not None and rem > 0


def _same_holder(record: dict | None, owner: str) -> bool:
    """这份记录是不是**本进程**自己持有的（owner + pid 都相同 = 同进程重入）。"""
    if not isinstance(record, dict):
        return False
    if str(record.get("owner") or "") != owner:
        return False
    pid = _number(record.get("pid"))
    return pid is not None and int(pid) == os.getpid()


# ---------------------------------------------------------------------------
# Lease：拿到的租约（ctx manager）
# ---------------------------------------------------------------------------
class Lease:
    """一份设备租约（``acquire`` 的返回值；支持 ``with``）。

    * :meth:`release` —— 放掉（删租约文件）；幂等，第二次返回 ``False``；别人的租约绝不动；
    * :meth:`heartbeat` —— 续租（刷 ``heartbeat``）；已被别人接管则抛 :class:`LeaseLost`；
    * ``with acquire(...) as lease:`` —— 退出代码块（含异常）自动 release。

    进程被杀（``taskkill`` / 崩溃 / 断电）时靠 ``atexit`` 兜最后一道，来不及跑也会有
    TTL 兜底（心跳过期 -> 排队者接管并打印「接管过期租约」）。
    """

    def __init__(
        self,
        serial: str,
        owner: str,
        ttl: float,
        record: dict,
        *,
        path: Path,
        reentrant: bool = False,
        auto_heartbeat: bool = False,
    ) -> None:
        self.serial = str(serial)
        self.owner = str(owner)
        self.ttl = float(ttl)
        self.path = Path(path)
        self.reentrant = bool(reentrant)
        self._record = dict(record)
        self._lock = threading.RLock()
        self._released = False
        self._stop = threading.Event()
        self._beat_thread: threading.Thread | None = None
        if not self.reentrant:
            atexit.register(self._release_at_exit)
        if auto_heartbeat and not self.reentrant:
            self._start_heartbeat()

    # -- 只读视图 ----------------------------------------------------------
    @property
    def pid(self) -> int | None:
        pid = _number(self._record.get("pid"))
        return int(pid) if pid is not None else None

    @property
    def host(self) -> str:
        return str(self._record.get("host") or "?")

    @property
    def since(self) -> float | None:
        return _number(self._record.get("since"))

    @property
    def heartbeat(self) -> float | None:
        return _number(self._record.get("heartbeat"))

    def info(self) -> dict:
        """当前租约记录（副本：改它不会影响文件）。"""
        with self._lock:
            return dict(self._record)

    # -- 续租 --------------------------------------------------------------
    def heartbeat(self) -> dict:
        """续租：把 ``heartbeat`` 刷成现在（``since`` / ``owner`` 不变）。

        已经被别人接管（``steal`` / 过期被接手）时抛 :class:`LeaseLost` —— **不要吞掉它**：
        那意味着本进程不再独占设备，继续驱动设备就是在和别人抢。
        """
        with self._lock:
            if self._released:
                raise LeaseLost(self.serial, self._record, reason="本 Lease 已 release")
            beat = time.time()
            with _mutex(self.path):
                current = _load(self.path)
                if current is None or not _same_holder(current, self.owner):
                    raise LeaseLost(self.serial, current or self._record)
                current["heartbeat"] = beat
                current.setdefault("ttl", self.ttl)
                _write(self.path, current)
                self._record = dict(current)
                return dict(current)

    def _start_heartbeat(self) -> None:
        """后台续租线程（daemon）：每 ``ttl/3`` 一次，保证长跑（五重连刷几小时）不会被判死。"""
        interval = max(0.2, self.ttl / HEARTBEAT_FRACTION)

        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.heartbeat()
                except LeaseLost as exc:
                    if self._stop.is_set():  # 正常释放时正好撞上：不是事故，别刷屏
                        return
                    print(f"[lease] ★续租失败，本进程已不再持有设备 {self.serial}：{exc}★", flush=True)
                    return
                except (OSError, LeaseError) as exc:  # 临时故障：下一轮再试（别把线程打崩）
                    print(f"[lease] 续租异常（继续尝试）：{exc!r}", flush=True)

        thread = threading.Thread(
            target=loop, name=f"device-lease-{serial_key(self.serial)}", daemon=True
        )
        self._beat_thread = thread
        thread.start()

    def stop_heartbeat(self) -> None:
        """置停止信号并**等**续租线程真的退出（收尾 / 测试用）。

        :meth:`release` 只置信号、不 join（它可能正被续租线程等锁，join 会白等一个心跳周期）；
        需要确认线程已退出的场合（长跑收尾、pytest 清理）用这个。
        """
        self._stop.set()
        thread = self._beat_thread
        self._beat_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.5, self.ttl / HEARTBEAT_FRACTION + 0.5))

    # -- 释放 --------------------------------------------------------------
    def release(self) -> bool:
        """放掉租约（删文件）。返回是否真的删掉了。

        * 幂等：同一个 Lease 第二次 release 返回 ``False``，不抛；
        * **别人的租约绝不动**：文件里的 owner 已经不是我（被 steal / 过期被接管）就只打印、
          不删 —— 否则删掉别人的租约等于偷偷把设备让出去；
        * 重入 Lease（``reentrant``）是 no-op：真正持有者才负责释放。
        """
        with self._lock:
            self._stop.set()
            if self.reentrant:
                self._released = True
                print(
                    f"[lease] 同进程重入的租约，不释放设备 {self.serial}（由真正持有者释放）",
                    flush=True,
                )
                return False
            if self._released:
                return False
            self._released = True
            self._unregister_atexit()
            with _mutex(self.path):
                current = _load(self.path)
                if current is not None and not _same_holder(current, self.owner):
                    print(
                        f"[lease] 设备 {self.serial} 的租约已被 {current.get('owner')}"
                        f"（pid={current.get('pid')}）接管，不删别人的租约",
                        flush=True,
                    )
                    return False
                with contextlib.suppress(FileNotFoundError):
                    self.path.unlink()
            print(f"[lease] 释放设备 {self.serial} 的租约（owner={self.owner}）", flush=True)
            return True

    def _unregister_atexit(self) -> None:
        unregister = getattr(atexit, "unregister", None)
        if unregister is None:  # pragma: no cover -- Python < 3.9
            return
        with contextlib.suppress(Exception):
            unregister(self._release_at_exit)

    def _release_at_exit(self) -> None:
        """进程退出路径：**绝不抛**（解释器收尾阶段抛异常只会盖掉真正的退出原因）。"""
        try:
            self.release()
        except Exception:  # noqa: BLE001 -- 退出路径必须静默
            pass

    # -- 状态 --------------------------------------------------------------
    def is_mine(self) -> bool:
        """租约文件现在是否仍由本进程持有（``steal`` / 过期被接管后为假）。"""
        with self._lock:
            if self._released:
                return False
            return _same_holder(_load(self.path), self.owner)

    def __enter__(self) -> "Lease":
        if self._released:
            raise LeaseError(f"设备 {self.serial} 的租约已释放，不能再进 with 块")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def __repr__(self) -> str:
        flag = " reentrant" if self.reentrant else ""
        return (
            f"<Lease serial={self.serial!r} owner={self.owner!r} pid={self.pid} "
            f"ttl={self.ttl:.0f}s{flag}>"
        )


# ---------------------------------------------------------------------------
# acquire：独占 / 排队 / 接管过期 / steal
# ---------------------------------------------------------------------------
def _poll_delay(record: dict | None, now: float, deadline: float | None) -> float:
    """一次排队等待睡多久：默认 0.5s；快过期时早一点再看一眼，避免迟到半秒白等。"""
    delay = POLL_INTERVAL
    rem = remaining_sec(record, now)
    if rem is not None and rem > 0:
        delay = min(delay, rem)
    if deadline is not None:
        delay = min(delay, max(0.0, deadline - time.monotonic()) or POLL_INTERVAL)
    return max(0.05, delay)


def _takeover(
    path: Path,
    serial: str,
    owner: str,
    ttl: float,
    *,
    steal: bool,
    allow_unparsable: bool = False,
) -> tuple[bool, dict | None]:
    """在短临界区里重判一次，然后接管（返回 ``(是否接管到, 被接管者的记录)``）。

    重判是必须的：两个等待者可能都看到「过期」，若各自直接写，两人都会以为自己抢到了。
    锁里重读一次，第二个就会看到**刚刚写下的活租约**而退回排队。

    ``allow_unparsable=True`` 是给「文件在、但读不出记录」（写了一半 / 手工写坏）用的：
    那种文件必须能被覆盖，否则一台设备会被一个坏文件**永久**挡在门外。
    """
    with _mutex(path):
        current = _load(path)
        now = time.time()
        if current is not None and _is_live(current, now, ttl) and not steal:
            return False, current
        if current is None and not allow_unparsable:
            # 这一瞬别人把文件删了/写好了：回主循环按「新建」或「活租约」重判。
            return False, None
        _write(path, _record(serial, owner, ttl, now=now))
        return True, current


def acquire(
    serial: str,
    owner: str,
    ttl: float = DEFAULT_TTL,
    steal: bool = False,
    wait: bool = True,
    timeout: float | None = None,
    *,
    auto_heartbeat: bool = False,
) -> Lease:
    """拿这台设备的独占租约；返回 :class:`Lease`（``with`` 用，或自己 ``release()``）。

    参数
    ----
    serial : 设备 serial（``127.0.0.1:16384`` / ``emulator-5554`` …）。★路径由它决定★。
    owner  : 谁占的（``runner:<pid>`` / ``ops`` …）——别人排队时看的就是它。
    ttl    : 心跳过期阈值（秒），默认 :data:`DEFAULT_TTL` = 120。
    steal  : ``True`` = 强抢**活**租约（打印被抢者）；只有运维显式 ``--steal`` 才该用。
    wait   : 被活租约占着时是否排队等；``False`` = 立刻抛 :class:`LeaseBusy`。
    timeout: 排队上限（秒）；``None`` = 一直等（D9：被占就排队，不设人为上限）。

    语义（D9，逐条）：没有租约 -> 立刻独占；有**活**租约且没 ``steal`` -> 打印持有者并
    排队（``wait=False`` 抛 :class:`LeaseBusy`）；心跳过期 -> 打印「接管过期租约」后接管；
    ``steal=True`` -> 打印被抢者后立刻接管。
    """
    serial = (serial or "").strip()
    owner = (owner or "").strip()
    if not serial:
        raise ValueError("acquire 需要设备 serial（空字符串会让所有设备共用一个租约文件）")
    if not owner:
        raise ValueError("acquire 需要 owner（空字符串会让排队的人看不出是谁占着设备）")
    try:
        ttl_value = float(ttl)
    except (TypeError, ValueError):
        ttl_value = DEFAULT_TTL
    if ttl_value <= 0:
        ttl_value = DEFAULT_TTL

    path = lease_path(serial)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
    queued = False

    while True:
        now = time.time()
        current = _load(path)

        # ① 没有可用租约：原子创建，抢到的就是我的。
        if current is None:
            if path.exists():
                # 文件在、但读不出记录（写了一半 / 手工写坏）：按「无可用记录」接管。
                # 否则一个坏文件会把这台设备永久挡在门外（所有人都卡在「已存在」）。
                taken, _victim = _takeover(
                    path, serial, owner, ttl_value, steal=False, allow_unparsable=True
                )
                if not taken:
                    continue  # 别人刚写好/刚删掉：回主循环重判
                fresh = _load(path) or _record(serial, owner, ttl_value)
                print(
                    f"[lease] 拿到设备 {serial} 的独占租约 owner={owner}"
                    "（原租约文件无可解析记录，已覆盖）",
                    flush=True,
                )
                return Lease(serial, owner, ttl_value, fresh, path=path, auto_heartbeat=auto_heartbeat)
            fresh = _record(serial, owner, ttl_value)
            if _create_exclusive(path, fresh):
                print(
                    f"[lease] 拿到设备 {serial} 的独占租约 owner={owner} ttl={ttl_value:.0f}s",
                    flush=True,
                )
                return Lease(serial, owner, ttl_value, fresh, path=path, auto_heartbeat=auto_heartbeat)
            time.sleep(0.01)  # 有人刚好在建：让他先落盘，下一轮按「有租约」处理
            continue

        # ② 本进程已经持有：重入续租，绝不自己等自己。
        if _same_holder(current, owner):
            latest = None
            with _mutex(path):
                latest = _load(path)
                if latest is not None and _same_holder(latest, owner):
                    latest["heartbeat"] = time.time()
                    _write(path, latest)
                else:
                    latest = None  # 刚好在这一瞬被别人接管/删除：回主循环重判
            if latest is None:
                continue
            print(
                f"[lease] 本进程已持有设备 {serial} 的租约（owner={owner}），续租，不重复占",
                flush=True,
            )
            return Lease(serial, owner, ttl_value, latest, path=path, reentrant=True)

        # ③ 活租约且不抢：排队（或按调用方的意愿直接报忙）。
        if _is_live(current, now, ttl_value) and not steal:
            if not wait:
                busy = LeaseBusy(serial, current, reason="wait=False")
                print(f"[lease] {busy}", flush=True)
                raise busy
            if deadline is not None and time.monotonic() >= deadline:
                busy = LeaseBusy(serial, current, reason=f"排队超时（{timeout}s）")
                print(f"[lease] {busy}", flush=True)
                raise busy
            if not queued:
                print(
                    f"[lease] 设备 {serial} 已被 {current.get('owner')}"
                    f"（pid={current.get('pid')} host={current.get('host')} "
                    f"since={fmt_ts(current.get('since'))}）占用，排队等待…",
                    flush=True,
                )
                queued = True
            time.sleep(_poll_delay(current, now, deadline))
            continue

        # ④ 过期 / steal：临界区里重判后接管。
        taken, victim = _takeover(path, serial, owner, ttl_value, steal=steal)
        if not taken:
            continue  # 别人抢先接管了；下一轮按活租约排队
        fresh = _load(path) or _record(serial, owner, ttl_value)
        if victim is None:
            print(
                f"[lease] 拿到设备 {serial} 的独占租约 owner={owner}"
                "（原租约文件无可解析记录，已覆盖）",
                flush=True,
            )
        elif steal:
            print(
                f"[lease] ★--steal 强抢设备 {serial}★：从 {victim.get('owner')}"
                f"（pid={victim.get('pid')} host={victim.get('host')} "
                f"since={fmt_ts(victim.get('since'))}）手里接管",
                flush=True,
            )
        else:
            print(
                f"[lease] ★接管过期租约★：设备 {serial} 原持有者 {victim.get('owner')}"
                f"（pid={victim.get('pid')} host={victim.get('host')}）心跳停在 "
                f"{fmt_ts(victim.get('heartbeat'))}，超过 ttl={ttl_value:.0f}s"
                f"（视为死锁），现在归 {owner}",
                flush=True,
            )
        return Lease(serial, owner, ttl_value, fresh, path=path, auto_heartbeat=auto_heartbeat)


# ---------------------------------------------------------------------------
# 模块级便捷口（只接受 Lease：串号无法判断「是谁的租约」，不给这种含糊入口）
# ---------------------------------------------------------------------------
def release(lease: Lease) -> bool:
    """放掉 ``lease``（等价于 ``lease.release()``）。"""
    if not isinstance(lease, Lease):
        raise TypeError("release() 只接受 acquire() 返回的 Lease（串号无法判断是谁的租约）")
    return lease.release()


def heartbeat(lease: Lease) -> dict:
    """续租 ``lease``（等价于 ``lease.heartbeat()``）。"""
    if not isinstance(lease, Lease):
        raise TypeError("heartbeat() 只接受 acquire() 返回的 Lease")
    return lease.heartbeat()


# ---------------------------------------------------------------------------
# 只读诊断
# ---------------------------------------------------------------------------
def read_lease(serial: str) -> dict | None:
    """读这台设备当前的租约记录（只读；没有/坏了 -> ``None``）。"""
    return _load(lease_path(serial))


def status(root: str | Path | None = None) -> list[dict]:
    """列出当前所有租约（含活/死与剩余秒数）。只读，不连设备、不改文件。"""
    base = Path(root) if root is not None else _root()
    rows: list[dict] = []
    if not base.is_dir():
        return rows
    for path in sorted(base.glob("*.json")):
        record = _load(path)
        record = record or {}
        rows.append(
            {
                "path": str(path),
                "serial": record.get("serial") or path.stem,
                "owner": record.get("owner"),
                "pid": record.get("pid"),
                "host": record.get("host"),
                "since": record.get("since"),
                "heartbeat": record.get("heartbeat"),
                "ttl": record.get("ttl"),
                "live": _is_live(record),
                "remaining": remaining_sec(record),
            }
        )
    return rows


def describe(serial: str) -> str:
    """一行摘要（日志 / 报错用）。"""
    record = read_lease(serial)
    if record is None:
        return f"设备 {serial}：无租约"
    state = "活" if _is_live(record) else "已过期"
    rem = remaining_sec(record)
    tail = f"，{rem:.0f}s 后过期" if rem is not None else ""
    return (
        f"设备 {serial}：{state} owner={record.get('owner')} pid={record.get('pid')} "
        f"host={record.get('host')} since={fmt_ts(record.get('since'))}"
        f" heartbeat={fmt_ts(record.get('heartbeat'))}{tail}"
    )


# ---------------------------------------------------------------------------
# CLI：诊断 + **申请/释放**（运维裁决 2026-10-17：子代理也可以拿真机，但必须走租约）
#
#   python tools/device_lease.py                       # 列出所有租约（只读）
#   python tools/device_lease.py <serial>              # 看某台（只读）
#   python tools/device_lease.py --serial S --acquire --owner agent:105 --ttl 600 --hold 1800
#       # 申请并长驻心跳（--hold 0 = 一直持有；Ctrl-C 或 --hold 到期即释放）
#   python tools/device_lease.py --serial S --release   # 释放（幂等）
#
# ★#114 更正★：**不要**后台起 --acquire --hold（会让所有内层 acquire 的脚本排队等死）。
#   每个进程自己 acquire / release（自动心跳）；--hold 只用于人工诊断，见模块 docstring。
# ---------------------------------------------------------------------------
def _parse_cli(args: list) -> dict:
    """极简参数解析（不引 argparse，保持本模块零第三方依赖）。"""
    out = {
        "serial": None,
        "acquire": False,
        "release": False,
        "owner": None,
        "ttl": 120.0,
        "hold": None,
        "steal": False,
        "no_wait": False,
        "rest": [],
    }
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--serial" and i + 1 < len(args):
            out["serial"] = args[i + 1]
            i += 2
        elif a == "--owner" and i + 1 < len(args):
            out["owner"] = args[i + 1]
            i += 2
        elif a == "--ttl" and i + 1 < len(args):
            out["ttl"] = float(args[i + 1])
            i += 2
        elif a == "--hold" and i + 1 < len(args):
            out["hold"] = float(args[i + 1])
            i += 2
        elif a == "--hold":
            out["hold"] = 0.0
            i += 1
        elif a == "--acquire":
            out["acquire"] = True
            i += 1
        elif a == "--release":
            out["release"] = True
            i += 1
        elif a == "--steal":
            out["steal"] = True
            i += 1
        elif a == "--no-wait":
            out["no_wait"] = True
            i += 1
        else:
            out["rest"].append(a)
            i += 1
    if out["serial"] is None and out["rest"]:
        out["serial"] = out["rest"][0]
    return out


def _cli_acquire(opts: dict) -> int:
    serial = opts["serial"]
    if not serial:
        print("--acquire 需要 --serial", flush=True)
        return 2
    owner = opts["owner"] or f"cli:{os.getpid()}"
    hold = opts["hold"]
    if hold is None:
        hold = 900.0  # 默认 15 分钟长驻（--hold 0 = 一直持有）
    try:
        lease = acquire(
            serial,
            owner,
            ttl=float(opts["ttl"]),
            steal=bool(opts["steal"]),
            wait=not bool(opts["no_wait"]),
        )
    except LeaseBusy as exc:
        print(f"✗ 设备 {serial} 已被占用：{exc}", flush=True)
        return 3
    print(f"✓ 已拿到 {serial}：owner={owner} ttl={opts['ttl']:.0f}s"
          + ("" if hold else "（长驻，Ctrl-C 释放）"), flush=True)
    deadline = (time.monotonic() + hold) if hold else None
    try:
        while True:
            time.sleep(max(1.0, float(opts["ttl"]) / 3.0))
            if not lease.heartbeat():
                print("★租约丢了（被 steal 或过期被接管）→ 退出★", flush=True)
                return 4
            if deadline is not None and time.monotonic() >= deadline:
                print(f"--hold {hold:.0f}s 到期 → 释放", flush=True)
                return 0
    except KeyboardInterrupt:
        print("收到 Ctrl-C → 释放", flush=True)
        return 0
    finally:
        lease.release()


def release_by_serial(serial: str, owner: str | None = None, *, force: bool = False) -> bool:
    """按 serial 释放租约（CLI 用）。

    * ``owner`` 给了且与记录不符 → 拒绝（打印持有者），除非 ``force=True``；
    * 返回是否真的删掉了。
    """
    record = read_lease(serial)
    if not record:
        return False
    holder = record.get("owner")
    if owner and holder != owner and not force:
        print(f"✗ {serial} 的持有者是 {holder!r}，不是你（{owner!r}）→ 拒绝释放；要强抢用 --steal 申请", flush=True)
        return False
    with contextlib.nullcontext():
        record2 = read_lease(serial)
        if not record2:
            return False
        try:
            lease_path(serial).unlink()
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    opts = _parse_cli(args) if any(x.startswith("--") for x in args) else None
    if opts is not None:
        if opts["acquire"]:
            return _cli_acquire(opts)
        if opts["release"]:
            serial = opts["serial"]
            if not serial:
                print("--release 需要 --serial", flush=True)
                return 2
            ok = release_by_serial(serial, opts["owner"])
            print(("✓ 已释放 " if ok else "（没有释放：无租约或持有者不符）") + str(serial), flush=True)
            return 0 if ok else 0
        if opts["serial"]:
            print(describe(opts["serial"]))
            return 0
    if args:
        for serial in args:
            print(describe(serial))
        return 0
    rows = status()
    if not rows:
        print(f"没有租约（目录 {_root()}）")
        return 0
    print(f"租约目录 {_root()}")
    for row in rows:
        rem = row["remaining"]
        state = "活 " if row["live"] else "过期"
        tail = f"{rem:7.1f}s" if rem is not None else "      ?s"
        print(
            f"  [{state}] {str(row['serial']):24} owner={row['owner']} "
            f"pid={row['pid']} host={row['host']} 剩余 {tail}"
        )
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
