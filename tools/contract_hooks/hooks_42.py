# -*- coding: utf-8 -*-
"""#42：列表选行错位 → **静默打了别的成员**（请求 A、打开 B、还记成 A）——两个守卫。

seam：``agent/side_impl.py``（``detail_page_identity`` / ``verify_row_on_frame`` /
``SpecialBatchFightAction._row_click`` / ``SpecialBatchPlanRecognition`` 的错页分支）
+ ``assets/resource/pipeline/special_dungeon.json``（``SpecialEnterBoss`` 的选行动作、
``SpecialFightTargetRow``、``SpecialScrollList`` 的稳定等待）。

背景（真机实证：本票两个复现 + #36 的一次同形观察）
----------------------------------------------------
* r9：目标 ``伊劳德雷斯讨伐``（中级）→ 打开的却是 **碧之女王** 的详情页
  （帧 ``joss_r9/f_0070.jpg``：碧之女王高级/中级），这一局仍被账本记成 ``伊劳德雷斯讨伐``；
* C3：目标 ``水狂精灵兽``（中级）→ 打开的是 **圣夜的淘气鬼** 的详情页
  （帧 ``joss_C3/f_0010.jpg``：难度行 ``圣夜的雪像G中级``），同样记成 ``水狂精灵兽``；
* #36 早先也见过一次同形（请求 ``寄居蟹船长讨伐``、打开 ``诅咒弧魔艾基尔讨伐``），两种几何下
  都没复现 —— 那正是「只认难度行、不认成员」这套判据的盲区（**静默**的错误结果，比卡死更糟）。

根因（证据，不是猜）
--------------------
``SpecialEnterBoss`` 是「识别框 → 点击」两步，而 MAA 的点击发生在**识别那一帧之后**：
深行目标要滑动好几次才能看到，滑动后的列表还在收惯性时按识别框点下去，落点已经**不是目标行**
（r9 的那一帧：识别框停在目标行、点下去却打开了相邻的 ``碧之女王`` 的详情页），
而 ``special_target_fight`` 只认「难度行正则」（``中级$``）——**每个成员的详情页都有中级行**
→ 谁的页面都命中 → ``SpecialBatchFinishAction`` 直接按当前目标记一场账本。于是「打错成员」
被完整伪装成一次成功。本票的两道闸：

1. **选行点击复核**（``SpecialEnterBoss`` 走 ``special_batch_fight`` 的 ``row_click`` 分支）：
   点击前立刻重抓一帧、在列表体内复核目标行 —— 还在就用**新框**点（位移进日志），不在就**不点**；
2. **详情页身份校验**（``special_target_fight`` 的 ``member``）：读详情页横幅大标题、归属到
   「最像它的已知成员」，**不是目标成员就不命中**（绝不开打）；指挥官据此退回并重新导航，
   连续超限则把该目标记为**失败/跳过**并写明原因。

三个守卫（prove-red 也在本文件里）
----------------------------------
1. ``detail-identity-blocks-wrong-page`` —— 用**真机帧 OCR 逐条**（720 空间）驱动真正的
   ``SpecialTargetFightRecognition``：目标 A / 页面 B **必须被拒**（r9 的 伊劳德雷斯↔碧之女王、
   C3 的水狂↔圣夜的淘气鬼），页面就是目标的则必须命中；
2. ``row-click-reverifies-target-before-tap`` —— 驱动真正的 ``_row_click``：识别框已过期
   （列表还在动）时必须按**新框**点击、目标已移出屏时必须**不点**；
3. ``deep-row-tap-race-repro`` —— **离线复现**「深行多次滑动 + 收惯性时点行」：旧行为滑到
   **别人的**详情页、还记成目标；新行为命中目标自己的行；连续错页则由指挥官记为失败/跳过。
   同一守卫还断言指挥官在错页上**绝不 arm 开打**（``_BATCH_IN_FIGHT`` 恒 False → 不可能记账）。

★诚实边界★：真机帧的 OCR 逐条内嵌（与 hooks_35 同法），不重跑 MAA OCR；帧文件本身在
``%TEMP%\\opencode\\sweepjoss2\\frames\\{joss_r9,joss_C3}\\*.jpg``（帧在，供交叉核对；
``tools/test_row_selection.py`` 会在帧存在时 best-effort 重跑一遍真 OCR）。

prove-red（``python tools\\contract_hooks\\hooks_42.py``）：
* 关掉详情页身份闸（``detail_page_identity`` 直接返回 match）→ 守卫 1 与 3 红；
* 让选行点击信任陈旧识别框（不复核）→ 守卫 2 与 3 红。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"

# ---------------------------------------------------------------------------
# 真机帧 OCR 逐条（720 空间；与 OcrTask 的 (text, box, score) 同形）
# ---------------------------------------------------------------------------
# joss_r9 f_0070 = 碧之女王 详情页（难度行 碧之女王高级/中级；标题「碧之女王」@ y=214）。
BINU_PAGE = [
    ("NEW", [13, 385, 53, 25], 0.999946),
    ("COMPLETE!!", [15, 577, 125, 23], 0.999721),
    ("返回", [30, 1246, 46, 26], 0.999986),
    ("× 20", [41, 333, 62, 29], 0.875321),
    ("×0", [43, 264, 47, 29], 0.971196),
    ("×4", [43, 300, 47, 26], 0.977977),
    ("推荐编成", [56, 530, 96, 30], 0.999773),
    ("推荐编成", [56, 721, 96, 29], 0.999836),
    ("战斗", [82, 689, 38, 20], 0.999818),
    ("战斗", [87, 501, 30, 16], 0.999839),
    ("999/101", [112, 17, 94, 31], 0.999916),
    ("主城", [157, 1246, 44, 27], 0.999976),
    ("碧之女王高级", [199, 454, 178, 36], 0.999791),
    ("降临讨伐", [201, 428, 92, 28], 0.999388),
    ("降临讨伐", [201, 618, 92, 28], 0.999259),
    ("碧之女王中级", [203, 649, 171, 28], 0.999893),
    ("推荐属性火体力", [209, 533, 203, 27], 0.99994),
    ("推荐属性火", [209, 722, 156, 27], 0.999759),
    ("碧之女王", [251, 214, 213, 62], 0.99959),
    ("角色", [275, 1242, 47, 31], 0.999954),
    ("BOSS BATTLE", [284, 276, 151, 18], 0.989754),
    ("降临讨伐", [291, 182, 115, 35], 0.991757),
    ("体力", [363, 724, 48, 25], 0.999892),
    ("商店", [395, 1245, 47, 27], 0.999991),
    ("16", [447, 537, 28, 19], 0.999856),
    ("13", [447, 724, 32, 25], 0.999963),
    ("3,140,355", [509, 18, 95, 24], 0.999896),
    ("扭蛋", [516, 1245, 45, 27], 0.995519),
    ("首次报酬", [541, 429, 83, 27], 0.999965),
    ("x1", [590, 513, 25, 21], 0.419456),
    ("兑换道具", [615, 329, 81, 24], 0.999043),
    ("菜单", [636, 1246, 45, 27], 0.999718),
]

# joss_C3 f_0010 = 圣夜的淘气鬼 详情页（难度行 圣夜的雪像G中级；横幅标题 OCR 成「室淘气鬼」）。
SEIYA_PAGE = [
    ("NEW", [14, 385, 54, 25], 0.99994),
    ("M×0", [18, 289, 77, 37], 0.679519),
    ("返回", [30, 1246, 46, 26], 0.999986),
    ("K", [31, 332, 19, 18], 0.454262),
    ("×0", [42, 328, 53, 34], 0.940676),
    ("×0", [47, 257, 49, 29], 0.946941),
    ("推荐编成", [55, 530, 97, 30], 0.999792),
    ("室淘气鬼", [83, 166, 536, 252], 0.624203),
    ("战斗", [86, 498, 34, 20], 0.999722),
    ("999/101", [112, 17, 94, 31], 0.999919),
    ("XMAS EVENT", [148, 301, 83, 24], 0.992295),
    ("主城", [157, 1246, 44, 27], 0.999976),
    ("降临讨伐", [201, 428, 92, 28], 0.99945),
    ("圣夜的雪像G中级", [202, 457, 226, 32], 0.999855),
    ("推荐属性火体力", [209, 533, 203, 27], 0.999926),
    ("隆临讨伐", [240, 209, 109, 39], 0.92302),
    ("角色", [276, 1245, 45, 27], 0.999966),
    ("商店", [395, 1245, 47, 27], 0.999991),
    ("10", [447, 534, 28, 22], 0.999894),
    ("3,140,160", [512, 18, 94, 24], 0.999974),
    ("扭蛋", [516, 1245, 45, 27], 0.995519),
    ("首次报酬", [541, 429, 83, 27], 0.999965),
    ("×1", [590, 514, 29, 19], 0.967545),
    ("兑换道具", [615, 329, 79, 24], 0.999034),
    ("菜单", [636, 1246, 45, 27], 0.999718),
]

# joss_C3 f_0009 = 降临讨伐列表页（无「推荐编成」；顶部横幅那个「战斗」不是难度行）。
LIST_PAGE = [
    ("活动进行中", [11, 301, 169, 32], 0.99997),
    ("返回", [30, 1246, 46, 26], 0.999986),
    ("领主战", [135, 388, 90, 34], 0.999966),
    ("降临讨伐", [201, 488, 92, 28], 0.998895),
    ("圣夜的淘气鬼", [201, 660, 166, 32], 0.999832),
    ("怨炎精灵兽", [201, 804, 140, 33], 0.999259),
    ("水狂精灵兽", [201, 948, 140, 33], 0.999935),
    ("魁雷精灵兽", [201, 1092, 140, 33], 0.998392),
    ("战斗", [300, 176, 119, 58], 0.99975),
    ("更新列表", [614, 328, 84, 28], 0.999766),
]

# joss_r9 f_0050 = 降临讨伐列表页（真机 OCR 逐条；行名框实测 y=541/684/828/972/1117）。
ROW_LIST_PAGE = [
    ("活动进行中", [11, 301, 167, 32], 0.999948),
    ("NEW", [11, 778, 57, 30], 0.999921),
    ("返回", [30, 1246, 46, 26], 0.999986),
    ("领主战", [135, 388, 90, 34], 0.999966),
    ("主城", [156, 1246, 45, 27], 0.999962),
    ("降临讨伐", [201, 513, 91, 28], 0.998413),
    ("方舟守护者讨伐", [201, 541, 194, 32], 0.998888),
    ("赤之女王讨伐", [201, 684, 165, 32], 0.99943),
    ("青之女王讨伐", [201, 828, 165, 32], 0.999261),
    ("金之女王讨伐", [201, 972, 165, 32], 0.999273),
    ("碧之女王讨伐", [199, 1117, 167, 32], 0.997944),
    ("降临讨伐", [201, 388, 117, 33], 0.999517),
    ("更新列表", [614, 328, 84, 28], 0.999766),
    ("菜单", [636, 1246, 45, 27], 0.999718),
]

# 详情页「身份校验」的期望判定（目标成员 → (verdict, 期望战斗框或 None, 难度)）。
IDENTITY_CASES = [
    ("碧之女王页面/目标=碧之女王讨伐", BINU_PAGE, "碧之女王讨伐", "中级$", [82, 689, 38, 20]),
    ("碧之女王页面/目标=伊劳德雷斯讨伐（r9 缺陷）", BINU_PAGE, "伊劳德雷斯讨伐", "中级$", None),
    ("碧之女王页面/目标=青之女王讨伐（同后缀家族）", BINU_PAGE, "青之女王讨伐", "中级$", None),
    ("圣夜的淘气鬼页面/目标=圣夜的淘气鬼", SEIYA_PAGE, "圣夜的淘气鬼", "中级$", [86, 498, 34, 20]),
    ("圣夜的淘气鬼页面/目标=水狂精灵兽（C3 缺陷）", SEIYA_PAGE, "水狂精灵兽", "中级$", None),
    ("列表页/目标=水狂精灵兽", LIST_PAGE, "水狂精灵兽", "中级$", None),
]

# 选行点击复核的期望（fresh 帧；recognition box → (期望点击框, 是否该点)）。
ROW_CLICK_CASES = [
    # 列表仍在动：识别框停在「目标行往上 3 行」的位置，重抓帧里目标行还在 y=1117 → 必须点新框。
    ("陈旧识别框 → 按新框点", "碧之女王讨伐", [199, 820, 167, 32], [199, 1117, 167, 32]),
    # 目标行已移出屏 → 必须【不点】。
    ("目标移出屏 → 不点", "伊劳德雷斯讨伐", [199, 1117, 167, 32], None),
    # 稳定帧 → 新框 == 识别框。
    ("稳定帧 → 原框", "碧之女王讨伐", [199, 1117, 167, 32], [199, 1117, 167, 32]),
]

# 稳定等待下限（SpecialScrollList.post_delay，ms）：滑动后必须给列表留出收惯性的时间。
SETTLE_MIN_MS = 2200
# 手势时长下限（SpecialScrollList 的 Swipe duration，ms）：400px 行程的【受控拖拽】下限。
SWIPE_MIN_DURATION_MS = 700

# 深行复现：真机「降临讨伐」列表里 碧之女王 与 伊劳德雷斯 的相对位置
# （f_0050：碧之女王讨伐 @y=1117；sweep_joss_06：伊劳德雷斯讨伐 @y=782 一屏，二者之间还隔
#  伊尔格拉乌讨伐 —— 见 scene.lord_battle 的 #32 行扫注释）。
DEEP_ROWS = [
    "方舟守护者讨伐",
    "赤之女王讨伐",
    "青之女王讨伐",
    "金之女王讨伐",
    "碧之女王讨伐",
    "伊尔格拉乌讨伐",
    "伊劳德雷斯讨伐",
    "伊萨巴迪卡讨伐",
]
DEEP_TARGET = "伊劳德雷斯讨伐"
DEEP_WRONG = "碧之女王讨伐"      # 收惯性（内容下移 2 行）后停在目标旧位置的那一行
DEEP_WINDOW = 5
DEEP_STEP = 2                    # 每次受控滚动 2 行
DEEP_GLIDE = 2                   # 松手后的惯性/回弹：识别之后内容再下移 2 行


# ---------------------------------------------------------------------------
def _load_side_impl(agent_dir: Path | None = None):
    """导入 ``agent/side_impl``（可指定副本目录，供 prove-red）。"""
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _failures(si=None) -> list[str]:
    """#42 全部离线断言（纯函数 + 真机帧夹具 + 产物绑定）。空 = 绿。"""
    si = si or _load_side_impl()
    msgs: list[str] = []
    msgs += _identity_frame_failures(si)
    msgs += _row_click_failures(si)
    msgs += _deep_row_repro_failures(si)
    msgs += _pipeline_failures()
    return msgs


