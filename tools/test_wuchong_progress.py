# -*- coding: utf-8 -*-
"""#143（map #7 / 票 #8）五重决战的进度行 —— 纯离线一键守卫。

    .venv\\Scripts\\python.exe tools\\test_wuchong_progress.py

不需要游戏 / 设备：喂**假 OCR 帧** + 假 ``custom_recognition_param``，断言打进面板的那一行逐字
（唯一口径：``docs/spec/progress-visibility.md`` §B 出口 API / §C 五重那一行）。

覆盖：
  ① start：任务开始、读到「打几次」→ ``[进度] 五重决战 开始（共 N 次）``（同一任务只一条）；
  ② step ：**进入一场战斗**（#76 计数点，规格 B2）→ ``[进度] 五重决战 i/N 次（打几次=N）``；
     结算页**不出**步进（计数点不许搬到结算）；
  ③ done ：收工兜底出口（``WuchongGiveUp``）→ ``[进度] 五重决战 收工：<既有 reason 原文>``；
     旧的「五重决战：收工 —— 原因」照旧（#86 / hooks_86 / hooks_87 的契约）；
  ④ 格式：模块源码里没有第二份 ``[进度]`` 拼接（唯一真源 = ``reporting.format_progress``）；
  ⑤ 委托：``_say`` / ``_log`` 真的走 ``reporting.say`` / ``reporting.log``，且 #86 的
     ``debug/wuchong_agent.log`` 落盘 + ``QUIET``（机制日志不进 stdout）语义不变。

★真机行为不在本测试范围★（面板双签见 ``docs/spec/progress-visibility.md`` §D）。
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"
for _p in (str(ROOT), str(AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import reporting  # noqa: E402
import wuchong_impl as impl  # noqa: E402

FAILS: list[str] = []

#: 模式页（带门票读数）—— 与 hooks_86 的 ``_MODE_TICKETS`` 同一份假帧。
MODE_ITEMS = [
    ("今天剩余次数x 3", [381, 922, 319, 42]),
    ("单人游戏", [100, 700, 150, 40]),
]
#: 真机合并框战斗 HUD（#74 证据帧：``时间 29:30 分数 38629797530``）→ classify = wuchong_battle。
BATTLE_ITEMS = [("时间 29:30 分数 38629797530", [34, 1221, 402, 40])]

TID = 570_900_001


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


class _Argv:
    """``CustomRecognition.analyze`` 的最小 argv 假件（字段与 hooks_86 的 ``_RecArgv`` 同形）。"""

    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


@contextlib.contextmanager
def _panel():
    """把「面板」换成可读缓冲（生产里它就是进程真实 stdout，见 reporting.say）。"""
    old = reporting._REAL_STDOUT
    buf = io.StringIO()
    reporting._REAL_STDOUT = buf
    try:
        yield buf
    finally:
        reporting._REAL_STDOUT = old


def _reset():
    """把会话 / 账本 / 进度线钉到「新任务还没跑」的已知起点（同 hooks_86 的做法）。"""
    td = Path(tempfile.mkdtemp(prefix="wf_wuchong_progress_"))
    impl.ledger.set_file(td / "progress.json")
    impl.ledger.reset(impl.LEDGER_SCOPE)
    impl._LOG_PATH = td / "wuchong_agent.log"
    impl._PROGRESS = None
    with impl._LOCK:
        # task_id=None → 下一次 analyze 的 _sync_task 真的做一次换任务复位。
        impl._SESSION["task_id"] = None
        # _sync_task 不复位这几项（它们由 giveup 每次现读），测试里显式钉住。
        impl._SESSION["said_target"] = False
        impl._SESSION["settle_said"] = False
        impl._SESSION["remaining_plays"] = None
        impl._SESSION["unknown_streak"] = 0
        impl._SESSION["room_beat_ts"] = 0.0
        impl._SESSION["last_state"] = None
        impl._SESSION["last_observe_ts"] = 0.0
        impl._SESSION["fights_done"] = 0
        impl._SESSION["target_fights"] = 0
        impl._SESSION["in_fight"] = False
        impl._SESSION["battle_had_continue"] = False
        impl._SESSION["start_ts"] = time.monotonic()
        impl._SESSION["last_progress_ts"] = time.monotonic()
    return td


def _drive(items, target, tid=TID):
    """跑一次真实的 ``WuchongGiveUpRecognition.analyze``；返回 (结果, 被重定向的 stdout)。"""
    impl._ocr = lambda context, image, entry="OcrTask": list(items)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        res = impl.WuchongGiveUpRecognition().analyze(
            None,
            _Argv(tid, {"ocr_entry": "OcrTask", "room_wait_sec": 300,
                        "no_progress_sec": 900, "target_fights": target}),
        )
    return res, out.getvalue()


def _observe(state) -> None:
    """直接喂一个分类结果（hooks_74 同款单元缝）；仅静音旧用户行，进度行走面板。"""
    with contextlib.redirect_stdout(io.StringIO()):
        impl._observe(state, {}, [])


def _handmade_progress_literals(source: str) -> list[str]:
    """源码里**非 docstring** 的 ``[进度]`` 字符串字面量（= 场景自己拼格式）。"""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "[进度]" in node.value
        and id(node) not in docstrings
    ]


def test_start_line() -> None:
    print("\n== 1. start：任务开始、读到「打几次」= 一条 `[进度] … 开始（共 N 次）` ==")
    with _panel() as panel:
        _reset()
        res, out = _drive(MODE_ITEMS, 3)
        p = impl._progress()
        check("读到「打几次」没有误收工", res.box is None, repr(res.detail))
        check("start 行逐字", p.lines == ["[进度] 五重决战 开始（共 3 次）"], repr(p.lines))
        check("start 行进了面板", "[进度] 五重决战 开始（共 3 次）" in panel.getvalue())
        check("旧「要打 3 次」照旧（#86）", "五重决战：要打 3 次" in out, repr(out))
        _drive(MODE_ITEMS, 3)          # 同一任务再 tick 一次
        check("start 同一任务只出一条", len(p.lines) == 1, repr(p.lines))
        # ★换任务 = 换一条进度线★：不能依赖 #86 的 said_target 闩锁（它跨任务不复位）。
        _drive(MODE_ITEMS, 3, tid=TID + 1)
        p2 = impl._progress()
        check(
            "换任务后重新 start（本次任务口径）",
            p2 is not p and p2.lines == ["[进度] 五重决战 开始（共 3 次）"],
            repr(p2.lines),
        )


def test_step_line() -> None:
    print("\n== 2. step：进入一场战斗 = 一步（#76 计数点；结算页不步进） ==")
    with _panel() as panel:
        _reset()
        _drive(MODE_ITEMS, 2)
        _drive(BATTLE_ITEMS, 2)
        p = impl._progress()
        check(
            "step 行逐字（进场那一步）",
            p.lines[-1] == "[进度] 五重决战 1/2 次（打几次=2）",
            repr(p.lines),
        )
        check(
            "step 行 = reporting.format_progress（唯一格式）",
            p.lines[-1] == reporting.format_progress("五重决战", 1, 2, "次", "打几次=2"),
            p.lines[-1],
        )
        with impl._LOCK:
            fights = int(impl._SESSION["fights_done"])
        check("计数口径不变：fights_done=1", fights == 1, str(fights))
        check(
            "账本 key 不变：wuchong/fight/1",
            impl.ledger.scope(impl.FIGHT_LEDGER_PREFIX) == ["wuchong/fight/1"],
            repr(impl.ledger.scope(impl.FIGHT_LEDGER_PREFIX)),
        )
        # ★计数点必须是「进场」不是「结算」★：结算帧不许再出一步。
        _observe(impl.WUCHONG_SETTLE)
        check("结算页不出步进（计数点仍是进场）", len(p.lines) == 2, repr(p.lines))
        # 真正离开本场后再进一场 → 第二场照常一步。
        _observe(impl.WUCHONG_TEAM)
        _drive(BATTLE_ITEMS, 2)
        check(
            "第二场 step 递增",
            p.lines[-1] == "[进度] 五重决战 2/2 次（打几次=2）",
            repr(p.lines),
        )
        check("面板收齐两条 step", panel.getvalue().count("次（打几次=2）") == 2, panel.getvalue()[:160])


def test_done_line() -> None:
    print("\n== 3. done：收工兜底出口把既有 reason 原文带出来 ==")
    with _panel() as panel:
        _reset()
        _drive(MODE_ITEMS, 1)
        _drive(BATTLE_ITEMS, 1)
        _observe(impl.WUCHONG_TEAM)      # 本场收场（收工时机 = 本场之后，#76）
        res, out = _drive(MODE_ITEMS, 1)
        reason = str((res.detail or {}).get("reason") or "")
        check("命中既有收工出口", res.box == [0, 0, 0, 0], repr(res.detail))
        check("reason 是既有文案（未新造）", reason == "已打够 1 次（打几次=1）", repr(reason))
        p = impl._progress()
        check(
            "done 行逐字：`[进度] 五重决战 收工：<reason>`",
            p.lines[-1] == f"[进度] 五重决战 收工：{reason}",
            repr(p.lines),
        )
        check("done 用的是同一条进度线", p.done_reason == reason, repr(p.done_reason))
        check(
            "旧「五重决战：收工 —— 原因」照旧（#86 / hooks_87）",
            f"五重决战：收工 —— {reason}" in out,
            repr(out),
        )
        check("收工行进了面板", f"[进度] 五重决战 收工：{reason}" in panel.getvalue())
        before = len(p.lines)
        _drive(MODE_ITEMS, 1)
        check("done 之后不再出进度", len(p.lines) == before, repr(p.lines))


def test_single_format() -> None:
    print("\n== 4. 格式唯一：模块里没有第二份 `[进度]` 拼接 ==")
    source = Path(impl.__file__).read_text(encoding="utf-8")
    bad = _handmade_progress_literals(source)
    check("非 docstring 的 `[进度]` 字面量 = 0", bad == [], repr(bad[:3]))
    check(
        "step 行由 reporting.format_progress 决定",
        reporting.format_progress("五重决战", 2, 3, "次", "打几次=3")
        == "[进度] 五重决战 2/3 次（打几次=3）",
    )


def test_delegation_and_quiet() -> None:
    print("\n== 5. 委托 reporting + #86 的 wuchong_agent.log / QUIET 语义 ==")
    td = _reset()
    log = td / "wuchong_agent.log"
    seen = {"say": [], "log": []}
    real_say, real_log = reporting.say, reporting.log
    try:
        reporting.say = lambda text="": seen["say"].append(text)
        reporting.log = lambda text="": seen["log"].append(str(text))
        impl._say("委托行")
        impl._log("[wuchong] 机制行")
    finally:
        reporting.say, reporting.log = real_say, real_log
    check("_say 真的调用 reporting.say", "委托行" in seen["say"], repr(seen["say"]))
    check("_log 真的调用 reporting.log", "[wuchong] 机制行" in seen["log"], repr(seen["log"]))
    body = log.read_text(encoding="utf-8")
    check("#86 落盘：`[say]` 前缀", "[say] 委托行" in body, body[:160])
    check("#86 落盘：机制行", "[wuchong] 机制行" in body, body[:160])
    with contextlib.redirect_stdout(io.StringIO()) as out:
        impl._log("[wuchong] 非静音机制行")
    check("非静音：机制日志进 stdout（离线取证）", "[wuchong] 非静音机制行" in out.getvalue())

    real_quiet = impl.QUIET
    try:
        impl.set_quiet(True)
        with _panel() as panel, contextlib.redirect_stdout(io.StringIO()) as out:
            impl._log("[wuchong] 静音机制行")
            impl._say("静音用户行")
        check("QUIET：机制日志不进 stdout", "[wuchong] 静音机制行" not in out.getvalue(), repr(out.getvalue()))
        check(
            "QUIET：机制日志仍逐行落盘",
            "[wuchong] 静音机制行" in log.read_text(encoding="utf-8"),
        )
        check("QUIET：面板吞不掉（#86）", "静音用户行" in panel.getvalue(), panel.getvalue()[:120])
        # ★#114 的真实取证通道★：``QUIET`` 只管**机制日志**；用户可见行在有人把
        #   ``sys.stdout`` 重定向走时仍要镜像一份 —— 否则 ``hooks_114`` 抓不到
        #   「客户端重启 N 次仍连不上服务器」那句收工原因（它整段 `_drive` 都置 `QUIET=True`）。
        check(
            "QUIET：用户行仍可被取证（镜像到当前 stdout）",
            "静音用户行" in out.getvalue(),
            repr(out.getvalue()),
        )
        # ★生产 GUI★：``reporting`` 真的静音时**不镜像**（否则会往日志文件多写一份）。
        quiet_log = Path(tempfile.mkdtemp()) / "agent.log"
        reporting.set_quiet(True, quiet_log)
        try:
            with _panel() as panel_q, contextlib.redirect_stdout(io.StringIO()) as out_q:
                impl._say("生产面板行")
        finally:
            reporting.set_quiet(False)
        check(
            "reporting 静音（GUI）：面板有、stdout 不镜像",
            "生产面板行" in panel_q.getvalue() and "生产面板行" not in out_q.getvalue(),
            f"panel={panel_q.getvalue()[:60]!r} out={out_q.getvalue()[:60]!r}",
        )
    finally:
        impl.set_quiet(real_quiet)


def main() -> int:
    test_start_line()
    test_step_line()
    test_done_line()
    test_single_format()
    test_delegation_and_quiet()
    print("")
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    real_ocr = impl._ocr
    try:
        raise SystemExit(main())
    finally:
        impl._ocr = real_ocr
