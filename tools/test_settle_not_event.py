# -*- coding: utf-8 -*-
"""离线单测：#27 结算不再被「打断型事件」抢帧 —— 链上结算节点会被评估，收工闸有机会。

不需要游戏（判定全在事件层 / pipeline 结构 / 结算动作的 stub 上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_settle_not_event.py

覆盖 #27 的验收：

  1. **结算不再是打断型事件**：``结算`` 不在 ``INTERRUPT_EVENTS``，其节点
     （``PubResultContinue`` / ``PubQuestResult``）不在打断组里；九类异常分类仍在场；
  2. **守卫：链上页面 ∩ 打断型事件 = ∅**（``scene.drift.chain_page_interrupt_drift``；
     违反 → 红）；pipeline 里不再有抢帧的 ``[JumpBack]PubResultContinue`` /
     ``[JumpBack]PubQuestResult``；
  3. **离线复现本次遮蔽**（结算帧，确定性）：旧形态（前缀塞回 PubResultContinue）首个命中
     是抢帧者、链上结算节点 ``SpecialResultContinue`` **永不执行**；新形态首个命中是链上
     结算节点、它**执行**，且 #22 的收工闸在 stub 下把它的 next 覆盖成 ``SpecialBatchStop``；
  4. **破坏实验**：把结算塞回打断前缀 / 塞回打断事件组 → 守卫变红（prove-red 在 hooks_27）；
  5. **无漂移 + #9 守卫仍绿 + 三条既有路径（幻想 / 战阵 / 迷宫）结构不变**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_27.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_27  # noqa: E402
from scene import drift  # noqa: E402
from scene.events import EXCEPTION_EVENTS, INTERRUPT_EVENTS  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _files() -> dict:
    return drift.load_pipelines(PIPELINE_DIR)


# ---------------------------------------------------------------------------
# 1. 结算不再是打断型事件
# ---------------------------------------------------------------------------
def test_settle_not_interrupt() -> None:
    print("\n== 1. 结算不再是打断型事件（分类仍在场） ==")
    names = [e.name for e in INTERRUPT_EVENTS]
    check("「结算」不在 INTERRUPT_EVENTS", "结算" not in names, f"names={names}")
    nodes = {n for e in INTERRUPT_EVENTS for n in e.nodes}
    check("抢帧节点 PubResultContinue / PubQuestResult 不在打断组里",
          not ({"PubResultContinue", "PubQuestResult"} & nodes))
    check("「结算」仍在九类异常分类里（taxonomy 不变）",
          "结算" in [e.name for e in EXCEPTION_EVENTS])
    check("九类分类仍是 9 条", len(EXCEPTION_EVENTS) == 9, f"got={len(EXCEPTION_EVENTS)}")


# ---------------------------------------------------------------------------
# 2. 守卫：链上页面 ∩ 打断型事件 = ∅
# ---------------------------------------------------------------------------
def test_guard_chain_pages_disjoint() -> None:
    print("\n== 2. 守卫：链上页面 ∩ 打断型事件 = ∅（链上页面不再被注入为打断） ==")
    check("chain_page_interrupt_drift(真实树) == []",
          drift.chain_page_interrupt_drift(REPO_ROOT) == [],
          f"msgs={drift.chain_page_interrupt_drift(REPO_ROOT)[:1]}")
    check("check_all(真实树) == []", drift.check_all(repo_root=REPO_ROOT) == [])
    check("挂点 settle-not-interrupt-event 已点亮",
          hooks_27.probe_settle_not_interrupt_event() is True)
    # 产物里不再有抢帧前缀（#26 的 PubResultContinue / PubQuestResult）。
    sd = _files().get("special_dungeon.json") or {}
    refs = {x for s in sd.values() if isinstance(s, dict) for x in (s.get("next") or [])}
    check("pipeline 无 [JumpBack]PubResultContinue / PubQuestResult",
          not (set(hooks_27.OLD_INTERRUPT_REFS) & refs),
          f"left={sorted(set(hooks_27.OLD_INTERRUPT_REFS) & refs)}")


# ---------------------------------------------------------------------------
# 3. 离线复现遮蔽（结算帧）
# ---------------------------------------------------------------------------
def test_offline_shadowing_repro() -> None:
    print("\n== 3. 离线复现本次遮蔽（结算帧，确定性） ==")
    files = _files()
    real = list((files["special_dungeon.json"]["SpecialBattleWait"] or {}).get("next") or [])
    old = [real[0], *hooks_27.OLD_INTERRUPT_REFS, *real[1:]]

    old_first = hooks_27._first_hit(old, files)
    new_first = hooks_27._first_hit(real, files)
    old_seq = hooks_27.settlement_trace(old, files, max_steps=6)
    new_seq = hooks_27.settlement_trace(real, files, max_steps=6)

    print(f"     结算帧 = {hooks_27.SETTLE_FRAME}")
    print(f"     旧形态首命中 = {old_first}   序列 = {' → '.join(old_seq)}")
    print(f"     新形态首命中 = {new_first}   序列 = {' → '.join(new_seq)}")

    check("旧形态首命中 = 抢帧者 PubResultContinue", old_first == "[JumpBack]PubResultContinue")
    check("旧形态里链上结算节点 SpecialResultContinue 永不执行",
          "SpecialResultContinue" not in old_seq, f"seq={old_seq}")
    check("旧形态复现「前缀反复抢帧」死循环（同一节点反复命中）",
          old_seq == ["PubResultContinue"] * 6, f"seq={old_seq}")
    check("新形态首命中 = 链上结算节点 SpecialResultContinue", new_first == "SpecialResultContinue")
    check("新形态里链上结算节点真的执行", "SpecialResultContinue" in new_seq, f"seq={new_seq}")

    # 链上结算节点执行 -> #22 的收工闸有机会（stub 下打满 -> 指向 SpecialBatchStop）。
    gate = hooks_27._gate_fires()
    check("链上结算节点执行后 #22 收工闸落 SpecialBatchStop（收工）", gate is True)
    check("终端映射：收工 = SpecialBatchStop",
          (files["special_dungeon.json"]["SpecialBatchStop"] or {}).get("action", {}).get("type")
          == "StopTask")
    check("挂点 settle-chain-node-reachable 已点亮",
          hooks_27.probe_settle_chain_node_reachable() is True)


# ---------------------------------------------------------------------------
# 4. 破坏实验（prove-red）
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 4. 破坏实验：塞回打断前缀 / 塞回打断事件组 -> 守卫变红 ==")
    check("hooks_27.prove_red() 成立", hooks_27.prove_red() is True)


# ---------------------------------------------------------------------------
# 5. 三条既有路径（幻想 / 战阵 / 迷宫）结构不变
# ---------------------------------------------------------------------------
def test_three_paths_unchanged() -> None:
    print("\n== 5. #9 三条既有路径结构守卫仍绿（幻想 / 战阵 / 迷宫） ==")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 72)
    print("离线单测：#27 结算不再被「打断型事件」抢帧（链上结算节点可执行）")
    print("=" * 72)
    test_settle_not_interrupt()
    test_guard_chain_pages_disjoint()
    test_offline_shadowing_repro()
    test_prove_red()
    test_three_paths_unchanged()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
