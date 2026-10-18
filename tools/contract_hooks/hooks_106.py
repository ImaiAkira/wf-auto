# -*- coding: utf-8 -*-
"""#106：领主战 / 讨伐【难度静态数据】—— 结构 · 证伪 · 采集一致性 · 运行期不探测。

seam：``scene.lords``（**难度静态数据真源**：M / 解锁链 / 认证文本 / 证据）
      ↔ ``tools/gen_lord_registry.py``（一次性采集 CLI，假 OCR 可注入）
      ↔ ``assets/data/lords.json``（``scene.lords`` 的投影）
      ↔ ``scene.lord_battle``（成员花名册，本票**只读**）。

四个挂点
--------
1. ``lord-registry-schema``
   schema 校验：必填字段、``max_tiers`` 正整数（或 ``None`` 占位）、
   **解锁链首尾与 M 一致**（``len(tier_chain) == max_tiers``；链首 ∈ {初级, 中级}；
   链尾 = 链上最高档）、``verified`` 与证据一致（``verified`` ⇒ 有证据 ∧ 证据路径**在仓内真实存在**
   ∧ 链完整 ∧ 每档有行名；``verified=False`` ⇒ ``needs`` 非空）、``max_tiers_verified`` ⇒ ``max_tiers`` 非空、
   slug 格式与唯一性、行名集合 == 花名册（46）、``kind`` ↔ 子族一致，
   以及**证伪回归钉**（:data:`FALSIFIED`：旧静态表在 4 行里错了 3 行，另加 无猾机兵 M=5）。
2. ``lord-registry-no-supported-set``
   **禁止「支持难度集」字段**：出现即红。检查三条路：数据类字段名 / 源码里的**活跃**标识符与字符串
   （AST，注释与 docstring 不算）/ JSON 键名；外加「任何字段值不得是 set/frozenset」（那正是被证伪的形状）。
3. ``lord-registry-cli-consistent``
   采集 CLI 的**产出一致性**：用内嵌假 OCR 重跑一遍 ``collect()``，要求
   ``scene.lords.LORDS`` 逐条相等、``render_block`` 与标记段**逐字**相等、
   ``render_json`` 与 ``assets/data/lords.json`` **逐字**相等。
4. ``lord-collect-cli-not-on-runtime-path``
   「运行期不探测」的静态证明：
   (a) 业务路径（``agent/`` + ``scene/``）里 ``discover_difficulties`` 的出现点**逐条登记**在
       :data:`RUNTIME_PROBES` 里（新冒出未登记的 → 红并列出位置）；本票**不改**业务调用，
       所以这条登记的是**现状与债**，不是「已经干净」；
   (b) 没有任何运行期模块 import 采集 CLI（``agent/``/``scene/`` 的 import + ``assets/resource/pipeline`` 的文本）；
   (c) ``scene/lords.py`` 的顶层 import 只允许 stdlib + ``scene.config``（静态数据**够不到**探测器）；
   (d) CLI 的顶层 import 不许出现 ``maa`` / ``agent`` / ``numpy`` / ``PIL`` / ``subprocess`` / ``socket``
       （它不在运行期路径上，也不在 import 期连设备）。

★诚实边界★
* 本守卫**不重跑** MAA OCR、**不碰设备**：假 OCR 用的是 ``tools/gen_lord_registry.FRAME_OCR``（逐条内嵌的真机帧摘录）。
  所以它证的是「**仓内的数据 == 仓内那几张帧的读数**」，不是「今天真机还是这样」——
  后者要靠 ``--live`` 重采 + 第二账号复算（见 ``scene/lords.py`` 的 ``needs``）。
* 本守卫**不校验**「某账号能打哪几档」：那是账号状态，离线永远比不了
  （``scene/drift.py`` 已把这条明确列为不校验）。能校验的只有「结构 + 证据存在性 + 与帧的读数一致」。

prove-red（``python tools\\contract_hooks\\hooks_106.py``，6 条破坏实验）
----------------------------------------------------------------------
① 给已验证条目配一条**不存在的证据路径** → schema 红；
② 把 ``红嫉机兵`` 的 M 改成 3（链长 4）→ 「链长与 M 不一致」红；
③ 给源码塞一个 ``支持难度集`` 字段 + 给 JSON 塞同名键 → 禁止字段红；
④ 把 ``八岐大蛇讨伐`` 的 M 改回旧静态表的 3 → 证伪回归钉红；
⑤ 从假 OCR 里删掉一行（``妖狐中级``）→ 采集产出一致性红；
⑥ 在业务路径上新增一处未登记的 ``discover_difficulties`` → 「运行期不探测」红。
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

HOOK_ID_SCHEMA = "lord-registry-schema"
HOOK_ID_NO_SET = "lord-registry-no-supported-set"
HOOK_ID_CLI = "lord-registry-cli-consistent"
HOOK_ID_RUNTIME = "lord-collect-cli-not-on-runtime-path"

# ---------------------------------------------------------------------------
# 被证伪的旧静态表（★本票的立身之本★）
# ---------------------------------------------------------------------------
# (旧 ``支持难度集`` 的档数, 仓内帧实读的 M)。来源：
#   * docs/research/lord-battle-difficulty-registry.md §2.4（同一帧 4 行里 3 行不符）
#   * tools/frames/lord_page_tab_lord.png（艾基尔·嫉妒 1/4、背鳍三兄弟 1/4、八岐大蛇 4/4）
#   * tools/frames/lord_page_tab_joss.png（无猾机兵 5/5 —— 旧表记 4 档且含 地狱级）
# 断言 `scene/lords.py` 的 M **等于帧实读值**、且若链已采则长度不等于旧档数
# （即：绝不把「某账号当时的可见档数」当成 M）。
FALSIFIED: dict[str, tuple[int, int]] = {
    "艾基尔·嫉妒讨伐": (1, 4),
    "背鳍三兄弟讨伐": (2, 4),
    "八岐大蛇讨伐": (3, 4),
    "无猾机兵": (4, 5),
}

#: 禁止的字段名（「支持难度集」的各种马甲）。命中即红。
FORBIDDEN_FIELDS: tuple[str, ...] = (
    "支持难度集",
    "难度集",
    "difficulties",
    "available_difficulties",
    "supported_difficulties",
    "available_tiers",
    "allowed_tiers",
    "supported_tiers",
    "tiers",
)

#: 「运行期探测」的唯一现存符号。★本票不改业务调用★：这里登记的是**现状与债**，
#: 语义是**子集门禁** —— 新冒出来未登记的出现点 → 红并列出位置；变少 → 照绿（修好了不该罚）。
RUNTIME_PROBES: dict[str, int] = {
    # #39 的运行时发现：``def discover_difficulties`` + ``classify_detail_difficulty`` 里的一次调用
    "agent/side_impl.py": 2,
}

#: 运行期模块**不许** import 采集 CLI（模块名出现即视为接线）。
COLLECT_CLI_MODULE = "gen_lord_registry"

#: ``scene/lords.py`` 顶层 import 的白名单（静态数据必须够不到 agent / 探测器）。
LORDS_ALLOWED_IMPORTS: frozenset[str] = frozenset({"__future__", "dataclasses", "typing", "scene.config", ".config"})

#: CLI 顶层 import 的**黑名单**（出现即说明它可能在 import 期连设备/进运行期）。
CLI_FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {"maa", "agent", "numpy", "PIL", "subprocess", "socket", "adb", "requests", "scene.lord_battle"}
)

_SKIP_DIRS = frozenset({".git", ".slim", "__pycache__", ".venv", "node_modules", "install", "debug", "deps"})


# ---------------------------------------------------------------------------
# 惰性导入（与同目录其它 hooks 同一手法：挂点模块必须在 import 期保持轻）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR)):
        if path not in sys.path:
            sys.path.append(path)


def _lords():
    """``scene.lords`` **子模块**（用 import_module：``scene/__init__`` 会遮蔽同名属性）。"""
    _paths()
    return importlib.import_module("scene.lords")


def _gen():
    """采集 CLI（模块名以 ``g`` 开头，避免被 pytest 收成测试）。"""
    _paths()
    return importlib.import_module("gen_lord_registry")


def _config():
    _paths()
    return importlib.import_module("scene.config")


def _roster() -> tuple:
    _paths()
    lord_battle = importlib.import_module("scene.lord_battle")
    return tuple(lord_battle.LORD_BATTLE.members)


def _difficulties() -> tuple[str, ...]:
    return tuple(_config().DIFFICULTIES)


# ---------------------------------------------------------------------------
# 1. schema
# ---------------------------------------------------------------------------
def _schema_failures(entries=None, roster=None) -> list[str]:
    """schema 校验（空列表 = 绿）。``entries``/``roster`` 可注入（破坏实验用）。"""
    lords_mod = _lords()
    difficulties = _difficulties()
    entries = tuple(lords_mod.LORDS) if entries is None else tuple(entries)
    members = _roster() if roster is None else tuple(roster)

    msgs: list[str] = []

    seen_slug: dict[str, int] = {}
    seen_row: dict[str, int] = {}
    for idx, entry in enumerate(entries):
        where = f"第 {idx} 条（slug={entry.slug!r}）"

        # (a) 必填字段
        for field_name in ("slug", "kind", "row_name", "row_regex", "max_tiers_source"):
            value = getattr(entry, field_name)
            if not isinstance(value, str) or not value.strip():
                msgs.append(f"{where}：必填字段 {field_name} 为空 —— 每条登记都必须可单独读懂")
        if entry.kind not in lords_mod.KINDS:
            msgs.append(f"{where}：kind={entry.kind!r} 不在 {lords_mod.KINDS} 里")
        if entry.slug != f"{entry.kind}/{entry.row_name}":
            msgs.append(
                f"{where}：slug 必须是 `kind/行名`（{entry.kind}/{entry.row_name}），"
                f"否则账本 key 与成员对不上（slug 一改，老账本全部失配）"
            )

        # (b) slug / 行名唯一
        if entry.slug in seen_slug:
            msgs.append(f"{where}：slug 与第 {seen_slug[entry.slug]} 条重复 —— 账本 key 必须唯一")
        else:
            seen_slug[entry.slug] = idx
        if entry.row_name in seen_row:
            msgs.append(f"{where}：行名与第 {seen_row[entry.row_name]} 条重复（两条登记抢同一个点击锚点）")
        else:
            seen_row[entry.row_name] = idx

        # (c) M 必须是正整数（或 None = 未采集）
        if entry.max_tiers is not None and (
            not isinstance(entry.max_tiers, int) or isinstance(entry.max_tiers, bool) or entry.max_tiers <= 0
        ):
            msgs.append(f"{where}：max_tiers={entry.max_tiers!r}，M 必须是正整数或 None")
        if entry.max_tiers_source not in lords_mod.MAX_TIERS_SOURCES:
            msgs.append(
                f"{where}：max_tiers_source={entry.max_tiers_source!r} 不在 "
                f"{lords_mod.MAX_TIERS_SOURCES} 里"
            )
        elif entry.max_tiers_source == lords_mod.SOURCE_UNKNOWN and entry.max_tiers is not None:
            msgs.append(f"{where}：source=unknown 却给了 max_tiers={entry.max_tiers} —— 来源必须诚实")
        elif entry.max_tiers_source != lords_mod.SOURCE_UNKNOWN and entry.max_tiers is None:
            msgs.append(
                f"{where}：source={entry.max_tiers_source!r} 却没有 max_tiers —— 来源指向了一个不存在的值"
            )
        if entry.max_tiers_verified and entry.max_tiers is None:
            msgs.append(f"{where}：max_tiers_verified=True 但 max_tiers=None —— 验证标志与数据矛盾")

        # (d) 解锁链：成员 ⊂ 词表、严格升序、首尾与 M 一致
        unknown = [d for d in entry.tier_chain if d not in difficulties]
        if unknown:
            msgs.append(
                f"{where}：解锁链里有不存在的难度 {unknown}（词表 {difficulties}）"
                f" —— 难度词表的唯一真源是 scene/config.py 的 DIFFICULTIES"
            )
        else:
            order = [difficulties.index(d) for d in entry.tier_chain]
            if order != sorted(order) or len(set(entry.tier_chain)) != len(entry.tier_chain):
                msgs.append(
                    f"{where}：解锁链 {entry.tier_chain} 不是「升序（低档→高档）」"
                    f"（词表顺序 {difficulties}）—— 链的语义是逐档递进，顺序错了整条链就错了"
                )
            if entry.tier_chain:
                if entry.max_tiers is None:
                    msgs.append(
                        f"{where}：链已采到 {len(entry.tier_chain)} 档，但 max_tiers=None"
                        f" —— 链长度必须能与 M 对账（缺 M 就不要写完整链）"
                    )
                elif len(entry.tier_chain) != entry.max_tiers:
                    msgs.append(
                        f"{where}：链长 {len(entry.tier_chain)} != M {entry.max_tiers}"
                        f" —— 「解锁链首尾与 M 一致」要求 len(tier_chain) == max_tiers"
                        f"（缺的档要么补行名，要么把链留空）"
                    )
                if entry.tier_chain[0] not in lords_mod.ENTRY_DIFFICULTIES:
                    msgs.append(
                        f"{where}：链首（起始档）{entry.tier_chain[0]!r} 不在 "
                        f"{lords_mod.ENTRY_DIFFICULTIES} 里 —— 真机起始档只见过这两档"
                        f"（中级 / 初级仅 维·索拉斯讨伐）"
                    )
                if entry.tier_chain[-1] != max(entry.tier_chain, key=difficulties.index):
                    msgs.append(f"{where}：链尾 {entry.tier_chain[-1]!r} 不是链上最高档 —— 链序坏了")
                if entry.entry_difficulty != entry.tier_chain[0] or entry.top_difficulty != entry.tier_chain[-1]:
                    msgs.append(f"{where}：entry_difficulty / top_difficulty 派生值与链首尾不一致")

        # (e) 逐档行名
        label_keys = [d for d, _lab in entry.row_labels]
        if len(set(label_keys)) != len(label_keys):
            msgs.append(f"{where}：row_labels 有重复难度 {label_keys}")
        bad = [d for d in label_keys if d not in difficulties]
        if bad:
            msgs.append(f"{where}：row_labels 里有不存在的难度 {bad}")
        if entry.tier_chain:
            extra = [d for d in label_keys if d not in entry.tier_chain]
            if extra:
                msgs.append(f"{where}：row_labels 含链上没有的档 {extra} —— 行名与链必须对得上")
        for difficulty, label in entry.row_labels:
            if not label.endswith(difficulty):
                msgs.append(
                    f"{where}：行名 {label!r} 不以难度 {difficulty!r} 结尾"
                    f" —— 详情页行名 = 前缀 + 难度名，认错档会打错"
                )
            if entry.row_prefix is None:
                msgs.append(f"{where}：有逐档行名却没有 row_prefix（认证文本缺失）")
            elif not label.startswith(entry.row_prefix):
                msgs.append(
                    f"{where}：行名 {label!r} 不以认证前缀 {entry.row_prefix!r} 开头 —— 前缀登记错了"
                )
        if entry.row_prefix is not None and not entry.row_prefix.strip():
            msgs.append(f"{where}：row_prefix 是空串（未实测请写 None）")

        # (f) verified 与证据一致 ★
        if entry.verified:
            if not entry.evidence:
                msgs.append(f"{where}：verified=True 但 evidence 为空 —— 「凭什么」必须写出来")
            if not entry.max_tiers_verified:
                msgs.append(f"{where}：verified=True 要求 max_tiers_verified=True（M 都没验证谈不上全验证）")
            if entry.max_tiers is None or len(entry.tier_chain) != entry.max_tiers:
                msgs.append(f"{where}：verified=True 要求链完整（len(tier_chain) == max_tiers）")
            labelled = {d for d, _lab in entry.row_labels}
            missing = [d for d in entry.tier_chain if d not in labelled]
            if missing:
                msgs.append(f"{where}：verified=True 但 {missing} 没有逐档行名（认证文本不全）")
        elif not entry.needs:
            msgs.append(
                f"{where}：verified=False 时 needs 必须写清「还缺什么」"
                f" —— 本仓库吃过「转述式已验证」的亏（docs/spec/wuchong-spec.md:200）"
            )

        # (g) 证据路径必须真实存在（补上「注释里写着来源、仓里没有」的老洞）
        for item in entry.evidence:
            path_part, _, note = item.partition("|")
            if not note:
                msgs.append(
                    f"{where}：证据串 {item!r} 没有 `|` 后的读数摘录"
                    f"（格式 `<仓库相对路径>|<读数/时间/score>`）"
                )
            candidate = Path(path_part)
            if not candidate.is_absolute():
                candidate = REPO_ROOT / candidate
            if not candidate.is_file():
                msgs.append(
                    f"{where}：证据 {path_part!r} 在仓库里**不存在** —— "
                    f"verified 的证据必须是仓内可复核的文件（这是 #32 时代最大的结构缺陷）"
                )

    # (h) 花名册一致（防两份成员表打架）
    names = {entry.row_name for entry in entries}
    roster_names = {m.行名 for m in members}
    if names != roster_names:
        msgs.append(
            f"花名册守卫：scene/lords.py 的成员集与 scene/lord_battle 不一致 —— "
            f"多={sorted(names - roster_names)} 缺={sorted(roster_names - names)}"
            f"（新增成员必须补一条登记，哪怕只是 pending 占位）"
        )
    for member in members:
        entry = next((e for e in entries if e.row_name == member.行名), None)
        if entry is None:
            continue
        want = lords_mod.SUBFAMILY_BY_KIND.get(entry.kind)
        if want != member.子族:
            msgs.append(
                f"{entry.slug}：kind={entry.kind!r} 对应子族 {want!r}，但花名册里它在 {member.子族!r}"
            )

    # (i) ★证伪回归钉★：旧静态表的档数不得回流
    by_name = {entry.row_name: entry for entry in entries}
    for row_name, (old_tiers, frame_m) in FALSIFIED.items():
        entry = by_name.get(row_name)
        if entry is None:
            msgs.append(f"证伪回归：{row_name!r} 的登记被删了 —— 该行是「静态表必然出错」的现场证据")
            continue
        if entry.max_tiers != frame_m:
            msgs.append(
                f"证伪回归：{row_name!r} 的 M 应为 {frame_m}（列表页 `通关数 N/M` 实读），"
                f"实际 {entry.max_tiers} —— 旧静态表记的是 {old_tiers} 档，"
                f"那是「某账号可见档数」，不是 M（docs/research/lord-battle-difficulty-registry.md §2.4）"
            )
        if entry.tier_chain and len(entry.tier_chain) == old_tiers:
            msgs.append(
                f"证伪回归：{row_name!r} 的链长 {len(entry.tier_chain)} 恰等于旧静态表的 {old_tiers} 档"
                f" —— 疑似把「账号可见集」当成了全集"
            )

    return msgs


def probe_lord_registry_schema() -> bool:
    """#106：难度静态数据的 schema / 链 / 证据 / 花名册 / 证伪回归全部合法。"""
    return _schema_failures() == []


