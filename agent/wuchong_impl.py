# -*- coding: utf-8 -*-
"""「五重决战」状态机 + ★手操战斗引擎★ + 跨模式「自动」规则（#56 Phase 4）。

为什么要单独一个模块
--------------------
同 ``phantom_impl`` / ``abyss_impl`` / ``side_impl``：本模块只依赖 ``maa.custom_recognition``
/ ``maa.custom_action`` 与纯逻辑模块（``maa_util`` / ``progress``），**不导入
``maa.agent.agent_server``**。这样 MFAAvalonia 的 AgentServer 进程能 import 并在
``my_reco.py`` / ``my_action.py`` 里注册，离线/真机测试脚本也能直接在进程内 Resource 上注册。

★与幻想/深渊的关系（诚实交代）★
  · 导航遵循 kernel 的「领主战 → 降临讨伐 → 五王连战行 → 五重决战·超级 详情」——
    与深渊的「终始之战」**不是同一条**导航，但**同一套纪律**：模板/OCR 双重门控、
    「绝不点在错的目标上」、异常挂在每个节点上。
  · 手操战斗是**唯一真正新**的部分（运维：「唯一分歧点：…进入挑战后若手动开启，需要全程
    点板子+放技能」）：:class:`WuchongBattleAction` 按 :data:`scene.wuchong.BATTLE_PARAMS`
    的节奏参数连点弹板 + 轮换放技能，带战斗页安全阀，且**可切回自动**。

★配置权威在 ``scene/wuchong.py``★（ADR-0001）：导航关键词 / 模板 / 开关几何 / 节奏参数 /
流程链 / **跨模式自动规则**都从那里取。安装态（只发 ``agent/``、仓库根没有 ``scene/``）回退到
本文件的**冻结快照**；快照由 ``tools/contract_hooks/hooks_wuchong.py`` 钉死「必须与
``scene.wuchong`` 逐字一致」，漂移即变红。

★跨模式硬规则（运维）★：「除了『五重决战』可以选择自动或手动以外，其他所有战斗都需要勾选
『自动』」。落地三处：
  1. :func:`scene.wuchong.effective_auto_state` 把开关意图夹到合法值（非五重一律自动开）；
     :class:`WuchongSwitchAction` / :class:`auto_switch_impl.AutoSwitchSetAction` 强制执行；
  2. GUI 上只有「五重决战」任务挂「是否手操」（守卫 ``wuchong-cross-mode-auto`` 把守）；
  3. ★二批★：检查点从「战斗内(暂停→自动滑块)」**移到战斗外的编队页/房间页**，且「自动」
     按钮一律**定位**（不写死坐标）—— 由 ``SpecialTeamAutoSet`` / ``AbyssTeamAutoSet``
     覆盖各模式编队页（守卫 ``auto-outside-*`` 把守）。

安全红线（继承本项目踩过的坑）
-----------------------------
* 绝不 KeyEvent 4；返回一律用屏幕按钮。
* 绝不用「识别框 + 死偏移」猜按钮：``wuchong_act`` 只点 OCR/模板命中的框中心。
* 换日重进文案未实测到：只做【整句】匹配，绝不宽匹配。
* 手操连点走框架原生 Click（一次 run_action 连点 ``burst`` 下），不逐次 ``post_click``。
"""

from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

import auto_switch_impl as auto_switch
import progress as ledger
import reporting
from maa_util import ocr_all, read_action_param, read_param

