# -*- coding: utf-8 -*-
"""导航决策：``decide``（下一步节点 / 收工）+ ``navigate``（有界重试地走到目标）。

对应 ticket #4 / ADR-0002：**目标由配置声明，导航由引擎负责**。

* ``decide(配置, 当前页面, 目标场景)`` —— 纯函数：看到某个页面时，链上的**下一步节点**
  是什么；不可达（未知页面 / 未知成员 / 详情页难度门不过）则返回 ``收工``。
* ``navigate(...)`` —— 从任意已知页面出发，沿显式后继走到目标；目标行找不到时
  **有界重试**，上限内仍到不了就 ``收工``，绝不无限空转。

本模块不需要设备、不需要 maa 运行时：全部是页面标识上的纯函数。
"""

from __future__ import annotations

from dataclasses import dataclass

from .chain import (
    NODE_降临讨伐页签,
    NODE_详情,
    NODE_领主战页签,
    NODE_结算,
    Node,
    TERMINAL_归位,
    TERMINAL_收工,
    Terminal,
    build_chain,
    found_difficulties,
    resolve_target,
    结算终点,
    收工,
)
from .config import FamilyConfig

# 到达目标的判定页：把目标成员锁定、进入挑战（或已经在战斗 HUD）。
到达页面 = frozenset({"编队页", "战斗HUD"})

# 走链的硬上限：任何意料之外的自环都由它兜底收工（活性问题，不进事件层）。
_步数上限 = 200


def decide(
    cfg: FamilyConfig,
    当前页面: str,
    目标场景,
    发现难度集=None,
    *,
    目标次数: int | None = None,
    已打次数: int = 0,
) -> Node | Terminal:
    """给定当前页面与目标，返回链上的**下一步节点**；不可达返回 ``收工``（Terminal）。

    * 未知页面 → 收工（认不出的画面不兜底跳转）；
    * 目标解析不出来（成员不在配置 / 难度非法 / 子族不属于本 family）→ 收工；
    * 当前页面 = 详情页时，目标难度必须落在**详情页发现的可用难度集**内，
      否则收工（范围追加：难度由运行时发现，不是配置手写）；
    * 当前页面 = 结算页时（#22）：目标**已打满配置次数**（``已打次数 >= 目标次数``，
      即 pipeline 上 ``SpecialFightTargetRow.max_hit`` 用尽）→ ``收工``（落
      ``SpecialBatchStop``）；否则 ``归位``（通用事件，回主城继续）。缺省
      ``目标次数=None`` ＝ 不限次 → 恒为归位（既有行为不变）。
    """
    target = resolve_target(cfg, 目标场景)
    if target is None:
        return 收工("目标场景无法解析（成员不在配置 / 难度非法 / 子族不属于本 family）")

    chain = build_chain(cfg, target, 目标次数=目标次数, 已打次数=已打次数)
    node = chain.by_page(当前页面)
    if node is None:
        return 收工(f"未知页面：{当前页面!r}（不在链的已知页面上）")

    # #22 结算终点：打满配置次数 → 收工（说明里点名次数），否则归位回主城。
    if node.id == NODE_结算:
        return 结算终点(目标次数, 已打次数)

    if node.id == NODE_详情:
        可用 = found_difficulties(cfg, target, 发现难度集)
        if target.难度 not in 可用:
            return 收工(
                f"目标难度【{target.难度}】不在详情页发现的可用难度集内：{sorted(可用)}"
            )

    refs = node.下一步
    if not refs:
        return 收工(f"节点 {node.id!r} 没有显式后继")
    ref = refs[0]
    nxt = chain.node(ref)
    if nxt is not None:
        return nxt
    if ref == TERMINAL_归位:
        return Terminal(TERMINAL_归位, 到页面="主城", 原因="归位回主城")
    if ref == TERMINAL_收工:
        return 结算终点(目标次数, 已打次数)
    return 收工(f"未知后继：{ref!r}")


@dataclass(frozen=True)
class 导航结果:
    结局: str  # "到达" | "收工"
    路径: tuple[str, ...]
    原因: str = ""

    @property
    def 到达(self) -> bool:
        return self.结局 == "到达"


def navigate(
    cfg: FamilyConfig,
    目标场景,
    *,
    发现难度集=None,
    起始页面: str = "主城",
    可见行=None,
    重试上限: int | None = None,
    目标次数: int | None = None,
    已打次数: int = 0,
) -> 导航结果:
    """从 ``起始页面`` 出发走到目标。

    * ``可见行``：模拟列表页 OCR 能看到的行名集合。给了它且目标行名不在其中时，
      页签节点会**自恢复重试**（重滚列表），重试上限内找不到就收工 —— 这就是
      「目标不可达 → 有界重试 → 收工」。``None`` 表示假定目标行可见（正常路径）。
    * ``重试上限``：缺省取链上节点的最大重试上限。
    * ``目标次数`` / ``已打次数``（#22）：目标已打满配置次数时，从结算页出发的结局是
      ``收工``（不再「归位 → 主城 → 重进」）；缺省 ``目标次数=None`` = 不限次，行为不变。
    """
    target = resolve_target(cfg, 目标场景)
    if target is None:
        return 导航结果("收工", (起始页面,), "目标场景无法解析")

    chain = build_chain(cfg, target, 目标次数=目标次数, 已打次数=已打次数)
    if 起始页面 not in set(chain.页面集()):
        return 导航结果("收工", (起始页面,), f"未知页面：{起始页面!r}")

    bound = 重试上限 if 重试上限 is not None else max(n.重试上限 for n in chain.nodes)
    当前 = 起始页面
    路径: list[str] = [当前]
    重试: dict[str, int] = {}
    步 = 0

    while True:
        步 += 1
        if 步 > _步数上限:
            return 导航结果("收工", tuple(路径), "步数超过上限（不无限空转）")

        if 当前 in 到达页面:
            return 导航结果("到达", tuple(路径), "到达目标")

        node = chain.by_page(当前)

        # 列表页目标行认不出 → 自恢复重试（滚列表）直到上限，再收工。
        if (
            node is not None
            and node.id in (NODE_领主战页签, NODE_降临讨伐页签)
            and 可见行 is not None
            and target.行名 not in set(可见行)
        ):
            重试[当前] = 重试.get(当前, 0) + 1
            if 重试[当前] > bound:
                return 导航结果(
                    "收工",
                    tuple(路径),
                    f"目标行【{target.行名}】未找到（有界重试 {bound} 次后收工）",
                )
            continue  # 重试同一页面（重滚列表），不前进

        nxt = decide(
            cfg, 当前, target, 发现难度集=发现难度集,
            目标次数=目标次数, 已打次数=已打次数,
        )
        if isinstance(nxt, Terminal):
            if nxt.名称 == TERMINAL_收工:
                return 导航结果("收工", tuple(路径), nxt.原因)
            # 归位：回主城，链继续（可循环到目标）。
            路径.append(TERMINAL_归位)
            当前 = nxt.到页面
            路径.append(当前)
            continue

        当前 = nxt.页面
        路径.append(当前)
