# -*- coding: utf-8 -*-
"""#104 + #98 的 runner 集成契约（静态断言，不连设备、不起进程）。

为什么要有这个测试：租约与监管都是「基础设施」，一旦被谁改掉一行（少传 steal / 少起监管 /
少了退出时的小结），真机长跑出问题时排查成本极高。这里把它钉成文本契约。
"""

from __future__ import annotations

import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNNER = REPO / "tools" / "run_wuchong_live.py"
HARNESS = REPO / "tools" / "live_harness.py"

FAILS: list[str] = []


def check(name: str, ok: bool, msg: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {msg}" if msg and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    src = RUNNER.read_text(encoding="utf-8-sig")
    ast.parse(src)
    harness = HARNESS.read_text(encoding="utf-8-sig")

    check("runner 能解析（BOM 已处理）", True)
    check("runner 有 --steal 参数（D9：默认排队，显式抢）", "--steal" in src)
    check("runner 把 steal 传给 connect_device", 'steal=bool(getattr(a, "steal", False))' in src)
    check("runner 有 --monitor 参数（#98）", "--monitor" in src)
    check("runner 会起长跑监管", "monitor_for_serial" in src and "_mon.start()" in src)
    check("监管退出时停线程并打小结", "_atexit.register(_mon_stop_and_summary)" in src and "summary.as_line()" in src)
    # ★Q1★ --as-gui 等价验收模式
    check("runner 有 --as-gui（用 install/resource）", "--as-gui" in src and "install" in src)
    check("--as-gui 会核对 install/agent 是否落后（Q1 那条差异）", "install/agent 与仓库不一致" in src)
    check("--as-gui 会开静音（等同 GUI 的 --quiet）", "set_quiet(True)" in src)
    check("harness 连设备前拿租约", "_acquire_device_lease" in harness)
    check("harness 连不上/抛错会还租（不霸占）", "release_device_lease" in harness)
    check("harness 进程退出兜底释放（atexit / TTL）", "atexit" in harness)

    if FAILS:
        print(f"\nFAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("\nALL GREEN —— 租约与监管的 runner 集成契约成立")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
