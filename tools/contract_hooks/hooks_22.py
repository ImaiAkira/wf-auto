# -*- coding: utf-8 -*-
"""#22：单目标打满配置次数后必须**明确收工**（复用 ``SpecialBatchStop``）的挂点（已点亮）。

seam：``scene.chain``（结算终点 / 终端 → pipeline 节点的映射）
+ ``assets/resource/pipeline/special_dungeon.json``（终止节点 ``SpecialBatchStop``）
+ ``agent/side_impl.py``（结算动作里的单目标收工闸）。

背景（#13 第 3 次真机运行，15:50:48→15:54:06，约 60 轮、每轮 ~3s）
----------------------------------------------------------------
必需的那条链已通（主城 → 领主战 → 结算 → 归位），但**结算+归位之后无限重进同一目标**：

    SpecialEntry → SpecialOpenLord → SpecialTabLord → SpecialEnterBoss
                 → PubReturnHome ×2 → 重复

**根因是既有缺口**：单目标模式**没有收工条件**。配置次数由选项「打几次」写成
``SpecialFightTargetRow.max_hit``（「限制战斗开始次数」）；打满后它只是「不再从候选里
命中」，而 ``SpecialBatchStop``（本文件要接的终止节点）**没有任何东西指向它** ——
唯一的前进方向就是后缀兜底归位回枢纽 → 重进。

两个守卫（都在本文件里，prove-red 也在本文件里）
------------------------------------------------
1. ``single-target-settle-stop`` —— 收工边**在场且接线正确**：
   * 链：``终端pipeline节点[收工] == "SpecialBatchStop"``；``结算终点`` 在
     ``已打次数 >= 目标次数`` 时给收工、否则归位；``decide`` / ``navigate``（结算页）一致；
   * pipeline：``SpecialBatchStop`` 在场且是 ``DirectHit + StopTask``、``next`` 为空；
     结算节点的动作是 custom ``special_batch_finish``（收工闸的落点）；
   * agent：单目标 + 打满 → ``override_next(<结算节点>, ["SpecialBatchStop"])``；
     未打满 / 不限次（无 ``max_hit``）/ 批量模式 / 非 special 入口 / 读不到节点定义
     → **绝不覆盖**（绝不误停任务）。
2. ``single-target-no-reenter`` —— **确定性复现**：打满后接线态必经 ``SpecialBatchStop``
   收工，旧形态（无收工边）走到步数上限 = 无限重进。

★prove-red★（在文件末尾，``python tools\\contract_hooks\\hooks_22.py``）：
   * 在临时副本上**摘掉结算里的收工接线**（``agent/side_impl.py``）→ 守卫红；
   * 在临时副本上**把链的结算终点改回恒归位**（``scene/chain.py``）→ 两个守卫各自红。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

_PIPELINE_REL = "assets/resource/pipeline"
_SD = "special_dungeon.json"

# 链上的收工终点 → pipeline 终止节点（#22 只允许这一个落点）。
STOP_TERMINAL = "收工"
STOP_NODE = "SpecialBatchStop"

# 单目标收工的结算落点（动作 = custom special_batch_finish）与配置次数节点。
SETTLE_NODE = "SpecialResultContinue"
FIGHT_NODE = "SpecialFightTargetRow"

# 复现模型用到的真实边（若产物被改动，模型必须跟着报红而不是静默漂移）。
REQUIRED_EDGES = (
    ("SpecialEntry", "SpecialOpenLord"),
    ("SpecialOpenLord", "SpecialTabLord"),
    ("SpecialTabLord", "SpecialEnterBoss"),
    ("SpecialEnterBoss", "SpecialFightTargetRow"),
    ("SpecialFightTargetRow", "SpecialModeSolo"),
    ("SpecialBattleWait", "SpecialResultContinue"),
)

LORD = {"成员": "八岐大蛇讨伐", "难度": "高级"}


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def agent_on_path() -> None:
    """把 agent 目录放到 sys.path【末尾】——同样让坏副本经 PYTHONPATH 抢先。"""
    if str(REPO_ROOT / "agent") not in sys.path:
        sys.path.append(str(REPO_ROOT / "agent"))


def load_files(pipeline_dir=None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(pipeline_dir) if pipeline_dir else REPO_ROOT / _PIPELINE_REL
    return drift.load_pipelines(base)


def _import_side():
    agent_on_path()
    import side_impl  # noqa: PLC0415

    return side_impl


# ---------------------------------------------------------------------------
# 守卫 1：(a) 链 / (b) pipeline / (c) agent 三段接线
# ---------------------------------------------------------------------------
def _chain_failures() -> list[str]:
    scene_on_path()
    from scene import chain as C  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415
    from scene.navigation import decide, navigate  # noqa: PLC0415

    msgs: list[str] = []

    landed = C.终端pipeline节点.get(C.TERMINAL_收工)
    if landed != STOP_NODE:
        msgs.append(
            f"收工终点没有落到 {STOP_NODE}（链上的收工边与 pipeline 终止节点脱节）：{landed!r}"
        )

    # 结算终点语义：不限次恒归位；打满收工；超打也收工。
    if C.结算终点(None, 99).名称 != C.TERMINAL_归位:
        msgs.append("结算终点：不限次（目标次数=None）必须归位（保持旧行为）")
    if C.结算终点(2, 1).名称 != C.TERMINAL_归位:
        msgs.append("结算终点：未打满（1/2）必须归位")
    if C.结算终点(2, 2).名称 != C.TERMINAL_收工:
        msgs.append("结算终点：打满（2/2）必须收工")
    if C.结算终点(1, 5).名称 != C.TERMINAL_收工:
        msgs.append("结算终点：超出配置次数（5/1）必须收工")
    if "次数" not in C.结算终点(1, 1).原因:
        msgs.append("结算终点：收工原因应点名「次数」（不点名目标 / 原因）")

    # decide / navigate 一致（结算页）。
    if getattr(decide(LORD_BATTLE, "结算页", LORD), "名称", None) != C.TERMINAL_归位:
        msgs.append("decide(结算页) 缺省必须归位（既有行为不变）")
    if getattr(decide(LORD_BATTLE, "结算页", LORD, 目标次数=1, 已打次数=1), "名称", None) != C.TERMINAL_收工:
        msgs.append("decide(结算页, 打满) 必须收工（不再重进）")
    done = navigate(LORD_BATTLE, LORD, 起始页面="结算页", 目标次数=1, 已打次数=1)
    if done.结局 != "收工":
        msgs.append(f"navigate(从结算页, 打满) 结局必须是收工，实际 {done.结局!r}")
    live = navigate(LORD_BATTLE, LORD, 起始页面="结算页")
    if live.结局 != "到达":
        msgs.append(f"navigate(从结算页, 不限次) 仍应归位后到达，实际 {live.结局!r}")
    return msgs


def _pipeline_failures(files: dict) -> list[str]:
    sd = files.get(_SD)
    msgs: list[str] = []
    if not isinstance(sd, dict):
        return [f"找不到 {_SD}"]

    node = sd.get(STOP_NODE)
    if not isinstance(node, dict):
        msgs.append(f"终止节点 {STOP_NODE} 缺失（收工边无处落地）")
    else:
        if (node.get("recognition") or {}).get("type") != "DirectHit":
            msgs.append(f"{STOP_NODE} 必须是 DirectHit（收工是任务终止，不靠画面判据）")
        if (node.get("action") or {}).get("type") != "StopTask":
            msgs.append(f"{STOP_NODE} 的动作必须是 StopTask")
        if node.get("next") != []:
            msgs.append(f"{STOP_NODE}.next 必须为空（终止），实际 {node.get('next')!r}")

    # 结算节点的动作必须是收工闸的落点（custom special_batch_finish）。
    settle = sd.get(SETTLE_NODE)
    action = (settle or {}).get("action") or {}
    if action.get("param", {}).get("custom_action") != "special_batch_finish":
        msgs.append(
            f"{SETTLE_NODE} 的动作必须是 custom「special_batch_finish」"
            f"（单目标收工闸的落点），实际 {action!r}"
        )

    # 配置次数节点在场（收工闸读它的 max_hit / 命中计数）。
    if not isinstance(sd.get(FIGHT_NODE), dict):
        msgs.append(f"配置次数节点 {FIGHT_NODE} 缺失（收工闸失去「打满」的判据）")

    # 复现模型的边必须与产物一致（否则模型会静默漂移）。
    for src, dst in REQUIRED_EDGES:
        nxt = (sd.get(src) or {}).get("next") or []
        if dst not in nxt:
            msgs.append(f"复现模型与产物脱节：{src}.next 不含 {dst}")
    return msgs


class _Box:
    x, y, w, h = 300, 600, 60, 30


class _TaskDetail:
    def __init__(self, entry="SpecialEntry"):
        self.entry = entry
        self.task_id = 1


class _Argv:
    """结算动作的最小 argv（node_name 决定覆盖哪个结算节点）。"""

    def __init__(self, node=SETTLE_NODE, entry="SpecialEntry"):
        self.custom_action_param = "{}"
        self.box = _Box()
        self.task_detail = _TaskDetail(entry)
        self.node_name = node


class _Ctx:
    """stub context：只实现收工闸用到的读接口 + 覆盖 / 点击。"""

    def __init__(self, *, max_hit=None, hit=0, has_node_data=True):
        self.nexts: list[tuple[str, list[str]]] = []
        self._max_hit = max_hit
        self._hit = hit
        self._has_node_data = has_node_data

    def run_action(self, entry, box=None):
        return True

    def override_next(self, name, lst):
        self.nexts.append((name, list(lst)))
        return True

    def get_node_data(self, name):
        if not self._has_node_data:
            raise RuntimeError("stub: 没有 get_node_data")
        if name != FIGHT_NODE or self._max_hit is None:
            return None
        return {"max_hit": self._max_hit}

    def get_hit_count(self, name):
        return self._hit


def _agent_failures(side) -> list[str]:
    msgs: list[str] = []
    save_active = side._BATCH_ACTIVE
    save_stopped = side._SINGLE_TARGET_STOPPED
    try:
        act = side.SpecialBatchFinishAction()

        def run(ctx, argv):
            side._BATCH_ACTIVE = False
            side._SINGLE_TARGET_STOPPED = False
            if not act.run(ctx, argv):
                msgs.append("结算动作执行失败（stub 下应为 True）")
            return ctx

        # 正例：单目标 + 打满 → 覆盖当前结算节点为 SpecialBatchStop。
        ctx = run(_Ctx(max_hit=1, hit=1), _Argv())
        if ctx.nexts != [(SETTLE_NODE, [STOP_NODE])]:
            msgs.append(f"打满后必须把 {SETTLE_NODE} 指向 {STOP_NODE}，实际 nexts={ctx.nexts}")

        # 正例：从升级结算页打满 → 覆盖的是**当前**节点。
        ctx = run(_Ctx(max_hit=2, hit=2), _Argv(node="SpecialLevelUpContinue"))
        if ctx.nexts != [("SpecialLevelUpContinue", [STOP_NODE])]:
            msgs.append(f"打满后应覆盖当前结算节点，实际 nexts={ctx.nexts}")

        # 反例 1：未打满 → 绝不覆盖（否则会中断没打完的局）。
        ctx = run(_Ctx(max_hit=3, hit=2), _Argv())
        if ctx.nexts:
            msgs.append(f"未打满不得覆盖 next，实际 {ctx.nexts}")

        # 反例 2：不限次（无 max_hit）→ 没有收工条件，绝不覆盖。
        ctx = run(_Ctx(max_hit=None, hit=99), _Argv())
        if ctx.nexts:
            msgs.append(f"不限次（无 max_hit）不得覆盖 next，实际 {ctx.nexts}")

        # 反例 3：批量模式 → 收工由指挥官负责，单目标闸不动作。
        side._BATCH_ACTIVE = True
        side._SINGLE_TARGET_STOPPED = False
        ctx = _Ctx(max_hit=1, hit=1)
        act.run(ctx, _Argv())
        if ctx.nexts:
            msgs.append(f"批量模式不得触发单目标收工闸，实际 {ctx.nexts}")

        # 反例 4：非 special 入口（farm/raid/phantom 别名）→ 不动作。
        ctx = run(_Ctx(max_hit=1, hit=1), _Argv(entry="FarmEntry"))
        if ctx.nexts:
            msgs.append(f"非 special 入口不得触发单目标收工闸，实际 {ctx.nexts}")

        # 反例 5：读不到节点定义（旧框架 / 离线 stub）→ 绝不臆测「已打满」。
        ctx = run(_Ctx(max_hit=1, hit=1, has_node_data=False), _Argv())
        if ctx.nexts:
            msgs.append(f"读不到节点定义时不得覆盖 next，实际 {ctx.nexts}")
    finally:
        side._BATCH_ACTIVE = save_active
        side._SINGLE_TARGET_STOPPED = save_stopped
    return msgs


def settle_stop_failures(files=None, side=None) -> list[str]:
    """收工边的全部检查（链 / pipeline / agent）；空 = 接线正确。"""
    msgs: list[str] = []
    msgs += _chain_failures()
    msgs += _pipeline_failures(files if files is not None else load_files())
    msgs += _agent_failures(side if side is not None else _import_side())
    return msgs


def probe_single_target_settle_stop() -> bool:
    """#22：单目标打满配置次数 → 结算帧指向 SpecialBatchStop（链 / pipeline / agent 三段）。"""
    return settle_stop_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：确定性复现（打满后旧形态无限重进 / 新形态收工）
