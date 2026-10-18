# -*- coding: utf-8 -*-
"""#74：★★体力不足弹窗「星导石行」ROI 重新标定（真机A，2026-10-16 第三次 run）★★

现场事实（真机 run A，第三次；逐条见 ``tools/frames/stamina_insufficient_wuchong_a.ocr.txt``）
----------------------------------------------------------------------------------------------
体力不足弹窗整轮都在屏上，产品**从未处理**：五重枢纽空转 ``WuchongEntry ×121`` /
``WuchongWait ×120`` 共 432s、``state`` 恒 ``unknown``，最终由 ``[wuchong] 触发收工兜底：
未知画面累计 121 次`` 收工；账本只剩 ``wuchong/run/completed``（零战斗、零点击）。

根因 = 星导石行 ROI 差 ~30px（720 空间）：
  * ``scene/stamina.py:STONE_ROW_ROI = (180, 900, 420, 80)``（y 900..980，取自**旧线**帧，
    那里星导石行在 y≈934）；
  * 本线真机A 弹窗里「星导石 × 50」实测 ``box=[209, 873, 160, 32]``（行跨 y 873..905、
    中心 y≈889）→ **跨在旧 ROI 上边界之外**；
  * MaaFramework 先按 ROI 裁剪再 OCR → 该行被裁掉 → ``PubStaminaStoneText`` miss →
    ``And[PubStaminaInsufficientText, PubStaminaStoneText]`` miss → ``PubStaminaUseStone`` 永不点
    → 体力永不恢复 → 上述空转收工。
证据帧：``tools/frames/stamina_insufficient_wuchong_a.png``（同屏亦见 ``…/wc73/frames/00306_stamina.png``）。

守卫（本文件；prove-red 见文末）
-------------------------------
1. ``stamina-stone-row-roi-calibrated`` —— ★承重★：``scene.stamina.STONE_ROW_ROI`` 必须
   **完整包含**真机A 帧标定的星导石行框 ``[209,873,160,32]``（含其上下边），且与
   ``common.json`` 的 ``PubStaminaStoneText.roi`` **相等**（相等这一段**复用**既有
   ``hooks_stamina.node_failures``，不抄第二份）；同时 ``common.json`` 侧也必须包含该框；
   并断言本次事故的旧值 ``(180,900,420,80)`` **不**包含它（证明本次标定是承重的、旧值即那次事故）。
   ★这条守卫正是缺陷探针★：修复前（旧 ROI）它会红。

★诚实边界★
----------
真机 leg（在真机上制造体力不足、观察真的点了星导石行 → 二次确认 → 体力 +100）**未在本机运行**
（无设备授权）—— 本文件只做**离线**断言；另由 ``tools/verify_stamina_frames.py`` 用**真实
MaaFramework + 真 OCR** 回放本仓真机帧（已把该帧纳入默认语料）。

prove-red（``python tools\\contract_hooks\\hooks_74_stamina.py``）：把 ROI 倒回旧值 (180,900,420,80)
（常量 + common.json 同步、以及仅常量不同步两种坏法），要求守卫变红。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
HOOKS_DIR = Path(__file__).resolve().parent

#: ★只 append 到 sys.path 末尾★：prove-red 用 PYTHONPATH 抢先塞坏副本时副本仍优先命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

from contract_hooks import hooks_stamina  # noqa: E402

#: 真机A（2026-10-16）体力不足弹窗里「星导石 × 50」那一行的 OCR 框（720 空间）。
#: 来源：``tools/frames/stamina_insufficient_wuchong_a.png``（逐条 OCR 见同名 ``.ocr.txt``）。
REAL_STONE_ROW_BOX_A = [209, 873, 160, 32]
#: 真机标定帧（入库随仓）—— 缺失即守卫失去证据。
REAL_FRAME_A = "tools/frames/stamina_insufficient_wuchong_a.png"
#: 本次事故的旧 ROI（必须**不**包含真机行框 —— 若它包含，则本次标定不再承重 = 证据脱节）。
OLD_ROI = (180, 900, 420, 80)


def _contains(roi, box) -> bool:
    """``box``（x,y,w,h）是否**完整**落在 ``roi``（x,y,w,h）内（含边界）。"""
    if not roi or not box:
        return False
    rx, ry, rw, rh = roi
    x, y, w, h = box
    return rx <= x and ry <= y and (x + w) <= (rx + rw) and (y + h) <= (ry + rh)


def roi_calibration_failures(common=None) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    common = hooks_stamina.load_common() if common is None else common

    # (a) 真机标定证据帧在场。
    if not (REPO_ROOT / REAL_FRAME_A).is_file():
        msgs.append(f"真机标定帧未入库：{REAL_FRAME_A}（守卫失去真机证据）")

    # (b) 共享 ROI 常量 == common.json 的 PubStaminaStoneText.roi（★复用既有相等守卫，不抄第二份★）。
    msgs.extend(hooks_stamina.node_failures(common))

    roi = tuple(S.STONE_ROW_ROI)
    conf_roi = tuple(
        ((common.get(S.NODE_STONE) or {}).get("recognition") or {}).get("param", {}).get("roi") or []
    )

    # (c) ★承重★：ROI 必须完整包含真机A 标定的星导石行框。
    if not _contains(roi, REAL_STONE_ROW_BOX_A):
        msgs.append(
            f"STONE_ROW_ROI={list(roi)} 未完整包含真机A 星导石行框 {REAL_STONE_ROW_BOX_A}"
            " —— 行会被 ROI 裁剪、PubStaminaStoneText 永不命中（2026-10-16 空转收工那次的根因）"
        )
    # (d) 承重自证：旧值 (180,900,420,80) 必须**不**包含它（否则本标定没有意义 / 证据已脱节）。
    if _contains(OLD_ROI, REAL_STONE_ROW_BOX_A):
        msgs.append(
            f"旧 ROI {list(OLD_ROI)} 竟包含真机行框 {REAL_STONE_ROW_BOX_A} —— "
            "本次标定不再是承重的（守卫证据与缺陷不符）"
        )
    # (e) 配置侧同样必须包含（相等已由 (b) 钉住，这里对常见「只改常量 / 只改配置」的失效点直接留牙齿）。
    if not _contains(conf_roi, REAL_STONE_ROW_BOX_A):
        msgs.append(
            f"common.json PubStaminaStoneText.roi={list(conf_roi)} 未完整包含真机行框 "
            f"{REAL_STONE_ROW_BOX_A}"
        )
    return msgs


def probe_stamina_stone_row_roi_calibrated() -> bool:
    return roi_calibration_failures() == []


# ---------------------------------------------------------------------------
# prove-red
# ---------------------------------------------------------------------------
def _red(check, *args) -> tuple[bool, str]:
    msgs = check(*args)
    return bool(msgs), (msgs[0] if msgs else "（守卫没抓到！）")


def prove_red() -> bool:
    from scene import stamina as S  # noqa: PLC0415

    print("hooks_74_stamina prove-red：把星导石行 ROI 倒回旧值 (180,900,420,80)，要求守卫变红")

    green = probe_stamina_stone_row_roi_calibrated() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：真机标定 ROI（绿）")
    if not green:
        return False

    checks: list[bool] = []
    orig = S.STONE_ROW_ROI

    # (A) 常量 + common.json 同步倒回旧值 -> 相等仍成立，但「包含真机行框」必须红。
    broken = hooks_stamina.load_common()
    broken[S.NODE_STONE]["recognition"]["param"]["roi"] = list(OLD_ROI)
    try:
        S.STONE_ROW_ROI = OLD_ROI
        red_a, tail_a = _red(roi_calibration_failures, broken)
    finally:
        S.STONE_ROW_ROI = orig
    print(f"  [{'PASS' if red_a else 'FAIL'}] ROI（常量 + 配置）倒回旧值 -> "
          f"{'红' if red_a else '仍绿'}  {tail_a}")
    checks.append(red_a)

    # (B) 仅常量倒回旧值、配置保持新值 -> 相等检查必须红（防「改一处」静默分叉）。
    try:
        S.STONE_ROW_ROI = OLD_ROI
        red_b, tail_b = _red(roi_calibration_failures)
    finally:
        S.STONE_ROW_ROI = orig
    print(f"  [{'PASS' if red_b else 'FAIL'}] 仅常量倒回旧值（配置不同步）-> "
          f"{'红' if red_b else '仍绿'}  {tail_b}")
    checks.append(red_b)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "stamina-stone-row-roi-calibrated",
        "#74",
        "体力不足弹窗「星导石行」ROI 重新标定（真机A，2026-10-16）：STONE_ROW_ROI 必须完整包含真机标定框 "
        "[209,873,160,32]、且与 common.json 的 PubStaminaStoneText.roi 相等（复用 hooks_stamina 的相等守卫）；"
        "旧值 (180,900,420,80) 必须不含它（旧值即那次 121 次空转收工的根因）",
        probe_stamina_stone_row_roi_calibrated,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
