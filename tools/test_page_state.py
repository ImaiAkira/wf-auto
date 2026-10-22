# -*- coding: utf-8 -*-
"""#112：``agent/`` 的**页面状态判据**（「这一帧算不算编队页」）—— 离线一键守卫入口。

    .venv\\Scripts\\python.exe tools\\test_page_state.py

直接 import **改后的函数**并断言（不需要游戏 / 设备 / 框架会话）：

1. **快照 == 真源**：``agent/battle_loop_core.PAGE_CHALLENGE_PATTERNS``（安装态逐字快照，
   因为 ``agent/`` 没有 ``scene/``）与 ``scene.challenge.CHALLENGE_CLICK_PATTERNS`` 逐项相等；
   ``abyss_impl`` / ``wuchong_impl`` 取的是**同一个对象**（不是各自抄一份）。
2. **判据层正反例**：``挑战`` / ``挑战→`` 判 True；``再次挑战 / 继续挑战 / 挑战深渊连战 /
   挑战深渊连战EX / 高难挑战 / 连续挑战次数 / 挑战→→ / →挑战`` 全判 False —— 即
   ``scene.challenge.REJECTED_TEXTS`` 一个都不中（``(→)?`` 不是 ``(→)*``，也不是 ``.*``）。
   同时**自证 bug 存在**：旧写法 ``any(t == "挑战")`` 仍漏 ``挑战→``（否则本票没有修的东西）。
3. **三处 classify 层**（``battle_loop_core.classify``(phantom 场景) / ``abyss_impl.classify`` /
   ``wuchong_impl.classify``）：两种渲染都判成**编队页**；反例都不是编队页（走别的分支可以，
   走成编队页就是走错分支）。
4. **ratchet 绿**：``agent/`` 里没有未登记的「逐字相等」页面状态判据。
5. ``hooks_112`` 三个契约点亮 + ``prove_red()``（三条破坏各自变红）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (
    str(ROOT),
    str(ROOT / "tools"),
    str(ROOT / "tools" / "contract_hooks"),
    str(ROOT / "agent"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: 取**子模块**（``scene/__init__`` 把同名函数导出到包上，属性会被遮蔽成函数）。
CHALLENGE = importlib.import_module("scene.challenge")

import abyss_impl as ab  # noqa: E402
import battle_loop_core as core  # noqa: E402
import phantom_impl as ph  # noqa: E402
import wuchong_impl as wc  # noqa: E402

import hooks_112 as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


#: 旧写法（**运行时拼出来**：本文件必须点名被废除的形状，但不该成为一次「活跃使用」——
#: 与 hooks_110._OLD_SHAPE / hooks_109.BLIND 同一手法）。
_OLD_ANCHOR = "^挑战" + "$"


def _old_predicate(texts):
    """#112 之前的实现（逐字相等）—— 只用来证明 bug 真实存在。"""
    return any(t == "挑战" for t in (texts or ()))


# ---------------------------------------------------------------------------
# 1. 快照 == 真源（agent 是安装态：只能逐字快照，不能 import）
# ---------------------------------------------------------------------------
def test_snapshot_is_truth() -> None:
    print("\n== 1. 页面状态快照 == 真源 scene/challenge（逐字）+ 只有一处落点 ==")
    truth = tuple(CHALLENGE.CHALLENGE_CLICK_PATTERNS)
    check("真源形状仍是 ^挑战(→)?$（整串 + 至多一个箭头）",
          truth == (r"^挑战(→)?$",), f"{truth!r}")
    check("agent/battle_loop_core.PAGE_CHALLENGE_PATTERNS 逐字等于真源",
          tuple(core.PAGE_CHALLENGE_PATTERNS) == truth,
          f"{tuple(core.PAGE_CHALLENGE_PATTERNS)!r}")
    check("快照与真源是**逐项**相等（不是长度碰巧相等）",
          list(core.PAGE_CHALLENGE_PATTERNS) == list(truth))
    for name, mod in (("abyss_impl", ab), ("wuchong_impl", wc)):
        check(f"{name}.has_challenge_page_text 是 battle_loop_core 的同一个对象",
              getattr(mod, "has_challenge_page_text", None) is core.has_challenge_page_text)
        check(f"{name} 没有自己抄一份快照",
              getattr(mod, h.SNAPSHOT_ATTR, None) is None,
              f"{getattr(mod, h.SNAPSHOT_ATTR, None)!r}")
    # phantom 走 SceneConfig 复用 core.classify —— 它不该有第二份判据。
    check("phantom_impl.classify 就是 core.classify 的绑定（没有第二份判据）",
          ph.classify.func is core.classify)


