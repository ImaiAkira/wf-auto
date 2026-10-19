# -*- coding: utf-8 -*-
"""#74 的一张票守卫文件：★手操态以选项参数为权威源 + 零点击空转有界★（自动发现，零改既有文件）。

现场事实（真机 run 384，2026-10-16，多人模式）
------------------------------------------------
产品管线跑真机时 criterion 1 失败：**手操引擎连点 0 次，连续 455 次 0 次**。真实日志行
（每次各一条，共 455 组）：

    info:[wuchong_battle] 手操开始（直到结算 / 关卡失败才交还；无固定时长上限）…
    info:[wuchong_battle] 手操连点结束：共点弹板 0 次（技能 0 发，stopped=manual_off，…）

根因（已诊断，见 ``agent/wuchong_impl.py`` 的 #74 承重注释）：
  · 手操引擎的停止条件钩子 ``_manual_on()``（``_run_battle_live`` 内）只读会话标志
    ``_SESSION["manual"]``；
  · ``_SESSION["manual"]`` 全仓库**只有一个写者** —— ``wuchong_switch`` 自定义动作；
  · 只有两个管线节点带该动作，且**都以「自动=开」为前提门控**（``WuchongTeamAutoSet`` /
    ``WuchongBattleAutoOff``）；
  · 于是当自动开关**本来就是关的**（正是手操想要的状态）时，两节点都不触发 →
    ``_SESSION["manual"]`` 恒 False → ``WuchongBattleAction`` 自认 ``manual=true``（选项参数）
    却启动一个立刻 ``stopped=manual_off`` 的引擎 → 0 点击；管线枢纽反复重进 455 次空转。

两个守卫（对应本票硬要求；prove-red 见文末）：

1. ``wuchong-74-manual-param-is-authoritative`` —— **选项参数就是手操态权威源**：以
   **新鲜会话**（``_SESSION["manual"] == False``，等价于「``wuchong_switch`` 节点从未跑过」=
   自动=开门控从未命中的现场）驱动**真实** :class:`WuchongBattleAction`、且把 ``run_manual_battle``
   的 ``manual_on`` 接**真的** ``_SESSION`` 读（**不是** ``lambda: True``）→ 断言引擎**真的点板**
   （taps > 0），并直接断言「选项 param → 会话回填」在**引擎入口之前**已发生。
   ★这条守卫正是本缺陷的探针★：修复前（不回填会话）它会红。
2. ``wuchong-74-zero-tap-yield-is-bounded`` —— **零点击空转有界（可见失败）**：连续
   ``ZERO_TAP_YIELD_LIMIT`` 次「0 点击且 stopped=manual_off」后，**既有** ``WuchongGiveUpRecognition``
   必须带**点名零点击空转**的理由收工（写 ``run_done`` 标记 = StopTask 出口），绝不空转；
   且一场「点到了板 / 结算收场」的战斗必须把连击**复位**。

★为什么离线旧守卫没抓到★：既有 ``tools/contract_hooks/hooks_71.py`` 用
``manual_on=lambda: True`` 的**桩钩子**驱动 ``run_manual_battle`` —— 离线从未跑过
``真实 _manual_on() ← _SESSION["manual"] ← 选项参数`` 这条链，故修复前的缺陷对离线全绿。

prove-red（``python tools\\contract_hooks\\hooks_74.py``）：逐一改坏实现，要求守卫各自变红。
"""

from __future__ import annotations

import pathlib

import contextlib
import io
import json
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

#: 合成战斗帧（形态取自 hooks_71.BATTLE_FRAME / ~/hooks_auto_outside.BATTLE_HUD_ITEMS）。
#: 用于让「零点击空转达上限」后被 ``WuchongGiveUpRecognition`` 观测为 ``wuchong_battle``，
#: 从而只可能命中 #74 的新理由（无 progress / unknown 干扰）。
BATTLE_ITEMS = [
    ("分数  00166756407", [195, 1222, 241, 36]),
    ("时间 09:55", [37, 1225, 128, 32]),
]

#: 本票守卫用的假 task_id（与其它挂点隔离）。
TID = 740074


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


class _CtxStub:
    """最小 context 桩（动作只经 monkeypatch 的 ``_run_battle_live``，不触设备）。"""


class _ActArgv:
    def __init__(self, param):
        self.custom_action_param = json.dumps(param)


class _RecArgv:
    """最小 ``CustomRecognition`` 入参桩（image + task_detail.task_id + custom_recognition_param）。"""

    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


