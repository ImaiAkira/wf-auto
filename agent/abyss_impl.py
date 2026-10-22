# -*- coding: utf-8 -*-
"""「自动刷深渊EX」（深渊连战EX）状态机 —— 自定义识别 / 动作实现（#55 Phase 2）。

为什么要单独一个模块
--------------------
同 ``phantom_impl`` / ``side_impl``：本模块只依赖 ``maa.custom_recognition`` /
``maa.custom_action`` 与纯逻辑模块（``maa_util`` / ``progress``），**不导入
``maa.agent.agent_server``**。这样 MFAAvalonia 的 AgentServer 进程能 import 并在
``my_reco.py`` / ``my_action.py`` 里注册，离线/真机测试脚本也能直接在进程内 Resource 上注册。

★与幻想连战的关系（诚实交代）★
深渊连战EX 与幻想连战在**同一张终始之战列表页**、hub / 关卡选择 / 单人编队 / 结算 / 战斗
**逐处同形**（校准 §1）。本模块是把 ``phantom_impl`` 的判定**照搬**成深渊版：
  · 状态机骨架 / 账本 / 会话接管 / 有界收工 与 phantom_impl 同构（本票**不**创建
    ``agent/battle_loop_core.py`` —— 那条抽取在并行 lane，由 orchestrator 收口）；
  · 只保留**单人**路径：**不移植共斗房节点**（``AbyssCoop*`` / 招募 / 建立房间）——
    运维明确「深渊EX 只有单人，没有共斗」，memo §5 也拒绝为未证实的复杂度买单（YAGNI）。
  · 关卡编号用 **``第N战``**（深渊是 30 层线性阶梯），**不是**幻想的 ``第N关``。
  · **不关心有几套**：没有 ``target_sets`` 选项；一直往下刷 30 层，刷完（游戏自己跳回
    关卡选择页）继续 —— 由有界收工（连续认不出画面超过 ``lost_sec`` / 无进展 / 卡死）兜底，
    绝不无限空转。

★配置权威在 ``scene/abyss.py``★（ADR-0001）：横幅模板 / 二级页签列表 / 进关确认文案 /
阶梯规模 / 账本范围 / 状态词表都从那里取。本模块只实现「怎么跑」。安装态（``tools/install.py``
只随包发 ``agent/``、仓库根没有 ``scene/``）回退到本文件的**冻结快照**；快照由
``tools/contract_hooks/hooks_abyss.py`` 钉死「必须与 ``scene.abyss`` 逐字一致」，漂移即变红。

安全红线（继承本项目踩过的坑）
------------------------------
* 绝不 KeyEvent 4；返回一律用屏幕按钮。
* 绝不用「识别框 + 死偏移」猜按钮：``abyss_act`` 只点 OCR 到的按钮中心。
* 换日重进文案未实测到：只做【整句】匹配，绝不宽匹配；识别不了交给卡死兜底重开。

★#55 Phase 3：普通深渊 = 同一实现 + 场景数据（「只差导航」）★
----------------------------------------------------------
运维：「深渊和深渊EX 只有导航的区别」。普通深渊（``scene.abyss.ABYSS_PLAIN``）与 EX 在 hub /
关卡选择 / 单人编队 / 结算 / 战斗**逐处同形**，差异只有「横幅模板 / 进关确认文案 / 账本范围」——
前两者落在 ``assets/resource/pipeline/abyss.json``（模板匹配 / OCR 是流水线判据），后者在本模块。
故本模块**按场景 id 参数化**（:data:`_REGISTRY` + :data:`_ACTIVE_SCENE`），**不 fork 状态机**：
  · 入口节点 ``AbyssPlainEntry``（``abyss_scene`` set=true）声明本次任务的活动场景 id；
  · 共享节点不带 ``scene`` → 取【当前活动场景】的配置（账本 ``abyss_plain`` vs ``abyss``）；
  · 横幅 / 确认节点用 ``abyss_scene`` 门控 → 普通深渊任务不会误点「未通关」页签里可见的 EX 横幅。

★#117：终始之战页签「自证式校验」+ 空态不收工★
------------------------------------------------
真机A（2026-10-18 08:0x）三个页签全空时，``abyss_act step=tab`` 的 ``expect`` 写的是
「还是 zhongshi 就算通过」⇒ 每次点击都"校验通过"⇒ 与页签循环索引凑成无限三连。两处修法：

1. **页签校验不再看 state**：判据 = 「页签**内容区文本集合**必须变」（:func:`content_signature`
   + :func:`tab_switch_verdict`）；点到的页签本来就在选中态时内容区不变，那只记一笔连续计数，
   **一整轮无变化**才算切换失败，重试上限 ``TAB_SWITCH_RETRY_LIMIT`` = **1 次**（#19 的结论），
   之后 ``request_giveup(原因)`` 带原因退出。
2. **空态收工**：内容区出现锚点「没有相关的活动」（真源 ``ZHONGSHI_EMPTY_ANCHOR``，证据帧
   ``tools/frames/abyss_zhongshi_tabs.png``）⇒ 记该页签为空；**三个页签都记满** ⇒
   ``request_giveup("终始之战没有可打的关卡（三个页签均无内容）")``。
   收工出口仍是既有的 ``abyss_giveup``（``AbyssGiveUpRecognition`` 取走原因 → 写收工标记 →
   pipeline 的 ``AbyssGiveUp`` 节点 ``StopTask``），**不新造第二套收工语义**。

★#21 / ADR 0005 第 4 条：迷路后先「归位重导航」，2 次预算用尽才收工★
------------------------------------------------------------------
08:06 真机事故：任务被交接在「五重决战详情页」（主城分区深层页，``classify`` = **unknown**），
迷路闸门 60s 到点就收工，白等 300 秒零进度。本票把「迷路 → 收工」改成「迷路 → 先归位」：

  · ``abyss_giveup`` 到点只置 ``recover_pending``（**不写收工标记、不收工**），返回 box=None；
  · ``abyss_recover_gate`` 只在 ``recover_pending`` **且当前帧仍是 unknown** 时命中（门控叶）；
  · ``abyss_recover`` 点底部导航「主城」（页面判据 :func:`is_home_section_deep_page`）或
    左槽「返回」，然后由**既有**导航链（活动 → 终始之战 → 横幅）重进，不新造导航；
  · 2 次预算（:data:`MAX_RECOVERIES`）用尽仍迷路 → 收工，原因
    ``连续 {n}s 认不出画面（归位 2 次失败）``（前半句仍由 ``core.lost_reason`` 出）。

★为什么判据是纯 Python 函数、不是 ColorMatch★：颜色门在这件事上没有信息量（#29 的教训：
底导高亮只告诉我们「哪个分区」，这次要区分的是「主城分区的深层页 vs 主城本身」，
二者差的是最左槽「返回」这**一列文字**）。判据只用 OCR 文本 + 框中心，离线可复算。

★#11（进度可见 3/5）：深渊连战 + 深渊连战EX 接 :mod:`reporting`★
--------------------------------------------------------------
运维要求「深渊这类模式要显示进度」；裁决与口径的唯一真源是
``docs/spec/progress-visibility.md``（§B 出口 API / §C 深渊那两行）。

  * 一步 = **一次「第 N 战」记账**（账本 ``{scope}/stage/{N}`` 落盘成功，§C）；
    ``N`` 取账面/画面真实战号 —— ★中途接管从画面读数起算，**绝不从 1 数**★；
  * ``total`` = ``ScenarioTarget.max_stages``（30）、``unit`` = 「战」、``note`` = 圈次；
  * 开头（首次观察基准）``start()``；三处收工出口（零进度超时 / 无新关卡 / 已打完一圈）
    ``done(既有原因文案)``，既有 giveup 的另外两条原因（页签全空 / 切换失败）同样带出来；
  * ★进度行只在 :mod:`reporting` 拼格式★：本文件不出现 ``[进度]`` 字面量；
  * 机制日志（点击 / 账本 / 收工）**一行都不用改**：``--quiet`` 已把 ``sys.stdout``
    整体重定向到 ``debug/agent.log``（#142），所以这里既有的 ``print`` 自动归入机制日志。

★按「圈」分段，而不是一条线跑到黑★：``Progress.step`` 单调去重，而深渊阶梯每圈从
第 1 战重新数 —— 一条线走完 30 战之后，第二圈的 1..30 会被全部吞掉。故一圈一条线：
圈末 ``done``，既有的「阶梯重置」判据（:func:`_handle_possible_reset`）成立时新建下一条
（note=第 j 圈）。★本功能只显示，不改任何计数 / 收工 / 重置口径★。
"""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

import progress as ledger
import reporting
from maa_util import ocr_all, read_action_param, read_param

