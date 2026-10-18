# -*- coding: utf-8 -*-
"""#56 二批：自动的切换移到「战斗外」（运维五大裁决）—— 离线一键守卫入口。

    .venv\\Scripts\\python.exe tools\\test_auto_outside.py

把 hooks_auto_outside 的八个守卫集中跑一遍（便于单独定位），再加 prove-red。判据全在
纯 Python + 配置数据 + pipeline JSON + 已入库裁片/真机帧上，**不需要游戏 / 设备**。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent"), str(TOOLS / "contract_hooks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from contract_hooks import hooks_auto_outside as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def test_hooks_green() -> None:
    print("\n== 1. hooks_auto_outside 九个守卫点亮（probe=True） ==")
    check("自动按钮按定位（不写死坐标）", h.probe_auto_switch_located() is True)
    check("标签裁片命中自动、不误命中自动续战", h.probe_auto_switch_template_distinct() is True)
    check("状态读对开/关", h.probe_auto_switch_state_read_correct() is True)
    check("战斗内不再有自动切换", h.probe_auto_switch_no_in_battle() is True)
    check("覆盖所有模式编队页的自动检查", h.probe_auto_switch_cross_mode_team_auto() is True)
    check("自动续战保持关", h.probe_auto_switch_cont_kept_off() is True)
    check("续战 OCR 整串锚定", h.probe_auto_switch_resume_anchored() is True)
    check("归位在编队页先点返回", h.probe_auto_switch_return_home_back_first() is True)
    check("自动只在编队页/房间页认（战斗 HUD 不误命中）", h.probe_auto_switch_page_scoped() is True)


def test_prove_red() -> None:
    print("\n== 2. 破坏实验：逐一改坏实现，守卫必须各自变红 ==")
    check("hooks_auto_outside.prove_red()", h.prove_red() is True)


def main() -> int:
    print("=" * 72)
    print("#56 二批：自动的切换移到「战斗外」（定位 / 读状态 / 战斗内不切 / 归位先返回）")
    print("=" * 72)
    test_hooks_green()
    test_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_auto_outside: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
