# -*- coding: utf-8 -*-
"""#48：归位必须认识幻想共斗「战斗结束」QUEST RESULT 页（【解散】/【返回房间】）。

seam：``tools/live_harness.py`` 的归位有序表 ``RETURN_HOME_RULES``（页面 -> 动作分派）。

缺陷（真机战役 #48 实证）
------------------------
一场 幻想连战 共斗打完后，收工把设备留在共斗的 **QUEST RESULT** 页（真机帧
``s_stuck.png``）：底部只有【解散】@[183,1182,63,36] 与【返回房间】@[444,1184,118,33]，
**没有** 继续 / OK，也没有带底部导航的页脚（``bottom_nav_mc`` / ``back_page`` 都够不着它）。

而页顶那条大字横幅 **QUEST RESULT** 会被 ``settlement`` 规则的 ``QUESTRE`` 子串命中 ——
``settlement`` 找不到【继续】/【OK】，就退回 ``_pick(r"QUESTRE")`` **点顶部横幅**；横幅是
纯装饰、点了画面不变 → 状态机原地空转 ``max_steps``（10 步）仍回不了主城。真机只能人工
恢复（``recover_coop.py``），下一个任务起不来。

本票新增 ``coop_result`` 规则（**排在 settlement 之前**，否则 settlement 因横幅抢先命中）：
以底部【返回房间】为**唯一必需**锚点（共斗「战斗结束」页独有；``coop_room`` 的「解散房间
可以吗？」确认框、主城、排名结算页都没有它）—— 这样即便 OCR 把【解散】读丢，归位仍认得
这一页（不退回 settlement 的横幅死路）。动作**只点自己识别到的按钮框中心** —— 优先【解散】
（离开共斗房间，与真机人工恢复 ``recover_coop.py`` 一致），读不到才退回【返回房间】
（回共斗房，由 ``coop_room`` 接管）。**绝不点顶部 QUEST RESULT 横幅，绝不用写死坐标兜底。**

两个守卫（都在本文件里，prove-red 也在本文件里）
------------------------------------------------
1. ``return-home-coop-result`` —— 共斗结算页是**已知页面**：合成帧（照抄真机帧 ``s_stuck.png``
   的判据）首命中 = ``coop_result``（不是 ``settlement``）；动作只点【解散】识别框中心
   ``(214,1200)``，**不是**顶部横幅 ``(357,87)``；且它**不抢**主城 / 排名结算页。
2. ``return-home-coop-result-to-main-city`` —— **确定性回归**：共斗结算页 →（点【解散】）→ 主城。
   旧形态（表里没有 ``coop_result``）在该页首命中 ``settlement``、点的却是顶部横幅（纯装饰、
   画面不变）→ 原地空转、永远回不了主城（复现 #48）。

★prove-red★（``python tools\\contract_hooks\\hooks_48.py``）：
    * 从有序表里删掉 ``coop_result`` 规则 -> 共斗结算帧首命中变 ``settlement``、回归空转运不到
      主城（守卫红）；
    * 让 ``coop_result`` 判据过宽并排在最前（抢在 ``main_city`` 之前）-> 主城帧不再命中
      ``main_city``（守卫红）。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★（同 hooks_20/24/28/31）：prove-red 用 PYTHONPATH 抢先塞坏副本时，
# 副本仍优先命中，不被真实的 live_harness 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

COOP_RESULT_RULE_ID = "coop_result"
SETTLEMENT_RULE_ID = "settlement"
MAIN_CITY_RULE_ID = "main_city"

# ---------------------------------------------------------------------------
# 合成 OCR 帧（720 空间；坐标照抄真机帧 s_stuck.png 的 OCR）
# ---------------------------------------------------------------------------
#: 共斗「战斗结束」QUEST RESULT 页：底部【解散】+【返回房间】，顶部 QUEST RESULT 横幅，
#: 中部「合作」段 —— 真机帧 s_stuck.png 的 OCR 逐字复刻。
COOP_RESULT_ITEMS: list[tuple[str, list[int]]] = [
    ("QUESTRESULT", [124, 53, 467, 68]),
    ("合作", [116, 728, 52, 30]),
    ("RANK158 不思量自难忘", [187, 778, 309, 28]),
    ("RANK158 艾尔之暗", [189, 937, 254, 28]),
    ("解散", [183, 1182, 63, 36]),
    ("返回房间", [444, 1184, 118, 33]),
]
#: 退化帧：只剩下排两个按钮之一【返回房间】仍可读（【解散】抖动丢失）——动作须退回点它，
#: 仍绝不点横幅。
COOP_RESULT_FALLBACK_ITEMS: list[tuple[str, list[int]]] = [
    ("QUESTRESULT", [124, 53, 467, 68]),
    ("合作", [116, 728, 52, 30]),
    ("返回房间", [444, 1184, 118, 33]),
]
#: 共斗排名结算页（真机帧 s_afterQ2.png）：名次 / 贡献度 / 底部【继续】——**不是** coop_result，
#: 仍归 ``settlement`` 处理（不能抢）。
RANKINGS_ITEMS: list[tuple[str, list[int]]] = [
    ("QUESTRESULT", [124, 53, 470, 68]),
    ("名次", [119, 193, 53, 32]),
    ("贡献度", [190, 1061, 65, 25]),
    ("继续", [326, 1181, 67, 39]),
]
#: 共斗房（#31）：【解散】在（解散确认框里）但没有【返回房间】——coop_result 绝不能命中它。
ROOM_DIALOG_ITEMS: list[tuple[str, list[int]]] = [
    ("解散房间", [300, 536, 118, 37]),
    ("可以吗？", [300, 573, 106, 37]),
    ("取消", [164, 805, 63, 36]),
    ("解散", [489, 802, 66, 42]),
    ("房间号码", [276, 1182, 94, 30]),
]
#: 主城：主城独有锚点 ≥2（与 _is_main_city 一致）。
MAIN_CITY_ITEMS: list[tuple[str, list[int]]] = [
    ("修行之道", [22, 728, 151, 41]),
    ("成长任务", [50, 368, 116, 33]),
    ("当前进度", [365, 928, 61, 20]),
    ("主城", [157, 1248, 44, 25]),
]

#: 【解散】识别框中心（[183,1182,63,36]）。
EXPECTED_DISSOLVE_CLICK = (214, 1200)
#: 【返回房间】识别框中心（[444,1184,118,33]）。
EXPECTED_RETURN_ROOM_CLICK = (503, 1200)
#: 顶部 QUEST RESULT 横幅中心（[124,53,467,68]）——``settlement`` 在旧形态下会点这里（纯装饰）。
BANNER_CENTER = (357, 87)
#: 底部按钮行的 y 下界：只有点在这一行（y >= 该值）才会推进页面（确定性回归用）。
BUTTON_ROW_Y_MIN = 1000


# ---------------------------------------------------------------------------
# 有序表的【唯一来源】：tools/live_harness.py
# ---------------------------------------------------------------------------
def rules() -> list:
    """返回 live_harness 的归位有序表 ``RETURN_HOME_RULES``（['rule_id', probe, act]）。"""
    import live_harness as ca

    return [tuple(item) for item in ca.RETURN_HOME_RULES]


def rule_ids() -> list[str]:
    return [rid for rid, _probe, _act in rules()]


def _first_rule(rules_, items):
    """模拟 ensure_main_city 的分派：按顺序取首个命中判据的 rule_id。"""
    for rid, probe, _act in rules_:
        if probe(items):
            return rid
    return None


def _act_for(rules_, rid: str):
    for item in rules_:
        if item[0] == rid:
            return item[2]
    return None


def _click_point_for(items, rid: str, rules_=None):
    """真实调用某规则的 action（adb_tap 被替换捕获），返回它点到的 720 坐标。"""
    import live_harness as ca

    captured: list[tuple[int, int]] = []
    real_tap = ca.adb_tap
    real_time = ca.time

    class _NoSleep:
        @staticmethod
        def sleep(_seconds):  # noqa: D401
            return None

    try:
        ca.adb_tap = lambda x, y: captured.append((int(round(x)), int(round(y))))
        ca.time = _NoSleep
        act = _act_for(rules_ if rules_ is not None else rules(), rid)
        if act is None:
            return None
        act(items, 0)
    finally:
        ca.adb_tap = real_tap
        ca.time = real_time
    return captured[-1] if captured else None


def walk(rules_, start, next_frame=MAIN_CITY_ITEMS, max_steps: int = 10):
    """确定性回归：``start`` 页上**只有点到底部按钮行（y>=1000）才推进**到 ``next_frame``。

    模拟真机语义：点顶部横幅（纯装饰）画面不变 —— 因此盲点横幅的规则会在本页原地空转。
    返回 ``(是否到主城, 命中序列)``。
    """
    items = start
    seq: list[str] = []
    for _ in range(max_steps):
        rid = _first_rule(rules_, items)
        seq.append(rid)
        if rid is None:
            return False, seq
        if rid == MAIN_CITY_RULE_ID:
            return True, seq
        point = _click_point_for(items, rid, rules_)
        if point is not None and point[1] >= BUTTON_ROW_Y_MIN:
            items = next_frame  # 真的按到了按钮 -> 推进
        # 否则：点空了（例如点到顶部横幅），画面不变 -> 下一步还是同一页
    return False, seq


# ---------------------------------------------------------------------------
# 守卫 1：共斗结算页是已知页面 + 读后动 + 不抢排名页/主城
# ---------------------------------------------------------------------------
def coop_result_failures() -> list[str]:
    import live_harness as ca

    rules_ = rules()
    msgs: list[str] = []

    if COOP_RESULT_RULE_ID not in rule_ids():
        msgs.append("有序表缺少 coop_result 规则（共斗结算页仍是「settlement 点横幅」的死路，#48）")
        return msgs

    if not ca._is_coop_result(COOP_RESULT_ITEMS):
        msgs.append("共斗结算帧没有被认出（#48 未修）")
    if not ca._is_coop_result(COOP_RESULT_FALLBACK_ITEMS):
        msgs.append("只剩【返回房间】的退化帧没有被认出（动作会无处可点）")

    # 不抢：排名结算页 / 主城 / 共斗房解散确认框都不被 coop_result 命中。
    if ca._is_coop_result(RANKINGS_ITEMS):
        msgs.append("coop_result 判据误命中共斗排名结算页（会抢走 settlement 的【继续】）")
    if ca._is_coop_result(MAIN_CITY_ITEMS):
        msgs.append("coop_result 判据误命中主城帧")
    if ca._is_coop_result(ROOM_DIALOG_ITEMS):
        msgs.append("coop_result 判据误命中共斗房解散确认框（只有【解散】没有【返回房间】）")

    # 首命中：共斗结算页 = coop_result（不是 settlement）；排序必须早于 settlement。
    first = _first_rule(rules_, COOP_RESULT_ITEMS)
    if first != COOP_RESULT_RULE_ID:
        msgs.append(f"共斗结算帧首命中应为 coop_result，实际 {first!r}")
    # 退化帧（OCR 读丢【解散】，只剩【返回房间】）仍须命中 coop_result（不退回 settlement 死路）。
    if _first_rule(rules_, COOP_RESULT_FALLBACK_ITEMS) != COOP_RESULT_RULE_ID:
        msgs.append(
            f"只剩【返回房间】的退化帧首命中应为 coop_result，实际 "
            f"{_first_rule(rules_, COOP_RESULT_FALLBACK_ITEMS)!r}（会退回 settlement 点横幅）"
        )
    if rule_ids().index(COOP_RESULT_RULE_ID) > rule_ids().index(SETTLEMENT_RULE_ID):
        msgs.append("coop_result 排在了 settlement 之后（settlement 会因横幅 QUESTRE 抢先点横幅）")

    # 不抢排名页 / 主城 的首命中。
    if _first_rule(rules_, RANKINGS_ITEMS) != SETTLEMENT_RULE_ID:
        msgs.append(f"排名结算页首命中应为 settlement，实际 {_first_rule(rules_, RANKINGS_ITEMS)!r}")
    if _first_rule(rules_, MAIN_CITY_ITEMS) != MAIN_CITY_RULE_ID:
        msgs.append(f"主城帧被抢走：首命中 {_first_rule(rules_, MAIN_CITY_ITEMS)!r}")

    # 读后动：只点识别到的按钮框中心（【解散】），绝不是顶部横幅。
    point = _click_point_for(COOP_RESULT_ITEMS, COOP_RESULT_RULE_ID, rules_)
    if point != EXPECTED_DISSOLVE_CLICK:
        msgs.append(f"共斗结算页应点【解散】框中心 {EXPECTED_DISSOLVE_CLICK}，实际 {point}")
    if point == BANNER_CENTER:
        msgs.append("共斗结算页点到顶部 QUEST RESULT 横幅（纯装饰，画面不变 —— #48 根因）")
    if point is not None and point[1] < BUTTON_ROW_Y_MIN:
        msgs.append(f"共斗结算页点到了按钮行之外 {point}（非底部按钮，绝不盲点）")

    # 退化帧：只剩【返回房间】时退回点它，仍不点横幅。
    fb = _click_point_for(COOP_RESULT_FALLBACK_ITEMS, COOP_RESULT_RULE_ID, rules_)
    if fb != EXPECTED_RETURN_ROOM_CLICK:
        msgs.append(f"退化帧应退回点【返回房间】框中心 {EXPECTED_RETURN_ROOM_CLICK}，实际 {fb}")
    return msgs


def probe_coop_result() -> bool:
    """#48 守卫 1：共斗结算页是已知页面，动作只点识别到的按钮框中心（不点横幅）。"""
    return coop_result_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：确定性回归 —— 共斗结算页 →（点【解散】）→ 主城；旧形态空转
