"""「自动刷」共享引擎 —— 场景无关的战斗循环 / 账本 / 收工 / 重启状态机。

从 ``phantom_impl.py`` 抽出「状态机骨架」：画面分类、进度账本、会话观察、
进度重置、出口判定（Done / GiveUp）、动作后校验、强杀重启。场景差异**全部**来自
``SceneConfig``（一个纯数据 + 两个判据 callable 的配置对象）。

设计约束
--------
* ★不 import ``maa.agent``★：只依赖 ``maa.custom_recognition`` / ``maa.custom_action``
  以及纯逻辑模块（``maa_util`` / ``progress``）。这样 MFAAvalonia 的 AgentServer 进程能
  import，离线/真机测试脚本也能直接在进程内 Resource 上注册。
* ★``_SESSION`` / ``_LOCK`` 按 scene 分槽★：``session(scene)`` / ``lock(scene)`` 返回
  【同一 scene 固定复用】的 dict / Lock。幻/渊绝不串账、串状态（硬红线）。
* 薄壳（``phantom_impl`` / ``abyss_impl``）通过 ``make_*`` 工厂拿到绑定好 scene 的类；
  工厂接收 ``ocr`` / ``click_box`` 回调（薄壳用延迟绑定 lambda 传入），以保证
  薄壳里 ``ph._ocr = ...`` 的 monkeypatch 仍能在运行时生效。

本文件的行为与抽取前的 ``phantom_impl.py`` **逐字等价**：判据、阈值、顺序、签名均原样，
只把“场景相关值”搬进 ``SceneConfig``。``#30`` / ``#47`` 的共斗房停留时钟规则与有界收工
原样保留。
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

import progress as ledger
from maa_util import ocr_all, read_action_param, read_param

# ---------------------------------------------------------------------------
# 场景无关常量 / 锚点（两套实现逐字一致，故上提到 core）
# ---------------------------------------------------------------------------
# 「换日重进」整句候选（来自游戏包内置文案：请重新启动游戏）—— ★整句、绝不宽匹配★。
DEFAULT_RELOGIN = ("请重新启动游戏",)
# 「需要 130 级」限制弹窗：两个高信息量整句片段（绝不关键词宽匹配）。
LEVEL_GATE_HALVES = ("玩家等级达到130后", "解锁幻想连战与深渊连战")
# 主城独有锚点（至少 2 个才算主城，与 recover.json 一致）。
MAIN_CITY_ANCHORS = ("修行之道", "成长任务", "当前进度", "活动", "关卡", "领主战")

# ★主城判据的【唯一共享源】（#31 harness + #63 深渊/五重/幻想 同源）★
# MAIN_CITY_ANCHORS 的六个里只有三个是主城**独有**的：`活动`（枢纽/列表页常驻的
# 「活动时间：…」/「活动进行中！」会命中）、`关卡`、`领主战` 在别的页面也有。若按
# 「六锚点任意 ≥2」判定，任何带两个这类词的画面（#31 的领主战列表页 = 活动进行中 + 领主战；
# 深渊/五重 的编队页过渡帧同样会带上主城残留的这类词）都会被**误判成主城** ——
# 端到端表现为「点一下 → state=main_city → 空点击 → 重新导航」。
# 故主城判据收紧为「三独有锚点 ≥2」。此集合与下面的判据是**唯一真源**：
# tools/live_harness._is_main_city、abyss_impl.classify、wuchong_impl.classify、幻想 classify、
# side_impl.is_neutral_home 都从这里取，**绝不各自复制一份**（复制即漂移，#63）。
MAIN_CITY_UNIQUE_ANCHORS = ("修行之道", "成长任务", "当前进度")
MAIN_CITY_MIN_UNIQUE = 2

# ★#119★ 「终始之战」列表页的三个二级页签 —— 抽取前 core 直接写在 classify 里、
# abyss_impl 从 ``scene.abyss.ZHONGSHI_TABS`` 取，两处**同值**（"未通关/已通关/完成"）。
# 去重后它成为 :class:`SceneConfig.zhongshi_tabs` 的缺省值（幻想用缺省；深渊显式传真源值），
# 判据仍是「任一页签**整串**在场」—— 页签是数据，不是又一份分支。
DEFAULT_ZHONGSHI_TABS: tuple[str, ...] = ("未通关", "已通关", "完成")

# 与上游六锚点对账：独有集必须是子集（上游改名 -> 立刻响亮失败，不静默收紧到空集）。
assert set(MAIN_CITY_UNIQUE_ANCHORS) <= set(MAIN_CITY_ANCHORS), (
    f"主城独有锚点 {MAIN_CITY_UNIQUE_ANCHORS} 不在 MAIN_CITY_ANCHORS={MAIN_CITY_ANCHORS} 里"
)


def main_city_hits(texts):
    """命中给定文本集合里的主城**独有**锚点（#31/#63 收紧后判据的内核）。"""
    return [a for a in MAIN_CITY_UNIQUE_ANCHORS if any(a in (t or "") for t in (texts or []))]


def is_main_city_texts(texts) -> bool:
    """文本集合是否主城：主城独有锚点命中 ≥ :data:`MAIN_CITY_MIN_UNIQUE`（#31/#63 收紧）。

    只用 `修行之道` / `成长任务` / `当前进度` 这三个**主城独有**判据。这样领主战列表页
    （活动 + 领主战）、深渊/五重的编队页过渡帧都不再被误判成主城（#31 设备实证 + #63）。
    """
    return len(main_city_hits(texts)) >= MAIN_CITY_MIN_UNIQUE


# ★#112★ 「编队页」**页面状态**判据的「挑战」锚点 —— 【唯一共享源】★
#   真机事实（与 #109/#110 同源；`docs/research/recognition-ocr-vs-template.md` §1.2 例 1 / §1.3）：
#   编队页底部【挑战】按钮有两种**稳定**渲染 `挑战` / `挑战→`（统计 8/17 帧带箭头，两种读法
#   各自像素稳定、长跑里一字不差）—— 不是随机抖动，是两个视觉状态。
#   旧写法 `any(t == "挑战" for t in texts)` 是**逐字相等** ⇒ 带箭头的那一半帧上判据不成立 ⇒
#   编队页被判成 `unknown` ⇒ 状态机走错分支（#109 修的是页面**锚点**、#110 修的是**点击**判据，
#   本票修的是 classify 的**页面状态**判据 —— 三件事，别混）。
#   ★真源 = ``scene/challenge.py::CHALLENGE_CLICK_PATTERNS``★，但 ``agent/`` 是**安装态的独立目录
#   （没有 ``scene/``）**，绝不能 ``from scene.challenge import ...`` ⇒ 这里存一份**逐字快照**，
#   由 ``tools/contract_hooks/hooks_112.py`` 钉「快照 == 真源」（漂移即红）。
#   形状语义：整串锚定 + **至多一个**箭头。``(→)?`` 不是 ``(→)*`` / ``.*``：``再次挑战`` /
#   ``继续挑战`` / ``挑战深渊连战`` / ``挑战深渊连战EX`` / ``挑战→→`` / ``→挑战`` 必须继续被拒收
#   （它们都是真机屏上真的存在、且判成编队页就会**走错分支**的别的控件）。
PAGE_CHALLENGE_PATTERNS: tuple[str, ...] = (r"^挑战(→)?$",)
_PAGE_CHALLENGE_RES = tuple(re.compile(p) for p in PAGE_CHALLENGE_PATTERNS)


def is_challenge_page_text(text) -> bool:
    """这一条 OCR 文本是不是编队页那颗【挑战】按钮（整串锚定 + 至多一个箭头）。

    **页面状态判据**（「这一帧算不算编队页」），不是点击判据（点击判据见 #110 /
    ``scene/challenge.py``；两条判据同形不同责，改一个错一个就是两套真源）。
    """
    s = (text or "").strip()
    return any(r.search(s) for r in _PAGE_CHALLENGE_RES)


def has_challenge_page_text(texts) -> bool:
    """这组 OCR 文本里有没有编队页那颗【挑战】按钮（`挑战` / `挑战→` 都算）。

    深渊 / 五重 / 幻想（经 :class:`SceneConfig`）的 classify 都从这里取 ——
    **绝不各自复制一份**（复制即漂移，#63 同一纪律）。
    """
    return any(is_challenge_page_text(t) for t in (texts or ()))

# ★#33：长战斗是【正常等待】，不是异常（运维裁决 verbatim，2026-10-15）★
#   「长战斗属正常等待，必须等 —— 不要跳过、不要收工」。
#   实测 209 场：min 5s / avg ~58s / **max 842s**；游戏自身把单局封顶在 ~14min（≈840s）。
#   故「开打后等待结算」的等待上限【不得】取任意值（旧的 300s 会把仍在进行的战斗判成结束
#   —— 真机 127.0.0.1:16384 猩红巨熊讨伐/中级 实证：设备被留在战斗中、目标被跳过）。
#   本常量 = 游戏自身上限的**安全上界**（≥ 实测 max 842s，也 ≥ 游戏自身 ~14min 封顶，取整到 900s）,
#   是【单一真源】：`agent/side_impl._BATCH_FIGHT_TIMEOUT`（开打等待兜底）与
#   `tools/live_harness.LIVE_BATTLE_WAIT_SEC`（归位等待实时战斗页）都从它派生。
BATTLE_GAME_CAP_SEC = 900.0

# 战斗中 HUD：底部条带的「时间 HH:MM」+「分数 NNNNN」。
# ★必须带格式且限定底部★：结算页的「最长滞空时间6秒」「战斗分数」在上/中部，
#   裸「时间」「分数」会把结算页误判成战斗 → 空等死循环（raid 踩过 32 分钟）。
_TIME_RE = re.compile(r"时间\s*\d{1,3}:\d{2}")
_HHMM_RE = re.compile(r"^\d{1,3}:\d{2}$")
_BOTTOM_Y = 1150  # 720 空间，底部条带起点

# 关卡上限选项「打到第几关以后放弃」的默认值：0 = 不限制（保持旧行为）。
DEFAULT_STAGE_CAP = 0

# 「共斗房停留上限」（#30）默认值：共斗房「挑战」在没招募到队友前是灰的，
# 停留超过这么久仍未能开战 → 有界收工（绝不空转）。
DEFAULT_COOP_ROOM_SEC = 120.0

#: ★#118★ 「零进度」的独立上限（秒）：**一场都没完成**时用这个，比 no_progress_sec 更短。
#: 真机：幻想连战用空队伍反复重进第 1 关，20 秒一轮；旧判据要求 `cs>0 或 mx>0` ⇒ 永不收工。
#: 与真源 scene.abyss.ZERO_PROGRESS_SEC 同值（由守卫钉）。
ZERO_PROGRESS_SEC = 300