# ★#119：画面分类判据只有 battle_loop_core.classify 一份★（本文件只提供场景数据；
#   ``classify`` 是薄封装）。★别删下面这三个 re-export★：它们是“同一对象”契约的锚点 ——
#   hooks_63 钉 ``MAIN_CITY_UNIQUE_ANCHORS is core.MAIN_CITY_UNIQUE_ANCHORS``、
#   hooks_112 钉 ``has_challenge_page_text is core.has_challenge_page_text``
#   （各自复制一份判据 = 第二套真源，#63 的纪律）。
import battle_loop_core as core
from battle_loop_core import (  # noqa: F401 —— 共享判据的 re-export（守卫按对象同一性检查）
    MAIN_CITY_MIN_UNIQUE,
    MAIN_CITY_UNIQUE_ANCHORS,
    has_challenge_page_text,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# ★冻结快照★（安装态没有 ``scene/`` 时回退）；hooks_abyss 钉死它与 scene.abyss 逐字一致。
# ---------------------------------------------------------------------------
_ZHONGSHI_TABS_SNAPSHOT = ("未通关", "已通关", "完成")
_MAX_STAGES_SNAPSHOT = 30
_LEDGER_SCOPE_SNAPSHOT = "abyss"
_STAGE_RE_SNAPSHOT = r"第\s*(\d{1,2})\s*战"
_BANNER_TEMPLATE_SNAPSHOT = "banner_abyss_ex.png"
_BANNER_THRESHOLD_SNAPSHOT = 0.90
_CONFIRM_TEXT_SNAPSHOT = "挑战深渊连战EX"
_HUB_MATCH_SNAPSHOT = ("深渊连战",)
_MAIN_MATCH_SNAPSHOT = ("不可续战", "战斗记录", "推荐编成", "ABYSS ONSLAUGHT", "战斗")
_ACTIVE_STATES_SNAPSHOT = (
    "abyss_hub",
    "abyss_main",
    "abyss_solo_team",
    "abyss_settle",
    "abyss_battle",
)

# ★普通深渊（plain）冻结快照（#55 Phase 3）★——安装态没有 ``scene/`` 时回退。
# 只列与 EX **不同**的字段；页签 / hub / main / 状态集 / 阶梯规模 / 「第N战」正则
# **完全共享**上面的 EX 快照（「只差导航」的直接含义）。
_PLAIN_SCENE_SNAPSHOT = "abyss_plain"
_PLAIN_DISPLAY_SNAPSHOT = "深渊连战"
_PLAIN_BANNER_TEMPLATE_SNAPSHOT = "banner_abyss_plain.png"
_PLAIN_BANNER_THRESHOLD_SNAPSHOT = 0.90
# 负向先行断言破「深渊连战」⊂「深渊连战EX」子串歧义（模板是主判据，串只作兜底/日志）。
_PLAIN_BANNER_PATTERNS_SNAPSHOT = (r"深渊连战(?!\s*EX)", r"ABYSS ONSLAUGHT(?!\s+EX)")
_PLAIN_CONFIRM_TEXT_SNAPSHOT = "挑战深渊连战"
_PLAIN_LEDGER_SCOPE_SNAPSHOT = "abyss_plain"

# ★ADR 0005 / #19★ 「迷路」闸门（秒）：安装态没有 ``scene/`` 时的冻结快照（真源 =
# ``scene.abyss.LOST_SEC``，两个深渊场景同值）。证据（2026-10-19 真机逐帧重建）：本轮
# 725 帧 / 110 段 unknown，连续驻留中位 3s、p95 6s、最长 16s —— 全是正常转场，
# 60s = 最长段的 3.75× 余量，既不误杀转场，又能让真卡住的任务 1 分钟内带原因退出。
_LOST_SEC_SNAPSHOT = 60

# ★ADR 0005 第 4 条 / 票 #21★ 迷路后「归位重导航」的预算：最多 2 次，用尽才收工。
#   决策原文（ADR 0005）：「恢复先只给深渊……值得『归位重导航 → 继续』（最多 2 次）」。
#   ★为什么是 2 而不是无限★：归位是**有界**兜底 —— 第一次是「被交接在深层页」这种能救的
#   形态；第二次给「点完主城但导航又跑偏」留一次机会；第三次还迷路说明不是靠点主城能救的，
#   继续点只会把预算烧成空转（ADR 0005：任何闸门都不许无界）。
MAX_RECOVERIES = 2

# ★#27★ 「有正在挑战中的关卡」弹窗（真机 2026-10-20 01:25 证据帧）：
#   「挑战深渊连战 EX。若非通关或放弃正在挑战中的关卡，则无法挑战其他难度的极限战斗关卡」
#   弹窗盖住底导，归位点「返回」点空 → 60s×2 后收工。这里改成：点 **OK（继续）** 往下走
#   （运维裁决：这个弹窗要点 OK 才行，点取消只是退出）；兜底认不到 OK 才点「取消」。
#   连续 MAX_BLOCKED 次遇到弹窗仍没真正续上，才请求收工（原因写明需人工处理）。
#   ★为什么有界★：任何闸门都不许无界（ADR 0005）—— 无界重试会把整夜变成空转。
MAX_BLOCKED = 3

#: 归位判据的 720 空间 ROI —— **与 ``common.json`` 同源，绝不新造坐标**：
#:   · ``_RECOVER_HOME_ROI`` = ``PubReturnHomeText`` 的 OCR ROI ``[0,1180,720,100]``（底部导航带）；
#:   · ``_RECOVER_BACK_ROI`` = ``PubReturnHomeBackTab`` 的 OCR ROI ``[0,1180,110,100]``（最左槽）。
#: 两者都是 MAA 的 ``[x, y, w, h]`` 形状。
_RECOVER_HOME_ROI = (0, 1180, 720, 100)
_RECOVER_BACK_ROI = (0, 1180, 110, 100)

# ★#117★ 终始之战「空态 / 页签切换」判据（两个场景**共享**；真源在 ``scene.abyss``）。
#   证据帧：``tools/frames/abyss_zhongshi_tabs.png``（真机A，2026-10-18 08:0x；
#   720 空间 OCR 侧车 = 同名 ``.ocr.txt``：``没有相关的活动`` [240,789,237,37]）。
#   ★安装态没有 ``scene/`` ⇒ 这里是冻结快照，hooks_117 钉死「快照 == 真源」★。
_ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT = "没有相关的活动"
_ZHONGSHI_EMPTY_REASON_SNAPSHOT = "终始之战没有可打的关卡（三个页签均无内容）"
_TAB_SWITCH_RETRY_LIMIT_SNAPSHOT = 1
_ZHONGSHI_CONTENT_BOX_SNAPSHOT = (0, 445, 720, 1180)
#: 整轮页签扫描上限 + 扫完找不到横幅的收工原因模板（同属 #117；见 scene.abyss）。
_TAB_SCAN_ROUND_LIMIT_SNAPSHOT = 2
_TAB_SCAN_FAIL_REASON_SNAPSHOT = "终始之战扫过 {rounds} 轮页签都没有找到「{display}」横幅"


class _Snapshot:
    """安装态回退配置（字段与 ``scene.abyss.ScenarioTarget`` 同名）。"""

    scene = "abyss"
    display = "深渊连战EX"
    banner_template = _BANNER_TEMPLATE_SNAPSHOT
    banner_patterns = (r"深渊连战\s*EX", r"ABYSS ONSLAUGHT EX")
    tabs = _ZHONGSHI_TABS_SNAPSHOT
    confirm_text = _CONFIRM_TEXT_SNAPSHOT
    max_stages = _MAX_STAGES_SNAPSHOT
    ledger_scope = _LEDGER_SCOPE_SNAPSHOT
    stage_re = _STAGE_RE_SNAPSHOT
    banner_threshold = _BANNER_THRESHOLD_SNAPSHOT
    hub_match = _HUB_MATCH_SNAPSHOT
    main_match = _MAIN_MATCH_SNAPSHOT
    active_states = _ACTIVE_STATES_SNAPSHOT
    # #19 / ADR 0005：「迷路」闸门 = 连续 lost_sec 秒认不出画面（秒，不是帧）。
    lost_sec = _LOST_SEC_SNAPSHOT
    # #117：终始之战页签 / 空态判据（与真源 scene.abyss 逐字一致）。
    empty_anchor = _ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT
    empty_reason = _ZHONGSHI_EMPTY_REASON_SNAPSHOT
    tab_retry_limit = _TAB_SWITCH_RETRY_LIMIT_SNAPSHOT
    content_box = _ZHONGSHI_CONTENT_BOX_SNAPSHOT
    tab_scan_rounds = _TAB_SCAN_ROUND_LIMIT_SNAPSHOT
    tab_scan_reason = _TAB_SCAN_FAIL_REASON_SNAPSHOT


class _PlainSnapshot:
    """安装态回退配置（普通深渊；字段与 ``scene.abyss.ScenarioTarget`` 同名）。

    与 EX 快照**共享**页签 / hub / main / 状态集 / 阶梯 / 正则，只覆盖四个随场景变的字段
    （scene / display / 横幅模板+阈值 / 确认文案 / 账本范围）。
    """

    scene = _PLAIN_SCENE_SNAPSHOT
    display = _PLAIN_DISPLAY_SNAPSHOT
    banner_template = _PLAIN_BANNER_TEMPLATE_SNAPSHOT
    banner_patterns = _PLAIN_BANNER_PATTERNS_SNAPSHOT
    tabs = _ZHONGSHI_TABS_SNAPSHOT
    confirm_text = _PLAIN_CONFIRM_TEXT_SNAPSHOT
    max_stages = _MAX_STAGES_SNAPSHOT
    ledger_scope = _PLAIN_LEDGER_SCOPE_SNAPSHOT
    stage_re = _STAGE_RE_SNAPSHOT
    banner_threshold = _PLAIN_BANNER_THRESHOLD_SNAPSHOT
    hub_match = _HUB_MATCH_SNAPSHOT
    main_match = _MAIN_MATCH_SNAPSHOT
    active_states = _ACTIVE_STATES_SNAPSHOT
    # #19 / ADR 0005：与 EX 共享「迷路」阈值（秒）。
    lost_sec = _LOST_SEC_SNAPSHOT
    # #117：与 EX 共享（「只差导航」的直接含义）。
    empty_anchor = _ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT
    empty_reason = _ZHONGSHI_EMPTY_REASON_SNAPSHOT
    tab_retry_limit = _TAB_SWITCH_RETRY_LIMIT_SNAPSHOT
    content_box = _ZHONGSHI_CONTENT_BOX_SNAPSHOT
    tab_scan_rounds = _TAB_SCAN_ROUND_LIMIT_SNAPSHOT
    tab_scan_reason = _TAB_SCAN_FAIL_REASON_SNAPSHOT


def _load_config():
    """从 ``scene.abyss`` 取真源（**两个场景**）；仓库根没有 ``scene/``（安装态）时回退冻结快照。

    返回 ``(registry, source)``：``registry`` = ``{scene_id: ScenarioTarget}``。
    ★#55 Phase 3★：普通深渊与深渊EX 是**两个场景 id**（``abyss`` / ``abyss_plain``），
    但共用同一套机制；差异只在数据（横幅模板 / 确认文案 / 账本范围）。
    """
    try:
        if not (_REPO_ROOT / "scene" / "abyss.py").is_file():
            raise ModuleNotFoundError(f"真源不在场：{_REPO_ROOT / 'scene' / 'abyss.py'}")
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scene.abyss import SCENARIOS  # noqa: PLC0415

        return {s.scene: s for s in SCENARIOS}, "scene"
    except ModuleNotFoundError:
        return {"abyss": _Snapshot(), "abyss_plain": _PlainSnapshot()}, "snapshot"


_REGISTRY, CFG_SOURCE = _load_config()

#: 已登记的场景 id（缺省场景在前）。数据权威在 ``scene.abyss.SCENARIOS``。
SCENES = tuple(_REGISTRY)
DEFAULT_SCENE = "abyss"

# ---------------------------------------------------------------------------
# 常量（值来自配置）
#
# ★模块级常量一律取【缺省场景 EX】★（向后兼容：既有守卫 / 调用方按名字消费它们）；
# 普通深渊用 :func:`_cfg` / :data:`_ACTIVE_SCENE` 取自己的配置。
# ---------------------------------------------------------------------------
CFG = _REGISTRY[DEFAULT_SCENE]
SCENE = CFG.scene
MAX_STAGES = CFG.max_stages
LEDGER_SCOPE = CFG.ledger_scope
ZHONGSHI_TABS = tuple(CFG.tabs)
STAGE_RE = re.compile(CFG.stage_re)
BANNER_TEMPLATE = CFG.banner_template
BANNER_PATTERNS = tuple(CFG.banner_patterns)
BANNER_THRESHOLD = CFG.banner_threshold
CONFIRM_TEXT = CFG.confirm_text
HUB_MATCH = tuple(CFG.hub_match)
MAIN_MATCH = tuple(CFG.main_match)
ACTIVE_STATES = tuple(CFG.active_states)

# ★#117★ 终始之战「空态 / 页签切换」判据（数据来自配置；两个场景共享）。
#   · ``ZHONGSHI_EMPTY_ANCHOR``：三个页签都没有内容时列表区的那句话（证据帧见模块顶部）；
#   · ``ZHONGSHI_EMPTY_REASON``：空态收工原因（用户可见一句话，走既有 abyss_giveup 出口）；
#   · ``TAB_SWITCH_RETRY_LIMIT``：页签切换失败的重试上限（#19：1 次后带原因退出）；
#   · ``ZHONGSHI_CONTENT_BOX``：「页签内容区」720 空间范围（判切换是否真的生效）；
#   · ``TAB_SCAN_ROUND_LIMIT`` / ``TAB_SCAN_FAIL_REASON``：整轮扫描上限与扫空的收工原因。
ZHONGSHI_EMPTY_ANCHOR = getattr(CFG, "empty_anchor", _ZHONGSHI_EMPTY_ANCHOR_SNAPSHOT)
ZHONGSHI_EMPTY_REASON = getattr(CFG, "empty_reason", _ZHONGSHI_EMPTY_REASON_SNAPSHOT)
TAB_SWITCH_RETRY_LIMIT = int(getattr(CFG, "tab_retry_limit", _TAB_SWITCH_RETRY_LIMIT_SNAPSHOT))
ZHONGSHI_CONTENT_BOX = tuple(
    getattr(CFG, "content_box", _ZHONGSHI_CONTENT_BOX_SNAPSHOT)
)
TAB_SCAN_ROUND_LIMIT = int(getattr(CFG, "tab_scan_rounds", _TAB_SCAN_ROUND_LIMIT_SNAPSHOT))
TAB_SCAN_FAIL_REASON = str(getattr(CFG, "tab_scan_reason", _TAB_SCAN_FAIL_REASON_SNAPSHOT))

# 「本轮已收工」标记：存在时下一次新任务清账（只在有界收工/告吹时写）。
# ★#55 Phase 3★：这是【缺省场景 EX】的键。普通深渊用 ``abyss_plain/run/completed`` ——
#   ``_sync_task`` / ``_mark_run_done`` 按【活动场景】的账本范围现算（见 ``_cfg().ledger_scope``），
#   故这里保留的只是 EX 的那一份（向后兼容）。
RUN_DONE_KEY = f"{LEDGER_SCOPE}/run/completed"

# 状态名（与 pipeline 的 abyss_state 参数一一对应）。
ABYSS_HUB = "abyss_hub"
ABYSS_MAIN = "abyss_main"
ABYSS_SOLO_TEAM = "abyss_solo_team"
ABYSS_SETTLE = "abyss_settle"
ABYSS_BATTLE = "abyss_battle"
ABYSS_LEVEL_REQUIRED = "abyss_level_required"

# ---------------------------------------------------------------------------
# ★#119★ 画面分类：判据只有 battle_loop_core.classify 一份（本文件只给场景数据）
#
# 下面是抽取前 ``abyss_impl.classify`` 里两条**场景判据**的原样搬移（它们从 #55 Phase 3 起
# 就是这个形状：hub/main 的差异属于场景，不属于共享判据）：
#   · hub  = `深渊连战 & !(不可续战｜战斗记录｜推荐编成)` **且** 任一 hub 标记在场；
#   · main = `(不可续战｜战斗记录) & (推荐编成｜ABYSS ONSLAUGHT｜战斗)`。
# 正例词表来自 ``scene.abyss.ScenarioTarget.hub_match/main_match``（真源，校准 §3.1）；
# 反例/标记词表是抽取前 classify 里的内联字面量，原样保留（改它 = 改判据，要单独走票）。
# ---------------------------------------------------------------------------
_HUB_NONE = ("不可续战", "战斗记录", "推荐编成")
_HUB_MARKERS = ("兑换道具", "通关奖励", "激战", "排名", "无尽战斗")
# 形状断言：HUB_MATCH 是「hub 主词」，MAIN_MATCH 前 2 = 关卡选择页反例、后 3 = 正例。
assert len(HUB_MATCH) == 1, f"HUB_MATCH 形状变了：{HUB_MATCH!r}（只取第 1 个作 hub 主词）"
assert len(MAIN_MATCH) == 5, (
    f"MAIN_MATCH 形状变了：{MAIN_MATCH!r}（前 2 = 不可续战/战斗记录，后 3 = main 正例）"
)
_MAIN_NONE = tuple(MAIN_MATCH[:2])
_MAIN_MARKERS = tuple(MAIN_MATCH[2:])


def _hub_match(has, texts):
    """深渊活动入口（hub）判据（抽取前 classify 第 9 条，逐字保留）。"""
    return (
        has(HUB_MATCH[0])
        and not any(has(x) for x in _HUB_NONE)
        and any(has(x) for x in _HUB_MARKERS)
    )


def _main_match(has, texts):
    """深渊关卡选择页（main）判据（抽取前 classify 第 10 条，逐字保留）。"""
    return any(has(x) for x in _MAIN_NONE) and any(has(x) for x in _MAIN_MARKERS)


#: ★#119★ 深渊的画面分类配置（唯一一份 classify 的**数据面**）。
#: ★只喂 classify★：深渊有自己的状态机（本文件），不需要 SceneConfig 的状态机字段。
#: 顺序 = 抽取前 ``abyss_impl.classify`` 的分支顺序（逐条对账见票 #119 的评论）：
#: 战斗 → 主城 → 活动 → 终始之战 → 单人编队 → 结算 → hub → main。
#: ★没有共斗房 / 招募弹窗分支★：运维裁决「深渊EX 只有单人，没有共斗」，hooks_abyss 钉着。
_CLASSIFY_ORDER = (
    "loading", "level_gate", "relogin", "battle", "main_city", "activity",
    "zhongshi", "party", "settle", "hub", "main",
)
_CLASSIFY_CFG = core.SceneConfig(
    scene="abyss",
    state_prefix="abyss",
    classify_order=_CLASSIFY_ORDER,
    zhongshi_tabs=ZHONGSHI_TABS,
    hub_match=_hub_match,
    main_match=_main_match,
)

# 主城独有锚点（≥2 才算主城，与 recover.json 一致）。
# ★#63★：主城判据不在本文件复制一份（复制即漂移）；改用共享源 agent/battle_loop_core 的
# 「三独有锚点 ≥2」判据（与 #31 的 harness、五重/幻想 同源）。六锚点会把编队页过渡帧 /
# 列表页误判成主城 —— 端到端表现为「点一下 → state=main_city → 空点击 → 重新导航」。
#
# ★#119★ 换日重进 / 130 级限制 / 战斗 HUD 三处判据也一并上提到 battle_loop_core（唯一一份）：
# 本文件曾经各存一份 _TIME_RE / _HHMM_RE / _BOTTOM_Y / DEFAULT_RELOGIN / LEVEL_GATE_HALVES
# 的副本 —— 那正是「#107 的修复只对五重生效」的形状。别再抄回来（hooks_119 会红）。

# 有界收工默认值（与 phantom 同源）。
# ★ADR 0005 / #19★ 「迷路」不再有本文件的默认**帧数**上限：量纲换成**秒**，真源在
#   ``scene.abyss.LOST_SEC``（按场景数据化，与 ``ZERO_PROGRESS_SEC`` 同一处）；override 的
#   ``lost_sec`` 优先。旧的帧数参数已全仓删除 —— 帧数随运行时长单调增长，无界会话必越线
#   （真机：深渊第 20 战的转场帧上以旧文案自杀，而那一轮 110 段 unknown 全是正常转场；
#   逐帧重建见 ADR 0005）。
DEFAULT_NO_PROGRESS_SEC = 900
#: ★#118★ 安装态快照（真源 = ``scene.abyss.ZERO_PROGRESS_SEC``）。
#: 零进度（一场都没完成）时的上限；比 900s 短，因为这类任务通常「打不过」而不是「慢」。
_ZERO_PROGRESS_SEC_SNAPSHOT = 300

_LOCK = threading.Lock()

#: ★#11★ 进度行的单位（口径 = ``docs/spec/progress-visibility.md`` §C：深渊一步 = 一战）。
#: display / 总量**都从配置取**（``_cfg().display`` / ``.max_stages``，真源 ``scene.abyss``）——
#: 这里只有「战」这个单位是场景常量，绝不写死场景名或 30。
PROGRESS_UNIT = "战"

# ---------------------------------------------------------------------------
# ★活动场景（#55 Phase 3）★：由入口节点经 ``abyss_scene``（set=true）声明本次任务的活动场景；
# 共享节点不带 scene → 取它。新任务（task_id 变化）重置为缺省 EX。默认 EX。
# ★赋值是原子的、不加 _LOCK★：``_sync_task`` 在持锁时调用它，加锁会自死锁。
# ---------------------------------------------------------------------------
_ACTIVE_SCENE = DEFAULT_SCENE


def _cfg(scene_id=None):
    """按场景 id 取配置；id 为空取【当前活动场景】。未登记的场景回退缺省 EX（绝不臆造）。"""
    sid = (scene_id or "").strip() or _ACTIVE_SCENE
    return _REGISTRY.get(sid) or _REGISTRY[DEFAULT_SCENE]


def _set_active_scene(scene_id):
    """设置当前活动场景（只接受已登记 id；空 / 未登记则不动）。"""
    global _ACTIVE_SCENE
    sid = (scene_id or "").strip()
    if sid in _REGISTRY:
        _ACTIVE_SCENE = sid


_STAGE_RE_CACHE: dict[str, re.Pattern] = {}


def _stage_re(cfg):
    """取某场景的「第N战」正则（编译缓存；EX 与普通深渊用同一条数据）。"""
    pat = cfg.stage_re
    reg = _STAGE_RE_CACHE.get(pat)
    if reg is None:
        reg = re.compile(pat)
        _STAGE_RE_CACHE[pat] = reg
    return reg


_SESSION = {
    "task_id": None,
    "cur_stage": None,          # 画面解析出的当前层（第N战）
    "max_done": 0,              # 账本里本场景已完成的最大层
    "session_max_done": 0,      # ★本次任务会话★实际结算过的最大层（重置/收工判据只看它）
    "joined_stage": None,       # 首次观察基准（中途接管以画面为准）
    "total_marks": 0,
    "ladder_cleared": False,    # 本次任务里是否打到过第 30 战
    "in_fight": False,
    "start_ts": 0.0,
    "last_progress_ts": 0.0,
    # ★ADR 0005 / #19★ 迷路时钟（替换旧的**帧数累计**计数器）：
    #   连续认不出画面的**秒**数由它算，阈值是 ``cfg.lost_sec``。
    "lost": core.LostClock(),
    "last_state": None,
    "last_observe_ts": 0.0,
    "tab_index": 0,             # 终始之战二级页签搜索索引（数据驱动，见 scene.abyss）
    # ★#117★ 终始之战页签扫描账本（只为「三个页签均无内容」与「切换失败」两个判据存在）：
    "tab_selected": None,       # 已确认站在哪个页签上（成功切换 / 空态观测后写入；未知 = None）
    "tab_sigs": {},             # 页签 -> 内容区文本集合签名（该页签被观测为其选中态时）
    "tab_empty": {},            # 页签 -> 是否「没有相关的活动」空态（三页签全 True = 收工）
    "tab_fail_streak": 0,       # 连续「点完内容区无变化、也不是空态」次数（重试上限靠它）
    "tab_switches": 0,          # 本次「在终始之战页上」成功切过的页签次数（整轮扫描上限靠它）
    "giveup_reason": None,      # 动作层请求收工的原因（由既有 abyss_giveup 出口消费，一次性）
    # ★ADR 0005 第 4 条 / #21★ 迷路后「归位重导航」预算（新任务在 ``_sync_task`` 里复位）：
    "recoveries": 0,            # 本次任务已用掉几次归位（上限 MAX_RECOVERIES）
    "recover_pending": False,   # 刚判到迷路、等 abyss_recover_gate 把这一帧交给归位动作
    # ★#27★ 「有正在挑战中的关卡」弹窗被取消后仍无法离开的次数（上限 MAX_BLOCKED）：
    "blocked_count": 0,
    # ★#11（进度可见）★ 用户可见进度线（**只显示**，不参与任何判据/记账）：
    "lap": 1,                   # 第几圈（只在既有「阶梯重置」判据成立时 +1，见 _handle_possible_reset）
    "progress": None,           # 本圈的 reporting.Progress（圈末 done；下一圈新建一条）
    "progress_done_reason": None,  # 已经报过的收工原因（同一条原因重复来时不再刷第二行）
}

# OCR 结果缓存（同一帧多次 OCR 复用）。
_OCR_CACHE: dict[tuple, list] = {}
_OCR_CACHE_TS: dict[tuple, float] = {}


# ---------------------------------------------------------------------------
# 图像 / OCR / 点击（与 phantom_impl 同构）
# ---------------------------------------------------------------------------
def _feature(image):
    try:
        import numpy as np

        a = np.asarray(image)
        if a.ndim == 3:
            a = a[:, :, :3]
        return (a.shape, int(a[::37, ::37].sum()))
    except Exception:  # noqa: BLE001
        return ("raw", id(image))


def _ocr(context, image, entry="OcrTask"):
    key = _feature(image)
    now = time.monotonic()
    cached = _OCR_CACHE.get(key)
    if cached is not None and (now - _OCR_CACHE_TS.get(key, 0.0)) < 1.5:
        return cached
    items = ocr_all(context, image, entry)
    _OCR_CACHE[key] = items
    _OCR_CACHE_TS[key] = now
    if len(_OCR_CACHE) > 24:
        oldest = sorted(_OCR_CACHE_TS, key=lambda k: _OCR_CACHE_TS.get(k, 0.0))[:12]
        for k in oldest:
            _OCR_CACHE.pop(k, None)
            _OCR_CACHE_TS.pop(k, None)
    return items


def _grab(context):
    return context.tasker.controller.post_screencap().wait().get()


def _click_box(context, cx, cy):
    """用 pipeline 原生 Click 动作点击 720 空间 (cx,cy)。

    ★为什么不用 controller.post_click★：部分 MaaFramework 原生库未导出
    ``MaaControllerPostClickV2``，Python binding 的 ``post_click`` 会 ACCESS_VIOLATION。
    改走 ``context.run_action("AbyssClick", box=...)``：由框架原生动作引擎执行 Click。
    """
    try:
        context.run_action("AbyssClick", box=(int(cx) - 1, int(cy) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[abyss] 点击失败 ({cx},{cy})：{exc}")
        return False


# ---------------------------------------------------------------------------
# ★ADR 0005 第 4 条 / 票 #21★ 迷路后「归位」的页面判据（纯函数，离线可求值、零设备）
#
# 08:06 事故（#21 背景）：任务被交接在「五重决战详情页」—— 深渊 ``classify`` 认不出它
# （``unknown``），只能干等 300 秒零进度收工。这一页是【主城分区的深层页】：底部导航有
# 「主城」、最左槽有「返回」；#29 让 ``PubReturnHome`` 故意不命中（它要求「其他分区高亮」，
# 见 common.json::PubReturnHomeOtherSection），所以归位判据要在这里补一份**只在迷路时用**的
# 版本 —— ★绝不进 ``classify`` / 常规状态机★（否则「主城深层页」变成已知页，迷路闸门失效）。
#
# 证据帧（``tools/frames``，720 空间 OCR 侧车 ``.ocr.txt``）：
#   · ``lord_mode_select.png``（五重决战详情页，classify=unknown）：
#       ``主城 [156,1245,45,28]`` + ``返回 [30,1247,47,25]`` ⇒ 本判据 **True**；
#   · ``lord_home_city.png``（主城，classify=main_city）：
#       ``主城`` 在，但最左槽是 ``主角色``、**没有「返回」** ⇒ **False**。
#
# ★不用 ColorMatch / 不校色★：颜色门在这里没有信息量 —— 要区分的是「同一个主城分区里
# 主城本身 vs 它的深层页」，二者差的是最左槽「返回」这**一列文字**，与配色无关。
# ---------------------------------------------------------------------------
def _box_center_in(box, roi) -> bool:
    """720 空间的框中心是否落在 ROI 内（``roi`` = MAA 的 ``[x, y, w, h]``）。"""
    try:
        x, y, w, h = (float(v) for v in roi)
        cx = float(box[0]) + float(box[2]) / 2.0
        cy = float(box[1]) + float(box[3]) / 2.0
    except (TypeError, ValueError, IndexError):
        return False
    return (x <= cx <= x + w) and (y <= cy <= y + h)


def _find_text_box(items, text, roi):
    """在 ROI 里按【整串相等】找 OCR 框 → ``(text, cx, cy)``；没有返回 ``None``。

    ★整串相等★（不是包含）：底导上「主城」「返回」都是短词，包含匹配会把
    「返回主城」「主角色」之类误当成按钮 —— 点错入口比不点更糟（#21：绝不盲点）。
    """
    want = (text or "").strip()
    for t, b in items or []:
        if not want or not b or len(b) != 4:
            continue
        if (t or "").strip() != want:
            continue
        if not _box_center_in(b, roi):
            continue
        return (t, b[0] + b[2] / 2.0, b[1] + b[3] / 2.0)
    return None


def is_home_section_deep_page(items) -> bool:
    """★#21★ 主城分区深层页：底部带里有「主城」，且最左槽里有「返回」。

    判定 = 存在文本 == "主城" 且中心落在 ``_RECOVER_HOME_ROI``（与 ``PubReturnHomeText``
    同一 ROI）、**并且** 存在文本 == "返回" 且中心落在 ``_RECOVER_BACK_ROI``（与
    ``PubReturnHomeBackTab`` 同一 ROI）。

    两个正反例（真机帧，见上面的证据段）：五重决战详情页 ⇒ True；主城本身 ⇒ False
    （主城最左槽是「主角色」，没有「返回」）。

    ★调用范围★：只允许 ``abyss_recover`` 动作在迷路时调用（守卫 ``hooks_abyss`` 的
    ``abyss-recover-judge-scoped`` 逐行把守）—— 不许进 ``classify`` / 常规状态机。
    """
    has_home = _find_text_box(items, "主城", _RECOVER_HOME_ROI) is not None
    if not has_home:
        return False
    return _find_text_box(items, "返回", _RECOVER_BACK_ROI) is not None


# ---------------------------------------------------------------------------
# 画面分类（#119：判据只有 battle_loop_core.classify 一份；本文件只提供场景数据）
#
# 抽取前这里是一份**完整副本**（与 battle_loop_core.classify 逐行重复）。代价见票 #119：
# #107 给共享 is_battle_hud 加的多视觉兜底**对深渊不生效**，同一帧共享判据 True、本文件的
# classify 却判 unknown。现在只剩薄封装 —— ★不许再在这里加分支★（hooks_119 ② 把守）。
# 深渊的差异（状态前缀 / 分支顺序 / 终始之战页签 / hub/main 判据）全部在
# 上面的 ``_CLASSIFY_CFG`` 里，顺序与抽取前逐条一致。
# ---------------------------------------------------------------------------
def classify(items, relogin_phrases=()):
    return core.classify(_CLASSIFY_CFG, items, relogin_phrases)


def parse_stage(items, cfg=None):
    """从关卡选择页 / 编队页卡片里解析「第N战」的 N；找不到返回 None。

    ★按活动场景取正则★（EX 与普通深渊同一条 ``第N战`` 数据，但坚持从配置取、不烧死假设）。
    """
    reg = _stage_re(cfg or _cfg())
    for t, _b in items or []:
        m = reg.search(t or "")
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# ★#117★ 终始之战：页签切换判据 + 空态收工判据（纯函数，离线可求值、零设备）
#
# 真机事故（设备A，2026-10-18 08:0x，见 scene.abyss 顶部）：三个页签全空时
# ``expect=["zhongshi", ...]`` 恒成立 ⇒ 每次点击都"校验通过" ⇒ 无限三连。
#
# 所以判据必须是**页面给出的新证据**：
#   · 内容区文本集合**变了**            ⇒ 切换真的生效（'switched'）；
#   · 内容区出现空态锚点                 ⇒ 这个页签确实没有内容（'empty'），继续搜别的页签；
#   · 两者都没有（集合一模一样也不是空态）⇒ 这次点击没产生可观测证据。
#
# ★为什么「没变化」不等于「切换失败」★：点到的页签**本来就在选中态**时，内容区当然不变
# （真机第一次点「未通关」时游戏多半就停在这页）。所以「没变化」只记一笔连续计数：
# 一整轮（len(tabs) 个页签）都没变化 = 切换失败，允许**再重试一整轮**（= 重试 1 次，
# ``TAB_SWITCH_RETRY_LIMIT``），仍失败 ⇒ 带原因收工（#19 的结论：不许多次重试）。
# ---------------------------------------------------------------------------
#: 页签切换判据的三种结论（+ 收工）。
TAB_SWITCH_SWITCHED = "switched"
TAB_SWITCH_EMPTY = "empty"
TAB_SWITCH_RETRY = "retry"
TAB_SWITCH_GIVEUP = "giveup"


def content_signature(items, box=None):
    """页签**内容区**的文本集合（720 空间；只取框中心落在内容区里的 OCR 项）。

    ★为什么用「文本集合」而不是「有没有字」★：页签栏（y≈386..424）与底部导航（y≈1244 起）
    是常驻元素，必须排除在外（:data:`ZHONGSHI_CONTENT_BOX` 已经切好）；集合相等 ⇒ 这一屏
    的内容区没有给出任何新信息。
    """
    x0, y0, x1, y1 = box or ZHONGSHI_CONTENT_BOX
    out = []
    for text, b in items or []:
        if not b or len(b) != 4:
            continue
        cx = b[0] + b[2] / 2.0
        cy = b[1] + b[3] / 2.0
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            continue
        s = (text or "").strip()
        if s:
            out.append(s)
    return tuple(sorted(out))


def has_empty_anchor(items, anchor=None):
    """这一帧有没有空态锚点「没有相关的活动」（整句子串；只在终始之战列表页有意义）。"""
    needle = anchor or ZHONGSHI_EMPTY_ANCHOR
    if not needle:
        return False
    return any(needle in (text or "") for text, _b in (items or []))


def tab_switch_budget(tabs=None, retry_limit=None):
    """★#117①★ 一次「页签切换」允许的**无证据点击数**上限。

    ``len(tabs)``（= 一整轮：每个页签各点一次都没给新证据才算失败）
    × ``(1 + retry_limit)``（= 允许重试 ``retry_limit`` 轮；真源取 1 ⇒ 一整轮重试）。
    真机含义：三个页签 ⇒ 首轮 3 次 + 重试轮 3 次 = **6 次**，之后必须带原因退出。
    """
    names = list(tabs if tabs is not None else ZHONGSHI_TABS)
    limit = TAB_SWITCH_RETRY_LIMIT if retry_limit is None else int(retry_limit)
    return max(1, len(names)) * (1 + max(0, limit))


def tab_switch_verdict(sig_before, sig_after, *, empty_after, streak, budget=None):
    """★#117①★ 页签切换判据（纯函数）。

    ``streak`` = **含本次**在内、连续「内容区无变化且非空态」的次数（1 起算）。
    ``budget`` = 允许的无证据点击数上限（真源 :func:`tab_switch_budget` = 6）。

    * ``empty_after``                  → :data:`TAB_SWITCH_EMPTY`（空页签不是失败）
    * 文本集合变了                      → :data:`TAB_SWITCH_SWITCHED`
    * 没变且 ``streak <  budget``       → :data:`TAB_SWITCH_RETRY`（继续扫 / 重试）
    * 没变且 ``streak >= budget``       → :data:`TAB_SWITCH_GIVEUP`（带原因收工）
    """
    limit = tab_switch_budget(None, None) if budget is None else int(budget)
    if empty_after:
        return TAB_SWITCH_EMPTY
    if tuple(sig_after or ()) != tuple(sig_before or ()):
        return TAB_SWITCH_SWITCHED
    return TAB_SWITCH_RETRY if int(streak) < limit else TAB_SWITCH_GIVEUP


def tabs_all_empty(tabs=None):
    """★#117②★ 本轮任务里，三个页签是否**都**已被确认「没有相关的活动」。

    账本 ``_SESSION["tab_empty"]`` 由 :meth:`AbyssActAction._run_tab_step` 每点一次页签填一笔；
    这是「三个页签均无内容」这句话的**唯一**依据（不靠推测，不靠单帧）。
    """
    names = [str(t) for t in (tabs if tabs is not None else ZHONGSHI_TABS)]
    if not names:
        return False
    with _LOCK:
        empty = dict(_SESSION["tab_empty"])
    return all(empty.get(name) for name in names)


def _tab_remember(name, sig, empty):
    """记一笔某页签的观测（内容区签名 + 是否空态）。"""
    with _LOCK:
        _SESSION["tab_sigs"][str(name)] = tuple(sig)
        _SESSION["tab_empty"][str(name)] = bool(empty)


#: 「已离开终始之战页」的状态：见到这些就把页签账本（空态 / 扫描计数）复位。
#: ★不含 loading / unknown★：它们是页内过渡帧，复位会把「三个页签均无内容」的连续证据打断。
_TAB_LEDGER_AWAY_STATES = (
    "main_city",
    "activity",
    ABYSS_HUB,
    ABYSS_MAIN,
    ABYSS_SOLO_TEAM,
    ABYSS_SETTLE,
    ABYSS_BATTLE,
    ABYSS_LEVEL_REQUIRED,
    "relogin",
)


def _tab_fail_streak(ok):
    """连续失败计数：``ok``（切换生效 **或** 明确空态）→ 清零；否则 +1。返回本次计数值。"""
    with _LOCK:
        _SESSION["tab_fail_streak"] = 0 if ok else int(_SESSION["tab_fail_streak"]) + 1
        return int(_SESSION["tab_fail_streak"])


def _tab_note_switch():
    """记一次「成功切到某个页签」（含空页签）；返回本次在页上累计的切换次数。"""
    with _LOCK:
        _SESSION["tab_switches"] = int(_SESSION["tab_switches"]) + 1
        return int(_SESSION["tab_switches"])


def reset_tab_ledger():
    """离开终始之战页时复位页签账本（空态 / 扫描上限都只统计**一次连续停留**内的证据）。"""
    with _LOCK:
        _SESSION["tab_selected"] = None
        _SESSION["tab_empty"] = {}
        _SESSION["tab_fail_streak"] = 0
        _SESSION["tab_switches"] = 0


def tab_scan_reason(cfg=None):
    """整轮扫描扫空时的收工原因（模板来自真源 ``TAB_SCAN_FAIL_REASON``）。"""
    conf = cfg or _cfg()
    template = str(getattr(conf, "tab_scan_reason", TAB_SCAN_FAIL_REASON))
    try:
        return template.format(rounds=TAB_SCAN_ROUND_LIMIT, display=conf.display)
    except (KeyError, IndexError, ValueError):
        return f"终始之战扫过 {TAB_SCAN_ROUND_LIMIT} 轮页签都没有找到「{conf.display}」横幅"


def request_giveup(reason):
    """★#117★ 动作层请求收工（一次性）：真正的出口仍是既有的 ``abyss_giveup``。

    ★为什么不在这里直接 StopTask★：收工要有**唯一**出口与唯一的记账位置
    （``_mark_run_done`` + 用户可见原因），否则会多出第二套收工语义。
    """
    text = str(reason or "").strip()
    if not text:
        return
    with _LOCK:
        if not _SESSION["giveup_reason"]:
            _SESSION["giveup_reason"] = text
    print(f"[abyss] 请求收工：{text}")


def _consume_giveup_reason():
    """取走并清空动作层请求的收工原因（一次性；没有则 None）。"""
    with _LOCK:
        reason = _SESSION["giveup_reason"]
        _SESSION["giveup_reason"] = None
    return reason


# ---------------------------------------------------------------------------
# 进度账本（30 层线性阶梯；无「套」概念）
#
# ★账本范围随活动场景（#55 Phase 3）★：EX = ``abyss``、普通深渊 = ``abyss_plain`` —— 两条
# 阶梯各自独立，绝不互相污染（否则跨场景 total_marks 会虚高、触发假的「阶梯记账数异常」收工）。
# ---------------------------------------------------------------------------
def _stage_key(stage_no, cfg=None):
    """账本 key：``{scope}/stage/{n}``（线性阶梯，n = 1..30；scope 随活动场景）。"""
    return f"{(cfg or _cfg()).ledger_scope}/stage/{int(stage_no)}"


def _scan_max_done(cfg=None):
    """账本里本场景（活动场景）已完成的最大层号。"""
    scope = (cfg or _cfg()).ledger_scope
    mx = 0
    for k in ledger.scope(f"{scope}/stage"):
        m = re.search(r"/stage/(\d+)$", k)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def _recover_counters(cfg=None):
    """用账本重建会话计数器（跨重开恢复）。返回 (max_done, total_marks)。"""
    cfg = cfg or _cfg()
    mx = _scan_max_done(cfg)
    total = len(ledger.scope(cfg.ledger_scope))
    with _LOCK:
        _SESSION["max_done"] = mx
        _SESSION["total_marks"] = total
    return mx, total


def _mark_run_done(cfg=None):
    """写「本轮已收工」标记：下一次新任务据此清账（按活动场景的账本范围）。"""
    key = f"{(cfg or _cfg()).ledger_scope}/run/completed"
    try:
        if ledger.mark_done(key):
            print(f"[abyss] 写入收工标记 {key}")
    except Exception as exc:  # noqa: BLE001
        print(f"[abyss] 写收工标记失败：{exc}")


def _sync_task(task_id, scene_id=None):
    """task_id 变化 = 新一轮任务；``scene_id`` 非空 = 该调用【声明】本次任务的活动场景。

    ★跨重开恢复★：账本里有收工标记 → 清空本场景账本；否则保留、按已记进度恢复。
    ★中途接管★：会话进度（session_max_done / joined_stage）一律从 0/None 起算，
      不拿旧账本去纠正画面（见 ``phantom_impl`` 的同名设计；#55 照搬）。
    ★活动场景（#55 Phase 3）★：新任务先重置为缺省 EX，再套用调用方声明的 scene_id
      （入口节点 ``AbyssPlainEntry`` 传 ``abyss_plain``）；同一任务内共享节点传 None =
      不改动（沿用入口声明的场景）。
    """
    if task_id is None:
        if scene_id:
            _set_active_scene(scene_id)
        return
    with _LOCK:
        new_task = _SESSION["task_id"] != task_id
        if not new_task and not scene_id:
            return
        if new_task:
            _SESSION["task_id"] = task_id
            _SESSION["cur_stage"] = None
            _SESSION["in_fight"] = False
            _SESSION["start_ts"] = time.monotonic()
            _SESSION["last_progress_ts"] = time.monotonic()
            # ★ADR 0005 / #19★ 新任务：迷路时钟整只归零（与 ``_SESSION`` 的缺省值同一份）。
            _SESSION["lost"].reset()
            _SESSION["last_state"] = None
            _SESSION["last_observe_ts"] = 0.0
            _SESSION["tab_index"] = 0
            # ★#117★ 页签扫描账本按任务复位（「三个页签均无内容」是**本轮任务**的结论）。
            _SESSION["tab_selected"] = None
            _SESSION["tab_sigs"] = {}
            _SESSION["tab_empty"] = {}
            _SESSION["tab_fail_streak"] = 0
            _SESSION["tab_switches"] = 0
            _SESSION["giveup_reason"] = None
            # ★ADR 0005 第 4 条 / #21★ 归位预算按任务复位（新任务重新拥有 2 次机会）。
            _SESSION["recoveries"] = 0
            _SESSION["recover_pending"] = False
            # ★#27★ 弹窗受阻计数也按任务复位。
            _SESSION["blocked_count"] = 0
            _SESSION["session_max_done"] = 0
            _SESSION["joined_stage"] = None
            _SESSION["ladder_cleared"] = False
            # ★#11★ 进度线按任务重置（新任务的第一次观察基准会 start 一条新的）。
            _SESSION["lap"] = 1
            _SESSION["progress"] = None
            _SESSION["progress_done_reason"] = None
            _set_active_scene(scene_id or DEFAULT_SCENE)
        elif scene_id:
            _set_active_scene(scene_id)

    cfg = _cfg()
    run_done_key = f"{cfg.ledger_scope}/run/completed"
    try:
        if ledger.is_done(run_done_key):
            n = ledger.reset(cfg.ledger_scope)
            print(f"[abyss] 新任务 task_id={task_id}：上一轮已收工，清空深渊账本（{n} 条）")
        else:
            print(f"[abyss] 新任务 task_id={task_id}：未发现收工标记，保留账本按进度继续")
    except Exception as exc:  # noqa: BLE001
        print(f"[abyss] 账本检查失败：{exc}")

    mx, total = _recover_counters(cfg)
    print(f"[abyss] 账本恢复：阶梯已到第 {mx} 战（账本共 {total} 笔）")


# ---------------------------------------------------------------------------
# ★#11（进度可见 3/5）★ 用户可见进度线：一圈一条 ``reporting.Progress``
#
# 口径唯一真源 ``docs/spec/progress-visibility.md``：
#   · §B：进度行**只许**从 :mod:`reporting` 出（本文件不拼 ``[进度]`` 字符串）；
#   · §C：深渊 / 深渊EX 一步 = 一次「第 N 战」记账（账本 ``{scope}/stage/{N}``），
#         total = ``max_stages``（30）→ ``i/30 战``，note = 圈次（第 j 圈）。
#
# ★为什么按「圈」分段，而不是一条线跑到黑★
# ``Progress.step`` 是**单调去重**的（倒退不出线，见 reporting 的文档）。深渊的阶梯每圈
# 从第 1 战重新数：一条线走完 30 战之后，第二圈的 1..30 会被全部吞掉 ⇒ 面板从第二圈起
# 就「死了」。所以一圈一条：圈末 ``done``（沿用既有「已打完一圈」文案），既有的阶梯重置
# 判据（:func:`_handle_possible_reset`）成立时新建下一条（note=第 j 圈）。
# ★本功能只显示，不改任何计数 / 收工 / 重置口径★（#118 的零进度上限、阶梯重置判据都不动）。
# ---------------------------------------------------------------------------
def _new_progress(cfg, lap):
    """按配置建一条进度线（**只**用 ``ScenarioTarget`` 的字段，不写死场景名/总量）。"""
    return reporting.Progress(
        cfg.display,
        total=cfg.max_stages,
        unit=PROGRESS_UNIT,
        note=f"第 {int(lap)} 圈",
    )


def _progress_new(cfg):
    """开一条新进度线并 ``start()``（首次观察基准 / 阶梯重置=新一圈两处调用）。

    ★调用方不要持 ``_LOCK``★：``start()`` 要写面板（日志坏了也不许影响跑图，
    :mod:`reporting` 自己兜住异常）。
    """
    with _LOCK:
        lap = int(_SESSION["lap"])
        line = _new_progress(cfg, lap)
        _SESSION["progress"] = line
        _SESSION["progress_done_reason"] = None
    line.start()
    return line


def _progress_step(cfg, stage_no):
    """记一步：**该战记账成功处**调用，``stage_no`` = 账面/画面真实战号（**不从 1 数**）。

    正常路径上进度线一定已由首次观察基准建好；万一没有（例如识别器只见过结算帧），
    这里兜底建一条再记 —— ``Progress`` 本身去重，绝不会因为兜底多出一条。
    """
    with _LOCK:
        line = _SESSION["progress"]
        lap = int(_SESSION["lap"])
        if line is None:
            line = _new_progress(cfg, lap)
            _SESSION["progress"] = line
    return line.step(int(stage_no))


def _progress_done(cfg, reason):
    """收工：把**既有原因文案**原样带出来（不新造一句话；``done`` 幂等）。

    当前这条线已经收过工（圈末 ``done``）时另起一条只装收工原因 —— 否则收工原因会被
    幂等吞掉，面板上就只剩「进度没了」，用户看不出为什么停。
    ★同一条原因重复回来不再刷第二行★（重复观察同一帧时面板不该出现两条一样的收工）。
    """
    text = str(reason)
    with _LOCK:
        line = _SESSION["progress"]
        lap = int(_SESSION["lap"])
        already = _SESSION["progress_done_reason"]
        if line is None or (line.done_reason and already != text):
            line = _new_progress(cfg, lap)
            _SESSION["progress"] = line
        _SESSION["progress_done_reason"] = text
    return line.done(text)


def _lap_cleared_reason(cfg):
    """「一圈打完」的既有文案（机制日志与进度收工**同一句话**，不新造第二份）。"""
    return f"已打完第 {cfg.max_stages} 战（一圈 {cfg.max_stages} 层全清）"


def _handle_possible_reset(n, cfg=None):
    """画面回到「第 1 战」而本次任务已推进到更靠后 → 判定为【阶梯重置/新一圈】，清账重记。

    与「接管」区分：接管时会话进度=0 → 不触发。与「本圈自然重来」一致：第 30 战结算后
    画面回第 1 战 → 会话进度=30 → 触发清账（新一轮），绝不把上一圈当异常。

    ★#11★ 圈次（``_SESSION["lap"]``）只在这里 +1 —— 这就是既有「新一圈」判据的**唯一**落点，
    本功能不另造一套圈次判据。
    """
    cfg = cfg or _cfg()
    with _LOCK:
        progress = _SESSION["session_max_done"]
    if progress < 2:
        return False
    try:
        cleared = ledger.reset(f"{cfg.ledger_scope}/stage")
    except Exception as exc:  # noqa: BLE001
        print(f"[abyss] 重置清账失败：{exc}")
        return False
    with _LOCK:
        _SESSION["max_done"] = 0
        _SESSION["session_max_done"] = 0
        _SESSION["cur_stage"] = n
        _SESSION["ladder_cleared"] = False
        _SESSION["total_marks"] = max(0, _SESSION["total_marks"] - cleared)
        _SESSION["lap"] = int(_SESSION["lap"]) + 1
    print(
        f"[abyss] 检测到阶梯重置：本次已打到第 {progress} 战，画面回到第 1 战 → "
        f"作废已记 {cleared} 笔（{cfg.ledger_scope}/stage/*），从第 1 战重新记"
    )
    # ★#11★ 新一圈 = 新一条进度线（上一条通常已在圈末 done；就算没有 —— 画面被判成重置的
    #   异常路径 —— 也照样开新的一条，**不新造收工原因**）。
    _progress_new(cfg)
    return True


def _observe(state, info, items, cfg=None):
    """按帧更新会话状态 / 账本（同一帧同一状态只记一次）。``cfg`` = 活动场景配置（#55 Phase 3）。"""
    cfg = cfg or _cfg()
    now = time.monotonic()
    with _LOCK:
        changed = state != _SESSION["last_state"]
        stale = (now - _SESSION["last_observe_ts"]) > 1.2
        if not changed and not stale:
            return
        _SESSION["last_observe_ts"] = now
        _SESSION["last_state"] = state
        # ★ADR 0005 / #19★ 迷路时钟在这里喂（持锁，且位置不能挪）：
        #   ① 必须在上面「changed/stale」早退**之后** —— 早退的帧是同一帧的重复观察，
        #      不该重复打点/清点；
        #   ② 必须在下面所有状态分支**之前** —— 那些分支各自 early return（关卡页 / 战斗 /
        #      结算 / unknown），若把喂钟放进分支里，「离开 unknown 命中已知页」这一帧会被
        #      ``return`` 吃掉 ⇒ 时钟永远不清点，越攒越长（正好是 ADR 0005 要消灭的累计语义）；
        #   ③ ``in_fight`` 从会话取：战斗 episode 内的 unknown 不记起点（#76 的结论并入原语）。
        _SESSION["lost"].observe(state, now, in_fight=bool(_SESSION["in_fight"]))

    # ★#21★ 画面重新认出已知页 ⇒ 这张「归位许可证」作废：
    #   ``recover_pending`` 只对「仍然迷路」的连续帧有意义。正常流程里 giveup 置完旗标
    #   紧接着就被同一条链上的 ``abyss_recover_gate`` 取走（同一帧、同一份 OCR），所以
    #   这里只是防御：万一门控因为异常没命中，绝不能让一次迷路在下一个正常转场的
    #   unknown 帧上误触「点主城」—— 那就不再是「迷路时归位」了。
    if state != "unknown":
        with _LOCK:
            _SESSION["recover_pending"] = False

    # ★#117★ 离开终始之战页 ⇒ 复位页签账本：空态（三个页签均无内容）与整轮扫描上限都只统计
    #   **一次连续停留**内的证据。否则「进关 → 打完一圈 → 又回到列表页」会把上一趟的页签
    #   记账带进来，可能凑出假的「三页签全空 / 扫过 2 轮」。
    #   ★只认「真的站在别的页面上」★：loading / unknown 是页内过渡帧，不能当离开。
    if state in _TAB_LEDGER_AWAY_STATES:
        reset_tab_ledger()

    # 「当前第几战」在【两条路径】上都解析（关卡选择页 / 单人编队页 —— 结算点「继续挑战」
    # 连打时不回关卡选择页，只有编队页还能读到关卡号）。
    if state in (ABYSS_MAIN, ABYSS_SOLO_TEAM):
        n = parse_stage(items, cfg)
        first_frame = False
        with _LOCK:
            if n is not None:
                if _SESSION["joined_stage"] is None:
                    _SESSION["joined_stage"] = n
                    first_frame = True
                if _SESSION["cur_stage"] != n:
                    where = "关卡选择页" if state == ABYSS_MAIN else "单人编队页"
                    print(f"[abyss] {where}：当前第 {n} 战")
                _SESSION["cur_stage"] = n
        if first_frame:
            print(f"[abyss] ★首次观察基准：画面第 {n} 战★（中途接管以画面为准，会话进度从 0 起算）")
            # ★#11★ 进度线从这里开始（§B：开头用 ``Progress.start()``）。
            #   ★中途接管时基准 = 画面读数★：这条线**不从 1 数** —— 第一条带数字的线是第一次
            #   「第 N 战」记账（N = 画面读数，例如 12/30），见下面的 ``_progress_step``。
            _progress_new(cfg)
            return
        if n == 1:
            _handle_possible_reset(n, cfg)
        return

    if state == ABYSS_BATTLE:
        with _LOCK:
            if not _SESSION["in_fight"]:
                print("[abyss] 进入战斗")
            _SESSION["in_fight"] = True
            # ★#28★ 归位预算「成功即回血」：进到战斗 = 真的续上了，把连续失败计数清零。
            #   ★为什么只在「进入战斗」回血，而不是见到任意已知页★：否则「已知页 ↔ unknown」
            #   的抖动会让预算变成事实上的无限（每次点完归位都会短暂看到已知页）；而连续失败时
            #   state 一直是 unknown，永远走不到这里 —— 于是「连续 2 次才收工」的语义保持不变。
            used = int(_SESSION["recoveries"])
            if used:
                _SESSION["recoveries"] = 0
                print(f"[abyss] 归位成功（已续跑）→ 归位预算复位（此前用掉 {used}/{MAX_RECOVERIES}）")
            # ★#27★ 弹窗受阻计数同样只在「真的进到战斗」时清零：否则
            #   「弹窗 → 取消 → 又弹」会无界打转（见 AbyssBlockedAction 的说明）。
            blocked = int(_SESSION["blocked_count"])
            if blocked:
                _SESSION["blocked_count"] = 0
                print(f"[abyss] 已续跑 → 弹窗受阻计数复位（此前 {blocked}/{MAX_BLOCKED} 次）")
        return

    if state == ABYSS_SETTLE:
        with _LOCK:
            cur = _SESSION["cur_stage"]
            in_fight = _SESSION["in_fight"]
        if cur is None:
            return
        newly = False
        try:
            newly = ledger.mark_done(_stage_key(cur, cfg))
        except Exception as exc:  # noqa: BLE001
            print(f"[abyss] 记账失败：{exc}")
        with _LOCK:
            if newly:
                _SESSION["total_marks"] += 1
                _SESSION["max_done"] = max(_SESSION["max_done"], cur)
            _SESSION["session_max_done"] = max(_SESSION["session_max_done"], cur)
            _SESSION["last_progress_ts"] = now
            _SESSION["in_fight"] = False
            if cur >= cfg.max_stages:
                # 第 30 战 = 一圈打完。清掉 cur_stage，防同一结算页后续帧把 30 错记到下一圈。
                _SESSION["ladder_cleared"] = True
                _SESSION["cur_stage"] = None
            mx = _SESSION["max_done"]
        if newly and in_fight:
            print(f"[abyss] 第 {cur} 战完成（已记账；阶梯最高第 {mx} 战）")
        # ★#11★ 一步 = 该战**记账成功**（``{scope}/stage/{cur}`` 已在上面的 mark_done 落盘）。
        #   ★只认 ``newly``★：同一结算页被重复观察、或账本里本来就有这一战（中途接管）都不出线；
        #   ``n`` 用画面/账面真实战号 ``cur``，**绝不从 1 数**。
        if newly:
            _progress_step(cfg, cur)
        if cur >= cfg.max_stages:
            print(f"[abyss] ★{_lap_cleared_reason(cfg)}★ → 回关卡选择页继续")
            # ★#11★ 三处收工出口之一「已打完一圈」：原因就是上面那行既有文案（去掉 ★ 装饰）。
            _progress_done(cfg, _lap_cleared_reason(cfg))
        return

    # ★ADR 0005 / #19★ ``state == "unknown"`` 无需分支：迷路时钟已在函数开头喂过
    #   （进 unknown 打点 / 命中任一已知页清点），这里不再累计任何帧数。


# ---------------------------------------------------------------------------
# 自定义识别
# ---------------------------------------------------------------------------
class AbyssSceneRecognition(CustomRecognition):
    """★场景声明 / 门控（#55 Phase 3）★：普通深渊与深渊EX 只差「导航」，故用场景 id 参数化。

    参数（custom_recognition_param）：
        scene : 场景 id（``abyss`` = 深渊EX / ``abyss_plain`` = 普通深渊）。
        set   : true 时**声明**本次任务的活动场景（入口节点用；总是命中 —— 动作 DoNothing）；
                缺省（false）时是**门控叶**：仅当活动场景 == scene 才命中。
                ★为什么需要门控★：EX 横幅常与普通深渊横幅在**不同页签**——普通深渊任务若不带门控，
                会在「未通关」页签误点 EX 横幅（校准 §3.2 坑 1：两条横幅美术几乎一样）。
    返回：命中时 box=[0,0,0,0]（门控叶，不用于点击）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        scene = (param.get("scene") or "").strip()
        task_id = getattr(argv.task_detail, "task_id", None)
        if param.get("set"):
            # 声明活动场景：``_sync_task`` 新任务先重置缺省 EX、再套用本次声明（顺序不能反）。
            _sync_task(task_id, scene or None)
            active = _cfg().scene
            print(f"[abyss_scene] 声明活动场景 scene={active!r}（task={task_id}）")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"set": True, "scene": active, "task_id": task_id}
            )
        _sync_task(task_id)
        active = _cfg().scene
        hit = (not scene) or (active == scene)
        detail = {"scene": scene, "active": active, "hit": hit}
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0] if hit else None, detail=detail)


class AbyssStateRecognition(CustomRecognition):
    """把当前画面分类成深渊状态；命中请求的 state 时返回 hit。

    参数（custom_recognition_param）：
        state        : 期望画面名（abyss_hub / abyss_main / abyss_solo_team /
                       abyss_settle / abyss_battle / abyss_level_required /
                       main_city / activity / zhongshi / loading / relogin）；留空=任意命中。
        ocr_entry    : 截图用 OCR 节点，默认 OcrTask。
        relogin_text : 追加的换日重进整句候选（interface 选项注入）。
        scene        : 可选场景 id（#55 Phase 3）：非空时【声明】本次任务的活动场景
                       （普通深渊入口节点带它；共享节点留空 = 沿用活动场景）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        want = (param.get("state") or "").strip()
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        relogin_text = param.get("relogin_text")
        phrases = [str(relogin_text)] if relogin_text else []
        scene = (param.get("scene") or "").strip()

        items = _ocr(context, argv.image, ocr_entry)
        _sync_task(getattr(argv.task_detail, "task_id", None), scene or None)
        state, info = classify(items, relogin_phrases=phrases)
        _observe(state, info, items)

        if state == ABYSS_LEVEL_REQUIRED:
            print(
                "[abyss] 检测到『需要130级』限制：玩家等级达到130后，解锁幻想连战与深渊连战 → "
                "本账号无法进入深渊连战，任务停止（StopTask）"
            )

        if want and state != want:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"want": want, "state": state, **info}
            )
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"state": state, **info})


