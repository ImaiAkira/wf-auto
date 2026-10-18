# -*- coding: utf-8 -*-
"""#37：任何被注入的事件都不得命中【链上步骤页面】—— #18/#29/#37 的共同不变量。

seam：``scene.events``（被注入事件的枚举）+ ``scene.page_rules``（链上步骤页面集合，
``chain_step_pages``）+ ``assets/resource/pipeline/common.json``（``PubNewCharText`` 判据）
+ ``scene.drift``（pipeline 读取 + 页面判据来源映射）。

背景（真机实证）
----------------
* #18：归位（兜底型注入）在【主城】自匹配 → 点空 → 死循环；
* #29：归位在【列表页 / 详情页】自匹配 → 滚动找行永不执行 → 只打得到首屏 3 个；
* #37：新角色（打断型注入）在【**降临讨伐列表页**】自匹配 —— 列表行 NEW 徽标实测
  ``box=[14,877,54,25]`` / ``[14,1021,52,24]``（中心 (41,889)/(40,1033)）落在
  ``PubNewCharText`` 的 ROI ``[0,800,400,340]`` 内 → 公共事件点自己的框心（打开【别人】的
  详情页）→ 链无法恢复（``SpecialEnterBoss`` 要目标名、``SpecialScrollList`` 要「更新列表」
  详情页都没有；#29 又在链上页面关掉了归位）→ 循环到超时。真机 16408 上 14/14 全挂。

三者同构，故本票把它做成**一条通用不变量**（不是只修这一个节点）：

    ★链上步骤页面 ∩ 被注入事件 = ∅★

用**真机帧模型**逐「被注入事件 × 链上步骤页面」验证。本文件是它的验证器 + prove-red。

三个守卫
--------
1. ``injected-events-not-on-chain-pages`` —— 遍历 ``scene.events.injected_event_nodes()``
   里的每个事件节点，对其 recognition 在每张**链上步骤页真机帧**（主城 / 领主战列表页 /
   降临讨伐列表页 / 详情页 / 编队页 / 加成弹窗）上求值，命中即红。**唯一豁免**是同判据页
   （事件与链步认同一页同一按钮，如 ``PubChallenge`` 与 ``SpecialChallenge`` 都认编队页的
   「挑战」；``SpecialBonusNo`` 事件与链步同节点）—— 豁免会点名打印，绝不静默。
2. ``new-char-tap-not-on-list`` —— #37 的判据级正反例：``PubNewCharTap`` 在**列表页真机帧**
   （含 NEW 徽标）上**不命中**，在**真正该弹「新角色」的页面帧**上**命中**。
3. ``new-char-hijack-loop-repro`` —— 离线复现本次循环：从 ``SpecialEntry`` 出发、屏幕=降临
   讨伐列表页。旧形态（判据 ROI ``[0,800,400,340]``）：``PubNewCharTap`` 抢跑、打开别人的
   详情页、**永远到不了目标详情**（循环到上限）；新形态（真实产物）：``PubNewCharTap`` 不
   命中、``SpecialEnterBoss`` 命中目标行 → **到达目标详情**。

★关于 MAA 的 OCR roi★：真实 MAA 是【先按 roi 裁剪、再 OCR】（离线实测：把 ROI 左边界裁进
徽标中间，OCR 就读不出 "NEW"）。故本文件用「裁剪保读率」模型（``VISIBLE_MIN``）而不是
hooks_29 的「中心点落入 ROI」模型 —— 否则会把「行小徽标（宽 54，裁掉左 27px 只剩一半）
读不出、大徽标（宽 252，裁掉同样 27px 仍读全）」这一真实现象建模错。该模型由
``tools/test_inject_scope.py`` 的真机帧 MAA 回放（best-effort）交叉验证。

★prove-red★（``python tools\\contract_hooks\\hooks_37.py``）：
    * 把 ``PubNewCharText`` 的 ROI 改回 ``[0,800,400,340]`` → 守卫 1/2 变红（新角色又在
      列表页命中）；
    * 去掉归位的页面范围判别叶 ``PubReturnHomeOtherSection`` → 守卫 1 变红（归位又在链上
      列表页命中）—— 证明本通用不变量**覆盖 #29**。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

_PIPELINE_REL = "assets/resource/pipeline"
_COMMON = "common.json"
_SD = "special_dungeon.json"

# 裁剪保读率阈值：一个 OCR 文本框落在识别 ROI 内的面积占比 ≥ 此值才算「读得出」。
# 依据真机实测：大 NEW 徽标（宽 252）裁掉左侧 27px（≈89% 保留）仍读作 "NEW"；列表行小
# NEW 徽标（宽 54）裁掉同样 27px（≈52% 保留）读不出。0.7 落在这两条实测之间。
VISIBLE_MIN = 0.7


# ---------------------------------------------------------------------------
# 真机帧模型（720 空间 OCR 条目；括号里是帧来源）
# ---------------------------------------------------------------------------
_ZERO = {"角色": 0, "商店": 0, "扭蛋": 0, "菜单": 0}
_NAV = [
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1246, 45, 27]),
]

# 主城（sweepjoss/recon_00_maincity.png）：底导最左槽是「城镇」而非「返回」。
_MAIN_CITY_ITEMS = [
    ("城镇", [31, 1245, 47, 27]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1246, 45, 27]),
    ("领主战", [569, 1121, 78, 29]),
    ("修行之道", [17, 728, 159, 41]),
    ("活动", [82, 1122, 59, 31]),
    ("关卡", [313, 1088, 93, 49]),
    ("当前进度", [369, 928, 59, 20]),
]

# 领主战列表页（sweepjoss/recon_01_list_lord.png）：一个行 NEW 徽标，落在旧 ROI 内。
_LORD_LIST_ITEMS = [
    ("NEW", [13, 1021, 57, 24]),
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 47, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
    ("更新列表", [615, 328, 82, 28]),
    ("降临讨伐", [481, 389, 117, 32]),
    ("猩红巨熊讨伐", [201, 637, 166, 32]),
    ("背鳍三兄弟讨伐", [202, 781, 193, 32]),
    ("八岐大蛇讨伐", [201, 928, 165, 28]),
    ("妖狐讨伐", [201, 1069, 114, 33]),
]

# 降临讨伐列表页（sweepjoss/recon_02_list_joss.png）★#37 的关键反例帧★：三个行 NEW 徽标。
_JOSS_LIST_ITEMS = [
    ("NEW", [13, 733, 54, 25]),
    ("NEW", [14, 877, 54, 25]),
    ("NEW", [14, 1021, 52, 24]),
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [276, 1246, 46, 27]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
    ("更新列表", [615, 328, 82, 28]),
    ("领主战", [135, 388, 90, 34]),
    ("降临讨伐", [481, 388, 117, 33]),
    ("红嫉机兵", [199, 925, 116, 33]),
    ("无猾机兵", [201, 781, 114, 33]),
    ("苍叹机兵", [201, 1069, 114, 33]),
]

# 详情页（sweepjoss/recon_03_detail.png）：无「更新列表」、无底部行徽标。
_DETAIL_ITEMS = [
    ("NEW", [18, 389, 46, 20]),
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [276, 1246, 45, 26]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1248, 45, 25]),
    ("推荐编成", [55, 530, 97, 30]),
    ("战斗", [88, 501, 29, 16]),
    ("红嫉族机兵", [191, 149, 382, 99]),
    ("降临讨伐", [202, 428, 91, 28]),
    ("红机兵海茵莱特中", [203, 458, 253, 28]),
    ("体力", [361, 534, 50, 24]),
    ("兑换道具", [614, 328, 82, 28]),
]

# 编队页（tools/frames/lord_team_page.png）：底部「挑战」+ 左上「返回」，无底导整条。
_TEAM_ITEMS = [
    ("返回", [31, 1247, 45, 25]),
    ("挑战", [296, 1055, 82, 45]),
    ("等级100", [41, 815, 89, 29]),
    ("编成", [513, 952, 46, 25]),
    ("战力", [525, 516, 41, 25]),
    ("自动续战", [17, 1061, 81, 28]),
]

# 加成弹窗（tools/frames/lord_bonus_dialog.png）：「领主加成点数」+ 左下「返回」。
_BONUS_ITEMS = [
    ("返回", [31, 1245, 44, 27]),
    ("“领主加成点数”吗？", [235, 539, 250, 32]),
    ("猩红巨熊", [229, 191, 258, 75]),
    ("要使用增加报酬的", [247, 504, 223, 28]),
    ("领主战", [325, 271, 69, 28]),
]

# 链上步骤页真机帧（反例：任何被注入事件都不得命中）。``page`` 用于查
# scene.drift.PAGE_RULE_SOURCES（同判据豁免只在「事件认的是这一页」时成立）。
CHAIN_PAGE_FRAMES: list[dict] = [
    {"name": "主城", "page": "主城",
     "source": "tools/frames + sweepjoss/recon_00_maincity.png",
     "items": _MAIN_CITY_ITEMS, "orange": dict(_ZERO)},
    {"name": "领主战列表页", "page": "领主战列表页",
     "source": "sweepjoss/recon_01_list_lord.png",
     "items": _LORD_LIST_ITEMS, "orange": dict(_ZERO)},
    {"name": "降临讨伐列表页", "page": "领主战列表页",
     "source": "sweepjoss/recon_02_list_joss.png",
     "items": _JOSS_LIST_ITEMS, "orange": dict(_ZERO)},
    {"name": "详情页", "page": "详情页",
     "source": "sweepjoss/recon_03_detail.png",
     "items": _DETAIL_ITEMS, "orange": dict(_ZERO)},
    {"name": "编队页", "page": "编队页",
     "source": "tools/frames/lord_team_page.png",
     "items": _TEAM_ITEMS, "orange": dict(_ZERO)},
    {"name": "加成弹窗", "page": "加成弹窗",
     "source": "tools/frames/lord_bonus_dialog.png",
     "items": _BONUS_ITEMS, "orange": dict(_ZERO)},
]

# 「真正该弹新角色」的页面帧（正例）。大 NEW 徽标为设备实测 720 box ≈ (13,845,252,153)
# （见 common.json::PubNewCharText 上方注释的原始 1080 实测 box=[19,1268,378,230]）。
# 可与环境变量 WF_R37_NEWCHAR 指向的真机 PNG 并用（best-effort，见 test_inject_scope.py）。
NEWCHAR_POSITIVE_FRAME: dict = {
    "name": "新角色加入画面（大 NEW 徽标）",
    "page": None,  # 不是链上步骤页
    "source": "设备实测 box (13,845,252,153)（common.json 原始 1080 实测换算）",
    "items": [("NEW", [13, 845, 252, 153])],
    "orange": dict(_ZERO),
}

# #37 判据级正反例用到的帧（列表页 = 反例；真正该弹新角色的页 = 正例）。
_LIST_FRAMES = [f for f in CHAIN_PAGE_FRAMES if f["page"] == "领主战列表页"]


# ---------------------------------------------------------------------------
# 离线 recognition 求值器（OCR / And / Or / ColorMatch；DirectHit=True；Custom=不命中）
#  OCR 的 roi 按【裁剪保读率】建模（真实 MAA：先裁剪再 OCR）。
# ---------------------------------------------------------------------------
def _box_visible_fraction(box, roi) -> float:
    x, y, w, h = box
    if w <= 0 or h <= 0 or roi is None:
        return 0.0
    ix0, iy0 = max(x, roi[0]), max(y, roi[1])
    ix1, iy1 = min(x + w, roi[0] + roi[2]), min(y + h, roi[1] + roi[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    return (iw * ih) / float(w * h)


def _ocr_hit(rec: dict, items) -> bool:
    param = rec.get("param") or {}
    pats = param.get("expected") or [".*"]
    roi = param.get("roi")
    for text, box in items:
        if not any(re.search(p, text or "") for p in pats):
            continue
        if roi is None:
            return True
        if _box_visible_fraction(box, roi) >= VISIBLE_MIN:
            return True
    return False


_TAB_ROIS = {
    "角色": [275, 1244, 46, 29],
    "商店": [397, 1246, 43, 26],
    "扭蛋": [516, 1246, 45, 26],
    "菜单": [636, 1248, 45, 25],
}


def _tab_key(roi):
    for name, r in _TAB_ROIS.items():
        if list(roi or []) == list(r):
            return name
    return None


def _color_hit(rec: dict, orange) -> bool:
    param = rec.get("param") or {}
    key = _tab_key(param.get("roi"))
    if key is None or orange is None:
        return False
    return int(orange.get(key, 0)) >= int(param.get("count", 1))


def eval_recognition(rec, items, resolve=None, orange=None) -> bool:
    """在给定真机帧模型（OCR 条目 + 分区橙色像素计数）上求一条 recognition。"""
    if not isinstance(rec, dict):
        return False
    kind = rec.get("type", "DirectHit")
    if kind == "DirectHit":
        return True
    if kind == "OCR":
        return _ocr_hit(rec, items)
    if kind == "ColorMatch":
        return _color_hit(rec, orange)
    if kind in ("And", "Or"):
        leaves = (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []
        hits = []
        for leaf in leaves:
            leaf_rec = resolve(leaf) if (isinstance(leaf, str) and resolve is not None) else leaf
            hits.append(eval_recognition(leaf_rec, items, resolve, orange))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测，视为不命中


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def _node(files: dict, name: str):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


def _files(root: Path | None = None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    return drift.load_pipelines(base / _PIPELINE_REL)


# ---------------------------------------------------------------------------
# 同判据豁免 + 守卫 1
# ---------------------------------------------------------------------------
def _ocr_expected_of(rec, resolve=None):
    """一条 recognition 的 OCR 断言集合（And/Or 递归；含非 OCR 叶则返回 None）。"""
    if not isinstance(rec, dict):
        return None
    kind = rec.get("type", "DirectHit")
    if kind == "OCR":
        return set((rec.get("param") or {}).get("expected") or [])
    if kind in ("And", "Or"):
        out: set = set()
        for leaf in (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []:
            sub = resolve(leaf) if (isinstance(leaf, str) and resolve is not None) else leaf
            got = _ocr_expected_of(sub, resolve)
            if got is None:
                return None
            out |= got
        return out
    return None


def _node_ocr_expected(files: dict, name: str):
    import scene.drift as drift  # noqa: PLC0415

    return _ocr_expected_of(drift._resolve_recognition(name, files), lambda n: drift._resolve_recognition(n, files))


#: ★#109★ 「同一按钮」判据等价：把**一个可选箭头**从正则里归一化掉再比。
#:   为什么：``SpecialChallenge{^挑战(→)?$}`` 不再字面包含于 ``PubChallenge{^挑战$}``，
#:   但真机上认的是**同一个按钮**（只差容不容忍箭头）；字面子集比较会把 PubChallenge
#:   误判成「命中编队页帧」。
#:   ★只放宽一个可选箭头★ —— 绝不退化成裸「挑战」（那样 `再次挑战` 也会中）。
_ARROW_GROUP = re.compile(r"(?:\(\?:→\)\?|\(→\)\?|\(→\)\*)")


def _norm_pattern(pat: str) -> str:
    """去掉「一个可选箭头」的写法差异，用于同按钮比较。"""
    return _ARROW_GROUP.sub("", pat or "")


def _same_button(chain, event) -> bool:
    """链步与事件认的是否同一按钮（字面等价，或只差一个可选箭头）。"""
    return {_norm_pattern(x) for x in chain} <= {_norm_pattern(x) for x in event}


def _exemption(files: dict, event_node: str, page: str | None):
    """返回豁免理由；不豁免则返回 None。

    合法豁免 = 「事件认的就是链上这一步的页面」（同判据）：链步节点的 OCR 断言是该事件
    OCR 断言的【子集】。例如「挑战」事件 ``PubChallenge``（``^挑战$``，无 ROI）与链步
    ``SpecialChallenge``（``^挑战$``，ROI 收窄）都认编队页底部同一按钮；``SpecialBonusNo``
    事件与链步同节点。此时事件命中该页不是「抢帧」，而是它本身即该页的通用识别。
    """
    if page is None:
        return None
    import scene.drift as drift  # noqa: PLC0415

    source = drift.PAGE_RULE_SOURCES.get(page)
    if source is None:
        return None
    chain_node = source[1]
    ev = _node_ocr_expected(files, event_node)
    ch = _node_ocr_expected(files, chain_node)
    if ev is None or ch is None or not ch:
        return None
    if _same_button(ch, ev):
        return (f"同判据豁免：事件 {event_node} 的 OCR 断言 {sorted(ev)} 覆盖链步 "
                f"{chain_node} 的 {sorted(ch)}（同一页同一按钮）")
    return None


def _injected_events_guard(files: dict) -> list:
    from scene.events import injected_event_nodes  # noqa: PLC0415

    resolve = _resolver(files)
    msgs: list = []
    for node in injected_event_nodes():
        import scene.drift as drift  # noqa: PLC0415

        rec = drift._resolve_recognition(node, files)
        if not isinstance(rec, dict):
            msgs.append(f"注入事件 {node!r} 在 pipeline 里找不到 recognition（引用悬空？）")
            continue
        for frame in CHAIN_PAGE_FRAMES:
            if not eval_recognition(rec, frame["items"], resolve, frame["orange"]):
                continue
            if _exemption(files, node, frame["page"]) is not None:
                continue
            msgs.append(
                f"注入事件命中链上步骤页：{node!r} 在「{frame['name']}」"
                f"（{frame['source']}，页面「{frame['page']}」）上命中 —— "
                f"链上步骤页面 ∩ 被注入事件 ≠ ∅（#18/#29/#37 同族）；"
                f"请收窄该事件的判据，使其不命中链上步骤页"
            )
    return msgs


def probe_injected_events_not_on_chain_pages() -> bool:
    """#37 通用不变量：任何被注入的事件都不得命中链上步骤页（真机帧模型）。"""
    return _injected_events_guard(_files()) == []