# ---------------------------------------------------------------------------
# 会话摆位 / 驱动
# ---------------------------------------------------------------------------
def _fresh_session(mod, tid: int = TID) -> None:
    """把会话摆成「刚进任务、尚未跑过任何 wuchong_switch 节点」的新鲜现场。

    ``_SESSION["manual"] = False`` 正是缺陷现场：自动开关本来就是关的 ⇒ 两个带
    ``wuchong_switch`` 的节点都以「自动=开」为前提门控、都不触发 ⇒ 会话手操态无人写。
    同时把收工相关字段清零，使「零点击空转达上限」只可能命中 #74 的新理由。
    """
    with mod._LOCK:
        mod._SESSION["task_id"] = tid
        mod._SESSION["manual"] = False
        mod._SESSION["zero_tap_yield_streak"] = 0
        mod._SESSION["lost"].reset()
        mod._SESSION["renav_count"] = 0
        mod._SESSION["net_misses"] = 0
        mod._SESSION["start_ts"] = time.monotonic()
        mod._SESSION["last_progress_ts"] = time.monotonic()
        mod._SESSION["last_state"] = None
        mod._SESSION["last_observe_ts"] = 0.0
        mod._SESSION["recruit_started"] = False
        mod._SESSION["room_first_ts"] = 0.0
        mod._SESSION["room_seen"] = False
        mod._SESSION["fights_done"] = 0
        mod._SESSION["target_fights"] = 0
        mod._SESSION["battle_had_continue"] = False
        mod._SESSION["in_fight"] = False
        mod._SESSION["gameover_seen"] = False
        mod._SESSION["continues_done"] = 0
        mod._SESSION["target_continues"] = 0
        mod._SESSION["gameover_first_ts"] = 0.0


def _drive_action(mod, engine, param, action_cls=None) -> None:
    """用 ``engine`` 替换 ``_run_battle_live`` 后驱动一次手操动作（用完还原）。"""
    action_cls = action_cls or mod.WuchongBattleAction
    real = mod._run_battle_live
    try:
        mod._run_battle_live = engine
        with contextlib.redirect_stdout(io.StringIO()):
            action_cls().run(_CtxStub(), _ActArgv(param))
    finally:
        mod._run_battle_live = real


def _session_engine(mod, stop_at: float = 12.0, entry: dict | None = None):
    """真实引擎的驱动件：``manual_on`` 接**真的** ``_SESSION["manual"]`` 读（不是恒 True 的桩）。

    返回 ``(engine, state)``；``state["taps"]`` 累计点击数，``entry["manual"]`` 记录引擎**入口**
    读到的会话态（用于断言「回填发生在引擎启动之前」）。
    """
    state = {"t": 0.0, "taps": 0}

    def now():
        return state["t"]

    def burst_click(point, times, gap):
        state["t"] += (int(times) * int(gap)) / 1000.0
        state["taps"] += int(times)

    def engine(context, cadence):
        def _manual_on():
            with mod._LOCK:
                return bool(mod._SESSION["manual"])

        if entry is not None:
            entry["manual"] = _manual_on()
        hooks = mod.BattleHooks(
            burst_click=burst_click,
            swipe=lambda begin, end, ms: None,
            verdict=lambda: mod.PAGE_CONTINUE if state["t"] < stop_at else mod.PAGE_OVER,
            manual_on=_manual_on,
            sleep=lambda sec: None,
            now=now,
            stopping=lambda: False,
        )
        return mod.run_manual_battle(hooks, cadence)

    return engine, state


def _drive_giveup(mod, tid: int):
    """用战斗帧驱动**真实** ``WuchongGiveUpRecognition`` 一次；返回 ``(是否命中, reason)``。"""
    real_ocr = mod._ocr
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(BATTLE_ITEMS)
        res = mod.WuchongGiveUpRecognition().analyze(
            None, _RecArgv(tid, {"ocr_entry": "OcrTask", "no_progress_sec": 900})
        )
        return (res.box == [0, 0, 0, 0]), str((res.detail or {}).get("reason") or "")
    finally:
        mod._ocr = real_ocr


# ---------------------------------------------------------------------------
# 守卫 A：选项参数就是手操态权威源（会话回填先于引擎）
# ---------------------------------------------------------------------------
def _seed_failures(mod, action_cls=None) -> list:
    msgs: list[str] = []
    _fresh_session(mod, TID)
    entry: dict = {}
    engine, state = _session_engine(mod, entry=entry)
    _drive_action(mod, engine, {mod.BATTLE_MANUAL_FIELD: True}, action_cls)

    if state["taps"] <= 0:
        msgs.append(
            f"新鲜会话 + 动作 {mod.BATTLE_MANUAL_FIELD}=true：手操引擎 0 点击（taps={state['taps']}）"
            " —— 动作没把选项手操回填进会话，_manual_on() 与动作自身决定自相矛盾"
        )
    if entry.get("manual") is not True:
        msgs.append(
            f"引擎入口读到 _SESSION['manual']={entry.get('manual')!r}（应 True）"
            " —— 回填时机不对 / 缺失（必须在启动引擎之前回填）"
        )
    with mod._LOCK:
        seeded = bool(mod._SESSION["manual"])
    if not seeded:
        msgs.append("动作以 manual=true 进入后 _SESSION['manual'] 仍非 True（选项→会话回填缺失）")
    return msgs


