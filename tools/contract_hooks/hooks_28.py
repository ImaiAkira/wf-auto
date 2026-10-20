# -*- coding: utf-8 -*-
"""#28：归位必须认结算 / 奖励页 —— 收工后设备停在结算页（#26 真机实证）。

seam：``tools/live_harness.py`` 的归位状态机有序表 ``RETURN_HOME_RULES``
（``ensure_main_city`` 页面 -> 动作的分派表）。

背景（#26 真机实证）
-------------------------------
#22 把收工闸挂在结算帧：单目标打满配置次数后，结算动作在 **结算页** 把任务
``StopTask`` 掉（复用批量终端 ``SpecialBatchStop``）。于是设备停在 QUESTRESULT /
结算页——证据 ``v26/shot_015_164900.png``：OCR 读到

    「继续」@[328,1181,63,36] +「QUESTRESULT」+「等级最大！」

而本状态机【不认识】这一页（它的「继续」不是任何一条规则的判据）→
``[归位] step0: 未知页面，停手`` → 设备留在结算页。**归位的定义是「从任意【已知】
页面回主城」**，结算 / 奖励页就是一处已知页面，只是此前没有规则。本票补齐它。

两个守卫（都在本文件里，prove-red 也在本文件里）
------------------------------------------------
1. ``return-home-settlement-page`` —— 结算 / 奖励页是**已知页面**：合成结算帧（照抄真机
   帧的判据：继续 / QUESTRESULT / 等级最大）首命中 = ``settlement``（不是 ``None``）；
   动作只点【识别到的框中心】（继续 @ (359,1199)），绝不盲点；且它**不抢**主城 /
   账号确认页 / 标题页（那三页仍各自命中各自规则）。
2. ``return-home-settlement-to-main-city`` —— **确定性回归**：结算页 →（点继续）→ 带底部
   导航的列表页 →（点主城）→ 主城。旧形态（表里没有 settlement）在结算页首命中 = None
   = 停手 = 设备留在结算页（复现 #26）；新形态走回主城。

★prove-red★（``python tools\\contract_hooks\\hooks_28.py``）：
    * 从有序表里删掉 ``settlement`` 规则 -> 结算帧首命中变 None、回归走不到主城（守卫红）；
    * 让 ``settlement`` 判据过宽并排在最前（抢在 main_city 之前）-> 主城帧不再命中
      ``main_city``（守卫红）。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★（同 hooks_20/hooks_24）：prove-red 用 PYTHONPATH 抢先塞坏副本时，
# 副本仍优先命中，不被真实的 live_harness 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

SETTLEMENT_RULE_ID = "settlement"

# ---------------------------------------------------------------------------
# 合成 OCR 帧（720 空间，与真机帧 v26/shot_015_164900.png 的判据一致）
# ---------------------------------------------------------------------------
#: 结算 / 奖励页：底部【继续】+ 顶部 QUESTRESULT + 升级结算大字「等级最大！」。
#: 实测坐标照抄真机帧：继续 @[328,1181,63,36]（中心 (359,1199)），横幅 @[127,53,465,68]。
SETTLE_ITEMS: list[tuple[str, list[int]]] = [
    ("继续", [328, 1181, 63, 36]),
    ("QUESTRESULT", [127, 53, 465, 68]),
    ("等级最大！", [51, 774, 113, 34]),
]
#: 结算推进后落到的「带底部导航」页面（领主战列表 / 详情页）：底部导航「主城」+ 最左槽「返回」。
#: 只放一个主城锚点「领主战」，确保它不是 main_city（主城独有判据需 ≥2 命中）。
LIST_ITEMS: list[tuple[str, list[int]]] = [
    ("主城", [157, 1248, 44, 25]),
    ("返回", [8, 1248, 40, 25]),
    ("领主战", [330, 700, 80, 30]),
]
#: 主城：主城独有锚点 ≥2（与 _is_main_city 一致）。
MAIN_CITY_ITEMS: list[tuple[str, list[int]]] = [
    ("修行之道", [100, 300, 90, 30]),
    ("关卡", [600, 1100, 70, 30]),
    ("当前进度", [200, 400, 90, 30]),
    ("主城", [157, 1248, 44, 25]),
]
#: 账号确认页（弹窗盖在标题页上，两框都有）——结算规则绝不能抢它。
ACCOUNT_CONFIRM_ITEMS: list[tuple[str, list[int]]] = [
    ("继续游戏", [300, 820, 120, 60]),
    ("点击开始", [250, 1150, 220, 60]),
]
#: 标题页（只有「点击开始」）。
TITLE_ITEMS: list[tuple[str, list[int]]] = [("点击开始", [250, 1150, 220, 60])]

EXPECTED_CONTINUE_CLICK = (359, 1199)  # [328,1181,63,36] 的中心


# ---------------------------------------------------------------------------
# 有序表的【唯一来源】：tools/live_harness.py
# ---------------------------------------------------------------------------
def rules() -> list:
    """返回 live_harness 的归位有序表 ``RETURN_HOME_RULES``（['rule_id', probe, act]）。"""
    import live_harness as ca

    return [tuple(item) for item in ca.RETURN_HOME_RULES]


def rule_ids() -> list[str]:
    return [rid for rid, _probe, _act in rules()]


def _probe_for(rules_, rid: str):
    for item in rules_:
        if item[0] == rid:
            return item[1]
    return None


def _act_for(rules_, rid: str):
    for item in rules_:
        if item[0] == rid:
            return item[2]
    return None


def _first_rule(rules_, items) -> str | None:
    """模拟 ensure_main_city 的分派：按顺序取首个命中判据的 rule_id。"""
    for rid, probe, _act in rules_:
        if probe(items):
            return rid
    return None


def trace(frames, rules_=None, max_steps: int = 10):
    """确定性走一遍归位状态机（画面按脚本推进）。

    每一步取首个命中规则；命中 ``main_city`` 即到主城（结束）；其余命中 = 已出手，
    推进到下一帧；无命中 = 未知页面、停手。返回 ``(是否到主城, 命中序列)``。
    """
    rules_ = rules() if rules_ is None else rules_
    frames = list(frames)
    seq: list[str] = []
    i = 0
    for _ in range(max_steps):
        items = frames[min(i, len(frames) - 1)]
        rid = _first_rule(rules_, items)
        seq.append(rid)
        if rid is None:
            return False, seq
        if rid == "main_city":
            return True, seq
        i += 1
    return False, seq


def click_point_for(items, rules_=None) -> tuple[int, int] | None:
    """真实调用 settlement 规则的动作（adb_tap 被替换捕获），返回它点到的 720 坐标。"""
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
        act = _act_for(rules_ if rules_ is not None else rules(), SETTLEMENT_RULE_ID)
        if act is None:
            return None
        act(items, 0)
    finally:
        ca.adb_tap = real_tap
        ca.time = real_time
    return captured[-1] if captured else None


# ---------------------------------------------------------------------------
# 守卫 1：结算 / 奖励页是已知页面（且不抢主城 / 账号 / 标题）
# ---------------------------------------------------------------------------
def settlement_page_failures() -> list[str]:
    rules_ = rules()
    msgs: list[str] = []

    if SETTLEMENT_RULE_ID not in rule_ids():
        msgs.append(f"有序表缺少 {SETTLEMENT_RULE_ID!r} 规则（结算 / 奖励页仍是未知页面）")
        return msgs

    first = _first_rule(rules_, SETTLE_ITEMS)
    if first != SETTLEMENT_RULE_ID:
        msgs.append(f"结算帧首命中应为 {SETTLEMENT_RULE_ID!r}，实际 {first!r}（设备会停在结算页）")

    point = click_point_for(SETTLE_ITEMS, rules_)
    if point != EXPECTED_CONTINUE_CLICK:
        msgs.append(f"结算动作应点『继续』识别框中心 {EXPECTED_CONTINUE_CLICK}，实际 {point}")

    # 不抢：主城 / 账号确认页 / 标题页仍各自命中各自规则。
    if _first_rule(rules_, MAIN_CITY_ITEMS) != "main_city":
        msgs.append(f"主城帧被 settlement 抢走：首命中 {_first_rule(rules_, MAIN_CITY_ITEMS)!r}")
    if _first_rule(rules_, ACCOUNT_CONFIRM_ITEMS) != "account_confirm":
        msgs.append(f"账号确认页被抢走：首命中 {_first_rule(rules_, ACCOUNT_CONFIRM_ITEMS)!r}")
    if _first_rule(rules_, TITLE_ITEMS) != "title":
        msgs.append(f"标题页被抢走：首命中 {_first_rule(rules_, TITLE_ITEMS)!r}")
    return msgs


def probe_settlement_known_page() -> bool:
    """#28 守卫 1：结算 / 奖励页是已知页面，动作只点识别到的『继续』框中心。"""
    return settlement_page_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：确定性回归 —— 结算页 →（继续）→ 列表页 →（主城）→ 主城
