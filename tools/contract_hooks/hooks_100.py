# -*- coding: utf-8 -*-
"""#100：领主战「全难度解禁」的离线契约 —— 读数 · 规划 · 终结 · 防死循环 · 接线。

seam：``scene/lords_unlock.py``（**判定真源**：解析 / 规划 / 三条终结）
      ↔ ``scene/lords.py``（静态花名册：M + 解锁链；本票**只读**）
      ↔ ``agent/lords_impl.py``（OCR 胶水 + 「下一处点哪」+ **安装态冻结快照**）
      ↔ ``assets/resource/pipeline/lords.json``（页面流转）
      ↔ ``tools/live_harness.py`` / ``agent/my_*.py``（注册）。

八个挂点（+ 本票新增七个：页签 / 滚动 / 去重 / 导航快照 / 导航行为 / 两轮之间 / 节拍预算）
--------
1. ``lords-progress-parse``
   ``parse_progress`` 的**正反例**（真机原样 ``通关数3/4`` / ``通关数 3/4`` / 夹「全」的
   ``通关数 全5/5`` / 全角 / 分隔符抖动 / 歧义 ``3/4/5`` / 裸数字 / 三位数）逐条钉住，
   并钉住正则本身没被放宽成 ``(\\d+)/(\\d+)``。
2. ``lords-plan-round``
   ``plan_round`` 的正确性：**全部 M/M → 无目标**；``N<M`` + 完整链 → ``链[N]``；
   静态链未采集 → 目标带 ``difficulty=None`` + ``no_chain`` 问题（**不是静默跳过**）；
   ``N>M`` → **抛 LordsDataError**；行名不在花名册 → ``unknown_row``；M 对不上 → ``m_conflict``；
   **零行不算全通**。外加对 ``scene/lords.LORDS`` 的**全量扫描**（每个有完整链的领主，
   ``N`` 在 ``0..M-1`` 上都必须算出 ``链[N]`` 且 ``unlock_requires`` 恰是前缀）。
3. ``lords-stop-conditions``
   三条终结的**优先级与文案**：全 M/M（主）/ 连续 2 轮无新解锁 / 场次上限 60；
   以及「判了全通却零行读数」必须按**失败**收工（不许假收工）。
4. ``lords-no-deadloop``
   ★防死循环★：``played == 0`` 的任何状态都**必须** stop（零目标 / 计划了却没打成）。
   这一条是**反证式**的：穷举 ``planned`` 取值，只要有一个能返回「继续」就红。
5. ``lords-pipeline-wiring``
   ``lords.json`` 的形状：四个业务节点齐全、枢纽自环轮询、业务节点 ``on_error`` 回枢纽、
   ``lords_progress`` 两个 mode、动作是 ``lords_unlock_step``、``LordsStop`` 是 StopTask、
   **进列表的判据与 ROI 逐字等于** ``special_dungeon.json::SpecialOpenLord``、
   所有 ``next``/``on_error`` 引用都指得到真实节点、两个自定义名在 runner 注册表与本仓
   ``my_*.py`` 里都登记过、编队页【挑战】的判据 == ``scene/challenge.py`` 的真源形状。
6. ``lords-agent-offline``
   ``agent/lords_impl.py`` 的行为（**假 OCR + 假点击**，不碰设备）：
   读列表 → detail 带结构化的 name/n/m/box；点目标行 → 详情页点该档【战斗】→ 编队页点【挑战】
   并计一场；**点过挑战后禁双击**；**20s 点不出去 → override_next 到 LordsStop 带原因收工**；
   两条路（``scene/`` 真源 + 冻结快照）都不通时**不命中、不假成功**。
7. ``lords-install-snapshot-parity``
   ★安装态单源守卫（一）★：``agent/lords_impl.py`` 的**逐字冻结快照**与真源逐项相等 ——
   正则字符串 / ``{行名: M}`` / ``{行名: 解锁链}`` / 行名表 / 行名正则表 / 阈值 / ``PROBLEM_*``
   / 难度词表，外加 ``plan_round`` / ``should_stop`` / ``group_progress_rows`` /
   ``parse_progress`` / ``round_gained`` 的**行为表**（样例覆盖 no_chain / m_conflict /
   unknown_row / duplicate_row / played==0 / N>M 抛错）。
8. ``lords-install-behavior-parity``
   ★安装态单源守卫（二）★：把 ``scene.*`` 摘掉（= 真实安装态：``install/agent`` 没有 ``scene/``）
   之后**整条链照跑**：``_logic()`` 回落到快照、``_registry()``/``_row_regex()`` 用冻结表、
   识别**命中**、三跳点中心一致、点下【挑战】记一场；且与仓库态（有 ``scene/``）的结果**逐项相同**
   （含 detail 的 rows/targets/problems/行名容错）。

9. ``lords-tab-confirm``（#100 第 1 条真机缺口的离线部分）
   页签判据**逐字段等于** ``scene.page_rules``（领主战页签 / 降临讨伐页签）；
   **点击点 = 真机帧里标签框的中心**（``lord_page_tab_lord.png`` 的
   ``领主战 [202,582,135,52]`` / ``降临讨伐 [722,584,175,50]`` ÷1.5，与 ``SpecialTab*`` 的
   实测点 (180,405) / (540,404) 对账）；★切后**确认条件**只认行族身份证据★
   （两个标签**常驻同屏** ⇒ 「读得到标签」不算确认，那正是 #19 的自我欺骗）；
   切换**只许点 1 次**（失败不重试，跑满 12 次判决统计真正点了几次）+ 不确认必有界收工。
10. ``lords-scroll-latch``（#100 第 2 条真机缺口的离线部分）
   ★``lords.json`` **全文件不许出现 ``max_hit``**★（#50：命中级计数按任务共享，用尽即被
   框架**静默跳过** → 目标行永远滚不到）；时间闩 ≥1.2s（agent 侧有补睡与记账）；
   **到底判据**跑行为表（连续 2 个**滚动世代**「无新行 ∧ 位移 ≤4px」才算到底；同一世代重复读
   同一屏**不重复记账**、没真的滚过**不记账**——否则加载弹窗把扫描节点弹回来两帧就「到底」了）；
   每页上限用尽 → 明确要求「带原因收工」；手势几何（400px / 800ms / 严格竖直 /
   两端在列表体 440~1180）与 ``SCROLL_PLAN`` **逐字段相等**；手势节点不许进任何 ``next``。
11. ``lords-scroll-dedup``
   去重键 = ``(行名, N/M)``：重叠两屏只记一次、进度变化算新读数、累计无重复键，
   且去重后的 ``plan_round`` 不会把同一行打两遍（也不报 ``duplicate_row``）。
12. ``lords-nav-snapshot-parity``
   ★导航安装态单源★：``lords_impl`` 的导航冻结快照 == ``scene/lords_nav.py`` ——
   常量 / 页签锚点（判据 ROI 点击点）/ 滚动计划逐字段相等，且同一段剧本
   （到底 / 时间闩 / 切换与重试 / 拒绝 / 扫描推进）**行为逐项相同**。
13. ``lords-nav-agent-offline``
   导航 glue 的离线行为（假 OCR + 假时钟 + 假点击）：页扫描累计去重、切页签给**当帧标签框**
   且确认后不再点、滚动时间闩拒连甩、到底后推进页签、两个页签扫完把**整份读数**交给
   ``mode=read`` 判一轮（合成帧逐项复原核对；零行不判全通）；**下一轮重新武装**扫描。
14. ``lords-round-rearm``（★R1/R2 的守卫★）
    累计表按**行名**留**最新**读数（喂 ``1/4`` + ``2/4`` → 目标是「高级+」，**不是**已通关的
    「高级」）；``begin_round`` 每轮**重新武装**（复位 sweep + 清累计；否则第 2 轮
    ``desired_tab()`` 是 ``None`` ⇒ 不切页签、页签闸被跳过、``advance_tab`` 立刻说「两个都扫完」）；
    ``observe`` 的「连续 2 次」按**滚动世代**记账；``mode=read`` 的**扫描闸**（扫描阶段 +
    页签未确认 ⇒ **不按单帧规划**）。
15. ``lords-beat-budget``
    ``lords.json`` 的节拍预算：``timeout ≤ 3000ms``（#100 新增的 5 个导航节点必须显式声明）、
    ``post_delay ≤ 1000ms``（白名单：切页签 1200 / 战斗 HUD 2000 / 进列表 2500 /
    滚动 2600 == ``SCROLL_PLAN.settle_ms``，每条都写清「为什么这一等不能省」）。

★诚实边界★
* 本守卫**不碰设备**、**不重跑 MAA OCR**：假 OCR 用的是 ``tools/frames/`` 那几帧的**逐条读数**
  （720 空间，已 ÷1.5，见 :data:`LIST_FRAME` / :data:`TAB_FRAME_JOSS` / :data:`DETAIL_FRAME` /
  :data:`TEAM_FRAME`）。所以它证的是「**仓内实现 == 仓内那几张帧的读数**」，不是「今天真机还是这样」。
* 本守卫**不校验**「某账号能打哪几档」（那是账号状态，离线永远比不了）。
* 挂点 7/8/12 证的是「**快照 == 真源 + 行为等价**」，**不是**「安装包里的 ``install/agent`` 已经刷新」
  —— 后者由 ``tools/install.py`` 拷贝与真机验收负责（``tools/test_lords_install_state.py`` 另证
  「把 ``agent/`` 单独拷到没有 ``scene/`` 的目录仍可 import、可跑通」）。
* 页签 / 滚动的**真机标定**仍是下一张票：切页签后列表是否回到顶部、一屏几行、滚一次实际几行、
  列表底部有没有可用的尾部锚点（:data:`scene.lords_nav.END_ANCHORS` 现在是空的 = 不猜）。

prove-red（``python tools\\contract_hooks\\hooks_100.py``，25 条破坏实验，全部在内存里做）
----------------------------------------------------------------------------------------
① 把 ``parse_progress`` 放宽成裸 ``(\\d+)/(\\d+)`` → 反例命中 → 挂点 1 红；
② 把 ``plan_round`` 改成「一行也不规划、直接当全通」→ 挂点 2 红；
③ 把 ``should_stop`` 改成恒返回「继续」→ 挂点 3/4 红；
④ 把编队页【挑战】的快照改回旧形状（漏带箭头那半帧）→ 挂点 5 红；
⑤ 从 runner 注册表里摘掉 ``lords_progress`` / ``lords_unlock_step`` → 挂点 5 红；
⑥ 让「点过挑战」的闩失效（允许连点两次挑战）→ 挂点 6 红；
⑦ **快照漂移**：``_PROGRESS_RE_SNAPSHOT`` 放宽成裸 ``(\\d+)/(\\d+)`` → 挂点 7 红；
⑧ **快照漂移**：``_LORDS_M_SNAPSHOT`` 把妖狐讨伐的 M 改成 3 → 挂点 7 红；
⑨ **只改真源不改快照**：``scene/lords.LORDS`` 的妖狐讨伐链加一档 → 挂点 7 红；
⑩ **把安装态回落摘掉**（``_SnapshotLogic`` 打桩成 ``None``）→ 挂点 8 红；
⑪ **去掉时间闩**（``min_interval_sec`` 1.2 → 0.1）→ 挂点 10 红；
⑫ **去掉到底判据**（``observe`` 恒「未到底」）→ 挂点 10 红；
⑬ **允许 ``max_hit`` 当「滚几次」的上限**（临时副本上加回 ``"max_hit": 80``）→ 挂点 10 红；
⑭ **去掉页签确认**（有标签就算确认）→ 挂点 9 红；
⑮ **允许页签切换重试 3 次**（#19 竞速）→ 挂点 9 红；
⑯ **去重键退化成只有行名**（进度变化被吞）→ 挂点 11 红；
⑰ **导航快照漂移**：页签 ROI 改坏 → 挂点 12 红；
⑱ **导航快照漂移**：滚动时间闩改坏 → 挂点 12 红；
⑲ **导航 glue 被摘掉**（``mode=page`` 不再读行）→ 挂点 13 红；
⑳ **R1 回归**：累计表退回按 ``row_key`` 存多条（第 2 轮反复打刚打完的档）→ 挂点 14 红；
㉑ **R2 回归**：``begin_round`` 只做 ``reset_page``（第 2 轮一个页签都不切）→ 挂点 14 红；
㉒ **世代回归**：``note_scroll`` 不推进滚动世代（同一屏重读就能凑「到底」）→ 挂点 14 红；
㉓ **扫描闸回归**：``mode=read`` 绕过扫描闸（错页签的单帧也照常规划）→ 挂点 14 红；
㉔ **节拍回归**：``LordsScanPage.post_delay`` 写 4000 → 挂点 15 红；
㉕ **节拍回归**：删掉新增节点的一个 ``timeout``（节拍裸奔）→ 挂点 15 红。

"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile as _tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE_REL = Path("assets") / "resource" / "pipeline"
REF_PIPELINE_DIR = REPO_ROOT / PIPELINE_REL
LORDS_FILE = "lords.json"
OPEN_LORD_FILE = "special_dungeon.json"
OPEN_LORD_NODE = "SpecialOpenLord"

HOOK_ID_PARSE = "lords-progress-parse"
HOOK_ID_PLAN = "lords-plan-round"
HOOK_ID_STOP = "lords-stop-conditions"
HOOK_ID_DEADLOOP = "lords-no-deadloop"
HOOK_ID_WIRING = "lords-pipeline-wiring"
HOOK_ID_AGENT = "lords-agent-offline"
#: ★安装态单源守卫★：一）快照 == 真源（逐字/逐项/行为表）；二）摘掉 scene/ 后行为逐项等价。
HOOK_ID_INSTALL_SNAPSHOT = "lords-install-snapshot-parity"
HOOK_ID_INSTALL_BEHAVIOR = "lords-install-behavior-parity"
#: ★本票三条（页签切换 + 列表滚动）★
HOOK_ID_TAB = "lords-tab-confirm"
HOOK_ID_SCROLL = "lords-scroll-latch"
HOOK_ID_DEDUP = "lords-scroll-dedup"
#: 导航真源的安装态单源守卫（与挂点 7 同一纪律，管 ``scene/lords_nav.py`` 那一份快照）。
HOOK_ID_NAV_PARITY = "lords-nav-snapshot-parity"
#: 导航的 **agent 侧行为**（假 OCR + 假时钟 + 假点击，把两个页签扫一遍）。
HOOK_ID_NAV_AGENT = "lords-nav-agent-offline"
#: ★两轮之间★（R1 累计表按行名留最新 / R2 每轮重新武装 / mode=read 的扫描闸）。
HOOK_ID_ROUND = "lords-round-rearm"
#: ★lords 的节拍预算★（timeout ≤3000 / post_delay ≤1000，白名单逐条带理由）。
HOOK_ID_BEAT = "lords-beat-budget"

#: 必须存在的四个业务节点（本票点名交付的四个）+ 两个支撑节点（进列表 / 收工出口）。
REQUIRED_NODES: tuple[str, ...] = ("LordsEntry", "LordsReadProgress", "LordsPickTarget", "LordsAfterFight")
SUPPORT_NODES: tuple[str, ...] = ("LordsOpenList", "LordsStop")

#: 两个自定义名（注册表 / 我的 agent 注册都要有）。
RECO_NAME = "lords_progress"
ACTION_NAME = "lords_unlock_step"


# ---------------------------------------------------------------------------
# 惰性导入（与同目录其它 hooks 同一手法：挂点模块 import 期必须保持轻）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR), str(AGENT_DIR)):
        if path not in sys.path:
            sys.path.append(path)


def _module(name: str):
    _paths()
    return importlib.import_module(name)


def _lords_unlock():
    """``scene.lords_unlock``（**判定真源**）。"""
    return _module("scene.lords_unlock")


def _lords():
    return _module("scene.lords")


def _challenge():
    return _module("scene.challenge")


def _drift():
    return _module("scene.drift")


def _impl():
    """``agent/lords_impl``（OCR 胶水 + 点哪一下）。"""
    return _module("lords_impl")


def _harness():
    return _module("live_harness")


def _pipelines() -> dict:
    return _drift().load_pipelines(REPO_ROOT / PIPELINE_REL)


# ---------------------------------------------------------------------------
# 真机帧读数（720 空间；源 = tools/frames/*.png 的 OCR，1080 值 ÷1.5）
# ---------------------------------------------------------------------------
#: 列表页（``tools/frames/lord_page_tab_lord.png``，1080 → ÷1.5）。
#: 行名与进度的纵向错位 ≈48px 是真机的版式（不是随手编的），见 ``scene.lords_unlock.MAX_NAME_DY``。
LIST_FRAME: tuple = (
    ("领主战", [135, 388, 90, 35]),          # 页签（列表页上的「领主战」文字）
    ("降临讨伐", [481, 389, 117, 33]),        # 另一个页签
    ("更新列表", [615, 328, 82, 28]),          # 列表页判据
    ("艾基尔·嫉妒讨伐", [202, 640, 197, 28]), ("通关数1/4", [547, 688, 127, 28]),
    ("猩红巨熊讨伐", [201, 783, 164, 28]), ("通关数3/4", [547, 832, 126, 28]),
    ("八岐大蛇讨伐", [201, 1072, 165, 28]), ("通关数4/4", [547, 1120, 126, 28]),
)

#: 详情页（``tools/frames/lord_detail_multidiff.png`` 妖狐；降序 超级→高级+→高级→中级）。
DETAIL_FRAME: tuple = (
    ("推荐编成", [37, 353, 65, 20]),           # 详情页判据
    ("妖狐超级", [135, 305, 169, 19]), ("战斗", [58, 334, 21, 11]),
    ("妖狐高级+", [135, 433, 181, 19]), ("战斗", [60, 461, 18, 11]),
    ("妖狐高级", [135, 560, 169, 19]), ("战斗", [60, 591, 18, 11]),
    ("妖狐中级", [135, 687, 169, 19]), ("战斗", [60, 715, 18, 11]),
)

#: 单人编队页（``hooks_110.PAGE_READING_BOXES["solo_team"]`` 的真机框）。
TEAM_FRAME: tuple = (
    ("自动续战", [20, 1060, 80, 24]),          # A 类战前编队页独有标记
    ("挑战", [297, 1069, 80, 47]),
)

#: 降临讨伐页签帧（``tools/frames/lord_page_tab_joss.png``，1080 → ÷1.5）。
#: ★``五王连战`` 不是本 family 的成员（五重决战）⇒ 只进 ``unknown_rows``，不参与页签确认★。
TAB_FRAME_JOSS: tuple = (
    ("领主战", [135, 388, 90, 35]),
    ("降临讨伐", [481, 389, 117, 33]),
    ("更新列表", [615, 328, 82, 28]),
    ("五王连战", [201, 637, 115, 32]), ("通关数1/1", [547, 688, 123, 28]),
    ("无猾机兵", [201, 781, 114, 33]), ("通关数5/5", [547, 832, 127, 28]),
    ("红嫉机兵", [201, 925, 114, 33]), ("通关数4/4", [547, 976, 126, 28]),
    ("苍叹机兵", [201, 1069, 114, 33]), ("通关数4/4", [547, 1120, 126, 28]),
)

#: **真机帧里两个页签标签的原始读数**（1080 空间，逐字照抄
#: ``docs/research/lord-battle-difficulty-registry.md`` §2.1，score 0.9998 / 0.9997）。
#: ★本票的「点击点 = 当帧 OCR 框中心」就是拿它跟 ``SpecialTab*`` 的实测点对账的★：
#: ``[202,582,135,52]`` 中心 (269.5,608) ÷1.5 = (179.7,405.3) ≈ ``SpecialTabLord`` target (180,405)；
#: ``[722,584,175,50]`` 中心 (809.5,609) ÷1.5 = (539.7,406.0) ≈ ``SpecialTabJoss`` target (540,404)。
TAB_FRAME_1080: dict = {
    "领主战": (202, 582, 135, 52),
    "降临讨伐": (722, 584, 175, 50),
}

#: 页签节点 → 它的真机点击点（``special_dungeon.json::SpecialTab*`` 的 ``action.target``）。
TAB_PIPELINE_POINTS: dict = {"领主战": (180, 405), "降临讨伐": (540, 404)}
TAB_PIPELINE_NODES: dict = {"领主战": "SpecialTabLord", "降临讨伐": "SpecialTabJoss"}


# ---------------------------------------------------------------------------
# 假 context / 假 argv（离线跑 custom_recognition / custom_action，不碰设备）
# ---------------------------------------------------------------------------
class _FakeTaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class FakeContext:
    """只实现本模块用到的两件事：``override_next`` / ``run_action``（点击落在这里）。"""

    def __init__(self) -> None:
        self.overrides: list = []   # [(node_name, [next...])]
        self.actions: list = []     # [(action_name, box)]

    def override_next(self, node_name, next_list) -> None:  # noqa: D102
        self.overrides.append((node_name, list(next_list)))

    def run_action(self, action_name, box=None, **kwargs) -> bool:  # noqa: D102
        self.actions.append((action_name, box))
        return True

    # -- 断言辅助 ---------------------------------------------------------
    def clicked_centers(self) -> list:
        """把 ``PubClick`` 的 ``(cx-1, cy-1, 2, 2)`` 还原成点击中心。"""
        out = []
        for name, box in self.actions:
            if name != "PubClick" or not box or len(box) != 4:
                continue
            out.append((box[0] + 1, box[1] + 1))
        return out


class FakeArgv:
    """假 argv：识别用 ``image`` / ``custom_recognition_param``，动作用 ``box`` / ``custom_action_param``。"""

    def __init__(
        self,
        image=None,
        reco_param=None,
        act_param=None,
        box=None,
        node_name="LordsReadProgress",
        task_id=1,
    ) -> None:
        self.image = image
        self.custom_recognition_param = json.dumps(reco_param or {}, ensure_ascii=False)
        self.custom_action_param = json.dumps(act_param or {}, ensure_ascii=False)
        self.box = box
        self.node_name = node_name
        self.task_detail = _FakeTaskDetail(task_id)


class FakeOcr:
    """把 ``lords_impl._ocr`` 换成「永远返回这一帧」（或按队列依次返回几帧），收尾必定恢复。"""

    def __init__(self, frame=None, frames=None) -> None:
        self.queue = [list(one) for one in frames] if frames is not None else None
        self.frame = [tuple(item) for item in (frame or [])]

    def __enter__(self):
        impl = _impl()
        self.saved = impl._ocr
        impl.reset_sessions()
        impl._ocr = self._call
        return self

    def __exit__(self, *exc):
        impl = _impl()
        impl._ocr = self.saved
        impl.reset_sessions()
        return False

    def _call(self, context, image, entry="OcrTask"):
        if self.queue is not None:
            return list(self.queue.pop(0)) if self.queue else []
        return list(self.frame)


class FakeClock:
    """替换 ``lords_impl._now``（死线测试不必真等 20 秒）。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.saved = None

    def __enter__(self):
        impl = _impl()
        self.saved = impl._now
        impl._now = self
        return self

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __exit__(self, *exc):
        _impl()._now = self.saved
        return False


