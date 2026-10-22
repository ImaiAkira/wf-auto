# -*- coding: utf-8 -*-
"""#38：战斗失败 / GAMEOVER（「是否续关？」）无恢复路径 → 卡死且后续成员全部不跑。

seam
----
* ``assets/resource/pipeline/common.json``：``PubGameOver*``（拒绝续关 + 放弃确认框的
  公共节点，由 ``special_dungeon.json`` 的 ``SpecialEntry.next`` 以 ``[JumpBack]`` 引用）；
* ``assets/resource/pipeline/special_dungeon.json``：``SpecialEntry.next`` 的引用位置；
* ``agent/side_impl.py``：``classify_gameover`` / ``plan_gameover_action`` /
  ``SpecialBatchPlanRecognition`` 的 GAMEOVER 分支（记账 + 放弃/收工决定）；
* ``tools/live_harness.py`` 的归位有序表 ``RETURN_HOME_RULES``（``gameover`` 规则，
  与 #31 的共斗房同一张表）。

诊断（真机扫描）
----------------
``魁雷精灵兽`` 战斗**打输** → 进入 GAMEOVER /「是否续关？」→ pipeline 没有对应节点 →
任务卡死，且后续 3 个成员（威风 / 巫光 / 暗唤精灵兽）一个都没跑成（设备被留在 GAMEOVER 页，
``ensure_main_city`` 认不出该页故放弃）。一次战斗失败不该让整批任务死掉。

处置（已定）
------------
**放弃该次战斗 → 记录原因 → 继续清单**（批量清单里往往还有别的目标）；但同一失败**连续
2 次**（其间没有任何胜利）时**主动收工并说明原因**（连续失败 = 系统性问题，继续只烧资源）。

守卫（本文件；prove-red 也在本文件里）
-------------------------------------
1. ``gameover-recognised-from-real-frame`` —— ``classify_gameover`` 在**真机帧 OCR**（720
   空间，逐条内嵌）上：GAMEOVER 页 = ``giveup``、放弃确认框 = ``confirm``；在详情页 / 主城 /
   战斗 HUD（同含「时间/分数」）上都是 ``None``（不误命中）。帧文件随仓
   ``tools/frames/gameover_prompt.png`` / ``gameover_confirm.png``。
2. ``gameover-decline-not-continue`` —— pipeline **拒绝续关、绝不点『续关』**：主节点
   And 三叶 ``box_index=2`` 点【放弃】自己的 OCR 框；Fallback 点【放弃】实测坐标 (213,1062)；
   确认框读【OK】框 / 实测坐标 (523,824)；且全部 pipeline 里**没有任何节点**点【续关】座标。
   ★#72★ 该断言现在只对**固定坐标**成立：五重决战改为点【续关】——它是**识别框中心点击**
   （``target: true``，节点 ``PubGameOverContinue``，声明于 ``scene.wuchong.continue_refs()``），
   不写死 (506,1061)。批量链（special_dungeon）**仍拒绝续关**、且全 pipeline 仍**绝不使用固定
   续关坐标** —— 见本文件守卫 2 的坐标断言与 hooks_72 的 ``gameover-continue-frame``。
3. ``gameover-abandon-continue-or-stop`` —— 离线端到端（合成 ctx 回放帧）：
   战斗失败 → 当前目标被放弃、清单继续；**连续 2 次** → ``override_next -> SpecialBatchStop``
   主动收工（原因记录）；纯函数 ``plan_gameover_action`` 的正反例。
4. ``return-home-gameover`` —— 归位认识 GAMEOVER / 其放弃确认框：GAMEOVER →（放弃）→
   确认框 →（OK）→ 详情页 →（主城）→ 主城；破坏实验：删掉该规则 -> 首命中 None = 停手。

★诚实边界★：真机帧实证用**逐条内嵌 OCR**（不重跑 MAA OCR —— 那是 verify_* 的活）；
帧文件随仓供交叉核对。**真机 leg 见 issue 评论**（本守卫是离线部分）。

★prove-red★（``python tools\\contract_hooks\\hooks_38.py``）：
    * 把 ``classify_gameover`` 换成「永远 None」-> 守卫 1 变红；
    * 删掉 pipeline 的 ``PubGameOverGiveUp`` -> 守卫 2 变红；
    * 把连续上限改成 99（永不收工）-> 守卫 3 变红；
    * 从归位有序表删掉 ``gameover`` 规则 -> 守卫 4 变红。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：prove-red 用 PYTHONPATH 抢先塞坏副本时副本仍优先命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

_PIPELINE = REPO_ROOT / "assets" / "resource" / "pipeline"

HOOK_ID = "gameover-abandon-continue-or-stop"

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间；由 1080 帧 ÷1.5 得到）—— source 见每块注释。
# ---------------------------------------------------------------------------
# tools/frames/gameover_prompt.png（原 sweep_lord/recover_before.png）：GAMEOVER 页。
GAMEOVER_PAGE_ITEMS: list[tuple[str, list[int]]] = [
    ("自动", [17, 195, 53, 19]),
    ("技能动", [21, 240, 44, 45]),
    ("11", [25, 53, 39, 39]),
    ("开", [33, 280, 19, 19]),
    ("时间 25:20", [39, 1224, 130, 33]),
    ("×2", [51, 177, 25, 16]),
    ("GAMEOVER", [65, 463, 589, 73]),
    ("剑士类型的强化弹射，可以进行大范围攻击", [123, 728, 357, 19]),
    ("放弃", [180, 1043, 66, 39]),
    ("分数00043411105", [193, 1225, 236, 32]),
    ("2,779,3552,779,305", [221, 908, 321, 28]),
    ("所有角色可回复生命值、", [237, 959, 229, 23]),
    ("0%", [239, 28, 51, 24]),
    ("NNNNNM", [255, 247, 175, 32]),
    ("使用星导石×50", [275, 864, 171, 23]),
    ("雷龟普罗格雷奧", [300, 308, 118, 23]),
    ("是否续关?", [300, 820, 130, 33]),
    ("发动技能。", [300, 977, 106, 32]),
    ("续关", [473, 1043, 65, 36]),
]
# tools/frames/gameover_confirm.png（原 sweep_lord/recover_mid.png）：放弃确认框。
CONFIRM_ITEMS: list[tuple[str, list[int]]] = [
    ("11", [21, 51, 43, 43]),
    ("接能动", [21, 245, 44, 41]),
    ("时间 25:20 分数 00043411105", [35, 1217, 395, 45]),
    ("0%", [153, 27, 141, 28]),
    ("取消", [164, 805, 66, 39]),
    ("道具、RP、经验值、玛纳。", [185, 595, 333, 31]),
    ("无法获得该关卡内已获得的", [189, 557, 337, 32]),
    ("放弃时", [313, 519, 90, 35]),
    ("OK", [496, 805, 54, 37]),
]
# 详情页（原 sweep_lord/recover_after.png）：有『返回 + 主城底导 + 推荐编成』，无 GAMEOVER。
DETAIL_ITEMS: list[tuple[str, list[int]]] = [
    ("地狱级", [0, 240, 50, 20]),
    ("COMPLETE!!", [15, 960, 123, 23]),
    ("返回", [31, 1247, 44, 25]),
    ("推荐编成", [57, 532, 95, 28]),
    ("战斗", [87, 1072, 31, 20]),
    ("主城", [156, 1245, 45, 28]),
    ("降临讨伐", [199, 427, 93, 28]),
    ("雷龟普罗格雷奥地狱级", [205, 459, 278, 28]),
    ("角色", [275, 1244, 47, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("菜单", [636, 1248, 45, 25]),
]
# 主城（原 sweep_lord/recover_home.png）：主城独有锚点 ≥2。
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
# 战斗 HUD：只含带格式的「时间/分数」，**没有** GAMEOVER 字样 —— 分类器不得误命中。
BATTLE_HUD_ITEMS: list[tuple[str, list[int]]] = [
    ("时间 09:53", [300, 1200, 80, 30]),
    ("分数 0000001", [430, 1200, 120, 30]),
]

#: 真机帧文件（随仓，供交叉核对）。
FRAMES = (
    ("tools/frames/gameover_prompt.png", "GAMEOVER 页"),
    ("tools/frames/gameover_confirm.png", "放弃确认框"),
)

#: 期望点击点（720 空间，＝按钮 OCR 框中心）。
EXPECTED_GIVEUP_CLICK = (213, 1062)   # 【放弃】[180,1043,66,39] 中心
EXPECTED_OK_CLICK = (523, 823)        # 【OK】[496,805,54,37] 中心
#: 【续关】按钮中心（720）——**绝不许**任何节点点它（要花星导石×50）。
CONTINUE_BUTTON = (506, 1061)


# ---------------------------------------------------------------------------
# 唯一真源：agent / pipeline / live_harness
# ---------------------------------------------------------------------------
def _import_side_impl():
    import side_impl  # noqa: PLC0415

    return side_impl


def _pipelines(pipeline_dir: Path | None = None) -> dict:
    from scene import drift  # noqa: PLC0415

    return drift.load_pipelines(pipeline_dir or _PIPELINE)


def rules() -> list:
    import live_harness as ca  # noqa: PLC0415

    return [tuple(item) for item in ca.RETURN_HOME_RULES]


def _first_rule(rules_, items) -> str | None:
    for rid, probe, _act in rules_:
        if probe(items):
            return rid
    return None


def _act_for(rules_, rid: str):
    for item in rules_:
        if item[0] == rid:
            return item[2]
    return None


def trace(frames, rules_=None, max_steps: int = 12):
    """确定性走一遍归位状态机（画面按脚本推进）。返回 (是否到主城, 命中序列)。"""
    rules_ = rules() if rules_ is None else rules_
    frames = list(frames)
    seq: list[str] = []
    i = 0
    for _ in range(max_steps):
        items = frames[min(i, len(frames) - 1)]
        rid = _first_rule(rules_, items)
        seq.append(rid)
        if rid is None:
            return False, seq
        if rid == "main_city":
            return True, seq
        i += 1
    return False, seq


def _click_point_for(items, rid: str, rules_=None):
    """真实调用某规则的 action（adb_tap 被替换捕获），返回它点到的 720 坐标。"""
    import live_harness as ca  # noqa: PLC0415

    captured: list[tuple[int, int]] = []
    real_tap = ca.adb_tap
    real_time = ca.time

    class _NoSleep:
        @staticmethod
        def sleep(_seconds):  # noqa: D401
            return None

    try:
        ca.adb_tap = lambda x, y: captured.append((int(round(x)), int(round(y))))
        ca.time = _NoSleep
        act = _act_for(rules_ if rules_ is not None else rules(), rid)
        if act is None:
            return None
        act(items, 0)
    finally:
        ca.adb_tap = real_tap
        ca.time = real_time
    return captured[-1] if captured else None


# ---------------------------------------------------------------------------
# 守卫 1：真机帧 —— 分类器认得 GAMEOVER，但不误命中其它页面
# ---------------------------------------------------------------------------
def recognition_failures(si=None) -> list[str]:
    si = si or _import_side_impl()
    msgs: list[str] = []

    for rel, label in FRAMES:
        if not (REPO_ROOT / rel).is_file():
            msgs.append(f"真机帧缺失：{rel}（{label}，守卫失去证据）")

    if si.classify_gameover(GAMEOVER_PAGE_ITEMS) != "giveup":
        msgs.append(
            f"GAMEOVER 页帧：classify_gameover 应为 giveup，实际 "
            f"{si.classify_gameover(GAMEOVER_PAGE_ITEMS)!r}"
        )
    if si.classify_gameover(CONFIRM_ITEMS) != "confirm":
        msgs.append(
            f"放弃确认框帧：classify_gameover 应为 confirm，实际 "
            f"{si.classify_gameover(CONFIRM_ITEMS)!r}"
        )
    for label, items in (
        ("详情页", DETAIL_ITEMS),
        ("主城", MAIN_CITY_ITEMS),
        ("战斗 HUD（时间/分数）", BATTLE_HUD_ITEMS),
    ):
        got = si.classify_gameover(items)
        if got is not None:
            msgs.append(f"{label}帧被误判成战斗失败（{got!r}）——分类器过宽")
    return msgs


def probe_gameover_recognised() -> bool:
    return recognition_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：pipeline 拒绝续关（点【放弃】/【OK】自己的框；绝不点【续关】）
# ---------------------------------------------------------------------------
def _target_of(node) -> object:
    return ((node or {}).get("action") or {}).get("param", {}).get("target")


def pipeline_failures(si=None, files=None) -> list[str]:
    si = si or _import_side_impl()
    files = files or _pipelines()
    msgs: list[str] = []

    common = files.get("common.json") or {}
    sd = files.get("special_dungeon.json") or {}

    def rec(name):
        return ((common.get(name) or {}).get("recognition") or {})

    def param(name):
        return (rec(name).get("param") or {})

    # 主节点：And 三叶 + box_index 指向【放弃】按钮 → 点它自己的 OCR 框。
    if rec("PubGameOverGiveUp").get("type") != "And":
        msgs.append("PubGameOverGiveUp 的识别不是 And")
    elif param("PubGameOverGiveUp").get("all_of") != [
        "PubGameOverTitle", "PubGameOverPrompt", "PubGameOverGiveUpBtn"
    ] or param("PubGameOverGiveUp").get("box_index") != 2:
        msgs.append(f"PubGameOverGiveUp 的 And 叶子/box_index 不对：{param('PubGameOverGiveUp')!r}")
    if _target_of(common.get("PubGameOverGiveUp")) is not True:
        msgs.append(
            f"PubGameOverGiveUp 的动作不是「点识别框中心」："
            f"{_target_of(common.get('PubGameOverGiveUp'))!r}"
        )

    # 叶子判据文案（与 side_impl 的常量同源）。
    if "^放弃$" not in (param("PubGameOverGiveUpBtn").get("expected") or []):
        msgs.append("PubGameOverGiveUpBtn 未以 ^放弃$ 锚定【放弃】按钮")
    if si.GAMEOVER_TITLE not in (param("PubGameOverTitle").get("expected") or []):
        msgs.append("PubGameOverTitle 未识别 GAMEOVER 横幅")
    if si.GAMEOVER_PROMPT not in (param("PubGameOverPrompt").get("expected") or []):
        msgs.append("PubGameOverPrompt 未识别「是否续关」")
    if "^OK$" not in (param("PubGameOverOkBtn").get("expected") or []):
        msgs.append("PubGameOverOkBtn 未以 ^OK$ 锚定【OK】按钮")
    confirm_exp = param("PubGameOverConfirmText").get("expected") or []
    for marker in si.GAMEOVER_CONFIRM_MARKERS:
        if marker not in confirm_exp:
            msgs.append(f"PubGameOverConfirmText 未识别确认框文案 {marker!r}")

    # Fallback：只认页面锚点后点实测【放弃】/【OK】坐标（防 OCR 抖动停手）。
    if _target_of(common.get("PubGameOverGiveUpFallback")) != list(EXPECTED_GIVEUP_CLICK):
        msgs.append(
            f"PubGameOverGiveUpFallback 未点实测【放弃】坐标 {EXPECTED_GIVEUP_CLICK}："
            f"{_target_of(common.get('PubGameOverGiveUpFallback'))!r}"
        )
    if _target_of(common.get("PubGameOverConfirmFallback")) != list(EXPECTED_OK_CLICK):
        msgs.append(
            f"PubGameOverConfirmFallback 未点实测【OK】坐标 {EXPECTED_OK_CLICK}："
            f"{_target_of(common.get('PubGameOverConfirmFallback'))!r}"
        )
    if rec("PubGameOverConfirm").get("type") != "And" or param("PubGameOverConfirm").get("box_index") != 1:
        msgs.append("PubGameOverConfirm 未以 box_index=1 点【OK】自己的框")

    # 引用：SpecialEntry.next 里四个节点都在，且排在指挥官之后、种类分派器之前。
    entry = (sd.get("SpecialEntry") or {}).get("next") or []
    for name in ("PubGameOverGiveUp", "PubGameOverGiveUpFallback",
                 "PubGameOverConfirm", "PubGameOverConfirmFallback"):
        ref = f"[JumpBack]{name}"
        if ref not in entry:
            msgs.append(f"SpecialEntry.next 缺少 {ref}")
    idx = {x: i for i, x in enumerate(entry)}

    def _i(name):
        return idx.get(name)

    if _i("[JumpBack]PubGameOverGiveUp") is not None and _i("SpecialBatchPlan") is not None:
        if _i("[JumpBack]PubGameOverGiveUp") < _i("SpecialBatchPlan"):
            msgs.append("GAMEOVER 节点排在指挥官之前（指挥官无法据此帧记账）")
    for disp in ("FarmDispatch", "RaidDispatch", "PhantomDispatch"):
        if _i("FarmDispatch") is not None and _i("[JumpBack]PubGameOverGiveUp") is not None:
            if _i("[JumpBack]PubGameOverGiveUp") > _i("FarmDispatch"):
                msgs.append(f"GAMEOVER 节点排在种类分派器 {disp} 之后（失败画面会被分派器抢走）")
                break

    # ★绝不点【续关】★：全部 pipeline 里没有任何节点把点击目标设成续关坐标。
    #   ★#72★ 这条现在只覆盖**固定坐标**；五重的续关是**识别框中心点击**（target:true，
    #   PubGameOverContinue，声明于 scene.wuchong.continue_refs()）——批量本文件仍拒绝续关，
    #   全 pipeline 仍绝不写死 (506,1061)。见 hooks_72 的 gameover-continue-frame。
    for fname, data in files.items():
        if not isinstance(data, dict):
            continue
        for node, spec in data.items():
            tgt = _target_of(spec)
            if isinstance(tgt, list) and len(tgt) == 2 and tuple(tgt) == CONTINUE_BUTTON:
                msgs.append(f"{fname}::{node} 点了【续关】坐标 {CONTINUE_BUTTON}（有限资源！）")
    return msgs


def probe_gameover_decline_not_continue() -> bool:
    return pipeline_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：放弃/继续 与 连续 2 次收工（纯函数 + 离线端到端）
# ---------------------------------------------------------------------------
def policy_failures(si=None) -> list[str]:
    si = si or _import_side_impl()
    msgs: list[str] = []

    a, r = si.plan_gameover_action(
        1, batch_active=True, has_current=True, remaining_other=2)
    if a != "abandon_continue" or "继续清单" not in r:
        msgs.append(f"失败 1 次 + 还有目标：应为 abandon_continue/继续清单，实际 {(a, r)}")

    a2, r2 = si.plan_gameover_action(
        2, batch_active=True, has_current=True, remaining_other=2)
    if a2 != "stop" or "连续" not in r2:
        msgs.append(f"连续 2 次失败：应为 stop（连续），实际 {(a2, r2)}")

    a3, _ = si.plan_gameover_action(
        1, batch_active=False, has_current=False, remaining_other=0)
    if a3 != "stop":
        msgs.append(f"单目标（无可继续）：应为 stop，实际 {a3}")

    a4, _ = si.plan_gameover_action(
        1, batch_active=True, has_current=True, remaining_other=0)
    if a4 != "stop":
        msgs.append(f"批量但已无目标可继续：应为 stop，实际 {a4}")

    if si.GAMEOVER_CONSECUTIVE_LIMIT != 2:
        msgs.append(f"连续失败上限应为 2，实际 {si.GAMEOVER_CONSECUTIVE_LIMIT}")
    return msgs


def probe_gameover_abandon_or_stop() -> bool:
    """#38：战斗失败 → 放弃该目标继续清单；连续 2 次 → 主动收工（纯函数 + 离线端到端）。"""
    return policy_failures() == [] and e2e_failures() == []


