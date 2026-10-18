# -*- coding: utf-8 -*-
"""#105 A 类「战前编队页」的**模板真源**：5 张模板 + SET 槽位几何 + 模板引导的局部 OCR 窗口。

★这张票要解决什么（先纠正票面事实，再谈方案）★
-------------------------------------------------
票面说「真机证明 A 类页的关键标签 OCR 读不出来」，并列了 ``SET 1 / Party A / 战力 /
自动续战 / 挑战`` 五个读不到的词。**实测不成立**：

* 票面指定的证据帧 ``tools/frames/abyss_ex_team_page_A.png`` 是「深渊连战 EX 第1战」的
  **关卡详情页**（不可续战 / 推荐编成 / 推荐属性 水 / 体力 0 / 放弃 / 战斗记录&重置），
  这一页**物理上没有** SET 条 / Party / 战力 / 自动续战 / 挑战 —— 它当然读不到。
  票面引用的那串 OCR 输出正是这一帧的完整结果。
* 真正的 A 类战前编队页是同一次抓帧的**另一张** ``abyss_ex_team_page_A_team.png``
  （1080x1920，484 / 深渊连战EX 第1战 / SET 1·2·3 三页签 / 1 Party A / 战力 141）。
  它在 720 空间 OCR **能读**：``自动续战``(0.9999) / ``Party A``(0.9407) / ``SET 1``(0.9588) /
  ``战力``(0.9999) / ``141``(0.9999) / ``挑战``(0.9998)。
* ⇒ 真正坏掉的是**解析**，不是 OCR。``agent/team_impl.read_team`` 在真帧上返回
  ``(None, None, None)`` 的两个直接原因：
  1. ``TEAM_PARTY_RE = (\\d+)\\s*Party\\s*([A-Z])`` **要求 ``Party`` 前必须有数字**，而真机把队号
     那个大字 ``1`` 吞掉、只给 ``Party A`` → ``party=None``；
  2. ``战力`` 与数值 ``141`` 是**两个独立 OCR 框** → ``power=None``。
* 解析两条是**主修**（纯解析，不依赖任何模板，见 ``read_team``）；模板通道是**第二通道**
  （OCR 退化时的兜底），两者必须**各自都能读对**（``hooks_105`` 的
  ``team-battle-read-team-parse-only`` 与 ``-template-only`` 分别钉住）。

★模板通道承担三件事（不是「替 OCR 认字」）★
------------------------------------------
1. **页面判据**（:func:`scene.team.is_battle_team_page` 的第二通道）：A 类页的布局独有图形
   命中任一即算 —— 与 OCR 通道取**或**；
2. **SET 号兜底**（:func:`set_index_from_pill`）：``SET N`` 的 **N 是内容**（1..12 都出现过），
   模板**不能**裁数字。所以只裁**选中槽**（深底白字 ``SET`` 三字母，不含数字），再用它的
   **x 位置**落到实测槽位表 ⇒ 当前 SET 号；
3. **Party 行 / 战力行的定位锚**（:data:`PARTY_NO_CROP` / :data:`POWER_ROW`）：队号大字全屏
   OCR 会吞，但**只裁那一小块再 OCR 就读得出来**（实测 ``1`` @720 (39,521)）—— 取值仍在
   OCR 侧，模板不猜数字。

★为什么 A 类页能模板化，而 B 类编辑器不行★
------------------------------------------
A 类页是**一张定版面板**：SET 槽、``Party`` 行、``战力`` 徽标在 720 空间是固定几何
（``SET`` 槽文字 y≈461..470、``Party`` 行 y≈514、``战力`` 徽标 y≈515），三张不同页面
（深渊 EX / 五重 / 外传）实测坐标**一致** —— 见 :data:`TEAM_TEMPLATES` 的 ``roi``。
B 类编辑器（角色→队伍编成）的锚点是 ``^切换$`` 与会滚动的圆点行，本票**不改**它。

★三种防线（#108 的机制教训：别只靠阈值）★
----------------------------------------
1. **``roi`` 是主防线**：全屏 = 把兄弟控件放进候选池，届时「选哪个」由 ``order_by`` +
   ``index`` 决定，默认 ``Horizontal`` + ``0`` = **取最左**。每个 roi 都按「装得下正例整窗、
   装不下最近的兄弟图形」标定；``global_watch`` 记下**放宽到全屏**时会命中哪里（量化证据：
   最危险的一条是 ``power_label``，全屏 0.7763 —— 仍低于 0.90，但余量只剩 0.12）。
2. **``order_by: Score`` 显式**：要「最像」，不吃默认「最左」。
3. **``threshold`` 只保留本义**（低分噪声闸门）：挡不住同款底框的兄弟控件，那靠 roi；
   ``margin`` = 「阈值 − 负例最高分」，<0.05 就是靠阈值擦屁股。

★量测口径（与 #102 同一把尺）★
----------------------------
* 坐标一律 **720x1280 基准空间**；非 720 源帧按 **LANCZOS** 下采样（``auto/switch_label.png``
  与框架所见逐像素差 0.00，调研 §5.2 第一步）。
* 分数 = **全滑窗** ``TM_CCOEFF_NORMED``，两口径：``gray``（灰度）与 ``color``（三通道展平，
  框架真正的口径）。正例取 ``min(gray,color)``（保守），负例取 ``max(gray,color)``（危险侧）。
* 有效期：**数字只对 ``tools/frames/`` 里那几帧成立**。换帧 / 换模板 / 动 roi ⇒ 重新标定，
  ``hooks_105`` 的 ``team-battle-tpl-archive``（容差 0.02）与 ``team-battle-tpl-pixels``
  （逐像素重裁）会当场变红。

★取证现状（诚实登记）★
--------------------
* **正例 4 条**：``abyss_ex_team_page_A_team.png``（484/深渊EX，**裁剪源**）、
  ``33_wuchong_team.png``（720 原生，五重超级：SET 1 / Party A / 战力 8,876）、
  ``side_team_page.png`` 与 ``lord_team_page.png``（外传：SET 2 / Party E / 战力 12,205，
  同一画面的两次存盘）。★后三条**不是裁剪源**★ ⇒ 「跨帧泛化」是实测出来的，
  不是样本内自证（调研 §5.3 第 3 条的坑）。
* **负例 8 条**：票面点名的 4 张（关卡详情 / 领主详情 / 主城 / 结算）+ 战斗 HUD 2 张 +
  关卡列表 + 加成弹窗。
* ★未取证的外推★：``SET 2`` / ``SET 3`` **被选中**时的画面仓里没有（票面只给了 SET 1 选中的帧）。
  L1（三页签）槽位表 :data:`SET_SLOT_TAB_X` 的第 2/3 项是从**未选中页签的文字位置**量的
  （文字不随选中态移动，只有底色变）。这种外推必须留痕：:data:`SET_SLOT_TAB_MEASURED` 只认
  第 1 项，``hooks_105`` 的 ``team-battle-tpl-set-index`` 钉住这句声明。
"""

