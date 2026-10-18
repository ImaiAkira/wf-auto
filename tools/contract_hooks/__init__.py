# -*- coding: utf-8 -*-
"""按票分文件的挂点注册表 + 自动发现聚合器（#15）。

契约：本目录下每个 ``hooks_<票号>.py`` 是**一张票**的挂点文件，导出
``HOOKS``（``(hook_id, ticket, 说明, probe)`` 的列表）。

聚合器只做「扫目录 + 逐个导入」，**不维护任何手写模块清单** —— 新增一张票 =
新建一个 ``hooks_<票号>.py``，零改既有文件（这正是并行 lane 不撞车的前提）。

发现唯一入口是 :func:`discover_hooks`：

* **不缓存**：每次重新扫盘、重新导入，因此「刚新建的文件」当场可见
  （归一性守卫 ``aggregator-discovers-new-file`` 正是靠这一点自证）；
* **导入报错不吞**：抛出去让套件红，绝不静默丢一张票的挂点。

对应 ADR-0001（配置为真源）/ ADR-0002（目标声明式导航）/ ADR-0003（页面判据全局唯一）。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
MODULE_GLOB = "hooks_*.py"

_NUM = re.compile(r"(\d+)")


def _sort_key(path: Path):
    """按文件名里的票号自然排序（``hooks_2`` < ``hooks_10`` < ``hooks_15``）。"""
    match = _NUM.search(path.stem)
    return (int(match.group(1)) if match else 10**9, path.stem)


def iter_hook_files():
    """按票号排序，返回本目录下所有 ``hooks_*.py``。"""
    return sorted(
        (p for p in HOOKS_DIR.glob(MODULE_GLOB) if p.is_file()),
        key=_sort_key,
    )


def _load_module(path: Path):
    """把 ``path`` 当独立模块执行（不写入 sys.modules，支持反复发现新文件）。"""
    spec = importlib.util.spec_from_file_location(f"_contract_hook_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法导入挂点模块：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_hooks():
    """扫描 HOOKS_DIR，聚合所有 ``hooks_*.py`` 导出的 ``HOOKS``。

    导入失败或模块缺 ``HOOKS`` 都会抛异常（套件因此变红），而不是静默跳过。
    """
    hooks = []
    for path in iter_hook_files():
        module = _load_module(path)
        module_hooks = getattr(module, "HOOKS", None)
        if module_hooks is None:
            raise AttributeError(f"挂点模块缺少 HOOKS：{path.name}")
        hooks.extend(module_hooks)
    return hooks


def scan_hook_ids():
    """**独立于 discover_hooks** 的核对：直接按约定名扫盘并加载，返回全部 hook_id。

    为什么要独立一份：守卫 ``aggregator-discovers-new-file`` 本身也是一个挂点文件，
    一旦有人把 ``discover_hooks`` 换成手写清单并把该守卫模块漏掉，守卫就跑不起来了
    （in-band 守卫管不到自己被丢掉的场景）。这里的扫盘只依赖 ``iter_hook_files`` /
    ``_load_module``，不看 ``discover_hooks`` 的结果，因此入口可以拿它跟聚合结果对账，
    任何「手写清单少加载了某票文件」都会当场暴露。
    """
    ids = []
    for path in iter_hook_files():
        module = _load_module(path)
        module_hooks = getattr(module, "HOOKS", None)
        if module_hooks is None:
            raise AttributeError(f"挂点模块缺少 HOOKS：{path.name}")
        ids.extend(hook_id for hook_id, _t, _w, _p in module_hooks)
    return ids
