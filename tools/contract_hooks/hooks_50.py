# -*- coding: utf-8 -*-
"""#50：``SpecialScrollList`` 的滚动预算必须【每条目重置】，且【用尽即有界停止】。

seam：``assets/resource/pipeline/special_dungeon.json``（``SpecialScrollList.max_hit`` =
每条目预算；``SpecialTabLord`` / ``SpecialTabJoss`` 的 next 顺序）+ ``agent/side_impl.py``
（指挥官在每个条目开始导航前抬预算；预算用尽则明确跳过）。

缺陷（设备 16448，5 个【深行】成员的降临讨伐 chunk，原生日志）
-------------------------------------------------------------
``max_hit reached [data.name=SpecialScrollList] [current_hit=30] [data.max_hit=30]``
—— 框架的命中计数是**按任务**累计的（任务重开才清零），而一个批量 chunk = 一个任务，
故按任务写死的 ``SpecialScrollList.max_hit`` 被整条清单**共享消费**：5 个深行成员共用
一个 30 次的预算，用尽后该节点被框架**静默跳过** → 目标行永远滚不到 → 链只剩
``SpecialEntry`` / ``SpecialTabJoss`` 互跳 → 空转到超时。行越深越吃亏
（**深批次被系统性惩罚**）。单个成员的 fresh task 里整份预算都归它用，故同一个深行目标
「找得到」。失败 chunk（``log_q1_c4``）：魁雷精灵兽 / 威风精灵兽 / 巫光精灵兽 /
暗唤精灵兽 / 方舟守护者讨伐。

三个守卫（prove-red 也在本文件里）
----------------------------------
1. ``scroll-budget-per-item`` —— 读产品的 ``SpecialScrollList.max_hit``，断言它是**有限、
   在合理区间内**，且与 agent 的单源常量 ``side_impl._PER_ITEM_SCROLL_BUDGET`` **逐字段相等**；
   并断言「``SpecialEnterBoss`` 排在滚动节点之前」（= 行一旦进屏就被选行、不再消耗预算，
   故「预算被滚完」只可能是「行始终没进屏」）以及指挥官侧确实接了预算重置/用尽判定。
2. ``scroll-budget-resets-per-item`` —— **离线复现**：一个 29 行的降临讨伐列表、一个 chunk
   里 5 个**深行**成员（最末 5 行，保守取 1 行/次受控滚动）。
   * 旧形态（预算按任务共享、无重置）：滚到中途就把一份预算用尽 → 后面的成员**全都到不了**
     （系统性惩罚）；
   * 新形态（每条目重置 + 用尽即跳过）：**逐一到达**这 5 个成员，且单条目滚动从不超过一份预算。
3. ``scroll-budget-bounded-stop`` —— 目标是**列表里根本没有的行**：新形态在滚完一份预算后
   **明确跳过并记录原因**、随即收尾（有界，绝不无限滚）；旧形态无安全网 → 静默空转。

★prove-red★（``python tools\\contract_hooks\\hooks_50.py``）：把产品的 max_hit 改坏 / 把
agent 常量改坏 / 去掉指挥官的重置接线 / 关掉重置或安全网 → 三个守卫各自变红。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

_PIPELINE_REL = "assets/resource/pipeline"
_SD = "special_dungeon.json"

SCROLL_NODE = "SpecialScrollList"
_ENTER_BOSS = "SpecialEnterBoss"

# 每条目预算的合理区间（次）。太少 → 单条目滚不到深行；太多 → 坏形态空转时长过大。
MIN_SCROLL_BUDGET = 8
MAX_SCROLL_BUDGET = 200


def scene_on_path() -> None:
    """把仓库根 / agent 目录放到 sys.path（离线读产品 + 导入 agent 单源常量）。"""
    for p in (str(REPO_ROOT), str(AGENT_DIR)):
        if p not in sys.path:
            sys.path.append(p)


def _files(root: Path | None = None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    return drift.load_pipelines(base / _PIPELINE_REL)


def _node(files: dict, name: str):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


def _agent():
    scene_on_path()
    import side_impl  # noqa: PLC0415

    return side_impl


def _agent_source() -> str:
    return (AGENT_DIR / "side_impl.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 守卫 1：预算语义（有限、区间内、与 agent 常量单源绑定；选行先于滚动）
# ---------------------------------------------------------------------------
def _declared_budget(files: dict):
    node = _node(files, SCROLL_NODE)
    if not isinstance(node, dict):
        return None
    return node.get("max_hit")


def _budget_failures(root=None, *, agent_budget=None, agent_source=None) -> list[str]:
    files = _files(root)
    msgs: list[str] = []

    declared = _declared_budget(files)
    if not isinstance(declared, int) or isinstance(declared, bool):
        msgs.append(
            f"预算守卫：产品 {SCROLL_NODE}.max_hit 必须是有限整数（每条目预算），实际 {declared!r}"
        )
    else:
        if not (MIN_SCROLL_BUDGET <= declared <= MAX_SCROLL_BUDGET):
            msgs.append(
                f"预算守卫：{SCROLL_NODE}.max_hit={declared} 不在合理区间 "
                f"[{MIN_SCROLL_BUDGET},{MAX_SCROLL_BUDGET}]（太小滚不到深行 / 太大留给坏形态空转）"
            )

    si = _agent()
    budget = si._PER_ITEM_SCROLL_BUDGET if agent_budget is None else agent_budget
    if isinstance(declared, int) and not isinstance(declared, bool) and budget != declared:
        msgs.append(
            f"预算守卫：单源漂移 —— agent _PER_ITEM_SCROLL_BUDGET={budget} != 产品 "
            f"{SCROLL_NODE}.max_hit={declared}（两者必须相等）"
        )
    if si.SCROLL_NODE != SCROLL_NODE and root is None:
        msgs.append(f"预算守卫：agent SCROLL_NODE={si.SCROLL_NODE!r} != {SCROLL_NODE!r}")

    # 「选行先于滚动」：行一旦进屏就被 SpecialEnterBoss 选走、不再消耗滚动预算 ——
    # 这正是「预算被滚完 ⇒ 行始终没进屏」的前提（用尽即跳过的判定靠它成立）。
    for tab in ("SpecialTabLord", "SpecialTabJoss"):
        seq = (_node(files, tab) or {}).get("next") or []
        if _ENTER_BOSS not in seq or SCROLL_NODE not in seq:
            msgs.append(f"预算守卫：{tab}.next 缺 {_ENTER_BOSS} / {SCROLL_NODE}（链被改坏？）")
        elif list(seq).index(_ENTER_BOSS) > list(seq).index(SCROLL_NODE):
            msgs.append(
                f"预算守卫：{tab}.next 里 {SCROLL_NODE} 排在 {_ENTER_BOSS} 之前 —— "
                f"行可见时仍会先滚动，『用尽 ⇒ 行不可达』的判定不再成立"
            )
    entry = (_node(files, "SpecialEntry") or {}).get("next") or []
    if SCROLL_NODE not in entry:
        msgs.append(f"预算守卫：SpecialEntry.next 缺 {SCROLL_NODE}（兜底滚动边丢了？）")

    # 指挥官接线：切条目时必须调 _ensure_scroll_budget；用尽判定必须用 scroll_budget_exhausted。
    src = _agent_source() if agent_source is None else agent_source
    if "_ensure_scroll_budget(context, task_id)" not in src:
        msgs.append("预算守卫：指挥官切换条目后没有调用 _ensure_scroll_budget(context, task_id)（预算不会重置）")
    if "scroll_budget_exhausted(" not in src:
        msgs.append("预算守卫：指挥官没有使用 scroll_budget_exhausted（缺『用尽即有界停止』）")
    return msgs


def probe_scroll_budget_per_item() -> bool:
    """#50 守卫 1：预算有限 + 区间内 + agent 单源绑定 + 选行先于滚动 + 指挥官接线。"""
    return _budget_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2 / 3：离线复现（多条目共享预算 vs 每条目重置）
