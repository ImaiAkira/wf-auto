# -*- coding: utf-8 -*-
"""#119：三份 ``classify`` 去重成一份 —— 判据只许一份、薄壳只许一行、状态前缀必须对得上。

## 现场（为什么这张守卫值得存在）

``classify``（把全屏 OCR 分词画面名）曾在**三个文件**里各写一份：``battle_loop_core`` /
``abyss_impl`` / ``wuchong_impl``。**#107** 给共享的 ``is_battle_hud`` 加了「HUD 被 toast
遮挡时的多视觉特征兜底」，但另外两份 ``classify`` 根本没调它 —— 同一帧上
``is_battle_hud=True``，幻想判 ``battle``、另外两份判 ``unknown``，真机幻想 912 秒死循环。
**一个正确的修复被重复实现静默废掉**，比 bug 本身更危险（票 #119 原文）。

去重后：判据只有 ``battle_loop_core.classify`` + 它的分支纯函数一份；三个场景只差**数据**
（``SceneConfig.classify_order`` / 锚点 / ``state_names`` / ``hub_match`` / ``main_match``）。
本文件把「不许再长出第二份」写成三条可执行的契约。

## 守卫

① ``classify-predicates-single-source`` —— AST 扫 ``agent/*.py``：

   * 除 ``battle_loop_core.py`` 外，**不许**出现战斗判据的变量名 ``time_ok`` / ``score_ok``
     （= 那个 ``if time_ok and score_ok`` 的形状）；
   * ``abyss_impl.py`` / ``wuchong_impl.py`` 的模块级**活跃**字符串常量里，不许再有
     ``QUESTRESULT`` / ``获得道具`` / ``继续挑战`` / ``时间`` / ``分数`` / ``Party\\s*[A-Za-z]``
     这几颗判据锚点（注释与 docstring 天然不算）；
   * 任何**页面分类函数**（返回值是页面状态名的函数，含 f-string 尾字面量）只要在
     ``battle_loop_core`` 之外，就不许含上面这些锚点 —— 这一条抓的是「换个文件名再抄一份」。

② ``classify-thin-wrappers`` —— ``abyss_impl.classify`` / ``wuchong_impl.classify`` 的函数体
   必须是**可选 docstring + 恰好一条** ``return core.classify(_CLASSIFY_CFG, items,
   relogin_phrases)``；且模块里必须有 ``_CLASSIFY_CFG = core.SceneConfig(...)`` 的赋值。
   幻想的 ``classify`` 必须是 ``functools.partial(core.classify, _CFG)``（不是手写 def）。

③ ``classify-state-prefixes`` —— 三条腿的 ``SceneConfig`` 与状态名/顺序对得上：

   * ``scene == state_prefix ==`` 期望前缀，三个前缀互不相同；
   * ``classify_order`` **逐项等于**冻结的期望顺序（★顺序也是语义★：结算在 hub/main 之前、
     五重的领主战列表在 main_city 之前、编队页在 detail 之前……改顺序 = 红，要单独走票）；
   * 分支表完整（``CLASSIFY_BRANCHES`` 与 ``_BRANCH_STATE_SUFFIX`` 同集合、且含所有被引用名字）；
   * 每个可返回状态 ∈ ``{unknown} ∪ BARE_STATES ∪ {prefix_*}``；可返回集合**精确等于**冻结值
     （删一个共享分支 / 换一种拼法立刻红）；
   * 模块自己的 ``ABYSS_*`` / ``WUCHONG_*`` 状态常量必须都在可返回集合里（pipeline 按名匹配）。

## 破坏实验（``python tools\\contract_hooks\\hooks_119.py``）≥3，本票做 5 条

① 在 wuchong 薄封装里塞回一个自有分支（``QUESTRESULT``）→ ①② 红；
② 把 abyss 的薄封装改回复制（``time_ok`` / ``score_ok`` + 结算锚点）→ ①② 红；
③ 从共享分支表里删掉 ``settle`` → ③ 红（顺序/可返回集合对不上）；
④ 把五重的 ``state_names["party"]`` 改成 ``wuchong_solo_team`` → ③ 红（拼法漂移）；
⑤ 把深渊配置的 ``state_prefix`` 换成 ``phantom`` → ③ 红（跨场景前缀混用）。

★破坏实验 ① ② 在**临时副本**上做（绝不改真仓库）；③④⑤ 用进程内 monkeypatch + finally 恢复。★
"""

