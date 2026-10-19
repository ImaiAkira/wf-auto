# -*- coding: utf-8 -*-
"""#58（Phase 0 / E1+E2）：页面判据注册表 + 按场景派生的链上步骤页集 —— 契约挂点。

seam：``scene.page_rules``（全局唯一注册表 + 每场景有序选取 + 具名覆盖 + per-scene 的
链上步骤页集）+ ``scene.config.override_report``（覆盖报告）+ ``scene.lord_battle``
（缺省场景的配置数据）。

三个守卫（对应本票要重构的三条不变量；prove-red 见文末）：

1. ``page-rules-registry-unique`` —— 判据仍**全局唯一**；注册表与 ``PAGE_RULES`` 是同一份
   真源（场景只引用、不复制判据），且唯一性检测器对「第二份同名列」有效；
2. ``override-still-reported``    —— 场景专有判据仍是**具名显式**的 ``Override``
   （owner + rule + reason），且仍进 ``override_report``（覆盖绝不隐形）；
3. ``chain-step-pages-per-scene`` —— ``CHAIN_STEP_PAGES`` 是**按场景派生**的链上步骤页集，
   **不是**各场景页面的累积并集（#37 的不变量因此保住）。

prove-red（``python tools\\contract_hooks\\hooks_phase0.py``）：复制一份 ``scene`` 包、施加
一处破坏、用子进程重跑本文件的探针，要求**各自变红**（红 = 可用信号）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】。

    放末尾是有意的：prove-red 会在子进程里用 PYTHONPATH 指向一份坏掉的 ``scene`` 副本
    （其位置在 sys.path 里更靠前），这里的真实仓库根不会把它盖掉。
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 守卫 1：判据仍全局唯一；注册表是唯一一份（场景只引用、不复制）
# ---------------------------------------------------------------------------
def probe_page_rules_registry_unique() -> bool:
    """#58/E1：页面判据仍全局唯一；注册表与 ``PAGE_RULES`` 是同一份真源。"""
    scene_on_path()
    from scene.page_rules import (  # noqa: PLC0415
        PAGE_RULES,
        PageRuleRegistry,
        default_registry,
        duplicate_rule_names,
        page_rule,
        page_rules,
        registered_scenes,
    )

    # 全局唯一仍成立。
    if duplicate_rule_names():
        return False
    reg = default_registry()
    # 注册表持有的是**同一批**判据对象（同一份真源），不是副本。
    if len(reg.rules) != len(PAGE_RULES):
        return False
    if any(a is not b for a, b in zip(reg.rules, PAGE_RULES)):
        return False
    # 唯一性检测器**有效**：往一份新注册表里塞第二份同名 → 必须被点出。
    probe_reg = PageRuleRegistry(list(PAGE_RULES) + [PAGE_RULES[0]])
    if probe_reg.duplicates() != [PAGE_RULES[0].name]:
        return False
    # page_rule 返回注册表里的同一条判据（引用而非复制）。
    if not any(page_rule(PAGE_RULES[0].name) is r for r in PAGE_RULES):
        return False
    # 已登记场景的选取都**引用**全局表里的规则名（场景不发明页面）。
    names = {r.name for r in page_rules()}
    for s in registered_scenes():
        if any(p not in names for p in reg.selection(s).pages):
            return False
    return True


# ---------------------------------------------------------------------------
# 守卫 2：场景专有判据是具名显式 Override，且仍进覆盖报告
# ---------------------------------------------------------------------------
def probe_override_still_reported() -> bool:
    """#58/E1：场景专有判据是具名显式 Override，且仍进 ``override_report``（不隐形）。"""
    scene_on_path()
    from scene.config import ConfigError, override_report  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415
    from scene.page_rules import (  # noqa: PLC0415
        PAGE_RULES,
        PageRuleRegistry,
        scene_overrides,
    )

    scene_id = LORD_BATTLE.family.id
    reg_over = scene_overrides(scene_id)
    declared = list(LORD_BATTLE.overrides)
    # 注册表里的覆盖 == 配置声明的覆盖（同一批对象，逐条都在）。
    if len(reg_over) != len(declared):
        return False
    if not all(any(o is d for o in reg_over) for d in declared):
        return False
    # 仍进覆盖报告（ADR-0003：覆盖不得隐形）。
    report = override_report(LORD_BATTLE)
    if not all(any(o is r for r in report) for o in reg_over):
        return False
    # 具名且显式：owner + reason 非空。
    if not all(getattr(o, "owner", "") and getattr(o, "reason", "") for o in reg_over):
        return False
    # 不具名的覆盖（缺 reason）必须被 register **拒绝**，而不是静默接受。
    class _Unnamed:
        rule = PAGE_RULES[0].name
        owner = "X"
        reason = ""

    reg = PageRuleRegistry(list(PAGE_RULES))
    try:
        reg.register("probe-bad", [PAGE_RULES[0].name], [_Unnamed()])
    except ConfigError:
        return True
    except Exception:  # noqa: BLE001 -- 别的异常也算守卫失败（不是预期的拒绝）
        return False
    return False