# ---------------------------------------------------------------------------
# 2. 禁止「支持难度集」字段
# ---------------------------------------------------------------------------
_FORBIDDEN_REASON = (
    "「每个领主支持哪些难度」是**账号进度**不是领主属性：同一成员（红嫉机兵）在清关账号 4 档、"
    "早期账号只有 中级（tools/frames/lord_detail_redjoss_{cleared,early}.png），"
    "而同一帧列表页证伪了整张旧表 —— 4 行里 3 行不符（艾基尔·嫉妒 1/4、背鳍三兄弟 1/4、"
    "八岐大蛇 4/4，见 docs/research/lord-battle-difficulty-registry.md §2.4）。"
    "要存只能存 M（总档数）+ 解锁链 + 认证文本；判「本账号能打哪档」请读列表页 `通关数 N/M`。"
)


def _active_py_names_and_strings(path: Path) -> tuple[list[str], list[str]]:
    """Python 文件里**活跃**的标识符（Name/Attribute/关键字参数/赋值目标）与字符串常量。

    注释天然不在 AST 里；docstring 显式排除 —— 本仓库的纪律是把「为什么不这样写」写在注释/
    docstring 里，那些不是「使用」（同一手法见 ``hooks_109._active_py_strings``）。
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

    names: list[str] = []
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
            # 装饰器里的符号也是「活跃使用」
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.Name):
                        names.append(sub.id)
                    elif isinstance(sub, ast.Attribute):
                        names.append(sub.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.append(node.arg)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                strings.append(node.value)
    return names, strings


def _scan_forbidden(obj, trail: str = "$") -> list[str]:
    """递归扫 JSON-ish 结构的**键名**。"""
    hits: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key in FORBIDDEN_FIELDS:
                hits.append(f"{trail}.{key}")
            hits.extend(_scan_forbidden(value, f"{trail}.{key}"))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            hits.extend(_scan_forbidden(value, f"{trail}[{idx}]"))
    return hits


def _forbidden_failures(source_text: str | None = None, json_text: str | None = None, entries=None) -> list[str]:
    """禁止「支持难度集」字段（数据类 / 源码 / JSON / 值形状四条路）。"""
    lords_mod = _lords()
    msgs: list[str] = []

    # (a) 数据类字段名
    field_names = {f.name for f in dataclasses.fields(lords_mod.Lord)}
    bad_fields = sorted(field_names & set(FORBIDDEN_FIELDS))
    if bad_fields:
        msgs.append(f"scene.lords.Lord 出现了禁止字段 {bad_fields} —— {_FORBIDDEN_REASON}")

    # (b) 任何字段值不得是 set/frozenset（那正是「集合」形状；链必须是有序 tuple）
    entries = tuple(lords_mod.LORDS) if entries is None else tuple(entries)
    for entry in entries:
        for field in dataclasses.fields(entry):
            value = getattr(entry, field.name)
            if isinstance(value, (set, frozenset)):
                msgs.append(
                    f"{entry.slug}：字段 {field.name} 的值是 {type(value).__name__}（集合）"
                    f" —— 集合正是被证伪的「支持难度集」形状；有序事实请用 tuple"
                )

    # (c) 源码里的活跃标识符 / 字符串
    if source_text is None:
        source_path = REPO_ROOT / "scene" / "lords.py"
        source_text = source_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        msgs.append(f"scene/lords.py 语法错误，无法做「禁止字段」检查：{exc}")
    else:
        names = [
            node.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute))
            and (getattr(node, "id", None) or getattr(node, "attr", None)) in FORBIDDEN_FIELDS
        ]
        kwargs = [
            node.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.keyword) and node.arg in FORBIDDEN_FIELDS
        ]
        if names or kwargs:
            msgs.append(
                f"scene/lords.py 里出现**活跃**的禁止标识符 {sorted(set(names + kwargs))} "
                f"—— {_FORBIDDEN_REASON}"
            )
        # 字符串常量里出现「支持难度集」= 有人在做集合映射（docstring 已排除）
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in FORBIDDEN_FIELDS
        ]
        if literals:
            msgs.append(f"scene/lords.py 的活跃字符串里出现 {sorted(set(literals))} —— {_FORBIDDEN_REASON}")

    # (d) 投影 JSON 的键名
    if json_text is None:
        json_path = REPO_ROOT / "assets" / "data" / "lords.json"
        json_text = json_path.read_text(encoding="utf-8") if json_path.is_file() else "{}"
    try:
        payload = json.loads(json_text)
    except ValueError as exc:
        msgs.append(f"assets/data/lords.json 不是合法 JSON：{exc}")
    else:
        hits = _scan_forbidden(payload)
        if hits:
            msgs.append(f"assets/data/lords.json 出现禁止键 {hits} —— {_FORBIDDEN_REASON}")

    return msgs


def probe_lord_registry_no_supported_set() -> bool:
    """#106：难度静态数据里**没有**「支持难度集」字段（出现即红）。"""
    return _forbidden_failures() == []


