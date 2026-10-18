# -*- coding: utf-8 -*-
"""便携路径：脱敏把本机绝对路径换成了字面量占位符 `<local>` / `<repo>`，那会让**代码里**
的默认值失效（最严重的是 `live_harness.ADB` —— 所有设备工具都找不到 adb）。

本模块提供**可执行**的替代：
- ``REPO_ROOT``  仓库根（本文件在 tools/ 下）
- ``TEMP_OPENCODE`` 临时工作目录（``%TEMP%/opencode``）
- ``find_adb()``  按 环境变量 → PATH → 常见安装位置 → 字面量 ``adb`` 的顺序找 adb
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMP_OPENCODE = Path(tempfile.gettempdir()) / "opencode"


def find_adb() -> str:
    """找 adb 可执行文件：显式环境变量 > PATH > 常见位置 > 字面量 ``adb``。

    ★为什么不是写死路径★：仓库要 public，不能带本机路径；但默认值又必须**可执行**，
    否则 `WF_LIVE_ADB` 没设时所有设备工具直接崩（脱敏时踩过这个坑）。
    """
    explicit = os.environ.get("WF_LIVE_ADB")
    if explicit:
        return explicit
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    candidates = [
        REPO_ROOT.parent / "ops" / "toolchain" / "platform-tools" / "adb.exe",
        REPO_ROOT / "platform-tools" / "adb.exe",
        # 系统盘符从环境读，不在源码里写死 `盘符:\目录\...`（脱敏 B 类）。
        Path(os.environ.get("SystemDrive", "C:") + "/platform-tools/adb.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return "adb"
