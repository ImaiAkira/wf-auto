# -*- coding: utf-8 -*-
"""编队页 / 房间页「自动」按钮 —— **场景无关**的定位 · 读状态 · 切换（#56 二批）。

运维裁决②（原文）：「把自动的切换从战斗内做到战斗外……战斗内不再做自动的切换了……
在进战斗之前的那个编队的界面上有自动的按钮，在那里把自动关掉。」并且：
「**不得假定固定坐标**：必须**定位**到那个自动按钮（模板/图片识别优先，OCR 辅助），
读它开/关的状态，再按其识别框中心点击。**这条要覆盖所有模式的编队页，不能只做五重。**」

本模块 = 这条规则的**唯一机制**（数据在 :mod:`scene.auto_switch`）：

* :func:`locate_switch`  —— 定位标签框：**模板优先**（``common.json::AutoSwitchLabel``），
  **OCR 整串锚定兜底**（``^自动$``，排除「自动续战」）。**绝不写死坐标。**
* :func:`is_team_auto_control` —— ★三批根因修复★：把「自动」门控**限定在编队页/房间页**
  （页面文本锚点 ∨ 开关探针内的 ``开``/``关`` 状态字）；**战斗 HUD 的「自动」永不命中**
  （真机根因 + 证据帧见 :mod:`scene.auto_switch` 第 ②b 段）。
* :func:`read_switch_state` —— 由定位到的标签框推出探针、读橙色占比 → 开/关。
* :func:`click_point` —— 点击点 = 识别框中心。
* :class:`AutoSwitchStateRecognition`（``auto_switch_state``）—— 定位 + 读状态（可按期望态命中）。
* :class:`AutoSwitchSetAction`（``auto_switch``）—— 读后动：状态不对才点，点后复查；
  ★跨模式硬规则★：非五重场景一律夹回「开」（算子：其他所有战斗都要开自动）。
* :class:`AutoContDialogRecognition`（``auto_cont_dialog``）—— 「自动续战功能」确认框（ruling ③）：
  认到标题 + 「取消」即命中（box = 取消框），由 pipeline 的 Click 动作点掉，**绝不打开功能**。

★安全★：只点**自己定位到的帧内框中心**；定位不到就不动（绝不猜坐标）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from maa_util import ocr_all, read_action_param, read_param

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 冻结快照（安装态没有 scene/ 时回退；与 scene.auto_switch 一致）
# ---------------------------------------------------------------------------
_AUTO_LABEL_SNAPSHOT = "自动"
_AUTO_LABEL_PATTERNS_SNAPSHOT = (r"^自动$",)
_AUTO_LABEL_TEMPLATES_SNAPSHOT = ("auto/switch_label.png",)
_AUTO_TEMPLATE_THRESHOLD_SNAPSHOT = 0.75
_AUTO_TEMPLATE_NODE_SNAPSHOT = "AutoSwitchLabel"
_CONT_LABEL_SNAPSHOT = "自动续战"
_AUTO_ON_RATIO_SNAPSHOT = 0.15
_PROBE_OFFSETS_SNAPSHOT = {
    "自动": (-15, 41, 17, 70),
    "自动续战": (3, 40, -18, 71),
}
_CONT_DIALOG_TITLE_SNAPSHOT = "自动续战功能"
_CONT_DIALOG_PATTERNS_SNAPSHOT = (r"自动续战功能",)
_CONT_DIALOG_CANCEL_SNAPSHOT = (r"^取消$",)
#: 页面范围（★三批根因修复★）：编队页/房间页的文本锚点 + 开关状态字（与 scene.auto_switch 一致）。
#: ★#109★ 「挑战」按钮真机有两种渲染（`挑战` / `挑战→`，识别调研统计 8/17 帧带箭头）——
#:   锚点必须容忍**一个**可选箭头；与 `scene.auto_switch.TEAM_PAGE_ANCHORS` 逐项一致
#:   （安装态没有 scene/，走的就是这份快照，不同步 = 装好的产品仍只认「挑战」）。
_TEAM_PAGE_ANCHORS_SNAPSHOT = (
    r"^挑战(→)?$",
    r"^编成$",
    r"^SET编辑$",
    r"^招募$",
    r"^复制$",
    r"^战力$",
    r"Party",
)
_SWITCH_STATE_PATTERNS_SNAPSHOT = (r"^开$", r"^关$")
# ★#71 战斗页作用域★：与 scene.auto_switch 的 ②c 段一致（策略层不在场时回退用）。
#: 战斗 HUD 锚点 —— 与 agent/battle_loop_core.py 的 BATTLE_HUD_TIME_RE/BATTLE_HUD_SCORE_RE 逐字同源。
_BATTLE_HUD_ANCHORS_SNAPSHOT = (r"时间\s*\d{1,3}:\d{2}", r"分数\s*\d")
_BATTLE_AUTO_LABEL_SNAPSHOT = "自动"
_BATTLE_AUTO_LABEL_ROI_SNAPSHOT = (0, 150, 170, 240)
_BATTLE_AUTO_PROBE_OFFSETS_SNAPSHOT = {"自动": (-7, -33, 30, 16)}
_BATTLE_AUTO_ON_RATIO_SNAPSHOT = 0.15
_BATTLE_AUTO_FILL_DR_SNAPSHOT = 40
_BATTLE_AUTO_TEMPLATES_SNAPSHOT: tuple[str, ...] = ()


def _page_is_team(anchors, items) -> bool:
    for t, _b in items or ():
        s = (t or "").strip()
        for p in anchors:
            if re.search(p, s):
                return True
    return False


def _battle_hud_is_present(anchors, items) -> bool:
    for t, _b in items or ():
        s = (t or "").strip()
        for p in anchors:
            if re.search(p, s):
                return True
    return False


def _is_battle_auto_control(roi, items, label, box) -> bool:
    if not _battle_hud_is_present(_BATTLE_HUD_ANCHORS_SNAPSHOT, items):
        return False
    if not box or len(box) != 4:
        return False
    cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
    x0, y0, x1, y1 = roi
    return x0 <= cx <= x1 and y0 <= cy <= y1


def _has_switch_state_text(patterns, probe, items) -> bool:
    for t, b in items or ():
        if not b or len(b) != 4:
            continue
        if not any(re.search(p, (t or "").strip()) for p in patterns):
            continue
        cx, cy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
        if probe[0] <= cx <= probe[2] and probe[1] <= cy <= probe[3]:
            return True
    return False


class _Snapshot:
    AUTO_LABEL = _AUTO_LABEL_SNAPSHOT
    AUTO_LABEL_PATTERNS = _AUTO_LABEL_PATTERNS_SNAPSHOT
    AUTO_LABEL_TEMPLATES = _AUTO_LABEL_TEMPLATES_SNAPSHOT
    AUTO_TEMPLATE_THRESHOLD = _AUTO_TEMPLATE_THRESHOLD_SNAPSHOT
    AUTO_TEMPLATE_NODE = _AUTO_TEMPLATE_NODE_SNAPSHOT
    CONT_LABEL = _CONT_LABEL_SNAPSHOT
    AUTO_ON_RATIO = _AUTO_ON_RATIO_SNAPSHOT
    PROBE_OFFSETS = _PROBE_OFFSETS_SNAPSHOT
    CONT_DIALOG_TITLE = _CONT_DIALOG_TITLE_SNAPSHOT
    CONT_DIALOG_PATTERNS = _CONT_DIALOG_PATTERNS_SNAPSHOT
    CONT_DIALOG_CANCEL_PATTERNS = _CONT_DIALOG_CANCEL_SNAPSHOT
    TEAM_PAGE_ANCHORS = _TEAM_PAGE_ANCHORS_SNAPSHOT
    SWITCH_STATE_PATTERNS = _SWITCH_STATE_PATTERNS_SNAPSHOT
    BATTLE_HUD_ANCHORS = _BATTLE_HUD_ANCHORS_SNAPSHOT
    BATTLE_AUTO_LABEL = _BATTLE_AUTO_LABEL_SNAPSHOT
    BATTLE_AUTO_LABEL_ROI = _BATTLE_AUTO_LABEL_ROI_SNAPSHOT
    BATTLE_AUTO_PROBE_OFFSETS = _BATTLE_AUTO_PROBE_OFFSETS_SNAPSHOT
    BATTLE_AUTO_ON_RATIO = _BATTLE_AUTO_ON_RATIO_SNAPSHOT
    BATTLE_AUTO_FILL_DR = _BATTLE_AUTO_FILL_DR_SNAPSHOT
    BATTLE_AUTO_TEMPLATES = _BATTLE_AUTO_TEMPLATES_SNAPSHOT

    @staticmethod
    def label_patterns(label):
        return (rf"^{re.escape(label)}$",)

    @staticmethod
    def probe_for(label, box):
        x, y, w, h = (int(v) for v in box)
        dx0, dy0, dx1, dy1 = _PROBE_OFFSETS_SNAPSHOT.get(label, _PROBE_OFFSETS_SNAPSHOT["自动"])
        return (x + dx0, y + dy0, x + w + dx1, y + dy1)

    @staticmethod
    def battle_probe_for(label, box):
        x, y, w, h = (int(v) for v in box)
        dx0, dy0, dx1, dy1 = _BATTLE_AUTO_PROBE_OFFSETS_SNAPSHOT.get(
            label, _BATTLE_AUTO_PROBE_OFFSETS_SNAPSHOT["自动"])
        return (x + dx0, y + dy0, x + w + dx1, y + dy1)

    @staticmethod
    def click_point_of(box):
        x, y, w, h = (int(v) for v in box)
        return (x + w // 2, y + h // 2)

    @staticmethod
    def page_is_team(items):
        return _page_is_team(_TEAM_PAGE_ANCHORS_SNAPSHOT, items)

    @staticmethod
    def has_switch_state_text(items, label, box):
        return _has_switch_state_text(
            _SWITCH_STATE_PATTERNS_SNAPSHOT, _Snapshot.probe_for(label, box), items)

    @staticmethod
    def is_team_auto_control(items, label, box):
        return _Snapshot.page_is_team(items) or _Snapshot.has_switch_state_text(items, label, box)

    @staticmethod
    def battle_hud_is_present(items):
        return _battle_hud_is_present(_BATTLE_HUD_ANCHORS_SNAPSHOT, items)

    @staticmethod
    def is_battle_auto_control(items, label, box):
        return _is_battle_auto_control(_BATTLE_AUTO_LABEL_ROI_SNAPSHOT, items, label, box)


def _load_config():
    try:
        if not (_REPO_ROOT / "scene" / "auto_switch.py").is_file():
            raise ModuleNotFoundError("真源不在场：scene/auto_switch.py")
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scene import auto_switch as a  # noqa: PLC0415

        return a, "scene"
    except ModuleNotFoundError:
        return _Snapshot(), "snapshot"


CFG, CFG_SOURCE = _load_config()

AUTO_LABEL = CFG.AUTO_LABEL
AUTO_LABEL_TEMPLATES = tuple(CFG.AUTO_LABEL_TEMPLATES)
AUTO_TEMPLATE_THRESHOLD = float(CFG.AUTO_TEMPLATE_THRESHOLD)
AUTO_TEMPLATE_NODE = CFG.AUTO_TEMPLATE_NODE
CONT_LABEL = CFG.CONT_LABEL
AUTO_ON_RATIO = float(CFG.AUTO_ON_RATIO)
CONT_DIALOG_PATTERNS = tuple(CFG.CONT_DIALOG_PATTERNS)
CONT_DIALOG_CANCEL_PATTERNS = tuple(CFG.CONT_DIALOG_CANCEL_PATTERNS)

# ★#71 战斗页作用域★（策略层数据在 scene.auto_switch 的 ②c 段；不落地则回退快照）。
BATTLE_AUTO_LABEL = getattr(CFG, "BATTLE_AUTO_LABEL", _BATTLE_AUTO_LABEL_SNAPSHOT)
BATTLE_HUD_ANCHORS = tuple(getattr(CFG, "BATTLE_HUD_ANCHORS", _BATTLE_HUD_ANCHORS_SNAPSHOT))
BATTLE_AUTO_LABEL_ROI = tuple(getattr(CFG, "BATTLE_AUTO_LABEL_ROI", _BATTLE_AUTO_LABEL_ROI_SNAPSHOT))
BATTLE_AUTO_ON_RATIO = float(getattr(CFG, "BATTLE_AUTO_ON_RATIO", _BATTLE_AUTO_ON_RATIO_SNAPSHOT))
BATTLE_AUTO_FILL_DR = float(getattr(CFG, "BATTLE_AUTO_FILL_DR", _BATTLE_AUTO_FILL_DR_SNAPSHOT))
BATTLE_AUTO_TEMPLATES = tuple(
    getattr(CFG, "BATTLE_AUTO_TEMPLATES", _BATTLE_AUTO_TEMPLATES_SNAPSHOT))

#: 跨模式硬规则（唯一真源在 scene.wuchong）：只有五重允许关自动。取不到时保守「只许五重关」。
try:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scene.wuchong import effective_auto_state as _effective_auto_state  # noqa: PLC0415

    _MANUAL_ALLOWED = None  # 用 scene.wuchong 的真源
except Exception:  # noqa: BLE001
    _effective_auto_state = None
    _MANUAL_ALLOWED = ("wuchong",)


def label_patterns(label: str) -> tuple[str, ...]:
    fn = getattr(CFG, "label_patterns", None)
    if callable(fn):
        return tuple(fn(label))
    return (rf"^{re.escape(label)}$",)


def probe_for(label: str, box):
    fn = getattr(CFG, "probe_for", None)
    if callable(fn):
        return fn(label, box)
    x, y, w, h = (int(v) for v in box)
    dx0, dy0, dx1, dy1 = CFG.PROBE_OFFSETS.get(label, CFG.PROBE_OFFSETS[AUTO_LABEL])
    return (x + dx0, y + dy0, x + w + dx1, y + dy1)


def click_point(box):
    fn = getattr(CFG, "click_point_of", None)
    if callable(fn):
        return fn(box)
    x, y, w, h = (int(v) for v in box)
    return (x + w // 2, y + h // 2)


# ---------------------------------------------------------------------------
# 页面范围（★三批根因修复★）：只在【编队页 / 房间页】认「自动」
# ---------------------------------------------------------------------------
def page_is_team(items) -> bool:
    """画面是否是**编队页 / 房间页**（文本锚点，位置无关）。"""
    fn = getattr(CFG, "page_is_team", None)
    if callable(fn):
        return bool(fn(items))
    anchors = getattr(CFG, "TEAM_PAGE_ANCHORS", _TEAM_PAGE_ANCHORS_SNAPSHOT)
    return _page_is_team(anchors, items)


def has_switch_state_text(items, label: str, box) -> bool:
    """标签框正下方探针区内是否有 开/关 状态字（证明它是开关而非普通标签）。"""
    fn = getattr(CFG, "has_switch_state_text", None)
    if callable(fn):
        return bool(fn(items, label, box))
    patterns = getattr(CFG, "SWITCH_STATE_PATTERNS", _SWITCH_STATE_PATTERNS_SNAPSHOT)
    return _has_switch_state_text(patterns, probe_for(label, box), items)


def is_team_auto_control(items, label: str, box) -> bool:
    """定位到的「自动」是否是**编队页 / 房间页的自动开关**（页面锚点 ∨ 开关状态字）。

    ★这是把「自动」门控限定在编队页/房间页的唯一判据★：战斗 HUD 的「自动」两条都不满足
    （真机根因 + 证据帧见 ``scene/auto_switch.py`` 第 ②b 段）。
    """
    fn = getattr(CFG, "is_team_auto_control", None)
    if callable(fn):
        return bool(fn(items, label, box))
    return page_is_team(items) or has_switch_state_text(items, label, box)


# ---------------------------------------------------------------------------
# 战斗页作用域（★#71★）：只在【战斗页】认战斗 HUD 的「自动」—— 与编队页作用域互斥
# ---------------------------------------------------------------------------
def battle_hud_is_present(items) -> bool:
    """画面是否是**战斗页**（战斗 HUD 锚点：``时间 HH:MM`` / ``分数 N``；文本判据，位置无关）。"""
    fn = getattr(CFG, "battle_hud_is_present", None)
    if callable(fn):
        return bool(fn(items))
    anchors = getattr(CFG, "BATTLE_HUD_ANCHORS", _BATTLE_HUD_ANCHORS_SNAPSHOT)
    return _battle_hud_is_present(anchors, items)


def battle_probe_for(label: str, box):
    """由**定位到的战斗标签框**推出状态探针 ``(x0,y0,x1,y1)``（相对框，绝不写死坐标）。"""
    fn = getattr(CFG, "battle_probe_for", None)
    if callable(fn):
        return fn(label, box)
    x, y, w, h = (int(v) for v in box)
    offsets = getattr(CFG, "BATTLE_AUTO_PROBE_OFFSETS", _BATTLE_AUTO_PROBE_OFFSETS_SNAPSHOT)
    dx0, dy0, dx1, dy1 = offsets.get(label, offsets[BATTLE_AUTO_LABEL])
    return (x + dx0, y + dy0, x + w + dx1, y + dy1)


def is_battle_auto_control(items, label: str, box) -> bool:
    """定位到的「自动」是否是**战斗页 HUD 的自动控件**（战斗页锚点 ∧ 框中心在战斗 ROI 内）。

    ★与 :func:`is_team_auto_control` 互斥★：编队页帧无战斗 HUD 锚点 → 判否；战斗 HUD 的
    「技能自动」/编队页底栏「自动」因框中心不在 ROI 内 → 也判否（口径见 ``scene.auto_switch`` ②c）。
    """
    fn = getattr(CFG, "is_battle_auto_control", None)
    if callable(fn):
        return bool(fn(items, label, box))
    roi = getattr(CFG, "BATTLE_AUTO_LABEL_ROI", _BATTLE_AUTO_LABEL_ROI_SNAPSHOT)
    return _is_battle_auto_control(roi, items, label, box)


# ---------------------------------------------------------------------------
# 定位 / 读状态（纯函数，便于离线守卫）
# ---------------------------------------------------------------------------
def _clean_box(box):
    if box is None:
        return None
    b = [int(v) for v in box]
    return b if len(b) == 4 else None


def _center_of(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _overlap(a, b) -> bool:
    """两个 720 空间框是否有交集。"""
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def _same_spot(a, b) -> bool:
    """两个框是否指同一处（中心距 ≤ 较大边长的一半 + 4px 容差）。"""
    (ax, ay), (bx, by) = _center_of(a), _center_of(b)
    tol = max(a[2], a[3], b[2], b[3]) / 2.0 + 4.0
    return abs(ax - bx) <= tol and abs(ay - by) <= tol


def locate_switch_label(items, label: str = AUTO_LABEL, template_box=None):
    """定位某个开关的**标签框** ``[x,y,w,h]``；定位不到返回 None。

    次序（运维裁决②：「模板/图片识别优先，OCR 辅助」——**但模板必须经 OCR 校验**）：

    1. **模板命中**（``common.json::AutoSwitchLabel``）——仅在：(a) 没被**别的开关标签**
       （OCR 里整串/子串含「续战」而当前 label 是「自动」等）覆盖，且 (b) 与 OCR 锚定结果不矛盾
       时采用；
    2. **OCR 整串锚定**（``^自动$``）——最可靠（真机 5+ 帧都读对），矛盾时以它为准；
    3. 都没有 → None（绝不猜坐标）。

    ★为什么模板不能盲信（真机实测）★：MAA 原生 TemplateMatch 在**领主战成员编队页**上把
    「自动」裁片命中了「**自动续战**」的位置（`box=[17,1062,43,26]`）——刻痕与 2 字前缀都吻合。
    因此模板命中必须满足「不与其它开关标签重叠、且不与 OCR 锚定矛盾」，否则退回 OCR。
    """
    ocr_box = None
    regs = [re.compile(p) for p in label_patterns(label)]
    for t, b in items or ():
        if not b or len(b) != 4:
            continue
        text = (t or "").strip()
        if any(r.fullmatch(text) for r in regs):
            ocr_box = [int(v) for v in b]
            break

    tpl = _clean_box(template_box)
    if tpl is not None:
        # (a) 模板命中处若被**别的**开关标签（含「续战」）覆盖 → 判为误命中，丢弃。
        for t, b in items or ():
            if not b or len(b) != 4:
                continue
            text = (t or "").strip()
            if text == label or not text:
                continue
            if ("续战" in text or "自动" in text) and _overlap(tpl, [int(v) for v in b]):
                tpl = None
                break
        # (b) 与 OCR 锚定矛盾（不在一处）→ 以 OCR 为准，丢弃模板。
        if tpl is not None and ocr_box is not None and not _same_spot(ocr_box, tpl):
            tpl = None

    if tpl is not None:
        return tpl
    return ocr_box


def to_rgb_array(image):
    """把 MAA screencap 转成 **RGB ndarray**；需要 numpy（随包内置），**不强求 PIL**。

    ★为什么不能依赖 PIL（真机 P0：五重「选只手操但仍自动」）★
      随包内置的便携 Python（``interface.json`` 的 ``child_exec`` = ``install/python/python.exe``）
      **只装了 maafw + numpy + StrEnum，没有 Pillow**（install.py 也不装它）。旧实现
      ``from PIL import Image`` 在**安装态**必抛 ``ModuleNotFoundError`` → 被 ``except`` 吞掉
      → ``_orange_ratio`` 恒返回 None → ``read_switch_state`` 判不出 → ``auto_switch_state``
      报 ``state_unknown`` → 编队页/房间页的「自动」开关**永远读不出、也永远关不掉**。
      真机 ``install/debug/maafw.log``（2026-10-16 01:16:17）实证：
      ``WuchongTeamAutoSet`` detail = ``{"box":[630,102,43,27],"found":true,"on":null,
      "reason":"state_unknown","source":"template"}``（模板命中了，却读不出开/关）。
      这里只用 numpy 的 **BGR 原生规约**（MAA screencap = BGR，真机实证）；PIL 仅在
      **确有 PIL** 时用于把 ``PIL.Image`` 转 ndarray（离线测试/真机 runner 会传 PIL）。
    """
    try:
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    # PIL（若在场）能吃掉 PIL.Image 与任意模式；不在场也绝不报错。
    try:
        from PIL import Image  # noqa: PLC0415

        if isinstance(image, Image.Image):
            return np.asarray(image.convert("RGB"))
    except Exception:  # noqa: BLE001
        pass
    arr = np.asarray(image)
    if arr.ndim == 2:
        return np.stack([arr, arr, arr], axis=-1)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        return np.ascontiguousarray(arr[:, :, 2::-1])  # BGR -> RGB（MAA 原生规约）
    return None


def _orange_ratio(image, probe) -> float | None:
    """probe=(x0,y0,x1,y1) 内橙色像素占比；需要 numpy（随包内置），**不需要 PIL**（不猜）。

    ★通道序★：MAA 原生 screencap 是 **BGR**（真机实证），PIL 入参按 RGB —— 见 :func:`to_rgb_array`。
    """
    try:
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    arr = to_rgb_array(image)
    if arr is None:
        return None
    h, w = int(arr.shape[0]), int(arr.shape[1])
    x0, y0, x1, y1 = (int(v) for v in probe)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = arr[y0:y1, x0:x1].astype(np.int16)
    if crop.size == 0:
        return None
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    orange = (r > 150) & (r - b > 80) & (r - g > 20) & (g < 210)
    return float(orange.mean())


def read_switch_state(image, label: str, box) -> bool | None:
    """由标签框推出探针、读开关「开/关」；判不出返回 None。"""
    ratio = _orange_ratio(image, probe_for(label, box))
    if ratio is None:
        return None
    return ratio > AUTO_ON_RATIO


def _cyan_ratio(image, probe) -> float | None:
    """probe=(x0,y0,x1,y1) 内**青绿色**像素占比；需要 numpy，**不需要 PIL**（不猜）。

    ★通道序★：MAA 原生 screencap 是 **BGR**（真机实证），PIL 入参按 RGB —— **必须经
    :func:`to_rgb_array` 归一**（否则会拿 B 当 R，青绿判据失效；同 :func:`_orange_ratio` 的坑）。
    判据：``g - r > BATTLE_AUTO_FILL_DR ∧ b - r > BATTLE_AUTO_FILL_DR``（战斗 HUD「自动」按钮的
    青色填充；ON 帧实测均值 ≈ (93,191,183)、占比 ≈ 0.73）。
    """
    try:
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    arr = to_rgb_array(image)
    if arr is None:
        return None
    h, w = int(arr.shape[0]), int(arr.shape[1])
    x0, y0, x1, y1 = (int(v) for v in probe)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = arr[y0:y1, x0:x1].astype(np.int16)
    if crop.size == 0:
        return None
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    dr = BATTLE_AUTO_FILL_DR
    cyan = (g - r > dr) & (b - r > dr)
    return float(cyan.mean())


def read_battle_auto_state(image, label: str = BATTLE_AUTO_LABEL, box=None) -> bool | None:
    """由**战斗页标签框**推出探针、读战斗 HUD「自动」开/关（青绿填充占比）；判不出返回 None。

    ★绝不把「判不出」当成关★：读不出（无 numpy / 探针越界）一律返回 ``None``，由调用方决定「不动作」。
    """
    ratio = _cyan_ratio(image, battle_probe_for(label, box))
    if ratio is None:
        return None
    return ratio > BATTLE_AUTO_ON_RATIO


def template_box(context, image, label: str = AUTO_LABEL):
    """借 ``common.json::AutoSwitchLabel`` 的模板匹配定位（仅「自动」有裁片）。失败返回 None。"""
    if label != AUTO_LABEL or not AUTO_LABEL_TEMPLATES:
        return None
    try:
        detail = context.run_recognition(AUTO_TEMPLATE_NODE, image)
    except Exception:  # noqa: BLE001
        return None
    if detail is None or not getattr(detail, "hit", False):
        return None
    best = getattr(detail, "best_result", None)
    box = getattr(best, "box", None) if best is not None else None
    if box is not None:
        box = [int(v) for v in box]
        if len(box) == 4:
            return box
    # 兜底：从 all_results 取第一个。
    for r in getattr(detail, "all_results", None) or []:
        b = getattr(r, "box", None)
        if b is not None and len(b) == 4:
            return [int(v) for v in b]
    return None


def locate_switch(context, image, label: str = AUTO_LABEL, ocr_entry: str = "OcrTask"):
    """端到端定位：模板优先 → OCR 整串兜底（★限编队页/房间页★）。返回 ``(box, source)``。

    ``box`` 为 None 的两种情形：No.1 根本没定位到；No.2 定位到了但不是编队页/房间页的开关
    （:func:`is_team_auto_control` 判否，例如**战斗 HUD 的「自动」**）—— 两者都返回 (None, source)。
    """
    items = ocr_all(context, image, ocr_entry)
    tbox = template_box(context, image, label)
    box = locate_switch_label(items, label, tbox)
    source = "template" if tbox is not None else ("ocr" if box else None)
    if box is not None and not is_team_auto_control(items, label, box):
        return None, source
    return box, source


def locate_battle_auto(context, image, label: str = BATTLE_AUTO_LABEL, ocr_entry: str = "OcrTask"):
    """端到端定位**战斗页**的「自动」：**只走 OCR**（:data:`BATTLE_AUTO_TEMPLATES` 为空 → 无模板）。

    候选必须过：(a) OCR **整串** ``^自动$``；(b) 画面有战斗 HUD 锚点（:func:`battle_hud_is_present`）；
    (c) 框中心落在 :data:`BATTLE_AUTO_LABEL_ROI`（用 :func:`is_battle_auto_control` 一并判定）。
    定位不到 / 不是战斗 HUD 的「自动」→ 返回 ``(None, None)``（绝不猜坐标）。
    """
    items = ocr_all(context, image, ocr_entry)
    regs = [re.compile(p) for p in label_patterns(label)]
    for t, b in items or ():
        if not b or len(b) != 4:
            continue
        if not any(r.fullmatch((t or "").strip()) for r in regs):
            continue
        if not is_battle_auto_control(items, label, b):
            continue
        return [int(v) for v in b], "ocr"
    return None, None


def _click_box(context, click_action, cx, cy) -> bool:
    try:
        context.run_action(click_action, box=(int(cx) - 1, int(cy) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[auto_switch] 点击失败 ({cx},{cy})：{exc}")
        return False


def effective_auto_state(scene: str, want_on: bool) -> bool:
    """夹到合法值：非五重场景一律 True（其他所有战斗都要开自动）。与 scene.wuchong 同口径。"""
    if _effective_auto_state is not None:
        return bool(_effective_auto_state(scene, want_on))
    return bool(want_on) if scene in (_MANUAL_ALLOWED or ()) else True


def dismiss_cont_dialog(context, image, click_action="PubClick", ocr_entry="OcrTask") -> bool:
    """若「自动续战功能」确认框在屏，点它的「取消」（ruling ③：该出现就按取消处理）。"""
    items = ocr_all(context, image, ocr_entry)
    texts = [t for t, _ in items]
    title = any(re.search(p, t or "") for t in texts for p in CONT_DIALOG_PATTERNS)
    if not title:
        return False
    for t, b in items:
        if not b or len(b) != 4:
            continue
        if any(re.search(p, t or "") for p in CONT_DIALOG_CANCEL_PATTERNS):
            cx, cy = b[0] + b[2] // 2, b[1] + b[3] // 2
            print(f"[auto_switch] 检测到「自动续战功能」确认框 -> 点『取消』@{cx},{cy}（绝不打开）")
            _click_box(context, click_action, cx, cy)
            return True
    print("[auto_switch] 检测到『自动续战功能』框但读不到『取消』-> 只等待，绝不盲点")
    return False


# ---------------------------------------------------------------------------
# 自定义识别：auto_switch_state
# ---------------------------------------------------------------------------
class AutoSwitchStateRecognition(CustomRecognition):
    """定位某个开关并读状态；按 ``state`` 决定是否命中。

    参数（custom_recognition_param）：
        label      : 开关标签，默认「自动」（可传「自动续战」）。
        state      : 命中条件 —— ``off``（当前是关）/``on``（当前是开）/``any``（默认）。
        scope      : 作用域 —— ``team``（默认，编队页/房间页）/``battle``（#71 战斗页 HUD）。
        ocr_entry  : 截图用 OCR 节点，默认 OcrTask。

    命中时 ``box`` = **定位到的标签框**（下游若用 Click 即点其中心）。

    ★三批：``scope="team"``（默认）只在【编队页 / 房间页】认「自动」（:func:`is_team_auto_control`）★
    —— 战斗 HUD 的「自动」在别的页面/位置，两条判据都不满足 → **永不命中**
    （真机根因见 scene/auto_switch ②b 段）。
    ★#71★：``scope="battle"`` 改用**战斗页作用域**（:func:`locate_battle_auto` +
    :func:`is_battle_auto_control` + :func:`read_battle_auto_state`），绝**不**接受编队页的「自动」。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        label = str(param.get("label") or AUTO_LABEL)
        want = str(param.get("state") or "any").strip().lower()
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        scope = str(param.get("scope") or "team").strip().lower()
        image = argv.image
        if image is None:
            image = context.tasker.controller.post_screencap().wait().get()

        # ★#71 战斗页作用域★：只走战斗页判据（战斗 HUD 锚点 + 战斗 ROI），绝不吃编队页的「自动」。
        if scope == "battle":
            box, source = locate_battle_auto(context, image, label, ocr_entry)
            items = ocr_all(context, image, ocr_entry)
            detail = {"label": label, "state": want, "scope": "battle", "box": box,
                      "hud": battle_hud_is_present(items), "source": source}
            if box is None:
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={**detail, "found": False, "reason": "not_located"})
            on = read_battle_auto_state(image, label, box)
            detail["on"] = on
            if on is None:
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={**detail, "found": True, "reason": "state_unknown"})
            hit = want == "any" or (want == "on") == bool(on)
            if not hit:
                return CustomRecognition.AnalyzeResult(box=None, detail={**detail, "found": True})
            return CustomRecognition.AnalyzeResult(box=box, detail={**detail, "found": True})

        items = ocr_all(context, image, ocr_entry)
        tbox = template_box(context, image, label)
        box = locate_switch_label(items, label, tbox)
        detail = {"label": label, "state": want, "box": box, "team_page": page_is_team(items),
                  "source": "template" if tbox is not None else ("ocr" if box else None)}
        if box is None:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={**detail, "found": False, "reason": "not_located"})
        # ★三批★：战斗 HUD 的「自动」不是编队页/房间页的开关 → 不认（否则动作会在转场帧上静默失败）。
        if not is_team_auto_control(items, label, box):
            return CustomRecognition.AnalyzeResult(
                box=None, detail={**detail, "found": False, "reason": "not_team_control"})
        on = read_switch_state(image, label, box)
        detail["on"] = on
        if on is None:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={**detail, "found": True, "reason": "state_unknown"})
        hit = want == "any" or (want == "on") == bool(on)
        if not hit:
            return CustomRecognition.AnalyzeResult(box=None, detail={**detail, "found": True})
        return CustomRecognition.AnalyzeResult(box=box, detail={**detail, "found": True})


