# -*- coding: utf-8 -*-
"""#27：「结算」不再被抢帧 —— 链上结算节点会被评估，收工闸才有机会执行（已点亮）。

seam：``scene.events``（打断型事件组）+ ``scene.drift``（链上页面 ∩ 打断型事件守卫）
+ ``assets/resource/pipeline/special_dungeon.json``。

背景（#26 真机实证，非推断）
------------------------------
#22 把收工闸挂在 ``SpecialResultContinue`` / ``SpecialResultFallback`` /
``SpecialLevelUpContinue`` 上。但 ``SpecialEntry.next`` 的**最前面**是公共叶子
``[JumpBack]PubResultContinue`` / ``[JumpBack]PubQuestResult`` —— 它们是**被注入的
「结算」打断型事件**（#5 的事件组前缀）。结算帧一到：前缀里的 ``PubResultContinue``
先命中并**吃掉这一帧** → ``[JumpBack]`` 回当前节点重扫 → 链上的结算节点
（挂着 #22 闸门的那个）**从未被评估**。真机计数：三个结算节点命中各 **0**、
``special_batch_finish`` 执行 **0**、``override_next`` **0**、``SpecialBatchStop`` **0**。

这是**设计层冲突**：``结算页`` 既是链上的一步（ADR-0002 / ``NODE_结算``），又被当成
优先级更高的打断型事件注入。**链上已有的页面，不得同时作为打断型事件注入。**

两个守卫（都在本文件里，prove-red 也在本文件里）
------------------------------------------------
1. ``settle-not-interrupt-event`` —— 「结算」不再是打断型事件；链上页面 ∩ 打断型事件 = ∅
   （``scene.drift.chain_page_interrupt_drift``，``check_all`` 第 5 条）；pipeline 里不再有
   抢帧的 ``[JumpBack]PubResultContinue`` / ``[JumpBack]PubQuestResult``。
2. ``settle-chain-node-reachable`` —— **离线复现遮蔽**（结算帧，确定性）：
   * 旧形态（把 ``PubResultContinue`` 塞回 ``SpecialBattleWait.next`` 前缀）：首个命中 =
     ``PubResultContinue``，链上结算节点 ``SpecialResultContinue`` **永不执行**；
   * 新形态（真实产物）：首个命中 = ``SpecialResultContinue``，它**执行**，且 #22 的收工闸
     在 stub 下把它的 next 覆盖成 ``SpecialBatchStop``（= 收工）。

★prove-red★（在文件末尾，`python tools\\contract_hooks\\hooks_27.py`）：
   * 产物级：把 ``[JumpBack]PubResultContinue`` 塞回某个流程节点前缀 -> 守卫红；
   * 配置级：把「结算」塞回打断型事件组 -> 守卫红。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

_PIPELINE_REL = "assets/resource/pipeline"
_SD = "special_dungeon.json"

SETTLE_NODE = "SpecialResultContinue"
STOP_NODE = "SpecialBatchStop"
STOP_TERMINAL = "收工"
FIGHT_NODE = "SpecialFightTargetRow"

# 结算页的一帧（合成 OCR，离线确定性）：
#   「继续」   -> PubResultContinueText 的 ^继续$ 命中（PubResultContinue / SpecialResultContinue 同判据）；
#   「QUESTRESULT」 -> PubQuestResultText 的 QUESTRE 命中。
SETTLE_FRAME: list[tuple[str, list[int]]] = [
    ("继续", [330, 640, 60, 30]),
    ("QUESTRESULT", [180, 380, 360, 60]),
]

# 旧形态的抢帧前缀（#5 注入的「结算」打断型事件引用；#26 实证抢帧）。
OLD_INTERRUPT_REFS = ("[JumpBack]PubResultContinue", "[JumpBack]PubQuestResult")

# 配置级破坏点：把「结算」塞回打断型事件组（去掉 chain_page 过滤）。
_BREAK_OLD = "INTERRUPT_EVENTS: tuple[Event, ...] = tuple(e for e in EXCEPTION_EVENTS if e.chain_page is None)"
_BREAK_NEW = "INTERRUPT_EVENTS: tuple[Event, ...] = EXCEPTION_EVENTS"


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def agent_on_path() -> None:
    """把 agent 目录放到 sys.path【末尾】（让坏副本经 PYTHONPATH 抢先）。"""
    if str(REPO_ROOT / "agent") not in sys.path:
        sys.path.append(str(REPO_ROOT / "agent"))


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
    return False  # Custom / 其它：离线不臆测，视为不命中


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def candidate_hit(ref: str, items, files) -> bool:
    """一个候选引用（可带 ``[JumpBack]`` 前缀）在给定画面上是否命中。"""
    name = ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref
    import scene.drift as drift  # noqa: PLC0415

    return eval_recognition(drift._resolve_recognition(name, files), items, _resolver(files))


def _first_hit(candidates: list, files: dict) -> str | None:
    for ref in candidates:
        if candidate_hit(ref, SETTLE_FRAME, files):
            return ref
    return None


def settlement_trace(candidates: list, files: dict, max_steps: int = 6) -> list[str]:
    """在结算帧上按 MAA 的 ``next`` 语义走若干步（``[JumpBack]`` 执行后回调用者重扫）。

    返回依次命中的节点名序列。画面在离线模拟里【不变】，故死循环会表现为同一节点反复出现
    —— 这正是 #26 的形态。
    """
    seq: list[str] = []
    cur = list(candidates)
    for _ in range(max_steps):
        ref = _first_hit(cur, files)
        if ref is None:
            break
        if ref.startswith("[JumpBack]"):
            seq.append(ref[len("[JumpBack]"):])  # 执行完回调用者重扫（画面不变 -> 再命中）
            continue
        seq.append(ref)
        nxt = (files.get(_SD, {}).get(ref) or {}).get("next")
        if not nxt:
            break
        cur = list(nxt)
    return seq


# ---------------------------------------------------------------------------
# #22 收工闸的 stub（证明：链上结算节点一旦执行，闸门就有机会落到收工）
# ---------------------------------------------------------------------------
class _Box:
    x, y, w, h = 300, 600, 60, 30


class _TaskDetail:
    def __init__(self, entry="SpecialEntry"):
        self.entry = entry
        self.task_id = 1


class _Argv:
    def __init__(self, node=SETTLE_NODE):
        self.custom_action_param = "{}"
        self.box = _Box()
        self.task_detail = _TaskDetail()
        self.node_name = node


class _Ctx:
    def __init__(self, *, max_hit=1, hit=1):
        self.nexts: list[tuple[str, list[str]]] = []
        self._max_hit = max_hit
        self._hit = hit

    def run_action(self, entry, box=None):
        return True

    def override_next(self, name, lst):
        self.nexts.append((name, list(lst)))
        return True

    def get_node_data(self, name):
        if name != FIGHT_NODE or self._max_hit is None:
            return None
        return {"max_hit": self._max_hit}

    def get_hit_count(self, name):
        return self._hit


def _gate_fires() -> bool:
    """单目标 + 打满 -> 结算动作把当前结算节点指向 ``SpecialBatchStop``（= 收工）。"""
    agent_on_path()
    import side_impl  # noqa: PLC0415

    real_active = side_impl._BATCH_ACTIVE
    real_stopped = side_impl._SINGLE_TARGET_STOPPED
    try:
        side_impl._BATCH_ACTIVE = False
        side_impl._SINGLE_TARGET_STOPPED = False
        ctx = _Ctx(max_hit=1, hit=1)
        ok = side_impl.SpecialBatchFinishAction().run(ctx, _Argv())
        return bool(ok) and ctx.nexts == [(SETTLE_NODE, [STOP_NODE])]
    finally:
        side_impl._BATCH_ACTIVE = real_active
        side_impl._SINGLE_TARGET_STOPPED = real_stopped


# ---------------------------------------------------------------------------
# 守卫 1：结算不再是打断型事件；链上页面 ∩ 打断型事件 = ∅
# ---------------------------------------------------------------------------
def _not_interrupt_failures() -> list[str]:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415
    from scene.events import EXCEPTION_EVENTS, INTERRUPT_EVENTS  # noqa: PLC0415

    msgs: list[str] = []
    names = [e.name for e in INTERRUPT_EVENTS]
    if "结算" in names:
        msgs.append("「结算」仍在打断型事件组里（链上结算节点会被它遮蔽）")
    nodes = {n for e in INTERRUPT_EVENTS for n in e.nodes}
    stolen = {"PubResultContinue", "PubQuestResult"} & nodes
    if stolen:
        msgs.append(f"打断型事件组里仍有结算抢帧节点 {sorted(stolen)}")
    if "结算" not in [e.name for e in EXCEPTION_EVENTS]:
        msgs.append("「结算」不在九类异常分类里（taxonomy 被删，注入之外的分类应保留）")

    msgs += drift.chain_page_interrupt_drift(REPO_ROOT)
    msgs += drift.check_all(repo_root=REPO_ROOT)

    data = drift.load_pipelines(REPO_ROOT / _PIPELINE_REL).get(_SD) or {}
    refs = {
        x
        for spec in data.values()
        if isinstance(spec, dict)
        for x in (spec.get("next") or [])
    }
    left = sorted(set(OLD_INTERRUPT_REFS) & refs)
    if left:
        msgs.append(f"{_SD} 里仍有抢帧的结算前缀 {left}（应已从打断组移出）")
    return msgs


def probe_settle_not_interrupt_event() -> bool:
    """#27：结算不再是打断型事件；链上页面 ∩ 打断型事件 = ∅；pipeline 无抢帧前缀。"""
    return _not_interrupt_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：离线复现遮蔽（结算帧）—— 旧形态链节点永不执行 / 新形态执行且闸门落收工