# ★#119：画面分类判据只有 battle_loop_core.classify 一份★（本文件只提供场景数据；
#   ``classify`` 是薄封装）。★别删下面这些 re-export★：
#   · hooks_63 钉 ``MAIN_CITY_UNIQUE_ANCHORS is core.MAIN_CITY_UNIQUE_ANCHORS``；
#   · hooks_112 钉 ``has_challenge_page_text is core.has_challenge_page_text``；
#   · hooks_74 的 HUD 兜底探针直接读 ``wuchong_impl.is_battle_hud``（同 HUD 判据只此一份）。
#   各自复制一份判据 = 第二套真源（#63/#107 的纪律）。
import battle_loop_core as core
from battle_loop_core import (  # noqa: F401 —— 共享判据的 re-export（守卫按对象同一性检查）
    MAIN_CITY_MIN_UNIQUE,
    MAIN_CITY_UNIQUE_ANCHORS,
    has_challenge_page_text,
    is_battle_hud,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# ★冻结快照★（安装态没有 ``scene/`` 时回退）；hooks_wuchong 钉死它与 scene.wuchong 一致。
# ---------------------------------------------------------------------------
_LORD_TAB_SNAPSHOT = "领主战"
_JOVEN_TAB_SNAPSHOT = "降临讨伐"
_JOVEN_TAB_Y_MAX_SNAPSHOT = 450
_ROW_NAME_SNAPSHOT = "五王连战"
_ROW_PATTERNS_SNAPSHOT = (r"五王连战",)
_ROW_TEMPLATE_SNAPSHOT = "wuchong/row_wuwang.png"
_DETAIL_TITLE_SNAPSHOT = "五重决战超级"
_DETAIL_PATTERNS_SNAPSHOT = (r"五重决战\s*超级",)
_DETAIL_TEMPLATE_SNAPSHOT = "wuchong/detail_wuchong.png"
_TEMPLATE_THRESHOLD_SNAPSHOT = 0.80
_SOLO_TEXT_SNAPSHOT = "单人游戏"
_MULTI_TEXT_SNAPSHOT = "多人游戏"
_MANUAL_ALLOWED_SNAPSHOT = ("wuchong",)
_AUTO_REQUIRED_SNAPSHOT = (
    "phantom", "abyss", "abyss_plain", "farm", "raid", "special", "maze",
)
_AUTO_ON_RATIO_SNAPSHOT = 0.15
#: coop-fix2 快照：共斗房有界重试 + 有界收工 + 弹窗拒点（真源 scene.wuchong ②b）。
_RECRUIT_OPEN_MAX_HIT_SNAPSHOT = 3
_ROOM_WAIT_SEC_SNAPSHOT = 300
#: ★ADR 0005★ 「迷路」闸门阈值的安装态快照（真源 scene.wuchong.LOST_SEC；单位秒）。
#: 旧的「帧数累计」上限已删除 —— 本值只换「连续多久认不出」，不换量纲。
_LOST_SEC_SNAPSHOT = 60
_ROOM_SEQUENCE_STATES_SNAPSHOT = ("wuchong_room", "wuchong_recruit_dialog")
_ROOM_LEAVE_STATES_SNAPSHOT = (
    "wuchong_team", "wuchong_battle", "wuchong_settle", "wuchong_mode",
    "wuchong_detail", "wuchong_lord_list", "main_city", "activity",
    "relogin", "wuchong_level_required",
)
_MODAL_BLOCK_STATES_SNAPSHOT = ("wuchong_recruit_dialog",)
#: coop-fix2 快照：手操引擎「关」时结点不被选中（真源 scene.wuchong ②c）。
_BATTLE_MANUAL_FIELD_SNAPSHOT = "manual"
_BATTLE_DISABLED_EXPECTED_SNAPSHOT = ("__NONE__",)
#: #56「打几次」快照（真源 scene.wuchong ②d）。
_FIGHT_LEDGER_PREFIX_SNAPSHOT = "wuchong/fight"
_TARGET_FIGHTS_FIELD_SNAPSHOT = "target_fights"
_TARGET_FIGHTS_DEFAULT_SNAPSHOT = 0
#: #72「GAMEOVER 续关（不是放弃）」快照（真源 scene.wuchong ②f）。
_CONTINUE_LEDGER_PREFIX_SNAPSHOT = "wuchong/continue"
_TARGET_CONTINUES_FIELD_SNAPSHOT = "target_continues"
_TARGET_CONTINUES_DEFAULT_SNAPSHOT = 0
_CONTINUE_TITLE_SNAPSHOT = "GAMEOVER"
_CONTINUE_PROMPT_SNAPSHOT = "是否续关"
_CONTINUE_BTN_TEXT_SNAPSHOT = "^续关$"
_CONTINUE_BTN_ROI_SNAPSHOT = (400, 1000, 320, 110)
#: ★#72 有界卡住等待★：同一 GAMEOVER 屏存活超过这么久仍未推进 → 判定续关点击无效 / 星导石不足
#: （真源 scene.wuchong ②f 的 CONTINUE_STUCK_SEC；先例 ROOM_WAIT_SEC）。
_CONTINUE_STUCK_SEC_SNAPSHOT = 60.0
#: ★#87★ 「当前不满足出战条件」的整句判据（真机帧 OCR；与 ``scene.wuchong.NO_ENTRY_TEXT`` 同源）。
_NO_ENTRY_TEXT_SNAPSHOT = "当前不满足出战条件"
#: 本票「开始类闩锁 = 重试窗口」快照（真源 scene.wuchong ②e）。
_LATCH_RETRY_S_SNAPSHOT = 8.0
#: ★#116★ 共斗房「挑战」的时间闩窗口的安装态快照（真源 scene.wuchong ②e' 的
#: ``COOP_CHALLENGE_LATCH_S``）。★必须 > 房间页一轮的重复周期（真机实测 5.2s）★，
#: 否则「窗口内不重复点」永远不触发 = 闩锁形同虚设（票面建议的 2.5–3s 就属于这种，故不采纳）。
_COOP_CHALLENGE_LATCH_S_SNAPSHOT = 8.0
#: ★#113★ 「别打服务器」的重试冷却秒数的安装态快照。
#: 真源 = scene.wuchong.SERVER_RETRY_COOLDOWN_S（=10.0）。
_SERVER_RETRY_COOLDOWN_S_SNAPSHOT = 10.0
#: ★#114★ 三种断连文案 + 有界重启客户端的安装态快照（真源 = scene.wuchong ②h）。
#: 判据只允许一份：``net_disconnect_kinds()`` 用这张表切分，pipeline 三个断连节点都经过
#: ``wuchong_net`` custom recognition，绝不各写一份 OCR 列表。
_NET_DISCONNECT_KINDS_SNAPSHOT = ("F2032", "A4050", "UNREACHABLE")
_NET_DISCONNECT_TEXTS_SNAPSHOT = {
    # 只取「离开这块弹窗就不可能出现」的锚点（同 scene.wuchong ②h）。
    "F2032": ("未能连网", r"\(No\.F2032\)"),
    "A4050": ("发生意想不到的错误", r"\(No\.A4050\)"),
    "UNREACHABLE": (
        "暂时无法连接",
        "暂时连接不上服务器",
        "客户端接入提示",
        "连接暂时不可用",
    ),
}
_NET_DISCONNECT_LABELS_SNAPSHOT = {
    "F2032": "F2032 掉线",
    "A4050": "A4050 会话错误",
    "UNREACHABLE": "暂时无法连接",
}
_NET_ERROR_OK_KINDS_SNAPSHOT = ("F2032", "A4050")
_NET_RECONNECT_KINDS_SNAPSHOT = ("UNREACHABLE",)
_NET_RESTART_LIMIT_SNAPSHOT = 3
_RELAUNCH_WAIT_SEC_SNAPSHOT = 45.0
_NET_RESTART_EXHAUSTED_REASON_SNAPSHOT = (
    "客户端重启 {n} 次仍连不上服务器（F2032/A4050/暂时无法连接）—— 带原因收工"
)
_RESUME_QUEST_TEXTS_SNAPSHOT = ("正在进行中的关卡", "^是否继续关卡$")
_BATTLE_CENTER_SNAPSHOT = (360, 600)
_BATTLE_SWIPE_DIST_SNAPSHOT = 160
_BATTLE_FLIPPER_SNAPSHOT = (360, 1067)
_BATTLE_SWIPE_MS_SNAPSHOT = 300
# ★#71★：手操不再有「点 N 秒就交出」——引擎持续点板/放技能直到【结算】或【关卡失败】才
#   交还；「手操连点时长」(duration_s) 这个截断旋钮已从真源（scene.wuchong.BATTLE_PARAMS）
#   与快照一并删除，快照必须与真源逐字一致（hooks_wuchong 钉死）。
_BATTLE_PARAMS_SNAPSHOT = (
    ("flipper_gap_ms", "弹板间隔", 220),
    ("skill_gap_ms", "技能间隔", 800),
    ("skill_every", "每几次弹板放技能", 6),
    ("burst", "连点批量", 10),
)


class _Snapshot:
    """安装态回退配置（字段与 ``scene.wuchong`` 同名）。"""

    LORD_TAB = _LORD_TAB_SNAPSHOT
    JOVEN_TAB = _JOVEN_TAB_SNAPSHOT
    JOVEN_TAB_Y_MAX = _JOVEN_TAB_Y_MAX_SNAPSHOT
    ROW_NAME = _ROW_NAME_SNAPSHOT
    ROW_PATTERNS = _ROW_PATTERNS_SNAPSHOT
    ROW_TEMPLATE = _ROW_TEMPLATE_SNAPSHOT
    DETAIL_TITLE = _DETAIL_TITLE_SNAPSHOT
    DETAIL_PATTERNS = _DETAIL_PATTERNS_SNAPSHOT
    DETAIL_TEMPLATE = _DETAIL_TEMPLATE_SNAPSHOT
    TEMPLATE_THRESHOLD = _TEMPLATE_THRESHOLD_SNAPSHOT
    SOLO_TEXT = _SOLO_TEXT_SNAPSHOT
    MULTI_TEXT = _MULTI_TEXT_SNAPSHOT
    MANUAL_ALLOWED_SCENES = _MANUAL_ALLOWED_SNAPSHOT
    AUTO_REQUIRED_SCENES = _AUTO_REQUIRED_SNAPSHOT
    AUTO_ON_RATIO = _AUTO_ON_RATIO_SNAPSHOT
    RECRUIT_OPEN_MAX_HIT = _RECRUIT_OPEN_MAX_HIT_SNAPSHOT
    ROOM_WAIT_SEC = _ROOM_WAIT_SEC_SNAPSHOT
    LOST_SEC = _LOST_SEC_SNAPSHOT
    ROOM_SEQUENCE_STATES = _ROOM_SEQUENCE_STATES_SNAPSHOT
    ROOM_LEAVE_STATES = _ROOM_LEAVE_STATES_SNAPSHOT
    MODAL_BLOCK_STATES = _MODAL_BLOCK_STATES_SNAPSHOT
    BATTLE_MANUAL_FIELD = _BATTLE_MANUAL_FIELD_SNAPSHOT
    BATTLE_DISABLED_EXPECTED = _BATTLE_DISABLED_EXPECTED_SNAPSHOT
    FIGHT_LEDGER_PREFIX = _FIGHT_LEDGER_PREFIX_SNAPSHOT
    TARGET_FIGHTS_FIELD = _TARGET_FIGHTS_FIELD_SNAPSHOT
    TARGET_FIGHTS_DEFAULT = _TARGET_FIGHTS_DEFAULT_SNAPSHOT
    CONTINUE_LEDGER_PREFIX = _CONTINUE_LEDGER_PREFIX_SNAPSHOT
    TARGET_CONTINUES_FIELD = _TARGET_CONTINUES_FIELD_SNAPSHOT
    TARGET_CONTINUES_DEFAULT = _TARGET_CONTINUES_DEFAULT_SNAPSHOT
    CONTINUE_TITLE_TEXT = _CONTINUE_TITLE_SNAPSHOT
    CONTINUE_PROMPT_TEXT = _CONTINUE_PROMPT_SNAPSHOT
    CONTINUE_BTN_TEXT = _CONTINUE_BTN_TEXT_SNAPSHOT
    CONTINUE_BTN_ROI = _CONTINUE_BTN_ROI_SNAPSHOT
    CONTINUE_STUCK_SEC = _CONTINUE_STUCK_SEC_SNAPSHOT
    LATCH_RETRY_S = _LATCH_RETRY_S_SNAPSHOT
    #: ★#116★ 共斗房「挑战」的时间闩窗口（安装态快照，来源见模块顶部）。
    COOP_CHALLENGE_LATCH_S = _COOP_CHALLENGE_LATCH_S_SNAPSHOT
    #: ★#113★ 安装态快照（来源见模块顶部的 _SERVER_RETRY_COOLDOWN_S_SNAPSHOT）。
    SERVER_RETRY_COOLDOWN_S = _SERVER_RETRY_COOLDOWN_S_SNAPSHOT
    #: ★#114★ 三种断连文案 + 有界重启（真源 scene.wuchong ②h）。
    NET_DISCONNECT_KINDS = _NET_DISCONNECT_KINDS_SNAPSHOT
    NET_DISCONNECT_TEXTS = _NET_DISCONNECT_TEXTS_SNAPSHOT
    NET_DISCONNECT_LABELS = _NET_DISCONNECT_LABELS_SNAPSHOT
    NET_ERROR_OK_KINDS = _NET_ERROR_OK_KINDS_SNAPSHOT
    NET_RECONNECT_KINDS = _NET_RECONNECT_KINDS_SNAPSHOT
    NET_RESTART_LIMIT = _NET_RESTART_LIMIT_SNAPSHOT
    RELAUNCH_WAIT_SEC = _RELAUNCH_WAIT_SEC_SNAPSHOT
    NET_RESTART_EXHAUSTED_REASON = _NET_RESTART_EXHAUSTED_REASON_SNAPSHOT
    RESUME_QUEST_TEXTS = _RESUME_QUEST_TEXTS_SNAPSHOT

    WUCHONG_BATTLE = type(
        "BG",
        (),
        {
            "center": _BATTLE_CENTER_SNAPSHOT,
            "swipe_dist": _BATTLE_SWIPE_DIST_SNAPSHOT,
            "flipper": _BATTLE_FLIPPER_SNAPSHOT,
            "swipe_ms": _BATTLE_SWIPE_MS_SNAPSHOT,
        },
    )()


def _load_config():
    """从 ``scene.wuchong`` 取真源；仓库根没有 ``scene/``（安装态）时回退冻结快照。"""
    try:
        if not (_REPO_ROOT / "scene" / "wuchong.py").is_file():
            raise ModuleNotFoundError(f"真源不在场：{_REPO_ROOT / 'scene' / 'wuchong.py'}")
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scene import wuchong as w  # noqa: PLC0415

        return w, "scene"
    except ModuleNotFoundError:
        return _Snapshot(), "snapshot"


CFG, CFG_SOURCE = _load_config()

# ---------------------------------------------------------------------------
# 常量（值来自配置）
# ---------------------------------------------------------------------------
LORD_TAB = CFG.LORD_TAB
JOVEN_TAB = CFG.JOVEN_TAB
JOVEN_TAB_Y_MAX = CFG.JOVEN_TAB_Y_MAX
ROW_NAME = CFG.ROW_NAME
ROW_PATTERNS = tuple(CFG.ROW_PATTERNS)
ROW_TEMPLATE = CFG.ROW_TEMPLATE
DETAIL_TITLE = CFG.DETAIL_TITLE
DETAIL_PATTERNS = tuple(CFG.DETAIL_PATTERNS)
DETAIL_TEMPLATE = CFG.DETAIL_TEMPLATE
TEMPLATE_THRESHOLD = CFG.TEMPLATE_THRESHOLD
SOLO_TEXT = CFG.SOLO_TEXT
MULTI_TEXT = CFG.MULTI_TEXT
MANUAL_ALLOWED_SCENES = tuple(CFG.MANUAL_ALLOWED_SCENES)
AUTO_REQUIRED_SCENES = tuple(CFG.AUTO_REQUIRED_SCENES)
AUTO_ON_RATIO = CFG.AUTO_ON_RATIO
# ★coop-fix2★：共斗房有界重试 / 有界收工 / 弹窗拒点（真源 scene.wuchong ②b）。
RECRUIT_OPEN_MAX_HIT = int(getattr(CFG, "RECRUIT_OPEN_MAX_HIT", _RECRUIT_OPEN_MAX_HIT_SNAPSHOT))
ROOM_WAIT_SEC = float(getattr(CFG, "ROOM_WAIT_SEC", _ROOM_WAIT_SEC_SNAPSHOT))
# ★ADR 0005★ 「迷路」闸门阈值（秒）：真源 ``scene.wuchong.LOST_SEC``（安装态旧配置缺项时回退 60s）。
LOST_SEC = int(getattr(CFG, "LOST_SEC", _LOST_SEC_SNAPSHOT))
ROOM_SEQUENCE_STATES = tuple(getattr(CFG, "ROOM_SEQUENCE_STATES", _ROOM_SEQUENCE_STATES_SNAPSHOT))
ROOM_LEAVE_STATES = tuple(getattr(CFG, "ROOM_LEAVE_STATES", _ROOM_LEAVE_STATES_SNAPSHOT))
MODAL_BLOCK_STATES = tuple(getattr(CFG, "MODAL_BLOCK_STATES", _MODAL_BLOCK_STATES_SNAPSHOT))
# ★coop-fix2★：手操引擎「关」时结点不被选中（真源 scene.wuchong ②c）。
BATTLE_MANUAL_FIELD = str(getattr(CFG, "BATTLE_MANUAL_FIELD", _BATTLE_MANUAL_FIELD_SNAPSHOT))
BATTLE_DISABLED_EXPECTED = tuple(
    getattr(CFG, "BATTLE_DISABLED_EXPECTED", _BATTLE_DISABLED_EXPECTED_SNAPSHOT)
)
# ★本票「打几次」（真源 scene.wuchong ②d）★
FIGHT_LEDGER_PREFIX = str(getattr(CFG, "FIGHT_LEDGER_PREFIX", _FIGHT_LEDGER_PREFIX_SNAPSHOT))
TARGET_FIGHTS_FIELD = str(getattr(CFG, "TARGET_FIGHTS_FIELD", _TARGET_FIGHTS_FIELD_SNAPSHOT))
TARGET_FIGHTS_DEFAULT = int(getattr(CFG, "TARGET_FIGHTS_DEFAULT", _TARGET_FIGHTS_DEFAULT_SNAPSHOT))
# ★#72「GAMEOVER 续关（不是放弃）」（真源 scene.wuchong ②f）★
CONTINUE_LEDGER_PREFIX = str(getattr(CFG, "CONTINUE_LEDGER_PREFIX", _CONTINUE_LEDGER_PREFIX_SNAPSHOT))
TARGET_CONTINUES_FIELD = str(getattr(CFG, "TARGET_CONTINUES_FIELD", _TARGET_CONTINUES_FIELD_SNAPSHOT))
TARGET_CONTINUES_DEFAULT = int(
    getattr(CFG, "TARGET_CONTINUES_DEFAULT", _TARGET_CONTINUES_DEFAULT_SNAPSHOT)
)
CONTINUE_TITLE_TEXT = str(getattr(CFG, "CONTINUE_TITLE_TEXT", _CONTINUE_TITLE_SNAPSHOT))
CONTINUE_PROMPT_TEXT = str(getattr(CFG, "CONTINUE_PROMPT_TEXT", _CONTINUE_PROMPT_SNAPSHOT))
CONTINUE_BTN_TEXT = str(getattr(CFG, "CONTINUE_BTN_TEXT", _CONTINUE_BTN_TEXT_SNAPSHOT))
CONTINUE_BTN_ROI = tuple(getattr(CFG, "CONTINUE_BTN_ROI", _CONTINUE_BTN_ROI_SNAPSHOT))
# ★#72 有界卡住等待★（真源 scene.wuchong ②f；先例 ROOM_WAIT_SEC）。
CONTINUE_STUCK_SEC = float(getattr(CFG, "CONTINUE_STUCK_SEC", _CONTINUE_STUCK_SEC_SNAPSHOT))
# ★本票「开始类闩锁 = 重试窗口」（真源 scene.wuchong ②e）★
LATCH_RETRY_S = float(getattr(CFG, "LATCH_RETRY_S", _LATCH_RETRY_S_SNAPSHOT))
#: ★#116★ 共斗房「挑战」的时间闩窗口（真源 scene.wuchong ②e' 的 ``COOP_CHALLENGE_LATCH_S``）。
COOP_CHALLENGE_LATCH_S = float(
    getattr(CFG, "COOP_CHALLENGE_LATCH_S", _COOP_CHALLENGE_LATCH_S_SNAPSHOT)
)
#: ★#113★ 断连重试冷却（秒）。★#114★ 重启客户端也要等满这个窗口（不许借重启绕过冷却）。
SERVER_RETRY_COOLDOWN_S = float(
    getattr(CFG, "SERVER_RETRY_COOLDOWN_S", _SERVER_RETRY_COOLDOWN_S_SNAPSHOT)
)
#: ★#114★ 三种断连文案 + 有界重启（真源 scene.wuchong ②h）。
NET_DISCONNECT_KINDS = tuple(
    getattr(CFG, "NET_DISCONNECT_KINDS", _NET_DISCONNECT_KINDS_SNAPSHOT)
)
NET_DISCONNECT_TEXTS = {
    str(k): tuple(v)
    for k, v in dict(
        getattr(CFG, "NET_DISCONNECT_TEXTS", _NET_DISCONNECT_TEXTS_SNAPSHOT)
    ).items()
}
NET_DISCONNECT_LABELS = {
    str(k): str(v)
    for k, v in dict(
        getattr(CFG, "NET_DISCONNECT_LABELS", _NET_DISCONNECT_LABELS_SNAPSHOT)
    ).items()
}
NET_DISCONNECT_LABEL = str(
    getattr(CFG, "NET_DISCONNECT_LABEL", "F2032/A4050/暂时无法连接")
)
NET_ERROR_OK_KINDS = tuple(
    getattr(CFG, "NET_ERROR_OK_KINDS", _NET_ERROR_OK_KINDS_SNAPSHOT)
)
NET_RECONNECT_KINDS = tuple(
    getattr(CFG, "NET_RECONNECT_KINDS", _NET_RECONNECT_KINDS_SNAPSHOT)
)
NET_RESTART_LIMIT = int(getattr(CFG, "NET_RESTART_LIMIT", _NET_RESTART_LIMIT_SNAPSHOT))
RELAUNCH_WAIT_SEC = float(
    getattr(CFG, "RELAUNCH_WAIT_SEC", _RELAUNCH_WAIT_SEC_SNAPSHOT)
)
NET_RESTART_EXHAUSTED_REASON = str(
    getattr(CFG, "NET_RESTART_EXHAUSTED_REASON", _NET_RESTART_EXHAUSTED_REASON_SNAPSHOT)
)
RESUME_QUEST_TEXTS = tuple(
    getattr(CFG, "RESUME_QUEST_TEXTS", _RESUME_QUEST_TEXTS_SNAPSHOT)
)
#: ``wuchong_net`` 的两种模式（pipeline 的 custom_recognition_param.mode）。
NET_RETRY_MODE = "retry"
NET_RESTART_MODE = "restart"
#: 测试可替换的单调时钟（离线守卫用假时钟驱动冷却/重启，不触设备）。
_NET_CLOCK = time.monotonic
#: ★#79★ 共斗房等待心跳间隔（秒）—— 画面不动时也要能看出任务活着。
ROOM_BEAT_SEC = 15.0
_BG = CFG.WUCHONG_BATTLE
BATTLE_CENTER = tuple(_BG.center)
BATTLE_SWIPE_DIST = int(_BG.swipe_dist)
BATTLE_FLIPPER = tuple(_BG.flipper)
BATTLE_SWIPE_MS = int(_BG.swipe_ms)
# ★#56 真机修复★ 手操战斗的日志 tag（真源 scene/wuchong.BATTLE_TAG）。此前 impl 只在
#   print 里裸用 `BATTLE_TAG` 却**从未定义/导入** → 手操动作一进 `run` 就 `NameError`，
#   `WuchongBattleAction` 直接崩，手操引擎**一次都跑不起来**。这里按其它常量同口径取真源。
BATTLE_TAG = getattr(CFG, "BATTLE_TAG", "wuchong_battle")
# ★#71★：手操引擎的采样节流（毫秒，时间驱动）与心跳间隔（毫秒）。二者都是有默认值的读取
#   —— 另一条 lane 可能尚未把 scene.wuchong 落地，缺项时用这些默认值也不会炸。
#   ``check_min_gap_ms`` 取代旧的 ``check_every``（按点击计数）；循环已无次数/时长上限。
CHECK_MIN_GAP_MS = int(getattr(CFG, "CHECK_MIN_GAP_MS", 2000))
BATTLE_HEARTBEAT_MS = int(getattr(CFG, "BATTLE_HEARTBEAT_MS", 60000))

#: 手操引擎的三值**页面判据**（:func:`page_verdict` 的全部取值）。
#: ★运维裁决（2026-10-16，逐字）★：「那我觉得不要做HUD的OCR了，这个实在是没有意义。你就一直点，
#:   点到要么是续关，要么是推出去了，要么就结算了就完事了」。含义：**默认一直点**（弹板 + 按节奏
#:   放技能），只在三个**正面终止点**停手：
#:     · :data:`PAGE_OVER` —— 续关屏（``GAMEOVER`` + ``是否续关?``）/ 结算页（``wuchong_settle``）；
#:     · :data:`PAGE_LEFT` —— 被推出战斗（画面变成任一已知非战斗页）；
#:     · 其余（真战斗帧 / 认不出 / 转场加载）→ :data:`PAGE_CONTINUE` → **继续点**。
#: ★为什么不再用战斗 HUD（``is_battle_hud``）做判据★：真机证据（设备A，2026-10-16 诊断跑，
#:   1s 粒度逐帧留档）——**同一场真战斗内部** HUD 会间歇性认不出（技能演出 / 遮罩帧）：
#:   ``wuchong_battle``(hud=True) 与 ``unknown``(hud=False) 每 2~3 秒来回
#:   （96-106 / 107-108 / 109-111 / 113-114 …）；战斗本身是真的。实时短采样的手操引擎因此
#:   每 2~4 秒 ``stopped=yield`` 让位一次（点板断续）；且让计数器把同一场战斗计成多场
#:   （见 :func:`_observe` 的 episode 闩锁）。HUD 判据保留给别处（``SpecialBattleWait`` 等）。
PAGE_CONTINUE = "continue"   # 继续点（真战斗帧 / 认不出 / 转场加载 全归此）
PAGE_OVER = "over"           # 正面终止点：续关屏 / 结算页
PAGE_LEFT = "left"           # 正面终止点：被推出战斗（任一已知非战斗页）

# ★#74 防御性「可见失败」★：手操引擎连续这么多次「0 点击且 stopped=manual_off」就判定
#   「手操根本没生效」（自动未真正关掉 / 会话手操态与动作决定自相矛盾），交给既有收工出口
#   带原因停任务，绝不空转。真机证据（run A，2026-10-16）：自动开关本来就是关的 → 两个
#   wuchong_switch 节点都不触发 → `_manual_on()` 恒 False → 每次引擎 `stopped=manual_off`、
#   0 点击；pipeline 枢纽反复重进 WuchongBattle **455 次**，随后被旧帧数闸门（累计 121 帧）误杀。
#   这是**兜底**：正常路径由 WuchongBattleAction 回填手操态（见该动作的承重注释）。
ZERO_TAP_YIELD_LIMIT = 3

#: 手操节奏参数默认值（field -> value）。配置在場时从 BATTLE_PARAMS 派生。
if hasattr(CFG, "BATTLE_PARAMS"):
    BATTLE_DEFAULTS: dict[str, int] = {p.field: p.default for p in CFG.BATTLE_PARAMS}
else:  # 快照
    BATTLE_DEFAULTS = {f: v for f, _o, v in _BATTLE_PARAMS_SNAPSHOT}

# ---------------------------------------------------------------------------
# 状态名（与 pipeline 的 wuchong_state 参数一一对应）
# ---------------------------------------------------------------------------
WUCHONG_LORD_LIST = "wuchong_lord_list"
WUCHONG_DETAIL = "wuchong_detail"
WUCHONG_MODE = "wuchong_mode"
WUCHONG_ROOM = "wuchong_room"
WUCHONG_RECRUIT_DIALOG = "wuchong_recruit_dialog"
WUCHONG_TEAM = "wuchong_team"
WUCHONG_SETTLE = "wuchong_settle"
WUCHONG_BATTLE = "wuchong_battle"
WUCHONG_LEVEL_REQUIRED = "wuchong_level_required"
#: ★#87★ 点【挑战】被游戏拒绝：「当前不满足出战条件」弹窗（入场门票 / 关卡开放 / 队伍限制）。
WUCHONG_NO_ENTRY = str(getattr(CFG, "WUCHONG_NO_ENTRY", "wuchong_no_entry"))
NO_ENTRY_TEXT = str(getattr(CFG, "NO_ENTRY_TEXT", _NO_ENTRY_TEXT_SNAPSHOT))

# ---------------------------------------------------------------------------
# ★#119★ 画面分类：判据只有 battle_loop_core.classify 一份（本文件只给场景数据）
#
# 抽取前 ``wuchong_impl.classify`` 是**第三份副本**（12 个分支，逐行重复）。它是唯一有真机
# 证据的主流程（10 连打），所以这次只搬判据、**一个字都不改行为**：
#   · 分支顺序原样保留（见 _CLASSIFY_ORDER，顺序也是语义）；
#   · 五重独有的分支（no_entry / quest_clear / lord_list / mode / detail）在共享版里是
#     **参数化分支**（数据字段），不是 if scene == "wuchong"；
#   · 五重独有的状态名拼法（wuchong_team / wuchong_room / wuchong_no_entry）用
#     ``state_names`` 显式覆盖 —— 别处一律 f"{state_prefix}_{后缀}"。
# 行为核对见 tools/test_classify_equiv.py（入库真机帧三份实现一致性回归）。
# ---------------------------------------------------------------------------
#: 顺序 = 抽取前 wuchong_impl.classify 的分支顺序（逐条对账见票 #119 的评论）：
#: 2.9 no_entry 必须在 battle 之前（弹窗页上也可能读到 HUD 残留）；3.5 quest_clear 紧接 battle；
#: 4 lord_list 必须在 main_city 之前（#56：列表页会被宽松主城判据误吞）；
#: 7 party 必须在 detail 之前（编队页卡片上有「五重决战」徽标，detail 最宽松）；
#: 12 settle 在 detail 之后（抽取前的顺序就是如此）。
_CLASSIFY_ORDER = (
    "loading", "level_gate", "relogin", "no_entry", "battle", "quest_clear",
    "lord_list", "main_city", "activity", "party", "mode", "recruit_dialog",
    "coop_room", "detail", "settle",
)

#: 五重的画面分类配置（唯一一份 classify 的**数据面**；只喂 classify）。
#: ★battle_direct_hud★：#74 真机 HUD 是一个合并框（'时间 29:30 分数 38629797530'）⇒
#:   位置无关的 is_battle_hud 是主判据（抽取前就是它，逐字保留）；
#: ★settle_extra_anchors★：五重结算页的两个独有锚点（返回房间 / 解散）；
#: ★state_names★：这三颗状态名不按默认后缀走（抽取前就是这三颗名字，pipeline 按名匹配）。
_CLASSIFY_CFG = core.SceneConfig(
    scene="wuchong",
    state_prefix="wuchong",
    classify_order=_CLASSIFY_ORDER,
    battle_direct_hud=True,
    settle_extra_anchors=("返回房间", "解散"),
    no_entry_text=NO_ENTRY_TEXT,
    quest_clear=True,
    lord_list_all=("更新列表", "通过房间号码参加"),
    lord_list_tabs=(LORD_TAB, JOVEN_TAB),
    lord_list_rows=(ROW_NAME, "五重决战"),
    mode_anchors=(SOLO_TEXT, MULTI_TEXT),
    detail_titles=(DETAIL_TITLE, "五重决战"),
    detail_markers=("推荐编成", "战斗"),
    state_names={
        "party": WUCHONG_TEAM,
        "coop_room": WUCHONG_ROOM,
        "no_entry": WUCHONG_NO_ENTRY,
    },
)

ACTIVE_STATES = (
    WUCHONG_LORD_LIST,
    WUCHONG_DETAIL,
    WUCHONG_MODE,
    WUCHONG_ROOM,
    WUCHONG_RECRUIT_DIALOG,
    WUCHONG_TEAM,
    WUCHONG_SETTLE,
    WUCHONG_BATTLE,
)

#: ★#74★ 真正「离开本场战斗」的画面 —— 计数点搬到「进战斗」后，续关回到战斗不算新的一场；
#: 这些状态表示「这一场已经结束、回到了导航/结算」，故在此清掉「本场已续关」标记 **与**
#: 「本场战斗 episode 闩锁」(``in_fight``)，让**下一场**重新计数。★刻意不含 ``loading`` /
#: ``unknown`` / ``wuchong_battle``★：续关后「GAMEOVER → 点了续关 → loading → 又回到战斗 HUD」
#: 这条路径里的过渡帧若清了标记，回到战斗就会被**误计**成一场新的（违反规格 B2「打输后续关不算
#: 新的一次」）；真机 HUD 间歇闪回 ``unknown`` 更是同一根因（见 :func:`_observe`）。
_FIGHT_LEAVE_STATES = (
    WUCHONG_SETTLE,
    WUCHONG_TEAM,
    WUCHONG_ROOM,
    WUCHONG_RECRUIT_DIALOG,
    WUCHONG_MODE,
    WUCHONG_DETAIL,
    WUCHONG_LORD_LIST,
    WUCHONG_LEVEL_REQUIRED,
    "main_city",
    "activity",
    "relogin",
)

#: ★运维裁决（2026-10-16）★ 手操引擎判为「被推出战斗」（:data:`PAGE_LEFT`）的**已知非战斗页**：
#: ``classify`` 的既有状态名，**复用不复制**。★刻意不含 ``unknown`` / ``loading`` /
#: ``wuchong_battle``★（认不出的帧 / 转场帧 / 战斗帧 → **继续点**），也**不含** ``wuchong_settle``
#: （结算归 :data:`PAGE_OVER`）。画面是这些之一 = 已被推出本场战斗 → 停手交还管线接房间流程。
PAGE_LEFT_STATES = (
    WUCHONG_ROOM,
    WUCHONG_MODE,
    WUCHONG_TEAM,
    WUCHONG_DETAIL,
    WUCHONG_LORD_LIST,
    "main_city",
    "activity",
    WUCHONG_LEVEL_REQUIRED,
    "relogin",
)

# 「本轮已收工」标记（有界收工/告吹时写）。
LEDGER_SCOPE = "wuchong"
RUN_DONE_KEY = f"{LEDGER_SCOPE}/run/completed"

# 整句候选（未真机自然触发过 → 绝不宽匹配）。
# ★#119★ 换日重进 / 130 级限制两条判据已上提到 battle_loop_core（唯一一份），本文件不再存副本。
# ★#63★：主城判据不在本文件复制一份（复制即漂移）；改用共享源 agent/battle_loop_core 的
# 「三独有锚点 ≥2」判据（与 #31 的 harness、深渊/幻想 同源）。六锚点会把编队页过渡帧 /
# 领主战列表页误判成主城（列表页已在 classify 里被显式接走，但编队页没有）。

# 战斗 HUD：★判据不在本文件复制一份★（复制即漂移，单一真源是本仓硬规矩）。
#   唯一真源 = :func:`battle_loop_core.is_battle_hud`（= ``scene.auto_switch.BATTLE_HUD_ANCHORS``
#   逐字同源）。这里历史上曾自带一份 ``_TIME_RE`` / ``_HHMM_RE`` 的「独立文本框」判据；
#   真机（A, 2026-10-16 run2）HUD 是**一个合并框**（'时间 29:30 分数 38629797530'），
#   旧判据恒判 unknown → 见 #74 与共享版 ``_branch_battle`` 的 battle_direct_hud 注释。

# 有界收工默认值。
# ★ADR 0005★ 「迷路」闸门已改用**连续秒数**：旧的帧数上限（120 帧）已删除
#   —— 它是随运行时长单调增长的量，长战斗必越线。阈值见
#   ``scene.wuchong.LOST_SEC``（override 的 ``lost_sec`` 优先）。
DEFAULT_NO_PROGRESS_SEC = 900

_LOCK = threading.Lock()
_SESSION = {
    "task_id": None,
    "manual": False,          # 本次任务是否手操（= 自动关）。只有五重可为 True。
    # ★#74★：手操引擎「连续 0 点击且 stopped=manual_off」的连击计数（防御性可见失败）。
    #   见 :data:`ZERO_TAP_YIELD_LIMIT`；由 WuchongBattleAction 每次引擎返回后维护，
    #   由 WuchongGiveUpRecognition 读作收工理由（复用既有 StopTask 出口，绝不另造机制）。
    "zero_tap_yield_streak": 0,
    # ★ADR 0005 / #76★ 「迷路」时钟：连续多久认不出画面（旧的帧数累计计数器已删除）。
    #   战斗 episode 内的 unknown **不打点**（#76 的结论并入 ``LostClock.observe(in_fight=...)``）。
    "lost": core.LostClock(),
    "renav_count": 0,
    "net_misses": 0,
    # ★#114★ 三种断连（F2032/A4050/暂时无法连接）有界重启的会话状态：
    #   · net_kind：当前断连文案（换 kind = 新 episode，重算 10s 冷却）；
    #   · net_first_ts：当前 episode 首次被看到 monotonic 时刻（0 = 不在断连屏）；
    #   · net_restarts：本任务已重启客户端次数（换 task_id 清零；上限 NET_RESTART_LIMIT）。
    "net_kind": None,
    "net_first_ts": 0.0,
    "net_restarts": 0,
    "start_ts": 0.0,
    "last_progress_ts": 0.0,
    "last_state": None,
    "last_observe_ts": 0.0,
    "recruit_started": False,
    "battle_taps": 0,
    "room_first_ts": 0.0,     # 进入共斗房序列的起点（0 = 不在房间）；维护见 _observe
    # ★本票「打几次」★：本场景已打场次（账本恢复）+ 目标场次（0 = 不限制）。
    #   ★#74 修正（规格 B2/D2）★：计数点 = **跃变进入战斗**（战斗 HUD 首次出现）那一刻 +1
    #   （并落账本 wuchong/fight/{n}）；收工由既有 wuchong_giveup 读 target_fights 判定。
    #   旧实现记在【结算页】→ 真机所有战斗都以 GAMEOVER/关卡失败收场、从不出现结算页 →
    #   账本 fight=0、「打几次」永远到不了 → 只能被兜底掐死。
    "fights_done": 0,
    "target_fights": 0,
    # ★#74★：本场战斗是否已出现过 GAMEOVER 续关屏（规格 B2「打输后续关不算新的一次」）。
    #   _observe 见到 is_gameover_page 即置真（去重之前，连帧也认）；续关后回到战斗**不再** +1；
    #   真正离开本场（_FIGHT_LEAVE_STATES）才清掉，让下一场重新计数。_sync_task 换任务时复位。
    "battle_had_continue": False,
    # ★2026-10-16 运维裁决（计数 episode 闩锁）★：是否**正处在本场战斗 episode 里**。
    #   命中 ``wuchong_battle`` 且 ``in_fight == False`` → 计一场（+1）并置真；
    #   ★只在 :data:`_FIGHT_LEAVE_STATES`（真正离开本场）时清假★ —— 真机 HUD 间歇闪回
    #   ``unknown``（每 2~3 秒一次）**不得**清它，否则每次闪回都再计一场（诊断跑 run5：一次真
    #   战斗被计成 fight/1..4、25 秒就「已打够 4 次」收工，零场真正打完）。
    #   与 battle_had_continue 叠加：续关回到战斗既不清 in_fight 也不重复计。
    "in_fight": False,
    # ★2026-10-19 收尾★：打够次数后「先等结算收尾」的起点（0.0 = 不在收尾）。
    #   维护见 :func:`finish_settle_wait`；消费方 = WuchongGiveUpRecognition（收工时机）
    #   与 WuchongActAction（收尾时别点【再次挑战】、优先【解散】）。换任务时复位。
    "finish_settle_ts": 0.0,
    # ★#86★：用户可见输出用的闩锁（每次战斗只报一次「完成」；任务内只报一次「要打几次」）。
    "settle_said": False,
    "said_target": False,
    # ★#86★：门票（今天剩余次数）最近一次读到的值；连续认不出画面的连击数。
    "remaining_plays": None,
    "unknown_streak": 0,
    # ★#72「GAMEOVER 续关」★：本场景已续关次数（账本恢复）+ 目标上限（0 = 不限制）。
    #   · gameover_seen：**本 GAMEOVER episode** 是否已计过（连帧只算一次；离屏即清零）；
    #   · continues_done：已续关次数（跨重开由账本 wuchong/continue/{n} 恢复）；
    #   · target_continues：上限（由 WuchongContinueGuard 的识别参数现设；0 = 不限）。
    "gameover_seen": False,
    "continues_done": 0,
    "target_continues": 0,
    # ★#72★ gameover_first_ts：**当前 GAMEOVER episode** 的起点（0.0 = 不在 GAMEOVER 屏）。
    #   用于「同一屏卡住超过 CONTINUE_STUCK_SEC → 带原因收工」的有界等待（点击无效 / 星导石不足）。
    "gameover_first_ts": 0.0,
    # ★coop-fix2 P0★：本任务是否**进过共斗房**（粘性：进过就真；只在换任务时清零）。
    #   单人编队页与「人齐后的共斗厅」是**同一张队伍页**（classify 都含 Party/SET + 挑战），
    #   光看画面分不开；「本轮是否进过房间」是唯一能分开二者的信号 —— 多人模式据此拒绝
    #   从**从未进过房的**编队页直接开战（真机 07:45 leg_b：那是上一轮单人留下的编队页，
    #   被直接点了「挑战」→ 又打单人）。见 scene.wuchong 的 WuchongStaleTeam / 界面选项「游戏模式」。
    "room_seen": False,
    # ★#71★：「本场战斗是否已尝试过关自动」的**每场一次**闩锁（另一条 lane 的战斗页
    #   关自动动作读它）。_sync_task 换任务时复位 False；_observe 见到「跃变进入
    #   WUCHONG_BATTLE」也复位 False（故新一场战斗会重新允许尝试一次）。
    "battle_auto_off_tried": False,
}

_OCR_CACHE: dict[tuple, list] = {}
_OCR_CACHE_TS: dict[tuple, float] = {}


# ---------------------------------------------------------------------------
# 图像 / OCR / 点击（与 abyss_impl 同构）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ★#86★ 用户可见输出 vs 机制日志；★#143★ 两个出口都委托 :mod:`reporting`
#
# 运维原话：「你的五重输出到用户的界面上有很多**乱七八糟的东西**，你只要告诉用户**要打几次、这是第几次**就好了」。
#   · :func:`_say` —— **用户可见**（MFAAvalonia 日志面板）：要打几次 / 第 i/N 次 开始 / 完成 /
#     收工原因，以及 #143 的统一进度行（``[进度] …``，格式只在 :mod:`reporting` 里）；
#   · :func:`_log` —— 机制日志（点击/校验/闩锁/心跳/账本…）：委托 :func:`reporting.log`，
#     同时按 #86 契约逐行落 ``debug/wuchong_agent.log``；``QUIET`` 时不进 stdout（GUI 干净），
#     离线守卫 / 真机 runner 默认 QUIET=False 仍可在 stdout 取证。
#   ★#143 是**追加**统一进度行，不是替换 #86 的旧四类用户行★：hooks_86 的 W3 把旧行逐字钉死，
#     所以面板上「五重决战：第 i/N 次 开始」与「[进度] 五重决战 i/N 次」会各出现一次 ——
#     两者都是**用户可见行**，不是机制日志（机制日志才归 ``debug/agent.log``）。
# ---------------------------------------------------------------------------
QUIET = False
_LOG_PATH = None


def set_quiet(on=True, log_path=None):
    """由 ``agent/main.py --quiet`` 调用：打开静音（机制日志只进文件）。"""
    global QUIET, _LOG_PATH
    QUIET = bool(on)
    if log_path:
        _LOG_PATH = Path(log_path)


def _append_log(line):
    try:
        path = _LOG_PATH or (_REPO_ROOT / "debug" / "wuchong_agent.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 8 * 1024 * 1024:
            path.write_text("", encoding="utf-8")          # 有界：超 8MB 清空重来
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S") + " " + line + "\n")
    except Exception:  # noqa: BLE001  日志失败绝不影响主流程
        pass


def _log(msg=""):
    """机制日志：委托 :func:`reporting.log`，并保留 #86 的两条承重语义。

    ★#86 契约（承重，hooks_86 把守）★：
      · 机制日志**始终**逐行落盘 ``debug/wuchong_agent.log``（:func:`_append_log`）；
      · :data:`QUIET` 为真时**不进 stdout** —— 离线守卫 hooks_86 用 ``redirect_stdout`` 抓
        stdout 取证，它只翻 ``wuchong_impl.QUIET``、不碰 ``reporting`` 的全局静音；若这里
        无条件委托 ``reporting.log``，机制行就会漏进它抓到的 stdout（守卫当场变红）。
    ``reporting`` **真的**已经静音时（生产 GUI，``agent/main.py --quiet``）委托是安全的：
    它只落盘 ``debug/agent.log``、不进面板。
    """
    _append_log(msg)
    if QUIET and not reporting.is_quiet():
        return
    reporting.log(msg)


def _say(msg):
    """★用户可见★：委托 :func:`reporting.say`（永远进面板，静音吞不掉），同时留档。

    ★#86 契约（承重，hooks_86 / hooks_87 把守）★：离线守卫用 ``contextlib.redirect_stdout``
    抓「用户可见行」—— 它们抢的是**当前** ``sys.stdout``，而 ``reporting.say`` 写的是导入时
    抓到的真实 stdout（这正是它「静音吞不掉」的原因）。故当有人把 ``sys.stdout`` 重定向走时，
    再往它写一份供取证。

    ★镜像的闸是「reporting 没静音」，**不是** :data:`QUIET`★（#114 真实验证里踩到的）：
    ``QUIET`` 管的是**机制日志**（:func:`_log`），用户可见行按 #86 的原语义**永远出**。
    若把镜像也挂在 ``not QUIET`` 上，``hooks_114``（它只在 ``_drive`` 期间置 ``QUIET=True``）
    就抓不到「客户端重启 N 次仍连不上」这句收工原因 —— 守卫当场变红。生产 GUI 里
    ``reporting.is_quiet()`` 为真 ⇒ 不镜像（否则会往日志文件里多写一份）。
    """
    _append_log("[say] " + msg)
    reporting.say(msg)
    try:
        if not reporting.is_quiet() and sys.stdout is not reporting._REAL_STDOUT:
            print(msg, flush=True)
    except Exception:  # noqa: BLE001  输出失败绝不影响主流程
        pass


# ---------------------------------------------------------------------------
# ★#143★ 进度线（「打几次」的步进）—— 格式只在 reporting 里，本模块只报「什么时候算一步」
#
# 口径（唯一真源 docs/spec/progress-visibility.md §C「五重决战」那一行）：
#   · :func:`_start_progress`：任务开始、读到 ``target_fights`` 时（共 N 次；0 = 不限）；
#   · :func:`_step_progress` ：**进入一场战斗**时 —— 与 :func:`_count_fight` 是同一个计数点
#     （#76 / 规格 B2），★一个字都不许搬到结算页★；
#   · :func:`_done_progress` ：收工兜底出口（:class:`WuchongGiveUpRecognition`），把既有
#     ``reason`` 原文带出来，不新造文案。
# ★绝不在本模块拼 ``[进度]`` 字符串★（一拼就有第二份格式；hooks_143 ①④ 把守）。
# ---------------------------------------------------------------------------
#: 本任务的进度线实例（唯一）。换任务时由 :func:`_sync_task` 置 None；``Progress`` 自带
#: 单调去重与「收工后静默」，所以重复调用是安全的。
_PROGRESS = None


def _progress(target_fights=None):
    """取本任务的进度线（首次调用时创建；总量 / 备注来自「打几次」）。"""
    global _PROGRESS
    with _LOCK:
        if _PROGRESS is None:
            total = (
                int(_SESSION.get("target_fights") or 0)
                if target_fights is None
                else int(target_fights)
            )
            _PROGRESS = reporting.Progress(
                "五重决战", total=total, unit="次", note=f"打几次={total}"
            )
        return _PROGRESS


def _start_progress(target_fights):
    """任务开始 / 读到「打几次」→ 打一条 start（同一任务只出一条）。"""
    try:
        return _progress(target_fights).start(total=int(target_fights))
    except Exception:  # noqa: BLE001  进度行绝不拖垮跑图
        return ""


def _step_progress(n):
    """进入一场战斗 → 打一条 step（★#76 计数点：进场算一步，结算不算★）。"""
    try:
        return _progress().step(int(n))
    except Exception:  # noqa: BLE001
        return ""


def _done_progress(reason):
    """收工 → 打一条 done，把**既有 reason 原文**带出来（不新造文案）。"""
    try:
        return _progress().done(str(reason or ""))
    except Exception:  # noqa: BLE001
        return ""


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
    """用 pipeline 原生 Click 动作点击 720 空间 (cx,cy)（★不走 controller.post_click★）。"""
    try:
        context.run_action("WuchongClick", box=(int(cx) - 1, int(cy) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 点击失败 ({cx},{cy})：{exc}")
        return False


def _pick(items, patterns, roi=None, prefer=None):
    """在 OCR 项里找第一个匹配任一正则的按钮框（与 abyss_impl._pick 同口径）。"""
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


# ---------------------------------------------------------------------------
# ★#114★ 三种断连文案的**唯一判据**（F2032 / A4050 / 暂时无法连接）
#
# 为什么只允许一份：真机只有这三条路径，任何一条判错都会导致「点重试点不动」→ 长跑静默。
# 把文案表放 scene.wuchong（真源）、切分逻辑放这里（机制），pipeline 三个断连节点统一走
# ``wuchong_net`` custom recognition —— 别在 pipeline 里再写一份 OCR expected 列表。
# ---------------------------------------------------------------------------
def _ocr_texts(items) -> list[str]:
    """把 ``[(text, box)]`` / ``[text]`` / 混排归一成纯文本列表（纯函数）。"""
    out: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, (tuple, list)) and item and isinstance(item[0], str):
            out.append(item[0])
    return out


def net_disconnect_kinds(items) -> list[str]:
    """★纯函数★：返回这一帧命中的**所有**断连种类（正常帧返回 []）。

    三种文案的判据来自 :data:`NET_DISCONNECT_TEXTS`（真源 scene.wuchong ②h）；正常主城 /
    战斗帧不得命中。返回列表而不是单个值，是为了让守卫能断言「一帧只命中一种」（互不混淆）；
    生产路径用 :func:`net_disconnect_kind` 取第一种。
    """
    texts = _ocr_texts(items)
    hits: list[str] = []
    for kind in NET_DISCONNECT_KINDS:
        patterns = NET_DISCONNECT_TEXTS.get(kind, ())
        if any(re.search(pat, text or "") for pat in patterns for text in texts):
            hits.append(kind)
    return hits


def net_disconnect_kind(items):
    """★纯函数★：这一帧的断连种类（``F2032`` / ``A4050`` / ``UNREACHABLE``；正常帧 None）。"""
    hits = net_disconnect_kinds(items)
    return hits[0] if hits else None


# ---------------------------------------------------------------------------
# 画面分类（#119：判据只有 battle_loop_core.classify 一份；本文件只提供场景数据）
#
# ★行为冻结★：抽取前这 12 个分支的判据与顺序原样保留（见 _CLASSIFY_CFG / _CLASSIFY_ORDER）；
# 本函数**只许是这一行**。再往这里加一个分支 = 「一个修复只对一个场景生效」的形态复活
# （#107 的 912 秒死循环就是这么来的），hooks_119 ② 会红。
# ---------------------------------------------------------------------------
def classify(items, relogin_phrases=()):
    return core.classify(_CLASSIFY_CFG, items, relogin_phrases)


# ---------------------------------------------------------------------------
# 会话 / 有界收工
# ---------------------------------------------------------------------------
def _mark_run_done():
    try:
        if ledger.mark_done(RUN_DONE_KEY):
            _log(f"[wuchong] 写入收工标记 {RUN_DONE_KEY}")
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 写收工标记失败：{exc}")


#: ★#86★ 「今天剩余次数 xN」的 OCR 判据（真机模式页底部，如 `今天剩余次数x 3`）。
_REMAIN_RE = re.compile(r"今天剩余次数\s*[x×X*]?\s*(\d+)")
#: ★#86★ 连续认不出多少次 + 出现错误关键词 → 判定「错误弹窗」并停手。
UNKNOWN_MODAL_LIMIT = 3
#: ★#86★ 错误提示关键词（认不出的画面上出现这些 = 大概率是游戏错误框，绝不盲点）。
_ERROR_HINTS = ("剩余次数", "不足", "错误", "失败", "无法挑战", "已达上限")


def _remaining_plays(items):
    """从 OCR 项里读「今天剩余次数 xN」的 N（读不到返回 None —— 绝不猜）。"""
    for text, _box in items or []:
        m = _REMAIN_RE.search(text or "")
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _has_error_hint(items):
    texts = [t or "" for t, _b in (items or [])]
    return any(any(h in t for h in _ERROR_HINTS) for t in texts)


def _no_entry_reason():
    """★#87★「当前不满足出战条件」的收工原因（None = 不是这一屏）。

    ★运维裁决（2026-10-17）★：这一屏**一律当「门票不够了」**处理 —— 中止五重决战，
    用户可见就一句话；弹窗里的三条自查（关卡开放 / 入场门票 / 队伍限制 / 幻想连战专属装备）
    走 :func:`_log` 进调试日志，不刷用户的界面。
    """
    return "门票不够了"


def _no_entry_detail() -> str:
    """★#87★ 弹窗原文（只进调试日志，给排障用；不进用户界面）。"""
    return (
        "「当前不满足出战条件」弹窗原文：请检查关卡开放状态、入场门票和队伍限制；"
        "幻想连战专属装备及魂珠仅限幻想连战使用（真机帧 debug/wc448_popup_ready.png）"
    )


def _sync_task(task_id):
    global _PROGRESS
    if task_id is None:
        return
    with _LOCK:
        if _SESSION["task_id"] == task_id:
            return
        _SESSION["task_id"] = task_id
        # ★#143★ 换任务 = 换一条进度线（start/step/done 从头来；旧任务的进度不许串到新任务）。
        _PROGRESS = None
        _SESSION["manual"] = False
        _SESSION["zero_tap_yield_streak"] = 0
        # ★ADR 0005★ 换任务 = 换一条迷路时钟（旧的帧数计数器也在这里清零）。
        _SESSION["lost"].reset()
        _SESSION["renav_count"] = 0
        _SESSION["net_misses"] = 0
        # ★#114★ 换任务 = 重启次数清零（上限是「3 次/任务」）；断连 episode 也一并复位。
        _SESSION["net_kind"] = None
        _SESSION["net_first_ts"] = 0.0
        _SESSION["net_restarts"] = 0
        _SESSION["start_ts"] = time.monotonic()
        _SESSION["last_progress_ts"] = time.monotonic()
        _SESSION["last_state"] = None
        _SESSION["last_observe_ts"] = 0.0
        _SESSION["recruit_started"] = False
        _SESSION["battle_taps"] = 0
        _SESSION["room_first_ts"] = 0.0
        _SESSION["room_seen"] = False
        # ★#71★：换任务 → 「本场已尝试关自动」闩锁复位（新任务的战斗重新允许尝试一次）。
        _SESSION["battle_auto_off_tried"] = False
        # ★本票「打几次」★：会话场次/目标按新任务复位（目标由识别参数现设）。
        _SESSION["fights_done"] = 0
        _SESSION["target_fights"] = 0
        # ★#74★：换任务 → 「本场已续关」标记复位（新任务的第一场照常计）。
        _SESSION["battle_had_continue"] = False
        # ★2026-10-16 运维裁决★：换任务 → 战斗 episode 闩锁复位（新任务的第一场照常计）。
        _SESSION["in_fight"] = False
        # ★2026-10-19 收尾★：换任务 → 收尾计时复位（新任务的「打够」从零起算）。
        _SESSION["finish_settle_ts"] = 0.0
        # ★#72「GAMEOVER 续关」★：会话续关计数/episode 标记按新任务复位（上限由识别参数现设）。
        _SESSION["gameover_seen"] = False
        _SESSION["continues_done"] = 0
        _SESSION["target_continues"] = 0
        _SESSION["gameover_first_ts"] = 0.0
        # ★本票「开始类闩锁 = 重试窗口」★：换任务时把时间戳清零（绝不把上一任务的闩锁带过来
        #   —— 否则新任务的「挑战/开始招募」会被旧时间戳挡下；真源 scene.wuchong ②e）。
        #   ★#116★ ``coop_challenge`` 同理（共斗房那颗「挑战」，真源 ②e'）。
        for _name in ("recruit_start", "battle_start", "coop_challenge"):
            _SESSION[f"latch_ts_{_name}"] = 0.0

    # ★跨重开恢复（与 abyss/phantom 同口径）★：账本里有收工标记 → 清空五重账本（含场次），
    # 从头开始打；否则保留账本、按已打场次继续（中途接管/重启不重复计数）。
    try:
        if ledger.is_done(RUN_DONE_KEY):
            n = ledger.reset(LEDGER_SCOPE)
            _log(f"[wuchong] 新任务 task_id={task_id}：上一轮已收工，清空五重账本（{n} 条）")
        else:
            _log(f"[wuchong] 新任务 task_id={task_id}：未发现收工标记，保留账本按进度继续")
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 账本检查失败：{exc}")
    done = _recover_fights()
    with _LOCK:
        _SESSION["fights_done"] = done
    if done:
        _log(f"[wuchong] 账本恢复：本场景已打 {done} 场（继续计到『打几次』为止）")
    cont = _recover_continues()
    with _LOCK:
        _SESSION["continues_done"] = cont
    if cont:
        _log(f"[wuchong] 账本恢复：本场景已续关 {cont} 次（继续计到『续关几次』为止）")


def _recover_fights():
    """用账本恢复「本场景已打场次」（``wuchong/fight/{n}`` 的最大 n 与笔数取大）。"""
    try:
        keys = ledger.scope(FIGHT_LEDGER_PREFIX)
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 读五重账本失败：{exc}")
        return 0
    n = 0
    for k in keys:
        m = re.search(r"/fight/(\d+)$", k)
        if m:
            n = max(n, int(m.group(1)))
    return max(n, len(keys))


def _record_fight(n):
    """把「第 n 场」落账本（跨重开恢复）；返回该场次。"""
    key = f"{FIGHT_LEDGER_PREFIX}/{int(n)}"
    try:
        ledger.mark_done(key)
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 写场次账本失败 {key}：{exc}")
    return int(n)


def _count_fight():
    """本场景又**进入一场**新战斗（跃变进入战斗 HUD 首次出现）：会话 +1 并落账本。

    ★#74 修正（规格 B2）★：计数点 = **进入战斗**，不是结算页（旧实现记在结算页 → 真机所有
    战斗都以 GAMEOVER/关卡失败收场、从不出现结算页 → 账本 fight=0）。返回新的已打场次。
    """
    with _LOCK:
        n = int(_SESSION["fights_done"]) + 1
        _SESSION["fights_done"] = n
    _record_fight(n)
    _log(f"[wuchong] 已进入第 {n} 场战斗（账本 {FIGHT_LEDGER_PREFIX}/{n}）")
    with _LOCK:
        _SESSION["settle_said"] = False
        target = int(_SESSION.get("target_fights") or 0)
    # ★#86★ 用户可见：只报「这是第几次 / 一共几次」。
    _say(f"五重决战：第 {n}{f'/{target}' if target else ''} 次 开始")
    # ★#143★ 进度线：**进入一场战斗**就是一步（与上面 +1 同一个计数点 —— 规格 B2 / #76，
    #   绝不搬到结算页；进度只是把这个既有计数点显示出来）。
    _step_progress(n)
    return n


# ---------------------------------------------------------------------------
# ★#72 GAMEOVER 续关★ —— 账本镜像（与「打几次」同口径：既有账本 + 既有收工机制）
# ---------------------------------------------------------------------------
def _recover_continues():
    """用账本恢复「本场景已续关次数」（``wuchong/continue/{n}`` 的最大 n 与笔数取大）。

    序号正则从 :data:`CONTINUE_LEDGER_PREFIX` **派生**（不再硬编码 ``/continue/`` —— 改前缀
    即同步，不会留下一个静默失效的旧正则）。
    """
    tail = re.escape(CONTINUE_LEDGER_PREFIX.rsplit("/", 1)[-1])
    pat = re.compile(rf"/{tail}/(\d+)$")
    try:
        keys = ledger.scope(CONTINUE_LEDGER_PREFIX)
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 读续关账本失败：{exc}")
        return 0
    n = 0
    for k in keys:
        m = pat.search(k)
        if m:
            n = max(n, int(m.group(1)))
    return max(n, len(keys))


def _record_continue(n):
    """把「第 n 次续关」落账本（跨重开恢复）；返回该次数。"""
    key = f"{CONTINUE_LEDGER_PREFIX}/{int(n)}"
    try:
        ledger.mark_done(key)
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong] 写续关账本失败 {key}：{exc}")
    return int(n)


def _count_continue():
    """本场景又开始一次续关（新的 GAMEOVER episode）：会话 +1 并落账本。返回新的已续关次数。"""
    with _LOCK:
        n = int(_SESSION["continues_done"]) + 1
        _SESSION["continues_done"] = n
    _record_continue(n)
    _log(f"[wuchong] 已续关第 {n} 次（账本 {CONTINUE_LEDGER_PREFIX}/{n}）")
    return n


def is_gameover_page(items) -> bool:
    """当前 OCR 项是否为 GAMEOVER 续关页。

    ★子串判定，与 pipeline 叶子同口径★：**某一项**文本含 :data:`CONTINUE_TITLE_TEXT`（`GAMEOVER`）
    **且**某一项文本含 :data:`CONTINUE_PROMPT_TEXT`（`是否续关`）→ True。纯函数，离线可测。
    """
    texts = [(t or "") for t, _b in (items or [])]
    has_title = any(CONTINUE_TITLE_TEXT in t for t in texts)
    has_prompt = any(CONTINUE_PROMPT_TEXT in t for t in texts)
    return bool(has_title and has_prompt)


def fight_target_reached(target_fights: int, fights_done: int, in_fight: bool) -> bool:
    """★#76★ 纯函数：「已打够 N 次」这条收工理由**现在**成不成立。

    ★计数与收工时机是两件事★：计数点仍是「进入战斗」（规格 B2/D2 —— 「打几次 = N」就是**进场 N 次**，
    这笔账、这个理由文案、账本一律不变）；本函数只把**收工时机**推到「本场收场之后」。

    ★为什么不能在战斗内收工（承重）★：
      · 手操：进第 N 场就 StopTask = 玩家角色原地不动、球停在弹板等「点击」→ 本场必输、体力白烧。
        运维现场原话「不点板子我的任务死了」。真机 2026-10-17 单人 run1（打几次 = GUI 默认 1）：
        全日志**一次** ``info:[wuchong_battle] 手操开始`` 都没有，紧接着就是
        ``触发收工兜底：已打够 1 次（打几次=1）（state=wuchong_battle）`` —— 收拾的是自己刚开的战斗。
      · 自动：同上，任务停在战斗里，游戏还在自己打；下一个任务接上来时画面还是战斗页。
    ★不是「永不收工」★：本场收场（结算 / 被推出 / 回主城 / 回到编队页 → ``in_fight`` 落回 False）
    后本条立刻成立；其余收工理由（未知画面 / 无进展 / 总时长 / 共斗房 / 手操 0 点击）不受影响。
    """
    if int(target_fights) <= 0:
        return False
    if int(fights_done) < int(target_fights):
        return False
    return not in_fight


# ---------------------------------------------------------------------------
# ★2026-10-19 收尾（#76 收工时机的第二次修订）★：打够次数后**先把本场结算点完再收工**。
#
# 真机现场（设备 127.0.0.1:16385，2026-10-19 08:01，`install/logs/log-20261019.log`）::
#
#     08:01:17  五重决战：第 80/80 次 完成
#     08:01:18  [wuchong_act] state=wuchong_settle 点击 '继续' …
#     08:01:21  [wuchong] 写入收工标记 wuchong/run/completed
#     08:01:21  五重决战：收工 —— 已打够 80 次（打几次=80）
#     08:01:22  任务 自动刷深渊EX 开始
#     08:06:23  [abyss] 收工 —— 300s 一场都没有完成（关卡打不过？）（state=unknown）
#
# 五重在**共斗结算第一屏**（QUESTRESULT + 继续）就 StopTask，设备被留在结算页；队列里的
# 下一个任务（自动刷深渊EX）从这一页起步：它把共斗结算页认成自己的 `abyss_settle`（共用
# QUESTRESULT 锚点），点【继续】推进两屏后遇到只有【解散】/【返回房间】的第三屏 —— 它的
# 结算出口全都不命中，只能空转，300s 零进度收工（运维看到的就是「深渊EX 很快就结束了」）。
#
# ★收工时机 = 「打够」+「本场结算收尾完成」★（计数点 / 理由文案 / 账本一个字都不动）：
#   · 还停在结算页（或它前后的 loading / unknown 过渡帧）→ **先不收工**，让本场景自己的
#     结算节点把【继续】点完、用【解散】离开共斗（真机帧 `tools/frames/coop_result_dissolve.png`
#     → 点【解散】→ `tools/frames/coop_result_home.png` 主城，与 #48 的归位规则同一条证据）；
#   · 落到结算页以外的任何页面（主城 / 编队页 / 房间…）→ 立刻按既有理由收工（最多再等
#     :data:`FINISH_SETTLE_MAX_SEC`，绝不无限等）；
#   · GAMEOVER 页**不算**结算（它是失败页，`classify` 会落到 unknown）：这条出口保持原样，
#     绝不因为等结算而把失败页交给续关链再开一局。
# ---------------------------------------------------------------------------
#: 收尾阶段允许停留的「过渡页」：结算页本身 + 它前后的 loading / unknown 帧。
#: ★GAMEOVER 不在这里★（`classify_gameover` 单独判；见 :func:`finish_settle_wait`）。
FINISH_SETTLE_STATES = (WUCHONG_SETTLE, "loading", "unknown")
#: 收尾等待上限（秒）。共斗结算三屏真机实测 5-15s；留足动画/掉帧余量后仍远小于 no_progress_sec。
FINISH_SETTLE_MAX_SEC = 120.0


def finish_settle_wait(state, gameover, reached, started_ts, now):
    """★打够次数后是否「先等结算收尾」★（纯函数，离线可单测）。

    返回 ``(wait, started_ts)``：
      * ``wait=True``  = 现在**不要**按「已打够」收工 —— 还在结算（或它前后的过渡帧）里，
        让 pipeline 的结算节点继续点；``started_ts`` = 收尾起点（跨帧保持）；
      * ``wait=False`` = 按既有语义收工（已离开结算页 / 失败页 / 收尾超时 / 根本没打够）。

    ★为什么必须带 ``gameover``★：``classify`` 对 GAMEOVER /「是否续关？」页返回 ``unknown``，
    而 ``unknown`` 在 :data:`FINISH_SETTLE_STATES` 里（结算页之间确有 loading/unknown 过渡帧）。
    若不显式排除，失败页会被当成「结算过渡」继续等 —— 那一等就会让 GAMEOVER 续关链
    （``WuchongContinueGuard`` / ``[JumpBack]PubGameOverContinue``）抢先点【续关】再开一局，
    「打几次」的收工时机被无限推迟。失败页一律**立刻**按既有理由收工（旧行为不变）。
    """
    if not reached or gameover:
        return False, 0.0
    if state not in FINISH_SETTLE_STATES:
        return False, 0.0
    started = float(started_ts or 0.0)
    if started <= 0.0:
        started = float(now)
    if (float(now) - started) > FINISH_SETTLE_MAX_SEC:
        return False, started
    return True, started


def finish_adjust_targets(what, what_next, finishing, skip=(), prefer=()):
    """★收尾阶段的按钮选择★（纯函数）：过滤掉会**再开一局**的按钮，并优先【解散】。

    * ``skip``：收尾时从 ``what`` / ``what_next`` 里剔除的按钮正则
      （pipeline 给 ``WuchongSettleContinue`` 配 ``["^再次挑战$", "^继续挑战$"]`` —— 单人的
      结算屏会先弹【再次挑战】，收尾时点它就是**新开一局**，把「打几次」无限推迟）；
    * ``prefer``：收尾时**优先**点击的按钮正则（pipeline 给 ``WuchongSettleReturnRoom`` 配
      ``["^解散$"]`` —— 共斗结算第三屏同时有【解散】/【返回房间】，只有【解散】一步回主城；
      正常运行时仍点【返回房间】回房续战，绝不解散房间）。

    返回 ``(what, what_next, prefer)``（都不就地改入参）。
    """
    what = list(what or [])
    what_next = list(what_next or [])
    if not finishing:
        return what, what_next, []

    def skipped(pattern):
        """这个按钮正则是否属于「收尾时要剔除」的那一颗。

        ★按**整串**比对，不把 skip 当搜索词去搜按钮正则本身★：``what`` 里存的是正则
        （如 ``^再次挑战$``），拿 ``^再次挑战$`` 去 ``re.search`` 它自己是匹配不上的
        （字符串里确有字面 ``^``/``$``）。故先按字面相等，再退一步用去掉两端锚点的整串比对。
        """
        body = str(pattern or "").strip("^$")
        for s in skip:
            if pattern == s or body == str(s or "").strip("^$"):
                return True
        return False

    def kept(patterns):
        return [p for p in patterns if not skipped(p)]

    return kept(what), kept(what_next), list(prefer or [])


def _observe(state, info, items):
    now = time.monotonic()
    count = False
    with _LOCK:
        # ★#74★：GAMEOVER 续关屏出现即置「本场已续关」标记（在**去重之前** —— 同一屏的连帧也要
        #   认；判据复用既有 :func:`is_gameover_page`，绝不另造）。续关后回到战斗据此不再 +1。
        if is_gameover_page(items):
            _SESSION["battle_had_continue"] = True
        changed = state != _SESSION["last_state"]
        stale = (now - _SESSION["last_observe_ts"]) > 1.2
        if not changed and not stale:
            return
        _SESSION["last_observe_ts"] = now
        _SESSION["last_state"] = state
        # ★ADR 0005 / #76★ 「迷路」看**连续**多久认不出，不看累计多少帧：
        #   每处理一帧就喂一次时钟（进入 unknown 打点 / 命中任一已知页清点）。
        #   ★#76 的结论并入原语★：``in_fight`` 期间不给 unknown 打点 —— 真战斗里技能演出 /
        #   换波过渡帧天然反复认不出（真机 2026-10-17 单人 run：``wuchong_battle`` 与 ``unknown``
        #   每 2~3 秒来回，一次换波过渡连出 8 帧，见 ``docs/spec/wuchong-spec.md`` D8）。
        #   ★离开本场后照旧计时★（``in_fight`` 由下面的 :data:`_FIGHT_LEAVE_STATES` 分支落回 False）。
        #   位置必须在**去重守卫之后、状态分支之前** —— 分支里的 early return 不能漏掉
        #   「离开 unknown 要清点」这一半（否则钟会一直跑到收工）。
        _SESSION["lost"].observe(state, now, in_fight=bool(_SESSION["in_fight"]))
        if state == WUCHONG_RECRUIT_DIALOG:
            _SESSION["recruit_started"] = True
        # ★coop-fix2★：共斗房停留时钟：进入房间序列起算；只在【真正离开】时清零。
        #   loading / unknown 等过渡帧保持不动（#47 同口径，防过渡帧把时钟清零）。
        if state in ROOM_LEAVE_STATES:
            _SESSION["room_first_ts"] = 0.0
        elif state in ROOM_SEQUENCE_STATES and not _SESSION["room_first_ts"]:
            _SESSION["room_first_ts"] = now
        # ★coop-fix2 P0★：进过共斗房就**永久**置真（粘性，不受 ROOM_LEAVE_STATES 清零）——
        #   多人模式据此只认「进过房」的编队页，拒绝从 stale 单人编队页开战。
        if state == WUCHONG_ROOM:
            _SESSION["room_seen"] = True
        # ★#71★：战斗页也算「有进展」——真机战报同屏出现过 `时间 28:03`，而
        #   ``no_progress_sec=900`` 会把 15 分钟的战斗判成「无进展」→ 被既有收工兜底掐死
        #   （与 spec D「长战斗不设强判」一致：长战斗是正常等待，不是异常）。
        if state in (WUCHONG_SETTLE, WUCHONG_TEAM, WUCHONG_BATTLE):
            _SESSION["last_progress_ts"] = now
        # ★#86★ 用户可见：本场打完（每次战斗只报一次，靠 settle_said 闩锁）。
        settled = False
        if state == WUCHONG_SETTLE and not _SESSION["settle_said"]:
            _SESSION["settle_said"] = True
            settled = True
            done = int(_SESSION["fights_done"])
            target = int(_SESSION.get("target_fights") or 0)
            _say(f"五重决战：第 {done}{f'/{target}' if target else ''} 次 完成")
        # ★#71★：**跃变进入战斗** → 复位「本场已尝试关自动」闩锁（每场战斗只关一次自动；
        #   持续帧不重复复位，避免把已在战斗中途的闩锁反复抹掉）。
        if changed and state == WUCHONG_BATTLE:
            _SESSION["battle_auto_off_tried"] = False
        # ★本票「打几次」★ ★#74 修正（规格 B2/D2）★ ★2026-10-16 运维裁决（episode 闩锁）★：
        #   计数点 = **战斗 HUD 首次出现**（进本场战斗），+1 并置 ``in_fight`` 闩锁。
        #   ★真机证据★（设备A，2026-10-16 诊断跑，1s 逐帧）：同一场真战斗内部 HUD 每 2~3 秒
        #   在 ``wuchong_battle`` 与 ``unknown`` 之间闪回；旧条件 ``changed and state == battle``
        #   每次闪回都再计一场 → 一次真战斗被计成 fight/1..4、25 秒「已打够 4 次」收工（零场打完）。
        #   闩锁 ``in_fight`` 一置真就**不再**重复计 —— ``unknown``/``loading`` 的闪烁**不清**它
        #   （清它只在 :data:`_FIGHT_LEAVE_STATES` = 真正离开本场）。
        #   ★续关不算新的一场★：本场出现过 GAMEOVER 续关屏（``battle_had_continue``）时，
        #   续关后回到战斗**不再** +1（与闩锁叠加；两者都不因过渡帧乱动）。
        if state == WUCHONG_BATTLE and not _SESSION["in_fight"] and not _SESSION["battle_had_continue"]:
            _SESSION["in_fight"] = True
            count = True
        # 真正离开本场（结算/编队/房间/模式…）→ 清「本场已续关」与「战斗 episode」闩锁，
        # 下一场重新计数。★刻意不含 loading / unknown / wuchong_battle★（HUD 闪烁/续关过渡帧
        # 不得清标记 —— 这正是本次虚计的根因）。
        if state in _FIGHT_LEAVE_STATES:
            _SESSION["battle_had_continue"] = False
            _SESSION["in_fight"] = False
    if count:
        _count_fight()


# ---------------------------------------------------------------------------
# ★跨模式「自动」规则★ —— 只有五重决战允许手动
# ---------------------------------------------------------------------------
def manual_allowed(scene: str) -> bool:
    """该场景是否允许手动（= 允许把自动关掉）。**只有五重决战**。"""
    return scene in MANUAL_ALLOWED_SCENES


def effective_auto_state(scene: str, want_on: bool) -> bool:
    """夹到合法值：非五重场景一律 True（自动必开）。与 scene.wuchong 同口径。"""
    return bool(want_on) if manual_allowed(scene) else True


# ---------------------------------------------------------------------------
# 开关几何量 / 判据（橙色占比）
# ---------------------------------------------------------------------------
def _orange_ratio(image, probe) -> float | None:
    """probe=(x0,y0,x1,y1) 内的橙色像素占比；**只用 numpy（随包内置），不依赖 PIL**。

    ★#63/#56 真机修复·通道序★：MAA 的 screencap 原生 ndarray 是 **BGR**（真机实证：
    同一帧 auto=开 时 `Image.fromarray(ndarray)` 直接读 → 0.0，`ndarray[:,:,::-1]` → 0.6317；
    保存成 PNG 的 RGB 也读 0.6317）。旧实现把 ndarray 当 RGB，橙色判据里 `r-b>80` 因红蓝
    互换恒为假 → **开关永远读成「关」**。

    ★真机 P0（本票）★：旧实现还 `from PIL import Image` —— 随包内置便携 Python
    （``install/python``）**没有 Pillow** → 必抛 ImportError → 恒返回 None → 编队页/房间页
    「自动」开关读不出/关不掉（真机 ``auto_switch_state`` 报 ``state_unknown``）。
    唯一真源已收敛到 :mod:`auto_switch_impl` 的 numpy-only 实现（本函数直接委托，杜绝漂移）。
    """
    return auto_switch._orange_ratio(image, probe)


def switch_on(image, probes, on_ratio=AUTO_ON_RATIO):
    """按数据里的**多个 pattern** 判断开关是否「开」；全测不出返回 None。

    （「自动」按钮自二批起一律**定位**，不走这里；本函数只服务还有固定几何的「自动续战」。）
    """
    for probe in probes or ():
        ratio = _orange_ratio(image, probe)
        if ratio is None:
            continue
        return ratio > on_ratio
    return None


def switch_geometry(which: str):
    """which -> (probes, toggles)；未登记的 which 报 KeyError（绝不静默）。

    ★二批★：只有「自动续战」(``cont``) 还有固定几何；「自动」按钮一律**定位**
    （见 :mod:`auto_switch_impl`），传 ``auto``/``pause_auto`` 一律报错 —— 绝不静默用一个
    写死的坐标去点「自动」（运维裁决②：「不得假定固定坐标」）。
    """
    if which == "cont" and hasattr(CFG, "WUCHONG_SWITCHES"):
        sw = CFG.WUCHONG_SWITCHES
        return tuple(sw.cont_probes), tuple(sw.cont_toggles)
    raise KeyError(
        f"开关 which={which!r} 没有固定几何（合法：cont）。「自动」按钮必须【定位】"
        "（auto_switch_impl.locate_switch），绝不写死坐标（运维裁决②）"
    )


# ---------------------------------------------------------------------------
# 自定义识别
# ---------------------------------------------------------------------------
class WuchongRenavRecognition(CustomRecognition):
    """「返回房间时房间已解散 → 重新导航」的有界收口：连续失败 >= limit → 收工。

    ``disconnected``/``failed`` 参数由调用方（或连续观察到房间消失）置真；本类只维护计数。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        limit = int(param.get("limit") or 3)
        failed = bool(param.get("failed"))
        with _LOCK:
            if failed:
                _SESSION["renav_count"] += 1
                n = _SESSION["renav_count"]
            else:
                _SESSION["renav_count"] = 0
                n = 0
        if n >= limit:
            _log(f"[wuchong] 连续 {n} 次重新导航仍未回到房间 → 收工")
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"renav_giveup": True, "count": n})
        return CustomRecognition.AnalyzeResult(box=None, detail={"renav_giveup": False, "count": n})


class WuchongStateRecognition(CustomRecognition):
    """把当前画面分类成五重状态；命中请求的 state 时返回 hit。

    参数（custom_recognition_param）：
        state        : 期望画面名；留空=任意命中。
        ocr_entry    : 截图用 OCR 节点，默认 OcrTask。
        relogin_text : 追加的换日重进整句候选。
        recruit_state: 房间序细判据（not_started / started）——只在房间按「未招募 / 已招募」过滤。
        room_seen    : 布尔；要求「本轮任务是否进过共斗房」等于该值（多人模式区分 stale 编队页用）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        want = (param.get("state") or "").strip()
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        relogin_text = param.get("relogin_text")
        phrases = [str(relogin_text)] if relogin_text else []

        items = _ocr(context, argv.image, ocr_entry)
        _sync_task(getattr(argv.task_detail, "task_id", None))
        state, info = classify(items, relogin_phrases=phrases)
        _observe(state, info, items)

        if state == WUCHONG_LEVEL_REQUIRED:
            _log(
                "[wuchong] 检测到『需要130级』限制：玩家等级达到130后，解锁幻想连战与深渊连战 → "
                "本账号无法进入五重决战，任务停止（StopTask）"
            )
        # ★coop-fix2★ 招募细判据：房间序（room）可再按「未进行招募 / 已开始招募」过滤 ——
        #   让「招募」节点只在**确实还没招募**时命中（已开始招募时不再重开弹窗，安心等人齐）。
        recruit_state = (param.get("recruit_state") or "any").strip().lower()
        if recruit_state in ("not_started", "started") and state == WUCHONG_ROOM:
            recruited = bool(info.get("recruited"))
            if (recruit_state == "not_started" and recruited) or (
                recruit_state == "started" and not recruited
            ):
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={"want": want, "state": state, "recruit_state": recruit_state, **info}
                )
        # ★coop-fix2 P0★ room_seen 过滤器：把「本轮任务是否进过共斗房」也作为判据。
        #   多人模式下用它分开**stale 单人编队页**（room_seen=False -> 走 WuchongStaleTeam 返回重选）
        #   与**人齐后的编队页**（room_seen=True -> 允许 WuchongTeamChallenge 点「挑战」开战）。
        room_seen_filter = param.get("room_seen")
        if room_seen_filter is not None:
            with _LOCK:
                seen = bool(_SESSION.get("room_seen"))
            if seen != bool(room_seen_filter):
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={"want": want, "state": state, "room_seen": seen, **info}
                )
        if want and state != want:
            return CustomRecognition.AnalyzeResult(box=None, detail={"want": want, "state": state, **info})
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"state": state, **info})