#: ★ADR 0005★ 「迷路」闸门的缺省阈值（秒）：连续这么久认不出画面 → 收工兜底。
#: 旧的「每帧累计」闸门（120 帧）已删除 —— 它随运行时长单调增长，无界会话必越线
#: （幻象 38 套 / 深渊第 20 战都是这么误杀的）。阈值按场景数据化（``scene/*``，与
#: ``ZERO_PROGRESS_SEC`` 同处）；override 里的 ``lost_sec`` 优先于本缺省值。
#: 深渊实测：正常转场连续驻留 p95 6s、最长 16s → 60s 有 3.75× 余量（#18 / ADR 0005）。
DEFAULT_LOST_SEC = 60.0


def lost_reason(seconds: float, last_known: str | None = None) -> str:
    """★ADR 0005 / #76★ 迷路收工原因（三个场景**同一句**，绝不各写一份）。

    格式：``连续 {n}s 认不出画面（最后已知页：{last}）``。
    ``n`` 向下取整（不把没走满的那一秒算进去）；``last`` 为空时写「未知」。
    """
    last = (last_known or "").strip() or "未知"
    return f"连续 {int(seconds)}s 认不出画面（最后已知页：{last}）"


# ===========================================================================
# ★#38 / #46：战斗失败页（GAMEOVER /「是否续关？」）与战斗 HUD 的判据（纯函数）★
#
# 现场（真机，已核过的事实，勿重新发现）
# ------------------------------------
# · #38（魁雷精灵兽 战斗打输）：进入 GAMEOVER /「是否续关？」→ pipeline 没有对应节点 →
#   任务卡死，且后续 3 个成员（威风 / 巫光 / 暗唤精灵兽）一个都没跑成。一次战斗失败不该
#   让整批任务死掉 → 处置「放弃该次战斗 → 记录原因 → 继续清单」，同一失败连续 2 次才收工。
# · #46（真机 127.0.0.1:16384，维·索拉斯讨伐/超级 打输）：GAMEOVER /「是否续关？」页
#   **底部仍然画着战斗 HUD 的「时间/分数」**，于是 SpecialBattleWait 的 And(时间,分数)
#   在这一页也命中 → 它赢下这一帧、DoNothing、走自己的 next（无 GAMEOVER 打断）→
#   [JumpBack]PubGameOver* 永不执行 → SpecialBattleWait ↔ SpecialEntry 空转到 1200s 超时。
#   ★致命现场事实★：失败页的「放弃 / 续关」那一行（720 y≈1043）与弹板点 (360,1067)
#   **同一行** → 在失败页继续连点 = 真实误点。故 #71 手操引擎的停止条件必须是**正面页面
#   判据**，不能只靠「HUD 消失」。
#
# MAA 识别无 Not（And 也无法对子引用取反 —— 已用最小 pipeline 实测），故 pipeline 侧用
# 【分派优先级】表达排他：SpecialEntry.next 里在 SpecialBattleWait 之前放了
# SpecialGameOverHold（只认『GAMEOVER』+「是否续关？」）。
#
# 分工（#38 段原文）：
#   · 画面识别与「拒绝续关」的点击 = pipeline 节点（common.json 的 PubGameOver*，
#     由 SpecialEntry.next 以 [JumpBack] 引用）—— 读屏再点，绝不盲点、绝不点『续关』；
#   · 「记一次失败 / 放弃该目标 / 连续 2 次收工」的决定 = 指挥官（SpecialBatchPlan）。
# 下面的纯函数是这条规则的【语义真源】，供离线真机帧复现/守卫逐帧求值。
#   ★R8 单源收敛★：side_impl / wuchong_impl 都从这里取，**绝不各自复制一份**。
# ===========================================================================

#: 战斗失败页的识别锚点（真机帧 recover_before / recover_mid；判据值与 common.json 的
#: PubGameOver* 节点同源，绝不两写——hooks_38 会把两边对账）。
GAMEOVER_TITLE = "GAMEOVER"
GAMEOVER_PROMPT = "是否续关"
GAMEOVER_GIVEUP = "放弃"
GAMEOVER_CONFIRM_MARKERS = ("放弃时", "无法获得该关卡内已获得的")


def classify_gameover(items) -> str | None:
    """画面 OCR 条目 -> 战斗失败状态（★纯函数★，离线可单测，不碰设备）。

    返回：
      · ``"giveup"``  —— GAMEOVER 页（『GAMEOVER』横幅 + 「是否续关？」）→ 应拒绝续关；
      · ``"confirm"`` —— 放弃确认框（『放弃时 无法获得…』）→ 应点『OK』推进；
      · ``None``      —— 不是战斗失败画面（不介入）。

    ★先判 confirm★：确认框是 GAMEOVER 的子状态，且两页不共存；若有万一同时读到，按确认框
    处理（点『OK』）比按 GAMEOVER 处理（再点一次『放弃』）更安全。
    """
    texts = [(t or "") for t, _b in items]
    if any(m in t for t in texts for m in GAMEOVER_CONFIRM_MARKERS):
        return "confirm"
    if any(GAMEOVER_TITLE in t for t in texts) and any(GAMEOVER_PROMPT in t for t in texts):
        return "giveup"
    return None


#: 战斗 HUD 判据（与 common.json 的 PubBattleTime/PubBattleScore 同源，绝不两写）。
#: ★空格鲁棒★：真机 OCR 会给出**双空格**（如 ``分数  00166756407``，见
#: tools/contract_hooks/hooks_auto_outside.BATTLE_HUD_ITEMS / tools/frames/auto_battle_hud_hit.png），
#: 写死一个空格会把战斗页判成 ``other``（手操引擎每 2s 让位一次）；故用 ``\s*``。
#: 这两条与 scene/auto_switch.BATTLE_HUD_ANCHORS（lane B）**逐字相等**（守卫字面比对）。
BATTLE_HUD_TIME_RE = r"时间\s*\d{1,3}:\d{2}"
BATTLE_HUD_SCORE_RE = r"分数\s*\d"

#: ★#107 真机★ `scene.auto_switch.BATTLE_HUD_FALLBACK_ANCHORS` 的**逐字快照**
#: （安装态没有 scene/；由 hooks_74 钉「快照 == 真源」）。
#: 用途：HUD 那条被 toast 压住时（真机 wuchong_hud_occluded.png），靠**多个视觉特征**兜底认出战斗页。
BATTLE_HUD_FALLBACK_ANCHORS_SNAPSHOT = (
    r"FEVER",
    r"\d{1,3}\.\d%",
    r"^ABILIT",
)
BATTLE_HUD_FALLBACK_MIN_SNAPSHOT = 2


def is_battle_hud(items) -> bool:
    """★纯函数★：这一帧是不是【真正的战斗 HUD】（底部「时间 mm:ss」+「分数 N」）。

    只判 HUD 本身（与 SpecialBattleWait 的 And 同判据），不掺页面语义。
    """
    texts = [(t or "") for t, _b in items]
    # ① 主判据：时间 + 分数都在（最可靠）
    if any(re.search(BATTLE_HUD_TIME_RE, t) for t in texts) and any(
        re.search(BATTLE_HUD_SCORE_RE, t) for t in texts
    ):
        return True
    # ② ★#107 兜底★ HUD 被 toast 压住时（真机 wuchong_hud_occluded.png）：
    #    靠**≥2 个战斗视觉特征**认。单个太弱（结算页也有伤害数字/主城也有倒计时），
    #    所以要求多特征共现；负例（结算/失败/编队/主城）由守卫用入库帧逐个验。
    # ★失败页排除★：GAMEOVER /「是否续关？」页同样保留战斗视觉（真机帧 gameover_prompt.png /
    # gameover_confirm.png），主判据历史上就把它们判 True（由 battle_wait_should_hold 排除）；
    # 新兜底分支必须自己排除，否则失败页会被当成战斗页去点弹板。
    if classify_gameover(items) is not None:
        return False
    hits = sum(
        1
        for pat in BATTLE_HUD_FALLBACK_ANCHORS_SNAPSHOT
        if any(re.search(pat, t) for t in texts)
    )
    return hits >= BATTLE_HUD_FALLBACK_MIN_SNAPSHOT


def battle_wait_should_hold(items) -> bool:
    """★#46★：这一帧【该不该由 SpecialBattleWait 处理】= 真战斗 HUD 且不是失败页。

    GAMEOVER /「是否续关？」页底部仍画着「时间/分数」（真机帧实证），故只靠 HUD 判据会把
    失败页当成「战斗中」；这里额外排除 ``classify_gameover`` 认出的失败页 / 放弃确认框，
    于是失败页上 SpecialBattleWait **不应命中**，交给 #38 的拒绝续关 / 确认框推进。
    """
    if classify_gameover(items) is not None:
        return False
    return is_battle_hud(items)


# ---------------------------------------------------------------------------
# ★#119★ 画面分类的「分支表 / 状态名拼法」—— 唯一一份 classify 的数据面
#
# 现场（本票的起点，别再重新发现）：``classify`` 曾在**三个文件**里各写一份
# （core / abyss_impl / wuchong_impl），判据几乎逐行重复。代价不是"多维护一份"，而是
# **#107 修好的 HUD 兜底只对五重生效** —— 同一帧上 ``is_battle_hud=True``，另外两份
# classify 却判 ``unknown``，真机 912 秒死循环。一个正确的修复被重复实现静默废掉，
# 比 bug 本身更危险。
#
# 去重后的形状：
#   · 判据**只有**本文件的 ``classify`` + 下面 18 个 ``_branch_*`` 纯函数这一份；
#   · 每个场景的差异**只有数据**（:class:`SceneConfig`）：``classify_order`` 决定
#     「启用哪些分支、按什么顺序」，其余字段是锚点/状态名；
#   · **顺序也是语义**（三个场景的顺序逐条原样保留，见各模块的 ``_CLASSIFY_ORDER``）：
#       结算必须排在 hub/main 之前；五重的领主战列表必须排在 main_city 之前；
#       编队页必须排在 detail 之前；五重的 no_entry 弹窗必须排在 battle 之前。
# 任何「这个场景要一段自己的分支逻辑」的诉求，都不许再写成第二份 classify
# （``tools/contract_hooks/hooks_119.py`` 的 ①② 把守：判据字面量 + 薄封装的函数体）。
# ---------------------------------------------------------------------------

#: classify 能返回的**不带前缀**的状态名（三个场景共用同一批词汇）。
#: 其余状态一律 ``f"{scene.state_prefix}_{后缀}"`` —— 前缀就是场景 id。跨场景状态名混用
#: 会让排查时说不清是谁的页面（#100 的现场，见 hooks_116 的教训；lords 也因此自己一份）。
BARE_STATES: tuple[str, ...] = ("loading", "relogin", "main_city", "activity", "zhongshi")