# ---------------------------------------------------------------------------
# 守卫 3：CHAIN_STEP_PAGES 按场景派生，不是各场景页面的累积并集
# ---------------------------------------------------------------------------
def probe_chain_step_pages_per_scene() -> bool:
    """#58/E2：#37 的链上步骤页集按场景派生，**不是**各场景页面的累积并集。"""
    scene_on_path()
    from scene.page_rules import (  # noqa: PLC0415
        CHAIN_STEP_PAGES,
        PAGE_RULES,
        PageRuleRegistry,
        _EXPECTED_DEFAULT_CHAIN_STEP_PAGES,
        chain_step_pages,
        default_registry,
    )

    # CHAIN_STEP_PAGES / chain_step_pages() = 缺省场景（领主战族）的页面选取。
    chain_step_pages()  # 惰性登记缺省场景
    reg = default_registry()
    default_scene = reg.default_scene
    if default_scene is None:
        return False
    sel = reg.selection(default_scene)
    if tuple(CHAIN_STEP_PAGES) != tuple(sel.pages):
        return False
    if tuple(chain_step_pages()) != tuple(sel.pages):
        return False
    if tuple(chain_step_pages(default_scene)) != tuple(sel.pages):
        return False
    # 与「文档里登记的缺省场景期望面」一致（配置改了而文档没跟上 → 红）。
    if tuple(chain_step_pages()) != tuple(_EXPECTED_DEFAULT_CHAIN_STEP_PAGES):
        return False
    # 每场景自成一域：隔离注册表里两个场景的链页集互不累积。
    names = [r.name for r in PAGE_RULES]
    if len(names) < 4:
        return False
    a, b = names[:2], names[2:4]
    reg2 = PageRuleRegistry(list(PAGE_RULES))
    reg2.register("A", a)
    reg2.register("B", b)
    if tuple(reg2.chain_step_pages("A")) != tuple(a):
        return False
    if tuple(reg2.chain_step_pages("B")) != tuple(b):
        return False
    if set(reg2.chain_step_pages("A")) == (set(a) | set(b)):
        return False            # A 的链页集不是 A∪B（不累积）
    # #18 / #29：主城 / 详情页 仍是缺省场景的链上步骤页。
    if "主城" not in chain_step_pages() or "详情页" not in chain_step_pages():
        return False
    return True


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_phase0.py`）
# ---------------------------------------------------------------------------
def _temp_scene() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_phase0_"))
    shutil.copytree(REPO_ROOT / "scene", root / "scene")
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _run_probe_in(root: Path, probe_name: str):
    """在子进程里、以 ``root`` 作为 ``scene`` 包来源跑一个探针；返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks.hooks_phase0 import " + probe_name + "\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    neutral = Path(tempfile.mkdtemp(prefix="wf_phase0_neutral_"))
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


def _break_and_check(label: str, mutate, probe_name: str) -> bool:
    """复制整个 scene 包 → 施加一处破坏 → 真实挂点须绿、坏副本挂点须红。"""
    tmp = _temp_scene()
    try:
        mutate(tmp)
        green_ok = _run_probe_in(REPO_ROOT, probe_name) is True
        red_ok = _run_probe_in(tmp, probe_name) is False
        print(f"  [{'PASS' if green_ok and red_ok else 'FAIL'}] {label}"
              f"  (真实探针绿={green_ok}, 破坏后变红={red_ok})")
        return green_ok and red_ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prove_red() -> bool:
    """真实绿；三条不变量各自的破坏 → 对应守卫变红（红 = 可用信号）。"""
    scene_on_path()
    print("hooks_phase0 prove-red：逐一破坏 判据唯一 / 覆盖报告 / per-scene 派生，要求守卫各自变红")
    green = (
        probe_page_rules_registry_unique() is True
        and probe_override_still_reported() is True
        and probe_chain_step_pages_per_scene() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三条不变量成立（绿）")
    if not green:
        return False

    checks = [
        _break_and_check(
            "破坏全局唯一检测器（duplicates 恒空）",
            lambda t: _sub(
                t / "scene" / "page_rules.py",
                "        return sorted(n for n, c in counts.items() if c > 1)",
                "        return []",
            ),
            "probe_page_rules_registry_unique",
        ),
        _break_and_check(
            "破坏覆盖报告（注册表吞掉覆盖）",
            lambda t: _sub(
                t / "scene" / "page_rules.py",
                "        return list(sel.overrides)",
                "        return []",
            ),
            "probe_override_still_reported",
        ),
        _break_and_check(
            "破坏 per-scene 派生（链页集变成各场景并集）",
            lambda t: _sub(
                t / "scene" / "page_rules.py",
                "        return tuple(sel.pages)",
                "        return tuple(p for s in self._order for p in self._scenes[s].pages)",
            ),
            "probe_chain_step_pages_per_scene",
        ),
    ]
    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "page-rules-registry-unique",
        "#58",
        "页面判据仍全局唯一；注册表是唯一一份（场景只引用、不复制判据）",
        probe_page_rules_registry_unique,
    ),
    (
        "override-still-reported",
        "#58",
        "场景专有判据是具名显式 Override（owner + reason），且仍进覆盖报告",
        probe_override_still_reported,
    ),
    (
        "chain-step-pages-per-scene",
        "#58",
        "CHAIN_STEP_PAGES 按场景派生，不是各场景页面的累积并集（#37 不变量）",
        probe_chain_step_pages_per_scene,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
