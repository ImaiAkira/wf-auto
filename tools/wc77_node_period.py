# -*- coding: utf-8 -*-
"""列出某个 pipeline 节点每次被「进入」的时刻与间隔（真实重复周期），跨所有 maafw 日志。

用法：python debug/wc77_node_period.py NodeName [NodeName ...]
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

LINE = re.compile(r"^\[(?P<ts>\d{4}-\d\d-\d\d (?P<hms>\d\d:\d\d:\d\d\.\d{3}))\]")
MSG = re.compile(r"\[msg=Node\.PipelineNode\.Starting\]")
NAME = re.compile(r'"name":"(?P<name>[^"]+)"')


def ts_of_hms(hms: str) -> float:
    hh, mi, rest = hms.split(":")
    ss, ms = rest.split(".")
    return int(hh) * 3600 + int(mi) * 60 + int(ss) + int(ms) / 1000.0


def main() -> None:
    want = set(sys.argv[1:])
    files = [Path("debug/maafw.log")] + [Path(p) for p in sorted(glob.glob("debug/maafw.bak.*.log"))]
    hits: dict[str, list[tuple[str, float]]] = {n: [] for n in want}
    for f in files:
        if not f.exists():
            continue
        for raw in f.open(encoding="utf-8", errors="replace"):
            if "PipelineNode.Starting" not in raw:
                continue
            m = LINE.match(raw)
            if not m:
                continue
            mm = MSG.search(raw)
            if not mm:
                continue
            nm = NAME.search(raw)
            if not nm or nm.group("name") not in want:
                continue
            hits[nm.group("name")].append((f"{m.group('hms')}", ts_of_hms(m.group("hms"))))
    for name, rows in hits.items():
        if not rows:
            print(f"{name}: 日志里没有")
            continue
        print(f"\n== {name}：{len(rows)} 次 ==")
        for i, (hms, t) in enumerate(rows):
            delta = "" if i == 0 else f"  (+{t - rows[i - 1][1]:.2f}s)"
            if i < 8 or i >= len(rows) - 6:
                print(f"  {hms}{delta}")
            elif i == 8:
                print("  ...")


if __name__ == "__main__":
    main()