class WuchongSwitchStateRecognition(CustomRecognition):
    """检测某开关当前状态（编队页/房间页「自动」/「自动续战」）。

    ★二批★：「自动」按钮一律**定位**（模板优先 / OCR 整串兜底）—— 不同页面位置不同
    （编队页左下 / 共斗房间页右上），绝不写死坐标。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        which = (param.get("which") or "auto").strip()
        want = param.get("want")  # True/False/None
        label = auto_switch.AUTO_LABEL if which == "auto" else auto_switch.CONT_LABEL
        img = argv.image if argv.image is not None else _grab(context)
        items = ocr_all(context, img)
        tbox = auto_switch.template_box(context, img, label)
        box = auto_switch.locate_switch_label(items, label, tbox)
        on = None if box is None else auto_switch.read_switch_state(img, label, box)
        detail = {"which": which, "on": on, "box": box,
                  "source": "template" if tbox is not None else ("ocr" if box else None)}
        if on is None:
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)
        if want is None or bool(on) == bool(want):
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)
        return CustomRecognition.AnalyzeResult(box=None, detail=detail)


class WuchongGiveUpRecognition(CustomRecognition):
    """兜底出口：连续认不出画面（迷路）/ 长时间无进展 / 显式总时长 → 收工（绝不空转）。"""

    def analyze(self, context, argv):
        param = read_param(argv)
        max_task_sec = float(param.get("max_task_sec") or 0)
        # ★ADR 0005★ 迷路闸门改用**连续秒数**（旧的帧数参数已删除）。
        #   兼容：override 里还留着旧帧数参数时**忽略并警告一次**，绝不静默恢复计数。
        core.warn_stale_frame_limit(LEDGER_SCOPE, "[wuchong]", param)
        lost_sec = float(param.get("lost_sec") or LOST_SEC)
        no_progress_sec = float(param.get("no_progress_sec") or DEFAULT_NO_PROGRESS_SEC)
        room_wait_sec = float(param.get("room_wait_sec") or ROOM_WAIT_SEC)
        # ★本票「打几次」★：目标场次（<=0 = 不限制，保持旧行为；GUI 选项默认 1）。
        target_fights = int(param.get(TARGET_FIGHTS_FIELD) or TARGET_FIGHTS_DEFAULT)

        items = _ocr(context, argv.image, param.get("ocr_entry") or "OcrTask")
        _sync_task(getattr(argv.task_detail, "task_id", None))
        state, info = classify(items)
        _observe(state, info, items)
        # ★#114★ 断连文案（F2032/A4050/暂时无法连接）：与重试/重启识别器**同一份判据**；
        #   这里只用它读「重启次数是否已用尽」，不做点击（点击由 pipeline 的 wuchong_net 节点）。
        net_kind = net_disconnect_kind(items)

        now = time.monotonic()
        with _LOCK:
            _SESSION["target_fights"] = target_fights
            said_target = bool(_SESSION.get("said_target"))
            _SESSION["said_target"] = True
            start = _SESSION["start_ts"] or now
            last = _SESSION["last_progress_ts"] or now
            # ★ADR 0005★ 判定与收工原因共用**同一个**连续秒数快照（避免两次取值说两句话）。
            lost = _SESSION["lost"]
            lost_seconds = lost.seconds_lost(now)
            last_known = lost.last_known
            room_first = _SESSION["room_first_ts"]
            fights_done = _SESSION["fights_done"]
            zero_tap = _SESSION["zero_tap_yield_streak"]
            # ★#76★：本场战斗 episode 是否还在进行（进战斗置真，结算/被推出/回主城才落回假）。
            in_fight = bool(_SESSION["in_fight"])

        room_sec = (now - room_first) if room_first else 0.0
        # ★#86★ 门票（今天剩余次数）用尽 → 带原因收工。真机 OCR：模式页底部 `今天剩余次数x 3`。
        #   ★绝不靠「点一下挑战再读弹窗」★ —— 点一次就白烧一张票；这里每页都读一眼。
        remain = _remaining_plays(items)
        with _LOCK:
            if remain is not None:
                _SESSION["remaining_plays"] = remain
            streak = int(_SESSION["unknown_streak"]) if state == "unknown" else 0
            if state == "unknown":
                _SESSION["unknown_streak"] = streak + 1
            else:
                _SESSION["unknown_streak"] = 0
        # ★#86★ 用户可见：任务开始时报一次「要打几次」（0 = 不限）。
        if not said_target:
            _say(f"五重决战：要打 {target_fights} 次" if target_fights else "五重决战：不限次数（打到异常为止）")
        # ★2026-10-19 收尾★：打够次数后**先把本场结算点完再收工**（见 :func:`finish_settle_wait`）。
        #   `finish_settle_ts` 跨帧保持；落到结算页以外（主城/编队页/…）立即按既有理由收工。
        gameover = is_gameover_page(items)
        reached = fight_target_reached(target_fights, fights_done, in_fight)
        with _LOCK:
            prev_finish_ts = float(_SESSION.get("finish_settle_ts") or 0.0)
            wait_settle, finish_ts = finish_settle_wait(
                state, gameover, reached, prev_finish_ts, now
            )
            _SESSION["finish_settle_ts"] = finish_ts
        if wait_settle and prev_finish_ts <= 0.0:
            _log(
                f"[wuchong] 已打够 {target_fights} 次 → 先等本场结算收尾"
                f"（state={state}；最长 {FINISH_SETTLE_MAX_SEC:.0f}s，落到非结算页即收工）"
            )
        elif not wait_settle and prev_finish_ts > 0.0 and reached and not gameover:
            _log(
                f"[wuchong] 结算收尾结束（已 {now - prev_finish_ts:.0f}s，state={state}）→ 按既有理由收工"
            )
        # ★#143★ 任务开始、读到「打几次」→ 进度线 start（共 N 次；0 = 不限，渲染成「已 X 次」）。
        #   ★故意放在 said_target 闩锁之外★：那个 #86 闩锁跨任务**不复位**（既有行为，本票不动），
        #   而进度线是**每任务**一条 —— 可靠性来自 ``_sync_task`` 换任务时把 ``_PROGRESS`` 置 None
        #   以及 ``Progress.start`` 自己的去重，不依赖 :data:`said_target`。
        _start_progress(target_fights)
        # ★#79★ 共斗房等待的「还活着」心跳：房里没人来时画面完全不动，运维会以为卡死
        #   （真机 19:13–19:18 静默 302s）。每 ``ROOM_BEAT_SEC`` 打一行，带已等秒数 + 招募状态；
        #   超过 ``room_wait_sec`` 仍有既有收工兜底（带原因），绝不无限空转。
        if state == WUCHONG_ROOM and room_sec >= ROOM_BEAT_SEC:
            with _LOCK:
                beat = float(_SESSION.get("room_beat_ts") or 0.0)
                due = (now - beat) >= ROOM_BEAT_SEC
                if due:
                    _SESSION["room_beat_ts"] = now
            if due:
                recruited = bool((info or {}).get("recruited"))
                _log(
                    f"[wuchong] 共斗房等待中：已等 {room_sec:.0f}s"
                    f"（{'招募中' if recruited else '未进行招募'}；"
                    f"满 {room_wait_sec:.0f}s 仍未开战才按有界收工，任务没卡）"
                )
        reason = None
        # ★#114★ 断连重启次数用尽：带原因收工（**最高优先级** —— 服务端都连不上，再做任何事都是白费）。
        #   计数由 ``WuchongNetGuardRecognition``（mode=restart）维护；本节点是**既有** StopTask 出口，
        #   ★不另造一套收工机制★。用户可见原因逐字含「客户端重启 N 次仍连不上服务器」。
        with _LOCK:
            net_restarts = int(_SESSION.get("net_restarts") or 0)
        # ★#86★：门票用尽 / 认不出的错误弹窗 —— 优先级最高（再做任何事都是白费）。
        # ★#87★：「当前不满足出战条件」更优先 —— 游戏已经明确拒绝，再点也是白点。
        no_entry = _no_entry_reason() if state == WUCHONG_NO_ENTRY else None
        if net_kind is not None and net_restarts >= NET_RESTART_LIMIT:
            reason = NET_RESTART_EXHAUSTED_REASON.format(n=net_restarts)
            _log(
                f"[wuchong] 断连 {net_kind}：已重启客户端 {net_restarts} 次仍不恢复 → {reason}"
            )
        elif no_entry:
            reason = no_entry
            _log("[wuchong] " + _no_entry_detail())
        elif remain is not None and int(remain) <= 0:
            reason = "今天剩余次数已用完（五重门票）→ 请明天再来，或换号/换关卡"
        elif streak + 1 >= UNKNOWN_MODAL_LIMIT and _has_error_hint(items):
            hint = " / ".join(x for x, _b in (items or []) if _has_error_hint([(x, _b)]))[:60]
            reason = f"连续 {streak + 1} 次认不出画面且出现错误提示（{hint}）→ 收工，绝不盲点"
        # ★#76★：★「已打够 N 次」不许在【战斗 episode 内】收工★ —— 判据是纯函数
        #   :func:`fight_target_reached`（见那里的真机证据、与规格 B2/D2 的关系）。
        # ★2026-10-19★：战斗收场还不够 —— 结算页也是「设备被留下」的坏收尾（共斗 QUEST RESULT
        #   页没有底部导航，下一个任务起不来）。还在结算（或过渡帧）时 `wait_settle=True`，
        #   本条**先不成立**，让本场景的结算节点把【继续】/【解散】点完；落到主城等页面才收工。
        elif reached and not wait_settle:
            # ★本票「打几次」★：打够次数 → 用**既有收工出口**（同一 _mark_run_done + StopTask）
            #   优雅收工，绝不另造一套（下一步由 pipeline 的 WuchongGiveUp.action=StopTask 执行）。
            reason = f"已打够 {target_fights} 次（打几次={target_fights}）"
        elif zero_tap >= ZERO_TAP_YIELD_LIMIT:
            # ★#74★：手操连续 0 点击且 manual_off（手操未生效 / 自动未真正关掉）→ 带原因收工，
            #   绝不空转（真机 run A 的 455 次空转正是缺这道有界出口）。
            reason = f"手操连续 {zero_tap} 次 0 点击且 manual_off（手操未生效）"
        elif max_task_sec > 0 and (now - start) > max_task_sec:
            reason = f"总时长超过 {max_task_sec:.0f}s"
        elif lost_seconds >= lost_sec:
            # ★ADR 0005★ 迷路 = **连续** lost_sec 秒认不出画面（不是累计帧数）；
            #   原因文案走共享 :func:`battle_loop_core.lost_reason`（三个场景同一句）。
            reason = core.lost_reason(lost_seconds, last_known)
        elif room_sec > room_wait_sec:
            # ★coop-fix2★：共斗房有界出口：停留过久仍未开战 / 人齐 → 有理由收工（绝不无限死等）。
            reason = f"共斗房停留 {room_sec:.0f}s 仍未能开战（招募未成 / 人未齐）"
        elif (now - last) > no_progress_sec:
            reason = f"{no_progress_sec:.0f}s 无进展"
        if reason:
            _mark_run_done()
            _say(f"五重决战：收工 —— {reason}")
            # ★#143★ 收工兜底出口：进度线 done 带**既有 reason 原文**（不新造文案）。
            _done_progress(reason)
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"giveup": True, "reason": reason, "state": state}
            )
        if wait_settle:
            # 还没有「已离开结算页」的证据：不命中（放行给结算节点），也不写收工标记。
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"giveup": False, "finish_settle": True, "state": state,
                        "elapsed": now - finish_ts},
            )
        return CustomRecognition.AnalyzeResult(box=None, detail={"giveup": False, "state": state})


class WuchongContinueGuardRecognition(CustomRecognition):
    """★#72★ GAMEOVER 续关的【上限闸 + 有原因收工】（五重在 GAMEOVER 屏点【续关】而非【放弃】）。

    语义（★承重★）：
        * ``target_continues = N > 0`` → **恰好允许 N 次续关**；第 **(N+1)** 个 GAMEOVER episode
          命中并收工（StopTask）。
        * ``target_continues = 0`` → **不限**（永不由此停；规格「续关无限」）。
        * 同一 episode（同一个 GAMEOVER 屏的连续多帧）**只计一次**；画面不再是 GAMEOVER 页
          （``is_gameover_page`` 为假 = 已点续关 / 已离屏）即把 ``gameover_seen`` 清零 →
          下一次 GAMEOVER 屏算新的 episode。
        * ★有界卡住等待★：同一 GAMEOVER 屏自本 episode 起存活超过 :data:`CONTINUE_STUCK_SEC`
          （默认 60s）仍未推进 → 判定「续关点击无效 / 星导石不足」→ **带原因收工**（先例
          ``ROOM_WAIT_SEC``）。否则 guard 的每 episode 去抖会让「点了没生效」时**上限永不触发**，
          节点每轮重敲续关、空转到通用 900s 兜底 —— 违反「用完即带原因收工、不空转」。
        * ★计数口径★：按**进入 GAMEOVER 屏的次数**结算（运维原话「按进去的次数结算」）。计数在
          **episode 进入时、点击之前**发生 —— 故只会**保守**（先算一次再尝试点续关；即便随后点击
          生效、屏消失，这一次也已计入本 episode），绝不漏计，绝不会比「实际点中的续关次数」少。

    参数（custom_recognition_param）：
        ocr_entry        : 截图用 OCR 节点，默认 OcrTask。
        target_continues : 续关上限（0 = 不限）；缺省 = :data:`TARGET_CONTINUES_DEFAULT`。

    ★命中 = box [0,0,0,0]（收工）；未命中 = box None（放行，由 [JumpBack]PubGameOverContinue
      去点识别的续关框中心）。绝不自己点坐标、绝不动 classify / _observe★。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        target = int(param.get(TARGET_CONTINUES_FIELD) or TARGET_CONTINUES_DEFAULT)
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        items = _ocr(context, argv.image, ocr_entry)
        _sync_task(getattr(argv.task_detail, "task_id", None))

        # 非 GAMEOVER 页：清 episode 标记与卡住时钟（已点续关 / 已离屏 → 下一次 GAMEOVER 算新 episode）。
        if not is_gameover_page(items):
            with _LOCK:
                _SESSION["gameover_seen"] = False
                _SESSION["gameover_first_ts"] = 0.0
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"continue": False, "reason": "not_gameover"}
            )

        now = time.monotonic()
        with _LOCK:
            _SESSION["target_continues"] = target
            seen = bool(_SESSION["gameover_seen"])
            _SESSION["gameover_seen"] = True
            if not seen or not _SESSION["gameover_first_ts"]:
                # 新的 GAMEOVER episode：起算卡住时钟。
                _SESSION["gameover_first_ts"] = now
            first = float(_SESSION["gameover_first_ts"])
        if not seen:
            # 新的 GAMEOVER episode：记一笔续关（连帧只算一次）。
            n = _count_continue()
        else:
            with _LOCK:
                n = int(_SESSION["continues_done"])

        stuck_sec = (now - first) if first else 0.0

        # ★上限优先（cap precedence 承重）★：用尽即用**既有**原因文本收工（不看卡住）。
        if target > 0 and n > target:
            # ★上限用尽★：带原因收工（既有 _mark_run_done + 本节点 StopTask），绝不空转。
            reason = f"续关次数用尽（已续关 {target} 次，target_continues={target}）"
            _mark_run_done()
            _log(f"[wuchong] {reason} → 带原因收工")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0],
                detail={"continue_exhausted": True, "reason": reason, "continues_done": n},
            )
        # ★有界卡住等待★：同一 GAMEOVER 屏存活超过 CONTINUE_STUCK_SEC 仍未推进 → 带原因收工。
        if stuck_sec > CONTINUE_STUCK_SEC:
            reason = f"续关屏停留 {stuck_sec:.0f}s 仍未推进（续关点击无效 / 星导石不足？）"
            _mark_run_done()
            _log(f"[wuchong] {reason} → 带原因收工")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0],
                detail={"continue_stuck": True, "reason": reason, "stuck_sec": stuck_sec,
                        "continues_done": n},
            )
        # 未到上限、也未卡住：放行（[JumpBack]PubGameOverContinue 点续关框中心）。
        return CustomRecognition.AnalyzeResult(
            box=None,
            detail={
                "continue": False,
                "under_cap": True,
                "continues_done": n,
                "target_continues": target,
                "stuck_sec": stuck_sec,
            },
        )


