# -*- coding: utf-8 -*-
"""#138：``--as-gui`` 遇到落后的 ``install/`` 必须**硬失败**（不再只警告）+ 一条同步命令。

真机现场（票面）
----------------
``install/`` 是 gitignored 的构建产物，实测会落后：``install/agent/lords_impl.py``
13:13（仓库 15:51）、``install/resource/pipeline/lords.json`` 13:00、
``wuchong.json`` 07:37、``install/resource/image/team/*.png`` 缺 5 张。而 ``--as-gui``
的语义是「资源从 ``install/resource`` 读、代码从仓库 ``agent/`` 导入」⇒ 落后时是
**旧流水线 + 新代码** 的最坏混合：日志里看到的修复和实际生效的修复不是同一份。

原实现只打印一行 ``★警告★ install/agent 与仓库不一致`` 然后继续跑，而且**只比了
``install/agent``，从不比 ``install/resource``** —— 所以「资源缺一张 team 模板」这种
最直接的流水线落后根本拦不住。

三个挂点（本文件）
------------------
1. ``as-gui-hard-gate``：``install/agent`` 落后 ⇒ ``--as-gui`` **非零退出**（不是警告），
   输出含可复制的修法 ``python tools/sync_install.py``；硬闸必须发生在碰设备之前。
2. ``as-gui-checks-resource``：**本次真洞** —— ``install/resource`` 缺一张
   ``image/team/*.png``（agent 完全一致）也必须同样拦下；只比 agent 的实现会在这里变绿。
3. ``as-gui-sync-then-pass``：``python tools/sync_install.py`` 同步后差异为 0 ⇒ 硬闸放行；
   且同步必须覆盖 agent + resource（只拷 agent 的「半截同步」不能算过）。
   附带 ``as-gui-allow-stale``：``--allow-stale-install`` 默认关；显式打开时**必须**打
   一行「本次验的不是最新流水线」的警告（仍有修法提示），而不是静默放行。

破坏实验（``python tools\\contract_hooks\\hooks_138.py``，全部在临时目录里做）
------------------------------------------------------------------------------
① 删掉比 resource 那段（``GATE_SCOPE_NAMES`` 只剩 agent）⇒ 挂点 2 红（真洞复发）；
② 硬闸退回警告（``check_install_freshness`` 只打印、不 SystemExit）⇒ 挂点 1 红；
③ 同步只拷 agent（``SYNC_SCOPE_NAMES`` 只剩 agent）⇒ 挂点 3 红。

★诚实边界★
* 本守卫不碰设备、不碰仓库里真实的 ``install/``：每个剧本都在 ``tempfile`` 新建的
  迷你仓库上跑（agent / pipeline / image 各一个文件），跑完删除。
* 它证明的是「硬闸的范围与退出语义按票面落地」，不是「当前这台机器的 install 是新的」；
  真实一致性由 ``python tools/sync_install.py --check`` 回答。
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import sync_install  # noqa: E402

_TICKET = "#138"

HOOK_ID_GATE = "as-gui-hard-gate"
HOOK_ID_RESOURCE = "as-gui-checks-resource"
HOOK_ID_SYNC = "as-gui-sync-then-pass"
HOOK_ID_ALLOW_STALE = "as-gui-allow-stale"

#: 迷你仓库的固定内容（源与 install 初始一致）。
_REPO_AGENT = "VERSION = 'repo'\n"
_REPO_PIPELINE = '{"name": "wuchong", "version": "repo"}\n'
_REPO_IMAGE = b"\x89PNG\r\n\x1a\nrepo"

_FILES = {
    "agent/lords_impl.py": _REPO_AGENT,
    "assets/resource/pipeline/wuchong.json": _REPO_PIPELINE,
    "assets/resource/image/team/party_label.png": _REPO_IMAGE,
    "install/agent/lords_impl.py": _REPO_AGENT,
    "install/resource/pipeline/wuchong.json": _REPO_PIPELINE,
    "install/resource/image/team/party_label.png": _REPO_IMAGE,
}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _new_project() -> Path:
    """新建一个「install 与仓库一致」的迷你仓库（临时目录）。"""
    root = Path(tempfile.mkdtemp(prefix="wf_hook138_"))
    for rel, data in _FILES.items():
        _write(root / rel, data)
    return root


def _make_agent_stale(root: Path) -> None:
    _write(root / "install/agent/lords_impl.py", "VERSION = 'old'\n")


def _make_pipeline_stale(root: Path) -> None:
    _write(root / "install/resource/pipeline/wuchong.json", '{"name": "wuchong", "version": "old"}\n')


def _make_image_missing(root: Path) -> None:
    (root / "install/resource/image/team/party_label.png").unlink()


def _runner():
    """惰性 import：本模块会被 ``_load_module`` 扫描；只有跑探针时才需要 maa。"""
    import run_wuchong_live  # noqa: PLC0415

    return run_wuchong_live


def _gate_exit(project: Path, *, allow_stale: bool = False):
    """直接跑硬闸函数，返回 ``(退出码, stdout, 返回值)``；SystemExit 也算退出码。"""
    runner = _runner()
    buf = io.StringIO()
    code = 0
    returned = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            returned = runner.check_install_freshness(Path(project), allow_stale=allow_stale)
        except SystemExit as exc:
            code = int(exc.code) if isinstance(exc.code, int) else (2 if exc.code else 0)
        except Exception as exc:  # noqa: BLE001 -- 硬闸自己炸了也是红，不能假绿
            code = -1
            print(f"[hook138] 硬闸异常：{type(exc).__name__}: {exc}")
    return code, buf.getvalue(), returned


def _run_cli(project: Path, *args: str):
    """真的走 ``--as-gui`` 的 argv 入口（只用于会硬失败的剧本，碰不到设备）。"""
    runner = _runner()
    saved_project = runner.PROJECT
    saved_argv = list(sys.argv)
    buf = io.StringIO()
    code = 0
    runner.PROJECT = Path(project)
    sys.argv = ["run_wuchong_live.py", "--as-gui", *args]
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                runner.main()
            except SystemExit as exc:
                code = int(exc.code) if isinstance(exc.code, int) else (2 if exc.code else 0)
            except Exception as exc:  # noqa: BLE001
                code = -1
                print(f"[hook138] runner.main 异常：{type(exc).__name__}: {exc}")
    finally:
        runner.PROJECT = saved_project
        sys.argv = saved_argv
    return code, buf.getvalue()


def _fail(fails: list, label: str, detail: str) -> None:
    fails.append(f"{label}：{detail}")


# ---------------------------------------------------------------------------
# 挂点 1：agent 落后 ⇒ --as-gui 非零退出 + 可复制修法（且 CLI 入口同样拦下）
# ---------------------------------------------------------------------------
def _stale_agent_failures() -> list:
    fails: list = []
    root = _new_project()
    try:
        _make_agent_stale(root)
        code, out, returned = _gate_exit(root)
        if code == 0:
            _fail(fails, "硬闸", f"install/agent 落后却退出码 0（returned={returned!r}）")
        if sync_install.FIX_COMMAND not in out:
            _fail(fails, "修法", f"输出没有可复制的 {sync_install.FIX_COMMAND!r}")
        if "install/agent" not in out or "lords_impl.py" not in out:
            _fail(fails, "差异", f"输出没点名落后的 install/agent/lords_impl.py：{out[-200:]!r}")
        if code != 0:
            # 只有硬闸真的先拦下，才走 CLI；否则（如退回警告）会继续碰设备。
            cli_code, cli_out = _run_cli(root, "--recon")
            if cli_code == 0:
                _fail(fails, "--as-gui", "CLI 入口退出码 0（警告后继续跑）")
            if sync_install.FIX_COMMAND not in cli_out:
                _fail(fails, "--as-gui 修法", "CLI 输出没有可复制的修法命令")
            if "install/agent/lords_impl.py" not in cli_out:
                _fail(fails, "--as-gui 差异", f"CLI 输出没点名 lords_impl.py：{cli_out[-200:]!r}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return fails


def probe_as_gui_hard_gate() -> bool:
    """#138-1：install/agent 落后 ⇒ --as-gui 非零退出（不是警告），输出含修法。"""
    fails = _stale_agent_failures()
    print(f"  [{'PASS' if not fails else 'FAIL'}] 挂点 1：agent 落后 ⇒ 硬闸非零退出 + 修法")
    for msg in fails:
        print(f"      - {msg}")
    return not fails


