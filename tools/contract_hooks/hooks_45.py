# -*- coding: utf-8 -*-
"""#45：战阵之宴(raid) —— 从主城不可达 ⇒ 配置层【声明为能力缺口】。

★#52 起本守卫只守 raid★
------------------------
farm（摇曳的迷宫）曾在 #45 与 raid 一起被声明为「不可打」能力缺口；#52 按现版本迷宫页
（行名恒为「摇曳的迷宫<域>【<元素>】」）把 farm 的目标模型重定为「按【域】选 +【元素】为
独立（可选）选项」，farm 因此**不再是能力缺口** —— 它走【真导航 + 真开打】。
farm 的模型 / 选项 / 守卫见 ``tools/contract_hooks/hooks_52.py``；本文件只保留 raid 的声明守卫，
并额外钉死「farm 不再被声明为不可达」。

seam
----
* ``agent/side_impl.py``：``UNREACHABLE_FROM_MAIN_CITY``（#52 起只含 ``raid``）、
  ``declared_unreachable`` / ``declared_grace_sec`` / ``unreachable_skip_reason``（纯函数）、
  ``_BATCH_NAV_TIMEOUT_BY_KIND``（由声明派生：宽限 0 ⇒ 一确认中立页即跳过，不再等超时）、
  ``SpecialBatchPlanRecognition``（用声明表渲染跳过原因）。
* ``assets/resource/pipeline/raid.json`` / ``special_dungeon.json``：各自的 #45 声明段。

诊断（真机 16448，2026-10-14；本仓库随附证据）
----------------------------------------------
``raid.json`` 的设计就是【不做任何导航】（假定用户已手动打开战阵之宴页面）。真机主城整屏
OCR 里 **没有** 战阵之宴入口 —— 从主城到不了，直到 45s 超时才跳过。

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``raid-unreachable-declared`` —— 声明（agent / raid.json / special_dungeon.json）齐备；
   宽限 0；**farm 不再被声明**（#52：迷宫可达、可打）；真机主城 OCR 证明无战阵之宴入口。
2. ``raid-skip-without-timeout`` —— 从主城出发的批量清单里遇到 raid：一确认中立页即
   【明确跳过并记录原因】（grace=0）；绝不假记账。对照：把宽限改回 45s 就【不会】跳过。
3. ``raid-single-target-unchanged`` —— 清单为空（RaidEntry / FarmEntry）时指挥官不介入、不跳过。

★诚实边界★：真机帧在临时目录、随运行消失；这里内嵌**真机 OCR**（主城整屏 / 迷宫页行名），
不重跑 MAA OCR。farm 现版本行名「可识别」的正向证明见 hooks_52。

★prove-red★（``python tools\\contract_hooks\\hooks_45.py``）：两处破坏，要求守卫各自变红：
  * 把派生宽限换回写死的 45s -> 守卫 2 红（又变成“等超时才跳过”）；
  * 把 raid 的声明宽限改回 45s -> 守卫 2 红；
  * 把 farm 重新写回「不可打」能力缺口（farm.json）-> 守卫 1 红（#52 已重定模型）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
RAID_JSON = PIPE_DIR / "raid.json"
FARM_JSON = PIPE_DIR / "farm.json"
SD_JSON = PIPE_DIR / "special_dungeon.json"

# ★只 append 到 sys.path 末尾★：prove-red 子进程用 PYTHONPATH 抢先塞坏副本时仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌；源：2026-10-14 设备 16448 的 live 抓帧，
# tools/ocr_image.py 以 OcrTask 读出的原始 1080 框已 ÷1.5 归一到 720）
# ---------------------------------------------------------------------------
#: 主城整屏 OCR（真机 16448）：**没有**战阵之宴入口 —— raid 从主城不可达的正证。
MAIN_CITY_ITEMS: list[tuple[str, list[int]]] = [
    ("I 账号B", [2, 73, 88, 27]),
    ("I RANK", [5, 105, 63, 20]),
    ("130", [14, 122, 62, 38]),
    ("修行之道", [17, 728, 159, 41]),
    ("摇曳的迷宫", [56, 880, 166, 37]),
    ("成长任务", [47, 368, 118, 33]),
    ("活动", [82, 1122, 59, 31]),
    ("当前进度", [366, 928, 60, 20]),
    ("城镇", [31, 1245, 47, 27]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 47, 29]),
    ("商店", [397, 1245, 45, 27]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1248, 45, 25]),
    ("领主战", [569, 1121, 78, 29]),
    ("关卡", [313, 1088, 93, 49]),
    ("公告", [631, 733, 46, 25]),
    ("邮件", [631, 841, 47, 25]),
    ("任务", [632, 949, 46, 25]),
]
#: 迷宫页（「摇曳的迷宫 宝物域」子域）真机 OCR：行名 =「摇曳的迷宫<域>【<元素>】」
#: （**无难度档**；游戏写**的**迷宫，元素 token 常被 OCR 丢掉）。#52 用它做正向证据。
MAZE_ITEMS: list[tuple[str, list[int]]] = [
    ("NEW", [21, 1152, 78, 38]),
    ("NEW", [23, 866, 76, 38]),
    ("NEW", [23, 1438, 76, 38]),
    ("Q×10", [25, 496, 125, 50]),
    ("COMPLETE!", [27, 580, 173, 34]),
    ("返回", [45, 1870, 70, 38]),
    ("推荐编成", [85, 798, 143, 42]),
    ("推荐编成", [85, 1084, 143, 42]),
    ("推荐编成", [85, 1370, 143, 42]),
    ("推荐编成", [85, 1654, 141, 44]),
    ("战斗", [133, 752, 43, 22]),
    ("战斗", [133, 1038, 43, 22]),
    ("战斗", [133, 1324, 41, 24]),
    ("战斗", [133, 1610, 43, 24]),
    ("主城", [234, 1868, 67, 42]),
    ("摇曳的迷宫宝物域", [305, 1260, 340, 42]),
    ("摇曳的迷宫宝物域【风】", [305, 1546, 435, 42]),
    ("摇曳的迷宫宝物域【火】", [307, 688, 435, 40]),
    ("摇曳的迷宫宝物域【水】", [307, 974, 435, 42]),
    ("摇曳的迷宫", [488, 224, 304, 56]),
    ("推荐属性雷", [313, 1086, 227, 38]),
    ("推荐属性风体力", [315, 1372, 300, 38]),
    ("推荐属性火", [315, 1662, 234, 34]),
    ("体力", [549, 800, 70, 38]),
    ("首次报酬", [810, 1502, 127, 40]),
    ("首次报酬", [811, 930, 126, 40]),
]

#: #45 的旧 farm 模型（历史）：配置/界面里的 farm 目标与旧滚动判据 —— 真机一个都匹配不到。
CONFIGURED_FARM_TARGET = "光之迷宫中级"
LEGACY_SCROLL_PREDICATE = "之迷宫"
#: #52 的现版本标记：行名带「的迷宫」（游戏写法）+ 三域之一。
CURRENT_MAZE_ROW_MARKER = "的迷宫"
MAZE_DOMAINS = ("崩坏域", "宝物域", "幽玄域")

#: 单跑用清单。
RAID_LIST = "战阵之宴,-,1"

#: 声明必须点到的关键词（raid.json / special_dungeon.json 的 #45 段）。
DECLARED_KINDS = ("raid",)
#: #52 起**不再**声明为不可达的种类（迷宫已可达、可打）。
UNDECLARED_KINDS = ("farm",)

#: #12 的承重注释硬规则：纯编辑，绝不丢这些短语。
BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


# ---------------------------------------------------------------------------
# 离线 stub：回放一帧 OCR；记录 override / 点击（与 hooks_44 同形）
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
        self.image = image
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        self.custom_action_param = "{}"
        self.task_detail = _TaskDetail(task_id, entry)
        self.box = box


def _import_side(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _temp_ledger():
    import progress as ledger  # noqa: PLC0415

    tmp = tempfile.TemporaryDirectory(prefix="wf_hook45_ledger_")
    ledger.set_file(Path(tmp.name) / "progress.json")
    return ledger, tmp


def _drive(rec, items, text, tid, *, entry="SpecialEntry"):
    ctx = _Ctx(items)
    argv = _Argv(items, {"list": text}, task_id=tid, entry=entry)
    return ctx, rec.analyze(ctx, argv)


# ---------------------------------------------------------------------------
# 守卫 1：raid 能力缺口“已声明” + farm 不再被声明 + 真机 OCR 证据
# ---------------------------------------------------------------------------
def _declaration_file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _config_declaration_failures(
    raid_text: str | None = None,
    sd_text: str | None = None,
    farm_text: str | None = None,
) -> list[str]:
    """配置侧声明是否齐备（★纯文本★，便于 prove-red 用改坏后的文本调用）。"""
    raid = _declaration_file_text(RAID_JSON) if raid_text is None else raid_text
    sd = _declaration_file_text(SD_JSON) if sd_text is None else sd_text
    farm = _declaration_file_text(FARM_JSON) if farm_text is None else farm_text
    msgs: list[str] = []
    if "#45" not in raid or "不做任何导航" not in raid or "能力缺口" not in raid:
        msgs.append("raid.json 缺少 #45 声明段（应写明：不做导航 → 从主城不可达 → 能力缺口）")
    if "#45" not in sd or "能力缺口" not in sd:
        msgs.append("special_dungeon.json 缺少 #45 声明段（承接 #44 的同一条规则）")
    # ★#52★：farm 不再是能力缺口 —— farm.json 不得再把它声明成「不可打」。
    if "不可打" in farm and "#45" in farm:
        msgs.append(
            "farm.json 仍把 farm 写成「不可打」能力缺口（#52 已重定目标模型：迷宫可达、可打，"
            "应改为可达/可打的说明）"
        )
    for phrase in BEARING_PHRASES:
        if sd.count(phrase) < 1:
            msgs.append(f"承重短语「{phrase}」丢失（#12 硬规则：纯编辑不得丢注释）")
    return msgs


def probe_raid_unreachable_declared(agent_dir: Path | None = None) -> bool:
    si = _import_side(agent_dir)
    msgs: list[str] = []

    # (a) 声明表：raid 在，宽限 0，原因点到关键事实；farm 不在（#52）。
    for kind in DECLARED_KINDS:
        decl = si.declared_unreachable(kind)
        if not decl:
            msgs.append(f"UNREACHABLE_FROM_MAIN_CITY 缺少声明项：{kind}")
            continue
        if float(decl.get("grace_sec", -1)) != 0.0:
            msgs.append(f"{kind} 的 grace_sec 应为 0（一确认中立页即判定）：{decl.get('grace_sec')}")
        if not str(decl.get("reason") or "").strip():
            msgs.append(f"{kind} 的跳过原因为空（原因必须来自声明表）")
    if "跳过" not in str(si.declared_unreachable("raid").get("reason")):
        msgs.append("raid 的声明原因必须写明「跳过」")
    for kind in UNDECLARED_KINDS:
        if si.declared_unreachable(kind) is not None:
            msgs.append(
                f"{kind} 竟仍在 UNREACHABLE_FROM_MAIN_CITY 里（#52：迷宫已可达/可打，"
                f"不应再声明为能力缺口）"
            )

    # (b) 派生宽限：由声明表派生，且只剩 raid=0（#52 起 farm 不在表里 → 不介入）。
    if si._BATCH_NAV_TIMEOUT_BY_KIND != {"raid": 0.0}:
        msgs.append(f"_BATCH_NAV_TIMEOUT_BY_KIND 应由声明派生为 {{'raid': 0.0}}：{si._BATCH_NAV_TIMEOUT_BY_KIND}")

    # (c) 真机 OCR 证据：迷宫页有「的迷宫」+ 三域之一（#52 新模型），没有旧目标/旧判据/难度档。
    texts = [t for t, _b in MAZE_ITEMS]
    if not any(CURRENT_MAZE_ROW_MARKER in t for t in texts):
        msgs.append("内嵌迷宫页 OCR 缺少现版本行名标记「的迷宫」（证据已与实现脱节）")
    if not any(any(d in t for d in MAZE_DOMAINS) for t in texts):
        msgs.append("内嵌迷宫页 OCR 里没有三域之一（#52 目标模型缺证据）")
    if any(re.search(re.escape(CONFIGURED_FARM_TARGET), t) for t in texts):
        msgs.append(f"迷宫页竟然出现了旧配置目标 {CONFIGURED_FARM_TARGET!r} —— 与诊断矛盾")
    if any(re.search(re.escape(LEGACY_SCROLL_PREDICATE), t) for t in texts):
        msgs.append(f"迷宫页竟然出现了旧滚动判据 {LEGACY_SCROLL_PREDICATE!r} —— 与诊断矛盾")
    if any("初级" in t or "中级" in t or "高级" in t for t in texts):
        msgs.append("迷宫页出现了难度档位字样 —— 与本模式无难度档的诊断矛盾")

    # (d) 主城 OCR 证据：没有战阵之宴入口（raid 从主城不可达）。
    city = [t for t, _b in MAIN_CITY_ITEMS]
    if any("战阵之宴" in t for t in city):
        msgs.append("主城 OCR 竟然出现了战阵之宴入口 —— raid 不可达的断言已失效")

    # (e) 配置侧声明。
    msgs.extend(_config_declaration_failures())

    for m in msgs[:8]:
        print(f"    × {m}")
    return msgs == []


# ---------------------------------------------------------------------------
# 守卫 2：批量清单里 raid 一确认中立页即明确跳过（不等超时、不假记账）
# ---------------------------------------------------------------------------
def _skip_without_timeout_failures(agent_dir: Path | None = None) -> list[str]:
    si = _import_side(agent_dir)
    from batch_plan import count_done, item_prefix  # noqa: PLC0415

    ledger, tmp = _temp_ledger()
    msgs: list[str] = []
    try:
        # 清单里在 raid 之后还放一条 special：这样「跳过」之后应【继续下一条】。
        cases = (
            ("raid", "战阵之宴,-,1;猩红巨熊讨伐,中级,1", 45002),
        )
        for kind, text, tid in cases:
            si.reset_gameover_state()
            rec = si.SpecialBatchPlanRecognition()

            # 帧 1（主城）：切到该目标 -> 归位（已经是主城）-> 放行并开始。
            ctx1, r1 = _drive(rec, MAIN_CITY_ITEMS, text, tid)
            if si._BATCH_CURRENT is None or si._BATCH_CURRENT.kind != kind:
                msgs.append(f"{kind}：第一条未切到目标（cur={getattr(si._BATCH_CURRENT, 'dungeon', None)}）")
                continue
            if r1.box is None:
                msgs.append(f"{kind}：主城上未放行（前提不成立）")
            prefix = item_prefix(si._BATCH_CURRENT)

            # 帧 2（主城）：**不做任何计时器回拨** —— grace=0 ⇒ 本帧即明确跳过。
            ctx2, r2 = _drive(rec, MAIN_CITY_ITEMS, text, tid)
            if any(it.kind == kind for it in si._BATCH_ITEMS):
                msgs.append(f"{kind}：一确认中立页仍未跳过（declared grace=0 未生效 —— 又要等超时）")
            if not any(("跳过" in s and "能力缺口" in s) for s in si._BATCH_SKIPPED):
                msgs.append(f"{kind}：未记录「声明式能力缺口」的明确跳过原因：{si._BATCH_SKIPPED}")
            if count_done(prefix) != 0:
                msgs.append(f"{kind}：被跳过的目标竟有记账（假记账）：{count_done(prefix)}")
            # 跳过之后应继续下一条（而不是被卡在这一条 / 把整批收掉）。
            if si._BATCH_CURRENT is None or si._BATCH_CURRENT.dungeon != "猩红巨熊讨伐":
                msgs.append(
                    f"{kind}：跳过之后未继续下一条（cur="
                    f"{getattr(si._BATCH_CURRENT, 'dungeon', None)}）"
                )
            if r2.box is None:
                msgs.append(f"{kind}：跳过之后应继续归位/开始下一条（box=None 表示卡住）")

        # 对照：把 raid 宽限改回 45s（= 未声明时的旧行为），第二帧【不该】跳过。
        si.reset_gameover_state()
        rec = si.SpecialBatchPlanRecognition()
        saved = dict(si._BATCH_NAV_TIMEOUT_BY_KIND)
        try:
            si._BATCH_NAV_TIMEOUT_BY_KIND["raid"] = 45.0
            _drive(rec, MAIN_CITY_ITEMS, RAID_LIST, 45003)
            _drive(rec, MAIN_CITY_ITEMS, RAID_LIST, 45003)
            if not any(it.kind == "raid" for it in si._BATCH_ITEMS):
                msgs.append("对照实验失败：宽限=45s 时第二帧竟也跳过了（跳过并非由声明驱动）")
        finally:
            si._BATCH_NAV_TIMEOUT_BY_KIND.clear()
            si._BATCH_NAV_TIMEOUT_BY_KIND.update(saved)
    finally:
        tmp.cleanup()
    for m in msgs[:8]:
        print(f"    × {m}")
    return msgs


def probe_raid_skip_without_timeout(agent_dir: Path | None = None) -> bool:
    return _skip_without_timeout_failures(agent_dir) == []


# ---------------------------------------------------------------------------
# 守卫 3：单目标（清单为空）行为不变 —— 指挥官不介入、不跳过
# ---------------------------------------------------------------------------
def _single_target_failures(agent_dir: Path | None = None) -> list[str]:
    si = _import_side(agent_dir)
    msgs: list[str] = []
    ledger, tmp = _temp_ledger()
    try:
        for entry, kind, tid in (("FarmEntry", "farm", 45011), ("RaidEntry", "raid", 45012)):
            si.reset_gameover_state()
            rec = si.SpecialBatchPlanRecognition()
            ctx, r = _drive(rec, MAIN_CITY_ITEMS, "", tid, entry=entry)
            if r.box is not None:
                msgs.append(f"{entry}（单目标，清单为空）：指挥官竟命中（应不介入）")
            if ctx.overrides_next or ctx.overrides_pipeline:
                msgs.append(f"{entry}：单目标不应产生任何 override：{ctx.overrides_next}")
            if si._BATCH_SKIPPED:
                msgs.append(f"{entry}：单目标竟记录了跳过原因：{si._BATCH_SKIPPED}")
            if si._BATCH_MODE != kind:
                msgs.append(f"{entry}：_BATCH_MODE 应为 {kind}，实际 {si._BATCH_MODE}")
    finally:
        tmp.cleanup()
    for m in msgs[:8]:
        print(f"    × {m}")
    return msgs


def probe_raid_single_target_unchanged(agent_dir: Path | None = None) -> bool:
    return _single_target_failures(agent_dir) == []


# ---------------------------------------------------------------------------
# prove-red（agent 副本 + PYTHONPATH 抢先）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_static_grace(agent_dir: Path) -> None:
    """把“由声明派生”的宽限换回写死的 45s -> 又变成等超时才跳过。"""
    _sub(
        agent_dir / "side_impl.py",
        "_BATCH_NAV_TIMEOUT_BY_KIND = {\n"
        '    kind: float(decl["grace_sec"]) for kind, decl in UNREACHABLE_FROM_MAIN_CITY.items()\n'
        "}",
        '_BATCH_NAV_TIMEOUT_BY_KIND = {"raid": 45.0}  # #45 派生被摘掉（prove-red）',
    )


def _break_raid_declaration(agent_dir: Path) -> None:
    """把 raid 的声明宽限改回 45s -> 不再一确认中立页即跳过。"""
    _sub(
        agent_dir / "side_impl.py",
        '    "raid": {\n        "grace_sec": 0.0,',
        '    "raid": {\n        "grace_sec": 45.0,',
    )


def _probe_in(agent_copy: Path, probe_name: str):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针。返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        f"sys.path.insert(1, {str(agent_copy)!r})\n"
        "from contract_hooks import hooks_45\n"
        f"print('PROBE_RESULT', repr(hooks_45.{probe_name}(agent_dir={str(agent_copy)!r})))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral45_"))
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
    print("hooks_45 prove-red：两处破坏，要求守卫各自变红")
    _config_declaration_failures()  # noqa: B018
    green = (
        probe_raid_unreachable_declared() is True
        and probe_raid_skip_without_timeout() is True
        and probe_raid_single_target_unchanged() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：raid 声明齐备 + farm 不再声明 + 一确认中立页即跳过（绿）")
    if not green:
        return False

    # 配置侧破坏（纯文本，无副作用）：把 farm 重新写成「不可打」能力缺口。
    config_red = bool(
        _config_declaration_failures(
            farm_text=_declaration_file_text(FARM_JSON) + "\n// #45 不可打（prove-red）\n"
        )
    )
    print(f"  [{'PASS' if config_red else 'FAIL'}] 把 farm 写回「不可打」能力缺口 -> "
          f"{'红' if config_red else '仍绿'}（#52 已重定模型）")

    breaks = [
        ("把派生宽限换回写死的 45s", _break_static_grace,
         "probe_raid_skip_without_timeout", "又变成等超时才跳过"),
        ("把 raid 的声明宽限改回 45s", _break_raid_declaration,
         "probe_raid_skip_without_timeout", "raid 不再一确认中立页即跳过"),
    ]
    results = []
    for label, mutate, probe, why in breaks:
        tmp = Path(tempfile.mkdtemp(prefix="wf_hook45_agent_"))
        try:
            shutil.copytree(AGENT_DIR, tmp / "agent")
            mutate(tmp / "agent")
            red = _probe_in(tmp / "agent", probe) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}（{why}）")
        results.append(red)

    ok = green and config_red and all(results)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "raid-unreachable-declared",
        "#45",
        "战阵之宴(raid) 从主城不可达 = 配置层声明的能力缺口（声明齐备；真机主城 OCR 证明无入口）；"
        "#52 起 farm 不再声明（迷宫可达、可打）",
        probe_raid_unreachable_declared,
    ),
    (
        "raid-skip-without-timeout",
        "#45",
        "批量清单里 raid 一确认中立页即明确跳过并记录声明原因（grace=0，不等 45s；不假记账）",
        probe_raid_skip_without_timeout,
    ),
    (
        "raid-single-target-unchanged",
        "#45",
        "单目标（清单为空，RaidEntry/FarmEntry）行为不变：指挥官不介入、不跳过",
        probe_raid_single_target_unchanged,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
