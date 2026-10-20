# -*- coding: utf-8 -*-
"""#67：领主战页面上的「讨伐完成」奖励弹窗未被处理 —— 数据声明地处理它（公共节点）。

seam
----
* ``assets/resource/pipeline/common.json``：三个公共节点 —— 标题叶 ``PubRewardDoneText``
  （OCR 子串「讨伐完成」）、按钮叶 ``PubRewardDoneBtn``（OCR ``^关闭$``）、动作节点
  ``PubRewardDoneClose``（与门 ``And[标题, 按钮]`` + ``box_index=1`` -> ``Click target:true``
  点【关闭】框**中心**）。放在公共节点所在地 common.json（与其它 ``Pub*`` 同处一地）。
* ``assets/resource/pipeline/special_dungeon.json``：``SpecialEntry.next`` 以
  ``[JumpBack]PubRewardDoneClose`` 引用（领主战枢纽可达），且排在 ``SpecialStallRecover``
  之前（静止弹窗帧不得被卡死看门狗当成「卡死」而重开游戏）。
* ``assets/resource/pipeline/raid.json``：``RaidPopupClose`` 换成引用同一份公共与门的
  **薄包装**（动作/延时/next 原样）—— 同一事实只有一份定义（绝不复制第二份 expected）。

诊断（真机 127.0.0.1:16448，#33 part-B；证据见本文件内嵌的 ``RAID_DONE_FRAME``）
----------------------------------------------------------------------------------------
领主战清单【开跑前】就停在一张待处理的奖励弹窗上，整屏 OCR 只有：
    讨伐完成 [84,436,552,110]   /   关闭 [326,957,67,39]
清掉它之后，同一屏 OCR =【战阵之宴 RAID 页】—— 即这是**战阵之宴的奖励弹窗**落在领主战页面上。
此前 special_dungeon.json 没有任何节点认它 → 领主战清单在第一帧就被它挡住、无进展地空滚到超时
（战阵之宴链 raid.json 只认 ``^关闭$``，而领主战链根本没有对应节点）。运维只能手动清掉。

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``raid-done-popup-data-declared`` —— 处理是**数据声明**：三节点在场、动作节点是与门、
   ``box_index`` 指向【关闭】、``Click target:true``（零死偏移 / 无固定点）。
2. ``raid-done-popup-reachable-from-hub`` —— 领主战枢纽可达：``SpecialEntry.next`` 含
   ``[JumpBack]PubRewardDoneClose`` 且排在 ``SpecialStallRecover`` 之前；被引用的公共节点确有定义。
3. ``raid-done-popup-real-frame`` —— **真机帧回放**：真实帧（讨伐完成 + 关闭）命中，而且点到的
   点是【关闭】框**中心** (359,976)；领主战列表页 / 只有标题 / 只有按钮 都**不**命中（与门是承重的）。
4. ``raid-done-popup-shared-with-raid`` —— 与战阵之宴链共用一份判据：``raid.json::RaidPopupClose``
   是与门薄包装（``all_of=[Text,Btn]``, ``box_index=1``），raid.json 里**不再**出现第二份 ``^关闭$``。
5. ``raid-done-popup-declared`` —— ``special_dungeon.json`` 的 #67 声明注释在场；五条承重短语零丢失（纯编辑）。

★prove-red★（``python tools\\contract_hooks\\hooks_raid_done_popup.py``）五处破坏，要求守卫各自变红：
  * 从 ``SpecialEntry.next`` 摘掉 ``[JumpBack]PubRewardDoneClose``（= 讨伐完成又变「无人处理」）-> 守卫 2 红；
  * 动作换成固定死点 ``target:[359,976]`` -> 守卫 1 红（不许死偏移）；
  * ``box_index`` 改成 0（点标题框）-> 守卫 3 红（没点到【关闭】框中心）；
  * 去掉标题叶（只认按钮）-> 守卫 3 红（「只有按钮」的反例帧误命中 = 与门不再承重）；
  * 把 raid 的薄包装退回字面 ``^关闭$`` -> 守卫 4 红（同一事实两处落地 = 第二份拷贝）。

诚实边界
--------
真机帧（临时目录）随运行消失；这里内嵌**逐条 OCR**（与 hooks_44/hooks_38/hooks_60 同做法），
不重跑 MAA OCR。内嵌帧只含**本票缺陷的那两个识别框**（``讨伐完成`` + ``关闭``）—— 整屏 OCR 的
其余条目未随运行留存，故不做「整屏逐条」断言。战阵之宴链的行为收窄（``RaidPopupClose`` 现要求
标题 + 按钮）**无真机帧**直接回放：只有「同一张弹窗」这一条证据支撑（见诊断），如实标注。
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
PIPE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
COMMON_JSON = PIPE_DIR / "common.json"
RAID_JSON = PIPE_DIR / "raid.json"
SD_JSON = PIPE_DIR / "special_dungeon.json"

# ★只 append 到 sys.path 末尾★：prove-red 若用 PYTHONPATH 抢先塞副本仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

NODE = "PubRewardDoneClose"
TEXT_NODE = "PubRewardDoneText"
BTN_NODE = "PubRewardDoneBtn"
HUB = "SpecialEntry"
HUB_REF = f"[JumpBack]{NODE}"

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌；源：真机 127.0.0.1:16448，#33 part-B 运行）
# ---------------------------------------------------------------------------
#: 缺陷帧：领主战页面上待处理的奖励弹窗 = 讨伐完成 + 【关闭】。
RAID_DONE_FRAME: list[tuple[str, list[int]]] = [
    ("讨伐完成", [84, 436, 552, 110]),
    ("关闭", [326, 957, 67, 39]),
]
#: 【关闭】框 [326,957,67,39] 的中心。
EXPECTED_CLOSE_CENTER = (359, 976)
EXPECTED_CLOSE_BOX = [326, 957, 67, 39]

#: 反例 1：领主战列表页（同类页面但**没有**弹窗）—— 绝不能命中。
LORD_LIST_ITEMS: list[tuple[str, list[int]]] = [
    ("更新列表", [656, 342, 80, 30]),
    ("领主战", [180, 405, 60, 25]),
    ("降临讨伐", [540, 404, 90, 25]),
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
]
#: 反例 2：只有标题、没有【关闭】按钮 —— 与门缺一叶，不得命中。
TITLE_ONLY_ITEMS: list[tuple[str, list[int]]] = [("讨伐完成", [84, 436, 552, 110])]
#: 反例 3：只有【关闭】、没有标题 —— 不得命中（与门是承重的，不是「见关闭就点」）。
BTN_ONLY_ITEMS: list[tuple[str, list[int]]] = [("关闭", [326, 957, 67, 39])]

#: #12 的承重注释硬规则：纯编辑，绝不丢这些短语。
BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


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
            elif text[i : i + 2] == "//":
                while i < len(text) and text[i] != "\n":
                    i += 1
            elif text[i : i + 2] == "/*":
                i += 2
                while i + 1 < len(text) and text[i : i + 2] != "*/":
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


def load_json(path: Path) -> dict:
    """读一个 pipeline JSONC 文件为 dict。"""
    return json.loads(_strip_jsonc(Path(path).read_text(encoding="utf-8")))


def load_common() -> dict:
    return load_json(COMMON_JSON)


def load_raid() -> dict:
    return load_json(RAID_JSON)


def load_sd() -> dict:
    return load_json(SD_JSON)


def _text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8") if Path(path).is_file() else ""


def _center(box) -> tuple[int, int]:
    x, y, w, h = box
    return int(x + w / 2), int(y + h / 2)


def _ocr_first(items, patterns):
    regs = [re.compile(p) for p in patterns]
    for text, box in items:
        if any(r.search(text or "") for r in regs):
            return box
    return None


def and_eval(common: dict, items) -> tuple[bool, list | None, list]:
    """模拟 MAA ``And(all_of=..., box_index=...)``：返回 (命中?, 输出框, 各叶框)。"""
    node = common.get(NODE) or {}
    param = ((node.get("recognition") or {}).get("param")) or {}
    leaves = list(param.get("all_of") or [])
    bi = int(param.get("box_index", 0))
    boxes: list = []
    for name in leaves:
        rec = common.get(name) or {}
        expected = ((rec.get("recognition") or {}).get("param") or {}).get("expected") or []
        box = _ocr_first(items, expected)
        if box is None:
            return False, None, boxes
        boxes.append(box)
    if not boxes:
        return False, None, boxes
    idx = bi if 0 <= bi < len(boxes) else 0
    return True, boxes[idx], boxes


# ---------------------------------------------------------------------------
# 守卫 1：数据声明（不是硬编码坐标 / 死偏移）
# ---------------------------------------------------------------------------
def pipeline_failures(common: dict) -> list[str]:
    msgs: list[str] = []

    node = common.get(NODE)
    if not isinstance(node, dict):
        msgs.append(f"common.json 缺少 {NODE} 节点（讨伐完成弹窗未被数据声明地处理）")
        return msgs

    rec = node.get("recognition") or {}
    param = rec.get("param") or {}
    if rec.get("type") != "And":
        msgs.append(f"{NODE} 识别应为 And（弹窗标题 ∧【关闭】按钮），实际 {rec.get('type')!r}")
    if list(param.get("all_of") or []) != [TEXT_NODE, BTN_NODE]:
        msgs.append(f"{NODE}.all_of 应为 [{TEXT_NODE!r}, {BTN_NODE!r}]，实际 {param.get('all_of')!r}")
    if int(param.get("box_index", 0)) != 1:
        msgs.append(
            f"{NODE}.box_index 应为 1（输出【关闭】按钮的框），实际 {param.get('box_index')!r}"
            " —— 否则会点到弹窗标题而不是【关闭】"
        )

    for leaf in (TEXT_NODE, BTN_NODE):
        if not isinstance(common.get(leaf), dict):
            msgs.append(f"common.json 缺少与门叶 {leaf}（守卫与实现脱节）")

    text = (((common.get(TEXT_NODE) or {}).get("recognition") or {}).get("param") or {})
    btn = (((common.get(BTN_NODE) or {}).get("recognition") or {}).get("param") or {})
    text_exp = text.get("expected") or []
    btn_exp = btn.get("expected") or []
    if len(text_exp) != 1 or not re.search(text_exp[0], "讨伐完成"):
        msgs.append(f"{TEXT_NODE}.expected={text_exp!r} 认不出真机弹窗标题「讨伐完成」")
    if btn_exp != [r"^关闭$"]:
        msgs.append(f"{BTN_NODE}.expected 应为 [r'^关闭$']（两端锚定单字），实际 {btn_exp!r}")

    act = node.get("action") or {}
    aparam = act.get("param") or {}
    if act.get("type") != "Click" or aparam.get("target") is not True:
        msgs.append(
            f"{NODE} 动作应为 Click target:true（点识别框=【关闭】框中心、零偏移），实际 "
            f"{act.get('type')!r}/{aparam.get('target')!r}"
        )
    if isinstance(aparam.get("target_offset"), (list, tuple)) and any(
        float(v or 0) != 0.0 for v in aparam["target_offset"]
    ):
        msgs.append(f"{NODE} 用了死偏移 target_offset={aparam.get('target_offset')!r}（要求零偏移）")

    if node.get("next") != []:
        msgs.append(f"{NODE}.next 应为 []（叶子型：点掉后弹窗消失、自然不再命中），实际 {node.get('next')!r}")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 2：领主战枢纽可达（且先于卡死看门狗）
# ---------------------------------------------------------------------------
def reachability_failures(sd: dict, common: dict | None = None) -> list[str]:
    msgs: list[str] = []
    entry = (sd.get(HUB) or {}).get("next") or []
    if HUB_REF not in entry:
        return [f"special_dungeon.json::{HUB}.next 缺少 {HUB_REF}（讨伐完成弹窗又变『无人处理』）"]

    if "SpecialStallRecover" in entry and entry.index(HUB_REF) > entry.index("SpecialStallRecover"):
        msgs.append(
            f"{HUB_REF} 必须排在 SpecialStallRecover 之前（否则静止的弹窗帧会被卡死看门狗"
            f"当成『卡死』而重开游戏；实际链={entry}）"
        )

    if common is not None and not isinstance(common.get(NODE), dict):
        msgs.append(f"{HUB_REF} 引用的公共节点 {NODE!r} 在 common.json 里没有定义（悬空引用）")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 3：真机帧回放
# ---------------------------------------------------------------------------
def frame_failures(common: dict) -> list[str]:
    msgs: list[str] = []

    ok, box, _boxes = and_eval(common, RAID_DONE_FRAME)
    if not ok or box is None:
        msgs.append(f"真机弹窗帧（讨伐完成 + 关闭）未命中 {NODE}（#67 回归）")
    else:
        if list(box) != EXPECTED_CLOSE_BOX:
            msgs.append(f"真机帧输出框应为【关闭】框 {EXPECTED_CLOSE_BOX}，实际 {list(box)}")
        if _center(box) != EXPECTED_CLOSE_CENTER:
            msgs.append(
                f"真机弹窗帧点到 {_center(box)}，应为【关闭】框中心 {EXPECTED_CLOSE_CENTER}"
                f"（box={box}）—— 读后动必须点在按钮自己的框中心"
            )

    for label, items in (
        ("领主战列表页（无弹窗）", LORD_LIST_ITEMS),
        ("只有标题、没有【关闭】", TITLE_ONLY_ITEMS),
        ("只有【关闭】、没有标题", BTN_ONLY_ITEMS),
    ):
        hit, _b, _bs = and_eval(common, items)
        if hit:
            msgs.append(f"{label} 误命中讨伐完成弹窗 —— 与门/判据过宽（应只认完整弹窗）")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 4：与战阵之宴链共用一份判据（不留第二份拷贝）
# ---------------------------------------------------------------------------
def _nodes_with_expected(data: dict, pattern: str) -> list[str]:
    """顶层节点里，recognition.expected（OCR）含给定串的节点名（只解析 JSON，不看注释）。"""
    out: list[str] = []
    for name, node in (data or {}).items():
        if not isinstance(node, dict):
            continue
        exp = (((node.get("recognition") or {}).get("param") or {}).get("expected")) or []
        if isinstance(exp, list) and pattern in exp:
            out.append(name)
    return out


def shared_failures(raid: dict, common: dict | None = None) -> list[str]:
    msgs: list[str] = []
    node = raid.get("RaidPopupClose")
    if not isinstance(node, dict):
        return ["raid.json 缺少 RaidPopupClose（战阵之宴链的弹窗处理器）"]

    param = ((node.get("recognition") or {}).get("param")) or {}
    if (node.get("recognition") or {}).get("type") != "And":
        msgs.append("RaidPopupClose 识别应为与门薄包装（引用公共叶），实际不是 And")
    if list(param.get("all_of") or []) != [TEXT_NODE, BTN_NODE]:
        msgs.append(
            f"RaidPopupClose.all_of 应引用公共叶 [{TEXT_NODE!r}, {BTN_NODE!r}]（共用一份判据），"
            f"实际 {param.get('all_of')!r}"
        )
    if int(param.get("box_index", 0)) != 1:
        msgs.append(f"RaidPopupClose.box_index 应为 1（点【关闭】框），实际 {param.get('box_index')!r}")

    # 「同一事实只有一份」：字面 ^关闭$ 只能出现在公共叶 PubRewardDoneBtn 这一处。
    if _nodes_with_expected(raid, "^关闭$"):
        msgs.append(
            "raid.json 里仍有字面 '^关闭$' 的 OCR 叶（同一事实的第二份拷贝 —— 应只引用公共叶）"
        )
    if common is not None:
        holders = _nodes_with_expected(common, "^关闭$")
        if holders != [BTN_NODE]:
            msgs.append(
                f"common.json 里 '^关闭$' 应只由 {BTN_NODE!r} 持有（唯一真源），实际持有者={holders}"
            )
    if node.get("next") != [HUB]:
        msgs.append(f"RaidPopupClose.next 应为 [{HUB!r}]（战阵之宴链原样），实际 {node.get('next')!r}")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 5：纯编辑 —— 五条承重短语仍在 + #67 声明注释在场
# ---------------------------------------------------------------------------
def declaration_failures(sd_text: str | None = None) -> list[str]:
    text = _text(SD_JSON) if sd_text is None else sd_text
    msgs: list[str] = []
    for phrase in BEARING_PHRASES:
        if text.count(phrase) < 1:
            msgs.append(f"承重短语「{phrase}」丢失（#12 硬规则：纯编辑不得丢注释）")
    if "#67" not in text:
        msgs.append("special_dungeon.json 缺少 #67 声明注释（讨伐完成弹窗的接线未被记录）")
    return msgs


def all_failures(*, common=None, sd=None, raid=None) -> list[str]:
    common = load_common() if common is None else common
    sd = load_sd() if sd is None else sd
    raid = load_raid() if raid is None else raid
    return (
        pipeline_failures(common)
        + reachability_failures(sd, common)
        + frame_failures(common)
        + shared_failures(raid, common)
        + declaration_failures()
    )


# ---------------------------------------------------------------------------
# 探针
# ---------------------------------------------------------------------------
def probe_raid_done_popup_data_declared() -> bool:
    return pipeline_failures(load_common()) == []


def probe_raid_done_popup_reachable_from_hub() -> bool:
    return reachability_failures(load_sd(), load_common()) == []


def probe_raid_done_popup_real_frame() -> bool:
    return frame_failures(load_common()) == []


def probe_raid_done_popup_shared_with_raid() -> bool:
    return shared_failures(load_raid(), load_common()) == []


def probe_raid_done_popup_declared() -> bool:
    return declaration_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_raid_done_popup.py`）
# ---------------------------------------------------------------------------
def _red(check, *args) -> tuple[bool, str]:
    msgs = check(*args)
    return bool(msgs), (msgs[0] if msgs else "（守卫没抓到！）")


def prove_red() -> bool:
    print("hooks_raid_done_popup prove-red：五处破坏，要求守卫各自变红")
    common = load_common()
    sd = load_sd()
    raid = load_raid()
    green = (
        probe_raid_done_popup_data_declared() is True
        and probe_raid_done_popup_reachable_from_hub() is True
        and probe_raid_done_popup_real_frame() is True
        and probe_raid_done_popup_shared_with_raid() is True
        and probe_raid_done_popup_declared() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：数据声明 + 枢纽可达 + 真机帧 + 共用判据 + 声明（绿）")
    if not green:
        return False

    # (a) 从枢纽摘掉引用 -> 讨伐完成又变「无人处理」。
    broken_sd = copy.deepcopy(sd)
    broken_sd[HUB]["next"].remove(HUB_REF)
    red_a, tail_a = _red(reachability_failures, broken_sd, common)

    # (b) 动作换成固定死点 -> 数据声明守卫红。
    broken_common = copy.deepcopy(common)
    broken_common[NODE]["action"]["param"]["target"] = [359, 976]
    red_b, tail_b = _red(pipeline_failures, broken_common)

    # (c) box_index 改成 0（点标题框）-> 真机帧守卫红。
    broken_common_c = copy.deepcopy(common)
    broken_common_c[NODE]["recognition"]["param"]["box_index"] = 0
    red_c, tail_c = _red(frame_failures, broken_common_c)

    # (d) 去掉标题叶（只认按钮）-> 「只有按钮」的反例帧误命中 -> 真机帧守卫红。
    broken_common_d = copy.deepcopy(common)
    broken_common_d[NODE]["recognition"]["param"]["all_of"] = [BTN_NODE]
    red_d, tail_d = _red(frame_failures, broken_common_d)

    # (e) 把 raid 的薄包装退回字面 ^关闭$ -> 共用判据守卫红（第二份拷贝）。
    broken_raid = copy.deepcopy(raid)
    broken_raid["RaidPopupClose"]["recognition"] = {
        "type": "OCR",
        "param": {"expected": ["^关闭$"]},
    }
    red_e, tail_e = _red(shared_failures, broken_raid, common)

    for label, red, tail in (
        ("从枢纽摘掉引用（讨伐完成又无人处理）", red_a, tail_a),
        ("动作改成固定死点", red_b, tail_b),
        ("box_index 改成 0", red_c, tail_c),
        ("去掉标题叶（只认按钮）", red_d, tail_d),
        ("raid 退回字面 ^关闭$（第二份拷贝）", red_e, tail_e),
    ):
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}  {tail}")

    ok = green and red_a and red_b and red_c and red_d and red_e
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "raid-done-popup-data-declared",
        "#67",
        "讨伐完成奖励弹窗是数据声明（And[标题,【关闭】], box_index=1, Click target:true 零偏移）",
        probe_raid_done_popup_data_declared,
    ),
    (
        "raid-done-popup-reachable-from-hub",
        "#67",
        "special_dungeon.json::SpecialEntry.next 以 [JumpBack]PubRewardDoneClose 引用（排在看门狗之前）",
        probe_raid_done_popup_reachable_from_hub,
    ),
    (
        "raid-done-popup-real-frame",
        "#67",
        "真机帧回放：讨伐完成 + 关闭 命中且点到【关闭】框中心 (359,976)；列表页/只有标题/只有按钮都不命中",
        probe_raid_done_popup_real_frame,
    ),
    (
        "raid-done-popup-shared-with-raid",
        "#67",
        "与战阵之宴链共用一份判据：raid.json::RaidPopupClose 是与门薄包装（无第二份 ^关闭$）",
        probe_raid_done_popup_shared_with_raid,
    ),
    (
        "raid-done-popup-declared",
        "#67",
        "special_dungeon.json 的 #67 声明注释在场；五条承重短语零丢失（纯编辑）",
        probe_raid_done_popup_declared,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
