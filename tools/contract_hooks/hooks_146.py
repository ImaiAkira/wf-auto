# -*- coding: utf-8 -*-
"""#10：领主战 / 外传接入 ``agent/reporting.py`` —— 面板上「已 X 个目标 / 已 X 关」。

## 为什么有这张票

运维要求「这些模式要显示进度」（规格 ``docs/spec/progress-visibility.md`` §C）。地基（#142）
已经把唯一出口造好（``say`` / ``log`` / ``Progress`` / ``format_progress``），但**领主战与
外传一次都没调用它**：``agent/lords_impl.py`` 按「轮」规划目标、``agent/side_impl.py``
按账本逐关打，两边只有机制 ``print``，面板上看不到「打到哪了」。

本票只做两件事（**不碰任何判定**）：领主战「一个目标打完」与「收工」，外传「一关完成」
与「收工」，各自调一次 :class:`reporting.Progress`。

## 契约（守卫口径）

- **H1 步进复用既有计数**（``lords-target-step-reuses-sessions``）：见到战斗/结算 = 一个目标
  （成员 × 档位）打完 ⇒ ``[进度] 领主战 已 N 个目标（第 j 轮·计划 M 个）``，**N 就是**
  ``Session.sessions_played``（点【挑战】时 +1 的既有唯一场次计数）。重复证据 / 倒退数字都
  不再出线（``Progress.step`` 单调去重）；``_note_after_fight`` **不许**改 ``sessions_played``。
- **H2 note 每轮更新**（``lords-round-note-planned``）：一轮规划落地 ⇒ ``第 j 轮·计划 N 个``
  （j 由既有 ``round_index`` 显示成 1 起算，N = 本轮目标数）；``total=0`` / ``unit=个目标``
  —— **不编分母**（进度行里绝不能出现 ``i/N``）。
- **H3 收工接既有出口**（``lords-done-at-every-stop-exit``）：每条 ``[lords] 收工：…`` 出口都
  出 ``[进度] 领主战 收工：<同一句 reason>``（动态验两条不同路径 + 源码逐行核对其余出口），
  且 ``override_next`` 到 ``LordsStop`` 的收工语义不变。
- **H4 外传步进 = 账本新增一笔**（``side-step-on-ledger-new``）：``mark_done`` 真的新增时
  ⇒ ``[进度] 外传 已 X 关（副本名）``；同一关「已存在」不重复出线。
- **H5 外传收工复用既有文案**（``side-done-reuses-page-done-reason``）：``SidePageDoneStop``
  （``page_done_repeat`` 命中 → ``StopTask``）⇒ ``[进度] 外传 收工：<page_done_repeat 那句>``。
- **H6 格式唯一**（``lords-side-progress-format``）：两个场景文件里**没有**自拼的
  ``[进度]`` 字符串常量（AST 常量扫描，docstring 除外）、也没有绕过 ``Progress`` 直接
  ``reporting.say(...)``。一拼就有第二份格式（规格 §B 的纪律）。

## prove-red（破坏实验 6 条，全部在内存里）

1. 把 ``lords_impl.note_target_done`` 换成恒空 → **H1 红**；
2. 把 ``lords_impl.note_round_plan`` 换成空 note → **H2 红**；
3. 把 ``lords_impl.finish_progress`` 换成恒空 → **H3 红**；
4. 把 ``side_impl.note_stage_done`` 换成恒空 → **H4 红**；
5. 把 ``side_impl.finish_progress`` 换成恒空 → **H5 红**；
6. 往场景源码副本里塞一行 ``reporting.say("[进度] 领主战 1/9")`` → **H6 红**。

    .venv\\Scripts\\python.exe tools\\contract_hooks\\hooks_146.py
"""

from __future__ import annotations

import ast
import contextlib
import io
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = Path(__file__).resolve().parent

HOOK_ID_LORDS_STEP = "lords-target-step-reuses-sessions"
HOOK_ID_LORDS_NOTE = "lords-round-note-planned"
HOOK_ID_LORDS_DONE = "lords-done-at-every-stop-exit"
HOOK_ID_SIDE_STEP = "side-step-on-ledger-new"
HOOK_ID_SIDE_DONE = "side-done-reuses-page-done-reason"
HOOK_ID_FORMAT = "lords-side-progress-format"