# ---------------------------------------------------------------------------
# 3. 采集 CLI 的产出一致性
# ---------------------------------------------------------------------------
def _consistency_failures(collected=None) -> list[str]:
    """假 OCR 重跑采集 → 与 ``scene/lords.py`` / ``assets/data/lords.json`` 逐字一致。"""
    gen = _gen()
    lords_mod = _lords()
    msgs: list[str] = []

    try:
        fresh = tuple(gen.collect()) if collected is None else tuple(collected)
    except Exception as exc:  # noqa: BLE001 - 采集炸了本身就是红
        return [f"用假 OCR 重跑采集失败：{exc!r}"]

    # (a) 假 OCR 真的覆盖了全部登记帧（否则「一致」是碰巧）
    corpus = gen.FRAME_OCR
    missing_frames = [frame for frame in gen.FRAMES if frame not in corpus]
    if missing_frames:
        msgs.append(f"假 OCR 语料缺帧 {missing_frames} —— 采集一致性失去意义")
    for frame in gen.DETAIL_FRAMES:
        if not (REPO_ROOT / frame).is_file():
            msgs.append(f"详情页帧 {frame!r} 不在仓里 —— 证据与语料都失去了对照物")
    for frame in gen.LIST_FRAMES:
        if not (REPO_ROOT / frame).is_file():
            msgs.append(f"列表页帧 {frame!r} 不在仓里")

    # (b) 数据逐条相等
    if tuple(lords_mod.LORDS) != fresh:
        msgs.append(f"scene/lords.py 的 LORDS 与重跑结果不一致（仓内 {len(lords_mod.LORDS)} / 重跑 {len(fresh)} 条）")
        fresh_by_slug = {entry.slug: entry for entry in fresh}
        for entry in lords_mod.LORDS:
            other = fresh_by_slug.get(entry.slug)
            if other is None:
                msgs.append(f"  重跑结果里没有 {entry.slug!r}")
                continue
            for field in dataclasses.fields(entry):
                disk = getattr(entry, field.name)
                now = getattr(other, field.name)
                if disk != now:
                    msgs.append(f"  {entry.slug}.{field.name}：仓内 {disk!r} != 重跑 {now!r}")
        for slug in sorted(set(fresh_by_slug) - {e.slug for e in lords_mod.LORDS}):
            msgs.append(f"  重跑多出 {slug!r}（仓内没有）")

    # (c) 标记段逐字相等
    source = (REPO_ROOT / "scene" / "lords.py").read_text(encoding="utf-8")
    try:
        on_disk_block = gen.read_block(source)
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"读不到 scene/lords.py 的标记段：{exc!r}")
    else:
        rendered = gen.render_block(fresh)
        if on_disk_block.rstrip("\n") != rendered.rstrip("\n"):
            msgs.append(
                "scene/lords.py 标记段 != 重跑渲染的文本 —— 手改过数据，或改了采集逻辑没重跑 --write"
            )

    # (d) 投影 JSON 逐字相等
    json_path = REPO_ROOT / "assets" / "data" / "lords.json"
    if not json_path.is_file():
        msgs.append("assets/data/lords.json 不存在 —— 投影必须由 --write 产出并提交")
    else:
        on_disk = json_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if on_disk.rstrip("\n") != gen.render_json(fresh).rstrip("\n"):
            msgs.append("assets/data/lords.json != 重跑渲染的投影（手改过 / 没重跑 --write）")

    return msgs


