# -*- coding: utf-8 -*-
"""离线单测（#39）：难度集**运行时从详情页发现** + 声明难度不存在时的**明确行为**。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_difficulty_discovery.py

覆盖 #39 的验收标准：

  1. 难度**运行时从详情页发现**（同一成员 ``红嫉机兵`` 两个账号：清关账号 4 档、早期账号
     只有 ``中级``）—— 静态按成员难度表**按定义就会错**（真机帧，内嵌 OCR）；
  2. 选项/目标「声明的难度」在该成员详情页**不存在**时，有**明确、可理解**的行为：
     · 批量清单 → **跳过该目标、继续下一个**（原因记录）；
     · 单目标 / 无目标可继续 → **主动收工**（原因记录）；
     · 连难度都读不到（undetermined）→ **主动收工**（绝不盲目开打）。
     —— 绝不静默打错档、绝不卡死。
  3. ``诅咒弧魔艾基尔讨伐`` 的难度集修正为 ``("中级",)``；「未测定占位」常量从配置消失；
  4. GUI「打哪个难度」与 ``scene.config.DIFFICULTIES`` 一致（含 ``地狱级``），drift 为空；
  5. 守卫 ``hooks_39`` 已点亮，且自带破坏实验（把发现换成静态表 -> 变红）。

真机证据帧随仓：``tools/frames/lord_detail_redjoss_cleared.png`` / ``..._early.png``
（OCR 逐条内嵌于 ``hooks_39``）。本文件**只读**，绝不写盘。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import side_impl as si  # noqa: E402
from batch_plan import DIFF_REGEX  # noqa: E402
from scene.config import DIFFICULTIES  # noqa: E402
from scene.lord_battle import LORD_BATTLE  # noqa: E402
from scene import drift  # noqa: E402
from scene import options as opt  # noqa: E402

import hooks_39  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 桩：回放内嵌真机 OCR；记录指挥官写到 pipeline 上的 override。
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self, items=None):
        self._items = items
        self.overrides_next: dict = {}
        self.overrides_pipeline: dict = {}

    def run_recognition(self, entry, image):
        items = self._items(entry) if callable(self._items) else self._items
        rows = [types.SimpleNamespace(box=list(b), text=t) for t, b in (items or [])]
        return types.SimpleNamespace(all_results=rows, hit=bool(rows))

    def run_action(self, *a, **k):
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
        self.image = image
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)
        self.task_detail = _TaskDetail(task_id, entry)


def _fresh_note():
    si.reset_detail_difficulty()


# ---------------------------------------------------------------------------
# 1. 运行时发现：同一成员两账号放同一函数
# ---------------------------------------------------------------------------
def test_runtime_discovery_two_accounts() -> None:
    print("\n== 1. 运行时发现：同一成员（红嫉机兵）两账号难度集不同 ==")
    cleared = hooks_39.CLEARED_ITEMS
    early = hooks_39.EARLY_ITEMS

    check("清关账号帧：发现 = {超级, 高级+, 高级, 中级}",
          set(si.discover_difficulties(cleared)) == {"超级", "高级+", "高级", "中级"},
          f"got={sorted(si.discover_difficulties(cleared))}")
    check("早期账号帧：发现 = {中级}  （★账号相关：静态表必错★）",
          set(si.discover_difficulties(early)) == {"中级"},
          f"got={sorted(si.discover_difficulties(early))}")

    check("静态表（清关账号实测）说 超级 可用",
          "超级" in hooks_39.STATIC_CLEARED_SET)

    # 清关账号：声明 超级 可用 → present + 命中超级行战斗框。
    cl = si.classify_detail_difficulty(cleared, DIFF_REGEX["超级"])
    check("清关账号：声明「超级」→ present（发现通过）", cl.outcome == "present", f"got={cl.outcome}")
    box, _d = si.pick_target_battle_box(cleared, difficulty=DIFF_REGEX["超级"])
    check("清关账号：命中超级行战斗框 = 实测 [87,501,32,16]",
          box is not None and list(box) == hooks_39.CLEARED_SUPER_BOX, f"box={box}")

    # 早期账号：声明 超级 不存在 → absent（静态表在这里必错）。
    ab = si.classify_detail_difficulty(early, DIFF_REGEX["超级"])
    check("早期账号：声明「超级」→ absent（静态表会静默打错档）", ab.outcome == "absent",
          f"got={ab.outcome}")
    check("早期账号：声明「中级」→ present（该档确实存在）",
          si.classify_detail_difficulty(early, DIFF_REGEX["中级"]).outcome == "present")

    # 非详情页 / farm 目标 → not_applicable（保持旧行为，不新造）。
    check("非纯难度正则（farm 目标）→ not_applicable",
          si.classify_detail_difficulty(early, "光之迷宫初级").outcome == "not_applicable")
    check("主城画面（无难度行、无推荐编成）→ not_applicable",
          si.classify_detail_difficulty([("主城", [157, 1248, 44, 25])], DIFF_REGEX["超级"]).outcome
          == "not_applicable")


# ---------------------------------------------------------------------------
# 2. 明确行为：absent → skip/stop；undetermined → stop（纯函数）
# ---------------------------------------------------------------------------
def test_defined_behaviour() -> None:
    print("\n== 2. 声明难度不存在 / 不可判定 → 明确行为（纯函数） ==")
    a, r = si.plan_absent_difficulty_action(
        "absent", "超级", {"中级"}, batch_active=True, has_current=True)
    check("absent + 批量有当前目标 → skip（跳过并继续）", a == "skip", f"got={(a, r)}")
    check("skip 的原因点名声明难度与实读可用集",
          "超级" in r and "中级" in r, f"reason={r}")

    a2, r2 = si.plan_absent_difficulty_action(
        "absent", "超级", {"中级"}, batch_active=False, has_current=False)
    check("absent + 单目标 → stop（明确收工）", a2 == "stop", f"got={(a2, r2)}")
    check("stop 的原因点名声明难度与实读可用集",
          "超级" in r2 and "中级" in r2, f"reason={r2}")

    a3, r3 = si.plan_absent_difficulty_action(
        "undetermined", "超级", frozenset(), batch_active=True, has_current=True)
    check("undetermined（读不到难度）→ stop（绝不盲目开打）", a3 == "stop", f"got={(a3, r3)}")

    a4, _r = si.plan_absent_difficulty_action(
        "present", "超级", {"超级"}, batch_active=True, has_current=True)
    check("present → none（不介入）", a4 == "none", f"got={a4}")


# ---------------------------------------------------------------------------
# 3. 端到端（离线桩）：详情页发现 -> 指挥官跳过 / 收工
# ---------------------------------------------------------------------------
def _list_override(text):
    return {"list": text, "特别": "无"}


def test_e2e_batch_skip_and_continue() -> None:
    print("\n== 3a. 端到端：批量清单里一个目标难度不存在 → 跳过它、继续下一个 ==")
    si._BATCH_SKIPPED.clear()
    _fresh_note()
    ctrl = si.SpecialBatchPlanRecognition()

    # 清单：红嫉机兵(超级) + 青之女王讨伐(中级)。
    text = "红嫉机兵,超级,1;青之女王讨伐,中级,1"
    ctx = _Ctx(items=lambda entry: None)  # 指挥官自身不需要 OCR 内容
    ctx1 = _Ctx(items=None)
    r1 = ctrl.analyze(ctx1, _Argv(None, {"list": text}, task_id=9001))
    check("指挥官先切到第一个目标（红嫉机兵）并归位",
          si._BATCH_CURRENT is not None and si._BATCH_CURRENT.dungeon == "红嫉机兵"
          and r1.box is not None, f"cur={getattr(si._BATCH_CURRENT, 'dungeon', None)} box={r1.box}")

    # 详情页：声明 超级 不存在（早期账号帧）→ 识别器写交接状态。
    rec = si.SpecialTargetFightRecognition()
    rrec = rec.analyze(_Ctx(hooks_39.EARLY_ITEMS),
                       _Argv(hooks_39.EARLY_ITEMS, {"difficulty": DIFF_REGEX["超级"]}, task_id=9001))
    check("详情页识别器：声明难度不存在 → 不命中（box=None）", rrec.box is None, f"box={rrec.box}")

    # 指挥官消费交接状态：跳过红嫉机兵、切到青之女王讨伐。
    ctx2 = _Ctx(items=None)
    r2 = ctrl.analyze(ctx2, _Argv(None, {"list": text}, task_id=9001))
    check("指挥官：红嫉机兵 已被移出清单",
          all(it.dungeon != "红嫉机兵" for it in si._BATCH_ITEMS),
          f"items={[it.dungeon for it in si._BATCH_ITEMS]}")
    check("指挥官：记录了跳过原因", len(si._BATCH_SKIPPED) == 1 and "超级" in si._BATCH_SKIPPED[0],
          f"skipped={si._BATCH_SKIPPED}")
    check("指挥官：已切到下一个目标（青之女王讨伐）并归位",
          si._BATCH_CURRENT is not None and si._BATCH_CURRENT.dungeon == "青之女王讨伐"
          and r2.box is not None,
          f"cur={getattr(si._BATCH_CURRENT, 'dungeon', None)} box={r2.box}")


def test_e2e_single_target_stops() -> None:
    print("\n== 3b. 端到端：单目标（清单为空）声明难度不存在 → 主动收工 ==")
    _fresh_note()
    ctrl = si.SpecialBatchPlanRecognition()

    # 单目标：清单为空（选项走 SpecialFightTargetRow 的 difficulty）。
    # 先让指挥官跑一次（任务开始：重置状态），随后详情页写交接状态，再跑指挥官。
    ctrl.analyze(_Ctx(items=None), _Argv(None, {"list": ""}, task_id=9101))
    rec = si.SpecialTargetFightRecognition()
    rec.analyze(_Ctx(hooks_39.EARLY_ITEMS),
                _Argv(hooks_39.EARLY_ITEMS, {"difficulty": DIFF_REGEX["超级"]}, task_id=9101))
    ctx = _Ctx(items=None)
    r = ctrl.analyze(ctx, _Argv(None, {"list": ""}, task_id=9101))
    check("单目标：指挥官主动收工（override_next -> SpecialBatchStop）",
          ctx.overrides_next.get("SpecialBatchPlan") == ["SpecialBatchStop"],
          f"overrides_next={ctx.overrides_next}")
    check("单目标：命中并执行收工动作（box=[0,0,0,0]）", r.box is not None, f"box={r.box}")
    check("单目标：原因点名声明难度与实读可用集",
          r.detail.get("declared") == "超级" and r.detail.get("available") == ["中级"],
          f"detail={r.detail}")


# ---------------------------------------------------------------------------
# 4. 配置：#39 修正 + 未测定占位消失 + drift
# ---------------------------------------------------------------------------
def test_config_corrections() -> None:
    print("\n== 4. 配置：诅咒弧魔艾基尔讨伐 修正、未测定占位消失 ==")
    src = (REPO_ROOT / "scene" / "lord_battle.py").read_text(encoding="utf-8")
    check("scene/lord_battle.py 里不再出现「未测定占位」常量名", "_UNMEASURED" not in src)
    by_name = {m.行名: tuple(m.支持难度集) for m in LORD_BATTLE.members}
    check("诅咒弧魔艾基尔讨伐 的难度集 = ('中级',)（真机实读）",
          by_name.get("诅咒弧魔艾基尔讨伐") == ("中级",),
          f"got={by_name.get('诅咒弧魔艾基尔讨伐')}")
    check("诅咒弧魔艾基尔讨伐 仍是有效成员（详情页可打开）", "诅咒弧魔艾基尔讨伐" in by_name)


def test_difficulty_option_matches_config() -> None:
    print("\n== 5. GUI「打哪个难度」与 DIFFICULTIES 一致（含 地狱级）；drift 为空 ==")
    derived = opt.derive_difficulty_block()
    check("派生难度选项 cases 名 == scene.config.DIFFICULTIES（顺序）",
          [c["name"] for c in derived["cases"]] == list(DIFFICULTIES),
          f"got={[c['name'] for c in derived['cases']]}")
    check("地狱级 在派生选项里（过去手写漏了它）", "地狱级" in [c["name"] for c in derived["cases"]])

    # 手写 interface.json 的「打哪个难度」与派生一致。
    msgs = drift.difficulty_option_drift(INTERFACE)
    check("interface.json 的「打哪个难度」与派生逐项一致", msgs == [], f"drift={msgs}")
    check("真实树 drift.check_all() == []", drift.check_all() == [], f"{drift.check_all()}")

    # 破坏：从界面删掉「地狱级」一份 -> 该选项报红（证明守卫真的在看它）。
    text = INTERFACE.read_text(encoding="utf-8")
    broken = text.replace('{ "name": "地狱级",', '{ "name": "地狱级X",', 1)
    check("前提：确实改到了「地狱级」case", broken != text)
    tmp = Path(tempfile.mkdtemp(prefix="wf_h39_opt_"))
    try:
        p = tmp / "interface.json"
        p.write_text(broken, encoding="utf-8")
        red = drift.difficulty_option_drift(p)
        check("界面少了「地狱级」-> 难度选项报红", red != [], f"drift={red}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hook_and_prove_red() -> None:
    print("\n== 6. 守卫 #39 已点亮；破坏实验（换成静态表）成立 ==")
    check("probe_difficulty_discovered_from_detail_page() 返回 True",
          hooks_39.probe_difficulty_discovered_from_detail_page() is True)
    check("prove_red() 成立：把发现换成静态表 -> 守卫变红", hooks_39.prove_red() is True)


def main() -> None:
    print("=" * 74)
    print("#39：难度运行时从详情页发现 + 声明难度不存在时的明确行为（离线测试）")
    print("=" * 74)
    test_runtime_discovery_two_accounts()
    test_defined_behaviour()
    test_e2e_batch_skip_and_continue()
    test_e2e_single_target_stops()
    test_config_corrections()
    test_difficulty_option_matches_config()
    test_hook_and_prove_red()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