class WuchongNetGuardRecognition(CustomRecognition):
    """★#114★ 三种断连（F2032 / A4050 / 暂时无法连接）的**唯一识别入口** + 有界重启策略。

    为什么不是「掉线计个 N 次就收工」：真机实测（docs/spec/runner-delivery.md R1）点【重试】
    **无效**，`am force-stop` + 重新拉起客户端才能恢复；直接收工会把长跑提前打死。

    参数（custom_recognition_param）：
        mode      : ``"retry"`` = 冷却窗口内放行去点【OK】/【重新连接】；
                    ``"restart"`` = 冷却窗口外仍停在同一断连屏 → 命中重启动作。缺省 retry。
        kinds     : retry 模式下本节点负责的断连种类（缺省 = 全部三种）。
        limit     : 重启上限（缺省 :data:`NET_RESTART_LIMIT`；pipeline 显式写 3，守卫钉死）。
        ocr_entry : 截图用 OCR 节点，缺省 ``OcrTask``。

    语义（真源 ``scene.wuchong`` ②h）：
      · 断连屏第一次出现 / 种类变化 → 记 episode 起点（换 task_id 也清零）；
      · ``retry`` 只在 ``[0, SERVER_RETRY_COOLDOWN_S)`` 内命中 —— 动作侧同一把
        ``server_retry`` 时间闩保证「冷却窗口内最多点一次」；窗口外 retry 不再命中
        （★绝不每轮狂点【重试】★），任务继续走到 ``mode=restart``；
      · ``restart`` 命中一次 = 重启客户端一次（计数 +1 并复位 episode）：
        重启后若还断连，会重新走「冷却 10s → 重试一次 → 仍失败再重启」；
      · 计数达到 :data:`NET_RESTART_LIMIT` 后两种模式都 miss ⇒ 既有 ``WuchongGiveUp``
        按 :data:`NET_RESTART_EXHAUSTED_REASON` 带原因收工（绝不无限重启）；
      · 正常主城 / 战斗帧 → miss（三种文案一个都不命中），episode 复位。

    ★重启后的恢复路径不在这里实现★：``WuchongNetGuard`` 动作返回后 ``next=WuchongEntry``，
    由既有 ``[JumpBack]PubLoginContinue`` / ``[JumpBack]PubTitleStart`` / ``WuchongResumeQuest``
    接回「继续游戏 / 点击开始 / 有正在进行中的关卡」——不另造一套、不点屏幕。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        mode = str(param.get("mode") or NET_RETRY_MODE).strip().lower()
        raw_kinds = param.get("kinds")
        kinds = tuple(
            str(k) for k in (raw_kinds if isinstance(raw_kinds, (list, tuple)) else NET_DISCONNECT_KINDS)
        )
        limit = max(1, int(param.get("limit") or NET_RESTART_LIMIT))
        ocr_entry = param.get("ocr_entry") or "OcrTask"

        image = getattr(argv, "image", None)
        if image is None:
            image = _grab(context)
        items = _ocr(context, image, ocr_entry)
        task_detail = getattr(argv, "task_detail", None)
        _sync_task(getattr(task_detail, "task_id", None))

        kind = net_disconnect_kind(items)
        now = _NET_CLOCK()
        with _LOCK:
            if kind is None:
                _SESSION["net_kind"] = None
                _SESSION["net_first_ts"] = 0.0
                restarts = int(_SESSION.get("net_restarts") or 0)
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={"net": None, "kind": None, "mode": mode,
                            "restarts": restarts, "limit": limit},
                )
            new_episode = kind != _SESSION.get("net_kind")
            if new_episode:
                _SESSION["net_kind"] = kind
                _SESSION["net_first_ts"] = now
            # ★0.0 是合法时钟值（离线假时钟 t=0）★：不能用 ``first or now`` 判断 ——
            #   ``new_episode`` 分支已经把起点写好了（哪怕写的是 0.0），这里直接读。
            first = float(_SESSION["net_first_ts"])
            restarts = int(_SESSION.get("net_restarts") or 0)
            elapsed = max(0.0, now - first)

        label = NET_DISCONNECT_LABELS.get(kind, kind)
        detail = {
            "net": kind,
            "kind": kind,
            "label": label,
            "mode": mode,
            "restarts": restarts,
            "limit": limit,
            "elapsed_sec": round(elapsed, 1),
        }
        if new_episode:
            _log(
                f"[wuchong] 检测到断连 {label}（{kind}）→ 先按 "
                f"{SERVER_RETRY_COOLDOWN_S:.0f}s 冷却重试一次；仍失败才重启客户端"
            )

        # ★上限优先★：已达上限 → 两种模式都 miss，交给 WuchongGiveUp 带原因收工。
        if restarts >= limit:
            detail["net_exhausted"] = True
            detail["phase"] = "exhausted"
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)

        if mode == NET_RESTART_MODE:
            # ★冷却承重★：重启必须等满 SERVER_RETRY_COOLDOWN_S（先让 retry 点一次），
            #   绝不因为「加了重启」就绕过冷却（hooks_114 守卫 ④）。
            if elapsed < SERVER_RETRY_COOLDOWN_S:
                detail["phase"] = "retry_window"
                return CustomRecognition.AnalyzeResult(box=None, detail=detail)
            with _LOCK:
                _SESSION["net_restarts"] = restarts + 1
                # 重启后若还断连 = 新 episode：重新给一次冷却重试机会（不是直接连着重启）。
                _SESSION["net_kind"] = None
                _SESSION["net_first_ts"] = 0.0
            detail.update(phase="restart", restart=restarts + 1)
            _log(
                f"[wuchong] 断连 {label}（{kind}）冷却 {elapsed:.0f}s 仍连不上 → "
                f"重启客户端（第 {restarts + 1}/{limit} 次）"
            )
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)

        # ---- retry 模式 ----
        if kind not in kinds:
            detail["phase"] = "other_kind"
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)
        if elapsed < SERVER_RETRY_COOLDOWN_S:
            detail["phase"] = "retry"
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail=detail)
        detail["phase"] = "restart_due"
        return CustomRecognition.AnalyzeResult(box=None, detail=detail)


# ---------------------------------------------------------------------------
# ★手操战斗引擎★（场景无关的节奏逻辑，可离线驱动）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Cadence:
    """一轮手操的节奏（值来自 ``custom_action_param`` 或场景默认）。

    ★#71★：**没有** ``duration_s``（固定时长截断已删除）；``check_min_gap_ms`` 取代旧的
    ``check_every`` —— 采样按**时间**节流（循环无次数上限，只能用时间做节流）。
    ★2026-10-16 运维裁决★：**没有** ``hud_miss_limit`` —— 不再用战斗 HUD 做判据，认不出的帧
    一律**继续点**（见 :func:`page_verdict`），故没有「连续 N 次不见战斗就停手」这条。
    """

    center: tuple[int, int]
    flipper: tuple[int, int]
    dist: int
    swipe_ms: int
    flipper_gap_ms: int
    skill_gap_ms: int
    skill_every: int
    burst: int
    check_min_gap_ms: int


@dataclass(frozen=True)
class BattleHooks:
    """手操战斗的外呼 + 时钟（★全部可替换★，离线测试塞假件）。

    · ``burst_click(point, times, gap)``：一次原生连点 ``times`` 下，间隔 ``gap`` 毫秒；
    · ``swipe(begin, end, ms)``：滑动（放技能）；
    · ``verdict() -> str``：采样当前帧的页面判据（取值 = :func:`page_verdict` 的三个常量）；
    · ``manual_on() -> bool``：手操是否仍开着（自动被重新打开 → 立刻停手）；
    · ``stopping() -> bool``：框架是否请求停止任务（默认恒 False；生产接 tasker.stopping）；
    · ``sleep(sec)`` / ``now()``：时钟。
    """

    burst_click: Callable[[tuple, int, int], None]
    swipe: Callable[[tuple, tuple, int], None]
    verdict: Callable[[], str]
    manual_on: Callable[[], bool]
    sleep: Callable[[float], None]
    now: Callable[[], float]
    stopping: Callable[[], bool] = lambda: False  # noqa: E731


def page_verdict(items) -> str:
    """★纯函数★：把一帧 OCR 判成手操引擎的**三值页面判据**之一（★顺序不可换★）。

    ★运维裁决（2026-10-16）★：手操引擎**不再用战斗 HUD 做判据**（真机 HUD 会间歇性认不出 →
    点板断续 + 虚计）。判据只认**三个正面终止点**，其余一切**继续点**：

    1. :func:`is_gameover_page`（``GAMEOVER`` + ``是否续关?``）→ :data:`PAGE_OVER`（续关屏）；
    2. ``classify(items)[0] == WUCHONG_SETTLE`` → :data:`PAGE_OVER`（结算页）；
    3. ``classify(items)[0] ∈`` :data:`PAGE_LEFT_STATES`（已知非战斗页）→ :data:`PAGE_LEFT`
       （被推出战斗）；
    4. 其余（真战斗帧 ``wuchong_battle`` / ``unknown`` / ``loading`` / 弹窗）→
       :data:`PAGE_CONTINUE`（**继续点**）。

    ★为什么顺序不可换（承重）★：续关屏（GAMEOVER /「是否续关？」）**底部照样画着战斗 HUD 的
    「时间/分数」**（真机帧实证）→ 会被 :func:`classify` 判成 ``wuchong_battle``。若先判「是不是
    战斗」（旧实现第 4 条 ``is_battle_hud``）就会把续关屏当成「还在战斗」，于是在续关屏继续连点
    —— 而续关屏的「放弃 / 续关」那一行（720 y≈1043）与弹板点 (360,1067) **同一行** = 真实误点。
    故续关屏/结算页必须**最先**被接走。同理，真机战斗帧里 ``unknown`` 闪烁也归 :data:`PAGE_CONTINUE`
    （继续点），**绝不停手**。
    """
    if is_gameover_page(items):
        return PAGE_OVER
    state, _info = classify(items)
    if state == WUCHONG_SETTLE:
        return PAGE_OVER
    if state in PAGE_LEFT_STATES:
        return PAGE_LEFT
    return PAGE_CONTINUE


def _touch_progress():
    """把「有进展」时间戳刷到现在（锁内）——心跳刷新，避免长战斗被收工兜底掐死。"""
    with _LOCK:
        _SESSION["last_progress_ts"] = time.monotonic()


def run_manual_battle(hooks: BattleHooks, cadence: Cadence) -> dict:
    """★手操核心（纯节奏逻辑）★：连点弹板 + 每 ``skill_every`` 次弹板补一发技能。

    ★运维裁决（2026-10-16，逐字）★：「那我觉得不要做HUD的OCR了…你就一直点，点到要么是续关，
    要么是推出去了，要么就结算了就完事了」。本循环 accordingly：
      · **默认一直点**（弹板 + 按节奏放技能）；
      · **不再**用战斗 HUD 做判据（HUD 会间歇性认不出 → 点板断续）；认不出的帧 / 转场帧 /
        加载帧 **一律继续点**；
      · 只在**三个正面终止点**停手（见 :func:`page_verdict`）：续关屏 / 结算页 / 被推出战斗。

    ★没有任何墙上时钟上限★（#71）：``while True`` 里**没有** ``deadline`` / ``duration`` 这类
    墙钟上限。停止只由下面这些条件触发（``stopped`` 的合法取值）：

      · ``"manual_off"``  —— 手操被关（``manual_on()`` 假）：切回自动 → 立刻停手；
      · ``"battle_over"`` —— 续关屏 / 结算页（``verdict()`` = :data:`PAGE_OVER`）；
      · ``"left"``        —— **被推出战斗**（``verdict()`` = :data:`PAGE_LEFT`，任一已知非战斗页）；
      · ``"stopped"``     —— 框架请求停止任务（``stopping()`` 真）。

    ★先判据、后点击★（承重安全属性）：循环首轮即先采一帧判据（``last_check`` 初始化成
    ``t0 - check_gap``），据此决定是否开始点板 —— 被以续关屏 / 结算页 / 非战斗页 / 弹窗帧调用时
    **不会先落任何点击**（续关屏的「放弃/续关」那一行与弹板点 (360,1067) 同一行，误点即真机事故）。

    返回 transcript（taps / swipes / checks / stopped / reason），供守卫断言**参数真的被使用**：
      · ``burst`` 控制一次原生连点几下（把逐次 run_action 的开销吃掉）；
      · ``flipper_gap_ms`` 是每次弹板的间隔；
      · ``skill_every`` 按**累计点击数**触发技能（左/上/右轮换）；
      · ``skill_gap_ms`` 是技能后的间隔；
      · ``check_min_gap_ms`` 是判据采样的**时间节流**（每隔这么多毫秒采一帧页面判据；
        ★只节流采样，不构成停手条件★）。
    """
    burst = max(1, int(cadence.burst))
    gap = max(20, int(cadence.flipper_gap_ms))
    skill_every = int(cadence.skill_every)
    center = tuple(cadence.center)
    cx, cy = center
    dirs = ((cx - int(cadence.dist), cy), (cx, cy - int(cadence.dist)), (cx + int(cadence.dist), cy))
    check_gap = max(0.0, int(cadence.check_min_gap_ms) / 1000.0)
    heartbeat = max(1.0, BATTLE_HEARTBEAT_MS / 1000.0)

    t0 = hooks.now()
    # ★#71 修正★：``last_check = t0 - check_gap`` → 循环**首轮先采样一次**再决定是否落第一串
    #   点击（否则「被以续关屏/结算页/非战斗页帧调用」时会先点 burst 下 —— 续关屏那一行与弹板点
    #   同一行 = 真实误点）。见下方循环里「先判据、后点击」。
    last_check = t0 - check_gap
    last_beat = t0
    taps = 0
    swipes: list = []
    checks = 0
    skill_i = 0
    next_skill_at = skill_every if skill_every > 0 else 0
    stopped = None
    reason = ""

    while True:
        # ★可停手★：框架对阻塞中的自定义动作**不抢占**（need_to_stop 只在动作前后检查），
        #   故每轮开头显式问一次 stopping()，让「停止任务」尽快生效。
        if hooks.stopping():
            stopped = "stopped"
            reason = "框架请求停止任务"
            break
        if not hooks.manual_on():
            stopped = "manual_off"
            reason = "手操已关（切回自动）→ 立刻停手"
            break

        # ★先判据、后点击★：按节流（含首轮）先采一帧页面判据；只有**三个正面终止点**才停手，
        #   其余（含真战斗帧 / unknown / loading）**继续点** —— 停手时**不落任何点击**就交还
        #   （续关屏的「放弃/续关」与弹板点同一行）。
        now = hooks.now()
        if now - last_check >= check_gap:
            last_check = now
            checks += 1
            v = hooks.verdict()
            if v == PAGE_OVER:
                stopped = "battle_over"
                reason = "续关屏 / 结算页"
                break
            if v == PAGE_LEFT:
                stopped = "left"
                reason = "被推出战斗（已知非战斗页）"
                break
            # PAGE_CONTINUE（真战斗帧 / 认不出 / 转场加载）→ 落到下面继续点。

        hooks.burst_click(tuple(cadence.flipper), burst, gap)
        taps += burst
        if next_skill_at and taps >= next_skill_at:
            next_skill_at += skill_every
            end = dirs[skill_i % 3]
            hooks.swipe(center, end, int(cadence.swipe_ms))
            swipes.append((center, end))
            skill_i += 1
            hooks.sleep(max(0.0, int(cadence.skill_gap_ms) / 1000.0))

        now = hooks.now()
        if now - last_beat >= heartbeat:
            last_beat = now
            # ★ADR 0005 / #76★：心跳顺带上报 ``seconds_lost`` —— 战斗 episode 内它**应当恒为 0**
            #   （判据 = ``LostClock.observe(in_fight=...)`` 不打点）。这是「长战斗不会被『未知
            #   画面累计 N 次』收工兜底掐死」在**真机日志**上的可观测证据（离线牙齿 = 守卫
            #   ``wuchong-unknown-not-counted-in-fight``）。
            with _LOCK:
                lost_now = _SESSION["lost"].seconds_lost(now)
            _log(f"[{BATTLE_TAG}] 心跳 t=+{int(now - t0)}s taps={taps} 仍在战斗 "
                  f"lost={lost_now:.0f}s（战斗内不计）")
            _touch_progress()
    return {"taps": taps, "swipes": swipes, "checks": checks, "stopped": stopped, "reason": reason}


class WuchongBattleAction(CustomAction):
    """★手操战斗★：一次调用**从进战斗持续连点弹板 + 轮换放技能，直到续关屏 / 结算页 / 被推出战斗才交还**。

    ★#71★：本动作**没有固定时长上限**（旧 ``duration_s`` 秒截断已删除）。★2026-10-16 运维裁决★：
    停止只由 :func:`run_manual_battle` 的正面条件触发（续关屏 / 结算页 / 被推出战斗 / 手操被关 /
    框架停止任务）—— **不再**用战斗 HUD 判据，认不出的帧一律继续点。

    参数（custom_action_param；缺省值来自 :data:`BATTLE_DEFAULTS` = ``scene.wuchong.BATTLE_PARAMS``）：
        manual / scene : 是否手操 / 场景 id（跨模式规则：非五重恒自动）。
        center / flipper / dist / swipe_ms : 手操几何量（场景标定）。
        弹板间隔 / 技能间隔 / 每几次弹板放技能 / 连点批量 : 见 BATTLE_PARAMS。
        check_min_gap_ms : 判据采样的**时间节流**（只节流，不构成停手条件）。

    ★自动模式（manual=False）时本动作**不点任何东西**★：保证「其他所有战斗都是自动」，
    且「要能取消手打、要开自动」。
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        scene = str(param.get("scene") or "wuchong")
        with _LOCK:
            session_manual = _SESSION["manual"]
        manual = bool(param.get(BATTLE_MANUAL_FIELD, session_manual))

        # ★跨模式硬规则★：非五重场景绝不手操（自动必开）。
        if manual and not manual_allowed(scene):
            _log(f"[wuchong_battle] 场景 {scene!r} 不允许手动（其他战斗一律自动）→ 自动模式")
            manual = False

        if not manual:
            # ★带原因停下★：手操引擎关（是否手操=自动 / 非五重场景）→ 不点任何东西。
            # 结点本身在 raw 默认与「自动」case 都是 __NONE__，因此不会被重选空转。
            _log(
                "[wuchong_battle] 手操引擎关（manual=off）→ 不点任何东西："
                f"scene={scene!r}，结点应由选项关闭（raw 默认 __NONE__）；不使用识别空框"
            )
            return True

        # ★#74★ ★承重★：选项参数就是手操态的【权威源】—— 动作自己决定手操，就**必须先**把
        #   它落进会话，绝不能让 `_manual_on()` 读到旧值而自相矛盾。
        #   真机证据（run A，2026-10-16）：自动开关**本来就是关的**（正是手操想要的状态）→
        #   WuchongTeamAutoSet / WuchongBattleAutoOff 两个 `wuchong_switch` 节点都以「自动=开」
        #   为前提门控、都不触发 → `_SESSION["manual"]` 无人写、恒 False → run_manual_battle
        #   每轮开头 `manual_on()` 立刻假 → `stopped=manual_off`、0 点击，连续 455 次，随后以
        #   被旧帧数闸门（累计 121 帧）误杀。回填后「动作决定手操」与「引擎读到的会话态」一致。
        #   （切回自动仍有效：WuchongSwitchAction 观察到自动=开时照旧写 `_SESSION["manual"]=False`
        #     —— 那就是「降级为自动」，是 #74 之后唯一【关手操】的写者。）
        with _LOCK:
            _SESSION["manual"] = True

        # ★只用手操几何（场景真源），绝不用识别空框★（empty rect 真机缺陷）。
        center, flipper = battle_geometry()
        cadence = _cadence_from_param(param)
        _log(
            f"info:[{BATTLE_TAG}] 手操开始（直到续关屏 / 结算页 / 被推出战斗才交还；无固定时长上限）"
            f"（几何来自场景 center720={center} flipper720={flipper}；"
            f"dist={cadence.dist} 弹板间隔{cadence.flipper_gap_ms}ms "
            f"每{cadence.skill_every}次弹板补一发技能 批量{cadence.burst} "
            f"采样间隔{cadence.check_min_gap_ms}ms；认不出的帧继续点）"
        )
        result = _run_battle_live(context, cadence)
        stopped = result.get("stopped")
        taps = int(result.get("taps") or 0)
        with _LOCK:
            _SESSION["battle_taps"] += taps
            # ★#74★：维护「连续 0 点击且 manual_off」连击（防御性可见失败）：有点击 / 结算收场
            #   = 有进展 → 清零；只有「0 点击 + manual_off」才累加（被推出去 left 是正常交还，
            #   不累加也不冤枉）。
            if taps > 0 or stopped == "battle_over":
                _SESSION["zero_tap_yield_streak"] = 0
            elif stopped == "manual_off":
                _SESSION["zero_tap_yield_streak"] += 1
            else:
                _SESSION["zero_tap_yield_streak"] = 0
            streak = _SESSION["zero_tap_yield_streak"]
        if streak >= ZERO_TAP_YIELD_LIMIT:
            _log(
                f"[wuchong] 手操连续 {streak} 次 0 点击且 stopped=manual_off（手操未真正生效 / "
                f"自动未关掉）→ 交由 WuchongGiveUp 带原因收工，绝不空转"
            )
        _log(f"info:[{BATTLE_TAG}] 手操连点结束：共点弹板 {result.get('taps')} 次"
              f"（技能 {len(result.get('swipes') or [])} 发，stopped={result.get('stopped')}，"
              f"reason={result.get('reason')}）")
        return True


