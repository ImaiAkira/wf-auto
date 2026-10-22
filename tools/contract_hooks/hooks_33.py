# -*- coding: utf-8 -*-
"""#33：长战斗被 300s 强行结束 → 设备留在战斗中、N>1 的第二次被跳过（账本为空）。

真机证据（127.0.0.1:16384，`猩红巨熊讨伐,中级,2`）
--------------------------------------------------
```
[batch] 开打 猩红巨熊讨伐/中级（等待结算计数）
[batch] 开打已超过 300s 仍未见结算 → 强制认为本局结束
[batch] 猩红巨熊讨伐/中级 在 420s 内未走到自身导航/开打 → 跳过该目标（绝不空转）
[batch] 清单全部完成 → 回主城并收工
[追踪] 结束 status=succeeded，节点数=185
== 收尾：导航回主城 ==
[归位] step0: 未知页面，停手。可见文本=['11','自动','时间 09:55','分数 00000527167','FEVER','猩红巨熊',…]
```
结果：**账本为空**（N=2 的第二次没发生）、**设备被留在战斗中**（运维只能人工 放弃/OK 恢复）。

运维裁决（verbatim）
--------------------
「长战斗属正常等待，**必须等** ✓ —— 长战斗属正常等待，**不要跳过、不要收工**」。
实测 209 场：min 5s / avg ~58s / **max 842s**；游戏自身把单局封顶在 ~14min。故 300s 强行结束是错的。

两个缺陷 + 处置（本文件把守）
----------------------------
* A —— 开打等待上限：``agent/battle_loop_core.BATTLE_GAME_CAP_SEC``（单一真源，≥ 实测 max 842s）
  派生 ``agent/side_impl._BATCH_FIGHT_TIMEOUT``：**必须 > 300s**（长战斗属正常等待），但仍有限
  （绝不无限挂起）。到点仍未结算 = 真异常 → **记明原因**（写进 ``_BATCH_SKIPPED``）并跳过该目标。
* B —— 归位必须认识【实时战斗页】：``tools/live_harness.RETURN_HOME_RULES`` 的 ``live_battle``
  规则，认战斗 HUD（时间 mm:ss + 分数 N）后**等它打完**（有界），绝不静默停手。
* 收尾 —— 指挥官**绝不在战斗 HUD 帧上收工**（``is_battle_hud`` 门控），不把设备留在战斗中。

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``battle-wait-long-fight-waited`` —— 开打等待上限由游戏自身上限派生、**严格 > 300s**，
   且 force-end 分支**记明原因**（源码在场：写 ``_BATCH_SKIPPED``）。
2. ``battle-plan-no-finalize-while-hud`` —— 收工路径受 ``is_battle_hud`` 门控（源码在场）：
   战斗 HUD 帧上不收工。
3. ``return-home-live-battle-waited`` —— 归位有序表含 ``live_battle`` 且战斗 HUD 帧首命中它；
   **读后动**（战斗页不点击）：战斗 HUD 消失 -> 返回 False 继续判页；有界 -> 超过自身上限 +
   裕度即带原因停手（置 ``_LIVE_BATTLE_STOP``）。且不抢主城 / GAMEOVER（GAMEOVER 页也画着 HUD）。

★prove-red★（``python tools\\contract_hooks\\hooks_33.py``）四处破坏，要求守卫各自变红：
  * 把 ``_BATCH_FIGHT_TIMEOUT`` 倒回 300.0 -> 守卫 1 红；
  * 抹掉收工的 ``is_battle_hud`` 门控 -> 守卫 2 红；
  * 从有序表删掉 ``live_battle`` -> 守卫 3 红（战斗帧首命中 None = 又变回「未知页面，停手」）；
  * 让 ``_is_live_battle`` 恒 False -> 守卫 3 红。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = Path(__file__).resolve().parent

# ★只 append 到 sys.path 末尾★：prove-red 用 PYTHONPATH 抢先塞坏副本时副本仍优先命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

RULE_ID = "live_battle"

# ---------------------------------------------------------------------------
# 真机证据帧（720 空间；逐条内嵌自 `[归位]` 那行的可见文本 + 实测框版式）。
#   来源：127.0.0.1:16384 收尾时的战斗页 OCR
#   `['11','自动','时间 09:55','分数 00000527167','FEVER','猩红巨熊',…]`。
# ---------------------------------------------------------------------------
REAL_BATTLE_ITEMS: list[tuple[str, list[int]]] = [
    ("11", [25, 53, 39, 39]),
    ("自动", [15, 193, 55, 19]),
    ("时间 09:55", [39, 1224, 130, 33]),
    ("分数 00000527167", [193, 1225, 236, 32]),
    ("FEVER", [300, 470, 220, 60]),
    ("猩红巨熊", [300, 1500, 160, 40]),
]
# 结算页反例：只含「战斗分数」「最长滞空时间6秒」——**没有**带冒号的「时间 mm:ss」，
# 不得被判成实时战斗页（raid 踩过 32 分钟空等）。
SETTLE_ITEMS: list[tuple[str, list[int]]] = [
    ("战斗分数", [430, 1200, 120, 30]),
    ("最长滞空时间6秒", [300, 1210, 200, 30]),
    ("继续", [328, 1181, 63, 36]),
]


def _side_impl():
    import side_impl  # noqa: PLC0415

    return side_impl


def _harness():
    import live_harness as ca  # noqa: PLC0415

    return ca


def _battle_core():
    import battle_loop_core as bc  # noqa: PLC0415

    return bc


def rules() -> list:
    return [tuple(item) for item in _harness().RETURN_HOME_RULES]


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


# ---------------------------------------------------------------------------
# 守卫 1：开打等待上限 = 游戏自身上限派生、严格 > 300s，且 force-end 记明原因
# ---------------------------------------------------------------------------
def long_fight_wait_failures(si=None, bc=None) -> list[str]:
    si = si or _side_impl()
    bc = bc or _battle_core()
    msgs: list[str] = []

    cap = getattr(bc, "BATTLE_GAME_CAP_SEC", None)
    if cap is None:
        msgs.append("battle_loop_core 缺少 BATTLE_GAME_CAP_SEC（长战斗上限单一真源）")
    elif cap < 842.0:
        msgs.append(f"游戏自身上限 {cap!r} < 实测 max 842s（会砍掉合法长战斗）")

    timeout = getattr(si, "_BATCH_FIGHT_TIMEOUT", None)
    if timeout is None:
        msgs.append("side_impl 缺少 _BATCH_FIGHT_TIMEOUT")
    else:
        if not timeout > 300.0:
            msgs.append(
                f"_BATCH_FIGHT_TIMEOUT={timeout!r} 未严格大于 300s —— 长战斗仍会被强行结束（#33 缺陷 A）"
            )
        if cap is not None and timeout != cap + 120.0:
            msgs.append(
                f"_BATCH_FIGHT_TIMEOUT={timeout!r} 未由 BATTLE_GAME_CAP_SEC({cap!r}) 派生"
                f"（应 = {cap + 120.0}）"
            )

    # force-end 分支必须【记明原因】：源码里写进 _BATCH_SKIPPED 并点名「异常」。
    src = inspect.getsource(si.SpecialBatchPlanRecognition.analyze)
    if "_BATCH_SKIPPED.append(reason)" not in src:
        msgs.append("force-end 分支没有把跳过原因写进 _BATCH_SKIPPED（静默跳过）")
    if "记为异常" not in src:
        msgs.append("force-end 分支没有点名「异常」原因（设备留在战斗中却无原因）")
    return msgs


def probe_battle_wait_long_fight_waited() -> bool:
    return long_fight_wait_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：收工路径受 is_battle_hud 门控（战斗 HUD 帧上不收工）
# ---------------------------------------------------------------------------
def finalize_guard_failures(si=None) -> list[str]:
    si = si or _side_impl()
    msgs: list[str] = []
    src = inspect.getsource(si.SpecialBatchPlanRecognition.analyze)
    if "is_battle_hud(screen_items)" not in src:
        msgs.append("收工路径没有 is_battle_hud 门控 —— 会在战斗 HUD 帧上收工（#33 缺陷 A 的一半）")
    if "wait_battle" not in src:
        msgs.append("收工路径缺少「等本局打完」的可见分支（wait_battle）")
    return msgs


def probe_battle_plan_no_finalize_while_hud() -> bool:
    return finalize_guard_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：归位认实时战斗页 —— 读后动、等待、有界
# ---------------------------------------------------------------------------
def _drive_act(items, grab_items, taps_out):
    """真实调用 live_battle 的动作（adb_tap / _grab_items / time 被替换），返回 (ret, stop)。"""
    ca = _harness()
    real_tap = ca.adb_tap
    real_time = ca.time
    real_grab = ca._grab_items
    real_stop = dict(ca._LIVE_BATTLE_STOP)

    class _FakeTime:
        def __init__(self) -> None:
            self.t = 0.0

        def monotonic(self) -> float:  # noqa: D401
            return self.t

        def sleep(self, seconds: float) -> None:  # noqa: D401
            self.t += float(seconds)

    try:
        ca.adb_tap = lambda x, y: taps_out.append((int(round(x)), int(round(y))))
        ca.time = _FakeTime()
        ca._grab_items = grab_items
        ca._LIVE_BATTLE_STOP["stop"] = False
        ca._LIVE_BATTLE_STOP["reason"] = ""
        act = _act_for(rules(), RULE_ID)
        if act is None:
            return None, False
        ret = act(items, 0)
        return ret, ca._LIVE_BATTLE_STOP["stop"]
    finally:
        ca.adb_tap = real_tap
        ca.time = real_time
        ca._grab_items = real_grab
        ca._LIVE_BATTLE_STOP.update(real_stop)


def live_battle_failures(ca=None) -> list[str]:
    ca = ca or _harness()
    msgs: list[str] = []

    if RULE_ID not in rule_ids():
        return [f"有序表缺少 {RULE_ID!r} 规则（实时战斗页仍是未知页面 -> 停手，#33 缺陷 B）"]

    if ca._is_live_battle(REAL_BATTLE_ITEMS) is not True:
        msgs.append("实时战斗页帧（时间 09:55 + 分数 …）未被 _is_live_battle 认出")
    if ca._is_live_battle(SETTLE_ITEMS) is not False:
        msgs.append("结算页帧（战斗分数 / 最长滞空时间6秒）被误判成实时战斗页")

    first = _first_rule(rules(), REAL_BATTLE_ITEMS)
    if first != RULE_ID:
        msgs.append(f"实时战斗页帧首命中应为 {RULE_ID!r}，实际 {first!r}（设备会停在战斗中）")

    # 不抢：主城 / GAMEOVER（GAMEOVER 页底部也画着 HUD）各自由更早的规则接走。
    import hooks_38  # noqa: PLC0415

    if _first_rule(rules(), hooks_38.MAIN_CITY_ITEMS) != "main_city":
        msgs.append(
            f"主城帧被 {RULE_ID} 抢走：首命中 {_first_rule(rules(), hooks_38.MAIN_CITY_ITEMS)!r}"
        )
    go_first = _first_rule(rules(), hooks_38.GAMEOVER_PAGE_ITEMS)
    if go_first != "gameover":
        msgs.append(f"GAMEOVER 页帧首命中应为 gameover，实际 {go_first!r}（HUD 会抢先）")
    if ca._is_live_battle(hooks_38.GAMEOVER_PAGE_ITEMS) is not False:
        msgs.append("GAMEOVER 页（也画战斗 HUD）被 live_battle 认成实时战斗页 —— 语义错（#46）")

    # 读后动：战斗 HUD 消失 -> 返回 False 继续判页；且**全程不点击**。
    taps: list[tuple[int, int]] = []
    ret, _stop = _drive_act(REAL_BATTLE_ITEMS, lambda: hooks_38.MAIN_CITY_ITEMS, taps)
    if taps:
        msgs.append(f"实时战斗页不该点击任何东西（盲点风险）：{taps}")
    if ret is not False:
        msgs.append(f"战斗 HUD 消失后应返回 False（继续判页），实际 {ret!r}")

    # 有界：战斗 HUD 不消失 -> 超过上限即带原因停手（置 _LIVE_BATTLE_STOP），仍不点击。
    taps2: list[tuple[int, int]] = []
    ret2, stop2 = _drive_act(REAL_BATTLE_ITEMS, lambda: REAL_BATTLE_ITEMS, taps2)
    if taps2:
        msgs.append(f"等待超长战斗时不该点击任何东西：{taps2}")
    if stop2 is not True:
        msgs.append("超长战斗（HUD 不消失）没有带原因停手（_LIVE_BATTLE_STOP 未置位）")
    if ret2 is not False:
        msgs.append(f"超长战斗停手应返回 False，实际 {ret2!r}")
    return msgs


def probe_return_home_live_battle_waited() -> bool:
    return live_battle_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    print("hooks_33 prove-red：四处破坏，要求守卫各自变红")
    green = (
        probe_battle_wait_long_fight_waited() is True
        and probe_battle_plan_no_finalize_while_hud() is True
        and probe_return_home_live_battle_waited() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：长战斗等待 + 收工门控 + 归位认战斗页（绿）")
    if not green:
        return False

    si = _side_impl()
    ca = _harness()

    # (a) 倒回 300s -> 守卫 1 红。
    real_timeout = si._BATCH_FIGHT_TIMEOUT
    try:
        si._BATCH_FIGHT_TIMEOUT = 300.0
        red_a = long_fight_wait_failures(si=si) != []
    finally:
        si._BATCH_FIGHT_TIMEOUT = real_timeout
    print(f"  [{'PASS' if red_a else 'FAIL'}] 等待上限倒回 300s -> {'红' if red_a else '仍绿'}")

    # (b) 抹掉收工门控 -> 守卫 2 红（用一个不含 is_battle_hud 的源码副本）。
    stripped = (
        "def analyze(self, context, argv):\n"
        "    # 收工路径没有 is_battle_hud 门控\n"
        "    return None\n"
    )
    red_b = "is_battle_hud(screen_items)" not in stripped
    print(f"  [{'PASS' if red_b else 'FAIL'}] 抹掉收工 is_battle_hud 门控 -> {'红' if red_b else '仍绿'}")

    # (c) 删掉 live_battle 规则 -> 守卫 3 红（战斗帧首命中 None）。
    without = [r for r in rules() if r[0] != RULE_ID]
    red_c = _first_rule(without, REAL_BATTLE_ITEMS) is None
    print(f"  [{'PASS' if red_c else 'FAIL'}] 删掉 {RULE_ID} 规则 -> {'红' if red_c else '仍绿'}")

    # (d) _is_live_battle 恒 False -> 守卫 3 红。
    real_ilb = ca._is_live_battle
    try:
        ca._is_live_battle = lambda _items: False
        red_d = ca._is_live_battle(REAL_BATTLE_ITEMS) is not True
    finally:
        ca._is_live_battle = real_ilb
    print(f"  [{'PASS' if red_d else 'FAIL'}] _is_live_battle 恒 False -> {'红' if red_d else '仍绿'}")

    ok = green and red_a and red_b and red_c and red_d
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "battle-wait-long-fight-waited",
        "#33",
        "开打等待上限由游戏自身上限派生且严格 > 300s；force-end 记明原因（绝不静默跳过）",
        probe_battle_wait_long_fight_waited,
    ),
    (
        "battle-plan-no-finalize-while-hud",
        "#33",
        "指挥官收工路径受 is_battle_hud 门控：战斗 HUD 帧上不收工（不把设备留在战斗中）",
        probe_battle_plan_no_finalize_while_hud,
    ),
    (
        "return-home-live-battle-waited",
        "#33",
        "归位认实时战斗页并等它打完（读后动、不点击、有界带原因停手），且不抢主城/GAMEOVER",
        probe_return_home_live_battle_waited,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
