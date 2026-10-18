# -*- coding: utf-8 -*-
"""#62：单个「能导航进详情页、却配不出战斗」的成员必须【有界跳过】，绝不吃掉整批。

seam：``agent/side_impl.py``（``_own_detail_unfightable`` / ``plan_unfightable_detail_action``
/ 指挥官的 #62 分支 + special 的兜底导航上限）↔ ``assets/resource/pipeline/special_dungeon.json``
（#62 声明注释）↔ 真机帧 ``tools/frames/ark62_detail_unpairable.png``。

缺陷（设备 127.0.0.1:16448，批量 chunk_j4）
------------------------------------------
``list = 方舟守护者讨伐,中级,1;赤之女王讨伐,中级,1;青之女王讨伐,中级,1;碧之女王讨伐,中级,1;皓之女王讨伐,中级,1``

* ``方舟守护者讨伐`` 排第一：导航成功、详情页身份校验 **match**（``标题='方舟守护者'``），
  但该行【战斗】按钮在真机那一帧被 OCR 读成**单字 `5`**（框 [93,506,7,7]，见内嵌帧
  ``ark62_detail_unpairable.ocr.txt``）—— 既不是 ``^战斗$``，也不是 #43 的「等长单字替换」
  或 #49 的「真前缀截断」可救的字形 → ``special_target_fight`` 配不出战斗框 → 详情页无法推进。
* #39 也不接：``discover_difficulties`` 读得到 ``中级``（行名 ``方舟守护者中级``）→ 难度发现是
  ``present``（**不是** absent / undetermined），于是 #39 的「跳过/收工」分支不触发。
* 结果：整条清单在它身上空转到 **1200s 超时**（status=timeout，账本为空），**后面 4 个成员
  一个都没被尝试**；单独重跑那 4 个（chunk_j4b.log）4/4 正常。

三个守卫（prove-red 也在本文件里）
----------------------------------
1. ``special-unfightable-detected`` —— 内嵌真机帧：该帧满足
   ``classify_detail_difficulty == present`` **且** ``pick_target_battle_box is None`` **且**
   ``_own_detail_unfightable`` 认出「自己的详情页、尚未开打」；开打后（``_BATCH_ITEM_ENGAGED``）
   即不再认；非自己详情页 / 错页也不认。**纯函数 + 内嵌真机 OCR**（不重跑 MAA OCR）。
2. ``special-unfightable-bounded`` —— ① 纯函数 ``plan_unfightable_detail_action``：未到上限 →
   ``retry``；到上限且清单还有别的目标 → ``skip``；到上限且没有别的目标 → ``stop``。
   ② **离线复现**：一个批量清单 = [坏成员, 4 个正常成员]。**旧形态（无上限）**：坏成员在它
   自己的详情页上无限重试 → 后面 4 个永远轮不到（系统性饿死）；**新形态（有界）**：坏成员被
   **明确跳过**、4 个正常成员全部跑完。③ 指挥官接线：源码里确实接了 ``_own_detail_unfightable``
   / ``_note_unfightable_detail`` / ``plan_unfightable_detail_action`` / ``reset_unfightable_detail``。
3. ``special-nav-deadline-backstop`` —— special 条目也要有一个【有限、在合理区间内】的兜底
   导航上限（覆盖「详情页连 ``推荐编成`` 标记都读不到」的形态），且指挥官确实在
   ``nav_timeout is None`` 时把它接上；已声明的种类（raid，``#45``）行为不变。

★prove-red★（``python tools\\contract_hooks\\hooks_62.py``）：把上限去掉 / 把检测接线摘掉 /
把声明注释删掉 → 三个守卫各自变红。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
SD = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"

# ★只 append 到 sys.path 末尾★（与 hooks_44/hooks_45 同形：不抢占 prove-red 的坏副本）。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

# ---------------------------------------------------------------------------
# 真机帧：方舟守护者讨伐详情页（那一帧战斗按钮被 OCR 读成单字 `5`）——逐条内嵌。
# 来源：设备 127.0.0.1:16448 单跑 `方舟守护者讨伐`（watch_ark_4.ocr.txt）；帧文件随仓，
# 供交叉核对：tools/frames/ark62_detail_unpairable.png / .ocr.txt
# ---------------------------------------------------------------------------
ARK_FRAME = [
    ("NEW", [15, 389, 51, 20]),
    ("返回", [30, 1246, 46, 26]),
    ("×0", [43, 300, 45, 26]),
    ("×0", [43, 334, 47, 27]),
    ("×0", [45, 265, 45, 28]),
    ("推荐编成", [55, 530, 97, 30]),
    ("日999/101", [92, 18, 111, 28]),
    ("5", [93, 506, 7, 7]),          # ← 【战斗】按钮被 OCR 读成单字 `5`（缺陷核心）
    ("主城", [157, 1248, 44, 25]),
    ("降临讨伐", [201, 428, 92, 28]),
    ("方舟守护者中级", [202, 457, 200, 32]),
    ("方舟守护者", [203, 198, 313, 66]),
    ("推荐属性？？", [214, 534, 124, 24]),
    ("角色", [276, 1246, 45, 26]),
    ("领主战", [325, 268, 68, 29]),
    ("体力", [365, 533, 46, 25]),
    ("商店", [397, 1245, 43, 27]),
    ("13", [450, 534, 26, 22]),
    ("3,140,655", [509, 18, 95, 24]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("首次报酬", [543, 433, 81, 23]),
    ("兑换道具", [615, 329, 79, 24]),
    ("菜单", [636, 1248, 45, 25]),
]
ARK_MEMBER = "方舟守护者讨伐"

#: 批量清单（真机 chunk_j4 的同款顺序）：坏成员排第一，后面 4 个正常成员。
BAD_MEMBER = ARK_MEMBER
GOOD_MEMBERS = ["赤之女王讨伐", "青之女王讨伐", "碧之女王讨伐", "皓之女王讨伐"]
BATCH_LIST = [BAD_MEMBER] + GOOD_MEMBERS

#: #12 的承重注释硬规则：纯编辑，绝不丢这些短语。
BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)

#: 兜底导航上限的合理区间（秒）：太小会误伤深行成员；太大则「有界」名不副实（任务超时 1200s）。
MIN_NAV_DEADLINE = 60.0
MAX_NAV_DEADLINE = 900.0


def _agent(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _agent_source(agent_dir: Path | None = None) -> str:
    return (Path(agent_dir) if agent_dir else AGENT_DIR).joinpath("side_impl.py").read_text(
        encoding="utf-8"
    )


def _sd_text() -> str:
    return SD.read_text(encoding="utf-8") if SD.is_file() else ""


# ---------------------------------------------------------------------------
# 离线 stub：回放一帧 OCR + 一个「当前条目」（与 hooks_44/hooks_45 同形）
# ---------------------------------------------------------------------------
def _rows(items):
    return types.SimpleNamespace(
        all_results=[types.SimpleNamespace(box=list(b), text=t) for t, b in items],
        hit=bool(items),
    )


class _Ctx:
    def __init__(self, items=None, node_data=None):
        self.items = list(items or [])
        self.node_data = dict(node_data or {})

    def run_recognition(self, entry, image):
        if entry == "OcrTask":
            return _rows(self.items)
        return types.SimpleNamespace(all_results=[], hit=False)

    def get_node_data(self, node):
        return dict(self.node_data.get(node, {}))

    def get_hit_count(self, node):
        return 0

    def override_next(self, node, nxt):
        pass

    def override_pipeline(self, ov):
        pass


class _TaskDetail:
    def __init__(self, task_id, entry="SpecialEntry"):
        self.task_id = task_id
        self.entry = entry


class _Argv:
    def __init__(self, image, param, *, task_id=1, entry="SpecialEntry", box=None):
        self.image = image
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        self.custom_action_param = "{}"
        self.task_detail = _TaskDetail(task_id, entry)
        self.box = box


def _member_item(si, name):
    import batch_plan as bp  # noqa: PLC0415

    items, errors = bp.parse_batch(f"{name},中级,1")
    assert not errors and items, f"清单解析失败：{errors}"
    return items[0]


# ---------------------------------------------------------------------------
# 守卫 1：缺陷帧必须被识别为「自己的详情页、配不出战斗、尚未开打」
# ---------------------------------------------------------------------------
def _detect_failures(agent_dir: Path | None = None) -> list[str]:
    si = _agent(agent_dir)
    import batch_plan as bp  # noqa: PLC0415

    msgs: list[str] = []
    mid = bp.DIFF_REGEX["中级"]

    # 帧文件在场（守卫的证据）。
    for rel in ("tools/frames/ark62_detail_unpairable.png",
                "tools/frames/ark62_detail_unpairable.ocr.txt"):
        if not (REPO_ROOT / rel).is_file():
            msgs.append(f"真机帧缺失：{rel}（守卫失去证据）")

    # (a) 难度发现是 present（#39 不接）—— 证明本票补的是 #39 之外的那段空转。
    outcome = si.classify_detail_difficulty(ARK_FRAME, mid).outcome
    if outcome != "present":
        msgs.append(f"缺陷帧的难度发现应为 present（中级行在），实际 {outcome}（复现前提不成立）")

    # (b) 配不出战斗框（缺陷本体）。
    box, detail = si.pick_target_battle_box(ARK_FRAME, difficulty=mid, pair="below")
    if box is not None:
        msgs.append(f"缺陷帧竟配出了战斗框 {box}（本票的复现前提不成立）")
    if detail.get("reason") != "未找到战斗按钮":
        msgs.append(f"缺陷帧的配对失败原因应为『未找到战斗按钮』，实际 {detail.get('reason')!r}")

    # (c) 身份校验 = match（页对，不是 #42 的错页）。
    verdict, _ident = si.detail_page_identity(
        [(t, b, 1.0) for t, b in ARK_FRAME], ARK_MEMBER, universe=si.known_row_names()
    )
    if verdict != "match":
        msgs.append(f"缺陷帧的身份校验应为 match，实际 {verdict}")

    # (d) _own_detail_unfightable：自己的详情页 + 尚未开打 → 认出该成员。
    item = _member_item(si, ARK_MEMBER)
    with si._BATCH_LOCK:
        saved_cur = si._BATCH_CURRENT
        saved_eng = si._BATCH_ITEM_ENGAGED
    try:
        si._BATCH_CURRENT = item
        si._BATCH_ITEM_ENGAGED = False
        got = si._own_detail_unfightable(_Ctx(ARK_FRAME), _Argv(None, {}), ARK_FRAME)
        if not got or got[0] != ARK_MEMBER:
            msgs.append(f"_own_detail_unfightable 未认出缺陷帧（应返回 {ARK_MEMBER!r}）：{got}")

        # 开打后（已走过自身导航）→ 不再认（绝不误跳正在正常推进的条目）。
        si._BATCH_ITEM_ENGAGED = True
        if si._own_detail_unfightable(_Ctx(ARK_FRAME), _Argv(None, {}), ARK_FRAME) is not None:
            msgs.append("_own_detail_unfightable 在『已开打』时仍命中（会误跳正常推进的条目）")

        # 别的成员（错页 / 非自己详情页）→ 不认（那是 #42 的活）。
        si._BATCH_ITEM_ENGAGED = False
        other = _member_item(si, "赤之女王讨伐")
        si._BATCH_CURRENT = other
        if si._own_detail_unfightable(_Ctx(ARK_FRAME), _Argv(None, {}), ARK_FRAME) is not None:
            msgs.append("_own_detail_unfightable 把『别人的详情页』也认成自己（与 #42 冲突）")
    finally:
        with si._BATCH_LOCK:
            si._BATCH_CURRENT = saved_cur
            si._BATCH_ITEM_ENGAGED = saved_eng
    return msgs


def probe_special_unfightable_detected():
    """#62 守卫 1：真机缺陷帧必须被识别为「自己的详情页、配不出战斗、尚未开打」。"""
    return _detect_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：有界（纯函数语义 + 离线复现 + 指挥官接线）
