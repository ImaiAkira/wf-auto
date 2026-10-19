# -*- coding: utf-8 -*-
"""租约 CLI 的契约（运维裁决：子代理也可以拿真机，但必须走租约 → CLI 必须能申请/释放）。

不连设备、不起子进程：只验参数解析、申请写入、持有者校验、释放语义。
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tools")]

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("== 租约 CLI：申请 / 持有者校验 / 释放 ==")
    # 用临时租约目录，别污染 debug/
    tmp = tempfile.mkdtemp(prefix="wf_lease_cli_")
    os.environ["WF_DEVICE_LEASE_DIR"] = tmp
    import importlib

    import device_lease as dl

    importlib.reload(dl)

    serial = "127.0.0.1:16384"
    # ① 参数解析
    opts = dl._parse_cli(["--serial", serial, "--acquire", "--owner", "agent:105", "--ttl", "33", "--hold", "0"])
    check("--acquire 解析", opts["acquire"] is True and opts["serial"] == serial)
    check("--owner/--ttl/--hold 解析", opts["owner"] == "agent:105" and opts["ttl"] == 33.0 and opts["hold"] == 0.0)
    opts2 = dl._parse_cli(["--serial", serial, "--release", "--owner", "agent:105"])
    check("--release 解析", opts2["release"] is True and opts2["owner"] == "agent:105")

    # ② 申请写入
    lease = dl.acquire(serial, "agent:105", ttl=60.0, wait=False)
    check("申请后能被 status 看到", any(r["serial"] == serial for r in dl.status()))
    check("持有者正确", dl.read_lease(serial).get("owner") == "agent:105")

    # ③ 别人申请：--no-wait 必须被拒（子代理要排队而不是硬闯）
    busy = False
    try:
        dl.acquire(serial, "agent:other", ttl=60.0, wait=False)
    except dl.LeaseBusy:
        busy = True
    check("被占时 wait=False 抛 LeaseBusy（会排队/报错，不硬闯）", busy)

    # ④ 持有者校验：别人的 owner 不能释放
    ok_wrong = dl.release_by_serial(serial, "agent:other")
    check("非持有者 release 被拒", ok_wrong is False and dl.read_lease(serial) is not None)
    # ⑤ 自己的 owner 能释放
    ok_own = dl.release_by_serial(serial, "agent:105")
    check("持有者 release 成功", ok_own is True and dl.read_lease(serial) is None)
    # ⑥ 幂等
    check("重复 release 幂等（False 不抛）", dl.release_by_serial(serial, "agent:105") is False)

    lease.release()
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("\nALL GREEN —— 子代理可以「申请 → 用 → 释放」真机")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
