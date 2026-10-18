# -*- coding: utf-8 -*-
"""#46（CRITICAL）：GAMEOVER 页被 ``SpecialBattleWait`` 抢帧 —— 失败画面不可达 → 1200s 超时。

seam
----
* ``assets/resource/pipeline/special_dungeon.json``：``SpecialEntry.next`` 里
  ``SpecialGameOverHold``（新增守卫）相对 ``SpecialBattleWait`` 的位置；
* ``assets/resource/pipeline/common.json``：``PubLevelUpText``（全局打断事件
  ``[JumpBack]PubLevelUpContinue`` 的判据）—— #46 的「确认框被抢占」判别器；
* ``agent/side_impl.py``：``classify_gameover`` / ``is_battle_hud`` / ``battle_wait_should_hold``。

诊断（真机 127.0.0.1:16384；维·索拉斯讨伐/超级 打输；MAA 08:34:33–08:35:15）
----------------------------------------------------------------------------
调试日志逐轮：``SpecialStallRecover Fail · PubGameOverConfirm Fail · SpecialBattleWait
Succeeded``；节点序列尾 40 = ``SpecialBattleWait ↔ SpecialEntry`` 交替到 1200s 超时。
两个叠加缺陷：

1. **GAMEOVER 页仍带战斗 HUD**：失败页底部照样画「时间 23:52 / 分数 00081260335」，
   于是 ``SpecialBattleWait`` 的 ``And(时间, 分数)`` 在该页也命中，赢下这一帧。
2. **放弃确认框被全局打断吃掉**：确认框正文「道具、RP、经验值、玛纳。」含「经验值」，
   ``[JumpBack]PubLevelUpContinue``（被注入到每个流程节点候选集【前缀】）先命中、点底部
   固定点 ``[358,1198]``（在框外 = 空点）→ ``PubGameOverConfirm`` 永远轮不到 →
   「放弃」点出确认框又被打回 GAMEOVER → GiveUp/GiveUpFallback 各 ``max_hit=10`` 用尽 →
   再没有节点能推进 → ``SpecialBattleWait`` 顶上 → 超时（#38 的「放弃→记账→继续」
   因此从未真正执行）。

处置（已定）
------------
* **判别器（common.json）**：``PubLevelUpText`` 的「经验值」叶收紧为
  ``经验值(?!、?玛纳)`` —— 只排除确认框的清单项，升级页自身的「经验值」不受影响；
* **排他（special_dungeon.json）**：``SpecialEntry.next`` 在 ``SpecialBattleWait`` **之前**
  插入 ``SpecialGameOverHold``（``And(GAMEOVER, 是否续关)``，DoNothing，**无 max_hit**），
  使 GAMEOVER 页的命中者不再是 ``SpecialBattleWait``（MAA 无 ``Not``，无法在
  SpecialBattleWait 的 And 里表达「且不是 GAMEOVER 页」，故用分派优先级表达）。

守卫（本文件；prove-red 也在本文件里）
------------------------------------
1. ``battle-wait-not-gameover`` —— 真机失败帧上：HUD 判据**确实**命中（复现缺陷），但
   ``battle_wait_should_hold`` 为假、且**分派求值器的命中者不是 SpecialBattleWait**；
   真机/合成战斗帧上 ``SpecialBattleWait`` **仍是**命中者（判别器不会漏掉真正的战斗）。
2. ``gameover-confirm-reachable`` —— 真机确认框帧上：``[JumpBack]PubLevelUpContinue``
   **不再命中**（判别器生效），且 ``PubGameOverConfirm``（读『OK』）**可达**。
3. ``gameover-hold-guard-wired`` —— ``SpecialGameOverHold`` 在位、排在 ``SpecialBattleWait``
   之前、只认 GAMEOVER 页锚点、动作 DoNothing、绝不点【续关】坐标。
   ★#72★ 该「绝不点续关」现在只对**固定坐标**成立：五重决战改为点【续关】——它是**识别框中心
   点击**（``target: true``，节点 ``PubGameOverContinue``，声明于 ``scene.wuchong.continue_refs()``），
   不写死 (506,1061)。批量（special_dungeon）**仍拒绝续关**、全 pipeline 仍**绝不使用固定续关坐标**。

★诚实边界★：真机帧用**逐条内嵌 OCR**（不重跑 MAA OCR —— 那需要随仓 OCR 模型）；
帧来源见每条注释。MAA 的 ``And`` 不认子引用的 ``inverse``（本票用最小 pipeline
实测确证），故排他只能落在分派优先级上 —— 本文件的求值器照此对账。

★prove-red★（``python tools\\contract_hooks\\hooks_46.py``）：
    * 把 ``PubLevelUpText`` 的「经验值」叶改回裸 ``经验值`` -> 守卫 2 变红；
    * 从 ``SpecialEntry.next`` 删掉 ``SpecialGameOverHold`` -> 守卫 1/3 变红。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：prove-red 用 PYTHONPATH 抢先塞坏副本时副本仍优先命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

_SD = "special_dungeon.json"
_PIPELINE = REPO_ROOT / "assets" / "resource" / "pipeline"

#: 【续关】按钮中心（720）——**绝不许**任何节点点它（星导石×50 是有限资源）。
#: ★#72★ 这条现在只覆盖**固定坐标**：五重的续关是识别框中心点击（target:true，PubGameOverContinue），
#: 不是这个死坐标；批量本文件仍拒绝续关，全 pipeline 仍绝不写死 (506,1061)。
CONTINUE_BUTTON = (506, 1061)

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌）
# ---------------------------------------------------------------------------
#: 失败帧（#46 真机：维·索拉斯讨伐/超级 打输，帧 f_D_020_082139.png 的 OCR）。
#: ★关键：底部【仍然】画着战斗 HUD 的「时间 23:52」「分数 00081260335」★——这就是
#: SpecialBattleWait 误命中的原因，故必须原样带上。
FAILURE_ITEMS: list[tuple[str, list[int]]] = [
    ("自动", [17, 195, 53, 19]),
    ("技能", [21, 240, 44, 45]),
    ("开", [33, 280, 19, 19]),
    ("×2", [51, 177, 25, 16]),
    ("时间 23:52", [39, 1224, 130, 33]),
    ("分数 00081260335", [193, 1225, 236, 32]),
    ("GAMEOVER", [65, 463, 589, 73]),
    ("是否续关?", [300, 820, 130, 33]),
    ("放弃", [180, 1043, 66, 39]),
    ("续关", [473, 1043, 65, 36]),
    # 该失败帧上的敌人名（#46 调查：见 test_gameover_match 的 不死王 说明）。
    ("不死王", [123, 745, 80, 19]),
    ("使用星导石×50", [275, 864, 171, 23]),
    ("所有角色可回复生命值、", [237, 959, 229, 23]),
    ("发动技能。", [300, 977, 106, 32]),
    ("0%", [239, 28, 51, 24]),
]

#: 放弃确认框帧（随仓 tools/frames/gameover_confirm.png；由 #38 的 hooks_38.CONFIRM_ITEMS 单源）。
CONFIRM_ITEMS: list[tuple[str, list[int]]] = [
    ("11", [21, 51, 43, 43]),
    ("时间 25:20 分数 00043411105", [35, 1217, 395, 45]),
    ("0%", [153, 27, 141, 28]),
    ("取消", [164, 805, 66, 39]),
    ("道具、RP、经验值、玛纳。", [185, 595, 333, 31]),
    ("无法获得该关卡内已获得的", [189, 557, 337, 32]),
    ("放弃时", [313, 519, 90, 35]),
    ("OK", [496, 805, 54, 37]),
]

#: 真正的战斗 HUD 帧（随仓 tools/frames/lord_battle_hud.png 的底部 HUD 与左上角标签）。
#: 与失败帧的唯一区别：**没有** GAMEOVER /「是否续关」/「经验值、玛纳」。
BATTLE_ITEMS: list[tuple[str, list[int]]] = [
    ("自动", [17, 195, 53, 19]),
    ("技能", [21, 240, 44, 45]),
    ("开", [33, 280, 19, 19]),
    ("×2", [51, 177, 25, 16]),
    ("时间 10:00", [39, 1207, 130, 33]),
    ("分数 00000082254", [193, 1208, 236, 32]),
]


# ---------------------------------------------------------------------------
# 离线 recognition 求值器（只覆盖判据用到的类型；Custom / 未知 -> 视为不命中）
# ---------------------------------------------------------------------------
def _ocr_hit(rec: dict, items: list[tuple[str, list[int]]]) -> bool:
    param = rec.get("param") or {}
    pats = param.get("expected") or []
    roi = param.get("roi")
    for text, box in items:
        if not any(re.search(p, text or "") for p in pats):
            continue
        if roi is None:
            return True
        cx = box[0] + box[2] / 2
        cy = box[1] + box[3] / 2
        if roi[0] <= cx <= roi[0] + roi[2] and roi[1] <= cy <= roi[1] + roi[3]:
            return True
    return False


def eval_recognition(rec: dict | None, items, resolve=None) -> bool:
    if not isinstance(rec, dict):
        return False
    kind = rec.get("type", "DirectHit")
    if kind == "DirectHit":
        return True
    if kind == "OCR":
        return _ocr_hit(rec, items)
    if kind in ("And", "Or"):
        leaves = (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []
        hits = []
        for leaf in leaves:
            leaf_rec = leaf if not isinstance(leaf, str) else (resolve(leaf) if resolve else None)
            hits.append(eval_recognition(leaf_rec, items, resolve))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测，视为不命中（与真机 GiveUp/Commander 的 Fail 一致）


def _files() -> dict:
    from scene import drift  # noqa: PLC0415

    return drift.load_pipelines(_PIPELINE)


def _resolver(files: dict):
    from scene import drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def candidate_hit(ref: str, items, files) -> bool:
    """一个候选引用（可带 ``[JumpBack]``）在给定画面上是否命中。"""
    name = ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref
    from scene import drift  # noqa: PLC0415

    return eval_recognition(drift._resolve_recognition(name, files), items, _resolver(files))


def winner(candidates: list, items, files, exhausted=frozenset()) -> str | None:
    """按 MAA 的 ``next`` 语义求首个命中者；``exhausted`` 模拟 ``max_hit`` 用尽被跳过。"""
    for ref in candidates:
        name = ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref
        if name in exhausted:
            continue
        if candidate_hit(ref, items, files):
            return name
    return None


# ---------------------------------------------------------------------------
# 守卫 1：失败页不是 SpecialBattleWait；真战斗页仍是 SpecialBattleWait
# ---------------------------------------------------------------------------
def _battle_wait_failures(si=None, files=None) -> list[str]:
    si = si or _import_side_impl()
    files = files or _files()
    sd = files.get(_SD) or {}
    msgs: list[str] = []

    # 语义真源（side_impl 纯函数）。
    if si.is_battle_hud(FAILURE_ITEMS) is not True:
        msgs.append("失败帧应带战斗 HUD（时间/分数）——守卫已与真机帧脱节")
    if si.battle_wait_should_hold(FAILURE_ITEMS) is not False:
        msgs.append("GAMEOVER 失败帧：battle_wait_should_hold 应为 False（不得当战斗中）")
    if si.battle_wait_should_hold(BATTLE_ITEMS) is not True:
        msgs.append("真战斗帧：battle_wait_should_hold 应为 True（判别器不得漏掉真正的战斗）")

    # pipeline 判据（SpecialBattleWait 的 And 引用 common 的 PubBattleTime/PubBattleScore）。
    sbw_rec = (sd.get("SpecialBattleWait") or {}).get("recognition")
    if eval_recognition(sbw_rec, FAILURE_ITEMS, _resolver(files)) is not True:
        msgs.append(
            "失败帧上 SpecialBattleWait 的 HUD 判据应仍命中（#46 缺陷存在的前提；"
            "若这里已 False，说明缺陷已从判据层修复，请同步更新本守卫）"
        )

    # 分派求值：GAMEOVER 页的命中者【不是】SpecialBattleWait。
    entry = (sd.get("SpecialEntry") or {}).get("next") or []
    fresh = winner(entry, FAILURE_ITEMS, files)
    if fresh == "SpecialBattleWait":
        msgs.append("GAMEOVER 页：SpecialBattleWait 竟命中并赢下这一帧（#46 未修复）")
    if fresh is None or "GameOver" not in fresh:
        msgs.append(f"GAMEOVER 页应被 GAMEOVER 节点（GiveUp/守卫）接住，实际命中者={fresh!r}")

    # 模拟 GiveUp/GiveUpFallback 的 max_hit=10 用尽（#46 真机卡死点）：命中者仍不得是 SpecialBattleWait。
    exhausted = {"PubGameOverGiveUp", "PubGameOverGiveUpFallback"}
    after = winner(entry, FAILURE_ITEMS, files, exhausted=exhausted)
    if after == "SpecialBattleWait":
        msgs.append(
            "GiveUp/Fallback 用尽后，GAMEOVER 页又被 SpecialBattleWait 抢走（#46 真机卡死点未修）"
        )
    if after != "SpecialGameOverHold":
        msgs.append(f"GiveUp/Fallback 用尽后应由 SpecialGameOverHold 接住，实际命中者={after!r}")

    # 真战斗帧：命中者【必须】是 SpecialBattleWait（判别器不得漏掉真正的战斗）。
    bw = winner(entry, BATTLE_ITEMS, files)
    if bw != "SpecialBattleWait":
        msgs.append(f"真战斗帧应由 SpecialBattleWait 命中，实际命中者={bw!r}（判别器漏掉了真正的战斗）")
    return msgs


def probe_battle_wait_not_gameover(si=None, files=None) -> bool:
    return _battle_wait_failures(si=si, files=files) == []


# ---------------------------------------------------------------------------
# 守卫 2：确认框不再被全局打断抢占；PubGameOverConfirm 可达
# ---------------------------------------------------------------------------
def _confirm_reachable_failures(si=None, files=None) -> list[str]:
    files = files or _files()
    sd = files.get(_SD) or {}
    common = files.get("common.json") or {}
    msgs: list[str] = []

    # 判别器本体：升级页判据不得命中放弃确认框的「经验值、玛纳」清单项。
    lvl_rec = (common.get("PubLevelUpText") or {}).get("recognition")
    if eval_recognition(lvl_rec, CONFIRM_ITEMS, _resolver(files)) is not False:
        msgs.append(
            "PubLevelUpText 仍命中放弃确认框（『道具、RP、经验值、玛纳。』）——"
            "全局打断 [JumpBack]PubLevelUpContinue 会继续抢占确认框（#46 根因之一）"
        )
    # 判别器不得误伤升级页自身的文案。
    if eval_recognition(lvl_rec, [("等级最大！", [51, 774, 113, 34])], _resolver(files)) is not True:
        msgs.append("PubLevelUpText 应在真实升级页『等级最大！』上命中（判别器不得误伤升级页）")
    if eval_recognition(lvl_rec, [("获得经验值 1200", [200, 800, 300, 30])], _resolver(files)) is not True:
        msgs.append("PubLevelUpText 应在『获得经验值 1200』（非清单项）上命中")

    # 确认框帧：全局打断不再命中；链上确认节点可达。
    if candidate_hit("[JumpBack]PubLevelUpContinue", CONFIRM_ITEMS, files):
        msgs.append("确认框帧上 [JumpBack]PubLevelUpContinue 仍命中（抢占未修）")
    entry = (sd.get("SpecialEntry") or {}).get("next") or []
    who = winner(entry, CONFIRM_ITEMS, files)
    if who not in ("PubGameOverConfirm", "PubGameOverConfirmFallback"):
        msgs.append(f"放弃确认框帧应由 PubGameOverConfirm（读 OK）命中，实际命中者={who!r}")
    return msgs


def probe_gameover_confirm_reachable(si=None, files=None) -> bool:
    return _confirm_reachable_failures(si=si, files=files) == []


# ---------------------------------------------------------------------------
# 守卫 3：SpecialGameOverHold 守卫接线
# ---------------------------------------------------------------------------
def _hold_guard_failures(files=None) -> list[str]:
    files = files or _files()
    sd = files.get(_SD) or {}
    msgs: list[str] = []

    hold = sd.get("SpecialGameOverHold")
    if not isinstance(hold, dict):
        return ["special_dungeon.json 缺少 SpecialGameOverHold（GAMEOVER 页排他守卫）"]

    entry = (sd.get("SpecialEntry") or {}).get("next") or []
    if "SpecialGameOverHold" not in entry:
        msgs.append("SpecialEntry.next 缺少 SpecialGameOverHold")
    if "SpecialBattleWait" not in entry:
        msgs.append("SpecialEntry.next 缺少 SpecialBattleWait")
    if "SpecialGameOverHold" in entry and "SpecialBattleWait" in entry:
        if entry.index("SpecialGameOverHold") > entry.index("SpecialBattleWait"):
            msgs.append("SpecialGameOverHold 必须排在 SpecialBattleWait 【之前】（否则抢不到帧）")

    # 只认 GAMEOVER 页锚点（Title + Prompt），动作 DoNothing，绝不点【续关】。
    rec = hold.get("recognition") or {}
    if rec.get("type") != "And" or (rec.get("param") or {}).get("all_of") != [
        "PubGameOverTitle", "PubGameOverPrompt"
    ]:
        msgs.append(f"SpecialGameOverHold 识别应为 And(『GAMEOVER』,「是否续关？」)，实际 {rec!r}")
    act = (hold.get("action") or {}).get("type")
    if act != "DoNothing":
        msgs.append(f"SpecialGameOverHold 动作应为 DoNothing（点击交给 #38 节点），实际 {act!r}")

    # 绝不点【续关】：全部 pipeline 里没有节点把 target 设成续关坐标。
    #   ★#72★ 只覆盖**固定坐标**；五重的 PubGameOverContinue 是识别框中心点击（target:true）。
    for fname, data in files.items():
        if not isinstance(data, dict):
            continue
        for node, spec in data.items():
            tgt = ((spec or {}).get("action") or {}).get("param", {}).get("target") if isinstance(spec, dict) else None
            if isinstance(tgt, list) and len(tgt) == 2 and tuple(tgt) == CONTINUE_BUTTON:
                msgs.append(f"{fname}::{node} 点了【续关】坐标 {CONTINUE_BUTTON}（有限资源！）")
    return msgs


def probe_gameover_hold_guard_wired(files=None) -> bool:
    return _hold_guard_failures(files=files) == []


# ---------------------------------------------------------------------------
# 汇总 + 破坏实验
# ---------------------------------------------------------------------------
def _import_side_impl():
    import side_impl  # noqa: PLC0415

    return side_impl


def probe_battle_failure_reachable() -> bool:
    """#46 全部离线断言（失败页不是战斗等待 + 确认框可达 + 守卫接线）。"""
    return (
        _battle_wait_failures() == []
        and _confirm_reachable_failures() == []
        and _hold_guard_failures() == []
    )


