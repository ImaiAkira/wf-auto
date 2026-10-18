# -*- coding: utf-8 -*-
"""编队（SET / 队）切换的数据真源（#91）。

★真机标定（2026-10-17，A = 127.0.0.1:16384，720x1280）★
- 编队页在「角色 → 队伍编成」；顶部一排圆点是 **SET 选择器**，选中的那个圆点上方浮着
  `SET N` 标签（标签的 x 随选中项移动：SET 1 → box x=30，SET 10 → x=525，SET 11 → x=578）。
- 相邻圆点中心距 **≈55px**（由 10 次「点一次读一次」标定得出：54, 110, 165, 220, …）。
- **不是固定坐标**：点在标签左/右邻的圆点上 = 上一个/下一个 SET，但整排会随时滚动，
  所以切换动作必须「读 → 点 → 再读」闭环，绝不按固定坐标一把点。
- 队（Party）在 SET 之内，标签形如 `5 Party E`（第 5 队）；B 类编辑器页的**队切换箭头**位置
  仍未真机确认，动作里用 OCR 校验兜底，确认不了就带原因失败（绝不盲点）。
- A 类「战前编队页」的队轮播**已真机标定**（#124，2026-10-18）：**横向滑动**切 Party，
  左滑 +1 / 右滑 −1，SET 不变 —— 几何与 ``switch_party`` 见文件末尾的 #124 段。

⚠️ 改这里的数值必须附新的真机标定（截图/日志），否则守卫会红。

★★分辨率与归属（2026-10-17 22:2x 只读核查）★★
- 本文件的坐标全部是 **720x1280 基准**（MAA 侧帧空间）。**不要假设设备原生分辨率**：
  B（16448）今晚先后被观察到 **1080x1920**（21:12–21:38 的原始帧）与 **720x1280**（22:26 起），
  分辨率在 21:38 之后变过（改过或换实例）。动作里一律用 MAA 帧坐标，禁止用原始像素。
- A（16384）当前就在 720x1280，`SET 1` + `Party E`（第5队）+ 战力 13,116，与「通解队」相符。
- **B 的编队从未从屏幕确认**（它停主城，读不到 SET/Party），所以「B 用 Set1第1队」仍只是运维口径。
"""

from __future__ import annotations

#: 顶部 SET 圆点行的 y（720x1280 坐标）。
TEAM_SET_ROW_Y = 30

#: 相邻 SET 圆点的中心间距（px，720 宽基准）。
TEAM_SET_STEP_PX = 55

#: SET 总数上限（真机见过 SET 11，留余量）。
TEAM_MAX_SETS = 11

#: 每个 SET 内的队数上限：★真机 **10 队**★（2026-10-18，A = 127.0.0.1:16384，720x1280 实测）。
#:
#: 证据（#124 评论，**不要重测**）：Party **1..10，环形轮播**（左滑 10→1、右滑 1→10，无「滑不动」
#: 边界；两方向各走完整一圈都回到原点）；边界画面无异常（SET 全程 1、战力 10 队各不相同
#: 10452…11588、两侧箭头在、底部 10 个圆点）。
#: 旧值 6 是 #91 时期「只见过 Party E」把**下界当上界**，会让 7..10 被判越界（真缺陷，#124 修）。
TEAM_PARTY_COUNT = 10

#: SET 标签的 OCR 判据 / 队伍标签判据 / 战力图注。
TEAM_SET_RE = r"SET\s*(\d+)"
#: ★队标签判据（#105 修正）★：队号是**可选**的。
#: 原式 ``(\d+)\s*Party\s*([A-Z])`` 要求 ``Party`` 前必须有数字 —— 真机B 深渊EX 战前编队页
#: 的队号大字 ``1`` **被 OCR 吞掉**，只给 ``Party A``，于是 ``party=None``（编队页判定成立却
#: 读不出队，是本票最直接的坏点）。现在 ``1 Party A`` / ``Party A`` 两种都认：
#: 有数字用数字；只有字母名时按 :func:`party_ordinal` 兜底（见那里的证据）。
TEAM_PARTY_RE = r"(?:(\d+)\s*)?Party\s*([A-Z])"
TEAM_POWER_RE = r"战力"

