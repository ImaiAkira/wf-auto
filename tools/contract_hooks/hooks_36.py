# -*- coding: utf-8 -*-
"""#36：``SpecialScrollList`` 的滑动手势必须【起终点都落在列表体内】——
绝不压在底部导航 / 左下「返回」ROI 上。

seam：``assets/resource/pipeline/special_dungeon.json``（``SpecialScrollList`` 的 Swipe 几何）
+ ``assets/resource/pipeline/common.json``（底导 / 返回 ROI 的来源节点）
+ ``scene.lord_battle``（真机行扫表的成员绑定）。

背景（真机实证，失败帧）
------------------------
``SpecialScrollList`` 的 Swipe 曾是 720 空间的 ``[360,1200] → [360,800]``，而起点
``y=1200`` 正落在底部导航 ROI ``[0,1180,720,100]`` **之内**（节点注释自称「列表中部
800~1200」，但真机列表体止于 ~1180，底导六槽标签在 y≈1245~1272）。后果：

    深行目标（要滑好几屏才看得到）→ 手势从底导控件上起手 → 列表不吃这一笔（画面不滚）
    → 手指抬起处（y≈800 那一行）被当成【选行】→ 打开【别人的】详情页 → 链无法恢复
    （``SpecialEnterBoss`` 要目标名、``SpecialScrollList`` 要「更新列表」，详情页两样都
    没有，只剩 DirectHit 的 ``SpecialEntry`` / ``SpecialWait`` 互跳）→ 空转到超时。

失败帧（``%TEMP%\\opencode\\sweep_lord\\frames_LA\\{end_list,baihu_last,unmframe_*}.jpg``）
全部停在 ``Sec-5200Li讨伐`` 的详情页上。行越深越易触发（行 6/8 可过；行 9/12/15 失败）。

这是 #29「归位抢跑」的**【同族病】**：手势作用在了【导航控件】上，只是换成了 Swipe。

两个守卫（prove-red 也在本文件里）
----------------------------------
1. ``scroll-gesture-avoids-nav-roi`` —— 读产品里 ``SpecialScrollList`` 的 Swipe，断言
   **起点与终点都落在列表体内**（``y ∈ [440, 1180]``），且**都不落在**任何「底部导航 /
   左下返回」ROI 内。那些 ROI **从产品枚举**（任何 ``^主城$``/``^返回$``/页签标签的 OCR
   节点 + 落在底导带内的 ColorMatch 节点），并把两个权威 ROI 与 hooks_36 的常量
   **逐字段绑定**（产品一改、守卫即提醒，绝不自说自话）。
2. ``deep-row-scroll-repro`` —— **离线复现「深行目标需要多次滑动」**：17 行领主战列表，
   目标 = **最末行** ``维·索拉斯讨伐``（真机行扫 ``sweep_lord_03.ocr.txt`` @y=1070）。
   * 旧形态（起点 y=1200，压在底导上）：滑到**别人的详情页**、**永远到不了**目标详情；
   * 新形态（真实产物）：滚到最末行 → ``SpecialEnterBoss`` 命中 → 到达**目标自己的详情页**。

★prove-red★（``python tools\\contract_hooks\\hooks_36.py``）：把产品里的起点退回 ``y=1200``
→ 两个守卫各自变红。
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
_SD = "special_dungeon.json"
_COMMON = "common.json"

SCROLL_NODE = "SpecialScrollList"

# ---------------------------------------------------------------------------
# 底部导航 / 左下返回：权威 ROI（720 空间，产品 `common.json` 里 PubReturnHome 判据的两叶）
#
# 「底部导航带」= 屏幕最下方那条常驻 tab 栏；真机实测它的 ROI 上沿 = 1180，六槽标签
# （返回 / 主城 / 角色 / 商店 / 扭蛋 / 菜单）在 y≈1245~1272。**列表体止于 1180**。
# 这两个常量会被 _binding_failures 与产品逐字段对照（产品一改即报红，防守卫与实现脱节）。
# ---------------------------------------------------------------------------
BOTTOM_NAV_ROI = [0, 1180, 720, 100]   # common.json::PubReturnHomeText 的 OCR ROI
BACK_SLOT_ROI = [0, 1180, 110, 100]    # common.json::PubReturnHomeBackTab 的 OCR ROI

_NAV_ANCHORS = {
    "PubReturnHomeText": BOTTOM_NAV_ROI,
    "PubReturnHomeBackTab": BACK_SLOT_ROI,
}

# 底导 / 返回控件的 OCR 断言（任何带这些串的 OCR 节点都算「导航控件」）。
_NAV_LABEL_PATTERNS = ("^主城$", "^返回$", "^角色$", "^商店$", "^扭蛋$", "^菜单$")

# 列表体（真机实测）：上沿 440 = 固定条（活动栏 y≈302、页签行 y≈388~421）之下；
# 下沿 = 底导带上沿 1180。行高 ≈ 144px，首屏 4~5 行（sweep_lord_00/01.ocr.txt）。
LIST_BODY_TOP = 440

# 受控滚动的行程范围（px）：太大变「甩动」会跳过目标（见节点注释的踩坑记录）。
_SWIPE_MIN_TRAVEL = 200
_SWIPE_MAX_TRAVEL = 600


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _files(root: Path | None = None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    return drift.load_pipelines(base / _PIPELINE_REL)


def _node(files: dict, name: str):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


def _resolve(files: dict, name: str):
    import scene.drift as drift  # noqa: PLC0415

    return drift._resolve_recognition(name, files)


# ---------------------------------------------------------------------------
# 几何小工具
# ---------------------------------------------------------------------------
def _pt(value) -> tuple[int, int] | None:
    """两点式 / 四点式的点：取前两个分量（MAA Swipe 的 begin/end 是 4 元素）。"""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _inside(point: tuple[int, int], roi) -> bool:
    x, y = point
    rx, ry, rw, rh = roi
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def _roi(rec) -> list | None:
    if not isinstance(rec, dict):
        return None
    roi = (rec.get("param") or {}).get("roi")
    if isinstance(roi, list) and len(roi) == 4:
        return [int(v) for v in roi]
    return None


# ---------------------------------------------------------------------------
# 「底部导航 / 返回」控件的 ROI —— 从产品枚举（不写死清单）
# ---------------------------------------------------------------------------
def _nav_rois(files: dict) -> list[tuple[str, list[int]]]:
    """返回 ``[(来源, roi), ...]``：产品里所有底部导航 / 左下返回控件的 ROI（去重）。

    两条规则（都是**正向**枚举，不认识的东西不强算）：
      * OCR 节点的 expected 含底导 / 返回标签（``^主城$`` / ``^返回$`` / 四个分区页签）；
      * ColorMatch 节点的 ROI 整个落在底导带内（页签选中态的高亮块）。
    """
    band = BOTTOM_NAV_ROI
    out: list[tuple[str, list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for fname, data in files.items():
        if not isinstance(data, dict):
            continue
        for node, spec in data.items():
            if not isinstance(spec, dict):
                continue
            rec = spec.get("recognition")
            roi = _roi(rec)
            if roi is None:
                continue
            kind = rec.get("type", "DirectHit")
            hit = False
            if kind == "OCR":
                pats = (rec.get("param") or {}).get("expected") or []
                hit = any(p in _NAV_LABEL_PATTERNS for p in pats)
            elif kind == "ColorMatch":
                # 高亮块整个在底导带里 → 是某个底导页签的选中态。
                hit = roi[1] >= band[1]
            if not hit:
                continue
            key = tuple(roi)
            if key in seen:
                continue
            seen.add(key)
            out.append((f"{fname}::{node}", roi))
    return out


def _band_top(nav: list[tuple[str, list[int]]]) -> int:
    return min(roi[1] for _src, roi in nav) if nav else BOTTOM_NAV_ROI[1]


def _list_body(band_top: int) -> list[int]:
    return [0, LIST_BODY_TOP, 720, band_top - LIST_BODY_TOP]


# ---------------------------------------------------------------------------
# 守卫 1：Swipe 的起点 / 终点都不得落在底导 / 返回 ROI 上，且都要在列表体内
# ---------------------------------------------------------------------------
def _geometry(files: dict) -> dict | None:
    """读产品的 ``SpecialScrollList`` Swipe 几何；不合形态返回 None。"""
    node = _node(files, SCROLL_NODE)
    if not isinstance(node, dict):
        return None
    action = node.get("action") or {}
    if action.get("type") != "Swipe":
        return None
    param = action.get("param") or {}
    begin = _pt(param.get("begin"))
    end = _pt(param.get("end"))
    if begin is None or end is None:
        return None
    return {
        "begin": [int(v) for v in param["begin"]],
        "end": [int(v) for v in param["end"]],
        "begin_pt": begin,
        "end_pt": end,
        "duration": param.get("duration"),
    }


def _binding_failures(files: dict) -> list[str]:
    """两个权威 ROI 必须与产品逐字段一致（否则守卫与实现脱节）。"""
    msgs: list[str] = []
    for node, want in _NAV_ANCHORS.items():
        got = _roi(_resolve(files, node))
        if got is None:
            msgs.append(f"几何绑定：pipeline 里找不到 {node} 的 OCR ROI（引用悬空？）")
        elif got != list(want):
            msgs.append(
                f"几何绑定：{node} 的 ROI {got} != hooks_36 常量 {list(want)}"
                f"（产品改了底导 ROI，请同步 hooks_36 与列表体边界）"
            )
    return msgs


def _geometry_failures(root: Path | None = None) -> list[str]:
    files = _files(root)
    msgs: list[str] = _binding_failures(files)
    nav = _nav_rois(files)
    if not nav:
        msgs.append("几何守卫：产品里找不到任何「底部导航 / 返回」ROI（枚举规则失效了？）")
    band = _band_top(nav)
    body = _list_body(band)

    node = _node(files, SCROLL_NODE)
    if node is None:
        return msgs + [f"几何守卫：pipeline 里找不到节点 {SCROLL_NODE}"]

    geo = _geometry(files)
    if geo is None:
        return msgs + [
            f"几何守卫：{SCROLL_NODE} 的 action 不是带 begin/end 的 Swipe"
            f"（现为 {(node.get('action') or {}).get('type')!r}）"
        ]

    for label, pt in (("起点", geo["begin_pt"]), ("终点", geo["end_pt"])):
        for src, roi in nav:
            if _inside(pt, roi):
                msgs.append(
                    f"几何守卫：滚动手势{label} {list(pt)} 落在底部导航 / 返回 ROI {roi}"
                    f"（{src}）内 —— 手势会作用在【导航控件】上（#18/#29/#36 同族病）；"
                    f"起终点必须落在列表体 {body} 内"
                )
        if pt[1] >= band:
            msgs.append(
                f"几何守卫：滚动手势{label} y={pt[1]} 不低于底导带上沿 y={band}"
                f"（列表面止于 {band}，{label} 已在底导带内）"
            )
        if not _inside(pt, body):
            msgs.append(
                f"几何守卫：滚动手势{label} {list(pt)} 不在列表体 {body} 内"
                f"（上沿是固定条，下沿是底导带）"
            )

    if geo["begin_pt"][1] <= geo["end_pt"][1]:
        msgs.append(
            f"几何守卫：滚动方向不是向上（起点 y={geo['begin_pt'][1]} <= 终点 "
            f"y={geo['end_pt'][1]}）—— 列表不会向下翻"
        )
    travel = geo["begin_pt"][1] - geo["end_pt"][1]
    if not (_SWIPE_MIN_TRAVEL <= travel <= _SWIPE_MAX_TRAVEL):
        msgs.append(
            f"几何守卫：滚动手势行程 {travel}px 不在 [{_SWIPE_MIN_TRAVEL},"
            f"{_SWIPE_MAX_TRAVEL}] 内（太短不翻行 / 太长成甩动会跳过目标）"
        )
    return msgs


def probe_scroll_gesture_avoids_nav_roi() -> bool:
    """#36 守卫 1：SpecialScrollList 的 Swipe 起终点都落在列表体内、不压在底导 / 返回 ROI 上。"""
    return _geometry_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：离线复现「深行目标需要多次滑动」
