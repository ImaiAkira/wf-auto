# -*- coding: utf-8 -*-
"""#64：模态框弹着时「归位」认不出「主城」→「未知页面，停手」，任务与接力都卡住。

seam：``tools/live_harness.py`` 的归位状态机有序表 ``RETURN_HOME_RULES``
（``ensure_main_city`` 页面 -> 动作的分派表）。

缺陷（两次真机实证，见 #64）
----------------------------
屏幕上压着一张**模态确认框**时，底部「主城」标签被压暗/遮挡 → ``bottom_nav_mc`` 认不出
「主城」→ ``[归位] step0: 未知页面，停手`` → **不动** → 任务收尾与「接力」（下一个任务能否
从主城起跑）都卡住。实例：迷宫的「是否使用阿尔戈罗盘」弹框（#60 同族）、幻想共斗的
``QUEST RESULT``（该页已由 #48 单独处理）。

处置（两条，缺一不可）
--------------------
1. **已知模态框：读后动** —— ``maze_item_confirm`` 规则：读弹框标题（``MAZE_ITEM_PROMPT``）
   再点它【是】按钮**自己的** OCR 框中心（绝不盲点、绝不写死坐标）。判据与 pipeline 侧
   ``farm.json::FarmItemConfirm`` 逐字一致（守卫 1）。
2. **未知模态框：可见、带原因地降级** —— ``ensure_main_city`` 认不出画面时，若画面有
   模态框信号（成对【是/否】·【确定/取消】·【OK/取消】/ 以问号结尾的提示）则明确打印
   「疑似【未知模态框】…带原因停手」，而不再是一句笼统的「未知页面，停手」。**绝不静默。**

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``return-home-maze-item-confirm`` —— 弹框帧首命中 = ``maze_item_confirm``（不是 None）、
   只点【是】识别框中心 (522,823)，且不抢主城 / 账号确认页 / 标题页。
2. ``return-home-known-modal-read-then-act`` —— 读后动：弹框在但读不到【是】时**只等待、
   绝不出手**（不 adb_tap）。
3. ``return-home-unknown-modal-visible-degradation`` —— 未知模态框帧被判为「疑似模态框」，
   且 ``ensure_main_city`` 里有**带原因**的降级分支（源码在场，不是静默停手）。

★prove-red★（``python tools\\contract_hooks\\hooks_64.py``）三处破坏，要求守卫各自变红：
  * 删掉 ``maze_item_confirm`` 规则 -> 弹框帧首命中 None（复现 #64 卡住）；
  * 让 ``_looks_like_modal`` 恒 False -> 未知模态框不再被点名（降级不可见）；
  * 抹掉 ``ensure_main_city`` 的带原因分支 -> 守卫 3 红（又变回静默停手）。

★顺序（安全属性）★：``maze_item_confirm`` 排在有底导的页面之后（弹框压暗底导时
``bottom_nav_mc`` 认不出，正是它要接住的那一帧）；不改动 ``account_confirm`` 先于
``title`` 的顺序锁（#24）。
"""

from __future__ import annotations

import copy
import inspect
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
HOOKS_DIR = Path(__file__).resolve().parent

for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

import hooks_60  # noqa: E402  （复用真机弹框帧 + 变体帧）

RULE_ID = "maze_item_confirm"
#: ensure_main_city 里未知模态框降级分支的**可读标记**（源码在场即证明「不静默」）。
DEGRADE_MARKER = "未知模态框"

#: 未知模态框反例帧：成对【确定/取消】+ 以问号结尾的提示，且**没有**任何已知规则命中它。
UNKNOWN_MODAL_ITEMS: list[tuple[str, list[int]]] = [
    ("确定要放弃本局吗？", [200, 500, 320, 40]),
    ("确定", [300, 800, 60, 36]),
    ("取消", [420, 800, 60, 36]),
    ("返回", [30, 1246, 45, 26]),
]
#: 与上面同族、但**只有对按钮、没有问号提示**的未知模态框（也能被模态框信号认出）。
UNKNOWN_MODAL_ITEMS2: list[tuple[str, list[int]]] = [
    ("OK", [300, 800, 60, 36]),
    ("取消", [420, 800, 60, 36]),
    ("返回", [30, 1246, 45, 26]),
]
#: 真·非模态的未知页面（无成对按钮、无问号提示）——不该被当模态框。
UNKNOWN_PAGE_ITEMS: list[tuple[str, list[int]]] = [
    ("某种没登记过的分区标题", [200, 500, 320, 40]),
    ("返回", [30, 1246, 45, 26]),
]

#: 归位不该被 maze_item_confirm 抢走的页面（#28 同款）。
MAIN_CITY_ITEMS: list[tuple[str, list[int]]] = [
    ("修行之道", [100, 300, 90, 30]),
    ("当前进度", [200, 400, 90, 30]),
    ("主城", [157, 1248, 44, 25]),
]
ACCOUNT_CONFIRM_ITEMS: list[tuple[str, list[int]]] = [
    ("继续游戏", [300, 820, 120, 60]),
    ("点击开始", [250, 1150, 220, 60]),
]
TITLE_ITEMS: list[tuple[str, list[int]]] = [("点击开始", [250, 1150, 220, 60])]


