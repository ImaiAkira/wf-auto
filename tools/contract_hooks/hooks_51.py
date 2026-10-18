# -*- coding: utf-8 -*-
"""#51：``run_side_live.py`` 三个账本节点在真机上 hit=False —— 进入卡片【读后动】+【明确收工】。

现场（设备 16448 账号B，接力 relayB；证据 <工作区>\\final_joss\\log_q3_relay.txt +
frames\\relayA\\；截屏 tools/frames/side_story_list_empty.png）
------------------------------------------------------------------
接力 relayA（降临讨伐，干净收工）之后 relayB 跑 ``run_side_live.py``：主城 -> 关卡 ->
外传故事列表 -> 点「未通关」-> 盲点固定坐标 (540,720) -> **什么都没进去** ->
``SideNextSpecial`` / ``SideNextStory`` / ``SideNextBattle`` 三个节点 **hit=False**，
任务却「静默地什么都没做」，随后干净回主城。

★根因（真机帧 + 离线 OCR 实证）★：**不是**关卡列表结构不匹配 —— 该账号「未通关」列表
为空（画面显示「未找到符合的外传故事」，tools/frames/side_story_list_empty.png），
根本没有卡片可进。真实结构（tools/frames/event_stage_list.png）与 ``parse_side_rows`` /
``select_side_stage`` **完全一致**：点第一张卡后是外传关卡列表（NEW/COMPLETE!! 徽标 +
STORY / 战斗 标签 + 关卡标题），``SideNextStory`` 在真机帧上**命中了 STORY 行**。

四个守卫（prove-red 也在本文件里）
----------------------------------
1. ``side-entry-empty-list-stops`` —— 空「未通关」列表 -> ``entry_decision`` **明确收工并给出
   原因**（绝不静默 hit=False、绝不盲点固定坐标）；且此帧上三个账本节点本就选不出一关
   （hit=False 是【正确结果】，不是缺陷）。
2. ``side-entry-reads-first-card`` —— 非空列表 -> 点【识别到的第一张卡标记框中心】（读后动），
   绝不写死 (540,720) 之类固定坐标。
3. ``side-stage-advances-with-ledger`` —— 真实关卡列表：确有 NEW/COMPLETE!! 徽标；
   ``select_side_stage`` 选出 STORY 行「遥远过去的国家」；记账后 is_done 成立、复选跳过
   （账本真正推进、留下账目）。
4. ``side-no-stale-accounting`` —— 记账只在【真正进入关卡列表（有徽标）】之后发生
   （与 #44 同一纪律：绝不用陈旧页面记账）。

★prove-red★（``python tools\\contract_hooks\\hooks_51.py``）：把 entry_decision 改成「永远
enter + 写死坐标」/ 把 has_stage_badge 改成恒真 / 摘掉进入后的徽标复核 -> 守卫各自变红。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"


def _paths():
    for p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _rl():
    _paths()
    import run_side_live  # noqa: PLC0415

    return run_side_live


def _sr():
    _paths()
    import stage_rows as sr  # noqa: PLC0415

    return sr


def _agent_source() -> str:
    return (TOOLS_DIR / "run_side_live.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 真机帧的 OCR 条目（720 空间）—— 逐字来自离线 OCR（OcrTask，assets/resource/model/ocr）。
# 这些是【证据】，不是臆造：结构判据必须能在其上复现。
# ---------------------------------------------------------------------------
# tools/frames/side_story_list_empty.png（= relayB 截屏 live_stage_list.png）：空「未通关」。
EMPTY_LIST_ITEMS = [
    ("外传故事列表", [30, 305, 172, 32]),
    ("返回", [30, 1246, 46, 26]),
    ("未通关", [74, 388, 91, 34]),
    ("日999/101", [93, 20, 112, 28]),
    ("主城", [157, 1248, 44, 25]),
    ("未找到符合的外传故事", [190, 790, 335, 32]),
    ("角色", [275, 1244, 46, 29]),
    ("已通关", [316, 388, 89, 34]),
    ("都记录在这里了★", [387, 304, 228, 34]),
    ("各位活跃的身姿", [389, 274, 198, 32]),
    ("商店", [397, 1245, 45, 27]),
    ("3,140,655", [509, 18, 95, 24]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("已完成", [555, 388, 90, 34]),
    ("菜单", [636, 1248, 45, 26]),
]

# tools/frames/side_story_list.png：外传故事列表，三张卡（每张右侧「角色加入/装备获得」）。
# 第一张卡的标记中心 y=581 落在 SideClearCardMark 的 ROI（y 430~600）内；第 2/3 张在外。
LIST_WITH_CARDS_ITEMS = [
    ("外传故事列表", [29, 305, 174, 32]),
    ("返回", [31, 1246, 45, 26]),
    ("虚假的人偶公主", [35, 481, 481, 93]),
    ("幻彩摩天楼", [62, 625, 356, 97]),
    ("未通关", [74, 388, 91, 34]),
    ("894/106", [93, 20, 114, 28]),
    ("主城", [157, 1248, 44, 25]),
    ("the peineess of-figment", [206, 562, 176, 19]),
    ("M激4", [230, 768, 161, 53]),
    ("情人节盛典", [234, 790, 219, 80]),
    ("角色", [275, 1244, 46, 29]),
    ("THE SKYSCRAPER", [287, 697, 119, 20]),
    ("已通关", [316, 388, 89, 34]),
    ("珠", [333, 853, 30, 21]),
    ("防", [363, 854, 26, 18]),
    ("C", [365, 757, 24, 23]),
    ("S", [387, 760, 40, 20]),
    ("各位活跃的身姿", [389, 274, 198, 32]),
    ("都记录在这里了★", [390, 309, 224, 27]),
    ("商店", [397, 1246, 43, 26]),
    ("角色加入/装备获得", [512, 568, 170, 26]),
    ("角色加入/装备获得", [512, 710, 170, 28]),
    ("角色加入/装备获得", [512, 857, 169, 23]),
    ("2,779,410", [513, 18, 91, 24]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("已完成", [557, 388, 87, 34]),
    ("菜单", [636, 1248, 45, 26]),
]

# 第一张卡标记框（720）——entry_decision / first_card_box 必须返回它。
FIRST_CARD_BOX = [512, 568, 170, 26]
# 「读后动」反例：写死坐标（旧实现盲点的 (540,720)）绝不能被当成识别框返回。
HARDCODED_TAP = [539, 719, 2, 2]

# tools/frames/event_stage_list.png：点第一张卡后的【外传关卡列表】（真实结构）。
# NEW 行 = STORY「遥远过去的国家」；两条 战斗 行已 COMPLETE!!。
STAGE_LIST_ITEMS = [
    ("虚假人偶公主", [11, 248, 701, 194]),
    ("NEW", [13, 673, 54, 25]),
    ("COMPLETE!!", [15, 817, 121, 23]),
    ("COMPLETE!!", [15, 1009, 126, 23]),
    ("返回", [30, 1246, 46, 26]),
    ("推荐编成", [55, 961, 97, 29]),
    ("推荐编成", [56, 1152, 97, 29]),
    ("战斗", [87, 929, 33, 20]),
    ("战斗", [88, 1122, 29, 16]),
    ("894/106", [95, 20, 112, 28]),
    ("主城", [157, 1248, 44, 25]),
    ("遥远过去的国家", [202, 752, 199, 32]),
    ("向王都进发2", [202, 889, 158, 28]),
    ("STORY", [203, 700, 70, 18]),
    ("向王都进发1", [203, 1080, 153, 28]),
    ("推荐属性雷", [207, 1154, 154, 27]),
    ("推荐属性", [209, 965, 86, 24]),
    ("角色", [275, 1244, 46, 29]),
    ("雷", [329, 969, 19, 17]),
    ("the princess of kigment.", [333, 409, 312, 28]),
    ("体力", [363, 1154, 49, 24]),
    ("体力", [366, 962, 45, 27]),
    ("商店", [397, 1245, 43, 27]),
    ("领主战", [423, 606, 62, 26]),
    ("10", [447, 1154, 29, 23]),
    ("10", [448, 964, 29, 24]),
    ("2,779,410", [509, 18, 95, 24]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("剧情", [530, 602, 47, 31]),
    ("SS", [536, 880, 94, 82]),
    ("SS", [538, 1074, 90, 74]),
    ("道具", [633, 622, 44, 26]),
    ("兑换", [635, 605, 40, 21]),
    ("菜单", [636, 1248, 45, 25]),
]

# 真机帧里 SideNextStory 选中的那一关（真实结构 -> 账目键）。
EXPECTED_STORY_STAGE = "遥远过去的国家"


# ---------------------------------------------------------------------------
# 守卫 1：空「未通关」列表 -> 明确收工（不静默 hit=False、不盲点固定坐标）
# ---------------------------------------------------------------------------
def _entry_empty_failures(entry_fn=None, badge_fn=None) -> list[str]:
    rl = _rl()
    sr = _sr()
    entry = entry_fn or rl.entry_decision
    badge = badge_fn or rl.has_stage_badge
    msgs: list[str] = []

    decision, payload, reason = entry(EMPTY_LIST_ITEMS)
    if decision != "stop":
        msgs.append(f"空列表：entry_decision 应明确收工（stop），实际 {decision!r}（静默继续 = 本票缺陷）")
    if payload is not None:
        msgs.append(f"空列表：收工时不应给出点击目标，实际 payload={payload!r}（盲点固定坐标）")
    if not reason or ("空" not in reason and "未找到" not in reason):
        msgs.append("空列表：收工未给出明确原因（票面要求：停下来并说清为什么）")

    if badge(EMPTY_LIST_ITEMS):
        msgs.append("空列表：被判成外传关卡列表（有 NEW/COMPLETE 徽标）—— 判据串页")

    # 空列表上三个账本节点本就选不出一关 —— hit=False 是【正确结果】，不是结构缺陷。
    rows = sr.parse_side_rows(EMPTY_LIST_ITEMS)
    if sr.select_side_stage(rows, row_type_regex="STORY", check_badge=True) is not None:
        msgs.append("空列表：竟能选出一关（判据过松，可能对陈旧页取证）")
    return msgs


def probe_side_entry_empty_list_stops() -> bool:
    """#51 守卫 1：空「未通关」列表 -> 明确收工并给出原因。"""
    return _entry_empty_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：非空列表 -> 点【识别到的第一张卡标记框中心】（读后动）
