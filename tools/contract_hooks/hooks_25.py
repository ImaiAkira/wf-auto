# -*- coding: utf-8 -*-
"""#25：真机 runner 必须把设备地址同步给 live_harness —— 收敛成【唯一入口】+ 死默认禁令。

seam：``tools/run_*live*.py`` / ``tools/run_pipeline.py``（地址的**调用方**）
    ↔ ``tools/live_harness.py::connect_device``（地址的**唯一来源**）。

背景（#13/#24）
---------------
真机 runner 亲手把地址交给 ``maa.controller.AdbController``，却没同步给
``live_harness.ADDRESS``。于是 ``AdbController`` 连的是真设备，而 ``live_harness.adb_tap``
（归位 / 点「未通关」等）仍打**模块级默认地址** ``127.0.0.1:16384`` —— 一个**早已不存在**
的端口。设备上看不到任何反馈，归位整段静默点到空设备上（#13 收尾 10 步全败的隐藏原因）。

``run_special_live.py`` 在 #24 手补了一行 ``ca.ADDRESS = a.address``，但 ``run_side_live.py``
（以及 ``run_pipeline.py``）仍是同样的漏接。**每漏一个 runner 就复发一次**，所以这张票不再
逐个手补，而是：

* 把「构造 AdbController + 连接 + 同步 ADDRESS + 登记 _ctrl_ref」收敛成 ``connect_device``
  —— 地址因此**只有一个来源**，runner 只要调它就不可能再漏；
* 取消 ``live_harness.ADDRESS`` 的硬编码默认；未登记时 ``_adb`` 立刻抛错（响亮失败，
  而不是静默打空端口）。

三个守卫（都在本文件里，prove-red 也在本文件里）：

1. ``live-runners-wire-harness-address`` —— 每个真机 runner 都经由
   ``live_harness.connect_device(...)`` 登记设备，且**不再**自己直接 ``AdbController(...)``
   （否则等于绕过唯一入口）。
2. ``live-runners-no-dead-default-address`` —— 任何 runner 都不得重新引入写死的
   ``127.0.0.1:16384``（只看**代码**，注释 / 文档字符串里提到它不算）。
3. ``harness-wires-address-from-device`` —— ``connect_device`` 确实把地址写进模块级
   ``ADDRESS``；``live_harness.ADDRESS`` 的模块默认不再是死端口；未登记地址时 ``_adb``
   必须拒绝执行。

★prove-red★（``python tools\\contract_hooks\\hooks_25.py``）：
   * 把某 runner 的 ``connect_device(...)`` 还原成「只给 AdbController、不同步地址」-> 守卫 1 红；
   * 往 runner 里塞回 ``DEFAULT_ADDRESS = "127.0.0.1:16384"`` -> 守卫 2 红；
   * 去掉 ``_require_address`` 的守卫 -> 守卫 3 红（空地址不再被拒）。
"""

from __future__ import annotations

import inspect
import io
import re
import shutil
import sys
import tempfile
import tokenize
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★（同 hooks_20/hooks_24）：prove-red 用 PYTHONPATH 抢先塞
# 坏副本时，副本仍优先命中，不被真实的 live_harness 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

#: 已确认不存在、绝不允许再写死的默认端口（#13/#24 的真凶）。
DEAD_ADDRESS = "127.0.0.1:16384"
#: 设备登记的唯一入口（tools/live_harness.py）。
FUNNEL = "connect_device"


# ---------------------------------------------------------------------------
# 只看「代码」：去掉注释与文档字符串（免得把解释 bug 的注释误判成写死地址）
# ---------------------------------------------------------------------------
def code_only(src: str) -> str:
    """返回去掉注释 / 文档字符串后的源码（字符串默认值等真实代码保留）。"""
    offsets = [0]
    for line in src.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    chars = list(src)

    def blank(tok: tokenize.TokenInfo) -> None:
        start = offsets[tok.start[0] - 1] + tok.start[1]
        end = offsets[tok.end[0] - 1] + tok.end[1]
        for i in range(start, min(end, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "

    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError):
        # 源不能完整 token 化：保守退回全文（宁严勿松）。
        return src

    prev_sig = None
    for tok in toks:
        t = tok.type
        if t == tokenize.COMMENT:
            blank(tok)
            continue
        if t == tokenize.STRING and prev_sig in (
            None,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.NL,
        ):
            # 语句开头单独一个字符串 = 文档字符串 / 裸字符串语句，忽略。
            blank(tok)
        if t not in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING):
            prev_sig = t
    return "".join(chars)


