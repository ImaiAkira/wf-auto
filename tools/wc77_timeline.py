# -*- coding: utf-8 -*-
"""打印某个时间窗内的节点事件时间线（带与上一事件的间隔），用来定位「一轮 10s 花在哪」。

用法：python debug/wc77_timeline.py <起HH:MM:SS> <止HH:MM:SS> [日志路径]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT = Path(r"debug/maafw.log")
LINE = re.compile(r"^\[(?P<ts>\d{4}-\d\d-\d\d (?P<hms>\d\d:\d\d:\d\d\.\d{3}))\]")
MSG = re.compile(r"\[msg=(?P<msg>[A-Za-z.]+)\]")
NODE = re.compile(r'"name":"(?P<name>[^"]+)"')
FOCUS = re.compile(r'"focus":(?:\{[^}]*"name":"(?P<focus>[^"]+)"|null)')
CUR = re.compile(r"\[cur_node_=(?P<cur>[A-Za-z0-9_]+)\]")


def main() -> None:
    lo, hi = sys.argv[1], sys.argv[2]
    path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT
    prev = None
    for raw in path.open(encoding="utf-8", errors="replace"):
        m = LINE.match(raw)
        if not m:
            continue
        hms = m.group("hms")
        if not (lo <= hms <= hi):
            continue
        mm = MSG.search(raw)
        if not mm:
            continue
        msg = mm.group("msg")
        if not (msg.startswith("Node.") or msg.startswith("Task.")):
            continue
        nm = NODE.search(raw)
        cur = CUR.search(raw)
        tag = nm.group("name") if nm else (cur.group("cur") if cur else "")
        hh, mi, rest = hms.split(":")
        ss, ms = rest.split(".")
        t = int(hh) * 3600 + int(mi) * 60 + int(ss) + int(ms) / 1000.0
        delta = "" if prev is None else f"+{t - prev:6.3f}s"
        prev = t
        print(f"{hms} {delta:>9} {msg:34s} {tag}")


if __name__ == "__main__":
    main()
