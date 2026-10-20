# -*- coding: utf-8 -*-
"""#19 / ADR 0005：深渊「迷路」闸门改成**连续秒数**（``LostClock``）—— 离线，零设备。

    .venv\\Scripts\\python.exe tools\\test_abyss_giveup_lost.py

判据全部在进程内：真实 ``abyss_impl.AbyssGiveUpRecognition.analyze`` + 被替换掉的 OCR
（不抓屏、不连设备、不写仓里的 ``progress.json``）。

覆盖（照票面四问 + 数据真源）：

1. 战斗中（``in_fight=True``）连续 300s unknown **不**触发 —— #76 的结论并入原语：
   战斗 episode 内的 unknown 不记起点，所以「一场 5 分钟的战斗」不再把自己算成迷路；
2. 离开战斗后连续 61s unknown **触发**（★#21 起：第一次迷路先归位，本文件把预算置满，
   验证的是「归位 2 次失败后」的收工出口），原因前半句 = ``core.lost_reason``
   （三个场景同一句，文案里的秒数**向下取整**），括号里换成「归位 2 次失败」；
3. override 里残留的旧**帧数**参数被**忽略**且只警告一次（ADR 0005 的兼容口径）：
   旧量纲不许静默恢复，也不许把日志刷爆；
4. 回归：零进度 300s / 无新关卡 900s 两条闸门**未被本次改动碰过**（#118 的判据还在）；
5. 阈值真源：``scene.abyss.LOST_SEC``（EX / plain 都继承）+ 安装态快照 + kernel 缺省值
   三处同值，且 ``abyss.json`` 里不再复制一份（ADR 0005：阈值只有一个真源）。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import abyss_impl as impl  # noqa: E402
import battle_loop_core as core  # noqa: E402
import jsonc  # noqa: E402
from scene import abyss as scene_abyss  # noqa: E402

FAILS: list[str] = []

#: 与 argv 里的 task_id 一致：``_sync_task`` 见到同一个 id 就不会复位会话
#: （复位会清掉本文件精心预置的「已连续迷路 N 秒」）。
_TASK_ID = 19_000_001

#: 一帧**已知页**（深渊 hub）：``深渊连战`` + 一个 hub 标记词 ``兑换道具``。
#: 用它证明「画面认得出 ⇒ 迷路时钟清点」而不是「计时照跑」。
_HUB_FRAME = (
    ("深渊连战", [100, 100, 80, 30]),
    ("兑换道具", [200, 600, 60, 24]),
)


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 离线驱动：argv 桩 + 临时账本 + 会话复位（同一套 harness 供四个用例共用）
# ---------------------------------------------------------------------------
class _RecoArgv:
    """``abyss_giveup`` 只读 ``image`` / ``task_detail.task_id`` / 自定义参数。"""

    class _TaskDetail:
        task_id = _TASK_ID

    def __init__(self, param, image=("frame",), task_id: int = _TASK_ID):
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        detail = self._TaskDetail()
        detail.task_id = int(task_id)
        self.task_detail = detail
        self.image = image


@contextlib.contextmanager
def _sandbox():
    """临时账本：真正触发收工时会写「本轮已收工」标记 —— 绝不写仓里的 ``progress.json``。"""
    saved = impl.ledger._DEFAULT
    with tempfile.TemporaryDirectory() as td:
        impl.ledger.set_file(Path(td) / "progress.json")
        try:
            yield
        finally:
            impl.ledger._DEFAULT = saved


def _reset_session() -> None:
    """一场干净的任务会话（task_id 与 argv 相同，``_sync_task`` 不会二次复位）。"""
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION.update(
            {
                "task_id": _TASK_ID,
                "cur_stage": None,
                "in_fight": False,
                "start_ts": now,
                "last_progress_ts": now,
                "last_state": None,
                "last_observe_ts": 0.0,
                "total_marks": 0,
                "max_done": 0,
                "session_max_done": 0,
                "joined_stage": None,
                "ladder_cleared": False,
                "giveup_reason": None,
                "tab_selected": None,
                "tab_sigs": {},
                "tab_empty": {},
                "tab_fail_streak": 0,
                "tab_switches": 0,
                "lap": 1,
                "progress": None,
                "progress_done_reason": None,
                # ★#21★ 归位预算（本文件不测归位；缺省 = 0 次已用、无待执行归位）。
                "recoveries": 0,
                "recover_pending": False,
            }
        )
        # ★ADR 0005 / #19★ 迷路时钟整只归零（与 ``_sync_task`` 的新任务复位同一份）。
        impl._SESSION["lost"].reset()


def _giveup(param: dict | None = None, items=None, capture: io.StringIO | None = None):
    """跑一次**真实** ``AbyssGiveUpRecognition.analyze``（OCR 被替换，零设备）。"""
    saved_ocr = impl._ocr
    impl._ocr = lambda context, image, entry="OcrTask": list(items or [])
    try:
        if capture is None:
            return impl.AbyssGiveUpRecognition().analyze(None, _RecoArgv(param or {}))
        with contextlib.redirect_stdout(capture):
            return impl.AbyssGiveUpRecognition().analyze(None, _RecoArgv(param or {}))
    finally:
        impl._ocr = saved_ocr


def _detail(result) -> dict:
    return getattr(result, "detail", None) or {}


# ---------------------------------------------------------------------------
# 1. 战斗中 300s unknown 不触发（#76：不记起点）
# ---------------------------------------------------------------------------
def test_in_fight_not_giveup() -> None:
    print("\n== 1. 战斗中（in_fight=True）连续 300s unknown 不触发（#76）==")
    _reset_session()
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION["in_fight"] = True
        lost = impl._SESSION["lost"]
    # 战斗 episode 内的 unknown：每 10s 喂一帧，全程 in_fight=True。
    for t in range(0, 301, 10):
        lost.observe("unknown", now - 300.0 + t, in_fight=True)
    check(
        "战斗中 300s unknown：seconds_lost 恒为 0（不记起点）",
        lost.seconds_lost(now) == 0.0,
        str(lost.seconds_lost(now)),
    )
    check("战斗中 unknown 不写 last_known", lost.last_known is None, str(lost.last_known))
    check("战斗中 unknown 不写 worst_seconds", lost.worst_seconds == 0.0, str(lost.worst_seconds))

    with _sandbox():
        got = _giveup({})
    detail = _detail(got)
    check(
        "战斗中 300s unknown：不因迷路收工",
        getattr(got, "box", None) is None and not detail.get("giveup"),
        str(detail),
    )


# ---------------------------------------------------------------------------
# 2. 离开战斗后连续 61s ⇒ 收工（原因 = core.lost_reason）
# ---------------------------------------------------------------------------
def test_after_fight_61s_giveup() -> None:
    print("\n== 2. 离开战斗后连续 61s unknown 触发，原因 = core.lost_reason ==")
    _reset_session()
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION["in_fight"] = False
        # ★#21★ 本用例验证的是「预算用尽后的收工出口」：第一次迷路会先归位重导航
        #   （见 tools/test_abyss_recover.py），故这里把预算置满，直接走收工分支。
        impl._SESSION["recoveries"] = impl.MAX_RECOVERIES
        # last_state / last_observe_ts 对齐：giveup 内部这帧 observe 不重新打点，只读钟。
        impl._SESSION["last_state"] = "unknown"
        impl._SESSION["last_observe_ts"] = now
        lost = impl._SESSION["lost"]
        lost.observe("abyss_hub", now - 75.0)   # 最后已知页 = hub（离开战斗后确实站过）
        lost.observe("unknown", now - 61.4)     # 已连续 61.4s 认不出画面
    check(
        "预置：连续 61.4s unknown",
        61.0 <= lost.seconds_lost(now) < 62.0,
        str(lost.seconds_lost(now)),
    )

    buf = io.StringIO()
    with _sandbox():
        got = _giveup({}, capture=buf)
    detail = _detail(got)
    # ★#21★ 归位预算用尽 → 原因在 core.lost_reason 的同一句上换成「归位 N 次失败」。
    want = "连续 61s 认不出画面（归位 2 次失败）"
    check("秒数向下取整 + 归位预算用尽（归位 2 次失败）", detail.get("reason") == want, repr(detail.get("reason")))
    check(
        "原因前半句就是 kernel 的 lost_reason（三场景同一句，不各写一份）",
        want == impl._lost_after_recover_reason(61.4, "abyss_hub", impl.MAX_RECOVERIES)
        and want.split("（", 1)[0] == core.lost_reason(61.4, "abyss_hub").split("（", 1)[0],
        impl._lost_after_recover_reason(61.4, "abyss_hub", impl.MAX_RECOVERIES),
    )
    check(
        "abyss_giveup 命中（box=[0,0,0,0] 且 detail.giveup=True）",
        getattr(got, "box", None) == [0, 0, 0, 0] and bool(detail.get("giveup")),
        str(detail),
    )
    check(
        "用户可见行 =『[abyss] 收工 —— 连续 61s 认不出画面（归位 2 次失败）』",
        "[abyss] 收工 —— 连续 61s 认不出画面（归位 2 次失败）" in buf.getvalue(),
        [ln for ln in buf.getvalue().splitlines() if "收工 ——" in ln][:2],
    )


# ---------------------------------------------------------------------------
# 3. 旧帧数参数：忽略 + 只警告一次（ADR 0005 兼容口径）
# ---------------------------------------------------------------------------
def test_stale_frame_param_ignored() -> None:
    print("\n== 3. override 残留的旧帧数参数：忽略 + 只警告一次（ADR 0005）==")
    _reset_session()
    scene_name = impl._cfg().scene
    # 每进程每场景只警告一次：先清掉本进程可能已有的记录，才能证明「第一次会警告」。
    core._STALE_PARAM_WARNED.discard((core._STALE_FRAME_LIMIT_PARAM, scene_name))
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION["last_state"] = "abyss_hub"
        impl._SESSION["last_observe_ts"] = now
        lost = impl._SESSION["lost"]
        lost.observe("abyss_hub", now - 5.0)
        lost.observe("unknown", now - 3.0)      # 只迷路 3s，远低于 lost_sec=600

    buf = io.StringIO()
    with _sandbox():
        # ``unknown_limit=1``：旧判据下 2 帧就该收工；新实现必须**当没看见**。
        first = _giveup({"lost_sec": 600, "unknown_limit": 1}, capture=buf)
        second = _giveup({"lost_sec": 600, "unknown_limit": 1}, capture=buf)

    warn = "[abyss] 忽略过时参数 unknown_limit=1（已换成 lost_sec，见 ADR 0005）"
    lines = buf.getvalue().splitlines()
    check(
        "旧帧数参数只警告一次（每进程每场景一行证据）",
        lines.count(warn) == 1,
        [ln for ln in lines if "忽略过时参数" in ln],
    )
    check(
        "旧参数被忽略：unknown_limit=1 也不再按帧数收工",
        not _detail(first).get("giveup") and not _detail(second).get("giveup"),
        f"first={_detail(first)} second={_detail(second)}",
    )
    check("会话里不再有帧数计数器", "unknown_count" not in impl._SESSION, str(sorted(impl._SESSION)))
    check(
        "这次没收工的原因与迷路无关（3s < lost_sec=600）",
        lost.seconds_lost(now) < 600.0,
        str(lost.seconds_lost(now)),
    )


# ---------------------------------------------------------------------------
# 4. 回归：零进度 300s / 无新关卡 900s 两条闸门未被改动
# ---------------------------------------------------------------------------
def test_other_gates_unchanged() -> None:
    print("\n== 4. 回归：零进度 300s / 无新关卡 900s 两条闸门未被改动（#118）==")

    # 4a 零进度（一场都没完成）：画面一直是已知页 ⇒ 迷路时钟不参与，只看 no-progress。
    _reset_session()
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION["last_progress_ts"] = now - 300.5
        impl._SESSION["last_state"] = "abyss_hub"
        impl._SESSION["last_observe_ts"] = now
    with _sandbox():
        got = _giveup({}, items=_HUB_FRAME)
    detail = _detail(got)
    check(
        "零进度 300s ⇒「300s 一场都没有完成（关卡打不过？）」",
        detail.get("reason") == "300s 一场都没有完成（关卡打不过？）",
        repr(detail.get("reason")),
    )
    check("零进度判据不是迷路（lost_seconds=0）", impl._SESSION["lost"].seconds_lost(time.monotonic()) < 1.0)

    # 4b 无新关卡：本次会话已打过 ≥1 战 ⇒ 用 900s 窗口（仍比零进度的 300s 宽）。
    _reset_session()
    now = time.monotonic()
    with impl._LOCK:
        impl._SESSION["session_max_done"] = 5
        impl._SESSION["last_progress_ts"] = now - 900.5
        impl._SESSION["last_state"] = "abyss_hub"
        impl._SESSION["last_observe_ts"] = now
    with _sandbox():
        got = _giveup({}, items=_HUB_FRAME)
    detail = _detail(got)
    check(
        "无新关卡 900s ⇒「900s 无新关卡完成」",
        detail.get("reason") == "900s 无新关卡完成",
        repr(detail.get("reason")),
    )


# ---------------------------------------------------------------------------
# 5. 阈值真源：scene.abyss.LOST_SEC（EX/plain 继承）+ 快照 + kernel 同值；JSON 不复制
# ---------------------------------------------------------------------------
def test_threshold_source_of_truth() -> None:
    print("\n== 5. 阈值真源：scene.abyss.LOST_SEC + 安装态快照 + kernel 同值 ==")
    check("scene.abyss.LOST_SEC = 60s（ADR 0005 的 3.75× 余量）",
          scene_abyss.LOST_SEC == 60, str(scene_abyss.LOST_SEC))
    check("深渊EX 继承 lost_sec",
          scene_abyss.ABYSS_EX.lost_sec == float(scene_abyss.LOST_SEC),
          str(scene_abyss.ABYSS_EX.lost_sec))
    check("普通深渊继承 lost_sec（两个登记场景都不用各写一遍）",
          scene_abyss.ABYSS_PLAIN.lost_sec == float(scene_abyss.LOST_SEC),
          str(scene_abyss.ABYSS_PLAIN.lost_sec))
    check("安装态冻结快照与真源同值（装到没有 scene/ 的目录也不漂）",
          impl._LOST_SEC_SNAPSHOT == scene_abyss.LOST_SEC, str(impl._LOST_SEC_SNAPSHOT))
    check("kernel 缺省阈值同值（三个场景同一个数量级）",
          core.DEFAULT_LOST_SEC == float(scene_abyss.LOST_SEC), str(core.DEFAULT_LOST_SEC))

    pipes = jsonc.load(open(ROOT / "assets" / "resource" / "pipeline" / "abyss.json", encoding="utf-8"))
    param = (
        ((pipes["AbyssGiveUp"]["recognition"] or {}).get("param") or {})
        .get("custom_recognition_param")
        or {}
    )
    check("abyss.json 不再复制迷路阈值（真源只在 scene/abyss.py）",
          "lost_sec" not in param, str(sorted(param)))
    check("abyss.json 不再带旧帧数参数（ADR 0005：全仓删除）",
          "unknown_limit" not in param, str(sorted(param)))
    check("AbyssGiveUp 仍是唯一收工出口（StopTask）",
          (pipes["AbyssGiveUp"].get("action") or {}).get("type") == "StopTask")


def main() -> int:
    print("=" * 78)
    print("#19 / ADR 0005：深渊「迷路」= 连续秒数（不是累计帧数）—— 离线零设备")
    print("=" * 78)
    test_in_fight_not_giveup()
    test_after_fight_61s_giveup()
    test_stale_frame_param_ignored()
    test_other_gates_unchanged()
    test_threshold_source_of_truth()
    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_abyss_giveup_lost: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
