# -*- coding: utf-8 -*-
"""#19：结算后「页签翻转 + 归位弹跳」死循环的挂点（已点亮）。

seam：``scene.chain``（页签由目标子族决定）+ ``assets/resource/pipeline/special_dungeon.json``
（``SpecialOpenLord`` / ``SpecialTabLord`` / ``SpecialTabJoss`` / ``SpecialEnterBoss``）。

背景（#13 真机实证，15:21:57 结算后）
--------------------------------------
外发路径已通（主城 → 领主战 → 页签 → 命中目标行 → 详情 → 高级 → 战斗 → **结算**）。
结算后重进列表时：``SpecialOpenLord.next`` 同时列了两个页签节点，**两者都带 ``max_hit: 1``**。
首轮 ``SpecialTabLord`` 用掉唯一一次命中 → 此后每次重进列表，``SpecialTabJoss`` 都抢先 →
列表翻到「降临讨伐」→ 目标行（领主战成员）不可见 → ``SpecialEnterBoss`` 永不命中 →
后缀兜底 ``[JumpBack]PubReturnHome`` → 主城 → ``SpecialOpenLord`` 重开 → 循环（每 ~4.3s）
直到 stall。

两个守卫（都在本文件里，prove-red 也在本文件里）：

1. ``tab-target-driven`` —— 页签**由目标子族决定**：
   * 链：``target_tab_node`` / ``decide`` 对两个子族各给出各自的页签节点；重进列表若站在
     错误的页签页上，``decide`` 自恢复回列表页（有界、不弹跳）；
   * pipeline：页签节点 ``SpecialTabLord`` / ``SpecialTabJoss`` **不得**带 ``max_hit``
     （不再靠「谁先命中谁用尽次数」竞速）；``SpecialOpenLord`` 仍同时列出两个 tab 候选
     （两张 tab 标签常驻，页签择一由目标子族经选项覆盖表达）。
2. ``settle-return-recovers`` —— **结算后重进不死循环**：用一张列表屏的状态机 + MAA 的
   ``next`` / ``max_hit`` 语义离线复现「首轮已消耗页签命中 → 重进」：旧形态死循环，
   新形态必经 ``SpecialEnterBoss`` 命中目标行（到达）。

★prove-red★（在文件末尾，``python tools\\contract_hooks\\hooks_19.py``）：
   * 在临时副本上给两个页签节点**还原 ``max_hit: 1``** -> 恢复性守卫红（死循环复现）；
   * 把链里的「领主战 → 领主战页签」映射改坏 -> 目标驱动守卫红。
"""

from __future__ import annotations

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

# 两个页签节点（同一张列表屏上的两个页签页面 → 两个锚点）。
TAB_NODES = ("SpecialTabLord", "SpecialTabJoss")

# 子族 → 它在列表页该走的 pipeline 页签节点（#19：页签由目标子族决定）。
TAB_OF = {"领主战": "SpecialTabLord", "降临讨伐": "SpecialTabJoss"}

# 目标场景（与 scene.lord_battle 的成员一致）：一个领主战、一个降临讨伐。
LORD = {"成员": "八岐大蛇讨伐", "难度": "高级"}   # 领主战（#13 实证的目标）
JOSS = {"成员": "苍叹机兵", "难度": "超级"}        # 降临讨伐

