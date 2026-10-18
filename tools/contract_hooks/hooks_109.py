# -*- coding: utf-8 -*-
"""#109：``^挑战$`` 漏掉带箭头的『挑战→』—— 编队页判据必须两种渲染都认。

## 事实（真机 / 调研）
- 编队页底部【挑战】按钮有**两种渲染**：``挑战`` 与 ``挑战→``（带箭头）。
  真机帧 ``debug/wc_a_set1_back.png`` 上可见箭头；识别调研（
  ``docs/research/recognition-ocr-vs-template.md`` V12）统计 **8/17 帧**带箭头。
- 整串 ``^挑战$`` **不匹配** ``挑战→`` ⇒ 编队页锚点/判据在约**一半**的帧上不成立。
  这不是「识别率抖动」，是**门控有一半概率不成立**。

## 真源 / 派生（本票的「派生」答案，别猜）
- ``assets/resource/pipeline/*.json`` **不是**生成物：ADR-0001 明确「pipeline / interface
  JSON 不被清空、也不被整体生成」，判据仍是**手写**的；仓里**没有**任何 ``gen_*`` 能重跑
  这些 ``expected``（``scene.apply`` 只往 ``next`` 插事件引用，不重写判据）。
- 但 ``scene/page_rules.py`` 的「编队页」判据是**抄自** ``special_dungeon.json::SpecialChallenge``
  （``scene.drift.PAGE_RULE_SOURCES``），并由 ``scene.drift.recognition_drift`` **钉住**：
  ``expected`` 走**子集**、``roi`` 走**相等**。
  ⇒ **真源 = pipeline 节点，投影 = page_rules**；改判据必须**两者一起改**，否则 drift 红。
- ``scene/auto_switch.py::TEAM_PAGE_ANCHORS`` 是**另一处独立**的页面锚点表（不在 drift 里），
  它的**安装态回退快照**在 ``agent/auto_switch_impl.py``（``agent/*`` 不在本票范围 ——
  见 :data:`OUT_OF_SCOPE_PENDING`）。

## 契约
- **T1 两种渲染都判成编队页**：``挑战`` / ``挑战→`` 都要被**页面锚点**（
  :func:`scene.auto_switch.page_is_team`）与**页面判据**（``scene.page_rules``「编队页」）
  同时认下；且**放宽必须封顶**：``再次挑战 / 继续挑战 / 挑战深渊连战EX / 挑战→→ / →挑战``
  仍然一个都不许中（整串锚定，绝不退化成裸「挑战」）。
- **T2 判据单源**：``page_rules``「编队页」仍是 ``SpecialChallenge`` 的**子集**且 ROI 相等
  （复用 :func:`scene.drift._compare_ocr`，不另写第二份比法器）；且**真源自己**两种渲染都认
  —— 否则「投影比真源宽」= 判据没有事实支撑。
- **T3 仓里不再有「活跃的」孤立 ``^挑战$``**：编队页判据三处（两个 py + pipeline 真源节点）
  的**活跃**（非注释、非 docstring）字符串里不许再出现它；仓里**其它**位置的活跃
  ``^挑战$`` 必须是 :data:`OUT_OF_SCOPE_PENDING` 里登记过的角色（**新增文件即红**）。

★为什么 T3 不是「全仓一个都不许有」★：同一个按钮的「点它」判据还散在
``common.json::PubChallenge``、``wuchong.json::WuchongChallengeText``/``WuchongTeamChallenge``、
``phantom.json::PhantomSoloChallenge``、``abyss.json`` 等**别的节点**里 —— 它们**同样**受箭头
问题影响，但各自被 #30 / #71 / #78 / 五重与幻想的守卫钉着（改一处就连带红一片，上一轮正是
这么翻车的）。#109 只收「页面判据」这一层；其余**逐条登记**（见 :data:`OUT_OF_SCOPE_PENDING`），
新冒出来的、没登记的才会当场变红。
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_REL = Path("assets") / "resource" / "pipeline"
SPECIAL_FILE = "special_dungeon.json"
PAGE_NAME = "编队页"

# ---------------------------------------------------------------------------
# 真机文本（720 空间）。10/17 的框取自 #30 已入库的真机帧（单人编队页），箭头版是
# **同一行**把框向右放宽 30px（箭头在标签右侧）。宽度不影响任何结论：两条判据都只问
# 「文字是否整串命中」+「框的可见部分是否落在 ROI 内」，两者都**整框**在 ROI 里。
# ---------------------------------------------------------------------------
TEAM_PAGE_TEXTS: tuple[tuple[str, list[int]], ...] = (
    ("挑战", [297, 1069, 80, 47]),
    ("挑战→", [297, 1069, 110, 47]),
)

#: 反例：整串锚定必须继续**拒收**的文字。放宽成裸「挑战」（或 ``挑战.*``）就会全中。
NEGATIVE_TEXTS: tuple[str, ...] = (
    "再次挑战",
    "继续挑战",
    "挑战深渊连战",
    "挑战深渊连战EX",
    "高难挑战",
    "连续挑战次数",
    "挑战→→",   # 只允许**一个**箭头（`(→)?` 不是 `(→)*`，也不是 `.*`）
    "→挑战",     # 箭头在前 = 另一个控件，不许中
)

#: 「裁剪保读率」阈值（与 ``hooks_37.VISIBLE_MIN`` 同值）：真机 MAA 先裁剪再 OCR。
VISIBLE_MIN = 0.7

#: 被判据禁止的「孤立整串」（运行时拼接，避免本文件自己成为活跃出现 —— 见 :func:`_scan`）。
BLIND = "^挑战" + "$"

#: 编队页判据**三处**：活跃字符串里不许再有 :data:`BLIND`。
PAGE_CRITERIA_FILES: tuple[str, ...] = (
    "scene/page_rules.py",                              # 页面判据注册表（投影）
    "scene/auto_switch.py",                             # 编队页/房间页页面锚点
    (PIPELINE_REL / SPECIAL_FILE).as_posix(),           # 真源节点 SpecialChallenge 所在文件
)

#: ★本票**不改**、但**同样**承载「点编队页挑战」的活跃 ``^挑战$`` —— 逐条登记角色。
#: 语义：**子集门禁**。新文件冒出活跃 ``^挑战$`` → 红；某文件没了 → 照绿（修好了不该罚）。
#: 这些位置被别的票的守卫钉着（改一处连带红一片），#109 只收「页面判据」层。
OUT_OF_SCOPE_PENDING: dict[str, str] = {
    "agent/auto_switch_impl.py":
        "安装态回退快照 _TEAM_PAGE_ANCHORS_SNAPSHOT（agent/* 不在本票范围；"
        "需另票同步，否则装好的产品仍按 ^挑战$ 判编队页）",
    "agent/side_impl.py":
        "PubChallenge 的 phantom/还原两种运行时 override（#30 钉住 ^挑战$ 形态）",
    "assets/resource/pipeline/common.json":
        "公共事件 PubChallenge（通用『点挑战』；与页面判据不同责，见 hooks_37 的同判据豁免）",
    "assets/resource/pipeline/wuchong.json":
        "WuchongChallengeText（OCR 门）/ WuchongTeamChallenge 与共斗房的 what 断言",
    "assets/resource/pipeline/phantom.json":
        "PhantomSoloChallenge / PhantomCoopChallenge 的 what 断言（phantom_act 状态机）",
    "assets/resource/pipeline/abyss.json":
        "深渊单人编队页 Abyss*Challenge 的 what 断言",
    "tools/contract_hooks/hooks_30.py":
        "真机帧模型 + PubChallenge 收窄/还原的逐字断言（#30 的判据来源）",
    "tools/contract_hooks/hooks_78.py":
        "五重真机帧模型里的 what 断言（#78 节拍票）",
    "tools/contract_hooks/hooks_wuchong.py":
        "五重真机帧模型 WuchongActAction 的 what 断言",
}

#: 扫描时跳过的目录（构建物 / 证据 / 依赖）。
_SKIP_DIRS = frozenset({
    ".git", ".slim", "__pycache__", ".venv", "node_modules", "install", "debug",
})

#: 只扫这两类（``.md``/``.txt`` 是散文，本来就当注释看）。
_SUFFIXES = frozenset({".py", ".json", ".jsonc"})

#: 守卫自己 + 本票的测试文件：必然**点名**被禁的那条模式（判据不是它的「活跃使用」）。
_SELF_FILES = frozenset({
    "tools/contract_hooks/hooks_109.py",
    "tools/test_challenge_arrow.py",
})


# ---------------------------------------------------------------------------
# 路径 / 惰性导入（与同目录其它 hooks 同一手法）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for p in (str(REPO_ROOT), str(REPO_ROOT / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)


def _submodule(name: str):
    """取 ``scene.<name>`` **子模块**（别用 ``from scene import <name>``：``scene/__init__``
    把同名**函数**导出到了包上，属性会被遮蔽成函数，拿不到模块）。"""
    _paths()
    import importlib  # noqa: PLC0415

    return importlib.import_module(f"scene.{name}")


def _auto_switch():
    return _submodule("auto_switch")


def _page_rules():
    return _submodule("page_rules")


def _drift():
    _paths()
    import scene.drift as drift  # noqa: PLC0415

    return drift


# ---------------------------------------------------------------------------
# 离线 OCR 求值（只覆盖本票用到的 OCR 型判据；其余类型不静默通过）
# ---------------------------------------------------------------------------
def _visible_fraction(box, roi) -> float:
    """框落在 ROI 内的**面积占比**（真机 MAA 先裁剪再 OCR，框被裁掉就大概率读不出）。"""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return 0.0
    ix0, iy0 = max(x, roi[0]), max(y, roi[1])
    ix1, iy1 = min(x + w, roi[0] + roi[2]), min(y + h, roi[1] + roi[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    return (iw * ih) / float(w * h)


def _ocr_hits(rec, text: str, box) -> bool:
    """一条 OCR recognition 在 ``(text, box)`` 上是否命中（整串正则 + ROI 保读率）。"""
    if not isinstance(rec, dict):
        return False
    if rec.get("type") != "OCR":
        return False
    param = rec.get("param") or {}
    pats = param.get("expected") or []
    if not any(re.search(p, (text or "").strip()) for p in pats):
        return False
    roi = param.get("roi")
    if roi is None:
        return True
    return _visible_fraction(box, roi) >= VISIBLE_MIN


# ---------------------------------------------------------------------------
# T1：两种渲染都判成「编队页」，且放宽封顶
# ---------------------------------------------------------------------------
def _both_renderings_failures() -> list[str]:
    asw = _auto_switch()
    pr = _page_rules()

    try:
        rule = pr.page_rule(PAGE_NAME).recognition
    except KeyError as exc:
        return [f"scene.page_rules 里没有「{PAGE_NAME}」判据：{exc}（判据被删/改名）"]

    msgs: list[str] = []

    # (a) 正例：真机两种文本都必须判成编队页。
    for text, box in TEAM_PAGE_TEXTS:
        if not asw.page_is_team([(text, box)]):
            msgs.append(
                f"页面锚点漏了『{text}』：scene.auto_switch.page_is_team 判否"
                f"（TEAM_PAGE_ANCHORS={asw.TEAM_PAGE_ANCHORS!r} 里必须有兼容箭头的整串正则）"
            )
        if not _ocr_hits(rule, text, box):
            msgs.append(
                f"页面判据漏了『{text}』：scene.page_rules「{PAGE_NAME}」判否"
                f"（expected={(rule.get('param') or {}).get('expected')!r}；"
                f"整串 ^挑战$ 不匹配带箭头的『挑战→』）"
            )

    # (b) 反例：放宽不许过头（裸「挑战」会让「再次挑战 / 继续挑战」全部误命中）。
    probe_box = TEAM_PAGE_TEXTS[0][1]
    for bad in NEGATIVE_TEXTS:
        if asw.page_is_team([(bad, list(probe_box))]):
            msgs.append(
                f"页面锚点放宽过头：『{bad}』被判成{PAGE_NAME}（整串锚定被破坏 —— "
                f"只许容忍**一个**箭头，绝不许退化成裸「挑战」）"
            )
        if _ocr_hits(rule, bad, probe_box):
            msgs.append(f"页面判据放宽过头：『{bad}』命中「{PAGE_NAME}」判据（整串锚定被破坏）")

    # (c) 页面判据自己必须点名叫“编队页底部”，别把别的页的挑战拖进来。
    expected = (rule.get("param") or {}).get("expected") or []
    if not expected:
        msgs.append(f"「{PAGE_NAME}」判据没有 expected（识别条件为空 = 恒不命中）")
    return msgs


def probe_challenge_arrow_page_criteria() -> bool:
    """T1：``挑战`` / ``挑战→`` 都判成编队页（锚点 + 判据两条路）；反例不许误命中。"""
    return _both_renderings_failures() == []


# ---------------------------------------------------------------------------
# T2：判据单源（page_rules ⊆ pipeline 真源，且真源自己两态都认）
# ---------------------------------------------------------------------------
def _single_source_failures(repo_root: Path | None = None) -> list[str]:
    drift = _drift()
    pr = _page_rules()

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    source = drift.PAGE_RULE_SOURCES.get(PAGE_NAME)
    if source is None:
        return [f"scene.drift.PAGE_RULE_SOURCES 里没有「{PAGE_NAME}」的来源登记（判据无真源）"]
    fname, node_name = source
    where = f"{fname}::{node_name}"

    path = root / PIPELINE_REL / fname
    try:
        data = drift._load_jsonc(path)
    except (OSError, ValueError) as exc:
        return [f"读不到判据真源 {where}：{exc}"]

    node = data.get(node_name) if isinstance(data, dict) else None
    src = node.get("recognition") if isinstance(node, dict) else None
    if not isinstance(src, dict):
        return [f"判据真源 {where} 不存在或没有 recognition（单源断了）"]

    try:
        page = pr.page_rule(PAGE_NAME).recognition
    except KeyError as exc:
        return [f"scene.page_rules 里没有「{PAGE_NAME}」判据：{exc}"]

    # 复用 drift 的比法器（子集 + ROI 相等），不另写第二份语义。
    msgs: list[str] = list(drift._compare_ocr(PAGE_NAME, page, src, where))

    # 真源**自己**也必须两种渲染都认：否则「投影比真源宽」= 判据没有事实支撑。
    for text, box in TEAM_PAGE_TEXTS:
        if not _ocr_hits(src, text, box):
            msgs.append(
                f"判据真源 {where} 不认『{text}』"
                f"（expected={(src.get('param') or {}).get('expected')!r}）—— "
                f"page_rules 抄的就是它，它不认就等于判据比事实宽"
            )
    return msgs


def probe_challenge_single_source() -> bool:
    """T2：page_rules「编队页」⊆ ``SpecialChallenge`` 且 ROI 相等；真源自己两态都认。"""
    return _single_source_failures() == []


# ---------------------------------------------------------------------------
# T3：仓里不再有「活跃的」孤立 ^挑战$
# ---------------------------------------------------------------------------
def _active_py_strings(path: Path) -> list[str]:
    """Python 文件里**活跃**的字符串常量（注释天然不在 AST 里；docstring 排除）。

    为什么走 AST：``^挑战$`` 在本票里必然出现在**注释/docstring**中（说明「为什么不这样写」），
    那些不是「使用」；手写去注释的状态机会被 ``#`` 出现在字符串里骗到。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    docstrings.add(id(value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _active_json_text(path: Path) -> str:
    """JSONC 文件去掉 ``//`` ``/* */`` 注释后的文本（字符串原样保留）。"""
    return _drift()._strip_jsonc(path.read_text(encoding="utf-8"))