# ---------------------------------------------------------------------------
# 守卫 2：#37 判据级正反例（列表页不命中 / 真正该弹新角色的页命中）
# ---------------------------------------------------------------------------
def _new_char_scope_failures(files: dict) -> list:
    import scene.drift as drift  # noqa: PLC0415

    resolve = _resolver(files)
    rec = drift._resolve_recognition("PubNewCharTap", files)
    msgs: list = []
    if not isinstance(rec, dict):
        return ["#37：pipeline 里找不到 PubNewCharTap 的 recognition"]
    for frame in _LIST_FRAMES:
        hit = eval_recognition(rec, frame["items"], resolve, frame["orange"])
        if hit:
            msgs.append(
                f"#37 判据范围：PubNewCharTap 在反例帧「{frame['name']}」"
                f"（{frame['source']}，含行 NEW 徽标）上命中 —— 会在链上列表页抢跑"
            )
    pos = NEWCHAR_POSITIVE_FRAME
    if not eval_recognition(rec, pos["items"], resolve, pos["orange"]):
        msgs.append(
            f"#37 判据范围：PubNewCharTap 在正例帧「{pos['name']}」"
            f"（{pos['source']}）上不命中 —— 修过头了，真正该弹「新角色」的页面也点不掉"
        )
    return msgs