# 列表屏的合成 OCR（720 空间；只保留与判据/页签相关的条目）。
# 两张 tab 标签**常驻**（领主战 / 降临讨伐各一处），命中各自页签节点的 tab 行 ROI。
_TAB_LORD = ("领主战", [100, 401, 60, 28])       # 中心 (130,415) ∈ [0,375,360,60]
_TAB_JOSS = ("降临讨伐", [452, 401, 90, 28])     # 中心 (497,415) ∈ [360,375,360,60]
_LIST_FIXED = [
    ("更新列表", [620, 540, 96, 40]),             # SpecialScrollList 的列表页独有元素
    ("返回", [32, 1247, 43, 24]),                 # 底部导航最左槽（非主城）
    ("主城", [158, 1248, 42, 24]),                # 底部导航「主城」
]
_MAIN_CITY = [
    ("主城", [157, 1248, 44, 25]),
    ("主角色", [22, 1249, 61, 20]),               # 主城最左槽是主角色（没有「返回」）
    ("领主战", [569, 1121, 79, 29]),              # 主城右下角入口（SpecialOpenLord ROI 内）
]


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _pipeline_dir() -> Path:
    return REPO_ROOT / _PIPELINE_REL


def load_files(pipeline_dir=None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(pipeline_dir) if pipeline_dir else _pipeline_dir()
    return drift.load_pipelines(base)


# ---------------------------------------------------------------------------
# 离线 recognition 求值器（同 hooks_18 形状：OCR / And / Or / DirectHit；
# Custom / 未知 -> 视为不命中，绝不臆测设备侧行为）
# ---------------------------------------------------------------------------
def _ocr_hit(rec: dict, items) -> bool:
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


def eval_recognition(rec, items, resolve=None) -> bool:
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
            leaf_rec = resolve(leaf) if (isinstance(leaf, str) and resolve is not None) else leaf
            hits.append(eval_recognition(leaf_rec, items, resolve))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def _node(name: str, files: dict):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


# ---------------------------------------------------------------------------
# 列表屏状态机 + MAA ``next`` / ``max_hit`` 语义模拟（确定性、离线）
# ---------------------------------------------------------------------------
class Screen:
    """一张可识别的画屏：主城 or 领主战列表；列表上当前选中哪个页签。"""

    def __init__(self, page: str, active_tab: str, target_tab: str, target_row: str):
        self.page = page                  # "主城" | "列表"
        self.active_tab = active_tab      # 列表页当前选中的子族页签
        self.target_tab = target_tab      # 目标子族
        self.target_row = target_row      # 目标行名

    def items(self):
        if self.page == "主城":
            return list(_MAIN_CITY)
        out = [_TAB_LORD, _TAB_JOSS, *_LIST_FIXED]
        if self.active_tab == self.target_tab:
            out.append((self.target_row, [200, 650, 180, 36]))  # 目标行仅在本子族页签上可见
        return out


def _apply_action(name: str, screen: Screen) -> None:
    """模拟节点动作对画屏的可观测影响（只到「哪个页面 / 哪个页签」这一粒度）。"""
    if name == "SpecialOpenLord":
        screen.page = "列表"          # 点主城入口 → 打开列表（页签保持游戏记忆）
    elif name == "SpecialTabLord":
        screen.active_tab = "领主战"
    elif name == "SpecialTabJoss":
        screen.active_tab = "降临讨伐"
    elif name == "PubReturnHome":
        screen.page = "主城"


def simulate(entry: str, screen: Screen, files: dict, overrides: dict,
             counters: dict, max_steps: int = 120):
    """从 ``entry`` 出发，按 MAA 的 ``next`` / ``max_hit`` 语义走；返回 "ARRIVED"/"LIMIT"/None。

    * 候选按序识别，取第一个「未因 max_hit 用尽被跳过」且命中当前画屏的；
    * 普通引用：执行后流程进入它的子树（不再扫调用者剩余候选）；
    * ``[JumpBack]`` 引用：执行后回到调用者继续扫剩余候选；
    * ``SpecialEnterBoss`` 命中 = 选中了目标行 = 到达。
    """
    resolve = _resolver(files)
    state = {"steps": 0}

    def can_hit(name: str, spec: dict) -> bool:
        mh = spec.get("max_hit")
        if mh is None:
            return True
        return counters.get(name, 0) < mh

    def matches(name: str) -> bool:
        rec = overrides.get(name)
        if rec is None:
            import scene.drift as drift  # noqa: PLC0415
            rec = drift._resolve_recognition(name, files)
        return eval_recognition(rec, screen.items(), resolve)

    def dispatch(node_name: str):
        spec = _node(node_name, files)
        if spec is None:
            return None
        for ref in spec.get("next") or []:
            if state["steps"] >= max_steps:
                return "LIMIT"
            jb = isinstance(ref, str) and ref.startswith("[JumpBack]")
            name = ref[len("[JumpBack]"):] if jb else ref
            nspec = _node(name, files)
            if nspec is None:
                continue
            if not can_hit(name, nspec):
                continue
            if not matches(name):
                continue
            state["steps"] += 1
            _apply_action(name, screen)
            counters[name] = counters.get(name, 0) + 1
            if name == "SpecialEnterBoss":
                return "ARRIVED"
            r = dispatch(name)
            if r is not None:
                return r
            if jb:
                continue
            return None
        return None

    return dispatch(entry)


def overrides_for(目标) -> dict:
    """目标对应的运行期覆盖：目标行 OCR + 子族页签覆盖（只启用目标子族的页签）。

    复用 ``scene.chain.tab_override_for`` —— 与 GUI / 批量指挥官同一事实；「哪个页签生效」
    正是由目标子族决定的（#19）。
    """
    scene_on_path()
    from scene.chain import resolve_target, tab_override_for  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415

    t = resolve_target(LORD_BATTLE, 目标)
    ov = {
        "SpecialEnterBoss": {
            "type": "OCR",
            "param": {"expected": [t.行名], "roi": [150, 440, 320, 800]},
        }
    }
    for node, spec in tab_override_for(t.子族).items():
        ov[node] = spec["recognition"]
    return t, ov


def reenter(files: dict, 目标, *, seed: dict, active: str, max_steps: int = 120) -> str:
    """模拟一次「结算后重进列表」：从主城出发走到选中目标行（或死循环）。

    ``seed`` 预置 max_hit 计数（表达「首轮已消耗页签命中」）；``active`` 是列表页当前页签。
    """
    t, ov = overrides_for(目标)
    counters = dict(seed)
    screen = Screen("主城", active, t.页签, t.行名)
    r = simulate("SpecialEntry", screen, files, ov, counters, max_steps=max_steps)
    return "到达" if r == "ARRIVED" else "死循环"


def scenarios(pipeline_dir=None) -> dict:
    """三个确定性用例：都必须在【新形态】下「到达」、在【旧形态】下「死循环」。"""
    files = load_files(pipeline_dir)
    return {
        # A：结算后重进 —— 首轮已消耗 SpecialTabLord 命中，列表停在领主战 tab（目标子族）
        "领主战·结算后重进": reenter(files, LORD, seed={"SpecialTabLord": 1}, active="领主战"),
        # B：重进且页签已被切到【另一子族】（#19 用例：当前在列表页、页签已翻）
        "领主战·页签已被切到降临讨伐": reenter(files, LORD, seed={"SpecialTabLord": 1}, active="降临讨伐"),
        # C：降临讨伐目标，首轮已消耗 SpecialTabJoss
        "降临讨伐·结算后重进": reenter(files, JOSS, seed={"SpecialTabJoss": 1}, active="降临讨伐"),
        # D：降临讨伐目标，重进且页签已被切到领主战
        "降临讨伐·页签已被切到领主战": reenter(files, JOSS, seed={"SpecialTabJoss": 1}, active="领主战"),
    }


# ---------------------------------------------------------------------------
# 守卫 1：页签由目标子族决定（链 + pipeline）
# ---------------------------------------------------------------------------
def _tab_target_driven_failures() -> list[str]:
    scene_on_path()
    from scene import chain as C  # noqa: PLC0415
    from scene.chain import resolve_target, target_tab_node  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415
    from scene.navigation import decide, navigate  # noqa: PLC0415

    msgs: list[str] = []
    cfg = LORD_BATTLE
    lord = resolve_target(cfg, LORD)
    joss = resolve_target(cfg, JOSS)
    if lord is None or joss is None:
        return ["页签目标驱动：目标场景无法解析（配置面变动？）"]

    # 链：子族 → 页签节点；列表页 → 目标子族的页签。
    if target_tab_node(lord) != C.NODE_领主战页签:
        msgs.append(f"页签目标驱动：领主战目标应走 {C.NODE_领主战页签}，实际 {target_tab_node(lord)}")
    if target_tab_node(joss) != C.NODE_降临讨伐页签:
        msgs.append(f"页签目标驱动：降临讨伐目标应走 {C.NODE_降临讨伐页签}，实际 {target_tab_node(joss)}")
    if getattr(decide(cfg, "领主战列表页", LORD), "id", None) != C.NODE_领主战页签:
        msgs.append("页签目标驱动：decide(列表页, 领主战目标) 不是领主战页签")
    if getattr(decide(cfg, "领主战列表页", JOSS), "id", None) != C.NODE_降临讨伐页签:
        msgs.append("页签目标驱动：decide(列表页, 降临讨伐目标) 不是降临讨伐页签")

    # 重进列表若站在错误页签页上 → 自恢复回列表页（不弹跳）。
    if getattr(decide(cfg, "降临讨伐页签", LORD), "id", None) != C.NODE_列表:
        msgs.append("页签目标驱动：领主战目标站在降临讨伐页签上不自恢复回列表页")
    if getattr(decide(cfg, "领主战页签", JOSS), "id", None) != C.NODE_列表:
        msgs.append("页签目标驱动：降临讨伐目标站在领主战页签上不自恢复回列表页")
    if navigate(cfg, LORD, 起始页面="降临讨伐页签").结局 != "到达":
        msgs.append("页签目标驱动：从「页签被切到降临讨伐」出发到不了领主战目标")
    if navigate(cfg, JOSS, 起始页面="领主战页签").结局 != "到达":
        msgs.append("页签目标驱动：从「页签被切到领主战」出发到不了降临讨伐目标")

    # pipeline：页签节点不得再用 max_hit 竞速；SpecialOpenLord 仍同时列出两个 tab 候选。
    files = load_files()
    for n in TAB_NODES:
        spec = _node(n, files)
        if not isinstance(spec, dict):
            msgs.append(f"页签目标驱动：pipeline 里找不到页签节点 {n}")
        elif "max_hit" in spec:
            msgs.append(
                f"页签目标驱动：{n} 仍带 max_hit={spec.get('max_hit')!r}"
                f"（页签靠竞速 → 首轮用尽后重进必被另一页签抢先）"
            )
    ol = _node("SpecialOpenLord", files)
    nxt = (ol or {}).get("next") or []
    if "SpecialTabLord" not in nxt or "SpecialTabJoss" not in nxt:
        msgs.append(f"页签目标驱动：SpecialOpenLord.next 不再同时列出两个页签候选（{nxt}）")

    # 子族页签覆盖（runner / 批量指挥官复用）：只启用目标子族的页签、关掉另一个。
    from scene.chain import tab_override_for  # noqa: PLC0415

    for 子族, enabled, disabled in (
        ("领主战", TAB_OF["领主战"], TAB_OF["降临讨伐"]),
        ("降临讨伐", TAB_OF["降临讨伐"], TAB_OF["领主战"]),
    ):
        ov = tab_override_for(子族)
        en = ((ov.get(enabled) or {}).get("recognition") or {}).get("param") or {}
        dis = ((ov.get(disabled) or {}).get("recognition") or {}).get("param") or {}
        if en.get("expected") == ["__NONE__"]:
            msgs.append(f"页签目标驱动：{子族} 子族覆盖把目标页签 {enabled} 关掉了")
        if dis.get("expected") != ["__NONE__"]:
            msgs.append(f"页签目标驱动：{子族} 子族覆盖没有关掉非目标页签 {disabled}")
    return msgs


def probe_tab_target_driven() -> bool:
    """#19：页签由目标子族决定（链 + pipeline 无 max_hit 竞速）。"""
    return _tab_target_driven_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：结算后重进不再死循环
# ---------------------------------------------------------------------------
def probe_settle_return_recovers() -> bool:
    """#19：三个用例在新形态下都必须「到达」（旧形态 = max_hit 竞速，会死循环）。"""
    result = scenarios()
    return all(v == "到达" for v in result.values())


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_19.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _temp_pipeline_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook19_"))
    shutil.copytree(REPO_ROOT / _PIPELINE_REL, root / "pipeline")
    return root


def _restore_max_hit(pipeline_dir: Path) -> None:
    """在临时副本上给两个页签节点【还原 max_hit: 1】——旧「竞速」形态。"""
    sd = pipeline_dir / _SD
    for target in ("[180, 405]", "[540, 404]"):
        _sub(
            sd,
            f'        "action": {{ "type": "Click", "param": {{ "target": {target} }} }},\n',
            f'        "action": {{ "type": "Click", "param": {{ "target": {target} }} }},\n'
            '        "max_hit": 1,\n',
        )


def _run_probe_in(root: Path, probe_name: str):
    """以 ``root`` 作为 ``scene`` 包来源，在子进程里跑一个探针；返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks.hooks_19 import probe_tab_target_driven\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    import os  # noqa: PLC0415

    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral19_"))
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
    """真实绿；还原 max_hit 竞速 -> 恢复性守卫红；改坏链的页签映射 -> 目标驱动守卫红。"""
    scene_on_path()

    print("hooks_19 prove-red：改坏两处，要求两个守卫各自变红")
    green = probe_tab_target_driven() and probe_settle_return_recovers()
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：页签目标驱动 + 结算后重进必到达（绿）")
    if not green:
        return False

    # (a) 还原 max_hit 竞速 -> 恢复性守卫红（离线复现死循环）。
    root = _temp_pipeline_copy()
    try:
        _restore_max_hit(root / "pipeline")
        bad = scenarios(root / "pipeline")
        red_mh = any(v != "到达" for v in bad.values())
        detail = ", ".join(f"{k}={v}" for k, v in bad.items())
        print(f"  [{'PASS' if red_mh else 'FAIL'}] 还原 max_hit 竞速 -> "
              f"{'红（复现死循环）' if red_mh else '仍绿'}  {detail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 改坏链的页签映射（领主战 → 降临讨伐页签）-> 目标驱动守卫红。
    tmp = Path(tempfile.mkdtemp(prefix="wf_hook19_scene_"))
    try:
        shutil.copytree(REPO_ROOT / "scene", tmp / "scene")
        _sub(
            tmp / "scene" / "chain.py",
            '"领主战": NODE_领主战页签,',
            '"领主战": NODE_降临讨伐页签,',
        )
        green_real = _run_probe_in(REPO_ROOT, "probe_tab_target_driven") is True
        red_broken = _run_probe_in(tmp, "probe_tab_target_driven") is False
        red_chain = green_real and red_broken
        print(f"  [{'PASS' if red_chain else 'FAIL'}] 改坏链页签映射 -> "
              f"{'红' if red_broken else '仍绿'}  (真实绿={green_real})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = green and red_mh and red_chain
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "tab-target-driven",
        "#19",
        "页签由目标子族决定（链 target_tab_node/decide + pipeline 页签节点无 max_hit 竞速）",
        probe_tab_target_driven,
    ),
    (
        "settle-return-recovers",
        "#19",
        "结算后重进列表不再「页签翻转+归位弹跳」死循环：三个用例必经 SpecialEnterBoss 到达",
        probe_settle_return_recovers,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