#: 票面盘点的既有收工出口数（``print(f"[lords] 收工：…")``；删一条就要重新盘点）。
LORDS_STOP_SITES = 17

#: H3 的「动态两条」：一条走 mode=read 的 should_stop，一条走 mode=tab 的阶梯用尽。
TAB_FAIL_REASON = "模式页换点阶梯用尽：state=lords_unknown 锚=None（hooks_146 注入）"


# ---------------------------------------------------------------------------
# 惰性导入（挂点模块 import 期必须保持轻：discover_hooks 会扫全部 hooks_*.py）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR), str(AGENT_DIR), str(HOOKS_DIR)):
        if path not in sys.path:
            sys.path.append(path)


def _impl():
    _paths()
    import lords_impl  # noqa: PLC0415

    return lords_impl


def _side():
    _paths()
    import side_impl  # noqa: PLC0415

    return side_impl


def _reporting():
    _paths()
    import reporting  # noqa: PLC0415

    return reporting


def _fakes():
    """假 OCR / 假时钟 / 假 argv 借 ``hooks_100``（同一批真机帧与假 I/O，不抄第二份）。"""
    _paths()
    import hooks_100  # noqa: PLC0415

    return hooks_100


def _h122():
    """战斗/结算帧与 ``_scan_read`` / ``_frame`` 借 ``hooks_122``（真机 484 的读数）。"""
    _paths()
    import hooks_122  # noqa: PLC0415

    return hooks_122


def _h51():
    """外传「本页全清」帧借 ``hooks_51``（真机 event_stage_list 的逐条 OCR 读数）。"""
    _paths()
    import hooks_51  # noqa: PLC0415

    return hooks_51


@contextlib.contextmanager
def _panel(mod):
    """把「面板」换成可读缓冲（生产里它就是进程真实 stdout；quiet 吞不掉它）。"""
    saved_quiet = mod.is_quiet()
    if saved_quiet:
        mod.set_quiet(False)
    old = mod._REAL_STDOUT
    buf = io.StringIO()
    mod._REAL_STDOUT = buf
    try:
        yield buf
    finally:
        mod._REAL_STDOUT = old
        if saved_quiet:
            mod.set_quiet(False)


def _panel_lines(buf) -> list:
    return [line for line in buf.getvalue().splitlines() if line.startswith("[进度]")]


def _all_complete_frame() -> tuple:
    """外传「本页全清」帧：真机关卡列表帧去掉 NEW 行与剧情行（判据 = ``side_list_all_done``）。"""
    stage_items = _h51().STAGE_LIST_ITEMS
    return tuple(
        item
        for item in stage_items
        if not item[0].startswith("NEW") and item[0] not in ("遥远过去的国家", "STORY")
    )


# ---------------------------------------------------------------------------
# H1 领主战：步进复用既有场次计数（sessions_played）
# ---------------------------------------------------------------------------
def _lords_step_failures(impl=None) -> list:
    impl = _impl() if impl is None else impl
    h122 = _h122()
    mod = _reporting()
    msgs: list = []
    task = 146101
    impl.reset_sessions()
    try:
        with _panel(mod) as buf:
            session = impl._session(task)
            impl.note_round_plan(session, 4)
            line = impl.progress_line(session)
            # 三场：第 1、2 场真打；第 2 场再来一次重复证据（闩还在，不许再出线）。
            for played, frame in (
                (1, h122.BATTLE_FRAME),
                (2, h122.SETTLE_FRAME),
                (2, h122.BATTLE_FRAME),
            ):
                session.sessions_played = played
                session.back_to_list_pending = False
                impl._note_after_fight(session, frame)

            steps = [one for one in line.lines if "已 " in one]
            want = [
                "[进度] 领主战 已 1 个目标（第 1 轮·计划 4 个）",
                "[进度] 领主战 已 2 个目标（第 1 轮·计划 4 个）",
            ]
            if steps != want:
                msgs.append(f"步进行不是「已 1 / 已 2 个目标」各一条：{steps!r}")
            if line.count != session.sessions_played:
                msgs.append(
                    f"Progress.count={line.count} 与 sessions_played={session.sessions_played} 不一致 "
                    f"—— 说明又造了一个计数器（票面要求复用既有场次计数）"
                )
            if session.sessions_played != 2:
                msgs.append(f"_note_after_fight 改了 sessions_played（{session.sessions_played}）")

            # 倒退：会话里的既有数字被改小（stale 读数）⇒ 绝不许把进度报回去。
            before = list(line.lines)
            session.back_to_list_pending = False
            session.sessions_played = 1
            impl._note_after_fight(session, h122.BATTLE_FRAME)
            if line.lines != before:
                msgs.append(f"倒退的数字又出了一行（Progress 应单调）：{line.lines!r}")
            if any(__import__("re").search(r"\d+/\d+", one) for one in _panel_lines(buf)):
                msgs.append(f"进度行里出现了假分母 i/N：{_panel_lines(buf)!r}")
    finally:
        impl.reset_sessions()
    return msgs


