# -*- coding: utf-8 -*-
"""迷宫入口 ``FarmMazeEntry`` 的【有界重试】+ 重试用尽后的【可见失败】。

缺陷（在 #60 的迷宫工作里发现，真机可复现）
------------------------------------------
``assets/resource/pipeline/farm.json::FarmMazeEntry`` 过去 ``max_hit: 1`` —— 整个任务只允许
【一次】命中。可主城左侧【轮播横幅】会转走（子区域约每 6s 自转，整条轮播约 30~40s 才轮到
迷宫一次），识别到→点击之间存在竞态：那唯一一次点空后，框架会**永久跳过**本节点（命中数已到
上限），于是再也进不了迷宫页，只能 ``FarmDispatch → FarmWait`` 空转到 1200s 超时
（“刷迷宫”经常第一次就进不去）。#60 lane 只是**临时**把 max_hit 抬到 6 才让那一次运行通过
（临时包装未提交）。

修复（两条，缺一不可）
--------------------
1. **有界重试**（``assets/resource/pipeline/farm.json``）：``FarmMazeEntry.max_hit`` 1 -> 6。
   每次重试都经 ``FarmDispatch`` 分派循环回到本节点、在**新鲜帧**上重新识别（与模板门控同帧），
   命中（横幅正是声明的那个域）才点击；**有限次数**、用尽即停。
   ★不改 ``next``★：``tools/test_scene_unchanged._guard_nexts_home``（#9）要求 farm 链每个节点
   的 ``next`` 一律回 ``SpecialEntry``；重试靠 ``max_hit``，不靠 self-loop（自环一旦与
   ``max_hit`` 脱钩就是无界 spin）。★域仍由模板判★（#57 语义不动）。
2. **用尽后可见失败**（``agent/side_impl.py``）：farm 被 #54 移出 ``_BATCH_NAV_TIMEOUT_BY_KIND``
   （那是 #45 的声明表）后，「导航之后、开打之前」就没有任何上限了 —— 若重试用尽仍没进迷宫页，
   指挥官会空转到任务超时。现在给 farm 一个**有界**兜底导航上限 ``_FARM_NAV_DEADLINE_SEC``
   （180s），超时即走 #45/#62 同一套「**明确跳过该目标 + 打印原因**」
   （``[batch] … 跳过该目标（绝不空转）``）——绝不静默空转、绝不假记账。

守卫（本文件；prove-red 也在本文件末尾）
--------------------------------------
1. ``maze-entry-bounded-retry`` —— ``FarmMazeEntry.max_hit`` 是**有限且在合理区间**的整数
   （2..12；既不是 1，也不是缺省 / 巨大 = 无界）；``next`` 仍是 ``['SpecialEntry']``（无自环）。
2. ``maze-entry-domain-still-template`` —— 仍是 ``And[FarmMazeDomain(模板), FarmMazeTitle(OCR)]``、
   ``box_index=0``、``Click target:true``；域判据是 ``TemplateMatch``、标题 OCR 的 expected
   **不含任何域名**（#57：域只由图片模板判，OCR 绝不参与判域）。
3. ``maze-entry-exhaustion-visible`` —— ``side_impl._FARM_NAV_DEADLINE_SEC`` 有限且在合理区间
   （60..900s）；指挥官确实在 ``kind == 'farm'`` 时接上它；且超时走**明确跳过 + 打印原因**
   （``print(f"[batch] {reason}")`` 源码在场）——不是静默 spin。
4. ``maze-entry-no-regression`` —— #9 的 farm 结构守卫仍绿（``test_scene_unchanged.guard_farm``）；
   ``scene.drift.check_all() == []``。

★prove-red★（``python tools\\contract_hooks\\hooks_maze_entry.py``）：
  * ``max_hit = 1``（复现缺陷）-> 守卫 1 红；
  * 删掉 ``max_hit``（= 缺省 UINT_MAX = 无界）-> 守卫 1 红；
  * ``max_hit`` 巨大（999999）-> 守卫 1 红；
  * ``next`` 改自环 ``['FarmMazeEntry','SpecialEntry']`` -> 守卫 1 红；
  * 域判据换成 OCR（去掉 ``FarmMazeDomain`` 模板叶）-> 守卫 2 红；
  * 摘掉 farm 的兜底导航上限分支 -> 守卫 3 红；
  * 兜底上限改成无界（1e9）-> 守卫 3 红。

全离线、不碰设备。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
SIDE_IMPL = AGENT_DIR / "side_impl.py"

# ★只 append 到 sys.path 末尾★：prove-red 若用 PYTHONPATH 抢先塞副本仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

import hooks_60  # noqa: E402  （复用 JSONC 读取，load_farm）

TICKET = "#maze-entry"
ENTRY = "FarmMazeEntry"

#: 有界重试的合理区间（含）。max_hit:1 = 缺陷本体；> MAX = 无界/过大（重试必须有界）。
ENTRY_MAX_HIT_MIN = 2
ENTRY_MAX_HIT_MAX = 12
#: 兜底导航上限的合理区间（秒）。太小会误伤“只是等轮播”的正常目标；太大则「有界」名不副实。
FARM_NAV_DEADLINE_MIN = 60.0
FARM_NAV_DEADLINE_MAX = 900.0


def _agent(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _side_source() -> str:
    return SIDE_IMPL.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 守卫 1：有界重试（max_hit 有限且合理；next 不自环）
# ---------------------------------------------------------------------------
def entry_bound_failures(farm: dict | None = None) -> list[str]:
    f = hooks_60.load_farm() if farm is None else farm
    msgs: list[str] = []
    node = f.get(ENTRY)
    if not isinstance(node, dict):
        return [f"farm.json 缺少 {ENTRY}（迷宫入口被删？）"]

    mh = node.get("max_hit")
    if isinstance(mh, bool) or not isinstance(mh, int):
        msgs.append(
            f"{ENTRY}.max_hit={mh!r} 缺失/非整数 —— 缺省 = UINT_MAX = **无界**重试"
            "（点不进去就永远重试，没有上限）"
        )
    elif mh < ENTRY_MAX_HIT_MIN:
        msgs.append(
            f"{ENTRY}.max_hit={mh} < {ENTRY_MAX_HIT_MIN}：max_hit:1 = 整个任务只允许【一次】"
            "命中 —— 轮播转走时那唯一一次点空后本节点被永久跳过 -> 空转到超时（缺陷本体）"
        )
    elif mh > ENTRY_MAX_HIT_MAX:
        msgs.append(
            f"{ENTRY}.max_hit={mh} > {ENTRY_MAX_HIT_MAX}：重试**无界/过大**"
            "（有界重试才有意义；用尽必须能停）"
        )

    if node.get("next") != ["SpecialEntry"]:
        msgs.append(
            f"{ENTRY}.next={node.get('next')!r} != ['SpecialEntry']（#9 要求 farm 链每节点回"
            " SpecialEntry；self-loop 与 max_hit 脱钩即无界 spin）"
        )
    return msgs


def probe_maze_entry_bounded_retry() -> bool:
    return entry_bound_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：#57 域判定语义不变（域 = 图片模板；OCR 不作域判据）
# ---------------------------------------------------------------------------
def domain_failures(farm: dict | None = None) -> list[str]:
    f = hooks_60.load_farm() if farm is None else farm
    from scene.config import MAZE_DOMAINS  # noqa: PLC0415

    msgs: list[str] = []
    entry = f.get(ENTRY, {})
    rec = entry.get("recognition", {})
    if rec.get("type") != "And":
        msgs.append(f"{ENTRY}.recognition 不是 And（标题 ∧ 域 的与门），实际 {rec.get('type')!r}")
    else:
        p = rec.get("param", {})
        if p.get("all_of") != ["FarmMazeDomain", "FarmMazeTitle"]:
            msgs.append(
                f"{ENTRY}.all_of={p.get('all_of')!r} != ['FarmMazeDomain','FarmMazeTitle']"
                "（域的判据被改了？）"
            )
        if p.get("box_index") != 0:
            msgs.append(f"{ENTRY}.box_index={p.get('box_index')!r} != 0（应点横幅域名美术字）")

    act = entry.get("action", {})
    if act.get("type") != "Click" or act.get("param", {}).get("target") is not True:
        msgs.append(
            f"{ENTRY} 动作应为 Click target:true（点自身识别框中心、零偏移），实际 "
            f"{act.get('type')!r}/{act.get('param', {}).get('target')!r}"
        )

    dom = (f.get("FarmMazeDomain") or {}).get("recognition", {})
    if dom.get("type") != "TemplateMatch":
        msgs.append(
            f"FarmMazeDomain 的 recognition 不是 TemplateMatch（域必须由图片模板判，不得用 OCR）："
            f"{dom.get('type')!r}"
        )

    title = (f.get("FarmMazeTitle") or {}).get("recognition", {})
    if title.get("type") != "OCR":
        msgs.append(f"FarmMazeTitle 应为标题 OCR 次要叶，实际 {title.get('type')!r}")
    else:
        for pat in (title.get("param", {}).get("expected") or []):
            for d in MAZE_DOMAINS:
                if d in pat:
                    msgs.append(f"标题 OCR 判据 {pat!r} 含域名 {d!r}（OCR 不得作域判据，#57）")
    return msgs


def probe_maze_entry_domain_still_template() -> bool:
    return domain_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：重试用尽 -> 可见失败（有界兜底导航上限 + 明确跳过 + 打印原因）
# ---------------------------------------------------------------------------
def exhaustion_failures(*, source: str | None = None, deadline=None, agent_dir=None) -> list[str]:
    src = _side_source() if source is None else source
    if deadline is None:
        si = _agent(agent_dir)
        deadline = getattr(si, "_FARM_NAV_DEADLINE_SEC", None)

    msgs: list[str] = []
    try:
        val = float(deadline)
    except (TypeError, ValueError):
        val = -1.0
    if not (FARM_NAV_DEADLINE_MIN <= val <= FARM_NAV_DEADLINE_MAX):
        msgs.append(
            f"_FARM_NAV_DEADLINE_SEC={deadline!r} 不在合理区间 "
            f"[{FARM_NAV_DEADLINE_MIN},{FARM_NAV_DEADLINE_MAX}]（太小误伤等轮播的正常目标 / "
            f"太大或缺失 = 名不副实，重试用尽仍会空转到超时）"
        )
    if 'getattr(running, "kind", "special") == "farm"' not in src:
        msgs.append(
            "指挥官没有在 kind=='farm' 时接上兜底导航上限 —— FarmMazeEntry 重试用尽后仍会"
            "空转到任务超时（静默 spin）"
        )
    if "nav_timeout = _FARM_NAV_DEADLINE_SEC" not in src:
        msgs.append("指挥官没有把 _FARM_NAV_DEADLINE_SEC 赋给 nav_timeout（兜底上限不生效）")
    if 'print(f"[batch] {reason}")' not in src:
        msgs.append("缺少「明确跳过 + 打印原因」的可见失败出口（会静默 spin）")
    return msgs


def probe_maze_entry_exhaustion_visible() -> bool:
    return exhaustion_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：不回归（#9 farm 结构守卫 + drift）
# ---------------------------------------------------------------------------
def no_regression_failures() -> list[str]:
    msgs: list[str] = []
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.guard_farm()
        if fails:
            msgs.append(f"#9 farm 结构守卫变红（本票带坏了 farm 链）：{fails[:2]}")
    except Exception as exc:  # noqa: BLE001 -- 坏实现也要变红
        msgs.append(f"#9 farm 守卫无法运行：{exc!r}")

    try:
        from scene import drift  # noqa: PLC0415

        allm = drift.check_all(repo_root=REPO_ROOT)
        if allm:
            msgs.append(f"drift.check_all() 非空：{allm[:2]}")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"drift.check_all() 无法运行：{exc!r}")
    return msgs


def probe_maze_entry_no_regression() -> bool:
    return no_regression_failures() == []


HOOKS = [
    (
        "maze-entry-bounded-retry",
        TICKET,
        "迷宫入口 FarmMazeEntry 有界重试：max_hit 有限且在 [2,12]（不是 1、不是缺省/巨大 = 无界）；"
        "next 仍回 SpecialEntry（不自环）",
        probe_maze_entry_bounded_retry,
    ),
    (
        "maze-entry-domain-still-template",
        TICKET,
        "域判定语义不变（#57）：入口 = And[FarmMazeDomain 模板, FarmMazeTitle OCR]、box_index=0、"
        "Click target:true；域判据是 TemplateMatch、标题 OCR 不含域名",
        probe_maze_entry_domain_still_template,
    ),
    (
        "maze-entry-exhaustion-visible",
        TICKET,
        "重试用尽 -> 可见失败：farm 有界兜底导航上限（60..900s）+ 指挥官接上 + 超时走"
        "「明确跳过 + 打印原因」，绝不静默 spin",
        probe_maze_entry_exhaustion_visible,
    ),
    (
        "maze-entry-no-regression",
        TICKET,
        "#9 farm 结构守卫仍绿；drift.check_all() == []",
        probe_maze_entry_no_regression,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_maze_entry.py`）
# ---------------------------------------------------------------------------
def _mut(broken: dict, mutate) -> dict:
    d = copy.deepcopy(broken)
    mutate(d)
    return d


def prove_red() -> bool:
    print("hooks_maze_entry prove-red：有界重试 + 域模板 + 可见失败，要求守卫各自变红")
    farm = hooks_60.load_farm()
    src = _side_source()

    green = (
        probe_maze_entry_bounded_retry() is True
        and probe_maze_entry_domain_still_template() is True
        and probe_maze_entry_exhaustion_visible() is True
        and probe_maze_entry_no_regression() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：有界重试 + 域模板 + 可见失败（绿）")
    if not green:
        return False

    checks: list[bool] = []

    # (a) max_hit = 1（复现缺陷）-> 守卫 1 红。
    m = entry_bound_failures(_mut(farm, lambda d: d[ENTRY].__setitem__("max_hit", 1)))
    red_a = len(m) > 0
    print(f"  [{'PASS' if red_a else 'FAIL'}] max_hit=1（复现缺陷）-> 有界守卫"
          + (f"红（{m[0]}）" if m else "仍绿（守卫没抓到！）"))
    checks.append(red_a)

    # (b) 删掉 max_hit（缺省 UINT_MAX = 无界）-> 守卫 1 红。
    m = entry_bound_failures(_mut(farm, lambda d: d[ENTRY].pop("max_hit", None)))
    red_b = len(m) > 0
    print(f"  [{'PASS' if red_b else 'FAIL'}] 删掉 max_hit（= 无界）-> 有界守卫"
          + (f"红（{m[0]}）" if m else "仍绿（守卫没抓到！）"))
    checks.append(red_b)

    # (c) max_hit 巨大（999999）-> 守卫 1 红。
    m = entry_bound_failures(_mut(farm, lambda d: d[ENTRY].__setitem__("max_hit", 999999)))
    red_c = len(m) > 0
    print(f"  [{'PASS' if red_c else 'FAIL'}] max_hit=999999（无界/过大）-> 有界守卫"
          + (f"红（{m[0]}）" if m else "仍绿（守卫没抓到！）"))
    checks.append(red_c)

    # (d) next 改自环 -> 守卫 1 红。
    m = entry_bound_failures(_mut(farm, lambda d: d[ENTRY].__setitem__("next", [ENTRY, "SpecialEntry"])))
    red_d = len(m) > 0
    print(f"  [{'PASS' if red_d else 'FAIL'}] next 改自环 -> 有界守卫"
          + (f"红（{m[0]}）" if m else "仍绿（守卫没抓到！）"))
    checks.append(red_d)

    # (e) 域判据换成 OCR（去掉 FarmMazeDomain 模板叶）-> 守卫 2 红。
    m = domain_failures(
        _mut(farm, lambda d: d[ENTRY]["recognition"]["param"].__setitem__("all_of", ["FarmMazeTitle"]))
    )
    red_e = len(m) > 0
    print(f"  [{'PASS' if red_e else 'FAIL'}] 入口去掉域模板叶（改看标题 OCR）-> 域守卫"
          + (f"红（{m[0]}）" if m else "仍绿（守卫没抓到！）"))
    checks.append(red_e)

    # (f) 摘掉 farm 的兜底导航上限分支 -> 守卫 3 红。
    broken_src = src.replace('getattr(running, "kind", "special") == "farm"',
                             'getattr(running, "kind", "special") == "farm_BROKEN"')
    red_f = broken_src != src and len(exhaustion_failures(source=broken_src)) > 0
    print(f"  [{'PASS' if red_f else 'FAIL'}] 摘掉 farm 兜底导航上限分支 -> 可见失败守卫"
          + ("红" if red_f else "仍绿（守卫没抓到！）"))
    checks.append(red_f)

    # (g) 兜底上限改成无界（1e9）-> 守卫 3 红。
    m = exhaustion_failures(deadline=10 ** 9)
    red_g = len(m) > 0
    print(f"  [{'PASS' if red_g else 'FAIL'}] 兜底上限 = 1e9（无界）-> 可见失败守卫"
          + (f"红（{m[0]}）" if m else "仍绿（守卫没抓到！）"))
    checks.append(red_g)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
