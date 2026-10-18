# -*- coding: utf-8 -*-
"""#112：``agent/`` 的**页面状态判据**还在用逐字相等 —— `挑战` / `挑战→` 只认一半帧。

## 事实（真机帧 / 识别调研，与 #109 / #110 同源）
编队页底部【挑战】按钮有两种**稳定**渲染：``挑战`` 与 ``挑战→``（带箭头）。
``docs/research/recognition-ocr-vs-template.md`` §1.2 例 1 / §1.3「两态」统计 **8/17 帧**带箭头，
两种读法**各自像素稳定**（score 1.000 / 0.962，长跑里一字不差）—— 不是抖动，是两个视觉状态。

``agent/`` 的状态分类里原先写的是**逐字相等**：

    agent/battle_loop_core.py:402   if party and any(t == "挑战" for t in texts):
    agent/abyss_impl.py:398         if party and any(t == "挑战" for t in texts):
    agent/wuchong_impl.py:636       if party and any(t == "挑战" for t in texts):

⇒ 带箭头的那一半帧上「编队页」判据不成立 ⇒ ``classify`` 判成 ``unknown`` ⇒ 状态机走错分支
（不是识别率问题，是**门控有一半概率不成立**）。#109 修的是页面**锚点**、#110 修的是**点击**
判据，本票修的是 classify 的**页面状态**判据 —— 三件事，别混。

## 真源 / 快照（别猜）
- **真源 = ``scene/challenge.py``**（``CHALLENGE_CLICK_PATTERNS`` = ``^挑战(→)?$``，整串锚定 +
  **至多一个**箭头）。页面判据与点击判据**同形不同责**：本票只动 classify 的判据。
- ★``agent/`` 是**安装态的独立目录（没有 ``scene/``）**⇒ 不能 ``from scene.challenge import``★
  ⇒ 按本仓既有做法存**逐字快照**（先例：``agent/side_impl._PUBCHALLENGE_PATTERNS``、
  ``agent/auto_switch_impl._TEAM_PAGE_ANCHORS_SNAPSHOT``）：快照落在
  ``agent/battle_loop_core.PAGE_CHALLENGE_PATTERNS``（**唯一一处**，与 #63 的主城判据同纪律：
  共享源放在 core，深渊/五重 ``from battle_loop_core import ...``，**绝不各自复制一份**）。

## 契约
- **T1 快照 == 真源（逐字）**：``agent/battle_loop_core.PAGE_CHALLENGE_PATTERNS`` 与
  ``scene.challenge.CHALLENGE_CLICK_PATTERNS`` **逐项相等**；``abyss_impl`` / ``wuchong_impl``
  取的是**同一个对象**（不是各自复制）；且这份字面量在 ``agent/`` 里只有**三处合法落点**
  （本票的页面快照 + #110 的点击快照 ``side_impl._PUBCHALLENGE_PATTERNS`` + #109 的编队页锚点
  ``auto_switch_impl._TEAM_PAGE_ANCHORS_SNAPSHOT``）—— 多抄一份就红（抄第三份 = 第三套真源）。
- **T2 ratchet（逐字相等 = 红）**：``agent/`` 里任何**活跃**字符串常量，只要
  (a) 值等于 :data:`WATCHED_PAGE_TOKENS` 里的一颗页面状态字（``挑战`` / ``挑战→`` / ``自动`` /
  ``自动→`` / ``SET 1``），或
  (b) 作为一个**中文 OCR 判据**被 ``==`` / ``!=`` / ``in``(常量元组) 逐字比较，
  就必须登记在 :data:`LITERAL_EQUALITY_EXEMPT` 里（文件 + 字面量 + 为什么安全），否则红并
  **点名文件+行号**。★为什么 (b) 只盯中文★：``OK`` / ``special`` 这类 ASCII 是**状态机词汇**
  不是 OCR 页面文字，把它们算进来只会逼人改错的东西（与 hooks_110 T2 同一取舍）。
  ★登记项必须仍然「指得到东西」★：字面量没了还留着登记 = 影子豁免，会掩盖下一次漂移。
- **T3 两种渲染都算编队页 / 放宽封顶**：``挑战`` / ``挑战→`` 都判 ``True``（判据层 + 三处
  ``classify`` 层）；``再次挑战 / 继续挑战 / 挑战深渊连战 / 挑战深渊连战EX / 高难挑战 /
  连续挑战次数 / 挑战→→ / →挑战``（= ``scene.challenge.REJECTED_TEXTS``）全部判 ``False``
  （``(→)?`` 不是 ``(→)*``，也不是 ``.*``；这些控件在真机屏上真的存在，判成编队页就会走错）。

破坏实验（``.venv\\Scripts\\python.exe tools\\contract_hooks\\hooks_112.py``）≥2，本票做 3 条：
① 把一处 classify 改回 ``== "挑战"`` -> ratchet 红（在**临时副本**上做，绝不改真文件）；
② 快照漂移（``PAGE_CHALLENGE_PATTERNS`` 改回 ``^挑战$``）-> T1 红；
③ 行为倒退（编译好的判据改回 ``^挑战$``）-> T3 红（``挑战→`` 漏），证明行为用例真的在求值。
"""

