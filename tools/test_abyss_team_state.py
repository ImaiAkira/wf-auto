# -*- coding: utf-8 -*-
"""离线单测：#63 深渊EX 编队页不被 ``abyss_state`` 误判成「主城」（主城锚点过松）。

不需要游戏；纯离线、确定性。直接跑：

    .venv\\Scripts\\python.exe tools\\test_abyss_team_state.py

覆盖 #63 的验收：

  1. **编队页绝非主城**：真机形态的深渊EX 编队页（``abyss_cal/10_abyss_team`` /
     ``12_abyss_team_via_row``）与五重编队页都不得判成 ``main_city``；主城帧仍正判 ``main_city``；
  2. **宽松判据危险**：含「活动+领主战」两宽松锚点、零独有锚点的真机帧不得判成主城；
  3. **单源**：主城判据（独有锚点集 + 内核）只有一份，abyss / wuchong / phantom / side 与
     harness 取同一份对象（复制即漂移）；
  4. **破坏实验**：把判据倒回六锚点「任意 ≥2」 -> 守卫变红（挂点 ``hooks_63``，
     prove-red 在 ``tools/contract_hooks/hooks_63.py``）。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_63  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def test_team_page_not_main_city() -> None:
    print("\n== 1. 编队页绝非主城（真机帧正反例） ==")
    check("挂点 abyss-team-page-not-main-city 已点亮", hooks_63.probe_abyss_team_not_main_city() is True)
    from abyss_impl import classify as ab_classify

    check("主城帧 -> main_city", ab_classify(list(hooks_63.MAIN_CITY_OCR))[0] == "main_city")
    check(
        "深渊EX 编队页(10_abyss_team) != main_city",
        ab_classify(list(hooks_63.ABYSS_TEAM_OCR))[0] != "main_city",
    )
    check(
        "深渊EX 编队页(12_abyss_team_via_row) != main_city",
        ab_classify(list(hooks_63.ABYSS_TEAM_ROW_OCR))[0] != "main_city",
    )
    from wuchong_impl import classify as wc_classify

    check(
        "五重编队页 != main_city",
        wc_classify(list(hooks_63.WUCHONG_TEAM_OCR))[0] != "main_city",
    )


def test_loose_predicate_dangerous() -> None:
    print("\n== 2. 六锚点宽松判据确实危险（收紧必要） ==")
    check(
        "六锚点在『活动+领主战』帧上命中主城",
        hooks_63._loose_main_city(hooks_63.LOOSE_DANGER_OCR) is True,
    )
    from abyss_impl import classify as ab_classify

    check(
        "收紧后该帧不再是主城",
        ab_classify(list(hooks_63.LOOSE_DANGER_OCR))[0] != "main_city",
    )


def test_single_source() -> None:
    print("\n== 3. 主城判据单源（防漂移） ==")
    check(
        "挂点 main-city-predicate-single-source 已点亮",
        hooks_63.probe_main_city_predicate_single_source() is True,
    )
    import battle_loop_core as core

    check(
        "共享独有锚点集 == 修行之道/成长任务/当前进度",
        tuple(core.MAIN_CITY_UNIQUE_ANCHORS) == ("修行之道", "成长任务", "当前进度"),
    )


def test_prove_red() -> None:
    print("\n== 4. 破坏实验（判据倒回六锚点 -> 守卫变红） ==")
    check("hooks_63.prove_red()", hooks_63.prove_red() is True)


def main() -> int:
    test_team_page_not_main_city()
    test_loose_predicate_dangerous()
    test_single_source()
    test_prove_red()
    print()
    if FAILS:
        print(f"FAILED: {FAILS}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