#: 分支 → 返回状态的缺省后缀（``None`` = 用 :data:`BARE_STATES` 里的裸名）。
#: 场景要用别的拼法（如五重的 ``wuchong_team`` / ``wuchong_room``）时，在
#: :attr:`SceneConfig.state_names` 里**显式**覆盖 —— 绝不写 ``if scene == ...``。
_BRANCH_STATE_SUFFIX: dict[str, str | None] = {
    "loading": None,
    "level_gate": "level_required",
    "relogin": None,
    "no_entry": "no_entry",
    "battle": "battle",
    # ★#107★ 过关演出帧（QUEST CLEAR）：语义上这一场还在收尾，紧接着就是结算 → 归 battle。
    "quest_clear": "battle",
    "lord_list": "lord_list",
    "main_city": None,
    "activity": None,
    "zhongshi": None,
    "recruit_dialog": "recruit_dialog",
    "coop_room": "coop_room",
    # 编队页：幻想/深渊叫 ``*_solo_team``；五重叫 ``wuchong_team``（state_names 覆盖）。
    "party": "solo_team",
    "mode": "mode",
    "detail": "detail",
    "settle": "settle",
    "hub": "hub",
    "main": "main",
}

@dataclass(frozen=True)
class SceneConfig:
    """一个场景的静态配置：**画面分类的数据面** + 自动刷状态机的配置。

    ★#119★ ``classify`` 只读「画面分类」那一段（``classify_order`` / 锚点 / ``state_names`` /
    ``hub_match`` / ``main_match``）。抽取前所有字段都是必填；现在只有真状态机（幻想）需要
    状态机段，classify-only 场景（深渊 / 五重各有自己的状态机）留缺省即可 ——
    :meth:`__post_init__` 会拒绝「状态机字段只配了一半」的配置，免得有人拿一份只够分类的
    配置去跑 ``observe``。
    """

    scene: str                      # 会话/账本命名空间（如 "phantom"）；= state_prefix
    state_prefix: str               # 画面状态名前缀（phantom_main / phantom_hub / …）
    #: ★画面分类的两个承重字段★：启用哪些分支、按什么顺序（顺序也是语义）。
    #: 名字必须来自 :data:`CLASSIFY_BRANCHES`；同一分支不许出现两次。
    classify_order: Sequence[str]

    # ---- 画面分类：场景差异（全部是数据；判据实现只有 classify 一份）----
    #: ★#74 五重★ 战斗判据用「位置无关的 is_battle_hud」（真机 HUD 是一个合并框）。
    #: False = 底部条带「时间 mm:ss」+「分数 N」为主判据、共享 is_battle_hud 兜底（#118）。
    battle_direct_hud: bool = False
    #: 结算的**额外**锚点（五重：返回房间 / 解散）；核心锚点见 :func:`_is_settle`。
    settle_extra_anchors: Sequence[str] = ()
    #: ★#87 五重★ 「当前不满足出战条件」弹窗的整句判据（空串 = 不启用该分支）。
    no_entry_text: str = ""
    #: ★#107 五重★ 是否启用「QUEST CLEAR 过关演出 → battle」分支。
    quest_clear: bool = False
    #: ★#56 五重★ 领主战/降临讨伐列表页的独有锚点（任一在场即列表页）。
    lord_list_all: Sequence[str] = ()
    #: 列表页顶部的两个页签 + 首行名（(页签在场) 且 (行名在场) 也算列表页）。
    lord_list_tabs: Sequence[str] = ()
    lord_list_rows: Sequence[str] = ()
    #: ★#116 五重★ 模式选择页锚点（单人游戏 / 多人游戏；页判据是「或」）。
    mode_anchors: Sequence[str] = ()
    #: 详情页判据：标题锚点 且 标记锚点（五重决战·超级）。
    detail_titles: Sequence[str] = ()
    detail_markers: Sequence[str] = ()
    #: 终始之战列表页的二级页签（缺省 = :data:`DEFAULT_ZHONGSHI_TABS`）。
    zhongshi_tabs: Sequence[str] = DEFAULT_ZHONGSHI_TABS
    #: 状态名的显式覆盖（分支名 → 完整状态名）；未覆盖的按前缀+后缀拼。
    state_names: Mapping[str, str] = field(default_factory=dict)

    # ---- 自动刷状态机（只有幻想这类真状态机需要；classify-only 场景留缺省）----
    class_prefix: str = ""                 # 生成的类名前缀（Phantom*）
    log_tag: str = ""                      # 打印前缀（phantom）
    click_action: str = ""                 # 原生 Click 动作名（PhantomClick）
    max_stages: int = 0                    # 一「套」的关数（15）
    default_target_sets: int = 1           # 默认刷几套（1）
    stage_re: re.Pattern | None = None     # 「第N关」解析正则
    #: 是否有共斗房：状态机 ``observe`` 是否调用 ``coop_clock``（#30 / #47）。
    #: ★分类不看它★ —— 分类是否认识「共斗房页」由 ``classify_order`` 里有没有
    #: ``coop_room`` 分支决定（深渊没有这个分支，幻想/五重有）。
    coop: bool = False
    banner_patterns: Sequence[str] = ()    # 横幅 OCR 正则列表（step=banner 用）
    coop_room_states: Sequence[str] = ()   # 「仍在共斗房序列」的画面（#30）
    coop_leave_states: Sequence[str] = ()  # 「真正离开共斗房」的画面（#47）
    cap_stop_states: Sequence[str] = ()    # 「第 N 关打完」允许收工的安全画面
    dispatch_node: str = ""                # 批量模式回指挥官的节点名（override_next 用）
    #: ★共斗房停留计时钩子（#30 / #47）★：规则**场景相关**（幻想连战的协力关才有共斗房），
    #: 收敛到场景钩子；核心 observe 在「去重守卫之后、状态处理之前」调用它。签名：
    #: ``(scene, state, sess, now) -> None``（只在 ``coop`` 为真时被调用）。
    coop_clock: Callable[[SceneConfig, str, dict, float], None] | None = None

    #: ★#12★ 可选的**用户可见进度**钩子（默认 None = 与抽取前逐字节等价的旧行为）。
    #:
    #: 只有真状态机场景（幻想连战）会挂它；classify-only 场景（深渊 / 五重）与所有离线
    #: 守卫都留缺省。形状是 **duck-typed 的三个方法**（缺哪个就不回调哪个）：
    #:
    #:   ``start(total: int)``                                 新任务开始（task_id 变化时）
    #:   ``step(index: int, set_no: int, target_sets: int)``    该关**结算记账成功**（账本已落盘）
    #:   ``done(reason: str)``                                 本任务收工（Done / GiveUp 出口）
    #:
    #: ★分工★：引擎只负责在**语义点**上告诉钩子「这一步是什么、数据是什么」；一句话怎么
    #: 说是场景钩子的事（文案的唯一出口是 :mod:`reporting` 的 ``Progress``）。引擎里不拼
    #: ``[进度]`` 字符串 —— 一拼就有第二份格式（本票的硬约束）。
    #: 所有回调都经 :func:`notify_progress`：None 时**一个字节都不写**，异常绝不影响跑图。
    progress: object | None = None

    # ---- 页面判据 callable（场景自己的 hub / main；#63 起就是这个形状）----
    hub_match: Callable[[Callable[[str], bool], Sequence[str]], bool] | None = None
    main_match: Callable[[Callable[[str], bool], Sequence[str]], bool] | None = None

    def __post_init__(self) -> None:
        """配置自检：分支/数据/状态名对不上就**在构造期**炸，绝不静默少判一页。

        为什么值得写这么多校验：classify 的失败形态是「某一页不再被认出来」，
        在真机上表现为状态机走错分支 / 空转 —— #107 就是被两份副本这样静默废掉的。
        宁可 import 期响亮失败。
        """
        if not self.scene or not self.state_prefix:
            raise ValueError("SceneConfig 必须有 scene / state_prefix")
        order = tuple(self.classify_order)
        if not order:
            raise ValueError(f"场景 {self.scene!r} 的 classify_order 为空")
        unknown = [b for b in order if b not in _BRANCH_STATE_SUFFIX]
        if unknown:
            raise ValueError(
                f"场景 {self.scene!r} 的 classify_order 含未知分支 {unknown!r}"
                f"（可选：{sorted(_BRANCH_STATE_SUFFIX)}）"
            )
        if len(set(order)) != len(order):
            raise ValueError(f"场景 {self.scene!r} 的 classify_order 有重复分支：{order!r}")
        # 每个分支需要的锚点数据必须到位（缺了不是「少判一页」，是每帧都少判）。
        need = {
            "no_entry": (("no_entry_text", self.no_entry_text),),
            "lord_list": (
                ("lord_list_tabs", tuple(self.lord_list_tabs)),
                ("lord_list_rows", tuple(self.lord_list_rows)),
            ),
            "mode": (("mode_anchors", tuple(self.mode_anchors)),),
            "detail": (
                ("detail_titles", tuple(self.detail_titles)),
                ("detail_markers", tuple(self.detail_markers)),
            ),
            "zhongshi": (("zhongshi_tabs", tuple(self.zhongshi_tabs)),),
        }
        for branch in order:
            for name, value in need.get(branch, ()):
                if not value:
                    raise ValueError(
                        f"场景 {self.scene!r} 启用了 {branch!r} 分支，但 {name} 为空"
                    )
        if "quest_clear" in order and not self.quest_clear:
            raise ValueError(
                f"场景 {self.scene!r} 启用了 quest_clear 分支，但 quest_clear=False"
            )
        for branch, attr in (("hub", "hub_match"), ("main", "main_match")):
            if branch in order and getattr(self, attr) is None:
                raise ValueError(
                    f"场景 {self.scene!r} 启用了 {branch!r} 分支，但没有 {attr} callable"
                )
        for branch, name in self.state_names.items():
            if branch not in _BRANCH_STATE_SUFFIX:
                raise ValueError(
                    f"场景 {self.scene!r} 的 state_names 含未知分支 {branch!r}"
                )
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"场景 {self.scene!r} 的 state_names[{branch!r}] 必须是非空字符串"
                )
        # 状态机字段：要么一项不配（classify-only），要么配全（真状态机）。
        machine = {
            "class_prefix": self.class_prefix,
            "log_tag": self.log_tag,
            "click_action": self.click_action,
            "max_stages": self.max_stages,
            "stage_re": self.stage_re,
            "dispatch_node": self.dispatch_node,
            "coop_clock": self.coop_clock,
        }
        given = [k for k, v in machine.items() if v]
        if given and len(given) != len(machine):
            missing = [k for k in machine if k not in given]
            raise ValueError(
                f"场景 {self.scene!r} 的状态机字段只配了一半（缺 {missing}）—— "
                "classify-only 场景请全部留缺省；真状态机必须配全"
            )



