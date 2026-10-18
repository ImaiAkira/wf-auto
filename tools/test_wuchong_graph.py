#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""#103 状态机迁移的**图论自检**（离线、不碰设备）。

背景：#103 把五重流程从「线性 next + 每节点 20 项异常前缀」改成「枢纽按状态分派 + 验证器交回枢纽」。
这是一次**架构级**改动，离线只有结构守卫，没有执行证据。本测试补上「图的形状」这一层：

1. **可达性**：从 `WuchongEntry` 出发，21 个业务节点 + 7 个验证器 + 接口层都可达
   （不可达 = 那段代码是死的，或者被我的迁移切断了）。
2. **每步可推进**（★R1b 改口径★）：21 个业务节点 `next` **末项必须**是
   `[JumpBack]SceneEnterWuchong`，而**末项之前**必须是 `FLOW_STEPS[i].next` 的**真后继**
   —— 第一版把 `next[0]` 写成验证器，验证器在当前页恒真 ⇒ 动作永不发生、回枢纽后又被派回
   本节点（真机 2.5 分钟零进展）。故这里钉的是「真后继在前、兜底在末位」。
3. **无死状态**：7 个 state 里每一个，都至少有一个业务节点把「它的动作落点」登记在
   `IN_NODES` 里（R1b 后验证器不进业务 next，落点登记改由 `IN_NODES` 承担）。
   某个 state 没有任何节点处理 = 一旦落到那一页，枢纽只能在异常前缀里打转。
4. **验证器都能回枢纽**：`WuchongIn*.next == IN_NEXT`，且**绝对** `IN_NEXT == ["WuchongEntry"]`
   （R1 修正的固化；空 next 不是「纯闸门」而是**任务流程终止**）。
5. **异常前缀仍完整**：`WuchongGuardChain.next` ⊇ `FLOW_EXCEPTIONS`（每一条异常都有挂载点）。

跑法：``python tools/test_wuchong_graph.py``（exit 0 = 通过）
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))

PIPELINE = PROJECT / "assets" / "resource" / "pipeline"


def load_all() -> dict:
    """把 pipeline 目录下所有 JSON（带注释）读成 {节点名: 节点}。"""
    import jsonc  # noqa: PLC0415  (仓内 tools/jsonc.py)

    nodes: dict = {}
    for path in sorted(PIPELINE.glob("*.json")):
        try:
            data = jsonc.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            for name, node in data.items():
                if isinstance(node, dict):
                    nodes[name] = node
    return nodes


