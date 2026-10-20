# -*- coding: utf-8 -*-
"""编队（SET / 队）切换：识别 + 动作（#91）；#105 起 A 类「战前编队页」走**双通道**。

★★真机纪律（2026-10-17，384 = 127.0.0.1:16384，720x1280）★★
- 编队页在「角色 → 队伍编成」；顶部一排圆点是 SET 选择器，选中项浮着 `SET N` 标签，
  标签 x 随选中项移动（SET 1 → x=30，SET 10 → x=525，SET 11 → x=578），相邻圆点距 ≈55px。
- 圆点行会**滚动**：同一次标定里 x=109 读到 `SET 1`、x=178 读到 `SET 3` ——
  **固定坐标不可用**。所以只做闭环：`读 SET → 点标签左/右邻 → 再读`，直到目标或步数用尽。
- 队（Party）标签形如 `5 Party E`。队箭头位置**未真机确认** → 每次点击后强制复查，
  队号没变就带原因放弃（绝不盲点连击）。

★★#105：A 类战前编队页的**双通道**★★（模板第二通道 + 解析修好，缺一不可）
- **解析是主修**：真机 484 深渊EX 页的 OCR **能读**（``自动续战``/``Party A``/``SET 1``/
  ``战力``/``141`` 全读到），坏在两条解析 —— 队号大字被吞（``Party A`` 没有数字）、
  ``战力`` 与数值分两个框。:func:`read_team` 已修（字母序号兜底 + 同行绑定数值框）。
- **模板是兜底**：:func:`detect_team_templates` 用 5 张模板（``assets/resource/image/team/``）
  量 A 类页的定版图形；命中即可判页（:func:`is_battle_team_page`）、可用选中槽的 x 推 SET 号、
  可定位 Party 行/战力行后**只裁那一小块再 OCR**（:func:`guided_ocr_crops`）。
- 两条通道**各自都能读对**（``tools/test_team_templates.py`` 两条腿分开跑），
  模板挂掉时（无 numpy / 无图 / 解码失败）一律退回 OCR，绝不因此拒动。

★安装态约定★：`install/` 里没有 `scene/`，所以本模块**不硬依赖** scene；
真源是 ``scene/team.py`` + ``scene/team_templates.py``，安装态用下面的 ``_S_*`` 快照兜底
（与仓库既有做法一致），两者一致性由 ``tools/contract_hooks/hooks_91.py`` 与
``hooks_105.py``（``team-battle-tpl-projection``）把守。★模板 PNG 的读取也不依赖 Pillow★：
安装态的便携 Python 只有 maafw + numpy，所以 :func:`_decode_png` 是 zlib 手写最小解码器
（逐字节对 PIL 校验，见 ``hooks_105`` 的 ``team-battle-tpl-pixels``）。

★★#124：就地切的单位是 **Party**，不是 SET★★
- 真机 394eb66（384，720x1280）受控实验：**左滑（600→200）Party +1、右滑（200→600）Party −1**，
  逐步精确可逆；**SET 不变**（那一行是队伍轮播，不是 SET 页签）；**战力随 Party 变** ⇒ 可作独立证据。
- :func:`switch_party` 用 ``Δ = target - current`` 连滑 ``|Δ|`` 次，每步复核；成功要求
  **SET 不变 ∧ Party == target ∧ 战力变化** 三者同时成立；失败重试 ≤1 次、``|Δ| ≤ 12``（有界）。
- 真机 10 队（2026-10-18，384）：Party **1..10 环形轮播**（左滑 10→1、右滑 1→10，无滑不动的边界）；
  1..10 内最大 ``|Δ|=9 ≤ 12`` ⇒ **环形不改变算法**（不按环取模）。
- ★越界**一步不滑**★：**先判「目标是否存在（1..TEAM_PARTY_COUNT）」，再判「要滑几步（|Δ| 上限）」**，
  两个判断都在任何 read / swipe **之前**；默认**绝不夹紧**（静默夹紧 = 让调用方以为切到了越界值），
  要夹紧必须调用方显式 ``clamp=True``（会打印夹紧结果）。
- ``switch_party`` 的 IO 全部由调用方注入（``read_hook`` / ``swipe_hook`` / ``tap_hook``），
  所以离线守卫能完整验证算法；生产入口有两个：探针 ``tools/probe_team_carousel.py --target``
  与动作 :class:`TeamSwitchBattleAction`（``party`` 参数，走 ``ocr_team_state`` + 原生 Swipe）。

对外：
- ``custom_recognition = "team_state"``  参数：set / party（可选；用于「必须已经是这队」的门控）
- ``custom_action      = "team_switch"`` 参数：set / party / max_steps / ocr_entry
- ``custom_action      = "team_switch_battle"`` 参数：set / party / max_steps / ocr_entry（A 类页就地切；
  ``party`` 是**动作目标**：走 :func:`switch_party` 横向滑动 + 三重校验；读不到编队 / 不在 A 类页 ⇒ 拒动）
- ``switch_party(target, *, tap_hook=None, swipe_hook=None, read_hook=None) -> bool``（#124：A 类页切 Party）
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import NamedTuple

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from maa_util import ocr_all, read_action_param, read_param
from phantom_impl import _click_box, _grab

try:  # 仓库态：真源
    from scene import team as _SCENE_TEAM  # noqa: PLC0415

    CFG_SOURCE = "scene"
except ModuleNotFoundError:  # 安装态：无 scene/
    _SCENE_TEAM = None
    CFG_SOURCE = "snapshot"

try:  # 仓库态：模板真源（#105）
    from scene import team_templates as _SCENE_TPL  # noqa: PLC0415

    TPL_SOURCE = "scene"
except ModuleNotFoundError:  # 安装态：无 scene/
    _SCENE_TPL = None
    TPL_SOURCE = "snapshot"

# ---- 快照（必须与 scene/team.py 逐项一致；hooks_91 把守）----
_S_SET_ROW_Y = 30
_S_SET_STEP_PX = 55
_S_SET_MAX = 11
_S_PARTY_COUNT = 10
_S_SET_RE = r"SET\s*(\d+)"
_S_PARTY_RE = r"(?:(\d+)\s*)?Party\s*([A-Z])"
_S_POWER_RE = r"战力"
_S_MAX_STEPS = 16
_S_TAP_MIN_X = 12
_S_TAP_MAX_X = 708
_S_OPTION_NONE = "不切换"
_S_PRESET_384 = (1, 5)
_S_PRESET_484 = (1, 1)
#: ★#105★ A 类「战前编队页」几何（与 B 类分开；真源 scene/team.py）。
_S_BATTLE_SET_ROW_Y = 466
_S_BATTLE_SET_STEP_PX = 49
_S_BATTLE_SET_MAX = 12
_S_BATTLE_SET_LABEL_X = 84
_S_PAGE_ANCHOR_A = "自动续战"
_S_PAGE_ANCHOR_B = "^切换$"
#: ★#105★ 队名字母表（字母序号 == 队号；仅在队号数字被 OCR 吞掉时兜底）。
#: 长度必须 == ``TEAM_PARTY_COUNT``（真机 10 队 ⇒ A..J）；短了 ``Party I/J`` 会退化成
#: 「读不到 Party」。``hooks_124`` 的 ``party-alphabet-count`` 与 ``hooks_105`` 的投影守卫把守。
_S_PARTY_LETTERS = "ABCDEFGHIJ"
#: ★#105★ 模板通道的本地 OCR 窗口 / 同行绑定容差（真源 scene/team_templates.py）。
_S_PARTY_NO_CROP = (16, 505, 70, 50)
_S_POWER_ROW = (480, 500, 240, 46)
_S_POWER_ROW_DY = 14
_S_POWER_ROW_DX = (0, 200)
#: ★#105★ SET 槽位几何（模板左上角 x；真源 scene/team_templates.py）。
_S_SET_SLOT_TAB_X = (126, 337, 549)
_S_SET_SLOT_BAR_X0 = 68
_S_SET_SLOT_BAR_STEP = 49
_S_SET_SLOT_BAR_MAX = 12
_S_SET_SNAP_TOL = 6
#: ★#105★ 参与页判据的模板键（任一命中即算）。
_S_PAGE_KEYS = ("auto_continue", "set_selected", "challenge_btn", "party_label", "power_label")
#: ★#105★ 五张模板的快照 ``(key, template, roi, threshold, order_by, window)``。
#: 与 ``scene.team_templates.TEAM_TEMPLATES`` 逐项一致（``hooks_105`` 的
#: ``team-battle-tpl-projection`` 把守）；安装态没有 ``scene/``，模板通道靠这份快照活着。
_S_TEAM_TEMPLATES = (
    ("auto_continue", "team/auto_continue.png", (0, 1040, 140, 60), 0.90, "Score", (16, 1061, 82, 26)),
    ("set_selected", "team/set_selected.png", (40, 440, 640, 60), 0.88, "Score", (126, 456, 34, 20)),
    ("challenge_btn", "team/challenge_btn.png", (250, 1040, 220, 80), 0.88, "Score", (296, 1066, 66, 40)),
    ("party_label", "team/party_label.png", (60, 500, 300, 46), 0.90, "Score", (92, 514, 58, 26)),
    ("power_label", "team/power_label.png", (480, 500, 200, 46), 0.90, "Score", (524, 515, 44, 27)),
)


def _cfg(name: str, snapshot):
    return getattr(_SCENE_TEAM, name, snapshot) if _SCENE_TEAM is not None else snapshot


TEAM_SET_ROW_Y = _cfg("TEAM_SET_ROW_Y", _S_SET_ROW_Y)
TEAM_SET_STEP_PX = _cfg("TEAM_SET_STEP_PX", _S_SET_STEP_PX)
TEAM_MAX_SETS = _cfg("TEAM_MAX_SETS", _S_SET_MAX)
TEAM_PARTY_COUNT = _cfg("TEAM_PARTY_COUNT", _S_PARTY_COUNT)
TEAM_SET_RE = _cfg("TEAM_SET_RE", _S_SET_RE)
TEAM_PARTY_RE = _cfg("TEAM_PARTY_RE", _S_PARTY_RE)
TEAM_POWER_RE = _cfg("TEAM_POWER_RE", _S_POWER_RE)
TEAM_MAX_STEPS = _cfg("TEAM_MAX_STEPS", _S_MAX_STEPS)
TEAM_TAP_MIN_X = _cfg("TEAM_TAP_MIN_X", _S_TAP_MIN_X)
TEAM_TAP_MAX_X = _cfg("TEAM_TAP_MAX_X", _S_TAP_MAX_X)
TEAM_OPTION_NONE = _cfg("TEAM_OPTION_NONE", _S_OPTION_NONE)
TEAM_PRESET_384 = _cfg("TEAM_PRESET_384", _S_PRESET_384)
TEAM_PRESET_484 = _cfg("TEAM_PRESET_484", _S_PRESET_484)
#: ★#105★ A 类战前编队页几何（真源 scene/team.py；两套坐标绝不混用）
TEAM_BATTLE_SET_ROW_Y = _cfg("TEAM_BATTLE_SET_ROW_Y", _S_BATTLE_SET_ROW_Y)
TEAM_BATTLE_SET_STEP_PX = _cfg("TEAM_BATTLE_SET_STEP_PX", _S_BATTLE_SET_STEP_PX)
TEAM_BATTLE_SET_MAX = _cfg("TEAM_BATTLE_SET_MAX", _S_BATTLE_SET_MAX)
TEAM_BATTLE_SET_LABEL_X = _cfg("TEAM_BATTLE_SET_LABEL_X", _S_BATTLE_SET_LABEL_X)
TEAM_PAGE_ANCHOR_A = _cfg("TEAM_PAGE_ANCHOR_A", _S_PAGE_ANCHOR_A)
TEAM_PAGE_ANCHOR_B = _cfg("TEAM_PAGE_ANCHOR_B", _S_PAGE_ANCHOR_B)
#: ★#105★ 队名字母表 / 模板引导的局部 OCR 窗口 / 同行绑定容差 / SET 槽位几何
TEAM_PARTY_LETTERS = _cfg("TEAM_PARTY_LETTERS", _S_PARTY_LETTERS)
TEAM_PARTY_NO_CROP = _cfg("PARTY_NO_CROP", _S_PARTY_NO_CROP)
TEAM_POWER_ROW = _cfg("POWER_ROW", _S_POWER_ROW)
TEAM_POWER_ROW_DY = _cfg("POWER_ROW_DY", _S_POWER_ROW_DY)
TEAM_POWER_ROW_DX = _cfg("POWER_ROW_DX", _S_POWER_ROW_DX)
TEAM_SET_SLOT_TAB_X = _cfg("SET_SLOT_TAB_X", _S_SET_SLOT_TAB_X)
TEAM_SET_SLOT_BAR_X0 = _cfg("SET_SLOT_BAR_X0", _S_SET_SLOT_BAR_X0)
TEAM_SET_SLOT_BAR_STEP = _cfg("SET_SLOT_BAR_STEP", _S_SET_SLOT_BAR_STEP)
TEAM_SET_SLOT_BAR_MAX = _cfg("SET_SLOT_BAR_MAX", _S_SET_SLOT_BAR_MAX)
TEAM_SET_SNAP_TOL = _cfg("SET_SNAP_TOL", _S_SET_SNAP_TOL)
TEAM_PAGE_KEYS = _cfg("PAGE_KEYS", _S_PAGE_KEYS)


def party_ordinal(letter):
    """``"A"`` → 1 … ``"J"`` → 10；不在 :data:`TEAM_PARTY_LETTERS` 里返回 ``None``。

    真源 `scene.team.party_ordinal`；安装态用本地实现（同一份表，``hooks_105`` 核对逐项一致）。
    """
    key = (letter or "").strip().upper()
    if len(key) != 1 or key not in TEAM_PARTY_LETTERS:
        return None
    return TEAM_PARTY_LETTERS.index(key) + 1


def team_template_specs():
    """``[(key, template, roi, threshold, order_by, window), …]``（仓库态读真源，安装态读快照）。"""
    if _SCENE_TPL is not None:
        return [
            (s.key, s.template, tuple(s.roi), s.threshold, s.order_by, tuple(s.window))
            for s in (getattr(_SCENE_TPL, "TEAM_TEMPLATES", {}) or {}).values()
        ]
    return list(_S_TEAM_TEMPLATES)


def set_slots():
    """全部候选 SET 槽位 ``[(x, set_no, layout), …]``（真源 ``scene.team_templates.set_slots``）。"""
    if _SCENE_TPL is not None and hasattr(_SCENE_TPL, "set_slots"):
        return _SCENE_TPL.set_slots()
    slots = [(x, i + 1, "tab3") for i, x in enumerate(TEAM_SET_SLOT_TAB_X)]
    slots += [
        (TEAM_SET_SLOT_BAR_X0 + TEAM_SET_SLOT_BAR_STEP * (n - 1), n, "barN")
        for n in range(1, TEAM_SET_SLOT_BAR_MAX + 1)
    ]
    return slots


def set_index_from_pill(pill_x, tol=None):
    """选中槽 x → SET 号；有歧义/够不着返回 ``None``（真源同 ``scene.team_templates``）。"""
    if _SCENE_TPL is not None and hasattr(_SCENE_TPL, "set_index_from_pill"):
        return _SCENE_TPL.set_index_from_pill(
            pill_x, TEAM_SET_SNAP_TOL if tol is None else tol
        )
    if pill_x is None:
        return None
    try:
        x = int(pill_x)
    except (TypeError, ValueError):
        return None
    tol = TEAM_SET_SNAP_TOL if tol is None else tol
    hits = [(abs(x - sx), n, layout) for sx, n, layout in set_slots() if abs(x - sx) <= tol]
    if not hits:
        return None
    hits.sort()
    best_res, best_no, best_layout = hits[0]
    for res, _n, layout in hits[1:]:
        if layout != best_layout and res - best_res <= 1:
            return None
    return best_no, best_layout, best_res


#: 队切换箭头候选点（720x1280）。★未真机确认★——动作里每次点击后都复查队号。
TEAM_PARTY_ARROWS = ((27, 625), (693, 625))

_SET_RE = re.compile(TEAM_SET_RE)
_PARTY_RE = re.compile(TEAM_PARTY_RE)


# ---------------------------------------------------------------------------
# 纯逻辑（可单测；不碰 context）
# ---------------------------------------------------------------------------
def set_tap_plan(current: int, target: int, pill_box):
    """「往目标 SET 走一步」该点哪里；返回 ``(tap_x, direction)``，已到目标返回 None。

    ★为什么按标签算而不是按序号算★：真机实测圆点行会随选中项滚动，
    固定坐标点几次就偏一位（标定帧里 x=109 → SET 1、x=178 → SET 3）。
    """
    if current == target:
        return None
    if not pill_box or len(pill_box) < 3:
        return None
    x, _y, w = int(pill_box[0]), int(pill_box[1]), int(pill_box[2])
    direction = -1 if target < current else 1
    tap_x = x - TEAM_SET_STEP_PX if direction < 0 else x + w + TEAM_SET_STEP_PX
    tap_x = max(TEAM_TAP_MIN_X, min(TEAM_TAP_MAX_X, tap_x))
    return tap_x, direction


from battle_loop_core import has_challenge_page_text as _has_challenge  # noqa: E402


def read_team(items, hits=None):

    # ★#105 真机★ 只排除「SET编辑」页，不用 `is_battle_team_page` 当总门：
    #   真机 `debug/r54_setedit.png` 是「狂热激战用SET编辑」页（顶部 `● SET2` + `Party A..E`
    #   五行 + ✓）。那页的 `● SETn` 是**编辑器正在显示哪个 SET**，不是战斗 SET；
    #   旧实现把它读成战斗 SET ⇒ 制造「切成功了」的假成功。
    #   判别：`Party X` 行数 >= 3 且没有 A 类页锚（`自动续战` / `挑战`）。
    #   ★不用总门的原因★：「只开模板」那条腿只喂两块局部裁片，OCR 侧没有页锚，
    #   `is_battle_team_page` 会 False；用总门会把这条诚实的腿挡掉。
    _texts = [(t or "").strip() for t, _b in (items or ()) if (t or "").strip()]
    _party_rows = sum(1 for t in _texts if re.fullmatch(r"Party\s*[A-Za-z]", t))
    #   ★#112 棘轮★ 不许裸字面量：A 类页锚走真源常量，挑战走共享判据（`挑战` / `挑战→` 都算）。
    _has_page_anchor = any(TEAM_PAGE_ANCHOR_A in t for t in _texts) or _has_challenge(_texts)
    if _party_rows >= 3 and not _has_page_anchor:
        return (None, None, None)

    """从 OCR 项里读 ``(set, party, power)``；``set`` 是 ``(号码, 标签框)``，读不到的项为 None。

    ★#105 修正（**纯解析**，不依赖任何模板）★ 真机 484 深渊EX 战前编队页上本函数曾返回
    ``(None, None, None)``，原因**不是 OCR 读不到**（实测 ``自动续战``/``Party A``/``SET 1``/
    ``战力``/``141`` 全部读到，score 0.94~0.9999），而是两条解析 bug：

    1. ``party`` 的正则要求 ``Party`` 前必须有队号数字，而真机把队号大字 ``1`` **吞掉**、
       只给 ``Party A``。现在：有数字用数字；只有字母名时按 :func:`scene.team.party_ordinal`
       兜底（``A``→1、``E``→5，两条真机样本一致，见 ``TEAM_PARTY_LETTERS`` 的注释）；
    2. ``战力`` 与数值是**两个独立 OCR 框**（``战力``@(525,516) / ``141``@(590,516)），
       原实现只在同一框内找数字。现在再按「同一行 + 在 ``战力`` 右侧」绑定数值框
       （:data:`TEAM_POWER_ROW`）。

    另外两条**模板通道**兜底（``hits`` 由 :func:`detect_team_templates` 量出来）：

    * ``SET``：OCR 读不到 ``SET N`` 时，用 ``set_selected`` 模板的命中 x 经
      :func:`scene.team_templates.set_index_from_pill` 换成 SET 号（``hits.set_index``）；
    * ``party``：队号大字被吞时，模板定位后的**局部 OCR** 结果（框落在 ``PARTY_NO_CROP`` 里
      的纯数字项）就是队号 —— 这条由调用方把局部 OCR 的项并进 ``items`` 来启用
      （见 :func:`guided_ocr_crops`）。

    ``hits=None`` ⇒ **纯 OCR 解析路径**（模板完全不参与）：老调用方的签名与行为不受影响，
    但解析本身按本票修好了（队号可缺、战力可跨框）—— 相对 #91 版本「队号必须有数字、
    战力必须同框」这两条，是**加宽**而不是改窄。``tools/test_team_templates.py`` 的
    「只改解析」那条腿就是钉住这一点：**即使一张模板都不加，真帧也必须读出 SET 1 / 队 1 / 141**。
    """
    set_no = party_no = power = None
    party_letter = None
    power_label_box = None
    numbers_in_party_crop = []
    for text, box in items or []:
        raw = (text or "").strip()
        box_list = list(box or [])
        if set_no is None:
            m = _SET_RE.search(raw.replace(" ", ""))
            if m:
                set_no = (int(m.group(1)), box_list)
        if party_letter is None:
            m = _PARTY_RE.search(raw)
            if m:
                party_letter = m.group(2)
                if m.group(1):
                    party_no = int(m.group(1))
        if power is None and TEAM_POWER_RE in raw:
            digits = re.sub(r"[^0-9]", "", raw.split(TEAM_POWER_RE, 1)[-1])
            if digits:
                power = int(digits)
            else:
                power_label_box = box_list
        # 模板定位后的局部 OCR：队号大字单独一个纯数字框，落在 PARTY_NO_CROP 里。
        if _digits_only(raw) and _center_inside(box_list, TEAM_PARTY_NO_CROP):
            numbers_in_party_crop.append((int(_digits_only(raw)), box_list))
    # ① 队号：文字里的数字 > 模板证明「这里是 Party 行」+ 局部 OCR 的数字框 > 字母序号兜底
    #    ★局部 OCR 那条必须由模板证明★：没有 `party_label` 命中，`PARTY_NO_CROP` 里的数字
    #    可能是任何东西（B 类页 / 详情页上都有数字），绑成队号就是静默错。
    party_hit = hits is not None and "party_label" in (getattr(hits, "hit_keys", ()) or ())
    if party_no is None and party_hit and numbers_in_party_crop:
        party_no = numbers_in_party_crop[0][0]
    if party_no is None and party_letter:
        party_no = party_ordinal(party_letter)
    # ② 战力：同框数字已在上面取到；否则把「同一行、在战力右侧」的数字框绑过来
    if power is None and power_label_box is not None:
        power = _power_near_label(items, power_label_box)
    # ③ SET：模板通道兜底（OCR 一个字都没读到时也不塌）
    if set_no is None and hits is not None:
        idx = getattr(hits, "set_index", None)
        if idx:
            set_no = (int(idx), list(getattr(hits, "set_box", None) or []))
    return set_no, party_no, power


def _digits_only(text: str):
    """``"141"`` / ``"8,876"`` -> 数字串；含非数字（除逗号/点/空格）返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"[0-9][0-9,.\s]*", raw):
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    return digits or None