# ---------------------------------------------------------------------------
def _bounded_semantics_failures(agent_dir: Path | None = None) -> list[str]:
    si = _agent(agent_dir)
    msgs: list[str] = []
    limit = float(si._UNFIGHTABLE_DETAIL_SEC)

    a, _r = si.plan_unfightable_detail_action(
        ARK_MEMBER, limit / 2.0, batch_active=True, remaining_other=4)
    if a != "retry":
        msgs.append(f"未到上限应为 retry，实际 {a}")
    a, r = si.plan_unfightable_detail_action(
        ARK_MEMBER, limit * 2.0, batch_active=True, remaining_other=4)
    if a != "skip" or ARK_MEMBER not in r:
        msgs.append(f"到上限 + 还有别的目标应为 skip 且点名成员，实际 {(a, r)}")
    a, _r = si.plan_unfightable_detail_action(
        ARK_MEMBER, limit * 2.0, batch_active=False, remaining_other=0)
    if a != "stop":
        msgs.append(f"到上限 + 没有别的目标应为 stop，实际 {a}")

    # 计时：同一成员连续帧累计；换成员 / 换任务重新计时。
    si.reset_unfightable_detail(1)
    if si._note_unfightable_detail(ARK_MEMBER, 1, now=100.0) != 0.0:
        msgs.append("计时：首次进入应为 0s")
    if abs(si._note_unfightable_detail(ARK_MEMBER, 1, now=130.0) - 30.0) > 1e-6:
        msgs.append("计时：同一成员连续帧应累计到 30s")
    if si._note_unfightable_detail("别的成员", 1, now=130.0) != 0.0:
        msgs.append("计时：换成员应重新计时")
    si.reset_unfightable_detail(1)
    return msgs


