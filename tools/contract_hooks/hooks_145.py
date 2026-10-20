# -*- coding: utf-8 -*-
"""#12：幻想连战接入 reporting（第 k/15 关 · 第 j/M 套）—— 契约挂点。

## 这张票的 seam

* ``agent/battle_loop_core.py``：``SceneConfig`` 上新增**可选**字段 ``progress``（默认
  ``None``）+ 唯一调用口 :func:`notify_progress`。三个语义点：
  ``start(total)``（新任务）/ ``step(k, set_no, target_sets)``（该关**结算记账成功**）/
  ``done(reason)``（Done / GiveUp 出口）。
* ``agent/phantom_impl.py``：``_CFG.progress = PhantomProgress(...)``（场景钩子；每个「套」
  一条 ``reporting.Progress``，故第 2 套的 1..15 不会被单调去重吞掉）。

## 四条守卫（对应验收；prove-red 见文末）

1. ``phantom-progress-hook-seam`` —— **可选钩子 + 唯一调用口**：
   ``SceneConfig.progress`` 缺省 None；``notify_progress`` 对 None 是纯 no-op；源码里
   ``scene.progress`` **只出现在** ``notify_progress`` 内（加一处直调即红）；全仓只有
   ``phantom_impl.py`` 的 ``SceneConfig(...)`` 传了 ``progress=``（别的场景不被顺手改）。
2. ``phantom-progress-points`` —— **一步的时机与数据**：记录式钩子证明
   ``start`` 只在新任务一次；``step`` 只在 ``ledger.mark_done`` 落盘成功时（重复结算帧 /
   战斗帧不报），参数是**真实关号** + 套号 + 目标套数；``done`` 在套数达标 / 关卡上限 /
   GiveUp 兜底三个出口各一次，reason 逐字复用既有文案。
3. ``phantom-progress-lines`` —— **面板行**：端到端（真实 ``Phantom*Recognition`` + 假 OCR）
   跑「开始 → 第 1 套 1..15 → 第 2 套 1..15 → 收工」，逐行精确比对（换套从 1 重新数、
   note=第 j/M 套），且机制日志不漏进面板；代码里没有第二份 ``[进度]`` 拼装。
4. ``phantom-progress-fail-open`` —— **钩子坏了不许停跑**：三个方法各自抛异常时
   ``observe`` / 收工识别器不冒泡、账本照常落盘、机制日志点名；``progress=None`` 时
   一行输出都不写。

## prove-red（``python tools\\contract_hooks\\hooks_145.py``，逐条造坏件）

① 把 ``_CFG.progress`` 摘成 None → 3 红（面板行归零）；
② 把 ``PhantomProgress.step`` 换成「整个任务共用一条 Progress」→ 3 红（第 2 套被吞）；
③ 让 ``notify_progress`` 把 step 调两次 → 2 红（时机/去重判据有灵敏度）；
④ 让 ``notify_progress`` 吞掉 done → 2 红（收工行）；
⑤ 往 core 源码里加一处 ``scene.progress`` 直调 → 1 红（唯一调用口）；
⑥ 给 abyss 的 ``SceneConfig(...)`` 加 ``progress=`` → 1 红（只有幻想能挂钩子）；
⑦ 用手工拼的 ``[进度]`` 字面量 → 3 红（格式唯一真源）。
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import io
import json
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：不抢其它 hook / 测试已经放好的路径。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

HOOK_ID_SEAM = "phantom-progress-hook-seam"
HOOK_ID_POINTS = "phantom-progress-points"
HOOK_ID_LINES = "phantom-progress-lines"
HOOK_ID_FAIL_OPEN = "phantom-progress-fail-open"

_TICKET = "#12"


# ---------------------------------------------------------------------------
# 读取真实实现（每次现读：守卫要能看见「刚被改坏的盘上源码」）
# ---------------------------------------------------------------------------
def _core_path() -> Path:
    return AGENT_DIR / "battle_loop_core.py"


def _phantom_path() -> Path:
    return AGENT_DIR / "phantom_impl.py"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 纯判据（prove-red 直接喂坏源码用；probe_* 只从这里下结论）
# ---------------------------------------------------------------------------
def _scene_config_attr_nodes(tree) -> list:
    """源码里所有 ``scene.progress`` 属性访问。"""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "progress"
        and isinstance(node.value, ast.Name)
        and node.value.id == "scene"
    ]


def _function_def(tree, name: str):
    return next(
        (n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
        None,
    )


def _notify_none_guard_ok(fn) -> bool:
    """``notify_progress`` 里必须有 ``if hook is None: return``（None = 一个字节都不写）。"""
    if fn is None:
        return False
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if not (isinstance(test.left, ast.Name) and test.left.id == "hook"):
            continue
        if not any(isinstance(op, ast.Is) for op in test.ops):
            continue
        if any(isinstance(comp, ast.Constant) and comp.value is None for comp in test.comparators):
            if any(isinstance(inner, ast.Return) for inner in node.body):
                return True
    return False


def _seam_failures(source: str) -> list[str]:
    """唯一调用口判据：``scene.progress`` 只许出现在 ``notify_progress`` 里 + 有 None 守卫。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"battle_loop_core.py 无法解析：{exc}"]
    problems: list[str] = []
    notify = _function_def(tree, "notify_progress")
    if notify is None:
        return ["battle_loop_core.py 里没有 notify_progress（进度钩子的唯一调用口没了）"]
    everywhere = _scene_config_attr_nodes(tree)
    inside = set(_scene_config_attr_nodes(notify))
    outside = [node for node in everywhere if node not in inside]
    if outside:
        problems.append(
            f"scene.progress 在 notify_progress 之外被直调 {len(outside)} 处"
            f"（行 {sorted({n.lineno for n in outside})}）—— 唯一调用口被绕开"
        )
    if not everywhere:
        problems.append("notify_progress 没有读 scene.progress（钩子根本没接上）")
    if not _notify_none_guard_ok(notify):
        problems.append("notify_progress 缺少 `if hook is None: return` 守卫（None 时不再等价旧行为）")
    return problems