# ---------------------------------------------------------------------------
# ★ADR 0005 / #76★ 「迷路」原语：连续多久认不出画面（不是累计多少帧）
# ---------------------------------------------------------------------------
class LostClock:
    """连续认不出画面的时钟 —— ADR 0005 的**唯一**迷路判据来源。

    语义（ADR 0005）：「迷路」与「正常转场」的区别只在**持续** —— 进入 ``unknown``
    打点、命中任一已知页清点，用「连续秒数」表达。旧的「累计帧数」计数器是单调增长量，
    无界会话必然越线：幻象 38 套、深渊第 20 战都因此被误杀（真机逐帧：正常转场连续
    驻留 p95 6s、最长 16s，没有一次是迷路）。

    ``in_fight=True`` 期间 unknown **不记起点**（#76 的结论并入原语）—— 战斗
    episode 内技能演出 / 换波必然反复出现 unknown，那不是迷路。

    ``worst_seconds`` / ``last_known`` 只给日志与收工原因（:func:`lost_reason`）用，
    **不参与任何判定**。``now`` 一律由调用方显式传入（类内绝不调
    ``time.monotonic()``）—— 离线测试要能喂假时间。
    """

    __slots__ = ("_start", "worst_seconds", "last_known")

    def __init__(self) -> None:
        self._start: float | None = None   # 当前这段 unknown 的起点（None = 不在 unknown）
        self.worst_seconds = 0.0           # 最长的一段**已结束** unknown（诊断用；当前段看 seconds_lost）
        self.last_known: str | None = None  # 最后一个已知页面名（诊断 / 收工原因用）

    def observe(self, state, now: float, in_fight: bool = False) -> None:
        """喂一帧分类结果：进入 unknown 打点、命中已知页清点、战斗中不打点。"""
        if state == "unknown":
            if in_fight:
                # #76：战斗 episode 内的 unknown 不算迷路 —— 不记起点。
                # （正常流程里战斗页/结算页都是已知页，已有的起点在那些帧就已清掉。）
                return
            if self._start is None:
                self._start = now
            return
        # 命中任一已知页 → 清点：把刚结束的这一段计入 worst_seconds，并记住最后已知页。
        if self._start is not None:
            self.worst_seconds = max(self.worst_seconds, now - self._start)
            self._start = None
        self.last_known = state

    def seconds_lost(self, now: float) -> float:
        """当前**连续** unknown 秒数；不在 unknown 时恒为 0（历史不累加）。"""
        if self._start is None:
            return 0.0
        return max(0.0, now - self._start)

    def reset(self) -> None:
        """新任务：整只时钟归零（与 ``_new_session`` 的缺省值同一份）。"""
        self._start = None
        self.worst_seconds = 0.0
        self.last_known = None


# ---------------------------------------------------------------------------
# ★按 scene 分槽的会话 / 锁 / OCR 缓存★（硬红线：幻/渊绝不共享）
# ---------------------------------------------------------------------------
_SESSIONS: dict = {}
_LOCKS: dict = {}
_OCR_CACHES: dict = {}
_SLOT_BOOKKEEPING_LOCK = threading.Lock()

#: ★ADR 0005★ override 里残留的旧「帧数上限」参数名。本仓已删除该参数，这里只留
#: 兼容识别用的**唯一一处**字面量（兼容行为需要读这个键，不可能完全消失）。
_STALE_FRAME_LIMIT_PARAM = "unknown_limit"

#: 该过时参数只警告一次（GiveUp 每帧都跑，逐帧打会把日志刷爆）；
#: 键 = (参数名, scene)，新任务也不必重复警告。
_STALE_PARAM_WARNED: set = set()


def warn_stale_frame_limit(scene_name: str, tag: str, param) -> None:
    """兼容口径（ADR 0005）：override 里残留的旧帧数参数 → **忽略** + 打一行警告。

    ★绝不静默恢复计数★：把它当没看见会制造「看起来调好了」的错觉，恢复计数更糟
    （那正是本 ADR 要删掉的量纲）。所以：忽略参数，但每次进程每场景留一行证据。

    ★公开 + 只收 ``scene_name``★：三个场景的 GiveUp 各有自己的会话/配置对象
    （kernel 的 ``SceneConfig`` / 深渊的 ``AbyssScenario``），本函数不该依赖其中任何一种 ——
    否则深渊/五重为了复用它就得各自抄一份警告文案（ADR 0005 要消灭的正是「三份漂移」）。
    """
    if _STALE_FRAME_LIMIT_PARAM not in param:
        return
    key = (_STALE_FRAME_LIMIT_PARAM, scene_name)
    with _SLOT_BOOKKEEPING_LOCK:
        if key in _STALE_PARAM_WARNED:
            return
        _STALE_PARAM_WARNED.add(key)
    value = param.get(_STALE_FRAME_LIMIT_PARAM)
    print(
        f"{tag} 忽略过时参数 {_STALE_FRAME_LIMIT_PARAM}={value}"
        f"（已换成 lost_sec，见 ADR 0005）"
    )


def _new_session(scene: SceneConfig) -> dict:
    """新建一个 scene 的会话状态（字段与抽取前 ``_SESSION`` 逐字一致）。"""
    return {
        "task_id": None,
        "cur_stage": None,          # 当前套内第几关（画面解析得出）
        "cur_set": 1,               # 当前第几套（1 起）
        "completed_sets": 0,        # 已完整打完的套数
        "target_sets": scene.default_target_sets,  # 用户指定要跑几套
        "max_done": 0,              # 当前套内【账本 + 会话】已完成的最大关号
        # ★会话（本次任务）内实际观察到的当前套最大完成关号★。
        "session_max_done": 0,
        # ★首次观察基准★：本次任务第一次看到「关卡选择页/编队页」时的画面关号。
        "joined_stage": None,
        # 关卡上限（选项「打到第几关以后放弃」注入；0 = 不限制）。
        "stage_cap": DEFAULT_STAGE_CAP,
        "total_marks": 0,           # 账本里 phantom/set 下的总笔数（异常检测用）
        "in_fight": False,
        "start_ts": 0.0,
        "last_progress_ts": 0.0,
        # ★ADR 0005★ 迷路时钟（替换旧的帧数累计计数器）。
        "lost": LostClock(),
        "last_state": None,
        "last_observe_ts": 0.0,
        "tab_index": 0,
        "wait_count": 0,
        # ★共斗房停留计时（#30）★：进入共斗房（或招募弹窗）的单调时刻。
        "coop_room_first_ts": 0.0,
    }


def session(scene: SceneConfig) -> dict:
    """返回 scene 的会话 dict（同一 scene 固定复用同一对象；测试可直接改键）。"""
    with _SLOT_BOOKKEEPING_LOCK:
        return _SESSIONS.setdefault(scene.scene, _new_session(scene))


def lock(scene: SceneConfig) -> threading.Lock:
    """返回 scene 的线程锁（同一 scene 固定复用同一 Lock）。"""
    with _SLOT_BOOKKEEPING_LOCK:
        return _LOCKS.setdefault(scene.scene, threading.Lock())


# ---------------------------------------------------------------------------
# ★#12★ 用户可见进度钩子：引擎侧**唯一**调用口
# ---------------------------------------------------------------------------
def notify_progress(scene: SceneConfig, method: str, *args) -> None:
    """把「一个进度语义点」转给 ``scene.progress``（None = 未启用 → 立即返回）。

    ★为什么只留这一个口★
    所有回调集中在这里，才可能用一条守卫证明「progress=None 时行为与旧实现逐字节等价」：
    ``hook is None`` 时本函数直接 return，一个 print / 一个 say 都不会发生；``scene.progress``
    在引擎里**只出现在本函数**（``hooks_145`` 用 AST 钉住这一点，加一处直调就红）。

    ★失败语义（与 :mod:`reporting` 同一条纪律）★：钩子里的任何异常都只写一行机制日志
    （quiet 时进 ``debug/agent.log``），绝不冒泡 —— 进度行坏了不许把跑图搞停。
    """
    hook = scene.progress
    if hook is None:
        return
    fn = getattr(hook, method, None)
    if fn is None:
        return
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        print(f"[{scene.log_tag}] 进度钩子 {method} 失败：{exc}")


# ---------------------------------------------------------------------------
# OCR / 截图 / 原生点击
# ---------------------------------------------------------------------------
def _feature(image):
    """廉价图像特征（用于 OCR 缓存键）。"""
    try:
        import numpy as np
        a = np.asarray(image)
        if a.ndim == 3:
            a = a[:, :, :3]
        return (a.shape, int(a[::37, ::37].sum()))
    except Exception:  # noqa: BLE001
        return ("raw", id(image))


def ocr(scene: SceneConfig, context, image, entry="OcrTask"):
    """带 1.5s 缓存的 OCR（每个 scene 独立缓存）。"""
    with _SLOT_BOOKKEEPING_LOCK:
        cache, ts = _OCR_CACHES.setdefault(scene.scene, ({}, {}))
    key = _feature(image)
    now = time.monotonic()
    cached = cache.get(key)
    if cached is not None and (now - ts.get(key, 0.0)) < 1.5:
        return cached
    items = ocr_all(context, image, entry)
    cache[key] = items
    ts[key] = now
    if len(cache) > 24:
        oldest = sorted(ts, key=lambda k: ts.get(k, 0.0))[:12]
        for k in oldest:
            cache.pop(k, None)
            ts.pop(k, None)
    return items


def grab(context):
    return context.tasker.controller.post_screencap().wait().get()


