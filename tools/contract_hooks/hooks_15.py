# -*- coding: utf-8 -*-
"""#15：归一性守卫 —— 证明「新增挂点 = 新建一个文件，零改既有文件」。

为什么需要它：把 HOOKS 拆成按票分文件后，最大的风险是未来某条 lane 图省事，
把聚合器改回**手写模块清单** —— 那一刻并行的前提就没了，而套件仍会全绿。

机制（最便宜且诚实，不依赖任何手写清单）：往真实的挂点目录里临时新建一个
符合约定（``hooks_*.py``）的模块，其中含一个可识别 id 的探针挂点；**重新跑一遍
自动发现**，断言那个新挂点当场出现；随后删掉临时文件。因此：

* 聚合器改成手写清单 -> 新文件不被发现 -> 断言不成立 -> 红；
* 约定名被改坏（例如发现用 ``hook_*.py`` 而票文件是 ``hooks_*.py``）-> 临时文件
  同样落不到发现范围 -> 红；
* 上一轮崩溃残留下临时文件 -> 发现前就存在 -> 也判红（把脏状态暴露出来）。

写盘 → 发现 → 删除都在 ``try/finally`` 内，正常跑完工作树不变。
"""

from __future__ import annotations

import os

from contract_hooks import HOOKS_DIR, discover_hooks

_PROBE_HOOK_ID = "__collision_probe_should_be_discovered__"


def probe_no_collision():
    """新建一个 ``hooks_*.py`` 即被自动发现（聚合器非手写清单）。"""
    before = {h[0] for h in discover_hooks()}
    if _PROBE_HOOK_ID in before:
        # 上一次异常退出残留了临时文件 —— 脏状态本身就是红。
        return False

    tmp = HOOKS_DIR / f"hooks___collision_probe_{os.getpid()}.py"
    body = (
        "# -*- coding: utf-8 -*-\n"
        "# 由 hooks_15.probe_no_collision 临时写入，运行后即删（归一性守卫自证用）。\n"
        "def _probe():\n"
        "    return True\n\n"
        "HOOKS = [\n"
        f"    ({_PROBE_HOOK_ID!r}, '#15', '临时探针：新建文件即被发现', _probe),\n"
        "]\n"
    )
    try:
        tmp.write_text(body, encoding="utf-8")
        after = {h[0] for h in discover_hooks()}
        return _PROBE_HOOK_ID in after
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


HOOKS = [
    ("aggregator-discovers-new-file", "#15",
     "新增一个 hooks_*.py 即被自动发现（聚合器靠发现，非手写清单）", probe_no_collision),
]