def _scene_config_call_sites(source: str) -> list[tuple[int, bool]]:
    """源码里每个 ``SceneConfig(...)`` / ``_SceneConfig(...)`` 调用 → (行号, 是否传了 progress)。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    sites: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else ""
        )
        if name in ("SceneConfig", "_SceneConfig"):
            sites.append((node.lineno, any(kw.arg == "progress" for kw in node.keywords)))
    return sites


def _only_phantom_failures(sources: dict[str, str]) -> list[str]:
    """只有 ``phantom_impl.py`` 能挂进度钩子；其它场景的配置必须保持缺省 None。"""
    problems: list[str] = []
    hook_files = []
    for name, source in sorted(sources.items()):
        for lineno, has_progress in _scene_config_call_sites(source):
            if not has_progress:
                continue
            hook_files.append(name)
            if name != "phantom_impl.py":
                problems.append(f"{name}:{lineno} 的 SceneConfig(...) 传了 progress= —— 只有幻想连战能挂进度钩子")
    if hook_files.count("phantom_impl.py") != 1:
        problems.append(
            f"phantom_impl.py 必须**恰好**有一处 SceneConfig(progress=...)（实际 {hook_files.count('phantom_impl.py')} 处）"
        )
    return problems


def _docstring_node_ids(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", []) or []
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _handbuilt_progress_literals(source: str) -> list[str]:
    """**代码**（非 docstring）里的 ``[进度]`` 字面量 —— 空 = 格式只有 reporting 一份。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["源码无法解析"]
    skip = _docstring_node_ids(tree)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip and "[进度]" in node.value:
                bad.append(node.value[:60])
        elif isinstance(node, ast.JoinedStr):
            for part in ast.walk(node):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    if "[进度]" in part.value:
                        bad.append(part.value[:60])
    return bad


def _agent_sources() -> dict[str, str]:
    return {path.name: _read(path) for path in sorted(AGENT_DIR.glob("*.py"))}


# ---------------------------------------------------------------------------
# 帧 / argv（与 test_phantom_sets.py 同形状）
# ---------------------------------------------------------------------------
class _TaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class _Argv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = _TaskDetail(task_id)
        self.custom_recognition_param = json.dumps(param)