# ---------------------------------------------------------------------------
# 守卫 1：详情页身份校验（真机帧，离线可复算）
# ---------------------------------------------------------------------------
def _identity_frame_failures(si) -> list[str]:
    msgs: list[str] = []
    for name, items, member, difficulty, expect_box in IDENTITY_CASES:
        r = si.SpecialTargetFightRecognition().analyze(
            _FakeRecoContext(items),
            _FakeRecoArgv({"difficulty": difficulty, "pair": "below", "member": member}),
        )
        box = list(r.box) if r.box is not None else None
        if expect_box is None:
            if box is not None:
                msgs.append(
                    f"身份闸「{name}」：竟返回了战斗框 {box} —— 目标 A / 页面 B 必须被拒"
                    f"（否则会静默打错成员并记成 A；detail={getattr(r, 'detail', None)}）"
                )
        else:
            # 允许与实测框逐值相等（容忍 1px OCR 抖动）。
            if box is None or any(abs(a - b) > 1 for a, b in zip(box, expect_box)):
                msgs.append(
                    f"身份闸「{name}」：命中战斗框 {box} != 该页面目标难度行的实测框 {expect_box}"
                )
    # 纯函数层：归属必须能分开「同后缀家族」（青之女王 vs 碧之女王）。
    verdict, info = si.detail_page_identity(BINU_PAGE, "青之女王讨伐")
    if verdict != "mismatch":
        msgs.append(
            f"身份闸：碧之女王页面被判给「青之女王讨伐」（verdict={verdict} info={info}）—— "
            f"同后缀家族（之女王）必须靠「归属到最像的成员」分开"
        )
    return msgs