#
# 真机行扫同款：29 行的降临讨伐列表（matrix_final.md 的 29 成员），
# 一屏 5 行、受控滚动 1 行/次（保守：真机 16448 观测 ~1 行/次）。
# 语义模型（不臆造触摸物理，只建模「链 + 命中计数 + 每条目重置」）：
#   · 每轮：SpecialEnterBoss 先判（行可见 → 选中、到达）；否则 SpecialScrollList 滚一次
#     （命中数 +1）；命中数 >= 上限 → 该节点被框架跳过（不再滚）。
# ---------------------------------------------------------------------------
ROWS = [
    "无猾机兵",           # 1
    "红嫉机兵",           # 2
    "苍叹机兵",           # 3
    "橙悚机兵",           # 4
    "闪哭机兵",           # 5
    "暗凛机兵",           # 6
    "始龙之眼",           # 7
    "为你奏响的镇魂歌",   # 8
    "圣夜的淘气鬼",       # 9
    "怨炎精灵兽",         # 10
    "水狂精灵兽",         # 11
    "魁雷精灵兽",         # 12
    "威风精灵兽",         # 13
    "巫光精灵兽",         # 14
    "暗唤精灵兽",         # 15
    "方舟守护者讨伐",     # 16
    "赤之女王讨伐",       # 17
    "青之女王讨伐",       # 18
    "碧之女王讨伐",       # 19
    "皓之女王讨伐",       # 20
    "墨之女王讨伐",       # 21
    "伊尔昂斯拉讨伐",     # 22
    "伊尔梅塔雷讨伐",     # 23
    "碧愁机兵",           # 24
    "金之女王讨伐",       # 25
    "伊尔格拉乌讨伐",     # 26
    "伊劳德雷斯讨伐",     # 27
    "伊萨巴迪卡讨伐",     # 28
    "伊尔考普斯讨伐",     # 29
]

