# -*- coding: utf-8 -*-
"""离线单测：#28 归位认结算 / 奖励页 —— 收工后设备回到主城。

不需要游戏 / 设备（判定全在归位状态机的有序表 + 合成 OCR 上）；真机帧实证是 best-effort
（缺 maa / OCR 模型 / 帧则 SKIP，不算失败）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_settle_home.py

覆盖 #28 的验收：

  1. **结算页 → 归位 → 主城**（确定性）：合成 [结算帧, 列表帧, 主城帧]，逐帧分派
     ``RETURN_HOME_RULES`` -> 失败路径不存在（首命中 None = 停手），必须走到主城；
  2. **回归复现**：#26 的形态 —— 旧表（没有 settlement 规则）在结算帧首命中 = None
     = ``[归位] step0: 未知页面，停手`` = 设备留在结算页；新表首命中 = settlement；
  3. **动作安全**：结算动作只点【识别到的『继续』框中心】(359,1199)，绝不盲点；
  4. **真机帧实证（best-effort）**：对 #26 落盘的结算页 ``v26/shot_015_164900.png``
     （+ 结算横幅 / 继续帧）跑 OCR，断言首命中 = settlement（缺模型 / 帧则 SKIP）；
  5. **无漂移 + #9 守卫仍绿 + 挂点 prove-red 成立**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_28.py``。
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_28  # noqa: E402
import live_harness as ca  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

# 真机帧（#26）：设备被打满收工后【停在这一页】——结算 / 奖励页。
FRAME_SETTLE = Path(
    os.environ.get(
        "WF_H28_SETTLE_FRAME",
        str(TEMP_OPENCODE / "v26/shots/shot_015_164900.png"),
    )
)
# 结算横幅 / 继续帧（#13 rerun13b 证据）。
FRAME_BANNER = Path(
    os.environ.get(
        "WF_H28_BANNER_FRAME",
        str(TEMP_OPENCODE / "rerun13b/evidence/04_result_score_155039.png"),
    )
)
# OCR 资源（含 gitignore 的 det.onnx 运行期模型）；裸检出没有则真机帧实证 SKIP。
_ASSETS_CANDIDATES = (
    os.environ.get("WF_H28_ASSETS"),
    str(REPO_ROOT / "assets" / "resource"),
)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


def _assets_with_model() -> Path | None:
    for cand in _ASSETS_CANDIDATES:
        if not cand:
            continue
        p = Path(cand)
        if (p / "model" / "ocr" / "det.onnx").is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# 1. 结算页 → 归位 → 主城（确定性状态机）
# ---------------------------------------------------------------------------
def test_settlement_to_main_city() -> None:
    print("\n== 1. 结算页 → 归位 → 主城（确定性） ==")
    reached, seq = hooks_28.trace(
        [hooks_28.SETTLE_ITEMS, hooks_28.LIST_ITEMS, hooks_28.MAIN_CITY_ITEMS]
    )
    print(f"     分派序列 = {' → '.join(str(x) for x in seq)}")
    check("结算页首命中 = settlement（不是 None = 停手）", seq and seq[0] == "settlement")
    check("结算后落到列表页，点底部『主城』回家（bottom_nav_mc）",
          "bottom_nav_mc" in seq, f"seq={seq}")
    check("最终到主城（main_city）", reached and seq[-1] == "main_city", f"seq={seq}")


# ---------------------------------------------------------------------------
# 2. 回归复现：#26 的形态（旧表在结算页停手）
# ---------------------------------------------------------------------------
def test_regression_old_table_stops() -> None:
    print("\n== 2. 回归复现 #26：旧表在结算帧首命中 None = 停手（设备留在结算页） ==")
    old_rules = [r for r in hooks_28.rules() if r[0] != hooks_28.SETTLEMENT_RULE_ID]
    first = hooks_28._first_rule(old_rules, hooks_28.SETTLE_ITEMS)
    reached_old, seq_old = hooks_28.trace(
        [hooks_28.SETTLE_ITEMS, hooks_28.LIST_ITEMS, hooks_28.MAIN_CITY_ITEMS], old_rules
    )
    print(f"     旧表首命中 = {first!r}   旧表分派序列 = {seq_old}")
    check("旧表在结算帧【认不出】（首命中 None）", first is None)
    check("旧表在结算帧停手、永远到不了主城（复现 #26）", (not reached_old) and seq_old == [None])

    # 新表同一帧首命中 settlement（对照）。
    check("新表同一帧首命中 settlement",
          hooks_28._first_rule(hooks_28.rules(), hooks_28.SETTLE_ITEMS) == "settlement")


# ---------------------------------------------------------------------------
# 3. 动作安全：只点识别到的『继续』框中心
# ---------------------------------------------------------------------------
def test_action_never_blind() -> None:
    print("\n== 3. 动作安全：结算动作只点【识别到的『继续』框中心】，绝不盲点 ==")
    point = hooks_28.click_point_for(hooks_28.SETTLE_ITEMS)
    check("结算动作点在『继续』识别框中心 (359,1199)",
          point == hooks_28.EXPECTED_CONTINUE_CLICK, f"point={point}")
    # 升级结算页（只有大字「等级最大！」，读不到『继续』）-> 退回照抄 pipeline 的固定继续点。
    level_up = [("等级最大！", [51, 774, 113, 34])]
    point2 = hooks_28.click_point_for(level_up)
    check("升级结算页（无『继续』文字）退回固定继续点 [358,1198]",
          point2 == ca.LEVEL_UP_CONTINUE, f"point={point2}")
    check("固定继续点照抄 common.json::PubLevelUpContinue",
          ca.LEVEL_UP_CONTINUE == (358, 1198))


# ---------------------------------------------------------------------------
# 4. 真机帧实证（best-effort）
# ---------------------------------------------------------------------------
def _ocr_frame(frame: Path, assets: Path):
    import numpy as np
    from PIL import Image

    pil = Image.open(frame).convert("RGB")
    if pil.size != (720, 1280):
        pil = pil.resize((720, 1280))
    img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
    return ca.ocr(img, assets)


def test_real_frames_best_effort() -> None:
    print("\n== 4. 真机帧实证（best-effort）：#26 结算页首命中 = settlement ==")
    assets = _assets_with_model()
    if assets is None:
        skip("真机帧 OCR（结算页）", "缺 OCR 模型 det.onnx（裸检出）")
        return
    frames = [(FRAME_SETTLE, "结算页 shot_015（设备被打满后停在这一页）"), (FRAME_BANNER, "结算横幅 04_result_score")]
    any_frame = False
    for frame, label in frames:
        if not frame.is_file():
            skip(f"真机帧 OCR（{label}）", f"缺帧：{frame}")
            continue
        any_frame = True
        try:
            items = _ocr_frame(frame, assets)
        except Exception as exc:  # noqa: BLE001
            skip(f"真机帧 OCR（{label}）", f"OCR 不可用：{exc!r}")
            continue
        texts = [t for t, _ in items if t]
        first = hooks_28._first_rule(hooks_28.rules(), items)
        print(f"     {label}：文本（截断）={texts[:12]}")
        check(f"{label}：首命中 settlement", first == "settlement", f"pick={first}")
        old = hooks_28._first_rule(
            [r for r in hooks_28.rules() if r[0] != hooks_28.SETTLEMENT_RULE_ID], items
        )
        check(f"{label}：旧表首命中 None（复现停手）", old is None, f"old={old}")
    if not any_frame:
        skip("真机帧 OCR", "所有候选帧都不在（非取证机）")


# ---------------------------------------------------------------------------
# 5. 无漂移 + #9 守卫 + prove-red
# ---------------------------------------------------------------------------
def test_drift_guards_prove_red() -> None:
    print("\n== 5. 无漂移 + #9 守卫仍绿 + prove-red 成立 ==")
    try:
        from scene import drift  # noqa: PLC0415

        msgs = drift.check_all(repo_root=REPO_ROOT)
        check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("drift.check_all 可运行", False, f"raised {exc!r}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")
    check("挂点 return-home-settlement-page 已点亮",
          hooks_28.probe_settlement_known_page() is True)
    check("挂点 return-home-settlement-to-main-city 已点亮",
          hooks_28.probe_settlement_to_main_city() is True)
    check("hooks_28.prove_red() 成立（删规则 / 抢主城各自变红）",
          hooks_28.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 72)
    print("离线单测：#28 归位认结算 / 奖励页（收工后设备回到主城）")
    print("=" * 72)
    test_settlement_to_main_city()
    test_regression_old_table_stops()
    test_action_never_blind()
    test_real_frames_best_effort()
    test_drift_guards_prove_red()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
