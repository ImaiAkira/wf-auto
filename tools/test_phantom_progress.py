# -*- coding: utf-8 -*-
"""#12 离线单测：幻想连战接入 reporting —— 用户可见进度行（第 k/15 关 · 第 j/M 套）。

不需要游戏、不需要 AgentServer（纯离线；假 OCR 帧驱动真实的 ``Phantom*Recognition``）：

    .venv\\Scripts\\python.exe tools\\test_phantom_progress.py

覆盖（对应票 #12 的验收 + 规格 ``docs/spec/progress-visibility.md`` §B/§C）：

  1. **接线**：``_CFG.progress`` 是 ``PhantomProgress``，display/unit/分母与场景一致；
     ``SceneConfig.progress`` 缺省 None（classify-only 场景 / 离线守卫不受影响）；
  2. **面板行唯一真源**：整套流程的面板输出**逐行精确等于**期望（开始 / 1..15 / 换套 /
     收工），且机制日志（``[phantom] ...``）一行都不许漏进面板；
  3. **一步的时机**：该关**结算记账成功**才报（重复结算帧、战斗帧、unknown 帧都不报），
     k 是**真实关号**（跳关时按真实关号报，不是自增计数）；
  4. **换套**：第 2 套从 1/15 重新数（note 变 ``第 2/2 套``）—— 这条钉住「每套一条
     Progress」的实现（共用一条会被单调去重吃掉整个第二套）；
  5. **收工**：Done（套数达标 / 关卡上限）与 GiveUp 兜底三个出口各打一条，reason 复用
     既有文案；之后不再出步进行；
  6. **progress=None 时机制行为不变**：同一段脚本分别用 None / 只记录不输出的钩子跑，
     机制输出、会话快照、账本 keys 三者逐字节相同（钩子只是旁路观察者）；
  7. **失败语义**：钩子抛异常 → 不冒泡、跑图照常记账、机制日志点名（进度行坏了不许停跑）；
  8. **格式纪律**：``agent/phantom_impl.py`` / ``agent/battle_loop_core.py`` 的**代码**里
     没有 ``[进度]`` 字面量（只有 docstring 提到它）；引擎不 import reporting。
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
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

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
sys.path.insert(0, str(AGENT_DIR))

import battle_loop_core as core  # noqa: E402
import phantom_impl as ph  # noqa: E402
import progress as ledger  # noqa: E402
import reporting  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 假 OCR 帧 / argv（与 test_phantom_sets.py 同形状）
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
    """一帧【关卡选择页】，画面显示「第 stage 关」→ classify = phantom_main。"""
    return [
        ("不可续战", [300, 980, 90, 30]),
        ("推荐编成", [55, 1105, 97, 29]),
        ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
        (f"第{stage}关", [345, 131, 90, 30]),
        ("战斗", [300, 700, 60, 30]),
    ]


def _force_observe() -> None:
    """绕过 _observe 的「同状态 1.2s 去重」守卫，保证本帧一定被处理。"""
    with ph._LOCK:
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0


def _observe_main(task_id: int, stage: int) -> None:
    _force_observe()
    ph._ocr = lambda context, image, entry="OcrTask": list(_main_items(stage))
    ph.PhantomStateRecognition().analyze(None, _Argv(task_id, {"ocr_entry": "OcrTask"}))


def _observe_as(task_id: int, state: str, stage: int = 1) -> None:
    items = list(BATTLE_ITEMS) if state == "phantom_battle" else list(_main_items(stage))
    _force_observe()
    ph._ocr = lambda context, image, entry="OcrTask": list(items)
    ph.PhantomStateRecognition().analyze(None, _Argv(task_id, {"ocr_entry": "OcrTask"}))


def _settle(task_id: int, stage: int) -> None:
    """模拟「第 stage 关结算」的观察帧（经真实 _observe 记账）。"""
    with ph._LOCK:
        ph._SESSION["in_fight"] = True
        ph._SESSION["cur_stage"] = stage
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0
    ph._observe("phantom_settle", {}, [])


def _play_stage(task_id: int, stage: int) -> None:
    """一关完整时序：关卡选择页第 stage 关 → 结算记账。"""
    _observe_main(task_id, stage)
    _settle(task_id, stage)


def _done_hit(task_id: int, target: int, extra: dict | None = None) -> dict:
    ph._ocr = lambda context, image, entry="OcrTask": list(_main_items(3))
    param = {"ocr_entry": "OcrTask", "target_sets": target}
    param.update(extra or {})
    res = ph.PhantomDoneRecognition().analyze(None, _Argv(task_id, param))
    return {"box": res.box, "detail": res.detail}


def _giveup_hit(task_id: int, target: int, extra: dict | None = None) -> dict:
    ph._ocr = lambda context, image, entry="OcrTask": list(_main_items(3))
    param = {"ocr_entry": "OcrTask", "target_sets": target}
    param.update(extra or {})
    res = ph.PhantomGiveUpRecognition().analyze(None, _Argv(task_id, param))
    return {"box": res.box, "detail": res.detail}


# ---------------------------------------------------------------------------
# 面板 / 机制日志的双路捕获
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _channels():
    """产出 (panel, mech)：panel = reporting.say（用户可见）；mech = sys.stdout（机制）。"""
    old_panel = reporting._REAL_STDOUT
    old_stdout = sys.stdout
    panel, mech = io.StringIO(), io.StringIO()
    reporting.set_quiet(False)          # 测试进程里绝不允许残留静音态
    reporting._REAL_STDOUT = panel
    sys.stdout = mech
    try:
        yield panel, mech
    finally:
        sys.stdout = old_stdout
        reporting._REAL_STDOUT = old_panel
        reporting.set_quiet(False)


def _reset_session() -> None:
    """把幻想会话恢复成刚构造的状态（测试之间互不串味）。"""
    fresh = core._new_session(ph._CFG)
    with ph._LOCK:
        ph._SESSION.clear()
        ph._SESSION.update(fresh)


def _new_task(task_id: int, target: int, scratch: str) -> dict:
    """新任务起点：临时账本 + 干净会话 + 重置进度钩子，然后用 Done 识别器建立目标套数。"""
    ledger.set_file(Path(scratch) / f"p_{task_id}.json")
    _reset_session()
    ph._CFG.progress.reset()
    with ph._LOCK:
        ph._SESSION["task_id"] = None
    return _done_hit(task_id, target)


def _line(display: str, index: int, total: int, unit: str, note: str) -> str:
    """期望行 = reporting 的唯一格式实现（测试**不**自己拼格式）。"""
    return reporting.format_progress(display, index, total, unit, note)


# ---------------------------------------------------------------------------
# 1. 接线 / 缺省
# ---------------------------------------------------------------------------
def test_wiring() -> None:
    print("\n== 1. 接线：_CFG.progress = PhantomProgress；缺省 None = 旧行为 ==")
    progress = ph._CFG.progress
    check("_CFG.progress 是 PhantomProgress", isinstance(progress, ph.PhantomProgress),
          type(progress).__name__)
    check("display = 幻想连战", progress.display == "幻想连战", progress.display)
    check("unit = 关", progress.unit == "关", progress.unit)
    check("分母 == 场景 max_stages == MAX_STAGES",
          progress.max_stages == ph._CFG.max_stages == ph.MAX_STAGES == 15,
          f"{progress.max_stages}/{ph._CFG.max_stages}/{ph.MAX_STAGES}")

    off = dataclasses.replace(ph._CFG, progress=None)
    check("dataclasses.replace(progress=None) 能构造（可选字段不进状态机必填组）",
          off.progress is None and off.scene == "phantom")
    check("notify_progress(None 钩子) 是纯 no-op",
          core.notify_progress(off, "start", 15) is None
          and core.notify_progress(off, "step", 1, 1, 1) is None
          and core.notify_progress(off, "done", "x") is None)

    classify_only = core.SceneConfig(scene="probe", state_prefix="probe",
                                     classify_order=("loading",))
    check("classify-only 配置的 progress 缺省为 None（深渊/五重不受影响）",
          classify_only.progress is None)


# ---------------------------------------------------------------------------
# 2/3/4/5. 端到端：开始 → 两套逐关 → 重复/战斗帧去噪 → 套数达标收工
# ---------------------------------------------------------------------------
def test_panel_lines_full_run() -> None:
    print("\n== 2. 面板行：开始 / 两套各 1..15 / 换套 note / 套数达标收工 ==")
    with tempfile.TemporaryDirectory() as d:
        with _channels() as (panel, mech):
            _new_task(8101, 2, d)
            for st in range(1, 4):          # 第 1 套 1..3
                _play_stage(8101, st)
            _settle(8101, 3)                # 同一关重复结算帧：不得多报一步
            _observe_as(8101, "phantom_battle")
            for st in range(4, 16):         # 第 1 套 4..15（第 15 关 = 一套完成）
                _play_stage(8101, st)
            for st in range(1, 3):          # 第 2 套 1..2
                _play_stage(8101, st)
            for st in range(3, 16):         # 第 2 套 3..15
                _play_stage(8101, st)
            _done_hit(8101, 2)              # 达标：cs(2) >= target(2)
            _settle(8101, 5)                # 收工后：不再出步进行
        panel_text, mech_text = panel.getvalue(), mech.getvalue()

    expected = ["[进度] 幻想连战 开始（共 15 关）"]
    expected += [_line("幻想连战", st, 15, "关", "第 1/2 套") for st in range(1, 16)]
    expected += [_line("幻想连战", st, 15, "关", "第 2/2 套") for st in range(1, 16)]
    expected += ["[进度] 幻想连战 收工：已完成 2 套（目标 2 套）"]
    got = panel_text.splitlines()
    diff = "无"
    if got != expected:
        diff = next(
            ((i, g, e) for i, (g, e) in enumerate(zip(got, expected)) if g != e),
            (min(len(got), len(expected)), "（长度不同）", "（长度不同）"),
        )
    check("面板行逐行精确等于期望（32 行：1 + 15 + 15 + 1）", got == expected,
          f"got={len(got)} lines; 差异={diff}")
    check("★机制日志一行都没漏进面板★", "[phantom]" not in panel_text,
          panel_text[:120] if "[phantom]" in panel_text else "")
    check("★进度行没有混进机制日志★", "[进度]" not in mech_text,
          mech_text[:160] if "[进度]" in mech_text else "")
    check("机制日志照旧（第 1 套·第 1 关完成 / 第 2 套完成）",
          "[phantom] 第 1 套·第 1 关完成" in mech_text
          and "[phantom] 第 2 套完成（一整套 15 关）" in mech_text)
    check("★换套：第 2 套从 1/15 重新数（note=第 2/2 套）★",
          expected[16] == "[进度] 幻想连战 1/15 关（第 2/2 套）", expected[16])
    check("重复结算帧 / 战斗帧没有多出面板行",
          got.count("[进度] 幻想连战 3/15 关（第 1/2 套）") == 1)


def test_real_stage_number() -> None:
    print("\n== 3. k = 真实关号（跳关时按真实关号报，不是自增计数） ==")
    with tempfile.TemporaryDirectory() as d:
        with _channels() as (panel, _mech):
            _new_task(8202, 1, d)
            for st in (1, 2, 5):
                _play_stage(8202, st)
        got = panel.getvalue().splitlines()
    check("跳关 1,2,5 → 报 1/15、2/15、5/15（不是 1,2,3）",
          got == [
              "[进度] 幻想连战 开始（共 15 关）",
              "[进度] 幻想连战 1/15 关（第 1/1 套）",
              "[进度] 幻想连战 2/15 关（第 1/1 套）",
              "[进度] 幻想连战 5/15 关（第 1/1 套）",
          ], str(got))


def test_cap_done_line() -> None:
    print("\n== 4. 收工出口 ①关卡上限：reason 复用「已达关卡上限：第 N 关已打完」 ==")
    with tempfile.TemporaryDirectory() as d:
        with _channels() as (panel, _mech):
            _new_task(8303, 99, d)
            for st in range(1, 6):
                _play_stage(8303, st)
            with ph._LOCK:
                ph._SESSION["stage_cap"] = 5      # 选项「打到第 5 关以后放弃」注入的效果
            _done_hit(8303, 99)
        got = panel.getvalue().splitlines()
    check("上限出口打出收工行，且排在 5/15 之后",
          got[-1] == "[进度] 幻想连战 收工：已达关卡上限：第 5 关已打完", got[-1])
    check("收工前是 1..5 关的步进", got[1:6] == [
        f"[进度] 幻想连战 {st}/15 关（第 1/99 套）" for st in range(1, 6)
    ], str(got[1:6]))


def test_giveup_done_line() -> None:
    print("\n== 5. 收工出口 ②GiveUp 兜底：reason 逐字复用兜底文案 ==")
    with tempfile.TemporaryDirectory() as d:
        with _channels() as (panel, _mech):
            _new_task(8404, 1, d)
            for st in (1, 2):
                _play_stage(8404, st)
            with ph._LOCK:
                ph._SESSION["last_progress_ts"] = time.monotonic() - 1000.0  # 「无新进度」判据必中
            result = _giveup_hit(8404, 1, {"no_progress_sec": 900})
        got = panel.getvalue().splitlines()
    check("GiveUp 命中且 reason = 900s 无新关卡完成",
          result["box"] == [0, 0, 0, 0] and result["detail"].get("reason") == "900s 无新关卡完成",
          str(result["detail"]))
    check("面板收工行 = 兜底 reason（逐字）",
          got[-1] == "[进度] 幻想连战 收工：900s 无新关卡完成", got[-1])


# ---------------------------------------------------------------------------
# 6. progress=None 时引擎行为不变（机制输出 / 会话 / 账本逐字节相同）
# ---------------------------------------------------------------------------
class _SilentHook:
    """只记录、不打印的钩子：用来证明「引擎行为与钩子无关」，钩子只是旁路。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, total):
        self.calls.append(("start", total))

    def step(self, index, set_no=0, target_sets=0):
        self.calls.append(("step", index, set_no, target_sets))

    def done(self, reason=""):
        self.calls.append(("done", reason))