from __future__ import annotations

from dataclasses import dataclass

from .auto_switch import box_fully_inside

#: 模板根（pipeline 里的 ``template`` 是相对它的路径）。
IMAGE_DIR_REL = "assets/resource/image"

#: 识别空间（写死 720；与 ``scene.pixels.BASE_W/BASE_H`` 同源，守卫核对相等）。
BASE_W = 720
BASE_H = 1280


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TplHit:
    """一帧上某模板在 **roi 内**的最高分位置（灰 / 彩两口径）。"""

    frame: str
    gray: float
    color: float
    x: int
    y: int

    @property
    def worst(self) -> float:
        """危险侧（负例用它）：两口径取**高**者。"""
        return max(self.gray, self.color)

    @property
    def best(self) -> float:
        """保守侧（正例用它）：两口径取**低**者。"""
        return min(self.gray, self.color)


@dataclass(frozen=True)
class TeamTemplateSpec:
    """一张模板的全部承重数据：路径 / roi / 阈值 / 排序 / 裁片窗口 / 正负例与**存档分数**。"""

    key: str
    label: str
    #: 相对 ``assets/resource/image/`` 的模板路径。
    template: str
    #: 搜索范围（720 空间 ``[x, y, w, h]``）—— ★主防线★，必须**整窗**放下 :attr:`window`。
    roi: tuple
    #: 入闸门阈值（「这个位置算不算命中」；**不是**「取最高分」）。
    threshold: float
    #: 结果排序（一律显式 ``Score`` = 取最像，不吃默认 ``Horizontal`` = 取最左）。
    order_by: str
    #: 裁片窗口（720 空间 ``[x, y, w, h]``；同时就是模板尺寸）。
    window: tuple
    #: 裁片来源帧（模板必须能从这里按 window **逐像素**重裁出来）。
    source_frame: str
    #: 跨帧正例（**含** source_frame 自己）。
    positives: tuple
    #: 负例帧在 roi 内的最高分（逐帧）。
    negatives: tuple
    #: 为什么裁这块、为什么不裁更多（人读理由，别只留数字）。
    why: str
    #: ★roi 外的危险高分★：放宽到全屏时会命中哪里（证明 roi 是承重防线）。
    global_watch: tuple = ()

    # --- 派生量（守卫 / 测试 / agent 都走这里，别在别处重算） --------------------
    @property
    def positive_worst(self) -> float:
        """正例最保守分（全部正例、两口径取低者的最小值）。"""
        return min((h.best for h in self.positives), default=0.0)

    @property
    def negative_worst(self) -> float:
        """负例最高分（全部负例里两口径取高者的最大值）。"""
        return max((h.worst for h in self.negatives), default=0.0)

    @property
    def margin(self) -> float:
        """阈值余量 = ``threshold - negative_worst``；<0.05 就是靠阈值擦屁股。"""
        return round(self.threshold - self.negative_worst, 4)

    @property
    def positive_margin(self) -> float:
        """正例余量 = ``positive_worst - threshold``；<0.05 就是擦线，跨帧一抖就漏。"""
        return round(self.positive_worst - self.threshold, 4)

    @property
    def template_rel(self) -> str:
        """模板的仓内相对路径。"""
        return f"{IMAGE_DIR_REL}/{self.template}"