def probe_wuchong_74_manual_param_is_authoritative() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _seed_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 B：零点击空转有界（可见失败，走既有收工出口）
# ---------------------------------------------------------------------------
def _zero_tap_failures(mod, action_cls=None) -> list:
    msgs: list[str] = []
    limit = getattr(mod, "ZERO_TAP_YIELD_LIMIT", None)
    if not isinstance(limit, int) or limit <= 0:
        return ["wuchong_impl 缺 ZERO_TAP_YIELD_LIMIT（零点击空转上限常数被删 / 改名）"]

    _fresh_session(mod, TID)

    def _zero_engine(context, cadence):
        return {"taps": 0, "swipes": [], "checks": 0,
                "stopped": "manual_off", "reason": "手操已关（切回自动）→ 立刻停手"}

    for _ in range(limit):
        _drive_action(mod, _zero_engine, {mod.BATTLE_MANUAL_FIELD: True}, action_cls)

    with mod._LOCK:
        streak = mod._SESSION["zero_tap_yield_streak"]
    if streak < limit:
        msgs.append(
            f"连续 {limit} 次 0 点击且 manual_off 后 streak={streak} 未达上限"
            " —— 空转无界、阻塞收敛（旧 455 次空转的根因之一）"
        )

    hit, reason = _drive_giveup(mod, TID)
    if not hit:
        msgs.append("零点击空转达上限后 WuchongGiveUpRecognition 竟未收工（仍会空转）")
    elif "0 点击" not in (reason or ""):
        msgs.append(f"收工理由未点名『0 点击』空转：reason={reason!r}")

    # 有进展（点到了板 / 结算收场）→ 连击必须复位。
    def _tap_engine(context, cadence):
        return {"taps": 5, "swipes": [], "checks": 0, "stopped": "battle_over", "reason": "结算"}

    _drive_action(mod, _tap_engine, {mod.BATTLE_MANUAL_FIELD: True}, action_cls)
    with mod._LOCK:
        after = mod._SESSION["zero_tap_yield_streak"]
        mod._SESSION["zero_tap_yield_streak"] = 0  # 收尾复位，避免污染后续挂点
    if after != 0:
        msgs.append(f"有点击的战斗后零点击连击未复位：streak={after}（应 0）")
    return msgs


def probe_wuchong_74_zero_tap_yield_is_bounded() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _zero_tap_failures(impl) == []


# ---------------------------------------------------------------------------
# #74 真机合并框帧标定（本仓既有先例：tools/frames/auto_battle_hud_hit.png）
# ---------------------------------------------------------------------------
#: 真机 run2（384, 2026-10-16）的两张战斗帧：HUD 是**一个合并框**，不是三个独立文本框。
#: 来源帧在运维的临时目录（``wc74/frames/``）—— 这里**复制**留档两份（真机帧标定证据）：
#:   · tools/frames/wuchong74_battle_hud_merged.png  ← wc74/frames/00122_unknown.png
#:   · tools/frames/wuchong74_battle_hud_merged2.png ← wc74/frames/00322_unknown.png
#: 逐字 OCR（由 ``tools/ocr_image.py --entry OcrTask`` 离线读出）：
#:   00122 → '时间 29:30 分数 38629797530'（box=[34,1221,402,40]）
#:   00322 → '时间 28:37 分数 99999999999'（box=[33,1220,402,40]）
FRAME_MERGED_1 = "tools/frames/wuchong74_battle_hud_merged.png"
FRAME_MERGED_2 = "tools/frames/wuchong74_battle_hud_merged2.png"
#: 逐字来自真机帧的合并框 OCR 项（720 空间；每条 = (text, [x, y, w, h])，与 OcrTask 同形）。
#: 只用合并框那一条 —— 判据的全部信息都在里面，这正是旧「独立文本框」判据漏掉、而共享真源
#: :func:`battle_loop_core.is_battle_hud`（正则**搜索**）认得的东西。
MERGED_HUD_ITEMS_1 = [("时间 29:30 分数 38629797530", [34, 1221, 402, 40])]
MERGED_HUD_ITEMS_2 = [("时间 28:37 分数 99999999999", [33, 1220, 402, 40])]

#: GAMEOVER 续关屏（真机 run2 逐字 OCR：['GAMEOVER', '使用星导石×50', '是否续关?']）——
#: 用于守卫「续关不算新的一场」：``_observe`` 见到它即置 ``battle_had_continue``。
GAMEOVER_CONTINUE_ITEMS = [
    ("GAMEOVER", [101, 696, 875, 108]),
    ("是否续关?", [450, 1230, 195, 48]),
    ("使用星导石×50", [412, 1296, 257, 34]),
    # ★底部同样画着合并框 HUD★（真机失败页事实；正是 #46 的坑，故必须靠 is_gameover_page 认）。
    ("时间 28:37 分数 99999999999", [33, 1220, 402, 40]),
]

TID_COUNT = 740075
TID_UNKNOWN = 740076


# ---------------------------------------------------------------------------
# 守卫 C：真机合并框帧必须被判 wuchong_battle（两套判据不得再打架）
# ---------------------------------------------------------------------------
def _merged_hud_failures(mod, core=None) -> list:
    _paths()
    if core is None:
        import battle_loop_core as core  # noqa: PLC0415

    msgs: list[str] = []
    # (a) 来源帧随仓（真机帧标定证据）。
    for rel in (FRAME_MERGED_1, FRAME_MERGED_2):
        if not (REPO_ROOT / rel).is_file():
            msgs.append(f"真机合并框帧未入库：{rel}（真机帧标定证据缺失）")
    # (b) 共享真源认得合并框（正则搜索）；classify / page_verdict 必须与之一致（判据只一份）。
    for label, items in (("00122", MERGED_HUD_ITEMS_1), ("00322", MERGED_HUD_ITEMS_2)):
        if not core.is_battle_hud(items):
            msgs.append(f"{label} 合并框：battle_loop_core.is_battle_hud 竟为 False（共享真源失效）")
        state, _info = mod.classify(list(items))
        if state != mod.WUCHONG_BATTLE:
            msgs.append(
                f"{label} 合并框：classify={state!r} != 'wuchong_battle'"
                "（战斗页被判 unknown = 未知计数早亡根因；两套判据打架）"
            )
        # ★2026-10-16 运维裁决★：真战斗帧（含合并框）→ 引擎**继续点**（PAGE_CONTINUE）；
        #   即便某帧 HUD 闪回 unknown，也归 continue —— 引擎绝不停手，也绝不再虚计。
        if mod.page_verdict(list(items)) != mod.PAGE_CONTINUE:
            msgs.append(f"{label} 合并框：page_verdict != PAGE_CONTINUE（引擎会误停手）")
    # (c) ★单一真源★：本文件不得再自带一份战斗 HUD 正则（历史上 _TIME_RE/_HHMM_RE 的第三份拷贝）。
    for leaked in ("_TIME_RE", "_HHMM_RE", "_BOTTOM_Y"):
        if hasattr(mod, leaked):
            msgs.append(f"wuchong_impl 仍自带战斗 HUD 判据 {leaked}（第三份正则 = 单一真源漂移）")
    return msgs


