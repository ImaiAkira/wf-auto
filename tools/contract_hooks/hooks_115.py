# -*- coding: utf-8 -*-
"""#115 元守卫：守卫自己的有效性没有守卫 —— 每条 hook 的 prove_red 必须「真跑 + 真能红」。

为什么需要（2026-10-18 复盘：同一个坑（假绿）一晚上栽三次）
--------------------------------------------------------------
1. ``hooks_103`` 用 ``getattr(w, "IN_NEXT", 默认)`` 给真源兜底 -> 真源缺常量也能绿；
2. ``WuchongInSettle`` 是死状态（没有任何业务节点等它），套件却全绿；
3. ``hooks_74`` 的 prove-red 有一条空转：``is_battle_hud`` 恒 False 时守卫 E 仍绿 ——
   断言走的是 ``analyze`` + 会话里残留的 ``in_fight=True``，而 #76 规定战斗 episode 内
   unknown 帧不计 -> 「``unknown_count == 0``」恒成立。

根因不在某条守卫，而在**纪律没人执行**：``tools/run_all_tests.ps1`` 只通过
``discover_hooks()`` import 探针，**每条 hook 的 ``prove_red()`` 是否被执行没有任何断言**，
于是「守卫自己要有破坏实验」这条纪律，在没进套件的 hook 上等于没落地。

本模块把这条纪律补成三道闸
--------------------------
A. **每条 hook 必须带破坏实验**：模块导出 ``prove_red()``，或者在
   :data:`EXEMPT_NO_PROVE_RED` 里写明**为什么不需要**（占位理由如「无需」直接判红）。
B. **每条 prove_red 必须能对一个坏实现返回 False**（不能只看函数存在）：
   * **静态红路证明** :func:`_static_red_path`：prove_red 的返回值必须由它自己造的坏件
     决定（不是恒真），且「破坏点」与「红判据」都在调用图内；
   * 静态证明不了的，先试**动态打瞎判据见证** :func:`_witness_verdict`（把模块的
     ``*failures*`` / ``probe*`` 判据函数打瞎成「永远没有问题」，要求 prove_red 变红）；
   * 两条都证不成的，必须进 :data:`MANUAL_REVIEW`，写明复核方式
     （``method``）与最近一次复核日期（``reviewed``）—— 日期会过期，过期即红。
C. **套件必须真的跑 prove_red**：``run_all_tests.ps1`` 要调用本模块的
   ``--run-prove-red`` 聚合跑器；跑器逐条以子进程执行
   ``python tools/contract_hooks/hooks_XX.py``（= 每个模块文档里写的跑法）并要求退出码 0。
   若哪天脚本改成 ``--only`` 白名单式，白名单必须覆盖全部有 prove_red 的模块。

★本模块自己的破坏实验★（``python tools\\contract_hooks\\hooks_115.py``）
------------------------------------------------------------------------
① 删掉某模块的 ``prove_red`` -> 覆盖闸必须红；
② 把某模块的 ``prove_red`` 改成 ``return True`` -> 静态红路闸必须红；
③ 从套件里摘掉 prove_red 入口 / 用 ``--only`` 白名单漏掉一条 -> 接线闸必须红；
④ 豁免表里理由写占位符（如「无需」）-> 覆盖闸必须红；
⑤ **跑器自检**：一个真绿 + 一个真红的临时钩子，跑器必须分辨（证明「真跑」不是嘴上说的）；
⑥ **打瞎判据见证自检**：有红腿的 prove_red 必须能被打瞎成红，恒真的必须打不红；
⑦ **人工复核校验**：复核方式写占位符 / 复核日期写未来 -> 闸 B 必须红。
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from collections import namedtuple
from datetime import date
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = HOOKS_DIR.parent
REPO_ROOT = TOOLS_DIR.parent
SUITE_ENTRY = TOOLS_DIR / "run_all_tests.ps1"

# ★必须先修 sys.path 再 import 包★：本模块既会被 ``discover_hooks()`` 当挂点文件加载，
# 也会被跑器当**脚本**直接执行（``python tools\\contract_hooks\\hooks_115.py``）——
# 后者 ``sys.path[0]`` 是 contract_hooks 目录，``import contract_hooks`` 会失败。
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from contract_hooks import _load_module, discover_hooks, iter_hook_files  # noqa: E402

# ---------------------------------------------------------------------------
# 豁免表：**没有** prove_red 的挂点模块 -> 为什么不需要自己的破坏实验
# ---------------------------------------------------------------------------
#: ``kind`` 三种（都必须机器可查，不许一句话免责）：
#:   * ``no-need``    —— 该守卫本身每次运行都自带「现场实验」，或断言无法被改坏；
#:   * ``delegated``  —— 破坏实验在别处，且**由本套件执行**（``executor`` 必须出现在
#:                       :data:`EXTRA_PROVE_RED_ENTRIES` 里，跑器会真的跑它）；
#:   * ``manual``     —— 破坏实验在别处，但**套件不跑**（成本太高），必须给
#:                       ``method``（怎么跑）+ ``reviewed``（最近一次真的跑过的日期）。
#:
#: 任何一条理由都必须实质（见 :func:`_reason_problem`）：太短 / 占位词 / 缺机器可查的
#: 依据，一律判红。
EXEMPT_NO_PROVE_RED: dict[str, dict[str, str]] = {
    "hooks_2": {
        "kind": "manual",
        "why": (
            "入口契约（entry-offline-signal）的破坏实验是**中央配方**：复制 "
            "tools/test_offline_contract.py::_prove_red 那份，删掉强制 UTF-8 的那行，要求本探针"
            "变红。配方只留一份（避免两份漂移），本模块不再自带 prove_red。"
        ),
        "method": (
            "python tools/test_offline_contract.py --prove-red"
            "（整套复制入口 + 两次全量契约，约 170s）"
        ),
        "reviewed": "2026-10-18",
    },
    "hooks_3": {
        "kind": "manual",
        "why": (
            "scene 配置面三条守卫的破坏实验是**中央配方** "
            "tools/test_offline_contract.py::_prove_red_scene：复制整包 scene，逐一改坏"
            "（跳过重复成员 / 跳过空难度集 / 覆盖报告吞掉 / 抄第二份页面规则），要求三条守卫各自变红。"
        ),
        "method": (
            "python tools/test_offline_contract.py --prove-red"
            "（复制 scene 包 + 子进程重跑探针，约 170s）"
        ),
        "reviewed": "2026-10-18",
    },
    "hooks_4": {
        "kind": "delegated",
        "why": (
            "链式拓扑守卫的破坏实验在 tools/test_scene_chain.py 的 --prove-red 模式里"
            "（复制 scene 包、逐一改坏链实现）。套件通过本模块的跑器执行该入口。"
        ),
        "executor": "tools/test_scene_chain.py --prove-red",
    },
    "hooks_9": {
        "kind": "delegated",
        "why": (
            "「三条既有路径 + agent 判定不变」的破坏实验在 tools/test_scene_unchanged.py 的"
            " --prove-red 模式里（逐一改坏真实产物副本）。套件通过本模块的跑器执行该入口。"
        ),
        "executor": "tools/test_scene_unchanged.py --prove-red",
    },
    "hooks_15": {
        "kind": "no-need",
        "why": (
            "归一性守卫本身就是**每次运行都做的现场实验**：probe_no_collision 真的新建一个"
            " hooks_*.py 再重新发现它。把聚合器改成手写清单会让这条断言变红，同时 "
            "tools/test_offline_contract.py::_disk_alignment_error（聚合结果 vs 独立扫盘）也会红 ——"
            " 破坏实验已经内建在守卫里，不需要另造一份。"
        ),
    },
    "hooks_23": {
        "kind": "delegated",
        "why": (
            "「规律循环不算卡死」的破坏实验在 tools/test_stall_detector.py 的 --prove-red 模式里"
            "（退回旧判据，要求用例变红）。套件通过本模块的跑器执行该入口。"
        ),
        "executor": "tools/test_stall_detector.py --prove-red",
    },
}

#: 跑器在「逐文件跑 prove_red」之外，额外执行的等价破坏入口（``delegated`` 的落点）。
#: 每一项都会被跑器真的执行（``--prove-red`` 参数），失败即整套红。
EXTRA_PROVE_RED_ENTRIES: tuple[tuple[str, str], ...] = (
    ("tools/test_scene_chain.py", "--prove-red"),
    ("tools/test_scene_unchanged.py", "--prove-red"),
    ("tools/test_stall_detector.py", "--prove-red"),
)

#: 人工复核清单：有 prove_red 但静态红路 + 动态见证都证不成的模块。
#: 每项必须 ``method``（怎么复核）+ ``reviewed``（最近一次复核日期，ISO）。
MANUAL_REVIEW: dict[str, dict[str, str]] = {}

#: 人工复核记录的保鲜期（天）：过期即红，避免「写了日期就永久免检」。
MAX_REVIEW_AGE_DAYS = 400

#: 跑器的命令行入口（``run_all_tests.ps1`` 必须调用这一行）。
RUNNER_FLAG = "--run-prove-red"
#: 跑器的白名单开关（只给本地调试；套件里必须不带，或带了就得覆盖全集）。
ONLY_FLAG = "--only"

_TICKET = "#115"

# ---------------------------------------------------------------------------
# 扫描：每个 hooks_*.py = 一张票
# ---------------------------------------------------------------------------


#: 一个挂点文件（一张票）的静态视图。
#: ★不用 @dataclass★：本模块会被 ``contract_hooks._load_module`` 以**不写 sys.modules**
#: 的方式加载，dataclass 解析 ``cls.__module__`` 时会炸（NoneType.__dict__）。
_Slot = namedtuple("_Slot", ("stem", "path", "source", "hook_ids"))


_MODULES: list[_Slot] | None = None
_DISCOVERED: list[str] | None = None


def _modules() -> list[_Slot]:
    """加载全部 ``hooks_*.py``（不缓存**文件集合**语义 —— 每次进程内只算一次，够快）。"""
    global _MODULES
    if _MODULES is not None:
        return _MODULES
    slots = []
    for path in iter_hook_files():
        source = path.read_text(encoding="utf-8-sig")
        module = _load_module(path)
        raw = getattr(module, "HOOKS", None)
        if raw is None:
            raise AttributeError(f"挂点模块缺少 HOOKS：{path.name}")
        slots.append(_Slot(path.stem, path, source, tuple(h[0] for h in raw)))
    _MODULES = slots
    return slots


def _discovered_ids() -> list[str]:
    """``discover_hooks()`` 收进来的 hook_id（= 套件真正会跑的挂点）。"""
    global _DISCOVERED
    if _DISCOVERED is None:
        _DISCOVERED = [h[0] for h in discover_hooks()]
    return _DISCOVERED


def _has_prove_red(source: str) -> bool:
    """源码里是否定义了顶层 ``prove_red()``（扫描按模块名，不看有没有被调用）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name == "prove_red" for n in tree.body)