def window_fits(roi, window) -> bool:
    """``window`` 是否**完整**落在 ``roi`` 内（滑窗逐位置，装不下就永远命中不了）。"""
    return box_fully_inside(roi, window)


# ---------------------------------------------------------------------------
# 取证帧（这里的字符串是**评审入口**：每个数字都能顺着它回到一帧真机画面）
# ---------------------------------------------------------------------------
#: ★裁剪源 / 主证据帧★：484 深渊连战 EX 第1战 的战前编队页（1080x1920 → LANCZOS 720）。
SRC_FRAME = "tools/frames/abyss_ex_team_page_A_team.png"
#: 384 五重决战·超级 的战前编队页（**原生 720x1280**；SET 1 / Party A / 战力 8,876）。
WUCHONG_FRAME = "tools/frames/33_wuchong_team.png"
#: 外传「向王都进发1」的战前编队页（1080x1920 → 720；SET 2 / Party E / 战力 12,205）。
SIDE_FRAME = "tools/frames/side_team_page.png"
#: 领主战的战前编队页（与 ``SIDE_FRAME`` 同一画面的另一次存盘，字节不同）。
LORD_FRAME = "tools/frames/lord_team_page.png"

#: ★票面点名的 4 张负例★（前四条 = 票面顺序）+ 4 张同族危险页。
NEG_FRAMES = (
    # 票面第一条点名的是「详情页」；票面误把它当成了 A 类页（见模块 docstring）。
    "tools/frames/abyss_ex_team_page_A.png",
    "tools/frames/lord_detail_multidiff.png",
    "tools/frames/maze57_head_on_maincity.png",
    "tools/frames/wuchong76_settle_giveup_after_fight.png",
    # 追加：战斗 HUD 有「自动 / 自动续战」开关（同款字），是最容易被 auto_continue 假阳的画面。
    "tools/frames/wuchong_hud_readable.png",
    "tools/frames/auto_battle_hud_action.png",
    # 追加：列表页 / 弹窗（`战力` / `挑战` / 编队字样会出现）。
    "tools/frames/event_stage_list.png",
    "tools/frames/lord_bonus_dialog.png",
)


# ---------------------------------------------------------------------------
# ★A 类页判据的模板通道★：任一命中即算（与 OCR 通道取或）
# ---------------------------------------------------------------------------
#: 参与「这是不是 A 类页」的模板键（= 全部 5 张）。票面口径：**任一命中即算**。
PAGE_KEYS = ("auto_continue", "set_selected", "challenge_btn", "party_label", "power_label")

#: A 类独有 OCR 锚点（既有通道，**不删**）：与 ``scene.team.TEAM_PAGE_ANCHOR_A`` 同源，
#: 守卫核对相等。放在这里是为了「只看一个文件就能读懂判据」。
PAGE_ANCHOR_A = "自动续战"
#: B 类独有 OCR 锚点（否定判据：B 类页绝不能按 A 类坐标点）。
PAGE_ANCHOR_B = "^切换$"


# ---------------------------------------------------------------------------
# ① 选中 SET 槽的「SET」三字母（不含数字）
# ---------------------------------------------------------------------------
#: 模板 = **深底白字**的 ``SET`` 三字母 + 左右各 5px 深底（34x20）。
#: ★为什么只裁这三字母★：``SET N`` 的 **N 是内容**（1..12 都出现过）⇒ 裁了数字的模板只在那一
#: 帧成立（调研 §1.3「内容在变」）。三字母在 SET 1..12 每一态下像素相同。
#: ★为什么天然只命中「被选中」的那一槽★：未选中槽是**白底深字**（与模板明暗相反），灰度
#: ZNCC 是强负相关，永远过不了 0.88 的闸门。
#: ★为什么 roi 是 y 440..500 的一条带★：三张 A 类页的 SET 条 y 都在 450..482；这条带**排除**
#: 了 ``SET编辑`` 按钮（y≈950，同样的 ``SET`` 三字母 —— 全屏 roi 会把它放进候选池）。
SET_SELECTED = TeamTemplateSpec(
    key="set_selected",
    label="A 类页·被选中的 SET 槽（深底白字 SET 三字母，不含数字）",
    template="team/set_selected.png",
    roi=(40, 440, 640, 60),
    threshold=0.88,
    order_by="Score",
    window=(126, 456, 34, 20),
    source_frame=SRC_FRAME,
    positives=(
        TplHit(SRC_FRAME, 1.0000, 1.0000, 126, 456),
        TplHit(WUCHONG_FRAME, 0.9953, 0.9952, 68, 456),
        TplHit(SIDE_FRAME, 0.9520, 0.9456, 117, 456),
        TplHit(LORD_FRAME, 0.9520, 0.9456, 117, 456),
    ),
    negatives=(
        TplHit("tools/frames/abyss_ex_team_page_A.png", 0.5074, 0.4293, 504, 462),
        TplHit("tools/frames/lord_detail_multidiff.png", 0.3529, 0.3310, 125, 480),
        TplHit("tools/frames/maze57_head_on_maincity.png", 0.3109, 0.2441, 346, 472),
        TplHit("tools/frames/wuchong76_settle_giveup_after_fight.png", 0.4246, 0.4097, 615, 474),
        TplHit("tools/frames/wuchong_hud_readable.png", 0.4194, 0.3566, 332, 472),
        TplHit("tools/frames/auto_battle_hud_action.png", 0.4011, 0.3813, 246, 449),
        TplHit("tools/frames/event_stage_list.png", 0.2808, 0.1085, 627, 445),
        TplHit("tools/frames/lord_bonus_dialog.png", 0.0000, 0.0189, 194, 465),
    ),
    why=(
        "N 是内容（SET 1..12 都出现过），所以只裁选中槽的「SET」三字母：任何 N 下像素相同，"
        "把「第几个槽被选中」交给几何（set_index_from_pill），而不是交给模板去认数字。"
    ),
    global_watch=(TplHit("tools/frames/lord_detail_multidiff.png", 0.4677, 0.4405, 86, 501),),
)