# ---------------------------------------------------------------------------
def _entry_first_card_failures(entry_fn=None) -> list[str]:
    rl = _rl()
    entry = entry_fn or rl.entry_decision
    msgs: list[str] = []

    decision, payload, reason = entry(LIST_WITH_CARDS_ITEMS)
    if decision != "enter":
        msgs.append(f"非空列表：entry_decision 应给出点击目标（enter），实际 {decision!r}")
    elif list(payload) != FIRST_CARD_BOX:
        msgs.append(f"非空列表：应点第一张卡标记 {FIRST_CARD_BOX}，实际 {payload!r}")
    if payload is not None and list(payload) == HARDCODED_TAP:
        msgs.append("非空列表：返回的疑似写死坐标（读后动应返回 OCR 框，不是常量）")

    # 卡片 ROI 只认第一张卡带：第 2/3 张卡的标记不得被选中（否则可能进错卡）。
    if list(rl.first_card_box(LIST_WITH_CARDS_ITEMS) or []) != FIRST_CARD_BOX:
        msgs.append("非空列表：first_card_box 未取到第一张卡标记（ROI/排序被改坏？）")
    return msgs


def probe_side_entry_reads_first_card() -> bool:
    """#51 守卫 2：非空列表 -> 点识别到的第一张卡标记框中心。"""
    return _entry_first_card_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：真实关卡列表 -> 选出一关 + 记账（任务真正推进、留下账目）