# ---------------------------------------------------------------------------
# 离线端到端：指挥官在「GAMEOVER → 确认框 → 详情页」三帧上的行为
# ---------------------------------------------------------------------------
class _Ctx:
    """回放当前帧 OCR；记录 override_next / override_pipeline。"""

    def __init__(self, items=None):
        self.items = items or []
        self.overrides_next: dict = {}
        self.overrides_pipeline: dict = {}
        self.actions: list = []

    def run_recognition(self, entry, image):
        import types  # noqa: PLC0415

        if entry != "OcrTask":
            return types.SimpleNamespace(all_results=[], hit=False)
        rows = [types.SimpleNamespace(box=list(b), text=t) for t, b in self.items]
        return types.SimpleNamespace(all_results=rows, hit=bool(rows))

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
    def __init__(self, image, param, *, task_id=1, entry="SpecialEntry"):
        import json  # noqa: PLC0415

        self.image = image
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        self.custom_action_param = "{}"
        self.task_detail = _TaskDetail(task_id, entry)


def _argv_param(text):
    return {"list": text}


def _drive(rec, items, text, tid):
    ctx = _Ctx(items)
    r = rec.analyze(ctx, _Argv(items, _argv_param(text), task_id=tid))
    return ctx, r


def e2e_failures(si=None) -> list[str]:
    si = si or _import_side_impl()
    rec = si.SpecialBatchPlanRecognition()
    msgs: list[str] = []

    # 账本落到临时文件，绝不污染真实进度。
    import tempfile  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415
    import progress as ledger  # noqa: PLC0415

    _tmp = tempfile.TemporaryDirectory()
    ledger.set_file(_P(_tmp.name) / "h38_progress.json")

    # ---- 场景 A：一个目标失败 → 放弃它、继续清单（后续成员照跑） ----
    text = "魁雷精灵兽,高级,1;威风精灵兽,高级,1;巫光精灵兽,高级,1"
    si.reset_gameover_state()
    ctx, r = _drive(rec, [], text, 30001)
    if r.box is None or si._BATCH_CURRENT is None or si._BATCH_CURRENT.dungeon != "魁雷精灵兽":
        _tmp.cleanup()
        return ["场景A 起始：指挥官没有先切到第一个目标（测试前提不成立）"]

    # 开打（战斗中）
    si._BATCH_IN_FIGHT = True
    # 帧1：GAMEOVER 页
    ctx_go, r_go = _drive(rec, GAMEOVER_PAGE_ITEMS, text, 30001)
    if r_go.box is not None:
        msgs.append("GAMEOVER 页：指挥官不应命中（点击交给 pipeline 节点）")
    if not si._GO_PENDING or si._BATCH_LOSSES != 1:
        msgs.append(f"GAMEOVER 页：应记账一次失败（pending/losses），实际 "
                    f"pending={si._GO_PENDING} losses={si._BATCH_LOSSES}")
    if si._BATCH_IN_FIGHT:
        msgs.append("GAMEOVER 页：in_fight 未清（指挥官会一直等到超时）")

    # 帧2：放弃确认框
    ctx_cf, r_cf = _drive(rec, CONFIRM_ITEMS, text, 30001)
    if r_cf.box is not None:
        msgs.append("放弃确认框：指挥官不应命中（点 OK 交给 pipeline 节点）")

    # 帧3：详情页（失败画面已过）→ 放弃魁雷精灵兽、继续威风精灵兽
    ctx2, r2 = _drive(rec, [], text, 30001)
    if r2.box is None:
        msgs.append("失败画面过后：指挥官应命中（归位主城、继续下一个目标）")
    if any(it.dungeon == "魁雷精灵兽" for it in si._BATCH_ITEMS):
        msgs.append("被放弃的 魁雷精灵兽 仍在清单里（未放弃）")
    if si._BATCH_CURRENT is None or si._BATCH_CURRENT.dungeon != "威风精灵兽":
        msgs.append("失败后未继续到下一个目标（威风精灵兽）")
    if not any(("魁雷精灵兽" in s) or ("连续" in s) for s in si._BATCH_SKIPPED):
        msgs.append("未记录被放弃目标及其原因")

    # ---- 场景 B：连续 2 次失败 → 主动收工（override_next -> SpecialBatchStop） ----
    text2 = "魁雷精灵兽,高级,1;威风精灵兽,高级,1;巫光精灵兽,高级,1"
    si.reset_gameover_state()
    ctxb, rb = _drive(rec, [], text2, 30002)
    if rb.box is None:
        _tmp.cleanup()
        return msgs or ["场景B 起始前提不成立"]

    # 第 1 次失败：A 放弃，继续 B
    si._BATCH_IN_FIGHT = True
    _drive(rec, GAMEOVER_PAGE_ITEMS, text2, 30002)
    _drive(rec, CONFIRM_ITEMS, text2, 30002)
    _drive(rec, [], text2, 30002)
    if si._BATCH_CURRENT is None or si._BATCH_CURRENT.dungeon != "威风精灵兽":
        msgs.append("场景B：第 1 次失败后未切到 威风精灵兽")

    # 第 2 次失败：连续 2 次 → 收工
    si._BATCH_IN_FIGHT = True
    _drive(rec, GAMEOVER_PAGE_ITEMS, text2, 30002)
    _drive(rec, CONFIRM_ITEMS, text2, 30002)
    ctx_stop, r_stop = _drive(rec, [], text2, 30002)
    if r_stop.box is None:
        msgs.append("场景B：连续 2 次失败应命中并收工，实际未命中")
    if ctx_stop.overrides_next.get("SpecialBatchPlan") != ["SpecialBatchStop"]:
        msgs.append(
            f"场景B：连续 2 次失败应 override_next -> SpecialBatchStop，实际 "
            f"{ctx_stop.overrides_next}"
        )
    if si._BATCH_LOSSES != 2:
        msgs.append(f"场景B：连续失败计数应为 2，实际 {si._BATCH_LOSSES}")

    # ---- 胜利打断连续计数：结算（真的打完）后连续失败计数清零 ----
    si.reset_gameover_state()
    _drive(rec, [], text2, 30003)  # 新任务：重新解析清单、切到第一个目标
    si._BATCH_LOSSES = 1
    if si._BATCH_CURRENT is None:
        msgs.append("胜利场景起始前提不成立（指挥官未切到目标）")
    else:
        class _Box:
            x, y, w, h = 180, 1050, 120, 60

        class _ArgvBox(_Argv):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.box = _Box()

        si._BATCH_IN_FIGHT = True
        fin = si.SpecialBatchFinishAction()
        fin.run(_Ctx([]), _ArgvBox([], {}, task_id=30003))
        if si._BATCH_LOSSES != 0:
            msgs.append(f"结算（胜利）后连续失败计数应清零，实际 {si._BATCH_LOSSES}")

    si.reset_gameover_state()
    _tmp.cleanup()
    return msgs