# ---------------------------------------------------------------------------
# ② Party 行标签（Party 五个字母，不含队号大字 / 字母名）
# ---------------------------------------------------------------------------
#: 模板 = ``Party`` 五个字母（深字白底，58x26）。
#: ★为什么不裁队号 ``1``★：队号是内容（1..6），且它在大屏上常被吞（见模块 docstring）。
#: ★为什么不裁字母名★：``Party A`` / ``Party E`` 的字母名也是内容（实测 31 次里 6 种）。
#: ★用途★：①页面判据；②``read_team`` 的**行定位锚** —— 队号大字读不到时按 :data:`PARTY_NO_CROP`
#: 只裁那一小块再 OCR（取到 ``1``）。
PARTY_LABEL = TeamTemplateSpec(
    key="party_label",
    label="A 类页·Party 行标签（Party 五字母，不含队号 / 字母名）",
    template="team/party_label.png",
    roi=(60, 500, 300, 46),
    threshold=0.90,
    order_by="Score",
    window=(92, 514, 58, 26),
    source_frame=SRC_FRAME,
    positives=(
        TplHit(SRC_FRAME, 1.0000, 1.0000, 92, 514),
        TplHit(WUCHONG_FRAME, 0.9961, 0.9956, 92, 514),
        TplHit(SIDE_FRAME, 1.0000, 1.0000, 92, 514),
        TplHit(LORD_FRAME, 1.0000, 1.0000, 92, 514),
    ),
    negatives=(
        TplHit("tools/frames/abyss_ex_team_page_A.png", 0.3271, 0.2989, 238, 501),
        TplHit("tools/frames/lord_detail_multidiff.png", 0.3123, 0.3058, 188, 506),
        TplHit("tools/frames/maze57_head_on_maincity.png", 0.4308, 0.4284, 199, 500),
        TplHit("tools/frames/wuchong76_settle_giveup_after_fight.png", 0.3013, 0.2109, 265, 520),
        TplHit("tools/frames/wuchong_hud_readable.png", 0.2626, 0.1917, 296, 519),
        TplHit("tools/frames/auto_battle_hud_action.png", 0.1675, 0.1489, 290, 513),
        TplHit("tools/frames/event_stage_list.png", 0.2950, 0.0894, 153, 506),
        TplHit("tools/frames/lord_bonus_dialog.png", 0.2913, 0.2916, 246, 501),
    ),
    why=(
        "Party 行是 A 类页独有的白色行（y≈514，三张页面一致）；只裁五个字母，"
        "因为队号（1..6）与字母名（A..H）都是内容。它同时是队号局部 OCR 的锚。"
    ),
    global_watch=(TplHit("tools/frames/lord_detail_multidiff.png", 0.3811, 0.2577, 84, 9),),
)