def _run_scripted(cfg, ledger_path: Path) -> dict:
    """同一段脚本（只用 core 的公共入口）跑一遍，抓机制输出 / 会话 / 账本。"""
    _reset_session()
    ledger.set_file(ledger_path)
    mech = io.StringIO()
    with contextlib.redirect_stdout(mech):
        core.sync_task(cfg, 6500)
        core.set_target(cfg, {"target_sets": 2})
        for st in range(1, 16):
            core.observe(cfg, "phantom_main", {}, _main_items(st))
            with core.lock(cfg):
                core.session(cfg)["in_fight"] = True
                core.session(cfg)["cur_stage"] = st
                core.session(cfg)["last_state"] = None
                core.session(cfg)["last_observe_ts"] = 0.0
            core.observe(cfg, "phantom_settle", {}, [])
        # 第 2 套第 1 关（换套 note）
        core.observe(cfg, "phantom_main", {}, _main_items(1))
        with core.lock(cfg):
            core.session(cfg)["in_fight"] = True
            core.session(cfg)["cur_stage"] = 1
            core.session(cfg)["last_state"] = None
            core.session(cfg)["last_observe_ts"] = 0.0
        core.observe(cfg, "phantom_settle", {}, [])
        # 收工出口（Done 达标）
        done_cls = core.make_done_reco(cfg, lambda context, image, entry="OcrTask": list(_main_items(1)))
        done_cls().analyze(None, _Argv(6500, {"ocr_entry": "OcrTask", "target_sets": 1}))
    keep = ("cur_set", "cur_stage", "max_done", "completed_sets", "target_sets",
            "session_max_done", "total_marks", "stage_cap", "joined_stage",
            "last_state", "in_fight", "wait_count", "tab_index")
    with core.lock(cfg):
        session = {k: core.session(cfg)[k] for k in keep}
        # ★ADR 0005★ 会话里换成了 LostClock 实例（不再有累计帧数那个键）：对象本身
        #   跨 run 不可比，快照只取诊断量（本次最长连续秒数 / 最后已知页）。
        #   「当前是否仍在 unknown」由 tools/test_lost_clock.py 单独钉住。
        lost = core.session(cfg)["lost"]
        session["lost"] = (lost.worst_seconds, lost.last_known)
    return {
        "mech": mech.getvalue().splitlines(),
        "session": session,
        "ledger": ledger.scope("phantom/set"),
    }