# ---------------------------------------------------------------------------
# 守卫 2：选行点击必须先复核（真机帧列表）
# ---------------------------------------------------------------------------
def _row_click_failures(si) -> list[str]:
    msgs: list[str] = []
    for name, member, rec_box, expect_click in ROW_CLICK_CASES:
        ctx = _FakeActionContext(ROW_LIST_PAGE)
        act = si.SpecialBatchFightAction()
        act.run(
            ctx,
            _FakeActionArgv(
                box=rec_box,
                param={"row_click": True, "member": member},
            ),
        )
        if expect_click is None:
            if ctx.clicked:
                msgs.append(
                    f"选行复核「{name}」：目标已不在重抓帧里，却仍点了 {ctx.clicked_point} —— "
                    f"绝不按陈旧坐标点别人的行"
                )
        else:
            want = (expect_click[0] + expect_click[2] / 2.0, expect_click[1] + expect_click[3] / 2.0)
            got = ctx.clicked_point
            if got is None:
                msgs.append(f"选行复核「{name}」：应当点击但一次都没点（ctx.clicks={ctx.clicks}）")
            elif abs(got[0] - want[0]) > 1.5 or abs(got[1] - want[1]) > 1.5:
                msgs.append(
                    f"选行复核「{name}」：点击到了 {got}，应为复核帧里的目标行中心 {want}"
                    f"（识别框 {rec_box}）"
                )
    # 纯函数层：列表体外的匹配（底导标签）不算行。
    outside = [("碧之女王讨伐", [199, 1240, 167, 32], 0.99)]
    got = si.verify_row_on_frame(outside, "碧之女王讨伐")
    if got is not None:
        msgs.append(f"选行复核：列表体（y<=1180）之外的匹配被当成了行：{got}")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 3：离线复现「深行多次滑动 + 收惯性时点行」