def _lost_after_recover_reason(seconds, last_known, recoveries) -> str:
    """★#21★ 归位预算用尽后的收工原因：**在 ``core.lost_reason`` 同一句上**换掉括号说明。

    ``core.lost_reason`` 给的是 ``连续 {n}s 认不出画面（最后已知页：{页}）``；本票要的是
    ``连续 {n}s 认不出画面（归位 2 次失败）``。ADR 0005 要求三个场景**同一句**，所以前半句
    （量纲 / 秒数）逐字取自 kernel，只替换括号里的补充说明 —— ★不另起一句★。
    """
    head = core.lost_reason(seconds, last_known).split("（", 1)[0]
    return f"{head}（归位 {int(recoveries)} 次失败）"


class AbyssGiveUpRecognition(CustomRecognition):
    """兜底出口：连续认不出画面超过 lost_sec / 长时间无新关卡 / 阶梯记账异常 → 收工，绝不空转。

    ★没有「刷几套」★（运维：不关心有几套）：深渊是 30 层线性阶梯，一直往下刷；
    本节点只在异常时优雅收工。默认 ``max_task_sec=0`` = 不限制总时长。

    ★#117★ 它同时是「终始之战没有可打的关卡」与「页签切换失败」的**唯一收工出口**：
      · 动作层（``AbyssActAction._run_tab_step``）判定成功后只 ``request_giveup(reason)``；
      · 这里把原因取走、写收工标记（``_mark_run_done``）、打一句用户可见的「收工 —— 原因」，
        再由 pipeline 的 ``AbyssGiveUp`` 节点 ``StopTask``。**不新造第二套收工语义。**

    ★#11★ 每一条收工出口都把**同一条**既有原因文案交给 ``reporting.Progress.done()``
    （面板最后一行的 ``[进度] … 收工：<原因>``），原因字符串一个字都不新造。

    ★ADR 0005 / #19★ 迷路闸门 = **连续** ``lost_sec`` 秒认不出画面（``core.LostClock``），
    不是「本轮累计多少帧 unknown」。阈值真源 = ``scene.abyss.LOST_SEC``（override 的
    ``lost_sec`` 优先）；override 里残留的旧**帧数**参数一律忽略并警告一次
    （``core.warn_stale_frame_limit``），绝不静默恢复计数。

    ★#21★ 迷路闸门到点**先归位、后收工**（ADR 0005 第 4 条）：
      · 预算还有（``recoveries < MAX_RECOVERIES``）→ 只置 ``recover_pending``、返回 box=None，
        **不写收工标记、不进进度收工**；同一帧里紧跟在本节点之后的 ``abyss_recover_gate``
        会把它交给 ``abyss_recover`` 执行；
      · 预算用尽 → 照旧收工，原因 ``连续 {n}s 认不出画面（归位 2 次失败）``。
    其余闸门（零进度 / 无新关卡 / 总时长 / 记账异常）**不享受归位**：它们不是「认不出」，
    点回主城救不了「关卡打不过」。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        max_task_sec = float(param.get("max_task_sec") or 0)
        no_progress_sec = float(param.get("no_progress_sec") or DEFAULT_NO_PROGRESS_SEC)
        # ★#118★ 零进度上限（真源 scene.abyss.ZERO_PROGRESS_SEC）
        zero_progress_sec = float(
            param.get("zero_progress_sec") or _ZERO_PROGRESS_SEC_SNAPSHOT
        )
        scene = (param.get("scene") or "").strip()

        items = _ocr(context, argv.image, param.get("ocr_entry") or "OcrTask")
        _sync_task(getattr(argv.task_detail, "task_id", None), scene or None)
        cfg = _cfg(scene or None)
        # ★ADR 0005 / #19★ 迷路闸门：阈值是**秒**，真源在 scene.abyss（按场景数据化）。
        #   兼容：override 里还残留旧**帧数**参数时忽略 + 警告一次（tag = 本文件既有日志前缀，
        #   具体的旧参数名与警告文案只有 kernel 那一份 —— 三个场景不许各抄一句）。
        core.warn_stale_frame_limit(cfg.scene, "[abyss]", param)
        lost_sec = float(param.get("lost_sec") or cfg.lost_sec)
        state, info = classify(items)
        _observe(state, info, items, cfg)

        # ★#117★ ① 动作层已经判定「为什么必须收工」（页签三连空 / 页签切换失败）：
        #   这里只做出口，不重新发明判据。
        pending = _consume_giveup_reason()
        if pending:
            _mark_run_done(cfg)
            # ★#11★ 收工原因进面板（既有文案原样；reason 为同一条字符串，不新造）。
            _progress_done(cfg, pending)
            print(f"[abyss] 收工 —— {pending}（state={state}）")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"giveup": True, "reason": pending, "state": state}
            )

        # ★#117★ ② 兜底：当前帧本身就是终始之战空态，且本轮任务里三个页签都已被确认没有
        #   内容（账本由 abyss_act step=tab 填）→ 同样走既有收工出口。
        empty_anchor = str(param.get("empty_anchor") or getattr(cfg, "empty_anchor", ZHONGSHI_EMPTY_ANCHOR))
        if has_empty_anchor(items, empty_anchor) and tabs_all_empty(cfg.tabs):
            empty_reason = str(getattr(cfg, "empty_reason", ZHONGSHI_EMPTY_REASON))
            _mark_run_done(cfg)
            # ★#11★ 同上：空态收工原因也带进面板（文案来自真源 ZHONGSHI_EMPTY_REASON）。
            _progress_done(cfg, empty_reason)
            print(f"[abyss] 收工 —— {empty_reason}（state={state}）")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0],
                detail={"giveup": True, "reason": empty_reason, "state": state},
            )

        now = time.monotonic()
        with _LOCK:
            start = _SESSION["start_ts"] or now
            last = _SESSION["last_progress_ts"] or now
            # ★ADR 0005 / #19★ 判定与原因文案共用**同一个**快照：连续秒数 + 最后已知页
            #   必须在同一把锁里取，否则两次取值可能说两句话（例如刚好这一帧清点了钟）。
            lost = _SESSION["lost"]
            lost_seconds = lost.seconds_lost(now)
            last_known = lost.last_known
            total = _SESSION["total_marks"]
            session_mx = _SESSION["session_max_done"]

        reason = None
        recover_now = False
        recoveries = 0
        if total > (cfg.max_stages + 2):
            reason = f"阶梯记账数异常（{total}）"
        elif max_task_sec > 0 and (now - start) > max_task_sec:
            reason = f"总时长超过 {max_task_sec:.0f}s"
        elif lost_seconds >= lost_sec:
            # ★ADR 0005 / #19★ 迷路 = **连续** lost_sec 秒认不出画面（不是累计帧数）；
            #   原因文案与幻象/五重同一句（core.lost_reason），三个场景不许各写一份。
            # ★#21★ 但先给「归位重导航」一次机会：预算还有就只置旗标、**不收工**。
            with _LOCK:
                recoveries = int(_SESSION["recoveries"])
                if recoveries < MAX_RECOVERIES:
                    _SESSION["recover_pending"] = True
                    recover_now = True
                else:
                    reason = _lost_after_recover_reason(lost_seconds, last_known, recoveries)
            if recover_now:
                print(
                    f"[abyss] 连续 {int(lost_seconds)}s 认不出画面 → 先归位重导航"
                    f"（第 {recoveries + 1}/{MAX_RECOVERIES} 次预算），本次不收工"
                )
        elif (now - last) > (no_progress_sec if session_mx > 0 else zero_progress_sec):
            # ★#118★ 去掉旧的 `session_mx > 0` 门：EX 第 1 战打不过时它恒为 0，
            #   旧条件让「零进度」任务永不收工（真机 20 秒一轮无限重进 5+ 次）。
            #   零进度改用更短窗口，且原因能区分两种情形。
            if session_mx > 0:
                reason = f"{no_progress_sec:.0f}s 无新关卡完成"
            else:
                reason = f"{zero_progress_sec:.0f}s 一场都没有完成（关卡打不过？）"

        if recover_now:
            # ★#21★ 只置 recover_pending、返回不命中：**不写 run-done 标记、不报收工**。
            #   同一帧里紧跟在后的 AbyssRecover（pipeline 里紧随 AbyssGiveUp 之后）会命中并执行。
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "giveup": False,
                    "recover_pending": True,
                    "state": state,
                    "recoveries": recoveries,
                    "lost_seconds": int(lost_seconds),
                },
            )

        if reason:
            _mark_run_done(cfg)
            # ★#11★ 三处点名收工出口里的两处（零进度超时 / 无新关卡）都走这里：
            #   原因沿用既有 reason 文案（zero_progress / no_progress 两条），一字不改。
            _progress_done(cfg, reason)
            print(f"[abyss] 收工 —— {reason}（state={state} 会话进度={session_mx}）")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"giveup": True, "reason": reason, "state": state}
            )
        return CustomRecognition.AnalyzeResult(
            box=None, detail={"giveup": False, "state": state}
        )


class AbyssRecoverGateRecognition(CustomRecognition):
    """★#21★ 归位闸门：只有「刚判到迷路、还没归位」**且当前帧仍是 ``unknown``** 时才命中。

    为什么要有独立门控叶：``abyss_recover`` 会点屏幕（点主城 / 返回），**绝不能进常规状态机**。
    把「是否允许点」压成一个只在 ``recover_pending`` 时命中的叶子，动作就永远只在迷路帧发生
    —— 这是 #29 的教训形状（归位是兜底，不是每帧的候选），也保证正常帧上本节点恒不命中、
    不存在抢帧。

    与 ``AbyssGiveUp`` 的分工（pipeline 里两者紧邻、**本节点紧随其后**）：
      · GiveUp 判「该归位还是该收工」，置 ``recover_pending``；
      · 本节点只读旗标 + 复判画面，命中即把这一帧交给 ``AbyssRecoverAction`` 执行。

    参数（custom_recognition_param）：
        ocr_entry : 截图用 OCR 节点，默认 OcrTask。
    返回：命中时 box=[0,0,0,0]（门控叶，不用于点击）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        # 共享节点不带 scene：沿用入口声明的活动场景（AbyssPlainEntry / 缺省 EX）。
        _sync_task(getattr(argv.task_detail, "task_id", None))
        with _LOCK:
            pending = bool(_SESSION["recover_pending"])
        if not pending:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"recover_pending": False}
            )
        items = _ocr(context, argv.image, param.get("ocr_entry") or "OcrTask")
        state, info = classify(items)
        detail = {"recover_pending": True, "state": state, **info}
        if state != "unknown":
            # 旗标还在但画面已经认出来了（同一帧的复判不一致 / 过渡帧已过）→ 不归位，
            # 交给下一次 ``_observe`` 把旗标清掉（那里有「认出已知页即作废」的防御）。
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)