from __future__ import annotations

import ast
import functools
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT = REPO_ROOT / "agent"

TICKET = "#119"
CORE = "battle_loop_core.py"
#: 去重后的三个入口（模块文件 → 配置属性名）。
SCENE_MODULES: tuple[tuple[str, str], ...] = (
    ("phantom_impl.py", "_CFG"),
    ("abyss_impl.py", "_CLASSIFY_CFG"),
    ("wuchong_impl.py", "_CLASSIFY_CFG"),
)

#: 战斗判据的变量名（``if time_ok and score_ok`` 那个形状）。只许出现在 battle_loop_core。
BATTLE_PREDICATE_NAMES: tuple[str, ...] = ("time_ok", "score_ok")

#: 判据锚点字面量（抽取前在三份 classify 里逐行重复）。
#: ``QUESTRESULT`` / ``获得道具`` / ``继续挑战`` = 结算；``时间`` / ``分数`` = 战斗 HUD；
#: ``Party\\s*[A-Za-z]`` = 编队页。
FORBIDDEN_ANCHORS: tuple[str, ...] = (
    "QUESTRESULT",
    "获得道具",
    "继续挑战",
    "时间",
    "分数",
)
PARTY_ANCHOR_RE = re.compile(r"Party\s*[A-Za-z]")

#: 页面状态名的形状（用于「这个函数是不是页面分类函数」的判定；f-string 只看尾字面量）。
_PAGE_SUFFIXES = (
    "loading", "level_required", "relogin", "battle", "settle", "main_city", "activity",
    "zhongshi", "solo_team", "team", "mode", "detail", "lord_list", "room", "coop_room",
    "recruit_dialog", "hub", "main", "no_entry",
)
_PAGE_STATE_RE = re.compile(
    r"^(?:[a-z0-9]+_)?(?:" + "|".join(_PAGE_SUFFIXES) + r")$"
)
_PAGE_TAIL_RE = re.compile(r"_(?:" + "|".join(_PAGE_SUFFIXES) + r")$")

#: ★顺序也是语义★ 三个场景的冻结顺序（逐条对账见票 #119 的评论）。改顺序 = 红。
EXPECTED_ORDERS: dict[str, tuple[str, ...]] = {
    "phantom": (
        "loading", "level_gate", "relogin", "battle", "main_city", "activity", "zhongshi",
        "recruit_dialog", "coop_room", "party", "settle", "hub", "main",
    ),
    "abyss": (
        "loading", "level_gate", "relogin", "battle", "main_city", "activity", "zhongshi",
        "party", "settle", "hub", "main",
    ),
    "wuchong": (
        "loading", "level_gate", "relogin", "no_entry", "battle", "quest_clear",
        "lord_list", "main_city", "activity", "party", "mode", "recruit_dialog",
        "coop_room", "detail", "settle",
    ),
}

#: ★状态名拼法★ 每个场景 classify 可能返回的状态集合（精确值；删一个共享分支即红）。
EXPECTED_STATES: dict[str, frozenset[str]] = {
    "phantom": frozenset({
        "loading", "phantom_level_required", "relogin", "phantom_battle", "main_city",
        "activity", "zhongshi", "phantom_recruit_dialog", "phantom_coop_room",
        "phantom_solo_team", "phantom_settle", "phantom_hub", "phantom_main", "unknown",
    }),
    "abyss": frozenset({
        "loading", "abyss_level_required", "relogin", "abyss_battle", "main_city",
        "activity", "zhongshi", "abyss_solo_team", "abyss_settle", "abyss_hub",
        "abyss_main", "unknown",
    }),
    "wuchong": frozenset({
        "loading", "wuchong_level_required", "relogin", "wuchong_no_entry",
        "wuchong_battle", "wuchong_lord_list", "main_city", "activity", "wuchong_team",
        "wuchong_mode", "wuchong_recruit_dialog", "wuchong_room", "wuchong_detail",
        "wuchong_settle", "unknown",
    }),
}