# ---------------------------------------------------------------------------
# ③ 战力标签（只裁「战力」二字，数值另行 OCR）
# ---------------------------------------------------------------------------
#: 模板 = 青色徽标里的白字 ``战力``（**不含**数值，44x27）。
#: ★为什么不连数值一起裁★：战力每帧在变（141 / 8,876 / 12,205），模板必须**状态无关**；
#: 数值仍走 OCR（数字大、可读：真机 ``141`` score 0.9999）。它也是 :data:`POWER_ROW`
#: 同行绑定的锚（``战力`` 与数值是两个 OCR 框）。
POWER_LABEL = TeamTemplateSpec(
    key="power_label",
    label="A 类页·战力标签（只裁「战力」二字，数值走 OCR）",
    template="team/power_label.png",
    roi=(480, 500, 200, 46),
    threshold=0.90,
    order_by="Score",
    window=(524, 515, 44, 27),
    source_frame=SRC_FRAME,
    positives=(
        TplHit(SRC_FRAME, 1.0000, 1.0000, 524, 515),
        TplHit(WUCHONG_FRAME, 0.9959, 0.9972, 524, 515),
        TplHit(SIDE_FRAME, 1.0000, 1.0000, 524, 515),
        TplHit(LORD_FRAME, 1.0000, 1.0000, 524, 515),
    ),
    negatives=(
        TplHit("tools/frames/abyss_ex_team_page_A.png", 0.4369, 0.6249, 500, 512),
        TplHit("tools/frames/lord_detail_multidiff.png", 0.2371, 0.4036, 614, 509),
        TplHit("tools/frames/maze57_head_on_maincity.png", 0.3176, 0.6199, 491, 513),
        TplHit("tools/frames/wuchong76_settle_giveup_after_fight.png", 0.3072, 0.1358, 578, 505),
        TplHit("tools/frames/wuchong_hud_readable.png", 0.3307, 0.3804, 634, 501),
        TplHit("tools/frames/auto_battle_hud_action.png", 0.2557, 0.3867, 510, 505),
        TplHit("tools/frames/event_stage_list.png", 0.3746, 0.6146, 627, 504),
        TplHit("tools/frames/lord_bonus_dialog.png", 0.0392, 0.3637, 481, 519),
    ),
    why=(
        "「战力」二字是定版白字 + 青色底，跨三张页面像素相同；数值（141 / 8,876 / 12,205）"
        "是内容，裁进模板就等于把模板钉死在一帧上。"
    ),
    # ★放宽到全屏的代价（量化证据）★：``lord_detail_multidiff.png`` 全屏**彩**口径最高
    # **0.7763**@(651,579) —— 仍低于 0.90，但余量只剩 0.12；roi 把窗口钉在「战力」徽标上时
    # 余量是 0.2751。这就是「roi 是主防线、阈值是第二道」的数字形态。
    global_watch=(TplHit("tools/frames/lord_detail_multidiff.png", 0.6017, 0.3469, 153, 66),),
)

# ---------------------------------------------------------------------------
# ④ 自动续战（A 类页**独有**的 OCR 锚点，这里做它的模板版）
# ---------------------------------------------------------------------------
#: 模板 = ``自动续战`` 四个字（浅底深字，82x26），A 类页底部左侧。
#: ★为什么它是页面判据里最硬的一条★：``自动`` 两字出现在战斗 HUD / 各种开关上，``自动续战``
#: **只有战前编队页有**（既有 OCR 通道的 ``TEAM_PAGE_ANCHOR_A`` 就是它）。模板版的意义是
#: 「OCR 读不到这四个字时判据不塌」，不是替它认字。★不能只裁「自动」★——那会命中战斗 HUD
#: 的开关（``scene/auto_switch.py`` 记下的那次误点）。
AUTO_CONTINUE = TeamTemplateSpec(
    key="auto_continue",
    label="A 类页·自动续战（A 类页独有锚点）",
    template="team/auto_continue.png",
    roi=(0, 1040, 140, 60),
    threshold=0.90,
    order_by="Score",
    window=(16, 1061, 82, 26),
    source_frame=SRC_FRAME,
    positives=(
        TplHit(SRC_FRAME, 1.0000, 1.0000, 16, 1061),
        TplHit(WUCHONG_FRAME, 0.9973, 0.9972, 16, 1061),
        TplHit(SIDE_FRAME, 1.0000, 1.0000, 16, 1061),
        TplHit(LORD_FRAME, 1.0000, 1.0000, 16, 1061),
    ),
    negatives=(
        TplHit("tools/frames/abyss_ex_team_page_A.png", 0.3068, 0.2888, 19, 1074),
        TplHit("tools/frames/lord_detail_multidiff.png", 0.2274, 0.2076, 20, 1044),
        TplHit("tools/frames/maze57_head_on_maincity.png", 0.1645, 0.1518, 18, 1068),
        TplHit("tools/frames/wuchong76_settle_giveup_after_fight.png", 0.3411, 0.1891, 39, 1061),
        TplHit("tools/frames/wuchong_hud_readable.png", 0.1702, 0.1536, 0, 1046),
        TplHit("tools/frames/auto_battle_hud_action.png", 0.2355, 0.1937, 3, 1040),
        TplHit("tools/frames/event_stage_list.png", 0.1725, 0.1182, 21, 1047),
        TplHit("tools/frames/lord_bonus_dialog.png", 0.1149, 0.0654, 35, 1057),
    ),
    why=(
        "四字整体裁（不是只裁「自动」）：只裁「自动」会命中战斗 HUD 的开关（同字同底色），"
        "这正是 scene/auto_switch.py 记下的那次误点。roi 收在左下角那一格。"
    ),
    global_watch=(TplHit("tools/frames/wuchong_hud_readable.png", 0.4105, 0.3884, 328, 852),),
)

