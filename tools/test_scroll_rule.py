# -*- coding: utf-8 -*-
"""离线单测：#58 列表导航的全部 Swipe 手势 —— 区域内竖直下滑。

不需要游戏 / 设备（判据全在**产品 pipeline JSON** + 内嵌几何常量上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_scroll_rule.py
    .venv\\Scripts\\python.exe tools\\test_scroll_rule.py --prove-red

覆盖 #58 的验收（运维口径 verbatim：只往下拉、卡片式每行一个、在区域内从上往下划、
不要从左往右、不要点到最下面的 UI）：

  1. **audit 表**：打印产品里全部 ``Swipe`` 节点的 begin / end / 轴 / 行程；
  2. **主守卫** ``scroll-rule-all-gestures-vertical``：全部 Swipe 节点轴竖直、起终点在
     列表体 ``[440,1180]`` 内、不落在底导 / 返回 ROI、行程受控 ``[200,600]``；
  3. **防静默豁免**：``PushStageAllDone / FarmScroll / FarmScrollUp / WuchongScrollList /
     SpecialScrollList`` 必须都被枚举到；
  4. **破坏实验**（prove-red）：改横向 → 红；起点退回 ``y=1200`` → 红；
  5. **无漂移 + #9 既有路径守卫仍绿**；``special_dungeon.json`` 五条承重短语零丢失。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_58.py``。
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

from scene import drift  # noqa: E402

import hooks_36  # noqa: E402
import hooks_58  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

FAILS: list[str] = []
SKIPS: list[str] = []

# #12 的承重注释硬规则（纯编辑，绝不丢这些短语）。
_BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _files() -> dict:
    return drift.load_pipelines(PIPELINE_DIR)


# ---------------------------------------------------------------------------
# 1. audit 表（全部 Swipe 节点的几何）
# ---------------------------------------------------------------------------
def test_audit_inventory() -> None:
    print("\n== 1. audit：产品里全部 Swipe 手势节点（720 空间）==")
    files = _files()
    nav = hooks_36._nav_rois(files)
    band = hooks_36._band_top(nav)
    body = hooks_36._list_body(band)
    print(f"     列表体 = {body}；底导带上沿 = {band}；底导 / 返回 ROI = {nav}")
    inv = hooks_58.swipe_inventory()
    print(f"     {'节点':<22}{'begin':<16}{'end':<16}{'轴':<12}{'行程'}")
    for fname, name, begin, end in inv:
        if not begin or not end:
            print(f"     {name:<22}{'?':<16}{'?':<16}{'?':<12}?")
            continue
        axis = "竖直" if begin[0] == end[0] else f"横向 dx={end[0] - begin[0]}"
        travel = abs(begin[1] - end[1])
        print(f"     {name:<22}{str(begin):<16}{str(end):<16}{axis:<12}{travel}")

    names = {name for _f, name, _b, _e in inv}
    missing = sorted(hooks_58.REQUIRED_SCROLL_NODES - names)
    check("枚举到产品里全部 Swipe 节点，且必备滚动节点都在",
          inv and not missing, f"共 {len(inv)} 个: {sorted(names)}；缺 {missing}")

    # WuchongSwipe 必须是竖直（本票修的那一处）。
    for _f, name, begin, end in inv:
        if name == "WuchongSwipe":
            check("WuchongSwipe 轴竖直（dx==0）", begin and end and begin[0] == end[0],
                  f"begin={begin} end={end}")


# ---------------------------------------------------------------------------
# 2. 主守卫
# ---------------------------------------------------------------------------
def test_main_guard() -> None:
    print("\n== 2. 主守卫 #58：全部 Swipe = 区域内竖直下滑 ==")
    check("挂点 scroll-rule-all-gestures-vertical 已点亮（probe=True）",
          hooks_58.probe_all_scroll_gestures_vertical() is True,
          f"{hooks_58._failures()[:2]}")

    files = _files()
    check("几何绑定：产品两个权威 ROI 与 hooks_36 常量一致",
          hooks_36._binding_failures(files) == [], f"{hooks_36._binding_failures(files)[:2]}")

    names = {name for _f, name, _b, _e in hooks_58.swipe_inventory()}
    missing = sorted(hooks_58.REQUIRED_SCROLL_NODES - names)
    check("必备滚动节点都被枚举到（防静默豁免）", missing == [], f"缺 {missing}")

    # 逐节点可读性（供报告引用）：每个节点都必须是带 begin/end 的 Swipe。
    problems = []
    for fname, name, param in hooks_58._swipe_nodes(files):
        if hooks_36._pt(param.get("begin")) is None or hooks_36._pt(param.get("end")) is None:
            problems.append(f"{name}（{fname}）")
    check("所有 Swipe 节点都有 begin/end", problems == [], f"缺 {problems}")


# ---------------------------------------------------------------------------
# 3. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 3. 破坏实验：改横向 → 红；起点退回 y=1200 → 红 ==")
    check("hooks_58.prove_red() 成立", hooks_58.prove_red() is True)


# ---------------------------------------------------------------------------
# 4. 无漂移 + #9 守卫 + 承重短语
# ---------------------------------------------------------------------------
def test_drift_guards_phrases() -> None:
    print("\n== 4. 无漂移 + #9 守卫仍绿 + 五条承重短语零丢失 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    check("兜底范围守卫 chain_page_fallback_drift == []",
          drift.chain_page_fallback_drift(REPO_ROOT) == [])
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [])
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")

    text = (PIPELINE_DIR / "special_dungeon.json").read_text(encoding="utf-8")
    for phrase in _BEARING_PHRASES:
        check(f"仍含承重短语「{phrase}」", phrase in text)


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
    print("离线单测：#58 列表导航全部 Swipe 手势 —— 区域内竖直下滑")
    print("=" * 72)
    test_audit_inventory()
    test_main_guard()
    test_prove_red()
    test_drift_guards_phrases()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
