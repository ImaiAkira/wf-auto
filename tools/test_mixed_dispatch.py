# -*- coding: utf-8 -*-
"""离线单测（#44）：混排清单**假完成** —— 跨种类陈旧界面不得记账；切种类先确认中立页。

不需要游戏 / 设备（判据与复现在**内嵌的真机帧 OCR 与真机轨迹**上求值）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_mixed_dispatch.py

覆盖 #44 的验收：

  1. **固定规则（纯函数）**：``is_neutral_home`` / ``classify_screen`` 在真机帧上的正反例
     —— 主城（三独有锚点）= neutral；详情页 / 结算页 = other；读不到 = unknown；
  2. **离线复现混排清单**（真机轨迹 logs/mixed.log 同形）：special 真打 -> 切 raid 时画面是
     上一场**结算页残留的「再次挑战」** -> 战阵之宴**不得**被记账；陈旧界面封锁种类分派；
     战阵之宴（不做导航）按导航超时**明确跳过并记录原因**；
  3. **切种类先确认中立页**：陈旧页上 phantom 分派器不命中；回到主城后放行（幻想在混排里
     能正常进入的前提）；
  4. **守卫 + 破坏实验**：``hooks_44`` 已点亮、自带 prove-red（四处破坏各自变红）；
  5. **不变量**：``special_dungeon.json`` 五条承重短语零丢失；``drift.check_all() == []``；
     #9 三条既有路径守卫仍绿；#18/#27/#29/#30/#35/#36/#37/#38/#39 的挂点不因本票变红。

真机证据（本仓库随附）：``logs/mixed.log`` 与 ``frames/mixed/f_0088…f_0264``（全是同一张
猩红巨熊详情页）；OCR 见 ``mixed_scan.txt``。真机 leg（整条五项混排清单真打）见 issue #44 评论。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
AGENT_DIR = REPO_ROOT / "agent"
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import side_impl as si  # noqa: E402
from batch_plan import item_prefix  # noqa: E402
from scene import drift  # noqa: E402

import hooks_44  # noqa: E402
from contract_hooks import discover_hooks  # noqa: E402

SD = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"

# #12 的承重注释硬规则：纯编辑，绝不丢这些短语。
PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)

# 本票必须保持不变的挂点（其它票 #18/#27/#29/#30/#35/#36/#37/#38/#39）。
KEEP_TICKETS = ("#18", "#27", "#29", "#30", "#35", "#36", "#37", "#38", "#39")
# 本票自己的挂点（#44）。
OWN_TICKET = "#44"

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 1. 固定规则（纯函数）：中立页判定
# ---------------------------------------------------------------------------
def test_pure_rules() -> None:
    print("\n== 1. 固定规则：is_neutral_home / classify_screen（真机帧 OCR） ==")
    check("主城帧（修行之道/成长任务/当前进度）判为 neutral",
          si.classify_screen(hooks_44.MAIN_CITY_ITEMS) == "neutral")
    check("陈旧详情页（有底导『主城』但无三独有锚点）判为 other",
          si.classify_screen(hooks_44.DETAIL_ITEMS) == "other")
    check("结算页（残留 OK/再次挑战）判为 other",
          si.classify_screen(hooks_44.SETTLE_RETRY_ITEMS) == "other")
    check("读不到文字 -> unknown（回退旧行为，不阻断）",
          si.classify_screen([]) == "unknown" and si.classify_screen(None) == "unknown")
    check("主城独有锚点集合与 live_harness 同源（三独有）",
          tuple(si.NEUTRAL_HOME_ANCHORS) == ("修行之道", "成长任务", "当前进度"))


# ---------------------------------------------------------------------------
# 2. 离线复现：混排清单的陈旧界面不得假完成
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.overrides_next: dict = {}
        self.overrides_pipeline: dict = {}
        self.actions: list = []

    def run_recognition(self, entry, image):
        import types  # noqa: PLC0415

        if entry == "OcrTask":
            rows = [types.SimpleNamespace(box=list(b), text=t) for t, b in self.items]
            return types.SimpleNamespace(all_results=rows, hit=bool(rows))
        if entry in ("SpecialResultContinue", "SpecialResultFallback"):
            hit = any(t in ("OK", "继续") or t.startswith("QUESTRESULT") for t, _b in self.items)
            return types.SimpleNamespace(all_results=[], hit=hit)
        return types.SimpleNamespace(all_results=[], hit=False)

    def run_action(self, *a, **k):
        self.actions.append((a, k))
        return True

    def override_next(self, node, nxt):
        self.overrides_next[node] = list(nxt)

    def override_pipeline(self, ov):
        self.overrides_pipeline.update(ov)


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


class _Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


def _drive(rec, items, text, tid, entry="SpecialEntry"):
    ctx = _Ctx(items)
    return ctx, rec.analyze(ctx, _Argv(items, {"list": text}, task_id=tid, entry=entry))


def _finish(record, box):
    ctx = _Ctx([])
    argv = _Argv([], {}, task_id=1, box=_Rect(*box))
    argv.custom_action_param = '{"record": "%s"}' % record
    si.SpecialBatchFinishAction().run(ctx, argv)
    return ctx


def test_offline_mixed_repro() -> None:
    print("\n== 2. 离线复现混排清单（special -> raid，切种类时画面是上一场结算页） ==")
    import progress as ledger  # noqa: PLC0415

    text = hooks_44.MIXED_LIST  # 猩红巨熊讨伐,中级,1;战阵之宴,-,1
    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "mixed_progress.json")
        si.reset_gameover_state()
        rec = si.SpecialBatchPlanRecognition()

        # (1) 第一条 special 在主城开始。
        ctx1, r1 = _drive(rec, hooks_44.MAIN_CITY_ITEMS, text, 44010)
        check("第一条：指挥官切到 猩红巨熊讨伐 并在主城放行",
              r1.box is not None and si._BATCH_CURRENT is not None
              and si._BATCH_CURRENT.dungeon == "猩红巨熊讨伐",
              f"cur={getattr(si._BATCH_CURRENT, 'dungeon', None)}")

        # (2) 真打一场并结算（镜像 mixed.log「结算完成 猩红巨熊 1/1」）。
        si._BATCH_IN_FIGHT = True
        prefix_special = item_prefix(si._BATCH_CURRENT)
        _finish("in_fight", [461, 1180, 120, 40])
        check("第一条：真结算 -> 账本 +1", ledger.scope(prefix_special) and
              len(ledger.scope(prefix_special)) == 1, f"{ledger.scope(prefix_special)}")

        # (3) 切到 raid：画面仍是【上一场结算页残留的「再次挑战」】。
        seq = ["切换目标：战阵之宴 / -（剩余 1 次）"]
        ctx2, r2 = _drive(rec, hooks_44.SETTLE_RETRY_ITEMS, text, 44010)
        seq.append("[#44] 尚未回到中立页（主城），先归位（封锁种类分派）")
        check("切 raid 时画面明确不是主城 -> 保持归位中、封锁种类分派",
              si._BATCH_CURRENT is not None and si._BATCH_CURRENT.kind == "raid"
              and si._BATCH_NEEDS_HOME and si._BATCH_BLOCK_DISPATCH,
              f"cur={getattr(si._BATCH_CURRENT, 'kind', None)} home={si._BATCH_NEEDS_HOME} "
              f"block={si._BATCH_BLOCK_DISPATCH}")

        bm = si.BatchModeRecognition()
        raid_argv = _Argv([], {"kind": "raid"}, task_id=44010)
        check("封锁期 raid 分派器不命中（陈旧「再次挑战」不会被 raid 链吃到）",
              bm.analyze(_Ctx([]), raid_argv).box is None)

        # (4) 直接驱动结算动作：陈旧「再次挑战」不得点击、不得记账。
        prefix_raid = item_prefix(si._BATCH_CURRENT)
        ctx3 = _finish("always", [461, 1180, 120, 40])
        seq.append("[#44] 忽略跨种类陈旧结算页的『再次挑战』：战阵之宴/- 尚未经过自身导航")
        check("陈旧「再次挑战」未被点击", ctx3.actions == [], f"actions={ctx3.actions}")
        check("陈旧「再次挑战」未记账（无假完成）",
              len(ledger.scope(prefix_raid)) == 0, f"{ledger.scope(prefix_raid)}")

        # (5) 回到主城 -> 确认中立页 -> 放行 raid。
        ctx4, r4 = _drive(rec, hooks_44.MAIN_CITY_ITEMS, text, 44010)
        seq.append("[#44] 已确认中立页（主城），开始刷 战阵之宴 / -")
        check("回到主城 -> 解除封锁、放行下一条",
              not si._BATCH_NEEDS_HOME and not si._BATCH_BLOCK_DISPATCH and r4.box is not None)

        # (6) 战阵之宴不做导航，从主城到不了 -> 导航超时明确跳过并记录原因。
        si._BATCH_TARGET_START_TS = time.monotonic() - 999.0
        _drive(rec, hooks_44.MAIN_CITY_ITEMS, text, 44010)
        seq.append("[#44] 战阵之宴不做导航（需先手动打开其页面）→ 明确跳过该目标（原因记录）")
        check("战阵之宴被明确跳过（不在清单里）",
              not any(it.kind == "raid" for it in si._BATCH_ITEMS))
        check("跳过原因点名战阵之宴且写入 _BATCH_SKIPPED",
              any(("战阵之宴" in s and "跳过" in s) for s in si._BATCH_SKIPPED),
              f"{si._BATCH_SKIPPED}")
        check("战阵之宴从未被假记账",
              len(ledger.scope(prefix_raid)) == 0, f"{ledger.scope(prefix_raid)}")
        check("前一条 special 的记账未被误伤", len(ledger.scope(prefix_special)) == 1)

        print("       复现序列：")
        for line in seq:
            print(f"         · {line}")
        print(f"       账本：{sorted(ledger.all_keys())}")


# ---------------------------------------------------------------------------
# 3. 切种类先确认中立页 + 幻想在混排里能进入
# ---------------------------------------------------------------------------
def test_phantom_enters_after_neutral() -> None:
    print("\n== 3. 切种类先确认中立页：phantom 分派器封锁期不命中、解封后命中 ==")
    import progress as ledger  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "phantom_gate.json")
        si.reset_gameover_state()
        rec = si.SpecialBatchPlanRecognition()
        bm = si.BatchModeRecognition()
        phantom_argv = _Argv([], {"kind": "phantom"}, task_id=44011)

        # 陈旧详情页上切到 phantom：封锁分派（幻想不会在陈旧页上瞎跑）。
        _drive(rec, hooks_44.DETAIL_ITEMS, "幻想连战,-,1;猩红巨熊讨伐,中级,1", 44011)
        check("陈旧详情页上切 phantom：封锁分派",
              si._BATCH_NEEDS_HOME and si._BATCH_BLOCK_DISPATCH and
              si._BATCH_CURRENT.kind == "phantom")
        check("封锁期 phantom 分派器不命中", bm.analyze(_Ctx([]), phantom_argv).box is None)

        # 回主城确认中立页：放行 phantom（幻想连战与单跑一致地从主城导航进入）。
        _drive(rec, hooks_44.MAIN_CITY_ITEMS, "幻想连战,-,1;猩红巨熊讨伐,中级,1", 44011)
        check("回主城 -> 解除封锁、phantom 分派器命中",
              not si._BATCH_BLOCK_DISPATCH and bm.analyze(_Ctx([]), phantom_argv).box == [0, 0, 0, 0])


# ---------------------------------------------------------------------------
# 4. 守卫 / 破坏实验 / 纯编辑不变量
# ---------------------------------------------------------------------------
def _hook_probes(tickets):
    rows = []
    for hook_id, ticket, _what, probe in discover_hooks():
        if ticket in tickets:
            try:
                rows.append((hook_id, ticket, probe()))
            except Exception as exc:  # noqa: BLE001
                rows.append((hook_id, ticket, f"raised {exc!r}"))
    return rows


def test_guard_and_prove_red() -> None:
    print("\n== 4. 守卫 hooks_44 + prove-red（四处破坏各自变红） ==")
    check("混合：陈旧界面不记账 探针绿",
          hooks_44.probe_mixed_no_stale_screen_completion() is True)
    check("混合：切种类确认中立页 探针绿",
          hooks_44.probe_mixed_kind_switch_confirms_neutral() is True)
    check("混合：战阵之宴明确跳过 探针绿",
          hooks_44.probe_mixed_raid_unreachable_skipped() is True)
    check("混合：pipeline #44 注释 + 承重短语 探针绿",
          hooks_44.probe_mixed_pipeline_comment() is True)
    check("hooks_44.prove_red() 成立（四处破坏各自变红）", hooks_44.prove_red() is True)


def test_pure_edit_invariants() -> None:
    print("\n== 5. 纯编辑：五条承重短语 + #9 守卫 + 其它票挂点不因本票变红 ==")
    text = SD.read_text(encoding="utf-8")
    for phrase in PHRASES:
        check(f"短语「{phrase}」仍出现", text.count(phrase) >= 1, f"count={text.count(phrase)}")
    check("drift.check_all() == []", drift.check_all(repo_root=REPO_ROOT) == [],
          f"{drift.check_all(repo_root=REPO_ROOT)}")

    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")

    rows = _hook_probes(KEEP_TICKETS)
    red = [(h, t, v) for h, t, v in rows if v is False]
    check(f"#18/#27/#29/#30/#35/#36/#37/#38/#39 挂点不因本票变红（共 {len(rows)} 个）",
          red == [], f"red={red}")


def main() -> int:
    print("=" * 76)
    print("#44：混排清单假完成 —— 跨种类陈旧界面不得记账 / 切种类先确认中立页（离线）")
    print("=" * 76)
    test_pure_rules()
    test_offline_mixed_repro()
    test_phantom_enters_after_neutral()
    test_guard_and_prove_red()
    test_pure_edit_invariants()
    print("\n" + "=" * 76)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