def click_box(scene: SceneConfig, context, cx, cy):
    """用 pipeline 原生 Click 动作点击 720 空间 (cx,cy)。

    ★不用 ``controller.post_click``★：部分原生库未导出 → ACCESS_VIOLATION。走
    ``context.run_action(scene.click_action, box=...)``，版本无关。
    """
    try:
        context.run_action(scene.click_action, box=(int(cx) - 1, int(cy) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[{scene.log_tag}] 点击失败 ({cx},{cy})：{exc}")
        return False


# ---------------------------------------------------------------------------
# 画面分类
# ---------------------------------------------------------------------------
def _is_level_gate(texts):
    """是否出现「需要 130 级」限制弹窗（两个整句片段都命中）。"""
    joined = "".join(t or "" for t in (texts or []))
    return all(h in joined for h in LEVEL_GATE_HALVES)


def _bottom_texts(items):
    out = []
    for t, b in items:
        if not b or len(b) != 4:
            continue
        if b[1] + b[3] / 2.0 > _BOTTOM_Y:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# ★#119★ 唯一一份「画面分类」：分支纯函数 + 场景数据驱动的顺序
#
# 每个分支签名统一：``(scene, items, texts, has, relogin_phrases) -> (state, info) | None``。
# ``None`` = 不是这一页，继续下一个分支；:data:`CLASSIFY_BRANCHES` 是**全部判据的唯一落点**。
# ★别在这里给某个场景加 if★ —— 场景差异一律走 :class:`SceneConfig`（加字段可以，
# 加分支逻辑不行；hooks_119 会红）。
# ---------------------------------------------------------------------------
def state_for_branch(scene: SceneConfig, branch: str) -> str:
    """某分支在该场景下返回的状态名（``state_names`` 覆盖优先，否则前缀+后缀拼）。

    ★唯一拼法★：``f"{scene.state_prefix}_{后缀}"``，或 :data:`BARE_STATES` 里的裸名。
    五重的 ``wuchong_team`` / ``wuchong_room`` / ``wuchong_no_entry`` 用
    ``state_names`` **显式**覆盖 —— 绝不在 classify 或分支函数里为某场景写 if。
    """
    override = scene.state_names.get(branch)
    if override:
        return override
    suffix = _BRANCH_STATE_SUFFIX.get(branch)
    return f"{scene.state_prefix}_{suffix}" if suffix else branch


def _settle_like(texts, has, scene: SceneConfig) -> bool:
    """结算**锚点**是否在场（战斗兜底必须排除它们，但不要求「获得道具 + 继续/OK」组合）。

    抽取前 core / abyss 的兜底排除判据就是这三条（+ 场景额外锚点），原样保留：
    结算页上方也有「时间/分数」与伤害数字，不能判成战斗中。
    """
    if has("QUESTRESULT") or has("获得道具") or has("继续挑战"):
        return True
    return any(a and any(a in t for t in texts) for a in scene.settle_extra_anchors)


def _is_settle(scene: SceneConfig, texts, has) -> bool:
    """结算 / 奖励页的完整判据（核心三条 + 场景额外锚点）。"""
    if has("QUESTRESULT") or has("继续挑战"):
        return True
    if any(a and any(a in t for t in texts) for a in scene.settle_extra_anchors):
        return True
    return has("获得道具") and (has("继续") or any(t == "OK" for t in texts))


def _branch_loading(scene, items, texts, has, relogin_phrases):
    """1) 加载/过场：只等待（三处同形）。"""
    if has("请耐心等待") or has("健康游戏忠告"):
        return state_for_branch(scene, "loading"), {}
    return None


def _branch_level_gate(scene, items, texts, has, relogin_phrases):
    """1.5) 「需要 130 级」限制弹窗（须在活动/终始之战等宽松分支之前判定）。"""
    if _is_level_gate(texts):
        return state_for_branch(scene, "level_gate"), {}
    return None


def _branch_relogin(scene, items, texts, has, relogin_phrases):
    """2) 换日重进：整句匹配（绝不宽匹配）；额外候选来自识别参数的 ``relogin_text``。"""
    for p in list(relogin_phrases) + list(DEFAULT_RELOGIN):
        if p and any(p == t or p in t for t in texts):
            return state_for_branch(scene, "relogin"), {"phrase": p}
    return None


def _branch_no_entry(scene, items, texts, has, relogin_phrases):
    """2.9) ★#87 五重★ 点【挑战】被拒绝：「当前不满足出战条件」弹窗（**整句**判据）。

    真机帧 debug/wc448_popup_ready.png。旧实现判 unknown ⇒ 只能等 unknown/no_progress
    兜底收工（慢且原因含糊）；判成已知页，giveup 才能立刻带原因（「门票不够了」）收工。
    """
    if scene.no_entry_text and scene.no_entry_text in "".join(texts):
        return state_for_branch(scene, "no_entry"), {}
    return None


def _branch_battle(scene, items, texts, has, relogin_phrases):
    """3) 战斗中。两种形态都是**场景数据**，不是两份判据：

    · 缺省（幻想 / 深渊）：底部条带「时间 mm:ss」+「分数 N」。位置（``_BOTTOM_Y``）与格式
      双限定 —— 结算页上/中部的「最长滞空时间6秒」「战斗分数」不会命中；
    · ``battle_direct_hud``（五重，#74）：位置无关的 :func:`is_battle_hud`。真机A 的 HUD
      是**一个合并框**（'时间 29:30 分数 38629797530'），旧的「三个独立文本框」判据判 unknown。

    两条腿都用**唯一共享真源** :func:`is_battle_hud` 兜底（#107 多视觉特征；#118 给
    幻想/深渊补上）—— ★这正是本票要保住的东西★：一个修复必须同时惠及三个场景。
    """
    battle_state = state_for_branch(scene, "battle")
    if scene.battle_direct_hud:
        if is_battle_hud(items):
            return battle_state, {}
        return None
    btexts = [t.strip() for t in _bottom_texts(items) if t.strip()]
    time_ok = any(_TIME_RE.search(t) for t in btexts) or (
        any(t == "时间" for t in btexts) and any(_HHMM_RE.match(t) for t in btexts)
    )
    score_ok = any(t.startswith("分数") for t in btexts)
    if time_ok and score_ok:
        return battle_state, {}
    # ★#118 修「判据两写」★ HUD 被 toast 遮挡时（真机 wuchong_hud_occluded.png）主判据失效；
    #   走**唯一共享真源** is_battle_hud（它带「多视觉特征」兜底，#107）。
    #   ★但必须排除结算锚点★：结算页上方也有「时间/分数」字样与伤害数字，不能判成战斗。
    if not _settle_like(texts, has, scene) and is_battle_hud(items):
        return battle_state, {"hud_fallback": True}
    return None


def _branch_quest_clear(scene, items, texts, has, relogin_phrases):
    """3.5) ★#107 五重★ 过关演出「QUEST CLEAR」：boss 已倒地、之后才进结算页。

    演出帧的 HUD 数字被艺术字盖住、OCR 读不出「时间/分数」⇒ 旧实现落到 unknown，
    每场灌 3-5 帧（ADR 0005 之后不再按帧数收工，迷路只看连续秒数；这里仍归 battle，
    是为了让这一帧不落进迷路计时）。
    语义上这一场还在收尾、紧接着就是结算 ⇒ 归 battle（detail 带 ``clearing``）。
    """
    if not scene.quest_clear:
        return None
    if has("QUEST CLEAR") or (has("QUEST") and has("CLEAR")):
        return state_for_branch(scene, "battle"), {"clearing": True}
    return None


def _branch_lord_list(scene, items, texts, has, relogin_phrases):
    """4) ★#56 五重★ 领主战/降临讨伐列表页（**必须排在 main_city 之前**）。

    现场：列表页顶部有「活动进行中！」+ 页签「领主战」→ 旧的宽松主城判据把列表页误判成
    主城 ⇒ ``WuchongLordState`` 永不命中 ⇒ 在列表页反复点「领主战」死循环。
    列表页**独有**锚点：``更新列表`` / 首行「通过房间号码参加」（两个页签都在）。
    """
    if any(has(x) for x in scene.lord_list_all):
        return state_for_branch(scene, "lord_list"), {}
    if any(has(x) for x in scene.lord_list_tabs) and any(
        has(x) for x in scene.lord_list_rows
    ):
        return state_for_branch(scene, "lord_list"), {}
    return None


def _branch_main_city(scene, items, texts, has, relogin_phrases):
    """4/5) 主城（#63：共享的「主城**独有**锚点 ≥2」判据，绝不各自复制）。"""
    if is_main_city_texts(texts):
        return state_for_branch(scene, "main_city"), {"anchors": main_city_hits(texts)}
    return None


def _branch_activity(scene, items, texts, has, relogin_phrases):
    """5/6) 活动页（三处同形）。"""
    if has("亲爱的冒险者") or has("这是今天的推荐任务"):
        return state_for_branch(scene, "activity"), {}
    return None


def _branch_zhongshi(scene, items, texts, has, relogin_phrases):
    """6) 终始之战列表（三个二级页签**任一整串在场**；页签是数据，不是写死的三连）。

    info 带上 ``tabs``（搜索顺序）：排障时一眼看出该场景认的是哪三个页签。
    """
    tabs = tuple(scene.zhongshi_tabs)
    if (has("终始之战") or has("BATTLE OF ORIGINS")) and any(t in tabs for t in texts):
        return state_for_branch(scene, "zhongshi"), {"tabs": list(tabs)}
    return None


def _branch_recruit_dialog(scene, items, texts, has, relogin_phrases):
    """7/9) 招募方式弹窗（招募方式 + 开始招募；幻想/五重同形）。"""
    if has("招募方式") and has("开始招募"):
        return state_for_branch(scene, "recruit_dialog"), {}
    return None


def _branch_coop_room(scene, items, texts, has, relogin_phrases):
    """8/10) 共斗房间页（有房间号码，或 招募+复制）。

    ★状态名按场景★：幻想 = ``phantom_coop_room``，五重 = ``wuchong_room``
    （``SceneConfig.state_names`` 覆盖；深渊根本没有这个分支）。
    """
    if has("房间号码") or (has("招募") and has("复制")):
        return state_for_branch(scene, "coop_room"), {"recruited": not has("未进行招募")}
    return None


def _branch_party(scene, items, texts, has, relogin_phrases):
    """9/7) 单人编队页（★「挑战」只认唯一共享源 :func:`has_challenge_page_text`★）。

    ★#112★ ``挑战`` / ``挑战→`` 两种**稳定**渲染都算（真机 8/17 帧带箭头）；旧写法
    ``any(t == "挑战" ...)`` 逐字相等 ⇒ 带箭头的那一半帧判不出编队页 ⇒ 走错分支。
    ★状态名按场景★：幻想/深渊 = ``*_solo_team``，五重 = ``wuchong_team``（state_names）。
    """
    party = (
        any(re.search(r"Party\s*[A-Za-z]", t) for t in texts)
        or any(t == "SET 1" for t in texts)
        or has("SET编辑")
    )
    if party and has_challenge_page_text(texts):
        return state_for_branch(scene, "party"), {}
    return None


def _branch_mode(scene, items, texts, has, relogin_phrases):
    """8) ★#116 五重★ 模式选择页（单人游戏 / 多人游戏）。

    ★页判据是「或」是**正确**的★：两个模式卡同屏，页面就是模式页；「只点自己」由节点识别
    （And 自己那张卡的标题串）+ 点击位置判据承担 —— 页判据 / 识别门 / 点击判据是三件事。
    """
    if any(has(x) for x in scene.mode_anchors):
        return state_for_branch(scene, "mode"), {}
    return None


def _branch_detail(scene, items, texts, has, relogin_phrases):
    """11) ★#56 五重★ 详情页（五重决战·超级；**排在 team/mode 之后** —— 最宽松）。

    编队页也含「五重决战」+「战斗」（卡片上的模式徽标），故必须先判编队页；
    detail / mode 页都没有 SET / 挑战。
    """
    if any(has(x) for x in scene.detail_titles) and any(
        has(x) for x in scene.detail_markers
    ):
        return state_for_branch(scene, "detail"), {}
    return None


def _branch_settle(scene, items, texts, has, relogin_phrases):
    """10/12) 结算 / 奖励页（**先于 hub/main**；五重多两个锚点：返回房间 / 解散）。"""
    if _is_settle(scene, texts, has):
        return state_for_branch(scene, "settle"), {}
    return None


def _branch_hub(scene, items, texts, has, relogin_phrases):
    """11/9) 活动入口（hub）—— 场景判据不同，收敛到 ``SceneConfig.hub_match``。"""
    if scene.hub_match is not None and scene.hub_match(has, texts):
        return state_for_branch(scene, "hub"), {}
    return None


def _branch_main(scene, items, texts, has, relogin_phrases):
    """12/10) 关卡选择页（main）—— 同上，``SceneConfig.main_match``。"""
    if scene.main_match is not None and scene.main_match(has, texts):
        return state_for_branch(scene, "main"), {}
    return None


#: ★唯一落点★ 分支名 → 纯函数。``SceneConfig.classify_order`` 只能从这里选名字。
CLASSIFY_BRANCHES: dict[str, Callable[..., tuple | None]] = {
    "loading": _branch_loading,
    "level_gate": _branch_level_gate,
    "relogin": _branch_relogin,
    "no_entry": _branch_no_entry,
    "battle": _branch_battle,
    "quest_clear": _branch_quest_clear,
    "lord_list": _branch_lord_list,
    "main_city": _branch_main_city,
    "activity": _branch_activity,
    "zhongshi": _branch_zhongshi,
    "recruit_dialog": _branch_recruit_dialog,
    "coop_room": _branch_coop_room,
    "party": _branch_party,
    "mode": _branch_mode,
    "detail": _branch_detail,
    "settle": _branch_settle,
    "hub": _branch_hub,
    "main": _branch_main,
}

# 分支表与状态名表必须是同一套名字（少一个 = 某分支永远拼不出状态）。
assert set(CLASSIFY_BRANCHES) == set(_BRANCH_STATE_SUFFIX), (
    f"分支表 {sorted(CLASSIFY_BRANCHES)} 与状态名表 {sorted(_BRANCH_STATE_SUFFIX)} 不一致"
)


def classify(scene: SceneConfig, items, relogin_phrases=()):
    """把全屏 OCR 项分类成画面名。返回 ``(state, info)``。★唯一一份实现（#119）★

    ``items`` = ``[(text, box720), ...]``；``relogin_phrases`` = 场景额外的「换日重进」整句候选。
    分支顺序来自 ``scene.classify_order``（数据），判据来自 :data:`CLASSIFY_BRANCHES`（唯一落点）。
    抽取前 core / abyss / wuchong 三份 classify 的分支与顺序逐条对账保留，见票 #119 的评论。
    """
    items = [(t or "", b) for t, b in (items or []) if (t or "").strip() or b]
    texts = [(t or "").strip() for t, _ in items if (t or "").strip()]

    def has(sub):
        return any(sub in t for t in texts)

    for branch in scene.classify_order:
        hit = CLASSIFY_BRANCHES[branch](scene, items, texts, has, relogin_phrases)
        if hit is not None:
            return hit
    return "unknown", {}


def parse_stage(scene: SceneConfig, items):
    """从关卡选择页卡片里解析「第N关」的 N；找不到返回 None。"""
    for t, _b in items or []:
        m = scene.stage_re.search(t or "")
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# 进度账本 / 会话观察
# ---------------------------------------------------------------------------
def stage_key(scene: SceneConfig, set_no, stage_no):
    """账本 key：``{scope}/set/{套号}/stage/{关号}``。"""
    return f"{scene.scene}/set/{int(set_no)}/stage/{int(stage_no)}"


def set_done_key(scene: SceneConfig, set_no):
    """账本 key：某套「完整打通」的显式标记 ``{scope}/set/{套号}/completed``。"""
    return f"{scene.scene}/set/{int(set_no)}/completed"


def run_done_key(scene: SceneConfig):
    """「本轮已正常收工」标记 key。"""
    return f"{scene.scene}/run/completed"


def scan_sets(scene: SceneConfig):
    """从账本读出 ``{套号: 该套已完成的最大关号}``。"""
    sets: dict = {}
    for k in ledger.scope(f"{scene.scene}/set"):
        m = re.search(r"/set/(\d+)/stage/(\d+)$", k)
        if not m:
            continue
        s, st = int(m.group(1)), int(m.group(2))
        if st > sets.get(s, 0):
            sets[s] = st
    return sets


def scan_completed_sets(scene: SceneConfig):
    """从账本读出「已完成的套号」集合（显式标记 ∪ 记满 max_stages 关）。"""
    done: set = set()
    marker_re = re.compile(r"/set/(\d+)/completed$")
    for k in ledger.scope(f"{scene.scene}/set"):
        m = marker_re.search(k)
        if m:
            done.add(int(m.group(1)))
    for s, st in scan_sets(scene).items():
        if st >= scene.max_stages:
            done.add(s)
    return done


def recover_counters(scene: SceneConfig):
    """用账本重建会话计数器（跨重开恢复的核心）。"""
    sess = session(scene)
    lk = lock(scene)
    sets = scan_sets(scene)
    completed = len(scan_completed_sets(scene))
    cur = completed + 1
    max_done = sets.get(cur, 0)
    total = len(ledger.scope(f"{scene.scene}/set"))
    with lk:
        sess["completed_sets"] = completed
        sess["cur_set"] = cur
        sess["max_done"] = max_done
        sess["total_marks"] = total
    return completed, cur, max_done, total


def read_target(scene: SceneConfig, param):
    try:
        n = int(param.get("target_sets"))
    except (TypeError, ValueError):
        n = scene.default_target_sets
    return max(1, n)


def read_stage_cap(scene: SceneConfig, param) -> int:
    """解析选项「打到第几关以后放弃」→ stage_cap。

    · 缺省 / 非法 / <=0 → 0 = **不限制**（保持旧行为，默认值）；
    · 合法值夹到 1..max_stages，防止越界。
    """
    try:
        n = int(param.get("stage_cap"))
    except (TypeError, ValueError):
        n = DEFAULT_STAGE_CAP
    if n <= 0:
        return 0
    return min(n, scene.max_stages)


def set_stage_cap(scene: SceneConfig, param) -> int:
    """把识别参数里的 stage_cap 写进会话（仅在参数确实带了该键时更新）。

    ★只在带键时更新★：只有被选项覆盖的节点才带 stage_cap；其余节点若也把会话 cap
    归零，就会在几帧之内把上限抹掉。
    """
    sess = session(scene)
    if "stage_cap" not in param:
        with lock(scene):
            return sess["stage_cap"]
    cap = read_stage_cap(scene, param)
    with lock(scene):
        changed = sess["stage_cap"] != cap
        sess["stage_cap"] = cap
    if changed:
        if cap:
            print(f"[{scene.log_tag}] 关卡上限 = 第 {cap} 关（打到第 {cap} 关打完就收工）")
        else:
            print(f"[{scene.log_tag}] 关卡上限 = 不限制")
    return cap


def read_mode(param) -> str:
    """收工模式："single"（默认）或 "batch"。"""
    m = param.get("mode")
    if isinstance(m, str) and m.strip().lower() == "batch":
        return "batch"
    return "single"


def set_target(scene: SceneConfig, param):
    """把 agent 取到的目标套数写进会话（默认 scene.default_target_sets）。"""
    n = read_target(scene, param)
    sess = session(scene)
    with lock(scene):
        changed = sess["target_sets"] != n
        sess["target_sets"] = n
    if changed:
        print(f"[{scene.log_tag}] 目标套数 = {n}（一整套 = {scene.max_stages} 关）")
    return n


def mark_run_done(scene: SceneConfig):
    """写「本轮已收工」标记：下一次新任务据此清账，从头开始一套新的。"""
    key = run_done_key(scene)
    try:
        if ledger.mark_done(key):
            print(f"[{scene.log_tag}] 写入收工标记 {key}")
    except Exception as exc:  # noqa: BLE001
        print(f"[{scene.log_tag}] 写收工标记失败：{exc}")


def sync_task(scene: SceneConfig, task_id):
    """task_id 变化 = 新一轮任务（跨重开恢复：有收工标记才清账）。"""
    if task_id is None:
        return
    sess = session(scene)
    lk = lock(scene)
    with lk:
        if sess["task_id"] == task_id:
            return
        sess["task_id"] = task_id
        sess["cur_stage"] = None
        sess["in_fight"] = False
        sess["start_ts"] = time.monotonic()
        sess["last_progress_ts"] = time.monotonic()
        # ★ADR 0005★ 迷路时钟随新任务归零（原累计帧数计数器在此清零）。
        sess["lost"].reset()
        sess["last_state"] = None
        sess["last_observe_ts"] = 0.0
        sess["tab_index"] = 0
        sess["wait_count"] = 0
        sess["target_sets"] = scene.default_target_sets
        # ★接管复位★：首次观察基准 / 会话进度 / 关卡上限都按新任务重置。
        sess["session_max_done"] = 0
        sess["joined_stage"] = None
        sess["stage_cap"] = DEFAULT_STAGE_CAP
        # ★共斗房计时复位（#30）★。
        sess["coop_room_first_ts"] = 0.0

    try:
        if ledger.is_done(run_done_key(scene)):
            n = ledger.reset(scene.scene)
            print(
                f"[{scene.log_tag}] 新任务 task_id={task_id}：上一轮已收工，"
                f"清空 {scene.scene} 账本（{n} 条），从第 1 套开始"
            )
        else:
            print(f"[{scene.log_tag}] 新任务 task_id={task_id}：未发现收工标记，保留账本按进度继续")
    except Exception as exc:  # noqa: BLE001
        print(f"[{scene.log_tag}] 账本检查失败：{exc}")

    completed, cur, max_done, total = recover_counters(scene)
    print(
        f"[{scene.log_tag}] 账本恢复：已完成 {completed} 套，当前第 {cur} 套，"
        f"套内已到第 {max_done} 关（账本共 {total} 笔）"
    )
    # ★#12★ 新任务开始 → 用户可见进度行「开始（共 15 关）」。
    #   progress=None（缺省 / classify-only 场景）时 notify_progress 立即返回，行为不变。
    notify_progress(scene, "start", scene.max_stages)


def _current_set_recorded_progress(scene: SceneConfig, cur_set=None):
    """重置判据用：**本次任务会话**在当前套内实际完成的最大关号（只看 session_max_done）。

    （``cur_set`` 仅为兼容旧调用签名保留，判据已与套号无关。）
    """
    with lock(scene):
        return session(scene)["session_max_done"]


def handle_possible_reset(scene: SceneConfig, n):
    """画面回到「第 1 关」时，判定是否发生【进度被游戏重置】，并按套作废账目。

    判据（重置 vs 正常进入下一套 / 中途接管，见抽取前注释）：只认**本次任务会话**落账的
    ``session_max_done``；接管首帧（进度=0）绝不判重置、绝不清账。命中后只清当前套。
    返回 True 表示本帧判定为重置。
    """
    sess = session(scene)
    lk = lock(scene)
    with lk:
        cur_set = sess["cur_set"]
    progress = _current_set_recorded_progress(scene)
    if progress < 2:
        return False
    try:
        cleared = ledger.reset(f"{scene.scene}/set/{int(cur_set)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[{scene.log_tag}] 重置清账失败：{exc}")
        return False
    with lk:
        sess["max_done"] = 0
        sess["session_max_done"] = 0
        sess["cur_stage"] = n
        sess["total_marks"] = max(0, sess["total_marks"] - cleared)
        cs = sess["completed_sets"]
        tgt = sess["target_sets"]
    print(
        f"[{scene.log_tag}] ⚠ 检测到进度重置：第 {cur_set} 套本次已打到第 {progress} 关，"
        f"但画面回到第 1 关 → 作废本套已记 {cleared} 笔 "
        f"({scene.scene}/set/{cur_set}/*)，从第 1 关重新开始"
        f"（不动已完成套；已完成 {cs} 套，目标 {tgt} 套）"
    )
    return True


def observe(scene: SceneConfig, state, info, items):
    """按帧更新会话状态 / 账本（同一帧同一状态只记一次）。★判据与抽取前逐字一致★。"""
    sess = session(scene)
    lk = lock(scene)
    sp = scene.state_prefix
    now = time.monotonic()
    with lk:
        changed = state != sess["last_state"]
        stale = (now - sess["last_observe_ts"]) > 1.2
        if not changed and not stale:
            return
        sess["last_observe_ts"] = now
        sess["last_state"] = state

    # ★ADR 0005 / #76★ 「迷路」看**连续**多久认不出，不看累计多少帧：
    #   每处理一帧就喂一次时钟（进入 unknown 打点 / 命中任一已知页清点）。
    #   位置必须在去重守卫之后、各状态分支之前 —— 分支里的 early return 不能漏掉
    #   「离开 unknown 要清点」这一半（否则钟会一直跑到收工）。
    with lk:
        sess["lost"].observe(state, now, in_fight=sess["in_fight"])

    # ★共斗房停留计时（#30 / #47）★：进入共斗房 / 招募弹窗即开始计时；离开即清零。
    #   规则本身是**场景相关**的（幻想连战的协力关才有共斗房），收敛到 scene.coop_clock；
    #   核心只负责在「去重守卫之后、状态处理之前」按原顺序调用它。
    #   ★#47 修正★：只有真正离开的房间状态才清零（scene.coop_leave_states）；点「挑战」后的
    #   loading / unknown 过渡帧保持时钟不动（见 phantom 侧的 coop_clock 注释）。
    if scene.coop:
        scene.coop_clock(scene, state, sess, now)

    # ★「当前第几关」必须在【两条路径】上都解析★（关卡选择页 + 单人编队页）。
    if state in (f"{sp}_main", f"{sp}_solo_team"):
        n = parse_stage(scene, items)
        first_frame = False
        with lk:
            if n is not None:
                # ★首次观察基准★：本次任务第一次看到关卡页 → 记下画面关号，本帧不做重置判定。
                if sess["joined_stage"] is None:
                    sess["joined_stage"] = n
                    first_frame = True
                if sess["cur_stage"] != n:
                    where = "关卡选择页" if state == f"{sp}_main" else "单人编队页"
                    print(f"[{scene.log_tag}] {where}：当前第 {n} 关")
                sess["cur_stage"] = n
        if first_frame:
            print(
                f"[{scene.log_tag}] ★首次观察基准：画面第 {n} 关★（中途接管以画面为准，"
                f"不拿旧账本纠正；本任务会话进度从 0 起算）"
            )
            return
        # ★进度重置检测★：画面回到第 1 关，而【本次任务会话】在本套已实际打到更靠后的关号。
        if n == 1:
            handle_possible_reset(scene, n)
        return

    if state == f"{sp}_battle":
        with lk:
            if not sess["in_fight"]:
                print(f"[{scene.log_tag}] 进入战斗")
            sess["in_fight"] = True
        return

    if state == f"{sp}_settle":
        with lk:
            cur = sess["cur_stage"]
            in_fight = sess["in_fight"]
            cur_set = sess["cur_set"]
        if cur is not None:
            newly = False
            try:
                newly = ledger.mark_done(stage_key(scene, cur_set, cur))
            except Exception as exc:  # noqa: BLE001
                print(f"[{scene.log_tag}] 记账失败：{exc}")
            finished_set = False
            with lk:
                if newly:
                    sess["total_marks"] += 1
                    sess["max_done"] = max(sess["max_done"], cur)
                # ★会话进度★：只要本次任务观察到本关结算，就记入 session_max_done。
                sess["session_max_done"] = max(sess["session_max_done"], cur)
                sess["last_progress_ts"] = now
                sess["in_fight"] = False
                if cur >= scene.max_stages:
                    # 第 N 关 = 一整套结束。清掉 cur_stage，防止同一结算页的后续帧错记。
                    sess["cur_stage"] = None
                    if newly and in_fight:
                        # ★显式写「本套完成」标记★：只有最后一关结算且确实在战斗中完成才写。
                        try:
                            if ledger.mark_done(set_done_key(scene, cur_set)):
                                sess["total_marks"] += 1
                        except Exception as exc:  # noqa: BLE001
                            print(f"[{scene.log_tag}] 写套完成标记失败：{exc}")
                        sess["completed_sets"] += 1
                        sess["cur_set"] = sess["completed_sets"] + 1
                        sess["max_done"] = 0
                        sess["session_max_done"] = 0
                        finished_set = True
                cs = sess["completed_sets"]
                tgt = sess["target_sets"]
                mx = sess["max_done"]
            # ★#12★ 用户可见进度：**该关结算记账成功**（``phantom/stage/k`` 已落盘）才报一步。
            #   ★位置就是口径★：必须在 ``ledger.mark_done`` 之后 —— 记账失败（异常）或
            #   重复结算帧（newly=False）都不报；``cur`` 是**真实关号**（套内第 k 关），
            #   换套的「第 j/M 套」由场景钩子按 ``cur_set`` / ``target_sets`` 换。
            #   progress=None（缺省 / 非真状态机场景）时这里一个字节都不写。
            if newly:
                notify_progress(scene, "step", cur, cur_set, tgt)
            if finished_set:
                print(f"[{scene.log_tag}] 第 {cs} 套完成（一整套 {scene.max_stages} 关）")
                if cs < tgt:
                    print(
                        f"[{scene.log_tag}] 第 {cs} 套完成，开始第 {cs + 1} 套"
                        f"（目标 {tgt} 套，未达目标不收工）"
                    )
                else:
                    print(f"[{scene.log_tag}] 已完成 {cs} 套（达到目标 {tgt} 套）→ 待回到关卡选择页收工")
            elif newly and in_fight:
                print(f"[{scene.log_tag}] 第 {cur_set} 套·第 {cur} 关完成（已记账；套内最高第 {mx} 关）")
        return

    # ``state == "unknown"`` 在这里**不再计数**（ADR 0005 已删掉累计帧数）：
    # 迷路时钟在函数开头已随每一帧喂过，unknown 帧落到函数末尾即可。


# ---------------------------------------------------------------------------
# 自定义识别 / 动作 —— 工厂函数（按 scene 生成类，避免复制）
# ---------------------------------------------------------------------------
def pick(items, patterns, roi=None, prefer=None):
    """在 OCR 项里找第一个匹配任一正则的按钮框（可选 roi 限定中心、prefer 取上/下）。"""
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


def make_state_reco(scene: SceneConfig, ocr, click_box=None):
    """生成 ``{Prefix}StateRecognition``（custom_recognition="{scene}_state"）。"""
    sp = scene.state_prefix
    tag = f"[{scene.log_tag}]"

    class StateReco(CustomRecognition):
        def analyze(self, context, argv):
            param = read_param(argv)
            want = (param.get("state") or "").strip()
            ocr_entry = param.get("ocr_entry") or "OcrTask"
            relogin_text = param.get("relogin_text")
            phrases = [str(relogin_text)] if relogin_text else []

            items = ocr(context, argv.image, ocr_entry)
            sync_task(scene, getattr(argv.task_detail, "task_id", None))
            set_stage_cap(scene, param)
            state, info = classify(scene, items, relogin_phrases=phrases)
            observe(scene, state, info, items)

            if state == f"{sp}_level_required":
                print(
                    f"{tag} 检测到『需要130级』限制："
                    "玩家等级达到130后，解锁幻想连战与深渊连战 → "
                    "本账号无法进入终结之战/幻想连战，任务停止（StopTask）"
                )

            if want and state != want:
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={"want": want, "state": state, **info}
                )
            if want == f"{sp}_coop_room" and param.get("need_recruit"):
                if info.get("recruited"):
                    return CustomRecognition.AnalyzeResult(
                        box=None, detail={"want": want, "state": state, "recruited": True}
                    )
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"state": state, **info}
            )

    StateReco.__name__ = f"{scene.class_prefix}StateRecognition"
    StateReco.__qualname__ = StateReco.__name__
    return StateReco