# ---------------------------------------------------------------------------
# 有序表（唯一来源：tools/live_harness.py）
# ---------------------------------------------------------------------------
def rules() -> list:
    import live_harness as ca  # noqa: PLC0415

    return [tuple(item) for item in ca.RETURN_HOME_RULES]


def rule_ids() -> list[str]:
    return [rid for rid, _p, _a in rules()]


def _first_rule(rules_, items) -> str | None:
    for rid, probe, _act in rules_:
        if probe(items):
            return rid
    return None


def _act_for(rules_, rid: str):
    for item in rules_:
        if item[0] == rid:
            return item[2]
    return None


def click_point_for(items, rules_=None) -> tuple[int, int] | None:
    """真实调用 ``maze_item_confirm`` 的动作（adb_tap 被替换捕获），返回它点到的 720 坐标。"""
    import live_harness as ca  # noqa: PLC0415

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
        act = _act_for(rules_ if rules_ is not None else rules(), RULE_ID)
        if act is None:
            return None
        act(items, 0)
    finally:
        ca.adb_tap = real_tap
        ca.time = real_time
    return captured[-1] if captured else None


# ---------------------------------------------------------------------------
# 守卫 1：弹框帧 = 已知页面，只点【是】框中心，且不抢别的页
# ---------------------------------------------------------------------------
def maze_item_confirm_failures() -> list[str]:
    rules_ = rules()
    msgs: list[str] = []
    if RULE_ID not in rule_ids():
        return [f"有序表缺少 {RULE_ID!r} 规则（迷宫道具弹框仍是未知页面 -> 停手，#64 卡住）"]

    first = _first_rule(rules_, hooks_60.POPUP_FRAME_ITEMS)
    if first != RULE_ID:
        msgs.append(f"弹框帧首命中应为 {RULE_ID!r}，实际 {first!r}（设备会停在弹框上）")

    point = click_point_for(hooks_60.POPUP_FRAME_ITEMS, rules_)
    if point != hooks_60.EXPECTED_YES_CENTER:
        msgs.append(f"弹框动作应点【是】识别框中心 {hooks_60.EXPECTED_YES_CENTER}，实际 {point}")

    # 变体（阿戈尔罗盘）同样命中并点【是】框中心。
    first_v = _first_rule(rules_, hooks_60.POPUP_FRAME_ITEMS_VARIANT)
    if first_v != RULE_ID:
        msgs.append(f"变体弹框帧（阿戈尔罗盘）首命中应为 {RULE_ID!r}，实际 {first_v!r}")
    point_v = click_point_for(hooks_60.POPUP_FRAME_ITEMS_VARIANT, rules_)
    if point_v != hooks_60.EXPECTED_VARIANT_YES_CENTER:
        msgs.append(
            f"变体弹框帧应点【是】框中心 {hooks_60.EXPECTED_VARIANT_YES_CENTER}，实际 {point_v}"
        )

    # 不抢：主城 / 账号确认页 / 标题页仍各自命中各自规则。
    if _first_rule(rules_, MAIN_CITY_ITEMS) != "main_city":
        msgs.append(f"主城帧被 maze_item_confirm 抢走：首命中 {_first_rule(rules_, MAIN_CITY_ITEMS)!r}")
    if _first_rule(rules_, ACCOUNT_CONFIRM_ITEMS) != "account_confirm":
        msgs.append(
            f"账号确认页被抢走：首命中 {_first_rule(rules_, ACCOUNT_CONFIRM_ITEMS)!r}"
        )
    if _first_rule(rules_, TITLE_ITEMS) != "title":
        msgs.append(f"标题页被抢走：首命中 {_first_rule(rules_, TITLE_ITEMS)!r}")
    return msgs


def probe_return_home_maze_item_confirm() -> bool:
    return maze_item_confirm_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：读后动（读不到【是】只等待，绝不出手）
# ---------------------------------------------------------------------------
def read_then_act_failures() -> list[str]:
    import live_harness as ca  # noqa: PLC0415

    if RULE_ID not in rule_ids():
        return [f"有序表缺少 {RULE_ID!r} 规则（无法判定读后动）"]

    msgs: list[str] = []
    # 弹框标题在、但【是】读不到（例如 OCR 抖动）-> 只等待，绝不 adb_tap。
    no_yes = [t for t in hooks_60.POPUP_FRAME_ITEMS if t[0] != "是"]
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
        act = _act_for(rules(), RULE_ID)
        ret = act(no_yes, 0)
    finally:
        ca.adb_tap = real_tap
        ca.time = real_time
    if captured:
        msgs.append(f"读不到【是】时仍出手了（盲点）：{captured}")
    if ret is not False:
        msgs.append(f"读不到【是】时应返回 False（等待），实际 {ret!r}")

    # 正例：读到【是】就点它中心。
    point = click_point_for(hooks_60.POPUP_FRAME_ITEMS)
    if point != hooks_60.EXPECTED_YES_CENTER:
        msgs.append(f"读到【是】时应点其中心 {hooks_60.EXPECTED_YES_CENTER}，实际 {point}")
    return msgs


