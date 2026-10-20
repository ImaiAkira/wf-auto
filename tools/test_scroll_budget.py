# -*- coding: utf-8 -*-
"""离线单测：#50 ``SpecialScrollList`` 滚动预算 —— 每条目重置 + 用尽即有界停止。

不需要游戏 / 设备（判据全在内嵌的**列表状态机**上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_scroll_budget.py
    .venv\\Scripts\\python.exe tools\\test_scroll_budget.py --prove-red

覆盖 #50 的验收：

  1. **预算语义**：``special_dungeon.json::SpecialScrollList.max_hit`` 是有限、在合理区间内的
     【每条目】预算，且与 agent 单源常量 ``side_impl._PER_ITEM_SCROLL_BUDGET`` 逐字段相等；
     ``SpecialEnterBoss`` 排在滚动节点之前（= 行进屏即选行、不再消耗预算）；指挥官接了
     预算重置与用尽判定；
  2. **离线复现**：29 行降临讨伐列表、一个 chunk 里 5 个**深行**成员 —— 旧形态（预算按任务
     共享）滚到第 3 个成员即用尽、后面的成员全都到不了；新形态（每条目重置）**逐一到达**，
     且单条目滚动从不超过一份预算；
  3. **有界停止**：目标是**列表里不存在的行** —— 新形态滚完一份预算后**明确跳过并记录原因**
     （有界，绝不无限滚）；旧形态静默空转；
  4. **破坏实验**：改坏预算 / 单源常量 / 指挥官接线 / 关掉重置与安全网 → 三个守卫各自变红；
  5. **无漂移 + #9 三条既有路径守卫仍绿**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_50.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR), str(REPO_ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402

import hooks_50 as h50  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 预算语义
# ---------------------------------------------------------------------------
def test_budget_semantics() -> None:
    print("\n== 1. 预算语义：有限、区间内、与 agent 单源绑定、选行先于滚动 ==")
    files = h50._files()
    declared = h50._declared_budget(files)
    si = h50._agent()
    print(f"     产品 SpecialScrollList.max_hit = {declared}")
    print(f"     agent _PER_ITEM_SCROLL_BUDGET   = {si._PER_ITEM_SCROLL_BUDGET}")
    print(f"     合理区间 = [{h50.MIN_SCROLL_BUDGET}, {h50.MAX_SCROLL_BUDGET}]")

    check("产品声明了有限的每条目预算", isinstance(declared, int) and not isinstance(declared, bool))
    check(f"预算在合理区间 [{h50.MIN_SCROLL_BUDGET},{h50.MAX_SCROLL_BUDGET}]",
          isinstance(declared, int) and h50.MIN_SCROLL_BUDGET <= declared <= h50.MAX_SCROLL_BUDGET)
    check("agent 单源常量 == 产品 max_hit", si._PER_ITEM_SCROLL_BUDGET == declared)
    check("挂点 scroll-budget-per-item 已点亮（probe=True）",
          h50.probe_scroll_budget_per_item() is True)
    check("预算守卫失败清单为空", h50._budget_failures() == [],
          f"{h50._budget_failures()[:2]}")

    for tab in ("SpecialTabLord", "SpecialTabJoss"):
        seq = (h50._node(files, tab) or {}).get("next") or []
        ib = seq.index("SpecialEnterBoss") if "SpecialEnterBoss" in seq else -1
        isc = seq.index("SpecialScrollList") if "SpecialScrollList" in seq else -1
        check(f"{tab}.next: SpecialEnterBoss 排在 SpecialScrollList 之前", 0 <= ib < isc,
              f"EnterBoss@{ib} ScrollList@{isc}")


# ---------------------------------------------------------------------------
# 2. 离线复现：多条目共享预算 vs 每条目重置
# ---------------------------------------------------------------------------
def test_deep_batch_repro() -> None:
    print("\n== 2. 离线复现 #50：单 chunk 内 5 个深行成员 ==")
    budget = h50._budget()
    print(f"     列表 = {len(h50.ROWS)} 行；一屏 {h50.WINDOW} 行；{h50.SCROLL_ROWS} 行/次；预算 = {budget}")
    print(f"     目标（最深 5 行）= {h50.DEEP_TARGETS}")

    new = h50._simulate(h50.DEEP_TARGETS, budget=budget, reset=True, safety_net=True)
    old = h50._simulate(h50.DEEP_TARGETS, budget=budget, reset=False, safety_net=False)
    print(f"     新形态（每条目重置）：到达 {new.reached}（命中数 {new.hits}，步数 {new.steps}）")
    print(f"     旧形态（预算共享）  ：到达 {old.reached}；空转={old.spin}（命中数 {old.hits}）")

    check("挂点 scroll-budget-resets-per-item 已点亮（probe=True）",
          h50.probe_scroll_budget_resets_per_item() is True)
    check("新形态到达全部 5 个深行成员", len(new.reached) == len(h50.DEEP_TARGETS),
          f"{new.reached}")
    check("新形态单条目滚动不超过一份预算（有界）", new.over_budget is False)
    check("新形态无空转", new.spin is False)
    check("旧形态未到达全部深行成员（复现『系统性惩罚』）",
          len(old.reached) < len(h50.DEEP_TARGETS), f"old={old.reached}")
    check("旧形态复现『预算用尽后静默空转』", old.spin is True)


# ---------------------------------------------------------------------------
# 3. 有界停止：找不到的行
# ---------------------------------------------------------------------------
def test_bounded_stop() -> None:
    print("\n== 3. 有界停止：目标行不在列表里 ==")
    budget = h50._budget()
    new = h50._simulate([h50.ABSENT_TARGET], budget=budget, reset=True, safety_net=True)
    print(f"     新形态：跳过 {new.skipped}，步数 {new.steps}，空转={new.spin}")
    check("挂点 scroll-budget-bounded-stop 已点亮（probe=True）",
          h50.probe_scroll_budget_bounded_stop() is True)
    check("找不到的行被明确跳过（记录原因）", h50.ABSENT_TARGET in new.skipped)
    check("用尽后及时停止（未跑到步数上限）", new.steps < 4000 and new.spin is False)


# ---------------------------------------------------------------------------
# 4. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 4. 破坏实验：改坏预算 / 接线 / 开关 -> 三个守卫各自变红 ==")
    check("hooks_50.prove_red() 成立", h50.prove_red() is True)


# ---------------------------------------------------------------------------
# 5. 无漂移 + #9 守卫
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 5. 无漂移 + #9 三条既有路径守卫仍绿 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [])
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    if "--prove-red" in sys.argv[1:]:
        test_prove_red()
        print("\n" + "=" * 72)
        if FAILS:
            print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
            sys.exit(1)
        print("结果：prove-red 成立 ✅")
        return

    print("=" * 72)
    print("离线单测：#50 SpecialScrollList 滚动预算 —— 每条目重置 + 用尽有界停止")
    print("=" * 72)
    test_budget_semantics()
    test_deep_batch_repro()
    test_bounded_stop()
    test_prove_red()
    test_drift_and_guards()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