def make_done_reco(scene: SceneConfig, ocr, click_box=None):
    """生成 ``{Prefix}DoneRecognition``（出口：账本已完成目标套数且回到关卡页 + 关卡上限）。"""
    sp = scene.state_prefix
    tag = f"[{scene.log_tag}]"

    class DoneReco(CustomRecognition):
        def analyze(self, context, argv):
            param = read_param(argv)
            items = ocr(context, argv.image, param.get("ocr_entry") or "OcrTask")
            sync_task(scene, getattr(argv.task_detail, "task_id", None))
            # ★必须先 _sync_task 再 _set_target★：_sync_task 换任务时会把 target 复位为默认。
            target = set_target(scene, param)
            mode = read_mode(param)
            state, info = classify(scene, items)
            observe(scene, state, info, items)
            sess = session(scene)
            with lock(scene):
                cs = sess["completed_sets"]
                cap = sess["stage_cap"]
                session_mx = sess["session_max_done"]
            if state == f"{sp}_main" and cs >= target:
                # batch 模式：不写收工标记（保留账本供批量指挥官按已完成套数续跑/统计）。
                if mode != "batch":
                    mark_run_done(scene)
                print(
                    f"{tag} 已完成 {cs} 套（≥目标 {target} 套）且回到关卡选择页 → "
                    f"{'回批量指挥官' if mode == 'batch' else '收工'}"
                )
                # ★#12★ 收工进度行：reason 复用既有文案（已完成 X 套 / 目标 Y 套）。
                notify_progress(scene, "done", f"已完成 {cs} 套（目标 {target} 套）")
                return CustomRecognition.AnalyzeResult(
                    box=[0, 0, 0, 0],
                    detail={"done": True, "completed_sets": cs, "target_sets": target, "mode": mode},
                )
            # ★关卡上限出口★：本次会话已实际打到（完成）第 cap 关 → 在安全画面优雅收工。
            if cap > 0 and session_mx >= cap and state in tuple(scene.cap_stop_states):
                if mode == "batch":
                    # 回一次指挥官再走指挥官的收工节点 SpecialBatchStop（避免未满套被反复重选）。
                    try:
                        context.override_next(scene.dispatch_node, ["SpecialBatchStop"])
                    except Exception as exc:  # noqa: BLE001
                        print(f"{tag} 关卡上限设置收工 next 失败：{exc}")
                else:
                    mark_run_done(scene)
                print(
                    f"{tag} ★已达关卡上限：第 {cap} 关已打完（本次会话进度 {session_mx}）"
                    f"→ {'回指挥官优雅收工' if mode == 'batch' else '优雅收工'}"
                    f"（非 giveup 兜底；state={state}）"
                )
                # ★#12★ 收工进度行：reason 复用这一条既有文案的「已达关卡上限：第 N 关已打完」。
                notify_progress(scene, "done", f"已达关卡上限：第 {cap} 关已打完")
                return CustomRecognition.AnalyzeResult(
                    box=[0, 0, 0, 0],
                    detail={
                        "done": True,
                        "reason": "stage_cap",
                        "stage_cap": cap,
                        "session_max_done": session_mx,
                        "completed_sets": cs,
                        "state": state,
                        "mode": mode,
                    },
                )
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"done": False, "completed_sets": cs, "target_sets": target, "mode": mode},
            )

    DoneReco.__name__ = f"{scene.class_prefix}DoneRecognition"
    DoneReco.__qualname__ = DoneReco.__name__
    return DoneReco