def probe_wuchong_74_merged_battle_hud_is_battle() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _merged_hud_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 D：计数点 = 跃变进入战斗（规格 B2/D2）；续关不算新的一场；结算页不再计
# ---------------------------------------------------------------------------
def _reset_count_session(mod, tid: int) -> None:
    with mod._LOCK:
        mod._SESSION["task_id"] = tid
        mod._SESSION["fights_done"] = 0
        mod._SESSION["target_fights"] = 0
        mod._SESSION["battle_had_continue"] = False
        mod._SESSION["in_fight"] = False
        mod._SESSION["last_state"] = None
        mod._SESSION["last_observe_ts"] = 0.0
        mod._SESSION["lost"].reset()
        mod._SESSION["room_first_ts"] = 0.0
        mod._SESSION["start_ts"] = time.monotonic()
        mod._SESSION["last_progress_ts"] = time.monotonic()


def _fight_count_timing_failures(mod) -> list:
    _paths()
    import tempfile  # noqa: PLC0415

    msgs: list[str] = []

    def done() -> int:
        with mod._LOCK:
            return int(mod._SESSION["fights_done"])

    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p74_count.json")
        try:
            mod.ledger.reset(mod.LEDGER_SCOPE)
            _reset_count_session(mod, TID_COUNT)

            # (a) 跃变进入战斗 → +1 且写账本 wuchong/fight/1。
            mod._observe(mod.WUCHONG_BATTLE, {}, [])
            if done() != 1:
                msgs.append(f"跃变进入战斗未 +1：fights_done={done()}（规格 B2：计数点 = 进战斗）")
            scope = mod.ledger.scope(mod.FIGHT_LEDGER_PREFIX)
            if scope != [f"{mod.FIGHT_LEDGER_PREFIX}/1"]:
                msgs.append(f"进入战斗未落账本：{scope}")

            # (b) 同状态持续帧不重复计。
            mod._observe(mod.WUCHONG_BATTLE, {}, [])
            if done() != 1:
                msgs.append(f"同状态持续帧重复计数：fights_done={done()}")

            # (c) 续关（GAMEOVER 屏）后回到战斗 → 不再 +1（续关不算新的一场）。
            mod._observe(mod.WUCHONG_BATTLE, {}, GAMEOVER_CONTINUE_ITEMS)
            mod._observe("loading", {}, [])
            mod._observe(mod.WUCHONG_BATTLE, {}, [])
            if done() != 1:
                msgs.append(f"续关后回到战斗被误计为新的一场：fights_done={done()}（应仍 1）")

            # (d) 结算页不再是计数点（旧语义 D2 已废）。
            mod._observe(mod.WUCHONG_SETTLE, {}, [])
            if done() != 1:
                msgs.append(f"结算页仍在计数（旧语义 D2）：fights_done={done()}")

            # (e) 真正离开本场后的新一场照常 +1（别把计数整体关死）。
            mod._observe(mod.WUCHONG_TEAM, {}, [])
            mod._observe(mod.WUCHONG_BATTLE, {}, [])
            if done() != 2:
                msgs.append(f"离开本场后的新一场未 +1：fights_done={done()}（应 2）")
            scope2 = mod.ledger.scope(mod.FIGHT_LEDGER_PREFIX)
            if scope2 != [f"{mod.FIGHT_LEDGER_PREFIX}/1", f"{mod.FIGHT_LEDGER_PREFIX}/2"]:
                msgs.append(f"新一场未落账本：{scope2}")
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
            _reset_count_session(mod, TID_COUNT)
    return msgs


def probe_wuchong_74_fight_counted_on_battle_entry() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _fight_count_timing_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 E：战斗页帧不再被累加进「迷路」（早亡根因）
# ---------------------------------------------------------------------------
#: 守卫 E 用的「上一状态哨兵」：让 ``_observe`` 一定把这一帧当**跃变**，不依赖上一帧残留态。
_SENTINEL_STATE = "__hooks_74_guard_e_sentinel__"


