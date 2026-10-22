# -*- coding: utf-8 -*-
"""#30 幻想连战共斗房：离线守卫集合（独立可跑）。

    .venv\\Scripts\\python.exe tools\\test_phantom_coop.py

它把 hooks_30 的三个守卫 + 承重注释/接线不变量集中跑一遍，便于单独定位；
契约入口（test_offline_contract）仍会通过 HOOKS 自动发现同一批守卫。

覆盖：
  1. 诊断/修法的前提在产物里成立：PhantomCoop* 节点在场、SpecialRecruitOpen max_hit=1、
     PubChallenge 按种类收窄/还原；
  2. 离线复现共斗房死循环（旧形态）与收窄后的开战路径；
  3. 共斗房长时间开不了战 → 有界收工（点名共斗房），刚进房不误收工；
  4. 承重注释零丢失（special_dungeon.json 那几句必须仍在）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from contract_hooks import hooks_30 as h30  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# 承重注释（#30 不许改坏 special_dungeon.json 的这几句；hard rule）。
_BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


def test_bearing_phrases_intact() -> None:
    print("\n== 1. special_dungeon.json 承重注释零丢失 ==")
    text = (ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json").read_text(
        encoding="utf-8"
    )
    for phrase in _BEARING_PHRASES:
        check(f"仍含「{phrase}」", phrase in text)


def test_guard_1_not_pubchallenge() -> None:
    print("\n== 2. 收窄 PubChallenge：不抓共斗房、仍认单人编队 ==")
    msgs = h30._pubchallenge_scope_failures()
    check("phantom-coop-room-not-pubchallenge", msgs == [], "; ".join(msgs[:2]))


def test_guard_2_loop_repro() -> None:
    print("\n== 3. 离线复现死循环 + 收窄后可开战 ==")
    msgs = h30._loop_repro_failures()
    check("phantom-coop-room-loop-repro", msgs == [], "; ".join(msgs[:2]))
    old_seq, _st, old_loop = h30.simulate_room(None)
    check("旧形态：PubChallenge 自锁死循环", old_loop and old_seq[:1] == ["PubChallenge"],
          f"seq[:4]={old_seq[:4]}")
    new_seq, new_state, new_loop = h30.simulate_room(h30.PHANTOM_ROI)
    check("新形态：招募→开始招募→挑战→开战", (not new_loop) and new_state == "battle",
          f"seq={new_seq[:6]}")


def test_guard_3_bounded_stop() -> None:
    print("\n== 4. 共斗房有界收工（点名共斗房） ==")
    msgs = h30._bounded_stop_failures()
    check("phantom-coop-room-bounded-stop", msgs == [], "; ".join(msgs[:2]))
    hit, reason = h30._coop_giveup_hit(age_sec=300.0, coop_room_sec=120.0)
    check("长时间未开战 → 命中收工且原因点名共斗房", hit and "共斗房" in reason, reason)
    hit_fresh, reason_fresh = h30._coop_giveup_hit(age_sec=1.0, coop_room_sec=120.0)
    check("刚进房不误收工", not hit_fresh, reason_fresh)


def test_pipeline_wiring() -> None:
    print("\n== 5. 产物接线（phantom.json / side_impl / phantom_impl） ==")
    msgs = h30._pipeline_bound_failures()
    check("PhantomGiveUp 声明 coop_room_sec>0", msgs == [], "; ".join(msgs[:2]))
    # PhantomCoopChallenge 不再把「点完还停在房间」当成功。
    scene_on_path = h30.scene_on_path
    scene_on_path()
    import json as _json  # noqa: PLC0415

    files = h30.load_files()
    node = h30._node("PhantomCoopChallenge", files) or {}
    act = (node.get("action") or {}).get("param") or {}
    aparam = act.get("custom_action_param") or {}
    check("PhantomCoopChallenge.expect 不含 phantom_coop_room",
          "phantom_coop_room" not in (aparam.get("expect") or []),
          f"expect={aparam.get('expect')}")
    # PubChallenge scope 纯函数存在且形态正确（正/反例帧）。
    ov = h30._pubchallenge_override("phantom")
    rec = ((ov.get("PubChallenge") or {}).get("recognition") or {})
    check("PubChallenge phantom 形态不命中共斗房挑战", not h30._ocr_hit(rec, h30.ROOM_ITEMS))
    check("PubChallenge phantom 形态仍命中单人编队挑战", h30._ocr_hit(rec, h30.SOLO_TEAM_ITEMS))


def main() -> int:
    test_bearing_phrases_intact()
    test_guard_1_not_pubchallenge()
    test_guard_2_loop_repro()
    test_guard_3_bounded_stop()
    test_pipeline_wiring()
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("test_phantom_coop: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