# ---------------------------------------------------------------------------
# ⑤ 挑战按钮（``挑战`` 二字，白字橙底）
# ---------------------------------------------------------------------------
#: 模板 = ``挑战`` 两个字（白字 + 橙色按钮底，66x40），**不含箭头 ``→``**。
#: ★为什么不含箭头★：箭头是独立图形，它的 y 在两族页面之间**差 16px**
#: （``33_wuchong_team.png`` 按钮在 y≈1050，深渊/外传在 y≈1066）⇒ 把箭头裁进去会把跨帧最差
#: 正例从 **0.9722 压到 0.9447**（实测）。而且箭头不增加鉴别力：没有任何负例页有 ``挑战``
#: 二字（负例最高 0.3892）。
#: ★为什么这一条不能只靠 OCR★：``挑战`` 在真机有**两种像素稳定的读法**
#: （``挑战`` / ``挑战→``，调研 §1.2 例 1：约 47% 的帧上「``挑战`` 整串锚定」不匹配 —— 正则写成
#: ``^挑战`` + ``$`` 时只认前者）—— 正是模板该管的那一类。
CHALLENGE_BTN = TeamTemplateSpec(
    key="challenge_btn",
    label="A 类页·挑战按钮（挑战二字，白字橙底；不含箭头）",
    template="team/challenge_btn.png",
    roi=(250, 1040, 220, 80),
    threshold=0.88,
    order_by="Score",
    window=(296, 1066, 66, 40),
    source_frame=SRC_FRAME,
    positives=(
        TplHit(SRC_FRAME, 1.0000, 1.0000, 296, 1066),
        TplHit(WUCHONG_FRAME, 0.9722, 0.9910, 296, 1050),
        TplHit(SIDE_FRAME, 1.0000, 1.0000, 296, 1066),
        TplHit(LORD_FRAME, 0.9739, 0.9914, 296, 1050),
    ),
    negatives=(
        TplHit("tools/frames/abyss_ex_team_page_A.png", 0.2447, 0.1076, 255, 1056),
        TplHit("tools/frames/lord_detail_multidiff.png", 0.2527, 0.1702, 268, 1042),
        TplHit("tools/frames/maze57_head_on_maincity.png", 0.3137, -0.0859, 398, 1080),
        TplHit("tools/frames/wuchong76_settle_giveup_after_fight.png", 0.2924, 0.3255, 398, 1048),
        TplHit("tools/frames/wuchong_hud_readable.png", 0.2545, 0.1226, 368, 1078),
        TplHit("tools/frames/auto_battle_hud_action.png", 0.2883, 0.1418, 330, 1045),
        TplHit("tools/frames/event_stage_list.png", 0.2015, 0.0883, 289, 1080),
        TplHit("tools/frames/lord_bonus_dialog.png", 0.3892, 0.1347, 250, 1068),
    ),
    why=(
        "「挑战」是真机两种像素稳定读法之一（挑战 / 挑战→），OCR 的整串锚定"
        "（「挑战」+ 行尾 $）只在约一半帧成立；模板是这一类的正解。roi 只给按钮中心那一块，"
        "左右两侧的铃铛 / 自动开关都不进候选池。"
    ),
    # ★放宽到全屏的代价★：``wuchong76_manual_fight_working.png`` 全屏**彩**口径最高 **0.5893**。
    global_watch=(
        TplHit("tools/frames/wuchong76_manual_fight_working.png", 0.5009, 0.1830, 263, 612),
    ),
)

#: 全部模板（键 = :attr:`TeamTemplateSpec.key`）。
TEAM_TEMPLATES: dict = {
    spec.key: spec
    for spec in (SET_SELECTED, PARTY_LABEL, POWER_LABEL, AUTO_CONTINUE, CHALLENGE_BTN)
}


# ---------------------------------------------------------------------------
# SET 槽位几何：把「选中槽的 x」翻译成 SET 号
# ---------------------------------------------------------------------------
#: L1 = 深渊 EX 那种**三页签**条（每页签都写着 ``SET n``，被选中的那个是深色药丸）。
#: 值 = **模板左上角 x**（不是文字左边界：模板在文字左侧留 5px 深底）。
#: 第 1 项 126 是**实测命中**（本帧 SET 1 被选中）；第 2/3 项 337 / 549 是从**未选中页签的
#: 文字位置**量的（342 / 554 各减 5）：文字不随选中态移动，只有底色变。
SET_SLOT_TAB_X = (126, 337, 549)
#: L1 里**实测命中过**的槽位下标（0 基）。守卫用它钉住「其余两项是外推」。
SET_SLOT_TAB_MEASURED = (0,)

#: L2 = 五重 / 外传那种**圆点条 + 滑动药丸**（未选中的槽是一个个圆点，药丸停在当前槽上）。
#: 档位 1 的模板左上角 x（实测：``33_wuchong_team.png`` SET 1 → 68；
#: ``side_team_page.png`` SET 2 → 117 = 68 + 49 ⇒ step 49，与 #105 的圆点间距标定一致）。
SET_SLOT_BAR_X0 = 68
#: L2 相邻槽位间距（px，720 空间；与 ``scene.team.TEAM_BATTLE_SET_STEP_PX`` 同源，守卫核对）。
SET_SLOT_BAR_STEP = 49
#: L2 档数上限（与 ``scene.team.TEAM_BATTLE_SET_MAX`` 同源）。
SET_SLOT_BAR_MAX = 12
#: 槽位吸附容差（px）。实测命中位置是整数且可复现；容差 6 同时保证两族布局不互相顶掉：
#: L1 的 126 与 L2 的 117（SET 2）差 9 > 6；L1 的 549 与 L2 的 558（SET 11）差 9 > 6。
SET_SNAP_TOL = 6