def _broken_levelup_text(expected: list) -> dict:
    """把 common.json 的 PubLevelUpText 判据换成给定 expected（破坏实验用）。"""
    files = _files()
    common = dict(files["common.json"])
    node = dict(common["PubLevelUpText"])
    node["recognition"] = {"type": "OCR", "param": {"expected": list(expected)}}
    common["PubLevelUpText"] = node
    return {**files, "common.json": common}


def _without_hold(files: dict) -> dict:
    """从 SpecialEntry.next 删掉 SpecialGameOverHold（破坏实验用）。"""
    sd = {k: dict(v) if isinstance(v, dict) else v for k, v in (files.get(_SD) or {}).items()}
    entry = sd["SpecialEntry"]
    entry = dict(entry)
    entry["next"] = [x for x in (entry.get("next") or []) if x != "SpecialGameOverHold"]
    sd["SpecialEntry"] = entry
    return {**files, _SD: sd}


def prove_red() -> bool:
    print("hooks_46 prove-red：两处破坏，要求守卫各自变红")
    green = probe_battle_failure_reachable()
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：失败页非战斗等待 / 确认框可达 / 守卫接线（绿）")
    if not green:
        return False

    # (a) 把「经验值」叶改回裸经验值 -> 确认框又被抢占 -> 守卫 2 红。
    old_files = _broken_levelup_text(["等级提升", "等级最大", "经验值"])
    ra = _confirm_reachable_failures(files=old_files) != []
    print(f"  [{'PASS' if ra else 'FAIL'}] PubLevelUpText 改回裸『经验值』 -> {'红' if ra else '仍绿'}")

    # (b) 删掉 SpecialGameOverHold -> 用尽后 SpecialBattleWait 抢帧 -> 守卫 1/3 红。
    no_hold = _without_hold(_files())
    rb = _battle_wait_failures(files=no_hold) != []
    rc = _hold_guard_failures(files=no_hold) != []
    print(f"  [{'PASS' if rb else 'FAIL'}] 删掉 SpecialGameOverHold -> 守卫1 {'红' if rb else '仍绿'}；"
          f"守卫3 {'红' if rc else '仍绿'}")

    ok = green and ra and rb and rc
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "battle-wait-not-gameover",
        "#46",
        "GAMEOVER 失败页不由 SpecialBattleWait 命中（用尽后由 SpecialGameOverHold 接住）；真战斗页仍命中",
        probe_battle_wait_not_gameover,
    ),
    (
        "gameover-confirm-reachable",
        "#46",
        "放弃确认框不再被全局打断 PubLevelUpContinue 抢占；PubGameOverConfirm（读 OK）可达",
        probe_gameover_confirm_reachable,
    ),
    (
        "gameover-hold-guard-wired",
        "#46",
        "SpecialGameOverHold 排在 SpecialBattleWait 之前、只认 GAMEOVER 页锚点、DoNothing、绝不点续关",
        probe_gameover_hold_guard_wired,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