# ---------------------------------------------------------------------------
def _stage_advances_failures(badge_fn=None) -> list[str]:
    rl = _rl()
    sr = _sr()
    badge = badge_fn or rl.has_stage_badge
    msgs: list[str] = []

    if not badge(STAGE_LIST_ITEMS):
        msgs.append("真实关卡列表：has_stage_badge 判为 False（require_badge 前提不成立）")

    rows = sr.parse_side_rows(STAGE_LIST_ITEMS)
    if len(rows) != 3:
        msgs.append(f"真实关卡列表：parse_side_rows 应解析 3 行，实际 {len(rows)}")

    sel = sr.select_side_stage(rows, row_type_regex="STORY", check_badge=True)
    if sel is None or sel.get("name") != EXPECTED_STORY_STAGE:
        msgs.append(
            f"真实关卡列表：SideNextStory 应选到 {EXPECTED_STORY_STAGE!r}，实际 {sel.get('name') if sel else None!r}"
        )
        return msgs

    # 记账往返：选中 -> mark_done -> is_done 成立 -> 复选跳过（账本真正生效）。
    import progress as ledger  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="wf_hook51_led") as d:
        led = ledger.Progress(Path(d) / "progress.json")
        key = sr.side_stage_key("side_story", sel["name"])
        if led.is_done(key):
            msgs.append("真实关卡列表：记账前 is_done 不应成立")
        led.mark_done(key)
        if not led.is_done(key):
            msgs.append("真实关卡列表：mark_done 后 is_done 仍为 False（账本没留下账目）")
        # select_side_stage 的 is_done 收到的是【关卡名】（normalize_key），不是完整 key
        # （见 stage_rows.pick_side_next）-> 用 side_stage_key("side_story", 名) 回指账目。
        sel2 = sr.select_side_stage(
            rows,
            row_type_regex="STORY",
            check_badge=True,
            is_done=lambda n: led.is_done(sr.side_stage_key("side_story", n)),
        )
        if sel2 is not None:
            msgs.append("真实关卡列表：记账后复选仍返回同一关（账本未生效 -> 会重复打）")
    return msgs