def probe_new_char_criterion_scope() -> bool:
    """#37 判据级正反例：列表页（含 NEW）= 反例不命中；大 NEW 徽标页 = 正例命中。"""
    return _new_char_scope_failures(_files()) == []


# ---------------------------------------------------------------------------
# 守卫 3：离线复现「列表页自匹配 → 打开别人的详情 → 循环到超时」
#
# 屏幕状态机：page ∈ {主城, 列表页, 详情页_目标, 详情页_别的}；MAA next / max_hit /
# [JumpBack] 语义同 hooks_19 / hooks_29。目标行 = 降临讨伐「红嫉机兵」（列表可见）。
# ---------------------------------------------------------------------------
_TARGET_ROW = "红嫉机兵"
_TARGET_DETAIL = "详情页_目标"
_OTHER_DETAIL = "详情页_别的"


class _Screen:
    def __init__(self, page: str = "主城"):
        self.page = page

    def items(self):
        if self.page == "主城":
            return list(_MAIN_CITY_ITEMS)
        if self.page == "列表页":
            return list(_JOSS_LIST_ITEMS)
        if self.page == _TARGET_DETAIL:
            return [*_DETAIL_ITEMS, (_TARGET_ROW, [199, 925, 116, 33])]
        # 别人的详情页：有目标名【以外】的东西，但没有目标行。
        return [*_DETAIL_ITEMS, ("苍叹机兵", [201, 1069, 114, 33])]

    def orange(self):
        return dict(_ZERO)