# ---------------------------------------------------------------------------
def probe_coop_result_to_main_city() -> bool:
    """#48 守卫 2：共斗结算页能经「点【解散】」走到主城；旧形态（settlement 点横幅）空转。"""
    reached, seq = walk(rules(), COOP_RESULT_ITEMS)
    if not reached or seq != [COOP_RESULT_RULE_ID, MAIN_CITY_RULE_ID]:
        return False
    # 旧形态（表里没有 coop_result）：settlement 抢先命中、点的却是顶部横幅 -> 画面不变 -> 空转。
    without = [r for r in rules() if r[0] != COOP_RESULT_RULE_ID]
    old_reached, old_seq = walk(without, COOP_RESULT_ITEMS)
    return (not old_reached) and old_seq[:1] == [SETTLEMENT_RULE_ID] and len(old_seq) == 10


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_48.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """真实绿；删掉 coop_result / 让它过宽抢主城 -> 守卫各自变红。"""
    print("hooks_48 prove-red：两处破坏，要求守卫各自变红")
    green = probe_coop_result() is True and probe_coop_result_to_main_city() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：共斗结算页是已知页面 + 能经【解散】回主城（绿）")
    if not green:
        return False

    # (a) 删掉 coop_result -> 共斗结算帧首命中变 settlement、回归空转（守卫红）。
    without = [r for r in rules() if r[0] != COOP_RESULT_RULE_ID]
    first = _first_rule(without, COOP_RESULT_ITEMS)
    reached_wo, seq_wo = walk(without, COOP_RESULT_ITEMS)
    red_a = first == SETTLEMENT_RULE_ID and (not reached_wo) and seq_wo[:1] == [SETTLEMENT_RULE_ID]
    tail = f"  首命中={first!r}，回归序列前 3={seq_wo[:3]}" if not red_a else ""
    print(f"  [{'PASS' if red_a else 'FAIL'}] 删掉 coop_result -> settlement 点横幅空转 "
          f"{'红' if red_a else '仍绿'}{tail}")

    # (b) 让 coop_result 判据过宽并排最前 -> 主城帧不再命中 main_city（守卫红）。
    broken = [
        (COOP_RESULT_RULE_ID, lambda _items: True, _act_for(rules(), COOP_RESULT_RULE_ID)),
        *rules(),
    ]
    stolen = _first_rule(broken, MAIN_CITY_ITEMS)
    red_b = stolen != MAIN_CITY_RULE_ID
    print(f"  [{'PASS' if red_b else 'FAIL'}] coop_result 抢在主城之前 -> "
          f"主城帧首命中={stolen!r}（{'红' if red_b else '仍绿'}）")

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-coop-result",
        "#48",
        "归位认识共斗「战斗结束」QUEST RESULT 页（【解散】/【返回房间】）：首命中 coop_result、"
        "只点识别到的按钮框中心（绝不点顶部横幅），且不抢排名结算页 / 主城",
        probe_coop_result,
    ),
    (
        "return-home-coop-result-to-main-city",
        "#48",
        "确定性回归：共斗结算页 →（点【解散】）→ 主城；旧形态（settlement 点顶部横幅）原地空转",
        probe_coop_result_to_main_city,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