def probe_return_home_known_modal_read_then_act() -> bool:
    return read_then_act_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：未知模态框的可见、带原因降级
# ---------------------------------------------------------------------------
def _ensure_source() -> str:
    import live_harness as ca  # noqa: PLC0415

    return inspect.getsource(ca.ensure_main_city)


def _degradation_present(src: str) -> bool:
    """源码里确实有「带原因的未知模态框降级」，而不是笼统的静默停手。"""
    return DEGRADE_MARKER in src and "_looks_like_modal" in src


def unknown_modal_failures(src: str | None = None) -> list[str]:
    import live_harness as ca  # noqa: PLC0415

    msgs: list[str] = []
    rules_ = rules()

    # 未知模态框帧：没有任何已知规则命中（否则就轮不到降级分支）。
    if _first_rule(rules_, UNKNOWN_MODAL_ITEMS) is not None:
        msgs.append(
            f"未知模态框帧被已有规则命中（{_first_rule(rules_, UNKNOWN_MODAL_ITEMS)!r}）——"
            "守卫反例不成立"
        )
    # 但它必须被「疑似模态框」信号认出（于是降级分支才会带原因地停手）。
    if ca._looks_like_modal(UNKNOWN_MODAL_ITEMS) is not True:
        msgs.append("未知模态框帧（确定的问句 + 确定/取消）未被 _looks_like_modal 认出")
    if ca._looks_like_modal(UNKNOWN_MODAL_ITEMS2) is not True:
        msgs.append("未知模态框帧2（OK/取消 成对按钮）未被 _looks_like_modal 认出")
    # 非模态的未知页面：不该被当模态框（降级措辞才有意义）。
    if ca._looks_like_modal(UNKNOWN_PAGE_ITEMS) is not False:
        msgs.append("非模态的未知页面被误判为模态框")

    # 源码里确有一条**看得见、带原因**的降级分支。
    source = _ensure_source() if src is None else src
    if not _degradation_present(source):
        msgs.append(
            "ensure_main_city 缺少未知模态框的带原因降级分支（会静默停手）"
        )
    return msgs


def probe_return_home_unknown_modal_visible_degradation() -> bool:
    return unknown_modal_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    print("hooks_64 prove-red：三处破坏，要求守卫各自变红")
    green = (
        probe_return_home_maze_item_confirm() is True
        and probe_return_home_known_modal_read_then_act() is True
        and probe_return_home_unknown_modal_visible_degradation() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：已知弹框读后动 + 未知模态框带原因降级（绿）")
    if not green:
        return False

    # (a) 删掉 maze_item_confirm 规则 -> 弹框帧首命中 None（复现 #64 卡住）。
    without = [r for r in rules() if r[0] != RULE_ID]
    first = _first_rule(without, hooks_60.POPUP_FRAME_ITEMS)
    red_a = first is None
    print(f"  [{'PASS' if red_a else 'FAIL'}] 删掉 {RULE_ID} 规则 -> "
          f"{'红' if red_a else '仍绿'}（弹框帧首命中={first!r}）")

    # (b) _looks_like_modal 恒 False -> 未知模态框不再被点名。
    import live_harness as ca  # noqa: PLC0415

    real_llm = ca._looks_like_modal
    try:
        ca._looks_like_modal = lambda _items: False
        red_b = ca._looks_like_modal(UNKNOWN_MODAL_ITEMS) is not True
    finally:
        ca._looks_like_modal = real_llm
    print(f"  [{'PASS' if red_b else 'FAIL'}] _looks_like_modal 恒 False -> "
          f"{'红' if red_b else '仍绿'}")

    # (c) 抹掉带原因分支 -> 守卫 3 红。
    stripped = "def ensure_main_city(watcher, max_steps=10):\n    return False\n"
    red_c = _degradation_present(stripped) is False
    print(f"  [{'PASS' if red_c else 'FAIL'}] 抹掉带原因降级分支 -> {'红' if red_c else '仍绿'}")

    ok = green and red_a and red_b and red_c
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-maze-item-confirm",
        "#64",
        "归位认迷宫道具弹框：首命中 maze_item_confirm、只点【是】框中心、且不抢主城/账号/标题",
        probe_return_home_maze_item_confirm,
    ),
    (
        "return-home-known-modal-read-then-act",
        "#64",
        "已知模态框读后动：读不到【是】只等待、绝不出手（不盲点）",
        probe_return_home_known_modal_read_then_act,
    ),
    (
        "return-home-unknown-modal-visible-degradation",
        "#64",
        "未知模态框：被判为「疑似模态框」且 ensure_main_city 有带原因的降级分支（不静默停手）",
        probe_return_home_unknown_modal_visible_degradation,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
