# -*- coding: utf-8 -*-
"""#4：链式拓扑（页面驱动主路径 + 导航决策）的契约挂点。

对应 ADR-0002（目标声明式导航）/ ADR-0003（页面判据全局唯一）。已点亮：

* ``chain-page-anchored`` —— 链上每个节点锚在一个【全局页面判据】上，且
  「页面 → 节点」是一一对应（每页恰好一个锚点），链的页面集 = family 页序 = 全局判据集；
* ``decide-next-node``    —— 给定当前页面 + 目标 → 期望的显式后继节点（含页签分支、
  错页签自恢复、详情页难度门、结算→归位、不可达→收工、有界重试→收工）。

破坏实验（红 = 可用信号）在 ``tools/test_scene_chain.py --prove-red``：它复制一份
``scene`` 包、施加一处破坏、再用子进程重跑本文件的两个探针，要求变红。本 lane **不**改
中央的 prove-red 配方清单（``test_offline_contract.py`` 归另一条 lane），故把破坏步骤放在
本 lane 自己的测试文件里。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】。

    放末尾是有意的：prove-red 会在子进程里用 PYTHONPATH 指向一份坏掉的 ``scene`` 副本
    （其位置在 sys.path 里更靠前），这里的真实仓库根不会把它盖掉。
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def probe_chain_page_anchored():
    """#4：页面驱动 —— 每个节点锚在全局页面判据上，且每页恰好一个锚点。"""
    scene_on_path()
    from scene.chain import build_chain, page_names, validate_chain, _占位目标  # noqa: PLC0415
    from scene.lord_battle import FAMILY, LORD_BATTLE  # noqa: PLC0415

    cfg = LORD_BATTLE
    if validate_chain(cfg):  # 页面解析 / 唯一锚点 / 页序覆盖 / 后继可解析
        return False

    chain = build_chain(cfg, _占位目标(cfg))
    pages = chain.页面集()
    names = page_names()

    # 每个节点的页面都是全局注册表里的一条（引用而非复制；ADR-0003）。
    if any(p not in names for p in pages):
        return False
    # 每页恰好一个锚点（否则 decide 不可能是页面上的纯函数）。
    if len(set(pages)) != len(pages):
        return False
    # 链的页面集 = family 页序 = 全局判据集（主路径覆盖全部已知页面）。
    if set(pages) != set(FAMILY.页序):
        return False
    if set(pages) != names:
        return False
    return True


def probe_decide_next_node():
    """#4：给定当前页面 + 目标 → 期望的显式后继节点（不可达 → 收工）。"""
    scene_on_path()
    from scene import chain as C  # noqa: PLC0415
    from scene.chain import build_chain, resolve_target  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415
    from scene.navigation import decide, navigate  # noqa: PLC0415

    cfg = LORD_BATTLE
    lord = {"成员": "猩红巨熊讨伐", "难度": "高级"}
    joss = {"成员": "苍叹机兵", "难度": "超级"}

    # (1) 每个已知页面的后继正确（领主战目标，正常主路径）。
    期望 = {
        "主城": C.NODE_列表,
        "领主战列表页": C.NODE_领主战页签,
        "领主战页签": C.NODE_详情,
        "详情页": C.NODE_模式,
        "模式选择页": C.NODE_加成,
        "加成弹窗": C.NODE_编队,
        "编队页": C.NODE_战斗,
        "战斗HUD": C.NODE_结算,
    }
    for page, want in 期望.items():
        got = decide(cfg, page, lord)
        if not isinstance(got, C.Node) or got.id != want:
            return False

    # (2) 页签由目标子族决定；错页签自恢复回列表页。
    if decide(cfg, "领主战列表页", joss).id != C.NODE_降临讨伐页签:
        return False
    if decide(cfg, "降临讨伐页签", joss).id != C.NODE_详情:
        return False
    if decide(cfg, "降临讨伐页签", lord).id != C.NODE_列表:
        return False

    # (3) 详情页难度门：目标难度必须落在【发现的】可用难度集内。
    ok = decide(cfg, "详情页", lord, 发现难度集={"初级", "中级", "高级"})
    if not isinstance(ok, C.Node) or ok.id != C.NODE_模式:
        return False
    bad = decide(cfg, "详情页", lord, 发现难度集={"初级", "中级"})
    if not (isinstance(bad, C.Terminal) and bad.名称 == "收工"):
        return False

    # (4) 结算 → 归位（通用事件）；未知页面 / 未知成员 → 收工。
    settle = decide(cfg, "结算页", lord)
    if not (isinstance(settle, C.Terminal) and settle.名称 == "归位"):
        return False
    if decide(cfg, "根本不存在的页面", lord).名称 != "收工":
        return False
    if decide(cfg, "主城", {"成员": "不存在的成员", "难度": "高级"}).名称 != "收工":
        return False

    # (5) 从任意已知页面出发都能到达目标（含模式选择 / 加成弹窗两步）。
    target = resolve_target(cfg, joss)
    chain = build_chain(cfg, target)
    for page in chain.页面集():
        if navigate(cfg, joss, 起始页面=page).结局 != "到达":
            return False

    # (6) 目标行认不出 → 有界重试后收工（不无限空转）。
    r = navigate(cfg, lord, 可见行=set())
    if r.结局 != "收工" or len(r.路径) > 20:
        return False
    # 难度不在发现集内 → 不可达 → 收工。
    if navigate(cfg, lord, 发现难度集={"初级"}).结局 != "收工":
        return False
    return True


HOOKS = [
    ("chain-page-anchored", "#4", "链上每个节点锚在一个页面上", probe_chain_page_anchored),
    ("decide-next-node", "#4", "给定当前页面 + 目标 -> 期望的显式后继节点", probe_decide_next_node),
]
