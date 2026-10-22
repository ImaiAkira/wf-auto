# -*- coding: utf-8 -*-
"""离线单测：#10 领主战 / 外传的用户可见进度行（`agent/reporting.py::Progress`）。

不需要游戏、不需要设备（帧与假 context 借 ``hooks_100`` / ``hooks_122`` / ``hooks_51`` 的真机读数）。
直接跑::

    .venv\\Scripts\\python.exe tools\\test_lords_side_progress.py

覆盖这张票的验收（规格 ``docs/spec/progress-visibility.md`` §B/§C）：

  1. **领主战 · 开始 + note**：一轮规划落地 ⇒ ``[进度] 领主战 开始`` 一条（幂等），
     note = ``第 j 轮·计划 N 个``（j 由既有 ``round_index`` 换算、N = 本轮目标数），
     ``total=0`` / ``unit=个目标``（**不编分母**）；
  2. **领主战 · 步进复用既有计数**：一个目标（成员 × 档位）打完（见到战斗/结算）⇒
     ``已 N 个目标``，N **就是** ``Session.sessions_played``（点【挑战】时 +1 的那个既有计数），
     重复证据 / 倒退数字都不再出线（``Progress.step`` 单调去重）；
  3. **领主战 · 收工接既有出口**：``全部解禁``（mode=read）与「模式页阶梯用尽」（mode=tab）两条
     收工路径都出 ``[进度] 领主战 收工：<既有 reason>``，reason 与 ``[lords] 收工：`` 原文
     **逐字相同**，且 ``LordsStop`` override 仍在（收工语义没被改动）；收工后 step 静默；
  4. **领主战 · 17 个收工出口全接上**：源码逐行核对 —— 每条 ``print(f"[lords] 收工：…")``
     的后面都紧跟 ``finish_progress(session, …)``（漏一个 = 那一条收工在面板上无收工行）；
  5. **外传 · 步进 = 账本新增一笔**：``mark_done`` 真的新增时出 ``[进度] 外传 已 X 关（副本名）``；
     同一关重复记（``已存在``）不重复出线；第二关 ⇒ ``已 2 关``；
  6. **外传 · 收工接既有出口**：``SidePageDoneStop``（``page_done_repeat`` 命中 → StopTask）出
     ``[进度] 外传 收工：<既有文案>``，与 ``[page_done_repeat]`` 打印的那一句逐字相同；
  7. **格式唯一**：两处场景文件里**没有**自拼的 ``[进度]`` 字面量，进度行不带假分母 ``i/N``；
  8. **无漂移**：``scene.drift.check_all()`` 为空。

挂点 / prove-red 在 ``tools/contract_hooks/hooks_146.py``。
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

# #14-offline-utf8: 强制本文件自己的 stdout 为 UTF-8（不依赖外部 PYTHONIOENCODING）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import reporting  # noqa: E402
import lords_impl as impl  # noqa: E402
import side_impl as side  # noqa: E402
import hooks_100 as fakes  # noqa: E402
import hooks_122 as h122  # noqa: E402
import hooks_146 as h146  # noqa: E402
import hooks_51 as h51  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


@contextlib.contextmanager
def panel():
    """把「面板」换成可读缓冲（生产里它就是进程真实 stdout；quiet 吞不掉它）。"""
    saved_quiet = reporting.is_quiet()
    if saved_quiet:
        reporting.set_quiet(False)
    old = reporting._REAL_STDOUT
    buf = io.StringIO()
    reporting._REAL_STDOUT = buf
    try:
        yield buf
    finally:
        reporting._REAL_STDOUT = old
        if saved_quiet:
            reporting.set_quiet(False)


def _panel_lines(buf) -> list[str]:
    return [line for line in buf.getvalue().splitlines() if line.startswith("[进度]")]


#: 外传「本页全清」帧：拿真机关卡列表帧（``event_stage_list.png``）去掉 NEW 行与剧情行
#: ⇒ 剩下的两行都带 ``COMPLETE!!``、没有 NEW（= ``side_list_all_done`` 的真实判据）。
ALL_COMPLETE_FRAME: tuple = tuple(
    item
    for item in h51.STAGE_LIST_ITEMS
    if not item[0].startswith("NEW") and item[0] not in ("遥远过去的国家", "STORY")
)


# ---------------------------------------------------------------------------
# 1. 领主战：开始 + note（第 j 轮·计划 N 个）
# ---------------------------------------------------------------------------
def test_lords_start_and_note() -> None:
    print("\n== 1. 领主战：开始一条 + note=第 j 轮·计划 N 个（total=0，不编分母）==")
    impl.reset_sessions()
    task = 146001
    ctx = fakes.FakeContext()
    reco = impl.LordsProgressRecognition()
    with panel() as buf, fakes.FakeClock(1000.0) as clock:
        session = impl._session(task)
        nav = impl._nav_state(session)
        nav.complete_scan(session.round_index, clock.now)
        first = h122._scan_read(impl, fakes, reco, ctx, task, session, h122.SCAN_A_ROWS)
        detail = dict(getattr(first, "detail", None) or {})
        line = impl.progress_line(session)
        planned = len(session.targets)
        print(f"     第 1 轮：targets={[t.pair for t in session.targets]} note={line.note!r}")
        check("一轮规划落地 ⇒ 出一条「领主战 开始」", line.lines[:1] == ["[进度] 领主战 开始"],
              f"lines={line.lines[:2]!r}")
        check("note 写成本轮计划数（第 1 轮·计划 N 个）",
              line.note == f"第 1 轮·计划 {planned} 个", f"note={line.note!r}")
        check("total=0（没有固定上限，不编分母）", line.total == 0, f"total={line.total!r}")
        check("unit=个目标", line.unit == "个目标", f"unit={line.unit!r}")
        check("detail 里的本轮目标数与 note 一致",
              len(detail.get("targets") or ()) == planned,
              f"targets={detail.get('targets')!r}")

        # 第二轮：关一轮（打过 1 场）+ 新一次整轮扫描 ⇒ note 跟着轮次走
        session.attempts_since_read = 1
        session.sessions_played = 1
        second = h122._scan_read(impl, fakes, reco, ctx, task, session, h122.SCAN_B_ROWS)
        detail2 = dict(getattr(second, "detail", None) or {})
        print(f"     第 2 轮：round_index={session.round_index} "
              f"targets={[t.pair for t in session.targets]} note={line.note!r}")
        check("关轮后 round_index 前进到 1（既有计数）", session.round_index == 1,
              f"round_index={session.round_index}")
        check("note 每轮更新：第 2 轮·计划 N 个",
              line.note == f"第 2 轮·计划 {len(session.targets)} 个", f"note={line.note!r}")
        check("开始行仍只有一条（start 幂等）",
              len([one for one in line.lines if one.endswith("开始")]) == 1,
              f"lines={line.lines!r}")
        check("第二轮读数没被判收工（进度行不影响既有判据）", not detail2.get("stop"),
              f"stop={detail2.get('stop')!r} reason={detail2.get('reason')!r}")
    impl.reset_sessions()


# ---------------------------------------------------------------------------
# 2. 领主战：步进复用既有场次计数
# ---------------------------------------------------------------------------
def test_lords_step_reuses_sessions() -> None:
    print("\n== 2. 领主战：一个目标打完 ⇒ 已 N 个目标（N = 既有场次计数）==")
    impl.reset_sessions()
    task = 146002
    with panel() as buf, fakes.FakeClock(2000.0):
        session = impl._session(task)
        impl.note_round_plan(session, 3)          # 本轮计划 3 个（note 由 _read 写）
        line = impl.progress_line(session)
        # 第 1 场：点【挑战】时 sessions_played += 1（既有唯一记数点），见到战斗即算打完
        session.sessions_played = 1
        hit = impl._note_after_fight(session, h122.BATTLE_FRAME)
        check("见到战斗/结算 ⇒ 记「这一场打完」（既有 D6 闩置位）", hit is True, f"hit={hit!r}")
        check("一步 = 已 1 个目标（与 sessions_played 同一个数）",
              line.lines[-1] == "[进度] 领主战 已 1 个目标（第 1 轮·计划 3 个）",
              f"lines={line.lines!r}")
        check("Progress.count 等于 sessions_played（没有第二个计数器）",
              line.count == session.sessions_played, f"count={line.count} sessions={session.sessions_played}")

        # 第 2 场：闩被清（回到列表读了一轮）之后又见到结算
        session.back_to_list_pending = False
        session.sessions_played = 2
        impl._note_after_fight(session, h122.SETTLE_FRAME)
        check("第 2 场 ⇒ 已 2 个目标",
              line.lines[-1] == "[进度] 领主战 已 2 个目标（第 1 轮·计划 3 个）",
              f"lines={line.lines!r}")

        # 同一场的重复证据（闩还在）⇒ 不再出线
        before = list(line.lines)
        impl._note_after_fight(session, h122.BATTLE_FRAME)
        check("同一场重复见到战斗/结算 ⇒ 不重复出线", line.lines == before, f"lines={line.lines!r}")

        # 倒退的数字（stale sessions_played）⇒ 不出线（单调）
        session.back_to_list_pending = False
        session.sessions_played = 1
        impl._note_after_fight(session, h122.BATTLE_FRAME)
        check("倒退的场次数字 ⇒ 不出线（Progress 单调）", line.lines == before, f"lines={line.lines!r}")
        check("面板上只有进度行，且没有假分母 i/N",
              all(re.match(r"^\[进度\] 领主战 ", one) for one in _panel_lines(buf))
              and not any(re.search(r"\d+/\d+", one) for one in _panel_lines(buf)),
              f"panel={_panel_lines(buf)!r}")
    impl.reset_sessions()


# ---------------------------------------------------------------------------
# 3. 领主战：收工行接既有出口（两条不同路径）
# ---------------------------------------------------------------------------
def test_lords_done_at_stop_exits() -> None:
    print("\n== 3. 领主战：收工出口 ⇒ 收工行 reason 与既有「收工：」逐字相同 ==")
    # (a) 全部解禁（mode=read 的 should_stop 出口）
    impl.reset_sessions()
    task = 146003
    ctx = fakes.FakeContext()
    reco = impl.LordsProgressRecognition()
    with panel() as buf, fakes.FakeClock(3000.0) as clock:
        session = impl._session(task)
        nav = impl._nav_state(session)
        nav.complete_scan(session.round_index, clock.now)
        with h122._frame(impl, h122.ALL_DONE_FRAME):
            res = reco.analyze(ctx, fakes.FakeArgv(reco_param={"mode": "read"}, task_id=task))
        detail = dict(getattr(res, "detail", None) or {})
        line = impl.progress_line(session)
        reason = str(detail.get("reason") or "")
        print(f"     read 出口：stop={detail.get('stop')!r} reason={reason!r}")
        check("判了收工（既有 stop 语义不变）", bool(detail.get("stop")) and bool(reason),
              f"detail={detail!r}")
        check("★收工行 reason 与既有 reason 逐字相同★", line.done_reason == reason,
              f"done={line.done_reason!r} reason={reason!r}")
        check("面板收工行 == [进度] 领主战 收工：<既有 reason>",
              f"[进度] 领主战 收工：{reason}" in _panel_lines(buf),
              f"panel={_panel_lines(buf)!r}")
        check("收工仍 override 到 LordsStop（收工出口没被改动）",
              any(impl.STOP_NODE in [str(x) for x in nxt] for _n, nxt in ctx.overrides),
              f"overrides={ctx.overrides!r}")
        check("收工行排在「开始」之后（面板顺序不倒）",
              _panel_lines(buf).index("[进度] 领主战 开始") < _panel_lines(buf).index(
                  f"[进度] 领主战 收工：{reason}"),
              f"panel={_panel_lines(buf)!r}")
        # 收工之后不再报进度（Progress.done 静默）
        before = list(line.lines)
        impl.note_target_done(session)
        check("收工后 step 静默（不再刷面板）", line.lines == before, f"lines={line.lines!r}")

    # (b) 模式页换点阶梯用尽（mode=tab 的收工出口；不同函数/不同分支）
    impl.reset_sessions()
    task = 146004
    ctx = fakes.FakeContext()
    reco = impl.LordsProgressRecognition()
    with panel() as buf, fakes.FakeClock(4000.0):
        session = impl._session(task)
        session.mode_fail_reason = "模式页换点阶梯用尽：state=lords_unknown 锚=None（离线注入）"
        with h122._frame(impl, fakes.LIST_FRAME):
            res = reco.analyze(
                ctx, fakes.FakeArgv(reco_param={"mode": "tab"}, task_id=task,
                                    node_name="LordsSwitchTab")
            )
        detail = dict(getattr(res, "detail", None) or {})
        line = impl.progress_line(session)
        print(f"     tab 出口：stop={detail.get('stop')!r} reason={detail.get('reason')!r}")
        check("tab 收工（既有语义不变）", bool(detail.get("stop")),
              f"detail={detail!r}")
        check("★tab 出口的收工行 reason 也是原文★",
              line.done_reason == session.mode_fail_reason,
              f"done={line.done_reason!r} want={session.mode_fail_reason!r}")
        check("tab 出口也 override 到 LordsStop",
              any(impl.STOP_NODE in [str(x) for x in nxt] for _n, nxt in ctx.overrides),
              f"overrides={ctx.overrides!r}")
    impl.reset_sessions()


# ---------------------------------------------------------------------------
# 4. 领主战：17 个既有收工出口逐个接上（源码逐行核对）
# ---------------------------------------------------------------------------
def test_lords_every_stop_wired() -> None:
    print("\n== 4. 领主战：每条「[lords] 收工：」出口后面都有 finish_progress ==")
    lines = (REPO_ROOT / "agent" / "lords_impl.py").read_text(encoding="utf-8").splitlines()
    sites = [i for i, one in enumerate(lines) if 'print(f"[lords] 收工：' in one]
    missing: list[str] = []
    for i in sites:
        window = "\n".join(lines[i + 1:i + 3])
        if "finish_progress(session," not in window:
            missing.append(f"L{i + 1}: {lines[i].strip()}")
    print(f"     收工出口 {len(sites)} 条，未接进度的 {len(missing)} 条")
    check("每条收工出口都接了 finish_progress（漏一条 = 那种收工面板无收工行）",
          not missing, f"missing={missing[:3]}")
    check("收工出口数量没被悄悄删少（票面盘点 = 17 条）", len(sites) == 17,
          f"count={len(sites)}")


# ---------------------------------------------------------------------------
# 5. 外传：步进 = 账本新增一笔
# ---------------------------------------------------------------------------
def test_side_step_on_ledger_new() -> None:
    print("\n== 5. 外传：账本新增一笔 ⇒ 已 X 关（副本名）；已存在不重复 ==")
    import progress as ledger  # noqa: PLC0415

    tmp = Path(tempfile.mkdtemp(prefix="wf_test_146_")) / "progress.json"
    ledger.set_file(tmp)
    side.reset_progress()
    task = 146005
    with panel() as buf:
        one = fakes.FakeArgv(task_id=task, act_param={"scope": "百兽王冠", "stage": "秘宝之力"})
        two = fakes.FakeArgv(task_id=task, act_param={"scope": "百兽王冠", "stage": "前往圣地"})
        check("第一笔记账成功", side.MarkDoneAction().run(None, one) is True)
        line = side.progress_line(one)
        check("一关完成 ⇒ 已 1 关（副本名）",
              line.lines == ["[进度] 外传 开始", "[进度] 外传 已 1 关（百兽王冠）"],
              f"lines={line.lines!r}")
        check("total=0 / unit=关（外传没有固定分母）",
              line.total == 0 and line.unit == "关", f"total={line.total!r} unit={line.unit!r}")
        check("开始只出一条（start 幂等）",
              len([one_line for one_line in line.lines if one_line.endswith("开始")]) == 1,
              f"lines={line.lines!r}")

        side.MarkDoneAction().run(None, one)          # 同一关重复记（已存在）
        check("同一关重复记（账本「已存在」）⇒ 不重复出线",
              line.lines == ["[进度] 外传 开始", "[进度] 外传 已 1 关（百兽王冠）"],
              f"lines={line.lines!r}")

        side.MarkDoneAction().run(None, two)          # 第二关
        check("第二关 ⇒ 已 2 关",
              line.lines[-1] == "[进度] 外传 已 2 关（百兽王冠）", f"lines={line.lines!r}")
        check("面板只有进度行，且没有假分母 i/N",
              all(re.match(r"^\[进度\] 外传 ", one_line) for one_line in _panel_lines(buf))
              and not any(re.search(r"\d+/\d+", one_line) for one_line in _panel_lines(buf)),
              f"panel={_panel_lines(buf)!r}")
    side.reset_progress()


# ---------------------------------------------------------------------------
# 6. 外传：SidePageDoneStop 出口的收工行
# ---------------------------------------------------------------------------
def test_side_done_at_page_done_stop() -> None:
    print("\n== 6. 外传：SidePageDoneStop（page_done_repeat → StopTask）⇒ 收工行复用既有文案 ==")
    from stage_rows import side_list_all_done  # noqa: PLC0415

    check("这一帧确实是「本页全清」（有 COMPLETE!!、无 NEW、解析得出关卡行）",
          side_list_all_done(ALL_COMPLETE_FRAME) is True)
    side.reset_progress()
    side._reset_page_done()
    for _ in range(3):                    # 既有计数：连续 3 次全清页
        side._note_page_done()
    saved_ocr = side.ocr_all
    side.ocr_all = lambda *_a, **_k: list(ALL_COMPLETE_FRAME)
    argv = fakes.FakeArgv(reco_param={"ocr_entry": "OcrTask"}, task_id=146006)
    try:
        with panel() as buf:
            res = side.PageDoneRepeatRecognition().analyze(None, argv)
            detail = dict(getattr(res, "detail", None) or {})
            line = side.progress_line(argv)
            reason = line.done_reason
            print(f"     repeat={detail.get('repeat')!r} reason={reason!r}")
            check("命中收工（既有判据不变）", bool(detail.get("repeat")), f"detail={detail!r}")
            check("收工行 reason 以既有文案开头",
                  reason.startswith("连续 3 次全清页且其间无任何关卡完成"),
                  f"reason={reason!r}")
            check("面板收工行 == [进度] 外传 收工：<既有文案>",
                  f"[进度] 外传 收工：{reason}" in _panel_lines(buf),
                  f"panel={_panel_lines(buf)!r}")
            check("收工行排在「开始」之后（面板顺序不倒）",
                  _panel_lines(buf) == [
                      "[进度] 外传 开始",
                      f"[进度] 外传 收工：{reason}",
                  ],
                  f"panel={_panel_lines(buf)!r}")
            # 收工后不再报进度
            before = list(line.lines)
            side.note_stage_done("百兽王冠", argv)
            check("收工后 step 静默", line.lines == before, f"lines={line.lines!r}")
    finally:
        side.ocr_all = saved_ocr
        side._reset_page_done()
        side.reset_progress()


# ---------------------------------------------------------------------------
# 7. 格式唯一：场景不许自拼 [进度]
# ---------------------------------------------------------------------------
def test_no_handmade_format() -> None:
    print("\n== 7. 场景里不许自拼 [进度]（格式唯一真源 = reporting.format_progress）==")
    # ★判据与 hooks_146 共用一份实现★：AST 常量扫描（docstring / 注释不算「拼格式」），
    #   并禁止绕过 Progress 直接 reporting.say(...)。两边各写一份就是第二套判据。
    msgs = h146._handmade_failures()
    check("lords_impl.py / side_impl.py 里没有自拼的「[进度]」常量、也没有 reporting.say",
          msgs == [], f"msgs={msgs[:2]}")
    check("两个场景都走 reporting.Progress（唯一出口）",
          "import reporting" in (REPO_ROOT / "agent" / "lords_impl.py").read_text(encoding="utf-8")
          and "import reporting" in (REPO_ROOT / "agent" / "side_impl.py").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 8. 无漂移
# ---------------------------------------------------------------------------
def test_drift() -> None:
    print("\n== 8. 无漂移（scene.drift.check_all()）==")
    from scene import drift  # noqa: PLC0415

    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移", msgs == [], f"drift={msgs[:2]}")


def main() -> int:
    print("=" * 72)
    print("#10 领主战 / 外传 · 用户可见进度行（离线）")
    print("=" * 72)
    for fn in (
        test_lords_start_and_note,
        test_lords_step_reuses_sessions,
        test_lords_done_at_stop_exits,
        test_lords_every_stop_wired,
        test_side_step_on_ledger_new,
        test_side_done_at_page_done_stop,
        test_no_handmade_format,
        test_drift,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 单节崩了要红，不许整套静默
            import traceback

            traceback.print_exc()
            check(f"{fn.__name__} 未抛异常", False, repr(exc))
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 ❌")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
