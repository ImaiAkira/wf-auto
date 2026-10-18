# -*- coding: utf-8 -*-
"""#43：详情页【战斗】按钮对「单字 OCR 误差」有韧性，但绝不点到相邻难度行的战斗。

seam：``agent/side_impl.battle_text_match`` / ``pick_target_battle_box`` /
      ``SpecialTargetFightRecognition`` ↔ ``assets/resource/pipeline/special_dungeon.json``
      （``SpecialFightTargetRow``）。

背景（#43 真机缺陷，设备 16448）
------------------------------
成员 ``无猾机兵`` 导航**成功**（停在它自己的详情页），却 **6.5 分钟卡死、未开打**：
实时 OCR 在那一张详情页上把【战斗】按钮**稳定读成 `战三`**
（``debug\\maafw.bak.*-04.37.29.7.log`` 里 **85/85** 条 OcrTask 都是 `战三`），
而严格 ``^战斗$`` 永不命中 → 详情页无法推进 → ``SpecialWait ⇄ SpecialEntry`` 循环到超时。

★关键事实★：**同一帧存成 jpg 后离线 OCR 又能正确读出 `战斗`**（``decode37.txt`` /
``c1_ocr.txt``，见本守卫夹具）→ 差异来自 MAA 原始帧的重采样，不是这一帧特例 ——
所以必须让匹配对「单字字形读错」有韧性，而不是等下一帧碰运气。

守卫 ``battle-button-tolerates-single-glyph-ocr-error``
-------------------------------------------------------
用**真机帧**做夹具（OCR 逐条内嵌；帧文件随仓 ``tools/frames/lord_detail_naught_robot_c1.jpg``）：

1. ``battle_text_match`` 只认「等长、且只有一个字形不同」：`战三` → approx，
   `战斗` → exact，`主城` / `推荐编成` / `挑战`（两字都不同）→ 不认；
2. 真机 ``战三`` 帧：声明 ``中级`` 仍命中的是**该行**的战斗框 ``[88,501,29,16]``，
   且 ``battle_match == "approx"``、行主 = ``机工神兵菲诺梅那中级``（声明的难度）；
3. **破坏复现（strict 回归）**：同一帧把近似通道关掉（``battle_approx_max_subst=0``，
   = 退回严格 ``^战斗$``）→ 不命中（这正是缺陷本身）；
4. 同帧的**离线读数**（`战斗`）同样命中同一框 → 证明差异只来自重采样；
5. **不点错行（#35 保证不变）**：多难度行帧里，把 ``中级`` 行的战斗读成 ``战三``，
   四个难度仍各配到**自己那一行**的战斗框（中级 → ``[86,1068,35,24]``）；
6. 近似候选超出同一行带（> ``max_gap``）→ 不命中（近似也绝不跨行）。

★诚实边界★：守卫用内嵌 OCR（真机逐字），不重跑 MAA OCR（重跑是 verify_* 的活）；
帧文件本身随仓，供交叉核对。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_43.py``）：
把 ``BATTLE_APPROX_MAX_SUBST`` 退回 0（= 严格 ``^战斗$``）-> 守卫必须变红。
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

HOOK_ID = "battle-button-tolerates-single-glyph-ocr-error"

FRAME_SRC = "tools/frames/lord_detail_naught_robot_c1.jpg"

# ---------------------------------------------------------------------------
# 真机夹具：C1 详情页（成员 无猾机兵，单难度行「机工神兵菲诺梅那中级」）。
# 每条 = (text, [x, y, w, h])，与 OcrTask 的 box 同形（720 空间）。
#
# `战三`  = **真机 MAA 原始帧**的读数（maafw.bak 日志 85/85）；
# `战斗`  = **同一帧存成 jpg 后离线**的读数（c1_ocr.txt / decode37.txt）。
# 其余条目两处一致，故差异**只**在这一个字形 —— 这正是「重采样导致单字读错」。
# ---------------------------------------------------------------------------
C1_ITEMS_CORRUPTED = [
    ("999/101", [109, 17, 97, 31]),
    ("3,140,055", [509, 18, 95, 24]),
    ("降临讨伐", [207, 128, 142, 28]),
    ("无猾机兵", [160, 156, 374, 89]),
    ("STEAM-ROBOT OF NAUGHT", [232, 238, 274, 19]),
    ("×1,080", [43, 262, 109, 35]),
    ("×3,961", [42, 300, 87, 28]),
    ("兑换道具", [614, 328, 83, 28]),
    ("×10,739", [41, 332, 101, 32]),
    ("NEW", [11, 384, 57, 29]),
    ("降临讨伐", [202, 428, 91, 28]),
    ("首次报酬", [542, 433, 82, 23]),
    ("机工神兵菲诺梅那中级", [203, 458, 280, 28]),
    ("战三", [88, 501, 29, 16]),          # ← 真机 MAA 原始帧读数（单字误差）
    ("×15", [587, 508, 48, 28]),
    ("推荐编成", [56, 530, 94, 30]),
    ("推荐属性？？？", [213, 533, 145, 27]),
    ("体力", [361, 533, 51, 25]),
    ("10", [447, 534, 28, 22]),
    ("角色", [275, 1244, 47, 29]),
    ("商店", [395, 1245, 45, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1246, 44, 27]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 同一帧的**离线**读数：只把 `战三` 换回 `战斗`，其余逐条相同。
C1_ITEMS_OFFLINE = [
    (("战斗" if (t == "战三" and list(b) == [88, 501, 29, 16]) else t), list(b))
    for t, b in C1_ITEMS_CORRUPTED
]

#: 声明 ``中级`` 时该帧唯一战斗框的实测值（probe_node_c1.txt）。
C1_BATTLE_BOX = [88, 501, 29, 16]
#: 该帧唯一难度行名（实测）。
C1_ROW_NAME = "机工神兵菲诺梅那中级"


def _c1_multi_corrupted():
    """多难度行帧（#35 的妖狐讨伐），只把 ``中级`` 行的战斗读成 ``战三``。

    用于证明：近似匹配**不会**把 ``中级`` 声明的战斗配到别行，也不影响别行。
    """
    # 直接当脚本跑时 tools/ 不在 sys.path；补上以便复用 #35 的多难度行夹具
    # （同一事实不两写：多行帧的 OCR 条目只维护在 hooks_35 一份）。
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    from contract_hooks import hooks_35 as h35  # noqa: PLC0415

    out = []
    for t, b in h35.MULTI_ITEMS:
        if t == "战斗" and list(b) == [86, 1068, 35, 24]:
            t = "战三"
        out.append((t, list(b)))
    return out


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
    """#43 全部离线断言；返回失败信息列表（空 = 绿）。"""
    si = si or _import_side_impl(agent_dir)
    from batch_plan import DIFF_REGEX  # noqa: PLC0415

    msgs: list[str] = []

    # (0) 帧文件在场（守卫的证据）。
    if not (REPO_ROOT / FRAME_SRC).is_file():
        msgs.append(f"真机帧缺失：{FRAME_SRC}（守卫失去证据）")

    # (1) battle_text_match 只认「等长 + 单字不同」。
    for text, want in (
        ("战斗", "exact"),
        ("战三", "approx"),
        ("主城", None),
        ("推荐编成", None),
        ("挑战", None),      # 两个字形都不同 → 不是单字误差
        ("领队", None),
    ):
        got = si.battle_text_match(text)
        if got != want:
            msgs.append(f"battle_text_match({text!r}) = {got!r}，应为 {want!r}")

    # (2) 真机 `战三` 帧：声明「中级」仍命中该行战斗框，且走的是 approx 通道。
    box, detail = si.pick_target_battle_box(
        C1_ITEMS_CORRUPTED, difficulty=DIFF_REGEX["中级"]
    )
    if box is None or list(box) != C1_BATTLE_BOX:
        msgs.append(
            f"真机 `战三` 帧：声明「中级」命中战斗框 {box} != 该行实测 {C1_BATTLE_BOX}"
            f"（单字 OCR 误差未被容忍 → 详情页卡死）detail={detail}"
        )
    if detail.get("battle_match") != "approx":
        msgs.append(
            f"真机 `战三` 帧：battle_match={detail.get('battle_match')!r}，应为 'approx'"
            f"（未走单字误差通道）"
        )
    owner = detail.get("row_owner")
    owner_text = owner[0] if owner else None
    if owner_text is None or not re.search(DIFF_REGEX["中级"], owner_text):
        msgs.append(
            f"真机 `战三` 帧：命中框行主 {owner_text!r} 不是声明的「中级」难度"
            f"（归属无法证明）"
        )

    # (3) ★缺陷复现（strict 回归）★：关掉近似通道（= 退回严格 ^战斗$）→ 不命中。
    box0, _d0 = si.pick_target_battle_box(
        C1_ITEMS_CORRUPTED, difficulty=DIFF_REGEX["中级"], battle_approx_max_subst=0
    )
    if box0 is not None:
        msgs.append(
            f"关掉近似通道后仍命中 {box0} —— 无法证明缺陷来自严格 `^战斗$`"
        )

    # (4) 同帧离线读数（`战斗`）同样命中同一框 → 差异只来自重采样。
    box_off, det_off = si.pick_target_battle_box(
        C1_ITEMS_OFFLINE, difficulty=DIFF_REGEX["中级"]
    )
    if box_off is None or list(box_off) != C1_BATTLE_BOX:
        msgs.append(f"同帧离线读数（战斗）未命中同一框 {C1_BATTLE_BOX}：box={box_off}")
    if det_off.get("battle_match") != "exact":
        msgs.append(
            f"同帧离线读数应为 exact 通道，实际 {det_off.get('battle_match')!r}"
        )

    # (5) ★不点错行（#35 保证不变）★：中级行战斗读成 `战三`，各行仍配自己那一行。
    multi = _c1_multi_corrupted()
    expected = {
        "超级": [88, 501, 31, 16],
        "高级+": [87, 689, 32, 20],
        "高级": [87, 880, 32, 20],
        "中级": [86, 1068, 35, 24],
    }
    for declared, exp_box in expected.items():
        rx = DIFF_REGEX[declared]
        b, d = si.pick_target_battle_box(multi, difficulty=rx)
        if b is None or list(b) != list(exp_box):
            msgs.append(
                f"多行帧·声明「{declared}」（中级行战斗读成 `战三`）：命中 {b} != 本行 {exp_box}"
                f"（近似匹配窜到了别行）"
            )
            continue
        own = d.get("row_owner")
        own_text = own[0] if own else None
        if own_text is None or not re.search(rx, own_text):
            msgs.append(
                f"多行帧·声明「{declared}」：命中框行主 {own_text!r} 不是声明的难度"
            )

    # (6) 近似候选超出同一行带（> max_gap）→ 不命中（绝不跨行）。
    far = [
        ("机工神兵菲诺梅那中级", [203, 458, 280, 28]),
        ("战三", [88, 700, 29, 16]),   # dy=242 > 120
    ]
    b_far, _d = si.pick_target_battle_box(far, difficulty=DIFF_REGEX["中级"])
    if b_far is not None:
        msgs.append(f"近似候选超出同一行带仍命中 {b_far}（近似也不得跨行）")

    # (7) 端到端接线：识别器（difficulty-only，GUI 形态）在 `战三` 帧上仍命中。
    rec = si.SpecialTargetFightRecognition()
    r = rec.analyze(_Ctx(C1_ITEMS_CORRUPTED), _Argv(C1_ITEMS_CORRUPTED, {"difficulty": DIFF_REGEX["中级"]}))
    if r.box is None or list(r.box) != C1_BATTLE_BOX:
        msgs.append(
            f"SpecialTargetFightRecognition 在 `战三` 帧上未命中 {C1_BATTLE_BOX}：box={r.box}"
        )

    return msgs