#
# 屏幕状态机（页面级，不臆造触摸物理）：列表 8 行、窗口 5 行、每次滚动 2 行；松手后还有
# DEEP_GLIDE 行的「收惯性」（内容下移）—— 关键：识别发生在**惯性结束之前**。
# 旧行为 = 直接按识别那一帧的框点击（落点已经错位 2 行）；新行为 = 点击前重抓一帧复核。
# ---------------------------------------------------------------------------
class _DeepRowSim:
    """深行场景：滚动 → 识别（惯性未结束）→ 点击（旧行为按陈旧框 / 新行为先复核）。

    模型（页面级，不臆造触摸物理）：
      · 列表 = ``DEEP_ROWS``（8 行），窗口 5 行；识别帧 offset=2（=滚动 1 次后目标可见）；
      · 松手后列表**回弹** ``DEEP_GLIDE`` 行 → 稳定帧 offset=0；识别发生在回弹**之前**；
      · 旧行为：按识别框的 y 点 → 落到稳定帧里**别人的行**上（这就是 r9 的错位）；
      · 新行为：点击前重抓稳定帧复核 → 目标已不在帧里 → **不点**；随后在稳定位置上
        重新滚动（此时列表已稳、无回弹）→ 第二次尝试命中目标自己的行。
    """

    TOPS = [470, 615, 760, 905, 1050]

    def __init__(self, si, *, reverify: bool):
        self.si = si
        self.reverify = reverify
        self.offset = 0
        self.opened = None
        self.clicked_box = None
        self.trace: list[str] = []

    def _items_at(self, offset: int):
        rows = DEEP_ROWS[offset:offset + DEEP_WINDOW]
        return [(name, [201, self.TOPS[i], 194, 32], 0.999) for i, name in enumerate(rows)]

    @staticmethod
    def _box_of(items, name):
        for text, box, _s in items:
            if text == name:
                return list(box)
        return None

    @staticmethod
    def _row_at(items, point):
        cy = point[1]
        for text, b, _s in items:
            if b[1] - 20 <= cy <= b[1] + b[3] + 20:
                return text
        return None

    def _click_via_action(self, frame_items, rec_box, target):
        """按**产品实现**（``SpecialBatchFightAction`` 的 row_click 分支）点一次。

        返回落点 (cx,cy)；``None`` = 产品拒绝点击（复核没过）。
        """
        ctx = _FakeActionContext(frame_items)
        self.si.SpecialBatchFightAction().run(
            ctx,
            _FakeActionArgv(box=rec_box, param={"row_click": True, "member": target}),
        )
        return ctx.clicked_point

    def _search(self, target) -> int | None:
        """受控滚动到目标可见，返回识别帧 offset（每步 2 行）。"""
        offset = 0
        while target not in [n for n, _b, _s in self._items_at(offset)]:
            nxt = min(offset + DEEP_STEP, len(DEEP_ROWS) - DEEP_WINDOW)
            if nxt == offset:
                return None
            offset = nxt
        return offset

    def run(self, target, *, glide: int) -> str | None:
        """返回打开的详情页所属行名（``None`` = 滚动也没露出目标）。"""
        rec_offset = self._search(target)
        if rec_offset is None:
            self.trace.append("滚动也没露出目标")
            return None
        rec_box = self._box_of(self._items_at(rec_offset), target)
        # 松手后的稳定位置（回弹）：
        settled_offset = max(0, rec_offset - glide)
        if self.reverify:
            point = self._click_via_action(self._items_at(settled_offset), rec_box, target)
            if point is None:
                self.trace.append(
                    f"识别帧 offset={rec_offset} 框={rec_box} → 复核帧 offset={settled_offset} "
                    f"里目标不在 → 产品拒绝点击（重新滑动）"
                )
                # 第二次尝试：列表已稳（无回弹），从稳定位置重新滚到目标
                rec2 = self._search(target)
                if rec2 is None:
                    self.trace.append("稳定后重新滚动仍找不到目标")
                    return None
                rec2_box = self._box_of(self._items_at(rec2), target)
                point = self._click_via_action(self._items_at(rec2), rec2_box, target)
                if point is None:
                    self.trace.append("稳定帧复核仍失败（不敢点）")
                    return None
                final_items = self._items_at(rec2)
                self.trace.append(f"稳定后重找：offset={rec2} 框={rec2_box} → 点目标自己的行")
            else:
                final_items = self._items_at(settled_offset)
                self.trace.append(f"复核帧里目标仍在 → 按新框点 {point}")
            self.clicked_point = point
            self.opened = self._row_at(final_items, point)
            return self.opened
        # 旧行为：直接按识别框点（惯性未结束）→ 落点是稳定帧里**别人的行**。
        self.clicked_point = (rec_box[0] + rec_box[2] / 2.0, rec_box[1] + rec_box[3] / 2.0)
        self.trace.append(f"旧行为：按识别框 {rec_box} 直接点（惯性未结束）")
        self.opened = self._row_at(self._items_at(settled_offset), self.clicked_point)
        return self.opened


