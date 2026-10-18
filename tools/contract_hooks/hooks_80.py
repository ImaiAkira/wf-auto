# -*- coding: utf-8 -*-
"""#84：全仓 `max_hit` 扫描守卫（ratchet）—— 任务级计数不许再被当成「每回合限次」。

## 为什么

MAA 的 `max_hit` 是**整个任务共享**的计数器，用光后节点**静默跳过**（不报错、不打印）。
真机事故（#79）：`WuchongRecruitOpen max_hit: 3` → 打 3 把后第 4 间房起再也不招募 → 房里干等 302s 收工，
运维看到的就是「打了几把画面卡死」。

全仓普查（#80 正文）同类误用还有一批：`special_dungeon` 招募 5 个 `max_hit: 1`（幻想连战共斗只有第一间房能开）、
`common` 的登录/标题 3 次、`SideBack: 3`、`FarmScroll: 10` …

## 这道守卫怎么工作（ratchet，只收紧不放宽）

1. 扫 `assets/resource/pipeline/*.json`，收集所有带 `max_hit` 的节点；
2. 允许两种豁免：
   - 节点注释里写了 `max_hit-reason: <为什么一局只该发生一次>`（就地说明，最优先）；
   - 在 `tools/max_hit_baseline.json` 的 `reasoned` / `debt` 里登记过（debt = 已知欠账，待 #80 清）；
3. 以下任一情况**变红**：
   - 出现**没登记也没写理由**的 `max_hit`（新增误用）；
   - 基线里的节点**已经没有** `max_hit`（基线陈旧 —— 必须同步删，逼着账目只减不增）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
BASELINE = REPO_ROOT / "tools" / "max_hit_baseline.json"

NODE_HEAD = re.compile(r'^    "(?P<name>[A-Za-z0-9_]+)": \{', re.M)


def _node_blocks(raw: str) -> dict:
    """把 JSONC 原文切成 {节点名: 该节点的原文块}（块 = 从节点头到下一个节点头）。"""
    heads = list(NODE_HEAD.finditer(raw))
    blocks: dict = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw)
        blocks[m.group("name")] = raw[m.start():end]
    return blocks


def _inventory() -> dict:
    """{节点名: (文件, max_hit, 是否有 max_hit-reason 注释)}。"""
    import jsonc  # noqa: PLC0415

    out: dict = {}
    for path in sorted(PIPELINE_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        blocks = _node_blocks(raw)
        with open(path, encoding="utf-8") as f:
            data = jsonc.load(f)
        for name, node in (data or {}).items():
            if not isinstance(node, dict) or "max_hit" not in node:
                continue
            block = blocks.get(name, "")
            out[name] = (path.name, node["max_hit"], "max_hit-reason:" in block)
    return out


def _baseline() -> tuple[dict, dict]:
    with open(BASELINE, encoding="utf-8") as f:
        data = json.load(f)
    return dict(data.get("reasoned") or {}), dict(data.get("debt") or {})


def failures() -> list:
    """Ratchet 判定：返回违规列表（空 = 绿）。"""
    msgs: list[str] = []
    inv = _inventory()
    reasoned, debt = _baseline()
    known = set(reasoned) | set(debt)

    for name, (fname, value, has_reason) in sorted(inv.items()):
        if has_reason or name in known:
            continue
        msgs.append(
            f"{fname}::{name} 带了未登记的 max_hit={value!r}（任务级计数，用光即静默跳过）——"
            "要么改成时间闩锁 / 每 episode 计数，要么在 tools/max_hit_baseline.json 登记理由"
        )

    for name in sorted(known - set(inv)):
        msgs.append(
            f"基线陈旧：{name} 已不再带 max_hit，请从 tools/max_hit_baseline.json 删掉这一条"
            "（ratchet 只减不增，账目必须诚实）"
        )
    return msgs


def probe_maxhit_ratchet() -> bool:
    return failures() == []


HOOKS = [
    (
        "pipeline-no-unregistered-maxhit",
        "#84",
        "全仓 max_hit ratchet：带 max_hit 的节点必须「注释里写 max_hit-reason:」或「在 tools/max_hit_baseline.json 登记」；"
        "基线陈旧（节点已无 max_hit）也红 —— 任务级计数不许再被当成「每回合限次」（#79 真机：3 把后卡房 302s）",
        probe_maxhit_ratchet,
    ),
]


# ---------------------------------------------------------------------------
def prove_red() -> bool:
    print("hooks_80 prove-red：逐一破坏实现，要求守卫各自变红")
    msgs = failures()
    green = len(msgs) == 0
    reasoned, debt = _baseline()
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：守卫全绿（基线债务 {len(debt)} 条，待 #80 清）")
    if not green:
        for m in msgs[:5]:
            print(f"      - {m}")
        return False

    checks: list[bool] = []
    inv = _inventory()
    orig_inventory = _inventory

    # ① 新增一个未登记、无理由的 max_hit（模拟「又有人把 max_hit 当限次用」）
    try:
        import hooks_80 as self_mod  # noqa: PLC0415

        poisoned = dict(inv)
        poisoned["WuchongTeamChallenge"] = ("wuchong.json", 3, False)
        self_mod._inventory = lambda: poisoned
        m1 = self_mod.failures()
        red1 = any("WuchongTeamChallenge" in x for x in m1)
        print(f"  [{'PASS' if red1 else 'FAIL'}] 给 WuchongTeamChallenge 塞一个未登记的 max_hit -> {'红' if red1 else '仍绿'}")
        checks.append(red1)
    finally:
        self_mod._inventory = orig_inventory

    # ② 基线陈旧：登记一个其实没有 max_hit 的节点
    try:
        import hooks_80 as self_mod  # noqa: PLC0415

        stale_reasoned = dict(reasoned)
        stale_reasoned["WuchongRoomWait"] = "假的：这个节点根本没有 max_hit"
        self_mod._baseline = lambda: (stale_reasoned, debt)
        m2 = self_mod.failures()
        red2 = any("基线陈旧" in x and "WuchongRoomWait" in x for x in m2)
        print(f"  [{'PASS' if red2 else 'FAIL'}] 基线里塞一条已不存在的 max_hit 节点 -> {'红' if red2 else '仍绿'}")
        checks.append(red2)
    finally:
        self_mod._baseline = lambda: (reasoned, debt)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