# ---------------------------------------------------------------------------
def settle_trace(
    *,
    configured: int,
    fought: int,
    stop_wired: bool | None = None,
    files=None,
    side=None,
    max_steps: int = 20,
) -> list[str]:
    """按 MAA 的 ``next`` 语义走一遍「目标已打满」后的走向（确定性、离线）。

    ``stop_wired`` 缺省由**真实产物**决定（``settle_stop_failures`` 为空 = 接线态），
    因此这不是一个「写死的开关」：产物里少了收工边，本函数就真的走回无限重进。
    """
    if stop_wired is None:
        stop_wired = settle_stop_failures(files, side) == []

    seq: list[str] = ["结算页"]
    for _ in range(max_steps):
        if stop_wired and fought >= configured:
            # 新形态：结算推进 → 收工（复用批量终端 SpecialBatchStop）。
            return seq + [SETTLE_NODE, STOP_NODE, STOP_TERMINAL]
        # 旧形态：结算推进 → 归位 → 主城 → 重进列表 → 详情页；打满后
        # SpecialFightTargetRow 不再命中 → 详情页无开打 → 归位弹回主城 → 再进（死循环）。
        seq += [
            SETTLE_NODE,
            "[JumpBack]PubReturnHome",
            "主城",
            "SpecialOpenLord",
            "SpecialTabLord",
            "SpecialEnterBoss",
            "详情页",
            "[JumpBack]PubReturnHome",
            "主城",
        ]
    return seq + ["…(无限重进)"]