def _deep_row_repro_failures(si) -> list[str]:
    msgs: list[str] = []
    old = _DeepRowSim(si, reverify=False)
    old_opened = old.run(DEEP_TARGET, glide=DEEP_GLIDE)
    if old_opened != DEEP_WRONG:
        msgs.append(
            f"深行复现（旧行为）：打开的是 {old_opened!r}，期望复现『滑到别人的行』"
            f"（{DEEP_WRONG!r}）—— 复现模型已与实现脱节；trace={old.trace}"
        )
    # 旧行为的「静默错记」就在这一步：账本无条件按**当前目标**（DEEP_TARGET）记一笔，
    # 而真正打开/打完的是 DEEP_WRONG —— 这正是 r9/C3 的记账错位。

    new = _DeepRowSim(si, reverify=True)
    new_opened = new.run(DEEP_TARGET, glide=DEEP_GLIDE)
    if new_opened != DEEP_TARGET:
        msgs.append(
            f"深行复现（新行为）：最终打开 {new_opened!r}，应为目标自己的行 {DEEP_TARGET!r}"
            f"；trace={new.trace}"
        )
    if new_opened == DEEP_WRONG:
        msgs.append("深行复现（新行为）：竟打开了别人的详情页（复核形同虚设）")

    # 关键不变量：**错页不得被记成目标** —— 由身份闸 + 指挥官错页分支保证。
    if si.detail_page_identity(BINU_PAGE, DEEP_TARGET)[0] != "mismatch":
        msgs.append("深行复现：碧之女王页面没有被判成「不是伊劳德雷斯」——身份闸失效")
    a1, _ = si.plan_wrong_detail_action(DEEP_TARGET, 1)
    a9, reason9 = si.plan_wrong_detail_action(DEEP_TARGET, si.WRONG_DETAIL_LIMIT + 1)
    if a1 != "back_out":
        msgs.append(f"错页处置：首次应为 back_out，实际 {a1!r}")
    if a9 != "skip" or "跳过" not in reason9:
        msgs.append(f"错页处置：超限应为 skip 且写明原因，实际 {a9!r}/{reason9!r}")
    return msgs