def probe_lords_target_step() -> bool:
    """H1：一个目标打完 ⇒ 已 N 个目标（N = 既有 sessions_played；重复/倒退静默）。"""
    return _lords_step_failures() == []


# ---------------------------------------------------------------------------
# H2 领主战：note = 第 j 轮·计划 N 个（total=0，不编分母）
# ---------------------------------------------------------------------------
def _lords_note_failures(impl=None) -> list:
    impl = _impl() if impl is None else impl
    fakes = _fakes()
    h122 = _h122()
    mod = _reporting()
    msgs: list = []
    task = 146102
    impl.reset_sessions()
    try:
        with _panel(mod) as buf, fakes.FakeClock(1000.0) as clock:
            ctx = fakes.FakeContext()
            reco = impl.LordsProgressRecognition()
            session = impl._session(task)
            nav = impl._nav_state(session)
            if nav is None:
                return ["取不到导航状态（_nav_state）—— 本探针无从注入整轮扫描"]
            nav.complete_scan(session.round_index, clock.now)
            h122._scan_read(impl, fakes, reco, ctx, task, session, h122.SCAN_A_ROWS)
            line = impl.progress_line(session)
            if line.lines[:1] != ["[进度] 领主战 开始"]:
                msgs.append(f"一轮规划后第一条不是「领主战 开始」：{line.lines[:2]!r}")
            if line.total != 0 or line.unit != "个目标":
                msgs.append(f"total/unit 不是 0/个目标：{line.total!r}/{line.unit!r}")
            want = f"第 1 轮·计划 {len(session.targets)} 个"
            if line.note != want:
                msgs.append(f"note 不是「{want}」：{line.note!r}")

            # 关一轮 + 再扫一次 ⇒ note 跟着轮到「第 2 轮」
            session.attempts_since_read = 1
            session.sessions_played = 1
            h122._scan_read(impl, fakes, reco, ctx, task, session, h122.SCAN_B_ROWS)
            want2 = f"第 2 轮·计划 {len(session.targets)} 个"
            if line.note != want2:
                msgs.append(f"第二轮 note 不是「{want2}」：{line.note!r}")
            if len([one for one in line.lines if one.endswith("开始")]) != 1:
                msgs.append(f"「开始」不是幂等的一条：{line.lines!r}")
            if any(__import__("re").search(r"\d+/\d+", one) for one in _panel_lines(buf)):
                msgs.append(f"进度行里出现了假分母 i/N：{_panel_lines(buf)!r}")
    finally:
        impl.reset_sessions()
    return msgs


def probe_lords_round_note() -> bool:
    """H2：note 每轮更新为本轮计划数（第 j 轮·计划 N 个），total=0 不编分母。"""
    return _lords_note_failures() == []