# ---------------------------------------------------------------------------
def _reachable_failures() -> list[str]:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    files = drift.load_pipelines(REPO_ROOT / _PIPELINE_REL)
    real = list((files.get(_SD, {}).get("SpecialBattleWait") or {}).get("next") or [])
    if not real:
        return ["找不到 SpecialBattleWait.next（无法复现结算帧走向）"]

    old = [real[0], *OLD_INTERRUPT_REFS, *real[1:]]
    msgs: list[str] = []

    old_first = _first_hit(old, files)
    if old_first != OLD_INTERRUPT_REFS[0]:
        msgs.append(f"旧形态首命中应为 {OLD_INTERRUPT_REFS[0]!r}（抢帧者），实际 {old_first!r}")
    new_first = _first_hit(real, files)
    if new_first != SETTLE_NODE:
        msgs.append(f"新形态首命中应为链上结算节点 {SETTLE_NODE!r}，实际 {new_first!r}")

    old_seq = settlement_trace(old, files, max_steps=6)
    new_seq = settlement_trace(real, files, max_steps=6)
    if SETTLE_NODE in old_seq:
        msgs.append(f"旧形态里链上结算节点竟被执行（不应发生）：{old_seq}")
    if SETTLE_NODE not in new_seq:
        msgs.append(f"新形态里链上结算节点未被执行：{new_seq}")
    if old_seq[:3] != [OLD_INTERRUPT_REFS[0][len("[JumpBack]"):]] * 3:
        msgs.append(f"旧形态未复现「前缀反复抢帧」的死循环：{old_seq}")

    if not _gate_fires():
        msgs.append("链上结算节点执行后，#22 的收工闸未指向 SpecialBatchStop（闸门没接上）")
    return msgs