WINDOW = 5          # 一屏可见 5 行
SCROLL_ROWS = 1     # 每次受控滚动 ≈ 1 行（真机 16448 观测：降临讨伐列表 ~1 行/次，
                    # 与 hooks_36 的 2 行/次同量级；这里取保守值以覆盖最深行）

# 复现目标 = 最深 5 行（「深批次被系统性惩罚」的最坏形态；行越深越吃亏）。
DEEP_TARGETS = ROWS[-5:]

# 目标行【根本不在列表里】——用于守卫 3（预算用尽 ⇒ 有界停止）。
ABSENT_TARGET = "不存在的成员讨伐"


class _Trace:
    __slots__ = ("reached", "skipped", "hits", "spin", "steps", "over_budget")

    def __init__(self):
        self.reached: list[str] = []
        self.skipped: list[str] = []
        self.hits = 0
        self.spin = False
        self.steps = 0
        self.over_budget = False


def _simulate(targets, *, budget, reset, safety_net, max_steps: int = 4000) -> _Trace:
    """一个 chunk = 一个任务，按顺序处理 ``targets``。返回 :class:`_Trace`。

    ``reset``       —— 每个条目开始时是否把预算抬到「已用 + 一份」（#50 新形态）。
    ``safety_net``  —— 预算用尽时是否「明确跳过并记录原因」（#50 新形态）。
    """
    si = _agent()
    tr = _Trace()
    ceiling = None
    for target in targets:
        if tr.steps >= max_steps:
            break
        # 指挥官切换条目：恢复预算（旧形态：整任务一份固定上限，不恢复）。
        if budget is not None:
            ceiling = si.restored_scroll_max_hit(tr.hits, budget) if reset else budget

        idx = ROWS.index(target) if target in ROWS else None
        offset = 0
        item_scrolls = 0
        done = False
        while tr.steps < max_steps:
            tr.steps += 1
            visible = idx is not None and offset <= idx <= offset + WINDOW - 1
            if visible:
                done = True
                break
            if budget is not None and tr.hits >= ceiling:
                # 命中数已达上限 → 框架跳过滚动节点，列表被冻住。
                if safety_net and si.scroll_budget_exhausted(tr.hits, ceiling):
                    break  # 明确跳过该目标（有界停止）
                tr.spin = True     # 无安全网：在 tab / 入口间静默空转
                continue
            tr.hits += 1
            item_scrolls += 1
            offset = min(offset + SCROLL_ROWS, len(ROWS) - WINDOW)

        if done:
            tr.reached.append(target)
        else:
            tr.skipped.append(target)
            if tr.steps >= max_steps:
                break
        if budget is not None and item_scrolls > budget:
            tr.over_budget = True
    return tr