#
# 屏幕状态机（页面级，不臆造触摸物理）：page ∈ {主城, 列表, 详情页_目标, 详情页_别的}；
# 列表用【真机行扫】的 17 行（屏幕顺序），显示窗口 5 行；滚动把窗口下移 2 行。
# 目标 = 最末行。MAA 的 next / max_hit / [JumpBack] 语义同 hooks_19 / hooks_29 / hooks_37。
# ---------------------------------------------------------------------------
_TARGET_ROW = "维·索拉斯讨伐"      # 真机第 17 行（最末行，sweep_lord_03.ocr.txt @y=1070）
_WRONG_DETAIL = "详情页_别的"
_TARGET_DETAIL = "详情页_目标"

# 真机行扫表（屏幕自上而下；sweep_lord_00..04.ocr.txt 的滚动链拼出）。
ROWS = [
    "艾基尔·嫉妒讨伐",     # 1（sweep_lord_00 @y=640）
    "猩红巨熊讨伐",         # 2（@y=782）
    "背鳍三兄弟讨伐",       # 3（@y=928）
    "八岐大蛇讨伐",         # 4（@y=1072）
    "妖狐讨伐",             # 5（sweep_lord_01 @y=565）
    "管理者讨伐",           # 6（@y=709）
    "Sec-5200Li讨伐",       # 7（@y=856）
    "白虎讨伐",             # 8（@y=997）
    "风将獠牙骑士讨伐",     # 9（@y=1144 / sweep_lord_02 @y=485）
    "诅咒弧魔艾基尔讨伐",   # 10（sweep_lord_02 @y=628）
    "寄居蟹船长讨伐",       # 11（@y=772）
    "潮汐巨妖讨伐",         # 12（@y=914）
    "废墟魔像讨伐",         # 13（@y=1058 / sweep_lord_03 @y=494）
    "废墟守卫·火讨伐",      # 14（@y=640）
    "不死王瑞西塔尔讨伐",   # 15（@y=785）
    "雷霆树妖讨伐",         # 16（@y=926）
    "维·索拉斯讨伐",        # 17（@y=1070）
]