def _pin_count_session(mod, tid: int) -> None:
    """把计数相关会话字段钉成**已知起点**：迷路时钟归零 / 必为跃变 / 必为 stale / 不在战斗 episode 内。

    ★为什么必须钉 ``in_fight=False``★（守卫 E 曾经空转的根因，2026-10-18 复盘）：
    #76 的判据（ADR 0005 之后收敛到 ``LostClock.observe(..., in_fight=...)``）规定
    「战斗 episode 内的 unknown 帧不打点」。旧版守卫 E 只清计数器 / ``last_state``，**不清
    ``in_fight``** —— 而它自己的绿腿先跑过一遍 ``analyze``（战斗帧 → ``_observe`` 把 ``in_fight``
    置真），于是 prove-red 的 red 腿（``is_battle_hud`` 恒 False → 判 unknown）里时钟**恒不启动**
    ⇒「战斗页没打点」恒成立 ⇒ 红线永不可能变红（任务描述里的第 3 条假绿）。
    这里一次钉全，断言不再依赖调用顺序。
    """
    with mod._LOCK:
        mod._SESSION["task_id"] = tid
        mod._SESSION["lost"].reset()
        mod._SESSION["unknown_streak"] = 0
        mod._SESSION["last_state"] = _SENTINEL_STATE
        mod._SESSION["last_observe_ts"] = 0.0
        mod._SESSION["in_fight"] = False          # ★#76 排除条件必须钉假★
        mod._SESSION["zero_tap_yield_streak"] = 0
        mod._SESSION["room_first_ts"] = 0.0
        mod._SESSION["start_ts"] = time.monotonic()
        mod._SESSION["last_progress_ts"] = time.monotonic()


def _lost_started(mod) -> int:
    """迷路时钟是否已被这一帧启动（1 = 正在计时；0 = 没打点）。

    ★ADR 0005 改指★：旧实现数 ``_SESSION["unknown_count"]``（累计帧数）；现在判据是
    ``LostClock.observe(in_fight=...)`` —— 战斗 episode 内 unknown **不记起点**，故「没打点」。
    """
    with mod._LOCK:
        return 0 if mod._SESSION["lost"]._start is None else 1


def _battle_frame_not_unknown_failures(mod) -> list:
    """守卫 E：真机合并框战斗帧不得启动迷路时钟，也不得以『认不出画面』收工。

    ★三条腿，缺一即假绿★：
      (a) **判据直证**：``classify(合并框帧)`` 必须是 ``wuchong_battle``（纯函数，无会话残留）；
      (b) **打点路径**：把同一帧喂**真实计数函数** :func:`wuchong_impl._observe`
          （= ``WuchongGiveUpRecognition.analyze`` 内部那条路径）→ 迷路时钟不得启动；
      (c) **时钟活性自证（反空转）**：一帧真·未知画面必须让时钟开始计时。
          没有 (c)，(b) 的「没打点」在「判据根本没跑」时也恒成立 —— 正是本次抓到的假绿形态。
    """
    _paths()
    msgs: list[str] = []
    items = list(MERGED_HUD_ITEMS_1)
    real_ocr = mod._ocr
    try:
        # (a) 判据直证：真机合并框战斗帧 → wuchong_battle（不经过任何会话状态）。
        state, info = mod.classify(items)
        if state != mod.WUCHONG_BATTLE:
            msgs.append(
                f"真机合并框战斗帧被 classify 判成 {state!r}（应 'wuchong_battle'）"
                " —— 战斗页被判 unknown = 未知计数早亡根因"
            )

        # (b) 打点路径：_observe（analyze 内部就是它）不得让战斗帧启动迷路时钟。
        _pin_count_session(mod, TID_UNKNOWN)
        mod._observe(state, info, items)
        battle_lost = _lost_started(mod)
        if battle_lost != 0:
            msgs.append(
                f"战斗页（真机合并框）经 _observe 后迷路时钟已启动（{battle_lost}）"
                " —— 战斗页被判 unknown = 未知计数早亡根因"
            )

        # (c) 时钟活性自证：认不出的帧必须真的开始计时（否则 (b) 恒成立 = 空转）。
        _pin_count_session(mod, TID_UNKNOWN)
        mod._observe("unknown", {}, [])
        unknown_alive = _lost_started(mod)
        if unknown_alive != 1:
            msgs.append(
                f"未知画面帧经 _observe 后迷路时钟未启动（{unknown_alive}，应 1）"
                " —— 时钟本身不活，守卫 E 的『没打点』恒成立（空转）"
            )

        # (d) 整条收工出口：真实 WuchongGiveUpRecognition 在战斗帧上不得启动时钟、不得以「认不出」收工。
        _pin_count_session(mod, TID_UNKNOWN)
        mod._ocr = lambda context, image, entry="OcrTask": list(MERGED_HUD_ITEMS_1)
        res = mod.WuchongGiveUpRecognition().analyze(
            None,
            _RecArgv(
                TID_UNKNOWN,
                {"ocr_entry": "OcrTask", "no_progress_sec": 900, "room_wait_sec": 300,
                 "lost_sec": 60},
            ),
        )
        exit_lost = _lost_started(mod)
        reason = str((res.detail or {}).get("reason") or "")
        if exit_lost != 0:
            msgs.append(
                f"战斗页喂 giveup 后迷路时钟已启动（{exit_lost}）"
                " —— 收工出口路径上战斗帧仍被当成迷路"
            )
        if res.box == [0, 0, 0, 0] and "认不出画面" in reason:
            msgs.append(f"战斗页帧竟以『认不出画面』理由收工（早亡根因复现）：{reason!r}")
    finally:
        mod._ocr = real_ocr
        with mod._LOCK:
            mod._SESSION["lost"].reset()
            mod._SESSION["unknown_streak"] = 0
            mod._SESSION["last_state"] = None
            mod._SESSION["in_fight"] = False
            mod._SESSION["zero_tap_yield_streak"] = 0
    return msgs