from __future__ import annotations

import ast
import importlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"

#: 真机「挑战」按钮的两种读法（受本守卫管辖的页面状态判据必须命中这两段文字）。
RENDERINGS: tuple[str, ...] = ("挑战", "挑战→")

#: 需求点名的反例（完整反例表在 ``scene.challenge.REJECTED_TEXTS``；这里再点名一遍，
#: 万一有人从真源反例表里悄悄删一条，本守卫会先红）。
REQUIRED_REJECTS: tuple[str, ...] = (
    "再次挑战",
    "继续挑战",
    "挑战深渊连战EX",
    "挑战→→",
    "→挑战",
)

#: 快照的落点（模块名 / 常量名）。
SNAPSHOT_MODULE = "battle_loop_core"
SNAPSHOT_ATTR = "PAGE_CHALLENGE_PATTERNS"
SINGLE_TEXT_PREDICATE = "is_challenge_page_text"
PREDICATE_ATTR = "has_challenge_page_text"
#: 必须**从共享源取**（而不是自己抄一份）的兄弟模块。
PREDICATE_CONSUMERS: tuple[str, ...] = ("abyss_impl", "wuchong_impl")

#: ★本票管辖的页面状态字★ —— 出现「逐字相等 / 裸字面量」即红（除非登记）。
#: ``挑战`` / ``挑战→`` 是本票修的那颗按钮；``自动`` / ``自动→`` 是同一类「开关字」；
#: ``SET 1`` 是**同一个编队页**的 party 兜底锚点（同类风险在空白/粘连，见豁免表）。
WATCHED_PAGE_TOKENS: tuple[str, ...] = ("挑战", "挑战→", "自动", "自动→", "SET 1")

