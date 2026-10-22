# -*- coding: utf-8 -*-
"""#35 离线测试：详情页【难度名 ↔ 战斗按钮】按真机几何配对。

真机事实（`recon_unm/recon.log`，720 空间）——
详情页每行是【难度名在上、战斗在其下方 ≈40px、且更靠左】：

    妖狐超级 y=456 → 战斗 y=501    妖狐高级+ y=648 → 战斗 y=689
    妖狐高级 y=837 → 战斗 y=880    妖狐中级   y=1028 → 战斗 y=1068
    诅咒弧魔艾基尔中级 y=458 → 战斗 y=498（单难度行成员）

旧默认 ``pair="above"`` 与真机相反，导致：
  · 单难度行成员上方无战斗 → 永不命中 → 卡死（6 个实测成员）；
  · 多难度行成员配到上一行的战斗 → 静默打错难度。

本测试 = 真机帧守卫（复用 hooks_35）+ 合成帧单元断言 + 接线断言（离线、无设备）。
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

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


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


MULTI = h35.MULTI_ITEMS
SINGLE = h35.SINGLE_ITEMS


def test_default_is_real_geometry() -> None:
    print("\n== 1. 默认配对 = 真机几何（战斗在难度名下方） ==")
    check("DEFAULT_PAIR == 'below'（#35 真机几何）", si.DEFAULT_PAIR == "below",
          f"DEFAULT_PAIR={si.DEFAULT_PAIR}")
    check("同一行间距带上限锁死「同一行」(120)", si.BATTLE_ROW_MAX_GAP == 120,
          f"BATTLE_ROW_MAX_GAP={si.BATTLE_ROW_MAX_GAP}")


def test_real_frame_guard() -> None:
    print("\n== 2. 真机帧守卫（多行 + 单行）：命中框隶属声明的难度名 ==")
    msgs = h35._pair_failures()
    check("hooks_35 真机帧守卫全绿", msgs == [], "; ".join(msgs[:3]))


def test_multi_row_declared_difficulty() -> None:
    print("\n== 3. 多难度行：每个声明难度都配到「自己那一行」的战斗 ==")
    for declared, exp_box in h35.FRAMES[0]["expected"].items():
        rx = DIFF_REGEX[declared]
        box, detail = si.pick_target_battle_box(MULTI, difficulty=rx)
        own = detail.get("row_owner")
        check(f"{declared}: 命中本行战斗框 {exp_box}",
              box is not None and list(box) == list(exp_box), f"box={box}")
        check(f"{declared}: 命中框同一行难度名 = 声明的难度",
              bool(own) and re.search(rx, own[0] or ""), f"row_owner={own}")
    # 未声明的难度（初级）本帧没有 → 不臆测命中。
    box, detail = si.pick_target_battle_box(MULTI, difficulty=DIFF_REGEX["初级"])
    check("初级（本帧无该行）→ 不命中、不猜偏移", box is None, f"detail={detail}")


def test_single_row_no_longer_hangs() -> None:
    print("\n== 4. 单难度行成员：不再卡死（返回唯一的战斗框） ==")
    box, detail = si.pick_target_battle_box(SINGLE, difficulty=DIFF_REGEX["中级"])
    check("中级：单行成员命中其唯一战斗框 [86,498,33,20]",
          box is not None and list(box) == [86, 498, 33, 20], f"box={box} detail={detail}")
    check("中级：归属难度名仍是「诅咒弧魔艾基尔中级」",
          bool(detail.get("row_owner"))
          and re.search(DIFF_REGEX["中级"], detail["row_owner"][0] or ""),
          f"row_owner={detail.get('row_owner')}")
    check("战斗在难度名下方（dy≈36）", box is not None
          and 0 < _center(box)[1] - _center([203, 458, 252, 28])[1] <= si.BATTLE_ROW_MAX_GAP)


def test_legacy_above_is_wrong() -> None:
    print("\n== 5. 对照：旧「above」假设会卡死单行 / 打错多行（缺陷复现） ==")
    box, _d = si.pick_target_battle_box(SINGLE, difficulty=DIFF_REGEX["中级"], pair="above")
    check("旧 above：单行成员上方无战斗 → 不命中（卡死根因）", box is None, f"box={box}")
    box, _d = si.pick_target_battle_box(MULTI, difficulty=DIFF_REGEX["中级"], pair="above")
    check("旧 above：多行「中级」不会配到中级行自己的战斗",
          box is None or list(box) != [86, 1068, 35, 24], f"box={box}")


def test_topmost_unchanged() -> None:
    print("\n== 6. 无难度参数：取最上面的【战斗】（未通关行在最上面） ==")
    box, _d = si.pick_target_battle_box(MULTI, None)
    ys = [_center(b)[1] for _t, b in MULTI if re.search(r"^战斗$", _t)]
    check("返回最上面的战斗框", box is not None and abs(_center(box)[1] - min(ys)) < 1,
          f"box={box}")


def test_recognizer_and_override_wiring() -> None:
    print("\n== 7. 接线：识别器默认 below + 批量 override 编码真机几何 ==")
    rec = si.SpecialTargetFightRecognition()
    # 关键路径：**不带 pair**（= 图形界面 interface.json 的 difficulty-only 覆盖形态）。
    r = rec.analyze(_Ctx(SINGLE), _Argv(SINGLE, {"difficulty": DIFF_REGEX["中级"]}))
    check("识别器（difficulty-only，GUI 形态）命中单行战斗框",
          r.box is not None and list(r.box) == [86, 498, 33, 20], f"box={r.box}")

    from batch_plan import BatchItem  # noqa: PLC0415

    ov = si._special_override(BatchItem("猩红巨熊讨伐", "中级", 2))
    crp = (ov["SpecialFightTargetRow"]["recognition"]["param"]
           ["custom_recognition_param"])
    check("批量 override 声明难度 + pair=below（真机几何）",
          crp.get("difficulty") == "中级$" and crp.get("pair") == "below", f"crp={crp}")


def main() -> int:
    print("=" * 74)
    print("#35：详情页【难度名↔战斗按钮】真机几何配对（离线测试）")
    print("=" * 74)
    test_default_is_real_geometry()
    test_real_frame_guard()
    test_multi_row_declared_difficulty()
    test_single_row_no_longer_hangs()
    test_legacy_above_is_wrong()
    test_topmost_unchanged()
    test_recognizer_and_override_wiring()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：配对按真机几何、命中声明的难度、单行成员不再卡死 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