def probe_wuchong_74_battle_frame_not_unknown() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _battle_frame_not_unknown_failures(impl) == []


# ---------------------------------------------------------------------------
# 破坏件（prove-red 用；自带一份，绝不 import 别的守卫模块）
# ---------------------------------------------------------------------------
class _BrokenNoSeedBattleAction:
    """坏实现（prove-red）：动作入口**不回填** ``_SESSION["manual"]``。

    = #74 的真实缺陷原形：手操态只由 ``wuchong_switch`` 节点写，而自动=关时它不触发。
    除缺这行回填外，其余与真实 :class:`WuchongBattleAction` 一致 —— 故只有守卫 A 会变红。
    """

    def __init__(self, mod):
        self._mod = mod

    def run(self, context, argv):  # noqa: N802
        m = self._mod
        param = m.read_action_param(argv)
        scene = str(param.get("scene") or "wuchong")
        with m._LOCK:
            session_manual = m._SESSION["manual"]
        manual = bool(param.get(m.BATTLE_MANUAL_FIELD, session_manual))
        if manual and not m.manual_allowed(scene):
            manual = False
        if not manual:
            return True
        cadence = m._cadence_from_param(param)
        m._run_battle_live(context, cadence)   # ★缺回填：会话手操态仍 False★
        return True


class _BrokenNoStreakBattleAction(_BrokenNoSeedBattleAction):
    """坏实现（prove-red）：仍回填选项手操，但**不维护零点击连击计数** = 去掉有界出口。

    故守卫 A 仍绿、只有守卫 B 变红。
    """

    def run(self, context, argv):  # noqa: N802
        m = self._mod
        param = m.read_action_param(argv)
        scene = str(param.get("scene") or "wuchong")
        with m._LOCK:
            session_manual = m._SESSION["manual"]
            m._SESSION["manual"] = True   # 仍回填（守卫 A 不该红）
        manual = bool(param.get(m.BATTLE_MANUAL_FIELD, session_manual))
        if manual and not m.manual_allowed(scene):
            manual = False
        if not manual:
            return True
        cadence = m._cadence_from_param(param)
        result = m._run_battle_live(context, cadence)
        with m._LOCK:
            m._SESSION["battle_taps"] += int((result or {}).get("taps") or 0)
        # ★缺：不维护 zero_tap_yield_streak★
        return True


def _make_settle_count_observe(mod):
    """坏实现（prove-red）：把计数点倒回旧语义「进入结算页 +1」（规格 D2 = 缺陷原形）。"""

    def _observe(state, info, items):  # noqa: N802
        now = time.monotonic()
        count = False
        with mod._LOCK:
            changed = state != mod._SESSION["last_state"]
            mod._SESSION["last_observe_ts"] = now
            mod._SESSION["last_state"] = state
            count = changed and state == mod.WUCHONG_SETTLE
        if count:
            mod._count_fight()

    return _observe


def _make_ignore_continue_observe(mod):
    """坏实现（prove-red）：跃变进战斗一律 +1，**不看** battle_had_continue（续关后重复计数）。"""

    def _observe(state, info, items):  # noqa: N802
        now = time.monotonic()
        count = False
        with mod._LOCK:
            changed = state != mod._SESSION["last_state"]
            mod._SESSION["last_observe_ts"] = now
            mod._SESSION["last_state"] = state
            count = changed and state == mod.WUCHONG_BATTLE
        if count:
            mod._count_fight()

    return _observe


def _patch_is_battle_hud_false(mod):
    """坏实现（prove-red）：模拟 #74 之前 —— classify 战斗分支不认共享真源（合并框判 unknown）。

    ★#119★ 五重的 ``classify`` 已薄封装到 ``battle_loop_core.classify``（判据只有一份）：
    战斗分支实际读取的是 **battle_loop_core.is_battle_hud**，不再经 ``wuchong_impl`` 的模块
    全局。破坏点跟着判据的真实位置走（契约不变：判据被打瞎时守卫必须红）。
    ``mod`` 保留为形参：调用方仍按「被测模块」传入，签名不漂。
    """
    import battle_loop_core as core  # noqa: PLC0415

    orig = core.is_battle_hud
    core.is_battle_hud = lambda _items: False
    return orig


def _restore_is_battle_hud(orig):
    """把 :func:`_patch_is_battle_hud_false` 打瞎的共享判据恢复回去。"""
    import battle_loop_core as core  # noqa: PLC0415

    core.is_battle_hud = orig