# ---------------------------------------------------------------------------
# 自定义动作：auto_switch
# ---------------------------------------------------------------------------
class AutoSwitchSetAction(CustomAction):
    """把某开关设成期望状态：**先定位**（模板/OCR）→ 读状态 → 需要才点识别框中心 → 复查。

    参数（custom_action_param）：
        on          : 期望状态（True=开）。★非五重场景一律夹回 True★（跨模式硬规则）。
        scene       : 场景 id（默认 wuchong）；只有 wuchong 允许 on=False。
        label       : 开关标签，默认「自动」。
        scope       : 作用域 —— ``team``（默认，编队页/房间页）/``battle``（#71 战斗页 HUD）。
        click_action: 用于原生点击的节点名，默认 PubClick。
        ocr_entry   : 截图用 OCR 节点，默认 OcrTask。

    定位不到 / 状态读不出 → **不动**（绝不猜坐标、绝不盲点）。

    ★#71 战斗页作用域（``scope="battle"``）的安全纪律★（战斗里只关自动，绝不乱点）：
        1. 只在**正证据**下动作：定位到 ∧ 战斗页作用域（:func:`is_battle_auto_control`）∧
           读数**明确为「开」**（:func:`read_battle_auto_state` 为 True）才点一次；
        2. 读数为 ``None`` / 定位不到 → **不动作** + 打印可见失败 ``[auto_switch][FAIL] ...``；
        3. 点后用**新截图**复查；仍为「开」→ 打印 FAIL（**绝不点第二次**）；
        4. **绝不把「判不出」当成「关」**（``None`` 既不算成功、也不触发动作）。
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        label = str(param.get("label") or AUTO_LABEL)
        scene = str(param.get("scene") or "wuchong")
        click_action = str(param.get("click_action") or "PubClick")
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        scope = str(param.get("scope") or "team").strip().lower()
        want_raw = bool(param.get("on", True))
        want = effective_auto_state(scene, want_raw)
        if want != want_raw:
            print(f"[auto_switch] 场景 {scene!r} 不允许关自动（其他战斗一律自动）→ 强制 on=True")

        image = context.tasker.controller.post_screencap().wait().get()
        # ruling ③：先处理「自动续战功能」确认框（出现就按取消），绝不打开功能。
        dismiss_cont_dialog(context, image, click_action=click_action, ocr_entry=ocr_entry)

        # ★#71★：战斗页作用域走独立路径（战斗 HUD 定位 + 青绿读数 + 只在「明确为开」时关一次）。
        if scope == "battle":
            return self._set_battle(context, image, label, scene, want, click_action, ocr_entry)

        items = ocr_all(context, image, ocr_entry)
        tbox = template_box(context, image, label)
        box = locate_switch_label(items, label, tbox)
        source = "template" if tbox is not None else ("ocr" if box else None)
        if box is None:
            # ★三批：可见失败★（旧形态是 `定位不到 … → 不动` 静默返回 True）。
            print(f"[auto_switch][FAIL] 定位不到『{label}』开关（模板/OCR 均未命中）→ 不执行；"
                  f"编队页锚点={page_is_team(items)} 屏上 OCR={[(t, b) for t, b in items][:40]}")
            return False
        # ★三批根因修复★：必须是【编队页/房间页】的自动开关 —— 战斗 HUD 的「自动」在这里被挡下，
        #   绝不点它（真机证据帧见 tools/frames/auto_battle_hud_*.png）。
        if not is_team_auto_control(items, label, box):
            print(f"[auto_switch][FAIL] 定位到的『{label}』不是编队页/房间页的开关"
                  f"（无编队锚点且标签下方探针无 开/关；疑为战斗 HUD）→ 不执行；box={box}")
            return False
        cx, cy = click_point(box)
        on = read_switch_state(image, label, box)
        print(f"[auto_switch] label={label} scene={scene} want={want} 当前={on} "
              f"source={source} box={box} 点击点=({cx},{cy})")
        if on is None:
            print(f"[auto_switch][FAIL] 状态读不出（探针无橙/灰判据）→ 不执行；box={box}")
            return False
        if bool(on) == bool(want):
            print(f"[auto_switch] 已是期望状态（{on}）→ 不动")
            return True

        _click_box(context, click_action, cx, cy)
        import time

        time.sleep(0.6)
        again = read_switch_state(context.tasker.controller.post_screencap().wait().get(), label, box)
        if again is not None and bool(again) != bool(want):
            print(f"[auto_switch][FAIL] 点后仍未达期望（{again}）—— 已按识别框中心点击 ({cx},{cy})")
            return False
        print(f"[auto_switch] 已设 {label} -> {want}（复查 {again}）")
        return True

    def _set_battle(self, context, image, label, scene, want, click_action, ocr_entry):
        """★#71 战斗页作用域★：定位战斗 HUD 的「自动」→ 读青绿状态 → 只在**正证据为「开」**时关一次。

        安全纪律（详见类 docstring）：定位不到 / 读不出 → 不动作 + ``[auto_switch][FAIL]``；
        点后用新截图复查，仍为「开」（或判不出）→ FAIL、**绝不点第二次**；绝不当「判不出」为关。
        """
        box, source = locate_battle_auto(context, image, label, ocr_entry)
        if box is None:
            print(f"[auto_switch][FAIL] scope=battle 定位不到战斗页『{label}』"
                  f"（无战斗 HUD 锚点 / 框中心不在战斗 ROI 内 / OCR 未整串命中）→ 不执行")
            return False
        cx, cy = click_point(box)
        on = read_battle_auto_state(image, label, box)
        print(f"[auto_switch] scope=battle label={label} scene={scene} want={want} 当前={on} "
              f"box={box} 点击点=({cx},{cy})")
        if on is None:
            # ★绝不把「判不出」当成「关」★：读不出就绝不动作。
            print(f"[auto_switch][FAIL] scope=battle 状态读不出（青绿探针判不出）→ 不执行；box={box}")
            return False
        if bool(on) == bool(want):
            print(f"[auto_switch] scope=battle 已是期望状态（{on}）→ 不动")
            return True
        if not on:
            # 读数为关但期望为开：战斗页作用域只用于**关**自动，绝不据此乱点（正证据缺失）。
            print(f"[auto_switch][FAIL] scope=battle 读数为关（{on}）而期望为开 —— "
                  f"战斗页作用域只在正证据为「开」时关自动 → 不执行；box={box}")
            return False

        # 正证据：战斗页 ∧ 读数**明确为「开」** → 点一次（识别框中心）。
        _click_box(context, click_action, cx, cy)
        import time

        time.sleep(0.6)
        again = read_battle_auto_state(
            context.tasker.controller.post_screencap().wait().get(), label, box)
        if again is False:
            print(f"[auto_switch] scope=battle 已设 {label} -> {want}（复查 {again}）")
            return True
        # 仍为「开」或判不出（None）→ 都不得声称成功，且**绝不点第二次**。
        print(f"[auto_switch][FAIL] scope=battle 点后复查未确认关闭（复查={again}）—— "
              f"已按识别框中心点击 ({cx},{cy})，不点第二次")
        return False


# ---------------------------------------------------------------------------
# 自定义识别：auto_cont_dialog（「自动续战功能」确认框）
# ---------------------------------------------------------------------------
class AutoContDialogRecognition(CustomRecognition):
    """识别「自动续战功能」确认框：命中时 ``box`` = 它的「取消」按钮框（读后动）。

    参数（custom_recognition_param）：``ocr_entry``（默认 OcrTask）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        image = argv.image
        if image is None:
            image = context.tasker.controller.post_screencap().wait().get()
        items = ocr_all(context, image, ocr_entry)
        texts = [t for t, _ in items]
        if not any(re.search(p, t or "") for t in texts for p in CONT_DIALOG_PATTERNS):
            return CustomRecognition.AnalyzeResult(box=None, detail={"dialog": False})
        for t, b in items:
            if not b or len(b) != 4:
                continue
            if any(re.search(p, t or "") for p in CONT_DIALOG_CANCEL_PATTERNS):
                return CustomRecognition.AnalyzeResult(
                    box=[int(v) for v in b], detail={"dialog": True, "cancel": t}
                )
        return CustomRecognition.AnalyzeResult(box=None, detail={"dialog": True, "cancel": None})
