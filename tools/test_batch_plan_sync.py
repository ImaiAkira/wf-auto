# -*- coding: utf-8 -*-
"""离线单测（#34）：agent 侧「难度词表 / 降临成员表」与配置真源不分叉。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_batch_plan_sync.py

背景见 ``tools/contract_hooks/hooks_34.py``。真机校正的来源见 #32
（``tools/test_lord_data.py`` / ``hooks_32``）。本文件**只读**，绝不写盘。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
for _p in (str(AGENT_DIR), str(REPO_ROOT), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import batch_plan as bp  # noqa: E402
from contract_hooks import hooks_34  # noqa: E402
from scene.config import DIFFICULTIES as TRUTH_DIFFICULTIES  # noqa: E402
from scene.lord_battle import LORD_BATTLE  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def truth_joss() -> set[str]:
    return {m.行名 for m in LORD_BATTLE.members if m.子族 == "降临讨伐"}


def test_no_divergence() -> None:
    print("\n== 1. agent 侧词表 / 名单与真源一致（复用挂点 #34 的守卫逻辑） ==")
    fails = hooks_34._sync_failures(bp)
    check("hooks_34._sync_failures 为空（无分叉）", fails == [], f"fails={fails}")


def test_difficulty_vocabulary() -> None:
    print("\n== 2. 难度词表含「地狱级」，且正则锚定正确 ==")
    check("batch_plan.DIFFICULTIES == scene.config.DIFFICULTIES",
          set(bp.DIFFICULTIES) == set(TRUTH_DIFFICULTIES),
          f"bp={bp.DIFFICULTIES} truth={TRUTH_DIFFICULTIES}")
    check("地狱级 在词表里", "地狱级" in bp.DIFFICULTIES)
    check("DIFF_REGEX 有 地狱级 且带 $ 锚定",
          bp.DIFF_REGEX.get("地狱级") == r"地狱级$", f"got={bp.DIFF_REGEX.get('地狱级')!r}")
    check("高级$ 不误命中 高级+", re.fullmatch(bp.DIFF_REGEX["高级"], "高级+") is None)
    check("高级+ 正则该命中自己", re.fullmatch(bp.DIFF_REGEX["高级+"], "高级+") is not None)


def test_joss_roster() -> None:
    print("\n== 3. 降临成员表按真机校正（补 6 名、去 石芯心六） ==")
    truth = truth_joss()
    check("batch_plan.JOSS_NAMES == 真源降临行名集",
          set(bp.JOSS_NAMES) == truth,
          f"多={sorted(set(bp.JOSS_NAMES) - truth)} 缺={sorted(truth - set(bp.JOSS_NAMES))}")
    for name in hooks_34.NEW_JOSS:
        check(f"#32 新增降临成员「{name}」在列", bp.is_joss(name) is True)
    check("石芯心六 不在列（真机不存在）", bp.is_joss("石芯心六") is False)
    check("领主战成员不是 joss", bp.is_joss("猩红巨熊讨伐") is False)


def test_snapshot_matches_truth() -> None:
    print("\n== 4. 安装态快照与真源一致（客户端实际使用的副本） ==")
    check("_DIFFICULTIES_SNAPSHOT == 真源词表",
          set(bp._DIFFICULTIES_SNAPSHOT) == set(TRUTH_DIFFICULTIES),
          f"snap={bp._DIFFICULTIES_SNAPSHOT}")
    check("_JOSS_NAMES_SNAPSHOT == 真源降临行名集",
          frozenset(bp._JOSS_NAMES_SNAPSHOT) == frozenset(truth_joss()),
          f"多={sorted(set(bp._JOSS_NAMES_SNAPSHOT) - truth_joss())} "
          f"缺={sorted(truth_joss() - set(bp._JOSS_NAMES_SNAPSHOT))}")


def test_glossary_not_hardcoded() -> None:
    print("\n== 5. GLOSSARY 不再写死成员数量、点名真源 ==")
    text = (REPO_ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    check("GLOSSARY 无写死的「39 个」", "39 个" not in text)
    check("GLOSSARY 点名 scene/lord_battle.py", "scene/lord_battle.py" in text)
    check("GLOSSARY 点名 scene.config.DIFFICULTIES", "scene.config.DIFFICULTIES" in text)


def main() -> None:
    print("=" * 70)
    print("离线单测：agent 侧难度词表 / 降临成员表与配置真源一致（#34）")
    print(f"（事实来源 FACTS_SOURCE = {bp.FACTS_SOURCE}）")
    print("=" * 70)
    test_no_divergence()
    test_difficulty_vocabulary()
    test_joss_roster()
    test_snapshot_matches_truth()
    test_glossary_not_hardcoded()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
