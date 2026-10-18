"""「自动刷幻想」（幻想连战）—— 共享引擎 ``battle_loop_core`` 的【导出清单 + 场景绑定】。

★★ 本文件已经没有任何状态机逻辑，只剩「绑定」和「导出」★★
------------------------------------------------------
共享引擎（画面分类 / 账本 / 会话观察 / 进度重置 / 出口 / 动作后校验 / 强杀重启）已抽到
``agent/battle_loop_core.py``，场景差异收敛到本文件的 ``_CFG = SceneConfig(...)``。这里只剩：

  ① **纯直通别名** —— core 里【同名同签名】的对象，直接绑定同一个对象::

         _feature = core._feature
         _pick    = core.pick

  ② **场景绑定** —— core 的对象 + ``functools.partial(_CFG)``，取代旧的手写转发 ``def``::

         classify = _bind(core.classify, _CFG)   # 等价于旧的手写转发，签名不变

     ``partial`` 不重列形参，故**签名与旧 def 逐字一致**。

  ③ **两个 monkeypatch 点** —— ``_ocr`` / ``_click_box`` 仍必须是模块级 ``def``：测试用
     ``ph._ocr = lambda ...`` 打桩，工厂拿到的是**运行时才去查本模块全局名**的 lambda，
     所以「替换 ph._ocr 立刻生效」（用 partial 别名会丢掉这一能力）。

★不 import ``maa.agent``★：保持离线可注册（同旧实现）。
★行为零变化★：判据 / 阈值 / 顺序 / 签名全部原样，本文件只做「去样板」。

对外名字（注册表 my_reco / my_action、离线测试、真机 runner 都依赖）：见 ``__all__``。
"""

from __future__ import annotations

import re
from functools import partial as _bind

import battle_loop_core as core
from battle_loop_core import (  # noqa: F401 —— re-export 场景无关常量（旧名字沿用）
    DEFAULT_COOP_ROOM_SEC,
    DEFAULT_RELOGIN,
    DEFAULT_STAGE_CAP,
    LEVEL_GATE_HALVES,
    MAIN_CITY_ANCHORS,
    MAIN_CITY_MIN_UNIQUE,
    MAIN_CITY_UNIQUE_ANCHORS,
    _BOTTOM_Y,
    _HHMM_RE,
    _TIME_RE,
    is_main_city_texts,
    main_city_hits,
)
from battle_loop_core import SceneConfig as _SceneConfig

# 对外名字一览（维护 ``from phantom_impl import ...`` 的既有调用方时按此表逐个找）。
__all__ = [
    # 类（注册表用）
    "PhantomStateRecognition", "PhantomDoneRecognition", "PhantomGiveUpRecognition",
    "PhantomActAction", "PhantomRestartAction",
    # 常量（含从 core re-export 的场景无关常量）
    "SCENE", "MAX_STAGES", "DEFAULT_TARGET_SETS", "RUN_DONE_KEY", "STAGE_RE",
    "DEFAULT_RELOGIN", "LEVEL_GATE_HALVES", "MAIN_CITY_ANCHORS",
    "MAIN_CITY_UNIQUE_ANCHORS", "MAIN_CITY_MIN_UNIQUE",
    "main_city_hits", "is_main_city_texts",
    "DEFAULT_STAGE_CAP", "DEFAULT_COOP_ROOM_SEC",
    "_COOP_ROOM_STATES", "_COOP_LEAVE_STATES", "_CAP_STOP_STATES",
    "_BOTTOM_Y", "_HHMM_RE", "_TIME_RE",
    # 会话（按 scene 分槽）
    "_SESSION", "_LOCK",
    # 直通（①）与场景绑定（②）的函数 + 两个 monkeypatch 点（③）
    "_feature", "_ocr", "_grab", "_click_box", "_is_level_gate", "_bottom_texts",
    "classify", "parse_stage", "_stage_key", "_set_done_key",
    "_scan_sets", "_scan_completed_sets", "_recover_counters", "_read_target",
    "_read_stage_cap", "_set_stage_cap", "_read_mode", "_set_target",
    "_mark_run_done", "_sync_task", "_current_set_recorded_progress",
    "_handle_possible_reset", "_observe", "_pick",
]