def probe_single_target_no_reenter() -> bool:
    """#22：打满后接线态必经 SpecialBatchStop 收工；旧形态（去边）复现无限重进。"""
    new = settle_trace(configured=1, fought=1)
    old = settle_trace(configured=1, fought=1, stop_wired=False)
    return (
        new[-1] == STOP_TERMINAL
        and STOP_NODE in new
        and old[-1] == "…(无限重进)"
        and STOP_NODE not in old
    )


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_22.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _temp_agent_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook22_agent_"))
    shutil.copytree(REPO_ROOT / "agent", root / "agent")
    return root / "agent"


def _temp_scene_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook22_scene_"))
    shutil.copytree(REPO_ROOT / "scene", root / "scene")
    return root


def _run_probe_in(root: Path, probe_name: str):
    """以 ``root`` 作为包来源（PYTHONPATH 抢先）在子进程里跑一个探针；返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks.hooks_22 import " + probe_name + "\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral22_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
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
    """真实绿；摘掉结算里的收工接线 → 接线守卫红；把链的收工边改回恒归位 → 两守卫各自红。"""
    scene_on_path()

    print("hooks_22 prove-red：改坏两处，要求守卫变红")
    green = probe_single_target_settle_stop() and probe_single_target_no_reenter()
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：收工边在场 + 打满必经 SpecialBatchStop（绿）")
    if not green:
        return False

    # (a) 摘掉 agent 里的收工接线（= 结算动作不再指向 SpecialBatchStop）-> 接线守卫红。
    agent_dir = _temp_agent_copy()
    try:
        _sub(
            agent_dir / "side_impl.py",
            "        _single_target_stop(context, argv)\n",
            "        pass  # #22 收工接线被摘掉（prove-red）\n",
        )
        real_green = _run_probe_in(REPO_ROOT, "probe_single_target_settle_stop") is True
        broken_red = _run_probe_in(agent_dir, "probe_single_target_settle_stop") is False
        red_agent = real_green and broken_red
        print(
            f"  [{'PASS' if red_agent else 'FAIL'}] 摘掉结算里的收工接线 -> "
            f"{'红' if broken_red else '仍绿'}  (真实绿={real_green})"
        )
    finally:
        shutil.rmtree(agent_dir.parent, ignore_errors=True)

    # (b) 把链的结算终点改回恒归位（= 去掉收工边）-> 接线守卫与复现守卫各自红。
    scene_root = _temp_scene_copy()
    try:
        _sub(
            scene_root / "scene" / "chain.py",
            "    if 目标次数 is not None and 已打次数 >= 目标次数:",
            "    if False:  # #22 收工边被摘掉（prove-red）",
        )
        real_1 = _run_probe_in(REPO_ROOT, "probe_single_target_settle_stop") is True
        red_1 = _run_probe_in(scene_root, "probe_single_target_settle_stop") is False
        real_2 = _run_probe_in(REPO_ROOT, "probe_single_target_no_reenter") is True
        red_2 = _run_probe_in(scene_root, "probe_single_target_no_reenter") is False
        red_chain = real_1 and red_1 and real_2 and red_2
        print(
            f"  [{'PASS' if red_chain else 'FAIL'}] 去掉链上的收工边 -> "
            f"接线守卫{'红' if red_1 else '仍绿'} / 复现守卫{'红' if red_2 else '仍绿'}"
        )
    finally:
        shutil.rmtree(scene_root, ignore_errors=True)

    ok = green and red_agent and red_chain
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "single-target-settle-stop",
        "#22",
        "单目标打满配置次数 → 明确收工：链的收工边落到 SpecialBatchStop，结算动作按「打满」接线",
        probe_single_target_settle_stop,
    ),
    (
        "single-target-no-reenter",
        "#22",
        "确定性复现：打满后接线态必经 SpecialBatchStop 收工（旧形态走回无限重进）",
        probe_single_target_no_reenter,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