def _repro_failures(*, bound=True, agent_dir: Path | None = None, limit=None) -> list[str]:
    """守卫 2②：离线复现——坏成员排第一，后面 4 个正常成员。

    ``bound=False`` = 旧形态（无上限）：坏成员在自己的详情页上空转到步数上限，后面全饿死。
    """
    si = _agent(agent_dir)
    if limit is None:
        limit = float(si._UNFIGHTABLE_DETAIL_SEC)
    msgs: list[str] = []
    dt = 2.0
    max_steps = 3000

    reached: list[str] = []
    skipped: list[str] = []
    spin = False
    steps = 0
    t = 0.0
    i = 0
    while i < len(BATCH_LIST) and steps < max_steps:
        target = BATCH_LIST[i]
        if target != BAD_MEMBER:
            reached.append(target)
            i += 1
            continue
        since = None
        while steps < max_steps:
            steps += 1
            t += dt
            if not bound:
                continue        # 旧形态：永远配不出战斗 → 无界空转
            if since is None:
                since = t
            act, _r = si.plan_unfightable_detail_action(
                target, t - since, limit=limit,
                batch_active=True, remaining_other=len(BATCH_LIST) - i - 1,
            )
            if act == "skip":
                skipped.append(target)
                break
        if steps >= max_steps:
            spin = True
            break
        i += 1

    if bound:
        if BAD_MEMBER not in skipped:
            msgs.append(f"新形态：坏成员未被明确跳过（skipped={skipped}）")
        missing = [m for m in GOOD_MEMBERS if m not in reached]
        if missing:
            msgs.append(f"新形态：坏成员跳过之后仍有成员没跑（缺 {missing}）")
        if spin:
            msgs.append("新形态：仍出现无界空转（有界性存疑）")
    else:
        # 旧形态必须【复现出系统性饿死】：坏成员吃掉整个预算，后面一个都没轮到。
        if not spin:
            msgs.append("旧形态：未复现『坏成员无界空转』（对照失败）")
        if reached:
            msgs.append(f"旧形态：竟然跑到了后面的成员 {reached}（未复现饿死）")
    return msgs


