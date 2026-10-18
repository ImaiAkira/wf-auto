# -*- coding: utf-8 -*-
"""#110：「挑战」按钮的**点击判据**——离线一键守卫入口。

    python tools\\test_challenge_click.py

直接 import 真源（``scene.challenge``：常量 + 落点清单）并**读真实 pipeline JSON**，断言：

1. 形状 ``^挑战(→)?$``：``挑战`` / ``挑战→`` 命中，``再次挑战 / 继续挑战 / 挑战深渊连战 /
   挑战深渊连战EX / 挑战→→ / →挑战`` 全不中（旧形状 ``^挑战$`` 必须**仍漏**箭头 —— 本票的存在理由）；
2. 7 处点击判据（PubChallenge / WuchongChallengeText / WuchongTeamChallenge /
   PhantomSoloChallenge / AbyssSoloChallenge）**逐字**是同一份真源，且清单本身没漏项；
3. 两种渲染都能被这 7 处判据**点到那颗按钮**（各自字段语义：OCR 走 roi 面积、what 走 roi 中心）；
4. 运行期 override（``agent/side_impl._PUBCHALLENGE_ORIGINAL``）与真源同形，收窄/还原都不回 ``^挑战$``；
5. 全仓 ratchet 绿 + ``hooks_110.prove_red()`` 四条破坏各自变红。

判据全在纯 Python + pipeline JSON 上，**不需要游戏 / 设备 / 框架依赖**。
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "tools" / "contract_hooks"), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: 取**子模块**（``scene/__init__`` 把同名函数导出到包上，属性会被遮蔽成函数）。
CHALLENGE = importlib.import_module("scene.challenge")
DRIFT = importlib.import_module("scene.drift")

import hooks_110 as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


#: 本票点名的 7 处（**测试自己再写一遍**：万一有人从真源清单里悄悄删一项，这里会红）。
EXPECTED_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("common.json", "PubChallenge", "expected"),
    ("wuchong.json", "WuchongChallengeText", "expected"),
    ("wuchong.json", "WuchongTeamChallenge", "what"),
    ("wuchong.json", "WuchongCoopChallenge", "what"),
    ("phantom.json", "PhantomSoloChallenge", "what"),
    ("phantom.json", "PhantomCoopChallenge", "what"),
    ("abyss.json", "AbyssSoloChallenge", "what"),
)

#: 旧形状 ``^挑战$``（**运行时拼出来**：本文件必须点名这条被废除的形状，但
#: ``hooks_109`` 的「仓里不许有活跃 ^挑战$」ratchet 会把字面量算作一次使用 ——
#: 与 ``hooks_110._OLD_SHAPE`` / ``hooks_109.BLIND`` 同一手法）。
_OLD_SHAPE = "^挑战" + "$"


def _pipeline() -> dict:
    return DRIFT.load_pipelines(ROOT / h.PIPELINE_REL)


# ---------------------------------------------------------------------------
# 1. 真源形状
# ---------------------------------------------------------------------------
def test_true_source_shape() -> None:
    print("\n== 1. 真源 scene/challenge：形状 + 正反例 ==")
    pat = CHALLENGE.CHALLENGE_CLICK_PATTERN
    check("真源常量就是 ^挑战(→)?$", pat == r"^挑战(→)?$", f"{pat!r}")
    check(
        "列表形态只有一项（同一颗按钮的一种渲染族）",
        CHALLENGE.CHALLENGE_CLICK_PATTERNS == (pat,),
        f"{CHALLENGE.CHALLENGE_CLICK_PATTERNS!r}",
    )
    for text in h.RENDERINGS:
        check(f"正例『{text}』命中", CHALLENGE.matches(text) is True)
    for bad in CHALLENGE.REJECTED_TEXTS:
        check(f"反例『{bad}』不命中", CHALLENGE.matches(bad) is False)
    # 反例表本身要覆盖需求点名的那些（别靠「恰好没写进去」蒙混）。
    for must in ("再次挑战", "继续挑战", "挑战深渊连战EX", "挑战→→", "→挑战"):
        check(f"反例表覆盖『{must}』", must in CHALLENGE.REJECTED_TEXTS)
    # 旧形状必须**仍**漏箭头（否则本票没有修的东西，守卫会变成恒绿）。
    check(f"旧形状 {_OLD_SHAPE!r} 仍不命中『挑战→』（本票要修的 bug）",
          re.search(_OLD_SHAPE, "挑战→") is None)
    check("is_challenge_pattern 只认逐字相等",
          CHALLENGE.is_challenge_pattern(pat) is True
          and CHALLENGE.is_challenge_pattern(_OLD_SHAPE) is False
          and CHALLENGE.is_challenge_pattern("挑战") is False)


# ---------------------------------------------------------------------------
# 2. 7 处点击判据 == 同一份真源
# ---------------------------------------------------------------------------
def test_five_targets() -> None:
    print("\n== 2. 7 处点击判据逐字等于真源（读真实 pipeline JSON）==")
    files = _pipeline()
    want = list(CHALLENGE.CHALLENGE_CLICK_PATTERNS)

    registered = tuple((c.file, c.node, c.field) for c in CHALLENGE.CLICK_CRITERIA)
    check("真源清单与本票点名的 7 处一一对应（不多不少）",
          sorted(registered) == sorted(EXPECTED_TARGETS),
          f"{sorted(registered)!r}")

    for fname, node_name, field in EXPECTED_TARGETS:
        node = (files.get(fname) or {}).get(node_name)
        got = h._criterion_value(node, field) if isinstance(node, dict) else None
        check(f"{fname}::{node_name}.{field} == {want!r}", got == want, f"{got!r}")
        # 同一个文件里**不该**再留着旧形状（注释里的不算：JSONC 注释已被剥掉）。
        text = (ROOT / h.PIPELINE_REL / fname).read_text(encoding="utf-8")
        active = DRIFT._strip_jsonc(text)
        check(f"{fname} 的活跃文本里没有 '\"挑战\"' 裸形状",
              '"挑战"' not in active, "")
    # 7 处必须是**同一份**：去重后只剩一种取值。
    values = {
        tuple(h._criterion_value((files.get(f) or {}).get(n), fld) or [])
        for f, n, fld in EXPECTED_TARGETS
    }
    check("7 处取值去重后只剩一份（真·单源）", values == {tuple(want)}, f"{values!r}")


# ---------------------------------------------------------------------------
# 3. 两种渲染都点得中
# ---------------------------------------------------------------------------
def _page_of(fname: str, node_name: str, field: str) -> str:
    """这处判据在哪个页面（决定用哪份真机框求值）。"""
    for crit in CHALLENGE.CLICK_CRITERIA:
        if (crit.file, crit.node, crit.field) == (fname, node_name, field):
            return crit.page
    return "solo_team"


def test_both_renderings_clickable() -> None:
    print("\n== 3. 挑战 / 挑战→ 都能被 7 处判据点中那颗按钮 ==")
    files = _pipeline()
    for fname, node_name, field in EXPECTED_TARGETS:
        node = (files.get(fname) or {}).get(node_name) or {}
        page = _page_of(fname, node_name, field)
        for text in h.RENDERINGS:
            box = list(h.PAGE_READING_BOXES[page][text])
            check(
                f"{node_name}.{field} 点中『{text}』",
                h._click_hit(node, field, text, box) is True,
                f"page={page} box={box} roi={h._roi_of(node, field)!r}",
            )
    # 反例：不许被别的控件文字误命中（用各处自己页面的真机框直接求值）。
    for bad in ("再次挑战", "继续挑战", "挑战深渊连战EX", "→挑战"):
        hit = []
        for fname, node_name, field in EXPECTED_TARGETS:
            node = (files.get(fname) or {}).get(node_name) or {}
            box = list(h.PAGE_READING_BOXES[_page_of(fname, node_name, field)]["挑战"])
            if h._click_hit(node, field, bad, box):
                hit.append(f"{node_name}.{field}")
        check(f"反例『{bad}』7 处都不命中", not hit, f"误命中={hit!r}")


# ---------------------------------------------------------------------------
# 4. 运行期 override 同步
# ---------------------------------------------------------------------------
def test_runtime_override() -> None:
    print("\n== 4. agent/side_impl 的运行期 override 与真源同形 ==")
    si = h._side_impl()
    want = list(CHALLENGE.CHALLENGE_CLICK_PATTERNS)
    check("_PUBCHALLENGE_ORIGINAL.expected == 真源",
          list(getattr(si, "_PUBCHALLENGE_ORIGINAL", {}).get("expected") or []) == want,
          f"{getattr(si, '_PUBCHALLENGE_ORIGINAL', None)!r}")
    for kind in ("phantom", "special", "farm", "raid"):
        ov = si.pubchallenge_override_for(kind) or {}
        got = (((ov.get("PubChallenge") or {}).get("recognition") or {}).get("param") or {}).get("expected")
        check(f"override({kind}) 的 expected == 真源", got == want, f"{got!r}")
        check(f"override({kind}) 没有改回 {_OLD_SHAPE!r}", _OLD_SHAPE not in (got or []))
    # 收窄形态仍必须带 ROI（#30：只认底部带，不抓共斗房的灰按钮）。
    ov = si.pubchallenge_override_for("phantom") or {}
    roi = (((ov.get("PubChallenge") or {}).get("recognition") or {}).get("param") or {}).get("roi")
    check("override(phantom) 仍有页面带 roi [150,980,600,1180]（#30 的收窄不能被本票改坏）",
          list(roi or []) == [150, 980, 600, 1180], f"{roi!r}")


# ---------------------------------------------------------------------------
# 5. 守卫 + 破坏实验
# ---------------------------------------------------------------------------
def test_hooks_green() -> None:
    print("\n== 5. hooks_110 五个契约点亮（probe=True） ==")
    check("T1 单源形状", h.probe_challenge_click_single_source() is True)
    check("T2 ratchet", h.probe_challenge_click_ratchet() is True)
    check("T3 放宽封顶", h.probe_challenge_click_anchored() is True)
    check("T4 运行期 override 同步", h.probe_challenge_click_runtime_override() is True)
    check("T5 两种渲染都点得中", h.probe_challenge_click_both_renderings() is True)


def test_prove_red() -> None:
    print("\n== 6. 破坏实验：改一处回旧形状 / 放宽成裸「挑战」/ 去掉 override 同步 / 多一处未登记 ==")
    check("hooks_110.prove_red()（四条破坏各自变红）", h.prove_red() is True)


def main() -> int:
    print("=" * 78)
    print("#110：「挑战」按钮点击判据收成一处真源（`挑战` / `挑战→` 两种渲染都认）")
    print("=" * 78)
    test_true_source_shape()
    test_five_targets()
    test_both_renderings_clickable()
    test_runtime_override()
    test_hooks_green()
    test_prove_red()
    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL GREEN —— 7 处点击判据同一份真源，两种渲染都点得中，反例全不中，运行期 override 已同步")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
