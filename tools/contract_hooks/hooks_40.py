# -*- coding: utf-8 -*-
"""#40：设备地址不得写死端口 —— 按【账号身份】发现 + 连接身份守卫。

seam：``tools/{live_harness,run_*live*,run_pipeline,auto_stage,probe,live_check}.py``
      ——  addr 的**唯一真源**是 ``tools/live_harness.py``（身份发现 + 身份守卫）。

背景（#40 真机实证）
-------------------
MUMA 实例会重编号，**端口会漂移**：任务书里假设的某个端口扫描首日已消失，而回归的端口上
正是同一台测试账号（机型 ``MODEL-A`` / 产品名 ``PRODUCT-A``）。任何写死端口的脚本都可能
**连错设备**，而连错的代价可能是驱动用户的真实账号。已知硬编码过：
``tools/auto_stage.py`` / ``tools/probe.py`` / ``tools/live_check.py`` 的
``DEFAULT_ADDRESS``，以及 ``run_phantom_merge_live.py`` 的地址默认值。

因此本票把「地址」从**端口字面量**改成**账号身份发现**，并把「身份不符即拒绝」做成守卫：

1. ``addr-discovery-no-hardcoded-port`` —— 本票拥有的 9 个工具文件里，**代码**中不再有
   任何设备端口字面量（只看代码，注释 / 文档字符串不算）。
2. ``addr-discovery-single-source`` —— ``live_harness`` 暴露唯一真源
   （``resolve_address`` / ``discover_devices`` / ``read_identity`` / ``expected_identity``
   / ``identity_mismatch``）；每个消费地址的工具都经它取地址（含 ``expected_identity()``），
   不再自造 ``DEFAULT_ADDRESS``。
3. ``addr-discovery-identity-guard`` —— ``connect_device(..., expect=...)`` 在连到的设备
   身份与期望不符时**抛错拒绝执行**（防止误驱动别的账号）；匹配时正常返回。

★prove-red★（``python tools\\contract_hooks\\hooks_40.py``）：
   * 往 ``live_harness`` 副本里塞回一个端口字面量 -> 守卫 1 红；
   * 从某个 runner 副本里删掉 ``expected_identity(`` -> 守卫 2 红；
   * 把 ``identity_mismatch`` 换成「永远匹配」-> 守卫 3 红（不再拒绝）。
"""

from __future__ import annotations

import importlib
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

# ★只 append 到 sys.path 末尾★（同 hooks_20/25）：prove-red 用 PYTHONPATH 抢先塞坏副本时，
# 副本仍优先命中，不被真实的 live_harness 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

#: 本票拥有（并负责收敛）的工具文件 —— 地址的调用方 + 唯一真源。
OWNED_FILES: tuple[str, ...] = (
    "live_harness.py",
    "run_special_live.py",
    "run_side_live.py",
    "run_phantom_live.py",
    "run_phantom_merge_live.py",
    "run_pipeline.py",
    "auto_stage.py",
    "probe.py",
    "live_check.py",
)
#: 唯一真源文件。
HARNESS = "live_harness.py"
#: 真实存在过的设备端口字面量（#40：全部清零）。只看**代码**，注释不算。
STALE_PORT_LITERALS: tuple[str, ...] = ("16384", "16385", "16448")
#: 身份发现的唯一真源函数名（live_harness 必须导出）。
DISCOVERY_API: tuple[str, ...] = (
    "resolve_address",
    "discover_devices",
    "read_identity",
    "expected_identity",
    "identity_mismatch",
    "DeviceIdentity",
)
#: 每个消费地址的工具都必须经它取地址 / 校验身份（证明它不再自造端口）。
SINGLE_SOURCE_MARKERS: tuple[str, ...] = ("expected_identity(", "resolve_address(")


# ---------------------------------------------------------------------------
# 只看「代码」：去掉注释与文档字符串（免得把解释 bug 的注释误判成写死端口）
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
            blank(tok)
        if t not in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING):
            prev_sig = t
    return "".join(chars)


def _owned_files(tools_dir: Path = TOOLS_DIR) -> list[Path]:
    """返回本票拥有的、且真实存在的工具文件。"""
    return [tools_dir / name for name in OWNED_FILES if (tools_dir / name).is_file()]


def _consumer_files(tools_dir: Path = TOOLS_DIR) -> list[Path]:
    """返回消费地址的工具文件（唯一真源 live_harness 除外）。"""
    return [p for p in _owned_files(tools_dir) if p.name != HARNESS]