def _wiring_failures(agent_source: str | None = None) -> list[str]:
    src = _agent_source() if agent_source is None else agent_source
    msgs: list[str] = []
    for needle, what in (
        ("_own_detail_unfightable(context, argv, items_raw)",
         "指挥官没有用缺陷帧判据 _own_detail_unfightable（检测接线缺失）"),
        ("_note_unfightable_detail(member, task_id)",
         "指挥官没有给『自己详情页配不出战斗』计时（上限不会生效）"),
        ("plan_unfightable_detail_action(", "指挥官没有用纯函数决定跳过/收工"),
        ("reset_unfightable_detail(task_id)", "新任务没有复位 #62 计时"),
        ("_clear_unfightable_detail()", "离开该状态时没有复位计时"),
        ('"detail_unfightable_retry"', "缺少 #62 的 retry 分支标识"),
        ('"detail_unfightable_stop"', "缺少 #62 的 stop 分支标识"),
    ):
        if needle not in src:
            msgs.append(f"接线守卫：{what}（缺 {needle!r}）")
    return msgs


def probe_special_unfightable_bounded():
    """#62 守卫 2：有界语义 + 离线复现（旧形态饿死 / 新形态跳过并跑完后 4 个）+ 指挥官接线。"""
    return (
        _bounded_semantics_failures() == []
        and _repro_failures(bound=True) == []
        and _repro_failures(bound=False) == []
        and _wiring_failures() == []
    )