# ---------------------------------------------------------------------------
# 自定义动作
# ---------------------------------------------------------------------------
def _pick(items, patterns, roi=None, prefer=None):
    """在 OCR 项里找第一个匹配任一正则的按钮框（与 phantom_impl._pick 同口径）。"""
    regs = [re.compile(p) for p in patterns]
    found = []
    for t, b in items or []:
        if not b or len(b) != 4:
            continue
        for r in regs:
            if r.search(t or ""):
                cx, cy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
                if roi and not (roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]):
                    continue
                found.append((t, cx, cy))
                break
    if not found:
        return None
    if prefer == "top":
        found.sort(key=lambda x: x[2])
    elif prefer == "bottom":
        found.sort(key=lambda x: x[2], reverse=True)
    return found[0]


class AbyssActAction(CustomAction):
    """按 OCR 到的【按钮文字本身】点击，点完校验画面是否推进到期望状态。

    参数（custom_action_param）：
        what    : 按钮文字正则列表（按顺序取第一个命中的按钮）。
        roi     : 可选 (x0,y0,x1,y1) 限定按钮中心范围（720）。
        prefer  : 可选 "top"/"bottom"。
        expect  : 点击后【期望出现】的状态列表；为空表示画面变了就算成功。
        wait_ms : 点击后等待毫秒，默认 1600。
        step    : 特殊步骤名 ``tab``（终始之战切二级页签）。
        tabs    : ``step=tab`` 时的**页签列表**（**数据驱动**；缺省取 scene.abyss.ZHONGSHI_TABS）。
                  引擎照 ``scene.abyss`` 的语义：从当前索引起按【数据顺序】循环，找到页签就点它。
        validate: ``step=tab`` 时的校验判据，只认 ``"content_change"``（内容区文本集合必须变）。
                  ★``step=tab`` 不看 ``expect``★：页面状态在切页签时**本来就该是 zhongshi**，
                  用它做判据就是自证式（#117 真机无限三连的根因）。
        retry_limit : ``step=tab`` 时页签切换失败的重试上限（缺省取真源 TAB_SWITCH_RETRY_LIMIT）。
        empty_anchor: ``step=tab`` 时的空态锚点（缺省取真源 ZHONGSHI_EMPTY_ANCHOR）。
        content_roi : ``step=tab`` 时的内容区 720 空间 ``x0,y0,x1,y1``（缺省取真源）。
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        step = param.get("step")
        wait_ms = int(param.get("wait_ms") or 1600)
        expect = list(param.get("expect") or [])

        img0 = _grab(context)
        items0 = _ocr(context, img0)
        state0, _info0 = classify(items0)

        if step == "tab":
            # ★#117★ 页签切换有自己的（非自证的）判据，走单独分支。
            return self._run_tab_step(context, param, items0, state0, wait_ms)

        target = _pick(
            items0,
            list(param.get("what") or []),
            roi=tuple(param["roi"]) if param.get("roi") else None,
            prefer=param.get("prefer"),
        )

        if target is None:
            print(
                f"[abyss_act] 未找到按钮（state={state0} step={step} what={param.get('what')}）→ 不点击"
            )
            return True

        text, cx, cy = target
        print(f"[abyss_act] state={state0} 点击 '{text}' @720({int(cx)},{int(cy)}) step={step}")
        _click_box(context, cx, cy)
        time.sleep(max(0.2, wait_ms / 1000.0))

        img1 = _grab(context)
        items1 = _ocr(context, img1)
        state1, _i1 = classify(items1)
        _observe(state1, _i1, items1)

        ok = (state1 in expect) if expect else (state1 != state0)
        if not ok:
            print(f"[abyss_act] [!] 校验未通过：点击后 state={state1}，期望 {expect or '画面变化'}")
        else:
            print(f"[abyss_act] 校验通过：state {state0} -> {state1}")
        return True

    # ------------------------------------------------------------------
    # ★#117★ 终始之战切二级页签：判据必须是「页面给了新证据」
    # ------------------------------------------------------------------
    def _run_tab_step(self, context, param, items0, state0, wait_ms):
        """点一个页签 → 读【内容区文本集合】是否真的变了 → 空态记账 / 失败计数 → 有界收工。

        ★绝不沿用「state 还是 zhongshi 就算通过」★（自证式判据 = #117 的根因）：
        真机 2026-10-18 08:0x（设备A）三个页签全空，点哪一个 state 都还是 zhongshi，
        于是每次点击都"校验通过"，与页签循环索引凑成无限三连。

        三次结论映射（见 :func:`tab_switch_verdict`）：
          * 内容区文本集合变了 → 切换生效（记 ``tab_selected``），继续找横幅；
          * 内容区是空态锚点     → 这个页签确实没内容（记 ``tab_empty``）；
            三个页签都记满 ⇒ **请求收工**（原因 = 真源 ``ZHONGSHI_EMPTY_REASON``）；
          * 没变也不是空态       → 可能本来就在这个页签上（信息：``tab_selected`` = 它）⇒
            记一笔连续失败，**整轮无变化**算切换失败；超过重试上限 ⇒ 带原因请求收工。

        第二道闸（同一张票的「账号没这条活动」）：横幅节点排在切页签**之前**，所以「还在切页签」
        等价于「这一轮页签上都没有横幅」。切满 ``len(tabs) * TAB_SCAN_ROUND_LIMIT`` 次（= 2 轮）
        仍没被横幅节点接手 ⇒ 带原因收工（:func:`tab_scan_reason`），绝不无限切页签。
        """
        cfg = _cfg()
        tabs = [str(t) for t in (param.get("tabs") or list(cfg.tabs))]
        raw_limit = param.get("retry_limit")
        retry_limit = (
            int(raw_limit)
            if raw_limit is not None
            else int(getattr(cfg, "tab_retry_limit", TAB_SWITCH_RETRY_LIMIT))
        )
        box = tuple(param.get("content_roi") or getattr(cfg, "content_box", ZHONGSHI_CONTENT_BOX))
        anchor = str(param.get("empty_anchor") or getattr(cfg, "empty_anchor", ZHONGSHI_EMPTY_ANCHOR))
        empty_reason = str(getattr(cfg, "empty_reason", ZHONGSHI_EMPTY_REASON))
        raw_rounds = param.get("scan_rounds")
        scan_rounds = (
            int(raw_rounds) if raw_rounds is not None else int(TAB_SCAN_ROUND_LIMIT)
        )
        scan_limit = max(1, len(tabs)) * max(1, scan_rounds)

        if param.get("validate") not in (None, "", "content_change"):
            print(
                f"[abyss_act] [!] step=tab 只认 validate='content_change'，忽略 {param.get('validate')!r}"
            )
        if param.get("expect"):
            print(
                f"[abyss_act] [!] step=tab 不使用 expect={param.get('expect')!r}"
                "（页面状态在切页签时本来就该是 zhongshi，用它做判据就是自证式）"
            )

        sig0 = content_signature(items0, box)
        empty0 = has_empty_anchor(items0, anchor)

        with _LOCK:
            selected = _SESSION["tab_selected"]
        if selected:
            _tab_remember(selected, sig0, empty0)

        # (0) 三个页签都已被确认为空 ⇒ 立刻带原因收工（不再点第 n 次，也不再找横幅）。
        if empty0 and tabs_all_empty(tabs):
            request_giveup(empty_reason)
            return True

        # (1) 目标页签：照旧按循环索引取（数据驱动；不假定目标在哪个页签）。
        with _LOCK:
            idx = _SESSION["tab_index"] % max(1, len(tabs))
        target = None
        for off in range(len(tabs)):
            name = tabs[(idx + off) % len(tabs)]
            target = _pick(items0, [f"^{re.escape(name)}$"])
            if target:
                with _LOCK:
                    _SESSION["tab_index"] = (idx + off + 1) % len(tabs)
                break
        if target is None:
            print(f"[abyss_act] 未找到页签按钮（state={state0} tabs={tabs}）→ 不点击")
            return True

        text, cx, cy = target
        budget = tab_switch_budget(tabs, retry_limit)
        print(f"[abyss_act] state={state0} 点击页签 '{text}' @720({int(cx)},{int(cy)})")
        _click_box(context, cx, cy)
        time.sleep(max(0.2, wait_ms / 1000.0))

        items1 = _ocr(context, _grab(context))
        state1, info1 = classify(items1)
        _observe(state1, info1, items1, cfg)
        sig1 = content_signature(items1, box)
        empty1 = has_empty_anchor(items1, anchor)

        streak = _tab_fail_streak(ok=empty1 or (sig1 != sig0))
        _tab_remember(text, sig1, empty1)
        verdict = tab_switch_verdict(
            sig0, sig1, empty_after=empty1, streak=streak, budget=budget
        )

        if verdict == TAB_SWITCH_SWITCHED:
            with _LOCK:
                _SESSION["tab_selected"] = text
            print(
                f"[abyss_act] 校验通过：页签 '{text}' 切换生效"
                f"（内容区文本 {len(sig0)} 条 -> {len(sig1)} 条；state {state0} -> {state1}）"
            )
            if _tab_note_switch() >= scan_limit:
                # 切满 2 轮还是没被横幅节点接手 ⇒ 这条活动不在这个账号的三个页签里。
                request_giveup(tab_scan_reason(cfg))
            return True

        if verdict == TAB_SWITCH_EMPTY:
            with _LOCK:
                _SESSION["tab_selected"] = text
            print(f"[abyss_act] 页签 '{text}' 没有内容（空态锚点「{anchor}」）")
            if tabs_all_empty(tabs):
                request_giveup(empty_reason)
                return True
            if _tab_note_switch() >= scan_limit:
                request_giveup(tab_scan_reason(cfg))
            return True

        if verdict == TAB_SWITCH_RETRY:
            print(
                f"[abyss_act] [!] 页签切换未生效（内容区文本集合没变、也不是空态）"
                f"→ 继续扫 / 重试（连续无证据 {streak}/{budget} 次）"
            )
            return True

        request_giveup(
            f"页签切换失败：三个页签各点 {1 + retry_limit} 轮"
            f"（共 {budget} 次）内容区仍无变化（最后点到『{text}』，state 仍 {state1}）"
        )
        return True


class AbyssRecoverAction(CustomAction):
    """★ADR 0005 第 4 条 / 票 #21★ 迷路后归位：点底导「主城」或左槽「返回」，交给既有导航链重进。

    只在 ``abyss_recover_gate`` 命中（= 刚判到迷路 + 还有预算 + 当前帧仍 ``unknown``）时被调用。
    三种结局：
      1. **主城分区深层页**（判据 :func:`is_home_section_deep_page`：底导「主城」+ 最左槽「返回」）
         → 点「主城」框中心（回主城后 pipeline 从 ``AbyssNavActivity`` 起走**既有**导航链：
         活动 → 终始之战 → 搜横幅 → 进关，**不新造导航**）；
      2. 否则左槽仍有「返回」→ 点「返回」框中心（兜底；仍然只在迷路时发生）；
      3. 两个都不在 → **不点击**，只打日志（★绝不盲点★：认不出按钮就只花预算，不猜坐标）。

    无论如何：``recoveries += 1``、``recover_pending = False``、**迷路时钟清零**，并打一行
    ``[abyss] 归位第 k/2 次：{state} → {点了什么 / 没找到}``（回放 08:06 事故时要能看出
    「第几次归位、从哪页开始」）。

    ★为什么点「主城」而不是「返回」★：深层页逐级返回要猜几层（还可能落回活动页/终始之战），
    点底导「主城」是**一步回已知页**；导航的细节交给既有链，本动作只做「归位」这一件事。

    ★真机欠账★：点「主城」在五重决战详情页上会不会先弹确认框，离线判据看不出来 ——
    需要真机验收（票 #21 的验收段）；若会弹，下一轮 ``unknown`` + 预算还剩时会把确认框
    当未知页再归位一次，直到预算用尽收工（有界，不会空转）。
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        items = _ocr(context, _grab(context), ocr_entry)
        state, _info = classify(items)

        # ★预算与旗标先记，再点★：票面要求「都不命中也要 recoveries += 1」（一次迷路只换一次
        #   归位机会，绝不因为没找到按钮就无限重试）。
        # ★迷路时钟清零（#21 裁决）★：点完主城到新页面渲染出来之间是过渡帧（仍是 unknown），
        #   不清零的话 60s 旧账会立刻再吃掉第 2 次预算 —— 两次归位会在 2 秒内烧完。
        #   清零后每次归位各得一个完整的 ``lost_sec`` 窗口，连续两次失败才收工
        #   （总耗时有界 ≈ 60 + 60 + 60 秒）。
        with _LOCK:
            _SESSION["recoveries"] = int(_SESSION["recoveries"]) + 1
            done = int(_SESSION["recoveries"])
            _SESSION["recover_pending"] = False
            _SESSION["lost"].reset()

        if is_home_section_deep_page(items):
            target = _find_text_box(items, "主城", _RECOVER_HOME_ROI)
        else:
            target = _find_text_box(items, "返回", _RECOVER_BACK_ROI)

        if target is None:
            what = "没找到（主城/返回都不在）→ 不点击"
        else:
            text, cx, cy = target
            what = f"点了「{text}」@720({int(cx)},{int(cy)})"
            _click_box(context, cx, cy)
        print(f"[abyss] 归位第 {done}/{MAX_RECOVERIES} 次：{state} → {what}")
        return True


