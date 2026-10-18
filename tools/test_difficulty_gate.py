# -*- coding: utf-8 -*-
"""离线单测（#41）：详情页判据必须要求真正的详情页标记（``推荐编成``），修 #39 的回归。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_difficulty_gate.py

覆盖 #41 的验收标准：

  1. ``on_detail_page`` 只认详情页标记「推荐编成」（与 pipeline ``SpecialDetailGate`` 同源）；
  2. **真机主城帧**（携带被误读的 ``地狱级``/``超级``、没有「推荐编成」）上难度发现为
     ``not_applicable``，**绝不** ``absent`` —— 即成员不会在导航前被假跳过；
  3. 端到端（离线桩）：清单指挥官 + 主城帧上的 ``SpecialFightTargetRow`` →
     **不跳过**该成员；对照：真机详情页帧上声明不存在的难度仍会**真跳过**（证明机制非空转）；
  4. #39 的真行为仍成立：真机详情页帧 ``present`` / ``absent`` 判定不变；
  5. 守卫 ``hooks_41`` 已点亮（自带破坏实验：退回松散判据 -> 变红）；
  6. 排位事实：``SpecialFightTargetRow`` 仍排在 ``SpecialOpenLord`` 之前（门控修的是判据，
     不是顺序）。

真机证据：主城帧 OCR 逐条内嵌于 ``tools/contract_hooks/hooks_41.py``（不重跑 MAA OCR）。
本文件**只读**，绝不写盘（prove-red 走临时副本）。
"""

from __future__ import annotations

import json
import sys
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

import hooks_39  # noqa: E402
import hooks_41  # noqa: E402

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


# ---------------------------------------------------------------------------
# 1. on_detail_page：只认「推荐编成」标记。
# ---------------------------------------------------------------------------
def test_on_detail_page_marker() -> None:
    print("\n== 1. on_detail_page 只认详情页标记「推荐编成」 ==")
    for frame in hooks_41.MAIN_FRAMES:
        check(f"{frame['name']}：不是详情页",
              si.on_detail_page(frame["items"]) is False)
    check("真机详情页（#39 早期账号帧）：是详情页",
          si.on_detail_page(hooks_39.EARLY_ITEMS) is True)
    check("真机详情页（#39 清关账号帧）：是详情页",
          si.on_detail_page(hooks_39.CLEARED_ITEMS) is True)
    # 只有难度词、没有标记 → 不是详情页（回归的最小复现）。
    check("仅含难度词、无标记 → 不是详情页",
          si.on_detail_page([("地狱级", [33, 240, 53, 20])]) is False)
    check("标记与 pipeline SpecialDetailGate 同源（= 推荐编成）",
          si._DETAIL_PAGE_MARKER == "推荐编成")


# ---------------------------------------------------------------------------
# 2. 主城帧：not_applicable（绝不 absent）。
# ---------------------------------------------------------------------------
def test_main_city_not_applicable() -> None:
    print("\n== 2. 真机主城帧：难度发现 not_applicable（绝不假跳过） ==")
    for frame in hooks_41.MAIN_FRAMES:
        out = si.classify_detail_difficulty(frame["items"], DIFF_REGEX["中级"])
        check(f"{frame['name']}：中级 → not_applicable",
              out.outcome == "not_applicable", f"got={out.outcome}")
        found = set(si.discover_difficulties(frame["items"]))
        check(f"{frame['name']}：确实读到被误读的难度词（破坏实验依据）",
              bool(found & set(frame["misread"])), f"found={sorted(found)}")


# ---------------------------------------------------------------------------
# 3. #39 真行为保持：真机详情页帧 present / absent 不变。
# ---------------------------------------------------------------------------
def test_genuine_behaviour_preserved() -> None:
    print("\n== 3. #39 真行为保持：真机详情页帧 present / absent 不变 ==")
    check("早期账号详情页：超级 → absent（真跳过仍成立）",
          si.classify_detail_difficulty(hooks_39.EARLY_ITEMS, DIFF_REGEX["超级"]).outcome
          == "absent")
    check("早期账号详情页：中级 → present（该档确实存在）",
          si.classify_detail_difficulty(hooks_39.EARLY_ITEMS, DIFF_REGEX["中级"]).outcome
          == "present")
    check("清关账号详情页：超级 → present",
          si.classify_detail_difficulty(hooks_39.CLEARED_ITEMS, DIFF_REGEX["超级"]).outcome
          == "present")


