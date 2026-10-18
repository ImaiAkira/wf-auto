# -*- coding: utf-8 -*-
"""离线单测：#36 ``SpecialScrollList`` 的手势几何 —— 起终点都落在列表体内，深行可达。

不需要游戏 / 设备（判据全在内嵌的**真机行扫表 + 页面状态机**上）；真机帧实证是
best-effort（缺 maa / 帧则 SKIP，不算失败）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_scroll_gesture.py
    .venv\\Scripts\\python.exe tools\\test_scroll_gesture.py --prove-red

覆盖 #36 的验收：

  1. **几何**：``SpecialScrollList`` 的 Swipe 起点与终点都落在列表体（y ∈ [440,1180]）内，
     且**都不落在**任何「底部导航 / 左下返回」ROI 内（ROI 从产品枚举 + 与常量绑定）；
  2. **离线复现「深行目标需多次滑动」**：目标 = 真机列表**最末行** ``维·索拉斯讨伐``；
     旧形态（起点 y=1200 压在底导上）滑到**别人的详情页**并 ``SpecialEntry↔SpecialWait``
     空转；新形态滚到最末行、``SpecialEnterBoss`` 命中 → 到达**目标自己的详情页**；
  3. **破坏实验**（prove-red）：把起点退回 ``y=1200`` → 两个守卫各自变红；
  4. **真机帧实证（best-effort）**：对抓下的领主战**列表页**帧跑 MAA OCR，断言
     行名框都在列表体内、底导标签都在 y≥1180（= 旧起点 1200 所在带），而新起点 / 终点
     都不在底导带内；缺 maa / 帧 / 模型则 SKIP；
  5. **无漂移 + #9 三条既有路径守卫仍绿**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_36.py``。
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import os
import re
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

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
ASSETS_DIR = REPO_ROOT / "assets" / "resource"

FAILS: list[str] = []
SKIPS: list[str] = []

# 真机帧证据（#36；缺则 best-effort 段 SKIP）。列表页首屏帧：
# 行名框 y≈634/782/928/1072、底导六槽 y≈1245~1272。
FRAME_LIST = Path(
    os.environ.get(
        "WF_R36_LIST",
        str(TEMP_OPENCODE / "sweep_lord/frames_LA/list_first.jpg"),
    )
)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


def _files() -> dict:
    return drift.load_pipelines(PIPELINE_DIR)


# ---------------------------------------------------------------------------
# 1. 几何：起终点都在列表体内、都不在底导 / 返回 ROI 上
# ---------------------------------------------------------------------------
def test_geometry() -> None:
    print("\n== 1. 手势几何：起终点都在列表体内、不压在底导 / 返回 ROI 上 ==")
    files = _files()
    check("挂点 scroll-gesture-avoids-nav-roi 已点亮（probe=True）",
          hooks_36.probe_scroll_gesture_avoids_nav_roi() is True)
    check("几何绑定：产品两个权威 ROI 与 hooks_36 常量一致",
          hooks_36._binding_failures(files) == [], f"{hooks_36._binding_failures(files)[:2]}")

    nav = hooks_36._nav_rois(files)
    band = hooks_36._band_top(nav)
    body = hooks_36._list_body(band)
    geo = hooks_36._geometry(files)
    check("能读到 Swipe 几何", geo is not None)
    if geo is None:
        return
    print(f"     底导 / 返回 ROI（从产品枚举）= {nav}")
    print(f"     列表体 = {body}；底导带上沿 = {band}")
    print(f"     Swipe begin={geo['begin']} end={geo['end']} duration={geo['duration']}")

    for label, pt in (("起点", geo["begin_pt"]), ("终点", geo["end_pt"])):
        check(f"{label} {list(pt)} 不在任何底导 / 返回 ROI 内",
              not hooks_36._in_nav(pt, nav))
        check(f"{label} {list(pt)} 低于底导带上沿（y<{band}）", pt[1] < band)
        check(f"{label} {list(pt)} 在列表体 {body} 内", hooks_36._inside(pt, body))
    check("滚动方向向上（起点 y > 终点 y）",
          geo["begin_pt"][1] > geo["end_pt"][1],
          f"{geo['begin_pt'][1]} > {geo['end_pt'][1]}")
    check("行程落在受控滚动区间 [200, 600]px",
          hooks_36._SWIPE_MIN_TRAVEL
          <= geo["begin_pt"][1] - geo["end_pt"][1]
          <= hooks_36._SWIPE_MAX_TRAVEL,
          f"travel={geo['begin_pt'][1] - geo['end_pt'][1]}")


# ---------------------------------------------------------------------------
# 2. 离线复现：深行（最末行）目标要多次滑动
# ---------------------------------------------------------------------------
def test_deep_row_repro() -> None:
    print("\n== 2. 离线复现 #36：最末行目标需多次滑动，旧形态滑到别人的详情页 ==")
    (new_ok, new_seq, new_pages), (old_ok, old_seq, old_pages) = hooks_36.loop_traces()
    target = hooks_36._TARGET_ROW
    print(f"     目标行 = {target}（真机列表第 {len(hooks_36.ROWS)} 行 = 最末行）")
    print(f"     新形态：到达={new_ok} 序列前 12={new_seq[:12]}")
    print(f"     旧形态：到达={old_ok} 序列前 12={old_seq[:12]}")
    print(f"     旧形态页面（前 6）={old_pages[:6]}")

    check("真机行扫表与配置「领主战」成员一致", hooks_36._rows_binding(_files()) == [],
          f"{hooks_36._rows_binding(_files())[:1]}")
    check(f"最末行目标 = {target}", hooks_36.ROWS[-1] == target)
    check("新形态确实执行了滚动（SpecialScrollList）", "SpecialScrollList" in new_seq)
    check("新形态滚到最末行后经 SpecialEnterBoss 选行", "SpecialEnterBoss" in new_seq)
    check("新形态到达目标自己的详情页", new_ok is True)
    check("新形态【没有】滑到别人的详情页", hooks_36._WRONG_DETAIL not in new_pages)
    check("旧形态未到达目标详情（深行不可达）", old_ok is False)
    check("旧形态滑到了别人的详情页（_WRONG_DETAIL）",
          hooks_36._WRONG_DETAIL in old_pages)
    check("旧形态复现 SpecialEntry↔SpecialWait 空转",
          old_seq[:12].count("SpecialEntry") >= 3 and old_seq[:12].count("SpecialWait") >= 3)


# ---------------------------------------------------------------------------
# 3. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 3. 破坏实验：起点退回 y=1200 -> 两个守卫各自变红 ==")
    check("hooks_36.prove_red() 成立", hooks_36.prove_red() is True)


# ---------------------------------------------------------------------------
# 4. 真机帧实证（best-effort；缺 maa / 帧 / 模型则 SKIP）
# ---------------------------------------------------------------------------
def _load_bgr(path: Path):
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        im = Image.open(path).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    if im.size != (720, 1280):
        im = im.resize((720, 1280))
    return np.ascontiguousarray(np.array(im)[:, :, ::-1])


def test_real_frame_best_effort() -> None:
    print("\n== 4. 真机帧实证（best-effort）：列表页行名在列表体内、底导标签在 y>=1180 ==")
    if not FRAME_LIST.is_file():
        skip("真机列表页帧", f"缺帧：{FRAME_LIST}")
        return
    img = _load_bgr(FRAME_LIST)
    if img is None:
        skip("真机列表页帧", "缺 numpy/PIL")
        return
    try:
        import live_harness as ca  # noqa: PLC0415

        items = ca.ocr(img, ASSETS_DIR)
    except Exception as exc:  # noqa: BLE001
        skip("真机列表页 MAA OCR", f"缺 maa / OCR 模型 / 资源：{exc!r}")
        return
    if not items:
        skip("真机列表页 MAA OCR", "OCR 返回空（模型缺失？）")
        return

    rows = [
        (t, b)
        for t, b in items
        if re.search(r"讨伐$", t or "") and t not in ("降临讨伐", "领主战")
    ]
    nav_labels = [(t, b) for t, b in items if t in ("返回", "主城", "角色", "商店", "扭蛋", "菜单")]
    print(f"     行名框 = {[(t, b) for t, b in rows][:8]}")
    print(f"     底导标签框 = {nav_labels}")

    check("列表页帧里 OCR 到了行名（讨伐行）", len(rows) >= 3)
    check("列表页帧里 OCR 到了底导标签", len(nav_labels) >= 4)
    if not rows or not nav_labels:
        return

    band = hooks_36._band_top(hooks_36._nav_rois(_files()))
    band_roi = hooks_36.BOTTOM_NAV_ROI
    nav_label_min = min(b[1] for _t, b in nav_labels)
    row_tops = [b[1] for _t, b in rows]
    row_bottoms = [b[1] + b[3] for _t, b in rows]

    print(f"     列表体上沿={hooks_36.LIST_BODY_TOP} 产品底导带上沿={band} "
          f"真机底导标签 y_min={nav_label_min}")
    check("真机底导标签都落在产品底导带内（y >= 1180）",
          all(b[1] >= band for _t, b in nav_labels),
          f"nav_label_min={nav_label_min} band_top={band}")
    check("真机行名框都在列表体内（>= 440 且底边 < 底导带上沿）",
          all(t >= hooks_36.LIST_BODY_TOP for t in row_tops)
          and max(row_bottoms) < band,
          f"row_tops={row_tops} row_bottoms_max={max(row_bottoms)} band_top={band}")

    geo = hooks_36._geometry(_files())
    old_begin = hooks_36._LEGACY_GEOMETRY["begin_pt"]
    check(f"旧起点 {list(old_begin)} 落在产品底导带 {band_roi} 内（#36 缺陷）",
          hooks_36._inside(old_begin, band_roi))
    for label, pt in (("起点", geo["begin_pt"]), ("终点", geo["end_pt"])):
        check(f"新{label} {list(pt)} 不在真机底导带内", not hooks_36._inside(pt, band_roi))
        check(f"新{label} y={pt[1]} 落在真机行名区段内（列表体内）",
              min(row_tops) <= pt[1] <= max(row_bottoms),
              f"row span=[{min(row_tops)}, {max(row_bottoms)}]")


# ---------------------------------------------------------------------------
# 5. 无漂移 + #9 守卫
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 5. 无漂移 + #9 三条既有路径守卫仍绿 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    check("兜底范围守卫 chain_page_fallback_drift == []",
          drift.chain_page_fallback_drift(REPO_ROOT) == [])
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
    print("离线单测：#36 SpecialScrollList 手势几何 —— 起终点在列表体内、深行可达")
    print("=" * 72)
    test_geometry()
    test_deep_row_repro()
    test_prove_red()
    test_real_frame_best_effort()
    test_drift_and_guards()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
