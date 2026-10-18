# -*- coding: utf-8 -*-
"""离线单测：#104 / D9 设备**独占租约**（``tools/device_lease.py``）。

不连设备、不跑 adb、**不碰 ``debug/``**：每个用例把 ``device_lease.LEASE_ROOT`` 指到一个
临时目录（``tempfile.mkdtemp``），跑完删掉。所以本文件在裸 checkout 上也能绿。

覆盖（D9 的每一条语义都有实测）：

  1. **路径与记录**：``127.0.0.1:16384`` -> ``127.0.0.1_16384.json``；记录字段
     owner/pid/host/since/heartbeat（+ ttl/serial）；
  2. **独占**：活租约 + ``wait=False`` -> :class:`LeaseBusy`（带 owner/pid/since），
     且租约文件**一个字都没变**；
  3. **排队**：另一个 owner 在 ``wait=True`` 下必须等到 release 才拿到（实测挂钟耗时），
     接手后文件里的 owner 换成新人；
  4. **跨进程**：子进程 ``acquire(wait=False)`` 必须报忙（父进程持有时），父进程 release 后
     子进程能立刻拿到 —— 证明这是**真·跨进程**独占，不是进程内锁；
  5. **过期接管**：心跳超 ``ttl`` -> 可接管，且**必须打印**「接管过期租约」；
     ``ttl`` 以**记录里的**为准（持有者用 ttl=120 续租时，ttl=5 的等待者不许抢活租约）；
  6. **steal**：强抢**活**租约并打印被抢者；被抢者的 ``heartbeat()`` 抛 :class:`LeaseLost`，
     它的 ``release()`` 绝不删新持有者的租约；
  7. **续租**：``heartbeat()`` 刷新后不再过期；
  8. **释放**：删文件、幂等、``with`` 块里异常也释放、``atexit`` 回调也能释放；
  9. **重入**：同 owner + 同 pid 第二次 ``acquire`` 不排队、不重复占，且它的 ``release``
     是 no-op（否则 ``live_harness.connect_device`` 会被自己等死）；
 10. **容错**：坏 JSON 视为可接管（否则一个坏文件永久挡门）；``timeout`` 到点抛 LeaseBusy；
 11. **诊断**：``status()`` / ``describe()`` 只读且能报活/死；
 12. **挂点**：``hooks_104`` 的探针全绿 + ``prove_red()`` 成立。

跑法::

    .venv\\Scripts\\python.exe tools\\test_device_lease.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
REPO_ROOT = TOOLS_DIR.parent
for _p in (str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import device_lease as dl  # noqa: E402
import hooks_104  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []
#: 模块 import 时就记下真目录：跑完必须还原，绝不让测试把租约写进 ``debug/``。
_REAL_ROOT = dl.LEASE_ROOT


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


@contextlib.contextmanager
def temp_root():
    """把租约根指到临时目录（跑完还原 + 删干净）：测试绝不污染 ``debug/``。"""
    root = Path(tempfile.mkdtemp(prefix="wf_lease_test_"))
    saved = dl.LEASE_ROOT
    dl.LEASE_ROOT = root
    try:
        yield root
    finally:
        dl.LEASE_ROOT = saved
        shutil.rmtree(root, ignore_errors=True)


def quiet():
    """吞掉 acquire/release 的正常打印（要断言打印的用例单独用 capture）。"""
    return contextlib.redirect_stdout(io.StringIO())


def capture():
    """把 stdout 收进缓冲（断言「必须打印」的那些话）。"""
    return contextlib.redirect_stdout(io.StringIO())


# ---------------------------------------------------------------------------
# 1. 路径与记录
# ---------------------------------------------------------------------------
def test_path_and_record() -> None:
    print("\n== 1. 路径与记录：serial 安全化 + 五个必备字段 ==")
    check("serial 里的 : 换成 _", dl.serial_key("127.0.0.1:16384") == "127.0.0.1_16384")
    check("emulator-5554 原样（本来就安全）", dl.serial_key("emulator-5554") == "emulator-5554")
    check("空 serial 退化成 unknown（绝不生成 '.json' 这种共用文件）",
          dl.serial_key("  ") == "unknown")
    check("路径分隔符也被安全化（不可能跳出租约目录）",
          "/" not in dl.serial_key("a/b\\c:d") and "\\" not in dl.serial_key("a/b\\c:d"))
    check("默认根目录是 debug/.device_lease",
          _REAL_ROOT.as_posix().endswith("debug/.device_lease"), str(_REAL_ROOT))

    with temp_root() as root:
        with quiet():
            lease = dl.acquire("127.0.0.1:16384", "runner:1", ttl=60)
        try:
            path = lease.path
            check("落在 <root>/127.0.0.1_16384.json", path == root / "127.0.0.1_16384.json", str(path))
            record = json.loads(path.read_text(encoding="utf-8"))
            for key in ("owner", "pid", "host", "since", "heartbeat"):
                check(f"记录里有 {key}", key in record, f"{key}={record.get(key)!r}")
            check("owner 就是传进去的", record["owner"] == "runner:1")
            check("pid 就是本进程", record["pid"] == os.getpid())
            check("since <= heartbeat（刚拿到时相等）",
                  float(record["since"]) <= float(record["heartbeat"]))
            check("host 非空（两台机器抢同一台设备时看得出是谁）", bool(record["host"]))
        finally:
            with quiet():
                lease.release()
        check("release 后文件消失", not (root / "127.0.0.1_16384.json").exists())


# ---------------------------------------------------------------------------
# 2. 独占：活租约 + wait=False -> LeaseBusy
# ---------------------------------------------------------------------------
def test_exclusive_rejects_immediately() -> None:
    print("\n== 2. 独占：活租约 + wait=False -> LeaseBusy（带 owner/pid/since） ==")
    with temp_root():
        with quiet():
            holder = dl.acquire("emulator-5554", "ops-gui", ttl=60)
        try:
            path = holder.path
            before = path.read_bytes()
            busy = None
            try:
                with quiet():
                    dl.acquire("emulator-5554", "runner:2", ttl=60, wait=False)
            except dl.LeaseBusy as exc:
                busy = exc
            check("第二个 acquire(wait=False) 抛 LeaseBusy", busy is not None)
            check("LeaseBusy.owner = 持有者", busy is not None and busy.owner == "ops-gui")
            check("LeaseBusy.pid = 持有者 pid", busy is not None and busy.pid == os.getpid())
            check("LeaseBusy.since 非空（排队的人看得出占了多久）", busy is not None and busy.since)
            check("报错文本里带持有者信息",
                  busy is not None and "ops-gui" in str(busy), str(busy))
            check("被拒时租约文件一个字都没变（绝不误覆盖）", path.read_bytes() == before)
        finally:
            with quiet():
                holder.release()


# ---------------------------------------------------------------------------
# 3. 排队：wait=True 必须等到 release 才拿到
# ---------------------------------------------------------------------------
def test_queue_waits_for_release() -> None:
    print("\n== 3. 排队：wait=True 等到 release 才拿到（实测挂钟） ==")
    with temp_root():
        HOLD = 0.7
        with quiet():
            holder = dl.acquire("127.0.0.1:16448", "runner:1", ttl=60)
        result: dict = {}

        def waiter() -> None:
            try:
                started = time.monotonic()
                with quiet():
                    lease = dl.acquire("127.0.0.1:16448", "runner:2", ttl=60, wait=True)
                result["waited"] = time.monotonic() - started
                result["lease"] = lease
                result["owner"] = dl.read_lease("127.0.0.1:16448")["owner"]
            except BaseException as exc:  # noqa: BLE001 -- 线程里的异常要带回主线程判
                result["error"] = repr(exc)

        thread = threading.Thread(target=waiter, name="lease-waiter")
        thread.start()
        time.sleep(HOLD)
        check("等待期间租约还在持有者手里（没被抢）",
              dl.read_lease("127.0.0.1:16448")["owner"] == "runner:1")
        with quiet():
            holder.release()
        thread.join(timeout=5.0)
        check("等待线程拿到了租约（没有死等）", "lease" in result, result.get("error", ""))
        check(f"确实等了 >= {HOLD - 0.1:.1f}s（真排队，不是立刻抢）",
              result.get("waited", 0.0) >= HOLD - 0.1, f"waited={result.get('waited', 0.0):.2f}s")
        check("接手后文件里的 owner 换成新人", result.get("owner") == "runner:2")
        with quiet():
            result["lease"].release()


# ---------------------------------------------------------------------------
# 4. 跨进程：子进程必须报忙；父进程放手后能拿到
# ---------------------------------------------------------------------------
_CHILD_CODE = """
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ["WF_LEASE_TOOLS"])
import device_lease as dl
dl.LEASE_ROOT = Path(os.environ["WF_LEASE_TEST_ROOT"])
serial, owner = sys.argv[1], sys.argv[2]
try:
    lease = dl.acquire(serial, owner, ttl=60, wait=False)