def set_slots():
    """全部候选槽位 ``[(x, set_no, layout), …]``（layout ∈ ``{"tab3", "barN"}``）。

    ★为什么把两族布局并成一张候选表★：A 类页其实有**两族**布局（深渊 EX 三页签 / 五重·外传
    圆点条），槽位间距差 4 倍（211 vs 49），一张表表达不了。并成一张候选表 + 唯一性检查，
    比「先判布局再查表」少一次判据（少一次判据 = 少一处假阳）。
    """
    slots = [(x, i + 1, "tab3") for i, x in enumerate(SET_SLOT_TAB_X)]
    slots += [
        (SET_SLOT_BAR_X0 + SET_SLOT_BAR_STEP * (n - 1), n, "barN")
        for n in range(1, SET_SLOT_BAR_MAX + 1)
    ]
    return slots


def set_index_from_pill(pill_x, tol=SET_SNAP_TOL):
    """把「选中 SET 槽的模板左上角 x」翻成 SET 号；**有歧义 / 够不着就返回 None**。

    返回 ``(set_no, layout, residual)`` 或 ``None``。三条规则，缺一不可：

    1. 只在 ``|x − 槽位| ≤ tol`` 的候选里选；
    2. 取残差最小的那个；
    3. ★歧义即拒★：若**另一个布局**的候选残差与最小值相差 ≤1px，说明两种几何都能解释这个
       位置 ⇒ 返回 ``None``（宁可不读，也不猜 SET —— 猜错就是按 A 类坐标点到 B 类页上）。
    """
    if pill_x is None:
        return None
    try:
        x = int(pill_x)
    except (TypeError, ValueError):
        return None
    hits = [(abs(x - sx), n, layout) for sx, n, layout in set_slots() if abs(x - sx) <= tol]
    if not hits:
        return None
    hits.sort()
    best_res, best_no, best_layout = hits[0]
    for res, _n, layout in hits[1:]:
        if layout != best_layout and res - best_res <= 1:
            return None
    return best_no, best_layout, best_res


# ---------------------------------------------------------------------------
# 模板引导的**局部 OCR** 窗口（模板定位 + 局部 OCR 取值）
# ---------------------------------------------------------------------------
#: 队号大字裁片窗口（720 空间 ``[x, y, w, h]``）。
#: ★为什么需要它★：全屏 OCR 把队号那个大字**吞掉**（真帧只给 ``Party A``），但**只裁这一小块**
#: 再 OCR 就读得出来 —— 实测 ``1`` @720 框 (39,521) score 0.9994（真帧裁剪后 OCR 直接给
#: ``1``，框 = 整个裁片）。★为什么宽 70★：再宽就把 ``Party`` 的 ``P``（x≈88）圈进来。
PARTY_NO_CROP = (16, 505, 70, 50)

#: 战力行的裁片窗口（720 空间 ``[x, y, w, h]``）：``战力`` 与数值是两个 OCR 框，全屏时可能
#: 分开给；只裁这一条行再 OCR，两个框都在（实测 ``战力`` + ``141`` / ``8,876``）。
POWER_ROW = (480, 500, 240, 46)
#: 「同一行」的 y 中心容差（px）：用来把数值框绑到 ``战力`` 框上。
POWER_ROW_DY = 14
#: 数值框必须落在 ``战力`` 框右侧的横向窗口内（相对 ``战力`` 框左边界的 px 区间）。
POWER_ROW_DX = (0, 200)


