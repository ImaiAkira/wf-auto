# -*- coding: utf-8 -*-
"""离线单测：#48 归位必须认识幻想共斗「战斗结束」QUEST RESULT 页（【解散】/【返回房间】）。

不需要游戏 / 设备；真机帧实证是 best-effort（缺 maa / OCR 模型则 SKIP，不算失败）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_coop_result_home.py

覆盖 #48 的验收：

  1. **共斗结算页是已知页面**：合成帧（照抄真机帧 ``s_stuck.png``）首命中 = ``coop_result``
     （不是 ``settlement``），且**排在 settlement 之前**；动作**只点识别到的按钮框中心**
     （【解散】@(214,1200)），**绝不点顶部 QUEST RESULT 横幅**；
  2. **不抢**排名结算页（``s_afterQ2.png``，归 settlement 的【继续】）/ 主城 / 共斗房解散确认框；
  3. **确定性回归**：共斗结算页 →（点【解散】）→ 主城；旧形态（settlement 点顶部横幅）原地空转
     （复现 #48：10 步仍回不了主城）；
  4. **真机帧实证（best-effort）**：对 ``tools/frames/coop_result_*.png`` 跑 OCR，断言分派与动作点；
  5. **无漂移 + #9 守卫 + 挂点 prove-red 成立**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_48.py``。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_48  # noqa: E402
import live_harness as ca  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 真机帧实证的 OCR 资源：优先显式环境变量，其次本工作树 assets，最后退回主工作树。
# ---------------------------------------------------------------------------
def _pick_assets() -> Path | None:
    cands: list[Path] = []
    env = os.environ.get("WF_H48_ASSETS")
    if env:
        cands.append(Path(env))
    cands.append(REPO_ROOT / "assets" / "resource")
    cands.append(Path(__file__).resolve().parents[1] / "assets" / "resource")
    for c in cands:
        if (c / "model" / "ocr" / "det.onnx").is_file():
            return c
    return None


FRAME_DIR = TOOLS_DIR / "frames"
FRAMES = {
    "dissolve": "coop_result_dissolve.png",   # 共斗「战斗结束」页（【解散】/【返回房间】）
    "rankings": "coop_result_rankings.png",   # 共斗排名结算页（【继续】）
    "home": "coop_result_home.png",           # 主城（回归终点）
}


def _ocr_frame(assets: Path, name: str):
    path = FRAME_DIR / FRAMES[name]
    if not path.is_file():
        return None, f"缺帧：{path}"
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        return None, f"缺 numpy/PIL：{exc!r}"
    try:
        pil = Image.open(path).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280))
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        return ca.ocr(img, assets), None
    except Exception as exc:  # noqa: BLE001
        return None, f"OCR 不可用：{exc!r}"


# ---------------------------------------------------------------------------
# 1. 共斗结算页是已知页面 + 读后动 + 顺序（#48）
# ---------------------------------------------------------------------------
def test_coop_result_known_page() -> None:
    print("\n== 1. 归位认识共斗结算页（读后动，绝不点顶部横幅） ==")
    rules_ = hooks_48.rules()

    check("共斗结算帧（合成）被认出", ca._is_coop_result(hooks_48.COOP_RESULT_ITEMS))
    check("只剩【返回房间】的退化帧仍被认出", ca._is_coop_result(hooks_48.COOP_RESULT_FALLBACK_ITEMS))
    check("首命中 = coop_result（不是 settlement）",
          hooks_48._first_rule(rules_, hooks_48.COOP_RESULT_ITEMS) == "coop_result")
    check("coop_result 排在 settlement 之前",
          hooks_48.rule_ids().index("coop_result") < hooks_48.rule_ids().index("settlement"))

    check("coop_result 不误命中排名结算页", not ca._is_coop_result(hooks_48.RANKINGS_ITEMS))
    check("coop_result 不误命中主城", not ca._is_coop_result(hooks_48.MAIN_CITY_ITEMS))
    check("coop_result 不误命中共斗房解散确认框（无【返回房间】）",
          not ca._is_coop_result(hooks_48.ROOM_DIALOG_ITEMS))

    pt = hooks_48._click_point_for(hooks_48.COOP_RESULT_ITEMS, "coop_result", rules_)
    check("共斗结算页只点识别到的【解散】框中心",
          pt == hooks_48.EXPECTED_DISSOLVE_CLICK, f"pt={pt}")
    check("绝不点顶部 QUEST RESULT 横幅",
          pt is not None and pt != hooks_48.BANNER_CENTER and pt[1] >= hooks_48.BUTTON_ROW_Y_MIN,
          f"pt={pt} banner={hooks_48.BANNER_CENTER}")

    fb = hooks_48._click_point_for(hooks_48.COOP_RESULT_FALLBACK_ITEMS, "coop_result", rules_)
    check("退化帧退回点【返回房间】框中心",
          fb == hooks_48.EXPECTED_RETURN_ROOM_CLICK, f"pt={fb}")

    # 不抢：排名页仍归 settlement、主城仍是 main_city。
    check("排名结算页首命中 = settlement（不抢【继续】）",
          hooks_48._first_rule(rules_, hooks_48.RANKINGS_ITEMS) == "settlement")
    check("主城帧首命中 = main_city",
          hooks_48._first_rule(rules_, hooks_48.MAIN_CITY_ITEMS) == "main_city")


# ---------------------------------------------------------------------------
# 2. 确定性回归：共斗结算页 -> 主城；旧形态空转
# ---------------------------------------------------------------------------
def test_walk_to_main_city() -> None:
    print("\n== 2. 确定性回归：共斗结算页 →（点【解散】）→ 主城；旧形态点横幅空转 ==")
    reached, seq = hooks_48.walk(hooks_48.rules(), hooks_48.COOP_RESULT_ITEMS)
    check("共斗结算页 →（解散）→ 主城",
          reached and seq == ["coop_result", "main_city"], f"seq={seq}")

    without = [r for r in hooks_48.rules() if r[0] != "coop_result"]
    old_reached, old_seq = hooks_48.walk(without, hooks_48.COOP_RESULT_ITEMS)
    check("旧形态（无 coop_result）：settlement 点顶部横幅、10 步空转（复现 #48）",
          (not old_reached) and old_seq[:1] == ["settlement"] and len(old_seq) == 10,
          f"reached={old_reached} seq_len={len(old_seq)}")


# ---------------------------------------------------------------------------
# 3. 真机帧实证（best-effort）
# ---------------------------------------------------------------------------
def test_real_frames_best_effort() -> None:
    print("\n== 3. 真机帧实证（best-effort）：共斗结算页 / 排名页 / 主城 ==")
    assets = _pick_assets()
    if assets is None:
        skip("真机帧 OCR（#48）",
             "缺 OCR 模型（WF_H48_ASSETS / 本工作树 / 主工作树都没有 det.onnx）")
        return

    rules_ = hooks_48.rules()

    items, err = _ocr_frame(assets, "dissolve")
    if items is None:
        skip("真机帧 共斗结算页", err or "OCR 失败")
    else:
        texts = [t for t, _ in items]
        print(f"  帧 共斗结算页（{FRAMES['dissolve']}）文本节选：{texts[:12]}")
        check("真机共斗结算帧：首命中 = coop_result",
              hooks_48._first_rule(rules_, items) == "coop_result")
        check("真机共斗结算帧：不是 settlement（旧缺陷路径）",
              hooks_48._first_rule(rules_, items) != "settlement")
        box = ca._pick(items, r"^解散$")
        pt = hooks_48._click_point_for(items, "coop_result", rules_)
        if box is None:
            skip("真机共斗结算帧 动作点", "OCR 未读到【解散】（动作点无法与识别框对账）")
        else:
            check("真机共斗结算帧：动作点 = 识别到的【解散】框中心（读后动，不盲点）",
                  pt == ca._center(box), f"pt={pt} box_center={ca._center(box)}")
        banner = ca._pick(items, r"QUESTRE")
        if banner is not None:
            check("真机共斗结算帧：动作点不是顶部 QUEST RESULT 横幅",
                  pt is not None and pt != ca._center(banner), f"pt={pt} banner={ca._center(banner)}")

    items, err = _ocr_frame(assets, "rankings")
    if items is None:
        skip("真机帧 排名结算页", err or "OCR 失败")
    else:
        texts = [t for t, _ in items]
        print(f"  帧 排名结算页（{FRAMES['rankings']}）文本节选：{texts[:10]}")
        check("真机排名结算帧：不判成 coop_result", not ca._is_coop_result(items))
        check("真机排名结算帧：首命中 = settlement（仍归 settlement 的【继续】）",
              hooks_48._first_rule(rules_, items) == "settlement")

    items, err = _ocr_frame(assets, "home")
    if items is None:
        skip("真机帧 主城", err or "OCR 失败")
    else:
        check("真机主城帧：首命中 = main_city",
              hooks_48._first_rule(rules_, items) == "main_city")


# ---------------------------------------------------------------------------
# 4. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 4. 挂点点亮 + prove-red ==")
    check("挂点 return-home-coop-result 已点亮", hooks_48.probe_coop_result() is True)
    check("挂点 return-home-coop-result-to-main-city 已点亮",
          hooks_48.probe_coop_result_to_main_city() is True)
    check("hooks_48.prove_red() 成立（删规则 / 判据过宽各自变红）", hooks_48.prove_red() is True)


# ---------------------------------------------------------------------------
# 5. 无漂移 + #9 守卫
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 5. 无漂移 + #9 三条既有路径守卫仍绿 ==")
    try:
        from scene import drift

        msgs = drift.check_all(repo_root=REPO_ROOT)
        check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("drift.check_all 可运行", False, f"raised {exc!r}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [])
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：#48 归位认识幻想共斗「战斗结束」QUEST RESULT 页")
    print("=" * 70)
    test_coop_result_known_page()
    test_walk_to_main_city()
    test_real_frames_best_effort()
    test_hooks_and_prove_red()
    test_drift_and_guards()
    print("\n" + "=" * 70)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