def probe_side_stage_advances_with_ledger() -> bool:
    """#51 守卫 3：真实关卡列表 -> 选出一关 + 记账后不再复选。"""
    return _stage_advances_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：记账只在【真正进入关卡列表（有徽标）】之后发生（#44 纪律）
# ---------------------------------------------------------------------------
def _no_stale_accounting_failures(badge_fn=None, source: str | None = None) -> list[str]:
    rl = _rl()
    badge = badge_fn or rl.has_stage_badge
    src = _agent_source() if source is None else source
    msgs: list[str] = []

    # 行为：列表页（含空列表）都没有徽标 -> 不是关卡列表 -> 绝不对它记账/取证。
    for frame, tag in ((EMPTY_LIST_ITEMS, "空列表"), (LIST_WITH_CARDS_ITEMS, "卡片列表")):
        if badge(frame):
            msgs.append(f"{tag}：被判成关卡列表（有徽标）—— 记账前置条件被绕过")

    # 源码：进入后必须【先复核徽标】，且记账必须排在该复核之后。
    gate = "if not has_stage_badge(items1):"
    if gate not in src:
        msgs.append("源码：进入卡片后没有复核 NEW/COMPLETE 徽标（缺关卡列表前置闸）")
    if "ledger.mark_done(" not in src:
        msgs.append("源码：找不到记账调用（账本被摘掉？）")
    if gate in src and "ledger.mark_done(" in src:
        if src.index(gate) > src.index("ledger.mark_done("):
            msgs.append("源码：记账早于『关卡列表徽标复核』（可能对陈旧/非列表页记账）")
    # 读后动：主流程不得再盲点 (540,720) 这类固定坐标。
    if "ca.adb_tap(540, 720)" in src:
        msgs.append("源码：仍存在盲点固定坐标 ca.adb_tap(540, 720)（#51 要求读后动）")
    return msgs