# ---------------------------------------------------------------------------
# 场景配置（幻想连战的全部「场景相关值」；判据 callable 逐字取自旧 classify 11/12 分支）
# ---------------------------------------------------------------------------
STAGE_RE = re.compile(r"第\s*(\d{1,2})\s*关")

# 「共斗房停留计时」的两类状态（#30 / #47）——
#   _COOP_ROOM_STATES ：仍在共斗房序列（房间 / 招募弹窗）→ 起算并保持时钟；
#   _COOP_LEAVE_STATES：真正离开共斗房序列（开战 / 结算 / 回关卡页 / …）→ 时钟清零。
#     ★loading / unknown 这类过渡帧【不】在表里★（#47：点「挑战」后的 loading 不清零）。
_COOP_ROOM_STATES = ("phantom_coop_room", "phantom_recruit_dialog")
_COOP_LEAVE_STATES = (
    "phantom_battle",
    "phantom_settle",
    "phantom_main",
    "phantom_solo_team",
    "phantom_hub",
    "main_city",
    "activity",
    "zhongshi",
    "relogin",
    "phantom_level_required",
)
# 「打到第 N 关就停」允许出现的画面（安全边界；★绝不包含 phantom_battle★）。
_CAP_STOP_STATES = (
    "phantom_settle",
    "phantom_main",
    "phantom_solo_team",
    "phantom_coop_room",
    "phantom_recruit_dialog",
)


def _coop_clock(scene, state, sess, now):
    """★共斗房停留计时（#30 / #47）★ —— 场景相关规则，故留在幻想的场景绑定里。

    进入共斗房 / 招募弹窗即开始计时；★只有【真正离开共斗房序列】的状态才清零★
    （_COOP_LEAVE_STATES）；点「挑战」后的 loading、认不出的 unknown 等过渡帧**保持时钟
    不动** —— 这正是 #47 的真机缺陷所在：旧实现「非房间即清零」→ 每次点挑战都把 120s
    时钟归零 → coop_room_sec 永远到不了 → 被 180s 的 PhantomStall 抢走并强杀重启游戏。
    """
    lk = core.lock(scene)
    if state in _COOP_ROOM_STATES:
        with lk:
            if not sess["coop_room_first_ts"]:
                sess["coop_room_first_ts"] = now
                print(f"[{scene.log_tag}] 进入共斗房：先招募队友再挑战；若长时间未能开战将收工")
    elif state in _COOP_LEAVE_STATES:
        with lk:
            sess["coop_room_first_ts"] = 0.0


# ★#119★ 幻想的分支顺序 = 抽取前 ``battle_loop_core.classify`` 的顺序（逐条对账见票 #119）。
# ★顺序也是语义★：结算（10）必须在 hub（11）/ main（12）之前；招募弹窗（7）/ 共斗房（8）
# 必须在编队页（9）之前（编队页与房间页的过渡帧同屏时先归房间，状态机才等招募）；
# 编队页（9）在结算（10）之前。去重只搬判据，不重排。
_CLASSIFY_ORDER = (
    "loading", "level_gate", "relogin", "battle", "main_city", "activity", "zhongshi",
    "recruit_dialog", "coop_room", "party", "settle", "hub", "main",
)


_CFG = _SceneConfig(
    scene="phantom",
    state_prefix="phantom",
    classify_order=_CLASSIFY_ORDER,
    class_prefix="Phantom",
    log_tag="phantom",
    click_action="PhantomClick",
    max_stages=15,
    default_target_sets=1,
    stage_re=STAGE_RE,
    coop=True,
    banner_patterns=(r"幻.连战", r"FANTASY"),
    coop_room_states=_COOP_ROOM_STATES,
    coop_leave_states=_COOP_LEAVE_STATES,
    cap_stop_states=_CAP_STOP_STATES,
    dispatch_node="PhantomDispatch",
    coop_clock=_coop_clock,
    # 11) 幻想连战活动入口（hub）：有 FANTASY 大标题但没有关卡选择页的「不可续战」。
    hub_match=lambda has, texts: (
        has("FANTASY ONSLAUGHT") and not has("不可续战")
        and (has("道具兑换") or has("通关奖励") or has("激战") or has("排名"))
    ),
    # 12) 幻想连战关卡选择页（主界面）。
    main_match=lambda has, texts: (
        (has("不可续战") or has("战斗记录"))
        and (has("推荐编成") or has("FANTASY ONSLAUGHT") or has("战斗"))
    ),
)