class AbyssBlockedAction(CustomAction):
    """★#27★ 「有正在挑战中的关卡」弹窗：点 **OK**（继续），而不是点「取消」。

    真机证据（2026-10-20 01:25）：工具在一圈打满后又去点第 30 战，游戏弹出

        挑战深渊连战 EX。
        若非通关或放弃正在挑战中的关卡，则无法挑战其他难度的极限战斗关卡
        [取消] [OK]

    这个弹窗**盖住底部导航**，而 ``classify`` 不认识它 ⇒ 进 ``unknown``；归位动作去点底导
    「返回」全点在弹窗上 → 60s×2 后「归位 2 次失败」收工。

    ★点 OK 而不是取消（运维 2026-10-20 裁决）★：这个弹窗是「继续」性质的确认，点 OK 才会
    往下走；点「取消」只是退出。所以先找 **OK**；只有整帧确实认不到 OK 时才兜底点「取消」
    （能关掉总比卡在弹窗上强），并在日志里写明是兜底。

    本动作只做一件事：OCR 找按钮 → 点框中心 → 等一拍再看状态。

    * 回到任一已知页：返回 True，流水线 ``next`` 回 ``AbyssEntry`` 重新导航（正常续跑）；
    * 仍是 ``unknown``：记一次受阻；
    * **每遇到一次弹窗就计一次**（不是每点空才计）—— 到 ``MAX_BLOCKED`` 才 ``request_giveup``
      （原因写明「需人工处理」）。真正收工仍走既有 ``abyss_giveup`` 唯一出口（不新造语义）。

    ★为什么计数不因「点完回已知页」清零★：真机上完全可能「点第 30 战 → 弹窗 → OK →
    又点第 30 战 → 又弹」地打转；一见到已知页就清零，这个环就是**无界**的
    （ADR 0005：任何闸门都不许无界）。清零只发生在「真的进到战斗」（``_observe`` 的
    ``ABYSS_BATTLE`` 分支）—— 那才是「已经续上」的证据。
    """

    def run(self, context, argv):  # noqa: ANN001, ANN201
        param = read_action_param(argv)
        ocr_entry = param.get("ocr_entry") or "OcrTask"

        # ★每「遇到一次」弹窗就记一次★（见类文档：清零只在真正进战斗时发生）。
        blocked = self._bump()

        img0 = _grab(context)
        items0 = _ocr(context, img0, ocr_entry)

        # ★先 OK（继续）★；认不到才兜底「取消」。
        target = _find_text_box(items0, "OK", (0, 0, 720, 1280))
        fallback = False
        if target is None:
            target = _find_text_box(items0, "取消", (0, 0, 720, 1280))
            fallback = True

        if target is None:
            # ★绝不盲点★：认不出按钮就不点（与归位动作同一纪律），只记一次受阻。
            print(f"[abyss] 弹窗受阻：OK/取消 都没找到 → 不点击（第 {blocked}/{MAX_BLOCKED} 次）")
            self._maybe_giveup(blocked)
            return True

        text, cx, cy = target
        tag = "兜底点取消" if fallback else "点 OK 继续"
        print(f"[abyss] 弹窗受阻（正在挑战中的关卡）→ {tag}「{text}」@720({int(cx)},{int(cy)})（第 {blocked}/{MAX_BLOCKED} 次）")
        _click_box(context, cx, cy)
        time.sleep(1.2)

        img1 = _grab(context)
        items1 = _ocr(context, img1, ocr_entry)
        state1, _info1 = classify(items1)
        _observe(state1, _info1, items1)

        print(f"[abyss] 弹窗已处理 → state={state1}（受阻 {blocked}/{MAX_BLOCKED}）")
        # ★无论这一步之后成没成功都过闸★：点完还是弹 = 环；到上限就收工（有界）。
        self._maybe_giveup(blocked)
        return True

    @staticmethod
    def _bump() -> int:
        with _LOCK:
            _SESSION["blocked_count"] = int(_SESSION["blocked_count"]) + 1
            return int(_SESSION["blocked_count"])

    @staticmethod
    def _maybe_giveup(blocked: int) -> None:
        if blocked >= MAX_BLOCKED:
            request_giveup(
                f"账号有正在挑战中的关卡（连续 {blocked} 次处理该弹窗仍无法进入关卡，需人工处理）"
            )
