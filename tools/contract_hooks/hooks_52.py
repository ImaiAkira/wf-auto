# -*- coding: utf-8 -*-
"""#52（★#54 修订后★）：摇曳的迷宫（farm）—— 目标模型 = 【域 + 行名】。

本文件曾是 #52「域 + 元素独立轴」模型的守卫。#54 用设备（16448）**修订**了该模型：
迷宫页每个域是一张**异质行列表**，**元素是行名的一部分**（不是独立轴）——见
``tools/contract_hooks/hooks_54.py`` 的文件头（真机三域逐行结构 + 证据）。

本文件的**修订**（逐字说明，仅此一处，便于复核）：
  · 原实现断言 ``derive_maze_element_block`` / ``_apply_element`` / ``MAZE_ELEMENTS`` /
    ``FarmElementPick`` 等「元素轴」——这些在 #54 已从真源 / GUI / pipeline 中移除；
  · 现改为**委托** ``hooks_54._model_failures()``：hook id 与探针名保持不变
    （``maze-by-domain`` / ``probe_maze_by_domain``），因为既有测试
    （``tools/test_raid_farm_nav.py``）按名字调用它。model 断言不再在此重复一份。

★保留（未删）★：本文件与 ``hooks_54`` 都留在套件里；#52 的 hook id 继续点亮，故
「域 + 行名」两票的守卫都在场、都不沉默。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

HOOK_ID = "maze-by-domain"


def _maze54():
    """延迟导入 #54 守卫（避免 import 期循环 / 路径顺序问题）。"""
    from contract_hooks import hooks_54  # noqa: PLC0415

    return hooks_54


def _model_failures(agent_dir: Path | None = None) -> list[str]:
    """委托 #54 的「域 + 行名」模型全套断言（保留旧入口名，供既有调用方复用）。"""
    return _maze54()._model_failures(agent_dir=agent_dir)


def probe_maze_by_domain() -> bool:
    """#52（#54 修订后）：迷宫「域 + 行名」模型 + 配置真源一致（离线、不碰设备）。

    ★名字保留★：既有测试（``tools/test_raid_farm_nav.py``）按此名调用；实现委托给 #54。
    """
    return probe_maze_rows()


def probe_maze_rows() -> bool:
    """#54 模型探针（委托）。"""
    return _maze54().probe_maze_rows()


def prove_red() -> bool:
    """#52 的破坏实验委托 #54（两处破坏各自变红）。"""
    return _maze54().prove_red()


HOOKS = [
    (
        HOOK_ID,
        "#52",
        "摇曳的迷宫「域 + 行名」模型（#54 修订：元素是行名的一部分）：配置真源一致 / GUI 选项派生 / "
        "批量 域,行名,次数 / 行名末尾锚定 + 绝不误选相邻行 + 丢片段容错（真机帧正向证明）"
        "——实现委托 tools/contract_hooks/hooks_54.py",
        probe_maze_by_domain,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