def _center_inside(box, rect) -> bool:
    """``box`` 的中心是否落在 ``rect`` 内（720 空间 ``[x, y, w, h]``）。"""
    if not box or len(box) < 4 or not rect or len(rect) < 4:
        return False
    cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
    x, y, w, h = rect[0], rect[1], rect[2], rect[3]
    return x <= cx <= x + w and y <= cy <= y + h


def _power_near_label(items, label_box):
    """战力数值的**同行绑定**：``战力`` 与数值是两个 OCR 框，按几何把数字框绑过来。

    条件（全部满足才算，宁可读不到也不绑定错的数字）：纯数字项 ∧ y 中心与 ``战力`` 框差
    ≤ :data:`TEAM_POWER_ROW_DY` ∧ x 在 ``战力`` 框右侧 :data:`TEAM_POWER_ROW_DX` 窗口内。
    取最靠左的那个（真机 ``141`` / ``8,876`` / ``12,205`` 都紧贴右边）。
    """
    if not label_box or len(label_box) < 4:
        return None
    lx, ly, lw, lh = (int(v) for v in label_box[:4])
    ly_center = ly + lh / 2.0
    dx0, dx1 = TEAM_POWER_ROW_DX
    best = None
    for text, box in items or []:
        digits = _digits_only(text)
        if not digits or not box or len(box) < 4:
            continue
        bx, by, bw, bh = (int(v) for v in box[:4])
        if abs((by + bh / 2.0) - ly_center) > TEAM_POWER_ROW_DY:
            continue
        if not (dx0 <= (bx - lx) <= dx1):
            continue
        if best is None or bx < best[0]:
            best = (bx, int(digits))
    return best[1] if best else None


