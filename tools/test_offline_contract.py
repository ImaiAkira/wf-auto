# -*- coding: utf-8 -*-
"""离线契约入口：套件契约 + 场景配置 seam 的断言挂点（自动发现聚合）。

本文件仍是**唯一入口**（``test_*.py``，被 ``run_all_tests.ps1`` 扫到），但不测
业务逻辑。它做两件事：

1. **套件契约（本文件自带，现在就生效）** —— 定义「一个离线断言」的三种结局：

   * 探针返回 ``True``  ->  ``PASS``；
   * 探针返回 ``False`` ->  ``FAIL``，整套退出码非 0（红）；
   * 探针返回 ``None``  ->  ``PENDING``（seam 尚未实现，既不算通过也不算失败），
     但会被打印出来，写清由哪张 ticket 点亮。

2. **挂点发现（#15 拆分）** —— 挂点按票分文件，放在 ``tools/contract_hooks/``，
   每个 ``hooks_<票号>.py`` 导出 ``HOOKS``。本文件用
   :func:`contract_hooks.discover_hooks` **自动发现**并聚合，**不维护手写清单**：

   * 新增一张票的挂点 = 新建一个 ``hooks_<票号>.py``，**零改既有文件** ——
     这是 #4/#5/#6/#8 能并行不撞车的前提；
   * 归一性守卫 ``aggregator-discovers-new-file``（``hooks_15.py``）会当场新建一个
     文件并断言它被发现，防止未来有人把聚合器改回手写清单。

   对应 ADR-0001（配置为真源）/ ADR-0002（目标声明式导航）/ ADR-0003（页面判据全局唯一）。

``hooks_2.probe_entry_offline`` 是**已点亮的 worked example**：它守卫本入口本身，
展示「挂点 -> 把东西改坏 -> 必须红」的完整机制，供后续票照抄。
``--prove-red`` 就真的把入口改坏（复制一份、删掉强制 UTF-8 的那行），要求守卫抓到；
对 #3 则逐一改坏 scene 配置面，要求三个守卫各自变红。

跑法::

    python tools\\test_offline_contract.py                # 绿：pending 不打红
    python tools\\test_offline_contract.py --prove-red    # 证明：改坏实现 -> 必须红
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
ENTRY = TOOLS_DIR / "run_all_tests.ps1"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from contract_hooks import discover_hooks, scan_hook_ids  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"


def load_hooks():
    """聚合所有票的挂点（自动发现，无手写模块清单，无缓存）。"""
    return discover_hooks()


def get_probe(hook_id):
    """按 hook_id 取探针；prove-red 用它在不依赖文件名的情况下定位某票的探针。"""
    for hid, _ticket, _what, probe in load_hooks():
        if hid == hook_id:
            return probe
    raise KeyError(f"找不到挂点：{hook_id}")


def _disk_alignment_error():
    """入口级对账：聚合结果必须与「按约定扫盘」的独立结果一致。

    归一性守卫的 out-of-band 兜底。守卫 ``aggregator-discovers-new-file`` 自己就是一个
    挂点文件；若有人把 ``discover_hooks`` 改成手写清单、还顺手把守卫模块 ``hooks_15``
    漏掉，in-band 守卫根本不会跑。这里不看 ``discover_hooks`` 的实现，只拿它与独立扫盘
    ``scan_hook_ids`` 对账，任何「磁盘上有票文件、聚合里没有」都会当场判红。
    """
    got = sorted(h[0] for h in discover_hooks())
    expected = sorted(scan_hook_ids())
    if got == expected:
        return None
    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    return f"聚合器与磁盘约定不一致（手写清单会丢挂点）：missing={missing} extra={extra}"


def run_hooks(hooks):
    """跑一遍挂点，返回 (rows, fails)。

    rows 每项 = (state, hook_id, ticket, 说明, extra)；state 取 PASS/FAIL/PENDING。
    fails = 结局为 FAIL 的 hook_id 列表。探针抛异常按 FAIL 处理（坏实现也要变红）。
    """
    rows = []
    fails = []
    for hook_id, ticket, what, probe in hooks:
        try:
            got = probe()
        except Exception as exc:  # noqa: BLE001 -- 坏探针必须变红，不能把套件带崩
            rows.append((FAIL, hook_id, ticket, what, f"probe raised {exc!r}"))
            fails.append(hook_id)
            continue
        if got is None:
            rows.append((PENDING, hook_id, ticket, what, f"seam 未实现，待 {ticket} 点亮"))
        elif got is True:
            rows.append((PASS, hook_id, ticket, what, ""))
        else:
            rows.append((FAIL, hook_id, ticket, what, "断言不成立"))
            fails.append(hook_id)
    return rows, fails


def _print_report(rows, title):
    print("=" * 74)
    print(title)
    print("=" * 74)
    for state, hook_id, ticket, what, extra in rows:
        tail = f"  {extra}" if extra else ""
        print(f"  [{state}] {hook_id} ({ticket})  {what}{tail}")


def _prove_red() -> int:
    """真·破坏实验：复制入口并删掉强制 UTF-8 的那行，守卫必须抓到它变红。"""
    print("\n--prove-red：把入口复制一份并删掉强制 UTF-8 的那行，要求守卫变红")
    tmpdir = Path(tempfile.mkdtemp(prefix="wf_contract_"))
    try:
        src = ENTRY.read_text(encoding="utf-8")
        broken = src.replace("$env:PYTHONIOENCODING = 'utf-8'", "# utf-8 forcing deliberately removed")
        if broken == src:
            print("  [FAIL] 没能在入口里找到强制 UTF-8 的那行 -- 守卫已与实现脱节")
            return 1
        broken_path = tmpdir / "run_all_tests.ps1"
        broken_path.write_text(broken, encoding="utf-8")

        hooks = load_hooks()
        idx = next(i for i, h in enumerate(hooks) if h[0] == "entry-offline-signal")
        hook_id, ticket, what, _probe = hooks[idx]
        real_entry_probe = get_probe("entry-offline-signal")
        hooks[idx] = (hook_id, ticket, what, lambda: real_entry_probe(broken_path))
        rows_broken, fails_broken = run_hooks(hooks)
        _print_report(rows_broken, "--prove-red：坏入口进入后")

        green_ok = len(run_hooks(load_hooks())[1]) == 0
        red_ok = hook_id in fails_broken
        print()
        print(f"  [{'PASS' if green_ok else 'FAIL'}] 真实入口通过守卫（绿）")
        print(f"  [{'PASS' if red_ok else 'FAIL'}] 改坏入口后 {hook_id} 变红（红 = 可用信号）")
        if green_ok and red_ok:
            print("\n结果：★prove-red 成功★：挂点既能绿也能红，红的含义可用")
            return 0
        print("\n结果：★prove-red 失败★：挂点抓不到坏实现，红不可用")
        return 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_scene_probe_in(root: Path, hook_id: str):
    """在子进程里、以 ``root`` 作为 ``scene`` 包的来源跑一个探针（按 hook_id 取）。

    返回 True/False（探针结论），或 None（子进程没跑到结论 = harness 失败）。
    cwd 指到中立空目录：run_all_tests 会把 CWD 钉在仓库根，若不换，仓库根会经
    ``sys.path`` 抢先命中真实 scene，破坏实验就白做了。
    """
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "import test_offline_contract as t\n"
        f"print('PROBE_RESULT', repr(t.get_probe({hook_id!r})()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _mut_add_duplicate_page_rule(path: Path) -> None:
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\n# --prove-red：故意抄第二份同名列，守卫必须抓到\n"
        + "PAGE_RULES.append(PageRule('主城', {'type': 'OCR', 'param': {}}, 'duplicate'))\n",
        encoding="utf-8",
    )


def _break_scene_and_check(label: str, mutate, hook_id: str) -> bool:
    """复制整个 scene 包 -> 施加一处破坏 -> 真实探针须绿、坏副本探针须红。"""
    tmp = Path(tempfile.mkdtemp(prefix="wf_scenepr_"))
    try:
        shutil.copytree(REPO_ROOT / "scene", tmp / "scene")
        mutate(tmp)
        green = get_probe(hook_id)() is True
        red = _run_scene_probe_in(tmp, hook_id) is False
        print(f"  [{'PASS' if green and red else 'FAIL'}] {label}"
              f"  (真实绿={green}, 破坏后红={red})")
        return green and red
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _prove_red_scene() -> int:
    """scene 配置面三个守卫的破坏实验：逐一改坏实现，守卫必须各自变红。"""
    print("\n--prove-red：逐一破坏 scene 配置面，要求 3 个守卫各自变红（红 = 可用信号）")
    checks = [
        _break_scene_and_check(
            "破坏 cfg-member-unique（跳过重复成员检测）",
            lambda t: _sub(t / "scene" / "config.py", "        if n > 1:", "        if False:"),
            "cfg-member-unique",
        ),
        _break_scene_and_check(
            "破坏 cfg-difficulty-set（跳过空难度集检测）",
            lambda t: _sub(t / "scene" / "config.py", "        if not m.支持难度集:", "        if False:"),
            "cfg-difficulty-set",
        ),
        _break_scene_and_check(
            "破坏 cfg-page-rules-report（覆盖报告吞掉覆盖）",
            lambda t: _sub(t / "scene" / "config.py", "    return list(cfg.overrides)", "    return []"),
            "cfg-page-rules-report",
        ),
        _break_scene_and_check(
            "破坏 cfg-page-rules-report（注册表里抄第二份同名列）",
            lambda t: _mut_add_duplicate_page_rule(t / "scene" / "page_rules.py"),
            "cfg-page-rules-report",
        ),
    ]
    ok = all(checks)
    print(f"  [{'PASS' if ok else 'FAIL'}] scene 配置面守卫可红可用")
    return 0 if ok else 1


def main() -> int:
    hooks = load_hooks()
    rows, fails = run_hooks(hooks)
    align_err = _disk_alignment_error()
    if align_err:
        rows.append((FAIL, "aggregator-matches-disk", "#15",
                     "聚合器按约定扫盘，不靠手写清单（磁盘对账）", align_err))
        fails.append("aggregator-matches-disk")
    _print_report(rows, "离线契约骨架：套件契约 + seam 断言挂点")
    pending = [r for r in rows if r[0] == PENDING]
    print(
        f"\n  共 {len(rows)} 个挂点："
        f"{len(rows) - len(pending) - len(fails)} 通过，"
        f"{len(fails)} 失败，"
        f"{len(pending)} 待点亮(seam 未实现)"
    )

    if "--prove-red" in sys.argv[1:]:
        rc_entry = _prove_red()
        rc_scene = _prove_red_scene()
        return 0 if (rc_entry == 0 and rc_scene == 0) else 1

    if fails:
        print("\n结果：★不通过★ -> " + ", ".join(fails))
        return 1
    print("\n结果：契约骨架就绪 ✅（待点亮的挂点在 seam 落地后自动承担守卫）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