# ---------------------------------------------------------------------------
# 1. parse_progress 正反例
# ---------------------------------------------------------------------------
def _parse_failures(parse=None) -> list[str]:
    """``parse_progress`` 的正反例（``parse`` 可注入，破坏实验用）。"""
    lu = _lords_unlock()
    parse = lu.parse_progress if parse is None else parse
    msgs: list[str] = []

    positives = tuple(getattr(lu, "POSITIVE_CASES", ()) or ())
    rejected = tuple(getattr(lu, "REJECTED_CASES", ()) or ())
    if len(positives) < 5:
        msgs.append(f"POSITIVE_CASES 只剩 {len(positives)} 条 —— 反例集被删空就等于没守卫")
    if len(rejected) < 5:
        msgs.append(f"REJECTED_CASES 只剩 {len(rejected)} 条 —— 「拒收什么」必须写清")

    for text, n, m, why in positives:
        got = parse(text)
        if got != (n, m):
            msgs.append(f"正例 {text!r} 读成 {got!r}，应为 ({n},{m}) —— {why}")
    for text, why in rejected:
        got = parse(text)
        if got is not None:
            msgs.append(f"反例 {text!r} 被读成 {got!r}，必须拒收（返回 None）—— {why}")

    # 真机原样与「夹全」这两条是本票点名要求，单独钉一遍（防有人把它们从数据里删掉）
    for text, want in (("通关数 3/4", (3, 4)), ("通关数3/4", (3, 4)), ("通关数 全5/5", (5, 5))):
        got = parse(text)
        if got != want:
            msgs.append(f"点名正例 {text!r} 读成 {got!r}，应为 {want!r}")

    # 正则本身没被放宽：必须锚定标签、必须带「右界」断言（否则 3/4/5 会被读成 3/4）
    pattern = str(getattr(lu, "PROGRESS_RE", ""))
    if not pattern or "通" not in pattern:
        msgs.append("PROGRESS_RE 不见了或不再锚定「通关数」标签 —— 裸 (\\d+)/(\\d+) 会读进时间/分数")
    if "(?!" not in pattern:
        msgs.append(
            "PROGRESS_RE 没有右界否定断言 (?!...) —— `通关数 3/4/5` 这种**歧义读数**会被取前两段"
            f"（当前 {pattern!r}）"
        )
    return msgs


def probe_lords_progress_parse() -> bool:
    """#100：``parse_progress`` 的正例全读对、反例全拒收，且正则没被放宽。"""
    return _parse_failures() == []


# ---------------------------------------------------------------------------
# 2. plan_round
# ---------------------------------------------------------------------------
def _plan_failures(plan=None, registry=None) -> list[str]:
    """``plan_round`` 的正确性（``plan`` 可注入，破坏实验用）。"""
    lu = _lords_unlock()
    plan = lu.plan_round if plan is None else plan
    registry = _lords().LORDS if registry is None else registry
    msgs: list[str] = []

    def call(rows):
        return plan(rows, registry)

    # (a) 全部 M/M → 无目标 + all_done
    got = call([("八岐大蛇讨伐", 4, 4), ("无猾机兵", 5, 5)])
    if got.targets:
        msgs.append(f"全部 M/M 时仍给出目标 {got.pairs} —— 全通了就不该再打")
    if not got.all_done:
        msgs.append("全部 M/M 却没判 all_done —— 主终结条件失效")

    # (b) N<M + 完整链 → 链[N]（逐档递进）
    got = call([("妖狐讨伐", 1, 4)])
    if got.pairs != (("妖狐讨伐", "高级"),):
        msgs.append(
            f"妖狐讨伐 通关数1/4 应规划 (妖狐讨伐, 高级)（链[1]），实际 {got.pairs} —— "
            f"链 = {_lords().by_row_name('妖狐讨伐').tier_chain}"
        )
    if got.all_done:
        msgs.append("还有 N<M 的行却判了 all_done")

    # (c) 静态链未采集 → 仍给目标（difficulty=None）+ no_chain 问题（★不是静默跳过★）
    got = call([("艾基尔·嫉妒讨伐", 1, 4)])
    if got.pairs != (("艾基尔·嫉妒讨伐", None),):
        msgs.append(f"链未采集时应给 (行名, None) 的目标并报 no_chain，实际 {got.pairs}")
    if not any(p.kind == lu.PROBLEM_NO_CHAIN for p in got.problems):
        msgs.append("链未采集却没报 no_chain —— 「档位待定」被静默吞了")

    # (d) N>M 是脏数据 → 必须抛，不许静默跳过
    try:
        call([("妖狐讨伐", 4, 3)])
    except lu.LordsDataError:
        pass
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"N>M 抛的不是 LordsDataError 而是 {type(exc).__name__}：{exc}")
    else:
        msgs.append("通关数4/3（N>M 脏数据）被静默接受了 —— 必须抛 LordsDataError")

    # (e) 行名不在花名册 → unknown_row（不规划、也不当成不存在）
    got = call([("降临过伐", 1, 4)])
    if got.targets:
        msgs.append(f"花名册里没有的行仍被规划了：{got.pairs} —— 认错字去点行 = 点错人")
    if not any(p.kind == lu.PROBLEM_UNKNOWN_ROW for p in got.problems):
        msgs.append("花名册外的行没报 unknown_row（★静默跳过正是本仓最反感的形态★）")

    # (f) 列表页 M 与静态 M 冲突 → 不取档（宁可不打，不打错档）
    got = call([("妖狐讨伐", 1, 3)])
    if got.targets:
        msgs.append(f"M 对不上时仍取档 {got.pairs} —— 拿错的分母取档 = 打错档")
    if not any(p.kind == lu.PROBLEM_M_CONFLICT for p in got.problems):
        msgs.append("列表页 M=3 与静态 M=4 冲突却没报 m_conflict")

    # (g) 零行 ≠ 全通
    got = call([])
    if got.all_done:
        msgs.append("**零行读数**被判成 all_done —— 这是「假收工」的入口（一屏没读到就宣布全通）")
    if got.targets:
        msgs.append("零行读数却给出目标")

    # (h) 全量扫描：每个有完整链的领主，N 在 0..M-1 上都必须算出 链[N] 且前置恰为前缀
    sweep_bad: list[str] = []
    for entry in registry:
        chain = tuple(entry.tier_chain)
        if not chain or entry.max_tiers != len(chain):
            continue
        for n in range(len(chain)):
            one = plan([(entry.row_name, n, len(chain))], registry)
            want = (entry.row_name, chain[n])
            if one.pairs != (want,):
                sweep_bad.append(f"{entry.row_name} N={n} 应 {want} 实际 {one.pairs}")
                continue
            if len(entry.unlock_requires(chain[n])) != n:
                sweep_bad.append(f"{entry.row_name} 链[{n}]={chain[n]} 的前置数 != N")
    if sweep_bad:
        msgs.append("全量扫描失败：" + "；".join(sweep_bad[:4]))

    return msgs


def probe_lords_plan_round() -> bool:
    """#100：``plan_round`` 的 M/M、链[N]、脏数据、未知行、M 冲突、零行、全量扫描全对。"""
    return _plan_failures() == []


# ---------------------------------------------------------------------------
# 3. 三条终结条件
# ---------------------------------------------------------------------------
def _stop_failures(stop=None) -> list[str]:
    lu = _lords_unlock()
    stop = lu.should_stop if stop is None else stop
    msgs: list[str] = []
    S = lu.UnlockState

    # (a) 全 M/M（主）
    ok, reason = stop(S(all_done=True, rows_read=4, planned=0, played=1, sessions=3))
    if not ok:
        msgs.append("全 M/M 却没停 —— 主终结条件失效")
    elif "M/M" not in reason and "全部解禁" not in reason:
        msgs.append(f"全 M/M 的收工原因没说清「全解禁」：{reason!r}")

    # (a') 零行却判全通 → 照样停，但**不许**说成功
    ok, reason = stop(S(all_done=True, rows_read=0, sessions=0))
    if not ok:
        msgs.append("零行 + all_done 竟然不停")
    if "全部解禁" in reason:
        msgs.append(f"零行读数却宣布「全部解禁」—— 假收工：{reason!r}")

    # (b) 连续 2 轮无新解锁（兜底）
    ok, reason = stop(S(all_done=False, rows_read=4, planned=1, played=2, sessions=8, no_progress_rounds=2))
    if not ok:
        msgs.append("连续 2 轮无新解锁却没停 —— 兜底条件失效")
    elif "2" not in reason:
        msgs.append(f"原因里没有「连续 2 轮」这个量：{reason!r}")
    ok, _reason = stop(S(all_done=False, rows_read=4, planned=1, played=2, sessions=8, no_progress_rounds=1))
    if ok:
        msgs.append("只连续 1 轮无新解锁就停了 —— 提前收工会漏掉本该解锁的档")

    # (c) 场次上限 60（兜底，带原因）
    ok, reason = stop(S(all_done=False, rows_read=4, planned=2, played=2, sessions=60, no_progress_rounds=0))
    if not ok:
        msgs.append("场次到 60 却没停 —— 上限失效")
    elif "60" not in reason:
        msgs.append(f"原因里没有「60」这个上限值：{reason!r}")
    ok, _reason = stop(S(all_done=False, rows_read=4, planned=2, played=2, sessions=59, no_progress_rounds=0))
    if ok:
        msgs.append("场次 59 就停了 —— 上限比裁决值严")

    # (d) 正常的「还有得打」不许停
    ok, reason = stop(S(all_done=False, rows_read=4, planned=2, played=2, sessions=5, no_progress_rounds=0))
    if ok:
        msgs.append(f"正常推进中却收工了：{reason!r}")

    return msgs


def probe_lords_stop_conditions() -> bool:
    """#100：全 M/M（主）/ 连续 2 轮无新解锁 / 场次上限 60 三条终结都成立且带原因。"""
    return _stop_failures() == []


# ---------------------------------------------------------------------------
# 4. ★防死循环★（反证式）
# ---------------------------------------------------------------------------
def _deadloop_failures(stop=None) -> list[str]:
    """``played == 0`` 的任何状态都必须 stop —— 只要有一个能「继续」就红。"""
    lu = _lords_unlock()
    stop = lu.should_stop if stop is None else stop
    S = lu.UnlockState
    msgs: list[str] = []

    for planned in (0, 1, 3, 17):
        ok, reason = stop(
            S(all_done=False, rows_read=4, planned=planned, played=0, sessions=0, no_progress_rounds=0)
        )
        if not ok:
            msgs.append(
                f"本轮计划 {planned} 个目标、一场都没打，should_stop 却说「继续」—— "
                f"这正是死循环的准入条件（D6：每轮必须至少打一场才允许继续）"
            )
        elif not reason:
            msgs.append(f"计划 {planned} 个目标却零场：停了但没给原因")

    # 计划的语义必须真的被用到（planned==0 与 planned>0 的文案要不同，否则计划数没意义）
    _ok0, reason_zero = stop(S(all_done=False, rows_read=4, planned=0, played=0))
    _okp, reason_planned = stop(S(all_done=False, rows_read=4, planned=3, played=0))
    if reason_zero == reason_planned:
        msgs.append("零目标与「计划了却没打」用了同一句原因 —— 现场分不清是哪种卡住")

    # 反向：真的打了就不该被这条规则拦
    ok, _reason = stop(S(all_done=False, rows_read=4, planned=3, played=1, sessions=1, no_progress_rounds=0))
    if ok:
        msgs.append("本轮打了 1 场却仍被拦 —— 防死循环变成了「不许干活」")
    return msgs


def probe_lords_no_deadloop() -> bool:
    """#100：``played == 0`` 的任何状态都必须收工（零目标 / 计划了没打），并给不同原因。"""
    return _deadloop_failures() == []


# ---------------------------------------------------------------------------
# 5. pipeline 接线
# ---------------------------------------------------------------------------
def _refs(node: dict) -> list[str]:
    """节点里 ``next`` / ``on_error`` 引用的节点名（去掉 ``[JumpBack]`` 前缀）。"""
    out: list[str] = []
    for key in ("next", "on_error"):
        value = node.get(key)
        if isinstance(value, str):
            value = [value]
        for item in value or []:
            if not isinstance(item, str):
                continue
            name = item.replace("[JumpBack]", "").strip()
            if name and not name.startswith("["):
                out.append(name)
    return out


