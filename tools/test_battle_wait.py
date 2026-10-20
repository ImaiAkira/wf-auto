# -*- coding: utf-8 -*-
"""#33 长战斗把守（离线，独立可跑）。

    .venv\\Scripts\\python.exe tools\\test_battle_wait.py

把 hooks_33 的三个守卫集中跑一遍（契约入口 test_offline_contract.py 也会经 HOOKS 自动发现
同一批守卫）：

  1. 长战斗是【正常等待】（运维裁决）：开打等待上限由游戏自身上限派生、**严格 > 300s**，
     force-end 分支记明原因（绝不静默跳过）；收工路径受 is_battle_hud 门控（战斗 HUD 帧上不收工）。
  2. 归位认识【实时战斗页】（RETURN_HOME_RULES 的 live_battle）：认战斗 HUD、**等它打完**（读后动、
     不点击、有界带原因停手），且不抢主城 / GAMEOVER。
  3. prove-red：四处破坏，要求守卫各自变红。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
HOOKS = TOOLS / "contract_hooks"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent"), str(HOOKS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from contract_hooks import hooks_33 as h33  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def test_long_fight_waited() -> None:
    print("\n== 1. 长战斗是正常等待：等待上限 > 300s 且由游戏自身上限派生 ==")
    msgs = h33.long_fight_wait_failures()
    check("battle-wait-long-fight-waited", msgs == [], "; ".join(msgs[:3]))


def test_no_finalize_while_hud() -> None:
    print("\n== 2. 收工路径受 is_battle_hud 门控（战斗帧上不收工） ==")
    msgs = h33.finalize_guard_failures()
    check("battle-plan-no-finalize-while-hud", msgs == [], "; ".join(msgs[:3]))


def test_return_home_live_battle() -> None:
    print("\n== 3. 归位认实时战斗页并等它打完（读后动、有界） ==")
    msgs = h33.live_battle_failures()
    check("return-home-live-battle-waited", msgs == [], "; ".join(msgs[:3]))


def test_prove_red() -> None:
    print("\n== 4. prove-red：四处破坏 -> 守卫各自变红 ==")
    check("hooks_33.prove_red()", h33.prove_red() is True)


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    test_long_fight_waited()
    test_no_finalize_while_hud()
    test_return_home_live_battle()
    test_prove_red()
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("test_battle_wait: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