def _apply_action(name: str, screen: _Screen) -> None:
    if name in ("SpecialOpenLord", "SpecialTabLord", "SpecialTabJoss"):
        screen.page = "列表页"
    elif name == "SpecialEnterBoss" and screen.page == "列表页":
        screen.page = _TARGET_DETAIL
    elif name == "PubNewCharTap" and screen.page == "列表页":
        # 点击自己的识别框中心 = 列表行 NEW 徽标（别人的那一行）→ 打开别人的详情页。
        screen.page = _OTHER_DETAIL


def simulate(entry: str, screen: _Screen, files: dict, *, rec_overrides=None, max_steps: int = 300):
    """从 ``entry`` 出发按 MAA next / max_hit / [JumpBack] 语义走。返回 (到达目标详情?, 序列)。"""
    resolve = _resolver(files)
    counters: dict[str, int] = {}
    seq: list[str] = []
    reached = {"target": False}

    def node_spec(name: str):
        return _node(files, name) or {}

    def matches(name: str) -> bool:
        if rec_overrides and name in rec_overrides:
            rec = rec_overrides[name]
        else:
            import scene.drift as drift  # noqa: PLC0415

            rec = drift._resolve_recognition(name, files)
        return eval_recognition(rec, screen.items(), resolve, screen.orange())

    def dispatch(node_name: str, depth: int = 0):
        for ref in node_spec(node_name).get("next") or []:
            if depth > max_steps:
                return "LIMIT"
            jb = isinstance(ref, str) and ref.startswith("[JumpBack]")
            name = ref[len("[JumpBack]"):] if jb else ref
            mh = node_spec(name).get("max_hit")
            if mh is not None and counters.get(name, 0) >= mh:
                continue
            if not matches(name):
                continue
            seq.append(name)
            _apply_action(name, screen)
            counters[name] = counters.get(name, 0) + 1
            if screen.page == _TARGET_DETAIL:
                reached["target"] = True
                return "TARGET"
            r = dispatch(name, depth + 1)
            if r is not None:
                return r
            if jb:
                continue
        return None

    dispatch(entry)
    return reached["target"], seq


