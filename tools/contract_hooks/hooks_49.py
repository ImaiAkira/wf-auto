# -*- coding: utf-8 -*-
"""#49：详情页【战斗】按钮容忍「单字框（丢尾字）」OCR 误差，但仍受几何 + 行主证明约束。

seam：``agent/side_impl.battle_text_match`` / ``pick_target_battle_box`` /
      ``SpecialTargetFightRecognition`` ↔ ``assets/resource/pipeline/special_dungeon.json``
      （``SpecialFightTargetRow``）。

背景（#49 真机缺陷，设备 16448，降临讨伐 Q1 全量扫描）
------------------------------------------------------
29 个成员里 25 个正常；**4 个**导航到**自己**的详情页（#42 身份 match）、却
**定位不到【战斗】按钮** → ``special_target_fight`` 找不到战斗框 → 详情页无法推进 →
空转到任务超时（**账本为空，无假记账**）。

真机帧**离线 OCR 实证**（同一 ``OcrTask``：``assets/resource/model/ocr/{det,rec}.onnx``）：
捕获帧逐条重跑 OCR（``live_harness.ocr``），【战斗】按钮读数与框：

    成员            帧                读数      框（720）
    赤之女王   s01  f_s01_015_085912  `战`      [91, 505, 14, 9]   ← 单字（宽 14 ≈ 半宽）
    方舟守护者 r4   f_r4_020_084303   `战`      [88, 501, 19, 17]  ← 单字
    青之女王   r5   f_r5_025_085119   `战`      [92, 506,  9,  7]  ← 单字
    伊尔梅塔雷 s06  f_s06_010_091503  `战头`    [88, 504, 27, 10]  ← 斗→头 单字替换（#43 通道）

25 个正常成员的同一按钮读作 `战斗`（框宽 ≈28~34）。差别只在**第二个字形「斗」**：
白字叠在 **Boss 立绘缩略图**（深色 / 高纹理）上，检测器把两字标签**塌缩成单字框**
（★是【文字检测】塌缩、不是识别读错 —— 框宽只剩半字宽）。#43 只覆盖「等长 + 单字替换」，
**不覆盖「丢字」** → s01/r4/r5 仍不命中（本票修复）。

守卫 ``battle-button-tolerates-truncated-glyph-ocr``
----------------------------------------------------
用**真机帧**做夹具（OCR 逐条内嵌；帧文件随仓 ``tools/frames/btn49_*.png``）：

1. ``battle_text_match`` 新增 ``approx_trunc``：文本是规范文本的**真前缀**且只少 ≤
   ``max_missing`` 个尾字（``战`` → approx_trunc）；等长单字替换照旧（``战三``/``战头``
   → approx）；``斗``（后缀，不是前缀）/``主城``/``挑战``/``推荐编成`` → 不认；
   ``max_missing=0`` → 关掉截断通道（``战`` 不认）。
2. **真机帧**：s01/r4/r5 声明 ``中级`` 命中的是**该行**战斗框（逐值相等）、
   ``battle_match == "approx_trunc"``、行主 = 该成员的中级难度名；s06 走 ``approx``。
3. **破坏复现（strict 回归）**：``battle_approx_max_missing=0``（= 退回「丢字不认」）
   → s01/r4/r5 三帧都不命中（这正是缺陷本身）。
4. **不点错行（#35 保证不变）**：截断候选超出同一行带（> max_gap）→ 不命中；截断候选
   在难度名右列（非左）→ 不命中；无声明难度（topmost）→ **截断通道不启用** → 不命中。
5. **工作帧对照（exact 不受影响）**：碧之女王双行帧，声明 ``高级`` / ``中级`` 仍各配
   自己那一行的战斗框、走 ``exact`` 通道。
6. **回归**：#35（``hooks_35._pair_failures``）与 #42（``hooks_42.probe_detail_identity_blocks_wrong_page``）
   仍全绿。

★诚实边界★：本通道**只救「有框但丢尾字」**；若 OCR **连单字框都没有**（完全无文本），
**绝不**凭空造坐标（战斗与【推荐编成】只差 ≈36px，凭空偏移会点到推荐编成，破坏性）
—— 那属于 OCR 模型下界，本守卫不假装修好。守卫用**内嵌真机 OCR**，不重跑 MAA OCR
（重跑是 ``verify_*`` 的活）；帧文件随仓供交叉核对。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_49.py``）：
把 ``BATTLE_APPROX_MAX_MISSING`` 退回 0（= 丢字不认）-> 守卫必须变红。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

HOOK_ID = "battle-button-tolerates-truncated-glyph-ocr"

# ---------------------------------------------------------------------------
# 真机帧夹具：逐条内嵌自「真机捕获帧 → live_harness.ocr → assets/resource/model/ocr」。
# 每条 = (text, [x, y, w, h])，与 OcrTask 的 box 同形（720 空间）。
# 帧文件随仓：tools/frames/btn49_*.png。
# ---------------------------------------------------------------------------
S01_ITEMS = [
    ("NEW", [14, 386, 60, 24]),
    ("返回", [30, 1246, 46, 26]),
    ("× 0", [42, 298, 48, 31]),
    ("× 0", [43, 334, 47, 27]),
    ("× 0", [45, 264, 45, 29]),
    ("推荐编成", [55, 530, 97, 30]),
    ("战", [91, 505, 14, 9]),            # ← 真机读数：单字（丢「斗」）
    ("999/101", [95, 20, 110, 28]),
    ("主城", [158, 1249, 41, 21]),
    ("降临讨伐", [202, 428, 91, 28]),
    ("赤之女王中级", [202, 457, 173, 32]),
    ("推荐属性", [207, 534, 89, 24]),
    ("赤之女王", [251, 214, 214, 60]),
    ("降临讨伐", [266, 177, 142, 44]),
    ("角色", [276, 1246, 45, 26]),
    ("BOSS BATTLE", [283, 277, 151, 17]),
    ("水", [311, 534, 52, 24]),
    ("体力", [362, 536, 46, 20]),
    ("商店", [397, 1245, 43, 27]),
    ("13", [450, 534, 26, 22]),
    ("3,140,535", [509, 18, 95, 24]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("首次报酬", [543, 433, 81, 23]),
    ("兑换道具", [614, 328, 83, 28]),
    ("菜单", [636, 1248, 45, 25]),
]

R4_ITEMS = [
    ("NEW", [14, 386, 53, 24]),
    ("返回", [31, 1246, 45, 26]),
    ("地狱级", [33, 69, 53, 20]),        # 主城横幅被误读，非详情页难度行
    ("×0", [42, 334, 48, 27]),
    ("×0", [43, 300, 45, 26]),
    ("×0", [45, 265, 45, 29]),
    ("推荐编成", [55, 532, 97, 28]),
    ("战", [88, 501, 19, 17]),           # ← 真机读数：单字
    ("999/101", [95, 20, 110, 28]),
    ("主城", [157, 1248, 44, 25]),
    ("降临讨伐", [201, 428, 92, 28]),
    ("方舟守护者", [202, 197, 312, 65]),
    ("方舟守护者中级", [202, 457, 200, 32]),
    ("推荐属性？？", [214, 534, 124, 24]),
    ("角色", [276, 1246, 45, 26]),
    ("领主战", [325, 268, 68, 29]),
    ("体力", [365, 533, 46, 25]),
    ("商店", [397, 1245, 45, 27]),
    ("13", [450, 534, 26, 22]),
    ("3,140,535", [509, 18, 95, 24]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("首次报酬", [543, 433, 81, 23]),
    ("兑换道具", [615, 329, 79, 24]),
    ("菜单", [636, 1248, 45, 25]),
]

R5_ITEMS = [
    ("NEW", [14, 386, 53, 24]),
    ("返回", [30, 1246, 46, 26]),
    ("× 0", [39, 296, 49, 33]),
    ("× 0", [41, 334, 49, 27]),
    ("× 0", [43, 264, 47, 29]),
    ("推荐编成", [55, 532, 97, 28]),
    ("战", [92, 506, 9, 7]),             # ← 真机读数：单字（框仅 9×7）
    ("999/101", [93, 20, 112, 28]),
    ("主城", [158, 1249, 41, 21]),
    ("降临讨伐", [201, 428, 92, 28]),
    ("青之女王中级", [202, 457, 173, 32]),
    ("推荐属性 雷体力", [209, 533, 202, 27]),
    ("青之女王", [254, 213, 211, 61]),
    ("角色", [276, 1246, 45, 26]),
    ("BOSS BATTLE", [284, 277, 150, 17]),
    ("降临讨伐", [291, 182, 137, 35]),
    ("商店", [397, 1245, 43, 27]),
    ("13", [450, 534, 26, 22]),
    ("03,140,535", [508, 18, 96, 24]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("首次报酬", [543, 433, 81, 23]),
    ("兑换道具", [614, 328, 83, 28]),
    ("菜单", [636, 1248, 45, 25]),
]

S06_ITEMS = [
    ("NEW", [14, 386, 54, 26]),
    ("返回", [30, 1246, 46, 26]),
    ("× 0", [38, 330, 53, 32]),
    ("× 0", [41, 300, 49, 26]),
    ("×0", [43, 266, 45, 26]),
    ("推荐编成", [55, 532, 97, 28]),
    ("战头", [88, 504, 27, 10]),         # ← 真机读数：斗→头 单字替换（#43 通道）
    ("1999/101", [115, 22, 88, 24]),
    ("降临讨伐", [148, 214, 100, 55]),
    ("主城", [158, 1249, 41, 21]),
    ("光芒荒龙", [186, 218, 318, 119]),
    ("降临讨伐", [203, 429, 89, 24]),
    ("伊尔梅塔雷中级", [205, 458, 196, 28]),
    ("推荐属性暗体力", [209, 533, 202, 27]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1245, 43, 27]),
    ("FLOODING LIGHT", [432, 334, 121, 14]),
    ("13", [450, 534, 26, 22]),
    ("D-DRAGON OF", [455, 324, 96, 9]),
    ("3,140,565", [509, 20, 95, 22]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("首次报酬", [543, 433, 81, 23]),
    ("兑换道具", [614, 328, 83, 28]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 工作帧对照（碧之女王双行，战斗读作 `战斗`=exact）：证明精确配对不受本票影响。
S02OK_ITEMS = [
    ("NEW", [14, 386, 52, 26]),
    ("COMPLETE!!", [17, 580, 121, 18]),
    ("返回", [30, 1246, 46, 26]),
    ("× 50", [39, 330, 64, 32]),
    ("× 10", [42, 297, 62, 33]),
    ("× 0", [45, 264, 45, 29]),
    ("推荐编成", [55, 532, 97, 28]),
    ("推荐编成", [55, 721, 97, 29]),
    ("战斗", [83, 692, 34, 16]),
    ("战斗", [88, 502, 28, 15]),
    ("999/101", [95, 20, 110, 28]),
    ("主城", [157, 1248, 44, 25]),
    ("碧之女王高级", [198, 453, 177, 36]),
    ("碧之女王中级", [199, 645, 178, 36]),
    ("降临讨伐", [201, 428, 92, 28]),
    ("降临讨伐", [201, 618, 92, 28]),
    ("推荐属性火体力", [207, 532, 204, 28]),
    ("推荐属性火", [210, 726, 144, 23]),
    ("碧之女王", [252, 214, 213, 62]),
    ("角色", [276, 1246, 45, 26]),
    ("BOSS BATTLE", [284, 276, 150, 18]),
    ("降临讨伐", [311, 186, 96, 28]),
    ("体力", [366, 722, 46, 27]),
    ("商店", [397, 1246, 43, 26]),
    ("13", [447, 724, 32, 25]),
    ("16", [450, 536, 26, 21]),
    ("03,140,535", [508, 18, 96, 24]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("首次报酬", [541, 429, 83, 27]),
    ("兑换道具", [614, 328, 83, 28]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 帧夹具：帧名 / 来源文件 / OCR 条目 / 声明难度 / 该行战斗框（实测）/ 归属 / 期望误差通道。
FRAMES = [
    {
        "name": "详情页·赤之女王讨伐（战斗读成单字 `战`）",
        "source": "tools/frames/btn49_s01_redqueen.png",
        "items": S01_ITEMS,
        "declared": "中级",
        "box": [91, 505, 14, 9],
        "row": "赤之女王中级",
        "match": "approx_trunc",
    },
    {
        "name": "详情页·方舟守护者讨伐（战斗读成单字 `战`）",
        "source": "tools/frames/btn49_r4_arkguardian.png",
        "items": R4_ITEMS,
        "declared": "中级",
        "box": [88, 501, 19, 17],
        "row": "方舟守护者中级",
        "match": "approx_trunc",
    },
    {
        "name": "详情页·青之女王讨伐（战斗读成单字 `战`）",
        "source": "tools/frames/btn49_r5_bluequeen.png",
        "items": R5_ITEMS,
        "declared": "中级",
        "box": [92, 506, 9, 7],
        "row": "青之女王中级",
        "match": "approx_trunc",
    },
    {
        "name": "详情页·伊尔梅塔雷讨伐（战斗读成 `战头`）",
        "source": "tools/frames/btn49_s06_irmetare.png",
        "items": S06_ITEMS,
        "declared": "中级",
        "box": [88, 504, 27, 10],
        "row": "伊尔梅塔雷中级",
        "match": "approx",
    },
]

#: 工作帧（exact 通道对照）：声明难度 → 该行战斗框（实测）。
S02OK_EXPECTED = {
    "高级": ([88, 502, 28, 15], "碧之女王高级"),
    "中级": ([83, 692, 34, 16], "碧之女王中级"),
}


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


def _import_side_impl(agent_dir: Path | None = None):
    """导入 ``agent/side_impl``（可指定副本目录，供 prove-red）。"""
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _failures(si=None, agent_dir: Path | None = None) -> list[str]:
    """#49 全部离线断言；返回失败信息列表（空 = 绿）。"""
    si = si or _import_side_impl(agent_dir)
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    from batch_plan import DIFF_REGEX  # noqa: PLC0415

    msgs: list[str] = []

    # (0) 帧文件在场（守卫的证据）。
    for frame in FRAMES:
        if not (REPO_ROOT / frame["source"]).is_file():
            msgs.append(f"真机帧缺失：{frame['source']}（守卫失去证据）")

    # (1) battle_text_match：精确 / 单字替换 / 丢尾字 三通道的边界。
    for text, want in (
        ("战斗", "exact"),
        ("战三", "approx"),          # 单字替换（#43）
        ("战头", "approx"),          # 单字替换（真机 s06）
        ("战", "approx_trunc"),      # 丢尾字（真机 s01/r4/r5）★#49★
        ("斗", None),                # 后缀不是前缀 → 不认
        ("主城", None),
        ("挑战", None),
        ("推荐编成", None),
        ("", None),
    ):
        got = si.battle_text_match(text)
        if got != want:
            msgs.append(f"battle_text_match({text!r}) = {got!r}，应为 {want!r}")

    # 关掉截断通道（max_missing=0）→ 单字 `战` 不认（= 缺陷复现通道）。
    if si.battle_text_match("战", max_missing=0) is not None:
        msgs.append("关掉截断通道后 `战` 仍被认（无法证明缺陷来自『丢字不认』）")

    # (2) 真机帧：声明难度命中**该行**战斗框 + 走期望的误差通道 + 行主 = 声明的难度。
    for frame in FRAMES:
        rx = DIFF_REGEX[frame["declared"]]
        box, det = si.pick_target_battle_box(frame["items"], difficulty=rx)
        tag = f"真机帧「{frame['name']}」声明「{frame['declared']}」"
        if box is None or list(box) != list(frame["box"]):
            msgs.append(f"{tag}：命中 {box} != 该行实测 {frame['box']}（丢字未被容忍 → 卡死）"
                        f" detail={det.get('reason')}")
            continue
        if det.get("battle_match") != frame["match"]:
            msgs.append(f"{tag}：battle_match={det.get('battle_match')!r}，应为 {frame['match']!r}")
        owner = det.get("row_owner")
        owner_text = owner[0] if owner else None
        if owner_text != frame["row"]:
            msgs.append(f"{tag}：命中框行主 {owner_text!r} != 声明的难度行 {frame['row']!r}")

    # (3) ★缺陷复现（strict 回归）★：关掉截断通道（= 丢字不认）→ s01/r4/r5 三帧都不命中。
    for frame in FRAMES:
        if frame["match"] != "approx_trunc":
            continue
        box0, _d0 = si.pick_target_battle_box(
            frame["items"], difficulty=DIFF_REGEX[frame["declared"]],
            battle_approx_max_missing=0,
        )
        if box0 is not None:
            msgs.append(f"关掉截断通道后「{frame['name']}」仍命中 {box0} "
                        f"—— 无法证明缺陷来自『丢字不认』")

    # (4) ★不点错行（#35 保证不变）★
    #   (4a) 截断候选超出同一行带（> max_gap）→ 不命中。
    far = [
        ("诅咒弧魔艾基尔中级", [203, 458, 252, 28]),
        ("战", [88, 900, 20, 12]),   # dy=442 > 120
    ]
    b_far, _d = si.pick_target_battle_box(far, difficulty=DIFF_REGEX["中级"])
    if b_far is not None:
        msgs.append(f"截断候选超出同一行带仍命中 {b_far}（截断也不得跨行）")
    #   (4b) 截断候选在难度名右列（非左）→ 不命中。
    right = [
        ("诅咒弧魔艾基尔中级", [100, 458, 252, 28]),
        ("战", [360, 500, 20, 12]),  # bcx 370 > ncx 226 → 右侧，不是按钮列
    ]
    b_right, _d = si.pick_target_battle_box(right, difficulty=DIFF_REGEX["中级"])
    if b_right is not None:
        msgs.append(f"截断候选在难度名右列仍命中 {b_right}（不是按钮列）")
    #   (4c) 无声明难度（topmost）→ 截断通道**不启用** → 单字 `战` 不命中。
    b_top, _d = si.pick_target_battle_box(S01_ITEMS, difficulty=None)
    if b_top is not None:
        msgs.append(f"topmost（无声明难度）下仍凭单字 `战` 命中 {b_top}（截断通道越权）")

    # (5) exact 不受影响（工作帧对照）：碧之女王双行，各难度配自己那一行、走 exact。
    for declared, (exp_box, exp_row) in S02OK_EXPECTED.items():
        rx = DIFF_REGEX[declared]
        box, det = si.pick_target_battle_box(S02OK_ITEMS, difficulty=rx)
        if box is None or list(box) != list(exp_box):
            msgs.append(f"工作帧声明「{declared}」：命中 {box} != 本行 {exp_box}（精确配对被破坏）")
            continue
        if det.get("battle_match") != "exact":
            msgs.append(f"工作帧声明「{declared}」：battle_match={det.get('battle_match')!r}，应为 'exact'")
        owner = det.get("row_owner")
        if (owner[0] if owner else None) != exp_row:
            msgs.append(f"工作帧声明「{declared}」：行主 {owner} != {exp_row!r}")

    # (6) 端到端接线：识别器（difficulty + member，GUI/批量形态）在单字帧上仍命中。
    rec = si.SpecialTargetFightRecognition()
    r = rec.analyze(
        _Ctx(S01_ITEMS),
        _Argv(S01_ITEMS, {"difficulty": DIFF_REGEX["中级"], "member": "赤之女王讨伐"}),
    )
    if r.box is None or list(r.box) != [91, 505, 14, 9]:
        msgs.append(f"SpecialTargetFightRecognition 在单字帧上未命中 [91,505,14,9]：box={r.box}")

    # (7) 回归：#35（真机帧配对）与 #42（详情页身份闸）仍全绿。
    try:
        from contract_hooks import hooks_35 as h35  # noqa: PLC0415
        from contract_hooks import hooks_42 as h42  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"导入 #35/#42 守卫失败：{exc!r}")
        return msgs
    h35_msgs = h35._pair_failures(agent_dir=agent_dir)
    if h35_msgs:
        msgs.append(f"#35 守卫被本票破坏：{h35_msgs[:2]}")
    if h42.probe_detail_identity_blocks_wrong_page() is not True:
        msgs.append("#42 身份闸（拒错页）不再绿 —— 本票不得削弱身份校验")

    return msgs