def _runner_files(tools_dir: Path = TOOLS_DIR) -> list[Path]:
    """需要登记设备的真机 runner：``run_*live*.py`` + ``run_pipeline.py``。

    与 hooks_20 的 selection 保持一致（同一批文件即同一批「真机 runner」）。
    """
    return [
        p
        for p in sorted(tools_dir.glob("run_*.py"))
        if "live" in p.stem or p.stem == "run_pipeline"
    ]


# ---------------------------------------------------------------------------
# 守卫 1：每个 runner 都走唯一登记入口，且不绕过它直接建 AdbController
# ---------------------------------------------------------------------------
def _runner_wiring_messages(tools_dir: Path = TOOLS_DIR) -> list[str]:
    msgs: list[str] = []
    files = _runner_files(tools_dir)
    if not files:
        return ["找不到任何 run_*live*.py / run_pipeline.py（守卫已与实现脱节）"]
    for path in files:
        code = code_only(path.read_text(encoding="utf-8"))
        if f"{FUNNEL}(" not in code:
            msgs.append(
                f"{path.name} 没有走 live_harness.{FUNNEL}(...) 登记设备地址"
                "（只把地址给了 AdbController 会让 adb_tap 打到空设备）"
            )
        if "AdbController(" in code:
            msgs.append(
                f"{path.name} 直接构造了 AdbController(...)，绕过唯一登记入口 "
                f"live_harness.{FUNNEL}(...)"
            )
    return msgs


def probe_live_runners_wire_harness_address(tools_dir: Path = TOOLS_DIR) -> bool:
    """#25 守卫 1：每个真机 runner 都经唯一入口登记设备（地址不可能再漏）。"""
    return _runner_wiring_messages(tools_dir) == []


# ---------------------------------------------------------------------------
# 守卫 2：任何 runner 都不得重新写死死默认地址
# ---------------------------------------------------------------------------
def _dead_default_messages(tools_dir: Path = TOOLS_DIR) -> list[str]:
    msgs: list[str] = []
    for path in _runner_files(tools_dir):
        code = code_only(path.read_text(encoding="utf-8"))
        if DEAD_ADDRESS in code:
            msgs.append(f"{path.name} 重新写死了已不存在的默认地址 {DEAD_ADDRESS}")
    return msgs


def probe_live_runners_no_dead_default_address(tools_dir: Path = TOOLS_DIR) -> bool:
    """#25 守卫 2：没有 runner 把已不存在的 127.0.0.1:16384 写回代码。"""
    return _dead_default_messages(tools_dir) == []


# ---------------------------------------------------------------------------
# 守卫 3：harness 自己就是唯一来源，且未登记地址时拒绝执行
# ---------------------------------------------------------------------------
_HARNESS_SRC = TOOLS_DIR / "live_harness.py"