def make_giveup_reco(scene: SceneConfig, ocr, click_box=None):
    """生成 ``{Prefix}GiveUpRecognition``（兜底出口 + 共斗房有界出口 #30/#47）。"""
    sp = scene.state_prefix
    tag = f"[{scene.log_tag}]"

    class GiveUpReco(CustomRecognition):
        def analyze(self, context, argv):
            param = read_param(argv)
            max_task_sec = float(param.get("max_task_sec") or 7200)
            # ★ADR 0005★ 迷路闸门改用**连续秒数**（旧的 `unknown_limit` 帧数已删除）。
            #   兼容：override 里还留着 unknown_limit 时忽略并警告一次，绝不静默恢复计数。
            warn_stale_frame_limit(scene.scene, tag, param)
            lost_sec = float(param.get("lost_sec") or DEFAULT_LOST_SEC)
            no_progress_sec = float(param.get("no_progress_sec") or 900)
            coop_room_sec = float(param.get("coop_room_sec") or DEFAULT_COOP_ROOM_SEC)

            items = ocr(context, argv.image, param.get("ocr_entry") or "OcrTask")
            sync_task(scene, getattr(argv.task_detail, "task_id", None))
            target = set_target(scene, param)
            mode = read_mode(param)
            state, info = classify(scene, items)
            observe(scene, state, info, items)

            sess = session(scene)
            now = time.monotonic()
            with lock(scene):
                start = sess["start_ts"] or now
                last = sess["last_progress_ts"] or now
                lost = sess["lost"]
                # 判定与原因文案共用**同一个**连续秒数快照（避免两次取值说两句话）。
                lost_seconds = lost.seconds_lost(now)
                last_known = lost.last_known
                cs = sess["completed_sets"]
                mx = sess["max_done"]
                total = sess["total_marks"]
                coop_first = sess["coop_room_first_ts"]

            done = cs >= target
            reason = None
            # ★共斗房出口（#30 / #47）★：停留超过 coop_room_sec 仍未开战 → 有界收工。
            #   ★#47★：时钟只在【真正离开房间】时清零，点「挑战」后的 loading 过渡帧不清零。
            if (
                coop_first
                and state in tuple(scene.coop_room_states)
                and (now - coop_first) > coop_room_sec
            ):
                reason = (
                    f"共斗房停留 {now - coop_first:.0f} 秒 仍未能开战"
                    f"（未招募到队友 / 挑战不可用）"
                )
            # ★跑够目标套数的【正常收工】由 Done 负责★：本兜底只在 done 且长时间回不到关卡页时兜底。
            elif done and (now - last) > 90 and state not in (
                f"{sp}_battle",
                f"{sp}_settle",
            ):
                reason = f"已完成 {cs} 套且 90s 未回到关卡选择页"
            elif total > (target + 2) * scene.max_stages:
                reason = f"关卡记账数异常（{total}）"
            elif (now - start) > max_task_sec:
                reason = f"总时长超过 {max_task_sec:.0f}s"
            elif lost_seconds >= lost_sec:
                # ★ADR 0005★ 迷路 = 连续 lost_sec 秒认不出画面（不是累计帧数）。
                reason = lost_reason(lost_seconds, last_known)
            elif (now - last) > (no_progress_sec if (cs or mx) else ZERO_PROGRESS_SEC):
                # ★#118 推广★ 去掉旧的 `cs > 0 or mx > 0` 门：幻想/特殊副本「一场都没完成」时
                #   它恒为假 ⇒ 永不收工（真机：空队伍打幻想连战，20 秒一轮无限重进）。
                #   零进度改用更短窗口，原因要能区分两种情形。
                if cs or mx:
                    reason = f"{no_progress_sec:.0f}s 无新关卡完成"
                else:
                    reason = f"{ZERO_PROGRESS_SEC}s 一场都没有完成（关卡打不过？）"

            if reason:
                # ★batch 模式不写收工标记★：批量任务里幻想的完成由「已完成套数」统计。
                if done and mode != "batch":
                    mark_run_done(scene)
                print(
                    f"{tag} 触发收工兜底：{reason}"
                    f"（state={state} 已完成={cs}套 目标={target}套 mode={mode}）"
                )
                # ★#12★ 收工进度行：reason 就是上面这条兜底文案（逐字复用，不另造口径）。
                notify_progress(scene, "done", reason)
                return CustomRecognition.AnalyzeResult(
                    box=[0, 0, 0, 0],
                    detail={"giveup": True, "reason": reason, "state": state, "mode": mode},
                )
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"giveup": False, "state": state, "mode": mode}
            )

    GiveUpReco.__name__ = f"{scene.class_prefix}GiveUpRecognition"
    GiveUpReco.__qualname__ = GiveUpReco.__name__
    return GiveUpReco