#: ★已知的同类落点：**本票不改**，逐条登记「为什么安全 / 为什么不归本票」★。
#: 语义：**子集门禁** —— 新冒出来的（文件, 字面量）没登记就红；某处修好了字面量没了，
#: 登记项会主动报错要求删掉（不留影子豁免）。
LITERAL_EQUALITY_EXEMPT: dict[tuple[str, str], str] = {
    # --- 同一个编队页的 party 兜底锚点（★#119 后只剩共享版这一处★）---
    # 主锚点是正则 `Party\s*[A-Za-z]`（真机编队页一屏多张 `Party A..G` 卡，永远先命中）；
    # `SET 1` 只是兜底。它的风险在**空白/粘连**（`SET  1` / `SET1`）而不是箭头，且真机帧
    # （hooks_63.WUCHONG_TEAM_OCR 取自 abyss_cal 真机截图）逐字读作 `SET 1`。
    # 宽成 `^SET\s*1$` 属于「无真源可依的新判据」（scene/ 里没有这条常量）⇒ 登记待证据（YAGNI），
    # 一旦有真机帧证明有第二种读法，正解是先在 scene/ 立真源、再回来同步。
    # ★#119★ 深渊/五重的 classify 已薄封装到 battle_loop_core（判据只有一份），故本文件里
    # abyss_impl / wuchong_impl 的三条豁免已**删除**（字面量不再存在 = 影子豁免必须删）。
    ("battle_loop_core.py", "SET 1"): "编队页 party 兜底锚点（主锚点是 Party 正则；无多渲染证据）",
    # --- 战斗 HUD：不是页面状态判据，且旁边已有正则路径 ---
    # battle_loop_core：`time_ok = any(_TIME_RE.search(t) …) or (any(t == "时间") and any(_HHMM_RE…))`
    # —— 正则那条走在前，`t == "时间"` 只是 OCR 把 HUD 切成「时间 / 07:32」两个框时的兜底；
    # 真机没有「时间→」这种渲染（箭头装饰只出现在【挑战】按钮上）。
    ("battle_loop_core.py", "时间"): "战斗 HUD 分隔框兜底（正则 _TIME_RE 走在前；非页面状态判据）",
    ("battle_loop_core.py", "分数"): "战斗 HUD 分数框前缀（宽松方向：只多认不漏帧；非页面状态判据）",
    # --- 终始之战列表页签：无多渲染证据，且不是「带装饰的按钮」---
    # ★#119★ 三颗页签现在是 SceneConfig.zhongshi_tabs 的**数据缺省值**（DEFAULT_ZHONGSHI_TABS），
    # 不再是 `t in ("未通关", "已通关", "完成")` 的逐字比较 ⇒ 不在 ratchet 的管辖面里
    # （ratchet 管的是「逐字相等判据」，数据表不在此列）。故三条豁免一并删除。
    # --- 「自动」：开关字，不是本票的页面状态判据；真源/守卫在别处 ---
    # auto_switch_impl 里的 `"自动"` 是**开关标签值 + 探针偏移表的键**（定位/读数用），
    # 由 #108 的 `_AUTO_LABEL_PATTERNS_SNAPSHOT = (r"^自动$",)` 钉着 scene.auto_switch 真源
    # （hooks_108 / hooks_auto_outside 逐字对账）。真机没有「自动→」的证据；若哪天有，
    # 正解是在 scene/auto_switch 立真源 + 三处快照一起改，绝不是在本票里手改一个 agent 文件。
    ("auto_switch_impl.py", "自动"): "自动开关的标签值/探针键（真源 scene.auto_switch，hooks_108 钉着）",
    # --- 域模型字段，不是 OCR 文本 ---
    ("batch_plan.py", "降临讨伐"): "比对的是域模型字段 m.子族（GLOSSARY 数据），不是屏幕 OCR",
}

#: 快照这份字面量在 ``agent/`` 里的**合法落点**（模块文件 → 承接它的常量名 → 角色）。
#: 多一处 = 第三套真源（漂移起点），少一处 = 有人把某一层的同步删了（同样红）。
SNAPSHOT_HOME: dict[tuple[str, str], str] = {
    ("battle_loop_core.py", "PAGE_CHALLENGE_PATTERNS"):
        "本票：页面状态判据（classify 的「编队页」）唯一共享源，深渊/五重 import 它",
    ("side_impl.py", "_PUBCHALLENGE_PATTERNS"):
        "#110：PubChallenge 的**点击**判据运行期快照（pipeline_override 用），hooks_110 钉着",
    ("auto_switch_impl.py", "_TEAM_PAGE_ANCHORS_SNAPSHOT"):
        "#109：编队页**锚点**快照（scene.auto_switch.TEAM_PAGE_ANCHORS 的安装态回退）",
}

#: 兼容旧引用：真源里的完整反例表（本守卫按它做行为用例，跟随真源不硬编码）。
_CHALLENGE_DOC = "scene.challenge"


# ---------------------------------------------------------------------------
# 路径 / 惰性导入（与同目录其它 hooks 同一手法）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for p in (str(REPO_ROOT), str(REPO_ROOT / "tools"), str(AGENT_DIR)):
        if p not in sys.path:
            sys.path.append(p)


def _challenge():
    """取 ``scene.challenge`` **子模块**（``scene/__init__`` 会把同名函数挂到包上）。"""
    _paths()
    return importlib.import_module(_CHALLENGE_DOC)


def _agent_module(name: str):
    """取 ``agent/<name>.py`` 模块（安装态目录；靠 sys.path 里的 agent 目录）。"""
    _paths()
    return importlib.import_module(name)


