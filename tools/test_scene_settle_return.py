# -*- coding: utf-8 -*-
"""离线单测：#19 结算后「页签翻转 + 归位弹跳」死循环 —— 页签由目标子族决定 + 复现。

不需要游戏；连 maa 运行时都不需要（判据在**合成的列表屏 OCR**上求值，页签/行名/ROI
全部照抄 ``special_dungeon.json`` 的实测值）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_settle_return.py

覆盖 #19 的验收：

  1. **页签由目标子族决定**：链 ``target_tab_node`` / ``decide`` 对两个子族给出各自的
     页签节点；重进列表站在错误页签上会自恢复回列表页（有界、不弹跳）；
  2. **pipeline 不再靠 max_hit 竞速**：``SpecialTabLord`` / ``SpecialTabJoss`` 不带
     ``max_hit``；``SpecialOpenLord`` 仍同时列出两个 tab 候选（标签常驻）；
  3. **确定性复现死循环**：用列表屏状态机 + MAA 的 ``next``/``max_hit`` 语义，给四个用例
     （含「当前在列表页且页签已被切到另一子族」）——
     **新形态**第 N 步必经 ``SpecialEnterBoss`` 到达；**旧形态**（页签带 ``max_hit: 1``）里
     「页签已被切到另一子族」的两例死循环（#19 缺陷）。注：#29 前「结算后重进」两例也被
     「归位在列表页抢跑」拖进死循环 —— 那正是 #29 修的 bug，故现只对另两例断言死循环；
  4. 无漂移 + #9 守卫仍绿 + ``hooks_19.prove_red()`` 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_19.py``。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_19  # noqa: E402
from scene import chain as C  # noqa: E402
from scene import drift  # noqa: E402
from scene.chain import resolve_target, target_tab_node  # noqa: E402
from scene.lord_battle import LORD_BATTLE  # noqa: E402
from scene.navigation import decide  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
SD = PIPELINE_DIR / "special_dungeon.json"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 页签由目标子族决定（链）
# ---------------------------------------------------------------------------
def test_tab_target_driven() -> None:
    print("\n== 1. 页签由目标子族决定（链 + pipeline 无 max_hit 竞速） ==")
    lord = resolve_target(LORD_BATTLE, hooks_19.LORD)
    joss = resolve_target(LORD_BATTLE, hooks_19.JOSS)
    check("领主战目标 → 领主战页签节点", target_tab_node(lord) == C.NODE_领主战页签)
    check("降临讨伐目标 → 降临讨伐页签节点", target_tab_node(joss) == C.NODE_降临讨伐页签)
    check("decide(列表页, 领主战目标) → 领主战页签",
          decide(LORD_BATTLE, "领主战列表页", hooks_19.LORD).id == C.NODE_领主战页签)
    check("decide(列表页, 降临讨伐目标) → 降临讨伐页签",
          decide(LORD_BATTLE, "领主战列表页", hooks_19.JOSS).id == C.NODE_降临讨伐页签)
    check("错页签自恢复：领主战目标站在降临讨伐页签上 → 回列表页",
          decide(LORD_BATTLE, "降临讨伐页签", hooks_19.LORD).id == C.NODE_列表)

    sd = drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]
    for n in hooks_19.TAB_NODES:
        check(f"{n} 不带 max_hit（页签不再竞速）", "max_hit" not in sd.get(n, {}),
              f"max_hit={sd.get(n, {}).get('max_hit')!r}")
    check("SpecialOpenLord 仍同时列出两个页签候选",
          "SpecialTabLord" in sd["SpecialOpenLord"]["next"]
          and "SpecialTabJoss" in sd["SpecialOpenLord"]["next"])
    check("子族页签覆盖：领主战只开领主战页签、关掉降临讨伐页签",
          _enabled_disabled("领主战") == (hooks_19.TAB_OF["领主战"], hooks_19.TAB_OF["降临讨伐"]))
    check("子族页签覆盖：降临讨伐只开降临讨伐页签、关掉领主战页签",
          _enabled_disabled("降临讨伐") == (hooks_19.TAB_OF["降临讨伐"], hooks_19.TAB_OF["领主战"]))

    # 真机 runner 必须按子族关掉非目标页签（#19 回归防线，见 tools/run_special_live.py）。
    runner = (TOOLS_DIR / "run_special_live.py").read_text(encoding="utf-8")
    check("真机 runner 按子族关掉非目标页签（_apply_target_tab_override + tab_override_for）",
          "_apply_target_tab_override(ov, a.dungeon)" in runner and "tab_override_for" in runner)
    check("挂点 tab-target-driven 已点亮", hooks_19.probe_tab_target_driven() is True)


def _enabled_disabled(子族: str):
    """该子族覆盖里「启用的页签 / 关掉的页签」（用 expected == __NONE__ 判定）。"""
    from scene.chain import tab_override_for

    ov = tab_override_for(子族)
    enabled = disabled = None
    for node, spec in ov.items():
        exp = ((spec.get("recognition") or {}).get("param") or {}).get("expected")
        if exp == ["__NONE__"]:
            disabled = node
        else:
            enabled = node
    return (enabled, disabled)


# ---------------------------------------------------------------------------
# 2. 确定性复现：旧形态死循环 / 新形态到达
# ---------------------------------------------------------------------------
def test_offline_loop_repro() -> None:
    print("\n== 2. 确定性复现 #13 死循环：结算后重进（含页签已被切到另一子族） ==")
    new = hooks_19.scenarios()
    print("     新形态（页签由目标子族决定）：")
    for k, v in new.items():
        print(f"       {k} -> {v}")
    for k, v in new.items():
        check(f"新形态「{k}」到达目标行", v == "到达", f"got={v}")

    # 旧形态：在临时副本上还原 max_hit: 1（页签竞速）。
    root = hooks_19._temp_pipeline_copy()
    try:
        hooks_19._restore_max_hit(root / "pipeline")
        old = hooks_19.scenarios(root / "pipeline")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("     旧形态（还原 max_hit: 1，页签竞速）：")
    for k, v in old.items():
        print(f"       {k} -> {v}")
    # ★#29 影响★：「页签已被切到另一子族」的两个用例 = #19 的页签竞速缺陷，旧形态必死循环。
    for k in ("领主战·页签已被切到降临讨伐", "降临讨伐·页签已被切到领主战"):
        check(f"旧形态「{k}」死循环（复现 #19 页签竞速缺陷）", old[k] == "死循环", f"got={old[k]}")
    # 「结算后重进」本就站在正确页签上：max_hit 竞速此时不构成缺陷。#29 之前它之所以也被
    # 拖进死循环，靠的是「归位在列表页抢跑」（那正是 #29 要修的 bug）；#29 收紧归位后，
    # 这两例直接由 SpecialEnterBoss 到达目标行。
    for k in ("领主战·结算后重进", "降临讨伐·结算后重进"):
        check(f"旧形态「{k}」到达（本就在正确页签上；#29 后不再被归位抢跑）",
              old[k] == "到达", f"got={old[k]}")
    check("挂点 settle-return-recovers 已点亮", hooks_19.probe_settle_return_recovers() is True)


# ---------------------------------------------------------------------------
# 3. 无漂移 + #9 守卫仍绿 + prove-red
# ---------------------------------------------------------------------------
def test_drift_guards_prove_red() -> None:
    print("\n== 3. 无漂移 + #9 守卫仍绿 + prove-red 成立 ==")
    check("真实树无漂移（check_all == []）", drift.check_all(repo_root=REPO_ROOT) == [],
          f"drift={drift.check_all(repo_root=REPO_ROOT)[:2]}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")
    check("hooks_19.prove_red() 成立（还原 max_hit / 改坏链页签各自变红）",
          hooks_19.prove_red() is True)


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 72)
    print("离线单测：#19 结算后「页签翻转+归位弹跳」死循环 —— 页签由目标子族决定 + 复现")
    print("=" * 72)
    test_tab_target_driven()
    test_offline_loop_repro()
    test_drift_guards_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