def _custom_names(data: dict) -> tuple[set, set]:
    """一个 pipeline 文件里引用的 ``custom_recognition`` / ``custom_action`` 名字。"""
    recos: set = set()
    actions: set = set()

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "custom_recognition" and isinstance(item, str):
                    recos.add(item)
                elif key == "custom_action" and isinstance(item, str):
                    actions.add(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return (recos, actions)


def _wiring_failures(
    files: dict | None = None,
    reco_registry: dict | None = None,
    action_registry: dict | None = None,
    challenge_patterns=None,
) -> list[str]:
    """``lords.json`` 的形状 + 注册 + 【挑战】判据单源（全部可注入，破坏实验用）。"""
    ch = _challenge()
    harness = _harness()
    files = _pipelines() if files is None else files
    reco_registry = dict(harness.CUSTOM_RECOGNITIONS) if reco_registry is None else dict(reco_registry)
    action_registry = dict(harness.CUSTOM_ACTIONS) if action_registry is None else dict(action_registry)
    challenge_patterns = (
        tuple(getattr(_impl(), "PAGE_CHALLENGE_PATTERNS", ()))
        if challenge_patterns is None
        else tuple(challenge_patterns)
    )
    msgs: list[str] = []

    data = files.get(LORDS_FILE)
    if not isinstance(data, dict):
        return [f"{LORDS_FILE} 不存在或不是对象 —— 解禁链的页面流转整个不见了"]

    # (a) 节点齐全
    for name in REQUIRED_NODES + SUPPORT_NODES:
        if not isinstance(data.get(name), dict):
            msgs.append(f"{LORDS_FILE} 缺节点 {name}（本票点名交付的四个业务节点 + 进列表/收工出口）")

    # (b) 枢纽：DirectHit + 自环轮询 + 四个业务节点都在它的 next 里
    hub = data.get("LordsEntry") or {}
    if str((hub.get("recognition") or {}).get("type")) != "DirectHit":
        msgs.append("LordsEntry 应是 DirectHit 枢纽（照 SpecialEntry），否则它会去抢业务节点的画面")
    hub_next = hub.get("next") or []
    if not hub_next or hub_next[-1] != "LordsEntry":
        msgs.append(
            f"LordsEntry.next 末项应是它自己（自环轮询 = 等待节点，post_delay 就是周期），"
            f"实际末项 {hub_next[-1] if hub_next else None!r}"
        )
    for name in ("LordsReadProgress", "LordsPickTarget", "LordsAfterFight", "LordsOpenList"):
        if name not in hub_next:
            msgs.append(f"LordsEntry.next 里没有 {name} —— 枢纽扫不到它，链路断开")
    if not any(str(item).startswith("[JumpBack]") for item in hub_next):
        msgs.append("LordsEntry.next 没有异常前缀（[JumpBack]Pub*）—— 弹窗/结算/失败页会把它挡住")

    # (c) 业务节点：next 末项回枢纽、on_error 回枢纽
    for name in REQUIRED_NODES[1:] + ("LordsOpenList",):
        node = data.get(name) or {}
        nxt = node.get("next") or []
        if not nxt or nxt[-1] != "LordsEntry":
            msgs.append(f"{name}.next 末项应回枢纽 LordsEntry，实际 {nxt[-1] if nxt else None!r}")
        if list(node.get("on_error") or []) != ["LordsEntry"]:
            msgs.append(f"{name}.on_error 必须回枢纽（ADR-0002 的自恢复边），实际 {node.get('on_error')!r}")

    # (d) 识别/动作接线
    read = (data.get("LordsReadProgress") or {}).get("recognition") or {}
    read_param = read.get("param") or {}
    if read_param.get("custom_recognition") != RECO_NAME:
        msgs.append(f"LordsReadProgress 的识别应是 {RECO_NAME}，实际 {read_param.get('custom_recognition')!r}")
    if str((read_param.get("custom_recognition_param") or {}).get("mode")) != "read":
        msgs.append("LordsReadProgress 的识别参数缺 mode=read")
    read_action = (data.get("LordsReadProgress") or {}).get("action") or {}
    if str(read_action.get("type")) != "DoNothing":
        msgs.append("LordsReadProgress 只读不点，action 必须是 DoNothing（点错页面的代价是打错档）")

    pick = data.get("LordsPickTarget") or {}
    pick_reco = (pick.get("recognition") or {}).get("param") or {}
    if pick_reco.get("custom_recognition") != RECO_NAME:
        msgs.append(f"LordsPickTarget 的识别应是 {RECO_NAME}（mode=pick），实际 {pick_reco.get('custom_recognition')!r}")
    if str((pick_reco.get("custom_recognition_param") or {}).get("mode")) != "pick":
        msgs.append("LordsPickTarget 的识别参数缺 mode=pick")
    pick_action = (pick.get("action") or {}).get("param") or {}
    if pick_action.get("custom_action") != ACTION_NAME:
        msgs.append(f"LordsPickTarget 的动作应是 {ACTION_NAME}，实际 {pick_action.get('custom_action')!r}")
    # ★点哪里必须来自当帧 OCR 框★：动作参数里不许出现写死的坐标
    blob = json.dumps(pick.get("action") or {}, ensure_ascii=False)
    if '"target"' in blob:
        msgs.append("LordsPickTarget 的动作里出现了写死坐标 target —— 坐标必须来自当帧 OCR 框（绝不猜）")

    stop_node = (data.get("LordsStop") or {}).get("action") or {}
    if str(stop_node.get("type")) != "StopTask":
        msgs.append(f"LordsStop 的 action 应是 StopTask（唯一的收工出口），实际 {stop_node.get('type')!r}")

    # (e) 进列表的判据/ROI 逐字等于 SpecialOpenLord（两个文件不许各写一份）
    mine = (data.get("LordsOpenList") or {}).get("recognition")
    theirs = ((files.get(OPEN_LORD_FILE) or {}).get(OPEN_LORD_NODE) or {}).get("recognition")
    if not isinstance(theirs, dict):
        msgs.append(f"找不到 {OPEN_LORD_FILE}::{OPEN_LORD_NODE} 的 recognition —— 无法证明判据一致")
    elif mine != theirs:
        msgs.append(
            f"LordsOpenList 的判据 {mine!r} 与 {OPEN_LORD_FILE}::{OPEN_LORD_NODE} 的 {theirs!r} 不一致 —— "
            f"「主城点领主战」只能有一份判据（ADR-0003），改一处必须改另一处"
        )

    # (f) 所有 next/on_error 引用都指得到真实节点（跨文件合并命名空间）
    known: set = set()
    for payload in files.values():
        if isinstance(payload, dict):
            known.update(payload.keys())
    for name, node in data.items():
        if not isinstance(node, dict):
            continue
        for ref in _refs(node):
            if ref not in known:
                msgs.append(f"{LORDS_FILE}::{name} 引用了不存在的节点 {ref!r}（拼错 = 走到就断链）")

    # (g) 两个自定义名在 runner 注册表 / 本仓 my_*.py 里都登记过
    if reco_registry.get(RECO_NAME) is None:
        msgs.append(f"live_harness.CUSTOM_RECOGNITIONS 缺 {RECO_NAME}（真机上会静默 no-op）")
    if action_registry.get(ACTION_NAME) is None:
        msgs.append(f"live_harness.CUSTOM_ACTIONS 缺 {ACTION_NAME}（真机上会静默 no-op）")
    # ★lords.json 只许引用**已注册**的 custom 名字★：新名字要同时改三处注册
    # （agent/my_reco.py / agent/my_action.py / tools/live_harness.py），本泳道不可改 →
    # 新能力一律用「既有名字 + 显式参数」（先例：special_batch_fight{row_click:true}，#20/#42）。
    used_recos, used_actions = _custom_names(data)
    for name in sorted(used_recos):
        if reco_registry.get(name) is None:
            msgs.append(
                f"{LORDS_FILE} 引用了未注册的 custom_recognition {name!r} —— 真机上会静默 no-op；"
                f"本泳道不改注册表，请用既有名字 + mode/do 参数（先例：#42 的 row_click）"
            )
    for name in sorted(used_actions):
        if action_registry.get(name) is None:
            msgs.append(
                f"{LORDS_FILE} 引用了未注册的 custom_action {name!r} —— 真机上会静默 no-op；"
                f"本泳道不改注册表，请用既有名字 + mode/do 参数（先例：#42 的 row_click）"
            )
    for rel, needle in (
        ("agent/my_reco.py", 'custom_recognition("' + RECO_NAME + '")'),
        ("agent/my_action.py", 'custom_action("' + ACTION_NAME + '")'),
    ):
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except OSError as exc:
            msgs.append(f"读不到 {rel}：{exc}")
            continue
        if needle not in text:
            msgs.append(f"{rel} 缺注册 `{needle}` —— pipeline 引用了没人实现的识别/动作")

    # (h) 编队页【挑战】判据单源：agent 快照 == scene/challenge 真源
    want = tuple(ch.CHALLENGE_CLICK_PATTERNS)
    if challenge_patterns != want:
        msgs.append(
            f"agent 侧【挑战】快照 {challenge_patterns!r} != 真源 scene.challenge.CHALLENGE_CLICK_PATTERNS "
            f"{want!r}（不同步 = 带箭头那一半帧点不中，约 8/17 帧）"
        )
    impl = _impl()
    for text in ("挑战", "挑战→"):
        if impl.find_challenge_box([(text, [297, 1069, 80, 47])]) is None:
            msgs.append(f"find_challenge_box 认不出真机读法 {text!r}")
    for text in ch.REJECTED_TEXTS:
        if impl.find_challenge_box([(text, [461, 1180, 120, 30])]) is not None:
            msgs.append(f"find_challenge_box 认了反例 {text!r} —— 会点到「再打一局/确认框」而不是开打")
    return msgs


def probe_lords_pipeline_wiring() -> bool:
    """#100：``lords.json`` 形状 + 注册 + 进列表判据一致性 + 【挑战】判据单源。"""
    return _wiring_failures() == []


# ---------------------------------------------------------------------------
# 6. agent 行为（假 OCR + 假点击）
# ---------------------------------------------------------------------------
def _agent_failures() -> list[str]:
    impl = _impl()
    lu = _lords_unlock()
    msgs: list[str] = []
    reco = impl.LordsProgressRecognition()
    action = impl.LordsUnlockAction()

    # (a) 读列表：结构化行列表（每行 name/n/m/box）
    with FakeOcr(frame=LIST_FRAME):
        ctx = FakeContext()
        res = reco.analyze(ctx, FakeArgv(reco_param={"mode": "read"}, task_id=101))
        detail = res.detail or {}
        if res.box is None:
            msgs.append(f"列表页帧没命中 read（{detail.get('reason')!r}）—— 读不到 N/M 就整条链停摆")
        rows = detail.get("rows") or []
        if len(rows) != 3:
            msgs.append(f"列表页帧应读出 3 行（艾基尔/猩红巨熊/八岐大蛇），实际 {len(rows)} 行：{rows}")
        by_name = {row["name"]: row for row in rows if isinstance(row, dict)}
        want = {"艾基尔·嫉妒讨伐": (1, 4), "猩红巨熊讨伐": (3, 4), "八岐大蛇讨伐": (4, 4)}
        for name, pair in want.items():
            got = by_name.get(name)
            if not got:
                msgs.append(f"detail.rows 里没有 {name!r}")
                continue
            if (got.get("n"), got.get("m")) != pair:
                msgs.append(f"{name} 读到 {(got.get('n'), got.get('m'))}，应为 {pair}")
            if not (got.get("name_box") and got.get("progress_box")):
                msgs.append(f"{name} 的 detail 里缺 box（现场复核要用它）")
        targets = [list(t) for t in (detail.get("targets") or [])]
        if ["八岐大蛇讨伐", None] in targets:
            msgs.append("八岐大蛇讨伐 已 4/4，不该出现在目标里")
        if detail.get("stop"):
            msgs.append(f"第一轮刚读完就判了收工（{detail.get('reason')!r}）—— 会当场退，一场都不打")
        if ctx.overrides:
            msgs.append(f"第一轮不该 override_next，实际 {ctx.overrides}")

    # ---- ★D6（本票 ①/②）：详情页逐档状态徽标 ⇒ 只点**未通关**的那一档 ----
    # 真机 484 第 3 轮验收（`debug/lords_accept4.log` 17:19–17:40）：`超级` NEW → COMPLETE!! SS
    # 后又解锁 `地狱级`，但旧实现 `difficulty=None` 时**盲取最上面那个战斗框**，而地狱级已
    # COMPLETE!! 却仍在最上 ⇒ 第 4/5/6 场全在重打已通关的档。下列帧 = 720 空间真机几何
    # （徽标在档名**上方 ≈70px**、行距 ≈128–190px；判据见 `scene/lords_nav.py` 第 7b 节）。
    #: 最上面那档已 COMPLETE!!（`妖狐超级`），未通关的 NEW 在第二行（`妖狐高级+`）。
    detail_status_top_complete = (
        ("推荐编成", [37, 353, 65, 20]),
        ("COMPLETE!!", [15, 235, 126, 22]),
        ("妖狐超级", [135, 305, 169, 19]), ("战斗", [58, 334, 21, 11]),
        ("NEW", [15, 363, 46, 20]),
        ("妖狐高级+", [135, 433, 181, 19]), ("战斗", [60, 461, 18, 11]),
        ("COMPLETE!!", [15, 490, 123, 24]),
        ("妖狐高级", [135, 560, 169, 19]), ("战斗", [60, 591, 18, 11]),
        ("COMPLETE!!", [15, 617, 127, 22]),
        ("妖狐中级", [135, 687, 169, 19]), ("战斗", [60, 715, 18, 11]),
    )
    #: 两档 NEW（超级在最上、高级+ 在第二行）—— 用来钉「显式指定的档优先」与
    #: 「显式档已 COMPLETE!! 时不点它」两种语义。
    detail_status_two_new = (
        ("推荐编成", [37, 353, 65, 20]),
        ("NEW", [15, 235, 46, 20]),
        ("妖狐超级", [135, 305, 169, 19]), ("战斗", [58, 334, 21, 11]),
        ("NEW", [15, 363, 46, 20]),
        ("妖狐高级+", [135, 433, 181, 19]), ("战斗", [60, 461, 18, 11]),
        ("COMPLETE!!", [15, 490, 123, 24]),
        ("妖狐高级", [135, 560, 169, 19]), ("战斗", [60, 591, 18, 11]),
        ("COMPLETE!!", [15, 617, 127, 22]),
        ("妖狐中级", [135, 687, 169, 19]), ("战斗", [60, 715, 18, 11]),
    )
    #: 全档 COMPLETE!! + 底部【返回】（该账号这一行可见档已清空 ⇒ 回列表换领主）。
    detail_status_all_complete = (
        ("推荐编成", [37, 353, 65, 20]),
        ("COMPLETE!!", [15, 235, 126, 22]),
        ("妖狐超级", [135, 305, 169, 19]), ("战斗", [58, 334, 21, 11]),
        ("COMPLETE!!", [15, 363, 123, 22]),
        ("妖狐高级+", [135, 433, 181, 19]), ("战斗", [60, 461, 18, 11]),
        ("COMPLETE!!", [15, 490, 123, 24]),
        ("妖狐高级", [135, 560, 169, 19]), ("战斗", [60, 591, 18, 11]),
        ("COMPLETE!!", [15, 617, 127, 22]),
        ("妖狐中级", [135, 687, 169, 19]), ("战斗", [60, 715, 18, 11]),
        ("返回", [30, 1246, 46, 26]),
    )

    # (b) 三跳：列表页点行 → 详情页点该档【战斗】→ 编队页点【挑战】并计一场
    #     帧序列 = 读列表 / 列表页选行 / 详情页选档 / 编队页点挑战（每次 pick 都重抓一帧）
    #     ★详情页帧改用带状态徽标的那一帧★：目标档未采集（difficulty=None）时选的是
    #     「从上往下第一个 NEW」= 超级（NEW），不是「最上面」碰巧也是超级的两回事。
    with FakeOcr(frames=[LIST_FRAME, LIST_FRAME, detail_status_two_new, TEAM_FRAME]):
        ctx = FakeContext()
        task = 102
        reco.analyze(ctx, FakeArgv(reco_param={"mode": "read"}, task_id=task))
        step_row = reco.analyze(
            ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget")
        )
        if step_row.box != [202, 640, 197, 28]:
            msgs.append(f"pick 应选目标行的行名框 [202,640,197,28]，实际 {step_row.box}")
        if (step_row.detail or {}).get("what") != impl.WHAT_ROW:
            msgs.append(f"第一跳应是 row，实际 {(step_row.detail or {}).get('what')!r}")
        if not action.run(ctx, FakeArgv(task_id=task, box=step_row.box)):
            msgs.append("点目标行的动作返回 False")
        step_tier = reco.analyze(
            ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget")
        )
        if (step_tier.detail or {}).get("what") != impl.WHAT_TIER:
            msgs.append(f"第二跳应是 tier（详情页【战斗】），实际 {(step_tier.detail or {}).get('what')!r}")
        if not action.run(ctx, FakeArgv(task_id=task, box=step_tier.box)):
            msgs.append("点【战斗】的动作返回 False")
        step_challenge = reco.analyze(
            ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget")
        )
        if (step_challenge.detail or {}).get("what") != impl.WHAT_CHALLENGE:
            msgs.append(f"第三跳应是 challenge（编队页【挑战】），实际 {(step_challenge.detail or {}).get('what')!r}")
        if not action.run(ctx, FakeArgv(task_id=task, box=step_challenge.box)):
            msgs.append("点【挑战】的动作返回 False")
        clicks = ctx.clicked_centers()
        if len(clicks) < 3:
            msgs.append(f"三跳应产生 3 次点击，实际 {len(clicks)} 次：{ctx.actions}")
        # 目标档未采集（艾基尔·嫉妒讨伐 的链未采集）⇒ 详情页取**第一个 NEW**（超级行）
        want_centers = [(300, 654), (68, 339), (337, 1092)]
        for got, want_center in zip(clicks[:3], want_centers):
            if abs(got[0] - want_center[0]) > 1 or abs(got[1] - want_center[1]) > 1:
                msgs.append(f"点击中心 {got} 与框中心 {want_center} 不符（框中心 = 点它就对了）")
        session = impl._session(task)
        if session.sessions_played != 1:
            msgs.append(f"点一次【挑战】应记 1 场，实际 {session.sessions_played} 场")
        if not session.challenge_pending:
            msgs.append("点过【挑战】后没置「禁双击」的闩 —— 会连着点两次挑战")

    # (c) ★禁双击★：点过【挑战】之后，停在同一个编队页再 pick 一次**不许**再给挑战框
    with FakeOcr(frame=TEAM_FRAME):
        ctx = FakeContext()
        task = 107
        session = impl._session(task)
        session.targets = [lu.Target("妖狐讨伐", None, 0, 4)]
        first = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        if (first.detail or {}).get("what") != impl.WHAT_CHALLENGE:
            msgs.append(f"编队页应选出【挑战】，实际 {(first.detail or {}).get('what')!r}")
        if not action.run(ctx, FakeArgv(task_id=task, box=first.box)):
            msgs.append("点【挑战】的动作返回 False")
        again = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        if again.box is not None:
            msgs.append(f"点过【挑战】后同一个编队页又给出可点框 {again.box} —— 会双击开打")

    # (d) ★20s 点不出去 → override_next 到 LordsStop + 带原因收工★
    with FakeOcr(frame=LIST_FRAME), FakeClock() as clock:
        ctx = FakeContext()
        task = 103
        reco.analyze(ctx, FakeArgv(reco_param={"mode": "read"}, task_id=task))       # 建立 last_click_at
        reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        clock.advance(impl.STUCK_SEC + 5)
        detail = reco.analyze(ctx, FakeArgv(reco_param={"mode": "read"}, task_id=task)).detail or {}
        if not detail.get("stop"):
            msgs.append(f"目标 {impl.STUCK_SEC:.0f}s 点不出去却没判收工（detail={detail.get('reason')!r}）")
        elif "点不出去" not in str(detail.get("reason")):
            msgs.append(f"收工原因没说清是「点不出去」：{detail.get('reason')!r}")
        if ("LordsReadProgress", [impl.STOP_NODE]) not in [(n, list(x)) for n, x in ctx.overrides]:
            msgs.append(f"没收工出口的 override_next 到 {impl.STOP_NODE}，实际 {ctx.overrides}")

    # (e) 全 M/M → 当场收工（主终结），且原因说「全部解禁」
    all_done_frame = [
        ("更新列表", [615, 328, 82, 28]),
        ("八岐大蛇讨伐", [201, 1072, 165, 28]), ("通关数4/4", [547, 1120, 126, 28]),
        ("猩红巨熊讨伐", [201, 783, 164, 28]), ("通关数4/4", [547, 832, 126, 28]),
    ]
    with FakeOcr(frame=all_done_frame):
        ctx = FakeContext()
        task = 104
        detail = reco.analyze(ctx, FakeArgv(reco_param={"mode": "read"}, task_id=task)).detail or {}
        if not detail.get("stop"):
            msgs.append("全 M/M 的列表页没有当场收工")
        elif "全部解禁" not in str(detail.get("reason")):
            msgs.append(f"全 M/M 的收工原因没写「全部解禁」：{detail.get('reason')!r}")

    # (f) 两条路（scene/ 真源 + 冻结快照）都不通 → 不命中、不假成功。
    #     ★正常安装态走的是快照回落（见挂点 8），这里证的是「连快照都拿不到时也不假成功」★。
    saved_logic = impl._logic
    try:
        impl._logic = lambda: None
        res = reco.analyze(FakeContext(), FakeArgv(reco_param={"mode": "read"}, task_id=105))
        if res.box is not None:
            msgs.append("判定真源与冻结快照都取不到时仍「命中」了 —— 会假成功")
        if impl.INSTALL_STATE_REASON not in str((res.detail or {}).get("reason")):
            msgs.append("真源与快照都不通时没说清原因（INSTALL_STATE_REASON）")
    finally:
        impl._logic = saved_logic

    # (g) ★D6：详情页逐档状态徽标 ⇒ 选未通关那一档（不按位置）★
    #     ★语义裁决（本票）★：显式难度（plan_round 给的 difficulty）**只在它那一档读到 NEW 时**
    #     优先；若屏幕显示它已 COMPLETE!!，**不点它**（改点从上往下第一个 NEW）——
    #     「已通关的档不再被点」是硬约束，计划是战前读数，屏幕才是这一帧的事实。
    import contextlib
    import io as _io

    # g1) 最上面那档已 COMPLETE!! ⇒ 选下面的 NEW，**不选**最上面
    with FakeOcr(frame=detail_status_top_complete):
        ctx = FakeContext()
        task = 106
        session = impl._session(task)
        session.targets = [lu.Target("妖狐讨伐", None, 1, 4)]
        step = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        if (step.detail or {}).get("what") != impl.WHAT_TIER:
            msgs.append(f"有徽标的详情页应选出 tier，实际 {(step.detail or {}).get('what')!r}")
        if step.box != [60, 461, 18, 11]:
            msgs.append(
                f"★最上面那档已 COMPLETE!! ⇒ 应选第二行 NEW（妖狐高级+）的【战斗】[60,461,18,11]，"
                f"实际 {step.box}"
            )
        if step.box == [58, 334, 21, 11]:
            msgs.append(
                "★盲取最上面那个战斗框（地狱级/超级已 COMPLETE!!）★ —— 这正是真机 484 第 4/5/6 "
                "场重打已通关档的形态"
            )

    # g2) 显式指定档是 NEW ⇒ 指定档优先（两档 NEW 时**不**取最上面的超级）
    with FakeOcr(frame=detail_status_two_new):
        ctx = FakeContext()
        task = 110
        session = impl._session(task)
        session.targets = [lu.Target("妖狐讨伐", "高级+", 1, 4)]
        step = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        if step.box != [60, 461, 18, 11]:
            msgs.append(
                f"显式目标档=高级+ 应点它那一行的【战斗】[60,461,18,11]（不是最上面的超级），实际 {step.box}"
            )

    # g3) 显式指定档已 COMPLETE!! ⇒ **不点它**，改点第一个 NEW（硬约束：已通关的档不再被点）
    with FakeOcr(frame=detail_status_two_new):
        ctx = FakeContext()
        task = 111
        session = impl._session(task)
        session.targets = [lu.Target("妖狐讨伐", "高级", 1, 4)]
        step = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        if step.box == [60, 591, 18, 11]:
            msgs.append("★显式目标档=高级 已 COMPLETE!! 却仍去点它★ —— 会重打已通关的档")
        if step.box != [58, 334, 21, 11]:
            msgs.append(f"显式档已 COMPLETE!! 时应改点第一个 NEW（超级 [58,334,21,11]），实际 {step.box}")

    # g4) 一档状态都读不到（现有 DETAIL_FRAME，**保持原样不加徽标**）⇒ 不点 + 日志可查
    buf = _io.StringIO()
    with FakeOcr(frame=DETAIL_FRAME), contextlib.redirect_stdout(buf):
        ctx = FakeContext()
        task = 108
        session = impl._session(task)
        session.targets = [lu.Target("妖狐讨伐", None, 0, 4)]
        step = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
    if step.box is not None:
        msgs.append(f"★读不到任何档状态却仍给出了可点框 {step.box}★ —— 绝不盲点（旧行为=取最上面）")
    if "读不到任何档状态" not in buf.getvalue():
        msgs.append(f"读不到档状态时日志没说清原因：{buf.getvalue()[-300:]!r}")

    # g5) 全档 COMPLETE!! ⇒ 不点任何档，产出【返回】步（回列表重读、关本轮）
    buf2 = _io.StringIO()
    with FakeOcr(frame=detail_status_all_complete), contextlib.redirect_stdout(buf2):
        ctx = FakeContext()
        task = 109
        session = impl._session(task)
        session.targets = [lu.Target("妖狐讨伐", None, 4, 4)]
        step = reco.analyze(ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
    if (step.detail or {}).get("what") != impl.WHAT_BACK:
        msgs.append(
            f"全档 COMPLETE!! 应产出【返回】步（what=back），实际 {(step.detail or {}).get('what')!r}"
        )
    if step.box != [30, 1246, 46, 26]:
        msgs.append(f"全档 COMPLETE!! 的【返回】框应是 [30,1246,46,26]（当帧 OCR 框），实际 {step.box}")
    if "回列表" not in buf2.getvalue():
        msgs.append(f"全档 COMPLETE!! 的日志没说「回列表重读」（现场分不清卡住还是换领主）：{buf2.getvalue()[-300:]!r}")


    impl.reset_sessions()
    return msgs


def probe_lords_agent_offline() -> bool:
    """#100：``lords_impl`` 的读/三跳/禁双击/死线/全通收工/两条路都断时不假成功，全部离线成立。"""
    return _agent_failures() == []


# ---------------------------------------------------------------------------
# 7. 安装态冻结快照：「快照 == 真源」（逐字 / 逐项 / 行为表）
# ---------------------------------------------------------------------------
#: ``plan_round`` 的行为样例（★点名覆盖 no_chain / m_conflict / unknown_row / duplicate_row /
#: N>M 抛错★）。样例表被删空或漏掉某个分支时，:func:`_coverage_failures` 会红。
SNAPSHOT_ROW_CASES: tuple = (
    ("正常：链[N]", [("妖狐讨伐", 1, 4)]),
    ("起始档：链[0]", [("妖狐讨伐", 0, 4)]),
    ("最后一档：链[3]", [("妖狐讨伐", 3, 4)]),
    ("已 M/M 的领主不产生目标", [("八岐大蛇讨伐", 4, 4), ("无猾机兵", 5, 5)]),
    ("no_chain：有 M 但链未采集", [("艾基尔·嫉妒讨伐", 1, 4)]),
    ("no_chain：pending 成员（M 也未采集）", [("管理者讨伐", 1, 4)]),
    ("m_conflict：列表页 M 与静态 M 对不上", [("妖狐讨伐", 1, 3)]),
    ("unknown_row：花名册外的行", [("降临过伐", 1, 4)]),
    ("duplicate_row：同一行两个读数", [("妖狐讨伐", 1, 4), ("妖狐讨伐", 2, 4)]),
    ("all_done", [("八岐大蛇讨伐", 4, 4)]),
    ("零行 ≠ 全通", []),
    ("映射输入", [{"name": "红嫉机兵", "n": 2, "m": 4}]),
    ("N>M：抛 LordsDataError", [("妖狐讨伐", 4, 3)]),
    ("M=0：抛 LordsDataError", [("妖狐讨伐", 1, 0)]),
)

#: ``should_stop`` 的行为样例（★点名覆盖 played==0 的两条分支★）。
SNAPSHOT_STOP_CASES: tuple = (
    ("全 M/M（主）", {"all_done": True, "rows_read": 4, "planned": 0, "played": 1, "sessions": 3}),
    ("零行却判全通（假收工）", {"all_done": True, "rows_read": 0, "sessions": 0}),
    ("场次上限 60", {"all_done": False, "rows_read": 4, "planned": 2, "played": 2, "sessions": 60}),
    ("上限差一场", {"all_done": False, "rows_read": 4, "planned": 2, "played": 2, "sessions": 59}),
    ("连续 2 轮无新解锁", {"all_done": False, "rows_read": 4, "planned": 1, "played": 2,
                          "sessions": 8, "no_progress_rounds": 2}),
    ("连续 1 轮不停", {"all_done": False, "rows_read": 4, "planned": 1, "played": 2,
                      "sessions": 8, "no_progress_rounds": 1}),
    ("played==0 且零目标", {"all_done": False, "rows_read": 4, "planned": 0, "played": 0}),
    ("played==0 且计划了没打", {"all_done": False, "rows_read": 4, "planned": 3, "played": 0}),
    ("正常推进", {"all_done": False, "rows_read": 4, "planned": 2, "played": 2, "sessions": 5}),
    ("全通优先于场次上限", {"all_done": True, "rows_read": 4, "planned": 0, "played": 1, "sessions": 60}),
)

#: ``group_progress_rows`` 的行为样例（真机帧 + 三种反例）。
SNAPSHOT_ITEM_CASES: tuple = (
    ("真机列表页帧", LIST_FRAME),
    ("读不出归属 → orphans", (("更新列表", [615, 328, 82, 28]), ("通关数1/1", [547, 688, 127, 28]))),
    ("徽标不抢行名", tuple(LIST_FRAME) + (("COMPLETE!!", [15, 1022, 124, 24]),)),
    ("纵向太远不配对", (("艾基尔·嫉妒讨伐", [202, 300, 197, 28]), ("通关数1/4", [547, 688, 127, 28]))),
    ("空帧", ()),
)

#: ``parse_progress`` 的行为样例（正例 + 反例 + 全角/抖动/歧义）。
SNAPSHOT_TEXT_CASES: tuple[str, ...] = (
    "通关数3/4",
    "通关数 3/4",
    "通关数 3 / 4",
    "通关数 全5/5",
    "通关数：4/4",
    "通关数３／４",
    "通关数1|4",
    "通关数 3/4/5",
    "通关数 3/",
    "角色数 3/4",
    "1234",
    "通关数 100/120",
    "通关数3/0",
    "通关数4/3",
    "",
)

#: ``round_gained`` 的行为样例（涨 / 不涨 / 首见 / 倒退）。
SNAPSHOT_GAINED_CASES: tuple = (
    ({"妖狐讨伐": 1, "猩红巨熊讨伐": 3}, [("妖狐讨伐", 2, 4), ("猩红巨熊讨伐", 3, 4)]),
    ({"妖狐讨伐": 2}, [("妖狐讨伐", 2, 4)]),
    (None, [("妖狐讨伐", 0, 4)]),
    ({"妖狐讨伐": 2}, [("妖狐讨伐", 1, 4)]),
)

#: 行为样例**必须**覆盖到的 problem kind（★表被删空 = 守卫瞎了，这一条先红★）。
REQUIRED_PROBLEM_KINDS: tuple[str, ...] = (
    "no_chain",
    "m_conflict",
    "unknown_row",
    "duplicate_row",
)

#: 行为样例**必须**覆盖到的收工文案片段（主终结 / 两条兜底 / 防死循环各一）。
REQUIRED_STOP_PHRASES: tuple[str, ...] = ("全部解禁", "场次上限", "连续", "防死循环")

#: 安装态回落必须存在的 ``scene.lords_unlock`` 同名面（少一个 = 安装态 AttributeError）。
SNAPSHOT_REQUIRED_SURFACE: tuple[str, ...] = (
    "parse_progress",
    "group_progress_rows",
    "round_gained",
    "plan_round",
    "should_stop",
    "RowReading",
    "Problem",
    "Target",
    "RoundPlan",
    "UnlockState",
    "LordsDataError",
    "PROBLEM_UNKNOWN_ROW",
    "PROBLEM_NO_CHAIN",
    "PROBLEM_M_CONFLICT",
    "PROBLEM_DUPLICATE",
    "SESSION_CAP",
    "IDLE_ROUND_LIMIT",
)


def _norm_plan(plan) -> tuple:
    """``plan_round`` 结果 → 纯数据（两种实现各自的 dataclass 都能被同一份归一化吃掉）。"""
    return (
        tuple((t.row_name, t.difficulty, t.n, t.m) for t in plan.targets),
        bool(plan.all_done),
        tuple((r.name, r.n, r.m, tuple(r.name_box), tuple(r.progress_box)) for r in plan.rows),
        tuple((p.kind, p.row_name, p.detail) for p in plan.problems),
        tuple(tuple(pair) for pair in plan.pairs),
        tuple(t.row_name for t in plan.needs_detail),
    )


def _norm_rows(result) -> tuple:
    """``group_progress_rows`` 结果 → 纯数据。"""
    rows, orphans = result
    return (
        tuple((r.name, r.n, r.m, tuple(r.name_box), tuple(r.progress_box)) for r in rows),
        tuple((text, tuple(box)) for text, box in orphans),
    )


def _outcome(fn, args, norm, error_cls):
    """跑一次判定：正常 → ``("OK", 归一化结果)``；抛 ``error_cls`` → ``("LordsDataError", 文案)``。

    ★按「角色」比而不是按类名比★：真源与快照各自有自己的 ``LordsDataError`` 子类
    （安装态没有 ``scene/``，不可能共用同一个类），但它们必须**在同一处抛、同一句话**。
    """
    try:
        value = fn(*args)
    except error_cls as exc:
        return ("LordsDataError", str(exc))
    except Exception as exc:  # noqa: BLE001 - 别的异常也是「行为不同」，必须点名
        return (f"EXC:{type(exc).__name__}", str(exc))
    return ("OK", norm(value) if norm is not None else value)


def _behavior_failures(truth_logic, truth_registry, snap_logic, snap_registry) -> list[str]:
    """同一批样例分别跑「真源」与「快照」，结果必须**逐项相等**（含抛错类别与文案）。"""
    msgs: list[str] = []

    for label, rows in SNAPSHOT_ROW_CASES:
        mine = _outcome(truth_logic.plan_round, (rows, truth_registry), _norm_plan,
                        truth_logic.LordsDataError)
        theirs = _outcome(snap_logic.plan_round, (rows, snap_registry), _norm_plan,
                          snap_logic.LordsDataError)
        if mine != theirs:
            msgs.append(
                f"plan_round 样例『{label}』快照与真源不一致：真源 {mine!r} / 快照 {theirs!r}"
            )

    for label, kwargs in SNAPSHOT_STOP_CASES:
        mine = tuple(truth_logic.should_stop(truth_logic.UnlockState(**kwargs)))
        theirs = tuple(snap_logic.should_stop(snap_logic.UnlockState(**kwargs)))
        if mine != theirs:
            msgs.append(
                f"should_stop 样例『{label}』快照与真源不一致（含原因文案）："
                f"真源 {mine!r} / 快照 {theirs!r}"
            )

    for label, items in SNAPSHOT_ITEM_CASES:
        mine = _norm_rows(truth_logic.group_progress_rows(items))
        theirs = _norm_rows(snap_logic.group_progress_rows(items))
        if mine != theirs:
            msgs.append(
                f"group_progress_rows 样例『{label}』快照与真源不一致：真源 {mine!r} / 快照 {theirs!r}"
            )

    for text in SNAPSHOT_TEXT_CASES:
        mine = truth_logic.parse_progress(text)
        theirs = snap_logic.parse_progress(text)
        if mine != theirs:
            msgs.append(f"parse_progress({text!r}) 快照 {theirs!r} != 真源 {mine!r}")

    for previous, rows in SNAPSHOT_GAINED_CASES:
        mine_raw = truth_logic.round_gained(previous, rows)
        theirs_raw = snap_logic.round_gained(previous, rows)
        mine = (bool(mine_raw[0]), tuple(mine_raw[1]))
        theirs = (bool(theirs_raw[0]), tuple(theirs_raw[1]))
        if mine != theirs:
            msgs.append(f"round_gained({previous!r}, {rows!r}) 快照 {theirs!r} != 真源 {mine!r}")

    return msgs


def _coverage_failures(truth_logic, truth_registry) -> list[str]:
    """样例表必须**真的**走到点名分支（表被删空 / 漏一支，守卫就瞎了 —— 先红）。"""
    msgs: list[str] = []
    kinds: set = set()
    raised = 0
    for _label, rows in SNAPSHOT_ROW_CASES:
        try:
            plan = truth_logic.plan_round(rows, truth_registry)
        except truth_logic.LordsDataError:
            raised += 1
            continue
        kinds.update(problem.kind for problem in plan.problems)
    for kind in REQUIRED_PROBLEM_KINDS:
        if kind not in kinds:
            msgs.append(f"行为样例没覆盖 problem.kind={kind!r} —— 删掉样例等于删掉守卫（现有 {sorted(kinds)}）")
    if raised < 1:
        msgs.append("行为样例没有一条触发 LordsDataError —— 脏数据分支（N>M / M=0）没被证")

    reasons = [truth_logic.should_stop(truth_logic.UnlockState(**kwargs))[1]
               for _label, kwargs in SNAPSHOT_STOP_CASES]
    for phrase in REQUIRED_STOP_PHRASES:
        if not any(phrase in reason for reason in reasons):
            msgs.append(f"行为样例没有一条收工原因含 {phrase!r} —— 该终结分支没被证（现 {reasons}）")
    return msgs


def _snapshot_parity_failures(impl=None) -> list[str]:
    """★安装态单源守卫（一）★：``agent/lords_impl.py`` 的冻结快照 == 真源（逐字/逐项/行为）。"""
    impl = _impl() if impl is None else impl
    lu = _lords_unlock()
    lords = _lords()
    cfg = _module("scene.config")
    msgs: list[str] = []

    # (0) 回落替身本身必须在场（它没了 = 安装态整条回落消失）
    snap = getattr(impl, "_SnapshotLogic", None)
    snap_registry = getattr(impl, "_SNAPSHOT_REGISTRY", None)
    if snap is None or snap_registry is None:
        return [
            "agent/lords_impl 缺 _SnapshotLogic / _SNAPSHOT_REGISTRY —— 安装态没有判定真源替身"
            "（没有 scene/ 时会重新变成「识别不命中」）"
        ]

    # (a) 解析正则：**逐字**（放宽一个字符就红）+ 编译产物与字符串一致
    want_re = str(getattr(lu, "PROGRESS_RE", ""))
    got_re = str(getattr(impl, "_PROGRESS_RE_SNAPSHOT", ""))
    if not got_re:
        msgs.append("agent/lords_impl._PROGRESS_RE_SNAPSHOT 不见了 —— 安装态没有解析正则")
    elif got_re != want_re:
        msgs.append(
            f"_PROGRESS_RE_SNAPSHOT 与真源 scene.lords_unlock.PROGRESS_RE 不一致：\n"
            f"      快照 {got_re!r}\n      真源 {want_re!r}"
        )
    compiled = getattr(impl, "_PROGRESS_RES_SNAPSHOT", None)
    if compiled is None or str(getattr(compiled, "pattern", "")) != got_re:
        msgs.append("_PROGRESS_RES_SNAPSHOT 不是 _PROGRESS_RE_SNAPSHOT 编译出来的（改了一边忘了另一边）")

    # (b) M 表：{行名: M} 逐项（只收有证据的 M；其余按 None，等价于真源的 max_tiers=None）
    want_m = {e.row_name: e.max_tiers for e in lords.LORDS if e.max_tiers is not None}
    got_m = dict(getattr(impl, "_LORDS_M_SNAPSHOT", {}) or {})
    if got_m != want_m:
        msgs.append(
            f"_LORDS_M_SNAPSHOT 与 scene/lords.py 的 {{行名: max_tiers}} 不一致：\n"
            f"      多/不同 {sorted(set(got_m.items()) - set(want_m.items()))}\n"
            f"      缺 {sorted(set(want_m.items()) - set(got_m.items()))}"
        )

    # (c) 链表：{行名: 解锁链} 逐项（只收已验证的完整链；其余 = ()）
    want_chain = {e.row_name: tuple(e.tier_chain) for e in lords.LORDS if e.tier_chain}
    got_chain = {k: tuple(v) for k, v in (getattr(impl, "_LORDS_CHAIN_SNAPSHOT", {}) or {}).items()}
    if got_chain != want_chain:
        msgs.append(
            f"_LORDS_CHAIN_SNAPSHOT 与 scene/lords.py 的 {{行名: tier_chain}} 不一致："
            f"快照 {got_chain!r} / 真源 {want_chain!r}"
        )

    # (d) 行名表：成员身份必须齐（少了 = 安装态把已知行报成 unknown_row）
    want_rows = tuple(e.row_name for e in lords.LORDS)
    got_rows = tuple(getattr(impl, "_LORDS_ROWS_SNAPSHOT", ()) or ())
    if got_rows != want_rows:
        msgs.append(
            f"_LORDS_ROWS_SNAPSHOT 与 scene/lords.py 的 LORDS 行名表不一致："
            f"缺 {sorted(set(want_rows) - set(got_rows))} / 多 {sorted(set(got_rows) - set(want_rows))}"
            f"（顺序也要一致；共 {len(want_rows)} 位）"
        )

    # (e) 行名容错正则：逐行对账（表里缺省 = ^{行名}$，与真源 pending() 同形）
    want_regex = {e.row_name: e.row_regex for e in lords.LORDS}
    got_regex = {
        name: (getattr(impl, "_LORDS_ROW_REGEX_SNAPSHOT", {}) or {}).get(name) or "^" + name + "$"
        for name in want_regex
    }
    stale = set((getattr(impl, "_LORDS_ROW_REGEX_SNAPSHOT", {}) or {})) - set(want_regex)
    if got_regex != want_regex or stale:
        diff = {k: (want_regex[k], got_regex.get(k)) for k in want_regex if got_regex.get(k) != want_regex[k]}
        msgs.append(
            f"_LORDS_ROW_REGEX_SNAPSHOT 与 scene/lords.py 的 {{行名: row_regex}} 不一致："
            f"不同 {diff!r} / 花名册外 {sorted(stale)}"
        )

    # (f) 阈值 / kind / 难度词表
    for name, want in (
        ("SESSION_CAP", getattr(lu, "SESSION_CAP", None)),
        ("IDLE_ROUND_LIMIT", getattr(lu, "IDLE_ROUND_LIMIT", None)),
        ("MAX_NAME_DY", getattr(lu, "MAX_NAME_DY", None)),
        ("MIN_NAME_LEFT_GAP", getattr(lu, "MIN_NAME_LEFT_GAP", None)),
        ("NOT_A_ROW_NAME", tuple(getattr(lu, "NOT_A_ROW_NAME", ()) or ())),
    ):
        got = getattr(snap, name, None)
        if got != want:
            msgs.append(f"快照 {name} = {got!r} != 真源 {want!r}")
    for name in ("PROBLEM_UNKNOWN_ROW", "PROBLEM_NO_CHAIN", "PROBLEM_M_CONFLICT", "PROBLEM_DUPLICATE"):
        got = getattr(snap, name, None)
        want = getattr(lu, name, None)
        if got != want:
            msgs.append(f"快照 {name} = {got!r} != 真源 {want!r}")
    want_diff = tuple(getattr(cfg, "DIFFICULTIES", ()) or ())
    got_diff = tuple(getattr(impl, "_DIFFICULTIES_SNAPSHOT", ()) or ())
    if got_diff != want_diff:
        msgs.append(f"_DIFFICULTIES_SNAPSHOT = {got_diff!r} != scene.config.DIFFICULTIES {want_diff!r}")

    # (g) 同名的面必须齐（少一个 = 安装态 AttributeError）
    for name in SNAPSHOT_REQUIRED_SURFACE:
        if not hasattr(snap, name):
            msgs.append(f"快照面缺 {name} —— 安装态会 AttributeError（scene.lords_unlock 有它）")

    # (h) 行为表：同一批样例，真源 vs 快照逐项相等
    msgs.extend(_behavior_failures(lu, tuple(lords.LORDS), snap, snap_registry))

    # (i) 覆盖率自检（表被删空 = 守卫瞎了）
    msgs.extend(_coverage_failures(lu, tuple(lords.LORDS)))
    return msgs


def probe_lords_install_snapshot_parity() -> bool:
    """#100：安装态冻结快照逐字/逐项等于 ``scene/lords_unlock.py`` + ``scene/lords.py``。"""
    return _snapshot_parity_failures() == []


# ---------------------------------------------------------------------------
# 8. 安装态行为等价（把 scene/ 摘掉，整条链照跑）
# ---------------------------------------------------------------------------
def _run_agent_flow(impl, task_id: int) -> dict:
    """跑一遍「读列表 → 三跳」，返回**可比较**的观测（假 OCR + 假点击，不碰设备）。"""
    reco = impl.LordsProgressRecognition()
    action = impl.LordsUnlockAction()
    with FakeOcr(frames=[LIST_FRAME, LIST_FRAME, DETAIL_FRAME, TEAM_FRAME]), FakeClock():
        ctx = FakeContext()
        read = reco.analyze(ctx, FakeArgv(reco_param={"mode": "read"}, task_id=task_id))
        detail = read.detail or {}
        picks = []
        for _hop in range(3):
            step = reco.analyze(
                ctx,
                FakeArgv(reco_param={"mode": "pick"}, task_id=task_id, node_name="LordsPickTarget"),
            )
            ok = action.run(ctx, FakeArgv(task_id=task_id, box=step.box))
            picks.append(((step.detail or {}).get("what"), tuple(step.box or ()), bool(ok)))
        session = impl._session(task_id)
        return {
            "read_box": tuple(read.box or ()),
            "rows": tuple((r["name"], r["n"], r["m"]) for r in detail.get("rows") or []),
            "targets": tuple(tuple(t) for t in detail.get("targets") or []),
            "problems": tuple((p[0], p[1]) for p in detail.get("problems") or []),
            "stop": bool(detail.get("stop")),
            "reason": detail.get("reason"),
            "picks": tuple(picks),
            "clicks": tuple(ctx.clicked_centers()),
            "overrides": tuple((name, tuple(nxt)) for name, nxt in ctx.overrides),
            "sessions_played": session.sessions_played,
            "challenge_pending": session.challenge_pending,
            "round": session.round_index,
        }


def _fuzzy_pick_observation(impl, task_id: int) -> dict:
    """行名容错：目标行名干净、当帧被 OCR 读成「红嫉族机兵」—— 冻结的 ``^红嫉族?机兵$`` 也得认。"""
    reco = impl.LordsProgressRecognition()
    frame = (
        ("降临讨伐", [481, 389, 117, 33]),
        ("红嫉族机兵", [201, 783, 164, 28]),
        ("通关数2/4", [547, 832, 126, 28]),
    )
    with FakeOcr(frame=frame):
        ctx = FakeContext()
        session = impl._session(task_id)
        session.targets = [impl._logic().Target("红嫉机兵", "中级", 2, 4)]
        step = reco.analyze(
            ctx, FakeArgv(reco_param={"mode": "pick"}, task_id=task_id, node_name="LordsPickTarget")
        )
        return {
            "what": (step.detail or {}).get("what"),
            "box": tuple(step.box or ()),
            "row_regex": impl._row_regex("红嫉机兵"),
        }


def _install_behavior_failures() -> list[str]:
    """★安装态单源守卫（二）★：没有 ``scene/`` 时**行为与仓库态逐项相同**（识别命中、动作照做）。"""
    impl = _impl()
    lu = _lords_unlock()
    lords = _lords()
    msgs: list[str] = []

    # 模拟安装态要靠这两个入口（它们被改名/删掉 = 回落机制被改坏了，先红）
    if not callable(getattr(impl, "_scene_logic", None)) or not callable(
        getattr(impl, "_scene_lords", None)
    ):
        return [
            "agent/lords_impl 缺 _scene_logic / _scene_lords —— 无法模拟安装态（取真源的入口被改坏了）"
        ]

    # 基线 = 仓库态（现在 scene/ 在场）：读列表 + 三跳 + 容错行名
    baseline = _run_agent_flow(impl, task_id=301)
    baseline_fuzzy = _fuzzy_pick_observation(impl, task_id=302)
    if baseline["read_box"] == () or len(baseline["rows"]) != 3:
        msgs.append(f"仓库态基线自身不成立（read_box={baseline['read_box']!r}，rows={baseline['rows']!r}）")
    truth_plan = _outcome(lu.plan_round, ([("妖狐讨伐", 1, 4)], tuple(lords.LORDS)), _norm_plan,
                          lu.LordsDataError)

    # ★模拟真实安装态★：install/agent 里没有 scene/ ⇒ 两个取真源的入口都取不到
    saved_logic, saved_lords = impl._scene_logic, impl._scene_lords
    try:
        impl._scene_logic = lambda: None
        impl._scene_lords = lambda: None

        logic = impl._logic()
        if logic is None:
            msgs.append(
                "安装态（没有 scene/）回落失败：_logic() 返回 None —— "
                "装好的产品会「识别不命中、动作如实失败」（本票要修的正是这个）"
            )
            return msgs
        if getattr(logic, "plan_round", None) is None:
            msgs.append("安装态回落的判定真源没有 plan_round —— 装好的产品读不了列表")
            return msgs

        registry = impl._registry()
        if registry is None or len(tuple(registry)) != len(tuple(lords.LORDS)):
            msgs.append(
                f"安装态花名册不可用/不齐：{None if registry is None else len(tuple(registry))} "
                f"!= 真源 {len(tuple(lords.LORDS))} 位"
            )
            return msgs
        inst_plan = _outcome(logic.plan_round, ([("妖狐讨伐", 1, 4)], registry), _norm_plan,
                             logic.LordsDataError)
        if inst_plan != truth_plan:
            msgs.append(f"安装态 plan_round 与仓库态不一致：{inst_plan!r} != {truth_plan!r}")

        # 行名容错正则：安装态必须能从冻结表里取到真机实测过的变体
        for entry in tuple(lords.LORDS):
            if impl._row_regex(entry.row_name) != entry.row_regex:
                msgs.append(
                    f"安装态 _row_regex({entry.row_name!r}) = {impl._row_regex(entry.row_name)!r} "
                    f"!= 真源 {entry.row_regex!r}"
                )
                break
        if impl._row_regex("花名册外的行") is not None:
            msgs.append("安装态 _row_regex 为花名册外的行编了一个正则 —— 认错字去点行 = 点错人")

        # 整条链：读列表 → 三跳 → 计一场，与仓库态**逐项相同**
        install = _run_agent_flow(impl, task_id=303)
        if install != baseline:
            diff = {k: (baseline[k], install[k]) for k in baseline if baseline[k] != install.get(k)}
            msgs.append(f"安装态整条链与仓库态不一致：{diff!r}")
        if install["read_box"] == () or not install["rows"]:
            msgs.append("安装态识别**不命中**（read_box 空）—— 装好的产品读不出列表页")
        if install["sessions_played"] != 1:
            msgs.append(f"安装态点下【挑战】没记 1 场（{install['sessions_played']}）—— 动作没照做")

        install_fuzzy = _fuzzy_pick_observation(impl, task_id=304)
        if install_fuzzy != baseline_fuzzy:
            msgs.append(f"安装态行名容错与仓库态不一致：{install_fuzzy!r} != {baseline_fuzzy!r}")
        if install_fuzzy["box"] == ():
            msgs.append("安装态认不出「红嫉族机兵」（冻结的 ^红嫉族?机兵$ 没生效）—— 真机会漏行")
    finally:
        impl._scene_logic = saved_logic
        impl._scene_lords = saved_lords
        impl.reset_sessions()
    return msgs


def probe_lords_install_behavior_parity() -> bool:
    """#100：没有 ``scene/`` 时 ``lords_impl`` 仍命中、仍点、仍记账，且与仓库态逐项相同。"""
    return _install_behavior_failures() == []


# ---------------------------------------------------------------------------
# 9. 页签切换（#100 第 1 条缺口）：判据来源 + **确认条件** + 失败不重试
# ---------------------------------------------------------------------------
def _lords_nav():
    """``scene.lords_nav``（导航真源：页签 + 滚动，纯逻辑）。"""
    return _module("scene.lords_nav")


def _page_rules():
    return _module("scene.page_rules")


def _rows_of(frame) -> tuple:
    """一帧 OCR 项 → 行读数（走真源 ``group_progress_rows``，与运行期同一个入口）。"""
    rows, _orphans = _lords_unlock().group_progress_rows(frame)
    return tuple(rows)


def _tab_failures(nav=None, files=None) -> list[str]:
    """页签守卫：判据来源 / 点击点对账 / **确认条件** / **只许点 1 次** / pipeline 形状。"""
    nav = _lords_nav() if nav is None else nav
    files = _pipelines() if files is None else files
    pr = _page_rules()
    msgs: list[str] = []

    # (a) 判据**逐字段等于** scene.page_rules（ADR-0003：引用不复制）
    for tab, page in (("领主战", "领主战页签"), ("降临讨伐", "降临讨伐页签")):
        rule = pr.page_rule(page)
        param = rule.recognition.get("param") or {}
        anchor = nav.TAB_ANCHORS.get(tab)
        if anchor is None:
            msgs.append(f"页签守卫：TAB_ANCHORS 缺 {tab!r}")
            continue
        if tuple(param.get("expected") or ()) != tuple(anchor.expected):
            msgs.append(
                f"页签守卫：{tab} 的判据 {tuple(anchor.expected)!r} 与 scene.page_rules::{page} "
                f"的 {tuple(param.get('expected') or ())!r} 不一致（判据只能有一份）"
            )
        if tuple(param.get("roi") or ()) != tuple(anchor.roi):
            msgs.append(
                f"页签守卫：{tab} 的 ROI {tuple(anchor.roi)!r} != scene.page_rules::{page} 的 "
                f"{tuple(param.get('roi') or ())!r}"
            )

    # (b) ★点击点 = 真机帧里标签框的中心★（并与 SpecialTab* 的实测点击点对账）
    for tab, (x, y, w, h) in TAB_FRAME_1080.items():
        cx, cy = (x + w / 2.0) / 1.5, (y + h / 2.0) / 1.5
        anchor = nav.TAB_ANCHORS[tab]
        hx, hy = anchor.click_hint
        if abs(cx - hx) > 2.5 or abs(cy - hy) > 2.5:
            msgs.append(
                f"页签守卫：{tab} 的 click_hint ({hx},{hy}) 与真机帧标签框中心 "
                f"({cx:.1f},{cy:.1f})（[x,y,w,h]={TAB_FRAME_1080[tab]} ÷1.5）差超过 2.5px —— "
                f"「点标签框中心」必须落在真机实测那一点上"
            )
        px, py = TAB_PIPELINE_POINTS[tab]
        if abs(cx - px) > 2.5 or abs(cy - py) > 2.5:
            msgs.append(
                f"页签守卫：真机帧标签框中心 ({cx:.1f},{cy:.1f}) 与 "
                f"{TAB_PIPELINE_NODES[tab]} 的实测点击点 ({px},{py}) 对不上 —— 帧或节点被改过"
            )
        rx, ry, rw, rh = anchor.roi
        if not (rx <= cx <= rx + rw and ry <= cy <= ry + rh):
            msgs.append(f"页签守卫：{tab} 标签框中心 ({cx:.1f},{cy:.1f}) 不在它的 ROI {anchor.roi} 内")

    # (c) ★确认条件★：只认行族身份证据，**绝不认「读得到标签」**（两个标签常驻同屏）
    if not str(getattr(nav, "CONFIRM_BASIS", "") or ""):
        msgs.append("页签守卫：CONFIRM_BASIS 为空 —— 切换后的确认条件必须写清（守卫据此对账）")
    ev = nav.tab_state(LIST_FRAME)
    if ev.confirmed != "领主战":
        msgs.append(f"页签守卫：领主战帧确认出 {ev.confirmed!r}，应为 '领主战'（{ev}）")
    ev = nav.tab_state(TAB_FRAME_JOSS)
    if ev.confirmed != "降临讨伐":
        msgs.append(f"页签守卫：降临讨伐帧确认出 {ev.confirmed!r}，应为 '降临讨伐'（{ev}）")
    labels_only = tuple(
        item
        for item in LIST_FRAME
        if item[0] in ("领主战", "降临讨伐", "更新列表")
    )
    ev = nav.tab_state(labels_only)
    if ev.confirmed is not None:
        msgs.append(
            f"页签守卫：只有页签标签（没有行族证据）就确认成 {ev.confirmed!r} —— "
            f"两个标签常驻同屏，这等于「点完就当成功」（#19 竞速死循环的入口）"
        )
    mixed = tuple(LIST_FRAME) + tuple(TAB_FRAME_JOSS)
    if nav.tab_state(mixed).confirmed is not None:
        msgs.append("页签守卫：两族行同屏（矛盾）却确认出了一个页签 —— 猜的页签会点错列表")

    # (d) ★切换失败不得重试超过 1 次★（#19）：行为表逐次跑，统计真正点了几次
    if int(getattr(nav, "TAB_SWITCH_MAX_ATTEMPTS", 99)) > 1:
        msgs.append(
            f"页签守卫：TAB_SWITCH_MAX_ATTEMPTS = {nav.TAB_SWITCH_MAX_ATTEMPTS} > 1 —— "
            f"切页签失败重试正是 #19 的竞速死循环（点A→未确认→点B→未确认→~4.3s 一圈）"
        )
    state = nav.NavState()
    evidence = nav.tab_state(LIST_FRAME)                      # 站在领主战
    box = nav.label_box(TAB_FRAME_JOSS, nav.TAB_ANCHORS["降临讨伐"])
    if box is None:
        msgs.append("页签守卫：降临讨伐帧里读不出它的标签框（label_box 失效）")
    else:
        clicks = 0
        stopped = False
        now = 1000.0
        for _step in range(12):
            decision = state.switch_decision(evidence, "降临讨伐", box, now)
            if decision.action == nav.ACTION_CLICK:
                clicks += 1
                if decision.box != box:
                    msgs.append("页签守卫：切页签的框不是当帧标签框（坐标必须来自当帧 OCR）")
            if decision.action == nav.ACTION_STOP:
                stopped = True
                break
            now += float(getattr(nav, "TAB_CONFIRM_GRACE_SEC", 0.0)) + 0.5
        if clicks > 1:
            msgs.append(f"页签守卫：同一目标页签被点了 {clicks} 次 —— 切换失败只许 1 次，不许重试")
        if clicks == 0:
            msgs.append("页签守卫：需要切换却一次都没点（永远不切 → 走不到另一个页签的行）")
        if not stopped:
            msgs.append(
                "页签守卫：反复不确认却从不收工 —— 必须有界（TAB_UNCONFIRMED_LIMIT），"
                "否则就是 #19 那种无限空转"
            )

    # (e) pipeline 形状：LordsSwitchTab（含切后确认的机会 = post_delay）+ 两个 mode/do
    data = files.get(LORDS_FILE) or {}
    node = data.get("LordsSwitchTab")
    if not isinstance(node, dict):
        msgs.append(f"{LORDS_FILE}::LordsSwitchTab 不存在 —— 页签切换这条腿整个不见了")
    else:
        reco = ((node.get("recognition") or {}).get("param") or {})
        mode = (reco.get("custom_recognition_param") or {}).get("mode")
        if reco.get("custom_recognition") != RECO_NAME or str(mode) != "tab":
            msgs.append(f"LordsSwitchTab 的识别应是 {RECO_NAME} mode=tab，实际 {mode!r}")
        act = ((node.get("action") or {}).get("param") or {})
        if act.get("custom_action") != ACTION_NAME or str((act.get("custom_action_param") or {}).get("do")) != "tab":
            msgs.append(f"LordsSwitchTab 的动作应是 {ACTION_NAME} do=tab，实际 {act!r}")
        if int(node.get("post_delay") or 0) < 1000:
            msgs.append(
                f"LordsSwitchTab.post_delay={node.get('post_delay')!r} 太短 —— 切完要留出「再读一次页签状态」"
                f"的时间（真机 SpecialTab* 是 1200）"
            )
        if list(node.get("next") or [])[-1:] != ["LordsEntry"]:
            msgs.append("LordsSwitchTab.next 末项应回枢纽 LordsEntry")
        if "max_hit" in node:
            msgs.append("LordsSwitchTab 带 max_hit —— 页签绝不能靠「谁先命中谁用尽次数」竞速（#19）")

    # (f) 页签来源链一致：LordsSwitchTab 必须被枢纽扫到（否则永不执行）
    hub_next = (data.get("LordsEntry") or {}).get("next") or []
    if "LordsSwitchTab" not in hub_next:
        msgs.append("LordsEntry.next 里没有 LordsSwitchTab —— 枢纽扫不到它，页签永远不会被切")
    return msgs


def probe_lords_tab_confirm() -> bool:
    """#100：页签判据来源 + 点击点对账 + 切后确认（只认行族）+ 失败不重试 + pipeline 形状。"""
    return _tab_failures() == []


# ---------------------------------------------------------------------------
# 10. 列表滚动（#100 第 2 条缺口）：★绝不用 max_hit★ + 时间闩 + 到底判据
# ---------------------------------------------------------------------------
#: agent 侧滚动接线必须出现的片段（去掉任何一条 = 时间闩/记账/有界停 掉了）。
SCROLL_SOURCE_NEEDLES: tuple = (
    ("plan.min_interval_sec", "动作里没有读时间闩"),
    ("_sleep(", "时间闩到点时没有补睡余量"),
    ("nav.note_scroll(", "滚完没有记账（时间闩的基准不会前进）"),
    ("nav.scroll_budget_exhausted()", "每页上限用尽时没有「带原因收工」的判定"),
    ("context.run_action(SCROLL_NODE)", "动作没有调用手势节点"),
    ("SCROLL_NODE = ", "手势节点名不见了"),
)


def _scroll_failures(nav=None, files=None, agent_source=None) -> list[str]:
    """滚动守卫：无 ``max_hit`` / 时间闩 / 到底判据 / 手势几何 / 上限即收工 / 管线顺序。"""
    nav = _lords_nav() if nav is None else nav
    files = _pipelines() if files is None else files
    src = (
        (AGENT_DIR / "lords_impl.py").read_text(encoding="utf-8")
        if agent_source is None
        else agent_source
    )
    plan = nav.SCROLL_PLAN
    msgs: list[str] = []
    data = files.get(LORDS_FILE) or {}

    # (a) ★全文件不许出现 max_hit★（#50：命中级计数按任务共享，用尽即被框架静默跳过）
    for name, node in data.items():
        if isinstance(node, dict) and "max_hit" in node:
            msgs.append(
                f"滚动守卫：{LORDS_FILE}::{name} 带了 max_hit={node['max_hit']!r} —— "
                f"「滚几次」的上限绝不能交给 max_hit（#50：按任务共享的计数用尽后节点被**静默跳过**，"
                f"目标行永远滚不到）；必须是时间闩 + 明确的「到底」判据"
            )

    # (b) 时间闩
    if float(plan.min_interval_sec) < 1.2:
        msgs.append(
            f"滚动守卫：时间闩 {plan.min_interval_sec}s < 1.2s —— 连甩会把列表甩过头"
            f"（SpecialScrollList 的 #42 修正就是为此）"
        )
    for needle, why in SCROLL_SOURCE_NEEDLES:
        if needle not in src:
            msgs.append(f"滚动守卫：agent 侧滚动接线缺 {needle!r}（{why}）")

    # (c) 手势几何
    if plan.begin[0] != plan.end[0]:
        msgs.append("滚动守卫：手势不竖直（dx != 0）—— 四元素写法会被当区域，dx 会随机乱跳（#42）")
    if plan.begin[1] - plan.end[1] != plan.travel_px:
        msgs.append(
            f"滚动守卫：行程 {plan.travel_px}px 与 begin/end 的纵向差 "
            f"{plan.begin[1] - plan.end[1]}px 不一致"
        )
    if not plan.geometry_ok:
        msgs.append(
            f"滚动守卫：手势端点 {plan.begin}/{plan.end} 不在列表体 {plan.list_body} 内 —— "
            f"起手落在底部导航带上会让列表不吃这一笔、抬手处被当成选行（#36 真机事故）"
        )

    # (d) ★到底判据★：行为表。口径 = **按滚动世代记账**
    #     （同一世代只记一次；没真的滚过不记账；连续 2 个世代无变化才算到底）
    rows = _rows_of(LIST_FRAME)
    if not rows:
        msgs.append("滚动守卫：列表页帧读不出行 —— 到底判据无从验证")
    else:
        state = nav.NavState()
        first, _w1 = state.observe(rows)
        second, _w2 = state.observe(rows)
        third, _w3 = state.observe(rows)
        if first or second or third:
            msgs.append(
                "滚动守卫：**一次都没滚过**就判「到底」—— 同一屏重读不是「列表不动」"
                "（LordsScanPage 被 [JumpBack]PubLoadingWait / PubDailyPopup 弹回来就会这样）"
            )
        if state.stable_scrolls != 0:
            msgs.append(
                f"滚动守卫：没滚过却攒了 {state.stable_scrolls} 次「无变化」—— "
                f"到底计数必须绑「确实滚过」（滚动世代）"
            )
        state.note_scroll(1000.0)
        gen1, _wg1 = state.observe(rows)
        gen1_again, _wg1b = state.observe(rows)
        if gen1:
            msgs.append("滚动守卫：滚动**一次**没动就判到底 —— 加载/惯性抖动会把它误判成列表尾"
                        f"（stable_times={plan.stable_times}）")
        if state.stable_scrolls != 1:
            msgs.append(
                f"滚动守卫：滚过 1 次后同屏应只记 1 次，实际 {state.stable_scrolls} 次"
            )
        if gen1_again or state.stable_scrolls != 1:
            msgs.append(
                "滚动守卫：**同一世代**重复读同一屏又记了一次 —— 弹窗/加载把扫描节点弹回来就能凑数"
            )
        state.note_scroll(1002.0)
        end, why_end = state.observe(rows)
        if not end:
            msgs.append(
                f"滚动守卫：连续 {plan.stable_times} 个滚动世代「无新行 ∧ 无位移」却没判到底 —— "
                f"滚动会一路滚到每页上限（半扫的列表判不了「全部解禁」）"
            )
        if "新行" not in str(why_end) or "位移" not in str(why_end):
            msgs.append(f"滚动守卫：到底的原因没说清量（新行/位移）：{why_end!r} —— 现场无法复核")
        # 有新行 / 有位移 → 必须不算到底
        state2 = nav.NavState()
        state2.observe(rows)
        state2.note_scroll(2000.0)
        shifted = tuple((text, [box[0], box[1] - 400, box[2], box[3]]) for text, box in LIST_FRAME)
        moved, _wm = state2.observe(_rows_of(shifted))
        if moved:
            msgs.append("滚动守卫：整屏位移 400px（滚动真的生效）却判到底 —— 会只读第一屏就收工")

    # (e) 页内上限：用尽必须「带原因收工」
    state3 = nav.NavState()
    state3.observe(rows)
    state3.scrolls_in_page = plan.max_scrolls_per_page
    if not state3.scroll_budget_exhausted():
        msgs.append("滚动守卫：每页上限用尽却没被判定出来（scroll_budget_exhausted）")
    allowed, why_budget = state3.may_scroll(
        10_000.0, confirmed="领主战", desired="领主战", target_visible=False, scanning=True
    )
    if allowed:
        msgs.append("滚动守卫：每页上限用尽后仍允许滚动 —— 无界")
    if "收工" not in str(why_budget):
        msgs.append(f"滚动守卫：上限用尽的原因没说「带原因收工」：{why_budget!r}")

    # (f) 管线：手势节点几何 == SCROLL_PLAN；滚动节点 post_delay == settle_ms；手势节点不进 next
    swipe = data.get("LordsSwipeOnce") or {}
    action = swipe.get("action") or {}
    if str(action.get("type")) != "Swipe":
        msgs.append(f"{LORDS_FILE}::LordsSwipeOnce 的动作应是 Swipe，实际 {action.get('type')!r}")
    param = action.get("param") or {}
    for field, want in (("begin", list(plan.begin)), ("end", list(plan.end))):
        got = param.get(field)
        if not isinstance(got, list) or len(got) != 2:
            msgs.append(
                f"滚动守卫：LordsSwipeOnce.{field}={got!r} 必须是**两元素定点** [x, y] —— "
                f"四元素会被 MAA 当【区域】随机取点（#42 真机：begin x∈[362,710]）"
            )
        elif list(got) != want:
            msgs.append(
                f"滚动守卫：LordsSwipeOnce.{field}={got!r} 与 SCROLL_PLAN 的 {want!r} 不一致 "
                f"（两处各写一份数字必然漂移）"
            )
    if param.get("duration") != plan.duration_ms:
        msgs.append(
            f"滚动守卫：LordsSwipeOnce.duration={param.get('duration')!r} != SCROLL_PLAN.duration_ms "
            f"{plan.duration_ms}（800ms 才是拖拽，快了就是甩动）"
        )
    scroll = data.get("LordsScrollOnce") or {}
    if int(scroll.get("post_delay") or 0) != int(plan.settle_ms):
        msgs.append(
            f"滚动守卫：LordsScrollOnce.post_delay={scroll.get('post_delay')!r} != "
            f"SCROLL_PLAN.settle_ms={plan.settle_ms}（滚完的稳定等待由节点承担）"
        )
    reco = ((scroll.get("recognition") or {}).get("param") or {})
    if str((reco.get("custom_recognition_param") or {}).get("mode")) != "scroll":
        msgs.append(f"LordsScrollOnce 的识别应是 {RECO_NAME} mode=scroll")
    act = ((scroll.get("action") or {}).get("param") or {})
    if str((act.get("custom_action_param") or {}).get("do")) != "scroll":
        msgs.append(f"LordsScrollOnce 的动作应是 {ACTION_NAME} do=scroll")
    for name, node in data.items():
        if not isinstance(node, dict):
            continue
        for ref in _refs(node):
            if ref == "LordsSwipeOnce":
                msgs.append(
                    f"{LORDS_FILE}::{name} 把 LordsSwipeOnce 写进了 next —— 手势节点只许被 "
                    f"run_action 调用（写进 next 就等于「无条件滚动」，绕开所有闸）"
                )

    # (g) 「先判到底、再滚动」+「行可见先选行」（#29 形态）
    scan_next = (data.get("LordsScanPage") or {}).get("next") or []
    if "LordsListEnd" not in scan_next or "LordsScrollOnce" not in scan_next:
        msgs.append(f"LordsScanPage.next 缺 LordsListEnd / LordsScrollOnce（{scan_next}）")
    elif list(scan_next).index("LordsListEnd") > list(scan_next).index("LordsScrollOnce"):
        msgs.append("LordsScanPage.next 里 LordsScrollOnce 排在 LordsListEnd 之前 —— 到底了还会再滚")
    hub_next = (data.get("LordsEntry") or {}).get("next") or []
    if "LordsScrollOnce" in hub_next and "LordsPickTarget" in hub_next:
        if list(hub_next).index("LordsScrollOnce") < list(hub_next).index("LordsPickTarget"):
            msgs.append("LordsEntry.next 里滚动排在选行之前 —— 行在屏上也会先滚（#29）")
    end_node = data.get("LordsListEnd") or {}
    end_reco = ((end_node.get("recognition") or {}).get("param") or {})
    if str((end_reco.get("custom_recognition_param") or {}).get("mode")) != "end":
        msgs.append(f"LordsListEnd 的识别应是 {RECO_NAME} mode=end")
    return msgs


def probe_lords_scroll_latch() -> bool:
    """#100：滚动没有 max_hit、有时间闩、有到底判据（行为表）、手势几何与管线逐字段一致。"""
    return _scroll_failures() == []


# ---------------------------------------------------------------------------
# 11. 滚动去重：同一 (行名, N/M) 在一轮里只许出现一次
# ---------------------------------------------------------------------------
def _dedup_failures(nav=None, logic=None) -> list[str]:
    """去重守卫：键形状 + 重叠两屏只留一次 + 进度变化算新读数 + ``plan_round`` 不重复。"""
    nav = _lords_nav() if nav is None else nav
    logic = _lords_unlock() if logic is None else logic
    msgs: list[str] = []

    # (a) 键形状 = (行名, N/M)
    row = _rows_of(LIST_FRAME)[0] if _rows_of(LIST_FRAME) else None
    if row is None:
        return ["去重守卫：列表页帧读不出行 —— 无法验证去重"]
    key = tuple(nav.row_key(row))
    if len(key) != 2 or "/" not in str(key[1]):
        msgs.append(f"去重守卫：去重键 {key!r} 不是 (行名, N/M)")
    if nav.row_key(("妖狐讨伐", 1, 4)) == nav.row_key(("妖狐讨伐", 2, 4)):
        msgs.append(
            "去重守卫：同一行**不同进度**被并成了同一个键 —— 进度变化是真·新信息，不能吞"
        )

    # (b) 重叠两屏：第一屏的行在第二屏里必须全部算「重复」
    page1 = _rows_of(LIST_FRAME)
    page2 = _rows_of(LIST_FRAME) + _rows_of(TAB_FRAME_JOSS)[1:]
    state = nav.NavState()
    new1, dup1 = state.add_rows(page1)
    if dup1:
        msgs.append(f"去重守卫：首屏就判出重复 {dup1!r}")
    new2, dup2 = state.add_rows(page2)
    if tuple(dup2) != tuple(nav.row_key(r) for r in page1):
        msgs.append(
            f"去重守卫：重叠帧里的重复项对不上 —— 应等于首屏的键 {tuple(nav.row_key(r) for r in page1)!r}，"
            f"实际 {tuple(dup2)!r}"
        )
    if len(new2) != len(_rows_of(TAB_FRAME_JOSS)) - 1:
        msgs.append(f"去重守卫：重叠帧只应新增降临讨伐那几行，实际新增 {len(new2)} 行")
    keys = tuple(nav.row_key(r) for r in state.rows())
    if len(keys) != len(set(keys)):
        msgs.append(f"去重守卫：累计里仍有重复键 {keys!r} —— 同一行会被读两遍")

    # (c) ★去重之后 plan_round 不会把同一行打两遍★
    plan = logic.plan_round(state.rows(), _lords().LORDS)
    names = [target.row_name for target in plan.targets]
    if len(names) != len(set(names)):
        msgs.append(f"去重守卫：plan_round 的目标里同一行出现两次 {names!r}")
    kinds = {p.kind for p in plan.problems}
    if logic.PROBLEM_DUPLICATE in kinds:
        msgs.append(
            "去重守卫：去重后的读数仍触发 duplicate_row —— 说明同一行的两个读数被一起喂进了规划"
        )

    # (d) 反过来：**不去重**时 rows_read 会虚高（这正是要防的形态）
    dirty = tuple(page1) + tuple(page1)
    if len(dirty) <= len(page1):
        msgs.append("去重守卫：脏样例构造失败")
    state2 = nav.NavState()
    state2.add_rows(dirty)
    if len(state2.rows()) != len(page1):
        msgs.append(
            f"去重守卫：同一屏读两遍后累计成了 {len(state2.rows())} 行，应为 {len(page1)} 行"
        )

    # (e) 接线：`mode=page` 必须真的走上 add_rows（否则「读全」等于没做）
    src = (AGENT_DIR / "lords_impl.py").read_text(encoding="utf-8")
    for needle, why in (
        ("nav.add_rows(", "页扫描没有把行读数并进累计"),
        ("navl.row_key(", "没有用真源的去重键做核对"),
    ):
        if needle not in src:
            msgs.append(f"去重守卫：agent 侧缺 {needle!r}（{why}）")
    return msgs


def probe_lords_scroll_dedup() -> bool:
    """#100：滚动去重键 = (行名, N/M)，重叠两屏只记一次，规划里同一行不出现两遍。"""
    return _dedup_failures() == []


# ---------------------------------------------------------------------------
# 12. 导航真源的安装态单源守卫（快照 == 真源，数据 + 行为表）
# ---------------------------------------------------------------------------
#: 导航快照必须与真源逐项相等的**数据字段**。
NAV_PARITY_FIELDS: tuple = (
    "LORD_TABS",
    "LIST_PAGE_ANCHOR",
    "TAB_LABELS_ALWAYS_PRESENT",
    "TAB_SWITCH_MAX_ATTEMPTS",
    "TAB_UNCONFIRMED_LIMIT",
    "TAB_CONFIRM_GRACE_SEC",
    "CONFIRM_BASIS",
    "END_ANCHORS",
    "NAV_STUCK_SEC",
)

#: 滚动计划必须逐项相等的字段。
SCROLL_PARITY_FIELDS: tuple = (
    "travel_px",
    "begin",
    "end",
    "duration_ms",
    "settle_ms",
    "min_interval_sec",
    "max_scrolls_per_page",
    "stable_times",
    "no_move_px",
    "list_body",
)


def _norm_evidence(ev) -> tuple:
    """页签证据 → 纯数据（真源与快照的 dataclass 都能被同一份归一化吃掉）。"""
    return (bool(ev.list_page), tuple(sorted(ev.labels)), ev.confirmed, tuple(ev.kinds),
            tuple(ev.unknown_rows))


def _norm_decision(dec) -> tuple:
    """页签判决 → 纯数据。"""
    return (dec.action, dec.target, tuple(dec.box) if dec.box is not None else None, dec.reason)


def _nav_scenario(navl) -> tuple:
    """一段确定性的导航剧本 → 可比较的观测元组（真源与快照必须逐项相同）。"""
    state = navl.NavState()
    out: list = []
    page1 = _rows_of(LIST_FRAME)
    out.append(("observe1",) + tuple(state.observe(page1)))
    out.append(("add1", tuple(state.add_rows(page1, now=1.0)[0])))
    out.append(("observe2",) + tuple(state.observe(page1)))
    out.append(("observe3",) + tuple(state.observe(page1)))
    out.append(("at_end", state.at_end()))
    out.append(
        ("may_scroll_end",)
        + tuple(state.may_scroll(5.0, confirmed="领主战", desired="领主战",
                                 target_visible=False, scanning=True))
    )
    other = navl.NavState()
    other.observe(page1)
    other.note_scroll(100.0)
    out.append(
        ("may_scroll_latch",)
        + tuple(other.may_scroll(100.0 + 0.5, confirmed="领主战", desired="领主战",
                                 target_visible=False, scanning=True))
    )
    out.append(
        ("may_scroll_ok",)
        + tuple(other.may_scroll(100.0 + 2.0, confirmed="领主战", desired="领主战",
                                 target_visible=False, scanning=True))
    )
    out.append(
        ("may_scroll_tab",)
        + tuple(other.may_scroll(200.0, confirmed="降临讨伐", desired="领主战",
                                 target_visible=False, scanning=True))
    )
    ev_lord = navl.tab_state(LIST_FRAME)
    ev_joss = navl.tab_state(TAB_FRAME_JOSS)
    out.append(("evidence_lord", _norm_evidence(ev_lord)))
    out.append(("evidence_joss", _norm_evidence(ev_joss)))
    third = navl.NavState()
    box = navl.label_box(TAB_FRAME_JOSS, navl.TAB_ANCHORS["降临讨伐"])
    out.append(("decide_ok", _norm_decision(third.switch_decision(ev_lord, "领主战", None, 10.0))))
    out.append(("decide_click", _norm_decision(third.switch_decision(ev_lord, "降临讨伐", box, 11.0))))
    now = 11.0
    for _step in range(4):
        now += float(getattr(navl, "TAB_CONFIRM_GRACE_SEC", 0.0)) + 0.5
        out.append(("decide_retry", _norm_decision(third.switch_decision(ev_lord, "降临讨伐", box, now))))
    out.append(("decide_cannot", _norm_decision(third.switch_decision(ev_lord, None, None, now))))
    sweep = navl.NavState()
    out.append(("page_pending0", sweep.page_pending(0)))
    out.append(("advance1",) + tuple(sweep.advance_tab(20.0)))
    out.append(("desired1", sweep.desired_tab()))
    out.append(("advance2",) + tuple(sweep.advance_tab(21.0)))
    out.append(("complete", sweep.complete_scan(0, 22.0) or () ))
    out.append(("page_pending_after", sweep.page_pending(0), sweep.page_pending(1)))
    out.append(("classify", tuple(navl.classify_kind(name) for name in
                                  ("妖狐讨伐", "红嫉族机兵", "降临过伐", ""))))
    out.append(("tab_of_row", tuple(navl.tab_of_row(name) for name in ("妖狐讨伐", "红嫉机兵", "降临过伐"))))
    out.append(("stuck", navl.NavState().stuck_reason(500.0)))

    # ★R1：累计表按**行名**留最新★（喂 1/4 → 2/4，累计里只能有一条）
    latest = navl.NavState()
    latest.add_rows([("妖狐讨伐", 1, 4)])
    latest.add_rows([("妖狐讨伐", 2, 4)])
    out.append(("r1_latest", tuple(navl.row_key(r) for r in latest.rows())))
    latest.add_rows([("妖狐讨伐", 1, 4)])          # 回读到更旧的读数 → 不覆盖
    out.append(("r1_no_downgrade", tuple(navl.row_key(r) for r in latest.rows())))

    # ★到底判据按滚动世代记账★：没滚过不记账 / 同世代只记一次 / 两个世代才到底
    gen = navl.NavState()
    gen.observe(page1)
    gen.observe(page1)
    out.append(("gen0_no_count", gen.stable_scrolls, gen.at_end()))
    gen.note_scroll(700.0)
    gen.observe(page1)
    gen.observe(page1)
    out.append(("gen1_once", gen.stable_scrolls, gen.at_end()))
    gen.note_scroll(702.0)
    out.append(("gen2_end",) + tuple(gen.observe(page1)))

    # ★R2：新一轮必须重新武装★（扫完 → 下一轮）
    rearm = navl.NavState()
    rearm.advance_tab(30.0)
    rearm.advance_tab(31.0)
    rearm.complete_scan(0, 32.0)
    out.append(("before_rearm", rearm.desired_tab(), rearm.page_pending(1)))
    rearm.seen["妖狐讨伐"] = ("妖狐讨伐", 1, 4)
    rearm.begin_round(33.0)
    out.append(
        (
            "after_rearm",
            rearm.desired_tab(),
            rearm.sweep_index,
            rearm.sweep_done,
            len(rearm.rows()),
            rearm.page_pending(1),
        )
    )
    return tuple(out)


def _nav_parity_failures(impl=None, nav=None) -> list[str]:
    """★导航快照 == 真源★：数据逐项 + 锚点逐字段 + 滚动计划逐字段 + 行为表逐项。"""
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    snap = getattr(impl, "_NavSnapshotLogic", None)
    if snap is None:
        return [
            "agent/lords_impl 缺 _NavSnapshotLogic —— 安装态没有导航真源替身"
            "（没有 scene/ 时页签/滚动会整体失效）"
        ]
    msgs: list[str] = []

    # (a) 常量逐项
    for name in NAV_PARITY_FIELDS:
        want = getattr(nav, name, None)
        got = getattr(snap, name, None)
        if got != want:
            msgs.append(f"导航快照 {name} = {got!r} != 真源 {want!r}")
    for name in ("ACTION_OK", "ACTION_CLICK", "ACTION_GIVE_UP", "ACTION_STOP", "ACTION_CANNOT"):
        want, got = getattr(nav, name, None), getattr(snap, name, None)
        if got != want:
            msgs.append(f"导航快照 {name} = {got!r} != 真源 {want!r}")

    # (b) 页签锚点逐字段（判据 / ROI / 实测点击点）
    if tuple(getattr(nav, "LORD_TABS", ())) != tuple(getattr(snap, "LORD_TABS", ())):
        msgs.append(f"导航快照 LORD_TABS = {getattr(snap, 'LORD_TABS', None)!r} != {nav.LORD_TABS!r}")
    for tab in getattr(nav, "LORD_TABS", ()):
        mine = nav.TAB_ANCHORS.get(tab)
        theirs = getattr(snap, "TAB_ANCHORS", {}).get(tab)
        if mine is None or theirs is None:
            msgs.append(f"导航快照缺页签锚点 {tab!r}")
            continue
        for field in ("expected", "roi", "click_hint"):
            if tuple(getattr(mine, field)) != tuple(getattr(theirs, field)):
                msgs.append(
                    f"导航快照 {tab}.{field} = {tuple(getattr(theirs, field))!r} != 真源 "
                    f"{tuple(getattr(mine, field))!r}"
                )

    # (c) 滚动计划逐字段
    plan = nav.SCROLL_PLAN
    snap_plan = getattr(snap, "SCROLL_PLAN", None)
    if snap_plan is None:
        msgs.append("导航快照缺 SCROLL_PLAN")
    else:
        for field in SCROLL_PARITY_FIELDS:
            want, got = getattr(plan, field, None), getattr(snap_plan, field, None)
            if got != want:
                msgs.append(f"导航快照 SCROLL_PLAN.{field} = {got!r} != 真源 {want!r}")
        if getattr(snap_plan, "max_scrolls_total", None) != plan.max_scrolls_total:
            msgs.append("导航快照 SCROLL_PLAN.max_scrolls_total 与真源不一致")
        if bool(getattr(snap_plan, "geometry_ok", False)) != bool(plan.geometry_ok):
            msgs.append("导航快照 SCROLL_PLAN.geometry_ok 与真源不一致")

    # (d) 数据表逐项（行名 rowname 正则 / kind / 花名册）
    for needle in ("_LORDS_KIND_SNAPSHOT", "_SUBFAMILY_BY_KIND_SNAPSHOT"):
        if not hasattr(impl, needle):
            msgs.append(f"agent/lords_impl 缺 {needle} —— 安装态算不出行的页签归属")

    # (e) 行为表：同一段剧本分别跑真源与快照，结果必须逐项相同
    mine = _nav_scenario(nav)
    theirs = _nav_scenario(snap)
    for a, b in zip(mine, theirs):
        if a != b:
            msgs.append(f"导航行为表不一致：真源 {a!r} / 快照 {b!r}")
    if len(mine) != len(theirs):
        msgs.append(f"导航行为表长度不一致：{len(mine)} vs {len(theirs)}")

    # (f) 覆盖率自检：剧本必须真的走到「到底 / 时间闩 / 切换 / 拒绝 / 扫描推进 / R1 / R2 / 世代」
    labels = tuple(item[0] for item in mine)
    for must in (
        "observe3",
        "may_scroll_latch",
        "decide_click",
        "decide_retry",
        "advance2",
        "r1_latest",
        "gen1_once",
        "after_rearm",
    ):
        if must not in labels:
            msgs.append(f"导航行为表没走到 {must!r}（剧本被删空 = 守卫瞎了）")
    return msgs


def probe_lords_nav_snapshot_parity() -> bool:
    """#100：安装态导航快照与 ``scene/lords_nav.py`` 逐项相等（数据 + 锚点 + 行为表）。"""
    return _nav_parity_failures() == []


# ---------------------------------------------------------------------------
# 13. 导航的 agent 侧行为（假 OCR + 假时钟 + 假点击：把两个页签扫一遍）
# ---------------------------------------------------------------------------
class FakeSleeper:
    """替换 ``lords_impl._sleep``（滚动时间闩的补睡不必真等）。"""

    def __init__(self) -> None:
        self.calls: list = []
        self.saved = None

    def __enter__(self):
        impl = _impl()
        self.saved = impl._sleep
        impl._sleep = self
        return self

    def __call__(self, seconds: float) -> None:
        self.calls.append(float(seconds))

    def __exit__(self, *exc):
        _impl()._sleep = self.saved
        return False


def _nav_agent_failures() -> list[str]:
    """导航 glue 的离线行为：页扫描累计（按行名留最新）/ 页签切换确认 / 滚动时间闩 /
    到底按**滚动世代**记账 / 下一轮**重新武装**扫描 / 交给判定。

    ★帧队列必须与「真的滚了几次」一一对应★：到底判据按滚动世代记账（同一世代重复读同一屏
    不攒计数），所以剧本里每读两帧同一屏就要真的 ``do=scroll`` 滚一次，并把假时钟推过时间闩。
    """
    impl = _impl()
    nav = _lords_nav()
    msgs: list[str] = []
    reco = impl.LordsProgressRecognition()
    action = impl.LordsUnlockAction()
    task = 501

    # 帧队列（每次 analyze 取一帧）：
    #   领主战：读 → 同屏重读（★不许攒计数★）→ 滚① → 读（世代 1 记 1）→ 同世代重读（不重复记）
    #   → 滚② → 读（世代 2 记 2 = 到底）→ end（推进页签）
    #   → tab（切到降临讨伐）→ tab（确认、不命中）→ 读（累计 7 行）
    #   → 滚③ → 读（世代 3 记 1）→ 滚④ → 读（世代 4 记 2 = 到底）→ end（两个都扫完 → 交给 read）
    #   → tab（★R2：下一轮重新武装★）
    frames = [
        LIST_FRAME,        # 1  mode=page：领主战首屏（3 行新读数）
        LIST_FRAME,        # 2  mode=page：同一屏重读（全重复；一次没滚过 ⇒ 不许攒「到底」计数）
        LIST_FRAME,        # 3  mode=scroll：可滚
        LIST_FRAME,        # 4  mode=page：世代 1 → 记 1
        LIST_FRAME,        # 5  mode=page：同世代重读 → 不重复记
        LIST_FRAME,        # 6  mode=scroll：可滚
        LIST_FRAME,        # 7  mode=page：世代 2 → 记 2 = 到底
        LIST_FRAME,        # 8  mode=end：推进页签 → 降临讨伐
        LIST_FRAME,        # 9  mode=tab：要切到降临讨伐 → click
        TAB_FRAME_JOSS,    # 10 mode=tab：确认已到降临讨伐 → 不命中
        TAB_FRAME_JOSS,    # 11 mode=page：降临讨伐首屏（累计 7 行）
        TAB_FRAME_JOSS,    # 12 mode=scroll：时间闩未到 → 不许滚
        TAB_FRAME_JOSS,    # 13 mode=scroll：可滚（世代 3）
        TAB_FRAME_JOSS,    # 14 mode=page：世代 3 → 记 1
        TAB_FRAME_JOSS,    # 15 mode=scroll：可滚（世代 4）
        TAB_FRAME_JOSS,    # 16 mode=page：世代 4 → 记 2 = 到底
        TAB_FRAME_JOSS,    # 17 mode=end：两个页签扫完 → 交给 mode=read
        TAB_FRAME_JOSS,    # 18 mode=tab：第 2 轮重新武装（目标页签回到领主战）
    ]
    with FakeOcr(frames=frames), FakeClock() as clock, FakeSleeper():
        ctx = FakeContext()
        page = lambda mode, t=task: reco.analyze(  # noqa: E731
            ctx, FakeArgv(reco_param={"mode": mode}, task_id=t, node_name="LordsScanPage")
        )
        state = impl._nav_state(impl._session(task))
        if state is None:
            return ["导航 glue：_nav_state() 返回 None —— 安装态回落没接上"]

        def scroll_once(where: str) -> None:
            """滚一次（识别命中 → 动作真的调手势节点 → 记账），并把假时钟推过时间闩。"""
            res = page("scroll")
            detail = dict(res.detail or {})
            if res.box != [0, 0, 0, 0]:
                msgs.append(f"{where}：mode=scroll 应命中，实际 {res.box!r}（{detail.get('reason')!r}）")
                return
            before, gen_before = state.scrolls_in_page, state.scroll_gen
            if not action.run(ctx, FakeArgv(task_id=task, act_param={"do": "scroll"})):
                msgs.append(f"{where}：do=scroll 的动作返回 False")
                return
            if not any(name == impl.SCROLL_NODE for name, _box in ctx.actions):
                msgs.append(f"{where}：do=scroll 没有调用手势节点 {impl.SCROLL_NODE}（{ctx.actions}）")
            if state.scrolls_in_page != before + 1:
                msgs.append(f"{where}：滚一次后页内计数应为 {before + 1}，实际 {state.scrolls_in_page}")
            if state.scroll_gen != gen_before + 1:
                msgs.append(
                    f"{where}：滚一次后滚动世代应 +1（{gen_before}→{gen_before + 1}），"
                    f"实际 {state.scroll_gen} —— 到底判据没绑「确实滚过」"
                )
            clock.advance(float(nav.SCROLL_PLAN.min_interval_sec) + 0.5)   # 下一次滚动的时间闩

        # (a) 页扫描：命中 + 累计 3 行 + 未到底
        res = page("page")
        detail = dict(res.detail or {})
        if res.box != [0, 0, 0, 0]:
            msgs.append(f"mode=page 应命中（box=[0,0,0,0]），实际 {res.box!r}（{detail.get('reason')!r}）")
        if detail.get("tab") != "领主战":
            msgs.append(f"mode=page 的页签应为领主战，实际 {detail.get('tab')!r}")
        if detail.get("scanned") != len(_rows_of(LIST_FRAME)):
            msgs.append(f"mode=page 首帧应累计 {len(_rows_of(LIST_FRAME))} 行，实际 {detail.get('scanned')!r}")
        if detail.get("at_end"):
            msgs.append("mode=page 首帧就判到底 —— 会只读一屏就收工")
        if len(state.rows()) != len(_rows_of(LIST_FRAME)):
            msgs.append(f"页扫描累计应为 {len(_rows_of(LIST_FRAME))} 行，实际 {len(state.rows())}")

        # (b) 同一屏再读：★必须全部算重复★；且★一次没滚过 ⇒ 不许攒「到底」计数★（item 7 的 agent 见证）
        detail2 = dict(page("page").detail or {})
        if detail2.get("dup") != len(_rows_of(LIST_FRAME)):
            msgs.append(f"同一屏再读应全算重复（{len(_rows_of(LIST_FRAME))}），实际 {detail2.get('dup')!r}")
        if detail2.get("scanned") != detail.get("scanned"):
            msgs.append("同一屏再读竟让累计变大 —— 去重没生效")
        if detail2.get("at_end") or state.stable_scrolls != 0:
            msgs.append(
                f"同一屏重读（本页一次都没滚过）却攒了「到底」计数 {state.stable_scrolls} —— "
                f"加载/弹窗把 LordsScanPage 弹回来就能凑数（到底判据必须按滚动世代记账）"
            )
        if state.scroll_gen != 0:
            msgs.append(f"还没滚过一次，滚动世代却是 {state.scroll_gen}")

        # (c) 滚① → 世代 1 记 1；同世代重读**不重复记**
        scroll_once("领主战首个世代")
        if not state.at_end():
            d4 = dict(page("page").detail or {})
            if d4.get("at_end") or state.stable_scrolls != 1:
                msgs.append(
                    f"滚过 1 次后同屏应只记 1 次（还不算到底），实际 stable={state.stable_scrolls} "
                    f"/ at_end={d4.get('at_end')!r}"
                )
            d5 = dict(page("page").detail or {})
            if d5.get("at_end") or state.stable_scrolls != 1:
                msgs.append(
                    f"同一世代重复读又记了一次（stable={state.stable_scrolls}）—— "
                    f"「连续 2 次」必须是连续 2 个**滚动世代**"
                )

            # (d) 滚② → 世代 2 记 2 = 到底
            scroll_once("领主战第二个世代")
            d7 = dict(page("page").detail or {})
            if not d7.get("at_end"):
                msgs.append("连续 2 个滚动世代「无新行 ∧ 无位移」却没判到底 —— 滚动会无界")

        # (e) mode=end：推进页签（领主战 → 降临讨伐）
        res = page("end")
        detail = dict(res.detail or {})
        if not detail.get("advance") or "轮到" not in str(detail.get("advance")):
            msgs.append(f"mode=end 应推进页签并说清「轮到下一个」，实际 {detail.get('advance')!r}")
        if state.desired_tab() != "降临讨伐":
            msgs.append(f"推进后的目标页签应为降临讨伐，实际 {state.desired_tab()!r}")
        if "收工" in str(detail.get("reason")):
            msgs.append("推进页签时不该收工")

        # (f) mode=tab：要切页签 → 命中并给出**当帧标签框**
        res = page("tab")
        detail = dict(res.detail or {})
        want_box = list(nav.label_box(LIST_FRAME, nav.TAB_ANCHORS["降临讨伐"]))
        if res.box != want_box:
            msgs.append(f"mode=tab 应给出降临讨伐的标签框 {want_box}，实际 {res.box!r}")
        if str(detail.get("action")) != nav.ACTION_CLICK:
            msgs.append(f"mode=tab 的判决应为 click，实际 {detail.get('action')!r}")
        if not action.run(ctx, FakeArgv(task_id=task, box=res.box, act_param={"do": "tab"})):
            msgs.append("do=tab 的动作返回 False")
        centers = ctx.clicked_centers()
        if not centers:
            msgs.append("do=tab 没有产生点击")
        else:
            cx, cy = centers[-1]
            want_cx = want_box[0] + want_box[2] / 2
            want_cy = want_box[1] + want_box[3] / 2
            if abs(cx - want_cx) > 1 or abs(cy - want_cy) > 1:
                msgs.append(f"点页签的中心 {cx,cy} 不是标签框中心 {want_cx,want_cy}")
        if impl._session(task).attempts_since_read != 0:
            msgs.append(
                "点页签被记成了「一次目标点击」—— 会让扫完一轮后的首读误判「本轮结束」，"
                "进而 played==0 触发防死循环收工"
            )
        if state.scrolls_in_page != 0 or state.stable_scrolls != 0:
            msgs.append("切页签后没有清页内计数（页内滚动/到底计数跨页污染）")

        # (g) mode=tab 复核：站在降临讨伐、目标也是降临讨伐 → 必须**不命中**
        res = page("tab")
        if res.box is not None:
            msgs.append(f"已确认停在目标页签却又给了可点框 {res.box!r} —— 会重复点页签")

        # (h) 页扫描降临讨伐：累计到 7 行（领主战 3 + 降临讨伐 4）
        detail = dict(page("page").detail or {})
        total = len(_rows_of(LIST_FRAME)) + len(_rows_of(TAB_FRAME_JOSS))
        if detail.get("scanned") != total:
            msgs.append(f"两个页签累计应为 {total} 行，实际 {detail.get('scanned')!r}")

        # (i) ★时间闩★：同一时刻再滚一次必须被拒（不许连甩）
        if state.last_scroll_at > 0:
            clock.now = state.last_scroll_at + 0.1          # 把时钟拨到「刚滚完 0.1s」
            res = page("scroll")
            detail = dict(res.detail or {})
            if res.box is not None:
                msgs.append(f"时间闩未到却允许再滚一次（box={res.box!r}）—— 会连甩把列表甩过头")
            elif "时间闩" not in str(detail.get("reason")):
                msgs.append(f"拒绝滚动的理由没说「时间闩」：{detail.get('reason')!r}")
            clock.advance(float(nav.SCROLL_PLAN.min_interval_sec) + 1.0)

        # (j) 降临讨伐：滚③（世代 3 记 1）→ 滚④（世代 4 记 2 = 到底）
        for where in ("降临讨伐首个世代", "降临讨伐第二个世代"):
            scroll_once(where)
            d_after = dict(page("page").detail or {})
            want_end = where.endswith("第二个世代")
            if bool(d_after.get("at_end")) != want_end:
                msgs.append(
                    f"{where} 之后 at_end 应为 {want_end}，实际 {d_after.get('at_end')!r}"
                    f"（stable={state.stable_scrolls}/{nav.SCROLL_PLAN.stable_times}）"
                )

        # (k) mode=end 把**整份读数**交给 mode=read
        res = page("end")
        detail = dict(res.detail or {})
        nav_detail = detail.get("nav") or {}
        if not nav_detail.get("sweep_done"):
            msgs.append(f"两个页签都扫到底后 nav.sweep_done 应为真，实际 {nav_detail!r}")
        if not detail.get("rows"):
            msgs.append(f"扫描收尾没有把累计读数交给 mode=read（detail={detail}）")
        if len(detail.get("rows") or []) != total:
            msgs.append(
                f"交给判定的读数应为 {total} 行（两个页签全量），实际 {len(detail.get('rows') or [])} 行"
            )
        targets = [tuple(t) for t in (detail.get("targets") or [])]
        names = [t[0] for t in targets]
        if len(names) != len(set(names)):
            msgs.append(f"交给判定后同一行出现两次目标 {names!r} —— 去重/合成帧坏了")
        problems = [tuple(p[:2]) for p in (detail.get("problems") or [])]
        if not any(kind == _lords_unlock().PROBLEM_NO_CHAIN for kind, _row in problems):
            msgs.append(
                f"交给判定后应报 no_chain（妖狐/艾基尔这类未采集解锁链的领主必须**不静默跳**），"
                f"实际 problems={problems}"
            )
        if detail.get("stop"):
            msgs.append(f"两个页签刚扫完就判收工（{detail.get('reason')!r}）—— 一场都还没打")
        if state.page_pending(0):
            msgs.append("扫描收尾后同一轮仍在「待扫描」—— 会无限重扫")
        if not state.page_pending(1):
            msgs.append("下一轮（round 前进）却不重扫 —— 违反 D6「每轮重开列表」")

        # (l) ★R2：第 2 轮必须重新武装扫描★（修前 desired_tab()=None ⇒ 不切页签、页签闸被跳过）
        session = impl._session(task)
        session.round_index = 1                    # 打完一场回到列表 = 轮次前进
        rows_before = state.rows()
        res = page("tab")
        detail = dict(res.detail or {})
        back_box = list(nav.label_box(TAB_FRAME_JOSS, nav.TAB_ANCHORS[nav.LORD_TABS[0]]))
        if not detail.get("round_rearmed"):
            msgs.append(f"第 2 轮开始没有重新武装扫描（detail={detail}）—— 会一个页签都不扫")
        if state.sweep_done or state.sweep_index != 0:
            msgs.append(
                f"重新武装后 sweep 应为 (index=0, done=False)，实际 "
                f"({state.sweep_index}, {state.sweep_done})"
            )
        if state.rows() != ():
            msgs.append(f"新一轮没有清累计读数（{len(state.rows())} 行还在：{rows_before!r}）")
        if detail.get("target") != nav.LORD_TABS[0] or res.box != back_box:
            msgs.append(
                f"第 2 轮的目标页签应回到 {nav.LORD_TABS[0]!r} 并给出它的标签框 {back_box}，"
                f"实际 target={detail.get('target')!r} box={res.box!r}"
            )

    impl.reset_sessions()
    return msgs


def probe_lords_nav_agent_offline() -> bool:
    """#100：导航 glue 离线可跑（页扫描去重 / 切页签确认 / 时间闩 / 到底推进 / 交给判定）。"""
    return _nav_agent_failures() == []


# ---------------------------------------------------------------------------
# 14. 两轮之间：累计表（R1）+ 重新武装（R2）+ mode=read 的扫描闸
# ---------------------------------------------------------------------------
def _round_rearm_failures(impl=None, nav=None, agent_source=None) -> list[str]:
    """★R1/R2★：累计表按**行名**留最新、每轮 ``begin_round`` 重新武装、``mode=read`` 有扫描闸。

    R1 的后果（修前）：第 2 轮 ``rows()`` 同时含 ``(行名, 旧 N/M)`` 与 ``(行名, 新 N/M)``，
    ``plan_round`` 对同名行取**第一条** ⇒ 反复打刚打完的档，「打没打过的，直到全 M/M」永远到不了，
    最后以「连续 2 轮无新解锁」误收工。
    R2 的后果（修前）：``complete_scan`` 之后无人复位 ⇒ 第 2 轮 ``page_pending`` 为真但
    ``desired_tab()`` 是 ``None`` ⇒ 不切页签、页签闸被跳过、``advance_tab`` 立刻宣布「两个都扫完」。
    """
    impl = _impl() if impl is None else impl
    nav = _lords_nav() if nav is None else nav
    src = (
        (AGENT_DIR / "lords_impl.py").read_text(encoding="utf-8")
        if agent_source is None
        else agent_source
    )
    msgs: list[str] = []

    # (a) ★R1 行为表★：累计表按行名留最新 —— 喂 1/4 + 2/4 只留一条，目标不得是已通关的「高级」
    state = nav.NavState()
    state.add_rows([("妖狐讨伐", 1, 4)])
    state.add_rows([("妖狐讨伐", 2, 4)])
    if len(state.rows()) != 1:
        msgs.append(
            f"R1：同一行 1/4 → 2/4 后累计里是 {len(state.rows())} 条读数（应为 1 条）—— "
            f"累计表按 (行名, N/M) 存了多条，plan_round 只会取第一条（= 反复打刚打完的档）"
        )
    plan = _lords_unlock().plan_round(state.rows(), _lords().LORDS)
    if ("妖狐讨伐", "高级") in plan.pairs:
        msgs.append(
            f"R1：喂 1/4 + 2/4 后目标仍是**已通关**的「高级」（{plan.pairs}）—— 会反复打刚打完的档"
        )
    if ("妖狐讨伐", "高级+") not in plan.pairs:
        msgs.append(f"R1：喂 1/4 + 2/4 后目标应为「高级+」（链[2]），实际 {plan.pairs}")

    # (b) ★R2 行为表★：扫完一轮 → 下一轮必须重新武装（sweep 复位 + 清累计）
    sweep = nav.NavState()
    sweep.advance_tab(10.0)
    sweep.advance_tab(11.0)
    sweep.complete_scan(0, 12.0)
    if sweep.desired_tab() is not None:
        msgs.append(
            f"R2：扫完一轮后 desired_tab()={sweep.desired_tab()!r}（守卫假设它是 None，"
            f"按新修法先确认这条不变量）"
        )
    if not sweep.page_pending(1):
        msgs.append("R2：扫完一轮后 round 前进却仍是「不待扫描」—— 每轮重开列表失效（D6）")
    sweep.seen["妖狐讨伐"] = ("妖狐讨伐", 1, 4)
    sweep.begin_round(13.0)
    if sweep.desired_tab() != nav.LORD_TABS[0]:
        msgs.append(
            f"R2：begin_round 后目标页签应回到 {nav.LORD_TABS[0]!r}，实际 {sweep.desired_tab()!r} —— "
            f"第 2 轮不切页签、页签闸被跳过"
        )
    if sweep.sweep_done or sweep.sweep_index != 0:
        msgs.append(
            f"R2：begin_round 没有复位 sweep（index={sweep.sweep_index}, done={sweep.sweep_done}）"
        )
    if sweep.rows() != ():
        msgs.append("R2：begin_round 没有清累计读数 —— 上一轮的旧 N 会混进新一轮（R1 的另一半）")

    # (c) ★滚动世代★：没滚过不记账 / 同世代只记一次 / 两个世代才到底
    rows = _rows_of(LIST_FRAME)
    gen = nav.NavState()
    gen.observe(rows)
    gen.observe(rows)
    if gen.stable_scrolls or gen.at_end():
        msgs.append(
            f"世代：一次都没滚过就攒了 {gen.stable_scrolls} 次「到底」计数 —— "
            f"同一屏重读被当成「列表没动」（LordsScanPage 的 [JumpBack]PubLoadingWait/PubDailyPopup 就会这样）"
        )
    gen.note_scroll(500.0)
    gen.observe(rows)
    gen.observe(rows)
    if gen.stable_scrolls != 1:
        msgs.append(
            f"世代：滚过 1 次后同屏应只记 1 次（同一世代重复读不重复记账），实际 {gen.stable_scrolls}"
        )
    gen.note_scroll(502.0)
    gen.observe(rows)
    if not gen.at_end():
        msgs.append("世代：连续 2 个滚动世代无变化却没判到底 —— 会一路滚到每页上限")

    # (d) 接线：四个导航 mode 的入口各调一次 _ensure_round；read 的扫描闸要在
    if src.count("_ensure_round(navl, nav, session") < 4:
        msgs.append(
            "agent 侧 `_ensure_round` 调用点不足 4 处（page/tab/scroll/end 四个导航 mode 的入口各要一次；"
            "少一个入口 = 从那一条路进来时不重新武装）"
        )
    if "nav.begin_round(now)" not in src:
        msgs.append("agent 侧没有调用 nav.begin_round —— 扫描永远不会重新武装（R2 回归）")
    if "def _scan_gate(" not in src or "synthesized=True" not in src:
        msgs.append(
            "mode=read 缺扫描闸（`_scan_gate` 定义 + 合成帧的 `synthesized=True`）—— "
            "nav 节点全 no-hit 时它会按**错页签的单帧**规划"
        )

    # (e) 行为：_ensure_round 在第 2 轮入口返回 True，同一轮内不重复复位
    session = impl.Session(task_id=999)
    navl = impl._nav()
    st = navl.NavState()
    st.advance_tab(1.0)
    st.advance_tab(2.0)
    st.complete_scan(0, 3.0)
    session.nav = st
    session.round_index = 1
    if impl._ensure_round(navl, st, session, 4.0) is not True:
        msgs.append("_ensure_round 在第 2 轮入口没有返回 True —— 扫描没被重新武装")
    elif impl._ensure_round(navl, st, session, 5.0) is not False:
        msgs.append("_ensure_round 在同一轮又复位了一次 —— 会把扫到一半的进度清掉")

    # (f) 行为：扫描阶段读**错页签**的一帧 → mode=read 不规划（扫描闸）
    with FakeOcr(frame=TAB_FRAME_JOSS):
        ctx = FakeContext()
        res = impl.LordsProgressRecognition().analyze(
            ctx, FakeArgv(reco_param={"mode": "read"}, task_id=902)
        )
        reason = str((res.detail or {}).get("reason") or "")
        if res.box is not None:
            msgs.append(
                "扫描阶段读到**降临讨伐**的一帧却照常规划了（错页签的行会被记进本轮；"
                f"首屏恰好都 M/M 就是假收工）—— mode=read 的扫描闸没生效（box={res.box!r}）"
            )
        elif "扫描阶段" not in reason and "页签" not in reason:
            msgs.append(f"mode=read 被拦下了，但理由没说清是页签/扫描阶段：{reason!r}")
    impl.reset_sessions()
    return msgs


def probe_lords_round_rearm() -> bool:
    """#100：R1（累计表按行名留最新）+ R2（每轮重新武装）+ mode=read 的扫描闸。"""
    return _round_rearm_failures() == []


# ---------------------------------------------------------------------------
# 15. lords 的**节拍预算**（timeout ≤ 3000 / post_delay ≤ 1000，白名单带理由）
# ---------------------------------------------------------------------------
#: 与 #78 对五重的那一份同一组数字（``scene.wuchong.FLOW_TIMEOUT_MS`` /
#: ``FLOW_POST_DELAY_MS``）。★本票选 **(a) 给 lords 也加节拍守卫**★，而不是把研究文档那句
#: 「新增解禁节点须 timeout≤3000 / post_delay≤1000」收窄成「仅五重」，理由：
#: ``docs/research/pipeline-exception-patterns.md:523`` 的 R4 明写「任何『多扫一遍』的设计都要
#: 重新过这条契约，不能因为『识别很快』就放松」——而 lords 的五个新导航节点恰好是**同一帧会被
#: 枢纽反复扫**的形态；真机上确实必须超过 1000ms 的等待只有少数几处，故用**白名单 + 逐条理由**，
#: 而不是把上限放宽（放宽 = 契约消失）。
LORDS_TIMEOUT_MAX_MS = 3000
LORDS_POST_DELAY_MAX_MS = 1000
#: 必须显式声明 ``timeout`` 的节点：#100 新增的 5 个导航节点（新节点不许裸奔）。
LORDS_TIMEOUT_REQUIRED: tuple = (
    "LordsSwitchTab",
    "LordsScanPage",
    "LordsListEnd",
    "LordsScrollOnce",
    "LordsSwipeOnce",
)
#: 允许 ``post_delay`` 超过默认上限的节点（白名单；``None`` = 值由真源常量派生，逐字段对账）。
LORDS_POST_DELAY_EXEMPT: dict = {
    "LordsSwitchTab": 1200,
    "LordsAfterFight": 2000,
    "LordsOpenList": 2500,
    "LordsScrollOnce": None,
}
#: 白名单的**理由**（人读；白名单不是免死金牌 —— 每个豁免都要说清为什么这一等不能省）。
LORDS_POST_DELAY_WHY: dict = {
    "LordsSwitchTab": "切页签后列表要重排、页签闸要重读一帧（真机 SpecialTab* 也是 1200）",
    "LordsAfterFight": "战斗 HUD 的轮询周期：HUD 每秒在跳，2s 一次 OCR 才不把帧打爆",
    "LordsOpenList": "主城→列表的真实转场（真机 1~2s），短了会点到上一屏",
    "LordsScrollOnce": "= scene/lords_nav.SCROLL_PLAN.settle_ms（#42 真机：滚动后还有惯性，稳定前点行会点飞）",
}


def _beat_failures(files: dict | None = None, nav=None) -> list[str]:
    """节拍守卫：timeout ≤ 3000（新增节点必须显式声明）、post_delay ≤ 1000（白名单除外）。"""
    nav = _lords_nav() if nav is None else nav
    files = _pipelines() if files is None else files
    data = files.get(LORDS_FILE) or {}
    if not data:
        return [f"{LORDS_FILE} 读不到 —— 节拍预算无从检查"]
    msgs: list[str] = []

    for name, node in data.items():
        if not isinstance(node, dict):
            continue
        timeout = node.get("timeout")
        if name in LORDS_TIMEOUT_REQUIRED and timeout is None:
            msgs.append(
                f"{name}: 缺 timeout —— #100 新增的导航节点必须声明节拍上限（≤{LORDS_TIMEOUT_MAX_MS}ms）；"
                f"裸奔节点卡住时只能等任务级死线（运维看到的是「卡死」）"
            )
        elif timeout is not None and int(timeout) > LORDS_TIMEOUT_MAX_MS:
            msgs.append(
                f"{name}: timeout={timeout} > 上限 {LORDS_TIMEOUT_MAX_MS}ms —— "
                f"空转重试会把一次尝试拖成十几秒（#78 真机：WuchongSettleContinue 12.4s/次）"
            )
        post = 0 if node.get("post_delay") is None else int(node.get("post_delay"))
        if name in LORDS_POST_DELAY_EXEMPT:
            exempt = LORDS_POST_DELAY_EXEMPT[name]
            want = int(nav.SCROLL_PLAN.settle_ms) if exempt is None else int(exempt)
            if post != want:
                msgs.append(
                    f"{name}: post_delay={post} 与白名单/真源 {want} 不一致 —— "
                    f"这一等是有出处的（{LORDS_POST_DELAY_WHY.get(name, '见白名单')}），不许随手改"
                )
        elif post > LORDS_POST_DELAY_MAX_MS:
            msgs.append(
                f"{name}: post_delay={post} > 上限 {LORDS_POST_DELAY_MAX_MS}ms 且不在白名单 —— "
                f"每轮都白等（要留就写进 LORDS_POST_DELAY_EXEMPT，并说明为什么这一等不能省）"
            )

    dead = sorted(k for k in LORDS_POST_DELAY_EXEMPT if k not in data)
    if dead:
        msgs.append(f"节拍白名单里有不存在的节点 {dead}（写错/写空 = 守卫瞎了）")
    no_why = sorted(k for k in LORDS_POST_DELAY_EXEMPT if not LORDS_POST_DELAY_WHY.get(k))
    if no_why:
        msgs.append(f"节拍白名单 {no_why} 没写「为什么这一等不能省」—— 白名单不是免死金牌")
    if not LORDS_TIMEOUT_REQUIRED:
        msgs.append("LORDS_TIMEOUT_REQUIRED 被清空 —— 新节点的 timeout 又没人管了")
    return msgs


def probe_lords_beat_budget() -> bool:
    """#100：lords.json 的节拍预算（timeout ≤3000 / post_delay ≤1000，白名单逐条带理由）。"""
    return _beat_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        HOOK_ID_PARSE,
        "#100",
        "`parse_progress` 正反例：真机原样 通关数3/4 / 夹「全」/ 全角 / 分隔符抖动都读对；"
        "歧义 3/4/5、裸数字、三位数、错标签一律拒收；正则不许被放宽成裸 (\\d+)/(\\d+)",
        probe_lords_progress_parse,
    ),
    (
        HOOK_ID_PLAN,
        "#100",
        "`plan_round`：全 M/M → 无目标；N<M → 链[N]；链未采集 → difficulty=None + no_chain；"
        "N>M → 抛 LordsDataError；未知行 / M 冲突 → 点名不规划；零行 ≠ 全通；全量扫描 LORDS",
        probe_lords_plan_round,
    ),
    (
        HOOK_ID_STOP,
        "#100",
        "三条终结条件：全 M/M（主）/ 连续 2 轮无新解锁 / 场次上限 60，各带用户可见原因；"
        "零行却判全通 → 按失败收工（不许假收工）",
        probe_lords_stop_conditions,
    ),
    (
        HOOK_ID_DEADLOOP,
        "#100",
        "★防死循环★：`played == 0` 的任何状态都必须收工（零目标 / 计划了没打），"
        "且两者原因不同；真打了就不许被拦",
        probe_lords_no_deadloop,
    ),
    (
        HOOK_ID_WIRING,
        "#100",
        "`lords.json` 形状（四业务节点 + 枢纽自环 + on_error 回枢纽 + StopTask 出口 + 无写死坐标）"
        "、进列表判据逐字等于 SpecialOpenLord、引用节点都存在、两个自定义名双端登记、"
        "【挑战】判据 == scene.challenge 真源",
        probe_lords_pipeline_wiring,
    ),
    (
        HOOK_ID_AGENT,
        "#100",
        "`lords_impl` 离线行为（假 OCR + 假点击）：读完给结构化 name/n/m/box、三跳点中心正确、"
        "点下挑战记 1 场、禁双击、20s 点不出去带原因收工、全 M/M 当场收工、两条路都断时不假成功",
        probe_lords_agent_offline,
    ),
    (
        HOOK_ID_INSTALL_SNAPSHOT,
        "#100",
        "★安装态单源（一）★`lords_impl` 的逐字冻结快照 == 真源：正则串 / {行名: M} / {行名: 解锁链} / "
        "行名表 / 行名正则表 / 阈值 / PROBLEM_* / 难度词表逐项相等，且 plan_round / should_stop / "
        "group_progress_rows / parse_progress / round_gained 的行为表逐项相等（覆盖 no_chain / "
        "m_conflict / unknown_row / duplicate_row / played==0 / N>M 抛错）",
        probe_lords_install_snapshot_parity,
    ),
    (
        HOOK_ID_INSTALL_BEHAVIOR,
        "#100",
        "★安装态单源（二）★把 scene/ 摘掉（= 真实安装态）：_logic() 回落快照、_registry()/_row_regex() "
        "用冻结表，识别仍命中、三跳点中心一致、点挑战记一场，且与仓库态结果逐项相同",
        probe_lords_install_behavior_parity,
    ),
    (
        HOOK_ID_TAB,
        "#100",
        "★页签切换★判据逐字段等于 scene.page_rules（领主战/降临讨伐页签）；点击点 = 真机帧标签框中心 "
        "（与 SpecialTab* 实测点 (180,405)/(540,404) 对账）；切后确认只认**行族身份证据**"
        "（两个标签常驻同屏，读得到标签不算确认）；失败只许 1 次、绝不重试（#19）；不确认必有界收工",
        probe_lords_tab_confirm,
    ),
    (
        HOOK_ID_SCROLL,
        "#100",
        "★列表滚动★`lords.json` 全文件无 `max_hit`（#50：按任务共享的计数用尽即被静默跳过）；"
        "时间闩 ≥1.2s + 几何到底判据（连续 2 个**滚动世代**「无新行 ∧ 无位移」；同一世代重复读不重复记账、"
        "没真的滚过不记账）+ 每页上限用尽**带原因收工**；"
        "手势几何（400px / 800ms / 严格竖直 / 两端在列表体 440~1180）与 SCROLL_PLAN 逐字段一致",
        probe_lords_scroll_latch,
    ),
    (
        HOOK_ID_DEDUP,
        "#100",
        "★滚动去重★键 = (行名, N/M)：重叠两屏只记一次、进度变化算新读数、累计里无重复键，"
        "且去重后的 `plan_round` 不会把同一行打两遍（也不报 duplicate_row）",
        probe_lords_scroll_dedup,
    ),
    (
        HOOK_ID_NAV_PARITY,
        "#100",
        "★导航安装态单源★`lords_impl` 的导航冻结快照 == `scene/lords_nav.py`："
        "常量 / 页签锚点（判据 ROI 点击点）/ 滚动计划逐字段相等，且同一段剧本（到底 / 时间闩 / "
        "切换 / 拒绝 / 扫描推进）行为逐项相同",
        probe_lords_nav_snapshot_parity,
    ),
    (
        HOOK_ID_NAV_AGENT,
        "#100",
        "★导航 agent 行为★（假 OCR + 假时钟 + 假点击）：页扫描累计按行名留最新、切页签给当帧标签框且确认后不再点、"
        "滚动时间闩拒连甩、到底按**滚动世代**记账（同一屏重读不攒数）、到底后推进页签、两个页签扫完把"
        "**整份读数**交给 mode=read 判一轮，且**下一轮重新武装**（目标页签回到 LORD_TABS[0]）",
        probe_lords_nav_agent_offline,
    ),
    (
        HOOK_ID_ROUND,
        "#100",
        "★两轮之间（R1/R2）★累计表按**行名**留最新读数（喂 1/4 + 2/4 → 目标是「高级+」而不是已通关的「高级」）；"
        "**每轮 begin_round 重新武装**扫描（复位 sweep + 清累计，否则第 2 轮 desired_tab()=None → 一个页签都不切）；"
        "mode=read 的**扫描闸**（扫描阶段 + 页签未确认 ⇒ 不按单帧规划）",
        probe_lords_round_rearm,
    ),
    (
        HOOK_ID_BEAT,
        "#100",
        "★lords 节拍预算★timeout ≤3000ms（#100 新增的 5 个导航节点必须显式声明）、post_delay ≤1000ms"
        "（白名单：切页签 1200 / 战斗 HUD 2000 / 进列表 2500 / 滚动 2600==SCROLL_PLAN.settle_ms，"
        "每条都写清「为什么这一等不能省」）",
        probe_lords_beat_budget,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（10 条；全部在内存里做，绝不改真仓库）
# ---------------------------------------------------------------------------
def _prove_red_checks() -> list[tuple[str, bool, str]]:
    lu = _lords_unlock()
    impl = _impl()
    checks: list[tuple[str, bool, str]] = []

    def _record(name: str, msgs: list[str]) -> None:
        checks.append((name, bool(msgs), msgs[0] if msgs else ""))

    # ① parse_progress 放宽成裸 (\\d+)/(\\d+)
    import re as _re

    def _loose_parse(text):
        match = _re.search(r"(\d+)\s*/\s*(\d+)", str(text or ""))
        return (int(match.group(1)), int(match.group(2))) if match else None

    _record("① parse_progress 放宽成裸 (\\d+)/(\\d+)", _parse_failures(parse=_loose_parse))

    # ② plan_round 改成「一行也不规划、直接当全通」
    def _lazy_plan(rows, registry=None):
        return lu.RoundPlan(targets=(), all_done=True, rows=(), problems=())

    _record("② plan_round 永不规划、直接判全通", _plan_failures(plan=_lazy_plan))

    # ③ should_stop 恒返回「继续」
    def _never_stop(state):
        return (False, "")

    _record("③ should_stop 恒返回「继续」", _stop_failures(stop=_never_stop) + _deadloop_failures(stop=_never_stop))

    # ④ 【挑战】快照改回旧形状（漏带箭头那半帧）
    old_shape = "^挑战" + "$"          # 运行期拼出来：本文件不做「活跃使用」被别的 ratchet 抓
    _record("④ 编队页【挑战】快照改回旧形状（漏带箭头）", _wiring_failures(challenge_patterns=(old_shape,)))

    # ⑤ runner 注册表摘掉两个名字（真机上会静默 no-op）
    harness = _harness()
    _record(
        "⑤ runner 注册表摘掉 lords_progress / lords_unlock_step",
        _wiring_failures(
            reco_registry={k: v for k, v in harness.CUSTOM_RECOGNITIONS.items() if k != RECO_NAME},
            action_registry={k: v for k, v in harness.CUSTOM_ACTIONS.items() if k != ACTION_NAME},
        ),
    )

    # ⑥ 「点过挑战」的闩失效（允许连点两次挑战）
    saved = impl.LordsProgressRecognition._release_challenge_latch
    try:
        impl.LordsProgressRecognition._release_challenge_latch = staticmethod(
            lambda session: setattr(session, "challenge_pending", False)
        )
        _record("⑥ 禁双击的闩失效（允许连点两次挑战）", _agent_failures())
    finally:
        # ★必须包回 staticmethod★：直接赋函数会变成「实例方法」，后面的挂点一调用就
        # TypeError（takes 1 positional argument but 2 were given）—— 破坏实验不许把仓库态搞坏。
        impl.LordsProgressRecognition._release_challenge_latch = staticmethod(saved)

    # ⑦ ★快照漂移★：冻结的解析正则放宽成裸 (\d+)/(\d+)（安装态会把时间/分数读成进度）
    real_re, real_res = impl._PROGRESS_RE_SNAPSHOT, impl._PROGRESS_RES_SNAPSHOT
    try:
        loose = _re.compile(r"(\d+)\s*/\s*(\d+)")
        impl._PROGRESS_RE_SNAPSHOT = loose.pattern
        impl._PROGRESS_RES_SNAPSHOT = loose
        _record("⑦ 快照正则放宽成裸 (\\d+)/(\\d+)（快照漂移）", _snapshot_parity_failures())
    finally:
        impl._PROGRESS_RE_SNAPSHOT = real_re
        impl._PROGRESS_RES_SNAPSHOT = real_res

    # ⑧ ★快照漂移★：冻结的 M 表把妖狐讨伐改成 3（安装态会按错的分母取档）
    real_m = dict(impl._LORDS_M_SNAPSHOT)
    try:
        impl._LORDS_M_SNAPSHOT["妖狐讨伐"] = 3
        _record("⑧ 快照 M 表把妖狐讨伐改成 3（快照漂移）", _snapshot_parity_failures())
    finally:
        impl._LORDS_M_SNAPSHOT.clear()
        impl._LORDS_M_SNAPSHOT.update(real_m)

    # ⑨ ★只改真源、不改快照★：scene/lords.py 的妖狐讨伐多一档（真机若真加了档，快照必须跟上）
    lords = _lords()
    real_lords = tuple(lords.LORDS)
    try:
        import dataclasses as _dataclasses

        lords.LORDS = tuple(
            _dataclasses.replace(entry, tier_chain=tuple(entry.tier_chain) + ("地狱级",), max_tiers=5)
            if entry.row_name == "妖狐讨伐"
            else entry
            for entry in real_lords
        )
        _record("⑨ 只改真源（妖狐讨伐多一档）不改快照", _snapshot_parity_failures())
    finally:
        lords.LORDS = real_lords

    # ⑩ ★安装态回落被摘掉★：_SnapshotLogic 打桩成 None（回到「识别不命中」的老毛病）
    real_shim = impl._SnapshotLogic
    try:
        impl._SnapshotLogic = None
        _record("⑩ 安装态回落被摘掉（_SnapshotLogic -> None）", _install_behavior_failures())
    finally:
        impl._SnapshotLogic = real_shim
        impl.reset_sessions()

    # ------------------------------------------------------------------
    # ⑪–⑯ ★本票三条（页签 / 滚动 / 去重）各自的破坏实验★
    # ------------------------------------------------------------------
    import dataclasses as _dc
    import types as _types

    nav = _lords_nav()

    def _fake_nav(**overrides):
        """复制一份真源模块的命名空间，按需替换若干属性（破坏实验专用，不改真仓库）。"""
        ns = {
            name: getattr(nav, name)
            for name in dir(nav)
            if not name.startswith("__")
        }
        ns.update(overrides)
        return _types.SimpleNamespace(**ns)

    # ⑪ 去掉时间闩（连甩）：min_interval_sec 1.2 → 0.1
    _record(
        "⑪ 去掉滚动时间闩（min_interval_sec 1.2 → 0.1）",
        _scroll_failures(nav=_fake_nav(SCROLL_PLAN=_dc.replace(nav.SCROLL_PLAN, min_interval_sec=0.1))),
    )

    # ⑫ 去掉到底判据（observe 恒「还没到底」）
    class _NeverEnd(nav.NavState):
        def observe(self, rows, *, anchor_hit=None):
            return (False, "永远没到底")

    _record("⑫ 去掉到底判据（observe 恒 False）", _scroll_failures(nav=_fake_nav(NavState=_NeverEnd)))

    # ⑬ 允许用 max_hit 当「滚几次」的上限（#50 的形态）
    tmp_root = Path(_tempfile.mkdtemp(prefix="wf_hook100_"))
    try:
        import shutil as _shutil

        _shutil.copytree(REF_PIPELINE_DIR, tmp_root / PIPELINE_REL)
        broken = tmp_root / PIPELINE_REL / LORDS_FILE
        text = broken.read_text(encoding="utf-8")
        broken.write_text(
            text.replace('"post_delay": 2600,', '"post_delay": 2600,\n        "max_hit": 80,', 1),
            encoding="utf-8",
        )
        bad_files = _drift().load_pipelines(tmp_root / PIPELINE_REL)
        _record("⑬ 给滚动节点加回 max_hit: 80（#50 的坑）", _scroll_failures(files=bad_files))
    finally:
        import shutil as _shutil2

        _shutil2.rmtree(tmp_root, ignore_errors=True)

    # ⑭ 去掉页签确认（有标签就算确认 —— 两个标签常驻同屏，等于没确认）
    def _labels_confirm(items, registry=None):
        return nav.TabEvidence(
            list_page=True,
            labels=frozenset(nav.LORD_TABS),
            confirmed="领主战",
            kinds=("lord",),
            unknown_rows=(),
        )

    _record("⑭ 去掉页签确认（有标签就算确认）", _tab_failures(nav=_fake_nav(tab_state=_labels_confirm)))

    # ⑮ 页签失败重试（TAB_SWITCH_MAX_ATTEMPTS 1 → 3，#19 的竞速死循环）
    _record(
        "⑮ 允许页签切换重试 3 次（#19 竞速）",
        _tab_failures(nav=_fake_nav(TAB_SWITCH_MAX_ATTEMPTS=3)),
    )

    # ⑯ 去重键退化成「只有行名」（进度变化被吞）
    _record(
        "⑯ 去重键退化成只有行名",
        _dedup_failures(nav=_fake_nav(row_key=lambda row: (getattr(row, "name", None) or row[0],))),
    )

    # ⑰ ★导航快照漂移★：把页签锚点的 ROI 改坏（安装态会点错页签）
    real_tab_anchor = getattr(impl, "_TAB_ANCHOR_SNAPSHOT")
    try:
        drift_anchor = {k: dict(v) for k, v in real_tab_anchor.items()}
        drift_anchor["降临讨伐"]["roi"] = (0, 375, 360, 60)
        impl._TAB_ANCHOR_SNAPSHOT = drift_anchor
        impl._NavSnapshotLogic.TAB_ANCHORS = {
            tab: impl._TabAnchorSnapshot(tab=tab, **spec) for tab, spec in drift_anchor.items()
        }
        _record("⑰ 导航快照的页签 ROI 漂移", _nav_parity_failures())
    finally:
        impl._TAB_ANCHOR_SNAPSHOT = real_tab_anchor
        impl._NavSnapshotLogic.TAB_ANCHORS = {
            tab: impl._TabAnchorSnapshot(tab=tab, **spec) for tab, spec in real_tab_anchor.items()
        }

    # ⑱ ★导航快照漂移★：把滚动计划的时间闩改成 0.1（安装态会连甩）
    real_plan = impl._NavSnapshotLogic.SCROLL_PLAN
    try:
        impl._NavSnapshotLogic.SCROLL_PLAN = _dc.replace(real_plan, min_interval_sec=0.1)
        _record("⑱ 导航快照的时间闩漂移（1.2 → 0.1）", _nav_parity_failures())
    finally:
        impl._NavSnapshotLogic.SCROLL_PLAN = real_plan

    # ⑲ ★导航 glue 被摘掉★：`mode=page` 不再累计读数（= 页扫描形同虚设）
    real_page = impl.LordsProgressRecognition._page
    try:
        impl.LordsProgressRecognition._page = lambda self, *a, **k: impl._no_hit("页扫描被摘掉了")
        _record("⑲ 页扫描被摘掉（mode=page 不再读行）", _nav_agent_failures())
    finally:
        impl.LordsProgressRecognition._page = real_page
        impl.reset_sessions()

    # ⑳ ★R1 回归★：累计表退回「按 row_key 存多条」（第 2 轮会在旧/新读数之间取旧的那条）
    def _by_row_key(self, rows, now=None):
        new, dup = [], []
        for row in rows or ():
            key = nav.row_key(row)
            if key in self.seen:
                dup.append(key)
                continue
            self.seen[key] = row
            new.append(key)
        return (tuple(new), tuple(dup))

    real_add = nav.NavState.add_rows
    try:
        nav.NavState.add_rows = _by_row_key
        _record("⑳ 累计表退回按 row_key 存多条（R1：会反复打刚打完的档）", _round_rearm_failures())
    finally:
        nav.NavState.add_rows = real_add

    # ㉑ ★R2 回归★：begin_round 只做 reset_page（扫描不重新武装）
    real_begin = nav.NavState.begin_round
    try:
        nav.NavState.begin_round = lambda self, now=None: self.reset_page()
        _record("㉑ begin_round 不重新武装（R2：第 2 轮一个页签都不切）", _round_rearm_failures())
    finally:
        nav.NavState.begin_round = real_begin

    # ㉒ ★世代回归★：note_scroll 不再推进滚动世代（同一屏重读就能凑「到底」）
    real_note = nav.NavState.note_scroll

    def _no_gen(self, now):
        self.scrolls_in_page += 1
        self.last_scroll_at = now
        self.note_progress(now)

    try:
        nav.NavState.note_scroll = _no_gen
        _record("㉒ 滚动不推进世代（同一屏重读就能判到底）", _round_rearm_failures())
    finally:
        nav.NavState.note_scroll = real_note

    # ㉓ ★扫描闸回归★：mode=read 绕过扫描闸（扫描阶段按错页签的单帧规划）
    real_gate = impl.LordsProgressRecognition._scan_gate
    try:
        impl.LordsProgressRecognition._scan_gate = staticmethod(lambda items, session: "")
        _record("㉓ mode=read 绕过扫描闸（错页签的单帧也照常规划）", _round_rearm_failures())
    finally:
        impl.LordsProgressRecognition._scan_gate = staticmethod(real_gate)
        impl.reset_sessions()

    # ㉔ ★节拍回归★：把 LordsScanPage.post_delay 拉过上限（每个业务轮都白等）
    beat_root = Path(_tempfile.mkdtemp(prefix="wf_hook100_beat_"))
    try:
        import shutil as _shutil3

        _shutil3.copytree(REF_PIPELINE_DIR, beat_root / PIPELINE_REL)
        broken = beat_root / PIPELINE_REL / LORDS_FILE
        broken.write_text(
            broken.read_text(encoding="utf-8").replace(
                '"post_delay": 400,\n        // 节拍预算：timeout 3000（#100 新增节点必须显式声明上限',
                '"post_delay": 4000,\n        // 节拍预算：timeout 3000（#100 新增节点必须显式声明上限',
                1,
            ),
            encoding="utf-8",
        )
        _record(
            "㉔ 给 LordsScanPage.post_delay 写 4000（越过节拍预算）",
            _beat_failures(files=_drift().load_pipelines(beat_root / PIPELINE_REL)),
        )
    finally:
        import shutil as _shutil4

        _shutil4.rmtree(beat_root, ignore_errors=True)

    # ㉕ ★节拍回归★：删掉新增导航节点的 timeout（裸奔）
    beat_root2 = Path(_tempfile.mkdtemp(prefix="wf_hook100_beat2_"))
    try:
        import shutil as _shutil5

        _shutil5.copytree(REF_PIPELINE_DIR, beat_root2 / PIPELINE_REL)
        broken = beat_root2 / PIPELINE_REL / LORDS_FILE
        text = broken.read_text(encoding="utf-8")
        broken.write_text(
            text.replace('        "timeout": 3000,\n', "", 1), encoding="utf-8"
        )
        _record(
            "㉕ 删掉一个新增节点的 timeout（节拍裸奔）",
            _beat_failures(files=_drift().load_pipelines(beat_root2 / PIPELINE_REL)),
        )
    finally:
        import shutil as _shutil6

        _shutil6.rmtree(beat_root2, ignore_errors=True)
    return checks


def prove_red() -> bool:
    """真实绿；25 条破坏实验各自如愿变红。"""
    print("hooks_100 prove-red：逐一破坏实现，要求十五个挂点各自变红")
    green = (
        probe_lords_progress_parse()
        and probe_lords_plan_round()
        and probe_lords_stop_conditions()
        and probe_lords_no_deadloop()
        and probe_lords_pipeline_wiring()
        and probe_lords_agent_offline()
        and probe_lords_install_snapshot_parity()
        and probe_lords_install_behavior_parity()
        and probe_lords_tab_confirm()
        and probe_lords_scroll_latch()
        and probe_lords_scroll_dedup()
        and probe_lords_nav_snapshot_parity()
        and probe_lords_nav_agent_offline()
        and probe_lords_round_rearm()
        and probe_lords_beat_budget()
    )
    print(
        f"  [{'PASS' if green else 'FAIL'}] 真实实现：读数 / 规划 / 终结 / 防死循环 / 接线 / agent 行为 / "
        f"安装态快照一致 / 安装态行为等价 / 页签确认 / 滚动闩 / 去重 / 导航快照一致 / 导航行为 / "
        f"两轮之间（R1/R2/扫描闸）/ 节拍预算（绿）"
    )
    if not green:
        for msg in (
            _parse_failures()
            + _plan_failures()
            + _stop_failures()
            + _deadloop_failures()
            + _wiring_failures()
            + _agent_failures()
            + _snapshot_parity_failures()
            + _install_behavior_failures()
            + _tab_failures()
            + _scroll_failures()
            + _dedup_failures()
            + _nav_parity_failures()
            + _nav_agent_failures()
            + _round_rearm_failures()
            + _beat_failures()
        ):
            print(f"      - {msg}")
        return False

    checks = _prove_red_checks()
    for name, red, first in checks:
        print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {first}" if first else ""))
    ok = green and all(red for _n, red, _f in checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