def _active_count(path: Path) -> int:
    if path.suffix == ".py":
        return sum(text.count(BLIND) for text in _active_py_strings(path))
    return _active_json_text(path).count(BLIND)


def _scan(root: Path) -> dict[str, int]:
    """扫盘：``{相对路径: 活跃 ^挑战$ 个数}``（只含 >0）。"""
    hits: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() not in _SUFFIXES:
            continue
        rel_posix = rel.as_posix()
        if rel_posix in _SELF_FILES:
            continue
        try:
            n = _active_count(path)
        except (OSError, SyntaxError, ValueError):
            continue
        if n:
            hits[rel_posix] = n
    return hits


def _no_blind_anchor_failures(root: Path | None = None) -> list[str]:
    base = Path(root) if root is not None else REPO_ROOT
    hits = _scan(base)
    msgs: list[str] = []

    # (a) 编队页判据三处：活跃出现必须为 0（注释/docstring 里的说明不受限）。
    for rel in PAGE_CRITERIA_FILES:
        if hits.get(rel):
            msgs.append(
                f"{rel} 仍有 {hits[rel]} 处**活跃**的 `{BLIND}` —— "
                f"编队页判据必须写成兼容箭头的整串（``^挑战(→)?$``），"
                f"否则带箭头的『挑战→』帧上判据不成立（#109）"
            )

    # (b) 其余位置：必须是登记过的角色；新冒出来的没登记 → 红（逼人先判断再改）。
    for rel, n in sorted(hits.items()):
        if rel in PAGE_CRITERIA_FILES or rel in OUT_OF_SCOPE_PENDING:
            continue
        msgs.append(
            f"{rel} 出现 {n} 处活跃的 `{BLIND}`，但没在 hooks_109.OUT_OF_SCOPE_PENDING 里"
            f"登记角色 —— 先判断它是不是**编队页判据**（是就必须兼容箭头），"
            f"再登记理由；不许悄悄新增一个只会认『挑战』的判据"
        )
    return msgs


