# -*- coding: utf-8 -*-
"""#2：一键离线入口的契约挂点（worked example，已点亮）。

守卫入口本身：任何控制台都给出确定退出码。挂点 ``entry-offline-signal``。
"""

from __future__ import annotations

from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
ENTRY = TOOLS_DIR / "run_all_tests.ps1"


def probe_entry_offline(path=None):
    """守卫本票的一键入口（UTF-8 强制 + 固定 CWD，缺一即红）。

    红是可用的信号，前提是入口在任何控制台都给出确定的退出码：强制 UTF-8，
    否则 GBK 控制台下子进程打印 emoji 会 UnicodeEncodeError；把子进程 CWD
    钉在仓库根，否则「在哪敲命令」会改变结果。传入 ``path`` 便于 --prove-red
    指向坏副本。
    """
    p = Path(path) if path else ENTRY
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8", errors="replace")
    return (
        "PYTHONIOENCODING" in text
        and "'utf-8'" in text
        and "CurrentDirectory" in text
    )


HOOKS = [
    ("entry-offline-signal", "#2", "一键入口在任意控制台给出确定退出码（UTF-8 + 固定 CWD）", probe_entry_offline),
]
