# -*- coding: utf-8 -*-
"""离线单测：幻想连战「按套数收工」记账与出口判定。

不需要游戏、不需要 AgentServer。直接跑：

    .venv\\Scripts\\python.exe tools\\test_phantom_sets.py

覆盖（对应需求）：
  1. 账本 key = ``phantom/set/{套号}/stage/{关号}``，能区分「套数」与「套内关号」；
  2. 完成第 15 关 = 一套结束 → 套计数 +1，且【未达目标套数时 PhantomDone 不命中
     （不 StopTask）】；
  3. 达到目标套数 → PhantomDone 命中（StopTask），并写收工标记；
  4. 跨重开恢复：账本保留时 _recover_counters 能接着未完成的套（不重复打已完成套）；
  5. 上一轮已收工（有收工标记）→ 新任务自动清账，从第 1 套开始。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
sys.path.insert(0, str(AGENT_DIR))

import progress as ledger  # noqa: E402
import phantom_impl as ph  # noqa: E402

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# 一帧「幻想连战关卡选择页」的 OCR 项（能让 classify() 判为 phantom_main）。
MAIN_ITEMS = [
    ("不可续战", [300, 980, 90, 30]),
    ("推荐编成", [55, 1105, 97, 29]),
    ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
    ("第3关", [345, 131, 90, 30]),
    ("战斗", [300, 700, 60, 30]),
]


class _TaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class _Argv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = _TaskDetail(task_id)
        self.custom_recognition_param = json.dumps(param)


def _force_new_task(ledger_path: Path) -> None:
    """把账本指到临时文件，并让下一次 analyze 视为「新任务」。"""
    ledger.set_file(ledger_path)
    ph._SESSION["task_id"] = None


def _use_main_frame() -> None:
    ph._ocr = lambda context, image, entry="OcrTask": list(MAIN_ITEMS)


def _simulate_settle(cur_set: int, cur_stage: int = ph.MAX_STAGES) -> None:
    """模拟「打完套内第 cur_stage 关」的结算帧（直接驱动 _observe 记账）。"""
    with ph._LOCK:
        ph._SESSION["cur_set"] = cur_set
        ph._SESSION["cur_stage"] = cur_stage
        ph._SESSION["in_fight"] = True
        ph._SESSION["last_state"] = None      # 强制本帧不被去重守卫拦掉
        ph._SESSION["last_observe_ts"] = 0.0
    ph._observe("phantom_settle", {}, [])


def _done_hit(task_id: int, target_sets: int):
    """跑一次 PhantomDoneRecognition.analyze，返回 (hit, detail)。"""
    _use_main_frame()
    res = ph.PhantomDoneRecognition().analyze(
        None, _Argv(task_id, {"ocr_entry": "OcrTask", "target_sets": target_sets})
    )
    return res.box == [0, 0, 0, 0], res.detail


# ---------------------------------------------------------------------------
# 进度重置（游戏机制）测试用辅助
# ---------------------------------------------------------------------------
def _main_items(stage: int):
    """一帧【关卡选择页】的 OCR 项，画面显示「第 stage 关」（能判为 phantom_main）。"""
    return [
        ("不可续战", [300, 980, 90, 30]),
        ("推荐编成", [55, 1105, 97, 29]),
        ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
        (f"第{stage}关", [345, 131, 90, 30]),
        ("战斗", [300, 700, 60, 30]),
    ]


def _force_observe() -> None:
    """绕过 _observe 的「同状态 1.2s 去重」守卫，保证本帧一定被处理。"""
    with ph._LOCK:
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0


def _observe_main(task_id: int, stage: int) -> None:
    """模拟一帧【关卡选择页 第 stage 关】经真实识别器 phantom_state 流入 _observe。"""
    _force_observe()
    ph._ocr = lambda context, image, entry="OcrTask": list(_main_items(stage))
    ph.PhantomStateRecognition().analyze(
        None, _Argv(task_id, {"ocr_entry": "OcrTask"})
    )


def _play_stage(task_id: int, stage: int, cur_set=None) -> None:
    """模拟一关的完整时序：关卡选择页第 stage 关 -> 进战斗 -> 结算记账。"""
    _observe_main(task_id, stage)
    with ph._LOCK:
        if cur_set is not None:
            ph._SESSION["cur_set"] = cur_set
        ph._SESSION["in_fight"] = True
        ph._SESSION["cur_stage"] = stage
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0
    ph._observe("phantom_settle", {}, [])


def _snap() -> dict:
    """会话关键计数 + phantom/set 账本快照（便于贴原始证据）。"""
    with ph._LOCK:
        sess = {
            "cur_set": ph._SESSION["cur_set"],
            "cur_stage": ph._SESSION["cur_stage"],
            "max_done": ph._SESSION["max_done"],
            "completed_sets": ph._SESSION["completed_sets"],
        }
    return {"session": sess, "set_keys": ledger.scope("phantom/set")}


def _stage_keys(set_no: int) -> set:
    """某套的 stage/* 账目集合（不含 completed 标记，便于断言无跳号/串套）。"""
    return {k for k in ledger.scope(f"phantom/set/{int(set_no)}") if "/stage/" in k}


def _all_stages(set_no: int) -> set:
    return {ph._stage_key(set_no, s) for s in range(1, ph.MAX_STAGES + 1)}


def test_normal_sequential_completes() -> None:
    print("\n== 6. 正常：set1 逐关记到 stage/7 -> stage/15 -> 套计数 +1 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        for st in range(1, 16):
            _play_stage(6006, st)
        with ph._LOCK:
            cs = ph._SESSION["completed_sets"]
            cur = ph._SESSION["cur_set"]
        keys = _stage_keys(1)
        check("set1 依次记满 stage/1..15（无跳号/串套）",
              keys == _all_stages(1), f"stage_keys={sorted(keys)}")
        check("写入了显式完成标记 phantom/set/1/completed",
              ledger.is_done(ph._set_done_key(1)) is True)
        check("完成 15 关 -> 套计数 +1", cs == 1, f"completed_sets={cs}")
        check("cur_set 前进到第 2 套", cur == 2, f"cur_set={cur}")
        print(f"   快照：{_snap()}")


def test_reset_voids_current_set() -> None:
    print("\n== 7. ★重置★：set1 记到 stage/7 -> 画面回第 1 关 -> 本套账目作废、从头记 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        ledger.mark_done("side_story/无关账目")  # 其它场景账目：重置绝不能误清
        for st in range(1, 8):
            _play_stage(7007, st)
        before = _snap()
        print(f"   重置前：{before}")
        check("重置前 set1 记到第 7 关（max_done=7）",
              before["session"]["max_done"] == 7, f"{before['session']}")

        # 画面回到第 1 关（游戏重置）
        _observe_main(7007, 1)
        after = _snap()
        print(f"   重置后：{after}")
        check("重置判据命中：本套 stage/2..7 账目被清空",
              ledger.scope("phantom/set/1") == [], f"{after['set_keys']}")
        check("重置后 max_done 归零、cur_stage 回到 1",
              after["session"]["max_done"] == 0 and after["session"]["cur_stage"] == 1,
              f"{after['session']}")
        check("重置只作废本套：套计数不变（仍 0）",
              after["session"]["completed_sets"] == 0, f"{after['session']}")
        check("重置不误清其它场景账目（side_story 仍在）",
              ledger.is_done("side_story/无关账目") is True)
        _observe_main(7007, 1)  # 再来一帧第 1 关，验证清账幂等、不误清 side
        check("重复第 1 关帧不会误清其它场景账目",
              ledger.is_done("side_story/无关账目") is True)

        # 从第 1 关重新记
        _play_stage(7007, 1)
        check("重置后从 stage/1 重新记账",
              ledger.is_done(ph._stage_key(1, 1)) is True)

        # 打到第 14 关都不能算一套完成
        for st in range(2, 15):
            _play_stage(7007, st)
        with ph._LOCK:
            cs14 = ph._SESSION["completed_sets"]
            mx14 = ph._SESSION["max_done"]
        check("★完成第 15 关之前套计数不增加（1..14 关时仍 0）",
              cs14 == 0, f"completed_sets={cs14} max_done={mx14}")
        check("套完成标记此时不存在",
              ledger.is_done(ph._set_done_key(1)) is False)

        # 第 15 关 -> 才算一套完成
        _play_stage(7007, 15)
        with ph._LOCK:
            cs15 = ph._SESSION["completed_sets"]
        check("★重新连续打到第 15 关才 +1 套", cs15 == 1, f"completed_sets={cs15}")
        check("完成后写入 phantom/set/1/completed",
              ledger.is_done(ph._set_done_key(1)) is True)
        keys = _stage_keys(1)
        check("重新打完后 set1 为完整连续 stage/1..15",
              keys == _all_stages(1), f"stage_keys={sorted(keys)}")


def test_next_set_stage1_not_reset() -> None:
    print("\n== 8. ★不误伤★：正常进入 set2 第 1 关不得被当成重置 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        for st in range(1, 16):
            _play_stage(8008, st)
        # 模拟上一套的残留帧：仍显示第 15 关（若拿 cur_stage 当判据就会误判）
        _observe_main(8008, 15)
        before = _snap()
        print(f"   残留第15关后：{before}")

        # 正常进入 set2 第 1 关
        _observe_main(8008, 1)
        after = _snap()
        print(f"   进入 set2 第1关后：{after}")
        check("★set2 第 1 关没有被判成重置：set1 账目完好",
              ledger.is_done(ph._stage_key(1, 15)) is True and
              len(ledger.scope("phantom/set/1")) == 16,
              f"set1_keys={ledger.scope('phantom/set/1')}")
        check("已完成套数保持 1、cur_set 保持 2",
              after["session"]["completed_sets"] == 1 and
              after["session"]["cur_set"] == 2, f"{after['session']}")
        check("set2 第 1 关不被当作「本套已有更后进度」",
              after["session"]["max_done"] == 0, f"{after['session']}")

        # 正常把 set2 第 1 关打完
        _play_stage(8008, 1)
        check("set2 正常从 stage/1 开始记账",
              ledger.is_done(ph._stage_key(2, 1)) is True)
        check("set1 的完成标记未被动过",
              ledger.is_done(ph._set_done_key(1)) is True)


def test_reset_only_touches_current_set() -> None:
    print("\n== 9. 重置只清当前套：set1/set2 已完成，set3 中途重置不动它们 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        for st in range(1, 16):
            _play_stage(9009, st)
        for st in range(1, 16):
            _play_stage(9009, st)
        with ph._LOCK:
            cs = ph._SESSION["completed_sets"]
        check("先打满 set1 + set2（completed_sets=2）", cs == 2, f"completed_sets={cs}")
        # 第 3 套打到第 4 关
        for st in range(1, 5):
            _play_stage(9009, st)
        # 重置回第 1 关
        _observe_main(9009, 1)
        with ph._LOCK:
            cs2 = ph._SESSION["completed_sets"]
            cur2 = ph._SESSION["cur_set"]
        check("重置后 set3 账目被清空", ledger.scope("phantom/set/3") == [],
              f"set3={ledger.scope('phantom/set/3')}")
        check("★set1 / set2 已完成套毫发无损",
              ledger.is_done(ph._set_done_key(1)) is True and
              ledger.is_done(ph._set_done_key(2)) is True and
              ledger.is_done(ph._stage_key(1, 15)) is True and
              ledger.is_done(ph._stage_key(2, 15)) is True)
        check("套计数保持 2、cur_set 保持 3",
              cs2 == 2 and cur2 == 3, f"completed_sets={cs2} cur_set={cur2}")
        # 第 3 套重打满 -> 3 套
        for st in range(1, 16):
            _play_stage(9009, st)
        with ph._LOCK:
            cs3 = ph._SESSION["completed_sets"]
        check("第 3 套重打满第 15 关 -> 套计数 3",
              cs3 == 3, f"completed_sets={cs3}")


def test_key_and_target() -> None:
    print("\n== 1. 账本 key / 目标套数解析 ==")
    check("set 3 stage 7 -> phantom/set/3/stage/7",
          ph._stage_key(3, 7) == "phantom/set/3/stage/7")
    check("target_sets 缺省 = 1", ph._read_target({}) == 1)
    check('target_sets "4"（字符串）解析为 4', ph._read_target({"target_sets": "4"}) == 4)
    check("target_sets 4（JSON 数字）解析为 4", ph._read_target({"target_sets": 4}) == 4)
    check("target_sets 非法（0/负/空）兜底为 1",
          ph._read_target({"target_sets": "0"}) == 1
          and ph._read_target({"target_sets": -2}) == 1
          and ph._read_target({"target_sets": ""}) == 1)


def test_run_until_target() -> None:
    print("\n== 2. 完成 15 关 = 一套结束，未达目标不收工；达到目标才 StopTask ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)

        target = 3
        print(f"   目标套数 = {target}")
        hit, detail = _done_hit(1001, target)
        check("起始：0 套 -> PhantomDone 不命中（不收工）",
              hit is False and detail["completed_sets"] == 0, f"detail={detail}")

        # ---- 第 1 套：逐关打到第 15 关 ----
        _simulate_settle(cur_set=1, cur_stage=15)
        with ph._LOCK:
            cs = ph._SESSION["completed_sets"]
            cur = ph._SESSION["cur_set"]
        check("完成第 1 套：套计数 +1", cs == 1, f"completed_sets={cs}")
        check("cur_set 前进到第 2 套", cur == 2, f"cur_set={cur}")
        check("账本出现真实记录 phantom/set/1/stage/15",
              ledger.is_done("phantom/set/1/stage/15") is True)
        check("结算页后续帧不会把 15 错记到下一套",
              ledger.is_done("phantom/set/2/stage/15") is False)

        hit, detail = _done_hit(1001, target)
        check("★完成 15 关但未达目标（1/3）：PhantomDone 仍不命中（不 StopTask）",
              hit is False and detail["completed_sets"] == 1, f"detail={detail}")
        check("未达目标时没有写收工标记", ledger.is_done(ph.RUN_DONE_KEY) is False)

        # ---- 第 2 套 ----
        _simulate_settle(cur_set=2, cur_stage=15)
        hit, detail = _done_hit(1001, target)
        check("完成第 2 套（2/3）：仍不命中", hit is False and detail["completed_sets"] == 2,
              f"detail={detail}")

        # ---- 第 3 套：达到目标 ----
        _simulate_settle(cur_set=3, cur_stage=15)
        hit, detail = _done_hit(1001, target)
        check("★达到目标（3/3）：PhantomDone 命中 -> StopTask",
              hit is True and detail["completed_sets"] == 3, f"detail={detail}")
        check("收工后写入收工标记 phantom/run/completed",
              ledger.is_done(ph.RUN_DONE_KEY) is True)


def test_default_one_set() -> None:
    print("\n== 3. 默认 1 套：打完 15 关就收工（保持旧行为） ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        _done_hit(2002, 1)  # 先触发一次 sync，建立干净会话
        _simulate_settle(cur_set=1, cur_stage=15)
        hit, detail = _done_hit(2002, 1)
        check("目标 1 套 + 完成 1 套 -> 命中", hit is True and detail["completed_sets"] == 1,
              f"detail={detail}")


def test_resume_across_restart() -> None:
    print("\n== 4. 跨重开恢复：保留账本，接着未完成的套继续 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)  # 先把账本指到临时文件，再写入「上一轮的进度」
        # 模拟上一轮：第 1 套全部 15 关已完成 + 第 2 套打到第 7 关，然后进程重开。
        for s in range(1, ph.MAX_STAGES + 1):
            ledger.mark_done(ph._stage_key(1, s))
        for s in range(1, 8):
            ledger.mark_done(ph._stage_key(2, s))
        ledger.mark_done("side_story/无关账目")  # 其它场景账目不能被误清

        sets = ph._scan_sets()
        check("_scan_sets 读出 {1:15, 2:7}", sets == {1: 15, 2: 7}, f"sets={sets}")

        hit, detail = _done_hit(3003, 3)
        with ph._LOCK:
            cs = ph._SESSION["completed_sets"]
            cur = ph._SESSION["cur_set"]
            mx = ph._SESSION["max_done"]
        check("恢复：已完成 1 套", cs == 1, f"completed_sets={cs}")
        check("恢复：当前第 2 套", cur == 2, f"cur_set={cur}")
        check("恢复：套内已到第 7 关", mx == 7, f"max_done={mx}")
        check("恢复后未达目标（1/3）-> 不命中", hit is False)
        check("恢复不清掉非 phantom 账目", ledger.is_done("side_story/无关账目") is True)


def test_resume_real_ledger_shape() -> None:
    """真实用户账本形态：两套带 completed 标记 + 第三套只到 stage/5 → 从第 3 套续跑。

    对应 <repo-旧线>\\wf-auto\\install\\progress.json（用户实跑产生的账本）：
      phantom/set/1/completed + stage/1..15
      phantom/set/2/completed + stage/1..15
      phantom/set/3/stage/1..5（未完成）
    期望恢复：已完成 2 套、当前第 3 套、套内已到第 5 关（→ 下次从第 3 套接着刷）。
    """
    print("\n== 4b. 真实账本形态（含 completed 标记）恢复 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        for s in range(1, ph.MAX_STAGES + 1):
            ledger.mark_done(ph._stage_key(1, s))
            ledger.mark_done(ph._stage_key(2, s))
        ledger.mark_done(ph._set_done_key(1))
        ledger.mark_done(ph._set_done_key(2))
        for s in range(1, 6):
            ledger.mark_done(ph._stage_key(3, s))

        hit, detail = _done_hit(3004, 9999999)
        with ph._LOCK:
            cs = ph._SESSION["completed_sets"]
            cur = ph._SESSION["cur_set"]
            mx = ph._SESSION["max_done"]
        check("恢复：已完成 2 套", cs == 2, f"completed_sets={cs}")
        check("恢复：当前第 3 套", cur == 3, f"cur_set={cur}")
        check("恢复：套内已到第 5 关", mx == 5, f"max_done={mx}")
        check("恢复后未达目标（2/9999999）-> 不命中（继续续跑）", hit is False)
        check("未完成套的 stage 账目未被清", ledger.is_done(ph._stage_key(3, 5)) is True)


def test_done_run_resets_next_task() -> None:
    print("\n== 5. 上一轮已收工（有标记）-> 新任务自动清账 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        for s in range(1, ph.MAX_STAGES + 1):
            ledger.mark_done(ph._stage_key(1, s))
        ledger.mark_done(ph.RUN_DONE_KEY)

        # _done_hit 会触发 _sync_task（新任务）→ 检测到收工标记 → 清账
        hit, detail = _done_hit(4004, 1)
        check("新任务检测到收工标记：账本已清空", ph._scan_sets() == {},
              f"scan={ph._scan_sets()}")
        check("清账后从第 1 套开始 -> 未达成 1 套前不命中",
              hit is False and detail["completed_sets"] == 0, f"detail={detail}")


# ---------------------------------------------------------------------------
# A. 中途接管（任务启动时游戏已在幻想连战里 → 接着打，不导航/不重开/不清账）
# ---------------------------------------------------------------------------
BATTLE_ITEMS = [
    ("时间 09:53", [300, 1200, 80, 30]),
    ("分数 0000001", [430, 1200, 120, 30]),
]
SETTLE_ITEMS = [
    ("QUESTRESULT", [180, 380, 360, 60]),
    ("OK", [330, 640, 60, 30]),
]


def _observe_as(task_id: int, state: str, stage: int | None = None) -> None:
    """模拟一帧指定状态经真实识别器 phantom_state 流入 _observe。"""
    if state == "phantom_main":
        items = _main_items(stage if stage is not None else 1)
    elif state == "phantom_battle":
        items = list(BATTLE_ITEMS)
    elif state == "phantom_settle":
        items = list(SETTLE_ITEMS)
    else:
        items = _main_items(stage if stage is not None else 1)
    _force_observe()
    ph._ocr = lambda context, image, entry="OcrTask": list(items)
    ph.PhantomStateRecognition().analyze(None, _Argv(task_id, {"ocr_entry": "OcrTask"}))


def _seed_set1(path: Path, upto: int) -> None:
    """账本指到临时文件，并预置 set1 stage/1..upto（模拟“上一次任务/游戏会话”的旧账本）。"""
    ledger.set_file(path)
    for s in range(1, upto + 1):
        ledger.mark_done(ph._stage_key(1, s))
    ph._SESSION["task_id"] = None  # 让下一次 analyze 视为新任务（接管）


def test_join_stage1_with_stale_ledger_no_clear() -> None:
    print("\n== A1. ★中途接管★：画面第 1 关 + 旧账本更靠后 → 绝不判重置/清账 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _seed_set1(path, 10)  # 旧账本 set1 已到第 10 关
        before = ledger.scope("phantom/set")

        _observe_as(501, "phantom_main", 1)   # 接管首帧：以画面第 1 关为准
        with ph._LOCK:
            sess = dict(ph._SESSION)
        after1 = ledger.scope("phantom/set")
        check("★接管首帧不判重置：旧账本 set1 一条不少",
              after1 == before, f"before={len(before)} after={len(after1)}")
        check("首次观察基准 = 画面第 1 关（joined_stage=1）",
              sess["joined_stage"] == 1 and sess["cur_stage"] == 1, f"{sess['joined_stage']}")
        check("会话进度 session_max_done=0（不拿旧账本充数）",
              sess["session_max_done"] == 0, f"{sess['session_max_done']}")

        _observe_as(501, "phantom_main", 1)   # 再来一帧第 1 关
        check("★非首帧、会话尚无进度：仍不清账（旧账本完好）",
              ledger.scope("phantom/set") == before)

        # 打完第 1 关（会话进度=1，<2）→ 回第 1 关仍不清
        _play_stage(501, 1)
        _observe_as(501, "phantom_main", 1)
        check("会话仅在套内打到第 1 关（进度 1<2）→ 不误判重置",
              ledger.scope("phantom/set/1") == before)

        # 本次会话真正打到第 2 关后再回第 1 关 → 才是游戏重置 → 清当前套
        _play_stage(501, 2)
        _observe_as(501, "phantom_main", 1)
        check("★会话确实打到第 2 关后回第 1 关 → 判重置并只清当前套",
              ledger.scope("phantom/set/1") == [], f"{ledger.scope('phantom/set/1')}")


def test_join_stage3_with_stale_ledger_continues() -> None:
    print("\n== A2. ★中途接管★：画面第 3 关 + 旧账本更靠后 → 接着第 3 关打、不清账 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _seed_set1(path, 6)
        before = ledger.scope("phantom/set")

        _observe_as(502, "phantom_main", 3)
        with ph._LOCK:
            joined = ph._SESSION["joined_stage"]
            cur = ph._SESSION["cur_stage"]
            smx = ph._SESSION["session_max_done"]
        check("接管到第 3 关：joined_stage=3 / cur_stage=3（以画面为准，不回第 1 关）",
              joined == 3 and cur == 3, f"joined={joined} cur={cur}")
        check("旧账本未被动过", ledger.scope("phantom/set") == before)

        # 第 3 关打完 → 会话进度=3；账本应保持（第 3 关旧账已有 → 不重复记）
        _play_stage(502, 3)
        with ph._LOCK:
            smx2 = ph._SESSION["session_max_done"]
        check("第 3 关结算：会话进度推进到 3", smx2 == 3, f"{smx2}")
        check("旧账本仍完好（接管不重开、不清账）",
              ledger.scope("phantom/set") == before)
        check("接管后不会回落第 1 关（第 1 关未被重新触发/清账）",
              ledger.is_done(ph._stage_key(1, 5)) is True)


def test_join_battle_and_settle() -> None:
    print("\n== A3. ★中途接管★：在战斗中 / 在结算页 → 不清账 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _seed_set1(path, 5)
        before = ledger.scope("phantom/set")

        _observe_as(503, "phantom_battle")
        with ph._LOCK:
            in_fight = ph._SESSION["in_fight"]
        check("战斗中接管：标记 in_fight=True", in_fight is True)
        check("战斗中接管：旧账本完好", ledger.scope("phantom/set") == before)

        _observe_as(503, "phantom_settle")   # cur_stage 仍为 None，不应误记/误清
        check("结算页接管：旧账本完好（不清账）", ledger.scope("phantom/set") == before)

        # 结算后回到关卡选择页第 4 关：正常继续
        _observe_as(503, "phantom_main", 4)
        with ph._LOCK:
            cur = ph._SESSION["cur_stage"]
        check("接管后继续：关卡选择页第 4 关被识别", cur == 4, f"cur={cur}")
        check("全程未清账", ledger.scope("phantom/set") == before)


# ---------------------------------------------------------------------------
# B. 关卡上限（选项「打到第几关以后放弃」= stage_cap）
# ---------------------------------------------------------------------------
def _set_cap(cap: int) -> None:
    with ph._LOCK:
        ph._SESSION["stage_cap"] = cap


def _set_session_progress(n: int) -> None:
    with ph._LOCK:
        ph._SESSION["session_max_done"] = n


class _FakeCtx:
    def __init__(self):
        self.nexts = []

    def override_next(self, name, lst):
        self.nexts.append((name, list(lst)))
        return True


def test_read_stage_cap() -> None:
    print("\n== B1. stage_cap 解析：缺省/非法/越界 ==")
    check("缺省 = 0（不限制）", ph._read_stage_cap({}) == 0)
    check('"0" = 不限制', ph._read_stage_cap({"stage_cap": "0"}) == 0)
    check("非法 = 0（不限制）", ph._read_stage_cap({"stage_cap": "abc"}) == 0)
    check("负数 = 0（不限制）", ph._read_stage_cap({"stage_cap": -3}) == 0)
    check('"5" = 5', ph._read_stage_cap({"stage_cap": "5"}) == 5)
    check("越界 99 夹到 15", ph._read_stage_cap({"stage_cap": 99}) == ph.MAX_STAGES)


def test_stage_cap_single_mode() -> None:
    print("\n== B2. ★上限·单目标★：第 N 关打完 → PhantomDone 命中 → 收工 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        _done_hit(6006, 99)              # 先 sync 建立干净会话
        _simulate_settle(cur_set=1, cur_stage=5)   # 本会话实际打到第 5 关
        _set_cap(5)
        hit, detail = _done_hit(6006, 99)          # 同一 task_id，不会重置 cap
        check("★打到第 5 关（cap=5）→ 命中收工（reason=stage_cap）",
              hit is True and detail.get("reason") == "stage_cap"
              and detail.get("stage_cap") == 5, f"detail={detail}")
        check("未跑够目标套数也收工（上限与套数取先到者）",
              detail.get("completed_sets") == 0, f"detail={detail}")
        check("单目标收工写了 phantom/run/completed 收工标记",
              ledger.is_done(ph.RUN_DONE_KEY) is True)

        # cap 未到：不清不命中
        ledger.reset("phantom/run/completed")
        _set_cap(5)
        _set_session_progress(3)
        hit2, detail2 = _done_hit(6006, 99)
        check("会话只到第 3 关（cap=5）→ 不命中（继续打）",
              hit2 is False and "reason" not in detail2, f"detail={detail2}")


def test_stage_cap_default_no_limit() -> None:
    print("\n== B3. ★上限默认 0 = 不限制★：不改变旧行为 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        _done_hit(6007, 99)
        _simulate_settle(cur_set=1, cur_stage=15)
        _set_cap(0)                       # 不限制
        hit, detail = _done_hit(6007, 99)
        check("cap=0：仅凭关卡不会收工", hit is False and "reason" not in detail, f"detail={detail}")
        check("cap=0：也没写收工标记", ledger.is_done(ph.RUN_DONE_KEY) is False)


def test_stage_cap_batch_mode() -> None:
    print("\n== B4. ★上限·批量模式★：回指挥官走 SpecialBatchStop，不写收工标记 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        _use_main_frame()
        # 批量模式的 PhantomDone 参数（target_sets + mode=batch）
        argv0 = _Argv(6008, {"ocr_entry": "OcrTask", "target_sets": 9, "mode": "batch"})
        ph.PhantomDoneRecognition().analyze(None, argv0)   # sync
        _simulate_settle(cur_set=1, cur_stage=4)
        _set_cap(4)

        ctx = _FakeCtx()
        res = ph.PhantomDoneRecognition().analyze(ctx, argv0)
        check("批量模式 cap 命中（框有效）", res.box == [0, 0, 0, 0], f"box={res.box}")
        check("批量模式 cap：令 PhantomDispatch 走 SpecialBatchStop（回指挥官优雅收工）",
              ctx.nexts == [("PhantomDispatch", ["SpecialBatchStop"])], f"nexts={ctx.nexts}")
        check("批量模式【不】写 phantom/run/completed（保留套数统计）",
              ledger.is_done(ph.RUN_DONE_KEY) is False)


def test_stage_cap_target_first() -> None:
    print("\n== B5. ★上限与套数共存★：目标套数先达标 → 走原「套数收工」路径 ==")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.json"
        _force_new_task(path)
        _done_hit(6009, 1)
        _simulate_settle(cur_set=1, cur_stage=15)   # 完成 1 套（cs>=target=1）
        _set_cap(3)                                 # 上限 3 也已“超过”（会话到 15）
        hit, detail = _done_hit(6009, 1)
        check("目标套数先到 → 命中，且不是 stage_cap 分支",
              hit is True and detail.get("reason") != "stage_cap"
              and detail.get("completed_sets") == 1, f"detail={detail}")
        check("走原路径写了收工标记", ledger.is_done(ph.RUN_DONE_KEY) is True)


def main() -> None:
    print("=" * 72)
    print("离线单测：幻想连战按套数收工（phantom_impl + progress，不依赖游戏/AgentServer）")
    print("=" * 72)
    test_key_and_target()
    test_run_until_target()
    test_default_one_set()
    test_resume_across_restart()
    test_resume_real_ledger_shape()
    test_done_run_resets_next_task()
    test_normal_sequential_completes()
    test_reset_voids_current_set()
    test_next_set_stage1_not_reset()
    test_reset_only_touches_current_set()
    # A. 中途接管
    test_join_stage1_with_stale_ledger_no_clear()
    test_join_stage3_with_stale_ledger_continues()
    test_join_battle_and_settle()
    # B. 关卡上限
    test_read_stage_cap()
    test_stage_cap_single_mode()
    test_stage_cap_default_no_limit()
    test_stage_cap_batch_mode()
    test_stage_cap_target_first()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅（15 关=一套；重置按套作废；中途接管不误清账；关卡上限优雅收工）")


if __name__ == "__main__":
    main()
