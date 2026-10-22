# -*- coding: utf-8 -*-
"""#31：归位状态机的三个真机缺口 —— 共斗房 / 列表页误判 / 超时不终止。

seam：
  · ``tools/live_harness.py`` 的归位有序表 ``RETURN_HOME_RULES``（页面 -> 动作分派）；
  · 主城判据 ``_is_main_city``（收紧为主城独有锚点）；
  · ``run_task_traced`` 的结束路径（``_terminate_task``：有界停止，绝不阻塞 ``post_stop().wait()``）。

三个缺口（真机战役、设备实证）
------------------------------
1. **不认识共斗房**（gap1）：Stage F 用 ``run_side_live.py`` 接力时，前一阶段把游戏留在
   幻想共斗房（真机帧 ``preF.png`` / ``disband.png`` / ``home_00.png``：房间号码 / 准备中： /
   未进行招募 / 队长；无底部导航，只有左下『返回』）→ ``[归位] step0: 未知页面，停手`` →
   没回主城 → 下一个任务起不来。
2. **危险误判**（gap2）：领主战列表页（真机帧 ``sweep_lord_02.png``）同时含 ``活动``
   （来自「活动进行中！」）与 ``领主战``，被 6 锚点「任意 ≥2」判成主城 → harness 在
   **没到家**时直接报「已在主城」返回 True、不点「主城」。
3. **超时不终止**（gap3）：Stage D 的 ``--timeout 900`` 到点后任务仍在跑 —— 旧实现的
   ``post_stop().wait()`` 在任务卡死时**永不返回**，runner 既没停掉任务、也没归还控制。

四个守卫（都在本文件里，prove-red 也在本文件里）
------------------------------------------------
* ``return-home-main-city-not-list-page`` —— 主城判据收紧：列表页不再是主城。
* ``return-home-list-page-to-main-city``  —— 列表页经 bottom_nav_mc 点「主城」回主城。
* ``return-home-coop-room``               —— 共斗房/解散确认框是已知页面，读后动（点『返回』/
  『解散』各自的框中心），并经「解散 → 列表页 → 主城」走到主城。
* ``runner-timeout-terminates``           —— 任务卡死时 ``run_task_traced`` 仍能按时归还控制。

★prove-red★（``python tools\\contract_hooks\\hooks_31.py``）：
  * 把主城判据倒回 6 锚点「任意 ≥2」 -> 列表页首命中变 main_city（守卫 1 红）；
  * 删掉 coop_room 规则 -> 共斗房首命中 None、走不到主城（守卫 3 红）；
  * 把超时结束倒回 ``post_stop().wait()`` -> 卡死场景下 runner 不归还控制（守卫 4 红）。
"""

from __future__ import annotations

import sys
import threading
import time as _time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★（同 hooks_20/24/28）：prove-red 用 PYTHONPATH 抢先塞坏副本时，
# 副本仍优先命中，不被真实的 live_harness 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

MAIN_CITY_RULE_ID = "main_city"
COOP_RULE_ID = "coop_room"

