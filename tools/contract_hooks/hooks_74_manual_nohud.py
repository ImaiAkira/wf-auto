# -*- coding: utf-8 -*-
"""★2026-10-16 运维裁决★：手操引擎「一直点 + 三个正面终止点」（去掉 HUD 判据）+ 计数 episode 闩锁。

本文件是一张**独立守卫票**（``tools/contract_hooks/hooks_74_manual_nohud.py``）；既有 ``hooks_71`` / ``hooks_74``
的断言只做**同步更新**（四值判据 → 三值、stopped 词表、计数闩锁），本文件专门钉**新契约**。

运维原话（逐字）
--------------
    「那我觉得不要做HUD的OCR了，这个实在是没有意义。你就一直点，点到要么是续关，要么是退出去
     了，要么就结算了就完事了」

含义（实现契约）
----------------
手操引擎**不再用战斗 HUD（时间/分数）做判据** —— 真机证据（设备A，2026-10-16 诊断跑，1s 粒度
逐帧留档）：**同一场真战斗内部** ``wuchong_battle``(hud=True) 与 ``unknown``(hud=False) 每 2~3 秒
来回（96-106 / 107-108 / …）；战斗本身是真的（``时间 30:00 / 分数 …/ 打倒领主！``）。旧引擎因此
每 2~4 秒 ``stopped=yield`` 让位一次（点板断续），且计数器把同一场战斗计成多场（run5 一次真战斗被
计成 ``fight/1..4``、25 秒「已打够 4 次」收工、零场真正打完）。

新契约：**默认一直点**（弹板 + 按节奏放技能），只在**三个正面终止点**停手：
  1. 续关屏（``GAMEOVER`` + ``是否续关?``）→ 停手交还（下一步由管线点【续关】）；
  2. 结算页（``classify == wuchong_settle``）→ 停手交还；
  3. 被推出战斗（画面变成任一**已知非战斗页**）→ 停手交还。
其余一切（真战斗帧 / 认不出的帧 / 加载帧 / 没有 HUD 的帧）→ **继续点**。

计数：**一场战斗只计一次**（episode 闩锁 ``in_fight``）——命中 ``wuchong_battle`` 且未在战斗中
→ 计一场并置闩锁；``unknown``/``loading`` 的闪烁**不清**闩锁（虚计根因）；只在
``_FIGHT_LEAVE_STATES``（真正离开本场）时清。``battle_had_continue``（GAMEOVER 续关不算新一场）
语义不变，两者叠加。

三个守卫（prove-red 见文末）
---------------------------
A. ``wuchong-74-nohud-default-keep-tapping`` —— HUD 缺失 / ``unknown`` / ``loading`` 帧**不得**让引擎
   停手：用**真实** ``page_verdict`` 判假帧序列（HUD → unknown → loading → … → 续关屏）驱动
   ``run_manual_battle``，断言持续点板、``stopped`` 是 ``battle_over``，**绝不出现** ``hud_miss``/``yield``。
B. ``wuchong-74-nohud-three-termination-points`` —— 三个正面终止点各自命中即停、且**零新增点击**
   （★先判据、后点击★：首帧就是终止点 → ``taps == 0``；命中的那一刻**不落任何点击**就交还）。
C. ``wuchong-74-nohud-fight-episode-latch`` —— 计数 episode 闩锁：``battle→unknown→battle→unknown→battle``
   只计 **1**；``battle→房间→battle`` 计 **2**；``GAMEOVER→续关→battle`` 不重复计（仍 1）。

prove-red（``python tools\\contract_hooks\\hooks_74_manual_nohud.py``）：逐一改坏实现，要求守卫各自变红。
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

#: 本票守卫用的假 task_id（与其它挂点隔离）。
TID = 760076


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


# ---------------------------------------------------------------------------
# 合成 OCR 帧（形态取自真机 / 既有守卫，720 空间）
# ---------------------------------------------------------------------------
#: 真机双空格战斗帧（HUD 合并框 + 独立框都涵在内）。
HUD_FRAME = [
    ("分数  00166756407", [195, 1222, 241, 36]),
    ("时间 09:55", [37, 1225, 128, 32]),
]
#: 认不出的帧（技能演出 / 遮罩 —— 真机里正是它把战斗帧判成 unknown）。
UNKNOWN_FRAME = [("技能演出中", [300, 600, 200, 40])]
#: 加载 / 过场帧。
LOADING_FRAME = [("请耐心等待", [200, 500, 300, 40])]
#: 续关屏（★底部照样画着战斗 HUD★ —— 必须先于「还在战斗」被接走）。
CONTINUE_FRAME = [
    ("GAMEOVER", [300, 400, 200, 60]),
    ("是否续关?", [300, 700, 200, 50]),
    ("放弃", [250, 1043, 120, 50]),
    ("时间 09:55", [37, 1225, 128, 32]),
    ("分数  00166756407", [195, 1222, 241, 36]),
]
#: 结算页。
SETTLE_FRAME = [
    ("QUESTRESULT", [500, 300, 300, 60]),
    ("战斗分数", [300, 800, 200, 40]),
    ("返回房间", [400, 900, 150, 50]),
]
#: 已知非战斗页（被推出战斗）—— 逐条对应 :data:`wuchong_impl.PAGE_LEFT_STATES`。
LEFT_FRAMES = {
    "wuchong_room": [("房间号码", [100, 300, 200, 40]), ("招募", [400, 900, 80, 40]), ("复制", [500, 900, 80, 40])],
    "wuchong_mode": [("单人游戏", [180, 790, 260, 50])],
    "wuchong_team": [("Party E", [100, 400, 200, 40]), ("挑战", [300, 1100, 120, 50])],
    "wuchong_detail": [("五重决战", [310, 690, 300, 45]), ("推荐编成", [60, 1110, 100, 30])],
    "wuchong_lord_list": [("更新列表", [600, 470, 110, 40])],
    "main_city": [("修行之道", [15, 725, 161, 45]), ("成长任务", [47, 368, 118, 33])],
    "activity": [("亲爱的冒险者", [100, 400, 300, 40])],
    "wuchong_level_required": [("玩家等级达到130后", [100, 400, 400, 40]), ("解锁幻想连战与深渊连战", [100, 500, 400, 40])],
    "relogin": [("请重新启动游戏", [100, 400, 300, 40])],
}
#: GAMEOVER 续关屏（真机 run2 逐字）；用于计数闩锁的「续关不算新一场」。
GAMEOVER_ITEMS = [
    ("GAMEOVER", [101, 696, 875, 108]),
    ("是否续关?", [450, 1230, 195, 48]),
    ("使用星导石×50", [412, 1296, 257, 34]),
    ("时间 28:37 分数 99999999999", [33, 1220, 402, 40]),
]


# ---------------------------------------------------------------------------
# 驱动：用假帧序列 + 假时钟驱动真实 run_manual_battle
# ---------------------------------------------------------------------------
def _drive(mod, frames, run_fn=None):
    """按 ``frames`` 逐帧驱动引擎；返回 ``(transcript, obs)``。

    ``obs["verdicts"]`` = 每帧判据；``obs["burst_ts"]`` = 每串连点的假时刻。verdict 前进一个
    0.5s 的假时钟，``check_min_gap_ms=1`` 保证每循环恰好采一帧（一帧一判一 dig）。
    """
    run_fn = run_fn or mod.run_manual_battle
    obs = {"t": 0.0, "taps": 0, "burst_ts": [], "verdicts": []}
    idx = {"i": 0}

    def now():
        return obs["t"]

    def burst_click(point, times, gap):
        obs["taps"] += int(times)
        obs["burst_ts"].append(obs["t"])

    def verdict():
        i = min(idx["i"], len(frames) - 1)
        v = mod.page_verdict(frames[i])
        obs["verdicts"].append(v)
        idx["i"] += 1
        obs["t"] += 0.5
        return v

    hooks = mod.BattleHooks(
        burst_click=burst_click, swipe=lambda b, e, ms: None, verdict=verdict,
        manual_on=lambda: True, sleep=lambda sec: None, now=now, stopping=lambda: False,
    )
    cadence = mod.Cadence(
        center=(360, 600), flipper=(360, 1067), dist=160, swipe_ms=300,
        flipper_gap_ms=220, skill_gap_ms=0, skill_every=0, burst=1, check_min_gap_ms=1,
    )
    return run_fn(hooks, cadence), obs


# ---------------------------------------------------------------------------
# 守卫 A：默认一直点（HUD 缺失 / unknown / loading 不得停手）
# ---------------------------------------------------------------------------
def _default_continue_failures(mod, run_fn=None) -> list:
    msgs: list[str] = []
    frames = [HUD_FRAME, UNKNOWN_FRAME, LOADING_FRAME, HUD_FRAME, UNKNOWN_FRAME,
              HUD_FRAME, LOADING_FRAME, UNKNOWN_FRAME, HUD_FRAME, CONTINUE_FRAME]
    res, obs = _drive(mod, frames, run_fn=run_fn)
    stopped = res.get("stopped")
    if stopped in ("hud_miss", "yield"):
        msgs.append(f"HUD 缺失 / 认不出的帧让引擎停手了（旧行为）：stopped={stopped!r}")
    if stopped != "battle_over":
        msgs.append(f"引擎未由续关屏收场：stopped={stopped!r}（期望 battle_over）")
    # 前 9 帧（HUD / unknown / loading）判据必须全是 continue（继续点）。
    for i, v in enumerate(obs["verdicts"][:9]):
        if v != mod.PAGE_CONTINUE:
            msgs.append(f"第 {i} 帧（HUD/unknown/loading）判据={v!r} != continue（应继续点）")
    if obs["taps"] < 8:
        msgs.append(f"HUD 缺失 / unknown / loading 帧下未持续点板：taps={obs['taps']}（应 ≥8）")
    # page_verdict 三值 + 已知非战斗页集合逐条钉死。
    if set(mod.PAGE_LEFT_STATES) != set(LEFT_FRAMES):
        msgs.append(
            f"PAGE_LEFT_STATES={tuple(mod.PAGE_LEFT_STATES)!r} 与契约（已知非战斗页）不符"
        )
    for bad in ("unknown", "loading", "wuchong_battle", "wuchong_settle"):
        if bad in mod.PAGE_LEFT_STATES:
            msgs.append(f"PAGE_LEFT_STATES 不得含 {bad!r}（认不出/转场/战斗/结算）")
    for state, items in LEFT_FRAMES.items():
        got_state, _info = mod.classify(items)
        if got_state != state:
            msgs.append(f"合成帧 classify={got_state!r} != {state!r}（守卫与实现脱节）")
        if mod.page_verdict(items) != mod.PAGE_LEFT:
            msgs.append(f"已知非战斗页 {state!r} 未判 left（应停手交还）")
    for items, want, label in (
        (HUD_FRAME, mod.PAGE_CONTINUE, "真战斗帧"),
        (UNKNOWN_FRAME, mod.PAGE_CONTINUE, "认不出的帧"),
        (LOADING_FRAME, mod.PAGE_CONTINUE, "加载帧"),
        (CONTINUE_FRAME, mod.PAGE_OVER, "续关屏"),
        (SETTLE_FRAME, mod.PAGE_OVER, "结算页"),
    ):
        got = mod.page_verdict(items)
        if got != want:
            msgs.append(f"{label} 判据={got!r} != {want!r}")
    return msgs


def probe_wuchong_76_default_keep_tapping() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _default_continue_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 B：三个正面终止点各自命中即停 + 零新增点击（先判据、后点击）
# ---------------------------------------------------------------------------
def _termination_failures(mod, run_fn=None) -> list:
    msgs: list[str] = []

    # 首帧就是终止点 → **零点击**（先判据、后点击的承重安全属性）。
    res_over, _o1 = _drive(mod, [CONTINUE_FRAME], run_fn=run_fn)
    if res_over.get("stopped") != "battle_over":
        msgs.append(f"首帧续关屏未停手：stopped={res_over.get('stopped')!r}（期望 battle_over）")
    if res_over.get("taps") != 0:
        msgs.append(f"首帧续关屏仍落点击：taps={res_over.get('taps')}（★先判据后点击★失败）")

    res_left, _o2 = _drive(mod, [LEFT_FRAMES["wuchong_room"]], run_fn=run_fn)
    if res_left.get("stopped") != "left":
        msgs.append(f"首帧被推出战斗未停手：stopped={res_left.get('stopped')!r}（期望 left）")
    if res_left.get("taps") != 0:
        msgs.append(f"首帧被推出战斗仍落点击：taps={res_left.get('taps')}（★先判据后点击★失败）")

    # 先点一会儿再命中终止点：命中那一刻**不落任何点击**就交还。
    #   ★判据：点击数 == 终止点**之前**的 continue 帧数（命中的那一帧绝不落点击）★。
    res2, obs2 = _drive(mod, [HUD_FRAME, HUD_FRAME, SETTLE_FRAME], run_fn=run_fn)
    if res2.get("stopped") != "battle_over":
        msgs.append(f"结算页中途命中未停手：stopped={res2.get('stopped')!r}")
    if obs2["verdicts"][-1] != mod.PAGE_OVER:
        msgs.append(f"最后一帧判据={obs2['verdicts'][-1]!r} != over（驱动无效）")
    if res2.get("taps") != 2:
        msgs.append(f"结算页命中帧仍落点击：taps={res2.get('taps')}（期望 2 = 命中的那一帧零点击）")

    res3, obs3 = _drive(mod, [HUD_FRAME, LEFT_FRAMES["wuchong_mode"]], run_fn=run_fn)
    if res3.get("stopped") != "left":
        msgs.append(f"被推出战斗中途命中未停手：stopped={res3.get('stopped')!r}")
    if res3.get("taps") != 1:
        msgs.append(f"被推出战斗命中帧仍落点击：taps={res3.get('taps')}（期望 1 = 命中的那一帧零点击）")
    return msgs


def probe_wuchong_76_three_termination_points() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _termination_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 C：计数 episode 闩锁（一场战斗只计一次）
# ---------------------------------------------------------------------------
def _reset_session(mod, tid: int) -> None:
    with mod._LOCK:
        mod._SESSION["task_id"] = tid
        mod._SESSION["fights_done"] = 0
        mod._SESSION["target_fights"] = 0
        mod._SESSION["battle_had_continue"] = False
        mod._SESSION["in_fight"] = False
        mod._SESSION["last_state"] = None
        mod._SESSION["last_observe_ts"] = 0.0
        mod._SESSION["unknown_count"] = 0
        mod._SESSION["room_first_ts"] = 0.0
        mod._SESSION["start_ts"] = time.monotonic()
        mod._SESSION["last_progress_ts"] = time.monotonic()


def _episode_latch_failures(mod, observe=None) -> list:
    msgs: list[str] = []
    obs = observe or mod._observe
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p76.json")
        try:
            mod.ledger.reset(mod.LEDGER_SCOPE)
            _reset_session(mod, TID)

            def done() -> int:
                with mod._LOCK:
                    return int(mod._SESSION["fights_done"])

            # (1) battle → unknown → battle → unknown → battle：HUD 闪烁**只计 1 场**。
            for st, items in ((mod.WUCHONG_BATTLE, []), ("unknown", []), (mod.WUCHONG_BATTLE, []),
                              ("unknown", []), (mod.WUCHONG_BATTLE, [])):
                obs(st, {}, items)
            if done() != 1:
                msgs.append(f"HUD 闪烁（battle→unknown→battle→unknown→battle）被计成 {done()} 场（应 1）")
            scope = mod.ledger.scope(mod.FIGHT_LEDGER_PREFIX)
            if scope != [f"{mod.FIGHT_LEDGER_PREFIX}/1"]:
                msgs.append(f"HUD 闪烁后账本={scope}（应只 1 笔）")

            # (2) battle → 房间（真正离开） → battle：计 2 场。
            obs(mod.WUCHONG_ROOM, {}, [])
            obs(mod.WUCHONG_BATTLE, {}, [])
            if done() != 2:
                msgs.append(f"真正离开后的新一场未计：fights_done={done()}（应 2）")

            # (3) GAMEOVER → 续关 → battle：不重复计（仍 1 场）。
            _reset_session(mod, TID)
            obs(mod.WUCHONG_BATTLE, {}, [])
            obs(mod.WUCHONG_BATTLE, {}, GAMEOVER_ITEMS)
            obs("loading", {}, [])
            obs(mod.WUCHONG_BATTLE, {}, [])
            if done() != 1:
                msgs.append(f"续关回到战斗被误计为新的一场：fights_done={done()}（应 1）")
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
            _reset_session(mod, TID)
    return msgs


def probe_wuchong_76_fight_episode_latch() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _episode_latch_failures(impl) == []


# ---------------------------------------------------------------------------
# 破坏件（prove-red 用；自带一份，绝不 import 别的守卫模块）
# ---------------------------------------------------------------------------
class _BrokenUnknownIsLeft:
    """坏实现 A：把**认不出的帧**判成 ``left``（= 旧 ``yield`` 让位）→ 引擎会停手。"""

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def page_verdict(self, items):  # noqa: N802
        state, _info = self._mod.classify(items)
        if state in ("unknown", "loading"):
            return self._mod.PAGE_LEFT
        return self._mod.page_verdict(items)


class _BrokenClickFirstBattle:
    """坏实现 B：循环**先点击、后判据**（首帧就是终止点也会先落一串点击）。"""

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def run_manual_battle(self, hooks, cadence):  # noqa: N802
        # ★坏：先点一串，再采判据（正确实现是先判据、后点击）★
        taps = 0
        hooks.burst_click(tuple(cadence.flipper), max(1, int(cadence.burst)),
                          max(20, int(cadence.flipper_gap_ms)))
        taps += max(1, int(cadence.burst))
        v = hooks.verdict()
        if v == self._mod.PAGE_OVER:
            return {"taps": taps, "swipes": [], "checks": 1, "stopped": "battle_over", "reason": ""}
        if v == self._mod.PAGE_LEFT:
            return {"taps": taps, "swipes": [], "checks": 1, "stopped": "left", "reason": ""}
        return {"taps": taps, "swipes": [], "checks": 1, "stopped": "left", "reason": "坏：先点后判"}


def _make_latchless_observe(mod):
    """坏实现 C：计数**不看 episode 闩锁**（= 旧实现 ``changed and state == battle``）→ 闪烁虚计。"""

    def _observe(state, info, items):  # noqa: N802
        now = time.monotonic()
        count = False
        with mod._LOCK:
            if mod.is_gameover_page(items):
                mod._SESSION["battle_had_continue"] = True
            changed = state != mod._SESSION["last_state"]
            mod._SESSION["last_observe_ts"] = now
            mod._SESSION["last_state"] = state
            count = changed and state == mod.WUCHONG_BATTLE and not mod._SESSION["battle_had_continue"]
        if count:
            mod._count_fight()

    return _observe


# ---------------------------------------------------------------------------
# prove-red
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_74_manual_nohud prove-red：逐一破坏实现，要求守卫各自变红")

    a = _default_continue_failures(impl)
    b = _termination_failures(impl)
    c = _episode_latch_failures(impl)
    for label, group in (("守卫 A", a), ("守卫 B", b), ("守卫 C", c)):
        for msg in group:
            print(f"      {label} 断言落空：{msg}")
    green = not (a or b or c)
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # G-A：认不出的帧判 left（旧 yield）→ 引擎停手 → 守卫 A 必红。
    broken_a = _default_continue_failures(_BrokenUnknownIsLeft(impl))
    print(f"  [{'PASS' if broken_a else 'FAIL'}] 默认继续点：认不出的帧判 left（旧 yield）-> "
          f"{'红' if broken_a else '仍绿'}" + (f"  {broken_a[0]}" if broken_a else ""))
    checks.append(bool(broken_a))

    # G-B：循环先点击、后判据（首帧终止点也先点）→ 守卫 B 必红。
    broken_b = _termination_failures(impl, run_fn=_BrokenClickFirstBattle(impl).run_manual_battle)
    print(f"  [{'PASS' if broken_b else 'FAIL'}] 三个终止点先判据后点击：先点后判 -> "
          f"{'红' if broken_b else '仍绿'}" + (f"  {broken_b[0]}" if broken_b else ""))
    checks.append(bool(broken_b))

    # G-C：计数不看 episode 闩锁（旧实现）→ HUD 闪烁虚计 → 守卫 C 必红。
    broken_c = _episode_latch_failures(impl, observe=_make_latchless_observe(impl))
    print(f"  [{'PASS' if broken_c else 'FAIL'}] 计数 episode 闩锁：不看闩锁（旧 changed+battle）-> "
          f"{'红' if broken_c else '仍绿'}" + (f"  {broken_c[0]}" if broken_c else ""))
    checks.append(bool(broken_c))

    # 收尾：把会话复位回干净态（避免污染其它挂点）。
    _reset_session(impl, TID)

    ok = green and all(checks)
    print("结果：★prove-red 成功★" if ok else "结果：★prove-red 失败★")
    return ok


HOOKS = [
    (
        "wuchong-74-nohud-default-keep-tapping",
        "#74",
        "默认一直点（2026-10-16 运维裁决）：手操不再用战斗 HUD 做判据；HUD 缺失 / unknown / loading "
        "帧一律**继续点**，绝不停手（旧行为会 yield/hud_miss）。用真实 page_verdict 判假帧序列驱动引擎："
        "持续点板、stopped=battle_over；PAGE_LEFT_STATES = 9 个已知非战斗页（不含 unknown/loading/battle/settle）",
        probe_wuchong_76_default_keep_tapping,
    ),
    (
        "wuchong-74-nohud-three-termination-points",
        "#74",
        "三个正面终止点各自命中即停：续关屏 / 结算页→battle_over、被推出战斗→left；且★先判据、后点击★"
        "（首帧就是终止点则 taps=0；命中那一刻不落任何点击就交还）",
        probe_wuchong_76_three_termination_points,
    ),
    (
        "wuchong-74-nohud-fight-episode-latch",
        "#74",
        "计数 episode 闩锁（一场只计一次）：battle→unknown→battle→unknown→battle 只计 1（真机 HUD 每 2~3s "
        "闪回 unknown 不再虚计）；battle→房间→battle 计 2（真正离开才清闩锁）；GAMEOVER→续关→battle 不重复计",
        probe_wuchong_76_fight_episode_latch,
    ),
]


if __name__ == "__main__":
    import sys as _sys  # noqa: PLC0415

    for _stream in (_sys.stdout, _sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)