def _paths() -> None:
    for p in (str(REPO_ROOT), str(REPO_ROOT / "tools"), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _modules():
    """导入三个入口模块（agent 目录已在 sys.path 上）。"""
    _paths()
    import abyss_impl as ab  # noqa: PLC0415
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415
    import wuchong_impl as wc  # noqa: PLC0415

    return core, ph, ab, wc


# ---------------------------------------------------------------------------
# AST 小工具（注释天然不在 AST；docstring 明确跳过）
# ---------------------------------------------------------------------------
def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _active_constants(tree: ast.AST):
    """活跃字符串常量 ``(值, 行号)``（docstring 不算；注释不在 AST）。"""
    skip = _docstring_ids(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
        ):
            yield node.value, node.lineno


def _parsed_files(root: Path):
    for path in sorted((Path(root) / "agent").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:  # pragma: no cover - 坏文件必须响亮失败
            yield path, None, f"{path.name} 解析失败：{exc}"
            continue
        yield path, tree, None


def _returned_state_literals(fn) -> list[str]:
    """函数里 ``return <状态>, info`` 的状态字面量（含 f-string 的**尾字面量**）。"""
    out: list[str] = []

    def add(value) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.append(value.value)
        elif isinstance(value, ast.JoinedStr) and value.values:
            tail = value.values[-1]
            if isinstance(tail, ast.Constant) and isinstance(tail.value, str):
                out.append(tail.value)

    for node in ast.walk(fn):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        if isinstance(value, ast.Tuple) and value.elts:
            add(value.elts[0])
        else:
            add(value)
    return out


def _is_page_classifier(fn) -> bool:
    """这个函数像不像「页面分类器」：返回过页面状态名（``unknown`` / ``*_battle`` / …）。"""
    for literal in _returned_state_literals(fn):
        if literal == "unknown" or _PAGE_STATE_RE.match(literal):
            return True
        if _PAGE_TAIL_RE.search(literal):  # f"{sp}_battle" 的尾字面量
            return True
    return False


def _anchor_hits(value: str) -> list[str]:
    """``value`` 命中了哪些判据锚点。"""
    hits = [a for a in FORBIDDEN_ANCHORS if a and a == value]
    if PARTY_ANCHOR_RE.fullmatch(value):
        hits.append("Party\\s*[A-Za-z]")
    return hits


# ---------------------------------------------------------------------------
# 守卫 ①：判据只有一份（AST 扫 agent/*.py）
# ---------------------------------------------------------------------------
def _predicate_failures(root: Path | None = None) -> list[str]:
    root = Path(root) if root is not None else REPO_ROOT
    msgs: list[str] = []
    for path, tree, err in _parsed_files(root):
        if err:
            msgs.append(err)
            continue
        rel = path.name
        in_core = rel == CORE
        # (a) 除 core 外，不许出现战斗判据的变量名（if time_ok and score_ok 的形状）。
        if not in_core:
            for fn in _functions(tree):
                names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
                leaked = sorted(names & set(BATTLE_PREDICATE_NAMES))
                if leaked:
                    msgs.append(
                        f"agent/{rel}::{fn.name} 还在自写战斗判据 {leaked} —— "
                        "战斗判据只许在 battle_loop_core._branch_battle（#119）"
                    )
        # (b) 深渊 / 五重：模块级活跃常量里不许再有判据锚点（抽取前它们是副本）。
        if rel in ("abyss_impl.py", "wuchong_impl.py"):
            for value, lineno in _active_constants(tree):
                hits = _anchor_hits(value)
                if hits:
                    msgs.append(
                        f"agent/{rel}:{lineno} 的 {value!r} 是判据锚点 {hits}"
                        "（classify 已是薄封装；锚点只许由 SceneConfig 数据或 battle_loop_core 持有）"
                    )
        # (c) 除 core 外，任何**页面分类函数**都不许含判据锚点（换个文件名再抄一份也抓）。
        if not in_core:
            for fn in _functions(tree):
                if not _is_page_classifier(fn):
                    continue
                skip = _docstring_ids(fn)
                for node in ast.walk(fn):
                    if not (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in skip
                    ):
                        continue
                    hits = _anchor_hits(node.value)
                    if hits:
                        msgs.append(
                            f"agent/{rel}::{fn.name}:{node.lineno} 的 {node.value!r} 是判据锚点 "
                            f"{hits} —— 页面分类函数不许自带判据（判据只有 battle_loop_core 一份；"
                            "场景差异走 SceneConfig）"
                        )
    return msgs


def probe_classify_predicates_single_source() -> bool:
    """①：``agent/`` 里没有第二份判据（变量名 / 锚点 / 页面分类函数三条腿）。"""
    msgs = _predicate_failures()
    if msgs:
        print("  [119] 判据不是只有一份：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [119] 判据单源：time_ok/score_ok 只在 core；abyss/wuchong 无判据锚点；"
          "无第二份页面分类函数")
    return True


# ---------------------------------------------------------------------------
# 守卫 ②：薄封装只有一行 return
# ---------------------------------------------------------------------------
def _find_top_level(tree: ast.AST, name: str):
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _assigns_config(tree: ast.AST, cfg_name: str) -> bool:
    """模块里有没有 ``cfg_name = [core.]SceneConfig(...)``。"""
    for node in ast.walk(tree):
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if not any(isinstance(t, ast.Name) and t.id == cfg_name for t in targets):
            continue
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        if isinstance(func, ast.Attribute) and func.attr == "SceneConfig":
            return True
        if isinstance(func, ast.Name) and func.id == "SceneConfig":
            return True
    return False


def _wrapper_failures(root: Path | None = None) -> list[str]:
    root = Path(root) if root is not None else REPO_ROOT
    msgs: list[str] = []
    for module_file, cfg_name in SCENE_MODULES[1:]:
        path = Path(root) / "agent" / module_file
        if not path.is_file():
            msgs.append(f"agent/{module_file} 不存在（守卫与实现脱节）")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            msgs.append(f"agent/{module_file} 解析失败：{exc}")
            continue
        fn = _find_top_level(tree, "classify")
        if fn is None:
            msgs.append(f"agent/{module_file} 没有顶层 classify()（薄封装被改名/删了）")
            continue
        body = list(fn.body)
        # 允许先写 docstring（说明），但**业务语句只许一条 return**。
        if body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                body = body[1:]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            msgs.append(
                f"agent/{module_file}::classify 的函数体有 {len(body)} 条语句 —— "
                "薄封装只许 `return core.classify(...)` 一条（自带分支 = 第二份 classify，"
                "修复又会只对一个场景生效）"
            )
            continue
        call = body[0].value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "classify"
        ):
            msgs.append(
                f"agent/{module_file}::classify 不是 `return <core>.classify(...)`（实际 "
                f"{ast.unparse(call)[:80]!r}）"
            )
            continue
        base = call.func.value
        if not (
            isinstance(base, ast.Name) and base.id in ("core", "battle_loop_core")
        ):
            msgs.append(
                f"agent/{module_file}::classify 调的不是 battle_loop_core.classify（实际 "
                f"{ast.unparse(base)!r}）"
            )
        if len(call.args) != 3:
            msgs.append(
                f"agent/{module_file}::classify 应传 3 个位置参数（配置, items, relogin_phrases），"
                f"实际 {len(call.args)} 个"
            )
        elif not (isinstance(call.args[0], ast.Name) and call.args[0].id == cfg_name):
            msgs.append(
                f"agent/{module_file}::classify 的第一个实参不是 {cfg_name}"
                f"（实际 {ast.unparse(call.args[0])!r}）"
            )
        if not _assigns_config(tree, cfg_name):
            msgs.append(
                f"agent/{module_file} 没有 `{cfg_name} = [core.]SceneConfig(...)` —— "
                "薄封装的数据面不见了（判据会退回默认/别的场景）"
            )

    # 幻想：classify 必须是 core.classify 的 partial 绑定（不是手写 def）。
    if root == REPO_ROOT:
        _paths()
        import battle_loop_core as core  # noqa: PLC0415
        import phantom_impl as ph  # noqa: PLC0415

        if not (
            isinstance(ph.classify, functools.partial) and ph.classify.func is core.classify
        ):
            msgs.append(
                "agent/phantom_impl.py 的 classify 不是 functools.partial(core.classify, _CFG)"
                "（手写 def = 可能又长出一份分支）"
            )
        if ph.classify.args[:1] != (ph._CFG,):
            msgs.append("agent/phantom_impl.py 的 classify 绑定配置不是 ph._CFG")
    return msgs


def probe_classify_thin_wrappers() -> bool:
    """②：abyss/wuchong 的 classify 只有一行 return core.classify(...)；phantom 是 partial。"""
    msgs = _wrapper_failures()
    if msgs:
        print("  [119] 薄封装不成立：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [119] 薄封装：abyss/wuchong = 一行 return core.classify(_CLASSIFY_CFG, …)；"
          "phantom = partial(core.classify, _CFG)")
    return True


# ---------------------------------------------------------------------------
# 守卫 ③：state_prefix / 顺序 / 状态名拼法
# ---------------------------------------------------------------------------
def _prefix_failures() -> list[str]:
    core, ph, ab, wc = _modules()
    msgs: list[str] = []
    configs = {
        "phantom": ph._CFG,
        "abyss": ab._CLASSIFY_CFG,
        "wuchong": wc._CLASSIFY_CFG,
    }
    modules = {"phantom": ph, "abyss": ab, "wuchong": wc}

    # (a) 共享分支表完整（删一个分支 = 某页从此永远判不出）。
    table = set(core.CLASSIFY_BRANCHES)
    suffix = set(core._BRANCH_STATE_SUFFIX)
    if table != suffix:
        msgs.append(
            f"battle_loop_core.CLASSIFY_BRANCHES 与 _BRANCH_STATE_SUFFIX 不是同一套名字："
            f"多 {sorted(table - suffix)} 少 {sorted(suffix - table)}"
        )
    used = {b for order in EXPECTED_ORDERS.values() for b in order}
    missing = sorted(used - table)
    if missing:
        msgs.append(f"共享分支表缺 {missing}（被 classify_order 引用却不存在 = import 期就该炸）")

    prefixes = []
    for scene, cfg in configs.items():
        prefixes.append(getattr(cfg, "state_prefix", None))
        # (b) 前缀/场景 id 必须对得上（跨场景状态名混用的根）。
        if not isinstance(cfg, core.SceneConfig):
            msgs.append(f"{scene} 的配置不是 battle_loop_core.SceneConfig（类型 {type(cfg)!r}）")
            continue
        if cfg.scene != scene:
            msgs.append(f"{scene} 的 SceneConfig.scene={cfg.scene!r} != {scene!r}")
        if cfg.state_prefix != scene:
            msgs.append(
                f"{scene} 的 SceneConfig.state_prefix={cfg.state_prefix!r} != {scene!r}"
                "（状态前缀 = 场景 id；混用会让排查时说不清是谁的页面）"
            )
        # (c) 顺序逐项相等（★顺序也是语义★）。
        order = tuple(cfg.classify_order)
        if order != EXPECTED_ORDERS[scene]:
            msgs.append(
                f"{scene} 的 classify_order 被改了：\n      实际 {order}\n      期望 "
                f"{EXPECTED_ORDERS[scene]}\n      顺序也是语义（结算在 hub/main 之前、五重的"
                "领主战列表在 main_city 之前、编队页在 detail 之前）—— 改顺序要单独走票 + 真机三场景"
            )
        unknown = [b for b in order if b not in core.CLASSIFY_BRANCHES]
        if unknown:
            msgs.append(f"{scene} 的 classify_order 含未知分支 {unknown}")
        # (d) 可返回状态集合精确匹配（删共享分支 / 换拼法立刻红）。
        emitted = {core.state_for_branch(cfg, b) for b in order} | {"unknown"}
        want = EXPECTED_STATES[scene]
        if emitted != want:
            msgs.append(
                f"{scene} 的 classify 可返回状态集合变了：多 {sorted(emitted - want)} "
                f"少 {sorted(want - emitted)}"
            )
        # (e) 每个状态要么裸名、要么带**自己的**前缀。
        for state in sorted(emitted):
            if state == "unknown" or state in core.BARE_STATES:
                continue
            if not state.startswith(f"{scene}_"):
                msgs.append(
                    f"{scene} 会返回 {state!r}：既不是裸名也不是 {scene}_* 前缀"
                )
        # (f) 模块自己的状态常量必须都在可返回集合里（pipeline 按名匹配）。
        mod = modules[scene]
        const_prefix = f"{scene.upper()}_"
        for name in dir(mod):
            if not name.startswith(const_prefix):
                continue
            value = getattr(mod, name)
            if not isinstance(value, str) or not re.fullmatch(
                rf"{re.escape(scene)}_[a-z_]+", value
            ):
                continue
            if value not in emitted:
                msgs.append(
                    f"agent/{scene}_impl.py::{name}={value!r} 不在 classify 可返回集合里 —— "
                    "状态名拼法漂移 / 该分支被删了（pipeline 按这个名字匹配，改了就静默不命中）"
                )

    # (g) 三个前缀互不相同。
    if len(set(prefixes)) != len(configs):
        msgs.append(f"三个场景的 state_prefix 有重复：{prefixes!r}（= 跨场景状态混用）")
    # (h) 共享裸名不许长成某场景前缀。
    for bare in core.BARE_STATES:
        for scene in configs:
            if bare.startswith(f"{scene}_"):
                msgs.append(f"共享裸状态 {bare!r} 用了场景前缀 {scene!r}")
    return msgs


def probe_classify_state_prefixes() -> bool:
    """③：三条腿的 state_prefix / 分支顺序 / 状态名拼法都与契约一致。"""
    msgs = _prefix_failures()
    if msgs:
        print("  [119] 状态前缀/顺序/拼法对不上：")
        for m in msgs:
            print(f"    - {m}")
        return False
    print("  [119] 三条腿：state_prefix == 场景 id、三个前缀互不相同；"
          "classify_order 逐项 == 冻结顺序；可返回状态集合精确匹配")
    return True


HOOKS = [
    (
        "classify-predicates-single-source",
        TICKET,
        "判据只有一份：#107 的 HUD 兜底曾只对五重生效（同一帧 is_battle_hud=True，"
        "另外两份 classify 判 unknown → 真机幻想 912s 死循环）。AST 扫 agent/*.py："
        "time_ok/score_ok 只在 core；abyss/wuchong 无判据锚点；除 core 外没有第二份页面分类函数",
        probe_classify_predicates_single_source,
    ),
    (
        "classify-thin-wrappers",
        TICKET,
        "薄封装：abyss_impl.classify / wuchong_impl.classify 的函数体 = 恰好一条 "
        "`return core.classify(_CLASSIFY_CFG, items, relogin_phrases)`；phantom 是 "
        "partial(core.classify, _CFG) —— 带分支的薄壳 = 第二份判据（修复只对一个场景生效）",
        probe_classify_thin_wrappers,
    ),
    (
        "classify-state-prefixes",
        TICKET,
        "state_prefix == 场景 id 且互不相同；classify_order 逐项等于冻结顺序（顺序也是语义）；"
        "可返回状态集合精确匹配（删共享分支/换拼法立刻红）；模块的 ABYSS_*/WUCHONG_* 状态常量 "
        "全部在可返回集合里（pipeline 按名匹配）",
        probe_classify_state_prefixes,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（≥3；本票做 5 条）
# ---------------------------------------------------------------------------
def _temp_agent() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook119_"))
    shutil.copytree(
        REPO_ROOT / "agent", root / "agent",
        ignore=shutil.ignore_patterns("__pycache__", "debug"),
    )
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


_WUCHONG_WRAPPER = (
    "def classify(items, relogin_phrases=()):\n"
    "    return core.classify(_CLASSIFY_CFG, items, relogin_phrases)"
)
_ABYSS_WRAPPER = _WUCHONG_WRAPPER


def prove_red() -> bool:
    _paths()
    print("hooks_119 prove-red：五条破坏，要求守卫各自变红")
    green = (
        probe_classify_predicates_single_source()
        and probe_classify_thin_wrappers()
        and probe_classify_state_prefixes()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三条守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # ① 在 wuchong 薄封装里塞回一个自有分支（QUESTRESULT 结算）→ ①② 红
    tmp = _temp_agent()
    try:
        target = tmp / "agent" / "wuchong_impl.py"
        _sub(
            target,
            _WUCHONG_WRAPPER,
            "def classify(items, relogin_phrases=()):\n"
            "    if any(\"QUESTRESULT\" in (t or \"\") for t, _b in items):\n"
            "        return WUCHONG_SETTLE, {}\n"
            "    return core.classify(_CLASSIFY_CFG, items, relogin_phrases)",
        )
        m1 = _predicate_failures(tmp)
        m2 = _wrapper_failures(tmp)
        red = bool(m1) and bool(m2)
        print(
            f"  [{'PASS' if red else 'FAIL'}] wuchong 薄封装塞回自有分支（QUESTRESULT）-> "
            f"{'红' if red else '仍绿'}" + (f"  {m1[0]}" if m1 else "")
        )
        checks.append(red)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ② 把 abyss 薄封装改回复制（time_ok/score_ok + 结算锚点）→ ①② 红
    tmp = _temp_agent()
    try:
        target = tmp / "agent" / "abyss_impl.py"
        _sub(
            target,
            _ABYSS_WRAPPER,
            "def classify(items, relogin_phrases=()):\n"
            "    btexts = [t for t, _b in items]\n"
            "    time_ok = any(\"时间\" in t for t in btexts)\n"
            "    score_ok = any(t.startswith(\"分数\") for t in btexts)\n"
            "    if time_ok and score_ok:\n"
            "        return ABYSS_BATTLE, {}\n"
            "    if any(\"QUESTRESULT\" in t for t in btexts):\n"
            "        return ABYSS_SETTLE, {}\n"
            "    return core.classify(_CLASSIFY_CFG, items, relogin_phrases)",
        )
        m1 = _predicate_failures(tmp)
        m2 = _wrapper_failures(tmp)
        red = bool(m1) and bool(m2)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 深渊薄封装改回复制（time_ok/score_ok + 锚点）-> "
            f"{'红' if red else '仍绿'}" + (f"  {m1[0]}" if m1 else "")
        )
        checks.append(red)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    core, _ph, ab, wc = _modules()

    # ③ 从共享分支表删掉 settle → ③ 红（顺序/可返回集合对不上）
    saved = dict(core.CLASSIFY_BRANCHES)
    try:
        core.CLASSIFY_BRANCHES.pop("settle", None)
        m = _prefix_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 删掉共享分支 settle -> {'红' if red else '仍绿'}"
            + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        core.CLASSIFY_BRANCHES.clear()
        core.CLASSIFY_BRANCHES.update(saved)

    # ④ 五重的 state_names["party"] 改成 wuchong_solo_team → ③ 红（拼法漂移）
    real_names = dict(wc._CLASSIFY_CFG.state_names)
    try:
        wc._CLASSIFY_CFG.state_names["party"] = "wuchong_solo_team"
        m = _prefix_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 五重编队页状态名改成 wuchong_solo_team -> "
            f"{'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        wc._CLASSIFY_CFG.state_names.clear()
        wc._CLASSIFY_CFG.state_names.update(real_names)

    # ⑤ 深渊配置的 state_prefix 换成 phantom → ③ 红（跨场景前缀混用）
    import dataclasses  # noqa: PLC0415

    saved_cfg = ab._CLASSIFY_CFG
    try:
        ab._CLASSIFY_CFG = dataclasses.replace(saved_cfg, state_prefix="phantom")
        m = _prefix_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 深渊 state_prefix 换成 phantom -> "
            f"{'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        ab._CLASSIFY_CFG = saved_cfg

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