# ---------------------------------------------------------------------------
# 产物绑定：pipeline 里两道闸真的接上了
# ---------------------------------------------------------------------------
def _pipeline_failures(path: Path | None = None) -> list[str]:
    msgs: list[str] = []
    p = path or PIPELINE
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"读不到 {p}：{exc}"]
    stripped = "\n".join(
        line.split("//", 1)[0] if line.lstrip().startswith("//") else line
        for line in text.splitlines()
    )
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return [f"解析 special_dungeon.json 失败：{exc}"]

    row = data.get("SpecialEnterBoss") or {}
    action = row.get("action") or {}
    param = action.get("param") or {}
    if action.get("type") != "Custom" or param.get("custom_action") != "special_batch_fight":
        msgs.append(
            "产物绑定：SpecialEnterBoss 的 action 不是 custom special_batch_fight —— "
            "选行点击失去「点击前复核」（会按陈旧识别框点别人的行）"
        )
    if not (param.get("custom_action_param") or {}).get("row_click"):
        msgs.append(
            "产物绑定：SpecialEnterBoss 的 special_batch_fight 没有 row_click=true "
            "（会退化成普通开打点击：点别人的行 + 误 arm in_fight）"
        )
    nxt = row.get("next") or []
    if "SpecialFightTargetRow" not in nxt:
        msgs.append(f"产物绑定：SpecialEnterBoss.next 不再接详情页节点（{nxt[:4]}…）")

    fight = data.get("SpecialFightTargetRow") or {}
    frec = (fight.get("recognition") or {}).get("param") or {}
    if frec.get("custom_recognition") != "special_target_fight":
        msgs.append("产物绑定：SpecialFightTargetRow 不再是 custom special_target_fight")

    settle = (data.get("SpecialScrollList") or {}).get("post_delay")
    try:
        settle_ms = int(settle)
    except (TypeError, ValueError):
        settle_ms = -1
    if settle_ms < SETTLE_MIN_MS:
        msgs.append(
            f"产物绑定：SpecialScrollList.post_delay={settle!r} < {SETTLE_MIN_MS}ms —— "
            f"滑动后没给列表留出收惯性的时间（深行选行最容易在这里错位）"
        )

    # 手势必须是【受控拖拽】而不是「甩动」：真机实证（机型A/RANK158）里出现过
    # 「没经过选行节点、却打开了某个行的详情页」（抬手被读成一次点行）。行程已由 hooks_36
    # 把守；这里把住【时长】这一半（缓解，不是已证实的修复）。
    swipe_param = ((data.get("SpecialScrollList") or {}).get("action") or {}).get("param") or {}
    try:
        dur_ms = int(swipe_param.get("duration"))
    except (TypeError, ValueError):
        dur_ms = -1
    if dur_ms < SWIPE_MIN_DURATION_MS:
        msgs.append(
            f"产物绑定：SpecialScrollList 的 Swipe duration={swipe_param.get('duration')!r} < "
            f"{SWIPE_MIN_DURATION_MS}ms —— 400px 行程配这么短的时长是【甩动】，抬手容易被当成"
            f"「点行」（真机见过：无选行节点却打开了别人的详情页）"
        )
    return msgs