def battle_geometry() -> tuple[tuple[int, int], tuple[int, int]]:
    """手操战斗的**几何真源**（场景 ``WUCHONG_BATTLE``）：(技能滑动中心, 弹板点)。

    动作只用它定位 —— 绝不用识别的空框（真机 ``rect=[0,0,0,0]`` 的 WRN 就是这条）。
    """
    return (tuple(BATTLE_CENTER), tuple(BATTLE_FLIPPER))


def _cadence_from_param(param: Mapping) -> Cadence:
    """把 custom_action_param 解析成 Cadence（缺项取场景默认；坐标必须来自场景）。"""

    def pair(key, default):
        v = param.get(key)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            try:
                return (int(v[0]), int(v[1]))
            except (TypeError, ValueError):
                return default
        return default

    def num(key, default):
        try:
            return int(param.get(key, default))
        except (TypeError, ValueError):
            return default

    return Cadence(
        center=pair("center", BATTLE_CENTER),
        flipper=pair("flipper", BATTLE_FLIPPER),
        dist=num("dist", BATTLE_SWIPE_DIST),
        swipe_ms=num("swipe_ms", BATTLE_SWIPE_MS),
        flipper_gap_ms=num("flipper_gap_ms", BATTLE_DEFAULTS["flipper_gap_ms"]),
        skill_gap_ms=num("skill_gap_ms", BATTLE_DEFAULTS["skill_gap_ms"]),
        skill_every=num("skill_every", BATTLE_DEFAULTS["skill_every"]),
        burst=num("burst", BATTLE_DEFAULTS["burst"]),
        # ★#71★：时间驱动的采样节流（取代旧的按点击计数 check_every）；有默认值读取，
        #   另一条 lane 未落地 scene.wuchong 时也不会炸。
        # ★2026-10-16 运维裁决★：不再有 hud_miss_limit（HUD 判据已删）。
        check_min_gap_ms=num("check_min_gap_ms", CHECK_MIN_GAP_MS),
    )