# ---------------------------------------------------------------------------
# 闸 A/B：证明「prove_red 能对一个坏实现返回 False」
# ---------------------------------------------------------------------------
#: 能说明「prove_red 真的造了一个坏件」的调用/赋值痕迹（宁可宽松：这条只用来排除
#: 「一个坏件都不造、纯靠读真源就 return True」的假破坏实验）。
_MUTATION_HINTS = (
    "patch",
    "Broken",
    "broken",
    "poison",
    "stale",
    "_mut",
    "copy",
    "copytree",
    "mkdtemp",
    "tempfile",
    "subprocess",
    "write_text",
    "write_bytes",
    "_break",
    "break_",
    "replace",
    "prove_red",
    "reversed",
    "shuffle",
    "stripped",
    "mutated",
)

#: 本地变量名里带这些词 = 装的是一个**坏件**（钩子们的惯例：broken / poisoned / stale /
#: without / stripped …）。只认赋值目标名，不碰别的语义，避免误判。
_BAD_NAME_HINTS = (
    "broken",
    "poison",
    "stale",
    "mutat",
    "without",
    "reversed",
    "shuffled",
    "stripped",
    "fake",
    "bad",
)

_PLACEHOLDER_WORDS = re.compile(
    r"^\s*(无需|不需要|没有必要|不需要了|无|略|同上|见上|暂无|待补|todo|tbd|n/?a|none|nothing)\s*[。.]?\s*$",
    re.IGNORECASE,
)
_MIN_REASON_CHARS = 12
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_truthy_const(node) -> bool:
    """``True`` / 非零数字 / 非空字符串 这类「恒成功」常量。"""
    return isinstance(node, ast.Constant) and bool(node.value) and node.value is not None