#: 队名的字母表：真机 ``1 Party A`` / ``5 Party E`` / ``10 Party J`` —— **字母序号 == 队号**。
#: ★这是 2/2 样本的归纳，不是官方文档★：证据只有 ``1 Party A``（33_wuchong_team / 深渊EX）
#: 与 ``5 Party E``（side_team_page / lord_team_page），两条都满足 A→1、E→5；
#: 2026-10-18 的 1..10 环形标定把上界推到 **J = 第 10 队**（A 实测 10 队）。
#: 因此它只在**队号数字读不到**时兜底（:func:`party_ordinal`），且被
#: ``hooks_105`` 的 ``team-battle-read-team-parse-only`` 用真帧钉住；若哪天真机证伪（出现
#: ``3 Party A`` 这种），那条守卫会当场红。
#: ★长度必须 == :data:`TEAM_PARTY_COUNT`★（现在 10 == 10）：字母表短了，OCR 吞掉队号大字时
#: ``Party I`` / ``Party J`` 会退化成「读不到 Party」（= 编队页判定成立却读不出队）。
#: ``hooks_124`` 的 ``party-alphabet-count`` 与 ``hooks_105`` 的投影守卫盯的就是这条。
TEAM_PARTY_LETTERS = "ABCDEFGHIJ"


def party_ordinal(letter):
    """``"A"`` → 1 … ``"J"`` → 10；不在 :data:`TEAM_PARTY_LETTERS` 里返回 ``None``。"""
    key = (letter or "").strip().upper()
    if len(key) != 1 or key not in TEAM_PARTY_LETTERS:
        return None
    return TEAM_PARTY_LETTERS.index(key) + 1

#: 一次切换允许的最大点击次数（读→点→再读的轮数；超过就带原因失败）。
TEAM_MAX_STEPS = 16

#: 点击坐标的安全边界（避开状态栏与两侧边缘）。
TEAM_TAP_MIN_X = 12
TEAM_TAP_MAX_X = 708

#: 选项值：`不切换` + Set1第1队 …（值域由 :func:`option_values` 生成，界面与守卫共用同一份）。
TEAM_OPTION_NONE = "不切换"

#: **GUI「切换编队」选项只列前 6 队**（scene-only；不是真机队数）。
#:
#: 为什么不直接用 :data:`TEAM_PARTY_COUNT`：``assets/interface.json`` 的「切换编队」值域就是
#: ``Set1第1队 … Set1第6队``，``hooks_91`` 的 ``team-wiring`` 逐项比对它。真机有 10 队，但**界面
#: 值域本票没扩**（值域在 interface.json，改动不在本 lane）—— 把两者绑在一起会让选项表与
#: interface.json 当场脱钩（hooks_91 红）。要扩界面，另开票同时改 interface.json + 这个常量。
TEAM_OPTION_PARTIES = 6
#: 运维指定（A 通解队 / B 第一队）—— 任务前置检查用；不是"默认值"，只是记录事实。
TEAM_PRESET_A = (1, 5)
TEAM_PRESET_B = (1, 1)


def option_values(sets: int = 1, parties: int = TEAM_OPTION_PARTIES) -> list:
    """生成「切换编队」选项的值域（只列前 `sets` 个 SET；默认只列 SET 1，够运维用且短）。

    ``parties`` 缺省是 :data:`TEAM_OPTION_PARTIES`（GUI 值域 6），**不是**真机队数
    :data:`TEAM_PARTY_COUNT`（10）—— 见那个常量的注释。
    """
    values = [TEAM_OPTION_NONE]
    for s in range(1, max(1, min(sets, TEAM_MAX_SETS)) + 1):
        for p in range(1, max(1, min(parties, TEAM_PARTY_COUNT)) + 1):
            values.append(f"Set{s}第{p}队")
    return values