# ---------------------------------------------------------------------------
# 探针（聚合入口）
# ---------------------------------------------------------------------------
def probe_detail_identity_blocks_wrong_page() -> bool:
    """#42 守卫 1：真机帧上「目标 A / 页面 B」被拒，页面就是目标时命中。"""
    return _identity_frame_failures(_load_side_impl()) == []


def probe_row_click_reverifies_target() -> bool:
    """#42 守卫 2：选行点击按复核帧的新框点；目标不在帧里就不点。"""
    return _row_click_failures(_load_side_impl()) == []


def probe_deep_row_tap_race_repro() -> bool:
    """#42 守卫 3：离线复现深行收惯性错位 + 错页绝不被记成目标。"""
    return _deep_row_repro_failures(_load_side_impl()) == []


# ---------------------------------------------------------------------------
# 测试替身（把真机帧 OCR 回放给自定义识别/动作；不连设备、不点击）
# ---------------------------------------------------------------------------
class _OcrItem:
    def __init__(self, text, box, score):
        self.text = text
        self.box = list(box)
        self.score = score


class _OcrDetail:
    def __init__(self, items):
        self.hit = bool(items)
        self.all_results = [_OcrItem(t, b, s) for t, b, s in items]


class _FakeRecoContext:
    """把一帧的 OCR 结果回放给自定义识别器（run_recognition）。"""

    def __init__(self, items):
        self._items = items

    def run_recognition(self, entry, image):
        return _OcrDetail(self._items)

    def get_node_data(self, name):
        return {}

    def run_action(self, entry, box=None):
        return True


class _FakeRecoArgv:
    def __init__(self, param):
        self.image = None
        self.custom_recognition_param = json.dumps(param)


class _FakeController:
    def __init__(self, frame_items):
        self._frame = frame_items or []

    def post_screencap(self):
        outer = self

        class _Job:
            def wait(self):
                return self

            def get(self):
                return _OcrDetail(outer._frame)

        return _Job()


class _FakeTasker:
    def __init__(self, frame_items):
        self.controller = _FakeController(frame_items)


