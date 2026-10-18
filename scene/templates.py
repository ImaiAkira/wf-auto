# -*- coding: utf-8 -*-
"""模板识别 P0 三项（#102）—— **模板路径 / ROI / 阈值 / 期望 ZNCC 的唯一真源**。

★这张票要解决什么★
------------------
`docs/research/template-match-candidates.md` 的 P0 三项：星导石不足行、领主加成「是/否」按钮、
NEW 徽标。它们的共同点是「画进图里的图形 / 一两个字的按钮」，OCR 在这里的失效是**结构性**的
（单字无上下文、艺术字描边、多写法兜底）。本模块只描述**数据**，不导入 PIL / numpy、不跑逻辑
（``scene/`` 的纪律：离线可导入、是配置权威；量测在 ``tools/contract_hooks/hooks_102.py``）。

★为什么门槛是「负例不假阳 + 存档 ZNCC 数字」，不是「换完能认」★
---------------------------------------------------------------
本仓血泪（``scene/auto_switch.py`` 模块头 + ``docs/research/recognition-ocr-vs-template.md``
§2.4）：MAA **原生** ``TemplateMatch`` 在离线 ZNCC 只有 **0.470** 的位置也选中过；同类的第二例是
``banner_abyss_ex`` 对纯深渊横幅假阳 **0.8708``。所以每个模板都必须在**已入库真机帧**上逐帧
报出分数，并把数字**存档在本文件**（:data:`TEMPLATES`），由 ``hooks_102``
（``p0-archive-scores-match-measured``，容差 0.02）与 ``tools/test_template_p0.py`` 双向核对 ——
换帧 / 换模板 / 调阈值只要不重新标定，离线套件就红。

★三种防线，不要只靠阈值★（#108 的机制教训）
------------------------------------------
1. **``roi`` 是主防线**：全屏 = 候选池 = 整屏，届时「选哪个」由 ``order_by`` + ``index`` 决定，
   而默认 ``order_by: Horizontal`` + ``index: 0`` = **取最左**（协议，见 ``.research/3.1-pipeline.md``
   ``:497-508``）。所以每个模板节点都必须有**收窄**的 roi，且 roi 要能**整窗**放得下正例窗口
   （:func:`window_fits`，滑窗是逐位置的，被裁掉一半的位置不存在）。
2. **``order_by: Score`` 显式**：要「最像」，不要吃默认的「最左」。
3. **``threshold`` 只保留本义**：过滤低分噪声。它挡不住「同款底框的兄弟控件」——「否/是」两个
   按钮底框**完全相同**（实测灰 ZNCC 互评 **0.5840**，远超任何可用阈值），真正把它们分开的是
   roi 把各自那一半排除，见 :data:`BONUS_NO` / :data:`BONUS_YES` 的 ``sibling_*``。

★量测口径★（与 ``hooks_108`` 同一手法，另加彩色）
------------------------------------------------
* 坐标系：**720x1280 基准空间**（MaaFramework 识别空间，``scene.pixels``）；源帧非 720 的
  （1080x1920 原图）按 **LANCZOS 下采样**到 720 —— 与 ``auto/switch_label.png`` 的裁片口径一致
  （调研 §5.2 第一步：LANCZOS 与框架所见逐像素差 0.00）。
* 分数：**全滑窗** ``TM_CCOEFF_NORMED``（不是点测一个框！框架做的是滑窗，会跑到点测跑不到的位置）。
  * ``gray`` = 灰度 ZNCC —— 与本仓既有存档（0.8964 / 0.470 / 0.8708）可比。
  * ``color`` = 三通道展平 ZNCC —— **框架真正的口径**（协议没有「转灰度」开关，模板是彩色 PNG，
    ``cv::matchTemplate(…, TM_CCOEFF_NORMED)`` 在 8UC3 上是**跨通道单一均值**）。
  * 结论取**保守侧**：正例取 ``min(gray, color)``，负例取 ``max(gray, color)``。
* 有效期：**本文件的数字只对 ``tools/frames/`` 里那几帧成立**。换帧 / 换模板 / 动 roi 就必须重标定
  （``hooks_102`` 的破坏实验会逼你这么做）。

★三项的取证现状（诚实登记，别假装齐了）★
---------------------------------------
* **P0-1 星导石不足行** —— 正例帧 ``stamina_insufficient_wuchong384.png``（真机 384，720x1280）
  在库；负例 6 帧在库。模板 = **图标**（不含 ``×50`` 数量，数量会变）。
* **P0-2 是/否** —— 正例帧 ``lord_bonus_dialog.png``（真机，1080x1920 → LANCZOS 720）在库；
  同帧另一按钮就是天然负例（互相验证）。
* **P0-3 NEW 徽标** —— ★**正例帧缺失**★：票面指定的 ``tools/frames/side_story_list.png`` **不含任何
  NEW 徽标**（整帧扫描 + 左列放大目视复核；该帧是「外传故事列表」系列卡，没有 NEW 角标），
  而 ``PubNewCharTap`` 认的**大** NEW 徽标（720 ``(13,845,252,153)``）**仓内一张真机帧都没有**
  （``tools/test_inject_scope.py`` 只能**合成**一张）。全仓唯一含 NEW 徽标的真机帧是
  ``ark62_detail_unpairable.png``（小行徽标 720 ``(14,388,51,20)``，OCR ``NEW [15,389,51,20]``），
  但它的宿主节点是 ``special_dungeon.json::SpecialNewBadge`` —— **本票禁改**。
  ⇒ 该项标 **待取证**：模板与数字已备（:data:`NEW_BADGE`，供下一张票直接用），但**不接线**
  （:data:`NEW_BADGE_WIRED = False`，``hooks_102`` 的 ``p0-new-badge-unwired-pending`` 钉住这句话）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .auto_switch import box_fully_inside

#: 模板根（pipeline 里的 ``template`` 是相对它的路径；协议：模板图片路径 = ``image`` 文件夹的相对路径）。
IMAGE_DIR_REL = "assets/resource/image"

#: 识别空间（写死 720；与 ``scene.pixels.BASE_W/BASE_H`` 同源，这里只作为本模块的常量别名，
#: 免得为了一个尺寸去 import 整个 pixels —— 守卫会核对两者相等）。
BASE_W = 720
BASE_H = 1280


# ---------------------------------------------------------------------------
# 数据结构：一份模板 = 一条「配置 + 数字」的证词
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NegativeHit:
    """一帧负例上，**roi 内**的最高分位置（灰 / 彩两口径）。"""

    frame: str
    gray: float
    color: float
    x: int
    y: int

    @property
    def worst(self) -> float:
        """保守分：两口径取高者（负例越「像」越危险）。"""
        return max(self.gray, self.color)


@dataclass(frozen=True)
class TemplateSpec:
    """一个模板的全部承重数据：路径 / roi / 阈值 / 排序 / 正负例与**存档分数**。"""

    key: str
    label: str
    #: 相对 ``assets/resource/image/`` 的模板路径。
    template: str
    #: 搜索范围（720 空间 ``[x, y, w, h]``）—— ★主防线★，必须**整窗**放得下 :attr:`window`。
    roi: tuple[int, int, int, int]
    #: 入闸门阈值（「这个位置算不算命中」；**不是**「取最高分」）。
    threshold: float
    #: 结果排序（本仓一律显式 ``Score`` = 取最像，不吃默认 ``Horizontal`` = 取最左）。
    order_by: str
    #: 正例帧上模板的**最佳对齐窗口**（720 空间 ``[x, y, w, h]``，同时也是模板裁片尺寸）。
    window: tuple[int, int, int, int]
    #: 正例帧（仓内相对路径）。
    positive_frame: str
    #: 正例分数（灰 / 彩），实测。
    positive_gray: float
    positive_color: float
    #: 负例帧逐帧的 roi 内最高分。
    negatives: tuple[NegativeHit, ...] = ()
    #: ★同帧兄弟控件★（底框同款的另一个按钮 / 另一个徽标）：它**必须落在 roi 外**，
    #: 且分数要**报出来**（这是「阈值救不了」的证据）。
    sibling_window: tuple[int, int, int, int] | None = None
    sibling_gray: float = 0.0
    sibling_color: float = 0.0
    #: ★roi 外的危险高分★：证明「roi 是主防线」而不是「模板天然不假阳」。
    global_watch: tuple[NegativeHit, ...] = ()
    #: 该项的取证状态（``"ok"`` = 正例在库；``"pending"`` = 待取证）。
    evidence: str = "ok"
    #: 证据缺失的具体说明（``evidence != "ok"`` 时必填）。
    evidence_note: str = ""

    # --- 派生量（守卫与测试都走这里，别在别处重算） -----------------------------
    @property
    def positive_worst(self) -> float:
        """正例保守分：两口径取**低**者。"""
        return min(self.positive_gray, self.positive_color)

    @property
    def negative_worst(self) -> float:
        """负例最高分（保守）：roi 内全部负例里两口径取高者的最大值。"""
        return max((n.worst for n in self.negatives), default=0.0)

    @property
    def margin(self) -> float:
        """阈值余量 = ``threshold - negative_worst``；<0 就是**已经假阳**。"""
        return round(self.threshold - self.negative_worst, 4)

    @property
    def template_rel(self) -> str:
        """模板的仓内相对路径。"""
        return f"{IMAGE_DIR_REL}/{self.template}"


def window_fits(roi, window) -> bool:
    """``window`` 是否**完整**落在 ``roi`` 内（模板滑窗只有整窗在内才是候选）。

    走 ``scene.auto_switch.box_fully_inside``（#108 的同一份几何判据，不抄第二份）。
    """
    return box_fully_inside(roi, window)


# ---------------------------------------------------------------------------
# P0-1 ★星导石不足行★（帧：tools/frames/stamina_insufficient_wuchong384.png）
# ---------------------------------------------------------------------------
#: 模板：真机 384 帧里「星导石 × 50」那一行的**物品图标**（彩虹球），720 空间 ``(82,877,103,88)``。
#: ★为什么不裁文字★：行名会 OCR 成「星岛石」（多写法兜底的来源）；★为什么不裁 ``×50``★：
#: 数量是真机 2753425（持有数）会变，模板必须**状态无关**（N=「内容会跳变」的教训）。
#: ★为什么是图标而不是「行卡片」★：行卡片横跨 x 70..650，而「体力回复药（中/大）」的行卡片
#: 形状完全一样 → 会互相假阳；图标是这个行**独有**的图形。
STONE_ICON = TemplateSpec(
    key="stone_icon",
    label="星导石不足行·物品图标（模板优先，OCR 兜底）",
    template="common/stamina_stone_icon.png",
    # roi 只框**图标那一栏**：x 66..200（行名起于 x≈209，数量起于 x≈518 都被排除），
    # y 852..988 留 ±23px 上 / ±23px 下余量（#74 的教训：ROI 差 30px 就整条失效）。
    roi=(66, 852, 134, 136),
    threshold=0.85,
    order_by="Score",
    window=(82, 877, 103, 88),
    positive_frame="tools/frames/stamina_insufficient_wuchong384.png",
    positive_gray=1.0,
    positive_color=1.0,
    negatives=(
        NegativeHit("tools/frames/stamina_recovered_done_wuchong384.png", 0.2534, 0.0404, 73, 870),
        NegativeHit("tools/frames/lord_bonus_dialog.png", 0.2716, 0.0396, 96, 871),
        NegativeHit("tools/frames/side_story_list.png", 0.0, 0.2779, 77, 900),
        NegativeHit("tools/frames/side_story_list_empty.png", 0.0, 0.0001, 66, 896),
        NegativeHit("tools/frames/ark62_detail_unpairable.png", 0.0, 0.0001, 66, 896),
        NegativeHit("tools/frames/lord_team_page.png", 0.165, 0.1077, 66, 891),
    ),
    # ★roi 外的危险高分，必须点名★：同一个「彩虹球」图形在别处真会出现 ——
    # ``ark62_detail_unpairable.png`` 的【首次报酬】道具就是这个彩虹球（灰 **0.7734** / 彩 **0.8014**
    # @(530,439)），``lord_team_page.png`` 上也有 灰 **0.7805** / 彩 **0.8090** @(568,269)。
    # **全屏 roi = 直接假阳**（彩口径 0.8014 离 0.85 只剩 0.049），所以 roi 是承重防线，
    # 不是顺手写一个。破坏实验「roi 全屏 + 阈值 0.70」就是拿这条把 C4 打红的。
    global_watch=(
        NegativeHit("tools/frames/ark62_detail_unpairable.png", 0.7734, 0.8014, 530, 439),
        NegativeHit("tools/frames/lord_team_page.png", 0.7805, 0.809, 568, 269),
    ),
)


# ---------------------------------------------------------------------------
# P0-2 ★领主加成「是 / 否」按钮★（帧：tools/frames/lord_bonus_dialog.png）
# ---------------------------------------------------------------------------
#: 模板 = **按钮底框 + 字**（不是只裁字）：底框的圆角/渐变压过单字的笔画，且它在同一张弹窗里
#: 位置稳定。裁自 1080x1920 原图 LANCZOS 到 720 后的 ``(44,789,296,73)`` / ``(372,789,296,73)``。
#:
#: ★为什么阈值救不了这一对★：两个按钮的底框**像素级同款**（只有填充色与字不同）。
#: 实测互评：灰 **0.5840**、彩 **−0.9169**。灰口径下 0.5840 已经高于本仓任何可用阈值下界附近，
#: 而彩口径把它压到负值 —— 两个口径都**不能**单独把「否」挡住「是」的位置。
#: ⇒ 真正的防线是 **roi 把另一半排除**（:data:`BONUS_NO`.roi 右边界 360 < 是按钮左边界 372）。
BONUS_NO = TemplateSpec(
    key="bonus_no",
    label="领主加成点数弹窗·【否】按钮（模板优先，OCR 兜底）",
    template="wuchong/bonus_btn_no.png",
    roi=(0, 760, 360, 140),
    threshold=0.85,
    order_by="Score",
    window=(44, 789, 296, 73),
    positive_frame="tools/frames/lord_bonus_dialog.png",
    positive_gray=1.0,
    positive_color=1.0,
    negatives=(
        NegativeHit("tools/frames/stamina_insufficient_wuchong384.png", 0.1938, 0.1632, 42, 760),
        NegativeHit("tools/frames/stamina_recovered_done_wuchong384.png", 0.1662, -0.2092, 43, 785),
        NegativeHit("tools/frames/side_story_list.png", 0.178, 0.5609, 22, 811),
        NegativeHit("tools/frames/side_story_list_empty.png", 0.0604, 0.0141, 31, 780),
        NegativeHit("tools/frames/ark62_detail_unpairable.png", 0.0, 0.0, 0, 767),
        NegativeHit("tools/frames/lord_team_page.png", 0.0625, 0.0179, 21, 819),
    ),
    sibling_window=(372, 789, 296, 73),
    sibling_gray=0.584,
    sibling_color=-0.9169,
    global_watch=(
        # 「体力回复了！」结果窗的【取消】也是同款红色圆角按钮：灰 **0.7091** @(206,789)
        # （该窗口处彩口径 −0.9010，因为取消按钮是粉红而模板是红：彩口径反而把它推开）。
        # 它在 roi 的 x 允许范围（0..64）之外 → 被 roi 挡住，而不是被阈值挡住。
        NegativeHit("tools/frames/stamina_recovered_done_wuchong384.png", 0.7091, -0.901, 206, 789),
    ),
)

BONUS_YES = TemplateSpec(
    key="bonus_yes",
    label="领主加成点数弹窗·【是】按钮（模板优先，OCR 兜底）",
    template="wuchong/bonus_btn_yes.png",
    roi=(360, 760, 360, 140),
    threshold=0.85,
    order_by="Score",
    window=(372, 789, 296, 73),
    positive_frame="tools/frames/lord_bonus_dialog.png",
    positive_gray=1.0,
    positive_color=1.0,
    negatives=(
        NegativeHit("tools/frames/stamina_insufficient_wuchong384.png", 0.1057, 0.1418, 360, 779),
        NegativeHit("tools/frames/stamina_recovered_done_wuchong384.png", 0.08, 0.4642, 374, 779),
        NegativeHit("tools/frames/side_story_list.png", 0.1814, -0.1839, 415, 788),
        NegativeHit("tools/frames/side_story_list_empty.png", 0.0624, 0.0124, 391, 775),
        NegativeHit("tools/frames/ark62_detail_unpairable.png", 0.0, 0.0, 370, 767),
        NegativeHit("tools/frames/lord_team_page.png", 0.135, 0.021, 382, 774),
    ),
    sibling_window=(44, 789, 296, 73),
    sibling_gray=0.584,
    sibling_color=-0.9169,
)


# ---------------------------------------------------------------------------
# P0-3 ★NEW 徽标★ —— **待取证**（详见模块 docstring 的「取证现状」）
# ---------------------------------------------------------------------------
#: 模板 = 小行 NEW 徽标本体（粉字 + 深红描边），720 空间 ``(14,388,52,21)``，
#: 裁自 ``tools/frames/ark62_detail_unpairable.png``（全仓唯一含 NEW 徽标的真机帧）。
#: ★不裁背景★：徽标在不同页面的行底色不同（橙色详情行 / 浅色卡片），带底色 = 换页必挂。
#: ★不加内边距★：加了 5px 背景后负例最高分从 0.7615 → **0.8255**（更危险），实测数据在案。
NEW_BADGE = TemplateSpec(
    key="new_badge",
    label="NEW 徽标·小行徽标（**待取证，未接线**）",
    template="common/badge_new.png",
    roi=(0, 380, 120, 600),
    threshold=0.85,
    order_by="Score",
    window=(14, 388, 52, 21),
    positive_frame="tools/frames/ark62_detail_unpairable.png",
    positive_gray=1.0,
    positive_color=1.0,
    negatives=(
        NegativeHit("tools/frames/stamina_insufficient_wuchong384.png", 0.4277, 0.3596, 22, 405),
        NegativeHit("tools/frames/stamina_recovered_done_wuchong384.png", 0.6834, 0.4095, 29, 857),
        NegativeHit("tools/frames/lord_bonus_dialog.png", 0.6886, 0.7607, 46, 787),
        NegativeHit("tools/frames/side_story_list.png", 0.7615, 0.5998, 25, 470),
        NegativeHit("tools/frames/side_story_list_empty.png", 0.3374, 0.3446, 56, 435),
        NegativeHit("tools/frames/lord_team_page.png", 0.5843, 0.6976, 24, 565),
    ),
    evidence="pending",
    evidence_note=(
        "票面指定的正例帧 tools/frames/side_story_list.png **不含任何 NEW 徽标**"
        "（整帧扫描 + 左列放大目视复核：该帧是「外传故事列表」的三张系列卡，没有 NEW 角标）；"
        "而 PubNewCharTap 认的**大** NEW 徽标 720 (13,845,252,153) 仓内**一张真机帧都没有**"
        "（tools/test_inject_scope.py 只能合成）。全仓唯一含 NEW 徽标的真机帧是 "
        "ark62_detail_unpairable.png（小行徽标），其宿主节点 special_dungeon.json::SpecialNewBadge "
        "在本票禁改清单里 ⇒ 模板与数字已备好，**不接线**，等下一张票补正例帧 / 改宿主节点。"
    ),
)

#: ★P0-3 是否已接线★：False = 只交付模板 + 数字，**没有任何 pipeline 节点引用它**。
#: ``hooks_102`` 的 ``p0-new-badge-unwired-pending`` 会核对这句声明与 pipeline 现状一致
#: （有人偷偷接线却不更新这里 → 红；有人在证据齐了之后接线却忘了改 → 也红）。
NEW_BADGE_WIRED = False


# ---------------------------------------------------------------------------
# 注册表 + pipeline 节点的**唯一真源**（JSON 是手写投影，逐项相等由 hooks_102 钉住）
# ---------------------------------------------------------------------------
#: 全部模板（键 = :attr:`TemplateSpec.key`）。
TEMPLATES: dict[str, TemplateSpec] = {
    spec.key: spec for spec in (STONE_ICON, BONUS_NO, BONUS_YES, NEW_BADGE)
}

#: P0 三项（票面口径）→ 模板键（一项可以有多张模板）。
P0_ITEMS: dict[str, tuple[str, ...]] = {
    "P0-1 星导石不足行": ("stone_icon",),
    "P0-2 是/否按钮": ("bonus_no", "bonus_yes"),
    "P0-3 NEW 徽标": ("new_badge",),
}

# --- P0-1 的节点名 ---------------------------------------------------------
#: 模板叶（TemplateMatch，common.json）。
NODE_STONE_ICON = "PubStaminaStoneIcon"
#: ★双通道叶★ ``Or(any_of: [模板叶, OCR 叶])`` —— 模板优先、OCR 兜底（``Or`` 是「命中第一个即
#: 成功，后续不再识别」，协议 ``.research/3.1-pipeline.md:858-860``）。
NODE_STONE_ROW = "PubStaminaStoneRow"
#: 动作节点（``And(弹窗正文, 双通道行) + box_index=1`` → ``Click target:true`` = 点识别框中心）。
NODE_USE_STONE_TPL = "PubStaminaUseStoneTpl"
#: OCR 兜底叶（**既有节点，本票不动**：``hooks_stamina`` 钉住它是 OCR + expected + roi）。
NODE_STONE_OCR = "PubStaminaStoneText"
#: OCR 兜底的**动作**节点（既有，本票不动；``PubStaminaUseStoneTpl`` 就是它的模板版）。
NODE_USE_STONE_OCR = "PubStaminaUseStone"
#: 弹窗正文叶（既有，复用）。
NODE_STONE_POPUP = "PubStaminaInsufficientText"
#: ★接线现状（2026-10-18 更新）★：模板动作节点已接进**全部 7 个消费链枢纽** ——
#: ``side_story.json`` 的 ``SideStoryEntry`` / ``SideClearEntry``、``abyss.json::AbyssEntry``、
#: ``auto_push.json::AutoPush``、``raid.json::RaidDispatch``、``special_dungeon.json::SpecialEntry``、
#: ``wuchong.json::WuchongEntry`` + ``wuchong_scene.json::WuchongGuardChain``（#102）。
#: 一律 ``[JumpBack]`` 排在既有 OCR 动作节点**之前**（模板优先、OCR 兜底）。
#: ★下面这个常量是**历史声明**（#102 之前只接了外传两个入口），保留它是因为
#: ``hooks_102`` / ``tools/test_template_p0.py`` 拿它当「追加声明」用；接线事实由
#: ``scene.stamina.STAMINA_CONSUMING_CHAINS``（消费链真源）与 ``hooks_102`` 的
#: ``p0-stone-row-hubs`` 逐枢纽对账，不靠这份常量。★
STONE_TPL_WIRED_HUBS: tuple[tuple[str, str], ...] = (
    ("side_story.json", "SideStoryEntry"),
    ("side_story.json", "SideClearEntry"),
)
#: 模板动作节点的 ``[JumpBack]`` 引用形式（各枢纽 ``next`` 里用它）。
STONE_TPL_REF = f"[JumpBack]{NODE_USE_STONE_TPL}"

# --- P0-2 的节点名 ---------------------------------------------------------
#: ``Or`` 双通道叶（**保留原节点名** ⇒ ``WuchongBonusNo`` / 各流程节点的候选集不用改一个字节）。
NODE_BONUS_NO = "WuchongBonusNoBtn"
NODE_BONUS_YES = "WuchongBonusYesBtn"
NODE_BONUS_NO_TPL = "WuchongBonusNoBtnTpl"
NODE_BONUS_YES_TPL = "WuchongBonusYesBtnTpl"
NODE_BONUS_NO_OCR = "WuchongBonusNoBtnOcr"
NODE_BONUS_YES_OCR = "WuchongBonusYesBtnOcr"

# --- P0-3 的节点名 ---------------------------------------------------------
#: ★**不存在**★：P0-3 未接线（:data:`NEW_BADGE_WIRED` 为 False）⇒ 没有节点引用
#: ``common/badge_new.png``。这里保留一个空元组，让守卫「按名字找引用」的写法一致。
NEW_BADGE_NODES: tuple[str, ...] = ()
