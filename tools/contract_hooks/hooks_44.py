# -*- coding: utf-8 -*-
"""#44：混排清单**假完成** —— 跨种类陈旧界面不得记账；切种类先确认中立页。

seam
----
* ``agent/side_impl.py``：``is_neutral_home`` / ``classify_screen``（中立页判定纯函数）、
  ``BatchModeRecognition``（切种类未确认中立页时封锁三个种类分派器）、
  ``SpecialBatchFinishAction``（``record="always"`` 的记账前提 = 本条目自身导航）、
  ``SpecialBatchPlanRecognition``（归位确认 + 无导航种类的明确跳过）。
* ``assets/resource/pipeline/special_dungeon.json``：``SpecialEntry`` 的 #44 声明注释。

诊断（真机 16448 混排实测，本仓库自带的证据）
--------------------------------------------
命令：``--list "碧之女王讨伐,中级,1;猩红巨熊讨伐,中级,1;战阵之宴,-,1;光之迷宫,中级,1;幻想连战,-,1"``
轨迹（``logs/mixed.log``）：::

    [batch] 切换目标：猩红巨熊讨伐 / 中级      # 前两条：真开打、真结算
    [batch] 开打 猩红巨熊讨伐/中级（等待结算计数）
    [batch] 结算完成 猩红巨熊讨伐/中级 第 1/1 次
    [batch] 切换目标：战阵之宴 / -（剩余 1 次）   # ← 没有任何「归位/开打」
    [batch] 结算完成 战阵之宴/- 第 1/1 次        # ← 假完成（实际没打）
    [batch] 切换目标：光之迷宫 / 中级（剩余 1 次）
    [batch] 结算完成 光之迷宫/中级 第 1/1 次     # ← 假完成
    [batch] 切换目标：幻想连战 / -
    [batch] 归位主城，开始刷 幻想连战 / -
    ... PhantomDispatch⇄PhantomWait 循环 ... 追踪 结束 status=timeout

滞留帧（``frames/mixed/f_0088…f_0264``，全部是同一张「猩红巨熊详情页」；战阵之宴/迷宫/
幻想界面从未出现）：OCR 见 ``mixed_scan.txt``。

根因：切种类时指挥官只点一次「主城」就假定已回中立页 ——
``RaidContinueChallenge`` / ``FarmRetry``（均带 ``record="always"``）随后命中了**上一场战斗
结算页上残留的「再次挑战」** → 假记账；幻想那段则停在**陈旧的详情页**上空转到超时。

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``mixed-no-stale-screen-completion`` —— 陈旧结算页的「再次挑战」不得完成下一条：
   切到 raid 后 ``_BATCH_BLOCK_DISPATCH`` 被置位、raid 分派器不命中；
   即便结算动作直接在陈旧帧上被调用，``record="always"`` 也**不点击、不记账**。
2. ``mixed-kind-switch-confirms-neutral`` —— 切条目必须先确认中立页（主城）：
   ``is_neutral_home`` / ``classify_screen`` 的正反例；陈旧详情页（有底导「主城」但无
   三独有锚点）判为 ``other``（封锁分派）；主城帧判为 ``neutral``（放行）；
   phantom 分派器在封锁期不命中、解封后命中（幻想在混排里能正常进入的前提）。
3. ``mixed-raid-unreachable-skipped`` —— 不做导航的战阵之宴在整条清单里从主城到不了 →
   按导航超时**明确跳过并记录原因**（``_BATCH_SKIPPED``），绝不假记账、绝不空转。

★诚实边界★：真机帧（``frames/mixed``）在临时目录、随运行消失；这里内嵌**真机 OCR 与轨迹**
（主城帧 / 详情页帧为随仓帧的逐条 OCR；上一场结算页的「再次挑战」几何来自 ``raid.json``
坑点 4 的真机实测 ``OK[189,1181] / 再次挑战[461,1180]``），不重跑 MAA OCR（那是 verify_* 的活）。

★prove-red★（``python tools\\contract_hooks\\hooks_44.py``）：四处破坏，要求守卫各自变红：
  * 摘掉 ``record="always"`` 的「自身导航」前提 -> 守卫 1 红（陈旧「再次挑战」又假记账）；
  * 摘掉「切种类先确认中立页」判定 -> 守卫 2 红（陈旧界面不再封锁分派）；
  * 摘掉分派器的封锁读取 -> 守卫 2 红（封锁标志形同虚设）；
  * 把 raid 从导航超时种类里去掉 -> 守卫 3 红（战阵之宴不再明确跳过）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：prove-red 子进程用 PYTHONPATH 抢先塞坏副本时仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

_SD = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌；与 tools/frames/、hooks_38/hooks_39 同源）
# ---------------------------------------------------------------------------
#: 主城帧（随仓帧 recover_home.png；主城【独有】锚点三个齐全）——中立页正例。
MAIN_CITY_ITEMS: list[tuple[str, list[int]]] = [
    ("修行之道", [23, 728, 151, 41]),
    ("成长任务", [49, 368, 117, 33]),
    ("当前进度", [369, 928, 60, 20]),
    ("主城", [156, 1245, 45, 28]),
    ("角色", [275, 1244, 47, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1248, 45, 25]),
]
#: 详情页帧（真机 红嫉机兵早期账号详情页；有底部导航「主城」+「推荐编成」+ 行内「战斗」，
#: 但**没有**三个主城独有锚点）——正是幻想滞留的那种陈旧页（frames/mixed/f_0088…）。
DETAIL_ITEMS: list[tuple[str, list[int]]] = [
    ("NEW", [18, 389, 46, 20]),
    ("返回", [30, 1246, 46, 26]),
    ("推荐编成", [55, 530, 97, 30]),
    ("战斗", [88, 501, 29, 16]),
    ("主城", [157, 1248, 44, 25]),
    ("红嫉族机兵", [191, 149, 382, 99]),
    ("降临讨伐", [202, 428, 91, 28]),
    ("红机兵海茵莱特中级", [203, 458, 253, 28]),
    ("角色", [276, 1246, 45, 26]),
    ("商店", [397, 1245, 43, 27]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1248, 45, 25]),
]
#: 上一场战斗的【结算页】残留帧：底部并排「OK / 再次挑战」。
#: 几何来自 raid.json 坑点 4 的真机实测（720）：OK 文字框 [189,1181]、再次挑战 [461,1180]。
SETTLE_RETRY_ITEMS: list[tuple[str, list[int]]] = [
    ("OK", [189, 1181, 70, 40]),
    ("再次挑战", [461, 1180, 120, 40]),
]

#: 混排清单（与真机实测同一份，去掉前两条里的 farm/special 干扰，保留 special -> raid 的切换）。
MIXED_LIST = "猩红巨熊讨伐,中级,1;战阵之宴,-,1"

#: 五条承重短语（#12 硬规则；纯编辑不得丢）。
BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


# ---------------------------------------------------------------------------
# 离线 stub：回放一帧 OCR；记录 override / 点击
# ---------------------------------------------------------------------------
def _rows(items):
    return types.SimpleNamespace(
        all_results=[types.SimpleNamespace(box=list(b), text=t) for t, b in items],
        hit=bool(items),
    )


class _Ctx:
    """回放当前帧的 OCR；只对「忙闲判据」节点给出画面驱动的 hit。"""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.overrides_next: dict = {}
        self.overrides_pipeline: dict = {}
        self.actions: list = []

    def run_recognition(self, entry, image):
        if entry == "OcrTask":
            return _rows(self.items)
        # _batch_busy 会跑这些节点；用画面内容决定「是否还在结算页」。
        if entry in ("SpecialResultContinue", "SpecialResultFallback"):
            hit = any(
                t in ("OK", "继续") or t.startswith("QUESTRESULT")
                for t, _b in self.items
            )
            return types.SimpleNamespace(all_results=[], hit=hit)
        return types.SimpleNamespace(all_results=[], hit=False)

    def run_action(self, *a, **k):
        self.actions.append((a, k))
        return True

    def override_next(self, node, nxt):
        self.overrides_next[node] = list(nxt)

    def override_pipeline(self, ov):
        self.overrides_pipeline.update(ov)

    def get_node_data(self, node):
        return {}

    def get_hit_count(self, node):
        return 0


class _TaskDetail:
    def __init__(self, task_id, entry="SpecialEntry"):
        self.task_id = task_id
        self.entry = entry


class _Argv:
    def __init__(self, image, param, *, task_id=1, entry="SpecialEntry", box=None):
        import json  # noqa: PLC0415

        self.image = image
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        self.custom_action_param = "{}"
        self.task_detail = _TaskDetail(task_id, entry)
        self.box = box


class _Rect:
    """Rect 兼容对象（x/y/w/h），供结算动作取框中心。"""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


def _import_side(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _temp_ledger():
    import progress as ledger  # noqa: PLC0415

    tmp = tempfile.TemporaryDirectory(prefix="wf_hook44_ledger_")
    ledger.set_file(Path(tmp.name) / "progress.json")
    return ledger, tmp


def _drive(rec, items, text, tid, *, entry="SpecialEntry"):
    ctx = _Ctx(items)
    argv = _Argv(items, {"list": text}, task_id=tid, entry=entry)
    res = rec.analyze(ctx, argv)
    return ctx, res


def _settle(si, ledger, record, box):
    """直接驱动一次结算推进动作（模拟 RaidContinueChallenge / FarmRetry 在帧上被调用）。"""
    ctx = _Ctx([])
    argv = _Argv(
        [], {}, task_id=1, box=_Rect(box[0], box[1], box[2], box[3])
    )
    argv.custom_action_param = '{"record": "%s"}' % record
    ok = si.SpecialBatchFinishAction().run(ctx, argv)
    return ok, ctx


# ---------------------------------------------------------------------------
# 守卫 1：陈旧结算页的「再次挑战」不得完成下一条
# ---------------------------------------------------------------------------
def _stale_completion_failures(agent_dir: Path | None = None) -> list[str]:
    si = _import_side(agent_dir)
    import batch_plan as bp  # noqa: PLC0415

    ledger, tmp = _temp_ledger()
    msgs: list[str] = []
    try:
        si.reset_gameover_state()
        rec = si.SpecialBatchPlanRecognition()

        # 1) 第一条（special）在主城上开始。
        ctx1, r1 = _drive(rec, MAIN_CITY_ITEMS, MIXED_LIST, 44001)
        if r1.box is None or si._BATCH_CURRENT is None:
            return ["场景起始不成立：指挥官没有切到第一个目标（猩红巨熊讨伐）"]
        if si._BATCH_CURRENT.dungeon != "猩红巨熊讨伐":
            msgs.append(f"第一条应为 猩红巨熊讨伐，实际 {si._BATCH_CURRENT.dungeon}")

        # 2) 真打一场并结算（镜像 mixed.log 的「结算完成 猩红巨熊 1/1」）。
        si._BATCH_IN_FIGHT = True
        _settle(si, ledger, "in_fight", [461, 1180, 120, 40])
        prefix_special = bp.item_prefix(si._BATCH_CURRENT)
        if bp.count_done(prefix_special) != 1:
            msgs.append("前提不成立：猩红巨熊 未记到 1/1")

        # 3) 切到 raid（战阵之宴）时画面仍是【上一场结算页】的残留「再次挑战」。
        ctx2, r2 = _drive(rec, SETTLE_RETRY_ITEMS, MIXED_LIST, 44001)
        if si._BATCH_CURRENT is None or si._BATCH_CURRENT.dungeon != "战阵之宴":
            msgs.append("未切到 战阵之宴（raid）")
        if not si._BATCH_BLOCK_DISPATCH:
            msgs.append("切种类时画面明确不是主城，却未封锁种类分派（陈旧界面会被别种类碰到）")
        if r2.box is not None and not si._BATCH_NEEDS_HOME:
            msgs.append("陈旧帧上竟已放行开始下一条（应保持归位中）")

        # 3b) raid 分派器在封锁期必须不命中（否则陈旧「再次挑战」会被 RaidDispatch 吃到）。
        bm = si.BatchModeRecognition()
        raid_argv = _Argv([], {"kind": "raid"}, task_id=44001)
        if bm.analyze(_Ctx([]), raid_argv).box is not None:
            msgs.append("封锁期 raid 分派器仍然命中（陈旧界面会被 raid 链动作碰到）")

        # 4) 第二道防线：record="always" 在「未走过自身导航」前不点击、不记账。
        prefix_raid = bp.item_prefix(si._BATCH_CURRENT)
        ok, ctx3 = _settle(si, ledger, "always", [461, 1180, 120, 40])
        if bp.count_done(prefix_raid) != 0:
            msgs.append(
                f"陈旧结算页的『再次挑战』被记为完成（假完成）：raid 账本={bp.count_done(prefix_raid)}"
            )
        if ctx3.actions:
            msgs.append(f"陈旧『再次挑战』被点击了（会重开上一场）：actions={ctx3.actions}")
        if not ok:
            msgs.append("结算动作在陈旧帧上应安全返回 True（不点击、不记账）")

        # 5) 正面：真打过自身导航后，record="always" 正常记账。
        si._BATCH_ITEM_ENGAGED = True
        _settle(si, ledger, "always", [461, 1180, 120, 40])
        if bp.count_done(prefix_raid) != 1:
            msgs.append("走过自身导航后，record=always 竟不记账（把正常 farm/raid 流程打坏）")
    finally:
        tmp.cleanup()
    return msgs


def probe_mixed_no_stale_screen_completion(agent_dir: Path | None = None) -> bool:
    return _stale_completion_failures(agent_dir) == []


# ---------------------------------------------------------------------------
# 守卫 2：切条目必须先确认中立页（主城）；陈旧详情页封锁分派
# ---------------------------------------------------------------------------
def _neutral_switch_failures(agent_dir: Path | None = None) -> list[str]:
    si = _import_side(agent_dir)
    msgs: list[str] = []

    # 纯函数正反例（不碰设备 / 不碰状态）。
    if not si.is_neutral_home(MAIN_CITY_ITEMS):
        msgs.append("主城帧未被判为中立页（三独有锚点判定失效）")
    if si.is_neutral_home(DETAIL_ITEMS):
        msgs.append("详情页（有底导『主城』但无独有锚点）被误判为中立页")
    if si.is_neutral_home(SETTLE_RETRY_ITEMS):
        msgs.append("结算页被误判为中立页")
    if si.classify_screen([]) != "unknown" or si.classify_screen(None) != "unknown":
        msgs.append("读不到文字时应为 unknown（回退旧行为）")
    if si.classify_screen(MAIN_CITY_ITEMS) != "neutral":
        msgs.append("主城帧应为 neutral")
    if si.classify_screen(DETAIL_ITEMS) != "other":
        msgs.append("详情页应为 other（切种类时必须先归位）")

    ledger, tmp = _temp_ledger()
    try:
        si.reset_gameover_state()
        rec = si.SpecialBatchPlanRecognition()

        # 第一条在【陈旧详情页】上切：必须保持归位中 + 封锁分派，绝不开始下一条。
        ctx1, r1 = _drive(rec, DETAIL_ITEMS, MIXED_LIST, 44002)
        if si._BATCH_CURRENT is None or si._BATCH_CURRENT.dungeon != "猩红巨熊讨伐":
            return msgs + ["场景起始不成立：未切到第一条"]
        if not si._BATCH_NEEDS_HOME:
            msgs.append("陈旧详情页上竟已放行开始下一条（未确认中立页）")
        if not si._BATCH_BLOCK_DISPATCH:
            msgs.append("陈旧详情页上未封锁种类分派")
        if r1.detail.get("batch") != "home_retry":
            msgs.append(f"陈旧详情页上应继续归位（home_retry），实际 {r1.detail!r}")

        # phantom 分派器在封锁期不命中、解封后命中（幻想在混排里能正常进入的前提）。
        bm = si.BatchModeRecognition()
        phantom_argv = _Argv([], {"kind": "phantom"}, task_id=44002)
        with si._BATCH_LOCK:
            si._BATCH_MODE = "phantom"
        if bm.analyze(_Ctx([]), phantom_argv).box is not None:
            msgs.append("封锁期 phantom 分派器仍然命中（幻想会在陈旧页上瞎跑）")

        # 回到主城 -> 确认中立页 -> 放行下一条（解除封锁）。
        ctx2, r2 = _drive(rec, MAIN_CITY_ITEMS, MIXED_LIST, 44002)
        if si._BATCH_NEEDS_HOME:
            msgs.append("已回到主城却仍在归位中（中立页未确认）")
        if si._BATCH_BLOCK_DISPATCH:
            msgs.append("已确认中立页却仍封锁分派（下一条永远起不来）")
        if r2.box is None:
            msgs.append("确认中立页后应命中并开始下一条")
        with si._BATCH_LOCK:
            si._BATCH_MODE = "phantom"
        if bm.analyze(_Ctx([]), phantom_argv).box is None:
            msgs.append("解封后 phantom 分派器不命中（幻想进不去）")
    finally:
        tmp.cleanup()
    return msgs


def probe_mixed_kind_switch_confirms_neutral(agent_dir: Path | None = None) -> bool:
    return _neutral_switch_failures(agent_dir) == []


# ---------------------------------------------------------------------------
# 守卫 3：不做导航的战阵之宴在整条清单里明确跳过（原因记录）
# ---------------------------------------------------------------------------
def _raid_skip_failures(agent_dir: Path | None = None) -> list[str]:
    si = _import_side(agent_dir)
    import batch_plan as bp  # noqa: PLC0415

    ledger, tmp = _temp_ledger()
    msgs: list[str] = []
    try:
        si.reset_gameover_state()
        rec = si.SpecialBatchPlanRecognition()

        # 第一条 special 在主城开始并真打结算（让清单前进到 raid）。
        ctx1, r1 = _drive(rec, MAIN_CITY_ITEMS, MIXED_LIST, 44003)
        if r1.box is None or si._BATCH_CURRENT is None:
            return ["场景起始不成立：未切到第一条"]
        si._BATCH_IN_FIGHT = True
        _settle(si, ledger, "in_fight", [461, 1180, 120, 40])
        prefix_special = bp.item_prefix(si._BATCH_CURRENT)

        # 切到 raid 并在主城确认中立页（战阵之宴不做导航 -> 从主城到不了）。
        _drive(rec, SETTLE_RETRY_ITEMS, MIXED_LIST, 44003)   # 陈旧结算页：归位中
        ctx2, r2 = _drive(rec, MAIN_CITY_ITEMS, MIXED_LIST, 44003)  # 主城：放行 raid
        if si._BATCH_CURRENT is None or si._BATCH_CURRENT.kind != "raid":
            msgs.append("未切到 raid 目标（战阵之宴）")
        if si._BATCH_NEEDS_HOME or si._BATCH_BLOCK_DISPATCH:
            msgs.append("主城确认后仍未放行 raid（前提不成立）")

        prefix_raid = bp.item_prefix(si._BATCH_CURRENT)

        # 模拟 raid 导航超时（不做导航 -> 从主城到不了）：指挥官应明确跳过并记录原因。
        with si._BATCH_LOCK:
            si._BATCH_TARGET_START_TS = time.monotonic() - 999.0
        ctx3, r3 = _drive(rec, MAIN_CITY_ITEMS, MIXED_LIST, 44003)

        if any(it.kind == "raid" for it in si._BATCH_ITEMS):
            msgs.append("导航超时后 raid 目标仍在清单里（未跳过 -> 会空转到超时）")
        if not any(("战阵之宴" in s and "跳过" in s) for s in si._BATCH_SKIPPED):
            msgs.append(f"未记录「战阵之宴」的明确跳过原因：{si._BATCH_SKIPPED}")
        if bp.count_done(prefix_raid) != 0:
            msgs.append(f"被跳过的战阵之宴竟有记账（假记账）：{bp.count_done(prefix_raid)}")
        if bp.count_done(prefix_special) != 1:
            msgs.append("前一条 special 的记账被误伤")
    finally:
        tmp.cleanup()
    return msgs


def probe_mixed_raid_unreachable_skipped(agent_dir: Path | None = None) -> bool:
    return _raid_skip_failures(agent_dir) == []


# ---------------------------------------------------------------------------
# 守卫 4：纯编辑 —— 五条承重短语仍在 + #44 声明注释在场
# ---------------------------------------------------------------------------
def _pipeline_failures() -> list[str]:
    msgs: list[str] = []
    if not _SD.is_file():
        return [f"缺少 {_SD}"]
    text = _SD.read_text(encoding="utf-8")
    for phrase in BEARING_PHRASES:
        if text.count(phrase) < 1:
            msgs.append(f"承重短语「{phrase}」丢失（#12 硬规则：纯编辑不得丢注释）")
    if "#44 混排清单" not in text:
        msgs.append("special_dungeon.json 缺少 #44 声明注释（混排规则未被记录）")
    return msgs


def probe_mixed_pipeline_comment() -> bool:
    return _pipeline_failures() == []


# ---------------------------------------------------------------------------
# prove-red（agent 副本 + PYTHONPATH 抢先）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_settle_guard(agent_dir: Path) -> None:
    """摘掉 record="always" 的「自身导航」前提 -> 陈旧『再次挑战』又假记账。"""
    _sub(
        agent_dir / "side_impl.py",
        'if _active0 and _cur0 is not None and record == "always" and not _engaged0:',
        "if False:  # #44 记账前提被摘掉（prove-red）",
    )


def _break_neutral_gate(agent_dir: Path) -> None:
    """摘掉「切种类先确认中立页」判定 -> 陈旧界面不再封锁分派。"""
    _sub(
        agent_dir / "side_impl.py",
        '            screen = classify_screen(screen_items)\n            if screen == "other":',
        '            screen = classify_screen(screen_items)\n            if False:  # #44 中立页判定被摘掉（prove-red）',
    )


def _break_dispatch_block(agent_dir: Path) -> None:
    """摘掉分派器对封锁标志的读取 -> 封锁形同虚设。"""
    _sub(
        agent_dir / "side_impl.py",
        "            blocked = _BATCH_BLOCK_DISPATCH\n        if blocked:",
        "            blocked = False  # #44 封锁读取被摘掉（prove-red）\n        if blocked:",
    )


def _break_raid_timeout(agent_dir: Path) -> None:
    """把 raid 从导航超时种类里去掉 -> 战阵之宴不再明确跳过。"""
    _sub(
        agent_dir / "side_impl.py",
        "_BATCH_NAV_TIMEOUT_BY_KIND.get(running.kind)\n            if running is not None and not home_pending",
        '(_BATCH_NAV_TIMEOUT_BY_KIND.get(running.kind) if running.kind == "farm" else None)\n'
        "            if running is not None and not home_pending",
    )


def _probe_in(agent_copy: Path, probe_name: str):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针。返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        f"sys.path.insert(1, {str(agent_copy)!r})\n"
        "from contract_hooks import hooks_44\n"
        f"print('PROBE_RESULT', repr(hooks_44.{probe_name}(agent_dir={str(agent_copy)!r})))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral44_"))
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
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def prove_red() -> bool:
    print("hooks_44 prove-red：四处破坏，要求守卫各自变红")
    _pipeline_failures()  # 无障碍时为空；仅确保配置断言可运行
    green = (
        probe_mixed_no_stale_screen_completion() is True
        and probe_mixed_kind_switch_confirms_neutral() is True
        and probe_mixed_raid_unreachable_skipped() is True
        and probe_mixed_pipeline_comment() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：陈旧界面不记账 + 切种类确认中立页 + raid 明确跳过（绿）")
    if not green:
        return False

    breaks = [
        ("摘掉 record=always 的自身导航前提", _break_settle_guard,
         "probe_mixed_no_stale_screen_completion", "陈旧『再次挑战』假记账"),
        ("摘掉切种类确认中立页判定", _break_neutral_gate,
         "probe_mixed_kind_switch_confirms_neutral", "陈旧界面不再封锁分派"),
        ("摘掉分派器的封锁读取", _break_dispatch_block,
         "probe_mixed_kind_switch_confirms_neutral", "封锁标志形同虚设"),
        ("把 raid 从导航超时种类里去掉", _break_raid_timeout,
         "probe_mixed_raid_unreachable_skipped", "战阵之宴不再明确跳过"),
    ]
    results = []
    for label, mutate, probe, why in breaks:
        tmp = Path(tempfile.mkdtemp(prefix="wf_hook44_agent_"))
        try:
            shutil.copytree(AGENT_DIR, tmp / "agent")
            mutate(tmp / "agent")
            red = _probe_in(tmp / "agent", probe) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}（{why}）")
        results.append(red)

    ok = green and all(results)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "mixed-no-stale-screen-completion",
        "#44",
        "陈旧结算页的『再次挑战』不得完成下一条：切种类封锁分派 + record=always 需自身导航"
        "（真机轨迹 mixed.log + 真机帧 OCR）",
        probe_mixed_no_stale_screen_completion,
    ),
    (
        "mixed-kind-switch-confirms-neutral",
        "#44",
        "切条目先确认中立页（主城三独有锚点）：陈旧详情页判 other 并封锁分派；phantom 分派解封后命中",
        probe_mixed_kind_switch_confirms_neutral,
    ),
    (
        "mixed-raid-unreachable-skipped",
        "#44",
        "不做导航的战阵之宴从主城到不了 -> 导航超时明确跳过并记录原因，绝不假记账/空转",
        probe_mixed_raid_unreachable_skipped,
    ),
    (
        "mixed-pipeline-comment",
        "#44",
        "special_dungeon.json 的 #44 混排规则声明注释在场；五条承重短语零丢失（纯编辑）",
        probe_mixed_pipeline_comment,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