# ---------------------------------------------------------------------------
# 守卫 1：代码里没有过时的设备端口字面量
# ---------------------------------------------------------------------------
def _hardcoded_port_messages(tools_dir: Path = TOOLS_DIR) -> list[str]:
    msgs: list[str] = []
    files = _owned_files(tools_dir)
    if not files:
        return ["找不到任何本票拥有的工具文件（守卫已与实现脱节）"]
    for path in files:
        code = code_only(path.read_text(encoding="utf-8"))
        for literal in STALE_PORT_LITERALS:
            if re.search(rf"(?<!\d){re.escape(literal)}(?!\d)", code):
                msgs.append(f"{path.name} 代码里仍有设备端口字面量 {literal}（应改为身份发现）")
    return msgs


def probe_no_hardcoded_port(tools_dir: Path = TOOLS_DIR) -> bool:
    """#40 守卫 1：本票拥有的工具代码里没有过时的设备端口字面量。"""
    return _hardcoded_port_messages(tools_dir) == []


# ---------------------------------------------------------------------------
# 守卫 2：地址的唯一真源 = live_harness 的身份发现；消费者都经它取地址
# ---------------------------------------------------------------------------
def _harness_api_messages(harness_src: Path = TOOLS_DIR / HARNESS) -> list[str]:
    if not harness_src.is_file():
        return [f"缺少唯一真源 {HARNESS}"]
    try:
        module = importlib.import_module(HARNESS[:-3])
    except Exception as exc:  # noqa: BLE001 -- 导入失败即真源不可用
        return [f"{HARNESS} 导入失败：{exc!r}"]
    missing = [name for name in DISCOVERY_API if not hasattr(module, name)]
    if missing:
        return [f"{HARNESS} 缺少身份发现 API：{missing}"]
    return []


def _consumer_single_source_messages(tools_dir: Path = TOOLS_DIR) -> list[str]:
    msgs: list[str] = []
    files = _consumer_files(tools_dir)
    if not files:
        return ["找不到任何消费地址的工具文件（守卫已与实现脱节）"]
    for path in files:
        code = code_only(path.read_text(encoding="utf-8"))
        if not any(marker in code for marker in SINGLE_SOURCE_MARKERS):
            msgs.append(
                f"{path.name} 未经身份发现取地址（缺 {' / '.join(SINGLE_SOURCE_MARKERS)}）"
            )
        if re.search(r"^DEFAULT_ADDRESS\s*=", code, re.M):
            msgs.append(f"{path.name} 又自造了 DEFAULT_ADDRESS（地址应只有一个真源）")
    return msgs


def probe_single_source() -> bool:
    """#40 守卫 2：唯一真源在 live_harness；每个消费者都经它取地址。"""
    return _harness_api_messages() == [] and _consumer_single_source_messages() == []


# ---------------------------------------------------------------------------
# 守卫 3：身份不符即拒绝执行（防止误驱动别的账号）
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


