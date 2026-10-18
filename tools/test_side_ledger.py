# -*- coding: utf-8 -*-
"""离线单测：#51 ``run_side_live.py`` 三个账本节点 hit=False —— 读后动 + 空列表明确收工。

不需要游戏 / 设备（判据全在真机帧的 OCR 条目上，逐字内嵌于 ``hooks_51.py``）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_side_ledger.py
    .venv\\Scripts\\python.exe tools\\test_side_ledger.py --prove-red

覆盖 #51 的验收：

  1. **真实结构**（真机帧 tools/frames/event_stage_list.png）：点第一张卡后是外传关卡列表
     （NEW/COMPLETE!! 徽标 + STORY / 战斗 标签 + 关卡标题），``parse_side_rows`` /
     ``select_side_stage`` 正确解析，``SideNextStory`` 选中 STORY 行 —— 三个账本节点在真实
     结构上**本来就能命中**；
  2. **空列表明确收工**（真机帧 tools/frames/side_story_list_empty.png）：relayB 的
     hit=False 根因是该账号「未通关」列表为空（「未找到符合的外传故事」），
     ``entry_decision`` 必须【明确收工并给出原因】，绝不静默、绝不盲点固定坐标；
  3. **读后动**：非空列表 -> 点【识别到的第一张卡标记框中心】；
  4. **记账纪律**（与 #44 同）：记账只在【真正进入关卡列表（有徽标）】之后发生；
  5. **破坏实验**：改坏 entry_decision / has_stage_badge / 摘掉进入后复核 -> 守卫各自变红；
  6. **无漂移 + #9 三条既有路径守卫仍绿**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_51.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR), str(REPO_ROOT / "agent"), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402

import hooks_51 as h51  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 真实结构：关卡列表解析 + SideNextStory 选中 STORY 行
# ---------------------------------------------------------------------------
def test_real_structure() -> None:
    print("\n== 1. 真实结构：外传关卡列表（真机帧 event_stage_list.png）==")
    sr = h51._sr()
    rows = sr.parse_side_rows(h51.STAGE_LIST_ITEMS)
    print(f"     parse_side_rows -> {len(rows)} 行")
    for r in rows:
        print(f"       {r['name']!r:20} type={r['type']!r:8} badge={r['badge']!r}")
    sel = sr.select_side_stage(rows, row_type_regex="STORY", check_badge=True)
    print(f"     SideNextStory 选中 -> {sel['name']!r}" if sel else "     SideNextStory 未命中")

    check("挂点 side-stage-advances-with-ledger 已点亮（probe=True）",
          h51.probe_side_stage_advances_with_ledger() is True)
    check("真实关卡列表解析出 3 行", len(rows) == 3)
    check("SideNextStory 选中 STORY 行（账本驱动选关在真实结构上命中）",
          sel is not None and sel["name"] == h51.EXPECTED_STORY_STAGE,
          f"got={sel['name'] if sel else None!r}")
    check("真实关卡列表带 NEW/COMPLETE!! 徽标（require_badge 前提）",
          h51._rl().has_stage_badge(h51.STAGE_LIST_ITEMS) is True)


# ---------------------------------------------------------------------------
# 2. 空列表：明确收工并给出原因（relayB 的真实现场）
# ---------------------------------------------------------------------------
def test_empty_list_stops() -> None:
    print("\n== 2. 空「未通关」列表 -> 明确收工（真机帧 side_story_list_empty.png）==")
    rl = h51._rl()
    decision, payload, reason = rl.entry_decision(h51.EMPTY_LIST_ITEMS)
    print(f"     entry_decision -> {decision!r} payload={payload!r}")
    print(f"     reason = {reason}")

    check("挂点 side-entry-empty-list-stops 已点亮（probe=True）",
          h51.probe_side_entry_empty_list_stops() is True)
    check("空列表 -> decision=stop", decision == "stop")
    check("空列表 -> 不给点击目标（绝不盲点固定坐标）", payload is None)
    check("空列表 -> 给出明确原因（不静默 hit=False）",
          bool(reason) and ("空" in reason or "未找到" in reason))
    check("空列表不被误判成关卡列表", rl.has_stage_badge(h51.EMPTY_LIST_ITEMS) is False)


# ---------------------------------------------------------------------------
# 3. 非空列表：读后动，点第一张卡标记框
# ---------------------------------------------------------------------------
def test_first_card_readthenact() -> None:
    print("\n== 3. 非空列表 -> 点识别到的第一张卡标记框中心 ==")
    rl = h51._rl()
    decision, payload, _reason = rl.entry_decision(h51.LIST_WITH_CARDS_ITEMS)
    print(f"     entry_decision -> {decision!r} payload={payload!r}")

    check("挂点 side-entry-reads-first-card 已点亮（probe=True）",
          h51.probe_side_entry_reads_first_card() is True)
    check("非空列表 -> decision=enter", decision == "enter")
    check("点的是第一张卡标记框（= 识别框，不是写死坐标）",
          payload is not None and list(payload) == h51.FIRST_CARD_BOX,
          f"got={payload!r}")
    check("卡片列表未被误判成关卡列表（无徽标）",
          rl.has_stage_badge(h51.LIST_WITH_CARDS_ITEMS) is False)


# ---------------------------------------------------------------------------
# 4. 记账纪律（与 #44 同）
# ---------------------------------------------------------------------------
def test_no_stale_accounting() -> None:
    print("\n== 4. 记账纪律：只在真正进入关卡列表之后记账 ==")
    check("挂点 side-no-stale-accounting 已点亮（probe=True）",
          h51.probe_side_no_stale_accounting() is True)
    check("列表页 / 空列表都不满足记账前置（无徽标）",
          h51._no_stale_accounting_failures() == [])


# ---------------------------------------------------------------------------
# 5. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 5. 破坏实验：改坏 entry_decision / has_stage_badge / 摘掉进入后复核 ==")
    check("hooks_51.prove_red() 成立", h51.prove_red() is True)


# ---------------------------------------------------------------------------
# 6. 无漂移 + #9 守卫
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 6. 无漂移 + #9 三条既有路径守卫仍绿 ==")
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
    print("离线单测：#51 外传 run_side_live 三个账本节点 hit=False —— 读后动 + 空列表明确收工")
    print("=" * 72)
    test_real_structure()
    test_empty_list_stops()
    test_first_card_readthenact()
    test_no_stale_accounting()
    test_prove_red()
    test_drift_and_guards()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
