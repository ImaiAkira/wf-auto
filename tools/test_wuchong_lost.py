# -*- coding: utf-8 -*-
"""#24 / ADR 0005：五重决战的「迷路」闸门改成**连续秒数**（#76 并入 ``LostClock``）。

    .venv\\Scripts\\python.exe tools\\test_wuchong_lost.py

覆盖（纯离线，不需要游戏 / 设备 —— 手操战斗本来就不走 MAA 识别节点）：
  1. 战斗 episode 内 300s 长的 unknown 序列**不**给时钟打点（#76 语义仍在）；
  2. 离开战斗后的 unknown **照旧打点**：连续 61s → ``wuchong_giveup`` 触发且文案正确；
  3. 旧帧数参数被**忽略并只警告一次**（绝不静默恢复「未知画面累计」）。

判据真源：``docs/adr/0005-unknown-is-time-not-frames.md``；接线点 =
``agent/wuchong_impl._observe``（喂钟）+ ``WuchongGiveUpRecognition.analyze``（闸门）。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import battle_loop_core as core  # noqa: E402
import wuchong_impl as wc  # noqa: E402
from scene import wuchong as wsc  # noqa: E402

FAILS: list[str] = []

#: 真机合并框战斗帧（HUD 一行读完 = ``wuchong_battle``；#74 的判据证据）。
BATTLE_ITEMS = [("时间 29:30 分数 38629797530", [34, 1220, 400, 40])]


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _reset_session() -> None:
    """把会话钉成已知起点（换任务 / 全新迷路时钟 / 不在战斗中）。"""
    with wc._LOCK:
        wc._SESSION["task_id"] = 570_200_000 + int(time.monotonic() * 1000) % 900
        wc._SESSION["fights_done"] = 0
        wc._SESSION["target_fights"] = 0
        wc._SESSION["start_ts"] = time.monotonic()
        wc._SESSION["last_progress_ts"] = time.monotonic()
        wc._SESSION["room_first_ts"] = 0.0
        wc._SESSION["zero_tap_yield_streak"] = 0
        wc._SESSION["last_state"] = None
        wc._SESSION["last_observe_ts"] = 0.0
        wc._SESSION["battle_had_continue"] = False
        wc._SESSION["in_fight"] = False
        wc._SESSION["lost"].reset()


def _drive(seq: list[str]) -> core.LostClock:
    """按真机语义驱动真实 ``_observe``（战斗帧带真机 HUD，其余帧空 OCR）。"""
    _reset_session()
    for state in seq:
        wc._observe(state, {}, BATTLE_ITEMS if state == "wuchong_battle" else [])
    with wc._LOCK:
        return wc._SESSION["lost"]


class _Argv:
    """最小 argv：``read_param`` 只读 ``custom_recognition_param``（JSON 串）。"""

    def __init__(self, param: dict) -> None:
        self.image = object()
        self.task_detail = None
        self.custom_recognition_param = json.dumps(param)


def _giveup(param: dict, items: list | None = None) -> tuple[dict, str]:
    """驱动真实 ``WuchongGiveUpRecognition`` 一次，返回 (detail, stdout)。"""
    real_ocr = wc._ocr
    out = io.StringIO()
    try:
        wc._ocr = lambda context, image, entry="OcrTask": list(items or [])
        with contextlib.redirect_stdout(out):
            res = wc.WuchongGiveUpRecognition().analyze(None, _Argv(param))
    finally:
        wc._ocr = real_ocr
    return dict(res.detail or {}), out.getvalue()


# ---------------------------------------------------------------------------
# 1. 战斗 episode 内 300s unknown：一次都不许给时钟打点（#76 → LostClock）
# ---------------------------------------------------------------------------
def test_in_fight_not_counted() -> None:
    print("\n== 1. 战斗 episode 内 300s unknown 不启动时钟（#76 并入 LostClock）==")
    # (a) 原语层：真·300s 的 unknown 序列，in_fight=True 时秒数恒为 0。
    clock = core.LostClock()
    for t in range(0, 301, 10):
        clock.observe("unknown", float(t), in_fight=True)
    check("战斗中 300s unknown：seconds_lost 恒为 0", clock.seconds_lost(300.0) == 0.0,
          str(clock.seconds_lost(300.0)))
    check("战斗中 unknown 不写 worst_seconds / last_known",
          clock.worst_seconds == 0.0 and clock.last_known is None)

    # (b) 接线层：真实 _observe 在 in_fight 期间喂钟时**不打点**（给足 300s 仍为 0）。
    lost = _drive(["wuchong_battle", "unknown"] * 6)
    check("battle/unknown 闪烁 6 轮后仍在战斗 episode 内",
          bool(wc._SESSION["in_fight"]))
    check("接线层：战斗中 unknown 不打点（300s 后仍为 0）",
          lost.seconds_lost(time.monotonic() + 300.0) == 0.0,
          str(lost.seconds_lost(time.monotonic() + 300.0)))


# ---------------------------------------------------------------------------
# 2. 离开战斗后 unknown 照旧打点，连续 61s 触发收工且文案正确
# ---------------------------------------------------------------------------
def test_leave_fight_then_lost() -> None:
    print("\n== 2. 离开战斗后连续 61s unknown → 收工（文案 = lost_reason）==")
    lost = _drive(["wuchong_battle", "unknown", "wuchong_team", "unknown"])
    check("编队页（∈ _FIGHT_LEAVE_STATES）清掉 in_fight",
          wc._SESSION["in_fight"] is False)
    check("离开本场后 last_known = 最后已知页", lost.last_known == "wuchong_team",
          str(lost.last_known))
    # 61s 之后 ≈ 61s（不是 61s + 历史累计）⇒ 连续秒数真的从离开战斗后的那一帧起算。
    secs = lost.seconds_lost(time.monotonic() + 61.0)
    check("离开战斗后的 unknown 从 0 起算（60.9s ≤ 61s ≤ 61.5s）",
          60.9 <= secs <= 61.5, f"{secs:.2f}s")

    # 预置「已经连续 61.2s 认不出」：驱动真实 GiveUp 闸门（它内部会再喂一帧 unknown，不清点）。
    _reset_session()
    now = time.monotonic()
    with wc._LOCK:
        lost = wc._SESSION["lost"]
        lost.last_known = "wuchong_team"
        lost.observe("unknown", now - 61.2)
        wc._SESSION["last_state"] = "unknown"
        wc._SESSION["last_observe_ts"] = now
    detail, out = _giveup({"lost_sec": 60})
    reason = "连续 61s 认不出画面（最后已知页：wuchong_team）"
    check("连续 61s ≥ lost_sec=60 → 触发收工",
          detail.get("giveup") is True, str(detail))
    check("收工文案 = 共享 lost_reason（连续 Ns + 最后已知页）",
          detail.get("reason") == reason, str(detail.get("reason")))
    check("没有回退成旧的「未知画面累计 N 次」文案",
          "未知画面累计" not in str(detail.get("reason")),
          str(detail.get("reason")))

    # 差一秒不触发：59.2s < 60s（闸门是 ≥，不是「差不多」）。
    _reset_session()
    now = time.monotonic()
    with wc._LOCK:
        lost = wc._SESSION["lost"]
        lost.last_known = "wuchong_team"
        lost.observe("unknown", now - 59.2)
        wc._SESSION["last_state"] = "unknown"
        wc._SESSION["last_observe_ts"] = now
    detail_59, _out = _giveup({"lost_sec": 60})
    check("连续 59s < lost_sec=60 → 不收工", detail_59.get("giveup") is False,
          str(detail_59))


# ---------------------------------------------------------------------------
# 3. 旧帧数参数被忽略且只警告一次（ADR 0005 兼容口径）
# ---------------------------------------------------------------------------
def test_stale_unknown_limit_ignored() -> None:
    print("\n== 3. 旧参数被忽略 + 只警告一次（绝不静默恢复计数）==")
    # 警告是「每次进程每场景一行」：先清掉，保证本测试自己能看到那唯一一行。
    core._STALE_PARAM_WARNED.discard((core._STALE_FRAME_LIMIT_PARAM, "wuchong"))
    _reset_session()
    now = time.monotonic()
    with wc._LOCK:
        wc._SESSION["lost"].observe("unknown", now - 5.0)
        wc._SESSION["last_state"] = "unknown"
        wc._SESSION["last_observe_ts"] = now
    param = {"lost_sec": 60, "unknown_limit": 1}   # 若旧参数生效，1 帧就会收工。
    detail, out1 = _giveup(param)
    _detail2, out2 = _giveup(param)
    warn = "[wuchong] 忽略过时参数 unknown_limit=1（已换成 lost_sec，见 ADR 0005）"
    lines = (out1 + out2).splitlines()
    check("旧参数 unknown_limit 被忽略（5s < 60s 不收工）",
          detail.get("giveup") is False, str(detail))
    check("旧参数只警告一次（两帧只一行）", lines.count(warn) == 1,
          str([ln for ln in lines if "忽略过时参数" in ln]))

    # 上界写多大都挡不住真·迷路：判定只看连续秒数（忽略旧参数的另一面）。
    _reset_session()
    now = time.monotonic()
    with wc._LOCK:
        lost = wc._SESSION["lost"]
        lost.last_known = "wuchong_team"
        lost.observe("unknown", now - 61.2)
        wc._SESSION["last_state"] = "unknown"
        wc._SESSION["last_observe_ts"] = now
    detail_big, _out = _giveup({"lost_sec": 60, "unknown_limit": 99999})
    check("unknown_limit=99999 挡不住连续 61s 的迷路（旧参数不再参与判定）",
          detail_big.get("giveup") is True, str(detail_big))

    # 场景阈值真源：scene.wuchong.LOST_SEC 与实现快照一致（ADR 0005 数据化）。
    check("scene.wuchong.LOST_SEC = 60（与实现同值）",
          wsc.LOST_SEC == 60 and wc.LOST_SEC == 60,
          f"scene={wsc.LOST_SEC} impl={wc.LOST_SEC}")

    # override 完全不写 lost_sec 时按场景阈值判（数据化，不进 GUI 选项）。
    _reset_session()
    now = time.monotonic()
    with wc._LOCK:
        lost = wc._SESSION["lost"]
        lost.last_known = "wuchong_team"
        lost.observe("unknown", now - 61.2)
        wc._SESSION["last_state"] = "unknown"
        wc._SESSION["last_observe_ts"] = now
    detail_default, _out = _giveup({})
    check("override 不写 lost_sec 也按场景阈值 60s 收工",
          detail_default.get("giveup") is True
          and detail_default.get("reason")
          == "连续 61s 认不出画面（最后已知页：wuchong_team）",
          str(detail_default))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        saved_file = getattr(wc.ledger, "_DEFAULT", None)
        wc.ledger.set_file(Path(td) / "progress.json")
        try:
            test_in_fight_not_counted()
            test_leave_fight_then_lost()
            test_stale_unknown_limit_ignored()
        finally:
            wc.ledger.set_file(None)
            if saved_file is not None:
                wc.ledger._DEFAULT = saved_file
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("test_wuchong_lost: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