def _raises_runtime(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except RuntimeError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


def probe_identity_guard() -> bool:
    """#40 守卫 3：connect_device 对**显式期望**不符即抛错；匹配则正常返回。

    #130：期望必须是**显式**的 —— ``expected_identity()`` 在 ``WF_LIVE_EXPECT_*`` 全 unset
    时返回空期望（不校验，等于永远「匹配」），拿它来测守卫会变成空断言。所以这里写死一个
    具体期望（不是生产默认值，只是本守卫的测试夹具）。
    """
    import live_harness as ca

    expected = ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A")
    saved = (ca.AdbController, ca.read_identity, ca.ADB, ca.ADDRESS, ca._ctrl_ref.get("ctrl"))
    try:
        ca.AdbController = _FakeCtrl  # type: ignore[assignment]
        ca.read_identity = lambda adb, address, **kw: ca.DeviceIdentity(  # type: ignore[assignment]
            address=address, model="MODEL-B", product="PRODUCT-B"
        )
        refused = _raises_runtime(ca.connect_device, "fake-adb", "1.2.3.4:5", expect=expected)
        ca.read_identity = lambda adb, address, **kw: ca.DeviceIdentity(  # type: ignore[assignment]
            address=address, model=expected.model, product=expected.product
        )
        ctrl = ca.connect_device("fake-adb", "1.2.3.4:5", expect=expected)
        accepted = isinstance(ctrl, _FakeCtrl)
    finally:
        ca.AdbController, ca.read_identity, ca.ADB, ca.ADDRESS = saved[0], saved[1], saved[2], saved[3]  # type: ignore[assignment]
        ca._ctrl_ref["ctrl"] = saved[4]
    return refused and accepted


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_40.py`）
# ---------------------------------------------------------------------------
def _copy_harness_with_dead_port() -> Path:
    """复制 live_harness.py，塞回一个端口字面量。"""
    src = TOOLS_DIR / HARNESS
    text = src.read_text(encoding="utf-8")
    tmpdir = Path(tempfile.mkdtemp(prefix="wf_hook40_port_"))
    dst = tmpdir / src.name
    dst.write_text(text + '\nLEGACY_ADDRESS = "127.0.0.1:16384"  # 故意写回端口字面量\n', encoding="utf-8")
    return dst


def _copy_runner_without_identity() -> Path:
    """复制 run_side_live.py，删掉所有 expected_identity( / resolve_address( 标记。"""
    src = TOOLS_DIR / "run_side_live.py"
    text = src.read_text(encoding="utf-8")
    broken = text.replace("expected_identity(", "expected_id(").replace("resolve_address(", "resolve_addr(")
    if broken == text:
        raise RuntimeError("破坏点没找到：run_side_live.py 里没有身份发现标记")
    tmpdir = Path(tempfile.mkdtemp(prefix="wf_hook40_src_"))
    dst = tmpdir / src.name
    dst.write_text(broken, encoding="utf-8")
    return dst


def prove_red() -> bool:
    """真实绿；三处破坏，要求三个守卫各自变红。"""
    print("hooks_40 prove-red：三处破坏，要求三个守卫各自变红")
    green = (
        probe_no_hardcoded_port() is True
        and probe_single_source() is True
        and probe_identity_guard() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：无端口字面量 + 身份单源 + 身份守卫（绿）")
    if not green:
        return False

    # (a) 塞回端口字面量 -> 守卫 1 红。
    broken = _copy_harness_with_dead_port()
    try:
        msgs = _hardcoded_port_messages(broken.parent)
        red_port = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_port else 'FAIL'}] 写回端口字面量 -> {'红' if red_port else '仍绿'}{tail}")
    finally:
        shutil.rmtree(broken.parent, ignore_errors=True)

    # (b) 删掉身份发现标记 -> 守卫 2 红。
    bad_runner = _copy_runner_without_identity()
    try:
        msgs2 = _consumer_single_source_messages(bad_runner.parent)
        red_src = len(msgs2) > 0
        tail2 = f"  {msgs2[0]}" if msgs2 else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_src else 'FAIL'}] 自造地址（不经身份发现）-> {'红' if red_src else '仍绿'}{tail2}")
    finally:
        shutil.rmtree(bad_runner.parent, ignore_errors=True)

    # (c) identity_mismatch 永远匹配 -> 守卫 3 红。
    import live_harness as ca

    # #130：同样必须用**显式**期望（空期望本来就「不校验」，摘掉守卫也看不出差别）。
    expected = ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A")
    saved = (ca.AdbController, ca.read_identity, ca.identity_mismatch, ca._ctrl_ref.get("ctrl"))
    try:
        ca.AdbController = _FakeCtrl  # type: ignore[assignment]
        ca.read_identity = lambda adb, address, **kw: ca.DeviceIdentity(  # type: ignore[assignment]
            address=address, model="MODEL-B", product="PRODUCT-B"
        )
        ca.identity_mismatch = lambda identity, expected: None  # type: ignore[assignment]
        leaked = not _raises_runtime(ca.connect_device, "fake-adb", "1.2.3.4:5", expect=expected)
    finally:
        ca.AdbController, ca.read_identity, ca.identity_mismatch = saved[0], saved[1], saved[2]  # type: ignore[assignment]
        ca._ctrl_ref["ctrl"] = saved[3]
    print(f"  [{'PASS' if leaked else 'FAIL'}] 摘掉身份守卫（永不拒绝）-> {'红' if leaked else '仍绿'}")

    ok = green and red_port and red_src and leaked
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "addr-discovery-no-hardcoded-port",
        "#40",
        "本票工具代码里没有过时的设备端口字面量（改为账号身份发现）",
        probe_no_hardcoded_port,
    ),
    (
        "addr-discovery-single-source",
        "#40",
        "地址唯一真源 = live_harness 身份发现；每个消费者都经它取地址",
        probe_single_source,
    ),
    (
        "addr-discovery-identity-guard",
        "#40",
        "connect_device 身份不符即拒绝执行（防止误驱动别的账号）",
        probe_identity_guard,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