# ---------------------------------------------------------------------------
# 守卫 2b：#39/#41 协同 —— 详情页「读不到任何难度档」（undetermined）不得瞬时收工/空转
#
# 真机 chunk_62：碧之女王 re-navigate 后的第一帧只读到顶栏「活动时间」（难度行尚未渲染）→
# #39 undetermined。旧行为**立刻收工整个批量**（后面 皓之女王 也没跑）；#62 给一个【有界】
# 重试窗口（页面加载完即开打），超窗才处置（批量 → 跳过继续 / 否则收工）。
# ---------------------------------------------------------------------------
def _undetermined_bounded_failures(agent_source: str | None = None) -> list[str]:
    si = _agent()
    msgs: list[str] = []
    limit = float(si._UNFIGHTABLE_DETAIL_SEC)

    a, _r = si.plan_undetermined_difficulty_action(
        "中级", limit / 2.0, batch_active=True, has_current=True, remaining_other=3)
    if a != "retry":
        msgs.append(f"undetermined 未到上限应为 retry（页面可能还在加载），实际 {a}")
    a, r = si.plan_undetermined_difficulty_action(
        "中级", limit * 2.0, batch_active=True, has_current=True, remaining_other=3)
    if a != "skip" or "中级" not in r:
        msgs.append(f"undetermined 到上限 + 还有别的目标应为 skip 且点名难度，实际 {(a, r)}")
    a, _r = si.plan_undetermined_difficulty_action(
        "中级", limit * 2.0, batch_active=False, has_current=True, remaining_other=0)
    if a != "stop":
        msgs.append(f"undetermined 到上限 + 没有别的目标应为 stop，实际 {a}")

    src = _agent_source() if agent_source is None else agent_source
    for needle, what in (
        ("plan_undetermined_difficulty_action(", "指挥官没有用有界 undetermined 判定"),
        ('"difficulty_retry"', "缺少 undetermined 的有界重试分支标识"),
    ):
        if needle not in src:
            msgs.append(f"接线守卫：{what}（缺 {needle!r}）")
    return msgs


def _undetermined_repro_failures(*, bounded=True, limit=None) -> list[str]:
    """离线复现：批量 [瞬态成员, 正常成员]；瞬态成员详情页 6s 内读不到难度档（加载中）。

    ``bounded=False`` = 旧行为（第一帧 undetermined 即收工整个批量）：后面成员被饿死。
    """
    si = _agent()
    if limit is None:
        limit = float(si._UNFIGHTABLE_DETAIL_SEC)
    dt = 2.0
    max_steps = 2000
    targets = ["瞬态成员", "正常成员"]
    reached: list[str] = []
    stopped = None
    t = 0.0
    steps = 0
    i = 0
    while i < len(targets) and steps < max_steps and stopped is None:
        target = targets[i]
        if target != "瞬态成员":
            reached.append(target)
            i += 1
            continue
        since = None
        done = False
        while steps < max_steps:
            steps += 1
            t += dt
            if t >= 6.0:          # 页面加载完 → 难度行可读 → 正常开打
                reached.append(target)
                done = True
                break
            if not bounded:
                stopped = target       # 旧行为：第一帧 undetermined 即收工整批
                done = True
                break
            if since is None:
                since = t
            act, _r = si.plan_undetermined_difficulty_action(
                "中级", t - since, limit=limit,
                batch_active=True, has_current=True, remaining_other=len(targets) - i - 1,
            )
            if act in ("skip", "stop"):
                stopped = target
                done = True
                break
        if not done:
            break
        i += 1

    msgs: list[str] = []
    if bounded:
        if "瞬态成员" not in reached:
            msgs.append(f"新形态：瞬态 undetermined 未在【有界重试】后开打（reached={reached}）")
        if "正常成员" not in reached:
            msgs.append("新形态：后面的成员没跑到")
    else:
        if stopped is None:
            msgs.append("旧形态：未复现『第一帧 undetermined 即收工整批』（对照失败）")
        if reached:
            msgs.append(f"旧形态：竟然跑到了成员 {reached}（未复现瞬时收工）")
    return msgs