# ---------------------------------------------------------------------------
# 2. 判据层：正反例
# ---------------------------------------------------------------------------
def test_predicate_positives_and_negatives() -> None:
    print("\n== 2. 判据层：挑战 / 挑战→ 判 True，真源反例表一个都不中 ==")
    for text in h.RENDERINGS:
        check(f"正例『{text}』判 True", core.is_challenge_page_text(text) is True)
        check(f"正例『{text}』(has_challenge_page_text) 判 True",
              core.has_challenge_page_text([text]) is True)
    check("空白被容忍（OCR 常带首尾空白）",
          core.is_challenge_page_text("  挑战→ ") is True)
    check("空串 / None 不算",
          core.is_challenge_page_text("") is False
          and core.is_challenge_page_text(None) is False)

    rejects = tuple(CHALLENGE.REJECTED_TEXTS)
    for text in rejects:
        check(f"反例『{text}』判 False", core.is_challenge_page_text(text) is False)
    # 需求点名的那些必须在真源反例表里（别靠「恰好没写进去」蒙混）。
    for must in h.REQUIRED_REJECTS:
        check(f"反例表覆盖『{must}』", must in rejects)

    # 自证 bug：旧写法在两种渲染里只认一种 —— 这正是本票要修的东西。
    check("旧写法（逐字相等）仍漏『挑战→』（本票要修的 bug）",
          _old_predicate(["挑战→"]) is False and _old_predicate(["挑战"]) is True)
    check(f"旧形态 {_OLD_ANCHOR!r} 仍不命中『挑战→』（真机 8/17 帧会漏）",
          CHALLENGE.matches("挑战→") is True and
          importlib.import_module("re").search(_OLD_ANCHOR, "挑战→") is None)


# ---------------------------------------------------------------------------
# 3. 三处 classify 层
# ---------------------------------------------------------------------------
def test_classify_both_renderings() -> None:
    print("\n== 3. 三处 classify：两种渲染都判成编队页；反例不是编队页 ==")
    classifiers = h._classifiers()
    check("三处 classify 都被覆盖", len(classifiers) == 3,
          f"{[c[0] for c in classifiers]!r}")
    for label, classify, team_state in classifiers:
        for text in h.RENDERINGS:
            got = classify(h._frame(text, h.READING_BOXES[text]))
            check(f"{label}：『{text}』-> {team_state}", got == team_state, f"实际 {got!r}")
        for text in CHALLENGE.REJECTED_TEXTS:
            got = classify(h._frame(text, h.NEGATIVE_BOX))
            check(f"{label}：反例『{text}』不是编队页", got != team_state, f"实际 {got!r}")
        # 旧实现复现：同样的帧喂给「逐字相等」版判据 → 带箭头那一帧判不出来。
        old_state = team_state if _old_predicate(["挑战→"]) else "<旧写法判不出>"
        check(f"{label}：旧写法在『挑战→』帧上确实判不出编队页",
              old_state != team_state)


# ---------------------------------------------------------------------------
# 4. ratchet
# ---------------------------------------------------------------------------
def test_ratchet() -> None:
    print("\n== 4. ratchet：agent/ 里没有未登记的逐字相等页面状态判据 ==")
    check("LITERAL_EQUALITY_EXEMPT 每条都能指到东西（无影子豁免）",
          h.probe_page_state_challenge_ratchet() is True,
          f"{h._ratchet_failures()[:2]}")
    check("豁免表非空（内含 set 1 / 时间 / 自动 等已登记同类落点；全部写明理由）",
          len(h.LITERAL_EQUALITY_EXEMPT) >= 5 and all(
              isinstance(v, str) and len(v) > 4 for v in h.LITERAL_EQUALITY_EXEMPT.values()),
          f"{len(h.LITERAL_EQUALITY_EXEMPT)} 条")
    check("豁免表里没有『挑战』（那颗按钮必须是共享判据，绝不允许豁免）",
          not [k for k in h.LITERAL_EQUALITY_EXEMPT if k[1] in ("挑战", "挑战→")])


# ---------------------------------------------------------------------------
# 5. 守卫 + 破坏实验
# ---------------------------------------------------------------------------
def test_hooks_green() -> None:
    print("\n== 5. hooks_112 三个契约点亮（probe=True） ==")
    check("T1 快照 == 真源（逐字）", h.probe_page_state_challenge_snapshot() is True)
    check("T2 ratchet", h.probe_page_state_challenge_ratchet() is True)
    check("T3 两种渲染都算编队页", h.probe_page_state_challenge_both_renderings() is True)


def test_prove_red() -> None:
    print("\n== 6. 破坏实验：改回 == \"挑战\" / 快照漂移 / 行为倒退 ==")
    check("hooks_112.prove_red()（三条破坏各自变红）", h.prove_red() is True)


def main() -> int:
    print("=" * 78)
    print("#112：agent/ 的页面状态判据 —— `挑战` / `挑战→` 两种渲染都算「编队页」")
    print("=" * 78)
    test_snapshot_is_truth()
    test_predicate_positives_and_negatives()
    test_classify_both_renderings()
    test_ratchet()
    test_hooks_green()
    test_prove_red()
    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL GREEN —— 页面状态判据已与 scene/challenge 真源同形，两种渲染都算编队页，反例全不中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