def probe_battle_button_tolerates_single_glyph_ocr_error() -> bool:
    """#43：真机 `战三` 单字误差仍命中声明难度行的战斗框；近似不越行；#35 保证不变。"""
    return _failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_43.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_strict(agent_dir: Path) -> None:
    """破坏：把「单字误差」通道退回严格（= 旧的 `^战斗$`）。"""
    _sub(
        agent_dir / "side_impl.py",
        "BATTLE_APPROX_MAX_SUBST = 1",
        "BATTLE_APPROX_MAX_SUBST = 0",
    )


def _probe_in(agent_copy: Path):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针。返回 True/False/None。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import hooks_43\n"
        f"print('PROBE_RESULT', repr(hooks_43._failures(agent_dir={str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral43_"))
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
    """真实绿；把单字误差通道退回严格 `^战斗$` -> 守卫变红。"""
    print(
        "hooks_43 prove-red：把 BATTLE_APPROX_MAX_SUBST 退回 0（= 严格 `^战斗$`），"
        "要求 battle-button-tolerates-single-glyph-ocr-error 变红"
    )
    green = probe_battle_button_tolerates_single_glyph_ocr_error() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：真机 `战三` 仍命中声明难度行（绿）")
    if not green:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook43_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_strict(tmp / "agent")
        red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 退回严格 `^战斗$` -> 探针变红（缺陷复现）")
    ok = green and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#43",
        "详情页【战斗】按钮容忍单字 OCR 误差（真机 `战三`），但近似仍受几何 + 行主证明约束，"
        "绝不点到相邻难度行的战斗（#35 保证不变）；真机帧 + strict 破坏复现",
        probe_battle_button_tolerates_single_glyph_ocr_error,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