def probe_lord_registry_cli_consistent() -> bool:
    """#106：采集 CLI（假 OCR）重跑结果 == scene/lords.py == assets/data/lords.json。"""
    return _consistency_failures() == []


# ---------------------------------------------------------------------------
# 4. 运行期不探测
# ---------------------------------------------------------------------------
def _iter_py(base: Path, root: Path):
    """遍历 ``base`` 下的 ``.py``，产出 ``(相对 root 的 posix 路径, Path)``（跳过构建物目录）。"""
    for path in base.rglob("*.py"):
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in _SKIP_DIRS for part in parts):
            continue
        yield path.relative_to(root).as_posix(), path


def _collect_probe_sites(root: Path, symbol: str) -> dict[str, int]:
    """扫 ``agent/`` + ``scene/`` 的**活跃**代码，统计 ``symbol`` 出现次数（文件 -> 次数）。"""
    sites: dict[str, int] = {}
    for sub in ("agent", "scene"):
        base = root / sub
        if not base.is_dir():
            continue
        for rel, path in _iter_py(base, root):
            try:
                names, strings = _active_py_names_and_strings(path)
            except (OSError, SyntaxError):
                continue
            count = sum(1 for name in names if name == symbol) + sum(
                1 for text in strings if text == symbol
            )
            if count:
                sites[rel] = count
    return sites