def probe_gameover_offline_repro() -> bool:
    return e2e_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：归位认识 GAMEOVER（与 #31 同一张表）
# ---------------------------------------------------------------------------
def return_home_failures() -> list[str]:
    msgs: list[str] = []
    rules_ = rules()
    ids = [r[0] for r in rules_]
    if "gameover" not in ids:
        return ["归位有序表缺少 gameover 规则（GAMEOVER 仍是未知页面 -> 停手）"]

    # 首命中：GAMEOVER 页 / 确认框都归 gameover。
    if _first_rule(rules_, GAMEOVER_PAGE_ITEMS) != "gameover":
        msgs.append(
            f"GAMEOVER 页首命中应为 gameover，实际 {_first_rule(rules_, GAMEOVER_PAGE_ITEMS)!r}"
        )
    if _first_rule(rules_, CONFIRM_ITEMS) != "gameover":
        msgs.append(
            f"放弃确认框首命中应为 gameover，实际 {_first_rule(rules_, CONFIRM_ITEMS)!r}"
        )
    # 不抢：详情页 / 主城不被 gameover 命中。
    for label, items in (("详情页", DETAIL_ITEMS), ("主城", MAIN_CITY_ITEMS)):
        if _first_rule(rules_, items) == "gameover":
            msgs.append(f"gameover 规则误命中{label}")

    # 读后动：GAMEOVER 页点【放弃】框中心、确认框点【OK】框中心（绝不点续关/取消）。
    pt_go = _click_point_for(GAMEOVER_PAGE_ITEMS, "gameover", rules_)
    if pt_go != EXPECTED_GIVEUP_CLICK:
        msgs.append(f"GAMEOVER 页应点【放弃】框中心 {EXPECTED_GIVEUP_CLICK}，实际 {pt_go}")
    pt_cf = _click_point_for(CONFIRM_ITEMS, "gameover", rules_)
    if pt_cf != EXPECTED_OK_CLICK:
        msgs.append(f"确认框应点【OK】框中心 {EXPECTED_OK_CLICK}，实际 {pt_cf}")

    # 到主城：GAMEOVER →（放弃）→ 确认框 →（OK）→ 详情页 →（主城）→ 主城。
    reached, seq = trace([GAMEOVER_PAGE_ITEMS, CONFIRM_ITEMS, DETAIL_ITEMS, MAIN_CITY_ITEMS])
    if not reached or seq != ["gameover", "gameover", "bottom_nav_mc", "main_city"]:
        msgs.append(f"GAMEOVER 归位序列不对（应到主城）：{seq}")

    # 旧形态（无 gameover 规则）：GAMEOVER 页首命中 None = 停手（复现 #38）。
    old_rules = [r for r in rules_ if r[0] != "gameover"]
    old_first = _first_rule(old_rules, GAMEOVER_PAGE_ITEMS)
    old_reached, old_seq = trace(
        [GAMEOVER_PAGE_ITEMS, CONFIRM_ITEMS, DETAIL_ITEMS, MAIN_CITY_ITEMS], old_rules
    )
    if old_first is not None or old_reached or old_seq != [None]:
        msgs.append(f"旧形态未复现「未知页面，停手」：first={old_first!r} seq={old_seq}")
    return msgs


