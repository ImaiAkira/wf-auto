# -*- coding: utf-8 -*-
"""#18 / ADR 0005：``LostClock`` 迷路时钟（纯离线，不需要设备）。

    .venv\\Scripts\\python.exe tools\\test_lost_clock.py

覆盖：
  1. ``in_fight`` 期间 300 秒 unknown **一律不计**（#76：战斗 episode 内不记起点）；
  2. 离开 unknown 即清点：``seconds_lost`` 归 0，``worst_seconds`` / ``last_known`` 留证；
  3. ``unknown → loading → unknown`` 要**重新计时**（连续秒数 ≠ 累计帧数）；
  4. ``lost_reason`` 两例（有 / 无 last_known），格式 ``连续 {n}s 认不出画面（…）``；
  5. ``observe()`` 真的在喂这只钟（含 in_fight 那条腿）；
  6. GiveUp 闸门真的用连续秒数收工，且遗留的旧帧数参数只忽略 + 警告一次。
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import time
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
sys.path.insert(0, str(AGENT_DIR))

import battle_loop_core as core  # noqa: E402

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _cfg(scene: str) -> core.SceneConfig:
    """最小真状态机配置：空 OCR 一律落到 unknown（本文件只考迷路时钟）。

    ``SceneConfig`` 要求状态机字段「配全或全不配」，``log_tag`` 又要非空才好在
    警告行里认出来，所以这里把七个字段都填上哑值（它们都不参与 LostClock 判定）。
    """
    return core.SceneConfig(
        scene=scene,
        state_prefix=scene,
        classify_order=("battle", "settle"),
        class_prefix="Lostclock",
        log_tag=scene,
        click_action="LostclockClick",
        max_stages=1,
        stage_re=re.compile(r"第(\d+)关"),
        dispatch_node="LostclockStop",
        coop_clock=lambda scene, state, sess, now: None,
    )


# ---------------------------------------------------------------------------
# 1. in_fight 期间不记起点（#76）
# ---------------------------------------------------------------------------
def test_in_fight_not_counted() -> None:
    print("\n== 1. in_fight 期间 300 秒 unknown 一律不计（#76）==")
    clock = core.LostClock()
    for t in range(0, 301, 10):
        clock.observe("unknown", float(t), in_fight=True)
        if clock.seconds_lost(float(t)) != 0.0:
            break
    check("战斗中 300s unknown：seconds_lost 恒为 0", clock.seconds_lost(300.0) == 0.0)
    check("战斗中 unknown 不写 worst_seconds", clock.worst_seconds == 0.0)
    check("战斗中 unknown 不算 last_known", clock.last_known is None)


# ---------------------------------------------------------------------------
# 2. 离开 unknown 清点
# ---------------------------------------------------------------------------
def test_leaving_unknown_clears() -> None:
    print("\n== 2. 离开 unknown 清点：秒数归 0，诊断量留存 ==")
    clock = core.LostClock()
    clock.observe("unknown", 1000.0)
    check("仍在 unknown：连续 3.5s", clock.seconds_lost(1003.5) == 3.5,
          str(clock.seconds_lost(1003.5)))
    clock.observe("lostclock_settle", 1004.0)
    check("命中已知页后 seconds_lost 归 0", clock.seconds_lost(2000.0) == 0.0)
    check("worst_seconds 记下这一段（4s）", clock.worst_seconds == 4.0,
          str(clock.worst_seconds))
    check("last_known = 最后已知页", clock.last_known == "lostclock_settle",
          str(clock.last_known))


# ---------------------------------------------------------------------------
# 3. unknown → loading → unknown 要重新计时
# ---------------------------------------------------------------------------
def test_restart_after_known_page() -> None:
    print("\n== 3. unknown → loading → unknown 重新计时（不是累计）==")
    clock = core.LostClock()
    clock.observe("unknown", 0.0)
    clock.observe("loading", 10.0)      # 任何非 unknown 页都清点
    clock.observe("unknown", 20.0)
    check("第二段的连续秒数从 20s 起算（5s，不是 25s）",
          clock.seconds_lost(25.0) == 5.0, str(clock.seconds_lost(25.0)))
    check("第一段 10s 只进 worst_seconds", clock.worst_seconds == 10.0,
          str(clock.worst_seconds))


# ---------------------------------------------------------------------------
# 4. lost_reason 两例
# ---------------------------------------------------------------------------
def test_lost_reason() -> None:
    print("\n== 4. lost_reason：三处场景同一句 ==")
    with_last = core.lost_reason(60.0, "phantom_settle")
    without = core.lost_reason(3.9, None)
    check("有 last_known",
          with_last == "连续 60s 认不出画面（最后已知页：phantom_settle）", with_last)
    check("无 last_known → 未知（秒数向下取整）",
          without == "连续 3s 认不出画面（最后已知页：未知）", without)
    check("缺省阈值 = 60s（ADR 0005）", core.DEFAULT_LOST_SEC == 60.0,
          str(core.DEFAULT_LOST_SEC))


# ---------------------------------------------------------------------------
# 5. observe() 真的在喂这只钟
# ---------------------------------------------------------------------------
def test_observe_feeds_clock() -> None:
    print("\n== 5. observe() 喂钟：已知页清点、in_fight 期间不打点 ==")
    cfg = _cfg("lostclock_observe")
    sess = core.session(cfg)
    check("会话字段是 LostClock 实例", isinstance(sess["lost"], core.LostClock),
          type(sess["lost"]).__name__)
    core.observe(cfg, "unknown", {}, [])
    lost = sess["lost"]
    check("unknown 帧：真的开始计时",
          lost.seconds_lost(time.monotonic() + 5.0) >= 4.99,
          str(lost.seconds_lost(time.monotonic() + 5.0)))
    core.observe(cfg, f"{cfg.state_prefix}_settle", {}, [])
    check("结算页（已知页）清点并记住 last_known",
          lost.seconds_lost(time.monotonic()) == 0.0
          and lost.last_known == f"{cfg.state_prefix}_settle",
          str(lost.last_known))
    with core.lock(cfg):
        sess["in_fight"] = True
    core.observe(cfg, "unknown", {}, [])
    check("in_fight 期间再进 unknown：不记起点",
          lost.seconds_lost(time.monotonic() + 300.0) == 0.0)


# ---------------------------------------------------------------------------
# 6. GiveUp 闸门用连续秒数；旧参数只忽略 + 警告一次
# ---------------------------------------------------------------------------
class _Argv:
    def __init__(self, param):
        self.image = object()
        self.task_detail = None
        self.custom_recognition_param = json.dumps(param)


def test_giveup_uses_seconds() -> None:
    print("\n== 6. GiveUp：连续秒数过阈值即收工，旧帧数参数忽略 + 警告一次 ==")
    cfg = _cfg("lostclock_giveup")
    sess = core.session(cfg)
    now = time.monotonic()
    with core.lock(cfg):
        # 预置一段「已经连续 61s 认不出」的画面；last_state 对齐 + 刷新去重时间戳，
        # 让 giveup 内部的 observe() 这一帧不再重新打点（只读这只钟）。
        sess["last_state"] = "unknown"
        sess["last_observe_ts"] = now
        sess["lost"].last_known = f"{cfg.state_prefix}_settle"
        sess["lost"].observe("unknown", now - 61.0)
    cls = core.make_giveup_reco(cfg, lambda context, image, entry="OcrTask": [])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        first = cls().analyze(None, _Argv({"lost_sec": 60, "unknown_limit": 120}))
        second = cls().analyze(None, _Argv({"lost_sec": 60, "unknown_limit": 120}))
    reason = f"连续 61s 认不出画面（最后已知页：{cfg.state_prefix}_settle）"
    check("连续 61s ≥ lost_sec=60 → giveup 且 reason 用 lost_reason",
          bool(first.detail.get("giveup")) and first.detail.get("reason") == reason,
          str(first.detail))
    check("第二次同样收工（判定只看连续秒数）",
          bool(second.detail.get("giveup")) and second.detail.get("reason") == reason)
    warn = (
        f"[{cfg.log_tag}] 忽略过时参数 unknown_limit=120"
        "（已换成 lost_sec，见 ADR 0005）"
    )
    lines = out.getvalue().splitlines()
    check("旧参数 unknown_limit 被忽略并打一行警告（只一次）",
          lines.count(warn) == 1, str([ln for ln in lines if "忽略过时参数" in ln]))


def main() -> int:
    test_in_fight_not_counted()
    test_leaving_unknown_clears()
    test_restart_after_known_page()
    test_lost_reason()
    test_observe_feeds_clock()
    test_giveup_uses_seconds()
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("test_lost_clock: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