WINDOW = 5                 # 真机一屏可见 4~5 行（滚动后 5 行）
SCROLL_ROWS = 2            # 每次受控滚动 ≈ 2 行（见节点注释「每次约 2~3 行」）

# 旧形态几何（#36 前的产品值；prove-red 用它对照）。
_LEGACY_GEOMETRY = {
    "begin": [360, 1200, 0, 0],
    "end": [360, 800, 0, 0],
    "begin_pt": (360, 1200),
    "end_pt": (360, 800),
    "duration": 500,
}

_VISIBLE_MIN = 0.7   # 裁剪保读率（同 hooks_37）：文本框落在 ROI 内的面积占比阈值

_ZERO_ORANGE = {"角色": 0, "商店": 0, "扭蛋": 0, "菜单": 0}
_MAIN_CITY_ITEMS = [
    ("城镇", [31, 1245, 47, 27]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1246, 45, 27]),
    ("领主战", [569, 1121, 78, 29]),   # 主城右下角入口（SpecialOpenLord ROI 内）
]
_LIST_CHROME = [
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
    ("更新列表", [615, 328, 82, 28]),   # 列表页独有固定元素
    ("领主战", [135, 388, 90, 34]),     # 领主战页签（SpecialTabLord ROI 内）
    ("降临讨伐", [481, 388, 117, 33]),  # 降临讨伐页签（SpecialTabJoss ROI 内）
]
_DETAIL_CHROME = [
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
    ("推荐编成", [56, 530, 97, 30]),    # 详情页独有（SpecialDetailGate）
    ("战斗", [88, 501, 29, 16]),
]
_ROW_X, _ROW_W, _ROW_H = 201, 200, 32
_ROW_TOPS = [470, 615, 760, 905, 1050]   # 5 行窗口在列表体 [440,1180] 内的实测位形