# ---------------------------------------------------------------------------
# H3 领主战：收工行接在每条既有收工出口（动态两条 + 源码逐行核对全部）
# ---------------------------------------------------------------------------
def _lords_stop_wiring_failures(source: str | None = None) -> list:
    """源码核对：每条 ``print(f"[lords] 收工：…")`` 后面 2 行内必须有 ``finish_progress(session,``。"""
    text = source
    if text is None:
        text = (AGENT_DIR / "lords_impl.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    sites = [i for i, one in enumerate(lines) if 'print(f"[lords] 收工：' in one]
    msgs: list = []
    missing = []
    for i in sites:
        window = "\n".join(lines[i + 1:i + 3])
        if "finish_progress(session," not in window:
            missing.append(f"L{i + 1}: {lines[i].strip()}")
    if missing:
        msgs.append(f"{len(missing)} 条收工出口没接进度收工行：{missing[:2]}")
    if len(sites) != LORDS_STOP_SITES:
        msgs.append(f"收工出口数={len(sites)}，票面盘点 {LORDS_STOP_SITES} 条 —— 删/增出口要同步盘点")
    return msgs


def _lords_done_failures(impl=None) -> list:
    impl = _impl() if impl is None else impl
    fakes = _fakes()
    h122 = _h122()
    mod = _reporting()
    msgs: list = list(_lords_stop_wiring_failures())

    # (a) 全部解禁：mode=read 的 should_stop 出口
    task = 146103
    impl.reset_sessions()
    try:
        with _panel(mod) as buf, fakes.FakeClock(3000.0) as clock:
            ctx = fakes.FakeContext()
            reco = impl.LordsProgressRecognition()
            session = impl._session(task)
            nav = impl._nav_state(session)
            if nav is None:
                return msgs + ["取不到导航状态（_nav_state）—— 收工探针无从注入"]
            nav.complete_scan(session.round_index, clock.now)
            with h122._frame(impl, h122.ALL_DONE_FRAME):
                res = reco.analyze(ctx, fakes.FakeArgv(reco_param={"mode": "read"}, task_id=task))
            detail = dict(getattr(res, "detail", None) or {})
            reason = str(detail.get("reason") or "")
            line = impl.progress_line(session)
            if not detail.get("stop") or not reason:
                msgs.append(f"全部解禁没判收工：stop={detail.get('stop')!r} reason={reason!r}")
            if line.done_reason != reason:
                msgs.append(f"收工行 reason 不是既有原文：{line.done_reason!r} != {reason!r}")
            if f"[进度] 领主战 收工：{reason}" not in _panel_lines(buf):
                msgs.append(f"面板没有收工行：{_panel_lines(buf)!r}")
            if not any(impl.STOP_NODE in [str(x) for x in nxt] for _n, nxt in ctx.overrides):
                msgs.append("收工没有 override 到 LordsStop（收工出口被改动了）")
            before = list(line.lines)
            impl.note_target_done(session)
            if line.lines != before:
                msgs.append("收工后 step 还出线（Progress.done 之后必须静默）")
    finally:
        impl.reset_sessions()

    # (b) 模式页阶梯用尽：mode=tab 的收工出口（与 (a) 不同函数/不同分支）
    task = 146104
    impl.reset_sessions()
    try:
        with _panel(mod) as buf, fakes.FakeClock(4000.0):
            ctx = fakes.FakeContext()
            reco = impl.LordsProgressRecognition()
            session = impl._session(task)
            session.mode_fail_reason = TAB_FAIL_REASON
            with h122._frame(impl, fakes.LIST_FRAME):
                res = reco.analyze(
                    ctx,
                    fakes.FakeArgv(
                        reco_param={"mode": "tab"}, task_id=task, node_name="LordsSwitchTab"
                    ),
                )
            detail = dict(getattr(res, "detail", None) or {})
            line = impl.progress_line(session)
            if not detail.get("stop"):
                msgs.append(f"阶梯用尽没判收工：{detail!r}")
            if line.done_reason != TAB_FAIL_REASON:
                msgs.append(f"tab 出口收工行 reason 不是原文：{line.done_reason!r}")
            if f"[进度] 领主战 收工：{TAB_FAIL_REASON}" not in _panel_lines(buf):
                msgs.append(f"tab 出口面板没有收工行：{_panel_lines(buf)!r}")
            if not any(impl.STOP_NODE in [str(x) for x in nxt] for _n, nxt in ctx.overrides):
                msgs.append("tab 出口没有 override 到 LordsStop")
    finally:
        impl.reset_sessions()
    return msgs


def probe_lords_done() -> bool:
    """H3：每条收工出口都出收工行，且 reason 与既有「[lords] 收工：」原文逐字相同。"""
    return _lords_done_failures() == []


# ---------------------------------------------------------------------------
# H4 外传：步进 = 账本新增一笔
# ---------------------------------------------------------------------------
def _side_step_failures(side=None) -> list:
    side = _side() if side is None else side
    fakes = _fakes()
    mod = _reporting()
    msgs: list = []
    _paths()
    import progress as ledger  # noqa: PLC0415

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook146_")) / "progress.json"
    ledger.set_file(tmp)
    side.reset_progress()
    task = 146105
    try:
        with _panel(mod) as buf:
            one = fakes.FakeArgv(task_id=task, act_param={"scope": "百兽王冠", "stage": "秘宝之力"})
            two = fakes.FakeArgv(task_id=task, act_param={"scope": "百兽王冠", "stage": "前往圣地"})
            if side.MarkDoneAction().run(None, one) is not True:
                msgs.append("MarkDoneAction 第一笔记账没返回 True")
            line = side.progress_line(one)
            want = ["[进度] 外传 开始", "[进度] 外传 已 1 关（百兽王冠）"]
            if line.lines != want:
                msgs.append(f"一关完成后的进度行不是 {want!r}：{line.lines!r}")
            if line.total != 0 or line.unit != "关":
                msgs.append(f"total/unit 不是 0/关：{line.total!r}/{line.unit!r}")
            side.MarkDoneAction().run(None, one)
            if line.lines != want:
                msgs.append(f"账本「已存在」却又报了一步：{line.lines!r}")
            side.MarkDoneAction().run(None, two)
            want2 = want + ["[进度] 外传 已 2 关（百兽王冠）"]
            if line.lines != want2:
                msgs.append(f"第二关的进度行序列不是 {want2!r}：{line.lines!r}")
            if any(__import__("re").search(r"\d+/\d+", one_line) for one_line in _panel_lines(buf)):
                msgs.append(f"外传进度行里出现了假分母 i/N：{_panel_lines(buf)!r}")
    finally:
        ledger.set_file(None)
        side.reset_progress()
    return msgs


def probe_side_step() -> bool:
    """H4：一关完成（账本真的新增一笔）⇒ 已 X 关（副本名）；重复记账不再出线。"""
    return _side_step_failures() == []


# ---------------------------------------------------------------------------
# H5 外传：SidePageDoneStop 出口的收工行复用既有文案
# ---------------------------------------------------------------------------
def _side_done_failures(side=None) -> list:
    side = _side() if side is None else side
    fakes = _fakes()
    mod = _reporting()
    msgs: list = []
    _paths()
    from stage_rows import side_list_all_done  # noqa: PLC0415

    frame = _all_complete_frame()
    if not side_list_all_done(frame):
        return ["测试帧不是「本页全清」—— 探针会空转，先修帧"]
    side.reset_progress()
    side._reset_page_done()
    for _ in range(3):
        side._note_page_done()
    saved_ocr = side.ocr_all
    side.ocr_all = lambda *_a, **_k: list(frame)
    argv = fakes.FakeArgv(reco_param={"ocr_entry": "OcrTask"}, task_id=146106)
    try:
        with _panel(mod) as buf, contextlib.redirect_stdout(io.StringIO()) as log:
            res = side.PageDoneRepeatRecognition().analyze(None, argv)
            detail = dict(getattr(res, "detail", None) or {})
            line = side.progress_line(argv)
            reason = line.done_reason
            if not detail.get("repeat"):
                msgs.append(f"连续 3 次全清没命中收工：{detail!r}")
            if not reason.startswith("连续 3 次全清页且其间无任何关卡完成"):
                msgs.append(f"收工行 reason 不是既有文案：{reason!r}")
            if f"[page_done_repeat] {reason}" not in log.getvalue():
                msgs.append(f"收工行文案与 [page_done_repeat] 打印的不一致：{log.getvalue()!r}")
            if f"[进度] 外传 收工：{reason}" not in _panel_lines(buf):
                msgs.append(f"面板没有收工行：{_panel_lines(buf)!r}")
            before = list(line.lines)
            side.note_stage_done("百兽王冠", argv)
            if line.lines != before:
                msgs.append("收工后 step 还出线（Progress.done 之后必须静默）")
    finally:
        side.ocr_all = saved_ocr
        side._reset_page_done()
        side.reset_progress()
    return msgs


def probe_side_done() -> bool:
    """H5：SidePageDoneStop（page_done_repeat → StopTask）出收工行，reason 复用既有文案。"""
    return _side_done_failures() == []


# ---------------------------------------------------------------------------
# H6 格式唯一：场景里没有自拼的 [进度]（AST 常量扫描，docstring 除外）
# ---------------------------------------------------------------------------
_SCENE_FILES = ("lords_impl.py", "side_impl.py")


def _string_constants_outside_docstrings(source: str) -> list:
    """收集源码里**非 docstring** 的字符串常量（注释本来就不在 AST 里）。"""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
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
        and id(node) not in docstrings
    ]


