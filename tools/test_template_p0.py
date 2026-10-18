# -*- coding: utf-8 -*-
"""#102：模板识别 P0 三项 —— 离线一键验收（PIL + numpy 即可，不连设备、不跑 runner）。

    .venv\\Scripts\\python.exe tools\\test_template_p0.py

★这张票的验收门槛不是「换完能认」★（本仓血泪：原生 ``TemplateMatch`` 在离线 ZNCC **0.470**
的位置也选中过、``banner_abyss_ex`` 假阳 **0.8708``）⇒ 本测试对每一项都断四件事：

1. **正例命中**：真机帧上 roi 内最高分 ≥ 阈值、位置 = 正例窗口（±2px）、且 roi 内
   ≥threshold 的候选**恰好 1 个**（多结果才需要排序，本票要求候选唯一）；**跨帧正例**（未参与
   裁图的其它真机帧）在同一窗口仍要 ≥ 阈值 + 0.05，argmax 不漂。
2. **负例不假阳**：其余已入库真机帧 roi 内最高分 **< 阈值**，并且余量 ≥ 0.05
   （低于 0.05 = 靠阈值擦屁股，不是靠 roi）。
3. **存档分数与实测一致**（容差 0.02）：正例 / 跨帧正例 / 负例逐帧 / 同帧兄弟 / roi 外危险分。
4. **跳过真机也没问题**的诚实边界：本票**测不了**真机耗时（不碰设备），只打印离线量测耗时
   作为参考，并写明真机测法（见文件末尾）。

另外三块结构性判据：模板 PNG == 从正例帧按 window 重裁（像素级）；OCR 兜底仍在场且没被改坏；
接线现状与 ``scene/templates.py`` 的声明一致（P0-1 已接**全部**消耗体力的枢纽：外传两个入口 +
五重 / 战阵之宴 / 领主战族 / 深渊 / 主线，接入点由 ``scene.stamina.STAMINA_CONSUMING_CHAINS`` 派生；
P0-3 小行徽标已接 1 处双通道，另有 4 张跨帧正例）。
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "tools" / "contract_hooks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: 取**子模块**（``scene/__init__`` 把同名函数导出到包上，属性会被遮蔽成函数）。
T = importlib.import_module("scene.templates")
DRIFT = importlib.import_module("scene.drift")
PIXELS = importlib.import_module("scene.pixels")

import hooks_102 as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def info(text: str) -> None:
    print(f"        {text}")


# ---------------------------------------------------------------------------
# 1. 取证帧 / 模板资产在场
# ---------------------------------------------------------------------------
def test_assets() -> None:
    print("\n== 1. 取证帧与模板资产在场（缺帧不许拿别的帧冒充） ==")
    for key, spec in T.TEMPLATES.items():
        check(f"[{key}] 正例帧在库：{spec.positive_frame}", (ROOT / spec.positive_frame).is_file())
        for hit in spec.negatives:
            check(f"[{key}] 负例帧在库：{hit.frame}", (ROOT / hit.frame).is_file())
        for hit in spec.cross_positives:
            check(f"[{key}] 跨帧正例在库：{hit.frame}", (ROOT / hit.frame).is_file())
        path = ROOT / spec.template_rel
        check(f"[{key}] 模板在库：{spec.template_rel}", path.is_file())
        if not path.is_file():
            continue
        from PIL import Image  # noqa: PLC0415

        w, h = Image.open(path).size
        check(
            f"[{key}] 模板尺寸 == 正例窗口 {spec.window[2]}x{spec.window[3]}",
            (w, h) == (spec.window[2], spec.window[3]),
            f"实际 {w}x{h}",
        )
        check(f"[{key}] 模板是合法的 720 空间框（assert_base_box）",
              _legal_box(spec.window))
        check(f"[{key}] roi 是合法的 720 空间框", _legal_box(spec.roi))
    # 命名/目录约定（调研 §4.1：场景私有放子目录，共享叶子进 common/）
    check(
        "共享叶子放在 common/（星导石图标 / NEW 徽标）",
        T.STONE_ICON.template.startswith("common/") and T.NEW_BADGE.template.startswith("common/"),
    )
    check(
        "五重私有叶子放在 wuchong/（是 / 否 按钮）",
        T.BONUS_NO.template.startswith("wuchong/") and T.BONUS_YES.template.startswith("wuchong/"),
    )
    check("P0-3 小行徽标已接线（NEW_BADGE_WIRED=True）", T.NEW_BADGE_WIRED is True)
    check("P0-3 取证状态为 ok", T.NEW_BADGE.evidence == "ok")
    check(
        "P0-3 跨帧正例 ≥2 帧（模板不是样本内自证）",
        len(T.NEW_BADGE.cross_positives) >= 2,
        f"{len(T.NEW_BADGE.cross_positives)} 帧",
    )


def _legal_box(box) -> bool:
    try:
        PIXELS.assert_base_box(list(box), name="box")
        return True
    except ValueError as exc:
        print(f"        {exc}")
        return False


# ---------------------------------------------------------------------------
# 2. 正例命中 / 负例不假阳 / 存档一致
# ---------------------------------------------------------------------------
def test_zncc() -> None:
    print("\n== 2. 真机帧全滑窗 ZNCC：正例命中 + 负例不假阳 + 存档一致（容差 0.02） ==")
    missing = h._deps_missing()
    check("依赖齐备（numpy + Pillow）", missing is None, missing or "")
    if missing:
        return

    for key, spec in T.TEMPLATES.items():
        m = h.measure(spec)
        pos = m["positive"]
        print(f"  -- {key}（模板 {spec.template}，threshold {spec.threshold}，roi {list(spec.roi)}）")
        # ① 正例命中
        check(f"[{key}] 正例灰分 {pos['gray'][0]:.4f} ≥ 阈值", pos["gray"][0] >= spec.threshold)
        check(f"[{key}] 正例彩分 {pos['color'][0]:.4f} ≥ 阈值", pos["color"][0] >= spec.threshold)
        for metric in ("gray", "color"):
            score, x, y = pos[metric]
            check(
                f"[{key}] 正例 {metric} 落在正例窗口 {list(spec.window[:2])}（实测 ({x},{y})）",
                abs(x - spec.window[0]) <= h.WINDOW_TOL and abs(y - spec.window[1]) <= h.WINDOW_TOL,
            )
        check(f"[{key}] roi 内 ≥threshold 的候选恰好 1 个（实测 {pos['candidates']}）", pos["candidates"] == 1)

        # ①b 跨帧正例：未参与裁图的帧上，同一窗口仍要够分、argmax 不漂、候选唯一
        if spec.cross_positives:
            need = max(h.CROSS_POSITIVE_MIN, spec.threshold + h.NEGATIVE_MARGIN_MIN)
            for hit in spec.cross_positives:
                got = m["cross"][hit.frame]
                name = Path(hit.frame).name
                for metric in ("gray", "color"):
                    at = got[f"{metric}_at"]
                    check(
                        f"[{key}] 跨帧正例 {name} {metric}@{list(spec.window[:2])} {at:.4f} ≥ {need:.2f}",
                        at is not None and at >= need,
                    )
                    score, x, y = got[metric]
                    check(
                        f"[{key}] 跨帧正例 {name} {metric} argmax 仍落在正例窗口（实测 ({x},{y})）",
                        abs(x - hit.x) <= h.WINDOW_TOL and abs(y - hit.y) <= h.WINDOW_TOL,
                    )
                check(
                    f"[{key}] 跨帧正例 {name} roi 内候选恰好 1 个（实测 {got['candidates']}）",
                    got["candidates"] == 1,
                )
                check(
                    f"[{key}] 跨帧正例 {name} 存档分与实测一致（灰 {hit.gray:.4f} / 彩 {hit.color:.4f}）",
                    abs(got["gray_at"] - hit.gray) <= h.SCORE_TOL
                    and abs(got["color_at"] - hit.color) <= h.SCORE_TOL,
                )

        # ② 负例不假阳
        worst_all = 0.0
        for frame, got in m["negatives"].items():
            worst = max(got["gray"][0], got["color"][0])
            worst_all = max(worst_all, worst)
            check(
                f"[{key}] 负例 {Path(frame).name} roi 内最高 {worst:.4f} < 阈值 {spec.threshold}",
                worst < spec.threshold,
            )
            check(
                f"[{key}] 负例 {Path(frame).name} 余量 {spec.threshold - worst:.4f} ≥ {h.NEGATIVE_MARGIN_MIN}",
                spec.threshold - worst >= h.NEGATIVE_MARGIN_MIN,
            )
        info(f"负例最高分 {worst_all:.4f} / 阈值 {spec.threshold} / 余量 {spec.threshold - worst_all:.4f}")
        info(
            f"存档口径：正例保守分 {spec.positive_worst:.4f} / 负例最高 {spec.negative_worst:.4f}"
            f" / 余量 {spec.margin:.4f}"
        )

        # ③ 存档一致
        check(
            f"[{key}] 存档正例分与实测一致（灰 {spec.positive_gray:.4f} / 彩 {spec.positive_color:.4f}）",
            abs(pos["gray"][0] - spec.positive_gray) <= h.SCORE_TOL
            and abs(pos["color"][0] - spec.positive_color) <= h.SCORE_TOL,
        )
        if m["sibling"] is not None:
            check(
                f"[{key}] 同帧兄弟控件分数存档一致（灰 {spec.sibling_gray:.4f} / 彩 {spec.sibling_color:.4f}）",
                abs(m["sibling"]["gray"] - spec.sibling_gray) <= h.SCORE_TOL
                and abs(m["sibling"]["color"] - spec.sibling_color) <= h.SCORE_TOL,
            )
            check(
                f"[{key}] 兄弟控件窗口整窗落在 roi **外**（靠 roi 分开，不靠阈值）",
                T.window_fits(spec.roi, spec.sibling_window) is False,
            )


# ---------------------------------------------------------------------------
# 3. 是/否 的「互相验证」：底框同款，阈值救不了
# ---------------------------------------------------------------------------
def test_sibling_mutual() -> None:
    print("\n== 3. 是/否 互为正负例：底框像素级同款 ⇒ 阈值救不了，roi 才是防线 ==")
    if h._deps_missing():
        return
    m = h.measure(T.BONUS_NO)
    sib = m["sibling"]
    check("「否」模板在「是」按钮窗口上的灰分 ≥ 0.5（危险真实存在）", sib["gray"] >= 0.5, f"{sib['gray']:.4f}")
    check(
        "「否」模板在「是」按钮窗口上的灰分仍 < 阈值（所以它不会自证假阳，但也不能靠阈值）",
        sib["gray"] < T.BONUS_NO.threshold,
        f"{sib['gray']:.4f} < {T.BONUS_NO.threshold}",
    )
    check(
        "两个 roi 互不重叠（左右各一半）——这是「选哪个」不变的唯一理由",
        T.BONUS_NO.roi[0] + T.BONUS_NO.roi[2] <= T.BONUS_YES.roi[0],
        f"否 roi 右边界 {T.BONUS_NO.roi[0] + T.BONUS_NO.roi[2]} ≤ 是 roi 左边界 {T.BONUS_YES.roi[0]}",
    )
    # roi 外的危险高分（= 同一款红色按钮出现在别的弹窗）
    for spec in (T.BONUS_NO, T.BONUS_YES):
        for hit in spec.global_watch:
            got = m["watch"][hit.frame]
            inside = T.window_fits(spec.roi, (hit.x, hit.y, spec.window[2], spec.window[3]))
            check(
                f"[{spec.key}] roi 外危险分 {Path(hit.frame).name} 灰 {got['gray_at']:.4f} 在 roi **外**",
                inside is False,
            )


# ---------------------------------------------------------------------------
# 4. 双通道：OCR 兜底仍在场（绝不删 OCR）
# ---------------------------------------------------------------------------
def test_ocr_fallback() -> None:
    print("\n== 4. 双通道：模板优先、OCR 兜底（OCR 节点一个都没删） ==")
    check("OCR 兜底契约无失败项", h._ocr_fallback_failures() == [], f"{h._ocr_fallback_failures()[:3]}")
    nodes = h._nodes_by_name()
    for or_name, tpl_name, ocr_name in (
        (T.NODE_STONE_ROW, T.NODE_STONE_ICON, T.NODE_STONE_OCR),
        (T.NODE_BONUS_NO, T.NODE_BONUS_NO_TPL, T.NODE_BONUS_NO_OCR),
        (T.NODE_BONUS_YES, T.NODE_BONUS_YES_TPL, T.NODE_BONUS_YES_OCR),
        (T.NODE_NEW_BADGE, T.NODE_NEW_BADGE_TPL, T.NODE_NEW_BADGE_OCR),
    ):
        any_of = (h._param(nodes.get(or_name)).get("any_of")) or []
        check(f"{or_name} = Or([模板, OCR])，模板在第一位", any_of[:2] == [tpl_name, ocr_name], f"{any_of}")
    check(
        "星导石行 OCR 叶仍是既有节点（PubStaminaStoneText，未改）",
        h._rec(nodes.get(T.NODE_STONE_OCR)).get("type") == "OCR",
    )
    check(
        "NEW 徽标 OCR 兜底叶仍是 ^NEW$ + 同 roi（模板漏检时还有它）",
        h._rec(nodes.get(T.NODE_NEW_BADGE_OCR)).get("type") == "OCR"
        and h._param(nodes.get(T.NODE_NEW_BADGE_OCR)).get("expected") == ["^NEW$"]
        and h._param(nodes.get(T.NODE_NEW_BADGE_OCR)).get("roi") == list(T.NEW_BADGE.roi),
    )
    check(
        "星导石行 OCR 叶的 roi 仍 == scene.stamina.STONE_ROW_ROI（#74 的真机标定没被本票动过）",
        h._param(nodes.get(T.NODE_STONE_OCR)).get("roi")
        == list(importlib.import_module("scene.stamina").STONE_ROW_ROI),
    )


# ---------------------------------------------------------------------------
# 5. 接线现状 ⇄ 声明
# ---------------------------------------------------------------------------
def test_wiring() -> None:
    print("\n== 5. 接线现状 ⇄ 声明（P0-1 已接全部消费链枢纽 / P0-3 小行徽标已接 1 处双通道） ==")
    files = h._pipelines()
    nodes = h._nodes_by_name()
    for fname, hub in T.STONE_TPL_WIRED_HUBS:
        nxt = ((files.get(fname) or {}).get(hub) or {}).get("next") or []
        check(f"{fname}::{hub}.next 含 {T.STONE_TPL_REF}", T.STONE_TPL_REF in nxt)
        ocr_ref = f"[JumpBack]{T.NODE_USE_STONE_OCR}"
        check(
            f"{fname}::{hub}：模板通道排在 OCR 版之前",
            ocr_ref in nxt and nxt.index(T.STONE_TPL_REF) < nxt.index(ocr_ref),
        )
    check(
        "side_story 两个入口分派表仍逐项一致（本次插桩没打破不变式）",
        (files["side_story.json"]["SideStoryEntry"]["next"]
         == files["side_story.json"]["SideClearEntry"]["next"]),
    )
    check(
        "P0-3 NEW 徽标已接线（pipeline 引用 common/badge_new.png）",
        T.NEW_BADGE.template in h._referenced_templates(),
    )
    check("P0-3 取证状态为 ok（正例 + 跨帧正例已在库）", T.NEW_BADGE.evidence == "ok")
    check(
        "P0-3 双通道叶 SpecialNewBadge = Or",
        h._rec(nodes.get(T.NODE_NEW_BADGE)).get("type") == "Or",
        f"{h._rec(nodes.get(T.NODE_NEW_BADGE)).get('type')!r}",
    )
    check(
        "P0-3 模板叶 SpecialNewBadgeTpl = TemplateMatch",
        h._rec(nodes.get(T.NODE_NEW_BADGE_TPL)).get("type") == "TemplateMatch",
    )
    check(
        "P0-3 只声明了 1 处模板叶（大徽标 / 列表行仍是 OCR，不是漏声明）",
        list(T.NEW_BADGE_NODES) == [T.NODE_NEW_BADGE_TPL],
        f"{list(T.NEW_BADGE_NODES)}",
    )
    info("P0-3 范围：只换小行徽标（special_dungeon 详情页）1 处；"
         "PubNewCharText 大徽标 / SideStoryNodeNew / SideEnter 仍是 OCR（理由见 scene/templates.py）")
    # ★#102 四个枢纽★：票面「剩下四个枢纽未接」已接上（接线清单从 scene.stamina 派生）
    fails = h._stone_hub_failures()
    check("C8 四个枢纽 + 全部消费链枢纽都挂模板优先通道且在 OCR 版之前", fails == [], f"{fails[:2]}")
    info(
        "已接线枢纽："
        + "、".join(f"{f}::{hub}" for f, hub in h.STONE_TPL_REQUIRED_HUBS)
        + "（+ 外传两个入口；清单真源 = scene.stamina.STAMINA_CONSUMING_CHAINS）"
    )


# ---------------------------------------------------------------------------
# 6. 守卫 + 破坏实验
# ---------------------------------------------------------------------------
def test_hooks() -> None:
    print("\n== 6. hooks_102 九个契约点亮（probe=True） ==")
    cases = (
        ("C1 p0-roi-scoped", h.probe_p0_roi_scoped, h._roi_scoped_failures),
        ("C2 p0-order-by-score", h.probe_p0_order_by_score, h._order_by_failures),
        ("C3 p0-projection-synced", h.probe_p0_projection_synced, h._projection_failures),
        ("C4 p0-frame-no-false-positive", h.probe_p0_frame_no_false_positive, h._frame_failures),
        ("C5 p0-archive-scores", h.probe_p0_archive_scores_match_measured, h._archive_failures),
        ("C6 p0-template-pixels", h.probe_p0_template_pixels_from_evidence, h._pixel_failures),
        ("C7 p0-wiring-declared", h.probe_p0_wiring_declared, h._wiring_failures),
        ("C8 p0-stone-row-hubs", h.probe_p0_stone_row_hubs, h._stone_hub_failures),
        ("C9 p0-threshold-floor", h.probe_p0_threshold_floor, h._threshold_floor_failures),
    )
    for name, probe, fails in cases:
        ok = probe() is True
        check(name, ok, "" if ok else f"{fails()[:2]}")
    check("scene.drift.check_all() == []", DRIFT.check_all() == [], f"{DRIFT.check_all()[:2]}")


def test_prove_red() -> None:
    print("\n== 7. 破坏实验：删 roi / roi 放宽吃兄弟 / 放宽阈值吃负例 / 删 order_by /")
    print("        模板换错文件 / 删 OCR 兜底 / 断接线 / 偷偷多接一处 NEW / 摘掉枢纽模板项 / 挪到 OCR 后 ==")
    print("        P0-3 专项：阈值 0.4（C4+C9）/ 删 OCR 兜底 / 删模板资产 / 双通道只剩一条 / 删模板叶 / 删 roi ==")
    check("hooks_102.prove_red()（全部破坏实验各自变红）", h.prove_red() is True)


# ---------------------------------------------------------------------------
# 8. 耗时（诚实边界）
# ---------------------------------------------------------------------------
def test_timing() -> None:
    print("\n== 8. 耗时：本票**测不了真机**（不碰设备），只给离线量测参考 ==")
    if h._deps_missing():
        return
    from PIL import Image  # noqa: PLC0415

    tpl = Image.open(ROOT / T.STONE_ICON.template_rel).convert("RGB")
    frame = h.frame_720(T.STONE_ICON.positive_frame)

    def timeit(label: str, fn, n: int = 5) -> float:
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        dt = (time.perf_counter() - t0) / n
        info(f"{label} = {dt * 1000:.1f} ms（numpy FFT，参考值）")
        return dt

    # 框架的做法是「先按 roi 裁剪再匹配」⇒ 这才是实际路径（小图，快）
    for key, spec in T.TEMPLATES.items():
        tpl = Image.open(ROOT / spec.template_rel).convert("RGB")
        frame = h.frame_720(spec.positive_frame)
        timeit(
            f"离线·[{key}] 按 roi {list(spec.roi)} 裁剪后全滑窗（灰+彩）",
            lambda tpl=tpl, frame=frame, spec=spec: h.roi_scores(frame, tpl, spec.roi),
        )
    # 全屏（只有 global_watch 才需要）—— 贵一两个数量级，别在节点上写全屏 roi
    timeit("离线·**全屏**彩口径滑窗（仅 global_watch 用）", lambda: h.zncc_color(frame, tpl), n=3)
    info("★上面这些数字都**不可**与框架比★（实现不同：numpy FFT vs OpenCV C++）——它们只用来说明"
         "「roi 裁剪」是本票的性能关键。")
    info("★真机耗时 = 未测★：已入库的 debug/maafw*.log 里，三个 P0 模板节点只在加载期被 `parse_node`，"
         "运行时从未进入（grep 'name\":\"PubStaminaStoneIcon' / 'WuchongBonus*Tpl' / 'SpecialNewBadgeTpl' = 0）")
    info("  ⇒ 没有框架侧数字，不给猜测值。同一份 maafw.log 的 OCR 基线：OcrTask n=83 med 0.124s"
         "（文档 avg 0.107s）；真机做法：")
    info("  (1) python debug\\wc77_profile_rounds.py debug\\maafw.log --top 18   （单节点识别耗时排行）")
    info("  (2) python debug\\wc77_node_period.py <节点名>                      （同节点真实重复周期）")
    info("  门槛：TemplateMatch 单节点 ≤ 同节点 OCR 的 1.5×（docs/guide/maa-pitfalls.md:36-40）")


def main() -> int:
    print("=" * 78)
    print("#102：模板识别 P0 三项（星导石行 / 是·否按钮 / NEW 徽标）离线验收")
    print("=" * 78)
    test_assets()
    test_zncc()
    test_sibling_mutual()
    test_ocr_fallback()
    test_wiring()
    test_hooks()
    test_prove_red()
    test_timing()
    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL GREEN —— 三项各自：正例命中 + 跨帧正例 + 负例不假阳 + 存档 ZNCC 与实测一致；")
    print("            P0-1/P0-2 已接线（模板优先、OCR 兜底；P0-1 已接全部消费链枢纽），"
          "P0-3 小行徽标已接 1 处双通道（大徽标 / 列表行仍 OCR）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
