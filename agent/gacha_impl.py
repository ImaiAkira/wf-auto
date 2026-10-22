"""扭蛋（抽卡）：在当前池子抽 N 发十连，抽满即停（#26）。

## 为什么需要 agent 侧计数

MAA 的 ``max_hit`` 是**整个任务共享**的计数器，用光后节点只是**静默从 next 里消失**，
不会结束任务（``.research/3.1-pipeline.md`` / ``docs/guide/max-hit-debt.md``）。
旧实现正是栽在这里：``GachaContinue10.max_hit`` 用光后流程落到 ``GachaWait``
（DirectHit 兜底）→ 无限空转，只能手动停。所以「抽满 N 发」必须有一个**显式出口**，
本模块提供它（与五重决战「打几次」同一套 shape：agent 计数 → 命中 → 节点 StopTask）。

## 一发的口径（承重）

**汇总页出现** = 这一发真的抽出去了的正面证据。计数点放在这里，而不是「点了确认框」：
用户可能在确认框上点「取消」，那一下不算抽。

真机实测（2026-10-19，720 空间）：
* 池子页 = 「1次抽取」+「10连抽取」两个按钮**同时**在屏（汇总页没有「1次抽取」）
* 汇总页 = 「继续」+「10连抽取」
* 揭示页 = 只有「跳过」/「全部跳过」，两个页面判据都不命中 → 不计数、不误停

## 两个出口

* :class:`GachaCountRecognition` —— 抽满 N 发 → 命中（pipeline 点「前往扭蛋首页」回池子页
  → ``GachaStop`` 的 StopTask）。**收尾不回主城**（运维口径：回扭蛋池页即可）。
* :class:`GachaStallRecognition` —— 连续 ``no_progress_sec`` 秒没有新增一发 → 带原因收工。
  纯时钟判断，**不跑 OCR**（每帧多一次全屏 OCR 会拖慢整个循环）。
  没见过的确认框（例如某个池子的第三种文案）就靠这道闸门收口，**绝不猜着点**。

## 计数是会话态，不落账本

``progress.json`` 只记「完成了什么」（GLOSSARY「账本」），而「这次抽到第几发」是会话状态，
换 ``task_id`` 清零即可。跨重启续抽不做（本票范围外）。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from maa.custom_recognition import CustomRecognition

import reporting
from gacha_pages import has_continue, is_pool_page, is_summary_page
from maa_util import ocr_all as _ocr_all, read_param as _read_param

#: 用户可见名字（进度线用，``reporting.Progress`` 的唯一来源）。
DISPLAY = "抽卡"

#: 默认抽几发（GUI 选项会覆盖；这里给 pipeline 直跑时的兜底）。
DEFAULT_TIMES = 1

#: 无进展闸门（秒）。一次完整循环（确认 → 加载 → 揭示 → 汇总）真机约 10~25s，60s 足够。
NO_PROGRESS_SEC = 60.0

_LOCK = threading.Lock()
_SESSION: dict = {
    "task_id": None,
    "times": DEFAULT_TIMES,
    "done": 0,
    # 「当前这一帧是不是汇总页」的边沿闩锁：同一个汇总页连续多帧只计一次。
    "summary_seen": False,
    # 是否已经开抽过（见过非汇总页）。★起点就在汇总页时，那一发不计入 N★。
    "armed": False,
    "last_progress_ts": 0.0,
    "said_target": False,
}

_PROGRESS: Optional[reporting.Progress] = None


# ---------------------------------------------------------------------------
# 用户可见输出（格式只有 reporting 一处）
# ---------------------------------------------------------------------------
def _say(text: str) -> None:
    reporting.say(text)


def _log(text: str) -> None:
    reporting.log(text)


def _progress(times: Optional[int] = None) -> reporting.Progress:
    global _PROGRESS
    if _PROGRESS is None:
        _PROGRESS = reporting.Progress(DISPLAY, total=int(times or 0), unit="发")
    elif times:
        _PROGRESS.total = max(int(times), 0)
    return _PROGRESS


def _start_progress(times: int) -> str:
    return _progress(times).start(total=int(times))


def _step_progress(n: int) -> str:
    return _progress().step(int(n))


def _done_progress(reason: str) -> str:
    return _progress().done(str(reason or ""))


def _sync_task(task_id) -> None:
    """换了一次任务就清空会话计数（含进度线），让新一轮从 1 开始。"""
    global _PROGRESS
    if task_id is None:
        return
    with _LOCK:
        if _SESSION["task_id"] == task_id:
            return
        _SESSION["task_id"] = task_id
        _SESSION["done"] = 0
        _SESSION["summary_seen"] = False
        _SESSION["armed"] = False
        _SESSION["last_progress_ts"] = 0.0
        _SESSION["said_target"] = False
        _PROGRESS = None


# ---------------------------------------------------------------------------
# 页面判据：实现在 gacha_pages（纯函数、不导入 maa，离线测试可直接 import）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 出口一：抽满 N 发
# ---------------------------------------------------------------------------
class GachaCountRecognition(CustomRecognition):
    """数「汇总页出现」= 已抽几发；到 N 命中。

    pipeline 侧该节点的 action 是点「前往扭蛋首页」（回扭蛋池页），next 是 ``GachaStop``
    （DirectHit + StopTask）。命中即收工，**不回主城**。
    """

    def analyze(self, context, argv):
        param = _read_param(argv)
        try:
            times = max(1, int(param.get("times") or DEFAULT_TIMES))
        except (TypeError, ValueError):
            times = DEFAULT_TIMES

        _sync_task(getattr(argv.task_detail, "task_id", None))
        items = _ocr_all(context, argv.image, param.get("ocr_entry") or "OcrTask")

        now = time.monotonic()
        summary = is_summary_page(items)
        can_continue = has_continue(items) if summary else False
        with _LOCK:
            _SESSION["times"] = times
            if _SESSION["last_progress_ts"] <= 0:
                _SESSION["last_progress_ts"] = now
            said = bool(_SESSION["said_target"])
            _SESSION["said_target"] = True

            just_counted = False
            if not summary:
                # 见过非汇总页 = 这一轮真的开抽过了（下一张汇总页才算一发）。
                # ★起点若就在汇总页，先不计数★：那一发是开跑前抽的，不该算进 N。
                _SESSION["summary_seen"] = False
                _SESSION["armed"] = True
            elif not _SESSION["summary_seen"]:
                _SESSION["summary_seen"] = True
                if _SESSION["armed"]:
                    _SESSION["done"] += 1
                    _SESSION["last_progress_ts"] = now
                    just_counted = True
            done = int(_SESSION["done"])

        # 用户可见：开工时报一次目标；每抽完一发给一行进度（不刷屏：只在真计入时打）。
        if not said:
            _start_progress(times)
            _say(f"{DISPLAY}：要抽 {times} 发十连（当前池子）")
        if just_counted:
            _step_progress(done)
            _say(f"{DISPLAY}：第 {done}/{times} 发 完成")

        detail = {"done": done, "times": times, "summary": summary, "continue": can_continue}
        # ★收工一律**就地停**（StopTask），绝不做任何导航★ ——
        #   「前往扭蛋首页」回到的是扭蛋首页的默认池（真机：从装备池起步、收尾落在深渊限定），
        #   那就等于替用户换池。停在汇总页不会动池子选择。
        reason = None
        if done >= times:
            reason = f"已抽满 {times} 发"
        elif summary and not can_continue:
            # 该池的汇总页没有「继续 10连抽取」→ 无法在**原池**连抽下一发。
            # 宁可收工报原因，也不点「前往扭蛋首页」把池子换掉。
            reason = "该池汇总页没有『继续』，无法在原池连抽下一发"
        if reason:
            _log(f"[gacha] {reason} → 就地收工（不做导航，避免换池）")
            _say(f"{DISPLAY}：收工 —— {reason}")
            _done_progress(reason)
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={**detail, "reason": reason}
            )
        return CustomRecognition.AnalyzeResult(box=None, detail=detail)


# ---------------------------------------------------------------------------
# 揭示页兜底：★4 以上角色的揭示页**没有「跳过」按钮**（真机 2026-10-20 哈奥 ★4）
#
# 游戏会停在那页等一次点击。OCR 门的两个跳过节点都命中不了 → 卡住。
# 这里的闸门：**只要不在池子页、也不在汇总页**（＝在揭示/转场里），就命中，
# 由 pipeline 点那个记死的位置（与「全部跳过」同一颗按钮的落点）。
# ★这样「一直点那里」只在揭示/转场里发生，池子页和汇总页一个都不点★。
# ---------------------------------------------------------------------------
class GachaSkipGateRecognition(CustomRecognition):
    """揭示/转场帧闸门：池子页与汇总页都不命中，其余一律命中。"""

    def analyze(self, context, argv):
        param = _read_param(argv)
        items = _ocr_all(context, argv.image, param.get("ocr_entry") or "OcrTask")
        pool = is_pool_page(items)
        summary = is_summary_page(items)
        detail = {"pool": pool, "summary": summary}
        if pool or summary:
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=dict(detail, skip=True))


# ---------------------------------------------------------------------------
# 出口二：无进展（分钟级）
# ---------------------------------------------------------------------------
class GachaStallRecognition(CustomRecognition):
    """连续 ``no_progress_sec`` 秒没有新增一发 → 收工（ADR 0005：每个场景都要有界出口）。

    **不跑 OCR**：只读时钟。少一次全屏 OCR，循环更快，也不影响判据正确性
    （「多久没进展」本来就不需要看画面）。
    """

    def analyze(self, context, argv):
        param = _read_param(argv)
        try:
            limit = float(param.get("no_progress_sec") or NO_PROGRESS_SEC)
        except (TypeError, ValueError):
            limit = NO_PROGRESS_SEC

        _sync_task(getattr(argv.task_detail, "task_id", None))
        now = time.monotonic()
        with _LOCK:
            if _SESSION["last_progress_ts"] <= 0:
                _SESSION["last_progress_ts"] = now
            last = float(_SESSION["last_progress_ts"])
            done = int(_SESSION["done"])
            times = int(_SESSION["times"])

        if done >= times:
            # 已抽满：交给 GachaCount 收口，本节点不抢。
            return CustomRecognition.AnalyzeResult(box=None, detail={"stall": False})

        idle = now - last
        if idle < limit:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"stall": False, "idle": round(idle, 1)}
            )

        reason = f"连续 {limit:.0f} 秒没有抽成任何一发（无进展）"
        _log(f"[gacha] 无进展 {idle:.0f}s ≥ {limit:.0f}s → 收工")
        _say(f"{DISPLAY}：收工 —— {reason}")
        _done_progress(reason)
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 0, 0], detail={"stall": True, "idle": round(idle, 1), "reason": reason}
        )


# ---------------------------------------------------------------------------
# ★不做任何导航★：抽满/无法连抽都**就地** StopTask
#
# 「前往扭蛋首页」回到的是**扭蛋首页的默认池**（真机：从装备池起步、收尾落在深渊限定），
# 那等于替用户换池。停在汇总页不会改动池子选择。
# ---------------------------------------------------------------------------


__all__ = [
    "DISPLAY",
    "DEFAULT_TIMES",
    "NO_PROGRESS_SEC",
    "GachaCountRecognition",
    "GachaSkipGateRecognition",
    "GachaStallRecognition",
    "is_pool_page",
    "is_summary_page",
]