def _handmade_failures(sources: dict | None = None) -> list:
    msgs: list = []
    files = dict(sources) if sources is not None else {
        name: (AGENT_DIR / name).read_text(encoding="utf-8") for name in _SCENE_FILES
    }
    for name, source in files.items():
        try:
            consts = _string_constants_outside_docstrings(source)
        except SyntaxError as exc:
            msgs.append(f"{name} 解析失败：{exc}")
            continue
        for text in consts:
            if "[进度]" in text:
                msgs.append(f"{name} 自拼了进度行常量：{text!r}（格式唯一真源 = reporting.format_progress）")
        if "reporting.say(" in source:
            msgs.append(f"{name} 直接调了 reporting.say(...) —— 进度必须走 Progress（格式/去重唯一出口）")
    return msgs


def probe_no_handmade_format() -> bool:
    """H6：场景里没有自拼的 ``[进度]`` 字符串，也没有绕过 Progress 的 ``reporting.say``。"""
    return _handmade_failures() == []


# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_LORDS_STEP,
        "#10",
        "领主战：一个目标（成员 × 档位）打完 ⇒ [进度] 领主战 已 N 个目标，N = 既有 "
        "sessions_played（点【挑战】时 +1），不另立计数器；重复/倒退不出线",
        probe_lords_target_step,
    ),
    (
        HOOK_ID_LORDS_NOTE,
        "#10",
        "领主战：note = 第 j 轮·计划 N 个（j 由既有 round_index 显示成 1 起算，N = 本轮目标数）；"
        "total=0 / 个目标，绝不编分母",
        probe_lords_round_note,
    ),
    (
        HOOK_ID_LORDS_DONE,
        "#10",
        "领主战：每条既有 [lords] 收工：出口都出 [进度] 领主战 收工：<同一句 reason>，"
        "且收工仍 override 到 LordsStop",
        probe_lords_done,
    ),
    (
        HOOK_ID_SIDE_STEP,
        "#10",
        "外传：mark_done 真的新增一笔 ⇒ [进度] 外传 已 X 关（副本名）；同一关「已存在」不重复出线",
        probe_side_step,
    ),
    (
        HOOK_ID_SIDE_DONE,
        "#10",
        "外传：SidePageDoneStop（page_done_repeat → StopTask）⇒ [进度] 外传 收工："
        "<page_done_repeat 那句>，文案逐字复用",
        probe_side_done,
    ),
    (
        HOOK_ID_FORMAT,
        "#10",
        "进度格式唯一：lords_impl / side_impl 里没有自拼的 [进度] 字符串常量（docstring 除外），"
        "也没有绕过 Progress 直接 reporting.say",
        probe_no_handmade_format,
    ),
]


