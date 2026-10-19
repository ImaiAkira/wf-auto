# -*- coding: utf-8 -*-
"""#105 动作级测试：`TeamSwitchBattleAction` 的闭环（假 OCR + 假点击，不连设备）。

验的不是「坐标算得对」（hooks_105 已验），而是**一次完整切换会做什么**：
  读 SET 2 → 算一步 → 点在 SET 1 的圆点上 → 再读 SET 1 → 收敛退出；
以及**拒动**：读不到编队时不动（不点队伍点条、不盲滑）。

★#124 收尾改了这半★：目标队 ≠ 当前队**不再拒动**，改走 ``switch_party``（横向滑动 + 三重校验，
守卫在 ``hooks_105.team-battle-party-switch`` / ``hooks_124.party-action-wiring``）。旧「拒动」
保留下来的是「**读不到编队就不动**」—— 本文件现在钉的就是这半。
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tools"), str(REPO / "agent")]

import team_impl as ti  # noqa: E402

FAILS: list[str] = []


class _Argv:
    def __init__(self, param: dict):
        self.custom_action_param = json.dumps(param)


def _frame(set_no: int, party: int = 5, power: str = "8,876"):
    return [
        (f"SET {set_no}", [90, 458, 60, 20]),
        (f"{party}  Party {'ABCDEF'[party - 1]}", [35, 520, 130, 24]),
        ("自动续战", [20, 1060, 80, 24]),
        (f"战力 {power}", [500, 516, 130, 24]),
    ]


def _run(param: dict, frames: list, clicks: list) -> str:
    """把 frames 依次喂给动作；每次点击后切到下一帧（模拟画面推进）。"""
    seq = list(frames)
    state = {"i": 0}

    def _fake_ocr_all(context, image, entry="OcrTask"):  # noqa: ANN001
        idx = min(state["i"], len(seq) - 1)
        return list(seq[idx])

    def _fake_click(context, cx, cy):  # noqa: ANN001
        clicks.append((cx, cy))
        state["i"] = min(state["i"] + 1, len(seq) - 1)
        return True

    def _fake_grab(context):  # noqa: ANN001
        return object()

    saved = (ti.ocr_all, ti._click_box, ti._grab)
    ti.ocr_all, ti._click_box, ti._grab = _fake_ocr_all, _fake_click, _fake_grab
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ti.TeamSwitchBattleAction().run(None, _Argv(param))
        return buf.getvalue()
    finally:
        ti.ocr_all, ti._click_box, ti._grab = saved


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("== #105 TeamSwitchBattleAction 闭环 ==")

    # ① SET 2 → SET 1：必须点一次，落点是 SET 1 的圆点 x=113
    clicks: list = []
    out = _run({"set": 1, "party": 5}, [_frame(2), _frame(1)], clicks)
    check("SET 2 → SET 1 点了一次", len(clicks) == 1, f"clicks={clicks}")
    if clicks:
        check("落点是 SET 1 的圆点（x≈113, y=466）", clicks[0] == (113, 466), f"实际 {clicks[0]}")
    check("收敛后打印 ✓ 收尾", "✓ 收尾" in out, out[-120:])

    # ② 已在目标：一次都不点
    clicks = []
    out = _run({"set": 1, "party": 5}, [_frame(1)], clicks)
    check("已在 SET 1 时零点击（不白点）", clicks == [], f"clicks={clicks}")

    # ③ 目标队 ≠ 当前队、但**读不到编队**：必须拒动（不点队伍点条、也不盲滑）。
    #    ★#124 收尾★ 旧的「队不符就拒动」已被接线取代；保留的是「读不到就不动」这半。
    clicks = []
    no_party = [
        ("SET 1", [90, 458, 60, 20]),
        ("自动续战", [20, 1060, 80, 24]),
        ("战力 8,876", [500, 516, 130, 24]),
    ]
    out = _run({"set": 1, "party": 1}, [no_party], clicks)
    check("读不到编队时零点击（绝不盲点队伍点条）", clicks == [], f"clicks={clicks}")
    check("读不到编队时打印拒动原因", "拒动" in out, out[-160:])

    # ④ 不是 A 类页（B 类帧含「切换」）：必须停手，不点任何东西
    clicks = []
    b_frame = [("SET 1", [30, 14, 48, 19]), ("切换", [633, 685, 40, 24]), ("战力 13,116", [560, 74, 140, 24])]
    out = _run({"set": 4, "party": 5}, [b_frame], clicks)
    check("B 类页上停手（零点击）", clicks == [], f"clicks={clicks}")
    check("B 类页上说明原因", "不是战前编队页" in out, out[-160:])

    # ⑤ 目标越界：不动
    clicks = []
    out = _run({"set": 99, "party": 5}, [_frame(1)], clicks)
    check("越界目标零点击", clicks == [], f"clicks={clicks}")

    if FAILS:
        print(f"\nFAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("\nALL GREEN —— 动作闭环与拒动语义成立")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
