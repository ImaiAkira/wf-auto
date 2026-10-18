# -*- coding: utf-8 -*-
"""编队页 / 房间页「自动」按钮 —— **场景无关**的定位数据（#56 二批：自动的切换移到战斗外）。

★为什么单独一份、且是场景无关★
----------------------------
运维裁决②：「自动的切换从『战斗内』挪到『战斗外』……**不得假定固定坐标**：必须**定位**到
那个自动按钮（模板/图片识别优先，OCR 辅助），读它**开/关**的状态，再按其**识别框中心**点击。
**这条要覆盖所有模式的编队页，不能只做五重。**」

真机实测（`tools/frames/lord_team_page.png` 领主战编队页、`wc_live/001_room.png` 共斗房、
`wc_live/001_pre_WuchongTeamAutoSet.png` 五重编队页）：「自动」这个东西在**不同页面位置不同**——
  · 编队页（领主战 / 深渊EX / 五重）：标签在**左下** `720 (142,1062)`，开关在其正下方；
  · 共斗房间页（多人）：标签在**右上** `720 (630,102)`，开关同在其正下方；
  · 战斗暂停屏：`720 (148,1086)`（本批**不再使用**——战斗内不再切自动）。
所以**绝不写死坐标**：先定位标签框（模板优先 / OCR 兜底），再由标签框推出**开关探针**与
**点击点**。两处的相对几何一致（标签在上、开关在正下方 ≈ +41..+70px），故同一组偏移即可覆盖。

★锚定★：标签文本一律用**整串**正则（`^自动$`），绝不裸「自动」——否则会误命中「**自动续战**」
（真机实证：`WuchongResume` 的裸「续战」把编队页的「自动续战」点掉了）。

★模板★：`auto/switch_label.png` 裁自仓库内真机帧 `tools/frames/lord_team_page.png`
（720 空间 `(142,1062,43,26)`，纯标签、**与开关状态无关**）。离线 ZNCC 交叉验证：
  · 五重编队页 0.997@(142,1062) / 领主战编队页 1.000@(142,1062) / 深渊EX 编队页 0.997@(142,1062)；
  · 同排兄弟控件「**自动续战**」（标签在 x=17..96）实测 **0.8964@(17,1062)** —— ★#108 更正★：
    本文件原先写的 0.470 **是尺度不一致**（模板被放大 5%）条件下的分数，**不是真机分数**
    （见 `docs/research/recognition-ocr-vs-template.md` §5.2 第三步）；真机分数 0.8964 **高于**
    阈值 0.75，所以「阈值 0.75 能挡住它」这句话是错的，别再用它当安全感。
  · 共斗房间页 0.811@(630,102)（历史上曾命中；★#108 起 roi 只框编队页那一栏 → 房间页改走 OCR
    兜底，见 :data:`AUTO_LABEL_ROI` 的说明）。

★阈值救不了这条（#108 的机制根因）★：`TemplateMatch.threshold` 是**入闸门**（"这个位置算不算
命中"），**不是"取最高分"**；多结果时选哪个由 `order_by` + `index` 决定 —— **默认 `Horizontal`
+ `0` = 最左的那一个**。真「自动」1.0000@x=142、假「自动续战」0.8964@x=17 **都过 0.75** ⇒
默认语义下**必选 x=17**（`[17,1062,43,26]` 那次误点，机制上就是这么发生的；不需要把阈值调到
0.90 去解释，也**不该**只靠调阈值 —— 见 :data:`AUTO_TEMPLATE_THRESHOLD` 的注释）。
⇒ 现在是**三重防线**：:data:`AUTO_LABEL_ROI` 把兄弟那一栏排除出候选池（**主要防线**，让候选唯一）
+ :data:`AUTO_ORDER_BY` 显式要「最像」而不是吃默认「最左」（**语义防线**）+ 模板仍须经 OCR 校验
（**复核防线**：(a) 命中处未被其它开关标签（OCR 里含「续战」/「自动」）覆盖，(b) 与 OCR 整串锚定
`^自动$` 不矛盾；否则一律退回 OCR，见 ``auto_switch_impl.locate_switch_label``）。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# ① 标签定位（模板优先 / OCR 兜底）
# ---------------------------------------------------------------------------
#: 「自动」按钮的标签文本 + 用于 OCR 的**整串锚定**正则（排除「自动续战」「自动战斗」等）。
AUTO_LABEL = "自动"
AUTO_LABEL_PATTERNS: tuple[str, ...] = (r"^自动$",)
#: 「自动」标签裁片（仓库资源树内；自证 + 跨帧见模块 docstring）。
AUTO_LABEL_TEMPLATES: tuple[str, ...] = ("auto/switch_label.png",)
#: 模板**入闸门**阈值（"这个位置算不算命中"，**不是**"取最高分"；见 :data:`AUTO_ORDER_BY`）。
#: 真机命中 0.811~1.000（编队页 1.000）。
#: ★#108★ 这个数**故意保持 0.75 不动**，两个理由：
#:   (a) 它**挡不住**兄弟控件 ——「自动续战」实测 0.8964 ≥ 0.75，要挡得抬到 0.90 以上；但那样
#:       就把阈值变成了"替 roi 擦屁股"的手段，而且 0.90 离真机最低命中 0.811 只剩 0.09 余量
#:       （房间页/换皮随时掉出去）；
#:   (b) 它与 ``agent/auto_switch_impl._AUTO_TEMPLATE_THRESHOLD_SNAPSHOT`` 是**逐项 pin** 的一对
#:       （``hooks_auto_outside.auto-outside-snapshot-pinned``），单方面改会红 —— 阈值真要动，
#:       得连 agent 快照一起动，那是另一张票。
#: ⇒ 真正的防线是 :data:`AUTO_LABEL_ROI`（让候选唯一）+ :data:`AUTO_ORDER_BY`（选最像），阈值只
#:   保留它的本义：过滤低分噪声。
AUTO_TEMPLATE_THRESHOLD = 0.75
#: 承载模板的 pipeline 节点名（自定义识别经 ``context.run_recognition`` 复用；在 common.json）。
AUTO_TEMPLATE_NODE = "AutoSwitchLabel"

#: 模板的搜索范围 = **只框「自动」那一栏**（720 空间，``[x, y, w, h]``）。★#108★
#:
#: ★为什么必须写★：`roi` 缺省是全屏（协议默认 ``[0,0,0,0]``），而全屏 = 把**同排兄弟控件**
#: 「自动续战」也放进候选池；配合默认 ``order_by: Horizontal`` + ``index: 0`` = **取最左**，
#: 结果是**必选错**（真 1.0000@x=142 / 假 0.8964@x=17，两张已入库真机帧实测）。
#:
#: 数值怎么来的（坐标系：**720x1280 基准空间**；两张源帧都是 **1080x1920 原图**，
#: 按 ``scene.pixels`` 口径（÷1.5 = LANCZOS 下采样到 720，与模板同一口径）换算后测得）：
#:
#:   · 正例窗口：(142, 1062, 43, 26) —— ``tools/frames/lord_team_page.png`` 与
#:     ``tools/frames/side_team_page.png`` 上都是 **1.0000**；五重编队页 0.997 / 深渊EX 0.997
#:     （同一位置，见模块 docstring）⇒ 位置稳定，不是偶然。
#:   · 滑窗要能**跑到** (142,1062)，roi 就必须**完整包含**该窗口 ⇒ 左 ≤142、上 ≤1062、
#:     右 ≥142+43=185、下 ≥1062+26=1088。取 (100,1030,130,90) 后四边余量
#:     **左 42 / 右 45 / 上 32 / 下 32 px**（真机 OCR 框漂 ≤3px，余量足够吃布局微移）。
#:   · 反例「自动续战」标签占 **x≈17..97**（真机 OCR 框 ``[18,1062,79,24]``），其最佳对齐窗口
#:     (17,1062,43,26)；左边界取 **100** 是把**整栏**排除（不只是排除那一个窗口位置），
#:     故 100..230 这一栏里 **≥ 阈值只剩「自动」一个**（实测：唯一候选）。
#:   · 同排别的控件都在 roi 外：底部【挑战】x≈297 起、Party 行 y≈74、SET 条 y≈14 —— 全在框外。
#:
#: ★诚实登记的副作用★：roi 是一个矩形，覆盖不了「编队页左下 (142,1062)」与「共斗房间页右上
#: (630,102)」两处不同位置。收窄到编队页后，**房间页不再由模板定位**，改由 OCR 整串 ``^自动$``
#: 兜底（:data:`AUTO_LABEL_PATTERNS`；真机 5+ 帧都读对，:func:`is_team_auto_control` 保证只在
#: 编队页/房间页认）。这是刻意取舍：房间页那次 0.811 只比阈值高 0.06，本来就在边缘；
#: 而「房间页误点兄弟控件」的风险随全屏候选池一起消失。要两头都覆盖，得再加一个节点（另票）。
AUTO_LABEL_ROI: tuple[int, int, int, int] = (100, 1030, 130, 90)

#: 模板结果排序：**显式** ``Score``（取最像的那个），绝不依赖默认 ``Horizontal``（最左）。
#:
#: 为什么必须显式（协议语义，不是风格问题）：``order_by`` 缺省 ``Horizontal`` + ``index`` 缺省 0
#: ⇒ 「排序后取第 0 个 = **x 最小**的那个」，与"最像"毫无关系。写了 ``Score`` 才是"最像"。
#: 即使 :data:`AUTO_LABEL_ROI` 已经让候选唯一（实测 roi 内 ≥ 阈值只有 1 个），这一条仍写死：
#:   (a) **语义显式** —— 这条定位的意图是"最像"，默认的最左只是**碰巧**正确；
#:   (b) **兜住 roi 放宽** —— 将来谁为了覆盖房间页又把 roi 放大，``Score`` 仍能挡住 0.8964 的兄弟；
#:   (c) **不吃默认值变更** —— ``order_by`` 的默认值/可选值随版本变过（v5.1 加 ``Expected``），
#:       写在节点里就不受框架默认值改动影响。
AUTO_ORDER_BY = "Score"

#: 「自动续战」开关的标签（ruling ③：保持关；定位同「自动」，仅文本不同）。
CONT_LABEL = "自动续战"


def label_patterns(label: str = AUTO_LABEL) -> tuple[str, ...]:
    """某个开关标签的**整串** OCR 正则（默认「自动」；「自动续战」按整串）。"""
    if label == AUTO_LABEL:
        return AUTO_LABEL_PATTERNS
    return (rf"^{re.escape(label)}$",)


def box_fully_inside(roi, box) -> bool:
    """``box`` 是否**完整**落在 ``roi`` 内（都是 720 空间 ``(x, y, w, h)``）。

    用途：判「模板滑窗能不能跑到这个位置」——模板匹配是逐位置滑窗，只有**整窗**落在 roi 内
    的位置才是候选（被裁掉一部分的位置不存在）。``AUTO_LABEL_ROI`` 的自证与守卫
    ``tools/contract_hooks/hooks_108.py`` 的假阳用例都走这一条，别在各处手写四边比较。
    """
    x, y, w, h = (int(v) for v in box)
    rx, ry, rw, rh = (int(v) for v in roi)
    return rx <= x and ry <= y and x + w <= rx + rw and y + h <= ry + rh


# ---------------------------------------------------------------------------
# ② 状态探针（相对**定位到的标签框**；不写死绝对坐标）+ 点击点
# ---------------------------------------------------------------------------
#: 橙色占比阈值（真机：开 ≈ 0.58~0.63；关 = 0.00 —— 与 0.15 有 ~4 倍余量）。
AUTO_ON_RATIO = 0.15

#: label -> (dx0, dy0, dx1, dy1)：探针相对标签框 ``(x, y, w, h)`` 的偏移。
#: 开关状态指示（橙色滑块）在**标签正下方**——三种页面（编队页 / 房间页 / 暂停屏）相对一致。
PROBE_OFFSETS: dict[str, tuple[int, int, int, int]] = {
    # 「自动」：真机标定 probe (127,1103,202,1132) 对标签 (142,1062,43,26)。
    AUTO_LABEL: (-15, 41, 17, 70),
    # 「自动续战」：真机标定 probe (20,1102,78,1133) 对标签 (17,1062,79,24)。
    CONT_LABEL: (3, 40, -18, 71),
}


def probe_for(label: str, box) -> tuple[int, int, int, int]:
    """由**定位到的标签框**推出状态探针 ``(x0,y0,x1,y1)``（720 空间）。"""
    x, y, w, h = (int(v) for v in box)
    dx0, dy0, dx1, dy1 = PROBE_OFFSETS.get(label, PROBE_OFFSETS[AUTO_LABEL])
    return (x + dx0, y + dy0, x + w + dx1, y + dy1)


def click_point_of(box) -> tuple[int, int]:
    """点击点 = **识别框中心**（运维裁决②：「按其识别框中心点击」）。

    ★真机复证★：编队页「自动」标签框 `[142,1062,43,26]` 的中心 `(163,1075)` 落在整张
    自动卡（标签 + 开关）的**可点区**内 —— 2026-10-15 真机 16384 实测：把自动关掉后点该中心
    即回「开」（diag: state False → True）。所以「点识别框中心」不是死坐标、且确实生效。
    """
    x, y, w, h = (int(v) for v in box)
    return (x + w // 2, y + h // 2)


# ---------------------------------------------------------------------------
# ②b 页面范围（★三批根因修复★）：只在【编队页 / 房间页】认「自动」
# ---------------------------------------------------------------------------
# ★为什么要这一步（真机帧自证，2026-10-15 127.0.0.1:16384）★
#   旧的 ``auto_switch_state`` 是**全屏** OCR（`^自动$`，无页面范围）→ 它在**战斗/结算画面**上
#   命中了**战斗 HUD 的「自动」**（OCR 框 `[15,193,55,19]`；与编队页底栏的「自动」
#   `[142,1062,43,26]` 是**两个不同的控件、位置也完全不同**）：
#     · 命中帧 = `QUEST CLEAR` 战斗画面（屏上还有 `时间 09:55` / `分数 …` / `技能 自动 开`）；
#       探针落在战斗 HUD 上没有橙色 → 读成「关」→ 门控误命中；
#     · 随后动作在**转场/加载帧**（`请耐心等待 79.28%`）上再截一帧 → 屏上已无「自动」
#       → `定位不到 … → 不动`（**静默失败**，规则形同没做）；
#     · 若动作帧仍是战斗画面，就会点战斗 HUD 中心（≈ `(42,202)`）→ `点后仍未达期望`。
#   两种失败形态都是**同一个根因**：门控没有限定在编队页/房间页。
#   证据帧（本批留档）：`tools/frames/auto_battle_hud_*.png`（战斗命中帧 + 加载失败帧）。
#
# 判据（都不含任何坐标，保持「定位式」）：
#   · 页面锚点：编队页/房间页的**独有文本**（挑战/编成/SET编辑/招募/复制/战力/Party）；
#   · 开关自证：定位到的「自动」标签**正下方探针区**内有 `开`/`关` 状态字 —— 证明它是**开关**，
#     而不是战斗 HUD 那种纯标签。
# 二者取「或」：任一成立即认；战斗画面两条都不成立 → 绝不认、绝不点。
TEAM_PAGE_ANCHORS: tuple[str, ...] = (
    # 编队页底部【挑战】（领主战 / 深渊EX / 五重 都实测有）。
    # ★#109★ 这同一个按钮有**两种渲染**：`挑战` 与 `挑战→`（带箭头）。真机识别调研统计
    #   8/17 帧是带箭头的（`debug/wc_a_set1_back.png` 亦可见箭头），整串 `^挑战$` 会漏掉
    #   这**一半**的帧 → 门控有一半概率不成立 ⇒ 必须兼容箭头。`(→)?` 只放过箭头本身，
    #   仍是**整串**锚定（绝不裸「挑战」，否则会命中「再次挑战 / 继续挑战 / 挑战深渊连战」）。
    r"^挑战(→)?$",
    r"^编成$",     # 编队页【编成】
    r"^SET编辑$",  # 编队页【SET编辑】
    r"^招募$",     # 房间页【招募】
    r"^复制$",     # 房间页每行【复制】
    r"^战力$",     # 编队页 / 房间页【战力】
    r"Party",      # 编队页 / 房间页左列 Party 槽位
)
#: 开关状态字（在开关探针区内出现即证明「这是个开关」）。
SWITCH_STATE_PATTERNS: tuple[str, ...] = (r"^开$", r"^关$")


def page_is_team(items) -> bool:
    """画面是否是**编队页 / 房间页**（文本锚点，位置无关；不含坐标）。"""
    for t, _b in items or ():
        s = (t or "").strip()
        for p in TEAM_PAGE_ANCHORS:
            if re.search(p, s):
                return True
    return False


def has_switch_state_text(items, label: str, box) -> bool:
    """定位到的标签框**正下方探针区内**是否有 `开`/`关` 状态字（证明它是开关而非普通标签）。"""
    probe = probe_for(label, box)
    for t, b in items or ():
        if not b or len(b) != 4:
            continue
        if not any(re.search(p, (t or "").strip()) for p in SWITCH_STATE_PATTERNS):
            continue
        cx, cy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
        if probe[0] <= cx <= probe[2] and probe[1] <= cy <= probe[3]:
            return True
    return False


def is_team_auto_control(items, label: str, box) -> bool:
    """定位到的「自动」是否是**编队页 / 房间页的自动开关**（页面锚点 ∨ 开关状态字）。

    ★这是把「自动」门控**限定在编队页/房间页**的唯一判据★（真机根因见本段开头）：
    战斗 HUD 的「自动」两条都不满足 → 永不认、永不点。
    """
    return page_is_team(items) or has_switch_state_text(items, label, box)


# ---------------------------------------------------------------------------
# ②c 战斗页作用域（#71）：在【战斗页】认战斗 HUD 的「自动」，只在正证据为「开」时关掉
# ---------------------------------------------------------------------------
# ★为什么要这一步（运维裁决 B1/D4，spec ``docs/spec/wuchong-spec.md``）★
#   「自动的关闭做在**编队页**不管用 —— 游戏会在**战斗里又把它打开**，所以必须在**战斗页**关。」
#   现状的 ``is_team_auto_control``（②b）**明确拒绝**战斗 HUD 的「自动」，因此战斗页永远关不掉。
#   本段新增**战斗页作用域**：定位战斗 HUD 的「自动」按钮、读它的开/关、只在**正证据为「开」**
#   时才点它一次（关掉）。与编队页作用域**互斥**（同一帧只会命中其一）。
#
# ★离线证据★：唯一真机帧 ``tools/frames/auto_battle_hud_hit.png``（720×1280，战斗页，自动=**开**）。
#   该帧上战斗 HUD 的「自动」OCR 框 = ``[15,193,55,19]``；同屏另有「技能自动」``[26,260,34,21]``
#   （状态字 `开` 在 ``[33,280,18,18]``）。按钮区的**青绿色填充**实测均值 RGB ≈ (93,191,183)
#   （G、B 远大于 R），上面压着白色图标/文字。
#   ★诚实缺口★：仓库里**没有任何一张「自动=关」的战斗页帧** → 关态只能靠「把探针区涂灰 → 读数必须
#   为关」的**合成反例**来守（照既有守卫 ``auto-outside-state-read-correct`` 的写法）；
#   真机校准待后续。
#: 战斗 HUD 锚点（底部条带：时间 HH:MM / 分数 N）。★与 ``agent/battle_loop_core.py`` 的
#: ``BATTLE_HUD_TIME_RE`` / ``BATTLE_HUD_SCORE_RE`` **逐字同源**（守卫 ``wuchong-71-*`` 逐字比对）★：
#: 二者不复制成两个真源，只保证取值一致（本模块不 import battle_loop_core 以免耦合）。
#: ★#107 真机（2026-10-18 05:5x）★ 战斗 HUD 被遮挡时的**兜底视觉锚点**。
#: 真机证据：`tools/frames/wuchong_hud_occluded.png` —— 同一场战斗中，底部「时间/分数」那条
#: 被「技能槽未满。」这类 toast 压住、OCR 读不出来，但 FEVER / 血条百分比 / ABILITY 都读得到。
#: ★判据是「≥2 个同时出现」★：单个特征太弱（结算页也有伤害数字、主城也有倒计时）。
#: 负例（必须**不**被兜底判据认成战斗）：结算页 / GAMEOVER / 编队页 / 主城，各有自己的状态判据。
BATTLE_HUD_FALLBACK_ANCHORS: tuple[str, ...] = (
    r"FEVER",
    r"\d{1,3}\.\d%",       # 血条百分比（三处队友血条）
    r"^ABILIT",              # 底部技能条被裁切时常见
)
#: 兜底判据至少命中几个锚点。
BATTLE_HUD_FALLBACK_MIN = 2

BATTLE_HUD_ANCHORS: tuple[str, ...] = (r"时间\s*\d{1,3}:\d{2}", r"分数\s*\d")

#: 战斗页「自动」标签文本（与编队页同字面，但作用域/位置不同）。
BATTLE_AUTO_LABEL = "自动"
#: 战斗页「自动」标签的允许 ROI ``(x0,y0,x1,y1)``（720 空间；用**框中心**落此筛选）。
#: 用它把战斗 HUD 的 ``[15,193,55,19]`` 选进来，把同屏「技能自动」``[26,260,34,21]``
#: 与编队页底栏的 ``[142,1062,43,26]`` **排除**掉。
BATTLE_AUTO_LABEL_ROI = (0, 150, 170, 240)
#: 战斗页「自动」探针（相对**定位到的标签框**，绝不写死坐标）：ON 帧标签 ``[15,193,55,19]``
#: → 探针 ``(8,160,100,228)``（按钮青绿色填充区）。
BATTLE_AUTO_PROBE_OFFSETS: dict[str, tuple[int, int, int, int]] = {
    BATTLE_AUTO_LABEL: (-7, -33, 30, 16),
}
#: 青绿填充占比阈值（ON 帧实测 ≈ 0.73；与 0.15 有 ~4.8 倍余量 —— ★关态无真机帧，待校准★）。
BATTLE_AUTO_ON_RATIO = 0.15
#: 青绿判据的通道差阈值：``g - r > 40 ∧ b - r > 40``（战斗 HUD 按钮填充）。
BATTLE_AUTO_FILL_DR = 40
#: 战斗页**不用**模板（仓库那张 ``auto/switch_label.png`` 裁片是**编队页**标签，别乱用）。
BATTLE_AUTO_TEMPLATES: tuple[str, ...] = ()


def battle_hud_is_present(items) -> bool:
    """画面是否是**战斗页**（战斗 HUD 底部条带锚点：``时间 HH:MM`` / ``分数 N``；文本判据，位置无关）。"""
    for t, _b in items or ():
        s = (t or "").strip()
        for p in BATTLE_HUD_ANCHORS:
            if re.search(p, s):
                return True
    return False


def is_battle_auto_control(items, label: str, box) -> bool:
    """定位到的「自动」是否是**战斗页 HUD 的自动控件**（战斗页锚点 ∧ 框中心落在战斗 ROI 内）。

    与 :func:`is_team_auto_control` **互斥**：编队页帧无战斗 HUD 锚点 → 这里判否；
    战斗 HUD 帧的「技能自动」/编队页底栏「自动」因框中心不在 ROI 内 → 也判否。
    """
    if not battle_hud_is_present(items):
        return False
    if not box or len(box) != 4:
        return False
    cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
    x0, y0, x1, y1 = BATTLE_AUTO_LABEL_ROI
    return x0 <= cx <= x1 and y0 <= cy <= y1


def battle_probe_for(label: str, box) -> tuple[int, int, int, int]:
    """由**定位到的战斗标签框**推出状态探针 ``(x0,y0,x1,y1)``（720 空间；相对框，绝不写死坐标）。

    语义与 :func:`probe_for` 一致，只是偏移取自 :data:`BATTLE_AUTO_PROBE_OFFSETS`。
    """
    x, y, w, h = (int(v) for v in box)
    dx0, dy0, dx1, dy1 = BATTLE_AUTO_PROBE_OFFSETS.get(
        label, BATTLE_AUTO_PROBE_OFFSETS[BATTLE_AUTO_LABEL])
    return (x + dx0, y + dy0, x + w + dx1, y + h + dy1)


# ---------------------------------------------------------------------------
# ③ 「自动续战功能」确认框（ruling ③）：出现就按「取消 / 不启用」处理，★绝不打开功能★
# ---------------------------------------------------------------------------
CONT_DIALOG_TITLE = "自动续战功能"
CONT_DIALOG_PATTERNS: tuple[str, ...] = (r"自动续战功能",)
CONT_DIALOG_CANCEL_PATTERNS: tuple[str, ...] = (r"^取消$",)


def auto_dialog_present(texts) -> bool:
    """是否出现「自动续战功能」确认框（标题命中）。"""
    return any(re.search(p, t or "") for t in texts or () for p in CONT_DIALOG_PATTERNS)


def dialog_cancel_point(items):
    """在 OCR 项里定位确认框的「取消 / 不启用」按钮框（返回 (cx,cy) 或 None）。"""
    for t, b in items or ():
        if not b or len(b) != 4:
            continue
        if any(re.search(p, t or "") for p in CONT_DIALOG_CANCEL_PATTERNS):
            return (b[0] + b[2] // 2, b[1] + b[3] // 2)
    return None