def _top_functions(tree) -> dict:
    return {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_names(fn) -> set:
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _static_red_path(source: str) -> tuple[bool, str]:
    """静态红路证明：``prove_red`` 的返回值必须由**它自己造的坏件**决定，不能恒真。

    判定（三条同时成立才算证明）：
    1. **不是恒成功**：所有 ``return`` 不能全是 ``True`` / 非零常量（``return True`` 当场红）；
    2. **有红判据**：调用图（prove_red + 它在本模块内调到的函数，展开两层）里存在
       比较 / 布尔运算 / ``not``，或者直接委托给另一个模块的 ``prove_red``；
    3. **有破坏点**：调用图里存在「改属性 / 改下标 / 造坏件」的痕迹
       （monkeypatch、临时副本、写盘、PYTHONPATH 子进程…）。

    这是**结构证明**，不是行为证明：它排除「恒真 / 没有红路 / 根本不动实现」三类假绿；
    逐条断言是否空转，靠 :func:`_witness_verdict` 与 :data:`MANUAL_REVIEW` 兜底。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"源码无法解析：{exc}"
    funcs = _top_functions(tree)
    fn = funcs.get("prove_red")
    if fn is None:
        return False, "模块里没有顶层 prove_red()"

    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    if not returns:
        return False, "prove_red 没有 return（无法返回 False）"
    if all(r.value is not None and _is_truthy_const(r.value) for r in returns):
        return False, "prove_red 的 return 全是恒真常量（恒绿 = 假破坏实验）"

    bodies = [fn]
    frontier = _called_names(fn)
    delegated = "prove_red" in frontier
    for _ in range(2):
        nxt = set()
        for name in frontier:
            sub = funcs.get(name)
            if sub is not None and sub not in bodies:
                bodies.append(sub)
                nxt |= _called_names(sub)
        frontier = nxt
        if "prove_red" in frontier:
            delegated = True

    mutations = 0
    verdicts = 0
    calls = 0
    for body in bodies:
        for node in ast.walk(body):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, (ast.Attribute, ast.Subscript)):
                        mutations += 1
                    elif isinstance(target, ast.Name) and any(
                        hint in target.id.lower() for hint in _BAD_NAME_HINTS
                    ):
                        # 本地变量装的坏件也算：hooks_28 的 `broken = [(...lambda...), *rules()]`、
                        # hooks_24 的 `stripped = "def ensure_main_city(...)"`。
                        mutations += 1
            elif isinstance(node, ast.Call):
                calls += 1
                text = ast.unparse(node.func)
                if any(hint in text for hint in _MUTATION_HINTS):
                    mutations += 1
                # 「合成坏源码」也算破坏点：把一段坏实现当字符串喂给判据
                # （hooks_24/hooks_28 的 prove_red 就是这么造坏件的）。
                if any(
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and "def " in arg.value
                    for arg in list(node.args) + [kw.value for kw in node.keywords]
                ):
                    mutations += 1
            elif isinstance(node, (ast.Compare, ast.BoolOp)):
                verdicts += 1
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                verdicts += 1

    if calls == 0:
        return False, "prove_red 什么也不调用（不可能真的去试坏实现）"
    if verdicts == 0 and not delegated:
        return False, "prove_red 没有红判据（比较 / 布尔 / not，也没有委托别的 prove_red）"
    if mutations == 0:
        return False, "prove_red 没有任何破坏点（不改属性、不造坏件、不写副本）"
    note = "（委托）" if delegated and verdicts == 0 else ""
    return True, f"红路可达{note}：mutations={mutations} verdicts={verdicts} calls={calls}"


#: 动态见证代码：把模块自己的「判据函数」打瞎（``*failures*`` -> 永远没有落空；
#: ``probe*`` -> 永远通过），再跑 ``prove_red()``。
#: 见证成立 = **打瞎后 prove_red 变红** —— 说明它的结论真的流经那些判据，
#: 因此它「能对一个坏实现（判据失效的守卫）返回 False」；恒真函数打不红。
_WITNESS_CODE = r'''
import importlib.util
import sys
import types

path = sys.argv[1]
sys.path.insert(0, str(__import__("pathlib").Path(path).parent))
spec = importlib.util.spec_from_file_location("_witness_mod", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

blinded = 0
for name, obj in list(vars(mod).items()):
    if name == "prove_red" or not isinstance(obj, types.FunctionType):
        continue
    if getattr(obj, "__module__", None) != mod.__name__:
        continue
    low = name.lower()
    if "failure" in low:
        setattr(mod, name, lambda *a, **k: [])
        blinded += 1
    elif low.startswith("probe") or "check" in low:
        setattr(mod, name, lambda *a, **k: True)
        blinded += 1

if blinded == 0:
    print("WITNESS none")
    sys.exit(2)
try:
    got = mod.prove_red()
except Exception as exc:  # noqa: BLE001 -- 打瞎后炸掉 = 没法见证，不算成立
    print("WITNESS raise " + repr(exc))
    sys.exit(3)
ok = (got is True) or (not isinstance(got, bool) and got == 0)
print("WITNESS green" if ok else "WITNESS red")
sys.exit(1 if ok else 0)
'''


def _witness_verdict(path: Path, timeout: int = 300) -> str:
    """动态打瞎判据见证。

    返回 ``"red"``（见证成立）/ ``"green"``（打瞎后仍绿 = 不能证明能红）/ ``"none"``
    （找不到可打瞎的判据）/ ``"raise:..."``（打瞎后炸了，无法据此下结论）。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _WITNESS_CODE, str(path)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"raise:{exc!r}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    match = re.search(r"WITNESS (red|green|none|raise.*)", out)
    if not match:
        return f"raise:no-marker:{out[-120:]!r}"
    return match.group(1).strip()


def _reason_problem(label: str, text, *, method: bool = False) -> str | None:
    """理由/复核方式是否「实质」：太短或占位词一律不成立。"""
    value = str(text or "").strip()
    if not value:
        return f"{label} 缺失（必须写明依据，不许留空）"
    if _PLACEHOLDER_WORDS.match(value):
        return f"{label} 是占位符（{value!r}）—— 必须写明真正的依据"
    if len(value) < _MIN_REASON_CHARS:
        return f"{label} 太短（{value!r}）—— 至少 {_MIN_REASON_CHARS} 字说明凭什么"
    if method and not re.search(r"(python|powershell|run_all_tests|--prove-red|hooks_\d+|\.ps1|\.py)", value):
        return f"{label} 没有可执行的复核命令（{value!r}）"
    return None


def _reviewed_problem(label: str, text) -> str | None:
    value = str(text or "").strip()
    if not _ISO_DATE.match(value):
        return f"{label} 不是 ISO 日期（{value!r}）—— 必须写最近一次复核日期 YYYY-MM-DD"
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return f"{label} 不是合法日期（{value!r}）"
    today = date.today()
    if parsed > today:
        return f"{label} 在未来（{value}）—— 复核日期必须是真跑过的日子"
    age = (today - parsed).days
    if age > MAX_REVIEW_AGE_DAYS:
        return f"{label} 已过期（{value}，{age} 天前 > {MAX_REVIEW_AGE_DAYS} 天）—— 请重跑并更新日期"
    return None


def _exempt_problem(stem: str, entry) -> str | None:
    """豁免项是否站得住（理由实质 + kind 对应的机器可查依据）。"""
    if not isinstance(entry, dict):
        return f"{stem}: 豁免项必须是 dict（kind/why/...），不是 {type(entry).__name__}"
    kind = str(entry.get("kind") or "").strip()
    if kind not in ("no-need", "delegated", "manual"):
        return f"{stem}: 豁免 kind={kind!r} 非法（只能是 no-need / delegated / manual）"
    problem = _reason_problem(f"{stem}: 豁免理由", entry.get("why"))
    if problem:
        return problem
    if kind == "delegated":
        executor = str(entry.get("executor") or "").strip()
        known = {f"{script} {flag}" for script, flag in EXTRA_PROVE_RED_ENTRIES}
        if executor not in known:
            return (
                f"{stem}: delegated 的 executor={executor!r} 不在 EXTRA_PROVE_RED_ENTRIES 里"
                " —— 说『由套件执行』就必须真的排进跑器"
            )
    if kind == "manual":
        problem = _reason_problem(f"{stem}: 复核方式", entry.get("method"), method=True)
        if problem:
            return problem
        return _reviewed_problem(f"{stem}: 复核日期", entry.get("reviewed"))
    return None


def _manual_problem(stem: str, entry) -> str | None:
    if not isinstance(entry, dict):
        return f"{stem}: 人工复核项必须是 dict（method/reviewed/why）"
    problem = _reason_problem(f"{stem}: 人工复核方式", entry.get("method"), method=True)
    if problem:
        return problem
    return _reviewed_problem(f"{stem}: 人工复核日期", entry.get("reviewed"))


def _gate_a_failures(
    slots: list[_Slot],
    discovered_ids: list[str],
    exempt: dict,
    manual: dict | None = None,
) -> list[str]:
    """闸 A：每条被 ``discover_hooks()`` 收进来的 hook 要么有 prove_red，要么有实质豁免。"""
    problems: list[str] = []
    manual = manual if manual is not None else MANUAL_REVIEW
    by_stem = {slot.stem: slot for slot in slots}
    discovered = list(discovered_ids)

    for slot in slots:
        if _has_prove_red(slot.source):
            continue
        entry = exempt.get(slot.stem)
        if entry is None:
            problems.append(
                f"{slot.stem}: 既没有 prove_red()，也不在豁免表里"
                " —— 它凭什么证明自己抓得住坏实现？"
            )
            continue
        problem = _exempt_problem(slot.stem, entry)
        if problem:
            problems.append(problem)

    for stem in sorted(set(exempt) - set(by_stem)):
        problems.append(f"豁免表里的 {stem} 不存在（陈旧条目请删掉）")
    for stem in sorted(set(manual) - set(by_stem)):
        problems.append(f"人工复核清单里的 {stem} 不存在（陈旧条目请删掉）")

    # 聚合器必须真的把这些挂点收进来（否则元守卫看不到的票永远漏检）
    known_ids = {hid for slot in slots for hid in slot.hook_ids}
    for hid in discovered:
        if hid not in known_ids:
            problems.append(f"discover_hooks() 收到的 {hid} 不属于任何 hooks_*.py（聚合器与磁盘不一致）")
    discovered_set = set(discovered)
    for slot in slots:
        for hid in slot.hook_ids:
            if hid not in discovered_set:
                problems.append(f"{slot.stem} 的挂点 {hid} 没被 discover_hooks() 收进来（漏票）")
    return problems


def _gate_b_failures(slots: list[_Slot], manual: dict | None = None) -> list[str]:
    """闸 B：每条 prove_red 必须能证明「对一个坏实现返回 False」（静态 / 动态 / 人工复核）。"""
    problems: list[str] = []
    manual = manual if manual is not None else MANUAL_REVIEW
    by_stem = {slot.stem: slot for slot in slots}
    for slot in slots:
        if not _has_prove_red(slot.source):
            continue
        ok, detail = _static_red_path(slot.source)
        if ok:
            continue
        entry = manual.get(slot.stem)
        if entry is not None:
            problem = _manual_problem(slot.stem, entry)
            if problem:
                problems.append(problem)
            continue
        on_disk = slot.path.read_text(encoding="utf-8-sig")
        if on_disk != slot.source:
            # 内存里的源码与磁盘不一致（破坏实验的输入）—— 动态见证只能见证磁盘上的实现，
            # 不能拿它给另一份源码背书。
            problems.append(
                f"{slot.stem}: 静态红路证明不成立（{detail}），且源码与磁盘不一致（无法做动态见证）"
                " —— 必须补静态红路或进 MANUAL_REVIEW"
            )
            continue
        witness = _witness_verdict(slot.path)
        if witness == "red":
            continue  # 动态见证成立：打瞎判据后 prove_red 真的变红
        problems.append(
            f"{slot.stem}: 静态红路证明不成立（{detail}），动态见证也不成立（{witness}）"
            " —— 必须进 MANUAL_REVIEW 写明复核方式与最近一次复核日期"
        )
    for stem in sorted(manual):
        slot = by_stem.get(stem)
        if slot is not None and not _has_prove_red(slot.source):
            problems.append(f"{stem}: 有 prove_red 才能登记人工复核（本模块没有）")
    return problems


def _coverage_failures(
    slots: list[_Slot],
    discovered_ids: list[str],
    exempt: dict,
    manual: dict | None = None,
) -> list[str]:
    """闸 A + 闸 B 的合并判据（prove_red 的绿腿用一次拿全部问题）。"""
    return _gate_a_failures(slots, discovered_ids, exempt, manual) + _gate_b_failures(slots, manual)


# ---------------------------------------------------------------------------
# 闸 C：套件真的跑 prove_red
# ---------------------------------------------------------------------------


def _prove_red_stems() -> set[str]:
    """有 prove_red 的模块名（跑器默认全跑这个集合）。"""
    return {path.stem for path in iter_hook_files() if _has_prove_red(path.read_text(encoding="utf-8-sig"))}


def _runner_invocations(script_text: str) -> list[str]:
    """``run_all_tests.ps1`` 里真正**调用**跑器的那几行（注释不算）。"""
    lines = []
    for line in script_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "hooks_115.py" in stripped and RUNNER_FLAG in stripped and "&" in stripped:
            lines.append(stripped)
    return lines


_ONLY_RE = re.compile(r"--only\s+([^\s|&]+)")


def _suite_wiring_failures(script_text: str, stems: set[str]) -> list[str]:
    """闸 C：读 ``run_all_tests.ps1`` 的源码，断言 prove_red 真的被跑了、且没被白名单偷偷缩水。"""
    problems: list[str] = []
    invocations = _runner_invocations(script_text)
    if not invocations:
        problems.append(
            "run_all_tests.ps1 没有执行 hooks_115 的 prove_red 聚合跑器（--run-prove-red）"
            " —— 每条 hook 的 prove_red 又回到「没人跑」的状态"
        )
    for line in invocations:
        match = _ONLY_RE.search(line)
        if not match:
            continue
        only = {name for name in re.split(r"[,;\s]+", match.group(1)) if name}
        missing = sorted(stems - only)
        if missing:
            problems.append(
                f"套件的 prove_red 白名单（--only）漏了 {len(missing)} 条 hook："
                + ", ".join(missing[:8])
                + ("…" if len(missing) > 8 else "")
            )
    if "(test_|verify_)" not in script_text:
        problems.append(
            "run_all_tests.ps1 不再按 test_/verify_ 扫目录 —— 契约入口（test_offline_contract.py）"
            " 可能整个不跑，本守卫也就无从执行"
        )
    return problems


# ---------------------------------------------------------------------------
# 跑器：逐文件以子进程执行 prove_red（``python tools\\contract_hooks\\hooks_XX.py``）
# ---------------------------------------------------------------------------


def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_script(path: Path, extra_args: tuple[str, ...] = (), timeout: int = 600) -> tuple[bool, str]:
    """跑一个脚本，``returncode == 0`` 才算过；返回 (ok, 输出尾巴)。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(path), *extra_args],
            cwd=str(REPO_ROOT),
            env=_child_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"[timeout] {path.name} 超过 {timeout}s"
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = "\n".join(text.splitlines()[-12:])
    return proc.returncode == 0, tail


def run_prove_red_all(only: set[str] | None = None, verbose: bool = False) -> int:
    """真的跑每条 hook 的 prove_red：逐个以脚本方式执行，退出码非 0 即整套红。

    ★为什么用子进程 + 脚本方式★：
      * 每个模块的 prove_red 都会 monkeypatch 全局（``impl.is_battle_hud`` / 账本文件…），
        进程内连跑会互相污染 —— 假绿/假红都可能；
      * 部分模块（如 hooks_80）在自己的 prove_red 里 ``import hooks_XX`` 自引用，
        只有按**脚本**（文档里写的跑法）执行才对。
    """
    import time

    stems = _prove_red_stems()
    selected = sorted(stems & only) if only else sorted(stems)
    if only:
        skipped = sorted(stems - only)
        print(f"[hooks_115] --only 只跑 {len(selected)} 条；其余 {len(skipped)} 条被跳过（仅调试用）")
    failures: list[str] = []
    started = time.monotonic()
    for stem in selected:
        path = HOOKS_DIR / f"{stem}.py"
        t0 = time.monotonic()
        ok, tail = _run_script(path)
        dt = time.monotonic() - t0
        print(f"  [{'OK  ' if ok else 'FAIL'}] {stem}  ({dt:.1f}s)")
        if not ok:
            failures.append(stem)
            for line in tail.splitlines():
                print(f"         {line}")
        elif verbose and tail:
            # --verbose：连绿的那条也把模块自己的结论行贴出来（核对它真的跑了红腿）。
            print(f"         {tail.splitlines()[-1]}")
    for script, flag in EXTRA_PROVE_RED_ENTRIES:
        target = REPO_ROOT / script
        if not target.is_file():
            failures.append(f"{script}{flag}")
            print(f"  [FAIL] {script} {flag}  (文件不存在)")
            continue
        t0 = time.monotonic()
        ok, tail = _run_script(target, (flag,))
        dt = time.monotonic() - t0
        print(f"  [{'OK  ' if ok else 'FAIL'}] {script} {flag}  ({dt:.1f}s)")
        if not ok:
            failures.append(f"{script}{flag}")
            for line in tail.splitlines():
                print(f"         {line}")
    elapsed = time.monotonic() - started
    print(
        f"[hooks_115] prove_red：{len(selected)} 个挂点模块 + "
        f"{len(EXTRA_PROVE_RED_ENTRIES)} 个等价入口，用时 {elapsed:.1f}s，失败 {len(failures)}"
    )
    if failures:
        print("[hooks_115] 失败：" + ", ".join(failures))
        return 1
    print("[hooks_115] 全部 prove_red 成立（绿于真实实现、红于各自造的坏实现）")
    return 0


# ---------------------------------------------------------------------------
# 三个挂点（元守卫本体）
# ---------------------------------------------------------------------------


def probe_meta_every_hook_has_prove_red() -> bool:
    """每条被 ``discover_hooks()`` 收进来的 hook：要么有 prove_red，要么有实质豁免。"""
    slots = _modules()
    problems = _gate_a_failures(slots, _discovered_ids(), EXEMPT_NO_PROVE_RED)
    if problems:
        print("  [115] 闸 A 不成立：")
        for problem in problems:
            print(f"    - {problem}")
        return False
    with_pr = [s for s in slots if _has_prove_red(s.source)]
    exempted = len({s.stem for s in slots} - {s.stem for s in with_pr})
    print(
        f"  [115] 闸 A 成立：{len(with_pr)}/{len(slots)} 个挂点文件自带 prove_red，"
        f"{exempted} 个有实质豁免"
    )
    return True


def probe_meta_prove_red_can_go_red() -> bool:
    """每条 prove_red 都能证明「对一个坏实现返回 False」（静态红路 / 动态见证 / 人工复核）。"""
    slots = _modules()
    problems = _gate_b_failures(slots, MANUAL_REVIEW)
    if problems:
        print("  [115] 闸 B 不成立：")
        for problem in problems:
            print(f"    - {problem}")
        return False
    with_pr = [s for s in slots if _has_prove_red(s.source)]
    print(
        f"  [115] 闸 B 成立：{len(with_pr)} 条 prove_red 都能给出「返回 False」的证据"
        f"（静态红路 {len(with_pr) - len(MANUAL_REVIEW)} 条 / 人工复核 {len(MANUAL_REVIEW)} 条）"
    )
    return True


def probe_meta_suite_runs_prove_red() -> bool:
    """``run_all_tests.ps1`` 真的跑 prove_red，且没被 `--only` 白名单偷偷缩水。"""
    if not SUITE_ENTRY.is_file():
        print(f"  [115] 找不到套件入口：{SUITE_ENTRY}")
        return False
    script_text = SUITE_ENTRY.read_text(encoding="utf-8-sig", errors="replace")
    stems = _prove_red_stems()
    problems = _suite_wiring_failures(script_text, stems)
    if problems:
        print("  [115] 闸 C 不成立：")
        for problem in problems:
            print(f"    - {problem}")
        return False
    print(f"  [115] 闸 C 成立：run_all_tests.ps1 调用 --run-prove-red，覆盖 {len(stems)} 条 hook")
    return True


HOOKS = [
    (
        "meta-every-hook-has-prove-red",
        _TICKET,
        "元守卫（闸 A）：每条被 discover_hooks() 收进来的 hook 要么带 prove_red()，要么在豁免表里"
        "写明为什么不需要破坏实验（占位理由如「无需」直接红）",
        probe_meta_every_hook_has_prove_red,
    ),
    (
        "meta-prove-red-can-go-red",
        _TICKET,
        "元守卫（闸 B）：每条 prove_red 必须能证明「对一个坏实现返回 False」——静态红路证明"
        "（恒真/无红判据/无破坏点 => 红）或动态打瞎判据见证；都不成立的必须进人工复核清单"
        "（含复核方式 + 最近一次复核日期，过期即红）",
        probe_meta_prove_red_can_go_red,
    ),
    (
        "meta-suite-runs-prove-red",
        _TICKET,
        "元守卫（闸 C）：run_all_tests.ps1 真的执行 hooks_115 --run-prove-red；若用 --only 白名单，"
        "必须覆盖全部有 prove_red 的模块（读脚本源码断言，不靠人记得）",
        probe_meta_suite_runs_prove_red,
    ),
]


# ---------------------------------------------------------------------------
# 本模块自己的破坏实验
# ---------------------------------------------------------------------------
def _strip_top_function(source: str, name: str) -> str:
    """删掉源码里的顶层函数（破坏实验用：模拟「某 tick 的 prove_red 被删」）。"""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = source.splitlines(keepends=True)
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            return "".join(lines[:start] + lines[node.end_lineno:])
    return source


def _narrow_runner_line(script_text: str) -> str:
    """把跑器调用行改成 ``--only hooks_74``（破坏实验用：白名单漏掉绝大多数 hook）。"""
    lines = []
    for line in script_text.splitlines(keepends=True):
        stripped = line.strip()
        if (
            not stripped.startswith("#")
            and "hooks_115.py" in stripped
            and RUNNER_FLAG in stripped
            and "&" in stripped
            and ONLY_FLAG not in stripped
        ):
            line = line.replace(RUNNER_FLAG, f"{RUNNER_FLAG} {ONLY_FLAG} hooks_74", 1)
        lines.append(line)
    return "".join(lines)


def _self_test_script(body: str) -> Path:
    """写一个临时钩子脚本（跑器自检用），由调用方负责目录生命周期。"""
    directory = Path(tempfile.mkdtemp(prefix="wf_hook115_"))
    path = directory / "hooks_9000.py"
    path.write_text(body, encoding="utf-8")
    return path


def prove_red() -> bool:
    _ = sys.path.insert(0, str(TOOLS_DIR))
    print("hooks_115 prove-red：逐一破坏元守卫的输入，要求它变红")
    slots = _modules()
    discovered = _discovered_ids()
    stems_with_pr = {s.stem for s in slots if _has_prove_red(s.source)}
    script_text = SUITE_ENTRY.read_text(encoding="utf-8-sig") if SUITE_ENTRY.is_file() else ""
    checks: list[bool] = []

    # 绿腿：真实仓库上三条闸都成立（不成立就没必要往下做破坏实验了）。
    coverage = _coverage_failures(slots, discovered, EXEMPT_NO_PROVE_RED)
    wiring = _suite_wiring_failures(script_text, stems_with_pr)
    green = not coverage and not wiring
    print(f"  [{'PASS' if green else 'FAIL'}] 真实仓库：三道闸全绿")
    if not green:
        for problem in (coverage + wiring)[:8]:
            print(f"      - {problem}")
        return False

    # ① 删掉某模块的 prove_red -> 覆盖闸必须红。
    victim = "hooks_74" if "hooks_74" in stems_with_pr else sorted(stems_with_pr)[0]
    mutated = [
        s._replace(source=_strip_top_function(s.source, "prove_red")) if s.stem == victim else s
        for s in slots
    ]
    problems = _coverage_failures(mutated, discovered, EXEMPT_NO_PROVE_RED)
    red_1 = any(victim in p and "prove_red" in p for p in problems)
    print(f"  [{'PASS' if red_1 else 'FAIL'}] 删掉 {victim}.prove_red -> "
          f"{'红' if red_1 else '仍绿'}")
    checks.append(red_1)

    # ② 把某模块的 prove_red 改成 return True -> 静态红路闸必须红。
    const_source = _strip_top_function(
        next(s.source for s in slots if s.stem == victim), "prove_red"
    ) + "\n\ndef prove_red():\n    return True\n"
    mutated = [s._replace(source=const_source) if s.stem == victim else s for s in slots]
    problems = _coverage_failures(mutated, discovered, EXEMPT_NO_PROVE_RED)
    const_ok, const_detail = _static_red_path(const_source)
    red_2 = (not const_ok) and any(victim in p and "静态红路" in p for p in problems)
    print(f"  [{'PASS' if red_2 else 'FAIL'}] {victim}.prove_red 改成 return True -> "
          f"{'红' if red_2 else '仍绿'}（静态结论：{const_detail}）")
    checks.append(red_2)

    # ③ 从套件里摘掉 prove_red 入口 / 白名单漏一条 -> 接线闸必须红。
    no_entry = "\n".join(
        line for line in script_text.splitlines()
        if not (line.strip().startswith("&") and "hooks_115.py" in line and RUNNER_FLAG in line)
    )
    problems = _suite_wiring_failures(no_entry, stems_with_pr)
    red_3a = any("没有执行" in p for p in problems)
    problems = _suite_wiring_failures(_narrow_runner_line(script_text), stems_with_pr)
    red_3b = any("白名单" in p for p in problems)
    red_3 = red_3a and red_3b
    print(f"  [{'PASS' if red_3 else 'FAIL'}] 套件摘掉 prove_red 入口 -> {'红' if red_3a else '仍绿'}；"
          f"白名单 --only hooks_74 -> {'红' if red_3b else '仍绿'}")
    checks.append(red_3)

    # ④ 豁免表里理由写占位符（「无需」）-> 覆盖闸必须红。
    fake_exempt = {k: dict(v) for k, v in EXEMPT_NO_PROVE_RED.items()}
    victim_exempt = next((stem for stem in fake_exempt if stem in {s.stem for s in slots}), None)
    if victim_exempt is None:
        victim_exempt = "hooks_2"
        fake_exempt[victim_exempt] = {"kind": "no-need", "why": "占位"}
    fake_exempt[victim_exempt] = dict(fake_exempt[victim_exempt], why="无需")
    problems = _coverage_failures(slots, discovered, fake_exempt)
    red_4 = any(victim_exempt in p and ("占位" in p or "太短" in p) for p in problems)
    print(f"  [{'PASS' if red_4 else 'FAIL'}] 豁免理由写成占位符「无需」（{victim_exempt}）-> "
          f"{'红' if red_4 else '仍绿'}")
    checks.append(red_4)

    # ⑤ 跑器自检：一个真绿 + 一个真红，跑器必须分辨（证明「跑器」真的执行 + 读退出码）。
    tmpdirs: list[Path] = []
    try:
        good = _self_test_script(
            "def prove_red():\n    return True\n\n\n"
            "if __name__ == '__main__':\n    raise SystemExit(0)\n"
        )
        bad = good.parent / "hooks_9001.py"
        bad.write_text(
            "def prove_red():\n    return False\n\n\n"
            "if __name__ == '__main__':\n    raise SystemExit(1)\n",
            encoding="utf-8",
        )
        tmpdirs += [good.parent]
        good_ok, _ = _run_script(good)
        bad_ok, _ = _run_script(bad)
        red_5 = good_ok and not bad_ok
        print(f"  [{'PASS' if red_5 else 'FAIL'}] 跑器自检：真绿={'过' if good_ok else '误判红'}，"
              f"真红={'误判绿' if bad_ok else '被抓到'}")
        checks.append(red_5)
    finally:
        import shutil

        for directory in tmpdirs:
            shutil.rmtree(directory, ignore_errors=True)

    # ⑥ 打瞎判据见证自检：有红腿的 prove_red 必须能被打瞎成红；恒真的必须打不红。
    witness_src = '''# -*- coding: utf-8 -*-
def _failures(items):
    return list(items)


def _broken_failures():
    return ["坏实现没被抓到"]


def prove_red():
    green = not _failures([])
    red = len(_broken_failures()) > 0
    print("green", green, "red", red)
    return bool(green and red)


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
'''
    constant_src = '''# -*- coding: utf-8 -*-
def _failures(items):
    return list(items)


def prove_red():
    return True


if __name__ == "__main__":
    raise SystemExit(0)
'''
    directories: list[Path] = []
    try:
        with_leg = _self_test_script(witness_src)
        directories.append(with_leg.parent)
        constant = with_leg.parent / "hooks_9002.py"
        constant.write_text(constant_src, encoding="utf-8")
        verdict_red = _witness_verdict(with_leg)
        verdict_const = _witness_verdict(constant)
        red_6 = verdict_red == "red" and verdict_const != "red"
        print(f"  [{'PASS' if red_6 else 'FAIL'}] 打瞎判据见证：有红腿 -> {verdict_red}；"
              f"恒真 -> {verdict_const}")
        checks.append(red_6)
    finally:
        import shutil

        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)

    # ⑦ 人工复核清单里复核方式写占位符 -> 闸 B 必须红（这条闸今天没有真实条目，
    #    所以用一个「静态证不成」的假源码 + 假登记来把校验路径跑通）。
    weak_src = _strip_top_function(
        next(s.source for s in slots if s.stem == victim), "prove_red"
    ) + "\n\ndef prove_red():\n    return bool(_weak_probe())\n"
    weak_slots = [s._replace(source=weak_src) if s.stem == victim else s for s in slots]
    fake_manual = {victim: {"method": "无需", "reviewed": date.today().isoformat()}}
    problems = _gate_b_failures(weak_slots, fake_manual)
    red_7 = any(victim in p and "人工复核方式" in p for p in problems)
    # 反向：把 method 写实、日期写未来 -> 也必须红（日期不许穿越）。
    fake_manual_2 = {
        victim: {"method": "python tools/contract_hooks/hooks_74.py（人工跑一遍 prove-red）",
                 "reviewed": "2999-01-01"}
    }
    problems_2 = _gate_b_failures(weak_slots, fake_manual_2)
    red_7 = red_7 and any(victim in p and "未来" in p for p in problems_2)
    print(f"  [{'PASS' if red_7 else 'FAIL'}] 人工复核：方式写占位符 / 日期写未来 -> "
          f"{'红' if red_7 else '仍绿'}")
    checks.append(red_7)

    ok = all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


# ---------------------------------------------------------------------------
# CLI：--run-prove-red（套件入口）/ --witness / --json
# ---------------------------------------------------------------------------
def _cli(argv: list[str]) -> int:
    only = None
    if ONLY_FLAG in argv:
        raw = argv[argv.index(ONLY_FLAG) + 1] if argv.index(ONLY_FLAG) + 1 < len(argv) else ""
        only = {name for name in re.split(r"[,;\s]+", raw) if name}
    if RUNNER_FLAG in argv:
        return run_prove_red_all(only=only, verbose="--verbose" in argv)
    if "--witness" in argv:
        bad = 0
        for path in sorted(iter_hook_files()):
            if not _has_prove_red(path.read_text(encoding="utf-8-sig")):
                continue
            verdict = _witness_verdict(path)
            print(f"  {path.stem:30s} {verdict}")
            if verdict != "red":
                bad += 1
        return 1 if bad else 0
    if "--json" in argv:
        import json

        slots = _modules()
        print(json.dumps(
            {
                "modules": len(slots),
                "with_prove_red": sum(1 for s in slots if _has_prove_red(s.source)),
                "exempt": sorted(EXEMPT_NO_PROVE_RED),
                "manual": sorted(MANUAL_REVIEW),
            },
            ensure_ascii=False,
            indent=1,
        ))
        return 0
    return 0 if prove_red() else 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