class _FakeActionContext:
    """选行点击的替身：重抓帧 = ``frame_items``；记录点击（720 空间的点）。"""

    def __init__(self, frame_items):
        self.tasker = _FakeTasker(frame_items)
        self.clicks: list = []
        self.clicked_point = None

    @property
    def clicked(self) -> bool:
        return self.clicked_point is not None

    def run_recognition(self, entry, image):
        return _OcrDetail(self.tasker.controller._frame)

    def get_node_data(self, name):
        return {}

    def run_action(self, entry, box=None):
        self.clicks.append((entry, box))
        if box is not None and len(box) == 4:
            # PubClick 传的是 (cx-1, cy-1, 2, 2) → 点 = (cx, cy)
            self.clicked_point = (box[0] + 1, box[1] + 1)
        return True


class _FakeActionArgv:
    def __init__(self, *, box, param):
        self.image = None
        self.box = box
        self.custom_action_param = json.dumps(param)
        self.node_name = "SpecialEnterBoss"


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_42.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_identity_gate(agent_dir: Path) -> None:
    """破坏：详情页身份闸永久返回 match（= 关掉闸门，谁的页面都能开打）。"""
    _sub(
        agent_dir / "side_impl.py",
        "    items3 = _as3(items)\n    on_detail = any(",
        '    items3 = _as3(items)\n    return "match", {"reason": "prove-red: gate off"}\n'
        "    on_detail = any(",
    )


def _break_row_verify(agent_dir: Path) -> None:
    """破坏：选行点击信任陈旧识别框（不重抓复核）。"""
    _sub(
        agent_dir / "side_impl.py",
        "        picked = verify_row_on_frame(fresh, re.escape(member), ref_box=rec_box)",
        "        picked = (list(rec_box), 0.0) if rec_box else None  # prove-red: trust stale",
    )


def _probe_in(agent_copy: Path) -> dict:
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑三个守卫，返回各守卫结果。"""
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import hooks_42\n"
        "si = hooks_42._load_side_impl(%r)\n"
        "res = {\n"
        "  'identity': hooks_42._identity_frame_failures(si) == [],\n"
        "  'row_click': hooks_42._row_click_failures(si) == [],\n"
        "  'deep_row': hooks_42._deep_row_repro_failures(si) == [],\n"
        "}\n"
        "print('PROBE_RESULT ' + json.dumps(res))\n" % (str(agent_copy),)
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral42_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        if line.startswith("PROBE_RESULT "):
            return json.loads(line[len("PROBE_RESULT "):])
    print(f"  （子进程没给出 PROBE_RESULT：{out.strip()[-400:]}）")
    return {}


def prove_red() -> bool:
    """真实绿；分别关掉身份闸 / 选行复核 -> 对应守卫各自变红。"""
    print("hooks_42 prove-red：分别破坏两道闸，要求守卫各自变红")
    green = (
        probe_detail_identity_blocks_wrong_page() is True
        and probe_row_click_reverifies_target() is True
        and probe_deep_row_tap_race_repro() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：身份闸 + 选行复核 + 深行复现（绿）")
    if not green:
        return False

    checks = [
        ("关掉详情页身份闸", _break_identity_gate, ("identity", "deep_row")),
        ("选行点击信任陈旧识别框", _break_row_verify, ("row_click", "deep_row")),
    ]
    ok = True
    for label, breaker, want_red in checks:
        tmp = Path(tempfile.mkdtemp(prefix="wf_hook42_"))
        try:
            shutil.copytree(AGENT_DIR, tmp / "agent")
            breaker(tmp / "agent")
            res = _probe_in(tmp / "agent")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for key in want_red:
            red = res.get(key) is False
            ok = ok and red
            detail = "" if not red else ""
            print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {key} {'红' if red else '仍绿'}{detail}")
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "detail-identity-blocks-wrong-page",
        "#42",
        "详情页身份校验：目标 A / 页面 B（真机帧：伊劳德雷斯↔碧之女王、水狂↔圣夜的淘气鬼）"
        "必须被拒；页面就是目标时命中（同后缀家族靠「归属到最像的成员」分开）",
        probe_detail_identity_blocks_wrong_page,
    ),
    (
        "row-click-reverifies-target-before-tap",
        "#42",
        "选行点击前立刻重抓一帧复核：识别框过期时按新框点，目标不在帧里就不点"
        "（绝不按陈旧坐标点别人的行）",
        probe_row_click_reverifies_target,
    ),
    (
        "deep-row-tap-race-repro",
        "#42",
        "离线复现：深行多次滑动 + 收惯性时点行 → 旧行为滑到别人的详情页并记成目标；"
        "新行为命中目标自己的行；错页连续超限记为失败/跳过（绝不静默）",
        probe_deep_row_tap_race_repro,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
