# -*- coding: utf-8 -*-
"""#55（Phase 2）：深渊EX 移植 —— 契约挂点（自动发现，零改既有文件）。

seam：``scene.abyss``（横幅模板 / 二级页签列表 / 确认文案 / 阶梯规模 / 账本范围 —— 配置权威）
+ ``agent/abyss_impl.py``（状态机 + 账本，纯机制）+ ``assets/resource/pipeline/abyss.json``
（自包含单人流水线）。

六个守卫（对应本票的六条硬要求；prove-red 见文末）：

1. ``abyss-config-is-source-of-truth`` —— 配置权威在 ``scene.abyss``：``abyss_impl`` 的冻结
   快照 / ``abyss.json`` 的横幅模板 / 阈值 / 确认文案 / 页签列表都从它派生（漂移即红）；
2. ``abyss-tab-search-data-driven`` —— 终始之战二级页签搜索**数据驱动**（页签列表可配置、
   不硬编码单个页签），横幅节点排在切页签之前，且「横幅在多个页签可见」有数据模型；
3. ``abyss-solo-no-coop`` —— **全单人、无共斗**：``abyss.json`` / ``abyss_impl`` 一律不含
   共斗房 / 招募 / 建立房间 / 多人 节点或状态（运维「深渊EX 只有单人，没有共斗」）；
4. ``abyss-ladder-30-no-sets`` —— 30 层线性阶梯、**不关心有几套**：MAX_STAGES=30、
   ledger_scope=abyss、阶段正则 = 第N战、无 ``target_sets`` / 「刷几套」；
5. ``abyss-banner-distinct`` —— EX 横幅用**模板匹配**且阈值可靠区分纯深渊横幅（阈值 >
   实测假阳分 0.874）；两条模板都在仓库资源树下；
6. ``abyss-classify-positives`` —— ``abyss_impl.classify`` 对真机形态的合成 OCR 帧正判
   （hub / main / 单人编队 / 结算 / 战斗 / 需要130级 / 主城 / 活动 / 终始之战）。

（另有两个后加的守卫，同样在本文件里：）

7. ``abyss-no-global-table-growth`` —— 深渊不改全局页面判据表（用注册表 API 证明）；
8. ``abyss-plain-wired``（#55 Phase 3）—— **普通深渊 = 同一实现 + 场景数据**（「只差导航」）：
   两个场景 id（``abyss`` / ``abyss_plain``）共用 ``abyss_impl`` 的实现，差异只落成数据
   （横幅模板 / 阈值 / 进关确认文案 / 账本范围）；流水线带【场景门控】防普通深渊任务误点
   「未通关」页签里的 EX 横幅；任务『自动刷深渊』入口 = ``AbyssPlainEntry``。

prove-red（``python tools\\contract_hooks\\hooks_abyss.py``）：逐一改坏实现，要求守卫各自变红。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE_REL = "assets/resource/pipeline"
ABYSS_JSON = "abyss.json"
INTERFACE_REL = "assets/interface.json"
IMAGE_REL = "assets/resource/image"

# 纯深渊横幅对 EX 模板的实测假阳分（校准 §3.2 坑 1：0.8708；本机复算 ZNCC=0.874）。
_PLAIN_FALSE_POSITIVE = 0.874


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


def _strip_jsonc(text: str) -> str:
    """去 JSONC 注释，保持结构（自足一份，避免依赖具体模块的私有实现）。"""
    out: list[str] = []
    state = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i : i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
            elif text[i : i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i : i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch)
            state = 1
            i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> dict:
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


def _abyss_pipe(root: Path | None = None) -> dict:
    base = (Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL / ABYSS_JSON
    return _load_jsonc(base)


def _abyss_text(root: Path | None = None) -> str:
    base = (Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL / ABYSS_JSON
    return base.read_text(encoding="utf-8")


def _node(pipes: dict, name: str) -> dict:
    return pipes.get(name) or {}


def _action_param(node: dict) -> dict:
    """节点自定义动作的 custom_action_param（找不到返回 {}）。"""
    return ((node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}


def _recognition_param(node: dict) -> dict:
    return (node.get("recognition") or {}).get("param") or {}


def _find_key(obj, key: str) -> bool:
    """递归查找 JSON 结构里是否存在某个键（用于「不得出现 target_sets」这类断言）。"""
    if isinstance(obj, dict):
        return key in obj or any(_find_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_find_key(v, key) for v in obj)
    return False


# ---------------------------------------------------------------------------
# 守卫 1：配置权威在 scene.abyss
# ---------------------------------------------------------------------------
def _config_source_failures(root: Path | None = None) -> list:
    _paths()
    from scene.abyss import ABYSS_EX, ZHONGSHI_TABS  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _abyss_pipe(root)

    # abyss_impl 的冻结快照必须与 scene 真源逐字一致（安装态回退不能漂）。
    import abyss_impl as ab  # noqa: PLC0415

    for name, snap, truth in (
        ("ZHONGSHI_TABS", tuple(ab._ZHONGSHI_TABS_SNAPSHOT), tuple(ZHONGSHI_TABS)),
        ("MAX_STAGES", ab._MAX_STAGES_SNAPSHOT, ABYSS_EX.max_stages),
        ("LEDGER_SCOPE", ab._LEDGER_SCOPE_SNAPSHOT, ABYSS_EX.ledger_scope),
        ("STAGE_RE", ab._STAGE_RE_SNAPSHOT, ABYSS_EX.stage_re),
        ("BANNER_TEMPLATE", ab._BANNER_TEMPLATE_SNAPSHOT, ABYSS_EX.banner_template),
        ("BANNER_THRESHOLD", ab._BANNER_THRESHOLD_SNAPSHOT, ABYSS_EX.banner_threshold),
        ("CONFIRM_TEXT", ab._CONFIRM_TEXT_SNAPSHOT, ABYSS_EX.confirm_text),
        ("HUB_MATCH", tuple(ab._HUB_MATCH_SNAPSHOT), tuple(ABYSS_EX.hub_match)),
        ("MAIN_MATCH", tuple(ab._MAIN_MATCH_SNAPSHOT), tuple(ABYSS_EX.main_match)),
        ("ACTIVE_STATES", tuple(ab._ACTIVE_STATES_SNAPSHOT), tuple(ABYSS_EX.active_states)),
    ):
        if snap != truth:
            msgs.append(f"配置漂移：abyss_impl 快照 {name}={snap!r} != scene.abyss 真源 {truth!r}")

    # pipeline 里的横幅模板 / 阈值 / 确认文案 / 页签列表必须来自配置。
    banner = _node(pipes, "AbyssBannerEx").get("recognition", {})
    bparam = banner.get("param", {}) if banner.get("type") == "TemplateMatch" else {}
    if bparam.get("template") != ABYSS_EX.banner_template:
        msgs.append(
            f"配置漂移：abyss.json::AbyssBannerEx.template={bparam.get('template')!r} "
            f"!= scene.abyss 真源 {ABYSS_EX.banner_template!r}"
        )
    if bparam.get("threshold") != ABYSS_EX.banner_threshold:
        msgs.append(
            f"配置漂移：abyss.json::AbyssBannerEx.threshold={bparam.get('threshold')!r} "
            f"!= scene.abyss 真源 {ABYSS_EX.banner_threshold!r}"
        )
    confirm = _node(pipes, "AbyssEnterConfirmText").get("recognition", {}).get("param", {})
    if (confirm.get("expected") or []) != [ABYSS_EX.confirm_text]:
        msgs.append(
            f"配置漂移：abyss.json::AbyssEnterConfirmText.expected={confirm.get('expected')!r} "
            f"!= scene.abyss 真源 [{ABYSS_EX.confirm_text!r}]"
        )
    return msgs


def probe_abyss_config_is_source_of_truth() -> bool:
    return _config_source_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：二级页签搜索数据驱动（不硬编码单个页签）
# ---------------------------------------------------------------------------
def _tab_search_failures(root: Path | None = None) -> list:
    _paths()
    from scene.abyss import ZHONGSHI_TABS, enter_from_any, tab_search_order  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _abyss_pipe(root)

    if len(ZHONGSHI_TABS) < 2:
        msgs.append(f"页签搜索不可数据化：scene.abyss.ZHONGSHI_TABS={ZHONGSHI_TABS!r} 少于 2 个")
    if tab_search_order() != tuple(ZHONGSHI_TABS):
        msgs.append("页签搜索顺序 != scene.abyss.ZHONGSHI_TABS（顺序即数据）")

    action = _action_param(_node(pipes, "AbyssNavTab"))
    if action.get("step") != "tab":
        msgs.append("abyss.json::AbyssNavTab 的 abyss_act 不是 step=tab（页签搜索被改坏）")
    tabs = action.get("tabs")
    if list(tabs or []) != list(ZHONGSHI_TABS):
        msgs.append(
            f"页签列表硬编码/漂移：abyss.json::AbyssNavTab.tabs={tabs!r} "
            f"!= scene.abyss.ZHONGSHI_TABS={list(ZHONGSHI_TABS)!r}"
        )

    # 横幅节点必须排在切页签之前（当前页签可见就直接进；否则才切下一个）。
    order = list(_node(pipes, "AbyssEntry").get("next") or [])
    if "AbyssNavBanner" not in order or "AbyssNavTab" not in order:
        msgs.append("AbyssEntry.next 缺少 AbyssNavBanner / AbyssNavTab（导航组被拆）")
    elif order.index("AbyssNavBanner") > order.index("AbyssNavTab"):
        msgs.append("AbyssNavBanner 必须排在 AbyssNavTab 之前（否则永远先切页签、找不到横幅）")

    # 「横幅在多个页签同时可见」的数据模型：数据顺序最靠前者被选中。
    if enter_from_any({"完成": True}) != "完成":
        msgs.append("enter_from_any：单一页签可见时未返回它")
    multi = enter_from_any({"已通关": True, "完成": True})
    if multi != "已通关":
        msgs.append(f"enter_from_any：多页签可见时应返回数据顺序最靠前者，实际 {multi!r}")
    if enter_from_any({}) is not None:
        msgs.append("enter_from_any：都不可见时应返回 None")
    return msgs


def probe_abyss_tab_search_data_driven() -> bool:
    return _tab_search_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：全单人、无共斗
# ---------------------------------------------------------------------------
_COOP_NODE_PREFIXES = ("AbyssCoop", "AbyssRecruit")
_COOP_STATE_TOKENS = ("abyss_coop", "abyss_recruit", "coop_room", "recruit_dialog")


def _no_coop_failures(root: Path | None = None) -> list:
    _paths()
    msgs: list[str] = []
    pipes = _abyss_pipe(root)

    # (1) pipeline 节点名不得是共斗房 / 招募。
    coop_nodes = [n for n in pipes if n.startswith(_COOP_NODE_PREFIXES)]
    if coop_nodes:
        msgs.append(f"共斗残留：abyss.json 含共斗节点 {coop_nodes}（运维：深渊EX 只有单人，没有共斗）")
    # (2) 任何自定义动作参数里不得出现「招募 / 建立房间 / 多人」这类共斗动作。
    for name, node in pipes.items():
        ap = _action_param(node)
        for bad in ("招募", "建立房间", "多人游戏", "开始招募"):
            if bad in (ap.get("what") or []):
                msgs.append(f"共斗残留：{name} 的 abyss_act.what 含 {bad!r}")

    # (3) 状态机里不得出现共斗状态。
    import abyss_impl as ab  # noqa: PLC0415

    for tok in _COOP_STATE_TOKENS:
        if tok in tuple(ab.ACTIVE_STATES):
            msgs.append(f"共斗残留：abyss_impl.ACTIVE_STATES 含 {tok!r}")
    src = Path(ab.__file__).read_text(encoding="utf-8")
    for tok in _COOP_STATE_TOKENS:
        if tok in src:
            msgs.append(f"共斗残留：abyss_impl 含共斗状态 {tok!r}（单人路径不得有共斗状态）")

    # (4) 分类器对「共斗房」形态的帧不得给出任何 abyss_* 状态。
    coop_items = [
        ("房间号码", [100, 300, 200, 40]),
        ("招募", [400, 900, 80, 40]),
        ("复制", [500, 900, 80, 40]),
    ]
    state, _ = ab.classify(coop_items)
    if state.startswith("abyss_"):
        msgs.append(f"共斗误判：classify 对共斗房形态帧给出 {state!r}（应 unknown/非 abyss 状态）")
    return msgs


def probe_abyss_solo_no_coop() -> bool:
    return _no_coop_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：30 层线性阶梯、无「套」概念
# ---------------------------------------------------------------------------
def _ladder_failures(root: Path | None = None) -> list:
    _paths()
    from scene.abyss import ABYSS_EX  # noqa: PLC0415
    import abyss_impl as ab  # noqa: PLC0415

    msgs: list[str] = []
    if ABYSS_EX.max_stages != 30:
        msgs.append(f"阶梯规模：scene.abyss.ABYSS_EX.max_stages={ABYSS_EX.max_stages} != 30")
    if ab.MAX_STAGES != 30:
        msgs.append(f"阶梯规模：abyss_impl.MAX_STAGES={ab.MAX_STAGES} != 30")
    if ab.LEDGER_SCOPE != "abyss":
        msgs.append(f"账本范围：abyss_impl.LEDGER_SCOPE={ab.LEDGER_SCOPE!r} != 'abyss'")
    # 阶段正则：第N战（不是幻想的 第N关）。
    if ab.parse_stage([("深渊连战EX第7战", [201, 1040, 237, 32])]) != 7:
        msgs.append("stage_re：parse_stage 未从『第7战』解析出 7")
    if ab.STAGE_RE.search("第3关") is not None:
        msgs.append("stage_re：不应命中幻想的『第N关』")
    # 无「套」/无 target_sets（结构化断言，不扫注释）。
    pipes = _abyss_pipe(root)
    if _find_key(pipes, "target_sets"):
        msgs.append("不应有「套」概念：abyss.json 的节点参数里含 target_sets 键")
    if hasattr(ab, "_read_target"):
        msgs.append("abyss_impl 不应有 _read_target（深渊没有「刷几套」）")
    iface = _load_jsonc((Path(root) if root is not None else REPO_ROOT) / INTERFACE_REL)
    for task in iface.get("task") or []:
        if task.get("name") == "自动刷深渊EX":
            opts = task.get("option") or []
            for bad in ("刷几套", "打到第几关以后放弃"):
                if bad in opts:
                    msgs.append(f"不应有「套」/关卡上限选项：任务『自动刷深渊EX』挂了 {bad!r}")
    # 账本键形状。
    if ab._stage_key(7) != "abyss/stage/7":
        msgs.append(f"账本键：_stage_key(7)={ab._stage_key(7)!r} != 'abyss/stage/7'")
    return msgs


def probe_abyss_ladder_30_no_sets() -> bool:
    return _ladder_failures() == []


# ---------------------------------------------------------------------------
# 守卫 5：横幅用模板匹配、阈值可靠区分纯深渊横幅
# ---------------------------------------------------------------------------
def _zncc(a, b) -> float:
    import numpy as np

    a = a - a.mean()
    b = b - b.mean()
    den = float(((a * a).sum() * (b * b).sum()) ** 0.5)
    return float((a * b).sum() / den) if den else 0.0


def _banner_distinct_failures(root: Path | None = None) -> list:
    _paths()
    from scene.abyss import ABYSS_EX, ABYSS_PLAIN  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    msgs: list[str] = []
    for tpl in (ABYSS_EX.banner_template, ABYSS_PLAIN.banner_template):
        if not (base / IMAGE_REL / tpl).is_file():
            msgs.append(f"横幅模板缺失：{IMAGE_REL}/{tpl} 不在仓库资源树下")

    pipes = _abyss_pipe(root)
    rec = _node(pipes, "AbyssBannerEx").get("recognition", {})
    if rec.get("type") != "TemplateMatch":
        msgs.append("横幅判据必须用模板匹配（TemplateMatch），不得用 OCR")
    thr = (rec.get("param") or {}).get("threshold")
    if not isinstance(thr, (int, float)) or thr <= _PLAIN_FALSE_POSITIVE:
        msgs.append(
            f"横幅阈值 {thr!r} 必须 > 纯深渊横幅的假阳分 {_PLAIN_FALSE_POSITIVE}"
            f"（否则 EX 模板会在纯深渊横幅上假阳）"
        )

    # 若 PIL/numpy 可用，直接复算 EX vs 纯深渊 的 ZNCC，证伪阈值。
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        def _gray(name):
            im = Image.open(base / IMAGE_REL / name).convert("L")
            return np.asarray(im, dtype=np.float64)

        cross = abs(_zncc(_gray(ABYSS_EX.banner_template), _gray(ABYSS_PLAIN.banner_template)))
        if isinstance(thr, (int, float)) and cross >= thr:
            msgs.append(
                f"横幅不可区分：EX vs 纯深渊 ZNCC={cross:.4f} >= 阈值 {thr}（会互相假阳）"
            )
        if cross > 0.95:
            msgs.append(f"横幅几乎相同：EX vs 纯深渊 ZNCC={cross:.4f}（模板裁片选错？）")
    except Exception:  # noqa: BLE001 - 无 PIL/numpy 时退回记录值断言
        pass
    return msgs


def probe_abyss_banner_distinct() -> bool:
    return _banner_distinct_failures() == []


# ---------------------------------------------------------------------------
# 守卫 6：classify 正例（真机形态的合成 OCR 帧）
# ---------------------------------------------------------------------------
def _classify_failures(mod) -> list:
    msgs: list[str] = []
    cases = [
        ("abyss_hub", [
            ("深渊连战EX", [247, 485, 255, 65]),
            ("兑换道具", [614, 328, 82, 28]),
            ("无尽战斗", [200, 700, 120, 30]),
            ("战斗", [600, 900, 60, 30]),
        ]),
        ("abyss_main", [
            ("深渊连战EX第1战", [201, 1040, 237, 32]),
            ("不可续战", [300, 980, 90, 30]),
            ("推荐编成", [56, 1114, 96, 30]),
            ("体力 0", [500, 900, 60, 30]),
        ]),
        ("abyss_solo_team", [
            ("SET 1", [17, 1062, 79, 24]),
            ("自动续战", [17, 1062, 79, 24]),
            ("挑战", [297, 1069, 80, 47]),
            ("编成", [513, 952, 45, 25]),
        ]),
        ("abyss_settle", [
            ("QUESTRESULT", [180, 380, 360, 60]),
            ("继续挑战", [446, 1183, 117, 33]),
        ]),
        ("abyss_battle", [
            ("时间 09:53", [300, 1200, 80, 30]),
            ("分数 0000001", [430, 1200, 120, 30]),
        ]),
        ("abyss_level_required", [
            ("玩家等级达到130后，解锁幻想连战与深渊连战。", [100, 800, 500, 80]),
        ]),
        ("main_city", [
            ("修行之道", [15, 725, 161, 45]),
            ("成长任务", [47, 368, 118, 33]),
            ("当前进度", [366, 928, 60, 20]),
            ("活动", [80, 1120, 62, 34]),
            ("领主战", [569, 1121, 78, 29]),
        ]),
        ("activity", [("亲爱的冒险者", [100, 300, 300, 40])]),
        ("zhongshi", [
            ("终始之战", [100, 462, 300, 60]),
            ("未通关", [119, 405, 90, 30]),
            ("已通关", [360, 405, 90, 30]),
            ("完成", [599, 406, 60, 30]),
        ]),
    ]
    for want, items in cases:
        got, _info = mod.classify([(t, b) for t, b in items])
        if got != want:
            msgs.append(f"classify 正例：{want!r} 得到 {got!r}")

    # 反例：EX hub 帧不得被当成 main（有 main 词才判 main）。
    got, _ = mod.classify([("深渊连战EX", [247, 485, 255, 65]), ("兑换道具", [614, 328, 82, 28])])
    if got != "abyss_hub":
        msgs.append(f"classify：EX hub 反例应为 abyss_hub，实际 {got!r}")
    # 反例：结算奖励条的「战斗分数」不得被当成战斗中。
    got, _ = mod.classify([("战斗分数", [430, 1200, 120, 30]), ("最长滞空时间6秒", [300, 1210, 200, 30])])
    if got == "abyss_battle":
        msgs.append("classify：只有『战斗分数』不得判为战斗中")
    return msgs


def probe_abyss_classify_positives() -> bool:
    _paths()
    import abyss_impl as ab  # noqa: PLC0415

    return _classify_failures(ab) == []


# ---------------------------------------------------------------------------
# 守卫 7：不污染全局页面判据表（「用注册表、别长全局表」）
#
# Phase 0 的页面判据注册表（scene.page_rules）是**领主战族**的全局唯一判据表 + 每场景
# 有序选取。深渊是第二类配置（scenario），它的页面锚定在 agent 侧（机制），**不得**把
# 深渊专属页面判据塞进全局 PAGE_RULES —— 那会「长全局表」并让 #37 的链上步骤页集退化
# 成累积并集（ADR-0003 要消灭的状态）。本守卫用它自身的 API 证明全局表没被撑大。
# ---------------------------------------------------------------------------
def _global_growth_failures(names) -> list:
    return [f"深渊不得把页面判据加进全局表：{n!r}" for n in names if "深渊" in n]


def _no_global_growth_failures() -> list:
    _paths()
    from scene.page_rules import (  # noqa: PLC0415
        _EXPECTED_DEFAULT_CHAIN_STEP_PAGES,
        chain_step_pages,
        duplicate_rule_names,
        page_rules,
    )

    msgs = _global_growth_failures([r.name for r in page_rules()])
    if duplicate_rule_names():
        msgs.append(f"全局判据表出现重名：{duplicate_rule_names()}")
    if tuple(chain_step_pages()) != tuple(_EXPECTED_DEFAULT_CHAIN_STEP_PAGES):
        msgs.append("缺省场景（领主战族）的链上步骤页集被深渊污染（应为派生结果，不是累积并集）")
    return msgs


def probe_abyss_no_global_table_growth() -> bool:
    return _no_global_growth_failures() == []


# ---------------------------------------------------------------------------
# 守卫 8：普通深渊 = 同一实现 + 场景数据（#55 Phase 3，「只差导航」）
#
# 运维：「深渊和深渊EX 只有导航的区别」。本守卫钉死「不 fork」：两个场景 id（abyss /
# abyss_plain）共用同一份实现（abyss_impl 的 _REGISTRY），差异只落成【数据】（横幅模板 /
# 进关确认文案 / 账本范围）；流水线用【场景门控】确保普通深渊任务**不**误点「未通关」
# 页签里可见的 EX 横幅（校准 §3.2 坑 1：两条横幅美术几乎一样，EX 模板对纯横幅假阳 0.8708）。
# ---------------------------------------------------------------------------
def _plain_wired_failures(root: Path | None = None) -> list:
    _paths()
    from scene.abyss import ABYSS_EX, ABYSS_PLAIN  # noqa: PLC0415
    import abyss_impl as ab  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    msgs: list[str] = []

    # (1) 数据：普通深渊有自己的横幅模板 / 阈值 / 确认文案 / 账本范围 / 场景 id（与 EX 区分）。
    if not (base / IMAGE_REL / ABYSS_PLAIN.banner_template).is_file():
        msgs.append(
            f"普通深渊横幅模板缺失：{IMAGE_REL}/{ABYSS_PLAIN.banner_template} 不在仓库资源树下"
        )
    if ABYSS_PLAIN.banner_threshold <= _PLAIN_FALSE_POSITIVE:
        msgs.append(
            f"普通深渊横幅阈值 {ABYSS_PLAIN.banner_threshold!r} 必须 > 假阳分 {_PLAIN_FALSE_POSITIVE}"
        )
    if ABYSS_PLAIN.ledger_scope == ABYSS_EX.ledger_scope:
        msgs.append("普通深渊与 EX 的账本范围相同（两条阶梯会互相污染）")
    if ABYSS_PLAIN.confirm_text == ABYSS_EX.confirm_text:
        msgs.append("普通深渊与 EX 的进关确认文案相同（应为去 EX 的那条）")
    if ABYSS_PLAIN.scene == ABYSS_EX.scene:
        msgs.append("普通深渊与 EX 的场景 id 相同（无法按场景 id 参数化）")

    # (2) 实现：同一份实现按场景 id 解析两个场景（不 fork 状态机）。
    if "abyss_plain" not in ab.SCENES:
        msgs.append(f"abyss_impl 未登记普通深渊场景：SCENES={ab.SCENES!r}")
    else:
        plain_cfg = ab._cfg(ABYSS_PLAIN.scene)
        if plain_cfg.scene != ABYSS_PLAIN.scene:
            msgs.append(f"abyss_impl._cfg({ABYSS_PLAIN.scene!r}).scene={plain_cfg.scene!r} 漂移")
        if plain_cfg.ledger_scope != ABYSS_PLAIN.ledger_scope:
            msgs.append(
                f"abyss_impl._cfg({ABYSS_PLAIN.scene!r}).ledger_scope={plain_cfg.ledger_scope!r} "
                f"!= scene.abyss {ABYSS_PLAIN.ledger_scope!r}"
            )
    if ab.DEFAULT_SCENE != ABYSS_EX.scene:
        msgs.append(f"abyss_impl.DEFAULT_SCENE={ab.DEFAULT_SCENE!r} != EX {ABYSS_EX.scene!r}")

    # (3) 流水线：普通深渊的 入口 / 横幅 / 确认 在场且派生自数据。
    pipes = _abyss_pipe(root)
    eparam = _recognition_param(_node(pipes, "AbyssPlainEntry"))
    econ = eparam.get("custom_recognition_param") or {}
    if eparam.get("custom_recognition") != "abyss_scene" or not econ.get("set"):
        msgs.append("abyss.json::AbyssPlainEntry 不是 abyss_scene set=true（未声明活动场景）")
    if econ.get("scene") != ABYSS_PLAIN.scene:
        msgs.append(
            f"abyss.json::AbyssPlainEntry.scene={econ.get('scene')!r} "
            f"!= scene.abyss {ABYSS_PLAIN.scene!r}"
        )
    bplain = _node(pipes, "AbyssBannerPlain").get("recognition", {})
    bp = bplain.get("param", {}) if bplain.get("type") == "TemplateMatch" else {}
    if bp.get("template") != ABYSS_PLAIN.banner_template:
        msgs.append(
            f"abyss.json::AbyssBannerPlain.template={bp.get('template')!r} "
            f"!= scene.abyss {ABYSS_PLAIN.banner_template!r}"
        )
    if bp.get("threshold") != ABYSS_PLAIN.banner_threshold:
        msgs.append(
            f"abyss.json::AbyssBannerPlain.threshold={bp.get('threshold')!r} "
            f"!= scene.abyss {ABYSS_PLAIN.banner_threshold!r}"
        )
    pconfirm = _recognition_param(_node(pipes, "AbyssPlainEnterConfirmText"))
    if (pconfirm.get("expected") or []) != [ABYSS_PLAIN.confirm_text]:
        msgs.append(
            f"abyss.json::AbyssPlainEnterConfirmText.expected={pconfirm.get('expected')!r} "
            f"!= scene.abyss [{ABYSS_PLAIN.confirm_text!r}]"
        )

    # (3b) 场景门控：EX 横幅 / 普通深渊横幅 / 普通深渊确认框各带自己的场景门控叶 ——
    #      否则普通深渊任务会在「未通关」页签误点 EX 横幅（两条横幅美术几乎一样）。
    def _all_of(node_name: str):
        rec = _node(pipes, node_name).get("recognition", {})
        if rec.get("type") != "And":
            return None
        return list((rec.get("param") or {}).get("all_of") or [])

    ex_nav = _all_of("AbyssNavBanner")
    if ex_nav is None or "AbyssSceneEx" not in ex_nav:
        msgs.append("abyss.json::AbyssNavBanner 缺 AbyssSceneEx 场景门控（普通深渊任务会误点 EX 横幅）")
    plain_nav = _all_of("AbyssPlainNavBanner")
    if plain_nav is None or "AbyssBannerPlain" not in plain_nav or "AbyssScenePlain" not in plain_nav:
        msgs.append("abyss.json::AbyssPlainNavBanner 必须 And(门控, AbyssBannerPlain, AbyssScenePlain)")
    plain_confirm = _all_of("AbyssPlainEnterConfirm")
    if plain_confirm is None or "AbyssScenePlain" not in plain_confirm:
        msgs.append("abyss.json::AbyssPlainEnterConfirm 缺 AbyssScenePlain 场景门控（与 EX 确认框歧义）")

    # (4) 分派器：普通深渊的导航 / 确认节点接进同一个 AbyssEntry.next（不复制分派表）。
    order = list(_node(pipes, "AbyssEntry").get("next") or [])
    for must in ("AbyssPlainNavBanner", "AbyssPlainEnterConfirm"):
        if must not in order:
            msgs.append(f"AbyssEntry.next 缺少 {must}（普通深渊导航/确认未接入共用分派器）")
    if "AbyssPlainNavBanner" in order and "AbyssNavTab" in order:
        if order.index("AbyssPlainNavBanner") > order.index("AbyssNavTab"):
            msgs.append("AbyssPlainNavBanner 必须排在 AbyssNavTab 之前（否则先切页签、找不到横幅）")

    # (5) 任务：interface.json 有「自动刷深渊」，入口指向 AbyssPlainEntry。
    iface = _load_jsonc(base / INTERFACE_REL)
    tasks = {t.get("name"): t for t in (iface.get("task") or [])}
    plain_task = tasks.get("自动刷深渊")
    if plain_task is None:
        msgs.append("interface.json 缺少任务『自动刷深渊』")
    elif plain_task.get("entry") != "AbyssPlainEntry":
        msgs.append(f"任务『自动刷深渊』entry={plain_task.get('entry')!r} != 'AbyssPlainEntry'")

    # (6) 注册：abyss_scene 在 agent 侧与 runner 侧都可解析（真机才不会静默 no-op）。
    reco = (REPO_ROOT / "agent" / "my_reco.py").read_text(encoding="utf-8")
    if 'custom_recognition("abyss_scene")' not in reco:
        msgs.append("agent/my_reco.py 未注册 abyss_scene")
    harness = (REPO_ROOT / "tools" / "live_harness.py").read_text(encoding="utf-8")
    if '"abyss_scene"' not in harness:
        msgs.append("tools/live_harness.py 的 CUSTOM_RECOGNITIONS 未登记 abyss_scene")
    return msgs


def probe_abyss_plain_wired() -> bool:
    return _plain_wired_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_abyss.py`）
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook55_"))
    (root / "assets").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "assets" / "resource", root / "assets" / "resource")
    shutil.copy2(REPO_ROOT / INTERFACE_REL, root / INTERFACE_REL)
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


class _BrokenClassify:
    """把结算误判为战斗中的坏模块（守卫必须抓到）。"""

    @staticmethod
    def classify(items, relogin_phrases=()):
        _paths()
        import abyss_impl as ab  # noqa: PLC0415

        state, info = ab.classify(items, relogin_phrases)
        if state == "abyss_settle":
            return "abyss_battle", info
        return state, info


def _break_and_check(label: str, mutate, run) -> bool:
    root = _temp_assets()
    try:
        mutate(root)
        red = len(run(root)) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}")
        return red
    finally:
        shutil.rmtree(root, ignore_errors=True)


def prove_red() -> bool:
    _paths()
    print("hooks_abyss prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_abyss_config_is_source_of_truth() is True
        and probe_abyss_tab_search_data_driven() is True
        and probe_abyss_solo_no_coop() is True
        and probe_abyss_ladder_30_no_sets() is True
        and probe_abyss_banner_distinct() is True
        and probe_abyss_classify_positives() is True
        and probe_abyss_no_global_table_growth() is True
        and probe_abyss_plain_wired() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：八个守卫全绿")
    if not green:
        return False

    pipe = lambda r: r / PIPELINE_REL / ABYSS_JSON  # noqa: E731
    checks = [
        _break_and_check(
            "配置漂移：改 abyss.json 的横幅模板名",
            lambda r: _sub(pipe(r), '"template": "banner_abyss_ex.png"', '"template": "banner_wrong.png"'),
            lambda r: _config_source_failures(r),
        ),
        _break_and_check(
            "页签硬编码：把 tabs 收成只剩一个页签",
            lambda r: _sub(
                pipe(r),
                '"tabs": ["未通关", "已通关", "完成"]',
                '"tabs": ["未通关"]',
            ),
            lambda r: _tab_search_failures(r),
        ),
        _break_and_check(
            "共斗残留：往 abyss.json 注入共斗房节点",
            lambda r: _sub(
                pipe(r),
                '"AbyssWait": {',
                '"AbyssCoopRecruit": { "recognition": { "type": "DirectHit", "param": {} }, "action": { "type": "DoNothing", "param": {} } },\n    "AbyssWait": {',
            ),
            lambda r: _no_coop_failures(r),
        ),
        _break_and_check(
            "「套」概念：往 abyss.json 注入 target_sets / 刷几套",
            lambda r: _sub(pipe(r), '"no_progress_sec": 900', '"no_progress_sec": 900,\n                    "target_sets": 1'),
            lambda r: _ladder_failures(r),
        ),
        _break_and_check(
            "横幅阈值：把 0.90 降到 0.50（不再区分纯深渊）",
            lambda r: _sub(pipe(r), '"threshold": 0.90', '"threshold": 0.50'),
            lambda r: _banner_distinct_failures(r),
        ),
        _break_and_check(
            "普通深渊确认文案漂移：把 AbyssPlainEnterConfirmText 改成去 EX 的那条=EX 文案",
            lambda r: _sub(pipe(r), '"expected": ["挑战深渊连战"]', '"expected": ["挑战深渊连战EX"]'),
            lambda r: _plain_wired_failures(r),
        ),
        _break_and_check(
            "普通深渊缺场景门控：从 AbyssNavBanner 摘掉 AbyssSceneEx（会误点 EX 横幅）",
            lambda r: _sub(
                pipe(r),
                '"AbyssZhongshiGate", "AbyssBannerEx", "AbyssSceneEx"',
                '"AbyssZhongshiGate", "AbyssBannerEx"',
            ),
            lambda r: _plain_wired_failures(r),
        ),
        _break_and_check(
            "普通深渊任务入口漂移：把『自动刷深渊』的 entry 指向 AbyssEntry",
            lambda r: _sub(
                r / INTERFACE_REL, '"entry": "AbyssPlainEntry"', '"entry": "AbyssEntry"'
            ),
            lambda r: _plain_wired_failures(r),
        ),
    ]
    red_classify = len(_classify_failures(_BrokenClassify)) > 0
    print(f"  [{'PASS' if red_classify else 'FAIL'}] classify：把结算误判为战斗中 -> "
          f"{'红' if red_classify else '仍绿'}")
    checks.append(red_classify)

    red_growth = len(_global_growth_failures(["深渊枢纽"])) > 0
    print(f"  [{'PASS' if red_growth else 'FAIL'}] 全局表污染：往全局判据表塞一条深渊页面 -> "
          f"{'红' if red_growth else '仍绿'}")
    checks.append(red_growth)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "abyss-config-is-source-of-truth",
        "#55",
        "深渊EX 配置权威在 scene.abyss：abyss_impl 快照 + abyss.json 模板/阈值/确认文案/页签均派生自它",
        probe_abyss_config_is_source_of_truth,
    ),
    (
        "abyss-tab-search-data-driven",
        "#55",
        "终始之战二级页签搜索数据驱动（页签列表可配置、不硬编码；横幅节点先于切页签；多页签数据模型）",
        probe_abyss_tab_search_data_driven,
    ),
    (
        "abyss-solo-no-coop",
        "#55",
        "全单人、无共斗：abyss.json / abyss_impl 不含共斗房 / 招募 / 建立房间 / 多人",
        probe_abyss_solo_no_coop,
    ),
    (
        "abyss-ladder-30-no-sets",
        "#55",
        "30 层线性阶梯、不关心套数：MAX_STAGES=30、ledger_scope=abyss、第N战、无 target_sets/刷几套",
        probe_abyss_ladder_30_no_sets,
    ),
    (
        "abyss-banner-distinct",
        "#55",
        "EX 横幅用模板匹配且阈值可靠区分纯深渊横幅（阈值 > 实测假阳分 0.874）",
        probe_abyss_banner_distinct,
    ),
    (
        "abyss-classify-positives",
        "#55",
        "abyss_impl.classify 对 hub/main/单人编队/结算/战斗/需要130级/主城/活动/终始之战 正判",
        probe_abyss_classify_positives,
    ),
    (
        "abyss-no-global-table-growth",
        "#55",
        "深渊不改全局页面判据表（用注册表 API 证明：无重名、无深渊页面、缺省场景链页集未被污染）",
        probe_abyss_no_global_table_growth,
    ),
    (
        "abyss-plain-wired",
        "#55",
        "普通深渊 = 同实现 + 数据（场景 id 参数化；横幅/确认/账本范围派生自 scene.abyss；"
        "场景门控防误点 EX 横幅；任务『自动刷深渊』入口 = AbyssPlainEntry）",
        probe_abyss_plain_wired,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
