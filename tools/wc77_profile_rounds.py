# -*- coding: utf-8 -*-
"""量「一轮为什么慢」：解析 MaaFramework 日志里的 Node.* 事件，按节点统计识别耗时与空转轮时长。

用法：python debug/wc77_profile_rounds.py [日志路径] [--top N]
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT = Path(r"debug/maafw.log")
LINE = re.compile(
    r"^\[(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\]\[(?P<lvl>[A-Z]{3})\]\[Px(?P<px>\d+)\]\[Tx(?P<tx>\d+)\]"
)
MSG = re.compile(r"\[msg=(?P<msg>[A-Za-z.]+)\]")
NODE = re.compile(r'"name":"(?P<name>[^"]+)"')
CUR = re.compile(r"\[cur_node_=(?P<cur>[A-Za-z0-9_]+)\]")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else DEFAULT
    top = 15
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])

    rec_start: dict[str, tuple[float, str]] = {}
    per_node: dict[str, list[float]] = defaultdict(list)
    cur_of_round: dict[int, str] = {}
    rounds: list[tuple[int, float, str]] = []   # (tx, ts, cur_node)
    pending_next: dict[int, float] = {}

    def parse_ts(s: str) -> float:
        hh, mm, rest = s.split(" ")[1].split(":")
        ss, ms = rest.split(".")
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0

    for raw in path.open(encoding="utf-8", errors="replace"):
        m = LINE.match(raw)
        if not m:
            continue
        ts = parse_ts(m.group("ts"))
        tx = m.group("tx")
        mm = MSG.search(raw)
        if not mm:
            continue
        msg = mm.group("msg")
        if msg == "Node.NextList.Starting":
            c = CUR.search(raw)
            rounds.append((int(tx), ts, c.group("cur") if c else "?"))
        elif msg == "Node.Recognition.Starting":
            nm = NODE.search(raw)
            if nm:
                rec_start[tx] = (ts, nm.group("name"))
        elif msg in ("Node.Recognition.Succeeded", "Node.Recognition.Failed"):
            started = rec_start.pop(tx, None)
            if started:
                per_node[started[1]].append(ts - started[0])

    # 同一节点的连续两轮之间 = 该节点「空转一轮」的真实代价
    by_cur: dict[str, list[float]] = defaultdict(list)
    for i, (_tx, ts, cur) in enumerate(rounds):
        if i + 1 < len(rounds):
            nxt = rounds[i + 1]
            if nxt[2] == cur:
                by_cur[cur].append(nxt[1] - ts)

    print(f"日志：{path}（{path.stat().st_size/1e6:.1f} MB）")
    print(f"识别事件节点数：{len(per_node)}；NextList 轮次：{len(rounds)}")
    print("\n== 每节点识别耗时（次数 / 中位 / p90 / 最长，秒）==")
    rows = []
    for name, ds in per_node.items():
        ds_sorted = sorted(ds)
        n = len(ds_sorted)
        med = ds_sorted[n // 2]
        p90 = ds_sorted[min(n - 1, int(n * 0.9))]
        rows.append((sum(ds_sorted) / n, name, n, med, p90, ds_sorted[-1]))
    for avg, name, n, med, p90, mx in sorted(rows, reverse=True)[:top]:
        print(f"  {name:32s} n={n:4d} avg={avg:6.3f} med={med:6.3f} p90={p90:6.3f} max={mx:6.3f}")

    print("\n== 同一节点「空转一轮」耗时（连续两轮起点差，秒）==")
    rows2 = []
    for cur, ds in by_cur.items():
        if len(ds) < 2:
            continue
        ds_sorted = sorted(ds)
        n = len(ds_sorted)
        rows2.append((ds_sorted[n // 2], cur, n, ds_sorted[-1]))
    for med, cur, n, mx in sorted(rows2, reverse=True)[:top]:
        print(f"  cur_node_={cur:28s} n={n:4d} med={med:6.2f}s max={mx:6.2f}s")


if __name__ == "__main__":
    main()
