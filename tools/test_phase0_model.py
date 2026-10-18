# -*- coding: utf-8 -*-
"""离线单测 #58（Phase 0 / E1+E2）：页面判据注册表 + 按场景派生的链上步骤页集。

**行为保持的纯重构**：全局判据仍唯一、场景只按名有序选取、覆盖仍具名且被报告、链上步骤
页集（#37）仍**按场景派生**（**不是**各场景页面的累积并集）。本文件是这些不变量的一键
离线入口；守卫本体与 prove-red 在 ``tools/contract_hooks/hooks_phase0.py``。

     .venv\\Scripts\\python.exe tools\\test_phase0_model.py
     .venv\\Scripts\\python.exe tools\\test_phase0_model.py --prove-red

不需要游戏 / 设备：判据与派生全在纯 Python + 配置数据上。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402
from scene.page_rules import (  # noqa: E402
    CHAIN_STEP_PAGES,
    chain_step_pages,
    duplicate_rule_names,
    page_rules,
    registered_scenes,
)

import hooks_phase0  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 三条守卫（挂点点亮）
# ---------------------------------------------------------------------------
def test_guards() -> None:
    print("\n== 1. 三条守卫点亮（probe=True） ==")
    check("挂点 page-rules-registry-unique 点亮",
          hooks_phase0.probe_page_rules_registry_unique() is True)
    check("挂点 override-still-reported 点亮",
          hooks_phase0.probe_override_still_reported() is True)
    check("挂点 chain-step-pages-per-scene 点亮",
          hooks_phase0.probe_chain_step_pages_per_scene() is True)


# ---------------------------------------------------------------------------
# 2. 被重构的不变量仍成立（直接断言 + 无漂移 + #9 守卫仍绿）
# ---------------------------------------------------------------------------
def test_invariants_refactored() -> None:
    print("\n== 2. 被重构的三条不变量仍成立（直接断言） ==")
    check("全局注册表无重名", duplicate_rule_names() == [], f"dup={duplicate_rule_names()}")

    names = {r.name for r in page_rules()}
    missing = [p for p in CHAIN_STEP_PAGES if p not in names]
    check("CHAIN_STEP_PAGES 每个名字都在 PAGE_RULES 里（绝不静默）", missing == [],
          f"missing={missing}")
    check("chain_step_pages() 与 CHAIN_STEP_PAGES 一致",
          tuple(chain_step_pages()) == tuple(CHAIN_STEP_PAGES))
    check("缺省场景已登记", registered_scenes() != (), f"scenes={registered_scenes()}")

    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")

    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [])
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")


# ---------------------------------------------------------------------------
# 3. 破坏实验：三条不变量各自的守卫都能变红
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 3. 破坏实验：三条不变量各自的守卫都能变红 ==")
    check("hooks_phase0.prove_red() 成立（三条破坏各自变红）",
          hooks_phase0.prove_red() is True)


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 72)
    print("离线单测 #58：页面判据注册表 + 按场景派生的链上步骤页集（E1+E2）")
    print("=" * 72)
    test_guards()
    test_invariants_refactored()
    test_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