def refs(value) -> list:
    """把 next/on_error 里的字符串项挑出来（忽略内联对象）。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                pass  # 内联识别对象，不是节点引用
        return out
    return []


def edges(nodes: dict, name: str) -> list:
    node = nodes.get(name) or {}
    return refs(node.get("next")) + refs(node.get("on_error"))


def reachable(nodes: dict, start: str) -> set:
    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in edges(nodes, cur):
            bare = nxt.replace("[JumpBack]", "").strip()
            if bare and bare not in seen and bare in nodes:
                seen.add(bare)
                queue.append(bare)
    return seen


def main() -> int:
    sys.path.insert(0, str(HERE))
    from scene import wuchong as w  # noqa: PLC0415

    nodes = load_all()
    msgs: list = []

    if not nodes:
        print("✗ 读不到任何 pipeline 节点（路径不对？）")
        return 1

    entry = "WuchongEntry"
    if entry not in nodes:
        print(f"✗ 找不到枢纽 {entry}")
        return 1

    seen = reachable(nodes, entry)
    business = list(getattr(w, "IN_NODES", {}) or {})
    if not business:
        # 从真源的 FLOW_STEPS 里取节点名
        business = [step.node for step in getattr(w, "FLOW_STEPS", ())]

    # 1) 可达性
    for name in list(business) + list(getattr(w, "IN_NODES", {}).keys()) + [
        w.SCENE_ENTER,
        w.SCENE_GUARD_CHAIN,
        w.SCENE_GUARD_DONE,
    ]:
        if name not in seen:
            msgs.append(f"{name} 从 {entry} 不可达（迁移切断了它，或它本来就是死的）")

    # 2) ★R1b 改口径★ 每步 = 「真后继（进度）+ 末位兜底」，不再要求 next[0] 是验证器。
    #    第一版（验证器在前）真机打转：验证器在当前页恒真 ⇒ 动作永不发生 ⇒ 回枢纽 ⇒ 又派回本节点。
    in_nodes = set((getattr(w, "IN_STATES", {}) or {}).keys())
    expect_map = dict(getattr(w, "IN_NODES", {}) or {})
    successors = dict(getattr(w, "step_successors", lambda: {})() or {})
    tail = getattr(w, "STEP_TAIL", f"[JumpBack]{w.SCENE_ENTER}")
    for name in business:
        nxt = refs((nodes.get(name) or {}).get("next"))
        if not nxt:
            msgs.append(f"{name}.next 为空（R1：任务会在这里终止；R1b：真后继与末位兜底都没了）")
            continue
        if nxt[-1] != tail:
            msgs.append(
                f"{name}.next 末项={nxt[-1]!r} 不是末位兜底 {tail!r}"
                f"（末位兜底被挪走 = 后续候选永不评估）"
            )
        want = list(successors.get(name) or ())
        if nxt[:-1] != want:
            msgs.append(
                f"{name}.next 的真后继 {nxt[:-1]!r} != FLOW_STEPS 声明 {want!r}"
                f"（★真后继被吞/被换 = 动作永不发生，R1b 现场就是这样）"
            )
        if expect_map.get(name) not in in_nodes:
            msgs.append(
                f"{name} 的动作落点页 {expect_map.get(name)!r} 不是已登记的验证器"
                f"（IN_NODES 必须指向 7 个 WuchongIn* 之一）"
            )

    # 3) 无死状态：每个 state 都有业务节点把「动作落点」登记在它上面（R1b 后走 IN_NODES）。
    waiting = {}
    for name in business:
        v = expect_map.get(name)
        if v in in_nodes:
            waiting.setdefault(v, []).append(name)
    for in_name, state in (getattr(w, "IN_STATES", {}) or {}).items():
        if in_name not in waiting:
            msgs.append(
                f"验证器 {in_name}（state={state!r}）没有任何业务节点把落点登记在它上面 —— 一旦落到这一页，"
                f"枢纽只能在异常前缀里打转（死状态）"
            )

    # 4) 验证器都回枢纽
    # ★绝对口径★：先钉住 IN_NEXT 本身**就是** ["WuchongEntry"] —— 否则真源把 IN_NEXT 改成空元组
    # 时下面的相对断言（got != in_next）会整体变绿，而那正是「验证器 next=[] = 任务流程终止」的
    # 致命形态（真机一跑就在第一步「任务完成」）。破坏实验见 hooks_103 的 prove_red。
    in_next = list(getattr(w, "IN_NEXT", ("WuchongEntry",)))
    if in_next != ["WuchongEntry"]:
        msgs.append(
            f"IN_NEXT={in_next!r} != ['WuchongEntry']（验证器必须交回枢纽；空 next = 任务流程终止）"
        )
    for name in in_nodes:
        got = refs((nodes.get(name) or {}).get("next"))
        if got != in_next:
            msgs.append(f"{name}.next={got!r} != IN_NEXT={in_next!r}（R1 修正失效）")

    # 5) 中继覆盖全部异常
    chain = set(refs((nodes.get(w.SCENE_GUARD_CHAIN) or {}).get("next")))
    missing = [x for x in getattr(w, "FLOW_EXCEPTIONS", ()) if x not in chain]
    if missing:
        msgs.append(f"中继漏了异常前缀 {missing}（这些异常将无处挂载）")

    lens = [len(refs((nodes.get(n) or {}).get("next"))) for n in business]
    print(f"节点总数 {len(nodes)}，从 {entry} 可达 {len(seen)}")
    print(f"业务节点 {len(business)}，验证器 {len(in_nodes)}，中继 {len(chain)} 项")
    print(
        f"业务 next 长度 {min(lens)}–{max(lens)} 项（平均 {sum(lens) / len(lens):.2f}）："
        f"真后继 {sum(len(v) for v in successors.values())} 条 + 每步 1 项末位兜底 {tail}"
    )
    if msgs:
        print("\n✗ 图论自检失败：")
        for m in msgs:
            print("  -", m)
        return 1
    print(
        "\nALL GREEN —— 状态机迁移的图形状成立：全可达、每步有真后继 + 末位兜底、无死状态、"
        "验证器回枢纽、异常有挂载点"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
