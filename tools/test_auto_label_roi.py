# -*- coding: utf-8 -*-
"""#108：``AutoSwitchLabel`` 的 roi 必须只框「自动」那一栏 —— 离线一键守卫入口。

    python tools\\test_auto_label_roi.py

三块判据，全离线（不需要游戏 / 设备 / 框架依赖；只用到已入库真机帧）：

1. **真源 ⇄ 投影 + roi 几何**：``scene/auto_switch.py`` 的 ``AUTO_LABEL_ROI`` /
   ``AUTO_ORDER_BY`` 与 ``common.json::AutoSwitchLabel`` 逐项相等；roi **完整包含**真按钮
   窗口 ``(142,1062,43,26)``（否则滑窗跑不到正例），且**不含** x=17 那一栏（兄弟「自动续战」），
   并且是合法的 720 空间框（走 ``scene.pixels.assert_base_box``）。
2. **真机帧 ZNCC 假阳用例**：两张已入库帧上算**全滑窗** ``TM_CCOEFF_NORMED`` —— roi 内命中
   恰好 1 个、分数 1.0000、位置 (142,1062)；兄弟窗口 (17,1062) 分数 **0.8964 ≥ 阈值 0.75**
   （危险是真的）但**落在 roi 外**；按框架语义（候选 + ``order_by`` + ``index``）选出来是真框，
   绝不可能是 x=17；负例帧（战斗页 / 弹窗 / 空列表）roi 内不命中。
3. **守卫与破坏实验**：``hooks_108`` 的四个契约全绿 + ``prove_red()`` 全红。
"""

from __future__ import annotations

import importlib
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
PIXELS = importlib.import_module("scene.pixels")
DRIFT = importlib.import_module("scene.drift")

import hooks_108 as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 真源 ⇄ 投影 + roi 几何
# ---------------------------------------------------------------------------
def test_projection_and_geometry() -> None:
    print("\n== 1. 真源 ⇄ 投影 + roi 几何（720 空间） ==")
    param = h._node_param()
    check("common.json::AutoSwitchLabel 存在且有 recognition.param", param is not None)
    if param is None:
        return

    roi = AUTO_SWITCH.AUTO_LABEL_ROI
    check("真源 roi 是四整数", isinstance(roi, tuple) and len(roi) == 4, f"{roi!r}")
    check("投影 roi == 真源 roi", param.get("roi") == list(roi), f"投影={param.get('roi')!r}")
    check("投影 order_by == 真源 AUTO_ORDER_BY",
          param.get("order_by") == AUTO_SWITCH.AUTO_ORDER_BY, f"投影={param.get('order_by')!r}")
    check("order_by 是 Score（要「最像」，不是默认的「最左」）",
          param.get("order_by") == "Score", f"{param.get('order_by')!r}")
    check("投影 template == 真源 AUTO_LABEL_TEMPLATES",
          param.get("template") == list(AUTO_SWITCH.AUTO_LABEL_TEMPLATES))
    check("投影 threshold == 真源 AUTO_TEMPLATE_THRESHOLD（本票刻意不动阈值）",
          param.get("threshold") == AUTO_SWITCH.AUTO_TEMPLATE_THRESHOLD,
          f"投影={param.get('threshold')!r}")

    # roi 必须是合法的 720 空间框（真源换算/越界守卫在 scene.pixels，别在这里手写）。
    try:
        PIXELS.assert_base_box(list(roi), name="AUTO_LABEL_ROI")
        legal = True
    except ValueError as exc:
        legal = False
        print(f"      {exc}")
    check("roi 是合法的 720 空间框（assert_base_box）", legal, f"{list(roi)}")

    # ★核心几何★：正例窗口要**整窗**落在 roi 内（滑窗才跑到得到），兄弟窗口要在 roi 外。
    check("roi 覆盖真按钮窗口 (142,1062,43,26)（整窗在内）",
          AUTO_SWITCH.box_fully_inside(roi, h.AUTO_WINDOW), f"roi={list(roi)}")
    check("roi 不含 x=17 那一栏（「自动续战」窗口整窗在外）",
          AUTO_SWITCH.box_fully_inside(roi, h.SIBLING_WINDOW) is False,
          f"roi={list(roi)} sibling={list(h.SIBLING_WINDOW)}")
    check("roi 左边界 > 「自动续战」标签右边界（整栏排除，不是只排除一个窗口位置）",
          roi[0] > h.SIBLING_LABEL_RIGHT, f"roi.x0={roi[0]} 兄弟右边界={h.SIBLING_LABEL_RIGHT}")
    # 真按钮**中心** (163,1075) 也必须落在 roi 内（点击点由识别框中心推出，别框到半个按钮）。
    cx, cy = h.AUTO_WINDOW[0] + h.AUTO_WINDOW[2] // 2, h.AUTO_WINDOW[1] + h.AUTO_WINDOW[3] // 2
    check(f"roi 覆盖真按钮中心 ({cx},{cy})",
          roi[0] <= cx <= roi[0] + roi[2] and roi[1] <= cy <= roi[1] + roi[3],
          f"roi={list(roi)}")

    # OCR 兜底必须保留且是整串锚定。
    check("OCR 兜底仍是整串 ^自动$（不是裸「自动」）",
          AUTO_SWITCH.AUTO_LABEL_PATTERNS == (r"^自动$",), f"{AUTO_SWITCH.AUTO_LABEL_PATTERNS!r}")
    check("OCR 兜底判据本身没有坏（hooks_108._ocr_fallback_failures 为空）",
          h._ocr_fallback_failures(AUTO_SWITCH) == [])

    # 真源没被"顺手改坏"：真源⇄投影整体一致 + drift 全仓为空。
    check("真源⇄投影整体一致（hooks_108._projection_failures 为空）",
          h._projection_failures() == [], f"{h._projection_failures()[:2]}")
    check("scene.drift.check_all() == []", DRIFT.check_all() == [])