# ---------------------------------------------------------------------------
# 取证 OCR 存档（720 空间；hooks_105 只读它，tools/test_team_templates.py 负责重跑复核）
# ---------------------------------------------------------------------------
#: 主证据帧的**完整** 720 空间 OCR 结果 ``(text, [x, y, w, h])``。★存档的意义★：守卫不跑 OCR
#: （native 库 + 资源加载，慢且脆），它读这份存档；``tools/test_team_templates.py`` 会**重跑
#: 一次真 OCR** 并断言存档仍能复现（逐条文本相同、框 ±3px）—— 「存档 vs 实跑」两处对账，
#: 改帧 / 换模型都会红。
#: ★别为了好看改这份存档★：里面**没有**单独的队号 ``1``（被吞），也没有把 ``战力`` 与数值
#: 合并成一框 —— 那两个正是本票要兜的坑，存档必须保留它们的真实形态。
EVIDENCE_OCR = {
    SRC_FRAME: (
        ("自动续战", [17, 1062, 79, 24]),
        ("返回", [30, 1246, 46, 26]),
        ("等级7", [41, 814, 63, 30]),
        ("队长", [45, 566, 33, 22]),
        ("关", [55, 1105, 27, 25]),
        ("SCORE", [60, 344, 57, 20]),
        ("BEST", [63, 280, 69, 30]),
        ("RECORD", [64, 305, 67, 19]),
        ("824/101", [92, 20, 113, 28]),
        ("Party A", [92, 512, 99, 36]),
        ("战斗", [100, 197, 33, 20]),
        ("SET 1", [127, 457, 39, 15]),
        ("开", [140, 1106, 24, 23]),
        ("自动", [142, 1062, 43, 26]),
        ("封锁：火·水·风·暗", [219, 88, 156, 22]),
        ("不可续战", [221, 205, 82, 24]),
        ("深渊连战 EX 第1战", [222, 117, 231, 28]),
        ("推荐属性水", [226, 165, 161, 27]),
        ("000,000,000", [239, 336, 175, 32]),
        ("SS评价", [254, 257, 82, 23]),
        ("挑战", [297, 1069, 80, 47]),
        ("SET 2", [337, 454, 44, 20]),
        ("体力", [379, 169, 55, 24]),
        ("关卡详情", [424, 198, 97, 30]),
        ("0", [485, 170, 16, 20]),
        ("3,142,815", [506, 17, 98, 27]),
        ("编成", [513, 952, 46, 25]),
        ("战力", [525, 516, 41, 25]),
        ("SET 3", [549, 454, 43, 20]),
        ("141", [590, 516, 45, 26]),
        ("SET编辑", [595, 950, 78, 28]),
    ),
    WUCHONG_FRAME: (
        ("自动续战", [17, 1062, 79, 24]),
        ("SET 1", [67, 454, 42, 20]),
        ("Party A", [92, 512, 99, 36]),
        ("自动", [142, 1062, 43, 26]),
        ("挑战", [296, 1053, 82, 47]),
        ("战力", [525, 516, 41, 25]),
        ("SET编辑", [596, 952, 76, 24]),
    ),
    SIDE_FRAME: (
        ("自动续战", [15, 1061, 82, 28]),
        ("Party E", [92, 512, 95, 36]),
        ("SET 2", [117, 457, 41, 15]),
        ("自动", [142, 1062, 43, 26]),
        ("挑战", [297, 1069, 80, 47]),
        ("战力", [525, 516, 41, 25]),
        ("SET编辑", [596, 952, 76, 28]),
    ),
}

#: ★模板引导的局部 OCR 存档★（窗口见 :data:`PARTY_NO_CROP` / :data:`POWER_ROW`；坐标已换算回
#: 720 空间）。这是「只开模板通道、把全屏 OCR 喂空」那条验收腿的输入：SET 由模板位置给出，
#: 队号与战力由这两块局部 OCR 给出。**实测**（两张不同页面各一遍，见 test_team_templates）。
LOCALIZED_OCR = {
    SRC_FRAME: (
        # PARTY_NO_CROP (16,505,70,50) 的 OCR：整个裁片就是一个大字 1。
        ("1", [16, 505, 70, 50]),
        # POWER_ROW (480,500,240,46) 的 OCR：战力 + 数值两个框。
        ("战力", [529, 518, 35, 22]),
        ("141", [593, 517, 38, 26]),
    ),
    WUCHONG_FRAME: (
        ("1", [16, 505, 70, 50]),
        ("战力", [525, 518, 39, 22]),
        ("8,876", [590, 518, 63, 26]),
    ),
    SIDE_FRAME: (
        # 外传页 `5 Party E`：全屏 OCR 同样只给 `Party E`（队号被吞），局部裁片给出 5。
        ("5", [16, 505, 70, 50]),
        ("战力", [525, 518, 39, 22]),
        ("12,205", [593, 517, 75, 26]),
    ),
}

#: 负例帧的**判据相关** OCR 片段（存档）。空元组 = 该帧一个判据相关词都没有（正是期望）。
EVIDENCE_OCR_NEG = {
    # 深渊EX 关卡详情页：只有「推荐编成 / 推荐属性」，没有 A 类页的任何锚点。
    "tools/frames/abyss_ex_team_page_A.png": (
        ("推荐编成", [56, 1114, 96, 30]),
        ("推荐属性", [209, 1116, 83, 28]),
    ),
    # 领主详情页：四行「推荐编成 / 推荐属性 光」，同样没有 A 类锚点。
    "tools/frames/lord_detail_multidiff.png": (
        ("推荐编成", [56, 530, 96, 30]),
        ("推荐编成", [56, 721, 94, 29]),
        ("推荐编成", [56, 912, 94, 29]),
        ("推荐编成", [56, 1102, 94, 30]),
        ("推荐属性  光", [206, 724, 152, 26]),
    ),
    # 主城 / 结算页：判据相关词一个都没有。
    "tools/frames/maze57_head_on_maincity.png": (),
    "tools/frames/wuchong76_settle_giveup_after_fight.png": (),
}