def parse_option(text: str):
    """把选项文案解析成 ``(set, party)``；``不切换``/空 → ``None``；非法 → ``ValueError``。"""
    import re as _re

    raw = (text or "").strip()
    if not raw or raw == TEAM_OPTION_NONE:
        return None
    m = _re.fullmatch(r"Set\s*(\d+)\s*第\s*(\d+)\s*队", raw)
    if not m:
        raise ValueError(f"切换编队选项无法解析：{raw!r}")
    s, p = int(m.group(1)), int(m.group(2))
    if not (1 <= s <= TEAM_MAX_SETS):
        raise ValueError(f"SET 越界：{s}（1..{TEAM_MAX_SETS}）")
    if not (1 <= p <= TEAM_PARTY_COUNT):
        raise ValueError(f"队号越界：{p}（1..{TEAM_PARTY_COUNT}）")
    return s, p


def set_tap_plan(current: int, target: int, pill_box):
    """纯函数：算出「往目标 SET 走一步」该点哪里。

    ``pill_box`` 是 `SET N` 标签的 OCR 框 ``[x, y, w, h]``。返回 ``(tap_x, direction)``：
    ``direction = -1`` 表示往前一个 SET，``+1`` 表示往后一个；已到目标返回 ``None``。

    ★为什么闭环★：真机实测圆点行会随选中项滚动，固定坐标点几次就会偏一位
    （标定帧里 x=109 读到 SET 1、x=178 读到 SET 3），所以只能按标签位置算邻居。
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

# ===========================================================================
# ★#105★ A 类「战前编队页」几何（与上面的 B 类编辑器几何**分开**，绝不混用）
# ===========================================================================
#: A 类顶部 SET 条的 y（720x1280；帧 `tools/frames/33_wuchong_team.png` 实测）。
TEAM_BATTLE_SET_ROW_Y = 466
#: A 类相邻 SET 圆点中心间距（实测 49：164,213,262,311,360,409,457,506,555,604,653,698）。
TEAM_BATTLE_SET_STEP_PX = 49
#: A 类 SET 档数上限（实测 12 个圆点）。
TEAM_BATTLE_SET_MAX = 12
#: A 类 `SET N` 标签的 x（条最左端）；圆点从它右边开始。
TEAM_BATTLE_SET_LABEL_X = 84
#: 页面判据（互斥）：A 类独有 `自动续战`；B 类独有 `^切换$`。
TEAM_PAGE_ANCHOR_A = "自动续战"
TEAM_PAGE_ANCHOR_B = "^切换$"


def battle_set_tap_plan(current: int, target: int, label_box=None):
    """A 类 SET 条的一步点击计划：按**实测圆点序列**算，不依赖标签框（A 类没有飘移问题）。

    返回 ``(tap_x, direction)``；已到目标返回 None。
    """
    if current == target:
        return None
    direction = -1 if target < current else 1
    idx = (target - 1) if direction > 0 else (target - 1)
    tap_x = TEAM_BATTLE_SET_LABEL_X + TEAM_BATTLE_SET_STEP_PX * (idx + 1) - 20
    tap_x = max(TEAM_TAP_MIN_X, min(TEAM_TAP_MAX_X, tap_x))
    return tap_x, direction


def template_page_hit(hit_keys=()) -> bool:
    """模板通道的页判据：**任一** A 类模板命中即算（见 ``scene.team_templates.PAGE_KEYS``）。

    ``hit_keys`` = 过了各自阈值的模板键集合（由执行侧量出来，``scene`` 只做判断）。
    这里刻意不接受图像：``scene`` 是配置真源，不导入 numpy / PIL、不跑匹配。
    """
    from .team_templates import PAGE_KEYS  # noqa: PLC0415 —— 循环导入防护（team_templates 不导入本模块）

    return any(key in PAGE_KEYS for key in (hit_keys or ()))


def is_battle_team_page(items, hit_keys=()):
    """A 类页判据（**双通道**）：OCR 通道 ∨ 模板通道；B 类锚点是否决票。

    判定顺序（顺序本身就是语义，别改）：

    1. **B 类否决先做**：屏上有 ``^切换$`` ⇒ 这是 B 类编辑器，**无论模板通道说什么都 False**
       （拿 A 类坐标点 B 类页 = 点到标题栏，#105 的真机教训）。模板通道只增加召回，
       不允许翻掉结构性的否定判据。
    2. **OCR 通道**：有 ``自动续战``（A 类独有）⇒ True。这是既有行为，未改。
    3. **模板通道**：``hit_keys`` 里任一 A 类模板命中 ⇒ True。用于「OCR 读不到那四个字」的帧
       （``自动续战`` 在真机有 ``挑战`` 那种两态读法，也可能整段漏读）。
    """
    import re as _r

    texts = [t or "" for t, _b in items or []]
    if any(_r.search(TEAM_PAGE_ANCHOR_B, t) for t in texts):
        return False
    if any(TEAM_PAGE_ANCHOR_A in t for t in texts):
        return True
    return template_page_hit(hit_keys)


# ===========================================================================
# ★#124★ A 类战前编队页的 **Party 轮播**（横向滑动）—— 真机标定，纯搬家入库
# ===========================================================================
# ★真机证据（394eb66，A = 127.0.0.1:16384，720x1280，受控实验）★
# - **左滑（手指 600→200）= Party +1**、**右滑（手指 200→600）= Party −1**，逐步精确可逆
#   （左 4 + 右 4 回到原点）；端点 x 固定，y 取当帧 `SET N` 框中心（**不写死行高**）。
# - **SET 不变** —— 那一行是队伍轮播，不是 SET 页签（点它 / `SET编辑` / `推荐编成` 都切不动 SET）。
# - **战力随 Party 变** ⇒ 可作「换队真的生效」的独立证据（三重校验的第三票）。
# - 双向真机验收（4→6→4）与「读不到编队就不动」的拒绝路径都已在 A 上跑过；
#   证据与复跑命令见 #124 的 resolution 评论（`tools/probe_team_carousel.py --target N`）。
#
# ★2026-10-18 追加标定（A，环形复核；结论已在 #124 评论，**不要重测**）★
# - Party **1..10，环形轮播**：左滑 10→1、右滑 1→10，**没有「滑不动」的边界**；两方向各走
#   完整一圈都回到原点。边界画面无异常：SET 全程 1、战力 10 队各不相同（10452…11588）、
#   两侧箭头在、底部 10 个圆点。
# - 1..10 内最大 ``|Δ| = 9 ≤ TEAM_PARTY_SWIPE_MAX(12)`` ⇒ **环形不改变算法**（无需按环取模；
#   三重校验 2→10(左8) / 10→1(右9) / 1→4(左3) 全过）。
# - ★越界目标**一步不滑**就失败★：先判「目标是否存在（1..TEAM_PARTY_COUNT）」，再判「要滑几步
#   （``|Δ|`` 上限）」。真机缺陷是 `switch_party(11)` 从 Party 10 起滑了 11 次才失败、还把轮播
#   留在 Party 1（副作用）。**绝不默认夹紧**：目标 11 夹成 10 会让调用方以为切到了 11
#   （静默错队比失败更糟）；要夹紧必须调用方显式 ``clamp=True``，且必须打印夹紧结果。
#   （行为实现在 ``agent/team_impl.switch_party``；``hooks_124`` 的 ``party-target-bounds`` 把守。）
#
# ⚠️ 这 6 个值**逐字**来自真机标定；agent 侧保留同名逐字快照，`hooks_124` 的
#   `party-constants-source-of-truth` 钉住「快照 == 真源」，任何一侧改动都红。

#: 左滑端点 ``(手指起点 x, 终点 x)`` —— Party +1（手指右→左）。
TEAM_PARTY_SWIPE_LEFT = (600, 200)
#: 右滑端点 ``(手指起点 x, 终点 x)`` —— Party −1（手指左→右）。
TEAM_PARTY_SWIPE_RIGHT = (200, 600)
#: 单次滑动时长（ms）：与入库探针 ``tools/probe_team_carousel.py`` 的 450ms 同口径。
TEAM_PARTY_SWIPE_MS = 450
#: 每一步之后的稳定间隔（秒）：探针实测每步 1.6s 后读数稳定（SET 条是动画轮播，读早了会读旧值）。
TEAM_PARTY_STEP_SLEEP = 1.6
#: ``|Δ|`` 上限：**超过就一步也不滑**，直接带量失败（有界，绝不无限滑）。
TEAM_PARTY_SWIPE_MAX = 12
#: 失败重试次数上限（总尝试次数 = 1 + TEAM_PARTY_RETRIES）。
TEAM_PARTY_RETRIES = 1