except dl.LeaseBusy as exc:
    print("CHILD_BUSY", exc.owner, exc.pid)
else:
    print("CHILD_ACQUIRED")
    lease.release()
"""


def _run_child(serial: str, owner: str, root: Path) -> str:
    env = dict(os.environ)
    env["WF_LEASE_TOOLS"] = str(TOOLS_DIR)
    env["WF_LEASE_TEST_ROOT"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_CODE, serial, owner],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    return (proc.stdout or "") + (proc.stderr or "")


def test_cross_process_exclusive() -> None:
    print("\n== 4. 跨进程：子进程 acquire(wait=False) -> 报忙；父进程放手后 -> 拿到 ==")
    with temp_root() as root:
        with quiet():
            holder = dl.acquire("127.0.0.1:16384", "runner:parent", ttl=60)
        try:
            busy_out = _run_child("127.0.0.1:16384", "runner:child", root)
            check("子进程报 CHILD_BUSY（真·跨进程独占）", "CHILD_BUSY" in busy_out, busy_out.strip()[:120])
            check("子进程看到的持有者是父进程",
                  "runner:parent" in busy_out and str(os.getpid()) in busy_out,
                  busy_out.strip()[:120])
        finally:
            with quiet():
                holder.release()
        free_out = _run_child("127.0.0.1:16384", "runner:child", root)
        check("父进程 release 后子进程立刻拿到", "CHILD_ACQUIRED" in free_out, free_out.strip()[:120])
        check("子进程也在 release 后把文件删了", not dl.lease_path("127.0.0.1:16384").exists())


# ---------------------------------------------------------------------------
# 5. 过期接管（必须打印「接管过期租约」）
# ---------------------------------------------------------------------------
def _write_stale(serial: str, owner: str, *, ttl: float, age: float) -> Path:
    """手写一份「心跳停在 age 秒前」的租约（模拟持有者被 taskkill / 断电）。"""
    path = dl.lease_path(serial)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    path.write_text(
        json.dumps(
            {
                "owner": owner,
                "pid": 424242,
                "host": "dead-box",
                "since": now - age - 30,
                "heartbeat": now - age,
                "ttl": ttl,
                "serial": serial,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_expired_takeover() -> None:
    print("\n== 5. 过期接管：心跳 > ttl 视为死锁，接管且必须打印 ==")
    with temp_root():
        _write_stale("emulator-5554", "dead-runner", ttl=5.0, age=60.0)
        check("过期租约不报忙（能接管）", not dl._is_live(dl.read_lease("emulator-5554")))
        buffer = io.StringIO()
        lease = None
        try:
            with contextlib.redirect_stdout(buffer):
                lease = dl.acquire("emulator-5554", "runner:alive", ttl=60)
            printed = buffer.getvalue()
            check("接管成功", dl.read_lease("emulator-5554")["owner"] == "runner:alive")
            check("打印了「接管过期租约」（不许静默抢）", "接管过期租约" in printed, printed.strip()[:160])
            check("打印里带原持有者（谁被接管了要能追溯）",
                  "dead-runner" in printed and "424242" in printed)
        finally:
            if lease is not None:
                with quiet():
                    lease.release()

        # ttl 以【记录里的】为准：持有者用 ttl=120 续租，用 ttl=5 的等待者不许抢活租约。
        _write_stale("emulator-5554", "slow-heartbeat", ttl=120.0, age=10.0)
        busy = None
        try:
            with quiet():
                dl.acquire("emulator-5554", "runner:impatient", ttl=5.0, wait=False)
        except dl.LeaseBusy as exc:
            busy = exc
        check("ttl 以记录里的为准（ttl=5 的等待者不抢 ttl=120 的活租约）", busy is not None)

        # 过期但调用方不想等：接管照旧（过期 = 没人在用）。
        _write_stale("emulator-5554", "dead-runner", ttl=5.0, age=300.0)
        with quiet():
            lease = dl.acquire("emulator-5554", "runner:takeover", ttl=60, wait=False)
        check("过期租约 + wait=False 也能立刻接管",
              lease is not None and dl.read_lease("emulator-5554")["owner"] == "runner:takeover")
        with quiet():
            lease.release()


# ---------------------------------------------------------------------------
# 6. steal：强抢活租约
# ---------------------------------------------------------------------------
def test_steal() -> None:
    print("\n== 6. steal：强抢活租约，打印被抢者；被抢者不能删新租约 ==")
    with temp_root():
        with quiet():
            victim = dl.acquire("127.0.0.1:16384", "ops-gui", ttl=60)
        buffer = io.StringIO()
        thief = None
        try:
            with contextlib.redirect_stdout(buffer):
                thief = dl.acquire("127.0.0.1:16384", "runner:steal", ttl=60, steal=True)
            printed = buffer.getvalue()
            check("steal 抢到了活租约", dl.read_lease("127.0.0.1:16384")["owner"] == "runner:steal")
            check("打印了被抢者", "ops-gui" in printed and "steal" in printed, printed.strip()[:160])
            check("被抢者 is_mine() 变假", victim.is_mine() is False)

            lost = None
            try:
                with quiet():
                    victim.heartbeat()
            except dl.LeaseLost as exc:
                lost = exc
            check("被抢者 heartbeat() 抛 LeaseLost（不再假装修租成功）", lost is not None)

            deleted = None
            with quiet():
                deleted = victim.release()
            check("被抢者 release() 不删新持有者的租约",
                  deleted is False and dl.read_lease("127.0.0.1:16384")["owner"] == "runner:steal")
        finally:
            if thief is not None:
                with quiet():
                    thief.release()


# ---------------------------------------------------------------------------
# 7. 续租
# ---------------------------------------------------------------------------
def test_heartbeat_renews() -> None:
    print("\n== 7. 续租：heartbeat() 刷新后不再过期 ==")
    with temp_root():
        with quiet():
            lease = dl.acquire("emulator-5554", "runner:1", ttl=0.6)
        try:
            first = dl.read_lease("emulator-5554")["heartbeat"]
            time.sleep(0.15)
            with quiet():
                renewed = lease.heartbeat()
            check("heartbeat 记录被刷新", float(renewed["heartbeat"]) > float(first))
            check("since 不因续租而变（开始时间要稳定）",
                  float(renewed["since"]) == float(dl.read_lease("emulator-5554")["since"]))
            time.sleep(0.35)  # 距上次心跳 0.35s < ttl 0.6s：还活着
            check("刚续过租 -> 仍算活（别人必须排队）", dl._is_live(dl.read_lease("emulator-5554")))
            busy = None
            try:
                with quiet():
                    dl.acquire("emulator-5554", "runner:2", ttl=0.6, wait=False)
            except dl.LeaseBusy:
                busy = True
            check("续租过的租约抢不走", busy is True)
        finally:
            with quiet():
                lease.release()


# ---------------------------------------------------------------------------
# 8. 释放：幂等 / with / atexit
# ---------------------------------------------------------------------------
def test_release_paths() -> None:
    print("\n== 8. 释放：幂等 + with 异常也释放 + atexit 回调 ==")
    with temp_root():
        # 幂等
        with quiet():
            lease = dl.acquire("emulator-5554", "runner:1", ttl=60)
            check("第一次 release 返回 True", lease.release() is True)
            check("第二次 release 返回 False（幂等，不抛）", lease.release() is False)
        check("文件已删", not lease.path.exists())

        # with：块里抛异常也必须释放（这是 runner 的 try/finally 保证）
        with quiet():
            ctx = dl.acquire("emulator-5554", "runner:ctx", ttl=60)
        raised = False
        try:
            with quiet():
                with ctx as entered:
                    check("with 返回 Lease 本身", isinstance(entered, dl.Lease))
                    raise RuntimeError("模拟 runner 中途炸掉")
        except RuntimeError:
            raised = True
        check("块内异常照旧传播（不吞）", raised)
        check("异常退出也释放了租约", not ctx.path.exists())

        # atexit 回调：进程退出路径（模拟，直接调回调）
        with quiet():
            dying = dl.acquire("127.0.0.1:16448", "runner:dying", ttl=60)
        check("atexit 前文件在", dying.path.exists())
        dying._release_at_exit()
        check("atexit 路径释放了租约（崩溃/被杀的最后一道）", not dying.path.exists())
        dying._release_at_exit()  # 再调一次：解释器收尾阶段重复调用也绝不抛
        check("atexit 回调重复调用不抛", True)


# ---------------------------------------------------------------------------
# 9. 重入（否则 live_harness 会自己等自己）
# ---------------------------------------------------------------------------
def test_reentrant_same_process() -> None:
    print("\n== 9. 重入：同 owner+pid 不排队、不重复占 ==")
    with temp_root():
        with quiet():
            first = dl.acquire("emulator-5554", "runner:1", ttl=60)
        started = time.monotonic()
        with quiet():
            second = dl.acquire("emulator-5554", "runner:1", ttl=60, wait=True)
        elapsed = time.monotonic() - started
        try:
            check("同进程同 owner 立刻返回（不排队）", elapsed < 0.3, f"elapsed={elapsed:.2f}s")
            check("第二次被标为 reentrant", second.reentrant is True)
            check("文件 owner 没变", dl.read_lease("emulator-5554")["owner"] == "runner:1")
            with quiet():
                check("重入 Lease 的 release 是 no-op", second.release() is False)
            check("重入 release 之后真租约还在", dl.read_lease("emulator-5554") is not None)
        finally:
            with quiet():
                first.release()
        check("真正持有者释放后才删文件", not dl.lease_path("emulator-5554").exists())


# ---------------------------------------------------------------------------
# 10. 容错：坏 JSON / 排队超时
# ---------------------------------------------------------------------------
def test_tolerance() -> None:
    print("\n== 10. 容错：坏 JSON 可接管；timeout 到点抛 LeaseBusy ==")
    with temp_root():
        path = dl.lease_path("emulator-5554")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ 半个 json", encoding="utf-8")
        buffer = io.StringIO()
        lease = None
        try:
            with contextlib.redirect_stdout(buffer):
                lease = dl.acquire("emulator-5554", "runner:1", ttl=60, wait=False)
            check("坏 JSON 被当成「无可用记录」接管（不会永久挡门）",
                  dl.read_lease("emulator-5554")["owner"] == "runner:1")
            check("打印了原因（取证线索不丢）",
                  "无可解析记录" in buffer.getvalue(), buffer.getvalue().strip()[:120])
        finally:
            if lease is not None:
                with quiet():
                    lease.release()

        # 排队超时：持有者不放，timeout=0.4 -> LeaseBusy（不许无限等）
        with quiet():
            holder = dl.acquire("emulator-5554", "runner:1", ttl=60)
        try:
            busy = None
            started = time.monotonic()
            try:
                with quiet():
                    dl.acquire("emulator-5554", "runner:2", ttl=60, wait=True, timeout=0.4)
            except dl.LeaseBusy as exc:
                busy = exc
            waited = time.monotonic() - started
            check("timeout 到点抛 LeaseBusy", busy is not None)
            check("确实等到了 timeout 附近（>= 0.3s）", waited >= 0.3, f"waited={waited:.2f}s")
            check("超时报错里说明是排队超时",
                  busy is not None and "超时" in str(busy), str(busy)[:120])
        finally:
            with quiet():
                holder.release()


# ---------------------------------------------------------------------------
# 11. 只读诊断
# ---------------------------------------------------------------------------
def test_status_readonly() -> None:
    print("\n== 11. 诊断：status()/describe() 只读且能报活/死 ==")
    with temp_root():
        with quiet():
            lease = dl.acquire("emulator-5554", "runner:1", ttl=60)
        _write_stale("127.0.0.1:16384", "dead-runner", ttl=5.0, age=600.0)
        try:
            rows = dl.status()
            check("status 列出两份租约", len(rows) == 2, f"{[r['serial'] for r in rows]}")
            live = [r for r in rows if r["serial"] == "emulator-5554"]
            dead = [r for r in rows if r["serial"] == "127.0.0.1:16384"]
            check("活租约报 live=True", bool(live) and live[0]["live"] is True)
            check("过期租约报 live=False", bool(dead) and dead[0]["live"] is False)
            check("status 不删不改文件（只读）", lease.path.exists())
            text = dl.describe("127.0.0.1:16384")
            check("describe 报「已过期」+ 原持有者",
                  "已过期" in text and "dead-runner" in text, text)
            check("describe 对没租约的设备也不抛", "无租约" in dl.describe("nope:1"))
        finally:
            with quiet():
                lease.release()


# ---------------------------------------------------------------------------
# 12. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 12. 挂点 hooks_104 点亮 + prove-red 成立 ==")
    check("挂点 lease-exclusive-queue 绿", hooks_104.probe_lease_exclusive_queue() is True)
    check("挂点 lease-expiry-and-steal 绿", hooks_104.probe_lease_expiry_and_steal() is True)
    check("挂点 lease-wired-into-harness 绿", hooks_104.probe_lease_wired_into_harness() is True)
    check("hooks_104.prove_red() 成立（3 处破坏各自变红）", hooks_104.prove_red() is True)


def main() -> int:
    print("=" * 72)
    print("离线单测：#104 / D9 设备独占租约（独占 / 排队 / 过期接管 / steal / 接线）")
    print("=" * 72)
    test_path_and_record()
    test_exclusive_rejects_immediately()
    test_queue_waits_for_release()
    test_cross_process_exclusive()
    test_expired_takeover()
    test_steal()
    test_heartbeat_renews()
    test_release_paths()
    test_reentrant_same_process()
    test_tolerance()
    test_status_readonly()
    test_hooks_and_prove_red()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