# ---------------------------------------------------------------------------
# 旧模块级常量（值来自场景配置）
# ---------------------------------------------------------------------------
SCENE = _CFG.scene
MAX_STAGES = _CFG.max_stages
DEFAULT_TARGET_SETS = _CFG.default_target_sets
RUN_DONE_KEY = core.run_done_key(_CFG)

# ★按 scene 分槽的会话 / 锁★：与 core 内部使用的是【同一对象】，测试可直接改键。
_SESSION = core.session(_CFG)
_LOCK = core.lock(_CFG)


# ---------------------------------------------------------------------------
# ① 纯直通：core 里【同名同签名】的对象 —— 绑定同一个对象，不再 def 包一层
# ---------------------------------------------------------------------------
_feature = core._feature
_grab = core.grab
_is_level_gate = core._is_level_gate
_bottom_texts = core._bottom_texts
_pick = core.pick


# ---------------------------------------------------------------------------
# ② 场景绑定：core 的对象 + partial(_CFG) —— 等价于旧 def 的逐字转发，签名不变
# ---------------------------------------------------------------------------
classify = _bind(core.classify, _CFG)
parse_stage = _bind(core.parse_stage, _CFG)
_stage_key = _bind(core.stage_key, _CFG)
_set_done_key = _bind(core.set_done_key, _CFG)
_scan_sets = _bind(core.scan_sets, _CFG)
_scan_completed_sets = _bind(core.scan_completed_sets, _CFG)
_recover_counters = _bind(core.recover_counters, _CFG)
_read_target = _bind(core.read_target, _CFG)
_read_stage_cap = _bind(core.read_stage_cap, _CFG)
_set_stage_cap = _bind(core.set_stage_cap, _CFG)
_read_mode = core.read_mode
_set_target = _bind(core.set_target, _CFG)
_mark_run_done = _bind(core.mark_run_done, _CFG)
_sync_task = _bind(core.sync_task, _CFG)
_current_set_recorded_progress = _bind(core._current_set_recorded_progress, _CFG)
_handle_possible_reset = _bind(core.handle_possible_reset, _CFG)
_observe = _bind(core.observe, _CFG)


# ---------------------------------------------------------------------------
# ③ ★monkeypatch 点：必须留成模块级 def + 延迟绑定 lambda★
# ---------------------------------------------------------------------------
# tools/test_phantom_sets.py 有 7 处 `ph._ocr = lambda context, image, entry="OcrTask": ...`。
# 下面的类工厂拿到的是 `_ocr_hook` —— 一个**运行时才去查本模块全局名**的 lambda，
# 所以「替换 ph._ocr 立刻生效」。换成 partial 别名会丢掉这个能力（partial 在绑定那一刻
# 就固定了调用目标），守卫测试会红，故这两个 def 是**故意留下**的，不是漏删的样板。
def _ocr(context, image, entry="OcrTask"):
    return core.ocr(_CFG, context, image, entry)


def _click_box(context, cx, cy):
    return core.click_box(_CFG, context, cx, cy)


# ---------------------------------------------------------------------------
# 自定义识别 / 动作（类工厂 + 延迟绑定 hook）
# ---------------------------------------------------------------------------
_ocr_hook = lambda *a, **k: _ocr(*a, **k)           # noqa: E731
_click_hook = lambda *a, **k: _click_box(*a, **k)    # noqa: E731

PhantomStateRecognition = core.make_state_reco(_CFG, _ocr_hook)
PhantomDoneRecognition = core.make_done_reco(_CFG, _ocr_hook)
PhantomGiveUpRecognition = core.make_giveup_reco(_CFG, _ocr_hook)
PhantomActAction = core.make_act_action(_CFG, _ocr_hook, _click_hook)
PhantomRestartAction = core.make_restart_action(_CFG, _ocr_hook, _click_hook)