def probe_side_no_stale_accounting() -> bool:
    """#51 守卫 4：记账只在真正进入关卡列表之后发生。"""
    return _no_stale_accounting_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_51.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """真实绿；三类破坏各自变红（永远 enter / 徽标恒真 / 摘掉进入后复核）。"""
    print("hooks_51 prove-red：改坏 entry_decision / has_stage_badge / 源码复核，要求守卫变红")
    green = (
        probe_side_entry_empty_list_stops() is True
        and probe_side_entry_reads_first_card() is True
        and probe_side_stage_advances_with_ledger() is True
        and probe_side_no_stale_accounting() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：读后动 + 空列表明确收工 + 记账纪律（绿）")
    if not green:
        return False

    checks: list[bool] = []

    # 破坏 1：entry_decision 永远 enter + 写死坐标（旧行为）-> 守卫 1、2 必须红。
    broken_entry = lambda _items: ("enter", HARDCODED_TAP, "")  # noqa: E731
    m1 = _entry_empty_failures(entry_fn=broken_entry)
    red1 = len(m1) > 0
    print(f"  [{'PASS' if red1 else 'FAIL'}] entry 永远 enter+写死坐标 -> 空列表守卫"
          + (f"红（{m1[0]}）" if red1 else "仍绿（守卫没抓到！）"))
    checks.append(red1)

    m2 = _entry_first_card_failures(entry_fn=broken_entry)
    red2 = len(m2) > 0
    print(f"  [{'PASS' if red2 else 'FAIL'}] entry 永远 enter+写死坐标 -> 第一张卡守卫"
          + (f"红（{m2[0]}）" if red2 else "仍绿（守卫没抓到！）"))
    checks.append(red2)

    # 破坏 2：has_stage_badge 恒真 -> 守卫 1、4 必须红（列表页被当成关卡列表）。
    always_badge = lambda _items: True  # noqa: E731
    m3 = _entry_empty_failures(badge_fn=always_badge)
    red3 = len(m3) > 0
    print(f"  [{'PASS' if red3 else 'FAIL'}] has_stage_badge 恒真 -> 空列表守卫"
          + (f"红（{m3[0]}）" if red3 else "仍绿（守卫没抓到！）"))
    checks.append(red3)

    m4 = _no_stale_accounting_failures(badge_fn=always_badge)
    red4 = len(m4) > 0
    print(f"  [{'PASS' if red4 else 'FAIL'}] has_stage_badge 恒真 -> 记账纪律守卫"
          + (f"红（{m4[0]}）" if red4 else "仍绿（守卫没抓到！）"))
    checks.append(red4)

    # 破坏 3：源码里摘掉「进入后复核徽标」的前置闸 -> 守卫 4 必须红。
    src = _agent_source()
    broken_src = src.replace("if not has_stage_badge(items1):", "if False:")
    if broken_src == src:
        print("  [FAIL] 找不到进入后复核的接线点（守卫已与实现脱节）")
        checks.append(False)
    else:
        m5 = _no_stale_accounting_failures(source=broken_src)
        red5 = len(m5) > 0
        print(f"  [{'PASS' if red5 else 'FAIL'}] 摘掉进入后徽标复核 -> 记账纪律守卫"
              + (f"红（{m5[0]}）" if red5 else "仍绿（守卫没抓到！）"))
        checks.append(red5)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "side-entry-empty-list-stops",
        "#51",
        "空「未通关」列表 -> entry_decision 明确收工并给出原因（绝不静默 hit=False、绝不盲点固定坐标）",
        probe_side_entry_empty_list_stops,
    ),
    (
        "side-entry-reads-first-card",
        "#51",
        "非空列表 -> 点【识别到的第一张卡标记框中心】（读后动），绝不写死固定坐标",
        probe_side_entry_reads_first_card,
    ),
    (
        "side-stage-advances-with-ledger",
        "#51",
        "真实关卡列表 -> select_side_stage 选出 STORY 行；记账后 is_done 成立、复选跳过（账本推进）",
        probe_side_stage_advances_with_ledger,
    ),
    (
        "side-no-stale-accounting",
        "#51",
        "记账只在【真正进入关卡列表（有 NEW/COMPLETE 徽标）】之后发生（与 #44 同一纪律）",
        probe_side_no_stale_accounting,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