def probe_return_home_gameover() -> bool:
    return return_home_failures() == []


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def probe_battle_failure_policy() -> bool:
    """#38 全部离线断言（识别 + 拒绝续关 + 放弃/收工 + 归位）。"""
    return (
        recognition_failures() == []
        and pipeline_failures() == []
        and policy_failures() == []
        and e2e_failures() == []
        and return_home_failures() == []
    )


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_38.py`）
# ---------------------------------------------------------------------------
def _broken_classifier_none(items):  # 永远认不出 GAMEOVER
    return None


def prove_red() -> bool:
    import types  # noqa: PLC0415

    print("hooks_38 prove-red：四处破坏，要求守卫各自变红")
    green = (
        probe_gameover_recognised()
        and probe_gameover_decline_not_continue()
        and probe_gameover_abandon_or_stop()
        and probe_gameover_offline_repro()
        and probe_return_home_gameover()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：识别 / 拒绝续关 / 放弃-收工 / 归位（绿）")
    if not green:
        return False

    si = _import_side_impl()

    # (a) classify_gameover 换成「永远 None」-> 识别守卫红。
    broke_si = types.SimpleNamespace(
        classify_gameover=_broken_classifier_none,
        GAMEOVER_TITLE=si.GAMEOVER_TITLE,
        GAMEOVER_PROMPT=si.GAMEOVER_PROMPT,
        GAMEOVER_CONFIRM_MARKERS=si.GAMEOVER_CONFIRM_MARKERS,
        GAMEOVER_CONSECUTIVE_LIMIT=si.GAMEOVER_CONSECUTIVE_LIMIT,
    )
    ra = recognition_failures(broke_si) != []
    print(f"  [{'PASS' if ra else 'FAIL'}] classify_gameover=永远None -> {'红' if ra else '仍绿'}")

    # (b) 删掉 pipeline 的 PubGameOverGiveUp -> 拒绝续关守卫红。
    files = _pipelines()
    broken_common = dict(files["common.json"])
    broken_common.pop("PubGameOverGiveUp", None)
    rb = pipeline_failures(files={**files, "common.json": broken_common}) != []
    print(f"  [{'PASS' if rb else 'FAIL'}] 删掉 PubGameOverGiveUp -> {'红' if rb else '仍绿'}")

    # (c) 连续上限改成 99（永不收工）-> 策略守卫红。
    broke_si2 = types.SimpleNamespace(
        plan_gameover_action=lambda c, **k: si.plan_gameover_action(c, **{**k, "limit": 99}),
        GAMEOVER_CONSECUTIVE_LIMIT=si.GAMEOVER_CONSECUTIVE_LIMIT,
    )
    rc = policy_failures(broke_si2) != []
    print(f"  [{'PASS' if rc else 'FAIL'}] 连续上限=99 -> {'红' if rc else '仍绿'}")

    # (d) 从归位有序表删掉 gameover 规则 -> 归位守卫红。
    import live_harness as ca  # noqa: PLC0415

    real_rules = ca.RETURN_HOME_RULES
    ca.RETURN_HOME_RULES = tuple(r for r in real_rules if r[0] != "gameover")
    try:
        rd = return_home_failures() != []
    finally:
        ca.RETURN_HOME_RULES = real_rules
    print(f"  [{'PASS' if rd else 'FAIL'}] 删掉 gameover 归位规则 -> {'红' if rd else '仍绿'}")

    ok = green and ra and rb and rc and rd
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "gameover-recognised-from-real-frame",
        "#38",
        "战斗失败页/放弃确认框由真机帧 OCR 判出；详情页/主城/战斗 HUD 不误命中",
        probe_gameover_recognised,
    ),
    (
        "gameover-decline-not-continue",
        "#38",
        "GAMEOVER 拒绝续关：点【放弃】/【OK】自己的框或实测坐标；绝不点【续关】（有限资源）",
        probe_gameover_decline_not_continue,
    ),
    (
        HOOK_ID,
        "#38",
        "战斗失败 → 放弃该目标继续清单；连续 2 次 → 主动收工（override_next -> SpecialBatchStop）",
        probe_gameover_abandon_or_stop,
    ),
    (
        "return-home-gameover",
        "#38",
        "归位认识 GAMEOVER/放弃确认框（与 #31 同一张表）：GAMEOVER →（放弃）→ 确认框 →（OK）→ 主城",
        probe_return_home_gameover,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