def probe_battle_button_tolerates_truncated_glyph_ocr() -> bool:
    """#49：详情页【战斗】按钮容忍单字框（丢尾字）OCR 误差，仍受几何 + 行主证明约束。"""
    return _failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_49.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_trunc(agent_dir: Path) -> None:
    """破坏：把「丢尾字」通道退回不认（= 旧的等长匹配）。"""
    _sub(
        agent_dir / "side_impl.py",
        "BATTLE_APPROX_MAX_MISSING = 1",
        "BATTLE_APPROX_MAX_MISSING = 0",
    )


def _probe_in(agent_copy: Path):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import hooks_49\n"
        f"print('PROBE_RESULT', repr(hooks_49._failures(agent_dir={str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral49_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def prove_red() -> bool:
    """真实绿；把「丢尾字」通道退回不认 -> 守卫变红。"""
    print(
        "hooks_49 prove-red：把 BATTLE_APPROX_MAX_MISSING 退回 0（= 丢字不认），"
        "要求 battle-button-tolerates-truncated-glyph-ocr 变红"
    )
    green = probe_battle_button_tolerates_truncated_glyph_ocr() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：单字帧仍命中声明难度行（绿）")
    if not green:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook49_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_trunc(tmp / "agent")
        red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 退回『丢字不认』-> 探针变红（缺陷复现）")
    ok = green and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#49",
        "详情页【战斗】按钮容忍『单字框（丢尾字）』OCR 误差（真机 `战`），仍受几何 + 行主证明约束，"
        "绝不点到相邻难度行 / 无声明难度的路径（#35/#42 保证不变）；真机帧 + 破坏复现",
        probe_battle_button_tolerates_truncated_glyph_ocr,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