def make_act_action(scene: SceneConfig, ocr, click_box):
    """生成 ``{Prefix}ActAction``（OCR 点按钮本身 + 点后校验画面推进）。"""
    tag = f"[{scene.log_tag}_act]"

    class ActAction(CustomAction):
        def run(self, context, argv):
            param = read_action_param(argv)
            step = param.get("step")
            wait_ms = int(param.get("wait_ms") or 1600)
            expect = list(param.get("expect") or [])

            img0 = grab(context)
            items0 = ocr(context, img0)
            state0, info0 = classify(scene, items0)

            target = None
            if step == "banner":
                target = pick(items0, list(scene.banner_patterns))
            elif step == "tab":
                sess = session(scene)
                with lock(scene):
                    idx = sess["tab_index"] % 3
                order = ["未通关", "已通关", "完成"]
                for off in range(3):
                    name = order[(idx + off) % 3]
                    target = pick(items0, [f"^{name}$"])
                    if target:
                        with lock(scene):
                            sess["tab_index"] = (idx + off + 1) % 3
                        break
            else:
                patterns = list(param.get("what") or [])
                target = pick(
                    items0,
                    patterns,
                    roi=tuple(param["roi"]) if param.get("roi") else None,
                    prefer=param.get("prefer"),
                )

            if target is None:
                print(f"{tag} 未找到按钮（state={state0} step={step} what={param.get('what')}）→ 不点击")
                if expect and state0 not in expect:
                    return True  # 不点，交回分派器等待/换策略
                return True

            text, cx, cy = target
            print(f"{tag} state={state0} 点击按钮 '{text}' @720({int(cx)},{int(cy)}) step={step}")
            click_box(context, cx, cy)
            time.sleep(max(0.2, wait_ms / 1000.0))

            img1 = grab(context)
            items1 = ocr(context, img1)
            state1, _info1 = classify(scene, items1)
            observe(scene, state1, _info1, items1)

            ok = (state1 in expect) if expect else (state1 != state0)
            if not ok:
                print(f"{tag} [!] 校验未通过：点击后 state={state1}，期望 {expect or '画面变化'}（旧 state={state0}）")
            else:
                print(f"{tag} 校验通过：state {state0} -> {state1}")
            return True

    ActAction.__name__ = f"{scene.class_prefix}ActAction"
    ActAction.__qualname__ = ActAction.__name__
    return ActAction


def make_restart_action(scene: SceneConfig, ocr, click_box):
    """生成 ``{Prefix}RestartAction``（强杀重启：OCR 引导回主城；绝不 KeyEvent 4）。"""
    tag = f"[{scene.log_tag}_restart]"

    class RestartAction(CustomAction):
        TAP_720 = {
            "account": (359, 847),   # 1080 (538,1270)
            "title": (347, 1113),    # 1080 (520,1669)
            "nav": (179, 1260),      # 1080 (268,1890)
        }

        def _click_ocr_or(self, context, patterns, fallback):
            img = grab(context)
            items = ocr(context, img)
            t = pick(items, patterns)
            if t:
                print(f"{tag} OCR 命中 '{t[0]}' @720({int(t[1])},{int(t[2])})")
                click_box(context, t[1], t[2])
            else:
                print(f"{tag} 未 OCR 到 {patterns}，退回实测固定点 {fallback}")
                click_box(context, fallback[0], fallback[1])

        def run(self, context, argv):
            param = read_action_param(argv)
            pkg = param.get("pkg") or "com.leiting.wf"

            def sec(name, default):
                try:
                    return max(0.0, float(param.get(name, default)))
                except (TypeError, ValueError):
                    return float(default)

            restart_wait = sec("restart_wait", 35)
            login_wait = sec("login_wait", 20)
            start_wait = sec("start_wait", 35)
            force_stop_wait = sec("force_stop_wait", 3)
            nav_wait = sec("nav_wait", 4)
            ctrl = context.tasker.controller

            try:
                print(f"{tag} 1) 强杀 {pkg}")
                ctrl.post_stop_app(pkg).wait()
                time.sleep(force_stop_wait)
                print(f"{tag} 2) 启动 {pkg}")
                ctrl.post_start_app(pkg).wait()
                time.sleep(restart_wait)

                print(f"{tag} 3) 账号确认页 → 继续游戏")
                self._click_ocr_or(context, [r"^继续游戏$"], self.TAP_720["account"])
                time.sleep(login_wait)

                print(f"{tag} 4) 标题页 → 点击开始")
                self._click_ocr_or(context, [r"^点击开始$"], self.TAP_720["title"])
                time.sleep(start_wait)

                print(f"{tag} 5) 底部导航 → 主城")
                self._click_ocr_or(context, [r"^主城$"], self.TAP_720["nav"])
                time.sleep(nav_wait)
            except Exception as exc:  # noqa: BLE001
                print(f"{tag} 异常：{exc}")
                return False

            # 校验是否回到主城（主城独有锚点 ≥2）
            try:
                img = grab(context)
                items = ocr(context, img)
                city = main_city_hits([t for t, _ in items])
                print(f"{tag} 主城锚点命中 {len(city)} 个：{city}")
            except Exception as exc:  # noqa: BLE001
                print(f"{tag} 主城校验失败：{exc}")
            return True

    RestartAction.__name__ = f"{scene.class_prefix}RestartAction"
    RestartAction.__qualname__ = RestartAction.__name__
    return RestartAction