# ---------------------------------------------------------------------------
# 合成 OCR 帧（720 空间；照抄真机帧的判据）
# ---------------------------------------------------------------------------
#: 主城：三个独有锚点全中（真机帧 home.ocr.txt / homeD2.ocr.txt）。
MAIN_CITY_ITEMS: list[tuple[str, list[int]]] = [
    ("修行之道", [22, 728, 150, 41]),
    ("成长任务", [50, 368, 116, 33]),
    ("当前进度", [365, 928, 59, 20]),
    ("活动", [82, 1122, 59, 31]),
    ("关卡", [313, 1088, 93, 50]),
    ("领主战", [569, 1121, 79, 29]),
    ("主城", [157, 1248, 44, 25]),
]
#: 领主战列表页（真机帧 sweep_lord_02.ocr.txt）：`活动`（活动进行中！）+ `领主战` 会命中，
#: 但**没有**任何主城独有锚点 —— 旧 6 锚点「≥2」规则会把它误判成主城。
LIST_ITEMS: list[tuple[str, list[int]]] = [
    ("活动进行中！", [11, 301, 183, 32]),
    ("领主战", [135, 388, 90, 34]),
    ("领主战", [201, 453, 70, 28]),
    ("降临讨伐", [481, 389, 117, 32]),
    ("返回", [31, 1246, 45, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [276, 1246, 45, 27]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [635, 1245, 47, 31]),
]
#: 共斗房（真机帧 preF.ocr.txt / disband.ocr.txt / home_00.ocr.txt）：房间号码 / 准备中： /
#: 未进行招募 / 队长；有『返回』(30,1246,46,26) 无底部导航。
ROOM_ITEMS: list[tuple[str, list[int]]] = [
    ("房间号码", [276, 1184, 94, 28]),
    ("准备中：", [75, 274, 71, 28]),
    ("未进行招募", [307, 286, 104, 28]),
    ("队长", [31, 410, 35, 20]),
    ("挑战", [297, 906, 81, 46]),
    ("招募", [352, 808, 72, 41]),
    ("返回", [30, 1246, 46, 26]),
]
#: 「解散房间 可以吗？」确认框（真机帧 dlg2.ocr.txt / home_05.ocr.txt）。
DIALOG_ITEMS: list[tuple[str, list[int]]] = [
    ("解散房间", [300, 536, 118, 37]),
    ("可以吗？", [300, 573, 106, 37]),
    ("取消", [164, 805, 63, 36]),
    ("解散", [489, 802, 66, 42]),
    ("房间号码", [276, 1182, 94, 30]),
    ("挑战→", [297, 905, 156, 47]),
    ("返回", [30, 1245, 45, 27]),
]
#: 离开房间后落到的列表页（真机帧 disband2.ocr.txt）：有底部导航『主城』。
LEFT_LIST_ITEMS: list[tuple[str, list[int]]] = [
    ("主城", [156, 1245, 45, 28]),
    ("返回", [30, 1246, 46, 26]),
    ("领主战", [201, 453, 70, 28]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 房间页『返回』框中心。
EXPECTED_ROOM_BACK = (53, 1259)      # [30,1246,46,26] 的中心
#: 确认框『解散』框中心。
EXPECTED_DIALOG_CONFIRM = (522, 823)  # [489,802,66,42] 的中心


# ---------------------------------------------------------------------------
# 有序表的【唯一来源】：tools/live_harness.py
# ---------------------------------------------------------------------------
def rules() -> list:
    import live_harness as ca

    return [tuple(item) for item in ca.RETURN_HOME_RULES]


def _first_rule(rules_, items) -> str | None:
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


def trace(frames, rules_=None, max_steps: int = 12):
    """确定性走一遍归位状态机（画面按脚本推进）。返回 (是否到主城, 命中序列)。"""
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
        if rid == MAIN_CITY_RULE_ID:
            return True, seq
        i += 1
    return False, seq


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


def _loose_main_city(items) -> bool:
    """旧规则（#31 之前的 6 锚点「任意 ≥2」）—— 仅用于 prove-red 复现误判。"""
    import live_harness as ca

    hits = [
        a
        for a in ca.MAIN_CITY_ANCHORS
        if any(a in t for t in ca._texts(items))
    ]
    return len(hits) >= 2


# ---------------------------------------------------------------------------
# 守卫 1：主城判据不得被领主战列表页满足（#31 gap2）
# ---------------------------------------------------------------------------
def main_city_not_list_failures() -> list[str]:
    import live_harness as ca

    rules_ = rules()
    msgs: list[str] = []

    if not ca._is_main_city(MAIN_CITY_ITEMS):
        msgs.append("主城帧没有被判为主城（收紧过头）")
    if ca._is_main_city(LIST_ITEMS):
        msgs.append("领主战列表页被判成主城（危险误判仍在，#31 gap2）")

    first_list = _first_rule(rules_, LIST_ITEMS)
    if first_list == MAIN_CITY_RULE_ID:
        msgs.append("列表页首命中 main_city（归位会直接宣布「已在主城」、不点主城）")
    elif first_list != "bottom_nav_mc":
        msgs.append(f"列表页首命中应为 bottom_nav_mc（点主城回家），实际 {first_list!r}")

    if _first_rule(rules_, MAIN_CITY_ITEMS) != MAIN_CITY_RULE_ID:
        msgs.append("主城帧首命中不是 main_city")

    # 旧规则确实会在列表页误判（证明收紧是必要而非装饰）。
    if not _loose_main_city(LIST_ITEMS):
        msgs.append("旧 6 锚点规则竟不在列表页命中（prove-red 前提不成立）")
    return msgs


def probe_main_city_not_list() -> bool:
    return main_city_not_list_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：领主战列表页经 bottom_nav_mc -> 主城
# ---------------------------------------------------------------------------
def probe_list_page_to_main_city() -> bool:
    reached, seq = trace([LIST_ITEMS, MAIN_CITY_ITEMS])
    if not reached or seq != ["bottom_nav_mc", MAIN_CITY_RULE_ID]:
        return False
    # 旧规则：列表页首命中 main_city，一步就「到主城」= 误判（不点主城）。
    old_rules = [
        (MAIN_CITY_RULE_ID, _loose_main_city, _act_for(rules(), MAIN_CITY_RULE_ID)),
        *[r for r in rules() if r[0] != MAIN_CITY_RULE_ID],
    ]
    old_reached, old_seq = trace([LIST_ITEMS, MAIN_CITY_ITEMS], old_rules)
    return old_reached and old_seq == [MAIN_CITY_RULE_ID]


# ---------------------------------------------------------------------------
# 守卫 3：共斗房是已知页面 + 读后动 + 到主城（#31 gap1）
# ---------------------------------------------------------------------------
def coop_room_failures() -> list[str]:
    import live_harness as ca

    rules_ = rules()
    msgs: list[str] = []

    if COOP_RULE_ID not in [r[0] for r in rules_]:
        msgs.append("有序表缺少 coop_room 规则（共斗房仍是未知页面 -> 停手）")
        return msgs

    if not ca._is_coop_room(ROOM_ITEMS):
        msgs.append("共斗房帧没有被认出（gap1 未修）")
    if not ca._is_coop_room(DIALOG_ITEMS):
        msgs.append("「解散房间」确认框没有被认成共斗房子状态")
    # 不抢：主城 / 列表页不被 coop_room 命中。
    if ca._is_coop_room(MAIN_CITY_ITEMS):
        msgs.append("coop_room 判据误命中主城帧")
    if ca._is_coop_room(LIST_ITEMS):
        msgs.append("coop_room 判据误命中领主战列表页")

    if _first_rule(rules_, ROOM_ITEMS) != COOP_RULE_ID:
        msgs.append(f"共斗房首命中应为 coop_room，实际 {_first_rule(rules_, ROOM_ITEMS)!r}")
    if _first_rule(rules_, DIALOG_ITEMS) != COOP_RULE_ID:
        msgs.append(f"解散确认框首命中应为 coop_room，实际 {_first_rule(rules_, DIALOG_ITEMS)!r}")

    # 读后动：只点识别到的框中心（『返回』/『解散』），绝不盲点。
    room_point = _click_point_for(ROOM_ITEMS, COOP_RULE_ID, rules_)
    if room_point != EXPECTED_ROOM_BACK:
        msgs.append(f"共斗房应点『返回』框中心 {EXPECTED_ROOM_BACK}，实际 {room_point}")
    dlg_point = _click_point_for(DIALOG_ITEMS, COOP_RULE_ID, rules_)
    if dlg_point != EXPECTED_DIALOG_CONFIRM:
        msgs.append(f"确认框应点『解散』框中心 {EXPECTED_DIALOG_CONFIRM}，实际 {dlg_point}")
    return msgs


def probe_coop_room() -> bool:
    return coop_room_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：共斗房 ->（返回/解散）-> 列表页 ->（主城）-> 主城
# ---------------------------------------------------------------------------
def probe_coop_room_to_main_city() -> bool:
    reached, seq = trace([ROOM_ITEMS, DIALOG_ITEMS, LEFT_LIST_ITEMS, MAIN_CITY_ITEMS])
    if not reached or seq != [COOP_RULE_ID, COOP_RULE_ID, "bottom_nav_mc", MAIN_CITY_RULE_ID]:
        return False
    # 旧形态（无 coop_room）：共斗房首命中 None = 停手 = 留在房间（复现 #31 gap1）。
    old_rules = [r for r in rules() if r[0] != COOP_RULE_ID]
    old_reached, old_seq = trace(
        [ROOM_ITEMS, DIALOG_ITEMS, LEFT_LIST_ITEMS, MAIN_CITY_ITEMS], old_rules
    )
    return (not old_reached) and old_seq == [None]


# ---------------------------------------------------------------------------
# 守卫 5：超时到点真正终止并归还控制（#31 gap3）
# ---------------------------------------------------------------------------
class _FakeJob:
    job_id = 1

    @property
    def done(self) -> bool:
        return False

    @property
    def status(self):
        class _S:
            succeeded = False
            failed = False
            running = True
            pending = False
            done = False

        return _S()


class _FakeStopJob:
    """post_stop() 返回的 Job：wait() 永不返回（模拟任务卡死时旧实现阻塞，#31 gap3）。"""

    def wait(self):
        threading.Event().wait()  # 永不 set
        return self


class _FakeTasker:
    def __init__(self, stop_works: bool = False) -> None:
        self.stop_calls = 0
        self._stop_works = stop_works
        self._running = True

    def post_task(self, entry, override=None):
        return _FakeJob()

    def get_task_detail(self, tid):
        return None

    def post_stop(self):
        self.stop_calls += 1
        if self._stop_works:
            self._running = False
        return _FakeStopJob()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stopping(self) -> bool:
        return False


def _capture(fn, budget: float):
    """在后台线程跑 fn，join(budget)；返回 (是否完成, {'value'/'error'})。"""
    box: dict = {}

    def _run():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = repr(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(budget)
    return (not t.is_alive()), box


def _real_runner(fake):
    import live_harness as ca

    return ca.run_task_traced(
        fake, "Entry", {}, 0.3, "probe", watcher=None, stop_timeout=0.4
    )


def _broken_runner(fake):
    """旧 #31 形态：结束路径阻塞在 post_stop().wait()。"""
    fake.post_stop().wait()
    return ("timeout", [])


def timeout_failures(runner=_real_runner) -> list[str]:
    msgs: list[str] = []
    fake = _FakeTasker(stop_works=False)  # 任务卡死：停止请求不会让它停
    completed, box = _capture(lambda: runner(fake), budget=8.0)
    if not completed:
        msgs.append(
            "run_task_traced 在任务卡死时【没有归还控制】（疑似 post_stop().wait() 阻塞，#31 gap3）"
        )
        return msgs
    if "error" in box:
        msgs.append(f"run_task_traced 抛异常：{box['error']}")
        return msgs
    status = box.get("value", (None, []))[0]
    if status != "timeout":
        msgs.append(f"卡死任务应报 status=timeout，实际 {status!r}")
    if fake.stop_calls < 1:
        msgs.append("超时后没有发出任何停止请求（任务会继续裸奔）")
    return msgs


def probe_timeout_terminates() -> bool:
    return timeout_failures(_real_runner) == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_31.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    print("hooks_31 prove-red：三处破坏，要求守卫各自变红")
    green = (
        probe_main_city_not_list() is True
        and probe_list_page_to_main_city() is True
        and probe_coop_room() is True
        and probe_coop_room_to_main_city() is True
        and probe_timeout_terminates() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：列表页非主城 / 共斗房可回主城 / 超时归还控制（绿）")
    if not green:
        return False

    # (a) 主城判据倒回 6 锚点「任意 ≥2」 -> 列表页首命中 main_city（守卫 1 红）。
    loose_rules = [
        (MAIN_CITY_RULE_ID, _loose_main_city, _act_for(rules(), MAIN_CITY_RULE_ID)),
        *[r for r in rules() if r[0] != MAIN_CITY_RULE_ID],
    ]
    first = _first_rule(loose_rules, LIST_ITEMS)
    red_a = first == MAIN_CITY_RULE_ID
    print(f"  [{'PASS' if red_a else 'FAIL'}] 主城判据倒回 6 锚点 -> "
          f"列表页首命中={first!r}（{'红' if red_a else '仍绿'}）")

    # (b) 删掉 coop_room -> 共斗房首命中 None、走不到主城（守卫 3 红）。
    without = [r for r in rules() if r[0] != COOP_RULE_ID]
    first_room = _first_rule(without, ROOM_ITEMS)
    reached_wo, seq_wo = trace([ROOM_ITEMS, DIALOG_ITEMS, LEFT_LIST_ITEMS, MAIN_CITY_ITEMS], without)
    red_b = first_room is None and reached_wo is False and seq_wo == [None]
    tail = f"  共斗房首命中={first_room!r}，回归序列={seq_wo}" if not red_b else ""
    print(f"  [{'PASS' if red_b else 'FAIL'}] 删掉 coop_room -> "
          f"{'红' if red_b else '仍绿'}{tail}")

    # (c) 超时结束倒回 post_stop().wait() -> 卡死场景不归还控制（守卫 4 红）。
    red_c = timeout_failures(_broken_runner) != []
    print(f"  [{'PASS' if red_c else 'FAIL'}] 超时结束倒回 post_stop().wait() -> "
          f"{'红' if red_c else '仍绿'}")

    ok = green and red_a and red_b and red_c
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-main-city-not-list-page",
        "#31",
        "主城判据收紧为主城独有锚点：领主战列表页（活动+领主战）不再被判成主城",
        probe_main_city_not_list,
    ),
    (
        "return-home-list-page-to-main-city",
        "#31",
        "领主战列表页经 bottom_nav_mc 点『主城』回家；旧规则会一步误判到主城",
        probe_list_page_to_main_city,
    ),
    (
        "return-home-coop-room",
        "#31",
        "归位认识共斗房（房间号码/准备中/未进行招募/队长）及其解散确认框，读后动、不盲点",
        probe_coop_room,
    ),
    (
        "return-home-coop-room-to-main-city",
        "#31",
        "共斗房 ->（返回/解散）-> 列表页 ->（主城）-> 主城；旧形态在房间停手",
        probe_coop_room_to_main_city,
    ),
    (
        "runner-timeout-terminates",
        "#31",
        "run_task_traced 超时/停手时有界停止并归还控制（绝不阻塞 post_stop().wait()）",
        probe_timeout_terminates,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