def _core():
    return _agent_module(SNAPSHOT_MODULE)


# ---------------------------------------------------------------------------
# AST：活跃字符串常量 / 逐字相等的判据
# ---------------------------------------------------------------------------
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def _docstring_ids(tree: ast.AST) -> set[int]:
    """模块/类/函数的 docstring 节点 id（它们是**说明**，不是「使用」）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _is_constant(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _active_constants(tree: ast.AST):
    """活跃的字符串常量：``(值, 行号)``（注释天然不在 AST 里；docstring 排除）。"""
    skip = _docstring_ids(tree)
    for node in ast.walk(tree):
        if _is_constant(node) and id(node) not in skip:
            yield node.value, node.lineno


def _compared_constants(tree: ast.AST):
    """作为**逐字相等判据**用的字符串常量：``(值, 行号, 片段)``。

    覆盖三种写法（本票排查出来的近似形态）：
      * ``t == "X"`` / ``t != "X"``（``Eq`` / ``NotEq``）；
      * ``t in ("X", "Y")``（``In`` + 常量元组）—— ``t in ZHONGSHI_TABS`` 这种**数据表**不算；
      * ``t.startswith("X")`` / ``t.endswith("X")`` —— 半开区间：``endswith`` 会漏 ``X→``，
        ``startswith`` 会多认 ``X→→``，两种都是错形状。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            ops = list(node.ops)
            comparators = list(node.comparators)
            for op, comp in zip(ops, comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and _is_constant(comp):
                    yield comp.value, comp.lineno, ast.unparse(node)
                elif isinstance(op, ast.In) and isinstance(comp, ast.Tuple):
                    for elt in comp.elts:
                        if _is_constant(elt):
                            yield elt.value, elt.lineno, ast.unparse(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("startswith", "endswith") and node.args:
                arg = node.args[0]
                if _is_constant(arg):
                    yield arg.value, arg.lineno, ast.unparse(node)


def _py_files(repo_root: Path) -> list[Path]:
    """``<repo_root>/agent/*.py``（只扫顶层：安装态发出去的就是这些）。"""
    return sorted(p for p in (Path(repo_root) / "agent").glob("*.py") if p.is_file())


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(Path(repo_root).resolve()).as_posix()


# ---------------------------------------------------------------------------
# T1：快照 == 真源（逐字），且只有一处页面状态快照
# ---------------------------------------------------------------------------
def _assignments_with(tree: ast.AST, literal: str) -> list[str]:
    """哪个模块级常量承接了这份字面量（``NAME = ...`` / ``NAME: t = ...`` 的值树里含它）。"""
    names: list[str] = []

    def contains(node) -> bool:
        return any(
            _is_constant(sub) and sub.value == literal for sub in ast.walk(node)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if contains(node.value):
                names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if contains(node.value) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
    return names


def _snapshot_failures(repo_root: Path | None = None) -> list[str]:
    ch = _challenge()
    core = _core()
    root = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    want = tuple(ch.CHALLENGE_CLICK_PATTERNS)
    msgs: list[str] = []

    got = getattr(core, SNAPSHOT_ATTR, None)
    if got is None:
        return [f"agent/{SNAPSHOT_MODULE}.{SNAPSHOT_ATTR} 不见了 —— 页面状态判据没有快照可钉"]
    if tuple(got) != want:
        msgs.append(
            f"agent/{SNAPSHOT_MODULE}.{SNAPSHOT_ATTR} = {tuple(got)!r} 与真源 "
            f"{_CHALLENGE_DOC}.CHALLENGE_CLICK_PATTERNS = {want!r} 不一致"
            f"（安装态没有 scene/，这里是**逐字快照**；不同步 = 装好的产品仍只认『挑战』）"
        )

    # 兄弟模块必须**取同一个对象**（自己抄一份 = 第二套真源，#63 同一纪律）。
    for name in PREDICATE_CONSUMERS:
        mod = _agent_module(name)
        if getattr(mod, PREDICATE_ATTR, None) is not getattr(core, PREDICATE_ATTR, None):
            msgs.append(
                f"agent/{name}.{PREDICATE_ATTR} 不是 battle_loop_core 的同一个对象"
                f"（各自复制一份判据即漂移；请 `from battle_loop_core import {PREDICATE_ATTR}`）"
            )
        theirs = getattr(mod, SNAPSHOT_ATTR, None)
        if theirs is not None and theirs is not got:
            msgs.append(
                f"agent/{name}.{SNAPSHOT_ATTR} 自己抄了一份快照 {tuple(theirs)!r} —— "
                f"快照只能有一处（battle_loop_core），别处一律 import"
            )

    # 这份字面量在 agent/ 里只许有 SNAPSHOT_HOME 登记的落点。
    seen: set[tuple[str, str]] = set()
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:  # pragma: no cover - 坏文件必须响亮失败
            msgs.append(f"{path.name} 解析失败，无法核对快照落点：{exc}")
            continue
        for name in _assignments_with(tree, want[0]):
            seen.add((path.name, name))
            if (path.name, name) not in SNAPSHOT_HOME:
                msgs.append(
                    f"agent/{path.name}::{name} 又抄了一份 {want[0]!r} 快照 —— "
                    f"`agent/` 里这份字面量只许三处合法落点（页面状态 / 点击判据 / 编队页锚点），"
                    f"第三份拷贝就是第三套真源"
                )
    for key in SNAPSHOT_HOME:
        if key not in seen:
            msgs.append(
                f"SNAPSHOT_HOME 登记了 agent/{key[0]}::{key[1]}，但那里已经没有这份快照了 —— "
                f"把它从登记表删掉（过期的登记会让人以为还有一处同步）"
            )
    return msgs


def probe_page_state_challenge_snapshot() -> bool:
    """T1：``agent/`` 的页面状态快照逐字等于 ``scene.challenge`` 真源，且只有一处。"""
    return _snapshot_failures() == []


# ---------------------------------------------------------------------------
# T2：ratchet —— 逐字相等的页面状态判据必须登记
# ---------------------------------------------------------------------------
def _literal_page_state_hits(repo_root: Path | None = None):
    """扫 ``agent/*.py``，产出 ``(相对文件, 字面量, 行号, 为什么受管辖)``。"""
    root = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = _rel(path, root)
        for value, lineno in _active_constants(tree):
            if value.strip() in WATCHED_PAGE_TOKENS:
                yield rel, value, lineno, "裸页面状态字（只可能被逐字/子串比较用上）"
        for value, lineno, snippet in _compared_constants(tree):
            # (b) 只盯中文 OCR 判据：ASCII 的是状态机词汇（OK / special / SET 1 走 (a) 那条）。
            if _has_cjk(value):
                yield rel, value, lineno, f"逐字相等判据 `{snippet}`"


def _ratchet_failures(repo_root: Path | None = None) -> list[str]:
    root = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    msgs: list[str] = []
    seen: set[tuple[str, str]] = set()

    for rel, value, lineno, why in _literal_page_state_hits(root):
        key = (Path(rel).name, value)
        seen.add(key)
        if key in LITERAL_EQUALITY_EXEMPT:
            continue
        if value.strip() in ("挑战", "挑战→"):
            fix = (
                f"改成 `battle_loop_core.{PREDICATE_ATTR}(texts)`（整串锚定 + 至多一个箭头；"
                f"真机『挑战』有两种渲染 `挑战` / `挑战→`，逐字相等会漏掉 8/17 的帧）"
            )
        else:
            fix = (
                "改成整串正则（`^…$`）—— 页面状态判据要按**文本形状**判，不按字面量；"
                "若确实是别的控件、且没有多渲染证据，就登记到 hooks_112.LITERAL_EQUALITY_EXEMPT"
                "并写明为什么安全"
            )
        msgs.append(
            f"{rel}:{lineno} 的 {value!r} 是{why} —— 页面状态判据不许逐字相等：{fix}"
        )

    # 登记项必须仍然「指得到东西」：字面量没了还留着 = 影子豁免，会掩盖下一次漂移。
    for key in LITERAL_EQUALITY_EXEMPT:
        if key not in seen:
            msgs.append(
                f"LITERAL_EQUALITY_EXEMPT 里 agent/{key[0]} 的 {key[1]!r} 已经不存在了 —— "
                f"把它从豁免表删掉（过期豁免 = 影子，会掩盖新漂移）"
            )
    return msgs


def probe_page_state_challenge_ratchet() -> bool:
    """T2：``agent/`` 里没有未登记的逐字相等页面状态判据。"""
    return _ratchet_failures() == []


# ---------------------------------------------------------------------------
# T3：两种渲染都算编队页；放宽封顶
# ---------------------------------------------------------------------------
#: 编队页 party 锚点（真机 720 空间框，取自 ``hooks_63.WUCHONG_TEAM_OCR`` 的真机编队页帧）。
PARTY_ITEMS: tuple[tuple[str, list[int]], ...] = (
    ("SET 1", [70, 457, 38, 15]),
    ("Party E", [92, 512, 97, 36]),
)

#: 两种渲染的读法框（箭头在标签右侧 ⇒ 框更宽；classify 只用它的 y，不影响结论）。
READING_BOXES: dict[str, list[int]] = {
    "挑战": [296, 1053, 82, 47],
    "挑战→": [296, 1053, 122, 47],
}
NEGATIVE_BOX: list[int] = [296, 1053, 190, 47]


def _frame(text: str, box) -> list[tuple[str, list[int]]]:
    """编队页帧 = party 锚点 + 一个【挑战】位置的文字（正例或反例）。"""
    return [(t, list(b)) for t, b in PARTY_ITEMS] + [(text, list(box))]


def _classifiers():
    """三处 classify：``(标签, items -> state, 编队页状态名)``。"""
    core = _core()
    ab = _agent_module("abyss_impl")
    wc = _agent_module("wuchong_impl")
    ph = _agent_module("phantom_impl")
    return (
        ("battle_loop_core.classify(phantom)", lambda items: core.classify(ph._CFG, items)[0],
         f"{ph._CFG.state_prefix}_solo_team"),
        ("abyss_impl.classify", lambda items: ab.classify(items)[0], ab.ABYSS_SOLO_TEAM),
        ("wuchong_impl.classify", lambda items: wc.classify(items)[0], wc.WUCHONG_TEAM),
    )


def _both_renderings_failures() -> list[str]:
    ch = _challenge()
    core = _core()
    msgs: list[str] = []

    # (a) 判据层：两种渲染 True；真源点名过的反例全 False。
    for text in RENDERINGS:
        if not core.is_challenge_page_text(text):
            msgs.append(
                f"页面状态判据漏了『{text}』：battle_loop_core.is_challenge_page_text 判否"
                f"（快照 {core.PAGE_CHALLENGE_PATTERNS!r} 必须整串锚定 + 至多一个箭头）"
            )
    rejects = tuple(getattr(ch, "REJECTED_TEXTS", ()) or ())
    missing = [t for t in REQUIRED_REJECTS if t not in rejects]
    if missing:
        msgs.append(
            f"真源 {_CHALLENGE_DOC}.REJECTED_TEXTS 少了本票点名的反例 {missing!r}"
            f"（反例表被删条目 = 放宽没了上限）"
        )
    for text in rejects:
        if core.is_challenge_page_text(text):
            msgs.append(
                f"页面状态判据放宽过头：反例『{text}』被判成编队页『挑战』"
                f"（`(→)?` 不是 `(→)*`，更不是 `.*`）"
            )

    # (b) classify 层：三处状态机都要两种渲染都判成「编队页」，反例都不是。
    for label, classify, team_state in _classifiers():
        for text in RENDERINGS:
            got = classify(_frame(text, READING_BOXES[text]))
            if got != team_state:
                msgs.append(
                    f"{label}：『{text}』帧判成 {got!r}，应为 {team_state!r}"
                    f"（带箭头的那一半帧会走错分支 —— 本票要修的正是它）"
                )
        for text in rejects:
            got = classify(_frame(text, NEGATIVE_BOX))
            if got == team_state:
                msgs.append(
                    f"{label}：反例『{text}』被判成 {team_state!r}"
                    f"（那是**别的控件**，判成编队页就会走错分支）"
                )
    return msgs


def probe_page_state_challenge_both_renderings() -> bool:
    """T3：``挑战`` / ``挑战→`` 都判成编队页（判据层 + 三处 classify 层）；反例一个都不中。"""
    return _both_renderings_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        "page-state-challenge-snapshot",
        "#112",
        "agent/battle_loop_core.PAGE_CHALLENGE_PATTERNS 逐字等于真源 scene.challenge"
        "（安装态没 scene/ 只能存快照）；abyss/wuchong 取的是同一个对象，快照只有一处落点",
        probe_page_state_challenge_snapshot,
    ),
    (
        "page-state-challenge-ratchet",
        "#112",
        "ratchet：agent/ 里任何『逐字相等 / 裸字面量』的页面状态判据（挑战 / 挑战→ / 自动 / "
        "SET 1 …）必须是共享判据或登记在豁免表；新增/回退即红并点名文件+行号",
        probe_page_state_challenge_ratchet,
    ),
    (
        "page-state-challenge-both-renderings",
        "#112",
        "两种渲染都算编队页：`挑战` / `挑战→` 在判据层与三处 classify 层都判 True；"
        "再次挑战/继续挑战/挑战深渊连战EX/挑战→→/→挑战 全部判 False",
        probe_page_state_challenge_both_renderings,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（≥2；本票做 3 条）
# ---------------------------------------------------------------------------
def _temp_agent() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook112_"))
    shutil.copytree(REPO_ROOT / "agent", root / "agent",
                    ignore=shutil.ignore_patterns("__pycache__", "debug"))
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def prove_red() -> bool:
    ch = _challenge()
    core = _core()
    print("hooks_112 prove-red：三条破坏，要求守卫各自变红")
    green = (
        probe_page_state_challenge_snapshot()
        and probe_page_state_challenge_ratchet()
        and probe_page_state_challenge_both_renderings()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三个守卫全绿")
    if not green:
        for m in (
            _snapshot_failures()
            + _ratchet_failures()
            + _both_renderings_failures()
        ):
            print(f"      - {m}")
        return False

    checks: list[bool] = []
    old_shape = "^挑战" + "$"  # 运行时拼出来：本文件不该成为一次「活跃使用」

    # ① 把一处 classify 改回 `any(t == "挑战" ...)`（= 有人手改回去 / 只修了一半）→ ratchet 红
    # ★#119★ 页面判据只剩 battle_loop_core.classify 一份（深渊/五重已是薄封装），
    #   故破坏点从 wuchong_impl 搬到共享版的那个分支 —— 换的是落点，不是契约。
    tmp = _temp_agent()
    try:
        target = tmp / "agent" / "battle_loop_core.py"
        _sub(
            target,
            f"if party and {PREDICATE_ATTR}(texts):",
            'if party and any(t == "挑战" for t in texts):',
        )
        m = _ratchet_failures(tmp)
        red = len(m) > 0 and any("\"挑战\"" in x or "'挑战'" in x for x in m)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 battle_loop_core 的编队页判据改回 "
            f"`any(t == \"挑战\" ...)` -> {'红' if red else '仍绿'}"
            + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ② 快照漂移（页面快照改回旧形状 `^挑战$`）→ T1 红
    real_snapshot = core.PAGE_CHALLENGE_PATTERNS
    try:
        core.PAGE_CHALLENGE_PATTERNS = (old_shape,)
        m = _snapshot_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 battle_loop_core.PAGE_CHALLENGE_PATTERNS "
            f"改回 {old_shape!r}（快照漂移）-> {'红' if red else '仍绿'}"
            + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        core.PAGE_CHALLENGE_PATTERNS = real_snapshot

    # ③ 行为倒退（编译好的判据改回 `^挑战$`）→ T3 红：证明行为用例真的在求值
    real_res = core._PAGE_CHALLENGE_RES
    try:
        core._PAGE_CHALLENGE_RES = (re.compile(old_shape),)
        m = _both_renderings_failures()
        red = len(m) > 0 and any("挑战→" in x for x in m)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把页面判据的行为改回 {old_shape!r}"
            f"（『挑战→』又漏）-> {'红' if red else '仍绿'}"
            + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        core._PAGE_CHALLENGE_RES = real_res

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