# ===========================================================================
# ★#124★ Party 切换：横向滑动 + 三重校验（就地切的单位是 Party，不是 SET）
# ===========================================================================
#: ★真源已迁 ``scene/team.py``★（#124 收尾：纯搬家，**数值一字未改**）。
#: 安装态没有 ``scene/``，所以这里保留**逐字冻结快照**（``_TEAM_PARTY_*_SNAPSHOT``）；
#: 仓库态一律在**运行时**读真源（``_cfg``）。两侧任何一侧改动都会被 ``hooks_124`` 的
#: ``party-constants-source-of-truth`` 当场判红（逐字比对，连类型一起比）。
#:
#: 真机 394eb66（384，720x1280）：左滑（600→200）Party +1、右滑（200→600）Party −1，
#: 逐步精确可逆；**SET 不变**；战力随 Party 变（⇒ 三重校验的第三票）。
_TEAM_PARTY_SWIPE_LEFT_SNAPSHOT = (600, 200)
_TEAM_PARTY_SWIPE_RIGHT_SNAPSHOT = (200, 600)
_TEAM_PARTY_SWIPE_MS_SNAPSHOT = 450
_TEAM_PARTY_STEP_SLEEP_SNAPSHOT = 1.6
_TEAM_PARTY_SWIPE_MAX_SNAPSHOT = 12
_TEAM_PARTY_RETRIES_SNAPSHOT = 1

#: 端点 x 固定；y 一律取**当帧 ``read_team`` 的 SET 框中心**（票面：不写死行高）。
TEAM_PARTY_SWIPE_LEFT = _cfg("TEAM_PARTY_SWIPE_LEFT", _TEAM_PARTY_SWIPE_LEFT_SNAPSHOT)
TEAM_PARTY_SWIPE_RIGHT = _cfg("TEAM_PARTY_SWIPE_RIGHT", _TEAM_PARTY_SWIPE_RIGHT_SNAPSHOT)
#: 单次滑动时长（ms）：与入库探针 ``tools/probe_team_carousel.py`` 的 450ms 同口径。
TEAM_PARTY_SWIPE_MS = _cfg("TEAM_PARTY_SWIPE_MS", _TEAM_PARTY_SWIPE_MS_SNAPSHOT)
#: 每一步之后的稳定间隔（秒）：探针实测每步 1.6s 后读数稳定（SET 条是动画轮播，读早了会读旧值）。
TEAM_PARTY_STEP_SLEEP = _cfg("TEAM_PARTY_STEP_SLEEP", _TEAM_PARTY_STEP_SLEEP_SNAPSHOT)
#: ``|Δ|`` 上限（票面建议 12）：**超过就一步也不滑**，直接带量失败（有界，绝不无限滑）。
TEAM_PARTY_SWIPE_MAX = _cfg("TEAM_PARTY_SWIPE_MAX", _TEAM_PARTY_SWIPE_MAX_SNAPSHOT)
#: 失败重试次数上限（票面 ≤1；总尝试次数 = 1 + TEAM_PARTY_RETRIES）。
TEAM_PARTY_RETRIES = _cfg("TEAM_PARTY_RETRIES", _TEAM_PARTY_RETRIES_SNAPSHOT)


class TeamReading(NamedTuple):
    """一次 ``read_team`` 读数的归一化形状（#124）。"""

    #: SET 号（读不到 None）。
    set_no: object
    #: Party 号（读不到 None）。
    party: object
    #: 战力（读不到 None）。
    power: object
    #: ``SET N`` 的 OCR/模板框 ``[x, y, w, h]``（720 空间；没有就是空元组）。
    set_box: tuple = ()

    @property
    def readable(self) -> bool:
        """能不能算「读到了」：SET 与 Party 都必须在（战力可以缺，但三重校验会因此失败）。"""
        return self.set_no is not None and self.party is not None