def test_none_is_behaviour_identical() -> None:
    print("\n== 6. progress=None 与「只记录不输出」的钩子：机制/会话/账本逐字节相同 ==")
    with tempfile.TemporaryDirectory() as d:
        none_cfg = dataclasses.replace(ph._CFG, progress=None)
        silent = _SilentHook()
        hook_cfg = dataclasses.replace(ph._CFG, progress=silent)
        with _channels() as (panel, _mech):
            a = _run_scripted(none_cfg, Path(d) / "none.json")
            b = _run_scripted(hook_cfg, Path(d) / "hook.json")
        panel_text = panel.getvalue()

    check("机制输出逐字节相同（None vs 旁路钩子）", a["mech"] == b["mech"],
          f"{len(a['mech'])} vs {len(b['mech'])} 行")
    check("会话快照相同", a["session"] == b["session"], str(a["session"]))
    check("账本 keys 相同", a["ledger"] == b["ledger"], f"{len(a['ledger'])} keys")
    check("★None 时面板零输出★（不启用就一个字节都不写）", panel_text == "", panel_text[:120])
    check("旁路钩子真的被调到（start / step / done 的语义点）",
          [c[0] for c in silent.calls][:2] == ["start", "step"]
          and ("done", "已完成 1 套（目标 1 套）") in silent.calls
          and ("step", 1, 2, 2) in silent.calls,
          str(silent.calls[:4]) + " ... " + str(silent.calls[-2:]))


