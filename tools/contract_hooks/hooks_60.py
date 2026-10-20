# -*- coding: utf-8 -*-
"""#60：迷宫「临境域 深渊之兽·极」卡在未处理的道具确认框 —— 数据声明地处理它。

seam
----
* ``assets/resource/pipeline/farm.json``：``FarmItemConfirm``（与门 = 弹框标题 ∧【是】按钮，
  ``box_index`` 指到【是】框 -> ``Click target:true`` 点【是】框**中心**）+ 两个与门叶
  ``FarmItemConfirmPrompt`` / ``FarmItemConfirmYes``；``FarmDispatch.next`` 里的顺序
  （必须排在 ``FarmFight`` / ``FarmScroll`` / ``FarmScrollUp`` **之前**）。
* ``tools/live_harness.py``：``MAZE_ITEM_PROMPT``（归位侧同一判据，与 farm.json 逐字一致）。

诊断（真机 16448，证据见本文件内嵌的 ``POPUP_FRAME_ITEMS``）
------------------------------------------------------------
迷宫行【战斗】点下去弹一张模态确认框（帧 OCR 逐条内嵌自
``.../verify_runs/mazeA_beng_ji_99_end.ocr.txt``）::

    是否使用阿尔戈罗盘              [232,436,253,32]
    挑战临境域深渊之兽·极？          [194,473,316,32]
    使用的道具将在通关后被扣除       [240,690,235,19]
    否 [178,806,37,36] / 是 [504,805,36,36]

farm 链此前没有任何节点处理它 → 卡在 ``FarmScroll×15 → FarmScrollUp×7 → FarmWait``，
战斗从未开始（#60 现象）。处置（#60 运维裁决 verbatim：
「阿尔戈罗盘的可以点确认，无所谓道具消耗」）= **点【是】**，允许消耗道具。

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``maze-item-confirm-data-declared`` —— 处理是**数据声明**：节点在场、是
   ``And[title, yes]``、``box_index`` 指向【是】、动作是 ``Click target:true``（零死偏移）。
2. ``maze-item-confirm-before-fight-and-scroll`` —— 顺序：``FarmItemConfirm`` 在
   ``FarmFight`` / ``FarmScroll`` / ``FarmScrollUp`` **之前**（弹框帧先被接住）。
3. ``maze-item-confirm-real-frame`` —— **真机帧回放**：两版标题（``阿尔戈罗盘`` / ``阿戈尔罗盘``）
   都命中，且点到的点是【是】框**中心** (522,823)；纯迷宫页（无弹框）**不**命中。
4. ``maze-item-confirm-both-landings-agree`` —— pipeline 侧与归位侧（live_harness）的判据**逐字一致**。

★prove-red★（``python tools\\contract_hooks\\hooks_60.py``）四处破坏，要求守卫各自变红：
  * 把 ``FarmItemConfirm`` 从链里挪到 ``FarmFight`` 之后 -> 顺序守卫红（又会空滚）；
  * 把动作换成死坐标 ``target:[522,823]`` -> 数据声明守卫红（不许死偏移）；
  * 把 ``box_index`` 改成 0（点标题框）-> 真机帧守卫红（没点到【是】框中心）；
  * 把标题判据收窄成只认 ``阿尔戈罗盘`` -> 真机帧守卫红（``阿戈尔罗盘`` 变体不再命中）。

诚实边界：真机帧（临时目录）随运行消失；这里内嵌**逐条 OCR**（与 hooks_44/hooks_38 同做法），
不重跑 MAA OCR（那是 verify_* 的活）。
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★：prove-red 若用 PYTHONPATH 抢先塞副本仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

FARM_JSON = REPO_ROOT / "assets" / "resource" / "pipeline" / "farm.json"
NODE = "FarmItemConfirm"
PROMPT_NODE = "FarmItemConfirmPrompt"
YES_NODE = "FarmItemConfirmYes"

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌；源：mazeA_beng_ji_99_end.ocr.txt）
# ---------------------------------------------------------------------------
#: 弹框帧：标题读成「阿尔戈罗盘」，【是】@[504,805,36,36]。
POPUP_FRAME_ITEMS: list[tuple[str, list[int]]] = [
    ("返回", [30, 1246, 45, 26]),
    ("摇电的迷宫前环感", [64, 101, 568, 217]),
    ("否", [178, 806, 37, 36]),
    ("挑战临境域深渊之兽·极？", [194, 473, 316, 32]),
    ("深层域3【暗】Lv70", [203, 1028, 257, 32]),
    ("推荐属性光 体力", [209, 1105, 209, 27]),
    ("是否使用阿尔戈罗盘", [232, 436, 253, 32]),
    ("使用的道具将在通关后被扣除", [240, 690, 235, 19]),
    ("角色", [276, 1246, 45, 26]),
    ("×10", [289, 613, 47, 28]),
    ("体力", [366, 913, 45, 25]),
    ("商店", [398, 1246, 42, 26]),
    ("20", [406, 1105, 71, 24]),
    ("x", [455, 624, 17, 14]),
    ("是", [504, 805, 36, 36]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("SS", [545, 1024, 83, 76]),
    ("兑换道具", [618, 329, 74, 23]),
    ("菜单", [636, 1246, 45, 27]),
]
#: 同一弹框的另一版 OCR（#60：设备把道具读成「阿戈尔罗盘」）。
POPUP_FRAME_ITEMS_VARIANT = [
    ("是否使用阿戈尔罗盘", [230, 436, 256, 32]),
    ("挑战临境域深渊之兽·极？", [194, 473, 316, 32]),
    ("否", [178, 806, 37, 36]),
    ("是", [504, 805, 36, 36]),
]
#: 反例：纯迷宫页（同一屏但**没有**弹框）——道具确认框节点绝不能在这里命中。
MAZE_PAGE_ITEMS: list[tuple[str, list[int]]] = [
    ("摇电的迷宫前环感", [64, 101, 568, 217]),
    ("深层域3【暗】Lv70", [203, 1028, 257, 32]),
    ("推荐属性光 体力", [209, 1105, 209, 27]),
    ("返回", [30, 1246, 45, 26]),
    ("角色", [276, 1246, 45, 26]),
    ("商店", [398, 1246, 42, 26]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
]

EXPECTED_YES_CENTER = (522, 823)          # [504,805,36,36] 中心
EXPECTED_VARIANT_YES_CENTER = (522, 823)  # 变体帧【是】同一框


# ---------------------------------------------------------------------------
# JSONC 读取 / 小工具
# ---------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    state = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i:i + 2] == "//":
                while i < len(text) and text[i] != "\n":
                    i += 1
            elif text[i:i + 2] == "/*":
                i += 2
                while i + 1 < len(text) and text[i:i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch)
            state = 1
            i += 1
    return "".join(out)


def load_farm(path: Path | None = None) -> dict:
    """读 farm.json（JSONC）为 dict。"""
    p = Path(path) if path else FARM_JSON
    return json.loads(_strip_jsonc(p.read_text(encoding="utf-8")))


def _center(box) -> tuple[int, int]:
    x, y, w, h = box
    return int(x + w / 2), int(y + h / 2)


def _ocr_first(items, patterns):
    regs = [re.compile(p) for p in patterns]
    for text, box in items:
        if any(r.search(text or "") for r in regs):
            return box
    return None


def and_eval(farm: dict, items) -> tuple[bool, list | None, list]:
    """模拟 MAA ``And(all_of=..., box_index=...)``：返回 (命中?, 输出框, 各叶框)。"""
    param = farm[NODE]["recognition"]["param"]
    leaves = list(param.get("all_of") or [])
    bi = int(param.get("box_index", 0))
    boxes = []
    for name in leaves:
        rec = farm.get(name) or {}
        expected = ((rec.get("recognition") or {}).get("param") or {}).get("expected") or []
        box = _ocr_first(items, expected)
        if box is None:
            return False, None, boxes
        boxes.append(box)
    return True, boxes[bi], boxes


# ---------------------------------------------------------------------------
# 守卫 1：数据声明（不是硬编码坐标）
# ---------------------------------------------------------------------------
def pipeline_failures(farm: dict) -> list[str]:
    """结构守卫：节点形状 + 与门 + 零偏移中心点击。返回失败信息（空 = 绿）。"""
    msgs: list[str] = []

    node = farm.get(NODE)
    if not isinstance(node, dict):
        msgs.append(f"farm.json 缺少 {NODE} 节点（道具确认框未被数据声明地处理）")
        return msgs

    rec = node.get("recognition") or {}
    param = rec.get("param") or {}
    if rec.get("type") != "And":
        msgs.append(f"{NODE} 识别应为 And（弹框标题 ∧【是】按钮），实际 {rec.get('type')!r}")
    if list(param.get("all_of") or []) != [PROMPT_NODE, YES_NODE]:
        msgs.append(f"{NODE}.all_of 应为 [{PROMPT_NODE!r}, {YES_NODE!r}]，实际 {param.get('all_of')!r}")
    if int(param.get("box_index", 0)) != 1:
        msgs.append(
            f"{NODE}.box_index 应为 1（输出【是】按钮的框），实际 {param.get('box_index')!r}"
            " —— 否则会点到弹框标题而不是【是】"
        )

    for leaf in (PROMPT_NODE, YES_NODE):
        if not isinstance(farm.get(leaf), dict):
            msgs.append(f"farm.json 缺少与门叶 {leaf}（守卫与实现脱节）")

    prompt = (((farm.get(PROMPT_NODE) or {}).get("recognition") or {}).get("param") or {})
    yes = (((farm.get(YES_NODE) or {}).get("recognition") or {}).get("param") or {})
    prompt_exp = prompt.get("expected") or []
    yes_exp = yes.get("expected") or []
    if len(prompt_exp) != 1 or not re.search(prompt_exp[0], "是否使用阿尔戈罗盘"):
        msgs.append(f"{PROMPT_NODE}.expected={prompt_exp!r} 认不出真机弹框标题「是否使用阿尔戈罗盘」")
    if yes_exp != [r"^是$"]:
        msgs.append(f"{YES_NODE}.expected 应为 [r'^是$']（两端锚定单字「是」），实际 {yes_exp!r}")

    act = node.get("action") or {}
    aparam = act.get("param") or {}
    if act.get("type") != "Click" or aparam.get("target") is not True:
        msgs.append(
            f"{NODE} 动作应为 Click target:true（点识别框=【是】框中心、零偏移），实际 "
            f"{act.get('type')!r}/{aparam.get('target')!r}"
        )
    if isinstance(aparam.get("target_offset"), (list, tuple)) and any(
        float(v or 0) != 0.0 for v in aparam["target_offset"]
    ):
        msgs.append(f"{NODE} 用了死偏移 target_offset={aparam.get('target_offset')!r}（要求零偏移）")

    if node.get("next") != ["SpecialEntry"]:
        msgs.append(f"{NODE}.next 应为 ['SpecialEntry']，实际 {node.get('next')!r}")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 2：顺序（在选行/开打/滚动之前）
# ---------------------------------------------------------------------------
def order_failures(farm: dict) -> list[str]:
    """``FarmItemConfirm`` 必须排在 FarmFight / FarmScroll / FarmScrollUp 之前。"""
    chain = list((farm.get("FarmDispatch") or {}).get("next") or [])
    msgs: list[str] = []
    if NODE not in chain:
        return [f"FarmDispatch.next 缺少 {NODE}（道具确认框没有被链处理）"]
    i = chain.index(NODE)
    for later in ("FarmFight", "FarmScroll", "FarmScrollUp"):
        if later in chain and chain.index(later) < i:
            msgs.append(
                f"{NODE} 必须排在 {later} 之前（否则弹框帧会被 {later} 抢先命中、空滚）"
                f"：实际链={chain}"
            )
    return msgs


# ---------------------------------------------------------------------------
# 守卫 3：真机帧回放
# ---------------------------------------------------------------------------
def frame_failures(farm: dict) -> list[str]:
    """真机帧回放：两版标题都命中且点到【是】框中心；纯迷宫页不命中。"""
    msgs: list[str] = []

    ok, box, _boxes = and_eval(farm, POPUP_FRAME_ITEMS)
    if not ok or box is None:
        msgs.append(f"真机弹框帧（阿尔戈罗盘）未命中 {NODE}（#60 回归）")
    elif _center(box) != EXPECTED_YES_CENTER:
        msgs.append(
            f"真机弹框帧点到 {_center(box)}，应为【是】框中心 {EXPECTED_YES_CENTER}"
            f"（box={box}）"
        )

    ok_v, box_v, _bv = and_eval(farm, POPUP_FRAME_ITEMS_VARIANT)
    if not ok_v or box_v is None:
        msgs.append("真机弹框变体帧（阿戈尔罗盘）未命中 —— OCR 变体没被容忍（#60 回归）")
    elif _center(box_v) != EXPECTED_VARIANT_YES_CENTER:
        msgs.append(
            f"变体帧点到 {_center(box_v)}，应为【是】框中心 {EXPECTED_VARIANT_YES_CENTER}"
        )

    ok_n, _box_n, _bn = and_eval(farm, MAZE_PAGE_ITEMS)
    if ok_n:
        msgs.append("纯迷宫页（无弹框）误命中道具确认框 —— 判据过宽")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 4：pipeline 侧与归位侧判据逐字一致
# ---------------------------------------------------------------------------
def both_landings_failures(farm: dict) -> list[str]:
    """farm.json 的标题判据必须与 live_harness.MAZE_ITEM_PROMPT 逐字一致。"""
    import live_harness as ca  # noqa: PLC0415

    prompt = (((farm.get(PROMPT_NODE) or {}).get("recognition") or {}).get("param") or {})
    exp = (prompt.get("expected") or [None])[0]
    msgs: list[str] = []
    if exp != ca.MAZE_ITEM_PROMPT:
        msgs.append(
            f"farm.json::{PROMPT_NODE}.expected[0]={exp!r} 与 live_harness.MAZE_ITEM_PROMPT="
            f"{ca.MAZE_ITEM_PROMPT!r} 不一致（同一事实两处落地分叉）"
        )
    yes = (((farm.get(YES_NODE) or {}).get("recognition") or {}).get("param") or {})
    if (yes.get("expected") or [None])[0] != ca.MAZE_ITEM_YES:
        msgs.append(f"farm.json::FarmItemConfirmYes 与 live_harness.MAZE_ITEM_YES 不一致")
    return msgs


def all_failures(farm: dict | None = None) -> list[str]:
    f = load_farm() if farm is None else farm
    return pipeline_failures(f) + order_failures(f) + frame_failures(f) + both_landings_failures(f)


# ---------------------------------------------------------------------------
# 探针
# ---------------------------------------------------------------------------
def probe_item_confirm_data_declared() -> bool:
    return pipeline_failures(load_farm()) == []


def probe_item_confirm_before_fight_and_scroll() -> bool:
    return order_failures(load_farm()) == []


def probe_item_confirm_real_frame() -> bool:
    return frame_failures(load_farm()) == []


def probe_item_confirm_both_landings_agree() -> bool:
    return both_landings_failures(load_farm()) == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_60.py`）
# ---------------------------------------------------------------------------
def _red(farm: dict, mutate, check) -> tuple[bool, str]:
    broken = copy.deepcopy(farm)
    mutate(broken)
    msgs = check(broken)
    return bool(msgs), (msgs[0] if msgs else "（守卫没抓到！）")


def prove_red() -> bool:
    print("hooks_60 prove-red：四处破坏，要求守卫各自变红")
    farm = load_farm()
    green = all_failures(farm) == []
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：数据声明 + 顺序 + 真机帧 + 两处一致（绿）")
    if not green:
        return False

    # (a) 把 FarmItemConfirm 从链里挪到 FarmFight 之后 -> 顺序守卫红。
    def _move(b):
        chain = b["FarmDispatch"]["next"]
        chain.remove(NODE)
        chain.insert(chain.index("FarmFight") + 1, NODE)

    red_a, tail_a = _red(farm, _move, order_failures)

    # (b) 动作换成死坐标 -> 数据声明守卫红。
    red_b, tail_b = _red(
        farm,
        lambda b: b[NODE]["action"]["param"].__setitem__("target", [522, 823]),
        pipeline_failures,
    )

    # (c) box_index 改成 0（点标题框）-> 真机帧守卫红。
    red_c, tail_c = _red(
        farm, lambda b: b[NODE]["recognition"]["param"].__setitem__("box_index", 0), frame_failures
    )

    # (d) 标题判据收窄成只认「阿尔戈罗盘」-> 变体帧不再命中 -> 真机帧守卫红。
    red_d, tail_d = _red(
        farm,
        lambda b: b[PROMPT_NODE]["recognition"]["param"].__setitem__(
            "expected", ["是否使用阿尔戈罗盘"]
        ),
        frame_failures,
    )

    for label, red, tail in (
        ("挪到 FarmFight 之后", red_a, tail_a),
        ("动作改成死坐标", red_b, tail_b),
        ("box_index 改成 0", red_c, tail_c),
        ("标题判据丢掉「阿戈尔」变体", red_d, tail_d),
    ):
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}  {tail}")

    ok = green and red_a and red_b and red_c and red_d
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "maze-item-confirm-data-declared",
        "#60",
        "迷宫道具确认框是数据声明（And[标题,【是】], box_index=1, Click target:true 零偏移）",
        probe_item_confirm_data_declared,
    ),
    (
        "maze-item-confirm-before-fight-and-scroll",
        "#60",
        "FarmItemConfirm 排在 FarmFight / FarmScroll / FarmScrollUp 之前（弹框帧先被接住）",
        probe_item_confirm_before_fight_and_scroll,
    ),
    (
        "maze-item-confirm-real-frame",
        "#60",
        "真机帧回放：阿尔戈罗盘 / 阿戈尔罗盘两版都命中，点到【是】框中心 (522,823)；纯迷宫页不命中",
        probe_item_confirm_real_frame,
    ),
    (
        "maze-item-confirm-both-landings-agree",
        "#60",
        "farm.json 与 live_harness 的弹框判据逐字一致（同一事实两处落地不分叉）",
        probe_item_confirm_both_landings_agree,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