# ---------------------------------------------------------------------------
# 4. 端到端：主城帧不跳过；真 absent 仍真跳过。
# ---------------------------------------------------------------------------
def _rec_on(items, declared, task_id):
    si.reset_detail_difficulty()
    rec = si.SpecialTargetFightRecognition()
    rec.analyze(_Ctx(items), _Argv(items, {"difficulty": DIFF_REGEX[declared]}, task_id=task_id))
    return si._take_detail_difficulty()


def test_e2e_no_skip_from_main_city() -> None:
    print("\n== 4a. 端到端：主城帧（SpecialFightTargetRow 早于导航）→ 不跳过成员 ==")
    si._BATCH_SKIPPED.clear()
    si.reset_detail_difficulty()
    ctrl = si.SpecialBatchPlanRecognition()
    text = "青之女王讨伐,中级,1"  # 该成员真机详情页有「中级」（#41 假跳过之一）

    r1 = ctrl.analyze(_Ctx(items=None), _Argv(None, {"list": text}, task_id=41101))
    check("指挥官先切到目标（青之女王讨伐）并归位",
          si._BATCH_CURRENT is not None and si._BATCH_CURRENT.dungeon == "青之女王讨伐"
          and r1.box is not None, f"cur={getattr(si._BATCH_CURRENT, 'dungeon', None)}")

    # 主城帧：SpecialFightTargetRow 直接跑（#41 的误判发生点）。
    rec = si.SpecialTargetFightRecognition()
    rrec = rec.analyze(_Ctx(hooks_41.MAIN_16448_ITEMS),
                       _Argv(hooks_41.MAIN_16448_ITEMS, {"difficulty": DIFF_REGEX["中级"]},
                             task_id=41101))
    check("主城帧识别器：不命中（box=None）", rrec.box is None, f"box={rrec.box}")
    check("主城帧识别器：不写下任何跳过交接（_take_detail_difficulty → None）",
          si._take_detail_difficulty() is None)

    r2 = ctrl.analyze(_Ctx(items=None), _Argv(None, {"list": text}, task_id=41101))
    check("指挥官：目标仍在清单（未被假跳过）",
          any(it.dungeon == "青之女王讨伐" for it in si._BATCH_ITEMS),
          f"items={[it.dungeon for it in si._BATCH_ITEMS]}")
    check("指挥官：未记录任何跳过原因", si._BATCH_SKIPPED == [], f"skipped={si._BATCH_SKIPPED}")
    check("指挥官：当前目标仍是青之女王讨伐",
          si._BATCH_CURRENT is not None and si._BATCH_CURRENT.dungeon == "青之女王讨伐")


def test_e2e_genuine_absent_still_skips() -> None:
    print("\n== 4b. 对照：真机详情页帧上声明不存在的难度 → 仍会真跳过（机制非空转） ==")
    si._BATCH_SKIPPED.clear()
    note = _rec_on(hooks_39.EARLY_ITEMS, "超级", 41201)
    check("详情页识别器：早期账号声明「超级」→ 写下 absent 交接",
          note is not None and note.outcome == "absent",
          f"note={note}")


# ---------------------------------------------------------------------------
# 5. 排位事实 + 守卫。
# ---------------------------------------------------------------------------
def test_ordering_and_hook() -> None:
    print("\n== 5. 排位事实 + 守卫 hooks_41 ==")
    data = hooks_41._load_pipeline()
    nxt = hooks_41._entry_next(data)
    check("SpecialFightTargetRow 仍排在 SpecialOpenLord 之前（门控修的是判据、非顺序）",
          nxt.index("SpecialFightTargetRow") < nxt.index("SpecialOpenLord")
          if "SpecialFightTargetRow" in nxt and "SpecialOpenLord" in nxt else False)
    check("hooks_41._failures() == []（守卫绿）", hooks_41._failures() == [])
    check("hooks_41.probe_...() is True", hooks_41.probe_difficulty_gate_requires_real_detail_marker() is True)
    check("hooks_41.prove_red() is True：退回松散判据 → 变红", hooks_41.prove_red() is True)
    check("hooks_39 守卫仍绿（#39 真行为未被破坏）",
          hooks_39.probe_difficulty_discovered_from_detail_page() is True)


def main() -> None:
    print("=" * 74)
    print("#41：详情页判据必须要求真正的详情页标记（推荐编成）—— 修 #39 的回归")
    print("=" * 74)
    test_on_detail_page_marker()
    test_main_city_not_applicable()
    test_genuine_behaviour_preserved()
    test_e2e_no_skip_from_main_city()
    test_e2e_genuine_absent_still_skips()
    test_ordering_and_hook()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
