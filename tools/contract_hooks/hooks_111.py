# -*- coding: utf-8 -*-
"""#111：清理「被证伪的静态表」+ 修「自动」兄弟窗口 —— 两个挂点。

## A. 「支持难度集」是**被证伪的概念**，不是数据

#106 用**同一帧列表页**（``tools/frames/lord_page_tab_lord.png``）把那张旧静态表证伪了：
4 行里 **3 行不符**（艾基尔·嫉妒 ``通关数1/4`` 而旧表记 1 档、背鳍三兄弟 ``1/4`` 记 2 档、
八岐大蛇 ``4/4`` 记 3 档），另外 ``无猾机兵`` 实测 **M=5** 而旧表记 4
（``docs/research/lord-battle-difficulty-registry.md`` §2.4）。
它错法是**系统性**的：旧表把「某账号那一刻**看得见**的档数」当成了「该成员**一共**几档」。

⇒ 事实源只剩 ``scene/lords.py``（**M** = 总档数、**tier_chain** = 解锁链、认证文本、证据）。
逐成员难度**只允许**以「**账号快照**」形态存在，且必须写明**账号 + 时间 + 帧**三要素；
任何地方出现「支持难度集」形状的**生产数据**（每成员一份难度集合）→ 本挂点判红。

## B. 「自动」的兄弟窗口必须写**实测滑窗尖峰**

``hooks_auto_outside.auto-outside-template-distinct`` 原来把兄弟窗口写成 ``x=18``（真机 OCR
文字框左边界）并**只比那一个点**：``ZNCC(18) = 0.4536`` < 阈值 0.75 ⇒「不误命中」成立 ⇒ **碰巧绿**。
可框架做的是**滑窗**，真尖峰在 ``x=17 = 0.8964``（两张已入库帧一致）——它照样过阈值。
#108 已经用滑窗口径把这件事钉在 ``hooks_108`` 里；本挂点要求 ``hooks_auto_outside`` 也满足：
**窗口值 == 实测尖峰**，且它的模板检查必须仍是**滑窗**口径（而不是点测）。

## 两个挂点

1. ``lord-difficulty-snapshot-only``
   (a) **形状扫描**（AST）：``scene/`` + ``agent/`` + ``tools/contract_hooks/`` 里
       —— 模块级「每成员一份难度集合」的映射、「内联到某成员声明的难度字面量」、
       以及把快照重新绑成 ``DEVICE_*`` / ``SUPPORTED_*`` 这类**真源口吻**的新名字，全判红；
       豁免只有两处 :data:`SNAPSHOT_SITES`（``scene/lord_battle`` 与 ``hooks_32`` 的
       ``ACCOUNT_SNAPSHOTS``）+ 两处 :data:`BARE_ALLOWED`（兜底常量 / 反例夹具），
       且豁免项要**逐个复算**：三要素齐全、仓内帧存在、快照与 ``scene/lords.py`` 不冲突。
   (b) **冲突复算**：直接复用 ``scene.drift.lords_snapshot_drift``（同一套规矩，不另写一份）。

2. ``auto-sibling-window-is-measured-spike``
   (a) ``AUTO_BOX_720`` == 真「自动」的滑窗尖峰（≥0.99）；
   (b) ``CONT_BOX_720`` == 左侧兄弟的滑窗尖峰（**逐像素相等**，偏 1px 即红）；
   (c) 兄弟尖峰 **≥ 阈值**（模板本身分不开 —— 这是事实，不是缺陷）；
   (d) 偏 1px 至少掉 :data:`OFF_BY_ONE_MIN_DROP`（实测 0.8964 → 0.4536）—— 把「点测会骗人」量化；
   (e) ``hooks_auto_outside._template_failures()`` 绿，且它对**偏 1px 的窗口**必须红
       （★这条是「碰巧绿」的判别式★：点测实现会把它判绿）；
   (f) 另一张同形帧上尖峰位置一致（不是单帧偶然）。

## 本票**不改**（边界）

* ``scene/lords.py`` —— 难度事实真源，**只读**；
* ``assets/resource/pipeline/*.json`` / ``agent/*`` —— 零改动；
* ``scene/auto_switch.py`` —— #108 已落 ``AUTO_LABEL_ROI`` / ``AUTO_ORDER_BY``，本挂点只**读**它复算。

## prove-red（``python tools\\contract_hooks\\hooks_111.py``，7 条破坏实验）

① 把一个成员内联成 ``member(..., ("高级","超级"))`` → 形状扫描红（**这正是被证伪的形状**）；
② 清空快照的「采集时间」→ 三要素红；
③ 把 ``无猾机兵`` 的快照塞到 6 档（``scene/lords.py`` 的 M=5）→ 快照与真源冲突红；
④ 把兄弟窗口改回 ``x=18``（偏 1px）→ 窗口必须等于实测尖峰，红；
⑤ 把 ``hooks_auto_outside`` 的模板检查换回**点测**口径（兄弟框写死 x=18，即当年「碰巧绿」的形态）
   → 红（证明本挂点在防「碰巧绿」）；
⑥ 塞一张**新的逐成员难度表**（不在快照站点）→ 红；
⑦ 把快照绑成 ``SUPPORTED_TIERS``（真源口吻的新名字）→ 红。
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"

HOOK_ID_SNAPSHOT = "lord-difficulty-snapshot-only"
HOOK_ID_WINDOW = "auto-sibling-window-is-measured-spike"

#: 难度事实的**唯一真源**（本票只读）：M / 解锁链 / 认证文本 / 证据。
TRUTH_SOURCE = "scene/lords.py"
#: 形状扫描范围（生产配置 + 运行期 + 契约夹具）。``tools/test_*.py`` **不在**范围内：
#: 它们是**合成夹具**（``member("领主战", "X", "X", ["初级"])`` 之类），验证的是机制不是数据。
SCAN_DIRS: tuple[str, ...] = ("scene", "agent", "tools/contract_hooks")

#: 「账号快照」必须带的三要素（属性名）。缺一个 = 无法复核 = 红。
SNAPSHOT_PROVENANCE_ATTRS: tuple[str, ...] = (
    "ACCOUNT_SNAPSHOT_ACCOUNT",
    "ACCOUNT_SNAPSHOT_CAPTURED_AT",
    "ACCOUNT_SNAPSHOT_FRAMES",
)
#: 快照证据里「仓外产物」的前缀（``%TEMP%`` 已不可得，明写而不是假装它还在仓里）。
ARTIFACT_PREFIX = "artifact:"

#: ★唯一的两个快照站点★（模块级「每成员一份难度集合」只允许出现在这里）。
SNAPSHOT_SITES: dict[str, str] = {
    "scene/lord_battle.py::ACCOUNT_SNAPSHOTS": (
        "生产配置里的账号快照：#111 从「支持难度集」降级而来，值 = 某账号某时刻看得见的档；"
        "三要素见同模块 ACCOUNT_SNAPSHOT_ACCOUNT / _CAPTURED_AT / _FRAMES"
    ),
    "tools/contract_hooks/hooks_32.py::ACCOUNT_SNAPSHOTS": (
        "#32 的真机内嵌夹具（#111 降级改名）：用于与配置侧快照逐成员对账；"
        "三要素见同模块 ACCOUNT_SNAPSHOT_ACCOUNT / _CAPTURED_AT / _FRAMES"
    ),
}
#: ★#100 安装态★ 允许 agent/ 里存在的「逐字冻结的真源副本」：site -> (说明, 钉住它的 parity 挂点名)。
#: 这不是放宽「禁逐成员难度表」：这几张表是 ``scene/lords.py`` / ``scene/lords_unlock.py`` 的**副本**，
#: 存在的唯一理由是 install/agent 没有 scene/；真源仍是 scene/lords.py。
#: ★每项必须能被 hooks_100 的 parity 逐项对账（改真源不改快照 → hooks_100 红）★，否则本守卫红。
INSTALL_FROZEN: dict[str, tuple[str, str]] = {
    "agent/lords_impl.py::_LORDS_ROWS_SNAPSHOT": (
        "行名表 = 真源 46 个成员身份（install 态没有 scene/，纯为可用性）",
        "lords-install-snapshot-parity",
    ),
    "agent/lords_impl.py::_LORDS_M_SNAPSHOT": (
        "M 表 = 真源已验证条目的 M（其余 None）；语义仍是「账号快照派生的 M」，不是支持难度集",
        "lords-install-snapshot-parity",
    ),
    "agent/lords_impl.py::_LORDS_CHAIN_SNAPSHOT": (
        "解锁链 = 真源已采集的两条完整链（其余空）",
        "lords-install-snapshot-parity",
    ),
}


def _install_frozen_failures() -> list:
    """逐项复算：站点真的存在于 agent/，且它点名的 parity 契约真的在 hooks_100 里。"""
    import pathlib as _pl

    msgs: list[str] = []
    hook_src = ""
    hook_path = _pl.Path(__file__).with_name("hooks_100.py")
    if hook_path.is_file():
        hook_src = hook_path.read_text(encoding="utf-8")
    for site, (why, contract) in INSTALL_FROZEN.items():
        rel, _, name = site.partition("::")
        target = _pl.Path(__file__).resolve().parents[2] / rel
        if not target.is_file():
            msgs.append(f"INSTALL_FROZEN 站点不存在：{site}（说明={why}）")
            continue
        if name not in target.read_text(encoding="utf-8"):
            msgs.append(f"INSTALL_FROZEN 站点里的常量找不到：{site}（改过名字就把登记也改掉）")
        if contract not in hook_src:
            msgs.append(f"INSTALL_FROZEN 站点 {site} 点名的 parity 契约 {contract!r} 不在 hooks_100 里 —— 没人钉住它就不许存在")
    return msgs


#: 站点 -> 要 import 的模块（复算三要素；import 名与仓内路径的对应写在这里，别处不猜）。
SNAPSHOT_MODULES: dict[str, str] = {
    "scene/lord_battle.py::ACCOUNT_SNAPSHOTS": "scene.lord_battle",
    "tools/contract_hooks/hooks_32.py::ACCOUNT_SNAPSHOTS": "hooks_32",
}

#: 模块级「难度集合常量」的豁免（**不是**每成员数据 —— 每一项都必须写明它到底是什么）。
BARE_ALLOWED: dict[str, str] = {
    "scene/lord_battle.py::_DISCOVERY_FALLBACK": (
        "未实测成员的**统一兜底**（#39）：不是成员数据、也不是任何账号的实测值；"
        "真机以详情页发现 / 列表页 `通关数 N/M` 为准"
    ),
    "tools/contract_hooks/hooks_39.py::STATIC_CLEARED_SET": (
        "#39 的**反例夹具**：它存在的意义是证明「静态表必错」（清关账号 4 档 vs 早期账号只有中级，"
        "证据帧 tools/frames/lord_detail_redjoss_cleared.png 在仓内）；"
        "与 hooks_32.ACCOUNT_SNAPSHOTS[红嫉机兵] 是同一份快照，两处由 hooks_39 自己断言一致"
    ),
}

#: 旧名的**遗留别名**：允许存在（有本票边界外的读者），但不许再新增，也不许当依据。
LEGACY_ALIASES: dict[str, str] = {
    "tools/contract_hooks/hooks_32.py::DEVICE_DIFFICULTIES": (
        "旧名别名 → ACCOUNT_SNAPSHOTS。仍被 tools/test_lord_data.py 与 hooks_39.py 按名读取，"
        "那两张票在 #111 的改动边界外 ⇒ 保留别名；★语义已降级为快照，新代码不许再用★"
    ),
}
#: 不许再用来给「难度集合」起名（它们读起来像真源，正是 #106 证伪的那种口吻）。
TRUTHY_NAME_PREFIXES: tuple[str, ...] = ("DEVICE_", "SUPPORTED_", "AVAILABLE_", "NATIVE_")

#: 兄弟窗口的验收线。
POSITIVE_MIN = 0.99        # 真「自动」滑窗尖峰
SIBLING_MIN = 0.80         # 兄弟尖峰（实测 0.8964；低于此说明前提变了，请重新标定）
#: 偏 1px 至少要掉这么多分（实测 0.8964 → 0.4536 = 掉 0.44）；「点测会骗人」的量化。
OFF_BY_ONE_MIN_DROP = 0.30

_SKIP_DIRS = frozenset({".git", ".slim", "__pycache__", ".venv", "node_modules", "install", "debug", "deps"})


# ---------------------------------------------------------------------------
# 惰性导入 / 路径（与同目录其它 hooks 同一手法）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT / "agent")):
        if path not in sys.path:
            sys.path.append(path)


def _module(name: str):
    _paths()
    return importlib.import_module(name)


def _lords():
    """``scene.lords``（难度事实真源）。用 import_module：``scene/__init__`` 会遮蔽同名属性。"""
    return _module("scene.lords")


def _diff() -> tuple:
    return tuple(_module("scene.config").DIFFICULTIES)


def _drift():
    return _module("scene.drift")


def _hooks_108():
    return _module("hooks_108")


def _auto_outside():
    return _module("hooks_auto_outside")


# ---------------------------------------------------------------------------
# AST 小工具
# ---------------------------------------------------------------------------
_COLLECTION_FACTORIES = frozenset({"frozenset", "set", "tuple", "list"})
_MEMBER_FACTORIES = frozenset({"member", "MemberDelta"})


def _string_elems(node) -> list[str] | None:
    """把一个「字符串集合字面量」解成 ``list[str]``；``frozenset({...})`` 之类也认。"""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                return None
        return out
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _COLLECTION_FACTORIES
        and len(node.args) == 1
    ):
        return _string_elems(node.args[0])
    return None


def _is_difficulty_collection(vals, difficulties: frozenset[str]) -> bool:
    """是不是一份「难度集合」：非空、元素**全是难度词**，且不是整张词表（那是词表本身）。"""
    return bool(vals) and all(v in difficulties for v in vals) and set(vals) != set(difficulties)


def _iter_py(rel_dir: str):
    base = REPO_ROOT / rel_dir
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.py")):
        parts = path.relative_to(REPO_ROOT).parts
        if any(part in _SKIP_DIRS for part in parts):
            continue
        yield path.relative_to(REPO_ROOT).as_posix(), path


def _source(rel: str, overrides: dict[str, str] | None) -> str:
    """读源码。★用 ``utf-8-sig``★：本仓有几个 hook 文件带 UTF-8 BOM（U+FEFF），
    用 ``utf-8`` 读会让 ``ast.parse`` 直接 ``SyntaxError`` —— 那会把「有 BOM」误报成坏源码。"""
    if overrides and rel in overrides:
        return overrides[rel]
    return (REPO_ROOT / rel).read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# 挂点 1：逐成员难度**只允许**账号快照形态
# ---------------------------------------------------------------------------
def _provenance_failures(module, label: str) -> list[str]:
    """三要素复算：账号 / 时间 / 帧（仓外产物用 ``artifact:`` 前缀明写）。"""
    msgs: list[str] = []
    for attr in SNAPSHOT_PROVENANCE_ATTRS[:2]:
        value = getattr(module, attr, "")
        if not isinstance(value, str) or not value.strip():
            msgs.append(
                f"{label}：缺 {attr}（或为空）—— 账号快照必须写明**账号 + 时间 + 帧**三要素"
                f"（#111：没有采集条件的观察无法复核，只能当噪声）"
            )
    frames = tuple(getattr(module, "ACCOUNT_SNAPSHOT_FRAMES", ()) or ())
    if not frames:
        msgs.append(
            f"{label}：ACCOUNT_SNAPSHOT_FRAMES 为空 —— 快照必须指向具体帧/产物；"
            f"仓外产物请写成 {ARTIFACT_PREFIX}<路径>"
        )
    for frame in frames:
        if not isinstance(frame, str) or not frame.strip():
            msgs.append(f"{label}：ACCOUNT_SNAPSHOT_FRAMES 里有空串（帧必须可点名）")
            continue
        if frame.startswith(ARTIFACT_PREFIX):
            continue
        if not (REPO_ROOT / frame).is_file():
            msgs.append(
                f"{label}：帧 {frame!r} 在仓库里**不存在** —— 仓内帧必须真实存在；"
                f"仓外产物请写 {ARTIFACT_PREFIX}<路径>（不要假装它还在仓里）"
            )
    return msgs


def _shape_failures(overrides: dict[str, str] | None = None) -> list[str]:
    """扫描生产数据里「支持难度集」形状的东西（``overrides`` 供破坏实验注入坏源码）。"""
    difficulties = frozenset(_diff())
    roster = {entry.row_name for entry in _lords().LORDS}
    snapshot_names = {key.split("::")[1] for key in SNAPSHOT_SITES}
    msgs: list[str] = []

    for rel_dir in SCAN_DIRS:
        for rel, _path in _iter_py(rel_dir):
            if rel == TRUTH_SOURCE:
                continue  # 真源本身：字段禁令由 hooks_106 守（不在此重复，避免两处规则打架）
            try:
                tree = ast.parse(_source(rel, overrides))
            except (OSError, SyntaxError) as exc:
                msgs.append(f"{rel}：读不到 / 解析不了源码，形状扫描失效（{exc}）")
                continue

            for node in tree.body:
                if isinstance(node, ast.Assign):
                    targets = [t for t in node.targets if isinstance(t, ast.Name)]
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets = [node.target] if isinstance(node.target, ast.Name) else []
                    value = node.value
                else:
                    continue
                if not targets:
                    continue
                name = targets[0].id
                site = f"{rel}::{name}"

                # (R1) 模块级「难度集合常量」。
                vals = _string_elems(value)
                if vals is not None and _is_difficulty_collection(vals, difficulties):
                    if site not in BARE_ALLOWED:
                        msgs.append(
                            f"{rel}::{name} 是一份模块级**难度集合** {vals} —— 这正是 #106 证伪的"
                            f"「支持难度集」形状。事实源是 {TRUTH_SOURCE}（M + 解锁链）；"
                            f"某账号的观察只能进 {sorted(SNAPSHOT_SITES)} 并写明账号/时间/帧"
                        )
                    continue

                # (R2) 模块级「每成员一份难度集合」的映射。
                if isinstance(value, ast.Dict):
                    keys = [
                        key.value
                        for key in value.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    ]
                    roster_keys = [key for key in keys if key in roster]
                    value_lists = [_string_elems(item) for item in value.values]
                    if len(roster_keys) >= 2 and all(
                        item is not None and _is_difficulty_collection(item, difficulties)
                        for item in value_lists
                    ):
                        if site not in SNAPSHOT_SITES and site not in INSTALL_FROZEN:
                            msgs.append(
                                f"{rel}::{name} 是**逐成员难度表**（{len(roster_keys)} 个花名册成员）"
                                f"—— 只允许 {sorted(SNAPSHOT_SITES)} 这两处账号快照；"
                                f"事实源是 {TRUTH_SOURCE}（M + 解锁链）"
                            )
                        continue

                # (R2') 把快照重新绑成「真源口吻」的新名字。
                if isinstance(value, ast.Name) and value.id in snapshot_names:
                    if name.startswith(TRUTHY_NAME_PREFIXES) and site not in LEGACY_ALIASES:
                        msgs.append(
                            f"{rel}::{name} 把账号快照绑成了「{name.split('_')[0]}_*」这种**真源口吻**"
                            f"的名字 —— #106 证伪的就是这种命名带来的误读；"
                            f"请用 ACCOUNT_SNAPSHOTS（旧名别名已登记，不再新增）"
                        )

            # (R3) 内联到**真实成员**声明上的难度字面量。
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                fname = getattr(func, "id", None) or getattr(func, "attr", None)
                if fname not in _MEMBER_FACTORIES:
                    continue
                strings = [
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                ]
                strings += [
                    kw.value.value
                    for kw in node.keywords
                    if kw.arg in ("行名", "id") and isinstance(kw.value, ast.Constant)
                ]
                if not any(value in roster for value in strings):
                    continue  # 合成夹具（"X" / "空集机兵"）不是生产数据
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    vals = _string_elems(arg)
                    if vals is not None and _is_difficulty_collection(vals, difficulties):
                        msgs.append(
                            f"{rel}:{node.lineno} 把难度字面量 {vals} **内联**在成员声明上 —— "
                            f"这正是 #106 证伪的形状；改成从账号快照取（scene/lord_battle._observed）"
                            f"或读 {TRUTH_SOURCE}"
                        )
                        break
    return msgs


def _snapshot_only_failures(overrides: dict[str, str] | None = None) -> list[str]:
    """① 形状扫描 + ② 快照三要素 + ③ 快照与 ``scene.lords`` 不冲突。

    ``overrides`` 非空时（破坏实验）只做**形状扫描** —— 那时源码是内存里的坏副本，
    三要素 / 冲突复算仍走真仓库（否则测不出想测的那一条）。
    """
    msgs = _shape_failures(overrides)
    if overrides is not None:
        return msgs

    # ② 三要素（两处快照站点各查一遍；scene 侧 drift 也会查，这里独立一份，别让挂点只靠别人）。
    for site, module_name in SNAPSHOT_MODULES.items():
        try:
            module = _module(module_name)
        except Exception as exc:  # noqa: BLE001 - 拿不到快照站点 = 红
            msgs.append(f"{site}：import {module_name} 失败，无法复算三要素（{exc!r}）")
            continue
        msgs.extend(_provenance_failures(module, site))

    # ③ 快照 vs 真源（复用 drift 的同一套规矩，绝不另写一份）。
    msgs.extend(_drift().lords_snapshot_drift(REPO_ROOT))
    return msgs


def probe_lord_difficulty_snapshot_only() -> bool:
    """#111：逐成员难度**只允许**以「账号快照（账号+时间+帧）」形态存在，且与 ``scene/lords.py``
    （M + 解锁链，唯一事实源）不冲突；「支持难度集」形状的生产数据出现即红。"""
    return _snapshot_only_failures() == [] and _install_frozen_failures() == []


# ---------------------------------------------------------------------------
# 挂点 2：「自动」的兄弟窗口必须等于**实测滑窗尖峰**
# ---------------------------------------------------------------------------
def _window_failures(guard=None, auto_box=None, cont_box=None) -> list[str]:
    """滑窗复算（与 ``hooks_108`` 同一套实现）+ 框架语义复算。

    ``guard`` = 被检查的模板检查函数（默认 ``hooks_auto_outside._template_failures``），
    破坏实验会换成「点测」实现，用来证明本挂点真的在防「碰巧绿」。
    """
    _paths()
    cfg = _module("scene.auto_switch")
    h108 = _hooks_108()
    outside = _auto_outside()

    auto_box = list(auto_box or outside.AUTO_BOX_720)
    cont_box = list(cont_box or outside.CONT_BOX_720)
    thr = float(cfg.AUTO_TEMPLATE_THRESHOLD)
    msgs: list[str] = []

    missing = h108._deps_missing()
    if missing:
        return [missing]
    tpl, rel = h108._template_gray(cfg)
    if tpl is None:
        return [f"模板裁片缺失：assets/resource/image/{rel}（没有裁片就没有滑窗复算）"]
    tpl_h, tpl_w = tpl.shape

    # (a)(b)(c)(d) 两张同形帧：本挂点用的帧 + hooks_108 的另一张（证明尖峰位置稳定）。
    frames: list[tuple[str, bool]] = []
    primary = getattr(outside, "FRAME_LORD_TEAM", "")
    if primary:
        frames.append((primary, True))
    others = [f for f in getattr(h108, "POSITIVE_FRAMES", ()) if f != primary]
    if others:
        frames.append((others[0], False))
    if not frames:
        return ["找不到任何正例帧 —— 本挂点无从复算"]

    for frame, is_primary in frames:
        if not (REPO_ROOT / frame).is_file():
            msgs.append(f"证据帧缺失：{frame}（已入库的证据帧被删 → 滑窗复算失效）")
            continue
        scores = h108._zncc_map(h108._frame_720(frame), tpl)
        peaks = h108._peaks(scores, thr)

        # (a) 真「自动」= 全屏最像（order_by Score 语义）。
        best = h108._select(peaks, "Score", 0)
        if best is None or best[0] < max(thr, POSITIVE_MIN):
            msgs.append(
                f"{frame}：真「自动」的滑窗尖峰 {best} 低于验收线 "
                f"{max(thr, POSITIVE_MIN):.2f}（阈值 {thr}，帧/模板变了请重新标定）"
            )
        elif is_primary and (abs(best[1] - auto_box[0]) > 2 or abs(best[2] - auto_box[1]) > 2):
            msgs.append(
                f"{frame}：hooks_auto_outside.AUTO_BOX_720={auto_box[:2]} 不是滑窗尖峰 "
                f"{(best[1], best[2])} —— 窗口值必须等于**实测尖峰**"
            )

        # (b)(c)(d) 兄弟尖峰 == CONT_BOX_720，且它照样过阈值、而偏 1px 就掉下来。
        left = [cand for cand in peaks if cand[1] < auto_box[0]]
        sibling = h108._select(left, "Score", 0)
        if sibling is None:
            msgs.append(
                f"{frame}：真「自动」左侧没有 ≥{thr} 的候选 —— 假阳前提消失了"
                f"（帧/模板/阈值变了，请重新标定）"
            )
            continue
        if is_primary and (sibling[1], sibling[2]) != (cont_box[0], cont_box[1]):
            msgs.append(
                f"{frame}：hooks_auto_outside.CONT_BOX_720={cont_box[:2]} 不是兄弟的滑窗尖峰 "
                f"{(sibling[1], sibling[2])}（ZNCC={sibling[0]}）—— 窗口值必须等于**实测尖峰**："
                f"差 1px 就能把分数从 {sibling[0]} 掉到 "
                f"{float(scores[cont_box[1], cont_box[0]]):.4f}，于是「点测」会骗人"
            )
        if sibling[0] < SIBLING_MIN:
            msgs.append(
                f"{frame}：兄弟尖峰 ZNCC={sibling[0]} < {SIBLING_MIN} —— 本挂点的前提是"
                f"「模板本身分不开这对兄弟」；分数掉下来了请重新标定验收线"
            )
        if is_primary:
            z_spike = float(scores[cont_box[1], cont_box[0]])
            x_off = cont_box[0] + 1
            drop = z_spike - float(scores[cont_box[1], x_off])
            if drop < OFF_BY_ONE_MIN_DROP:
                msgs.append(
                    f"{frame}：兄弟窗口右移 1px 只掉了 {drop:.4f}（< {OFF_BY_ONE_MIN_DROP}）"
                    f" —— 「点测会骗人」的前提变了，请重新标定本挂点的 OFF_BY_ONE_MIN_DROP"
                )

        # (e) 真源 roi：兄弟尖峰在 roi 外、真「自动」在 roi 内（distinctness 的来源）。
        roi = tuple(cfg.AUTO_LABEL_ROI)
        if h108._inside(roi, (cont_box[0], cont_box[1], tpl_w, tpl_h)):
            msgs.append(
                f"{frame}：真源 AUTO_LABEL_ROI={list(roi)} **覆盖**了兄弟尖峰窗口 {cont_box}"
                f" —— roi 必须把「自动续战」整栏排除出候选池（#108）"
            )
        if not h108._inside(roi, (auto_box[0], auto_box[1], tpl_w, tpl_h)):
            msgs.append(
                f"{frame}：真源 AUTO_LABEL_ROI={list(roi)} **不含**真「自动」窗口 {auto_box}"
                f" —— 收窄过头会把该命中的也裁掉"
            )
        inside = [cand for cand in peaks if h108._inside(roi, (cand[1], cand[2], tpl_w, tpl_h))]
        picked = h108._select(inside, cfg.AUTO_ORDER_BY, 0)
        if len(inside) != 1 or picked is None or (
            abs(picked[1] - auto_box[0]) > 2 or abs(picked[2] - auto_box[1]) > 2
        ):
            msgs.append(
                f"{frame}：按框架语义（roi {list(roi)} + order_by={cfg.AUTO_ORDER_BY!r} + index 0）"
                f"选到 {picked}（roi 内候选 {len(inside)} 个），不是真「自动」{auto_box[:2]}"
            )

    # (f) ★判别式★：被检查的函数必须**仍是滑窗口径**。
    check = guard or getattr(outside, "_template_failures", None)
    if check is None:
        return msgs + ["hooks_auto_outside 没有 _template_failures —— 模板守卫不存在了"]
    try:
        guard_msgs = list(check())
    except Exception as exc:  # noqa: BLE001 - 探针自己炸了也是红
        return msgs + [f"hooks_auto_outside._template_failures() 抛异常（{exc!r}）"]
    if guard_msgs:
        msgs.append(
            "hooks_auto_outside._template_failures() 变红（本挂点要求它绿）—— "
            + "；".join(guard_msgs)
        )
    off_by_one = [cont_box[0] + 1, cont_box[1], cont_box[2], cont_box[3]]
    try:
        drifted = list(check(cont_box=off_by_one))
    except TypeError as exc:
        return msgs + [
            f"hooks_auto_outside._template_failures 不接受 cont_box=（{exc!r}）—— "
            f"本挂点靠它验证「窗口必须等于实测尖峰」"
        ]
    if not drifted:
        msgs.append(
            f"hooks_auto_outside._template_failures(cont_box={off_by_one[:2]}) 判**绿** —— "
            f"说明它还在**点测**（偏 1px 的框分数掉到阈值以下，于是「不误命中」碰巧成立）；"
            f"必须改成滑窗口径并与实测尖峰逐像素比对（#108 / #111）"
        )
    return msgs


def probe_auto_sibling_window_is_measured_spike() -> bool:
    """#111：``hooks_auto_outside`` 的兄弟窗口 == **实测滑窗尖峰**（0.8964@x=17，不是 OCR 框的
    x=18=0.4536），且它的模板检查是**滑窗**口径而不是点测。"""
    return _window_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（5 条；全部在内存/临时态上做，绝不改真仓库）
# ---------------------------------------------------------------------------
def _break_inline_member() -> list[str]:
    """① 把一个成员内联成难度字面量 → 形状扫描必须红。"""
    rel = "scene/lord_battle.py"
    source = (REPO_ROOT / rel).read_text(encoding="utf-8-sig")
    old = '    _observed("领主战", "猩红巨熊讨伐"),'
    if old not in source:
        return []  # 破坏点丢了——由调用方判红
    new = '    member("领主战", "猩红巨熊讨伐", "猩红巨熊讨伐", ("高级", "超级")),'
    return _snapshot_only_failures(overrides={rel: source.replace(old, new, 1)})


def _break_drop_captured_at() -> list[str]:
    """② 清空快照的「采集时间」→ 三要素必须红。"""
    module = _module("scene.lord_battle")
    real = getattr(module, "ACCOUNT_SNAPSHOT_CAPTURED_AT", "")
    try:
        module.ACCOUNT_SNAPSHOT_CAPTURED_AT = ""
        return _provenance_failures(module, "scene/lord_battle.py::ACCOUNT_SNAPSHOTS")
    finally:
        module.ACCOUNT_SNAPSHOT_CAPTURED_AT = real


def _break_snapshot_over_max() -> list[str]:
    """③ 把「无猾机兵」的快照塞到 6 档（M=5）→ 快照与真源冲突必须红。"""
    module = _module("scene.lord_battle")
    real = module.ACCOUNT_SNAPSHOTS["无猾机兵"]
    try:
        module.ACCOUNT_SNAPSHOTS["无猾机兵"] = (
            "超级", "地狱级", "高级+", "高级", "中级", "初级",
        )
        return _drift().lords_snapshot_drift(REPO_ROOT)
    finally:
        module.ACCOUNT_SNAPSHOTS["无猾机兵"] = real


def _break_window_off_by_one() -> list[str]:
    """④ 把兄弟窗口改回 ``x=18``（真机 OCR 框位置，偏 1px）→ 窗口必须等于实测尖峰，红。"""
    outside = _auto_outside()
    real = outside.CONT_BOX_720
    try:
        outside.CONT_BOX_720 = [18, 1062, 43, 26]
        return _window_failures()
    finally:
        outside.CONT_BOX_720 = real


def _break_point_measure() -> list[str]:
    """⑤ 把模板检查换回**点测**口径（且兄弟窗口固定成旧的 x=18）→ 判别式必须红。

    ★这条最要紧★：旧实现**不是**失败的，它只是「点测了一个偏 1px 的框」→ 0.4536 < 阈值 →
    「不误命中」成立 → **碰巧绿**。所以本破坏实验刻意复刻那个「绿」的形态，
    再看判别式（喂偏 1px 的窗口必须红）能不能拆穿它。
    """
    OLD_CONT_BOX = [18, 1062, 43, 26]  # #111 修正前的常量（真机 OCR 文字框的左边界）

    def _point_only(frame_rgb, tpl, auto_box, thr):
        """点测：拿两个框裁出来算 ZNCC，只比那两个点（并且兄弟框写死旧值）。"""
        import numpy as np  # noqa: PLC0415

        gray = np.asarray(frame_rgb.convert("L"), dtype=float)

        def patch(box):
            x, y, w, h = (int(v) for v in box)
            return gray[y:y + h, x:x + w]

        def zncc(a, b):
            a = a - a.mean(); b = b - b.mean()
            den = float(((a * a).sum() * (b * b).sum()) ** 0.5)
            return float((a * b).sum() / den) if den else 0.0

        msgs = []
        if zncc(patch(auto_box), tpl) < thr:
            msgs.append("点测：未命中「自动」")
        if zncc(patch(OLD_CONT_BOX), tpl) >= thr:  # ← 旧的「误命中」判据
            msgs.append("点测：误命中「自动续战」")
        return msgs

    outside = _auto_outside()
    cfg = _module("scene.auto_switch")
    h108 = _hooks_108()
    outside_real = outside._template_failures
    try:
        tpl, _rel = h108._template_gray(cfg)
        img, _np = outside._frame_720()
        thr = float(cfg.AUTO_TEMPLATE_THRESHOLD)

        # ★参数名不能叫 frame★：会遮蔽上面那张图（旧写法就栽在这），这里显式用 img。
        def broken(tpl_rel=None, auto_box=None, cont_box=None, frame=None):
            return _point_only(img, tpl, list(auto_box or outside.AUTO_BOX_720), thr)

        outside._template_failures = broken
        return _window_failures(guard=broken)
    finally:
        outside._template_failures = outside_real


def _break_rogue_table() -> list[str]:
    """⑥ 在 ``scene/lord_battle.py`` 塞一张**新的逐成员难度表**（不在快照站点）→ R2 必须红。"""
    rel = "scene/lord_battle.py"
    source = (REPO_ROOT / rel).read_text(encoding="utf-8-sig")
    anchor = "FAMILY = FamilyTemplate(\n"
    if anchor not in source:
        return []
    rogue = (
        "# 破坏实验注入：一张「每成员支持哪些难度」的表（= 被证伪的形状）\n"
        "_ROGUE_TIERS = {\n"
        '    "猩红巨熊讨伐": ("高级", "超级"),\n'
        '    "背鳍三兄弟讨伐": ("中级",),\n'
        "}\n\n"
    )
    return _snapshot_only_failures(overrides={rel: source.replace(anchor, rogue + anchor, 1)})


def _break_truthy_alias() -> list[str]:
    """⑦ 把快照重新绑成 ``SUPPORTED_TIERS``（真源口吻）→ 别名规则必须红。"""
    rel = "scene/lord_battle.py"
    source = (REPO_ROOT / rel).read_text(encoding="utf-8-sig")
    anchor = "def _snapshot(行名: str) -> tuple[str, ...]:\n"
    if anchor not in source:
        return []
    alias = "SUPPORTED_TIERS = ACCOUNT_SNAPSHOTS\n\n\n"
    return _snapshot_only_failures(overrides={rel: source.replace(anchor, alias + anchor, 1)})


def prove_red() -> bool:
    """真实绿；5 条破坏实验各自如愿变红。"""
    print("hooks_111 prove-red：逐条破坏，要求两个挂点各自变红")
    green = (
        probe_lord_difficulty_snapshot_only()
        and probe_auto_sibling_window_is_measured_spike()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：快照形态 + 兄弟窗口尖峰（绿）")
    if not green:
        for msg in _snapshot_only_failures() + _window_failures():
            print(f"      - {msg}")
        return False

    checks: list[tuple[str, list[str]]] = [
        ("① 把 猩红巨熊讨伐 内联成难度字面量（= 被证伪的形状）", _break_inline_member()),
        ("② 清空快照的「采集时间」（三要素缺一）", _break_drop_captured_at()),
        ("③ 把 无猾机兵 的快照塞到 6 档（scene/lords.py 的 M=5）", _break_snapshot_over_max()),
        ("④ 兄弟窗口改回 x=18（偏 1px，真机 OCR 框位置）", _break_window_off_by_one()),
        ("⑤ 模板检查换回「点测」口径（旧写法：兄弟框写死 x=18）", _break_point_measure()),
        ("⑥ 塞一张新的逐成员难度表（不在快照站点）", _break_rogue_table()),
        ("⑦ 把快照绑成 SUPPORTED_TIERS（真源口吻的新名字）", _break_truthy_alias()),
    ]
    results: list[bool] = []
    for name, msgs in checks:
        red = len(msgs) > 0
        results.append(red)
        print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
    ok = green and all(results)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID_SNAPSHOT,
        "#111",
        "逐成员难度**只允许**账号快照形态（账号 + 时间 + 帧三要素）：模块级「每成员难度集合」/"
        "内联在成员声明上的难度字面量 / 真源口吻的新别名 全判红（豁免仅两处 ACCOUNT_SNAPSHOTS）；"
        "并复算快照与 scene/lords.py（M + 解锁链，唯一事实源）不冲突 —— 成员在花名册 / 档 ∈ 词表 /"
        "len(快照) ≤ M / 快照 ⊆ 链",
        probe_lord_difficulty_snapshot_only,
    ),
    (
        HOOK_ID_WINDOW,
        "#111",
        "「自动」的兄弟窗口必须等于**实测滑窗尖峰**：CONT_BOX_720 == (17,1062)（0.8964，"
        "偏 1px 的 x=18 只有 0.4536），hooks_auto_outside 的模板检查必须是**滑窗**口径"
        "（对它喂偏 1px 的窗口必须红）；真源 roi/order_by 复算选到真「自动」",
        probe_auto_sibling_window_is_measured_spike,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