def _old_new_tap_rec() -> dict:
    """旧形态判据：ROI 回到 [0,800,400,340]（行 NEW 徽标也在其中）。"""
    return {
        "type": "And",
        "param": {"all_of": [
            {"type": "OCR", "param": {"expected": ["^NEW$"], "roi": [0, 800, 400, 340]}}
        ]},
    }


def _target_boss_rec() -> dict:
    """目标行判据（模拟『降临讨伐·红嫉机兵』选项对 SpecialEnterBoss 的覆盖）。"""
    return {"type": "OCR", "param": {"expected": [_TARGET_ROW], "roi": [150, 440, 320, 800]}}


def loop_traces(root: Path | None = None):
    """返回 (新形态(到达?, 序列), 旧形态(到达?, 序列)) —— 屏幕 = 降临讨伐列表页状态机。"""
    files = _files(root)
    overrides = {"SpecialEnterBoss": _target_boss_rec()}

    new_screen = _Screen("主城")
    new_reached, new_seq = simulate("SpecialEntry", new_screen, files, rec_overrides=dict(overrides))

    old_overrides = dict(overrides)
    old_overrides["PubNewCharTap"] = _old_new_tap_rec()
    old_screen = _Screen("主城")
    old_reached, old_seq = simulate("SpecialEntry", old_screen, files, rec_overrides=old_overrides)

    return (new_reached, new_seq), (old_reached, old_seq)


