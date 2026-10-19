# -*- coding: utf-8 -*-
"""#34：agent 侧的「难度词表 / 降临讨伐成员表」不得与配置真源分叉。

seam：``scene.config.DIFFICULTIES`` + ``scene.lord_battle``（真源，ADR-0001）
      ↔ ``agent/batch_plan.py``（``DIFFICULTIES`` / ``DIFF_REGEX`` / ``JOSS_NAMES``）。

背景
----
``agent/batch_plan.py`` 曾在 agent 侧各写一份「难度词表 / 降临成员表」：``JOSS_NAMES``
漏了 #32 补的 6 名降临成员、还留着真机不存在的 ``石芯心六``；``DIFF_REGEX`` 词表缺
``地狱级``。这正是「同一件事写两遍」的缺陷形态 —— 修法是复制正确值只会再造一次缺陷。

本票的处理：agent 侧**优先从真源派生**（开发 / 测试态仓库根有 ``scene/``）；安装态
（``tools/install.py`` 的 ``install_agent`` 只随包发出 ``agent/``，仓库根的 ``scene/``
不在安装目录里）派生不到时，回退到一批**冻结快照**。本守卫把「派生结果 / 快照 / 真源」
三者钉死：任何一处与真源分叉都当场变红。

守卫 ``agent-facts-match-config``
--------------------------------
1. ``batch_plan.DIFFICULTIES`` == ``scene.config.DIFFICULTIES``；
2. ``batch_plan.JOSS_NAMES`` == ``scene.lord_battle`` 里子族 ``降临讨伐`` 的行名集；
3. ``batch_plan.DIFF_REGEX`` 覆盖同一词表，且「高级」正则不误命中「高级+」；
4. 冻结快照 ``_DIFFICULTIES_SNAPSHOT`` / ``_JOSS_NAMES_SNAPSHOT`` 与真源一致
   （安装态跑的就是它们，必须逐字一致）；
5. ``is_joss`` 行为：#32 新增的 6 名降临成员为真、``石芯心六`` 为假、领主战成员为假；
6. ``GLOSSARY.md`` 不再写死成员数量，且点名真源 ``scene/lord_battle.py``。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_34.py``）：把 agent 侧的
安装态冻结快照改坏（临时副本）-> 守卫必须变红。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
GLOSSARY = REPO_ROOT / "GLOSSARY.md"

HOOK_ID = "agent-facts-match-config"

# #32 补进真源的 6 名降临成员（本守卫顺带钉死 agent 侧确实认得它们）。
NEW_JOSS = (
    "碧愁机兵", "金之女王讨伐", "伊尔格拉乌讨伐",
    "伊劳德雷斯讨伐", "伊萨巴迪卡讨伐", "伊尔考普斯讨伐",
)
# 真机不存在、必须从任何名单里消失的名字。
NONEXISTENT = ("石芯心六",)
# 领主战成员（用于反例：不得被当成 joss）。
LORD_SAMPLE = ("猩红巨熊讨伐", "妖狐讨伐")


def _paths_on_path() -> None:
    """把 agent/ 与仓库根放进 sys.path（scene 与 batch_plan 才能一起导入）。"""
    for p in (str(REPO_ROOT), str(AGENT_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def truth_facts():
    """真源事实：(难度词表 tuple, 降临讨伐行名 frozenset)。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    from scene.config import DIFFICULTIES  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415

    joss = frozenset(m.行名 for m in LORD_BATTLE.members if m.子族 == "降临讨伐")
    return tuple(DIFFICULTIES), joss


