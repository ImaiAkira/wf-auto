# -*- coding: utf-8 -*-
"""#43 离线测试：详情页【战斗】按钮对「单字 OCR 误差」有韧性（真机 `战三`），
但绝不点到相邻难度行的战斗（#35 保证不变）。

真机事实（设备 16448，成员 无猾机兵）——
MAA 原始帧把详情页【战斗】按钮**稳定读成 `战三`**（maafw.bak 日志 85/85），
严格 `^战斗$` 永不命中 → 详情页无法推进 → SpecialWait ⇄ SpecialEntry 卡到超时；
而**同一帧存成 jpg 后离线 OCR 又能读出 `战斗`** → 差异来自 MAA 原始帧重采样。

本测试 = 真机帧守卫（复用 hooks_43）+ 破坏复现 + 近似不越行断言 + 接线断言（离线、无设备）。
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
for _p in (str(TOOLS_DIR), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import side_impl as si  # noqa: E402
from batch_plan import DIFF_REGEX  # noqa: E402
from contract_hooks import hooks_35 as h35  # noqa: E402
from contract_hooks import hooks_43 as h43  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


class _Ctx:
    """回放内嵌真机 OCR（不产生任何点击）。"""

    def __init__(self, items):
        self._items = items

    def run_recognition(self, entry, image):
        rows = [types.SimpleNamespace(box=list(b), text=t) for t, b in self._items]
        return types.SimpleNamespace(all_results=rows)


class _Argv:
    def __init__(self, image, param: dict):
        self.image = image
        self.custom_recognition_param = json.dumps(param)


C1_CORRUPT = h43.C1_ITEMS_CORRUPTED
C1_OFFLINE = h43.C1_ITEMS_OFFLINE
C1_BOX = h43.C1_BATTLE_BOX


def _center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def test_match_rule() -> None:
    print("\n== 1. 单字误差判据：等长 + 只有一个字形不同 ==")
    check("严格 `战斗` -> exact", si.battle_text_match("战斗") == "exact")
    check("真机 `战三` -> approx（单字误差）", si.battle_text_match("战三") == "approx")
    check("`主城` -> 不认（两字都不同）", si.battle_text_match("主城") is None)
    check("`推荐编成` -> 不认（长度不同）", si.battle_text_match("推荐编成") is None)
    check("`挑战` -> 不认（两字都不同）", si.battle_text_match("挑战") is None)
    check("关掉近似通道后 `战三` -> 不认（= 严格 ^战斗$）",
          si.battle_text_match("战三", max_subst=0) is None)
    check("DEFAULT_BATTLE_TERMS 含规范文本 战斗", "战斗" in si.DEFAULT_BATTLE_TERMS)
    check("BATTLE_APPROX_MAX_SUBST == 1", si.BATTLE_APPROX_MAX_SUBST == 1,
          f"={si.BATTLE_APPROX_MAX_SUBST}")


def test_real_frame_guard() -> None:
    print("\n== 2. 真机帧守卫（hooks_43）：`战三` 帧仍命中声明的难度行 ==")
    msgs = h43._failures()
    check("hooks_43 真机帧守卫全绿", msgs == [], "; ".join(msgs[:3]))


def test_naught_robot_frame() -> None:
    print("\n== 3. 真机 `战三` 帧（无猾机兵）：命中该行战斗框 + 走 approx 通道 ==")
    box, detail = si.pick_target_battle_box(C1_CORRUPT, difficulty=DIFF_REGEX["中级"])
    check(f"声明「中级」命中本行战斗框 {C1_BOX}",
          box is not None and list(box) == list(C1_BOX), f"box={box}")
    check("走的是 approx（单字误差）通道", detail.get("battle_match") == "approx",
          f"match={detail.get('battle_match')}")
    owner = detail.get("row_owner")
    check("命中框行主 = 声明的难度「中级」（归属可证）",
          bool(owner) and re.search(DIFF_REGEX["中级"], owner[0] or ""),
          f"row_owner={owner}")
    # 战斗在难度名下方 ≈40px（真机几何 #35 不变）。
    names = [b for t, b in C1_CORRUPT if re.search(DIFF_REGEX["中级"], t or "")]
    check("战斗在难度名下方（dy≈37）",
          box is not None and 0 < _center(box)[1] - _center(names[0])[1] <= si.BATTLE_ROW_MAX_GAP)


def test_strict_regression_reproduces_defect() -> None:
    print("\n== 4. 破坏复现：退回严格 ^战斗$ → 同一帧不命中（= 真机卡死根因） ==")
    box, detail = si.pick_target_battle_box(
        C1_CORRUPT, difficulty=DIFF_REGEX["中级"], battle_approx_max_subst=0)
    check("严格匹配下 `战三` 帧不命中任何战斗框", box is None, f"box={box}")
    check("原因 = 未找到战斗按钮", detail.get("reason") == "未找到战斗按钮",
          f"reason={detail.get('reason')}")


def test_offline_frame_reads_correctly() -> None:
    print("\n== 5. 同一帧离线读数 `战斗`：命中同一框、走 exact 通道 ==")
    box, detail = si.pick_target_battle_box(C1_OFFLINE, difficulty=DIFF_REGEX["中级"])
    check(f"离线读数命中同一框 {C1_BOX}",
          box is not None and list(box) == list(C1_BOX), f"box={box}")
    check("走的是 exact 通道", detail.get("battle_match") == "exact",
          f"match={detail.get('battle_match')}")


def test_no_wrong_row() -> None:
    print("\n== 6. 不点错行（#35 保证不变）：中级行读成 `战三`，各行仍配自己那一行 ==")
    multi = []
    for t, b in h35.MULTI_ITEMS:
        if t == "战斗" and list(b) == [86, 1068, 35, 24]:
            t = "战三"
        multi.append((t, list(b)))
    expected = {
        "超级": [88, 501, 31, 16],
        "高级+": [87, 689, 32, 20],
        "高级": [87, 880, 32, 20],
        "中级": [86, 1068, 35, 24],
    }
    for declared, exp_box in expected.items():
        rx = DIFF_REGEX[declared]
        box, detail = si.pick_target_battle_box(multi, difficulty=rx)
        check(f"{declared}: 命中本行战斗框 {exp_box}",
              box is not None and list(box) == list(exp_box), f"box={box}")
        own = detail.get("row_owner")
        check(f"{declared}: 命中框行主 = 声明的难度",
              bool(own) and re.search(rx, own[0] or ""), f"row_owner={own}")
    # 未声明的难度（初级）本帧没有 → 近似也绝不臆测命中。
    box, detail = si.pick_target_battle_box(multi, difficulty=DIFF_REGEX["初级"])
    check("初级（本帧无该行）→ 不命中", box is None, f"detail={detail}")


def test_approx_never_crosses_row() -> None:
    print("\n== 7. 近似候选超出同一行带（> max_gap）→ 不命中 ==")
    far = [
        ("机工神兵菲诺梅那中级", [203, 458, 280, 28]),
        ("战三", [88, 700, 29, 16]),   # dy=242 > 120
    ]
    box, _d = si.pick_target_battle_box(far, difficulty=DIFF_REGEX["中级"])
    check("近似候选过远 → 不命中（绝不跨行）", box is None, f"box={box}")


def test_recognizer_wiring() -> None:
    print("\n== 8. 接线：识别器（difficulty-only，GUI 形态）在 `战三` 帧上仍命中 ==")
    rec = si.SpecialTargetFightRecognition()
    r = rec.analyze(_Ctx(C1_CORRUPT), _Argv(C1_CORRUPT, {"difficulty": DIFF_REGEX["中级"]}))
    check("识别器命中该行战斗框", r.box is not None and list(r.box) == list(C1_BOX),
          f"box={r.box}")


def test_hook35_still_green() -> None:
    print("\n== 9. 回归：#35 真机帧守卫仍全绿（近似通道不破坏精确配对） ==")
    msgs = h35._pair_failures()
    check("hooks_35 真机帧守卫全绿", msgs == [], "; ".join(msgs[:3]))


def main() -> int:
    print("=" * 74)
    print("#43：详情页【战斗】按钮容忍单字 OCR 误差（真机 `战三`），且不点错行（离线测试）")
    print("=" * 74)
    test_match_rule()
    test_real_frame_guard()
    test_naught_robot_frame()
    test_strict_regression_reproduces_defect()
    test_offline_frame_reads_correctly()
    test_no_wrong_row()
    test_approx_never_crosses_row()
    test_recognizer_wiring()
    test_hook35_still_green()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：`战三` 单字误差仍命中声明难度行、近似不越行、#35 保证不变 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