# ---------------------------------------------------------------------------
# 生产副作用：原生连点 / 滑动 / 战斗页判据（可被测试替换）
# ---------------------------------------------------------------------------
def _run_action(context, node, **kwargs):
    return context.run_action(node, **kwargs)


def burst_click(context, point, times, gap_ms):
    """一次 run_action 让框架原生连点 ``times`` 下（自我循环 + max_hit 封顶）。"""
    override = {
        "WuchongClick": {
            "action": {"type": "Click", "param": {"target": [int(point[0]), int(point[1])]}},
            "post_delay": int(gap_ms),
            "next": ["WuchongClick"],
            "max_hit": int(times),
        }
    }
    try:
        _run_action(context, "WuchongClick", pipeline_override=override)
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong_battle] 原生连点失败 point={point} times={times}：{exc!r}")
        return False


def swipe(context, begin, end, duration_ms):
    override = {
        "WuchongSwipe": {
            "action": {
                "type": "Swipe",
                "param": {
                    "begin": [int(begin[0]), int(begin[1])],
                    "end": [int(end[0]), int(end[1])],
                    "duration": int(duration_ms),
                },
            }
        }
    }
    try:
        _run_action(context, "WuchongSwipe", pipeline_override=override)
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"[wuchong_battle] 滑动失败 {begin}->{end}：{exc!r}")
        return False