BATTLE_ITEMS = [
    ("时间 09:53", [300, 1200, 80, 30]),
    ("分数 0000001", [430, 1200, 120, 30]),
]


def _main_items(stage: int):
    return [
        ("不可续战", [300, 980, 90, 30]),
        ("推荐编成", [55, 1105, 97, 29]),
        ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
        (f"第{stage}关", [345, 131, 90, 30]),
        ("战斗", [300, 700, 60, 30]),
    ]


def _ocr_frames(items):
    return lambda context, image, entry="OcrTask": list(items)


def _settle(core, cfg, stage: int) -> None:
    with core.lock(cfg):
        core.session(cfg)["in_fight"] = True
        core.session(cfg)["cur_stage"] = stage
        core.session(cfg)["last_state"] = None
        core.session(cfg)["last_observe_ts"] = 0.0
    core.observe(cfg, "phantom_settle", {}, [])


@contextlib.contextmanager
def _isolated(ph, core, ledger, ledger_path: Path):
    """隔离会话 / 账本 / 面板输出（probe 跑完**必定**还原，绝不污染其它 hook）。"""
    import reporting  # noqa: PLC0415

    with ph._LOCK:
        saved_session = dict(ph._SESSION)
    saved_default = ledger._DEFAULT
    old_panel = reporting._REAL_STDOUT
    old_stdout = sys.stdout
    panel, mech = io.StringIO(), io.StringIO()
    try:
        with ph._LOCK:
            ph._SESSION.clear()
            ph._SESSION.update(core._new_session(ph._CFG))
        ledger.set_file(ledger_path)
        reporting.set_quiet(False)
        reporting._REAL_STDOUT = panel
        sys.stdout = mech
        yield panel, mech
    finally:
        sys.stdout = old_stdout
        reporting._REAL_STDOUT = old_panel
        reporting.set_quiet(False)
        with ledger._LOCK:
            ledger._DEFAULT = saved_default
        with ph._LOCK:
            ph._SESSION.clear()
            ph._SESSION.update(saved_session)


# ---------------------------------------------------------------------------
# 守卫 1：可选钩子 + 唯一调用口 + 只有幻想挂
# ---------------------------------------------------------------------------
def probe_hook_seam() -> bool:
    """``SceneConfig.progress`` 可选、``notify_progress`` 是唯一调用口、别的场景不受影响。"""
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415

    fields = {field.name: field for field in dataclasses.fields(core.SceneConfig)}
    field = fields.get("progress")
    if field is None or field.default is not None:
        print("  [12] SceneConfig 没有「默认 None」的 progress 字段")
        return False
    classify_only = core.SceneConfig(
        scene="probe", state_prefix="probe", classify_order=("loading",)
    )
    if classify_only.progress is not None:
        print("  [12] classify-only 配置的 progress 不是 None")
        return False
    if core.notify_progress(classify_only, "step", 1, 1, 1) is not None:
        print("  [12] notify_progress(None) 不是纯 no-op")
        return False

    problems = _seam_failures(_read(_core_path()))
    problems += _only_phantom_failures(_agent_sources())
    # 接线：幻想真的挂上了自己的场景钩子，且分母一致。
    if not isinstance(ph._CFG.progress, ph.PhantomProgress):
        problems.append("phantom_impl._CFG.progress 不是 PhantomProgress")
    elif ph._CFG.progress.max_stages != ph._CFG.max_stages:
        problems.append(
            f"进度分母 {ph._CFG.progress.max_stages} != 场景 max_stages {ph._CFG.max_stages}"
        )
    if problems:
        print("  [12] 唯一调用口/唯一挂点不成立：")
        for problem in problems[:5]:
            print(f"    - {problem}")
        return False
    return True