# ---------------------------------------------------------------------------
# prove-red：先跑绿，再逐条把实现换坏，判据必须变红
# ---------------------------------------------------------------------------
def _leg(name: str, failures_fn, checks: list) -> None:
    """跑一次破坏后**必须**报红（failures 非空）才算这条破坏实验成立。"""
    msgs = failures_fn()
    red = bool(msgs)
    print(
        f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红（有灵敏度）' if red else '仍绿（守卫是假的）'}"
        + (f"  {msgs[0]}" if msgs else "")
    )
    checks.append(red)


def prove_red() -> bool:
    """6 条破坏实验（全部在内存里改属性 / 造坏源码，跑完还原）。"""
    impl = _impl()
    side = _side()
    checks: list = []

    green = [
        ("H1 目标步进复用 sessions_played", probe_lords_target_step()),
        ("H2 note = 第 j 轮·计划 N 个", probe_lords_round_note()),
        ("H3 收工接每条既有出口", probe_lords_done()),
        ("H4 外传步进 = 账本新增", probe_side_step()),
        ("H5 外传收工复用既有文案", probe_side_done()),
        ("H6 格式唯一（无自拼 [进度]）", probe_no_handmade_format()),
    ]
    for name, ok in green:
        print(f"  [{'PASS' if ok else 'FAIL'}] 真实实现：{name}")
    if not all(ok for _n, ok in green):
        for msg in (
            _lords_step_failures()
            + _lords_note_failures()
            + _lords_done_failures()
            + _side_step_failures()
            + _side_done_failures()
            + _handmade_failures()
        ):
            print(f"      - {msg}")
        print("结果：★prove-red 失败★（真实实现都没跑绿）")
        return False

    real = {
        "note_target_done": impl.note_target_done,
        "note_round_plan": impl.note_round_plan,
        "finish_progress": impl.finish_progress,
        "side_note_stage_done": side.note_stage_done,
        "side_finish_progress": side.finish_progress,
    }
    try:
        # ① 断掉领主战步进 → H1 红
        impl.note_target_done = lambda session: ""  # type: ignore[assignment]
        _leg("把 note_target_done 换成恒空（断掉步进）", _lords_step_failures, checks)
        impl.note_target_done = real["note_target_done"]  # type: ignore[assignment]

        # ② note 不更新 → H2 红
        impl.note_round_plan = lambda session, planned: ""  # type: ignore[assignment]
        _leg("把 note_round_plan 换成空 note", _lords_note_failures, checks)
        impl.note_round_plan = real["note_round_plan"]  # type: ignore[assignment]

        # ③ 收工行不接 → H3 红
        impl.finish_progress = lambda session, reason: ""  # type: ignore[assignment]
        _leg("把 finish_progress 换成恒空（收工不出行）", _lords_done_failures, checks)
        impl.finish_progress = real["finish_progress"]  # type: ignore[assignment]

        # ④ 外传步进断 → H4 红
        side.note_stage_done = lambda *a, **k: ""  # type: ignore[assignment]
        _leg("把 note_stage_done 换成恒空（外传步进断掉）", _side_step_failures, checks)
        side.note_stage_done = real["side_note_stage_done"]  # type: ignore[assignment]

        # ⑤ 外传收工行不接 → H5 红
        side.finish_progress = lambda *a, **k: ""  # type: ignore[assignment]
        _leg("把外传 finish_progress 换成恒空", _side_done_failures, checks)
        side.finish_progress = real["side_finish_progress"]  # type: ignore[assignment]

        # ⑥ 往场景源码副本里塞一行自拼进度 → H6 红
        broken = {
            name: (AGENT_DIR / name).read_text(encoding="utf-8") + '\nreporting.say("[进度] 领主战 1/9")\n'
            for name in _SCENE_FILES
        }
        _leg(
            "往场景源码副本里塞自拼的 [进度] 行",
            lambda: _handmade_failures(sources=broken),
            checks,
        )
    finally:
        impl.note_target_done = real["note_target_done"]  # type: ignore[assignment]
        impl.note_round_plan = real["note_round_plan"]  # type: ignore[assignment]
        impl.finish_progress = real["finish_progress"]  # type: ignore[assignment]
        side.note_stage_done = real["side_note_stage_done"]  # type: ignore[assignment]
        side.finish_progress = real["side_finish_progress"]  # type: ignore[assignment]
        impl.reset_sessions()
        side.reset_progress()

    ok = all(ok for _n, ok in green) and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


def main() -> int:
    print("真实实现（lords_impl / side_impl → reporting.Progress）：")
    green = [
        (HOOK_ID_LORDS_STEP, probe_lords_target_step()),
        (HOOK_ID_LORDS_NOTE, probe_lords_round_note()),
        (HOOK_ID_LORDS_DONE, probe_lords_done()),
        (HOOK_ID_SIDE_STEP, probe_side_step()),
        (HOOK_ID_SIDE_DONE, probe_side_done()),
        (HOOK_ID_FORMAT, probe_no_handmade_format()),
    ]
    for hook_id, ok in green:
        print(f"  [{'PASS' if ok else 'FAIL'}] {hook_id}")
    if not all(ok for _h, ok in green):
        print("结果：★守卫失败★ " + ", ".join(hook_id for hook_id, ok in green if not ok))
        return 1
    return 0 if prove_red() else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