# ---------------------------------------------------------------------------
# 挂点 2：agent 干净、install/resource 缺一张 team 模板 ⇒ 同样拦下（本次真洞）
# ---------------------------------------------------------------------------
def _missing_resource_failures() -> list:
    fails: list = []
    root = _new_project()
    try:
        _make_image_missing(root)
        agent_tree = sync_install.compare_install(root).tree("agent")
        if not agent_tree.is_fresh:
            _fail(fails, "剧本前提", "agent 本来就不一致，无法证明是 resource 那段在拦")
        code, out, returned = _gate_exit(root)
        if code == 0:
            _fail(
                fails,
                "resource 硬闸",
                f"install/resource 缺 image/team/party_label.png 却退出码 0"
                f"（returned={returned!r}）—— 只比 agent 的实现会在这里假绿",
            )
        if "install/resource/image/team/party_label.png" not in out:
            _fail(fails, "差异", f"输出没点名缺失的 team 模板：{out[-200:]!r}")
        if "install/resource" not in out:
            _fail(fails, "范围", f"输出没有 install/resource 的差异段：{out[-200:]!r}")
        if sync_install.FIX_COMMAND not in out:
            _fail(fails, "修法", f"输出没有可复制的 {sync_install.FIX_COMMAND!r}")
        if code != 0:
            cli_code, cli_out = _run_cli(root, "--recon")
            if cli_code == 0:
                _fail(fails, "--as-gui", "CLI 入口没拦住缺 team 模板的 resource")
            if "team/party_label.png" not in cli_out:
                _fail(fails, "--as-gui 差异", f"CLI 输出没点名缺失模板：{cli_out[-200:]!r}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return fails


def probe_as_gui_checks_resource() -> bool:
    """#138-2：agent 一致但 install/resource 缺 team 模板 ⇒ 硬闸同样非零退出（真洞）。"""
    fails = _missing_resource_failures()
    print(f"  [{'PASS' if not fails else 'FAIL'}] 挂点 2：resource 缺 team 模板 ⇒ 同样拦下")
    for msg in fails:
        print(f"      - {msg}")
    return not fails


# ---------------------------------------------------------------------------
# 挂点 3：同步后差异为 0 ⇒ 放行；只拷 agent 的半截同步不算过
# ---------------------------------------------------------------------------
def _sync_then_pass_failures() -> list:
    fails: list = []
    root = _new_project()
    try:
        # 三个范围同时落后：agent 内容旧 / pipeline 旧 / image 缺一张。
        _make_agent_stale(root)
        _make_pipeline_stale(root)
        _make_image_missing(root)
        before = sync_install.compare_install(root)
        stale_names = {tree.scope for tree in before.stale_trees}
        if stale_names != {"agent", "pipeline", "image"}:
            _fail(fails, "剧本前提", f"同步前应三处都落后，实际 {sorted(stale_names)}")
        code, _out, _returned = _gate_exit(root)
        if code == 0:
            _fail(fails, "同步前", "三处都落后却已经放行")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            after = sync_install.sync_project(root)
        if not after.is_fresh:
            _fail(
                fails,
                "同步后",
                "同步后仍有差异：" + "；".join(
                    line for line in sync_install.format_lines(after, include_model=True) if "✗" in line
                ),
            )
        code, out, returned = _gate_exit(root)
        if code != 0:
            _fail(fails, "放行", f"同步后硬闸仍非零退出 code={code}")
        if returned is not True:
            _fail(fails, "放行", f"同步后硬闸返回值 {returned!r}，应为 True（一致）")
        if "install/resource" not in out or "✓" not in out:
            _fail(fails, "放行", f"同步后没有 agent+resource 的一致性确认：{out[-200:]!r}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return fails


def probe_as_gui_sync_then_pass() -> bool:
    """#138-3：sync_install 同步后差异为 0 ⇒ 硬闸放行（只拷 agent 会红）。"""
    fails = _sync_then_pass_failures()
    print(f"  [{'PASS' if not fails else 'FAIL'}] 挂点 3：同步后差异为 0 ⇒ 放行")
    for msg in fails:
        print(f"      - {msg}")
    return not fails


# ---------------------------------------------------------------------------
# 挂点 4：--allow-stale-install 默认关；打开时必须显式警告「不是最新流水线」
# ---------------------------------------------------------------------------
def _allow_stale_failures() -> list:
    fails: list = []
    root = _new_project()
    try:
        _make_agent_stale(root)
        code, out, returned = _gate_exit(root)
        if code == 0:
            _fail(fails, "默认关", f"没给 --allow-stale-install 却退出码 0（returned={returned!r}）")

        code, out, returned = _gate_exit(root, allow_stale=True)
        if code != 0:
            _fail(fails, "逃生阀", f"--allow-stale-install 仍非零退出 code={code}（不能当正常路径用）")
        if returned is not False:
            _fail(fails, "逃生阀", f"显式允许落后时返回值 {returned!r}，应为 False（已知落后）")
        if "本次验的不是最新流水线" not in out:
            _fail(fails, "警告", f"没有「本次验的不是最新流水线」的显式警告：{out[-200:]!r}")
        if "--allow-stale-install" not in out:
            _fail(fails, "警告", "警告里没点名 --allow-stale-install")
        if sync_install.FIX_COMMAND not in out:
            _fail(fails, "修法", "逃生阀放行时没有附修法命令（用户仍需知道怎么修）")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return fails


def probe_as_gui_allow_stale() -> bool:
    """#138-4：逃生阀默认关；显式 --allow-stale-install 才放行且必须警告「不是最新流水线」。"""
    fails = _allow_stale_failures()
    print(f"  [{'PASS' if not fails else 'FAIL'}] 挂点 4：--allow-stale-install 默认关 + 显式警告")
    for msg in fails:
        print(f"      - {msg}")
    return not fails


HOOKS = [
    (
        HOOK_ID_GATE,
        _TICKET,
        "★硬闸不是警告★--as-gui 启动时按内容哈希比对 install/agent ↔ agent/；不一致 ⇒ 非零退出"
        "（SystemExit 2）并打印可复制的 python tools/sync_install.py；硬闸发生在碰设备之前",
        probe_as_gui_hard_gate,
    ),
    (
        HOOK_ID_RESOURCE,
        _TICKET,
        "★本次真洞★install/resource ↔ assets/resource（pipeline *.json + image/**/*.png）也要比："
        "agent 完全一致、只缺一张 image/team/*.png 时，--as-gui 同样必须非零退出（只比 agent 会假绿）",
        probe_as_gui_checks_resource,
    ),
    (
        HOOK_ID_SYNC,
        _TICKET,
        "★一条命令修好★tools/sync_install.py 同步 agent + pipeline + image（+ model）后差异为 0 ⇒ "
        "--as-gui 放行；只拷 agent 的半截同步必须红（同步后按全范围校验）",
        probe_as_gui_sync_then_pass,
    ),
    (
        HOOK_ID_ALLOW_STALE,
        _TICKET,
        "★逃生阀默认关★只有显式 --allow-stale-install 才允许落后继续；此时必须打一行"
        "「本次验的不是最新流水线」的警告并附修法，不许静默放行",
        probe_as_gui_allow_stale,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _record(name: str, red: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {detail}" if detail else ""))


def _silent(probe) -> tuple[bool, str]:
    """跑一个探针并吞掉它自己的 PASS/FAIL 行（破坏实验只留一行结论）。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = probe()
    return bool(got), buf.getvalue()


def _warn_only_gate(_project, **_kwargs):
    """破坏实验 ② 的坏实现：旧的「只警告、然后继续」。"""
    print("[as-gui] ★警告★ install/agent 与仓库不一致（GUI 会跑旧代码）→ 先跑 install.py 或同步再验收")
    return False


def prove_red() -> bool:
    print("hooks_138 prove-red：先把硬闸 / 资源比对 / 同步 / 逃生阀四条腿跑绿，再逐一破坏")
    green = (
        probe_as_gui_hard_gate()
        and probe_as_gui_checks_resource()
        and probe_as_gui_sync_then_pass()
        and probe_as_gui_allow_stale()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：四条腿全绿")
    if not green:
        return False

    runner = _runner()
    checks: list[bool] = []

    # ① 删掉比 resource 那段：GATE_SCOPE_NAMES 只剩 agent → 挂点 2 必须红（真洞复发）。
    real_gate_names = sync_install.GATE_SCOPE_NAMES
    try:
        sync_install.GATE_SCOPE_NAMES = ("agent",)
        probe_green, _detail = _silent(probe_as_gui_checks_resource)
        _record("① 删掉比 resource 那段（GATE_SCOPE_NAMES 只剩 agent）", not probe_green, "挂点 2 应红")
        checks.append(not probe_green)
    finally:
        sync_install.GATE_SCOPE_NAMES = real_gate_names

    # ② 硬闸退回警告：check_install_freshness 只打印、不 SystemExit → 挂点 1 必须红。
    real_gate = runner.check_install_freshness
    try:
        runner.check_install_freshness = _warn_only_gate
        probe_green, _detail = _silent(probe_as_gui_hard_gate)
        _record("② 硬闸退回警告（只打印、不非零退出）", not probe_green, "挂点 1 应红")
        checks.append(not probe_green)
    finally:
        runner.check_install_freshness = real_gate

    # ③ 同步只拷 agent：SYNC_SCOPE_NAMES 只剩 agent → 挂点 3 必须红（pipeline/image 仍旧）。
    real_sync_names = sync_install.SYNC_SCOPE_NAMES
    try:
        sync_install.SYNC_SCOPE_NAMES = ("agent",)
        probe_green, _detail = _silent(probe_as_gui_sync_then_pass)
        _record("③ 同步只拷 agent（SYNC_SCOPE_NAMES 只剩 agent）", not probe_green, "挂点 3 应红")
        checks.append(not probe_green)
    finally:
        sync_install.SYNC_SCOPE_NAMES = real_sync_names

    ok = green and bool(checks) and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
