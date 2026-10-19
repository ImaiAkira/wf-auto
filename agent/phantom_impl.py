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
import reporting
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
    # ★#12★ 进度行：挂到 ``_CFG.progress`` 上的场景钩子（离线测试 / 守卫用）
    "PhantomProgress",
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


# ---------------------------------------------------------------------------
# ★#12★ 用户可见进度行：挂到 ``_CFG.progress`` 上的场景钩子
# ---------------------------------------------------------------------------
def _as_int(value, default: int = 1) -> int:
    """宽松整数（进度钩子的容错：坏参数最多让 note 退化成 1，绝不让跑图炸）。"""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


class PhantomProgress:
    """幻想连战的进度行（引擎三个语义点 → :mod:`reporting` 的 ``Progress``）。

    ★为什么每个「套」一条 Progress★（本类存在的唯一理由）
    ``Progress.step`` 是**单调去重**的（同一步只出一条、倒退静默）；而幻想的用户口径是
    **套内第 k/15 关**、每换一套从 1 重新数（``docs/spec/progress-visibility.md`` §C）。
    若整个任务共用一条 Progress，第 1 套报到 15 之后，第 2 套的 1..15 全被
    ``n <= last`` 吞掉 —— 面板在第二套上**再也不动**。故换套就换一条新的 Progress；
    「开始 / 收工」也走当前这条（开始 = 第一条，收工 = 当前那条）。

    ★口径分工★：k 是引擎给的**真实关号**；j/M 是引擎给的 ``set_no`` / ``target_sets``
    （= 选项「刷几套」的口径，本类**不重算**）。本类只决定「换套换 Progress」与
    「note 怎么写」；进度行字符串由 :mod:`reporting` 唯一生成 —— 这里不拼 ``[进度]``
    字面量（规格 §B 的硬纪律）。
    """

    def __init__(self, display: str = "幻想连战", unit: str = "关", max_stages: int = 15) -> None:
        self.display = display
        self.unit = unit
        self.max_stages = _as_int(max_stages, 15)
        self._lines: list[str] = []
        self._current = None    # 当前套的 reporting.Progress
        self._set_no = 0        # 当前套号（0 = 还没见过任何一步）
        self._done = False

    # -- 查询（离线测试 / 守卫的断言口径） ---------------------------------
    @property
    def lines(self) -> list[str]:
        """本任务已经打出的进度行（按出线顺序）。"""
        return list(self._lines)

    def reset(self) -> None:
        """忘掉当前任务（不打印；引擎的 ``start`` 与离线测试都从这里起步）。"""
        self._lines = []
        self._current = None
        self._set_no = 0
        self._done = False

    # -- 引擎钩子（``battle_loop_core.notify_progress`` 只调这三个） --------
    def start(self, total=None) -> str:
        """新任务开始 → 一条「开始（共 N 关）」。"""
        self.reset()
        total = self.max_stages if total is None else _as_int(total, self.max_stages)
        self._current = reporting.Progress(self.display, total=total, unit=self.unit)
        return self._emit(self._current.start())

    def step(self, index, set_no: int = 0, target_sets: int = 0) -> str:
        """该关结算记账成功 → 一条「k/N 关（第 j/M 套）」。

        ★换套换 Progress★（见类注释）：同一套内的重复/倒退仍由 ``Progress`` 单调去重。
        """
        if self._done:
            return ""
        note = self._note(set_no, target_sets)
        j = _as_int(set_no, self._set_no or 1)
        if self._current is None:
            # 懒启动：引擎没先 start（例如直接驱动 observe 的离线守卫）也不丢线。
            self._current = reporting.Progress(
                self.display, total=self.max_stages, unit=self.unit, note=note
            )
            self._set_no = j
            self._emit(self._current.start())
        elif j != self._set_no:
            self._current = reporting.Progress(
                self.display, total=self.max_stages, unit=self.unit, note=note
            )
            self._set_no = j
        self._current.note = note     # 目标套数可能被选项改掉：每次刷成最新口径
        return self._emit(self._current.step(index))

    def done(self, reason: str = "") -> str:
        """本任务收工 → 一条「收工：reason」；之后不再出步进行（``Progress.done`` 语义）。"""
        if self._done:
            return ""
        self._done = True
        if self._current is None:
            self._current = reporting.Progress(self.display, total=self.max_stages, unit=self.unit)
        return self._emit(self._current.done(reason))

    # -- 内部 ---------------------------------------------------------------
    def _note(self, set_no, target_sets) -> str:
        return f"第 {_as_int(set_no, 1)}/{_as_int(target_sets, 1)} 套"

    def _emit(self, text) -> str:
        text = text or ""
        if text:
            self._lines.append(text)
        return text



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
    # ★#12★ 用户可见进度行（唯一挂进度钩子的场景；其余场景的 SceneConfig.progress 保持 None）。
    progress=PhantomProgress(max_stages=15),
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

# ★#12★ 进度钩子的分母必须与场景的 max_stages 是**同一个数**（两处分叉 = 两套口径）。
assert _CFG.progress is None or _CFG.progress.max_stages == _CFG.max_stages, (
    f"进度钩子 max_stages={getattr(_CFG.progress, 'max_stages', None)} 与场景 "
    f"max_stages={_CFG.max_stages} 不一致（两处分叉）"
)

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
