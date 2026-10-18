# -*- coding: utf-8 -*-
"""#9：不变守卫（幻想 / 战阵 / 迷宫）的挂点。已点亮。

断言本体在 ``tools/test_scene_unchanged.py``（离线一键入口、--prove-red 都在那里）；
本探针复用同一份守卫逻辑，保证「挂点」与「测试文件」不分叉——不会出现挂点绿、
测试文件红的割裂。

绿 = 分派接线 + 三条既有路径的管线结构不变量 + agent 判定（分类正反例）全部成立；
任一被改坏 -> False -> 套件红（红 = 可用信号）。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def probe_behavior_unchanged():
    """幻想 / 战阵 / 迷宫三条既有路径行为不变（结构 + agent 判定，含反例帧）。

    反例帧（结算奖励条含「战斗分数/最长滞空时间」）必须【正判为结算】，
    不是靠 unknown /「没看到」蒙混 —— 这正是 32 分钟空转老 bug 的防线。
    """
    import test_scene_unchanged as tsu  # noqa: PLC0415

    return tsu.run_guards() == []


HOOKS = [
    (
        "behavior-unchanged",
        "#9",
        "幻想 / 战阵 / 迷宫三条既有路径行为不变（结构不变量 + agent 判定，含反例帧）",
        probe_behavior_unchanged,
    ),
]
