# -*- coding: utf-8 -*-
"""#6：GUI 目标选项由配置生成的挂点（已点亮）。

守卫「N 个成员 -> derive 出的 GUI 选项恰 N 项」，并顺带守住注入的**幂等**与
「手改生成区即判漂移」。对应 ADR-0001（配置为真源；注入幂等、不假脏）。

``prove_red()`` 是**本模块自带**的破坏实验：把 derive 改成丢一个成员，要求守卫当场变红。
它不走 ``tools/test_offline_contract.py`` 里那份中央 prove-red 配方（lane 不得改它），
而是由本票自己的 ``tools/test_scene_options.py`` 调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 注入用的最小 interface 骨架（顶层 "option": { 映射 + 一个既有条目 + 一条注释）。
_SKELETON = (
    "{\n"
    '    "task": [],\n'
    '    "option": {\n'
    "        // 既有的手写条目\n"
    '        "抽哪个池": { "type": "select", "cases": [] }\n'
    "    }\n"
    "}\n"
)


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】。

    放末尾是有意的：--prove-red 会在子进程里用 PYTHONPATH 指向一份坏掉的
    ``scene`` 副本（其位置在 sys.path 里更靠前），这里的真实仓库根不会把它盖掉。
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def probe_derive_gui_options():
    """#6：N 个成员 -> derive 出的 GUI 选项恰 N 项；增删成员随之变化；注入幂等。

    全程走 ``scene.options`` 的**模块属性**（``so.derive_target_options`` 等），
    这样 ``prove_red`` 用 monkeypatch 打断派生时能真的影响到本探针。
    """
    scene_on_path()
    import scene.options as so  # noqa: PLC0415
    from scene.config import FamilyConfig, member  # noqa: PLC0415
    from scene.lord_battle import FAMILY, LORD_BATTLE  # noqa: PLC0415

    cfg = LORD_BATTLE

    # (1) 选项数 == 成员数；选项名 == 成员行名（保持顺序）。
    cases = so.derive_target_options(cfg)
    if len(cases) != len(cfg.members):
        return False
    if [c["name"] for c in cases] != [m.行名 for m in cfg.members]:
        return False
    block = so.derive_option_block(cfg)
    if len(block["cases"]) != len(cases):
        return False

    # (2) 注入幂等：同一文本注入两次字节相同（ADR-0001）；且确实处在「已注入」态。
    once = so.inject_option(_SKELETON, cfg)
    twice = so.inject_option(once, cfg)
    if once != twice:
        return False
    if not so.verify_injection(once, cfg):
        return False

    # (3) 手改生成区 -> 漂移被抓（verify 必须为 False）。
    hand_edited = once.replace('"type": "select"', '"type": "selectX"', 1)
    if hand_edited == once:
        return False
    if so.verify_injection(hand_edited, cfg):
        return False

    # (4) 增删一个成员 -> 派生选项数随之变化（纯数据驱动，不改派生代码）。
    extra = member("领主战", "新成员·测试", "新成员·测试", ["初级"])
    added = FamilyConfig(
        family=FAMILY, members=[*cfg.members, extra], overrides=list(cfg.overrides)
    )
    removed = FamilyConfig(
        family=FAMILY, members=list(cfg.members[:-1]), overrides=list(cfg.overrides)
    )
    if len(so.derive_target_options(added)) != len(cfg.members) + 1:
        return False
    if len(so.derive_target_options(removed)) != len(cfg.members) - 1:
        return False

    return True


def prove_red() -> bool:
    """本票自带的破坏实验：derive 丢一个成员 -> 守卫必须变红。

    返回 ``True`` = 破坏实验成立（真实绿、破坏红）。不碰中央 prove-red 配方。
    """
    scene_on_path()
    import scene.options as so  # noqa: PLC0415

    real = so.derive_target_options

    def broken(cfg, *args, **kwargs):
        return real(cfg, *args, **kwargs)[:-1]  # 故意丢最后一个成员

    so.derive_target_options = broken  # type: ignore[assignment]
    try:
        red = probe_derive_gui_options() is False
    finally:
        so.derive_target_options = real  # type: ignore[assignment]
    green = probe_derive_gui_options() is True
    return green and red


HOOKS = [
    ("derive-gui-options", "#6", "N 个成员 -> derive 出的 GUI 选项恰 N 项", probe_derive_gui_options),
]
