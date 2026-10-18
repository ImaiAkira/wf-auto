# -*- coding: utf-8 -*-
"""#109：``^挑战$`` 漏掉带箭头的『挑战→』—— 离线一键守卫入口。

    python tools\\test_challenge_arrow.py

直接 import 两个真源模块（``scene.auto_switch`` / ``scene.page_rules``）里的常量与函数，
断言编队页底部【挑战】的**两种真机渲染**（``挑战`` / ``挑战→``）都判成「编队页」，
再跑 :mod:`tools.contract_hooks.hooks_109` 的三个契约与 prove-red。

判据全在纯 Python + 配置数据 + pipeline JSON 上，**不需要游戏 / 设备 / 框架依赖**。
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "tools" / "contract_hooks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: 取**子模块**（``scene/__init__`` 把同名函数导出到包上，属性会被遮蔽成函数）。
AUTO_SWITCH = importlib.import_module("scene.auto_switch")
PAGE_RULES = importlib.import_module("scene.page_rules")

import hooks_109 as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 页面锚点（scene.auto_switch.TEAM_PAGE_ANCHORS / page_is_team）
# ---------------------------------------------------------------------------
def test_page_anchors() -> None:
    print("\n== 1. 页面锚点 scene.auto_switch.page_is_team 两种渲染都认 ==")
    for text, box in h.TEAM_PAGE_TEXTS:
        check(
            f"『{text}』被认成编队页",
            AUTO_SWITCH.page_is_team([(text, list(box))]) is True,
            f"TEAM_PAGE_ANCHORS={AUTO_SWITCH.TEAM_PAGE_ANCHORS!r}",
        )
    # 两种渲染必须由**同一个**锚点正则覆盖（不是新增一条并列项蒙对）。
    arrows = [p for p in AUTO_SWITCH.TEAM_PAGE_ANCHORS if p.startswith("^挑战")]
    check("只有一条『挑战』锚点（单一判据，不是两条并列）", len(arrows) == 1, f"{arrows!r}")
    check("该锚点同时命中『挑战』与『挑战→』",
          bool(arrows) and all(re.search(arrows[0], t) for t, _b in h.TEAM_PAGE_TEXTS),
          f"{arrows[0] if arrows else '<缺失>'!r}")
    # 反例：整串锚定不许退化成裸「挑战」。
    for bad in h.NEGATIVE_TEXTS:
        check(f"反例『{bad}』不被误认成编队页",
              AUTO_SWITCH.page_is_team([(bad, [297, 1069, 80, 47])]) is False)


# ---------------------------------------------------------------------------
# 2. 页面判据（scene.page_rules「编队页」）
# ---------------------------------------------------------------------------
def test_page_rule() -> None:
    print("\n== 2. 页面判据 scene.page_rules「编队页」两种渲染都命中 ==")
    rule = PAGE_RULES.page_rule("编队页").recognition
    expected = (rule.get("param") or {}).get("expected") or []
    check("判据是 OCR 型", rule.get("type") == "OCR", f"{rule.get('type')!r}")
    check("判据里没有遗留的孤立 ^挑战$", h.BLIND not in expected, f"expected={expected!r}")
    for text, box in h.TEAM_PAGE_TEXTS:
        check(f"『{text}』命中编队页判据", h._ocr_hits(rule, text, list(box)) is True,
              f"expected={expected!r} roi={(rule.get('param') or {}).get('roi')!r}")
    for bad in h.NEGATIVE_TEXTS:
        check(f"反例『{bad}』不命中编队页判据",
              h._ocr_hits(rule, bad, [297, 1069, 80, 47]) is False)
    # 静态注册表与 page_rule() 必须是同一份（ADR-0003：判据全局唯一）。
    via_list = next(r for r in PAGE_RULES.PAGE_RULES if r.name == "编队页")
    check("PAGE_RULES 与 page_rule() 同源", via_list.recognition == rule)


# ---------------------------------------------------------------------------
# 3. 正则本身（逐串单测，与上面两条判据解耦）
# ---------------------------------------------------------------------------
def test_regex_shape() -> None:
    print("\n== 3. 正则形状：`^挑战(→)?$` = 只多容忍**一个**箭头 ==")
    pat = r"^挑战(→)?$"
    for good in ("挑战", "挑战→"):
        check(f"{pat} 命中『{good}』", re.search(pat, good) is not None)
    for bad in ("挑战→→", "→挑战", "再次挑战", "继续挑战", "挑战深渊连战EX", "挑战 ", "挑战x"):
        check(f"{pat} 不命中『{bad}』", re.search(pat, bad) is None)
    # 记录旧形态的病：^挑战$ 认不出带箭头的帧（本票的存在理由）。
    check("旧形态 ^挑战$ 确实漏掉『挑战→』（本票要修的 bug）",
          re.search(h.BLIND, "挑战→") is None)


# ---------------------------------------------------------------------------
# 4. 三个契约 + 破坏实验
# ---------------------------------------------------------------------------
def test_hooks_green() -> None:
    print("\n== 4. hooks_109 三个契约点亮（probe=True） ==")
    check("两种渲染都判成编队页（T1）", h.probe_challenge_arrow_page_criteria() is True)
    check("判据单源：page_rules ⊆ SpecialChallenge（T2）", h.probe_challenge_single_source() is True)
    check("仓里无活跃的孤立 ^挑战$（T3）", h.probe_challenge_no_blind_anchor() is True)


def test_prove_red() -> None:
    print("\n== 5. 破坏实验：改回 ^挑战$ / 只改一处 / 真源不改 / 放宽成裸「挑战」 ==")
    check("hooks_109.prove_red()（四条破坏各自变红）", h.prove_red() is True)


def main() -> int:
    print("=" * 72)
    print("#109：编队页底部【挑战】有 `挑战` 与 `挑战→` 两种渲染 —— 判据必须都认")
    print("=" * 72)
    test_page_anchors()
    test_page_rule()
    test_regex_shape()
    test_hooks_green()
    test_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL GREEN —— 两种渲染都判成编队页，判据单源，仓里无活跃的孤立 ^挑战$")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