# ---------------------------------------------------------------------------
# 2. 真机帧 ZNCC 假阳用例
# ---------------------------------------------------------------------------
def test_real_frame_no_sibling_pick() -> None:
    print("\n== 2. 真机帧 ZNCC：假「自动续战」绝不被选中 ==")
    missing = h._deps_missing()
    if missing:
        check("依赖齐备（numpy + Pillow）", False, missing)
        return

    tpl, rel = h._template_gray(AUTO_SWITCH)
    check(f"模板裁片可读：{rel}", tpl is not None)
    if tpl is None:
        return
    thr = float(AUTO_SWITCH.AUTO_TEMPLATE_THRESHOLD)
    roi = AUTO_SWITCH.AUTO_LABEL_ROI
    param = h._node_param() or {}
    order_by = param.get("order_by")
    tpl_h, tpl_w = tpl.shape

    for frame in h.POSITIVE_FRAMES:
        scores = h._zncc_map(h._frame_720(frame), tpl)
        cands = h._peaks(scores, thr)
        z_pos = float(scores[h.AUTO_WINDOW[1], h.AUTO_WINDOW[0]])
        z_sib = float(scores[h.SIBLING_WINDOW[1], h.SIBLING_WINDOW[0]])
        print(f"  -- {frame}")
        check(f"正例：真「自动」窗口 ZNCC={z_pos:.4f} ≥ {h.POSITIVE_MIN}",
              z_pos >= h.POSITIVE_MIN)
        check(f"同帧兄弟「自动续战」窗口 ZNCC={z_sib:.4f} ≥ {h.SIBLING_MIN}（危险是真的）",
              z_sib >= h.SIBLING_MIN)
        check(f"兄弟分数 ≥ 阈值 {thr}（所以阈值挡不住它 —— 本票不能用调阈值修）", z_sib >= thr)

        inside = [c for c in cands if h._inside(roi, (c[1], c[2], tpl_w, tpl_h))]
        check(f"roi 内候选恰好 1 个（实测 {inside}）", len(inside) == 1)
        picked = h._select(inside, order_by, 0)
        check(f"按投影语义选到真「自动」{list(h.AUTO_WINDOW[:2])}（实测 {picked}）",
              picked is not None
              and abs(picked[1] - h.AUTO_WINDOW[0]) <= 2
              and abs(picked[2] - h.AUTO_WINDOW[1]) <= 2)
        check("选出来的**不是** x=17 那一栏", picked is not None and abs(picked[1] - 17) > 2)

        # 反面：全屏 + 默认排序（= #108 修之前的语义）会选到兄弟 —— 证明本票修的是真 bug。
        blind = h._select(cands, "Horizontal", 0)
        check(f"全屏 + 默认 Horizontal 会选到 x={blind[1] if blind else None}（#108 的 bug 可复现）",
              blind is not None and abs(blind[1] - h.SIBLING_WINDOW[0]) <= 2)

    print("  -- 负例帧（战斗页 / 弹窗 / 空列表）：roi 内不许命中")
    for frame in h.NEGATIVE_FRAMES:
        scores = h._zncc_map(h._frame_720(frame), tpl)
        best = h._max_inside(scores, roi, tpl.shape)
        check(f"{Path(frame).name}：roi 内最高 {best[0]:.4f} < 阈值 {thr}",
              best is not None and best[0] < thr)
        check(f"{Path(frame).name}：负例余量 {thr - (best[0] if best else 0):.4f} ≥ 0.15",
              best is not None and (thr - best[0]) >= 0.15)


# ---------------------------------------------------------------------------
# 3. 守卫 + 破坏实验
# ---------------------------------------------------------------------------
def test_hooks_green() -> None:
    print("\n== 3. hooks_108 四个契约点亮（probe=True） ==")
    check("T1 所有 TemplateMatch 都有 roi", h.probe_template_match_roi_required() is True,
          f"{h._roi_required_failures()[:2]}")
    check("T2 多结果/多模板的 TemplateMatch 都显式 order_by",
          h.probe_template_match_order_by_explicit() is True, f"{h._order_by_failures()[:2]}")
    check("T3 真源⇄投影一致 + OCR 兜底整串",
          h.probe_auto_label_projection_synced() is True, f"{h._projection_failures()[:2]}")
    check("T4 真机帧假阳用例（兄弟绝不被选中）",
          h.probe_auto_label_no_sibling_pick() is True, f"{h._false_positive_failures()[:2]}")


def test_prove_red() -> None:
    print("\n== 4. 破坏实验：去掉 roi / 改回默认排序 / 放宽 roi / 兜底不锚定 ==")
    check("hooks_108.prove_red()（五类破坏各自变红）", h.prove_red() is True)


def main() -> int:
    print("=" * 72)
    print("#108：AutoSwitchLabel 必须 roi（只框「自动」那一栏）+ 显式 order_by: Score")
    print("=" * 72)
    test_projection_and_geometry()
    test_real_frame_no_sibling_pick()
    test_hooks_green()
    test_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL GREEN —— roi 只框「自动」那一栏，假「自动续战」0.8964@x=17 绝不会被选中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