def _verdict_live(context) -> str:
    """生产侧判据采样：**每次都用新帧**（``run_recognition`` 吃传入的 image，传旧帧会一直重判
    同一帧）。``_ocr`` 的 1.5s 缓存键是**图像特征**，拿着新帧天然安全；再顺带 ``_observe``
    让「进入战斗」的状态跃变被记账（``_observe`` 自带 1.2s 去重，安全）。
    """
    items = _ocr(context, _grab(context))
    state, _info = classify(items)
    _observe(state, {}, items)
    return page_verdict(items)


def _run_battle_live(context, cadence: Cadence) -> dict:
    """把核心循环接到真实副作用上。"""

    def _manual_on() -> bool:
        with _LOCK:
            return bool(_SESSION["manual"])

    def _stopping() -> bool:
        # ★可停手★：框架对阻塞中的自定义动作不抢占（need_to_stop 只在动作前后检查），
        #   故这里显式把「任务是否在停下」暴露给循环（生产 = tasker.stopping）。
        st = getattr(context.tasker, "stopping", False)
        return bool(st() if callable(st) else st)

    hooks = BattleHooks(
        burst_click=lambda point, times, gap: burst_click(context, point, times, gap),
        swipe=lambda begin, end, ms: swipe(context, begin, end, ms),
        verdict=lambda: _verdict_live(context),
        manual_on=_manual_on,
        sleep=time.sleep,
        now=time.monotonic,
        stopping=_stopping,
    )
    return run_manual_battle(hooks, cadence)