def probe_settle_chain_node_reachable() -> bool:
    """#27：结算帧上链上结算节点被执行（旧形态被 PubResultContinue 抢走、永不执行）。"""
    return _reachable_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_27.py`）
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook27_assets_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
    shutil.copytree(
        REPO_ROOT / "assets" / "resource" / "pipeline",
        root / "assets" / "resource" / "pipeline",
    )
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_readd_frame_thief(root: Path) -> None:
    """产物级：把 ``[JumpBack]PubResultContinue`` 塞回某个流程节点的前缀（旧抢帧形态）。"""
    _sub(
        root / _PIPELINE_REL / _SD,
        '        "next": [\n            "[JumpBack]PubLoadingWait",',
        '        "next": [\n'
        '            "[JumpBack]PubResultContinue",\n'
        '            "[JumpBack]PubLoadingWait",',
    )


def _run_probe_in(root: Path, probe_name: str):
    """以 ``root`` 作为包来源（PYTHONPATH 抢先）在子进程里跑一个探针；返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks.hooks_27 import " + probe_name + "\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral27_"))
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
    """真实绿；把结算塞回打断前缀 / 塞回打断事件组 -> 守卫各自变红。"""
    scene_on_path()

    print("hooks_27 prove-red：把结算塞回打断前缀 / 塞回打断事件组，要求守卫变红")
    green = probe_settle_not_interrupt_event() is True and probe_settle_chain_node_reachable() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：结算不再是打断事件 + 链上结算节点可达（绿）")
    if not green:
        return False

    # (a) 产物级：塞回抢帧前缀 -> chain_page_interrupt_drift 变红。
    root = _temp_assets()
    try:
        _break_readd_frame_thief(root)
        import scene.drift as drift  # noqa: PLC0415

        msgs = drift.chain_page_interrupt_drift(root)
        red_guard = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_guard else 'FAIL'}] 把 PubResultContinue 塞回前缀 -> "
              f"{'红' if red_guard else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 配置级：把「结算」塞回打断型事件组 -> 守卫红。
    scene_root = Path(tempfile.mkdtemp(prefix="wf_hook27_scene_"))
    try:
        shutil.copytree(REPO_ROOT / "scene", scene_root / "scene")
        _sub(scene_root / "scene" / "events.py", _BREAK_OLD, _BREAK_NEW)
        real_green = _run_probe_in(REPO_ROOT, "probe_settle_not_interrupt_event") is True
        broken_red = _run_probe_in(scene_root, "probe_settle_not_interrupt_event") is False
        red_conf = real_green and broken_red
        print(f"  [{'PASS' if red_conf else 'FAIL'}] 把结算塞回打断事件组 -> "
              f"{'红' if broken_red else '仍绿'}  (真实绿={real_green})")
    finally:
        shutil.rmtree(scene_root, ignore_errors=True)

    ok = green and red_guard and red_conf
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "settle-not-interrupt-event",
        "#27",
        "结算不再是打断型事件：链上页面 ∩ 打断型事件 = ∅（不再抢帧遮蔽链上的结算节点）",
        probe_settle_not_interrupt_event,
    ),
    (
        "settle-chain-node-reachable",
        "#27",
        "离线复现遮蔽（结算帧）：旧形态链上结算节点永不执行 / 新形态执行且 #22 收工闸落 SpecialBatchStop",
        probe_settle_chain_node_reachable,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