def _loop_failures(root: Path | None = None) -> list:
    (new_reached, new_seq), (old_reached, old_seq) = loop_traces(root)
    msgs: list = []
    if "PubNewCharTap" in new_seq:
        msgs.append(f"新形态仍命中 PubNewCharTap（列表页不该抢跑）：{new_seq[:10]}")
    if not new_reached:
        msgs.append(f"新形态未能到达目标详情：{new_seq[:12]}")
    if "SpecialEnterBoss" not in new_seq:
        msgs.append(f"新形态未经 SpecialEnterBoss 选目标行：{new_seq[:10]}")

    if "PubNewCharTap" not in old_seq:
        msgs.append(f"旧形态未复现抢跑（PubNewCharTap 未命中列表页）：{old_seq[:10]}")
    if old_reached:
        msgs.append(f"旧形态竟到达了目标详情（不应发生）：{old_seq[:12]}")
    # 旧形态应【循环到上限】而不是提前收尾：SpecialEntry / SpecialWait 反复出现。
    if old_seq.count("SpecialEntry") < 5:
        msgs.append(f"旧形态未复现『循环到超时』（SpecialEntry 反复出现次数不足）：{old_seq[:12]}")
    return msgs


def probe_new_char_hijack_loop_repro() -> bool:
    """#37 守卫 3：旧形态在列表页抢跑、到不了目标详情；新形态选目标行到达目标详情。"""
    return _loop_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_37.py`）
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook37_assets_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "assets" / "resource" / "pipeline",
        root / "assets" / "resource" / "pipeline",
    )
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_newchar_roi(root: Path) -> None:
    """产物级：把 PubNewCharText 的 ROI 改回 [0,800,400,340]（行 NEW 徽标又落进来）。"""
    _sub(
        root / _PIPELINE_REL / _COMMON,
        '"param": { "expected": ["^NEW$"], "roi": [40, 800, 360, 340] }',
        '"param": { "expected": ["^NEW$"], "roi": [0, 800, 400, 340] }',
    )


def _break_return_home_discriminator(root: Path) -> None:
    """产物级：把归位的页面范围判别叶去掉（回到 #18 的两叶形态 → 在列表页自匹配）。"""
    _sub(
        root / _PIPELINE_REL / _COMMON,
        '                    "PubReturnHomeBackTab",\n'
        '                    "PubReturnHomeOtherSection"\n',
        '                    "PubReturnHomeBackTab"\n',
    )


def prove_red() -> bool:
    """真实绿；改坏 #37 判据 / 去掉 #29 判别叶 -> 守卫各自变红。"""
    scene_on_path()
    print("hooks_37 prove-red：改坏 PubNewCharText ROI / 去掉归位判别叶，要求守卫各自变红")
    green = (
        probe_injected_events_not_on_chain_pages() is True
        and probe_new_char_criterion_scope() is True
        and probe_new_char_hijack_loop_repro() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：无被注入事件命中链上步骤页 + 正反例 + 复现（绿）")
    if not green:
        return False

    # (a) 改坏 #37 判据 -> 新角色又在列表页命中（守卫 1 / 2 红）。
    root = _temp_pipeline()
    try:
        _break_newchar_roi(root)
        files = _files(root)
        m1 = _injected_events_guard(files)
        m2 = _new_char_scope_failures(files)
        red_a = len(m1) > 0 and len(m2) > 0
        tail = f"  {m1[0]}" if m1 else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_a else 'FAIL'}] 改坏 PubNewCharText ROI -> "
              f"{'红' if red_a else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 去掉归位判别叶（#29）-> 归位又在链上列表页命中（通用不变量涵盖 #29）。
    root = _temp_pipeline()
    try:
        _break_return_home_discriminator(root)
        m = _injected_events_guard(_files(root))
        red_b = len(m) > 0
        tail = f"  {m[0]}" if m else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_b else 'FAIL'}] 去掉归位页面范围判别叶 -> "
              f"{'红' if red_b else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "injected-events-not-on-chain-pages",
        "#37",
        "通用不变量：任何被注入的事件都不得命中链上步骤页（真机帧模型，含 #18/#29 覆盖）",
        probe_injected_events_not_on_chain_pages,
    ),
    (
        "new-char-tap-not-on-list",
        "#37",
        "判据级正反例：PubNewCharTap 在降临讨伐列表页（含 NEW 徽标）不命中、在大 NEW 徽标页命中",
        probe_new_char_criterion_scope,
    ),
    (
        "new-char-hijack-loop-repro",
        "#37",
        "离线复现：旧形态在列表页抢跑到别人的详情并循环 / 新形态选目标行到达目标详情",
        probe_new_char_hijack_loop_repro,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