def _to_int(value):
    """宽容转 int：``None`` / 转不了 → ``None``（守卫喂坏形状时不抛）。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_team_reading(state):
    """``read_team`` 的返回值 → :class:`TeamReading`；形状不对返回 ``None``。

    兼容两种历史形状：``(set, party, power)``（当前）与 ``{"set": …, "party": …, "power": …}``
    （``tools/verify_team_battle.py::_unpack`` 也兼容它）；``set`` 既可以是 ``(号码, 框)``
    也可以是裸号码。
    """
    if isinstance(state, dict):
        cur = state.get("set")
        box = ()
        if isinstance(cur, (tuple, list)) and cur:
            if len(cur) > 1 and isinstance(cur[1], (tuple, list)):
                box = tuple(cur[1])
            cur = cur[0]
        return TeamReading(_to_int(cur), _to_int(state.get("party")), _to_int(state.get("power")), box)
    if not isinstance(state, (tuple, list)) or len(state) != 3:
        return None
    cur, party, power = state
    box = ()
    if isinstance(cur, (tuple, list)):
        if len(cur) > 1 and isinstance(cur[1], (tuple, list)):
            box = tuple(cur[1])
        cur = cur[0] if cur else None
    return TeamReading(_to_int(cur), _to_int(party), _to_int(power), box)


def verify_party_switch(origin, final, target):
    """三重校验（★票面：SET 不变 ∧ Party == target ∧ 战力变化，三者同时成立才算成功★）。

    ``origin`` / ``final`` 是 :class:`TeamReading`（起点读数 / 终点读数），``target`` 是目标 Party 号。
    返回 ``(ok, reasons)``：``reasons`` 逐条**带量**（谁变了、从多少到多少），失败日志直接拼它。

    ★为什么战力也算一票★：真机已证 Party 变 ⇒ 战力变（394eb66）。只读到 Party 命中而战力没变，
    说明读到的是残留/错行（假成功）——必须当失败，绝不放行。
    """
    reasons = []
    if origin is None or final is None:
        return False, ["读数缺失（orig/final 为空）"]
    if origin.set_no is None:
        reasons.append("起点 SET 读不到（无法证明 SET 没变）")
    elif final.set_no is None:
        reasons.append(f"终点 SET 读不到（起点 {origin.set_no}）")
    elif int(final.set_no) != int(origin.set_no):
        reasons.append(f"SET 变了：{origin.set_no}→{final.set_no}（票面：切 Party 时 SET 必须不变）")
    if final.party is None or int(final.party) != int(target):
        reasons.append(f"Party 没到位：当前 {final.party} / 目标 {target}")
    if origin.power is None or final.power is None:
        reasons.append(f"战力读不到（{origin.power}→{final.power}），无法证明换队生效")
    elif int(final.power) == int(origin.power):
        reasons.append(f"战力没变：{origin.power}→{final.power}（换队没有生效证据）")
    return (not reasons, reasons)


def party_swipe_geometry(direction: int, row_y: int):
    """方向 → 滑动端点 ``(x_from, x_to, y)``。

    ``+1`` = Party 变大 ⇒ **左滑**（手指 600→200）；``-1`` = Party 变小 ⇒ **右滑**（200→600）。
    方向反了这条函数先红（``hooks_124`` 的方向守卫就是照它下嘴的）。
    """
    x_from, x_to = TEAM_PARTY_SWIPE_LEFT if int(direction) > 0 else TEAM_PARTY_SWIPE_RIGHT
    return int(x_from), int(x_to), int(row_y)


def party_swipe_gap_ok(gap) -> bool:
    """``|Δ|`` 是否在允许范围内：**超过就一步都不滑**（有界，绝不无限滑）。

    ★顺序★：先问 :func:`party_target_ok`（目标存不存在），再问本函数（要滑几步）。
    """
    return abs(int(gap)) <= int(TEAM_PARTY_SWIPE_MAX)


def party_target_ok(target) -> bool:
    """目标 Party 是否存在（``1..TEAM_PARTY_COUNT``）。

    ★这条判断必须在任何 read / swipe 之前★：真机缺陷是 ``switch_party(11)`` 从 Party 10 起
    滑了 11 次才失败、还把轮播留在 Party 1（副作用）。存在的目标才配得到一次滑动。
    ``None`` / 非整数 / 越界一律 ``False``（不抛）。
    """
    want = _to_int(target)
    return want is not None and 1 <= want <= int(TEAM_PARTY_COUNT)


def clamp_party_target(target) -> int:
    """把目标夹到 ``1..TEAM_PARTY_COUNT``（**只给显式 ``clamp=True`` 的调用方用**）。

    ★为什么默认不夹紧★：目标 11 夹成 10 会让调用方以为切到了 11 —— **静默错队比失败更糟**。
    默认路径遇到越界目标直接失败（零滑动）；只有调用方明说 ``clamp=True`` 时才走这里，并把
    夹紧结果打印出来（:func:`switch_party` 负责打印，别在调用点静默用）。
    """
    return max(1, min(int(TEAM_PARTY_COUNT), int(target)))


def _sleep(seconds: float) -> None:
    """休眠（**模块级函数**，离线测试可 ``team_impl._sleep = 假睡眠`` 打桩；与 ``lords_impl`` 同一手法）。"""
    time.sleep(max(0.0, float(seconds)))


def _default_read_state():
    """缺省读数缝（票面「假 read_team」口径）：走模块级 :func:`read_team`。

    本模块没有 context，所以缺省帧源为空 ⇒ ``read_team(None)`` = 读不到 ⇒ **带原因失败，绝不假成功**。
    真实调用方传 ``read_hook=``（动作里有 context，探针里有 ``Page``）。
    ★守卫/单测替换模块级 ``read_team`` 即可生效★：这里按名字在调用时取，不提前绑定。
    """
    return read_team(None)


def _read_once(read):
    """读一次并归一化；异常/形状不对**打印原因**并返回 ``None``（动作异常必须留痕，#120）。"""
    try:
        raw = read()
    except Exception as exc:  # noqa: BLE001
        print(f"[team_party] 读帧异常：{type(exc).__name__}: {exc}")
        return None
    if isinstance(raw, TeamReading):  # 调用方直接给归一化读数也收（少一层转换就少一个坑）
        return raw
    reading = to_team_reading(raw)
    if reading is None:
        print(f"[team_party] 读帧返回形状不对：{raw!r}（应为 read_team 的 (set, party, power)）")
    return reading


def _set_row_y(reading):
    """SET 框中心 y（720 空间）；没有框返回 ``None`` —— **绝不写死行高**。"""
    box = getattr(reading, "set_box", ()) if reading is not None else ()
    if not box or len(box) < 4:
        return None
    return int(round(float(box[1]) + float(box[3]) / 2.0))


def _set_row_center(reading):
    """SET 框中心 ``(x, y)``（给可选的 ``tap_hook`` 用）；没有框返回 ``None``。"""
    box = getattr(reading, "set_box", ()) if reading is not None else ()
    if not box or len(box) < 4:
        return None
    return (
        int(round(float(box[0]) + float(box[2]) / 2.0)),
        int(round(float(box[1]) + float(box[3]) / 2.0)),
    )


def _party_switch_success_line(origin, final, swipes: int, attempt: int) -> str:
    """成功日志（三重校验的三票都印出来，真机第一跑就盯这一行）。"""
    return (
        f"[team_party] ✓ 切队成功：SET {origin.set_no}（不变）/ Party {origin.party}→{final.party} / "
        f"战力 {origin.power}→{final.power}（共滑 {swipes} 次，尝试 {attempt} 次）"
    )