def harness_address_default(source: str | None = None) -> str:
    """返回 ``live_harness.ADDRESS`` 模块级赋值的右侧文本（默认值的真源）。"""
    text = source if source is not None else _HARNESS_SRC.read_text(encoding="utf-8")
    m = re.search(r"^ADDRESS\s*=\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def probe_harness_wires_address_from_device() -> bool:
    """#25 守卫 3：connect_device 同步 ADDRESS；默认非死端口；未登记地址即报错。"""
    import live_harness as ca

    if not hasattr(ca, FUNNEL):
        return False
    if "ADDRESS" not in inspect.getsource(getattr(ca, FUNNEL)):
        return False
    if DEAD_ADDRESS in harness_address_default():
        return False

    old_address, old_adb = ca.ADDRESS, ca.ADB
    try:
        ca.ADDRESS = ""
        try:
            ca._adb("shell", "true")
        except RuntimeError:
            refused = True
        else:
            refused = False
    finally:
        ca.ADDRESS, ca.ADB = old_address, old_adb
    return refused


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_25.py`）
# ---------------------------------------------------------------------------
def _copy_runner_broken_wiring() -> Path:
    """复制 run_side_live.py，把 connect_device 还原成「只给 AdbController、不同步地址」。"""
    src = TOOLS_DIR / "run_side_live.py"
    text = src.read_text(encoding="utf-8")
    needle = "ca.connect_device(ca.ADB, a.address)"
    if needle not in text:
        raise RuntimeError(f"破坏点没找到：run_side_live.py 里没有 {needle!r}")
    legacy = (
        "AdbController(ca.ADB, a.address)\n"
        "    ctrl.post_connection().wait()\n"
        "    ca._ctrl_ref['ctrl'] = ctrl  # 故意漏掉 ca.ADDRESS 同步（复现 #13/#24）"
    )
    tmpdir = Path(tempfile.mkdtemp(prefix="wf_hook25_wire_"))
    dst = tmpdir / src.name
    dst.write_text(text.replace(needle, legacy), encoding="utf-8")
    return dst


def _copy_runner_dead_default() -> Path:
    """复制 run_side_live.py，塞回写死的死默认地址。"""
    src = TOOLS_DIR / "run_side_live.py"
    text = src.read_text(encoding="utf-8")
    tmpdir = Path(tempfile.mkdtemp(prefix="wf_hook25_dead_"))
    dst = tmpdir / src.name
    dst.write_text(
        text + f'\nDEFAULT_ADDRESS = "{DEAD_ADDRESS}"  # 故意写回死端口\n',
        encoding="utf-8",
    )
    return dst


def _prove_red_harness() -> tuple[bool, bool]:
    """去掉 _require_address 守卫后，空地址不再被拒（守卫 3 变红）。"""
    import live_harness as ca

    real_ok = probe_harness_wires_address_from_device() is True

    saved_require, saved_address = ca._require_address, ca.ADDRESS
    try:
        ca._require_address = lambda address: address  # 摘掉守卫
        ca.ADDRESS = ""
        try:
            ca._adb("shell", "true")
        except RuntimeError:
            red = False  # 仍被拒 —— 不该发生（说明守卫不在 _require_address 上）
        except Exception:
            red = True  # 走到了 subprocess —— 空地址不再被拒
        else:
            red = True  # 竟然直接执行了 —— 空地址不再被拒
    finally:
        ca._require_address, ca.ADDRESS = saved_require, saved_address
    return real_ok, red


def prove_red() -> bool:
    """真实绿；三处破坏，要求三个守卫各自变红。"""
    print("hooks_25 prove-red：三处破坏，要求三个守卫各自变红")
    green = (
        probe_live_runners_wire_harness_address() is True
        and probe_live_runners_no_dead_default_address() is True
        and probe_harness_wires_address_from_device() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：runner 走唯一入口 + 无死默认 + harness 拒绝空地址（绿）")
    if not green:
        return False

    # (a) 还原「只给 AdbController、不同步地址」-> 守卫 1 红。
    broken = _copy_runner_broken_wiring()
    try:
        msgs = _runner_wiring_messages(broken.parent)
        red_wire = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_wire else 'FAIL'}] 漏同步地址（还原旧写法）-> {'红' if red_wire else '仍绿'}{tail}")
    finally:
        shutil.rmtree(broken.parent, ignore_errors=True)

    # (b) 塞回死默认地址 -> 守卫 2 红。
    dead = _copy_runner_dead_default()
    try:
        msgs2 = _dead_default_messages(dead.parent)
        red_dead = len(msgs2) > 0
        tail2 = f"  {msgs2[0]}" if msgs2 else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_dead else 'FAIL'}] 写回死默认地址 {DEAD_ADDRESS} -> {'红' if red_dead else '仍绿'}{tail2}")
    finally:
        shutil.rmtree(dead.parent, ignore_errors=True)

    # (c) 摘掉 _require_address -> 守卫 3 红。
    real_ok, red_harness = _prove_red_harness()
    print(f"  [{'PASS' if real_ok and red_harness else 'FAIL'}] 摘掉空地址守卫 -> "
          f"{'红' if red_harness else '仍绿'}（真实绿={real_ok}）")

    ok = green and red_wire and red_dead and red_harness
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "live-runners-wire-harness-address",
        "#25",
        "每个真机 runner 都经 live_harness.connect_device(...) 登记设备地址（缺一即红）",
        probe_live_runners_wire_harness_address,
    ),
    (
        "live-runners-no-dead-default-address",
        "#25",
        "没有 runner 把已不存在的默认地址 127.0.0.1:16384 写回代码",
        probe_live_runners_no_dead_default_address,
    ),
    (
        "harness-wires-address-from-device",
        "#25",
        "connect_device 把地址写进模块级 ADDRESS；默认不再是死端口；未登记地址即报错",
        probe_harness_wires_address_from_device,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
