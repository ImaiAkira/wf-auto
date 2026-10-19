# -*- coding: utf-8 -*-
"""离线单测：#42 列表选行错位 → 静默打了别的成员（请求 A、打开 B、还记成 A）。

不需要游戏 / 设备（判据全在**真机帧 OCR 夹具** + 纯函数 + 页面状态机上）；真机帧回放是
best-effort（缺 maa / 帧 / OCR 模型则 SKIP，不算失败）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_row_selection.py
    .venv\\Scripts\\python.exe tools\\test_row_selection.py --prove-red

覆盖 #42 的验收：

  1. **详情页身份闸**（真机帧：joss_r9 f_0070 = 碧之女王页、joss_C3 f_0010 = 圣夜的淘气鬼页）：
     目标 A / 页面 B **必须被拒**（伊劳德雷斯↔碧之女王、水狂↔圣夜的淘气鬼）；页面就是目标时命中；
     同后缀家族（青之女王 vs 碧之女王）也分得开；
  2. **选行点击复核**：识别框已过期（列表还在动）时按**新框**点击；目标不在重抓帧里时**不点**；
  3. **离线复现「深行多次滑动 + 收惯性时点行」**：旧行为滑到**别人的**详情页并记成目标；
     新行为命中目标自己的行（或在复核不过时**不点**，绝不点错）；
  4. **真机帧实证（best-effort）**：对真实截图重跑 MAA OCR，断言标题可读且「目标 A / 页面 B」
     在真帧上同样被拒；
  5. **破坏实验**（prove-red）：关掉身份闸 / 让选行点击信任陈旧框 → 对应守卫各自变红；
  6. **无漂移 + #9 三条既有路径守卫仍绿**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_42.py``。
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR), str(REPO_ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402

import hooks_42  # noqa: E402

ASSETS_DIR = REPO_ROOT / "assets" / "resource"
PIPELINE_DIR = ASSETS_DIR / "pipeline"

FAILS: list[str] = []
SKIPS: list[str] = []

# 真机帧证据（#42；缺则 best-effort 段 SKIP）。
#   r9：目标 伊劳德雷斯讨伐 → 打开的是 碧之女王 的详情页（帧 f_0070）
#   C3：目标 水狂精灵兽   → 打开的是 圣夜的淘气鬼 的详情页（帧 f_0010）
FRAME_R9 = Path(
    os.environ.get(
        "WF_R42_R9",
        str(TEMP_OPENCODE / "sweepjoss2/frames/joss_r9/f_0070.jpg"),
    )
)
FRAME_C3 = Path(
    os.environ.get(
        "WF_R42_C3",
        str(TEMP_OPENCODE / "sweepjoss2/frames/joss_C3/f_0010.jpg"),
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


def _sd() -> dict:
    return drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]


# ---------------------------------------------------------------------------
# 0. 制品绑定：两道闸真的接在 pipeline 上
# ---------------------------------------------------------------------------
def test_product_binding() -> None:
    print("\n== 0. 制品绑定：选行点击复核 + 身份闸都接在 pipeline 上 ==")
    check("挂点 detail-identity-blocks-wrong-page 点亮",
          hooks_42.probe_detail_identity_blocks_wrong_page() is True)
    check("挂点 row-click-reverifies-target-before-tap 点亮",
          hooks_42.probe_row_click_reverifies_target() is True)
    check("挂点 deep-row-tap-race-repro 点亮",
          hooks_42.probe_deep_row_tap_race_repro() is True)
    check("产物绑定断言全绿", hooks_42._pipeline_failures() == [],
          f"{hooks_42._pipeline_failures()[:1]}")
    sd = _sd()
    action = (sd["SpecialEnterBoss"].get("action") or {})
    print(f"     SpecialEnterBoss.action = {action}")
    print(f"     SpecialScrollList.post_delay = {sd['SpecialScrollList'].get('post_delay')}")


# ---------------------------------------------------------------------------
# 1. 详情页身份闸：目标 A / 页面 B 必须被拒
# ---------------------------------------------------------------------------
def test_identity_gate() -> None:
    print("\n== 1. 详情页身份闸：真机帧「目标 A / 页面 B」必须被拒 ==")
    si = hooks_42._load_side_impl()
    for name, items, member, difficulty, expect in hooks_42.IDENTITY_CASES:
        verdict, info = si.detail_page_identity(items, member)
        label = "命中" if expect else "拒绝/不介入"
        check(
            f"{name}：[{label}] title={info.get('title')!r} 判定={verdict}",
            (verdict == "match") if expect else (verdict in ("mismatch", "unknown", "not_detail")),
            f"归属={info.get('best_member')!r}/{info.get('best_sim')} "
            f"目标相似度={info.get('target_sim')}",
        )
    check("r9 缺陷：碧之女王页被判成『不是伊劳德雷斯』（mismatch）",
          si.detail_page_identity(hooks_42.BINU_PAGE, "伊劳德雷斯讨伐")[0] == "mismatch")
    check("C3 缺陷：圣夜的淘气鬼页对 水狂精灵兽 不被接受",
          si.detail_page_identity(hooks_42.SEIYA_PAGE, "水狂精灵兽")[0] != "match")
    check("列表页不介入（not_detail）",
          si.detail_page_identity(hooks_42.LIST_PAGE, "水狂精灵兽")[0] == "not_detail")


# ---------------------------------------------------------------------------
# 2. 选行点击复核
# ---------------------------------------------------------------------------
def test_row_click_reverify() -> None:
    print("\n== 2. 选行点击复核：陈旧识别框 → 按新框点；目标不在 → 不点 ==")
    si = hooks_42._load_side_impl()
    for name, member, rec_box, expect_click in hooks_42.ROW_CLICK_CASES:
        ctx = hooks_42._FakeActionContext(hooks_42.ROW_LIST_PAGE)
        si.SpecialBatchFightAction().run(
            ctx,
            hooks_42._FakeActionArgv(box=rec_box, param={"row_click": True, "member": member}),
        )
        if expect_click is None:
            check(f"{name}：目标不在重抓帧里 → 不点", ctx.clicked_point is None,
                  f"clicked={ctx.clicked_point}")
        else:
            want = (expect_click[0] + expect_click[2] / 2.0, expect_click[1] + expect_click[3] / 2.0)
            got = ctx.clicked_point
            check(f"{name}：点到了复核帧里的目标行 {want}", got is not None
                  and abs(got[0] - want[0]) <= 1.5 and abs(got[1] - want[1]) <= 1.5,
                  f"got={got} rec_box={rec_box}")


# ---------------------------------------------------------------------------
# 3. 离线复现：深行多次滑动 + 收惯性时点行
# ---------------------------------------------------------------------------
def test_deep_row_repro() -> None:
    print("\n== 3. 离线复现：深行多次滑动 + 收惯性时点行 ==")
    si = hooks_42._load_side_impl()
    target = hooks_42.DEEP_TARGET
    print(f"     列表 = {hooks_42.DEEP_ROWS}；目标 = {target}；窗口 {hooks_42.DEEP_WINDOW} 行；"
          f"每步 {hooks_42.DEEP_STEP} 行；回弹 {hooks_42.DEEP_GLIDE} 行")

    old = hooks_42._DeepRowSim(si, reverify=False)
    old_opened = old.run(target, glide=hooks_42.DEEP_GLIDE)
    print(f"     旧行为：打开 {old_opened!r}（trace={old.trace}）")
    check(f"旧行为复现『滑到别人的行』（{hooks_42.DEEP_WRONG}）",
          old_opened == hooks_42.DEEP_WRONG)

    new = hooks_42._DeepRowSim(si, reverify=True)
    new_opened = new.run(target, glide=hooks_42.DEEP_GLIDE)
    print(f"     新行为：打开 {new_opened!r}（trace={new.trace}）")
    check(f"新行为命中目标自己的行（{target}）", new_opened == target)
    check("新行为绝不打开别人的详情页", new_opened != hooks_42.DEEP_WRONG)

    check("错页处置：首次 back_out（退回重导航）",
          si.plan_wrong_detail_action(target, 1)[0] == "back_out")
    action, reason = si.plan_wrong_detail_action(target, si.WRONG_DETAIL_LIMIT + 1)
    check("错页处置：连续超限 → skip 且写明原因",
          action == "skip" and "跳过" in reason and target in reason, f"{action}/{reason}")


# ---------------------------------------------------------------------------
# 4. 真机帧实证（best-effort；缺 maa / 帧 / OCR 模型则 SKIP）
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


def _scored_ocr(img):
    """对 720 空间 BGR 图跑 pipeline 的 OcrTask，返回 ``[(text, box, score)]``。

    走 ``live_harness`` 的离线 OCR 通道（同一份 Resource/Tasker），但**保留 score** ——
    标题置信度是「读不准就别判错页」的判据，所以 best-effort 段要拿到它才有意义。
    """
    import numpy as np  # noqa: PLC0415

    import live_harness as ca  # noqa: PLC0415

    tasker, ctrl = ca._ensure_ocr(ASSETS_DIR)
    ctrl.img = np.ascontiguousarray(img)
    job = tasker.post_task("OcrTask", {})
    job.wait()
    detail = job.get()
    out = []
    if detail is None:
        return out
    for node in detail.nodes:
        reco = node.recognition
        if reco is None:
            continue
        for r in reco.all_results or []:
            box = getattr(r, "box", None)
            if not box or len(box) != 4:
                continue
            try:
                score = float(getattr(r, "score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            out.append(((getattr(r, "text", "") or "").strip(), [int(v) for v in box], score))
    return out


def test_real_frames_best_effort() -> None:
    print("\n== 4. 真机帧实证（best-effort）：真帧上重跑 MAA OCR，目标 A / 页面 B 仍被拒 ==")
    si = hooks_42._load_side_impl()
    for label, path, member_ok, member_bad in (
        ("r9 碧之女王页", FRAME_R9, "碧之女王讨伐", "伊劳德雷斯讨伐"),
        ("C3 圣夜的淘气鬼页", FRAME_C3, "圣夜的淘气鬼", "水狂精灵兽"),
    ):
        if not path.is_file():
            skip(f"真机帧 {label}", f"缺帧：{path}")
            continue
        img = _load_bgr(path)
        if img is None:
            skip(f"真机帧 {label}", "缺 numpy/PIL")
            continue
        try:
            items = _scored_ocr(img)
        except Exception as exc:  # noqa: BLE001
            skip(f"真机帧 {label} MAA OCR", f"缺 maa / OCR 模型 / 资源：{exc!r}")
            continue
        if not items:
            skip(f"真机帧 {label} MAA OCR", "OCR 返回空（模型缺失？）")
            continue
        title = si._pick_detail_title(si._as3(items))
        v_ok, i_ok = si.detail_page_identity(items, member_ok)
        v_bad, i_bad = si.detail_page_identity(items, member_bad)
        print(f"     {path.name}: OCR {len(items)} 条，标题={title and title['text']!r} "
              f"score={title and round(title['score'], 3)}")
        check(f"真机帧 {label}：读到详情页横幅标题", title is not None)
        check(f"真机帧 {label}：页面就是目标（{member_ok}）→ 接受", v_ok == "match",
              f"verdict={v_ok} info={i_ok}")
        check(f"真机帧 {label}：目标 {member_bad} → 判为错页（真帧拒错页）",
              v_bad == "mismatch", f"verdict={v_bad} info={i_bad}")


# ---------------------------------------------------------------------------
# 5. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 5. 破坏实验：关掉身份闸 / 让选行点击信任陈旧框 → 守卫各自变红 ==")
    check("hooks_42.prove_red() 成立", hooks_42.prove_red() is True)


# ---------------------------------------------------------------------------
# 6. 无漂移 + #9 守卫
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 6. 无漂移 + #9 三条既有路径守卫仍绿 ==")
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
    print("离线单测：#42 列表选行错位 → 静默打了别的成员（请求 A、打开 B、记成 A）")
    print("=" * 72)
    test_product_binding()
    test_identity_gate()
    test_row_click_reverify()
    test_deep_row_repro()
    test_prove_red()
    test_real_frames_best_effort()
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