def probe_challenge_no_blind_anchor() -> bool:
    """T3：编队页判据三处无活跃 ``^挑战$``；仓里其它活跃位置必须逐条登记过角色。"""
    return _no_blind_anchor_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        "challenge-arrow-page-criteria",
        "#109",
        "编队页判据两种渲染都认：`挑战` / `挑战→` 都判成编队页（页面锚点 + 页面判据两条路）；"
        "反例 再次挑战/继续挑战/挑战深渊连战EX/挑战→→/→挑战 一个都不许中（整串锚定不退化成裸「挑战」）",
        probe_challenge_arrow_page_criteria,
    ),
    (
        "challenge-single-source",
        "#109",
        "判据单源：scene.page_rules「编队页」仍 ⊆ special_dungeon.json::SpecialChallenge 且 ROI 相等"
        "（复用 scene.drift 的比法器），且真源自己两种渲染都认",
        probe_challenge_single_source,
    ),
    (
        "challenge-no-blind-anchor",
        "#109",
        "仓里不再有活跃的孤立 ^挑战$：编队页判据三处（page_rules / auto_switch / SpecialChallenge）为 0；"
        "其它活跃位置必须逐条登记角色，新增未登记即红",
        probe_challenge_no_blind_anchor,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（≥2；本票做了 4 条）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    asw = _auto_switch()
    pr = _page_rules()

    print("hooks_109 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_challenge_arrow_page_criteria()
        and probe_challenge_single_source()
        and probe_challenge_no_blind_anchor()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三个守卫全绿")
    if not green:
        for m in (
            _both_renderings_failures()
            + _single_source_failures()
            + _no_blind_anchor_failures()
        ):
            print(f"      - {m}")
        return False

    checks: list[bool] = []
    real_anchors = asw.TEAM_PAGE_ANCHORS
    real_rules = list(pr.PAGE_RULES)

    try:
        # ① 只把「页面锚点」改回 ^挑战$（= 只修了一半，正是上一轮的形态）→ T1 红
        asw.TEAM_PAGE_ANCHORS = tuple(
            r"^挑战$" if p == r"^挑战(→)?$" else p for p in real_anchors
        )
        m = _both_renderings_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 只把 page_is_team 的锚点改回 ^挑战$（只改一处）"
            f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
        asw.TEAM_PAGE_ANCHORS = real_anchors

        # ② 只把「页面判据」改回 ^挑战$（另一处漏了）→ T1/T2/T3 红
        idx = next(i for i, r in enumerate(real_rules) if r.name == PAGE_NAME)
        pr.PAGE_RULES[idx] = type(real_rules[idx])(
            PAGE_NAME,
            {"type": "OCR", "param": {"expected": ["^挑战$"], "roi": [180, 1000, 400, 180]}},
            "破坏实验",
        )
        m = _both_renderings_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 只把 page_rules「编队页」判据改回 ^挑战$"
            f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
        pr.PAGE_RULES[idx] = real_rules[idx]

        # ③ 把 pipeline 真源改回 ^挑战$（投影改对了、真源没改 = drift 会红的那种）→ T2 红
        tmp = Path(tempfile.mkdtemp(prefix="hooks109_"))
        try:
            target = tmp / PIPELINE_REL
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / PIPELINE_REL / SPECIAL_FILE, target / SPECIAL_FILE)
            node_path = target / SPECIAL_FILE
            text = node_path.read_text(encoding="utf-8")
            node_path.write_text(
                text.replace(
                    '"expected": ["^挑战(→)?$"]', '"expected": ["^挑战$"]', 1
                ),
                encoding="utf-8",
                newline="",
            )
            m = _single_source_failures(tmp)
            red = len(m) > 0
            print(
                f"  [{'PASS' if red else 'FAIL'}] 把真源 SpecialChallenge 改回 ^挑战$（投影比真源宽）"
                f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
            )
            checks.append(red)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ④ 放宽过头（裸「挑战」）→ T1 反例红（证明「兼容箭头」没变成「什么都认」）
        asw.TEAM_PAGE_ANCHORS = (r"挑战",) + tuple(
            p for p in real_anchors if p != r"^挑战(→)?$"
        )
        m = _both_renderings_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把锚点放宽成裸「挑战」"
            f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        asw.TEAM_PAGE_ANCHORS = real_anchors
        pr.PAGE_RULES[:] = real_rules

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
