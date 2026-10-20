# -*- coding: utf-8 -*-
"""离线单测：#25 真机 runner 的设备地址同步（唯一入口 + 死默认禁令）。

不需要游戏 / 设备；默认连 maa 运行时都不需要（只做源码审计 + 纯函数 + 假 controller）。

直接跑::

    .venv\\Scripts\\python.exe tools\\test_live_address.py

覆盖 #25 的验收：

  1. **缺口审计**：逐个真机 runner 打印「是否走唯一入口 / 是否写死死默认」，断言全部干净；
     ``run_side_live.py`` 正是本轮修好的那个（#24 只补了 ``run_special_live.py``）；
  2. **旧写法复现**：把 ``connect_device`` 还原成「只给 AdbController、不同步 ADDRESS」，
     守卫 1 必须变红；塞回 ``127.0.0.1:16384``，守卫 2 必须变红；
  3. **唯一入口行为**（假 AdbController，无需设备）：``connect_device`` 把地址同步进
     ``ADDRESS`` 并登记 ``_ctrl_ref``；未登记地址时 ``_adb`` 拒绝执行（不静默打空端口）；
  4. **代码 vs 注释**：解释 bug 的注释里出现死端口不算违规，代码里出现才算；
  5. **挂点** ``hooks_25`` 已点亮（三个守卫都 True）、prove-red 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_25.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_25  # noqa: E402
import live_harness as ca  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 1. 缺口审计
# ---------------------------------------------------------------------------
def test_runner_audit() -> None:
    print("\n== 1. 真机 runner 地址同步审计 ==")
    files = hooks_25._runner_files()
    check("找到真机 runner（run_*live*.py + run_pipeline.py）", len(files) > 0,
          f"{[p.name for p in files]}")
    for path in files:
        code = hooks_25.code_only(path.read_text(encoding="utf-8"))
        wires = f"{hooks_25.FUNNEL}(" in code
        direct = "AdbController(" in code
        dead = hooks_25.DEAD_ADDRESS in code
        print(f"  - {path.name:28} connect_device={wires!s:5} direct_AdbController={direct!s:5} dead_default={dead!s:5}")
        check(f"{path.name} 走唯一登记入口", wires)
        check(f"{path.name} 不绕过入口直建 AdbController", not direct)
        check(f"{path.name} 无死默认地址", not dead)

    side = (TOOLS_DIR / "run_side_live.py").read_text(encoding="utf-8")
    check("run_side_live 是走 connect_device 的（本轮修好）", "ca.connect_device(" in side)
    check("run_side_live 不再有 #24 那半截手补 ca.ADDRESS = a.address",
          "ca.ADDRESS = a.address" not in side)


# ---------------------------------------------------------------------------
# 2. 旧写法复现（守卫必须红）
# ---------------------------------------------------------------------------
def test_gap_repro() -> None:
    print("\n== 2. 旧写法复现：漏同步地址 / 写回死默认，守卫必须变红 ==")
    broken = hooks_25._copy_runner_broken_wiring()
    try:
        msgs = hooks_25._runner_wiring_messages(broken.parent)
        check("漏同步地址 -> 守卫 1 red", len(msgs) > 0, (msgs[0] if msgs else "守卫没抓到！"))
    finally:
        import shutil

        shutil.rmtree(broken.parent, ignore_errors=True)

    dead = hooks_25._copy_runner_dead_default()
    try:
        msgs = hooks_25._dead_default_messages(dead.parent)
        check("写回死默认 -> 守卫 2 red", len(msgs) > 0, (msgs[0] if msgs else "守卫没抓到！"))
    finally:
        import shutil

        shutil.rmtree(dead.parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. 唯一入口行为（假 AdbController，无需设备）
# ---------------------------------------------------------------------------
class _FakeJob:
    def __init__(self, ok: bool) -> None:
        self.succeeded = ok

    def wait(self) -> "_FakeJob":
        return self


class _FakeCtrl:
    def __init__(self, adb: str, address: str) -> None:
        self.adb = adb
        self.address = address
        self.connected = True

    def post_connection(self) -> _FakeJob:
        return _FakeJob(True)


def test_connect_device_wires_address() -> None:
    print("\n== 3. connect_device 行为（假 controller）：地址进 ADDRESS + _ctrl_ref ==")
    saved = (ca.AdbController, ca.ADB, ca.ADDRESS, ca._ctrl_ref.get("ctrl"))
    try:
        ca.AdbController = _FakeCtrl  # type: ignore[assignment]
        ctrl = ca.connect_device("fake-adb", "9.9.9.9:9999")
        check("connect_device 返回 controller", isinstance(ctrl, _FakeCtrl))
        check("connect_device 把地址写进模块级 ADDRESS", ca.ADDRESS == "9.9.9.9:9999",
              f"ADDRESS={ca.ADDRESS!r}")
        check("connect_device 登记 _ctrl_ref['ctrl']", ca._ctrl_ref.get("ctrl") is ctrl)
        check("connect_device 同步 adb 路径", ca.ADB == "fake-adb", f"ADB={ca.ADB!r}")
    finally:
        ca.AdbController, ca.ADB, ca.ADDRESS = saved[0], saved[1], saved[2]  # type: ignore[assignment]
        ca._ctrl_ref["ctrl"] = saved[3]


def test_refuses_unwired_address() -> None:
    print("\n== 3b. 未登记地址：_adb 拒绝执行（不静默打空端口） ==")
    check("_require_address('') 抛 RuntimeError", _raises_runtime(ca._require_address, ""))
    check("_require_address('h:p') 原样返回", ca._require_address("1.2.3.4:5") == "1.2.3.4:5")
    old = ca.ADDRESS
    try:
        ca.ADDRESS = ""
        check("_adb 在空地址下抛 RuntimeError", _raises_runtime(ca._adb, "shell", "true"))
    finally:
        ca.ADDRESS = old


def _raises_runtime(fn, *args) -> bool:
    try:
        fn(*args)
    except RuntimeError:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# 4. 代码 vs 注释
# ---------------------------------------------------------------------------
def test_code_only_strips_comments_and_docstrings() -> None:
    print("\n== 4. 死默认扫描只看代码（注释/文档字符串不算） ==")
    code = hooks_25.code_only(
        '"""doc 127.0.0.1:16384"""\n'
        "# comment 127.0.0.1:16384\n"
        'DEFAULT = "127.0.0.1:16384"\n'
    )
    check("注释里的死端口被忽略", code.count("# comment") == 0)
    check("代码字符串里的死端口仍可见", hooks_25.DEAD_ADDRESS in code)
    check("harness 的 ADDRESS 默认不是死端口",
          hooks_25.DEAD_ADDRESS not in hooks_25.harness_address_default())
    check("harness ADDRESS 默认留空（由 connect_device 写入）",
          hooks_25.harness_address_default() == 'os.environ.get("WF_LIVE_ADDRESS", "")',
          hooks_25.harness_address_default())


# ---------------------------------------------------------------------------
# 5. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 5. 挂点点亮 + prove-red ==")
    check("挂点 live-runners-wire-harness-address 已点亮",
          hooks_25.probe_live_runners_wire_harness_address() is True)
    check("挂点 live-runners-no-dead-default-address 已点亮",
          hooks_25.probe_live_runners_no_dead_default_address() is True)
    check("挂点 harness-wires-address-from-device 已点亮",
          hooks_25.probe_harness_wires_address_from_device() is True)
    check("hooks_25.prove_red() 成立（三处破坏各自变红）", hooks_25.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 72)
    print("离线单测：#25 真机 runner 设备地址同步（唯一登记入口 + 死默认禁令）")
    print("=" * 72)
    test_runner_audit()
    test_gap_repro()
    test_connect_device_wires_address()
    test_refuses_unwired_address()
    test_code_only_strips_comments_and_docstrings()
    test_hooks_and_prove_red()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