# ---------------------------------------------------------------------------
# prove-red
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_74 prove-red：逐一破坏实现，要求守卫各自变红")

    seed_msgs = _seed_failures(impl)
    bound_msgs = _zero_tap_failures(impl)
    merged_msgs = _merged_hud_failures(impl)
    count_msgs = _fight_count_timing_failures(impl)
    unknown_msgs = _battle_frame_not_unknown_failures(impl)
    for label, group in (
        ("守卫 A", seed_msgs),
        ("守卫 B", bound_msgs),
        ("守卫 C（合并框）", merged_msgs),
        ("守卫 D（计数时机）", count_msgs),
        ("守卫 E（战斗页不启动迷路时钟）", unknown_msgs),
    ):
        for msg in group:
            print(f"      {label} 断言落空：{msg}")

    green = not (seed_msgs or bound_msgs or merged_msgs or count_msgs or unknown_msgs)
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：五个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # G-A：动作不回填 _SESSION["manual"] → 守卫 A 必须红。
    red_a = len(_seed_failures(
        impl, action_cls=lambda: _BrokenNoSeedBattleAction(impl))) > 0
    print(f"  [{'PASS' if red_a else 'FAIL'}] 选项→会话回填：去掉回填 -> {'红' if red_a else '仍绿'}")
    checks.append(red_a)

    # G-B：动作不维护零点击连击 → 守卫 B 必须红。
    red_b = len(_zero_tap_failures(
        impl, action_cls=lambda: _BrokenNoStreakBattleAction(impl))) > 0
    print(f"  [{'PASS' if red_b else 'FAIL'}] 零点击空转有界：去掉连击计数 -> {'红' if red_b else '仍绿'}")
    checks.append(red_b)

    # G-C / G-E：classify 战斗分支不认共享真源（模拟 #74 前）→ 合并框判 unknown →
    #   守卫 C 必红，且守卫 E（unknown 累加）必红。
    orig_hud = _patch_is_battle_hud_false(impl)
    try:
        red_c = len(_merged_hud_failures(impl)) > 0
    finally:
        _restore_is_battle_hud(orig_hud)
    print(f"  [{'PASS' if red_c else 'FAIL'}] 合并框判据单一真源：战斗分支不认共享真源 -> "
          f"{'红' if red_c else '仍绿'}")
    checks.append(red_c)

    orig_hud = _patch_is_battle_hud_false(impl)
    try:
        red_e = len(_battle_frame_not_unknown_failures(impl)) > 0
    finally:
        _restore_is_battle_hud(orig_hud)
    print(f"  [{'PASS' if red_e else 'FAIL'}] 战斗页不启动迷路时钟：合并框判 unknown -> "
          f"{'红' if red_e else '仍绿'}")
    checks.append(red_e)

    # G-D1：计数点倒回「结算页」→ 守卫 D 必须红。
    saved = impl._observe
    try:
        impl._observe = _make_settle_count_observe(impl)
        red_d1 = len(_fight_count_timing_failures(impl)) > 0
    finally:
        impl._observe = saved
    print(f"  [{'PASS' if red_d1 else 'FAIL'}] 计数点=进战斗：倒回结算页计数 -> "
          f"{'红' if red_d1 else '仍绿'}")
    checks.append(red_d1)

    # G-D2：计数不看 battle_had_continue → 续关后重复计数 → 守卫 D 必须红。
    try:
        impl._observe = _make_ignore_continue_observe(impl)
        red_d2 = len(_fight_count_timing_failures(impl)) > 0
    finally:
        impl._observe = saved
    print(f"  [{'PASS' if red_d2 else 'FAIL'}] 续关不算新的一场：计数不看 battle_had_continue -> "
          f"{'红' if red_d2 else '仍绿'}")
    checks.append(red_d2)

    # 收尾：把会话复位回干净态（避免污染后续挂点 / 单进程内其它守卫）。
    _fresh_session(impl, TID)
    _reset_count_session(impl, TID_COUNT)
    with impl._LOCK:
        impl._SESSION["lost"].reset()

    ok = green and all(checks)
    print("结果：★prove-red 成功★" if ok else "结果：★prove-red 失败★")
    return ok