def _budget() -> int | None:
    b = _declared_budget(_files())
    return b if isinstance(b, int) and not isinstance(b, bool) else None


def _repro_failures(*, reset=True, safety_net=True, budget=None, max_steps: int = 4000) -> list[str]:
    """守卫 2 的失败清单。默认（新形态）应绿；``reset=False`` 是旧形态对照。"""
    if budget is None:
        budget = _budget()
    msgs: list[str] = []
    if budget is None:
        return ["深行复现：读不到产品的每条目滚动预算（SpecialScrollList.max_hit）"]

    new = _simulate(DEEP_TARGETS, budget=budget, reset=reset, safety_net=safety_net, max_steps=max_steps)
    old = _simulate(DEEP_TARGETS, budget=budget, reset=False, safety_net=False, max_steps=max_steps)

    missing = [t for t in DEEP_TARGETS if t not in new.reached]
    if missing:
        msgs.append(
            f"深行复现：配置的新形态未能到达全部深行成员 {missing}（到达 {new.reached}）"
        )
    if new.over_budget:
        msgs.append("深行复现：新形态单条目滚动超过了一份预算（已不再有界）")
    if new.spin:
        msgs.append("深行复现：新形态出现了空转（不应发生）")
    if new.steps >= max_steps:
        msgs.append("深行复现：新形态跑到步数上限（有界性存疑）")
    if len(old.reached) >= len(DEEP_TARGETS):
        msgs.append("深行复现：旧形态（预算共享）竟也到达了全部深行成员 —— 未复现系统性惩罚")
    if not old.spin:
        msgs.append("深行复现：旧形态未复现『预算用尽后静默空转』")
    return msgs


def probe_scroll_budget_resets_per_item() -> bool:
    """#50 守卫 2：旧形态（共享预算）到不了后面的深行成员 / 新形态逐一到达且单条目有界。"""
    return _repro_failures() == []


def _bounded_stop_failures(*, safety_net=True, budget=None, max_steps: int = 4000) -> list[str]:
    """守卫 3 的失败清单：目标是【列表里不存在的行】。"""
    if budget is None:
        budget = _budget()
    msgs: list[str] = []
    if budget is None:
        return ["有界停止：读不到产品的每条目滚动预算（SpecialScrollList.max_hit）"]

    new = _simulate([ABSENT_TARGET], budget=budget, reset=True, safety_net=safety_net, max_steps=max_steps)
    if ABSENT_TARGET not in new.skipped:
        msgs.append("有界停止：配置的新形态未把『找不到的行』记为跳过（未记录原因）")
    if new.steps >= max_steps:
        msgs.append("有界停止：新形态跑到步数上限（用尽后没有及时停止）")
    old = _simulate([ABSENT_TARGET], budget=budget, reset=False, safety_net=False, max_steps=max_steps)
    if not old.spin:
        msgs.append("有界停止：旧形态未复现『静默空转』（对照失败）")
    return msgs