def _cli_import_failures(root: Path) -> list[str]:
    """(b)(c)(d)：运行期模块不许 import 采集 CLI；静态数据够不到探测器；CLI 不连设备。"""
    msgs: list[str] = []

    # (b) agent/ + scene/ 的 import 里不许出现采集 CLI
    for sub in ("agent", "scene"):
        base = root / sub
        if not base.is_dir():
            continue
        for rel, path in _iter_py(base, root):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if COLLECT_CLI_MODULE in alias.name:
                            module = alias.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if COLLECT_CLI_MODULE in node.module:
                        module = node.module
                if module:
                    msgs.append(
                        f"{rel}：import 了 {module!r} —— 采集 CLI 是**一次性**工具，"
                        f"运行期调用它就等于把「静态数据」变回「运行时生成」"
                    )

    # (b') pipeline 也不许接线到采集 CLI（custom_action / custom_recognition 引它 = 运行期调用）
    pipeline_dir = root / "assets" / "resource" / "pipeline"
    if pipeline_dir.is_dir():
        for path in pipeline_dir.rglob("*.json*"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if COLLECT_CLI_MODULE in text:
                msgs.append(
                    f"{path.relative_to(root).as_posix()}：提到 {COLLECT_CLI_MODULE!r} —— "
                    f"pipeline 侧不许接线到采集 CLI"
                )

    # (c) scene/lords.py 的顶层 import 白名单（静态数据够不到 agent / 探测器）
    lords_path = root / "scene" / "lords.py"
    try:
        tree = ast.parse(lords_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        msgs.append(f"读不到 scene/lords.py：{exc}")
    else:
        for node in tree.body:
            module = ""
            if isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = ("." * (node.level or 0)) + (node.module or "")
            if module and module not in LORDS_ALLOWED_IMPORTS:
                msgs.append(
                    f"scene/lords.py 顶层 import {module!r} 不在白名单 {sorted(LORDS_ALLOWED_IMPORTS)}"
                    f" —— 纯静态数据必须够不到 agent / 探测器"
                )

    # (d) CLI 的顶层 import 黑名单（import 期不连设备、不进运行期）
    gen_path = root / "tools" / "gen_lord_registry.py"
    try:
        tree = ast.parse(gen_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        msgs.append(f"读不到 tools/gen_lord_registry.py：{exc}")
    else:
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                full = ("." * (node.level or 0)) + (node.module or "")
                names = [full, full.split(".")[0]]
            for name in names:
                if name in CLI_FORBIDDEN_IMPORTS:
                    msgs.append(
                        f"tools/gen_lord_registry.py 顶层 import {name!r} —— "
                        f"采集 CLI 必须能在没有设备/没有 MaaFramework 的机器上跑（--live 是懒 import）"
                    )
    return msgs


def _probe_site_failures(sites: dict[str, int] | None = None) -> list[str]:
    """「运行期不探测」静态检查：现存探测点必须逐条登记，新冒出来的必须当场点名。"""
    msgs: list[str] = []
    found = _collect_probe_sites(REPO_ROOT, "discover_difficulties") if sites is None else dict(sites)

    for rel, count in sorted(found.items()):
        registered = RUNTIME_PROBES.get(rel)
        if registered is None:
            msgs.append(
                f"{rel} 出现 {count} 处**未登记**的 `discover_difficulties` —— "
                f"运行期难度探测是被明令禁止的（D7「纯静态数据」），"
                f"若确实只是既有的债，请登记到 hooks_106.RUNTIME_PROBES 并写清角色；"
                f"若是新增，请改成读 scene/lords.py + 列表页 `通关数 N/M`"
            )
        elif registered != count:
            msgs.append(
                f"{rel}：`discover_difficulties` 出现 {count} 处，登记的是 {registered} 处 —— "
                f"探测点变了，先判断是「收窄」还是「扩散」再改登记"
            )

    msgs.extend(_cli_import_failures(REPO_ROOT))
    return msgs


def probe_lord_collect_cli_not_on_runtime_path() -> bool:
    """#106：运行期不探测（现存探测点已登记）+ 采集 CLI 不在运行期路径上。"""
    return _probe_site_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_SCHEMA,
        "#106",
        "领主战/讨伐难度静态数据 schema：必填字段 / M 正整数 / 解锁链首尾与 M 一致 / verified 与证据一致"
        "（证据路径必须在仓内真实存在）/ 花名册 46 一致 / 旧静态表被证伪后的档数回归钉",
        probe_lord_registry_schema,
    ),
    (
        HOOK_ID_NO_SET,
        "#106",
        "禁止「支持难度集」字段（数据类字段名 / 活跃标识符与字符串 / JSON 键名 / 集合形状值四条路），"
        "理由：同一帧列表页证伪了旧表 4 行里的 3 行",
        probe_lord_registry_no_supported_set,
    ),
    (
        HOOK_ID_CLI,
        "#106",
        "采集 CLI 产出一致性：假 OCR 重跑 collect() == scene/lords.py 的 LORDS，"
        "标记段与 assets/data/lords.json 均逐字相等（手改任一边即红）",
        probe_lord_registry_cli_consistent,
    ),
    (
        HOOK_ID_RUNTIME,
        "#106",
        "运行期不探测：业务路径上 discover_difficulties 的出现点逐条登记（新增即红）；"
        "运行期模块/pipeline 不得 import 采集 CLI；scene/lords.py 只许 stdlib + scene.config；"
        "CLI 顶层 import 不许出现 maa/agent/numpy/PIL/subprocess/socket",
        probe_lord_collect_cli_not_on_runtime_path,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（6 条；临时副本 / 内存注入，绝不改真仓库）
# ---------------------------------------------------------------------------
def _prove_red_checks() -> list[tuple[str, bool, str]]:
    """跑 6 条破坏实验，返回 ``(名称, 是否如期变红, 首条失败信息)``。"""
    lords_mod = _lords()
    gen = _gen()
    real = tuple(lords_mod.LORDS)
    checks: list[tuple[str, bool, str]] = []

    def _record(name: str, msgs: list[str]) -> None:
        checks.append((name, bool(msgs), msgs[0] if msgs else ""))

    def _find(row_name: str):
        return next((e for e in real if e.row_name == row_name), None)

    # ① 已验证条目配一条不存在的证据路径（没有已验证条目时退化为「任何有证据的条目」）
    target = next((e for e in real if e.verified), None) or next(
        (e for e in real if e.evidence), real[0] if real else None
    )
    if target is None:
        _record("① 给条目加一条不存在的证据路径", ["仓里没有可破坏的条目（数据被清空了）"])
    else:
        broken = dataclasses.replace(
            target,
            evidence=(*target.evidence, "tools/frames/lord_does_not_exist.png|2026-10-17 OCR: 编的"),
        )
        _record(
            f"① 给 {target.row_name} 加一条不存在的证据路径",
            _schema_failures(entries=_swap(real, broken)),
        )

    # ② 链长与 M 不一致
    redjoss = _find("红嫉机兵")
    if redjoss is None:
        _record("② 把 红嫉机兵 的 M 改成 3", ["找不到 红嫉机兵 的登记（数据被删了）"])
    else:
        _record(
            "② 把 红嫉机兵 的 M 改成 3（链仍有 4 档）",
            _schema_failures(entries=_swap(real, dataclasses.replace(redjoss, max_tiers=3))),
        )

    # ③ 源码塞一个「支持难度集」字段 + JSON 塞同名键
    source = (REPO_ROOT / "scene" / "lords.py").read_text(encoding="utf-8")
    doctored = source + "\n\nclass _Broken(Lord):\n    支持难度集: tuple[str, ...] = ()\n"
    payload = json.loads((REPO_ROOT / "assets" / "data" / "lords.json").read_text(encoding="utf-8"))
    payload["lords"][0]["支持难度集"] = []
    _record(
        "③ 给数据类塞「支持难度集」字段 + 给 JSON 塞同名键",
        _forbidden_failures(source_text=doctored, json_text=json.dumps(payload, ensure_ascii=False)),
    )

    # ④ 把 八岐大蛇讨伐 的 M 改回旧静态表的 3
    yamata = _find("八岐大蛇讨伐")
    if yamata is None:
        _record("④ 把 八岐大蛇讨伐 的 M 改回 3", ["找不到 八岐大蛇讨伐 的登记（证伪回归钉失去对象）"])
    else:
        _record(
            "④ 把 八岐大蛇讨伐 的 M 改回旧静态表的 3",
            _schema_failures(entries=_swap(real, dataclasses.replace(yamata, max_tiers=3))),
        )

    # ⑤ 假 OCR 少读一行（删掉 妖狐中级）
    thinned = {
        name: tuple(item for item in items if item[0] != "妖狐中级")
        for name, items in gen.FRAME_OCR.items()
    }
    try:
        drifted = gen.collect(gen.corpus_ocr_fn(thinned))
    except Exception as exc:  # noqa: BLE001 - 采集自己炸也算「与仓内不一致」
        _record("⑤ 从假 OCR 里删掉一行（妖狐中级）", [f"采集失败：{exc!r}"])
    else:
        _record("⑤ 从假 OCR 里删掉一行（妖狐中级）", _consistency_failures(collected=drifted))

    # ⑥ 业务路径上新增一处未登记的 discover_difficulties
    sites = _collect_probe_sites(REPO_ROOT, "discover_difficulties")
    _record(
        "⑥ 业务路径新增一处未登记的 discover_difficulties",
        _probe_site_failures(sites={**sites, "agent/hacked_special.py": 1}),
    )
    return checks


def _swap(entries: tuple, replacement) -> tuple:
    """用 ``replacement`` 换掉同 slug 的那条（保持顺序）。"""
    return tuple(replacement if entry.slug == replacement.slug else entry for entry in entries)


def prove_red() -> bool:
    """真实绿；6 条破坏实验各自如愿变红。"""
    print("hooks_106 prove-red：逐一破坏实现，要求四个挂点各自变红")
    green = (
        probe_lord_registry_schema()
        and probe_lord_registry_no_supported_set()
        and probe_lord_registry_cli_consistent()
        and probe_lord_collect_cli_not_on_runtime_path()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：schema / 禁止字段 / 采集一致 / 运行期不探测（绿）")
    if not green:
        for msg in (
            _schema_failures()
            + _forbidden_failures()
            + _consistency_failures()
            + _probe_site_failures()
        ):
            print(f"      - {msg}")
        return False

    checks = _prove_red_checks()
    for name, red, first in checks:
        print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {first}" if first else ""))
    ok = green and all(red for _n, red, _f in checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