def _box_visible_fraction(box, roi) -> float:
    x, y, w, h = box
    if w <= 0 or h <= 0 or roi is None:
        return 0.0
    ix0, iy0 = max(x, roi[0]), max(y, roi[1])
    ix1, iy1 = min(x + w, roi[0] + roi[2]), min(y + h, roi[1] + roi[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    return (iw * ih) / float(w * h)


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


def eval_recognition(rec, items, resolve=None, orange=None) -> bool:
    """在真机帧模型（OCR 条目 + 分区橙色计数）上求一条 recognition。

    OCR 的 roi 按【裁剪保读率】建模（真实 MAA：先按 roi 裁剪、再 OCR —— 同 hooks_37）。
    """
    if not isinstance(rec, dict):
        return False
    kind = rec.get("type", "DirectHit")
    if kind == "DirectHit":
        return True
    if kind == "OCR":
        param = rec.get("param") or {}
        pats = param.get("expected") or [".*"]
        roi = param.get("roi")
        for text, box in items:
            if not any(re.search(p, text or "") for p in pats):
                continue
            if roi is None or _box_visible_fraction(box, roi) >= _VISIBLE_MIN:
                return True
        return False
    if kind == "ColorMatch":
        key = _tab_key((rec.get("param") or {}).get("roi"))
        if key is None or orange is None:
            return False
        return int(orange.get(key, 0)) >= int((rec.get("param") or {}).get("count", 1))
    if kind in ("And", "Or"):
        leaves = (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []
        hits = []
        for leaf in leaves:
            leaf_rec = resolve(leaf) if (isinstance(leaf, str) and resolve is not None) else leaf
            hits.append(eval_recognition(leaf_rec, items, resolve, orange))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测，视为不命中


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


class _Screen:
    """列表屏状态机：页面 + 可见窗口的起始行号。"""

    def __init__(self, page: str = "主城", offset: int = 0):
        self.page = page
        self.offset = offset

    def _window(self):
        end = min(self.offset + WINDOW, len(ROWS))
        return list(enumerate(ROWS[self.offset:end], start=self.offset))[:WINDOW]

    def items(self):
        if self.page == "主城":
            return list(_MAIN_CITY_ITEMS)
        if self.page == "列表":
            out = list(_LIST_CHROME)
            for slot, (idx, name) in enumerate(self._window()):
                out.append((name, [_ROW_X, _ROW_TOPS[slot], _ROW_W, _ROW_H]))
            return out
        if self.page == _TARGET_DETAIL:
            # 目标自己的详情页：有难度行，但【没有】行名（带「讨伐」的那一行名）。
            return [
                *_DETAIL_CHROME,
                (f"{_TARGET_ROW[:-2]}中级", [203, 458, 252, 28]),
                (f"{_TARGET_ROW[:-2]}超级", [203, 628, 252, 28]),
            ]
        # 别人的详情页：有另一个成员的难度行，但没有目标行名。
        return [*_DETAIL_CHROME, ("潮汐巨妖中级", [203, 458, 252, 28])]

    def orange(self):
        return dict(_ZERO_ORANGE)

    def target_visible(self) -> bool:
        return any(name == _TARGET_ROW for _idx, name in self._window())


def _in_nav(point, nav: list[tuple[str, list[int]]]) -> bool:
    return any(_inside(point, roi) for _src, roi in nav)


def _apply_action(name: str, screen: _Screen, geometry: dict, nav) -> None:
    if name in ("SpecialOpenLord", "SpecialTabLord", "SpecialTabJoss"):
        screen.page = "列表"
    elif name == "SpecialScrollList":
        if _in_nav(geometry["begin_pt"], nav):
            # ★缺陷机理★ 起点压在底导控件上 → 列表不吃这一笔（画面不滚）→ 手指抬起处
            #   （终点那一行）被当成选行 → 打开【别人的】详情页。
            if screen.page == "列表":
                screen.page = _WRONG_DETAIL
        elif screen.page == "列表":
            screen.offset = min(screen.offset + SCROLL_ROWS, len(ROWS) - WINDOW)
    elif name == "SpecialEnterBoss" and screen.page == "列表" and screen.target_visible():
        screen.page = _TARGET_DETAIL


def _target_row_rec() -> dict:
    """目标行判据：模拟界面选项对 ``SpecialEnterBoss`` 的覆盖（行名 + 行 ROI，单源 scene.options）。"""
    scene_on_path()
    from scene.options import TARGET_ROW_ROI  # noqa: PLC0415

    return {"type": "OCR", "param": {"expected": [_TARGET_ROW], "roi": list(TARGET_ROW_ROI)}}


def _simulate(geometry, files: dict, nav, *, rec_overrides=None, max_steps: int = 400):
    """从 ``SpecialEntry`` 出发走一遍。返回 (到达目标详情?, 节点序列, 每步后的页面)。"""
    resolve = _resolver(files)
    screen = _Screen("主城")
    counters: dict[str, int] = {}
    seq: list[str] = []
    pages: list[str] = []
    reached = {"target": False}

    def node_spec(name: str):
        return _node(files, name) or {}

    def matches(name: str) -> bool:
        if rec_overrides and name in rec_overrides:
            rec = rec_overrides[name]
        else:
            rec = _resolve(files, name)
        return eval_recognition(rec, screen.items(), resolve, screen.orange())

    def dispatch(node_name: str, depth: int = 0):
        for ref in node_spec(node_name).get("next") or []:
            if depth > max_steps:
                return "LIMIT"
            jb = isinstance(ref, str) and ref.startswith("[JumpBack]")
            name = ref[len("[JumpBack]"):] if jb else ref
            spec = node_spec(name)
            mh = spec.get("max_hit")
            if mh is not None and counters.get(name, 0) >= mh:
                continue
            if not matches(name):
                continue
            seq.append(name)
            _apply_action(name, screen, geometry, nav)
            pages.append(screen.page)
            counters[name] = counters.get(name, 0) + 1
            if screen.page == _TARGET_DETAIL:
                reached["target"] = True
                return "TARGET"
            r = dispatch(name, depth + 1)
            if r is not None:
                return r
        return None

    dispatch("SpecialEntry")
    return reached["target"], seq, pages


def _rows_binding(files: dict) -> list[str]:
    """真机行扫表必须 = 配置里「领主战」子族的成员（表过期就报红，绝不静默）。"""
    try:
        scene_on_path()
        from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return [f"行表绑定：无法导入 scene.lord_battle（{exc!r}）"]
    names = [m.行名 for m in LORD_BATTLE.members if m.子族 == "领主战"]
    if set(names) != set(ROWS):
        missing = sorted(set(ROWS) - set(names))
        extra = sorted(set(names) - set(ROWS))
        return [
            f"行表绑定：真机行扫表与配置「领主战」成员不一致（表多 {missing} / 表少 {extra}）"
            f"—— 请按真机行扫更新 hooks_36.ROWS"
        ]
    if ROWS[-1] != _TARGET_ROW:
        return [f"行表绑定：最末行应为 {_TARGET_ROW!r}，实际 ROWS[-1]={ROWS[-1]!r}"]
    return []


def loop_traces(root: Path | None = None):
    """返回 ((新到达?, 新序列, 新页面), (旧到达?, 旧序列, 旧页面))。"""
    files = _files(root)
    nav = _nav_rois(files)
    geo = _geometry(files) or _LEGACY_GEOMETRY
    # 单目标跑手的覆盖：SpecialEnterBoss 认【目标行名】（否则它认的是 pipeline 默认的
    # 「猩红巨熊讨伐」，模拟会去点别人的行）。
    overrides = {"SpecialEnterBoss": _target_row_rec()}
    new = _simulate(geo, files, nav, rec_overrides=dict(overrides))
    old = _simulate(_LEGACY_GEOMETRY, files, nav, rec_overrides=dict(overrides))
    return new, old


def _repro_failures(root: Path | None = None) -> list[str]:
    files = _files(root)
    msgs = _rows_binding(files)
    (new_ok, new_seq, new_pages), (old_ok, old_seq, old_pages) = loop_traces(root)

    if "SpecialScrollList" not in new_seq:
        msgs.append(f"深行复现：新形态从未执行滚动（SpecialScrollList）：{new_seq[:12]}")
    if _WRONG_DETAIL in new_pages:
        msgs.append(f"深行复现：新形态竟滑到【别人的】详情页：{new_seq[:12]}")
    if not new_ok:
        msgs.append(
            f"深行复现：新形态未能到达最末行 {_TARGET_ROW} 自己的详情页"
            f"（目标行在屏幕外时必须能滚到）：{new_seq[:12]}"
        )
    if "SpecialEnterBoss" not in new_seq:
        msgs.append(f"深行复现：新形态未经 SpecialEnterBoss 选目标行：{new_seq[:10]}")

    if old_ok:
        msgs.append(f"深行复现：旧形态竟到达了目标详情（不应发生）：{old_seq[:12]}")
    if _WRONG_DETAIL not in old_pages:
        msgs.append(f"深行复现：旧形态未复现『滑到别人的详情页』：{old_seq[:12]}")
    return msgs


def probe_deep_row_scroll_repro() -> bool:
    """#36 守卫 2：旧形态滑到别人的详情页 / 新形态滚到最末行并命中目标详情。"""
    return _repro_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_36.py`）
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook36_assets_"))
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


def _break_begin_y(root: Path) -> None:
    """产物级：把 Swipe 起点退回 y=1200（又压在底部导航带上）。"""
    _sub(
        root / _PIPELINE_REL / _SD,
        '"begin": [360, 1040],',
        '"begin": [360, 1200],',
    )


def prove_red() -> bool:
    """真实绿；把起点退回 y=1200 → 两个守卫各自变红。"""
    scene_on_path()
    print("hooks_36 prove-red：把 Swipe 起点退回 y=1200，要求两个守卫各自变红")
    green = (
        probe_scroll_gesture_avoids_nav_roi() is True
        and probe_deep_row_scroll_repro() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：起终点都在列表体内 + 深行可达（绿）")
    if not green:
        return False

    root = _temp_pipeline()
    try:
        _break_begin_y(root)
        m1 = _geometry_failures(root)
        red_a = len(m1) > 0
        tail = f"  {m1[0]}" if m1 else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_a else 'FAIL'}] 起点退回 y=1200（压底导）-> "
              f"{'红' if red_a else '仍绿'}{tail}")
        m2 = _repro_failures(root)
        red_b = len(m2) > 0
        tail = f"  {m2[0]}" if m2 else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_b else 'FAIL'}] 起点退回 y=1200 -> 深行不再可达 -> "
              f"{'红' if red_b else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "scroll-gesture-avoids-nav-roi",
        "#36",
        "SpecialScrollList 的 Swipe 起终点都落在列表体内、不压在底部导航 / 左下返回 ROI 上"
        "（ROI 从产品枚举 + 与常量逐字段绑定）",
        probe_scroll_gesture_avoids_nav_roi,
    ),
    (
        "deep-row-scroll-repro",
        "#36",
        "离线复现：旧形态滑到别人的详情页 / 新形态滚到最末行并到达目标自己的详情页",
        probe_deep_row_scroll_repro,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