def probe_scroll_budget_bounded_stop() -> bool:
    """#50 守卫 3：找不到的行 → 滚完一份预算即明确跳过（有界）；旧形态静默空转。"""
    return _bounded_stop_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_50.py`）
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook50_assets_"))
    (root / "assets" / "resource").mkdir(parents=True)
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


def prove_red() -> bool:
    """真实绿；四处破坏各自变红（预算值 / 单源常量 / 指挥官接线 / 重置-安全网开关）。"""
    scene_on_path()
    print("hooks_50 prove-red：改坏预算/接线/开关，要求三个守卫各自变红")
    green = (
        probe_scroll_budget_per_item() is True
        and probe_scroll_budget_resets_per_item() is True
        and probe_scroll_budget_bounded_stop() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：预算单源 + 每条目重置 + 用尽有界（绿）")
    if not green:
        return False

    checks: list[bool] = []

    # 破坏 1：把产品的 max_hit 改成不合理的大值（且与 agent 单源常量不等）。
    root = _temp_pipeline()
    try:
        _sub(root / _PIPELINE_REL / _SD, '"max_hit": 80,\n', '"max_hit": 999999,\n')
        m1 = _budget_failures(root)
        red = len(m1) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 产品 max_hit=999999 -> 预算守卫"
              + (f"红（{m1[0]}）" if red else "仍绿（守卫没抓到！）"))
        checks.append(red)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # 破坏 2：agent 单源常量与产品不一致。
    m2 = _budget_failures(agent_budget=7)
    red = len(m2) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] agent _PER_ITEM_SCROLL_BUDGET=7 -> 预算守卫"
          + (f"红（{m2[0]}）" if red else "仍绿（守卫没抓到！）"))
    checks.append(red)

    # 破坏 3：去掉指挥官里的预算重置接线。
    src = _agent_source()
    broken = src.replace("_ensure_scroll_budget(context, task_id)", "_ensure_scroll_budget_DISABLED")
    if broken == src:
        print("  [FAIL] 找不到 _ensure_scroll_budget(context, task_id) 接线点（守卫已与实现脱节）")
        checks.append(False)
    else:
        m3 = _budget_failures(agent_source=broken)
        red = len(m3) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 摘掉指挥官的重置接线 -> 预算守卫"
              + (f"红（{m3[0]}）" if red else "仍绿（守卫没抓到！）"))
        checks.append(red)

    # 破坏 4：关掉重置 + 安全网（旧形态）→ 复现守卫 / 有界停止守卫必须红。
    m4a = _repro_failures(reset=False, safety_net=False)
    red4a = len(m4a) > 0
    print(f"  [{'PASS' if red4a else 'FAIL'}] 旧形态（预算共享、无安全网）-> 深行复现守卫"
          + (f"红（{m4a[0]}）" if red4a else "仍绿（守卫没抓到！）"))
    checks.append(red4a)

    m4b = _bounded_stop_failures(safety_net=False)
    red4b = len(m4b) > 0
    print(f"  [{'PASS' if red4b else 'FAIL'}] 关掉安全网 -> 有界停止守卫"
          + (f"红（{m4b[0]}）" if red4b else "仍绿（守卫没抓到！）"))
    checks.append(red4b)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "scroll-budget-per-item",
        "#50",
        "SpecialScrollList 的 max_hit 是有限、区间内的【每条目】预算，且与 agent 单源常量逐字段相等"
        "（选行先于滚动 + 指挥官接了预算重置/用尽判定）",
        probe_scroll_budget_per_item,
    ),
    (
        "scroll-budget-resets-per-item",
        "#50",
        "离线复现：旧形态（预算按任务共享）到不了后面的深行成员 / 新形态（每条目重置）逐一到达且有界",
        probe_scroll_budget_resets_per_item,
    ),
    (
        "scroll-budget-bounded-stop",
        "#50",
        "预算用尽即有界停止：找不到的行 → 滚完一份预算明确跳过并记录原因；旧形态静默空转",
        probe_scroll_budget_bounded_stop,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