def _sync_failures(bp) -> list[str]:
    """核对某个 batch_plan 模块与真源是否一致；返回失败信息（空 = 一致）。"""
    import re  # noqa: PLC0415

    difficulties, joss = truth_facts()
    msgs: list[str] = []

    if set(bp.DIFFICULTIES) != set(difficulties):
        msgs.append(
            f"难度词表分叉：batch_plan.DIFFICULTIES={sorted(bp.DIFFICULTIES)} "
            f"!= scene.config.DIFFICULTIES={sorted(difficulties)}"
        )
    if frozenset(bp.JOSS_NAMES) != joss:
        msgs.append(
            f"降临成员表分叉：batch_plan 多={sorted(set(bp.JOSS_NAMES) - joss)} "
            f"缺={sorted(joss - set(bp.JOSS_NAMES))}（真源：scene.lord_battle）"
        )

    # DIFF_REGEX 覆盖同一词表，且锚定正确（「高级$」绝不能命中「高级+」）。
    if set(bp.DIFF_REGEX) != set(difficulties):
        msgs.append(
            f"难度正则表分叉：batch_plan.DIFF_REGEX 键={sorted(bp.DIFF_REGEX)} "
            f"!= 真源词表={sorted(difficulties)}"
        )
    for d, rx in bp.DIFF_REGEX.items():
        try:
            ok = re.fullmatch(rx, d) is not None
        except re.error as exc:
            msgs.append(f"难度正则 {d!r} 无法编译：{exc}")
            continue
        if not ok:
            msgs.append(f"难度正则 {d!r} -> {rx!r} 匹配不到自己（锚定写错？）")
    if re.fullmatch(bp.DIFF_REGEX.get("高级", "x"), "高级+") is not None:
        msgs.append("难度正则「高级$」误命中「高级+」（必须带 $ 锚定）")

    # 冻结快照（安装态实际使用的副本）必须与真源一致。
    snap_d = getattr(bp, "_DIFFICULTIES_SNAPSHOT", None)
    snap_j = getattr(bp, "_JOSS_NAMES_SNAPSHOT", None)
    if snap_d is None or set(snap_d) != set(difficulties):
        msgs.append(
            f"安装态快照 _DIFFICULTIES_SNAPSHOT={snap_d} 与真源 "
            f"{list(difficulties)} 不一致"
        )
    if snap_j is None:
        msgs.append("安装态快照 _JOSS_NAMES_SNAPSHOT 缺失")
    elif frozenset(snap_j) != joss:
        msgs.append(
            f"安装态快照 _JOSS_NAMES_SNAPSHOT 与真源不一致："
            f"多={sorted(set(snap_j) - joss)} 缺={sorted(joss - set(snap_j))}"
        )

    # is_joss 行为。
    for name in NEW_JOSS:
        if not bp.is_joss(name):
            msgs.append(f"is_joss({name!r}) 应为真（#32 新增的降临成员）")
    for name in NONEXISTENT:
        if bp.is_joss(name):
            msgs.append(f"is_joss({name!r}) 应为假（真机不存在该行）")
    for name in LORD_SAMPLE:
        if bp.is_joss(name):
            msgs.append(f"is_joss({name!r}) 应为假（领主战成员，不是降临讨伐）")

    # GLOSSARY 不再写死数量，且点名真源。
    try:
        glossary = GLOSSARY.read_text(encoding="utf-8")
    except OSError as exc:
        msgs.append(f"读不到 GLOSSARY.md：{exc}")
    else:
        if "39 个" in glossary:
            msgs.append("GLOSSARY.md 仍写死成员数量「39 个」（应指向真源 scene/lord_battle.py）")
        if "scene/lord_battle.py" not in glossary:
            msgs.append("GLOSSARY.md 未点名成员表真源 scene/lord_battle.py")
    return msgs


def probe_agent_facts_match_config() -> bool:
    """#34：agent 侧难度词表 / 降临成员表与配置真源一致。"""
    _paths_on_path()
    import batch_plan as bp  # noqa: PLC0415

    return _sync_failures(bp) == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_34.py`）
# ---------------------------------------------------------------------------
def _probe_in(agent_copy: Path):
    """子进程里、以 ``agent_copy`` 作为 batch_plan 来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "import batch_plan\n"
        "from contract_hooks import hooks_34\n"
        "print('PROBE_RESULT', repr(hooks_34._sync_failures(batch_plan) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral34_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
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


def _break_add_ghost_joss(agent_dir: Path) -> None:
    """破坏：给安装态快照塞一个真源里没有的名字（快照与真源分叉）。"""
    path = agent_dir / "batch_plan.py"
    text = path.read_text(encoding="utf-8")
    old = '    "伊劳德雷斯讨伐", "伊萨巴迪卡讨伐", "伊尔考普斯讨伐",\n}'
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    new = '    "伊劳德雷斯讨伐", "伊萨巴迪卡讨伐", "伊尔考普斯讨伐", "幽灵成员",\n}'
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def prove_red() -> bool:
    """真实绿；把安装态冻结快照改坏 -> 守卫变红。"""
    print("hooks_34 prove-red：改坏 agent 侧安装态快照，要求 agent-facts-match-config 变红")
    green = probe_agent_facts_match_config() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：agent 侧与真源一致（绿）")
    if not green:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook34_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_add_ghost_joss(tmp / "agent")
        red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 改坏快照 -> 探针变红")
    ok = green and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#34",
        "agent 侧难度词表 / 降临成员表从配置真源派生（安装态快照也必须一致，否则变红）",
        probe_agent_facts_match_config,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