def switch_party(target, *, tap_hook=None, swipe_hook=None, read_hook=None, clamp: bool = False) -> bool:
    """把当前 Party 切到 ``target``（横向滑动 + 三重校验；★只用于 A 类战前编队页★）。

    真机交互模型（394eb66 实测，384，720x1280）::

        左滑（手指右→左，600→200）= Party +1
        右滑（手指左→右，200→600）= Party −1
        SET **不变**（那一行是队伍轮播，不是 SET 页签）
        战力随 Party 变 ⇒ 可作独立证据
        Party **1..10 环形**（2026-10-18：左滑 10→1、右滑 1→10，无滑不动的边界；
        1..10 内最大 |Δ|=9 ≤ 12 ⇒ 环形不改变算法）

    算法::

        ① 目标存在吗？不在 1..TEAM_PARTY_COUNT ⇒ **一步不滑**、直接 False
           （放在任何 read / swipe 之前；越界目标连轮播都不许碰）
        ② clamp 呢？默认 False ⇒ 上面直接失败（**绝不默认夹紧**）；
           clamp=True ⇒ 夹到 1..N 并**打印夹紧结果**
        Δ = target - current
        |Δ| > TEAM_PARTY_SWIPE_MAX(12) ⇒ 一步不滑，直接带量失败（有界）
        连滑 |Δ| 次（左滑加 / 右滑减），**每步后复核读数**，并要求 Party 恰好 ±1、SET 中途不变
        三重校验：SET 不变 ∧ Party == target ∧ 战力变化（三者同时成立才算成功）
        失败重试 ≤1 次（TEAM_PARTY_RETRIES）；仍失败 ⇒ False + 带量原因
        （当前 Party / 目标 / 共滑几次 / 战力）

    IO 缝（本票不碰 pipeline，真机入口由调用方提供）::

        read_hook()                      -> read_team 的 (set, party, power)；缺省走模块级 read_team
        swipe_hook(x_from, x_to, y, ms)  -> 执行一次横向滑动（720 空间坐标）
        tap_hook(x, y)                   -> 可选：第 1 次尝试一步没动时轻点 SET 条（默认不点）
        clamp=False                      -> 默认**绝不夹紧**；True 才允许把越界目标夹到 1..N

    ★为什么默认不夹紧★：目标 11 夹成 10 会让调用方以为切到了 11（**静默错队比失败更糟**）。
    夹紧只能是调用方的显式要求，且必须打印结果 —— 默认路径遇到越界目标**一步不滑**就失败。

    ★为什么 tap_hook 默认不点★：真机证据表明切 Party 只需要横向滑动 —— 点那条行 / ``SET编辑`` /
    ``推荐编成`` 都不能切 SET（394eb66）。所以正常路径**绝不盲点**；只有调用方显式提供
    ``tap_hook``、且某次尝试**一步都没动**（典型：轮播条没焦点/被遮挡）时，才在重试前轻点一次
    SET 条中心（几何同样来自当帧 SET 框），是否启用这个动作由调用方决定。

    ★真机第一跑盯哪一行★：每步的
    ``[team_party]   ← 左滑 i/n @y=…（600→200）→ Party … / 战力 …``
    —— 应看到 Party 每步**恰好 +1**、SET 一直是同一个数；收尾那行
    ``[team_party] ✓ 切队成功：SET …（不变）/ Party a→b / 战力 c→d（共滑 n 次，尝试 m 次）``
    是三票齐全的唯一结论。
    """
    try:
        want = int(target)
    except (TypeError, ValueError):
        print(f"[team_party] ✗ 目标非法：{target!r}（应为 Party 号整数）→ 不动")
        return False
    # ★#124 收尾①★ **先判「目标是否存在」，再判「要滑几步」** —— 两条都在任何 read/swipe 之前。
    #   真机缺陷：switch_party(11) 从 Party 10 起滑了 11 次才失败，还把轮播留在 Party 1。
    #   铁律：不存在的目标，一步都不滑（连读数都不读 —— 存在性是纯目标属性）。
    if not party_target_ok(want):
        if not clamp:
            print(
                f"[team_party] ✗ 目标 Party {want} 不存在（真机轮播 1..{int(TEAM_PARTY_COUNT)}）"
                f"—— 一步没滑"
            )
            return False
        # ★#124 收尾②★ 只有调用方显式 clamp=True 才夹紧，而且必须打印夹紧结果（绝不静默）。
        clamped = clamp_party_target(want)
        print(
            f"[team_party] ! 目标 Party {want} 不存在（真机轮播 1..{int(TEAM_PARTY_COUNT)}）；"
            f"调用方显式 clamp=True → 夹紧到 {clamped}（默认不夹紧，静默夹紧会让调用方以为"
            f"切到了 {want}）"
        )
        want = clamped

    read = read_hook if read_hook is not None else _default_read_state
    max_attempts = 1 + max(0, int(TEAM_PARTY_RETRIES))
    origin = None  # 第一次成功读数：三重校验的基准（重试也不改它 —— 否则 SET 变了会被重试掩盖）
    last = None
    total_swipes = 0
    taps = 0
    reasons: list = []
    attempt = 0

    for attempt in range(1, max_attempts + 1):
        start = _read_once(read)
        if start is None or not start.readable:
            reasons = ["读不到当前编队（SET / Party）"]
            print(
                f"[team_party] 第 {attempt} 次：{reasons[0]} → "
                f"{'重试' if attempt < max_attempts else '放弃'}"
            )
            continue
        last = start
        if origin is None:
            origin = start
        row_y = _set_row_y(start)
        print(
            f"[team_party] 第 {attempt} 次读数：SET {start.set_no} / Party {start.party} / 战力 {start.power}"
            f"（目标 Party {want}；滑动行 y={row_y if row_y is not None else '?'}）"
        )

        # 已在目标：没滑过 = 幂等成功；滑过又回到目标 = 必须走三重校验（防「滑出去再回来」的假成功）。
        if int(start.party) == want:
            if total_swipes == 0:
                print(
                    f"[team_party] ✓ 已在目标 Party {want}"
                    f"（SET {start.set_no} / 战力 {start.power}）→ 不动"
                )
                return True
            ok, reasons = verify_party_switch(origin, start, want)
            if ok:
                print(_party_switch_success_line(origin, start, total_swipes, attempt))
                return True
            print(
                f"[team_party] 第 {attempt} 次失败：已在 Party {want} 但三重校验不过："
                f"{'；'.join(reasons)}"
            )
            break

        gap = want - int(start.party)
        if not party_swipe_gap_ok(gap):
            print(
                f"[team_party] ✗ |Δ|={abs(gap)} 超过上限 {TEAM_PARTY_SWIPE_MAX}"
                f"（当前 Party {start.party} → 目标 {want}）→ 一步不滑，直接失败（有界）"
            )
            return False
        if swipe_hook is None:
            print(
                "[team_party] ✗ 没有 swipe_hook：无法执行横向滑动"
                "（本票不碰 pipeline；真机入口由调用方注入）→ 不动"
            )
            return False
        if row_y is None:
            print(
                f"[team_party] ✗ read_team 没给 SET 框的 y（SET {start.set_no}）"
                "→ 不知道滑哪一行，绝不写死 → 不动"
            )
            return False

        direction = 1 if gap > 0 else -1
        print(
            f"[team_party] 起点：SET {start.set_no} / Party {start.party} / 战力 {start.power}"
            f"（目标 Party {want}，Δ={gap:+d} -> {'左滑' if direction > 0 else '右滑'}×{abs(gap)}）"
        )
        attempt_start_party = int(start.party)
        party_now = attempt_start_party
        moved = False
        for step in range(1, abs(gap) + 1):
            x_from, x_to, y = party_swipe_geometry(direction, row_y)
            try:
                swipe_hook(x_from, x_to, y, int(TEAM_PARTY_SWIPE_MS))
            except Exception as exc:  # noqa: BLE001
                reasons = [f"滑动异常：{type(exc).__name__}: {exc}"]
                print(f"[team_party] ✗ {reasons[0]}")
                break
            total_swipes += 1
            _sleep(TEAM_PARTY_STEP_SLEEP)
            cur = _read_once(read)
            if cur is None or not cur.readable:
                reasons = ["滑完读不到读数（SET / Party）"]
                print(f"[team_party]   第 {step} 步：{reasons[0]}")
                break
            last = cur
            expected = party_now + direction
            if int(cur.party) != expected:
                reasons = [f"第 {step} 步没按预期（Party {party_now}→{cur.party}，期望 {expected}）"]
                moved = int(cur.party) != attempt_start_party
                print(f"[team_party]   ! {reasons[0]}")
                break
            if origin.set_no is not None and cur.set_no is None:
                reasons = [f"第 {step} 步 SET 读不到（无法证明还在同一页；起点 SET {origin.set_no}）"]
                moved = int(cur.party) != attempt_start_party
                print(f"[team_party]   ! {reasons[0]}")
                break
            if (
                origin.set_no is not None
                and cur.set_no is not None
                and int(cur.set_no) != int(origin.set_no)
            ):
                reasons = [f"第 {step} 步 SET 中途变了：{origin.set_no}→{cur.set_no}（票面：SET 必须不变）"]
                moved = True
                print(f"[team_party]   ! {reasons[0]}")
                break
            party_now = int(cur.party)
            moved = True
            print(
                f"[team_party]   {'← 左滑' if direction > 0 else '右滑 →'} {step}/{abs(gap)}"
                f" @y={row_y}（{x_from}→{x_to}）→ Party {cur.party} / 战力 {cur.power}"
            )

        ok, reasons = verify_party_switch(origin, last, want)
        if ok:
            print(_party_switch_success_line(origin, last, total_swipes, attempt))
            return True
        print(f"[team_party] 第 {attempt} 次失败：{'；'.join(reasons)}")
        if attempt >= max_attempts:
            break
        if not moved and tap_hook is not None:
            center = _set_row_center(start)
            if center is not None:
                try:
                    tap_hook(center[0], center[1])
                    taps += 1
                    print(
                        f"[team_party]   第 {attempt} 次一步没动 → "
                        f"轻点 SET 条 @({center[0]},{center[1]}) 再重试"
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[team_party]   轻点异常：{type(exc).__name__}: {exc}")
                _sleep(TEAM_PARTY_STEP_SLEEP)

    now = last
    cur_desc = (
        f"SET {now.set_no} / Party {now.party} / 战力 {now.power}"
        if now is not None
        else "读不到（SET/Party/战力）"
    )
    origin_desc = (
        f"SET {origin.set_no} / Party {origin.party} / 战力 {origin.power}"
        if origin is not None
        else "读不到"
    )
    print(
        f"[team_party] ✗ 切队失败（尝试 {attempt} 次 / 共滑 {total_swipes} 次 / 轻点 {taps} 次）："
        f"当前 {cur_desc}；目标 Party {want}；起点 {origin_desc}；"
        f"缺：{'；'.join(reasons) or '未知原因'}"
    )
    return False


# ---------------------------------------------------------------------------
# 识别：当前编队是否等于期望
# ---------------------------------------------------------------------------
class TeamStateRecognition(CustomRecognition):
    """``custom_recognition="team_state"``：参数 ``set`` / ``party`` 可选。

    两者都不给 = 只要认到 SET 标签就命中（用来判断「在编队页」）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        want_set = param.get("set")
        want_party = param.get("party")
        entry = str(param.get("ocr_entry") or "OcrTask")
        img = argv.image if argv.image is not None else _grab(context)
        # ★#105★ 双通道：全屏 OCR + 模板通道（+ 模板引导的局部 OCR）。模板通道不可用时
        # 返回值与旧实现逐项等价（`detect_team_templates` 失败返回 None，`read_team(items, None)`
        # 走纯 OCR 解析路径）。
        (cur_set, cur_party, power), items, hits = ocr_team_state(context, img, entry)
        detail = {
            "set": cur_set[0] if cur_set else None,
            "party": cur_party,
            "power": power,
            "want_set": want_set,
            "want_party": want_party,
            "cfg": CFG_SOURCE,
            "tpl": TPL_SOURCE,
            "tpl_hits": list(getattr(hits, "hit_keys", ()) or ()),
        }
        if cur_set is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={**detail, "why": "读不到 SET 标签"})
        if want_set is not None and int(want_set) != cur_set[0]:
            return CustomRecognition.AnalyzeResult(box=None, detail={**detail, "why": "SET 不符"})
        if want_party is not None and int(want_party) != (cur_party if cur_party else -1):
            return CustomRecognition.AnalyzeResult(box=None, detail={**detail, "why": "队伍不符"})
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)


# ---------------------------------------------------------------------------
# 动作：闭环切到目标 SET / 队
# ---------------------------------------------------------------------------
class TeamSwitchAction(CustomAction):
    """``custom_action="team_switch"``：参数 ``set`` / ``party`` / ``max_steps`` / ``ocr_entry``。"""

    def run(self, context, argv):
        param = read_action_param(argv)
        target_set = int(param.get("set") or 0)
        raw_party = param.get("party")
        target_party = int(raw_party or 0)
        # ★#124 真机后续③★ 区分「不给 party」与「显式给 0」：前者 = 只切 SET（旧语义），
        #   后者 = 0 不是队号（真机 1..10）⇒ 拒动。静默把 0 当成「不切队」= 让调用方以为处理了。
        party_given = raw_party is not None and str(raw_party).strip() != ""
        max_steps = int(param.get("max_steps") or TEAM_MAX_STEPS)
        entry = str(param.get("ocr_entry") or "OcrTask")
        if not (1 <= target_set <= TEAM_MAX_SETS):
            print(f"[team_switch] 目标 SET {target_set} 越界（1..{TEAM_MAX_SETS}）→ 不动")
            return None
        if party_given and not (1 <= target_party <= TEAM_PARTY_COUNT):
            print(
                f"[team_switch] 目标队 {target_party} 不存在（真机轮播 1..{TEAM_PARTY_COUNT}）→ 不动"
            )
            return None

        cur_set = cur_party = None
        for step in range(1, max_steps + 1):
            cur_set, cur_party, power = read_team(ocr_all(context, _grab(context), entry))
            if cur_set is None:
                print(f"[team_switch] 第 {step} 步：读不到 SET 标签（不在编队页？）→ 停手")
                return None
            set_no, box = cur_set[0], cur_set[1]
            print(
                f"[team_switch] 第 {step} 步：SET {set_no} / 队 {cur_party} / 战力 {power}"
                f"（目标 SET {target_set} / 队 {target_party or '-'}）"
            )
            if set_no == target_set:
                break
            plan = set_tap_plan(set_no, target_set, box)
            if plan is None:
                print("[team_switch] 算不出下一步（标签框异常）→ 停手")
                return None
            tap_x, direction = plan
            print(f"[team_switch]   → 点 {direction:+d} 侧 x={tap_x}, y={TEAM_SET_ROW_Y}")
            _click_box(context, tap_x, TEAM_SET_ROW_Y)
            time.sleep(0.9)
        else:
            print(f"[team_switch] ★步数用尽（{max_steps}）仍未到 SET {target_set} → 放弃★")
            return None

        if cur_set and cur_set[0] == target_set and target_party and cur_party != target_party:
            cur_party = self._switch_party(context, target_party, cur_party, entry)
        ok = bool(cur_set and cur_set[0] == target_set and (not target_party or cur_party == target_party))
        print(
            f"[team_switch] {'✓' if ok else '✗'} 收尾：SET {cur_set[0] if cur_set else '?'} / 队 {cur_party}"
            f"（目标 SET {target_set} / 队 {target_party or '-'}）"
        )
        return None

    def _switch_party(self, context, target_party, cur_party, entry):
        """点左右箭头并**每次复查**；队号没变就放弃（几何未真机确认，绝不盲点连击）。"""
        for _attempt in range(TEAM_PARTY_COUNT + 1):
            if cur_party == target_party:
                return cur_party
            arrow = TEAM_PARTY_ARROWS[0 if (cur_party is None or target_party < cur_party) else 1]
            print(f"[team_switch]   队切换：点 {arrow}（当前 {cur_party} → 目标 {target_party}）")
            _click_box(context, arrow[0], arrow[1])
            time.sleep(0.9)
            _s, party_now, _p = read_team(ocr_all(context, _grab(context), entry))
            if party_now == cur_party:
                print(f"[team_switch]   ★点完队号没变（仍 {cur_party}）→ 队箭头几何可能不对，放弃队切换★")
                return cur_party
            cur_party = party_now
        return cur_party

# ---------------------------------------------------------------------------
# ★#105★ A 类「战前编队页」就地切 SET（队切换未标定 → 拒动）
# ---------------------------------------------------------------------------
def find_set_tabs(items):
    """从全屏 OCR 里抽 `SET N` 的**真实中心点**（720 空间）。

    ★#105 真机★ 固定步长/槽位表都不可靠：同一「三页签」布局在不同页面上 x 差 21px
    （幻想页 147/359/571，深渊EX 页 126/337/549）。页面自己的 OCR 框才是真源。

    返回 ``{n: (cx, cy)}``；抽不到返回空 dict（调用方退回 ``battle_set_tap_plan``）。
    """
    out = {}
    try:
        for text, box in items or ():
            m = _SET_RE.search((text or "").strip())
            if not m:
                continue
            n = int(m.group(1))
            if not (1 <= n <= 12):
                continue
            # Page.items()/OcrTask 给的框已经是 720 空间（read_team 同源），不再换算
            if len(box) < 4:
                continue
            out[n] = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
    except Exception:  # noqa: BLE001
        return {}
    return out


def battle_set_tap_plan(current: int, target: int):
    """A 类 SET 条一步计划（按实测圆点序列；已到目标 None）。"""
    if current == target:
        return None
    if not (1 <= target <= TEAM_BATTLE_SET_MAX):
        return None
    idx = target - 1
    tap_x = TEAM_BATTLE_SET_LABEL_X + TEAM_BATTLE_SET_STEP_PX * (idx + 1) - 20
    tap_x = max(TEAM_TAP_MIN_X, min(TEAM_TAP_MAX_X, tap_x))
    return tap_x, (-1 if target < current else 1)


def is_battle_team_page(items, hit_keys=()) -> bool:
    """A 类页判据（**双通道**）：OCR 通道 ∨ 模板通道；B 类锚点是否决票。

    判定顺序（顺序即语义）：

    1. **B 类否决先做**：屏上有 ``^切换$`` ⇒ B 类编辑器，**无论模板通道说什么都 False**
       （拿 A 类坐标点 B 类页 = 点到标题栏）。模板通道只加召回，不许翻结构性的否定判据；
    2. **OCR 通道**：有 ``自动续战``（A 类独有）⇒ True（既有行为，未改）；
    3. **模板通道**：``hit_keys`` 里任一 A 类模板命中 ⇒ True（``自动续战`` 读不到时的兜底）。

    ``hit_keys=()`` ⇒ 与改动前**逐项等价**（老调用方不受影响）。
    """
    texts = [t or "" for t, _b in items or []]
    if any(re.search(TEAM_PAGE_ANCHOR_B, x) for x in texts):
        return False
    if any(TEAM_PAGE_ANCHOR_A in x for x in texts):
        return True
    return any(key in TEAM_PAGE_KEYS for key in (hit_keys or ()))


# ---------------------------------------------------------------------------
# ★#105★ 模板通道：PNG 解码 + 全滑窗灰度 ZNCC（numpy，**不需要 PIL**）
# ---------------------------------------------------------------------------
#: 模板匹配的模板块缓存：``{绝对路径: (mtime_ns, size, ndarray)}``（每步都读盘太浪费）。
_TPL_CACHE: dict = {}


class TeamTemplateHits(NamedTuple):
    """模板通道的一次量测结果（全部模板都记，命中的进 ``hit_keys``）。"""

    #: ``{key: (score, x, y)}`` —— **所有**模板在各自 roi 内的最高分（过不过阈值都记，便于日志）。
    scores: dict
    #: 过了各自阈值的模板键（``scene.team_templates.PAGE_KEYS`` 里任一命中 = A 类页）。
    hit_keys: tuple
    #: ``set_selected`` 的命中 x 经槽位几何换出的 SET 号（None = 没命中 / 有歧义）。
    set_index: object
    #: 槽位几何命中时用的布局（``"tab3"`` / ``"barN"`` / None，写日志用）。
    set_layout: object
    #: ``set_selected`` 的命中框 ``[x, y, w, h]``（720 空间；给 ``read_team`` 的 set 元组用）。
    set_box: object
    #: 模板 / 配置的来源：``"scene"``（仓库态）或 ``"snapshot"``（安装态）。
    source: str
    #: 失败/降级原因（空 = 一切正常）。
    why: str = ""


def _np():
    """惰性导入 numpy（`maa_util` 也刻意不导入它：离线测试进程不该被它绑架）。"""
    try:
        import numpy as np  # noqa: PLC0415

        return np
    except Exception:  # noqa: BLE001
        return None


def team_image_dir():
    """找 ``resource/image`` 目录：仓库态 ``assets/resource/image``，安装态 ``<install>/resource/image``。

    ★为什么不用相对 cwd★：AgentServer 的工作目录由 framework 决定，本仓已有过「相对路径在安装态
    全部失效」的教训。这里按 ``__file__`` 往上找两个候选，找到即用，找不到返回 None
    （模板通道降级为「不可用」，OCR 通道照常）。
    """
    here = Path(__file__).resolve()
    for base in here.parents[1:3]:
        for rel in (("assets", "resource", "image"), ("resource", "image")):
            cand = base.joinpath(*rel)
            if cand.is_dir():
                return cand
    return None


def _decode_png(path: Path):
    """把 PNG 解成 ``HxWx3`` uint8（只支持 8bit / 非隔行 / RGB(2) 或 RGBA(6)）。

    ★为什么自己解★：安装态的便携 Python **只有 maafw + numpy**（没有 Pillow），而模板是 PNG。
    numpy 单独解不了 PNG，但 ``zlib`` 是标准库 —— 所以这里手写一个最小解码器（含 5 种行滤波）。
    ★正确性由谁保证★：``hooks_105`` / ``tools/test_team_templates.py`` 会拿 PIL 解码同一张 PNG
    与这里逐字节比对（``assert decode(png) == PIL(png)``）—— 解码器坏了当场红。
    """
    import struct
    import zlib

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    idat = bytearray()
    width = height = bit_depth = color_type = interlace = None
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        if pos + 12 + length > len(data):
            return None
        chunk_type = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6) or interlace not in (0, None):
        return None
    if not width or not height:
        return None
    raw = zlib.decompress(bytes(idat))
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    if len(raw) < height * (stride + 1):
        return None
    out = bytearray(height * stride)
    prev = bytes(stride)
    offset = 0
    for row in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if filter_type == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                upleft = prev[i - channels] if i >= channels else 0
                est = left + up - upleft
                da, db, dc = abs(est - left), abs(est - up), abs(est - upleft)
                pred = left if (da <= db and da <= dc) else (up if db <= dc else upleft)
                line[i] = (line[i] + pred) & 0xFF
        elif filter_type != 0:
            return None
        out[row * stride : (row + 1) * stride] = line
        prev = bytes(line)
    flat = _np().frombuffer(bytes(out), dtype=_np().uint8)
    np = _np()
    arr = flat.reshape(height, width, channels)
    return np.ascontiguousarray(arr[:, :, :3]) if channels == 4 else np.array(arr, copy=True)


def load_team_template(rel: str):
    """读一张模板 PNG → ``HxW`` float 灰度数组（带缓存）。失败返回 None。"""
    np = _np()
    if np is None:
        return None
    img_dir = team_image_dir()
    if img_dir is None:
        return None
    path = img_dir / rel
    if not path.is_file():
        return None
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    cached = _TPL_CACHE.get(str(path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    rgb = _decode_png(path)
    if rgb is None:
        return None
    gray = _to_gray(rgb)
    _TPL_CACHE[str(path)] = (stamp, gray)
    return gray


def _to_gray(rgb):
    """``HxWx3`` uint8/float → ``HxW`` float32 灰度（ITU-R 601-2，与 ``PIL.convert("L")`` 同系数）。"""
    np = _np()
    arr = np.asarray(rgb, dtype=np.float32)
    if arr.ndim == 2:
        return arr
    return arr[:, :, 0] * 0.299 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.114


def _resize_bilinear(arr, width: int, height: int):
    """numpy 双线性缩放（只作为「screencap 不是 720」的防御；正路是框架已经缩到 720）。"""
    np = _np()
    src_h, src_w = arr.shape[0], arr.shape[1]
    ys = (np.arange(height, dtype=np.float32) + 0.5) * (src_h / height) - 0.5
    xs = (np.arange(width, dtype=np.float32) + 0.5) * (src_w / width) - 0.5
    ys = np.clip(ys, 0, src_h - 1)
    xs = np.clip(xs, 0, src_w - 1)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.minimum(y0 + 1, src_h - 1)
    x1 = np.minimum(x0 + 1, src_w - 1)
    wy = (ys - y0)[:, None, None]
    wx = (xs - x0)[None, :, None]
    top = arr[y0][:, x0] * (1 - wx) + arr[y0][:, x1] * wx
    bottom = arr[y1][:, x0] * (1 - wx) + arr[y1][:, x1] * wx
    return top * (1 - wy) + bottom * wy


def to_gray_720(image):
    """把 screencap（MAA **BGR** ndarray / PIL **RGB**）归一到 **720x1280 灰度**；不合法返回 None。

    ★通道序★：MAA 原生 screencap 是 **BGR**（真机实证，见 ``auto_switch_impl.to_rgb_array``），
    PIL 入参按 RGB —— 这条**必须**分开处理：灰度权重 R 0.299 / B 0.114，青底白字的徽标上
    换错通道序会让灰度差到 ~26 级，ZNCC 直接掉出阈值（离线存档是 PIL 口径）。
    """
    np = _np()
    if np is None or image is None:
        return None
    try:
        if hasattr(image, "convert"):  # PIL.Image -> RGB
            arr = np.asarray(image.convert("RGB"))
        else:  # MAA screencap -> BGR，这里换成 RGB
            arr = np.asarray(image)
            if arr.ndim == 3 and arr.shape[2] >= 3:
                arr = np.ascontiguousarray(arr[:, :, 2::-1])
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        if arr.ndim != 3:
            return None
        if (arr.shape[1], arr.shape[0]) != (720, 1280):
            arr = _resize_bilinear(arr.astype(np.float32), 720, 1280)
        return _to_gray(arr)
    except Exception:  # noqa: BLE001
        return None


def _corr_valid(plane, kernel):
    """二维**互相关** ``mode="valid"``（FFT，纯 numpy）。与 ``hooks_102._corr`` 同一手法。"""
    np = _np()
    big_h, big_w = plane.shape
    h, w = kernel.shape
    if h > big_h or w > big_w:
        return None
    sh, sw = big_h + h - 1, big_w + w - 1
    full = np.fft.irfft2(
        np.fft.rfft2(plane, s=(sh, sw)) * np.fft.rfft2(kernel, s=(sh, sw)), s=(sh, sw)
    )
    return full[h - 1 : h - 1 + (big_h - h + 1), w - 1 : w - 1 + (big_w - w + 1)]


def _zncc_max(gray_720, template, roi):
    """灰度 ``TM_CCOEFF_NORMED`` 全滑窗，返回 ``(score, x, y)``（roi 内最高分，720 空间）。

    与 ``hooks_102.zncc_gray`` 同一公式（分子按通道求和 → 这里是单通道），所以离线存档
    （灰口径）与这里的分数可以逐项对比（容差 0.02）。
    """
    np = _np()
    if np is None:
        return None
    x0, y0, rw, rh = (int(v) for v in roi)
    th, tw = template.shape
    if rw < tw or rh < th:
        return None
    x0 = max(0, x0)
    y0 = max(0, y0)
    crop = np.asarray(gray_720[y0 : y0 + rh, x0 : x0 + rw], dtype=np.float64)
    if crop.shape[0] < th or crop.shape[1] < tw:
        return None
    tpl = np.asarray(template, dtype=np.float64)
    tz = tpl - tpl.mean()
    ones = np.ones((th, tw), dtype=np.float64)
    num = _corr_valid(crop, tz[::-1, ::-1])
    s1 = _corr_valid(crop, ones[::-1, ::-1])
    s2 = _corr_valid(crop * crop, ones[::-1, ::-1])
    if num is None or s1 is None or s2 is None:
        return None
    var = s2 - s1 * s1 / float(th * tw)
    den = np.sqrt(np.maximum(var, 1e-12) * float((tz * tz).sum()))
    scores = num / np.maximum(den, 1e-12)
    idx = int(np.argmax(scores))
    yy, xx = divmod(idx, scores.shape[1])
    return round(float(scores[yy, xx]), 4), int(x0 + xx), int(y0 + yy)


def detect_team_templates(image):
    """模板通道：在一帧上量全部 A 类模板 → :class:`TeamTemplateHits`；不可用时返回 None。

    ★失败一律返回 None（不是抛异常）★：模板通道是**第二通道**，它挂掉时 `read_team` /
    `is_battle_team_page` 必须退回 OCR 通道照常工作（绝不因为模板不可用就拒动）。
    """
    np = _np()
    if np is None:
        return None
    gray = to_gray_720(image)
    if gray is None:
        return None
    specs = team_template_specs()
    if not specs:
        return None
    scores: dict = {}
    hit_keys = []
    problems: list = []
    for key, rel, roi, threshold, _order_by, window in specs:
        tpl = load_team_template(rel)
        if tpl is None:
            # ★单张模板读不到不让整条通道熄火★：记下原因继续量其余的（安装态少一张图 =
            # 少一条召回证据，不是「模板通道不存在」）。
            problems.append(f"{key}:{rel} 读不到")
            continue
        got = _zncc_max(gray, tpl, roi)
        if got is None:
            problems.append(f"{key}:roi 比模板还小")
            continue
        score, x, y = got
        scores[key] = (score, x, y)
        if score >= float(threshold):
            hit_keys.append(key)
    if not scores:
        return None
    set_index = set_layout = set_box = None
    hit = scores.get("set_selected")
    if hit is not None and "set_selected" in hit_keys:
        mapped = set_index_from_pill(hit[1])
        if mapped is not None:
            set_index, set_layout, _res = mapped
            _key, _rel, _roi, _thr, _ob, window = next(
                s for s in specs if s[0] == "set_selected"
            )
            set_box = [hit[1], hit[2], int(window[2]), int(window[3])]
    return TeamTemplateHits(
        scores=scores,
        hit_keys=tuple(hit_keys),
        set_index=set_index,
        set_layout=set_layout,
        set_box=set_box,
        source=TPL_SOURCE,
        why="; ".join(problems),
    )


def guided_ocr_crops(state=None, hits=None):
    """模板定位后的**局部 OCR** 窗口：只在模板证明「那一行真的在」时才裁（防误绑数字）。

    返回 ``((x, y, w, h), …)``：

    * 队号那一块（:data:`TEAM_PARTY_NO_CROP`）：``party`` 还读不到 **且** ``party_label`` 命中；
    * 战力那一行（:data:`TEAM_POWER_ROW`）：``power`` 还读不到 **且** ``power_label`` 命中。

    ★为什么必须先有模板命中★：局部 OCR 会返回一块区域里的**任意**数字，没有模板证明「这里是
    Party 行」，那个数字可能是任何东西（等级 / 数量）→ 绑成队号就是静默错。
    """
    if hits is None:
        return ()
    keys = tuple(getattr(hits, "hit_keys", ()) or ())
    party, power = (state[1], state[2]) if state is not None else (None, None)
    crops = []
    if party is None and "party_label" in keys:
        crops.append(tuple(TEAM_PARTY_NO_CROP))
    if power is None and "power_label" in keys:
        crops.append(tuple(TEAM_POWER_ROW))
    return tuple(crops)


def _crop_image(image, box):
    """裁一块 ``[x, y, w, h]``（numpy BGR / PIL 都支持）；裁不了返回 None。"""
    x, y, w, h = (int(v) for v in box)
    if image is None:
        return None
    try:
        if hasattr(image, "crop"):  # PIL.Image
            return image.crop((x, y, x + w, y + h))
        arr = image
        return arr[y : y + h, x : x + w]
    except Exception:  # noqa: BLE001
        return None


def ocr_team_state(context, image, entry: str = "OcrTask"):
    """一次读全 A 类页状态：全屏 OCR → 模板通道 →（按需）模板引导的局部 OCR → ``read_team``。

    返回 ``(state, items, hits)``；``state`` 就是 :func:`read_team` 的三元组。
    ★提示词面（供 assert/日志用）★：``items`` 是**合并后**的 OCR 项（局部项已换算回 720 坐标），
    所以 ``read_team(items, hits)`` 与这里返回的 ``state`` 必然一致 —— 守卫与
    ``tools/test_team_templates.py`` 都按这个等式对账。
    """
    items = list(ocr_all(context, image, entry))
    hits = detect_team_templates(image)
    state = read_team(items, hits)
    crops = guided_ocr_crops(state, hits)
    if crops:
        extra = []
        for box in crops:
            crop = _crop_image(image, box)
            if crop is None:
                continue
            for text, cbox in ocr_all(context, crop, entry):
                if not cbox or len(cbox) < 4:
                    continue
                extra.append(
                    (text, [int(cbox[0]) + box[0], int(cbox[1]) + box[1], cbox[2], cbox[3]])
                )
        if extra:
            items = items + extra
            state = read_team(items, hits)
    return state, items, hits



# ---------------------------------------------------------------------------
# ★#124★ 动作层的生产 IO 缝（模块级函数 ⇒ 守卫/单测直接替换名字即可计数/打桩）
# ---------------------------------------------------------------------------
#: 横向滑动的内联节点名：程序化 ``pipeline_override`` 注入，**不依赖任何 json 节点存在**
#: （与 ``wuchong_impl.swipe`` / ``click_box`` 同一手法）。
TEAM_PARTY_SWIPE_NODE = "TeamPartySwipe"


def swipe_party_row(context, x_from, x_to, y, ms):
    """执行一次横向滑动（720 空间两元素定点）。

    ★不用 ``controller.post_swipe``★：与 ``click_box`` 同一条教训（部分原生库未导出 →
    进程崩），改走 ``context.run_action(node, pipeline_override=...)``，版本无关。
    ★begin/end 是两元素定点★（不是四元素区域 —— 四元素会在矩形内随机取点，手势就歪了，
    ``hooks_58`` 的 AST 扫描也在盯这条）。
    返回 ``False`` 表示这次滑动**没有真的划出去**（无 context / 框架报错），绝不假装划过。
    """
    if context is None:
        print("[team_switch_battle] 没有 context：无法执行横向滑动（不假装划过）")
        return False
    override = {
        TEAM_PARTY_SWIPE_NODE: {
            "action": {
                "type": "Swipe",
                "param": {
                    "begin": [int(x_from), int(y)],
                    "end": [int(x_to), int(y)],
                    "duration": int(ms),
                },
            }
        }
    }
    try:
        context.run_action(TEAM_PARTY_SWIPE_NODE, pipeline_override=override)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[team_switch_battle] 横向滑动失败 {x_from}->{x_to} @y={y}：{type(exc).__name__}: {exc}")
        return False


def read_battle_team(context, entry: str = "OcrTask"):
    """生产读数缝（``switch_party`` 的 ``read_hook``）：当帧 A 类编队页的 ``(set, party, power)``。

    ★与动作主循环同一把尺★：走 :func:`ocr_team_state`（全屏 OCR ∨ 模板通道 + 模板引导的
    局部 OCR），所以「主循环读到的」与「切队复核读到的」不会各用一套解析。
    """
    state, _items, _hits = ocr_team_state(context, _grab(context), entry)
    return state


class TeamSwitchBattleAction(CustomAction):
    """``custom_action="team_switch_battle"``：A 类战前编队页就地切 **SET** 与 **Party**。

    参数：``set`` / ``party`` / ``max_steps`` / ``ocr_entry``。

    * ``set``：目标 SET（必填，1..``TEAM_BATTLE_SET_MAX``）；
    * ``party``：目标 Party（可选，1..``TEAM_PARTY_COUNT``）。★#124 起是**动作目标**★：
      在 A 类页上走 :func:`switch_party`（横向滑动 + 三重校验），不再只是校验值；
      **不给** ⇒ 与旧行为一致，只切 SET；**显式给 0 / 越界 ⇒ 拒动**（0 不是队号，真机 1..10）；
    * ``max_steps`` / ``ocr_entry``：与旧行为一致。

    ★为什么保留「拒动」这个词★：旧语义里它表示「队不符 → 不动」。接线后**不动的那半照旧**——
    读不到编队（SET/Party 读不全）或不在 A 类页时**绝不按 A 类交互盲操作**，一行日志说清原因。
    ★成功判据只有一个★：``switch_party`` 返回 True。它内部的三重校验（SET 不变 ∧ Party 命中 ∧
    战力变化）不过 ⇒ 本动作绝不打印成功（不把「读到了 Party」当换队成功）。
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        target_set = int(param.get("set") or 0)
        raw_party = param.get("party")
        target_party = int(raw_party or 0)
        # ★#124 真机后续③★ 不给 party = 只切 SET（旧语义）；显式给 0 = 越界（0 不是队号）⇒ 拒动。
        party_given = raw_party is not None and str(raw_party).strip() != ""
        max_steps = int(param.get("max_steps") or TEAM_MAX_STEPS)
        entry = str(param.get("ocr_entry") or "OcrTask")
        if not (1 <= target_set <= TEAM_BATTLE_SET_MAX):
            print(f"[team_switch_battle] 目标 SET {target_set} 越界（1..{TEAM_BATTLE_SET_MAX}）→ 不动")
            return None
        if party_given and not (1 <= target_party <= TEAM_PARTY_COUNT):
            print(
                f"[team_switch_battle] 目标队 {target_party} 不存在（真机轮播 1..{TEAM_PARTY_COUNT}）"
                f"→ 不动"
            )
            return None

        cur_set = cur_party = None
        for step in range(1, max_steps + 1):
            img = _grab(context)
            # ★#105★ 双通道：OCR 通道 ∨ 模板通道（任一模板命中即算 A 类页）。
            state, items, hits = ocr_team_state(context, img, entry)
            if not is_battle_team_page(items, getattr(hits, "hit_keys", ())):
                print(f"[team_switch_battle] 第 {step} 步：这不是战前编队页（无「自动续战」或出现了「切换」）→ 停手")
                return None
            cur_set, cur_party, power = state
            if cur_set is None:
                print(f"[team_switch_battle] 第 {step} 步：读不到 SET 标签 → 停手")
                return None
            set_no = cur_set[0]
            print(
                f"[team_switch_battle] 第 {step} 步：SET {set_no} / 队 {cur_party} / 战力 {power}"
                f"（目标 SET {target_set} / 队 {target_party or '-'}；"
                f"模板通道命中={list(getattr(hits, 'hit_keys', ()) or ()) or '无'}）"
            )
            if set_no == target_set:
                break
            plan = battle_set_tap_plan(set_no, target_set)
            if plan is None:
                print("[team_switch_battle] 算不出下一步 → 停手")
                return None
            tap_x, _d = plan
            print(f"[team_switch_battle]   → 点 SET 条第 {target_set} 个圆点 x={tap_x}, y={TEAM_BATTLE_SET_ROW_Y}")
            _click_box(context, tap_x, TEAM_BATTLE_SET_ROW_Y)
            time.sleep(0.9)
        else:
            print(f"[team_switch_battle] ★步数用尽（{max_steps}）仍未到 SET {target_set} → 放弃★")
            return None

        ok_set = bool(cur_set and cur_set[0] == target_set)
        if not ok_set:
            print(f"[team_switch_battle] ✗ 收尾：SET {cur_set[0] if cur_set else '?'}（目标 {target_set}）")
            return None
        if not target_party:
            print(f"[team_switch_battle] ✓ 收尾：SET {target_set} / 队 {cur_party}")
            return None
        return self._switch_party(context, target_set, target_party, entry)

    def _switch_party(self, context, target_set, target_party, entry):
        """A 类页上就地切 Party（`switch_party`）；读不到编队 / 不在 A 类页 ⇒ 拒动。

        ★为什么调之前要**重新读一帧**★：SET 闭环的最后一次读发生在点完圆点之后，此刻画面可能
        已经变了（例如战斗倒计时弹出）。切 Party 的前提是「**现在**还在 A 类战前编队页且编队可读」，
        拿旧读数当授权就是盲操作 —— 旧 #105 的拒动语义保留下来的正是这半。
        """
        img = _grab(context)
        state, items, hits = ocr_team_state(context, img, entry)
        on_a_page = is_battle_team_page(items, getattr(hits, "hit_keys", ()))
        cur_set, cur_party, power = state
        if not on_a_page:
            print(
                f"[team_switch_battle] SET 已到 {target_set}；但**当帧不是 A 类战前编队页** "
                f"→ **拒动**（读不到编队页就不动，绝不按 A 类交互盲操作）"
            )
            return None
        if cur_set is None or cur_party is None:
            print(
                f"[team_switch_battle] SET 已到 {target_set}；但**读不到编队**"
                f"（SET={cur_set[0] if cur_set else None} / Party={cur_party}）→ **拒动**"
                f"（读不到就不动，绝不猜队号盲滑）"
            )
            return None

        print(
            f"[team_switch_battle] SET {cur_set[0]} 已到位；队 {cur_party} ≠ 目标 {target_party} "
            f"→ 走 switch_party（横向滑动 + 三重校验；战力 {power}）"
        )
        ok = switch_party(
            target_party,
            read_hook=lambda: read_battle_team(context, entry),
            swipe_hook=lambda x_from, x_to, y, ms: swipe_party_row(context, x_from, x_to, y, ms),
            # ★不给 tap_hook★：真机证据（394eb66）表明切 Party 只需要横向滑动；
            #   轻点 SET 条对切队无效，默认绝不盲点。
        )
        if not ok:
            print(
                f"[team_switch_battle] ✗ 收尾：SET {target_set} 已到，但队 {target_party} "
                f"**没切成功**（三重校验未全过）→ 不宣称成功"
            )
            return None
        print(
            f"[team_switch_battle] ✓ 收尾：SET {target_set} / 队 {target_party}"
            f"（switch_party 三重校验：SET 不变 ∧ Party 命中 ∧ 战力变化）"
        )
        return None
