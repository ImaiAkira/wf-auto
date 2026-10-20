# -*- coding: utf-8 -*-
"""#49 离线测试：详情页【战斗】按钮对「单字框（丢尾字）」OCR 误差有韧性（真机 `战`），
但绝不点到相邻难度行 / 无声明难度的路径（#35/#42 保证不变）。

真机事实（设备 16448，降临讨伐 Q1 全量扫描，捕获帧逐条重跑 OCR）——
29 个成员里 25 个正常；4 个导航到**自己**的详情页（#42 身份 match）却**定位不到【战斗】**
按钮 → 空转到超时（账本为空）。真机帧离线 OCR（同一 OcrTask + `model/ocr`）：

    赤之女王   s01  → `战`   [91, 505, 14, 9]   （丢「斗」）
    方舟守护者 r4   → `战`   [88, 501, 19, 17]  （丢「斗」）
    青之女王   r5   → `战`   [92, 506,  9,  7]  （丢「斗」）
    伊尔梅塔雷 s06  → `战头` [88, 504, 27, 10]  （斗→头，单字替换 —— #43 通道可救）

#43 只覆盖「等长 + 单字替换」，**不覆盖「丢字」** → s01/r4/r5 卡死。本测试 = 真机帧守卫
（复用 hooks_49）+ 破坏复现 + 不越行/不越权断言 + #35/#42 回归（离线、无设备）。
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
from contract_hooks import hooks_42 as h42  # noqa: E402
from contract_hooks import hooks_49 as h49  # noqa: E402

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


def test_match_rule() -> None:
    print("\n== 1. 三条通道的边界：exact / 单字替换(approx) / 丢尾字(approx_trunc) ==")
    check("严格 `战斗` -> exact", si.battle_text_match("战斗") == "exact")
    check("真机 `战三` -> approx（单字替换）", si.battle_text_match("战三") == "approx")
    check("真机 `战头` -> approx（单字替换）", si.battle_text_match("战头") == "approx")
    check("真机 `战` -> approx_trunc（丢尾字）", si.battle_text_match("战") == "approx_trunc")
    check("`斗` -> 不认（后缀不是前缀）", si.battle_text_match("斗") is None)
    check("`主城` -> 不认（等长两字都不同）", si.battle_text_match("主城") is None)
    check("`挑战` -> 不认", si.battle_text_match("挑战") is None)
    check("`推荐编成` -> 不认（长度不同）", si.battle_text_match("推荐编成") is None)
    check("空串 -> 不认", si.battle_text_match("") is None)
    check("关掉截断通道后 `战` -> 不认",
          si.battle_text_match("战", max_missing=0) is None)
    check("关掉替换通道后 `战三` -> 不认（= 严格 ^战斗$）",
          si.battle_text_match("战三", max_subst=0) is None)
    check("BATTLE_APPROX_MAX_MISSING == 1", si.BATTLE_APPROX_MAX_MISSING == 1,
          f"={si.BATTLE_APPROX_MAX_MISSING}")


def test_real_frame_guard() -> None:
    print("\n== 2. 真机帧守卫（hooks_49）：单字帧仍命中声明的难度行 ==")
    msgs = h49._failures()
    check("hooks_49 真机帧守卫全绿", msgs == [], "; ".join(msgs[:3]))


def test_truncated_frames() -> None:
    print("\n== 3. 真机单字帧（s01/r4/r5）：命中本行战斗框 + 走 approx_trunc + 行主可证 ==")
    for frame in h49.FRAMES:
        if frame["match"] != "approx_trunc":
            continue
        rx = DIFF_REGEX[frame["declared"]]
        box, detail = si.pick_target_battle_box(frame["items"], difficulty=rx)
        check(f"{frame['name']}：命中本行战斗框 {frame['box']}",
              box is not None and list(box) == list(frame["box"]), f"box={box}")
        check(f"{frame['name']}：走 approx_trunc（丢尾字）通道",
              detail.get("battle_match") == "approx_trunc",
              f"match={detail.get('battle_match')}")
        owner = detail.get("row_owner")
        check(f"{frame['name']}：行主 = 声明的难度行 {frame['row']!r}",
              bool(owner) and owner[0] == frame["row"], f"row_owner={owner}")
        # 战斗在难度名下方（真机几何 #35 不变）。
        names = [b for t, b in frame["items"] if re.search(rx, t or "")]
        check(f"{frame['name']}：战斗在难度名下方（0<dy≤max_gap）",
              box is not None and 0 < (box[1] + box[3] / 2.0) - (names[0][1] + names[0][3] / 2.0)
              <= si.BATTLE_ROW_MAX_GAP)


def test_s06_substitution() -> None:
    print("\n== 4. 真机 s06（`战头` 单字替换）：走 approx 通道、命中本行 ==")
    box, detail = si.pick_target_battle_box(h49.S06_ITEMS, difficulty=DIFF_REGEX["中级"])
    check("命中本行战斗框 [88,504,27,10]",
          box is not None and list(box) == [88, 504, 27, 10], f"box={box}")
    check("走 approx（单字替换）通道", detail.get("battle_match") == "approx",
          f"match={detail.get('battle_match')}")


def test_strict_regression_reproduces_defect() -> None:
    print("\n== 5. 破坏复现：关掉截断通道（max_missing=0）→ 单字帧不命中（= 真机卡死根因） ==")
    for frame in h49.FRAMES:
        if frame["match"] != "approx_trunc":
            continue
        box, detail = si.pick_target_battle_box(
            frame["items"], difficulty=DIFF_REGEX[frame["declared"]],
            battle_approx_max_missing=0,
        )
        check(f"{frame['name']}：不命中任何战斗框", box is None, f"box={box}")
        check(f"{frame['name']}：原因 = 未找到战斗按钮",
              detail.get("reason") == "未找到战斗按钮", f"reason={detail.get('reason')}")


def test_no_wrong_row() -> None:
    print("\n== 6. 不点错行（#35 保证不变）：截断也绝不跨行 / 越权 ==")
    far = [
        ("诅咒弧魔艾基尔中级", [203, 458, 252, 28]),
        ("战", [88, 900, 20, 12]),   # dy=442 > 120
    ]
    box, _d = si.pick_target_battle_box(far, difficulty=DIFF_REGEX["中级"])
    check("截断候选超出同一行带 → 不命中", box is None, f"box={box}")

    right = [
        ("诅咒弧魔艾基尔中级", [100, 458, 252, 28]),
        ("战", [360, 500, 20, 12]),  # 在难度名右列，不是按钮列
    ]
    box, _d = si.pick_target_battle_box(right, difficulty=DIFF_REGEX["中级"])
    check("截断候选在难度名右列 → 不命中", box is None, f"box={box}")

    box, _d = si.pick_target_battle_box(h49.S01_ITEMS, difficulty=None)
    check("topmost（无声明难度）→ 截断通道不启用、单字 `战` 不命中", box is None, f"box={box}")

    box, _d = si.pick_target_battle_box(h49.S01_ITEMS, difficulty=DIFF_REGEX["初级"])
    check("声明本帧不存在的难度（初级）→ 不命中", box is None, f"box={box}")


def test_exact_path_unchanged() -> None:
    print("\n== 7. exact 不受影响（工作帧对照）：碧之女王双行各配自己那一行 ==")
    for declared, (exp_box, exp_row) in h49.S02OK_EXPECTED.items():
        rx = DIFF_REGEX[declared]
        box, detail = si.pick_target_battle_box(h49.S02OK_ITEMS, difficulty=rx)
        check(f"{declared}: 命中本行战斗框 {exp_box}",
              box is not None and list(box) == list(exp_box), f"box={box}")
        check(f"{declared}: 走 exact 通道", detail.get("battle_match") == "exact",
              f"match={detail.get('battle_match')}")
        owner = detail.get("row_owner")
        check(f"{declared}: 行主 = {exp_row!r}",
              bool(owner) and owner[0] == exp_row, f"row_owner={owner}")


def test_recognizer_wiring() -> None:
    print("\n== 8. 接线：识别器（difficulty + member，GUI/批量形态）在单字帧上仍命中 ==")
    rec = si.SpecialTargetFightRecognition()
    r = rec.analyze(
        _Ctx(h49.S01_ITEMS),
        _Argv(h49.S01_ITEMS, {"difficulty": DIFF_REGEX["中级"], "member": "赤之女王讨伐"}),
    )
    check("识别器命中该行战斗框 [91,505,14,9]",
          r.box is not None and list(r.box) == [91, 505, 14, 9], f"box={r.box}")


def test_regressions() -> None:
    print("\n== 9. 回归：#35（真机帧配对）与 #42（身份闸）仍全绿 ==")
    check("hooks_35 真机帧守卫全绿", h35._pair_failures() == [],
          "; ".join(h35._pair_failures()[:3]))
    check("hooks_42 身份闸（拒错页）仍绿",
          h42.probe_detail_identity_blocks_wrong_page() is True)


def main() -> int:
    print("=" * 74)
    print("#49：详情页【战斗】按钮容忍单字框（丢尾字）OCR 误差，且不点错行（离线测试）")
    print("=" * 74)
    test_match_rule()
    test_real_frame_guard()
    test_truncated_frames()
    test_s06_substitution()
    test_strict_regression_reproduces_defect()
    test_no_wrong_row()
    test_exact_path_unchanged()
    test_recognizer_wiring()
    test_regressions()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：单字框仍命中声明难度行、截断不越行/不越权、#35/#42 保证不变 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