def probe_special_undetermined_bounded():
    """#62 守卫 2b：#39/#41 协同 —— undetermined 有界重试后再处置（批量跳过继续 / 否则收工）。"""
    return (
        _undetermined_bounded_failures() == []
        and _undetermined_repro_failures(bounded=True) == []
        and _undetermined_repro_failures(bounded=False) == []
    )


# ---------------------------------------------------------------------------
# 守卫 3：special 的兜底导航上限（覆盖「详情页连标记都读不到」的形态）
# ---------------------------------------------------------------------------
def _nav_deadline_failures(
    *, nav_deadline=None, agent_source: str | None = None, agent_dir: Path | None = None
) -> list[str]:
    si = _agent(agent_dir)
    msgs: list[str] = []
    if nav_deadline is not None:
        si._SPECIAL_NAV_DEADLINE_SEC = nav_deadline
    val = float(si._SPECIAL_NAV_DEADLINE_SEC)
    if not (MIN_NAV_DEADLINE <= val <= MAX_NAV_DEADLINE):
        msgs.append(
            f"special 兜底导航上限 {val} 不在合理区间 "
            f"[{MIN_NAV_DEADLINE},{MAX_NAV_DEADLINE}]（太小误伤深行成员 / 太大名不副实）"
        )
    src = _agent_source() if agent_source is None else agent_source
    if "nav_timeout = _SPECIAL_NAV_DEADLINE_SEC" not in src:
        msgs.append("指挥官没有在 nav_timeout is None 时接上 special 兜底上限")
    if 'getattr(running, "kind", "special") == "special"' not in src:
        msgs.append("兜底上限没有限定在 special 条目（会误伤已声明种类）")
    return msgs


def probe_special_nav_deadline_backstop():
    """#62 守卫 3：special 有有限、区间内的兜底导航上限，且指挥官确实接上。"""
    return _nav_deadline_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：纯编辑 —— 五条承重短语仍在 + #62 声明注释在场
# ---------------------------------------------------------------------------
def _declaration_failures(sd_text: str | None = None) -> list[str]:
    text = _sd_text() if sd_text is None else sd_text
    msgs: list[str] = []
    for phrase in BEARING_PHRASES:
        if text.count(phrase) < 1:
            msgs.append(f"承重短语「{phrase}」丢失（#12 硬规则：纯编辑不得丢注释）")
    if "#62" not in text:
        msgs.append("special_dungeon.json 缺少 #62 声明注释（有界跳过 + #39/#41 协同未被记录）")
    return msgs


