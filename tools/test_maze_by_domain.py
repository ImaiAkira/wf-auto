# -*- coding: utf-8 -*-
"""离线单测（#52，★#54 修订后★）：摇曳的迷宫 = 【域 + 行名】（元素是行名的一部分）。

★本文件的修订★（逐字说明）：#52 的原文断言「域 + 元素独立选项」（``derive_maze_element_block`` /
``MAZE_ELEMENTS`` / ``_apply_element`` / ``FarmElementPick``）——这些已被 #54 用设备证伪并从
真源 / GUI / pipeline 移除。本文件改为断言**修订后的**「域 + 行名」模型，并把「全套模型断言」
交给新票的守卫 ``tools/contract_hooks/hooks_54.py``（不在此重复一份）。文件名 / 入口保持不变。

跑法::

    .venv\\Scripts\\python.exe tools\\test_maze_by_domain.py
"""

from __future__ import annotations

import sys
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

import batch_plan as bp  # noqa: E402
import side_impl as si  # noqa: E402
import hooks_52  # noqa: E402
import hooks_54  # noqa: E402
from scene import drift  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    print("=" * 76)
    print("#52（#54 修订）：摇曳的迷宫 = 【域 + 行名】（元素是行名的一部分）")
    print("=" * 76)

    print("\n== 1. 修订后的模型（委托 hooks_54） ==")
    check("三域（崩坏域/宝物域/幽玄域）", tuple(bp.MAZE_DOMAINS) == ("崩坏域", "宝物域", "幽玄域"))
    check("行数 22 / 6 / 10",
          {d: len(bp.MAZE_ROWS[d]) for d in bp.MAZE_DOMAINS}
          == {"崩坏域": 22, "宝物域": 6, "幽玄域": 10})
    check("hooks_54.probe_maze_rows() 绿（域 + 行名 + 真机帧正证 + 相邻行守护）",
          hooks_54.probe_maze_rows() is True)
    check("hooks_52.probe_maze_by_domain() 绿（委托）", hooks_52.probe_maze_by_domain() is True)

    print("\n== 2. 配置为真源 / drift 空 ==")
    check("drift.maze_option_drift(interface) == []",
          drift.maze_option_drift(INTERFACE) == [], f"{drift.maze_option_drift(INTERFACE)}")
    check("drift.check_all() == []", drift.check_all(repo_root=REPO_ROOT) == [],
          f"{drift.check_all(repo_root=REPO_ROOT)}")

    print("\n== 3. 批量清单（域,行名,次数）+ farm 非能力缺口 ==")
    items, errors = bp.parse_batch("崩坏域,临境域深渊之兽·极,1\n")
    check("崩坏域,临境域深渊之兽·极,1 合法",
          errors == [] and items[0].target == "临境域深渊之兽·极"
          and items[0].domain == "崩坏域", f"errors={errors}")
    _it, err = bp.parse_batch("宝物域,风,3\n")
    check("旧「域,元素」写法不合法", len(err) == 1, f"errors={err}")
    check("declared_unreachable('farm') is None", si.declared_unreachable("farm") is None)

    print("\n== 4. 守卫 + 破坏实验 ==")
    check("hooks_54.prove_red() 成立", hooks_54.prove_red() is True)
    check("hooks_52.prove_red() 成立（委托）", hooks_52.prove_red() is True)

    print("\n" + "=" * 76)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
