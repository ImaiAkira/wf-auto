# -*- coding: utf-8 -*-
"""#47 幻想连战共斗房「停留时钟」缺陷：离线守卫集合（独立可跑）。

    .venv\\Scripts\\python.exe tools\\test_coop_stop.py

它把 hooks_47 的四个守卫集中跑一遍，便于单独定位；契约入口（test_offline_contract）
仍会通过 HOOKS 自动发现同一批守卫。

覆盖：
  1. 共斗房停留时钟不被『挑战后的 loading / unknown』过渡帧清零；房间↔招募弹窗来回不清零；
     真正离开（开战/结算/回关卡页…）才清零；
  2. 离线复现真机 Q2 循环（房间→挑战→loading→房间×8）→ 有界收工真的会触发，
     刚进房不误收工，开战清零；
  3. 超时是 StopTask 优雅收工，且 PhantomGiveUp 排在 PhantomStall（phantom_restart）之前；
  4. 另一条分支连通（队友到了 → 开战 → 推进）。
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

from contract_hooks import hooks_47 as h47  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# 承重注释（不许改坏 special_dungeon.json 的这几句；hard rule）。
_BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


def test_bearing_phrases_intact() -> None:
    print("\n== 0. special_dungeon.json 承重注释零丢失 ==")
    text = (ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json").read_text(
        encoding="utf-8"
    )
    for phrase in _BEARING_PHRASES:
        check(f"仍含「{phrase}」", phrase in text)


def test_clock_sticky() -> None:
    print("\n== 1. 共斗房停留时钟不被 loading/unknown 过渡帧清零 ==")
    msgs = h47._clock_failures(h47.phantom_module())
    check("phantom-coop-room-dwell-clock-sticky", msgs == [], "; ".join(msgs[:2]))


def test_bounded_stop_repro() -> None:
    print("\n== 2. 离线复现 Q2 循环 → 有界收工真的触发 ==")
    msgs = h47._bounded_stop_repro_failures(h47.phantom_module())
    check("phantom-coop-room-bounded-stop-repro", msgs == [], "; ".join(msgs[:2]))
    ph = h47.phantom_module()
    hit, reason = h47._drive_giveup(ph, state="phantom_coop_room", coop_room_sec=120.0, backdate=300.0)
    check("停留 300s(>120s) → 命中收工且原因点名共斗房", hit and "共斗房" in reason, reason)
    hit_fresh, reason_fresh = h47._drive_giveup(
        ph, state="phantom_coop_room", coop_room_sec=120.0, backdate=1.0
    )
    check("刚进房不误收工", not hit_fresh, reason_fresh)


def test_stop_not_restart() -> None:
    print("\n== 3. 超时是优雅收工 StopTask，且排在卡死兜底（强杀重启）之前 ==")
    msgs = h47._stop_not_restart_failures()
    check("phantom-coop-room-stop-not-restart", msgs == [], "; ".join(msgs[:2]))
    files = h47.load_files()
    disp = h47._node("PhantomDispatch", files) or {}
    nxt = list(disp.get("next") or [])
    check(
        "PhantomGiveUp 在 PhantomStall 之前",
        nxt.index("PhantomGiveUp") < nxt.index("PhantomStall"),
        f"GiveUp@{nxt.index('PhantomGiveUp')} Stall@{nxt.index('PhantomStall')}",
    )


def test_advance_path_intact() -> None:
    print("\n== 4. 另一条分支连通（队友到了 → 开战 → 推进） ==")
    msgs = h47._advance_path_failures()
    check("phantom-coop-room-advance-path-intact", msgs == [], "; ".join(msgs[:2]))


def test_prove_red() -> None:
    print("\n== 5. 破坏实验（倒回旧时钟规则 / 调换收工与强杀顺序 → 守卫变红） ==")
    check("hooks_47.prove_red()", h47.prove_red() is True)


def main() -> int:
    test_bearing_phrases_intact()
    test_clock_sticky()
    test_bounded_stop_repro()
    test_stop_not_restart()
    test_advance_path_intact()
    test_prove_red()
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("test_coop_stop: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