def probe_special_unfightable_declared():
    """#62 守卫 4：special_dungeon.json 的 #62 声明注释在场；五条承重短语零丢失（纯编辑）。"""
    return _declaration_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_62.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """真实绿；去掉上限 / 摘掉接线 / 删掉声明 → 三个守卫各自变红。"""
    print("hooks_62 prove-red：去掉有界上限 / 摘掉检测接线 / 删掉声明，要求守卫各自变红")
    green = (
        probe_special_unfightable_detected() is True
        and probe_special_unfightable_bounded() is True
        and probe_special_undetermined_bounded() is True
        and probe_special_nav_deadline_backstop() is True
        and probe_special_unfightable_declared() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：检测 + 有界 + undetermined协同 + 兜底 + 声明（绿）")
    if not green:
        return False

    checks: list[bool] = []

    # 破坏 1：把上限去掉（旧形态 / 实际上限=1e9）→ 离线复现必须红（坏成员饿死后面全部）。
    m1 = _repro_failures(bound=False) + _repro_failures(bound=True, limit=10 ** 9)
    red1 = _repro_failures(bound=True) == [] and len(m1) > 0
    print(f"  [{'PASS' if red1 else 'FAIL'}] 去掉上限（旧形态 / 上限 1e9）-> 有界守卫"
          + (f"红（{m1[0]}）" if m1 else "仍绿（守卫没抓到！）"))
    checks.append(red1)

    # 破坏 2：摘掉指挥官的检测接线。
    src = _agent_source()
    broken = src.replace(
        "_own_detail_unfightable(context, argv, items_raw)",
        "None  # #62 检测接线被摘掉（prove-red）",
    )
    red2 = broken != src and len(_wiring_failures(broken)) > 0
    print(f"  [{'PASS' if red2 else 'FAIL'}] 摘掉 _own_detail_unfightable 接线 -> 接线守卫"
          + ("红" if red2 else "仍绿（守卫没抓到！）"))
    checks.append(red2)

    # 破坏 2b：把 undetermined 的重试窗口关掉（limit=0 ⇒ 第一帧就处置）→ 协同守卫必须红。
    m2b = _undetermined_repro_failures(bounded=True, limit=0.0)
    red2b = len(m2b) > 0
    print(f"  [{'PASS' if red2b else 'FAIL'}] undetermined 重试窗口=0（瞬时处置）-> 协同守卫"
          + (f"红（{m2b[0]}）" if m2b else "仍绿（守卫没抓到！）"))
    checks.append(red2b)

    # 破坏 3：兜底上限改成不合理值。
    m3 = _nav_deadline_failures(nav_deadline=10 ** 9)
    red3 = len(m3) > 0
    print(f"  [{'PASS' if red3 else 'FAIL'}] 兜底上限 = 1e9 -> 兜底守卫"
          + (f"红（{m3[0]}）" if red3 else "仍绿（守卫没抓到！）"))
    checks.append(red3)

    # 破坏 4：删掉 #62 声明注释（纯编辑被破坏）。
    m4 = _declaration_failures(sd_text="#62 之外的文本，且不含声明\n")
    red4 = len(m4) > 0
    print(f"  [{'PASS' if red4 else 'FAIL'}] 删掉 #62 声明注释 -> 声明守卫"
          + (f"红（{m4[0]}）" if red4 else "仍绿（守卫没抓到！）"))
    checks.append(red4)

    # 破坏 5：摘掉 undetermined 的有界接线（源码里不再调用该纯函数）。
    broken2 = src.replace(
        "plan_undetermined_difficulty_action(",
        "plan_absent_difficulty_action(  # #62 undetermined 有界接线被摘掉（prove-red）",
    )
    red5 = broken2 != src and len(_undetermined_bounded_failures(broken2)) > 0
    print(f"  [{'PASS' if red5 else 'FAIL'}] 摘掉 undetermined 有界接线 -> 协同守卫"
          + ("红" if red5 else "仍绿（守卫没抓到！）"))
    checks.append(red5)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "special-unfightable-detected",
        "#62",
        "真机缺陷帧（方舟守护者讨伐详情页、战斗按钮被 OCR 读成 `5`）：难度 present + 配不出战斗"
        "+ 自己的详情页且未开打 → _own_detail_unfightable 认出（开打/错页则不认）",
        probe_special_unfightable_detected,
    ),
    (
        "special-unfightable-bounded",
        "#62",
        "有界跳过：plan_unfightable_detail_action（retry/skip/stop）+ 离线复现（旧形态坏成员饿死"
        "后面全部 / 新形态明确跳过并跑完后 4 个）+ 指挥官接线",
        probe_special_unfightable_bounded,
    ),
    (
        "special-undetermined-bounded",
        "#62",
        "协同 #39/#41：详情页「读不到任何难度档」（undetermined）先【有界重试】再处置"
        "（批量且还有别的目标 → 跳过并继续 / 否则收工），绝不在页面加载中瞬时空转或收工",
        probe_special_undetermined_bounded,
    ),
    (
        "special-nav-deadline-backstop",
        "#62",
        "special 条目的兜底导航上限（有限、区间内）覆盖「详情页连标记都读不到」的形态；已声明种类不变",
        probe_special_nav_deadline_backstop,
    ),
    (
        "special-unfightable-declared",
        "#62",
        "special_dungeon.json 的 #62 声明注释在场；五条承重短语零丢失（纯编辑）",
        probe_special_unfightable_declared,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