# ---------------------------------------------------------------------------
# 7. 失败语义：钩子抛异常不许影响跑图
# ---------------------------------------------------------------------------
class _ExplodingHook:
    def start(self, total):
        raise RuntimeError("注入的坏 start")

    def step(self, index, set_no=0, target_sets=0):
        raise RuntimeError("注入的坏 step")

    def done(self, reason=""):
        raise RuntimeError("注入的坏 done")


def test_hook_failure_is_fail_open() -> None:
    print("\n== 7. 钩子抛异常：不冒泡、照常记账、机制日志点名 ==")
    cfg = dataclasses.replace(ph._CFG, progress=_ExplodingHook())
    with tempfile.TemporaryDirectory() as d:
        _reset_session()
        ledger.set_file(Path(d) / "p.json")
        mech = io.StringIO()
        raised = ""
        with contextlib.redirect_stdout(mech):
            try:
                core.sync_task(cfg, 6600)
                with core.lock(cfg):
                    core.session(cfg)["in_fight"] = True
                    core.session(cfg)["cur_stage"] = 1
                    core.session(cfg)["cur_set"] = 1
                core.observe(cfg, "phantom_settle", {}, [])
                # 收工出口也不许冒泡：把「已完成套数」调到目标，让 Done 命中。
                with core.lock(cfg):
                    core.session(cfg)["completed_sets"] = 1
                done_cls = core.make_done_reco(
                    cfg, lambda context, image, entry="OcrTask": list(_main_items(1))
                )
                done_cls().analyze(None, _Argv(6600, {"ocr_entry": "OcrTask", "target_sets": 1}))
            except Exception as exc:  # noqa: BLE001
                raised = repr(exc)
        text = mech.getvalue()
    check("没有异常冒泡", raised == "", raised)
    check("账本照常记账（phantom/set/1/stage/1）", ledger.is_done(ph._stage_key(1, 1)) is True)
    check("机制日志点名 start / step / done 三个失败点",
          "进度钩子 start 失败" in text and "进度钩子 step 失败" in text
          and "进度钩子 done 失败" in text,
          " | ".join(line for line in text.splitlines() if "进度钩子" in line))