# ---------------------------------------------------------------------------
def probe_settlement_to_main_city() -> bool:
    """#28 守卫 2：结算页能经「点继续 → 点主城」走到主城；旧形态停手。"""
    reached, seq = trace([SETTLE_ITEMS, LIST_ITEMS, MAIN_CITY_ITEMS])
    if not reached or seq != [SETTLEMENT_RULE_ID, "bottom_nav_mc", "main_city"]:
        return False
    # 旧形态（表里没有 settlement）：结算页首命中 None = 停手 = 留在结算页（复现 #26）。
    old_rules = [r for r in rules() if r[0] != SETTLEMENT_RULE_ID]
    old_reached, old_seq = trace([SETTLE_ITEMS, LIST_ITEMS, MAIN_CITY_ITEMS], old_rules)
    return (not old_reached) and old_seq == [None]


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_28.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """真实绿；删掉 settlement 规则 / 让它过宽抢主城 -> 守卫各自变红。"""
    print("hooks_28 prove-red：两处破坏，要求守卫各自变红")
    green = probe_settlement_known_page() is True and probe_settlement_to_main_city() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：结算页是已知页面 + 能经列表页回主城（绿）")
    if not green:
        return False

    # (a) 删掉 settlement 规则 -> 结算帧首命中 None、回归走不到主城。
    without = [r for r in rules() if r[0] != SETTLEMENT_RULE_ID]
    first = _first_rule(without, SETTLE_ITEMS)
    reached_wo, seq_wo = trace([SETTLE_ITEMS, LIST_ITEMS, MAIN_CITY_ITEMS], without)
    red_a = first is None and reached_wo is False and seq_wo == [None]
    tail = f"  结算帧首命中={first!r}，回归序列={seq_wo}" if not red_a else ""
    print(f"  [{'PASS' if red_a else 'FAIL'}] 删掉 settlement 规则 -> "
          f"{'红' if red_a else '仍绿'}{tail}")

    # (b) 让 settlement 判据过宽并排最前 -> 主城帧不再命中 main_city。
    broken = [(SETTLEMENT_RULE_ID, lambda _items: True, _act_for(rules(), SETTLEMENT_RULE_ID)), *rules()]
    stolen = _first_rule(broken, MAIN_CITY_ITEMS)
    red_b = stolen != "main_city"
    print(f"  [{'PASS' if red_b else 'FAIL'}] settlement 抢在主城之前 -> "
          f"主城帧首命中={stolen!r}（{'红' if red_b else '仍绿'}）")

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-settlement-page",
        "#28",
        "归位状态机认结算 / 奖励页（继续 / QUESTRESULT / 等级最大）：首命中 settlement、"
        "只点识别框中心，且不抢主城 / 账号 / 标题",
        probe_settlement_known_page,
    ),
    (
        "return-home-settlement-to-main-city",
        "#28",
        "确定性回归：结算页 →（点继续）→ 列表页 →（点主城）→ 主城；"
        "旧形态（无 settlement）在结算页停手（复现 #26）",
        probe_settlement_to_main_city,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