def _hud_fallback_failures() -> list:
    """★#107 真机★ HUD 被遮挡时判据要兜底，且**不许误判非战斗页**。

    证据帧：
    - 正例 `tools/frames/wuchong_hud_occluded.png`（HUD 被「技能槽未满。」压住，只读得到 FEVER/血条/ABILITY）
    - 正例 `tools/frames/wuchong_hud_readable.png`（HUD 可读，走主判据）
    - 负例：结算 / 编队 / 主城 / 外传编队（都不许判成战斗）
    """
    import sys as _sys

    msgs: list[str] = []
    root = pathlib.Path(__file__).resolve().parents[2]
    _sys.path.insert(0, str(root / "tools"))
    _sys.path.insert(0, str(root / "agent"))
    import battle_loop_core as b  # noqa: PLC0415
    from scene import auto_switch as a  # noqa: PLC0415

    # (a) 快照 == 真源
    if tuple(b.BATTLE_HUD_FALLBACK_ANCHORS_SNAPSHOT) != tuple(a.BATTLE_HUD_FALLBACK_ANCHORS):
        msgs.append(
            "agent.battle_loop_core.BATTLE_HUD_FALLBACK_ANCHORS_SNAPSHOT 与 "
            "scene.auto_switch.BATTLE_HUD_FALLBACK_ANCHORS 不一致（安装态会跑旧判据）"
        )
    if b.BATTLE_HUD_FALLBACK_MIN_SNAPSHOT != a.BATTLE_HUD_FALLBACK_MIN:
        msgs.append("BATTLE_HUD_FALLBACK_MIN 快照与真源不一致")
    if a.BATTLE_HUD_FALLBACK_MIN < 2:
        msgs.append(
            f"BATTLE_HUD_FALLBACK_MIN={a.BATTLE_HUD_FALLBACK_MIN} 太小 —— 单个视觉特征太弱"
            "（结算页也有伤害数字、主城也有倒计时），至少 2 个"
        )

    # (b) 用入库帧验正负例（离线 OCR）
    import re as _re
    import subprocess as _sp

    def _items(png) -> list:
        out = _sp.run(
            [_sys.executable, str(root / "tools" / "ocr_image.py"), str(png)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        return [(t, []) for t in _re.findall(r"text='([^']*)'", out)]

    frames = root / "tools" / "frames"
    positive = ("wuchong_hud_occluded.png", "wuchong_hud_readable.png")
    negative = (
        "wuchong76_settle_giveup_after_fight.png",
        "lord_settle_1_record.png",
        "lord_team_page.png",
        "maze57_head_on_maincity.png",
        # ★注意：GAMEOVER 两帧**故意不在负例里**★
        #   它们是**主判据**（时间+分数）判 True 的**历史行为**（仓内注释：GAMEOVER 页底部仍画着
        #   时间/分数），由 battle_wait_should_hold / classify_gameover 排除，不是兜底判据的锅。
        #   把失败页当战斗页这件事（classify 层面）已另开票 #115，别在这里制造假红。
    )
    for name in positive:
        png = frames / name
        if not png.is_file():
            msgs.append(f"缺正例帧 {name}（判据没有证据）")
            continue
        if not b.is_battle_hud(_items(png)):
            msgs.append(f"正例帧 {name} 没被判成战斗页（HUD 兜底失效）")
    for name in negative:
        png = frames / name
        if not png.is_file():
            continue
        if b.is_battle_hud(_items(png)):
            msgs.append(f"负例帧 {name} 被误判成战斗页（兜底判据太宽）")
    return msgs


## ★#107★ HUD 遮挡时的兜底判据（正例命中 + 负例不误判 + 快照同源）
def probe_wuchong_hud_fallback() -> bool:
    return _hud_fallback_failures() == []


#: ``hooks_74`` 的挂点表在下面注册（保持既有风格）。
HOOKS = [
    (
        "wuchong-hud-fallback",
        "#107",
        "HUD 被 toast 遮挡时靠多个战斗视觉特征兜底认战斗页；快照与 scene/auto_switch 同源；结算/编队/主城/GAMEOVER 一律不误判",
        probe_wuchong_hud_fallback,
    ),
    (
        "wuchong-74-manual-param-is-authoritative",
        "#74",
        "手操态以选项参数为权威源：新鲜会话（_SESSION['manual']=False，等价于 wuchong_switch 节点"
        "从未触发）+ 动作 manual=true → 引擎入口前已回填 _SESSION['manual']=True 且真的点板（taps>0）；"
        "manual_on 接真实会话读（非恒 True 桩）—— 即修复前会红的那条守卫",
        probe_wuchong_74_manual_param_is_authoritative,
    ),
    (
        "wuchong-74-zero-tap-yield-is-bounded",
        "#74",
        "零点击空转有界（可见失败）：连续 ZERO_TAP_YIELD_LIMIT 次 0 点击且 stopped=manual_off 后，"
        "既有 WuchongGiveUpRecognition 带点名『0 点击』的理由收工（写 run_done = StopTask 出口）；"
        "一场点到了板 / 结算收场的战斗必须把连击复位",
        probe_wuchong_74_zero_tap_yield_is_bounded,
    ),
    (
        "wuchong-74-merged-battle-hud-is-battle",
        "#74",
        "真机合并框帧回归（规格 D2/单一真源）：真机 run2 的战斗 HUD 是**一个合并框**"
        "（'时间 29:30 分数 38629797530'，帧 tools/frames/wuchong74_battle_hud_merged.png[2].png）→"
        " classify 必须判 wuchong_battle（旧「独立文本框」判据会判 unknown = 早亡根因）；"
        "且与 battle_loop_core.is_battle_hud / page_verdict 一致；本文件不得再自带第三份 HUD 正则",
        probe_wuchong_74_merged_battle_hud_is_battle,
    ),
    (
        "wuchong-74-fight-counted-on-battle-entry",
        "#74",
        "计数点 = 跃变进入战斗（规格 B2/D2）：进入战斗 +1 且落账本 wuchong/fight/{n}、同状态帧不重复；"
        "续关（GAMEOVER 屏）后回到战斗不再 +1（续关不算新的一场）；结算页不再计；真正离开后的新一场照常 +1",
        probe_wuchong_74_fight_counted_on_battle_entry,
    ),
    (
        "wuchong-74-battle-frame-not-unknown",
        "#74",
        "战斗页帧不再启动迷路时钟（早亡根因）：真机合并框帧先直证 classify=wuchong_battle，"
        "再走**真实打点路径** _observe（= analyze 内部那条）断言 LostClock 未启动（in_fight 期间不打点）、"
        "不以『认不出画面』理由收工；并自带**时钟活性自证**（一帧真·未知画面必须开始计时），"
        "杜绝『判据根本没跑 -> 没打点恒成立』的假绿",
        probe_wuchong_74_battle_frame_not_unknown,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