# ---------------------------------------------------------------------------
# 守卫 2：一步的时机 / 数据 / 收工出口（记录式钩子）
# ---------------------------------------------------------------------------
class _Recorder:
    """记录三个语义点（不打印）—— 证明「钩子什么时候被调、带什么数据」。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, total):
        self.calls.append(("start", total))

    def step(self, index, set_no=0, target_sets=0):
        self.calls.append(("step", index, set_no, target_sets))

    def done(self, reason=""):
        self.calls.append(("done", reason))


def _steps(rec: _Recorder) -> list[tuple]:
    return [call for call in rec.calls if call[0] == "step"]


def probe_call_points() -> bool:
    """start 一次；step 只在记账成功处、参数是真实关号/套号/目标；done 三个出口各一次。"""
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415
    import progress as ledger  # noqa: PLC0415

    rec = _Recorder()
    cfg = dataclasses.replace(ph._CFG, progress=rec)
    with tempfile.TemporaryDirectory() as d:
        with _isolated(ph, core, ledger, Path(d) / "p.json") as (_panel, _mech):
            core.sync_task(cfg, 7001)              # 新任务 → start
            core.sync_task(cfg, 7001)              # 同任务再来一次 → 不许再 start
            core.set_target(cfg, {"target_sets": 2})
            for st in range(1, 16):                # 第 1 套 1..15
                core.observe(cfg, "phantom_main", {}, _main_items(st))
                _settle(core, cfg, st)
                if st == 5:
                    _settle(core, cfg, 5)          # 同一关重复结算帧 → 不许 step
            core.observe(cfg, "phantom_battle", {}, list(BATTLE_ITEMS))  # 战斗帧 → 不许 step
            core.observe(cfg, "phantom_main", {}, _main_items(1))        # 第 2 套第 1 关
            _settle(core, cfg, 1)
            # ---- 收工出口 ①套数达标 ----
            with core.lock(cfg):
                core.session(cfg)["completed_sets"] = 2
            done_cls = core.make_done_reco(cfg, _ocr_frames(_main_items(1)))
            done_cls().analyze(None, _Argv(7001, {"ocr_entry": "OcrTask", "target_sets": 2}))
            # ---- 收工出口 ②关卡上限 ----
            with core.lock(cfg):
                core.session(cfg)["completed_sets"] = 0
                core.session(cfg)["stage_cap"] = 9
                core.session(cfg)["session_max_done"] = 9
            done_cls().analyze(None, _Argv(7001, {"ocr_entry": "OcrTask", "target_sets": 99}))
            # ---- 收工出口 ③GiveUp 兜底（记账数异常） ----
            with core.lock(cfg):
                core.session(cfg)["total_marks"] = 100
            giveup_cls = core.make_giveup_reco(cfg, _ocr_frames(_main_items(1)))
            giveup_cls().analyze(None, _Argv(7001, {"ocr_entry": "OcrTask", "target_sets": 2}))

    expected_steps = [("step", st, 1, 2) for st in range(1, 16)] + [("step", 1, 2, 2)]
    got_steps = _steps(rec)
    ok = True
    if rec.calls.count(("start", 15)) != 1:
        print(f"  [12] start 次数不对：{rec.calls.count(('start', 15))}（应为 1）")
        ok = False
    if got_steps != expected_steps:
        print(f"  [12] step 调用序列不对：{got_steps}")
        ok = False
    dones = [call for call in rec.calls if call[0] == "done"]
    if dones != [
        ("done", "已完成 2 套（目标 2 套）"),
        ("done", "已达关卡上限：第 9 关已打完"),
        ("done", "关卡记账数异常（100）"),
    ]:
        print(f"  [12] done 出口不对：{dones}")
        ok = False
    return ok


# ---------------------------------------------------------------------------
# 守卫 3：面板行（端到端、逐行）
# ---------------------------------------------------------------------------
def probe_panel_lines() -> bool:
    """开始 / 第 1 套 1..15 / 换套后第 2 套 1..15 / 收工 —— 面板逐行精确。"""
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415
    import progress as ledger  # noqa: PLC0415
    import reporting  # noqa: PLC0415

    if ph._CFG.progress is None:
        print("  [12] _CFG.progress 被摘成 None —— 面板不会有任何进度行")
        return False
    ph._CFG.progress.reset()
    real_ocr = ph._ocr
    try:
        with tempfile.TemporaryDirectory() as d:
            with _isolated(ph, core, ledger, Path(d) / "p.json") as (panel, mech):
                ph._ocr = _ocr_frames(_main_items(3))
                ph.PhantomDoneRecognition().analyze(               # 新任务 + 目标 2 套
                    None, _Argv(7101, {"ocr_entry": "OcrTask", "target_sets": 2})
                )
                for st in range(1, 16):                            # 第 1 套
                    ph._ocr = _ocr_frames(_main_items(st))
                    ph.PhantomStateRecognition().analyze(None, _Argv(7101, {"ocr_entry": "OcrTask"}))
                    _settle(core, ph._CFG, st)
                for st in range(1, 16):                            # 第 2 套（note 必须换）
                    ph._ocr = _ocr_frames(_main_items(st))
                    ph.PhantomStateRecognition().analyze(None, _Argv(7101, {"ocr_entry": "OcrTask"}))
                    _settle(core, ph._CFG, st)
                ph._ocr = _ocr_frames(_main_items(1))
                ph.PhantomDoneRecognition().analyze(
                    None, _Argv(7101, {"ocr_entry": "OcrTask", "target_sets": 2})
                )
            panel_lines = panel.getvalue().splitlines()
            panel_text = panel.getvalue()
            mech_text = mech.getvalue()
    finally:
        ph._ocr = real_ocr
        ph._CFG.progress.reset()

    expected = ["[进度] 幻想连战 开始（共 15 关）"]
    expected += [reporting.format_progress("幻想连战", st, 15, "关", "第 1/2 套") for st in range(1, 16)]
    expected += [reporting.format_progress("幻想连战", st, 15, "关", "第 2/2 套") for st in range(1, 16)]
    expected += ["[进度] 幻想连战 收工：已完成 2 套（目标 2 套）"]
    ok = True
    if panel_lines != expected:
        pos = next(
            (i for i, (a, b) in enumerate(zip(panel_lines, expected)) if a != b),
            min(len(panel_lines), len(expected)),
        )
        print(f"  [12] 面板行不吻合（{len(panel_lines)} vs {len(expected)}，首个差异 @{pos}）")
        ok = False
    if "[phantom]" in panel_text:
        print("  [12] 机制日志漏进了面板")
        ok = False
    if "[进度]" in mech_text:
        print("  [12] 进度行混进了机制日志")
        ok = False
    bad = _handbuilt_progress_literals(_read(_core_path())) + _handbuilt_progress_literals(
        _read(_phantom_path())
    )
    if bad:
        print(f"  [12] 代码里出现自拼的进度格式：{bad[:2]}")
        ok = False
    if "import reporting" not in _read(_phantom_path()):
        print("  [12] phantom_impl 没有走 reporting（进度行不是唯一出口）")
        ok = False
    if "import reporting" in _read(_core_path()):
        print("  [12] battle_loop_core 依赖了 reporting —— 引擎不再场景无关")
        ok = False
    return ok


# ---------------------------------------------------------------------------
# 守卫 4：失败开放（钩子抛异常不许停跑）
# ---------------------------------------------------------------------------
class _ExplodingHook:
    def start(self, total):
        raise RuntimeError("注入的坏 start")

    def step(self, index, set_no=0, target_sets=0):
        raise RuntimeError("注入的坏 step")

    def done(self, reason=""):
        raise RuntimeError("注入的坏 done")


def probe_failure_open() -> bool:
    """钩子抛异常：不冒泡、账本照常记、机制日志点名；None 时零输出。"""
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415
    import progress as ledger  # noqa: PLC0415

    cfg = dataclasses.replace(ph._CFG, progress=_ExplodingHook())
    raised = ""
    booked = False
    none_writes = False
    with tempfile.TemporaryDirectory() as d:
        with _isolated(ph, core, ledger, Path(d) / "p.json") as (panel, mech):
            try:
                core.sync_task(cfg, 7201)
                with core.lock(cfg):
                    core.session(cfg)["in_fight"] = True
                    core.session(cfg)["cur_stage"] = 1
                    core.session(cfg)["completed_sets"] = 1
                core.observe(cfg, "phantom_settle", {}, [])
                done_cls = core.make_done_reco(cfg, _ocr_frames(_main_items(1)))
                done_cls().analyze(None, _Argv(7201, {"ocr_entry": "OcrTask", "target_sets": 1}))
            except Exception as exc:  # noqa: BLE001
                raised = repr(exc)
            text = mech.getvalue()
            booked = ledger.is_done(ph._stage_key(1, 1))
            none_panel_before = panel.getvalue()
            off = dataclasses.replace(ph._CFG, progress=None)
            core.notify_progress(off, "start", 15)
            core.notify_progress(off, "step", 1, 1, 1)
            core.notify_progress(off, "done", "x")
            none_writes = panel.getvalue() != none_panel_before
    ok = True
    if raised:
        print(f"  [12] 坏钩子把异常抛进了跑图：{raised}")
        ok = False
    if not booked:
        print("  [12] 钩子抛异常连累了记账（phantom/set/1/stage/1 没落盘）")
        ok = False
    for marker in ("进度钩子 start 失败", "进度钩子 step 失败", "进度钩子 done 失败"):
        if marker not in text:
            print(f"  [12] 机制日志缺 {marker!r}")
            ok = False
    if none_writes:
        print("  [12] progress=None 时面板仍被写（不启用也必须一个字节都不写）")
        ok = False
    return ok


# ---------------------------------------------------------------------------
# 探针清单（prove_red 只读这一份；hooks_115 打瞎 probe_* 后必红）
# ---------------------------------------------------------------------------
PROBES = (
    (HOOK_ID_SEAM, probe_hook_seam),
    (HOOK_ID_POINTS, probe_call_points),
    (HOOK_ID_LINES, probe_panel_lines),
    (HOOK_ID_FAIL_OPEN, probe_failure_open),
)


def _all_failures() -> list[str]:
    """真实实现上跑全部探针（名字带 failure：hooks_115 打瞎它 = 永远没问题）。"""
    return [hook_id for hook_id, probe in PROBES if not probe()]


# ---------------------------------------------------------------------------
# prove-red：造坏件，探针必须变红
# ---------------------------------------------------------------------------
def _leg(name: str, probe, failures: list[str]) -> bool:
    ok = not probe()             # 探针应报红（返回 False）
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {'红（守卫有灵敏度）' if ok else '仍绿（守卫是假的）'}")
    if not ok:
        failures.append(name)
    return ok


def _broken_step_one_progress(self, index, set_no=0, target_sets=0):
    """坏件：整个任务共用一条 Progress（换套不换）—— 第 2 套会被单调去重吞掉。"""
    import reporting  # noqa: PLC0415

    if self._current is None:
        self._current = reporting.Progress(self.display, total=self.max_stages, unit=self.unit)
        self._emit(self._current.start())
    return self._current.step(index)


def prove_red() -> bool:
    """七条破坏实验（进程内 monkeypatch + 造坏源码，跑完还原）。"""
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415
    import reporting  # noqa: PLC0415

    failures: list[str] = []
    checks: list[bool] = []

    real_cfg_progress = ph._CFG.progress
    real_step = ph.PhantomProgress.step
    real_notify = core.notify_progress

    print(f"破坏实验：{len(PROBES)} 条守卫 + 3 条静态判据")
    try:
        # ① 摘掉钩子 → 面板行归零
        object.__setattr__(ph._CFG, "progress", None)
        checks.append(_leg("把 _CFG.progress 摘成 None", probe_panel_lines, failures))
        object.__setattr__(ph._CFG, "progress", real_cfg_progress)

        # ② 换套不换 Progress（整个任务一条）→ 第 2 套被吞
        ph.PhantomProgress.step = _broken_step_one_progress
        checks.append(_leg("PhantomProgress.step 换成「整个任务一条 Progress」", probe_panel_lines, failures))
        ph.PhantomProgress.step = real_step

        # ③ step 被调两次（时机/去重判据失效）
        def _notify_double(sentence, method, *args):  # noqa: ANN001
            real_notify(sentence, method, *args)
            if method == "step":
                real_notify(sentence, method, *args)

        core.notify_progress = _notify_double
        checks.append(_leg("notify_progress 把 step 调两次", probe_call_points, failures))
        core.notify_progress = real_notify

        # ④ done 被吞（收工行消失）
        def _notify_drop_done(sentence, method, *args):  # noqa: ANN001
            if method == "done":
                return
            real_notify(sentence, method, *args)

        core.notify_progress = _notify_drop_done
        checks.append(_leg("notify_progress 吞掉 done", probe_call_points, failures))
        core.notify_progress = real_notify

        # ⑤ 唯一调用口被绕开（往 core 源码里加一处 scene.progress 直调）
        broken_src = _read(_core_path()) + (
            "\n\ndef _sneaky(scene):\n"
            "    scene.progress.step(1, 1, 1)\n"
        )
        bad = _seam_failures(broken_src)
        red_5 = bool(bad)
        print(f"  [{'PASS' if red_5 else 'FAIL'}] 往 core 加一处 scene.progress 直调 -> "
              f"{'红' if red_5 else '仍绿'}")
        checks.append(red_5)

        # ⑥ 别的场景也挂进度钩子（只有幻想能挂）
        broken_sources = dict(_agent_sources())
        broken_sources["abyss_impl.py"] = broken_sources["abyss_impl.py"] + (
            "\n\n_CFG2 = core.SceneConfig(scene='abyss2', state_prefix='abyss2', "
            "classify_order=('loading',), progress=object())\n"
        )
        bad = _only_phantom_failures(broken_sources)
        red_6 = bool(bad)
        print(f"  [{'PASS' if red_6 else 'FAIL'}] 给深渊的 SceneConfig 加 progress= -> "
              f"{'红' if red_6 else '仍绿'}")
        checks.append(red_6)

        # ⑦ 场景自己拼第二份进度格式
        bad = _handbuilt_progress_literals("LINE = f'[进度] 幻想连战 {k}/{n} 关'\n")
        red_7 = bool(bad)
        print(f"  [{'PASS' if red_7 else 'FAIL'}] 手拼 [进度] 字面量 -> {'红' if red_7 else '仍绿'}")
        checks.append(red_7)
    finally:
        object.__setattr__(ph._CFG, "progress", real_cfg_progress)
        ph.PhantomProgress.step = real_step
        core.notify_progress = real_notify
        try:
            ph._CFG.progress.reset()
        except Exception:  # noqa: BLE001
            pass
        reporting.set_quiet(False)

    green = not _all_failures()
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现上四条守卫全绿")
    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★ " + ", ".join(failures)))
    return ok


# ---------------------------------------------------------------------------
# 挂点导出（缺 HOOKS = discover_hooks 抛异常，会连坐别的票）
# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_SEAM,
        _TICKET,
        "幻想进度钩子是可选的唯一调用口：SceneConfig.progress 缺省 None、notify_progress 对 None "
        "纯 no-op、scene.progress 只在 notify_progress 内出现，且全仓只有 phantom_impl 挂钩子",
        probe_hook_seam,
    ),
    (
        HOOK_ID_POINTS,
        _TICKET,
        "一步的时机/数据：start 只在新任务一次；step 只在结算记账成功后（重复结算帧/战斗帧不报）"
        "且参数是真实关号+套号+目标套数；done 在套数达标/关卡上限/GiveUp 三出口各一次",
        probe_call_points,
    ),
    (
        HOOK_ID_LINES,
        _TICKET,
        "面板行唯一真源：端到端跑两套逐关，逐行精确（换套从 1 重新数、note=第 j/M 套），"
        "机制日志不漏进面板，代码里没有第二份 [进度] 拼装",
        probe_panel_lines,
    ),
    (
        HOOK_ID_FAIL_OPEN,
        _TICKET,
        "钩子失败开放：start/step/done 各自抛异常都不冒泡、账本照常落盘、机制日志点名；"
        "progress=None 时面板零输出（与旧实现等价）",
        probe_failure_open,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    bad = _all_failures()
    for hook_id, _probe in PROBES:
        print(f"  [{'PASS' if hook_id not in bad else 'FAIL'}] {hook_id}")
    raise SystemExit(0 if (not bad and prove_red()) else 1)