# ---------------------------------------------------------------------------
# 8. 格式纪律：不许在场景/引擎里拼第二份进度格式
# ---------------------------------------------------------------------------
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
    """源码里**代码**（非 docstring）出现的 ``[进度]`` 字面量（空 = 守纪律）。"""
    tree = ast.parse(source)
    skip = _docstring_node_ids(tree)
    bad = []
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


def test_format_single_source() -> None:
    print("\n== 8. 格式纪律：代码里没有第二份 [进度] 拼装；引擎不 import reporting ==")
    core_src = (AGENT_DIR / "battle_loop_core.py").read_text(encoding="utf-8")
    ph_src = (AGENT_DIR / "phantom_impl.py").read_text(encoding="utf-8")
    check("battle_loop_core.py 代码里无 [进度] 字面量", _handbuilt_progress_literals(core_src) == [],
          str(_handbuilt_progress_literals(core_src)))
    check("phantom_impl.py 代码里无 [进度] 字面量", _handbuilt_progress_literals(ph_src) == [],
          str(_handbuilt_progress_literals(ph_src)))
    check("★引擎保持场景无关：battle_loop_core 不 import reporting★",
          "import reporting" not in core_src and "reporting." not in core_src)
    check("场景只把钩子挂到 _CFG.progress（并且用 reporting.Progress）",
          "progress=PhantomProgress(" in ph_src and "reporting.Progress(" in ph_src)
    check("手工拼的坏源码会被抓到（判据不是恒绿）",
          _handbuilt_progress_literals("X = '[进度] 幻想连战 1/15 关'\n") != [])


def main() -> int:
    print("=" * 72)
    print("离线单测 #12：幻想连战接入 reporting（第 k/15 关 · 第 j/M 套）")
    print("=" * 72)
    test_wiring()
    test_panel_lines_full_run()
    test_real_stage_number()
    test_cap_done_line()
    test_giveup_done_line()
    test_none_is_behaviour_identical()
    test_hook_failure_is_fail_open()
    test_format_single_source()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅（面板行唯一真源；换套从 1 重新数；None 时行为不变；钩子失败开放）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