# ---------------------------------------------------------------------------
# 开关动作（自动 / 自动续战）+ ★跨模式规则★
# ★二批★：「自动」按钮一律【定位】（模板/OCR）+ 读状态 + 点识别框中心；战斗内不再切自动。
# ---------------------------------------------------------------------------
class WuchongSwitchAction(CustomAction):
    """把某个开关设成期望状态（★定位 → 读状态 → 需要才点**识别框中心** → 复查★）。

    参数（custom_action_param）：
        which      : auto / cont（「自动」/「自动续战」）。
        on         : 期望状态（True=开）。★非五重场景一律夹回 True★（跨模式硬规则）。
        scene      : 场景 id（默认 wuchong）；只有 wuchong 允许 on=False。
        click_action: 原生点击节点名（默认 PubClick）。
        on_unknown : 状态判不出时（"click" = 仍点识别框中心并复查；否则不动）。

    ★二批（运维裁决②）★：
      · 「自动」按钮**不写死坐标** —— 一律定位（模板优先 / OCR 整串 ``^自动$`` 兜底），
        读它开/关，再点**识别框中心**；不同页面（编队页左下 / 房间页右上）照样命中。
      · **战斗内不再切自动** —— 原「暂停屏自动」(``pause_auto``) 与 open/close_pause 已删除。
    ★ruling ③★：动作开头先处理「自动续战功能」确认框（出现就点『取消』，绝不打开功能）。
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        which = str(param.get("which") or "auto")
        scene = str(param.get("scene") or "wuchong")
        click_action = str(param.get("click_action") or "PubClick")
        want_raw = bool(param.get("on", True))
        want = effective_auto_state(scene, want_raw)
        if want != want_raw:
            _log(
                f"[wuchong_switch] 场景 {scene!r} 不允许关自动（其他战斗一律自动）→ "
                f"强制 on=True（请求 {want_raw}）"
            )
        if which == "auto":
            with _LOCK:
                # ★降级为自动★（观察到自动=开 ⇒ 关手操）：这是 #74 之后唯一【关手操】的写者
                #   （手操的【开】由 WuchongBattleAction 依选项参数回填，见其承重注释）。
                _SESSION["manual"] = not want
        label = auto_switch.AUTO_LABEL if which == "auto" else auto_switch.CONT_LABEL

        img = _grab(context)
        # ruling ③：先处理「自动续战功能」确认框 —— 出现就按『取消』，绝不打开功能。
        auto_switch.dismiss_cont_dialog(context, img, click_action=click_action)
        items = ocr_all(context, img)
        # ★coop-fix2 P0★：画面是弹窗（如招募方式弹窗）时**拒绝点击** —— 开关的识别框中心会落在
        #   弹窗背板上，点它 = 点错东西（真机：招募方式弹窗被「自动」开关的定点点击点掉 → 招募丢失）。
        st, _st_info = classify(items)
        if st in MODAL_BLOCK_STATES:
            _log(
                f"[wuchong_switch] 画面={st}（弹窗在屏）→ 拒绝点击（点位会落在弹窗背板 = 点错东西）"
            )
            return True
        tbox = auto_switch.template_box(context, img, label)
        box = auto_switch.locate_switch_label(items, label, tbox)
        source = "template" if tbox is not None else ("ocr" if box else None)
        _log(f"[wuchong_switch] which={which} scene={scene} 期望={want} 定位={box} source={source}")
        if box is None:
            # 定位不到（模板 / OCR 都没命中）→ 不动（绝不猜坐标、绝不盲点）。
            # ★三批：改为**可见失败**★（旧形态静默 return True；现打印原因 + 返回 False）。
            _log(f"[wuchong_switch][FAIL] 定位不到『{label}』开关（模板/OCR 均未命中）→ 不执行")
            return False
        cx, cy = auto_switch.click_point(box)
        on = auto_switch.read_switch_state(img, label, box)
        if on is None:
            if str(param.get("on_unknown") or "") == "click":
                auto_switch._click_box(context, click_action, cx, cy)
                time.sleep(0.6)
                again = auto_switch.read_switch_state(_grab(context), label, box)
                _log(f"[wuchong_switch] 判不出→点识别框中心 ({cx},{cy}) 后复查 on={again}")
                return True
            _log(f"[wuchong_switch][FAIL] 状态判不出且未允许盲点 → 不执行；box={box}")
            return False
        if bool(on) == bool(want):
            _log(f"[wuchong_switch] 已是期望状态（{on}）→ 不动")
            return True
        auto_switch._click_box(context, click_action, cx, cy)
        time.sleep(0.6)
        again = auto_switch.read_switch_state(_grab(context), label, box)
        if again is not None and bool(again) != bool(want):
            _log(f"[wuchong_switch][FAIL] 点后仍未达期望（{again}）（已点识别框中心 ({cx},{cy})）")
            return False
        _log(f"[wuchong_switch] 已设 {which} -> {want}（复查 {again}）")
        return True


# ---------------------------------------------------------------------------
# 导航 / 按钮点击动作（OCR/模板门控，绝不点错目标）
# ---------------------------------------------------------------------------
def locate_button(items, patterns, roi=None, prefer=None, y_max=None):
    """按 OCR 文本定位按钮；返回 ``(text, cx, cy)`` 或 None。

    ``y_max``：同名歧义（页签 vs 列表行）时只认**上半区**。
    """
    patterns = list(patterns or [])
    target = _pick(items, patterns, roi=roi, prefer=prefer)
    if target is not None and y_max is not None and target[2] >= float(y_max):
        target = None
        for t, b in items or []:
            if not b or len(b) != 4 or (b[1] + b[3] / 2.0) >= float(y_max):
                continue
            if any(re.search(p, t or "") for p in patterns):
                cx, cy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
                if roi and not (roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]):
                    continue
                target = (t, cx, cy)
                break
    return target


class WuchongActAction(CustomAction):
    """按 OCR 到的【按钮文字本身】点击，点完校验画面是否推进到期望状态。

    参数（custom_action_param）：
        what    : 按钮文字正则列表（按顺序取第一个命中的按钮）。
        what_next : 可选：主目标找不到时的**兜底按钮**（结算页「继续」点完后换「OK / 返回房间」，
                  让结算多段少走一跳；故意**不含「解散」**——那会把共斗房关掉）。
        roi     : 可选 (x0,y0,x1,y1) 限定按钮中心范围（720）。
        prefer  : 可选 "top"/"bottom"。
        y_max   : 可选：只取中心 y < y_max 的命中（用于「降临讨伐」页签 vs 列表行同名歧义）。
        expect  : 点击后期望出现的状态列表；为空表示画面变了就算成功。
                  ★``expect`` 里不许放 ``loading``★：过渡帧不是「已到达」（真机：灰「挑战」点了会闪
                  一下 loading 又回房 → 旧实现据此「校验通过」白等一整轮）。守卫 hooks_78 把守。
        wait_ms : 点击后等待毫秒，默认 **700**（#78：原 1600 是纯等；页面没推进就交给下一轮）。
        finish_skip : 可选。★收尾（打够次数后）★要**剔除**的按钮正则 —— 例如单人的结算屏第一颗是
                  【再次挑战】，收尾时点它就是新开一局（把「打几次」无限推迟）。
        finish_prefer : 可选。★收尾时优先点击★的按钮正则 —— 例如共斗结算第三屏的【解散】
                  （一步回主城；正常运行时仍点【返回房间】回房续战，绝不解散房间）。
        latch   : 可选「开始类」闩锁名（recruit_start / battle_start / coop_challenge）：★有界**重试窗口**★，
                  不是「永不再点」—— 点击后窗口内不重复点（防连击）；超过窗口还停在
                  同一个按钮/弹窗 = 上次没点中 → 允许重试（否则单人第二局永远点不到「挑战」，
                  见 scene.wuchong ②e / 本票缺陷 1、3）。
        above   : 可选**相对位置判据**（#116）—— ``{"what": <参照按钮正则表>, "min_dy": <像素>}``：
                  目标框中心必须在**同一份 OCR 结果集合**里那个参照框的**上方** ≥ ``min_dy`` 像素，
                  否则**拒绝点击**（返回 False + 打原因）。★参照找不到也拒绝★：证不出「目标在那颗之上」
                  = 证不出这是目标卡（绝不盲点）。真源 ``scene.wuchong.SOLO_ABOVE``（模式页单人卡）。

    ★#78★：这里**没有**「狂点」循环（#77 曾加过一个）。真因不是少点几下，而是
    ``timeout``/``post_delay`` 太大（真机实测：settle 节点重复周期 12.4s = `timeout: 12000`
    的空转重试；房间等待 4.6s = `post_delay: 3500`）—— 那两个旋钮已经在 pipeline 上砍掉，
    本动作保持「点一次 + 立刻校验」的简单形态。
    ★#116 复核（读码 + 数框架日志，票面第 4 问）★：``run()`` **确实是单趟** ——
    「抓帧 → 定位 → **点一次** → 等 ``wait_ms`` → 抓帧 → 校验 → return」，内部没有任何重试循环。
    真机「共斗房挑战连点 7 次」是**节点被命中 7 次**（框架日志 ``node_name=WuchongCoopChallenge``
    7 行 ``CustomAction::run ... | enter``），不是一次 ``run()`` 里的循环 ⇒ 修法是跨命中的时间闩
    （``latch: coop_challenge``），不是「改成只点一次」（它本来就是只点一次）。
    """

    #: ★#79★ 时间闩锁名：``recruit_open`` / ``stale_team`` 是替掉「任务级 max_hit」用的 ——
    #:   `max_hit` 是整个任务共享的计数器（#50 教训），会把第 4 间房起的面板整段锁死；
    #:   时间闩锁只压「点了没生效」时的重试频率（≤1 次/窗口），永不失效。
    #: ★#116★ ``coop_challenge`` = 共斗房那颗「挑战」（与编队页的 ``battle_start`` 是**两颗不同的按钮**，
    #:   共享时间戳会互相压制，故用新闩名）。
    _LATCHES = (
        "recruit_start",
        "battle_start",
        "recruit_open",
        "stale_team",
        "server_retry",
        "coop_challenge",
    )
    #: ★#113★ 每个闩的窗口秒数（缺省用 ``LATCH_RETRY_S``）。``server_retry`` 是「别打服务器」的
    #: 十秒级冷却，与「防连击」的几秒不是一回事；真源 ``scene.wuchong.SERVER_RETRY_COOLDOWN_S``。
    #: ★#116★ ``coop_challenge`` 有自己的窗口（真源 ``scene.wuchong.COOP_CHALLENGE_LATCH_S``）：
    #: 必须 > 房间页一轮的重复周期（实测 5.2s），否则每一轮都放行 = 闩锁无效。
    _LATCH_WINDOWS = {
        # ★#113/#114★ 与 scene.wuchong.SERVER_RETRY_COOLDOWN_S 同源；重启识别也读同一个值，
        #   守卫 hooks_114 ④ 钉死「重试与重启都不许绕过冷却」。
        "server_retry": SERVER_RETRY_COOLDOWN_S,
        "coop_challenge": COOP_CHALLENGE_LATCH_S,
    }

    def run(self, context, argv):
        param = read_action_param(argv)
        wait_ms = int(param.get("wait_ms") or 700)
        expect = list(param.get("expect") or [])
        latch = param.get("latch")
        what = list(param.get("what") or [])
        what_next = list(param.get("what_next") or [])
        roi = tuple(param["roi"]) if param.get("roi") else None
        prefer = param.get("prefer")
        y_max = param.get("y_max")
        # ★#116★ 相对位置判据（形态与语义见类文档；真源 scene.wuchong.SOLO_ABOVE）。
        above = param.get("above") if isinstance(param.get("above"), dict) else None
        # ★闩锁 = 【重试窗口】，不是「永不再点」★（真源 scene.wuchong ②e）：
        #   刚点过（该闩自己的窗口，缺省 ``LATCH_RETRY_S``）内不重复点（防连击）；超过窗口仍停在
        #   同一按钮/弹窗 = 上次没点中 → 允许重试。旧「永不再点」会让单人第二局永远点不到「挑战」（只打一局）。
        latch_key = f"latch_ts_{latch}"
        if latch in self._LATCHES:
            with _LOCK:
                last = float(_SESSION.get(latch_key) or 0.0)
            _window = self._LATCH_WINDOWS.get(latch, LATCH_RETRY_S)
            if last and (time.monotonic() - last) < _window:
                _log(f"[wuchong_act] 闩锁 {latch}：{_window:.0f}s 冷却窗口内刚点过 → 不重复点击")
                return True

        img0 = _grab(context)
        items0 = _ocr(context, img0)
        state0, _info0 = classify(items0)
        # ★2026-10-19 收尾★：打够次数后，结算按钮的选择要换一套（见 :func:`finish_adjust_targets`）：
        #   · `finish_skip`   = 过滤掉会再开一局的按钮（单人的【再次挑战】/【继续挑战】）；
        #   · `finish_prefer` = 优先点【解散】（共斗结算第三屏一步回主城；正常运行时不解散房间）。
        finishing = False
        with _LOCK:
            finishing = bool(float(_SESSION.get("finish_settle_ts") or 0.0) > 0.0)
        finish_skip = [str(p) for p in (param.get("finish_skip") or [])]
        finish_prefer = [str(p) for p in (param.get("finish_prefer") or [])]
        what, what_next, prefer_now = finish_adjust_targets(
            what, what_next, finishing, finish_skip, finish_prefer
        )
        if finishing and (finish_skip or finish_prefer):
            _log(
                f"[wuchong_act] 收尾中：跳过 {finish_skip or '—'}；"
                f"优先 {finish_prefer or '—'}（实际候选 {what}）"
            )
        target = None
        if prefer_now:
            target = locate_button(items0, prefer_now, roi=roi, prefer=prefer, y_max=y_max)
        if target is None:
            target = locate_button(items0, what, roi=roi, prefer=prefer, y_max=y_max)
        if target is None and what_next:
            target = locate_button(items0, what_next, roi=roi, prefer=prefer, y_max=y_max)

        if target is None:
            _log(f"[wuchong_act] 未找到按钮（state={state0} what={what}）→ 不点击")
            return True

        text, cx, cy = target
        # ★#116★ 相对位置判据：目标必须在**同一份 OCR 结果集合**里的参照按钮**上方** ≥ min_dy。
        #   为什么需要独立于字符串的第二道证据：模式页上「单人游戏」「多人游戏」是两张**同形大卡**，
        #   ``what`` 只锚字符串 —— 一旦 OCR 把多人那张卡的标题读成「单人游戏」（或有人把 what 放宽成
        #   「游戏」，多人卡内部会被拆成「多人」+「游戏」两颗子框，_pick 取第一个就落在多人卡里），
        #   字符串判据就**证不出**点的是哪一张。位置能证：单人卡在左上、多人卡在右下（实测 Δy≈343px）。
        #   ★参照找不到也拒绝★ —— 证不出「目标在那颗之上」就是证不出这是目标卡，绝不盲点
        #   （bounded：拒绝＝不点＝交给枢纽重派 / 有界收工，绝不点错页面）。
        if above:
            ref_patterns = [str(p) for p in (above.get("what") or [])]
            min_dy = float(above.get("min_dy") or 0.0)
            ref = locate_button(items0, ref_patterns) if ref_patterns else None
            if ref is None:
                _log(
                    f"[wuchong_act][FAIL] 位置判据：state={state0} 同屏找不到参照按钮 {ref_patterns}"
                    f" → 拒绝点击 '{text}'（证不出点的是目标卡，绝不盲点）"
                )
                return False
            ref_text, _ref_x, ref_y = ref
            gap = float(ref_y) - float(cy)
            if gap < min_dy:
                _log(
                    f"[wuchong_act][FAIL] 位置判据：'{text}' 中心 y={cy:.0f} 没有在参照 '{ref_text}'"
                    f" y={ref_y:.0f} 上方（差 {gap:.0f}px < 要求 {min_dy:.0f}px）→ 拒绝点击"
                )
                return False
            _log(
                f"[wuchong_act] 位置判据通过：'{text}' y={cy:.0f} 在 '{ref_text}' y={ref_y:.0f}"
                f" 上方 {gap:.0f}px（要求 ≥{min_dy:.0f}）"
            )
        _log(f"[wuchong_act] state={state0} 点击 '{text}' @720({int(cx)},{int(cy)})")
        _click_box(context, cx, cy)
        if latch in self._LATCHES:
            with _LOCK:
                _SESSION[f"latch_ts_{latch}"] = time.monotonic()
        time.sleep(max(0.2, wait_ms / 1000.0))

        img1 = _grab(context)
        items1 = _ocr(context, img1)
        state1, _i1 = classify(items1)
        _observe(state1, _i1, items1)
        ok = (state1 in expect) if expect else (state1 != state0)
        if ok:
            _log(f"[wuchong_act] 校验通过：state {state0} -> {state1}")
            return True
        _log(f"[wuchong_act] [!] 校验未通过：点击后 state={state1}，期望 {expect or '画面变化'}")
        return True

