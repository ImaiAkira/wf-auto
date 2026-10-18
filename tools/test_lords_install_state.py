# -*- coding: utf-8 -*-
"""离线测试：**安装态**（没有 ``scene/``）下的领主战「全难度解禁」（#100 后续票）。

跑：

    .venv\\Scripts\\python.exe tools\\test_lords_install_state.py

★它证的是什么（真隔离，不是「把 ``_logic`` 打桩成 ``None``」那种自欺）★

1. 把 ``agent/`` **整目录**拷到一个临时目录 —— **不带** ``scene/``、不带 ``tools/``、不带仓根。
   子进程里 ``import scene`` 必须失败：这正是 ``tools/install.py`` 发出去的 ``install/agent``
   的真实形态（``install_agent`` 只拷 ``agent/``）。
2. 在那个孤立目录里 ``import lords_impl`` 能起、``_logic()`` 回落到**逐字冻结快照**、
   ``_registry()`` / ``_row_regex()`` 用冻结表 —— 不再「识别不命中」。
3. 纯逻辑逐项对账：``parse_progress`` / ``plan_round`` / ``should_stop`` /
   ``group_progress_rows`` / ``round_gained`` 的样例结果与**仓库态真源**逐项相等
   （含 no_chain / m_conflict / unknown_row / duplicate_row / N>M 抛错 与原因文案）。
4. 识别 / 动作整条链：``lords_progress mode=read`` 命中且 detail.rows 三行齐、
   ``mode=pick`` 三跳（行 → 该档【战斗】 → 编队页【挑战】）框中心正确、
   ``lords_unlock_step`` 点下去并记 1 场、点过挑战后禁双击；行名容错 ``^红嫉族?机兵$`` 在
   安装态也生效。
5. 反证：真源与快照**都**取不到时仍**不命中、不假成功**（``INSTALL_STATE_REASON``）。

★它不证什么（诚实边界）★

* **不碰设备**：OCR / 点击全是假实现，帧读数是 ``tools/frames/`` 那几张真机帧的 720 空间读数；
* **不证**「``install/agent`` 已经刷新」—— 那是 ``tools/install.py`` 与真机验收的事；
* **不证**真机接线（页签切换 / 列表滚动）—— 与 ``hooks_100`` 同一条诚实边界。

两侧守卫分工：``tools/contract_hooks/hooks_100.py`` 的 ``lords-install-snapshot-parity`` /
``lords-install-behavior-parity`` 在**同一进程**里钉「快照 == 真源 + 行为等价」；
本文件钉「**离开仓库也能跑**」（两个进程、两套 ``sys.path``）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
TOOLS_DIR = Path(__file__).resolve().parent

for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(TOOLS_DIR / "contract_hooks"), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lords_impl as impl  # noqa: E402  仓库态（有 scene/），只用来算「真源侧」的期望值
from scene import lords_unlock as lu  # noqa: E402
from scene.lords import LORDS  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 样例（**唯一一份**：写进 cases.json 交给孤立进程，父进程用同一份算真源期望）
# ---------------------------------------------------------------------------
#: 真机帧读数（720 空间；源 = tools/frames/*.png 的 OCR，1080 值 ÷1.5，
#: 与 hooks_100.LIST_FRAME / DETAIL_FRAME / TEAM_FRAME 同一批数字）。
FRAMES: dict = {
    "list": [
        ["领主战", [135, 388, 90, 35]],
        ["降临讨伐", [481, 389, 117, 33]],
        ["更新列表", [615, 328, 82, 28]],
        ["艾基尔·嫉妒讨伐", [202, 640, 197, 28]], ["通关数1/4", [547, 688, 127, 28]],
        ["猩红巨熊讨伐", [201, 783, 164, 28]], ["通关数3/4", [547, 832, 126, 28]],
        ["八岐大蛇讨伐", [201, 1072, 165, 28]], ["通关数4/4", [547, 1120, 126, 28]],
    ],
    "detail": [
        ["推荐编成", [37, 353, 65, 20]],
        # ★D6（本票 ①）：详情页每一档带状态徽标（真机版式：徽标在档名上方 ≈70px）。
        #   最上面那档已 COMPLETE!!，未通关的是第二行（高级+，NEW）⇒ 选档必须按徽标，
        #   **不是**「取最上面那个战斗框」（旧行为，已被真机B 第 3 轮验收推翻）。
        ["COMPLETE!!", [15, 235, 126, 22]],
        ["妖狐超级", [135, 305, 169, 19]], ["战斗", [58, 334, 21, 11]],
        ["NEW", [15, 363, 46, 20]],
        ["妖狐高级+", [135, 433, 181, 19]], ["战斗", [60, 461, 18, 11]],
        ["COMPLETE!!", [15, 490, 123, 24]],
        ["妖狐高级", [135, 560, 169, 19]], ["战斗", [60, 591, 18, 11]],
        ["COMPLETE!!", [15, 617, 127, 22]],
        ["妖狐中级", [135, 687, 169, 19]], ["战斗", [60, 715, 18, 11]],
    ],
    "team": [
        ["自动续战", [20, 1060, 80, 24]],
        ["挑战", [297, 1069, 80, 47]],
    ],
    "fuzzy": [
        ["降临讨伐", [481, 389, 117, 33]],
        ["红嫉族机兵", [201, 783, 164, 28]], ["通关数2/4", [547, 832, 126, 28]],
    ],
}

#: ``plan_round`` 样例（覆盖 no_chain / m_conflict / unknown_row / duplicate_row / N>M 抛错）。
ROW_CASES: list = [
    ["正常：链[N]", [["妖狐讨伐", 1, 4]]],
    ["起始档：链[0]", [["妖狐讨伐", 0, 4]]],
    ["最后一档：链[3]", [["妖狐讨伐", 3, 4]]],
    ["已 M/M 不产生目标", [["八岐大蛇讨伐", 4, 4], ["无猾机兵", 5, 5]]],
    ["no_chain：有 M 但链未采集", [["艾基尔·嫉妒讨伐", 1, 4]]],
    ["no_chain：pending 成员", [["管理者讨伐", 1, 4]]],
    ["m_conflict：M 对不上", [["妖狐讨伐", 1, 3]]],
    ["unknown_row：花名册外", [["降临过伐", 1, 4]]],
    ["duplicate_row", [["妖狐讨伐", 1, 4], ["妖狐讨伐", 2, 4]]],
    ["all_done", [["八岐大蛇讨伐", 4, 4]]],
    ["零行 ≠ 全通", []],
    ["映射输入", [{"name": "红嫉机兵", "n": 2, "m": 4}]],
    ["N>M：抛 LordsDataError", [["妖狐讨伐", 4, 3]]],
    ["M=0：抛 LordsDataError", [["妖狐讨伐", 1, 0]]],
]

#: ``should_stop`` 样例（覆盖 played==0 的两条分支 + 三条终结）。
STOP_CASES: list = [
    ["全 M/M（主）", {"all_done": True, "rows_read": 4, "planned": 0, "played": 1, "sessions": 3}],
    ["零行却判全通（假收工）", {"all_done": True, "rows_read": 0, "sessions": 0}],
    ["场次上限 60", {"all_done": False, "rows_read": 4, "planned": 2, "played": 2, "sessions": 60}],
    ["上限差一场", {"all_done": False, "rows_read": 4, "planned": 2, "played": 2, "sessions": 59}],
    ["连续 2 轮无新解锁", {"all_done": False, "rows_read": 4, "planned": 1, "played": 2,
                          "sessions": 8, "no_progress_rounds": 2}],
    ["连续 1 轮不停", {"all_done": False, "rows_read": 4, "planned": 1, "played": 2,
                      "sessions": 8, "no_progress_rounds": 1}],
    ["played==0 且零目标", {"all_done": False, "rows_read": 4, "planned": 0, "played": 0}],
    ["played==0 且计划了没打", {"all_done": False, "rows_read": 4, "planned": 3, "played": 0}],
    ["正常推进", {"all_done": False, "rows_read": 4, "planned": 2, "played": 2, "sessions": 5}],
    ["全通优先于场次上限", {"all_done": True, "rows_read": 4, "planned": 0, "played": 1, "sessions": 60}],
]

#: ``group_progress_rows`` 样例（真机帧 + 归属不上 / 徽标 / 纵向太远 / 空帧）。
ITEM_CASES: list = [
    ["真机列表页帧", FRAMES["list"]],
    ["读不出归属 → orphans", [["更新列表", [615, 328, 82, 28]], ["通关数1/1", [547, 688, 127, 28]]]],
    ["徽标不抢行名", FRAMES["list"] + [["COMPLETE!!", [15, 1022, 124, 24]]]],
    ["纵向太远不配对", [["艾基尔·嫉妒讨伐", [202, 300, 197, 28]], ["通关数1/4", [547, 688, 127, 28]]]],
    ["空帧", []],
]

#: ``parse_progress`` 样例（正例 / 全角 / 抖动 / 歧义 / 裸数字 / 分母 0）。
TEXT_CASES: list = [
    "通关数3/4", "通关数 3/4", "通关数 3 / 4", "通关数 全5/5", "通关数：4/4", "通关数３／４",
    "通关数1|4", "通关数 3/4/5", "通关数 3/", "角色数 3/4", "1234", "通关数 100/120",
    "通关数3/0", "通关数4/3", "",
]

#: ``round_gained`` 样例（涨 / 不涨 / 首见 / 倒退）。
GAINED_CASES: list = [
    [{"妖狐讨伐": 1, "猩红巨熊讨伐": 3}, [["妖狐讨伐", 2, 4], ["猩红巨熊讨伐", 3, 4]]],
    [{"妖狐讨伐": 2}, [["妖狐讨伐", 2, 4]]],
    [None, [["妖狐讨伐", 0, 4]]],
    [{"妖狐讨伐": 2}, [["妖狐讨伐", 1, 4]]],
]


# ---------------------------------------------------------------------------
# 孤立目录里的探针（子进程执行；**只依赖 agent/ 里的文件**）
# ---------------------------------------------------------------------------
#: 这个脚本**故意**不 import 仓库里的任何东西（``tools/`` / ``scene/`` 都不在孤立目录里）：
#: 它写的就是「装好的产品」那一侧的样子。标准输出只留最后一行 JSON（中间的业务日志被吞进
#: 内存缓冲，随结果回传给父进程做证据）。
_PROBE = r'''
import io
import json
import os
import sys

agent_dir = sys.argv[1]
sys.path.insert(0, agent_dir)

import lords_impl as li

cases = json.loads(
    open(os.path.join(os.path.dirname(agent_dir), "cases.json"), encoding="utf-8").read()
)
frames = cases["frames"]

_real_stdout = sys.stdout
sys.stdout = io.StringIO()          # 业务 print（[lords] ...）不许污染 JSON 出口


class Ctx:
    def __init__(self):
        self.overrides = []
        self.actions = []

    def override_next(self, node, nxt):
        self.overrides.append([node, list(nxt)])

    def run_action(self, name, box=None, **kw):
        self.actions.append([name, list(box) if box else None])
        return True

    def clicked_centers(self):
        # PubClick 的 (cx-1, cy-1, 2, 2) 还原成点击中心
        return [[b[0] + 1, b[1] + 1] for n, b in self.actions
                if n == "PubClick" and b and len(b) == 4]


class TaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class Argv:
    def __init__(self, reco=None, box=None, node="LordsReadProgress", task_id=1):
        self.image = None
        self.custom_recognition_param = json.dumps(reco or {}, ensure_ascii=False)
        self.custom_action_param = "{}"
        self.box = box
        self.node_name = node
        self.task_detail = TaskDetail(task_id)


_queue = []


def fake_ocr(context, image, entry="OcrTask"):
    return _queue.pop(0) if _queue else []


li._ocr = fake_ocr


def logic():
    return li._logic()


def norm_plan(plan):
    return {
        "targets": [[t.row_name, t.difficulty, t.n, t.m] for t in plan.targets],
        "all_done": bool(plan.all_done),
        "rows": [[r.name, r.n, r.m, list(r.name_box), list(r.progress_box)] for r in plan.rows],
        "problems": [[p.kind, p.row_name, p.detail] for p in plan.problems],
        "pairs": [[a, b] for a, b in plan.pairs],
        "needs_detail": [t.row_name for t in plan.needs_detail],
    }


def plan_outcome(rows):
    lg = logic()
    try:
        return ["OK", norm_plan(lg.plan_round(rows, li._registry()))]
    except lg.LordsDataError as exc:
        return ["LordsDataError", str(exc)]
    except Exception as exc:  # noqa: BLE001
        return ["EXC:" + type(exc).__name__, str(exc)]


def norm_rows(result):
    rows, orphans = result
    return {
        "rows": [[r.name, r.n, r.m, list(r.name_box), list(r.progress_box)] for r in rows],
        "orphans": [[text, list(box)] for text, box in orphans],
    }


result = {
    "can_import_scene": None,
    "logic_is_snapshot": logic() is li._SnapshotLogic,
    "logic_name": getattr(logic(), "__name__", None),
    "registry_len": len(li._registry()),
}

try:
    import scene  # noqa: F401
    result["can_import_scene"] = True
except ModuleNotFoundError:
    result["can_import_scene"] = False

result["parse"] = {text: logic().parse_progress(text) for text in cases["text_cases"]}
result["plans"] = {label: plan_outcome(rows) for label, rows in cases["row_cases"]}
result["stops"] = {
    label: list(logic().should_stop(logic().UnlockState(**kwargs)))
    for label, kwargs in cases["stop_cases"]
}
result["group_rows"] = {
    label: norm_rows(logic().group_progress_rows(items)) for label, items in cases["item_cases"]
}
result["gained"] = {
    str(index): [
        bool(logic().round_gained(previous, rows)[0]),
        list(logic().round_gained(previous, rows)[1]),
    ]
    for index, (previous, rows) in enumerate(cases["gained_cases"])
}
result["row_regex"] = {
    "红嫉机兵": li._row_regex("红嫉机兵"),
    "妖狐讨伐": li._row_regex("妖狐讨伐"),
    "花名册外的行": li._row_regex("花名册外的行"),
}

# -- 识别 + 动作：读列表 → 三跳（行 → 档 → 【挑战】）-------------------------
reco = li.LordsProgressRecognition()
action = li.LordsUnlockAction()
li.reset_sessions()
_queue[:] = [frames["list"], frames["list"], frames["detail"], frames["team"]]
ctx = Ctx()
read = reco.analyze(ctx, Argv(reco={"mode": "read"}, task_id=11))
_detail = read.detail or {}
picks = []
for _hop in range(3):
    step = reco.analyze(ctx, Argv(reco={"mode": "pick"}, node="LordsPickTarget", task_id=11))
    ok = action.run(ctx, Argv(task_id=11, box=step.box))
    picks.append([(step.detail or {}).get("what"), list(step.box or []), bool(ok)])
session = li._session(11)
result["read"] = {
    "box": list(read.box or []),
    "rows": [[r["name"], r["n"], r["m"]] for r in (_detail.get("rows") or [])],
    "targets": [list(t) for t in (_detail.get("targets") or [])],
    "problems": [[p[0], p[1]] for p in (_detail.get("problems") or [])],
    "stop": bool(_detail.get("stop")),
    "reason": _detail.get("reason"),
}
result["picks"] = picks
result["clicks"] = ctx.clicked_centers()
result["sessions_played"] = session.sessions_played
result["challenge_pending"] = session.challenge_pending

# 点过【挑战】之后停在同一编队页 → 不许再给出可点框（禁双击在安装态也成立）
_queue[:] = [frames["team"]]
again = reco.analyze(ctx, Argv(reco={"mode": "pick"}, node="LordsPickTarget", task_id=11))
result["double_click_box"] = None if again.box is None else list(again.box)

# -- 行名容错：目标行名干净、当帧被 OCR 读成「红嫉族机兵」------------------------
li.reset_sessions()
_queue[:] = [frames["fuzzy"]]
ctx2 = Ctx()
session2 = li._session(22)
session2.targets = [li._SnapshotLogic.Target("红嫉机兵", "中级", 2, 4)]
fuzzy = reco.analyze(ctx2, Argv(reco={"mode": "pick"}, node="LordsPickTarget", task_id=22))
result["fuzzy_pick"] = {
    "what": (fuzzy.detail or {}).get("what"),
    "box": list(fuzzy.box or []),
}

# -- 反证：真源与快照**都**取不到 → 不命中、不假成功 ---------------------------
saved_logic = li._logic
li._logic = lambda: None
none_res = reco.analyze(Ctx(), Argv(reco={"mode": "read"}, task_id=33))
result["no_logic"] = {
    "box": None if none_res.box is None else list(none_res.box),
    "reason": (none_res.detail or {}).get("reason"),
    "install_state_reason": li.INSTALL_STATE_REASON,
}
li._logic = saved_logic

# -- 动作在没有框时如实失败（不静默成功）--------------------------------------
result["action_without_box"] = bool(action.run(Ctx(), Argv(task_id=44, box=None)))

log = sys.stdout.getvalue()
sys.stdout = _real_stdout
result["log"] = log
_real_stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
_real_stdout.flush()
'''


#: 反证探针：真源**在场但自己炸**时，回落必须不发生（响亮失败，不伪装成「安装态」）。
_BROKEN_TRUTH_PROBE = r'''
import sys
sys.path.insert(0, sys.argv[1])
import lords_impl as li

try:
    li._logic()
except Exception as exc:
    print("RAISED:" + type(exc).__name__ + ":" + str(exc))
else:
    print("FALLBACK")
'''


def _broken_truth_root() -> Path:
    """``agent/`` 拷进临时目录 + 一个**会炸**的 ``scene/lords_unlock.py``（模拟真源坏了）。"""
    root = Path(tempfile.mkdtemp(prefix="wf_lords_broken_"))
    shutil.copytree(
        AGENT_DIR,
        root / "agent",
        ignore=shutil.ignore_patterns("__pycache__", "debug", "*.pyc"),
    )
    scene = root / "scene"
    scene.mkdir()
    (scene / "__init__.py").write_text("", encoding="utf-8")
    (scene / "lords_unlock.py").write_text(
        "raise RuntimeError('真源坏了：这是一次故意制造的 import 期异常')\n", encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# 准备 / 执行
# ---------------------------------------------------------------------------
def _isolated_root() -> Path:
    """把 ``agent/`` 整目录拷到一个**没有 scene/** 的临时目录（= install/agent 的形态）。"""
    root = Path(tempfile.mkdtemp(prefix="wf_lords_install_"))
    shutil.copytree(
        AGENT_DIR,
        root / "agent",
        ignore=shutil.ignore_patterns("__pycache__", "debug", "*.pyc"),
    )
    cases = {
        "frames": FRAMES,
        "text_cases": TEXT_CASES,
        "row_cases": ROW_CASES,
        "stop_cases": STOP_CASES,
        "item_cases": ITEM_CASES,
        "gained_cases": GAINED_CASES,
    }
    (root / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return root


def _run_probe(root: Path) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)          # 别让父进程的搜索路径把仓根/scene 偷进来
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(root / "agent")],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "孤立进程里的 lord_impl 探针失败（安装态读不出/点不动就是本票要修的那个病）：\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"孤立进程没有输出 JSON。stderr：{proc.stderr}")
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# 真源侧期望值（父进程算：这里有 scene/）
# ---------------------------------------------------------------------------
def _truth_plan(rows) -> list:
    try:
        plan = lu.plan_round(rows, tuple(LORDS))
    except lu.LordsDataError as exc:
        return ["LordsDataError", str(exc)]
    except Exception as exc:  # noqa: BLE001
        return ["EXC:" + type(exc).__name__, str(exc)]
    return [
        "OK",
        {
            "targets": [[t.row_name, t.difficulty, t.n, t.m] for t in plan.targets],
            "all_done": bool(plan.all_done),
            "rows": [[r.name, r.n, r.m, list(r.name_box), list(r.progress_box)] for r in plan.rows],
            "problems": [[p.kind, p.row_name, p.detail] for p in plan.problems],
            "pairs": [[a, b] for a, b in plan.pairs],
            "needs_detail": [t.row_name for t in plan.needs_detail],
        },
    ]


def _truth_rows(items) -> dict:
    rows, orphans = lu.group_progress_rows(items)
    return {
        "rows": [[r.name, r.n, r.m, list(r.name_box), list(r.progress_box)] for r in rows],
        "orphans": [[text, list(box)] for text, box in orphans],
    }


# ---------------------------------------------------------------------------
# 1. 孤立目录的形状
# ---------------------------------------------------------------------------
def test_isolated_dir(root: Path) -> None:
    print("\n== 1. 孤立目录：只有 agent/，没有 scene/（= install/agent 的真实形态）==")
    check("临时目录里有 agent/", (root / "agent").is_dir())
    check("临时目录里**没有** scene/", not (root / "scene").exists(), f"root={root}")
    check("临时目录里没有 tools/", not (root / "tools").exists())
    agent_py = sorted(p.name for p in AGENT_DIR.glob("*.py"))
    copy_py = sorted(p.name for p in (root / "agent").glob("*.py"))
    check(f"agent/ 整目录拷全（{len(agent_py)} 个 .py）", agent_py == copy_py,
          f"缺 {sorted(set(agent_py) - set(copy_py))}")
    check("lords_impl.py 在拷贝里", (root / "agent" / "lords_impl.py").is_file())


# ---------------------------------------------------------------------------
# 2. 孤立进程能 import、且真的没有 scene
# ---------------------------------------------------------------------------
def test_import_in_isolated(probe: dict) -> None:
    print("\n== 2. 孤立进程：import scene 失败、import lords_impl 成功、判定真源回落快照 ==")
    check("子进程里 import scene 失败（真隔离，不是打桩）", probe["can_import_scene"] is False,
          f"can_import_scene={probe['can_import_scene']}")
    check("_logic() 回落到冻结快照（_SnapshotLogic）", probe["logic_is_snapshot"] is True,
          f"logic={probe['logic_name']!r}")
    check("_registry() 是完整花名册（46 位）", probe["registry_len"] == len(LORDS),
          f"got={probe['registry_len']} / 真源 {len(LORDS)}")
    check("回落时打印了一行「冻结快照」说明（现场可诊断）", "冻结快照" in probe.get("log", ""),
          f"log[:120]={probe.get('log', '')[:120]!r}")


# ---------------------------------------------------------------------------
# 3. 纯逻辑逐项对账（安装态快照 vs 仓库态真源）
# ---------------------------------------------------------------------------
def test_pure_logic(probe: dict) -> None:
    print("\n== 3. 纯逻辑对账：安装态（快照）== 仓库态（真源）逐项 ==")
    bad = []
    for text in TEXT_CASES:
        want = lu.parse_progress(text)
        got = probe["parse"][text]
        got = None if got is None else tuple(got)      # JSON 把 tuple 变 list，归一化再比
        if got != want:
            bad.append((text, want, got))
    check(f"parse_progress 全部 {len(TEXT_CASES)} 条样例一致", bad == [], f"mismatch={bad}")

    bad = []
    for label, rows in ROW_CASES:
        want = _truth_plan(rows)
        got = probe["plans"][label]
        if want != got:
            bad.append((label, want, got))
    check(f"plan_round 全部 {len(ROW_CASES)} 条样例一致（含问题文案与抛错）", bad == [],
          f"mismatch={bad}")

    bad = []
    for label, kwargs in STOP_CASES:
        want = list(lu.should_stop(lu.UnlockState(**kwargs)))
        got = probe["stops"][label]
        if want != got:
            bad.append((label, want, got))
    check(f"should_stop 全部 {len(STOP_CASES)} 条样例一致（含用户可见原因）", bad == [],
          f"mismatch={bad}")

    bad = []
    for label, items in ITEM_CASES:
        want = _truth_rows(items)
        got = probe["group_rows"][label]
        if want != got:
            bad.append((label, want, got))
    check(f"group_progress_rows 全部 {len(ITEM_CASES)} 条样例一致（含 orphans 不静默丢）",
          bad == [], f"mismatch={bad}")

    bad = []
    for index, (previous, rows) in enumerate(GAINED_CASES):
        gained, names = lu.round_gained(previous, rows)
        want = [bool(gained), list(names)]
        got = probe["gained"][str(index)]
        if want != got:
            bad.append((index, want, got))
    check(f"round_gained 全部 {len(GAINED_CASES)} 条样例一致", bad == [], f"mismatch={bad}")

    # 点名分支必须在样例里真的被走到（否则「一致」是空的）
    kinds = set()
    for label, rows in ROW_CASES:
        got = probe["plans"][label]
        if got[0] == "OK":
            kinds.update(problem[0] for problem in got[1]["problems"])
    for kind in ("no_chain", "m_conflict", "unknown_row", "duplicate_row"):
        check(f"样例覆盖分支 {kind}", kind in kinds, f"现有 {sorted(kinds)}")
    check("样例覆盖 N>M 抛 LordsDataError 分支",
          any(probe["plans"][label][0] == "LordsDataError" for label, _rows in ROW_CASES))
    reasons = " | ".join(probe["stops"][label][1] for label, _kw in STOP_CASES)
    for phrase in ("全部解禁", "场次上限", "连续", "防死循环"):
        check(f"样例覆盖收工文案 {phrase}", phrase in reasons)


# ---------------------------------------------------------------------------
# 4. 识别 + 动作（安装态也必须命中、必须点得出去）
# ---------------------------------------------------------------------------
def test_recognition_and_action(probe: dict) -> None:
    print("\n== 4. 识别 / 动作：安装态下 read 命中、三跳点到位、记一场、禁双击 ==")
    read = probe["read"]
    check("read 命中列表页（box 非空）", read["box"] != [], f"got={read['box']}")
    check("detail.rows 读出 3 行", [r[0] for r in read["rows"]]
          == ["艾基尔·嫉妒讨伐", "猩红巨熊讨伐", "八岐大蛇讨伐"], f"got={read['rows']}")
    check("detail.rows 的 N/M 与真机读数一致",
          [[r[1], r[2]] for r in read["rows"]] == [[1, 4], [3, 4], [4, 4]], f"got={read['rows']}")
    check("第一轮不收工（还没打）", read["stop"] is False, f"reason={read['reason']!r}")
    check("targets 是 [(行名, 档位)] 形状且不含已 4/4 的行",
          all(len(t) == 2 for t in read["targets"]) and ["八岐大蛇讨伐", None] not in read["targets"],
          f"got={read['targets']}")

    check("三跳之一 row（列表页点目标行）",
          probe["picks"][0][0] == impl.WHAT_ROW and probe["picks"][0][1] == [202, 640, 197, 28],
          f"got={probe['picks'][0]}")
    # ★D6（本票 ①）：详情页帧最上面那档是 COMPLETE!!，未通关的是第二行「高级+」（NEW）。
    #   安装态也必须**按徽标选**：点 [60,461]（高级+）而不是 [58,334]（最上面的超级）。
    check("三跳之二 tier（详情页点**未通关**那档【战斗】，不是最上面）",
          probe["picks"][1][0] == impl.WHAT_TIER and probe["picks"][1][1] == [60, 461, 18, 11],
          f"got={probe['picks'][1]}")
    check("★最上面那档（已 COMPLETE!!）的【战斗】不被点★",
          probe["picks"][1][1] != [58, 334, 21, 11],
          f"got={probe['picks'][1]}")
    check("三跳之三 challenge（编队页点【挑战】）",
          probe["picks"][2][0] == impl.WHAT_CHALLENGE and probe["picks"][2][1] == [297, 1069, 80, 47],
          f"got={probe['picks'][2]}")
    check("三次动作都返回 True（真的点下去了）", all(p[2] for p in probe["picks"]),
          f"got={probe['picks']}")
    check("点击中心 = 三个框中心",
          probe["clicks"] == [[300, 654], [69, 466], [337, 1092]],
          f"got={probe['clicks']}")
    check("点一次【挑战】记 1 场", probe["sessions_played"] == 1, f"got={probe['sessions_played']}")
    check("点过【挑战】后置「禁双击」闩", probe["challenge_pending"] is True)
    check("再 pick 一次不给可点框（禁双击在安装态也成立）", probe["double_click_box"] is None,
          f"got={probe['double_click_box']}")

    check("行名容错：安装态也认「红嫉族机兵」", probe["fuzzy_pick"]["what"] == impl.WHAT_ROW
          and probe["fuzzy_pick"]["box"] == [201, 783, 164, 28], f"got={probe['fuzzy_pick']}")
    check("冻结的容错正则 == 真源（^红嫉族?机兵$）",
          probe["row_regex"]["红嫉机兵"] == "^红嫉族?机兵$",
          f"got={probe['row_regex']['红嫉机兵']!r}")
    check("花名册外的行不编正则（绝不猜）", probe["row_regex"]["花名册外的行"] is None,
          f"got={probe['row_regex']['花名册外的行']!r}")


# ---------------------------------------------------------------------------
# 5. 反证：两条路都不通 → 不命中、不假成功
# ---------------------------------------------------------------------------
def test_no_logic_no_fake_success(probe: dict) -> None:
    print("\n== 5. 反证：真源与快照都取不到 → 不命中、不假成功 ==")
    check("识别不命中（box 为 None）", probe["no_logic"]["box"] is None,
          f"got={probe['no_logic']['box']}")
    check("原因串 == INSTALL_STATE_REASON", probe["no_logic"]["reason"] == probe["no_logic"]["install_state_reason"],
          f"reason={probe['no_logic']['reason']!r}")
    check("动作没有框时如实失败（返回 False）", probe["action_without_box"] is False)


# ---------------------------------------------------------------------------
# 6. 回落边界：只吞 ModuleNotFoundError（真源坏了要响亮失败，不许悄悄换快照）
# ---------------------------------------------------------------------------
def test_fallback_is_narrow() -> None:
    print("\n== 6. 回落边界：真源**在场但自己炸** → 响亮失败，不悄悄换成快照 ==")
    root = _broken_truth_root()
    try:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, "-c", _BROKEN_TRUTH_PROBE, str(root / "agent")],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=env,
        )
        out = (proc.stdout or "").strip().splitlines()
        got = out[-1] if out else ""
        check("真源 import 期异常**抛穿**（没有被伪装成安装态）",
              got.startswith("RAISED:RuntimeError"), f"got={got!r} stderr={proc.stderr[:200]!r}")
        check("没有悄悄回落到快照", got != "FALLBACK", f"got={got!r}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 78)
    print("离线测试：安装态（install/agent，没有 scene/）下的领主战解禁")
    print("=" * 78)

    root = _isolated_root()
    try:
        print(f"\n孤立目录：{root}")
        test_isolated_dir(root)
        probe = _run_probe(root)
        test_import_in_isolated(probe)
        test_pure_logic(probe)
        test_recognition_and_action(probe)
        test_no_logic_no_fake_success(probe)
        test_fallback_is_narrow()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 78)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
